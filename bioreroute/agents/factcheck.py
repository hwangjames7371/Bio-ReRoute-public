# -*- coding: utf-8 -*-
"""L2 팩트체커 — 초록 한 건을 지지/반박/무관으로 판정한다.

설계 판단 세 가지 (모두 신뢰도를 위해 LLM의 재량을 좁히는 방향이다)

  ① LLM에게 숫자를 뽑게 하지 않는다.
     LLM은 수치 보정이 나쁘다. LLM은 범주형 사실만 추출하고(방향·규모·결정성),
     가중치는 아래 WEIGHT 표가 결정론적으로 매긴다. 감사 가능하고, 나중에
     Platt 보정을 걸 지점이 명확해진다.

  ② 연구 유형은 PubMed 색인을 우선한다.
     PublicationType은 사람이 붙인 MeSH 메타데이터다. LLM 추론보다 낫다.
     색인이 없을 때만 LLM 추정으로 보완하고, 그 사실을 기록한다.

  ③ 인용문을 초록에서 실제로 검증한다.
     LLM이 근거 문장을 지어내면 무관으로 강등한다. 우리가 파는 반증 원칙을
     우리 에이전트 자신에게도 적용하는 것이다.

추가로, 철회 논문(Retracted Publication)은 가중치 0으로 죽인다.
철회된 근거로 판정하는 반증 시스템은 자기모순이다.
"""

import json
import re
from typing import Any, Dict, List, Optional

from ..io import llm

# ─────────────────────────────────────────────────────────────
# 가중치 표 — 근거의 강도는 연구 설계가 결정한다
#   기준점: 대규모 결정적 RCT = 3.0 (로그오즈), 소규모 파일럿 RCT = 1.2
#   이 두 지점은 W1에서 사람이 손으로 매긴 값과 일치하도록 잡았다.
# ─────────────────────────────────────────────────────────────
WEIGHT_BASE = {
    "meta": 2.4,           # 메타분석·체계적 고찰
    "rct": 2.0,            # 무작위배정 임상시험
    "trial": 1.2,          # 무작위배정 아닌 임상시험
    "observational": 0.6,  # 관찰연구 — 교란 위험
    "review": 0.5,         # 서술적 고찰
    "in_vitro": 0.2,       # 시험관·전임상
    "case": 0.2,           # 증례
    "other": 0.3,
}
SIZE_MULT = {"large": 1.0, "small": 0.6, "unknown": 0.8}
# GRADE 확실성. 코크란은 확실성을 표현으로 구분한다 —
#   "reduces"(고확실성) / "probably reduces"(중) / "may reduce"(저) / "uncertain"(매우 저).
# 이걸 무시하면 "may slightly reduce"가 확정 결과와 같은 무게를 갖는다.
# 실제로 플루복사민이 그렇게 99%까지 올라갔다.
CERTAINTY_MULT = {"high": 1.0, "moderate": 0.8, "low": 0.5, "very_low": 0.3}
CONF_MULT = {"high": 1.0, "medium": 0.7, "low": 0.4}
DECISIVE_MULT = 1.5        # 사전 등록된 1차 평가변수를 결정적으로 만족/기각
# ── 동료심사 상태 (09-01) — **미공개 근거를 논문과 같이 세지 않는다** ──
#
#   동료심사 · 재현 가능성 · **넣는 사람의 이해관계**가 다르다.
#   `peer_reviewed` 가 기본값이라 **기존 동작은 바뀌지 않는다.**
#
#   ⚠ **이름을 `SOURCE_MULT` 라고 지었다가 고쳤다** — `Evidence.source`
#     가 이미 있고 그건 **`curated|llm|pubmed`**(스텁 여부 추적)이며
#     `scoring.py:140` 이 그 값을 읽는다. 같은 파일 주석이 이미
#     *"`source` 와 다르다"* 며 `stage` 를 따로 둔 이력이 있는데
#     **내가 같은 자리에 또 충돌을 만들 뻔했다.**
#
#   ⚠ 이 값들은 **판정을 뒤집는 규칙이 아니라 무게**다. 미공개 근거
#     하나로 결론이 바뀌는지는 `bench/sourcesens` 가 따로 보여준다.
REVIEW_MULT = {
    "peer_reviewed": 1.0,   # 동료심사를 통과한 문헌 (기본)
    "preprint": 0.7,        # 심사 전 — 내용은 있으나 검증이 없다
    "internal": 0.5,        # 미공개 사내·랩실 결과 — 재현 불가
}
DECISIVE_OK = {"rct", "meta"}   # 결정성 배수는 확증 설계에만 준다

SYSTEM = "당신은 약물 재창출 가설을 검증하는 회의주의 심사자다. 근거가 없으면 없다고 답한다."

TEMPLATE = """가설: "{drug}는 {disease}에 임상적 효능이 있다"

아래 초록이 이 가설을 지지하는지, 반박하는지, 무관한지 판정하라.

규칙
1. 임상적 효능(efficacy)에 대한 증거만 본다. 기전·안전성·역학만 다룬 초록은 무관이다.
2. 다른 질환에 대한 효능은 무관이다. 반드시 {disease}에 대한 것이어야 한다.
3. quote는 초록에 있는 문장을 그대로 복사한다. 한 글자도 바꾸지 마라. 지어내면 안 된다.
4. 확실하지 않으면 neutral로 답하고 confidence를 low로 둔다. 과신하지 마라.
5. decisive는 사전에 정한 1차 평가변수를 명확히 만족했거나 명확히 기각한 경우에만 true다.

[초록 · PMID {pmid}]
{title}
{abstract}

JSON만 출력하라. 다른 말은 붙이지 마라.
{{"direction": "support|refute|neutral",
 "study_type": "meta|rct|trial|observational|review|in_vitro|case|other",
 "size": "large|small|unknown",
 "decisive": true or false,
 "quote": "초록에서 그대로 복사한 한 문장",
 "population": "대상군 (없으면 빈 문자열)",
 "dose": "용량 (없으면 빈 문자열)",
 "timing": "투여 시점 (없으면 빈 문자열)",
 "confidence": "high|medium|low"}}"""

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", (s or "")).strip().lower()


def _alnum(s: str) -> str:
    """영숫자만 남긴다. 구두점·공백 차이를 없애 비교한다."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


# 근거가 그 약을 지목하지 않을 때의 감쇠. 0으로 죽이지 않는 이유는 아래.
INDIRECT_MULT = 0.5

# 인용문이 결과를 담지 않을 때의 감쇠.
NO_RESULT_MULT = 0.4

# 거울상체·유도체 접두어. 이게 붙으면 **다른 화합물**이다.
#
#   실측 사고: `pramipexole / ALS` 가 EMPOWER 3상 초록을 근거로 잡았는데
#   그 시험의 약은 **dexpramipexole**이었다. 부분문자열이라 통과한 것이다.
#   프라미펙솔은 도파민 작용제(파킨슨), 덱스프라미펙솔은 R(+)-거울상체로
#   도파민 활성이 없고 ALS용으로 따로 개발됐다. **완전히 다른 약이다.**
#
#   같은 함정이 흔하다 — levocetirizine/cetirizine, esomeprazole/omeprazole,
#   dexlansoprazole/lansoprazole, levofloxacin/ofloxacin.
#   **벤치마크에 dexlansoprazole이 실제로 들어 있다.**
_CHIRAL = ("dex", "levo", "lev", "es", "ar", "dl", "rac")


def names_drug(drug: str, *texts) -> bool:
    """이 근거가 **그 약을 지목하는가.**

    실측 사고: `interferon beta-1a / Crohn` 이 **natalizumab** 메타분석을
    근거로 유망 94%를 받았다. 인용문이 "Pooled data ... suggest that
    natalizumab ..." 였는데 인터페론은 한 번도 안 나온다.

    프롬프트 규칙 2는 "다른 **질환**은 무관"만 막았고 **다른 약물**에 대한
    규칙이 없었다. 그리고 규칙을 넣어도 그건 LLM 판단이다 —
    **LLM 판단만 믿지 않는 것이 이 프로젝트의 전제다.**

    제목이나 인용문 중 한 곳에라도 약 이름(또는 낱말 조각)이 있으면 통과.
    둘 다 없으면 그 약을 직접 지목한 근거가 아니다.
    """
    # **약 이름을 모르는지부터 묻는다.** 순서가 반대면 없는 정보로 벌점을 준다.
    #   실측: 본문이 한국어뿐이라 hay가 비어 곧바로 False가 나왔다.
    #   모르는 것과 불일치는 다르다 — 모를 때는 감쇠하지 않는다.
    d = (drug or "").lower().strip()
    if not d:
        return True
    hay = _alnum(" ".join(t or "" for t in texts))
    if not hay:
        return False
    cands = {_alnum(d)}
    for w in re.split(r"[^a-z0-9]+", d):
        if len(w) > 4 and w not in ("acid", "sodium", "hydrochloride", "beta"):
            cands.add(_alnum(w))
    # 어간 일치도 허용한다 — erlotinib / erlotinib hydrochloride
    return any(c and (_occurs(c, hay) or (len(c) > 7 and _occurs(c[:7], hay)))
               for c in cands)


def _occurs(needle: str, hay: str) -> bool:
    """부분문자열이되 **거울상체 접두어에 붙은 것은 세지 않는다.**

    "dexpramipexole" 안의 "pramipexole" 은 프라미펙솔의 언급이 아니다.
    모든 출현 위치를 확인해 접두어가 안 붙은 것이 하나라도 있어야 인정한다 —
    한 초록이 두 약을 같이 다룰 수 있으므로 첫 출현만 보면 안 된다.
    """
    if not needle:
        return False
    i = hay.find(needle)
    while i >= 0:
        if not any(i >= len(p) and hay[i - len(p):i] == p for p in _CHIRAL):
            return True
        i = hay.find(needle, i + 1)
    return False


_NUM = re.compile(r"-?\d+(?:\.\d+)?")


# 인용문이 **결과를 담고 있는가.**
#
#   실측 사고: 아래 세 문장이 각각 w=3.0 이상으로 채택됐다.
#     "The pain was measured using the WOMAC pain subscale score"   ← 측정 방법
#     "Among the study group, 402 and 126 patients received ..."     ← 환자 배정
#     "Our trial can inform the design of future research"           ← 향후 계획
#   전부 결과가 아니다. 그런데 인용 검증은 통과했다 —
#   **실재하는 문장인지만 봤지 판정을 뒷받침하는지는 안 봤다.**
#
#   숫자 유무로는 못 가른다. "402명이 받았다"에도 숫자가 있다.
#   결과를 만드는 것은 **비교·평가 표현**이다.
_RESULT = re.compile(
    r"significant|superior|inferior|greater|better|worse|shorter|longer"
    r"|higher|lower|improv|reduc|increas|decreas|declin|prolong"
    r"|effective|efficac|benefit|response rate|remission|surviv"
    r"|no difference|did not|failed to|lack of|futil|ineffective"
    r"|no longer|not recommend|versus|compared with|compared to|vs\.?\s"
    r"|\bp\s*[=<>]|\bhr\b|\bor\b\s*[=(]|\brr\b|95%\s*ci|odds ratio"
    r"|hazard ratio|risk ratio|mean difference|\bsmd\b|\bnnt\b", re.I)

# 결과가 아니라 **연구를 서술하는** 표현. 위와 겹치면 이쪽을 우선한다.
_DESIGN_ONLY = re.compile(
    r"was measured using|were measured using|measured by|assessed using"
    r"|(was|were|is|are) defined|defined as|were enrolled|were randomi"
    r"|patients received|can inform|will be|aim(ed)? to|objective of"
    r"|primary outcome was|is (a|an) (new|novel)|is increasingly"
    r"|has been used|study was"
    # 평가변수의 **이름**만 적힌 줄. 등록부 본문에 특히 흔하다 —
    #   "Progression-free survival (PFS) distributions for the Phase II
    #   participants" 는 무엇을 쟀는지만 말하지 얼마가 나왔는지는 없다.
    r"|distributions? for|scores? for|rates? for|measure(s|d)? by"
    r"|outcome measure|endpoint (was|is)|assessment of", re.I)


def has_result(quote: str, structured: bool = False) -> bool:
    """인용문이 결과를 진술하는가. 아니면 연구 서술일 뿐인가.

    판정을 **뒷받침하지 않는 인용**을 걸러낸다. 인용 검증(지어냈는가)과는
    다른 문제다 — 실재하는 문장이어도 결과가 없으면 근거가 아니다.

    등록부 인용은 문장이 아니라 표의 한 줄이다. "Doxycycline -0.24 |
    Placebo -0.20" 에는 비교 표현이 없지만 **그 자체가 비교**다.
    구조화 문서에서는 수치 두 개 이상이면 결과로 본다.
    """
    q = quote or ""
    if structured:
        # 표의 값 줄. 군이 둘 이상이어야 비교가 성립한다.
        if len(_NUM.findall(q)) >= 2:
            return True
    if not _RESULT.search(q):
        return False
    # 결과 표현이 있어도 문장 전체가 설계 서술이면 결과가 아니다.
    #   "Overall survival was defined from ..." 에는 'surviv'가 있지만
    #   무엇이 나왔는지는 없다. 수치가 함께 있어야 결과로 본다.
    if _DESIGN_ONLY.search(q) and not _NUM.search(q):
        return False
    return True



def _nums(s: str):
    """문자열에서 수치를 뽑는다. 표에서 내용을 지고 있는 것은 숫자다."""
    return [x.lstrip("-") for x in _NUM.findall(s or "")]


OUTCOME_MARK = "[1차 평가변수 결과]"


def _in_outcome(quote: str, abstract: str) -> bool:
    """인용이 **1차 평가변수 결과** 구획에서 나왔는가.

    처음엔 반대로 짰다 — "상태 줄에서 왔으면 막는다". 그런데 인용이 두 줄에
    걸치면 어느 한 줄의 부분문자열도 아니게 되어 검사를 그냥 빠져나간다.
    금지 목록은 언제나 이렇게 샌다.

    그래서 뒤집었다. **허용할 구획을 명시하고 나머지는 전부 막는다.**
    운영상 멈춘 시험에서 살아남을 근거는 보고된 결과 수치뿐이다.
    """
    q = _norm(quote)
    if not q:
        return False
    body = abstract or ""
    i = body.find(OUTCOME_MARK)
    if i < 0:
        return False
    return q in _norm(body[i + len(OUTCOME_MARK):])


def verify_quote(quote: str, abstract: str, min_len: int = 25,
                 structured: bool = False) -> Dict[str, Any]:
    """인용문이 초록에 실제로 있는가.

    LLM이 문장을 약간 다듬는 경우가 흔하므로 완전일치만 요구하면 위양성이 많다.
    공백 정규화 후 부분문자열 일치를 보고, 실패하면 앞 절반으로 한 번 더 본다.
    그래도 없으면 지어낸 것으로 간주한다.

    최소 길이가 필요한 이유는 짧은 문자열이 **우연히** 맞을 수 있어서다.
    그런데 등록부 본문은 산문이 아니라 우리가 CT.gov JSON에서 직접 조립한
    구조화된 표다. 핵심 문구가 원래 짧다 — "Terminated for futility"는 23자다.

      실측 사고: 이 규칙 때문에 등록부 근거가 **전부** 무관으로 강등됐다.
      출판 편향 천장을 뚫으려고 만든 게이트를, 산문용으로 맞춘 검증기가
      통째로 무력화하고 있었다. B6가 B5와 같아진 진짜 이유다.

    구조화 문서에는 문턱을 낮추되 **완전일치만** 인정한다. 우리가 만든
    짧고 통제된 문서에서의 완전일치는 우연이 아니다.
    """
    q, a = _norm(quote), _norm(abstract)
    if not q:
        return {"ok": False, "how": "빈 인용"}
    if structured:
        if len(q) < 12:
            return {"ok": False, "how": "인용이 너무 짧아 검증 불가(%d자)" % len(q)}
        if q in a:
            return {"ok": True, "how": "완전일치(등록부)", "확인": q, "미확인": ""}
        # 구두점·공백 차이는 위조가 아니다. "±2.1"과 "± 2.1"은 같은 값이다.
        if _alnum(q) and _alnum(q) in _alnum(a):
            return {"ok": True, "how": "완전일치(등록부·구두점 무시)",
                    "확인": q, "미확인": ""}
        # 표를 문장으로 옮기면 순서가 바뀌고 연결어가 낀다. 그건 정상이다.
        #
        #   실측 사고: 등록부 시험 25건을 읽고 **채택 0건**이 나왔다.
        #   완전일치만 인정했더니 "Erlotinib 11.5 vs Placebo 13.2"처럼
        #   LLM이 표를 문장으로 옮긴 것이 전부 '지어냄'으로 강등됐다.
        #   위조를 막으려던 검증이 정상 근거를 몰살한 것이다.
        #
        #   표에서 **내용은 숫자다.** 숫자를 지어내면 본문에 없다.
        #   두 개 이상의 수치가 전부 본문에 있고 낱말도 겹치면 실재로 본다.
        #   substring보다 오히려 위조하기 어렵다 — 우연히 다 맞을 수 없다.
        qn, an = _nums(quote), set(_nums(abstract))
        if len(qn) >= 2 and all(n in an for n in qn):
            qw = [w for w in re.findall(r"[a-z]{4,}", q)]
            if not qw or sum(1 for w in qw if w in a) / len(qw) >= 0.6:
                # **이건 인용이 아니라 재서술이다.** 표를 문장으로 옮긴
                # 것이므로 원문에 그 문장이 없다 — 화면이 «인용 원문»
                # 이라 부르면 안 된다. 확인 구간을 비워 그걸 알린다.
                return {"ok": True, "how": "수치 대조(%d개 일치)" % len(qn),
                        "확인": "", "미확인": quote, "재서술": True}
        return {"ok": False, "how": "등록부 본문에 없는 문장(지어냄)"}
    if len(q) < min_len:
        return {"ok": False, "how": "인용이 너무 짧아 검증 불가(%d자)" % len(q)}
    if q in a:
        return {"ok": True, "how": "완전일치", "확인": q, "미확인": ""}
    half = q[: max(min_len, len(q) // 2)]
    if half in a:
        # ── 08-13 (결함 160) ─────────────────────────────────────
        #   여기서 `ok=True` 를 내면 **화면이 문장 전체를 「인용 원문」
        #   이라는 제목 아래 찍는다.** 그런데 뒤 절반은 초록에 없다.
        #
        #   현직 연구자 5명이 *"AI 가 알려준 논문이 실제로 없었던 적이
        #   있어서 지금은 참고용으로만 쓴다"* 고 했다(`인터뷰기록.md #2`).
        #   **그들이 겪은 바로 그 실패의 축소판이 우리 화면에 있었다.**
        #
        #   확인된 구간을 **길이 기준으로 최대한 늘려** 돌려준다. 화면은
        #   확인 구간만 인용으로 쓰고 나머지는 «미확인» 으로 갈라 적는다.
        #   판정·가중치는 **건드리지 않는다** — 표시만 정직해진다
        #   (`CLAUDE.md §3-2`: 벤치마크 값이 바뀌면 안 된다).
        lo, hi = len(half), len(q)
        while lo < hi:                       # 확인 가능한 최장 접두를 찾는다
            mid = (lo + hi + 1) // 2
            if q[:mid] in a:
                lo = mid
            else:
                hi = mid - 1
        return {"ok": True, "how": "부분일치",
                "확인": q[:lo], "미확인": q[lo:]}
    return {"ok": False, "how": "초록에 없는 문장(지어냄)"}


# GRADE 저확실성 표현의 결정론적 탐지. LLM 판단만 믿지 않고 원문에서도 확인한다.
_GRADE_LOW = re.compile(
    r"\b(may|might)\s+(slightly\s+)?(reduce|increase|improve|decrease|result|lead|have)"
    r"|low[- ]certainty|very low[- ]certainty|low[- ]quality evidence"
    r"|uncertain|insufficient evidence|evidence is (very )?uncertain", re.I)
_GRADE_MOD = re.compile(r"\bprobably\b|moderate[- ]certainty", re.I)
# 코크란 GRADE 고확실성 표현만 넣는다. "little or no difference"와 "results in"은
# GRADE 서술 규약상 고확실성을 뜻하는 정형구다.
#
# 주의 — "did not improve", "no significant effect" 같은 표현은 **넣지 않았다.**
#   그건 확실성 등급이 아니라 결과 서술이고, 부정 결과는 원래 그렇게 쓰인다.
#   고확실성으로 올리면 반박 근거만 조직적으로 부풀려 기각 쪽으로 기운다.
#   완화 표현 감쇠(긍정 결론에 더 자주 붙음)와 반대 방향의 같은 편향이다.
#   탐지에 실패하면 기본값이 high(배수 1.0)이므로 넣지 않아도 손해는 없다.
_GRADE_HIGH = re.compile(
    r"little or no difference|high[- ]certainty"
    r"|results in (a |an )?(large |slight |small )?(reduction|increase|decrease)", re.I)


def grade_from_text(text: str) -> Optional[str]:
    """GRADE 확실성 수준을 읽는다. 못 읽으면 None.

    주의: 반드시 **인용된 그 문장**에만 적용한다. GRADE는 결과(outcome)마다
    따로 매기는 등급이므로 초록 전체를 훑으면 다른 결과의 등급이 섞인다.
    """
    if not text:
        return None
    if _GRADE_HIGH.search(text):     # 단정 표현이 먼저 — 완화 표현보다 우선
        return "high"
    if _GRADE_LOW.search(text):
        return "low"
    if _GRADE_MOD.search(text):
        return "moderate"
    return None


def weight_for(study_type: str, size: str, decisive: bool, confidence: str,
               certainty: str = "high",
               review: str = "peer_reviewed") -> float:
    """근거 한 건의 무게.

    ## `review` — 09-01 추가 · **미공개 근거를 받되 같은 무게로 받지 않는다**

    사용자가 랩실·사내의 **미발표 결과**를 근거로 넣고 싶어 한다.
    넣는 것 자체는 쉽다. **어려운 건 무게다.**

    미공개 근거는 **동료심사가 없고 재현도 안 되며, 무엇보다 넣는
    사람이 원하는 결론 쪽으로 기울어 있을 가능성이 높다.** 논문과
    같은 무게로 받으면 **이 시스템의 존재 이유를 스스로 깬다** —
    우리는 «그럴듯하지만 틀린 후보를 거르는» 도구다.

    ⚠ **기본값이 `peer_reviewed`(×1.0) 이므로 기존 동작은 안 바뀐다.**
    """
    w = WEIGHT_BASE.get(study_type, WEIGHT_BASE["other"])
    w *= SIZE_MULT.get(size, 0.8)
    if decisive and study_type in DECISIVE_OK:
        w *= DECISIVE_MULT
    w *= CONF_MULT.get(confidence, 0.7)
    w *= CERTAINTY_MULT.get(certainty, 1.0)
    w *= REVIEW_MULT.get(review, 1.0)
    return round(w, 3)


def classify(drug: str, disease: str, rec: Dict[str, Any]) -> Dict[str, Any]:
    """초록 한 건 판정. 실패해도 예외를 던지지 않고 skip 사유를 돌려준다."""
    pmid = rec.get("pmid", "")
    out = {"pmid": pmid, "direction": "neutral", "weight": 0.0,
           "kept": False, "skip": None, "provenance": None,
           "study_type": rec.get("study_type"), "study_type_src": "pubmed",
           "quote": "", "quote_check": None, "pico": {},
           "retracted": False, "year": rec.get("year"),
           "title": rec.get("title", ""), "journal": rec.get("journal", "")}

    if pmid and pmid in EXCLUDE_PMID:
        out["skip"] = "라벨 출처 시험의 논문(PMID 색인) — 근거에서 제외"
        return out

    # ── 철회 논문은 근거로 쓰지 않는다 ──────────────────────
    pts = rec.get("pubtypes") or []
    if any("Retracted Publication" == p for p in pts):
        out.update(retracted=True, skip="철회 논문 — 근거에서 제외", weight=0.0)
        return out
    if rec.get("error"):
        out["skip"] = "초록 취득 실패: %s" % rec["error"]
        return out
    if not (rec.get("abstract") or "").strip():
        out["skip"] = "초록 없음 — 판정 불가"
        return out

    prompt = TEMPLATE.format(drug=drug, disease=disease, pmid=pmid,
                             title=rec.get("title", ""), abstract=rec["abstract"])
    r = llm.complete(prompt, system=SYSTEM, as_json=True,
                     model=llm.model_for("factcheck"),   # §3.2 고성능
                     purpose="factcheck")   # 계량 — 인용 검증
    out["provenance"] = r.get("provenance")
    if not r.get("ok") or not isinstance(r.get("data"), dict):
        out["skip"] = "LLM 실패: %s" % (r.get("error") or "형식 오류")
        return out

    d = r["data"]
    direction = str(d.get("direction", "neutral")).lower()
    if direction not in ("support", "refute", "neutral"):
        direction = "neutral"
    out["quote"] = str(d.get("quote", ""))
    out["pico"] = {k: str(d.get(k, "")) for k in ("population", "dose", "timing")}

    # ── 연구 유형: PubMed 색인 우선, 없으면 LLM 추정 ──────────
    if not out["study_type"]:
        out["study_type"] = str(d.get("study_type", "other")).lower()
        out["study_type_src"] = "llm"
    llm_type = str(d.get("study_type", "")).lower()
    out["type_conflict"] = bool(out["study_type_src"] == "pubmed" and
                                llm_type and llm_type != out["study_type"])

    if direction == "neutral":
        out.update(direction="neutral", skip="무관 — 효능 증거 아님")
        return out

    # ── 인용문 검증: 지어냈으면 강등 ─────────────────────────
    chk = verify_quote(out["quote"], rec["abstract"],
                       structured=(rec.get("source") == "ctgov"))
    out["quote_check"] = chk
    if not chk["ok"]:
        out.update(direction="neutral", weight=0.0,
                   skip="인용 검증 실패(%s) → 무관 강등" % chk["how"])
        return out

    conf = str(d.get("confidence", "medium")).lower()
    size = str(d.get("size", "unknown")).lower()
    decisive = bool(d.get("decisive", False))
    # 운영상 중단은 효능 반증이 아니다 (배치 경로와 같은 규칙)
    if (direction == "refute" and rec.get("stop_reason") == "operational"
            and not _in_outcome(out["quote"], rec["abstract"])):
        out.update(direction="neutral", weight=0.0, kept=False,
                   skip="운영상 중단(등록 부진·자금 등) — 효능 반증 아님 → 무관 강등")
        out["stop_reason_guard"] = True
        return out
    # ⚠ 09-01 · **`review` 를 레코드에서 읽는다.** 안 읽으면 `REVIEW_MULT`
    #    가 «아무도 안 부르는 죽은 인자» 가 된다 — 만들어 놓고 배선을
    #    안 한 것이고, `unwired` 는 모듈 단위라 그걸 못 잡는다.
    #    PubMed 레코드에는 이 칸이 없으므로 **기본 `peer_reviewed`**,
    #    미공개 근거를 주입할 때만 `internal` 등이 붙는다.
    rv = rec.get("review", "peer_reviewed")
    out.update(direction=direction, kept=True,
               weight=weight_for(out["study_type"], size, decisive, conf,
                                 review=rv),
               size=size, decisive=decisive, confidence=conf, review=rv)
    return out


# ═══════════════════════════════════════════════════════════
# 일괄 판정 — 초록 N건을 호출 1회로 처리한다
#
#   초록마다 호출하면 후보 4개에 32회가 나간다. 무료 티어 일일 한도(20회)를
#   한 번에 넘긴다. 묶으면 4회로 끝난다.
#
#   묶을 때의 위험은 모델이 초록을 뒤섞는 것이다. 그런데 인용 검증이 이미
#   그걸 잡는다 — 판정에 붙은 인용문이 해당 초록 안에 없으면 강등된다.
#   다른 초록의 문장을 가져오면 교차오염으로 기록한다.
# ═══════════════════════════════════════════════════════════
BATCH_HEAD = """가설: "{drug}는 {disease}에 임상적 효능이 있다"

아래 초록 {n}건을 **각각 독립적으로** 지지/반박/무관 판정하라.

규칙
1. 임상적 효능(efficacy)에 대한 증거만 본다. 기전·안전성·역학만 다룬 초록은 무관이다.
2. 다른 질환에 대한 효능은 무관이다. 반드시 {disease}에 대한 것이어야 한다.
2b. **다른 약물에 대한 효능도 무관이다.** 반드시 {drug}(또는 그 상품명·동의어)를
   투여한 결과여야 한다. 같은 질환의 다른 치료제를 다룬 초록은 neutral이다.
   같은 계열 약물(class)의 결과도 {drug} 자체의 근거가 아니므로 neutral로 둔다.
3. quote는 **그 초록 안에 있는** 문장을 그대로 복사한다. 다른 초록의 문장을 쓰면 안 된다.
   한 글자도 바꾸지 마라. 지어내면 안 된다.
4. 확실하지 않으면 neutral로 답하고 confidence를 low로 둔다. 과신하지 마라.
5. decisive는 사전에 정한 1차 평가변수를 명확히 만족했거나 명확히 기각한 경우에만 true다.
6. certainty는 GRADE 확실성이다. 저자가 "reduces"라고 단정하면 high,
   "probably reduces"면 moderate, "may (slightly) reduce"면 low,
   "uncertain"·"insufficient evidence"면 very_low 로 답한다.
"""

BATCH_TAIL = """
JSON 배열만 출력하라. 원소 {n}개, 초록과 같은 순서. 다른 말은 붙이지 마라.
[{{"pmid": "위에 적힌 PMID",
  "direction": "support|refute|neutral",
  "study_type": "meta|rct|trial|observational|review|in_vitro|case|other",
  "size": "large|small|unknown",
  "decisive": true or false,
  "quote": "그 초록에서 그대로 복사한 한 문장",
  "population": "", "dose": "", "timing": "",
  "certainty": "high|moderate|low|very_low",
  "confidence": "high|medium|low"}}]"""


def _blank(rec, skip):
    return {"pmid": rec.get("pmid", ""), "direction": "neutral", "weight": 0.0,
            "kept": False, "skip": skip, "provenance": None,
            "study_type": rec.get("study_type"), "study_type_src": "pubmed",
            "quote": "", "quote_check": None, "pico": {}, "retracted": False,
            "year": rec.get("year"), "title": rec.get("title", ""),
            "journal": rec.get("journal", ""), "nct": rec.get("nct") or [],
            # 출처를 판정에 실어 보내지 않으면 저장된 상태만 보고
            # 논문 근거인지 등록부 근거인지 구분할 수 없다. 감사 추적이 끊긴다.
            "source": rec.get("source") or "pubmed",
            "stop_reason": rec.get("stop_reason")}


# 근거로 쓰면 안 되는 시험. 벤치마크에서 라벨의 출처가 된 시험이 여기 들어온다.
#   등록부에서만 막고 논문에서 통과시키면 방어가 아니라 구멍이다.
#   출처가 무엇이든 같은 시험이면 같게 막아야 한다.
EXCLUDE_NCT = set()

# 그 시험의 **논문 PMID**. NCT 번호만으로는 못 막는다 —
#   초록에 등록번호를 안 쓴 논문이 흔하고, 그러면 라벨 출처 시험의 결과
#   논문이 그대로 근거가 된다. 실측에서 그런 누출이 2건 확인됐다.
#   gates.set_exclude() 가 PubMed [si] 색인으로 채운다.
EXCLUDE_PMID = set()


def classify_batch(drug: str, disease: str, recs: List[Dict[str, Any]],
                   role: str = "factcheck") -> List[Dict[str, Any]]:
    """초록 여러 건을 호출 1회로 판정. 반환 순서는 입력 순서와 같다.

    `role` 은 **모델 배정에만** 쓴다(§3.2). 기본값이 `factcheck` 이라
    **안 넘기면 지금까지와 완전히 같은 동작**이다.

    회의주의자가 이 함수를 재사용한다. 그동안 그 호출이 `factcheck` 로
    청구돼서 **`model_for("skeptic")` 을 바꿔도 아무 일이 안 났다**
    (결함 232). 둘 다 `strong` 이라 티가 안 났을 뿐이다.
    """
    out = {}
    live = []
    for rec in recs:
        pmid = rec.get("pmid", "")
        hit = [n for n in (rec.get("nct") or []) if n in EXCLUDE_NCT]
        if hit:
            # 초록에 라벨 출처 시험의 NCT가 박혀 있다 = 그 시험의 보고서다.
            out[pmid] = _blank(rec, "라벨 출처 시험(%s) — 근거에서 제외" % hit[0])
            continue
        if pmid and pmid in EXCLUDE_PMID:
            # 초록에 NCT는 없지만 PubMed가 그 시험의 논문으로 색인한 것.
            #   여기를 막지 않으면 "답안지를 읽고 기각"하게 된다.
            out[pmid] = _blank(rec, "라벨 출처 시험의 논문(PMID 색인) — 근거에서 제외")
            continue
        if any(p == "Retracted Publication" for p in (rec.get("pubtypes") or [])):
            r = _blank(rec, "철회 논문 — 근거에서 제외")
            r["retracted"] = True
            out[pmid] = r
        elif rec.get("error"):
            out[pmid] = _blank(rec, "초록 취득 실패: %s" % rec["error"])
        elif not (rec.get("abstract") or "").strip():
            out[pmid] = _blank(rec, "초록 없음 — 판정 불가")
        else:
            live.append(rec)

    if not live:
        return [out[r.get("pmid", "")] for r in recs]

    body = "\n\n".join(
        "[초록 %d · PMID %s]\n%s\n%s" % (i + 1, r["pmid"], r.get("title", ""), r["abstract"])
        for i, r in enumerate(live))
    prompt = (BATCH_HEAD.format(drug=drug, disease=disease, n=len(live))
              + "\n" + body + "\n" + BATCH_TAIL.format(n=len(live)))

    res = llm.complete(prompt, system=SYSTEM, as_json=True,
                       model=llm.model_for(role),   # §3.2 — 호출자가 정한 역할
                       purpose=role or "skeptic")   # 계량
    data = res.get("data")
    if isinstance(data, dict):                     # 배열을 감싸 보내는 모델 대응
        for v in data.values():
            if isinstance(v, list):
                data = v
                break
    if not res.get("ok") or not isinstance(data, list):
        why = "LLM 실패: %s" % (res.get("error") or "배열 형식 아님")
        for r in live:
            out[r["pmid"]] = _blank(r, why)
            out[r["pmid"]]["provenance"] = res.get("provenance")
        return [out[r.get("pmid", "")] for r in recs]

    # PMID로 맞춘다. 모델이 PMID를 빠뜨리면 순서로 보정한다.
    by_pmid = {}
    for i, d in enumerate(data):
        if not isinstance(d, dict):
            continue
        pid = str(d.get("pmid", "")).strip()
        if pid not in {r["pmid"] for r in live}:
            pid = live[i]["pmid"] if i < len(live) else ""
        if pid:
            by_pmid[pid] = d

    others = {r["pmid"]: r["abstract"] for r in live}
    for rec in live:
        pmid = rec["pmid"]
        r = _blank(rec, None)
        r["provenance"] = res.get("provenance")
        d = by_pmid.get(pmid)
        if d is None:
            r["skip"] = "응답 누락 — 판정 없음"
            out[pmid] = r
            continue

        direction = str(d.get("direction", "neutral")).lower()
        if direction not in ("support", "refute", "neutral"):
            direction = "neutral"
        r["quote"] = str(d.get("quote", ""))
        r["pico"] = {k: str(d.get(k, "")) for k in ("population", "dose", "timing")}

        if not r["study_type"]:
            r["study_type"] = str(d.get("study_type", "other")).lower()
            r["study_type_src"] = "llm"
        lt = str(d.get("study_type", "")).lower()
        r["type_conflict"] = bool(r["study_type_src"] == "pubmed" and lt
                                  and lt != r["study_type"])

        if direction == "neutral":
            r["skip"] = "무관 — 효능 증거 아님"
            out[pmid] = r
            continue

        structured = rec.get("source") == "ctgov"
        chk = verify_quote(r["quote"], rec["abstract"], structured=structured)
        r["quote_check"] = chk
        if not chk["ok"]:
            # 다른 초록에서 가져왔는지 확인 — 묶음 처리 고유의 실패 양상
            src = next((p for p, a in others.items()
                        if p != pmid and verify_quote(r["quote"], a)["ok"]), None)
            r["skip"] = ("인용 교차오염(PMID %s의 문장) → 무관 강등" % src if src
                         else "인용 검증 실패(%s) → 무관 강등" % chk["how"])
            r["cross_contaminated"] = bool(src)
            out[pmid] = r
            continue

        conf = str(d.get("confidence", "medium")).lower()
        size = str(d.get("size", "unknown")).lower()
        dec = bool(d.get("decisive", False))

        # ── 운영상 중단을 효능 반증으로 읽지 못하게 막는다 ──────
        #
        #   **자금이 끊겨 멈춘 시험은 약이 안 듣는다는 증거가 아니다.**
        #   그런데 본문에 "Terminated"가 있으면 LLM은 반증으로 읽는다.
        #   벤치마크 라벨을 만들 때는 이 구분을 하면서(bench/labels.py)
        #   정작 근거를 읽을 때는 안 했다. 같은 잣대를 여기에도 건다.
        #
        #   단, 1차 평가변수 수치는 여전히 유효한 근거다. 중단 사유가
        #   운영상 문제여도 결과가 올라와 있으면 그 결과는 읽는다.
        #   인용이 상태 줄에서 왔을 때만 막는다.
        if (direction == "refute" and rec.get("stop_reason") == "operational"
                and not _in_outcome(r["quote"], rec["abstract"])):
            r.update(direction="neutral", weight=0.0, kept=False,
                     skip="운영상 중단(등록 부진·자금 등) — 효능 반증 아님 → 무관 강등")
            r["stop_reason_guard"] = True
            out[pmid] = r
            continue
        # GRADE: LLM 판단과 원문 탐지 중 보수적인 쪽을 쓴다.
        # 저자가 "may slightly reduce"라고 썼으면 LLM이 high라 해도 low로 내린다.
        c_llm = str(d.get("certainty", "high")).lower().replace(" ", "_")
        # 초록 전체로 넘어가지 않는다. 인용문에 단서가 없으면 LLM 판단만 쓴다.
        c_txt = grade_from_text(r["quote"])
        order = ["very_low", "low", "moderate", "high"]
        cands = [x for x in (c_llm, c_txt) if x in order]
        cert = min(cands, key=order.index) if cands else "high"
        r["certainty"] = cert
        r["certainty_src"] = ("원문" if c_txt == cert and c_txt != c_llm else "LLM")
        # ⚠ 09-01 · 배치 경로도 `review` 를 읽는다 (단건과 같은 규칙)
        r["review"] = r.get("review", "peer_reviewed")
        w = weight_for(r["study_type"], size, dec, conf, cert,
                       review=r["review"])

        # ── 판정을 뒷받침하지 않는 인용은 근거가 아니다 ────────────
        #
        #   인용 검증은 *지어냈는가*만 본다. 실재하는 문장이어도 결과가
        #   없으면 그 판정을 정당화하지 못한다. 실측에서 측정 방법·환자
        #   배정·향후 계획 문장이 w=3.0 이상으로 채택됐다.
        #
        #   방향 자체는 맞을 수 있다 — 팩트체커는 초록 전체를 읽으니까.
        #   그래서 죽이지 않고 감쇠한다. **다만 감사 추적이 거짓인 상태를
        #   그대로 두면 안 된다.** 근거를 열어본 사람이 납득할 수 없다.
        if not has_result(r["quote"], structured=structured):
            w *= NO_RESULT_MULT
            r["no_result"] = True
            r["no_result_note"] = "인용문에 결과 진술 없음 — 정당성 부족으로 감쇠"

        # ── 그 약을 지목하지 않는 근거는 간접 근거다 ──────────────
        #
        #   실측: `interferon beta-1a / Crohn` 이 **natalizumab** 메타분석으로
        #   유망 94%를 받았다. 인용문에 인터페론이 한 번도 안 나온다.
        #
        #   0으로 죽이지 않고 절반으로 깎는 이유 — 계열 근거가 섞여 있다.
        #   "platinum drugs significantly ..." 는 cisplatin을 직접 지목하진
        #   않지만 무가치하지도 않다. **계열 효과는 약 자체의 근거보다 약하다**는
        #   것이 정확한 서술이고, 감쇠가 그 서술에 맞는다.
        #   전부 죽이면 정당한 계열 근거까지 잃고, 그대로 두면 natalizumab이 통과한다.
        if not names_drug(drug, r.get("title"), r["quote"]):
            w *= INDIRECT_MULT
            r["indirect"] = True
            r["indirect_note"] = "제목·인용에 약물명 없음 — 간접 근거로 감쇠"

        r.update(direction=direction, kept=True, skip=None, weight=round(w, 3),
                 size=size, decisive=dec, confidence=conf)
        out[pmid] = r

    return [out[r.get("pmid", "")] for r in recs]


def tag_for(r: Dict[str, Any]) -> str:
    """근거 표시명 — 사람이 읽고 원문을 찾아갈 수 있어야 한다."""
    bits = [b for b in (r.get("journal"), str(r.get("year") or "")) if b]
    head = " ".join(bits) if bits else "PMID %s" % r["pmid"]
    label = {"meta": "메타분석", "rct": "RCT", "trial": "임상시험",
             "observational": "관찰연구", "review": "고찰",
             "in_vitro": "시험관", "case": "증례"}.get(r.get("study_type"), "기타")
    return "%s %s(%s)" % (head, label, "지지" if r["direction"] == "support" else "반박")
