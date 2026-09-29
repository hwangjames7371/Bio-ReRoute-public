# -*- coding: utf-8 -*-
"""웹 데모의 **로직**. UI는 여기 없다.

`app.py` 가 Gradio로 감싼다. 나누는 이유는 둘이다.

1. **UI 없이 전 경로를 시험할 수 있다.** Gradio를 못 까는 환경에서도
   로직은 실제로 태워 볼 수 있다
2. UI를 바꿔도 로직이 안 흔들린다

## 이 모듈이 지켜야 하는 것

| | |
|---|---|
| **비용** | 공개 링크에 내 키가 물린다. 일일 상한 · 캐시 적중은 무료 |
| **안전** | 통제 물질 질의 차단 (`core/safety.py` · 제안서 §5) |
| **정직** | 막혔으면 막혔다고, 한도면 한도라고 적는다. **빈 결과를 내지 않는다** |
| **감사** | 판정만 주지 않는다. PMID·인용 원문·가중치를 같이 준다 |

## 왜 `run_pipeline` 을 안 쓰고 게이트를 직접 도는가

제안서 §6이 요구한 것이 **"각 후보가 깔때기를 통과·탈락하는 단계를
실시간 진행 표시로"** 다. 통째로 돌리면 중간을 보여줄 수 없다.
게이트를 하나씩 돌면서 그때그때 진행을 알린다.
"""

import os
import time as _t
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .core import gates, safety
from .core.state import Candidate, RunState
from .io import budget, cache, llm

# 미리 계산해 둔 예시 — 캐시에 있어 **즉시·무료**다.
#   서사가 있는 것으로 고른다: 기각 / 유망 / 보류가 다 나와야
#   "이 시스템은 전부 기각한다"는 오해를 막는다.
# ⛔ 08-14 결함 209 — **설명문에 판정·수치를 적지 마라**
#
#   `demo_cases.json` 을 다시 구웠더니 여섯 중 **넷의 판정이 바뀌었다**
#   (edaravone 보류 70% → 조건부 28% · fluvoxamine 98% → 84% ·
#    metformin 조건부 56% → 기각 26% · rifampin 50% → 56%).
#   그런데 설명문이 «기권(보류)이 정답인 자리»·«유망 97% 가 나왔다» 를
#   **상수로** 들고 있어서 **화면이 자기 판정과 어긋난 말을 했다.**
#
#   `CLAUDE.md §4` 가 못 박아 둔 것 —
#     *"해석 문구를 상수로 고정하지 마라. 방향을 데이터에서 읽어라."*
#
#   그래서 설명은 **«왜 이 사례를 골랐나»** 만 적는다. **결과는 안 적는다.**
#   판정과 확률은 바로 옆에 데이터에서 찍힌다. 시험 [119].
PRESETS = [
    ("hydroxychloroquine / COVID-19",
     "결정적 반박 RCT가 여럿 — 기각의 교과서"),
    ("baricitinib / COVID-19",
     "숙주 표적이라 도킹을 건너뛰고 임상 근거로 간다"),
    ("metformin / Malignant neoplasm of breast",
     "Ro5 통과가 투과성을 뜻하지 않는다 — 시연에서 발견한 구멍"),
    ("edaravone / Amyotrophic Lateral Sclerosis",
     "승인약인데 근거가 갈린다 — 확증 설계가 양방향인 자리"),
    # ── 아래는 **우리 시스템이 우리 제안서와 어긋난** 사례다 ──────────
    #   빼지 않는다. 이게 이 프로젝트가 파는 것이다.
    #
    #   ⚠ **여기 설명문에는 마크다운을 쓰지 마라** (결함 76).
    #     이 문자열은 `gr.Radio` 의 **선택지 라벨**로 들어가고, gradio 는
    #     선택지를 **평문으로** 그린다. 초판에 백틱과 별표를 넣었더니
    #     화면에 `` `보류` `` 와 `**유망 97%**` 가 **원문 그대로** 찍혔다.
    #
    #     08-07 브라우저로 실제 화면을 읽고 나서야 보였다 — 다른 넷은
    #     마크다운이 없어서 멀쩡했고 **이 한 줄만 티가 났다.**
    #     시험 [62]가 PRESETS 전체에 마크다운이 없는지 검사한다.
    ("fluvoxamine / COVID-19",
     "제안서는 「보류」를 예상했는데 우리 판정은 다르다 — 왜인지 근거를 보라"),
    # ── 08-11 추가 — **구조 경로를 실제로 타는 첫 후보** ─────────────
    #   라우터가 `직접·병원체 · rpoB → structure` 로 보내고 S1 이 돈다.
    #   앞의 다섯은 전부 숙주·간접이라 S1 이 SKIP 이었다(결함 106).
    #
    #   **판정은 볼 것이 아니다.** 승인 적응증이라 재창출 가설이 아니고,
    #   그래서 보류가 나온다. 여기서 보라는 것은 **구조 경로가 실제로
    #   열리고 S1 이 무엇을 말하는가** 다.
    ("rifampin / Tuberculosis",
     "구조 경로를 타는 대조군 — 이미 승인된 적응증이라 새 발견이 아니다"),
]

# ⚠ **`ORDER` 여덟과 맞춰 둔다** — 결함 247.
#   `s1`·`hitl` 이 빠져 있어 화면에 영문 그대로 찍혔다(`.get(name, name)` 폴백).
#   `adjudicate` 는 `ORDER` 밖이지만 **게이트별 초에 찍히므로** 여기 둔다.
# ⚠ **`ORDER` 8개로는 모자란다** — 결함 255.
#   trail 에는 게이트 **이름**만 남는 게 아니라 게이트가 **자기 안에서
#   찍는 이름**도 남는다. `rag` 게이트가 `factcheck` 로 적고, `skeptic`
#   과 `router` 가 `veto` 로 적는다. 그 둘이 여기 없어서 화면 표에
#   **영문 그대로** 찍혔다 — 심사위원이 **첫 탭에서 처음 보는 표**다.
#
#   결함 247 이 «`s1`·`hitl` 이 영문으로 찍힌다» 를 잡고 `ORDER` 8개 +
#   `adjudicate` 로 맞췄는데, **`ORDER` 를 기준으로 센 것이 문제였다.**
#   기준을 «실제로 trail 에 나오는 이름» 으로 바꾼다.
GATE_KO = {"f0": "근거가 실제로 있는가", "rag": "논문 읽고 지지·반박 가르기",
           "router": "검증 방식 정하기", "s1": "표적 구조 신뢰도",
           "s2": "약물다움 점검", "skeptic": "반대 근거 더 찾기",
           "registry": "임상시험 등록부 확인", "hitl": "전문가가 거절한 목록",
           # ⚠ 09-17 추가. **`ORDER` 에 있는데 09-15~16 내내 여기 없었다** —
           #   그동안 화면에 영문 `fulltext` 가 그대로 찍힐 상태였다.
           #   `demo_cases.json` 이 08-14 판이라 「판정 사례」 탭에서만 안
           #   보였을 뿐이고, **재굽는 순간 노출됐을 것**이다.
           #   시험 [82]가 이제 `ORDER` 전수를 검사한다.
           "fulltext": "논문 전문에서 저자가 적은 한계 읽기",
           "adjudicate": "종합 판정",
           # ↓ ORDER 에 없지만 trail 에 남는 것들
           "factcheck": "논문 읽고 지지·반박 가르기", "veto": "결정적 반박",
           "입력": "입력", "discovery": "후보 만들기", "dedupe": "중복 시험 정리",
           # ── **옛 표시 이름도 받는다** (결함 275) ──────────────────
           #   08-19 에 단계 이름을 사용자 말로 바꿨다. 그런데 구운 사례
           #   (`demo_cases.json`)에는 **옛 이름이 문자열로 저장돼 있다** —
           #   `F0 근거 실재성`·`S2 리간드 개발성` 처럼. 표를 갈아 끼우자
           #   그것들이 **고아**가 됐다(결함 255 와 같은 자리, 이번엔 내가 만들었다).
           #
           #   **구운 파일은 안 고친다** — 여러 문서가 인용하는 기준점이다.
           #   대신 **옛 이름을 키로 같이 받는다.** 화면은 늘 새 이름을 낸다.
           "F0 근거 실재성": "근거가 실제로 있는가",
           "L2 팩트체커": "논문 읽고 지지·반박 가르기",
           "기전 라우터": "검증 방식 정하기",
           "S1 구조 신뢰도": "표적 구조 신뢰도",
           "S2 리간드 개발성": "약물다움 점검",
           "회의주의자": "반대 근거 더 찾기",
           "등록부(CT.gov)": "임상시험 등록부 확인",
           "HITL 음성 KB": "전문가가 거절한 목록",
           "하드 비토": "결정적 반박"}


# ── 09-29 · 시연에서 **끈** 게이트를 화면에 설명하는 말 (결함 378) ─────────────
#   `gates.DEMO_GATES` 의 사유는 **개발 메모**다 — ««자율» 주장이 흐려진다» · «발표장에서 시연이
#   멈춘다» · 결함 색인. 그대로 화면에 찍혀 «점수를 위해 껐다» 로 읽혔다. 화면 말은 여기 둔다 —
#   `GATE_KO` 가 화면 이름을 여기 두는 것과 같은 까닭이다. `core/gates.py` 는 판정 경로
#   코드(코드 지문)라 글자 때문에 건드리지 않는다.
#   ⚠ 시연 구성이 새 게이트를 끄면 여기에 화면 말을 **먼저** 적는다 — 시험 [162]⑧ 이 본다.
GATE_OFF_SAY = {
    "hitl": "전문가가 이미 거절한 쌍을 다시 묻지 않게 막는 운용 기능입니다 — 거절 목록의 내용에 "
            "따라 결과가 달라지므로, 자동 판정을 재현하는 구운 사례와 벤치마크에서는 끕니다",
    "registry": "임상시험 등록부(ClinicalTrials.gov)를 조회합니다 — 응답 시간이 길어 구운 사례에서는 "
                "끄고, 라이브 실행에서 «신종감염병긴급» 심사 기준을 고르면 의무로 켭니다",
}


def _apply_exit(cfg: Dict[str, bool], exit_: str) -> Dict[str, bool]:
    """출구 축이 **게이트 구성**까지 바꾼다 — `registry_required` (결함 256).

    제안서 §2.2 의 «긴급» 은 문턱 셋만이 아니다. `profiles` 가
    `registry_required: True` 를 같이 낸다. 시연 대본 컷 4 가 그걸
    소리 내어 말한다 — *«등록부 조회가 의무가 됩니다. **긴급할수록
    실패한 임상을 더 봐야 합니다.** 덜 보는 게 아니라요.»*

    **말만 하고 안 켜면 그게 결함 256 그 자체다.** 그래서 켠다.
    비용이 는다(등록부 게이트 1개) — 그건 이 잣대의 뜻이 그렇기 때문이다.

    표준이면 **한 글자도 안 바꾼다** — 동결 수치가 전부 표준으로 났다.
    """
    try:
        prof = gates.profiles.exit_profile(exit_ or "표준")
    except KeyError:
        return cfg
    if prof.get("registry_required"):
        cfg = dict(cfg, registry=True)
    return cfg


def parse(text: str):
    """'약물 / 질환' → (약물, 질환). 못 읽으면 ValueError."""
    for sep in ("/", "|", "::"):
        if sep in text:
            a, b = [x.strip() for x in text.split(sep, 1)]
            break
    else:
        raise ValueError("'약물 / 질환' 형식으로 입력해라 (예: metformin / Breast Cancer)")
    if not a or not b:
        raise ValueError("약물과 질환이 모두 있어야 한다")
    if len(a) > 80 or len(b) > 80:
        raise ValueError("입력이 너무 길다 (각 80자 이내)")
    return a, b


def _evidence(c: Candidate) -> List[Dict[str, Any]]:
    """근거 카드. **판정만 주지 않는다** — 이게 이 시스템의 본체다."""
    out = []
    for e in list(c.refute) + list(c.support):
        out.append({"방향": "반박" if e.direction == "refute" else "지지",
                    "가중치": round(e.weight, 2), "출처": e.source,
                    "PMID": e.pmid or "", "설명": e.tag, "인용": e.note or "",
                    "검증": e.quote_how or "",
                    "회수": e.stage or "",
                    "조건": e.pico or {}})
    out.sort(key=lambda x: -x["가중치"])
    return out


def _ttr(st) -> Optional[Dict[str, Any]]:
    """Time-to-Refute. **실패하면 `None`** — 0 으로 채우면 «빨랐다» 는 거짓말이 된다."""
    try:
        d = dict(gates.time_to_refute(st))
        # **안 쟀으면 «0초» 를 내지 않는다** — 결함 254.
        #   계측이 빠지면 `sum([]) == 0` 이라 «0초» 가 나온다. 그건
        #   «빨랐다» 가 아니라 **«안 쟀다»** 다. 둘을 안 가르면 결함 89 다.
        #   그래서 여기서 **구조로** 막는다 — 다음에 계측이 또 빠지면
        #   화면은 «0초» 대신 **«아직 안 쟀다»** 를 낸다.
        if d.get("전체_초") is None and not d.get("게이트별"):
            return None
        d["warm"] = gates._cache_warm()
        return d
    except Exception:
        return None


def _trail(c: Candidate) -> List[Dict[str, str]]:
    return [{"게이트": GATE_KO.get(r.gate, r.gate), "결과": r.outcome,
             "설명": r.detail} for r in c.trail]


# ── 09-29 · **일시 장애로 판정에 못 들어간 초록** — 다시 돌리면 채워진다 (결함 380) ─────────
#
#   09-29 라이브 점검에서 같은 병명(COVID-19)을 두 번 돌렸더니 **후보 열 개와 순서는 같고**(생성은 캐시)
#   두 후보의 판정이 달랐다(nitazoxanide 조건부 26 → 기각 8 · dornase alfa 보류 70 → 조건부 65). 데운
#   둘째 실행이 **새 호출 6번**을 했다. 캐시는 일시 장애를 저장하지 않고(`cache.put` · 결함 37) JSON 파싱
#   실패도 저장하지 않는다(`llm._call`) — 그래서 첫 실행에서 **못 받은 초록 · 실패한 판정 호출**이 둘째에
#   다시 나가 근거가 채워진다. 판정 경로는 그걸 보수적으로 처리했다(근거에서 뺀다). 문제는 **어느 후보가
#   몇 건을 못 읽었는지 기록도 화면도 말하지 않은 것** — 그래서 두 실행이 왜 갈렸는지 못 갈랐다.
#
#   센다: `factcheck` 기록(1차 · 회의주의자 모두)에서 «초록 취득 실패» 중 **일시 장애인 것**
#   (`cache.transient` 와 같은 규칙 — 영구 오류는 캐시에 남아 다음에도 같다) + «LLM 실패» 중 오류가 있는 것
#   («배열 형식 아님» 은 응답이 캐시에 남으므로 다음에도 같다 — 빼고 센다). **판정은 안 바꾼다.**
_FETCH_FAIL = "초록 취득 실패: "
_LLM_FAIL = "LLM 실패: "


def _transient_skips(c: Candidate) -> int:
    """이 후보에서 **이번 실행의 일시 장애 때문에** 판정에 못 들어간 초록 수 — 다시 돌리면 달라질 수 있다."""
    n = 0
    for r in (getattr(c, "factcheck", None) or []):
        s = str((r or {}).get("skip") or "")
        if s.startswith(_FETCH_FAIL):
            n += 1 if cache.transient({"error": s[len(_FETCH_FAIL):]}) else 0
        elif s.startswith(_LLM_FAIL) and s != _LLM_FAIL + "배열 형식 아님":
            n += 1
    return n


def _served_since(call0: int) -> dict:
    """`call0` 이후 **누가 답했나** — 새 호출과 캐시 적중을 **나눠서** 센다.

    ## 08-20 — 캐시를 빼고 세니 화면이 비었다

    승우: *«아직도 LLM 모델은 안 나왔어»*

    앞판은 `if rec.get("cached"): continue` 로 **캐시 적중을 버렸다.**
    그런데 시연에서 예시를 다시 누르면 **전부 캐시에서 나온다** —
    그러면 집계가 `{}` 가 되고 화면이 «모델» 칸을 통째로 안 그렸다.

    **캐시 적중을 숨기는 것은 §4.1 규약을 어기는 것이기도 하다** —
    *«이 초는 «빠르다» 가 아니라 «이미 받아 뒀다» 다»*. 답이 어디서
    왔는지는 **판정의 재현성 그 자체**다.

    캐시 기록에도 `served_by`·`temperature_used` 가 들어 있다
    (`llm.py:158`). 그러니 **셀 수 있고, 세는 게 맞다.**

    돌려주는 꼴: `{"gpt-4o-mini @0.0": {"새로": 5, "캐시": 2}}`
    """
    served = {}
    for rec in llm.call_log()[call0:]:
        k = "%s @%s" % (rec.get("served_by") or "?",
                        rec.get("temperature_used", "?"))
        d = served.setdefault(k, {"새로": 0, "캐시": 0})
        d["캐시" if rec.get("cached") else "새로"] += 1
    return served


# ── **시연 구성은 이름 하나로 정한다** — 09-17 ────────────────────────
#
#   08-11 에 `B5S`(= B5 + s1) 를 만들면서 *"데모가 B5S 로 돈다 — 안
#   그러면 S1 이 꺼진 채 시연된다"* 를 시험 [82]로 못 박았다.
#   **09-15 에 `fulltext` 를 만들고 똑같이 빠뜨렸다.** 같은 사고 두 번째.
#
#   그래서 이제 **구성 이름을 상수 하나**로 둔다. 부르는 쪽이 문자열을
#   따로 쓰면 또 갈린다(결함 159: *"고치는 쪽이 검사하는 쪽보다 좁으면"*).
#   구성 자체는 `gates.DEMO_GATES` 표에서 파생되고, 시험 [82]가
#   **`ORDER` 전수가 그 표에 있는지**까지 본다.
DEMO_CONFIG = "B5SF"

def run_pair(text: str, config: str = DEMO_CONFIG,
             progress: Optional[Callable[[str, str], None]] = None,
             cache_path: str = "pubmed_cache.json",
             exit_: str = "표준") -> Dict[str, Any]:
    """한 가설을 검증한다. **예외를 밖으로 던지지 않는다** — 화면이 죽으면 안 된다.

    반환 {ok, 상태, 메시지, 판정, 신뢰도, 사유, 근거[], 게이트[], 비용, 예산}
    `상태` 는 정상 · 입력오류 · 차단 · 한도소진 · LLM없음 · 오류 중 하나.
    """
    def say(stage, detail=""):
        if progress:
            try:
                progress(stage, detail)
            except Exception:
                pass

    # ⚠ **어느 경로로 끝나도 키가 있어야 한다.** 「모델」을 정상 반환에만
    #   넣으면 «LLM없음·차단·오류» 로 끝났을 때 화면이 키를 못 찾는다.
    base = {"ok": False, "판정": "", "신뢰도": None, "사유": "",
            "근거": [], "게이트": [], "비용": 0, "예산": budget.status(),
            "모델": {}, "시각": datetime.now().strftime("%Y-%m-%d %H:%M")}

    # ── ① 입력 ────────────────────────────────────────────
    try:
        drug, disease = parse(text)
    except ValueError as e:
        return dict(base, 상태="입력오류", 메시지=str(e))

    # ── ② 안전 (제안서 §5) — 예산보다 먼저 본다 ─────────────
    #     막힐 질의에 실행권을 쓰면 안 된다.
    bad, why = safety.screen(drug, disease, text)
    if bad:
        say("안전 게이트", "차단")
        return dict(base, 상태="차단",
                    메시지="통제 물질 질의로 판단해 중단했다 — %s" % why)

    # ── ③ LLM 없으면 **미리** 끊는다 ───────────────────────
    #     근거가 비어 있어 전부 `보류`가 나오는데, 그건 그럴듯한 빈 결과다.
    if not llm.available():
        return dict(base, 상태="LLM없음",
                    메시지="이 배포본에 LLM이 설정돼 있지 않다. "
                           "「판정 사례」 탭은 미리 구워 둔 결과라 그대로 볼 수 있다.")

    # ── ④ 예산 — **먼저 소비하고 나중에 실행한다** ──────────
    #
    #   예시는 미리 계산돼 캐시에 있으므로 **아예 세지 않는다.**
    #   이렇게 목록으로 가르는 이유가 있다 — 처음엔 `llm.spent()==0` 이면
    #   환불하게 했는데, 그러면 **예산이 다른 모듈의 계수기에 의존한다.**
    #   그 계수기가 어긋나면 공개 링크에서 조용히 돈이 샌다.
    #   **비용 문제에서는 의존을 줄이고 안전한 쪽으로 틀린다.**
    is_preset = any(text.strip() == p for p, _ in PRESETS)
    left = None
    if not is_preset:
        ok, left = budget.take()
        if not ok:
            return dict(base, 상태="한도소진", 예산=budget.status(),
                        메시지="오늘 실행 한도를 다 썼다. 내일 다시 열리고, "
                               "아래 예시는 미리 계산돼 있어 지금도 볼 수 있다.")

    try:
        cache.configure(cache_path)
        cache.load()                      # **질의 전에** 읽는다 (결함 26·27)
        before = llm.spent()
        _call0 = len(llm.call_log())     # **누가 답했나** — 결함 234

        c = Candidate(name="%s / %s" % (drug, disease), origin="입력",
                      query="%s AND %s" % (drug, disease),
                      drug=drug, disease=disease, pubchem=drug)
        c.note("입력", "INPUT", "사용자가 입력한 가설 — 근거는 게이트가 수집한다")
        st = RunState(query_title="%s / %s" % (drug, disease), settings=config,
                      stamp=base["시각"], candidates=[c],
                      config=_apply_exit(dict(gates.CONFIGS[config]), exit_),
                      exit_=exit_ or "표준")

        # 게이트를 하나씩 — 통째로 돌리면 중간을 보여줄 수 없다
        #
        # ⚠ **시간을 여기서 적는다** (결함 254). `gates.run_funnel` 이
        #   `st.timing[name]` 을 적는데 **이 루프는 그걸 안 지나간다** —
        #   진행 표시를 하려고 게이트를 직접 부르기 때문이다. 그래서
        #   `st.timing` 이 **빈 채로** `_ttr` 에 갔고 화면이
        #   *«반박 근거 수집 0초 · 전체 None초»* 를 찍었다.
        #   **25초 걸린 실행에 «0초» 를 적는 것은 거짓말이다.**
        _t0 = _t.perf_counter()
        for name in gates.ORDER:
            if not st.config.get(name, False):
                c.note(name, "SKIP", "config off")
                continue
            say(GATE_KO.get(name, name), "실행 중")
            _g0 = _t.perf_counter()
            st = gates.REGISTRY[name](st)
            st.timing[name] = round(_t.perf_counter() - _g0, 3)
            last = [r for r in c.trail if r.gate == name]
            say(GATE_KO.get(name, name),
                last[-1].outcome if last else "완료")
            if c.killed:                  # 비용 순서 원칙 — 죽은 후보는 더 안 태운다
                say("중단", "F0에서 기각돼 이후 게이트를 태우지 않는다")
                break
        st = gates.gate_adjudicate(st)
        st.timing["_전체"] = round(_t.perf_counter() - _t0, 3)
        st.timing["_후보수"] = len(st.candidates)
        cache.save()

        # 캐시 적중이면 돌려준다 — **다만 이건 덤이지 방어가 아니다.**
        #   방어는 위의 `is_preset` 이다(다른 모듈에 의존하지 않는다).
        spent = llm.spent() - before
        if spent == 0 and not is_preset:
            budget.refund()
        return {"ok": True, "상태": "정상", "메시지": "",
                "판정": c.verdict, "신뢰도": c.confidence, "사유": c.reason,
                "근거": _evidence(c), "게이트": _trail(c),
                # **`s1` 을 실어 보낸다** (결함 109). 08-11에 rifampin 을
                # 구워 대시보드에 넣었는데 뷰어가 여전히 *"구조를 표시하지
                # 않는다"* 였다. `c.s1` 이 반환에 없어서 `cif_url` 이
                # 구운 파일까지 못 갔기 때문이다 — **게이트는 돌았고
                # 결과만 버려졌다.**
                "s1": getattr(c, "s1", None),
                # **Time-to-Refute 를 실어 보낸다** — 결함 250.
                #   `gates.time_to_refute()` 는 08-06 부터 **있었는데**
                #   `run_pair` 가 한 번도 안 불렀다. 그래서 화면 하단이
                #   *«「직접 검증」 탭에서 한 번 돌리면 채워진다»* 라고
                #   **약속해 놓고 돌려도 안 채워졌다.**
                #   `s1`(결함 109)·`served_by`(결함 234)와 **같은 형태** —
                #   게이트는 돌았고 **결과만 버려졌다.**
                "ttr": _ttr(st),
                # ── **누가 답했나** (08-20 승우: «우리가 돌린 LLM 모델이
                #    어떤 건지도 나와야 하는 거 아닌가?») ────────────
                #
                #   `run_disease` 는 이걸 집계하는데 **`run_pair` 는
                #   안 했다.** `s1`(109)·`ttr`(250)·`served_by`(234)와
                #   **같은 형태다 — 게이트는 돌았고 결과만 버려졌다.**
                #
                #   ⚠ **온도까지 적는다.** `TEMPERATURE = 0.0` 이라
                #     적어 놔도 모델이 온도를 안 받으면 기본값으로
                #     되돌아간다(`llm._NO_TEMP`). 그러면 같은 프롬프트가
                #     매번 다른 답을 낸다 — 08-18 에 생성이 10개와
                #     2개로 갈렸고 **모델은 하나였다**(결함 236).
                "모델": _served_since(_call0),
                # 09-29 · 이번 실행의 일시 장애로 못 읽은 초록 수(결함 380) — 0 이 아니면 다시 돌리면 달라질 수 있다
                "일시실패": _transient_skips(c),
                "비용": spent, "예산": budget.status(),
                "시각": base["시각"], "질의": "%s / %s" % (drug, disease)}
    except safety.Blocked as e:
        budget.refund()
        return dict(base, 상태="차단", 메시지=str(e))
    except Exception as e:
        # **실패를 조용히 빈 결과로 만들지 않는다.** 무엇이 터졌는지 적는다.
        return dict(base, 상태="오류", 예산=budget.status(),
                    메시지="%s: %s" % (type(e).__name__, str(e)[:200]))


# ─────────────────────────────────────────────────────────────
# 의료 면책 — **공개 링크로 나가는 화면에 이게 없었다** (결함 54)
#
# 이 시스템은 실재하는 승인 약물과 실재하는 질환에 대해
# `기각 4%` · `유망 97%` 같은 **임상처럼 들리는 문장**을 출력한다.
# 그리고 본선 제출물에 **공개 서비스 배포 링크**가 있다.
#
# 검색으로 흘러든 환자가 자기 약에 대한 `기각` 을 보고 복약을 바꾸면
# 그 피해는 실재한다. 제안서 §5(연구 윤리)는 **통제 물질 오남용**만
# 다뤘고 **출력 자체의 오용**은 다루지 않았다.
#
# 상수로 두고 모든 출력 경로에 붙인다. 화면 한 곳에만 적으면
# 스크린샷·복사로 떨어져 나간다 — **판정 문자열에 같이 실어야 한다.**
DISCLAIMER = (
    "⚠ **연구용 도구다. 의학적 조언이 아니다.** 이 출력은 공개 문헌을 "
    "기계적으로 종합한 것이고, 진단·치료·복약 결정에 쓰면 안 된다. "
    "**환자는 이 화면을 근거로 약을 바꾸지 마라** — 담당 의사와 상의해라. "
    "판정은 특정 시험의 조건(대상군·용량·시점)에 매인 것이며 "
    "그 약의 승인된 용도에 대한 판단이 아니다."
)

# ─────────────────────────────────────────────────────────────
# AI 생성 표기 — 제안서 §5 여덟 항목 중 **마지막 ❌** 였다
#
# §5 ⑤ 가 *"산출물에 AI 생성 표기 + 근거 PMID·점수 병기"* 를 약속했다.
# PMID·점수는 처음부터 붙었고 **표기만 그동안 줄곧 없었다.**
# `제안서_전수대조.md` 가 그걸 *"어려운 일이 아니라 **안 한 것**"* 이라 적었다.
#
# 면책과 **같은 규율**로 붙인다 — 상수 하나, 판정 문자열에 같이 실어서
# 스크린샷·복사로 떨어져 나가지 않게 한다(결함 54에서 배운 것).
#
# **문구를 좁게 쓴다.** "AI가 만들었다"로 끝내면 사람이 무엇을 했는지
# 지워진다. 실제 분업은 이것이다 —
#   생성·요약·분류  LLM        ← 여기가 AI 산출물이다
#   근거 문장        PubMed 원문 ← LLM 이 쓴 게 아니다. 대조해서 통과한 것만
#   판정 확률        규칙 기반 로그오즈 ← LLM 이 정하지 않는다
AI_NOTICE = (
    "🤖 **AI 생성물이다.** 후보 생성·문헌 요약·기전 분류는 대규모 언어모델이 "
    "했다. 다만 **인용 문장은 PubMed 초록 원문과 대조해 통과한 것만** 남기고, "
    "**판정 확률은 LLM 이 아니라 규칙 기반 로그오즈 합**으로 계산한다. "
    "모든 판정에 근거 PMID·인용 원문·가중치가 함께 붙는다."
)

SHORT_AI_NOTICE = "🤖 AI 생성물 · 인용은 원문 대조 · 확률은 규칙 계산"

SHORT_DISCLAIMER = "⚠ 연구용 · 의학적 조언 아님 · 복약 결정에 쓰지 마라"


# ══════════════════════════════════════════════════════════════════
#  병명 하나 → 후보 생성 → 깔때기        명세 `사전명세_병명입구.md`
#                                        봉인 `78e44afa1b3b`
#
#  ## 제안서 §6 흐름도의 🟥 두 칸
#
#      그림   [병명 입력] → 생성 → F0 → Top-3 → 라우터 → …
#      실측   🟥            🟦     🟩   🟥       🟩
#
#  생성 축은 340건을 돌려 사전 기준을 통과했는데(§3.3-5) **화면 흐름에
#  안 붙어 있었다.** 즉 «병명을 넣으면 후보가 나옵니까» 에 *"벤치마크에서는
#  됩니다"* 라고 답해야 했다.
#
#  ## 동결이 안 깨진다 — 확인하고 적는다
#
#      gates.ORDER = [hitl, f0, rag, router, s1, s2, skeptic, registry]
#      gate_discover  ← **이 목록 밖이다**
#
#  입구를 붙여도 B0~B6 의 trail 이 안 바뀐다.
#
#  ## 「Top-3」는 **표시 순서이지 절단이 아니다**
#
#  제안서 원문에 Top-3 **절단 기준이 없다**(검색 0건 · 그림에만 있다).
#  기준을 우리가 정하면 그게 자유도가 되므로 — **자르지 않는다.**
#  F0 를 통과한 전부를 태우고, 화면에서만 상위 3을 먼저 편다.
#  그러면 «무엇으로 자를까» 라는 자유도가 판정에서 사라진다.
# ══════════════════════════════════════════════════════════════════

DISEASE_K = 10              # 명세 §2 — 요청 후보 수. **여기서 안 바꾼다**
TIME_BUDGET = 150.0         # 명세 §1 — 초. 3분 시연의 절반

# ══════════════════════════════════════════════════════════════════
#  깔때기 병렬화 — **판정이 안 바뀌는 것이 유일한 합격 조건이다**
#
#  후보 8개를 순차로 태워 155~159초가 나왔다(상한 150 초과, 두 번 다).
#  게이트는 **후보별로 독립**이다 — 한 후보의 trail 이 다른 후보를
#  안 본다. 그래서 병렬이 가능하다. **빨라지는 건 부수 효과지 목적이
#  아니다.** 목적은 «같은 판정을 더 짧게» 이고, 앞 절반이 깨지면
#  뒤 절반은 의미가 없다.
#
#  ## 병렬이 판정을 바꿀 수 있던 자리 — 넣기 **전에** 셋을 막았다
#
#    결함 229  호출 간격이 스레드마다 따로 잤다 → 429 → 「조회 실패」
#              → `sources.throttle()` 전역 간격 · `cache._LOCK`
#    결함 230  `spent() >= MAX_CALLS` 가 검사-후-실행 → 상한 초과 호출
#              → `llm._reserve()` 원자적 예약
#    (남는 것) 공급자 429 → `FALLBACKS` 로 **다른 모델이 답한다**
#              → 그래서 일꾼 수를 **환경변수로 열되 기본을 낮게** 둔다
#
#  ## 일꾼 수 기본값을 왜 4로 두는가
#
#  1 로 두면 «켠 사람만 빨라지는» 기능이라 시연에서 안 쓰인다.
#  크게 두면 위 세 번째(모델 교체)가 커진다. **4 는 NCBI 제한(초당 3,
#  키 있으면 10)과 같은 자리**라 `throttle()` 이 실제로 병목이 되어
#  요청률이 스레드 수에 비례해 늘지 않는다.
#
#  **동결 수치에는 안 닿는다** — `run_disease` 는 화면 전용이고
#  `bench.run`(B0~B6)은 이 경로를 안 지난다.
# ══════════════════════════════════════════════════════════════════

DISEASE_WORKERS = int(os.environ.get("BIOREROUTE_DISEASE_WORKERS", "4"))


def _median(v: List[float]) -> float:
    s = sorted(v)
    if not s:
        return 0.0
    m = len(s) // 2
    return round(s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2.0, 2)


def _funnel_one(c: Candidate, rest: List[str], config: str,
                stamp: str, exit_: str = "표준") -> Dict[str, float]:
    """후보 **하나**를 깔때기에 태운다. 게이트별 초를 돌려준다.

    스레드에서 불린다 — **여기서 모듈 전역을 쓰지 않는다.**
    `RunState` 도 후보도 이 호출만의 것이다.
    """
    import time as _t
    # ⚠ **출구 축을 여기까지 들고 와야 한다** (결함 256). 후보별로 새
    #   `RunState` 를 만드는데 `exit_` 를 안 넘기면 **판정만 표준으로**
    #   난다 — 화면은 긴급인데 판정은 표준인, 정확히 그 결함의 모양이다.
    one = RunState(query_title=c.name, settings=config, stamp=stamp,
                   candidates=[c], exit_=exit_ or "표준",
                   config=_apply_exit(dict(gates.CONFIGS[config]), exit_))
    secs: Dict[str, float] = {}
    for name in rest:
        if not one.config.get(name, False):
            c.note(name, "SKIP", "config off")
            continue
        t = _t.perf_counter()
        one = gates.REGISTRY[name](one)
        secs[name] = round(_t.perf_counter() - t, 2)
        if c.killed:
            break
    t = _t.perf_counter()
    gates.gate_adjudicate(one)
    secs["adjudicate"] = round(_t.perf_counter() - t, 2)
    return secs


def _funnel_many(alive: List[Candidate], rest: List[str], config: str,
                 stamp: str, t0: float, budget_s: float,
                 say: Callable[[str, str], None],
                 workers: int = DISEASE_WORKERS, exit_: str = "표준"):
    """후보 여럿을 태운다. **일꾼이 1이든 4든 코드 경로는 하나다.**

    두 갈래로 쓰면 방어가 두 곳이 되어 한쪽만 고치는 결함이 난다
    (결함 98·222 가 그 형태였다). `max_workers=1` 이면 제출 순서대로
    하나씩 돌아 순차와 **문자 그대로 같은 실행**이 된다.

    돌려주는 것: `(태운 후보[], 못 태운 이름[], 게이트별 초{}, 깔때기 벽시계)`
    **못 태운 것은 개수가 아니라 이름으로 적는다** — 병렬에서는
    «뒤에서 몇 개» 가 아니라 «이것과 이것» 이기 때문이다.
    """
    import concurrent.futures as _cf
    import threading as _th
    import time as _t

    n = len(alive)
    out: List[Optional[Candidate]] = [None] * n
    secs: Dict[str, List[float]] = {}
    lock = _th.Lock()
    seen = [0]

    def work(i, c):
        # 시작 시점에 상한을 넘었으면 **안 태운다.** 기각이 아니다.
        if _t.monotonic() - t0 > budget_s:
            return i, None, None
        s = _funnel_one(c, rest, config, stamp, exit_)
        with lock:
            seen[0] += 1
            for g, v in s.items():
                secs.setdefault(g, []).append(v)
            say("깔때기", "%d/%d  %s" % (seen[0], n, c.name[:40]))
        return i, c, s

    # ── **깔때기만의 벽시계를 따로 잰다** — 결함 233 ────────────────
    #
    #   08-18 첫 실측이 «4.16배» 를 냈는데 **병렬로는 설명이 안 되는
    #   수치였다.** 후보가 둘이고 일꾼이 넷이면 **이론 최대가 2배**다.
    #   태울 것이 둘뿐이라 셋째·넷째 일꾼은 놀기 때문이다.
    #
    #   차액은 **프로세스 첫 실행 비용**이었다 — A 가 늘 먼저 도니까
    #   litellm 적재·TLS·DNS 를 **A 혼자 낸다**(깔때기 밖 37초 vs 2초).
    #   전체 초로 비교하면 그게 병렬 성과로 둔갑한다.
    #
    #   **깔때기 밖은 병렬화가 손댄 곳이 아니다.** 그러니 여기를 따로 잰다.
    t_f = _t.monotonic()
    with _cf.ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
        futs = [ex.submit(work, i, c) for i, c in enumerate(alive)]
        for f in _cf.as_completed(futs):
            i, c, _s = f.result()          # 예외는 그대로 위로 — run_pair 규약
            out[i] = c
    wall = round(_t.monotonic() - t_f, 1)

    done = [c for c in out if c is not None]
    unrun = [alive[i].name for i, c in enumerate(out) if c is None]
    return done, unrun, secs, wall


def run_disease(disease: str, config: str = DEMO_CONFIG, k: int = DISEASE_K,
                progress: Optional[Callable[[str, str], None]] = None,
                cache_path: str = "pubmed_cache.json",
                time_budget: float = TIME_BUDGET,
                workers: int = DISEASE_WORKERS,
                exit_: str = "표준", entry: str = "정방향") -> Dict[str, Any]:
    """병명 하나 → 후보 K개 → F0 → **통과분 전부**를 깔때기에.

    `run_pair` 와 같은 규약으로 실패한다 — **예외를 밖으로 안 던진다.**
    """
    import time as _t

    def say(stage, detail=""):
        if progress:
            try:
                progress(stage, detail)
            except Exception:
                pass

    t0 = _t.monotonic()
    base = {"ok": False, "질환": (disease or "").strip(), "후보": [],
            "요청": k, "생성": 0, "F0통과": 0, "태움": 0, "못태움": 0,
            "초": 0.0, "상한": time_budget, "warm": None,
            "못태운후보": [], "일꾼": max(1, int(workers)), "게이트초": {},
            "깔때기초": 0.0, "모델": {}, "역할배정": {},
            "비용": 0, "예산": budget.status(),
            "시각": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if not base["질환"]:
        return dict(base, 상태="입력오류", 메시지="병명을 입력해라")

    bad, why = safety.screen("", base["질환"], base["질환"])
    if bad:
        return dict(base, 상태="차단",
                    메시지="통제 물질 질의로 판단해 중단했다 — %s" % why)
    if not llm.available():
        return dict(base, 상태="LLM없음",
                    메시지="이 배포본에 LLM이 설정돼 있지 않다. "
                           "「판정 사례」 탭은 미리 구워 둔 결과라 그대로 볼 수 있다.")
    ok, _left = budget.take()
    if not ok:
        return dict(base, 상태="한도소진", 예산=budget.status(),
                    메시지="오늘 실행 한도를 다 썼다.")

    try:
        cache.configure(cache_path)
        cache.load()
        before = llm.spent()
        # **어느 모델이 실제로 답했나** — §3.2 감사 추적 · 결함 234
        #
        #   `FALLBACKS` 는 429 가 나면 **다른 모델로 넘어간다.** 그건
        #   비용 방어로는 옳은데, **같은 프롬프트에 다른 답**이 온다.
        #   08-18에 생성이 10개에서 **2개**로 떨어졌는데 입력·코드가
        #   같았다. 그때 화면이 «누가 답했나» 를 안 적어서 **모델 교체인지
        #   LLM 흔들림인지 가를 수가 없었다.**
        #
        #   판정을 흔들 수 있는 값은 **기록돼 있어야 한다.**
        call0 = len(llm.call_log())

        # ── ① 생성 — `gate_discover` 를 태운다 (직접 부르지 않는다) ──
        #    모듈을 직접 부르면 «배선됐다» 를 못 보인다. 결함 44·45 계열.
        say("발굴", "후보 %d개 요청" % k)
        st = RunState(query_title=base["질환"], settings=config, exit_=exit_ or "표준",
                      stamp=base["시각"], candidates=[],
                      config=_apply_exit(dict(gates.CONFIGS[config]), exit_))
        # **축1(입구)을 실어 보낸다** — 결함 273. `gate_discover` 가
        #   `profiles.ENTRY` 표에서 모듈을 고른다.
        st.discover = {"diseases": [base["질환"]], "k": k, "variant": "loose",
                       "entry": entry or "정방향"}
        base["입구"] = entry or "정방향"
        st = gates.gate_discover(st)
        cands = list(st.candidates)
        base["생성"] = len(cands)
        say("발굴", "%d개 생성" % len(cands))
        if not cands:
            budget.refund()
            return dict(base, 상태="생성없음", 초=round(_t.monotonic() - t0, 1),
                        메시지="후보가 하나도 안 나왔다. **«없다» 가 아니라 "
                               "«못 만들었다»** — 명세 §4 반증조건 1")

        # ── ② F0 — 여기서만 자른다. 문헌 0건이면 하드 기각 ──────────
        say("F0", "문헌 실재성 %d개" % len(cands))
        st.candidates = cands
        st = gates.REGISTRY["f0"](st)
        alive = [c for c in st.candidates if not c.killed]
        base["F0통과"] = len(alive)
        say("F0", "%d/%d 통과" % (len(alive), len(cands)))

        # ── ③ 정렬은 **표시용**이다. 아무것도 안 버린다 ─────────────
        #    F0 근거 수 내림차순 · 동수면 생성 순서(안정 정렬이 지킨다)
        #
        #    ⚠ **이 시점의 근거 수를 후보에 박아 둔다** — 결함 247.
        #      화면은 «정렬은 F0 근거 수» 라 적는데, 옆에 찍히는 «근거 N건」은
        #      **깔때기를 다 돈 뒤의 최종값**이다. 둘이 달라서 08-18 실측이
        #      «1건 · 0건 · 6건» 순으로 보였다 — **화면이 자기 정렬을
        #      설명 못 했다.** 명세(`78e44afa1b3b`)가 정렬 기준을 봉인했으므로
        #      **정렬은 안 바꾸고 그 값을 같이 보인다.**
        for c in alive:
            c.f0_ev = len(getattr(c, "evidence", []) or [])
        alive.sort(key=lambda c: -c.f0_ev)

        # ── ④ 깔때기 — **통과분 전부.** 시간 상한에 걸리면 그렇게 적는다 ──
        rest = [n for n in gates.ORDER if n != "f0"]
        done, unrun, secs, fwall = _funnel_many(alive, rest, config,
                                                base["시각"], t0, time_budget,
                                                say, workers, exit_)
        base["깔때기초"] = fwall     # **병렬화가 손댄 곳은 여기뿐이다**
        base["태움"] = len(done)
        base["못태움"] = len(unrun)
        base["못태운후보"] = unrun          # 개수만 적으면 어느 것인지 모른다
        base["일꾼"] = max(1, int(workers))
        # 게이트별 초 — «19초/후보» 가 어디로 가는지 화면이 스스로 말하게.
        # 합이 아니라 **중앙값**을 적는다: 후보 하나가 튀어도 안 가려진다.
        base["게이트초"] = {g: {"중앙": _median(v), "합": round(sum(v), 1),
                              "n": len(v)}
                          for g, v in sorted(secs.items())}
        if unrun:
            say("시간 상한", "%d개를 못 태웠다 — **기각이 아니다**: %s"
                % (len(unrun), ", ".join(unrun[:3])))
        cache.save()

        spent = llm.spent() - before
        if spent == 0:
            budget.refund()
        # Time-to-Refute — **`warm` 을 같이 낸다**(§4.1). 캐시가 데워져
        # 있으면 짧게 나오고, 그건 «빠르다» 가 아니라 «이미 받아 뒀다» 다.
        #
        # ⚠ 08-14 실측에서 **이 값이 화면에 안 찍혔다.** `time_to_refute(st)`
        #   에 넘긴 `st` 는 후보를 다른 RunState 로 옮긴 뒤라 비어 있었고,
        #   `except: pass` 가 그걸 **조용히 삼켰다.** 155.5초가 «느리다» 인지
        #   «캐시가 비었다» 인지 화면이 말을 못 했다 — **③ 상한 판정에
        #   직접 걸리는 값**이라 조용히 넘기면 안 된다.
        #
        #   `_cache_warm()` 을 직접 부른다. 실패하면 **`None` 을 남겨**
        #   화면이 «모른다» 를 적게 한다 — 0 으로 채우면 «캐시가 비었다»
        #   라는 거짓말이 된다(결함 89 계열).
        base["warm"] = gates._cache_warm()
        # **온도까지 같이 적는다** — `_served_since` 참조 (결함 236)
        base["모델"] = _served_since(call0)
        base["역할배정"] = llm.roles_in_use()
        # 09-29 · 후보마다 **일시 장애로 못 읽은 초록 수**(결함 380) — 합도 같이. 0 이 아니면 다시 돌리면 달라질 수 있다
        _tf = {c.name: _transient_skips(c) for c in done}
        return dict(base, ok=True, 상태="정상", 메시지="",
                    초=round(_t.monotonic() - t0, 1), 비용=spent,
                    예산=budget.status(), 일시실패=sum(_tf.values()),
                    후보=[{"이름": c.name, "약물": getattr(c, "drug", ""),
                          "판정": c.verdict, "신뢰도": c.confidence,
                          "사유": c.reason, "근거수": len(_evidence(c)),
                          "근거": _evidence(c), "게이트": _trail(c),
                          "F0근거수": getattr(c, "f0_ev", None),
                          "일시실패": _tf.get(c.name, 0),
                          "s1": getattr(c, "s1", None)} for c in done])
    except safety.Blocked as e:
        budget.refund()
        return dict(base, 상태="차단", 메시지=str(e))
    except Exception as e:
        return dict(base, 상태="오류", 예산=budget.status(),
                    초=round(_t.monotonic() - t0, 1),
                    메시지="%s: %s" % (type(e).__name__, str(e)[:200]))


def summary_line(r: Dict[str, Any]) -> str:
    """한 줄 요약. 상태가 정상이 아니면 그 사유를 보인다."""
    if r.get("상태") != "정상":
        return "· %s — %s" % (r.get("상태"), r.get("메시지", ""))
    n_sup = sum(1 for e in r["근거"] if e["방향"] == "지지")
    n_ref = sum(1 for e in r["근거"] if e["방향"] == "반박")
    # 면책과 AI 표기를 **판정 줄에 붙인다.** 화면 상단에만 두면
    # 스크린샷으로 떨어진다 — 결함 54가 그것이었고 §5 ⑤ 도 같은 문제다.
    return "· %s %s%%  — 지지 %d · 반박 %d · 새 LLM 호출 %d회\n\n%s\n%s" % (
        r["판정"], r["신뢰도"], n_sup, n_ref, r["비용"],
        SHORT_AI_NOTICE, SHORT_DISCLAIMER)
