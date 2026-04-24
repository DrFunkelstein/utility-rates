import requests
from bs4 import BeautifulSoup
import json
import re
import sys
from datetime import datetime

GAS_URL = "https://www.socalgas.com/business/energy-market-services/gas-prices"

def main():
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        with open('socalgas_rates.json', 'r') as f:
            data = json.load(f)
        
        resp = requests.get(GAS_URL, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)
        
        # Search for the "Residential" or "Core" procurement price
        # Look for the current Month/Year to ensure we aren't getting old data
        current_marker = datetime.now().strftime("%B %Y")
        
        # Find the rate (e.g. 0.12345) appearing after the current month
        pattern = re.escape(current_marker) + r".*?(\d+\.\d{4,6})"
        match = re.search(pattern, text)
        
        if match:
            new_rate = float(match.group(1))
            data["procurement"] = new_rate
            data["lastUpdated"] = datetime.now().strftime("%Y-%m-%d")
            
            with open('socalgas_rates.json', 'w') as f:
                json.dump(data, f, indent=2)
            print(f"Updated Procurement Rate to: {new_rate}")
            sys.exit(0)
        else:
            print("Structural Failure: Could not locate current procurement rate.")
            sys.exit(1)
            
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
