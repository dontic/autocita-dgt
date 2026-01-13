from datetime import datetime
import time
import nodriver as uc
import random
import sys
import requests
import os
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

NTFY_URL = os.getenv("NTFY_URL")
NTFY_TOPIC = os.getenv("NTFY_TOPIC")
NTFY_TOKEN = os.getenv("NTFY_TOKEN")

FORM_FIRST_NAME = os.getenv("FORM_FIRST_NAME")
FORM_LAST_NAME = os.getenv("FORM_LAST_NAME")
FORM_DNI = os.getenv("FORM_DNI")
FORM_EMAIL = os.getenv("FORM_EMAIL")

if not NTFY_URL or not NTFY_TOPIC or not NTFY_TOKEN:
    log.error("❌ NTFY_URL, NTFY_TOPIC or NTFY_TOKEN is not set")
    sys.exit(1)

if not FORM_FIRST_NAME or not FORM_LAST_NAME or not FORM_DNI or not FORM_EMAIL:
    log.error("❌ FORM_FIRST_NAME, FORM_LAST_NAME, FORM_DNI or FORM_EMAIL is not set")
    sys.exit(1)


# ---------------------------------------------------------------------------- #
#                                     Utils                                    #
# ---------------------------------------------------------------------------- #
def wait_random_time(min_seconds, max_seconds):
    time.sleep(random.uniform(min_seconds, max_seconds))


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
async def office_availability_checker(browser, office_id: str):

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

    wait_random_time(1, 3)

    # ------------------------------- Select office ------------------------------ #
    log.info("🔍 Selecting the office...")

    # Find the select element with id "formselectorCentro:j_id_2h"
    log.debug("🔍 Finding the office select field...")
    office_select = await page.select("select[id='formselectorCentro:j_id_2h']")

    if not office_select:
        log.error("❌ No office select field found")
        return False

    wait_random_time(1, 3)

    # Scroll into view
    log.debug("🖱️ Scrolling into view...")
    await office_select.scroll_into_view()

    wait_random_time(1, 3)

    # Focus on the select field
    log.debug("🖱️ Focusing on the select field...")
    await office_select.focus()

    wait_random_time(1, 3)

    # Get the option
    log.debug(f"🔍 Getting the option with value '{office_id}'...")
    option_to_select = await page.select(f"option[value='{office_id}']")

    if not option_to_select:
        log.error("❌ No option found with value '{office_id}'")
        return False

    # Get the office name and save it to a variable
    log.debug("🔍 Getting the office name...")
    office_name = option_to_select.text

    wait_random_time(1, 3)

    # Select that option
    log.debug("🖱️ Selecting the option...")
    await option_to_select.select_option()

    log.info(f"✅ Selected office: {office_name}")

    wait_random_time(1, 3)

    # ------------------------------ Select tramite ------------------------------ #
    log.info("🔍 Selecting the tramite...")

    # Select "Tipo de tramite"
    log.debug("🔍 Looking for the tramite select field...")
    tramite_select = await page.select(
        "select[id='formselectorCentro:idTipoTramiteSelector']"
    )

    # Sometimes there is no tramite select field, and it goes directly to the area select
    if tramite_select:

        wait_random_time(1, 3)

        # Focus on the select field
        log.debug("🖱️ Focusing on the tramite select field...")
        await tramite_select.focus()

        # Get all the options under the tramite select field
        log.debug("🔍 Getting all the options under the tramite select field...")
        all_options = await tramite_select.query_selector_all("option")

        wait_random_time(1, 3)

        log.debug("🔍 Looking for the option that contains the text 'oficina'...")
        for option in all_options:
            option_text = option.text
            if "oficina" in option_text.lower():
                log.debug("🖱️ Selecting the option...")
                await option.select_option()
                log.info(f"✅ Selected tramite: {option_text}")
                break

    else:
        log.warning(
            "⚠️ No tramite select field found, it might be because I need to select the area directly"
        )

    wait_random_time(1, 3)

    # Save a screenshot on debug mode
    await save_debug_screenshot(page, "tramite_selected")

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

    wait_random_time(1, 3)

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

    wait_random_time(1, 3)

    # Focus on the select field
    log.debug("🖱️ Focusing on the area select field...")
    await area_select.focus()

    wait_random_time(1, 3)

    # Get all the options under the area select field
    log.debug("🔍 Getting all the options under the area select field...")
    all_options = await area_select.query_selector_all("option")

    wait_random_time(1, 3)

    # Look for the option that contains the text "matriculación"
    # If there is no text "matriculación", look for the text "vehículos"
    # If there is no text vehiculos, exit

    option_found = False

    for option in all_options:
        option_text = option.text
        if "matriculación" in option_text.lower():
            log.debug("🖱️ Selecting the option...")
            await option.select_option()
            option_found = True
            log.info(f"✅ Selected area: {option_text}")
            break

    if not option_found:
        log.debug(
            "⚠️ No option found with the text 'matriculación', looking for 'vehículos'..."
        )
        for option in all_options:
            option_text = option.text
            if "vehículos" in option_text.lower():
                log.debug("🖱️ Selecting the option...")
                await option.select_option()
                option_found = True
                log.info(f"✅ Selected area: {option_text}")
                break

    if not option_found:
        log.debug(
            "⚠️ No option found with the text 'matriculación' or 'vehículos', looking for 'Tramites generales'..."
        )
        for option in all_options:
            option_text = option.text
            if "generales" in option_text.lower():
                log.debug("🖱️ Selecting the option...")
                await option.select_option()
                option_found = True
                log.info(f"✅ Selected area: {option_text}")
                break

    if not option_found:
        log.error(
            "❌ No area option found with the text 'matriculación', 'vehículos' or 'Tramites generales', exiting..."
        )
        return False

    wait_random_time(1, 3)

    # Save a screenshot on debug mode
    await save_debug_screenshot(page, "area_selected")

    # --------------------------------- Continue --------------------------------- #
    log.info("🔍 Continuing to the next step...")

    # Find the button with id "formselectorCentro:j_id_2x"
    log.debug("🔍 Looking for the continue button...")
    button = await page.find("button[id='formselectorCentro:j_id_2x']")

    wait_random_time(1, 3)

    # Click the button
    log.debug("🖱️ Clicking the continue button...")
    await button.click()

    wait_random_time(1, 3)

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

    wait_random_time(1, 3)

    # Click the link
    log.debug("🖱️ Clicking the 'Pedir cita' link...")
    await presence_link.click()

    wait_random_time(1, 3)

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
    screenshot_filename = await save_screenshot(page, "availability_checked")

    # -------------------------- Send NTFY notification -------------------------- #
    log.info("🔍 Sending NTFY notification...")

    notification_text = (
        f"{office_name} has availability, trying to book an appointment..."
    )

    requests.post(
        f"{NTFY_URL}/{NTFY_TOPIC}",
        data=notification_text.encode(encoding="utf-8"),
        headers={
            "Title": f"{office_name} has availability",
            "Priority": "default",
            "Tags": "calendar",
            "Authorization": f"Bearer {NTFY_TOKEN}",
        },
    )

    with open(f"{screenshot_filename}", "rb") as screenshot_file:
        requests.put(
            f"{NTFY_URL}/{NTFY_TOPIC}",
            data=screenshot_file,
            headers={
                "Filename": "screenshot.png",
                "Content-Type": "image/png",
                "Authorization": f"Bearer {NTFY_TOKEN}",
            },
        )

    log.info("✅ NTFY notification sent")

    # Comment the following line if you want to continue with the booking process
    return True

    # ---------------------- Select the first available date --------------------- #
    log.info("🔍 Selecting the first available date...")

    # Get all the <input> elements that have an id that starts with "formcita..." and are of type "submit"
    log.debug(
        "🔍 Getting all the <input> elements that have an id that starts with 'formcita:j_id_3j' and are of type 'submit'..."
    )
    submit_inputs = await page.query_selector_all(
        "input[id^='formcita:j_id_3j'][type='submit']"
    )

    if not submit_inputs:
        log.error("❌ No available dates found")
        return False

    # Get the first available date
    first_available_date = submit_inputs[0]
    log.debug(f"🔍 First available date: {first_available_date.value}")

    # Scroll into view
    log.debug("🖱️ Scrolling into view...")
    await first_available_date.scroll_into_view()

    wait_random_time(1, 3)

    # Click on the first available date
    log.debug("🖱️ Clicking on the first available date...")
    await first_available_date.click()

    wait_random_time(2, 4)

    # Wait for the page to be ready
    await wait_until_page_is_ready(page, complete=True)

    # Save a screenshot on debug mode
    await save_debug_screenshot(page, "dates_selected")

    # -------------------------- Select the first available time --------------------- #
    log.info("🔍 Selecting the first available time...")

    # Get all the <input> elements that start with "formcita:j_id_40:"
    log.debug(
        "🔍 Getting all the <input> elements that start with 'formcita:j_id_40:'..."
    )
    time_inputs = await page.query_selector_all("input[id^='formcita:j_id_40:']")

    if not time_inputs:
        log.error("❌ No available times found")
        return False

    # Get the first available time
    first_available_time = time_inputs[0]
    log.debug(f"🔍 First available time: {first_available_time.text}")

    # Click on the first available time
    log.debug("🖱️ Clicking on the first available time...")
    await first_available_time.click()

    wait_random_time(1, 3)

    # Wait for the page to be ready
    await wait_until_page_is_ready(page, complete=True)

    log.info(f"✅ Selected the first available time {first_available_time.text}")

    # Save a screenshot on debug mode
    await save_debug_screenshot(page, "time_selected")

    # ----------------------------- Fill out the form ---------------------------- #
    log.info("🔍 Filling out the form...")

    # Click and focus on the <input> with id "formulario:nombre"
    log.debug("🔍 Clicking and focusing on the <input> with id 'formulario:nombre'...")
    name_input = await page.find("input[id='formulario:nombre']")
    await name_input.click()
    await name_input.focus()

    # Write the name
    log.debug("🔍 Writing the name...")
    await name_input.send_keys(FORM_FIRST_NAME)

    # Click and focus on the <input> with id "formulario:apellido1"
    log.debug(
        "🔍 Clicking and focusing on the <input> with id 'formulario:apellido1'..."
    )
    last_name_input = await page.find("input[id='formulario:apellido1']")
    await last_name_input.click()
    await last_name_input.focus()

    wait_random_time(1, 2)

    # Write the last name
    log.debug("🔍 Writing the last name...")
    await last_name_input.send_keys(FORM_LAST_NAME)

    # Click and focus on the <input> with id "formulario:nif"
    log.debug("🔍 Clicking and focusing on the <input> with id 'formulario:nif'...")
    dni_input = await page.find("input[id='formulario:nif']")
    await dni_input.click()
    await dni_input.focus()

    wait_random_time(1, 2)

    # Write the DNI
    log.debug("🔍 Writing the DNI...")
    await dni_input.send_keys(FORM_DNI)

    # Click and focus on the <input> with id "formulario:email"
    log.debug("🔍 Clicking and focusing on the <input> with id 'formulario:email'...")
    email_input = await page.find("input[id='formulario:email']")
    await email_input.click()
    await email_input.focus()

    wait_random_time(1, 2)

    # Write the email
    log.debug("🔍 Writing the email...")
    await email_input.send_keys(FORM_EMAIL)

    wait_random_time(1, 2)

    # Find the conditions <input> with id "formulario:terminosYCondiciones"
    log.debug(
        "🔍 Looking for the conditions <input> with id 'formulario:terminosYCondiciones'..."
    )
    conditions_input = await page.find("input[id='formulario:terminosYCondiciones']")
    await conditions_input.scroll_into_view()

    wait_random_time(1, 2)

    # Click on the conditions
    log.debug("🖱️ Clicking on the conditions...")
    await conditions_input.click()

    wait_random_time(1, 2)

    # Save a screenshot of the page on debug mode
    await save_debug_screenshot(page, "form_filled")

    # Click the <button> with id "formulario:enviarFormulario"
    log.debug("🔍 Looking for the <button> with id 'formulario:enviarFormulario'...")
    send_button = await page.find("button[id='formulario:enviarFormulario']")
    await send_button.click()

    wait_random_time(1, 3)

    # Wait for the page to be ready
    await wait_until_page_is_ready(page, complete=True)

    # --------------------- Check if there is an error dialog -------------------- #
    log.info("🔍 Checking if there is an error dialog...")

    error_dialog = False

    # Check if there is a text <p> with the text "Error grave"
    error_text = await page.find("Error grave", best_match=True)
    if error_text:
        log.error("❌ There is an error dialog")
        error_dialog = True
    else:
        log.info("✅ No error dialog found")

    # Save a screenshot of the page
    screenshot_filename = await save_screenshot(page, "no_error_dialog_found")

    # -------------------------- Send NTFY notification -------------------------- #
    log.info("🔍 Sending NTFY notification...")

    if error_dialog:
        notification_title = f"Could not book appointment"
        notification_body = f"Could not book appointment for {office_name}"
    else:
        notification_title = f"Appointment booked!"
        notification_body = f"Appointment booked for {office_name}"

    requests.post(
        f"{NTFY_URL}/{NTFY_TOPIC}",
        data=notification_body.encode(encoding="utf-8"),
        headers={
            "Title": notification_title,
            "Priority": "default",
            "Tags": "white_check_mark",
            "Authorization": f"Bearer {NTFY_TOKEN}",
        },
    )

    with open(f"{screenshot_filename}", "rb") as screenshot_file:
        requests.put(
            f"{NTFY_URL}/{NTFY_TOPIC}",
            data=screenshot_file,
            headers={
                "Filename": "screenshot.png",
                "Content-Type": "image/png",
                "Authorization": f"Bearer {NTFY_TOKEN}",
            },
        )

    return True


async def dgt_availability_checker(officeIds: list[str]):

    log.info("🚀 Starting browser...")
    browser = await uc.start(
        headless=True,
        no_sandbox=True,  # Run as root
    )

    try:
        for office in officeIds:
            log.info(f"\n{'='*50}")
            await office_availability_checker(browser, office)
            log.info(f"{'='*50}\n")
    finally:
        log.info("🛑 Closing browser...")
        browser.stop()


async def main():
    # Madrid - 536

    offices = [543]

    await dgt_availability_checker(offices)


if __name__ == "__main__":
    uc.loop().run_until_complete(main())
