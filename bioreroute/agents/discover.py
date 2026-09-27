# -*- coding: utf-8 -*-
"""발굴 에이전트 — 질환 하나를 받아 재창출 후보를 **생성**한다.

공모분야 이름은 「자율형 가설 **생성** 및 검증」인데 이 저장소는 지금까지
검증만 있었다. `state.SEED_CANDIDATES` 5개가 사람이 손으로 쓴 값이고
`c.note("discovery", "STUB", ...)` 가 그 사실을 기록해 왔다. 이 파일이
그 STUB을 없앤다.

## 왜 프롬프트가 둘인가 — 이게 이 모듈의 핵심 설계다

생성기에게 "확신 없어도 좋다"고 말하면 쓰레기가 쏟아지고, 그걸 깔때기가
걸러낸 뒤 *"거르는 게 병목이다"* 라고 쓰면 **내가 만든 결론을 내가 다시
읽은 것**이다. 반대로 "확실한 것만"이라고 말하면 후보가 안 나오고
*"생성이 병목이다"* 가 된다. **프롬프트 한 줄이 결론을 정한다.**

그래서 한쪽을 고르지 않는다. 둘 다 돌리고 **차이를 보고한다.**
생성기의 신중함이 후보의 질을 얼마나 바꾸는지가 곧 측정값이다.

  strict — "확실히 근거가 있는 것만. 없으면 적게 답하라"
  loose  — "확신이 없어도 좋다. 이 단계는 생성이지 검증이 아니다"

## 생성기는 자기가 채점당하는 걸 모른다

프롬프트에 승인 목록도 실패 목록도 넣지 않는다. 질환 이름만 준다.
채점은 `bench/discover.py` 가 생성 **후에** RepoDB·TN풀과 대조해서 한다.
"""

from typing import Any, Dict, List, Optional

from ..io import llm

# 이 문자열은 **발굴 프롬프트에만** 있어야 한다.
# 시험용 모의 LLM이 이걸로 프롬프트를 판별하고, 판별이 모호하면 실패한다.
#   (결함 5·11의 재발 방지 — 모의가 거짓말한 게 네 번이다.
#    팩트체크 프롬프트에 "기전"이 들어 있어 라우터 응답이 간 적이 있다.)
MARK = "[발굴 요청 · 질환]"

SYSTEM = ("당신은 약물 재창출 후보를 발굴하는 연구자다. "
          "국제일반명(INN)으로만 답하고 상품명은 쓰지 않는다.")

# 두 변형이 **공유**하는 부분. 규칙 1~4는 채점 가능성을 위한 형식 제약이지
# 후보의 질에 대한 지시가 아니다. 질에 대한 지시는 TEMPER 에만 둔다.
BASE = MARK + """ {disease}

이 질환에 **약물 재창출(drug repurposing)** 로 시도해 볼 후보를 최대 {k}개 제시하라.

형식 규칙
1. 다른 적응증으로 **이미 승인된 약물**만 제시한다. 미승인 신규 화합물은 안 된다.
2. **이 질환에 이미 승인된 약물은 제외한다.** 그건 재창출이 아니라 표준치료다.
3. 계열당 최대 1개. 같은 기전의 약을 여러 개 채우지 마라.
4. drug 에는 국제일반명(INN) 영문만 적는다. 상품명·복합제·용량 표기 금지.

{temper}
"""

TAIL = """
JSON 배열만 출력하라. 다른 말은 붙이지 마라.
[{{"drug": "국제일반명(영문)",
  "mechanism": "이 질환에 작용할 것으로 보는 기전 (한 문장)",
  "rationale": "근거 (한 문장). 실제 시험·논문이 기억나면 그 이름을 적는다",
  "evidence_level": "clinical|preclinical|mechanistic|speculative",
  "confidence": "high|medium|low"}}]"""

TEMPER: Dict[str, str] = {
    # 신중 — 근거가 없으면 적게 답하는 쪽이 낫다고 말한다
    "strict": """생성 기준 (중요)
5. **임상 또는 전임상 근거를 실제로 아는 후보만** 제시하라.
6. 근거가 기억나지 않으면 그 후보는 빼라. **{k}개를 억지로 채우지 마라.**
   3개만 확실하면 3개만 답하는 것이 옳다.
7. 그럴듯함(plausibility)만으로 제시하지 마라. 그건 추측이다.""",
    # 관대 — 이 단계는 생성이라고 말한다
    "loose": """생성 기준 (중요)
5. **확신이 없어도 좋다.** 이 단계는 후보 생성이지 검증이 아니다.
   틀린 후보는 다음 단계에서 걸러진다.
6. 기전상 그럴듯하면 제시하라. 폭넓게 생각하라.
7. 가능하면 {k}개를 채워라.""",
}

_LEVEL = ("clinical", "preclinical", "mechanistic", "speculative")
_CONF = ("high", "medium", "low")


def build_prompt(disease: str, k: int, variant: str) -> str:
    if variant not in TEMPER:
        raise ValueError("variant 는 %s 중 하나여야 한다: %r"
                         % ("|".join(sorted(TEMPER)), variant))
    return (BASE.format(disease=disease, k=k, temper=TEMPER[variant].format(k=k))
            + TAIL)


def propose(disease: str, k: int = 20, variant: str = "loose",
            model: Optional[str] = None) -> Dict[str, Any]:
    """질환 → 후보 목록. 실패해도 예외를 던지지 않는다.

    반환 {ok, disease, variant, items, error, provenance, asked}
      items: [{drug, mechanism, rationale, evidence_level, confidence}]

    **`asked` 를 같이 돌려주는 이유** — strict 변형은 적게 답하는 것이
    정상 동작이다. 몇 개를 요청했는지 없이 "12개 나왔다"만 적으면
    나중에 그 12가 상한인지 자제인지 구분할 수 없다.
    """
    prompt = build_prompt(disease, k, variant)
    r = llm.complete(prompt, system=SYSTEM, as_json=True, model=model,
                     purpose="discover")   # 계량 — 생성 단계
    out = {"ok": False, "disease": disease, "variant": variant, "asked": k,
           "items": [], "error": r.get("error"),
           "provenance": r.get("provenance"), "cached": r.get("cached")}

    data = r.get("data")
    if isinstance(data, dict):                      # 배열을 감싸 보내는 모델 대응
        data = next((v for v in data.values() if isinstance(v, list)), None)
    if not r.get("ok") or not isinstance(data, list):
        out["error"] = out["error"] or "배열 형식 아님"
        return out

    seen, items = set(), []
    for d in data:
        if not isinstance(d, dict):
            continue
        name = str(d.get("drug", "")).strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:                             # 같은 이름 반복은 1개로 센다
            continue
        seen.add(key)
        lv = str(d.get("evidence_level", "")).lower().strip()
        cf = str(d.get("confidence", "")).lower().strip()
        items.append({
            "drug": name,
            "mechanism": str(d.get("mechanism", "")).strip(),
            "rationale": str(d.get("rationale", "")).strip(),
            # 모르는 값을 기본값으로 덮지 않는다. 빈 문자열로 남겨
            # "모델이 안 줬다"와 "모델이 speculative 라 했다"를 구분한다.
            "evidence_level": lv if lv in _LEVEL else "",
            "confidence": cf if cf in _CONF else "",
        })
    out.update(ok=True, items=items[:k])
    return out
