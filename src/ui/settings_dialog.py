"""
settings_dialog.py
===================
Visually enhanced setting dialog matching the new upgraded modern aesthetic.
"""

from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from src.audio.recorder import list_input_devices
from src.utils.config_manager import ConfigManager

_FONT_FAMILY = "Segoe UI"
_PRIMARY = ("#4F46E5", "#6366F1")
_BG = ("#F9FAFB", "#0F0F1A")
_TEXT = ("#111827", "#F9FAFB")
_CARD = ("#FFFFFF", "#1E1E2E")
_BORDER = ("#E5E7EB", "#313244")


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent, config: ConfigManager, on_saved: Callable[[], None]):
        super().__init__(parent)
        self.config = config
        self.on_saved = on_saved

        self.title("Settings")
        self.geometry("640x760")         # Increased height to 820
        self.resizable(False, True)      # Allows vertical resizing if needed
        self.configure(fg_color=_BG)
        self.transient(parent)
        self.grab_set()  

        self._mics = list_input_devices()
        self._build_widgets()
        self._load_current_values()

    def _build_widgets(self) -> None:
        pad = {"padx": 40, "pady": (0, 25)}

        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=40, pady=(40, 30))
        
        ctk.CTkLabel(
            header_frame, text="⚙️ Preferences", 
            font=(_FONT_FAMILY, 28, "bold"), text_color=_PRIMARY
        ).pack(side="left")

        # Container for main settings to give a card-like look
        main_card = ctk.CTkFrame(self, fg_color=_CARD, corner_radius=16, border_width=1, border_color=_BORDER)
        main_card.pack(fill="both", expand=True, padx=40, pady=(0, 20))

        # We will pad inside the card
        inner_pad = {"padx": 30, "pady": (20, 0)}

        # --- Microphone ---
        mic_frame = ctk.CTkFrame(main_card, fg_color="transparent")
        mic_frame.pack(fill="x", **inner_pad)
        ctk.CTkLabel(mic_frame, text="Microphone Device", font=(_FONT_FAMILY, 14, "bold")).pack(anchor="w")
        mic_row = ctk.CTkFrame(mic_frame, fg_color="transparent")
        mic_row.pack(fill="x", pady=(8, 0))
        self.mic_var = ctk.StringVar()
        mic_names = ["System default"] + [m.name for m in self._mics]
        self.mic_menu = ctk.CTkOptionMenu(
            mic_row, values=mic_names, variable=self.mic_var, 
            width=350, height=40, corner_radius=8, font=(_FONT_FAMILY, 14)
        )
        self.mic_menu.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            mic_row, text="🔄 Refresh", width=100, height=40, corner_radius=8,
            font=(_FONT_FAMILY, 13, "bold"), fg_color=_PRIMARY, command=self._refresh_mics
        ).pack(side="left", padx=(10, 0))

        # --- Autosave interval ---
        interval_frame = ctk.CTkFrame(main_card, fg_color="transparent")
        interval_frame.pack(fill="x", **inner_pad)
        ctk.CTkLabel(interval_frame, text="Autosave Interval (seconds)", font=(_FONT_FAMILY, 14, "bold")).pack(anchor="w")
        self.interval_var = ctk.StringVar()
        ctk.CTkEntry(
            interval_frame, textvariable=self.interval_var, width=120, height=40, 
            corner_radius=8, font=(_FONT_FAMILY, 14)
        ).pack(anchor="w", pady=(8, 0))

        # --- Save folder ---
        folder_frame = ctk.CTkFrame(main_card, fg_color="transparent")
        folder_frame.pack(fill="x", **inner_pad)
        ctk.CTkLabel(folder_frame, text="Output Folder", font=(_FONT_FAMILY, 14, "bold")).pack(anchor="w")
        folder_row = ctk.CTkFrame(folder_frame, fg_color="transparent")
        folder_row.pack(fill="x", pady=(8, 0))
        self.folder_var = ctk.StringVar()
        ctk.CTkEntry(
            folder_row, textvariable=self.folder_var, height=40, 
            corner_radius=8, font=(_FONT_FAMILY, 14)
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            folder_row, text="📂 Browse", width=100, height=40, corner_radius=8,
            font=(_FONT_FAMILY, 13, "bold"), fg_color=_PRIMARY, command=self._browse_folder
        ).pack(side="left", padx=(10, 0))

        # --- Document name ---
        doc_frame = ctk.CTkFrame(main_card, fg_color="transparent")
        doc_frame.pack(fill="x", **inner_pad)
        ctk.CTkLabel(doc_frame, text="Target Document Name", font=(_FONT_FAMILY, 14, "bold")).pack(anchor="w")
        self.doc_var = ctk.StringVar()
        ctk.CTkEntry(
            doc_frame, textvariable=self.doc_var, height=40, 
            corner_radius=8, font=(_FONT_FAMILY, 14)
        ).pack(fill="x", pady=(8, 0))

        # --- Theme ---
        theme_frame = ctk.CTkFrame(main_card, fg_color="transparent")
        theme_frame.pack(fill="x", **inner_pad)
        ctk.CTkLabel(theme_frame, text="Appearance", font=(_FONT_FAMILY, 14, "bold")).pack(anchor="w")
        self.theme_var = ctk.StringVar()
        self.theme_switch = ctk.CTkSegmentedButton(
            theme_frame, values=["Light", "Dark"], variable=self.theme_var, 
            height=40, font=(_FONT_FAMILY, 13, "bold"), corner_radius=8
        )
        self.theme_switch.pack(anchor="w", pady=(8, 0))

        # --- Large text mode ---
        self.large_text_var = ctk.BooleanVar()
        ctk.CTkCheckBox(
            main_card, text="Enable Large Text Mode (Accessibility)", variable=self.large_text_var, 
            font=(_FONT_FAMILY, 14, "bold"), checkbox_width=24, checkbox_height=24, 
            corner_radius=6, text_color=_TEXT
        ).pack(anchor="w", padx=30, pady=(20, 25))

        # --- buttons ---
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=40, pady=(0, 30), side="bottom")
        
        ctk.CTkButton(
            btn_row, text="💾 Save Preferences", height=50, corner_radius=12,
            font=(_FONT_FAMILY, 16, "bold"), fg_color=_PRIMARY, command=self._on_save,
        ).pack(side="right")
        
        ctk.CTkButton(
            btn_row, text="Cancel", height=50, corner_radius=12, width=120,
            font=(_FONT_FAMILY, 16, "bold"), fg_color="transparent", border_width=2,
            text_color=_TEXT, hover_color=_BORDER, command=self.destroy,
        ).pack(side="right", padx=(0, 15))

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