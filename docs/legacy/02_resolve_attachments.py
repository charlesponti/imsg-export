"""Second pass over the imsg export: recovered attachments by exact filename and
wrote the manifest. Superseded by the direct-database exporter.
"""
import json, os, shutil, csv, subprocess
from collections import Counter

OUT = os.path.expanduser("~/imessage-export-2026-10-21")
ATT = os.path.join(OUT, "attachments")
ROOT = os.path.expanduser("~/Library/Messages/Attachments")

msgs = [json.loads(l) for l in open(os.path.join(OUT, "messages.jsonl"))]

# index the live Attachments tree by basename
byname = {}
for dp, dn, fn in os.walk(ROOT):
    for f in fn:
        byname.setdefault(f, []).append(os.path.join(dp, f))

def safe(s):
    return "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in s).strip()[:50] or "chat"

rows = []
stats = Counter()
for m in msgs:
    for a in m.get("attachments") or []:
        name = a.get("transfer_name") or "unnamed"
        src = a.get("original_path")
        label = m.get("_chat_label") or str(m["chat_id"])
        dest_dir = os.path.join(ATT, safe(label))
        dest = os.path.join(dest_dir, name)
        status = "missing"
        if src and os.path.exists(src):
            os.makedirs(dest_dir, exist_ok=True)
            if not os.path.exists(dest):
                shutil.copy2(src, dest)
            status = "copied"
        elif name in byname and len(byname[name]) == 1:
            os.makedirs(dest_dir, exist_ok=True)
            if not os.path.exists(dest):
                shutil.copy2(byname[name][0], dest)
            status = "recovered"
        elif name in byname:
            status = "duplicate-name"
        stats[status] += 1
        rows.append({
            "chat_id": m["chat_id"], "chat": label,
            "message_id": m.get("id"), "sent_at": m.get("created_at"),
            "from_me": m.get("is_from_me"), "filename": name,
            "mime": a.get("mime_type"), "bytes": a.get("total_bytes"),
            "status": status, "source_path": src,
        })

with open(os.path.join(ATT, "manifest.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

# accurate size on disk
total_bytes = 0
nfiles = 0
for dp, dn, fn in os.walk(ATT):
    for f in fn:
        total_bytes += os.path.getsize(os.path.join(dp, f))
        nfiles += 1

summary = json.load(open(os.path.join(OUT, "summary.json")))
summary["attachments"] = dict(stats)
summary["attachments_on_disk"] = nfiles
summary["attachments_bytes_on_disk"] = total_bytes
json.dump(summary, open(os.path.join(OUT, "summary.json"), "w"), indent=2)

per_chat = Counter(m["_chat_label"] for m in msgs)
readme = f"""# iMessage export — {summary['first_message'][:10]} to {summary['last_message'][:10]}

Exported {summary['exported_at']} from Messages.app via imsg v0.15.10.

## Contents

- `messages.jsonl` — every message, one JSON object per line, chronological.
  Fields: id, guid, created_at (UTC ISO8601), chat_id, chat_guid, chat_name,
  chat_identifier, participants, is_group, sender, sender_name, is_from_me,
  text, attachments[], reactions[], reply_to_guid, reply_to_text,
  date_read, is_read, destination_caller_id.
- `chats.json` — one record per conversation (id, participants, service, unread count).
- `transcripts/<id>-<name>.txt` — human-readable per-conversation transcript.
- `raw/chat-<id>.jsonl` — untouched `imsg history` output per chat.
- `attachments/<contact>/` — copied media files, plus `manifest.csv` mapping
  every attachment to its message, with status (copied / recovered / missing).
- `summary.json` — counts.

## Totals

- {summary['messages']} messages across {summary['chats']} conversations
  ({summary['sent_by_me']} sent, {summary['received']} received)
- services: {', '.join(f'{k} {v}' for k, v in summary['services'].items())}
- {summary['messages_with_attachments']} messages had attachments;
  {stats.get('copied',0)+stats.get('recovered',0)} of {len(rows)} files recovered
  ({total_bytes/1e6:.1f} MB on disk)

## Per conversation

""" + "\n".join(f"- {k}: {v}" for k, v in per_chat.most_common()) + f"""

## Known gaps

{stats.get('missing',0)} attachment references point at files macOS has already
purged from disk (mostly `.pluginPayloadAttachment` link-preview cache entries and
expired `tmp.gif`). Message rows and text are complete — only those media blobs are gone.
"""

open(os.path.join(OUT, "README.md"), "w").write(readme)
print(json.dumps(summary["attachments"], indent=2))
print("files on disk:", nfiles, f"{total_bytes/1e6:.1f} MB")
