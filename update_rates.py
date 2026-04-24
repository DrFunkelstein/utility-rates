import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

ELECTRIC_URL = "https://www.ladwp.com/account/customer-service/electric-rates/residential-rates"
WATER_URL = "https://www.ladwp.com/account/customer-service/water-rates/schedule-residential"

def get_current_period():
    month = datetime.now().month
    if 1 <= month <= 3: return "janMar", "January - March"
    if 4 <= month <= 5: return "aprMay", "April - May"
    if month == 6: return "june", "June"
    if 7 <= month <= 9: return "julSep", "July - September"
    return "octDec", "October - December"

def extract_all_rates(text, marker, count=3):
    # Finds the marker (e.g. 'April - May') and extracts the next 'count' decimal numbers
    # Pattern looks for numbers like 0.12345 or 12.345
    pattern = rf"{re.escape(marker)}\s*" + r"\s*".join([r"(\d+\.\d+)"] * count)
    match = re.search(pattern, text)
    if match:
        return [float(g) for g in match.groups()]
    return None

def scrape_data():
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    period_key, site_marker = get_current_period()
    print(f"Targeting Period: {period_key} (Searching for '{site_marker}')")

    results = {"standard": None, "tou": None, "water": None}

    # 1. SCRAPE ELECTRIC
    try:
        e_resp = requests.get(ELECTRIC_URL, headers=headers, timeout=15)
        e_text = e_resp.text.replace('&nbsp;', ' ')
        soup_e = BeautifulSoup(e_text, 'html.parser')
        full_text_e = soup_e.get_text(separator=' ')

        # Find R-1A section
        if "R-1A" in full_text_e:
            rates = extract_all_rates(full_text_e, site_marker, 3)
            if rates:
                results["standard"] = {"tier1": rates[0], "tier2": rates[1], "tier3": rates[2]}
                print(f"Found Standard Rates: {rates}")

        # Find R-1B section
        if "R-1B" in full_text_e:
            # We look specifically after the R-1B header to avoid double-matching Standard
            tou_section = full_text_e.split("R-1B")[1]
            rates = extract_all_rates(tou_section, site_marker, 3)
            if rates:
                results["tou"] = {"tier1": rates[0], "tier2": rates[1], "tier3": rates[2]}
                print(f"Found TOU Rates: {rates}")
    except Exception as e:
        print(f"Electric Scrape Error: {e}")

    # 2. SCRAPE WATER
    try:
        w_resp = requests.get(WATER_URL, headers=headers, timeout=15)
        w_text = w_resp.text.replace('&nbsp;', ' ')
        soup_w = BeautifulSoup(w_text, 'html.parser')
        full_text_w = soup_w.get_text(separator=' ')

        # Water period is wider (Jan-Jun or Jul-Dec)
        water_marker = "January - June" if datetime.now().month <= 6 else "July - December"
        w_rates = extract_all_rates(full_text_w, water_marker, 4)
        if w_rates:
            results["water"] = {"tier1": w_rates[0], "tier2": w_rates[1], "tier3": w_rates[2], "tier4": w_rates[3]}
            print(f"Found Water Rates for {water_marker}: {w_rates}")
    except Exception as e:
        print(f"Water Scrape Error: {e}")

    return results, period_key

def main():
    try:
        with open('ladwp_2026.json', 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Critical JSON Load Error: {e}")
        return

    new_data, period = scrape_data()
    updated = False

    if new_data["standard"]:
        data["electric"]["standard"][period] = new_data["standard"]
        updated = True
    if new_data["tou"]:
        data["electric"]["tou"][period] = new_data["tou"]
        updated = True
    if new_data["water"]:
        # Update water for current and all sub-periods in that half-year
        sub_periods = ["janMar", "aprMay", "june"] if datetime.now().month <= 6 else ["julSep", "octDec"]
        for p in sub_periods:
            data["water"][p] = new_data["water"]
        updated = True

    if updated:
        data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        data["version"] = data.get("version", 1) + 1
        with open('ladwp_2026.json', 'w') as f:
            json.dump(data, f, indent=2)
        print(f"\nSUCCESS: Data committed to JSON for period: {period}")
    else:
        print("\nFAILED: No data was matched. The site text format may have changed.")

if __name__ == "__main__":
    main()
