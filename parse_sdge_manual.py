import os
import re
import json
import pdfplumber
from datetime import datetime

# --- CONFIGURATION ---
PDF_DIR = "pdfs/sdge"
JSON_FILE = "sdge_rates.json"

def extract_decimal(text):
    if not text: return 0.0
    # Clean up currency symbols and parentheses for negative numbers
    clean = text.replace('$', '').replace(',', '').strip()
    if '(' in clean and ')' in clean:
        clean = "-" + clean.replace('(', '').replace(')', '')
    match = re.search(r"(-?\d+\.\d{3,6})", clean)
    return float(match.group(1)) if match else 0.0

def parse_sdge_tariff(pdf_path):
    print(f"--- Parsing SDG&E PDF: {os.path.basename(pdf_path)} ---")
    
    results = {
        "plan_id": None,
        "summer": {"on": 0, "mid": 0, "off": 0},
        "winter": {"on": 0, "mid": 0, "off": 0},
        "baseline_credit": 0.10892, # Fallback
        "service_charge": 0.79343   # Fallback
    }

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        text = page.extract_text()
        
        # 1. IDENTIFY PLAN ID (e.g. Schedule TOU-DR1)
        plan_match = re.search(r"Schedule\s+([A-Z0-9-]+)", text)
        if plan_match:
            results["plan_id"] = plan_match.group(1)
            print(f"  Detected Plan: {results['plan_id']}")

        # 2. EXTRACT RATES FROM THE TABLE
        # We target the 'Total Electric Rate' column (usually the last one)
        table = page.extract_table()
        if table:
            current_season = None
            for row in table:
                # Remove None types and clean strings
                row = [str(cell) if cell else "" for cell in row]
                row_str = " ".join(row)

                # Identify Season blocks
                if "Summer" in row_str: current_season = "summer"
                if "Winter" in row_str: current_season = "winter"

                # Extract Peak Values from the LAST column (Total Electric Rate)
                if current_season:
                    rate_val = extract_decimal(row[-1])
                    if "On-Peak" in row_str: results[current_season]["on"] = rate_val
                    if "Off-Peak" in row_str: results[current_season]["mid"] = rate_val
                    if "Super Off-Peak" in row_str: results[current_season]["off"] = rate_val

                # Extract Baseline Adjustment Credit
                if "Baseline Adjustment Credit" in row_str:
                    credit = extract_decimal(row[-1])
                    if credit != 0:
                        results["baseline_credit"] = abs(credit)

                # Extract Base Services Charge
                if "Base Services Charge ($/Day)" in row_str:
                    charge = extract_decimal(row[-1])
                    if charge != 0:
                        results["service_charge"] = charge

    return results

def main():
    if not os.path.exists(PDF_DIR):
        print(f"Directory {PDF_DIR} not found. Skipping.")
        return

    # Load existing JSON
    try:
        with open(JSON_FILE, 'r') as f:
            data = json.load(f)
    except:
        print("sdge_rates.json not found. Initializing.")
        data = {"lastUpdated": "", "plans": {}}

    updated = False
    
    # Process every PDF in the directory
    for filename in os.listdir(PDF_DIR):
        if filename.lower().endswith(".pdf"):
            pdf_results = parse_sdge_tariff(os.path.join(PDF_DIR, filename))
            
            plan_id = pdf_results["plan_id"]
            if not plan_id: continue
            
            # Map PDF Schedule Name to App Plan ID
            # (Matches 'Standard' for Schedule DR, etc)
            app_id = plan_id
            if plan_id == "DR": app_id = "Standard DR"

            # Update the JSON structure
            if app_id not in data["plans"]:
                data["plans"][app_id] = {"hasBaseline": True, "summer": {}, "winter": {}}

            # Update rates
            data["plans"][app_id]["summer"] = {
                "onPeak": pdf_results["summer"]["on"],
                "offPeak": pdf_results["summer"]["mid"],
                "superOffPeak": pdf_results["summer"]["off"]
            }
            data["plans"][app_id]["winter"] = {
                "onPeak": pdf_results["winter"]["on"],
                "offPeak": pdf_results["winter"]["mid"],
                "superOffPeak": pdf_results["winter"]["off"]
            }
            
            # Update Global Constants
            data["baselineCredit"] = pdf_results["baseline_credit"]
            data["plans"][app_id]["dailyServiceCharge"] = pdf_results["service_charge"]
            
            updated = True
            print(f"  Successfully updated {app_id} in JSON.")

    if updated:
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(JSON_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        print("\n>>> All SDG&E PDFs processed. JSON saved.")

if __name__ == "__main__":
    main()
