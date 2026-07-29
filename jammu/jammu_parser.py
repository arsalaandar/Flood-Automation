import re


def _normalize_date(raw):
    raw = raw.replace(' ', '')
    m = re.match(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', raw)
    if not m:
        return None
    d, mo, y = m.groups()
    return f"{d.zfill(2)}-{mo.zfill(2)}-{y}"


def _normalize_time(raw):
    raw = re.sub(r'\s+', '', raw)
    raw = raw.replace('.', '')
    raw = raw.replace(':PM', ' PM').replace(':AM', ' AM')
    m = re.match(r'(\d{1,2}):?(\d{2})?\s*(AM|PM)', raw, re.IGNORECASE)
    if not m:
        return raw
    hh, mm, ampm = m.groups()
    mm = mm or "00"
    # Zero-pad the hour - without this, "8 A.M" (Akhnoor's format) and
    # "08:00 AM" (Ramban/Udhampur's format) normalize to DIFFERENT
    # strings ("8:00 AM" vs "08:00 AM") for the exact same time, which
    # breaks any grouping/matching done on this value downstream (e.g.
    # jammu_main.py's group_files_by_slot treating them as two separate
    # slots instead of one).
    return f"{hh.zfill(2)}:{mm} {ampm.upper()}"


def _parse_level_value(raw):
    """Handles decimal feet ('14.985'), the apostrophe-as-decimal-point
    notation these forms use ('29'8"' means 29.8, NOT 29 feet 8 inches),
    and no-reading markers ('-', '----'). Some departments' PDFs use
    curly/smart quotes (’ U+2019, ” U+201D) instead of straight ones
    ('/") for the feet/inch marks - Akhnoor's confirmed to do this
    ("29'2\"" vs "29\u20192\u201d") - so both are accepted here rather
    than only the straight ASCII versions."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw or raw.startswith('-'):
        return None
    apostrophe_match = re.match(r"^(\d+)['\u2019](\d+)", raw)
    if apostrophe_match:
        whole, decimal = apostrophe_match.groups()
        return float(f"{whole}.{decimal}")
    try:
        return float(raw.replace(',', ''))
    except ValueError:
        return None


STATION_BLOCK_RE = re.compile(
    r'(\d+\.?0?\s+)?([A-Za-z ]+?)\s*\(([A-Za-z ]+?)\)\s*\n?\s*Gauge',
    re.IGNORECASE
)


def parse_jammu_document(text: str) -> dict:

    result = {
        "region": "Jammu",
        "date": None,
        "time": None,
        "source_header": None,
        "stations": []
    }

    date_match = re.search(r'Date:?\s*\n?\s*([\d/\-]{6,10})', text)

    if date_match:
        result["date"] = _normalize_date(date_match.group(1))

    time_match = re.search(
        r'Time:?\s*\n?\s*([\d\s:]+\s*[APap]\.?[Mm]\.?)', text
    )

    if time_match:
        result["time"] = _normalize_time(time_match.group(1))

    header_match = re.search(r'^(.*?)Date:', text, re.DOTALL)

    if header_match:
        header_lines = [
            line.strip()
            for line in header_match.group(1).split('\n')
            if line.strip()
        ]
        result["source_header"] = " | ".join(header_lines)

    blocks = list(STATION_BLOCK_RE.finditer(text))

    if not blocks:
        return result

    for i, m in enumerate(blocks):

        river = m.group(2).strip()

        location_tag = m.group(3).strip()

        start = m.start()

        end = blocks[i + 1].start() if i + 1 < len(blocks) else len(text)

        chunk = text[start:end]

        readings = {}

        # Each regex below intentionally captures only the FIRST value
        # after its label - that's the Present Level. Alert/Danger/
        # Evacuation/HFL values that follow are ignored on purpose.
        if re.search(r'\bFt\b|\bfeet\b', chunk, re.IGNORECASE):

            val_m = re.search(
                r'(?:Ft|feet)\s*\n?\s*(\d+\'\d+"?|[\d.]+|-{1,})',
                chunk,
                re.IGNORECASE
            )

            if val_m:
                readings["feet"] = _parse_level_value(val_m.group(1))

        if re.search(r'\bMeter\b(?!\s*\()', chunk, re.IGNORECASE):

            val_m = re.search(
                r'Meter\s*\n?\s*(\d+\'\d+"?|[\d.]+|-{1,})',
                chunk,
                re.IGNORECASE
            )

            if val_m:
                readings["meter"] = _parse_level_value(val_m.group(1))

        msl_m = re.search(
            r'MSL\s*\(m\)\s*\n?\s*(\d+\'\d+"?|[\d.]+|-{1,})',
            chunk,
            re.IGNORECASE
        )

        if msl_m:
            readings["msl"] = _parse_level_value(msl_m.group(1))

        disc_m = re.search(
            r'Discharge\s*\(cusecs?\)\s*\n?\s*([\d,]+|-{1,})',
            chunk,
            re.IGNORECASE
        )

        if disc_m:
            readings["cusec"] = _parse_level_value(disc_m.group(1))

        result["stations"].append({
            "river": river,
            "location_tag": location_tag,
            "readings": readings,
        })

    return result


# Some agencies' documents mislabel the station in the (Location) tag next
# to the river name (e.g. Akhnoor's PDF says "Chenab (Jammu)" even though
# the document title says "FCD ( Akhnoor )"). When source_header contains
# one of these keys, override the station identification instead of
# trusting location_tag.
SOURCE_HEADER_OVERRIDES = {
    "Akhnoor": "Akhnoor",
    "ID Udhampur": "Udhampur",
    "RAMBAN": "Ramban",
    "Reasi": "Reasi",
    "FCD Jammu": None,  # ambiguous - fall back to location_tag/river name
}


def resolve_station_name(station: dict, source_header: str) -> str:
    """Best-effort resolution of which stations.json['Jammu'] key a parsed
    station block corresponds to. Falls back to the location_tag if no
    header override applies."""

    if source_header:

        for key, mapped in SOURCE_HEADER_OVERRIDES.items():

            if key.lower() in source_header.lower() and mapped:
                return mapped

    # No usable header override - trust location_tag, but nallahs/chowks
    # are identified by their river name instead since their location_tag
    # is just the administrative circle (e.g. "Jammu").
    if (
        "nallah" in station["river"].lower()
        or "chowk" in station["river"].lower()
    ):
        return station["river"]

    return station["location_tag"]