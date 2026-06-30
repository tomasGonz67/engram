# Tech Debt

## Startup

- **No `start.sh` script** — collection creation and any future startup logic runs inline on app start. If startup complexity grows (migrations, health checks, seed data), consolidate into a `start.sh` script.
