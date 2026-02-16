import os
import json
import time
import datetime as dt
import requests
from typing import Any, Dict, List, Optional

API_BASE = "https://api.mapleland.gg/trade"

INTERVAL_SEC = int(os.getenv("INTERVAL_SEC", "300"))  # 5분 기본
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "").strip()
SHEETS_WEBAPP_URL = os.getenv("SHEETS_WEBAPP_URL", "").strip()

DEFAULT_ITEMS = [
    {
        "item_code": "1082002",
        "item_name": "노가다 목장갑 (+5) 공10",
        # mapleland 페이지에서 쓰던 필터를 query로 넣어두면, API 호출에도 그대로 붙여서 동일 조건으로 수집 가능
        # 너가 원한 조건: incPAD=10, upgrade 5, tuc 5 등
        "query": "highPrice=9999999999&lowincPAD=10&highincPAD=10&highUpgrade=5&highTuc=5&lowHapStatsValue=0&highHapStatsValue=0",
    }
]

def load_items() -> List[Dict[str, str]]:
    raw = os.getenv("ITEMS_JSON", "").strip()
    if not raw:
        return DEFAULT_ITEMS
    try:
        items = json.loads(raw)
        if not isinstance(items, list) or not items:
            return DEFAULT_ITEMS
        normalized = []
        for it in items:
            if not isinstance(it, dict):
                continue
            item_code = str(it.get("item_code", "")).strip()
            item_name = str(it.get("item_name", "")).strip() or item_code
            query = str(it.get("query", "")).strip()
            if not item_code:
                continue
            normalized.append({"item_code": item_code, "item_name": item_name, "query": query})
        return normalized or DEFAULT_ITEMS
    except Exception:
        return DEFAULT_ITEMS

def now_kst_str() -> str:
    # Railway는 UTC일 수 있으니 표기만 KST로
    kst = dt.timezone(dt.timedelta(hours=9))
    return dt.datetime.now(tz=kst).strftime("%Y-%m-%d %H:%M:%S")

def build_api_url(item_code: str, query: str) -> str:
    if query:
        if query.startswith("?"):
            query = query[1:]
        return f"{API_BASE}?itemCode={item_code}&{query}"
    return f"{API_BASE}?itemCode={item_code}"

def fetch_trade(item_code: str, query: str) -> Optional[Dict[str, Any]]:
    url = build_api_url(item_code, query)
    res = requests.get(url, timeout=15)
    res.raise_for_status()
    data = res.json()
    # 응답이 리스트로 오는 케이스/딕트로 오는 케이스 모두 대비
    return {"url": url, "data": data}

def parse_min_price(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = payload["data"]

    # 1) 리스트 응답일 때: itemPrice 최저값 찾기
    if isinstance(data, list):
        prices = []
        for row in data:
            if isinstance(row, dict) and row.get("itemPrice") is not None:
                try:
                    prices.append(int(row["itemPrice"]))
                except Exception:
                    pass
        min_price = min(prices) if prices else None
        sell_count = len(prices) if prices else 0
        return {"min_price": min_price, "sell_count": sell_count}

    # 2) 딕트 응답일 때: 흔한 키들 탐색
    if isinstance(data, dict):
        # items / list / data 같은 내부 구조를 뒤져서 가격 리스트 추출
        candidates = []
        for key in ["items", "list", "data", "result"]:
            v = data.get(key)
            if isinstance(v, list):
                candidates = v
                break
        prices = []
        if candidates:
            for row in candidates:
                if isinstance(row, dict):
                    for pk in ["itemPrice", "price", "minPrice"]:
                        if row.get(pk) is not None:
                            try:
                                prices.append(int(row[pk]))
                                break
                            except Exception:
                                pass
        # 혹시 단일 값 형태
        if not prices:
            for pk in ["minPrice", "itemPrice", "price"]:
                if data.get(pk) is not None:
                    try:
                        prices = [int(data[pk])]
                        break
                    except Exception:
                        pass

        min_price = min(prices) if prices else None
        sell_count = len(prices) if prices else 0
        return {"min_price": min_price, "sell_count": sell_count}

    return {"min_price": None, "sell_count": 0}

def post_to_sheets(item_name: str, item_code: str, query: str, min_price: int, sell_count: int) -> Dict[str, Any]:
    body = {
        "token": SECRET_TOKEN,
        "timestamp": now_kst_str(),
        "item_name": item_name,
        "item_code": str(item_code),
        "query": query,
        "min_price": int(min_price),
        "sell_count": int(sell_count),
    }
    res = requests.post(SHEETS_WEBAPP_URL, json=body, timeout=20)
    # Apps Script가 200이 아니어도 JSON을 주는 경우가 많아서 우선 파싱
    try:
        j = res.json()
    except Exception:
        j = {"ok": False, "error": f"non_json_response status={res.status_code}", "text": res.text[:200]}
    return {"status": res.status_code, "json": j}

def validate_env() -> None:
    if not SECRET_TOKEN:
        raise RuntimeError("SECRET_TOKEN is empty (Railway Variables에 SECRET_TOKEN 필요)")
    if not SHEETS_WEBAPP_URL:
        raise RuntimeError("SHEETS_WEBAPP_URL is empty (Railway Variables에 SHEETS_WEBAPP_URL 필요)")
    if not SHEETS_WEBAPP_URL.startswith("https://script.google.com/macros/s/"):
        raise RuntimeError("SHEETS_WEBAPP_URL looks wrong. Apps Script Web App URL( /exec ) 넣어야 함")

def main_loop() -> None:
    validate_env()
    items = load_items()

    print("수집 시작")
    print(f"ITEMS={len(items)} | interval={INTERVAL_SEC}s")

    while True:
        try:
            for it in items:
                item_code = it["item_code"]
                item_name = it["item_name"]
                query = it.get("query", "")

                payload = fetch_trade(item_code, query)
                api_url = payload["url"]
                parsed = parse_min_price(payload)

                min_price = parsed["min_price"]
                sell_count = parsed["sell_count"]

                if min_price is None:
                    print(f"[{now_kst_str()}] {item_name}({item_code}) 매물 없음 (sell=0) | API={api_url}")
                    continue

                print(f"[{now_kst_str()}] {item_name}({item_code}) 판매 최저가: {min_price:,} (sell={sell_count})")
                resp = post_to_sheets(item_name, item_code, query, min_price, sell_count)

                if not resp["json"].get("ok", False):
                    print(f"ERROR | Sheets WebApp returned error: {resp['json']}")
                else:
                    # 정상
                    pass

            time.sleep(INTERVAL_SEC)

        except Exception as e:
            print(f"ERROR | loop error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main_loop()
