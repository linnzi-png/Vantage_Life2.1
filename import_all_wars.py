"""Bulk-import a directory of WAR xlsx files into MongoDB.

Superseded by the in-app Admin → Import War Report screen, which needs no
local MongoDB access. Kept for bulk local backfills.

Week start is read from each filename ('YYYY-MM-DD_...xlsx'), and files are
imported in chronological order so that the two days each report shares with
the following week are resolved later-file-wins.

Usage (never hardcode the connection string — pass it in the environment):

    export MONGO_URL='mongodb+srv://USER:PASSWORD@host/'
    python import_all_wars.py [directory]

Defaults to ./downloads if no directory is given.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(REPO, "backend", "import_xlsx_war.py")

# Credentials come from the environment. A connection string committed to the
# repo leaks the whole production database to anyone with read access.
MONGO_URL = os.environ.get("MONGO_URL")
if not MONGO_URL:
    sys.exit("MONGO_URL is not set. Export it before running (see module docstring).")

source_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "downloads")
if not os.path.isdir(source_dir):
    sys.exit(f"No such directory: {source_dir}")

files = sorted(f for f in os.listdir(source_dir) if f.endswith(".xlsx"))
if not files:
    sys.exit(f"No .xlsx files found in {source_dir}")

log_path = os.path.join(REPO, "import_log.txt")
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"

print(f"Importing {len(files)} file(s) from {source_dir} ...")
with open(log_path, "w", encoding="utf-8") as log:
    result = subprocess.run(
        [sys.executable, SCRIPT, *[os.path.join(source_dir, f) for f in files]],
        cwd=os.path.join(REPO, "backend"),
        env=env,
        capture_output=True,
        text=True,
    )
    log.write(result.stdout or "")
    log.write(result.stderr or "")

print(result.stdout or "")
if result.returncode != 0:
    print(result.stderr or "", file=sys.stderr)
print(f"Log written to {log_path}")
sys.exit(result.returncode)
