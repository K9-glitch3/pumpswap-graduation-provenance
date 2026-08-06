"""Pin the public datasets, their validation, and their descriptive summaries."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO

from analyze_seeded_rugs import (
    load_matched,
    load_rugs,
    main,
    matched_outcome_stats,
    render_report_summary,
    rug_population_stats,
)

RUG_FIELDS = {
    "mint",
    "pool_creator",
    "seed_funder",
    "seed_sol",
    "funding_gap_slots",
}
MATCHED_FIELDS = RUG_FIELDS | {"outcome"}


def _canonical_digest(records):
    payload = json.dumps(records, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rug_row(**overrides):
    row = {
        "mint": "mint-a",
        "pool_creator": "creator-a",
        "seed_funder": "funder-a",
        "seed_sol": 1.0,
        "funding_gap_slots": 1,
    }
    row.update(overrides)
    return row


def _matched_row(**overrides):
    row = {"outcome": "rug", **_rug_row()}
    row.update(overrides)
    return row


class DataShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rugs = load_rugs()
        cls.matched = load_matched()

    def test_record_counts_and_exact_public_fields(self):
        self.assertEqual(len(self.rugs), 189)
        self.assertEqual(len(self.matched), 60)
        self.assertTrue(all(set(row) == RUG_FIELDS for row in self.rugs))
        self.assertTrue(all(set(row) == MATCHED_FIELDS for row in self.matched))

    def test_dataset_content_and_order_are_pinned(self):
        self.assertEqual(
            _canonical_digest(self.rugs),
            "db3cac0e22c105063cc4fe72681a6126f223268806262c9ed9f610bc5dc02dde",
        )
        self.assertEqual(
            _canonical_digest(self.matched),
            "89df64577e9323200021889f5e9273c559729e720b53b7be611ad9b2f9a5a951",
        )

    def test_mints_are_unique(self):
        for records in (self.rugs, self.matched):
            mints = [row["mint"] for row in records]
            self.assertEqual(len(mints), len(set(mints)))

    def test_funding_fields_are_present_or_null_together(self):
        for records in (self.rugs, self.matched):
            for row in records:
                nulls = [
                    row["seed_funder"] is None,
                    row["seed_sol"] is None,
                    row["funding_gap_slots"] is None,
                ]
                self.assertIn(sum(nulls), (0, 3))

    def test_matched_outcomes_are_exact(self):
        counts = {
            outcome: sum(row["outcome"] == outcome for row in self.matched)
            for outcome in ("rug", "surv")
        }
        self.assertEqual(counts, {"rug": 30, "surv": 30})


class RugPopulationTests(unittest.TestCase):
    def test_exact_population_summary(self):
        self.assertEqual(
            rug_population_stats(load_rugs()),
            {
                "total": 189,
                "seed_sol": {
                    "known": 169,
                    "missing": 20,
                    "median": 189.980031,
                    "min": 16.141337,
                    "max": 2877.912488,
                },
                "funding_gap_slots": {
                    "known": 169,
                    "missing": 20,
                    "median": 51,
                    "min": -108111,
                    "max": 416098,
                },
                "distinct_pool_creators": 178,
                "seed_funder_known": 169,
                "seed_funder_missing": 20,
                "distinct_seed_funders": 114,
            },
        )


class MatchedOutcomeTests(unittest.TestCase):
    def test_exact_outcome_summaries(self):
        self.assertEqual(
            matched_outcome_stats(load_matched()),
            {
                "rug": {
                    "count": 30,
                    "seed_sol": {
                        "known": 27,
                        "missing": 3,
                        "median": 147.635449,
                        "min": 71.792005,
                        "max": 809.231414,
                    },
                    "funding_gap_slots": {
                        "known": 27,
                        "missing": 3,
                        "median": 45,
                        "min": 26,
                        "max": 363,
                    },
                },
                "surv": {
                    "count": 30,
                    "seed_sol": {
                        "known": 24,
                        "missing": 6,
                        "median": 158.2541785,
                        "min": 83.79441,
                        "max": 863.330889,
                    },
                    "funding_gap_slots": {
                        "known": 24,
                        "missing": 6,
                        "median": 61.5,
                        "min": 27,
                        "max": 14388,
                    },
                },
            },
        )


class ValidationTests(unittest.TestCase):
    def _load_payload(self, loader, payload):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "data.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            return loader(path)

    def test_valid_known_and_null_rows_are_accepted(self):
        rows = [
            _rug_row(),
            _rug_row(
                mint="mint-b",
                seed_funder=None,
                seed_sol=None,
                funding_gap_slots=None,
            ),
        ]
        self.assertEqual(rug_population_stats(rows)["total"], 2)

    def test_top_level_and_record_types_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "JSON array"):
            self._load_payload(load_rugs, {"not": "an array"})
        with self.assertRaisesRegex(ValueError, "record 0 must be an object"):
            self._load_payload(load_rugs, ["not an object"])

    def test_missing_and_extra_fields_are_rejected(self):
        missing = _rug_row()
        del missing["mint"]
        extra = _rug_row(private_field="not public")
        for row in (missing, extra):
            with self.subTest(row=row), self.assertRaisesRegex(
                ValueError, "invalid fields"
            ):
                rug_population_stats([row])

    def test_required_strings_must_be_non_empty(self):
        for field in ("mint", "pool_creator"):
            for value in (None, "", "   ", " padded ", 1, True):
                with self.subTest(field=field, value=value), self.assertRaises(
                    ValueError
                ):
                    rug_population_stats([_rug_row(**{field: value})])

    def test_seed_funder_must_be_non_empty_string_or_null(self):
        for value in ("", "   ", " padded ", 1, True):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "seed_funder"
            ):
                rug_population_stats([_rug_row(seed_funder=value)])

    def test_numeric_booleans_are_rejected(self):
        for field in ("seed_sol", "funding_gap_slots"):
            for value in (True, False):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(
                    ValueError, field
                ):
                    rug_population_stats([_rug_row(**{field: value})])

    def test_invalid_seed_values_are_rejected(self):
        for value in ("1", float("nan"), float("inf"), 0, -1, 1.1234567):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "seed_sol"
            ):
                rug_population_stats([_rug_row(seed_sol=value)])

    def test_arbitrarily_large_integer_seed_does_not_raise_overflow(self):
        value = 10**400
        summary = rug_population_stats([_rug_row(seed_sol=value)])
        self.assertEqual(summary["seed_sol"]["median"], value)

    def test_funding_gap_must_be_an_integer(self):
        for value in ("1", 1.0):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "funding_gap_slots"
            ):
                rug_population_stats([_rug_row(funding_gap_slots=value)])

    def test_partial_funding_missingness_is_rejected(self):
        for field in ("seed_funder", "seed_sol", "funding_gap_slots"):
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "all three null"
            ):
                rug_population_stats([_rug_row(**{field: None})])

    def test_duplicate_mints_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicates"):
            rug_population_stats([_rug_row(), deepcopy(_rug_row())])

    def test_duplicate_json_object_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "data.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    '[{"mint":"first","mint":"second",'
                    '"pool_creator":"creator","seed_funder":null,'
                    '"seed_sol":null,"funding_gap_slots":null}]'
                )
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                load_rugs(path)

    def test_unknown_outcomes_fail_in_loader_and_summary(self):
        for outcome in ("unknown", "", None, True, []):
            row = _matched_row(outcome=outcome)
            with self.subTest(outcome=outcome), self.assertRaisesRegex(
                ValueError, "outcome"
            ):
                self._load_payload(load_matched, [row])
            with self.subTest(outcome=outcome), self.assertRaisesRegex(
                ValueError, "outcome"
            ):
                matched_outcome_stats([row])

    def test_matched_schema_requires_outcome(self):
        with self.assertRaisesRegex(ValueError, "invalid fields"):
            matched_outcome_stats([_rug_row()])


class CommandOutputTests(unittest.TestCase):
    def test_report_generated_section_matches_analyzer_exactly(self):
        report_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "REPORT.md",
        )
        with open(report_path, encoding="utf-8") as handle:
            report = handle.read()
        begin = "<!-- BEGIN GENERATED SUMMARY -->"
        end = "<!-- END GENERATED SUMMARY -->"
        self.assertEqual(report.count(begin), 1)
        self.assertEqual(report.count(end), 1)
        embedded = report.split(begin, 1)[1].split(end, 1)[0].strip()
        self.assertEqual(embedded, render_report_summary())

    def test_output_reports_known_and_missing_counts_without_filter_language(self):
        output = StringIO()
        with redirect_stdout(output):
            main()
        rendered = output.getvalue()
        self.assertIn("known=169, missing=20", rendered)
        self.assertIn("rug: total=30", rendered)
        self.assertIn("known=27, missing=3", rendered)
        self.assertIn("surv: total=30", rendered)
        self.assertIn("known=24, missing=6", rendered)
        for term in ("filter", "edge", "signal", "separate", "position"):
            self.assertNotIn(term, rendered.lower())


if __name__ == "__main__":
    unittest.main()
