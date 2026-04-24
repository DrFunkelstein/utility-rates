import requests
from bs4 import BeautifulSoup
import json
import re
import sys
from datetime import datetime

GAS_URL = "https://www.socalgas.com/business/energy-market-services/gas-prices"

def main():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        # 1. Load your existing JSON
        with open('socalgas_rates.json', 'r') as f:
            data = json.load(f)
            
        # 2. Fetch the page
        resp = requests.get(GAS_URL, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # We get the text and preserve whitespace/tabs to catch the gap between date and rate
        full_text = soup.get_text(separator=' ')
        
        # 3. Identify the current month and year
        now = datetime.now()
        month_full = now.strftime("%B") # e.g., "April"
        year = now.strftime("%Y")       # e.g., "2026"
        
        # 4. Search for the specific pattern: "Month [Day], Year   Rate"
        # Example: "April 1, 2026 16.863"
        # The regex looks for the month name, a day, the year, and then the decimal number
        pattern = rf"{month_full}\s+\d{{1,2}},\s+{year}\s+(\d+\.\d{{3,5}})"
        match = re.search(pattern, full_text)
        
        if match:
            raw_rate = float(match.group(1))
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
