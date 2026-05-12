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
    """Cleans currency strings like '$0.52240' or '($0.08140)' into floats."""
    if pd.isna(val): return 0.0
    s = str(val).replace('$', '').replace(',', '').strip()
    if '(' in s and ')' in s:
        return -float(s.replace('(', '').replace(')', ''))
    try:
        return float(s)
    except:
        return 0.0

def parse_pge_xlsx(file_path):
    print(f"\n[Excel Scan] Processing workbook...")
    
    xlsx = pd.ExcelFile(file_path)
    extracted_data = {}
    baseline_credit_found = None

    # We iterate through all sheets because PG&E often splits 
    # Standard and EV rates into separate tabs.
    for sheet_name in xlsx.sheet_names:
        df = xlsx.parse(sheet_name)
        # Convert all content to string for easy searching
        df_str = df.astype(str)

        # 1. E-1 Tiered Logic
        if "E1" in extracted_data == False or True: # Force check
            e1_rows = df[df.iloc[:, 0].str.contains("E1", na=False)]
            if not e1_rows.empty:
                row = e1_rows.iloc[0]
                # Col 8 = Tier 1, Col 9 = Tier 2
                t1, t2 = clean_val(row.iloc[8]), clean_val(row.iloc[9])
                if t1 > 0:
                    extracted_data["E-1 tiered"] = {
                        "summer": {"onPeak": t2, "offPeak": t1},
                        "winter": {"onPeak": t2, "offPeak": t1}
                    }

        # 2. TOU-C and TOU-D Logic
        for plan_id, search_term in [("E-TOU-C", "E-TOU-C"), ("E-TOU-D", "E-TOU-D")]:
            plan_rows = df[df.iloc[:, 0].str.contains(search_term, na=False)]
            if not plan_rows.empty:
                # TOU plans usually span 4 rows (Summer Peak/Off, Winter Peak/Off)
                # We start from the match and look at the next few rows
                start_idx = plan_rows.index[0]
                res = {"summer": {}, "winter": {}}
                
                for i in range(start_idx, start_idx + 8):
                    if i >= len(df): break
                    row = df.iloc[i]
                    season = str(row.iloc[7]).lower()
                    period = str(row.iloc[8]).lower()
                    rate = clean_val(row.iloc[9])
                    
                    if "summer" in season:
                        if "peak" in period and "off" not in period: res["summer"]["onPeak"] = rate
                        elif "off" in period: res["summer"]["offPeak"] = rate
                    elif "winter" in season:
                        if "peak" in period and "off" not in period: res["winter"]["onPeak"] = rate
                        elif "off" in period: res["winter"]["offPeak"] = rate
                    
                    # Capture Baseline Credit from TOU-C row if available
                    b_credit = clean_val(row.iloc[10])
                    if b_credit < 0: baseline_credit_found = abs(b_credit)

                if res["summer"] or res["winter"]:
                    extracted_data[plan_id] = res

        # 3. EV and E-ELEC Logic (Table 2)
        ev_plans = [
            ("EV-B", "EV, Rate B"),
            ("EV2-A", "EV2"),
            ("E-ELEC", "E-ELEC")
        ]
        
        for json_id, search_term in ev_plans:
            plan_rows = df[df.iloc[:, 0].str.contains(search_term, na=False)]
            if not plan_rows.empty:
                start_idx = plan_rows.index[0]
                res = {"summer": {}, "winter": {}}
                
                for i in range(start_idx, start_idx + 12):
                    if i >= len(df): break
                    row = df.iloc[i]
                    season = str(row.iloc[6]).lower()
                    period = str(row.iloc[7]).lower()
                    rate = clean_val(row.iloc[8])

                    target_season = None
                    if "summer" in season: target_season = "summer"
                    elif "winter" in season: target_season = "winter"
                    
                    if target_season:
                        if "peak" in period and "part" not in period and "off" not in period:
                            res[target_season]["onPeak"] = rate
                        elif "part" in period:
                            res[target_season]["offPeak"] = rate
                        elif "off" in period:
                            res[target_season]["superOffPeak"] = rate

                if res["summer"] or res["winter"]:
                    extracted_data[json_id] = res

    return extracted_data, baseline_credit_found

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run: print("\n!!! DRY RUN MODE: No files will be modified !!!")

    tmp_xlsx = "pge_temp.xlsx"
    download_xlsx(XLSX_URL, tmp_xlsx)
    
    new_data, b_credit = parse_pge_xlsx(tmp_xlsx)
    
    with open(JSON_FILE, 'r') as f:
        current_json = json.load(f)

    print("\n[Comparison Ledger: JSON vs Excel]")
    updated = False
    
    # Update Baseline Credit if found
    if b_credit:
        old_bc = current_json.get("baselineCredit", 0)
        if abs(b_credit - old_bc) > 0.0001:
            print(f"  [CHANGE] Global Baseline Credit: ${old_bc:.5f} -> ${b_credit:.5f}")
            current_json["baselineCredit"] = b_credit
            updated = True

    for plan in ["E-1 tiered", "E-TOU-C", "E-TOU-D", "E-ELEC", "EV2-A", "EV-B"]:
        if plan not in new_data: continue
        for season in ["summer", "winter"]:
            for b_type in ["onPeak", "offPeak", "superOffPeak"]:
                rate = new_data[plan][season].get(b_type, 0)
                if rate == 0: continue
                
                current_val = current_json["plans"][plan][season].get(b_type, 0)
                diff = abs(rate - current_val)
                status = "[MATCH]" if diff < 0.00001 else "[CHANGE DETECTED]"
                
                print(f"  {status} {plan:12} ({season:6} {b_type:12}): JSON=${current_val:.5f} | XLSX=${rate:.5f}")

                if diff > 0.0001: 
                    current_json["plans"][plan][season][b_type] = rate
                    updated = True

    if updated and not args.dry_run:
        current_json["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(JSON_FILE, 'w') as f:
            json.dump(current_json, f, indent=2)
        print("\n>>> Result: Success. Changes committed.")
    else:
        print("\n>>> Result: No changes saved.")

    if os.path.exists(tmp_xlsx): os.remove(tmp_xlsx)

if __name__ == "__main__":
    main()
