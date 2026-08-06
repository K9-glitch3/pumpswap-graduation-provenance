"""Evaluate strict, pool-bound pump.fun migration evidence offline.

The public predicate in this module is deliberately narrower than an
authenticity classifier.  It returns ``BOUND_MIGRATION_EVIDENCE`` only when one
specific pump.fun outer instruction, its indexed inner-instruction group, the
named accounts' balance changes, and caller-supplied LP closure evidence all
agree with an explicit :class:`MigrationContext`.

That result means only that this strict evidence pattern matched.  It does not
prove canonical pool creation, validate a transaction against a live corpus,
make a safety judgement, or recommend a trade.  Any missing, malformed,
ambiguous, failed, or unbound evidence returns
``MIGRATION_EVIDENCE_NOT_ESTABLISHED``.

The module makes no network calls.  The caller obtains the parsed
``getTransaction`` response and the LP account/mint state independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

__all__ = [
    "PUMP_FUN_PROGRAMS",
    "PUMPSWAP_AMM_PROGRAM",
    "SPL_TOKEN_PROGRAMS",
    "WSOL_MINT",
    "MIGRATION_SOL_MIN",
    "EVIDENCE_MATCHED",
    "EVIDENCE_NOT_ESTABLISHED",
    "MigrationContext",
    "MigrationEvidenceVerdict",
    "LpAccountState",
    "verify_migration_evidence",
    "build_evidence",
    "propose_migration_context",
    "screen_pool",
]

PUMP_FUN_PROGRAMS = frozenset(
    {
        "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
        "FAdo9NCw1ssek6Z6yeWzWjhLVsr8uiCwcWNUnKgzTnHe",
    }
)
PUMPSWAP_AMM_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
SPL_TOKEN_PROGRAMS = frozenset(
    {
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    }
)
_SPL_TOKEN_PROGRAM_NAMES = {
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA": "spl-token",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb": "spl-token-2022",
}
WSOL_MINT = "So11111111111111111111111111111111111111112"

MIGRATION_SOL_MIN = 80.0
_LAMPORTS_PER_SOL = 1_000_000_000
_MIGRATION_SOL_MIN_LAMPORTS = 80 * _LAMPORTS_PER_SOL
_MAJOR_SOL_DEBIT_LAMPORTS = 1 * _LAMPORTS_PER_SOL
_U64_MAX = (1 << 64) - 1
_BASE58_ALPHABET = frozenset(
    "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
)

EVIDENCE_MATCHED = "BOUND_MIGRATION_EVIDENCE"
EVIDENCE_NOT_ESTABLISHED = "MIGRATION_EVIDENCE_NOT_ESTABLISHED"


@dataclass(frozen=True)
class MigrationContext:
    """Caller-known account identities for the pool under examination.

    ``base_source`` and ``base_destination`` are token accounts for
    ``base_mint``. ``sol_source`` and ``sol_destination`` bind the lamport
    transfer. These identities are requirements, not values the verifier
    guesses from whichever transaction-wide deltas are largest.
    """

    expected_pool: str
    lp_mint: str
    lp_account: str
    base_source: str
    base_destination: str
    sol_source: str
    sol_destination: str


@dataclass(frozen=True)
class LpAccountState:
    """Caller-supplied RPC evidence about the bound LP position."""

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
    if any(character not in _BASE58_ALPHABET for character in value):
        return False

    number = 0
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    for character in value:
        number = number * 58 + alphabet.index(character)
    payload_bytes = (number.bit_length() + 7) // 8
    leading_zero_bytes = len(value) - len(value.lstrip("1"))
    return payload_bytes + leading_zero_bytes == 32


def _parse_u64_string(value: Any, *, positive: bool) -> Optional[int]:
    if (
        type(value) is not str
        or not value
        or not value.isascii()
        or not value.isdecimal()
    ):
        return None
    parsed = int(value)
    if value != str(parsed) or parsed > _U64_MAX:
        return None
    if positive:
        return parsed if parsed > 0 else None
    return parsed if parsed >= 0 else None


def _normalise_pubkey(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        value = value.get("pubkey")
    return value if _is_pubkey(value) else None


def _sequence(container: dict[str, Any], key: str, *, none_is_empty: bool = False) -> Optional[list[Any]]:
    value = container.get(key)
    if value is None and none_is_empty:
        return []
    return value if isinstance(value, list) else None


def _transaction_parts(
    tx: Any,
) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]], Optional[str]]:
    if not isinstance(tx, dict):
        return None, None, "tx_not_dict"
    transaction = tx.get("transaction")
    if not isinstance(transaction, dict):
        return None, None, "transaction_not_dict"
    message = transaction.get("message")
    if not isinstance(message, dict):
        return None, None, "message_not_dict"
    meta = tx.get("meta")
    if not isinstance(meta, dict):
        return None, None, "meta_not_dict"
    if "err" not in meta:
        return None, None, "meta_err_missing"
    return message, meta, None


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
        if not isinstance(loaded, dict):
            return [], "loaded_addresses_not_dict"
        for bucket in ("writable", "readonly"):
            raw_bucket = loaded.get(bucket, [])
            if not isinstance(raw_bucket, list):
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
    if not isinstance(raw, dict):
        return None, "instruction_not_dict"

    has_explicit_program_id = "programId" in raw
    has_indexed_program_id = "programIdIndex" in raw
    if has_explicit_program_id and has_indexed_program_id:
        return None, "inconsistent_program_id_encoding"

    explicit_program_id: Optional[str] = None
    indexed_program_id: Optional[str] = None
    if has_explicit_program_id:
        explicit_program_id = _normalise_pubkey(raw.get("programId"))
        if explicit_program_id is None or explicit_program_id not in set(keys):
            return None, "invalid_program_id"
    if has_indexed_program_id:
        indexed_program_id = _resolve_account_reference(
            raw.get("programIdIndex"), keys
        )
        if indexed_program_id is None:
            return None, "invalid_program_id_index"
    if explicit_program_id is None and indexed_program_id is None:
        return None, "program_id_missing"
    program_id = explicit_program_id or indexed_program_id
    assert program_id is not None

    is_parsed = "parsed" in raw
    if is_parsed:
        if explicit_program_id is None:
            return None, "parsed_instruction_requires_program_id"
        if not _is_nonempty_string(raw.get("program")):
            return None, "parsed_instruction_program_missing"
        if not isinstance(raw.get("parsed"), dict):
            return None, "parsed_instruction_payload_not_dict"
        if "accounts" in raw or "data" in raw:
            return None, "mixed_instruction_encoding"
        return {
            "program_id": program_id,
            "accounts": frozenset(),
            "data": None,
            "is_parsed": True,
            "raw": raw,
        }, None

    if "accounts" not in raw:
        return None, "instruction_accounts_missing"
    raw_accounts = raw.get("accounts")
    if not isinstance(raw_accounts, list):
        return None, "instruction_accounts_not_list"
    data = raw.get("data")
    if type(data) is not str or any(
        character not in _BASE58_ALPHABET for character in data
    ):
        return None, "invalid_instruction_data"
    accounts: list[str] = []
    for raw_account in raw_accounts:
        if explicit_program_id is not None and type(raw_account) is not str:
            return None, "mixed_instruction_account_encoding"
        if indexed_program_id is not None and type(raw_account) is not int:
            return None, "mixed_instruction_account_encoding"
        account = _resolve_account_reference(raw_account, keys)
        if account is None:
            return None, "invalid_instruction_account"
        accounts.append(account)

    return {
        "program_id": program_id,
        "accounts": frozenset(accounts),
        "data": data,
        "is_parsed": False,
        "raw": raw,
    }, None


def _instruction_groups(
    message: dict[str, Any], meta: dict[str, Any], keys: list[str]
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]], Optional[str]]:
    raw_outer = _sequence(message, "instructions")
    if raw_outer is None:
        return [], {}, "outer_instructions_not_list"
    outer: list[dict[str, Any]] = []
    for raw in raw_outer:
        decoded, error = _decode_instruction(raw, keys)
        if error:
            return [], {}, error
        stack_height = raw.get("stackHeight")
        if stack_height is not None and (
            type(stack_height) is not int or stack_height != 1
        ):
            return [], {}, "invalid_outer_stack_height"
        outer.append(decoded or {})

    raw_groups = _sequence(meta, "innerInstructions", none_is_empty=True)
    if raw_groups is None:
        return [], {}, "inner_instruction_groups_not_list"
    groups: dict[int, list[dict[str, Any]]] = {}
    for raw_group in raw_groups:
        if not isinstance(raw_group, dict):
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
        previous_stack_height = 1
        for raw in raw_instructions:
            decoded, error = _decode_instruction(raw, keys)
            if error:
                return [], {}, error
            stack_height = raw.get("stackHeight")
            if (
                type(stack_height) is not int
                or stack_height < 2
                or stack_height > previous_stack_height + 1
            ):
                return [], {}, "invalid_inner_stack_height"
            previous_stack_height = stack_height
            decoded_group.append(decoded or {})
        groups[index] = decoded_group
    return outer, groups, None


def _context_is_valid(context: Any, base_mint: Any) -> bool:
    if not _is_pubkey(base_mint) or base_mint == WSOL_MINT:
        return False
    if not isinstance(context, MigrationContext):
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
    if context.base_source == context.base_destination:
        return False
    if context.lp_mint in (base_mint, WSOL_MINT):
        return False
    # Role collisions shrink the required-account sets and weaken the binding.
    # All named roles are therefore distinct; callers must name the concrete
    # token account and SOL source separately even when controlled by one PDA.
    return len(set(fields + (base_mint,))) == len(fields) + 1


def _bound_migration_groups(
    outer: list[dict[str, Any]],
    groups: dict[int, list[dict[str, Any]]],
    context: MigrationContext,
    base_mint: str,
) -> list[tuple[int, list[dict[str, Any]], int]]:
    bound_accounts = {
        context.expected_pool,
        base_mint,
        context.lp_mint,
        context.lp_account,
        context.base_source,
        context.base_destination,
        context.sol_source,
        context.sol_destination,
    }
    matches: list[tuple[int, list[dict[str, Any]], int]] = []
    for index, instruction in enumerate(outer):
        if instruction["program_id"] not in PUMP_FUN_PROGRAMS:
            continue
        if not instruction["data"]:
            continue
        if not bound_accounts.issubset(instruction["accounts"]):
            continue
        inner = groups.get(index, [])
        pumpswap_positions = [
            position
            for position, inner_instruction in enumerate(inner)
            if inner_instruction["program_id"] == PUMPSWAP_AMM_PROGRAM
            and bool(inner_instruction["data"])
            and bound_accounts.issubset(inner_instruction["accounts"])
        ]
        if len(pumpswap_positions) == 1:
            pumpswap_position = pumpswap_positions[0]
            after_pumpswap = inner[pumpswap_position + 1 :]
            pump_stack_height = inner[pumpswap_position]["raw"].get("stackHeight")
            if type(pump_stack_height) is not int or pump_stack_height < 1:
                continue
            descendant_limit = len(after_pumpswap)
            for offset, later_instruction in enumerate(after_pumpswap):
                later_height = later_instruction["raw"].get("stackHeight")
                if type(later_height) is not int or later_height < 1:
                    descendant_limit = 0
                    break
                if later_height <= pump_stack_height:
                    descendant_limit = offset
                    break
            matches.append((index, after_pumpswap, descendant_limit))
    return matches


def _token_balance_map(
    rows: list[Any], keys: list[str]
) -> tuple[dict[tuple[int, str], int], Optional[str]]:
    balances: dict[tuple[int, str], int] = {}
    account_indexes: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            return {}, "token_balance_not_dict"
        index = row.get("accountIndex")
        if type(index) is not int or not (0 <= index < len(keys)):
            return {}, "invalid_token_account_index"
        if index in account_indexes:
            return {}, "duplicate_token_account_index"
        account_indexes.add(index)
        mint = row.get("mint")
        if not _is_pubkey(mint):
            return {}, "invalid_token_mint"
        ui_amount = row.get("uiTokenAmount")
        if not isinstance(ui_amount, dict) or "amount" not in ui_amount:
            return {}, "token_amount_missing"
        amount = _parse_u64_string(ui_amount.get("amount"), positive=False)
        if amount is None:
            return {}, "invalid_token_amount"
        key = (index, mint)
        if key in balances:
            return {}, "duplicate_token_balance"
        balances[key] = amount
    return balances, None


def _token_flow(
    meta: dict[str, Any], keys: list[str], base_mint: str, context: MigrationContext
) -> tuple[dict[str, Any], Optional[str]]:
    raw_pre = _sequence(meta, "preTokenBalances", none_is_empty=True)
    raw_post = _sequence(meta, "postTokenBalances", none_is_empty=True)
    if raw_pre is None or raw_post is None:
        return {}, "token_balances_not_list"
    pre, error = _token_balance_map(raw_pre, keys)
    if error:
        return {}, error
    post, error = _token_balance_map(raw_post, keys)
    if error:
        return {}, error

    source_index = keys.index(context.base_source)
    destination_index = keys.index(context.base_destination)
    source_key = (source_index, base_mint)
    destination_key = (destination_index, base_mint)
    source_delta = post.get(source_key, 0) - pre.get(source_key, 0)
    destination_delta = post.get(destination_key, 0) - pre.get(destination_key, 0)
    return {
        "base_source": context.base_source,
        "base_destination": context.base_destination,
        "source_delta": source_delta,
        "destination_delta": destination_delta,
        "bound_negative_flow": source_delta < 0,
        "bound_positive_flow": destination_delta > 0,
        "bound_balanced_flow": source_delta < 0
        and destination_delta > 0
        and -source_delta == destination_delta,
    }, None


def _sol_flow(
    meta: dict[str, Any], keys: list[str], context: MigrationContext
) -> tuple[dict[str, Any], Optional[str]]:
    raw_pre = _sequence(meta, "preBalances")
    raw_post = _sequence(meta, "postBalances")
    if raw_pre is None or raw_post is None:
        return {}, "sol_balances_not_list"
    if len(raw_pre) != len(keys) or len(raw_post) != len(keys):
        return {}, "sol_balance_length_mismatch"

    pre: list[int] = []
    post: list[int] = []
    for value in raw_pre:
        if type(value) is not int or not (0 <= value <= _U64_MAX):
            return {}, "invalid_pre_balance"
        pre.append(value)
    for value in raw_post:
        if type(value) is not int or not (0 <= value <= _U64_MAX):
            return {}, "invalid_post_balance"
        post.append(value)

    major_debits: list[dict[str, Any]] = []
    for index, (before, after) in enumerate(zip(pre, post)):
        debit = before - after
        if debit >= _MAJOR_SOL_DEBIT_LAMPORTS:
            major_debits.append(
                {
                    "account": keys[index],
                    "debit_lamports": debit,
                    "debit_sol": debit / _LAMPORTS_PER_SOL,
                }
            )
    major_debits.sort(key=lambda row: row["debit_lamports"], reverse=True)

    source_index = keys.index(context.sol_source)
    destination_index = keys.index(context.sol_destination)
    source_debit = pre[source_index] - post[source_index]
    destination_credit = post[destination_index] - pre[destination_index]
    has_bound_flow = (
        source_debit >= _MIGRATION_SOL_MIN_LAMPORTS
        and source_debit == destination_credit
    )
    return {
        "major_sol_debits": major_debits,
        "sol_source": context.sol_source,
        "sol_destination": context.sol_destination,
        "sol_source_debit_lamports": source_debit,
        "sol_destination_credit_lamports": destination_credit,
        "has_large_migration_sol_debit": source_debit >= _MIGRATION_SOL_MIN_LAMPORTS,
        "has_bound_migration_sol_flow": has_bound_flow,
    }, None


def _lp_amount(info: dict[str, Any]) -> Optional[str]:
    raw_amount = info.get("amount")
    amount = _parse_u64_string(raw_amount, positive=True)
    return str(amount) if amount is not None else None


def _lp_ops(
    bound_groups: list[
        tuple[int, list[dict[str, Any]], int]
    ],
    context: MigrationContext,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    invalid_bound_operations = 0
    for group_index, instructions, descendant_limit in bound_groups:
        mint_to: list[tuple[int, str, str, str, bool]] = []
        burns: list[tuple[int, str, str, str, bool]] = []
        for operation_index, instruction in enumerate(instructions):
            parsed = instruction["raw"].get("parsed")
            if not isinstance(parsed, dict) or parsed.get("type") not in ("mintTo", "burn"):
                continue
            if instruction["program_id"] not in SPL_TOKEN_PROGRAMS:
                continue
            if instruction["raw"].get("program") != _SPL_TOKEN_PROGRAM_NAMES[
                instruction["program_id"]
            ]:
                invalid_bound_operations += 1
                continue
            operation_stack_height = instruction["raw"].get("stackHeight")
            if type(operation_stack_height) is not int or operation_stack_height < 1:
                invalid_bound_operations += 1
                continue
            info = parsed.get("info")
            if not isinstance(info, dict):
                invalid_bound_operations += 1
                continue
            mint = info.get("mint")
            raw_account = info.get("account")
            raw_destination = info.get("destination")
            if (
                raw_account is not None
                and raw_destination is not None
                and raw_account != raw_destination
            ):
                invalid_bound_operations += 1
                continue
            account = raw_account or raw_destination
            amount = _lp_amount(info)
            if not _is_pubkey(mint) or not _is_pubkey(account):
                invalid_bound_operations += 1
                continue
            if amount is None:
                invalid_bound_operations += 1
                continue
            if mint != context.lp_mint or account != context.lp_account:
                continue
            if parsed["type"] == "mintTo":
                is_pumpswap_descendant = operation_index < descendant_limit
                mint_to.append(
                    (
                        operation_index,
                        mint,
                        account,
                        amount,
                        is_pumpswap_descendant,
                    )
                )
            else:
                burns.append(
                    (
                        operation_index,
                        mint,
                        account,
                        amount,
                        operation_index < descendant_limit,
                    )
                )

        for minted in mint_to:
            for burned in burns:
                if (
                    minted[4]
                    and burned[4]
                    and minted[0] < burned[0]
                    and minted[1:4] == burned[1:4]
                ):
                    matches.append(
                        {
                            "group_index": group_index,
                            "mint": minted[1],
                            "account": minted[2],
                            "amount": minted[3],
                        }
                    )
    return {
        "matching_bound_mint_to_burn": matches,
        "invalid_bound_operation_count": invalid_bound_operations,
    }


def _lp_account_proof(
    matches: list[dict[str, Any]],
    lp_account_states: Any,
    context: MigrationContext,
) -> tuple[bool, bool]:
    if lp_account_states is None:
        return False, False
    try:
        states = list(lp_account_states)
    except (TypeError, RuntimeError):
        return False, False

    if not states:
        return False, False

    matching_states: list[LpAccountState] = []
    for state in states:
        if not isinstance(state, LpAccountState):
            return False, True
        if not _is_pubkey(state.lp_mint) or not _is_pubkey(state.destination):
            return False, True
        if type(state.destination_closed) is not bool or type(state.lp_supply_zero) is not bool:
            return False, True
        if state.lp_mint == context.lp_mint and state.destination == context.lp_account:
            matching_states.append(state)

    if len(matching_states) != 1:
        return False, True
    state = matching_states[0]
    proof_matches_operation = any(
        match["mint"] == state.lp_mint and match["account"] == state.destination
        for match in matches
    )
    return (
        state.destination_closed is True
        and state.lp_supply_zero is True
        and proof_matches_operation,
        True,
    )


def _base_evidence(base_mint: Any, context: Any) -> dict[str, Any]:
    context_view = None
    if isinstance(context, MigrationContext):
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
        "context_accounts_present": False,
        "has_pump_fun_program": False,
        "has_pumpswap_amm": False,
        "bound_migration_group_indexes": [],
        "sol_flow": {
            "major_sol_debits": [],
            "has_large_migration_sol_debit": False,
            "has_bound_migration_sol_flow": False,
        },
        "token_flow": {
            "bound_negative_flow": False,
            "bound_positive_flow": False,
            "bound_balanced_flow": False,
        },
        "lp_ops": {"matching_bound_mint_to_burn": [], "invalid_bound_operation_count": 0},
        "lp_account_proof": False,
        "lp_account_states_supplied": False,
    }


def build_evidence(
    tx: Any,
    base_mint: Any,
    context: Any,
    lp_account_states: Optional[Iterable[LpAccountState]] = None,
) -> dict[str, Any]:
    """Build strict evidence without I/O; malformed inputs are represented, not raised."""
    evidence = _base_evidence(base_mint, None)
    try:
        evidence = _base_evidence(base_mint, context)
        message, meta, error = _transaction_parts(tx)
        if error:
            evidence["malformed_reason"] = error
            return evidence
        assert message is not None and meta is not None

        keys, error = _account_keys(message, meta)
        if error:
            evidence["malformed_reason"] = error
            return evidence
        outer, groups, error = _instruction_groups(message, meta, keys)
        if error:
            evidence["malformed_reason"] = error
            return evidence

        evidence["transaction_succeeded"] = meta.get("err") is None
        programs = {instruction["program_id"] for instruction in outer}
        programs.update(
            instruction["program_id"]
            for instructions in groups.values()
            for instruction in instructions
        )
        evidence["has_pump_fun_program"] = bool(programs & PUMP_FUN_PROGRAMS)
        evidence["has_pumpswap_amm"] = PUMPSWAP_AMM_PROGRAM in programs

        if not evidence["base_mint_valid"] or not evidence["context_valid"]:
            evidence["well_formed_transaction"] = True
            return evidence
        assert isinstance(context, MigrationContext) and isinstance(base_mint, str)
        required_accounts = {
            context.expected_pool,
            context.lp_mint,
            context.lp_account,
            context.base_source,
            context.base_destination,
            context.sol_source,
            context.sol_destination,
            base_mint,
        }
        evidence["context_accounts_present"] = required_accounts.issubset(set(keys))
        if not evidence["context_accounts_present"]:
            evidence["well_formed_transaction"] = True
            return evidence

        bound_groups = _bound_migration_groups(outer, groups, context, base_mint)
        evidence["bound_migration_group_indexes"] = [
            index for index, _, _ in bound_groups
        ]

        sol_flow, error = _sol_flow(meta, keys, context)
        if error:
            evidence["malformed_reason"] = error
            return evidence
        token_flow, error = _token_flow(meta, keys, base_mint, context)
        if error:
            evidence["malformed_reason"] = error
            return evidence
        evidence["sol_flow"] = sol_flow
        evidence["token_flow"] = token_flow

        lp_ops = _lp_ops(bound_groups, context)
        evidence["lp_ops"] = lp_ops
        proof, supplied = _lp_account_proof(
            lp_ops["matching_bound_mint_to_burn"], lp_account_states, context
        )
        evidence["lp_account_proof"] = proof
        evidence["lp_account_states_supplied"] = supplied
        evidence["well_formed_transaction"] = True
        return evidence
    except Exception:
        # Arbitrary user-controlled container subclasses or iterators must not
        # escape the fail-closed boundary.
        evidence["malformed_reason"] = "unexpected_input_error"
        return evidence


_CHECKS = (
    ("transaction_shape", lambda e: e["well_formed_transaction"]),
    ("transaction_succeeded", lambda e: e["transaction_succeeded"]),
    ("base_mint", lambda e: e["base_mint_valid"]),
    ("migration_context", lambda e: e["context_valid"]),
    ("context_accounts", lambda e: e["context_accounts_present"]),
    ("pump_fun_program", lambda e: e["has_pump_fun_program"]),
    ("pumpswap_amm", lambda e: e["has_pumpswap_amm"]),
    (
        "bound_migration_instruction_group",
        lambda e: len(e["bound_migration_group_indexes"]) == 1,
    ),
    (
        "migration_sol_flow",
        lambda e: e["sol_flow"]["has_bound_migration_sol_flow"],
    ),
    (
        "base_mint_migrated",
        lambda e: e["token_flow"]["bound_balanced_flow"],
    ),
    (
        "lp_mint_and_burn",
        lambda e: e["lp_ops"]["invalid_bound_operation_count"] == 0
        and len(e["lp_ops"]["matching_bound_mint_to_burn"]) == 1,
    ),
    ("lp_account_closed_supply_zero", lambda e: e["lp_account_proof"]),
)


def verify_migration_evidence(
    tx: Any,
    base_mint: Any,
    context: Any,
    lp_account_states: Optional[Iterable[LpAccountState]] = None,
) -> MigrationEvidenceVerdict:
    """Evaluate the strict evidence predicate for one explicitly bound pool."""
    evidence = build_evidence(tx, base_mint, context, lp_account_states)
    for name, predicate in _CHECKS:
        if not predicate(evidence):
            return MigrationEvidenceVerdict(EVIDENCE_NOT_ESTABLISHED, name, evidence)
    return MigrationEvidenceVerdict(EVIDENCE_MATCHED, None, evidence)


# --------------------------------------------------------------------------
# Convenience: derive a candidate context, then verify it.
#
# ``verify_migration_evidence`` requires the caller to name every migration
# account up front. That is correct for the strict check, but a screener
# examining an unknown pool does not yet know the LP mint, the LP token account,
# the base-token source/destination, or the SOL source/destination — those live
# inside the migration transaction. It only knows the two facts you have from
# the pool account itself: the pool address and its non-WSOL mint.
#
# ``propose_migration_context`` derives the remaining accounts *structurally*
# from the transaction (the LP mint/burn pair, the two base-mint balance moves,
# the large bound SOL debit and its matching credit) and refuses when any role
# is ambiguous. It does not rank by magnitude and then hope: the proposal is
# only a candidate. ``screen_pool`` passes that candidate straight into
# ``verify_migration_evidence``, which re-binds and re-checks the whole
# structure and fails closed if the derivation was wrong. A wrong proposal
# cannot produce a match.
# --------------------------------------------------------------------------


def _unique(values: list[str]) -> Optional[str]:
    """Return the single distinct value, or None if there are zero or several."""
    distinct = set(values)
    return next(iter(distinct)) if len(distinct) == 1 else None


def _derive_lp_pair(
    outer: list[dict[str, Any]],
    groups: dict[int, list[dict[str, Any]]],
    base_mint: str,
) -> tuple[Optional[tuple[str, str]], Optional[str]]:
    """Find the single LP (mint, account) minted then burned under a pump.fun group."""
    pairs: set[tuple[str, str]] = set()
    for index, instruction in enumerate(outer):
        if instruction["program_id"] not in PUMP_FUN_PROGRAMS:
            continue
        inner = groups.get(index, [])
        mint_to: dict[tuple[str, str], set[str]] = {}
        burns: dict[tuple[str, str], set[str]] = {}
        for inner_instruction in inner:
            if inner_instruction["program_id"] not in SPL_TOKEN_PROGRAMS:
                continue
            parsed = inner_instruction["raw"].get("parsed")
            if not isinstance(parsed, dict) or parsed.get("type") not in ("mintTo", "burn"):
                continue
            info = parsed.get("info")
            if not isinstance(info, dict):
                continue
            mint = info.get("mint")
            account = info.get("account") or info.get("destination")
            amount = _lp_amount(info)
            if not _is_pubkey(mint) or not _is_pubkey(account) or amount is None:
                continue
            if mint in (base_mint, WSOL_MINT):
                continue
            bucket = mint_to if parsed["type"] == "mintTo" else burns
            bucket.setdefault((mint, account), set()).add(amount)
        for key, minted_amounts in mint_to.items():
            if key in burns and minted_amounts & burns[key]:
                pairs.add(key)
    if len(pairs) != 1:
        return None, "lp_pair_not_unique" if pairs else "lp_pair_not_found"
    return next(iter(pairs)), None


def _derive_base_flow(
    meta: dict[str, Any], keys: list[str], base_mint: str
) -> tuple[Optional[tuple[str, str]], Optional[str]]:
    """Find the single base-token account debited and the single one credited."""
    raw_pre = _sequence(meta, "preTokenBalances", none_is_empty=True)
    raw_post = _sequence(meta, "postTokenBalances", none_is_empty=True)
    if raw_pre is None or raw_post is None:
        return None, "token_balances_not_list"
    pre, error = _token_balance_map(raw_pre, keys)
    if error:
        return None, error
    post, error = _token_balance_map(raw_post, keys)
    if error:
        return None, error
    indexes = {index for (index, mint) in pre if mint == base_mint}
    indexes |= {index for (index, mint) in post if mint == base_mint}
    sources: list[str] = []
    destinations: list[str] = []
    for index in indexes:
        delta = post.get((index, base_mint), 0) - pre.get((index, base_mint), 0)
        if delta < 0:
            sources.append(keys[index])
        elif delta > 0:
            destinations.append(keys[index])
    if len(sources) != 1 or len(destinations) != 1:
        return None, "base_flow_not_unique"
    return (sources[0], destinations[0]), None


def _derive_sol_flow(
    meta: dict[str, Any], keys: list[str]
) -> tuple[Optional[tuple[str, str]], Optional[str]]:
    """Find the single account debited >= the migration floor and its matching credit."""
    raw_pre = _sequence(meta, "preBalances")
    raw_post = _sequence(meta, "postBalances")
    if raw_pre is None or raw_post is None:
        return None, "sol_balances_not_list"
    if len(raw_pre) != len(keys) or len(raw_post) != len(keys):
        return None, "sol_balance_length_mismatch"
    if any(type(v) is not int or not (0 <= v <= _U64_MAX) for v in raw_pre + raw_post):
        return None, "invalid_sol_balance"
    sources: list[tuple[str, int]] = []
    for index in range(len(keys)):
        debit = raw_pre[index] - raw_post[index]
        if debit >= _MIGRATION_SOL_MIN_LAMPORTS:
            sources.append((keys[index], debit))
    if len(sources) != 1:
        return None, "sol_source_not_unique"
    sol_source, debit = sources[0]
    destinations = [
        keys[index]
        for index in range(len(keys))
        if raw_post[index] - raw_pre[index] == debit
    ]
    if len(destinations) != 1:
        return None, "sol_destination_not_unique"
    return (sol_source, destinations[0]), None


def propose_migration_context(
    tx: Any, expected_pool: Any, base_mint: Any
) -> tuple[Optional[MigrationContext], Optional[str]]:
    """Derive a candidate ``MigrationContext`` from a pool's creation transaction.

    ``expected_pool`` and ``base_mint`` are the two identities a screener already
    has (the pool being examined and its non-WSOL mint). The LP mint/account and
    the base-token and SOL source/destination accounts are derived from the
    transaction structure. Returns ``(context, None)`` on success or
    ``(None, reason)`` when the transaction is malformed or any role is
    ambiguous. The returned context is a candidate for
    ``verify_migration_evidence``; it is not itself a verdict.
    """
    if not _is_pubkey(expected_pool) or not _is_pubkey(base_mint) or base_mint == WSOL_MINT:
        return None, "invalid_pool_or_base_mint"
    try:
        message, meta, error = _transaction_parts(tx)
        if error:
            return None, error
        assert message is not None and meta is not None
        keys, error = _account_keys(message, meta)
        if error:
            return None, error
        if expected_pool not in set(keys):
            return None, "expected_pool_absent"
        outer, groups, error = _instruction_groups(message, meta, keys)
        if error:
            return None, error

        lp_pair, error = _derive_lp_pair(outer, groups, base_mint)
        if error:
            return None, error
        base_flow, error = _derive_base_flow(meta, keys, base_mint)
        if error:
            return None, error
        sol_flow, error = _derive_sol_flow(meta, keys)
        if error:
            return None, error
    except Exception:
        return None, "unexpected_input_error"

    assert lp_pair is not None and base_flow is not None and sol_flow is not None
    context = MigrationContext(
        expected_pool=expected_pool,
        lp_mint=lp_pair[0],
        lp_account=lp_pair[1],
        base_source=base_flow[0],
        base_destination=base_flow[1],
        sol_source=sol_flow[0],
        sol_destination=sol_flow[1],
    )
    return context, None


def screen_pool(
    tx: Any,
    expected_pool: Any,
    base_mint: Any,
    lp_account_states: Optional[Iterable[LpAccountState]] = None,
) -> MigrationEvidenceVerdict:
    """Derive a candidate context from ``tx`` and verify it, fail-closed.

    Convenience wrapper for the screening case where only the pool address and
    its mint are known in advance. Derivation ambiguity yields a verdict whose
    ``failed_check`` is ``"derive:<reason>"``; otherwise the strict verifier's
    verdict is returned unchanged.
    """
    context, reason = propose_migration_context(tx, expected_pool, base_mint)
    if context is None:
        evidence = _base_evidence(base_mint, None)
        evidence["derive_failed_reason"] = reason
        return MigrationEvidenceVerdict(
            EVIDENCE_NOT_ESTABLISHED, f"derive:{reason}", evidence
        )
    return verify_migration_evidence(tx, base_mint, context, lp_account_states)
