# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AutoCita DGT is a self-hosted Python 3.11 bot that periodically drives the Spanish DGT appointment site (`sedeclave.dgt.gob.es/WEB_CITE_CONSULTA`) with a headless Chrome browser and books a vehicle-registration ("matriculación") appointment at the first configured office with a slot that fits the user's preferred dates/time windows. It is configured and started/stopped from a small web UI. After booking, it stops if the appointment is on the earliest preferred date (or, with no preferred dates, no later than the day after tomorrow); otherwise it keeps checking for earlier dates. Replacing the booked appointment with an earlier one (cancel in a new tab, then book) is not implemented yet: the bot only logs the earlier slot.

## Commands

Dependencies are managed with uv (`pyproject.toml` / `uv.lock`). There is no test suite, linter config, or build step; code is formatted with Black (configured in the devcontainer).

```bash
uv sync                                 # install deps into .venv
cp .env.template .env                   # optional, only holds DEBUG (loaded via python-dotenv)
uv run python main.py                   # serve the web UI on http://localhost:8000
uv run python dgt_availability_checker.py  # one-off run (no UI) with the settings saved in data/settings.json
docker build -t autocita-dgt .          # build the image (installs google-chrome-stable)
docker compose up -d                    # run the published image dontic/autocita-dgt:latest
```

Running requires a local Chrome/Chromium install (nodriver launches it). Set `DEBUG=True` to get debug logs and step-by-step screenshots.

## Configuration

- `DEBUG` is the only env var; it must be the exact string `True` to enable.
- Everything else (offices, procedure `matriculacion`/`vehiculos`, check period 5–60 min, applicant name/DNI/email, optional preferred date + time-window rows) is entered in the web UI and persisted to `data/settings.json` (mounted as a volume in Docker). Validation lives in the pydantic `Settings` model in `settings.py`.
- The web UI listens on port 8000 (hardcoded in `main.py`) and has no authentication.

## Architecture

- `main.py` — entry point. FastAPI app served by uvicorn: `GET /` (the UI), `GET /api/offices`, `GET /api/settings`, `GET /api/status`, `POST /api/start` (validates + saves settings, starts the bot), `POST /api/stop`.
- `bot.py` — `BotRunner` runs the check loop, holds the current booking (persisted to `data/booking.json`, forgotten once its date passes) and stops itself — clearing the session flag — when `is_booking_final` says the booking can't be improved. The loop runs as an asyncio task in the same event loop as the web server (start/stop = create/cancel the task). It attaches an in-memory log handler to the `autocita-dgt` logger so `/api/status` can return recent log lines. Sessions survive restarts: `/api/start` and `/api/stop` write `data/session.json` (`{"active": bool}`), and the FastAPI lifespan calls `resume_session()` on boot to restart the bot from the saved settings. Server shutdown stops the bot but deliberately leaves the flag set.
- `settings.py` — `Settings` / `DateRange` models and JSON persistence. `offices.py` — office ID → name map shown in the UI.
- `static/index.html` — the whole UI: a single page with vanilla JS, no build step. It polls `/api/status` every 3s.
- `dgt_availability_checker.py` — all scraping logic, built on **nodriver** (async, undetected Chrome via CDP — not Selenium/Playwright). Logging is configured here (logger name `autocita-dgt`), so importing it also sets up logging.
  - `dgt_availability_checker` starts one headless browser per cycle (`sandbox=False`; note nodriver silently ignores `no_sandbox`) and checks each office sequentially, stopping at the first booking and always stopping the browser in `finally`. Returns the new `Booking` or `None`.
  - `office_availability_checker` walks the site's JSF form flow: select office → bail if "El horario de atencion al cliente esta completo" appears → select area with `match_area_option` (accent-insensitive fuzzy match via `difflib` against `AREA_TARGETS[procedure]`; `matriculacion` falls back to `vehiculos`, and both fall back to `generales`) → click continue → click `a[title='Presencial']` → evaluate JS to detect a *visible* "sin capacidad de citación" confirm dialog (the text is always in the DOM; only `aria-hidden="false"` means no capacity) → read the month shown in the calendar and try candidate days earliest first (only preferred dates, and only dates before the current booking if any) → click the earliest slot in the day's time windows → fill the applicant form (whole last name goes in `apellido1`) → click "Solicitar cita". Any missing element logs an error and returns `None`.
  - Selectors depend on JSF-generated IDs such as `formselectorCentro:j_id_2i` (office select; was `j_id_2h` before 2026-10) and `formselectorCentro:j_id_2x`; these are brittle and are the first thing to check when the flow breaks after a DGT site change.
  - `await wait_random_time(1, 3)` between actions is deliberate human-like pacing to avoid bot detection. It must stay non-blocking (`asyncio.sleep`), otherwise the web UI freezes during checks.
  - Screenshots are written to `screenshots/` (relative to CWD).

## Release

`.github/workflows/build-docker.yml` builds and pushes `dontic/autocita-dgt:<tag>` and `:latest` to Docker Hub when a numeric semver tag (e.g. `1.0.1`) is pushed.
