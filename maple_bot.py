import os
import time
from datetime import datetime, timezone, timedelta

import requests


KST = timezone(timedelta(hours=9))

# ✅ 네가 준 "정답 API"
API_URL = "https://api.mapleland.gg/trade?itemCode=1082002"

# 5분마다
INTERVAL_SEC = 300


def is_sell_trade(obj: dict) -> bool:
    """
    서버 응답에 따라 키 이름이 다를 수 있어서,
    '팝니다' 성격으로 보이는 케이스를 최대한 폭넓게 잡는다.
    (그래도 서버가 완전 다른 형태면 로그로 확인 가능하게 해둠)
    """
    # 1) 가장 흔한 케이스들
    for k in ("tradeType", "type", "side", "direction"):
        v = obj.get(k)
        if v is None:
            continue
        # 문자열형
        if isinstance(v, str):
            s = v.lower()
            if s in ("sell", "seller", "s", "sale"):
                return True
            if s in ("buy", "buyer", "b"):
                return False
        # 숫자형 (0/1 류)
        if isinstance(v, (int, float)):
            # 보통 0=SELL, 1=BUY 혹은 반대인데 서비스마다 다름.
            # 여기선 안전하게: SELL로 확정되는 값만 True, BUY로 확정되는 값만 False
            # (애매하면 아래 fallback로 넘김)
            if v == 0:
                return True
            if v == 1:
                return False

    # 2) boolean 플래그
    for k in ("isSell", "sell", "isSelling"):
        v = obj.get(k)
        if isinstance(v, bool):
            return v

    # 3) fallback: 구매글에만 있는 필드/판매글에만 있는 필드가 있으면 판별
    # (여긴 데이터 보고 튜닝 가능)
    for k in ("buyMessage", "wantToBuy", "buyer"):
        if k in obj and obj.get(k):
            return False
    for k in ("sellMessage", "selling", "seller"):
        if k in obj and obj.get(k):
            return True

    # 4) 끝까지 모르겠으면 False 처리(=판매로 잡지 않음)
    return False


def extract_price(obj: dict):
    # mapleland 쪽에서 자주 쓰는 후보들
    for k in ("itemPrice", "price", "tradePrice"):
        v = obj.get(k)
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return None


def fetch_json() -> list[dict]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (maple-bot)",
        "Referer": "https://mapleland.gg/",
    }
    r = requests.get(API_URL, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()

    # 응답이 리스트가 아닐 수도 있어서 방어
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # 흔한 래핑 형태들
        for k in ("data", "items", "result", "trades"):
            v = data.get(k)
            if isinstance(v, list):
                return v
    return []


def main_once():
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    try:
        data = fetch_json()
        if not data:
            print(f"[{now}] 데이터 없음")
            return

        sells = []
        for obj in data:
            if not isinstance(obj, dict):
                continue
            if not is_sell_trade(obj):
                continue
            price = extract_price(obj)
            if price is None:
                continue
            sells.append(price)

        if not sells:
            # 판매만 필터했더니 0개면, 서버 필드가 다를 수 있어서 디버그 힌트 출력
            sample = next((x for x in data if isinstance(x, dict)), {})
            keys = list(sample.keys())[:30]
            print(f"[{now}] 판매 데이터 0개(구분필드 불일치 가능). 샘플키: {keys}")
            return

        min_price = min(sells)
        print(f"[{now}] 판매 최저가: {min_price}")

    except Exception as e:
        print(f"[{now}] 오류: {e}")


if __name__ == "__main__":
    print("수집 시작")
    while True:
        main_once()
        time.sleep(INTERVAL_SEC)
