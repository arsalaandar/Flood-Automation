import json
from dotenv import load_dotenv
from automation.browser import Browser
from automation.login import Login
from automation.navigator import Navigator
from automation.updater import Updater
from automation.verifier import Verifier
from automation.submit import Submit
from automation.screenshots import Screenshots
from automation.logger import logger

from datetime import datetime

from parser.kashmir_parser import (
    parse_kashmir_message,
    split_kashmir_messages
)
load_dotenv()

def sort_key(parsed):

    return datetime.strptime(
        f"{parsed['date']} {parsed['time']}",
        "%d-%m-%Y %I:%M %p"
    )


def load_settings():

    with open("config/settings.json", "r") as f:
        return json.load(f)


def load_whatsapp():

    with open("data/whatsapp.txt", "r", encoding="utf-8") as f:
        return f.read()


def retry_failed(updater, parsed, failed):

    print("\nRetrying Failed Stations\n")

    still_failed = []

    readings = {
        r["gauging_site"]: r
        for r in parsed["readings"]
    }

    for station in failed:

        reading = readings[station]

        ok = updater.update_station(
            station,
            reading["value"]
        )

        if not ok:
            still_failed.append(station)

    return still_failed


def process_message(page, settings, screenshots, navigator, submit, parsed, label, is_first):

    print(f"\n=========================================")
    print(f"Processing : {label}")
    print(f"=========================================")

    print(parsed)

    corrected = [
        r for r in parsed["readings"]
        if r.get("typo_corrected")
    ]

    if corrected:

        print("\n WARNING: Auto-corrected a likely typo:\n")

        for r in corrected:
            print(
                f"  - {r['gauging_site']}: "
                f"read as '{r['value']}{r['unit']}' "
                f"(unit typo corrected to 'ft')"
            )

        logger.error(
            f"[{label}] Typo-corrected readings : {corrected}"
        )

        print(
            "\nDouble-check these against the source message "
            "before trusting the submission.\n"
        )

    if parsed["unparsed_lines"]:

        print("\n WARNING: Some lines could not be parsed:\n")

        for line in parsed["unparsed_lines"]:
            print(f"  - {line}")

        logger.error(
            f"[{label}] Unparsed lines detected : "
            f"{parsed['unparsed_lines']}"
        )

        print(
            "\nThese stations will NOT be updated. "
            "Check for typos in the source message.\n"
        )

    if is_first:

        navigator.open_kashmir(parsed)

        logger.info(f"[{label}] Full Navigation Successful")

    else:

        navigator.goto_kashmir_slot(parsed)

        logger.info(f"[{label}] Slot Change Successful")

    updater = Updater(page)

    verifier = Verifier(page)

    success, failed, skipped = updater.update_all(parsed)

    logger.info(f"[{label}] Updated : {len(success)}")

    logger.info(f"[{label}] Failed : {len(failed)}")

    logger.info(f"[{label}] Skipped : {len(skipped)}")

    print("\nRunning Verification Pass\n")

    verification_failed = verifier.verify_all(parsed)

    if verification_failed:

        print("\nVerification Failed\n")

        verification_failed = retry_failed(

            updater,

            parsed,

            verification_failed

        )

    if verification_failed:

        print("\nStill Failed\n")

        for station in verification_failed:

            print(station)

        if settings["take_screenshot"]:

            screenshots.capture(f"verification_failed_{label}")

        logger.error(

            f"[{label}] Verification Failed : {verification_failed}"

        )

        return False

    print("\nAll Stations Verified\n")

    logger.info(f"[{label}] Verification Successful")

    if settings["dry_run"]:

        print("\nDRY RUN ENABLED")

        logger.info(f"[{label}] Dry Run Finished")

        return True

    submitted = submit.click_update()

    if not submitted:

        logger.error(
            f"[{label}] Update click did not get a confirmation "
            "dialog - treating as failed."
        )

        if settings["take_screenshot"]:

            screenshots.capture(f"submit_no_dialog_{label}")

        return False

    logger.info(f"[{label}] Update Submitted")

    return True


def main():

    settings = load_settings()

    browser = Browser(
        headless=settings["headless"]
    )

    page = browser.start()

    screenshots = Screenshots(page)

    try:

        logger.info("Automation Started")

        raw_text = load_whatsapp()

        messages = split_kashmir_messages(raw_text)

        parsed_messages = [
            parse_kashmir_message(m) for m in messages
        ]

        # Any message we couldn't extract a date/time for is unsafe
        # to place into a time slot automatically. Stop rather than
        # guess.
        undated = [
            p for p in parsed_messages if not p["date"] or not p["time"]
        ]

        if undated:

            print(
                "\n ABORTING: Could not detect date/time for "
                f"{len(undated)} message(s). Check the source text.\n"
            )

            logger.error(
                f"Aborting: {len(undated)} message(s) with no "
                "detected date/time"
            )

            return

        parsed_messages.sort(key=sort_key)

        # Date changes are now handled per-message by Navigator.set_date,
        # so multiple dates are fine — just note it for visibility.
        dates = {p["date"] for p in parsed_messages}

        if len(dates) > 1:

            print(
                f"\nNote: messages span multiple dates {dates}. "
                "The date field will be updated automatically "
                "between messages as needed.\n"
            )

            logger.info(
                f"Multiple dates in this run : {dates}"
            )

        print(f"\nFound {len(parsed_messages)} message(s) to process:\n")

        for p in parsed_messages:
            print(f"  - {p['date']} {p['time']}")

        Login(page).perform()

        logger.info("Login Successful")

        navigator = Navigator(page)

        submit = Submit(page)

        results = {}

        for parsed in parsed_messages:

            label = f"{parsed['date']} {parsed['time']}"

            try:

                ok = process_message(
                    page, settings, screenshots, navigator, submit,
                    parsed, label, is_first=(not navigator.opened)
                )

                results[label] = "OK" if ok else "VERIFICATION FAILED"

            except Exception as e:

                logger.exception(f"[{label}] {e}")

                screenshots.capture(
                    f"unexpected_error_{label.replace(':', '')}"
                )

                results[label] = f"ERROR: {e}"

        print("\n=========================================")
        print("Overall Run Summary")
        print("=========================================")

        for label, status in results.items():
            print(f"  {label} : {status}")

        logger.info(f"Run Summary : {results}")

        logger.info("Automation Finished")

    except Exception as e:

        logger.exception(e)

        screenshots.capture("unexpected_error")

    finally:

        browser.close()


if __name__ == "__main__":

    main()