import io
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd
import time
from datetime import datetime
import gspread
from gspread_dataframe import set_with_dataframe
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


# CONFIGURATION

DRIVE_FOLDER_ID = "0AJOwvpK_GNpwUk9PVA" 
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1HufBCTo6cQflvQMyNY5VZ5jrUh0zXEx4AHw-FUPWxr8/edit?gid=0#gid=0"
SERVICE_ACCOUNT_FILE = "service_account.json"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

# INITIALIZATION
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
client = gspread.authorize(creds)
drive_service = build('drive', 'v3', credentials=creds)
sheet = client.open_by_url(SPREADSHEET_URL).sheet1

# HELPER FUNCTIONS
def upload_bytes_to_drive(image_bytes, file_name):
    """Uploads image bytes directly from memory to Google Drive."""
    try:
        file_metadata = {'name': file_name, 'parents': [DRIVE_FOLDER_ID]}
        fh = io.BytesIO(image_bytes)
        media = MediaIoBaseUpload(fh, mimetype='image/png', resumable=True)
        
        file = drive_service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink',
            supportsAllDrives=True 
        ).execute()
        
        drive_service.permissions().create(
            fileId=file.get('id'), 
            body={'type': 'anyone', 'role': 'reader'},
            supportsAllDrives=True
        ).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        print(f"[{datetime.now()}] Drive Upload Error: {e}")
        return "Upload Failed"

# MAIN — runs once per invocation
# (GitHub Actions cron handles the 5-min repeat)
url = "https://www.google.com/maps/dir/SMDC+BLUE,+41+Katipunan+Ave,+Quezon+City,+1108+Metro+Manila/U.P.+Town+Center,+249,+216+Katipunan+Ave,+Diliman,+Quezon+City,+1101+Metro+Manila/"

driver = None
try:
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get(url)
    wait = WebDriverWait(driver, 30)

    print(f"[{datetime.now()}] Loading route info...")
    wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'min')]")))
    time.sleep(5)

    # Hide Panel & Snapshot to Memory
    try:
        collapse_btn = driver.find_element(By.XPATH, "//button[@aria-label='Collapse side panel']")
        collapse_btn.click()
        time.sleep(2)
    except:
        pass

    print(f"[{datetime.now()}] Capturing snapshot...")
    try:
        map_element = driver.find_element(By.TAG_NAME, "canvas")
        image_data = map_element.screenshot_as_png
    except:
        image_data = driver.get_screenshot_as_png()

    img_name = f"traffic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    snapshot_url = upload_bytes_to_drive(image_data, img_name)

    # Extraction
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

    # UPDATED LOGIC from JICA
    avg_speed = 0
    color_label = "GRAY"

    try:
        t_val = float(''.join(c for c in travel_time if c.isdigit() or c == '.'))
        d_val = float(''.join(c for c in distance if c.isdigit() or c == '.'))

        if t_val > 0:
            avg_speed = round(d_val / (t_val / 60), 2)

        # Logic based on JPT/MMDA Class A Road distribution
        if avg_speed > 25:
            color_label = "GREEN (Fast)"
        elif 20 <= avg_speed <= 25:
            color_label = "ORANGE (Normal)"
        else:
            color_label = "RED (Heavy Traffic)"
    except:
        avg_speed = "Error"

    # Sheet Update
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
        print(f"[{datetime.now()}] Success! Speed: {avg_speed} km/h ({color_label}) logged.\n")
    except Exception as sheet_err:
        print(f"[{datetime.now()}] Sheet Update Failed: {sheet_err}")

    driver.quit()

except Exception as e:
    print(f"[{datetime.now()}] Error: {e}")
    if driver:
        driver.quit()
    raise