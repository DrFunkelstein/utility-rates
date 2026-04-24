import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

# URLs provided
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
    # Extracts a decimal number from a string like "$0.24771/kWh"
    match = re.search(r"(\d+\.\d+)", text)
    return float(match.group(1)) if match else None

def scrape_electric():
    print("Scraping Electric Rates...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(ELECTRIC_URL, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    results = {"standard": None, "tou": None}
    
    # LADWP tables often have text identifiers in rows
    rows = soup.find_all('tr')
    
    # Logic for Standard (R-1A)
    s_t1, s_t2, s_t3 = None, None, None
    for row in rows:
        cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
        if "Tier 1" in str(cells): s_t1 = extract_float(str(cells))
        if "Tier 2" in str(cells): s_t2 = extract_float(str(cells))
        if "Tier 3" in str(cells): s_t3 = extract_float(str(cells))
    
    if s_t1 and s_t2 and s_t3:
        results["standard"] = {"tier1": s_t1, "tier2": s_t2, "tier3": s_t3}

    # Logic for TOU (R-1B)
    t_h, t_l, t_b = None, None, None
    for row in rows:
        cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
        if "High-Peak" in str(cells): t_h = extract_float(str(cells))
        if "Low-Peak" in str(cells): t_l = extract_float(str(cells))
        if "Base" in str(cells): t_b = extract_float(str(cells))
        
    if t_h and t_l and t_b:
        results["tou"] = {"tier1": t_h, "tier2": t_l, "tier3": t_b}
        
    return results

def scrape_water():
    print("Scraping Water Rates...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(WATER_URL, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    w_t1, w_t2, w_t3, w_t4 = None, None, None, None
    rows = soup.find_all('tr')
    for row in rows:
        cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
        if "Tier 1" in str(cells): w_t1 = extract_float(str(cells))
        if "Tier 2" in str(cells): w_t2 = extract_float(str(cells))
        if "Tier 3" in str(cells): w_t3 = extract_float(str(cells))
        if "Tier 4" in str(cells): w_t4 = extract_float(str(cells))
            
    if w_t1 and w_t2 and w_t3 and w_t4:
        return {"tier1": w_t1, "tier2": w_t2, "tier3": w_t3, "tier4": w_t4}
    return None

def main():
    # 1. Load existing JSON
    try:
        with open('ladwp_2026.json', 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Could not load JSON: {e}")
        return

    # 2. Scrape new data
    new_e = scrape_electric()
    new_w = scrape_water()
    period = get_current_period()

    # 3. Update Electric if successful
    updated = False
    if new_e["standard"]:
        data["electric"]["standard"][period] = new_e["standard"]
        updated = True
    if new_e["tou"]:
        data["electric"]["tou"][period] = new_e["tou"]
        updated = True

    # 4. Update Water if successful
    if new_w:
        data["water"][period] = new_w
        updated = True

    # 5. Save if changes made
    if updated:
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        data["version"] = data.get("version", 1) + 1
        with open('ladwp_2026.json', 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Successfully updated period: {period}")
    else:
        print("No updates found or scraping failed.")

if __name__ == "__main__":
    main()
