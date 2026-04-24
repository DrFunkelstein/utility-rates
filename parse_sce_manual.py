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
    saw_summer_header = False
    completed_plans = set()
    
    # Precise Spaceless Targets
    plan_targets = {
        "TOU-D-4": "OPTION4-9PM",
        "TOU-D-5": "OPTION5-8PM",
        "PRIME": "OPTIONPRIME",
        "Domestic": "SCHEDULED"
    }

    print(f"DEBUG: Processing {len(lines)} lines...")

    for line in lines:
        clean_line = line.strip()
        if not clean_line: continue
        norm = normalize(clean_line)

        # 1. DETECT THE ACTUAL TABLE START
        # We only set current_plan if we see the plan name AND it looks like a table header
        # Table headers usually have 'TOTAL' or 'GENERATION' on the same or nearby lines
        for plan_id, target in plan_targets.items():
            if target in norm and plan_id not in completed_plans:
                # Filter out sentences: "Available as an option to...", "Eligibility for...", etc.
                if any(x in norm for x in ["AVAILABLE", "ELIGIB", "PURSUANT", "CANCELLING", "REVISED"]):
                    continue
                
                # Special check for Domestic vs TOU-D
                if plan_id == "Domestic" and "TOU" in norm:
                    continue

                current_plan = plan_id
                saw_summer_header = False
                print(f"DEBUG: Entering Table Area for {current_plan}")

        if not current_plan:
            continue

        # 2. TRACK SEASONAL CONTEXT
        # If we see "Summer", we start looking for "On-Peak"
        if "SUMMER" in norm:
            saw_summer_header = True
            print(f"   ...Found Summer header for {current_plan}")
        
        # If we see "Winter", we stop looking for Summer On-Peak for this plan
        if "WINTER" in norm and saw_summer_header:
            print(f"   ...Hit Winter, abandoning search for {current_plan}")
            current_plan = None
            saw_summer_header = False
            continue

        # 3. MATCH THE RATE ROW
        is_rate_row = False
        if current_plan == "Domestic":
            # Schedule D matches 'Baseline Usage'
            if "BASELINE" in norm and "USAGE" in norm:
                is_rate_row = True
        else:
            # TOU matches 'On-Peak' only if we've seen a Summer header recently
            if "ON-PEAK" in norm and saw_summer_header:
                is_rate_row = True

        if is_rate_row:
            # Find all 5-decimal numbers
            rates = re.findall(r"(\d+\.\d{5})", clean_line)
            
            if len(rates) >= 2:
                # Delivery (0) + Generation (1)
                delivery = float(rates[0])
                generation = float(rates[1])
                total = round(delivery + generation, 5)
                
                found_data[current_plan] = total
                print(f"   >> SUCCESS: {current_plan} = ${total} ({delivery} + {generation})")
                
                completed_plans.add(current_plan)
                current_plan = None # Reset to look for next table
                saw_summer_header = False
            elif current_plan == "Domestic" and len(rates) == 1:
                # Backup for single-column Schedule D
                val = float(rates[0])
                found_data[current_plan] = val
                print(f"   >> SUCCESS: {current_plan} = ${val}")
                completed_plans.add(current_plan)
                current_plan = None
                saw_summer_header = False

    return found_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)
    files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith((".pdf", ".txt"))]
    
    if not files:
        print("No files found. Upload to 'sce_uploads'.")
        sys.exit(0)

    all_results = {}
    for filename in files:
        print(f"\n--- Checking File: {filename} ---")
        path = os.path.join(UPLOAD_FOLDER, filename)
        if filename.endswith(".pdf"):
            with pdfplumber.open(path) as pdf:
                content = "\n".join([p.extract_text() or "" for p in pdf.pages])
        else:
            with open(path, 'r', encoding='utf-8') as f: content = f.read()
        
        all_results.update(extract_from_raw_text(content))

    if not all_results:
        print("\nFAILURE: No rates matched.")
        sys.exit(1)

    if args.dry_run:
        print("\n--- DRY RUN RESULTS ---")
        for k, v in all_results.items(): print(f"{k}: ${v}")
        sys.exit(0)

    # Save to JSON
    try:
        with open(JSON_FILE, 'r') as f: data = json.load(f)
        for pid, val in all_results.items():
            if pid == "Domestic": data["plans"]["Domestic"]["summer"]["tier1"] = val
            else: data["plans"][pid]["summer"]["onPeak"] = val
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(JSON_FILE, 'w') as f: json.dump(data, f, indent=2)
        print("\nSUCCESS: JSON updated.")
    except Exception as e:
        print(f"Error: {e}"); sys.exit(1)

if __name__ == "__main__":
    main()
