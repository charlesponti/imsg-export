"""Minimal README writer for the imsg-only export. Superseded by write_readme.py.
"""
import json, os
from collections import Counter

OUT = os.path.expanduser("~/imessage-export-2026-10-21")
s = json.load(open(os.path.join(OUT, "summary.json")))
msgs = [json.loads(l) for l in open(os.path.join(OUT, "messages.jsonl"))]
per_chat = Counter(m["_chat_label"] for m in msgs)
att = s["attachments"]
restored = sum(v for k, v in att.items() if k.startswith(("copied", "recovered")))
total_refs = sum(att.values())

readme = f"""# iMessage export — {s['first_message'][:10]} to {s['last_message'][:10]}

Exported {s['exported_at']} from Messages.app on this Mac using imsg v0.15.10.

## Totals

- {s['messages']} messages across {s['chats']} conversations
- {s['sent_by_me']} sent by you, {s['received']} received
- Services: {', '.join(f'{k} {v}' for k, v in s['services'].items())}
- {s['messages_with_attachments']} messages carried {total_refs} attachment references;
  {restored} files restored to disk ({s['attachments_bytes_on_disk']/1e6:.1f} MB)

## Files

`messages.jsonl` — every message, one JSON object per line, chronological across all
chats. Fields: id, guid, created_at (UTC ISO8601), chat_id, chat_guid, chat_name,
chat_identifier, participants, is_group, sender, sender_name, is_from_me, text,
attachments[], reactions[], reply_to_guid, reply_to_text, date_read, is_read,
destination_caller_id. Extra export fields: _chat_label, _chat_is_group, _chat_service.

`chats.json` — one record per conversation (rowid, participants, service, unread count).

`transcripts/<chat-id>-<name>.txt` — plain-text transcript, timestamped, local time.

`raw/chat-<chat-id>.jsonl` — untouched `imsg history` output, one chat per file.

`attachments/<contact>/` — recovered media, with `manifest.csv` listing every
attachment reference: chat, message id, sent time, direction, filename, mime type,
status, and the path it was recovered from.

`summary.json` — machine-readable counts.

## Per conversation

""" + "\n".join(f"- {k}: {v} messages" for k, v in per_chat.most_common()) + f"""

## Attachment status

- copied: {att.get('copied', 0)} — original file still on disk, copied as-is
- recovered-name: {att.get('recovered-name', 0)} — original path gone, same filename
  found elsewhere in the Messages attachment store and copied from there
- purged: {att.get('purged', 0)} — file no longer exists anywhere on this Mac
  (mostly `.pluginPayloadAttachment` link-preview caches and expired `tmp.gif`)

Every one of the {total_refs} references is listed in `attachments/manifest.csv`, so
nothing is silently dropped. Message text itself is complete.

## Re-importing

Lines in `messages.jsonl` are self-contained JSON — load straight into pandas,
sqlite, or any JSON tool. To search text across the export:

    grep -i "search term" {OUT}/messages.jsonl

To rebuild from source at any time: `imsg history --chat-id <id> --limit 200000
--attachments --json`.
"""
open(os.path.join(OUT, "README.md"), "w").write(readme)
print(readme[:400])
