import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

ELECTRIC_URL = "https://www.ladwp.com/account/customer-service/electric-rates/residential-rates"
WATER_URL = "https://www.ladwp.com/account/customer-service/water-rates/schedule-residential"

PERIOD_MAP = {
    "January - March": "janMar",
    "April - May": "aprMay",
    "June": "june",
    "July - September": "julSep",
    "October - December": "octDec"
}

def extract_numbers(cells):
    """Extracts all decimals from a list of table cells."""
    found = []
    for cell in cells:
        text = cell.get_text(strip=True).replace('$', '').replace(',', '')
        match = re.search(r"(\d+\.\d+)", text)
        if match:
            found.append(float(match.group(1)))
    return found

def scrape_table_block(soup, table_id_text, year_target="2026"):
    """Finds a table by text, then finds the block of data for a specific year."""
    # Find the table that contains our ID (R-1A, R-1B, etc)
    target_table = None
    for table in soup.find_all('table'):
        if table_id_text in table.get_text():
            target_table = table
            break
    
    if not target_table:
        print(f"Could not find table: {table_id_text}")
        return {}

    results = {}
    in_year_block = False
    
    for row in target_table.find_all('tr'):
        cells = row.find_all(['td', 'th'])
        if not cells: continue
        
        row_text = row.get_text(separator=' ', strip=True)
        
        # Detect if we are entering the 2026 block or leaving it (entering 2025)
        if year_target in row_text:
            in_year_block = True
            continue
        elif "2025" in row_text or "2024" in row_text:
            in_year_block = False
            
        if in_year_block:
            # Check if this row is one of our periods
            for site_label, json_key in PERIOD_MAP.items():
                if site_label in row_text:
                    nums = extract_numbers(cells)
                    if nums:
                        results[json_key] = nums
                        print(f"Found {table_id_text} {json_key}: {nums}")
    return results

def main():
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    
    try:
        with open('ladwp_2026.json', 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"JSON Load Error: {e}")
        return

    # 1. Electric Scrape
    e_resp = requests.get(ELECTRIC_URL, headers=headers, timeout=15)
    e_soup = BeautifulSoup(e_resp.text, 'html.parser')
    
    r1a_data = scrape_table_block(e_soup, "R-1A")
    r1b_data = scrape_table_block(e_soup, "R-1B")

    # 2. Water Scrape
    w_resp = requests.get(WATER_URL, headers=headers, timeout=15)
    w_soup = BeautifulSoup(w_resp.text, 'html.parser')
    water_data = scrape_table_block(w_soup, "Total Consumption Charge")

    updated = False

    # Update R-1A (Standard)
    for period, rates in r1a_data.items():
        if len(rates) >= 3:
            data["electric"]["standard"][period] = {"tier1": rates[0], "tier2": rates[1], "tier3": rates[2]}
            updated = True

    # Update R-1B (TOU)
    for period, rates in r1b_data.items():
        if len(rates) >= 3:
            data["electric"]["tou"][period] = {"tier1": rates[0], "tier2": rates[1], "tier3": rates[2]}
            updated = True

    # Update Water
    for period, rates in water_data.items():
        if len(rates) >= 4:
            data["water"][period] = {"tier1": rates[0], "tier2": rates[1], "tier3": rates[2], "tier4": rates[3]}
            updated = True

    if updated:
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        data["version"] = data.get("version", 1) + 1
        with open('ladwp_2026.json', 'w') as f:
            json.dump(data, f, indent=2)
        print("SUCCESS: JSON updated with 2026 table data.")
    else:
        print("FAILED: No 2026 data found in tables.")

if __name__ == "__main__":
    main()
