# Contributing to WattSlot

Thank you for your interest! Bug reports, ideas, translations and code are all welcome. *Les contributions en français sont les bienvenues aussi.*

## Before you start

- **Bugs and ideas**: open an [issue](https://github.com/jmcruvellier/wattslot/issues/new/choose) first. For a bug, attach the anonymised report from **Settings → App status → Prepare a report**.
- **Larger changes**: describe them in an issue before writing code, so we can agree on the approach.
- **Languages**: issues and pull requests in English or French. The code's comments and commit messages are in French today; English comments in your changes are fine.

## Development setup

Requirements: Python 3.11+, Node.js 22.12+ with npm 11 (`npm install -g npm@11.20.0`), Docker with Docker Compose.

**A test Home Assistant**, replaying realistic days, with the app connected to it (nothing to type in):

```bash
docker compose -f dev/docker-compose.yml up -d --build
```

Home Assistant on http://localhost:8123 (account `dev` / `dev-password`), WattSlot on http://localhost:8100. See [`dev/README.md`](dev/README.md) to replay days and run the end-to-end check.

**Backend** (FastAPI, Oxigraph, SQLite), on port 8100:

```bash
cd app/backend
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"        # Windows: .venv/Scripts/python
WATTSLOT_DATA_DIR=data .venv/bin/uvicorn wattslot.main:app --reload --port 8100
```

**Interface** (React, TypeScript, Vite), on port 5173, forwarding `/api` to the backend:

```bash
cd app/frontend
npm ci
npm run dev
```

## Checks

The same as the CI; please run them before opening a pull request:

```bash
cd app/backend && ruff check . && ruff format --check . && mypy && pytest
cd app/frontend && npm run lint && npm run typecheck && npm test && npm run build && npm run size
python dev/tools/privacy_check.py      # no personal data in published files
```

## Conventions

- **Exact versions** for every dependency, published at least two weeks before they are added.
- **No personal data** in the code (addresses, host or device names, your own entity IDs): everything comes from the configuration. Example IP addresses use the documentation range `192.0.2.x`.
- **Relative URLs** in the interface (`api/health`, not `/api/health`): behind Home Assistant's ingress the app is served under a variable prefix.
- **Translations**: one JSON catalog per language in `app/frontend/src/i18n/catalogs/`, with the same keys and parameters everywhere (checked by the tests). Texts written by the server are in `app/backend/src/wattslot/planning/locales/`.
- **Tests** with every change: the backend and interface test suites are the safety net of the planner.
- One topic per pull request, with a clear description and screenshots when the interface changes.

## Translations

German, Dutch, Spanish and Italian were prepared without native speakers and need review. If you speak one of them, open a **Translation** issue or edit the catalog directly in a pull request; partial reviews are useful too.

## License

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](LICENSE).
