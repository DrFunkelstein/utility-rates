import pdfplumber
import json
import re
import os
import sys
import argparse
from datetime import datetime

UPLOAD_FOLDER = "sce_uploads"
JSON_FILE = "sce_rates.json"

def extract_from_text(text):
    """
    The core regex engine. Used for both PDF text and manual TXT uploads.
    """
    found_data = {}
    
    # We use very loose whitespace matching (\s+) because copy-pasting from 
    # PDFs often introduces weird line breaks or extra spaces.
    patterns = {
        "TOU-D-4": r"Option\s+4-9\s+PM(?!-CPP).*?Summer.*?On-Peak.*?(\d+\.\d{5})",
        "TOU-D-5": r"Option\s+5-8\s+PM(?!-CPP).*?Summer.*?On-Peak.*?(\d+\.\d{5})",
        "PRIME": r"Option\s+PRIME(?!-CPP).*?Summer.*?On-Peak.*?(\d+\.\d{5})",
        "Domestic": r"Schedule\s+D(?!-).*?Total\s+Rate.*?Baseline\s+Usage.*?(\d+\.\d{5})"
    }

    for plan_id, regex in patterns.items():
        # re.S (DOTALL) allows .* to match newlines
        match = re.search(regex, text, re.DOTALL | re.IGNORECASE)
        if match:
            found_data[plan_id] = float(match.group(1))
            print(f"FOUND: {plan_id} -> ${found_data[plan_id]}")
        else:
            print(f"MISSING: {plan_id} pattern not matched.")
            
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
        
        # --- CASE 1: PDF FILE ---
        if filename.lower().endswith(".pdf"):
            print(f"Attempting to read PDF: {filename}")
            try:
                with pdfplumber.open(file_path) as pdf:
                    pdf_text = ""
                    for page in pdf.pages:
                        # 'layout=True' helps preserve table structures even 
                        # in weirdly encoded SCE documents.
                        pdf_text += page.extract_text(layout=True) + "\n"
                    
                    all_extracted_rates.update(extract_from_text(pdf_text))
            except Exception as e:
                print(f"Error reading PDF: {e}")

        # --- CASE 2: TEXT FILE (Your manual copy-paste backup) ---
        elif filename.lower().endswith(".txt"):
            print(f"Reading manual text upload: {filename}")
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    all_extracted_rates.update(extract_from_text(f.read()))
            except Exception as e:
                print(f"Error reading text file: {e}")

    if not all_extracted_rates:
        print("CRITICAL FAILURE: No rates found in any uploaded files.")
        sys.exit(1)

    if args.dry_run:
        print("\n--- DRY RUN RESULT ---")
        print("Rates identified:", all_extracted_rates)
        sys.exit(0)

    # --- SAVE TO JSON ---
    try:
        with open(JSON_FILE, 'r') as f:
            data = json.load(f)
        
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
            
        print(f"\nSUCCESS: {JSON_FILE} updated.")
        
    except Exception as e:
        print(f"JSON Save Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
