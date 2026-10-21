"""Property-based tests.

The typedstream decoder is the riskiest code in this package: it parses an
undocumented binary blob written by Apple frameworks, and a wrong assumption
there either crashes an export or silently corrupts someone's history. These
tests assert the properties that must hold for *any* input, not just the inputs
we thought of.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from helpers import SCHEMA, body_blob
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from imsg_export import export_history, verify_export
from imsg_export.apple import (
    apple_timestamp,
    clean_text,
    decode_attributed_body,
    iso_utc,
    reaction_label,
)

SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

# Surrogates cannot be encoded as UTF-8, so they are not valid payload content.
TEXT = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=120)


class TestDecoderRobustness:
    @SETTINGS
    @given(st.binary(max_size=4096))
    def test_arbitrary_bytes_never_raise(self, blob):
        assert isinstance(decode_attributed_body(blob), str)

    @SETTINGS
    @given(st.binary(max_size=512), st.integers(min_value=0, max_value=512))
    def test_truncation_never_raises(self, blob, cut):
        assert isinstance(decode_attributed_body(blob[:cut]), str)

    @SETTINGS
    @given(TEXT)
    def test_roundtrip_single_byte_length(self, text):
        payload = text.encode("utf-8")
        if len(payload) >= 0x81:
            pytest.skip("single-byte length prefix only covers short payloads")
        assert decode_attributed_body(body_blob(text)) == text

    @SETTINGS
    @given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=400))
    def test_roundtrip_two_byte_length(self, text):
        payload = text.encode("utf-8")
        blob = body_blob(text, length_prefix=b"\x81" + len(payload).to_bytes(2, "little"))
        assert decode_attributed_body(blob) == text

    @SETTINGS
    @given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=2000))
    def test_roundtrip_four_byte_length(self, text):
        payload = text.encode("utf-8")
        blob = body_blob(text, length_prefix=b"\x82" + len(payload).to_bytes(4, "little"))
        assert decode_attributed_body(blob) == text

    @SETTINGS
    @given(st.binary(max_size=64), TEXT)
    def test_leading_garbage_is_tolerated(self, prefix, text):
        """Junk before the blob must not be mistaken for a marker."""
        assert decode_attributed_body(prefix + body_blob(text)) == text

    @SETTINGS
    @given(TEXT, st.binary(max_size=64))
    def test_trailing_garbage_is_tolerated(self, text, suffix):
        assert decode_attributed_body(body_blob(text) + suffix) == text

    @SETTINGS
    @given(TEXT)
    def test_payload_is_not_mistaken_for_a_later_marker(self, text):
        """A blob whose payload embeds a marker still decodes to itself."""
        embedded = "\x84\x01+" + text
        assert decode_attributed_body(body_blob(embedded)) == embedded


class TestCleanText:
    @SETTINGS
    @given(st.text())
    def test_never_raises_and_strips_control_characters(self, text):
        result = clean_text(text)
        assert all(ch in "\n\t" or ord(ch) >= 32 for ch in result)

    @SETTINGS
    @given(st.text())
    def test_result_is_stripped(self, text):
        result = clean_text(text)
        assert result == result.strip()

    @SETTINGS
    @given(st.text())
    def test_second_pass_is_stable(self, text):
        once = clean_text(text)
        assert clean_text(once) == clean_text(once.lstrip("\ufffc"))

    @SETTINGS
    @given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=50))
    def test_only_a_single_leading_placeholder_is_removed(self, text):
        result = clean_text("\ufffc" + text)
        assert not result.startswith("\ufffc") or text.startswith("\ufffc")


class TestTimestamps:
    @SETTINGS
    @given(st.integers(min_value=-(10**18), max_value=10**18))
    def test_never_raises(self, value):
        moment = apple_timestamp(value)
        assert moment is None or moment.tzinfo == UTC

    @SETTINGS
    @given(st.integers(min_value=0, max_value=10**11))
    def test_monotonic_in_input(self, value):
        earlier = apple_timestamp(value)
        later = apple_timestamp(value + 1)
        if earlier and later:
            assert later >= earlier

    @SETTINGS
    @given(st.integers(min_value=10**9, max_value=10**10))
    def test_iso_format_is_stable(self, value):
        moment = apple_timestamp(value)
        if moment is None:
            pytest.skip("value outside representable range")
        rendered = iso_utc(moment)
        assert rendered is not None
        assert datetime.strptime(rendered, "%Y-%m-%dT%H:%M:%S.%fZ")

    @SETTINGS
    @given(st.integers(min_value=-5000, max_value=5000))
    def test_reaction_labels_never_raise(self, value):
        assert isinstance(reaction_label(value), str)


message_spec = st.fixed_dictionaries(
    {
        "text": st.one_of(st.none(), st.text(max_size=60)),
        "from_me": st.booleans(),
        "in_chat": st.booleans(),
        "kind": st.sampled_from(["message", "reaction", "group-action", "system"]),
        "service": st.sampled_from(["iMessage", "SMS", "RCS"]),
    }
)


def materialise(db: Path, specs: list[dict[str, object]]) -> int:
    """Write generated message specs into a chat.db-shaped database."""
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.execute("insert into handle values (1, '+15550001111', 'iMessage', 'US')")
    con.execute("insert into chat values (1, 'any;-+15550001111', '+15550001111', '', 'iMessage')")
    con.execute("insert into chat_handle_join values (1, 1)")

    for index, spec in enumerate(specs, start=1):
        kind = spec["kind"]
        associated = 2000 if kind == "reaction" else 0
        con.execute(
            """
            insert into message (ROWID, guid, text, handle_id, service, date, is_from_me,
                                 is_read, is_sent, is_delivered, item_type,
                                 associated_message_type, associated_message_guid,
                                 is_system_message, is_spam)
            values (?, ?, ?, 1, ?, ?, ?, 1, ?, 1, ?, ?, ?, ?, 0)
            """,
            (
                index,
                f"GUID-{index}",
                spec["text"],
                spec["service"],
                (index + 1) * 10**16,
                int(bool(spec["from_me"])),
                int(bool(spec["from_me"])),
                1 if kind == "group-action" else 0,
                associated,
                f"p:0/GUID-{max(1, index - 1)}" if associated else None,
                1 if kind == "system" else 0,
            ),
        )
        if spec["in_chat"]:
            con.execute("insert into chat_message_join values (1, ?)", (index,))

    con.commit()
    con.close()
    return len(specs)


def check_full_accounting(workspace: Path, specs: list[dict[str, object]]) -> None:
    db = workspace / "chat.db"
    count = materialise(db, specs)
    target = workspace / "out"

    summary = export_history(target, db, use_contacts=False)
    assert summary["messages_total"] == count
    assert summary["rows_in_database"] == count

    body = (target / "messages.jsonl").read_text().splitlines()
    exported = [json.loads(line) for line in body]
    assert len(exported) == count
    assert sorted(m["id"] for m in exported) == list(range(1, count + 1))

    result = verify_export(target, db)
    assert result.ok, result.report()


def check_deterministic(workspace: Path, specs: list[dict[str, object]]) -> None:
    db = workspace / "chat.db"
    materialise(db, specs)

    first = export_history(workspace / "a", db, use_contacts=False)
    second = export_history(workspace / "b", db, use_contacts=False)

    assert first["messages_total"] == second["messages_total"]
    assert first["kinds"] == second["kinds"]
    assert first["attribution"] == second["attribution"]
    assert (workspace / "a" / "messages.jsonl").read_text() == (
        workspace / "b" / "messages.jsonl"
    ).read_text()


def check_reconciliation(workspace: Path, specs: list[dict[str, object]]) -> None:
    db = workspace / "chat.db"
    materialise(db, specs)
    summary = export_history(workspace / "out", db, use_contacts=False)
    assert summary["messages_in_chats"] + summary["messages_orphaned"] == summary["messages_total"]
    assert sum(summary["attribution"].values()) == summary["messages_total"]


class TestExporterProperties:
    """Every generated database must round-trip through export and verify.

    Each example gets its own directory: pytest fixtures are created once per test
    function, not once per hypothesis example, so a shared tmp_path would collide.
    """

    @settings(max_examples=60, deadline=None)
    @given(st.lists(message_spec, min_size=1, max_size=25))
    def test_export_accounts_for_every_generated_row(self, specs):
        with tempfile.TemporaryDirectory() as workspace:
            check_full_accounting(Path(workspace), specs)

    @settings(max_examples=60, deadline=None)
    @given(st.lists(message_spec, min_size=1, max_size=15))
    def test_export_is_deterministic(self, specs):
        with tempfile.TemporaryDirectory() as workspace:
            check_deterministic(Path(workspace), specs)

    @settings(max_examples=60, deadline=None)
    @given(st.lists(message_spec, min_size=1, max_size=15))
    def test_chat_and_orphan_counts_reconcile(self, specs):
        with tempfile.TemporaryDirectory() as workspace:
            check_reconciliation(Path(workspace), specs)
