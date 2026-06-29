"""Engagement auto-promotion — runs every ingest cycle.

If Ben has REPLIED in a deal's Gmail thread, that deal is a pipeline deal regardless of the
buy box: engagement overrides routing. Each cycle we find the threads Ben SENT mail in (one
cheap `in:sent` list call), match them to listings by raw_email_id, AI-infer the stage from
HIS OWN words, and promote the deal:

    asking to tour / requesting P&L / rent roll / T-12  -> underwriting
    offer / LOI / "finalize an offer" / price+terms     -> loi_sent
    any other reply                                     -> lead

Rules:
- Promotion only ever moves a deal FORWARD. We never downgrade a further-along deal and never
  re-log a deal already at/above the inferred stage (so re-running each cycle is idempotent).
- Sticky terminal states (passed / lost / under_contract) are NEVER flipped — they're flagged
  once (engaged-but-<status>) so the contradiction surfaces, and left for Ben to resolve.
- Package members are skipped: a package's status is governed at the package level.
- Every change is logged to listing_history (via freshness.set_status).
"""
import os

from ingest import gmail_client as gc, freshness
from ingest.parsers import _client
from ingest.reply_commands import _QUOTE

# the deal lifecycle as a forward-only ladder; engagement can lift a deal up it, never down.
RANK = {"comp_only": 0, "needs_review": 0, "lead": 1,
        "underwriting": 2, "loi_sent": 3, "under_contract": 4}
TERMINAL = ("passed", "lost", "under_contract")     # sticky — flag, never flip
STAGES = ("lead", "underwriting", "loi_sent")        # stages engagement can infer/set
TOP_TARGET = RANK["loi_sent"]                        # highest stage engagement promotes to

AFTER_FLOOR = os.environ.get("INGEST_AFTER_FLOOR", "2026/03/24")

SYSTEM = ("You classify a multifamily investor's OWN outbound emails to a broker into one deal "
          "stage. Judge only what the buyer's words commit him to. A reply is NOT automatically "
          "interest — he may be declining.")
PROMPT = """Below are the messages the BUYER (a multifamily investor) sent in one deal thread.
Output the FURTHEST stage his words imply, as exactly one lowercase label:

- loi_sent: he has made or is submitting an offer / LOI, named a price or terms, or says he
  wants to "finalize an offer", "put in an offer", "submit an LOI", or is negotiating price.
- underwriting: he is actively diligencing THIS deal — asking to tour/see the property, or
  requesting specific financials (P&L, T-12, rent roll, operating statements, leases). A vague
  "send me more info/details" is NOT underwriting.
- lead: genuine interest or active engagement short of a tour/financials request or an offer
  ("looks interesting", intro, scheduling, asking general questions, requesting basic info).
- pass: he is DECLINING or shows no buying intent — says it's too small/rural/expensive/not a
  fit, already owns enough, or is otherwise not pursuing it.

Output ONLY the one label word.

BUYER'S MESSAGES:
\"\"\"
{src}
\"\"\""""


def _sent_thread_ids(svc, after=AFTER_FLOOR):
    """Thread ids Ben has SENT mail in (cheap: list only, no bodies)."""
    out, page = set(), None
    while True:
        resp = svc.users().messages().list(
            userId="me", q=f"in:sent after:{after}", pageToken=page, maxResults=500).execute()
        for m in resp.get("messages", []):
            out.add(m["threadId"])
        page = resp.get("nextPageToken")
        if not page:
            break
    return out


def _strip_quote(text):
    """Keep only the message Ben actually wrote, dropping the quoted original below it."""
    m = _QUOTE.search(text or "")
    return (text[:m.start()] if m else (text or "")).strip()


def bens_sent_text(svc, thread_id, max_chars=4000):
    """Concatenated bodies of the messages BEN SENT in this thread (SENT label), quotes
    stripped so the classifier sees his words, not the broker's."""
    try:
        th = svc.users().threads().get(userId="me", id=thread_id, format="full").execute()
    except Exception:
        return ""
    parts = []
    for msg in th.get("messages", []):
        if "SENT" not in msg.get("labelIds", []):
            continue
        leaves = []
        gc._walk_parts(msg.get("payload", {}), leaves)
        plain = [gc._decode(p["body"]["data"]) for p in leaves
                 if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data")]
        if plain:
            body = "\n".join(plain)
        else:  # HTML-only: strip tags
            import re
            body = " ".join(re.sub(r"<[^>]+>", " ", gc._decode(p["body"]["data"]))
                            for p in leaves
                            if p.get("mimeType") == "text/html" and p.get("body", {}).get("data"))
        body = _strip_quote(body)
        if body:
            parts.append(body)
    return "\n---\n".join(parts)[:max_chars]


def infer_stage(text, model=None):
    """Classify Ben's sent text into a stage label, or None to NOT promote (nothing to read,
    or he's declining the deal — a reply is not automatically interest)."""
    if not (text or "").strip():
        return None
    model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    resp = _client().messages.create(
        model=model, max_tokens=8, system=SYSTEM,
        messages=[{"role": "user", "content": PROMPT.format(src=text)}])
    out = resp.content[0].text.strip().lower()
    if "pass" in out:
        return None  # declining -> leave the deal where it is (Ben can mark passed himself)
    for s in ("loi_sent", "underwriting", "lead"):   # most-specific first
        if s in out:
            return s
    return "lead"  # engaged but unclear -> at least a lead


def _flag_once(conn, lid, status, log):
    """Record a one-time 'engaged but sticky terminal' flag; don't re-flag each cycle."""
    seen = conn.execute(
        "SELECT 1 FROM listing_history WHERE listing_id=%s AND field='engagement_flag' LIMIT 1",
        (lid,)).fetchone()
    if seen:
        return False
    conn.execute(
        "INSERT INTO listing_history (listing_id, field, old_value, new_value) "
        "VALUES (%s, 'engagement_flag', %s, %s)", (lid, status, f"engaged-but-{status}"))
    log(f"[engage] FLAG #{lid}: Ben engaged but status is {status} (sticky — not flipped)")
    return True


def run(conn, svc, after=AFTER_FLOOR, log=print):
    """Promote engaged deals up the ladder. Commits its own work (call only when committing)."""
    threads = _sent_thread_ids(svc, after)
    s = {"sent_threads": len(threads), "checked": 0, "promoted": 0, "flagged": 0}
    if not threads:
        return s
    rows = conn.execute(
        "SELECT id, address, status, raw_email_id FROM listings "
        "WHERE raw_email_id = ANY(%s) AND package_id IS NULL", (list(threads),)).fetchall()
    for lid, addr, status, thread in rows:
        s["checked"] += 1
        if status in TERMINAL:
            if _flag_once(conn, lid, status, log):
                s["flagged"] += 1
            continue
        if RANK.get(status, 0) >= TOP_TARGET:
            continue  # already at the top stage engagement can set; nothing to do, no AI call
        stage = infer_stage(bens_sent_text(svc, thread))
        if not stage or RANK[stage] <= RANK.get(status, 0):
            continue  # no read, or would not move the deal forward
        freshness.set_status(conn, "listing", lid, stage,
                             reason=f"engaged (replied in thread) -> {stage}")
        log(f"[engage] #{lid} {addr}: {status} -> {stage}")
        s["promoted"] += 1
    conn.commit()
    if s["promoted"] or s["flagged"]:
        log(f"[engage] {s}")
    return s
