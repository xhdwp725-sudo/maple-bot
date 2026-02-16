import json
import os
import time
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))


def now_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def env(name: str, default: Optional[str] = None, required: bool = False) -> str:
    v = os.getenv(name, default)
    if (v is None or v == "") and required:
        raise RuntimeError(f"Missing env var: {name}")
    return v or ""


@dataclass
class Item:
    item_code: str
    item_name: str
    query: str  # full URL or query string


def load_items() -> List[Item]:
    """
    Priority:
      1) ITEMS_JSON env (JSON array)
      2) ./items.json file (JSON array)
      3) fallback sample (doesn't crash)
    """
    raw = os.getenv("ITEMS_JSON", "").strip()
    if not raw:
        if os.path.exists("items.json"):
            with open("items.json", "r", encoding="utf-8") as f:
                raw = f.read().strip()

    if not raw:
        # fallback (너가 나중에 Railway에 ITEMS_JSON 넣으면 자동으로 이건 안 씀)
        return [
            Item(
                item_code="1082002",
                item_name="노가다 목장갑 (+5)",
                query="https://mapleland.gg/item/1082002?lowPrice=&highPrice=9999999999&lowincPAD=10&highincPAD=10&lowincPDD=&highincPDD=&lowUpgrade=&highUpgrade=5&lowTuc=&highTuc=&hapStatsName=&lowHapStatsValue=0&highHapStatsValue=0"
            )
        ]

    data = json.loads(raw)
    items: List[Item] = []
    for x in data:
        items.append(Item(
            item_code=str(x.get("item_code", "")).strip(),
            item_name=str(x.get("item_name", "")).strip(),
            query=str(x.get("query", "")).strip(),
        ))
    # basic validation
    items = [it for it in items if it.item_code and it.item_name and it.query]
    if not items:
        raise RuntimeError("ITEMS_JSON parsed but no valid items found.")
    return items


PRICE_RE = re.compile(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)")

def parse_int_price(text: str) -> Optional[int]:
    m = PRICE_RE.search(text.replace(" ", ""))
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def extract_sell_min_from_html(html: str) -> Tuple[Optional[int], Optional[int]]:
    """
    '팝니다' 컬럼만 보고 최저가(min_price)와 판매글 수(sell_count)를 뽑는다.
    페이지 구조가 바뀌면 여기만 손보면 됨.
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1) "팝니다" 섹션 찾기 (텍스트 기반)
    sell_section = None
    for h in soup.find_all(["div", "h1", "h2", "h3", "span"]):
        if h.get_text(strip=True) == "팝니다":
            # 보통 이 헤더의 부모/근처가 리스트 컨테이너
            sell_section = h.parent
            break
    if sell_section is None:
        # fallback: 전체에서 '팝니다'가 있는 큰 블록을 찾기
        txt = soup.get_text(" ", strip=True)
        # 못 찾으면 None
        return None, None

    # 2) 해당 섹션 내부에서 가격 후보 수집
    text_block = sell_section.get_text(" ", strip=True)

    # 가격들 추출
    prices = []
    for m in PRICE_RE.finditer(text_block):
        prices.append(int(m.group(1).replace(",", "")))

    min_price = min(prices) if prices else None

    # 판매글 수(대충) = 가격 후보 개수로 근사 (페이지 구조 정확히 알면 여기 개선)
    sell_count = len(prices) if prices else None

    return min_price, sell_count


def post_to_sheets(webapp_url: str, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.post(webapp_url, json={"token": token, **payload}, timeout=20)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "http_status": r.status_code, "text": r.text[:500]}


def main() -> None:
    # required
    token = env("SECRET_TOKEN", required=True)
    webapp_url = env("SHEETS_WEBAPP_URL", required=True)

    # optional
    interval = int(env("INTERVAL_SEC", "300") or "300")

    items = load_items()

    print(f"{now_kst_str()} | INFO | ITEMS={len(items)} interval={interval}s")

    while True:
        for it in items:
            try:
                # fetch
                resp = requests.get(it.query, timeout=25, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; maple-bot/1.0)"
                })
                resp.raise_for_status()

                # parse sell only
                min_price, sell_count = extract_sell_min_from_html(resp.text)

                if min_price is None:
                    print(f"{now_kst_str()} | WARN | {it.item_name}({it.item_code}) sell_min not found")
                    continue

                payload = {
                    "timestamp": now_kst_str(),
                    "item_name": it.item_name,
                    "item_code": it.item_code,
                    "min_price": int(min_price),
                    "sell_count": int(sell_count) if sell_count is not None else "",
                    "query": it.query,
                }

                out = post_to_sheets(webapp_url, token, payload)

                if not out.get("ok"):
                    print(f"{now_kst_str()} | ERROR | Sheets WebApp returned error: {out}")
                else:
                    print(f"{now_kst_str()} | OK | {it.item_name}({it.item_code}) sell_min={min_price} sell_count={sell_count}")

            except Exception as e:
                print(f"{now_kst_str()} | ERROR | loop error: {e}")

        time.sleep(interval)


if __name__ == "__main__":
    main()
