# Doctor Voice Notes

Doctor Voice Notes is an offline Windows desktop application that converts spoken English into text in real time and continuously saves the transcription into a Microsoft Word document.

Designed specifically for healthcare professionals, the application provides a simple, distraction-free interface that enables doctors to dictate patient notes naturally while keeping all data on the local computer.

## Features

- Real-time offline speech recognition
- Live transcription display
- Automatic Word document generation
- Autosave every few seconds
- Voice commands for formatting and editing
- Large, easy-to-use interface
- Configurable microphone and save location
- Local settings storage
- Logging and error recovery
- No internet connection required
- No cloud services
- No external APIs
- No user accounts

## Technology Stack

- Python 3.12
- Tkinter
- faster-whisper
- sounddevice
- python-docx
- ctranslate2
- PyInstaller

## Project Structure

```
DoctorVoiceNotes/
│
├── assets/
├── config/
├── logs/
├── models/
├── notes/
├── src/
│   ├── audio/
│   ├── commands/
│   ├── document/
│   ├── transcription/
│   ├── ui/
│   └── utils/
│
├── main.py
├── requirements.txt
└── README.md
```

## Installation

1. Download the latest release.
2. Run the `DoctorVoiceNotes.exe` file.
3. If Windows SmartScreen appears, click **More info** → **Run anyway**.
4. Wait for the application to load the speech recognition model.
5. Click **Start** to begin dictating.

No Python installation, internet connection, or additional setup is required.

## Configuration

Application settings are stored locally and include:

- Default save folder
- Document name
- Microphone selection
- Autosave interval
- Theme
- Font size
- Voice command settings

## Voice Commands

Supported commands include:

- New paragraph
- Full stop
- Comma
- New patient
- Date
- Time
- Save note
- Delete last sentence

## Privacy

Doctor Voice Notes is designed with privacy as a primary requirement.

- Fully offline operation
- No cloud storage
- No telemetry
- No internet communication
- No patient data leaves the local computer

## Roadmap

Planned improvements include:

- Patient-specific documents
- PDF export
- Medical abbreviation expansion
- Prescription mode
- Foot pedal support
- Local encrypted backups
- Offline medical terminology dictionary

## License

This project is proprietary software developed for a private client.
