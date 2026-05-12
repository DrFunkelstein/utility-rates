import os
import json
import sys
import requests
import pandas as pd
import argparse
from datetime import datetime

# --- CONFIGURATION ---
XLSX_URL = "https://www.pge.com/assets/rates/tariffs/res-inclu-tou-current.xlsx"
JSON_FILE = "pge_rates.json"

def download_xlsx(url, save_path):
    print(f"[Network] Downloading XLSX from: {url}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            f.write(response.content)
        print(f"[Network] Download complete ({len(response.content)} bytes)")
    except Exception as e:
        print(f"[Error] Failed to download XLSX: {e}")
        sys.exit(1)

def clean_val(val):
    if pd.isna(val) or val == "-" or str(val).strip() == "": return 0.0
    s = str(val).replace('$', '').replace(',', '').strip()
    if '(' in s and ')' in s:
        s = "-" + s.replace('(', '').replace(')', '')
    try:
        return float(s)
    except:
        return 0.0

def parse_pge_xlsx(file_path):
    print(f"\n[Excel Scan] Processing workbook...")
    xlsx = pd.ExcelFile(file_path)
    extracted_data = {}
    baseline_credit_found = None

    plan_markers = {
        "E-1 tiered": ["E1,", "Tiered Energy Charges"],
        "E-TOU-C": ["E-TOU-C"],
        "E-TOU-D": ["E-TOU-D"],
        "E-ELEC": ["E-ELEC"],
        "EV2-A": ["EV2"],
        "EV-B": ["EV, Rate B"]
    }

    for sheet_name in xlsx.sheet_names:
        print(f"  > Scanning Sheet: {sheet_name}")
        df = xlsx.parse(sheet_name, header=None)
        
        current_plan_id = None
        current_season = "summer"

        for idx, row in df.iterrows():
            row_list = row.astype(str).tolist()
            row_str = " ".join(row_list).lower()
            
            # 1. Identify Plan Start
            for json_id, markers in plan_markers.items():
                if any(m.lower() in row_str for m in markers):
                    current_plan_id = json_id
                    if current_plan_id not in extracted_data:
                        extracted_data[current_plan_id] = {"summer": {}, "winter": {}}
                    print(f"    [Found] Plan Anchor: {json_id} (Row {idx})")

            if not current_plan_id: continue

            # 2. Update Season Context (Persists across rows)
            if "summer" in row_str: current_season = "summer"
            elif "winter" in row_str: current_season = "winter"

            # 3. Handle E-1 Tiered
            if current_plan_id == "E-1 tiered":
                if "tiered energy charges" in row_str:
                    t1 = clean_val(row.iloc[8])
                    t2 = clean_val(row.iloc[9])
                    if t1 > 0:
                        extracted_data["E-1 tiered"]["summer"] = {"onPeak": t2, "offPeak": t1}
                        extracted_data["E-1 tiered"]["winter"] = {"onPeak": t2, "offPeak": t1}
                        print(f"      -> E-1 Captured: T1={t1}, T2={t2}")
                continue

            # 4. Handle TOU Rows (C, D, EV, ELEC)
            # Column mapping differs by sheet based on your CSV
            # Standard: Col 8=Period, Col 9=Rate | EV/Tech: Col 7=Period, Col 8=Rate
            is_ev_tech = any(x in current_plan_id for x in ["EV", "ELEC"])
            period_col = 7 if is_ev_tech else 8
            rate_col = 8 if is_ev_tech else 9
            
            period_cell = str(row.iloc[period_col]).lower() if len(row) > period_col else ""
            
            if "peak" in period_cell:
                rate = clean_val(row.iloc[rate_col])
                if rate > 0:
                    # Mapping
                    if "peak" in period_cell and "off" not in period_cell and "part" not in period_cell:
                        extracted_data[current_plan_id][current_season]["onPeak"] = rate
                    elif "off-peak" in period_cell:
                        # Map to lowest available slot
                        key = "superOffPeak" if is_ev_tech else "offPeak"
                        extracted_data[current_plan_id][curre
