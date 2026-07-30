"""
recorder.py
===========

Microphone detection and audio capture for Doctor Voice Notes.

Covers PRD:
  FR-01 (detect microphone automatically)
  FR-02 (start recording)
  FR-07 (stop recording, finish remaining transcription)
  FR-09 (doctor can choose a specific microphone in Settings)
  FR-10 (release microphone on exit)
  Section 14 (error handling: "No microphone detected", no crash)
  Section 7  (support 2+ hour sessions without unbounded memory growth)
"""

import queue
import threading
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from src.utils.logger import get_logger

logger = get_logger(__name__)

TARGET_SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_DURATION_MS = 30
DTYPE = "int16"


class NoMicrophoneError(Exception):
    """No input device exists on this machine at all.
    UI must catch this and show 'No microphone detected.' (PRD Sec. 14)."""
    pass


class AudioDeviceError(Exception):
    """A specific microphone could not be opened (unplugged, in use
    elsewhere, permission denied, etc)."""
    pass


@dataclass
class MicrophoneInfo:
    """UI-friendly description of one microphone, for the Settings
    dropdown (FR-09)."""
    index: int
    name: str
    default_samplerate: float
    max_input_channels: int

    def __str__(self) -> str:
        return f"{self.name}"


def list_input_devices() -> list[MicrophoneInfo]:
    """Every microphone PortAudio can see on this machine."""
    devices = sd.query_devices()
    mics = []
    for index, device in enumerate(devices):
        if device.get("max_input_channels", 0) > 0:
            mics.append(
                MicrophoneInfo(
                    index=index,
                    name=device.get("name", f"Unknown device {index}"),
                    default_samplerate=device.get("default_samplerate", TARGET_SAMPLE_RATE),
                    max_input_channels=device.get("max_input_channels", 1),
                )
            )
    return mics


def get_default_input_device() -> Optional[MicrophoneInfo]:
    """The system default microphone, or None if there isn't one."""
    mics = list_input_devices()
    if not mics:
        return None
    try:
        default_index = sd.default.device[0]
        for mic in mics:
            if mic.index == default_index:
                return mic
    except Exception:
        pass
    return mics[0]


def ensure_microphone_available() -> MicrophoneInfo:
    """Call at startup AND right before Start Recording (a mic can be
    unplugged in between). Raises NoMicrophoneError if none exists."""
    default = get_default_input_device()
    if default is None:
        logger.error("No microphone detected on this system.")
        raise NoMicrophoneError("No microphone detected.")
    return default


class AudioRecorder:
    """
    Captures microphone audio in small fixed-size blocks and hands them
    off through a thread-safe, BOUNDED queue for the transcription engine
    (Phase 3) to consume.

    Bounded queue (not a growing list) is deliberate: PRD Sec. 7 requires
    2+ hour sessions without unbounded memory growth. If the consumer ever
    falls behind, we drop the OLDEST audio rather than freeze capture or
    grow memory forever - see _callback().
    """

    def __init__(
        self,
        device_index: Optional[int] = None,
        samplerate: int = TARGET_SAMPLE_RATE,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.device_index = device_index
        self.requested_samplerate = samplerate
        self.on_error = on_error
        self.actual_samplerate: int = samplerate

        self._stream: Optional[sd.InputStream] = None
        self._queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=500)
        self._is_recording = threading.Event()
        self.blocksize = 0

    @property
    def is_recording(self) -> bool:
        return self._is_recording.is_set()

    def start(self) -> None:
        """Opens the microphone and begins capturing (PRD FR-02)."""
        if self.is_recording:
            logger.warning("start() called but recording is already active - ignoring.")
            return

        ensure_microphone_available()
        self.blocksize = int(self.requested_samplerate * BLOCK_DURATION_MS / 1000)

        try:
            self._open_stream(self.requested_samplerate)
            self.actual_samplerate = self.requested_samplerate
        except sd.PortAudioError as e:
            logger.warning(
                f"Microphone rejected {self.requested_samplerate} Hz ({e}). "
                f"Retrying at the device's default sample rate."
            )
            devices = sd.query_devices()
            device_idx = self.device_index if self.device_index is not None else sd.default.device[0]
            fallback_rate = int(devices[device_idx]["default_samplerate"])
            self.blocksize = int(fallback_rate * BLOCK_DURATION_MS / 1000)
            try:
                self._open_stream(fallback_rate)
                self.actual_samplerate = fallback_rate
            except sd.PortAudioError as e2:
                logger.error(f"Could not open microphone at any sample rate: {e2}")
                raise AudioDeviceError(f"Could not open microphone: {e2}") from e2

        self._is_recording.set()
        logger.info(
            f"Recording started (device={self.device_index}, "
            f"samplerate={self.actual_samplerate} Hz, blocksize={self.blocksize})"
        )

    def _open_stream(self, samplerate: int) -> None:
        self._stream = sd.InputStream(
            device=self.device_index,
            channels=CHANNELS,
            samplerate=samplerate,
            blocksize=int(samplerate * BLOCK_DURATION_MS / 1000),
            dtype=DTYPE,
            callback=self._callback,
        )
        self._stream.start()

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        """Runs on PortAudio's own audio thread ~every 30ms. Must be fast
        and must never block, or the driver will glitch."""
        if status:
            logger.warning(f"Audio callback status flag: {status}")
            if self.on_error:
                self.on_error(f"Audio warning: {status}")

        block = indata[:, 0].copy()

        try:
            self._queue.put_nowait(block)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(block)
                logger.warning("Audio queue was full - dropped oldest block to keep up.")
            except queue.Empty:
                pass

    def read_chunk(self, timeout: float = 0.5) -> Optional[np.ndarray]:
        """Pulls the next captured audio block, or None after `timeout`
        seconds of silence from the queue (not the microphone) - lets the
        consumer loop check is_recording and exit promptly after stop()."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        """Stops capturing and releases the microphone (PRD FR-07, FR-10).
        Safe to call multiple times or if never started."""
        if not self.is_recording:
            return
        self._is_recording.clear()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except sd.PortAudioError as e:
                logger.error(f"Error while closing audio stream: {e}")
            finally:
                self._stream = None
        logger.info("Recording stopped, microphone released.")

    def drain_remaining_audio(self) -> list[np.ndarray]:
        """After stop(), pulls any blocks still queued so the final
        transcription (PRD FR-07) doesn't silently drop the doctor's last
        few words."""
        remaining = []
        while True:
            try:
                remaining.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return remaining


def resample_audio(audio: np.ndarray, original_rate: int, target_rate: int = TARGET_SAMPLE_RATE) -> np.ndarray:
    """
    Converts int16 PCM audio from original_rate Hz to target_rate Hz using
    linear interpolation. Only used if a microphone refuses to record
    directly at 16000 Hz (see AudioRecorder.start()'s fallback).

    Deliberately not scipy.signal.resample - keeps dependencies minimal.
    Linear interpolation is adequate for speech (not music) recognition;
    if a doctor's specific hardware needs this path and accuracy suffers,
    switching to scipy.signal.resample_poly is the documented upgrade.
    """
    if original_rate == target_rate:
        return audio

    duration = len(audio) / original_rate
    target_length = int(duration * target_rate)

    original_times = np.linspace(0, duration, num=len(audio), endpoint=False)
    target_times = np.linspace(0, duration, num=target_length, endpoint=False)

    resampled_float = np.interp(target_times, original_times, audio.astype(np.float32))
    return np.clip(resampled_float, -32768, 32767).astype(np.int16)