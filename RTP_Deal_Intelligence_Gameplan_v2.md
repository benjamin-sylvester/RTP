# RTP Deal Intelligence: Operating Architecture v2

**Supersedes:** "RTP Deal Intelligence System: Technical Architecture" (Feb 2026)
**Date:** June 22, 2026
**Owner:** Ben Sylvester, Rising Tide Partners

---

## 1. What changed since the Feb doc

The Feb 2026 blueprint described one thing: a custom app you build and host. That app is still the right spine. What's new is that you now operate day to day **inside Claude**, with live connectors to Gmail, Google Drive, Slack, and Calendar. So the system is now **three layers, not one**:

1. **Data spine** (the asset): Postgres + PostGIS on Railway. The proprietary, queryable database.
2. **Engineering layer:** Claude Code. Builds and maintains the codebase (ingestion, parser, auto underwriter, API, dashboard, schema). Version controlled in GitHub.
3. **Operating layer:** Cowork. Your daily driver. Reads and writes the same database, generates documents, drafts communications, and does the per deal judgment work.

The single design idea that makes "tools talk to each other": **one database, two interfaces.** A Postgres MCP connector is wired into *both* Claude Code and Cowork. Documents live in Drive and are linked from database rows. Gmail feeds ingestion. Slack carries the notifications. Nothing is siloed.

---

## 2. The asset thesis

You said it yourself: the enterprise value is the real estate *and* the data. Every broker blast, MLS export, and rent roll that hits your inbox is public or semi public information that almost no small balance operator captures, structures, or keeps. Organized into one geocoded, queryable store that grows every day, it becomes a durable advantage: you can answer "what is the right price for a 12 unit in Manchester" from your own data, instantly, while competitors guess. The whole architecture below is built to make capture automatic and loss impossible.

---

## 3. Claude Code vs Cowork: the decision rule

| Use **Claude Code** when the work is... | Use **Cowork** when the work is... |
|---|---|
| Code that lives in git (ingestion, parser, API, dashboard) | A document or deliverable (BOE, LOI, memo, briefing) |
| Schema changes and migrations | A conversation with your data ("show me comps within 3 miles") |
| Anything that runs server side 24/7 | Per deal judgment (review, scoring nuance, broker questions) |
| Debugging, tests, refactors | Communications (broker emails, LP updates, Slack posts) |
| Building the scheduled ingestion job | Recurring human facing tasks (morning briefing, weekly scan) |

**Shared by both:** the Postgres MCP, the Drive connector, the Gmail connector. That overlap is deliberate. It is how a deal parsed by the server side job becomes a BOE you generate in Cowork ten minutes later, both pointing at the same row.

Rough split of your time: Claude Code is a few intense build weeks then occasional maintenance. Cowork is every day, forever.

---

## 4. The data spine

PostgreSQL 16 + PostGIS on Railway, exactly as the Feb doc specified. The tables (full DDL is in the repo `db/schema.sql`):

- **`listings`** — master table. One row per unique property. *This single table is both your Sale Comp Database and your Pipeline.* A `status` field separates them (see below).
- **`listing_financials`** — NOI, cap, expenses, etc. per listing.
- **`unit_mix`** — unit type breakdown per listing.
- **`auto_underwriting`** — system generated quick screen (buy box pass/fail, implied caps, DSCR, score, AI summary).
- **`rent_comps`** *(new)* — market rent observations by market and unit type, from rent rolls and the weekly Zillow scan. Feeds BOE market rent assumptions.
- **`listing_history`** — price/status changes over time (for trend analysis and motivated seller signals).
- **`broker_format_config`** — per broker column mappings for MLS exports.

**Key design decision: Sale Comp DB and Pipeline are the same table.**

- Every listing ever ingested lands in `listings`. That *is* the Sale Comp DB. Comps become free.
- A deal "worth reviewing" simply gets `status` set to `lead` → `underwriting` → `under_contract` → `closed`. That subset *is* the Pipeline.
- A deal not worth reviewing stays `status = comp_only`. It never clutters the pipeline but is always there for comp pulls.

This is the cleanest answer to your "not every deal belongs in the pipeline, but I still want to keep the rest" requirement. No second database, no sync problem.

**Drive pointer columns** on `listings`: `drive_folder_id`, `boe_url`, `om_url`. The database holds structured data; Drive holds the documents; the row links them. That cross reference is the backbone of interoperability.

---

## 5. How the pieces connect

```
                    ┌──────────────────────────────────────┐
   Gmail  ─────────▶│  Ingestion job (server cron, 15 min)  │
 (Deal Flow label)  │  parse → geocode → dedup → insert     │
                    └───────────────┬──────────────────────┘
                                    ▼
                        ┌───────────────────────┐
                        │   Postgres + PostGIS   │◀── the asset
                        │   (Railway)            │
                        └─────┬───────────┬──────┘
                              │           │
                  Postgres MCP│           │Postgres MCP
                              ▼           ▼
                     ┌────────────┐  ┌────────────┐
                     │ Claude Code│  │   Cowork   │
                     │ (builds)   │  │ (operates) │
                     └────────────┘  └─────┬──────┘
                                           │
                 ┌─────────────┬───────────┼───────────┬─────────────┐
                 ▼             ▼           ▼            ▼             ▼
            Google Drive    Gmail        Slack      Calendar     xlsx/docx
          (OM, RR, BOE,   (drafts to   (briefings, (lease exp,  (BOE, LOI
           LOI by url)     brokers)     alerts)      deadlines)   outputs)
```

The thing to internalize: **the database is the hub, not Cowork and not the app.** Both interfaces are spokes. Add a third interface later (a phone app, a partner's login) and it just plugs into the same hub.

---

## 6. Folder and workspace structure

You actually have **four** structures to keep straight. They serve different masters; do not collapse them.

### A. GitHub repo (code) — `rtp-deal-intel`
The starter scaffold is in the package delivered with this doc. Layout:
```
rtp-deal-intel/
├── CLAUDE.md                  # instructions for the Claude Code agent
├── BUILD_PLAN.md              # sequenced build plan
├── README.md
├── .env.example
├── db/
│   └── schema.sql             # full DDL incl. rent_comps + drive pointers
├── config/
│   ├── buy_box.yaml           # single source of truth for buy box
│   └── broker_format_config.yaml  # seeded with your 5 known brokers
├── ingestion/                 # Gmail → parse → geocode → dedup → insert
├── underwriting/              # buy box filter + quick UW + scoring
├── api/                       # FastAPI REST endpoints
└── dashboard/                 # React + Recharts + Mapbox
```

### B. Google Drive (documents) — keep your existing tree
Your structure is already good and stays as is. The system writes outputs into it:
- BOE outputs → `2.0 Acquisitions / 0.0 Pipeline / BOE Outputs` (`18UzfmxWuywK2dTmPrmtSVwp3pXpQmWHe`)
- Active deal diligence → `2.0 Acquisitions / 2.0 Underwriting / [Deal]` (from the Folder Template)
- This gameplan and all specs → `5.0 Organizational / 3.0 Deal Intelligence`
- The Sheets versions of the Deal Database and Pipeline become **read only legacy** once Postgres is live. Keep them for reference, stop writing to them.

### C. Cowork spaces (operations)
- **One persistent RTP Ops space** (your current one): daily pipeline review, comp queries, briefings, broker comms, asset management.
- **One dedicated space per hot deal** once you bid or push: this is your "break it into its own project" instinct, and it is correct. Upload the OM, rent roll, T 12, inspection reports there; fine tune the model in isolation; keep the noise out of the main space. When the deal dies or closes, archive the space.

### D. Skills + memory
- Your 6 existing skills (migrated from clawdbot) are the operating logic. They get adapted to write to Postgres instead of Sheets (see Section 7).
- Memory holds the durable facts: buy box, Drive IDs, broker list, formatting standards. Already in place; updated this session.

---

## 7. Workstream playbooks

Each playbook lists the trigger, the tools, the skill, a ready to paste prompt, and the output.

### 7.1 Pipeline + comp capture from email  *(PRIORITY 1)*

**Trigger:** new email in the Gmail `Deal Flow` label (auto applied by your existing filters from the 5 known senders).

**Flow:**
1. Ingestion job reads new `Deal Flow` threads and attachments.
2. Parser extracts structured fields (address, units, price, rents, broker, MLS#).
3. Geocode + dedup against existing `listings`.
4. Run buy box filter from `config/buy_box.yaml`.
5. **Route:** buy box fit or borderline → insert with `status = lead` (enters Pipeline). Everything else → insert with `status = comp_only` (enters Sale Comp DB only).
6. Post new fits to Slack.

**Tools:** Gmail MCP (read), Postgres MCP (write), Census/Google geocoder, Claude API (server side parse), Slack MCP (dispatch).
**Skills:** `morning-briefing` (scan + classify), `deal-extraction` (parse), `deal-pipeline` (route + log).

**Interim mode (before the app is built):** you can run this in Cowork today off the Gmail connector, writing to the existing Deal Database, no server required. Prompt:
> "Scan my Gmail `Deal Flow` label for threads newer than [last scan date]. For each, extract address, city, state, units, unit mix, asking price, $/unit, in place rent, cap, year built, sqft, broker, and MLS#. Flag each against the buy box in memory (Southern NH, 4 to 34 units at the package level, Class B/C, value add). Deals that fit or are borderline: summarize and list as review candidates. Everything else: log as comp only. Give me the review candidates first, sorted by fit."

**Output:** updated pipeline, comps logged, Slack briefing of new fits.

### 7.2 Underwriting / BOE

**Trigger:** you mark a pipeline deal "underwrite it," or a deal lands as a strong fit.

**Flow:**
1. Copy the BOE template (`RTP_BOE_Template_v04.xlsx` for the quick BOE; the 10 year template for serious pushes).
2. Pull rent comps for that market and unit mix from `rent_comps`.
3. Populate inputs, run the simple annual DCF, score 1/2/3.
4. Save to Drive `BOE Outputs` as `[YYYY-MM-DD]_[City]_[Address]_BOE.xlsx`.
5. Update the listing: `status = underwriting`, write `boe_url`.
6. Generate the broker question list for missing inputs.

**Tools:** Drive MCP (template + save), Postgres MCP (read comps, update row), `xlsx` skill (mechanics).
**Skills:** `deal-boe` (has 13 documented lessons learned, reuse them), `deal-comps` (comp pull), `broker-questions` (gap list).
**Formatting:** Times New Roman 11, blue headers `#0000FF`, blue input cells on yellow background, green cross sheet formulas.

**Prompt:**
> "Build a BOE for [deal] using the BOE template. Pull 1BR/2BR/3BR market rents for [market] from the rent comp database. Populate inputs, run the annual DCF, and score it 1/2/3. Save to the BOE Outputs folder with the standard name, update the deal to `underwriting` status, and give me a broker question list for anything you had to assume."

**Hot deal escalation:** when you bid or push, spin up a dedicated Cowork space + a Drive diligence folder from the Folder Template. Fine tune the 10 year model there.

### 7.3 Sale Comp Database

Not a separate build. It *is* `listings` (every row, regardless of status). Query it conversationally in Cowork via the Postgres MCP.
> "Show me every listing logged in New Bedford in the last 18 months: address, units, list price, $/unit, cap, days on market. Then give me the median $/unit."

### 7.4 Rent Comp Database + weekly Zillow scan

**Two sources feed `rent_comps`:**
1. **Rent rolls shared with you:** when a rent roll comes in, parse it (`deal-extraction`) and write per unit type rents to `rent_comps`, tagged `source = rent_roll`.
2. **Weekly Zillow scan:** a scheduled task uses Claude in Chrome to pull active rent listings for each target market, by unit type, and writes them tagged `source = zillow`.

**Tools:** Claude in Chrome (browser scan), Postgres MCP (write), `deal-extraction` (rent roll parse).
**Prompt (rent roll):**
> "Parse this rent roll. For each unit, capture unit type, beds, baths, sqft, and current rent. Aggregate to average rent by unit type, write to the rent comp database tagged to [market] and this property, source rent_roll."

**Prompt (Zillow scan, scheduled):**
> "For each target market (Manchester, Nashua, Derry, Londonderry, Salem, Dover, Rochester, Somersworth, Farmington, Milton), pull current Zillow rental listings. Capture beds, baths, sqft, rent, address. Write to the rent comp database tagged by market and unit type, source zillow, dated today. Flag any market where median rent moved more than 3% vs last week."

### 7.5 Asset management  *(lowest priority)*

16 units across 3 buildings, stabilized. Keep it light until new deals generate revenue.
- Track lease expirations in Calendar (so renewals do not surprise you).
- Monthly: a one page variance check per property (actual vs budget rent, occupancy, delinquency), posted to Slack.
- The existing per property Drive folders (Fall River already has Monthly Financial Review, AM Dashboard) are the home for this.

Defer the build. Revisit once acquisitions are flowing.

---

## 8. Scheduled automation

Two distinct kinds. Do not confuse them.

- **Server side cron (in the app, always on):** the 15 minute Gmail ingestion. This belongs in the Railway app, not in Cowork, because it must run continuously and headless.
- **Cowork scheduled tasks (human facing cadence):**
  - **Daily morning briefing** (e.g. 6:30am): new deals in the last 24 to 48 hours, scored and summarized, posted to Slack. This is your coffee read.
  - **Weekly Zillow rent scan** (e.g. Monday am): refresh `rent_comps`, flag market moves.

I can set both Cowork tasks up the moment the database and Slack channel exist.

---

## 9. Prerequisites and open items

Before the priority 1 flow is fully automated, these need resolving:

1. **Confirm the buy box.** Feb doc said MA + NH, 6 to 30 units. My April note says Southern NH only (two corridors), 5 to 34 units, value add. The May pipeline is mostly NH with one MA (New Bedford) deal. `config/buy_box.yaml` is currently set to the April version. **Tell me which is right.**
2. **Reconnect Gmail with write scope.** The connector is currently read only, so I could not create the triage labels. Reconnect with label/modify access to enable auto labeling.
3. **`ben@rtprei.com` is not directly connected.** Deal emails are forwarded to `ben.sylvester18@gmail.com`, which *is* connected. Either keep forwarding, or connect the RTP inbox directly for cleaner capture.
4. **Dispatch is email** (Ben has no Slack). Briefings and high-score alerts are emailed via the Gmail API. Set `DISPATCH_EMAIL` in `.env`.
5. **Stand up Railway Postgres + the Postgres MCP connector.** This is the gating step for everything structured.

---

## 10. Sequenced rollout

- **Phase 0 (this week):** repo scaffold (done, in the package), create Railway Postgres + PostGIS, run `schema.sql`, connect the Postgres MCP to Cowork and Claude Code, seed the database from your existing Deal Database (22 deals).
- **Phase 1:** ingestion + comp capture (priority 1). Backfill 3 to 6 months of `Deal Flow` history.
- **Phase 2:** auto underwriting + BOE generation.
- **Phase 3:** rent comps + weekly Zillow scan.
- **Phase 4:** dashboard + map view.
- **Phase 5:** asset management.

A note on your own stated blind spot (over planning): this document is the plan. The next move is Phase 0, not a v3 of the plan. Open Claude Code on the repo, stand up the database, seed it. Build in reality.
