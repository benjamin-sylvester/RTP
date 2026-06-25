# Deal Status Model

The deal lifecycle, what each status means, and who (you vs. the system) controls it.
Kept deliberately small.

## Statuses

| Status | Label | Meaning | Set by |
|---|---|---|---|
| `comp_only` | Comp only | Logged as a market comp, never pursued (out of box, or not worth a look). The bulk of the DB — the sale-comp store. | System (routing) |
| `lead` | Lead created | Worth reviewing; in the active pipeline. | System on arrival; or manual promote from comp |
| `underwriting` | Underwriting | Actively running the numbers / BOE. | You |
| `loi_sent` | LOI sent | Offer/LOI submitted; officially bidding. | You |
| `under_contract` | Under contract | Won it; under PSA. | You |
| `lost` | Lost | Pursued (reached LOI/bid) but didn't win — other buyer or terms fell apart. | You |
| `passed` | Passed | Reviewed and chose not to pursue. Declined. | You |

`lost` vs `passed` is the key distinction: **lost = competed and didn't win; passed = chose not to compete.**

## Who controls what (sticky rule)
- The system auto-manages ONLY `comp_only <-> lead` (buy-box routing on ingestion).
- `underwriting`, `loi_sent`, `under_contract`, `lost`, `passed` are MANUAL and STICKY.
  Ingestion/enrichment refreshes data + `last_seen_at` on a re-sighting but NEVER changes these.
  (A deal you passed/lost can't be resurrected by a new MLS blast.)

## Activeness (no "stale" status)
- Active pipeline = status in (`lead`, `underwriting`, `loi_sent`, `under_contract`)
  AND `last_seen_at` within `pipeline.active_lead_days` (45).
- A lead that goes quiet stays `lead` but drops out of the default active view by date; review and
  mark `passed`/`lost` when you decide. The briefing notes "leads gone quiet (N)" by date — no
  status change. (Replaces the old auto lead->stale sweep.)

## Reporting this enables
- Deals I bid on (quarter/year): status in (`loi_sent`, `under_contract`, `lost`).
- Win rate: `under_contract / (loi_sent + under_contract + lost)`.
- Pass-through funnel: lead -> underwriting -> loi_sent -> under_contract, with lost/passed exits.

## Dashboard actions (slice 5, revised)
Buttons / status dropdown on the detail page (and inline in the table), working for listings AND
packages, each logged to `listing_history`:
- -> Underwriting, -> LOI sent, -> Under contract, -> Lost, -> Passed, and Reactivate (-> lead).
- Confirm on Lost and Passed.

## Migration (008)
- Existing `dead` -> `passed`. Existing `stale` -> `lead`.
- Remove the lead->stale sweep; active views filter by `last_seen_at` instead. Keep
  `active_lead_days` as the filter threshold.
- Update the schema status comment and any status enums/validators to this set.

## Deferred
- `closed` / `owned` (post-close, hands off to AUM tracking) — add when the first deal closes.
