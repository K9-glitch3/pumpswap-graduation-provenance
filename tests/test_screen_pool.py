"""Tests for the derive-then-verify screening entry point.

``screen_pool`` derives a candidate ``MigrationContext`` from a pool's creation
transaction (given only the pool address and its mint) and delegates to the
strict verifier. These tests confirm the derivation recovers the same accounts
the strict path requires, and that derivation failures fail closed rather than
inventing a match.

The transaction fixture mirrors the shape used in
``tests/test_graduation_provenance.py`` so the two suites stay consistent.
"""

import unittest

from graduation_provenance import (
    EVIDENCE_MATCHED,
    EVIDENCE_NOT_ESTABLISHED,
    PUMPSWAP_AMM_PROGRAM,
    LpAccountState,
    MigrationContext,
    propose_migration_context,
    screen_pool,
    verify_migration_evidence,
)

PUMP_FUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
BASE_MINT = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"
LP_MINT = "8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR"
LP_ACCOUNT = "CktRuQ2mttgRGkXJtyksdKHjUdc2C4TgDzyB98oEzy8"
BASE_SOURCE = "GgBaCs3NCBuZN12kCJgAW63ydqohFkHEdfdEXBPzLHq"
BASE_DESTINATION = "LbUiWL3xVV8hTFYBVdbTNrpDo41NKS6o3LHHuDzjfcY"
SOL_SOURCE = "QWmroo4YnnMqYW3cnxWkFdaTxGD3P7vMSzwMHGbUzwF"
EXPECTED_POOL = "US517G5965aydkZ46HS38QLi7UQiSojurfbQfKCELFx"
SOL_DESTINATION = "p2Yicb86aZig616Eav2VWG9vuXR5mEqhtzshZYBxzsV"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

STATIC_KEYS = [
    PUMP_FUN,
    BASE_MINT,
    BASE_SOURCE,
    BASE_DESTINATION,
    EXPECTED_POOL,
    LP_MINT,
    LP_ACCOUNT,
    SOL_DESTINATION,
    TOKEN_PROGRAM,
]
ALL_KEYS = STATIC_KEYS + [SOL_SOURCE, PUMPSWAP_AMM_PROGRAM]
BOUND_ACCOUNTS = [
    EXPECTED_POOL,
    BASE_MINT,
    LP_MINT,
    LP_ACCOUNT,
    BASE_SOURCE,
    BASE_DESTINATION,
    SOL_SOURCE,
    SOL_DESTINATION,
]


def _index(key):
    return ALL_KEYS.index(key)


def _mint_to(amount="500", mint=LP_MINT, account=LP_ACCOUNT):
    return {
        "program": "spl-token",
        "programId": TOKEN_PROGRAM,
        "stackHeight": 3,
        "parsed": {"type": "mintTo", "info": {"mint": mint, "account": account, "amount": amount}},
    }


def _burn(amount="500", mint=LP_MINT, account=LP_ACCOUNT):
    return {
        "program": "spl-token",
        "programId": TOKEN_PROGRAM,
        "stackHeight": 3,
        "parsed": {"type": "burn", "info": {"mint": mint, "account": account, "amount": amount}},
    }


def _pumpswap_instruction(accounts=None):
    if accounts is None:
        accounts = list(BOUND_ACCOUNTS)
    return {
        "programId": PUMPSWAP_AMM_PROGRAM,
        "accounts": accounts,
        "data": "1",
        "stackHeight": 2,
    }


def _matching_tx():
    pre_balances = [0] * len(ALL_KEYS)
    post_balances = [0] * len(ALL_KEYS)
    pre_balances[_index(SOL_SOURCE)] = 85_000_000_000
    post_balances[_index(SOL_DESTINATION)] = 85_000_000_000
    return {
        "slot": 100,
        "transaction": {
            "message": {
                "accountKeys": [
                    {"pubkey": key} if index == 0 else key
                    for index, key in enumerate(STATIC_KEYS)
                ],
                "instructions": [
                    {"programId": PUMP_FUN, "accounts": list(BOUND_ACCOUNTS), "data": "1"}
                ],
            }
        },
        "meta": {
            "err": None,
            "loadedAddresses": {
                "writable": [{"pubkey": SOL_SOURCE}],
                "readonly": [PUMPSWAP_AMM_PROGRAM],
            },
            "preBalances": pre_balances,
            "postBalances": post_balances,
            "preTokenBalances": [
                {"accountIndex": _index(BASE_SOURCE), "mint": BASE_MINT, "uiTokenAmount": {"amount": "1000"}},
            ],
            "postTokenBalances": [
                {"accountIndex": _index(BASE_SOURCE), "mint": BASE_MINT, "uiTokenAmount": {"amount": "0"}},
                {"accountIndex": _index(BASE_DESTINATION), "mint": BASE_MINT, "uiTokenAmount": {"amount": "1000"}},
            ],
            "innerInstructions": [
                {"index": 0, "instructions": [_pumpswap_instruction(), _mint_to(), _burn()]}
            ],
        },
    }


def _lp_proof():
    return [
        LpAccountState(
            lp_mint=LP_MINT,
            destination=LP_ACCOUNT,
            destination_closed=True,
            lp_supply_zero=True,
        )
    ]


class DeriveContextTests(unittest.TestCase):
    def test_derived_context_matches_the_hand_bound_one(self):
        context, reason = propose_migration_context(_matching_tx(), EXPECTED_POOL, BASE_MINT)
        self.assertIsNone(reason)
        self.assertEqual(
            context,
            MigrationContext(
                expected_pool=EXPECTED_POOL,
                lp_mint=LP_MINT,
                lp_account=LP_ACCOUNT,
                base_source=BASE_SOURCE,
                base_destination=BASE_DESTINATION,
                sol_source=SOL_SOURCE,
                sol_destination=SOL_DESTINATION,
            ),
        )

    def test_screen_matches_when_a_full_migration_is_present(self):
        verdict = screen_pool(_matching_tx(), EXPECTED_POOL, BASE_MINT, _lp_proof())
        self.assertEqual(verdict.verdict, EVIDENCE_MATCHED)
        self.assertIsNone(verdict.failed_check)

    def test_derivation_agrees_with_the_strict_path(self):
        # The context derived here must produce the same verdict the strict
        # verifier gives when handed that context directly.
        context, _ = propose_migration_context(_matching_tx(), EXPECTED_POOL, BASE_MINT)
        strict = verify_migration_evidence(_matching_tx(), BASE_MINT, context, _lp_proof())
        screened = screen_pool(_matching_tx(), EXPECTED_POOL, BASE_MINT, _lp_proof())
        self.assertEqual(strict.verdict, screened.verdict)
        self.assertEqual(strict.verdict, EVIDENCE_MATCHED)


class DeriveFailClosedTests(unittest.TestCase):
    def test_seeded_pool_with_no_pump_fun_program_has_no_lp_pair(self):
        # A direct CreatePool (no pump.fun program) exposes no bound LP pair,
        # so derivation fails closed before the strict check is even reached.
        tx = _matching_tx()
        # A direct CreatePool: PumpSwap AMM at the outer level, no pump.fun
        # program, no inner LP mint/burn group.
        tx["transaction"]["message"]["instructions"] = [
            {"programId": PUMPSWAP_AMM_PROGRAM, "accounts": list(BOUND_ACCOUNTS), "data": "1"}
        ]
        tx["meta"]["innerInstructions"] = []
        verdict = screen_pool(tx, EXPECTED_POOL, BASE_MINT, _lp_proof())
        self.assertEqual(verdict.verdict, EVIDENCE_NOT_ESTABLISHED)
        self.assertEqual(verdict.failed_check, "derive:lp_pair_not_found")

    def test_unknown_pool_address_fails_closed(self):
        verdict = screen_pool(_matching_tx(), TOKEN_PROGRAM[:-1] + "Z", BASE_MINT, _lp_proof())
        self.assertEqual(verdict.verdict, EVIDENCE_NOT_ESTABLISHED)
        self.assertTrue(verdict.failed_check.startswith("derive:"))

    def test_small_sol_move_is_not_a_migration_source(self):
        tx = _matching_tx()
        tx["meta"]["preBalances"][_index(SOL_SOURCE)] = 5_000_000_000
        tx["meta"]["postBalances"][_index(SOL_DESTINATION)] = 5_000_000_000
        verdict = screen_pool(tx, EXPECTED_POOL, BASE_MINT, _lp_proof())
        self.assertEqual(verdict.verdict, EVIDENCE_NOT_ESTABLISHED)
        self.assertEqual(verdict.failed_check, "derive:sol_source_not_unique")

    def test_ambiguous_lp_pair_fails_closed(self):
        # Two distinct LP pairs under the pump.fun group -> not unique.
        tx = _matching_tx()
        other_mint = "9zabHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR"
        other_acct = "DktRuQ2mttgRGkXJtyksdKHjUdc2C4TgDzyB98oEzy8"
        tx["meta"]["innerInstructions"][0]["instructions"].extend(
            [
                {**_mint_to(amount="700", mint=other_mint, account=other_acct), "stackHeight": 3},
                {**_burn(amount="700", mint=other_mint, account=other_acct), "stackHeight": 3},
            ]
        )
        verdict = screen_pool(tx, EXPECTED_POOL, BASE_MINT, _lp_proof())
        self.assertEqual(verdict.verdict, EVIDENCE_NOT_ESTABLISHED)
        self.assertEqual(verdict.failed_check, "derive:lp_pair_not_unique")

    def test_missing_lp_proof_still_fails_closed_after_derivation(self):
        verdict = screen_pool(_matching_tx(), EXPECTED_POOL, BASE_MINT, lp_account_states=None)
        self.assertEqual(verdict.verdict, EVIDENCE_NOT_ESTABLISHED)
        self.assertEqual(verdict.failed_check, "lp_account_closed_supply_zero")

    def test_malformed_transaction_fails_closed(self):
        verdict = screen_pool({}, EXPECTED_POOL, BASE_MINT, _lp_proof())
        self.assertEqual(verdict.verdict, EVIDENCE_NOT_ESTABLISHED)
        self.assertTrue(verdict.failed_check.startswith("derive:"))


if __name__ == "__main__":
    unittest.main()
