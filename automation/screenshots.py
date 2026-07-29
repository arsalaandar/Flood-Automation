import os
from datetime import datetime


class Screenshots:

    def __init__(self, page):

        self.page = page

        os.makedirs("screenshots", exist_ok=True)

    def capture(self, name):

        try:
            filename = datetime.now().strftime(
                "%Y%m%d_%H%M%S"
            )

            path = f"screenshots/{filename}_{name}.png"

            # Added timeout=5000 so it doesn't hang for 60 seconds on cloud servers
            self.page.screenshot(
                path=path,
                full_page=True,
                timeout=5000
            )

            print(f"Screenshot Saved : {path}")

            return path
            
        except Exception as e:
            # If taking a screenshot fails, print a warning but DO NOT crash the script
            print(f"⚠ Could not take screenshot: {e}")
            return None
