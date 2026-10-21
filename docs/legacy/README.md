# legacy — superseded, reference only

These are the first four scripts written for this job, kept because they document the
dead ends. They are hardcoded to `~/imessage-export-2026-10-21` and expect the
`imsg` CLI output shape. Do not wire them into anything.

Order they were written:

1. `01_imsg_chat_export.py` — exported via `imsg chats` + `imsg history --json`.
   Looked complete, but covered only a fraction of the database: `imsg` only sees
   conversations that still have a `chat_message_join` row, so every deleted chat was
   missing. Most of the history lives in the same database, unreachable from the CLI.
2. `02_resolve_attachments.py` — copied attachments out of the imsg JSON, recovered
   same-basename files, wrote `manifest.csv`.
3. `03_resolve_by_uuid.py` — resolved the remaining attachments by matching their UUID
   parent directory when the basename was ambiguous.
4. `04_write_readme_simple.py` — wrote a README from `summary.json`.

`02` and `03` were merged into `export_messages.py`; `01` revealed that the database,
not the CLI, has to be the source of truth.

Lessons that survived into the real exporter:

- Count messages from `message`, never from a chat join.
- Walk the attachment store once and index it; per-attachment `os.walk` is O(n·m) and
  turned a 4-second export into a 7-minute one that hit the tool timeout.
- Cross-check attachment status per reference instead of trusting a single "copied" count.
