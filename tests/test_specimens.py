"""Mandatory gate over five committed mainnet transaction specimens."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import unittest

from graduation_provenance import (
    EVIDENCE_MATCHED,
    EVIDENCE_NOT_ESTABLISHED,
    PUMP_FUN_PROGRAMS,
    PUMPSWAP_AMM_PROGRAM,
    LpAccountState,
    PoolAccountEvidence,
    propose_migration_context,
    screen_pool,
    verify_migration_evidence,
)
from pumpswap_decoder import PUMP_AMM_PROGRAM, decode_pool_b64

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RAW_DIR = os.path.join(_ROOT, "specimens", "raw")
_MANIFEST = os.path.join(_ROOT, "specimens", "specimen_manifest.json")
_SAFE_NAME = re.compile(r"^[a-z0-9_]+$")

_VERDICT = {
    "GENUINE_PUMP_FUN_GRADUATION": EVIDENCE_MATCHED,
    "NOT_GENUINE_PUMP_FUN_GRADUATION": EVIDENCE_NOT_ESTABLISHED,
}
_FIXTURE_KEYS = {
    "name",
    "signature",
    "slot",
    "base_mint",
    "expected_verdict",
    "expected_pool",
    "pool_account",
    "recorded_evidence",
    "transaction",
    "lp_account_states",
}
_MANIFEST_ROW_KEYS = {
    "name",
    "signature",
    "slot",
    "transaction_sha256",
    "base_mint",
    "expected_pool",
    "expected_verdict",
    "recorded_evidence",
}


def _load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _load_manifest():
    manifest = _load_json(_MANIFEST)
    if type(manifest) is not dict or type(manifest.get("specimens")) is not list:
        raise ValueError("malformed specimen manifest")
    return manifest


def _load_fixture_files():
    if not os.path.isdir(_RAW_DIR):
        raise ValueError("specimens/raw is missing")
    fixtures = {}
    for filename in sorted(os.listdir(_RAW_DIR)):
        if filename.endswith(".json"):
            fixtures[filename[:-5]] = _load_json(os.path.join(_RAW_DIR, filename))
    return fixtures


def _transaction_sha256(tx):
    canonical = json.dumps(
        tx,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _manifest_rows(manifest):
    rows = manifest["specimens"]
    names = [row.get("name") for row in rows if type(row) is dict]
    signatures = [row.get("signature") for row in rows if type(row) is dict]
    if len(rows) != 5 or len(names) != 5:
        raise ValueError("manifest must contain exactly five object rows")
    if any(set(row) != _MANIFEST_ROW_KEYS for row in rows if type(row) is dict):
        raise ValueError("manifest row fields do not match the committed schema")
    if len(set(names)) != len(names) or len(set(signatures)) != len(signatures):
        raise ValueError("manifest names and signatures must be unique")
    if any(type(name) is not str or _SAFE_NAME.fullmatch(name) is None for name in names):
        raise ValueError("unsafe specimen name")
    if set(manifest.get("expected_verdict_values", [])) != set(_VERDICT):
        raise ValueError("manifest verdict vocabulary drifted")
    if sum(row.get("expected_verdict") == "GENUINE_PUMP_FUN_GRADUATION" for row in rows) != 4:
        raise ValueError("manifest must contain four positives")
    if sum(row.get("expected_verdict") == "NOT_GENUINE_PUMP_FUN_GRADUATION" for row in rows) != 1:
        raise ValueError("manifest must contain one negative")
    return {row["name"]: row for row in rows}


def _assert_exact_fixture_set(rows, fixtures):
    if set(rows) != set(fixtures):
        missing = sorted(set(rows) - set(fixtures))
        extra = sorted(set(fixtures) - set(rows))
        raise ValueError(f"fixture set mismatch: missing={missing}, extra={extra}")


def _writable_transaction_keys(tx):
    message = tx["transaction"]["message"]
    keys = []
    for item in message["accountKeys"]:
        if type(item) is dict and item.get("writable") is True:
            keys.append(item.get("pubkey"))
    loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
    keys.extend(loaded.get("writable") or [])
    return keys


def _transaction_programs(tx):
    programs = set()
    message = tx["transaction"]["message"]
    for instruction in message["instructions"]:
        if type(instruction) is dict and type(instruction.get("programId")) is str:
            programs.add(instruction["programId"])
    for group in tx["meta"].get("innerInstructions") or []:
        for instruction in group.get("instructions") or []:
            if type(instruction) is dict and type(instruction.get("programId")) is str:
                programs.add(instruction["programId"])
    return programs


def _resolved_keys(tx):
    keys = [
        item["pubkey"] if type(item) is dict else item
        for item in tx["transaction"]["message"]["accountKeys"]
    ]
    loaded = tx["meta"].get("loadedAddresses") or {}
    return keys + (loaded.get("writable") or []) + (loaded.get("readonly") or [])


def _validate_fixture(row, fixture):
    if type(fixture) is not dict or set(fixture) != _FIXTURE_KEYS:
        raise ValueError("fixture fields do not match the committed schema")
    for field in (
        "name",
        "signature",
        "slot",
        "base_mint",
        "expected_verdict",
        "expected_pool",
        "recorded_evidence",
    ):
        if fixture.get(field) != row.get(field):
            raise ValueError(f"fixture {field} disagrees with manifest")

    tx = fixture.get("transaction")
    if type(tx) is not dict or not tx:
        raise ValueError("transaction is absent or empty")
    meta = tx.get("meta")
    wire_tx = tx.get("transaction")
    if (
        tx.get("slot") != row["slot"]
        or type(meta) is not dict
        or "err" not in meta
        or meta["err"] is not None
        or type(wire_tx) is not dict
        or type(wire_tx.get("message")) is not dict
        or type(wire_tx["message"].get("accountKeys")) is not list
        or not wire_tx["message"]["accountKeys"]
        or type(wire_tx["message"].get("instructions")) is not list
        or not wire_tx["message"]["instructions"]
    ):
        raise ValueError("transaction slot or success status disagrees")
    signatures = wire_tx.get("signatures")
    if type(signatures) is not list or not signatures or signatures[0] != row["signature"]:
        raise ValueError("transaction signature disagrees")
    if _transaction_sha256(tx) != row["transaction_sha256"]:
        raise ValueError("transaction content disagrees with manifest digest")
    if row["expected_pool"] not in _writable_transaction_keys(tx):
        raise ValueError("expected pool is not a writable transaction key")

    pool = fixture.get("pool_account")
    if type(pool) is not dict or set(pool) != {
        "address",
        "owner",
        "context_slot",
        "data_base64",
    }:
        raise ValueError("pool account evidence is absent or malformed")
    if pool["address"] != row["expected_pool"] or pool["owner"] != PUMP_AMM_PROGRAM:
        raise ValueError("pool account identity or owner disagrees")
    if type(pool["context_slot"]) is not int or pool["context_slot"] < row["slot"]:
        raise ValueError("pool account context slot is invalid")
    state = decode_pool_b64(pool["data_base64"], owner=pool["owner"])
    if state.token_mint != row["base_mint"]:
        raise ValueError("decoded pool mint disagrees")

    states = fixture.get("lp_account_states")
    if type(states) is not list:
        raise ValueError("LP states are not a list")
    recorded = row["recorded_evidence"]
    if "lp_mint" in recorded:
        if len(states) != 1 or type(states[0]) is not dict:
            raise ValueError("positive specimen must have exactly one LP state")
        state_row = states[0]
        if set(state_row) != {
            "lp_mint",
            "destination",
            "destination_closed",
            "lp_supply_zero",
        }:
            raise ValueError("LP state fields disagree with schema")
        if (
            state_row["lp_mint"] != recorded["lp_mint"]
            or state_row["destination"] != recorded["lp_account"]
            or state_row["destination_closed"] is not True
            or state_row["lp_supply_zero"] is not True
        ):
            raise ValueError("LP state disagrees with manifest evidence")
        if state.lp_mint != recorded["lp_mint"]:
            raise ValueError("decoded pool LP mint disagrees with manifest evidence")
    elif states:
        raise ValueError("negative specimen unexpectedly carries LP proof")
    return state


class SpecimenGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = _load_manifest()
        cls.rows = _manifest_rows(cls.manifest)
        cls.fixtures = _load_fixture_files()
        _assert_exact_fixture_set(cls.rows, cls.fixtures)

    def test_manifest_and_committed_fixture_set_are_exact(self):
        self.assertEqual(len(self.rows), 5)
        self.assertEqual(set(self.rows), set(self.fixtures))

    def test_fixture_copies_and_authenticated_pool_snapshots_match_manifest(self):
        for name, row in self.rows.items():
            with self.subTest(specimen=name):
                _validate_fixture(row, self.fixtures[name])

    def test_four_real_migrations_match_and_ordinary_buy_does_not(self):
        observed = {}
        for name, row in self.rows.items():
            fixture = self.fixtures[name]
            _validate_fixture(row, fixture)
            pool = PoolAccountEvidence(**fixture["pool_account"])
            states = [LpAccountState(**state) for state in fixture["lp_account_states"]]
            verdict = screen_pool(
                fixture["transaction"],
                row["expected_pool"],
                row["base_mint"],
                states,
                pool,
            )
            observed[name] = verdict.verdict
            with self.subTest(specimen=name, failed_check=verdict.failed_check):
                self.assertEqual(verdict.verdict, _VERDICT[row["expected_verdict"]])
                if row["expected_verdict"] == "GENUINE_PUMP_FUN_GRADUATION":
                    operations = verdict.evidence["migration_operations"]
                    self.assertEqual(
                        round(operations["bound_curve_debit_sol"], 6),
                        row["recorded_evidence"]["sol_migration_debit_sol"],
                    )
                    self.assertEqual(
                        operations["matching_lp_mint_to_burn"],
                        [
                            {
                                "mint": row["recorded_evidence"]["lp_mint"],
                                "account": row["recorded_evidence"]["lp_account"],
                                "amount": row["recorded_evidence"]["lp_mint_burn_amount"],
                                "outer_index": operations["matching_lp_mint_to_burn"][0]["outer_index"],
                            }
                        ],
                    )
                else:
                    self.assertEqual(verdict.failed_check, "derive:migration_frame_not_found")
                    programs = _transaction_programs(fixture["transaction"])
                    self.assertTrue(programs & PUMP_FUN_PROGRAMS)
                    self.assertIn(PUMPSWAP_AMM_PROGRAM, programs)
        self.assertEqual(sum(value == EVIDENCE_MATCHED for value in observed.values()), 4)
        self.assertEqual(sum(value == EVIDENCE_NOT_ESTABLISHED for value in observed.values()), 1)

    def test_real_positive_contexts_bind_the_hand_checked_account_indices(self):
        expected_indices = {
            "canonical_positive_1": (14, 17, 13, 5, 15, 2),
            "canonical_positive_2": (5, 12, 4, 13, 10, 11),
            "canonical_positive_3": (2, 10, 1, 11, 8, 9),
            "canonical_positive_4": (14, 10, 15, 9, 7, 8),
        }
        for name, indexes in expected_indices.items():
            fixture = self.fixtures[name]
            row = self.rows[name]
            pool = PoolAccountEvidence(**fixture["pool_account"])
            states = [LpAccountState(**state) for state in fixture["lp_account_states"]]
            context, reason = propose_migration_context(
                fixture["transaction"], row["expected_pool"], row["base_mint"], pool
            )
            self.assertIsNone(reason)
            self.assertIsNotNone(context)
            keys = _resolved_keys(fixture["transaction"])
            expected = tuple(keys[index] for index in indexes)
            actual = (
                context.base_source,
                context.base_destination,
                context.sol_source,
                context.sol_destination,
                context.lp_mint,
                context.lp_account,
            )
            with self.subTest(specimen=name):
                self.assertEqual(actual, expected)
                self.assertTrue(
                    verify_migration_evidence(
                        fixture["transaction"],
                        row["base_mint"],
                        context,
                        states,
                        pool,
                    ).is_match
                )

    def test_standard_migrate_coin_creator_role_is_bound(self):
        name = "canonical_positive_2"
        fixture = copy.deepcopy(self.fixtures[name])
        row = self.rows[name]
        migration = fixture["transaction"]["meta"]["innerInstructions"][0][
            "instructions"
        ][0]
        self.assertEqual(len(migration["accounts"]), 25)
        migration["accounts"][5] = row["base_mint"]
        pool = PoolAccountEvidence(**fixture["pool_account"])
        states = [LpAccountState(**state) for state in fixture["lp_account_states"]]
        verdict = screen_pool(
            fixture["transaction"],
            row["expected_pool"],
            row["base_mint"],
            states,
            pool,
        )
        self.assertEqual(verdict.failed_check, "derive:migration_frame_not_found")

    def test_fixture_controlled_oracle_tampering_fails_before_verification(self):
        positive_name = "canonical_positive_1"
        row = self.rows[positive_name]
        original = self.fixtures[positive_name]
        mutations = []

        changed = copy.deepcopy(original)
        changed["expected_verdict"] = "NOT_GENUINE_PUMP_FUN_GRADUATION"
        mutations.append(changed)
        changed = copy.deepcopy(original)
        changed["recorded_evidence"]["lp_mint_burn_amount"] = "1"
        mutations.append(changed)
        changed = copy.deepcopy(original)
        changed["transaction"] = {}
        mutations.append(changed)
        changed = copy.deepcopy(original)
        changed["transaction"]["meta"] = None
        mutations.append(changed)
        changed = copy.deepcopy(original)
        changed["transaction"]["transaction"]["signatures"].insert(0, row["signature"])
        mutations.append(changed)
        changed = copy.deepcopy(original)
        changed["transaction"]["transaction"]["message"]["recentBlockhash"] = row["base_mint"]
        mutations.append(changed)
        changed = copy.deepcopy(original)
        changed["pool_account"] = None
        mutations.append(changed)
        changed = copy.deepcopy(original)
        changed["pool_account"]["owner"] = row["base_mint"]
        mutations.append(changed)
        changed = copy.deepcopy(original)
        changed["pool_account"]["data_base64"] = "AAAA"
        mutations.append(changed)
        changed = copy.deepcopy(original)
        changed["lp_account_states"] = []
        mutations.append(changed)

        for fixture in mutations:
            with self.subTest(fields=sorted(fixture)):
                with self.assertRaises((ValueError, TypeError)):
                    _validate_fixture(row, fixture)

    def test_negative_cannot_pass_vacuously_with_an_empty_transaction(self):
        name = "negative_pump_and_pumpswap_no_lp_burn"
        fixture = copy.deepcopy(self.fixtures[name])
        fixture["transaction"] = {}
        with self.assertRaises(ValueError):
            _validate_fixture(self.rows[name], fixture)

    def test_missing_or_extra_manifest_fixture_is_a_hard_failure(self):
        missing = dict(self.fixtures)
        missing.pop(next(iter(missing)))
        with self.assertRaises(ValueError):
            _assert_exact_fixture_set(self.rows, missing)
        extra = dict(self.fixtures)
        extra["unlisted"] = {}
        with self.assertRaises(ValueError):
            _assert_exact_fixture_set(self.rows, extra)


if __name__ == "__main__":
    unittest.main()
