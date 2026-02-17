import requests
import time
from datetime import datetime

# ==============================
# 설정값 (완성본)
# ==============================

SHEET_URL = "https://script.google.com/macros/s/AKfycbw730jSMIIjf8a6xPe1D8Riv8rnP-9T1vCFMqrkTB_PEUPxkWb1W72nLmnWSGUtv27O/exec"

API_URL = "https://api.mapleland.gg/trade"
PARAMS = {
    "itemCode": "1082002",
    "lowPrice": "",
    "highPrice": "9999999999",
    "lowincPAD": "10",
    "highincPAD": "10",
    "lowincPDD": "",
    "highincPDD": "",
    "lowUpgrade": "",
    "highUpgrade": "5",
    "lowTuc": "",
    "highTuc": "5",
    "hapStatsName": "",
    "lowHapStatsValue": "0",
    "highHapStatsValue": "0",
}

INTERVAL = 300  # 5분


def get_min_price():
    try:
        res = requests.get(API_URL, params=PARAMS, timeout=15)
        res.raise_for_status()
        data = res.json()

        if not data:
            return None

        prices = [item["itemPrice"] for item in data if "itemPrice" in item]
        if not prices:
            return None

        return min(prices)

    except Exception as e:
        print("가격 조회 실패:", e)
        return None


def send_to_sheet(price):
    try:
        payload = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "item_name": "노가다 목장갑 공10",
            "item_code": "1082002",
            "min_price": price,
            "count": 1,
            "source": "railway-bot"
        }

        res = requests.post(SHEET_URL, json=payload, timeout=15)
        print("시트 전송 결과:", res.text)

    except Exception as e:
        print("시트 전송 실패:", e)


def main():
    print("START: maple bot running")

    while True:
        price = get_min_price()

        if price:
            print("최저가:", price)
            send_to_sheet(price)
        else:
            print("가격 없음")

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
