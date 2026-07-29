import json
import re
import sys
from pathlib import Path

from automation.browser import Browser
from automation.login import Login
from automation.logger import logger
from rainfall.rainfall_parser import parse_rainfall_excel
from dotenv import load_dotenv

load_dotenv()

# Explicit, human-reviewed aliases for cases where the Excel source name
# and the app's actual station name genuinely differ beyond just
# formatting (dropped qualifier words like AWS/ARG/KVK, or a fully
# different short name). Deliberately NOT auto-stripped by a generic
# rule (e.g. "always drop trailing AWS/ARG") - a blind rule like that
# risks silently matching the WRONG station if any two real stations on
# the list differ only by such a suffix. Add new confirmed pairs here
# as they're found, rather than guessing a pattern.
#
# Keys and values should be the RAW excel/app names (any case/spacing -
# normalize_name() is applied to both before comparison, so you don't
# need to pre-clean these).
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
    """
    Normalizes a station name for comparison - handles the SAFE,
    unambiguous formatting differences confirmed between the Excel
    source and the app's display:
      - case ("Udhampur IAF" vs "UDHAMPUR(IAF)")
      - parentheses ("UDHAMPUR(IAF)" vs "Udhampur IAF")
      - underscores vs spaces ("BARAMULLA_KVK" vs "BARAMULLA KVK")
      - doubled/irregular whitespace ("SAMBA  AWS" vs "Samba AWS" -
        confirmed real case: the Excel literally has a double space)

    Does NOT strip qualifier words like AWS/ARG/KVK - that's handled
    separately via STATION_ALIASES, deliberately, since auto-stripping
    those is not always safe (see STATION_ALIASES comment above).
    """

    name = name.upper()

    name = re.sub(r'[()_\-]', ' ', name)

    name = re.sub(r'\s+', ' ', name).strip()

    return name


_NORMALIZED_ALIASES = {
    normalize_name(excel_name): normalize_name(app_name)
    for excel_name, app_name in STATION_ALIASES.items()
}


def resolve_expected_app_name(excel_station_name: str) -> str:
    """Returns the normalized name we expect to find on the app's page
    for a given raw Excel station name - applying a known alias first
    if one exists, otherwise just normalizing formatting."""

    normalized = normalize_name(excel_station_name)

    return _NORMALIZED_ALIASES.get(normalized, normalized)


def main():
    # Find the excel file in the data/ directory
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
        
    # Convert list to a dictionary for fast lookups: { 'KUKERNAG': '0.0', ... }
    excel_data = {s["station"].strip().upper(): s["value"] for s in stations}

    # Map each excel station to (normalized_expected_app_name, value) -
    # applying aliasing/formatting normalization up front, so the actual
    # matching loop just compares clean, consistent strings instead of
    # raw excel text against raw app text.
    resolved_stations = [
        (resolve_expected_app_name(excel_name), excel_name, value)
        for excel_name, value in excel_data.items()
    ]

    # Sort by normalized-name length (longest first) to prevent a short
    # name like "TRAL" from matching inside a longer one first.
    resolved_stations = sorted(resolved_stations, key=lambda x: len(x[0]), reverse=True)

    print(f"Found {len(excel_data)} stations in Excel for date {target_date}.")
    
    with open("config/settings.json", "r") as f:
        settings = json.load(f)
        
    browser = Browser(headless=settings["headless"])
    page = browser.start()
    
    try:
        Login(page).perform()
        print("Login Successful")
        
        page.goto("https://jkiofs.in/jkiofs/rainfallinput.aspx")
        page.wait_for_load_state("networkidle")
        print("Navigated to Rainfall Input page.")
        
        # Wait for the table rows to load
        page.wait_for_selector("input[placeholder='Rainfall Value']", timeout=15000)
        
        # Find all Rainfall input boxes currently on the web page
        input_boxes = page.locator("input[placeholder='Rainfall Value']")
        web_input_count = input_boxes.count()
        print(f"Found {web_input_count} input fields on the web page. Matching with Excel...")
        
        filled_count = 0
        skipped_count = 0
        blank_count = 0
        
        print("\n--- Debugging row matching (first 5 rows) ---")
        
        for i in range(web_input_count):
            input_box = input_boxes.nth(i)
            
            # The station name is displayed inside a readonly <input>
            # (placeholder="Station Name"), NOT as plain text - confirmed
            # via inspecting the live page. row.textContent never picks up
            # an <input>'s value, which is why every row came back empty
            # before. Walk up from the Rainfall Value box until we reach
            # an ancestor that actually contains the station-name input
            # as a descendant, then read ITS value directly - robust to
            # whatever the row's actual container element/nesting is,
            # rather than guessing tr/[role="row"]/div picks the right
            # level in one shot.
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

            # Print the first 5 rows so we can see exactly what the website returns
            if i < 5:
                print(f"Row {i} text: '{row_text[:100]}'") # Print first 100 chars

            matched_excel_name = None
            matched_value = None

            # Check if any station from our Excel data (after alias
            # resolution + formatting normalization) matches this row's
            # (also normalized) station name.
            for normalized_expected, excel_station, excel_val in resolved_stations:
                if normalized_expected and normalized_expected in row_text:
                    matched_excel_name = excel_station
                    matched_value = excel_val
                    break # Stop searching once we found the match for this row

            matched_station = matched_excel_name

            if matched_station:
                if matched_value is None:
                    # In Excel, but has no data. Leave it blank in the app.
                    input_box.click()
                    input_box.fill("")
                    blank_count += 1
                else:
                    # Match found! Fill the value.
                    input_box.click()
                    input_box.fill(matched_value)
                    filled_count += 1
            else:
                # On the website, but NOT in the Excel file. Skip entirely.
                skipped_count += 1
                
        print("--- End debugging ---\n")
                
        print(f"Matching Complete:")
        print(f"  Filled: {filled_count}")
        print(f"  Left Blank (no Excel data): {blank_count}")
        print(f"  Skipped (not in Excel): {skipped_count}")
        
        # Click Submit and handle the popup dialog
        def handle_dialog(dialog):
            print(f"Dialog message: {dialog.message}")
            dialog.accept()
            
        page.once("dialog", handle_dialog)
        page.get_by_role("button", name="Submit").click()
        print("\n✓ Submit clicked. Waiting for confirmation...")
        
        page.wait_for_timeout(3000)
        print("✓ Rainfall data uploaded successfully.")
        
    except Exception as e:
        print(f"Error: {e}")
        logger.exception(e)
    finally:
        browser.close()

if __name__ == "__main__":
    main()