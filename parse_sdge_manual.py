import os
import re
import json
import sys
import pdfplumber
from datetime import datetime

# --- CONFIGURATION ---
UPLOAD_DIR = "sdge_uploads"
JSON_FILE = "sdge_rates.json"

def extract_decimal(text):
    if not text: return 0.0
    clean = text.replace('$', '').replace(',', '').strip()
    if '(' in clean and ')' in clean:
        clean = "-" + clean.replace('(', '').replace(')', '')
    match = re.search(r"(-?\d+\.\d{3,6})", clean)
    return float(match.group(1)) if match else 0.0

def parse_sdge_pdf(pdf_path):
    print(f"\n[Analyzing PDF] {os.path.basename(pdf_path)}")
    
    # Use None to distinguish between "value not found" and "zero price"
    results = {
        "plan_id": None,
        "is_tiered": False,
        "summer": {"on": None, "mid": None, "off": None},
        "winter": {"on": None, "mid": None, "off": None},
        "baseline_credit": None,
        "service_charge": None
    }

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        text = page.extract_text()
        
        # 1. Identify Plan ID
        plan_match = re.search(r"Schedule\s+([A-Z0-9-]+)", text)
        if plan_match:
            results["plan_id"] = plan_match.group(1)
            # Schedule DR is the tiered plan
            if results["plan_id"] == "DR":
                results["is_tiered"] = True
            print(f"  > Target Plan: {results['plan_id']} (Tiered: {results['is_tiered']})")

        # 2. Extract Table Data
        table = page.extract_table()
        if table:
            current_season = None
            for row in table:
                row = [str(cell) if cell else "" for cell in row]
                row_str = " ".join(row)

                # Track Season block
                if "Summer" in row_str: current_season = "summer"
                elif "Winter" in row_str: current_season = "winter"

                if current_season:
                    total_rate = extract_decimal(row[-1])
                    if total_rate == 0.0: continue

                    if results["is_tiered"]:
                        # MAPPING FOR SCHEDULE DR (TIERED)
                        # Row containing "Tier 1" or "Up to 130%"
                        if "Tier 1" in row_str or "Up to 130%" in row_str:
                            results[current_season]["on"] = total_rate
                        # Row containing "Tier 2" or "Above 130%"
                        if "Tier 2" in row_str or "Above 130%" in row_str:
                            results[current_season]["mid"] = total_rate
                            results[current_season]["off"] = total_rate
                    else:
                        # MAPPING FOR TOU PLANS
                        if "On-Peak" in row_str: results[current_season]["on"] = total_rate
                        if "Off-Peak" in row_str: results[current_season]["mid"] = total_rate
                        if "Super Off-Peak" in row_str: results[current_season]["off"] = total_rate

                # Global attribute: Baseline Credit
                if "Baseline Adjustment Credit" in row_str:
                    credit = extract_decimal(row[-1])
                    if credit != 0: results["baseline_credit"] = abs(credit)

                # Global attribute: Daily Service Charge
                if "Base Services Charge ($/Day)" in row_str:
                    charge = extract_decimal(row[-1])
                    if charge != 0: results["service_charge"] = charge

    return results

def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run: print("!!! DRY RUN MODE: No changes will be saved to disk !!!")

    if not os.path.exists(UPLOAD_DIR):
        print(f"Directory {UPLOAD_DIR} not found.")
        return

    try:
        with open(JSON_FILE, 'r') as f:
            data = json.load(f)
    except:
        print(f"Error: {JSON_FILE} not found.")
        sys.exit(1)

    overall_updated = False
    
    for filename in os.listdir(UPLOAD_DIR):
        if not filename.lower().endswith(".pdf"): continue
        
        pdf_data = parse_sdge_pdf(os.path.join(UPLOAD_DIR, filename))
        raw_id = pdf_data["plan_id"]
        if not raw_id:
            print(f"  [Error] Could not identify Schedule ID in {filename}")
            continue
            
        plan_key = "Standard DR" if raw_id == "DR" else raw_id
        if plan_key not in data["plans"]:
            print(f"  [Skip] Plan {plan_key} not in JSON dictionary.")
            continue

        p = data["plans"][plan_key]
        
        # Comparison and Logging helper
        def update_val(category, bin_name, current_val, new_val):
            nonlocal overall_updated
            if new_val is not None and new_val != 0.0 and new_val != current_val:
                print(f"    [CHANGE] {plan_key} {category} {bin_name}: {current_val} -> {new_val}")
                overall_updated = True
                return new_val
            return current_val

        # Apply Updates
        p["dailyServiceCharge"] = update_val("Fixed", "Service Charge", p.get("dailyServiceCharge", 0), pdf_data["service_charge"])

        for season in ["summer", "winter"]:
            p[season]["onPeak"] = update_val(season.capitalize(), "On/Tier1", p[season].get("onPeak"), pdf_data[season]["on"])
            p[season]["offPeak"] = update_val(season.capitalize(), "Off/Tier2", p[season].get("offPeak"), pdf_data[season]["mid"])
            p[season]["superOffPeak"] = update_val(season.capitalize(), "SuperOff/Tier2", p[season].get("superOffPeak"), pdf_data[season]["off"])

        if pdf_data["baseline_credit"]:
            data["baselineCredit"] = update_val("Global", "Baseline Credit", data.get("baselineCredit"), pdf_data["baseline_credit"])

    if overall_updated:
        if not dry_run:
            data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(JSON_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            print("\n>>> Success: sdge_rates.json updated.")
        else:
            print("\n>>> Dry Run Complete: Changes detected but not saved.")
    else:
        print("\n>>> No changes detected in PDFs compared to current JSON.")

if __name__ == "__main__":
    main()
