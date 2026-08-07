"""Strict decoder for WSOL-paired accounts in the public PumpSwap Pool schema.

Vendored from the sibling ``pumpswap-pool-decoder`` repository at commit
3dcc513 (MIT; same copyright and licence as this repository). This module
decodes state only and contains no endpoint or transaction-construction logic.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional

import base58

__all__ = [
    "POOL_DISCRIMINATOR",
    "PUMP_AMM_PROGRAM",
    "SUPPORTED_ACCOUNT_SIZES",
    "WSOL_MINT",
    "PoolDecodeError",
    "PoolState",
    "decode_pool",
    "decode_pool_b64",
    "decode_rpc_account_value",
]

WSOL_MINT = "So11111111111111111111111111111111111111112"
PUMP_AMM_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
POOL_DISCRIMINATOR = bytes.fromhex("f19a6d0411b16dbc")
SUPPORTED_ACCOUNT_SIZES = frozenset({261, 301})

_WSOL_MINT_BYTES = base58.b58decode(WSOL_MINT)


class PoolDecodeError(ValueError):
    """Raised when bytes cannot be established as a supported Pool account."""


def _pk(data: bytes, offset: int) -> str:
    return base58.b58encode(data[offset:offset + 32]).decode("ascii")


def _canonical_bool(data: bytes, offset: int, name: str) -> bool:
    value = data[offset]
    if value not in (0, 1):
        raise PoolDecodeError(f"{name} is not a canonical Borsh bool: {value}")
    return bool(value)


@dataclass(frozen=True)
class PoolState:
    pool_bump: int
    index: int
    creator: str
    base_mint: str
    quote_mint: str
    lp_mint: str
    base_vault: str
    quote_vault: str
    lp_supply: int
    coin_creator: str
    is_mayhem_mode: bool
    is_cashback_coin: bool
    virtual_quote_reserves: int
    reversed_layout: bool
    token_mint: str
    sol_vault: str
    token_vault: str

    def effective_quote_reserve(self, real_quote_vault_balance: int) -> int:
        """Return the effective reserve in the quote mint's smallest unit."""
        return real_quote_vault_balance + self.virtual_quote_reserves

    @property
    def cashback_flag(self) -> bool:
        return self.is_cashback_coin

    @property
    def lp_total_supply(self) -> int:
        return self.lp_supply


def decode_pool(data: bytes, *, owner: Optional[str] = None) -> PoolState:
    """Decode a supported raw Pool account, checking owner when supplied."""
    if owner is not None and owner != PUMP_AMM_PROGRAM:
        raise PoolDecodeError(f"unexpected account owner: {owner}")
    if len(data) not in SUPPORTED_ACCOUNT_SIZES:
        raise PoolDecodeError(
            f"unsupported Pool account size: {len(data)} "
            f"(expected one of {sorted(SUPPORTED_ACCOUNT_SIZES)})"
        )
    if data[:8] != POOL_DISCRIMINATOR:
        raise PoolDecodeError("Pool account discriminator mismatch")
    if len(data) == 301 and any(data[261:301]):
        raise PoolDecodeError("unsupported non-zero bytes in extended account tail")

    is_mayhem_mode = _canonical_bool(data, 243, "is_mayhem_mode")
    is_cashback_coin = _canonical_bool(data, 244, "is_cashback_coin")
    base_mint_raw = data[43:75]
    quote_mint_raw = data[75:107]
    base_is_wsol = base_mint_raw == _WSOL_MINT_BYTES
    quote_is_wsol = quote_mint_raw == _WSOL_MINT_BYTES
    if base_is_wsol == quote_is_wsol:
        raise PoolDecodeError("exactly one pool mint must be WSOL")

    base_mint = _pk(data, 43)
    quote_mint = _pk(data, 75)
    base_vault = _pk(data, 139)
    quote_vault = _pk(data, 171)
    reversed_layout = quote_is_wsol
    if reversed_layout:
        token_mint, sol_vault, token_vault = base_mint, quote_vault, base_vault
    else:
        token_mint, sol_vault, token_vault = quote_mint, base_vault, quote_vault

    return PoolState(
        pool_bump=data[8],
        index=int.from_bytes(data[9:11], "little"),
        creator=_pk(data, 11),
        base_mint=base_mint,
        quote_mint=quote_mint,
        lp_mint=_pk(data, 107),
        base_vault=base_vault,
        quote_vault=quote_vault,
        lp_supply=int.from_bytes(data[203:211], "little"),
        coin_creator=_pk(data, 211),
        is_mayhem_mode=is_mayhem_mode,
        is_cashback_coin=is_cashback_coin,
        virtual_quote_reserves=int.from_bytes(data[245:261], "little", signed=True),
        reversed_layout=reversed_layout,
        token_mint=token_mint,
        sol_vault=sol_vault,
        token_vault=token_vault,
    )


def decode_pool_b64(b64_data: str, *, owner: Optional[str] = None) -> PoolState:
    """Decode canonical Base64, optionally checking account ownership."""
    if not isinstance(b64_data, str):
        raise PoolDecodeError("invalid Base64 account payload")
    try:
        data = base64.b64decode(b64_data, validate=True)
    except (binascii.Error, TypeError, ValueError) as exc:
        raise PoolDecodeError("invalid Base64 account payload") from exc
    if base64.b64encode(data).decode("ascii") != b64_data:
        raise PoolDecodeError("non-canonical Base64 account payload")
    return decode_pool(data, owner=owner)


def decode_rpc_account_value(value: Any) -> PoolState:
    """Decode a getAccountInfo value while requiring owner metadata."""
    if not isinstance(value, Mapping):
        raise PoolDecodeError("RPC returned no account")
    owner = value.get("owner")
    if not isinstance(owner, str) or not owner:
        raise PoolDecodeError("RPC account owner is missing")
    payload = value.get("data")
    if (
        not isinstance(payload, (list, tuple))
        or len(payload) != 2
        or payload[1] != "base64"
    ):
        raise PoolDecodeError("RPC returned an unexpected account-data encoding")
    return decode_pool_b64(payload[0], owner=owner)
