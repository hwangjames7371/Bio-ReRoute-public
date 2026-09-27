# -*- coding: utf-8 -*-
"""기전 라우터 — 검증 경로를 분기한다.

제안서 §2.4의 핵심 주장: **언제 도킹하면 안 되는가**를 아는 것이 능력이다.

  · 약물이 병원체 단백질에 **직접 결합**한다   → 구조·도킹 경로가 타당
  · 표적이 **숙주 단백질**이다                → 병원체 도킹은 무의미
  · 결합이 아니라 **간접 효과**(pH·막·대사)다  → 도킹 자체가 범주 오류

실측으로 확인된 반례: 하이드록시클로로퀸은 바이러스 단백질에 결합하지 않는다.
엔도솜 pH를 올리고 ACE2 당화를 바꿀 뿐이다. 여기에 도킹을 돌리는 건
계산 자원 낭비를 넘어 **틀린 근거를 만들어내는** 짓이다.

지금까지 이 게이트는 시드 문자열을 확인만 하는 스텁이었고, 벤치마크에서는
`mech_class=None`이라 아무 일도 하지 않았다. 그래서 B4·B5 단이 사실상
시험되지 않았다. 이 파일이 그 구멍을 메운다.
"""

from typing import Any, Dict, List

from ..io import llm

SYSTEM = ("당신은 약리학자다. 약물의 작용 기전을 분류한다. "
          "확실하지 않으면 불명이라고 답한다.")

# 분류 → 검증 경로
#   구조 경로는 '병원체 단백질에 직접 결합'일 때만 준다.
#   숙주 표적이나 간접 효과는 임상·발현 증거로 검증해야 한다.
ROUTE = {
    "직접·병원체": "structure",
    "직접·숙주": "evidence",
    "간접": "evidence",
    "오프타겟": "evidence",
    "불명": None,
}

HEAD = """아래 약물 {n}개의 작용 기전을 분류하라. 질환 맥락: 각 항목에 표기.

분류 기준
  직접·병원체 : 병원체(바이러스·세균·기생충)의 단백질에 직접 결합한다
  직접·숙주   : 숙주(사람)의 단백질에 직접 결합한다
  간접        : 단백질 결합이 아니라 pH·막 성질·대사 경로 등을 통해 작용한다
  오프타겟    : 본래 표적이 아닌 부수 작용이 치료 효과의 근거다
  불명        : 기전을 특정할 수 없다

중요
1. 확실하지 않으면 반드시 "불명"이라고 답하라. 추측하지 마라.
2. target에는 아는 표적 단백질명을 적는다. 모르면 빈 문자열.
3. 암·대사질환처럼 병원체가 없는 질환이면 직접·병원체는 불가능하다.

"""

TAIL = """
JSON 배열만 출력하라. 원소 {n}개, 위 순서 그대로.
[{{"idx": 1, "mech": "직접·병원체|직접·숙주|간접|오프타겟|불명",
   "target": "표적 단백질 (모르면 빈 문자열)",
   "confidence": "high|medium|low",
   "why": "한 문장 근거"}}]"""


def classify(pairs: List[Dict[str, str]], chunk: int = 12) -> List[Dict[str, Any]]:
    """[{drug, disease}] → 기전 분류. 실패하면 '불명'으로 채운다."""
    out: List[Dict[str, Any]] = [None] * len(pairs)   # type: ignore
    for s in range(0, len(pairs), chunk):
        part = pairs[s:s + chunk]
        body = "\n".join("%d. %s  (질환: %s)" % (i + 1, p["drug"], p.get("disease", ""))
                         for i, p in enumerate(part))
        r = llm.complete(HEAD.format(n=len(part)) + body + "\n" + TAIL.format(n=len(part)),
                         system=SYSTEM, as_json=True,
                         model=llm.model_for("router"),   # §3.2 소형
                         purpose="router")   # 계량 — 경로 분기
        data = r.get("data")
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), None)
        idx = {}
        if isinstance(data, list):
            for j, d in enumerate(data):
                if isinstance(d, dict):
                    try:
                        k = int(d.get("idx", j + 1)) - 1
                    except Exception:
                        k = j
                    if 0 <= k < len(part):
                        idx[k] = d
        for i in range(len(part)):
            d = idx.get(i) or {}
            m = str(d.get("mech", "불명")).strip()
            if m not in ROUTE:
                m = "불명"
            out[s + i] = {"mech": m, "route": ROUTE[m],
                          "target": str(d.get("target", ""))[:60],
                          "confidence": str(d.get("confidence", "low")).lower(),
                          "why": str(d.get("why", ""))[:120],
                          "provenance": r.get("provenance"),
                          "error": None if idx.get(i) else (r.get("error") or "응답 누락")}
    return out


def docking_advised(rec: Dict[str, Any]) -> bool:
    """구조·도킹을 돌릴 가치가 있는가.

    이 판단이 라우터의 존재 이유다. 숙주 표적이나 간접 작용에 도킹을 돌리면
    자원을 쓸 뿐 아니라 **틀린 근거를 생산한다.**
    """
    return rec.get("route") == "structure" and rec.get("confidence") != "low"
