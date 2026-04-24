import requests
from bs4 import BeautifulSoup
import json
import re
import sys
from datetime import datetime

# SoCalGas Procurement Prices URL
GAS_URL = "https://www.socalgas.com/business/energy-market-services/gas-prices"

def main():
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    
    try:
        # 1. Load the existing Component-Based JSON from your repo
        with open('socalgas_rates.json', 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Critical Error: Could not load socalgas_rates.json: {e}")
        sys.exit(1)

    try:
        # 2. Fetch the Web Page
        resp = requests.get(GAS_URL, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # We clean up the text to make regex matching easier
        full_text = soup.get_text(separator=' ', strip=True).replace('&nbsp;', ' ')
        
        # 3. Identify the target month (e.g., "April 2026")
        current_marker = datetime.now().strftime("%B %Y")
        print(f"Searching for procurement rate for: {current_marker}")
        
        # 4. Extract the Procurement Rate
        # On the SoCalGas site, the rate follows the "Residential" label 
        # within the current month's section.
        if current_marker in full_text:
            # We isolate the text appearing after the current month header
            relevant_section = full_text.split(current_marker)[1]
            
            # Find the first decimal rate (0.XXXXX) following the word "Residential"
            # This avoids picking up the 'Total' or 'Transportation' numbers if they are nearby
            match = re.search(r"Residential.*?(\d+\.\d{4,6})", relevant_section, re.IGNORECASE)
            
            if match:
                new_rate = float(match.group(1))
                print(f"SUCCESS: Found current Procurement Rate: ${new_rate}")
                
                # 5. Update ONLY the procurement and timestamp
                # We do NOT touch 'transportation', 'fixed', or 'allowances'
                data["procurement"] = new_rate
                data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                
                # 6. Save the updated JSON
                with open('socalgas_rates.json', 'w') as f:
                    json.dump(data, f, indent=2)
                
                print("JSON file updated successfully.")
                sys.exit(0) # Green light for GitHub Actions
            else:
                print(f"Data Match Error: Found '{current_marker}' but couldn't parse the rate.")
                sys.exit(1) # Substantial Failure: Trigger Email Alert
        else:
            print(f"Structural Error: '{current_marker}' not found on the page. Site may have changed.")
            sys.exit(1) # Substantial Failure: Trigger Email Alert
            
    except Exception as e:
        print(f"Network or Script Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
