import sys
import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

# --- CONFIGURATION ---
ELECTRIC_URL = "https://www.ladwp.com/account/customer-service/electric-rates/residential-rates"
WATER_URL = "https://www.ladwp.com/account/customer-service/water-rates/schedule-residential"

# Regex patterns for matching period rows (flexible on spaces and dashes)
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
            # Filter: Electric rates (~0.20), Water rates (~15.00)
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
                                    print(f"  [Found] {year_target} Match: {nums}")
                break
    return results

def main():
    try:
        with open('ladwp_rates.json', 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error loading JSON: {e}")
        sys.exit(1)

    year = "2026"
    print(f"Scraping LADWP for {year}...")

    # 1. ELECTRIC R-1A (Standard)
    e_resp = requests.get(ELECTRIC_URL, headers=HEADERS, timeout=15)
    e_soup = BeautifulSoup(e_resp.text, 'html.parser')
    print("Checking R-1A (Standard)...")
    r1a_site_data = scrape_section(e_soup, 1, "Total Consumption Charge", year, E_PERIOD_PATTERNS)

    # 2. ELECTRIC R-1B (TOU)
    print("Checking R-1B (TOU)...")
    r1b_site_data = scrape_section(e_soup, 2, "Total Consumption Charge", year, E_PERIOD_PATTERNS)

    # 3. WATER
    w_resp = requests.get(WATER_URL, headers=HEADERS, timeout=15)
    w_soup = BeautifulSoup(w_resp.text, 'html.parser')
    print("Checking Water...")
    water_site_data = scrape_section(w_soup, 1, "Total Consumption Charge", year, W_PERIOD_PATTERNS, is_water=True)

    updated = False

    # Apply Electric Updates
    for site_map, json_path in [(r1a_site_data, "standard"), (r1b_site_data, "tou")]:
        for pattern, rates in site_map.items():
            json_key = E_PERIOD_PATTERNS[pattern]
            new_val = {"tier1": rates[0], "tier2": rates[1], "tier3": rates[2]}
            if data["electric"][json_path].get(json_key) != new_val:
                data["electric"][json_path][json_key] = new_val
                updated = True

    # Apply Water Updates
    for pattern, rates in water_site_data.items():
        json_keys = W_PERIOD_PATTERNS[pattern]
        new_val = {"tier1": rates[0], "tier2": rates[1], "tier3": rates[2], "tier4": rates[3]}
        for k in json_keys:
            if data["water"].get(k) != new_val:
                data["water"][k] = new_val
                updated = True

    if updated:
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open('ladwp_rates.json', 'w') as f:
            json.dump(data, f, indent=2)
        print(">>> SUCCESS: ladwp_rates.json updated.")
    else:
        print(">>> No new rates found.")

if __name__ == "__main__":
    main()
