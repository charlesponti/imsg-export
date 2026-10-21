"""Apple format decoding: epochs, timestamps and attributedBody blobs."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from helpers import body_blob

from imsg_export.apple import (
    APPLE_EPOCH,
    apple_timestamp,
    clean_text,
    decode_attributed_body,
    iso_utc,
    local_time,
    reaction_label,
)


class TestAppleTimestamp:
    """The Apple epoch is 2001-01-01; a stored value of 0 means exactly that."""

    OFFSET_SECONDS = 800_000_000  # 2026-05-ish, a whole number of seconds

    def test_nanoseconds(self):
        moment = apple_timestamp(self.OFFSET_SECONDS * 10**9)
        assert moment == datetime.fromtimestamp(self.OFFSET_SECONDS + APPLE_EPOCH, UTC)

    def test_seconds_are_passed_through(self):
        moment = apple_timestamp(self.OFFSET_SECONDS)
        assert moment == datetime.fromtimestamp(self.OFFSET_SECONDS + APPLE_EPOCH, UTC)

    def test_microseconds(self):
        moment = apple_timestamp(self.OFFSET_SECONDS * 10**6)
        assert moment == datetime.fromtimestamp(self.OFFSET_SECONDS + APPLE_EPOCH, UTC)

    @pytest.mark.parametrize("value", [None, 0, "", "nonsense"])
    def test_empty_values(self, value):
        assert apple_timestamp(value) is None

    def test_iso_and_local_rendering(self):
        moment = datetime(2026, 3, 4, 5, 6, 7, 891000, tzinfo=UTC)
        assert iso_utc(moment) == "2026-03-04T05:06:07.891Z"
        assert local_time(moment) == moment.astimezone().strftime("%Y-%m-%d %H:%M")
        assert local_time(None) == "?"


class TestAttributedBody:
    def test_single_byte_length(self):
        assert decode_attributed_body(body_blob("hello")) == "hello"

    def test_two_byte_length(self):
        text = "x" * 300
        blob = body_blob(text, length_prefix=b"\x81" + len(text).to_bytes(2, "little"))
        assert decode_attributed_body(blob) == text

    def test_four_byte_length(self):
        text = "y" * 5000
        blob = body_blob(text, length_prefix=b"\x82" + len(text).to_bytes(4, "little"))
        assert decode_attributed_body(blob) == text

    def test_unicode_survives(self):
        assert decode_attributed_body(body_blob("samosa + paneer 🥟")) == "samosa + paneer 🥟"

    def test_placeholder_only(self):
        assert decode_attributed_body(body_blob("\ufffc")) == "\ufffc"

    @pytest.mark.parametrize("blob", [None, b"", b"not a typedstream", b"\x84\x01+"])
    def test_bad_input_returns_empty(self, blob):
        assert decode_attributed_body(blob) == ""


class TestCleanText:
    def test_strips_leading_attachment_placeholder(self):
        assert clean_text("\ufffcButter chicken") == "Butter chicken"

    def test_keeps_inner_placeholder(self):
        assert clean_text("a\ufffcb") == "a\ufffcb"

    def test_drops_control_characters(self):
        assert clean_text("a\x00b\x07c") == "abc"

    def test_keeps_newlines_and_tabs(self):
        assert clean_text("line1\nline2\tend") == "line1\nline2\tend"

    def test_none(self):
        assert clean_text(None) == ""


@pytest.mark.parametrize(
    ("associated", "expected"),
    [
        (2000, "Loved ❤️"),
        (2001, "Liked 👍"),
        (2003, "Laughed 😆"),
        (3000, "Loved ❤️"),
        (9999, "9999"),
    ],
)
def test_reaction_labels(associated, expected):
    assert reaction_label(associated) == expected
