# pumpswap-graduation-provenance

An offline reference implementation for evaluating a fixed set of bound
pump.fun-to-PumpSwap migration-evidence predicates in a parsed Solana
transaction.

The caller supplies the parsed transaction, expected account identities, and
separately obtained LP-account state. A matched result means only that every
implemented predicate matched those inputs. The module makes no network calls.

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
- Nothing here supports a population-frequency, classification, execution, or
  economic claim.

See [REPORT.md](REPORT.md), [data/README.md](data/README.md), and
[CONTRIBUTING.md](CONTRIBUTING.md) for the reproducibility boundary.

## License

MIT - see [LICENSE](LICENSE).
