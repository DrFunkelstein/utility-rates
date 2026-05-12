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

def resolve_bins(rates, plan_id):
    """
    Intelligently maps a list of found rates to the correct bins.
    Rule 1: On-Peak is always highest.
    Rule 2: Super-Off is always lowest.
    """
    # Remove duplicates (common in graphical timelines) and sort high to low
    unique_rates = sorted(list(set(rates)), reverse=True)
    
    if not unique_rates:
        return None

    # Determine if this plan needs 2 bins or 3 bins
    # 3-Bin Plans: E-ELEC, EV2-A, EV-B
    # 2-Bin Plans: E-1, E-TOU-C, E-TOU-D
    is_3_bin = any(x in plan_id for x in ["ELEC", "EV"])
    
    result = {}
    if is_3_bin and len(unique_rates) >= 3:
        result["onPeak"] = unique_rates[0]
        result["offPeak"] = unique_rates[1]
        result["superOffPeak"] = unique_rates[2]
    elif len(unique_rates) >= 2:
        result["onPeak"] = unique_rates[0]
        result["offPeak"] = unique_rates[1]
        result["superOffPeak"] = 0.0
    else:
        result["onPeak"] = unique_rates[0]
        result["offPeak"] = unique_rates[0]
        result["superOffPeak"] = 0.0
        
    return result

def parse_pge_marketing_pdf(pdf_path):
    print(f"\n[Smart Scan] Analyzing {os.path.basename(pdf_path)}...")
    
    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"
    
    # Pre-processing text
    full_text = full_text.replace("c/kWh", "¢") # Standardize labels
    
    # 1. Segment text by plan to prevent bleed-through
    segments = {
        "E-1 tiered": "Tiered Rate Plan (E-1)",
        "E-TOU-C": "Time-of-Use (E-TOU-C)",
        "E-TOU-D": "Time-of-Use (E-TOU-D)",
        "E-ELEC": "Electric Home Rate Plan (E-ELEC)",
        "EV2-A": "EV2-A",
        "EV-B": "EV-B"
    }
    
    final_data = {}
    
    # Iterate through keys to define blocks
    keys = list(segments.keys())
    for i in range(len(keys)):
        current_plan = keys[i]
        start_marker = segments[current_plan]
        
        # Find index of marker
        start_idx = full_text.find(start_marker)
        if start_idx == -1: continue
        
        # End index is start of next plan or end of text
        end_idx = len(full_text)
        if i + 1 < len(keys):
            next_marker = segments[keys[i+1]]
            found_next = full_text.find(next_marker)
            if found_next != -1: end_idx = found_next
            
        plan_chunk = full_text[start_idx:end_idx]
        
        # Split chunk into Summer and Winter
        summer_chunk = ""
        winter_chunk = ""
        
        s_marker = plan_chunk.find("Summer")
        w_marker = plan_chunk.find("Winter")
        
        if s_marker != -1 and w_marker != -1:
            if s_marker < w_marker:
                summer_chunk = plan_chunk[s_marker:w_marker]
                winter_chunk = plan_chunk[w_marker:]
            else:
                winter_chunk = plan_chunk[w_marker:s_marker]
                summer_chunk = plan_chunk[s_marker:]
        else:
            # Fallback for E-1 (No seasons in marketing text usually)
            summer_chunk = plan_chunk
            winter_chunk = plan_chunk

        # Extract rates for each season
        def get_vals(txt):
            return [float(m)/100 for m in re.findall(r"(\d+)¢", txt)]

        final_data[current_plan] = {
            "summer": resolve_bins(get_vals(summer_chunk), current_plan),
            "winter": resolve_bins(get_vals(winter_chunk), current_plan)
        }

    return final_data

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
            plan_results = seasons.get(season)
            if not plan_results: continue
            
            for b_type in ["onPeak", "offPeak", "superOffPeak"]:
                rate = plan_results.get(b_type, 0)
                if rate == 0: continue
                
                current_val = current_json["plans"][plan][season].get(b_type, 0)
                diff = abs(rate - current_val)
                status = "[MATCH]" if diff < 0.00001 else "[CHANGE DETECTED]"
                
                print(f"  {status} {plan:12} ({season:6} {b_type:12}): JSON=${current_val:.5f} | PDF=${rate:.5f}")

                # Significance threshold for marketing PDF data
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
            print("\n>>> Result: Dry Run complete. Math looks correct.")
    else:
        print("\n>>> Result: No significant changes detected.")

    if os.path.exists(tmp_pdf): os.remove(tmp_pdf)

if __name__ == "__main__":
    main()
