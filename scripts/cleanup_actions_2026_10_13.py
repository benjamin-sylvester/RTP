"""One-time rewrite of the open action items into real tasks (Ben, 10/13/26: "feels pretty
useless"). Rules applied here and, from now on, by the daily review:
  - title: verb first, names the counterparty, under 60 characters
  - every open task has a due date; standing relationships get a check-in date, not 'ongoing'
  - one task per person or thread (duplicates merged into the survivor, the rest dropped)
  - status 'waiting' when the ball is in someone else's court
  - category: deal / capital / property / admin / network
The original title is kept at the top of details. Dry-run by default; --commit to persist.
  python scripts/cleanup_actions_2026_10_13.py [--sandbox] [--commit]
"""
import os
import sys

import psycopg
from _conn import connect, load_env

# id: (new_title, due, status, category, note)   status None = keep current
KEEP = {
    94:  ("Reply to Nick Gray on the Seacoast 8 decline", "2026-10-13", "open", "deal",
          "Options: name an RH number, look at 377-383 Manchester / 305-309 Cedar, wait for 371 Manchester / 396 Cedar, or the non-RH four-pack. Decide with Justin."),
    81:  ("Set Anthropic auto-reload on the org that holds the Railway key", "2026-10-15", "open", "admin",
          "Key verified valid 10/12, so it is not on the shut-off Individual Org. console.anthropic.com > Billing."),
    83:  ("Lafayette LOI: Porter chasing the seller", "2026-10-15", "waiting", "deal",
          "LOI v01 $650K with $400K seller note sent 10/8; acceptance date 10/12 passed. Porter 10/12: followed up with the seller again."),
    86:  ("EJG: current leases for 42-1 and 42-4", "2026-10-15", "waiting", "property",
          "Ryan 10/13: locating the current leases, has old renewals; 42-1 pays $1,750. Needed for the H&T OM."),
    92:  ("EJG: 44-2 lease for the 11/15 move-in", "2026-10-15", "waiting", "property",
          "Heather preparing the lease. Confirm showings stop once signed and funded; then set the H&T launch timing."),
    108: ("Confirm Fri 10/16 2pm NYC with Gedaliah Riesenberg", "2026-10-15", "open", "capital", "In person or call. Flight lands EWR 9:23am 10/16."),
    110: ("Lafayette: extend the LOI date in writing or wait for Porter", "2026-10-15", "open", "deal", None),
    112: ("Chase JDCU on floating-rate or interest-only for Summer St", "2026-10-15", "open", "property",
          "Asked Michelle Sapienza 10/8; fixed holding at 7.48 pct (FHLB + 2.25). No reply; Superhuman reminder fired 10/12."),
    114: ("EJG: 42-3 applicant cosigner and showing traffic", "2026-10-15", "waiting", "property", "Asked Heather 10/9; no reply."),
    104: ("Nick Gray: four-pack pricing and Manchester occupancy", "2026-10-16", "waiting", "deal", "Nudge if silent."),
    111: ("Kreiser: holdback review and the 2025 entity return", "2026-10-17", "waiting", "property", "Confirm which return he needs, then upload."),
    50:  ("Axel Ragnarsson: propose coffee in Boston", "2026-10-19", "open", "network",
          "Intro note sent 9/30 via Allen; connection accepted 10/1, no reply. Mention Russell Brott is an LP in one of his NH deals."),
    57:  ("Bakari Adams: confirm the 10/20 or 10/21 10am PT call", "2026-10-19", "waiting", "capital",
          "Abroad until the week of 10/19. Superhuman reminder fired 10/10, no answer."),
    51:  ("Ask Allen Meringolo for an intro to Eliot Bencuya", "2026-10-20", "open", "capital", "Reconvene Tier 1 LP; funded one of Allen's Airbnb deals."),
    90:  ("Decide on the Lucas Umbreit call (Tue 10/20, time not set)", "2026-10-20", "open", "network",
          "Oak 21 pitches deal-execution services, not capital. 20 minutes or skip."),
    109: ("Red Rock Securities discovery call, Tue 10/20 10am ET", "2026-10-20", "open", "admin", "Zoom from Doug Ruark. Securities counsel pitch."),
    105: ("Prep for the James Gallo call, Wed 10/21 12pm PT", "2026-10-21", "open", "capital",
          "H.I.G. Realty; the only Reconvene LP who named New England. Confirm H.I.G. vs personal investing."),
    113: ("Return the 42-3 security deposit to the former tenant", "2026-10-23", "open", "property",
          "With interest and itemized deductions (c.186 s15B, 30 days from the 9/25 key return). Forwarding address in Ryan's 10/12 email. RTP has held it since Sept 2023."),
    87:  ("NFP: other-carrier quotes for the 186 John St renewal", "2026-10-30", "waiting", "property",
          "VT Mutual options $9,230 ($10K deductible) or $8,794 ($25K). Annette marketing the renewal (10/9). Renewal 11/13; decide early November."),
    1:   ("Grossman: send the next deal with below-market in-place rents", "2026-11-14", "open", "capital",
          "'Bring me a deal.' Passed on Lakeside 9/8 (value-add too thin). Check-in date, not a deadline."),
    2:   ("Jason Weissman: follow up after the SF trip", "2026-10-20", "open", "capital",
          "10/5 NYC coffee did not happen (he was in Boston). 50/50 promote framework; made the Grossman intro."),
    5:   ("Doug McCrary: ReSeed operator model and pursuit notice", "2026-10-20", "waiting", "capital",
          "Emailed 10/12. Run a live NH deal through their scanner when it arrives. Nudge ~10/20."),
    6:   ("Greg Donahue: pipeline update and Baxter co-GP read", "2026-11-07", "open", "capital", "Lunch 10/2; thanked 10/5. Keep in the loop as deals progress."),
    7:   ("Collin van der Veen: coffee or a beer in Boston", "2026-10-24", "open", "capital", "Call 10/1. Advice: skip H&T auctions, work a hungry broker, bring a co-GP for the $3-5M raise."),
    8:   ("Mark Phillips (New Era): take him up on the intros", "2026-10-24", "open", "capital", "Passed on Lakeside 8/27 (development only); offered intros."),
    9:   ("Arcana / VMD: one more nudge or close", "2026-10-24", "waiting", "capital", "Met 8/24, followed up 8/27, no reply."),
    12:  ("Jake Smither: send the next deal or an update", "2026-11-01", "open", "capital", "Call 9/30; agreed 10/6 to stay in touch."),
    14:  ("Russell Brott: add to the LP list and send the overview deck", "2026-10-17", "open", "capital",
          "Said yes 10/12, russell@thebrottco.com. LP in an Axel Ragnarsson NH deal; family in Hampton Beach."),
    15:  ("Nat Piggee: reply and propose a call", "2026-10-17", "open", "capital", "Messaged 10/7 after the Reconvene dinner. LP on the next NH deal, plus legal help (TigerLaw)."),
    16:  ("Cash East: connect and add to the next NH deal list", "2026-10-24", "open", "capital", "Met on the Reconvene shuttle; Arkansas focus, interest in Maine, possible NH LP."),
    17:  ("Chirag Patel: connect; LP ask only once a deal is live", "2026-11-14", "open", "capital", "Low priority. chirag@pcginvestment.com."),
    22:  ("Will Rawlings: set the intro call (via Rutledge Long)", "2026-10-17", "waiting", "network",
          "Ben reached out 10/12. Providence Multifamily Partners, Boston. Nudge Rutledge if nothing by 10/16; thank him once set."),
    23:  ("Julian Scurci: reply; learn his firm and the Hamilton link", "2026-10-24", "open", "network", "Messaged 10/7. Cell 908-458-1097. Optional."),
    25:  ("Tucker Thompson: short reply to his survey email", "2026-10-17", "open", "network", "Optional; keep as a Richmond 5-50 unit peer."),
    28:  ("Marc Weiner: Boston family office intro", "2026-10-20", "waiting", "network", "Texted 10/12. Ask for the intro once he replies."),
    41:  None,  # merged into 90
    58:  ("Belay: follow up or close", "2026-10-17", "waiting", "capital", "Emailed 9/30 for 10/6 or 10/8; no reply."),
    60:  ("Aaron Greeno: message once the connection is accepted", "2026-10-24", "waiting", "capital", None),
    62:  ("Jack Foyle: send target returns and an example deal", "2026-10-24", "open", "capital", "Coffee 10/5 NYC. Also confirm a coffee date (invite accepted 10/4)."),
    63:  ("Add Allen Meringolo to the newsletter list", "2026-10-17", "open", "capital", "Asked to be on investor updates. First issue proposed 10/20."),
    64:  ("Oran Capital: offer a quarterly package", "2026-11-14", "open", "capital", "John Allen asked for monthly P&L and balance sheets (sent 8/12). Strong referral node."),
    91:  ("Reconvene feedback survey (optional)", "2026-10-17", "open", "network", "Airtable link in Moses Kagan's 10/10 email."),
    99:  ("LinkedIn: connect with the Reconvene peers", "2026-10-17", "open", "network",
          "Tanner Webster, Ben Karlin, Brian Jenkins, Mike Conger, Marilyn Moedinger, Rachael Jones, Alexis Morgan, Elliott Fisher, Erik Aukland. One-line note each, no ask."),
    101: ("LinkedIn: accept Robbie Hendricks and Tiernan Laue", "2026-10-17", "open", "network", "Midwest MF operator (3,750+ units) and an MHP owner. The other 20 invitations are noise."),
    102: ("Confirm whether you met Edgar De La Torre and Patrick Venne", "2026-10-17", "open", "network", "Both connected 10/12; neither is in your Reconvene debrief."),
    103: ("Ian Golightly: two-line reply", "2026-10-24", "open", "network", "Ex-Lasso Indy contact; congratulated you on going solo 8/23. Optional."),
}
# merged or noise: dropped with a reason (the survivor carries the task)
DROP = {
    3: "merged into #57", 4: "no action (declined 9/30)", 19: "merged into #15", 20: "merged into #99", 21: "merged into #5",
    24: "merged into #14", 26: "merged into #99", 27: "merged into #16", 29: "merged into #99", 30: "merged into #99",
    31: "merged into #99", 32: "merged into #17", 33: "merged into #99", 34: "merged into #99", 35: "merged into #99",
    36: "merged into #99", 37: "no action", 38: "merged into #102", 39: "merged into #50", 42: "merged into #22",
    43: "merged into #22", 44: "merged into #28", 45: "merged into #99", 46: "no action now", 47: "merged into #102",
    48: "merged into #103", 55: "merged into #2", 56: "merged into #1", 59: "merged row", 68: "merged into #8",
    71: "merged into #7", 72: "merged into #62", 73: "merged into #6", 74: "merged into #22", 77: "merged into #12",
    79: "merged into #15", 80: "merged into #23", 82: "done: call booked 10/21", 84: "merged into #14", 85: "merged into #25",
    88: "merged into #112", 93: "merged into #114", 95: "merged into #113", 96: "merged into #5", 97: "merged into #28",
    98: "merged into #16", 100: "merged into #17", 41: "merged into #90",
}


def conn_for(argv):
    if "--sandbox" in argv:
        load_env()
        return psycopg.connect(os.environ["SANDBOX_DATABASE_URL"], autocommit=False)
    return connect(autocommit=False)


def main():
    c = conn_for(sys.argv)
    rewritten = dropped = missing = 0
    for aid, spec in KEEP.items():
        if spec is None:
            continue
        title, due, status, cat, note = spec
        row = c.execute("SELECT title, details FROM action_items WHERE id=%s", (aid,)).fetchone()
        if not row:
            missing += 1; print("  missing", aid); continue
        old_title, old_details = row
        details = (note + "\n\n" if note else "") + "Was: " + old_title + ("\n" + old_details if old_details else "")
        c.execute("UPDATE action_items SET title=%s, due_on=%s, status=COALESCE(%s, status), category=%s, details=%s WHERE id=%s",
                  (title, due, status, cat, details[:2000], aid))
        rewritten += 1
    for aid, why in DROP.items():
        n = c.execute("UPDATE action_items SET status=CASE WHEN %s LIKE 'done%%' THEN 'done' ELSE 'dropped' END, "
                      "details=COALESCE(details,'')||%s, completed_at=now() WHERE id=%s AND status IN ('open','waiting')",
                      (why, f"\n[10/13 cleanup: {why}]", aid)).rowcount
        dropped += n
    left = c.execute("SELECT count(*) FROM action_items WHERE status IN ('open','waiting') AND (due_on IS NULL OR category IS NULL OR length(title) > 70)").fetchone()[0]
    print(f"rewritten {rewritten}, dropped/done {dropped}, missing {missing}; open items still undated/uncategorized/long: {left}")
    for r in c.execute("SELECT status, category, count(*) FROM action_items WHERE status IN ('open','waiting') GROUP BY 1,2 ORDER BY 1,2"):
        print("  ", r)
    if "--commit" in sys.argv:
        c.commit(); print("COMMITTED")
    else:
        c.rollback(); print("DRY-RUN, rolled back")


if __name__ == "__main__":
    main()
