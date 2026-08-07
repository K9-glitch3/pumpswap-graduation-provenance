# A fresh PumpSwap pool is not proof of a pump.fun graduation

When a pump.fun token completes its bonding curve, a migration can create a new
PumpSwap pool. PumpSwap `CreatePool` can also be invoked outside that migration
path. A pool's initial balances therefore do not, by themselves, establish how
the pool was created. The verifier checks the creation provenance directly.

The two artifacts support different claims:

- **The data** (`data/`, summarised below) is an outcome-labelled,
  outcome-selected sample. It supports descriptive statements about those rows
  and nothing wider.
- **The verifier** (`graduation_provenance.py`) checks whether a supported
  pump.fun migration created an authenticated PumpSwap pool. That is a question
  about transaction and account evidence, not about this sample.

## What the sample can and cannot show

Every figure between the generated-summary markers below is computed by
`analyze_seeded_rugs.py` from the two descriptive JSON files and compared
byte-for-byte by `tests/test_analyze_seeded_rugs.py`. The repository does not
reproduce sample acquisition or outcome-label construction. The rows are not a
random or exhaustive PumpSwap sample, provide no population base rate, and
support no significance test. Missing measurements are reported separately and
never folded silently into a denominator.

For the small outcome-selected matched sample, the table reports the group
medians for `seed_sol` and `funding_gap_slots`. These are bounded descriptive
facts, not evidence of predictive performance.

The creator and funder counts below are also descriptive and do not establish
how useful any identity rule would be in or out of sample.

The descriptive data cannot establish a specific pool's creation provenance
because it contains no transaction or pool-account evidence. The verifier is a
separate artifact with real-specimen and synthetic rejection tests.

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
establish how that label was assigned. Missingness is reflected in the numeric
denominators shown above.

The script does not calculate classification accuracy, effect size,
statistical significance, confidence intervals, or out-of-sample performance.
The displayed summaries do not support a predictive conclusion.

Distinct-address counts are descriptive. They support no claim about who
controls an address, why any pool drained, or what an actor intended — only how
many distinct values appear in these rows.

## Reproducing the summaries

```text
python analyze_seeded_rugs.py
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The script reads only the checked-in JSON. It does not fetch data or reproduce
sample acquisition. The generated section above is rendered by
`render_report_summary()` and compared byte-for-byte by the tests.

## Evidence boundary

The two descriptive data files contain no instruction payloads, program
identifiers, reserve series, LP operations, or LP-account state. They cannot
support claims about transaction causality, withdrawal mechanics, program
involvement, or verifier accuracy.

Those files also do not define a random or exhaustive PumpSwap sample. Counts
in this report describe only the checked-in rows. The committed specimens are a
separate, small verifier corpus and support conclusions only about those cases.
