"""
writer.py
=========

Writes the doctor's dictated notes into a Microsoft Word (.docx) document
on disk, per PRD FR-05 (Automatic Save), FR-06 (Word Document Generation),
FR-07 (Stop Recording final save), and Section 11 (Document Format).

This module is the consumer of src.commands.voice_commands's
VoiceCommandProcessor. It knows nothing about audio, VAD, or Whisper - it
only calls processor.get_pending_text() / mark_saved() / has_pending_text()
/ consume_save_request(), and turns whatever text comes back into
python-docx paragraphs. See the Phase 4 handoff brief, Section 5, for the
open interface question this module exists to resolve.
"""

import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from docx import Document
from docx.text.paragraph import Paragraph

from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger
from src.utils.paths import get_app_root

logger = get_logger(__name__)


_MAX_SAVE_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 1.0
_LOOP_POLL_SECONDS = 0.25


class DocumentWriter:
    """
    Owns the on-disk .docx file for the current recording session and the
    in-memory python-docx Document object backing it.
    """

    def __init__(
        self,
        config: ConfigManager,
        processor,
        clock: Callable[[], datetime] = datetime.now,
    ):
        self._config = config
        self._processor = processor
        self._clock = clock

        self._doc: Optional[Document] = None
        self._doc_path: Optional[Path] = None
        self._pending_paragraph: Optional[Paragraph] = None

    # ------------------------------------------------------------------
    # SESSION LIFECYCLE
    # ------------------------------------------------------------------
    def start_session(self) -> None:
        self._doc_path = self._resolve_document_path()

        if self._doc_path.exists():
            try:
                self._doc = Document(str(self._doc_path))
                logger.info(f"Opened existing document for appending: {self._doc_path}")
            except Exception as e:
                logger.error(
                    f"Existing document at {self._doc_path} could not be "
                    f"opened ({e}). Backing it up and starting a fresh "
                    f"document so the session can still proceed."
                )
                self._backup_unreadable_document()
                self._doc = Document()
        else:
            self._doc = Document()
            logger.info(f"Creating new document: {self._doc_path}")

        self._pending_paragraph = None

        self._write_session_header()
        if not self._save_to_disk():
            logger.error(
                f"Could not write the initial document to {self._doc_path} "
                f"at session start - will keep retrying on the next "
                f"autosave cycle."
            )

    def autosave(self) -> bool:
        if self._doc is None:
            raise RuntimeError("autosave() called before start_session().")

        if not self._processor.has_pending_text():
            return False

        pending_text = self._processor.get_pending_text()
        pending_paragraph_before = self._pending_paragraph
        mutations = self._write_pending_text(pending_text)

        if self._save_to_disk():
            self._processor.mark_saved()
            logger.info("Autosave: wrote and saved new content.")
            return True

        self._rollback(mutations, pending_paragraph_before)
        logger.error(
            "Autosave: could not persist to disk after retries. Rolled "
            "back in-memory changes; this text remains pending and will "
            "be retried on the next autosave cycle."
        )
        return False

    def stop_session(self) -> None:
        if self._doc is None:
            logger.warning("stop_session() called before start_session(); nothing to do.")
            return

        if self._processor.has_pending_text():
            success = self.autosave()
            if not success:
                logger.error(
                    "FR-07 final save on Stop FAILED after retries. "
                    "Dictated text exists only in memory. The UI layer "
                    "must warn the doctor rather than silently return to "
                    "Idle."
                )
        else:
            self._save_to_disk()

        logger.info("Recording session stopped; final save attempted.")

    # ------------------------------------------------------------------
    # AUTOSAVE LOOP
    # ------------------------------------------------------------------
    def run_autosave_loop(self, stop_event: threading.Event, interval_seconds: float) -> None:
        elapsed = 0.0
        while not stop_event.is_set():
            if stop_event.wait(timeout=_LOOP_POLL_SECONDS):
                break
            elapsed += _LOOP_POLL_SECONDS
            if self._processor.consume_save_request() or elapsed >= interval_seconds:
                elapsed = 0.0
                self.autosave()
        logger.info("Autosave loop stopped.")

    # ------------------------------------------------------------------
    # PATH RESOLUTION (FR-09 settings)
    # ------------------------------------------------------------------
    def _resolve_document_path(self) -> Path:
        folder_setting = Path(self._config.get("default_save_folder", "notes"))
        folder = folder_setting if folder_setting.is_absolute() else get_app_root() / folder_setting
        folder.mkdir(parents=True, exist_ok=True)

        doc_name = self._config.get("default_document_name", "PatientNotes.docx")
        return folder / doc_name

    # ------------------------------------------------------------------
    # SESSION HEADER (Section 11)
    # ------------------------------------------------------------------
    def _write_session_header(self) -> None:
        now = self._clock()
        date_str = now.strftime("%d %B %Y")
        time_str = now.strftime("%I:%M %p")
        self._doc.add_paragraph(date_str)
        self._doc.add_paragraph(time_str)
        self._doc.add_paragraph("")  # blank line before notes (Sec. 11 example)
        logger.info(f"Session header written: {date_str} {time_str}")

    # ------------------------------------------------------------------
    # CORE WRITE ALGORITHM
    # ------------------------------------------------------------------
    def _write_pending_text(self, text: str) -> list[tuple]:
        """
        Writes `text` (as returned by processor.get_pending_text()) into
        self._doc, extending the still-open paragraph from a previous
        cycle where applicable instead of duplicating it.
        
        MODIFIED:
          - No extra blank lines are generated for 'new paragraph'.
          - Consecutive new lines simply appear immediately on the next line.
        """
        mutations: list[tuple] = []
        lines = text.split("\n")
        last_index = len(lines) - 1

        for i, line in enumerate(lines):
            if line == "":
                # An explicitly empty string line (e.g. around PATIENT_HEADER blocks)
                # is written as a blank paragraph boundary.
                paragraph = self._doc.add_paragraph("")
                mutations.append(("new_paragraph", paragraph))
                self._pending_paragraph = None
                continue

            if i == 0 and self._pending_paragraph is not None:
                # Continuation of the paragraph left open by a previous
                # autosave cycle.
                run_text = f" {line}" if self._pending_paragraph.text else line
                run = self._pending_paragraph.add_run(run_text)
                mutations.append(("extend_run", self._pending_paragraph, run))
                paragraph = self._pending_paragraph
            else:
                # Starts on the very next line without any empty line gap
                paragraph = self._doc.add_paragraph(line)
                mutations.append(("new_paragraph", paragraph))

            # Only the LAST line of a batch can still be "open"
            if i == last_index and not line.endswith("."):
                self._pending_paragraph = paragraph
            else:
                self._pending_paragraph = None

        return mutations

    def _rollback(self, mutations: list[tuple], pending_paragraph_before: Optional[Paragraph]) -> None:
        for mutation in reversed(mutations):
            if mutation[0] == "new_paragraph":
                paragraph = mutation[1]
                paragraph._element.getparent().remove(paragraph._element)
            elif mutation[0] == "extend_run":
                _, _paragraph, run = mutation
                run._element.getparent().remove(run._element)
        self._pending_paragraph = pending_paragraph_before

    # ------------------------------------------------------------------
    # DISK I/O
    # ------------------------------------------------------------------
    def _save_to_disk(self) -> bool:
        for attempt in range(1, _MAX_SAVE_ATTEMPTS + 1):
            try:
                self._doc.save(str(self._doc_path))
                return True
            except OSError as e:
                logger.error(
                    f"Save attempt {attempt}/{_MAX_SAVE_ATTEMPTS} failed "
                    f"for {self._doc_path}: {e}"
                )
                if attempt < _MAX_SAVE_ATTEMPTS:
                    time.sleep(_RETRY_DELAY_SECONDS)
        return False

    def _backup_unreadable_document(self) -> None:
        timestamp = self._clock().strftime("%Y%m%d-%H%M%S")
        backup_path = self._doc_path.with_suffix(f".docx.broken-{timestamp}")
        try:
            shutil.copy2(self._doc_path, backup_path)
            logger.warning(f"Unreadable document backed up to {backup_path}")
        except OSError as e:
            logger.error(f"Could not back up the unreadable document: {e}")