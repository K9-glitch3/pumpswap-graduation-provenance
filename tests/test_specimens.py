"""Run the verifier against materialized real-transaction specimens.

These tests are **conditional**. Until you materialize fixtures with
``tools/fetch_specimens.py`` (which needs your own RPC endpoint), there is
nothing in ``specimens/raw/`` and the whole module skips, so CI stays green
without network access. Once fixtures exist, each one is a hard check: the
verifier must reproduce the manifest's expected verdict for that real
transaction.

A genuine specimen this verifier does NOT match is a real result, not a flaky
test — it would mean the strict, account-bound predicate is stricter than the
shape of real graduation transactions, and the verifier (not the specimen)
needs revisiting.
"""

import json
import os
import unittest

from graduation_provenance import EVIDENCE_MATCHED, EVIDENCE_NOT_ESTABLISHED, LpAccountState, screen_pool

_RAW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "specimens", "raw")

_VERDICT = {
    "GENUINE_PUMP_FUN_GRADUATION": EVIDENCE_MATCHED,
    "NOT_GENUINE_PUMP_FUN_GRADUATION": EVIDENCE_NOT_ESTABLISHED,
}


def _load_fixtures():
    if not os.path.isdir(_RAW_DIR):
        return []
    fixtures = []
    for name in sorted(os.listdir(_RAW_DIR)):
        if name.endswith(".json"):
            with open(os.path.join(_RAW_DIR, name), encoding="utf-8") as handle:
                fixtures.append(json.load(handle))
    return fixtures


class SpecimenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = _load_fixtures()
        if not cls.fixtures:
            raise unittest.SkipTest(
                "no materialized specimens; run tools/fetch_specimens.py with an RPC_URL"
            )

    def test_each_specimen_matches_its_expected_verdict(self):
        for fixture in self.fixtures:
            with self.subTest(specimen=fixture["name"]):
                expected = _VERDICT[fixture["expected_verdict"]]
                states = [LpAccountState(**state) for state in fixture.get("lp_account_states", [])]
                pool = fixture.get("expected_pool")
                if pool is None:
                    self.skipTest(f"{fixture['name']}: pool not resolved at fetch time")
                verdict = screen_pool(
                    fixture["transaction"],
                    pool,
                    fixture["base_mint"],
                    states,
                )
                self.assertEqual(
                    verdict.verdict,
                    expected,
                    f"{fixture['name']}: expected {fixture['expected_verdict']} "
                    f"({expected}), got {verdict.verdict} at check {verdict.failed_check}",
                )

    def test_fetched_evidence_agrees_with_the_manifest(self):
        # Guards against a truncated or wrong fetch: the LP mint recorded in the
        # manifest must be the one whose state was fetched.
        for fixture in self.fixtures:
            with self.subTest(specimen=fixture["name"]):
                recorded = fixture.get("recorded_evidence", {})
                if not recorded.get("lp_mint"):
                    continue
                fetched_mints = {s["lp_mint"] for s in fixture.get("lp_account_states", [])}
                self.assertIn(recorded["lp_mint"], fetched_mints)


if __name__ == "__main__":
    unittest.main()
