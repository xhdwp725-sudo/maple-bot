import os
import time
import requests
from urllib.parse import urlparse, parse_qs, urlencode
from datetime import datetime, timezone, timedelta

# 네가 준 페이지 URL (필터 포함)
PAGE_URL = "https://mapleland.gg/item/1082002?lowPrice=&highPrice=9999999999&lowincPAD=10&highincPAD=10&lowincMAD=&highincMAD=&lowincPDD=&highincPDD=&lowUpgrade=&highUpgrade=5&lowTuc=&highTuc=5&hapStatsName=&lowHapStatsValue=0&highHapStatsValue=0"

# 5분마다 수집
INTERVAL_SEC = 300

KST = timezone(timedelta(hours=9))


def to_api_url(page_url: str) -> str:
    """
    mapleland.gg/item/... 페이지 URL을
    api.mapleland.gg/trade 호출 URL로 변환 (쿼리 파라미터 유지)
    """
    u = urlparse(page_url)
    qs = parse_qs(u.query)

    # itemCode 추출: /item/1082002 형태
    parts = [p for p in u.path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "item":
        item_code = parts[1]
    else:
        # 혹시 itemCode가 쿼리에 들어있는 형태면 그걸 사용
        item_code = (qs.get("itemCode") or [None])[0]

    if not item_code:
        raise ValueError("itemCode를 찾지 못했어. PAGE_URL 경로(/item/1082002) 확인해줘.")

    # API는 itemCode가 필수
    qs["itemCode"] = [item_code]

    # parse_qs는 값이 list라서 urlencode(doseq=True)로 처리
    api_query = urlencode(qs, doseq=True)
    return f"https://api.mapleland.gg/trade?{api_query}"


def pick_price_field(obj: dict):
    """
    가격 필드 이름이 환경/버전에 따라 다를 수 있어서 후보를 여러 개로 둠.
    """
    for key in ("itemPrice", "price", "tradePrice", "sellPrice", "amount"):
        if key in obj and obj[key] is not None:
            return obj[key]
    return None


def is_sell_listing(obj: dict) -> bool:
    """
    '팝니다(판매)'만 남기려고 최대한 방어적으로 판별.
    API 응답 구조가 바뀌어도 어느 정도 버팀.
    """
    # 흔한 케이스들
    if "isBuy" in obj:
        return obj["isBuy"] is False
    if "isSell" in obj:
        return obj["isSell"] is True
    if "tradeType" in obj:
        v = str(obj["tradeType"]).lower()
        return v in ("sell", "seller", "sale")
    if "type" in obj:
        v = str(obj["type"]).lower()
        return v in ("sell", "seller", "sale")

    # fallback: buy 관련 키가 있으면 구매로 간주
    buyish_keys = ("buyer", "buy", "buyPrice")
    for k in buyish_keys:
        if k in obj:
            return False

    # 그래도 모르면 "판매로 추정"하지 말고 True로 두면 섞일 수 있어서,
    # 안전하게 False로 둠 (섞임 방지 우선)
    return False


def fetch_json(api_url: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; maple-bot/1.0)",
        "Accept": "application/json",
        "Referer": "https://mapleland.gg/",
    }
    r = requests.get(api_url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def format_num(n: int) -> str:
    return f"{n:,}"


def main():
    # 필요하면 Railway Variables에서 PAGE_URL을 덮어쓸 수 있게 해둠
    page_url = os.getenv("PAGE_URL", PAGE_URL).strip()
    api_url = to_api_url(page_url)

    print("수집 시작")
    print("API_URL =", api_url)

    while True:
        ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

        try:
            data = fetch_json(api_url)

            # 응답이 리스트가 아닐 수도 있어서 정규화
            if isinstance(data, dict):
                # 흔한 형태들 시도
                for k in ("data", "items", "result", "list"):
                    if k in data and isinstance(data[k], list):
                        data = data[k]
                        break

            if not isinstance(data, list) or not data:
                print(f"[{ts}] 데이터 없음(빈 응답)")
                time.sleep(INTERVAL_SEC)
                continue

            # 판매만 추출
            sells = [x for x in data if isinstance(x, dict) and is_sell_listing(x)]

            # 만약 sell 판별이 전부 실패하면(구조가 다른 경우),
            # 그때만 전체에서 가격 후보를 뽑되, 섞일 가능성 경고를 출력
            target = sells if sells else data

            prices = []
            for obj in target:
                if not isinstance(obj, dict):
                    continue
                p = pick_price_field(obj)
                if p is None:
                    continue
                try:
                    prices.append(int(p))
                except Exception:
                    continue

            if not prices:
                label = "판매" if sells else "전체(판매판별 실패)"
                print(f"[{ts}] {label} 가격 필드 못 찾음")
            else:
                best = min(prices)
                label = "판매" if sells else "전체(판매판별 실패)"
                print(f"[{ts}] {label} 최저가: {format_num(best)}")

        except Exception as e:
            print(f"[{ts}] 오류:", repr(e))

        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
