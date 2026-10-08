# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AutoCita DGT is a self-hosted Python 3.11 bot that periodically drives the Spanish DGT appointment site (`sedeclave.dgt.gob.es/WEB_CITE_CONSULTA`) with a headless Chrome browser and checks the configured offices for free vehicle-registration ("matriculación") slots. It is configured and started/stopped from a small web UI. It does not book appointments yet — `office_availability_checker` returns `True` right after taking a screenshot. The applicant fields and preferred date ranges are collected and saved but not used by the bot yet.

## Commands

Dependencies are managed with uv (`pyproject.toml` / `uv.lock`). There is no test suite, linter config, or build step; code is formatted with Black (configured in the devcontainer).

```bash
uv sync                                 # install deps into .venv
cp .env.template .env                   # optional, only holds DEBUG (loaded via python-dotenv)
uv run python main.py                   # serve the web UI on http://localhost:8000
uv run python dgt_availability_checker.py  # one-off check (no UI) of the offices hardcoded in its main()
docker build -t autocita-dgt .          # build the image (installs google-chrome-stable)
docker compose up -d                    # run the published image dontic/autocita-dgt:latest
```

Running requires a local Chrome/Chromium install (nodriver launches it). Set `DEBUG=True` to get debug logs and step-by-step screenshots.

## Configuration

- `DEBUG` is the only env var; it must be the exact string `True` to enable.
- Everything else (offices, check period 5–60 min, applicant name/DNI/email, optional preferred date + time-window rows) is entered in the web UI and persisted to `data/settings.json` (mounted as a volume in Docker). Validation lives in the pydantic `Settings` model in `settings.py`.
- The web UI listens on port 8000 (hardcoded in `main.py`) and has no authentication.

## Architecture

- `main.py` — entry point. FastAPI app served by uvicorn: `GET /` (the UI), `GET /api/offices`, `GET /api/settings`, `GET /api/status`, `POST /api/start` (validates + saves settings, starts the bot), `POST /api/stop`.
- `bot.py` — `BotRunner` runs the check loop as an asyncio task in the same event loop as the web server (start/stop = create/cancel the task). It attaches an in-memory log handler to the `autocita-dgt` logger so `/api/status` can return recent log lines. Sessions survive restarts: `/api/start` and `/api/stop` write `data/session.json` (`{"active": bool}`), and the FastAPI lifespan calls `resume_session()` on boot to restart the bot from the saved settings. Server shutdown stops the bot but deliberately leaves the flag set.
- `settings.py` — `Settings` / `DateRange` models and JSON persistence. `offices.py` — office ID → name map shown in the UI.
- `static/index.html` — the whole UI: a single page with vanilla JS, no build step. It polls `/api/status` every 3s.
- `dgt_availability_checker.py` — all scraping logic, built on **nodriver** (async, undetected Chrome via CDP — not Selenium/Playwright). Logging is configured here (logger name `autocita-dgt`), so importing it also sets up logging.
  - `dgt_availability_checker` starts one headless browser per cycle (`sandbox=False`; note nodriver silently ignores `no_sandbox`) and checks each office sequentially, always stopping the browser in `finally`. Returns the IDs of the offices with availability.
  - `office_availability_checker` walks the site's JSF form flow: select office → select tramite containing "oficina" (this select is sometimes absent) → bail if "El horario de atencion al cliente esta completo" appears → select area by text fallback (`matriculación` → `vehículos` → `generales`) → click continue → click `a[title='Presencial']` → evaluate JS to detect a *visible* "sin capacidad de citación" confirm dialog (the text is always in the DOM; only `aria-hidden="false"` means no capacity). Any missing element logs an error and returns `False`.
  - Selectors depend on JSF-generated IDs such as `formselectorCentro:j_id_2h` (as of 2026-10 the site renders `j_id_2i`) and `formselectorCentro:j_id_2x`; these are brittle and are the first thing to check when the flow breaks after a DGT site change.
  - `await wait_random_time(1, 3)` between actions is deliberate human-like pacing to avoid bot detection. It must stay non-blocking (`asyncio.sleep`), otherwise the web UI freezes during checks.
  - Screenshots are written to `screenshots/` (relative to CWD).

## Release

`.github/workflows/build-docker.yml` builds and pushes `dontic/autocita-dgt:<tag>` and `:latest` to Docker Hub when a numeric semver tag (e.g. `1.0.1`) is pushed.
