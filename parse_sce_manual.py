import pdfplumber
import json
import re
import os
import sys
import argparse
from datetime import datetime

# Set up global variables
UPLOAD_FOLDER = "sce_uploads"
JSON_FILE = "sce_rates.json"

# --- SCHEMA VALIDATOR ---
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
        "summer": ["tier1", "tier2"],
        "winter": ["tier1", "tier2"]
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
    domestic_tier_context = None 
    locked_bins, locked_fixed = set(), set()
    
    plan_targets = {
        "TOU-D-4": "OPTION4-9PM", 
        "TOU-D-5": "OPTION5-8PM",
        "PRIME": "OPTIONPRIME", 
        "Domestic": "SCHEDULED"
    }

    bucket_order = [
        ("SUPER-OFF-PEAK", "superOffPeak"),
        ("ON-PEAK", "onPeak"),
        ("MID-PEAK", "midPeak"),
        ("OFF-PEAK", "offPeak")
    ]

    print(f"DEBUG: Analyzing {len(lines)} lines of text...")

    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            continue
        norm = normalize(clean_line)

        # 1. FIXED CHARGES
        if "BASESERVICESCHARGE" in norm and "METER" in norm and "DAILY" not in locked_fixed:
            m = re.search(r"(\d+\.\d{3})", clean_line)
            if m: 
                fixed_values["dailyCharge"] = float(m.group(1))
                locked_fixed.add("DAILY")
                print(f"   >> FOUND BSC: {fixed_values['dailyCharge']}")

        if "BASELINECREDIT" in norm and "CREDIT" not in locked_fixed:
            m = re.search(r"(\d+\.\d{5})", clean_line)
            if m: 
                fixed_values["baselineCredit"] = float(m.group(1))
                locked_fixed.add("CREDIT")
                print(f"   >> FOUND Baseline Credit: {fixed_values['baselineCredit']}")

        # 2. PLAN DETECTION
        for plan_id, target in plan_targets.items():
            if target in norm and ("TOTAL1UG" in norm or "DELIVERYSERVICE" in norm or "DOMESTICSERVICE" in norm):
                if plan_id == "Domestic" and "TOU" in norm:
                    continue
                current_plan = plan_id
                current_season = None 
                domestic_tier_context = None
                print(f"DEBUG: Entering {current_plan} Table...")

        if not current_plan:
            continue

        # 3. SEASON & TIER DETECTION
        if "SUMMER" in norm:
            current_season = "summer"
        elif "WINTER" in norm:
            current_season = "winter"

        if current_plan == "Domestic":
            if "BASELINESERVICE" in norm and "OVER" not in norm:
                domestic_tier_context = "tier1"
            elif "OVERBASELINESERVICE" in norm:
                domestic_tier_context = "tier2"

        # 4. RATE EXTRACTION
        if current_plan == "Domestic" and domestic_tier_context and current_season:
            bin_key = f"DOM_{current_season}_{domestic_tier_context}"
            if bin_key not in locked_bins:
                rates = re.findall(r"(\d+\.\d
