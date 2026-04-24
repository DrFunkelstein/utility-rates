import pdfplumber
import json
import re
import os
import sys
import argparse
from datetime import datetime

UPLOAD_FOLDER = "sce_uploads"
JSON_FILE = "sce_rates.json"

def extract_rates_from_pdf(pdf_path):
    found_data = {}
    print(f"--- Parsing: {pdf_path} ---")
    
    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""
        for page in pdf.pages:
            # Clean up text by removing extra spaces to make matching more reliable
            text = page.extract_text()
            if text:
                full_text += text + "\n"

        # 1. DEFINE PATTERNS BASED ON TARIFF LANGUAGE
        # We look for the 'Option', skip any 'CPP' mentions, and find the 'Total Rate' row
        patterns = {
            "TOU-D-4": r"Option 4-9 PM(?!-CPP).*?Summer.*?On-Peak.*?(\d+\.\d{5})",
            "TOU-D-5": r"Option 5-8 PM(?!-CPP).*?Summer.*?On-Peak.*?(\d+\.\d{5})",
            "PRIME": r"Option PRIME(?!-CPP).*?Summer.*?On-Peak.*?(\d+\.\d{5})",
            # Tightened Domestic to avoid the Baseline Credit ($0.10108)
            "Domestic": r"Schedule D(?!-).*?Total Rate.*?Baseline Usage.*?(\d+\.\d{5})"
        }

        # 2. RUN EXTRACTION
        for plan_id, regex in patterns.items():
            # re.DOTALL allows the search to span multiple lines
            # re.IGNORECASE handles variances in capitalization
            match = re.search(regex, full_text, re.DOTALL | re.IGNORECASE)
            if match:
                found_data[plan_id] = float(match.group(1))
                print(f"SUCCESS: {plan_id} -> ${found_data[plan_id]}")
            else:
                print(f"PENDING: Pattern for {plan_id} not found in this file.")

    return found_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    pdfs = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith(".pdf")]
    if not pdfs:
        print("Error: No PDF found. Please upload the SCE Tariff PDF to 'sce_uploads'.")
        sys.exit(0)

    # We iterate through ALL PDFs in the folder in case TOU and Domestic are in separate files
    all_extracted_rates = {}
    for pdf_name in pdfs:
        pdf_path = os.path.join(UPLOAD_FOLDER, pdf_name)
        rates = extract_rates_from_pdf(pdf_path)
        all_extracted_rates.update(rates)

    if not all_extracted_rates:
        print("CRITICAL FAILURE: No rates could be identified in any uploaded PDFs.")
        sys.exit(1)

    if args.dry_run:
        print("\n--- DRY RUN RESULT ---")
        print("Data found:", all_extracted_rates)
        print("JSON file was NOT modified.")
        sys.exit(0)

    # 3. SAVE TO JSON
    try:
        with open(JSON_FILE, 'r') as f:
            data = json.load(f)
        
        # Update specific buckets (Summer On-Peak)
        if "TOU-D-4" in all_extracted_rates: 
            data["plans"]["TOU-D-4"]["summer"]["onPeak"] = all_extracted_rates["TOU-D-4"]
        if "TOU-D-5" in all_extracted_rates: 
            data["plans"]["TOU-D-5"]["summer"]["onPeak"] = all_extracted_rates["TOU-D-5"]
        if "PRIME" in all_extracted_rates: 
            data["plans"]["TOU-D-PRIME"]["summer"]["onPeak"] = all_extracted_rates["PRIME"]
        if "Domestic" in all_extracted_rates: 
            data["plans"]["Domestic"]["summer"]["tier1"] = all_extracted_rates["Domestic"]

        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        with open(JSON_FILE, 'w') as f:
            json.dump(data, f, indent=2)
            
        print(f"\nSUCCESS: Updated {len(all_extracted_rates)} plans in {JSON_FILE}")
        
    except Exception as e:
        print(f"Error updating JSON: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
