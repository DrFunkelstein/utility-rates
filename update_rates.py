import sys
import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

# --- CONFIGURATION ---
ELECTRIC_URL = "https://www.ladwp.com/account/customer-service/electric-rates/residential-rates"
WATER_URL = "https://www.ladwp.com/account/customer-service/water-rates/schedule-residential"

# The site uses these two blocks for electric "Total Consumption" tables
E_SITE_PERIODS = {
    "January - June": "FIRST_HALF",
    "July - December": "SECOND_HALF"
}

W_SITE_MAP = {
    "January - June": "FIRST_HALF",
    "July - December": "SECOND_HALF"
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

# --- HELPERS ---

def extract_numbers(cells, expected_count):
    """Extracts decimals from table cells, filtering out years or zip codes."""
    found = []
    for cell in cells:
        text = cell.get_text(strip=True).replace('$', '').replace(',', '')
        # Pattern finds 0.12345 or 12.34
        match = re.search(r"(\d+\.\d+)", text)
        if match:
            val = float(match.group(1))
            if val < 500: # Exclude years/zips
                found.append(val)
    return found[:expected_count]

def find_total_consumption_table(soup, occurrence=1):
    """Finds the nth table labeled 'Total Consumption Charge'."""
    count = 0
    for table in soup.find_all('table'):
        if "Total Consumption Charge" in table.get_text():
            count += 1
            if count == occurrence:
                return table
    return None

def scrape_consumption_rates(table, year_target="2026"):
    """Parses a Consumption table for the specific year and splits into Half-Year blocks."""
    results = {}
    in_year = False
    for row in table.find_all('tr'):
        text = row.get_text(separator=' ', strip=True)
        
        # Identify the Year block
        if year_target in text:
            in_year = True
            continue
        elif any(prev_year in text for prev_year in ["2025", "2024"]):
            in_year = False
            
        if in_year:
            cells = row.find_all(['td', 'th'])
            for site_label, json_key in E_SITE_PERIODS.items():
                if site_label in text:
                    # Look for 3 rates (Tiers or Peaks)
                    nums = extract_numbers(cells, 3)
                    if nums:
                        results[json_key] = nums
    return results

def scrape_pac_table(soup):
    """Scrapes the Power Access Charge table (Table 1) into a list of tiers."""
    pac_table = None
    for table in soup.find_all('table'):
        if "Power Access Charge" in table.get_text():
            pac_table = table
            break
    
    if not pac_table: return None
    
    # We grab the charges (usually the second column)
    charges = []
    for row in pac_table.find_all('tr'):
        nums = extract_numbers(row.find_all('td'), 1)
        if nums:
            charges.append(nums[0])
    return charges

# --- MAIN ---

def main():
    try:
        with open('ladwp_rates.json', 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"JSON Load Error: {e}")
        sys.exit(1)

    current_year = str(datetime.now().year)
    print(f"Targeting Year: {current_year}")

    # 1. SCRAPE ELECTRIC (R-1A and R-1B)
    e_resp = requests.get(ELECTRIC_URL, headers=HEADERS, timeout=15)
    e_soup = BeautifulSoup(e_resp.text, 'html.parser')

    # PAC (New!)
    pac_rates = scrape_pac_table(e_soup)
    if pac_rates:
        data["electric"]["pac"] = pac_rates
        print(f"PAC Rates Found: {pac_rates}")

    # R-1A: Total Consumption is Table 3
    r1a_table = find_total_consumption_table(e_soup, occurrence=1)
    r1a_data = scrape_consumption_rates(r1a_table, current_year) if r1a_table else {}

    # R-1B: Total Consumption is Table 6
    r1b_table = find_total_consumption_table(e_soup, occurrence=2)
    r1b_data = scrape_consumption_rates(r1b_table, current_year) if r1b_table else {}

    # 2. SCRAPE WATER
    w_resp = requests.get(WATER_URL, headers=HEADERS, timeout=15)
    w_soup = BeautifulSoup(w_resp.text, 'html.parser')
    # Water typically has only one Total Consumption table
    w_table = find_total_consumption_table(w_soup, occurrence=1)
    # We use consumption rates helper, but look for 4 numbers instead of 3
    water_data = {}
    if w_table:
        in_year = False
        for row in w_table.find_all('tr'):
            text = row.get_text(strip=True)
            if current_year in text: in_year = True
            elif "2025" in text: in_year = False
            if in_year:
                cells = row.find_all(['td', 'th'])
                for label, key in W_SITE_MAP.items():
                    if label in text:
                        nums = extract_numbers(cells, 4)
                        if nums: water_data[key] = nums

    # 3. BROADCAST TO JSON
    updated = False

    def apply_elec(source_data, json_path):
        nonlocal updated
        if "FIRST_HALF" in source_data:
            r = source_data["FIRST_HALF"]
            for p in ["janMar", "aprMay", "june"]:
                data["electric"][json_path][p] = {"tier1": r[0], "tier2": r[1], "tier3": r[2]}
                updated = True
        if "SECOND_HALF" in source_data:
            r = source_data["SECOND_HALF"]
            for p in ["julSep", "octDec"]:
                data["electric"][json_path][p] = {"tier1": r[0], "tier2": r[1], "tier3": r[2]}
                updated = True

    apply_elec(r1a_data, "standard")
    apply_elec(r1b_data, "tou")

    if "FIRST_HALF" in water_data:
        r = water_data["FIRST_HALF"]
        for p in ["janMar", "aprMay", "june"]:
            data["water"][p] = {"tier1": r[0], "tier2": r[1], "tier3": r[2], "tier4": r[3]}
            updated = True
    if "SECOND_HALF" in water_data:
        r = water_data["SECOND_HALF"]
        for p in ["julSep", "octDec"]:
            data["water"][p] = {"tier1": r[0], "tier2": r[1], "tier3": r[2], "tier4": r[3]}
            updated = True

    if updated or pac_rates:
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open('ladwp_rates.json', 'w') as f:
            json.dump(data, f, indent=2)
        print("Update Successful.")
    else:
        print("No changes applied.")

if __name__ == "__main__":
    main()
