import pdfplumber
import json
import re
import os
import sys
import argparse
from datetime import datetime

# Path Configuration
UPLOAD_FOLDER = "sce_uploads"
JSON_FILE = "sce_rates.json"

def extract_rates_from_pdf(pdf_path):
    found_data = {}
    print(f"--- Analyzing PDF: {pdf_path} ---")
    
    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"

        # Regex patterns for SCE Total Rates (looking for 5 decimal places)
        patterns = {
            "TOU-D-4": r"TOU-D-4-9PM.*?Summer.*?On-Peak.*?(\d+\.\d{5})",
            "TOU-D-5": r"TOU-D-5-8PM.*?Summer.*?On-Peak.*?(\d+\.\d{5})",
            "PRIME": r"TOU-D-PRIME.*?Summer.*?On-Peak.*?(\d+\.\d{5})",
            "Domestic": r"Schedule D.*?Baseline.*?(\d+\.\d{5})"
        }

    for plan, regex in patterns.items():
        match = re.search(regex, full_text, re.DOTALL)
        if match:
            found_data[plan] = float(match.group(1))
            print(f"MATCHED: {plan} -> ${found_data[plan]}")
        else:
            print(f"MISSING: Could not find pattern for {plan}")

    return found_data

def main():
    # Setup command line arguments for Dry Run
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help="Print results without saving to JSON")
    args = parser.parse_args()

    # 1. Find the PDF
    pdfs = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith(".pdf")]
    if not pdfs:
        print("No PDF found in sce_uploads. Use GitHub's 'Add File' to upload one.")
        sys.exit(0)

    pdf_path = os.path.join(UPLOAD_FOLDER, pdfs[0])

    # 2. Extract Data
    new_rates = extract_rates_from_pdf(pdf_path)
    
    if not new_rates:
        print("ERROR: No data extracted. PDF structure might have changed.")
        sys.exit(1)

    if args.dry_run:
        print("\n--- DRY RUN COMPLETE ---")
        print("Extracted values were NOT saved to sce_rates.json.")
        sys.exit(0)

    # 3. Update JSON (Only if not Dry Run)
    try:
        with open(JSON_FILE, 'r') as f:
            data = json.load(f)
        
        # Update logic based on found keys
        if "TOU-D-4" in new_rates: data["plans"]["TOU-D-4"]["summer"]["onPeak"] = new_rates["TOU-D-4"]
        if "PRIME" in new_rates: data["plans"]["TOU-D-PRIME"]["summer"]["onPeak"] = new_rates["PRIME"]
        if "Domestic" in new_rates: data["plans"]["Domestic"]["summer"]["tier1"] = new_rates["Domestic"]

        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        with open(JSON_FILE, 'w') as f:
            json.dump(data, f, indent=2)
            
        print("\nSUCCESS: sce_rates.json has been updated and saved.")
        
    except Exception as e:
        print(f"Error updating JSON: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
