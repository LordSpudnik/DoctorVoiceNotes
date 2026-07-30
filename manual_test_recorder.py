"""
manual_test_recorder.py
========================

Run this on the DOCTOR'S ACTUAL LAPTOP with a real microphone plugged in.
It is a standalone diagnostic script, not part of the shipped application.

What it does:
  1. Lists every microphone Windows can see.
  2. Records 5 seconds of audio from the default (or chosen) microphone.
  3. Saves it as test_recording.wav in this same folder.
  4. Prints basic stats so you can confirm capture is actually happening.

How to confirm it worked:
  - Open test_recording.wav in any media player (double-click it on
    Windows) and listen back. If you hear your own voice clearly, capture
    is working correctly.
  - If the file is silent or missing, the printed stats + on-screen error
    (if any) tell you where it failed.

Run with:
    python manual_test_recorder.py
"""

import sys
import time
import wave

sys.path.insert(0, ".")

from src.audio.recorder import (
    list_input_devices,
    get_default_input_device,
    AudioRecorder,
    NoMicrophoneError,
    AudioDeviceError,
)

RECORD_SECONDS = 5
OUTPUT_FILE = "test_recording.wav"


def main():
    print("=" * 60)
    print("Doctor Voice Notes - Microphone Hardware Test")
    print("=" * 60)

    print("\nStep 1: Listing all microphones Windows can see...")
    try:
        mics = list_input_devices()
    except Exception as e:
        print(f"ERROR: could not query audio devices at all: {e}")
        print("This usually means PortAudio/sounddevice is not installed correctly.")
        print("Try: pip install sounddevice")
        return

    if not mics:
        print("NO MICROPHONES FOUND.")
        print("Check that a microphone is plugged in and enabled in")
        print("Windows Settings > System > Sound > Input.")
        return

    for mic in mics:
        print(f"  [{mic.index}] {mic.name}  (default rate: {mic.default_samplerate} Hz)")

    default_mic = get_default_input_device()
    print(f"\nDefault microphone: {default_mic.name}")

    print(f"\nStep 2: Recording {RECORD_SECONDS} seconds from the default microphone...")
    print("Speak now (say a full sentence, e.g. count from 1 to 10).")

    recorder = AudioRecorder(device_index=None)  # None = default mic

    try:
        recorder.start()
    except NoMicrophoneError:
        print("ERROR: No microphone detected. Check it is plugged in.")
        return
    except AudioDeviceError as e:
        print(f"ERROR: Could not open the microphone: {e}")
        print("Is another application (Zoom, Teams, etc.) currently using it?")
        return

    print(f"Recording at {recorder.actual_samplerate} Hz, block size {recorder.blocksize} samples...")

    collected_blocks = []
    start_time = time.time()
    while time.time() - start_time < RECORD_SECONDS:
        chunk = recorder.read_chunk(timeout=0.5)
        if chunk is not None:
            collected_blocks.append(chunk)
        # Simple progress dots so you can see it's alive, not frozen
        print(".", end="", flush=True)

    print()  # newline after the dots
    recorder.stop()
    collected_blocks.extend(recorder.drain_remaining_audio())

    if not collected_blocks:
        print("\nWARNING: Zero audio blocks were captured. Something is wrong")
        print("with the microphone stream even though it opened successfully.")
        return

    total_samples = sum(len(b) for b in collected_blocks)
    actual_duration = total_samples / recorder.actual_samplerate
    print(f"\nCaptured {len(collected_blocks)} audio blocks, "
          f"{total_samples} samples, {actual_duration:.2f} seconds of audio.")

    print(f"\nStep 3: Saving to {OUTPUT_FILE} ...")
    import numpy as np
    full_audio = np.concatenate(collected_blocks)

    with wave.open(OUTPUT_FILE, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 2 bytes = 16-bit PCM, matches recorder's int16 dtype
        wf.setframerate(recorder.actual_samplerate)
        wf.writeframes(full_audio.tobytes())

    print(f"Saved. Open {OUTPUT_FILE} in any media player and listen back.")
    print("If you can hear your own voice, the microphone capture pipeline works.")
    print("=" * 60)


if __name__ == "__main__":
    main()