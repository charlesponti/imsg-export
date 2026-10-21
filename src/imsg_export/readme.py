"""Write a README.md into an export folder, derived from its own contents."""

from __future__ import annotations

import json
from pathlib import Path

from .exporter import iter_messages


def _count_lines(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.startswith("["))


def write_readme(target: str | Path) -> Path:
    """Generate `<export>/README.md` describing what was exported."""
    root = Path(target).expanduser()
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    messages = list(iter_messages(root / "messages.jsonl"))

    per_chat: dict[str, int] = {}
    for message in messages:
        if message["chat_name"]:
            per_chat[message["chat_name"]] = per_chat.get(message["chat_name"], 0) + 1

    transcripts = root / "transcripts"
    chat_files = sorted(p.name for p in transcripts.glob("*.txt"))
    orphan_dir = transcripts / "orphaned"
    orphan_files = sorted(orphan_dir.glob("*.txt")) if orphan_dir.exists() else []
    orphan_sizes = sorted(((_count_lines(p), p.name) for p in orphan_files), reverse=True)

    services = ", ".join(f"{k} {v:,}" for k, v in summary["services"].items())
    kinds = ", ".join(f"{k} {v:,}" for k, v in summary["kinds"].items())
    recovered = summary.get("text_sources", {}).get("attributedBody", 0)
    copied = summary["attachments_copied"]
    purged = summary["attachments_purged"]
    mb = summary["attachments_bytes_on_disk"] / 1e6
    orphaned = summary["messages_orphaned"]
    total = summary["messages_total"]

    audit = ""
    audit_file = root / "audit.txt"
    if audit_file.exists():
        audit = (
            "\n## Completeness check\n\n`audit.txt`, written by `imsg-export verify`:\n\n"
            "```\n" + audit_file.read_text(encoding="utf-8").strip() + "\n```\n"
        )

    first = summary["first_message"][:10]
    last = summary["last_message"][:10]
    body = (
        f"""# iMessage / SMS export — {first} to {last}

Pulled directly from `{summary["source"]}`.
Export run: {summary["exported_at"]}

## Totals

- {total:,} message rows — {summary["sent_by_me"]:,} sent, {summary["received"]:,} received
- {summary["chats_with_messages"]} live conversations ({summary["messages_in_chats"]:,} messages)
  with a current chat record in Messages
- {orphaned:,} messages whose conversation was deleted from Messages but whose rows are
  still in the database: {summary["attribution"].get("received-unlinked", 0):,} received
  (grouped by sender) and {summary["attribution"].get("sent-unattributed", 0):,} sent
  (no recipient stored)
- Services: {services}
- Rows by type: {kinds}
- {recovered:,} messages had an empty `text` column — their body was decoded from
  Apple's `attributedBody` blob
- {summary["messages_with_attachments"]:,} messages carried
  {summary["attachment_references"]:,} attachments; {copied:,} files restored ({mb:.0f} MB)

## Files

`messages.jsonl` — every message, one JSON object per line, chronological. Fields:
id, guid, created_at (UTC), created_at_local, chat_id, chat_ids, chat_name, is_group,
service, account, sender, sender_name, is_from_me, kind, text, text_source, item_type,
balloon_bundle_id, effect, thread_originator_guid, reply_to_guid, is_read, is_delivered,
is_spam, edited_at, retracted_at, has_chat, attribution, attachments[], reaction.

`kind` is one of `message`, `reaction`, `reaction-removed`, `group-action`, `system`.
`attribution` is `chat`, `received-unlinked` or `sent-unattributed`.
`text_source` is `text`, `attributedBody` or `none` — which column the text came from.

`all-messages.csv` — the same rows flattened for a spreadsheet.

`chats.json` — all {summary["chats_total"]} chat records, including the
{summary["chats_total"] - summary["chats_with_messages"]} with no messages left in them.

`transcripts/` — plain text, timestamped, local time:
"""
        + "\n".join(f"  - `{name}`" for name in chat_files)
        + f"""

`transcripts/orphaned/` — {len(orphan_files)} files for deleted conversations. Largest:
"""
        + "\n".join(f"  - `{name}` — {count:,} messages" for count, name in orphan_sizes[:8])
        + f"""

`attachments/<conversation>/` — recovered media, plus `manifest.csv` listing all
{summary["attachment_references"]:,} references with status, source path and message id.

`summary.json` — every count above, machine-readable.
{audit}
## Recovered vs. gone

{copied:,} attachment files were still on disk (or findable elsewhere in the Messages
attachment store) and were copied. {purged:,} references point at files macOS has already
purged — mostly `.pluginPayloadAttachment` link-preview caches, expired `tmp.gif` files and
stickers. Message rows and text are complete; only those blobs are gone. Every reference is
listed in the manifest, so nothing is silently dropped.

## Caveats

- {orphaned:,} of {total:,} rows ({orphaned / total * 100:.0f}%) belong to conversations deleted in
  Messages. The database keeps the messages but drops the chat link, so the conversation
  structure cannot be rebuilt — only the sender of a received message survives.
- Reactions are rendered inline on the message they target, and also kept as their own
  rows in `messages.jsonl`.
- Edited and unsent messages are flagged (`edited_at`, `retracted_at`), not rewritten.
- This is a snapshot of the local database, not iCloud. Anything not synced to this Mac
  is not here.

## Re-run

    imsg-export export {root}
    imsg-export verify {root}
"""
    )
    destination = root / "README.md"
    destination.write_text(body, encoding="utf-8")
    return destination
