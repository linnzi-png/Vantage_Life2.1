# VantageLife 2.1

Real-time sales tracking platform for AO Globe Life - Vantage. Expo/React Native
frontend, Python/FastAPI backend over MongoDB.

## Project shape

- `frontend/`: Expo (SDK 56) app, TypeScript, Expo Router file-based routing.
- `backend/`: FastAPI API (`server.py`), Motor async MongoDB driver, pytest suite in `tests/`.
- `railway.json` + `backend/Procfile` + `backend/nixpacks.toml`: Railway deployment (the live backend).
- `vercel.json`: Vercel deployment of the Expo web export.
- `.replit`: Replit run/deploy configuration (same Python backend).

## Environment

Backend (`backend/.env`, see `backend/.env.example`):

- `MONGO_URL`
- `DB_NAME`

Frontend:

- `EXPO_PUBLIC_BACKEND_URL` — `http://localhost:8000` for local development.

## Local development

From the repo root:

```bash
npm install
npm run install:all   # pip install backend deps + yarn install frontend deps
npm run dev           # uvicorn (port 8000) + expo web, concurrently
```

Backend only:

```bash
cd backend
cp .env.example .env
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
```

Frontend only:

```bash
cd frontend
yarn install
yarn web
```

## Checks

```bash
npm run typecheck   # frontend tsc --noEmit
npm test            # pytest backend/tests
npm run build       # expo web export (what Vercel runs)
```
