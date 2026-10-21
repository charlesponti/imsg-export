"""Apple formats: epochs, timestamps, tapbacks and NSAttributedString bodies."""

from __future__ import annotations

from datetime import UTC, datetime

# 2001-01-01T00:00:00Z as a unix timestamp.
APPLE_EPOCH = 978_307_200

# Apple stores message.date as nanoseconds, but old or migrated rows can arrive as
# microseconds or plain seconds. Sniff the magnitude instead of trusting the unit.
_NANOSECOND_CUTOFF = 10**15
_MICROSECOND_CUTOFF = 10**12

TAPBACK_ADDED = range(2000, 2007)
TAPBACK_REMOVED = range(3000, 3007)

TAPBACK_LABELS = {
    2000: "Loved ❤️",
    2001: "Liked 👍",
    2002: "Disliked 👎",
    2003: "Laughed 😆",
    2004: "Emphasised ‼️",
    2005: "Questioned ❓",
    2006: "Reacted",
}

# The attributedBody blob prefixes the string with class markers, a length byte and a
# 0x86 0x84 terminator. This is the marker that directly precedes the payload.
_BODY_MARKER = b"\x84\x01+"


def apple_timestamp(value: int | None) -> datetime | None:
    """Convert an Apple epoch value to an aware UTC datetime."""
    if not value:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    if value > _NANOSECOND_CUTOFF:
        seconds = value / 1e9
    elif value > _MICROSECOND_CUTOFF:
        seconds = value / 1e6
    else:
        seconds = value
    try:
        return datetime.fromtimestamp(seconds + APPLE_EPOCH, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def iso_utc(moment: datetime | None) -> str | None:
    """Millisecond-precision ISO 8601 in UTC, with a trailing Z."""
    if moment is None:
        return None
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def local_time(moment: datetime | None) -> str:
    """Human-readable local timestamp for transcripts."""
    if moment is None:
        return "?"
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def decode_attributed_body(blob: bytes | None) -> str:
    """Extract the plain string from an NSAttributedString typedstream blob.

    Roughly half of all message rows leave `text` empty and keep the body only in
    `attributedBody`. The payload is preceded by the NSString class marker, a
    base-128-ish length prefix (0x81 + uint16 LE, 0x82 + uint32 LE, or a single
    byte) and is followed by a 0x86 0x84 terminator.
    """
    if not blob:
        return ""
    start = blob.find(_BODY_MARKER)
    if start < 0:
        return ""
    cursor = start + len(_BODY_MARKER)
    if cursor >= len(blob):
        return ""
    try:
        lead = blob[cursor]
        if lead == 0x81:
            length = int.from_bytes(blob[cursor + 1 : cursor + 3], "little")
            cursor += 3
        elif lead == 0x82:
            length = int.from_bytes(blob[cursor + 1 : cursor + 5], "little")
            cursor += 5
        else:
            length = lead
            cursor += 1
        return blob[cursor : cursor + length].decode("utf-8", "ignore")
    except (IndexError, ValueError):
        return ""


def clean_text(text: str | None) -> str:
    """Strip the attachment placeholder and control characters, keep newlines."""
    if not text:
        return ""
    if text.startswith("\ufffc"):
        text = text[1:]
    return "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32).strip()


def reaction_label(associated_type: int) -> str:
    """Human label for an `associated_message_type` value."""
    base = associated_type if associated_type in TAPBACK_LABELS else associated_type % 1000 + 2000
    return TAPBACK_LABELS.get(base, str(associated_type))
