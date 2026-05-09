import os
import re
import json
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

def parse_sdge_pdf(pdf_path):
    print(f"Processing: {os.path.basename(pdf_path)}")
    
    results = {
        "plan_id": None,
        "summer": {"on": 0.0, "mid": 0.0, "off": 0.0},
        "winter": {"on": 0.0, "mid": 0.0, "off": 0.0},
        "baseline_credit": 0.0,
        "service_charge": 0.0
    }

    with pdfplumber.open(pdf_path) as pdf:
        # SDG&E summaries are always on the first page
        page = pdf.pages[0]
        text = page.extract_text()
        
        # 1. Identify Plan ID (e.g. Schedule TOU-DR1 or Schedule DR)
        plan_match = re.search(r"Schedule\s+([A-Z0-9-]+)", text)
        if plan_match:
            results["plan_id"] = plan_match.group(1)

        # 2. Extract Table Data
        table = page.extract_table()
        if table:
            current_season = None
            for row in table:
                # Clean row and join to string for searching
                row = [str(cell) if cell else "" for cell in row]
                row_str = " ".join(row)

                # Identify Season Section
                if "Summer" in row_str: current_season = "summer"
                if "Winter" in row_str: current_season = "winter"

                # Map the 'Total Electric Rate' (Final Column) to our bins
                if current_season:
                    total_rate = extract_decimal(row[-1])
                    if "On-Peak" in row_str: results[current_season]["on"] = total_rate
                    if "Off-Peak" in row_str: results[current_season]["mid"] = total_rate
                    if "Super Off-Peak" in row_str: results[current_season]["off"] = total_rate

                # Extract Baseline Credit (Found in the TRAC/UDC/Total columns)
                if "Baseline Adjustment Credit" in row_str:
                    credit = extract_decimal(row[-1])
                    if credit != 0:
                        results["baseline_credit"] = abs(credit)

                # Extract Service Charge
                if "Base Services Charge ($/Day)" in row_str:
                    charge = extract_decimal(row[-1])
                    if charge != 0:
                        results["service_charge"] = charge

    return results

def main():
    if not os.path.exists(UPLOAD_DIR):
        print(f"Directory {UPLOAD_DIR} not found.")
        return

    # Load existing JSON
    try:
        with open(JSON_FILE, 'r') as f:
            data = json.load(f)
    except:
        data = {"lastUpdated": "", "plans": {}}

    updated = False
    
    for filename in os.listdir(UPLOAD_DIR):
        if filename.lower().endswith(".pdf"):
            pdf_data = parse_sdge_pdf(os.path.join(UPLOAD_DIR, filename))
            
            # Map PDF name to JSON key
            raw_id = pdf_data["plan_id"]
            if not raw_id: continue
            
            # Normalize IDs to match App logic
            plan_key = raw_id
            if raw_id == "DR": plan_key = "Standard DR"

            # Prepare JSON entry
            if plan_key not in data["plans"]:
                # Default metadata for new plans
                data["plans"][plan_key] = {"hasBaseline": True, "monthlySubscriptionFee": 0.0}

            # Inject parsed values
            p = data["plans"][plan_key]
            p["dailyServiceCharge"] = pdf_data["service_charge"]
            p["summer"] = {"onPeak": pdf_data["summer"]["on"], "offPeak": pdf_data["summer"]["mid"], "superOffPeak": pdf_data["summer"]["off"]}
            p["winter"] = {"onPeak": pdf_data["winter"]["on"], "offPeak": pdf_data["winter"]["mid"], "superOffPeak": pdf_data["winter"]["off"]}
            
            # Global Baseline Credit update (SDG&E usually standardizes this across residential)
            if pdf_data["baseline_credit"] > 0:
                data["baselineCredit"] = pdf_data["baseline_credit"]
            
            print(f"  Updated {plan_key}")
            updated = True

    if updated:
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(JSON_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        print("\n>>> Success: sdge_rates.json updated via PDF.")

if __name__ == "__main__":
    main()
