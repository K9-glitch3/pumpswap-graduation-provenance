# Descriptive summary of the checked-in data

This report is limited to values computed by `analyze_seeded_rugs.py` from the
two JSON files in `data/`.

It does not infer collection mechanics, transaction mechanics, program
involvement, intent, classification performance, risk, execution, or
profitability. The files do not provide a denominator for a broader PumpSwap
population.

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

Distinct-address counts are descriptive only. No conclusion about address
reuse, identity, or action follows from them.

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
