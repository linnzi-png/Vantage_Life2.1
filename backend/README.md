# VantageLife Backend

This backend is now TypeScript/Node instead of Python/FastAPI. It keeps the same `/api` route surface used by the Expo frontend.

## Setup

Create `backend/.env` from `.env.example`:

```bash
MONGO_URL=your_mongodb_connection_string
DB_NAME=vantagelife
PORT=8000
```

Install and run:

```bash
npm install
npm run dev
```

Useful scripts:

```bash
npm run check
npm run build
npm start
```

## Replit

Set `MONGO_URL`, `DB_NAME`, and `EXPO_PUBLIC_BACKEND_URL` in Replit Secrets. The root `.replit` file runs the backend and Expo web frontend together.

The backend auto-seeds demo data on first run when `agent_profiles` is empty.
