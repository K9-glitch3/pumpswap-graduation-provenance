"""Tests for the authenticate, derive, then verify convenience wrapper."""

from __future__ import annotations

import copy
import unittest

from graduation_provenance import (
    EVIDENCE_MATCHED,
    EVIDENCE_NOT_ESTABLISHED,
    PUMPSWAP_AMM_PROGRAM,
    propose_migration_context,
    screen_pool,
    verify_migration_evidence,
)
from tests.synthetic_migration import BASE_MINT, POOL, make_bundle


class ScreenPoolTests(unittest.TestCase):
    def test_derivation_is_from_authenticated_create_pool_roles(self):
        bundle = make_bundle()
        context, reason = propose_migration_context(
            bundle["tx"], POOL, BASE_MINT, bundle["pool"]
        )
        self.assertIsNone(reason)
        self.assertEqual(context, bundle["context"])

    def test_wrapper_delegates_to_explicit_verifier(self):
        bundle = make_bundle()
        screened = screen_pool(
            bundle["tx"], POOL, BASE_MINT, bundle["states"], bundle["pool"]
        )
        strict = verify_migration_evidence(
            bundle["tx"],
            BASE_MINT,
            bundle["context"],
            bundle["states"],
            bundle["pool"],
        )
        self.assertEqual(screened.verdict, EVIDENCE_MATCHED)
        self.assertEqual(screened.verdict, strict.verdict)
        self.assertEqual(screened.evidence, strict.evidence)

    def test_direct_create_pool_does_not_gain_pump_fun_provenance(self):
        bundle = make_bundle()
        tx = bundle["tx"]
        create_pool = copy.deepcopy(
            tx["meta"]["innerInstructions"][0]["instructions"][2]
        )
        create_pool["stackHeight"] = 1
        tx["transaction"]["message"]["instructions"] = [create_pool]
        tx["meta"]["innerInstructions"] = []
        verdict = screen_pool(
            tx, POOL, BASE_MINT, bundle["states"], bundle["pool"]
        )
        self.assertEqual(verdict.verdict, EVIDENCE_NOT_ESTABLISHED)
        self.assertEqual(verdict.failed_check, "derive:migration_frame_not_found")

    def test_co_mentioned_wrong_pool_cannot_be_derived(self):
        bundle = make_bundle()
        # Add a valid address to both program instructions. Ordered role zero
        # remains the actual pool, so co-mentioning cannot authenticate it.
        wrong_pool = PUMPSWAP_AMM_PROGRAM
        bundle["tx"]["transaction"]["message"]["instructions"][0]["accounts"].append(
            wrong_pool
        )
        bundle["tx"]["meta"]["innerInstructions"][0]["instructions"][2][
            "accounts"
        ].append(wrong_pool)
        verdict = screen_pool(
            bundle["tx"],
            wrong_pool,
            BASE_MINT,
            bundle["states"],
            bundle["pool"],
        )
        self.assertEqual(verdict.verdict, EVIDENCE_NOT_ESTABLISHED)
        self.assertTrue(verdict.failed_check.startswith("derive:"))

    def test_missing_pool_snapshot_and_malformed_transaction_fail_closed(self):
        bundle = make_bundle()
        missing = screen_pool(bundle["tx"], POOL, BASE_MINT, bundle["states"], None)
        self.assertEqual(missing.failed_check, "derive:pool_account_invalid")
        malformed = screen_pool({}, POOL, BASE_MINT, bundle["states"], bundle["pool"])
        self.assertEqual(malformed.verdict, EVIDENCE_NOT_ESTABLISHED)
        self.assertTrue(malformed.failed_check.startswith("derive:"))


if __name__ == "__main__":
    unittest.main()
