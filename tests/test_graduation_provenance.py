"""Adversarial unit tests for the pool-authenticated verifier."""

from __future__ import annotations

import copy
import unittest
from dataclasses import replace

from graduation_provenance import (
    EVIDENCE_MATCHED,
    EVIDENCE_NOT_ESTABLISHED,
    PUMP_FUN_PROGRAMS,
    PUMPSWAP_AMM_PROGRAM,
    TOKEN_2022_PROGRAM,
    TOKEN_PROGRAM,
    LpAccountState,
    MigrationContext,
    PoolAccountEvidence,
    build_evidence,
    propose_migration_context,
    screen_pool,
    verify_migration_evidence,
)
from tests.synthetic_migration import (
    BASE_AMOUNT,
    BASE_CURVE,
    BASE_MINT,
    LP_ACCOUNT,
    LP_MINT,
    POOL,
    make_bundle,
)


_DEFAULT = object()


def _verify(
    bundle, *, context=_DEFAULT, states=_DEFAULT, pool=_DEFAULT, tx=_DEFAULT
):
    return verify_migration_evidence(
        bundle["tx"] if tx is _DEFAULT else tx,
        BASE_MINT,
        bundle["context"] if context is _DEFAULT else context,
        bundle["states"] if states is _DEFAULT else states,
        bundle["pool"] if pool is _DEFAULT else pool,
    )


def _inner(bundle):
    return bundle["tx"]["meta"]["innerInstructions"][0]["instructions"]


def _remove_operation(bundle, operation):
    _inner(bundle)[:] = [
        instruction
        for instruction in _inner(bundle)
        if (instruction.get("parsed") or {}).get("type") != operation
    ]


class AuthenticatedMatchTests(unittest.TestCase):
    def test_complete_synthetic_frame_matches(self):
        bundle = make_bundle()
        verdict = _verify(bundle)
        self.assertEqual(verdict.verdict, EVIDENCE_MATCHED)
        self.assertIsNone(verdict.failed_check)
        self.assertEqual(verdict.evidence["migration_frame_count"], 1)
        self.assertEqual(
            verdict.evidence["migration_operations"]["base_amount"], BASE_AMOUNT
        )

    def test_derive_then_verify_agrees_with_explicit_context(self):
        bundle = make_bundle()
        context, reason = propose_migration_context(
            bundle["tx"], POOL, BASE_MINT, bundle["pool"]
        )
        self.assertIsNone(reason)
        self.assertEqual(context, bundle["context"])
        screened = screen_pool(
            bundle["tx"],
            POOL,
            BASE_MINT,
            bundle["states"],
            bundle["pool"],
        )
        self.assertEqual(screened.verdict, _verify(bundle).verdict)

    def test_token_2022_rpc_label_is_not_treated_as_program_identity(self):
        bundle = make_bundle()
        for instruction in _inner(bundle):
            if instruction.get("programId") == TOKEN_2022_PROGRAM:
                instruction["program"] = "spl-token"
        self.assertTrue(_verify(bundle).is_match)

    def test_impossible_spl_program_label_fails_closed(self):
        bundle = make_bundle()
        _inner(bundle)[0]["program"] = "system"
        self.assertEqual(_verify(bundle).failed_check, "transaction_shape")

    def test_loaded_addresses_are_part_of_the_resolved_key_space(self):
        bundle = make_bundle()
        keys = bundle["tx"]["transaction"]["message"]["accountKeys"]
        keys.remove(PUMPSWAP_AMM_PROGRAM)
        bundle["tx"]["meta"]["loadedAddresses"] = {
            "writable": [],
            "readonly": [PUMPSWAP_AMM_PROGRAM],
        }
        self.assertTrue(_verify(bundle).is_match)

    def test_compiled_program_and_account_indexes_resolve(self):
        bundle = make_bundle()
        message = bundle["tx"]["transaction"]["message"]
        keys = message["accountKeys"]
        create_pool = _inner(bundle)[2]
        create_pool["programIdIndex"] = keys.index(create_pool.pop("programId"))
        create_pool["accounts"] = [keys.index(account) for account in create_pool["accounts"]]
        self.assertTrue(_verify(bundle).is_match)


class SubtreeConservationTests(unittest.TestCase):
    def test_exactly_eighty_sol_passes_and_one_lamport_less_fails(self):
        exact = make_bundle(quote_amount=80_000_000_000)
        self.assertTrue(_verify(exact).is_match)
        below = make_bundle(quote_amount=79_999_999_999)
        verdict = _verify(below)
        self.assertEqual(verdict.failed_check, "migration_sol_flow")

    def test_bound_curve_debit_has_its_own_eighty_sol_floor(self):
        exact = make_bundle(quote_amount=80_000_000_000)
        keys = exact["tx"]["transaction"]["message"]["accountKeys"]
        curve_index = keys.index(BASE_CURVE)
        exact["tx"]["meta"]["preBalances"][curve_index] = 90_000_000_000
        exact["tx"]["meta"]["postBalances"][curve_index] = 10_000_000_000
        self.assertTrue(_verify(exact).is_match)

        below = make_bundle(quote_amount=80_000_000_000)
        below["tx"]["meta"]["preBalances"][curve_index] = 90_000_000_000
        below["tx"]["meta"]["postBalances"][curve_index] = 10_000_000_001
        verdict = _verify(below)
        self.assertEqual(verdict.failed_check, "migration_sol_flow")
        self.assertEqual(
            verdict.evidence["migration_operations"]["bound_curve_debit_lamports"],
            79_999_999_999,
        )

    def test_bound_curve_debit_must_cover_create_pool_quote_transfer(self):
        bundle = make_bundle()
        keys = bundle["tx"]["transaction"]["message"]["accountKeys"]
        curve_index = keys.index(BASE_CURVE)
        bundle["tx"]["meta"]["preBalances"][curve_index] = 90_000_000_000
        bundle["tx"]["meta"]["postBalances"][curve_index] = 10_000_000_000
        verdict = _verify(bundle)
        self.assertEqual(verdict.failed_check, "migration_sol_flow")

    def test_missing_curve_to_create_pool_input_transfer_fails(self):
        bundle = make_bundle()
        del _inner(bundle)[0]
        verdict = _verify(bundle)
        self.assertEqual(verdict.failed_check, "base_mint_migrated")

    def test_noncanonical_bound_amount_is_malformed_evidence(self):
        bundle = make_bundle()
        _inner(bundle)[0]["parsed"]["info"]["tokenAmount"]["amount"] = "01"
        verdict = _verify(bundle)
        self.assertEqual(verdict.failed_check, "migration_operations_well_formed")
        self.assertEqual(
            verdict.evidence["migration_operations"]["invalid_bound_operation_count"],
            1,
        )

    def test_create_pool_transfer_must_match_instruction_amount(self):
        bundle = make_bundle()
        _inner(bundle)[3]["parsed"]["info"]["tokenAmount"]["amount"] = str(
            BASE_AMOUNT - 1
        )
        self.assertEqual(_verify(bundle).failed_check, "base_mint_migrated")

    def test_sync_native_is_required_in_the_migration_frame(self):
        bundle = make_bundle()
        _remove_operation(bundle, "syncNative")
        self.assertEqual(_verify(bundle).failed_check, "migration_sol_flow")

    def test_transaction_global_quote_transfer_cannot_substitute_for_cp_child(self):
        bundle = make_bundle()
        # Moving the otherwise exact transfer to stack 2 makes it a migration
        # child rather than a CreatePool child.
        _inner(bundle)[4]["stackHeight"] = 2
        self.assertEqual(_verify(bundle).failed_check, "migration_sol_flow")

    def test_create_pool_role_swap_breaks_pool_authentication_binding(self):
        bundle = make_bundle()
        accounts = _inner(bundle)[2]["accounts"]
        accounts[9], accounts[10] = accounts[10], accounts[9]
        self.assertEqual(_verify(bundle).failed_check, "migration_create_pool_binding")

    def test_migration_role_swap_breaks_create_pool_binding(self):
        bundle = make_bundle()
        accounts = bundle["tx"]["transaction"]["message"]["instructions"][0]["accounts"]
        accounts[17], accounts[18] = accounts[18], accounts[17]
        self.assertEqual(_verify(bundle).failed_check, "migration_create_pool_binding")

    def test_fixed_global_and_event_roles_are_not_merely_co_mentioned(self):
        for migration_index in (0, 25):
            bundle = make_bundle()
            accounts = bundle["tx"]["transaction"]["message"]["instructions"][0]["accounts"]
            accounts[migration_index] = BASE_CURVE
            with self.subTest(migration_index=migration_index):
                self.assertEqual(
                    _verify(bundle).failed_check, "migration_create_pool_binding"
                )

        bundle = make_bundle()
        migration = bundle["tx"]["transaction"]["message"]["instructions"][0]
        migration["accounts"][14] = BASE_CURVE
        _inner(bundle)[2]["accounts"][1] = BASE_CURVE
        self.assertEqual(_verify(bundle).failed_check, "migration_create_pool_binding")

    def test_multiple_complete_frames_are_ambiguous(self):
        bundle = make_bundle()
        message = bundle["tx"]["transaction"]["message"]
        message["instructions"].append(copy.deepcopy(message["instructions"][0]))
        second_group = copy.deepcopy(bundle["tx"]["meta"]["innerInstructions"][0])
        second_group["index"] = 1
        bundle["tx"]["meta"]["innerInstructions"].append(second_group)
        verdict = _verify(bundle)
        self.assertEqual(verdict.failed_check, "migration_create_pool_binding")
        self.assertEqual(verdict.evidence["migration_frame_count"], 2)


class LpDestructionTests(unittest.TestCase):
    def test_synthetic_programs_and_authentic_pool_without_burn_fails_only_lp_gate(self):
        """Synthetic discriminator: all gates through WSOL flow pass; burn is absent."""
        bundle = make_bundle()
        _remove_operation(bundle, "burn")
        verdict = _verify(bundle)
        self.assertEqual(verdict.failed_check, "lp_mint_and_burn")
        self.assertTrue(verdict.evidence["pool_authenticated"])
        self.assertEqual(verdict.evidence["migration_frame_count"], 1)
        self.assertTrue(verdict.evidence["migration_operations"]["base_migration_flow"])
        self.assertTrue(verdict.evidence["migration_operations"]["wsol_migration_flow"])

    def test_burn_must_be_a_direct_migration_child(self):
        bundle = make_bundle()
        burn = next(
            instruction
            for instruction in _inner(bundle)
            if (instruction.get("parsed") or {}).get("type") == "burn"
        )
        burn["stackHeight"] = 3
        self.assertEqual(_verify(bundle).failed_check, "lp_mint_and_burn")

    def test_lp_account_close_is_required_in_the_same_frame(self):
        bundle = make_bundle()
        _remove_operation(bundle, "closeAccount")
        self.assertEqual(_verify(bundle).failed_check, "lp_account_closed_in_frame")

    def test_lp_amounts_must_be_matching_positive_canonical_u64s(self):
        for amount in ("0", "01", "-1", str(1 << 64)):
            with self.subTest(amount=amount):
                bundle = make_bundle()
                burn = next(
                    instruction
                    for instruction in _inner(bundle)
                    if (instruction.get("parsed") or {}).get("type") == "burn"
                )
                burn["parsed"]["info"]["amount"] = amount
                self.assertEqual(
                    _verify(bundle).failed_check, "migration_operations_well_formed"
                )

    def test_external_lp_proof_is_fail_closed(self):
        bundle = make_bundle()
        cases = (
            None,
            [],
            [replace(bundle["states"][0], destination_closed=False)],
            [replace(bundle["states"][0], lp_supply_zero=False)],
            [replace(bundle["states"][0], destination_closed=1)],
            [replace(bundle["states"][0], destination=POOL)],
            bundle["states"] * 2,
        )
        for states in cases:
            with self.subTest(states=states):
                verdict = _verify(bundle, states=states)
                self.assertEqual(verdict.failed_check, "lp_account_closed_supply_zero")

    def test_lp_state_subclass_is_rejected(self):
        class StatefulLp(LpAccountState):
            pass

        bundle = make_bundle()
        state = StatefulLp(LP_MINT, LP_ACCOUNT, True, True)
        self.assertEqual(
            _verify(bundle, states=[state]).failed_check,
            "lp_account_closed_supply_zero",
        )


class PoolAuthenticationTests(unittest.TestCase):
    def test_wrong_pool_false_positive_reproducer_is_closed(self):
        bundle = make_bundle()
        verdict = screen_pool(
            bundle["tx"],
            TOKEN_PROGRAM,
            BASE_MINT,
            bundle["states"],
            bundle["pool"],
        )
        self.assertEqual(verdict.verdict, EVIDENCE_NOT_ESTABLISHED)
        self.assertEqual(verdict.failed_check, "derive:pool_not_authenticated")

    def test_pool_address_owner_bytes_and_slot_are_all_bound(self):
        bundle = make_bundle()
        cases = (
            (replace(bundle["pool"], address=TOKEN_PROGRAM), "pool_authenticated"),
            (replace(bundle["pool"], owner=TOKEN_PROGRAM), "pool_account"),
            (replace(bundle["pool"], data_base64="not base64"), "pool_authenticated"),
            (replace(bundle["pool"], context_slot=99), "pool_authenticated"),
            (replace(bundle["pool"], context_slot=True), "pool_account"),
        )
        for pool, failed_check in cases:
            with self.subTest(pool=pool):
                self.assertEqual(_verify(bundle, pool=pool).failed_check, failed_check)

    def test_pool_evidence_subclass_is_rejected(self):
        class StatefulPool(PoolAccountEvidence):
            pass

        bundle = make_bundle()
        pool = bundle["pool"]
        hostile = StatefulPool(pool.address, pool.owner, pool.data_base64, pool.context_slot)
        self.assertEqual(_verify(bundle, pool=hostile).failed_check, "pool_account")

    def test_pool_snapshot_for_another_base_mint_fails(self):
        bundle = make_bundle()
        verdict = verify_migration_evidence(
            bundle["tx"], TOKEN_PROGRAM, bundle["context"], bundle["states"], bundle["pool"]
        )
        self.assertEqual(verdict.failed_check, "pool_authenticated")


class InputHardeningTests(unittest.TestCase):
    def test_none_and_non_dict_transaction_shapes_never_raise(self):
        bundle = make_bundle()
        for tx in (None, [], "tx", 7, {}, {"transaction": None}):
            with self.subTest(tx=tx):
                verdict = _verify(bundle, tx=tx)
                self.assertEqual(verdict.verdict, EVIDENCE_NOT_ESTABLISHED)
                self.assertEqual(verdict.failed_check, "transaction_shape")

    def test_oversized_numeric_strings_fail_without_big_integer_conversion(self):
        bundle = make_bundle()
        _inner(bundle)[5]["parsed"]["info"]["amount"] = "9" * 100_000
        verdict = _verify(bundle)
        self.assertEqual(verdict.failed_check, "migration_operations_well_formed")

    def test_container_subclasses_are_rejected_before_they_can_switch(self):
        class StatefulDict(dict):
            pass

        bundle = make_bundle()
        hostile = StatefulDict(bundle["tx"])
        self.assertEqual(_verify(bundle, tx=hostile).failed_check, "transaction_shape")

    def test_stateful_context_subclass_cannot_switch_mid_check(self):
        class SwitchingContext(MigrationContext):
            reads = 0

            def __getattribute__(self, name):
                if name == "expected_pool":
                    type(self).reads += 1
                    if type(self).reads > 1:
                        return TOKEN_PROGRAM
                return super().__getattribute__(name)

        bundle = make_bundle()
        c = bundle["context"]
        hostile = SwitchingContext(*c.__dict__.values())
        verdict = _verify(bundle, context=hostile)
        self.assertEqual(verdict.failed_check, "migration_context")
        self.assertEqual(SwitchingContext.reads, 0)

    def test_failed_transaction_is_rejected(self):
        bundle = make_bundle()
        bundle["tx"]["meta"]["err"] = {"InstructionError": [0, "Custom"]}
        self.assertEqual(_verify(bundle).failed_check, "transaction_succeeded")

    def test_context_role_collisions_and_malformed_pubkeys_fail(self):
        bundle = make_bundle()
        contexts = (
            None,
            replace(bundle["context"], expected_pool=""),
            replace(bundle["context"], base_source=bundle["context"].sol_source),
            replace(bundle["context"], lp_mint=BASE_MINT),
        )
        for context in contexts:
            with self.subTest(context=context):
                self.assertEqual(_verify(bundle, context=context).failed_check, "migration_context")

    def test_malformed_loaded_addresses_fail_transaction_shape(self):
        bundle = make_bundle()
        for loaded in ([], {"writable": None}, {"readonly": [{}]}):
            with self.subTest(loaded=loaded):
                tx = copy.deepcopy(bundle["tx"])
                tx["meta"]["loadedAddresses"] = loaded
                self.assertEqual(_verify(bundle, tx=tx).failed_check, "transaction_shape")

    def test_impossible_stack_transition_fails_transaction_shape(self):
        bundle = make_bundle()
        _inner(bundle)[0]["stackHeight"] = 3
        self.assertEqual(_verify(bundle).failed_check, "transaction_shape")

    def test_unsupported_pump_fun_program_fails_closed(self):
        bundle = make_bundle()
        unsupported = next(program for program in PUMP_FUN_PROGRAMS if program != bundle["tx"]["transaction"]["message"]["instructions"][0]["programId"])
        keys = bundle["tx"]["transaction"]["message"]["accountKeys"]
        keys.append(unsupported)
        bundle["tx"]["meta"]["preBalances"].append(0)
        bundle["tx"]["meta"]["postBalances"].append(0)
        migration = bundle["tx"]["transaction"]["message"]["instructions"][0]
        migration["programId"] = unsupported
        migration["accounts"][-1] = unsupported
        verdict = _verify(bundle)
        self.assertTrue(verdict.evidence["has_pump_fun_program"])
        self.assertEqual(verdict.failed_check, "migration_create_pool_binding")

    def test_missing_pool_evidence_fails_closed(self):
        bundle = make_bundle()
        self.assertEqual(_verify(bundle, pool=None).failed_check, "pool_account")

    def test_build_evidence_never_raises_on_hostile_iterable(self):
        class HostileIterable:
            def __iter__(self):
                raise RuntimeError("do not escape")

        bundle = make_bundle()
        evidence = build_evidence(
            bundle["tx"], BASE_MINT, bundle["context"], HostileIterable(), bundle["pool"]
        )
        self.assertFalse(evidence["lp_account_proof"])
        self.assertTrue(evidence["lp_account_states_invalid"])


if __name__ == "__main__":
    unittest.main()
