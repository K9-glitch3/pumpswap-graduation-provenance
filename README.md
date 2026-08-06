# pumpswap-graduation-provenance

Tell a genuine pump.fun graduation apart from a **seeded pool** that only looks
like one, by checking a pool's creation transaction rather than its appearance.

When a pump.fun token finishes its bonding curve, its SOL migrates into a new
PumpSwap pool. A pool that appears already deep in SOL looks like that event —
but the same shape is produced by funding a wallet and calling PumpSwap
`CreatePool` directly, with no pump.fun program involved. The creator holds the
LP and can withdraw the pool later. [REPORT.md](REPORT.md) shows, from a sample
of drained pools, why the obvious pre-entry filters (seed size, funding recency,
creator/funder blocklists) do not separate the two cases — which is why this
repository checks provenance instead.

This is an offline reference implementation of a fixed set of bound
pump.fun-to-PumpSwap migration-evidence predicates over a parsed Solana
transaction. The caller supplies the parsed transaction, account identities, and
separately obtained LP-account state. A matched result means only that every
implemented predicate matched those inputs. The module makes no network calls,
constructs no transactions, selects or ranks no pools, and makes no safety or
trading judgement.

## Contents

- `graduation_provenance.py` evaluates caller-supplied transaction evidence.
- `analyze_seeded_rugs.py` computes descriptive summaries from the checked-in
  JSON files.
- `REPORT.md` contains a generated numeric section and states its evidence
  limits.
- `data/` documents the exact public schemas.

The transaction verifier and the descriptive datasets are separate artifacts.
The JSON files contain no parsed transactions and do not validate the verifier.

This repository contains no transaction construction, signing, submission,
pool selection or ranking, operational rules, observation schedule, economic
analysis, credentials, endpoints, or wallet-ownership labels.

## Evidence API

```python
from graduation_provenance import (
    LpAccountState,
    MigrationContext,
    verify_migration_evidence,
)

context = MigrationContext(
    expected_pool=pool_address,
    lp_mint=lp_mint,
    lp_account=lp_token_account,
    base_source=base_source_token_account,
    base_destination=base_destination_token_account,
    sol_source=sol_source_account,
    sol_destination=sol_destination_account,
)

result = verify_migration_evidence(
    parsed_transaction,
    base_mint,
    context,
    lp_account_states=[
        LpAccountState(
            lp_mint=lp_mint,
            destination=lp_token_account,
            destination_closed=True,
            lp_supply_zero=True,
        )
    ],
)

if result.is_match:
    ...  # every implemented predicate matched the supplied context
else:
    ...  # result.failed_check names the first predicate not established
```

`EVIDENCE_MATCHED` means all of the following were established, in this order:

1. the transaction shape is usable and `meta.err` is null;
2. the base mint and migration context are valid and their accounts are present;
3. a pump.fun outer instruction and PumpSwap inner instruction are present;
4. exactly one indexed inner-instruction group binds both instructions to the
   supplied accounts and provides usable stack-height metadata;
5. the named SOL source transfers at least 80 SOL to the named destination;
6. the named base-token source and destination have equal-magnitude negative
   and positive balance changes, respectively;
7. below the bound PumpSwap CPI, the named LP mint and account have a positive
   `mintTo` followed by an equal-amount `burn`; and
8. caller-supplied state says that exact LP account is closed and the LP mint
   supply is zero.

`EVIDENCE_NOT_ESTABLISHED` means at least one required predicate was not
established, including because input was missing, malformed, failed, or
inconsistent. It is not proof that no migration occurred.

The public result names an evidence match, not protocol-level authentication.
It does not establish that the transaction is canonical, determine intent,
assess safety or future behaviour, or recommend an action.

## Screening an unknown pool

`verify_migration_evidence` requires every migration account up front, which is
correct for the strict check but assumes you already know the LP mint, the LP
account, and the base-token and SOL source/destination accounts. A screener
examining a new pool knows only the two facts on the pool account itself: the
pool address and its non-WSOL mint.

`screen_pool` closes that gap. It derives the remaining accounts *structurally*
from the transaction — the LP mint/burn pair, the two base-mint balance moves,
and the large bound SOL debit with its matching credit — refuses when any role
is ambiguous, and then hands the derived context straight to
`verify_migration_evidence`.

```python
from graduation_provenance import screen_pool, LpAccountState

result = screen_pool(
    parsed_creation_tx,
    expected_pool=pool_address,      # the pool you are screening
    base_mint=pool_base_mint,        # its non-WSOL mint
    lp_account_states=[LpAccountState(...)],  # obtained separately, as above
)
```

The derivation is a convenience, not a second source of truth. Its output is
only a candidate context; the strict verifier re-binds and re-checks the whole
structure, so a wrong derivation fails closed rather than producing a match.
When derivation itself cannot resolve a role, the verdict's `failed_check` is
prefixed `derive:` (for example `derive:lp_pair_not_found`).

## Tests

```text
python -m unittest discover -s tests -v
```

The verifier tests use synthetic transaction dictionaries and supplied account
state. They open no network connection and are not validation against a
labelled transaction corpus. The analysis tests enforce the public schemas,
missing-value counts, descriptive values, and the generated report section.

CI runs the same suite on Python 3.11 and 3.13.

## Limits

- Opaque pump.fun and PumpSwap instruction data is required but its
  discriminator fields are not decoded; the result therefore remains an
  evidence match.
- The 80-SOL threshold and 1-SOL diagnostic debit floor are fixed reference
  predicates, not calibrated performance estimates.
- The datasets do not contain the transaction evidence required by the
  verifier and do not establish random or exhaustive sampling.
- `screen_pool`'s derivation resolves each account role only when it is
  unambiguous in the transaction and does not rank candidates by magnitude;
  where a role is ambiguous it fails closed. The strict verifier remains the
  authority, so a mis-derived account cannot yield a match.
- Both the verifier and the screening path are exercised against synthetic
  transaction fixtures only. They encode the intended decision; they have not
  been run against a labelled corpus of live transactions in this repository.
- Nothing here supports a population-frequency, classification, execution, or
  economic claim.

See [REPORT.md](REPORT.md), [data/README.md](data/README.md), and
[CONTRIBUTING.md](CONTRIBUTING.md) for the reproducibility boundary.

## License

MIT - see [LICENSE](LICENSE).
