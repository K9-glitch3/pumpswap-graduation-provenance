"""Materialize the public mainnet specimen manifest into offline fixtures.

This caller-run tool is the repository's only networked component. It performs
read-only Solana RPC calls, authenticates each referenced PumpSwap pool from its
owned account bytes, and writes fixtures only after every manifest entry has
been fetched and validated successfully.

    RPC_URL=<your endpoint> python tools/fetch_specimens.py

Set the endpoint in the environment so a credential-bearing URL is neither
placed on the command line nor written into a fixture. The endpoint is never
included in error messages.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import base58

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pumpswap_decoder import (
    PUMP_AMM_PROGRAM,
    PoolDecodeError,
    decode_rpc_account_value,
)

_MANIFEST = _ROOT / "specimens" / "specimen_manifest.json"
_RAW_DIR = _ROOT / "specimens" / "raw"

PUMPSWAP_AMM_PROGRAM = PUMP_AMM_PROGRAM
_EXPECTED_VERDICTS = frozenset(
    {
        "GENUINE_PUMP_FUN_GRADUATION",
        "NOT_GENUINE_PUMP_FUN_GRADUATION",
    }
)
_SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_U64_MAX = (1 << 64) - 1
_MANIFEST_FIELDS = frozenset(
    {
        "description",
        "provenance",
        "expected_verdict_values",
        "note_on_outcome",
        "specimens",
    }
)
_SPECIMEN_FIELDS = frozenset(
    {
        "name",
        "signature",
        "slot",
        "transaction_sha256",
        "base_mint",
        "expected_pool",
        "expected_verdict",
        "recorded_evidence",
    }
)
_POSITIVE_RECORDED_FIELDS = frozenset(
    {"sol_migration_debit_sol", "lp_mint", "lp_account", "lp_mint_burn_amount"}
)


class SpecimenFetchError(RuntimeError):
    """A fail-closed acquisition or validation error safe to print."""


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_base58(value: Any, *, decoded_size: int, field: str) -> str:
    max_encoded_length = math.ceil(decoded_size * math.log(256, 58))
    if (
        not isinstance(value, str)
        or not value
        or len(value) > max_encoded_length
    ):
        raise SpecimenFetchError(f"{field} must be a non-empty Base58 string")
    try:
        decoded = base58.b58decode(value)
    except (TypeError, ValueError) as exc:
        raise SpecimenFetchError(f"{field} is not valid Base58") from None
    if (
        len(decoded) != decoded_size
        or base58.b58encode(decoded).decode("ascii") != value
    ):
        raise SpecimenFetchError(
            f"{field} must be canonical Base58 encoding of {decoded_size} bytes"
        )
    return value


def _validate_pubkey(value: Any, field: str) -> str:
    return _validate_base58(value, decoded_size=32, field=field)


def _validate_signature(value: Any, field: str) -> str:
    return _validate_base58(value, decoded_size=64, field=field)


def _parse_u64_string(value: Any, field: str) -> int:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdigit()
        or len(value) > 20
    ):
        raise SpecimenFetchError(f"{field} must be a u64 string")
    parsed = int(value)
    if value != str(parsed) or parsed > _U64_MAX:
        raise SpecimenFetchError(f"{field} must be a u64 string")
    return parsed


def _transaction_sha256(tx: Any) -> str:
    try:
        canonical = json.dumps(
            tx,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise SpecimenFetchError("transaction cannot be canonically serialized") from None
    return hashlib.sha256(canonical).hexdigest()


def _rpc(url: str, method: str, params: list[Any]) -> Any:
    """Make one read-only JSON-RPC call without ever rendering ``url``."""
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        request = urllib.request.Request(
            url,
            method="POST",
            headers={"Content-Type": "application/json"},
            data=body,
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except Exception as exc:
        # HTTPError and URLError may embed a credential-bearing URL in their
        # string representation. Report only the exception type.
        raise SpecimenFetchError(
            f"{method} request failed ({type(exc).__name__})"
        ) from None

    if not isinstance(payload, Mapping):
        raise SpecimenFetchError(f"{method} returned a non-object response")
    if payload.get("jsonrpc") != "2.0" or payload.get("id") != 1:
        raise SpecimenFetchError(f"{method} returned invalid JSON-RPC metadata")
    if "error" in payload:
        raise SpecimenFetchError(f"{method} returned an RPC error")
    if "result" not in payload:
        raise SpecimenFetchError(f"{method} response omitted result")
    return payload["result"]


def _validate_manifest(manifest: Any) -> list[Mapping[str, Any]]:
    """Validate the local manifest before making any network request."""
    if not isinstance(manifest, Mapping):
        raise SpecimenFetchError("manifest root must be an object")
    if set(manifest) != _MANIFEST_FIELDS:
        raise SpecimenFetchError("manifest fields do not match the public schema")
    for field in ("description", "provenance", "note_on_outcome"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise SpecimenFetchError(f"manifest {field} must be a non-empty string")
    verdict_values = manifest.get("expected_verdict_values")
    if not isinstance(verdict_values, list) or set(verdict_values) != _EXPECTED_VERDICTS:
        raise SpecimenFetchError("manifest verdict vocabulary is invalid")
    specimens = manifest.get("specimens")
    if not isinstance(specimens, list) or len(specimens) != 5:
        raise SpecimenFetchError("manifest must contain exactly five specimens")

    seen_names: set[str] = set()
    seen_signatures: set[str] = set()
    validated: list[Mapping[str, Any]] = []
    for position, specimen in enumerate(specimens):
        label = f"manifest specimen {position}"
        if not isinstance(specimen, Mapping):
            raise SpecimenFetchError(f"{label} must be an object")
        if set(specimen) != _SPECIMEN_FIELDS:
            raise SpecimenFetchError(f"{label} fields do not match the public schema")

        name = specimen.get("name")
        if not isinstance(name, str) or _SAFE_NAME.fullmatch(name) is None:
            raise SpecimenFetchError(f"{label} has an unsafe name")
        if name in seen_names:
            raise SpecimenFetchError(f"manifest contains duplicate name {name}")
        seen_names.add(name)

        signature = _validate_signature(
            specimen.get("signature"), f"{name}.signature"
        )
        if signature in seen_signatures:
            raise SpecimenFetchError("manifest contains a duplicate signature")
        seen_signatures.add(signature)

        slot = specimen.get("slot")
        if not _is_nonnegative_int(slot):
            raise SpecimenFetchError(f"{name}.slot must be a non-negative integer")
        _validate_pubkey(specimen.get("base_mint"), f"{name}.base_mint")
        expected_pool = _validate_pubkey(
            specimen.get("expected_pool"), f"{name}.expected_pool"
        )
        digest = specimen.get("transaction_sha256")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise SpecimenFetchError(f"{name}.transaction_sha256 is invalid")

        verdict = specimen.get("expected_verdict")
        if verdict not in _EXPECTED_VERDICTS:
            raise SpecimenFetchError(f"{name}.expected_verdict is unsupported")
        recorded = specimen.get("recorded_evidence")
        if not isinstance(recorded, Mapping):
            raise SpecimenFetchError(f"{name}.recorded_evidence must be an object")

        if verdict == "GENUINE_PUMP_FUN_GRADUATION":
            if set(recorded) != _POSITIVE_RECORDED_FIELDS:
                raise SpecimenFetchError(
                    f"{name}.recorded_evidence fields are invalid for a positive"
                )
            debit = recorded.get("sol_migration_debit_sol")
            if (
                type(debit) not in (int, float)
                or not math.isfinite(debit)
                or debit < 80
                or debit != round(debit, 6)
            ):
                raise SpecimenFetchError(
                    f"{name}.recorded_evidence SOL debit is invalid"
                )
            lp_mint = recorded.get("lp_mint")
            lp_account = recorded.get("lp_account")
            _validate_pubkey(lp_mint, f"{name}.recorded_evidence.lp_mint")
            _validate_pubkey(lp_account, f"{name}.recorded_evidence.lp_account")
            if _parse_u64_string(
                recorded.get("lp_mint_burn_amount"),
                f"{name}.recorded_evidence.lp_mint_burn_amount",
            ) == 0:
                raise SpecimenFetchError(
                    f"{name}.recorded_evidence LP amount must be positive"
                )
        else:
            if set(recorded) != {"note"}:
                raise SpecimenFetchError(
                    f"{name}.recorded_evidence fields are invalid for a negative"
                )
            if not isinstance(recorded.get("note"), str) or not recorded["note"].strip():
                raise SpecimenFetchError(
                    f"{name}.recorded_evidence note must be non-empty"
                )
        validated.append(specimen)
    verdicts = [row["expected_verdict"] for row in validated]
    if verdicts.count("GENUINE_PUMP_FUN_GRADUATION") != 4:
        raise SpecimenFetchError("manifest must contain four positive specimens")
    if verdicts.count("NOT_GENUINE_PUMP_FUN_GRADUATION") != 1:
        raise SpecimenFetchError("manifest must contain one negative specimen")
    return validated


def _validate_transaction(
    tx: Any, specimen: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Require the requested successful transaction, not merely an RPC object."""
    if not isinstance(tx, Mapping) or not tx:
        raise SpecimenFetchError("transaction is unavailable or malformed")
    slot = tx.get("slot")
    if not _is_nonnegative_int(slot) or slot != specimen["slot"]:
        raise SpecimenFetchError("transaction slot does not match the manifest")

    wire_tx = tx.get("transaction")
    if not isinstance(wire_tx, Mapping):
        raise SpecimenFetchError("transaction payload is missing")
    signatures = wire_tx.get("signatures")
    if not isinstance(signatures, list) or not signatures:
        raise SpecimenFetchError("transaction signatures are missing")
    if signatures[0] != specimen["signature"]:
        raise SpecimenFetchError("returned transaction signature does not match")
    for position, signature in enumerate(signatures):
        _validate_signature(signature, f"transaction.signatures[{position}]")

    message = wire_tx.get("message")
    if not isinstance(message, Mapping):
        raise SpecimenFetchError("transaction message is missing")
    if not isinstance(message.get("accountKeys"), list):
        raise SpecimenFetchError("transaction accountKeys are missing")
    if not isinstance(message.get("instructions"), list):
        raise SpecimenFetchError("transaction instructions are missing")

    meta = tx.get("meta")
    if not isinstance(meta, Mapping) or "err" not in meta:
        raise SpecimenFetchError("transaction metadata is missing")
    if meta["err"] is not None:
        raise SpecimenFetchError("transaction did not succeed")
    inner = meta.get("innerInstructions")
    if inner is not None and not isinstance(inner, list):
        raise SpecimenFetchError("transaction innerInstructions are malformed")
    loaded = meta.get("loadedAddresses")
    if loaded is not None and not isinstance(loaded, Mapping):
        raise SpecimenFetchError("transaction loadedAddresses are malformed")
    if _transaction_sha256(tx) != specimen["transaction_sha256"]:
        raise SpecimenFetchError("transaction content does not match the manifest digest")
    return tx


def _writable_keys(tx: Mapping[str, Any]) -> list[str]:
    """Return only keys explicitly marked writable in a jsonParsed response."""
    message = tx["transaction"]["message"]
    keys: list[str] = []
    seen: set[str] = set()

    for position, entry in enumerate(message["accountKeys"]):
        if not isinstance(entry, Mapping):
            raise SpecimenFetchError(
                "jsonParsed accountKeys entry is not an object"
            )
        pubkey = _validate_pubkey(
            entry.get("pubkey"), f"transaction.accountKeys[{position}].pubkey"
        )
        writable = entry.get("writable")
        if not isinstance(writable, bool):
            raise SpecimenFetchError("accountKeys writable flag is missing")
        if pubkey in seen:
            raise SpecimenFetchError("transaction contains duplicate account keys")
        seen.add(pubkey)
        if writable:
            keys.append(pubkey)

    loaded = tx["meta"].get("loadedAddresses")
    if loaded is None:
        return keys
    for kind in ("writable", "readonly"):
        entries = loaded.get(kind)
        if not isinstance(entries, list):
            raise SpecimenFetchError(f"loadedAddresses.{kind} is malformed")
        for position, entry in enumerate(entries):
            pubkey = _validate_pubkey(
                entry, f"loadedAddresses.{kind}[{position}]"
            )
            if pubkey in seen:
                raise SpecimenFetchError("transaction contains duplicate account keys")
            seen.add(pubkey)
            if kind == "writable":
                keys.append(pubkey)
    return keys


def _iter_instructions(tx: Mapping[str, Any]):
    message = tx["transaction"]["message"]
    for instruction in message["instructions"]:
        if not isinstance(instruction, Mapping):
            raise SpecimenFetchError("transaction instruction is malformed")
        yield instruction

    inner_groups = tx["meta"].get("innerInstructions") or []
    for group in inner_groups:
        if not isinstance(group, Mapping):
            raise SpecimenFetchError("inner-instruction group is malformed")
        index = group.get("index")
        if not _is_nonnegative_int(index):
            raise SpecimenFetchError("inner-instruction index is malformed")
        instructions = group.get("instructions")
        if not isinstance(instructions, list):
            raise SpecimenFetchError("inner-instruction list is malformed")
        for instruction in instructions:
            if not isinstance(instruction, Mapping):
                raise SpecimenFetchError("inner instruction is malformed")
            yield instruction


def _pumpswap_account_zeroes(tx: Mapping[str, Any]) -> set[str]:
    """Return account[0] from every PumpSwap instruction in the transaction."""
    pools: set[str] = set()
    for instruction in _iter_instructions(tx):
        if instruction.get("programId") != PUMPSWAP_AMM_PROGRAM:
            continue
        accounts = instruction.get("accounts")
        if not isinstance(accounts, list) or not accounts:
            raise SpecimenFetchError("PumpSwap instruction has no account[0]")
        pools.add(_validate_pubkey(accounts[0], "PumpSwap instruction account[0]"))
    if not pools:
        raise SpecimenFetchError("transaction contains no PumpSwap account[0]")
    return pools


def _context_value(
    result: Any, method: str, *, min_context_slot: int
) -> tuple[int, Any]:
    if not isinstance(result, Mapping):
        raise SpecimenFetchError(f"{method} result is malformed")
    context = result.get("context")
    if not isinstance(context, Mapping):
        raise SpecimenFetchError(f"{method} context is missing")
    context_slot = context.get("slot")
    if (
        not _is_nonnegative_int(context_slot)
        or context_slot < min_context_slot
    ):
        raise SpecimenFetchError(f"{method} context slot is invalid")
    if "value" not in result:
        raise SpecimenFetchError(f"{method} result omitted value")
    return context_slot, result["value"]


def _resolve_pool_from_result(
    tx: Mapping[str, Any],
    base_mint: str,
    writable_keys: list[str],
    result: Any,
) -> dict[str, Any]:
    """Purely resolve one authenticated WSOL pool from an RPC result."""
    _validate_pubkey(base_mint, "base_mint")
    exact_writable = _writable_keys(tx)
    if writable_keys != exact_writable:
        raise SpecimenFetchError("pool lookup keys are not the exact writable keys")
    pump_account_zeroes = _pumpswap_account_zeroes(tx)
    tx_slot = tx["slot"]
    context_slot, values = _context_value(
        result, "getMultipleAccounts", min_context_slot=tx_slot
    )
    if not isinstance(values, list) or len(values) != len(writable_keys):
        raise SpecimenFetchError("getMultipleAccounts value count is invalid")

    candidates: list[dict[str, Any]] = []
    for address, value in zip(writable_keys, values):
        if address not in pump_account_zeroes or value is None:
            continue
        try:
            state = decode_rpc_account_value(value)
        except PoolDecodeError:
            # PumpSwap has non-Pool instructions whose account[0] is another
            # account type. Such accounts are not candidates.
            continue
        if state.token_mint != base_mint:
            continue
        if not isinstance(value, Mapping) or value.get("executable") is not False:
            raise SpecimenFetchError("decoded pool executable flag is invalid")
        payload = value.get("data")
        raw = base64.b64decode(payload[0], validate=True)
        canonical_b64 = base64.b64encode(raw).decode("ascii")
        candidates.append(
            {
                "address": address,
                "owner": value["owner"],
                "context_slot": context_slot,
                "data_base64": canonical_b64,
            }
        )

    if len(candidates) != 1:
        raise SpecimenFetchError(
            "pool resolution did not produce exactly one authenticated candidate"
        )
    return candidates[0]


def _resolve_pool(
    url: str, tx: Mapping[str, Any], base_mint: str
) -> dict[str, Any]:
    writable_keys = _writable_keys(tx)
    if not writable_keys:
        raise SpecimenFetchError("transaction contains no writable accounts")
    result = _rpc(
        url,
        "getMultipleAccounts",
        [
            writable_keys,
            {
                "encoding": "base64",
                "commitment": "confirmed",
                "minContextSlot": tx["slot"],
            },
        ],
    )
    return _resolve_pool_from_result(tx, base_mint, writable_keys, result)


def _lp_account_state_from_results(
    lp_mint: str,
    lp_account: str,
    info_result: Any,
    supply_result: Any,
    *,
    min_context_slot: int,
) -> dict[str, Any]:
    """Purely validate LP RPC results and reduce them to verifier state."""
    _validate_pubkey(lp_mint, "lp_mint")
    _validate_pubkey(lp_account, "lp_account")
    _, account_value = _context_value(
        info_result, "getAccountInfo", min_context_slot=min_context_slot
    )
    if account_value is not None and not isinstance(account_value, Mapping):
        raise SpecimenFetchError("getAccountInfo account value is malformed")

    _, supply_value = _context_value(
        supply_result, "getTokenSupply", min_context_slot=min_context_slot
    )
    if not isinstance(supply_value, Mapping):
        raise SpecimenFetchError("getTokenSupply value is malformed")
    amount = _parse_u64_string(
        supply_value.get("amount"), "getTokenSupply amount"
    )
    return {
        "lp_mint": lp_mint,
        "destination": lp_account,
        "destination_closed": account_value is None,
        "lp_supply_zero": amount == 0,
    }


def _lp_account_state(
    url: str, lp_mint: str, lp_account: str, *, min_context_slot: int
) -> dict[str, Any]:
    info_result = _rpc(
        url,
        "getAccountInfo",
        [
            lp_account,
            {
                "encoding": "base64",
                "commitment": "confirmed",
                "minContextSlot": min_context_slot,
            },
        ],
    )
    supply_result = _rpc(
        url,
        "getTokenSupply",
        [
            lp_mint,
            {"commitment": "confirmed", "minContextSlot": min_context_slot},
        ],
    )
    return _lp_account_state_from_results(
        lp_mint,
        lp_account,
        info_result,
        supply_result,
        min_context_slot=min_context_slot,
    )


def _build_fixture(url: str, specimen: Mapping[str, Any]) -> dict[str, Any]:
    tx = _rpc(
        url,
        "getTransaction",
        [
            specimen["signature"],
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
                "commitment": "confirmed",
            },
        ],
    )
    tx = _validate_transaction(tx, specimen)
    pool_account = _resolve_pool(url, tx, specimen["base_mint"])
    manifest_pool = specimen.get("expected_pool")
    if manifest_pool is not None and manifest_pool != pool_account["address"]:
        raise SpecimenFetchError("resolved pool does not match the manifest")

    recorded = specimen["recorded_evidence"]
    lp_states: list[dict[str, Any]] = []
    if recorded.get("lp_mint") is not None:
        lp_states.append(
            _lp_account_state(
                url,
                recorded["lp_mint"],
                recorded["lp_account"],
                min_context_slot=tx["slot"],
            )
        )

    return {
        "name": specimen["name"],
        "signature": specimen["signature"],
        "slot": specimen["slot"],
        "base_mint": specimen["base_mint"],
        "expected_verdict": specimen["expected_verdict"],
        "expected_pool": pool_account["address"],
        "pool_account": pool_account,
        "recorded_evidence": dict(recorded),
        "transaction": tx,
        "lp_account_states": lp_states,
    }


def _atomic_write_fixtures(fixtures: list[dict[str, Any]]) -> None:
    """Stage all files and roll back earlier replacements after an I/O failure."""
    _RAW_DIR.mkdir(parents=True, exist_ok=True)
    if not isinstance(fixtures, list) or not fixtures:
        raise SpecimenFetchError("fixture set must be a non-empty list")
    names: list[str] = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise SpecimenFetchError("fixture must be an object")
        name = fixture.get("name")
        if not isinstance(name, str) or _SAFE_NAME.fullmatch(name) is None:
            raise SpecimenFetchError("fixture has an unsafe name")
        names.append(name)
    if len(names) != len(set(names)):
        raise SpecimenFetchError("fixture names must be unique")

    staged: list[tuple[Path, Path]] = []
    backups: dict[Path, Path | None] = {}
    replaced: list[Path] = []
    try:
        for fixture in fixtures:
            target = _RAW_DIR / f"{fixture['name']}.json"
            descriptor, temporary_name = tempfile.mkstemp(
                dir=_RAW_DIR,
                prefix=f".{fixture['name']}.",
                suffix=".tmp",
                text=True,
            )
            temporary = Path(temporary_name)
            staged.append((temporary, target))
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(fixture, handle, indent=1, ensure_ascii=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

        for _, target in staged:
            if not target.exists():
                backups[target] = None
                continue
            descriptor, backup_name = tempfile.mkstemp(
                dir=_RAW_DIR,
                prefix=f".{target.stem}.",
                suffix=".bak",
            )
            os.close(descriptor)
            backup = Path(backup_name)
            backups[target] = backup
            shutil.copyfile(target, backup)
            with backup.open("rb+") as handle:
                os.fsync(handle.fileno())

        for temporary, target in staged:
            os.replace(temporary, target)
            replaced.append(target)
    except BaseException:
        rollback_failed = False
        for target in reversed(replaced):
            backup = backups.get(target)
            try:
                if backup is None:
                    target.unlink()
                else:
                    os.replace(backup, target)
            except (OSError, FileNotFoundError):
                rollback_failed = True
        if rollback_failed:
            raise SpecimenFetchError("fixture replacement and rollback both failed") from None
        raise
    finally:
        for temporary, _ in staged:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        for backup in backups.values():
            if backup is None:
                continue
            try:
                backup.unlink()
            except FileNotFoundError:
                pass


def main() -> int:
    url = os.environ.get("RPC_URL")
    if not isinstance(url, str) or not url.strip():
        print("Set RPC_URL to a Solana RPC endpoint (mainnet).", file=sys.stderr)
        return 2

    try:
        manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
        specimens = _validate_manifest(manifest)
    except Exception as exc:
        if isinstance(exc, SpecimenFetchError):
            message = str(exc)
        else:
            message = f"manifest could not be loaded ({type(exc).__name__})"
        print(message, file=sys.stderr)
        return 2

    fixtures: list[dict[str, Any]] = []
    failed = False
    for specimen in specimens:
        name = specimen["name"]
        try:
            fixture = _build_fixture(url, specimen)
        except Exception as exc:
            if isinstance(exc, SpecimenFetchError):
                message = str(exc)
            else:
                # Unexpected exceptions can also carry urllib request objects.
                message = f"unexpected fetch failure ({type(exc).__name__})"
            print(f"  {name}: {message}", file=sys.stderr)
            failed = True
            continue
        fixtures.append(fixture)
        print(
            f"  {name}: validated (pool={fixture['expected_pool']})"
        )

    if failed or len(fixtures) != len(specimens):
        print("No fixtures written because acquisition was incomplete.", file=sys.stderr)
        return 1

    try:
        _atomic_write_fixtures(fixtures)
    except Exception as exc:
        print(
            f"Fixture write failed ({type(exc).__name__}); no endpoint was recorded.",
            file=sys.stderr,
        )
        return 1

    for fixture in fixtures:
        out = _RAW_DIR / f"{fixture['name']}.json"
        print(f"  {fixture['name']}: wrote {out.relative_to(_ROOT)}")
    print("Done. Run: python -m unittest tests.test_specimens -v")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
