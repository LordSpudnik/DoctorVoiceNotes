"""
main.py
=======

Application entry point for Doctor Voice Notes (PRD Section 9/10, Phase 7).

This file's only job is to:
  1. Configure logging as early as possible, so startup failures are
     captured (PRD Section 13: "Application log - Startup").
  2. Load settings.json via ConfigManager.
  3. Create the root CustomTkinter window (ctk.CTk(), NOT tkinter.Tk() -
     main_window.py calls self.root.configure(fg_color=...), which only
     exists on CTk widgets, not plain Tk).
  4. Hand control to MainWindow, which owns everything else.
  5. Catch any exception that escapes to this top level so the doctor
     never sees a raw Python traceback (PRD Section 14: "Unexpected
     exception -> write stack trace to log, prevent application crash
     whenever possible").

Run from source:
    python main.py

Packaged (after Phase 7 build):
    DoctorVoiceNotes.exe
"""

import sys
import traceback

import customtkinter as ctk

from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger
from src.utils.paths import get_resource_path

logger = get_logger(__name__)


def _apply_app_icon(root: "ctk.CTk") -> None:
    """
    Sets the window/taskbar icon (PRD Section 22 deliverable). Nothing in
    main_window.py did this in Phase 6, so it is wired here instead.

    Deliberately non-fatal: the app must still launch and work perfectly
    even if app_icon.ico is missing or corrupt - a cosmetic taskbar icon
    is not worth crashing the app over.
    """
    icon_path = get_resource_path("assets/icons/app_icon.ico")
    if not icon_path.exists():
        logger.warning(f"App icon not found at {icon_path} - continuing without one.")
        return
    try:
        root.iconbitmap(str(icon_path))
    except Exception as e:
        # .iconbitmap() only accepts .ico on Windows and can raise on some
        # Tk builds (e.g. Linux dev machines) even when the file is valid.
        logger.warning(f"Could not set application icon: {e}")


def main() -> int:
    logger.info("=" * 60)
    logger.info("Doctor Voice Notes starting up.")

    config = ConfigManager()
    config.load()

    ctk.set_appearance_mode("Dark" if config.get("theme") == "dark" else "Light")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    _apply_app_icon(root)

    # Imported here, not at module level, so that a failure while building
    # the window (e.g. a missing widget attribute) is still caught by the
    # try/except below rather than crashing before logging is even set up.
    from src.ui.main_window import MainWindow

    MainWindow(root, config)

    root.mainloop()

    logger.info("Doctor Voice Notes exited normally.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Last-resort safety net (PRD Section 14). Anything that reaches
        # here is a bug MainWindow did not already handle - log the full
        # trace and exit cleanly instead of showing the doctor a raw
        # console crash (which, in a windowed PyInstaller build, they
        # would not even see - it would just silently vanish).
        logger.error("FATAL: unhandled exception reached main().\n%s", traceback.format_exc())
        try:
            import tkinter.messagebox as messagebox
            messagebox.showerror(
                "Doctor Voice Notes - Fatal Error",
                "Doctor Voice Notes hit an unexpected error and must close.\n\n"
                "Details were written to logs\\app.log.\n"
                "Please restart the application.",
            )
        except Exception:
            pass
        sys.exit(1)