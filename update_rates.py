import sys
import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

# --- CONFIGURATION ---
ELECTRIC_URL = "https://www.ladwp.com/account/customer-service/electric-rates/residential-rates"
WATER_URL = "https://www.ladwp.com/account/customer-service/water-rates/schedule-residential"

# Regex patterns for matching period rows
E_PERIOD_PATTERNS = {
    r"January\s*-\s*March": "janMar",
    r"April\s*-\s*May": "aprMay",
    r"June": "june",
    r"July\s*-\s*September": "julSep",
    r"October\s*-\s*December": "octDec"
}

W_PERIOD_PATTERNS = {
    r"January\s*-\s*June": ["janMar", "aprMay", "june"],
    r"July\s*-\s*December": ["julSep", "octDec"]
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

def extract_rates(row, expected_count):
    cells = row.find_all(['td', 'th'])
    found = []
    for cell in cells:
        text = cell.get_text(strip=True).replace('$', '').replace(',', '')
        match = re.search(r"(\d+\.\d+)", text)
        if match:
            val = float(match.group(1))
            if val < 2.0 or (10.0 < val < 40.0):
                found.append(val)
    return found[:expected_count]

def scrape_section(soup, occurrence, search_text, year_target, pattern_map, is_water=False):
    count = 0
    results = {}
    for table in soup.find_all('table'):
        if search_text.lower() in table.get_text().lower():
            count += 1
            if count == occurrence:
                in_year_block = False
                for row in table.find_all('tr'):
                    row_text = row.get_text(separator=' ', strip=True)
                    
                    if year_target in row_text:
                        in_year_block = True
                    elif any(prev in row_text for prev in ["2025", "2024"]) and year_target not in row_text:
                        in_year_block = False
                    
                    if in_year_block:
                        for pattern, json_key in pattern_map.items():
                            if re.search(pattern, row_text, re.IGNORECASE):
                                expected = 4 if is_water else 3
                                nums = extract_rates(row, expected)
                                if len(nums) >= 3:
                                    results[pattern] = nums
                break
    return results

def main():
    # Detect Dry Run flag
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("--- DRY RUN MODE ACTIVE (No changes will be saved) ---")

    try:
        with open('ladwp_rates.json', 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error loading JSON: {e}")
        sys.exit(1)

    year = "2026"
    print(f"Scraping LADWP for {year}...")

    # 1. Scrape
    e_resp = requests.get(ELECTRIC_URL, headers=HEADERS, timeout=15)
    e_soup = BeautifulSoup(e_resp.text, 'html.parser')
    r1a_site_data = scrape_section(e_soup, 1, "Total Consumption Charge", year, E_PERIOD_PATTERNS)
    r1b_site_data = scrape_section(e_soup, 2, "Total Consumption Charge", year, E_PERIOD_PATTERNS)

    w_resp = requests.get(WATER_URL, headers=HEADERS, timeout=15)
    w_soup = BeautifulSoup(w_resp.text, 'html.parser')
    water_site_data = scrape_section(w_soup, 1, "Total Consumption Charge", year, W_PERIOD_PATTERNS, is_water=True)

    updated = False
    
    # 2. Compare and Stage Updates
    # Process Electric
    for site_map, json_path in [(r1a_site_data, "standard"), (r1b_site_data, "tou")]:
        for pattern, rates in site_map.items():
            json_key = E_PERIOD_PATTERNS[pattern]
            new_val = {"tier1": rates[0], "tier2": rates[1], "tier3": rates[2]}
            
            if data["electric"][json_path].get(json_key) != new_val:
                print(f"  [CHANGE] Electric {json_path}/{json_key}: {data['electric'][json_path].get(json_key)} -> {new_val}")
                data["electric"][json_path][json_key] = new_val
                updated = True
            else:
                print(f"  [NO CHANGE] Electric {json_path}/{json_key} is current.")

    # Process Water
    for pattern, rates in water_site_data.items():
        json_keys = W_PERIOD_PATTERNS[pattern]
        new_val = {"tier1": rates[0], "tier2": rates[1], "tier3": rates[2], "tier4": rates[3]}
        for k in json_keys:
            if data["water"].get(k) != new_val:
                print(f"  [CHANGE] Water/{k}: {data['water'].get(k)} -> {new_val}")
                data["water"][k] = new_val
                updated = True
            else:
                print(f"  [NO CHANGE] Water/{k} is current.")

    # 3. Save Logic
    if updated:
        if dry_run:
            print("\n>>> DRY RUN COMPLETE: Changes detected but not saved.")
        else:
            data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            data["version"] = data.get("version", 1) + 1
            with open('ladwp_rates.json', 'w') as f:
                json.dump(data, f, indent=2)
            print("\n>>> SUCCESS: ladwp_rates.json updated.")
    else:
        print("\n>>> All rates match current JSON. No update needed.")

if __name__ == "__main__":
    main()
