import pdfplumber
import json
import re
import os
import sys
import argparse
from datetime import datetime

UPLOAD_FOLDER = "sce_uploads"
JSON_FILE = "sce_rates.json"

def normalize(text):
    return re.sub(r'\s+', '', text).upper()

def extract_from_raw_text(text):
    found_data = {}
    lines = text.split('\n')
    
    current_plan = None
    saw_summer_context = False
    completed_plans = set()
    
    plan_targets = {
        "TOU-D-4": "OPTION4-9PM",
        "TOU-D-5": "OPTION5-8PM",
        "PRIME": "OPTIONPRIME",
        "Domestic": "SCHEDULED"
    }

    print(f"DEBUG: Analyzing {len(lines)} lines...")

    for line in lines:
        clean_line = line.strip()
        if not clean_line: continue
        norm_line = normalize(clean_line)

        # 1. DETECT PLAN HEADERS
        # We look for the "OPTION" header that appears above the tables
        for plan_id, target in plan_targets.items():
            # Avoid the 'Applicability' sentences by checking for 'Option' string
            if target in norm_line and "OPTION" in norm_line and "-CPP" not in norm_line:
                if plan_id not in completed_plans:
                    # Specific check to ensure Schedule D doesn't match TOU-D
                    if plan_id == "Domestic" and "TOU" in norm_line:
                        continue
                    
                    current_plan = plan_id
                    saw_summer_context = False # Reset context for new plan
                    print(f"DEBUG: >>> Entering Table Context: {current_plan}")

        if not current_plan:
            continue

        # 2. DETECT SUMMER CONTEXT
        # Some plans put 'Summer' on its own line, others put it on the rate line.
        if "SUMMER" in norm_line:
            saw_summer_context = True

        # 3. DETECT RATE ROW
        is_rate_row = False
        if current_plan == "Domestic":
            # For Tiered: look for 'Baseline Usage' row
            if "BASELINE" in norm_line and "USAGE" in norm_line and "TOTAL" in norm_line:
                is_rate_row = True
        else:
            # For TOU: look for 'On-Peak' while in Summer context
            if "ON-PEAK" in norm_line and saw_summer_context:
                is_rate_row = True

        if is_rate_row:
            # Find all 5-decimal numbers
            rates = re.findall(r"(\d+\.\d{5})", clean_line)
            
            if len(rates) >= 2:
                # SCE Logic: Total = Delivery (0) + Generation (1)
                delivery = float(rates[0])
                generation = float(rates[1])
                total = round(delivery + generation, 5)
                
                found_data[current_plan] = total
                print(f"DEBUG: SUCCESS matched {current_plan}: ${delivery} + ${generation} = ${total}")
                
                completed_plans.add(current_plan)
                current_plan = None # Unlock
                saw_summer_context = False
            elif current_plan == "Domestic" and len(rates) == 1:
                # Backup for simple Schedule D rows
                total = float(rates[0])
                found_data[current_plan] = total
                print(f"DEBUG: SUCCESS matched {current_plan}: ${total}")
                completed_plans.add(current_plan)
                current_plan = None
                saw_summer_context = False

    return found_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)

    files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith((".pdf", ".txt"))]
    if not files:
        print("No files found in sce_uploads.")
        sys.exit(0)

    all_extracted = {}
    for filename in files:
        print(f"--- File: {filename} ---")
        path = os.path.join(UPLOAD_FOLDER, filename)
        if filename.endswith(".pdf"):
            with pdfplumber.open(path) as pdf:
                content = "\n".join([p.extract_text() or "" for p in pdf.pages])
        else:
            with open(path, 'r', encoding='utf-8') as f: content = f.read()
        
        all_extracted.update(extract_from_raw_text(content))

    if not all_extracted:
        print("FAILURE: No rates matched.")
        sys.exit(1)

    if args.dry_run:
        print("\n--- DRY RUN COMPLETE ---")
        print("Data found:", all_extracted)
        sys.exit(0)

    try:
        with open(JSON_FILE, 'r') as f: data = json.load(f)
        for pid, val in all_extracted.items():
            if pid == "Domestic": data["plans"]["Domestic"]["summer"]["tier1"] = val
            else: data["plans"][pid]["summer"]["onPeak"] = val
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(JSON_FILE, 'w') as f: json.dump(data, f, indent=2)
        print(f"SUCCESS: {JSON_FILE} updated.")
    except Exception as e:
        print(f"Error: {e}"); sys.exit(1)

if __name__ == "__main__":
    main()
