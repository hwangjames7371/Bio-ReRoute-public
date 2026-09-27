# -*- coding: utf-8 -*-
"""모델 간 판정 일치도 — BYOM 주장의 실측 근거.

제안서 §3.2는 "모델 비종속"을 주장한다. 주장만으로는 심사에서 버티지 못한다.
"모델 바꾸면 결과 달라지는 거 아니냐"는 질문에 숫자를 내밀 수 있어야 한다.

같은 초록을 두 모델에 태워 Cohen's κ를 잰다.
  κ ≥ 0.8  거의 완전 일치 — 모델 교체가 판정을 바꾸지 않는다
  κ 0.6~0.8 상당한 일치 — 실용상 허용
  κ < 0.6  판정이 모델에 의존한다 → 비종속 주장을 접거나 프롬프트를 고쳐야 한다

실행: py -m bioreroute.agreement
      py -m bioreroute.agreement --models gpt-5-mini gemini/gemini-flash-latest
"""

import argparse
import math
import sys

from .agents import factcheck
from .core.scoring import adjudicate, prepare
from .core.state import Candidate, Evidence, build_candidates
from .io import cache, llm, sources

LABELS = ["support", "refute", "neutral"]
BASE_A, BASE_B = [], []
VERDICTS = []


def cohen_kappa(a, b):
    """두 평가자의 일치도. 우연에 의한 일치를 보정한다.

    단순 일치율은 한쪽으로 쏠린 분포에서 과대평가된다. 예컨대 둘 다 90%를
    neutral로 찍으면 일치율 90%가 나오지만 실력은 없다. κ는 그걸 걷어낸다.
    """
    n = len(a)
    if n == 0:
        return None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = sum((a.count(L) / n) * (b.count(L) / n) for L in LABELS)
    if abs(1 - pe) < 1e-12:
        return 1.0 if abs(po - 1.0) < 1e-12 else 0.0
    return (po - pe) / (1 - pe)


def kappa_ci(a, b, k):
    """κ의 95% 신뢰구간(정규 근사).

    n이 작으면 κ 점추정만으로 "거의 완전 일치"라고 말할 수 없다.
    실측 n=31에서 하한이 0.71까지 내려간다 — 결론이 "상당한 일치"로 바뀐다.
    """
    n = len(a)
    if n < 2 or k is None:
        return None, None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = sum((a.count(L) / n) * (b.count(L) / n) for L in LABELS)
    if abs(1 - pe) < 1e-9:
        return None, None
    se = math.sqrt(max(po * (1 - po), 1e-12) / (n * (1 - pe) ** 2))
    return max(-1.0, k - 1.96 * se), min(1.0, k + 1.96 * se)


def verdict_of(results):
    """팩트체크 결과 → 최종 판정. 방향 일치보다 이쪽이 실제로 중요하다.

    방향이 같아도 가중치가 다르면 확률이 갈리고 판정이 뒤집힐 수 있다.
    사용자가 보는 건 방향이 아니라 판정이다.
    """
    c = Candidate(name="x", origin="", query="")
    c.f0 = {"count": 1}
    c.factcheck = [dict(r) for r in results]
    prepare(c)
    kept = [r for r in c.factcheck if r.get("kept")]
    c.support = [Evidence("s", "support", r["weight"], source="llm")
                 for r in kept if r["direction"] == "support"]
    c.refute = [Evidence("r", "refute", r["weight"], source="llm")
                for r in kept if r["direction"] == "refute"]
    return adjudicate(c)


def read(model, drug, disease, recs, fresh=False):
    """fresh=True면 캐시를 우회한다(재시험 신뢰도 측정용)."""
    saved, llm.MODEL = llm.MODEL, model
    saved_fb, llm.FALLBACKS = llm.FALLBACKS, []      # 폴백을 끄지 않으면 비교가 오염된다
    saved_bp, llm.BYPASS_CACHE = llm.BYPASS_CACHE, fresh
    try:
        return factcheck.classify_batch(drug, disease, recs)
    finally:
        llm.MODEL, llm.FALLBACKS, llm.BYPASS_CACHE = saved, saved_fb, saved_bp


def main(argv=None):
    ap = argparse.ArgumentParser()
    # 기본값은 온도 0을 받는 모델이어야 한다. 온도가 풀린 모델을 A로 쓰면
    # 자기 재시험 κ가 그 모델의 불안정성만 재게 되어 해석이 흐려진다.
    ap.add_argument("--models", nargs=2,
                    default=["gpt-5.4-mini", "gemini/gemini-flash-latest"])
    ap.add_argument("--n", type=int, default=8, help="후보당 초록 수")
    ap.add_argument("--cache", default="pubmed_cache.json")
    ap.add_argument("--baseline", action="store_true",
                    help="같은 모델을 두 번 돌려 잡음 바닥을 먼저 잰다 (호출 2배)")
    a = ap.parse_args(argv)

    cache.configure(a.cache)
    cache.load()
    m1, m2 = a.models

    print("=" * 74)
    print("모델 간 판정 일치도")
    print("  A: %s" % m1)
    print("  B: %s" % m2)
    print("=" * 74)

    A, B, rows = [], [], []
    del BASE_A[:], BASE_B[:], VERDICTS[:]
    for c in build_candidates():
        if not c.drug:
            continue
        s = sources.pubmed_search(c.query, a.n)
        if s.get("error") or not s["pmids"]:
            print("\n  %s — 검색 실패, 건너뜀" % c.name)
            continue
        recs = sources.pubmed_abstracts(s["pmids"])
        live = [recs[p] for p in s["pmids"] if p in recs]

        r1 = read(m1, c.drug, c.disease, live)
        r2 = read(m2, c.drug, c.disease, live)
        if a.baseline:
            rb = read(m1, c.drug, c.disease, live, fresh=True)
            for x, y in zip(r1, rb):
                if not (x.get("skip") and "철회" in str(x["skip"])):
                    BASE_A.append(x["direction"])
                    BASE_B.append(y["direction"])

        v1, v2 = verdict_of(r1), verdict_of(r2)
        VERDICTS.append((c.name, v1, v2))
        print("\n  %s   판정 A=%s %s%% / B=%s %s%%%s"
              % (c.name, v1[0], v1[1], v2[0], v2[1],
                 "   ← 판정 불일치" if v1[0] != v2[0] else ""))
        for x, y in zip(r1, r2):
            if x.get("skip") and "철회" in str(x["skip"]):
                continue                              # 결정론적 배제는 비교 대상 아님
            d1, d2 = x["direction"], y["direction"]
            A.append(d1)
            B.append(d2)
            mark = " " if d1 == d2 else "≠"
            print("    %s PMID %-10s A=%-8s B=%-8s  w %.2f / %.2f"
                  % (mark, x["pmid"], d1, d2, x["weight"], y["weight"]))
            rows.append((c.name, x["pmid"], d1, d2, x["weight"], y["weight"]))

    print("")
    print("=" * 74)
    if not A:
        print("비교할 판정이 없다. 할당량 또는 검색을 확인한다.")
        print("=" * 74)
        return 1

    k = cohen_kappa(A, B)
    same = sum(1 for x, y in zip(A, B) if x == y)
    verdict = ("거의 완전 일치" if k >= 0.8 else "상당한 일치" if k >= 0.6
               else "보통" if k >= 0.4 else "낮음 — 모델 의존적")
    lo, hi = kappa_ci(A, B, k)
    ci = ("  [95%% CI %.2f–%.2f]" % (lo, hi)) if lo is not None else ""
    # 해석은 점추정이 아니라 하한으로 한다. 하한이 0.8 미만이면
    # "거의 완전 일치"라고 말할 근거가 없다.
    base = lo if lo is not None else k
    verdict = ("거의 완전 일치" if base >= 0.8 else "상당한 일치" if base >= 0.6
               else "보통" if base >= 0.4 else "낮음 — 모델 의존적")
    print("  근거 %d건 · 방향 일치 %d건 (%.0f%%)" % (len(A), same, 100.0 * same / len(A)))
    print("  모델 간 κ = %.3f%s  → %s" % (k, ci, verdict))

    # 근거 질량 기준 일치 — κ가 못 보는 것을 본다.
    #   판정을 좌우하는 건 결정적 근거이지 잔챙이가 아니다.
    #   가중치 0.14짜리 불일치와 3.60짜리 불일치를 같게 세면 해석을 그르친다.
    mass_all = sum(max(w1, w2) for _, _, _, _, w1, w2 in rows)
    mass_bad = sum(max(w1, w2) for _, _, d1, d2, w1, w2 in rows if d1 != d2)
    if mass_all > 0:
        print("  근거 질량 기준 일치 = %.1f%%  (불일치 질량 %.2f / 전체 %.2f)"
              % (100 * (1 - mass_bad / mass_all), mass_bad, mass_all))
        big = [(p_, w1, w2) for _, p_, d1, d2, w1, w2 in rows
               if d1 != d2 and max(w1, w2) >= 1.0]
        if big:
            print("     결정적 근거(w≥1.0)에서 불일치 %d건:" % len(big))
            for p_, w1, w2 in big:
                print("       PMID %s  %.2f / %.2f" % (p_, w1, w2))
        else:
            print("     결정적 근거(w≥1.0)에서는 불일치 없음")

    # 잡음 바닥과 비교해야 해석이 선다.
    # 온도를 0으로 못 박지 못하는 모델은 자기 자신과도 완전히 일치하지 않는다.
    # 그 값을 모르면 모델 간 κ가 "모델 차이"인지 "샘플링 잡음"인지 구분할 수 없다.
    if BASE_A:
        kb = cohen_kappa(BASE_A, BASE_B)
        print("  자기 재시험 κ = %.3f  (%s 두 번, 잡음 바닥)" % (kb, m1))
        if kb is not None and k is not None:
            if k >= kb - 0.05:
                print("  → 모델 간 불일치가 잡음 수준이다.")
            else:
                print("  → 방향 κ는 잡음보다 %.3f 낮다. 다만 이 지표만으로 단정하지 않는다"
                      % (kb - k))
                print("     — 아래 근거 질량·판정 일치를 함께 본다.")
    else:
        print("  (--baseline 을 주면 잡음 바닥을 함께 잰다 — 해석에 필요하다)")

    tu = {str(c.get("temperature_used")) for c in llm.call_log()
          if c.get("temperature_used") is not None}
    if any("default" in t for t in tu):
        print("")
        print("  [주의] 온도를 0으로 고정하지 못한 모델이 있다(%s)." % ", ".join(sorted(tu)))
        print("         --baseline 없이는 위 κ를 모델 차이로 읽으면 안 된다.")

    # 가중치 차이 — 방향이 같아도 강도가 다르면 확률이 갈린다.
    #   무관(w=0)끼리를 포함하면 평균이 0으로 희석돼 문제를 숨긴다.
    #   실제로 채택된 근거만 본다.
    live = [(w1, w2) for _, _, d1, d2, w1, w2 in rows
            if d1 == d2 and (w1 > 0 or w2 > 0)]
    if live:
        d = sum(abs(w1 - w2) for w1, w2 in live) / len(live)
        rel = sum(abs(w1 - w2) / max(w1, w2) for w1, w2 in live) / len(live)
        print("  채택 근거 %d건의 가중치 차 = %.2f (상대 %.0f%%)" % (len(live), d, rel * 100))
        if rel > 0.25:
            print("     → 방향은 같아도 강도가 크게 다르다. 최종 확률이 갈릴 수 있다.")

    # 판정 수준 일치 — 사용자가 실제로 보는 것
    if VERDICTS:
        agree = sum(1 for _, v1, v2 in VERDICTS if v1[0] == v2[0])
        print("")
        print("  판정 일치 %d/%d" % (agree, len(VERDICTS)))
        for name, v1, v2 in VERDICTS:
            if v1[0] != v2[0]:
                print("     %s: A=%s %s%% / B=%s %s%%" % (name, v1[0], v1[1], v2[0], v2[1]))
        gap = [abs((v1[1] or 0) - (v2[1] or 0)) for _, v1, v2 in VERDICTS]
        if gap:
            print("  확률 최대 격차 %d%%p · 평균 %d%%p"
                  % (max(gap), sum(gap) / len(gap)))

        print("")
        print("  [종합] 지표 셋을 함께 읽는다")
        ok_mass = mass_all > 0 and (1 - mass_bad / mass_all) >= 0.95
        ok_verd = agree == len(VERDICTS)
        if ok_mass and ok_verd:
            print("    방향 불일치는 저가중 근거에 몰려 있고, 결정적 근거와 최종 판정은")
            print("    일치한다. 모델 교체가 결론을 바꾸지 않는다는 근거가 된다.")
        elif ok_verd:
            print("    최종 판정은 일치하나 근거 질량 불일치가 5%를 넘는다. 표본을 늘려야 한다.")
        else:
            print("    최종 판정이 갈린다. 비종속 주장을 이 데이터로 지지할 수 없다.")
        print("    ※ 표본 %d후보 · 근거 %d건은 결론을 확정하기에 작다." % (len(VERDICTS), len(A)))
        print("      벤치마크(후보 100개)로 재측정해야 신뢰구간이 좁아진다.")
        print("    ※ 이 판정은 회의주의자를 끈 상태(B2 상당)의 값이다.")

    f = llm.failure_summary()
    if f["failed"]:
        print("")
        print("  [주의] 호출 %d건 실패 — 위 수치는 성공분만 반영한다." % f["failed"])
        for msg, n in sorted(f["reasons"].items(), key=lambda x: -x[1])[:3]:
            print("     %3d회  %s" % (n, msg))
    print("  실제 호출 %d/%d" % (f["spent"], f["budget"]))
    print("=" * 74)
    cache.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
