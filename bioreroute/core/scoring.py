# -*- coding: utf-8 -*-
"""판정 — 로그오즈 베이지안 누적.

주의: 단순 합산은 조건부 독립을 가정한다. 상관된 증거(같은 모집단·설계 계열의
RCT 여러 건)를 그대로 더하면 확신이 과대평가된다. 제안서 §2가 약속한 대로
동일 증거군은 감쇠해서 통합한다(attenuate_correlated).
"""

import math
import os
from typing import Any, Dict, List, Optional, Tuple

from .state import Candidate, Evidence


# 같은 방향 증거를 그대로 더하면 확신이 과대평가된다. 실측으로 확인된 문제다.
#   바리시티닙: Lancet 메타분석이 NEJM RCT를 포함하는데 둘을 따로 세어
#   로그오즈 8.38(=99.98%)이 나왔다. 같은 환자를 두 번 센 것이다.
# 기본값 0.5는 잠정치다. 벤치마크로 보정하기 전까지는 설계 판단이지 측정값이 아니다.
CORR_FACTOR = float(os.environ.get("BIOREROUTE_CORR_FACTOR", "0.5"))

# 문헌만으로는 확정에 이를 수 없다. 로그오즈 절대값에 상한을 둔다.
#   4.0 → 약 98%. 100%를 출력하는 판정기는 그 자체로 틀렸다.
LOGIT_CAP = float(os.environ.get("BIOREROUTE_LOGIT_CAP", "4.0"))


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def attenuate_correlated(items: List[Evidence], factor: float = 1.0) -> float:
    """증거군 감쇠. factor=1.0이면 감쇠 없음(W1 동작과 동일).

    factor<1.0이면 두 번째 이후 증거의 가중을 기하급수적으로 줄인다.
    예: factor=0.5 → 1.0, 0.5, 0.25 …
    """
    if factor >= 1.0:
        return sum(e.weight for e in items)
    total = 0.0
    for i, e in enumerate(sorted(items, key=lambda x: -x.weight)):
        total += e.weight * (factor ** i)
    return total


CONFIRMATORY = {"rct", "meta"}


def dedupe_trials(c: Candidate) -> int:
    """같은 임상시험을 가리키는 근거를 하나로 줄인다.

    본 논문·장기추적·하위분석이 각각 별개 근거로 잡히면 같은 환자를 여러 번 센다.
    실측 사례: COVID-OUT 본 논문(PMID 36070710)과 long COVID 추적(37302406)이
    각각 로그오즈 3.00 반박으로 계산됐다. NCT 번호가 같으면 강한 쪽만 남긴다.
    """
    by_nct = {}
    for r in (c.factcheck or []):
        for n in (r.get("nct") or []):
            by_nct.setdefault(n, []).append(r)
    dropped = 0
    kill = set()
    for n, rs in by_nct.items():
        rs = [r for r in rs if r.get("kept")]
        if len(rs) < 2:
            continue
        rs.sort(key=lambda r: -r["weight"])
        for r in rs[1:]:
            kill.add(id(r))
            r["dup_of"] = n
            dropped += 1
    if kill:
        for r in c.factcheck:
            if id(r) in kill:
                r["kept"] = False
                r["skip"] = "같은 시험 중복(%s) — 강한 쪽만 유지" % r["dup_of"]
    return dropped


# 조건부로 부르려면 양쪽 근거가 **비슷한 무게**여야 한다.
#   약한 쪽이 강한 쪽의 이 비율 미만이면 조건부가 아니라 강한 쪽이 결론이다.
#   실측 문제: 소규모 2상 양성(0.6) + 대규모 3상 음성(3.0)이 조건부로 나왔다.
#   확증 3상이 실패했으면 그게 결론이지, 그 3상이 반증한 2상과 대등하지 않다.
BALANCE = float(os.environ.get("BIOREROUTE_BALANCE", "0.5"))


def confirmatory_split(c: Candidate):
    """확증 설계(RCT·메타분석) 근거를 방향별로 센다."""
    fc = [r for r in (c.factcheck or []) if r.get("kept")
          and r.get("study_type") in CONFIRMATORY]
    return ([r for r in fc if r["direction"] == "support"],
            [r for r in fc if r["direction"] == "refute"])


def contested(c: Candidate, balance: float = None):
    """양방향 확증 근거가 **대등한가**. (여부, 지지수, 반박수, 비율)

    개수만 세면 안 된다. 무게를 봐야 한다.

    `balance` 는 **출구 축**이 바꾸는 셋 중 하나다(결함 256).
    안 주면 `BALANCE`(표준 0.50) — **기본값이 지금까지의 모든 측정값이다.**
    """
    sup, ref = confirmatory_split(c)
    if not sup or not ref:
        return False, len(sup), len(ref), 0.0
    ws = sum(r.get("weight", 0) for r in sup)
    wr = sum(r.get("weight", 0) for r in ref)
    lo, hi = min(ws, wr), max(ws, wr)
    ratio = (lo / hi) if hi else 0.0
    bal = BALANCE if balance is None else balance
    return ratio >= bal, len(sup), len(ref), ratio


def adjudicate(c: Candidate, corr_factor: float = None,
               profile: Dict[str, Any] = None) -> Tuple[str, Optional[int], str]:
    """F0 결과 + 증거 → (판정, 확률%, 사유)

    ## `profile` — 출구 축 (제안서 §2.2) · 결함 256

    앞판은 문턱을 **`p >= 80` · `p >= 40` 상수로 박아** 뒀다. 그래서
    `profiles.exit_profile` 이 있어도 **판정이 안 움직였다** — 화면
    좌측이 «기각 문턱 25» 를 찍는 동안 중앙은 «metformin 기각 26%»
    였다. **26 ≥ 25 인데 기각이다.** 심사위원이 산수하면 나온다.

    **기본값(`None`)은 표준이고, 표준 값은 아래 상수와 같다.**
    즉 **동결 수치는 한 자리도 안 움직인다** — 시험 [140] 이 그걸 못 박는다.
    프로파일이 바꾸는 것은 셋이다: `유망`·`기각` 문턱과 `balance`.
    """
    from . import profiles
    prof = profile or profiles.exit_profile("표준")
    f0 = c.f0 or {}
    f0_ran = bool(f0)          # 게이트를 돌렸는가

    # 0) F0를 아예 돌리지 않은 구성(제거 실험 B0·B1)에서는
    #    '0건'과 '미실행'을 혼동하면 안 된다. 미실행이면 F0 규칙을 건너뛴다.
    if f0_ran:
        # 1) F0 조회 실패 — 허위 판정 금지
        if f0.get("error"):
            return "보류", None, "F0 조회 실패(네트워크) — 판정 보류"

        # 2) 실체 없음 = 환각 → 하드 기각
        #    단, 2겹 F0에서 약물 실재가 확인됐으면 환각이 아니다.
        if (f0.get("count") or 0) == 0:
            if f0.get("link_zero"):
                return ("보류", 50,
                        "약물은 실재하나 질환 연결 문헌 0건 — 판단 근거 없음"
                        "(신규성 신호일 수 있음)")
            return "기각", 0, "F0: 문헌 근거 없음(환각)"

    # 3) 결정적 반박 하드 비토
    #    ※ 임상 반증에만 적용한다. 서로 다른 조건에서 일관되게 음성일 때만이며,
    #      조건이 갈리면 기각이 아니라 보류로 간다(제안서 §2.3 PICO 규율).
    if c.veto:
        return "기각", 0, c.veto_reason or "결정적 반박"

    # 4) 로그오즈 누적 (사전확률 0.5 → logit 0)
    #    사람이 매긴 근거(W1)는 이미 중복을 제거한 값이므로 감쇠하지 않는다.
    #    LLM이 회수한 근거는 메타분석이 개별 RCT를 포함하는 등 상관이 크다.
    f = corr_factor
    if f is None:
        llm_sourced = any(e.source == "llm" for e in c.support + c.refute)
        f = CORR_FACTOR if llm_sourced else 1.0

    raw = attenuate_correlated(c.support, f) - attenuate_correlated(c.refute, f)
    logit = max(-LOGIT_CAP, min(LOGIT_CAP, raw))
    capped = abs(raw) > LOGIT_CAP
    p = int(round(sigmoid(logit) * 100))

    note = " · 상한 적용" if capped else ""
    if not c.support and not c.refute:
        return "보류", p, "증거 없음 — 판정 근거 부족"

    # 확증 설계가 양방향으로 존재하면 단일 결론을 내면 안 된다.
    #   제안서 §2.3: 조건이 갈리면 기각이 아니라 조건부다.
    #   실측 근거: 플루복사민은 코크란 메타(지지)와 COVID-OUT RCT(반박)를
    #   동시에 갖는다. 순 로그오즈만 보면 기각 16%지만, 그건
    #   "특정 조건에서는 듣는다"는 정보를 버리는 판정이다.
    ok_c, n_sup, n_ref, ratio = contested(c, prof["balance"])
    if ok_c:
        return ("조건부", p,
                "확증 설계 양방향·대등(지지 %d·반박 %d, 무게비 %.2f) — "
                "대상군·용량·시점별 결론 필요%s" % (n_sup, n_ref, ratio, note))
    if n_sup and n_ref:
        # 양방향이지만 한쪽이 압도한다. 조건부가 아니라 강한 쪽이 결론이다.
        note += " · 확증 근거 %d대%d이나 무게비 %.2f로 한쪽 우세" % (n_sup, n_ref, ratio)

    if p >= prof["유망"]:
        return "유망", p, "강한 지지·명백한 반박 없음" + note
    if p >= prof["기각"]:
        # ── ⛔ 09-25 · 보류 사유가 **근거 모양과 무관한 고정 문구**였다 (결함 340) ──
        #
        #   모든 보류에 «근거 엇갈림(확증 임상 실패 포함)» 을 붙였다. 본선 데모의
        #   `rifampin / Tuberculosis`(결핵 표준 치료제)는 **지지 고찰 둘(w=0.14) · 반박 0**
        #   인데 이 문구가 붙었고, 화면은 «근거가 갈립니다» 라고 말했다. 판정은 그대로
        #   두고 **문구가 거짓말**한 결함 34 의 자리다(그때는 기각 사유였다).
        #
        #   **판정·확률은 한 자리도 안 바뀐다** — 문턱과 `p` 는 위에서 이미 정해졌다.
        #   바뀌는 것은 사유 글자뿐이고, 기각 사유처럼 **근거의 수와 무게**를 적는다.
        ws = sum(e.weight for e in c.refute)
        wp = sum(e.weight for e in c.support)
        if c.support and c.refute:
            why = ("근거 엇갈림 (지지 %d건 w=%.2f · 반박 %d건 w=%.2f) → 확증 임상 권고"
                   % (len(c.support), wp, len(c.refute), ws))
        elif c.support:
            why = ("근거가 약함 (지지 %d건 w=%.2f · 반박 없음) → 확증 임상 권고"
                   % (len(c.support), wp))
        else:
            why = ("반박이 약함 (반박 %d건 w=%.2f · 지지 없음) → 기각할 만큼 쌓이지 않음"
                   % (len(c.refute), ws))
        return "보류", p, why + note

    # ── 기각 사유는 **부재가 아니라 반박 우세**다 (결함 34) ──────────
    #
    #   전에는 "지지 근거 부족"이라고만 적었다. 부재처럼 읽힌다.
    #   그런데 규칙상 근거가 하나도 없으면 위에서 `보류`(p=50)로 빠지므로,
    #   여기까지 온 것은 **반박이 지지보다 무겁다**는 뜻이다.
    #
    #   실측 사고: 깔때기 실험에서 기각 6건의 사유가 전부 "지지 근거 부족"
    #   이었다. 나는 그걸 보고 *"근거가 없어서 기각했구나"* 라고 읽었고,
    #   근거를 전수 세고 나서야 여섯 다 반박 우세였음을 알았다
    #   (예: metformin/Breast Neoplasms 지지 w=1.04 vs 반박 w=8.08).
    #
    #   **판정은 옳았고 문구가 거짓말했다.** 결함 12와 같은 유형이다 —
    #   감사 추적이 거짓인 상태를 그대로 두면 근거를 열어 본 사람이 오판한다.
    ws = sum(e.weight for e in c.refute)
    wp = sum(e.weight for e in c.support)
    return "기각", p, ("반박 우세 (지지 %d건 w=%.2f · 반박 %d건 w=%.2f)"
                     % (len(c.support), wp, len(c.refute), ws)) + note


def prepare(c: Candidate) -> int:
    """판정 직전 정리 — 중복 시험 제거. 반환값은 제거 건수."""
    return dedupe_trials(c)
