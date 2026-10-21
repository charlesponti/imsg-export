"""End-to-end behaviour of the exporter and the verifier."""

from __future__ import annotations

import csv
import json

import pytest

from imsg_export import export_history, iter_messages, verify_export
from imsg_export.exporter import SENT_WITHOUT_RECIPIENT, ExportError


class TestExportShape:
    def test_writes_every_expected_artifact(self, exported):
        target, _ = exported
        for name in ("messages.jsonl", "all-messages.csv", "chats.json", "summary.json"):
            assert (target / name).exists(), name
        assert (target / "transcripts").is_dir()
        assert (target / "attachments" / "manifest.csv").exists()

    def test_every_database_row_is_exported(self, exported):
        target, summary = exported
        records = list(iter_messages(target / "messages.jsonl"))
        assert len(records) == 7
        assert summary["messages_total"] == 7
        assert summary["rows_in_database"] == 7
        assert [r["id"] for r in records] == [1, 2, 3, 4, 5, 6, 7]

    def test_records_are_chronological(self, exported):
        target, _ = exported
        stamps = [r["created_at"] for r in iter_messages(target / "messages.jsonl")]
        assert stamps == sorted(stamps)

    def test_chat_and_orphan_split(self, exported):
        _, summary = exported
        assert summary["messages_in_chats"] == 5
        assert summary["messages_orphaned"] == 2
        assert summary["attribution"] == {
            "chat": 5,
            "received-unlinked": 1,
            "sent-unattributed": 1,
        }


class TestContentReconstruction:
    def test_text_recovered_from_attributed_body(self, exported):
        target, _ = exported
        record = next(r for r in iter_messages(target / "messages.jsonl") if r["id"] == 2)
        assert record["text"] == "recovered from blob"
        assert record["text_source"] == "attributedBody"

    def test_plain_text_preferred_over_blob(self, exported):
        target, _ = exported
        record = next(r for r in iter_messages(target / "messages.jsonl") if r["id"] == 1)
        assert record["text_source"] == "text"

    def test_reaction_targets_its_message(self, exported):
        target, _ = exported
        reaction = next(r for r in iter_messages(target / "messages.jsonl") if r["id"] == 3)
        assert reaction["kind"] == "reaction"
        assert reaction["reaction"]["type"] == "Loved ❤️"
        assert reaction["reaction"]["action"] == "added"
        assert reaction["reaction"]["target_guid"] == "p:0/GUID-1"

    def test_reaction_rendered_inline_in_transcript(self, exported):
        target, _ = exported
        transcript = (target / "transcripts" / "1-+15550001111.txt").read_text(encoding="utf-8")
        assert "hey there  [Loved ❤️ from Me]" in transcript
        assert "recovered from blob" in transcript

    def test_reaction_rows_are_not_duplicated_as_lines(self, exported):
        target, _ = exported
        transcript = (target / "transcripts" / "1-+15550001111.txt").read_text(encoding="utf-8")
        lines = [line for line in transcript.splitlines() if line.startswith("[")]
        assert len(lines) == 4  # five records, the reaction folds into its target


class TestAttachments:
    def test_present_file_is_copied(self, exported):
        target, summary = exported
        assert summary["attachments_copied"] == 1
        assert summary["attachments_purged"] == 1
        copied = list((target / "attachments").rglob("*.jpg"))
        assert len(copied) == 1
        assert copied[0].read_bytes() == b"jpeg-bytes"

    def test_manifest_records_both_states(self, exported):
        target, _ = exported
        with (target / "attachments" / "manifest.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        statuses = {row["filename"]: row["status"] for row in rows}
        assert statuses == {"photo.jpg": "copied", "gone.jpg": "purged"}

    def test_purged_attachment_keeps_its_name_in_the_record(self, exported):
        target, _ = exported
        record = next(r for r in iter_messages(target / "messages.jsonl") if r["id"] == 5)
        assert record["attachments"][0]["name"] == "gone.jpg"
        assert record["attachments"][0]["status"] == "purged"


class TestOrphans:
    def test_received_orphan_grouped_by_sender(self, exported):
        target, _ = exported
        assert (target / "transcripts" / "orphaned" / "+15550002222.txt").exists()

    def test_sent_orphan_gets_the_unattributed_bucket(self, exported):
        target, _ = exported
        path = target / "transcripts" / "orphaned" / f"{SENT_WITHOUT_RECIPIENT}.txt"
        assert path.exists()
        assert "orphan sent" in path.read_text(encoding="utf-8")


class TestVerification:
    def test_clean_export_verifies(self, exported, fake_db):
        target, _ = exported
        result = verify_export(target, fake_db)
        assert result.ok
        assert result.missing == [] and result.extra == []
        assert result.export_rows == result.database_rows == 7
        assert result.db_attachment_refs == result.export_attachment_refs == 2

    def test_missing_row_is_detected(self, exported, fake_db):
        target, _ = exported
        path = target / "messages.jsonl"
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        result = verify_export(target, fake_db)
        assert not result.ok
        assert result.missing == [7]

    def test_text_divergence_is_detected(self, exported, fake_db):
        target, _ = exported
        path = target / "messages.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        records[0]["text"] = "tampered"
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8"
        )
        result = verify_export(target, fake_db)
        assert not result.ok
        assert result.text_mismatches[0][0] == 1

    def test_missing_export_file(self, tmp_path, fake_db):
        with pytest.raises(FileNotFoundError):
            verify_export(tmp_path / "empty", fake_db)


class TestErrors:
    def test_missing_database_is_reported(self, tmp_path):
        with pytest.raises(ExportError, match="no Messages database"):
            export_history(tmp_path / "out", tmp_path / "nope.db", use_contacts=False)

    def test_unreadable_database_is_reported(self, tmp_path):
        broken = tmp_path / "broken.db"
        broken.write_bytes(b"not a database")
        with pytest.raises(ExportError):
            export_history(tmp_path / "out", broken, use_contacts=False)
