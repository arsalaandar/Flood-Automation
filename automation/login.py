import json
import os
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


LOGIN_MAX_ATTEMPTS = 3
LOGIN_LOAD_TIMEOUT_MS = 90000  # confirmed: the dashboard is sometimes genuinely slow to load


class Login:

    def __init__(self, page):

        self.page = page

    def _get_credentials(self, settings):
        """
        Username/password come from environment variables first (this
        is what GitHub Actions Secrets inject as JKIOFS_USER/JKIOFS_PASS)
        so settings.json never needs to hold real credentials and is
        safe to commit to the repo. Falls back to settings.json's
        "username"/"password" keys if the env vars aren't set, so local
        runs keep working exactly as before for anyone who still has
        real values there.
        """

        username = os.environ.get("JKIOFS_USER") or settings.get("username")

        password = os.environ.get("JKIOFS_PASS") or settings.get("password")

        if not username or not password:

            raise Exception(
                "No login credentials found. Set JKIOFS_USER and "
                "JKIOFS_PASS as environment variables (or GitHub "
                "Secrets), or add \"username\"/\"password\" to "
                "config/settings.json for local use."
            )

        return username, password

    def _attempt_login(self, username, password, settings):

        self.page.goto(settings["url"])

        self.page.get_by_role(
            "textbox",
            name="User Name"
        ).fill(username)

        self.page.get_by_role(
            "textbox",
            name="Password"
        ).fill(password)

        self.page.locator(
            "#ddlloginType"
        ).select_option(
            settings["login_type"]
        )

        self.page.get_by_role(
            "button",
            name="Login"
        ).click()

        # "networkidle" was removed here - it waits for ZERO network
        # activity for 500ms straight, which is unreliable on sites
        # with any ongoing background polling and was confirmed to
        # cause a real 60s timeout/crash even though login itself had
        # actually succeeded. "load" only waits for the page's own
        # resources to finish, which is what we actually care about.
        # Timeout raised to 90s since the dashboard is confirmed to be
        # genuinely slow sometimes, not just a flaky wait condition.
        self.page.wait_for_load_state("load", timeout=LOGIN_LOAD_TIMEOUT_MS)

    def perform(self):

        with open("config/settings.json", "r") as f:
            settings = json.load(f)

        # Credentials are checked once, up front, outside the retry loop -
        # a missing/wrong credential should fail immediately and clearly,
        # not waste time retrying something that can never succeed.
        username, password = self._get_credentials(settings)

        last_error = None

        for attempt in range(1, LOGIN_MAX_ATTEMPTS + 1):

            try:

                self._attempt_login(username, password, settings)

                return  # success

            except PlaywrightTimeoutError as e:

                last_error = e

                print(
                    f"Login attempt {attempt}/{LOGIN_MAX_ATTEMPTS} timed "
                    f"out (site was slow to load) - "
                    f"{'retrying' if attempt < LOGIN_MAX_ATTEMPTS else 'giving up'}."
                )

                if attempt < LOGIN_MAX_ATTEMPTS:

                    time.sleep(3)

        raise last_error