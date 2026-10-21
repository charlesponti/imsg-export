# Changelog

All notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioning follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-10-21

### Fixed

- `attributedBody` decoding could be fooled by bytes that look like a marker: it took
  the first `0x84 0x01 0x2b` sequence and trusted the length that followed. Candidates
  are now validated against the payload length and the `0x86 0x84` terminator, with the
  first valid one winning. Output is unchanged on a 23,394-blob database.
- `messages.jsonl` could contain raw U+0085, U+2028 or U+2029 inside message text, which
  `str.splitlines()`, `wc -l` and most line-oriented tools treat as record separators.
  Those characters are now escaped, so one record is always one physical line.
- Building the attachment index walked the entire Messages attachment store on every
  export, even when there was nothing to resolve. It is now built lazily.

### Performance

- Per-chat message counts were computed with a nested scan over every message for
  every chat — O(chats x messages), ~1.1 s on a 23.7k-message library. One `Counter`
  pass replaces it (~3 ms). End-to-end export of that library: ~3.0 s to ~1.8 s.
- `clean_text` filtered text with a per-character generator; a precompiled
  control-character regex with a fast path is ~9x faster (67 ms to 8 ms over 23k
  messages) with byte-identical output, checked against 200k random strings.

### Added

- `py.typed` and strict mypy configuration; the package type-checks clean.
- Hypothesis property tests over the decoder, timestamp handling and the exporter
  (export → verify round-trip, determinism), plus 100% line coverage enforced in CI.
- `scripts/check_no_pii.py` and a pinned full-history gitleaks scan in CI.
- `.github/badges/coverage.svg` and `scripts/coverage_badge.py`.

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
