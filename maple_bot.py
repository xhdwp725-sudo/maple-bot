import os
import re
import time
import json
from datetime import datetime, timedelta, timezone

import requests

# =========================
# ✅ 고정 설정 (네 값으로 이미 주입됨)
# =========================
DEFAULT_SECRET_TOKEN = "mapleland_2026_02_17_abc123xyz999"
DEFAULT_SHEETS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbw730jSMIIjf8a6xPe1D8Riv8rnP-9T1vCFMqrkTB_PEUPxkWb1W72nLmnWSGUtv27O/exec"

# 공10 노목(노가다 목장갑) item_code
DEFAULT_ITEMS = [
    {
        "item_code": "1082002",
        "item_name": "노가다 목장갑(+5)",
        "side": "sell",  # 팝니다만
    }
]

# 몇 초마다 돌릴지 (Railway 환경변수 INTERVAL_SEC 있으면 그걸 사용)
DEFAULT_INTERVAL_SEC = 300

KST = timezone(timedelta(hours=9))


def now_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def env(name: str, default: str) -> str:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip()


def load_items() -> list[dict]:
    """
    ✅ ITEMS_JSON 환경변수 없어도 동작하게 처리
    - 있으면 그걸 우선 사용
    - 없으면 DEFAULT_ITEMS(공10 노목)만 사용
    """
    raw = os.getenv("ITEMS_JSON")
    if raw and raw.strip():
        try:
            data = json.loads(raw)
            if isinstance(data, list) and len(data) > 0:
                normalized = []
                for it in data:
                    if not isinstance(it, dict):
                        continue
                    item_code = str(it.get("item_code", "")).strip()
                    item_name = str(it.get("item_name", "")).strip() or "unknown"
                    side = str(it.get("side", "sell")).strip().lower()
                    if item_code:
                        normalized.append({"item_code": item_code, "item_name": item_name, "side": side})
                if normalized:
                    return normalized
        except Exception:
            pass
    return DEFAULT_ITEMS


def fetch_html(url: str) -> tuple[int, str]:
    """
    403(Forbidden) 최대한 피하려고 브라우저 헤더를 강하게 넣음
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://mapleland.gg/",
        "Connection": "keep-alive",
    }
    r = requests.get(url, headers=headers, timeout=25)
    return r.status_code, r.text


def extract_min_sell_price(html: str) -> tuple[int | None, int]:
    """
    ✅ 핵심: '팝니다' 영역만 잘라서 가격만 뽑음
    - '팝니다' ~ '삽니다' 구간에서만 가격 추출
    - 가격은 47,000,000 형태를 숫자로 변환
    반환: (min_price, sell_count)
    """
    # 영역 자르기 (팝니다 ~ 삽니다)
    sell_start = html.find("팝니다")
    if sell_start == -1:
        return None, 0

    buy_start = html.find("삽니다", sell_start)
    if buy_start == -1:
        segment = html[sell_start:]
    else:
        segment = html[sell_start:buy_start]

    # 가격 패턴 (콤마 포함 숫자)
    prices = re.findall(r"(\d{1,3}(?:,\d{3})+)", segment)
    nums = []
    for p in prices:
        try:
            nums.append(int(p.replace(",", "")))
        except Exception:
            continue

    if not nums:
        return None, 0

    return min(nums), len(nums)


def post_to_sheets(webapp_url: str, token: str, payload: dict) -> dict:
    r = requests.post(
        webapp_url,
        json={"token": token, **payload},
        timeout=25,
    )
    r.raise_for_status()
    return r.json()


def run_once(item: dict, webapp_url: str, token: str) -> None:
    item_code = item["item_code"]
    item_name = item["item_name"]
    side = item.get("side", "sell").lower()

    # Mapleland 아이템 페이지 (네가 쓰던 필터 그대로 유지)
    url = (
        f"https://mapleland.gg/item/{item_code}"
        f"?lowPrice=&highPrice=9999999999"
        f"&lowincPAD=10&highincPAD=10"
        f"&lowincPDD=&highincPDD="
        f"&lowUpgrade=&highUpgrade=5"
        f"&lowTuc=&highTuc=5"
        f"&hapStatsName=&lowHapStatsValue=0&highHapStatsValue=0"
    )

    status, html = fetch_html(url)
    if status == 403:
        # 여기서 403이면 사이트가 봇 차단하는 상태
        print(f"{now_kst_str()} | ERROR | 403 Forbidden for url: {url}")
        return
    if status >= 400:
        print(f"{now_kst_str()} | ERROR | HTTP {status} for url: {url}")
        return

    min_price, sell_count = extract_min_sell_price(html)
    if min_price is None:
        print(f"{now_kst_str()} | ERROR | could not parse sell prices (팝니다) for item_code={item_code}")
        return

    payload = {
        "timestamp": now_kst_str(),
        "item_name": item_name,
        "item_code": str(item_code),
        "side": side,                 # ✅ sell 고정
        "min_price": int(min_price),
        "sell_count": int(sell_count),
        "source": "railway-bot",
    }

    res = post_to_sheets(webapp_url, token, payload)
    print(f"{now_kst_str()} | OK | posted: {payload['item_code']} min_sell={payload['min_price']} sell_count={sell_count} | res={res}")


def main() -> None:
    token = env("SECRET_TOKEN", DEFAULT_SECRET_TOKEN)
    webapp_url = env("SHEETS_WEBAPP_URL", DEFAULT_SHEETS_WEBAPP_URL)

    interval_sec = DEFAULT_INTERVAL_SEC
    v = os.getenv("INTERVAL_SEC")
    if v and v.strip().isdigit():
        interval_sec = int(v.strip())

    items = load_items()

    print(f"{now_kst_str()} | START | ITEMS={len(items)} interval={interval_sec}s")
    while True:
        for it in items:
            try:
                run_once(it, webapp_url, token)
            except Exception as e:
                print(f"{now_kst_str()} | ERROR | loop error: {repr(e)}")
        time.sleep(interval_sec)


if __name__ == "__main__":
    main()
