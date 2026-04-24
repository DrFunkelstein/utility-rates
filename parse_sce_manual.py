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
    """Removes all whitespace and converts to uppercase for reliable matching."""
    return re.sub(r'\s+', '', text).upper()

def extract_from_raw_text(text):
    found_data = {}
    lines = text.split('\n')
    
    current_plan = None
    completed_plans = set()
    
    # We define 'Spaceless' versions of our targets to defeat the bad PDF encoding
    plan_targets = {
        "TOU-D-4": "OPTION4-9PM",
        "TOU-D-5": "OPTION5-8PM",
        "PRIME": "OPTIONPRIME",
        "Domestic": "SCHEDULED" # This is for the Tiered PDF
    }

    print(f"DEBUG: Starting scan of {len(lines)} lines...")

    for line in lines:
        clean_line = line.strip()
        if not clean_line: continue
        
        # 1. SCAN FOR PLAN HEADERS
        # We only look for headers that contain 'Total1' or 'UG***' to ensure 
        # it's a table start and not just a sentence.
        norm_line = normalize(clean_line)
        
        for plan_id, target in plan_targets.items():
            if target in norm_line and plan_id not in completed_plans:
                # Extra safety: If we found "SCHEDULED", make sure "TOU" isn't also there
                if plan_id == "Domestic" and "TOU" in norm_line:
                    continue
                
                # Filter out the "Available as an option" sentences
                if "AVAILABLE" in norm_line and "OPTION" in norm_line:
                    continue

                current_plan = plan_id
                print(f"DEBUG: >>> Entering Table for {current_plan}")

        # 2. SCAN FOR RATES WITHIN THE ACTIVE PLAN
        if current_plan:
            # We look for the On-Peak row for TOU, or Baseline for Domestic
            # The text dump shows: 'Summer Season - On-Peak 0.33082 (R) 0.25448 (R) 0.00000'
            is_rate_row = False
            if current_plan == "Domestic":
                if "BASELINE" in norm_line and "USAGE" in norm_line:
                    is_rate_row = True
            else:
                if "SUMMER" in norm_line and "ON-PEAK" in norm_line:
                    is_rate_row = True

            if is_rate_row:
                # Find all 5-decimal numbers
                rates = re.findall(r"(\d+\.\d{5})", clean_line)
                print(f"DEBUG: Found potential rates on row: {rates}")
                
                if len(rates) >= 2:
                    # RULE: SCE Total = Delivery (Index 0) + Generation (Index 1)
                    delivery = float(rates[0])
                    generation = float(rates[1])
                    total = round(delivery + generation, 5)
                    
                    found_data[current_plan] = total
                    print(f"DEBUG: SUCCESS matched {current_plan}: ${delivery} + ${generation} = ${total}")
                    
                    completed_plans.add(current_plan)
                    current_plan = None # Unlock to find next plan

    return found_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)

    files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith((".pdf", ".txt"))]
    if not files:
        print("No files found. Upload .pdf or .txt to 'sce_uploads'.")
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
        print("FAILURE: No rates matched. Check if the text file contains 'Summer Season - On-Peak'.")
        sys.exit(1)

    if args.dry_run:
        print("\n--- DRY RUN COMPLETE ---")
        print("Data found:", all_extracted)
        sys.exit(0)

    # Committing to JSON
    try:
        with open(JSON_FILE, 'r') as f: data = json.load(f)
        for pid, val in all_extracted.items():
            if pid == "Domestic": 
                data["plans"]["Domestic"]["summer"]["tier1"] = val
            else: 
                data["plans"][pid]["summer"]["onPeak"] = val
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(JSON_FILE, 'w') as f: json.dump(data, f, indent=2)
        print(f"SUCCESS: {JSON_FILE} updated.")
    except Exception as e:
        print(f"Error: {e}"); sys.exit(1)

if __name__ == "__main__":
    main()
