import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from bot import BotRunner
from dgt_availability_checker import log
from offices import OFFICES
from settings import (
    Settings,
    load_session_active,
    load_settings,
    save_session_active,
    save_settings,
)

HOST = "0.0.0.0"
PORT = 8000
STATIC_DIR = Path(__file__).parent / "static"

bot = BotRunner()


@asynccontextmanager
async def lifespan(app: FastAPI):
    resume_session()
    yield
    # Make sure the browser is closed when the server shuts down. The session
    # flag is left untouched so the bot resumes on the next start.
    await bot.stop()


def resume_session():
    """Restart the bot if it was running when the server last went down."""
    if not load_session_active():
        return
    try:
        settings = load_settings()
    except Exception as e:
        log.error(f"❌ Could not resume the previous session, invalid settings: {e}")
        save_session_active(False)
        return
    if not settings:
        save_session_active(False)
        return
    log.info("♻️ Resuming the previous session")
    bot.start(settings)


app = FastAPI(title="AutoCita DGT", lifespan=lifespan)


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/offices")
async def get_offices():
    return [
        {"id": office_id, "name": name}
        for office_id, name in sorted(OFFICES.items(), key=lambda item: item[1])
    ]


@app.get("/api/settings")
async def get_settings() -> Settings | None:
    return load_settings()


@app.get("/api/status")
async def get_status():
    return bot.status()


@app.post("/api/start")
async def start(settings: Settings):
    if bot.running:
        raise HTTPException(status_code=409, detail="The bot is already running")
    save_settings(settings)
    save_session_active(True)
    bot.start(settings)
    return bot.status()


@app.post("/api/stop")
async def stop():
    save_session_active(False)
    await bot.stop()
    return bot.status()


if __name__ == "__main__":
    asyncio.run(uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT)).serve())
