"""
Jammu image parser - Free API based extraction (OCR.space)
----------------------------------------------------------
Uses the free OCR.space API to read the river gauge table from 
WhatsApp screenshots. 

This completely eliminates the coordinate/cropping issues caused by 
varying image sizes, aspect ratios, and WhatsApp chat backgrounds. 
"""

import base64
import json
import re
import os
import requests
from dotenv import load_dotenv

from jammu.jammu_parser import _normalize_date, _normalize_time, _parse_level_value, _round_to_hour

load_dotenv()


# ---------------------------------------------------------------------------
# API CONFIGURATION
# ---------------------------------------------------------------------------
# Get your FREE API key from: https://ocr.space/ocrapi
API_URL = "https://api.ocr.space/parse/image"
API_KEY = os.environ.get("OCR_API_KEY", "")  # <-- REPLACE THIS WITH YOUR FREE OCR.space API KEY


def _call_ocr_space_api(image_path):
    """Send image to free OCR.space API and get text back."""
    if API_KEY == "":
        print(" WARNING: You haven't set your free OCR.space API key.")
        print("   Get one instantly from: https://ocr.space/ocrapi")
        print("   Then paste it into jammu_image_parser.py")
        return None

    try:
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        
        payload = {
            "base64Image": f"data:image/jpeg;base64,{base64_image}",
            "language": "eng",
            "isTable": True,       # Optimizes for table structures
            "scale": True,         # Upscales internally for better accuracy
            "OCREngine": 2         # Engine 2 is best for screenshots/text
        }
        headers = {
            "apikey": API_KEY
        }

        print("  [api] Sending image to free OCR.space API...")
        response = requests.post(API_URL, data=payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        
        if result.get("IsErroredOnProcessing"):
            print(f" API Error: {result.get('ErrorMessage')}")
            return None
            
        # Extract parsed text
        parsed_results = result.get("ParsedResults", [])
        if parsed_results:
            return parsed_results[0].get("ParsedText", "")
            
        return None

    except requests.exceptions.RequestException as e:
        print(f" API Request Failed: {e}")
        return None


def _extract_values_from_text(text):
    """Use regex to find Date, Time, Meter, MSL, and Discharge in the raw text."""
    data = {
        "date": None,
        "time": None,
        "meter": None,
        "msl": None,
        "cusec": None
    }

    if not text:
        return data

    # 1. Extract Date (e.g., 28-07-2026 or 28/07/2026)
    date_match = re.search(r'(\d{1,2}[-/]\d{1,2}[-/]\d{4})', text)
    if date_match:
        data["date"] = _normalize_date(date_match.group(1))

    # 2. Extract Time (e.g., 06:20:AM or 06:20 AM)
    time_match = re.search(r'(\d{1,2}:\d{2}\s*:?\s*[APap][Mm])', text)
    if time_match:
        raw_time = time_match.group(1)
        hour_match = re.match(r'(\d{1,2}):', raw_time)
        if hour_match and int(hour_match.group(1)) <= 12:
            normalized = _normalize_time(raw_time)
            data["time"] = _round_to_hour(normalized)

    # Helper to find the number after a keyword
    def find_value_after_keyword(keyword):
        # Looks for keyword followed by optional chars and then a number
        pattern = rf'{keyword}[^\d]*?(\d+\.?\d*)'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    # 3. Extract Meter Value
    meter_val = find_value_after_keyword("Meter")
    if meter_val:
        data["meter"] = meter_val

    # 4. Extract MSL Value
    msl_val = find_value_after_keyword("MSL")
    if msl_val:
        data["msl"] = msl_val

    # 5. Extract Discharge Value
    # FIXED: Look specifically for 'cusec' to avoid grabbing the date (28)
    disc_match = re.search(r'cusec\)?\s*:?\s*(\d[\d,]*)', text, re.IGNORECASE)
    if not disc_match:
        # Fallback: look for "Discharge" followed by a large number (>100)
        disc_match = re.search(r'Discharge[^\d]*?(\d{3,}[\d,]*)', text, re.IGNORECASE)
    if disc_match:
        data["cusec"] = disc_match.group(1).replace(',', '')

    return data


def parse_jammu_image(image_path: str) -> dict:
    """Parse image using Free OCR API."""
    
    result = {
        "region": "Jammu",
        "date": None,
        "time": None,
        "source_header": "Ramban image (JAL SHAKTI HYDRAULIC DIVISION)",
        "stations": [],
    }

    # Call the API
    raw_text = _call_ocr_space_api(image_path)

    if not raw_text:
        print(" WARNING: API returned no text. Returning empty result.")
        return result

    # Extract values using Regex
    extracted = _extract_values_from_text(raw_text)

    result["date"] = extracted["date"]
    result["time"] = extracted["time"]

    # Build readings dictionary
    readings = {}
    
    if extracted["meter"]:
        readings["meter"] = _parse_level_value(extracted["meter"])
        
    if extracted["msl"]:
        readings["msl"] = _parse_level_value(extracted["msl"])
        
    if extracted["cusec"]:
        readings["cusec"] = _parse_level_value(extracted["cusec"])

    result["stations"].append({
        "river": "Chenab",
        "location_tag": "Ramban",
        "readings": readings,
    })

    print(f"  [api] Extracted readings: {readings}")
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python jammu_image_parser.py <image_path>")
        sys.exit(1)
    
    parsed = parse_jammu_image(sys.argv[1])
    print(json.dumps(parsed, indent=2))