import sys
import json
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
PRICING_URL = "https://www.sdge.com/residential/pricing-plans"

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
    match = re.search(r"(\d+\.\d+)", text)
    if match:
        val = float(match.group(1))
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
        # Use a high-quality User Agent to prevent bot-detection blocking
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # OPTIMIZATION: Block images and trackers to prevent timeouts
        def block_aggressively(route):
            if route.request.resource_type in ["image", "media", "font"]:
                route.abort()
            else:
                route.continue_()
        page.route("**/*", block_aggressively)

        print(f"Navigating to {PRICING_URL}...")
        try:
            # Change: wait_until="domcontentloaded" is much faster/reliable than "networkidle"
            page.goto(PRICING_URL, wait_until="domcontentloaded", timeout=45000)
            
            # Wait for a specific element that confirms the data has rendered
            print("Waiting for plan data to render...")
            page.wait_for_selector("text=TOU-DR1", timeout=15000)
            
            # Additional small buffer for the SPA to finish inflating values
            page.wait_for_timeout(3000)
            soup_text = page.inner_text("body")
        except Exception as e:
            print(f"!!! Error during page load: {e}")
            browser.close()
            sys.exit(1)

        # 2. LOAD JSON
        try:
            with open('sdge_rates.json', 'r') as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error loading sdge_rates.json: {e}")
            browser.close()
            sys.exit(1)

        updated = False
        now = datetime.now()
        # SDGE Summer: June 1 - Oct 31
        is_summer = (6 <= now.month <= 10)
        season = "summer" if is_summer else "winter"

        # 3. SCRAPE
        print(f"Scanning for {season.upper()} rates...")
        for app_id, marker in PLAN_MAP.items():
            if marker in soup_text:
                # NEW: Confirm detection
                print(f"  [Detected] Marker '{marker}' found.")
                
                start_idx = soup_text.find(marker)
                relevant_text = soup_text[start_idx : start_idx + 3500]
                
                # Find cent patterns (62.1¢)
                site_rates = re.findall(r"(\d+\.\d+¢)", relevant_text)
                
                if len(site_rates) >= 2:
                    found_vals = [extract_decimal(r) for r in site_rates]
                    if app_id not in data["plans"]: continue
                    target = data["plans"][app_id][season]
                    
                    new_on = found_vals[0]
                    # Check for updates with a 0.5 cent rounding buffer
                    if abs(target["onPeak"] - new_on) > 0.005:
                        print(f"    [UPDATE] {app_id}: {target['onPeak']} -> {new_on}")
                        target["onPeak"] = new_on
                        target["offPeak"] = found_vals[1]
                        target["superOffPeak"] = found_vals[2] if len(found_vals) >= 3 else found_vals[1]
                        updated = True
                    else:
                        # NEW: Explicitly state that data matches
                        print(f"    [MATCH] JSON value {target['onPeak']} aligns with site {new_on}")
                else:
                    print(f"    [WARN] Found marker for {app_id} but could not find rate values nearby.")
            else:
                print(f"  [MISS] Marker '{marker}' not found on page.")

        # 4. SAVE
        if updated and not dry_run:
            data["lastUpdated"] = now.strftime("%Y-%m-%d %H:%M")
            with open('sdge_rates.json', 'w') as f:
                json.dump(data, f, indent=2)
            print("\n>>> Success: sdge_rates.json updated.")
        elif updated:
            print("\n>>> Dry Run: Changes detected but not saved.")
        else:
            print("\n>>> No updates required.")

        browser.close()

if __name__ == "__main__":
    main()
