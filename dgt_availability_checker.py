import time
import nodriver as uc
import random
import sys
import requests
import os
from dotenv import load_dotenv

load_dotenv()

NTFY_URL = os.getenv("NTFY_URL")
NTFY_TOPIC = os.getenv("NTFY_TOPIC")
NTFY_TOKEN = os.getenv("NTFY_TOKEN")

if not NTFY_URL or not NTFY_TOPIC or not NTFY_TOKEN:
    print("❌ NTFY_URL, NTFY_TOPIC or NTFY_TOKEN is not set")
    sys.exit(1)


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


async def office_availability_checker(browser, office_id: str):

    print(f"🔍 Checking availability for office {office_id}...")

    print("🌐 Opening the entry URL...")
    page = await browser.get(
        "https://sedeclave.dgt.gob.es/WEB_CITE_CONSULTA/paginas/inicio.faces"
    )

    # Wait for the page to be ready
    # Use "interactive" instead of "complete" if you don't want to wait for all resources to be loaded
    print("🌐 Waiting for the page to be ready...")
    await wait_until_page_is_ready(page, complete=True)

    wait_random_time(1, 3)

    # Find the select element with id "formselectorCentro:j_id_2h"
    print("🔍 Finding the office select field...")
    office_select = await page.select("select[id='formselectorCentro:j_id_2h']")

    if not office_select:
        print("❌ No office select field found")
        return False

    wait_random_time(1, 3)

    # Scroll into view
    print("🖱️ Scrolling into view...")
    await office_select.scroll_into_view()

    wait_random_time(1, 3)

    # Focus on the select field
    print("🖱️ Focusing on the select field...")
    await office_select.focus()

    wait_random_time(1, 3)

    # Get the option
    print(f"🔍 Getting the option with value '{office_id}'...")
    option_to_select = await page.select(f"option[value='{office_id}']")

    if not option_to_select:
        print("❌ No option found with value '{office_id}'")
        return False

    # Get the office name and save it to a variable
    print(f"🔍 Getting the office name...")
    office_name = option_to_select.text
    print(f"✅ Office name: {office_name}")

    wait_random_time(1, 3)

    # Select that option
    print("🖱️ Selecting the option...")
    await option_to_select.select_option()

    wait_random_time(1, 3)

    # Select "Tipo de tramite"
    print("🔍 Looking for the tramite select field...")
    tramite_select = await page.select(
        "select[id='formselectorCentro:idTipoTramiteSelector']"
    )

    # Sometimes there is no tramite select field, and it goes directly to the area select
    if tramite_select:

        wait_random_time(1, 3)

        # Focus on the select field
        print("🖱️ Focusing on the tramite select field...")
        await tramite_select.focus()

        # Get all the options under the tramite select field
        print("🔍 Getting all the options under the tramite select field...")
        all_options = await tramite_select.query_selector_all("option")

        wait_random_time(1, 3)

        print("🔍 Looking for the option that contains the text 'oficina'...")
        for option in all_options:
            option_text = option.text
            if "oficina" in option_text.lower():
                print("🖱️ Selecting the option...")
                await option.select_option()
                break

    else:
        print(
            "⚠️ No tramite select field found, it might be because I need to select the area directly"
        )

    wait_random_time(1, 3)

    # Check if there is a message saying "El horario de atencion al cliente esta completo..."
    print("🔍 Checking if the schedule for this office is complete...")
    complete_text = await page.find(
        "El horario de atencion al cliente esta completo", best_match=True
    )

    if complete_text:
        print("❌ The schedule for this office is complete")
        return False

    print("✅ There is availability for this office")

    wait_random_time(1, 3)

    # Look for the select with id "formselectorCentro:idAreaSelector"
    print("🔍 Looking for the area select field...")
    area_select = await page.select("select[id='formselectorCentro:idAreaSelector']")

    if not area_select:
        print("❌ No area select field found")
        return False

    wait_random_time(1, 3)

    # Focus on the select field
    print("🖱️ Focusing on the area select field...")
    await area_select.focus()

    wait_random_time(1, 3)

    # Get all the options under the area select field
    print("🔍 Getting all the options under the area select field...")
    all_options = await area_select.query_selector_all("option")

    wait_random_time(1, 3)

    # Look for the option that contains the text "matriculación"
    # If there is no text "matriculación", look for the text "vehículos"
    # If there is no text vehiculos, exit

    option_found = False

    for option in all_options:
        option_text = option.text
        if "matriculación" in option_text.lower():
            print("🖱️ Selecting the option...")
            await option.select_option()
            option_found = True
            break

    if not option_found:
        print(
            "⚠️ No option found with the text 'matriculación', looking for 'vehículos'..."
        )
        for option in all_options:
            option_text = option.text
            if "vehículos" in option_text.lower():
                print("🖱️ Selecting the option...")
                await option.select_option()
                option_found = True
                break

    if not option_found:
        print("❌ No option found with the text 'matriculación' or 'vehículos'")
        return False

    wait_random_time(1, 3)

    # Find the button with id "formselectorCentro:j_id_2x"
    print("🔍 Looking for the continue button...")
    button = await page.find("button[id='formselectorCentro:j_id_2x']")

    wait_random_time(1, 3)

    # Click the button
    print("🖱️ Clicking the continue button...")
    await button.click()

    wait_random_time(1, 3)

    # Wait for the page to be ready
    print("🌐 Waiting for the page to be ready...")
    await wait_until_page_is_ready(page, complete=True)

    # Wait for the <a> element with the attribbute title="presencial"
    print("🔍 Looking for the <a> element with the attribute title='Presencial'...")
    presence_link = await page.select("a[title='Presencial']")

    wait_random_time(1, 3)

    # Click the link
    print("🖱️ Clicking the 'Pedir cita' link...")
    await presence_link.click()

    wait_random_time(1, 3)

    # Wait for the page to be ready
    await wait_until_page_is_ready(page, complete=True)

    # Check if there is a popup saying "...Selecciona otra oficina."
    print("🔍 Looking for the popup saying 'Selecciona otra oficina.'...")
    popup = await page.find("Selecciona otra oficina.", best_match=True)
    if popup:
        print("❌ This office is currently without capacity to schedule an appointment")
        return False

    print("✅ This office is currently with capacity to schedule an appointment")

    notification_text = (
        f"❕Office {office_name} is available for scheduling an appointment"
    )

    requests.post(
        f"{NTFY_URL}/{NTFY_TOPIC}",
        data=notification_text.encode(encoding="utf-8"),
        headers={
            "Title": f"Office {office_name} is available for scheduling an appointment",
            "Priority": "default",
            "Tags": "dgt,new",
            "Authorization": f"Bearer {NTFY_TOKEN}",
        },
    )

    return True


async def dgt_availability_checker(officeIds: list[str]):

    print("🚀 Starting browser...")
    browser = await uc.start(
        headless=True,
        no_sandbox=True,  # Run as root
    )

    try:
        for office in officeIds:
            print(f"\n{'='*50}")
            await office_availability_checker(browser, office)
            print(f"{'='*50}\n")
    finally:
        print("🛑 Closing browser...")
        browser.stop()


async def main():
    # Alcorcon - 491
    # Alcala de Henares - 627
    # Madrid - 536

    offices = [586, 588, 628, 539]

    await dgt_availability_checker(offices)


if __name__ == "__main__":
    uc.loop().run_until_complete(main())
