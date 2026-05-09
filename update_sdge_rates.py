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
    # Standardizes cent strings to dollars
    match = re.search(r"(\d+\.\d+)", text)
    if match:
        val = float(match.group(1))
        return round(val / 100, 5) if val > 1.0 else val
    return None

def main():
    dry_run = "--dry-run" in sys.argv
    print(f"--- Starting SDG&E Playwright Scraper (Dry Run: {dry_run}) ---")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 3000})
        page = context.new_page()

        print(f"Navigating to {PRICING_URL}...")
        try:
            page.goto(PRICING_URL, wait_until="domcontentloaded", timeout=60000)
            
            # 1. FORCE THE "SDG&E (BUNDLED)" VIEW
            # This ensures we get Generation + Delivery, not just Delivery.
            print("  Switching to Bundled Rates view...")
            try:
                # Target the button that contains 'SDG&E' (Bundled)
                bundled_toggle = page.get_by_text("SDG&E (Bundled)", exact=False)
                if bundled_toggle.is_visible():
                    bundled_toggle.click()
                    page.wait_for_timeout(1500)
            except:
                print("  [Note] Bundled toggle not found, assuming default view.")

            # 2. EXPAND ALL ACCORDIONS
            # Rates are often hidden behind "View pricing" or "Details" buttons.
            print("  Expanding all plan details...")
            page.evaluate("""() => {
                const buttons = Array.from(document.querySelectorAll('button, a'));
                const targets = buttons.filter(b => 
                    b.innerText.toLowerCase().includes('view details') || 
                    b.innerText.toLowerCase().includes('pricing details') ||
                    b.innerText.toLowerCase().includes('expand')
                );
                targets.forEach(t => t.click());
            }""")
            
            # Wait for expansion animations
            page.wait_for_timeout(3000)
            
            # Get the full text dump after expansion
            soup_text = page.inner_text("body")
            
        except Exception as e:
            print(f"!!! Error during page interaction: {e}")
            browser.close()
            sys.exit(1)

        # 3. LOAD JSON
        try:
            with open('sdge_rates.json', 'r') as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error loading JSON: {e}")
            browser.close()
            sys.exit(1)

        updated = False
        now = datetime.now()
        is_summer = (6 <= now.month <= 10)
        season = "summer" if is_summer else "winter"

        print(f"Scanning for {season.upper()} rates...")
        for app_id, marker in PLAN_MAP.items():
            if marker in soup_text:
                # Find the plan block
                start_idx = soup_text.find(marker)
                relevant_text = soup_text[start_idx : start_idx + 4500]
                
                # Regex Strategy: Look for numbers followed immediately by the cent sign ¢
                # This is the most reliable way to differentiate rates from years/IDs
                site_rates = re.findall(r"(\d+\.\d+)\s*¢", relevant_text)
                
                if len(site_rates) >= 2:
                    found_vals = [extract_decimal(r) for r in site_rates]
                    if app_id not in data["plans"]: continue
                    target = data["plans"][app_id][season]
                    
                    new_on = found_vals[0]
                    # Update if difference > 0.5 cents
                    if abs(target["onPeak"] - new_on) > 0.005:
                        print(f"  [UPDATE] {app_id}: {target['onPeak']} -> {new_on}")
                        target["onPeak"] = new_on
                        target["offPeak"] = found_vals[1]
                        target["superOffPeak"] = found_vals[2] if len(found_vals) >= 3 else found_vals[1]
                        updated = True
                    else:
                        print(f"  [MATCH] {app_id} aligns with site ({new_on})")
                else:
                    print(f"  [WARN] Found marker {app_id}, but no rates ending in ¢ found.")
                    # Fallback: Try range-based search if ¢ symbol is missing in text dump
                    fallback_rates = re.findall(r"(\d+\.\d+)", relevant_text)
                    filtered = [float(x) for x in fallback_rates if 5.0 < float(x) < 95.0]
                    if len(filtered) >= 2:
                        print(f"    [Fallback Success] Found decimal range for {app_id}: {filtered[:3]}")
            else:
                print(f"  [MISS] Marker '{marker}' not found on page.")

        # 4. SAVE
        if updated and not dry_run:
            data["lastUpdated"] = now.strftime("%Y-%m-%d %H:%M")
            with open('sdge_rates.json', 'r+') as f:
                json.dump(data, f, indent=2)
            print("\n>>> Success: sdge_rates.json updated.")
        elif updated:
            print("\n>>> Dry Run: Changes detected but not saved.")
        else:
            print("\n>>> No updates needed.")

        browser.close()

if __name__ == "__main__":
    main()
