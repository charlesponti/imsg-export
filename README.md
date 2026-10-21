# imsg-export

Export the full contents of macOS Messages.app — iMessage, SMS and RCS — to portable
JSONL, CSV and readable transcripts. Standard library only, no dependencies.

    uvx imsg-export export ~/imessage-export

## Why not just the `imsg` CLI?

Because the CLI is a view of Messages.app, and Messages.app hides deleted conversations.
Deleting a chat removes its rows from `chat_message_join` but leaves every message row in
`chat.db`. Anything that joins through the chat table — which is most tooling — silently
drops them.

On the machine this was built against, that gap was 74% of the entire history. Those messages are still recoverable; they just aren't reachable from the app.

`imsg-export` reads `message` directly, so it exports everything the database holds, and
labels each record with how it was attached:

| `attribution` | meaning |
|---|---|
| `chat` | belongs to a conversation that still exists |
| `received-unlinked` | conversation deleted; message and sender survive, thread does not |
| `sent-unattributed` | conversation deleted; message survives, recipient is gone |

## Install

    uv tool install imsg-export      # isolated CLI on your PATH
    uvx imsg-export --help           # or run without installing
    pip install imsg-export          # or the classic way

Requires macOS and Python 3.11+. **Full Disk Access** must be granted to the terminal
(or whatever app runs it): System Settings → Privacy & Security → Full Disk Access.
Without it `chat.db` is unreadable.

## Use

    imsg-export export ~/imessage-export          # write the export
    imsg-export verify ~/imessage-export          # audit it against chat.db
    imsg-export readme ~/imessage-export          # (re)generate the folder's README
    imsg-export all ~/imessage-export             # all three, exits 1 if the audit fails

Useful flags: `--db PATH` to point at a copied or mounted `chat.db`, `--no-contacts` to
skip the optional `imsg` lookup that maps phone numbers to contact names.

## What you get

    imessage-export/
    ├── messages.jsonl           every message, one JSON object per line, chronological
    ├── all-messages.csv         the same rows, flat, for Excel/Sheets/Numbers
    ├── chats.json               every chat record, including empty ones
    ├── transcripts/             one timestamped .txt per conversation
    │   └── orphaned/            deleted conversations: per-sender, plus sent-only bucket
    ├── attachments/             recovered media + manifest.csv with per-file status
    ├── summary.json             counts, date range, attachment tallies
    ├── audit.txt                verify output (with `all`)
    └── README.md                generated description of this specific export

Every message record carries: `id`, `guid`, `created_at` (UTC), `created_at_local`,
`chat_id`, `chat_ids`, `chat_name`, `is_group`, `service`, `account`, `sender`,
`sender_name`, `is_from_me`, `kind`, `text`, `text_source`, `item_type`,
`balloon_bundle_id`, `effect`, `thread_originator_guid`, `reply_to_guid`, `is_read`,
`is_delivered`, `is_spam`, `edited_at`, `retracted_at`, `has_chat`, `attribution`,
`attachments[]`, `reaction`.

## What it handles

- **Empty `text` column.** Roughly half of all rows store the body only in an
  `attributedBody` typedstream blob. It is decoded, and `text_source` tells you which
  column a row's text came from.
- **Tapbacks.** Stored as their own rows with `associated_message_type` 2000–2006
  (added) and 3000–3006 (removed); the target GUID needs its `p:0/` prefix stripped.
  Rendered inline on the message they belong to, and kept as rows in the JSONL.
- **Attachments.** `attachment.filename` is often already purged. Present files are
  copied; missing ones fall back to a basename index of the attachment store; the rest
  are recorded as `purged` in `manifest.csv` so a reference is never silently lost.
- **Timestamps.** Apple epoch, arriving as nanoseconds, occasionally microseconds or
  seconds — the magnitude decides.
- **Replies, edits, unsends.** `thread_originator_guid` (not `reply_to_guid`, which
  modern macOS sets far too liberally), `date_edited`, `date_retracted`.

## Verification

`imsg-export verify` compares identity, not totals — a count match can hide a dropped
conversation and a duplicated row elsewhere. It checks:

- every `message.ROWID` in the database is in the export, and no extras
- text is identical wherever the database still stores plain text
- one manifest row per `message_attachment_join` row
- transcript lines reconcile with non-reaction rows plus inline reactions

Exit code is 0 only when all of that holds.

## Library use

```python
from imsg_export import export_history, verify_export, iter_messages

summary = export_history("~/imessage-export")
assert verify_export("~/imessage-export").ok

for message in iter_messages("~/imessage-export/messages.jsonl"):
    if message["sender_name"] == "Alex Rivera":
        print(message["created_at"], message["text"])
```

## Limits

- Conversation structure for deleted chats is unrecoverable. The database keeps the
  message, its sender and its timestamp — nothing else. Time-proximity reconstruction was
  tried and rejected: bursts of unrelated texts within the same minute made it wrong
  often enough to be worse than nothing.
- Snapshot of the local database, not iCloud. Anything not synced to this Mac is absent.
- Edited messages expose the current text; the pre-edit text is not in `chat.db`.
- macOS only. The parsers are pure Python, but there is no database to read elsewhere.

## Development

    uv sync                    # venv + dev tools
    uv run pytest              # tests, including a synthetic chat.db
    uv run ruff check .        # lint
    uv build                   # sdist + wheel into dist/

`docs/legacy/` holds the first, superseded attempt at this — the imsg-CLI-only exporter
that missed 74% of the history, kept as a record of why the database is the source of truth.

## Licence

MIT.
