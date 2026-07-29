import json
from automation.waits import Waits

TABLE_ID = "TabContainer1_tab_pl_2_grd_Water_Level_Station_hourly"


class Updater:

    def __init__(self, page):

        self.page = page

        with open("config/settings.json", "r") as f:
            self.settings = json.load(f)

        with open("config/stations.json", "r") as f:
            self.stations = json.load(f)

    def get_selector(self, station):

        info = self.stations["Kashmir"][station]

        ctl = info["ctl"]

        column = info["column"]

        if column == "feet":
            field = "txtfeet"

        elif column == "meter":
            field = "txtmeter"

        elif column == "msl":
            field = "txtmsl"

        else:
            raise Exception(f"Unknown column: {column}")

        return f"#{TABLE_ID}_{ctl}_{field}"

    def fill_box(self, locator, value):

        locator.wait_for(state="visible")

        locator.scroll_into_view_if_needed()

        locator.click(force=True)

        locator.press("Control+A")

        locator.press("Delete")

        self.page.wait_for_timeout(200)

        locator.fill(str(value))

        self.page.wait_for_timeout(300)

        locator.press("Enter")

        self.page.wait_for_timeout(
            self.settings["wait_after_enter"]
        )

    def verify(self, locator, expected):

        actual = locator.input_value().strip()

        return actual == str(expected)

    def update_station(self, station, value):

        selector = self.get_selector(station)

        locator = self.page.locator(selector)

        retries = self.settings["retry_count"]

        for attempt in range(1, retries + 1):

            print(f"\nUpdating {station} (Attempt {attempt})")

            try:

                self.fill_box(locator, value)

                if not Waits.wait_until_value(locator, value):

                    print("Textbox verification failed")

                    continue

                if not self.verify(locator, value):

                    print("Verification failed")

                    continue

                print(f"✓ {station}")

                return True

            except Exception as e:

                print(f"{station}: {e}")

                self.page.wait_for_timeout(1000)

        print(f"✗ {station} failed after {retries} attempts")

        return False

    def update_all(self, parsed):

        successful = []

        failed = []

        skipped = []

        for reading in parsed["readings"]:

            if reading["no_reading"]:

                skipped.append(reading["gauging_site"])

                continue

            station = reading["gauging_site"]

            if station not in self.stations["Kashmir"]:

                print(f"{station} not found in stations.json")

                failed.append(station)

                continue

            ok = self.update_station(
                station,
                reading["value"]
            )

            if ok:

                successful.append(station)

            else:

                failed.append(station)

        print("\n=========================")
        print("Automation Summary")
        print("=========================")

        print(f"Updated : {len(successful)}")
        print(f"Failed  : {len(failed)}")
        print(f"Skipped : {len(skipped)}")

        if failed:

            print("\nFailed Stations:")

            for s in failed:
                print(f" - {s}")

        return successful, failed, skipped