import re
import pdfplumber

from jammu.jammu_parser import _normalize_date, _normalize_time, _parse_level_value, _round_to_hour


LABEL_PATTERNS = {
    "feet": re.compile(r'^feet$', re.IGNORECASE),
    "meter": re.compile(r'^meter$', re.IGNORECASE),
    "msl": re.compile(r'^msl\s*\(m\)$', re.IGNORECASE),
    "cusec": re.compile(r'^discharge\s*\(cusecs?\)$', re.IGNORECASE),
}

STATION_NAME_RE = re.compile(
    r'^([A-Za-z ]+?)\s*\n?\(([A-Za-z ]+?)\)$'
)

# Words that can appear in "Word (Word)" shape but are metric labels,
# not station names - must not be mistaken for a station row.
_NON_STATION_WORDS = {
    "discharge", "feet", "meter", "metre", "msl", "gauge",
    "cusec", "cusecs", "description", "present", "level"
}


def _clean(cell):

    if cell is None:
        return ""

    return re.sub(r'\s+', ' ', cell).strip()


def _find_present_level_column(table):
    """
    Finds which column index holds "Present Level" data by locating
    header cells that say "Present" and confirming (via the same
    column in nearby rows) that it's paired with "Level" rather than
    "Trend" or "status" (both of which also use the word "Present").
    """

    candidates = []

    for row_idx, row in enumerate(table):

        for col_idx, cell in enumerate(row):

            text = _clean(cell).lower()

            if not text:
                continue

            if "present" in text and "level" in text:

                # Single cell already says "Present Level" - confirmed
                return col_idx

            if text == "present":

                candidates.append((row_idx, col_idx))

    for row_idx, col_idx in candidates:

        for lookahead in range(1, 4):

            check_idx = row_idx + lookahead

            if check_idx >= len(table):
                break

            cell_text = _clean(table[check_idx][col_idx]).lower() \
                if col_idx < len(table[check_idx]) else ""

            if "level" in cell_text:
                return col_idx

            if "trend" in cell_text or "status" in cell_text:
                break

    return None


def _find_value_in_row_or_below(table, row_idx, col_idx, stop_row):
    """
    Reads the value at col_idx on row_idx. If that cell is empty
    (common when a row wraps across multiple physical table rows),
    scans forward until stop_row looking for the first non-empty
    value in the same column.
    """

    for r in range(row_idx, min(stop_row, len(table))):

        row = table[r]

        if col_idx < len(row):

            value = _clean(row[col_idx])

            if value:
                return value

    return None


def parse_jammu_pdf(pdf_path: str) -> dict:

    result = {
        "region": "Jammu",
        "date": None,
        "time": None,
        "source_header": None,
        "stations": []
    }

    with pdfplumber.open(pdf_path) as pdf:

        page = pdf.pages[0]

        full_text = page.extract_text() or ""

        date_match = re.search(
            r'Date:?\s*\n?\s*([\d/\-]{6,10})', full_text
        )

        if date_match:
            result["date"] = _normalize_date(date_match.group(1))

        time_match = re.search(
            r'Time:?\s*\n?\s*([\d\s:]+\s*[APap]\.?[Mm]\.?)', full_text
        )

        if time_match:
            normalized = _normalize_time(time_match.group(1))
            result["time"] = _round_to_hour(normalized)

        header_lines = full_text.split('\n')[:3]

        result["source_header"] = " | ".join(
            line.strip() for line in header_lines if line.strip()
        )

        tables = page.extract_tables()

        if not tables:
            return result

        table = tables[0]

        present_col = _find_present_level_column(table)

        if present_col is None:

            return result

        # Find every station-name row: a row whose "Name of river"
        # column matches "River\n(Location)" pattern. Column position
        # varies by department's table template (confirmed: col 1-2
        # for some, col 3 for others), so scan the full row rather
        # than assuming a fixed range.
        station_rows = []

        for row_idx, row in enumerate(table):

            for col_idx in range(len(row)):

                cell = _clean(row[col_idx])

                if not cell:
                    continue

                m = STATION_NAME_RE.match(cell.replace('\n', ' '))

                if m:

                    river_candidate = m.group(1).strip()

                    if river_candidate.lower() in _NON_STATION_WORDS:

                        continue

                    station_rows.append(
                        (row_idx, river_candidate, m.group(2).strip())
                    )

                    break

        for i, (row_idx, river, location_tag) in enumerate(station_rows):

            end_row = (
                station_rows[i + 1][0]
                if i + 1 < len(station_rows)
                else len(table)
            )

            readings = {}

            for r in range(row_idx, end_row):

                row = table[r]

                for col_idx, cell in enumerate(row):

                    label_text = _clean(cell)

                    if not label_text:
                        continue

                    for reading_type, pattern in LABEL_PATTERNS.items():

                        if pattern.match(label_text):

                            value = _find_value_in_row_or_below(
                                table, r, present_col, end_row
                            )

                            readings[reading_type] = _parse_level_value(
                                value
                            )

            result["stations"].append({
                "river": river,
                "location_tag": location_tag,
                "readings": readings,
            })

    return result