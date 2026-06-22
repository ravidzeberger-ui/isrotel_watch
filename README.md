# isrotel_watch — צייד דילי סופ"ש של ישרוטל

מנטר את עמוד **"דקה 90"** של ישרוטל (`/deals/special-sale/main/`) כמה פעמים ביום,
ומתריע בטלגרם **רק** כשמופיע דיל סופ"ש שעומד בקריטריונים — בשקט מוחלט בשאר הזמן.

## הקריטריונים (ברירת מחדל)
- **סופ"ש:** חמישי–שבת (2 לילות, לילות חמישי+שישי)
- **מחיר:** עד ~3,000 ₪ לזוג לסופ"ש (≈ 1,500 ₪/לילה)
- **יעדים:** כל הארץ **חוץ מאילת**
- **התראה אחת בלבד לכל דיל** (dedup לפי `saleid`) — בלי הצפה

לשינוי: ערוך את הקבועים בראש [`isrotel_watch.py`](isrotel_watch.py)
(`PER_NIGHT_MAX`, `WEEKEND_TOTAL_MAX`, `WEEKEND_NIGHTS`, `EILAT_LOC_CODES`).

## הרצה מקומית
```bash
pip install -r requirements.txt
cp .env.example .env          # מלא TG_BOT_TOKEN ו-TG_CHAT_ID
python isrotel_watch.py --dry-run   # בדיקה: לא שולח, רק מדפיס
python isrotel_watch.py             # אמיתי: שולח טלגרם על דילים חדשים
```

## הגדרת טלגרם
1. בטלגרם דבר עם **@BotFather** → `/newbot` → קבל **טוקן**.
2. שלח הודעה כלשהי לבוט החדש.
3. גלוש ל-`https://api.telegram.org/bot<TOKEN>/getUpdates` → מצא `"chat":{"id":...}` = ה-`TG_CHAT_ID`.

## פריסה
- **GitHub Actions** (מומלץ): ראה [`.github/workflows/watch.yml`](.github/workflows/watch.yml).
  הוסף `TG_BOT_TOKEN` ו-`TG_CHAT_ID` כ-Secrets בריפו. רץ 5 פעמים ביום, שומר מצב אוטומטית.
- **Task Scheduler (שרת/לפטוף):** הרץ `python isrotel_watch.py` כל כמה שעות.

## איך זה עובד
`fetch_deals()` מושך את העמוד ומפענח את כרטיסי `article.card--deal` →
`matches()` מסנן (סף + סופ"ש + לא-אילת) → `state.json` מונע התראה כפולה →
`send_telegram()` שולח. הלוג ב-`run.log`.
