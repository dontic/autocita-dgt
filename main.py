import os
import sys
import time
import logging
import nodriver as uc
from dotenv import load_dotenv
import requests

from dgt_availability_checker import dgt_availability_checker

load_dotenv()

log = logging.getLogger(__name__)


def get_office_ids():
    """Get the office IDs from environment variable."""
    office_ids = os.getenv("OFFICE_IDS")
    if not office_ids:
        log.error("❌ OFFICE_IDS environment variable is not set")
        sys.exit(1)
    try:
        return [int(id.strip()) for id in office_ids.split(",")]
    except ValueError:
        log.error(f"❌ OFFICE_IDS must be comma-separated integers, got: {office_ids}")
        sys.exit(1)


def get_check_period_minutes():
    """Get the check period from environment variable."""
    period = os.getenv("CHECK_PERIOD_MINUTES")
    if not period:
        log.error("❌ CHECK_PERIOD_MINUTES environment variable is not set")
        sys.exit(1)
    try:
        return int(period)
    except ValueError:
        log.error(f"❌ CHECK_PERIOD_MINUTES must be a valid integer, got: {period}")
        sys.exit(1)


async def run_checker():
    """Run the availability checker in a loop."""
    office_ids = get_office_ids()
    check_period_minutes = get_check_period_minutes()
    check_period_seconds = check_period_minutes * 60

    log.info("🚀 Starting DGT availability checker")
    log.info(f"📋 Offices to check: {office_ids}")
    log.info(f"⏱️  Check period: {check_period_minutes} minutes")

    # Send a NTFY message to test the connection
    log.info("🔍 Sending NTFY message to test the connection...")
    requests.post(
        f"{os.getenv('NTFY_URL')}/{os.getenv('NTFY_TOPIC')}",
        data="Initializing DGT availability checker",
        headers={
            "Title": "Initializing DGT availability checker",
            "Priority": "default",
            "Tags": "dgt,info",
            "Authorization": f"Bearer {os.getenv('NTFY_TOKEN')}",
        },
    )
    log.info("✅ NTFY message sent")

    while True:
        try:
            start_time = time.time()
            log.info("🔄 Running availability check...")
            await dgt_availability_checker(office_ids)
            elapsed_time = time.time() - start_time
            log.info(
                f"✅ Check completed in {elapsed_time:.2f} seconds. Next check in {check_period_minutes} minutes."
            )
        except Exception as e:
            log.error(f"❌ Error during check: {e}")
            log.info(f"⏳ Retrying in {check_period_minutes} minutes...")

        time.sleep(check_period_seconds)


if __name__ == "__main__":
    uc.loop().run_until_complete(run_checker())
