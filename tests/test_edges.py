"""Edge cases: optional integrations, rendering branches and error paths."""

from __future__ import annotations

import json
import os
import runpy
import sqlite3
import sys
from pathlib import Path

import pytest
from helpers import SCHEMA, body_blob, minutes

from imsg_export import export_history, verify_export
from imsg_export.apple import apple_timestamp
from imsg_export.cli import main
from imsg_export.verify import dump_messages


def build(tmp_path: Path, rows: list[dict], chats: list[dict] | None = None) -> Path:
    """Create a chat.db from explicit rows, for tests that need unusual shapes."""
    db = tmp_path / "chat.db"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.execute("insert into handle values (1, '+15550001111', 'iMessage', 'US')")
    con.execute("insert into handle values (2, '+15550002222', 'iMessage', 'US')")
    con.execute("insert into handle values (3, '+15550003333', 'iMessage', 'US')")

    for chat in chats or []:
        con.execute(
            "insert into chat values (?, ?, ?, ?, ?)",
            (
                chat["id"],
                chat["guid"],
                chat.get("identifier", ""),
                chat.get("name", ""),
                chat.get("service", "iMessage"),
            ),
        )
        for participant in chat.get("participants", []):
            con.execute("insert into chat_handle_join values (?, ?)", (chat["id"], participant))

    for index, row in enumerate(rows, start=1):
        row = {"id": index, "guid": f"GUID-{index}", **row}
        columns = {
            "ROWID": row["id"],
            "guid": row["guid"],
            "text": row.get("text"),
            "attributedBody": row.get("body"),
            "handle_id": row.get("handle", 1),
            "service": row.get("service", "iMessage"),
            "date": row.get("date", minutes(index)),
            "is_from_me": row.get("from_me", 0),
            "is_read": 1,
            "is_sent": row.get("from_me", 0),
            "is_delivered": 1,
            "item_type": row.get("item_type", 0),
            "associated_message_type": row.get("associated", 0),
            "associated_message_guid": row.get("target"),
            "thread_originator_guid": row.get("thread"),
            "date_edited": row.get("edited", 0),
            "date_retracted": row.get("retracted", 0),
            "is_spam": row.get("spam", 0),
            "is_system_message": row.get("system", 0),
        }
        names = ", ".join(columns)
        marks = ", ".join("?" for _ in columns)
        con.execute(f"insert into message ({names}) values ({marks})", list(columns.values()))
        for chat_id in row.get("chats", []):
            con.execute("insert into chat_message_join values (?, ?)", (chat_id, row["id"]))

    con.commit()
    con.close()
    return db


class TestContactLookup:
    def test_names_come_from_imsg_when_present(self, tmp_path, monkeypatch):
        stub = tmp_path / "bin" / "imsg"
        stub.parent.mkdir()
        stub.write_text(
            "#!/bin/sh\n"
            'echo \'{"contact_name": "Sam Example", "participants": ["+15550001111"]}\'\n'
            'echo \'{"contact_name": "", "participants": ["+15550002222"]}\'\n'
        )
        stub.chmod(0o755)
        monkeypatch.setenv("PATH", f"{stub.parent}{os.pathsep}{os.environ['PATH']}")

        db = build(
            tmp_path, [{"text": "hi", "chats": [1]}], [{"id": 1, "guid": "g", "participants": [1]}]
        )
        summary = export_history(tmp_path / "out", db)
        assert summary["messages_total"] == 1
        record = json.loads((tmp_path / "out" / "messages.jsonl").read_text().splitlines()[0])
        assert record["sender_name"] == "Sam Example"
        assert (tmp_path / "out" / "transcripts" / "1-Sam Example.txt").exists()

    def test_broken_imsg_is_not_fatal(self, tmp_path, monkeypatch):
        stub = tmp_path / "bin" / "imsg"
        stub.parent.mkdir()
        stub.write_text("#!/bin/sh\nnot json\n")
        stub.chmod(0o755)
        monkeypatch.setenv("PATH", f"{stub.parent}{os.pathsep}{os.environ['PATH']}")

        db = build(
            tmp_path, [{"text": "hi", "chats": [1]}], [{"id": 1, "guid": "g", "participants": [1]}]
        )
        summary = export_history(tmp_path / "out", db)
        assert summary["messages_total"] == 1

    def test_no_imsg_on_path_is_not_fatal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
        db = build(
            tmp_path, [{"text": "hi", "chats": [1]}], [{"id": 1, "guid": "g", "participants": [1]}]
        )
        assert export_history(tmp_path / "out", db)["messages_total"] == 1


class TestChatLabelling:
    def test_display_name_wins(self, tmp_path):
        db = build(
            tmp_path,
            [{"text": "hi", "chats": [1]}],
            [{"id": 1, "guid": "g", "name": "Book Club", "participants": [1, 2]}],
        )
        export_history(tmp_path / "out", db, use_contacts=False)
        record = json.loads((tmp_path / "out" / "messages.jsonl").read_text().splitlines()[0])
        assert record["chat_name"] == "Book Club"
        assert record["is_group"] is True

    def test_multiple_participants_without_a_name(self, tmp_path):
        db = build(
            tmp_path,
            [{"text": "hi", "chats": [1]}],
            [{"id": 1, "guid": "g", "participants": [1, 2]}],
        )
        export_history(tmp_path / "out", db, use_contacts=False)
        record = json.loads((tmp_path / "out" / "messages.jsonl").read_text().splitlines()[0])
        assert "+15550001111" in record["chat_name"]
        assert "+15550002222" in record["chat_name"]

    def test_no_participants_falls_back_to_identifier(self, tmp_path):
        db = build(
            tmp_path,
            [{"text": "hi", "chats": [1]}],
            [{"id": 1, "guid": "g", "identifier": "chat123456"}],
        )
        export_history(tmp_path / "out", db, use_contacts=False)
        record = json.loads((tmp_path / "out" / "messages.jsonl").read_text().splitlines()[0])
        assert record["chat_name"] == "chat123456"
        assert record["is_group"] is False


class TestRenderingBranches:
    def test_all_markers_render(self, tmp_path):
        rows = [
            {"text": "original", "chats": [1]},
            {"text": "", "chats": [1], "thread": "GUID-1"},
            {"text": "edited one", "from_me": 1, "chats": [1], "edited": minutes(5)},
            {"text": "unsent one", "from_me": 1, "chats": [1], "retracted": minutes(6)},
            {"text": "junk", "chats": [1], "spam": 1},
            {"text": None, "chats": [1], "item_type": 1, "from_me": 1},
            {"text": None, "chats": [1], "system": 1, "from_me": 1},
            {"from_me": 1, "chats": [1], "associated": 2000, "target": "p:0/GUID-1"},
            {"from_me": 1, "chats": [1], "associated": 3000, "target": "p:0/GUID-1"},
        ]
        db = build(tmp_path, rows, [{"id": 1, "guid": "g", "participants": [1]}])
        export_history(tmp_path / "out", db, use_contacts=False)
        transcript = next((tmp_path / "out" / "transcripts").glob("*.txt")).read_text()

        assert "↳" in transcript  # threaded reply marker
        assert "[edited]" in transcript
        assert "[unsent]" in transcript
        assert "[filtered as junk]" in transcript
        assert "[group event]" in transcript
        assert "[Loved ❤️ from Me]" in transcript
        assert "(removed)" not in transcript  # removed reactions are not shown

    def test_attachment_status_is_printed(self, tmp_path):
        store = tmp_path / "store"
        store.mkdir()
        (store / "pic.jpg").write_bytes(b"x")
        db = build(
            tmp_path, [{"text": "pic", "chats": [1]}], [{"id": 1, "guid": "g", "participants": [1]}]
        )
        con = sqlite3.connect(db)
        con.execute(
            "insert into attachment values "
            "(1, 'A1', ?, 'public.jpeg', 'image/jpeg', 'pic.jpg', 1, 0, 0)",
            (str(store / "pic.jpg"),),
        )
        con.execute("insert into message_attachment_join values (1, 1)")
        con.commit()
        con.close()

        export_history(tmp_path / "out", db, use_contacts=False)
        transcript = next((tmp_path / "out" / "transcripts").glob("*.txt")).read_text()
        assert "[file] pic.jpg (copied)" in transcript


class TestAttachmentFallbacks:
    def test_file_recovered_from_the_store_by_name(self, tmp_path, monkeypatch):
        store = tmp_path / "Attachments"
        (store / "aa" / "bb").mkdir(parents=True)
        recovered = store / "aa" / "bb" / "moved.jpg"
        recovered.write_bytes(b"found")
        monkeypatch.setattr("imsg_export.exporter.ATTACHMENT_STORE", str(store))

        db = build(
            tmp_path, [{"text": "x", "chats": [1]}], [{"id": 1, "guid": "g", "participants": [1]}]
        )
        con = sqlite3.connect(db)
        con.execute(
            "insert into attachment values "
            "(1, 'A1', ?, 'public.jpeg', 'image/jpeg', 'moved.jpg', 5, 0, 0)",
            (str(tmp_path / "gone" / "moved.jpg"),),
        )
        con.execute("insert into message_attachment_join values (1, 1)")
        con.commit()
        con.close()

        summary = export_history(tmp_path / "out", db, use_contacts=False)
        assert summary["attachments_copied"] == 1
        assert summary["attachments_purged"] == 0


class TestCliBranches:
    def test_export_with_readme_flag(self, tmp_path, capsys):
        db = build(
            tmp_path, [{"text": "hi", "chats": [1]}], [{"id": 1, "guid": "g", "participants": [1]}]
        )
        code = main(["export", str(tmp_path / "out"), "--db", str(db), "--no-contacts", "--readme"])
        assert code == 0
        assert (tmp_path / "out" / "README.md").exists()
        assert "README.md written" in capsys.readouterr().out

    def test_readme_command(self, tmp_path, capsys):
        db = build(
            tmp_path, [{"text": "hi", "chats": [1]}], [{"id": 1, "guid": "g", "participants": [1]}]
        )
        target = tmp_path / "out"
        main(["export", str(target), "--db", str(db), "--no-contacts"])
        capsys.readouterr()
        assert main(["readme", str(target)]) == 0
        assert "wrote" in capsys.readouterr().out

    def test_module_entry_point(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["imsg-export", "--version"])
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("imsg_export", run_name="__main__")
        assert exc.value.code == 0


class TestMiscellaneous:
    def test_dump_messages_round_trips(self, tmp_path):
        db = build(
            tmp_path, [{"text": "one", "chats": [1]}], [{"id": 1, "guid": "g", "participants": [1]}]
        )
        export_history(tmp_path / "out", db, use_contacts=False)
        dumped = json.loads(dump_messages(tmp_path / "out" / "messages.jsonl"))
        assert dumped[0]["text"] == "one"

    def test_absurd_timestamp_is_dropped(self):
        assert apple_timestamp(10**30) is None

    def test_verify_reports_transcript_lines(self, tmp_path):
        db = build(
            tmp_path,
            [{"text": "a", "chats": [1]}, {"text": "b", "chats": [1]}],
            [{"id": 1, "guid": "g", "participants": [1]}],
        )
        export_history(tmp_path / "out", db, use_contacts=False)
        result = verify_export(tmp_path / "out", db)
        assert result.transcript_lines == 2
        assert result.non_reaction_rows == 2

    def test_export_into_existing_folder_is_idempotent(self, tmp_path):
        db = build(
            tmp_path, [{"text": "a", "chats": [1]}], [{"id": 1, "guid": "g", "participants": [1]}]
        )
        export_history(tmp_path / "out", db, use_contacts=False)
        first = (tmp_path / "out" / "messages.jsonl").read_text()
        export_history(tmp_path / "out", db, use_contacts=False)
        assert (tmp_path / "out" / "messages.jsonl").read_text() == first

    def test_unreadable_attributed_body_falls_back_to_empty(self, tmp_path):
        db = build(
            tmp_path,
            [{"text": None, "body": b"\x00garbage\x00", "chats": [1]}],
            [{"id": 1, "guid": "g", "participants": [1]}],
        )
        summary = export_history(tmp_path / "out", db, use_contacts=False)
        assert summary["text_sources"]["none"] == 1
        record = json.loads((tmp_path / "out" / "messages.jsonl").read_text().splitlines()[0])
        assert record["text"] == ""

    def test_body_without_text_column_is_recovered(self, tmp_path):
        db = build(
            tmp_path,
            [{"text": None, "body": body_blob("from the blob"), "chats": [1]}],
            [{"id": 1, "guid": "g", "participants": [1]}],
        )
        export_history(tmp_path / "out", db, use_contacts=False)
        record = json.loads((tmp_path / "out" / "messages.jsonl").read_text().splitlines()[0])
        assert record["text"] == "from the blob"
        assert record["text_source"] == "attributedBody"
