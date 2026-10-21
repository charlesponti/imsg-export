"""Third pass: resolved remaining attachments by their UUID parent directory.
Superseded.
"""
import json, os, shutil, csv
from collections import Counter

OUT = os.path.expanduser("~/imessage-export-2026-10-21")
ATT = os.path.join(OUT, "attachments")
ROOT = os.path.expanduser("~/Library/Messages/Attachments")

msgs = [json.loads(l) for l in open(os.path.join(OUT, "messages.jsonl"))]

dirs_by_name, files_by_name = {}, {}
for dp, dn, fn in os.walk(ROOT):
    dirs_by_name.setdefault(os.path.basename(dp), []).append(dp)
    for f in fn:
        files_by_name.setdefault(f, []).append(os.path.join(dp, f))

def safe(s):
    return "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in s).strip()[:50] or "chat"

rows, stats = [], Counter()
for m in msgs:
    for a in m.get("attachments") or []:
        name = a.get("transfer_name") or "unnamed"
        src = a.get("original_path") or ""
        label = m.get("_chat_label") or str(m["chat_id"])
        dest_dir = os.path.join(ATT, safe(label))
        dest = os.path.join(dest_dir, name)
        status, resolved = "missing", None

        if src and os.path.exists(src):
            resolved, status = src, "copied"
        else:
            parent = os.path.basename(os.path.dirname(src)) if src else ""
            cands = [d for d in dirs_by_name.get(parent, []) if os.path.exists(os.path.join(d, name))]
            if len(cands) == 1:
                resolved, status = os.path.join(cands[0], name), "recovered-uuid"
            elif len(files_by_name.get(name, [])) == 1:
                resolved, status = files_by_name[name][0], "recovered-name"
            elif len(cands) > 1:
                resolved, status = os.path.join(cands[0], name), "recovered-ambiguous"
            else:
                status = "purged"

        if resolved:
            os.makedirs(dest_dir, exist_ok=True)
            if not os.path.exists(dest):
                try:
                    shutil.copy2(resolved, dest)
                except Exception:
                    status = "copy-error"
                    resolved = None
        stats[status] += 1
        rows.append({"chat_id": m["chat_id"], "chat": label, "message_id": m.get("id"),
                     "sent_at": m.get("created_at"), "from_me": m.get("is_from_me"),
                     "filename": name, "mime": a.get("mime_type"),
                     "bytes": a.get("total_bytes"), "status": status,
                     "resolved_from": resolved, "original_path": src})

with open(os.path.join(ATT, "manifest.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)

nfiles = total = 0
for dp, dn, fn in os.walk(ATT):
    for f in fn:
        total += os.path.getsize(os.path.join(dp, f)); nfiles += 1

s = json.load(open(os.path.join(OUT, "summary.json")))
s["attachments"] = dict(stats)
s["attachments_on_disk"] = nfiles
s["attachments_bytes_on_disk"] = total
json.dump(s, open(os.path.join(OUT, "summary.json"), "w"), indent=2)

readme = open(os.path.join(OUT, "README.md")).read()
start = readme.index("- ") if "- " in readme else len(readme)
got = sum(v for k, v in stats.items() if k.startswith("copied") or k.startswith("recovered"))
head = readme.split("## Known gaps")[0]
head = head[:head.rindex("- ")] if "- " in head else head
new = head + f"""- {s['messages_with_attachments']} messages had {len(rows)} attachment references;
  {got} files restored ({total/1e6:.1f} MB) -> {', '.join(f'{k} {v}' for k, v in sorted(stats.items()))}

## Known gaps

{stats.get('purged',0)} attachment references point at files macOS has already purged
from disk (mostly `.pluginPayloadAttachment` link-preview caches and expired `tmp.gif`).
Message rows and all text are complete; only those media blobs no longer exist anywhere
on the machine. Every reference is listed in `attachments/manifest.csv` with its status.
"""
open(os.path.join(OUT, "README.md"), "w").write(new)
print(json.dumps(dict(stats), indent=2)); print("on disk:", nfiles, f"{total/1e6:.1f} MB")
