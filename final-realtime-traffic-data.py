from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd
import time
import os
import json
from datetime import datetime
import gspread
from gspread_dataframe import set_with_dataframe
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# CONFIGURATION
# ==========================================
# 1. Folder ID from your SCHOOL'S SHARED DRIVE
DRIVE_FOLDER_ID = "0AJOwvpK_GNpwUk9PVA"

# 2. Google Sheets Setup
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1HufBCTo6cQflvQMyNY5VZ5jrUh0zXEx4AHw-FUPWxr8/edit?gid=0#gid=0"
SERVICE_ACCOUNT_FILE = "service_account.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# ==========================================
# INITIALIZATION
# ==========================================
# Support loading credentials from env variable (used in GitHub Actions)
if os.environ.get("SERVICE_ACCOUNT_JSON"):
    creds_info = json.loads(os.environ["SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
else:
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)

client = gspread.authorize(creds)
drive_service = build('drive', 'v3', credentials=creds)
sheet = client.open_by_url(SPREADSHEET_URL).sheet1

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def upload_screenshot_to_drive(file_path, file_name):
    """Uploads file to a Shared Drive folder and sets permission to reader."""
    try:
        file_metadata = {
            'name': file_name,
            'parents': [DRIVE_FOLDER_ID]
        }
        media = MediaFileUpload(file_path, mimetype='image/png')

        # supportsAllDrives=True allows using the Shared Drive's quota
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink',
            supportsAllDrives=True
        ).execute()

        file_id = file.get('id')

        # Shared Drives use 'reader' instead of 'viewer'
        drive_service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'},
            supportsAllDrives=True
        ).execute()

        return file.get('webViewLink')
    except Exception as e:
        print(f"[{datetime.now()}] Drive Upload Warning: {e}")
        return "Upload Failed"

# ==========================================
# MAIN — runs once per invocation
# (GitHub Actions cron handles the 5-min repeat)
# ==========================================
url = "https://www.google.com/maps/dir/SMDC+BLUE,+41+Katipunan+Ave,+Quezon+City,+1108+Metro+Manila/U.P.+Town+Center,+249,+216+Katipunan+Ave,+Diliman,+Quezon+City,+1101+Metro+Manila/"

driver = None
try:
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    driver.get(url)
    wait = WebDriverWait(driver, 30)

    print(f"[{datetime.now()}] Loading route info...")
    wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'min')]")))
    time.sleep(5)

    # -----------------------------
    # 1. Snapshot & Upload
    # -----------------------------
    img_filename = f"traffic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    driver.save_screenshot(img_filename)

    print(f"[{datetime.now()}] Uploading to Shared Drive folder...")
    snapshot_url = upload_screenshot_to_drive(img_filename, img_filename)

    if os.path.exists(img_filename):
        os.remove(img_filename)

    # -----------------------------
    # 2. Extraction
    # -----------------------------
    travel_time = "N/A"
    distance = "N/A"

    for el in driver.find_elements(By.XPATH, "//*[contains(text(),'min')]"):
        text = el.text.strip()
        if "min" in text and len(text) < 20:
            travel_time = text
            break

    for el in driver.find_elements(By.XPATH, "//*[contains(text(),'km')]"):
        text = el.text.strip()
        if "km" in text and len(text) < 20:
            distance = text
            break

    # -----------------------------
    # 3. Speed & Labeling
    # -----------------------------
    avg_speed = 0
    color_label = "GRAY"

    try:
        t_val = float(''.join(c for c in travel_time if c.isdigit() or c == '.'))
        d_val = float(''.join(c for c in distance if c.isdigit() or c == '.'))

        if t_val > 0:
            avg_speed = round(d_val / (t_val / 60), 2)

        if avg_speed >= 40:
            color_label = "GREEN (Fast)"
        elif 20 <= avg_speed < 40:
            color_label = "ORANGE (Moderate)"
        else:
            color_label = "RED (Heavy Traffic)"
    except:
        avg_speed = "Error"

    # -----------------------------
    # 4. Sheet Update
    # -----------------------------
    print(f"[{datetime.now()}] Updating Google Sheet...")
    data = {
        "Origin": ["SMDC BLUE"],
        "Destination": ["U.P. Town Center"],
        "Travel_Time": [travel_time],
        "Distance": [distance],
        "Avg_Speed_KMH": [avg_speed],
        "Traffic_Status": [color_label],
        "Snapshot_Link": [snapshot_url],
        "Timestamp": [datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    }

    df = pd.DataFrame(data)

    try:
        records = sheet.get_all_records()
        existing_df = pd.DataFrame(records)
        updated_df = pd.concat([existing_df, df], ignore_index=True)
        set_with_dataframe(sheet, updated_df)
        print(f"[{datetime.now()}] Success! Speed: {avg_speed} km/h logged.\n")
    except Exception as sheet_err:
        print(f"[{datetime.now()}] Sheet Update Failed: {sheet_err}")

    driver.quit()

except Exception as e:
    print(f"[{datetime.now()}] Error: {e}")
    if driver:
        driver.quit()
    raise
