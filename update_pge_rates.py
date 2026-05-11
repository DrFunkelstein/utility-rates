import os
import re
import json
import sys
import requests
import pdfplumber
import argparse
from datetime import datetime

# --- CONFIGURATION ---
PGE_URL = "https://www.pge.com/assets/pge/docs/account/rate-plans/residential-electric-rate-plan-pricing.pdf"
JSON_FILE = "pge_rates.json"

def download_pdf(url, save_path):
    print(f"[Network] Downloading PDF from: {url}")
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            f.write(response.content)
        print(f"[Network] Download complete ({len(response.content)} bytes)")
    except Exception as e:
        print(f"[Error] Failed to download PDF: {e}")
        sys.exit(1)

def parse_pge_marketing_pdf(pdf_path):
    print(f"\n[Scanning PDF] {os.path.basename(pdf_path)}")
    
    # Initialize data structure
    extracted_data = {
        "E-1 tiered": {"summer": {"on": 0.0}, "winter": {"on": 0.0}},
        "E-TOU-C": {"summer": {"on": 0.0, "off": 0.0}, "winter": {"on": 0.0, "off": 0.0}},
        "E-TOU-D": {"summer": {"on": 0.0, "off": 0.0}, "winter": {"on": 0.0, "off": 0.0}},
        "E-ELEC": {"summer": {"on": 0.0, "mid": 0.0, "off": 0.0}, "winter": {"on": 0.0, "mid": 0.0, "off": 0.0}},
        "EV2-A": {"summer": {"on": 0.0, "mid": 0.0, "off": 0.0}, "winter": {"on": 0.0, "mid": 0.0, "off": 0.0}},
        "EV-B": {"summer": {"on": 0.0, "mid": 0.0, "off": 0.0}, "winter": {"on": 0.0, "mid": 0.0, "off": 0.0}}
    }

    with pdfplumber.open(pdf_path) as pdf:
        for p_idx, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text: continue
            
            lines = text.split('\n')
            for line in lines:
                # Debug: Show lines that contain currency symbols to verify scraper is "seeing" them
                if "¢" in line or "c/kWh" in line.lower():
                    # print(f"  [Raw Line Scan] {line.strip()}") # Uncomment for extreme verbosity
                    
                    # Regex to find whole numbers or decimals followed by cent sign
                    cents_matches = re.findall(r"(\d+(?:\.\d+)?)¢", line)
                    if not cents_matches: continue
                    
                    val = float(cents_matches[0]) / 100
                    
                    # Logic Mapping with Verbose Feedback
                    if "Tier 1" in line and "E-1" in line:
                        print(f"    -> Matched E-1 Tier 1: {val}")
                        extracted_data["E-1 tiered"]["summer"]["on"] = val
                        extracted_data["E-1 tiered"]["winter"]["on"] = val
                    
                    elif "Peak" in line and "4–9 p.m." in line:
                        print(f"    -> Matched E-TOU-C Peak (4-9): {val}")
                        extracted_data["E-TOU-C"]["summer"]["on"] = val
                    
                    elif "Off-Peak" in line and "E-TOU-C" in line:
                        print(f"    -> Matched E-TOU-C Off-Peak: {val}")
                        extracted_data["E-TOU-C"]["summer"]["off"] = val
                        
                    elif "Electrification" in line or "E-ELEC" in line:
                        if "Peak" in line: 
                            print(f"    -> Matched E-ELEC Peak: {val}")
                            extracted_data["E-ELEC"]["summer"]["on"] = val
                    
                    elif "EV2-A" in line and "Peak" in line:
                        print(f"    -> Matched EV2-A Peak: {val}")
                        extracted_data["EV2-A"]["summer"]["on"] = val

    return extracted_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run: print("\n!!! DRY RUN MODE: No files will be modified !!!")

    tmp_pdf = "pge_temp.pdf"
    download_pdf(PGE_URL, tmp_pdf)
    new_data = parse_pge_marketing_pdf(tmp_pdf)
    
    if not os.path.exists(JSON_FILE):
        print(f"[Error] {JSON_FILE} not found in root.")
        return

    with open(JSON_FILE, 'r') as f:
        current_json = json.load(f)

    print("\n[Comparison Ledger: JSON vs Scraped]")
    updated = False
    
    for plan, seasons in new_data.items():
        if plan in current_json["plans"]:
            for season, bins in seasons.items():
                for bin_type, rate in bins.items():
                    # Align internal bin names to JSON keys
                    json_key = "onPeak"
                    if bin_type == "off": json_key = "offPeak"
                    elif bin_type == "mid": json_key = "offPeak" 

                    current_val = current_json["plans"][plan][season].get(json_key, 0)
                    
                    # Log every bin for visibility
                    status = "[MATCH]"
                    diff = abs(rate - current_val)
                    
                    if rate == 0:
                        status = "[SKIP] (Not found in PDF)"
                    elif diff > 0.00001:
                        status = "[CHANGE DETECTED]"
                    
                    print(f"  {status} {plan} ({season} {json_key}): JSON=${current_val:.5f} | PDF=${rate:.5f} | Delta=${diff:.5f}")

                    if rate > 0 and diff > 0.01: # Significant change threshold
                        current_json["plans"][plan][season][json_key] = rate
                        updated = True

    if updated:
        if not args.dry_run:
            current_json["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(JSON_FILE, 'w') as f:
                json.dump(current_json, f, indent=2)
            print("\n>>> Result: Changes committed to JSON.")
        else:
            print("\n>>> Result: Dry Run complete. Changes were found but NOT saved.")
    else:
        print("\n>>> Result: No significant changes to save.")

    if os.path.exists(tmp_pdf): os.remove(tmp_pdf)

if __name__ == "__main__":
    main()
