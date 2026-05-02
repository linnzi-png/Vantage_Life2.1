# VantageLife 2.1

VantageLife is an Expo/React Native app with a TypeScript Node backend.

## Project shape

- `frontend/`: Expo app written in TypeScript.
- `backend/`: Express + TypeScript API that serves the existing `/api` routes.
- `.replit`: Replit run/deploy configuration.

## Run in Replit

1. Import this GitHub repo into Replit.
2. Add these Replit Secrets:
   - `MONGO_URL`
   - `DB_NAME`
   - `EXPO_PUBLIC_BACKEND_URL`

For local development, `EXPO_PUBLIC_BACKEND_URL` is usually `http://localhost:8000`.
In Replit, set it to your backend web URL once Replit exposes port `8000`.
3. Press Run.

The Run command installs root, backend, and frontend dependencies, then starts:

```bash
npm --prefix backend run dev
npm --prefix frontend run web
```

## Local development

From the repo root:

```bash
npm install
npm run install:all
npm run dev
```

Backend only:

```bash
cd backend
cp .env.example .env
npm install
npm run dev
```

Frontend only:

```bash
cd frontend
npm install
npm run web
```
