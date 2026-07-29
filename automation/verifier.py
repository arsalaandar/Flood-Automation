import json

TABLE_ID = "TabContainer1_tab_pl_2_grd_Water_Level_Station_hourly"


class Verifier:

    def __init__(self, page):

        self.page = page

        with open("config/stations.json") as f:
            self.stations = json.load(f)

    def selector(self, station):

        info = self.stations["Kashmir"][station]

        ctl = info["ctl"]

        column = info["column"]

        if column == "feet":
            field = "txtfeet"

        elif column == "meter":
            field = "txtmeter"

        else:
            field = "txtmsl"

        return f"#{TABLE_ID}_{ctl}_{field}"

    def verify_station(self, station, value):

        selector = self.selector(station)

        actual = self.page.locator(
            selector
        ).input_value().strip()

        return actual == str(value)

    def verify_all(self, parsed):

        failed = []

        for reading in parsed["readings"]:

            if reading["no_reading"]:
                continue

            ok = self.verify_station(

                reading["gauging_site"],

                reading["value"]

            )

            if not ok:

                failed.append(

                    reading["gauging_site"]

                )

        return failed