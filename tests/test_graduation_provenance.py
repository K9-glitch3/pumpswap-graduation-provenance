"""Adversarial tests for the offline, pool-bound migration evidence predicate."""

import unittest
from dataclasses import replace

from graduation_provenance import (
    EVIDENCE_MATCHED,
    EVIDENCE_NOT_ESTABLISHED,
    PUMPSWAP_AMM_PROGRAM,
    WSOL_MINT,
    LpAccountState,
    MigrationContext,
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
OTHER_PROGRAM = "YMN9Qj5jPNp7j14VPcML1B6xGgcPWVZUGLFU3Mnyfaf"
DIFFERENT_POOL = "cGfHiC6Kgg3FpFZvgwGcswsCRtp4aBP2fzuXRQPizuN"
UNRELATED_MINT = "gBxS1f6uyyGPuW5MzGBukidSb71jdsCb5fZaoSzULE5"
UNRELATED_ACCOUNT = "k7FaK87WHGVXzkaoHb7CdVPgkKDQhZ29VLDeBVbDfYn"

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


def _context():
    return MigrationContext(
        expected_pool=EXPECTED_POOL,
        lp_mint=LP_MINT,
        lp_account=LP_ACCOUNT,
        base_source=BASE_SOURCE,
        base_destination=BASE_DESTINATION,
        sol_source=SOL_SOURCE,
        sol_destination=SOL_DESTINATION,
    )


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
    """Synthetic parsed transaction with one account-bound CPI group."""
    pre_balances = [0] * len(ALL_KEYS)
    post_balances = [0] * len(ALL_KEYS)
    pre_balances[_index(SOL_SOURCE)] = 85_000_000_000
    post_balances[_index(SOL_DESTINATION)] = 85_000_000_000
    return {
        "slot": 100,
        "transaction": {
            "message": {
                "accountKeys": [{"pubkey": key} if index == 0 else key for index, key in enumerate(STATIC_KEYS)],
                "instructions": [
                    {
                        "programId": PUMP_FUN,
                        "accounts": list(BOUND_ACCOUNTS),
                        "data": "1",
                    }
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
                {
                    "accountIndex": _index(BASE_SOURCE),
                    "mint": BASE_MINT,
                    "uiTokenAmount": {"amount": "1000"},
                }
            ],
            "postTokenBalances": [
                {
                    "accountIndex": _index(BASE_SOURCE),
                    "mint": BASE_MINT,
                    "uiTokenAmount": {"amount": "0"},
                },
                {
                    "accountIndex": _index(BASE_DESTINATION),
                    "mint": BASE_MINT,
                    "uiTokenAmount": {"amount": "1000"},
                },
            ],
            "innerInstructions": [
                {
                    "index": 0,
                    "instructions": [_pumpswap_instruction(), _mint_to(), _burn()],
                }
            ],
        },
    }


def _lp_proof(destination_closed=True, lp_supply_zero=True):
    return [
        LpAccountState(
            lp_mint=LP_MINT,
            destination=LP_ACCOUNT,
            destination_closed=destination_closed,
            lp_supply_zero=lp_supply_zero,
        )
    ]


_DEFAULT_TX = object()
_DEFAULT_CONTEXT = object()
_DEFAULT_STATES = object()


def _verify(
    tx=_DEFAULT_TX,
    *,
    base_mint=BASE_MINT,
    context=_DEFAULT_CONTEXT,
    states=_DEFAULT_STATES,
):
    return verify_migration_evidence(
        _matching_tx() if tx is _DEFAULT_TX else tx,
        base_mint,
        _context() if context is _DEFAULT_CONTEXT else context,
        _lp_proof() if states is _DEFAULT_STATES else states,
    )


class BoundEvidenceMatchTests(unittest.TestCase):
    def test_all_bound_evidence_matches(self):
        verdict = _verify()
        self.assertEqual(verdict.verdict, EVIDENCE_MATCHED)
        self.assertIsNone(verdict.failed_check)
        self.assertTrue(verdict.is_match)
        self.assertEqual(verdict.evidence["bound_migration_group_indexes"], [0])

    def test_loaded_addresses_resolve_for_program_accounts_and_balances(self):
        verdict = _verify()
        self.assertEqual(verdict.verdict, EVIDENCE_MATCHED)
        self.assertEqual(verdict.evidence["sol_flow"]["sol_source"], SOL_SOURCE)
        self.assertEqual(
            verdict.evidence["sol_flow"]["sol_source_debit_lamports"], 85_000_000_000
        )

    def test_loaded_program_id_index_and_compiled_accounts_resolve(self):
        tx = _matching_tx()
        instruction = tx["meta"]["innerInstructions"][0]["instructions"][0]
        instruction.pop("programId")
        instruction["programIdIndex"] = _index(PUMPSWAP_AMM_PROGRAM)
        instruction["accounts"] = [
            _index(account)
            for account in BOUND_ACCOUNTS
        ]
        verdict = _verify(tx)
        self.assertEqual(verdict.verdict, EVIDENCE_MATCHED)

    def test_pre_only_source_token_account_is_a_real_negative_flow(self):
        tx = _matching_tx()
        tx["meta"]["postTokenBalances"] = tx["meta"]["postTokenBalances"][1:]
        verdict = _verify(tx)
        self.assertEqual(verdict.verdict, EVIDENCE_MATCHED)
        self.assertEqual(verdict.evidence["token_flow"]["source_delta"], -1000)


class OrderedFailClosedTests(unittest.TestCase):
    def test_missing_lp_proof_fails_closed(self):
        for states in (None, []):
            with self.subTest(states=states):
                verdict = _verify(states=states)
                self.assertEqual(verdict.verdict, EVIDENCE_NOT_ESTABLISHED)
                self.assertEqual(verdict.failed_check, "lp_account_closed_supply_zero")

    def test_lp_account_must_be_closed_and_supply_zero(self):
        for closed, zero in ((False, True), (True, False)):
            with self.subTest(closed=closed, zero=zero):
                verdict = _verify(states=_lp_proof(closed, zero))
                self.assertEqual(verdict.failed_check, "lp_account_closed_supply_zero")

    def test_lp_state_flags_must_be_exact_booleans(self):
        states = [LpAccountState(LP_MINT, LP_ACCOUNT, "false", "false")]
        verdict = _verify(states=states)
        self.assertEqual(verdict.verdict, EVIDENCE_NOT_ESTABLISHED)
        self.assertEqual(verdict.failed_check, "lp_account_closed_supply_zero")

    def test_non_iterable_or_wrong_state_items_fail_without_raising(self):
        for states in (123, "not-a-state", [object()]):
            with self.subTest(states=states):
                verdict = _verify(states=states)
                self.assertEqual(verdict.failed_check, "lp_account_closed_supply_zero")

    def test_malformed_or_duplicate_state_cannot_hide_beside_valid_proof(self):
        cases = (
            _lp_proof() + [object()],
            _lp_proof() + _lp_proof(),
        )
        for states in cases:
            with self.subTest(states=states):
                verdict = _verify(states=states)
                self.assertEqual(
                    verdict.failed_check, "lp_account_closed_supply_zero"
                )

    def test_missing_pump_fun_program_fails_before_other_program_checks(self):
        tx = _matching_tx()
        tx["transaction"]["message"]["instructions"][0][
            "programId"
        ] = PUMPSWAP_AMM_PROGRAM
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "pump_fun_program")

    def test_missing_pumpswap_program_fails(self):
        tx = _matching_tx()
        tx["meta"]["innerInstructions"][0]["instructions"] = [
            {
                "programId": TOKEN_PROGRAM,
                "accounts": [],
                "data": "1",
                "stackHeight": 2,
            },
            _mint_to(),
            _burn(),
        ]
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "pumpswap_amm")

    def test_small_bound_sol_move_fails(self):
        tx = _matching_tx()
        tx["meta"]["preBalances"][_index(SOL_SOURCE)] = 5_000_000_000
        tx["meta"]["postBalances"][_index(SOL_DESTINATION)] = 5_000_000_000
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "migration_sol_flow")

    def test_positive_only_base_flow_fails(self):
        tx = _matching_tx()
        tx["meta"]["preTokenBalances"] = []
        tx["meta"]["postTokenBalances"] = tx["meta"]["postTokenBalances"][1:]
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "base_mint_migrated")

    def test_lp_minted_without_bound_burn_fails(self):
        tx = _matching_tx()
        tx["meta"]["innerInstructions"][0]["instructions"] = [
            _pumpswap_instruction(),
            _mint_to(),
        ]
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "lp_mint_and_burn")

    def test_lp_amounts_must_be_matching_positive_integers(self):
        cases = (
            ("500", "499"),
            ("0500", "500"),
            ("0500", "0500"),
            ("0", "0"),
            ("-1", "-1"),
            ("five", "five"),
            (str(1 << 64), str(1 << 64)),
            (500, 500),
            (None, None),
            (True, True),
            ("", ""),
        )
        for minted, burned in cases:
            with self.subTest(minted=minted, burned=burned):
                tx = _matching_tx()
                tx["meta"]["innerInstructions"][0]["instructions"] = [
                    _pumpswap_instruction(),
                    _mint_to(minted),
                    _burn(burned),
                ]
                verdict = _verify(tx)
                self.assertEqual(verdict.failed_check, "lp_mint_and_burn")

    def test_multiple_matching_lp_pairs_are_rejected_as_ambiguous(self):
        tx = _matching_tx()
        tx["meta"]["innerInstructions"][0]["instructions"].extend(
            [_mint_to("600"), _burn("600")]
        )
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "lp_mint_and_burn")

    def test_parsed_lp_instructions_reject_mixed_account_encoding(self):
        tx = _matching_tx()
        for instruction in tx["meta"]["innerInstructions"][0]["instructions"][1:]:
            instruction["accounts"] = [BASE_MINT, BASE_SOURCE]
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "transaction_shape")

    def test_lp_operations_must_come_from_an_spl_token_program(self):
        tx = _matching_tx()
        for instruction in tx["meta"]["innerInstructions"][0]["instructions"][1:]:
            instruction["programId"] = PUMP_FUN
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "lp_mint_and_burn")

    def test_malformed_lp_operation_cannot_hide_beside_a_valid_pair(self):
        tx = _matching_tx()
        malformed = _mint_to()
        malformed["parsed"]["info"].pop("amount")
        tx["meta"]["innerInstructions"][0]["instructions"].append(malformed)
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "lp_mint_and_burn")

    def test_wsol_mint_and_burn_are_not_bound_lp_evidence(self):
        tx = _matching_tx()
        tx["meta"]["innerInstructions"][0]["instructions"] = [
            _pumpswap_instruction(),
            _mint_to(mint=WSOL_MINT),
            _burn(mint=WSOL_MINT),
        ]
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "lp_mint_and_burn")


class InstructionGroupBindingTests(unittest.TestCase):
    def test_multiple_matching_groups_are_rejected_as_ambiguous(self):
        tx = _matching_tx()
        tx["transaction"]["message"]["instructions"].append(
            {
                "programId": PUMP_FUN,
                "accounts": list(BOUND_ACCOUNTS),
                "data": "1",
            }
        )
        tx["meta"]["innerInstructions"].append(
            {
                "index": 1,
                "instructions": [_pumpswap_instruction(), _mint_to(), _burn()],
            }
        )
        verdict = _verify(tx)
        self.assertEqual(
            verdict.failed_check, "bound_migration_instruction_group"
        )

    def test_lp_operations_must_follow_the_bound_pumpswap_cpi_in_order(self):
        before_mint = _mint_to()
        before_burn = _burn()
        before_mint["stackHeight"] = 2
        before_burn["stackHeight"] = 2
        cases = (
            [before_mint, before_burn, _pumpswap_instruction()],
            [_pumpswap_instruction(), _burn(), _mint_to()],
        )
        for instructions in cases:
            with self.subTest(instructions=instructions):
                tx = _matching_tx()
                tx["meta"]["innerInstructions"][0]["instructions"] = instructions
                verdict = _verify(tx)
                self.assertEqual(verdict.failed_check, "lp_mint_and_burn")

    def test_lp_mint_must_be_a_stack_descendant_of_pumpswap(self):
        tx = _matching_tx()
        tx["meta"]["innerInstructions"][0]["instructions"][1][
            "stackHeight"
        ] = 2
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "lp_mint_and_burn")

    def test_lp_burn_must_be_a_stack_descendant_of_pumpswap(self):
        tx = _matching_tx()
        tx["meta"]["innerInstructions"][0]["instructions"][2][
            "stackHeight"
        ] = 2
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "lp_mint_and_burn")

    def test_impossible_inner_stack_transitions_are_malformed(self):
        cases = ((1, 2, 2), (2, 99, 99))
        for pump_height, mint_height, burn_height in cases:
            with self.subTest(
                pump_height=pump_height,
                mint_height=mint_height,
            ):
                tx = _matching_tx()
                instructions = tx["meta"]["innerInstructions"][0][
                    "instructions"
                ]
                instructions[0]["stackHeight"] = pump_height
                instructions[1]["stackHeight"] = mint_height
                instructions[2]["stackHeight"] = burn_height
                verdict = _verify(tx)
                self.assertEqual(verdict.failed_check, "transaction_shape")

    def test_missing_pumpswap_stack_height_fails_closed(self):
        tx = _matching_tx()
        tx["meta"]["innerInstructions"][0]["instructions"][0].pop(
            "stackHeight"
        )
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "transaction_shape")

    def test_pumpswap_cpi_must_reference_every_pool_bound_account(self):
        required = BOUND_ACCOUNTS
        for omitted in required:
            with self.subTest(omitted=omitted):
                tx = _matching_tx()
                accounts = [account for account in required if account != omitted]
                tx["meta"]["innerInstructions"][0]["instructions"][0] = _pumpswap_instruction(
                    accounts
                )
                verdict = _verify(tx)
                self.assertEqual(verdict.failed_check, "bound_migration_instruction_group")

    def test_pump_fun_outer_instruction_must_reference_named_sources(self):
        for omitted in BOUND_ACCOUNTS:
            with self.subTest(omitted=omitted):
                tx = _matching_tx()
                tx["transaction"]["message"]["instructions"][0]["accounts"] = [
                    account
                    for account in BOUND_ACCOUNTS
                    if account != omitted
                ]
                verdict = _verify(tx)
                self.assertEqual(verdict.failed_check, "bound_migration_instruction_group")

    def test_transaction_global_program_composition_is_rejected(self):
        tx = _matching_tx()
        tx["transaction"]["message"]["accountKeys"].append(OTHER_PROGRAM)
        tx["meta"]["preBalances"].insert(len(STATIC_KEYS), 0)
        tx["meta"]["postBalances"].insert(len(STATIC_KEYS), 0)
        tx["transaction"]["message"]["instructions"] = [
            {
                "programId": PUMP_FUN,
                "accounts": list(BOUND_ACCOUNTS),
                "data": "1",
            },
            {"programId": OTHER_PROGRAM, "accounts": [], "data": "1"},
        ]
        tx["meta"]["innerInstructions"] = [
            {
                "index": 0,
                "instructions": [
                    {
                        "programId": OTHER_PROGRAM,
                        "accounts": [],
                        "data": "1",
                        "stackHeight": 2,
                    },
                    _mint_to(),
                    _burn(),
                ],
            },
            {
                "index": 1,
                "instructions": [
                    _pumpswap_instruction(),
                    _mint_to(),
                    _burn(),
                ],
            },
        ]
        verdict = _verify(tx)
        self.assertTrue(verdict.evidence["has_pump_fun_program"])
        self.assertTrue(verdict.evidence["has_pumpswap_amm"])
        self.assertEqual(verdict.failed_check, "bound_migration_instruction_group")

    def test_lp_ops_in_a_different_inner_group_do_not_compose(self):
        tx = _matching_tx()
        tx["transaction"]["message"]["accountKeys"].append(OTHER_PROGRAM)
        tx["meta"]["preBalances"].insert(len(STATIC_KEYS), 0)
        tx["meta"]["postBalances"].insert(len(STATIC_KEYS), 0)
        tx["transaction"]["message"]["instructions"].append(
            {"programId": OTHER_PROGRAM, "accounts": [], "data": "1"}
        )
        tx["meta"]["innerInstructions"] = [
            {"index": 0, "instructions": [_pumpswap_instruction()]},
            {
                "index": 1,
                "instructions": [
                    {
                        "programId": OTHER_PROGRAM,
                        "accounts": [],
                        "data": "1",
                        "stackHeight": 2,
                    },
                    _mint_to(),
                    _burn(),
                ],
            },
        ]
        verdict = _verify(tx)
        self.assertEqual(verdict.evidence["bound_migration_group_indexes"], [0])
        self.assertEqual(verdict.failed_check, "lp_mint_and_burn")

    def test_transaction_global_token_flows_do_not_substitute_for_bound_accounts(self):
        tx = _matching_tx()
        tx["meta"]["preTokenBalances"][0]["accountIndex"] = _index(LP_MINT)
        tx["meta"]["postTokenBalances"][0]["accountIndex"] = _index(LP_MINT)
        tx["meta"]["postTokenBalances"][1]["accountIndex"] = _index(LP_ACCOUNT)
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "base_mint_migrated")

    def test_bound_base_flow_amounts_must_balance(self):
        tx = _matching_tx()
        tx["meta"]["postTokenBalances"][1]["uiTokenAmount"]["amount"] = "999"
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "base_mint_migrated")

    def test_transaction_global_sol_debit_does_not_substitute_for_bound_source(self):
        tx = _matching_tx()
        tx["meta"]["preBalances"][_index(SOL_SOURCE)] = 0
        tx["meta"]["preBalances"][_index(BASE_SOURCE)] = 85_000_000_000
        verdict = _verify(tx)
        self.assertTrue(verdict.evidence["sol_flow"]["major_sol_debits"])
        self.assertEqual(verdict.failed_check, "migration_sol_flow")

    def test_sol_credit_must_reach_the_bound_destination_in_full(self):
        cases = (
            (0, 85_000_000_000),
            (84_000_000_000, 1_000_000_000),
        )
        for destination_credit, unrelated_credit in cases:
            with self.subTest(destination_credit=destination_credit):
                tx = _matching_tx()
                tx["meta"]["postBalances"][_index(SOL_DESTINATION)] = (
                    destination_credit
                )
                tx["meta"]["postBalances"][_index(LP_MINT)] = unrelated_credit
                verdict = _verify(tx)
                self.assertEqual(verdict.failed_check, "migration_sol_flow")

    def test_lp_ops_for_another_mint_and_account_do_not_substitute(self):
        tx = _matching_tx()
        tx["meta"]["innerInstructions"][0]["instructions"] = [
            _pumpswap_instruction(),
            _mint_to(mint=UNRELATED_MINT, account=UNRELATED_ACCOUNT),
            _burn(mint=UNRELATED_MINT, account=UNRELATED_ACCOUNT),
        ]
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "lp_mint_and_burn")


class InputHardeningTests(unittest.TestCase):
    def test_none_and_non_dict_transaction_shapes_never_raise(self):
        malformed = (None, [], "tx", 7, {"transaction": None}, {"transaction": {"message": None}})
        for tx in malformed:
            with self.subTest(tx=tx):
                verdict = _verify(tx)
                self.assertEqual(verdict.verdict, EVIDENCE_NOT_ESTABLISHED)
                self.assertEqual(verdict.failed_check, "transaction_shape")

    def test_failed_transaction_meta_is_rejected(self):
        tx = _matching_tx()
        tx["meta"]["err"] = {"InstructionError": [0, "Custom"]}
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "transaction_succeeded")

    def test_wsol_cannot_be_the_base_mint(self):
        verdict = _verify(base_mint=WSOL_MINT)
        self.assertEqual(verdict.failed_check, "base_mint")

    def test_malformed_base_mints_fail_without_raising(self):
        for base_mint in (None, [], {}, True, 7, "", "not a pubkey"):
            with self.subTest(base_mint=base_mint):
                verdict = _verify(base_mint=base_mint)
                self.assertEqual(verdict.failed_check, "base_mint")

    def test_missing_empty_or_role_colliding_context_is_rejected(self):
        invalid_contexts = (
            None,
            replace(_context(), expected_pool=""),
            replace(_context(), expected_pool="not a pubkey"),
            replace(_context(), expected_pool=LP_MINT),
            replace(_context(), sol_source=BASE_SOURCE),
        )
        for context in invalid_contexts:
            with self.subTest(context=context):
                verdict = _verify(context=context)
                self.assertEqual(verdict.failed_check, "migration_context")

    def test_hostile_context_subclass_cannot_escape_fail_closed_boundary(self):
        class HostileContext(MigrationContext):
            def __getattribute__(self, name):
                if name == "expected_pool":
                    raise RuntimeError("hostile attribute")
                return super().__getattribute__(name)

        ordinary = _context()
        hostile = HostileContext(
            ordinary.expected_pool,
            ordinary.lp_mint,
            ordinary.lp_account,
            ordinary.base_source,
            ordinary.base_destination,
            ordinary.sol_source,
            ordinary.sol_destination,
        )
        verdict = _verify(context=hostile)
        self.assertEqual(verdict.verdict, EVIDENCE_NOT_ESTABLISHED)
        self.assertEqual(verdict.failed_check, "transaction_shape")

    def test_context_accounts_must_exist_in_resolved_keys(self):
        verdict = _verify(context=replace(_context(), expected_pool=DIFFERENT_POOL))
        self.assertEqual(verdict.failed_check, "context_accounts")

    def test_missing_token_amount_is_malformed_not_fabricated_as_zero(self):
        for ui_amount in (
            None,
            {},
            {"amount": None},
            {"amount": True},
            {"amount": 1000},
            {"amount": "01000"},
            {"amount": str(1 << 64)},
        ):
            with self.subTest(ui_amount=ui_amount):
                tx = _matching_tx()
                tx["meta"]["postTokenBalances"][0]["uiTokenAmount"] = ui_amount
                verdict = _verify(tx)
                self.assertEqual(verdict.failed_check, "transaction_shape")

    def test_duplicate_token_account_index_is_malformed(self):
        tx = _matching_tx()
        tx["meta"]["postTokenBalances"].append(
            {
                "accountIndex": _index(BASE_SOURCE),
                "mint": UNRELATED_MINT,
                "uiTokenAmount": {"amount": "1"},
            }
        )
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "transaction_shape")

    def test_inner_instructions_none_is_safe_and_establishes_nothing(self):
        tx = _matching_tx()
        tx["meta"]["innerInstructions"] = None
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "pumpswap_amm")

    def test_malformed_inner_instruction_containers_fail_shape(self):
        for groups in ([None], [{"index": 0, "instructions": None}], [{"index": True, "instructions": []}]):
            with self.subTest(groups=groups):
                tx = _matching_tx()
                tx["meta"]["innerInstructions"] = groups
                verdict = _verify(tx)
                self.assertEqual(verdict.failed_check, "transaction_shape")

    def test_present_outer_stack_height_must_be_null_or_one(self):
        for value in ([], False, 0, 2):
            with self.subTest(value=value):
                tx = _matching_tx()
                tx["transaction"]["message"]["instructions"][0][
                    "stackHeight"
                ] = value
                verdict = _verify(tx)
                self.assertEqual(verdict.failed_check, "transaction_shape")

        for value in (None, 1):
            with self.subTest(value=value):
                tx = _matching_tx()
                tx["transaction"]["message"]["instructions"][0][
                    "stackHeight"
                ] = value
                self.assertTrue(_verify(tx).is_match)

    def test_malformed_loaded_addresses_fail_shape(self):
        bad_loaded = ([], {"writable": None}, {"readonly": [{}]})
        for loaded in bad_loaded:
            with self.subTest(loaded=loaded):
                tx = _matching_tx()
                tx["meta"]["loadedAddresses"] = loaded
                verdict = _verify(tx)
                self.assertEqual(verdict.failed_check, "transaction_shape")

    def test_invalid_loaded_index_fails_shape(self):
        tx = _matching_tx()
        instruction = tx["meta"]["innerInstructions"][0]["instructions"][0]
        instruction.pop("programId")
        instruction["programIdIndex"] = 999
        instruction["accounts"] = [
            _index(account)
            for account in BOUND_ACCOUNTS
        ]
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "transaction_shape")

    def test_bound_opaque_instruction_data_must_be_base58_and_nonempty(self):
        cases = (
            ([], "transaction_shape"),
            ("0", "transaction_shape"),
            ("", "bound_migration_instruction_group"),
        )
        for data, failed_check in cases:
            with self.subTest(data=data):
                tx = _matching_tx()
                tx["meta"]["innerInstructions"][0]["instructions"][0][
                    "data"
                ] = data
                verdict = _verify(tx)
                self.assertEqual(verdict.failed_check, failed_check)

    def test_program_and_account_reference_encodings_must_be_coherent(self):
        tx = _matching_tx()
        outer = tx["transaction"]["message"]["instructions"][0]
        outer["accounts"] = [
            _index(BASE_MINT),
            _index(BASE_SOURCE),
            _index(SOL_SOURCE),
        ]
        self.assertEqual(_verify(tx).failed_check, "transaction_shape")

        tx = _matching_tx()
        instruction = tx["meta"]["innerInstructions"][0]["instructions"][0]
        instruction.pop("programId")
        instruction["programIdIndex"] = _index(PUMPSWAP_AMM_PROGRAM)
        self.assertEqual(_verify(tx).failed_check, "transaction_shape")

    def test_parsed_token_program_label_must_match_program_id(self):
        tx = _matching_tx()
        for instruction in tx["meta"]["innerInstructions"][0]["instructions"][1:]:
            instruction["program"] = "spl-token-2022"
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "lp_mint_and_burn")

    def test_conflicting_direct_and_indexed_program_ids_fail_shape(self):
        tx = _matching_tx()
        outer = tx["transaction"]["message"]["instructions"][0]
        outer["programIdIndex"] = _index(PUMPSWAP_AMM_PROGRAM)
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "transaction_shape")

    def test_boolean_lamport_balance_is_not_an_integer(self):
        tx = _matching_tx()
        tx["meta"]["preBalances"][_index(SOL_SOURCE)] = True
        verdict = _verify(tx)
        self.assertEqual(verdict.failed_check, "transaction_shape")

    def test_lamport_balances_must_be_json_u64_integers(self):
        for value in ("85000000000", -1, 1 << 64, 85_000_000_000.0):
            with self.subTest(value=value):
                tx = _matching_tx()
                tx["meta"]["preBalances"][_index(SOL_SOURCE)] = value
                verdict = _verify(tx)
                self.assertEqual(verdict.failed_check, "transaction_shape")


class LamportBoundaryTests(unittest.TestCase):
    def test_exactly_eighty_sol_passes_and_one_lamport_less_fails(self):
        tx = _matching_tx()
        tx["meta"]["preBalances"][_index(SOL_SOURCE)] = 80_000_000_000
        tx["meta"]["postBalances"][_index(SOL_DESTINATION)] = 80_000_000_000
        self.assertEqual(_verify(tx).verdict, EVIDENCE_MATCHED)

        tx["meta"]["preBalances"][_index(SOL_SOURCE)] = 79_999_999_999
        tx["meta"]["postBalances"][_index(SOL_DESTINATION)] = 79_999_999_999
        self.assertEqual(_verify(tx).failed_check, "migration_sol_flow")

    def test_major_debit_floor_is_exactly_one_sol(self):
        tx = _matching_tx()
        tx["meta"]["preBalances"][_index(BASE_SOURCE)] = 1_000_000_000
        verdict = _verify(tx)
        accounts = {row["account"] for row in verdict.evidence["sol_flow"]["major_sol_debits"]}
        self.assertIn(BASE_SOURCE, accounts)

        tx["meta"]["preBalances"][_index(BASE_SOURCE)] = 999_999_999
        verdict = _verify(tx)
        accounts = {row["account"] for row in verdict.evidence["sol_flow"]["major_sol_debits"]}
        self.assertNotIn(BASE_SOURCE, accounts)


if __name__ == "__main__":
    unittest.main()
