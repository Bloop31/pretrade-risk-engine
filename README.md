# Pre-Trade Risk Check Service

Checks every order against configurable risk limits before it reaches the exchange,
and returns `ACCEPT` or `REJECT` with a result for each check. Limits live in a YAML
file that business users can edit; changes are hot-reloaded without a restart.

> Work in progress. Full documentation lands in phase 6.

## Quick start

```bash
make install   # uv sync --locked
make check     # lint + typecheck + tests
make run       # API on http://127.0.0.1:8000 (needs Redis on REDIS_URL)
```

Configuration is via environment variables; see [.env.example](.env.example).

### Windows / OneDrive note

If the repo lives in a OneDrive-synced folder, keep the virtualenv outside it:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$HOME\.venvs\pre-trade"
```
