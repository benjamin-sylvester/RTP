# Daily Briefing Kickoff — push deals to Ben's inbox

The piece that turns the database from something you query into something that works for you.
A once-a-day email: what's new, what changed, what needs your eyes. Lead with tier + AI summary,
NOT the raw score (per the calibration decisions).

## Where it runs
App-side, triggered by the scheduler (a daily job, separate from the 15-min ingestion). It sends
via the Gmail API to `DISPATCH_EMAIL` (ben@rtprei.com). It does NOT run from Cowork (Cowork ->
Railway reachability is unconfirmed).

## ⚠️ Scope gotcha to handle first
The current Gmail OAuth token has `gmail.modify`, which does NOT permit sending. The briefing
needs to send mail, so add the `gmail.send` scope and re-consent the OAuth token. Confirm send
works before scheduling.

## What's in the email
1. **Header line:** date + counts — "3 new leads · 2 price cuts · 1 needs review."
2. **New leads** (status `lead`, first seen since the last briefing), ordered by tier ->
   confidence -> score. Per deal: address, city, units, ask, $/unit, **tier**, the one-line **AI
   summary**, confidence, and a link (Gmail thread / Drive folder). Score shown small, not the
   headline.
3. **Changes since last briefing** (from `listing_history`): price cuts (flag prominently — the
   motivated-seller signal, e.g. "771 Rock St: $699.9k -> $649.9k"), status changes, and notable
   enrichments.
4. **Needs review** (status `needs_review`): count + list — deals the system couldn't auto-judge
   that need your call.
5. **Quiet day:** if nothing new or changed, send a single line ("No new deals today") or skip —
   your preference.

## Don't repeat deals
Track a `last_briefed_at` timestamp (a tiny `system_meta` key/value table, or a briefing_log row).
Each run covers deals where `date_ingested` or `listing_history.changed_at` > last_briefed_at,
then updates the timestamp on success.

## Build steps
1. Add `gmail.send` scope, re-consent, verify a test send.
2. `briefing.py`: query new leads + changes + needs_review since last_briefed_at; render a clean
   HTML email (tier + summary first, price cuts flagged); send via Gmail API; update last_briefed_at.
3. Schedule it daily (suggest 6:30am) alongside the ingestion job.

## Verification gate (before it's live)
- Dry-run: render the briefing to a file/console (no send) so Ben sees content + format.
- Then send ONE test to ben@rtprei.com and confirm it looks right in the inbox.
- Only then schedule the daily job.

## Config
- `DISPATCH_EMAIL=ben@rtprei.com` (already in .env.example)
- Briefing time + quiet-day behavior: put in .env or buy_box.yaml-adjacent config, not hardcoded.

## Paste-ready prompt
> Read BRIEFING_KICKOFF.md and build the daily briefing. First add the gmail.send scope and
> verify a test send (current token is gmail.modify, which can't send). Then build briefing.py:
> new leads + listing_history changes + needs_review since a tracked last_briefed_at, rendered as
> an HTML email led by tier + AI summary (price cuts flagged prominently, score de-emphasized),
> sent to DISPATCH_EMAIL. Track last_briefed_at so deals never repeat. STOP at a dry-run rendered
> to a file for me to review, then one test send to me, before scheduling the daily 6:30am job.
