# -*- coding: utf-8 -*-
"""폐쇄형 질의(closed-book) — B0 기준선이자 사전학습 누출 측정기.

두 가지를 한 번에 한다.

① **제거 실험 B0**
   제안서 §4.3의 B0는 "일반 언어모델 단독, 검색 없음"이다. 지금까지 B0는
   근거가 하나도 없어 전부 보류 50%가 나왔는데, 그건 기준선이 아니라 무응답이다.
   모델에게 문헌 없이 직접 물어야 진짜 B0다.

② **누출 측정**
   층 분리를 문헌량으로 하려던 건 틀렸다. `gabapentin/Pain`은 문헌이 많지만
   그 특정 futility 시험은 무명이고, `HCQ/COVID`는 실패 자체가 세계적 뉴스였다.
   문헌량은 "그 실패가 유명한가"의 대리 지표가 못 된다.

   가정하지 말고 측정한다. 문헌을 주지 않고 물어서 맞히면 그건 외운 것이다.
   그 항목에서 전체 시스템이 맞혀도 근거를 읽어서 맞혔다고 말할 수 없다.

   그리고 이 측정이 곧 시스템의 존재 이유를 시험한다.
   전체 시스템이 폐쇄형보다 낫지 않다면, 우리가 만든 파이프라인은 값을 못 한 것이다.
"""

import json
from typing import Any, Dict, List

from ..io import llm

SYSTEM = ("당신은 약물 재창출 전문가다. 모르는 것은 모른다고 답한다. "
          "추측으로 채우지 마라.")

HEAD = """아래 약물-질환 쌍 {n}개 각각에 대해, **당신이 이미 알고 있는 지식만으로** 답하라.

중요
1. 문헌을 검색할 수 없다. 기억에만 의존하라.
2. 그 약이 그 질환에 대해 **임상시험에서 효능을 입증했는지** 답하라.
3. 특정 시험 결과를 실제로 기억하지 못하면 반드시 "모름"이라고 답하라.
   약물 계열이나 그럴듯함으로 추측하지 마라. 추측은 "모름"보다 나쁘다.
4. basis에는 근거가 된 시험명·연도를 적어라. 기억나지 않으면 빈 문자열로 둔다.

"""

TAIL = """
JSON 배열만 출력하라. 원소 {n}개, 위 순서 그대로.
[{{"idx": 1, "verdict": "성공|실패|모름",
   "confidence": "high|medium|low",
   "basis": "기억하는 시험명·연도 (없으면 빈 문자열)"}}]"""


def probe(pairs: List[Dict[str, str]], chunk: int = 12) -> List[Dict[str, Any]]:
    """약-질환 쌍 목록 → 폐쇄형 판정.

    pairs: [{"drug": ..., "indication": ...}, ...]
    반환 순서는 입력 순서와 같다. 실패 시 "모름"으로 채운다(허위 생성 금지).
    """
    out: List[Dict[str, Any]] = [None] * len(pairs)   # type: ignore
    for s in range(0, len(pairs), chunk):
        part = pairs[s:s + chunk]
        body = "\n".join("%d. %s / %s" % (i + 1, p["drug"], p["indication"])
                         for i, p in enumerate(part))
        prompt = HEAD.format(n=len(part)) + body + "\n" + TAIL.format(n=len(part))
        r = llm.complete(prompt, system=SYSTEM, as_json=True,
                         purpose="closedbook")   # 계량 — B0 기준선
        data = r.get("data")
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), None)

        by_idx = {}
        if isinstance(data, list):
            for j, d in enumerate(data):
                if not isinstance(d, dict):
                    continue
                try:
                    k = int(d.get("idx", j + 1)) - 1
                except Exception:
                    k = j
                if 0 <= k < len(part):
                    by_idx[k] = d

        for i, p in enumerate(part):
            d = by_idx.get(i)
            if d is None:
                out[s + i] = {"verdict": "모름", "confidence": "low", "basis": "",
                              "ok": False, "error": r.get("error") or "응답 누락",
                              "provenance": r.get("provenance")}
                continue
            v = str(d.get("verdict", "모름")).strip()
            if v not in ("성공", "실패", "모름"):
                v = "모름"
            out[s + i] = {"verdict": v,
                          "confidence": str(d.get("confidence", "low")).lower(),
                          "basis": str(d.get("basis", ""))[:120],
                          "ok": True, "error": None,
                          "provenance": r.get("provenance")}
    return out


def leakage_flag(rec: Dict[str, Any], label: str) -> bool:
    """이 항목은 누출 의심인가.

    라벨과 일치하는 답을 높은 확신으로 냈으면, 문헌 없이 맞힌 것이다.
    그 항목에서 전체 시스템이 맞혀도 '근거를 읽어서'라고 말할 수 없다.
    """
    want = "실패" if label == "TN" else "성공"
    return rec.get("verdict") == want and rec.get("confidence") == "high"


def to_score(rec: Dict[str, Any]) -> float:
    """폐쇄형 판정을 0~1 점수로. AUROC 비교용(성공=높음)."""
    v, c = rec.get("verdict"), rec.get("confidence")
    w = {"high": 0.45, "medium": 0.30, "low": 0.15}.get(c, 0.15)
    if v == "성공":
        return 0.5 + w
    if v == "실패":
        return 0.5 - w
    return 0.5
