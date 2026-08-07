# Data

These JSON files use deliberately narrow schemas. Only the fields documented
below may appear.

## `seeded_pool_rugs.json`

This file contains 189 records. Every row has exactly:

| Field | Type | Meaning |
| --- | --- | --- |
| `mint` | string | Non-WSOL token mint recorded for the row. |
| `pool_creator` | string | Pool-creator address recorded for the row. |
| `seed_funder` | string or null | Funding address recorded for the creator, when available. |
| `seed_sol` | number or null | Recorded funding-transfer value in SOL, represented to at most six decimal places. |
| `funding_gap_slots` | integer or null | Pool-creation slot minus funding-transfer slot. A positive value records funding before creation; a negative value records the reverse. |

## `seed_timing_matched.json`

This file contains 60 records: 30 with `outcome: "rug"` and 30 with
`outcome: "surv"`.

It uses the five fields above plus:

| Field | Type | Meaning |
| --- | --- | --- |
| `outcome` | `"rug"` or `"surv"` | Renamed source label used to group rows in the descriptive analysis. |

The outcome is an input label. It is not a risk assessment or a statement about
future behaviour.

## Null handling

A null `seed_funder`, `seed_sol`, or `funding_gap_slots` means that this public
file contains no value for that field. The three funding fields are either all
present or all null in each row. Analysis reports the populated or numeric
denominator and never coerces null to zero.

## Reproducibility boundary

`python analyze_seeded_rugs.py` validates the schemas and recomputes descriptive
summaries from these files. It does not fetch data or reproduce acquisition.

The descriptive dataset contains no raw observation series or dataset-
acquisition code. It can support checks of schema, row counts, and summaries,
but cannot independently establish sample selection, outcome-label
construction, transaction mechanics, or completeness relative to a wider
population. The separately documented specimen fetcher acquires public
transaction fixtures only; it does not reproduce this dataset's acquisition.

Do not add unlisted source fields or document acquisition configuration,
operational parameters, economics, credentials, endpoints, local paths, or
wallet ownership.
