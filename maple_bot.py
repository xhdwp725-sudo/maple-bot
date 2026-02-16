import requests
import time

URL = "너가 쓰는 API URL 그대로"

def is_sell(item: dict) -> bool:
    # 응답에 들어올 수 있는 '구분' 키들을 여러 개 후보로 체크
    candidates = [
        item.get("tradeType"),
        item.get("type"),
        item.get("side"),
        item.get("tradeTypeName"),
        item.get("orderType"),
    ]
    text = " ".join([str(x) for x in candidates if x is not None]).lower()

    # 판매(팝니다)로 판정되는 문자열들
    if any(x in text for x in ["sell", "sale", "ask", "판매", "팝니다"]):
        return True
    # 구매(삽니다)로 판정되는 문자열들
    if any(x in text for x in ["buy", "bid", "구매", "삽니다"]):
        return False

    # 마지막 안전장치: buy/sell 구분 키가 없으면 일단 제외(=삽니다 섞이는 걸 막기 위해)
    return False

def main():
    try:
        res = requests.get(URL, timeout=10)
        res.raise_for_status()
        data = res.json()

        if not data:
            print("데이터 없음")
            return

        sell_items = [x for x in data if isinstance(x, dict) and is_sell(x)]

        if not sell_items:
            print("팝니다(SELL) 데이터 없음")
            return

        # SELL 중 itemPrice 최저가
        sell_items.sort(key=lambda x: x.get("itemPrice", 10**18))
        price = sell_items[0].get("itemPrice")

        print("현재 팝니다 최저가:", price)

    except Exception as e:
        print("오류:", e)

if __name__ == "__main__":
    print("수집 시작")
    while True:
        main()
        time.sleep(300)  # 5분마다 실행
