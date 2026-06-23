"""Reply-to-kill — prune the pipeline from your phone.
Reply to a briefing email with e.g. "kill 24, 25" and the ingestion job sets those
deals to 'dead'. Only the REPLY text (above the quoted original) is parsed, so example
ids in the quoted briefing are never killed. Each processed reply is labeled so it
runs once."""
import os
import re

from ingest import gmail_client as gc, freshness
from ingest.parsers import html_to_text

CMD_LABEL = "RTP/CmdProcessed"
# markers where the quoted original begins (everything below is ignored)
_QUOTE = re.compile(r"(^On .*wrote:|^\s*>|^-{3,}\s*Original Message|^From:\s)", re.M)
_KILL = re.compile(r"\bkill\b[:\s]+([0-9][0-9,\s]*)", re.I)


def parse_kill_ids(text):
    """Listing ids to kill from the reply's top text only (before the quoted original)."""
    m = _QUOTE.search(text or "")
    top = text[:m.start()] if m else (text or "")
    ids = []
    for chunk in _KILL.findall(top):
        ids += [int(x) for x in re.findall(r"\d+", chunk)]
    return list(dict.fromkeys(ids))  # dedupe, keep order


def process_replies(svc, conn, dispatch_email=None, log=print):
    """Find unprocessed briefing replies, kill the listed deals, label them processed."""
    dispatch_email = dispatch_email or os.environ.get("DISPATCH_EMAIL", "")
    label_id = gc.ensure_label(svc, CMD_LABEL)
    q = (f'from:{dispatch_email} subject:(RTP Deal Briefing) '
         f'-label:"{CMD_LABEL}"')
    msgs = svc.users().messages().list(userId="me", q=q).execute().get("messages", [])
    killed = []
    for mm in msgs:
        m = gc.get_message(svc, mm["id"])
        text = m["plain"].strip() or html_to_text(m["html"])
        ids = parse_kill_ids(text)
        for did in ids:
            row = freshness.kill(conn, did, reason="reply-to-kill")
            if row:
                killed.append(did)
                log(f"[reply-cmd] killed #{did} {row[1]}, {row[2]}")
        conn.commit()
        svc.users().messages().modify(
            userId="me", id=mm["id"], body={"addLabelIds": [label_id]}).execute()
    if msgs:
        log(f"[reply-cmd] processed {len(msgs)} reply(ies), killed {killed}")
    return killed
