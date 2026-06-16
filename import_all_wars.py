"""Import all downloaded WAR xlsx files into MongoDB. Downloads must already exist."""
import os
import subprocess

REPO = r"C:\Users\linnz\OneDrive\Documents\Vantage_Life2.1"
DOWNLOADS = os.path.join(REPO, "downloads")
MONGO_URL = "mongodb+srv://linnzi_db_user:Wy7fahxb9Gfp9xh2@vantagelife.r5atbyt.mongodb.net/"
SCRIPT = os.path.join(REPO, "backend", "import_xlsx_war.py")

WEEKS = [
    "2026-02-18", "2026-02-25", "2026-03-04", "2026-03-11",
    "2026-03-18", "2026-03-25", "2026-04-01", "2026-04-08",
    "2026-04-15", "2026-04-22", "2026-04-29", "2026-05-06",
    "2026-05-13", "2026-05-20", "2026-05-27", "2026-06-03",
]
OFFICES = ["Gojcaj", "MJ", "Rust", "Monty"]

log_path = os.path.join(REPO, "import_log.txt")
ok = 0
fail = 0

with open(log_path, "w") as log:
    for ws in WEEKS:
        safe = ws.replace("-", "_")
        for office in OFFICES:
            fname = f"{office}_WAR_{safe}.xlsx"
            fpath = os.path.join(DOWNLOADS, fname)
            if not os.path.exists(fpath):
                log.write(f"[SKIP] {ws} {office} — file not found\n")
                continue
            env = os.environ.copy()
            env["WEEK_START"] = ws
            env["MONGO_URL"] = MONGO_URL
            env["PYTHONIOENCODING"] = "utf-8"
            r = subprocess.run(
                ["python", SCRIPT, fpath],
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
            )
            status = "OK" if r.returncode == 0 else "FAIL"
            if r.returncode == 0:
                ok += 1
            else:
                fail += 1
            log.write(f"[{status}] {ws} {office}\n")
            if r.stdout:
                log.write(r.stdout)
            if r.stderr:
                log.write(r.stderr)
            log.flush()
            print(f"[{status}] {ws} {office}")

    summary = f"\nDone: {ok} OK, {fail} FAILED\n"
    log.write(summary)
    print(summary)
