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
    # We use a set to track what we've already found so we don't overwrite with 
    # garbage found later in the document
    completed_plans = set() 
    
    plan_map = {
        "Option 4-9 PM": "TOU-D-4",
        "Option 5-8 PM": "TOU-D-5",
        "Option PRIME": "TOU-D-PRIME",
        "Schedule D": "Domestic"
    }

    for line in lines:
        clean_line = line.strip()
        if not clean_line: continue

        # 1. DETECT NEW PLAN SECTION
        # We only look for a new plan if we aren't currently "locked" onto one
        if not current_plan:
            for pdf_label, app_id in plan_map.items():
                # Anchors: 
                # - Must contain the label
                # - Must NOT contain -CPP
                # - For 'Domestic', must be exactly 'Schedule D' to avoid matching 'Schedule TOU-D'
                is_match = False
                if pdf_label == "Schedule D":
                    if clean_line.startswith("Schedule D") and "TOU" not in clean_line:
                        is_match = True
                elif pdf_label in clean_line and "-CPP" not in clean_line.upper():
                    is_match = True

                if is_match and app_id not in completed_plans:
                    current_plan = app_id
                    print(f"DEBUG: Entering section for {current_plan}")
                    break

        # 2. EXTRACT DATA IF LOCKED ON A PLAN
        if current_plan:
            # Check for the correct row
            is_target_row = False
            if current_plan == "Domestic":
                if "Baseline" in clean_line and "Usage" in clean_line and "Total" in clean_line:
                    is_target_row = True
            else:
                if "Summer" in clean_line and "On-Peak" in clean_line:
                    is_target_row = True

            if is_target_row:
                # Regex finds all 5-decimal rates
                rates = re.findall(r"(\d+\.\d{5})", clean_line)
                
                if len(rates) >= 2:
                    # Logic: Total = Delivery (0) + Generation (1)
                    val = round(float(rates[0]) + float(rates[1]), 5)
                    found_data[current_plan] = val
                    print(f"   >> SUCCESS: {current_plan} Found ${val}")
                    
                    # LOCK: Mark as completed and unlock the search for the next plan
                    completed_plans.add(current_plan)
                    current_plan = None
                elif current_plan == "Domestic" and len(rates) == 1:
                    # Backup for Schedule D format
                    val = float(rates[0])
                    found_data[current_plan] = val
                    print(f"   >> SUCCESS: {current_plan} Found ${val}")
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
        print("No files found in sce_uploads.")
        sys.exit(0)

    all_results = {}
    for filename in files:
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        content = ""
        if filename.endswith(".pdf"):
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages: cont
