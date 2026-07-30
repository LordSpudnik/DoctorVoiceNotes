"""
config_manager.py
==================

Loads, validates, and saves the application's settings.json file
(PRD Section 9 - Configuration, Section 12 - Configuration File contents,
FR-09 - Settings).

DESIGN DECISIONS (and why)
---------------------------
1. DEFAULT_SETTINGS is the single source of truth for what a "valid"
   settings.json looks like. If a future feature needs a new setting, add
   it here, and every doctor's existing settings.json will automatically
   gain that new key (with its default value) the next time the app
   starts - see _merge_with_defaults() below. Nobody has to manually
   migrate old settings.json files.

2. If settings.json is missing, corrupted, or contains invalid JSON, we
   do NOT crash the app (PRD Section 14, Error Handling: "prevent
   application crash whenever possible"). Instead we back up the broken
   file (so nothing is silently destroyed) and fall back to defaults.

3. All reads/writes go through this one class so there is exactly one
   place in the whole codebase that touches settings.json directly.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger
from src.utils.paths import get_config_path

logger = get_logger(__name__)


# ----------------------------------------------------------------------------
# DEFAULT SETTINGS
# ----------------------------------------------------------------------------
# This must stay in sync with the fields described in PRD Section 12.
# A few extra technical fields (whisper_model_size, whisper_compute_type,
# window_width/height) are included beyond what Section 12 lists, because
# the transcription engine and UI need them; these are noted as additions
# beyond the PRD, not omissions from it.
# ----------------------------------------------------------------------------
DEFAULT_SETTINGS: dict[str, Any] = {
    "default_save_folder": "notes",
    "default_document_name": "PatientNotes.docx",
    "selected_microphone": None,
    "autosave_interval_seconds": 5,
    "theme": "light",
    "large_text_mode": False,
    "font_size": 18,
    "voice_commands_enabled": True,
    "whisper_model_size": "small.en",
    "whisper_model_path": "models/small.en",
    "whisper_compute_type": "int8",
    "window_width": 900,
    "window_height": 650,
}


class ConfigManager:
    """
    Wraps settings.json with safe load/save behaviour.

    Typical usage (see main.py in a later phase):

        config = ConfigManager()
        config.load()
        interval = config.get("autosave_interval_seconds")
        config.set("theme", "dark")
        config.save()
    """

    def __init__(self):
        self.path: Path = get_config_path()
        # In-memory copy of the settings. Always starts as a fresh copy of
        # the defaults so that even before load() is called, every key is
        # guaranteed to exist with a sane value - callers can never get a
        # KeyError from .get() on a known setting.
        self._settings: dict[str, Any] = dict(DEFAULT_SETTINGS)

    # ------------------------------------------------------------------
    # LOADING
    # ------------------------------------------------------------------
    def load(self) -> None:
        """
        Loads settings.json from disk into memory.

        - If the file does not exist yet (first run ever), creates it with
          default values and logs that this happened.
        - If the file exists but cannot be parsed as JSON (corrupted, or a
          doctor accidentally saved something invalid), the broken file is
          renamed with a timestamp so no data is lost, an error is logged,
          and we fall back to defaults instead of crashing.
        - If the file exists and IS valid JSON, any settings keys that are
          missing (e.g. after an app update introduced a new setting) are
          filled in from DEFAULT_SETTINGS automatically.
        """
        if not self.path.exists():
            logger.info(f"No settings.json found at {self.path}. Creating one with default values.")
            self._settings = dict(DEFAULT_SETTINGS)
            self.save()
            return

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(
                f"settings.json is corrupted or unreadable ({e}). "
                f"Backing it up and restoring defaults so the app can still start."
            )
            self._backup_corrupted_file()
            self._settings = dict(DEFAULT_SETTINGS)
            self.save()
            return

        # Remove the human-readable "_comment" key if present - it is not
        # a real setting, just documentation inside the JSON file.
        loaded.pop("_comment", None)

        self._settings = self._merge_with_defaults(loaded)
        logger.info(f"Loaded settings from {self.path}")

    def _backup_corrupted_file(self) -> None:
        """Renames a broken settings.json to settings.json.broken-<timestamp>
        instead of silently overwriting it, in case the doctor's custom
        save folder or document name was in there and is recoverable by
        hand later."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = self.path.with_suffix(f".json.broken-{timestamp}")
        try:
            shutil.copy2(self.path, backup_path)
            logger.warning(f"Corrupted settings.json backed up to {backup_path}")
        except OSError as e:
            logger.error(f"Could not even back up the corrupted settings.json: {e}")

    @staticmethod
    def _merge_with_defaults(loaded: dict[str, Any]) -> dict[str, Any]:
        """Returns a dict that has every key from DEFAULT_SETTINGS, using
        the doctor's saved value where one exists, and falling back to the
        default value for any key that is missing from the loaded file."""
        merged = dict(DEFAULT_SETTINGS)
        for key, value in loaded.items():
            if key in DEFAULT_SETTINGS:
                merged[key] = value
            else:
                # Unknown key (maybe from a future/older version). Keep it
                # around rather than silently discarding it, but log it so
                # it's visible during troubleshooting.
                merged[key] = value
                logger.info(f"settings.json contains an unrecognised key '{key}' - keeping it as-is.")
        return merged

    # ------------------------------------------------------------------
    # SAVING
    # ------------------------------------------------------------------
    def save(self) -> None:
        """Writes the current in-memory settings back to settings.json,
        pretty-printed so a doctor or developer can still read/edit it by
        hand if needed."""
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2, ensure_ascii=False)
            logger.info(f"Settings saved to {self.path}")
        except OSError as e:
            # Per PRD Section 14: "Cannot save document -> Retry
            # automatically." The same philosophy applies to settings: we
            # log loudly but do not crash the whole application over a
            # failed settings write.
            logger.error(f"Failed to save settings.json: {e}")

    # ------------------------------------------------------------------
    # ACCESS
    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        """Reads a single setting. Returns `default` if the key somehow
        does not exist (should not normally happen, since load() always
        merges in every default key)."""
        return self._settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Updates a single setting in memory. Does NOT write to disk -
        call save() explicitly afterwards (the settings dialog in Phase 6
        will call save() when the doctor clicks 'OK')."""
        self._settings[key] = value

    def as_dict(self) -> dict[str, Any]:
        """Returns a copy of all current settings. Used by the settings
        dialog UI to populate its fields."""
        return dict(self._settings)
