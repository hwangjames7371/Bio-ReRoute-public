# -*- coding: utf-8 -*-
"""2축 운용 구조 — 입구 · 출구 (제안서 §2.2 · §3.3-9)

제안서 §2.2 원문:

  > 사용자는 파이프라인의 서로 다른 단계에서 두 축을 각각 선택한다.
  > **축1(입구)** 은 후보를 어떻게 찾을지(정방향/역발상)를,
  > **축2(출구)** 는 어떤 규제 잣대로 심사할지(표준/신종 감염병 긴급)를 정한다.
  > 접근성(LMIC) 점수는 두 축과 독립적으로 조합된다.

## 긴급 프로파일을 **순진하게 만들면 우리가 반박하려는 실패를 재현한다**

"긴급이니까 문턱을 낮춘다"가 자연스러운 설계다. 그런데 그게 정확히
2020년에 일어난 일이다 — 우리 보고서 §1이 인용한 숫자가 이것이다.

```
2020년 2~11월 하이드록시클로로퀸 임상시험 NIH 등록부에만 206건
상당수 중복적·잠재적으로 비윤리적 · 결정적 반박 후에도 종료 지연
```

**긴급 상황에서 확신의 문턱을 낮췄기 때문에 생긴 일이다.**
우리 시스템의 존재 이유가 그걸 막는 것인데, 긴급 모드에서 문턱을 낮추면
시스템이 자기 논지를 배신한다.

## 그래서 긴급 프로파일은 **비대칭으로** 움직인다

|  | 표준 | 신종 감염병 긴급 | 왜 |
|---|---|---|---|
| `유망` 문턱 | 80 | **80 (그대로)** | 긴급이라고 확신을 싸게 팔지 않는다 |
| `기각` 문턱 | 40 | **25 로 낮춤** | 초기엔 근거가 얇다. **얇은 근거로 기각도 오류다** |
| 등록부(B6) | 선택 | **필수** | 발발 초기엔 미출판 결과가 지배적이다 |
| 확증 균형 | 0.5 | **0.35** | 조건부로 남기는 폭을 넓힌다 |

**낮춘 것은 기각 쪽이지 유망 쪽이 아니다.** 긴급 상황에서 늘어나는 것은
`보류` 이고, 그건 *"아직 모른다"* 를 더 자주 말하겠다는 뜻이다.

> 긴급 모드의 산출물은 **"더 많은 유망"이 아니라 "더 많은 기권"** 이다.
> 이게 이 프로파일의 전부다.

## 표준은 한 글자도 안 바뀐다

`표준` 프로파일의 값은 **현재 모듈 상수를 그대로 읽는다.** 하드코딩해서
베끼면 언젠가 상수만 바뀌고 프로파일이 안 따라와 조용히 갈라진다.
시험 [46]이 `표준 == 현재 동작` 을 검사한다 — 그래야 지금까지 잰
모든 수치가 그대로 유효하다.
"""

import os
from typing import Any, Dict, List, Optional

# ── 축1 입구 ────────────────────────────────────────────────
# 정방향 : 질환 → 후보 (`agents/discover.py`)
# 역발상 : 부작용 → 적응증 (`agents/reverse.py`) — 제안서가 "차별점"이라 쓴 쪽
ENTRY = {
    "정방향": {"module": "bioreroute.agents.discover", "fn": "propose",
             "설명": "질환에서 출발해 후보 약물을 제안한다"},
    "역발상": {"module": "bioreroute.agents.reverse", "fn": "propose",
             "설명": "부작용을 원하는 효과로 뒤집어 후보를 찾는다"},
    # 「직접 검증」 탭의 입구. **발굴을 안 한다** — 사용자가 쌍을 준다.
    #   제안서 §2.2 가 축1 을 *«후보를 어떻게 찾을지»* 로 정의했으므로,
    #   찾는 단계가 없는 입구에 정방향/역발상을 붙이면 **아무것도 안 하는
    #   토글**이 된다(결함 250 의 모양). 그래서 축을 지우는 대신
    #   **세 번째 값으로 정직하게 적는다.**
    "사용자 지정": {"module": None, "fn": None,
                "설명": "사용자가 약물–질환 쌍을 직접 준다 — **발굴 단계를 건너뛴다.** "
                      "정방향·역발상은 「병명으로 시작」 탭에서 갈린다"},
}


def _standard() -> Dict[str, Any]:
    """표준 잣대 = **지금 코드가 하는 그대로.** 베끼지 않고 읽는다."""
    from . import scoring
    return {"유망": 80, "기각": 40,
            "balance": scoring.BALANCE, "cap": scoring.LOGIT_CAP,
            "corr": scoring.CORR_FACTOR, "registry_required": False}


EXITS: Dict[str, Dict[str, Any]] = {
    "표준": {"설명": "통상 규제 잣대. 지금까지의 모든 측정이 이 값으로 났다",
           "값": _standard},
    "신종감염병긴급": {
        "설명": "발발 초기. **기각 문턱만 낮춘다** — 유망은 그대로",
        "값": lambda: dict(_standard(), **{"기각": 25, "balance": 0.35,
                                           "registry_required": True}),
    },
}


def exit_profile(name: str = "표준") -> Dict[str, Any]:
    if name not in EXITS:
        raise KeyError("모르는 출구 축: %r (있는 것: %s)" % (name, list(EXITS)))
    v = EXITS[name]["값"]()
    v["이름"] = name
    return v


# ── 접근성(LMIC) — **두 축과 독립** ──────────────────────────
#
# WHO 필수의약품목록(EML) 수록 여부가 가장 강한 단일 신호다. 전체 목록은
# 600여 품목이라 여기 다 넣지 않는다. **여기 있는 것은 목록의 일부다** —
# 없다고 해서 비필수라는 뜻이 아니고, 코드가 그렇게 말하지도 않는다.
#
# 자료가 부족한 항목을 0점으로 채우면 "조회 실패 = 나쁨"이 된다.
# 결함 35에서 배운 것이므로 **모르면 None 을 돌려준다.**
WHO_EML_CORE = {
    "metformin", "amoxicillin", "azithromycin", "ciprofloxacin", "rifampin",
    "rifampicin", "isoniazid", "dexamethasone", "prednisolone", "hydrocortisone",
    "hydroxychloroquine", "chloroquine", "ivermectin", "albendazole",
    "aspirin", "paracetamol", "acetaminophen", "ibuprofen", "morphine",
    "furosemide", "hydrochlorothiazide", "losartan", "enalapril", "amlodipine",
    "atenolol", "simvastatin", "warfarin", "heparin", "insulin", "levothyroxine",
    "fluoxetine", "amitriptyline", "haloperidol", "risperidone", "lithium",
    "valproic acid", "carbamazepine", "phenytoin", "levodopa", "methotrexate",
    "cyclophosphamide", "cisplatin", "doxorubicin", "tamoxifen", "allopurinol",
    "omeprazole", "ondansetron", "salbutamol", "albuterol", "beclometasone",
    "acyclovir", "zidovudine", "tenofovir", "lamivudine", "efavirenz",
    "nevirapine", "artemether", "artesunate", "amphotericin b", "fluconazole",
    "gentamicin", "ceftriaxone", "vancomycin", "meropenem", "doxycycline",
    "spironolactone", "digoxin", "naloxone", "diazepam", "tranexamic acid",
}


def accessibility(drug: str, s2: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """접근성 신호. **점수 하나로 뭉치지 않는다.**

    LMIC 접근성은 여러 축(가격·특허·냉장유통·경구투여)의 합인데, 우리는
    그중 둘만 볼 수 있다. 하나로 합치면 **모르는 것이 아는 것처럼 보인다.**

      eml     : WHO 필수의약품 목록(일부)에 있는가 — True / None
                **False 를 쓰지 않는다.** 목록이 부분집합이라 "없음"을
                "비필수"로 읽으면 안 된다
      oral_ok : Ro5 위반 0건이면 경구 가능성이 높다 (S2 결과 재사용)
                냉장유통이 필요한 생물학제제와 갈리는 가장 값싼 신호다
      small   : 저분자인가 (제안서 §1.2 탐색 범위). 이름 규칙만 본다 —
                여기서 ChEMBL 을 조회하면 판정 경로에 네트워크가 하나 는다

    제안서 §8.3이 예로 든 두 약이 그대로 갈려야 한다 —
    **플루복사민 MW 318 · Ro5 위반 0(경구 저가)** vs
    **렘데시비르 MW 603 · Ro5 위반 2(정맥 투여)**. 시험 [49]가 그걸 본다.
    """
    d = (drug or "").strip().lower()
    eml = True if d in WHO_EML_CORE else None
    oral = None
    if s2 and isinstance(s2, dict):
        v = s2.get("ro5_violations")
        if v is None:
            v = s2.get("violations")
        if isinstance(v, int):
            oral = (v == 0)
    small = None
    for suf in ("mab", "cept", "ase", "kin", "poetin", "grastim"):
        if d.endswith(suf):
            small = False
            break
    return {"eml": eml, "oral_ok": oral, "small_molecule": small,
            "note": ("부분 목록·간접 신호다. **점수로 합치지 않는다.** "
                     "효능 판정과 **분리된** 접근성 층이다")}


def describe(entry: str = "정방향", exit_: str = "표준") -> str:
    e = ENTRY.get(entry, {}).get("설명", "?")
    x = EXITS.get(exit_, {}).get("설명", "?")
    return "축1 입구 [%s] %s\n축2 출구 [%s] %s" % (entry, e, exit_, x)
