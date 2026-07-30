import json
import sys
import shutil
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv


from automation.browser import Browser
from automation.login import Login
from automation.navigator import Navigator
from automation.screenshots import Screenshots
from automation.logger import logger

from jammu.jammu_parser import parse_jammu_document, resolve_station_name
from jammu.jammu_pdf_parser import parse_jammu_pdf
from jammu.jammu_xlsx_parser import parse_jammu_xlsx
from jammu.jammu_image_parser import parse_jammu_image
from jammu.jammu_updater import JammuUpdater


load_dotenv()

DATA_DIR = Path("data")
SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".txt", ".png", ".jpg", ".jpeg"}


def load_settings():

    with open("config/settings.json", "r") as f:
        return json.load(f)


def get_file_paths():
    """
    Returns the list of files to process this run.

    If filenames are given on the command line, uses those (unchanged
    behavior). Otherwise, auto-scans DATA_DIR for every file with a
    supported extension - no renaming required, drop files in with
    whatever name they actually have (e.g. straight from WhatsApp/email).
    Ignores anything already inside data/processed/, so files moved
    there by a previous successful run are never picked up again.
    """

    if len(sys.argv) > 1:

        return [Path(p) for p in sys.argv[1:]]

    if not DATA_DIR.exists():

        print(
            f"No files given on the command line, and '{DATA_DIR}/' "
            f"doesn't exist.\n\n"
            "Usage: python jammu_main.py <file1> [file2] [file3] ...\n"
            f"Or just create a '{DATA_DIR}/' folder, drop your "
            ".pdf/.xlsx/.txt files in it (any names), and run with no "
            "arguments - every supported file in there gets picked up "
            "automatically."
        )

        sys.exit(1)

    found = sorted(
        p for p in DATA_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and "processed" not in p.parts
    )

    if not found:

        print(
            f"No .pdf/.xlsx/.txt files found directly in '{DATA_DIR}/'.\n"
            "For an image source (e.g. a WhatsApp screenshot), OCR has "
            "not proven reliable for these tables - transcribe its "
            "values into a .txt file (same layout as the other worked "
            "examples) and drop that in instead."
        )

        sys.exit(1)

    print(f"Found {len(found)} file(s) in '{DATA_DIR}/':")

    for p in found:
        print(f"  - {p.name}")

    return found


def archive_processed_files(paths):
    """
    Moves successfully-processed files out of data/ into
    data/processed/<today's date>/, so they don't linger and get
    accidentally reprocessed on the next run - replaces the manual
    rename-then-delete workflow.
    """

    archive_dir = DATA_DIR / "processed" / datetime.now().strftime("%Y-%m-%d")

    archive_dir.mkdir(parents=True, exist_ok=True)

    for path in paths:

        path = Path(path)

        if not path.exists():
            continue

        destination = archive_dir / path.name

        # Avoid clobbering a same-named file from an earlier run today
        if destination.exists():

            stamp = datetime.now().strftime("%H%M%S")

            destination = archive_dir / f"{path.stem}_{stamp}{path.suffix}"

        shutil.move(str(path), str(destination))

        print(f"Archived: {path.name} -> {destination}")


def parse_file(path):

    path = Path(path)

    lower = path.name.lower()

    if lower.endswith(".pdf"):

        return parse_jammu_pdf(path)

    if lower.endswith(".xlsx"):

        return parse_jammu_xlsx(path)

    if lower.endswith(".txt"):

        with open(path, "r", encoding="utf-8") as f:

            return parse_jammu_document(f.read())
    if lower.endswith((".png", ".jpg", ".jpeg")):

        return parse_jammu_image(path)
    

    raise ValueError(
        f"Unsupported file type: {path} (expected .pdf, .xlsx, or .txt)"
    )


def group_files_by_slot(paths):
    """
    Parses every file and groups the resulting stations by their OWN
    (date, time) - does NOT collapse everything into a single slot.

    This replaces an earlier version that merged every file's stations
    into one combined date/time (just using the first file's time and
    warning about the rest). That was silently wrong whenever files
    represented genuinely different hourly readings for the same
    station (e.g. Ramban at 8am, 9am, and 10am) - all of them ended up
    written to the SAME grid row, one overwriting the last, which is
    what showed up as a station being processed over and over with
    conflicting values ("looping").

    Each returned group is a dict shaped like a normal parsed result
    (region/date/time/source_header/stations) but containing only the
    stations that actually belong to that date+time. Groups are
    returned sorted chronologically, so the run processes older
    readings before newer ones.

    Within a single group, if two files somehow report the SAME
    station at the SAME date+time, only the first is kept, and a loud
    warning is printed for the rest - it's ambiguous which is correct.
    """

    slots = {}  # (date, time) -> group dict

    for path in paths:

        logger.info(f"Parsing : {path}")

        parsed = parse_file(path)

        print(f"\n--- Parsed {path} ---")

        print(json.dumps(parsed, indent=2))

        date = parsed.get("date")

        time_ = parsed.get("time")

        if not date or not time_:

            print(
                f"\n WARNING: {path} is missing a date or time - "
                "skipping this file entirely (can't safely assign it "
                "to a grid slot)."
            )

            logger.warning(f"Skipping {path}: missing date/time")

            continue

        key = (date, time_)

        if key not in slots:

            slots[key] = {
                "region": "Jammu",
                "date": date,
                "time": time_,
                "source_header": [],
                "stations": [],
                "source_files": [],
            }

        group = slots[key]

        file_header = parsed.get("source_header")

        seen_station_names = {
            resolve_station_name(s, None) for s in group["stations"]
        }

        for station in parsed.get("stations", []):

            resolved_name = resolve_station_name(station, file_header)

            station["location_tag"] = resolved_name

            if resolved_name in seen_station_names:

                print(
                    f"\n WARNING: {resolved_name} already has a reading "
                    f"for {date} {time_} from an earlier file in this "
                    f"run - ignoring the one from {path} (ambiguous "
                    f"which is correct; check both files manually if "
                    f"unsure)."
                )

                logger.warning(
                    f"Duplicate station in same slot: {resolved_name} "
                    f"at {date} {time_}, from {path} - ignored"
                )

                continue

            group["stations"].append(station)

            seen_station_names.add(resolved_name)

        if file_header:

            group["source_header"].append(f"[{path}] {file_header}")

        group["source_files"].append(path)

    groups = list(slots.values())

    for group in groups:

        group["source_header"] = " || ".join(group["source_header"])

    def _sort_key(group):

        d = datetime.strptime(group["date"], "%d-%m-%Y")

        t = datetime.strptime(group["time"], "%I:%M %p")

        return (d, t)

    groups.sort(key=_sort_key)

    return groups


def click_update_and_confirm(page):
    """
    Clicks Update for the currently-filled slot and waits for the site's
    own success confirmation dialog. Returns True if the site said
    "success", False otherwise (still returns after clicking either way -
    caller decides what a non-confirmation means for that group).
    """

    update_confirmed = {"value": False}

    def _handle_update_dialog(dialog):
        # This site uses a partial AJAX postback (no full page
        # navigation) even on success, so navigation-detection was never
        # reliable - the dialog's own wording is the real signal.
        print(f"\n[Update dialog] type={dialog.type!r} message={dialog.message!r}")

        logger.info(f"Update dialog - type={dialog.type} message={dialog.message}")

        if "success" in dialog.message.lower():
            update_confirmed["value"] = True

        dialog.accept()

    page.once("dialog", _handle_update_dialog)

    page.get_by_role("button", name="Update").click()

    page.wait_for_timeout(2000)

    return update_confirmed["value"]


def main():

    settings = load_settings()

    browser = Browser(
        headless=settings["headless"]
    )

    page = browser.start()

    screenshots = Screenshots(page)

    all_failed_files = set()

    try:

        paths = get_file_paths()

        logger.info(f"Jammu Automation Started : {paths}")

        groups = group_files_by_slot(paths)

        if not groups:

            print(
                "\n ABORTING: No files had a usable date/time - "
                "nothing to process.\n"
            )

            logger.error("Aborting: zero valid (date, time) groups")

            return

        print(f"\n=== Found {len(groups)} distinct date/time slot(s) ===")

        for g in groups:
            print(f"  - {g['date']} {g['time']}: "
                  f"{len(g['stations'])} station(s), "
                  f"{len(g['source_files'])} file(s)")

        Login(page).perform()

        logger.info("Login Successful")

        navigator = Navigator(page)

        updater = JammuUpdater(page)

        any_group_failed = False

        for i, group in enumerate(groups):

            print(f"\n\n=== Slot {i + 1}/{len(groups)}: "
                  f"{group['date']} {group['time']} ===")

            print(json.dumps(
                {k: v for k, v in group.items() if k != "source_files"},
                indent=2
            ))

            if not group["stations"]:

                print("No stations in this slot after de-duplication - skipping.")

                continue

            if i == 0:

                navigator.open_jammu(group)

            else:

                navigator.goto_jammu_slot(group)

            logger.info(f"Navigated to slot {group['date']} {group['time']}")

            # location_tag was already resolved per-file in
            # group_files_by_slot() - pass source_header=None so
            # update_all()'s internal resolve_station_name() call is a
            # no-op and just falls through to the already-correct value.
            update_input = dict(group)

            update_input["source_header"] = None

            successful, failed, skipped_no_reading, skipped_no_mapping = (
                updater.update_all(update_input)
            )

            logger.info(f"Slot {group['date']} {group['time']} - "
                        f"Updated: {len(successful)}, Failed: {len(failed)}, "
                        f"Skipped (no reading): {len(skipped_no_reading)}, "
                        f"Skipped (no mapping): {len(skipped_no_mapping)}")

            slot_failed = bool(failed)

            if slot_failed:

                any_group_failed = True

                all_failed_files.update(group["source_files"])

                if settings["take_screenshot"]:
                    screenshots.capture(
                        f"jammu_fields_failed_{group['date']}_{group['time']}"
                        .replace(":", "").replace(" ", "_")
                    )

                logger.error(f"Failed fields in this slot: {failed}")

                print(
                    "\nSome fields in this slot failed — review before "
                    "trusting this slot's submission.\n"
                )

            if settings["dry_run"]:

                print(f"\nDRY RUN — not clicking Update for this slot.\n")

                logger.info(f"Dry run - slot {group['date']} {group['time']}")

                continue

            confirmed = click_update_and_confirm(page)

            if confirmed:

                print(f"\n Site confirmed slot {group['date']} "
                      f"{group['time']} updated successfully.")

                logger.info(f"Slot {group['date']} {group['time']} - "
                            "site confirmed success")

            else:

                print(
                    f"\n No success confirmation seen from the site for "
                    f"slot {group['date']} {group['time']} - check the "
                    f"dialog message above and verify on the site."
                )

                logger.warning(
                    f"Slot {group['date']} {group['time']} - no success "
                    "confirmation seen"
                )

                any_group_failed = True

                all_failed_files.update(group["source_files"])

        logger.info("Jammu Automation Finished")

        if settings["dry_run"]:

            print("\nDRY RUN — files left in place in data/ "
                  "(nothing was actually submitted).")

        elif any_group_failed:

            print(
                f"\n{len(all_failed_files)} file(s) involved a failure — "
                "leaving them in data/ so you can retry without "
                "re-locating them. Fix/retry, then they'll be archived "
                "on a clean run."
            )

        else:

            archive_processed_files(paths)

    except Exception as e:

        logger.exception(e)

        screenshots.capture("jammu_unexpected_error")

    finally:

        browser.close()


if __name__ == "__main__":

    main()