import pandas as pd
import re

def parse_rainfall_excel(file_path):
    try:
        # Try reading with xlrd (for .xls)
        df = pd.read_excel(file_path, header=None, engine='xlrd')
    except Exception:
        # Fallback to openpyxl (for .xlsx)
        df = pd.read_excel(file_path, header=None, engine='openpyxl')
        
    date_str = None
    for i in range(min(10, len(df))):
        row_data = df.iloc[i].dropna().tolist()
        row_str = ' '.join(str(x) for x in row_data)
        match = re.search(r'(\d{2}-\d{2}-\d{4})', row_str)
        if match:
            date_str = match.group(1)
            break
            
    if not date_str:
        return None, []
        
    # date_str could be DD-MM-YYYY or MM-DD-YYYY depending on how the
    # source sheet formats it - confirmed real case: this file uses
    # MM-DD-YYYY ("07-29-2026" = July 29), which the old
    # split('-')[0] assumption read as day=07 (actually the month).
    # Since a real day can exceed 12 but a real month can't, whichever
    # segment is >12 must be the day; if both are <=12 (ambiguous), we
    # default to MM-DD-YYYY since that's this file's confirmed format.
    parts = date_str.split('-')
    p0, p1 = int(parts[0]), int(parts[1])
    if p0 > 12:
        target_day = p0
    elif p1 > 12:
        target_day = p1
    else:
        target_day = p1
    
    header_row_idx = None
    for i in range(len(df)):
        if str(df.iloc[i, 0]).strip() == 'MET.SUB/DISTRICT/STATION':
            header_row_idx = i
            break
            
    if header_row_idx is None:
        return None, []
        
    target_col = None
    for j in range(1, 32):
        try:
            if str(int(df.iloc[header_row_idx, j])).strip() == str(target_day):
                target_col = j
                break
        except (ValueError, TypeError):
            pass
            
    if target_col is None:
        return None, []
        
    stations = []
    current_district = ""
    for i in range(header_row_idx + 1, len(df)):
        cell0 = str(df.iloc[i, 0]).strip()
        if cell0.startswith('DISTRICT:'):
            current_district = cell0.replace('DISTRICT:', '').strip()
        elif (
            cell0
            and cell0.lower() != 'nan'
            and not cell0.startswith('---')
            and not cell0.startswith('MET.')
            and cell0 != '0'
        ):
            value = df.iloc[i, target_col]
            
            # If data is missing or marked with '*', pass None to leave the app blank
            if pd.isna(value) or str(value).strip() == '*':
                val_str = None
            else:
                val_str = str(value).strip()
                
            stations.append({
                "station": cell0,
                "district": current_district,
                "value": val_str
            })
            
    return date_str, stations