# REPORT.md — Pantry Meal Planner

---

## 1. What & Why (~220 words)

The Pantry Meal Planner is a Flask web app for busy parents and home cooks who want to reduce food waste and avoid the "what's for dinner?" decision loop. Users paste their pantry ingredients, specify dietary restrictions (vegan, gluten-free, nut-free, etc.), and choose how many servings they need. The app calls GPT-4o-mini and returns a structured 7-day dinner plan with prep times, difficulty ratings, and a grocery gap list showing only what they actually need to buy.

The core AI behavior challenge is **ingredient utilization fidelity**: the model must use what the user actually has, not hallucinate a plausible-sounding meal plan that ignores the pantry entirely. A secondary challenge is **dietary constraint compliance across all 7 days** — the model must not slip a banned ingredient into day 4 just because it fits the recipe well. Both failures are silent from the user's perspective: the UI renders either way, so the eval must catch them automatically.

The app also implements a multi-call feedback loop: after the initial plan is generated, users can click "Suggest a change" on any day card, describe what they dislike, and a second API call replaces only that day while keeping the rest of the week intact. This second call is context-dependent — it sends the full current plan so the model maintains ingredient coherence across the week.

---

## 2. Iterations

### V1 — Baseline: single prompt, no schema enforcement

**Change:** Initial system prompt asked the model to "create a 7-day meal plan" and return JSON, but did not specify required fields or provide a JSON schema template.

**Motivating example:** When tested with `"ingredients": "eggs, salt, olive oil"`, the model returned a plan where Monday was `"Pasta Carbonara"` with `ingredients_used: ["pasta", "eggs", "pancetta"]` — two of three items were not in the pantry. The grocery gap list was also missing entirely on two out of five runs.

**Delta:** ingredient_utilization_rate dropped to 0.31 on the sparse-pantry test case (TC04). Schema completeness failed on 3/10 test cases due to missing `missing_ingredients` or `grocery_gaps` keys.

**Conclusion:** The model needs an explicit JSON schema in the prompt with a filled-in example, and field-level rules. Vague output instructions produce inconsistent structure.

---

### V2 — Explicit JSON schema + field rules in system prompt

**Change:** Added a fully typed JSON template to the system prompt with all required fields populated (as shown in `app.py:14–40`). Added explicit rules: "difficulty is one of: Easy, Medium, or Advanced", "grocery_gaps is the combined unique list of all missing_ingredients", and "Do not include any text outside the JSON block."

**Motivating example:** TC06 (difficulty validation) was previously failing ~40% of runs with values like `"Beginner"`, `"Hard"`, or `"Moderate"`. After adding the rule, TC06 passed on 10/10 runs.

**Delta:** Schema completeness (TC05) rose from 70% to 100%. Valid difficulty values (TC06) rose from 60% to 100%. Overall suite pass rate rose from 5/10 to 8/10.

**Conclusion:** Explicit enumeration of allowed values in the system prompt is more reliable than relying on the model's prior knowledge of what "difficulty" means. Unresolved failures: TC02 (vegan compliance) still violated on ~20% of runs when the pantry contained eggs — the model used them anyway.

---

### V3 — Dietary restriction reinforcement + `strip_fences()` robustness

**Change:** Added a dedicated dietary compliance rule to the system prompt: "If a dietary restriction is provided, you must NEVER include banned ingredients in ingredients_used, even if they are present in the pantry." Also added `strip_fences()` in `app.py:72–80` to handle the model occasionally wrapping its JSON in ` ```json ``` ` fences, which caused silent `JSONDecodeError` failures.

**Motivating example:** TC10 (nut allergy, peanut butter in pantry) was failing because the model would include `"peanut butter"` in a stir-fry's `ingredients_used` since it was listed in the pantry. The model was optimizing for pantry utilization at the expense of the safety constraint. Adding the explicit "even if they are present in the pantry" clause in the rule fixed this.

**Delta:** TC02 (vegan) pass rate rose from 80% to 100% across 5 re-runs. TC10 (nut allergy) rose from 60% to 100%. The `strip_fences()` fix resolved 2 previously flaky runs where the model returned fenced JSON. Overall suite: 10/10 passing.

**Conclusion:** Dietary safety constraints require explicit negative framing ("never include X even if present") rather than just positive framing ("respect dietary restrictions"). The eval suite was essential for catching the vegan/nut failures that were invisible in manual UI testing.

---

## 3. Code Walkthrough (~250 words)

A user clicks "Generate My Week" in `templates/index.html:487`, which calls `generatePlan()`. That function reads the three form inputs and POSTs to `/plan` via `fetch()` using the `safeJson()` helper at `index.html:617`, which reads the response as text before parsing so an accidental HTML error page never crashes the stream.

On the backend, `app.py:94` defines the `/plan` route. The first notable design decision is `request.get_json(force=True, silent=True) or {}` at `app.py:97`. The `force=True` flag accepts any `Content-Type` header (not just `application/json`), and `silent=True` returns `None` instead of raising a `400` when the body is malformed — the `or {}` then prevents a `NoneType` `AttributeError` that would otherwise leak as an HTML 500 page. I considered using strict JSON parsing and rejecting malformed requests with a `415 Unsupported Media Type`, but since the frontend always sends the correct header, the permissive approach provides better resilience during development without any user-facing downside.

The response from OpenAI is cleaned by `strip_fences()` at `app.py:72` before `json.loads()`. An alternative I rejected was using the OpenAI `response_format={"type": "json_object"}` parameter, which forces JSON mode at the API level. I chose not to use it because JSON mode still allows the model to omit required fields — it only guarantees parseable JSON, not schema conformance. The explicit schema in `SYSTEM_PROMPT` does both.

The `/refine` route at `app.py:132` follows the same pattern but takes the entire current plan as input, serialized at `app.py:145` with `json.dumps(current_plan, indent=2)` so the model can read it clearly.

---

## 4. AI Disclosure & Safety (~175 words)

I used Claude (claude.ai) as my coding assistant throughout this project. Two specific moments where it failed and I had to recover:

**Failure 1 — Syntax error silenced the whole script block.** Claude generated an inline `onclick` handler string containing an unescaped apostrophe in `alert('Please describe what you'd like changed.')`, which broke the entire `<script>` block and caused `generatePlan is not defined`. I caught this via browser DevTools, identified the root cause (the JS string delimiter collision), and fixed it by switching to event delegation with `data-*` attributes and double-quoted strings throughout.

**Failure 2 — `request.get_json()` returning None.** Claude's initial backend code called `.get()` directly on the result of `get_json()` without null-checking, which threw an `AttributeError` that Flask returned as an HTML 500 page. The frontend then failed to parse the HTML as JSON. I recovered by adding `force=True, silent=True` and the `or {}` fallback.

**Primary safety risk:** Dietary constraint hallucination — the model may confidently include a banned allergen in `ingredients_used`. Mitigation: the system prompt explicitly forbids banned ingredients even when they are in the pantry, and TC02/TC10 in the eval suite catch regressions. An accepted limit is that the eval uses string matching, not a certified allergen database, so novel phrasings (e.g. "groundnut paste" for peanut butter) could slip through.
