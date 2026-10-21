"""First attempt: exported only the chats imsg could see (5,129 of 23,673 messages).
Kept as a reference for the imsg history --json output shape.
"""
import json, os, subprocess, sys, shutil
from datetime import datetime, timezone
from collections import Counter

OUT = os.path.expanduser("~/imessage-export-2026-10-21")
RAW = os.path.join(OUT, "raw")
TX = os.path.join(OUT, "transcripts")
ATT = os.path.join(OUT, "attachments")
for d in (OUT, RAW, TX, ATT):
    os.makedirs(d, exist_ok=True)

def run(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        print("FAIL", args, p.stderr[:300], file=sys.stderr)
    return p.stdout

# 1. chat list
chats = [json.loads(l) for l in run(["imsg", "chats", "--limit", "10000", "--json"]).splitlines() if l.strip()]
with open(os.path.join(OUT, "chats.json"), "w") as f:
    json.dump(chats, f, indent=2, ensure_ascii=False)

# 2. per-chat raw history
all_msgs = []
for c in chats:
    cid = c["id"]
    raw = run(["imsg", "history", "--chat-id", str(cid), "--limit", "200000",
               "--attachments", "--json"])
    msgs = [json.loads(l) for l in raw.splitlines() if l.strip()]
    with open(os.path.join(RAW, f"chat-{cid}.jsonl"), "w") as f:
        for m in msgs:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    label = c.get("contact_name") or c.get("display_name") or c.get("name") or str(cid)
    for m in msgs:
        m["_chat_label"] = label
        m["_chat_is_group"] = c.get("is_group", False)
        m["_chat_service"] = c.get("service", "")
    all_msgs.extend(msgs)
    print(f"chat {cid:>6}  {label[:34]:<34} {len(msgs):>5} msgs")

# 3. combined, chronological
all_msgs.sort(key=lambda m: m.get("created_at") or "")
with open(os.path.join(OUT, "messages.jsonl"), "w") as f:
    for m in all_msgs:
        f.write(json.dumps(m, ensure_ascii=False) + "\n")

# 4. readable transcripts
def ts(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso or ""

by_chat = {}
for m in all_msgs:
    by_chat.setdefault(m["chat_id"], []).append(m)

def safe(s):
    return "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in s).strip()[:50] or "chat"

for cid, msgs in by_chat.items():
    label = msgs[0]["_chat_label"]
    lines = [f"# {label}  (chat {cid}, {msgs[0]['_chat_service']})",
             f"{len(msgs)} messages, {ts(msgs[0].get('created_at'))} -> {ts(msgs[-1].get('created_at'))}", ""]
    for m in msgs:
        who = "Me" if m.get("is_from_me") else (m.get("sender_name") or m.get("sender") or "Them")
        body = (m.get("text") or "").strip()
        if not body and m.get("attachments"):
            body = "[attachment]"
        for a in m.get("attachments") or []:
            body += f"\n   [file] {a.get('transfer_name')}"
        if m.get("reactions"):
            body += "  " + " ".join(f"({r.get('kind')} by {r.get('sender')})" for r in m["reactions"])
        lines.append(f"[{ts(m.get('created_at'))}] {who}: {body}")
    with open(os.path.join(TX, f"{cid}-{safe(label)}.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")

# 5. attachments
files = 0
bytes_total = 0
missing = 0
for m in all_msgs:
    for a in m.get("attachments") or []:
        p = a.get("original_path")
        if not p or not os.path.exists(p):
            missing += 1
            continue
        dest_dir = os.path.join(ATT, safe(m["_chat_label"]))
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, a.get("transfer_name") or os.path.basename(p))
        if not os.path.exists(dest):
            shutil.copy2(p, dest)
            files += 1
        bytes_total += os.path.getsize(p)

# 6. summary
sent = sum(1 for m in all_msgs if m.get("is_from_me"))
svc = Counter(m.get("_chat_service") or "?" for m in all_msgs)
att_msgs = sum(1 for m in all_msgs if m.get("attachments"))
dates = sorted(m.get("created_at") for m in all_msgs if m.get("created_at"))
summary = {
    "exported_at": datetime.now(timezone.utc).isoformat(),
    "chats": len(by_chat),
    "messages": len(all_msgs),
    "sent_by_me": sent,
    "received": len(all_msgs) - sent,
    "services": dict(svc),
    "messages_with_attachments": att_msgs,
    "attachments_copied": files,
    "attachments_missing": missing,
    "attachments_bytes": bytes_total,
    "first_message": dates[0] if dates else None,
    "last_message": dates[-1] if dates else None,
}
with open(os.path.join(OUT, "summary.json"), "w") as f:
    json.dump(summary, f, indent=2)

print("\n" + json.dumps(summary, indent=2))
