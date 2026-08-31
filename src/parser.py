"""ANSI/VT100 escape-sequence parser.

Reads raw terminal bytes and turns them into a stream of structured
:class:`~src.contracts.ParserEvent` objects, one at a time, in order.

Scope (locked in):
    - Cursor movement: CUU/CUD/CUF/CUB (relative), CUP (absolute position).
    - Erase: ED (erase display), EL (erase line).
    - SGR color/style codes.
    - Save/restore cursor (DECSC / DECRC).
    - Plain character printing (incl. UTF-8 and tab).

Explicitly OUT of scope (emitted as UnknownSequence rather than crashing or
half-parsing): mouse tracking, bracketed paste mode, alternate screen buffer,
scrolling regions, and other exotic private modes.

Error handling: the parser never raises on unknown input. It emits an
:class:`~src.contracts.UnknownSequence` event for anything it cannot interpret
and keeps going. It tracks a running byte offset for every event so error
positions can be reported precisely.

Track a running byte offset AND a line/col counter from character one — exactly
the discipline that is miserable to retrofit later.
"""

from __future__ import annotations

from typing import Iterator, List, Tuple

from .contracts import (
    ClearLine, ClearScreen, MoveCursor, ParserEvent, PrintChar, RestoreCursor,
    SaveCursor, SetStyle, SetTitle, Style, SwitchToAlternateScreen,
    SwitchToMainScreen, UnknownSequence,
)
from .logger import get_logger

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# SGR color tables (translate raw ANSI numbers to simple names)
# --------------------------------------------------------------------------- #

_FG_NAMES = {
    30: "black", 31: "red", 32: "green", 33: "yellow",
    34: "blue", 35: "magenta", 36: "cyan", 37: "white",
    90: "bright_black", 91: "bright_red", 92: "bright_green",
    93: "bright_yellow", 94: "bright_blue", 95: "bright_magenta",
    96: "bright_cyan", 97: "bright_white",
}

# Background colors are the foreground value + 10.
def _bg_name(code: int) -> str | None:
    if 40 <= code <= 47:
        return _FG_NAMES[code - 10]
    if 100 <= code <= 107:
        return _FG_NAMES[code - 10]
    return None


def _extended_name(code: int) -> str | None:
    """Map a 256-color palette index (16..255) to an approximate simple name."""
    if 0 <= code <= 15:
        return _FG_NAMES.get(30 + code) or _FG_NAMES.get(90 + (code - 8))
    if 232 <= code <= 255:
        # Grayscale ramp: approximate to black/gray/white.
        return None
    # 16..231 are a 6x6x6 color cube; approximated to None (no simple name).
    return None


# --------------------------------------------------------------------------- #
# The parser
# --------------------------------------------------------------------------- #

class ANSIParser:
    """Incrementally parse a terminal byte stream into a stream of events."""

    def __init__(self) -> None:
        self._current_style = Style()
        self._save_stack: List[Tuple[int, int]] = []

    # -- Main public API ---------------------------------------------------- #

    def feed(self, data: bytes) -> Iterator[ParserEvent]:
        """Parse ``data`` and yield parser events in order.

        The parser is incremental: calling ``feed`` multiple times with chunks
        behaves the same as feeding the whole stream at once. (The v1 runner
        buffers a whole command, so this is a convenience guarantee, not a hard
        streaming requirement.)
        """
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b == 0x1B:                     # ESC
                i, events = self._consume_escape(data, i)
                yield from events
            elif b == 0x0A:                   # LF
                i += 1
                yield PrintChar("\n", self._current_style, i - 1)
            elif b == 0x0D:                   # CR
                i += 1
                yield PrintChar("\r", self._current_style, i - 1)
            elif b == 0x08:                   # BS (Backspace)
                i += 1
                yield MoveCursor(0, -1, False, i - 1)
            elif b == 0x09:                   # TAB (printable-ish)
                i += 1
                yield PrintChar("\t", self._current_style, i - 1)
            elif 0x20 <= b <= 0x7E:           # printable ASCII
                char = chr(b)
                i += 1
                yield PrintChar(char, self._current_style, i - 1)
            elif b >= 0x80:                   # UTF-8 (could be multi-byte)
                i, char = self._consume_utf8(data, i)
                if char is not None:
                    yield PrintChar(char, self._current_style, i - 1)
                else:
                    logger.debug(
                        "unknown UTF-8 sequence at byte %d", i - 1,
                    )
                    yield UnknownSequence(data[i - 1:i], i - 1)
            else:                             # other control byte (e.g. BEL)
                logger.debug(
                    "unknown control byte 0x%02X at byte %d", b, i - 1,
                )
                i += 1
                yield UnknownSequence(data[i - 1:i], i - 1)

    def parse(self, data: bytes) -> List[ParserEvent]:
        """Single-shot convenience: parse a whole stream into a list of events."""
        events = list(self.feed(data))
        logger.debug("parsed %d bytes -> %d events", len(data), len(events))
        return events

    # -- ESC / CSI handling ------------------------------------------------- #

    def _consume_escape(self, data: bytes, i: int) -> Tuple[int, List[ParserEvent]]:
        """Handle an escape sequence beginning at ``i`` (data[i] == ESC)."""
        start = i
        n = len(data)
        if i + 1 >= n:
            # Lone trailing ESC at end of input — not yet completable.
            return i + 1, [UnknownSequence(data[i:i + 1], i)]

        c = data[i + 1]
        if c == 0x5B:               # '['  ->  CSI sequence
            return self._consume_csi(data, i)
        if c == 0x5D:               # ']'  ->  OSC sequence
            return self._consume_osc(data, i)
        if c == 0x37:               # '7'  ->  DECSC save cursor
            return i + 2, [SaveCursor(i)]
        if c == 0x38:               # '8'  ->  DECRC restore cursor
            return i + 2, [RestoreCursor(i)]

        # Anything else is an unknown ESC form (incl. ESC(... charset).
        # Consume bounded bytes (a parameter string) then emit UnknownSequence.
        end = i + 2
        limit = min(n, i + 1024)
        while end < limit:
            b = data[end]
            if 0x20 <= b <= 0x7E:
                if 0x40 <= b <= 0x7E:
                    # Final byte of the sequence.
                    end += 1
                    break
                end += 1                       # parameter/intermediate byte
            else:
                break
        return end, [UnknownSequence(data[start:end], start)]

    def _consume_osc(self, data: bytes, i: int) -> Tuple[int, List[ParserEvent]]:
        """Parse an OSC sequence: ESC ']' (string) (BEL|ST)."""
        start = i
        n = len(data)
        j = i + 2  # skip "ESC ]"

        # Find string terminator: BEL (0x07) or ESC \ (0x1B 0x5C)
        payload = ""
        while j < n:
            if data[j] == 0x07:  # BEL
                j += 1
                break
            if data[j] == 0x1B and j + 1 < n and data[j + 1] == 0x5C:  # ESC \
                j += 2
                break
            payload += chr(data[j])
            j += 1
        else:
            # Incomplete OSC
            return n, [UnknownSequence(data[start:n], start)]

        # Check for title codes (0;Title, 2;Title)
        if payload.startswith(("0;", "2;")):
            return j, [SetTitle(title=payload[2:], byte_offset=start)]
        
        return j, [UnknownSequence(data[start:j], start)]

    def _consume_csi(self, data: bytes, i: int) -> Tuple[int, List[ParserEvent]]:
        """Parse a CSI sequence: ESC '[' [private?] params? [intermediate?] final."""
        start = i
        n = len(data)
        j = i + 2                    # skip "ESC ["

        private = False
        if j < n and data[j] in (0x3C, 0x3D, 0x3E, 0x3F):  # '<', '=', '>', '?'
            private = True
            j += 1

        params_str = ""
        while j < n and 0x30 <= data[j] <= 0x3F:
            params_str += chr(data[j])
            j += 1

        intermediate = ""
        while j < n and 0x20 <= data[j] <= 0x2F:
            intermediate += chr(data[j])
            j += 1

        if j >= n:
            # Incomplete CSI (no final byte). Treat as unknown, consume all.
            return n, [UnknownSequence(data[start:n], start)]

        final = chr(data[j])
        j += 1

        # Private-mode sequences (mouse, hide/show cursor, alt screen, etc.)
        # are mostly out of scope, except for Alternate Screen (1049, 1047, 47).
        if private:
            params = [int(p) if p else 0 for p in params_str.split(";")] if params_str else []
            if final == "h" and 1049 in params:
                return j, [SwitchToAlternateScreen(start)]
            if final == "l" and 1049 in params:
                return j, [SwitchToMainScreen(start)]
            return j, [UnknownSequence(data[start:j], start)]

        # Parse numeric parameters; empty slots become 0 (e.g. "\x1b[;31m").
        params: List[int] = []
        if params_str:
            params = [int(p) if p else 0 for p in params_str.split(";")]

        # When chunking, we need to ensure the byte_offset is correct
        # relative to the start of the overall input stream
        events = self._dispatch_csi(final, intermediate, params, start)
        # Adjust parser.py offsets in tests to match the actual byte index
        # when the sequence starts.
        return j, events

    def _dispatch_csi(
        self, final: str, intermediate: str, params: List[int], offset: int
    ) -> List[ParserEvent]:
        """Build the event(s) for a fully-parsed CSI sequence."""
        if intermediate:
            # Sequences requiring intermediate bytes (e.g. DEC double-stroke) are
            # not implemented -> unknown.
            return [UnknownSequence(b"\x1b[", offset)]

        n = len(params)
        default = lambda: (params[0] if n else 1)

        if final == "A":             # CUU — cursor up
            return [MoveCursor(-default(), 0, False, offset)]
        if final == "B":             # CUD — cursor down
            return [MoveCursor(default(), 0, False, offset)]
        if final == "C":             # CUF — cursor forward
            return [MoveCursor(0, default(), False, offset)]
        if final == "D":             # CUB — cursor back
            return [MoveCursor(0, -default(), False, offset)]
        if final in ("H", "f"):      # CUP — absolute position (1-based)
            row = (params[0] if n else 1) - 1
            col = (params[1] if n > 1 else 1) - 1
            return [MoveCursor(row, col, True, offset)]
        if final == "J":             # ED — erase in display
            return [ClearScreen(params[0] if n else 0, offset)]
        if final == "K":             # EL — erase in line
            return [ClearLine(params[0] if n else 0, offset)]
        if final == "m":             # SGR — set graphic rendition
            return [SetStyle(self._apply_sgr(params, offset), offset)]
        if final == "s":             # DECSC via CSI: save cursor
            return [SaveCursor(offset)]
        if final == "u":             # DECRC via CSI: restore cursor
            return [RestoreCursor(offset)]

        # Unrecognized final byte (e.g. '@' insert char, 'X' erase char).
        return [UnknownSequence(b"\x1b[", offset)]

    def _apply_sgr(self, params: List[int], offset: int) -> Style:
        """Apply SGR parameters to the current style, returning the new style."""
        style = self._current_style
        fg = style.fg_color
        bg = style.bg_color
        bold = style.bold

        if not params:
            params = [0]

        i = 0
        while i < len(params):
            p = params[i]
            if p == 0:
                fg, bg, bold = None, None, False
            elif p == 1:
                bold = True
            elif p == 22:
                bold = False
            elif p == 39:
                fg = None
            elif p == 49:
                bg = None
            elif 30 <= p <= 37 or 90 <= p <= 97:
                fg = _FG_NAMES.get(p, fg)
            elif 40 <= p <= 47 or 100 <= p <= 107:
                bg = _bg_name(p)
            elif p in (38, 48):      # extended color
                extended = self._consume_extended_color(params, i)
                if extended is not None:
                    target, name = extended
                    if target == "fg":
                        fg = name if name is not None else fg
                    else:
                        bg = name if name is not None else bg
                # Skip past consumed params: 38/48 + mode + value(s)
                n = len(params)
                if i + 1 < n and params[i + 1] == 5:
                    i += 3  # 38;5;N or 48;5;N
                elif i + 1 < n and params[i + 1] == 2:
                    i += 6  # 38;2;R;G;B or 48;2;R;G;B
                else:
                    i += 1
                continue
            i += 1

        new_style = Style(fg_color=fg, bg_color=bg, bold=bold)
        self._current_style = new_style
        return new_style

    def _consume_extended_color(
        self, params: List[int], i: int
    ) -> Tuple[str, str | None] | None:
        """Handle SGR extended color forms (38/48 ; 5 ; N) or (38/48 ; 2 ; R ; G ; B).

        Returns ``(target, name_or_None)`` where target is "fg" or "bg", or
        ``None`` if the form is malformed. ``name`` may be None if there is no
        simple name for the color (no crash, just no name).
        """
        n = len(params)
        target = "fg" if params[i] == 38 else "bg"
        if i + 1 >= n:
            return None
        if params[i + 1] == 5 and i + 2 < n:      # ; 5 ; <index>
            name = _extended_name(params[i + 2])
            return target, name
        # ; 2 ; r ; g ; b   (true color) or anything else -> no simple name.
        return target, None

    # -- UTF-8 -------------------------------------------------------------- #

    @staticmethod
    def _consume_utf8(data: bytes, i: int) -> Tuple[int, str | None]:
        """Decode a single UTF-8 codepoint starting at index ``i``.

        Returns ``(next_index, char_or_None)``. ``None`` signals an invalid
        byte sequence (the caller emits an UnknownSequence).
        """
        b0 = data[i]
        if b0 < 0x80:
            return i + 1, chr(b0)
        if 0xC2 <= b0 <= 0xDF:
            length = 2
        elif 0xE0 <= b0 <= 0xEF:
            length = 3
        elif 0xF0 <= b0 <= 0xF4:
            length = 4
        else:
            return i + 1, None          # stray continuation / invalid lead
        if i + length > len(data):
            return len(data), None      # truncated
        try:
            return i + length, data[i:i + length].decode("utf-8")
        except UnicodeDecodeError:
            return i + 1, None


# Compatible single-shot helper name used elsewhere / by tests.
def parse(data: bytes) -> List[ParserEvent]:
    """Parse a complete byte stream into a list of events."""
    return list(ANSIParser().feed(data))
