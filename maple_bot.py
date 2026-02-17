import os
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

# =========================
# 고정값(완성본)
# =========================
KST = timezone(timedelta(hours=9))

# 너가 준 값들 (완성본에 이미 삽입)
DEFAULT_SHEETS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbw730jSMIIjf8a6xPe1D8Riv8rnP-9T1vCFMqrkTB_PEUPxkWb1W72nLmnWSGUtv27O/exec"
DEFAULT_SECRET_TOKEN = "mapleland_2026_02_17_abc123xyz999"

# Mapleland API (HTML 말고 API로만 감)  ← 403 피하려고 이걸 씀
API_URL = "https://api.mapleland.gg/trade"

# 기본으로 1개만(공10 노목 +5)
DEFAULT_ITEMS = [
    {
        "name": "노가다 목장갑(+5) 공10",
        "itemCode": "1082002",
        "lowincPAD": "10",
        "highincPAD": "10",
        # 팝니다/삽니다 둘 다 나오지만, 우리는 팝니다(sell)만 최저가로 쓰기 위해 그대로 두고 필터링함
        "highUpgrade": "5",
        "highTuc": "5",
        "highPrice": "9999999999",
    }
]

# 5분
DEFAULT_INTERVAL_SEC = 300

# =========================
# 유틸
# =========================
def now_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

def env(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    if v is None or v.strip() == "":
        raise RuntimeError(f"Missing env var: {name}")
    return v

def env_optional(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v and v.strip() else default

def safe_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(x)
    except Exception:
        return None

def http_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        # 서버에서 막는 경우가 많아서 UA/Accept 지정
        "User-Agent": "Mozilla/5.0 (compatible; maple-bot/1.0; +https://railway.app)",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://mapleland.gg",
        "Referer": "https://mapleland.gg/",
    })
    return s

# =========================
# Mapleland API 호출
# =========================
def build_params(item: Dict[str, str]) -> Dict[str, str]:
    # 네가 캡쳐한 실제 요청 형태 그대로 맞춤
    return {
        "itemCode": item["itemCode"],
        "lowPrice": "",
        "highPrice": item.get("highPrice", "9999999999"),
        "lowincPAD": item.get("lowincPAD", ""),
        "highincPAD": item.get("highincPAD", ""),
        "lowincPDD": "",
        "highincPDD": "",
        "lowUpgrade": "",
        "highUpgrade": item.get("highUpgrade", ""),
        "lowTuc": "",
        "highTuc": item.get("highTuc", ""),
        "hapStatsName": "",
        "lowHapStatsValue": "0",
        "highHapStatsValue": "0",
    }

def pick_min_sell(trades: List[Dict[str, Any]]) -> Tuple[Optional[int], int]:
    """
    '팝니다' 최저가만 뽑는다.
    너가 말한 "삽니다 가격이 섞여서 최저가가 나옴" = sell/buy 섞어서 min 잡아서 생기는 문제.
    그래서 tradeType == 'sell'만 필터링.
    """
    sell_prices: List[int] = []
    for t in trades:
        if str(t.get("tradeType", "")).lower() != "sell":
            continue
        p = safe_int(t.get("itemPrice"))
        if p is not None and p > 0:
            sell_prices.append(p)
    if not sell_prices:
        return None, 0
    return min(sell_prices), len(sell_prices)

def fetch_min_sell_price(session: requests.Session, item: Dict[str, str], retries: int = 3) -> Dict[str, Any]:
    params = build_params(item)

    last_err: Optional[str] = None
    for attempt in range(1, retries + 1):
        try:
            r = session.get(API_URL, params=params, timeout=10)
            # 403이면 여기서 바로 보이게 로그 남김
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                time.sleep(1.0 * attempt)
                continue

            data = r.json()

            # 응답 구조가 2종류 가능해서 둘 다 대응
            # 1) list 바로
            # 2) { ok: true, data: [...] } 같은 래핑
            trades = None
            if isinstance(data, list):
                trades = data
            elif isinstance(data, dict):
                # 흔한 키 후보들
                for key in ("data", "trades", "items", "result"):
                    if key in data and isinstance(data[key], list):
                        trades = data[key]
                        break
                if trades is None and "tradeType" in data:
                    # 단건 dict가 들어온 경우
                    trades = [data]

            if not isinstance(trades, list):
                return {
                    "ok": False,
                    "error": f"Unexpected JSON shape: {type(data).__name__}",
                    "itemCode": item["itemCode"],
                    "itemName": item["name"],
                }

            min_price, count = pick_min_sell(trades)

            return {
                "ok": True,
                "itemCode": item["itemCode"],
                "itemName": item["name"],
                "minPrice": min_price,          # 팝니다 최저가
                "sellCount": count,             # 팝니다 매물 수(잡힌 것 기준)
                "ts": now_kst_str(),
            }

        except Exception as e:
            last_err = str(e)
            time.sleep(1.0 * attempt)

    return {
        "ok": False,
        "error": f"fetch_failed: {last_err}",
        "itemCode": item["itemCode"],
        "itemName": item["name"],
    }

# =========================
# Apps Script Web App으로 전송
# =========================
def post_to_sheets(session: requests.Session, webapp_url: str, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    body = {
        "token": token,
        "row": {
            "timestamp": payload.get("ts"),
            "side": "sell",
            "item_name": payload.get("itemName"),
            "item_code": payload.get("itemCode"),
            "min_price": payload.get("minPrice"),
            "count": payload.get("sellCount"),
            "source": "railway",
        },
    }
    r = session.post(webapp_url, json=body, timeout=15)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "error": f"non_json_response: {r.status_code} {r.text[:200]}"}

# =========================
# 아이템 로드(ENV 있으면 그걸 우선)
# =========================
def load_items() -> List[Dict[str, str]]:
    raw = os.getenv("ITEMS_JSON")
    if raw and raw.strip():
        items = json.loads(raw)
        if not isinstance(items, list):
            raise RuntimeError("ITEMS_JSON must be a JSON list")
        return items
    return DEFAULT_ITEMS

# =========================
# 메인 루프
# =========================
def main() -> None:
    webapp_url = env_optional("SHEETS_WEBAPP_URL", DEFAULT_SHEETS_WEBAPP_URL)
    token = env_optional("SECRET_TOKEN", DEFAULT_SECRET_TOKEN)
    interval = int(env_optional("INTERVAL_SEC", str(DEFAULT_INTERVAL_SEC)))

    items = load_items()

    s = http_session()
    print(f"{now_kst_str()} | START: maple bot running")
    print(f"{now_kst_str()} | items={len(items)} interval={interval}s")

    while True:
        for item in items:
            res = fetch_min_sell_price(s, item)
            if not res.get("ok"):
                print(f"{now_kst_str()} | ERROR(fetch) {res}")
                continue

            # 팝니다 최저가가 없으면(매물 0) 시트에 안 적음
            if res.get("minPrice") is None:
                print(f"{now_kst_str()} | OK(fetch) no sell listings | {res.get('itemCode')} {res.get('itemName')}")
                continue

            print(f"{now_kst_str()} | OK(fetch) sell_min={res['minPrice']} sell_count={res['sellCount']}")

            sheet_res = post_to_sheets(s, webapp_url, token, res)
            if not sheet_res.get("ok"):
                print(f"{now_kst_str()} | ERROR(sheet) {sheet_res}")
            else:
                print(f"{now_kst_str()} | OK(sheet) {sheet_res}")

        time.sleep(interval)

if __name__ == "__main__":
    main()
