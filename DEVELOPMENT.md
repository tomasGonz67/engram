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
