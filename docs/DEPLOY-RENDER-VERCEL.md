# Deploy Crucible: Render (API) + Vercel (UI)

**Order matters:** deploy the **API on Render first**, copy its public URL, then set **Vite** and deploy on **Vercel**.

---

## Part A — Backend on Render

### Option 1: Blueprint (uses `render.yaml` in this repo)

1. [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**.
2. Connect the **GitHub** repo that contains this project.
3. Select branch (e.g. `main`) and apply the blueprint. A service `crucible-api` will be created.
4. When prompted, set **sensitive** variables:
   - `OPENAI_API_KEY` — your OpenAI-compatible key (e.g. OpenRouter `sk-or-v1-...`).
   - `TAVILY_API_KEY` — for Literature QC web search (`tvly-...`).
5. Wait until the service is **Live**. Open `https://<name>.onrender.com/health` — expect JSON like `{"ok":true}`.
6. Check `https://<name>.onrender.com/settings` — `openai_api_key_set` and `tavily_api_key_set` should be `true` when keys are set.

**Note:** Free tier may **sleep** after idle; the first request can take 30–60s.

### Option 2: Web Service (manual, same as Blueprint)

- **Root directory:** `backend`
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Health check path:** `/health`
- **Environment** (in addition to non-secret defaults you prefer):

| Key | Value |
|-----|--------|
| `OPENAI_BASE_URL` | `https://openrouter.ai/api/v1` (if using OpenRouter) |
| `OPENAI_MODEL` | e.g. `openai/gpt-oss-120b:free` |
| `OPENAI_API_KEY` | (secret) |
| `TAVILY_API_KEY` | (secret) |
| `PYTHON_VERSION` | `3.12.11` (optional; matches `backend/.python-version`) |

**SQLite** on the free web service is **ephemeral**; history may reset on restart. OK for demos.

---

## Part B — Frontend on Vercel

1. [Vercel](https://vercel.com) → **Add New** → **Project** → import the **same** GitHub repo.
2. **Root Directory:** set to `frontend` (important for this monorepo).
3. Framework should detect **Vite**. Build: `npm run build`, output: `dist` (or rely on `frontend/vercel.json`).
4. **Environment variables** (for **Production** at minimum):

| Name | Value |
|------|--------|
| `VITE_API_BASE` | `https://<your-render-service>.onrender.com` — **no** trailing slash, **no** path |

5. **Deploy**. Vite bakes `VITE_API_BASE` in at build time: if you change the API URL later, **rebuild** (Redeploy).

6. Open your `.vercel.app` URL, run **Literature QC** and **Generate plan**; confirm Admin → Settings shows the API as expected.

---

## Checklist

- [ ] Render service Live; `/health` and `/settings` OK
- [ ] Vercel **Root directory** = `frontend`
- [ ] Vercel `VITE_API_BASE` = your Render **HTTPS** API origin
- [ ] Vercel deployment **after** setting `VITE_API_BASE` (redeploy if you changed it)

If the UI still calls `localhost` or the wrong host, the Vercel env was missing at build or Root Directory was not `frontend`.
