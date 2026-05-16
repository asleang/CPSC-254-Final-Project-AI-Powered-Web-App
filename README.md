# 🥦 Pantry Meal Planner

A Flask web app that turns your pantry ingredients into a personalized 7-day dinner plan — with a meal feedback/swap system — powered by the OpenAI API.

---

## Setup

### 1. Clone and install dependencies
```bash
git clone <your-repo-url>
cd pantry-meal-planner
pip install -r requirements.txt
```

### 2. Add your OpenAI API key
```bash
cp .env.example .env
# Open .env and set: OPENAI_API_KEY=sk-...
```

### 3. Run the app
```bash
python app.py
```

Open **http://localhost:5000** in your browser.

---

## Example API invocations

### Generate a meal plan
```bash
curl -s -X POST http://localhost:5000/plan \
  -H "Content-Type: application/json" \
  -d '{
    "ingredients": "chicken breasts, garlic, onions, pasta, canned tomatoes, olive oil",
    "dietary": "gluten-free",
    "servings": "4"
  }' | python3 -m json.tool
```

Expected response shape:
```json
{
  "week": [
    {
      "day": "Monday",
      "meal": "Garlic Chicken with Rice",
      "description": "A simple weeknight chicken dish with roasted garlic.",
      "ingredients_used": ["chicken breasts", "garlic", "olive oil"],
      "missing_ingredients": ["rice"],
      "prep_time": "30 mins",
      "difficulty": "Easy"
    }
  ],
  "grocery_gaps": ["rice"],
  "tip": "Batch-cook your proteins on Sunday to save time mid-week."
}
```

### Refine one day based on feedback
```bash
curl -s -X POST http://localhost:5000/refine \
  -H "Content-Type: application/json" \
  -d '{
    "plan": { "week": [...], "grocery_gaps": [...], "tip": "..." },
    "day": "Monday",
    "feedback": "Too complex, I want something under 20 minutes",
    "ingredients": "chicken breasts, garlic, onions, pasta, canned tomatoes, olive oil",
    "dietary": "gluten-free"
  }' | python3 -m json.tool
```

### Empty input — expected 400 error
```bash
curl -s -X POST http://localhost:5000/plan \
  -H "Content-Type: application/json" \
  -d '{"ingredients": "", "dietary": "", "servings": "4"}'
# Returns: {"error": "Please enter at least a few ingredients."}
```

---

## Running the eval suite

```bash
# Make sure the app is running first: python app.py
python eval/run_eval.py --url http://localhost:5000
```

Results are saved to `eval/results.json`.

---

## Project structure

```
pantry-meal-planner/
├── app.py                  # Flask backend + OpenAI API calls (/plan, /refine)
├── templates/
│   └── index.html          # Single-page frontend (vanilla JS)
├── eval/
│   ├── test_cases.json     # 10 labeled test cases with pass criteria
│   └── run_eval.py         # Eval runner — scores against ingredient_utilization_rate
├── requirements.txt        # Pinned dependencies
├── .env.example            # OPENAI_API_KEY placeholder
└── README.md
```

---

## How the multi-call feedback system works

1. **Call 1 (`/plan`)** — User submits pantry ingredients → GPT-4o-mini returns a full 7-day JSON plan.
2. **Call 2 (`/refine`)** — User clicks "Suggest a change" on any day card, types feedback (e.g. "too spicy", "I hate fish") → the full current plan is sent back to GPT-4o-mini with the feedback; only that one day is replaced.

The second call is context-dependent: it receives the whole plan so the model can avoid ingredient repetition and maintain dietary consistency across the week.
