import sys
import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

# --- CONFIGURATION ---
# SDG&E lists their "All-In" summaries on these primary landing pages
ELECTRIC_SUMMARY_URL = "https://www.sdge.com/residential/pricing-plans/time-of-use-pricing-plans"
GAS_SUMMARY_URL = "https://www.sdge.com/residential/pricing-plans/gas-pricing-plans"

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

# Mapping our App Plan IDs to the text markers on SDG&E's site
PLAN_MARKERS = {
    "TOU-DR1": "TOU-DR1",
    "TOU-DR2": "TOU-DR2",
    "TOU-ELEC": "TOU-ELEC",
    "DR-SES": "DR-SES",
    "EV-TOU-5": "EV-TOU-5",
    "EV-TOU-5-P": "EV-TOU-5-P",
    "TOU-DR-P": "TOU-DR-P",
    "Standard DR": "Standard",
    "EV-TOU": "EV-TOU"
}

def extract_decimal(text):
    """Finds the first decimal rate in a string (e.g. '$0.54123' -> 0.54123)"""
    match = re.search(r"(\d+\.\d+)", text.replace('$', ''))
    return float(match.group(1)) if match else None

def scrape_sdge_electric():
    print("--- Scraping SDG&E Electric Rates ---")
    results = {}
    try:
        resp = requests.get(ELECTRIC_SUMMARY_URL, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # SDG&E organizes plans in 'cards' or 'tables'
        # We look for the plan name and then find the rates in the immediate vicinity
        for app_id, marker in PLAN_MARKERS.items():
            plan_block = soup.find(string=re.compile(marker, re.IGNORECASE))
            if plan_block:
                # Find the next table or list containing rates
                container = plan_block.find_parent(['div', 'section'])
                rates = []
                if container:
                    for text in container.find_all(string=re.compile(r"\d+\.\d+")):
                        val = extract_decimal(text)
                        if val and 0.10 < val < 1.0: # Valid range for SDGE kWh
                            rates.append(val)
                
                if len(rates) >= 2:
                    # SDGE usually lists On-Peak then Off-Peak
                    # We broadcast these to our JSON structure
                    results[app_id] = {
                        "on": rates[0],
                        "off": rates[1],
                        "super": rates[2] if len(rates) > 2 else rates[1]
                    }
                    print(f"  [Found] {app_id}: {results[app_id]}")
                    
    except Exception as e:
        print(f"Electric Scrape Error: {e}")
    return results

def scrape_sdge_gas():
    print("--- Scraping SDG&E Gas Rates ---")
    gas_data = {}
    try:
        resp = requests.get(GAS_SUMMARY_URL, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 1. Procurement (Commodity)
        proc_match = soup.find(string=re.compile(r"Core Procurement", re.IGNORECASE))
        if proc_match:
            # Look for the price in the next <td> or <span>
            price_row = proc_match.find_parent('tr')
            val = extract_decimal(price_row.get_text()) if price_row else None
            if val:
                # SDGE often lists cents (45.123); convert to dollars
                gas_data["procurement"] = round(val / 100, 5) if val > 1.0 else val
                print(f"  [Found] Gas Procurement: ${gas_data['procurement']}")

        # 2. Transportation (Delivery)
        trans_match = soup.find(string=re.compile(r"Transportation", re.IGNORECASE))
        if trans_match:
            rates = []
            price_table = trans_match.find_parent('table')
            if price_table:
                for row in price_table.find_all('tr'):
                    val = extract_decimal(row.get_text())
                    if val and val > 0.5: # Delivery is usually $1.00+
                        rates.append(val)
            
            if len(rates) >= 2:
                gas_data["tier1"] = rates[0]
                gas_data["tier2"] = rates[1]
                print(f"  [Found] Gas Tiers: {rates[0]}, {rates[1]}")

    except Exception as e:
        print(f"Gas Scrape Error: {e}")
    return gas_data

def main():
    dry_run = "--dry-run" in sys.argv
    try:
        with open('sdge_rates.json', 'r') as f:
            data = json.load(f)
    except:
        print("Creating new sdge_rates.json structure...")
        data = {"lastUpdated": "", "nbcRate": 0.0245, "baselineCredit": 0.0872, "minimumBillDaily": 0.384, "sbpExportRate": 0.062, "plans": {}, "gas": {}}

    elec_rates = scrape_sdge_electric()
    gas_rates = scrape_sdge_gas()

    updated = False
    now = datetime.now()
    is_summer = (6 <= now.month <= 10)
    season_key = "summer" if is_summer else "winter"

    # Apply Electric
    for plan_id, rates in elec_rates.items():
        if plan_id not in data["plans"]: continue
        
        target = data["plans"][plan_id][season_key]
        if target["onPeak"] != rates["on"]:
            target["onPeak"] = rates["on"]
            target["offPeak"] = rates["off"]
            target["superOffPeak"] = rates["super"]
            updated = True

    # Apply Gas
    if "procurement" in gas_rates and data["gas"]["procurement"] != gas_rates["procurement"]:
        data["gas"]["procurement"] = gas_rates["procurement"]
        updated = True
    
    if "tier1" in gas_rates:
        data["gas"]["transportation"]["tier1"] = gas_rates["tier1"]
        data["gas"]["transportation"]["tier2"] = gas_rates["tier2"]
        updated = True

    if updated:
        if dry_run:
            print("\n>>> DRY RUN: Changes detected but not saved.")
        else:
            data["lastUpdated"] = now.strftime("%Y-%m-%d %H:%M")
            with open('sdge_rates.json', 'w') as f:
                json.dump(data, f, indent=2)
            print("\n>>> SUCCESS: sdge_rates.json updated.")
    else:
        print("\n>>> No changes needed.")

if __name__ == "__main__":
    main()
