import json
import os


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

    def perform(self):

        with open("config/settings.json", "r") as f:
            settings = json.load(f)

        username, password = self._get_credentials(settings)

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

        self.page.wait_for_load_state("networkidle")