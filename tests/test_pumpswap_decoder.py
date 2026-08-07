"""Strict unit tests for the vendored PumpSwap Pool decoder."""

from __future__ import annotations

import base64
import unittest

import base58

from pumpswap_decoder import (
    PUMP_AMM_PROGRAM,
    WSOL_MINT,
    PoolDecodeError,
    decode_pool,
    decode_pool_b64,
    decode_rpc_account_value,
)
from tests.synthetic_migration import BASE_MINT, BASE_VAULT, SOL_VAULT, _raw_pool


class PoolDecoderTests(unittest.TestCase):
    def test_valid_extended_pool_decodes_canonical_roles(self):
        state = decode_pool(_raw_pool(), owner=PUMP_AMM_PROGRAM)
        self.assertEqual(state.token_mint, BASE_MINT)
        self.assertEqual(state.token_vault, BASE_VAULT)
        self.assertEqual(state.sol_vault, SOL_VAULT)
        self.assertTrue(state.reversed_layout)

    def test_reversed_wsol_layout_decodes_roles(self):
        raw = bytearray(_raw_pool())
        raw[43:75], raw[75:107] = raw[75:107], raw[43:75]
        raw[139:171], raw[171:203] = raw[171:203], raw[139:171]
        state = decode_pool(bytes(raw), owner=PUMP_AMM_PROGRAM)
        self.assertEqual(state.token_mint, BASE_MINT)
        self.assertEqual(state.token_vault, BASE_VAULT)
        self.assertEqual(state.sol_vault, SOL_VAULT)
        self.assertFalse(state.reversed_layout)

    def test_owner_discriminator_size_tail_and_bools_fail_closed(self):
        mutations = []
        raw = bytearray(_raw_pool())
        raw[0] ^= 1
        mutations.append(bytes(raw))
        mutations.append(_raw_pool()[:-1])
        raw = bytearray(_raw_pool())
        raw[261] = 1
        mutations.append(bytes(raw))
        raw = bytearray(_raw_pool())
        raw[243] = 2
        mutations.append(bytes(raw))
        raw = bytearray(_raw_pool())
        raw[244] = 255
        mutations.append(bytes(raw))
        raw = bytearray(_raw_pool())
        raw[43:75] = base58.b58decode(WSOL_MINT)
        raw[75:107] = base58.b58decode(WSOL_MINT)
        mutations.append(bytes(raw))

        for data in mutations:
            with self.subTest(length=len(data)):
                with self.assertRaises(PoolDecodeError):
                    decode_pool(data, owner=PUMP_AMM_PROGRAM)
        with self.assertRaises(PoolDecodeError):
            decode_pool(_raw_pool(), owner=BASE_MINT)

    def test_base64_and_rpc_wrappers_require_canonical_evidence(self):
        encoded = base64.b64encode(_raw_pool()).decode("ascii")
        self.assertEqual(
            decode_pool_b64(encoded, owner=PUMP_AMM_PROGRAM).token_mint,
            BASE_MINT,
        )
        for value in (None, b"bytes", "not base64", encoded + "\n"):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(PoolDecodeError):
                    decode_pool_b64(value, owner=PUMP_AMM_PROGRAM)

        rpc_value = {
            "owner": PUMP_AMM_PROGRAM,
            "data": [encoded, "base64"],
        }
        self.assertEqual(decode_rpc_account_value(rpc_value).token_mint, BASE_MINT)
        for value in ({}, {"owner": PUMP_AMM_PROGRAM, "data": encoded}, None):
            with self.subTest(value=value):
                with self.assertRaises(PoolDecodeError):
                    decode_rpc_account_value(value)


if __name__ == "__main__":
    unittest.main()
