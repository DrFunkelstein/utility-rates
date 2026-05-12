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
        # User-agent header often required by PG&E to prevent block
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            f.write(response.content)
        print(f"[Network] Download complete ({len(response.content)} bytes)")
    except Exception as e:
        print(f"[Error] Failed to download XLSX: {e}")
        sys.exit(1)

def parse_pge_xlsx(file_path):
    print(f"\n[Excel Scan] Processing data...")
    
    # Load the spreadsheet
    # We skip rows to get to the actual data table (usually starts around row 3-5)
    df = pd.read_excel(file_path)
    
    # Standardize column names for searching
    df.columns = [str(col).strip() for col in df.columns]
    
    # Logic to find the "Total Bundled" column
    total_col = None
    for col in df.columns:
        if "Total" in col and "Bundled" in col:
            total_col = col
            break
    
    if not total_col:
        # Fallback if the column header is different
        total_col = df.columns[-1] 
        print(f"  [Note] Guessed total column: {total_col}")

    extracted_data = {}

    # Define the Plan Mapping (JSON ID : SpreadSheet Name)
    plan_map = {
        "E-1 tiered": "E-1",
        "E-TOU-C": "E-TOU-C",
        "E-TOU-D": "E-TOU-D",
        "E-ELEC": "E-ELEC",
        "EV2-A": "EV2-A",
        "EV-B": "EV-B"
    }

    for json_id, excel_name in plan_map.items():
        # Filter rows for this specific plan
        plan_rows = df[df.iloc[:, 0].astype(str).str.contains(excel_name, na=False, case=False)]
        
        if plan_rows.empty:
            print(f"  [Warn] No data found for {excel_name}")
            continue

        extracted_data[json_id] = {"summer": {}, "winter": {}}

        for _, row in plan_rows.iterrows():
            season_str = str(row.iloc[1]).lower() # Usually Col B
            period_str = str(row.iloc[2]).lower() # Usually Col C
            rate = float(row[total_col])

            season = "summer" if "summer" in season_str else "winter"
            
            # Map TOU Periods to JSON Bins
            if "peak" in period_str and "off" not in period_str and "part" not in period_str:
                extracted_data[json_id][season]["onPeak"] = rate
            elif "part" in period_str or "off-peak" in period_str:
                # For 2-bin plans, 'Off' goes to offPeak. 
                # For 3-bin plans, 'Part' goes to offPeak.
                extracted_data[json_id][season]["offPeak"] = rate
            elif "super" in period_str:
                extracted_data[json_id][season]["superOffPeak"] = rate
            
            # Special Handling for E-1 (Tiered)
            if json_id == "E-1 tiered":
                if "tier 1" in period_str: extracted_data[json_id][season]["offPeak"] = rate
                if "tier 2" in period_str: extracted_data[json_id][season]["onPeak"] = rate

    return extracted_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run: print("\n!!! DRY RUN MODE: No files will be modified !!!")

    tmp_xlsx = "pge_rates.xlsx"
    download_xlsx(XLSX_URL, tmp_xlsx)
    
    try:
        new_data = parse_pge_xlsx(tmp_xlsx)
    except Exception as e:
        print(f"[Error] Parsing failed: {e}")
        if os.path.exists(tmp_xlsx): os.remove(tmp_xlsx)
        return

    if not os.path.exists(JSON_FILE):
        print(f"[Error] {JSON_FILE} not found.")
        return

    with open(JSON_FILE, 'r') as f:
        current_json = json.load(f)

    print("\n[Comparison Ledger: JSON vs Excel]")
    updated = False
    
    for plan, seasons in new_data.items():
        if plan not in current_json["plans"]: continue
        for season in ["summer", "winter"]:
            for b_type in ["onPeak", "offPeak", "superOffPeak"]:
                rate = seasons[season].get(b_type, 0)
                if rate == 0: continue
                
                current_val = current_json["plans"][plan][season].get(b_type, 0)
                diff = abs(rate - current_val)
                
                status = "[MATCH]" if diff < 0.00001 else "[CHANGE DETECTED]"
                print(f"  {status} {plan:12} ({season:6} {b_type:12}): JSON=${current_val:.5f} | XLSX=${rate:.5f}")

                # Threshold: Since XLSX is high-precision, we update even for small changes (> 0.0001)
                if diff > 0.0001: 
                    current_json["plans"][plan][season][b_type] = rate
                    updated = True

    if updated:
        if not args.dry_run:
            current_json["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(JSON_FILE, 'w') as f:
                json.dump(current_json, f, indent=2)
            print("\n>>> Result: Changes committed to JSON.")
        else:
            print("\n>>> Result: Dry Run complete. Data is highly precise.")
    else:
        print("\n>>> Result: No changes detected.")

    if os.path.exists(tmp_xlsx): os.remove(tmp_xlsx)

if __name__ == "__main__":
    main()
