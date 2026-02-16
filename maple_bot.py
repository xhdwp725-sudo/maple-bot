import os
import time
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests


# =========================
# 설정: 여기만 네 아이템들로 채우면 됨
# (item_code는 기록용/정렬용이라 없어도 되는데 넣어두면 좋음)
# api_url은 네가 크롬 네트워크에서 잡은 api.mapleland.gg/trade?... 를 그대로 넣으면 됨
# =========================
ITEMS = [
    {
        "item_name": "노가다 목장갑 (+5) 공10",
        "item_code": "1082002",
        "api_url": "https://api.mapleland.gg/trade?highPrice=9999999999&lowincPAD=10&highincPAD=10&highUpgrade=5&highTuc=5&lowHapStatsValue=0&highHapStatsValue=0&itemCode=1082002",
    },
    # 아래에 이런 식으로 9개까지 추가
    # {
    #     "item_name": "예시 아이템",
    #     "item_code": "1234567",
    #     "api_url": "https://api.mapleland.gg/trade?...&itemCode=1234567",
    # },
]


# =========================
# 기본 설정
# =========================
KST = timezone(timedelta(hours=9))
POLL_SECONDS = 300          # 5분마다
HTTP_TIMEOUT = 20
RETRY = 3
RETRY_SLEEP = 2

# 시트 전송(웹앱)
# Railway Variables(환경변수)로 넣거나, Railway secrets 파일(/secrets/NAME)로 들어와도 읽히게 처리함
REQUIRED_SECRETS = ["SHEETS_WEBAPP_URL", "SECRET_TOKEN"]


# =========================
# 로깅
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("maple-bot")


# =========================
# 유틸: env 또는 /secrets 파일 둘 다 지원
# =========================
def read_secret(name: str) -> str:
    v = os.getenv(name)
    if v and v.strip():
        return v.strip()

    secret_path = f"/secrets/{name}"
    if os.path.exists(secret_path):
        with open(secret_path, "r", encoding="utf-8") as f:
            return f.read().strip()

    raise RuntimeError(f"Missing secret: {name} (env or {secret_path})")


def http_get_json(url: str) -> Any:
    last_err = None
    for _ in range(RETRY):
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            # 응답이 JSON이 아닐 때도 있어서 try/catch
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(RETRY_SLEEP)
    raise RuntimeError(f"GET failed: {url} | {last_err}")


def http_post_json(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    last_err = None
    for _ in range(RETRY):
        try:
            r = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            # GAS는 text로 주는 경우도 있어서 대응
            try:
                return r.json()
            except Exception:
                return {"ok": True, "raw": r.text}
        except Exception as e:
            last_err = e
            time.sleep(RETRY_SLEEP)
    raise RuntimeError(f"POST failed: {url} | {last_err}")


# =========================
# "팝니다(판매)"만 필터링
#  - mapleland API가 buy/sell 섞여 오는 케이스 대응
#  - 필드명이 바뀌거나 케이스가 달라도 최대한 잡히게 '휴리스틱'으로 처리
# =========================
def is_sell_record(rec: Dict[str, Any]) -> bool:
    # 1) 명시 필드들(가능성 높은 순)
    for key in ["tradeType", "type", "side", "orderType", "dealType", "kind"]:
        if key in rec and rec[key] is not None:
            v = str(rec[key]).strip().lower()
            # sell로 해석되는 값들
            if v in ["sell", "selling", "s", "ask", "offer", "판매", "팝니다"]:
                return True
            if v in ["buy", "buying", "b", "bid", "구매", "삽니다"]:
                return False

    # 2) boolean류
    for key in ["isSell", "sell", "isSelling"]:
        if key in rec:
            try:
                return bool(rec[key]) is True
            except Exception:
                pass

    # 3) 텍스트/메시지에 '팝니다'가 들어가는 경우
    for key in ["message", "memo", "comment", "desc", "description", "content"]:
        if key in rec and rec[key]:
            v = str(rec[key])
            if "팝니다" in v:
                return True
            if "삽니다" in v:
                return False

    # 4) 마지막 fallback:
    #    판매글에는 보통 "seller" 비슷한 필드가 있거나 buyer가 비어있는 경우가 많음
    seller_like = any(k in rec for k in ["seller", "sellerName", "sellerId"])
    buyer_like = any(k in rec for k in ["buyer", "buyerName", "buyerId"])
    if seller_like and not buyer_like:
        return True

    # 그래도 판별 불가면 "판매로 간주하지 않음" (안전하게)
    return False


def extract_price(rec: Dict[str, Any]) -> Optional[int]:
    # 가격 필드 후보들
    for key in ["itemPrice", "price", "tradePrice", "amount", "meso", "value"]:
        if key in rec and rec[key] is not None:
            try:
                return int(rec[key])
            except Exception:
                pass
    return None


def compute_min_sell_price(data: Any) -> Tuple[Optional[int], int, int]:
    """
    returns: (min_price, sell_count, total_count)
    """
    if not isinstance(data, list):
        return (None, 0, 0)

    total = len(data)
    sell_prices: List[int] = []

    for rec in data:
        if not isinstance(rec, dict):
            continue
        if not is_sell_record(rec):
            continue
        p = extract_price(rec)
        if p is None:
            continue
        sell_prices.append(p)

    if not sell_prices:
        return (None, len(sell_prices), total)

    return (min(sell_prices), len(sell_prices), total)


# =========================
# Google Sheets WebApp으로 전송
# payload 형식은 아래처럼 보냄:
# {
#   token: "...",
#   rows: [
#     {timestamp, item_name, item_code, min_price, sell_count, total_count, api_url}
#   ]
# }
# =========================
def send_rows_to_sheets(webapp_url: str, token: str, rows: List[Dict[str, Any]]) -> None:
    payload = {"token": token, "rows": rows}
    resp = http_post_json(webapp_url, payload)
    # GAS 응답이 ok true 형태면 정상
    if isinstance(resp, dict) and resp.get("ok") is False:
        raise RuntimeError(f"Sheets WebApp returned error: {resp}")
    log.info(f"Sheets push ok | rows={len(rows)}")


def now_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def main_once(webapp_url: str, token: str) -> None:
    rows: List[Dict[str, Any]] = []
    ts = now_kst_str()

    for item in ITEMS:
        name = item.get("item_name", "")
        code = item.get("item_code", "")
        api_url = item.get("api_url", "")

        if not api_url:
            log.warning(f"skip: missing api_url | {name}")
            continue

        try:
            data = http_get_json(api_url)
            min_price, sell_count, total_count = compute_min_sell_price(data)

            # 기록 row
            row = {
                "timestamp": ts,
                "item_name": name,
                "item_code": code,
                "min_price": min_price if min_price is not None else "",
                "sell_count": sell_count,
                "total_count": total_count,
                "api_url": api_url,
            }
            rows.append(row)

            if min_price is None:
                log.info(f"[{ts}] {name} | 판매 매물 없음 (total={total_count})")
            else:
                log.info(f"[{ts}] {name} | 판매 최저가: {min_price:,} (sell={sell_count}/{total_count})")

        except Exception as e:
            log.error(f"[{ts}] fetch fail | {name} | {e}")

    if rows:
        send_rows_to_sheets(webapp_url, token, rows)


def validate_config() -> None:
    if not ITEMS:
        raise RuntimeError("ITEMS is empty. Add at least 1 item.")

    for i, item in enumerate(ITEMS, start=1):
        if not item.get("api_url"):
            raise RuntimeError(f"ITEMS[{i}] missing api_url")

    # secrets 체크
    for s in REQUIRED_SECRETS:
        _ = read_secret(s)


if __name__ == "__main__":
    validate_config()
    sheets_webapp_url = read_secret("SHEETS_WEBAPP_URL")
    secret_token = read_secret("SECRET_TOKEN")

    log.info("수집 시작")
    log.info(f"ITEMS={len(ITEMS)} | interval={POLL_SECONDS}s")

    while True:
        try:
            main_once(sheets_webapp_url, secret_token)
        except Exception as e:
            log.error(f"loop error: {e}")
        time.sleep(POLL_SECONDS)
