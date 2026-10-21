"""Internals: unit-level coverage of helpers the end-to-end tests only touch sideways."""

from __future__ import annotations

import json
import shutil
import sqlite3

from helpers import SCHEMA, minutes

from imsg_export import exporter, verify_export
from imsg_export.apple import iso_utc
from imsg_export.exporter import _attachment_index, _chat_label, _contact_names, export_history
from imsg_export.verify import VerifyResult


def test_iso_utc_handles_none():
    assert iso_utc(None) is None


class TestContactNames:
    def test_blank_name_and_invalid_json_are_skipped(self, monkeypatch):
        payload = "\n".join(
            [
                '{"contact_name": "Real Name", "participants": ["+15550001111"]}',
                "",
                '{"contact_name": "", "participants": ["+15550002222"]}',
                "this is not json",
            ]
        )

        class Done:
            stdout = payload

        monkeypatch.setattr(exporter.subprocess, "run", lambda *a, **k: Done())
        names = _contact_names()
        assert names == {"+15550001111": "Real Name"}

    def test_timeout_is_not_fatal(self, monkeypatch):
        def boom(*args, **kwargs):
            raise TimeoutError("imsg hung")

        monkeypatch.setattr(exporter.subprocess, "run", boom)
        assert _contact_names() == {}


class TestChatLabel:
    def test_no_chats_returns_none(self):
        assert _chat_label([], {}, {}) == (None, False)

    def test_missing_chat_record_falls_back_to_id(self):
        label, is_group = _chat_label([42], {}, {})
        assert label == "chat 42"
        assert is_group is False


class TestAttachmentIndex:
    def test_missing_store_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(exporter, "ATTACHMENT_STORE", str(tmp_path / "nope"))
        assert _attachment_index() == {}

    def test_copy_failure_is_recorded(self, monkeypatch, tmp_path):
        store = tmp_path / "store"
        store.mkdir()
        (store / "pic.jpg").write_bytes(b"x")

        db = tmp_path / "chat.db"
        con = sqlite3.connect(db)
        con.executescript(SCHEMA)
        con.execute("insert into handle values (1, '+15550001111', 'iMessage', 'US')")
        con.execute("insert into chat values (1, 'g', '+15550001111', '', 'iMessage')")
        con.execute("insert into chat_handle_join values (1, 1)")
        con.execute(
            "insert into message (ROWID, guid, text, handle_id, service, date, is_from_me)"
            " values (1, 'GUID-1', NULL, 1, 'iMessage', ?, 1)",
            (minutes(0),),
        )
        con.execute("insert into chat_message_join values (1, 1)")
        con.execute(
            "insert into attachment values "
            "(1, 'A1', ?, 'public.jpeg', 'image/jpeg', 'pic.jpg', 1, 0, 0)",
            (str(store / "pic.jpg"),),
        )
        con.execute("insert into message_attachment_join values (1, 1)")
        con.commit()
        con.close()

        def failing_copy(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(shutil, "copy2", failing_copy)
        summary = export_history(tmp_path / "out", db, use_contacts=False)
        assert summary["attachments_purged"] == 0
        manifest = (tmp_path / "out" / "attachments" / "manifest.csv").read_text()
        assert "copy-error" in manifest


class TestRenderFallbacks:
    def test_attachment_only_message_renders_placeholder(self, tmp_path):
        store = tmp_path / "store"
        store.mkdir()
        (store / "only.jpg").write_bytes(b"x")

        db = tmp_path / "chat.db"
        con = sqlite3.connect(db)
        con.executescript(SCHEMA)
        con.execute("insert into handle values (1, '+15550001111', 'iMessage', 'US')")
        con.execute("insert into chat values (1, 'g', '+15550001111', '', 'iMessage')")
        con.execute("insert into chat_handle_join values (1, 1)")
        con.execute(
            "insert into message (ROWID, guid, text, handle_id, service, date, is_from_me)"
            " values (1, 'GUID-1', NULL, 1, 'iMessage', ?, 1)",
            (minutes(0),),
        )
        con.execute("insert into chat_message_join values (1, 1)")
        con.execute(
            "insert into attachment values (1, 'A1', ?, 'public.jpeg', 'image/jpeg',"
            " 'only.jpg', 1, 0, 0)",
            (str(store / "only.jpg"),),
        )
        con.execute("insert into message_attachment_join values (1, 1)")
        con.commit()
        con.close()

        export_history(tmp_path / "out", db, use_contacts=False)
        transcript = next((tmp_path / "out" / "transcripts").glob("*.txt")).read_text()
        assert "[attachment]" in transcript


class TestVerifyReport:
    def test_report_lists_missing_extra_and_divergence(self):
        result = VerifyResult(
            database_rows=3,
            export_rows=3,
            missing=[7],
            extra=[99],
            text_mismatches=[(4, "want", "got")],
            db_text_rows=2,
            db_attachment_refs=1,
            export_attachment_refs=1,
            messages_with_attachments=1,
            empty_messages=0,
            transcript_lines=3,
            non_reaction_rows=3,
            reaction_rows=0,
        )
        report = result.report()
        assert "MISSING: [7]" in report
        assert "EXTRA: [99]" in report
        assert "TEXT DIFF 4" in report
        assert "VERDICT: INCOMPLETE" in report
        assert result.ok is False

    def test_extra_row_is_detected_end_to_end(self, tmp_path):
        db = tmp_path / "chat.db"
        con = sqlite3.connect(db)
        con.executescript(SCHEMA)
        con.execute("insert into handle values (1, '+15550001111', 'iMessage', 'US')")
        con.execute("insert into chat values (1, 'g', '+15550001111', '', 'iMessage')")
        con.execute("insert into chat_handle_join values (1, 1)")
        con.execute(
            "insert into message (ROWID, guid, text, handle_id, service, date, is_from_me)"
            " values (1, 'GUID-1', 'hi', 1, 'iMessage', ?, 0)",
            (minutes(0),),
        )
        con.execute("insert into chat_message_join values (1, 1)")
        con.commit()
        con.close()

        export_history(tmp_path / "out", db, use_contacts=False)
        path = tmp_path / "out" / "messages.jsonl"
        record = json.loads(path.read_text().splitlines()[0])
        record["id"] = 12345
        path.write_text(json.dumps(record) + "\n", encoding="utf-8")

        result = verify_export(tmp_path / "out", db)
        assert result.extra == [12345]
        assert result.missing == [1]
        assert not result.ok


def test_jsonl_line_escapes_unicode_line_breaks():
    from imsg_export.exporter import jsonl_line

    text = "a\u0085b\u2028c\u2029d"
    line = jsonl_line({"id": 1, "text": text})

    assert "\u0085" not in line and "\u2028" not in line and "\u2029" not in line
    assert line.splitlines() == [line]  # one record, one physical line
    assert json.loads(line)["text"] == text  # and the text survives the round trip


def test_readme_command_without_an_export_reports_cleanly(capsys):
    from imsg_export.cli import main

    assert main(["readme", "/nonexistent/export"]) == 1
    assert "error:" in capsys.readouterr().err


def test_oversized_length_prefix_is_rejected():
    from imsg_export.apple import decode_attributed_body

    # A length that runs past the end of the blob is not trusted: better to return
    # nothing than to guess at a truncated string.
    assert decode_attributed_body(b"\x84\x01+" + bytes([200]) + b"short") == ""
    assert decode_attributed_body(b"\x84\x01+\x81\xff\xff") == ""
