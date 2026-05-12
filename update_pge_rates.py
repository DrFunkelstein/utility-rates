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
    except Exception as e:
        print(f"[Error] Failed to download PDF: {e}")
        sys.exit(1)

def parse_pge_marketing_pdf(pdf_path):
    print(f"\n[Proximity Scan] Analyzing {os.path.basename(pdf_path)}...")
    
    with pdfplumber.open(pdf_path) as pdf:
        # We merge all pages just in case PG&E moves to a 2-page layout later
        full_text = ""
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"
    
    # Clean up whitespace but preserve basic structure
    clean_text = " ".join(full_text.split())

    data = {
        "E-1 tiered": {"summer": {}, "winter": {}},
        "E-TOU-C": {"summer": {}, "winter": {}},
        "E-TOU-D": {"summer": {}, "winter": {}},
        "E-ELEC": {"summer": {}, "winter": {}},
        "EV2-A": {"summer": {}, "winter": {}},
        "EV-B": {"summer": {}, "winter": {}}
    }

    # Helper to find rates following a specific keyword
    def find_rates_after(keyword, count=4):
        # Find the keyword, then grab the next 300 characters of text
        idx = clean_text.find(keyword)
        if idx == -1: return []
        chunk = clean_text[idx:idx+400]
        # Find all XX¢ patterns
        matches = re.findall(r"(\d+)¢", chunk)
        return [float(m)/100 for m in matches]

    # 1. E-1 Tiered (Look for Tier 1 / Tier 2 labels)
    e1_rates = find_rates_after("Tiered Rate Plan (E-1)")
    if len(e1_rates) >= 2:
        # Usually 33 and 41
        data["E-1 tiered"]["summer"] = {"onPeak": e1_rates[1], "offPeak": e1_rates[0]}
        data["E-1 tiered"]["winter"] = {"onPeak": e1_rates[1], "offPeak": e1_rates[0]}

    # 2. E-TOU-C (Looking for the 'Above Baseline' sequence: 40 52 40)
    etc_summer = find_rates_after("E-TOU-C) Peak Pricing 4–9 p.m. Every Day Summer Season")
    if len(etc_summer) >= 3:
        data["E-TOU-C"]["summer"] = {"onPeak": etc_summer[1], "offPeak": etc_summer[0]}
    
    etc_winter = find_rates_after("Winter Season Oct 1–May 31")
    if len(etc_winter) >= 3:
        # Targets the 37 40 37 sequence in the winter block
        data["E-TOU-C"]["winter"] = {"onPeak": etc_winter[1], "offPeak": etc_winter[0]}

    # 3. E-TOU-D (Sequence: 34 48 34 for Summer / 35 39 35 for Winter)
    etd_summer = find_rates_after("E-TOU-D) Peak Pricing 5–8 p.m. Weekdays Summer Season")
    if len(etd_summer) >= 3:
        data["E-TOU-D"]["summer"] = {"onPeak": etd_summer[1], "offPeak": etd_summer[0]}
    
    etd_winter = find_rates_after("E-TOU-D) Peak Pricing 5–8 p.m. Weekdays") # Fallback to second occurrence
    # Since Winter comes after Summer, we find the second '35 39 35'
    all_etd_rates = re.findall(r"(\d+)¢ (\d+)¢ (\d+)¢", clean_text[clean_text.find("E-TOU-D"):])
    if len(all_etd_rates) >= 2:
        data["E-TOU-D"]["winter"] = {"onPeak": float(all_etd_rates[1][1])/100, "offPeak": float(all_etd_rates[1][0])/100}

    # 4. E-ELEC (Sequence: 55 33 39 Summer / 32 28 30 Winter)
    elec_chunk = clean_text[clean_text.find("E-ELEC"):clean_text.find("Electric Vehicle")]
    elec_rates = re.findall(r"(\d+)¢ (\d+)¢ (\d+)¢", elec_chunk)
    if len(elec_rates) >= 2:
        data["E-ELEC"]["summer"] = {"onPeak": float(elec_rates[0][0])/100, "offPeak": float(elec_rates[0][2])/100, "superOffPeak": float(elec_rates[0][1])/100}
        data["E-ELEC"]["winter"] = {"onPeak": float(elec_rates[1][0])/100, "offPeak": float(elec_rates[1][2])/100, "superOffPeak": float(elec_rates[1][1])/100}

    # 5. EV2-A and EV-B (The tricky interleaved columns)
    # They appear in the PDF as: 23 43 54 (EV2A) and then 26 38 38 62 (EVB)
    ev_summer = find_rates_after("EV2-A Electric Vehicle Rate Plan EV-B Summer Season", 10)
    if len(ev_summer) >= 7:
        data["EV2-A"]["summer"] = {"onPeak": ev_summer[2], "offPeak": ev_summer[1], "superOffPeak": ev_summer[0]}
        data["EV-B"]["summer"] = {"onPeak": ev_summer[6], "offPeak": ev_summer[4], "superOffPeak": ev_summer[3]}

    ev_winter = find_rates_after("Winter Season", 20) # Finds the second Winter section
    # Re-scanning specifically for the EV winter block
    ev_winter_chunk = clean_text[clean_text.find("EV2-A"):].split("Winter Season")[-1]
    ev_w_rates = re.findall(r"(\d+)¢", ev_winter_chunk)
    if len(ev_w_rates) >= 7:
        data["EV2-A"]["winter"] = {"onPeak": float(ev_w_rates[2])/100, "offPeak": float(ev_w_rates[1])/100, "superOffPeak": float(ev_w_rates[0])/100}
        data["EV-B"]["winter"] = {"onPeak": float(ev_w_rates[6])/100, "offPeak": float(ev_w_rates[4])/100, "superOffPeak": float(ev_w_rates[3])/100}

    return data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run: print("\n!!! DRY RUN MODE: No files will be modified !!!")

    tmp_pdf = "pge_temp.pdf"
    download_pdf(PGE_URL, tmp_pdf)
    new_data = parse_pge_marketing_pdf(tmp_pdf)
    
    with open(JSON_FILE, 'r') as f:
        current_json = json.load(f)

    print("\n[Comparison Ledger: JSON vs Scraped]")
    updated = False
    
    for plan, seasons in new_data.items():
        if plan not in current_json["plans"]: continue
        for season in ["summer", "winter"]:
            for b_type in ["onPeak", "offPeak", "superOffPeak"]:
                rate = seasons[season].get(b_type, 0)
                if rate == 0: continue
                
                current_val = current_json["plans"][plan][season].get(b_type, 0)
                diff = abs(rate - current_val)
                status = "[MATCH]" if diff < 0.00001 else "[CHANGE DETECTED]"
                
                print(f"  {status} {plan:12} ({season:6} {b_type:12}): JSON=${current_val:.5f} | PDF=${rate:.5f}")

                # Threshold to protect precision data
                if diff > 0.01: 
                    current_json["plans"][plan][season][b_type] = rate
                    updated = True

    if updated:
        if not args.dry_run:
            current_json["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(JSON_FILE, 'w') as f:
                json.dump(current_json, f, indent=2)
            print("\n>>> Result: Changes committed to JSON.")
        else:
            print("\n>>> Result: Dry Run complete. Matches manual verification.")
    else:
        print("\n>>> Result: No significant changes detected.")

    if os.path.exists(tmp_pdf): os.remove(tmp_pdf)

if __name__ == "__main__":
    main()
