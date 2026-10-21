"""Audit an export against the live database.

Counting rows is not enough: a count match can hide a dropped conversation and a
duplicated row elsewhere. This compares identity, not totals.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .apple import clean_text
from .exporter import default_db_path, iter_messages


@dataclass
class VerifyResult:
    database_rows: int = 0
    export_rows: int = 0
    missing: list[int] = field(default_factory=list)
    extra: list[int] = field(default_factory=list)
    text_mismatches: list[tuple[int, str, str]] = field(default_factory=list)
    db_text_rows: int = 0
    db_attachment_refs: int = 0
    export_attachment_refs: int = 0
    messages_with_attachments: int = 0
    empty_messages: int = 0
    transcript_lines: int = 0
    non_reaction_rows: int = 0
    reaction_rows: int = 0

    @property
    def ok(self) -> bool:
        return not self.missing and not self.extra and not self.text_mismatches

    def report(self) -> str:
        lines = [
            f"chat.db message rows      : {self.database_rows:,}",
            f"export jsonl rows         : {self.export_rows:,}",
            f"missing from export       : {len(self.missing)}",
            f"rows not in chat.db       : {len(self.extra)}",
            f"text mismatches           : {len(self.text_mismatches)}"
            f"  (of {self.db_text_rows:,} rows with stored text)",
            f"attachment refs in db     : {self.db_attachment_refs:,}",
            f"attachment refs in export : {self.export_attachment_refs:,}",
            f"messages w/ attachments   : {self.messages_with_attachments:,}",
            f"rows w/ no text & no file : {self.empty_messages:,}",
            f"transcript message lines  : {self.transcript_lines:,}"
            f"  (non-reaction rows: {self.non_reaction_rows:,},"
            f" inline reactions: {self.reaction_rows:,})",
            "",
        ]
        if self.missing:
            lines.append(f"MISSING: {sorted(self.missing)[:20]}")
        if self.extra:
            lines.append(f"EXTRA: {sorted(self.extra)[:20]}")
        for message_id, want, got in self.text_mismatches[:5]:
            lines.append(f"TEXT DIFF {message_id}: {want!r} != {got!r}")
        lines.append(f"VERDICT: {'complete' if self.ok else 'INCOMPLETE'}")
        return "\n".join(lines)


def verify_export(target: str | Path, db: str | Path | None = None) -> VerifyResult:
    """Compare an exported folder with the database it came from."""
    root = Path(target).expanduser()
    path = Path(db).expanduser() if db else default_db_path()

    messages_file = root / "messages.jsonl"
    if not messages_file.exists():
        raise FileNotFoundError(f"no messages.jsonl in {root}")

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        db_ids = {row[0] for row in con.execute("select ROWID from message")}
        db_text = {row[0]: (row[1] or "") for row in con.execute("select ROWID, text from message")}
        db_attachment_refs = con.execute("select count(*) from message_attachment_join").fetchone()[
            0
        ]
    finally:
        con.close()

    result = VerifyResult(
        database_rows=len(db_ids),
        db_attachment_refs=db_attachment_refs,
        db_text_rows=sum(1 for value in db_text.values() if value.strip()),
    )

    exported: dict[int, dict[str, Any]] = {}
    for message in iter_messages(messages_file):
        exported[message["id"]] = message

    result.export_rows = len(exported)
    result.missing = sorted(db_ids - set(exported))
    result.extra = sorted(set(exported) - db_ids)

    for message_id, raw in db_text.items():
        record = exported.get(message_id)
        if record is None:
            continue
        want = clean_text(raw)
        if want and want != record["text"]:
            result.text_mismatches.append((message_id, want[:60], record["text"][:60]))

    manifest_path = root / "attachments" / "manifest.csv"
    if manifest_path.exists():
        with manifest_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        result.export_attachment_refs = len(rows)
        result.messages_with_attachments = len({row["message_id"] for row in rows})

    result.empty_messages = sum(
        1 for message in exported.values() if not message["text"] and not message["attachments"]
    )
    result.reaction_rows = sum(1 for m in exported.values() if m["kind"].startswith("reaction"))
    result.non_reaction_rows = len(exported) - result.reaction_rows

    transcripts = root / "transcripts"
    if transcripts.exists():
        for file in transcripts.rglob("*.txt"):
            with file.open(encoding="utf-8") as handle:
                result.transcript_lines += sum(1 for line in handle if line.startswith("["))
    return result


def dump_messages(path: str | Path) -> str:  # pragma: no cover - convenience helper
    return json.dumps(list(iter_messages(Path(path).expanduser())), ensure_ascii=False, indent=2)
