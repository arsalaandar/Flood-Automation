"""
Single-pass version of auto_fetcher.py, for use in a scheduled CI
environment (GitHub Actions) instead of a persistent background
process. The schedule itself replaces the `while True: sleep(60)`
loop - every workflow run is one check.

Reuses check_email_and_download() and run_automation() from
auto_fetcher.py unchanged, so there's no duplicated logic to keep in
sync between the two entry points.
"""

from pathlib import Path

from auto_fetcher import check_email_and_download, run_automation, DATA_DIR


if __name__ == "__main__":

    DATA_DIR.mkdir(exist_ok=True)

    print("Single-pass check starting...")

    downloaded = check_email_and_download()

    if downloaded:

        run_automation(downloaded)

    else:

        print("Nothing new this run.")