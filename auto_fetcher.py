import os
import sys
import time
import imaplib
import email
from email.header import decode_header
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv


load_dotenv()

# --- CONFIGURATION ---
EMAIL_ACCOUNT = os.environ.get("EMAIL_ACCOUNT")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
IMAP_SERVER = "imap.gmail.com"
CHECK_INTERVAL_SECONDS = 60                        # Check every 60 seconds

DATA_DIR = Path("data")
VALID_EXTENSIONS = [".pdf", ".xlsx", ".xls", ".png", ".jpg", ".jpeg"]

def check_email_and_download():
    print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Checking {EMAIL_ACCOUNT} for new files...")
    
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        mail.select("inbox")
        
        status, messages = mail.search(None, "UNSEEN")
        email_ids = messages[0].split()
        
        if not email_ids:
            print("No new emails found.")
            mail.logout()
            return None
            
        downloaded_files = {
            "kashmir": None,
            "jammu": None,
            "rainfall": None
        }
        
        for e_id in email_ids:
            status, msg_data = mail.fetch(e_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    
                    for part in msg.walk():
                        # --- 1. Handle Attachments ---
                        if part.get_content_maintype() == 'multipart':
                            continue
                        if part.get('Content-Disposition') is not None:
                            filename = part.get_filename()
                            if filename:
                                filename, encoding = decode_header(filename)[0]
                                if isinstance(filename, bytes):
                                    filename = filename.decode(encoding or "utf-8")
                                
                                file_ext = Path(filename).suffix.lower()
                                
                                # If it's a text file, save as whatsapp.txt for Kashmir
                                if file_ext == ".txt":
                                    filepath = DATA_DIR / "whatsapp.txt"
                                    with open(filepath, "wb") as f:
                                        f.write(part.get_payload(decode=True))
                                    print(f"  ✓ Saved Kashmir attachment: whatsapp.txt")
                                    downloaded_files["kashmir"] = filepath
                                    
                                # If it's an Excel file, check the name to route it!
                                elif file_ext in [".xls", ".xlsx"]:
                                    filepath = DATA_DIR / filename
                                    with open(filepath, "wb") as f:
                                        f.write(part.get_payload(decode=True))
                                    
                                    # Check if filename indicates rainfall
                                    if "rainfall" in filename.lower() or "mkformat" in filename.lower():
                                        print(f"  ✓ Downloaded Rainfall file: {filename}")
                                        downloaded_files["rainfall"] = filepath
                                    else:
                                        print(f"  ✓ Downloaded Jammu Excel file: {filename}")
                                        downloaded_files["jammu"] = filepath
                                    
                                # If it's a PDF or Image, save for Jammu
                                elif file_ext in [".pdf", ".png", ".jpg", ".jpeg"]:
                                    filepath = DATA_DIR / filename
                                    with open(filepath, "wb") as f:
                                        f.write(part.get_payload(decode=True))
                                    print(f"  ✓ Downloaded Jammu file: {filename}")
                                    downloaded_files["jammu"] = filepath
                            continue
                        
                        # --- 2. Handle Plain Text Email Body (for Kashmir text) ---
                        if part.get_content_maintype() == 'text' and part.get_content_subtype() == 'plain':
                            body_text = part.get_payload(decode=True).decode(errors='ignore')
                            # If the email body contains the river data, save it!
                            if "Gauge @" in body_text and "JHELUM" in body_text.upper():
                                filepath = DATA_DIR / "whatsapp.txt"
                                with open(filepath, "w", encoding="utf-8") as f:
                                    f.write(body_text)
                                print(f"  ✓ Saved Kashmir email body: whatsapp.txt")
                                downloaded_files["kashmir"] = filepath
                                
        mail.logout()
        
        # Return the dictionary only if at least one file was downloaded
        if any(downloaded_files.values()):
            return downloaded_files
        return None

    except Exception as e:
        print(f"Error checking email: {e}")
        return None

def run_automation(downloaded_files):
    print("\nNew files found! Starting relevant automation scripts...")
    
    python_exe = sys.executable
    archive_dir = DATA_DIR / "processed" / datetime.now().strftime("%Y-%m-%d")
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    def archive_file(filepath):
        if filepath and filepath.exists():
            dest = archive_dir / filepath.name
            if dest.exists():
                dest = archive_dir / f"{filepath.stem}_{int(time.time())}{filepath.suffix}"
            shutil.move(str(filepath), str(dest))
            print(f"  Archived: {filepath.name} -> {dest}")

    # --- Run Kashmir ---
    if downloaded_files.get("kashmir"):
        print("\n--- Running Kashmir Automation ---")
        subprocess.run([python_exe, "main.py"])
        archive_file(downloaded_files["kashmir"])
    
    # --- Run Jammu ---
    if downloaded_files.get("jammu"):
        print("\n--- Running Jammu Automation ---")
        # jammu_main.py auto-scans the whole data/ folder when called
        # with no filename argument - important here specifically,
        # since a single email check can download MULTIPLE Jammu files
        # (e.g. 3 PDFs + 1 xlsx + 1 image), but downloaded_files["jammu"]
        # only ever holds the LAST one seen. Passing just that one
        # filename would silently drop the rest of that batch.
        subprocess.run([python_exe, "jammu_main.py"])
        archive_file(downloaded_files["jammu"])
        
    # --- Run Rainfall ---
    if downloaded_files.get("rainfall"):
        print("\n--- Running Rainfall Automation ---")
        subprocess.run([python_exe, "rainfall_main.py"])
        archive_file(downloaded_files["rainfall"])


if __name__ == "__main__":
    DATA_DIR.mkdir(exist_ok=True)
    print("Starting Local Auto-Fetcher. Press Ctrl+C to stop.")

    while True:
        downloaded = check_email_and_download()
        if downloaded:
            run_automation(downloaded)
        print(f"Sleeping for {CHECK_INTERVAL_SECONDS} seconds...")
        time.sleep(CHECK_INTERVAL_SECONDS)