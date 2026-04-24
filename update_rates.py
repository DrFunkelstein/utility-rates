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

def extract_float(text):
    # This regex is now tougher: it looks for a dollar sign followed by 0.XXXXX
    match = re.search(r"\$\s*(\d+\.\d+)", text)
    if match:
        val = float(match.group(1))
        return val if val < 1.0 else None # Basic safety: rates are usually < $1.00
    return None

def scrape_electric():
    print("--- Scraping Electric Rates ---")
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(ELECTRIC_URL, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    results = {"standard": None, "tou": None}
    rows = soup.find_all('tr')
    
    s_t1, s_t2, s_t3 = None, None, None
    t_h, t_l, t_b = None, None, None

    for row in rows:
        text = row.get_text(separator=' ', strip=True)
        # Standard Parsing
        if "Tier 1" in text and "usage" in text.lower() and not s_t1:
            s_t1 = extract_float(text)
            print(f"Found Standard T1: {s_t1}")
        if "Tier 2" in text and "usage" in text.lower() and not s_t2:
            s_t2 = extract_float(text)
            print(f"Found Standard T2: {s_t2}")
        if "Tier 3" in text and "usage" in text.lower() and not s_t3:
            s_t3 = extract_float(text)
            print(f"Found Standard T3: {s_t3}")

        # TOU Parsing
        if "High-Peak" in text and not t_h:
            t_h = extract_float(text)
            print(f"Found TOU High: {t_h}")
        if "Low-Peak" in text and not t_l:
            t_l = extract_float(text)
            print(f"Found TOU Low: {t_l}")
        if "Base" in text and "period" in text.lower() and not t_b:
            t_b = extract_float(text)
            print(f"Found TOU Base: {t_b}")
    
    if s_t1: results["standard"] = {"tier1": s_t1, "tier2": s_t2 or s_t1, "tier3": s_t3 or s_t1}
    if t_h: results["tou"] = {"tier1": t_h, "tier2": t_l or t_h, "tier3": t_b or t_h}
        
    return results

def scrape_water():
    print("\n--- Scraping Water Rates ---")
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(WATER_URL, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    w_rates = []
    rows = soup.find_all('tr')
    for row in rows:
        text = row.get_text(separator=' ', strip=True)
        if "Tier" in text:
            val = extract_float(text)
            if val:
                w_rates.append(val)
                print(f"Found Water Tier: {val}")

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
        print(f"Critical: Could not load JSON: {e}")
        return

    new_e = scrape_electric()
    new_w = scrape_water()
    period = get_current_period()
    updated = False

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
        print(f"\nSUCCESS: Updated data for {period}")
    else:
        print("\nFAILED: No data was captured from the site.")

if __name__ == "__main__":
    main()
