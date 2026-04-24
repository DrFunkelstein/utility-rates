import sys
import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

ELECTRIC_URL = "https://www.ladwp.com/account/customer-service/electric-rates/residential-rates"
WATER_URL = "https://www.ladwp.com/account/customer-service/water-rates/schedule-residential"

E_PERIOD_MAP = {
    "January - March": "janMar",
    "April - May": "aprMay",
    "June": "june",
    "July - September": "julSep",
    "October - December": "octDec"
}

def extract_rates_from_row(cells, expected_count):
    """Extracts only decimal rates, ignoring integers like '2026' or tier numbers."""
    found = []
    for cell in cells:
        text = cell.get_text(strip=True).replace('$', '').replace(',', '')
        match = re.search(r"(\d+\.\d+)", text)
        if match:
            val = float(match.group(1))
            if val < 500:
                found.append(val)
    return found[:expected_count]

def scrape_table_block(soup, table_id_text, mapping, year_target="2026"):
    target_table = None
    for table in soup.find_all('table'):
        if table_id_text in table.get_text():
            target_table = table
            break
    
    if not target_table:
        return {}

    results = {}
    in_year_block = False
    
    for row in target_table.find_all('tr'):
        row_text = row.get_text(separator=' ', strip=True)
        
        if year_target in row_text:
            in_year_block = True
            continue
        elif "2025" in row_text:
            in_year_block = False
            
        if in_year_block:
            cells = row.find_all(['td', 'th'])
            for site_label, json_key in mapping.items():
                if site_label in row_text:
                    count = 4 if "Water" in table_id_text or "Consumption Charge" in table_id_text else 3
                    nums = extract_rates_from_row(cells, count)
                    if nums:
                        results[json_key] = nums
                        print(f"Match Found: {site_label} -> {json_key}: {nums}")
    return results

def main():
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    try:
        with open('ladwp_rates.json', 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Critical JSON Load Error: {e}")
        sys.exit(1)

    current_year = str(datetime.now().year)
    print(f"Targeting Year: {current_year}")

    # 1. SCRAPE ELECTRIC (5 periods)
    e_resp = requests.get(ELECTRIC_URL, headers=headers, timeout=15)
    e_soup = BeautifulSoup(e_resp.text, 'html.parser')
    r1a_data = scrape_table_block(e_soup, "R-1A", E_PERIOD_MAP, current_year)
    r1b_data = scrape_table_block(e_soup, "R-1B", E_PERIOD_MAP, current_year)

    # 2. SCRAPE WATER (2 blocks mapped to 5 periods)
    w_resp = requests.get(WATER_URL, headers=headers, timeout=15)
    w_soup = BeautifulSoup(w_resp.text, 'html.parser')
    W_SITE_MAP = {
        "January - June": "FIRST_HALF",
        "July - December": "SECOND_HALF"
    }
    water_data = scrape_table_block(w_soup, "Total Consumption Charge", W_SITE_MAP, current_year)

    total_items_found = len(r1a_data) + len(r1b_data) + len(water_data)

    if total_items_found == 0:
        print("SUBSTANTIAL FAILURE: Scraper found 0 rates in all 2026 tables.")
        print("This likely means the website structure changed or the 2026 table was removed.")
        sys.exit(1)

    updated = False

    # Apply Electric
    for p, rates in r1a_data.items():
        if len(rates) >= 3:
            data["electric"]["standard"][p] = {"tier1": rates[0], "tier2": rates[1], "tier3": rates[2]}
            updated = True
    for p, rates in r1b_data.items():
        if len(rates) >= 3:
            data["electric"]["tou"][p] = {"tier1": rates[0], "tier2": rates[1], "tier3": rates[2]}
            updated = True

    # Apply Water (Broadcast logic)
    if "FIRST_HALF" in water_data:
        r = water_data["FIRST_HALF"]
        if len(r) >= 4:
            w_obj = {"tier1": r[0], "tier2": r[1], "tier3": r[2], "tier4": r[3]}
            for p in ["janMar", "aprMay", "june"]: data["water"][p] = w_obj
            updated = True
            
    if "SECOND_HALF" in water_data:
        r = water_data["SECOND_HALF"]
        if len(r) >= 4:
            w_obj = {"tier1": r[0], "tier2": r[1], "tier3": r[2], "tier4": r[3]}
            for p in ["julSep", "octDec"]: data["water"][p] = w_obj
            updated = True

    if updated:
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        data["version"] = data.get("version", 1) + 1
        with open('ladwp_rates.json', 'w') as f:
            json.dump(data, f, indent=2)
        print("Update Successful: New data found and applied.")
    else:
        print("Status: Table found, but no new data to apply to current JSON periods.")

    sys.exit(0)

if __name__ == "__main__":
    main()            raw_rate = float(match.group(1))
            print(f"Detected raw rate from site: {raw_rate} cents")
            
            # 5. Convert Cents to Dollars (16.863 -> 0.16863)
            # We divide by 100 because the app math expects dollars
            final_rate = round(raw_rate / 100, 5)
            
            print(f"SUCCESS: Converted to ${final_rate} per therm")
            
            # 6. Update JSON
            data["procurement"] = final_rate
            data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            
            with open('socalgas_rates.json', 'w') as f:
                json.dump(data, f, indent=2)
            
            sys.exit(0) # Green light
        else:
            print(f"FAILURE: Could not find a rate entry for {month_full} {year}")
            print("This might happen if SoCalGas hasn't posted the current month yet.")
            
            # Check if we can find ANY rate at all to see if the site structure changed
            any_rate_pattern = r"[A-Z][a-z]+\s+\d{1,2},\s+20\d{2}\s+(\d+\.\d{3,5})"
            if not re.search(any_rate_pattern, full_text):
                print("CRITICAL: Scraper is blind. No rates of any date found. Site structure changed.")
                sys.exit(1) # Substantial Failure (Email Alert)
            else:
                print("Status: Found other months, but not the current one. Skipping update.")
                sys.exit(0) # Silent success (Data gap behavior)
            
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
