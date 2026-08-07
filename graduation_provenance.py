"""Authenticate pump.fun migration provenance from offline Solana evidence.

The verifier in this module establishes one narrow fact: a successful,
supported pump.fun migration instruction created the supplied PumpSwap pool.
It authenticates the pool account, decodes ordered instruction roles, and
checks liquidity and LP-destruction operations inside the migration frame.

A match is not a safety judgement and is not a trading recommendation.  The
module makes no network calls.  Parsed transaction data, a PumpSwap-owned pool
account snapshot, and LP account/supply state are supplied by the caller.
Malformed, missing, ambiguous, unsupported, or inconsistent evidence fails
closed as ``MIGRATION_EVIDENCE_NOT_ESTABLISHED``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import base58

from pumpswap_decoder import PoolDecodeError, PoolState, decode_pool_b64

__all__ = [
    "PUMP_FUN_PROGRAMS",
    "PUMPSWAP_AMM_PROGRAM",
    "SPL_TOKEN_PROGRAMS",
    "WSOL_MINT",
    "MIGRATION_SOL_MIN",
    "EVIDENCE_MATCHED",
    "EVIDENCE_NOT_ESTABLISHED",
    "MigrationContext",
    "PoolAccountEvidence",
    "LpAccountState",
    "MigrationEvidenceVerdict",
    "build_evidence",
    "verify_migration_evidence",
    "propose_migration_context",
    "screen_pool",
]

PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
# The alternate address is recognised as pump.fun presence, but this module
# does not apply the 6EF8 account layouts to it without a validating specimen.
PUMP_FUN_PROGRAMS = frozenset(
    {PUMP_FUN_PROGRAM, "FAdo9NCw1ssek6Z6yeWzWjhLVsr8uiCwcWNUnKgzTnHe"}
)
PUMPSWAP_AMM_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
SPL_TOKEN_PROGRAMS = frozenset({TOKEN_PROGRAM, TOKEN_2022_PROGRAM})
WSOL_MINT = "So11111111111111111111111111111111111111112"

SYSTEM_PROGRAM = "11111111111111111111111111111111"
ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
RENT_SYSVAR = "SysvarRent111111111111111111111111111111111"
PUMPSWAP_EVENT_AUTHORITY = "GS4CU59F31iL7aR2Q8zVS8DRrcRnXX1yjQ66TqNVQnaR"
PUMPSWAP_GLOBAL = "ADyA8hdefvWN2dbGGWFotbzWxrAvLW83WG6QCVXvJKqw"
PUMP_GLOBAL = "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf"
PUMP_EVENT_AUTHORITY = "Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1"

MIGRATE_DISCRIMINATOR = bytes.fromhex("9beae792ec9ea21e")
MIGRATE_V2_DISCRIMINATOR = bytes.fromhex("bbcb121fceedfe29")
CREATE_POOL_DISCRIMINATOR = bytes.fromhex("e992d18ecf6840bc")

MIGRATION_SOL_MIN = 80.0
_LAMPORTS_PER_SOL = 1_000_000_000
_MIGRATION_SOL_MIN_LAMPORTS = 80 * _LAMPORTS_PER_SOL
_MAJOR_SOL_DEBIT_LAMPORTS = 1 * _LAMPORTS_PER_SOL
_U64_MAX = (1 << 64) - 1

EVIDENCE_MATCHED = "BOUND_MIGRATION_EVIDENCE"
EVIDENCE_NOT_ESTABLISHED = "MIGRATION_EVIDENCE_NOT_ESTABLISHED"


@dataclass(frozen=True)
class MigrationContext:
    """Concrete roles for one decoded CreatePool invocation.

    ``base_source`` is the bonding curve's base-token account and
    ``sol_source`` is the bonding-curve account whose lamport debit funds the
    migration. ``base_destination`` / ``sol_destination`` are the authenticated
    pool's token and WSOL vaults. Temporary CreatePool inputs are decoded from
    the migration frame rather than exposed as caller-selected roles.
    """

    expected_pool: str
    lp_mint: str
    lp_account: str
    base_source: str
    base_destination: str
    sol_source: str
    sol_destination: str


@dataclass(frozen=True)
class PoolAccountEvidence:
    """Caller-supplied raw pool-account snapshot and RPC ownership metadata."""

    address: str
    owner: str
    data_base64: str
    context_slot: int


@dataclass(frozen=True)
class LpAccountState:
    """Caller-supplied state for the LP destination and mint supply."""

    lp_mint: str
    destination: str
    destination_closed: bool
    lp_supply_zero: bool


@dataclass(frozen=True)
class MigrationEvidenceVerdict:
    verdict: str
    failed_check: Optional[str]
    evidence: dict[str, Any]

    @property
    def is_match(self) -> bool:
        return self.verdict == EVIDENCE_MATCHED


def _is_nonempty_string(value: Any) -> bool:
    return type(value) is str and bool(value) and value == value.strip()


def _is_pubkey(value: Any) -> bool:
    if not _is_nonempty_string(value) or not (32 <= len(value) <= 44):
        return False
    try:
        decoded = base58.b58decode(value)
    except (TypeError, ValueError):
        return False
    return len(decoded) == 32 and base58.b58encode(decoded).decode("ascii") == value


def _parse_u64_string(value: Any, *, positive: bool = False) -> Optional[int]:
    if (
        type(value) is not str
        or not value
        or len(value) > 20
        or not value.isascii()
        or not value.isdecimal()
    ):
        return None
    parsed = int(value)
    if value != str(parsed) or parsed > _U64_MAX:
        return None
    if positive and parsed == 0:
        return None
    return parsed


def _snapshot_json(value: Any, *, depth: int = 0) -> Any:
    """Copy a plain JSON value while rejecting subclasses, cycles, and NaN."""
    if depth > 100:
        raise ValueError("JSON nesting is too deep")
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return value
    if type(value) is list:
        return [_snapshot_json(item, depth=depth + 1) for item in value]
    if type(value) is dict:
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("non-string JSON object key")
            copied[key] = _snapshot_json(item, depth=depth + 1)
        return copied
    raise ValueError("input is not plain JSON")


def _snapshot_context(value: Any) -> Optional[MigrationContext]:
    if type(value) is not MigrationContext:
        return None
    try:
        return MigrationContext(
            value.expected_pool,
            value.lp_mint,
            value.lp_account,
            value.base_source,
            value.base_destination,
            value.sol_source,
            value.sol_destination,
        )
    except Exception:
        return None


def _snapshot_pool_account(value: Any) -> Optional[PoolAccountEvidence]:
    if type(value) is not PoolAccountEvidence:
        return None
    try:
        return PoolAccountEvidence(
            value.address, value.owner, value.data_base64, value.context_slot
        )
    except Exception:
        return None


def _context_is_valid(context: Optional[MigrationContext], base_mint: Any) -> bool:
    if context is None or not _is_pubkey(base_mint) or base_mint == WSOL_MINT:
        return False
    fields = (
        context.expected_pool,
        context.lp_mint,
        context.lp_account,
        context.base_source,
        context.base_destination,
        context.sol_source,
        context.sol_destination,
    )
    if not all(_is_pubkey(value) for value in fields):
        return False
    if context.lp_mint in (base_mint, WSOL_MINT):
        return False
    return len(set(fields + (base_mint, WSOL_MINT))) == len(fields) + 2


def _pool_account_is_valid(value: Optional[PoolAccountEvidence]) -> bool:
    return bool(
        value is not None
        and _is_pubkey(value.address)
        and value.owner == PUMPSWAP_AMM_PROGRAM
        and type(value.data_base64) is str
        and bool(value.data_base64)
        and type(value.context_slot) is int
        and 0 <= value.context_slot <= _U64_MAX
    )


def _normalise_pubkey(value: Any) -> Optional[str]:
    if type(value) is dict:
        value = value.get("pubkey")
    return value if _is_pubkey(value) else None


def _sequence(
    container: dict[str, Any], key: str, *, none_is_empty: bool = False
) -> Optional[list[Any]]:
    value = container.get(key)
    if value is None and none_is_empty:
        return []
    return value if type(value) is list else None


def _transaction_parts(
    tx: Any,
) -> tuple[
    Optional[dict[str, Any]],
    Optional[dict[str, Any]],
    Optional[int],
    Optional[str],
]:
    if type(tx) is not dict:
        return None, None, None, "tx_not_dict"
    slot = tx.get("slot")
    if type(slot) is not int or not (0 <= slot <= _U64_MAX):
        return None, None, None, "invalid_transaction_slot"
    transaction = tx.get("transaction")
    if type(transaction) is not dict:
        return None, None, None, "transaction_not_dict"
    message = transaction.get("message")
    if type(message) is not dict:
        return None, None, None, "message_not_dict"
    meta = tx.get("meta")
    if type(meta) is not dict:
        return None, None, None, "meta_not_dict"
    if "err" not in meta:
        return None, None, None, "meta_err_missing"
    return message, meta, slot, None


def _account_keys(
    message: dict[str, Any], meta: dict[str, Any]
) -> tuple[list[str], Optional[str]]:
    static = _sequence(message, "accountKeys")
    if static is None:
        return [], "account_keys_not_list"
    keys: list[str] = []
    for raw in static:
        key = _normalise_pubkey(raw)
        if key is None:
            return [], "invalid_static_account_key"
        keys.append(key)

    loaded = meta.get("loadedAddresses")
    if loaded is not None:
        if type(loaded) is not dict:
            return [], "loaded_addresses_not_dict"
        for bucket in ("writable", "readonly"):
            raw_bucket = loaded.get(bucket, [])
            if type(raw_bucket) is not list:
                return [], f"loaded_{bucket}_not_list"
            for raw in raw_bucket:
                key = _normalise_pubkey(raw)
                if key is None:
                    return [], f"invalid_loaded_{bucket}_key"
                keys.append(key)
    if not keys:
        return [], "account_keys_empty"
    if len(keys) != len(set(keys)):
        return [], "duplicate_account_key"
    return keys, None


def _resolve_account_reference(value: Any, keys: list[str]) -> Optional[str]:
    if type(value) is int:
        return keys[value] if 0 <= value < len(keys) else None
    key = _normalise_pubkey(value)
    return key if key in set(keys) else None


def _decode_instruction(
    raw: Any, keys: list[str]
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    if type(raw) is not dict:
        return None, "instruction_not_dict"
    explicit = "programId" in raw
    indexed = "programIdIndex" in raw
    if explicit == indexed:
        return None, "program_id_missing_or_conflicting"

    if explicit:
        program_id = _normalise_pubkey(raw.get("programId"))
        if program_id is None or program_id not in set(keys):
            return None, "invalid_program_id"
    else:
        program_id = _resolve_account_reference(raw.get("programIdIndex"), keys)
        if program_id is None:
            return None, "invalid_program_id_index"

    if "parsed" in raw:
        if not explicit:
            return None, "parsed_instruction_requires_program_id"
        if not _is_nonempty_string(raw.get("program")):
            return None, "parsed_instruction_program_missing"
        if program_id in SPL_TOKEN_PROGRAMS and raw.get("program") not in {
            "spl-token",
            "spl-token-2022",
        }:
            return None, "parsed_spl_program_label_inconsistent"
        if type(raw.get("parsed")) is not dict:
            return None, "parsed_instruction_payload_not_dict"
        if "accounts" in raw or "data" in raw:
            return None, "mixed_instruction_encoding"
        return {
            "program_id": program_id,
            "accounts": (),
            "data": None,
            "parsed": raw["parsed"],
            "raw": raw,
        }, None

    raw_accounts = raw.get("accounts")
    if type(raw_accounts) is not list:
        return None, "instruction_accounts_not_list"
    data_text = raw.get("data")
    if type(data_text) is not str:
        return None, "invalid_instruction_data"
    try:
        data = base58.b58decode(data_text)
    except (TypeError, ValueError):
        return None, "invalid_instruction_data"
    if base58.b58encode(data).decode("ascii") != data_text:
        return None, "noncanonical_instruction_data"

    accounts: list[str] = []
    for raw_account in raw_accounts:
        if explicit and type(raw_account) is not str:
            return None, "mixed_instruction_account_encoding"
        if indexed and type(raw_account) is not int:
            return None, "mixed_instruction_account_encoding"
        account = _resolve_account_reference(raw_account, keys)
        if account is None:
            return None, "invalid_instruction_account"
        accounts.append(account)
    return {
        "program_id": program_id,
        "accounts": tuple(accounts),
        "data": data,
        "parsed": None,
        "raw": raw,
    }, None


def _instruction_groups(
    message: dict[str, Any], meta: dict[str, Any], keys: list[str]
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]], Optional[str]]:
    raw_outer = _sequence(message, "instructions")
    if raw_outer is None:
        return [], {}, "outer_instructions_not_list"
    outer: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_outer):
        decoded, error = _decode_instruction(raw, keys)
        if error:
            return [], {}, error
        stack_height = raw.get("stackHeight")
        if stack_height is not None and (
            type(stack_height) is not int or stack_height != 1
        ):
            return [], {}, "invalid_outer_stack_height"
        assert decoded is not None
        decoded.update(
            {
                "outer_index": index,
                "position": -1,
                "stack_height": 1,
                "parent_position": None,
                "ancestors": (),
            }
        )
        outer.append(decoded)

    raw_groups = _sequence(meta, "innerInstructions", none_is_empty=True)
    if raw_groups is None:
        return [], {}, "inner_instruction_groups_not_list"
    groups: dict[int, list[dict[str, Any]]] = {}
    for raw_group in raw_groups:
        if type(raw_group) is not dict:
            return [], {}, "inner_instruction_group_not_dict"
        index = raw_group.get("index")
        if type(index) is not int or not (0 <= index < len(outer)):
            return [], {}, "invalid_inner_instruction_index"
        if index in groups:
            return [], {}, "duplicate_inner_instruction_index"
        raw_instructions = _sequence(raw_group, "instructions")
        if raw_instructions is None:
            return [], {}, "inner_instructions_not_list"

        decoded_group: list[dict[str, Any]] = []
        stack: dict[int, dict[str, Any]] = {1: outer[index]}
        previous_height = 1
        for position, raw in enumerate(raw_instructions):
            decoded, error = _decode_instruction(raw, keys)
            if error:
                return [], {}, error
            stack_height = raw.get("stackHeight")
            if (
                type(stack_height) is not int
                or stack_height < 2
                or stack_height > previous_height + 1
            ):
                return [], {}, "invalid_inner_stack_height"
            parent = stack.get(stack_height - 1)
            if parent is None:
                return [], {}, "missing_stack_parent"
            for height in tuple(stack):
                if height >= stack_height:
                    del stack[height]
            assert decoded is not None
            decoded.update(
                {
                    "outer_index": index,
                    "position": position,
                    "stack_height": stack_height,
                    "parent_position": parent["position"],
                    "ancestors": parent["ancestors"] + (parent["position"],),
                }
            )
            decoded_group.append(decoded)
            stack[stack_height] = decoded
            previous_height = stack_height
        groups[index] = decoded_group
    return outer, groups, None


def _prepare_transaction(
    tx: Any,
) -> tuple[
    Optional[dict[str, Any]],
    Optional[dict[str, Any]],
    Optional[dict[str, Any]],
    Optional[int],
    list[str],
    list[dict[str, Any]],
    dict[int, list[dict[str, Any]]],
    Optional[str],
]:
    try:
        snapshot = _snapshot_json(tx)
    except Exception:
        return None, None, None, None, [], [], {}, "input_not_plain_json"
    message, meta, slot, error = _transaction_parts(snapshot)
    if error:
        return snapshot, None, None, None, [], [], {}, error
    assert message is not None and meta is not None and slot is not None
    keys, error = _account_keys(message, meta)
    if error:
        return snapshot, message, meta, slot, [], [], {}, error
    outer, groups, error = _instruction_groups(message, meta, keys)
    return snapshot, message, meta, slot, keys, outer, groups, error


def _decode_authenticated_pool(
    evidence: PoolAccountEvidence,
    expected_pool: str,
    base_mint: str,
    transaction_slot: int,
) -> Optional[PoolState]:
    if evidence.address != expected_pool or evidence.context_slot < transaction_slot:
        return None
    try:
        state = decode_pool_b64(evidence.data_base64, owner=evidence.owner)
    except (PoolDecodeError, TypeError, ValueError):
        return None
    return state if state.token_mint == base_mint else None


def _parse_create_pool(node: dict[str, Any]) -> Optional[dict[str, Any]]:
    data = node["data"]
    accounts = node["accounts"]
    if (
        node["program_id"] != PUMPSWAP_AMM_PROGRAM
        or type(data) is not bytes
        or len(data) != 60
        or data[:8] != CREATE_POOL_DISCRIMINATOR
        or len(accounts) != 18
        or data[58] not in (0, 1)
        or data[59] not in (0, 1)
    ):
        return None
    return {
        "accounts": accounts,
        "index": int.from_bytes(data[8:10], "little"),
        "base_amount": int.from_bytes(data[10:18], "little"),
        "quote_amount": int.from_bytes(data[18:26], "little"),
        "coin_creator": base58.b58encode(data[26:58]).decode("ascii"),
        "is_mayhem_mode": bool(data[58]),
        "is_cashback_coin": bool(data[59]),
    }


def _create_pool_matches_state(
    parsed: dict[str, Any], state: PoolState, expected_pool: str
) -> bool:
    accounts = parsed["accounts"]
    return bool(
        state.base_mint == state.token_mint
        and state.quote_mint == WSOL_MINT
        and accounts[0] == expected_pool
        and accounts[1] == PUMPSWAP_GLOBAL
        and accounts[2] == state.creator
        and accounts[3] == state.base_mint
        and accounts[4] == state.quote_mint
        and accounts[5] == state.lp_mint
        and accounts[9] == state.base_vault
        and accounts[10] == state.quote_vault
        and accounts[11] == SYSTEM_PROGRAM
        and accounts[12] == TOKEN_2022_PROGRAM
        and accounts[13] in SPL_TOKEN_PROGRAMS
        and accounts[14] in SPL_TOKEN_PROGRAMS
        and accounts[15] == ASSOCIATED_TOKEN_PROGRAM
        and accounts[16] == PUMPSWAP_EVENT_AUTHORITY
        and accounts[17] == PUMPSWAP_AMM_PROGRAM
        and parsed["index"] == state.index
        and parsed["coin_creator"] == state.coin_creator
        and parsed["is_mayhem_mode"] == state.is_mayhem_mode
        and parsed["is_cashback_coin"] == state.is_cashback_coin
    )


def _context_from_create_pool(
    parsed: dict[str, Any], state: PoolState, roles: dict[str, Any]
) -> MigrationContext:
    accounts = parsed["accounts"]
    return MigrationContext(
        expected_pool=accounts[0],
        lp_mint=accounts[5],
        lp_account=accounts[8],
        base_source=roles["base_curve_account"],
        base_destination=state.token_vault,
        sol_source=roles["base_curve"],
        sol_destination=state.sol_vault,
    )


def _migration_role_map(
    migration: dict[str, Any], create_pool: dict[str, Any]
) -> Optional[dict[str, Any]]:
    if migration["program_id"] != PUMP_FUN_PROGRAM or type(migration["data"]) is not bytes:
        return None
    accounts = migration["accounts"]
    cp = create_pool["accounts"]
    data = migration["data"]
    if data == MIGRATE_V2_DISCRIMINATOR and len(accounts) == 27:
        required = {
            0: PUMP_GLOBAL, 2: cp[3], 3: cp[4], 8: SYSTEM_PROGRAM,
            9: PUMPSWAP_AMM_PROGRAM,
            10: cp[0], 11: cp[2], 12: cp[6], 13: cp[7], 14: cp[1],
            15: cp[5], 16: cp[8], 17: cp[9], 18: cp[10], 19: cp[13],
            20: cp[14], 21: TOKEN_2022_PROGRAM, 22: ASSOCIATED_TOKEN_PROGRAM,
            23: cp[16], 24: RENT_SYSVAR, 25: PUMP_EVENT_AUTHORITY,
            26: PUMP_FUN_PROGRAM,
        }
        if any(accounts[index] != value for index, value in required.items()):
            return None
        return {
            "variant": "migrate_v2",
            "base_curve": accounts[4],
            "base_curve_account": accounts[5],
            "migration_authority": accounts[1],
        }
    if data == MIGRATE_DISCRIMINATOR and len(accounts) == 25:
        required = {
            0: PUMP_GLOBAL, 2: cp[3], 5: create_pool["coin_creator"],
            6: SYSTEM_PROGRAM, 7: cp[13],
            8: PUMPSWAP_AMM_PROGRAM,
            9: cp[0], 10: cp[2], 11: cp[6], 12: cp[7], 13: cp[1],
            14: WSOL_MINT, 15: cp[5], 16: cp[8], 17: cp[9], 18: cp[10],
            19: TOKEN_2022_PROGRAM, 20: ASSOCIATED_TOKEN_PROGRAM, 21: cp[16],
            22: PUMP_EVENT_AUTHORITY, 23: PUMP_FUN_PROGRAM, 24: RENT_SYSVAR,
        }
        if cp[3] == WSOL_MINT or cp[4] != WSOL_MINT or cp[13] != cp[14]:
            return None
        if any(accounts[index] != value for index, value in required.items()):
            return None
        return {
            "variant": "migrate",
            "base_curve": accounts[3],
            "base_curve_account": accounts[4],
            "migration_authority": accounts[1],
        }
    return None


def _candidate_frames(
    outer: list[dict[str, Any]],
    groups: dict[int, list[dict[str, Any]]],
    state: PoolState,
    expected_pool: str,
    context: Optional[MigrationContext],
) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for outer_index, outer_node in enumerate(outer):
        nodes = groups.get(outer_index, [])
        possible_migrations = [outer_node] + nodes
        for migration in possible_migrations:
            if migration["program_id"] != PUMP_FUN_PROGRAM:
                continue
            for create_node in nodes:
                if create_node["parent_position"] != migration["position"]:
                    continue
                create_pool = _parse_create_pool(create_node)
                if create_pool is None or not _create_pool_matches_state(
                    create_pool, state, expected_pool
                ):
                    continue
                roles = _migration_role_map(migration, create_pool)
                if roles is None:
                    continue
                derived = _context_from_create_pool(create_pool, state, roles)
                if context is not None and derived != context:
                    continue
                frames.append(
                    {
                        "outer_index": outer_index,
                        "migration": migration,
                        "create_node": create_node,
                        "create_pool": create_pool,
                        "roles": roles,
                        "context": derived,
                        "nodes": nodes,
                    }
                )
    return frames


def _parsed_info(node: dict[str, Any], operation_type: str) -> Optional[dict[str, Any]]:
    parsed = node.get("parsed")
    if type(parsed) is not dict or parsed.get("type") != operation_type:
        return None
    info = parsed.get("info")
    return info if type(info) is dict else None


def _token_amount(info: dict[str, Any], *, checked: bool) -> Optional[int]:
    if checked:
        token_amount = info.get("tokenAmount")
        if type(token_amount) is not dict:
            return None
        decimals = token_amount.get("decimals")
        if type(decimals) is not int or not (0 <= decimals <= 255):
            return None
        return _parse_u64_string(token_amount.get("amount"), positive=True)
    return _parse_u64_string(info.get("amount"), positive=True)


def _bound_token_operation_is_valid(node: dict[str, Any]) -> bool:
    if node["program_id"] not in SPL_TOKEN_PROGRAMS:
        return True
    parsed = node.get("parsed")
    if type(parsed) is not dict:
        return True
    operation = parsed.get("type")
    if operation not in ("transferChecked", "mintTo", "burn", "syncNative", "closeAccount"):
        return True
    info = parsed.get("info")
    if type(info) is not dict:
        return False
    if operation == "transferChecked":
        return bool(
            all(_is_pubkey(info.get(key)) for key in ("source", "destination", "mint", "authority"))
            and _token_amount(info, checked=True) is not None
        )
    if operation == "mintTo":
        has_account = "account" in info
        has_destination = "destination" in info
        if has_account == has_destination:
            return False
        account = info.get("account") if has_account else info.get("destination")
        return bool(
            _is_pubkey(info.get("mint"))
            and _is_pubkey(account)
            and _is_pubkey(info.get("mintAuthority"))
            and _token_amount(info, checked=False) is not None
        )
    if operation == "burn":
        return bool(
            all(_is_pubkey(info.get(key)) for key in ("mint", "account", "authority"))
            and _token_amount(info, checked=False) is not None
        )
    if operation == "syncNative":
        return _is_pubkey(info.get("account"))
    return all(
        _is_pubkey(info.get(key)) for key in ("account", "destination", "owner")
    )


def _is_direct_child(node: dict[str, Any], parent: dict[str, Any]) -> bool:
    return (
        node["outer_index"] == parent["outer_index"]
        and node["parent_position"] == parent["position"]
    )


def _matching_transfer(
    node: dict[str, Any],
    *,
    parent: dict[str, Any],
    program_id: str,
    source: str,
    destination: str,
    mint: str,
    authority: str,
    amount: int,
) -> bool:
    if node["program_id"] != program_id or not _is_direct_child(node, parent):
        return False
    info = _parsed_info(node, "transferChecked")
    return bool(
        info is not None
        and info.get("source") == source
        and info.get("destination") == destination
        and info.get("mint") == mint
        and info.get("authority") == authority
        and _token_amount(info, checked=True) == amount
    )


def _sol_balance_summary(
    meta: dict[str, Any], keys: list[str]
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    raw_pre = _sequence(meta, "preBalances")
    raw_post = _sequence(meta, "postBalances")
    if raw_pre is None or raw_post is None:
        return None, "sol_balances_not_list"
    if len(raw_pre) != len(keys) or len(raw_post) != len(keys):
        return None, "sol_balance_length_mismatch"
    if any(type(value) is not int or not (0 <= value <= _U64_MAX) for value in raw_pre):
        return None, "invalid_pre_balance"
    if any(type(value) is not int or not (0 <= value <= _U64_MAX) for value in raw_post):
        return None, "invalid_post_balance"

    debits = {
        account: raw_pre[index] - raw_post[index]
        for index, account in enumerate(keys)
    }
    major = [
        {
            "account": account,
            "debit_lamports": debit,
            "debit_sol": debit / _LAMPORTS_PER_SOL,
        }
        for account, debit in debits.items()
        if debit >= _MAJOR_SOL_DEBIT_LAMPORTS
    ]
    major.sort(key=lambda row: row["debit_lamports"], reverse=True)
    return {"debits": debits, "major_sol_debits": major}, None


def _frame_operations(
    frame: dict[str, Any], sol_balance_summary: dict[str, Any]
) -> dict[str, Any]:
    migration = frame["migration"]
    create_node = frame["create_node"]
    cp = frame["create_pool"]
    roles = frame["roles"]
    nodes = frame["nodes"]
    accounts = cp["accounts"]
    curve_debit = sol_balance_summary["debits"].get(roles["base_curve"], 0)

    migration_descendants = [
        node for node in nodes if migration["position"] in node["ancestors"]
    ]
    invalid_operations = sum(
        not _bound_token_operation_is_valid(node) for node in migration_descendants
    )

    pre_base = [
        node
        for node in nodes
        if node["position"] < create_node["position"]
        and _matching_transfer(
            node,
            parent=migration,
            program_id=accounts[13],
            source=roles["base_curve_account"],
            destination=accounts[6],
            mint=accounts[3],
            authority=roles["base_curve"],
            amount=cp["base_amount"],
        )
    ]
    sync_native = []
    for node in nodes:
        if node["position"] >= create_node["position"]:
            continue
        info = _parsed_info(node, "syncNative")
        if (
            node["program_id"] == accounts[14]
            and _is_direct_child(node, migration)
            and info is not None
            and info.get("account") == accounts[7]
        ):
            sync_native.append(node)

    base_transfers = [
        node
        for node in nodes
        if _matching_transfer(
            node,
            parent=create_node,
            program_id=accounts[13],
            source=accounts[6],
            destination=accounts[9],
            mint=accounts[3],
            authority=accounts[2],
            amount=cp["base_amount"],
        )
    ]
    quote_transfers = [
        node
        for node in nodes
        if _matching_transfer(
            node,
            parent=create_node,
            program_id=accounts[14],
            source=accounts[7],
            destination=accounts[10],
            mint=accounts[4],
            authority=accounts[2],
            amount=cp["quote_amount"],
        )
    ]

    mint_tos: list[tuple[dict[str, Any], int]] = []
    for node in nodes:
        if node["program_id"] != accounts[12] or not _is_direct_child(node, create_node):
            continue
        info = _parsed_info(node, "mintTo")
        if info is None:
            continue
        has_account = "account" in info
        has_destination = "destination" in info
        account = (
            info.get("account")
            if has_account and not has_destination
            else info.get("destination")
            if has_destination and not has_account
            else None
        )
        amount = _token_amount(info, checked=False)
        if (
            info.get("mint") == accounts[5]
            and account == accounts[8]
            and info.get("mintAuthority") == accounts[0]
            and amount is not None
        ):
            mint_tos.append((node, amount))

    lp_matches: list[dict[str, Any]] = []
    close_matches: list[dict[str, Any]] = []
    if len(mint_tos) == 1:
        mint_node, minted_amount = mint_tos[0]
        burns: list[dict[str, Any]] = []
        for node in nodes:
            if (
                node["position"] <= mint_node["position"]
                or node["program_id"] != accounts[12]
                or not _is_direct_child(node, migration)
            ):
                continue
            info = _parsed_info(node, "burn")
            if (
                info is not None
                and info.get("mint") == accounts[5]
                and info.get("account") == accounts[8]
                and info.get("authority") == accounts[2]
                and _token_amount(info, checked=False) == minted_amount
            ):
                burns.append(node)
        if len(burns) == 1:
            burn_node = burns[0]
            lp_matches.append(
                {
                    "mint": accounts[5],
                    "account": accounts[8],
                    "amount": str(minted_amount),
                    "outer_index": frame["outer_index"],
                }
            )
            for node in nodes:
                if (
                    node["position"] <= burn_node["position"]
                    or node["program_id"] != accounts[12]
                    or not _is_direct_child(node, migration)
                ):
                    continue
                info = _parsed_info(node, "closeAccount")
                if (
                    info is not None
                    and info.get("account") == accounts[8]
                    and info.get("destination") == roles["migration_authority"]
                    and info.get("owner") == accounts[2]
                ):
                    close_matches.append(node)

    return {
        "migration_variant": roles["variant"],
        "base_amount": cp["base_amount"],
        "quote_amount_lamports": cp["quote_amount"],
        "quote_amount_sol": cp["quote_amount"] / _LAMPORTS_PER_SOL,
        "bound_curve_debit_lamports": curve_debit,
        "bound_curve_debit_sol": curve_debit / _LAMPORTS_PER_SOL,
        "pre_create_base_transfer_count": len(pre_base),
        "pre_create_sync_native_count": len(sync_native),
        "create_pool_base_transfer_count": len(base_transfers),
        "create_pool_quote_transfer_count": len(quote_transfers),
        "lp_mint_to_count": len(mint_tos),
        "matching_lp_mint_to_burn": lp_matches,
        "lp_close_count": len(close_matches),
        "invalid_bound_operation_count": invalid_operations,
        "base_migration_flow": len(pre_base) == 1 and len(base_transfers) == 1,
        "wsol_migration_flow": (
            len(sync_native) == 1
            and len(quote_transfers) == 1
            and cp["quote_amount"] >= _MIGRATION_SOL_MIN_LAMPORTS
            and curve_debit >= _MIGRATION_SOL_MIN_LAMPORTS
            and curve_debit >= cp["quote_amount"]
        ),
        "lp_destroyed_in_frame": len(lp_matches) == 1 and len(close_matches) == 1,
    }


def _lp_account_proof(
    lp_account_states: Any,
    context: MigrationContext,
    lp_matches: list[dict[str, Any]],
) -> tuple[bool, bool, bool]:
    if lp_account_states is None:
        return False, False, False
    try:
        raw_states = list(lp_account_states)
    except Exception:
        return False, False, True
    if not raw_states:
        return False, False, False
    states: list[LpAccountState] = []
    for value in raw_states:
        if type(value) is not LpAccountState:
            return False, True, True
        try:
            state = LpAccountState(
                value.lp_mint,
                value.destination,
                value.destination_closed,
                value.lp_supply_zero,
            )
        except Exception:
            return False, True, True
        if (
            not _is_pubkey(state.lp_mint)
            or not _is_pubkey(state.destination)
            or type(state.destination_closed) is not bool
            or type(state.lp_supply_zero) is not bool
        ):
            return False, True, True
        states.append(state)
    matching = [
        state
        for state in states
        if state.lp_mint == context.lp_mint and state.destination == context.lp_account
    ]
    if len(matching) != 1 or len(lp_matches) != 1:
        return False, True, False
    state = matching[0]
    operation = lp_matches[0]
    matches_operation = (
        operation["mint"] == state.lp_mint
        and operation["account"] == state.destination
    )
    return bool(
        state.destination_closed is True
        and state.lp_supply_zero is True
        and matches_operation
    ), True, False


def _base_evidence(base_mint: Any, context: Optional[MigrationContext]) -> dict[str, Any]:
    context_view = None
    if context is not None:
        context_view = {
            "expected_pool": context.expected_pool,
            "lp_mint": context.lp_mint,
            "lp_account": context.lp_account,
            "base_source": context.base_source,
            "base_destination": context.base_destination,
            "sol_source": context.sol_source,
            "sol_destination": context.sol_destination,
        }
    return {
        "base_mint": base_mint,
        "context": context_view,
        "well_formed_transaction": False,
        "malformed_reason": None,
        "transaction_succeeded": False,
        "base_mint_valid": _is_pubkey(base_mint) and base_mint != WSOL_MINT,
        "context_valid": _context_is_valid(context, base_mint),
        "pool_account_valid": False,
        "pool_authenticated": False,
        "pool_state": None,
        "context_accounts_present": False,
        "has_pump_fun_program": False,
        "has_pumpswap_amm": False,
        "migration_frame_count": 0,
        "migration_frames": [],
        "migration_operations": {
            "base_migration_flow": False,
            "wsol_migration_flow": False,
            "matching_lp_mint_to_burn": [],
            "lp_destroyed_in_frame": False,
            "invalid_bound_operation_count": 0,
        },
        "major_sol_debits": [],
        "lp_account_proof": False,
        "lp_account_states_supplied": False,
        "lp_account_states_invalid": False,
    }


def build_evidence(
    tx: Any,
    base_mint: Any,
    context: Any,
    lp_account_states: Optional[Iterable[LpAccountState]] = None,
    pool_account: Optional[PoolAccountEvidence] = None,
) -> dict[str, Any]:
    """Build authenticated migration evidence without performing I/O."""
    context_snapshot = _snapshot_context(context)
    pool_snapshot = _snapshot_pool_account(pool_account)
    evidence = _base_evidence(base_mint, context_snapshot)
    try:
        (
            _tx_snapshot,
            _message,
            meta,
            transaction_slot,
            keys,
            outer,
            groups,
            error,
        ) = _prepare_transaction(tx)
        if error:
            evidence["malformed_reason"] = error
            return evidence
        assert meta is not None and transaction_slot is not None
        evidence["well_formed_transaction"] = True
        evidence["transaction_succeeded"] = meta.get("err") is None
        programs = {node["program_id"] for node in outer}
        programs.update(node["program_id"] for group in groups.values() for node in group)
        evidence["has_pump_fun_program"] = bool(programs & PUMP_FUN_PROGRAMS)
        evidence["has_pumpswap_amm"] = PUMPSWAP_AMM_PROGRAM in programs

        sol_balance_summary, balance_error = _sol_balance_summary(meta, keys)
        if balance_error:
            evidence["well_formed_transaction"] = False
            evidence["malformed_reason"] = balance_error
            return evidence
        assert sol_balance_summary is not None
        evidence["major_sol_debits"] = sol_balance_summary["major_sol_debits"]

        evidence["pool_account_valid"] = _pool_account_is_valid(pool_snapshot)
        if (
            not evidence["base_mint_valid"]
            or not evidence["context_valid"]
            or not evidence["pool_account_valid"]
        ):
            return evidence
        assert context_snapshot is not None and pool_snapshot is not None
        assert type(base_mint) is str
        state = _decode_authenticated_pool(
            pool_snapshot,
            context_snapshot.expected_pool,
            base_mint,
            transaction_slot,
        )
        if state is None:
            return evidence
        evidence["pool_authenticated"] = True
        evidence["pool_state"] = {
            "address": pool_snapshot.address,
            "context_slot": pool_snapshot.context_slot,
            "creator": state.creator,
            "base_mint": state.base_mint,
            "quote_mint": state.quote_mint,
            "lp_mint": state.lp_mint,
            "base_vault": state.base_vault,
            "quote_vault": state.quote_vault,
            "token_mint": state.token_mint,
            "token_vault": state.token_vault,
            "sol_vault": state.sol_vault,
        }
        required_accounts = set(context_snapshot.__dict__.values()) | {base_mint, WSOL_MINT}
        evidence["context_accounts_present"] = required_accounts.issubset(set(keys))
        if not evidence["context_accounts_present"]:
            return evidence

        frames = _candidate_frames(
            outer, groups, state, context_snapshot.expected_pool, context_snapshot
        )
        evidence["migration_frame_count"] = len(frames)
        evidence["migration_frames"] = [
            {
                "outer_index": frame["outer_index"],
                "migration_position": frame["migration"]["position"],
                "create_pool_position": frame["create_node"]["position"],
                "migration_variant": frame["roles"]["variant"],
            }
            for frame in frames
        ]
        if len(frames) != 1:
            return evidence
        operations = _frame_operations(frames[0], sol_balance_summary)
        evidence["migration_operations"] = operations
        proof, supplied, invalid = _lp_account_proof(
            lp_account_states,
            context_snapshot,
            operations["matching_lp_mint_to_burn"],
        )
        evidence["lp_account_proof"] = proof
        evidence["lp_account_states_supplied"] = supplied
        evidence["lp_account_states_invalid"] = invalid
        return evidence
    except Exception:
        evidence["well_formed_transaction"] = False
        evidence["malformed_reason"] = "unexpected_input_error"
        return evidence


_CHECKS = (
    ("transaction_shape", lambda e: e["well_formed_transaction"]),
    ("transaction_succeeded", lambda e: e["transaction_succeeded"]),
    ("base_mint", lambda e: e["base_mint_valid"]),
    ("migration_context", lambda e: e["context_valid"]),
    ("pool_account", lambda e: e["pool_account_valid"]),
    ("pool_authenticated", lambda e: e["pool_authenticated"]),
    ("context_accounts", lambda e: e["context_accounts_present"]),
    ("pump_fun_program", lambda e: e["has_pump_fun_program"]),
    ("pumpswap_amm", lambda e: e["has_pumpswap_amm"]),
    ("migration_create_pool_binding", lambda e: e["migration_frame_count"] == 1),
    (
        "migration_operations_well_formed",
        lambda e: e["migration_operations"]["invalid_bound_operation_count"] == 0,
    ),
    (
        "base_mint_migrated",
        lambda e: e["migration_operations"]["base_migration_flow"],
    ),
    ("migration_sol_flow", lambda e: e["migration_operations"]["wsol_migration_flow"]),
    (
        "lp_mint_and_burn",
        lambda e: len(e["migration_operations"]["matching_lp_mint_to_burn"]) == 1,
    ),
    ("lp_account_closed_in_frame", lambda e: e["migration_operations"]["lp_destroyed_in_frame"]),
    ("lp_account_closed_supply_zero", lambda e: e["lp_account_proof"]),
)


def verify_migration_evidence(
    tx: Any,
    base_mint: Any,
    context: Any,
    lp_account_states: Optional[Iterable[LpAccountState]] = None,
    pool_account: Optional[PoolAccountEvidence] = None,
) -> MigrationEvidenceVerdict:
    """Evaluate the pool-authenticated migration predicate for one context."""
    evidence = build_evidence(
        tx, base_mint, context, lp_account_states, pool_account
    )
    for name, predicate in _CHECKS:
        if not predicate(evidence):
            return MigrationEvidenceVerdict(EVIDENCE_NOT_ESTABLISHED, name, evidence)
    return MigrationEvidenceVerdict(EVIDENCE_MATCHED, None, evidence)


def _propose_from_prepared(
    tx: Any,
    expected_pool: Any,
    base_mint: Any,
    pool_account: Any,
) -> tuple[Optional[MigrationContext], Optional[str]]:
    if not _is_pubkey(expected_pool) or not _is_pubkey(base_mint) or base_mint == WSOL_MINT:
        return None, "invalid_pool_or_base_mint"
    pool_snapshot = _snapshot_pool_account(pool_account)
    if not _pool_account_is_valid(pool_snapshot):
        return None, "pool_account_invalid"
    (
        _tx_snapshot,
        _message,
        _meta,
        transaction_slot,
        _keys,
        outer,
        groups,
        error,
    ) = _prepare_transaction(tx)
    if error:
        return None, error
    assert pool_snapshot is not None and transaction_slot is not None
    state = _decode_authenticated_pool(
        pool_snapshot, expected_pool, base_mint, transaction_slot
    )
    if state is None:
        return None, "pool_not_authenticated"
    frames = _candidate_frames(outer, groups, state, expected_pool, None)
    contexts = {frame["context"] for frame in frames}
    if len(frames) != 1 or len(contexts) != 1:
        return None, "migration_frame_not_unique" if frames else "migration_frame_not_found"
    context = next(iter(contexts))
    if not _context_is_valid(context, base_mint):
        return None, "derived_context_invalid"
    return context, None


def propose_migration_context(
    tx: Any,
    expected_pool: Any,
    base_mint: Any,
    pool_account: Optional[PoolAccountEvidence] = None,
) -> tuple[Optional[MigrationContext], Optional[str]]:
    """Derive CreatePool roles only after authenticating the supplied pool."""
    try:
        return _propose_from_prepared(tx, expected_pool, base_mint, pool_account)
    except Exception:
        return None, "unexpected_input_error"


def screen_pool(
    tx: Any,
    expected_pool: Any,
    base_mint: Any,
    lp_account_states: Optional[Iterable[LpAccountState]] = None,
    pool_account: Optional[PoolAccountEvidence] = None,
) -> MigrationEvidenceVerdict:
    """Authenticate a pool, derive its transaction roles, then delegate."""
    try:
        tx_snapshot = _snapshot_json(tx)
    except Exception:
        tx_snapshot = None
    pool_snapshot = _snapshot_pool_account(pool_account)
    context, reason = propose_migration_context(
        tx_snapshot, expected_pool, base_mint, pool_snapshot
    )
    if context is None:
        return MigrationEvidenceVerdict(
            EVIDENCE_NOT_ESTABLISHED,
            f"derive:{reason}",
            {
                "base_mint": base_mint,
                "expected_pool": expected_pool,
                "derive_reason": reason,
            },
        )
    return verify_migration_evidence(
        tx_snapshot,
        base_mint,
        context,
        lp_account_states,
        pool_snapshot,
    )
