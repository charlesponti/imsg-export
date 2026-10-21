"""Read ~/Library/Messages/chat.db and write a portable export.

The important design decision: messages come from the `message` table, not from a
join through `chat_message_join`. Deleting a conversation in Messages.app removes
the join rows but leaves the messages, so any chat-joined query silently loses
them. Each record therefore carries an `attribution` field saying whether it still
belongs to a live conversation or is a survivor of a deleted one.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import sqlite3
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .apple import (
    TAPBACK_ADDED,
    TAPBACK_REMOVED,
    apple_timestamp,
    clean_text,
    decode_attributed_body,
    iso_utc,
    local_time,
    reaction_label,
)

DEFAULT_DB = "~/Library/Messages/chat.db"
ATTACHMENT_STORE = "~/Library/Messages/Attachments"

#: Bucket used for outgoing messages whose conversation was deleted: the database
#: keeps no recipient for them, only the timestamp.
SENT_WITHOUT_RECIPIENT = "_sent-with-no-recipient-record"

Message = dict[str, Any]


class ExportError(RuntimeError):
    """Raised when the database cannot be read or the target is unusable."""


def default_db_path() -> Path:
    return Path(os.path.expanduser(DEFAULT_DB))


def safe_name(value: object) -> str:
    """Filesystem-safe label for transcripts and attachment folders."""
    cleaned = "".join(c if c.isalnum() or c in "-_.+@ " else "_" for c in str(value))
    return cleaned.strip()[:60] or "unknown"


def _connect(db: Path) -> sqlite3.Connection:
    if not db.exists():
        raise ExportError(f"no Messages database at {db}")
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        con.execute("select count(*) from message").fetchone()
    except sqlite3.Error as exc:  # pragma: no cover - depends on host permissions
        raise ExportError(
            f"cannot read {db}: {exc}. Grant Full Disk Access to your terminal."
        ) from exc
    return con


def _contact_names() -> dict[str, str]:
    """Handle -> contact name, from the optional `imsg` CLI. Never fatal."""
    names: dict[str, str] = {}
    try:
        result = subprocess.run(
            ["imsg", "chats", "--limit", "10000", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return names
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            chat = json.loads(line)
        except json.JSONDecodeError:
            continue
        contact = chat.get("contact_name")
        if not contact:
            continue
        for participant in chat.get("participants") or []:
            names[participant] = contact
    return names


def _load_graph(
    con: sqlite3.Connection,
) -> tuple[
    dict[int, str],
    dict[int, dict[str, Any]],
    dict[int, list[int]],
    dict[int, list[dict[str, Any]]],
]:
    handles = {row["ROWID"]: row["id"] for row in con.execute("select ROWID, id from handle")}

    chats: dict[int, dict[str, Any]] = {}
    for row in con.execute(
        "select ROWID, guid, chat_identifier, display_name, service_name from chat"
    ):
        chats[row["ROWID"]] = {
            "id": row["ROWID"],
            "guid": row["guid"],
            "chat_identifier": row["chat_identifier"],
            "display_name": row["display_name"] or "",
            "service": row["service_name"] or "",
            "participants": [],
            "message_count": 0,
        }
    for row in con.execute("select chat_id, handle_id from chat_handle_join"):
        chat = chats.get(row["chat_id"])
        handle = handles.get(row["handle_id"], "")
        if chat is not None and handle and handle not in chat["participants"]:
            chat["participants"].append(handle)

    message_chats: dict[int, list[int]] = defaultdict(list)
    for row in con.execute("select chat_id, message_id from chat_message_join"):
        message_chats[row["message_id"]].append(row["chat_id"])

    attachments: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in con.execute(
        """
        select a.ROWID as id, a.filename, a.transfer_name, a.uti, a.mime_type,
               a.total_bytes, a.is_sticker, a.hide_attachment, j.message_id
        from attachment a
        join message_attachment_join j on j.attachment_id = a.ROWID
        """
    ):
        attachments[row["message_id"]].append(
            {
                "id": row["id"],
                "filename": row["filename"],
                "transfer_name": row["transfer_name"],
                "uti": row["uti"],
                "mime_type": row["mime_type"],
                "bytes": row["total_bytes"],
                "is_sticker": bool(row["is_sticker"]),
                "hidden": bool(row["hide_attachment"]),
            }
        )
    return handles, chats, message_chats, attachments


def _chat_label(
    chat_ids: list[int], chats: dict[int, dict[str, Any]], names: dict[str, str]
) -> tuple[str | None, bool]:
    if not chat_ids:
        return None, False
    chat = chats.get(chat_ids[0], {})
    if chat.get("display_name"):
        return chat["display_name"], True
    participants = chat.get("participants") or []
    if len(participants) > 1:
        return ", ".join(names.get(p, p) for p in participants), True
    handle = participants[0] if participants else chat.get("chat_identifier", "")
    return names.get(handle, handle) or f"chat {chat_ids[0]}", False


def _build_messages(
    con: sqlite3.Connection,
    handles: dict[int, str],
    chats: dict[int, dict[str, Any]],
    message_chats: dict[int, list[int]],
    names: dict[str, str],
) -> list[Message]:
    rows = con.execute(
        """
        select ROWID, guid, text, attributedBody, handle_id, service, account,
               date, date_read, is_from_me, is_read, is_sent, is_delivered, item_type,
               cache_has_attachments, associated_message_type, associated_message_guid,
               associated_message_emoji, balloon_bundle_id, reply_to_guid,
               thread_originator_guid, date_edited, date_retracted, is_spam,
               is_system_message, expressive_send_style_id, group_title
        from message
        order by date asc, ROWID asc
        """
    ).fetchall()

    messages: list[Message] = []
    for row in rows:
        stored = clean_text(row["text"])
        decoded = clean_text(decode_attributed_body(row["attributedBody"]))
        text = stored or decoded
        text_source = "text" if stored else ("attributedBody" if decoded else "none")
        associated = row["associated_message_type"] or 0
        if associated in TAPBACK_ADDED or associated in TAPBACK_REMOVED:
            kind = "reaction-removed" if associated in TAPBACK_REMOVED else "reaction"
        elif row["is_system_message"]:
            kind = "system"
        elif row["item_type"] and row["item_type"] != 0:
            kind = "group-action"
        else:
            kind = "message"

        sender = "me" if row["is_from_me"] else (handles.get(row["handle_id"], "") or "unknown")
        moment = apple_timestamp(row["date"])
        chat_ids = sorted(message_chats.get(row["ROWID"], []))
        label, is_group = _chat_label(chat_ids, chats, names) if chat_ids else (None, False)

        record: Message = {
            "id": row["ROWID"],
            "guid": row["guid"],
            "created_at": iso_utc(moment),
            "created_at_local": local_time(moment),
            "chat_id": chat_ids[0] if chat_ids else None,
            "chat_ids": chat_ids,
            "chat_name": label,
            "is_group": is_group,
            "service": row["service"],
            "account": row["account"],
            "sender": sender,
            "sender_name": names.get(sender, sender),
            "is_from_me": bool(row["is_from_me"]),
            "kind": kind,
            "text": text,
            "text_source": text_source,
            "item_type": row["item_type"],
            "balloon_bundle_id": row["balloon_bundle_id"],
            "effect": row["expressive_send_style_id"],
            "reply_to_guid": row["reply_to_guid"],
            "thread_originator_guid": row["thread_originator_guid"],
            "is_read": bool(row["is_read"]),
            "is_delivered": bool(row["is_delivered"]),
            "is_spam": bool(row["is_spam"]),
            "edited_at": iso_utc(apple_timestamp(row["date_edited"]))
            if row["date_edited"]
            else None,
            "retracted_at": (
                iso_utc(apple_timestamp(row["date_retracted"])) if row["date_retracted"] else None
            ),
            "has_chat": bool(chat_ids),
            "attribution": (
                "chat"
                if chat_ids
                else ("sent-unattributed" if row["is_from_me"] else "received-unlinked")
            ),
            "attachments": [],
            "reaction": None,
        }
        if kind.startswith("reaction"):
            record["reaction"] = {
                "type": reaction_label(associated),
                "action": "removed" if associated in TAPBACK_REMOVED else "added",
                "target_guid": row["associated_message_guid"],
                "emoji": row["associated_message_emoji"],
            }
        messages.append(record)
    return messages


def _attachment_index() -> dict[str, str]:
    """Basename -> path, built once.

    Walking the store for every missing attachment is O(n*m) and was the difference
    between a 4 second export and a 7 minute one.
    """
    index: dict[str, str] = {}
    root = os.path.expanduser(ATTACHMENT_STORE)
    if not os.path.isdir(root):
        return index
    for directory, _dirs, files in os.walk(root):
        for name in files:
            index.setdefault(name, os.path.join(directory, name))
    return index


def _copy_attachments(
    messages: list[Message],
    attachments: dict[int, list[dict[str, Any]]],
    target: Path,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    index: dict[str, str] | None = None
    manifest: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for record in messages:
        for attachment in attachments.get(record["id"], []):
            raw = attachment["filename"] or ""
            source = os.path.expanduser(raw) if raw.startswith("~") else raw
            group = safe_name(record["chat_name"] or record["sender_name"] or "unassigned")
            directory = target / "attachments" / group
            name = (
                attachment["transfer_name"] or os.path.basename(source) or f"att-{attachment['id']}"
            )

            resolved = None
            status = "purged"
            if source and os.path.exists(source):
                resolved = source
            elif source:
                if index is None:
                    index = _attachment_index()
                resolved = index.get(os.path.basename(source))

            destination = directory / f"{attachment['id']}-{name}"
            if resolved:
                directory.mkdir(parents=True, exist_ok=True)
                try:
                    if not destination.exists():
                        shutil.copy2(resolved, destination)
                    status = "copied"
                except OSError:
                    status = "copy-error"
            counts[status] += 1

            record["attachments"].append(
                {
                    "name": name,
                    "mime": attachment["mime_type"],
                    "bytes": attachment["bytes"],
                    "status": status,
                    "exported_to": str(destination.relative_to(target)) if resolved else None,
                }
            )
            manifest.append(
                {
                    "chat": record["chat_name"] or record["sender_name"] or "unassigned",
                    "chat_id": record["chat_id"],
                    "message_id": record["id"],
                    "sent_at": record["created_at"],
                    "from_me": record["is_from_me"],
                    "filename": name,
                    "mime": attachment["mime_type"],
                    "bytes": attachment["bytes"],
                    "status": status,
                    "source": resolved,
                }
            )
    return manifest, counts


def _render(messages: list[Message]) -> list[str]:
    """Render a conversation, folding reactions onto the message they target."""
    guids = {m["guid"] for m in messages}
    reactions: dict[str, list[tuple[dict[str, Any], Message]]] = defaultdict(list)
    for message in messages:
        if not message["kind"].startswith("reaction"):
            continue
        target = (message["reaction"]["target_guid"] or "").split("/")[-1].split(":")[-1]
        if target in guids:
            reactions[target].append((message["reaction"], message))

    lines: list[str] = []
    for message in messages:
        if message["kind"].startswith("reaction"):
            continue  # rendered inline on the target
        who = "Me" if message["is_from_me"] else (message["sender_name"] or "unknown")
        body = message["text"]
        if not body and message["attachments"]:
            body = "[attachment]"
        for reaction, source in reactions.get(message["guid"], []):
            if reaction["action"] == "removed":
                continue
            by = "Me" if source["is_from_me"] else (source["sender_name"] or "unknown")
            body += f"  [{reaction['type']} from {by}]"
        for attachment in message["attachments"]:
            body += f"\n    [file] {attachment['name']} ({attachment['status']})"
        if message["kind"] == "group-action":
            body = body or "[group event]"
        if message["thread_originator_guid"]:
            body = f"\u21b3 {body}"
        if message["edited_at"]:
            body += "  [edited]"
        if message["retracted_at"]:
            body += "  [unsent]"
        if message["is_spam"]:
            body += "  [filtered as junk]"
        lines.append(f"[{message['created_at_local']}] {who}: {body}")
    return lines


def _write_transcripts(
    messages: list[Message], chats: dict[int, dict[str, Any]], names: dict[str, str], target: Path
) -> None:
    by_chat: dict[int, list[Message]] = defaultdict(list)
    orphans: dict[str, list[Message]] = defaultdict(list)
    for message in messages:
        if message["chat_id"]:
            by_chat[message["chat_id"]].append(message)
        elif message["is_from_me"]:
            orphans[SENT_WITHOUT_RECIPIENT].append(message)
        else:
            orphans[message["sender_name"] or "unknown"].append(message)

    transcripts = target / "transcripts"
    orphan_dir = transcripts / "orphaned"
    orphan_dir.mkdir(parents=True, exist_ok=True)

    for chat_id, group in by_chat.items():
        chat = chats.get(chat_id, {})
        title = (
            chat.get("display_name")
            or ", ".join(names.get(p, p) for p in chat.get("participants") or [])
            or chat.get("chat_identifier")
            or str(chat_id)
        )
        header = [
            f"# {title}  (chat {chat_id}, {chat.get('service', '')})",
            f"{len(group)} messages, {group[0]['created_at_local']} -> "
            f"{group[-1]['created_at_local']}",
            "",
        ]
        (transcripts / f"{chat_id}-{safe_name(title)}.txt").write_text(
            "\n".join(header + _render(group)) + "\n", encoding="utf-8"
        )

    for who, group in orphans.items():
        note = (
            "outgoing messages whose chat record was deleted; the database keeps no "
            "recipient for them, so they are listed here by timestamp only"
            if who == SENT_WITHOUT_RECIPIENT
            else (
                "received messages from a conversation no longer in Messages; "
                "recovered from chat.db"
            )
        )
        header = [
            f"# {who}  ({note})",
            f"{len(group)} messages, {group[0]['created_at_local']} -> "
            f"{group[-1]['created_at_local']}",
            "",
        ]
        (orphan_dir / f"{safe_name(who)}.txt").write_text(
            "\n".join(header + _render(group)) + "\n", encoding="utf-8"
        )


def _write_csv(messages: list[Message], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "id",
                "sent_at_local",
                "sent_at_utc",
                "chat",
                "direction",
                "sender",
                "kind",
                "text",
                "attachments",
            ]
        )
        for message in messages:
            writer.writerow(
                [
                    message["id"],
                    message["created_at_local"],
                    message["created_at"],
                    message["chat_name"]
                    or ("(no chat record)" if message["is_from_me"] else "unlinked"),
                    "sent" if message["is_from_me"] else "received",
                    message["sender_name"],
                    message["kind"],
                    message["text"],
                    "; ".join(a["name"] for a in message["attachments"]),
                ]
            )


#: Line/paragraph separators are valid inside a JSON string but are treated as line
#: breaks by str.splitlines(), wc -l and most line-oriented tools. Escaping them keeps
#: one record per physical line for every consumer.
_LINE_BREAKS = {
    "\u0085": "\\u0085",  # NEL
    "\u2028": "\\u2028",  # line separator
    "\u2029": "\\u2029",  # paragraph separator
}


def jsonl_line(record: Message) -> str:
    """Serialise one record as a single physical line of JSON."""
    line = json.dumps(record, ensure_ascii=False)
    for raw, escaped in _LINE_BREAKS.items():
        if raw in line:
            line = line.replace(raw, escaped)
    return line


def iter_messages(path: Path) -> Iterator[Message]:
    """Stream records out of an exported messages.jsonl."""
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def export_history(
    target: str | Path,
    db: str | Path | None = None,
    *,
    use_contacts: bool = True,
) -> dict[str, Any]:
    """Export the whole Messages database into `target`.

    Returns the summary dict that is also written to `summary.json`.
    """
    target_path = Path(target).expanduser()
    target_path.mkdir(parents=True, exist_ok=True)
    (target_path / "transcripts").mkdir(exist_ok=True)
    (target_path / "attachments").mkdir(exist_ok=True)

    con = _connect(Path(db).expanduser() if db else default_db_path())
    try:
        names = _contact_names() if use_contacts else {}
        handles, chats, message_chats, attachments = _load_graph(con)
        messages = _build_messages(con, handles, chats, message_chats, names)
        table_total = con.execute("select count(*) from message").fetchone()[0]
    finally:
        con.close()

    manifest, attachment_counts = _copy_attachments(messages, attachments, target_path)

    with (target_path / "messages.jsonl").open("w", encoding="utf-8") as handle:
        for message in messages:
            handle.write(jsonl_line(message) + "\n")

    for chat in chats.values():
        chat["message_count"] = sum(1 for m in messages if m["chat_id"] == chat["id"])
    (target_path / "chats.json").write_text(
        json.dumps(list(chats.values()), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    attachment_dir = target_path / "attachments"
    attachment_dir.mkdir(exist_ok=True)
    with (attachment_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = list(manifest[0].keys()) if manifest else ["chat"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(manifest)

    _write_transcripts(messages, chats, names, target_path)
    _write_csv(messages, target_path / "all-messages.csv")

    orphaned = sum(1 for m in messages if not m["chat_id"])
    files = [p for p in attachment_dir.rglob("*") if p.is_file()]
    disk_bytes = sum(p.stat().st_size for p in files)
    dates = [m["created_at"] for m in messages if m["created_at"]]

    summary = {
        "exported_at": datetime.now(UTC).isoformat(),
        "source": str(Path(db).expanduser() if db else default_db_path()),
        "chats_total": len(chats),
        "chats_with_messages": len({m["chat_id"] for m in messages if m["chat_id"]}),
        "messages_total": len(messages),
        "messages_in_chats": len(messages) - orphaned,
        "messages_orphaned": orphaned,
        "sent_by_me": sum(1 for m in messages if m["is_from_me"]),
        "received": sum(1 for m in messages if not m["is_from_me"]),
        "rows_in_database": table_total,
        "kinds": dict(Counter(m["kind"] for m in messages)),
        "services": dict(Counter(m["service"] or "?" for m in messages)),
        "messages_with_attachments": sum(1 for m in messages if m["attachments"]),
        "attachment_references": len(manifest),
        "attachments_copied": attachment_counts.get("copied", 0),
        "attachments_purged": attachment_counts.get("purged", 0),
        "attachment_files_on_disk": len(files),
        "attachments_bytes_on_disk": disk_bytes,
        "orphan_senders": len({m["sender_name"] for m in messages if not m["chat_id"]}),
        "attribution": dict(Counter(m["attribution"] for m in messages)),
        "first_message": dates[0] if dates else None,
        "last_message": dates[-1] if dates else None,
        "text_sources": dict(Counter(m["text_source"] for m in messages)),
    }
    (target_path / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary
