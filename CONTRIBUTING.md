# Contributing

Small, focused pull requests are welcome.

## Running the tests

From the repository root:

```text
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The suite uses standard-library `unittest` and opens no network connection. CI
runs it on the Python versions listed in `.github/workflows/tests.yml`.

## Ground rules

- **Keep the data schemas exact.** `seeded_pool_rugs.json` may contain only
  `mint`, `pool_creator`, `seed_funder`, `seed_sol`, and
  `funding_gap_slots`. `seed_timing_matched.json` may additionally contain
  `outcome`.
- **Report missingness explicitly.** Every statistic over a nullable field must
  state its populated or numeric denominator.
- **Keep empirical claims reproducible.** Numeric statements in `REPORT.md`
  must be returned by `analyze_seeded_rugs.py` and asserted by the tests.
- **Keep result semantics narrow.** An evidence match means the implemented
  predicates authenticate that the supplied pool snapshot is structurally a
  PumpSwap pool and bind its decoded roles to a pump.fun migration frame in the
  supplied transaction. Do not describe that provenance result as an assessment
  of intent, risk, or future behaviour.
- **Malformed evidence does not pass.** Add a rejection test for every newly
  accepted input shape. Booleans must not be accepted as numbers, required
  identifiers and amounts must be non-empty, and missing nested structures must
  produce the documented not-established result.
- **Offline tests only.** The committed specimen tests replay four real
  migration transactions, one ordinary-buy negative, and constructed adversarial
  cases. The suite does not contact an RPC endpoint.
- **No operational material.** Do not add transaction construction, signing,
  submission, selection, ranking, execution rules, acquisition configuration,
  profitability analysis, credentials, endpoints, local paths, or user/author
  wallet labels.

## What a good change looks like

- It updates code, tests, and documentation together.
- It asserts an observable success or rejection result.
- It preserves stable check precedence.
- It keeps the decoded pool roles, migration roles, CreatePool roles, and LP
  destruction evidence bound to one migration frame.
- It does not turn missing or malformed evidence into a positive match.

## Reporting a mismatch

Prefer a minimal synthetic fixture that reproduces the result. Include the
expected identifiers, the first failed check, and the result you expected.

Do not include credentials, credential-bearing endpoints, local paths,
operational parameters, or private wallet information.

## License

By contributing you agree that your contributions are licensed under the MIT
License.
