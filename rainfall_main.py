import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from automation.browser import Browser
from automation.login import Login
from automation.logger import logger
from automation.screenshots import Screenshots
from rainfall.rainfall_parser import parse_rainfall_excel


STATION_ALIASES = {
    "SRINAGAR AGRO AWS": "SRINAGAR AGRO",
    "BAKORE ARG": "BAKORE",
    "BARAMULLA KVK AWS": "BARAMULLA_KVK",
    "LARNOO ARG": "LARNOO",
    "TRAL ARG": "TRAL",
    "BARARRIMARG AWS": "BARARRI",
    "SANGAM AWS": "SANGAM",
}

def normalize_name(name: str) -> str:
    name = name.upper()
    name = re.sub(r'[()_\-]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

_NORMALIZED_ALIASES = {
    normalize_name(excel_name): normalize_name(app_name)
    for excel_name, app_name in STATION_ALIASES.items()
}

def resolve_expected_app_name(excel_station_name: str) -> str:
    normalized = normalize_name(excel_station_name)
    return _NORMALIZED_ALIASES.get(normalized, normalized)

def main():
    data_dir = Path("data")
    excel_files = list(data_dir.glob("*.xls")) + list(data_dir.glob("*.xlsx"))
    
    if not excel_files:
        print("No Excel files found in data/")
        sys.exit(1)
        
    file_path = excel_files[0]
    print(f"Parsing {file_path}...")
    
    target_date, stations = parse_rainfall_excel(file_path)
    if not stations:
        print("No stations found in Excel.")
        sys.exit(1)
        
    excel_data = {s["station"].strip().upper(): s["value"] for s in stations}

    resolved_stations = [
        (resolve_expected_app_name(excel_name), excel_name, value)
        for excel_name, value in excel_data.items()
    ]

    resolved_stations = sorted(resolved_stations, key=lambda x: len(x[0]), reverse=True)

    print(f"Found {len(excel_data)} stations in Excel for date {target_date}.")
    
    with open("config/settings.json", "r") as f:
        settings = json.load(f)
        
    browser = Browser(headless=settings["headless"])
    page = browser.start()

    screenshots = Screenshots(page)
    
    try:
        Login(page).perform()
        print("Login Successful")
        
        # The site requires visiting FloodDashboard.aspx first - it sets
        # some session/viewstate server-side that rainfallinput.aspx
        # depends on. Jumping straight to rainfallinput.aspx via goto()
        # (the old behavior) gets rejected (ERR_ABORTED) and bounces
        # back to Home_Page.aspx, which is why the input fields never
        # appeared - confirmed via the URL logging above. Matches the
        # same click-through Kashmir/Jammu's Navigator already does.
        page.get_by_role(
            "link",
            name="Flood Forecast",
            exact=True
        ).click()

        page.wait_for_timeout(3000)

        print(f"On Flood Dashboard: {page.url}")

        # Confirmed workflow: once FloodDashboard.aspx has fully loaded,
        # swapping its URL to rainfallinput.aspx (rather than a fresh
        # goto from Home_Page.aspx) is what actually works.
        rainfall_url = page.url.replace(
            "FloodDashboard.aspx", "rainfallinput.aspx"
        )

        try:
            page.goto(rainfall_url, wait_until="domcontentloaded")
        except Exception as nav_error:
            print(f"Navigation warning (continuing anyway): {nav_error}")
            logger.warning(f"Navigation warning during goto: {nav_error}")

        page.wait_for_timeout(3000)
        print("Navigated to Rainfall Input page.")

        print(f"Current URL after navigation: {page.url}")
        
        page.wait_for_selector("input[placeholder='Rainfall Value']", timeout=45000)
        
        input_boxes = page.locator("input[placeholder='Rainfall Value']")
        web_input_count = input_boxes.count()
        print(f"Found {web_input_count} input fields on the web page. Matching with Excel...")
        
        filled_count = 0
        skipped_count = 0
        blank_count = 0
        
        print("\n--- Debugging row matching (first 5 rows) ---")
        
        for i in range(web_input_count):
            input_box = input_boxes.nth(i)
            
            row_text = input_box.evaluate("""el => {
                let node = el;
                for (let i = 0; i < 8 && node; i++) {
                    node = node.parentElement;
                    if (!node) break;
                    let stationInput = node.querySelector('input[placeholder="Station Name"]');
                    if (stationInput) {
                        return stationInput.value || '';
                    }
                }
                return '';
            }""")
            row_text = normalize_name(row_text)

            if i < 5:
                print(f"Row {i} text: '{row_text[:100]}'")

            matched_excel_name = None
            matched_value = None

            for normalized_expected, excel_station, excel_val in resolved_stations:
                if normalized_expected and normalized_expected in row_text:
                    matched_excel_name = excel_station
                    matched_value = excel_val
                    break

            matched_station = matched_excel_name

            if matched_station:
                if matched_value is None:
                    input_box.click()
                    input_box.fill("")
                    blank_count += 1
                else:
                    try:
                        float_val = float(matched_value)
                        if float_val.is_integer():
                            matched_value = str(int(float_val))
                    except ValueError:
                        pass
                        
                    input_box.click()
                    input_box.fill(matched_value)
                    filled_count += 1
            else:
                skipped_count += 1
                
        print("--- End debugging ---\n")
                
        print(f"Matching Complete:")
        print(f"  Filled: {filled_count}")
        print(f"  Left Blank (no Excel data): {blank_count}")
        print(f"  Skipped (not in Excel): {skipped_count}")
        
        def handle_dialog(dialog):
            print(f"Dialog message: {dialog.message}")
            dialog.accept()
            
        page.once("dialog", handle_dialog)
        page.get_by_role("button", name="Submit").click()
        print("\n Submit clicked. Waiting for confirmation...")
        
        page.wait_for_timeout(3000)
        print(" Rainfall data uploaded successfully.")
        
    except Exception as e:
        print(f"Error: {e}")
        logger.exception(e)
        try:
            screenshots.capture("rainfall_error")
            print(f"Current URL at time of error: {page.url}")
        except Exception as screenshot_error:
            print(f"Could not capture screenshot: {screenshot_error}")
    finally:
        browser.close()

if __name__ == "__main__":
    main()