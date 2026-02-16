import requests
import time

URL = "https://api.mapleland.gg/trade?itemCode=1082002&lowPrice=&highPrice=9999999999&lowincPAD=10&highincPAD=10&lowincPDD=&highincPDD=&lowUpgrade=&highUpgrade=5&lowTuc=&highTuc=5&hapStatsName=&lowHapStatsValue=0&highHapStatsValue=0"

def main():
    try:
        res = requests.get(URL, timeout=10)
        data = res.json()

        if not data:
            print("가격 없음")
            return

        # 첫 번째 아이템 가격
        first = data[0]
        price = first.get("itemPrice")

        if price:
            print("현재 최저가:", price)
        else:
            print("가격 필드 없음:", first)

    except Exception as e:
        print("오류:", e)


if __name__ == "__main__":
    print("수집 시작")
    while True:
        main()
        time.sleep(300)  # 5분마다 실행


