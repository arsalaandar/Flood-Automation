import json
from automation.waits import Waits
from jammu.jammu_parser import resolve_station_name

TABLE_ID = "TabContainer1_tab_pl_2_grd_Water_Level_Station_hourly"

GAUGING_SITE_HEADER = "gauging site"

READING_TO_FIELD = {
    "feet": "txtfeet",
    "meter": "txtmeter",
    "msl": "txtmsl",
    "cusec": "txtcusec"
}

# Real manual workflow (confirmed): fill feet/meter, press Enter ONCE
# - this triggers the site's own auto-calculation of MSL from the
# level value. MSL is therefore NEVER typed in manually — doing so
# fights the site's auto-calc and both values end up wrong. Cusec is
# filled last, directly, with no Enter press needed.
LEVEL_TYPES = ["feet", "meter"]


class JammuUpdater:

    def __init__(self, page):

        self.page = page

        with open("config/settings.json", "r") as f:
            self.settings = json.load(f)

        with open("config/stations.json", "r") as f:
            self.stations = json.load(f)["Jammu"]

        # Cached per JammuUpdater instance (i.e. per date/time slot the
        # grid is currently showing), not across the whole run - the
        # header column position is the same for every row within one
        # grid render, so there's no reason to re-scan it per station.
        self._gauging_site_col = None

    def _find_gauging_site_column(self, header_row):
        """
        Finds which column index is "Gauging Site" by reading the actual
        header cells - NOT assumed from a fixed position, since the grid
        can have extra columns depending on the site/deployment.
        """

        if self._gauging_site_col is not None:

            return self._gauging_site_col

        header_cells = header_row.locator("th, td")

        count = header_cells.count()

        for i in range(count):

            text = header_cells.nth(i).inner_text().strip().lower()

            if GAUGING_SITE_HEADER in text:

                self._gauging_site_col = i

                return i

        raise Exception(
            "Could not find a 'Gauging Site' column in the Hourly Water "
            "Level grid header - the site's layout may have changed."
        )

    def _find_row_for_station(self, station):
        """
        Finds a station's actual grid row BY ITS DISPLAYED NAME in the
        "Gauging Site" column, instead of a hardcoded ctl-id.
        """

        table = self.page.locator(f'#{TABLE_ID}')

        rows = table.locator("tr")

        row_count = rows.count()

        if row_count == 0:

            return None

        col_idx = self._find_gauging_site_column(rows.nth(0))

        for r in range(1, row_count):

            row = rows.nth(r)

            cells = row.locator("td")

            if col_idx >= cells.count():

                continue

            cell_text = cells.nth(col_idx).inner_text().strip()

            if cell_text.lower() == station.lower():

                return row

        return None

    def get_field_locator(self, station, reading_type):
        """Returns the specific input Locator for a station's reading
        type, found by locating that station's actual row first (see
        _find_row_for_station) rather than building a ctl-based id."""

        row = self._find_row_for_station(station)

        if row is None:

            return None

        field = READING_TO_FIELD[reading_type]

        return row.locator(f'input[id$="{field}"]')

    def unlock_if_disabled(self, locator):
        """Removes the 'disabled' attribute via JS if the field is
        currently disabled. Safe no-op if it's already enabled."""

        locator.evaluate(
            """(el) => {
                if (el && el.disabled) {
                    el.removeAttribute('disabled');
                    el.classList.remove('aspNetDisabled');
                }
            }"""
        )

    def fill_box(self, locator, value, press_enter):

        locator.wait_for(state="visible")

        locator.scroll_into_view_if_needed()

        try:
            # Try standard fill first (with a short timeout to fail fast)
            locator.click(force=True)
            locator.press("Control+A")
            locator.press("Delete")
            self.page.wait_for_timeout(200)
            locator.fill(str(value), timeout=5000)
        except Exception:
            # If standard fill times out because it's disabled, force it with JS
            print("  ⚠ Standard fill failed (likely disabled). Forcing value via JavaScript...")
            locator.evaluate(
                """(el, val) => {
                    el.removeAttribute('disabled');
                    el.classList.remove('aspNetDisabled');
                    el.value = val;
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""",
                str(value)
            )

        self.page.wait_for_timeout(300)

        if press_enter:

            locator.press("Enter")

            self.page.wait_for_timeout(
                self.settings["wait_after_enter"]
            )

    def verify(self, locator, expected):

        actual = locator.input_value().strip()

        return actual == str(expected)

    def _format_value(self, reading_type, value):
        """_parse_level_value (jammu_parser.py) always returns a float, even
        for whole-number cusec readings - "15456" becomes 15456.0. Typing
        "15456.0" into the discharge box doesn't match what the site itself
        holds/displays once you move on (it stores the plain integer,
        "15456"), so verify() kept failing every retry even though the fill
        itself worked - a format mismatch, not a real fill failure.
        Feet/meter genuinely do have decimals (14.985, 29.8) so those are
        left untouched."""

        if reading_type == "cusec" and isinstance(value, float) and value.is_integer():
            return int(value)

        return value

    def update_field(self, station, reading_type, value, press_enter):

        value = self._format_value(reading_type, value)

        locator = self.get_field_locator(station, reading_type)

        if locator is None:

            print(
                f"✗ Could not find a grid row for '{station}' (checked "
                f"the 'Gauging Site' column) - skipping {reading_type}"
            )

            return False

        self.unlock_if_disabled(locator)

        retries = self.settings["retry_count"]

        for attempt in range(1, retries + 1):

            print(
                f"\nUpdating {station} ({reading_type}) "
                f"(Attempt {attempt})"
            )

            try:

                self.fill_box(locator, value, press_enter)

                if not Waits.wait_until_value(locator, value):

                    print("Textbox verification failed")

                    continue

                if not self.verify(locator, value):

                    print("Verification failed")

                    continue

                print(f"✓ {station} ({reading_type})")

                return True

            except Exception as e:

                print(f"{station} ({reading_type}): {e}")

                self.page.wait_for_timeout(1000)

        print(
            f"✗ {station} ({reading_type}) failed "
            f"after {retries} attempts"
        )

        return False

    def check_auto_calculated_msl(self, station, expected_msl):
        """
        MSL is never typed manually - the site auto-calculates it
        after the level field's Enter press. This just reads back
        whatever the site computed and compares it to the source
        document's MSL value, purely for visibility. Does not fill
        or retry, since we don't control the auto-calc's result.
        """

        locator = self.get_field_locator(station, "msl")

        if locator is None:

            print(
                f"Could not find MSL field for {station} (no matching "
                f"'Gauging Site' row found)"
            )

            return None

        try:

            actual = locator.input_value().strip()

        except Exception as e:

            print(f"Could not read auto-calculated MSL for "
                  f"{station}: {e}")

            return None

        if expected_msl is not None:

            matches = actual == str(expected_msl)

            status = "matches" if matches else "DIFFERS FROM"

            print(
                f"  Auto-calculated MSL for {station}: {actual} "
                f"({status} document value {expected_msl})"
            )

        return actual

    def final_verification_pass(self, filled_fields, successful, failed):
        """
        Re-checks every field that was successfully filled during this
        run, one more time, right before Update is clicked.
        """

        if not filled_fields:
            return

        print("\n--- Final verification pass (pre-Update) ---")

        for station, reading_type, expected in filled_fields:

            locator = self.get_field_locator(station, reading_type)

            if locator is None:
                label = f"{station} ({reading_type})"
                print(f"✗ {label}: row no longer found during re-check")
                if label in successful:
                    successful.remove(label)
                failed.append(label)
                continue

            try:
                current = locator.input_value().strip()
            except Exception as e:
                print(f"Could not re-read {station} ({reading_type}): {e}")
                continue

            if self.verify(locator, expected):
                print(f"✓ {station} ({reading_type}) still correct ({current})")
                continue

            print(
                f"⚠ {station} ({reading_type}) REVERTED - expected "
                f"{expected}, found {current!r}. Re-filling."
            )

            ok = self.update_field(
                station, reading_type, expected, press_enter=False
            )

            label = f"{station} ({reading_type})"

            if ok:
                print(f"✓ {label} re-filled successfully")
                if label not in successful:
                    successful.append(label)
            else:
                print(f"✗ {label} could not be re-filled - needs manual check")
                if label not in failed:
                    failed.append(label)

    def update_all(self, parsed):
        """
        Two-pass fill order, per station (confirmed to matter - see below):

        PASS 1: for every station, fill its level field (feet OR meter)
        and press Enter. This is the action that triggers the site's own
        MSL auto-calculation postback.

        PASS 2 (only after ALL of pass 1 has settled): for every station,
        fill its remaining fields.
        """

        successful = []

        failed = []

        skipped_no_reading = []

        skipped_no_mapping = []

        filled_fields = []

        # --- Resolve + validate every station up front -------------------

        station_infos = []

        for station_data in parsed["stations"]:

            station = resolve_station_name(
                station_data,
                parsed.get("source_header")
            )

            if station not in self.stations:

                print(f"{station} not found in stations.json['Jammu']")

                skipped_no_mapping.append(station)

                continue

            station_infos.append({
                "name": station,
                "readings": station_data["readings"],
                "level_type": None,
                "fill": self.stations[station].get("fill"),
            })

        # --- PASS 1: level fields (feet/meter), one gauge at a time ------

        for info in station_infos:

            readings = info["readings"]

            if info["fill"]:

                level_type = info["fill"][0]

            else:

                level_type = next(
                    (t for t in LEVEL_TYPES if t in readings), None
                )

            info["level_type"] = level_type

            if not level_type:
                continue

            value = readings.get(level_type)

            label = f"{info['name']} ({level_type})"

            if value is None:

                skipped_no_reading.append(label)

                continue

            ok = self.update_field(
                info["name"], level_type, value, press_enter=True
            )

            (successful if ok else failed).append(label)

            if ok:
                filled_fields.append(
                    (info["name"], level_type, self._format_value(level_type, value))
                )

        between_pass_ms = self.settings.get("between_pass_settle_ms", 1500)
        self.page.wait_for_timeout(between_pass_ms)

        # --- PASS 2: remaining fields --------------------------------

        for info in station_infos:

            readings = info["readings"]

            station = info["name"]

            level_type = info["level_type"]

            if info["fill"]:

                for reading_type in info["fill"][1:]:

                    if reading_type not in readings:

                        continue

                    value = readings[reading_type]

                    label = f"{station} ({reading_type})"

                    if value is None:

                        skipped_no_reading.append(label)

                        continue

                    ok = self.update_field(
                        station, reading_type, value, press_enter=False
                    )

                    (successful if ok else failed).append(label)

                    if ok:
                        filled_fields.append(
                            (station, reading_type, self._format_value(reading_type, value))
                        )

                continue

            # --- Fallback: original behavior for stations without an
            # explicit "fill" list (unchanged from before) ---

            if "msl" in readings:

                if level_type == "feet":

                    self.check_auto_calculated_msl(station, readings["msl"])

                elif level_type == "meter":

                    value = readings["msl"]

                    label = f"{station} (msl)"

                    if value is None:

                        skipped_no_reading.append(label)

                    else:

                        ok = self.update_field(
                            station, "msl", value, press_enter=False
                        )

                        (successful if ok else failed).append(label)

                        if ok:
                            filled_fields.append(
                                (station, "msl", self._format_value("msl", value))
                            )

            if "cusec" in readings:

                value = readings["cusec"]

                label = f"{station} (cusec)"

                if value is None:

                    skipped_no_reading.append(label)

                else:

                    ok = self.update_field(
                        station, "cusec", value, press_enter=False
                    )

                    (successful if ok else failed).append(label)

                    if ok:
                        filled_fields.append(
                            (station, "cusec", self._format_value("cusec", value))
                        )

        settle_ms = self.settings.get("final_verification_settle_ms", 2000)
        self.page.wait_for_timeout(settle_ms)

        self.final_verification_pass(filled_fields, successful, failed)

        print("\n=========================")
        print("Jammu Automation Summary")
        print("=========================")

        print(f"Updated : {len(successful)}")
        print(f"Failed  : {len(failed)}")
        print(f"Skipped (no reading) : {len(skipped_no_reading)}")
        print(f"Skipped (no mapping) : {len(skipped_no_mapping)}")

        if failed:

            print("\nFailed Fields:")

            for s in failed:
                print(f" - {s}")

        if skipped_no_mapping:

            print("\nWARNING: not in stations.json, skipped entirely:")

            for s in skipped_no_mapping:
                print(f" - {s}")

            print(
                "Add these to stations.json['Jammu'] if they should be "
                "filled (no ctl-id needed anymore - rows are now found "
                "by their 'Gauging Site' text at runtime)."
            )

        return successful, failed, skipped_no_reading, skipped_no_mapping