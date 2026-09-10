import requests
from datetime import datetime, timedelta

BASE_URL = "http://time.xmzkteco.com:8097"
API = "/iclock/api/transactions/"
AUTH = ("admin", "admin123")  # ⚠️ remplacer avec tes vrais credentials

# ---- FILTERS ----
EMP_FILTER = None #1           # None = all employees
DAY_FILTER = None#"2025-09-11"         # "YYYY-MM-DD"
DUPLUCATE_INTERVAL = 5 #minute
# DAY_FILTER = ("2025-09-01", "2025-09-11")  # tuple for range

def build_params(page=1, emp_filter=None, day_filter=None):
    """Build query params for API call"""
    params = {"page_size":500,"ordering":"emp_code,terminal_sn,punch_time","page": page}

    # filtre employé
    if emp_filter:
        params["emp_code"] = emp_filter

    # filtre date
    if isinstance(day_filter, str):
        params["start_time"] = f"{day_filter} 00:00:00"
        params["end_time"]   = f"{day_filter} 23:59:59"

    elif isinstance(day_filter, tuple):
        params["start_time"] = f"{day_filter[0]} 00:00:00"
        params["end_time"]   = f"{day_filter[1]} 23:59:59"

    return params

def fetch_transactions(page=1, emp_filter=None, day_filter=None):
    """Fetch a page of transactions with filters applied at API level"""
    params = build_params(page, emp_filter, day_filter)
    url = f"{BASE_URL}{API}"
    res = requests.get(url, auth=AUTH, params=params)
    res.raise_for_status()
    return res.json()

def delete_transaction(tid):
    """Delete a duplicate transaction"""
    url = f"{BASE_URL}{API}{tid}/"
    res = requests.delete(url, auth=AUTH)
    if res.status_code in (200, 204):
        print(f"✅ Deleted duplicate transaction {tid}")
    else:
        print(f"⚠️ Failed to delete {tid}: {res.status_code} → {res.text}")

def clean_duplicates(emp_filter=None, day_filter=None):
    seen = {}
    page = 1

    while True:
        print(f"\n📥 Fetching page {page} with filters ...")
        data = fetch_transactions(page, emp_filter, day_filter)
        tx_list = data.get("data", [])
        print(f"   → Retrieved {len(tx_list)} transactions")

        for tx in tx_list:
            emp = tx["emp_code"]
            tid = tx["id"]
            terminal = tx["terminal_sn"]
            punch_time_str = tx["punch_time"]
            punch_time = datetime.strptime(punch_time_str, "%Y-%m-%d %H:%M:%S")

            punch_day = punch_time.date()
            key = (emp, terminal, punch_day)

            if key in seen:
                delta = (punch_time - seen[key])
                if delta <= timedelta(minutes=DUPLUCATE_INTERVAL or 5):
                    print(f"❌ Duplicate → ID {tid} | Emp {emp} | {punch_time_str} | Δ {delta}")
                    delete_transaction(tid)
                else:
                    print(f"✔️ Keeping punch → ID {tid} | Emp {emp} | {punch_time_str}")
                    seen[key] = punch_time
            else:
                print(f"✔️ First punch (Emp {emp}, Terminal {terminal}, Day {punch_day}) → {punch_time_str}")
                seen[key] = punch_time

        if not data.get("next"):
            print("\n✅ Finished checking all pages")
            break
        page += 1

if __name__ == "__main__":
    clean_duplicates(EMP_FILTER, DAY_FILTER)