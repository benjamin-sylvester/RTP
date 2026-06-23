"""Phase 2 step 5 — CALIBRATION. Compare the human buy-box calls already in the data
(seeded Deal Database 'Buy Box Fit' + triage 'Buy Box': YES/MAYBE/SIZE/No) against the
computed score/tier, so Ben can sanity-check before we trust the scoring. The score is a
triage sort, not a verdict — we want hand-YES to rank visibly above hand-No."""
import sys
import pathlib
from statistics import mean

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect

RANK = {"YES": 0, "MAYBE": 1, "SIZE": 2, "No": 3}


def usd(c):
    return f"${c/100:,.0f}" if c is not None else "-"


def main():
    with connect() as conn:
        rows = conn.execute(
            """SELECT l.address, l.city, l.state, l.units, l.asking_price,
                      l.raw_data->>'buy_box_fit_sheet' AS human,
                      au.score, au.tier, au.score_confidence, au.meets_buy_box
               FROM listings l JOIN auto_underwriting au ON au.listing_id = l.id
               WHERE l.raw_data->>'buy_box_fit_sheet' IS NOT NULL
               ORDER BY au.score DESC NULLS LAST""").fetchall()

    print(f"CALIBRATION — {len(rows)} hand-evaluated deals: your call vs computed\n")
    print(f"{'human':<6}{'score':>5} {'tier':<9}{'conf':<7}{'mbb':<6}{'un':>3}{'ask':>12}  loc")
    print("-" * 92)
    buckets = {}
    for addr, city, state, units, ask, human, score, tier, conf, mbb in rows:
        buckets.setdefault(human, []).append(score)
        loc = f"{(addr or '?')[:22]}, {city} {state}"
        print(f"{human:<6}{str(score if score is not None else '-'):>5} {str(tier):<9}"
              f"{str(conf or '-'):<7}{str(mbb):<6}{str(units or '-'):>3}{usd(ask):>12}  {loc}")

    print("\nSeparation — computed score by your hand call (want YES >> No):")
    print(f"{'call':<7}{'n':>3}{'mean':>7}{'min':>6}{'max':>6}")
    print("-" * 30)
    for call in sorted(buckets, key=lambda k: RANK.get(k, 9)):
        s = [x for x in buckets[call] if x is not None]
        if s:
            print(f"{call:<7}{len(s):>3}{mean(s):>7.0f}{min(s):>6}{max(s):>6}")

    # quick sanity check
    yes = [x for x in buckets.get("YES", []) if x is not None]
    no = [x for x in buckets.get("No", []) if x is not None]
    if yes and no:
        verdict = "PASS" if mean(yes) > mean(no) else "REVIEW"
        print(f"\nYES mean {mean(yes):.0f} vs No mean {mean(no):.0f}  ->  {verdict}")


if __name__ == "__main__":
    main()
