#!/usr/bin/env python3
"""
eval/run_eval.py
----------------
Runs all test cases against the live /plan endpoint and scores each one
against the chosen metric: ingredient_utilization_rate.

Primary metric:
  ingredient_utilization_rate = (# pantry ingredients appearing in at least
  one ingredients_used list across the 7 days) / (# pantry ingredients provided)

Usage:
  # Start the Flask app first: python app.py
  python eval/run_eval.py [--url http://localhost:5000]
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

# ── Constants ────────────────────────────────────────────────────────────────
TESTS_FILE = Path(__file__).parent / "test_cases.json"
REQUIRED_DAY_FIELDS = {
    "day", "meal", "description",
    "ingredients_used", "missing_ingredients", "prep_time", "difficulty"
}
VALID_DIFFICULTIES = {"Easy", "Medium", "Advanced"}
VEGAN_BANNED = {"eggs", "egg", "butter", "milk", "cream", "cheese",
                "chicken", "beef", "pork", "fish", "salmon", "tuna",
                "shrimp", "bacon", "ham", "honey", "gelatin"}
NUT_BANNED = {"peanut butter", "peanuts", "peanut", "almonds", "almond",
              "cashews", "cashew", "walnuts", "walnut", "pecans", "pecan",
              "pistachios", "pistachio", "hazelnuts", "hazelnut", "nuts", "nut"}
GLUTEN_BANNED = {"flour", "pasta", "bread", "wheat", "soy sauce",
                 "noodles", "tortilla", "tortillas", "barley", "rye"}


# ── Helpers ───────────────────────────────────────────────────────────────────
def call_plan(base_url: str, payload: dict) -> tuple[int, dict]:
    try:
        r = requests.post(f"{base_url}/plan", json=payload, timeout=60)
        return r.status_code, r.json()
    except requests.exceptions.ConnectionError:
        print(f"\n❌  Cannot connect to {base_url}. Is `python app.py` running?\n")
        sys.exit(1)
    except Exception as e:
        return 500, {"error": str(e)}


def all_used_ingredients(plan: dict) -> set[str]:
    """Flat set of every ingredient mentioned in any day's ingredients_used."""
    used = set()
    for day in plan.get("week", []):
        for item in day.get("ingredients_used", []):
            used.add(item.lower())
    return used


def score_tc(tc: dict, status: int, plan: dict) -> tuple[bool, str]:
    metric = tc["pass_criteria"]["metric"]
    threshold = tc["pass_criteria"]["threshold"]
    pantry_raw = tc["input"]["ingredients"]
    pantry = [i.strip().lower() for i in pantry_raw.split(",") if i.strip()]

    # ── TC09: empty input → expect 400 ──────────────────────────────────────
    if metric == "error_on_empty_input":
        passed = status == 400 and "error" in plan
        return passed, f"HTTP {status}, error key present: {'error' in plan}"

    # All other tests expect HTTP 200
    if status != 200 or "error" in plan:
        return False, f"HTTP {status} — {plan.get('error', 'unknown error')}"

    # ── ingredient_utilization_rate ─────────────────────────────────────────
    if metric == "ingredient_utilization_rate":
        used = all_used_ingredients(plan)
        covered = sum(1 for ing in pantry if any(ing in u or u in ing for u in used))
        rate = covered / len(pantry) if pantry else 0
        passed = rate >= threshold
        return passed, f"utilization = {covered}/{len(pantry)} = {rate:.2f} (threshold {threshold})"

    # ── dietary_compliance ──────────────────────────────────────────────────
    if metric == "dietary_compliance":
        dietary = tc["input"]["dietary"].lower()
        banned: set[str] = set()
        if "vegan" in dietary:
            banned = VEGAN_BANNED
        elif "gluten" in dietary:
            banned = GLUTEN_BANNED
        elif "nut" in dietary:
            banned = NUT_BANNED

        violations = []
        for day in plan.get("week", []):
            for item in day.get("ingredients_used", []):
                item_l = item.lower()
                for b in banned:
                    if b in item_l:
                        violations.append(f"{day['day']}: '{item}'")
        passed = len(violations) == 0
        detail = "no violations" if passed else f"violations: {violations[:3]}"
        return passed, detail

    # ── grocery_gaps_nonempty ───────────────────────────────────────────────
    if metric == "grocery_gaps_nonempty":
        gaps = plan.get("grocery_gaps", [])
        passed = len(gaps) >= threshold
        return passed, f"grocery_gaps has {len(gaps)} items (need ≥{threshold})"

    # ── schema_completeness ─────────────────────────────────────────────────
    if metric == "schema_completeness":
        missing_fields = []
        for day in plan.get("week", []):
            for field in REQUIRED_DAY_FIELDS:
                if field not in day:
                    missing_fields.append(f"{day.get('day','?')}.{field}")
        passed = len(missing_fields) == 0
        detail = "all fields present" if passed else f"missing: {missing_fields[:5]}"
        return passed, detail

    # ── valid_difficulty_values ─────────────────────────────────────────────
    if metric == "valid_difficulty_values":
        bad = [f"{d.get('day')}: '{d.get('difficulty')}'"
               for d in plan.get("week", [])
               if d.get("difficulty") not in VALID_DIFFICULTIES]
        passed = len(bad) == 0
        return passed, "all valid" if passed else f"invalid: {bad}"

    # ── day_count ───────────────────────────────────────────────────────────
    if metric == "day_count":
        count = len(plan.get("week", []))
        passed = count == threshold
        return passed, f"{count} days returned (need {threshold})"

    # ── grocery_gaps_is_union ───────────────────────────────────────────────
    if metric == "grocery_gaps_is_union":
        all_missing = set()
        for day in plan.get("week", []):
            for item in day.get("missing_ingredients", []):
                all_missing.add(item.lower())
        gaps_set = {g.lower() for g in plan.get("grocery_gaps", [])}
        not_in_gaps = all_missing - gaps_set
        extra_in_gaps = gaps_set - all_missing
        passed = len(not_in_gaps) == 0
        detail = "union correct" if passed else f"missing from gaps: {list(not_in_gaps)[:3]}"
        return passed, detail

    return False, f"Unknown metric: {metric}"


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:5000",
                        help="Base URL of the running Flask app")
    args = parser.parse_args()

    tests = json.loads(TESTS_FILE.read_text())
    results = []

    print(f"\n{'─'*60}")
    print(f"  Pantry Meal Planner — Eval Suite ({len(tests)} test cases)")
    print(f"  Target: {args.url}")
    print(f"{'─'*60}\n")

    for tc in tests:
        print(f"  [{tc['id']}] {tc['description'][:55]:<55}", end=" ", flush=True)
        status, plan = call_plan(args.url, tc["input"])
        passed, detail = score_tc(tc, status, plan)
        symbol = "✅ PASS" if passed else "❌ FAIL"
        print(f"{symbol}  |  {detail}")
        results.append({"id": tc["id"], "passed": passed})
        time.sleep(0.5)   # be kind to the API

    total = len(results)
    passing = sum(1 for r in results if r["passed"])
    rate = passing / total

    print(f"\n{'─'*60}")
    print(f"  Result: {passing}/{total} passed  ({rate*100:.0f}%)")
    print(f"  Metric: ingredient_utilization_rate (primary, TC01)")

    # Write a simple results file
    out = Path(__file__).parent / "results.json"
    out.write_text(json.dumps({
        "passed": passing, "total": total, "rate": rate,
        "cases": results
    }, indent=2))
    print(f"  Full results saved to eval/results.json")
    print(f"{'─'*60}\n")

    sys.exit(0 if rate >= 0.8 else 1)


if __name__ == "__main__":
    main()
