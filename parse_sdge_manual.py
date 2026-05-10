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

def get_best_decimal_from_row(row):
    """Finds the 'Total Rate' by looking for the last valid decimal in the row, ignoring dashes."""
    for cell in reversed(row):
        val = extract_decimal(str(cell))
        # Rates are decimals (0.05 to 0.95) or service charges (0.10 to 0.90)
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
        "service_charge": None,
        "service_charge_reduced": None  # Key for DRAH/FERA reduced daily rate
    }

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        full_text = page.extract_text()
        
        # 1. Identify Plan ID
        plan_match = re.search(r"Schedule\s+([A-Z0-9-]+)", full_text)
        if plan_match:
            results["plan_id"] = plan_match.group(1)
            if results["plan_id"] == "DR": results["is_tiered"] = True
            print(f"  > Target: {results['plan_id']}")

        # 2. Hybrid Extraction
        # We iterate through rows extracted as tables first, as they preserve cell order
        table_data = page.extract_table()
        current_season = None

        if table_data:
            for row in table_data:
                row = [str(c).strip() if c else "" for c in row]
                row_str = " ".join(row)

                # Update Season context
                if "Summer" in row_str: current_season = "summer"
                elif "Winter" in row_str: current_season = "winter"

                if current_season:
                    val = get_best_decimal_from_row(row)
                    if val <= 0.01: continue

                    if results["is_tiered"]:
                        if "Tier 1" in row_str or "Up to" in row_str:
                            results[current_season]["on"] = val
                            print(f"    [Extracted] {current_season} Tier 1: {val}")
                        elif "Tier 2" in row_str or "Above" in row_str:
                            results[current_season]["mid"] = val
                            results[current_season]["off"] = val
                            print(f"    [Extracted] {current_season} Tier 2: {val}")
                    else:
                        # TOU LOGIC: Strict order to prevent substring collision
                        if "Super Off-Peak" in row_str:
                            results[current_season]["off"] = val
                            print(f"    [Extracted] {current_season} Super Off-Peak: {val}")
                        elif "Off-Peak" in row_str:
                            results[current_season]["mid"] = val
                            print(f"    [Extracted] {current_season} Off-Peak: {val}")
                        elif "On-Peak" in row_str:
                            results[current_season]["on"] = val
                            print(f"    [Extracted] {current_season} On-Peak: {val}")

                # Fixed Charge Logic
                if "Base Services Charge" in row_str:
                    charge_val = get_best_decimal_from_row(row)
                    if charge_val > 0:
                        # Check if this row is for DRAH or FERA reduced rates
                        if "DRAH" in row_str or "FERA" in row_str:
                            results["service_charge_reduced"] = charge_val
                            print(f"    [Extracted] Reduced Svc Charge: {charge_val}")
                        else:
                            results["service_charge"] = charge_val
                            print(f"    [Extracted] Standard Svc Charge: {charge_val}")

                # Global Baseline Credit
                if "Baseline Adjustment Credit" in row_str:
                    credit_val = get_best_decimal_from_row(row)
                    if credit_val != 0:
                        results["baseline_credit"] = abs(credit_val)
                        print(f"    [Extracted] Baseline Credit: {results['baseline_credit']}")

    return results

def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run: print("!!! DRY RUN MODE ACTIVE !!!")

    if not os.path.exists(UPLOAD_DIR):
        print(f"Error: {UPLOAD_DIR} directory not found.")
        return

    try:
        with open(JSON_FILE, 'r') as f:
            data = json.load(f)
    except:
        sys.exit(1)

    overall_updated = False
    
    for filename in os.listdir(UPLOAD_DIR):
        if not filename.lower().endswith(".pdf"): continue
        pdf_data = parse_sdge_pdf(os.path.join(UPLOAD_DIR, filename))
        
        raw_id = pdf_data["plan_id"]
        if not raw_id: continue
        plan_key = "Standard DR" if raw_id == "DR" else raw_id
        if plan_key not in data["plans"]: continue

        p = data["plans"][plan_key]
        
        def update_val(category, bin_name, current_val, new_val):
            nonlocal overall_updated
            if new_val is not None and new_val > 0.0 and abs(new_val - (current_val or 0)) > 0.00001:
                print(f"    [CHANGE] {plan_key} {category} {bin_name}: {current_val} -> {new_val}")
                overall_updated = True
                return new_val
            return current_val

        # Apply Service Charges
        p["dailyServiceCharge"] = update_val("Fixed", "Std Svc Charge", p.get("dailyServiceCharge"), pdf_data["service_charge"])
        p["dailyServiceChargeLowIncome"] = update_val("Fixed", "Reduced Svc Charge", p.get("dailyServiceChargeLowIncome"), pdf_data["service_charge_reduced"])

        # Apply Rates
        for s in ["summer", "winter"]:
            p[s]["onPeak"] = update_val(s.capitalize(), "On/T1", p[s].get("onPeak"), pdf_data[s]["on"])
            p[s]["offPeak"] = update_val(s.capitalize(), "Off/T2", p[s].get("offPeak"), pdf_data[s]["mid"])
            p[s]["superOffPeak"] = update_val(s.capitalize(), "SuperOff/T2", p[s].get("superOffPeak"), pdf_data[s]["off"])

        if pdf_data["baseline_credit"]:
            data["baselineCredit"] = update_val("Global", "Baseline Credit", data.get("baselineCredit"), pdf_data["baseline_credit"])

    if overall_updated:
        if not dry_run:
            data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(JSON_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            print("\n>>> Success: JSON updated.")
        else:
            print("\n>>> Dry Run Complete: Changes detected but not saved.")
    else:
        print("\n>>> No changes detected between PDF and JSON.")

if __name__ == "__main__":
    main()
