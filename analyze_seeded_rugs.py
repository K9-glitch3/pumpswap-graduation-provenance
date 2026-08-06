"""Validate and summarize the checked-in seeded-pool datasets.

The summaries are descriptive. Missing measurements are reported separately and
are never included silently in a denominator.

Run directly to print the summaries:

    python analyze_seeded_rugs.py
"""

from __future__ import annotations

import json
import math
import os
from statistics import median
from typing import Any

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

_RUG_FIELDS = frozenset(
    {"mint", "pool_creator", "seed_funder", "seed_sol", "funding_gap_slots"}
)
_MATCHED_FIELDS = _RUG_FIELDS | {"outcome"}
_OUTCOMES = frozenset({"rug", "surv"})


def _object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _non_empty_string(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
    )


def _validate_records(
    records: Any, *, matched: bool, source: str
) -> list[dict[str, Any]]:
    """Return *records* after enforcing the public dataset schema.

    The three funding measurements are either all present or all ``null`` in
    the published extraction. Numeric booleans are rejected explicitly because
    ``bool`` is a subclass of ``int`` in Python.
    """
    if not isinstance(records, list):
        raise ValueError(f"{source}: top-level value must be a JSON array")

    expected_fields = _MATCHED_FIELDS if matched else _RUG_FIELDS
    seen_mints: set[str] = set()

    for index, row in enumerate(records):
        where = f"{source}: record {index}"
        if not isinstance(row, dict):
            raise ValueError(f"{where} must be an object")

        actual_fields = frozenset(row)
        if actual_fields != expected_fields:
            missing = sorted(expected_fields - actual_fields)
            extra = sorted(actual_fields - expected_fields)
            raise ValueError(
                f"{where} has invalid fields; missing={missing}, extra={extra}"
            )

        mint = row["mint"]
        if not _non_empty_string(mint):
            raise ValueError(f"{where}.mint must be a non-empty string")
        if mint in seen_mints:
            raise ValueError(f"{where}.mint duplicates {mint!r}")
        seen_mints.add(mint)

        if not _non_empty_string(row["pool_creator"]):
            raise ValueError(f"{where}.pool_creator must be a non-empty string")

        seed_funder = row["seed_funder"]
        if seed_funder is not None and not _non_empty_string(seed_funder):
            raise ValueError(
                f"{where}.seed_funder must be a non-empty string or null"
            )

        seed_sol = row["seed_sol"]
        if seed_sol is not None:
            if isinstance(seed_sol, bool) or not isinstance(seed_sol, (int, float)):
                raise ValueError(f"{where}.seed_sol must be a number or null")
            if (
                isinstance(seed_sol, float) and not math.isfinite(seed_sol)
            ) or seed_sol <= 0:
                raise ValueError(f"{where}.seed_sol must be finite and positive")
            if seed_sol != round(seed_sol, 6):
                raise ValueError(
                    f"{where}.seed_sol must be rounded to at most six decimals"
                )

        funding_gap_slots = row["funding_gap_slots"]
        if funding_gap_slots is not None and (
            isinstance(funding_gap_slots, bool)
            or not isinstance(funding_gap_slots, int)
        ):
            raise ValueError(
                f"{where}.funding_gap_slots must be an integer or null"
            )

        missing_funding = (
            seed_funder is None,
            seed_sol is None,
            funding_gap_slots is None,
        )
        if any(missing_funding) and not all(missing_funding):
            raise ValueError(
                f"{where} must set seed_funder, seed_sol, and "
                "funding_gap_slots together or make all three null"
            )

        if matched:
            outcome = row["outcome"]
            if not isinstance(outcome, str) or outcome not in _OUTCOMES:
                raise ValueError(
                    f"{where}.outcome must be one of {sorted(_OUTCOMES)}"
                )

    return records


def _load(path: str, *, matched: bool) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        records = json.load(
            handle,
            object_pairs_hook=_object_without_duplicate_keys,
        )
    return _validate_records(records, matched=matched, source=path)


def load_rugs(path: str | None = None) -> list[dict[str, Any]]:
    path = path or os.path.join(_DATA_DIR, "seeded_pool_rugs.json")
    return _load(path, matched=False)


def load_matched(path: str | None = None) -> list[dict[str, Any]]:
    path = path or os.path.join(_DATA_DIR, "seed_timing_matched.json")
    return _load(path, matched=True)


def _measurement_summary(values: list[int | float], total: int) -> dict[str, Any]:
    known = len(values)
    return {
        "known": known,
        "missing": total - known,
        "median": median(values) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def rug_population_stats(rugs: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a descriptive summary of the rug-labelled records."""
    rugs = _validate_records(rugs, matched=False, source="rugs")
    total = len(rugs)
    seeds = [row["seed_sol"] for row in rugs if row["seed_sol"] is not None]
    gaps = [
        row["funding_gap_slots"]
        for row in rugs
        if row["funding_gap_slots"] is not None
    ]
    funders = [
        row["seed_funder"] for row in rugs if row["seed_funder"] is not None
    ]

    return {
        "total": total,
        "seed_sol": _measurement_summary(seeds, total),
        "funding_gap_slots": _measurement_summary(gaps, total),
        "distinct_pool_creators": len({row["pool_creator"] for row in rugs}),
        "seed_funder_known": len(funders),
        "seed_funder_missing": total - len(funders),
        "distinct_seed_funders": len(set(funders)),
    }


def matched_outcome_stats(matched: list[dict[str, Any]]) -> dict[str, Any]:
    """Return descriptive summaries for each outcome in the matched dataset."""
    matched = _validate_records(matched, matched=True, source="matched")

    def group(outcome: str) -> dict[str, Any]:
        rows = [row for row in matched if row["outcome"] == outcome]
        seeds = [row["seed_sol"] for row in rows if row["seed_sol"] is not None]
        gaps = [
            row["funding_gap_slots"]
            for row in rows
            if row["funding_gap_slots"] is not None
        ]
        return {
            "count": len(rows),
            "seed_sol": _measurement_summary(seeds, len(rows)),
            "funding_gap_slots": _measurement_summary(gaps, len(rows)),
        }

    return {outcome: group(outcome) for outcome in sorted(_OUTCOMES)}


def render_report_summary(
    rugs: list[dict[str, Any]] | None = None,
    matched: list[dict[str, Any]] | None = None,
) -> str:
    """Render the generated Markdown section embedded in ``REPORT.md``."""
    rugs = load_rugs() if rugs is None else rugs
    matched = load_matched() if matched is None else matched
    population = rug_population_stats(rugs)
    outcomes = matched_outcome_stats(matched)
    seeds = population["seed_sol"]
    gaps = population["funding_gap_slots"]
    rug = outcomes["rug"]
    surv = outcomes["surv"]
    matched_total = rug["count"] + surv["count"]

    return "\n".join(
        [
            "## File contents",
            "",
            "| File | Rows | Additional label |",
            "| --- | ---: | --- |",
            f"| `data/seeded_pool_rugs.json` | {population['total']} | none |",
            f"| `data/seed_timing_matched.json` | {matched_total} | `outcome` |",
            "",
            "## `seeded_pool_rugs.json`",
            "",
            "| Measure | Value | Denominator |",
            "| --- | ---: | --- |",
            f"| Rows | {population['total']} | {population['total']} rows |",
            f"| Populated `pool_creator` values | {population['total']} | {population['total']} rows |",
            f"| Distinct `pool_creator` values | {population['distinct_pool_creators']} | {population['total']} populated values |",
            f"| Populated `seed_funder` values | {population['seed_funder_known']} | {population['total']} rows |",
            f"| Missing `seed_funder` values | {population['seed_funder_missing']} | {population['total']} rows |",
            f"| Distinct `seed_funder` values | {population['distinct_seed_funders']} | {population['seed_funder_known']} populated values |",
            f"| Numeric `seed_sol` values | {seeds['known']} | {population['total']} rows |",
            f"| Missing `seed_sol` values | {seeds['missing']} | {population['total']} rows |",
            f"| Median `seed_sol` | {seeds['median']} SOL | {seeds['known']} numeric values |",
            f"| Minimum `seed_sol` | {seeds['min']} SOL | {seeds['known']} numeric values |",
            f"| Maximum `seed_sol` | {seeds['max']} SOL | {seeds['known']} numeric values |",
            f"| Numeric `funding_gap_slots` values | {gaps['known']} | {population['total']} rows |",
            f"| Missing `funding_gap_slots` values | {gaps['missing']} | {population['total']} rows |",
            f"| Median `funding_gap_slots` | {gaps['median']} slots | {gaps['known']} numeric values |",
            f"| Minimum `funding_gap_slots` | {gaps['min']} slots | {gaps['known']} numeric values |",
            f"| Maximum `funding_gap_slots` | {gaps['max']} slots | {gaps['known']} numeric values |",
            "",
            "## `seed_timing_matched.json`",
            "",
            "| `outcome` label | Rows | Numeric seed n | Median `seed_sol` | Numeric gap n | Median `funding_gap_slots` |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
            f"| `rug` | {rug['count']} | {rug['seed_sol']['known']} | {rug['seed_sol']['median']} SOL | {rug['funding_gap_slots']['known']} | {rug['funding_gap_slots']['median']} slots |",
            f"| `surv` | {surv['count']} | {surv['seed_sol']['known']} | {surv['seed_sol']['median']} SOL | {surv['funding_gap_slots']['known']} | {surv['funding_gap_slots']['median']} slots |",
        ]
    )


def _format_measurement(name: str, summary: dict[str, Any]) -> str:
    return (
        f"  {name}: known={summary['known']}, missing={summary['missing']}, "
        f"median={summary['median']}, min={summary['min']}, max={summary['max']}"
    )


def main() -> None:
    rugs = load_rugs()
    matched = load_matched()
    population = rug_population_stats(rugs)
    outcomes = matched_outcome_stats(matched)

    print(f"Rug-labelled records: {population['total']}")
    print(_format_measurement("seed_sol", population["seed_sol"]))
    print(
        _format_measurement(
            "funding_gap_slots", population["funding_gap_slots"]
        )
    )
    print(
        "  pool_creator: "
        f"distinct={population['distinct_pool_creators']}"
    )
    print(
        "  seed_funder: "
        f"known={population['seed_funder_known']}, "
        f"missing={population['seed_funder_missing']}, "
        f"distinct={population['distinct_seed_funders']}"
    )
    print()
    print("Matched records by outcome:")
    for outcome in ("rug", "surv"):
        summary = outcomes[outcome]
        print(f"  {outcome}: total={summary['count']}")
        print(_format_measurement("    seed_sol", summary["seed_sol"]))
        print(
            _format_measurement(
                "    funding_gap_slots", summary["funding_gap_slots"]
            )
        )


if __name__ == "__main__":
    main()
