import json
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

import requests

KST = timezone(timedelta(hours=9))

# ===== 너가 준 값들(완전 삽입됨) =====
TOKEN = "mapleland_2026_02_17_abc123xyz999"
SHEETS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbw730jSMIIjf8a6xPe1D8Riv8rnP-9T1vCFMqrkTB_PEUPxkWb1W72nLmnWSGUtv27O/exec"

# 공10 노가다 목장갑(+5) item_code
ITEM_CODE = "1082002"
ITEM_NAME = "노가다 목장갑(+5) 공10"


def now_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def env(name: str, default: Optional[str] = None) -> str:
    """
    Railway에서 env 없어서 크래시 난다고 했지?
    앞으로는 default 주면 크래시 안 나게 처리.
    """
    v = os.getenv(name, default)
    if v is None or v == "":
        raise RuntimeError(f"Missing env var: {name}")
    return v


def post_to_sheets(side: str, price: int, seller: str = "", note: str = "") -> Dict[str, Any]:
    payload = {
        "token": TOKEN,
        "timestamp": now_kst_str(),
        "side": side,  # "sell" or "buy"
        "item_code": ITEM_CODE,
        "item_name": ITEM_NAME,
        "price": int(price),
        "seller": seller,
        "note": note,
    }

    r = requests.post(
        SHEETS_WEBAPP_URL,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    r.raise_for_status()
    out = r.json()
    if not out.get("ok"):
        raise RuntimeError(f"Sheets WebApp returned error: {out}")
    return out


def main() -> None:
    """
    목적: '공10 노목' 데이터를 시트로 보내는 파이프라인을 먼저 "확실히" 성공시킴.

    현재 Railway에서 mapleland.gg 직접 크롤링은 403으로 막히는 케이스가 많아서,
    이 파일은 일단 '시트 전송'을 100% 고정으로 만들고, 이후 데이터 수집부를 붙이는 방식이 안전함.

    지금은 테스트로: 팝니다 최저가를 임시 값으로 47,000,000 전송.
    (너가 원하면 다음 단계에서 수집부를 붙이되, 403 안 나는 방식으로만 설계해야 함.)
    """
    test_sell_price = 47000000
    out = post_to_sheets("sell", test_sell_price, note="pipeline-test")
    print("OK:", out)


if __name__ == "__main__":
    main()
