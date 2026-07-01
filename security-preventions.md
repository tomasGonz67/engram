# Security Preventions

## Credentials & Secrets

- No hardcoded credentials in code — all connection info (Qdrant host/port, Postgres user/password/db, embedding model name) read from environment variables via `os.getenv()`
- Environment variables passed to containers via docker-compose, not stored in code
- `docker-compose.yml` (prod) added to `.gitignore` — never committed to GitHub
- `docker-compose-dev.yml` is committed but contains only local dev credentials, not production secrets

## To Add

- Rate limiting on API endpoints
- Authentication on protected routes
- HTTPS in prod
- Input validation via Pydantic (partially in place)
