import re


# Matches the start of each hourly message header, e.g.
# "Gauge @  11:00  PM  25/07/2026" or "Gauge @ 12:00 M/Night 26/07/2026"
_HEADER_START = re.compile(
    r'Gauge\s*@',
    re.IGNORECASE
)


def split_kashmir_messages(text: str):
    """
    Splits a text blob that may contain multiple hourly "Gauge @ ..."
    messages into a list of individual message strings, each starting
    at its own "Gauge @" header. If only one message is present,
    returns a list with that single message.
    """

    starts = [
        m.start()
        for m in _HEADER_START.finditer(text)
    ]

    if not starts:
        return [text]

    messages = []

    for i, start in enumerate(starts):

        end = starts[i + 1] if i + 1 < len(starts) else len(text)

        messages.append(text[start:end].strip())

    return messages


def parse_kashmir_message(text: str):

    result = {
        "region": "Kashmir",
        "date": None,
        "time": None,
        "source": None,
        "readings": [],
        "unparsed_lines": []
    }

    # Extract Date & Time (handles "AM"/"PM" and midday/midnight written
    # as "Noon", "M/Night", or "Midnight")
    header_match = re.search(
        r'@\s*(\d{1,2}:\d{2})\s*(AM|PM|Noon|M/Night|Midnight)\s*(\d{1,2}/\d{1,2}/\d{4})',
        text,
        re.IGNORECASE
    )

    if header_match:

        time_str, ampm, date_str = header_match.groups()

        ampm_norm = ampm.upper()

        if ampm_norm in ("M/NIGHT", "MIDNIGHT"):

            ampm_norm = "AM"

        elif ampm_norm == "NOON":

            ampm_norm = "PM"

        result["time"] = f"{time_str} {ampm_norm}"

        d, m, y = date_str.split("/")

        result["date"] = f"{d.zfill(2)}-{m.zfill(2)}-{y}"

    # Station with numeric value
    numeric_pattern = re.compile(
        r'^\s*\d+[\).]\s*'
        r'(.+?)'
        r'\.?\s*'
        r'\([^)]*\)\s*'
        r'=\s*'
        r'([\d.]+)\s*'
        r'(ft|m|t)(?=\b|Manual)'
        r'\.?\s*'
        r'(\(?Manual\)?)?'
        r'\.?\s*$',
        re.IGNORECASE
    )

    # Station with N/R
    no_reading_pattern = re.compile(
        r'^\s*\d+[\).]\s*'
        r'(.+?)'
        r'\.?\s*'
        r'\([^)]*\)\s*'
        r'=\s*'
        r'(N/?R)'
        r'\s*'
        r'(?:ft|m)?'
        r'\s*'
        r'(\(Manual\))?'
        r'\.?\s*$',
        re.IGNORECASE
    )

    for line in text.splitlines():

        line = line.strip()

        if not line:
            continue

        # Numeric value
        match = numeric_pattern.match(line)

        if match:

            name, value, unit, manual = match.groups()

            name = re.sub(r'\s+', ' ', name).strip().rstrip('.')

            name = re.sub(
                r'Nallahat',
                'Nallah at',
                name,
                flags=re.IGNORECASE
            )

            unit_lower = unit.lower()

            corrected = False

            # "t" is not a valid unit on its own — it's a dropped
            # "f" typo for "ft" (e.g. "16.85t." meant "16.85ft.").
            # Normalize it but flag it so it's never silent.
            if unit_lower == "t":

                unit_lower = "ft"

                corrected = True

            result["readings"].append({

                "gauging_site": name,

                "value": float(value),

                "unit": unit_lower,

                "manual": bool(manual),

                "no_reading": False,

                "typo_corrected": corrected

            })

            continue

        # N/R
        match = no_reading_pattern.match(line)

        if match:

            name, _, manual = match.groups()

            name = re.sub(r'\s+', ' ', name).strip().rstrip('.')

            name = re.sub(
                r'Nallahat',
                'Nallah at',
                name,
                flags=re.IGNORECASE
            )

            result["readings"].append({

                "gauging_site": name,

                "value": None,

                "unit": None,

                "manual": bool(manual),

                "no_reading": True,

                "typo_corrected": False

            })

            continue

        # Line looked like a numbered station entry but matched
        # neither the numeric nor the N/R pattern (e.g. a typo'd
        # unit like "16.85t." instead of "16.85ft."). Flag it
        # instead of silently dropping it.
        if re.match(r'^\s*\d+[\).]', line):

            result["unparsed_lines"].append(line)

    return result