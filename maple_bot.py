import json
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests


KST = timezone(timedelta(hours=9))


def now_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def env(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    if v is None or v == "":
        raise RuntimeError(f"Missing env var: {name}")
    return v


def safe_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(x)
    except Exception:
        return None


def extract_min_sell_price(data: Dict[str, Any]) -> Tuple[Optional[int], int]:
    """
    Returns (min_sell_price, sell_count).

    Supports common shapes:
      1) {"sell": [...], "buy": [...]}
      2) {"sellList": [...], "buyList": [...]}
      3) {"trades": [...]} where each item indicates side/type
      4) {"items": [...]} similarly

    Trade item may have price fields like:
      - "price", "meso", "amount", "tradePrice", "value"
    """

    def get_price(x: Dict[str, Any]) -> Optional[int]:
        for k in ("price", "meso", "amount", "tradePrice", "value"):
            if k in x and x[k] is not None:
                p = safe_int(x[k])
                if isinstance(p, int):
                    return p
        return None

    def is_sell(x: Dict[str, Any]) -> Optional[bool]:
        for k in ("type", "tradeType", "side", "buySell", "mode"):
            v = x.get(k)
            if isinstance(v, str):
                vv = v.strip().lower()
                if vv in ("sell", "seller", "s", "판매", "sellorder", "sell_order", "ask"):
                    return True
                if vv in ("buy", "buyer", "b", "구매", "buyorder", "buy_order", "bid"):
                    return False
        if x.get("isSell") is True:
            return True
        if x.get("isBuy") is True:
            return False
        return None

    sell_list: Optional[List[Any]] = None

    # split lists
    for key in ("sell", "sellList", "sells", "sellItems"):
        if isinstance(data.get(key), list):
            sell_list = data[key]
            break

    # unified list
    if sell_list is None:
        for key in ("trades", "items", "list", "data", "result"):
            if isinstance(data.get(key), list):
                candidates = data[key]
                sell_list = []
                for x in candidates:
                    if isinstance(x, dict):
                        flag = is_sell(x)
                        if flag is True:
                            sell_list.append(x)
                break

    if not sell_list:
        return (None, 0)

    prices: List[int] = []
    for x in sell_list:
        if isinstance(x, dict):
            p = get_price(x)
            if isinstance(p, int):
                prices.append(p)

    if not prices:
        return (None, len(sell_list))

    return (min(prices), len(sell_list))


def build_trade_url(item_code: str, query: str) -> str:
    """
    너가 이미 쓰고 있는 mapleland.gg 파라미터 스트링(query)을 그대로 붙여서 호출하는 방식.
    query 예시:
      "lowPrice=&highPrice=9999999999&lowincPAD=10&highincPAD=10&lowincPDD=&highincPDD=&lowUpgrade=&highUpgrade=&lowTuc=&highTuc=5&hapStatsName=&lowHapStatsValue=0&highHapStatsValue=0"
    """
    base = f"https://api.mapleland.gg/trade"
    if query.startswith("?"):
        query = query[1:]
    return f"{base}?{query}&itemCode={item_code}"


def post_to_sheets(webapp_url: str, token: str, payload: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
    r = requests.post(webapp_url, json={"token": token, **payload}, timeout=timeout)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "error": f"non_json_response status={r.status_code} text={r.text[:200]}"}


def fetch_trade_json(url: str, timeout: int = 15) -> Dict[str, Any]:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def load_items() -> List[Dict[str, str]]:
    """
    ITEMS_JSON 환경변수에 아래 같은 형태로 넣는 걸 전제로 함.
    [
      {"item_code":"1082002","item_name":"노가다 목장갑 (+5) 공10","query":"lowPrice=&highPrice=9999999999&lowincPAD=10&highincPAD=10&lowincPDD=&highincPDD=&lowUpgrade=&highUpgrade=&lowTuc=&highTuc=5&hapStatsName=&lowHapStatsValue=0&highHapStatsValue=0"},
      ...
    ]
    """
    raw = env("ITEMS_JSON")
    items = json.loads(raw)
    if not isinstance(items, list) or len(items) == 0:
        raise RuntimeError("ITEMS_JSON must be a non-empty list")
    out: List[Dict[str, str]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        item_code = str(it.get("item_code", "")).strip()
        item_name = str(it.get("item_name", "")).strip()
        query = str(it.get("query", "")).strip()
        if not item_code or not item_name or not query:
            raise RuntimeError(f"Bad item entry in ITEMS_JSON: {it}")
        out.append({"item_code": item_code, "item_name": item_name, "query": query})
    return out


def main():
    secret_token = env("SECRET_TOKEN")
    sheets_webapp_url = env("SHEETS_WEBAPP_URL")
    interval = int(os.getenv("INTERVAL_SECONDS", "300"))

    items = load_items()

    print(f"{now_kst_str()} | INFO | start | ITEMS={len(items)} | interval={interval}s")

    while True:
        for it in items:
            item_code = it["item_code"]
            item_name = it["item_name"]
            query = it["query"]

            url = build_trade_url(item_code, query)

            try:
                data = fetch_trade_json(url)
                min_sell, sell_count = extract_min_sell_price(data)

                if min_sell is None:
                    print(f"{now_kst_str()} | WARN | no_sell_price | {item_name}({item_code})")
                    continue

                payload = {
                    "timestamp": now_kst_str(),
                    "item_name": item_name,
                    "item_code": item_code,
                    "query": query,
                    "min_price": int(min_sell),
                    "sell_count": int(sell_count),
                }

                resp = post_to_sheets(sheets_webapp_url, secret_token, payload)

                if not resp.get("ok"):
                    print(f"{now_kst_str()} | ERROR | sheets | {item_name}({item_code}) | resp={resp}")
                else:
                    print(f"{now_kst_str()} | INFO | {item_name}({item_code}) | sell_min={min_sell:,} | sell_cnt={sell_count}")

            except Exception as e:
                print(f"{now_kst_str()} | ERROR | loop | {item_name}({item_code}) | {e}")

        time.sleep(interval)


if __name__ == "__main__":
    main()
