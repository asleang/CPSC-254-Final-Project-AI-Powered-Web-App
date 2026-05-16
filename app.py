from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
import os
import json

load_dotenv()

app = Flask(__name__)
CORS(app)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """You are a friendly home chef and meal planning expert. 
Given a list of pantry ingredients and dietary preferences, create a practical weekly dinner plan (7 days).

Respond ONLY with valid JSON in this exact format:
{
  "week": [
    {
      "day": "Monday",
      "meal": "Meal Name",
      "description": "One sentence description of the dish.",
      "ingredients_used": ["ingredient1", "ingredient2"],
      "missing_ingredients": ["item1", "item2"],
      "prep_time": "25 mins",
      "difficulty": "Easy"
    }
  ],
  "grocery_gaps": ["item1", "item2", "item3"],
  "tip": "A short practical cooking tip for the week."
}

Rules:
- Use as many pantry ingredients as possible.
- Keep meals practical and family-friendly.
- missing_ingredients should only list truly necessary items not in the pantry.
- grocery_gaps is the combined unique list of all missing ingredients across the week.
- difficulty is one of: Easy, Medium, or Advanced.
- Do not include any text outside the JSON block."""

REFINE_PROMPT = """You are a friendly home chef and meal planning expert.
You are given an existing 7-day dinner plan and a user's feedback about one specific day.
Replace ONLY that day's meal with a better option that addresses the feedback.
Keep all other days exactly the same.

Respond ONLY with the full updated plan as valid JSON in this exact format:
{
  "week": [
    {
      "day": "Monday",
      "meal": "Meal Name",
      "description": "One sentence description.",
      "ingredients_used": ["ingredient1", "ingredient2"],
      "missing_ingredients": ["item1"],
      "prep_time": "25 mins",
      "difficulty": "Easy"
    }
  ],
  "grocery_gaps": ["item1", "item2"],
  "tip": "A short practical cooking tip for the week."
}

Rules:
- Only change the day specified in the feedback. All other days must be identical to the input plan.
- Respect all original dietary restrictions.
- Prefer pantry ingredients when possible.
- difficulty is one of: Easy, Medium, or Advanced.
- Do not include any text outside the JSON block."""


def strip_fences(raw: str) -> str:
    """Remove markdown code fences if the model wraps its JSON in them."""
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


# ── Global error handler: always return JSON, never an HTML error page ────────
@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({"error": f"Server error: {str(e)}"}), 500


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/plan", methods=["POST"])
def generate_plan():
    # force=True accepts any content-type; silent=True returns None on bad JSON
    data = request.get_json(force=True, silent=True) or {}
    ingredients = data.get("ingredients", "").strip()
    dietary = data.get("dietary", "").strip()
    servings = data.get("servings", "4")

    if not ingredients:
        return jsonify({"error": "Please enter at least a few ingredients."}), 400

    user_message = (
        f"Pantry ingredients: {ingredients}\n\n"
        f"Dietary needs / restrictions: {dietary or 'None'}\n"
        f"Servings per meal: {servings}\n\n"
        "Create a 7-day dinner meal plan using these ingredients."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_tokens=2000,
        )
        raw = strip_fences(response.choices[0].message.content)
        plan = json.loads(raw)
        return jsonify(plan)

    except json.JSONDecodeError as e:
        return jsonify({"error": f"Model returned invalid JSON: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/refine", methods=["POST"])
def refine_plan():
    data = request.get_json(force=True, silent=True) or {}
    current_plan = data.get("plan")
    day = data.get("day", "").strip()
    feedback = data.get("feedback", "").strip()
    ingredients = data.get("ingredients", "").strip()
    dietary = data.get("dietary", "").strip()

    if not current_plan or not day or not feedback:
        return jsonify({"error": "Missing plan, day, or feedback."}), 400

    user_message = (
        f"Current meal plan:\n{json.dumps(current_plan, indent=2)}\n\n"
        f"Original pantry ingredients: {ingredients}\n"
        f"Dietary restrictions: {dietary or 'None'}\n\n"
        f'User feedback for {day}: "{feedback}"\n\n'
        f"Please replace the {day} meal to address this feedback, keeping all other days unchanged."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": REFINE_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_tokens=2000,
        )
        raw = strip_fences(response.choices[0].message.content)
        plan = json.loads(raw)
        return jsonify(plan)

    except json.JSONDecodeError as e:
        return jsonify({"error": f"Model returned invalid JSON: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
