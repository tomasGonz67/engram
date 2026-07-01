# Tech Debt

## Open

- **No services layer** — business logic currently lives in route handlers. When operations grow complex (e.g. store memory = embed + write to Qdrant + write to Postgres), extract into a services layer (e.g. `memory_service.store()`) to keep routers thin.

- **No `start.sh` script** — collection creation and any future startup logic runs inline on app start. If startup complexity grows (migrations, health checks, seed data), consolidate into a `start.sh` script.
- **POST endpoint uses query param** — `POST /?text=...` should use a request body with Pydantic when building real memory endpoints.

---

## Considered & Rejected

- **ORM (SQLAlchemy)** — considered for Postgres interaction. Rejected — one table, simple queries (insert, update strength, delete where strength < threshold). Raw SQL with psycopg2 is cleaner and easier to reason about for this project size. Revisit if schema complexity grows significantly.

---

## Resolved

- **Double startup on uvicorn reload** — collection creation was running at module level, firing twice due to uvicorn's reloader process. Fixed by moving startup logic into FastAPI's lifespan context manager, which only runs in the server process.
