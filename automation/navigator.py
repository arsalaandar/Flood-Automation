from datetime import datetime
import json
import time


# Same table the field selectors in jammu_updater.py are built against.
# Used here only to read back what date/time the grid is actually
# showing right now, not to fill anything.
GRID_TABLE_ID = "TabContainer1_tab_pl_2_grd_Water_Level_Station_hourly"


class Navigator:

    def __init__(self, page):

        self.page = page

        self.opened = False

        with open("config/settings.json") as f:
            self.settings = json.load(f)

    def _grid_row_texts(self):
        """Returns the visible text of every row in the Hourly Water Level
        grid, so callers can check what date/time it's actually showing -
        the picker fields updating doesn't mean the grid underneath has
        caught up yet."""

        rows = self.page.locator(f'table[id*="{GRID_TABLE_ID}"] tr')

        count = rows.count()

        texts = []

        for i in range(count):

            try:

                texts.append(rows.nth(i).inner_text())

            except Exception:

                # A row can detach mid-read if the grid reloads while
                # we're polling it - just skip that row this pass.
                continue

        return texts

    def _wait_for_grid_to_show(self, must_contain, timeout_ms=15000, poll_ms=500):
        """
        Polls the grid's own rows until one contains every string in
        must_contain (e.g. the target date, or the target date AND time
        together), instead of guessing a fixed wait. How long the grid
        actually takes to reflect a date/time change varies run to run -
        polling for the real displayed content sidesteps that rather than
        picking a number and hoping. Returns True once matched, False if
        timeout_ms elapses first (caller decides whether that's fatal).
        """

        deadline = time.monotonic() + (timeout_ms / 1000)

        while time.monotonic() < deadline:

            for row_text in self._grid_row_texts():

                if all(needle in row_text for needle in must_contain):

                    return True

            self.page.wait_for_timeout(poll_ms)

        return False

    def set_date(self, target_date):
        """
        Sets the #txtDate field to target_date (format DD-MM-YYYY).
        Clicking the field opens a calendar popup, so we dismiss it
        with Escape rather than clicking through it, then type the
        value directly and blur to trigger the onchange postback.
        Skips entirely if the field already shows the target date.
        """

        locator = self.page.locator("#txtDate")

        locator.wait_for(state="visible")

        current = locator.input_value().strip()

        if current == target_date:

            return

        locator.click()

        self.page.wait_for_timeout(300)

        # Dismiss the calendar popup without selecting a date from it
        self.page.keyboard.press("Escape")

        self.page.wait_for_timeout(200)

        locator.click()

        locator.press("Control+A")

        locator.press("Delete")

        self.page.wait_for_timeout(200)

        locator.type(target_date, delay=50)

        self.page.wait_for_timeout(200)

        # Dismiss any popup that reappeared from typing, then blur
        # to fire the onchange postback
        self.page.keyboard.press("Escape")

        locator.press("Tab")

        self.page.wait_for_timeout(
            self.settings.get("wait_after_date", 4000)
        )

        # Confirm it actually took, rather than assuming silently
        actual = locator.input_value().strip()

        if actual != target_date:

            raise Exception(
                f"Date field shows '{actual}' after attempting to "
                f"set '{target_date}' — calendar postback may not "
                f"have applied correctly."
            )

    def _ensure_date_committed(self, target_date, attempts=2):
        """
        Jammu-only. The picker field (#txtDate) updating is NOT the same
        thing as the grid underneath actually reloading against it - that
        was the previous bug (this method used to only re-check #txtDate,
        which can show the right date while the grid rows still show the
        old one). Now polls the grid's own rows for target_date directly.
        How long that takes varies run to run, so this polls for the real
        content instead of waiting a fixed duration. If a delayed re-render
        resets the picker field itself, this re-applies set_date() and
        tries again, rather than silently moving on with a stale grid.
        """

        for attempt in range(1, attempts + 1):

            actual = self.page.locator("#txtDate").input_value().strip()

            if actual != target_date:

                if attempt < attempts:

                    self.set_date(target_date)

                    continue

                raise Exception(
                    f"Date field shows '{actual}', not '{target_date}', "
                    f"after {attempts} attempt(s)."
                )

            if self._wait_for_grid_to_show([target_date]):

                return

            if attempt < attempts:

                self.set_date(target_date)

        raise Exception(
            f"Grid never showed a row for date '{target_date}' after "
            f"{attempts} attempt(s) - refusing to proceed to time "
            f"selection, since doing so risks filling the wrong row."
        )

    def _ensure_time_committed(self, target_date, target_time_24, attempts=2):
        """
        Jammu-only. Same idea as _ensure_date_committed but for the full
        date+time slot: polls the grid for a row containing BOTH, since
        the grid can (and did) lag behind the #ddlTime dropdown the same
        way it lagged behind #txtDate. Only once this returns is it safe
        to start filling fields.
        """

        for attempt in range(1, attempts + 1):

            if self._wait_for_grid_to_show([target_date, target_time_24]):

                return

            if attempt < attempts:

                self.set_time(
                    datetime.strptime(target_time_24, "%H:%M:00")
                    .strftime("%I:%M %p")
                )

        raise Exception(
            f"Grid never showed a row for '{target_date}' at "
            f"'{target_time_24}' after {attempts} attempt(s) - refusing "
            f"to fill fields against a slot that may be wrong."
        )

    def set_time(self, target_time):
        """
        Sets the #ddlTime dropdown to target_time (format 'HH:MM AM/PM').
        Skips entirely if the dropdown already shows the target time.
        """

        t24 = datetime.strptime(
            target_time,
            "%I:%M %p"
        ).strftime("%H:%M:00")

        locator = self.page.locator("#ddlTime")

        current = locator.input_value()

        if current == t24:

            return

        locator.select_option(t24)

        self.page.wait_for_timeout(
            self.settings["wait_after_time"]
        )

    def goto_kashmir_slot(self, parsed):
        """
        Changes date/time within an already-open Kashmir Observed Data
        page. Use this for every message AFTER the first in a
        multi-message run — re-running the full open_kashmir()
        navigation (re-clicking Flood Forecast / Observed Data / region)
        on an already-navigated page is unreliable, since the page's
        DOM state has changed since the first navigation. The "Hourly
        Water Level" tab itself DOES need re-clicking every time though
        — it resets/collapses after each update submission.
        """

        self.page.locator(
            '#__tab_TabContainer1_tab_pl_2'
        ).click()

        self.page.wait_for_timeout(2000)

        if parsed["date"]:

            self.set_date(parsed["date"])

        if parsed["time"]:

            self.set_time(parsed["time"])

    def goto_jammu_slot(self, parsed):
        """Jammu equivalent of goto_kashmir_slot - see its docstring."""

        self.page.locator(
            '#__tab_TabContainer1_tab_pl_2'
        ).click()

        self.page.wait_for_timeout(2000)

        if parsed.get("date"):

            self.set_date(parsed["date"])

            self._ensure_date_committed(parsed["date"])

        if parsed.get("time"):

            self.set_time(parsed["time"])

            # Confirmed via manual recording: the grid only actually
            # reloads to reflect the newly-selected time if the tab is
            # re-clicked AFTER set_time() too, not just after set_date().
            # Without this, the date/time picker shows the right values
            # but the grid rows underneath stay on whatever slot was
            # already loaded - which is exactly the bug (data got typed
            # into the right fields, but the wrong date/time's row).
            self.page.locator(
                '#__tab_TabContainer1_tab_pl_2'
            ).click()

            self.page.wait_for_timeout(2000)

            t24 = datetime.strptime(
                parsed["time"], "%I:%M %p"
            ).strftime("%H:%M:00")

            self._ensure_time_committed(parsed["date"], t24)

    def open_jammu(self, parsed):

        self.page.get_by_role(
            "link",
            name="Flood Forecast",
            exact=True
        ).click()

        self.page.wait_for_timeout(3000)

        self.page.get_by_role(
            "link",
            name="Observed Data"
        ).click()

        self.page.wait_for_timeout(3000)

        self.page.locator(
            "#rgName"
        ).select_option("Jammu")

        self.page.wait_for_timeout(
            self.settings["wait_after_region"]
        )

        if parsed.get("date"):

            self.set_date(parsed["date"])

            self._ensure_date_committed(parsed["date"])

        self.page.locator(
            '#__tab_TabContainer1_tab_pl_2'
        ).click()

        self.page.wait_for_timeout(2000)

        if parsed.get("time"):

            self.set_time(parsed["time"])

            # Same fix as goto_jammu_slot - see the comment there. The
            # grid doesn't reflect the newly-selected time until the tab
            # is clicked again after set_time(), not just after set_date().
            self.page.locator(
                '#__tab_TabContainer1_tab_pl_2'
            ).click()

            self.page.wait_for_timeout(2000)

            t24 = datetime.strptime(
                parsed["time"], "%I:%M %p"
            ).strftime("%H:%M:00")

            self._ensure_time_committed(parsed["date"], t24)

        self.opened = True

    def open_kashmir(self, parsed):

        self.page.get_by_role(
            "link",
            name="Flood Forecast",
            exact=True
        ).click()

        self.page.wait_for_timeout(3000)

        self.page.get_by_role(
            "link",
            name="Observed Data"
        ).click()

        self.page.wait_for_timeout(3000)

        self.page.locator(
            "#rgName"
        ).select_option("Kashmir")

        self.page.wait_for_timeout(
            self.settings["wait_after_region"]
        )

        if parsed["date"]:

            self.set_date(parsed["date"])

        self.page.locator(
            '#__tab_TabContainer1_tab_pl_2'
        ).click()

        self.page.wait_for_timeout(2000)

        if parsed["time"]:

            self.set_time(parsed["time"])

        self.opened = True