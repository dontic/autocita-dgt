import asyncio
import logging
import time
from collections import deque
from datetime import date, datetime, timedelta

from dgt_availability_checker import dgt_availability_checker, log
from offices import OFFICES
from settings import Booking, Settings, load_booking, save_booking, save_session_active


def is_booking_final(booking: Booking, settings: Settings, today: date) -> bool:
    """
    Whether the booking is good enough to stop looking for an earlier one: it
    is on the earliest preferred date (whatever the time) or, without preferred
    dates, no later than the day after tomorrow.
    """
    if settings.date_ranges:
        earliest = min(date_range.date for date_range in settings.date_ranges)
        return booking.date <= earliest
    return booking.date <= today + timedelta(days=2)


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
        self.booking: Booking | None = load_booking()
        self.log_handler = MemoryLogHandler()
        log.addHandler(self.log_handler)

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self, settings: Settings):
        if self.running:
            raise RuntimeError("The bot is already running")
        self.settings = settings
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
            "booking": self.booking
            and {
                **self.booking.model_dump(),
                "office_name": OFFICES.get(
                    self.booking.office_id, str(self.booking.office_id)
                ),
            },
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

            # An appointment that already went by no longer counts
            if self.booking and self.booking.date < date.today():
                log.info("🗑️ Forgetting the booked appointment, its date has passed")
                self._set_booking(None)

            if self.booking:
                log.info(
                    f"📌 Booked appointment: {self.booking.date.isoformat()} at "
                    f"{self.booking.time.strftime('%H:%M')} in {OFFICES.get(self.booking.office_id, self.booking.office_id)}"
                )
                if is_booking_final(self.booking, settings, date.today()):
                    log.info("🏁 The booked appointment is the best possible one")
                    self._finish()
                    return
                log.info("🔍 Looking for an earlier appointment...")

            try:
                start_time = time.time()
                log.info("🔄 Running availability check...")
                new_booking = await dgt_availability_checker(settings, self.booking)
                if new_booking:
                    self._set_booking(new_booking)
                    if is_booking_final(new_booking, settings, date.today()):
                        log.info("🏁 The booked appointment is the best possible one")
                        self._finish()
                        return
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

    def _set_booking(self, booking: Booking | None):
        self.booking = booking
        save_booking(booking)

    def _finish(self):
        """Stop for good: the bot won't resume on the next server start."""
        save_session_active(False)
        self.last_check_at = datetime.now().astimezone()
        log.info("🛑 Bot stopped")
