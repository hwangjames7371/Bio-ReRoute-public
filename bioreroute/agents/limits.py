# -*- coding: utf-8 -*-
"""저자가 스스로 적은 한계를 읽고 **지지 근거를 감쇠한다** (F · `사전명세_전문읽기.md`)

  > 초록은 **팔기 위해 쓴 글**이고 Limitations 는 **심사를 통과하려고
  > 쓴 글**이다.

## ⛔ 왜 «새 반박 근거» 가 아니라 «감쇠» 인가 — 09-15 구현 판단

명세(봉인 `acc3525cd1da…`)는 **주지표·반증조건·예산**을 정했지만
*"한계를 판정에 **어떻게** 반영하나"* 는 안 적었다. 봉인 뒤라 명세를
또 고치지 않고 **여기에 판단과 근거를 적는다.**

**새 `refute` 근거로 추가하면 안 된다** — 그 논문은 **초록으로 이미
근거 목록에 있다.** 한계를 별도 레코드로 넣으면 **같은 논문이 두 번**
세어져 근거 수가 부풀고, 그건 «값싸게 걸러낸다» 는 우리 주장과 반대다.

**그래서 가중치를 내린다.** 이 시스템이 이미 쓰는 패턴이다 —
`factcheck` 는 *"인용이 초록에 없으면 0으로 강등"* · *"다른 약을
가리키면 감쇠"* 를 한다. 한계 읽기는 **그 층의 하나**다.

    지지로 보이던 근거 + 저자가 적은 한계  →  **가중치 감쇠**

그리고 이것이 주지표(**기각 정밀도**)에 직접 작용한다 — 약한 지지가
내려가면 기각 쪽이 정확해진다.

## ⛔ 계수를 **미리 못 박고 안 바꾼다**

    약화  0.6      무관  1.0      강화  **1.0**

`0.6` 은 `factcheck.REVIEW_MULT` 의 `preprint 0.7` 과 `internal 0.5`
사이다 — *"동료심사는 받았으나 저자 스스로 한계를 적었다"* 가 그
사이라고 본다.

⚠ **「강화」에도 1.0 을 준다. 올리지 않는다.** 올리면 우리에게 유리한
방향인데, 그 방향으로 손대는 순간 «사후 조정» 이 된다. **내려가는
쪽만 쓴다.**
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..io import llm

# 위 주석 참조. **결과를 보고 바꾸지 않는다.**
LIMIT_MULT = {"약화": 0.6, "무관": 1.0, "강화": 1.0}
ROLE = "limits"

PROMPT = """약: {drug}
질환: {disease}

아래는 위 약-질환 쌍에 관한 논문들에서 **저자가 스스로 적은 한계**다.
각 항목이 **"이 약이 이 질환에 효과가 있다"는 주장을 약화시키는지**만
판정하라.

⚠ 판정 기준
- 약화: 그 한계가 **효능 주장의 신뢰도를 떨어뜨린다**
        (표본이 작다 · 대조군이 없다 · 이차 결과다 · 단일 기관 ·
         추적이 짧다 · 교란을 못 없앴다 …)
- 무관: 한계이긴 하나 **효능 주장과 상관없다**
        (비용 · 일반화 가능성만 언급 · 향후 연구 제안 · 편집상 한계 …)
- 강화: 한계를 적었는데도 **효능 주장이 더 단단해 보인다** (드물다)

⚠ **추측하지 마라.** 주어진 글에 없는 것을 지어내지 마라.
⚠ 한계 서술이 아니면 `무관`이다.

{items}

JSON으로만 답하라. 설명 금지.
{{"items": [{{"idx": 1, "effect": "약화|무관|강화", "why": "한 줄 근거"}}]}}"""


def _fmt(items: List[Dict[str, Any]]) -> str:
    out = []
    for i, it in enumerate(items, 1):
        out.append("[%d] PMID %s (%s)\n%s"
                   % (i, it.get("pmid", "?"), it.get("종류", "?"),
                      (it.get("본문") or "")[:4000]))
    return "\n\n".join(out)


def judge(drug: str, disease: str,
          items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """한계 여러 건을 **한 번에** 판정한다. LLM **1회**.

    ⚠ 건마다 부르면 후보당 3회가 된다. 묶으면 1회다 — 이 시스템이
      이미 쓰는 패턴이고(`B0` 12건 묶음 · 라우터 12건 묶음), 배점 15
      («크레딧 대비 결과»)가 그걸 요구한다.

    ⚠ **판정 못 하면 «무관» 이 아니라 «판정없음» 이다.** 무관으로 밀면
      «LLM 실패» 가 «한계가 효능과 상관없다» 는 **발견**으로 둔갑한다
      (결함 35 계열).
    """
    if not items:
        return {"ok": True, "판정": [], "왜": "대상 없음"}
    # ⚠ 09-15 · 처음에 `role=ROLE` 로 썼는데 **`complete()` 에 그런 인자가
    #   없다.** 다른 에이전트는 전부 `model=llm.model_for("역할")` 이다
    #   (`router`·`factcheck`·`reverse`…). 그대로 뒀으면 **TypeError 로
    #   크래시**했다 — 죽은 인자가 아니라 즉시 터지는 종류다.
    # ⚠ 09-15 · **리터럴로 쓴다.** 시험 [133] 이 AST 로 `model_for("…")` 의
    #   **문자열 인자**를 훑어 «선언한 역할이 실제로 배선됐나» 를 검사한다.
    #   `model_for(ROLE)` 처럼 변수를 넘기면 **죽은 역할로 판정**된다 —
    #   08-18에 `skeptic`·`approval`·`discover` 셋이 그렇게 죽어 있었고
    #   `roles_in_use()` 는 여섯을 다 찍어 **감사 추적이 거짓말을 했다**.
    r = llm.complete(PROMPT.format(drug=drug, disease=disease,
                                   items=_fmt(items)),
                     as_json=True,
                     model=llm.model_for("limits"),   # §3.2 — 적대적 추론
                     purpose="fulltext")   # 계량 — F(전문 읽기)
    if not r.get("ok") or not isinstance(r.get("data"), dict):
        return {"ok": False, "판정": [], "error": r.get("error") or "JSON 실패",
                "provenance": r.get("provenance")}
    out: List[Dict[str, Any]] = []
    for d in (r["data"].get("items") or []):
        try:
            i = int(d.get("idx", 0)) - 1
        except Exception:
            continue
        if not (0 <= i < len(items)):
            continue
        eff = str(d.get("effect", "")).strip()
        if eff not in LIMIT_MULT:
            continue                       # 모르는 값은 **버린다**(무관 아님)
        out.append({"pmid": items[i].get("pmid"), "종류": items[i].get("종류"),
                    "effect": eff, "mult": LIMIT_MULT[eff],
                    "why": str(d.get("why", ""))[:160]})
    return {"ok": True, "판정": out, "provenance": r.get("provenance"),
            "물어본수": len(items), "받은수": len(out)}
