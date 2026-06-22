# PROMPTS.md — RTP prompt library

Reusable prompts, organized by where they run. App prompts go to the Claude API inside the
code. Cowork prompts you paste into a Cowork session. Keep this file as the canonical copy;
the skills reference it.

---
## APP (Claude API, inside ingestion/underwriting code)

### Listing extraction (free-form email or PDF OM)
```
Extract listing data from this broker email and any attachment. Return JSON with fields:
address, city, state, zip, units, asking_price, year_built, building_sf, lot_sf,
unit_mix[] (type, count, avg_rent), gross_revenue, total_expenses, noi, vacancy_rate,
broker_name, broker_email, listing_date, external_id (MLS number if present).
Set any unavailable field to null. Money as plain integers in dollars.
For PDF attachments, content is provided as images. Return only valid JSON.
```

### Rent roll -> rent comps
```
Parse this rent roll. For each occupied unit, capture: unit_type (Studio/1BR/2BR/3BR),
beds, baths, sqft, current monthly rent. Then aggregate to average rent and average sqft
per unit_type. Return JSON: {property_address, market, unit_types: [{unit_type, beds,
baths, avg_sqft, avg_rent, count}]}. Money as integers in dollars.
```

### Deal summary (for auto_underwriting.summary)
```
Write a 2-3 sentence summary of this deal for an experienced multifamily investor.
Highlight the single most notable positive and the single most notable negative.
Be direct and specific. No filler.
Data: {structured_deal_json}
```

---
## COWORK (paste into a session)

### Daily triage (interim, before the app is live)
```
Scan my Gmail "Deal Flow" label for threads newer than [LAST_SCAN_DATE]. For each deal,
extract address, city, state, units, unit mix, asking price, $/unit, in-place rent, cap,
year built, sqft, broker, MLS#. Flag each against the buy box in memory. Deals that fit or
are borderline: summarize and list as REVIEW candidates first, sorted by fit. Everything
else: log as comp-only. Then update the deal database.
```

### Comp pull (Sale Comp DB)
```
Query the deal database: all listings in [MARKET] within the last [N] months. Return
address, units, list price, $/unit, cap, days on market. Give me the median $/unit and
median cap at the bottom.
```

### Radius comp pull (once Postgres is live)
```
Pull all closed listings within [X] miles of [ADDRESS], [UNIT_MIN]-[UNIT_MAX] units, sold
in the last [N] months. Sort by distance. Include $/unit and cap. Then summarize the range.
```

### Build a BOE
```
Build a BOE for [DEAL] using the BOE template. Pull market rents by unit type for [MARKET]
from the rent comp database. Populate inputs, run the annual DCF, score it 1/2/3. Save to
the BOE Outputs Drive folder as [YYYY-MM-DD]_[City]_[Address]_BOE.xlsx, update the deal to
"underwriting" status with the boe_url, and give me a broker question list for anything you
assumed. Formatting: Times New Roman 11, blue headers, blue input cells on yellow, green
cross-sheet formulas.
```

### Broker questions
```
For [DEAL], compare what the BOE needs against what we have. Generate a tailored question
list for the broker covering only the missing or assumed inputs. Keep it short and direct.
```

### Weekly Zillow rent scan (scheduled task)
```
For each target market in the buy box (Manchester, Nashua, Derry, Londonderry, Salem,
Dover, Rochester, Somersworth, Farmington, Milton), pull current Zillow rental listings.
Capture beds, baths, sqft, rent, address. Write to the rent comp database tagged by market
and unit type, source zillow, dated today. Flag any market where median rent moved >3% vs
last week. Email me the summary.
```

### Morning briefing (scheduled task)
```
Show me deals added to the pipeline in the last 24-48 hours, scored and summarized, highest
score first. One line each: address, city, units, ask, $/unit, score, the one-line summary.
Email it to me as the morning briefing.
```

### LOI (uses the rtp-loi skill)
```
Draft an LOI for [DEAL] at [PRICE]. [financing variant: loan assumption / seller financing
/ cash]. [direct-to-seller or broker-mediated]. Use the RTP LOI template and my signature.
```
