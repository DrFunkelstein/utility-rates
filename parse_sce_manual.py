import pdfplumber
import json
import re
import os
import sys
from datetime import datetime

# Path to the folder where you will drop the PDF
UPLOAD_FOLDER = "sce_uploads"
JSON_FILE = "sce_rates.json"

def extract_rates_from_pdf(pdf_path):
    found_data = {}
    print(f"Opening {pdf_path}...")
    
    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""
        for page in pdf.pages:
            full_text += page.extract_text() + "\n"

        # Regex Strategy: SCE rates are almost always 0.XXXXX
        # We look for the plan name followed by the "Total" rates
        
        plans_to_find = {
            "TOU-D-4": r"TOU-D-4-9PM.*?Summer.*?On-Peak.*?(\d+\.\d{5})",
            "TOU-D-5": r"TOU-D-5-8PM.*?Summer.*?On-Peak.*?(\d+\.\d{5})",
            "PRIME": r"TOU-D-PRIME.*?Summer.*?On-Peak.*?(\d+\.\d{5})",
            "Domestic": r"Schedule D.*?Baseline.*?(\d+\.\d{5})"
        }

        for plan_key, pattern in plans_to_find.items():
            match = re.search(pattern, full_text, re.DOTALL)
            if match:
                found_data[plan_key] = float(match.group(1))
                print(f"Found {plan_key} Rate: {found_data[plan_key]}")

    return found_data

def main():
    # 1. Find the PDF in the upload folder
    pdfs = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith(".pdf")]
    if not pdfs:
        print("No PDF found in sce_uploads. Skipping.")
        sys.exit(0)

    pdf_path = os.path.join(UPLOAD_FOLDER, pdfs[0])

    # 2. Extract Data
    new_rates = extract_rates_from_pdf(pdf_path)
    
    if not new_rates:
        print("CRITICAL: PDF found but no rates matched the patterns.")
        sys.exit(1)

    # 3. Update JSON
    try:
        with open(JSON_FILE, 'r') as f:
            data = json.load(f)
        
        # Mapping found rates back to your JSON structure
        # (Updating Summer On-Peak as a 'tripwire' indicator)
        if "TOU-D-4" in new_rates:
            data["plans"]["TOU-D-4"]["summer"]["onPeak"] = new_rates["TOU-D-4"]
        if "PRIME" in new_rates:
            data["plans"]["TOU-D-PRIME"]["summer"]["onPeak"] = new_rates["PRIME"]
        if "Domestic" in new_rates:
            data["plans"]["Domestic"]["summer"]["tier1"] = new_rates["Domestic"]

        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        with open(JSON_FILE, 'w') as f:
            json.dump(data, f, indent=2)
            
        print("SUCCESS: JSON updated from manual PDF upload.")
        
        # 4. Optional: Remove the PDF so it doesn't process again
        os.remove(pdf_path)
        
    except Exception as e:
        print(f"Error updating JSON: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
