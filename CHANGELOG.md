# Changelog

All notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioning follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-21

### Added

- `imsg-export export` — reads `~/Library/Messages/chat.db` directly and writes
  `messages.jsonl`, `all-messages.csv`, `chats.json`, `summary.json`, per-conversation
  transcripts and recovered attachments.
- `imsg-export verify` — audits an export against the database by identity (missing rows,
  extra rows, text divergence, attachment reference counts) and exits non-zero on failure.
- `imsg-export readme` and `imsg-export all` — generate the export folder's README and run
  the full pipeline.
- Decoding of `attributedBody` typedstream blobs, so messages with an empty `text` column
  are exported rather than silently blank.
- Tapback reactions folded onto their target message in transcripts and kept as rows.
- `attribution` field distinguishing messages in live chats from survivors of deleted
  conversations (`received-unlinked`, `sent-unattributed`).
- Attachment recovery with a prebuilt basename index, plus a manifest recording `copied`,
  `purged` or `copy-error` per reference.

### Notes

- Python 3.11+, standard library only.
- macOS only: the source database is Messages.app's.
