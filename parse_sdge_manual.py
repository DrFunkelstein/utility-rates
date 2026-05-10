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
    # Clean up currency symbols and parentheses for negative numbers
    clean = text.replace('$', '').replace(',', '').strip()
    if '(' in clean and ')' in clean:
        clean = "-" + clean.replace('(', '').replace(')', '')
    # Match decimals like -0.10892 or 0.79343
    match = re.search(r"(-?\d+\.\d{3,6})", clean)
    return float(match.group(1)) if match else 0.0

def get_total_rate_from_row(row):
    """Iterates backwards from the end of the row to find the first valid decimal rate."""
    for cell in reversed(row):
        val = extract_decimal(str(cell))
        # Rates are usually between 0.01 and 2.0 (but not 0.0)
        if 0.01 < val < 2.0:
            return val
    return 0.0

def parse_sdge_pdf(pdf_path):
    print(f"\n[Analyzing PDF] {os.path.basename(pdf_path)}")
    
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
            if results["plan_id"] == "DR":
                results["is_tiered"] = True
            print(f"  > Target Plan: {results['plan_id']} (Tiered: {results['is_tiered']})")

        # 2. Extract Table Data
        table = page.extract_table()
        if table:
            current_season = None
            for row in table:
                # Clean row cells
                row = [str(cell).strip() if cell else "" for cell in row]
                row_str = " ".join(row)

                # Track Season Block
                if "Summer" in row_str: 
                    current_season = "summer"
                    continue
                elif "Winter" in row_str: 
                    current_season = "winter"
                    continue

                if current_season:
                    # FIX: Search row for the rate decimal, ignoring trailing dashes
                    total_rate = get_total_rate_from_row(row)
                    
                    if total_rate <= 0.01: continue 

                    if results["is_tiered"]:
                        # Tiered Logic: check for 'Tier 1' vs 'Tier 2'
                        if "Tier 1" in row_str or "Up to" in row_str:
                            print(f"    [Found] Tier 1 ({current_season}): {total_rate}")
                            results[current_season]["on"] = total_rate
                        elif "Tier 2" in row_str or "Above" in row_str:
                            print(f"    [Found] Tier 2 ({current_season}): {total_rate}")
                            results[current_season]["mid"] = total_rate
                            results[current_season]["off"] = total_rate
                    else:
                        # TOU Logic
                        if "On-Peak" in row_str: 
                            results[current_season]["on"] = total_rate
                        elif "Off-Peak" in row_str: 
                            results[current_season]["mid"] = total_rate
                        elif "Super Off-Peak" in row_str: 
                            results[current_season]["off"] = total_rate

                # Extract Global Attributes
                if "Baseline Adjustment Credit" in row_str:
                    # Baseline credit can be negative, so we use the standard extractor
                    credit = extract_decimal(row[-2] if len(row) > 1 else "") 
                    if credit == 0: credit = extract_decimal(row[-1]) # Fallback
                    if credit != 0: results["baseline_credit"] = abs(credit)

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
        if not raw_id: continue
            
        plan_key = "Standard DR" if raw_id == "DR" else raw_id
        if plan_key not in data["plans"]:
            print(f"  [Skip] Plan {plan_key} not in JSON.")
            continue

        p = data["plans"][plan_key]
        
        def update_val(category, bin_name, current_val, new_val):
            nonlocal overall_updated
            if new_val is not None and new_val > 0.01 and abs(new_val - current_val) > 0.00001:
                print(f"    [CHANGE] {plan_key} {category} {bin_name}: {current_val} -> {new_val}")
                overall_updated = True
                return new_val
            return current_val

        # Update JSON
        p["dailyServiceCharge"] = update_val("Fixed", "Service Charge", p.get("dailyServiceCharge", 0), pdf_data["service_charge"])

        for season in ["summer", "winter"]:
            p[season]["onPeak"] = update_val(season.capitalize(), "Tier 1", p[season].get("onPeak"), pdf_data[season]["on"])
            p[season]["offPeak"] = update_val(season.capitalize(), "Tier 2", p[season].get("offPeak"), pdf_data[season]["mid"])
            p[season]["superOffPeak"] = update_val(season.capitalize(), "Tier 2", p[season].get("superOffPeak"), pdf_data[season]["off"])

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
        print("\n>>> No changes detected (JSON matches PDF).")

if __name__ == "__main__":
    main()
