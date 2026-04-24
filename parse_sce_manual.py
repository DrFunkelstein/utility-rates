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
    """
    State-machine parser. Finds the Option, then finds the Summer On-Peak line,
    and sums the Delivery + Generation components to get the Total Rate.
    """
    found_data = {}
    lines = text.split('\n')
    
    current_plan = None
    
    # Mapping PDF labels to App IDs
    plan_map = {
        "Option 4-9 PM": "TOU-D-4",
        "Option 5-8 PM": "TOU-D-5",
        "Option PRIME": "TOU-D-PRIME",
        "Schedule D": "Domestic"
    }

    for line in lines:
        clean_line = line.strip()
        if not clean_line: continue

        # 1. Identify the Plan Section
        # We skip any '-CPP' lines as those are business/event rates
        for pdf_label, app_id in plan_map.items():
            if pdf_label.lower() in clean_line.lower() and "-CPP" not in clean_line.upper():
                current_plan = app_id
                print(f"DEBUG: Now scanning section for {current_plan}")

        # 2. Identify and Process the Target Rate Row
        if current_plan:
            # We look for the row containing Summer and On-Peak
            # Note: In the text dump, these are often on the same line: 
            # 'Summer Season - On-Peak 0.33082 (R) 0.25448 (R)...'
            if "Summer" in clean_line and "On-Peak" in clean_line:
                # Find all 5-decimal numbers: 0.XXXXX
                # We use a regex that handles potential leading spaces or symbols
                rates = re.findall(r"(\d+\.\d{5})", clean_line)
                
                if len(rates) >= 2:
                    # Logic: Total Rate = Delivery (index 0) + Generation (index 1)
                    delivery = float(rates[0])
                    generation = float(rates[1])
                    total_rate = round(delivery + generation, 5)
                    
                    found_data[current_plan] = total_rate
                    print(f"   >> SUCCESS: {current_plan} -> ${delivery} + ${generation} = ${total_rate}")
                    
                    # Reset plan context to avoid double-matching sub-tables
                    current_plan = None 
            
            # Special case for Domestic (Schedule D) if found in a separate file
            elif current_plan == "Domestic" and "Baseline" in clean_line and "Usage" in clean_line:
                rates = re.findall(r"(\d+\.\d{5})", clean_line)
                if rates:
                    # Domestic usually provides the pre-summed total in the last column
                    found_data[current_plan] = float(rates[-1])
                    print(f"   >> SUCCESS: Domestic Baseline -> ${found_data[current_plan]}")
                    current_plan = None

    return found_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith((".pdf", ".txt"))]
    if not files:
        print("No files found in sce_uploads. Please upload the .pdf or .txt file.")
        sys.exit(0)

    all_extracted_rates = {}

    for filename in files:
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        content = ""
        
        if filename.lower().endswith(".pdf"):
            print(f"Reading PDF: {filename}")
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    content += (page.extract_text() or "") + "\n"
        else:
            print(f"Reading Text: {filename}")
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

        all_extracted_rates.update(extract_from_raw_text(content))

    if not all_extracted_rates:
        print("CRITICAL FAILURE: No rates could be extracted. Check regex patterns.")
        sys.exit(1)

    if args.dry_run:
        print("\n--- DRY RUN COMPLETE ---")
        print("Calculated Totals:", all_extracted_rates)
        sys.exit(0)

    # Committing to JSON
    try:
        with open(JSON_FILE, 'r') as f:
            data = json.load(f)
        
        # Update matching plans in the JSON structure
        for plan_id, total in all_extracted_rates.items():
            if plan_id == "Domestic":
                data["plans"]["Domestic"]["summer"]["tier1"] = total
            else:
                data["plans"][plan_id]["summer"]["onPeak"] = total

        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(JSON_FILE, 'w') as f:
            json.dump(data, f, indent=2)
            
        print(f"\nSUCCESS: Updated {JSON_FILE} with extracted rates.")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
