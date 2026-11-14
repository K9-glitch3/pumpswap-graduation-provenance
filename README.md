# pumpswap-graduation-provenance

Part of [Core Vanta's market provenance research](https://core-vanta.com/projects/market-provenance/), a central London AI research lab.

Authenticate whether a supported pump.fun migration created a specific
PumpSwap pool, using its creation transaction and raw pool-account state.

PumpSwap `CreatePool` can be invoked inside or outside a pump.fun migration.
Initial balances and program co-presence therefore do not authenticate a pool's
origin. This verifier decodes the pool account, the pump.fun migration, and the
ordered PumpSwap `CreatePool` roles before checking migration-frame token and LP
operations.

This is an offline reference implementation over caller-supplied Solana
evidence. A matched result establishes only that the implemented predicates
show a supported pump.fun migration created the authenticated pool. It does not
mean the pool is safe. The verifier makes no network calls, constructs no
transactions, selects or ranks no pools, and makes no trading judgement.

## Contents

- `graduation_provenance.py` evaluates caller-supplied transaction evidence.
- `pumpswap_decoder.py` is the strict pool-state decoder vendored from the
  sibling `pumpswap-pool-decoder` project under the same MIT license.
- `analyze_seeded_rugs.py` computes descriptive summaries from the checked-in
  JSON files.
- `REPORT.md` contains a generated numeric section and states its evidence
  limits.
- `data/` documents the exact public schemas.
- `specimens/` contains the manifest and committed real-transaction fixtures
  used as an offline acceptance gate.

The transaction verifier and the descriptive datasets are separate artifacts.
The two files under `data/` contain no parsed transactions and do not validate
the verifier.

This repository contains no transaction construction, signing, submission,
pool selection or ranking, operational rules, observation schedule, economic
analysis, credentials, concrete endpoints, or wallet-ownership labels. The
caller-run specimen fetcher makes bounded read-only RPC calls when explicitly
invoked; neither the verifier nor the test suite performs network I/O.

## Evidence API

```python
from graduation_provenance import (
    LpAccountState,
    MigrationContext,
    PoolAccountEvidence,
    PUMPSWAP_AMM_PROGRAM,
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
    pool_account=PoolAccountEvidence(
        address=pool_address,
        owner=PUMPSWAP_AMM_PROGRAM,
        data_base64=pool_account_data_base64,
        context_slot=pool_account_context_slot,
    ),
)

if result.is_match:
    ...  # the supported migration created this authenticated pool
else:
    ...  # result.failed_check names the first predicate not established
```

`EVIDENCE_MATCHED` means all of the following were established, in this order:

1. the transaction shape is usable and `meta.err` is null;
2. the base mint, immutable migration-context snapshot, and raw pool-account
   snapshot are valid;
3. the raw bytes decode as a PumpSwap-owned Pool at the expected address, with
   the supplied base mint and transaction roles matching its decoded mints,
   vaults, LP mint, creator, and configuration;
4. exactly one supported pump.fun `Migrate` or `MigrateV2` frame contains a
   decoded PumpSwap `CreatePool` invocation with the required ordered account
   roles;
5. direct child operations in that migration frame move the declared base
   amount into `CreatePool`, initialise WSOL, and move the instruction-declared
   base and quote amounts into the authenticated vaults; the decoded bonding-
   curve account must debit at least 80 SOL and at least the quote amount, but
   no exact debit/credit equality is assumed;
6. the LP mint receives exactly one positive `mintTo` below `CreatePool`,
   followed by a matching `burn` and close in the same pump.fun migration
   frame, matched by token program ID rather than the RPC program label; and
7. caller-supplied state says that exact LP account is closed and the LP mint
   supply is zero.

`EVIDENCE_NOT_ESTABLISHED` means at least one required predicate was not
established, including because input was missing, malformed, failed, or
inconsistent. It is not proof that no migration occurred.

The result authenticates the supported migration-to-pool relationship encoded
by these inputs. It does not determine intent, assess safety or future
behaviour, or recommend an action.

## Screening an unknown pool

`verify_migration_evidence` accepts an explicit `MigrationContext` for callers
that already have the decoded roles. `screen_pool` is the derive-then-verify
entry point: it authenticates the supplied pool bytes, locates one supported
migration/`CreatePool` frame, derives the roles from the decoded instruction and
pool state, and delegates to the same verifier.

```python
from graduation_provenance import (
    LpAccountState,
    PoolAccountEvidence,
    screen_pool,
)

result = screen_pool(
    parsed_creation_tx,
    expected_pool=pool_address,
    base_mint=pool_base_mint,
    lp_account_states=[LpAccountState(...)],
    pool_account=PoolAccountEvidence(...),
)
```

The derivation is a convenience, not a second trust path. The transaction and
pool evidence are snapshotted, and the verifier rechecks the derived immutable
context. Missing, malformed, unauthenticated, or ambiguous evidence fails
closed. A derivation failure has a `failed_check` prefixed with `derive:`.

## Tests

```text
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The suite includes synthetic rejection cases and five committed real-mainnet
specimens: four supported migrations must match and one ordinary post-migration
buy must not. The real negative is a weak discriminator because it fails
multiple gates, so a separate synthetic case isolates an otherwise valid
authenticated pool and program structure with no LP burn. Missing or altered
specimens fail the suite; tests never fetch from the network.

The analysis tests enforce the public schemas, missing-value counts,
descriptive values, and generated report section. CI runs the complete suite on
Python 3.10, 3.13, and 3.14.

## Limits

- Only the explicitly decoded PumpSwap Pool layouts and pump.fun migration /
  PumpSwap `CreatePool` instruction layouts are supported. Unknown variants
  fail closed.
- The 80-SOL floor is a fixed provenance predicate, not a calibrated
  performance estimate or trading threshold.
- Pool-account and LP-state snapshots are caller-supplied. The verifier checks
  their shape and identities, checks the pool owner's supplied RPC metadata,
  and requires the pool snapshot slot not to precede the transaction. The LP
  booleans carry no slot or cryptographic attestation. The verifier performs no
  fetch of its own and cannot prove that supplied RPC metadata is truthful.
- The parsed transaction and inner-instruction trace are also caller-supplied.
  The verifier checks their structure and reported success but does not verify a
  transaction signature or independently attest chain inclusion. The specimen
  manifest digest pins the committed RPC response; it is not a chain proof.
- The datasets do not contain the transaction evidence required by the
  verifier and do not establish random or exhaustive sampling.
- The committed real corpus is small, and its sole ordinary-buy negative fails
  several predicates. It validates those specimens, not broad classifier
  performance.
- Nothing here supports a population-frequency, safety, execution, or economic
  claim.

See [REPORT.md](REPORT.md), [data/README.md](data/README.md), and
[CONTRIBUTING.md](CONTRIBUTING.md) for the reproducibility boundary.

## License

MIT - see [LICENSE](LICENSE).
