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
    print(f"\n[Scanning PDF Content] {os.path.basename(pdf_path)}")
    
    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"
    
    # Flatten whitespace to simplify regex across column wraps
    text = " ".join(full_text.split())

    data = {
        "E-1 tiered": {"summer": {}, "winter": {}},
        "E-TOU-C": {"summer": {}, "winter": {}},
        "E-TOU-D": {"summer": {}, "winter": {}},
        "E-ELEC": {"summer": {}, "winter": {}},
        "EV2-A": {"summer": {}, "winter": {}},
        "EV-B": {"summer": {}, "winter": {}}
    }

    # 1. E-1 TIERED
    e1 = re.search(r"Tier 1.*?(\d+)¢.*?Tier 2.*?(\d+)¢", text)
    if e1:
        rate_t1, rate_t2 = float(e1.group(1))/100, float(e1.group(2))/100
        data["E-1 tiered"]["summer"] = {"onPeak": rate_t2, "offPeak": rate_t1}
        data["E-1 tiered"]["winter"] = {"onPeak": rate_t2, "offPeak": rate_t1}

    # 2. E-TOU-C (Capture the 'Above Baseline' sequence: 40 52 40)
    etc_s = re.search(r"E-TOU-C.*?Summer Season.*?(\d+)¢ (\d+)¢ (\d+)¢", text)
    if etc_s:
        data["E-TOU-C"]["summer"] = {"onPeak": float(etc_s.group(2))/100, "offPeak": float(etc_s.group(1))/100}
    
    etc_w = re.search(r"Winter Season Oct 1–May 31 (\d+)¢ (\d+)¢ (\d+)¢", text)
    if etc_w:
        data["E-TOU-C"]["winter"] = {"onPeak": float(etc_w.group(2))/100, "offPeak": float(etc_w.group(1))/100}

    # 3. E-TOU-D (Sequence: 34 48 34 for Summer)
    etd_s = re.search(r"E-TOU-D.*?Summer Season.*?(\d+)¢ (\d+)¢ (\d+)¢", text)
    if etd_s:
        data["E-TOU-D"]["summer"] = {"onPeak": float(etd_s.group(2))/100, "offPeak": float(etd_s.group(1))/100}
    
    etd_w = re.search(r"E-TOU-D.*?Winter Season.*?(\d+)¢ (\d+)¢ (\d+)¢", text)
    if etd_w:
        data["E-TOU-D"]["winter"] = {"onPeak": float(etd_w.group(2))/100, "offPeak": float(etd_w.group(1))/100}

    # 4. E-ELEC (Sequence: 55 33 39 for Summer / 32 28 30 for Winter)
    elec_s = re.search(r"E-ELEC.*?Summer Season.*?(\d+)¢ (\d+)¢ (\d+)¢", text)
    if elec_s:
        data["E-ELEC"]["summer"] = {"onPeak": float(elec_s.group(1))/100, "offPeak": float(elec_s.group(3))/100, "superOffPeak": float(elec_s.group(2))/100}
    
    elec_w = re.search(r"E-ELEC.*?Winter Season.*?(\d+)¢ (\d+)¢ (\d+)¢", text)
    if elec_w:
        data["E-ELEC"]["winter"] = {"onPeak": float(elec_w.group(1))/100, "offPeak": float(elec_w.group(3))/100, "superOffPeak": float(elec_w.group(2))/100}

    # 5. EV2-A & EV-B (Interleaved Sequence: 23 43 54 26 38 38 62)
    ev_s = re.search(r"EV2-A.*?EV-B.*?Summer.*?Summer.*?(\d+)¢ (\d+)¢ (\d+)¢ (\d+)¢ (\d+)¢ (\d+)¢ (\d+)¢", text)
    if ev_s:
        data["EV2-A"]["summer"] = {"onPeak": float(ev_s.group(3))/100, "offPeak": float(ev_s.group(2))/100, "superOffPeak": float(ev_s.group(1))/100}
        data["EV-B"]["summer"] = {"onPeak": float(ev_s.group(7))/100, "offPeak": float(ev_s.group(5))/100, "superOffPeak": float(ev_s.group(4))/100}

    ev_w = re.search(r"EV2-A.*?EV-B.*?Winter.*?Winter.*?(\d+)¢ (\d+)¢ (\d+)¢ (\d+)¢ (\d+)¢ (\d+)¢ (\d+)¢", text)
    if ev_w:
        data["EV2-A"]["winter"] = {"onPeak": float(ev_w.group(3))/100, "offPeak": float(ev_w.group(2))/100, "superOffPeak": float(ev_w.group(1))/100}
        data["EV-B"]["winter"] = {"onPeak": float(ev_w.group(7))/100, "offPeak": float(ev_w.group(5))/100, "superOffPeak": float(ev_w.group(4))/100}

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
            print("\n>>> Result: Dry Run complete. Changes were found.")
    else:
        print("\n>>> Result: No significant changes detected.")

    if os.path.exists(tmp_pdf): os.remove(tmp_pdf)

if __name__ == "__main__":
    main()
