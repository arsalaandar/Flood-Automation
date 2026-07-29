import os
from datetime import datetime


class Screenshots:

    def __init__(self, page):

        self.page = page

        os.makedirs("screenshots", exist_ok=True)

    def capture(self, name):

        filename = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        path = f"screenshots/{filename}_{name}.png"

        self.page.screenshot(
            path=path,
            full_page=True
        )

        print(f"Screenshot Saved : {path}")

        return path