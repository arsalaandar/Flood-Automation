import re
import openpyxl

from jammu.jammu_parser import _normalize_date, _normalize_time, _parse_level_value, _round_to_hour
from jammu.jammu_pdf_parser import STATION_NAME_RE, _NON_STATION_WORDS, _clean


# Office/division header lines can accidentally match the same
# "Word (Word)" shape as a real station row (e.g. "JAL SHAKTI HYDRAULIC
# DIVISION (RAMBAN)") - these words mark it as an office name, not a
# river, so they're excluded even though the shape matches.
_OFFICE_NAME_WORDS = {"division", "hydraulic", "irrigation", "department"}

# Same idea as jammu_pdf_parser.LABEL_PATTERNS, but as prefix checks since
# Excel cells sometimes carry extra whitespace/newlines pdftotext wouldn't.
_LABEL_TO_READING = [
    (re.compile(r'^(ft|feet)\b', re.IGNORECASE), "feet"),
    (re.compile(r'^(meter|metre)\b', re.IGNORECASE), "meter"),
    (re.compile(r'^msl', re.IGNORECASE), "msl"),
    (re.compile(r'^discharge', re.IGNORECASE), "cusec"),
]


def _reading_type_for_label(label_text):

    for pattern, reading in _LABEL_TO_READING:

        if pattern.match(label_text.strip()):

            return reading

    return None


def parse_jammu_xlsx(xlsx_path: str) -> dict:
    """
    Reads a gauge Excel sheet cell-by-cell via openpyxl instead of via
    text/regex matching - merged cells (the river/location block, the
    "MSL (m)"/"Discharge (cusec)" sub-label column) make text-flattening
    unreliable here, same reasoning as why jammu_pdf_parser.py reads PDF
    tables directly rather than pdftotext output. Finds the "Present
    Level" column by its header text (not a fixed index, since column
    layout varies - some sheets have Evacuation/HFL columns, some don't),
    then reads each metric row's value from that same column.
    """

    result = {
        "region": "Jammu",
        "date": None,
        "time": None,
        "source_header": None,
        "stations": []
    }

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.worksheets[0]

    present_col = None
    header_lines = []
    current_station = None

    for row in ws.iter_rows(values_only=False):

        values = [c.value for c in row]

        joined = " ".join(str(v) for v in values if v is not None)

        if not joined.strip():

            continue

        if "Date:" in joined and result["date"] is None:

            m = re.search(r'([\d/\-]{6,10})', joined)

            if m:

                result["date"] = _normalize_date(m.group(1))

            m = re.search(r'Time:?\s*([\d\s:]+\s*[APap]\.?[Mm]\.?)', joined)

            if m:

                normalized = _normalize_time(m.group(1))

                result["time"] = _round_to_hour(normalized)

        if present_col is None and "present" in joined.lower() and "level" in joined.lower():

            for idx, v in enumerate(values):

                text = _clean(v) if v else ""

                if "present" in text.lower() and "level" in text.lower():

                    present_col = idx

                    break

            header_lines.append(joined)

            continue

        if result["date"] is None:

            header_lines.append(joined)

        # A "River\n(Location)" cell anywhere in the row marks the start
        # of a new station - same pattern jammu_pdf_parser.py matches.
        for v in values:

            if not isinstance(v, str):

                continue

            cell = _clean(v).replace('\n', ' ')

            m = STATION_NAME_RE.match(cell)

            if not m:

                continue

            river_candidate = m.group(1).strip().lower()

            if river_candidate in _NON_STATION_WORDS:

                continue

            if any(word in river_candidate for word in _OFFICE_NAME_WORDS):

                continue

            current_station = {
                "river": m.group(1).strip(),
                "location_tag": m.group(2).strip(),
                "readings": {}
            }

            result["stations"].append(current_station)

            break

        if current_station is None or present_col is None:

            continue

        label_cell = next(
            (str(v) for v in values
             if v and re.match(r'^(Ft|feet|Meter|Metre|MSL|Discharge)', str(v), re.IGNORECASE)),
            None
        )

        if not label_cell:

            continue

        reading_type = _reading_type_for_label(label_cell)

        if not reading_type:

            continue

        present_value = values[present_col] if present_col < len(values) else None

        current_station["readings"][reading_type] = _parse_level_value(
            str(present_value) if present_value is not None else None
        )

    if header_lines:

        result["source_header"] = " | ".join(t for t in header_lines if t.strip())

    return result