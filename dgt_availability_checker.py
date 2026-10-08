from datetime import datetime
from difflib import SequenceMatcher
import asyncio
import nodriver as uc
import random
import sys
import os
import unicodedata
import logging
from dotenv import load_dotenv


# ---------------------------------------------------------------------------- #
#                       Logging and environment variables                      #
# ---------------------------------------------------------------------------- #

load_dotenv()

DEBUG = os.getenv("DEBUG", "False") == "True"

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# Create app-specific logger
log = logging.getLogger("autocita-dgt")
log.setLevel(logging.DEBUG if DEBUG else logging.INFO)


# ---------------------------------------------------------------------------- #
#                                     Utils                                    #
# ---------------------------------------------------------------------------- #
# Area option names to look for, in order of preference, for each procedure.
# A matriculación can also be booked with a generic vehículos appointment when
# the office has no specific matriculación area, and "Trámites generales" is
# the last resort for offices without a vehicles area.
AREA_TARGETS = {
    "matriculacion": ["matriculacion", "vehiculos", "generales"],
    "vehiculos": ["vehiculos", "generales"],
}

# Minimum similarity between a word of the option and the target to count as a match
AREA_MATCH_THRESHOLD = 0.8


def normalize_text(text: str) -> str:
    """Lowercase and strip accents so "Matriculación" matches "matriculacion"."""
    text = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(char for char in text if not unicodedata.combining(char))


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def match_area_option(option_texts: list[str], procedure: str) -> int | None:
    """
    Return the index of the area option that best fits the procedure, or None.

    Each target is tried in order. An option matches a target when one of its
    words is similar enough to it (so "Matriculación de Vehículos" matches
    "matriculacion"); among the matches, the one whose whole text is closest to
    the target wins (so "Vehículos" beats "Matriculación de Vehículos" for
    "vehiculos").
    """
    normalized = [normalize_text(text) for text in option_texts]

    for target in AREA_TARGETS[procedure]:
        best_index, best_score = None, None
        for index, text in enumerate(normalized):
            word_score = max(
                (similarity(word, target) for word in text.split()), default=0
            )
            if word_score < AREA_MATCH_THRESHOLD:
                continue
            score = (word_score, similarity(text, target))
            if best_score is None or score > best_score:
                best_index, best_score = index, score
        if best_index is not None:
            return best_index

    return None


async def wait_random_time(min_seconds, max_seconds):
    # Non-blocking so the web UI stays responsive while a check runs
    await asyncio.sleep(random.uniform(min_seconds, max_seconds))


async def wait_until_page_is_ready(page, complete=True):
    if complete:
        await page.evaluate(
            expression="""
                new Promise((resolve) => {
                    if (document.readyState === 'complete') {
                        resolve();
                    } else {
                        document.addEventListener('readystatechange', () => {
                            if (document.readyState === 'complete') {
                                resolve();
                            }
                        });
                    }
                });
            """,
            await_promise=True,
        )
    else:
        await page.evaluate(
            expression="""
                new Promise((resolve) => {
                    if (document.readyState === 'interactive') {
                        resolve();
                    } else {
                        document.addEventListener('readystatechange', () => {
                            if (document.readyState === 'interactive') {
                                resolve();
                            }
                        });
                    }
                });
            """,
            await_promise=True,
        )


async def save_debug_screenshot(page, step: str):
    if DEBUG:
        log.debug("🔍 Saving a debug screenshot of the page...")
        filename = await page.save_screenshot(
            filename=f"screenshots/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{step}.png",
            full_page=True,
        )
        log.debug("✅ Debug screenshot saved")
        return filename


async def save_screenshot(page, step: str):
    log.debug("🔍 Saving a screenshot of the page...")
    filename = await page.save_screenshot(
        filename=f"screenshots/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{step}.png",
        full_page=True,
    )
    log.debug("✅ Screenshot saved")
    return filename


# ---------------------------------------------------------------------------- #
#                                Main Functions                                #
# ---------------------------------------------------------------------------- #
async def office_availability_checker(browser, office_id: str, procedure: str):

    log.info(f"🔍 Checking availability for office {office_id}...")

    # --------------------------------- Open site -------------------------------- #
    log.info("🌐 Opening the entry URL...")
    page = await browser.get(
        "https://sedeclave.dgt.gob.es/WEB_CITE_CONSULTA/paginas/inicio.faces"
    )

    # Wait for the page to be ready
    # Use "interactive" instead of "complete" if you don't want to wait for all resources to be loaded
    log.debug("🌐 Waiting for the page to be ready...")
    await wait_until_page_is_ready(page, complete=True)

    await wait_random_time(1, 3)

    # ------------------------------- Select office ------------------------------ #
    log.info("🔍 Selecting the office...")

    # Find the select element with id "formselectorCentro:j_id_2i"
    log.debug("🔍 Finding the office select field...")
    office_select = await page.select("select[id='formselectorCentro:j_id_2i']")

    if not office_select:
        log.error("❌ No office select field found")
        return False

    await wait_random_time(1, 3)

    # Scroll into view
    log.debug("🖱️ Scrolling into view...")
    await office_select.scroll_into_view()

    await wait_random_time(1, 3)

    # Focus on the select field
    log.debug("🖱️ Focusing on the select field...")
    await office_select.focus()

    await wait_random_time(1, 3)

    # Get the option
    log.debug(f"🔍 Getting the option with value '{office_id}'...")
    option_to_select = await page.select(f"option[value='{office_id}']")

    if not option_to_select:
        log.error("❌ No option found with value '{office_id}'")
        return False

    # Get the office name and save it to a variable
    log.debug("🔍 Getting the office name...")
    office_name = option_to_select.text

    await wait_random_time(1, 3)

    # Select that option
    log.debug("🖱️ Selecting the option...")
    await option_to_select.select_option()

    log.info(f"✅ Selected office: {office_name}")

    await wait_random_time(1, 3)

    # Save a screenshot on debug mode
    await save_debug_screenshot(page, "office_selected")

    # --------------------- Check for schedule complete alert -------------------- #
    log.info("🔍 Checking if the schedule for this office is complete...")

    # Check if there is a message saying "El horario de atencion al cliente esta completo..."
    complete_text = await page.find(
        "El horario de atencion al cliente esta completo", best_match=True
    )

    if complete_text:
        log.error("❌ The schedule for this office is complete")
        return False

    log.info("✅ There might be availability for this office")

    await wait_random_time(1, 3)

    # Save a screenshot on debug mode
    await save_debug_screenshot(page, "schedule_complete_alert_checked")

    # ------------------------------ Select area ------------------------------ #
    log.info("🔍 Selecting the area...")

    # Look for the select with id "formselectorCentro:idAreaSelector"
    log.debug("🔍 Looking for the area select field...")
    area_select = await page.select("select[id='formselectorCentro:idAreaSelector']")

    if not area_select:
        log.error("❌ No area select field found")
        return False

    await wait_random_time(1, 3)

    # Focus on the select field
    log.debug("🖱️ Focusing on the area select field...")
    await area_select.focus()

    await wait_random_time(1, 3)

    # Get all the options under the area select field
    log.debug("🔍 Getting all the options under the area select field...")
    all_options = await area_select.query_selector_all("option")

    await wait_random_time(1, 3)

    # The area names differ between offices, so pick the closest one to the procedure
    option_texts = [option.text for option in all_options]
    log.debug(f"🔍 Area options found: {option_texts}")
    option_index = match_area_option(option_texts, procedure)

    if option_index is None:
        log.error(
            f"❌ No area option matches the procedure '{procedure}' (options: {option_texts}), exiting..."
        )
        return False

    log.debug("🖱️ Selecting the option...")
    await all_options[option_index].select_option()
    log.info(f"✅ Selected area: {option_texts[option_index]}")

    await wait_random_time(1, 3)

    # Save a screenshot on debug mode
    await save_debug_screenshot(page, "area_selected")

    # --------------------------------- Continue --------------------------------- #
    log.info("🔍 Continuing to the next step...")

    # Find the button with id "formselectorCentro:j_id_2x"
    log.debug("🔍 Looking for the continue button...")
    button = await page.find("button[id='formselectorCentro:j_id_2t']")

    await wait_random_time(1, 3)

    # Click the button
    log.debug("🖱️ Clicking the continue button...")
    await button.click()

    await wait_random_time(1, 3)

    # Wait for the page to be ready
    log.debug("🌐 Waiting for the page to be ready...")
    await wait_until_page_is_ready(page, complete=True)

    # Save a screenshot on debug mode
    await save_debug_screenshot(page, "continue_button_clicked")

    # -------------------------- Select cita presencial -------------------------- #
    log.info("🔍 Selecting cita presencial...")

    # Wait for the <a> element with the attribbute title="Presencial"
    log.debug("🔍 Looking for the <a> element with the attribute title='Presencial'...")
    presence_link = await page.select("a[title='Presencial']")
    if not presence_link:
        log.error("❌ No <a> element with the attribute title='Presencial' found")
        return False

    # TODO: Check if there are multiple <a> elements with the attribute title="Presencial" and select the one that relates to "Tramites de vehículos"

    await wait_random_time(1, 3)

    # Click the link
    log.debug("🖱️ Clicking the 'Pedir cita' link...")
    await presence_link.click()

    await wait_random_time(1, 3)

    # Wait for the page to be ready
    await wait_until_page_is_ready(page, complete=True)

    # Save a screenshot on debug mode
    await save_debug_screenshot(page, "presence_link_clicked")

    # ------------------------- Checking for availability ------------------------ #
    log.info("🔍 Checking for availability...")

    # Check if the "no capacity" dialog is visible
    # The text is always in the HTML, but the dialog is hidden when there IS availability
    # We need to check BOTH: dialog is visible (aria-hidden="false") AND contains the specific message
    log.debug("🔍 Checking if the 'no capacity' dialog is visible...")
    is_no_capacity = await page.evaluate(
        """
        (() => {
            const dialogs = document.querySelectorAll('div.ui-confirm-dialog[aria-hidden="false"]');
            for (const dialog of dialogs) {
                if (dialog.textContent.includes('sin capacidad de citación') || 
                    dialog.textContent.includes('Selecciona otra oficina')) {
                    return true;
                }
            }
            return false;
        })()
        """
    )
    if is_no_capacity:
        log.error(
            "❌ This office is currently without capacity to schedule an appointment"
        )
        return False

    log.info("✅ This office is currently with capacity to schedule an appointment")

    # Take a screenshot of the page
    await save_screenshot(page, "availability_checked")

    # Comment the following line if you want to continue with the booking process
    return True


async def dgt_availability_checker(officeIds: list[int], procedure: str) -> list[int]:
    """Check each office and return the IDs of the ones with availability."""
    available = []

    log.info("🚀 Starting browser...")
    browser = await uc.start(
        headless=True,
        sandbox=False,  # Required in containers (nodriver only auto-disables it for root)
    )

    try:
        for office in officeIds:
            log.info(f"\n{'='*50}")
            if await office_availability_checker(browser, office, procedure):
                available.append(office)
            log.info(f"{'='*50}\n")
    finally:
        log.info("🛑 Closing browser...")
        browser.stop()

    return available


async def main():
    # Madrid - 536

    offices = [543]

    await dgt_availability_checker(offices, "matriculacion")


if __name__ == "__main__":
    uc.loop().run_until_complete(main())
