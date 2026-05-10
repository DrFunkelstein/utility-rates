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
        full_text = page.extract_text()
        
        # 1. Identify Plan ID
        plan_match = re.search(r"Schedule\s+([A-Z0-9-]+)", full_text)
        if plan_match:
            results["plan_id"] = plan_match.group(1)
            if results["plan_id"] == "DR": results["is_tiered"] = True
            print(f"  > Target: {results['plan_id']} (Tiered: {results['is_tiered']})")

        # 2. Hybrid Extraction
        lines = full_text.split('\n')
        current_season = None

        for line in lines:
            line_clean = line.strip()
            if not line_clean: continue

            # Update Season Context
            if "Summer" in line_clean: 
                current_season = "summer"
            elif "Winter" in line_clean: 
                current_season = "winter"

            if current_season:
                # Find all 4 or 5 decimal numbers
                decimals = re.findall(r"\d+\.\d{4,5}", line_clean)
                if not decimals: continue
                
                rate = float(decimals[-1])

                if results["is_tiered"]:
                    if "Tier 1" in line_clean or "Up to" in line_clean:
                        results[current_season]["on"] = rate
                        print(f"    [Extracted] {current_season} Tier 1: {rate}")
                    elif "Tier 2" in line_clean or "Above" in line_clean:
                        results[current_season]["mid"] = rate
                        results[current_season]["off"] = rate
                        print(f"    [Extracted] {current_season} Tier 2: {rate}")
                else:
                    # TOU logic
                    if "On-Peak" in line_clean: 
                        results[current_season]["on"] = rate
                        print(f"    [Extracted] {current_season} On-Peak: {rate}")
                    elif "Off-Peak" in line_clean: 
                        results[current_season]["mid"] = rate
                        print(f"    [Extracted] {current_season} Off-Peak: {rate}")
                    elif "Super Off-Peak" in line_clean: 
                        results[current_season]["off"] = rate
                        print(f"    [Extracted] {current_season} Super Off-Peak: {rate}")

            # Global Attribute Extraction
            if "Baseline Adjustment Credit" in line_clean:
                decimals = re.findall(r"\(?\d+\.\d{4,5}\)?", line_clean)
                if decimals: 
                    credit_str = decimals[-1].replace('(','').replace(')','')
                    results["baseline_credit"] = abs(float(credit_str))
                    print(f"    [Extracted] Baseline Credit: {results['baseline_credit']}")

            if "Base Services Charge" in line_clean and "$/Day" in line_clean:
                if "DRAH" not in line_clean and "FERA" not in line_clean:
                    decimals = re.findall(r"\d+\.\d{4,5}", line_clean)
                    if decimals: 
                        results["service_charge"] = float(decimals[-1])
                        print(f"    [Extracted] Base Service Charge: {results['service_charge']}")

    return results

def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run: print("!!! DRY RUN MODE ACTIVE !!!")

    if not os.path.exists(UPLOAD_DIR):
        print(f"Error: {UPLOAD_DIR} not found.")
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
        if not pdf_data["plan_id"]: continue
            
        plan_key = "Standard DR" if pdf_data["plan_id"] == "DR" else pdf_data["plan_id"]
        if plan_key not in data["plans"]:
            print(f"  [Skip] {plan_key} not in app dictionary.")
            continue

        p = data["plans"][plan_key]
        
        def update_val(category, bin_name, current_val, new_val):
            nonlocal overall_updated
            if new_val is not None and new_val > 0.01 and abs(new_val - current_val) > 0.00001:
                print(f"    [CHANGE] {plan_key} {category} {bin_name}: {current_val} -> {new_val}")
                overall_updated = True
                return new_val
            return current_val

        # Apply Updates
        p["dailyServiceCharge"] = update_val("Fixed", "Service Charge", p.get("dailyServiceCharge", 0), pdf_data["service_charge"])

        for season in ["summer", "winter"]:
            p[season]["onPeak"] = update_val(season.capitalize(), "On/T1", p[season].get("onPeak"), pdf_data[season]["on"])
            p[season]["offPeak"] = update_val(season.capitalize(), "Off/T2", p[season].get("offPeak"), pdf_data[season]["mid"])
            p[season]["superOffPeak"] = update_val(season.capitalize(), "SuperOff/T2", p[season].get("superOffPeak"), pdf_data[season]["off"])

        if pdf_data["baseline_credit"]:
            data["baselineCredit"] = update_val("Global", "Baseline Credit", data.get("baselineCredit"), pdf_data["baseline_credit"])

    if overall_updated:
        if not dry_run:
            data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(JSON_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            print("\n>>> Success: JSON updated via PDF.")
        else:
            print("\n>>> Dry Run Complete: Changes detected but not saved.")
    else:
        print("\n>>> No changes detected (JSON already aligns with PDF).")

if __name__ == "__main__":
    main()
