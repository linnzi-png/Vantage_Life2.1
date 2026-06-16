"""
Batch WAR Import Script
Downloads all WAR xlsx files from Google Drive and imports them into MongoDB.

Edit WEEKS and DRIVE_FILE_IDS below, then run:
    pip install openpyxl pymongo dnspython requests
    MONGO_URL="mongodb+srv://..." python backend/import_all_wars.py

Or on Windows PowerShell:
    $env:MONGO_URL = "mongodb+srv://..."
    python backend\import_all_wars.py
"""
import os
import sys
import subprocess
from datetime import date, timedelta
from pathlib import Path

DOWNLOADS_DIR = Path(__file__).parent.parent / "downloads"
SCRIPT = Path(__file__).parent / "import_xlsx_war.py"

# Each entry: (week_start_date, {office_key: google_drive_file_id})
# Add new weeks here as they arrive. Week start = Wednesday.
WEEKS = [
    ("2026-02-18", {
        "gojcaj": None,
        "mj":     None,
        "rust":   None,
        "monty":  None,
    }),
    # Add more weeks as needed...
]


def download_drive_file(file_id: str, dest: Path):
    """Download a Google Drive file by ID using the Drive MCP or direct export URL."""
    import requests
    url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    if "text/html" in r.headers.get("Content-Type", ""):
        raise ValueError(
            "Downloaded file is HTML — likely a Google login or permission page, not an XLSX spreadsheet."
        )
    dest.write_bytes(r.content)


def import_week(week_start: str, xlsx_path: Path) -> bool:
    env = {**os.environ, "WEEK_START": week_start, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(xlsx_path)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"  ERROR:\n{result.stderr}")
        return False
    return True


def main():
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    ok = 0
    failed = 0

    for week_start, offices in WEEKS:
        for office_key, file_id in offices.items():
            fname = f"{week_start}_{office_key}.xlsx"
            dest = DOWNLOADS_DIR / fname

            if file_id and not dest.exists():
                print(f"Downloading {fname} ...")
                try:
                    download_drive_file(file_id, dest)
                except Exception as e:
                    print(f"  Download failed: {e}")
                    failed += 1
                    continue

            if not dest.exists():
                print(f"  Skipping {fname} — file not found and no Drive ID set")
                continue

            print(f"Importing {fname} (week {week_start}) ...")
            if import_week(week_start, dest):
                ok += 1
            else:
                failed += 1

    print(f"\nDone: {ok} OK, {failed} FAILED")


if __name__ == "__main__":
    main()