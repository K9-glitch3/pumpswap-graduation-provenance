"""Clearly synthetic, deterministic migration evidence for unit tests."""

from __future__ import annotations

import base64
import struct

import base58

from graduation_provenance import (
    ASSOCIATED_TOKEN_PROGRAM,
    CREATE_POOL_DISCRIMINATOR,
    MIGRATE_V2_DISCRIMINATOR,
    PUMP_FUN_PROGRAM,
    PUMP_EVENT_AUTHORITY,
    PUMP_GLOBAL,
    PUMPSWAP_AMM_PROGRAM,
    PUMPSWAP_EVENT_AUTHORITY,
    PUMPSWAP_GLOBAL,
    RENT_SYSVAR,
    SYSTEM_PROGRAM,
    TOKEN_2022_PROGRAM,
    TOKEN_PROGRAM,
    WSOL_MINT,
    LpAccountState,
    MigrationContext,
    PoolAccountEvidence,
)
from pumpswap_decoder import POOL_DISCRIMINATOR


def _pk(seed: int) -> str:
    return base58.b58encode(bytes([seed]) * 32).decode("ascii")


POOL = _pk(10)
CREATOR = _pk(11)
BASE_MINT = _pk(12)
LP_MINT = _pk(13)
LP_ACCOUNT = _pk(14)
BASE_CURVE = _pk(15)
BASE_CURVE_ACCOUNT = _pk(16)
QUOTE_CURVE_ACCOUNT = _pk(17)
BASE_INPUT = _pk(18)
SOL_INPUT = _pk(19)
BASE_VAULT = _pk(20)
SOL_VAULT = _pk(21)
MIGRATION_AUTHORITY = _pk(22)
AMM_GLOBAL = PUMPSWAP_GLOBAL
PAYER = _pk(25)
COIN_CREATOR = _pk(26)

BASE_AMOUNT = 206_900_000_000_000
LP_AMOUNT = 4_193_388_300_000


def _raw_pool() -> bytes:
    data = bytearray(301)
    data[0:8] = POOL_DISCRIMINATOR
    data[8] = 1
    data[9:11] = (0).to_bytes(2, "little")
    data[11:43] = base58.b58decode(CREATOR)
    data[43:75] = base58.b58decode(BASE_MINT)
    data[75:107] = base58.b58decode(WSOL_MINT)
    data[107:139] = base58.b58decode(LP_MINT)
    data[139:171] = base58.b58decode(BASE_VAULT)
    data[171:203] = base58.b58decode(SOL_VAULT)
    data[203:211] = (LP_AMOUNT + 100).to_bytes(8, "little")
    data[211:243] = base58.b58decode(COIN_CREATOR)
    data[243] = 0
    data[244] = 0
    return bytes(data)


def _parsed(program_id, operation, info, *, stack_height):
    # Token-2022 is intentionally labelled "spl-token", matching real RPC.
    return {
        "program": "spl-token",
        "programId": program_id,
        "stackHeight": stack_height,
        "parsed": {"type": operation, "info": info},
    }


def make_bundle(*, quote_amount: int = 84_990_360_000):
    cp_accounts = [
        POOL,
        AMM_GLOBAL,
        CREATOR,
        BASE_MINT,
        WSOL_MINT,
        LP_MINT,
        BASE_INPUT,
        SOL_INPUT,
        LP_ACCOUNT,
        BASE_VAULT,
        SOL_VAULT,
        SYSTEM_PROGRAM,
        TOKEN_2022_PROGRAM,
        TOKEN_2022_PROGRAM,
        TOKEN_PROGRAM,
        ASSOCIATED_TOKEN_PROGRAM,
        PUMPSWAP_EVENT_AUTHORITY,
        PUMPSWAP_AMM_PROGRAM,
    ]
    migration_accounts = [
        PUMP_GLOBAL,
        MIGRATION_AUTHORITY,
        BASE_MINT,
        WSOL_MINT,
        BASE_CURVE,
        BASE_CURVE_ACCOUNT,
        QUOTE_CURVE_ACCOUNT,
        PAYER,
        SYSTEM_PROGRAM,
        PUMPSWAP_AMM_PROGRAM,
        POOL,
        CREATOR,
        BASE_INPUT,
        SOL_INPUT,
        AMM_GLOBAL,
        LP_MINT,
        LP_ACCOUNT,
        BASE_VAULT,
        SOL_VAULT,
        TOKEN_2022_PROGRAM,
        TOKEN_PROGRAM,
        TOKEN_2022_PROGRAM,
        ASSOCIATED_TOKEN_PROGRAM,
        PUMPSWAP_EVENT_AUTHORITY,
        RENT_SYSVAR,
        PUMP_EVENT_AUTHORITY,
        PUMP_FUN_PROGRAM,
    ]
    create_data = (
        CREATE_POOL_DISCRIMINATOR
        + struct.pack("<HQQ", 0, BASE_AMOUNT, quote_amount)
        + base58.b58decode(COIN_CREATOR)
        + b"\x00\x00"
    )
    inner = [
        _parsed(
            TOKEN_2022_PROGRAM,
            "transferChecked",
            {
                "source": BASE_CURVE_ACCOUNT,
                "destination": BASE_INPUT,
                "mint": BASE_MINT,
                "authority": BASE_CURVE,
                "tokenAmount": {"amount": str(BASE_AMOUNT), "decimals": 6},
            },
            stack_height=2,
        ),
        _parsed(
            TOKEN_PROGRAM,
            "syncNative",
            {"account": SOL_INPUT},
            stack_height=2,
        ),
        {
            "programId": PUMPSWAP_AMM_PROGRAM,
            "accounts": cp_accounts,
            "data": base58.b58encode(create_data).decode("ascii"),
            "stackHeight": 2,
        },
        _parsed(
            TOKEN_2022_PROGRAM,
            "transferChecked",
            {
                "source": BASE_INPUT,
                "destination": BASE_VAULT,
                "mint": BASE_MINT,
                "authority": CREATOR,
                "tokenAmount": {"amount": str(BASE_AMOUNT), "decimals": 6},
            },
            stack_height=3,
        ),
        _parsed(
            TOKEN_PROGRAM,
            "transferChecked",
            {
                "source": SOL_INPUT,
                "destination": SOL_VAULT,
                "mint": WSOL_MINT,
                "authority": CREATOR,
                "tokenAmount": {"amount": str(quote_amount), "decimals": 9},
            },
            stack_height=3,
        ),
        _parsed(
            TOKEN_2022_PROGRAM,
            "mintTo",
            {
                "mint": LP_MINT,
                "account": LP_ACCOUNT,
                "mintAuthority": POOL,
                "amount": str(LP_AMOUNT),
            },
            stack_height=3,
        ),
        _parsed(
            TOKEN_2022_PROGRAM,
            "burn",
            {
                "mint": LP_MINT,
                "account": LP_ACCOUNT,
                "authority": CREATOR,
                "amount": str(LP_AMOUNT),
            },
            stack_height=2,
        ),
        _parsed(
            TOKEN_2022_PROGRAM,
            "closeAccount",
            {
                "account": LP_ACCOUNT,
                "destination": MIGRATION_AUTHORITY,
                "owner": CREATOR,
            },
            stack_height=2,
        ),
    ]
    keys = list(
        dict.fromkeys(
            migration_accounts
            + cp_accounts
            + [TOKEN_PROGRAM, TOKEN_2022_PROGRAM, PUMP_FUN_PROGRAM, PUMPSWAP_AMM_PROGRAM]
        )
    )
    tx = {
        "slot": 100,
        "transaction": {
            "signatures": [_pk(31) + _pk(32)[:20]],
            "message": {
                "accountKeys": keys,
                "instructions": [
                    {
                        "programId": PUMP_FUN_PROGRAM,
                        "accounts": migration_accounts,
                        "data": base58.b58encode(MIGRATE_V2_DISCRIMINATOR).decode("ascii"),
                        "stackHeight": 1,
                    }
                ],
            },
        },
        "meta": {
            "err": None,
            "preBalances": [
                90_000_000_000 if key == BASE_CURVE else 10_000_000
                for key in keys
            ],
            "postBalances": [
                4_994_640_000 if key == BASE_CURVE else 10_000_000
                for key in keys
            ],
            "innerInstructions": [{"index": 0, "instructions": inner}],
        },
    }
    context = MigrationContext(
        expected_pool=POOL,
        lp_mint=LP_MINT,
        lp_account=LP_ACCOUNT,
        base_source=BASE_CURVE_ACCOUNT,
        base_destination=BASE_VAULT,
        sol_source=BASE_CURVE,
        sol_destination=SOL_VAULT,
    )
    pool = PoolAccountEvidence(
        address=POOL,
        owner=PUMPSWAP_AMM_PROGRAM,
        data_base64=base64.b64encode(_raw_pool()).decode("ascii"),
        context_slot=101,
    )
    states = [
        LpAccountState(
            lp_mint=LP_MINT,
            destination=LP_ACCOUNT,
            destination_closed=True,
            lp_supply_zero=True,
        )
    ]
    return {"tx": tx, "context": context, "pool": pool, "states": states}
