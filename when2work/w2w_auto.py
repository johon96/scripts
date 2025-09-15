#!/usr/bin/env python3
"""
w2w_auto.py - updated

Fixes:
 - Correct iteration over pattern slots (lists)
 - Uses per-day popup when available to add ranges/dislikes and save there
 - Fallback to main-grid clicks if popup doesn't open, then saves main page
 - Handles 00:00 end-of-day as midnight
"""
import os
import time
import datetime
import re
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException

# --- Load credentials ---
load_dotenv()
W2W_EMAIL = os.getenv("W2W_EMAIL")
W2W_PASSWORD = os.getenv("W2W_PASSWORD")
if not W2W_EMAIL or not W2W_PASSWORD:
    raise SystemExit("Please set W2W_EMAIL and W2W_PASSWORD in a .env file.")

# === CONFIG ===
START_DATE = datetime.date(2025, 11, 23)
WEEKS_TO_UPDATE = 2
MAX_NAV_CLICK = 60

PATTERN = {
    "week1": {
        "sunday": ["dislike"],
        "monday": ["dislike"],
        "tuesday": ["dislike"],
        "wednesday": ["dislike"],
        "thursday": ["19:00-23:59"],
        "friday": ["00:00-07:30", "19:00-23:59"],
        "saturday": ["00:00-07:30", "19:00-23:59"]
    },
    "week2": {
        "sunday": ["00:00-07:30"],
        "tuesday": ["19:00-23:59"],
        "wednesday": ["00:00-07:30", "19:00-23:59"],
        "thursday": ["00:00-07:30", "19:00-23:59"],
        "friday": ["00:00-07:30"],
        "saturday": ["dislike"]
    }
}

# --- Selenium helper ---
def get_driver(headless=False):
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    return webdriver.Chrome(service=Service(), options=opts)

# --- Login ---
def login(driver):
    driver.get("https://www.whentowork.com/logins.htm")
    WebDriverWait(driver, 15).until(
        lambda d: d.find_elements(By.ID, "email") or d.find_elements(By.ID, "username")
    )

    if driver.find_elements(By.ID, "email"):
        driver.find_element(By.ID, "email").clear()
        driver.find_element(By.ID, "email").send_keys(W2W_EMAIL)
    else:
        driver.find_element(By.ID, "username").clear()
        driver.find_element(By.ID, "username").send_keys(W2W_EMAIL)

    driver.find_element(By.ID, "password").clear()
    driver.find_element(By.ID, "password").send_keys(W2W_PASSWORD)

    sign_in_btn = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.XPATH, "//button[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'SIGN IN')]"))
    )
    driver.execute_script("arguments[0].click();", sign_in_btn)

    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.XPATH, "//td[contains(@onclick, 'emppreferences.htm')]"))
    )
    print("✅ Logged in and dashboard detected.")

# --- Go to Preferences ---
def go_to_preferences(driver):
    prefs_td = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.XPATH, "//td[contains(@onclick, 'emppreferences.htm')]"))
    )
    driver.execute_script("arguments[0].click();", prefs_td)

    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "PrefTable")))
    except TimeoutException:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "shiftPrefsTable")))
    print("✅ Preferences page loaded.")

# --- Parse ndThisWeek text to a date ---
def parse_ndThisWeek_to_date(text):
    text = text.strip()
    m = re.search(r'([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})', text)
    if m:
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.datetime.strptime(m.group(1), fmt).date()
            except ValueError:
                pass
    m = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', text)
    if m:
        return datetime.datetime.strptime(m.group(1), "%m/%d/%Y").date()
    m = re.search(r'(\d{4}-\d{2}-\d{2})', text)
    if m:
        return datetime.datetime.strptime(m.group(1), "%Y-%m-%d").date()
    raise ValueError(f"Could not parse date from '{text}'")

# --- Navigate calendar to specific week ---
def navigate_to_week(driver, week_start_date, max_clicks=MAX_NAV_CLICK):
    WebDriverWait(driver, 15).until(lambda d: d.find_element(By.ID, "ndThisWeek"))
    clicks = 0
    while clicks < max_clicks:
        nd_text = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "ndThisWeek"))).text.strip()
        current_date = parse_ndThisWeek_to_date(nd_text)
        print(f"[nav] displayed: '{nd_text}' -> {current_date} | target: {week_start_date}")
        if current_date == week_start_date:
            print(f"✅ Reached target week {week_start_date} after {clicks} clicks.")
            return
        btn_id = "ndNextWeek" if current_date < week_start_date else "ndPrevWeek"
        btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, btn_id)))
        prior = nd_text
        driver.execute_script("arguments[0].click();", btn)
        try:
            WebDriverWait(driver, 10).until(lambda d: d.find_element(By.ID, "ndThisWeek").text.strip() != prior)
        except Exception:
            time.sleep(0.6)
        clicks += 1
    raise RuntimeError(f"Failed to navigate to {week_start_date} within {max_clicks} clicks.")

# --- Time to slot index used for main-grid fallback (not used when popup is available) ---
def time_to_slot_index(tstr):
    h, m = map(int, tstr.split(":"))
    return (h * 4) + (m // 15)

# --- Core: set preferences for currently displayed week ---
def set_week_preferences_on_current_week(driver, week_start_date, week_type, pattern):
    # Ensure the PrefTable (or equivalent) is present
    try:
        WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.ID, "PrefTable")))
        grid_id = "PrefTable"
    except TimeoutException:
        WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.ID, "shiftPrefsTable")))
        grid_id = "shiftPrefsTable"

    print(f"🛠 Setting preferences for {week_start_date} ({week_type})...")

    days_map = {
        "sunday": "Sun",
        "monday": "Mon",
        "tuesday": "Tue",
        "wednesday": "Wed",
        "thursday": "Thu",
        "friday": "Fri",
        "saturday": "Sat",
    }

    main_page_changed = False

    for day_name, slots in pattern[week_type].items():
        day_abbr = days_map[day_name.lower()]
        row_xpath = f"//tr[th[contains(normalize-space(.), '{day_abbr}')]]"
        day_header_xpath = f"{row_xpath}/th"

        # Remember window handles before clicking
        orig_handles = driver.window_handles[:]

        # Try opening the day popup by clicking the header cell
        try:
            day_header = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, day_header_xpath)))
            driver.execute_script("arguments[0].click();", day_header)
            # short delay to let popup open
            time.sleep(0.35)
        except Exception as e:
            print(f"⚠️ Could not click header for {day_name}: {e}")
            # continue to fallback behavior
        # If a popup opened, it'll be a new window handle
        if len(driver.window_handles) > len(orig_handles):
            # switch to popup
            popup_handle = [h for h in driver.window_handles if h not in orig_handles][-1]
            driver.switch_to.window(popup_handle)
            try:
                # Wait for popup form
                WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.NAME, "MainForm")))
            except TimeoutException:
                # popup didn't fully load -> close and fallback
                driver.close()
                driver.switch_to.window(orig_handles[0])
                print(f"⚠️ Popup for {day_name} didn't load; falling back to main-grid clicks.")
                # fallback will be used below
                popup_loaded = False
            else:
                popup_loaded = True

            if popup_loaded:
                try:
                    # clear existing preferences? (optional)
                    # Add each slot in the popup, then select Repeat=2 and Save
                    for slot in slots:
                        if slot.lower() == "dislike":
                            # Select Dislike radio (name=V1 value=D)
                            try:
                                dislike_radio = WebDriverWait(driver, 4).until(
                                    EC.element_to_be_clickable((By.XPATH, "//input[@name='V1' and (@value='D' or @value='d')]"))
                                )
                                dislike_radio.click()
                            except Exception:
                                # fallback: try any radio with label Dislike
                                try:
                                    driver.find_element(By.XPATH, "//label[contains(., 'Dislike')]/input").click()
                                except Exception:
                                    pass
                            # set full-day range: 00:00 -> 23:45
                            Select(driver.find_element(By.NAME, "SH")).select_by_value("0")
                            Select(driver.find_element(By.NAME, "SM")).select_by_value("0")
                            Select(driver.find_element(By.NAME, "EH")).select_by_value("23")
                            Select(driver.find_element(By.NAME, "EM")).select_by_value("3")
                            # click Add
                            driver.find_element(By.NAME, "B3").click()
                            time.sleep(0.25)
                            # when whole-day dislike, skip other slots for that day
                            break
                        else:
                            # parse start/end
                            start_str, end_str = slot.split("-")
                            sh, sm = map(int, start_str.split(":"))
                            eh, em = map(int, end_str.split(":"))
                            # handle end == 00:00 as midnight -> set to 23:45 on this day's popup
                            if end_str == "00:00" or (eh * 60 + em) <= (sh * 60 + sm):
                                # treat as till midnight for this day
                                eh = 23
                                em = 45
                            # Select Prefer (value='P') for a preferred shift (use 'P' based on HTML)
                            try:
                                like_radio = WebDriverWait(driver, 3).until(
                                    EC.element_to_be_clickable((By.XPATH, "//input[@name='V1' and (@value='P' or @value='p')]"))
                                )
                                like_radio.click()
                            except Exception:
                                # If 'P' isn't present, try 'L' or fallback to first radio
                                try:
                                    driver.find_element(By.XPATH, "//input[@name='V1' and (@value='L' or @value='l')]").click()
                                except Exception:
                                    radios = driver.find_elements(By.XPATH, "//input[@name='V1']")
                                    if radios:
                                        radios[0].click()
                            # set SH/SM/EH/EM using Select
                            Select(driver.find_element(By.NAME, "SH")).select_by_value(str(sh))
                            Select(driver.find_element(By.NAME, "SM")).select_by_value(str(sm // 15))
                            Select(driver.find_element(By.NAME, "EH")).select_by_value(str(eh))
                            Select(driver.find_element(By.NAME, "EM")).select_by_value(str(em // 15))
                            # click Add
                            driver.find_element(By.NAME, "B3").click()
                            time.sleep(0.2)

                    # Set Repeat to every 2 weeks if selector exists
                    try:
                        Select(driver.find_element(By.NAME, "Repeat")).select_by_value("1")
                    except Exception:
                        pass

                    # Click Save (name=B4)
                    try:
                        save_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.NAME, "B4")))
                        save_btn.click()
                    except Exception:
                        # final attempt using any button containing 'Save'
                        try:
                            driver.find_element(By.XPATH, "//input[@value='Save' or @value='SAVE' or contains(., 'Save')]").click()
                        except Exception:
                            pass

                    # wait for popup to close
                    WebDriverWait(driver, 10).until(EC.number_of_windows_to_be(1))
                    driver.switch_to.window(orig_handles[0])
                    print(f"   ✅ Saved preferences for {day_name} via popup.")
                except Exception as e:
                    # ensure popup closed
                    try:
                        if len(driver.window_handles) > 1:
                            driver.close()
                            driver.switch_to.window(orig_handles[0])
                    except Exception:
                        pass
                    print(f"   ❌ Error while setting popup prefs for {day_name}: {e}")
        else:
            # Popup didn't open -> fallback to main-grid cell clicks (paint)
            # We'll click the cells for each slot on the main grid and mark that we've changed main page
            for slot in slots:
                if slot.lower() == "dislike":
                    # click header to toggle all-day on main grid
                    try:
                        day_header = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, day_header_xpath)))
                        driver.execute_script("arguments[0].click();", day_header)
                        main_page_changed = True
                        print(f"   🚫 Marked DISLIKE for {day_name} (main-grid fallback).")
                    except Exception as e:
                        print(f"   ⚠ Failed to mark DISLIKE for {day_name} on main grid: {e}")
                    break
                else:
                    # paint on main grid by clicking the appropriate cells
                    start_str, end_str = slot.split("-")
                    start_idx = time_to_slot_index(start_str)
                    end_idx = time_to_slot_index(end_str)
                    if end_idx <= start_idx:
                        # treat as through midnight -> up to midnight
                        end_idx = 96
                    for slot_idx in range(start_idx, end_idx):
                        cell_xpath = f"({row_xpath}/td)[{slot_idx + 1}]"
                        try:
                            cell = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((By.XPATH, cell_xpath)))
                            driver.execute_script("arguments[0].click();", cell)
                            main_page_changed = True
                            time.sleep(0.03)
                        except Exception:
                            # ignore individual cell failures
                            pass
            print(f"   ℹ Completed main-grid changes for {day_name} (fallback).")

    # If we touched the main grid (fallback path), save main preferences once
    if main_page_changed:
        try:
            save_btn = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Save Preferences') or contains(., 'Save')]"))
            )
            driver.execute_script("arguments[0].click();", save_btn)
            # small wait for server side
            time.sleep(0.8)
            print(f"✅ Saved main-grid preferences for week of {week_start_date}.")
        except Exception as e:
            print(f"❌ Failed to save main-grid preferences for {week_start_date}: {e}")

# --- week type ---
def get_week_type(target_date):
    delta_days = (target_date - START_DATE).days
    if delta_days < 0:
        return None
    weeks = delta_days // 7
    return "week1" if (weeks % 2 == 0) else "week2"

# --- main ---
def main():
    driver = get_driver(headless=False)
    try:
        login(driver)
        go_to_preferences(driver)

        for i in range(WEEKS_TO_UPDATE):
            week_start = START_DATE + datetime.timedelta(weeks=i)
            wt = get_week_type(week_start)
            if not wt:
                print(f"⏭ Skipping {week_start} (before START_DATE)")
                continue

            print(f"🗓 Preparing to update week {week_start} as {wt}")
            try:
                navigate_to_week(driver, week_start)
            except Exception as e:
                print(f"❌ Could not navigate to {week_start}: {e}")
                continue

            try:
                set_week_preferences_on_current_week(driver, week_start, wt, PATTERN)
            except Exception as e:
                print(f"❌ Error setting preferences for {week_start}: {e}")
            time.sleep(1.0)

        print("🎉 Done updating weeks.")
    finally:
        time.sleep(1)
        driver.quit()

if __name__ == "__main__":
    main()
