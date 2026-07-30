"""
engine.py
=========

Speech-to-text transcription engine for Doctor Voice Notes.

Covers PRD:
  FR-01 (load speech recognition model at launch)
  FR-03 (real-time transcription, handle natural pauses)
  FR-04 (feeds text to the live editor - UI side is Phase 6)
  FR-07 (finish remaining transcription when Stop is pressed)
  Section 14 (model load failure -> display error and TERMINATE;
              a single failed phrase -> log and continue, do not crash)
  Section 15 (no internet communication, ever)
  Section 7  (CPU/memory budget, 2+ hour sessions)

IMPORTANT REALITY CHECK (see chat message for full explanation)
------------------------------------------------------------------
faster-whisper is a BATCH transcriber, not a streaming one - it cannot
emit words as they are spoken. This engine instead detects when the
doctor pauses (using voice activity detection) and transcribes each
"phrase" as a unit once it is complete. Realistic latency is therefore
1-4 seconds per phrase, not sub-second. This is a hard limitation of the
offline/CPU-only architecture, not a bug to be optimised away.

THREADING MODEL (how this fits together with recorder.py)
------------------------------------------------------------
  - PortAudio's own thread (managed by sounddevice, see recorder.py)
    pushes captured audio blocks into AudioRecorder's internal queue.
  - A background thread (started by the caller, e.g. main.py in Phase 7)
    runs TranscriptionEngine.transcribe_stream(), which pulls blocks from
    the recorder, groups them into phrases, transcribes each phrase, and
    pushes recognised text onto `output_queue`.
  - The main Tkinter thread (Phase 6) polls `output_queue` periodically
    (via widget.after()) to update the on-screen transcript.
This engine class itself does NOT spawn threads - it is the CALLER's job
to run transcribe_stream() in a background thread. Keeping thread
management out of this class keeps it simple to test (see engine tests).
"""

import collections
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import webrtcvad
from faster_whisper import WhisperModel

from src.audio.recorder import TARGET_SAMPLE_RATE, BLOCK_DURATION_MS, resample_audio
from src.utils.logger import get_logger

logger = get_logger(__name__)

# The exact number of samples every 30ms/16kHz block must have. webrtcvad
# hard-rejects any frame that isn't exactly this length, so every code path
# that feeds it audio must guarantee this - see _ensure_target_rate().
EXPECTED_BLOCK_SAMPLES = int(TARGET_SAMPLE_RATE * BLOCK_DURATION_MS / 1000)  # 480


class ModelLoadError(Exception):
    """
    FATAL error - the speech model could not be loaded.
    Per PRD Section 14, the caller must display an error message to the
    doctor and TERMINATE the application. Do not attempt to continue
    running without a working model - there is nothing useful the app can
    do without it.
    """
    pass


class TranscriptionError(Exception):
    """
    Raised internally when a single phrase fails to transcribe. Callers of
    this module generally will not see this directly - _transcribe_segment
    catches it, logs it, calls on_error if provided, and the session
    continues (PRD Section 14: prevent crash whenever possible).
    """
    pass


class PhraseSegmenter:
    """
    Groups a continuous stream of 30ms audio blocks into complete
    "phrases" (speech bounded by silence), using WebRTC's voice activity
    detector to decide where speech starts and stops.

    This is the standard ring-buffer VAD segmentation pattern: while not
    triggered, watch a rolling window of recent frames for a burst of
    speech to START a phrase; while triggered, watch for a sustained
    stretch of silence to END it. A max-duration safety valve prevents an
    uninterrupted monologue from delaying transcription indefinitely.
    """

    def __init__(
        self,
        vad: Optional[object] = None,
        sample_rate: int = TARGET_SAMPLE_RATE,
        frame_duration_ms: int = BLOCK_DURATION_MS,
        aggressiveness: int = 2,
        padding_duration_ms: int = 600,
        max_segment_duration_s: float = 15.0,
    ):
        """
        Args:
            vad: an object with an is_speech(bytes, sample_rate) method.
                 Defaults to a real webrtcvad.Vad instance. Accepting one
                 as a parameter (dependency injection) is what lets the
                 automated tests verify this class's state machine using a
                 controlled, predictable fake instead of relying on a real
                 audio classifier's probabilistic behaviour.
            aggressiveness: webrtcvad mode 0 (least aggressive filtering
                 of non-speech) to 3 (most aggressive). 2 is a reasonable
                 default for a clinical office (some background noise,
                 but usually one clear speaker).
            padding_duration_ms: how much continuous silence, after
                 speech, marks the end of a phrase. 600ms is roughly the
                 length of a natural mid-sentence breath pause, chosen so
                 the doctor is not cut off mid-thought, while sentence
                 boundaries still resolve reasonably quickly.
            max_segment_duration_s: hard cap on phrase length even without
                 a pause. Prevents both unbounded latency AND unbounded
                 memory growth if the doctor talks continuously for a long
                 time without pausing (PRD Sec. 7).
        """
        self.vad = vad if vad is not None else webrtcvad.Vad(aggressiveness)
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms

        num_padding_frames = max(1, int(padding_duration_ms / frame_duration_ms))
        self.ring_buffer: "collections.deque" = collections.deque(maxlen=num_padding_frames)

        self.triggered = False
        self.voiced_frames: list[np.ndarray] = []
        self.max_segment_frames = int(max_segment_duration_s * 1000 / frame_duration_ms)

    def process(self, block: np.ndarray) -> Optional[np.ndarray]:
        """
        Feed one audio block (exactly EXPECTED_BLOCK_SAMPLES int16 samples).

        Returns:
            A concatenated np.ndarray containing one complete phrase, if
            this block was the one that completed it (silence detected, or
            max duration reached). Otherwise None (still accumulating, or
            still waiting for speech to begin).
        """
        is_speech = self.vad.is_speech(block.tobytes(), self.sample_rate)

        if not self.triggered:
            self.ring_buffer.append((block, is_speech))
            num_voiced = len([f for f, speech in self.ring_buffer if speech])
            # Require the ring buffer to be FULL (not just started) and
            # mostly voiced before triggering, so a single stray noise
            # blip does not start a phrase.
            if len(self.ring_buffer) == self.ring_buffer.maxlen and num_voiced > 0.9 * self.ring_buffer.maxlen:
                self.triggered = True
                # Carry over the buffered frames - they contain the exact
                # moment speech began, so the transcribed phrase does not
                # lose its first word.
                self.voiced_frames = [f for f, _ in self.ring_buffer]
                self.ring_buffer.clear()
            return None

        # --- currently inside a phrase ---
        self.voiced_frames.append(block)
        self.ring_buffer.append((block, is_speech))
        num_unvoiced = len([f for f, speech in self.ring_buffer if not speech])

        silence_detected = (
            len(self.ring_buffer) == self.ring_buffer.maxlen
            and num_unvoiced > 0.9 * self.ring_buffer.maxlen
        )
        force_flush = len(self.voiced_frames) >= self.max_segment_frames

        if silence_detected or force_flush:
            segment = np.concatenate(self.voiced_frames)
            self.triggered = False
            self.voiced_frames = []
            self.ring_buffer.clear()
            if force_flush and not silence_detected:
                logger.info("Phrase reached max duration without a pause - flushing early to bound latency.")
            return segment

        return None

    def flush(self) -> Optional[np.ndarray]:
        """
        Force-emits whatever partial phrase is currently pending. Called
        once, right after recording stops, so the doctor's final words are
        not silently dropped just because they didn't pause before
        clicking Stop (PRD FR-07: "remaining text is written").
        """
        if self.triggered and self.voiced_frames:
            segment = np.concatenate(self.voiced_frames)
            self.triggered = False
            self.voiced_frames = []
            self.ring_buffer.clear()
            return segment
        return None


class TranscriptionEngine:
    """
    Owns the Whisper model and turns a live audio stream into a stream of
    recognised text phrases. See module docstring for the threading model.
    """

    def __init__(
        self,
        model_dir: "str | Path",
        compute_type: str = "int8",
        device: str = "cpu",
        language: str = "en",
        beam_size: int = 1,
        vad_aggressiveness: int = 2,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        """
        Args:
            model_dir: folder containing the local CTranslate2 model files
                       (e.g. "models/small.en"). See
                       models/small.en/README_DOWNLOAD_MODEL.txt.
            compute_type: "int8" is the fastest / lowest-memory option on
                       CPU, at a small accuracy cost versus "float32". This
                       matters directly for the PRD's CPU/memory NFRs.
            beam_size: 1 = greedy decoding (fastest, lowest CPU). Higher
                       values improve accuracy slightly at a real CPU cost.
                       Defaulting to 1 to respect the "<30% CPU" target
                       (Section 7) as much as this architecture allows.
            on_error: optional callback for NON-FATAL errors (a single
                       phrase failing to transcribe). For FATAL errors
                       (model failed to load), see load_model()'s docstring
                       instead - those must terminate the app per Sec. 14.
        """
        self.model_dir = str(model_dir)
        self.compute_type = compute_type
        self.device = device
        self.language = language
        self.beam_size = beam_size
        self.vad_aggressiveness = vad_aggressiveness
        self.on_error = on_error
        self._model: Optional[WhisperModel] = None

    @property
    def is_model_loaded(self) -> bool:
        return self._model is not None

    def load_model(self) -> None:
        """
        Loads the Whisper model from disk. This is a FATAL operation: if it
        fails, raise ModelLoadError and let the caller show an error dialog
        and terminate the application (PRD Section 14). Do not catch this
        exception here and try to "limp along" - there is no safe degraded
        mode for an app whose entire purpose is transcription.
        """
        logger.info(f"Loading speech model from '{self.model_dir}' (compute_type={self.compute_type}) ...")
        try:
            self._model = WhisperModel(
                self.model_dir,
                device=self.device,
                compute_type=self.compute_type,
                # Never attempt a network call, even to check for a newer
                # version - this is a hard requirement of PRD Section 15
                # ("no internet communication"), not just an optimisation.
                local_files_only=True,
            )
        except Exception as e:
            logger.error(f"FATAL: could not load speech model: {e}")
            raise ModelLoadError(
                f"Could not load the speech recognition model from "
                f"'{self.model_dir}'.\n\nMake sure the model files have "
                f"been downloaded there - see "
                f"models/small.en/README_DOWNLOAD_MODEL.txt for instructions."
            ) from e
        logger.info("Speech model loaded successfully.")

    def transcribe_stream(self, recorder, output_queue) -> None:
        """
        BLOCKING loop - run this in a dedicated background thread.

        Consumes audio from `recorder` (any object exposing
        .is_recording, .read_chunk(timeout), .actual_samplerate, and
        .drain_remaining_audio() - normally an AudioRecorder from
        src.audio.recorder), segments it into phrases, transcribes each
        phrase, and pushes the recognised text (str) onto `output_queue`.

        When recorder.is_recording becomes False, drains any remaining
        buffered audio, transcribes a final trailing phrase if one is
        pending, then pushes a single `None` onto output_queue as a
        sentinel meaning "final transcription complete" (PRD FR-07) before
        returning. The UI thread (Phase 6) should treat a None it reads
        from this queue as the cue to set status back to Idle.
        """
        if not self.is_model_loaded:
            raise RuntimeError("transcribe_stream() called before load_model() succeeded.")

        segmenter = PhraseSegmenter(aggressiveness=self.vad_aggressiveness)
        logger.info("Transcription stream started.")

        while recorder.is_recording:
            block = recorder.read_chunk(timeout=0.5)
            if block is None:
                # Just a timeout waiting for the next audio block (or a
                # brief gap) - loop back and re-check is_recording so we
                # notice promptly when Stop is pressed.
                continue
            self._process_block(block, recorder.actual_samplerate, segmenter, output_queue)

        # Recording has stopped - drain whatever was still sitting in the
        # queue so the doctor's last few words are not lost (PRD FR-07).
        for block in recorder.drain_remaining_audio():
            self._process_block(block, recorder.actual_samplerate, segmenter, output_queue)

        final_segment = segmenter.flush()
        if final_segment is not None:
            self._transcribe_and_emit(final_segment, output_queue)

        output_queue.put(None)  # sentinel: final transcription complete
        logger.info("Transcription stream finished (final transcription complete).")

    def _process_block(self, block, source_samplerate, segmenter, output_queue) -> None:
        block = self._ensure_target_rate(block, source_samplerate)
        segment = segmenter.process(block)
        if segment is not None:
            self._transcribe_and_emit(segment, output_queue)

    @staticmethod
    def _ensure_target_rate(block: np.ndarray, source_samplerate: int) -> np.ndarray:
        """
        Guarantees the block handed to VAD/Whisper is EXACTLY
        EXPECTED_BLOCK_SAMPLES long at TARGET_SAMPLE_RATE Hz.

        Why this matters: if the microphone's driver refused 16kHz capture
        directly, AudioRecorder falls back to the device's native rate
        (see recorder.py). webrtcvad will raise an exception on any frame
        that is not exactly the right length for its configured rate -
        floating point resampling math can be off by a sample, so we pad
        or trim defensively rather than let that exception propagate and
        kill the transcription thread mid-session.
        """
        if source_samplerate == TARGET_SAMPLE_RATE and len(block) == EXPECTED_BLOCK_SAMPLES:
            return block

        resampled = resample_audio(block, source_samplerate, TARGET_SAMPLE_RATE)

        if len(resampled) < EXPECTED_BLOCK_SAMPLES:
            resampled = np.pad(resampled, (0, EXPECTED_BLOCK_SAMPLES - len(resampled)), mode="constant")
        elif len(resampled) > EXPECTED_BLOCK_SAMPLES:
            resampled = resampled[:EXPECTED_BLOCK_SAMPLES]

        return resampled

    def _transcribe_and_emit(self, segment_audio: np.ndarray, output_queue) -> None:
        text = self._transcribe_segment(segment_audio)
        if text:
            output_queue.put(text)

    def _transcribe_segment(self, segment_audio: np.ndarray) -> str:
        """
        Runs one phrase of int16 PCM audio (at TARGET_SAMPLE_RATE) through
        Whisper. Returns the recognised text, or "" if the phrase turned
        out to contain no recognisable speech, or if transcription failed
        (in which case the failure is logged and on_error is called, but
        the session continues - PRD Sec. 14).
        """
        # faster-whisper expects float32 samples normalised to [-1, 1],
        # not raw int16 PCM.
        audio_float = segment_audio.astype(np.float32) / 32768.0

        try:
            segments, _info = self._model.transcribe(
                audio_float,
                language=self.language,
                beam_size=self.beam_size,
                # We already gated this audio through our own VAD
                # (PhraseSegmenter) upstream - enabling Whisper's internal
                # VAD filter too would be redundant extra CPU work.
                vad_filter=False,
                # Prevents the model from being biased by (and sometimes
                # repetitively looping on) its own prior output during a
                # long, multi-hour dictation session.
                condition_on_previous_text=False,
            )
            return "".join(s.text for s in segments).strip()
        except Exception as e:
            logger.error(f"Transcription failed for one phrase: {e}")
            if self.on_error:
                self.on_error(f"A phrase could not be transcribed and was skipped: {e}")
            return ""