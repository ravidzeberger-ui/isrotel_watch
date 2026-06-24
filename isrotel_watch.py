# -*- coding: utf-8 -*-
"""
isrotel_watch — מנטר את עמוד "דקה 90" של ישרוטל ומתריע בטלגרם
כשמופיע דיל סופ"ש (חמישי–שבת, 2 לילות) מתחת לסף, מחוץ לאילת.

מתריע פעם אחת בלבד לכל דיל (dedup לפי saleid) — שקט מוחלט עד שיש דיל אמיתי.

הרצה:
    python isrotel_watch.py            # מצב רגיל: שולח טלגרם על דילים חדשים
    python isrotel_watch.py --dry-run  # לא שולח כלום, רק מדפיס מה היה נשלח
"""
import re, json, sys, os, datetime as dt
import requests
from bs4 import BeautifulSoup

# קונסול Windows (cp1255) לא מציג אימוג'י/עברית מלאה — נכפה UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ----------------------------- הגדרות -----------------------------
URL          = "https://www.isrotel.co.il/deals/special-sale/main/"
PER_NIGHT_MAX  = 1500          # ₪ ללילה (כי 2 לילות ≈ 3,000)
WEEKEND_TOTAL_MAX = 3000       # ₪ לזוג לסופ"ש (2 לילות)
WEEKEND_NIGHTS = {3, 4}        # weekday(): חמישי=3, שישי=4  → סופ"ש חמישי–שבת
EILAT_LOC_CODES = {"17005"}    # קוד מיקום של אילת (לגונה/ספורט קלאב)
EILAT_NAME_HINTS = ["לגונה", "ספורט קלאב", "קינג סולומון", "אגמים",
                    "ים סוף", "ריביירה", "רויאל גארדן", "רויאל ביץ' אילת"]
EXCLUDE_HOTEL_CODES = {"AL"}        # מלונות לא רלוונטיים (AL=אלברטו)
EXCLUDE_HOTEL_NAMES = ["אלברטו"]

HERE       = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
LOG_FILE   = os.path.join(HERE, "run.log")
ENV_FILE   = os.path.join(HERE, ".env")

CITY_BY_LOC = {
    "17010": "תל אביב",
    "17009": "ירושלים",
    "17008": "נגב/דרום",
    "17006": "ים המלח",
    "17005": "אילת",
    "103719": "צפון/כרמל",
}

HE_DOW = {0: "שני", 1: "שלישי", 2: "רביעי", 3: "חמישי",
          4: "שישי", 5: "שבת", 6: "ראשון"}

# --------------------------- כלי עזר ---------------------------
def load_env():
    if not os.path.exists(ENV_FILE):
        return
    for line in open(ENV_FILE, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

def now_israel():
    """שעון ישראל — כי שרת ה-GitHub רץ ב-UTC"""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Asia/Jerusalem"))
    except Exception:
        return dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)

def log(msg):
    ts = now_israel().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def parse_dmy(s):  # '25/06/26' או '25/06'
    p = s.split("/")
    d, m = int(p[0]), int(p[1])
    y = 2000 + int(p[2]) if len(p) > 2 else dt.date.today().year
    return dt.date(y, m, d)

# --------------------------- שליפה + פענוח ---------------------------
def fetch_deals():
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
    }
    r = requests.get(URL, headers=headers, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    deals = []
    for c in soup.select("article.card--deal"):
        try:
            sid  = c.get("data-saleid")
            hcode = c.get("data-hotel")
            loc  = c.get("data-location")
            title = c.select_one(".card__title").get_text(" ", strip=True)
            name = re.sub(r"^\s*\d+%\s*הנחה למהירי החלטה\s*", "", title)
            name = name.replace("למזמינים באתר בלבד", "").strip()
            desc = c.select_one(".card__description").get_text(" ", strip=True)
            board = ""
            m = re.search(r'ע"ב\s*(.+)$', desc)
            if m:
                board = m.group(1).strip()
            price_el = c.select_one(".ux-ui-price")
            per_night = int(re.search(r"([\d,]{3,})", price_el.get_text()).group(1).replace(",", ""))
            note = c.select_one(".card__price-info-note").get_text(" ", strip=True)
            dm = re.search(r"(\d{1,2}/\d{1,2})[-–](\d{1,2}/\d{1,2}/\d{2})", note)
            ci = parse_dmy(dm.group(1))
            co = parse_dmy(dm.group(2))
            deals.append(dict(saleid=sid, hotel=hcode, loc=loc, name=name,
                              board=board, per_night=per_night,
                              checkin=ci, checkout=co, nights=(co - ci).days,
                              city=CITY_BY_LOC.get(loc, "לא ידוע")))
        except Exception as e:
            log(f"WARN: failed to parse a card: {e}")
    return deals

# --------------------------- לוגיקת סינון ---------------------------
def is_eilat(d):
    if d["loc"] in EILAT_LOC_CODES:
        return True
    return any(h in d["name"] for h in EILAT_NAME_HINTS)

def weekend_pair_covered(d):
    """האם הדיל מכסה ליל-חמישי + ליל-שישי רצופים (שהייה חמישי→שבת, 2 לילות אמיתיים)?
    מחזיר (חמישי, שישי) אם כן, אחרת None. דיל של לילה-בודד נדחה."""
    day = d["checkin"]
    # day+1 חייב להיות עדיין בתוך השהייה (checkout לא-כולל) → מבטיח שגם ליל-שישי נכלל
    while day + dt.timedelta(days=1) < d["checkout"]:
        if day.weekday() == 3 and (day + dt.timedelta(days=1)).weekday() == 4:
            return day, day + dt.timedelta(days=1)
        day += dt.timedelta(days=1)
    return None

def matches(d):
    if d["hotel"] in EXCLUDE_HOTEL_CODES or any(n in d["name"] for n in EXCLUDE_HOTEL_NAMES):
        return False, "מלון מוחרג"
    if is_eilat(d):
        return False, "אילת"
    if not weekend_pair_covered(d):
        return False, "אין שהייה של 2 לילות סופ\"ש (חמישי+שישי)"
    est_total = d["per_night"] * 2          # אומדן 2 לילות-הסופ"ש (החל-מ-X ללילה)
    if d["per_night"] > PER_NIGHT_MAX or est_total > WEEKEND_TOTAL_MAX:
        return False, f"יקר ({est_total:,}₪ ל-2 לילות)"
    return True, f"~{est_total:,}₪ ל-2 לילות (חמישי–שבת)"

# --------------------------- מצב (dedup) ---------------------------
def load_state():
    if os.path.exists(STATE_FILE):
        st = json.load(open(STATE_FILE, encoding="utf-8"))
    else:
        st = {}
    st.setdefault("alerted", {})    # saleid -> זמן התראה (שעון ישראל)
    st.setdefault("last_runs", [])  # זמני ריצה אחרונים (heartbeat)
    return st

def save_state(state):
    json.dump(state, open(STATE_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

# --------------------------- טלגרם ---------------------------
def send_telegram(text):
    token = os.environ.get("TG_BOT_TOKEN")
    chat  = os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        log("ERROR: חסר TG_BOT_TOKEN / TG_CHAT_ID ב-.env — לא נשלחה התראה")
        return False
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(api, data={"chat_id": chat, "text": text,
                                 "parse_mode": "HTML",
                                 "disable_web_page_preview": "false"}, timeout=20)
    if r.status_code != 200:
        log(f"ERROR: telegram {r.status_code}: {r.text[:200]}")
        return False
    return True

def format_alert(d, reason):
    ci, co = d["checkin"], d["checkout"]
    nights = d["nights"]
    return (
        f"🏨 <b>{d['name']}</b> — {d['city']}\n"
        f"🗓 {HE_DOW[ci.weekday()]} {ci.strftime('%d/%m')}–{HE_DOW[co.weekday()]} {co.strftime('%d/%m')} "
        f"({nights} לילות)\n"
        f"🍳 {d['board']}\n"
        f"💰 {d['per_night']:,} ₪ ללילה ⇒ <b>{reason}</b>\n"
        f"🔗 {URL}"
    )

def format_daily_summary(scanned, runs_today, n_alerts):
    times = ", ".join(t[11:16] for t in sorted(runs_today))   # HH:MM שעון ישראל
    n = len(runs_today)
    runs_line = (f"הריצות רצו תקין. היום בוצעה ריצה אחת ({times})." if n == 1
                 else f"הריצות רצו תקין. היום בוצעו {n} ריצות ({times}).")
    if n_alerts == 1:
        deals_line = "🔔 נמצא היום דיל סופ\"ש מתאים אחד — קיבלת עליו התראה."
    elif n_alerts:
        deals_line = f"🔔 נמצאו היום {n_alerts} דילי סופ\"ש מתאימים — קיבלת התראה על כל אחד."
    else:
        deals_line = "😴 לא נמצא היום אף דיל סופ\"ש שמתאים לקריטריונים שלך."
    return "\n".join([
        "✅ <b>סיכום יומי — isrotel_watch</b>",
        runs_line,
        f"נסרקו {scanned} דילים בעמוד דקה 90.",
        deals_line,
    ])

# --------------------------- main ---------------------------
def main():
    dry = "--dry-run" in sys.argv
    summary_mode = ("--daily-summary" in sys.argv
                    or os.environ.get("DAILY_SUMMARY", "").lower() == "true")
    load_env()

    if "--test-telegram" in sys.argv:
        ok = send_telegram("✅ isrotel_watch מחובר. מכאן תקבל התראות על דילי סופ\"ש מתחת ל-3,000 ₪.")
        log("בדיקת טלגרם: " + ("הצליחה ✅" if ok else "נכשלה ❌"))
        return

    now_iso = now_israel().isoformat(timespec="seconds")
    today = now_iso[:10]
    state = load_state()
    deals = fetch_deals()
    log(f"נמשכו {len(deals)} דילים מהעמוד" + (" [DRY-RUN]" if dry else "")
        + (" [SUMMARY]" if summary_mode else ""))

    # --- התראות על דילים חדשים שמתאימים ---
    new_hits = [(d, r) for d in deals
                for ok, r in [matches(d)]
                if ok and d["saleid"] not in state["alerted"]]
    if new_hits:
        for d, reason in new_hits:
            text = format_alert(d, reason)
            if dry:
                log("היה נשלח:\n" + text)
            elif send_telegram(text):
                log(f"נשלחה התראה: {d['name']} ({d['saleid']})")
                state["alerted"][d["saleid"]] = now_iso
    else:
        log("אין דילי סופ\"ש חדשים מתחת לסף. שקט.")

    # --- רישום heartbeat (סימן חיים לכל ריצה) ---
    state["last_runs"] = (state["last_runs"] + [now_iso])[-40:]

    # --- סיכום יומי בריצה האחרונה (גם אם לא נמצא כלום) ---
    if summary_mode:
        runs_today = [t for t in state["last_runs"] if t[:10] == today]
        alerts_today = sum(1 for t in state["alerted"].values() if t[:10] == today)
        text = format_daily_summary(len(deals), runs_today, alerts_today)
        if dry:
            log("סיכום יומי שהיה נשלח:\n" + text)
        elif send_telegram(text):
            log("נשלח סיכום יומי")

    if not dry:
        save_state(state)

if __name__ == "__main__":
    main()
