"""
main_window.py
===============
Upgraded for a vibrant, modern UI while STRICTLY preserving the original
backend wiring, threading, and scope restrictions.
"""

import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from src.audio.recorder import (
    AudioDeviceError,
    AudioRecorder,
    NoMicrophoneError,
    ensure_microphone_available,
    list_input_devices,
)
from src.commands.voice_commands import VoiceCommandProcessor
from src.document.writer import DocumentWriter
from src.transcription.engine import ModelLoadError, TranscriptionEngine
from src.ui.settings_dialog import SettingsDialog
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger
from src.utils.paths import get_app_root, get_model_path

logger = get_logger(__name__)

_POLL_MS = 150
_PULSE_MS = 120

_FONT_FAMILY = "Segoe UI"

# --- UPGRADED VIBRANT PALETTE ---
_PRIMARY = ("#4F46E5", "#6366F1")         # Brighter Electric Indigo
_ON_PRIMARY = ("#FFFFFF", "#FFFFFF")
_DANGER = ("#E11D48", "#F43F5E")          # Vibrant Rose/Red
_ON_DANGER = ("#FFFFFF", "#FFFFFF")
_RECORDING = ("#059669", "#10B981")       # Emerald Green
_RECORDING_BG = ("#D1FAE5", "#064E3B")    # Soft Emerald tint for pills
_CARD = ("#FFFFFF", "#1E1E2E")            # Rich dark card background
_BG = ("#F9FAFB", "#0F0F1A")              # Deep modern app background
_TEXT = ("#111827", "#F9FAFB")
_TEXT_VARIANT = ("#6B7280", "#9CA3AF")
_BORDER = ("#E5E7EB", "#313244")
_TRANSCRIPT_BG = ("#F3F4F6", "#181825")   # Slightly offset for depth
_PENDING_ACCENT = ("#4338CA", "#818CF8")


class MainWindow:
    def __init__(self, root: "ctk.CTk", config: ConfigManager):
        self.root = root
        self.config = config

        ctk.set_appearance_mode("Dark" if config.get("theme") == "dark" else "Light")
        ctk.set_default_color_theme("blue")

        self._recorder: "AudioRecorder | None" = None
        self._engine: "TranscriptionEngine | None" = None
        self._processor: "VoiceCommandProcessor | None" = None
        self._writer: "DocumentWriter | None" = None
        self._stop_event: "threading.Event | None" = None
        self._transcript_queue: "queue.Queue | None" = None
        self._audio_warning_queue: "queue.Queue[str]" = queue.Queue()
        self._model_load_queue: "queue.Queue" = queue.Queue()
        self._finalize_queue: "queue.Queue[bool]" = queue.Queue()
        self._is_recording = False
        self._poll_job = None
        self._pulse_job = None
        self._pulse_phase = 0

        self._build_window()
        self._build_widgets()
        self._show_idle_screen()
        self._refresh_status_labels()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._bind_shortcuts()

        self._set_start_enabled(False)
        self.status_var.set("Loading speech model...")
        threading.Thread(target=self._load_model_background, daemon=True).start()
        self.root.after(100, self._poll_model_load)

    def _build_window(self) -> None:
        self.root.title("Doctor Voice Notes")
        width = self.config.get("window_width", 960)
        height = self.config.get("window_height", 740)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(800, 650)
        self.root.configure(fg_color=_BG)

    def _build_widgets(self) -> None:
        pad = 40 

        # ---------------- header ----------------
        self.header = ctk.CTkFrame(self.root, fg_color="transparent")
        self.header.pack(fill="x", padx=pad, pady=(pad, 10))

        self.title_label = ctk.CTkLabel(
            self.header, text="🩺 Doctor Voice Notes",
            font=(_FONT_FAMILY, 28, "bold"), text_color=_PRIMARY,
        )
        self.title_label.pack(side="left")

        icon_row = ctk.CTkFrame(self.header, fg_color="transparent")
        icon_row.pack(side="right")

        self.help_btn = ctk.CTkButton(
            icon_row, text="❓", width=42, height=42, corner_radius=10,
            font=(_FONT_FAMILY, 18), fg_color=_CARD, text_color=_TEXT,
            hover_color=_BORDER, border_width=1, border_color=_BORDER, command=self._show_help,
        )
        self.help_btn.pack(side="right", padx=(12, 0))

        self.theme_btn = ctk.CTkButton(
            icon_row, text="🌓 Theme", width=110, height=42, corner_radius=10,
            font=(_FONT_FAMILY, 14, "bold"), fg_color=_CARD, text_color=_TEXT,
            hover_color=_BORDER, border_width=1, border_color=_BORDER, command=self._toggle_theme,
        )
        self.theme_btn.pack(side="right", padx=(12, 0))

        self.settings_btn = ctk.CTkButton(
            icon_row, text="⚙️ Settings", width=120, height=42, corner_radius=10,
            font=(_FONT_FAMILY, 14, "bold"), fg_color=_CARD, text_color=_TEXT,
            hover_color=_BORDER, border_width=1, border_color=_BORDER, command=self._open_settings,
        )
        self.settings_btn.pack(side="right")

        # ---------------- badge row ----------------
        badge_row = ctk.CTkFrame(self.root, fg_color="transparent")
        badge_row.pack(fill="x", padx=pad, pady=(0, 20))

        self.offline_badge = ctk.CTkLabel(
            badge_row, text="🔒 OFFLINE SECURE", font=(_FONT_FAMILY, 12, "bold"),
            text_color=_TEXT_VARIANT,
        )
        self.offline_badge.pack(side="left")

        self.autosave_badge = ctk.CTkLabel(
            badge_row, text="", font=(_FONT_FAMILY, 12, "bold"),
            text_color=_RECORDING,
        )
        self.autosave_badge.pack(side="left", padx=(20, 0))

        # ---------------- content area ----------------
        self.content = ctk.CTkFrame(self.root, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=pad, pady=(0, 10))

        self._build_idle_screen()
        self._build_recording_screen()

        # ---------------- status bar ----------------
        self.status_var = tk.StringVar(value="Ready")
        self.status_bar = ctk.CTkLabel(
            self.root, textvariable=self.status_var, font=(_FONT_FAMILY, 13),
            anchor="w", text_color=_TEXT_VARIANT,
        )
        self.status_bar.pack(fill="x", side="bottom", padx=pad, pady=(0, 20))

    def _build_idle_screen(self) -> None:
        self.idle_frame = ctk.CTkFrame(self.content, fg_color="transparent")

        spacer_top = ctk.CTkFrame(self.idle_frame, fg_color="transparent", height=40)
        spacer_top.pack()

        # Upgraded Start Button (Shadow-like border, icon focus)
        self.start_btn = ctk.CTkButton(
            self.idle_frame, text="     🎙️", width=160, height=160, corner_radius=80,
            font=(_FONT_FAMILY, 60), fg_color=_PRIMARY, text_color=_ON_PRIMARY,
            hover_color=_PENDING_ACCENT, border_width=4, border_color=_CARD,
            command=self._on_start,
        )
        self.start_btn.pack(pady=(20, 20))

        ctk.CTkLabel(
            self.idle_frame, text="Ready to Dictate", font=(_FONT_FAMILY, 28, "bold"),
            text_color=_TEXT,
        ).pack()
        ctk.CTkLabel(
            self.idle_frame, text="Tap the microphone to begin generating your clinical notes.",
            font=(_FONT_FAMILY, 16), text_color=_TEXT_VARIANT,
        ).pack(pady=(8, 40))

        info_card = ctk.CTkFrame(self.idle_frame, fg_color=_CARD, corner_radius=16, border_width=1, border_color=_BORDER)
        info_card.pack(pady=10)
        info_inner = ctk.CTkFrame(info_card, fg_color="transparent")
        info_inner.pack(padx=50, pady=25)

        mic_col = ctk.CTkFrame(info_inner, fg_color="transparent")
        mic_col.grid(row=0, column=0, padx=30, sticky="w")
        ctk.CTkLabel(mic_col, text="🎤 ACTIVE MICROPHONE", font=(_FONT_FAMILY, 11, "bold"),
                     text_color=_TEXT_VARIANT).pack(anchor="w")
        self.idle_mic_var = tk.StringVar()
        ctk.CTkLabel(mic_col, textvariable=self.idle_mic_var, font=(_FONT_FAMILY, 15, "bold"),
                     text_color=_PRIMARY).pack(anchor="w")

        doc_col = ctk.CTkFrame(info_inner, fg_color="transparent")
        doc_col.grid(row=0, column=1, padx=30, sticky="w")
        ctk.CTkLabel(doc_col, text="📄 TARGET DOCUMENT", font=(_FONT_FAMILY, 11, "bold"),
                     text_color=_TEXT_VARIANT).pack(anchor="w")
        self.idle_doc_var = tk.StringVar()
        ctk.CTkLabel(doc_col, textvariable=self.idle_doc_var, font=(_FONT_FAMILY, 15, "bold"),
                     text_color=_PRIMARY).pack(anchor="w")

    def _build_recording_screen(self) -> None:
        self.recording_frame = ctk.CTkFrame(self.content, fg_color="transparent")

        top_row = ctk.CTkFrame(self.recording_frame, fg_color="transparent")
        top_row.pack(fill="x", pady=(0, 10))

        self.recording_status_var = tk.StringVar(value="Listening...")
        self.recording_pill = ctk.CTkLabel(
            top_row, textvariable=self.recording_status_var, font=(_FONT_FAMILY, 14, "bold"),
            text_color=_RECORDING, fg_color=_RECORDING_BG, corner_radius=20,
            padx=25, pady=10,
        )
        self.recording_pill.pack()

        self.pulse_canvas = tk.Canvas(
            self.recording_frame, height=80, highlightthickness=0, bd=0, bg=self._resolve_color(_BG)
        )
        self.pulse_canvas.pack(pady=(10, 15))

        transcript_card = ctk.CTkFrame(self.recording_frame, fg_color=_CARD, corner_radius=16, border_width=1, border_color=_BORDER)
        transcript_card.pack(fill="both", expand=True)

        self.transcript_text = ctk.CTkTextbox(
            transcript_card, wrap="word", state="disabled",
            font=(_FONT_FAMILY, self._current_font_size()),
            fg_color=_TRANSCRIPT_BG, text_color=_TEXT,
            corner_radius=12, border_width=0,
        )
        self.transcript_text.pack(fill="both", expand=True, padx=15, pady=15)
        self.transcript_text.tag_config("pending", foreground=self._resolve_color(_PENDING_ACCENT))

        controls = ctk.CTkFrame(self.recording_frame, fg_color="transparent")
        controls.pack(fill="x", pady=(20, 5))

        self.save_btn = ctk.CTkButton(
            controls, text="💾 Checkpoint Save", font=(_FONT_FAMILY, 16, "bold"),
            height=55, corner_radius=12, fg_color=_CARD, text_color=_PRIMARY,
            border_width=2, border_color=_PRIMARY, hover_color=_BORDER,
            command=self._on_force_save,
        )
        self.save_btn.pack(side="left", fill="x", expand=True, padx=(0, 15))

        self.stop_btn = ctk.CTkButton(
            controls, text="⏹️ Stop Recording", font=(_FONT_FAMILY, 16, "bold"),
            height=55, corner_radius=12, fg_color=_DANGER, text_color=_ON_DANGER,
            hover_color=_PENDING_ACCENT, command=self._on_stop,
        )
        self.stop_btn.pack(side="left", fill="x", expand=True)

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-r>", lambda e: self._on_start())
        self.root.bind("<Control-R>", lambda e: self._on_start())
        self.root.bind("<Control-t>", lambda e: self._on_stop())
        self.root.bind("<Control-T>", lambda e: self._on_stop())
        self.root.bind("<Control-s>", lambda e: self._on_force_save())
        self.root.bind("<Control-S>", lambda e: self._on_force_save())
        self.root.bind("<Control-q>", lambda e: self._on_close())
        self.root.bind("<Control-Q>", lambda e: self._on_close())

    def _show_idle_screen(self) -> None:
        self.recording_frame.pack_forget()
        self.idle_frame.pack(fill="both", expand=True)
        self._stop_pulse()

    def _show_recording_screen(self) -> None:
        self.idle_frame.pack_forget()
        self.recording_frame.pack(fill="both", expand=True)
        self._start_pulse()

    def _toggle_theme(self) -> None:
        new_theme = "light" if self.config.get("theme") == "dark" else "dark"
        self.config.set("theme", new_theme)
        self.config.save()
        ctk.set_appearance_mode("Dark" if new_theme == "dark" else "Light")
        self.transcript_text.tag_config("pending", foreground=self._resolve_color(_PENDING_ACCENT))
        self.pulse_canvas.configure(bg=self._resolve_color(_BG))

    @staticmethod
    def _resolve_color(pair) -> str:
        return pair[1] if ctk.get_appearance_mode() == "Dark" else pair[0]

    def _current_font_size(self) -> int:
        base = self.config.get("font_size", 18)
        return base + 6 if self.config.get("large_text_mode", False) else base

    def _start_pulse(self) -> None:
        self._pulse_phase = 0
        self._animate_pulse()

    def _stop_pulse(self) -> None:
        if self._pulse_job is not None:
            self.root.after_cancel(self._pulse_job)
            self._pulse_job = None
        self.pulse_canvas.delete("all")

    def _animate_pulse(self) -> None:
        import math
        c = self.pulse_canvas
        c.delete("all")
        width = max(c.winfo_width(), 200)
        height = 80
        bar_count = 24
        bar_width = 6
        gap = (width - bar_count * bar_width) / (bar_count + 1)
        color = self._resolve_color(_RECORDING)
        for i in range(bar_count):
            x = gap + i * (bar_width + gap)
            level = (math.sin(self._pulse_phase / 4 + i * 0.6) + 1) / 2
            bar_height = 10 + level * (height - 20)
            y0 = (height - bar_height) / 2
            y1 = y0 + bar_height
            # Simulate rounded corners on canvas by drawing pill shape
            c.create_oval(x, y0, x + bar_width, y0 + bar_width, fill=color, outline="")
            c.create_rectangle(x, y0 + bar_width/2, x + bar_width, y1 - bar_width/2, fill=color, outline="")
            c.create_oval(x, y1 - bar_width, x + bar_width, y1, fill=color, outline="")
        self._pulse_phase += 1
        self._pulse_job = self.root.after(_PULSE_MS, self._animate_pulse)

    def _refresh_status_labels(self) -> None:
        mic_index = self.config.get("selected_microphone")
        mic_name = "System default"
        if mic_index is not None:
            for mic in list_input_devices():
                if mic.index == mic_index:
                    mic_name = mic.name
                    break
            else:
                mic_name = "System default (previously selected microphone not found)"
        self.idle_mic_var.set(mic_name)
        self.idle_doc_var.set(self.config.get("default_document_name", "PatientNotes.docx"))

        interval = self.config.get("autosave_interval_seconds", 5)
        self.autosave_badge.configure(text=f"🔄 AUTOSAVE EVERY {interval}s")
        self._refresh_last_saved_label()

    def _refresh_last_saved_label(self) -> None:
        folder_setting = Path(self.config.get("default_save_folder", "notes"))
        folder = folder_setting if folder_setting.is_absolute() else get_app_root() / folder_setting
        doc_path = folder / self.config.get("default_document_name", "PatientNotes.docx")
        if doc_path.exists():
            mtime = datetime.fromtimestamp(doc_path.stat().st_mtime)
            self.status_var.set(f"Last saved: {mtime.strftime('%I:%M:%S %p')}")
        else:
            self.status_var.set("Ready")

    def _load_model_background(self) -> None:
        model_dir = get_model_path(self.config.get("whisper_model_size", "small.en"))
        self._engine = TranscriptionEngine(
            model_dir=model_dir,
            compute_type=self.config.get("whisper_compute_type", "int8"),
            on_error=self._on_transcription_error,
        )
        try:
            self._engine.load_model()
        except ModelLoadError as e:
            self._model_load_queue.put(("error", str(e)))
            return
        self._model_load_queue.put(("ready", None))

    def _poll_model_load(self) -> None:
        try:
            status, payload = self._model_load_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_model_load)
            return
        if status == "error":
            self._fatal_model_error(payload)
        else:
            self._on_model_ready()

    def _on_model_ready(self) -> None:
        self.status_var.set("Ready")
        self._set_start_enabled(True)

    def _fatal_model_error(self, message: str) -> None:
        messagebox.showerror("Doctor Voice Notes - Fatal Error", message)
        self.root.destroy()

    def _on_start(self) -> None:
        if self._is_recording or self._engine is None or not self._engine.is_model_loaded:
            return

        try:
            ensure_microphone_available()
        except NoMicrophoneError:
            messagebox.showerror("Doctor Voice Notes", "No microphone detected.")
            return

        device_index = self.config.get("selected_microphone")
        self._recorder = AudioRecorder(
            device_index=device_index,
            on_error=lambda msg: self._audio_warning_queue.put(msg),
        )
        try:
            self._recorder.start()
        except AudioDeviceError as e:
            messagebox.showerror("Doctor Voice Notes", f"Could not open microphone: {e}")
            return

        self._processor = VoiceCommandProcessor()
        self._writer = DocumentWriter(self.config, self._processor)
        self._writer.start_session()

        self._transcript_queue = queue.Queue()
        self._stop_event = threading.Event()

        threading.Thread(
            target=self._engine.transcribe_stream,
            args=(self._recorder, self._transcript_queue),
            daemon=True,
        ).start()
        threading.Thread(
            target=self._writer.run_autosave_loop,
            args=(self._stop_event, self.config.get("autosave_interval_seconds", 5)),
            daemon=True,
        ).start()

        self._is_recording = True
        self.recording_status_var.set("🎙️  Listening...")
        self.status_var.set("Recording started.")
        self._set_transcript_text("")
        self._show_recording_screen()
        self._poll_job = self.root.after(_POLL_MS, self._poll_background_threads)

    def _on_stop(self) -> None:
        if not self._is_recording:
            return
        self.stop_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self.recording_status_var.set("⏳  Finishing transcription...")
        self.status_var.set("Stopping - finishing final transcription and save...")
        self._recorder.stop()

    def _finalize_stop(self) -> None:
        self._stop_event.set()

        def do_final_save():
            self._writer.stop_session()
            save_failed = self._processor.has_pending_text()
            self._finalize_queue.put(save_failed)

        threading.Thread(target=do_final_save, daemon=True).start()
        self.root.after(100, self._poll_finalize)

    def _poll_finalize(self) -> None:
        try:
            save_failed = self._finalize_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_finalize)
            return
        self._after_stop_session(save_failed)

    def _after_stop_session(self, save_failed: bool) -> None:
        self._is_recording = False
        self._set_start_enabled(True)
        self.stop_btn.configure(state="normal")
        self.save_btn.configure(state="normal")
        self._refresh_last_saved_label()
        self._show_idle_screen()

        if save_failed:
            messagebox.showwarning(
                "Doctor Voice Notes",
                "The last few lines of dictation could not be saved to "
                "disk after several attempts.\nPlease check PatientNotes.docx by hand.",
            )
            self.status_var.set("Warning: the final save did not complete.")
        else:
            self.status_var.set("Recording stopped. Note saved.")

        self._recorder = None
        self._writer = None
        self._processor = None
        self._stop_event = None

    def _on_force_save(self) -> None:
        if self._is_recording and self._processor is not None:
            self._processor.process_phrase("save note")
            self.status_var.set("Save requested.")

    def _poll_background_threads(self) -> None:
        try:
            while True:
                item = self._transcript_queue.get_nowait()
                if item is None:
                    self._finalize_stop()
                    return
                result = self._processor.process_phrase(item)
                for warning in result.warnings:
                    self.status_var.set(warning)
                self._set_transcript_text(self._processor.get_full_text())
        except queue.Empty:
            pass

        while not self._audio_warning_queue.empty():
            self.status_var.set(self._audio_warning_queue.get_nowait())

        if self._is_recording:
            self._poll_job = self.root.after(_POLL_MS, self._poll_background_threads)

    def _on_transcription_error(self, message: str) -> None:
        self._audio_warning_queue.put(message)

    def _set_transcript_text(self, text: str) -> None:
        self.transcript_text.configure(state="normal")
        self.transcript_text.delete("1.0", "end")

        lines = text.split("\n")
        last_nonempty = None
        for i in range(len(lines) - 1, -1, -1):
            if lines[i] != "":
                last_nonempty = i
                break

        for i, line in enumerate(lines):
            is_last_written = (i == len(lines) - 1)
            if i == last_nonempty and not line.endswith("."):
                self.transcript_text.insert("end", line, "pending")
            else:
                self.transcript_text.insert("end", line)
            if not is_last_written:
                self.transcript_text.insert("end", "\n")

        self.transcript_text.see("end")
        self.transcript_text.configure(state="disabled")

    def _set_start_enabled(self, enabled: bool) -> None:
        self.start_btn.configure(state="normal" if enabled else "disabled")

    def _open_settings(self) -> None:
        if self._is_recording:
            return
        SettingsDialog(self.root, self.config, on_saved=self._on_settings_saved)

    def _on_settings_saved(self) -> None:
        ctk.set_appearance_mode("Dark" if self.config.get("theme") == "dark" else "Light")
        self.transcript_text.configure(font=(_FONT_FAMILY, self._current_font_size()))
        self.pulse_canvas.configure(bg=self._resolve_color(_BG))
        self._refresh_status_labels()

    def _show_help(self) -> None:
        messagebox.showinfo(
            "Doctor Voice Notes - Help",
            "VOICE COMMANDS\n"
            "  • \"new paragraph\" - blank line\n"
            "  • \"full stop\" - ends the sentence with a period\n"
            "  • \"comma\" - inserts a comma\n"
            "  • \"new patient\" - inserts a Patient / Date / Time block\n"
            "  • \"save note\" - saves immediately\n"
            "  • \"delete last sentence\" - removes the last completed sentence\n\n"
            "KEYBOARD SHORTCUTS\n"
            "  • Ctrl+R - Start recording\n"
            "  • Ctrl+T - Stop recording\n"
            "  • Ctrl+S - Save now\n"
            "  • Ctrl+Q - Exit",
        )

    def _on_close(self) -> None:
        if self._is_recording:
            if not messagebox.askyesno(
                "Doctor Voice Notes",
                "Recording is still in progress. Stop and save before exiting?",
            ):
                return
            if self._poll_job is not None:
                self.root.after_cancel(self._poll_job)
            self._recorder.stop()
            if self._stop_event is not None:
                self._stop_event.set()
            try:
                self._writer.stop_session()
            except Exception as e:
                logger.error(f"Error during final save on exit: {e}")
        self.root.destroy()