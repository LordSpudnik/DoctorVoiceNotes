"""
voice_commands.py
==================

Parses recognised speech (as produced one phrase at a time by
src.transcription.engine.TranscriptionEngine) into structured document
content, per PRD FR-08 (Voice Commands).

Supported commands (spoken anywhere within a phrase, case-insensitive):
    "new paragraph"         -> inserts a blank line
    "full stop"             -> inserts "." and closes the current sentence
    "comma"                 -> inserts ","
    "new patient"           -> inserts a "Patient / <date> / <time>" block
    "save note"             -> requests an immediate out-of-cycle save
    "delete last sentence"  -> removes the most recently completed sentence,
                               only if it has not already been autosaved

Everything else is treated as normal dictation text (FR-08: "Unknown
commands are treated as normal speech").

WHY WHISPER'S OWN PUNCTUATION IS STRIPPED BEFORE PARSING
---------------------------------------------------------
faster-whisper is trained to add its own punctuation and capitalisation
heuristically, independent of anything the doctor says out loud. If we
did not strip that out, we would get silent double-punctuation (Whisper
writes a "." AND the doctor says "full stop" -> ".." ) and the sentence
boundaries this module tracks would drift out of sync with what is
actually in the text. Since the PRD explicitly wants punctuation to be
command-driven (FR-08), we treat Whisper's automatic punctuation as noise
and strip it before doing anything else. This is a deliberate design
choice, not an oversight - see the flagged risk in the handoff notes.

WHY THIS MODULE OWNS "SAVED vs PENDING" STATE
-----------------------------------------------
FR-08 requires "delete last sentence" to only remove a sentence that has
not yet reached the next autosave. That means this module - not the
document writer (Phase 5) - must be the one tracking exactly which
recognised content has already been handed off and saved, because it is
the only place that knows where sentence boundaries actually are. Phase
5 will call mark_saved() immediately after a successful write; from that
point on, none of the content included in that write can be deleted by
a subsequent "delete last sentence" command, even if a sentence spanning
that boundary is later closed by "full stop" - see delete_last_sentence()
for exactly how that boundary case is handled.

INTERFACE CONTRACT WITH PHASE 5 (document writer, not yet built)
-------------------------------------------------------------------
This module deliberately does NOT talk to python-docx or know anything
about .docx paragraphs. It exposes plain text:

    get_pending_text()   -> everything recognised since the last mark_saved(),
                             rendered as paragraphs separated by "\n".
    mark_saved()          -> call this immediately after Phase 5 successfully
                             writes get_pending_text() to disk.
    get_full_text()       -> everything recognised so far (saved + pending),
                             for the live transcript pane (FR-04).
    consume_save_request()-> True once if "save note" was heard since the
                             last check (resets after reading).

One thing Phase 5 will need to solve, and that this module deliberately
leaves open: get_pending_text() includes the paragraph currently being
dictated even if it has no closing boundary yet (needed so autosave does
not lose an unfinished sentence if the app crashes mid-dictation, per
FR-05/FR-07). That means the SAME in-progress paragraph text can appear
in more than one consecutive autosave call, each time slightly longer.
Phase 5 must decide how to extend the last paragraph it already wrote
rather than duplicating it (e.g. by tracking the python-docx Paragraph
object it last wrote to). That decision belongs to Phase 5 and is not
solved here - flagging it now so it is not a surprise in Phase 5.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Callable, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


# ----------------------------------------------------------------------------
# COMMAND GRAMMAR
# ----------------------------------------------------------------------------
# Every recognised phrase is scanned left-to-right for these phrases. Because
# they are complete, mutually-exclusive multi-word phrases (no command is a
# prefix of another), order within the alternation does not affect matching -
# re.finditer walks the string once and finds whichever alternative starts
# earliest, which is exactly the "commands can appear anywhere in the middle
# of dictated text" behaviour FR-08 needs.
# ----------------------------------------------------------------------------


class CommandType(Enum):
    NEW_PARAGRAPH = auto()
    FULL_STOP = auto()
    COMMA = auto()
    NEW_PATIENT = auto()
    SAVE_NOTE = auto()
    DELETE_LAST_SENTENCE = auto()


# Maps each command's regex group name to its enum value. Group names must
# be valid Python identifiers, hence underscores instead of spaces.
_COMMAND_GROUPS: dict[str, CommandType] = {
    "new_paragraph": CommandType.NEW_PARAGRAPH,
    "full_stop": CommandType.FULL_STOP,
    "comma": CommandType.COMMA,
    "new_patient": CommandType.NEW_PATIENT,
    "save_note": CommandType.SAVE_NOTE,
    "delete_last_sentence": CommandType.DELETE_LAST_SENTENCE,
}

_COMMAND_PATTERN = re.compile(
    r"(?P<new_paragraph>\bnew paragraph\b)"
    r"|(?P<full_stop>\bfull stop\b)"
    r"|(?P<comma>\bcomma\b)"
    r"|(?P<new_patient>\bnew patient\b)"
    r"|(?P<save_note>\bsave note\b)"
    r"|(?P<delete_last_sentence>\bdelete last sentence\b)",
    re.IGNORECASE,
)

# Strips punctuation Whisper may add on its own (see module docstring).
# Deliberately keeps apostrophes (contractions like "doesn't") and hyphens.
_STRIP_PUNCTUATION = re.compile(r"[.,!?;:]")
_COLLAPSE_WHITESPACE = re.compile(r"\s+")


# ----------------------------------------------------------------------------
# INTERNAL SEGMENT MODEL
# ----------------------------------------------------------------------------
# The processor's memory is a flat, ordered list of Segments. This is the
# structure delete_last_sentence() operates on directly (see its docstring),
# and render_segments() below is the one function that turns segments back
# into displayable/saveable text - both get_pending_text() and
# get_full_text() are thin wrappers around it over different slices of
# the same list, so there is exactly one place that defines what a rendered
# sentence/paragraph looks like.
# ----------------------------------------------------------------------------


class _SegType(Enum):
    TEXT = auto()             # a chunk of plain dictation words
    FULL_STOP = auto()        # closes the current sentence with "."
    COMMA = auto()            # inserts "," (does NOT close a sentence)
    PARAGRAPH_BREAK = auto()  # closes the paragraph + inserts a blank line
    PATIENT_HEADER = auto()   # closes the paragraph + inserts header block

# Boundary types that both close a sentence AND count as a valid deletion
# target for "delete last sentence". COMMA is intentionally excluded - a
# comma never ends a sentence.
_BOUNDARY_TYPES = (_SegType.FULL_STOP, _SegType.PARAGRAPH_BREAK, _SegType.PATIENT_HEADER)


@dataclass
class _Segment:
    type: _SegType
    text: str = ""                              # for TEXT
    header_lines: list[str] = field(default_factory=list)  # for PATIENT_HEADER


@dataclass
class ProcessResult:
    """Returned by process_phrase() so a caller (e.g. the Phase 6 UI) can
    react to what happened - flash "Saved", show a warning dialog, etc.
    Deliberately plain data, no behaviour."""
    commands_executed: list[CommandType] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _capitalize_first(text: str) -> str:
    """Capitalises only the first alphabetic character, leaving the rest of
    the text untouched (does not force-lowercase the remainder, so any
    doctor-spoken proper nouns Whisper happened to capitalise are kept)."""
    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1:]
    return text


def render_segments(segments: list[_Segment]) -> str:
    """
    Turns a list of segments into plain text: one paragraph per line,
    joined with "\n". Blank lines from "new paragraph" / "new patient"
    are represented as empty-string paragraphs, so joining with a single
    "\n" (not "\n\n") already produces the correct visual blank line.
    This function is intentionally pure (no side effects, no dependency
    on processor state) so it is trivial to unit test on its own.
    """
    paragraphs: list[str] = []
    current = ""

    def close_paragraph():
        nonlocal current
        # Only emit the paragraph being closed if it actually has content.
        # Without this guard, closing an already-empty "current" (e.g. two
        # boundary commands back-to-back, or a boundary as the very first
        # thing in the document) would insert a spurious extra blank line
        # on top of the one the boundary itself is about to add below.
        if current:
            paragraphs.append(current)
        current = ""

    for seg in segments:
        if seg.type == _SegType.TEXT:
            current = f"{current} {seg.text}" if current else seg.text
        elif seg.type == _SegType.FULL_STOP:
            current += "."
            # PRD Section 11's worked example shows every completed
            # sentence on its own line (not run together in one block),
            # so "full stop" ends the current line, not just the sentence.
            # "new paragraph" (below) is reserved for an ADDITIONAL blank
            # line on top of that, for grouping several sentences into a
            # visually distinct block - matching how the two commands are
            # described as separate things in FR-08.
            close_paragraph()
        elif seg.type == _SegType.COMMA:
            current += ","
        elif seg.type == _SegType.PARAGRAPH_BREAK:
            close_paragraph()
            paragraphs.append("")  # the blank line itself
        elif seg.type == _SegType.PATIENT_HEADER:
            close_paragraph()
            paragraphs.append("")
            paragraphs.extend(seg.header_lines)
            paragraphs.append("")

    if current:
        # Trailing in-progress paragraph (no closing boundary yet) - still
        # included, per FR-05's crash-safety rationale (see module docstring).
        paragraphs.append(current)

    return "\n".join(paragraphs)


class VoiceCommandProcessor:
    """
    Stateful parser: feed it recognised phrases one at a time via
    process_phrase(); read accumulated text back out via get_pending_text()
    / get_full_text(). See module docstring for the full interface contract.
    """

    def __init__(self, clock: Callable[[], datetime] = datetime.now):
        """
        Args:
            clock: injectable clock for "new patient" header timestamps.
                   Defaults to the real datetime.now, but tests pass a
                   fixed fake so assertions don't depend on wall-clock time
                   - same dependency-injection pattern engine.py uses for
                   its VAD.
        """
        self._clock = clock
        self._segments: list[_Segment] = []
        self._saved_index: int = 0   # segments[:saved_index] are already on disk
        self._save_requested: bool = False
        self._at_sentence_start: bool = True

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------
    def process_phrase(self, raw_text: str) -> ProcessResult:
        """
        Feeds one recognised phrase (as emitted by
        TranscriptionEngine.transcribe_stream's output_queue) through the
        parser. Updates internal state. Safe to call with empty/whitespace
        text (a no-op).
        """
        result = ProcessResult()
        if not raw_text or not raw_text.strip():
            return result

        # Strip Whisper's own punctuation and normalise whitespace BEFORE
        # matching commands or storing dictation text - see module
        # docstring for why.
        cleaned = _STRIP_PUNCTUATION.sub("", raw_text)
        cleaned = _COLLAPSE_WHITESPACE.sub(" ", cleaned).strip()
        if not cleaned:
            return result

        pos = 0
        for match in _COMMAND_PATTERN.finditer(cleaned):
            # Whatever came before this command match is plain dictation.
            dictation_span = cleaned[pos:match.start()].strip()
            if dictation_span:
                self._add_dictation_text(dictation_span)

            command_type = self._command_type_of(match)
            self._execute_command(command_type, result)
            pos = match.end()

        # Trailing dictation text after the last command match (or the
        # whole phrase, if no command was found at all).
        trailing = cleaned[pos:].strip()
        if trailing:
            self._add_dictation_text(trailing)

        return result

    @staticmethod
    def _command_type_of(match: re.Match) -> CommandType:
        group_name = match.lastgroup
        assert group_name is not None  # the pattern only matches named groups
        return _COMMAND_GROUPS[group_name]

    def _execute_command(self, command_type: CommandType, result: ProcessResult) -> None:
        if command_type == CommandType.NEW_PARAGRAPH:
            self._segments.append(_Segment(type=_SegType.PARAGRAPH_BREAK))
            self._at_sentence_start = True
            logger.info("Voice command: new paragraph")

        elif command_type == CommandType.FULL_STOP:
            self._segments.append(_Segment(type=_SegType.FULL_STOP))
            self._at_sentence_start = True
            logger.info("Voice command: full stop")

        elif command_type == CommandType.COMMA:
            self._segments.append(_Segment(type=_SegType.COMMA))
            logger.info("Voice command: comma")

        elif command_type == CommandType.NEW_PATIENT:
            now = self._clock()
            # Format matches the date/time style shown in PRD Section 11's
            # worked example ("29 July 2026" / "10:45 AM"). FR-08's literal
            # text is just the words "Patient / Date / Time" as a template
            # label - ASSUMPTION: these mean the literal word "Patient"
            # followed by the actual current date and time values (matching
            # Section 11's pattern), not the literal words "Date"/"Time".
            # Flagging this explicitly since the PRD is genuinely ambiguous
            # here.
            date_str = now.strftime("%d %B %Y")
            time_str = now.strftime("%I:%M %p")
            self._segments.append(
                _Segment(type=_SegType.PATIENT_HEADER, header_lines=["Patient", date_str, time_str])
            )
            self._at_sentence_start = True
            logger.info(f"Voice command: new patient ({date_str} {time_str})")

        elif command_type == CommandType.SAVE_NOTE:
            self._save_requested = True
            logger.info("Voice command: save note (immediate save requested)")

        elif command_type == CommandType.DELETE_LAST_SENTENCE:
            deleted = self._delete_last_sentence()
            if not deleted:
                warning = "Delete last sentence: nothing eligible to delete (either already saved or no completed sentence yet)."
                logger.warning(warning)
                result.warnings.append(warning)

        result.commands_executed.append(command_type)

    def _add_dictation_text(self, text: str) -> None:
        if self._at_sentence_start:
            text = _capitalize_first(text)
            self._at_sentence_start = False
        self._segments.append(_Segment(type=_SegType.TEXT, text=text))

    # ------------------------------------------------------------------
    # DELETE LAST SENTENCE
    # ------------------------------------------------------------------
    def _delete_last_sentence(self) -> bool:
        """
        Removes the most recently completed sentence, but ONLY if every
        segment making up that sentence is still pending (i.e. at or after
        self._saved_index). This is the safe interpretation of FR-08's
        "before the next autosave": once even part of a sentence has been
        written to disk, this module has no way to retract it (the writer
        only ever appends - see engine/writer design), so we refuse rather
        than silently deleting only the pending tail and leaving orphaned
        saved text in the .docx. Returns True if something was deleted.
        """
        pending = self._segments[self._saved_index:]

        # Find the last boundary segment within the pending region - that
        # marks the end of the most recent *completed* sentence. Anything
        # after it (with no boundary yet) is an in-progress fragment and
        # does not count as "completed".
        last_boundary_rel = None
        for i in range(len(pending) - 1, -1, -1):
            if pending[i].type in _BOUNDARY_TYPES:
                last_boundary_rel = i
                break

        if last_boundary_rel is None:
            # No completed sentence anywhere in the pending region at all.
            return False

        # Find the boundary before THAT one (still within the pending
        # region) to know where the completed sentence started.
        start_rel = 0
        for i in range(last_boundary_rel - 1, -1, -1):
            if pending[i].type in _BOUNDARY_TYPES:
                start_rel = i + 1
                break

        # If start_rel is 0, the sentence's first segment is the very
        # first pending segment - meaning it starts exactly at
        # saved_index or later, so the WHOLE sentence is pending. Good.
        # (There is no way for this loop to find a boundary belonging to
        # the SAVED region, because `pending` never includes saved
        # segments in the first place - so this is automatically safe:
        # we can never partially delete a sentence that straddles the
        # save boundary, because the saved half is simply not visible to
        # this method.)
        del_start_abs = self._saved_index + start_rel
        del_end_abs = self._saved_index + last_boundary_rel + 1  # exclusive

        removed = self._segments[del_start_abs:del_end_abs]
        removed_text = render_segments(removed).strip()
        del self._segments[del_start_abs:del_end_abs]

        logger.info(f"Voice command: delete last sentence - removed: {removed_text!r}")
        return True

    # ------------------------------------------------------------------
    # OUTPUT FOR PHASE 5 (writer) / PHASE 6 (live transcript pane)
    # ------------------------------------------------------------------
    def get_pending_text(self) -> str:
        """Everything recognised since the last mark_saved() call, rendered
        as text. Empty string if there is nothing new to save."""
        return render_segments(self._segments[self._saved_index:])

    def mark_saved(self) -> None:
        """Call immediately after Phase 5 successfully writes
        get_pending_text() to disk. Commits the current end of the
        segment list as the new saved/pending boundary - from this point
        on, delete_last_sentence() can no longer touch anything before it."""
        self._saved_index = len(self._segments)

    def get_full_text(self) -> str:
        """Everything recognised so far (saved + pending combined), for the
        FR-04 live transcript pane. Independent of the save boundary."""
        return render_segments(self._segments)

    def consume_save_request(self) -> bool:
        """Returns True exactly once per 'save note' command heard, then
        resets. Phase 5's autosave loop (or Phase 6's UI) should poll this
        to trigger an immediate out-of-cycle save."""
        if self._save_requested:
            self._save_requested = False
            return True
        return False

    def has_pending_text(self) -> bool:
        """Convenience for the autosave loop: is there anything new to
        write at all (avoids writing empty saves every cycle)."""
        return len(self._segments) > self._saved_index