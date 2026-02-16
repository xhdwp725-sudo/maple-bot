import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))


def now_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def env(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    if v is None or v == "":
        raise RuntimeError(f"Missing env var: {name}")
    return v


def env_opt(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name, default)
    return v if v not in (None, "") else default


@dataclass
class Item:
    item_code: str
    item_name: str
    url: str


def build_mapleland_item_url(item_code: str) -> str:
    # 네가 쓰던 쿼리 기반으로 고정 (공10 노목 필터)
    return (
        f"https://mapleland.gg/item/{item_code}"
        f"?lowPrice=&highPrice=9999999999"
        f"&lowincPAD=10&highincPAD=10"
        f"&lowincPDD=&highincPDD="
        f"&lowUpgrade=&highUpgrade=5"
        f"&lowTuc=&highTuc=5"
        f"&hapStatsName=&lowHapStatsValue=0&highHapStatsValue=0"
    )


def load_items() -> List[Item]:
    raw = env_opt("ITEMS_JSON")
    if raw:
        data = json.loads(raw)
        items: List[Item] = []
        for it in data:
            items.append(
                Item(
                    item_code=str(it["item_code"]),
                    item_name=str(it["item_name"]),
                    url=str(it["url"]),
                )
            )
        return items

    # 기본값: 공10 노목(1082002)만
    code = "1082002"
    return [Item(item_code=code, item_name="노가다 목장갑(+5) 공10", url=build_mapleland_item_url(code))]


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    return s


def fetch_html(url: str, timeout: int = 20) -> str:
    """
    1) requests로 시도
    2) 403이면 cloudscraper(있을 때)로 재시도
    """
    s = make_session()
    r = s.get(url, timeout=timeout)
    if r.status_code == 200:
        return r.text

    if r.status_code == 403:
        # Cloudflare/봇 차단일 가능성이 커서 우회 시도
        try:
            import cloudscraper  # type: ignore

            cs = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
            r2 = cs.get(url, timeout=timeout, headers=s.headers)
            r2.raise_for_status()
            return r2.text
        except Exception as e:
            raise RuntimeError(f"403 Forbidden (and cloudscraper failed): {e}")

    r.raise_for_status()
    return r.text


def parse_prices(html: str) -> Tuple[Optional[int], Optional[int], int, int]:
    """
    반환:
      (sell_min_price, buy_min_price, sell_count, buy_count)
    """
    soup = BeautifulSoup(html, "lxml")

    text = soup.get_text(" ", strip=True)

    # 카운트 추정: "팝니다" 섹션과 "삽니다" 섹션을 정확히 DOM으로 못 잡으면 fallback
    # 가격 추출은 숫자(콤마 포함) 패턴에서 "팝니다" / "삽니다" 주변을 우선으로 잡고,
    # 그래도 안되면 전체에서 최소값을 잡는 방식(최후 fallback)으로 감.
    def to_int(s: str) -> int:
        return int(s.replace(",", "").strip())

    price_pat = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*")

    # 1) DOM 기반: "팝니다"/"삽니다" 컬럼이 따로 있는 경우를 대비해서
    #    섹션 제목 노드 근처에서 가격을 모음.
    def collect_near(keyword: str) -> List[int]:
        # keyword 텍스트를 포함하는 요소 후보들
        nodes = soup.find_all(string=lambda x: x and keyword in x)
        prices: List[int] = []
        for n in nodes[:10]:
            parent = n.parent
            if not parent:
                continue
            # 주변(상위) 컨테이너에서 텍스트 뽑아서 가격 추출
            container = parent
            for _ in range(3):
                if container.parent:
                    container = container.parent
            chunk = container.get_text(" ", strip=True)
            for m in price_pat.finditer(chunk):
                v = m.group(1)
                # 너무 작은 수(시간/카운트) 오염 방지: 1000 이상만
                try:
                    iv = to_int(v)
                    if iv >= 1000:
                        prices.append(iv)
                except Exception:
                    pass
        return prices

    sell_prices = collect_near("팝니다")
    buy_prices = collect_near("삽니다")

    # 2) fallback: 페이지 전체에서 가격처럼 보이는 큰 숫자들을 뽑고 최소값 사용
    if not sell_prices or not buy_prices:
        all_prices: List[int] = []
        for m in price_pat.finditer(text):
            v = m.group(1)
            try:
                iv = to_int(v)
                if iv >= 1000:
                    all_prices.append(iv)
            except Exception:
                pass
        all_prices = sorted(set(all_prices))
        # fallback에서는 "sell/buy" 구분이 불가능하니 sell만이라도 잡자
        if not sell_prices and all_prices:
            sell_prices = all_prices[:20]

    sell_min = min(sell_prices) if sell_prices else None
    buy_min = min(buy_prices) if buy_prices else None

    # count는 정확히 잡기 어려워서, 근처에서 찾은 가격 개수를 대충 카운트로 둠
    sell_count = len(sell_prices)
    buy_count = len(buy_prices)

    return sell_min, buy_min, sell_count, buy_count


def post_to_sheets(
    webapp_url: str,
    token: str,
    item: Item,
    side: str,
    min_price: int,
    count: int,
    source: str = "railway",
) -> None:
    payload = {
        "token": token,
        "timestamp": now_kst_str(),
        "side": side,  # "sell" or "buy"
        "item_name": item.item_name,
        "item_code": item.item_code,
        "min_price": min_price,
        "count": count,
        "source": source,
    }
    r = requests.post(webapp_url, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Sheets WebApp returned error: {data}")


def main() -> None:
    webapp_url = env("SHEETS_WEBAPP_URL")
    token = env("SECRET_TOKEN")
    interval = int(env_opt("INTERVAL_SECONDS", "300") or "300")

    items = load_items()

    print(f"{now_kst_str()} | START | items={len(items)} interval={interval}s")
    while True:
        for item in items:
            try:
                html = fetch_html(item.url)
                sell_min, buy_min, sell_count, buy_count = parse_prices(html)

                # 여기서는 네 요청대로 "공10 노목 데이터 -> 시트"가 목적이라 SELL 우선 기록
                if sell_min is not None:
                    post_to_sheets(
                        webapp_url=webapp_url,
                        token=token,
                        item=item,
                        side="sell",
                        min_price=sell_min,
                        count=sell_count,
                        source="railway",
                    )
                    print(f"{now_kst_str()} | OK | sell_min={sell_min} count={sell_count}")

                # buy는 필요하면 켜라 (원하면 buy도 기록하도록 바꿔줄게)
                # if buy_min is not None:
                #     post_to_sheets(
                #         webapp_url=webapp_url,
                #         token=token,
                #         item=item,
                #         side="buy",
                #         min_price=buy_min,
                #         count=buy_count,
                #         source="railway",
                #     )
                #     print(f"{now_kst_str()} | OK | buy_min={buy_min} count={buy_count}")

                if sell_min is None:
                    print(f"{now_kst_str()} | WARN | could_not_find_sell_price")

            except Exception as e:
                print(f"{now_kst_str()} | ERROR | {e}")

        time.sleep(interval)


if __name__ == "__main__":
    main()
