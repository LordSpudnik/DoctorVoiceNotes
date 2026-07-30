"""
paths.py
========

Centralised, single source of truth for every file path the application uses.

WHY THIS FILE EXISTS (read this before touching any other module)
-------------------------------------------------------------------
When you run this app as a normal Python script during development, all
paths are simply relative to the project folder on disk. Easy.

When this app is packaged into a single Windows .exe with PyInstaller
(--onefile mode), the .exe does something surprising: every time it starts,
it silently extracts its bundled contents into a TEMPORARY folder
(accessible in code as sys._MEIPASS) and runs from there. That temp folder
is deleted by Windows when the program exits.

This matters enormously for this app, because if settings.json, the
patient notes, or the log file were ever written inside that temporary
folder, they would be SILENTLY DELETED the moment the doctor closes the
application. That is a data-loss bug that would be invisible until the
doctor asks "where did yesterday's notes go?".

To prevent that, this module draws a hard line between two kinds of paths:

    1. RESOURCE paths - read-only files bundled INTO the exe at build time
       (e.g. the application icon). These are allowed to live inside the
       temporary _MEIPASS folder, because they are never written to; they
       are shipped fresh every time.

    2. DATA paths - anything the app WRITES or that must SURVIVE between
       runs (settings.json, notes/*.docx, logs/app.log, the speech model
       files). These always live in the same folder as the .exe file
       itself (or the project root, when running from source). They are
       NEVER placed inside _MEIPASS.

Every other module in this application must obtain its paths from this
file. Do not call Path(__file__) or hardcode "notes/" anywhere else.
"""

import sys
from pathlib import Path


def is_frozen() -> bool:
    """
    Returns True if this code is currently running as a PyInstaller-built
    .exe, and False if it is running as a normal Python script.

    PyInstaller sets sys.frozen = True on the built executable. This is the
    standard, documented way to detect "am I an exe or a script".
    """
    return getattr(sys, "frozen", False)


def get_app_root() -> Path:
    """
    Returns the folder that should be treated as "home base" for all
    persistent data (settings, notes, logs, models).

    - If frozen (running as DoctorVoiceNotes.exe): this is the folder that
      CONTAINS the .exe file. Example: if the doctor's .exe lives at
      C:\\DoctorVoiceNotes\\DoctorVoiceNotes.exe, this returns
      C:\\DoctorVoiceNotes\\
      This is stable across runs - it is NOT the temporary _MEIPASS folder.

    - If running from source (python src/main.py): this is the project's
      top-level folder, i.e. the "DoctorVoiceNotes" folder that contains
      requirements.txt, src/, notes/, config/, etc.
    """
    if is_frozen():
        # sys.executable is the full path to the running .exe itself.
        return Path(sys.executable).resolve().parent
    else:
        # This file lives at: DoctorVoiceNotes/src/utils/paths.py
        # .parents[0] -> src/utils
        # .parents[1] -> src
        # .parents[2] -> DoctorVoiceNotes   <-- this is what we want
        return Path(__file__).resolve().parents[2]


def get_resource_path(relative_path: str) -> Path:
    """
    Resolves the path to a READ-ONLY resource that was bundled into the
    application (for example, an icon file listed in the PyInstaller
    .spec file's `datas` list).

    Unlike data paths, resource paths ARE allowed to point inside the
    temporary PyInstaller extraction folder, because we only ever read
    these files, never write to them, so it does not matter that the
    folder is temporary.

    Args:
        relative_path: path relative to the project root when running from
                       source, e.g. "assets/icons/app_icon.ico"

    Returns:
        The absolute Path to open the resource from, whether running from
        source or from the frozen exe.
    """
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = get_app_root()
    return base / relative_path


def _ensure_dir(path: Path) -> Path:
    """Internal helper: create a directory if it does not exist yet, then
    return it. Used by every get_*_dir() function below so callers never
    have to remember to call mkdir themselves."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_config_dir() -> Path:
    """Folder that holds settings.json. Always beside the exe / project root."""
    return _ensure_dir(get_app_root() / "config")


def get_config_path() -> Path:
    """Full path to settings.json itself."""
    return get_config_dir() / "settings.json"


def get_logs_dir() -> Path:
    """Folder that holds app.log. Always beside the exe / project root."""
    return _ensure_dir(get_app_root() / "logs")


def get_notes_dir() -> Path:
    """
    Default folder that holds the doctor's Word documents.

    NOTE: the doctor can override the actual save folder in Settings
    (PRD FR-09). This function only returns the DEFAULT location used the
    very first time the app runs, before any settings.json exists yet.
    Once settings.json exists, the document module reads the folder from
    there instead of calling this function again.
    """
    return _ensure_dir(get_app_root() / "notes")


def get_models_dir() -> Path:
    """Folder that holds the offline speech recognition model files."""
    return _ensure_dir(get_app_root() / "models")


def get_model_path(model_size: str = "small.en") -> Path:
    """
    Full path to a specific speech model's folder, e.g. models/small.en/

    This folder must contain the CTranslate2-converted Whisper model files
    (model.bin, config.json, tokenizer files, etc). See
    models/small.en/README_DOWNLOAD_MODEL.txt for how to obtain them -
    they are large binary files that are NOT included in source control
    or in this generated project, and must be downloaded once separately.
    """
    return get_models_dir() / model_size
