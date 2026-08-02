# Development

## Running the Environment

```bash
docker compose -f docker-compose-dev.yml up -d
```

## Services

| Service | URL |
|---------|-----|
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| Qdrant | http://localhost:6333 |
| Qdrant Dashboard | http://localhost:6333/dashboard |
| Postgres | localhost:5432 |

## Stopping the Environment

```bash
docker compose -f docker-compose-dev.yml down
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |

Requires the backend already running (see above) — the frontend calls it via `VITE_API_URL` (defaults to `http://localhost:8000`).

## Scripts

See `scripts.md` for utility scripts (`scripts/clear.sh`, `scripts/seed.py`, `scripts/backdate.sh`).
