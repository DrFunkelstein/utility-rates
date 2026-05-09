import sys
import json
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
PRICING_URL = "https://www.sdge.com/residential/pricing-plans"

# Complete mapping for all 9 SDG&E plans supported by MeterWise
PLAN_MAP = {
    "TOU-DR1": "TOU-DR1",
    "TOU-DR2": "TOU-DR2",
    "TOU-ELEC": "TOU-ELEC",
    "DR-SES": "DR-SES",
    "EV-TOU-5": "EV-TOU-5",
    "EV-TOU-5-P": "EV-TOU-5-P",
    "TOU-DR-P": "TOU-DR-P",
    "Standard DR": "Standard DR",
    "EV-TOU": "EV-TOU"
}

def extract_decimal(text):
    """Converts cent strings like '69.6¢' to dollar floats like 0.696."""
    match = re.search(r"(\d+\.\d+)", text)
    if match:
        val = float(match.group(1))
        # If it's formatted as cents (standard on the SDGE pricing page), convert to dollars
        if '¢' in text or val > 1.0:
            return round(val / 100, 5)
        return val
    return None

def main():
    dry_run = "--dry-run" in sys.argv
    print(f"--- Starting SDG&E Playwright Scraper (Dry Run: {dry_run}) ---")

    with sync_playwright() as p:
        # 1. SETUP BROWSER
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
        page = context.new_page()
        
        print(f"Navigating to {PRICING_URL}...")
        try:
            page.goto(PRICING_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000) # Wait for SPA rendering
            soup_text = page.inner_text("body")
        except Exception as e:
            print(f"Failed to load page: {e}")
            browser.close()
            sys.exit(1)

        # 2. LOAD EXISTING DATA
        try:
            with open('sdge_rates.json', 'r') as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error: sdge_rates.json not found or invalid: {e}")
            browser.close()
            sys.exit(1)

        updated = False
        now = datetime.now()
        # SDGE Summer: June 1 - Oct 31
        is_summer = (6 <= now.month <= 10)
        season = "summer" if is_summer else "winter"

        # 3. SCRAPE LOOP
        for app_id, marker in PLAN_MAP.items():
            if marker in soup_text:
                # Find the text specific to this plan
                # We snip a larger window (3000 chars) as these sections are wordy
                start_idx = soup_text.find(marker)
                relevant_text = soup_text[start_idx : start_idx + 3000]
                
                # Look for the cent values (e.g. 62.1¢)
                site_rates = re.findall(r"(\d+\.\d+¢)", relevant_text)
                
                if len(site_rates) >= 2:
                    found_vals = [extract_decimal(r) for r in site_rates]
                    
                    # Target specific plan in JSON
                    if app_id not in data["plans"]: continue
                    target = data["plans"][app_id][season]
                    
                    # LOGIC: Map values based on Tier Count
                    # SDGE Standard (Tiered) only has 2 values. TOU has 3.
                    new_on = found_vals[0]
                    new_off = found_vals[1]
                    new_super = found_vals[2] if len(found_vals) >= 3 else found_vals[1]

                    # PRECISION BUFFER: 
                    # Only update if the delta is > 0.005 (half a cent)
                    # This protects our 5-decimal PDF values from rounding pollution
                    if abs(target["onPeak"] - new_on) > 0.005:
                        print(f"  [CHANGE DETECTED] {app_id}: {target['onPeak']} -> {new_on}")
                        target["onPeak"] = new_on
                        target["offPeak"] = new_off
                        target["superOffPeak"] = new_super
                        updated = True
                    else:
                        print(f"  [CURRENT] {app_id} matches (within rounding buffer)")
            else:
                print(f"  [SKIPPED] Marker '{marker}' not found on page.")

        # 4. SAVE RESULTS
        if updated and not dry_run:
            data["lastUpdated"] = now.strftime("%Y-%m-%d %H:%M")
            with open('sdge_rates.json', 'w') as f:
                json.dump(data, f, indent=2)
            print("\n>>> FINISH: sdge_rates.json updated successfully.")
        elif updated:
            print("\n>>> FINISH: Changes detected but not saved (Dry Run).")
        else:
            print("\n>>> FINISH: No changes detected beyond rounding buffer.")

        browser.close()

if __name__ == "__main__":
    main()
