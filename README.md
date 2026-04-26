# Crucible

> Put your hypothesis through a real test before you spend reagents.

Crucible is an end-to-end app that turns a plain-language research question
into a **literature-grounded, falsifiable experiment plan**. It runs a live
web + academic literature sweep for a novelty signal, then generates a
structured plan covering protocol, materials & suppliers, budget, timeline,
and risks. A built-in review loop captures your inline corrections and
retrieves them as few-shot examples on the next plan in the same domain — so
the system gets sharper every time you use it.

Built for **Hackathon Challenge 04 — The AI Scientist**.

---

## What it does

1. **You paste a research question** in plain English (with an optional
   domain: Biology, Chemistry, Machine Learning, Materials, or one you add).
2. **Literature QC** runs three searches in parallel:
   - **Tavily** for the live web (recent news, blog posts, guides)
   - **Semantic Scholar** for peer-reviewed papers (DOI, authors, year)
   - **arXiv** for preprints (DOI, authors, year)
   - A novelty score is computed from title-token overlap and shown on a
     0–100 scale (`Likely novel` / `Similar work exists` / `Close match found`).
3. **Plan generation** uses an OpenAI-compatible LLM (default: `openai/gpt-oss-120b`
   served free via OpenRouter) to produce a long-form JSON plan with **at least
   10 protocol steps, 8 materials, 6 budget items, 5 timeline phases, and 5 risks**,
   each in concrete, lab-realistic detail.
4. **Inline correction & review loop**. Pick any field of the plan, edit its
   JSON, leave a note explaining the fix, and submit. Future generations in
   the same domain retrieve the most similar past corrections via TF-IDF
   cosine similarity and inject them into the prompt as few-shot examples.
5. **History & Admin**. Every plan is versioned and recoverable. Admin lets
   you edit per-domain system prompts and audit every correction.

## What it isn't

- **Not a fine-tuned model.** No training, no embeddings dataset. Everything
  is live retrieval + in-context prompting.
- **Not a replacement for peer review.** The novelty score is a signal, not
  a verdict — read the actual cited papers.

## Tech overview

| Layer | Stack |
|---|---|
| Frontend | React 19 + Vite + TypeScript |
| Backend | FastAPI + httpx + aiosqlite |
| Storage | SQLite (local file `backend/ai_scientist.sqlite`) |
| LLM | Any OpenAI-compatible endpoint (default: `openai/gpt-oss-120b` via OpenRouter free tier) |
| Literature | Semantic Scholar + arXiv + Tavily (all free / freemium) |

## Quickstart

Two terminals.

**Backend** (port 8000):

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate           # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                # then fill in keys (see below)
uvicorn app.main:app --reload
```

**Frontend** (port 5173):

```bash
cd frontend
npm install
npm run dev
```

Then open <http://localhost:5173>.

## Environment variables

Create `backend/.env` from `backend/.env.example`:

| Variable | Required? | What it's for |
|---|---|---|
| `OPENAI_API_KEY` | **yes** | Auth token for any OpenAI-compatible LLM (we use OpenRouter; key starts with `sk-or-v1-...`) |
| `OPENAI_BASE_URL` | optional | e.g. `https://openrouter.ai/api/v1`. Omit for the real OpenAI API |
| `OPENAI_MODEL` | optional | Default: `gpt-4o-mini`. We use `openai/gpt-oss-120b:free` on OpenRouter |
| `TAVILY_API_KEY` | optional | Enables live web search; without it, only academic refs are returned |
| `AI_SCIENTIST_DB_PATH` | optional | Path to the SQLite file. Default: `ai_scientist.sqlite` |

`backend/.env` is gitignored. **Never commit it.**

## Demo script (90 seconds)

1. Open <http://localhost:5173>. Pick a domain (e.g. Biology).
2. Paste a question, e.g. *"Can CRISPR-Cas9 enhance drought tolerance in
   wheat by editing DREB transcription factors?"*. Click **Run literature QC**.
3. Show the novelty score (e.g. `45/100`), the web sources card, and the
   research papers card with title / authors / year / DOI.
4. Click **Generate plan**. ~10–15 s later, scroll through the protocol,
   materials, budget, timeline, and risks.
5. Open **Inline correction**, pick *Materials · <a reagent>*, fix a wrong
   catalog number, leave a note, save. Re-run the plan; the model honors
   your correction.
6. Open **History** to show versioning, and **Admin** to show the live
   feedback store and editable per-domain prompts.

## Repository layout

```
.
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI app + endpoints
│   │   ├── db.py               # SQLite schema + queries
│   │   ├── models.py           # Pydantic schemas
│   │   ├── config.py           # env-driven settings
│   │   └── providers/
│   │       ├── literature.py   # Tavily + Semantic Scholar + arXiv
│   │       └── llm.py          # OpenAI-compatible chat completions
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.tsx             # routes, all views, correction form
│   │   ├── App.css             # dark theme
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

## Roadmap (post-hackathon)

- Native Anthropic provider (Claude Sonnet 4.5) for higher-quality plans
- pgvector / Postgres for the feedback store at scale
- Export plan as Markdown / PDF / JSON
- Real reproducibility check (run the protocol search against existing
  registered preprints/protocols)
- Multi-user auth + per-scientist feedback scoping
