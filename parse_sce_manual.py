import pdfplumber
import json
import re
import os
import sys
import argparse
from datetime import datetime

UPLOAD_FOLDER = "sce_uploads"
JSON_FILE = "sce_rates.json"

def extract_from_raw_text(text):
    found_data = {}
    lines = text.split('\n')
    
    current_plan = None
    completed_plans = set() 
    
    print(f"DEBUG: Total lines to analyze: {len(lines)}")

    # REGEX for Headers (Handles weird spaces like 'Opt io n')
    # These look for the keywords regardless of internal spacing
    header_patterns = {
        "TOU-D-4": re.compile(r"Opt.*?io.*?n.*?4-9.*?PM", re.IGNORECASE),
        "TOU-D-5": re.compile(r"Opt.*?io.*?n.*?5-8.*?PM", re.IGNORECASE),
        "PRIME": re.compile(r"Opt.*?io.*?n.*?PRIME", re.IGNORECASE),
        "Domestic": re.compile(r"Sched.*?ule.*?D", re.IGNORECASE)
    }

    for line in lines:
        clean_line = line.strip()
        if not clean_line: continue

        # 1. DETECT PLAN HEADERS (if not currently locked)
        if not current_plan:
            for plan_id, pattern in header_patterns.items():
                if pattern.search(clean_line) and "-CPP" not in clean_line.upper():
                    # Special check: Don't let 'Schedule TOU-D' count as 'Domestic'
                    if plan_id == "Domestic" and "TOU" in clean_line.upper():
                        continue
                        
                    if plan_id not in completed_plans:
                        current_plan = plan_id
                        print(f"DEBUG: Found header for {current_plan} in line: '{clean_line}'")
                        break

        # 2. EXTRACT DATA
        if current_plan:
            # Logic: We are looking for the 'Summer' 'On-Peak' line
            # Domestic uses 'Baseline Usage'
            is_target = False
            if current_plan == "Domestic":
                if "Baseline" in clean_line and "Usage" in clean_line and "Total" in clean_line:
                    is_target = True
            else:
                if "Summer" in clean_line and "On-Peak" in clean_line:
                    is_target = True

            if is_target:
                # Find all 5-decimal rates: 0.XXXXX
                rates = re.findall(r"(\d+\.\d{5})", clean_line)
                print(f"DEBUG: Target row found for {current_plan}. Found numbers: {rates}")
                
                if len(rates) >= 2:
                    # Sum Delivery + Generation
                    val = round(float(rates[0]) + float(rates[1]), 5)
                    found_data[current_plan] = val
                    print(f"   >> SUCCESS: {current_plan} -> ${val}")
                    completed_plans.add(current_plan)
                    current_plan = None # Unlock to find next plan
                elif current_plan == "Domestic" and len(rates) == 1:
                    val = float(rates[0])
                    found_data[current_plan] = val
                    print(f"   >> SUCCESS: Domestic -> ${val}")
                    completed_plans.add(current_plan)
                    current_plan = None

    return found_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)

    files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith((".pdf", ".txt"))]
    if not files:
        print("CRITICAL: No files found in sce_uploads. Use GitHub 'Add File' to upload.")
        sys.exit(1)

    all_results = {}
    for filename in files:
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        print(f"--- Processing: {filename} ---")
        
        if filename.endswith(".pdf"):
            with pdfplumber.open(file_path) as pdf:
                content = ""
                for page in pdf.pages: content += (page.extract_text() or "") + "\n"
        else:
            with open(file_path, 'r', encoding='utf-8') as f: content = f.read()
        
        all_results.update(extract_from_raw_text(content))

    if not all_results:
        print("FAILURE: No matches were found. Check the DEBUG lines above.")
        sys.exit(1)

    if args.dry_run:
        print("\n--- DRY RUN RESULTS ---")
        for k, v in all_results.items(): print(f"{k}: ${v}")
        sys.exit(0)

    try:
        with open(JSON_FILE, 'r') as f: data = json.load(f)
        for pid, val in all_results.items():
            if pid == "Domestic": data["plans"]["Domestic"]["summer"]["tier1"] = val
            else: data["plans"][pid]["summer"]["onPeak"] = val
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(JSON_FILE, 'w') as f: json.dump(data, f, indent=2)
        print("\nSUCCESS: JSON updated.")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
