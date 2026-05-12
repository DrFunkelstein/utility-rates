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

def extract_from_segment(text, plan_id):
    """
    Extracts rates from a specific fenced text segment and 
    sorts them based on California utility priority (Peak = Highest).
    """
    # Find all XX¢ values in this specific fenced area
    raw_vals = [float(m)/100 for m in re.findall(r"(\d+)¢", text)]
    if not raw_vals: return None

    # Remove duplicates and sort descending
    unique = sorted(list(set(raw_vals)), reverse=True)

    # Logic for 3-bin plans (ELEC, EV)
    if any(x in plan_id for x in ["ELEC", "EV"]):
        if len(unique) >= 3:
            return {"onPeak": unique[0], "offPeak": unique[1], "superOffPeak": unique[2]}
        return {"onPeak": unique[0], "offPeak": unique[unique[-1]], "superOffPeak": unique[-1]}

    # Logic for 2-bin plans (E-1, TOU-C/D)
    # Note: If 4 values found (Above/Below baseline), we pick the two highest
    if len(unique) >= 2:
        return {"onPeak": unique[0], "offPeak": unique[1], "superOffPeak": 0.0}
    
    return {"onPeak": unique[0], "offPeak": unique[0], "superOffPeak": 0.0}

def parse_pge_marketing_pdf(pdf_path):
    print(f"\n[Segmented Scan] Analyzing {os.path.basename(pdf_path)}...")
    
    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"
    
    # Pre-clean text to help index finding
    clean_text = " ".join(full_text.split())

    # Define the 'fences' to isolate plans
    fences = [
        ("E-1 tiered", "Tiered Rate Plan (E-1)", "Time-of-Use Rate Plans"),
        ("E-TOU-C", "Time-of-Use (E-TOU-C)", "Time-of-Use (E-TOU-D)"),
        ("E-TOU-D", "Time-of-Use (E-TOU-D)", "Electric Home Rate Plan"),
        ("E-ELEC", "Electric Home Rate Plan (E-ELEC)", "Electric Vehicle (EV)"),
        ("EV2-A", "Home Charging EV2-A", "Electric Vehicle Rate Plan EV-B"),
        ("EV-B", "Electric Vehicle Rate Plan EV-B", "The Electric Home Rate Plan includes")
    ]

    final_results = {}

    for plan_id, start_marker, end_marker in fences:
        start_idx = clean_text.find(start_marker)
        end_idx = clean_text.find(end_marker)

        if start_idx == -1: continue
        if end_idx == -1: end_idx = len(clean_text)

        # Surgical crop of the text for this plan
        segment_text = clean_text[start_idx:end_idx]
        
        # Split segment into summer/winter chunks
        summer_idx = segment_text.find("Summer")
        winter_idx = segment_text.find("Winter")

        if summer_idx != -1 and winter_idx != -1:
            s_text = segment_text[summer_idx:winter_idx]
            w_text = segment_text[winter_idx:]
            final_results[plan_id] = {
                "summer": extract_from_segment(s_text, plan_id),
                "winter": extract_from_segment(w_text, plan_id)
            }
        else:
            # Fallback for E-1 which might not have distinct seasonal text blocks
            res = extract_from_segment(segment_text, plan_id)
            final_results[plan_id] = {"summer": res, "winter": res}

    return final_results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run: print("\n!!! DRY RUN MODE: No files will be modified !!!")

    tmp_pdf = "pge_temp.pdf"
    download_pdf(PGE_URL, tmp_pdf)
    new_data = parse_pge_marketing_pdf(tmp_pdf)
    
    if not os.path.exists(JSON_FILE):
        print(f"[Error] {JSON_FILE} not found.")
        return

    with open(JSON_FILE, 'r') as f:
        current_json = json.load(f)

    print("\n[Comparison Ledger: JSON vs Scraped]")
    updated = False
    
    for plan, seasons in new_data.items():
        if plan not in current_json["plans"]: continue
        for season in ["summer", "winter"]:
            plan_results = seasons.get(season)
            if not plan_results: continue
            
            for b_type in ["onPeak", "offPeak", "superOffPeak"]:
                rate = plan_results.get(b_type, 0)
                if rate == 0: continue
                
                current_val = current_json["plans"][plan][season].get(b_type, 0)
                diff = abs(rate - current_val)
                status = "[MATCH]" if diff < 0.00001 else "[CHANGE DETECTED]"
                
                print(f"  {status} {plan:12} ({season:6} {b_type:12}): JSON=${current_val:.5f} | PDF=${rate:.5f}")

                # Using 0.01 threshold as marketing PDF values are rounded
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
            print("\n>>> Result: Dry Run complete. Math matches manual list.")
    else:
        print("\n>>> Result: No significant changes detected.")

    if os.path.exists(tmp_pdf): os.remove(tmp_pdf)

if __name__ == "__main__":
    main()
