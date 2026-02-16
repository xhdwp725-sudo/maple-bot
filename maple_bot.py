import os
import time
import json
import requests
from datetime import datetime, timezone, timedelta

# =========================
# 1) 너가 "반드시" 넣어야 하는 값
# =========================
# 가장 안전한 방식: Railway Variables에 API_URL로 넣고, 여기서는 그걸 읽는다.
# (로컬에서도 돌리고 싶으면 아래 fallback 문자열에 직접 붙여넣어도 됨)
API_URL = os.getenv("API_URL", "").strip()

# 로컬에서만 빠르게 테스트하고 싶으면 아래에 직접 넣어도 됨.
# Railway에 올릴 때는 Variables에 API_URL 넣는 게 정석.
# API_URL = "https://api.mapleland.gg/trade?...."

# =========================
# 2) 동작 설정 (웬만하면 건드리지 마)
# =========================
INTERVAL_SEC = int(os.getenv("INTERVAL_SEC", "300"))  # 기본 5분
KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": "maple-bot/1.0",
    "Accept": "application/json,text/plain,*/*",
}

def now_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

def fetch_json(url: str):
    res = requests.get(url, headers=HEADERS, timeout=20)
    res.raise_for_status()

    # content-type이 json이 아닐 수도 있어서, 무조건 json()만 때리지 말고 안전하게 처리
    ctype = (res.headers.get("content-type") or "").lower()
    text_head = res.text[:200].replace("\n", " ")

    try:
        return res.json()
    except Exception as e:
        print(f"[{now_kst_str()}] 오류: JSON 파싱 실패")
        print(f"  status={res.status_code}, content-type={ctype}")
        print(f"  body-head={text_head}")
        print(f"  err={e}")
        return None

def extract_prices(data):
    """
    data에서 판매/구매가 섞여 있을 수 있음.
    - 1순위: '판매'만 필터링 시도
    - 실패하면: 그냥 itemPrice 있는 것만 전부 모아서 최저가 출력(임시)
    """
    if not isinstance(data, list):
        return [], []

    sell_prices = []
    all_prices = []

    for x in data:
        if not isinstance(x, dict):
            continue

        price = x.get("itemPrice")
        if isinstance(price, int):
            all_prices.append(price)

        # sell/buy 구분 키 후보들
        side = (
            x.get("tradeType")
            or x.get("type")
            or x.get("side")
            or x.get("orderType")
            or x.get("category")
            or ""
        )

        side_str = str(side).upper()

        # 판매로 보이는 값들
        is_sell = ("SELL" in side_str) or ("판매" in side_str)
        if is_sell and isinstance(price, int):
            sell_prices.append(price)

    return sell_prices, all_prices

def main_once():
    if not API_URL:
        print(f"[{now_kst_str()}] 오류: API_URL이 비어있음")
        print("  해결: Railway -> Service -> Variables에 API_URL을 추가해라.")
        print("  (값은 https://api.mapleland.gg/... 로 시작하는 거래 API 주소)")
        return

    data = fetch_json(API_URL)
    if data is None:
        return

    sell_prices, all_prices = extract_prices(data)

    # 판매 필터가 제대로 먹으면 판매 최저가만 출력
    if sell_prices:
        print(f"[{now_kst_str()}] 판매 최저가: {min(sell_prices)}")
        return

    # 판매 구분 필드가 없거나 우리가 못 잡은 경우(임시 출력)
    if all_prices:
        print(f"[{now_kst_str()}] (주의) 판매/구매 구분 못함. 전체 최저가: {min(all_prices)}")
        # 디버깅: 첫 항목 키 일부 출력해서 어떤 필드가 있는지 확인
        if isinstance(data, list) and data and isinstance(data[0], dict):
            sample_keys = list(data[0].keys())
            print(f"[{now_kst_str()}] 샘플 키: {sample_keys[:30]}")
        return

    print(f"[{now_kst_str()}] 데이터는 왔는데 가격(itemPrice)이 없음")

if __name__ == "__main__":
    print(f"[{now_kst_str()}] 수집 시작")
    while True:
        try:
            main_once()
        except Exception as e:
            print(f"[{now_kst_str()}] 치명 오류: {e}")
        time.sleep(INTERVAL_SEC)
