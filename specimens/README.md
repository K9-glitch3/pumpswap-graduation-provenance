# Specimens

Real mainnet transactions used to check the verifier against on-chain data
rather than only synthetic fixtures. Every signature and account in
[`specimen_manifest.json`](specimen_manifest.json) is public and can be looked up
on any Solana explorer.

## What is and is not here

The manifest records, for five real transactions, what each one is (four
pump.fun graduations and one transaction that has the pump.fun and PumpSwap
programs but does not destroy its LP), the expected verdict, and the key facts a
correct decode must reproduce. It does **not** contain the raw transactions —
those are fetched on demand.

The expected verdicts and recorded evidence come from a prior offline decode of
these transactions in the source research project. Whether *this* repository's
stricter, account-bound verifier reproduces that classification is exactly what
the specimen test measures. A genuine specimen this verifier rejects is a real
finding about the verifier's strictness, not a defect in the specimen.

## Materializing the fixtures

```text
RPC_URL=<your mainnet endpoint> python tools/fetch_specimens.py
```

This writes one fixture per specimen into `specimens/raw/`. It is the only code
in the repository that uses the network, and neither the test suite nor CI runs
it. Set the endpoint in the environment, not on the command line.

## Running the check

```text
python -m unittest tests.test_specimens -v
```

With no fixtures present the module skips, so the default test run and CI need no
network. Once `specimens/raw/` is populated, each fixture becomes a hard check:
the verifier must reproduce the manifest's expected verdict for that real
transaction. If you commit the materialized fixtures, that check runs in CI too —
which is the point, but it also means a verifier that cannot classify a real
genuine graduation will turn CI red until the verifier is corrected.
