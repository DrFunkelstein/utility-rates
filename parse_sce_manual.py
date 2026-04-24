import pdfplumber
import json
import re
import os
import sys
import argparse
from datetime import datetime

UPLOAD_FOLDER = "sce_uploads"
JSON_FILE = "sce_rates.json"

# --- SCHEMA VALIDATOR ---
# This defines exactly which buckets exist for each plan/season combo
# to prevent 'ghost matches' from footnotes or other tables.
VALID_BUCKETS = {
    "TOU-D-4": {
        "summer": ["onPeak", "midPeak", "offPeak"],
        "winter": ["midPeak", "offPeak", "superOffPeak"]
    },
    "TOU-D-5": {
        "summer": ["onPeak", "midPeak", "offPeak"],
        "winter": ["midPeak", "offPeak", "superOffPeak"]
    },
    "PRIME": {
        "summer": ["onPeak", "midPeak", "offPeak"],
        "winter": ["midPeak", "offPeak", "superOffPeak"]
    },
    "Domestic": {
        "summer": ["tier1"],
        "winter": ["tier1"]
    }
}

def normalize(text):
    return re.sub(r'\s+', '', text).upper()

def extract_from_raw_text(text):
    found_data = {
        "TOU-D-4": {"summer": {}, "winter": {}},
        "TOU-D-5": {"summer": {}, "winter": {}},
        "PRIME": {"summer": {}, "winter": {}},
        "Domestic": {"summer": {}, "winter": {}}
    }
    
    fixed_values = {}
    lines = text.split('\n')
    current_plan, current_season = None, None
    locked_bins, locked_fixed = set(), set()
    
    plan_targets = {
        "TOU-D-4": "OPTION4-9PM", "TOU-D-5": "OPTION5-8PM",
        "PRIME": "OPTIONPRIME", "Domestic": "SCHEDULED"
    }

    bucket_order = [
        ("SUPER-OFF-PEAK", "superOffPeak"),
        ("ON-PEAK", "onPeak"),
        ("MID-PEAK", "midPeak"),
        ("OFF-PEAK", "offPeak")
    ]

    print(f"DEBUG: Analyzing {len(lines)} lines...")

    for line in lines:
        clean_line = line.strip()
        if not clean_line: continue
        norm = normalize(clean_line)

        # 1. FIXED CHARGES
        if "BASESERVICESCHARGE" in norm and "METER" in norm and "DAILY" not in locked_fixed:
            m = re.search(r"(\d+\.\d{3})", clean_line)
            if m: 
                fixed_values["dailyCharge"] = float(m.group(1))
                locked_fixed.add("DAILY")
        if "BASELINECREDIT" in norm and "CREDIT" not in locked_fixed:
            m = re.search(r"(\d+\.\d{5})", clean_line)
            if m: 
                fixed_values["baselineCredit"] = float(m.group(1))
                locked_fixed.add("CREDIT")

        # 2. PLAN DETECTION
        for plan_id, target in plan_targets.items():
            if target in norm and ("TOTAL1UG" in norm or "DELIVERYSERVICE" in norm):
                current_plan = plan_id
                current_season = None 

        if not current_plan: continue

        # 3. SEASON DETECTION
        if "SUMMER" in norm: current_season = "summer"
        elif "WINTER" in norm: current_season = "winter"

        # 4. RATE EXTRACTION WITH VALIDATION
        if current_plan == "Domestic":
            lock_key = "DOMESTIC_BASELINE"
            if "BASELINE" in norm and "USAGE" in norm and lock_key not in locked_bins:
                rates = re.findall(r"(\d+\.\d{5})", clean_line)
                if rates:
                    found_data["Domestic"]["summer"]["tier1"] = float(rates[-1])
                    found_data["Domestic"]["winter"]["tier1"] = float(rates[-1])
                    locked_bins.add(lock_key)
        else:
            for label, json_key in bucket_order:
                if label in norm and current_season:
                    # VALIDATION CHECK: Is this bucket allowed for this plan/season?
                    if json_key not in VALID_BUCKETS[current_plan][current_season]:
                        continue

                    lock_key = f"{current_plan}_{current_season}_{json_key}"
                    if lock_key not in locked_bins:
                        rates = re.findall(r"(\d+\.\d{5})", clean_line)
                        if len(rates) >= 2:
                            total = round(float(rates[0]) + float(rates[1]), 5)
                            found_data[current_plan][current_season][json_key] = total
                            locked_bins.add(lock_key)
                            break 

    return found_data, fixed_values

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--dry-run', action='store_true'); args = parser.parse_args()
    if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)
    files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith((".pdf", ".txt"))]
    if not files: print("No files found."); sys.exit(0)

    full_matrix, all_fixed = {}, {}
    for filename in files:
        path = os.path.join(UPLOAD_FOLDER, filename)
        content = ""
        if filename.endswith(".pdf"):
            with pdfplumber.open(path) as pdf: content = "\n".join([p.extract_text() or "" for p in pdf.pages])
        else:
            with open(path, 'r', encoding='utf-8') as f: content = f.read()
        
        rates, fixed = extract_from_raw_text(content)
        for plan, seasons in rates.items():
            if plan not in full_matrix: full_matrix[plan] = seasons
            else:
                for season, buckets in seasons.items(): full_matrix[plan][season].update(buckets)
        all_fixed.update(fixed)

    if args.dry_run:
        print("\n--- FINAL AUDITED DRY RUN RESULTS ---")
        print(json.dumps(full_matrix, indent=2)); print("Fixed Charges:", all_fixed); sys.exit(0)

    try:
        with open(JSON_FILE, 'r') as f: data = json.load(f)
        if "dailyCharge" in all_fixed: data["fixed"]["dailyCharge"] = all_fixed["dailyCharge"]
        if "baselineCredit" in all_fixed: data["fixed"]["baselineCredit"] = all_fixed["baselineCredit"]
        for pid, seasons in full_matrix.items():
            if seasons["summer"] or seasons["winter"]: data["plans"][pid] = seasons
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(JSON_FILE, 'w') as f: json.dump(data, f, indent=2)
        print(f"\nSUCCESS: Updated {JSON_FILE} with Audited Bundled Rates.")
    except Exception as e: print(f"Error: {e}"); sys.exit(1)

if __name__ == "__main__":
    main()
