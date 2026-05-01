import sys
import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

# --- CONFIGURATION ---
ELECTRIC_URL = "https://www.ladwp.com/account/customer-service/electric-rates/residential-rates"
WATER_URL = "https://www.ladwp.com/account/customer-service/water-rates/schedule-residential"

# Standard 5-period map for Electric
E_PERIOD_MAP = {
    "January - March": "janMar",
    "April - May": "aprMay",
    "June": "june",
    "July - September": "julSep",
    "October - December": "octDec"
}

# 2-period map for Water (to be broadcasted)
W_PERIOD_MAP = {
    "January - June": ["janMar", "aprMay", "june"],
    "July - December": ["julSep", "octDec"]
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

def extract_rates(row, expected_count):
    """Extracts rates as floats, specifically looking for small decimals."""
    cells = row.find_all(['td', 'th'])
    found = []
    for cell in cells:
        text = cell.get_text(strip=True).replace('$', '').replace(',', '')
        match = re.search(r"(\d+\.\d+)", text)
        if match:
            val = float(match.group(1))
            # Rates are small decimals; this filters out ZIPs, years, or large integers
            if val < 2.0 or (val > 10.0 and val < 30.0): # 2.0 for Electric, 30.0 for Water
                found.append(val)
    return found[:expected_count]

def scrape_section(soup, occurrence, search_text, year_target, mapping, is_water=False):
    """Finds the nth table with search_text and extracts year-specific rates."""
    count = 0
    results = {}
    for table in soup.find_all('table'):
        if search_text in table.get_text():
            count += 1
            if count == occurrence:
                in_year_block = False
                for row in table.find_all('tr'):
                    row_text = row.get_text(separator=' ', strip=True)
                    
                    # Year Boundary Logic
                    if year_target in row_text:
                        in_year_block = True
                    elif any(prev in row_text for prev in ["2025", "2024", "2023"]) and year_target not in row_text:
                        in_year_block = False
                    
                    if in_year_block:
                        for site_label, json_key in mapping.items():
                            if site_label in row_text:
                                expected = 4 if is_water else 3
                                nums = extract_rates(row, expected)
                                if len(nums) >= 3:
                                    results[site_label] = nums
                                    print(f"  [Found] {year_target} {site_label}: {nums}")
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
    print(f"Scraping LADWP Total Consumption Charges for {year}...")

    # 1. ELECTRIC R-1A (Table 3)
    e_resp = requests.get(ELECTRIC_URL, headers=HEADERS, timeout=15)
    e_soup = BeautifulSoup(e_resp.text, 'html.parser')
    print("Checking R-1A (Standard)...")
    r1a_site_data = scrape_section(e_soup, 1, "Total Consumption Charge", year, E_PERIOD_MAP)

    # 2. ELECTRIC R-1B (Table 6)
    print("Checking R-1B (TOU)...")
    r1b_site_data = scrape_section(e_soup, 2, "Total Consumption Charge", year, E_PERIOD_MAP)

    # 3. WATER (Table 1)
    w_resp = requests.get(WATER_URL, headers=HEADERS, timeout=15)
    w_soup = BeautifulSoup(w_resp.text, 'html.parser')
    print("Checking Water...")
    water_site_data = scrape_section(w_soup, 1, "Total Consumption Charge", year, W_PERIOD_MAP, is_water=True)

    updated = False

    # Apply Electric Updates
    for label, keys in [ (r1a_site_data, "standard"), (r1b_site_data, "tou") ]:
        for site_label, rates in label.items():
            json_key = E_PERIOD_MAP[site_label]
            new_val = {"tier1": rates[0], "tier2": rates[1], "tier3": rates[2]}
            if data["electric"][keys].get(json_key) != new_val:
                data["electric"][keys][json_key] = new_val
                updated = True

    # Apply Water Updates (Broadcast January-June across multiple months)
    for site_label, rates in water_site_data.items():
        json_keys = W_PERIOD_MAP[site_label]
        new_val = {"tier1": rates[0], "tier2": rates[1], "tier3": rates[2], "tier4": rates[3]}
        for k in json_keys:
            if data["water"].get(k) != new_val:
                data["water"][k] = new_val
                updated = True

    if updated:
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open('ladwp_rates.json', 'w') as f:
            json.dump(data, f, indent=2)
        print(">>> SUCCESS: ladwp_rates.json updated with 2026 data.")
    else:
        print(">>> No new 2026 rates found beyond what is already in JSON.")

if __name__ == "__main__":
    main()
