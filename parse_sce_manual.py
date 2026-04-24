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
    Precision extraction. Loops through lines to find specific On-Peak rows.
    """
    found_data = {}
    lines = text.split('\n')
    
    # We track which plan section we are currently reading
    current_section = None
    
    # Plan identifiers in the PDF
    sections = {
        "TOU-D-4": "Option 4-9 PM",
        "TOU-D-5": "Option 5-8 PM",
        "PRIME": "Option PRIME",
        "Domestic": "Schedule D"
    }

    for line in lines:
        # 1. Update the current section context
        for plan_id, marker in sections.items():
            if marker.lower() in line.lower() and "-CPP" not in line:
                current_section = plan_id
        
        # 2. If we are in a plan section, look for the Summer On-Peak line
        if current_section:
            # We look for lines containing 'On-Peak' and 'Summer'
            # Note: SCE sometimes puts 'Summer' on a header line above
            if "On-Peak" in line:
                # Find all 5-decimal numbers on this line
                rates = re.findall(r"(\d+\.\d{5})", line)
                if rates:
                    # RULE: The 'Total Rate' is almost always the last column
                    total_rate = float(rates[-1])
                    
                    # Safety check: On-Peak is usually > $0.40
                    if total_rate > 0.35:
                        found_data[current_section] = total_rate
                        print(f"MATCHED {current_section}: Line was '{line.strip()}' -> Found ${total_rate}")
                        # Move to next section once found
                        current_section = None 

    return found_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    files = os.listdir(UPLOAD_FOLDER)
    all_extracted_rates = {}

    for filename in files:
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        
        if filename.lower().endswith(".pdf"):
            print(f"Processing PDF: {filename}")
            with pdfplumber.open(file_path) as pdf:
                # We extract text without layout=True here to see if 
                # standard flow is cleaner for line-by-line parsing
                pdf_text = ""
                for page in pdf.pages:
                    pdf_text += page.extract_text() + "\n"
                all_extracted_rates.update(extract_from_raw_text(pdf_text))

        elif filename.lower().endswith(".txt"):
            print(f"Processing Text: {filename}")
            with open(file_path, 'r', encoding='utf-8') as f:
                all_extracted_rates.update(extract_from_raw_text(f.read()))

    if not all_extracted_rates:
        print("CRITICAL FAILURE: No rates found. Check search terms.")
        sys.exit(1)

    if args.dry_run:
        print("\n--- DRY RUN RESULT ---")
        print("Data extracted:", all_extracted_rates)
        sys.exit(0)

    # SAVE TO JSON
    try:
        with open(JSON_FILE, 'r') as f:
            data = json.load(f)
        
        if "TOU-D-4" in all_extracted_rates: data["plans"]["TOU-D-4"]["summer"]["onPeak"] = all_extracted_rates["TOU-D-4"]
        if "TOU-D-5" in all_extracted_rates: data["plans"]["TOU-D-5"]["summer"]["onPeak"] = all_extracted_rates["TOU-D-5"]
        if "PRIME" in all_extracted_rates: data["plans"]["TOU-D-PRIME"]["summer"]["onPeak"] = all_extracted_rates["PRIME"]
        if "Domestic" in all_extracted_rates: data["plans"]["Domestic"]["summer"]["tier1"] = all_extracted_rates["Domestic"]

        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(JSON_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"SUCCESS: {JSON_FILE} updated.")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
