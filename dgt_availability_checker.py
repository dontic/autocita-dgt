from datetime import date, datetime, time
from difflib import SequenceMatcher
import asyncio
import nodriver as uc
import random
import sys
import os
import unicodedata
import logging
from dotenv import load_dotenv

from settings import (
    Booking,
    DateRange,
    Settings,
    load_booking,
    load_settings,
    save_booking,
)


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


# Month names as shown in the calendar header (e.g. "octubre 2026")
SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def parse_calendar_header(text: str) -> tuple[int, int] | None:
    """Return (year, month) from a calendar header like "octubre 2026", or None."""
    words = normalize_text(text).split()
    if len(words) != 2 or words[0] not in SPANISH_MONTHS or not words[1].isdigit():
        return None
    return int(words[1]), SPANISH_MONTHS[words[0]]


def candidate_dates(available: list[date], date_ranges: list[DateRange]) -> list[date]:
    """
    Return the dates worth trying, earliest first: all the available ones, or
    only the user's preferred ones when they gave any.
    """
    if date_ranges:
        preferred = {date_range.date for date_range in date_ranges}
        available = [day for day in available if day in preferred]
    return sorted(available)


def pick_time(
    slots: list[time], day: date, date_ranges: list[DateRange]
) -> time | None:
    """
    Return the earliest slot that falls in one of the user's time windows for
    that day (both ends included), or the earliest slot when they gave no
    dates. None if nothing fits.
    """
    if date_ranges:
        windows = [
            (date_range.start_time, date_range.end_time)
            for date_range in date_ranges
            if date_range.date == day
        ]
        slots = [
            slot for slot in slots if any(start <= slot <= end for start, end in windows)
        ]
    return min(slots, default=None)


async def wait_for_time_slots(page, day: date, timeout=10) -> bool:
    """Wait until the time slots panel shows the given day (it loads via AJAX)."""
    expected = day.strftime("%d/%m/%Y")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        title = await page.query_selector("div[id='formcita:horasJefatura'] .titulo")
        if title and expected in title.text_all:
            return True
        await asyncio.sleep(0.5)
    return False


class BookingCancelledError(Exception):
    """The booked appointment was cancelled but the earlier one could not be booked."""


async def get_error_messages(page) -> list[str]:
    """Return the messages of the red error alerts shown on the page."""
    return await page.evaluate(
        """
        Array.from(document.querySelectorAll('div.alert.alert-danger li'))
            .map((item) => item.textContent.trim())
        """
    )


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
async def office_availability_checker(
    browser, office_id: int, settings: Settings, booking: Booking | None
) -> Booking | None:
    """
    Book the earliest slot at the office that fits the user's date ranges and
    return it, or None if there is none. With an existing booking, only dates
    before it are considered.
    """

    procedure = settings.procedure
    date_ranges = settings.date_ranges

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
        return None

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
        return None

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
        return None

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
        return None

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
        return None

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
        return None

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
        return None

    log.info("✅ This office is currently with capacity to schedule an appointment")

    await wait_random_time(1, 3)

    # -------------------------------- Select date ------------------------------- #
    log.info("🔍 Selecting the date...")

    # The calendar opens on the first month with availability, so the month
    # selector is ignored: only the dates of the month shown are considered
    log.debug("🔍 Looking for the calendar header...")
    header = await page.select("div.cite-calendario-cabecera > div")
    if not header:
        log.error("❌ No calendar header found")
        return None

    year_month = parse_calendar_header(header.text_all)
    if not year_month:
        log.error(f"❌ Could not parse the calendar month '{header.text_all.strip()}'")
        return None
    year, month = year_month

    # Available days are submit inputs whose value is the day number; the rest are plain text.
    # Keep their IDs rather than the elements, as clicking a day re-renders the calendar
    log.debug("🔍 Looking for the available days...")
    day_buttons = await page.select_all(
        "div.cite-calendario-dias input[type='submit']:not([disabled])"
    )
    day_button_ids = {
        date(year, month, int(button.attrs.get("value"))): button.attrs.get("id")
        for button in day_buttons
    }
    log.info(
        f"📅 Available dates: {[day.isoformat() for day in sorted(day_button_ids)]}"
    )

    days_to_try = candidate_dates(list(day_button_ids), date_ranges)
    if not days_to_try:
        log.error("❌ None of the available dates matches your preferred dates")
        return None

    if booking:
        days_to_try = [day for day in days_to_try if day < booking.date]
        if not days_to_try:
            log.info(
                f"⏭️ No available date before the booked one ({booking.date.isoformat()})"
            )
            return None

    # A preferred day may have no slot in the user's time windows, so try each in turn
    for day in days_to_try:
        log.info(f"🔍 Selecting the date {day.isoformat()}...")

        day_button = await page.select(f"input[id='{day_button_ids[day]}']")
        if not day_button:
            log.error(f"❌ No button found for the date {day.isoformat()}")
            return None

        await wait_random_time(1, 3)

        # Clicking a day loads its time slots via AJAX
        log.debug(f"🖱️ Clicking the date {day.isoformat()}...")
        await day_button.click()

        log.debug("🌐 Waiting for the time slots to load...")
        if not await wait_for_time_slots(page, day):
            log.error(f"❌ The time slots for {day.isoformat()} did not load")
            return None

        log.info(f"✅ Selected date: {day.isoformat()}")

        await wait_random_time(1, 3)

        # Save a screenshot on debug mode
        await save_debug_screenshot(page, "date_selected")

        # -------------------------------- Select time ------------------------------- #
        log.info("🔍 Selecting the time...")

        log.debug("🔍 Looking for the available times...")
        time_buttons = await page.select_all(
            "div[id='formcita:horasJefatura'] div.cite-horas input[type='submit']:not([disabled])"
        )
        time_buttons_by_slot = {
            time.fromisoformat(button.attrs.get("value")): button
            for button in time_buttons
        }
        log.info(
            f"🕐 Available times: {[slot.strftime('%H:%M') for slot in sorted(time_buttons_by_slot)]}"
        )

        slot = pick_time(list(time_buttons_by_slot), day, date_ranges)
        if slot is None:
            log.info(
                f"⏭️ No available time on {day.isoformat()} fits your time windows"
            )
            continue

        if booking:
            log.info(
                f"🎯 Found an earlier appointment on {day.isoformat()} at {slot.strftime('%H:%M')}"
            )

        await wait_random_time(1, 3)

        log.debug(f"🖱️ Clicking the time {slot.strftime('%H:%M')}...")
        await time_buttons_by_slot[slot].click()

        log.info(f"✅ Selected time: {slot.strftime('%H:%M')}")

        await wait_random_time(1, 3)

        # Save a screenshot on debug mode
        await save_debug_screenshot(page, "time_selected")
        break
    else:
        log.error("❌ None of the available times matches your preferred time windows")
        return None

    # ------------------------- Fill in the applicant data ------------------------ #
    log.info("🔍 Filling in the applicant data...")

    # Picking a time loads the applicant form as a new page
    log.debug("🌐 Waiting for the applicant form to load...")
    first_name_input = await page.select("input[id='formulario:nombre']", timeout=20)
    if not first_name_input:
        log.error("❌ The applicant form did not load")
        return None

    await wait_until_page_is_ready(page, complete=True)

    # The second surname and phone are optional and left empty: the whole last
    # name goes in the first surname field. Typing into the next field blurs the
    # NIF, which fires its onchange AJAX validation.
    fields = [
        ("formulario:nombre", settings.first_name),
        ("formulario:apellido1", settings.last_name),
        ("formulario:nif", settings.dni),
        ("formulario:email", settings.email),
    ]
    for field_id, value in fields:
        log.debug(f"🔍 Looking for the field '{field_id}'...")
        field = await page.select(f"input[id='{field_id}']")
        if not field:
            log.error(f"❌ No field '{field_id}' found")
            return None

        await wait_random_time(1, 3)

        log.debug(f"⌨️ Typing into the field '{field_id}'...")
        await field.scroll_into_view()
        await field.clear_input()
        await field.send_keys(value)

    log.info("✅ Applicant data filled in")

    await wait_random_time(1, 3)

    # Save a screenshot on debug mode
    await save_debug_screenshot(page, "applicant_data_filled")

    # ------------------------------ Request the cita ----------------------------- #
    log.info("🔍 Requesting the appointment...")
    errors = await submit_appointment_request(page)
    if errors is None:
        return None

    # DGT only allows one pending appointment, so the booked one has to be
    # cancelled before the earlier one can be confirmed
    if errors and booking and any("cita pendiente" in error for error in errors):
        log.info("🔁 The booked appointment has to be cancelled first")

        if not await cancel_booking(browser, booking, settings.dni):
            log.error("❌ Could not cancel the booked appointment, keeping it")
            return None

        # From here on the user has no appointment until the new one is confirmed
        try:
            log.info("🔙 Back to the first tab to confirm the new appointment...")
            await page.bring_to_front()

            await wait_random_time(1, 3)

            # Drop the previous error so it isn't mistaken for a new one
            await page.evaluate(
                "document.querySelectorAll('div.alert.alert-danger').forEach((alert) => alert.remove())"
            )

            errors = await submit_appointment_request(page)
        except Exception as e:
            raise BookingCancelledError(str(e)) from e
        if errors is None:
            raise BookingCancelledError("No 'Solicitar cita' button found")
        if errors:
            raise BookingCancelledError("; ".join(errors))

    if errors:
        log.error(f"❌ The appointment was not booked: {'; '.join(errors)}")
        return None

    log.info(
        f"🎉 Booked an appointment on {day.isoformat()} at {slot.strftime('%H:%M')}"
    )
    return Booking(
        office_id=office_id, date=day, time=slot, booked_at=datetime.now().astimezone()
    )


async def submit_appointment_request(page) -> list[str] | None:
    """
    Click "Solicitar cita" and return the error messages it produced (empty
    when the confirmation message is shown), or None if the button is missing.
    """
    log.debug("🔍 Looking for the 'Solicitar cita' button...")
    submit_button = await page.select("button[id='formulario:enviarFormulario']")
    if not submit_button:
        log.error("❌ No 'Solicitar cita' button found")
        return None

    await wait_random_time(1, 3)

    log.debug("🖱️ Clicking the 'Solicitar cita' button...")
    await submit_button.scroll_into_view()
    await submit_button.click()

    await wait_random_time(3, 5)
    await wait_until_page_is_ready(page, complete=True)

    # The response arrives via AJAX, so wait for either the confirmation or an error
    log.debug("🔍 Waiting for the confirmation message...")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 15
    while True:
        confirmed = await page.evaluate(
            """
            Array.from(document.querySelectorAll("section[id='formulario:mensajes'] div.alert li"))
                .some((item) => item.textContent.includes('tu cita ha sido solicitada'))
            """
        )
        errors = await get_error_messages(page)
        if confirmed or errors or loop.time() > deadline:
            break
        await asyncio.sleep(0.5)

    # Save a screenshot on debug mode
    await save_debug_screenshot(page, "appointment_requested")

    if errors:
        log.debug(f"🔍 Errors shown: {errors}")
        return errors
    if not confirmed:
        return ["No confirmation message was shown"]
    log.debug("✅ Confirmation message shown")
    return []


async def cancel_booking(browser, booking: Booking, dni: str) -> bool:
    """Cancel the booked appointment from "Tus citas" in a new tab."""
    booking_date = booking.date.strftime("%d/%m/%Y")
    booking_time = booking.time.strftime("%H:%M")
    log.info(f"🗑️ Cancelling the appointment on {booking_date} at {booking_time}...")

    log.info("🌐 Opening the entry URL in a new tab...")
    tab = await browser.get(
        "https://sedeclave.dgt.gob.es/WEB_CITE_CONSULTA/paginas/inicio.faces",
        new_tab=True,
    )
    try:
        await wait_until_page_is_ready(tab, complete=True)

        await wait_random_time(1, 3)

        # ------------------------- Look up the appointment ------------------------ #
        log.info("🔍 Looking up the booked appointment...")

        # The page also has the booking form's office select, so scope to forminicio
        log.debug("🔍 Finding the office select field...")
        office_select = await tab.select("select[id='forminicio:idCentro']")
        if not office_select:
            log.error("❌ No office select field found")
            return False

        await office_select.scroll_into_view()
        await office_select.focus()

        await wait_random_time(1, 3)

        option_to_select = await tab.select(
            f"select[id='forminicio:idCentro'] option[value='{booking.office_id}']"
        )
        if not option_to_select:
            log.error(f"❌ No option found with value '{booking.office_id}'")
            return False

        log.debug("🖱️ Selecting the office...")
        await option_to_select.select_option()

        await wait_random_time(1, 3)

        # Set the value directly: typing would open the date picker and fight the input mask
        log.debug("⌨️ Filling in the appointment date...")
        date_set = await tab.evaluate(
            f"""
            (() => {{
                const input = document.getElementById('forminicio:calendarInput');
                if (!input) return false;
                input.value = '{booking_date}';
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return true;
            }})()
            """
        )
        if not date_set:
            log.error("❌ No appointment date field found")
            return False

        await wait_random_time(1, 3)

        log.debug("🔍 Finding the DNI field...")
        dni_input = await tab.select("input[id='forminicio:doi']")
        if not dni_input:
            log.error("❌ No DNI field found")
            return False

        log.debug("⌨️ Typing the DNI...")
        await dni_input.clear_input()
        await dni_input.send_keys(dni)

        await wait_random_time(1, 3)

        # Save a screenshot on debug mode
        await save_debug_screenshot(tab, "cancel_lookup_filled")

        log.debug("🔍 Looking for the 'Buscar' button...")
        search_button = await tab.select(
            "form[id='forminicio'] input[type='submit'][value='Buscar']"
        )
        if not search_button:
            log.error("❌ No 'Buscar' button found")
            return False

        log.debug("🖱️ Clicking the 'Buscar' button...")
        await search_button.click()

        await wait_random_time(2, 4)
        await wait_until_page_is_ready(tab, complete=True)

        # Save a screenshot on debug mode
        await save_debug_screenshot(tab, "cancel_lookup_results")

        # ---------------------------- Cancel the cita ---------------------------- #
        log.info("🔍 Cancelling the appointment...")

        # Make sure the appointment found is the booked one before cancelling it
        log.debug("🔍 Checking the appointment found...")
        appointment_found = await tab.evaluate(
            f"""
            (() => {{
                const section = document.getElementById('seccionGlobal');
                return !!section && section.textContent.includes('{booking_date}, {booking_time}');
            }})()
            """
        )
        if not appointment_found:
            errors = await get_error_messages(tab)
            log.error(
                f"❌ The booked appointment was not found{f': {errors}' if errors else ''}"
            )
            return False

        log.debug("🔍 Looking for the 'Anular cita' button...")
        cancel_button = await tab.select(
            "fieldset[id='seccionGlobal'] button[onclick*=\"PF('confirmation').show()\"]"
        )
        if not cancel_button:
            log.error("❌ No 'Anular cita' button found")
            return False

        await wait_random_time(1, 3)

        log.debug("🖱️ Clicking the 'Anular cita' button...")
        await cancel_button.scroll_into_view()
        await cancel_button.click()

        await wait_random_time(1, 3)

        # Only the opened confirm dialog has aria-hidden="false"
        log.debug("🔍 Looking for the 'Aceptar' button of the confirmation dialog...")
        accept_button = await tab.select(
            "div.ui-confirm-dialog[aria-hidden='false'] input[type='submit'][value='Aceptar']"
        )
        if not accept_button:
            log.error("❌ The cancellation confirmation dialog did not open")
            return False

        log.debug("🖱️ Clicking the 'Aceptar' button...")
        await accept_button.click()

        await wait_random_time(2, 4)
        await wait_until_page_is_ready(tab, complete=True)

        # Save a screenshot on debug mode
        await save_debug_screenshot(tab, "appointment_cancelled")

        cancelled = await tab.evaluate(
            """
            Array.from(document.querySelectorAll('div.alert li'))
                .some((item) => item.textContent.includes('ha sido anulada'))
            """
        )
        if not cancelled:
            errors = await get_error_messages(tab)
            log.error(
                f"❌ The cancellation was not confirmed{f': {errors}' if errors else ''}"
            )
            return False

        log.info(f"✅ Cancelled the appointment on {booking_date} at {booking_time}")
        return True
    finally:
        log.debug("🗂️ Closing the cancellation tab...")
        await tab.close()

async def dgt_availability_checker(
    settings: Settings, booking: Booking | None = None
) -> Booking | None:
    """
    Check the configured offices in order and book the first slot that fits
    the user's date ranges (any slot when there are none) and is earlier than
    the current booking, replacing it. Return the booking the user holds
    afterwards: the new one, the unchanged one, or None if it was cancelled
    and nothing could be booked instead.
    """

    log.info("🚀 Starting browser...")
    browser = await uc.start(
        headless=True,
        sandbox=False,  # Required in containers (nodriver only auto-disables it for root)
    )

    try:
        for office in settings.office_ids:
            log.info(f"\n{'='*50}")
            try:
                new_booking = await office_availability_checker(
                    browser, office, settings, booking
                )
            except BookingCancelledError as e:
                # The other offices can still give the user an appointment
                log.error(
                    f"❌ The booked appointment was cancelled but the new one could not be booked: {e}"
                )
                booking, new_booking = None, None
            log.info(f"{'='*50}\n")
            # Only one appointment can be held at a time
            if new_booking:
                return new_booking
    finally:
        log.info("🛑 Closing browser...")
        browser.stop()

    return booking


async def main():
    # Uses the settings saved from the web UI
    settings = load_settings()
    if not settings:
        log.error("❌ No saved settings found, configure the bot in the web UI first")
        return

    booking = load_booking()
    new_booking = await dgt_availability_checker(settings, booking)
    if new_booking != booking:
        save_booking(new_booking)


if __name__ == "__main__":
    uc.loop().run_until_complete(main())
