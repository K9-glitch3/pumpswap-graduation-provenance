# A fresh PumpSwap pool is not proof of a pump.fun graduation

When a pump.fun token completes its bonding curve it *graduates*: the curve's
SOL migrates into a new PumpSwap pool. A pool that appears already deep in SOL
looks like that event. The same on-chain shape is also produced by a **seeded
pool** — a funded wallet calls PumpSwap `CreatePool` directly, with no pump.fun
program involved, holds the LP, and can withdraw both sides of the pool later.
Buyers who entered because "it just graduated" are the liquidity left behind.

This repository has two separate artifacts, and it is careful about which one
supports which claim:

- **The data** (`data/`, summarised below) is a sample of pools that were later
  drained. It supports statements about that sample and nothing wider.
- **The verifier** (`graduation_provenance.py`) checks, from a pool's creation
  transaction, whether a pump.fun migration actually produced it. That is a
  question about a transaction, not about this sample; the two are not mixed.

## What the sample can and cannot show

Every figure in the generated section below is computed by
`analyze_seeded_rugs.py` from the two JSON files and pinned byte-for-byte by
`tests/test_analyze_seeded_rugs.py`. The sample is one observation window,
selected on the drained outcome by construction. It therefore describes *these*
rows; it is **not** a random or exhaustive draw from PumpSwap, gives no base
rate of honeypots, and supports no significance test. Missing measurements are
reported as their own count and never folded silently into a denominator (20 of
the 189 rug rows, and some matched rows, have no funding data).

Two readings are worth stating in plain language, both taken directly from the
table:

- **The obvious pre-entry filter does not separate the two groups.** In the
  matched 30-rug / 30-survivor set, the survivors were seeded slightly *larger*
  (median 158 vs 148 SOL) and funded slightly *later* (median 62 vs 45 slots)
  than the rugs. Seed size and funding recency do not tell a later-drained pool
  apart from one that was not. Whatever decides the drain is not visible in
  these fields at creation time.
- **Blocklists have little to grip.** The 189 drained pools have 178 distinct
  creators — a fresh creator almost every time — so a creator blocklist has
  almost nothing to match. Funders are only mildly concentrated (114 distinct
  funders across the rows).

If appearance and identity at creation time do not separate a seeded pool from
a genuine graduation, the reliable signal is **provenance**: did a pump.fun
migration create the pool? That is what the verifier checks, and why it exists.
It is a question this dataset cannot answer for any specific pool — the JSON
holds no transactions — which is exactly why the verifier is a separate artifact
with its own synthetic-fixture tests.

<!-- BEGIN GENERATED SUMMARY -->
## File contents

| File | Rows | Additional label |
| --- | ---: | --- |
| `data/seeded_pool_rugs.json` | 189 | none |
| `data/seed_timing_matched.json` | 60 | `outcome` |

## `seeded_pool_rugs.json`

| Measure | Value | Denominator |
| --- | ---: | --- |
| Rows | 189 | 189 rows |
| Populated `pool_creator` values | 189 | 189 rows |
| Distinct `pool_creator` values | 178 | 189 populated values |
| Populated `seed_funder` values | 169 | 189 rows |
| Missing `seed_funder` values | 20 | 189 rows |
| Distinct `seed_funder` values | 114 | 169 populated values |
| Numeric `seed_sol` values | 169 | 189 rows |
| Missing `seed_sol` values | 20 | 189 rows |
| Median `seed_sol` | 189.980031 SOL | 169 numeric values |
| Minimum `seed_sol` | 16.141337 SOL | 169 numeric values |
| Maximum `seed_sol` | 2877.912488 SOL | 169 numeric values |
| Numeric `funding_gap_slots` values | 169 | 189 rows |
| Missing `funding_gap_slots` values | 20 | 189 rows |
| Median `funding_gap_slots` | 51 slots | 169 numeric values |
| Minimum `funding_gap_slots` | -108111 slots | 169 numeric values |
| Maximum `funding_gap_slots` | 416098 slots | 169 numeric values |

## `seed_timing_matched.json`

| `outcome` label | Rows | Numeric seed n | Median `seed_sol` | Numeric gap n | Median `funding_gap_slots` |
| --- | ---: | ---: | ---: | ---: | ---: |
| `rug` | 30 | 27 | 147.635449 SOL | 27 | 45 slots |
| `surv` | 30 | 24 | 158.2541785 SOL | 24 | 61.5 slots |
<!-- END GENERATED SUMMARY -->

`outcome` is treated as an input label. This repository does not independently
establish how that label was assigned. Three `rug` rows and six `surv` rows
have null funding fields, so the numeric denominators differ from the row
counts.

The script does not calculate classification accuracy, effect size,
statistical significance, confidence intervals, or out-of-sample performance.
The displayed summaries do not support a predictive conclusion.

Distinct-address counts are descriptive. They support no claim about who
controls an address, why any pool drained, or what an actor intended — only how
many distinct values appear in these rows.

## Reproducing the summaries

```text
python analyze_seeded_rugs.py
python -m unittest discover -s tests -v
```

The script reads only the checked-in JSON. It does not fetch data or reproduce
sample acquisition. The generated section above is rendered by
`render_report_summary()` and compared byte-for-byte by the tests.

## Evidence boundary

The checked-in files contain no instruction payloads, program identifiers,
reserve series, LP operations, or LP-account state. They cannot support claims
about transaction causality, withdrawal mechanics, program involvement, or
verifier accuracy.

The files also do not define a random or exhaustive PumpSwap sample. Counts in
this report describe only the checked-in rows.
