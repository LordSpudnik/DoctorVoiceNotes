"""
settings_dialog.py
===================

Settings dialog for Doctor Voice Notes (PRD FR-09).

Restyled onto CustomTkinter to match the rest of the Phase 6 UI. Every
control here still maps directly onto a real key in
config_manager.DEFAULT_SETTINGS - nothing invents a new setting the rest
of the app does not read (same rule as the previous draft).

WHAT CHANGED FROM THE PREVIOUS DRAFT
-------------------------------------
- Visual restyle only (CTk widgets, rounded corners, consistent palette).
- The Save button is now clearly labeled "Save Settings" and is the
  filled/primary button, with "Cancel" as a plain outlined button next to
  it, so the confirm action is unambiguous (this was the doctor's actual
  complaint about the old dialog - not a missing feature, a missing
  visual affordance).
- Theme is now a two-option segmented control instead of radio buttons -
  same underlying "theme": "light"/"dark" setting, just a more modern
  control that is easier to hit with a mouse for a doctor with limited
  computer experience (Section 16, Accessibility: large buttons).

Settings are only applied on the NEXT "Start" press, not to a session
that is already running - unchanged from the previous draft. main_window.py
enforces this by disabling the Settings button while recording.
"""

from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from src.audio.recorder import list_input_devices
from src.utils.config_manager import ConfigManager

_FONT_FAMILY = "Segoe UI"


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent, config: ConfigManager, on_saved: Callable[[], None]):
        super().__init__(parent)
        self.config = config
        self.on_saved = on_saved

        self.title("Settings")
        self.geometry("540x600")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()  # modal

        self._mics = list_input_devices()
        self._build_widgets()
        self._load_current_values()

    # ------------------------------------------------------------------
    def _build_widgets(self) -> None:
        pad = {"padx": 24, "pady": (0, 18)}

        ctk.CTkLabel(self, text="Settings", font=(_FONT_FAMILY, 22, "bold")).pack(
            anchor="w", padx=24, pady=(24, 16)
        )

        # --- Microphone (FR-09) ---
        mic_frame = ctk.CTkFrame(self, fg_color="transparent")
        mic_frame.pack(fill="x", **pad)
        ctk.CTkLabel(mic_frame, text="Microphone", font=(_FONT_FAMILY, 13, "bold")).pack(anchor="w")
        mic_row = ctk.CTkFrame(mic_frame, fg_color="transparent")
        mic_row.pack(fill="x", pady=(6, 0))
        self.mic_var = ctk.StringVar()
        mic_names = ["System default"] + [m.name for m in self._mics]
        self.mic_menu = ctk.CTkOptionMenu(mic_row, values=mic_names, variable=self.mic_var, width=320)
        self.mic_menu.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(mic_row, text="Refresh", width=90, command=self._refresh_mics).pack(
            side="left", padx=(8, 0)
        )

        # --- Autosave interval (FR-09, FR-05) ---
        interval_frame = ctk.CTkFrame(self, fg_color="transparent")
        interval_frame.pack(fill="x", **pad)
        ctk.CTkLabel(interval_frame, text="Autosave interval (seconds)",
                     font=(_FONT_FAMILY, 13, "bold")).pack(anchor="w")
        self.interval_var = ctk.StringVar()
        ctk.CTkEntry(interval_frame, textvariable=self.interval_var, width=100).pack(
            anchor="w", pady=(6, 0)
        )

        # --- Save folder (FR-09, FR-06) ---
        folder_frame = ctk.CTkFrame(self, fg_color="transparent")
        folder_frame.pack(fill="x", **pad)
        ctk.CTkLabel(folder_frame, text="Save folder", font=(_FONT_FAMILY, 13, "bold")).pack(anchor="w")
        folder_row = ctk.CTkFrame(folder_frame, fg_color="transparent")
        folder_row.pack(fill="x", pady=(6, 0))
        self.folder_var = ctk.StringVar()
        ctk.CTkEntry(folder_row, textvariable=self.folder_var).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(folder_row, text="Browse...", width=90, command=self._browse_folder).pack(
            side="left", padx=(8, 0)
        )

        # --- Document name (FR-09, FR-06) ---
        doc_frame = ctk.CTkFrame(self, fg_color="transparent")
        doc_frame.pack(fill="x", **pad)
        ctk.CTkLabel(doc_frame, text="Document name", font=(_FONT_FAMILY, 13, "bold")).pack(anchor="w")
        self.doc_var = ctk.StringVar()
        ctk.CTkEntry(doc_frame, textvariable=self.doc_var).pack(fill="x", pady=(6, 0))

        # --- Large text mode (FR-09, Accessibility) ---
        self.large_text_var = ctk.BooleanVar()
        ctk.CTkCheckBox(
            self, text="Large text mode", variable=self.large_text_var, font=(_FONT_FAMILY, 13),
        ).pack(anchor="w", padx=24, pady=(0, 18))

        # --- Theme (FR-09: dark mode) ---
        theme_frame = ctk.CTkFrame(self, fg_color="transparent")
        theme_frame.pack(fill="x", **pad)
        ctk.CTkLabel(theme_frame, text="Theme", font=(_FONT_FAMILY, 13, "bold")).pack(anchor="w")
        self.theme_var = ctk.StringVar()
        self.theme_switch = ctk.CTkSegmentedButton(
            theme_frame, values=["Light", "Dark"], variable=self.theme_var,
        )
        self.theme_switch.pack(anchor="w", pady=(6, 0))

        # --- buttons ---
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=24, pady=(10, 24), side="bottom")
        ctk.CTkButton(
            btn_row, text="Save Settings", height=44, corner_radius=22,
            font=(_FONT_FAMILY, 14, "bold"), command=self._on_save,
        ).pack(side="right")
        ctk.CTkButton(
            btn_row, text="Cancel", height=44, corner_radius=22, width=110,
            font=(_FONT_FAMILY, 14), fg_color="transparent", border_width=2,
            command=self.destroy,
        ).pack(side="right", padx=(0, 10))

    # ------------------------------------------------------------------
    def _refresh_mics(self) -> None:
        self._mics = list_input_devices()
        mic_names = ["System default"] + [m.name for m in self._mics]
        self.mic_menu.configure(values=mic_names)
        if self.mic_var.get() not in mic_names:
            self.mic_var.set("System default")

    def _browse_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.folder_var.get() or ".")
        if chosen:
            self.folder_var.set(chosen)

    # ------------------------------------------------------------------
    def _load_current_values(self) -> None:
        selected_index = self.config.get("selected_microphone")
        mic_name = "System default"
        if selected_index is not None:
            for m in self._mics:
                if m.index == selected_index:
                    mic_name = m.name
                    break
        self.mic_var.set(mic_name)

        self.interval_var.set(str(self.config.get("autosave_interval_seconds", 5)))
        self.folder_var.set(self.config.get("default_save_folder", "notes"))
        self.doc_var.set(self.config.get("default_document_name", "PatientNotes.docx"))
        self.large_text_var.set(self.config.get("large_text_mode", False))
        self.theme_var.set("Dark" if self.config.get("theme") == "dark" else "Light")

    def _on_save(self) -> None:
        # --- validation (Section 14: prevent crash, catch bad input) ---
        doc_name = self.doc_var.get().strip()
        if not doc_name:
            messagebox.showerror("Settings", "Document name cannot be empty.")
            return
        if not doc_name.lower().endswith(".docx"):
            doc_name += ".docx"

        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showerror("Settings", "Save folder cannot be empty.")
            return

        try:
            interval = int(self.interval_var.get())
        except ValueError:
            messagebox.showerror("Settings", "Autosave interval must be a whole number of seconds.")
            return
        if interval < 1:
            messagebox.showerror("Settings", "Autosave interval must be at least 1 second.")
            return

        mic_index = None
        chosen_mic_name = self.mic_var.get()
        if chosen_mic_name != "System default":
            for m in self._mics:
                if m.name == chosen_mic_name:
                    mic_index = m.index
                    break

        self.config.set("selected_microphone", mic_index)
        self.config.set("autosave_interval_seconds", interval)
        self.config.set("default_save_folder", folder)
        self.config.set("default_document_name", doc_name)
        self.config.set("large_text_mode", self.large_text_var.get())
        self.config.set("theme", "dark" if self.theme_var.get() == "Dark" else "light")
        self.config.save()

        self.on_saved()
        self.destroy()