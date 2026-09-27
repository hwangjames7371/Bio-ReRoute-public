# -*- coding: utf-8 -*-
"""LLM 어댑터 — 모델 비종속(BYOM) 계층.

제안서 §3.2가 약속한 두 가지를 코드로 강제한다.
  1. 모델 교체 가능성 — LiteLLM 한 겹 뒤에서 설정만으로 교체
  2. 감사 추적성   — 판정마다 모델·버전·온도·프롬프트 해시를 기록

둘은 서로 긴장 관계다. 모델을 바꿀 수 있다는 것과 판정을 감사할 수 있다는 것은
같이 가지 않으므로, 교체는 반드시 이력 기록을 동반해야 한다.

키가 없거나 litellm이 없으면 죽지 않고 NOT_CONFIGURED를 돌려준다.
Phase 0(LLM 미사용)에서 파이프라인이 그대로 돌아가야 하기 때문이다.
"""

from .. import config as _config  # .env를 먼저 올린다 (순서 중요)

import hashlib
import json
import os
import threading
from typing import Any, Dict, Optional

from . import cache

MODEL = os.environ.get("BIOREROUTE_MODEL", "gpt-5-mini")
# 429가 나면 순서대로 넘어간다. Gemini 무료 티어는 모델마다 하루 20회를 따로 세므로
# 체인에 남겨두면 유료 호출을 아끼는 완충재가 된다.
FALLBACKS = [x.strip() for x in os.environ.get(
    "BIOREROUTE_FALLBACKS",
    "gemini/gemini-flash-latest,gemini/gemini-2.0-flash"
).split(",") if x.strip()]
TEMPERATURE = 0.0          # 재현성 우선
MAX_RETRY = 1

# ── 커스텀 엔드포인트 (09-09 · 데이콘 본선 프록시) ──────────────────
#
#   본선 크레딧은 OpenAI 직결이 아니라 **Azure API Management 프록시**로
#   온다. 인증 헤더가 `Authorization: Bearer` 가 아니라 **`api-key`** 다
#   (안내문이 *"일부 SDK 는 Bearer 로만 보낸다 — 이 경우 반드시 api-key
#   사용자 지정 헤더도 함께 설정해야 한다"* 고 적었다).
#
#   ⚠ **비어 있으면 아무것도 안 바뀐다.** 지금까지의 실행과 완전히 같은
#     경로로 돈다. 켜는 순간부터는 **다른 시스템**이므로
#     `사전명세_모델교체_본선.md` 를 먼저 읽어라(`CLAUDE.md §3-2`).
#
#   ⚠ **키를 이 파일에 적지 마라.** 환경변수·`.env` 뿐이다
#     (`.gitignore` 가 `.env` 를 막고 있고, GitHub 이관이 예정돼 있다).
API_BASE = (os.environ.get("BIOREROUTE_API_BASE") or "").strip().rstrip("/")
API_KEY_HEADER = (os.environ.get("BIOREROUTE_API_KEY_HEADER")
                  or "api-key").strip()


def _proxy_key() -> str:
    for n in ("DACON_API_KEY", "BIOREROUTE_API_KEY", "OPENAI_API_KEY"):
        v = (os.environ.get(n) or "").strip()
        if v:
            return v
    return ""


def _endpoint_kwargs(model: str) -> Dict[str, Any]:
    """프록시로 보낼 모델에만 붙는다.

    `gemini/…` 처럼 **공급자 접두어가 붙은 다른 자료원은 안 건드린다** —
    폴백 사슬(무료 티어 완충재)이 그대로 살아 있어야 하기 때문이다.
    """
    if not API_BASE:
        return {}
    if "/" in model and not model.startswith("openai/"):
        return {}                          # gemini/… 등은 원래 경로로
    k = _proxy_key()
    if not k:
        return {}
    return {"api_base": API_BASE, "api_key": k,
            "extra_headers": {API_KEY_HEADER: k}}


# ── `seed` — 09-12 실측으로 되찾은 재현성 ────────────────────────────
#
#   본선 모델은 `temperature=0` 을 거부한다(§ 위 주석). 그래서 이 프로젝트가
#   여덟 달 동안 «재현성 우선» 이라 적어 온 근거가 사라졌다.
#   그런데 `apiprobe --determinism` 으로 재 보니 **셋 다 `seed` 를 받고,
#   `seed` 를 고정하면 자유도 높은 질문도 5/5 로 같은 답**이 왔다.
#
#   ⚠ **보장이 아니다.** OpenAI 계열의 `seed` 는 best-effort 이고 백엔드가
#     바뀌면 달라진다. **«재현된다» 가 아니라 «재현을 시도한다»** 로 적는다.
#
#   ⚠ **캐시 키에 `seed` 가 안 들어간다**(`LLM::{모델}::{온도}::{프롬프트}`).
#     고정해 쓰는 동안은 문제가 없지만 **값을 바꾸면 옛 답이 그대로 나온다.**
#     바꿀 일이 있으면 캐시를 비우거나 키 규약을 먼저 고쳐라.
SEED = (os.environ.get("BIOREROUTE_SEED") or "").strip()


def _seed_kwargs(model: str) -> Dict[str, Any]:
    """`seed` 를 받는 경로에만 붙인다. 비어 있으면 **기존 동작 그대로**."""
    if not SEED:
        return {}
    if "/" in model and not model.startswith("openai/"):
        return {}                          # gemini/… 등은 규약이 다르다
    try:
        return {"seed": int(SEED)}
    except ValueError:
        return {}


def _usage(r) -> Dict[str, Any]:
    """응답의 토큰 사용량. **크레딧 효율 15점의 원자료**.

    ⚠ 못 읽으면 **0 이 아니라 빈 값**이다 — «안 썼다» 와 «모른다» 는
      다르다(`CLAUDE.md §2` · 결함 35 계열). 집계는 그 둘을 갈라 센다.
    """
    try:
        u = r.get("usage") or {}
        if hasattr(u, "model_dump"):
            u = u.model_dump()
        elif not isinstance(u, dict):
            u = dict(u)
    except Exception:
        return {}
    if not u:
        return {}
    # ── **두 형식을 다 읽는다** (09-09 실측에서 걸렸다) ──────────────
    #
    #   Chat Completions   `prompt_tokens` / `completion_tokens`
    #   Responses API      `input_tokens`  / `output_tokens`
    #
    #   본선 프록시가 **Responses 형식**으로 답하는 것을 `apiprobe` 에서
    #   봤다: `{"input_tokens": 9, "output_tokens": 5, "total_tokens": 14}`.
    #   앞 이름만 읽으면 **토큰이 통째로 «계량 안 됨»** 이 된다 — 그래도
    #   0으로 안 밀도록 짜 뒀으니 «없어지는» 대신 «모른다» 로 남지만,
    #   **읽을 수 있는 값을 못 읽는 것은 그냥 결함이다.**
    pro = u.get("prompt_tokens")
    if pro is None:
        pro = u.get("input_tokens")
    com = u.get("completion_tokens")
    if com is None:
        com = u.get("output_tokens")
    tot = u.get("total_tokens")
    if tot is None and not (pro is None and com is None):
        tot = (pro or 0) + (com or 0)
    return {"prompt": pro, "completion": com, "total": tot}

# ─────────────────────────────────────────────────────────────
# 역할별 모델 배정 (제안서 §3.2 비용 통제)
#
#   > 작업 성격에 따라 모델을 나눈다. **기전 분류·형식 정규화처럼
#   > 결정론적 작업은 소형 모델에**, **반박 탐색처럼 적대적 추론이
#   > 필요한 작업은 고성능 모델에** 배정한다.
#
# 08-06까지 이걸 안 하고 있었다 — 전부 한 모델이었다. 환경변수로 나눈다.
# **기본값은 전부 MODEL 이다.** 안 그러면 지금까지의 실행과 모델이 달라져
# 동결 수치가 다른 시스템의 수치가 된다(`CLAUDE.md §3-2`).
#
#   BIOREROUTE_MODEL_SMALL   기전 분류 · 용어 변환 · 승인 판별
#   BIOREROUTE_MODEL_STRONG  반박 탐색(회의주의자) · 팩트체크
ROLE_ENV = {"small": "BIOREROUTE_MODEL_SMALL",
            "strong": "BIOREROUTE_MODEL_STRONG"}
# 어느 역할이 어느 등급인가. 제안서 문장을 그대로 옮긴 것이다.
#   09-15 · `limits` 추가 — 저자가 적은 한계가 **효능 주장을 약화시키는지**
#     판정한다. 제안서 §3.2 의 *"적대적 추론이 필요한 작업"* 에 해당하므로
#     `strong` 이다. ⚠ 지금은 small/strong 을 안 갈라 쓰고 있지만(전부
#     기본 모델), **선언은 해 둔다** — 나중에 가를 때 여기가 정본이다.
ROLE_OF = {"router": "small", "reverse_terms": "small", "approval": "small",
           "discover": "small",
           "skeptic": "strong", "factcheck": "strong", "limits": "strong"}


def model_for(role: str) -> str:
    """역할 → 모델. **설정이 없으면 기본 모델**을 그대로 쓴다.

    설정을 안 하면 지금까지와 **완전히 같은 동작**이다. 그게 중요하다 —
    이 기능을 켠 것만으로 봉인된 수치가 바뀌면 안 된다.
    """
    tier = ROLE_OF.get(role or "")
    if not tier:
        return MODEL
    return os.environ.get(ROLE_ENV[tier], "") or MODEL


def roles_in_use() -> Dict[str, str]:
    """지금 어떤 역할이 어떤 모델로 도는가. **감사 추적용**(§3.2).

    ⚠ **이 표는 「선언」이지 「배선」이 아니다** — 결함 232.

    08-18까지 `ROLE_OF` 여섯 중 **셋이 죽어 있었다**(`skeptic`·`approval`·
    `discover`). 그 셋은 `model_for()` 를 아무 데서도 안 불렀고, 그래서
    **환경변수를 바꿔도 아무 일이 안 났다.** 그런데 이 함수는 여섯을 다
    찍었다 — **감사 추적이 거짓말을 했다.**

    지금은 여섯 다 배선돼 있고, **시험 [133]이 그것을 강제한다.**
    새 역할을 `ROLE_OF` 에 적기만 하면 그 시험이 실패한다. 그게 요점이다 —
    이 함수 혼자로는 배선 여부를 알 수 없다.
    """
    return {r: model_for(r) for r in sorted(ROLE_OF)}

# 유료 API로 넘어가면 버그 하나가 요금이 된다. 실행당 호출 상한을 강제한다.
# 무한 루프·재귀 호출이 생겨도 여기서 끊긴다.
MAX_CALLS = int(os.environ.get("BIOREROUTE_MAX_CALLS", "60"))

# 재시험 신뢰도(같은 모델 두 번) 측정 시에만 켠다. 캐시가 살아 있으면
# 두 번째 실행이 첫 번째 답을 그대로 돌려줘 κ=1.0이 거짓으로 나온다.
#
# ── 09-16 · **환경변수로도 켜진다** ──────────────────────────────
#
#   `사전명세_비용곡선.md` 를 쓰면서 명세에 이렇게 적었다 —
#       $env:BIOREROUTE_BYPASS_CACHE = "1"
#   **그런 환경변수가 없었다.** 이 값은 모듈 상수였고 코드를 고쳐야만
#   켜졌다. 즉 **내가 한 번도 안 돌려 본 명령을 명세에 적었다** —
#   `CLAUDE.md §5`(*"검증 환경이 실행 환경과 다르면 그 검증은 거짓말"*)
#   의 작은 판이고, **봉인 전에 걸린 것이 다행이다.**
#
#   ⚠ 기본값은 **여전히 False** 다. 환경변수를 안 걸면 지금까지와
#     완전히 같이 돈다 — 봉인된 수치가 이것 때문에 움직이면 안 된다.
BYPASS_CACHE = (os.environ.get("BIOREROUTE_BYPASS_CACHE") or "").strip() \
    in ("1", "true", "True", "yes")

_CALLS = []                # 이번 실행의 전체 호출 이력


def spent() -> int:
    """캐시 적중을 뺀 실제 과금 호출 수.

    ⚠ 09-16 · **`summary` 는 빼고 센다.** 사슬이 전부 실패하면 `_call`
      끝에서 **요약 한 줄**을 더 남기는데, 그건 호출이 아니다. JSON 파싱
      실패를 시도별로 기록하게 고치자(같은 날) **실제 2회 호출에 기록이
      3건**이 되어 `spent()` 가 하나를 더 셌다.
    """
    return sum(1 for c in _CALLS
               if not c.get("cached") and not c.get("summary"))


def tokens_spent() -> Dict[str, Any]:
    """이번 실행이 **실제로 쓴 토큰**. 캐시 적중은 0이다.

    본선 한도는 **대회 기간 누적 3,000만 토큰**이고 배점 15점이
    *"제공된 크레딧 대비 결과물의 질"* 이다. 그래서 호출 수가 아니라
    **토큰**이 정본 단위가 된다.

    ⚠ **«계량 안 된 호출» 을 따로 센다.** 응답에 usage 가 없을 때
      0으로 밀어 넣으면 *"토큰을 적게 썼다"* 는 **거짓 성과**가 된다 —
      결함 35 계열이고, 하필 **우리에게 유리한 방향**이라 더 위험하다.
    """
    tot = pro = com = 0
    known = unknown = 0
    for c in _CALLS:
        if c.get("cached"):
            continue
        # ⛔ 09-16 · **`error` 라고 건너뛰면 안 된다.** 실패해도 응답을
        #   받았으면 **토큰은 이미 썼다**(JSON 파싱 실패가 그 경우다).
        #   `NOT_CONFIGURED`·`BUDGET_EXCEEDED` 처럼 호출 자체가 없던
        #   것은 `usage` 가 비어 있어 아래에서 자연히 «계량 안 됨» 으로
        #   빠진다 — **토큰을 쓴 실패만 세어진다.**
        u = c.get("usage") or {}
        if c.get("error") and not u:
            continue                       # 호출 자체가 없던 실패
        if u.get("total") is None:
            unknown += 1
            continue
        known += 1
        tot += u.get("total") or 0
        pro += u.get("prompt") or 0
        com += u.get("completion") or 0
    return {"총토큰": tot, "입력": pro, "출력": com,
            "계량된_호출": known, "계량_안된_호출": unknown,
            "캐시적중": sum(1 for c in _CALLS if c.get("cached"))}


# 본선 크레딧 한도 — 09-09 데이콘 안내 메일(대회 기간 **누적**).
#   ⚠ 팀별 잔량을 알려 주는 헤더가 없다는 것을 09-12에 실측했다
#     (`본선API_실측.md`). 그래서 **우리가 세는 것이 유일한 계량기**다.
TOKEN_BUDGET = int(os.environ.get("BIOREROUTE_TOKEN_BUDGET", "30000000"))


def cost_report() -> Dict[str, Any]:
    """**어느 단계가 토큰을 썼나** — 깔때기 비용 곡선 (09-16 신설).

    ## 왜 총합으로는 부족한가

    배점 ④는 *"제공된 크레딧 대비 결과물의 질적 완성도"* **15점**이고,
    `심사기준대조.md §④` 가 우리 약점을 이렇게 적어 뒀다 —
    *"확장성 주장에 **실측이 얇다**."*

    총 토큰 하나로는 **«값싼 게이트를 앞에 뒀다»** 를 증명하지 못한다.
    그건 이 프로젝트의 논지 자체다 —

    > *"병목은 후보를 만드는 일이 아니라, 그럴듯하지만 틀린 후보를
    > **값싸게** 걸러내는 일이다."*  (`CLAUDE.md §2`)

    **설계 주장을 비용 곡선으로 검증한다.** 값싼 것이 앞에 있고 비싼 것이
    뒤에 있으면, 뒤 단계의 **호출 수가 앞보다 적어야** 한다. 그게 깔때기다.
    아니면 깔때기가 아니라 그냥 파이프다.

    ## 이 함수가 **주장하지 않는 것**

      · **금액을 계산하지 않는다.** 프록시 단가를 모른다
      · **다른 팀과 비교하지 않는다.** 분모를 모른다
      · `purpose` 없이 불린 호출은 **`"미상"`** 으로 남긴다 —
        0으로 밀거나 다른 칸에 합치면 **결함 35 계열**이다

    ⚠ **캐시 적중은 토큰 0이지만 호출로는 센다.** 둘을 갈라 적는다 —
      *"캐시 덕에 안 썼다"* 와 *"원래 안 불렀다"* 는 다른 말이다.
    """
    by: Dict[str, Dict[str, int]] = {}
    for c in _CALLS:
        if c.get("summary"):
            continue                       # 호출이 아니다 (`spent()` 와 같은 규칙)
        k = c.get("purpose") or "미상"
        d = by.setdefault(k, {"호출": 0, "캐시": 0, "토큰": 0,
                              "입력": 0, "출력": 0, "계량_안됨": 0})
        if c.get("cached"):
            d["캐시"] += 1
            continue
        d["호출"] += 1
        u = c.get("usage") or {}
        if c.get("error") and not u:
            continue                       # 호출 자체가 없던 실패
        if u.get("total") is None:
            d["계량_안됨"] += 1
            continue
        d["토큰"] += u.get("total") or 0
        d["입력"] += u.get("prompt") or 0
        d["출력"] += u.get("completion") or 0
    t = tokens_spent()
    return {"단계별": by, "합계": t, "한도": TOKEN_BUDGET,
            "한도대비": (t["총토큰"] / TOKEN_BUDGET) if TOKEN_BUDGET else None}


# ── 한도는 **원자적으로** 잡는다 — 결함 230 ──────────────────────
#
# `spent() >= MAX_CALLS` 는 **검사하고 나서 쓴다**(check-then-act).
# 스레드가 넷이면 넷이 동시에 «아직 59회다» 를 보고 **넷 다 통과**한다.
# 넘긴 호출은 순차였다면 `BUDGET_EXCEEDED` → **보류**가 됐을 후보에
# **실제 답을 준다.** 즉 이건 요금 문제가 아니라 **판정이 바뀌는 문제**다.
#
# 자리를 먼저 예약하고, `_CALLS` 에 기록이 남은 뒤에 반납한다. 그 사이에는
# 예약과 기록이 겹쳐 **한 번 더 보수적으로** 세는데, 그쪽이 안전한 방향이다.
_BUDGET_LOCK = threading.Lock()
_RESERVED = [0]


def _reserve() -> bool:
    """호출 한 자리를 잡는다. 자리가 없으면 `False`."""
    with _BUDGET_LOCK:
        if spent() + _RESERVED[0] >= MAX_CALLS:
            return False
        _RESERVED[0] += 1
        return True


def _release() -> None:
    with _BUDGET_LOCK:
        if _RESERVED[0] > 0:
            _RESERVED[0] -= 1


def prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def provenance(prompt: str, model: Optional[str] = None) -> Dict[str, Any]:
    """판정에 첨부할 출처 정보."""
    return {"model": model or MODEL, "temperature": TEMPERATURE,
            "prompt_sha": prompt_hash(prompt)}


def available() -> bool:
    try:
        import litellm  # noqa: F401
    except Exception:
        return False
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY")
                or os.environ.get("ANTHROPIC_API_KEY"))


def complete(prompt: str, system: str = "", model: Optional[str] = None,
             as_json: bool = False, purpose: str = "") -> Dict[str, Any]:
    """LLM 호출. 반환: {ok, text, data, error, provenance}

    실패해도 예외를 던지지 않는다. 호출부가 보수적으로(=판단 보류) 처리하도록 한다.

    ## `purpose` — **토큰을 깔때기 단계에 귀속시킨다** (09-16 신설)

    배점 ④가 *"**제공된 크레딧 대비** 결과물의 질적 완성도"* **15점**이고
    본선 한도가 **3,000만 토큰**이다. 그런데 `_CALLS` 에는 `model` ·
    `prompt_sha` 뿐이라 **«어느 게이트가 얼마를 썼나» 를 낼 수가 없었다.**

    총량만으로는 우리 논지를 증명하지 못한다 —

    > *"병목은 만드는 일이 아니라 **값싸게 걸러내는 일**"* (`CLAUDE.md §2`)

    **값싼 게이트가 앞에 있다** 는 것이 설계 주장인데, 그 증거는
    **단계별 비용 곡선**이지 총합이 아니다. `cost_report()` 가 그것을 낸다.

    ### ⚠ 왜 이름이 `role` 이 **아닌가** — 가드를 멀게 하지 않으려고

    시험 **[133]** 은 소스를 AST 로 읽어 `role="x"` 키워드를 **«그 역할이
    `model_for` 에 배선됐다»** 는 증거로 센다(회의주의자가 그 꼴이다).
    여기에 `role="router"` 를 적으면 **계량용 표식이 배선 증거로 오독**되어
    [133] 이 **죽은 역할을 살아 있다고 보고**하게 된다 — 결함 232 가
    정확히 그 사고였고, 그때 *"감사 추적이 거짓말을 했다"* 고 적었다.

    **계량은 `purpose`, 배선은 `role`.** 시험 [157] 이 이 분리를 고정한다.

    ### ⚠ 캐시 키에 **안 들어간다**

    `key` 는 `model + temperature + prompt_sha` 그대로다. 그래서 —

      · **과거 캐시가 그대로 적중한다** (재측정이 안 일어난다 · `§3-2`)
      · `provenance` 에도 **안 넣는다** — 판정 출력의 모양이 바뀌면
        동결된 결과와 대조가 어긋난다. **기록은 `_CALLS` 안에서만** 한다
    """
    m = model or MODEL
    prov = provenance(prompt, m)
    key = "LLM::%s::%s::%s" % (m, TEMPERATURE, prov["prompt_sha"])

    if cache.has(key) and not BYPASS_CACHE:
        out = dict(cache.get(key))
        p = dict(prov, served_by=out.get("served_by", m),
                 temperature_used=out.get("temperature_used", TEMPERATURE))
        out["provenance"] = p
        out["cached"] = True
        _CALLS.append({"key": key, "cached": True, "purpose": purpose, **p})
        return out

    if not _reserve():                      # 결함 230 — 원자적으로 잡는다
        err = ("BUDGET_EXCEEDED: 실행당 호출 상한 %d회 도달 — 안전을 위해 중단. "
               "늘리려면 BIOREROUTE_MAX_CALLS 를 조정한다." % MAX_CALLS)
        _CALLS.append({"key": key, "cached": False, "error": err,
                       "purpose": purpose, **prov})
        return {"ok": False, "text": "", "data": None, "error": err,
                "provenance": prov, "cached": False}
    try:
        return _call(key, prompt, system, m, prov, as_json, purpose)
    finally:
        _release()


def _call(key, prompt, system, m, prov, as_json, purpose="") -> Dict[str, Any]:
    """실제 공급자 호출. **자리를 이미 잡은 상태로만 들어온다.**

    `purpose` 는 **계량 표식**이다 — 캐시 키·`provenance` 에 안 들어가고
    `_CALLS` 기록에만 붙는다. 이유는 `complete()` 독스트링.
    """
    if not available():
        out = {"ok": False, "text": "", "data": None,
               "error": "NOT_CONFIGURED: litellm 미설치 또는 API 키 없음",
               "provenance": prov, "cached": False}
        _CALLS.append({"key": key, "cached": False, "error": "NOT_CONFIGURED",
                       "purpose": purpose, **prov})
        return out

    import litellm
    litellm.suppress_debug_info = True   # 실패마다 나오는 안내 배너 억제
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]

    # 무료 티어 할당량은 모델별로 따로 센다(GenerateRequestsPerDayPerProjectPerModel).
    # 한 모델이 429면 다음 모델로 넘어가면 실효 한도가 늘어난다.
    chain = [m] + [x for x in FALLBACKS if x != m]
    # ── **죽은 칸을 매 호출마다 다시 두드리지 않는다** (결함 313) ────────
    #
    #   08-24: 키가 바뀌어 `gpt-4o-mini` 가 **접근 불가**가 됐는데
    #   `.env` 사슬에는 그대로 남아 있었다. 그러면 **호출마다** 그 칸에서
    #   실패하고, 429 가 아니라 `_is_rate_limit` 도 아니어서
    #   **`MAX_RETRY` 만큼 재시도까지** 한다. 판정 하나에 헛 호출이 넷.
    #
    #   ⚠ **판정은 안 바뀐다** — 어차피 실패할 칸을 건너뛸 뿐이고
    #     **답하는 모델은 그대로**다. 바뀌는 것은 **시간**이고, 시연
    #     시간은 배점 30점짜리다.
    #
    #   429(일시)와 404/401/403(영구)은 **다르게 다룬다.** 429 는 내일
    #   풀리므로 사슬에 남긴다. 영구는 이 프로세스 동안 뺀다.
    skipped = [c for c in chain if c in _DEAD]
    chain = [c for c in chain if c not in _DEAD]
    if not chain:
        # **사슬이 통째로 죽었으면 조용히 실패하지 않는다** (결함 99).
        err = "ALL_DEAD: 사슬의 모든 모델이 접근 불가다 — %s" % (
            " · ".join("%s(%s)" % (k, v) for k, v in _DEAD.items()))
        p = dict(prov, served_by=None, dead=dict(_DEAD))
        _CALLS.append({"key": key, "cached": False, "error": err,
                       "purpose": purpose, **p})
        return {"ok": False, "text": "", "data": None, "error": err,
                "provenance": p, "cached": False}
    last, served = "", None

    for cand in chain:
        for attempt in range(MAX_RETRY + 1):
            try:
                kw = {} if cand in _NO_TEMP else {"temperature": TEMPERATURE}
                kw.update(_endpoint_kwargs(cand))     # 09-09 · 본선 프록시
                kw.update(_seed_kwargs(cand))         # 09-09 · 온도 0 대체
                r = litellm.completion(model=cand, messages=msgs, **kw)
                text = r["choices"][0]["message"]["content"].strip()
                # **왜 끝났나.** `length` 면 **잘린 것**이고, 그러면 JSON 이
                # 짧아져 «후보가 적게 나왔다» 로 둔갑한다 — 08-18에 발굴이
                # 10개와 2개 사이를 오갔는데 이 값을 아무 데도 안 봤다.
                # 추론 모델은 생각에도 출력 예산을 쓴다(결함 237).
                try:
                    fin = r["choices"][0].get("finish_reason") or ""
                except Exception:
                    fin = ""
                data = None
                if as_json:
                    data = _parse_json(text)
                    if data is None:
                        last = "JSON 파싱 실패"
                        # ── ⛔ 09-16 · **기록 없이 재시도하고 있었다** ──
                        #
                        #   호출은 나갔고 **토큰도 썼는데** `_CALLS` 에
                        #   아무것도 안 남기고 `continue` 했다. 그래서 —
                        #     · `spent()` 가 이 호출을 **안 센다**
                        #       → **`MAX_CALLS` 상한을 우회한다**
                        #       (사슬 3 × 재시도 2 = 최대 6회에 기록 1개)
                        #     · `tokens_spent()` 가 토큰을 **안 센다**
                        #       → 배점 15(«크레딧 대비 결과») 가 과소 보고
                        #
                        #   **셋 다 «덜 썼다» 로 보이는 방향**이다.
                        #   ⚠ 판정은 안 바뀐다 — 이 호출은 어차피 버려지고
                        #     결과에 안 들어간다. 바뀌는 것은 **계측**이고,
                        #     상한에 **더 빨리** 걸리는 쪽이라 보수적이다.
                        _CALLS.append({"key": key, "cached": False,
                                       "usage": _usage(r), "error": last,
                                       "purpose": purpose,
                                       **dict(prov, served_by=cand)})
                        continue                      # 같은 모델로 재시도
                served = cand
                # 온도를 거부당해 기본값으로 돌았다면 그 사실을 기록한다.
                # 0.0으로 적어두면 재현 가능한 척하는 허위 이력이 된다.
                temp_used = "default(비결정)" if cand in _NO_TEMP else TEMPERATURE
                # `seed` 를 쓰면 «비결정» 만 적는 것이 사실과 다르다 —
                # 온도는 여전히 기본이지만 재현을 **시도**하고 있다.
                if cand in _NO_TEMP and _seed_kwargs(cand):
                    temp_used = "default+seed%s(재현 시도·보장 아님)" % SEED
                payload = {"ok": True, "text": text, "data": data, "error": None,
                           "served_by": cand, "temperature_used": temp_used,
                           "finish_reason": fin}
                # ── **폴백 답을 요청 모델 칸에 박지 않는다** (결함 311) ──
                #
                #   캐시 키는 **요청 모델**로 만든다(`LLM::gpt-5.4-mini::…`).
                #   그런데 08-24 에 키가 막혀 있던 동안 **Gemini 가 답했고
                #   그 답이 그 칸에 저장됐다** — 52칸. 키가 풀린 뒤에도
                #   같은 질문은 **영원히 그 Gemini 답**을 준다. 캐시가
                #   «gpt-5.4-mini 의 답» 인 척 남의 답을 들고 있는 것이다.
                #
                #   **폴백은 비상 수단이지 결과가 아니다.** 일시 장애를
                #   자료원으로 승격시키는 것 — 결함 대장의 「캐시는 최적화가
                #   아니라 자료원」 계열이고, *«일시 장애 380건이 캐시에 박혀
                #   누출 차단이 88%에서 안 걸렸다»* 와 같은 병이다.
                #
                #   ⚠ **버리지는 않는다.** 답한 모델의 칸에 넣으면 —
                #     · 요청 모델이 살아나면 **다시 그 모델에게 묻는다**
                #     · 같은 폴백으로 직접 물으면 **그대로 재사용**된다
                #       (무료 티어 완충이라는 원래 목적도 남는다)
                if cand == m:
                    cache.put(key, payload)
                else:
                    cache.put("LLM::%s::%s::%s"
                              % (cand, TEMPERATURE, prov["prompt_sha"]), payload)
                p = dict(prov, served_by=cand, temperature_used=temp_used,
                         finish_reason=fin)
                # **건너뛴 칸을 감사 추적에 남긴다** — 조용한 축소는 위험하다.
                #   «왜 저 모델이 안 답했나» 를 나중에 물을 수 있어야 한다.
                if skipped:
                    p["skipped_dead"] = list(skipped)
                # ⚠ **토큰은 `_CALLS` 에만 남기고 캐시에는 안 넣는다.**
                #   캐시 적중은 토큰을 **안 쓴다** — 저장해 두면 다음에
                #   그 값이 다시 나와 «쓴 것» 으로 둔갑한다.
                _CALLS.append({"key": key, "cached": False,
                               "usage": _usage(r), "purpose": purpose, **p})
                return {"ok": True, "text": text, "data": data, "error": None,
                        "provenance": p, "cached": False}
            except Exception as e:
                last = "%s: %s" % (type(e).__name__, str(e).replace("\n", " "))
                if _temp_unsupported(e) and cand not in _NO_TEMP:
                    _NO_TEMP.add(cand)                # 기본 온도로 한 번 더
                    continue
                if _is_permanent(e):
                    # **영구 실패다.** 재시도도 다음 호출도 의미 없다.
                    _DEAD[cand] = _why(e)
                    break
                if _is_rate_limit(e):
                    break                             # 재시도 무의미 — 다음 모델로
    p = dict(prov, served_by=served)
    out = {"ok": False, "text": "", "data": None, "error": last,
           "provenance": p, "cached": False}
    # ⚠ 09-16 · **요약 한 줄**이다 — 위 시도들이 이미 각자 기록됐다.
    #   `summary` 를 달아 `spent()` 가 **중복해 세지 않게** 한다.
    _CALLS.append({"key": key, "cached": False, "error": last,
                   "summary": True, "purpose": purpose, **p})
    return out


def _parse_json(text: str):
    t = text.strip()
    if "```" in t:                                    # 코드펜스 제거
        t = t.split("```")[1]
        t = t[4:] if t.lower().startswith("json") else t
    t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    # 앞뒤에 설명을 붙이는 모델 대응 — 가장 바깥 배열/객체만 잘라낸다
    for a, b in (("[", "]"), ("{", "}")):
        i, j = t.find(a), t.rfind(b)
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except Exception:
                continue
    return None


_NO_TEMP = set()          # temperature 지정을 거부하는 모델


def _temp_unsupported(e) -> bool:
    s = str(e).lower()
    return "temperature" in s and ("unsupported" in s or "does not support" in s
                                   or "not supported" in s)


def _is_rate_limit(e) -> bool:
    s = (type(e).__name__ + " " + str(e)).lower()
    return ("ratelimit" in s or "429" in s or "resource_exhausted" in s
            or "quota" in s)


# 이 프로세스 동안 **다시 두드리지 않을 모델** (결함 313). 모델 → 이유.
_DEAD: Dict[str, str] = {}


def _is_permanent(e) -> bool:
    """**오늘 다시 물어도 같은 답이 올 실패인가.**

    429(할당량)는 **내일 풀린다** — 여기 넣으면 무료 티어 완충재가
    통째로 죽는다. 그래서 429 는 **일부러 뺀다.**

    ⚠ **망 오류를 여기 넣지 마라.** 잠깐 끊긴 것을 «영구» 로 적으면
    남은 실행 내내 그 모델을 안 쓴다 — **가드가 시스템을 죽인다.**
    """
    if _is_rate_limit(e):
        return False
    s = (type(e).__name__ + " " + str(e)).lower()
    return any(k in s for k in (
        "404", "not found", "does not exist", "model_not_found",
        "401", "invalid_api_key", "invalid api key", "unauthorized",
        "403", "do not have access", "does not have access",
        "notfounderror", "authenticationerror", "permissiondenied"))


def _why(e) -> str:
    s = str(e).replace("\n", " ")
    for k, lab in (("404", "모델 없음"), ("not found", "모델 없음"),
                   ("401", "인증 실패"), ("403", "권한 없음"),
                   ("access", "권한 없음")):
        if k in s.lower():
            return lab
    return type(e).__name__


def dead_models() -> Dict[str, str]:
    """**무엇이 죽었는지 밖에서 볼 수 있어야 한다** — 조용한 축소는 위험하다."""
    return dict(_DEAD)


def call_log():
    return list(_CALLS)


def failure_summary():
    """실패를 조용히 넘기지 않는다. 사유별로 묶어 돌려준다."""
    fails = [c for c in _CALLS if c.get("error")]
    by = {}
    for c in fails:
        msg = str(c["error"]).replace("\n", " ")[:110]
        by[msg] = by.get(msg, 0) + 1
    served = {}
    for c in _CALLS:
        if not c.get("error") and c.get("served_by"):
            served[c["served_by"]] = served.get(c["served_by"], 0) + 1
    return {"total": len(_CALLS),
            "cached": sum(1 for c in _CALLS if c.get("cached")),
            "spent": spent(), "budget": MAX_CALLS,
            "failed": len(fails), "reasons": by, "served": served}
