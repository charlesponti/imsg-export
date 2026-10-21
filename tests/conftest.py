"""A tiny synthetic chat.db, so the exporter can be tested without a real Mac."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from helpers import SCHEMA, body_blob, minutes


@pytest.fixture
def fake_db(tmp_path: Path) -> Path:
    """chat.db with one live conversation, two orphans, a reaction and two files."""
    store = tmp_path / "store"
    store.mkdir()
    present = store / "photo.jpg"
    present.write_bytes(b"jpeg-bytes")

    db = tmp_path / "chat.db"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)

    con.execute("insert into handle values (1, '+15550001111', 'iMessage', 'US')")
    con.execute("insert into handle values (2, '+15550002222', 'iMessage', 'US')")
    con.execute("insert into chat values (1, 'any;-;+15550001111', '+15550001111', '', 'iMessage')")
    con.execute("insert into chat_handle_join values (1, 1)")

    def add(
        rowid: int,
        guid: str,
        *,
        text: str | None = None,
        body: bytes | None = None,
        handle: int = 1,
        from_me: int = 0,
        offset: int = 0,
        **extra: object,
    ) -> None:
        columns: dict[str, object] = {
            "ROWID": rowid,
            "guid": guid,
            "text": text,
            "attributedBody": body,
            "handle_id": handle,
            "service": "iMessage",
            "account": "E:test@example.com",
            "date": minutes(offset),
            "is_from_me": from_me,
            "is_read": 1,
            "is_sent": from_me,
            "is_delivered": 1,
            "item_type": 0,
            "cache_has_attachments": 0,
            "associated_message_type": 0,
            "is_spam": 0,
            "is_system_message": 0,
        }
        columns.update(extra)
        names = ", ".join(columns)
        marks = ", ".join("?" for _ in columns)
        con.execute(f"insert into message ({names}) values ({marks})", list(columns.values()))

    add(1, "GUID-1", text="hey there")
    add(2, "GUID-2", body=body_blob("recovered from blob"), from_me=1, offset=1)
    add(
        3,
        "GUID-3",
        from_me=1,
        offset=2,
        associated_message_type=2000,
        associated_message_guid="p:0/GUID-1",
        associated_message_emoji="❤️",
    )
    add(4, "GUID-4", text="photo attached", from_me=1, offset=3)
    add(5, "GUID-5", text="this one is gone", from_me=1, offset=4)
    # No chat_message_join for these two: the conversation was deleted in Messages.
    add(6, "GUID-6", text="orphan received", handle=2, offset=5)
    add(7, "GUID-7", text="orphan sent", handle=0, from_me=1, offset=6)

    for message_id in (1, 2, 3, 4, 5):
        con.execute("insert into chat_message_join values (1, ?)", (message_id,))

    con.execute(
        "insert into attachment values (10, 'ATT-1', ?, 'public.jpeg', 'image/jpeg',"
        " 'photo.jpg', 10, 0, 0)",
        (str(present),),
    )
    con.execute(
        "insert into attachment values (11, 'ATT-2', ?, 'public.jpeg', 'image/jpeg',"
        " 'gone.jpg', 99, 0, 0)",
        (str(store / "gone.jpg"),),
    )
    con.execute("insert into message_attachment_join values (4, 10)")
    con.execute("insert into message_attachment_join values (5, 11)")

    con.commit()
    con.close()
    return db


@pytest.fixture
def exported(tmp_path: Path, fake_db: Path) -> tuple[Path, dict]:
    """Run a real export of the synthetic database."""
    from imsg_export import export_history

    target = tmp_path / "out"
    summary = export_history(target, fake_db, use_contacts=False)
    return target, summary
