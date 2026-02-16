import requests
import time

URL = "https://mapleland.gg/item/1082002?lowPrice=&highPrice=9999999999&lowincPAD=10&highincPAD=10&lowincMAD=&highincMAD=&lowincPDD=&highincPDD=&lowUpgrade=&highUpgrade=5&lowTuc=&highTuc=5&hapStatsName=&lowHapStatsValue=0&highHapStatsValue=0"

def fetch():
    res = requests.get(URL, timeout=15)

    print("status:", res.status_code)
    print("content-type:", res.headers.get("content-type"))
    print("body-head:", res.text[:300])

    res.raise_for_status()  # 200 아니면 여기서 터져서 원인 보임

    # JSON 파싱
    try:
        return res.json()
    except Exception as e:
        print("오류: Failed to parse JSON:", e)
        return None

def main():
    data = fetch()
    if not data:
        return

    # 여기부터 기존 로직
    first = data[0] if isinstance(data, list) and data else None
    if not first:
        print("가격 없음")
        return

    price = first.get("itemPrice")
    if price is not None:
        print("현재 최저가:", price)
    else:
        print("가격 필드 없음:", first)

if __name__ == "__main__":
    print("수집 시작")
    while True:
        main()
        time.sleep(300)

