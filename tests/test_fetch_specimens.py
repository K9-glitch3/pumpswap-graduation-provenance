"""Offline tests for the specimen materializer's fail-closed helpers."""

from __future__ import annotations

import base64
import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from pumpswap_decoder import PUMP_AMM_PROGRAM
from tools import fetch_specimens as fetch

_ROOT = Path(__file__).resolve().parent.parent


def _fixture(name="canonical_positive_1"):
    return json.loads(
        (_ROOT / "specimens" / "raw" / f"{name}.json").read_text(
            encoding="utf-8"
        )
    )


def _manifest():
    return json.loads(
        (_ROOT / "specimens" / "specimen_manifest.json").read_text(
            encoding="utf-8"
        )
    )


def _pool_rpc_value(fixture):
    pool = fixture["pool_account"]
    return {
        "data": [pool["data_base64"], "base64"],
        "executable": False,
        "lamports": 1,
        "owner": pool["owner"],
        "rentEpoch": 0,
        "space": len(base64.b64decode(pool["data_base64"])),
    }


def _multiple_accounts_result(tx, fixture, *, extra=None):
    writable = fetch._writable_keys(tx)
    values = [None] * len(writable)
    values[writable.index(fixture["expected_pool"])] = _pool_rpc_value(fixture)
    if extra is not None:
        values[writable.index(extra)] = _pool_rpc_value(fixture)
    return writable, {
        "context": {"apiVersion": "test", "slot": fixture["pool_account"]["context_slot"]},
        "value": values,
    }


class ManifestAndTransactionTests(unittest.TestCase):
    def test_committed_manifest_is_strictly_valid(self):
        rows = fetch._validate_manifest(_manifest())
        self.assertEqual(len(rows), 5)

    def test_manifest_schema_amounts_and_pool_are_fail_closed(self):
        mutations = []
        changed = _manifest()
        changed["extra"] = True
        mutations.append(changed)
        changed = _manifest()
        changed["specimens"][0]["expected_pool"] = None
        mutations.append(changed)
        changed = _manifest()
        changed["specimens"][0]["recorded_evidence"]["lp_mint_burn_amount"] = "01"
        mutations.append(changed)
        changed = _manifest()
        changed["specimens"][0]["recorded_evidence"]["sol_migration_debit_sol"] = float("nan")
        mutations.append(changed)
        changed = _manifest()
        changed["specimens"].pop()
        mutations.append(changed)
        for manifest in mutations:
            with self.subTest(keys=sorted(manifest)):
                with self.assertRaises(fetch.SpecimenFetchError):
                    fetch._validate_manifest(manifest)

    def test_transaction_digest_detects_semantic_fixture_tampering(self):
        manifest_row = fetch._validate_manifest(_manifest())[0]
        tx = _fixture()["transaction"]
        self.assertIs(fetch._validate_transaction(tx, manifest_row), tx)
        changed = copy.deepcopy(tx)
        changed["transaction"]["message"]["recentBlockhash"] = manifest_row["base_mint"]
        with self.assertRaisesRegex(fetch.SpecimenFetchError, "digest"):
            fetch._validate_transaction(changed, manifest_row)


class PoolResolutionTests(unittest.TestCase):
    def test_resolver_uses_exact_writable_keys_and_decoder(self):
        fixture = _fixture()
        tx = fixture["transaction"]
        writable, result = _multiple_accounts_result(tx, fixture)
        resolved = fetch._resolve_pool_from_result(
            tx, fixture["base_mint"], writable, result
        )
        self.assertEqual(resolved, fixture["pool_account"])
        readonly = {
            entry["pubkey"]
            for entry in tx["transaction"]["message"]["accountKeys"]
            if entry["writable"] is False
        }
        self.assertFalse(readonly & set(writable))

    def test_invalid_discriminator_and_ambiguous_decoded_pools_are_rejected(self):
        fixture = _fixture()
        tx = copy.deepcopy(fixture["transaction"])
        writable, result = _multiple_accounts_result(tx, fixture)
        pool_index = writable.index(fixture["expected_pool"])
        raw = bytearray(base64.b64decode(result["value"][pool_index]["data"][0]))
        raw[0] ^= 1
        result["value"][pool_index]["data"][0] = base64.b64encode(raw).decode("ascii")
        with self.assertRaises(fetch.SpecimenFetchError):
            fetch._resolve_pool_from_result(tx, fixture["base_mint"], writable, result)

        tx = copy.deepcopy(fixture["transaction"])
        writable = fetch._writable_keys(tx)
        other = next(key for key in writable if key != fixture["expected_pool"])
        tx["transaction"]["message"]["instructions"].append(
            {"programId": PUMP_AMM_PROGRAM, "accounts": [other], "data": "1"}
        )
        writable, result = _multiple_accounts_result(tx, fixture, extra=other)
        with self.assertRaisesRegex(fetch.SpecimenFetchError, "exactly one"):
            fetch._resolve_pool_from_result(tx, fixture["base_mint"], writable, result)


class LpStateAndFailureTests(unittest.TestCase):
    def test_lp_state_results_require_valid_contexts_and_canonical_supply(self):
        fixture = _fixture()
        recorded = fixture["recorded_evidence"]
        info = {"context": {"slot": 101}, "value": None}
        supply = {"context": {"slot": 102}, "value": {"amount": "0"}}
        state = fetch._lp_account_state_from_results(
            recorded["lp_mint"],
            recorded["lp_account"],
            info,
            supply,
            min_context_slot=100,
        )
        self.assertTrue(state["destination_closed"])
        self.assertTrue(state["lp_supply_zero"])
        supply["value"]["amount"] = "00"
        with self.assertRaises(fetch.SpecimenFetchError):
            fetch._lp_account_state_from_results(
                recorded["lp_mint"],
                recorded["lp_account"],
                info,
                supply,
                min_context_slot=100,
            )

    def test_rpc_errors_never_render_the_endpoint(self):
        endpoint = "sensitive-endpoint-marker"
        with mock.patch.object(
            fetch.urllib.request,
            "urlopen",
            side_effect=RuntimeError(endpoint),
        ):
            with self.assertRaises(fetch.SpecimenFetchError) as caught:
                fetch._rpc(endpoint, "getTransaction", [])
        self.assertNotIn(endpoint, str(caught.exception))

    def test_main_returns_nonzero_and_writes_nothing_after_any_fetch_failure(self):
        with mock.patch.dict(os.environ, {"RPC_URL": "endpoint-marker"}), mock.patch.object(
            fetch, "_build_fixture", side_effect=fetch.SpecimenFetchError("unavailable")
        ), mock.patch.object(fetch, "_atomic_write_fixtures") as writer:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = fetch.main()
        self.assertEqual(result, 1)
        writer.assert_not_called()
        self.assertNotIn("endpoint-marker", stderr.getvalue())

    def test_multi_file_replace_rolls_back_an_earlier_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "a.json").write_text("old-a\n", encoding="utf-8")
            (directory / "b.json").write_text("old-b\n", encoding="utf-8")
            fixtures = [{"name": "a", "value": "new"}, {"name": "b", "value": "new"}]
            real_replace = os.replace
            replacement_calls = 0

            def flaky_replace(source, target):
                nonlocal replacement_calls
                if str(source).endswith(".tmp"):
                    replacement_calls += 1
                    if replacement_calls == 2:
                        raise OSError("injected replacement failure")
                return real_replace(source, target)

            with mock.patch.object(fetch, "_RAW_DIR", directory), mock.patch.object(
                fetch.os, "replace", side_effect=flaky_replace
            ):
                with self.assertRaises(OSError):
                    fetch._atomic_write_fixtures(fixtures)
            self.assertEqual((directory / "a.json").read_text(encoding="utf-8"), "old-a\n")
            self.assertEqual((directory / "b.json").read_text(encoding="utf-8"), "old-b\n")
            self.assertFalse(list(directory.glob(".*.tmp")))
            self.assertFalse(list(directory.glob(".*.bak")))

    def test_multi_file_replace_rolls_back_after_keyboard_interrupt(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "a.json").write_text("old-a\n", encoding="utf-8")
            (directory / "b.json").write_text("old-b\n", encoding="utf-8")
            fixtures = [{"name": "a", "value": "new"}, {"name": "b", "value": "new"}]
            real_replace = os.replace
            replacement_calls = 0

            def interrupted_replace(source, target):
                nonlocal replacement_calls
                if str(source).endswith(".tmp"):
                    replacement_calls += 1
                    if replacement_calls == 2:
                        raise KeyboardInterrupt()
                return real_replace(source, target)

            with mock.patch.object(fetch, "_RAW_DIR", directory), mock.patch.object(
                fetch.os, "replace", side_effect=interrupted_replace
            ):
                with self.assertRaises(KeyboardInterrupt):
                    fetch._atomic_write_fixtures(fixtures)
            self.assertEqual((directory / "a.json").read_text(encoding="utf-8"), "old-a\n")
            self.assertEqual((directory / "b.json").read_text(encoding="utf-8"), "old-b\n")
            self.assertFalse(list(directory.glob(".*.tmp")))
            self.assertFalse(list(directory.glob(".*.bak")))


if __name__ == "__main__":
    unittest.main()
