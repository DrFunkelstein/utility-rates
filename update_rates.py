import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

ELECTRIC_URL = "https://www.ladwp.com/account/customer-service/electric-rates/residential-rates"
WATER_URL = "https://www.ladwp.com/account/customer-service/water-rates/schedule-residential"

def get_current_period():
    month = datetime.now().month
    if 1 <= month <= 3: return "janMar"
    if 4 <= month <= 5: return "aprMay"
    if month == 6: return "june"
    if 7 <= month <= 9: return "julSep"
    return "octDec"

def extract_rate(text):
    # Aggressive search for numbers like 0.12345 or $0.12345
    # Look for a decimal starting with 0 or just the decimal point
    match = re.search(r"(\d?\.\d{3,6})", text)
    if match:
        val = float(match.group(1))
        # Logic check: Rates are rarely above $0.80 for LADWP
        return val if val < 0.85 else None
    return None

def scrape_electric():
    print("--- Scraping Electric Rates ---")
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(ELECTRIC_URL, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    results = {"standard": None, "tou": None}
    
    # LADWP Electric Logic: We look for rows that contain labels and values
    rows = soup.find_all('tr')
    
    standard_rates = {}
    tou_rates = {}

    for row in rows:
        cells = row.find_all(['td', 'th'])
        if len(cells) < 2: continue
        
        label = cells[0].get_text(strip=True)
        # Search the text of the entire row for the value
        value_text = " ".join([c.get_text(strip=True) for c in cells[1:]])
        rate = extract_rate(value_text)

        if not rate: continue

        # Standard R-1A Mapping
        if "Tier 1" in label and "usage" in label.lower(): standard_rates["tier1"] = rate
        elif "Tier 2" in label and "usage" in label.lower(): standard_rates["tier2"] = rate
        elif "Tier 3" in label and "usage" in label.lower(): standard_rates["tier3"] = rate

        # TOU R-1B Mapping
        if "High-Peak" in label: tou_rates["tier1"] = rate
        elif "Low-Peak" in label: tou_rates["tier2"] = rate
        elif "Base" in label and "Period" in label: tou_rates["tier3"] = rate

    if len(standard_rates) >= 2: 
        results["standard"] = standard_rates
        print(f"Captured Standard: {standard_rates}")
    
    if len(tou_rates) >= 2: 
        results["tou"] = tou_rates
        print(f"Captured TOU: {tou_rates}")
        
    return results

def scrape_water():
    print("\n--- Scraping Water Rates ---")
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(WATER_URL, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    w_rates = []
    # Water rates are usually in a table where Tier is in column 1
    rows = soup.find_all('tr')
    for row in rows:
        cells = row.find_all(['td', 'th'])
        if len(cells) < 2: continue
        
        row_text = row.get_text(separator=' ', strip=True)
        if "Tier" in row_text:
            rate = extract_rate(row_text)
            if rate and rate > 1.0: # Water rates are > $1.00 (per HCF)
                w_rates.append(rate)
                print(f"Found Water Tier {len(w_rates)}: {rate}")

    if len(w_rates) >= 3:
        return {
            "tier1": w_rates[0],
            "tier2": w_rates[1],
            "tier3": w_rates[2],
            "tier4": w_rates[3] if len(w_rates) > 3 else w_rates[-1]
        }
    return None

def main():
    try:
        with open('ladwp_2026.json', 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Critical Error: {e}")
        return

    period = get_current_period()
    print(f"Targeting Period: {period}")

    new_e = scrape_electric()
    new_w = scrape_water()
    updated = False

    # Update only if valid data was found
    if new_e["standard"]:
        data["electric"]["standard"][period] = new_e["standard"]
        updated = True
    if new_e["tou"]:
        data["electric"]["tou"][period] = new_e["tou"]
        updated = True
    if new_w:
        data["water"][period] = new_w
        updated = True

    if updated:
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        data["version"] = data.get("version", 1) + 1
        with open('ladwp_2026.json', 'w') as f:
            json.dump(data, f, indent=2)
        print(f"\nSUCCESS: Data updated for {period}")
    else:
        print("\nFAILED: No data was captured. Ensure URLs are correct or site hasn't changed.")

if __name__ == "__main__":
    main()
