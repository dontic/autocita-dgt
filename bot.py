import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timedelta

from dgt_availability_checker import dgt_availability_checker, log
from offices import OFFICES
from settings import Settings


class MemoryLogHandler(logging.Handler):
    """Keeps the most recent log lines so the web UI can display them."""

    def __init__(self, capacity=300):
        super().__init__()
        self.lines = deque(maxlen=capacity)
        self.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%H:%M:%S")
        )

    def emit(self, record):
        self.lines.append(self.format(record))


class BotRunner:
    """Runs the periodic checker as a background asyncio task."""

    def __init__(self):
        self.task: asyncio.Task | None = None
        self.settings: Settings | None = None
        self.last_check_at: datetime | None = None
        self.next_check_at: datetime | None = None
        self.last_available: list[int] = []
        self.log_handler = MemoryLogHandler()
        log.addHandler(self.log_handler)

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self, settings: Settings):
        if self.running:
            raise RuntimeError("The bot is already running")
        self.settings = settings
        self.last_available = []
        self.task = asyncio.create_task(self._run())

    async def stop(self):
        if not self.running:
            return
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        self.next_check_at = None
        log.info("🛑 Bot stopped")

    def status(self) -> dict:
        return {
            "running": self.running,
            "last_check_at": self.last_check_at,
            "next_check_at": self.next_check_at,
            "last_available": [
                {"id": office_id, "name": OFFICES.get(office_id, str(office_id))}
                for office_id in self.last_available
            ],
            "logs": list(self.log_handler.lines),
        }

    async def _run(self):
        settings = self.settings
        check_period_seconds = settings.check_period_minutes * 60

        log.info("🚀 Starting DGT availability checker")
        log.info(f"📋 Offices to check: {settings.office_ids}")
        log.info(f"🚗 Procedure: {settings.procedure}")
        log.info(f"⏱️  Check period: {settings.check_period_minutes} minutes")

        while True:
            self.next_check_at = None
            try:
                start_time = time.time()
                log.info("🔄 Running availability check...")
                self.last_available = await dgt_availability_checker(
                    settings.office_ids, settings.procedure
                )
                elapsed_time = time.time() - start_time
                log.info(
                    f"✅ Check completed in {elapsed_time:.2f} seconds. Next check in {settings.check_period_minutes} minutes."
                )
            except Exception as e:
                log.error(f"❌ Error during check: {e}")
                log.info(f"⏳ Retrying in {settings.check_period_minutes} minutes...")

            self.last_check_at = datetime.now().astimezone()
            self.next_check_at = self.last_check_at + timedelta(
                seconds=check_period_seconds
            )
            await asyncio.sleep(check_period_seconds)
