# RTP database: data model
Target schema for the RTP operating system. v01, 10/12/26. Companion to `context/build-plan.md` (why and when) and `context/ai-sandbox-plan.md` (dashboard and skills). Live DDL is `db/schema.sql` plus `db/migrations/NNN_*.sql`; this file is the human-readable contract and must be updated in the same commit as any migration.

Legend: **[live]** exists in production today. **[P1]** to **[P4]** added in that build phase. Column lists show name: type, then notes. PK = primary key, FK = foreign key, NN = not null, UQ = unique.

## Conventions (enforced by CHECK constraints and column types, not by habit)
• Money: `bigint` cents, suffix `_cents` on new columns (live tables use plain names like `asking_price`; still cents)
• Rates and percentages: `numeric(8,6)` decimal fraction. 8.5% is `0.085`
• Ratios: `numeric(8,4)`. 1.31x is `1.3100`
• Dates that are dates: `date`. Moments: `timestamptz`. Periods: `date` on the first of the month
• Identity: `id serial` PK on every table except pure join tables and `processed_messages`
• Provenance: every imported or parsed row carries `source text` (where it came from), `source_id text` (the id in that source) and `created_at timestamptz default now()`. Parsed rows also keep `raw_data jsonb` or a `document_id`
• Deletion: never. `status` flags, `merged_into_id` self-references, and `_history` tables. Append-only tables raise on UPDATE and DELETE (trigger)
• Names: snake_case, singular FK column names (`property_id`), plural table names
• Enumerations: `text` with a CHECK list, not Postgres enums (easier to extend by migration)
• Address key: `rtp_normalize_address(address, city, state)` lowercases, strips punctuation, expands "St/Street", "Rd/Road", "Ave/Avenue", collapses whitespace, and keeps the low end of a range. Used as a generated, unique column on `properties`

## Blocks and how they connect
```
                       organizations ──< people ──< people_emails
                              │            │
            ┌─────────────────┴────────────┴───────────────┐
            │          interactions  action_items  documents│   (events and pointers: any row
            │                                               │    can attach to a property, listing,
            │                                               │    package, entity or person)
            └───────────────────────┬───────────────────────┘
                                    │
   properties ──< listings >── packages          properties ──< property_units ──< leases
       │             │                                │                 │
       │             ├──< listing_financials          ├──< rent_roll_snapshots
       │             ├──< unit_mix                    ├──< gl_actuals ──> gl_accounts_standard <── gl_mappings
       │             ├──< auto_underwriting           ├──< capex_items
       │             ├──< listing_history             ├──< building_systems
       │             ├──< offers                      ├──< utility_setup
       │             └──< uw_model_versions           ├──< property_loans
       │                                              └──< reporting_requirements
       └──< entities ──< investments ──< distributions
                 └──< investor_communications ──< investor_communication_recipients

   rent_comps (standalone, optional link to listings)      job_runs, review_queue, system_meta
```
One idea: `properties` is the spine. A listing is one time a building came to market; an entity is one time RTP bought it; AM tables are what happened while RTP owned it. People and organizations are the other spine, and `interactions` is how the two meet.

---

## Block 1: core [P1]

### properties [P1]
One row per real building, forever. Created automatically from every distinct address in `listings` (backfill) and by hand for owned assets that never came through the ingest.
| column | type | notes |
|---|---|---|
| id | serial PK | |
| address | text NN | street line as best known |
| city | text NN | |
| state | char(2) NN | |
| zip | text | |
| county | text | |
| address_key | text, generated, UQ | `rtp_normalize_address(address, city, state)`; duplicate insert fails loudly |
| address_range_low | int, generated | low end of "116-118" so range variants surface in `v_duplicate_property_candidates`, never auto-merged |
| latitude, longitude | numeric(9,6) | geocoded once |
| parcel_id | text | assessor map/lot |
| units | int | best known |
| year_built | int | |
| building_sf, lot_sf | int | |
| property_class | text CHECK (A, B, C) | |
| rtp_relationship | text NN CHECK (prospect, owned, sold, passed) | default prospect; set owned when an `entities` row with this property closes |
| owner_of_record | text | from registry or CoStar |
| owner_org_id | FK organizations | when the owner entity is known |
| drive_folder_id | text | root folder for the asset (AUM folder when owned, UW folder when a deal) |
| notes | text | |
| merged_into_id | FK properties | survivor pointer |
| created_at, updated_at | timestamptz | |

### organizations [P1]
| column | type | notes |
|---|---|---|
| id | serial PK | |
| name | text NN | |
| kind | text NN CHECK (brokerage, pm_company, lender, law_firm, capital_partner, lp_entity, owner_entity, vendor, insurer, accountant, other) | |
| website, city, state | text | |
| notes | text | |
| source, source_id | text | tracker tab and row, broker list rank, CoStar owner name |
| merged_into_id | FK organizations | |
| created_at, updated_at | timestamptz | |
UQ on (lower(name), kind).

### people [P1]
One row per human. The relationship tracker's LP columns and the call list's owner scoring both land here, so one person can be an LP and an owner.
| column | type | notes |
|---|---|---|
| id | serial PK | |
| full_name | text NN | |
| first_name, last_name | text | |
| org_id | FK organizations | primary affiliation |
| title | text | |
| roles | text[] NN | any of lp, lp_prospect, capital_partner, broker, owner, lender, attorney, vendor, operator_partner, connector, personal |
| phone | text | |
| linkedin_url, reconvene_url | text | |
| city, state | text | |
| lp_tier | char(1) CHECK (A, B, C, D) | from the tracker |
| lp_relationship | text | how Ben knows them |
| lp_indicated_cents | bigint | indicated next-deal check |
| lp_next_deal_stage | text | tracker column |
| owner_score | int | call-list score |
| owner_tier | text CHECK (T1, T2, T3, T4) | |
| warmth | text CHECK (hot, warm, cold, closed) | capital partners and operators |
| notes | text | |
| source, source_id | text | |
| merged_into_id | FK people | |
| created_at, updated_at | timestamptz | |

### people_emails [P1]
| column | type | notes |
|---|---|---|
| id | serial PK | |
| person_id | FK people NN | |
| email | citext NN UQ | the join key to Gmail |
| is_primary | bool NN default false | |
| label | text | work, personal |

### interactions [P1], append-only
Every touch between RTP and a person, optionally about a deal or asset. Replaces every "last touch" column.
| column | type | notes |
|---|---|---|
| id | serial PK | |
| person_id | FK people | at least one of person_id or org_id |
| org_id | FK organizations | |
| listing_id | FK listings | optional subject |
| package_id | FK packages | |
| property_id | FK properties | |
| entity_id | FK entities | |
| channel | text NN CHECK (email, call, meeting, linkedin, reconvene, text, in_person, other) | |
| direction | text NN CHECK (inbound, outbound, mutual) | |
| occurred_at | timestamptz NN | |
| summary | text NN | one to three sentences |
| by_whom | text CHECK (ben, justin, claude) | who logged or who spoke |
| source, source_id | text | gmail thread id, wispr meeting id, "ben debrief 10/12" |
| created_at | timestamptz | |
UQ (source, source_id, person_id). Index (person_id, occurred_at desc).

### action_items [P1]
Replaces the tracker's Next actions tab and feeds every "to do" view.
| column | type | notes |
|---|---|---|
| id | serial PK | |
| title | text NN | |
| details | text | |
| owner | text NN CHECK (ben, justin, claude, other) | |
| due_on | date | |
| status | text NN CHECK (open, waiting, done, dropped) | |
| person_id, org_id, listing_id, package_id, property_id, entity_id | FKs | what it is about |
| source, source_id | text | |
| created_at, completed_at | timestamptz | |

### documents [P1]
The pointer layer between the database and Drive.
| column | type | notes |
|---|---|---|
| id | serial PK | |
| drive_file_id | text UQ | |
| drive_url | text | |
| title | text NN | |
| doc_type | text NN CHECK (om, rent_roll, t12, pnl, balance_sheet, lease, psa, loi, model, boe, investor_report, k1, insurance, loan_doc, tax_card, deed, photo, pm_export, survey, inspection, other) | |
| listing_id, package_id, property_id, entity_id, person_id | FKs | what it belongs to |
| version | text | "v03" |
| doc_date | date | |
| mime, size_bytes, sha256 | text, bigint, text | |
| notes | text | |
| created_at | timestamptz | |

### drive_map [P1]
| column | type | notes |
|---|---|---|
| id | serial PK | |
| entity_kind | text NN CHECK (property, listing, package, entity, firm) | |
| entity_id | int | null for firm-level |
| purpose | text NN | root, seller_data, legal, financing, uw, dd, am, investor_reporting, insurance, leases, taxes, templates |
| drive_folder_id | text NN | |
| path | text | human path for logs |
UQ (entity_kind, entity_id, purpose).

---

## Block 2: acquisitions [live], extended [P1]

### listings [live]
One row per time a building came to market or was offered. Also the sale comp store (`sale_price` set). 36 columns today; the ones that matter:
`id, external_id (MLS), address, city, state, zip, latitude, longitude, units, asking_price (cents), price_per_unit, year_built, building_sf, lot_sf, property_class, status, source, broker_name, broker_email, listing_date, date_ingested, days_on_market, raw_email_id, raw_data jsonb, drive_folder_id, om_url, boe_url, notes, package_id FK packages, last_seen_at, account, uw_folder, merged_into_id FK listings, sale_price, sale_price_per_unit, sale_date`.
Status CHECK: comp_only, lead, underwriting, loi_sent, under_contract, owned, lost, passed, needs_review (see `STATUS_MODEL.md`).
Added [P1]: `property_id FK properties NN after backfill`, `broker_person_id FK people`, `broker_org_id FK organizations`. Source gains values `registry`, `costar`, `manual`, `deal_log_csv`.

### packages [live]
Multi-parcel deals. `id, name, market, state, status, asking_price, total_units, broker_name, broker_email, drive_folder_id, notes, created_at, last_seen_at`. Members link through `listings.package_id`. Buy box is evaluated on combined units (`v_deals.effective_units`). Added [P1]: `broker_person_id`.

### listing_financials [live]
One per listing: `gross_revenue, vacancy_rate, effective_gross_income, total_expenses, expense_ratio, noi, cap_rate, avg_rent_per_unit, taxes, insurance, utilities, data_source, confidence`.

### unit_mix [live]
Per listing per unit type: `unit_type, count, avg_sf, avg_rent, market_rent, rent_delta_pct`.

### auto_underwriting [live]
System quick screen per listing or package: buy box flags, implied caps, DSCR, score, tier, summary, plus the Drive model sync (`model_file, model_version, model_modified, model_synced_at, model_stats jsonb`). [P1] the model sync moves to `uw_model_versions`; these columns stay as "latest" for the dashboard.

### listing_history [live], append-only
`listing_id, changed_at, field, old_value, new_value`. Every status move, price change and sale price.

### offers [P1]
Every indicative bid, LOI, revision, counter and PSA. Today's LOI gap is this table.
| column | type | notes |
|---|---|---|
| id | serial PK | |
| listing_id | FK listings | exactly one of listing_id or package_id |
| package_id | FK packages | |
| offer_type | text NN CHECK (indicative, loi, loi_revised, counter_received, psa_draft, psa_executed) | |
| direction | text NN CHECK (sent, received) | |
| offer_date | date NN | |
| price_cents | bigint | |
| terms | jsonb | deposit_cents, deposit_hard_after, dd_days, close_days, financing_contingency, seller_note, exclusivity_days, acceptance_date, allocation |
| document_id | FK documents | the LOI file |
| sent_to_person_id | FK people | broker or seller |
| response | text NN CHECK (pending, accepted, declined, countered, expired, withdrawn) | |
| response_date | date | |
| response_notes | text | |
| created_at | timestamptz | |

### uw_model_versions [P1]
| column | type | notes |
|---|---|---|
| id | serial PK | |
| listing_id, package_id | FKs | one required |
| drive_file_id | text NN | |
| file_name | text NN | |
| version_label | text | "v12" |
| modified_at | timestamptz NN | Drive modified time |
| synced_at | timestamptz NN | |
| price_cents | bigint | purchase price in the model |
| cap_in, cap_stabilized | numeric(8,6) | |
| irr, moic | numeric(8,6), numeric(8,4) | base case; the sheet!cell pointers live in `metrics` |
| metrics | jsonb | everything extracted, with provenance |
UQ (drive_file_id, modified_at).

### broker_format_config, processed_messages, system_meta [live]
Parser column maps per sender; Gmail ids already processed (`account, msg_id, processed_at, result`); key-value state.

---

## Block 3: comps [live], extended [P3]

### rent_comps [live]
`id, market, address, latitude, longitude, unit_type, beds, baths, sqft, rent, source, source_listing_id FK listings, observed_date, raw_data`. Added [P3]: `city, state, listing_url, available_on, concessions text, job_run_id FK job_runs`. Index (city, beds, observed_date).

### Sale comps
No new table. `listings` rows with `sale_price` not null, any status, exposed by `v_sale_comps`. Registry and CoStar sales are inserted as listings with `source` registry or costar and `status` comp_only.

### market_rents (view) [P3]
Median, p25, p75, count by city, beds, month, trailing 90 days. The BOE skill reads this.

---

## Block 4: asset management [P2]

### property_units
| column | type | notes |
|---|---|---|
| id | serial PK | |
| property_id | FK properties NN | |
| unit_label | text NN | "42-3", "Unit 2", "Basement N" |
| beds, baths | int, numeric(3,1) | |
| sqft | int | |
| floor | text | |
| pm_system | text CHECK (appfolio, buildium, none) | |
| pm_unit_id | text | the id in the PM system |
| notes | text | |
UQ (property_id, unit_label).

### leases
| column | type | notes |
|---|---|---|
| id | serial PK | |
| unit_id | FK property_units NN | |
| tenant_name | text | |
| tenant_person_id | FK people | optional |
| start_on, end_on | date | |
| rent_cents | bigint NN | |
| deposit_cents | bigint | |
| status | text NN CHECK (pending, active, month_to_month, notice, ended, evicted) | |
| voucher | bool | Section 8 or similar |
| document_id | FK documents | the lease file |
| source, source_id | text | pm system and lease id |
UQ (source, source_id).

### rent_roll_snapshots
One row per unit per export, so history is kept.
| column | type | notes |
|---|---|---|
| id | serial PK | |
| property_id | FK properties NN | |
| unit_id | FK property_units NN | |
| as_of | date NN | export date |
| tenant_name | text | |
| rent_cents | bigint | |
| balance_cents | bigint | delinquency |
| occupancy | text NN CHECK (occupied, vacant, notice, eviction, down) | |
| lease_end_on | date | |
| document_id | FK documents | the export file |
UQ (unit_id, as_of).

### gl_accounts_standard
RTP's chart of accounts (about 40 lines). Built from the John St and Summer St workbooks.
| column | type | notes |
|---|---|---|
| id | serial PK | |
| code | text NN UQ | "4010" |
| name | text NN | "Gross potential rent" |
| section | text NN CHECK (income, vacancy_credit_loss, other_income, opex, noi, below_line, capex, debt_service, distributions, balance_sheet) | |
| parent_id | FK gl_accounts_standard | roll-ups |
| sort | int NN | |
| is_active | bool NN default true | |

### gl_mappings
The normalization layer. One row per source account name.
| column | type | notes |
|---|---|---|
| id | serial PK | |
| source_system | text NN CHECK (appfolio, buildium, quickbooks, workbook, manual) | |
| source_account_name | text NN | exactly as the export prints it |
| source_account_code | text | |
| standard_account_id | FK gl_accounts_standard NN | |
UQ (source_system, source_account_name). An unmapped name on import creates a `review_queue` row and the amount parks on a "unmapped" standard account until resolved.

### gl_actuals
| column | type | notes |
|---|---|---|
| id | serial PK | |
| property_id | FK properties NN | |
| entity_id | FK entities | owning entity |
| period | date NN | first of month |
| standard_account_id | FK gl_accounts_standard NN | |
| amount_cents | bigint NN | |
| basis | text NN CHECK (cash, accrual) | |
| source | text NN | appfolio, buildium, workbook |
| document_id | FK documents | |
| imported_at | timestamptz | |
UQ (property_id, period, standard_account_id, source, basis). Index (property_id, period).

### budgets
Same shape as `gl_actuals` plus `version text`; UQ (property_id, period, standard_account_id, version).

### capex_items
| column | type | notes |
|---|---|---|
| id | serial PK | |
| property_id | FK properties NN | |
| unit_id | FK property_units | |
| item_date | date | |
| description | text NN | |
| category | text NN CHECK (roof, boiler_hvac, water_heater, plumbing, electrical, windows_doors, siding_exterior, porches_decks, interior_turn, appliances, site_parking, fire_safety, other) | |
| amount_cents | bigint | |
| vendor_org_id | FK organizations | |
| status | text NN CHECK (planned, approved, in_progress, done) | |
| document_id | FK documents | invoice or quote |
| notes | text | |

### building_systems
| column | type | notes |
|---|---|---|
| id | serial PK | |
| property_id | FK properties NN | |
| system | text NN CHECK (roof, boiler, furnace, water_heater, electrical_service, panels, plumbing_supply, sewer_line, windows, siding, porches_decks, fire_alarm, sprinkler, foundation, parking, septic, well) | |
| description | text | "rear flat roof", "Lochinvar 2024" |
| year_installed | int | |
| condition | text CHECK (good, fair, poor, unknown) | |
| remaining_life_years | int | |
| replacement_cost_cents | bigint | |
| next_action | text | |
| source | text | inspection, PCA, Ben walk, invoice |
| updated_at | timestamptz | |
UQ (property_id, system, description).

### utility_setup
| column | type | notes |
|---|---|---|
| id | serial PK | |
| property_id | FK properties NN | |
| utility | text NN CHECK (heat, hot_water, electric, water_sewer, trash, cooking_gas, internet, snow_landscape) | |
| fuel | text CHECK (gas, oil, electric, propane, none) | |
| paid_by | text NN CHECK (owner, tenant, split) | |
| meter_count | int | |
| provider | text | |
| annual_cost_cents | bigint | owner-paid portion |
| notes | text | |
UQ (property_id, utility).

### property_loans
| column | type | notes |
|---|---|---|
| id | serial PK | |
| property_id | FK properties NN | |
| entity_id | FK entities | borrower |
| lender_org_id | FK organizations | |
| loan_name | text | |
| original_cents, balance_cents | bigint | |
| balance_as_of | date | |
| rate | numeric(8,6) | |
| rate_type | text CHECK (fixed, floating) | |
| amort_months, io_months | int | |
| origination_on, maturity_on | date | |
| dscr_covenant | numeric(8,4) | |
| reporting | text | what the lender wants and when |
| guarantors | text | |
| document_id | FK documents | note or commitment |
| status | text NN CHECK (active, paid_off, refinanced) | |

### reporting_requirements
| column | type | notes |
|---|---|---|
| id | serial PK | |
| property_id | FK properties | one of property or entity |
| entity_id | FK entities | |
| requirement | text NN | "lender quarterly P&L", "MA annual report" |
| kind | text NN CHECK (lender, tax, investor, insurance, state_filing, license, inspection, other) | |
| frequency | text NN CHECK (monthly, quarterly, annual, one_time) | |
| due_rule | text | "45 days after quarter end" |
| next_due_on | date | |
| last_done_on | date | |
| owner | text CHECK (ben, justin, accountant, pm) | |
| notes | text | |
Generates `action_items` rows 30 days before `next_due_on`.

---

## Block 5: investor relations [P1 minimal, P4 full]

### entities [P1]
| column | type | notes |
|---|---|---|
| id | serial PK | |
| legal_name | text NN UQ | |
| short_name | text | "RTRG", "John St LLC" |
| kind | text NN CHECK (sponsor, deal_spv, holding, personal, pm_company) | |
| state_of_formation | char(2) | |
| ein_on_file | bool | never the EIN itself |
| formed_on | date | |
| registered_agent_org_id | FK organizations | |
| property_id | FK properties | single-asset SPV |
| manager | text | who signs |
| operating_agreement_document_id | FK documents | |
| notes | text | |

### investments [P1 minimal]
| column | type | notes |
|---|---|---|
| id | serial PK | |
| entity_id | FK entities NN | |
| person_id | FK people | one of person or investor_org |
| investor_org_id | FK organizations | an LP's LLC or IRA custodian |
| share_class | text | |
| commitment_cents | bigint | |
| funded_cents | bigint | |
| funded_on | date | |
| ownership_pct | numeric(8,6) | |
| is_gp | bool NN default false | |
| document_id | FK documents | Exhibit A, subscription |
| notes | text | |
UQ (entity_id, person_id, investor_org_id, share_class).

### distributions [P4]
| column | type | notes |
|---|---|---|
| id | serial PK | |
| entity_id | FK entities NN | |
| investment_id | FK investments NN | |
| paid_on | date NN | |
| amount_cents | bigint NN | |
| kind | text NN CHECK (cash_flow, return_of_capital, refinance, sale, tax) | |
| tax_year | int | |
| method, reference | text | ACH, check number |
| document_id | FK documents | |

### investor_communications [P4]
| column | type | notes |
|---|---|---|
| id | serial PK | |
| entity_id | FK entities | null = firm-wide (newsletter) |
| sent_on | date NN | |
| kind | text NN CHECK (quarterly_report, annual_report, newsletter, k1, capital_call, update, other) | |
| subject | text | |
| document_id | FK documents | |
| audience_rule | text | "Tier A+B plus opted-in" |
| notes | text | |

### investor_communication_recipients [P4]
`comm_id FK, person_id FK`, PK (comm_id, person_id).

---

## Block 6: operations [P1]

### job_runs
| column | type | notes |
|---|---|---|
| id | serial PK | |
| job | text NN | ingest, briefing, uw_sync, pm_import, rent_comps, registry_sales, review_check, backup, tracker_export |
| started_at | timestamptz NN | |
| finished_at | timestamptz | |
| status | text NN CHECK (running, ok, warn, error) | |
| counts | jsonb | inserted, enriched, skipped, errors |
| message | text | |
The briefing reads `v_jobs_missing` (jobs with no ok run inside their expected interval).

### review_queue
| column | type | notes |
|---|---|---|
| id | serial PK | |
| kind | text NN CHECK (listing_needs_review, unmapped_gl_account, unmatched_email, parse_failure, duplicate_property, scraper_error, model_sync_error) | |
| ref_table, ref_id | text, int | |
| payload | jsonb | |
| status | text NN CHECK (open, resolved, dismissed) | |
| created_at, resolved_at | timestamptz | |
| resolution | text | |
Replaces the `needs_review` listing status over time (listings keep it until the dashboard Inbox tab exists).

---

## Views (what the dashboard and Claude read)
| view | phase | purpose |
|---|---|---|
| v_deals, v_pipeline, v_pipeline_deals, v_deal_board, v_sale_comps | live | active pipeline, deal board, executed sales |
| v_property_history | P1 | every listing, offer and entity for a property |
| v_broker_activity | P1 | listings per broker per month, last interaction |
| v_lp_pipeline | P1 | people with lp roles, tier, indicated, last interaction, open action |
| v_action_items_open | P1 | by owner and due date |
| v_duplicate_property_candidates | P1 | same range low and city, different keys |
| v_portfolio_summary | P2 | per property: latest occupancy, T3 and T12 collections, NOI, loan, DSCR |
| v_property_pnl | P2 | monthly by standard account, all properties, budget beside actual |
| v_lease_expirations | P2 | next 12 months |
| v_reporting_due | P2 | requirements due in 60 days |
| v_market_rents | P3 | median, quartiles, count by city and beds |
| v_investor_positions | P4 | commitment, funded, distributed, pct by entity and investor |
| v_jobs_missing | P1 | jobs that did not run on schedule |

## Migrations plan
| file | phase | contents |
|---|---|---|
| 015_core_properties.sql | P1 | `rtp_normalize_address()`, `properties`, backfill from listings, `listings.property_id` |
| 016_people_orgs.sql | P1 | `organizations`, `people`, `people_emails`, `listings.broker_person_id` |
| 017_events_docs.sql | P1 | `interactions`, `action_items`, `documents`, `drive_map`, `offers`, `uw_model_versions`, append-only triggers |
| 018_ops.sql | P1 | `job_runs`, `review_queue`, `v_jobs_missing` |
| 019_entities_investments.sql | P1 | `entities`, `investments` |
| 020_views_p1.sql | P1 | P1 views |
| 021_am.sql | P2 | all Block 4 tables |
| 022_views_p2.sql | P2 | P2 views |
| 023_comps.sql | P3 | `rent_comps` columns, `v_market_rents` |
| 024_ir.sql | P4 | `distributions`, `investor_communications`, recipients, `v_investor_positions` |
Each migration is rehearsed on `postgres-sandbox`, then applied to production with `scripts/apply_migration.py NNN` after `scripts/backup_db.py`.

## Design decisions (Ben, 10/12/26)
1. **Unit count:** latest data wins. Owned: latest rent roll snapshot. Not owned: latest listing. Assessor and broker figures stay on the detail page
2. **Internal people:** Ben, Justin and Ren are `people` rows with role `internal`; `interactions.by_whom` and `action_items.owner` become FKs to them
3. **Investments:** one row per LP per entity. An LP in 186 John St who also invests in the next deal gets a second row under the new entity; `v_investor_positions` groups by person across entities so the cross-deal view is one query
4. **Review queue and the briefing:** move `needs_review` to `review_queue` in P1 with an Inbox tab. Ben does not read the briefing email ("pretty useless"); what he needs is that everything hitting the inbox is logged. P1 replaces the daily briefing email with an exceptions-only note (jobs that failed, review queue count, in-box leads with a model) and keeps the 6:30 job itself for the model sync and job checks. Kill it entirely if the exceptions version is still noise
5. **Chart of accounts:** Ben's AM workbook and the Baxter model lines are the base (seed list below), with a `parent_id` roll-up to the lender P&L format

## Seed: `gl_accounts_standard` v01
From the Baxter Master BOE (Other Income, Operating Expenses, CapEx blocks, Ben 10/12) plus the standard rental income lines above them. Codes group by thousand; `parent_id` points at the section total. Lines above Other Income are standard and need a check against the John St 2Q26 workbook `[CONFIRM names]`.

| code | name | section | parent |
|---|---|---|---|
| 4000 | Gross potential rent | income | |
| 4010 | Loss to lease | income | 4000 |
| 4020 | Vacancy | vacancy_credit_loss | 4000 |
| 4030 | Bad debt / delinquency | vacancy_credit_loss | 4000 |
| 4040 | Concessions | vacancy_credit_loss | 4000 |
| 4090 | Net rental income | income | |
| 4100 | Gas (heat and hot water) income | other_income | 4190 |
| 4110 | Electric income | other_income | 4190 |
| 4120 | Storage income | other_income | 4190 |
| 4130 | Water and sewer income | other_income | 4190 |
| 4140 | Trash income | other_income | 4190 |
| 4150 | Laundry income | other_income | 4190 |
| 4160 | Parking income | other_income | 4190 |
| 4170 | Pet fees | other_income | 4190 |
| 4180 | Other income, miscellaneous | other_income | 4190 |
| 4190 | Total other income | other_income | |
| 4900 | Total revenue | income | |
| 5100 | Repairs and maintenance | opex | 5900 |
| 5200 | Insurance | opex | 5900 |
| 5300 | Management | opex | 5900 |
| 5400 | Water and sewer | opex | 5900 |
| 5410 | Electric | opex | 5900 |
| 5420 | Gas (heat and hot water) | opex | 5900 |
| 5430 | Trash removal | opex | 5900 |
| 5500 | Pest control | opex | 5900 |
| 5510 | Snow removal / landscaping | opex | 5900 |
| 5600 | G&A / payroll / monitoring | opex | 5900 |
| 5700 | Real estate taxes | opex | 5900 |
| 5800 | Reserves | opex | 5900 |
| 5900 | Total operating expenses | opex | |
| 5950 | Net operating income | noi | |
| 6100 | Renovations / turnover | capex | 6900 |
| 6200 | General / building / systems | capex | 6900 |
| 6300 | Security systems | capex | 6900 |
| 6400 | Contingency | capex | 6900 |
| 6900 | Total capex | capex | |
| 7100 | Debt service, interest | debt_service | 7900 |
| 7110 | Debt service, principal | debt_service | 7900 |
| 7900 | Total debt service | debt_service | |
| 7950 | Cash flow after debt service | below_line | |
| 8100 | Distributions to members | distributions | |
| 8200 | Capital contributions | distributions | |
| 8900 | Professional fees (legal, tax prep) | below_line | |
| 8910 | Entity costs (state filings, registered agent) | below_line | |

Lender roll-up (The Business Bank quarterly P&L) is a second set of `parent_id` values added once the lender's template is read `[CONFIRM format]`. Mapping rows (`gl_mappings`) for AppFolio and Buildium are written when the first exports arrive.
