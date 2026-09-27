# -*- coding: utf-8 -*-
"""선택적 예측(selective prediction) — **위험–커버리지 곡선과 AURC**

    py -m bioreroute.bench.selective            표
    py -m bioreroute.bench.selective --json     기계용
    py -m bioreroute.bench.selective --md       문서에 붙일 마크다운

## ⚠ 왜 이걸 뒤늦게 만드나 (2026-08-31)

우리는 **«근거가 부족하면 판단불가를 낸다»** 를 차별점으로 내세웠다.
그런데 그 결정을 **평가하는 표준 도구를 안 썼다.**

`홀드아웃결과.md` 가 이렇게 적어 놨다 —

    시스템은 기각하지 않고 **기권한다**(보류 85%)

    | | 커버리지 | 정확도 |
    | 전수 387쌍 | B0 39% / B5 43% | B0 76% / B5 78% |

**커버리지가 다른데 정확도를 나란히 비교했다.** 더 많이 기권하면 남은
것의 정확도는 당연히 오른다 — 이 비교는 **B5 에 유리하게 기울어 있다.**
NeurIPS 2024 «Overcoming Common Flaws in the Evaluation of Selective
Classification Systems» 가 지적하는 바로 그 결함이다.

## 이 분야에는 이름이 있다 — 우리가 만든 게 아니다

| 우리 말 | 표준 이름 · 출처 |
|---|---|
| 판단불가 · 기권 | **reject option** — Chow (1957) |
| 기권하는 분류기 | **selective classification** — El-Yaniv & Wiener (2010) JMLR |
| 커버리지 대비 오류 | **risk–coverage curve** |
| 그 곡선 아래 면적 | **AURC** — Geifman et al. (2018) |

**신규성 주장은 줄어든다. 대신 방법론적 정당성이 는다.**
`선행연구대조.md` 가 여덟 번 배운 그 교훈이고, 여기가 아홉 번째다.

## 무엇을 재나

    커버리지 c   판정을 낸 비율 (1 - 기권율)
    선택 위험 r  **판정한 것 중** 틀린 비율
    AURC         모든 임계에서의 위험을 커버리지로 적분 — **낮을수록 좋다**

핵심은 **같은 커버리지에서 비교**하는 것이다. 곡선이 우하향하면
«신뢰도가 정보를 담고 있다» — 자신 있는 것부터 답하면 덜 틀린다.

곡선이 평평하면 **기권이 무의미하다.** 그건 우리 설계가 틀렸다는 뜻이고,
그 결과가 나와도 그대로 적는다.

## ⚠ 무엇을 안 하나

**라벨을 다시 만들지 않는다**(`CLAUDE.md §3-1`). `bench_results_sealed.json`
을 **읽기만** 한다. 새 벤치마크가 아니라 **이미 나온 결과를 표준 방식으로
다시 보는 것**이므로 §3-2(결과를 보고 고친 뒤 같은 벤치로 재기)에도
해당하지 않는다 — 점수도 판정도 손대지 않는다.
"""
import argparse
import json
import os
import random
import statistics
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import calibrate as C
from . import stats as S

OUT_DEFAULT = "선택예측결과.json"

REPEATS = 200          # 동점 무작위화 반복 — 아래 ⚠ 를 봐라


# ── ⚠ 동점(tie) 문제 — 2026-08-31 자기 검증에서 잡았다 ────────────────
#
# 첫 판은 `sorted(key=-|s-0.5|)` 만 썼다. 파이썬 `sorted` 는 **안정 정렬**
# 이라 **확신도가 같은 것들은 파일에 적힌 순서 그대로** 남는다.
#
# 그런데 `bench_results_sealed.json` 의 행은 **TN·TP 가 완벽히 교대**한다
# (387 + 387). 그리고 B0 는 서로 다른 확신도가 **네 개뿐**이고 그중
# **469 건(61%)이 |s-0.5| = 0** 인 한 덩어리다.
#
# AURC 는 누적 평균의 평균이라 **앞쪽 오답에 더 큰 벌점**을 준다. 그래서
# 동점 덩어리가 교대 순서로 들어가면 오답이 고르게 퍼져 **벌점이 인위적
# 으로 낮아진다.** 실측 —
#
#     B0  안정정렬 0.3028 · 무작위 평균 0.3203  → **2.8 SD 만큼 유리**
#     B5  안정정렬 0.2438 · 무작위 평균 0.2462  → 0.8 SD
#
# **자료를 담아 둔 순서가 지표를 움직였다.** 우연히 B0(대조군) 쪽이 더
# 이득을 봤으므로 이 편향은 **우리 주장에 불리한 방향**이었지만, 방향이
# 어느 쪽이든 고쳐야 한다.
#
# 해법은 표준대로 — **동점을 무작위로 섞어 여러 번 재고 평균**한다.
# seed 를 고정해 재현 가능하게 두고, **흩어진 정도(SD)도 같이 보고**한다.
def _order(s: Sequence[float], seed: Optional[int]) -> List[int]:
    """확신도 내림차순. `seed` 가 있으면 **동점 순서를 무작위화**한다."""
    idx = list(range(len(s)))
    if seed is not None:
        random.Random(seed).shuffle(idx)
    idx.sort(key=lambda i: -abs(s[i] - 0.5))
    return idx


# ── ⚠⚠ 기권을 무엇으로 셀 것인가 — 08-31 두 번째 결함 ────────────────
#
# 첫 판은 `pred = 1 if s >= thr else 0` 하나로 끝냈다. **그 부등호가
# 결론을 만들었다.**
#
# 점수 `0.500` 은 «모름/보류», 곧 **기권**이다. 예측이 아니다. 그런데
# `>=` 는 그걸 전부 **양성 예측**으로 세어 버린다. 그리고 실측 —
#
#     B0 기권 469건 → 양성 194 · **음성 275**
#     B5 기권 283건 → 양성 139 · 음성 144
#
# **B0 는 기권을 음성 쪽에 훨씬 많이 냈다.** 그것을 전부 «양성이라고
# 답했다» 고 세면 B0 만 275건을 틀린 것이 된다. 결과 —
#
#     동점→양성(첫 판)  B0 0.549 · B5 0.623 · 차 +0.074 · **p=0.004**
#     동점→음성        B0 0.654 · B5 0.629 · 차 −0.025 · p=0.340
#     동점→무작위       B0 0.624 · B5 0.602 · 차 −0.022 · p=0.404
#
# **부등호 하나로 «유의한 우세» 가 «열세» 로 뒤집힌다.**
#
# AURC·AUGRC 는 방향(B5 우세)이 세 처리에서 모두 유지되지만 **크기가
# 최대 15배 차이난다**(AUGRC 차 0.0333 → 0.0022). 0.0022 는 이 지표의
# 흔들림(SD)과 같은 크기다.
#
# 그래서 **어느 하나를 고르지 않는다. 셋을 다 보고한다.**
# 기본값은 가장 보수적인 `"neg"` 다 — 우리(B5)에게 가장 불리하다.
TIES = ("neg", "rand", "pos")


def _pred(si: float, thr: float, tie: str, rng: random.Random) -> int:
    """기권(`|s-thr| < eps`)을 무엇으로 셀지 **명시적으로** 고른다."""
    if abs(si - thr) < 1e-9:
        if tie == "pos":
            return 1
        if tie == "neg":
            return 0
        return rng.randint(0, 1)
    return 1 if si > thr else 0


# ── 위험–커버리지 ────────────────────────────────────────────────────
def risk_coverage(s: Sequence[float], y: Sequence[int],
                  thr: float = 0.5,
                  seed: Optional[int] = None,
                  tie: str = "neg") -> List[Dict[str, float]]:
    """확신도 순으로 정렬해 커버리지를 1건씩 늘리며 위험을 잰다.

    **확신도**는 «0.5 에서 얼마나 먼가» 다. 0.97 도 0.03 도 확신이 크고,
    0.51 은 작다. 이진 판정에서 자연스러운 정의다.

    `seed=None` 이면 안정 정렬(파일 순서 유지)이다 — **비교에 쓰지 마라.**
    위의 ⚠ 를 봐라. 정식 수치는 `evaluate()` 가 내는 무작위 평균이다.
    """
    n = len(y)
    if n == 0:
        return []
    idx = _order(s, seed)
    rng = random.Random((seed or 0) + 99991)
    out, wrong = [], 0
    for k, i in enumerate(idx, 1):
        pred = _pred(s[i], thr, tie, rng)
        if pred != y[i]:
            wrong += 1
        out.append({"n": k, "coverage": k / float(n),
                    "risk": wrong / float(k),        # 선택 위험 — 분모 k
                    "grisk": wrong / float(n),       # 일반화 위험 — 분모 n
                    "confidence": abs(s[i] - 0.5)})
    return out


def augrc(rc: Sequence[Dict[str, float]]) -> float:
    """**AUGRC** — Traub et al., NeurIPS 2024 (arXiv:2407.01032).

    ## ⚠ 그 논문은 AURC 를 **비판하는** 논문이다 (08-31 정정)

    처음에 나는 이 논문을 *"커버리지가 다른 걸 나란히 비교하지 마라"* 의
    근거로만 인용했다. **절반만 읽은 것이다.** 논문의 본론은 —

        Selective Risk    P(Yf=1 | g(x)≥τ)   조건부 — **수락한 것 중** 오류율
        Generalized Risk  P(Yf=1, g(x)≥τ)    결합  — **전체 중** 못 걸러낸 오류

    AURC 는 앞쪽(선택 위험)을 문턱에 걸쳐 모은 것인데, 논문은 그것이
    *"기각된 사례를 무시하므로 전체적 평가와 모순된다"* 고 본다. 그래서
    뒤쪽(일반화 위험)으로 만든 **AUGRC** 를 제안하고, 6개 자료 중 **5개
    에서 순위가 바뀌었다**고 보고한다.

    ## 우리에게는 이쪽이 더 맞다

    AUGRC 는 «**틀렸는데 안 걸러진**» 비율이다. 우리 논지가 정확히
    *"그럴듯하지만 틀린 후보를 값싸게 걸러내는 것"* 이므로, 재야 할 것은
    **못 걸러낸 오류**다. 기권한 것을 분모에서 빼 주는 AURC 보다 정직하다.

    구현은 분모만 다르다 — `wrong/k` 가 아니라 `wrong/n`.
    """
    if not rc:
        return float("nan")
    return sum(r["grisk"] for r in rc) / len(rc)


def aurc(rc: Sequence[Dict[str, float]]) -> float:
    """AURC — 커버리지에 대한 선택 위험의 평균. **낮을수록 좋다.**

    Geifman et al.(2018) 의 정의대로 모든 커버리지 수준에서의 위험을
    평균한다(이산이므로 단순 평균이 사다리꼴 적분과 같다).
    """
    if not rc:
        return float("nan")
    return sum(r["risk"] for r in rc) / len(rc)


# ── 기각 정밀도 — **우리 일의 정확한 지표** (09-01) ──────────────────
#
# ## 왜 이걸 뒤늦게 재나
#
# 사전명세의 주③은 게이트 유효성을 **기각 재현율**(TN 중 몇 %를
# 걸러내나)로 정의했고 **p = 0.077 로 미달**했다. 그런데 그 지표는
# **뒷면을 안 본다** — «거른 것이 맞았나» 다.
#
# 우리 논지는 *"그럴듯하지만 틀린 후보를 값싸게 걸러낸다"* 이다.
# 연구자가 실제로 쓰는 방식은 **«이건 확실히 안 된다» 목록의 상위
# 몇 개를 본다** 이지 «전수를 다 거른다» 가 아니다. 그러면 재야 할
# 것은 **정밀도**다.
#
# ## 09-01 실측 — 전 구간에서 20%p 앞선다
#
#     가장 강하게 기각한 K개 중 **실제로 실패한(TN)** 비율
#       K= 50   B0 0.737   B5 **0.940**   +0.203
#       K=100   B0 0.686   B5 **0.890**   +0.204   p<0.001 · CI 안 겹침
#
# **«많이는 못 거르지만, 거른 것은 정확하다.»** 재현율이 낮은 것은
# 기권 85% 설계의 필연이고, 정밀도가 높은 것이 그 설계의 값이다.
# 두 수치는 모순이 아니라 **정밀도–재현율 트레이드오프의 두 끝**이다.
#
# ## ⚠ 이 지표의 함정 둘
#
# **① K 가 기각 건수를 넘으면 「보류」가 섞인다.** B5 의 `기각` 은
# 106건이다. K=200 이면 94개가 보류이고, 그건 «기각했다» 가 아니다.
# 그래서 `n_verdict_reject` 를 같이 돌려주고 **넘으면 표시한다.**
#
# **② K 를 여러 개 보는 것 자체가 다중비교다.** 그래서 어느 하나를
# 고르지 않고 **전 구간을 싣는다.** 10~200 에서 일관되게 우세한 것이
# 단일 K 의 p 값보다 강한 증거다.
def reject_precision(s: Sequence[float], y: Sequence[int], k: int,
                     seed: Optional[int] = None) -> float:
    """**가장 강하게 기각한 K개** 중 실제로 음성(TN)인 비율.

    점수가 낮을수록 «기각» 이다. 동점은 `seed` 로 섞는다(08-31 결함①).
    """
    n = len(y)
    if n == 0 or k <= 0:
        return float("nan")
    k = min(k, n)
    idx = list(range(n))
    if seed is not None:
        random.Random(seed).shuffle(idx)
    idx.sort(key=lambda i: s[i])
    return sum(1 - y[i] for i in idx[:k]) / float(k)


def reject_curve(s: Sequence[float], y: Sequence[int],
                 ks: Sequence[int] = (10, 20, 30, 50, 100, 200),
                 repeats: int = REPEATS) -> List[Dict[str, Any]]:
    """K 를 훑으며 기각 정밀도를 잰다 — **전 구간을 싣는다**(위 ⚠②)."""
    out = []
    for k in ks:
        v = [reject_precision(s, y, k, seed) for seed in range(repeats)]
        out.append({"k": k, "precision": statistics.mean(v),
                    "SD": statistics.pstdev(v) if len(v) > 1 else 0.0})
    return out


def risk_at(rc: Sequence[Dict[str, float]], cov: float) -> Optional[float]:
    """**주어진 커버리지에서의 위험** — 공정 비교는 이걸로 한다."""
    best = None
    for r in rc:
        if r["coverage"] <= cov + 1e-9:
            best = r
    return best["risk"] if best else None


def optimal_aurc(y: Sequence[int], thr_pred: Sequence[int]) -> float:
    """**완벽한 확신도**를 가졌다면 나왔을 AURC — 곡선의 하한.

    맞은 것을 전부 먼저 답하고 틀린 것을 나중에 답하는 순서다.
    실제 AURC 를 이것과 비교해야 «확신도가 쓸모 있나» 가 보인다.
    """
    err = sorted(1 if p != t else 0 for p, t in zip(thr_pred, y))
    out, wrong = [], 0
    for k, e in enumerate(err, 1):
        wrong += e
        out.append(wrong / float(k))
    return sum(out) / len(out) if out else float("nan")


COVS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


def evaluate(s: Sequence[float], y: Sequence[int],
             thr: float = 0.5, repeats: int = REPEATS,
             tie: str = "neg") -> Dict[str, Any]:
    """**동점을 무작위화해 `repeats` 번 재고 평균**한다(위 ⚠ 참조).

    `AURC` 는 그 평균이고 `AURC_SD` 는 흩어진 정도다. SD 가 크면
    «자료 순서에 따라 값이 흔들린다» 는 뜻이므로 **차이를 주장할 때
    반드시 SD 와 견주어야 한다.**
    """
    n = len(y)
    _r = random.Random(12345)
    pred = [_pred(x, thr, tie, _r) for x in s]
    acc = sum(1 for p, t in zip(pred, y) if p == t) / float(n) if n else 0.0
    opt = optimal_aurc(y, pred)

    a_vals: List[float] = []
    g_vals: List[float] = []
    cov_vals: Dict[str, List[float]] = {("%.2f" % c): [] for c in COVS}
    rep = None
    for seed in range(repeats):
        rc = risk_coverage(s, y, thr, seed=seed, tie=tie)
        a_vals.append(aurc(rc))
        g_vals.append(augrc(rc))
        for c in COVS:
            v = risk_at(rc, c)
            if v is not None:
                cov_vals["%.2f" % c].append(v)
        if seed == 0:
            rep = rc                      # 표시용 대표 곡선
    a = statistics.mean(a_vals) if a_vals else float("nan")
    sd = statistics.pstdev(a_vals) if len(a_vals) > 1 else 0.0
    g = statistics.mean(g_vals) if g_vals else float("nan")
    gsd = statistics.pstdev(g_vals) if len(g_vals) > 1 else 0.0
    # 참고용 — 고치기 전 방식. 문서에 «무엇이 틀렸었나» 를 적으려고 남긴다
    a_stable = aurc(risk_coverage(s, y, thr, seed=None, tie=tie))
    return {
        "n": n,
        "기권처리": tie,
        "전체정확도": acc,
        "AUGRC": g,               # ← Traub 2024 가 권하는 주 지표
        "AUGRC_SD": gsd,
        "AURC": a,
        "AURC_SD": sd,
        "AURC_안정정렬": a_stable,        # ⚠ 편향된 옛 값 — 보고하지 마라
        "반복": repeats,
        "최적AURC": opt,
        "초과": a - opt,          # 확신도가 완벽했을 때보다 얼마나 나쁜가
        "커버리지별위험": {k: (statistics.mean(v) if v else None)
                           for k, v in cov_vals.items()},
        "커버리지별SD": {k: (statistics.pstdev(v) if len(v) > 1 else 0.0)
                         for k, v in cov_vals.items()},
        "곡선": rep or [],
    }


# ── 두 구성 비교 — **같은 커버리지에서** ─────────────────────────────
def compare(a: Dict[str, Any], b: Dict[str, Any],
            name_a: str, name_b: str) -> List[Dict[str, Any]]:
    """**동점 무작위화 평균**끼리 비교한다 — 대표 곡선 하나를 쓰지 않는다."""
    rows = []
    for c in COVS:
        k = "%.2f" % c
        ra = (a.get("커버리지별위험") or {}).get(k)
        rb = (b.get("커버리지별위험") or {}).get(k)
        if ra is None or rb is None:
            continue
        sa = (a.get("커버리지별SD") or {}).get(k, 0.0)
        sb = (b.get("커버리지별SD") or {}).get(k, 0.0)
        rows.append({"커버리지": c, name_a: ra, name_b: rb,
                     "차이": rb - ra,
                     "SD합": (sa ** 2 + sb ** 2) ** 0.5})
    return rows


def _acc_and_p(got: Dict[str, Any], ks: Sequence[str],
               thr: float, tie: str) -> Dict[str, Any]:
    """한 기권 처리에서의 전체정확도와 2×2 Fisher."""
    ya = got[ks[0]]["y"]
    n = len(ya)
    cs = []
    for k in ks:
        r = random.Random(12345)
        pr = [_pred(x, thr, tie, r) for x in got[k]["s"]]
        cs.append(sum(1 for p, t in zip(pr, ya) if p == t))
    return {"기권처리": tie, ks[0]: [cs[0], n], ks[1]: [cs[1], n],
            "정확도차": (cs[1] - cs[0]) / float(n),
            "p": S.fisher(cs[0], n - cs[0], cs[1], n - cs[1])}


def run(eval_p: str = None, configs: Sequence[str] = ("B0", "B5"),
        thr: float = 0.5, repeats: int = REPEATS,
        tie: str = "neg") -> Dict[str, Any]:
    eval_p = eval_p or C.EVAL_DEFAULT
    out: Dict[str, Any] = {"파일": eval_p, "문턱": thr,
                           "동점순서": "무작위 %d회 평균" % repeats,
                           "기권처리": tie,
                           "구성": {}}
    got, ev = {}, {}
    for cfg in configs:
        d = C.load(eval_p, cfg)
        if not d:
            out["구성"][cfg] = {"오류": "읽지 못함"}
            continue
        got[cfg] = d
        ev[cfg] = evaluate(d["s"], d["y"], thr, repeats, tie)
        r = dict(ev[cfg])
        r.pop("곡선")                     # json 이 커진다 — 요약만 남긴다
        out["구성"][cfg] = r
    if len(got) == 2:
        ks = list(got)
        out["같은커버리지비교"] = compare(ev[ks[0]], ev[ks[1]], ks[0], ks[1])
        out["전체정확도검정"] = _acc_and_p(got, ks, thr, tie)
        # ── 기각 정밀도 — **우리 일의 정확한 지표** (09-01) ──────────
        out["기각정밀도"] = {k: reject_curve(got[k]["s"], got[k]["y"],
                                             repeats=max(30, repeats // 4))
                             for k in ks}
        # ⚠ K 가 이 수를 넘으면 「보류」가 섞인다 — 위 함정 ①
        out["기각방향건수"] = {k: sum(1 for x in got[k]["s"] if x < thr)
                               for k in ks}
        # ⚠ **기권 처리 민감도** — 이 표가 08-31 결함의 재발 방지 장치다.
        #    어느 하나를 고르지 않고 셋을 다 싣는다.
        sens = []
        for t in TIES:
            row = dict(_acc_and_p(got, ks, thr, t))
            for k in ks:
                e = evaluate(got[k]["s"], got[k]["y"], thr,
                             max(30, repeats // 4), t)
                row["%s_AUGRC" % k] = e["AUGRC"]
                row["%s_AURC" % k] = e["AURC"]
            row["AUGRC차"] = row["%s_AUGRC" % ks[0]] - row["%s_AUGRC" % ks[1]]
            sens.append(row)
        out["기권처리민감도"] = sens
    return out


# ── 출력 ────────────────────────────────────────────────────────────
def _table(r: Dict[str, Any]) -> str:
    L = ["=" * 70,
         "선택적 예측 — 위험–커버리지 · AURC",
         "  Chow(1957) reject option · El-Yaniv & Wiener(2010) ·"
         " AURC: Geifman et al.(2018)",
         "=" * 70,
         "  자료  %s · 문턱 %.2f" % (r["파일"], r["문턱"]),
         "  동점순서  %s  ← 자료 순서가 지표를 움직인다(08-31 결함①)"
         % r["동점순서"],
         "  기권처리  %s  ← 이 선택이 결론을 바꾼다(08-31 결함③)"
         % r["기권처리"], ""]
    for cfg, d in r["구성"].items():
        if "오류" in d:
            L.append("  %-4s  ⚠ %s" % (cfg, d["오류"]))
            continue
        L.append("  [%s]  n=%d · 전체정확도 %.3f" % (cfg, d["n"], d["전체정확도"]))
        L.append("        **AUGRC %.4f ± %.4f**  ← 주 지표 (Traub 2024) ·"
                 " 못 걸러낸 오류의 평균"
                 % (d.get("AUGRC", float("nan")), d.get("AUGRC_SD", 0.0)))
        L.append("        AURC %.4f ± %.4f   (완벽한 확신도라면 %.4f · 초과 %+.4f)"
                 % (d["AURC"], d.get("AURC_SD", 0.0), d["최적AURC"], d["초과"]))
        if "AURC_안정정렬" in d:
            L.append("        ⚠ 파일 순서 그대로면 %.4f 가 나온다 — 편향된 값이다"
                     % d["AURC_안정정렬"])
        cv = d["커버리지별위험"]
        L.append("        커버리지  " + " ".join("%5s" % k for k in cv))
        L.append("        선택위험  " + " ".join(
            ("%5.3f" % v) if v is not None else "    –" for v in cv.values()))
        L.append("")
    if "같은커버리지비교" in r:
        ks = [k for k in r["구성"] if "오류" not in r["구성"][k]]
        L += ["  ── **같은 커버리지에서 비교** — 여기가 요점이다 ──",
              "     커버리지 " + " ".join("%6.1f" % (x["커버리지"] * 100)
                                          for x in r["같은커버리지비교"])]
        for k in ks:
            L.append("     %-8s " % k + " ".join(
                "%6.3f" % x[k] for x in r["같은커버리지비교"]))
        L.append("     차이     " + " ".join(
            "%+6.3f" % x["차이"] for x in r["같은커버리지비교"]))
        L.append("     ±SD     " + " ".join(
            "%6.3f" % x.get("SD합", 0.0) for x in r["같은커버리지비교"]))
        L.append("     ⚠ 차이가 ±SD 보다 작은 칸은 **자료 순서만큼의 흔들림**이다")
        t = r.get("전체정확도검정") or {}
        if "p" in t:
            L.append("")
            L.append("     전체(커버리지 100%%) 정확도 %s %d/%d · %s %d/%d · Fisher %s"
                     % (ks[0], t[ks[0]][0], t[ks[0]][1],
                        ks[1], t[ks[1]][0], t[ks[1]][1], S.fmt_p(t["p"])))
    rp = r.get("기각정밀도")
    if rp:
        ks = [k for k in r["구성"] if "오류" not in r["구성"][k]]
        cnt = r.get("기각방향건수") or {}
        L += ["", "  ── **기각 정밀도** — 거른 것이 맞았나 (우리 일) ──",
              "     주③은 «얼마나 많이 거르나»(재현율)라 **미달**했다.",
              "     이건 그 **뒷면**이다 — 무작위면 0.500", ""]
        kk = [x["k"] for x in rp[ks[0]]]
        L.append("     K        " + " ".join("%6d" % k for k in kk))
        for c in ks:
            L.append("     %-8s " % c + " ".join(
                "%6.3f" % x["precision"] for x in rp[c]))
        L.append("     차이     " + " ".join(
            "%+6.3f" % (rp[ks[1]][i]["precision"] - rp[ks[0]][i]["precision"])
            for i in range(len(kk))))
        L.append("     ⚠ 기각 방향 건수 " + " · ".join(
            "%s %d" % (c, cnt.get(c, 0)) for c in ks)
            + " — **K 가 이를 넘으면 「보류」가 섞인다**")
    sens = r.get("기권처리민감도")
    if sens:
        ks = [k for k in r["구성"] if "오류" not in r["구성"][k]]
        L += ["", "  ── ⚠ **기권을 무엇으로 세느냐에 따른 민감도** ──",
              "     첫 판은 «양성» 하나만 썼고 그 부등호가 결론을 만들었다",
              "",
              "     처리      %-6s정확도 %-6s정확도    차     Fisher      AUGRC차"
              % (ks[0], ks[1])]
        for x in sens:
            n = x[ks[0]][1]
            L.append("     %-8s  %.3f       %.3f      %+.3f  %-12s %+.4f"
                     % (x["기권처리"], x[ks[0]][0] / float(n),
                        x[ks[1]][0] / float(n), x["정확도차"],
                        S.fmt_p(x["p"]), x["AUGRC차"]))
        L += ["",
              "     **정확도·p 는 처리에 따라 뒤집힌다.** 주 결과로 쓰지 마라.",
              "     AUGRC 차는 부호(B5 우세)가 유지되나 **크기가 15배까지**",
              "     달라진다 — 가장 보수적인 `neg` 값을 보고한다."]
    L += ["", "=" * 70,
          "  **AURC 는 낮을수록 좋다.** 「초과」가 0 에 가까울수록 확신도가",
          "  실제 오류를 잘 예측한다는 뜻이다 — 기권이 정보를 담고 있다.",
          "  곡선이 평평하면 **기권해도 나아지지 않는다** = 설계가 틀렸다.",
          "=" * 70]
    return "\n".join(L)


def _md(r: Dict[str, Any]) -> str:
    L = ["## 선택적 예측 — 위험–커버리지와 AURC", "",
         "> 「판단불가」는 **selective classification**(Chow 1957 · "
         "El-Yaniv & Wiener 2010)이고, 표준 지표는 **AURC**"
         "(Geifman et al. 2018)다. 우리가 만든 개념이 아니다.", "",
         "> ⚠ **커버리지가 다른 두 구성의 정확도를 나란히 비교하면 안 된다.**",
         "> 더 많이 기권하면 남은 것의 정확도는 당연히 오른다.", ""]
    L += ["> ⚠ 동점 순서는 **%s**, 기권 처리는 **%s** 다. 둘 다 08-31 에"
          " 잡은 결함이고 **어느 쪽도 기본값에 기대면 안 된다.**"
          % (r["동점순서"], r["기권처리"]), "",
          "| 구성 | n | 전체정확도 | **AUGRC** | ±SD | AURC | ±SD | 완벽하다면 |",
          "|---|---|---|---|---|---|---|---|"]
    for cfg, d in r["구성"].items():
        if "오류" in d:
            continue
        L.append("| **%s** | %d | %.3f | **%.4f** | %.4f | %.4f | %.4f | %.4f |"
                 % (cfg, d["n"], d["전체정확도"], d.get("AUGRC", float("nan")),
                    d.get("AUGRC_SD", 0.0), d["AURC"],
                    d.get("AURC_SD", 0.0), d["최적AURC"]))
    if "같은커버리지비교" in r:
        ks = [k for k in r["구성"] if "오류" not in r["구성"][k]]
        L += ["", "### 같은 커버리지에서의 선택 위험", "",
              "| 커버리지 | " + " | ".join(ks) + " | 차이 | ±SD | 배율 |",
              "|---|" + "---|" * (len(ks) + 3)]
        for x in r["같은커버리지비교"]:
            sd = x.get("SD합", 0.0)
            rat = ("%.1f배" % (abs(x["차이"]) / sd)) if sd > 0 else "–"
            L.append("| %.0f%% | " % (x["커버리지"] * 100)
                     + " | ".join("%.3f" % x[k] for k in ks)
                     + " | %+.3f | %.3f | %s |" % (x["차이"], sd, rat))
        L += ["", "> **배율**은 «차이 ÷ 흔들림» 이다. 1 보다 작으면 그 칸의"
              " 차이는 **자료 순서만큼의 잡음**이므로 근거로 쓰지 마라."]
    sens = r.get("기권처리민감도")
    if sens:
        ks = [k for k in r["구성"] if "오류" not in r["구성"][k]]
        L += ["", "### ⚠ 기권을 무엇으로 세느냐에 따른 민감도", "",
              "> 첫 판은 «양성» 하나만 썼고 **그 부등호가 결론을 만들었다.**",
              "> 정확도와 p 는 처리에 따라 **뒤집힌다.** 주 결과로 쓰지 마라.", "",
              "| 기권 처리 | %s 정확도 | %s 정확도 | 차 | Fisher | AUGRC 차 |"
              % (ks[0], ks[1]), "|---|---|---|---|---|---|"]
        for x in sens:
            n = float(x[ks[0]][1])
            L.append("| `%s` | %.3f | %.3f | %+.3f | %s | %+.4f |"
                     % (x["기권처리"], x[ks[0]][0] / n, x[ks[1]][0] / n,
                        x["정확도차"], S.fmt_p(x["p"]), x["AUGRC차"]))
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="선택적 예측 평가 — 위험–커버리지·AURC (LLM 0회 · 읽기만)")
    ap.add_argument("--eval", default=None)
    ap.add_argument("--thr", type=float, default=0.5)
    ap.add_argument("--tie", default="neg", choices=list(TIES),
                    help="기권(s=문턱)을 무엇으로 셀지. 기본 neg = 가장 보수적")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--out", default=None, help="결과를 이 경로에 저장")
    a = ap.parse_args(argv)
    r = run(a.eval, thr=a.thr, tie=a.tie)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif a.md:
        print(_md(r))
    else:
        print(_table(r))
    if a.out:
        from ..io import safeio
        w = safeio.save_json(r, a.out, indent=1)   # ⚠ (obj, path) 순서다
        print("\n→ %s" % w.get("경로", a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
