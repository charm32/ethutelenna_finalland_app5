# eThute Lenna 5.0 — Deployment Guide

## Project Structure
```
ethutelenna_v2/
├── main.py              ← FastAPI backend + serves frontend
├── app.html             ← Full HTML app (replaces Streamlit)
├── index.html           ← Landing page (login/register now active)
├── config.py            ← App configuration
├── debugger.py          ← Logging utilities
├── requirements.txt     ← Python dependencies
├── railway.toml         ← Railway deployment config
├── Procfile             ← Start command
├── .env                 ← Your secret keys (never commit this)
├── static/              ← Images, CSS, logo files
├── study_guides/        ← Upload subject PDF study guides here
└── previous_papers/     ← Upload past exam papers here
```

## Key URLs
- `/`        → Landing page (index.html)
- `/app`     → Full study app (app.html)
- `/docs`    → API documentation (Swagger UI)
- `/health`  → Health check

## What Changed in v5.0

### 1. RAG Fix — Ask AI searches ALL PDFs
The `/subjects/{name}/ask` endpoint now searches BOTH:
- `study_guides/` folder
- `previous_papers/` folder

All PDFs for the selected subject are merged into one ChromaDB
collection (`_multi` suffix). This means better, more complete answers.

### 2. Streamlit Replaced
- Old: `streamlit run frontend_main.py`
- New: `uvicorn main:app` serves everything

### 3. Landing Page Active
- Login button → calls `/auth/login` API → redirects to `/app`
- Register button → calls `/auth/register` API → redirects to `/app`

## Naming Your PDFs

Name your PDFs so they match the subject. Examples:
```
study_guides/
  physics_grade12.pdf
  chemistry_study_guide.pdf
  mathematics_2024.pdf
  maths_lit_guide.pdf

previous_papers/
  physics_2023.pdf
  chemistry_2022.pdf
  mathematics_2021.pdf
```

## Local Development

```bash
# 1. Create virtual environment
python -m venv venv
venv\Scripts\activate   # Windows
source venv/bin/activate  # Mac/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create .env file
# JWT_SECRET=YourSecretKey123
# OPENROUTER_API_KEY=sk-or-v1-...

# 4. Create folders
mkdir study_guides previous_papers static

# 5. Run
uvicorn main:app --reload --port 8000
```

Open: http://localhost:8000

## Railway Deployment

1. Push your project to GitHub
2. Go to https://railway.app
3. Click "New Project" → "Deploy from GitHub"
4. Select your repo
5. Add environment variables:
   - `JWT_SECRET` = your secret
   - `OPENROUTER_API_KEY` = your key
6. Railway auto-deploys from railway.toml

## Adding Study Guides to Railway

Option A — Include PDFs in your GitHub repo (small files only)
Option B — Use Railway Volumes (for large files, ~$0.25/GB/month)
Option C — Use a cloud storage like Supabase Storage or Cloudinary
