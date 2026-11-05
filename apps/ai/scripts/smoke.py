"""실제 제공자(Bedrock·Gemini)로 ai 엔드포인트를 한 번씩 불러 동작·지연을 확인한다.

EC2(IAM Role)에서: `uv run --package bjk-ai python apps/ai/scripts/smoke.py`
쓰인 모델, 시도 횟수, 지연, 대체 응답 여부만 출력한다. 키·자격 증명은 출력하지 않는다.
"""

import itertools
import time

from bjk_ai.config import get_settings
from bjk_ai.main import create_app
from fastapi.testclient import TestClient

COMPANY_ID = "6f1c2f9e-6d1a-4c3e-9a51-2b7f0c8d4e11"
CHATS = [
    "3호기 베어링 두 개 씀",
    "볼트 200개, 너트 200개 씀",
    "V벨트 30개 시켜주세요, 저번 데서요",
    "베어링 6205ZZ 10개 들어왔어요, 개당 1만 8천원",
    "세어보니 940개",
    "V벨트 몇 개 있어?",
    "3호기 정비 끝",
    "오늘 점심 뭐임",
]
OPINION = {
    "company_id": COMPANY_ID,
    "part_name": "V벨트 A-42",
    "verdict": "revise",
    "checks": [
        {"code": "C-01", "level": "warning", "facts": {"S": 2, "O": 10, "Q": 30, "D99": 5}},
        {"code": "C-03", "level": "warning", "facts": {"incoming_qty": 10, "eta": "2026-11-08"}},
    ],
    "original": {"qty": 30, "supplier_name": "공급사 A", "unit_price": 18000, "total": 540000},
    "proposal": {"qty": 0, "total": 0, "saving": 540000, "no_order": True, "basis": ["C-01"]},
    "computed_at": "2026-11-04T03:00:00+09:00",
}


def usage_line(body: dict) -> str:
    usage = body.get("usage") or {}
    return (
        f"fallback={body['ai']['fallback']} reason={body['ai']['reason']} "
        f"model={usage.get('model')} attempts={usage.get('attempts')} "
        f"latency={usage.get('latency_ms')}ms"
    )


def main() -> None:
    settings = get_settings()
    print(
        f"llm_provider={settings.llm_provider} embedding_provider={settings.embedding_provider} "
        f"region={settings.aws_region}"
    )
    with TestClient(create_app()) as client:
        print("health:", client.get("/health").json())

        for text in CHATS:
            body = client.post(
                "/v1/chat/parse", json={"company_id": COMPANY_ID, "text": text}
            ).json()
            item = (body.get("items") or [{}])[0]
            print(f"chat {text!r} → {body['intent']} {item.get('part_text')} {item.get('qty')}")
            print("   ", usage_line(body))

        names = ["육각볼트 M8-20", "헥사볼트 M8×20", "볼베어링 6205ZZ"]
        body = client.post(
            "/v1/embeddings", json={"company_id": COMPANY_ID, "task": "document", "texts": names}
        ).json()
        print("embed", body.get("model"), usage_line(body))
        vectors = body.get("vectors") or []
        if vectors:
            print("   dims:", [len(v) for v in vectors])
            for (i, a), (j, b) in itertools.combinations(enumerate(vectors), 2):
                cos = sum(x * y for x, y in zip(a, b, strict=True))
                print(f"   cos({names[i]}, {names[j]}) = {cos:.3f}")

        started = time.monotonic()
        body = client.post("/v1/opinions", json=OPINION).json()
        print(f"opinion {time.monotonic() - started:.1f}s", usage_line(body))
        print("   " + (body.get("text") or "").replace("\n", "\n   "))

        rows = [{"row": i + 2, "name": n} for i, n in enumerate(["육각볼트 M8-20", "작업용 장갑"])]
        categories = [
            {"id": "cat-bolt", "name": "볼트·너트"},
            {"id": "cat-bearing", "name": "베어링"},
        ]
        body = client.post(
            "/v1/imports/suggest",
            json={"company_id": COMPANY_ID, "categories": categories, "rows": rows},
        ).json()
        print("import", usage_line(body))
        for suggestion in body.get("suggestions") or []:
            print("   ", suggestion)


if __name__ == "__main__":
    main()
