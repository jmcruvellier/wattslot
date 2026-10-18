# Instructions for Claude

- **Languages**: talk to the user in their language (French with the maintainer). Commit messages, code comments and developer documentation are in French (see `CONTRIBUTING.md`); identifiers in English, except existing domain names. User-facing files (`README.md`, `docs/`, issue templates, `ha-addon/wattslot/DOCS.md`) are written in English first, with the French version kept in step (`README.fr.md`, `docs/fr/`, same file names).
- **Branch and pull request** for every change, to `main`; never push to `main` directly. Merge only once every check is pass or skipping.
- **No secret and no personal data** in the repository: no tokens, passwords, IP addresses, host names, device or entity names of a real home. Example addresses use `192.0.2.x`. `dev/tools/privacy_check.py` runs in the CI with a private list of terms (secret `PRIVACY_TERMS`); never write that list anywhere in the repository, a commit or a pull request. Add a `.env.example` next to any component that reads a `.env`.
- **Checks** before opening a pull request: those listed in `CONTRIBUTING.md` (ruff, mypy, pytest; lint, typecheck, vitest, build and size of the interface; privacy check).
- **Translations**: a new interface text goes into the six catalogs of `app/frontend/src/i18n/catalogs/` (the tests check keys and parameters); texts written by the server into `app/backend/src/wattslot/planning/locales/`.
- **Releases**: `python app/scripts/version.py X.Y.Z` prepares the version and the changelog in a pull request; the maintainer pushes the `vX.Y.Z` tag, which publishes the image, the `addon` branch and the GitHub release.
- **Deployment** to the maintainer's own installations is not described here and not done by Claude: a pull request that needs one says which image to update.
