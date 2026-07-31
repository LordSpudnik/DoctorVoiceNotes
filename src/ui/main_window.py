"""
main_window.py
===============

Main window for Doctor Voice Notes (PRD Section 8, FR-01 to FR-04, FR-07,
FR-10; PRD Section 17 keyboard shortcuts).

Built on CustomTkinter (a themed wrapper around Tkinter itself - not a
different GUI toolkit), so this file can get rounded buttons, a circular
Start control, and light/dark theming close to the reference screenshots,
while keeping the exact same widget model, event loop, and threading
rules Tkinter already has. See the chat message for why CustomTkinter was
chosen over a full framework swap (e.g. PyQt) at this stage of the
project.

NEW DEPENDENCY: this file requires `customtkinter` (see requirements.txt).
It must be installed before this file will import successfully, and
verified to work under PyInstaller when Phase 7 builds the .exe.

This is the ONLY file that wires the four backend modules together:
    src.audio.recorder          - microphone capture (Phase 2, locked)
    src.transcription.engine    - speech-to-text (Phase 3, locked)
    src.commands.voice_commands - command parsing (Phase 4, locked)
    src.document.writer         - autosaving into .docx (Phase 5, locked)
None of those four files are modified here. This file only calls their
already-public methods - identical wiring to the previous draft of this
file; what changed in this pass is presentation, not behaviour.

------------------------------------------------------------------------
WHAT CHANGED FROM THE PREVIOUS DRAFT, AND WHY
------------------------------------------------------------------------
1. Two-screen layout (Idle "Start Consultation" screen / Recording
   screen), matching the reference images, instead of one static layout
   with buttons that just enable/disable. Implemented as two frames
   inside the same window that are swapped with .pack()/.pack_forget() -
   there is still only ONE window and ONE MainWindow instance; nothing
   about the session lifecycle changed.
2. Circular mic-icon Start button (CTkButton with corner_radius =
   width/2). Uses a text glyph ("MIC") rather than an image file, because
   there are no bundled icon assets in this project yet and the app must
   stay fully offline (no fetching an icon font at runtime). Swapping in
   a real icon later is a cosmetic change - see get_resource_path() in
   paths.py if the user wants to add real .png icons.
3. "Current line" highlighting in the transcript: the last line of
   processor.get_full_text() is shown in italics/accent color if it does
   NOT end in "." - which (per voice_commands.py's own documented
   invariant - see writer.py's module docstring) means it is still an
   open, in-progress sentence. This is computed ENTIRELY from the text
   VoiceCommandProcessor already returns; no changes to Phase 4 were
   needed or made.
4. A decorative "listening" pulse (animated bars on a Canvas) plays
   while recording. IMPORTANT HONESTY NOTE: this is NOT wired to actual
   microphone amplitude. AudioRecorder's audio queue (recorder.py) is
   already fully consumed by the transcription thread; exposing real
   audio levels to the UI would mean changing recorder.py, which is a
   locked, user-confirmed Phase 2 file. Flagging this as a deliberate
   scope decision, not an oversight - see the chat message for the
   "wire real levels" follow-up option if the doctor wants it later.
5. Removed from the reference design, because there is no backend for
   them and PRD Section 4 explicitly EXCLUDES the capability:
     - Patient IDs / "Patient Consult #4920" header (no patient database)
     - Left sidebar (search/people icon, archive icon, session list,
       "+" new-session button) - implies multiple saved sessions/patients
     - Top-left user avatar - implies user accounts (explicitly excluded)
     - "Emergency Stop" button on the idle screen - there is nothing
       running to stop when idle; the real Stop control only appears
       once a session is recording (see the Recording screen)
   These are flagged again, more fully, in the chat reply - the
   reference mockup is a generic product template, not a rendering of
   this app's actual scope.
6. Kept and re-skinned (real backend, real settings.json keys):
     - Start / Stop (FR-02 / FR-07)
     - Checkpoint Save = the existing Ctrl+S "force save" action (FR-08's
       "save note" command, reused verbatim)
     - Settings gear icon (FR-09)
     - Theme toggle (light/dark - settings.json "theme" key, Phase 1)
     - "Offline mode" badge - PRD Section 15 ("no internet, ever") is
       always true for this app, so this is a static, accurate label,
       not a fake status light
     - Autosave badge - reflects the real autosave_interval_seconds
       setting and the real run_autosave_loop() state
     - Microphone / save folder / document name / last-saved labels
       (Section 8), refreshed from ConfigManager
7. Added a small Help dialog (question-mark icon) - static text listing
   the real voice commands (FR-08) and keyboard shortcuts (Section 17).
   No new backend needed; it only reads from strings already true of
   this app.

------------------------------------------------------------------------
THREADING (unchanged from the previous draft - see it for full detail)
------------------------------------------------------------------------
Background threads never touch widgets directly. They post plain values
onto queue.Queue objects; only the Tkinter/CTk main-thread .after() loop
touches widgets. This is required, not optional - CustomTkinter widgets
sit on top of real Tkinter widgets and have the exact same "main thread
only" rule.
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
_PULSE_MS = 120  # decorative "listening" animation tick - see module docstring point 4

_FONT_FAMILY = "Segoe UI"

# Clinical Elegance palette - same intent as the reference screenshots'
# indigo/mint palette, expressed as CustomTkinter (light_color, dark_color)
# tuples so ctk's built-in light/dark switch (appearance mode) drives the
# whole app instead of us manually re-coloring every widget by hand.
_PRIMARY = ("#3525CD", "#8B85FF")
_ON_PRIMARY = ("#FFFFFF", "#0B1C30")
_DANGER = ("#BA1A1A", "#FFB3B6")
_ON_DANGER = ("#FFFFFF", "#40000C")
_RECORDING = ("#006C49", "#4EDEA3")
_RECORDING_BG = ("#DFF9EC", "#0F3C30")
_CARD = ("#FFFFFF", "#213145")
_BG = ("#F4F6FF", "#0B1C30")
_TEXT = ("#0B1C30", "#EAF1FF")
_TEXT_VARIANT = ("#5A5872", "#B9C3DA")
_BORDER = ("#DEDCF0", "#33415B")
_TRANSCRIPT_BG = ("#EFF4FF", "#16233A")
_PENDING_ACCENT = ("#3525CD", "#8B85FF")


class MainWindow:
    """Owns the CTk root window and the lifecycle of one recording session
    at a time. See module docstring for the full design."""

    def __init__(self, root: "ctk.CTk", config: ConfigManager):
        self.root = root
        self.config = config

        ctk.set_appearance_mode("Dark" if config.get("theme") == "dark" else "Light")
        ctk.set_default_color_theme("blue")

        # Session objects - all None while Idle, all created fresh on each
        # Start press (unchanged design decision from the previous draft:
        # matches writer.py's own documented assumption that a fresh
        # session never inherits a stale pending paragraph).
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

        # FR-01: load the speech model in the background so the window
        # appears immediately; Start stays disabled until it's ready.
        self._set_start_enabled(False)
        self.status_var.set("Loading speech model...")
        threading.Thread(target=self._load_model_background, daemon=True).start()
        self.root.after(100, self._poll_model_load)

    # ------------------------------------------------------------------
    # WINDOW / WIDGET CONSTRUCTION
    # ------------------------------------------------------------------
    def _build_window(self) -> None:
        self.root.title("Doctor Voice Notes")
        width = self.config.get("window_width", 900)
        height = self.config.get("window_height", 650)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(760, 560)
        self.root.configure(fg_color=_BG)

    def _build_widgets(self) -> None:
        pad = 20

        # ---------------- header (always visible) ----------------
        self.header = ctk.CTkFrame(self.root, fg_color="transparent")
        self.header.pack(fill="x", padx=pad, pady=(pad, 8))

        self.title_label = ctk.CTkLabel(
            self.header, text="Doctor Voice Notes",
            font=(_FONT_FAMILY, 22, "bold"), text_color=_PRIMARY,
        )
        self.title_label.pack(side="left")

        icon_row = ctk.CTkFrame(self.header, fg_color="transparent")
        icon_row.pack(side="right")

        self.help_btn = ctk.CTkButton(
            icon_row, text="?", width=36, height=36, corner_radius=18,
            font=(_FONT_FAMILY, 14, "bold"), fg_color=_CARD, text_color=_TEXT,
            hover_color=_BORDER, command=self._show_help,
        )
        self.help_btn.pack(side="right", padx=(8, 0))

        self.theme_btn = ctk.CTkButton(
            icon_row, text="Dark/Light", width=90, height=36, corner_radius=18,
            font=(_FONT_FAMILY, 12), fg_color=_CARD, text_color=_TEXT,
            hover_color=_BORDER, command=self._toggle_theme,
        )
        self.theme_btn.pack(side="right", padx=(8, 0))

        self.settings_btn = ctk.CTkButton(
            icon_row, text="Settings", width=90, height=36, corner_radius=18,
            font=(_FONT_FAMILY, 12), fg_color=_CARD, text_color=_TEXT,
            hover_color=_BORDER, command=self._open_settings,
        )
        self.settings_btn.pack(side="right")

        # ---------------- badge row (offline / autosave) ----------------
        badge_row = ctk.CTkFrame(self.root, fg_color="transparent")
        badge_row.pack(fill="x", padx=pad, pady=(0, 8))

        self.offline_badge = ctk.CTkLabel(
            badge_row, text="\u25CF  OFFLINE MODE", font=(_FONT_FAMILY, 11, "bold"),
            text_color=_TEXT_VARIANT,
        )
        self.offline_badge.pack(side="left")

        self.autosave_badge = ctk.CTkLabel(
            badge_row, text="", font=(_FONT_FAMILY, 11, "bold"),
            text_color=_RECORDING,
        )
        self.autosave_badge.pack(side="left", padx=(16, 0))

        # ---------------- content area: idle screen / recording screen ----------------
        self.content = ctk.CTkFrame(self.root, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=pad, pady=(0, 8))

        self._build_idle_screen()
        self._build_recording_screen()

        # ---------------- status bar (Section 8) ----------------
        self.status_var = tk.StringVar(value="Ready")
        self.status_bar = ctk.CTkLabel(
            self.root, textvariable=self.status_var, font=(_FONT_FAMILY, 11),
            anchor="w", text_color=_TEXT_VARIANT,
        )
        self.status_bar.pack(fill="x", side="bottom", padx=pad, pady=(0, 10))

    # ---------------- IDLE SCREEN ("Start Consultation") ----------------
    def _build_idle_screen(self) -> None:
        self.idle_frame = ctk.CTkFrame(self.content, fg_color="transparent")

        spacer_top = ctk.CTkFrame(self.idle_frame, fg_color="transparent", height=10)
        spacer_top.pack()

        self.start_btn = ctk.CTkButton(
            self.idle_frame, text="MIC", width=160, height=160, corner_radius=80,
            font=(_FONT_FAMILY, 26, "bold"), fg_color=_PRIMARY, text_color=_ON_PRIMARY,
            hover_color=_PRIMARY, command=self._on_start,
        )
        self.start_btn.pack(pady=(30, 24))

        ctk.CTkLabel(
            self.idle_frame, text="Start Recording", font=(_FONT_FAMILY, 26, "bold"),
            text_color=_TEXT,
        ).pack()
        ctk.CTkLabel(
            self.idle_frame, text="Press the microphone to begin dictating this note.",
            font=(_FONT_FAMILY, 13), text_color=_TEXT_VARIANT,
        ).pack(pady=(4, 24))

        info_card = ctk.CTkFrame(self.idle_frame, fg_color=_CARD, corner_radius=16)
        info_card.pack(pady=8)
        info_inner = ctk.CTkFrame(info_card, fg_color="transparent")
        info_inner.pack(padx=28, pady=20)

        mic_col = ctk.CTkFrame(info_inner, fg_color="transparent")
        mic_col.grid(row=0, column=0, padx=24, sticky="w")
        ctk.CTkLabel(mic_col, text="MICROPHONE", font=(_FONT_FAMILY, 10, "bold"),
                     text_color=_TEXT_VARIANT).pack(anchor="w")
        self.idle_mic_var = tk.StringVar()
        ctk.CTkLabel(mic_col, textvariable=self.idle_mic_var, font=(_FONT_FAMILY, 14, "bold"),
                     text_color=_TEXT).pack(anchor="w")

        doc_col = ctk.CTkFrame(info_inner, fg_color="transparent")
        doc_col.grid(row=0, column=1, padx=24, sticky="w")
        ctk.CTkLabel(doc_col, text="DOCUMENT", font=(_FONT_FAMILY, 10, "bold"),
                     text_color=_TEXT_VARIANT).pack(anchor="w")
        self.idle_doc_var = tk.StringVar()
        ctk.CTkLabel(doc_col, textvariable=self.idle_doc_var, font=(_FONT_FAMILY, 14, "bold"),
                     text_color=_TEXT).pack(anchor="w")

    # ---------------- RECORDING SCREEN ----------------
    def _build_recording_screen(self) -> None:
        self.recording_frame = ctk.CTkFrame(self.content, fg_color="transparent")

        top_row = ctk.CTkFrame(self.recording_frame, fg_color="transparent")
        top_row.pack(fill="x", pady=(4, 0))

        self.recording_status_var = tk.StringVar(value="Listening...")
        self.recording_pill = ctk.CTkLabel(
            top_row, textvariable=self.recording_status_var, font=(_FONT_FAMILY, 13, "bold"),
            text_color=_RECORDING, fg_color=_RECORDING_BG, corner_radius=14,
            padx=14, pady=6,
        )
        self.recording_pill.pack()

        # decorative pulse (see module docstring point 4 - not audio-reactive)
        self.pulse_canvas = tk.Canvas(
            self.recording_frame, height=90, highlightthickness=0, bd=0,
        )
        self.pulse_canvas.pack(pady=(14, 10))

        # transcript card
        transcript_card = ctk.CTkFrame(self.recording_frame, fg_color=_CARD, corner_radius=16)
        transcript_card.pack(fill="both", expand=True)

        self.transcript_text = ctk.CTkTextbox(
            transcript_card, wrap="word", state="disabled",
            font=(_FONT_FAMILY, self._current_font_size()),
            fg_color=_TRANSCRIPT_BG, text_color=_TEXT,
            corner_radius=12,
        )
        self.transcript_text.pack(fill="both", expand=True, padx=14, pady=14)
        self.transcript_text.tag_config("pending", foreground=self._resolve_color(_PENDING_ACCENT))

        # controls: Checkpoint Save / Stop Recording
        controls = ctk.CTkFrame(self.recording_frame, fg_color="transparent")
        controls.pack(fill="x", pady=(14, 4))

        self.save_btn = ctk.CTkButton(
            controls, text="Checkpoint Save", font=(_FONT_FAMILY, 15, "bold"),
            height=52, corner_radius=26, fg_color=_CARD, text_color=_PRIMARY,
            border_width=2, border_color=_PRIMARY, hover_color=_BORDER,
            command=self._on_force_save,
        )
        self.save_btn.pack(side="left", fill="x", expand=True, padx=(0, 12))

        self.stop_btn = ctk.CTkButton(
            controls, text="\u25A0  Stop Recording", font=(_FONT_FAMILY, 15, "bold"),
            height=52, corner_radius=26, fg_color=_DANGER, text_color=_ON_DANGER,
            hover_color=_DANGER, command=self._on_stop,
        )
        self.stop_btn.pack(side="left", fill="x", expand=True)

    def _bind_shortcuts(self) -> None:
        """PRD Section 17: Ctrl+R Start, Ctrl+S Force save, Ctrl+T Stop,
        Ctrl+Q Exit."""
        self.root.bind("<Control-r>", lambda e: self._on_start())
        self.root.bind("<Control-R>", lambda e: self._on_start())
        self.root.bind("<Control-t>", lambda e: self._on_stop())
        self.root.bind("<Control-T>", lambda e: self._on_stop())
        self.root.bind("<Control-s>", lambda e: self._on_force_save())
        self.root.bind("<Control-S>", lambda e: self._on_force_save())
        self.root.bind("<Control-q>", lambda e: self._on_close())
        self.root.bind("<Control-Q>", lambda e: self._on_close())

    # ------------------------------------------------------------------
    # SCREEN SWITCHING
    # ------------------------------------------------------------------
    def _show_idle_screen(self) -> None:
        self.recording_frame.pack_forget()
        self.idle_frame.pack(fill="both", expand=True)
        self._stop_pulse()

    def _show_recording_screen(self) -> None:
        self.idle_frame.pack_forget()
        self.recording_frame.pack(fill="both", expand=True)
        self._start_pulse()

    # ------------------------------------------------------------------
    # THEME
    # ------------------------------------------------------------------
    def _toggle_theme(self) -> None:
        new_theme = "light" if self.config.get("theme") == "dark" else "dark"
        self.config.set("theme", new_theme)
        self.config.save()
        ctk.set_appearance_mode("Dark" if new_theme == "dark" else "Light")
        self.transcript_text.tag_config("pending", foreground=self._resolve_color(_PENDING_ACCENT))

    @staticmethod
    def _resolve_color(pair) -> str:
        return pair[1] if ctk.get_appearance_mode() == "Dark" else pair[0]

    def _current_font_size(self) -> int:
        base = self.config.get("font_size", 18)
        return base + 6 if self.config.get("large_text_mode", False) else base

    # ------------------------------------------------------------------
    # DECORATIVE "LISTENING" PULSE (see module docstring point 4)
    # ------------------------------------------------------------------
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
        height = 90
        bar_count = 20
        bar_width = 6
        gap = (width - bar_count * bar_width) / (bar_count + 1)
        color = self._resolve_color(_RECORDING)
        for i in range(bar_count):
            x = gap + i * (bar_width + gap)
            # Smooth traveling-wave pattern - purely decorative.
            level = (math.sin(self._pulse_phase / 4 + i * 0.6) + 1) / 2
            bar_height = 10 + level * (height - 20)
            y0 = (height - bar_height) / 2
            y1 = y0 + bar_height
            c.create_rectangle(x, y0, x + bar_width, y1, fill=color, outline="")
        self._pulse_phase += 1
        self._pulse_job = self.root.after(_PULSE_MS, self._animate_pulse)

    # ------------------------------------------------------------------
    # STATUS LABEL REFRESH (Section 8: mic / save location / document)
    # ------------------------------------------------------------------
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
        self.autosave_badge.configure(text=f"\u25CF  AUTOSAVE EVERY {interval}s")
        self._refresh_last_saved_label()

    def _refresh_last_saved_label(self) -> None:
        """Non-invasive way to show 'last saved' without writer.py
        exposing a timestamp: reads the on-disk file's own mtime."""
        folder_setting = Path(self.config.get("default_save_folder", "notes"))
        folder = folder_setting if folder_setting.is_absolute() else get_app_root() / folder_setting
        doc_path = folder / self.config.get("default_document_name", "PatientNotes.docx")
        if doc_path.exists():
            mtime = datetime.fromtimestamp(doc_path.stat().st_mtime)
            self.status_var.set(f"Last saved: {mtime.strftime('%I:%M:%S %p')}")
        else:
            self.status_var.set("Ready")

    # ------------------------------------------------------------------
    # MODEL LOADING (FR-01, Section 14: failure -> error + terminate)
    # ------------------------------------------------------------------
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
        """Section 14: model load failure -> display error and TERMINATE."""
        messagebox.showerror("Doctor Voice Notes - Fatal Error", message)
        self.root.destroy()

    # ------------------------------------------------------------------
    # START (FR-02)
    # ------------------------------------------------------------------
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
        self.recording_status_var.set("\u25CF  Listening...")
        self.status_var.set("Recording started.")
        self._set_transcript_text("")
        self._show_recording_screen()
        self._poll_job = self.root.after(_POLL_MS, self._poll_background_threads)

    # ------------------------------------------------------------------
    # STOP (FR-07)
    # ------------------------------------------------------------------
    def _on_stop(self) -> None:
        if not self._is_recording:
            return
        self.stop_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self.recording_status_var.set("\u25CF  Finishing transcription...")
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
                "disk after several attempts (the file may be locked by "
                "another program, such as antivirus software or a "
                "cloud-sync client).\n\nPlease check the save folder is "
                "not being locked by another program, then check "
                "PatientNotes.docx by hand before dictating again.",
            )
            self.status_var.set("Warning: the final save did not complete.")
        else:
            self.status_var.set("Recording stopped. Note saved.")

        self._recorder = None
        self._writer = None
        self._processor = None
        self._stop_event = None

    def _on_force_save(self) -> None:
        """Checkpoint Save / Ctrl+S. Reuses the existing public "save
        note" voice command instead of reaching into VoiceCommandProcessor's
        private state."""
        if self._is_recording and self._processor is not None:
            self._processor.process_phrase("save note")
            self.status_var.set("Save requested.")

    # ------------------------------------------------------------------
    # POLLING (main-thread-only access to widgets)
    # ------------------------------------------------------------------
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
        """Writes the transcript, italicizing/highlighting the last line
        if it is still an open (un-punctuated, in-progress) sentence -
        see module docstring point 3 for why this is safe to infer
        purely from the text itself."""
        self.transcript_text.configure(state="normal")
        self.transcript_text.delete("1.0", "end")

        lines = text.split("\n")
        # Find the last non-empty line - that is the only one that can
        # still be "open" (see writer.py's own documented invariant).
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

    # ------------------------------------------------------------------
    # SETTINGS (FR-09) - only reachable while Idle
    # ------------------------------------------------------------------
    def _open_settings(self) -> None:
        if self._is_recording:
            return
        SettingsDialog(self.root, self.config, on_saved=self._on_settings_saved)

    def _on_settings_saved(self) -> None:
        ctk.set_appearance_mode("Dark" if self.config.get("theme") == "dark" else "Light")
        self.transcript_text.configure(font=(_FONT_FAMILY, self._current_font_size()))
        self._refresh_status_labels()

    # ------------------------------------------------------------------
    # HELP (question-mark icon - static content, no new backend)
    # ------------------------------------------------------------------
    def _show_help(self) -> None:
        messagebox.showinfo(
            "Doctor Voice Notes - Help",
            "VOICE COMMANDS\n"
            "  \u2022 \"new paragraph\" - blank line\n"
            "  \u2022 \"full stop\" - ends the sentence with a period\n"
            "  \u2022 \"comma\" - inserts a comma\n"
            "  \u2022 \"new patient\" - inserts a Patient / Date / Time block\n"
            "  \u2022 \"save note\" - saves immediately\n"
            "  \u2022 \"delete last sentence\" - removes the last completed, "
            "not-yet-saved sentence\n\n"
            "KEYBOARD SHORTCUTS\n"
            "  \u2022 Ctrl+R - Start recording\n"
            "  \u2022 Ctrl+T - Stop recording\n"
            "  \u2022 Ctrl+S - Save now\n"
            "  \u2022 Ctrl+Q - Exit",
        )

    # ------------------------------------------------------------------
    # EXIT (FR-10 / Ctrl+Q)
    # ------------------------------------------------------------------
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
            except Exception as e:  # pragma: no cover - best-effort on exit
                logger.error(f"Error during final save on exit: {e}")
        self.root.destroy()