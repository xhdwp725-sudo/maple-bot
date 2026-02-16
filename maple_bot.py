import time
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

# 네 값으로 고정 (Railway 변수 말고, PC에서 바로 실행용)
SECRET_TOKEN = "mapleland_2026_02_17_abc123xyz999"
SHEETS_WEBAPP_URL = "여기에 너의 Apps Script exec URL 넣어"  # 예: https://script.google.com/macros/s/XXXXX/exec

ITEM_CODE = "1082002"
ITEM_NAME = "노가다 목장갑 (+5)"
ITEM_URL = "https://mapleland.gg/item/1082002?lowPrice=&highPrice=9999999999&lowincPAD=10&highincPAD=10&lowincPDD=&highincPDD=&lowUpgrade=&highUpgrade=5&lowTuc=&highTuc=&hapStatsName=&lowHapStatsValue=0&highHapStatsValue=0"

INTERVAL_SEC = 300

PRICE_RE = re.compile(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)")

def now_kst_str():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

def parse_prices(text: str):
    out = []
    for m in PRICE_RE.finditer(text.replace(" ", "")):
        out.append(int(m.group(1).replace(",", "")))
    return out

def extract_sell_min(html: str):
    # “팝니다” 영역만 최대한 잡아서 가격만 뽑기 (페이지 구조 바뀌면 여기만 수정)
    soup = BeautifulSoup(html, "html.parser")

    sell_block = None
    for el in soup.find_all(["div", "span", "h1", "h2", "h3"]):
        if el.get_text(strip=True) == "팝니다":
            sell_block = el.parent
            break

    if not sell_block:
        # 그래도 못 찾으면 전체에서 가격을 찾지 말고 실패 처리
        return None, None

    text = sell_block.get_text(" ", strip=True)
    prices = parse_prices(text)
    if not prices:
        return None, None
    return min(prices), len(prices)

def post_to_sheet(min_price: int, sell_count: int):
    payload = {
        "token": SECRET_TOKEN,
        "timestamp": now_kst_str(),
        "item_name": ITEM_NAME,
        "item_code": ITEM_CODE,
        "min_price": int(min_price),
        "sell_count": int(sell_count),
        "query": ITEM_URL,
    }
    r = requests.post(SHEETS_WEBAPP_URL, json=payload, timeout=20)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "http_status": r.status_code, "text": r.text[:300]}

def main():
    print(now_kst_str(), "| start")

    while True:
        try:
            r = requests.get(
                ITEM_URL,
                timeout=25,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
                },
            )
            r.raise_for_status()

            min_price, sell_count = extract_sell_min(r.text)
            if min_price is None:
                print(now_kst_str(), "| WARN | sell_min not found")
            else:
                out = post_to_sheet(min_price, sell_count or 0)
                if out.get("ok"):
                    print(now_kst_str(), f"| OK | sell_min={min_price} sell_count={sell_count}")
                else:
                    print(now_kst_str(), f"| ERROR | webapp returned {out}")

        except Exception as e:
            print(now_kst_str(), "| ERROR |", e)

        time.sleep(INTERVAL_SEC)

if __name__ == "__main__":
    main()
