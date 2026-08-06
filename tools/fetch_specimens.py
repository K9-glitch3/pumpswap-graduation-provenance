"""Materialize the specimen manifest into runnable fixtures. Caller-run.

This is the only part of the repository that touches the network, and it is not
run by the test suite or by CI. It reads ``specimens/specimen_manifest.json``,
fetches each transaction and the LP-account state it needs from an RPC endpoint
you supply, and writes one fixture per specimen into ``specimens/raw/``. After
that, ``tests/test_specimens.py`` runs the verifier against whatever fixtures are
present.

    RPC_URL=<your endpoint> python tools/fetch_specimens.py

Set the endpoint in the environment rather than on the command line so a
credential-bearing URL does not land in shell history or the process list. The
transactions are public mainnet data; the endpoint is not shipped here.

Per genuine specimen this makes a small, bounded number of read-only calls:
one ``getTransaction``, one ``getMultipleAccounts`` over the writable keys to
resolve the pool, one ``getAccountInfo`` on the LP account, and one
``getTokenSupply`` on the LP mint. Nothing is written on chain.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_MANIFEST = _ROOT / "specimens" / "specimen_manifest.json"
_RAW_DIR = _ROOT / "specimens" / "raw"

PUMPSWAP_AMM_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
# PumpSwap Pool account allocation shapes (see pumpswap-pool-decoder).
_POOL_SIZES = {261, 301}


def _rpc(url: str, method: str, params: list[Any]) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    request = urllib.request.Request(
        url,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=body.encode(),
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if "error" in payload:
        raise RuntimeError(f"{method} error: {payload['error']}")
    return payload.get("result")


def _writable_keys(tx: dict[str, Any]) -> list[str]:
    message = tx.get("transaction", {}).get("message", {})
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in message.get("accountKeys", [])]
    loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
    for entry in loaded.get("writable", []):
        keys.append(entry if isinstance(entry, str) else entry.get("pubkey", ""))
    return [k for k in keys if k]


def _resolve_pool(url: str, tx: dict[str, Any]) -> str | None:
    """Return the single tx account owned by PumpSwap with a Pool-sized payload."""
    keys = _writable_keys(tx)
    if not keys:
        return None
    infos = _rpc(url, "getMultipleAccounts", [keys, {"encoding": "base64"}])
    candidates = []
    for key, info in zip(keys, (infos or {}).get("value", [])):
        if not info or info.get("owner") != PUMPSWAP_AMM_PROGRAM:
            continue
        data = info.get("data")
        raw = data[0] if isinstance(data, list) and data else ""
        try:
            import base64

            if len(base64.b64decode(raw)) in _POOL_SIZES:
                candidates.append(key)
        except Exception:
            continue
    return candidates[0] if len(candidates) == 1 else None


def _lp_account_state(url: str, lp_mint: str, lp_account: str) -> dict[str, Any]:
    info = _rpc(url, "getAccountInfo", [lp_account, {"encoding": "base64"}])
    supply = _rpc(url, "getTokenSupply", [lp_mint, {"commitment": "confirmed"}])
    supply_amount = ((supply or {}).get("value") or {}).get("amount")
    return {
        "lp_mint": lp_mint,
        "destination": lp_account,
        "destination_closed": (info or {}).get("value") is None,
        "lp_supply_zero": str(supply_amount) == "0",
    }


def main() -> int:
    url = os.environ.get("RPC_URL")
    if not url:
        print("Set RPC_URL to a Solana RPC endpoint (mainnet).", file=sys.stderr)
        return 2

    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    _RAW_DIR.mkdir(exist_ok=True)

    for specimen in manifest["specimens"]:
        name = specimen["name"]
        tx = _rpc(
            url,
            "getTransaction",
            [
                specimen["signature"],
                {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"},
            ],
        )
        if tx is None:
            print(f"  {name}: transaction not found (endpoint may lack history)", file=sys.stderr)
            continue

        recorded = specimen.get("recorded_evidence", {})
        lp_states = []
        if recorded.get("lp_mint") and recorded.get("lp_account"):
            lp_states = [_lp_account_state(url, recorded["lp_mint"], recorded["lp_account"])]

        fixture = {
            "name": name,
            "signature": specimen["signature"],
            "base_mint": specimen["base_mint"],
            "expected_verdict": specimen["expected_verdict"],
            "expected_pool": _resolve_pool(url, tx),
            "recorded_evidence": recorded,
            "transaction": tx,
            "lp_account_states": lp_states,
        }
        out = _RAW_DIR / f"{name}.json"
        out.write_text(json.dumps(fixture, indent=1), encoding="utf-8")
        print(f"  {name}: wrote {out.relative_to(_ROOT)} (pool={fixture['expected_pool']})")

    print("Done. Run: python -m unittest tests.test_specimens -v")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
