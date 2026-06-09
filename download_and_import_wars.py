"""
Download all WAR Google Sheets as xlsx and import into MongoDB.
Run from repo root: python download_and_import_wars.py
"""
import os
import sys
import time
import subprocess
import urllib.request
import urllib.error

REPO = r"C:\Users\linnz\OneDrive\Documents\Vantage_Life2.1"
DOWNLOADS = os.path.join(REPO, "downloads")
MONGO_URL = "mongodb+srv://linnzi_db_user:Wy7fahxb9Gfp9xh2@vantagelife.r5atbyt.mongodb.net/"

# All weeks: week_start_date -> {office: sheet_id}
# Week 5/6 already imported — include anyway (import script skips duplicates)
WEEKS = [
    ("2026-02-18", {
        "Gojcaj": "1p6wTkvBcjvI_nJK7voVYBVkn4d8wekF_RkcUqOhGLMA",
        "MJ":     "1-BhTvr_b3TlvL-5N6SI9oWfRoX-cY9u_0a8IWbNPHCo",
        "Rust":   "10XHH3GRNB0hrsQ4nbKasAW-rLriVRue4qtuiSCu_R48",
        "Monty":  "1kc_swpx9blob3qiRS-lGSZR7jbJBylQzuui8soCkJaI",
    }),
    ("2026-02-25", {
        "Gojcaj": "1Tfe_MHuNajDvHACyPUB2kjXKvnVy9bTMyOdZrLC-l-c",
        "MJ":     "1fP_kjVgkb_yvO5C9XKKvPBszXIv3Bx-Bzo1lPkWcaZA",
        "Rust":   "1lXQDYuvM3SmmkM6kjVhqSBaTy0dB7zTVuaCcAYF7KE0",
        "Monty":  "1WQRGIVXizDcnC_cvDHRBCJpPxBecxk0kv8wyelcEOA4",
    }),
    ("2026-03-04", {
        "Gojcaj": "17jAbIaInI_tEArSf-q8RDrqFPp-6WXD3Q44gX7uzrwY",
        "MJ":     "17XLHXl5Bmg9IWZT5_G5Z7CvD1HJDs09Y6ftfcKsl9bU",
        "Rust":   "1nQ8WAsxypXB_oHFmKSYWyK3Ul3bV_Jw4sFBu4dH3rQ8",
        "Monty":  "1xf3MnTNuBJxf_-9CaVq0nN18QKtX-SuFse8EUO8xveY",
    }),
    ("2026-03-11", {
        "Gojcaj": "18bUzLJrrTc2eagxwTBtd1uUtIRhzmyH-tWJbgEiQHHY",
        "MJ":     "10Xo_2Je9zjKWGIMxCvC_jaYuF3SGDzfB0KSATbrb8rc",
        "Rust":   "13xkw0bXl8SR06leIIeTj0uHWlLNs39Pjx19aDIKNp3E",
        "Monty":  "1d0DcMJDNI0Mmwp9EgGUn6dD4kha_vMGMp_bKSxk3u10",
    }),
    ("2026-03-18", {
        "Gojcaj": "1555JEpFHyLB95Aaq--htigSfBlgoDcAoWRq5SSqLbd0",
        "MJ":     "18-S1LKH_Dq53MCfNpM5yVGOKE22AWlNjNIOSx0B7G5U",
        "Rust":   "1W11ZapbHsMNrCkRVix78j3_HO9uSu0vxa5JKsNFyCpg",
        "Monty":  "1Zssfrydf-JZ9Mts3sQ-Pz_iG-oucz1mMCKlKv_ZPQvo",
    }),
    ("2026-03-25", {
        "Gojcaj": "1Zu6ejKLHNcR6zF6iZsSImG6k0RUAL6qjM0fFMnQa_To",
        "MJ":     "13fVhqUK6ucaAUo0E6I_Q4atmIADzUZr02YArlLG0DdE",
        "Rust":   "148kRkBFZVfsYsgl_rD-hgV77u15iRAE5kKJ0jOc6Ygw",
        "Monty":  "1vPfpoMdZOpQ4w2NuHHBhwDZ2-QF3pTxH59AqHQjIPnw",
    }),
    ("2026-04-01", {
        "Gojcaj": "1ndlHtnDHseMPPYelyle25Xh2SkWechQ7A6_MQQDsvWs",
        "MJ":     "1nBVnmcqC6LqCzCsU-KRKTVR_QOuRrU-TlRq6k720rBs",
        "Rust":   "1EVnVTHO2wAJzFVkFdLH5WEGjvd0WB3hDRbakT9W2NjQ",
        "Monty":  "1c33cK9tjw15VS-FWVVQNcouiUaLnEo-kzRHO4o-mBYM",
    }),
    ("2026-04-08", {
        "Gojcaj": "1cM_DsO9oOVhljSX4lSgLF4D39SBhj27t9H5qCPJJclE",
        "MJ":     "1KqC6ifA0w2uA-BWlzrR3nOT7Bc5Z7QUffsFNfFt2wRo",
        "Rust":   "15J7sArwe0ZyKUskgRiA9SUFsqLe0btXqGaV1RYq7SVQ",
        "Monty":  "1UdFwUERSIjoudEfobZqvZ3tY5EzUG6blThY-JO35d-I",
    }),
    ("2026-04-15", {
        "Gojcaj": "1kgkZkwnpZ-Jz8FV8ZYpg5UkYJEjU2RKgoctctSfXrjo",
        "MJ":     "1hCwRCLLbWX2_EPdU9RV4ZXFuFYftx0QnNSQuQi10oUk",
        "Rust":   "1Y8li5cj0F9-sYSL83h5N4ltO4g8f_Lh-ThTqOo8xdqw",
        "Monty":  "10aURgiPa1P4jl_bxyeEZELkBGtwVt38IT4AdE-spG3E",
    }),
    ("2026-04-22", {
        "Gojcaj": "1QPhU4LAdcST4E_m97YWTdiPopqz0OWhH2exEjeOiaPk",
        "MJ":     "1yPmKHnCaPvsto7kNPeVNpV7VJUTXhHNXqfMmQ21XdN0",
        "Rust":   "1CjutHeCkwwIXXb2kPOzWmAUb29kpXmriVF6u2FmjCbc",
        "Monty":  "1pyifE8y9v3SvHJqMVHyjOeGX4ZftZRUrtp_EcFiToVg",
    }),
    ("2026-04-29", {
        "Gojcaj": "112BjvtChAeRmEiZbd1ldFyaSMk7IN2ogjwp5qnHLB30",
        "MJ":     "1tJjgl9tEksEQh2RxVQQl_c6dUrG6q2vFHoRmaY1Y9fs",
        "Rust":   "1ETh_ao_-ET8mSKAJ2Kvdqq6krGP4VZDt_lcP4MvX5Jk",
        "Monty":  "13FVjZMJOWXg-OJIhoIJFizaop65THbLGNgqNta3Frww",
    }),
    ("2026-05-06", {
        "Gojcaj": "1vZy7zV2p6x0Q1uvs4jB2bvB2bUyApnQ7gGtsk3ja60s",
        "MJ":     "1MJ1YBmvVS0x6vf2vreLfcsW4-9ThLmRrBJAE5e1j1jo",
        "Rust":   "1QTRm6mqXPqdFFKMLVSviRKzGuuyputNOKim2DzgIoNg",
        "Monty":  "1JjyJddTjV3uFf3xWFd37arxgjtkBcjNhzwl9ZnRrL3U",
    }),
    ("2026-05-13", {
        "Gojcaj": "1Ve41LAzcz_AL18P_jUW95oAMrWkZp01G9movYpYT0is",
        "MJ":     "1UIBEJUxiV78yRNJqnS4-8qXfUXGHLlUq2aP27_7DIFQ",
        "Rust":   "1gH3COz2S9r1lUo3NZQY6qo_tdVI1SJsFFeBTz3r77Mw",
        "Monty":  "1GET_TTw30MDf2dIsH3UoEbszOKQDs_O2moz0emYFgY0",
    }),
    ("2026-05-20", {
        "Gojcaj": "1ue4tZZ2m6RW41Q8bTZfgXIiOdYMj-Z3UXBEnEfORGOg",
        "MJ":     "1-Tv_mHSZP7wxah-3HyHiVnzUaxfhmVQevBiqZz5yWNI",
        "Rust":   "1Q2nF859VFt6DkiSVJeqftT4keksjEZesh1BHgkOfGbA",
        "Monty":  "1Tsx3QFFH5yRhNzIn7fuZ-Hy7x2W503wbNP9d80vf4tI",
    }),
    ("2026-05-27", {
        "Gojcaj": "1OM8oSLRijhw_zMWI9geC6XtuIuOLhE9FpvcSP8RUVJU",
        "MJ":     "1_ZTou5cw1zY1xC1aoCmXgtFdYg7ZdnzgcCQuDsksgh4",
        "Rust":   "1Vv1qke_yWVctvgLYV5TytLv-cfDAKmscEE14_lkmGK8",
        "Monty":  "1iPGUSpBuvMnvD6wsCp1wKP330RY52zQDCRfEwYQ9dmc",
    }),
    ("2026-06-03", {
        "Gojcaj": "10qKVDuklampHV0bElir6Hb4waaxD1QgwaFe_H8UNVAU",
        "MJ":     "1m7iqAZlC_0ySD7ovvJRXwTtt8AYw2m_xGx4xRHGLjHc",
        "Rust":   "1ubv_dFVQdOUKDay08nMTApLTD1fSvJtimEAvx9iaPKI",
        "Monty":  "17fsAi10yqrxgwVqSoiqycWZ5_t9eYSlHdv58CeLWr5o",
    }),
]


def download_sheet(sheet_id: str, dest_path: str) -> bool:
    """Download a Google Sheet as xlsx. Returns True on success."""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if len(data) < 1000:
            print(f"  WARNING: file too small ({len(data)} bytes) — may not be a valid xlsx")
        with open(dest_path, "wb") as f:
            f.write(data)
        print(f"  Downloaded {len(data):,} bytes → {dest_path}")
        return True
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} downloading {sheet_id}: {e.reason}")
        return False
    except Exception as e:
        print(f"  Error downloading {sheet_id}: {e}")
        return False


def import_xlsx(xlsx_path: str, week_start: str) -> bool:
    """Run the import script for one xlsx file. Returns True on success."""
    script = os.path.join(REPO, "backend", "import_xlsx_war.py")
    env = os.environ.copy()
    env["WEEK_START"] = week_start
    env["MONGO_URL"] = MONGO_URL
    result = subprocess.run(
        ["python", script, xlsx_path],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if result.returncode != 0:
        print(f"  FAILED import for {xlsx_path} (exit {result.returncode})")
        return False
    return True


def main():
    os.makedirs(DOWNLOADS, exist_ok=True)
    total = failed_dl = failed_import = 0

    for week_start, offices in WEEKS:
        print(f"\n{'='*60}")
        print(f"Week: {week_start}")
        print(f"{'='*60}")
        for office, sheet_id in offices.items():
            total += 1
            safe_date = week_start.replace("-", "_")
            filename = f"{office}_WAR_{safe_date}.xlsx"
            dest = os.path.join(DOWNLOADS, filename)

            print(f"\n[{office}]")
            if not download_sheet(sheet_id, dest):
                failed_dl += 1
                continue

            time.sleep(1)  # be polite to Google

            if not import_xlsx(dest, week_start):
                failed_import += 1

    print(f"\n{'='*60}")
    print(f"Done. {total} sheets processed.")
    if failed_dl:
        print(f"  Download failures: {failed_dl}")
    if failed_import:
        print(f"  Import failures: {failed_import}")
    if failed_dl == 0 and failed_import == 0:
        print("  All imports successful!")


if __name__ == "__main__":
    main()
