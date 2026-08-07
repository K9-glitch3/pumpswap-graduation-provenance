# Specimens

Real mainnet transactions used to check the verifier against on-chain data
rather than only synthetic fixtures. Every signature and account in
[`specimen_manifest.json`](specimen_manifest.json) is public and can be looked up
on any Solana explorer.

## What is and is not here

The manifest records five real transactions: four supported pump.fun migrations
and one ordinary buy in an already migrated pool. The ordinary-buy negative is
a weak discriminator because it fails several provenance gates; it is not an
isolated test of LP destruction. A separate, clearly synthetic test preserves
the authenticated pool and program structure while removing the LP burn.

The manifest is the independent oracle for each real specimen's signature,
slot, canonical transaction digest, base mint, expected verdict, and recorded
evidence. The materialized files under `raw/` contain the public transaction
response, decoded pool-account snapshot, and LP state used by the verifier. The
test checks the complete transaction against that digest and cross-checks copied
fields against the manifest before evaluating it, so a self-consistent but
altered fixture cannot redefine its own expected result.

Here, a `GENUINE_PUMP_FUN_GRADUATION` label means only that the recorded
provenance says a supported pump.fun migration created the pool. It is not a
safety label.

## Materializing the fixtures

```text
RPC_URL=<your mainnet endpoint> python tools/fetch_specimens.py
```

This regenerates one fixture per manifest entry in `specimens/raw/`, including
the decoded pool's raw account bytes and required LP state. The fetcher makes
only read-only RPC calls and exits non-zero if any required transaction or
account is unavailable. It is the only code in the repository that uses the
network; neither the test suite nor CI invokes it. Set the endpoint in the
environment, not on the command line.

## Running the check

```text
python -m pip install -r requirements.txt
python -m unittest tests.test_specimens -v
```

The five materialized fixtures are committed and mandatory. A missing manifest
entry, missing or unresolved fixture, empty transaction, copied-field mismatch,
or wrong verifier verdict fails the test. CI therefore checks that all four
supported migrations match and the ordinary-buy negative does not, without
contacting an RPC endpoint.
