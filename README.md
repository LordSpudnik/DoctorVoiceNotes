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
├── main.py # App entry point
├── build.spec # PyInstaller build spec, onedir mode
├── build.bat # Windows build script
├── installer.iss # Inno Setup installer script
├── requirements.txt # Pinned dependencies
├── README.md # Developer setup, build, and known-issues doc
│
├── assets/
│ └── icons/
│ └── app_icon.ico
│
├── models/
│ └── small.en/ # Speech model
│ ├── model.bin
│ ├── config.json
│ ├── tokenizer.json
│ ├── vocabulary.txt
│ └── README_DOWNLOAD_MODEL.txt
│
├── src/
│ ├── init.py
│ ├── audio/
│ │ ├── init.py
│ │ └── recorder.py # Microphone detection + capture
│ ├── transcription/
│ │ ├── init.py
│ │ └── engine.py # Whisper transcription + VAD
│ ├── document/
│ │ ├── init.py
│ │ └── writer.py # .docx writing + autosave
│ ├── commands/
│ │ ├── init.py
│ │ └── voice_commands.py # Voice command parsing
│ ├── ui/
│ │ ├── init.py
│ │ ├── main_window.py # Main application window
│ │ └── settings_dialog.py # Settings dialog
│ └── utils/
│ ├── init.py
│ ├── config_manager.py # settings.json load/save
│ ├── logger.py # Rotating file logging
│ └── paths.py # Frozen-vs-source path resolution
│
├── config/ # Created automatically on first run
│ └── settings.json
├── logs/ # Created automatically on first run
│ └── app.log
├── notes/ # Created automatically on first run
│ └── PatientNotes.docx
│
├── venv/ # Local virtual environment (gitignored)
├── build/ # PyInstaller intermediate output (gitignored)
├── dist/ # PyInstaller final output (gitignored)
│ └── DoctorVoiceNotes/
│ ├── DoctorVoiceNotes.exe
│ ├── _internal/ # Bundled Python + dependencies
│ └── models/small.en/ # Model, copied here by build.bat
└── installer_output/ # Compiled installer (gitignored)
└── DoctorVoiceNotes_Setup_v1.0.0.exe
```

**Not committed to source control** (see `.gitignore`): `venv/`, `build/`, `dist/`, `installer_output/`, `models/small.en/*` (except `README_DOWNLOAD_MODEL.txt`), and the auto-generated `config/`, `logs/`, `notes/` contents — these are either environment-specific, build artifacts, or the doctor's own clinical data.

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
