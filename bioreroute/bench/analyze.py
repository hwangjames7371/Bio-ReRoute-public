# -*- coding: utf-8 -*-
"""재분석 — 저장된 결과만 읽는다. LLM 재호출 없음.

AUROC는 이 시스템에 맞는 주 지표가 아니다.

  · 우리 시스템은 `보류`로 **기권**한다. 모른다고 말하는 것이 설계의 일부다.
  · AUROC는 기권을 0.5로 밀어넣어 정보를 파괴한다.
  · 그러면 "많이 기권할수록 지표가 좋아지는" 착시가 생긴다.
    실측: 폐쇄형이 84건 중 56건(67%)을 '모름'으로 답해 ECE 0.072를 얻었다.
    기저율이 50%인 판에서 0.5를 찍으면 보정 오차는 공짜로 좋아진다.

기권을 인정하는 틀이 선택적 예측(selective prediction)이다.
  · 커버리지  — 얼마나 판단을 내렸는가
  · 선택 정확도 — 판단을 내린 것 중 얼마나 맞았는가
둘을 같이 봐야 "적게 말하고 정확한" 시스템을 정당하게 평가할 수 있다.

그리고 같은 항목을 두 구성이 함께 풀었으므로 **짝지은 검정**을 써야 한다.
독립 AUROC 비교는 이 설계에서 검정력을 버리는 짓이다. McNemar를 쓴다.

실행: py -m bioreroute.bench.analyze bench_results.json
"""

import argparse
import json
import math
import sys

from .stats import fisher, power1, wilson


# 판정별 의미. 기권을 점수로 판정하면 안 된다 —
#   `보류 60%` 는 점수가 0.6이라 "판단함"으로 세어지지만, 판정 자체는
#   "근거 부족"이다. 시스템이 무슨 말을 했는지는 판정이 정한다.
ABSTAIN = {"보류", "모름"}
POSITIVE = {"유망", "성공"}
NEGATIVE = {"기각", "실패"}
PARTIAL = {"조건부"}      # 확증 근거가 양방향 — 완전한 판단이 아니다


def predict(score, band=0.02):
    """점수만으로 예측(판정이 없을 때의 대체 경로)."""
    if abs(score - 0.5) <= band:
        return None
    return 1 if score > 0.5 else 0


def predict_verdict(v, score, strict=True, band=0.02):
    """판정 → 예측. None이면 기권.

    strict=True  : 조건부도 기권으로 본다(완전한 판단이 아니므로)
    strict=False : 조건부를 점수 방향으로 해석한다
    """
    if v is None:
        return predict(score, band)
    if v in ABSTAIN:
        return None
    if v in POSITIVE:
        return 1
    if v in NEGATIVE:
        return 0
    if v in PARTIAL:
        return None if strict else predict(score, band)
    return predict(score, band)


def selective(scores, labels, band=0.02, verdicts=None, strict=True):
    """커버리지와 선택 정확도."""
    if verdicts:
        pred = [predict_verdict(v, s, strict, band)
                for v, s in zip(verdicts, scores)]
    else:
        pred = [predict(s, band) for s in scores]
    committed = [(p, l) for p, l in zip(pred, labels) if p is not None]
    n = len(scores)
    if not committed:
        return 0.0, None, 0
    acc = sum(1 for p, l in committed if p == l) / len(committed)
    return len(committed) / n, acc, len(committed)


def mcnemar(a_ok, b_ok):
    """짝지은 이항 비교. 반환 (b, c, p값)

    b = A만 맞음, c = B만 맞음. 둘 다 맞거나 둘 다 틀린 항목은 정보가 없다.
    n이 작으므로 정확 이항검정을 쓴다(카이제곱 근사 대신).
    """
    b = sum(1 for x, y in zip(a_ok, b_ok) if x and not y)
    c = sum(1 for x, y in zip(a_ok, b_ok) if y and not x)
    n = b + c
    if n == 0:
        return b, c, 1.0
    k = min(b, c)
    p = 2.0 * sum(math.comb(n, i) for i in range(k + 1)) / (2.0 ** n)
    return b, c, min(1.0, p)


def risk_coverage(scores, labels, steps=6, verdicts=None, strict=True, band=0.02):
    """확신이 높은 순으로 잘라가며 정확도를 본다.

    좋은 시스템은 확신이 높을수록 정확해야 한다. 그렇지 않다면
    그 확률값은 순서 정보조차 담고 있지 않은 것이다.

    주의: **판정을 무시하고 점수만 쓰면 안 된다.**
      `보류 60%`는 시스템이 판단을 유보한 것인데 점수만 보면 양성 예측이 된다.
      선택적 예측 표는 판정으로 가르는데 여기만 점수로 가르면 두 표가
      서로 다른 것을 재게 된다. 기권 항목은 빼고 본다.
    """
    if verdicts:
        idx = [i for i, (v, s) in enumerate(zip(verdicts, scores))
               if predict_verdict(v, s, strict, band) is not None]
    else:
        idx = list(range(len(scores)))
    if not idx:
        return []
    order = sorted(idx, key=lambda i: -abs(scores[i] - 0.5))
    out = []
    for f in [i / steps for i in range(1, steps + 1)]:
        k = max(1, int(len(order) * f))
        sel = order[:k]
        acc = sum(1 for i in sel
                  if (scores[i] > 0.5) == (labels[i] == 1)) / k
        out.append((f, k, acc))
    return out


def binom_p(k, n, p0=0.5):
    """양측 이항검정. 기준 비율 p0는 호출부가 데이터에서 정한다."""
    if n == 0:
        return 1.0

    def pmf(i):
        return math.comb(n, i) * (p0 ** i) * ((1 - p0) ** (n - i))

    obs = pmf(k)
    return min(1.0, sum(pmf(i) for i in range(n + 1) if pmf(i) <= obs * (1 + 1e-9)))



def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="?", default="bench_results.json")
    ap.add_argument("--band", type=float, default=0.02,
                    help="판정이 없을 때 이 폭 안은 기권으로 본다")
    ap.add_argument("--loose", action="store_true",
                    help="조건부를 기권이 아니라 확률 방향으로 해석한다")
    a = ap.parse_args(argv)

    d = json.load(open(a.results, encoding="utf-8"))
    rows = d["rows"]
    labels = [1 if r["label"] == "TP" else 0 for r in rows]
    res = d["results"]
    # 구성 목록을 하드코딩하면 새 구성을 추가할 때마다 잊는다.
    #   실제로 B6를 추가하고 여기를 안 고쳐 **조용히 무시**되고 있었다.
    #   결과 파일에 있는 것을 그대로 쓰되 자연 순서로만 정렬한다.
    def _key(k):
        return (0, int(k[1:])) if k[:1] == "B" and k[1:].isdigit() else (1, 0, k)
    order = sorted(res.keys(), key=_key)

    print("=" * 78)
    print("재분석 — 기권을 인정하는 틀")
    print("  층 %s · TP %d · TN %d" % (d.get("stratum", "?"), d["n_tp"], d["n_tn"]))
    print("=" * 78)

    print("\n[선택적 예측] 적게 말하고 정확한 것도 실력이다")
    print("  기권 기준: 보류·모름%s. 점수가 아니라 **판정**으로 가른다."
          % ("" if a.loose else " + 조건부"))
    print("  %-4s %-12s %-24s %s" % ("구성", "커버리지", "선택 정확도 [95% CI]", "판단 건수"))
    print("  " + "-" * 70)
    ok = {}
    for k in order:
        sc = res[k]["scores"]
        vd = res[k].get("verdicts")
        cov, acc, n = selective(sc, labels, a.band, vd, strict=not a.loose)
        ok[k] = [predict_verdict(v, s, not a.loose, a.band) == lb
                 for v, s, lb in zip(vd or [None] * len(sc), sc, labels)]
        if acc is None:
            print("  %-4s 판단 없음" % k)
            continue
        lo, hi = wilson(round(acc * n), n)
        print("  %-4s %-12s %-24s %d/%d"
              % (k, "%.0f%%" % (100 * cov),
                 "%.0f%%  [%.0f–%.0f%%]" % (100 * acc, 100 * lo, 100 * hi),
                 n, len(sc)))

    print("\n[짝지은 검정] 같은 항목을 두 구성이 함께 풀었다")
    print("  독립 AUROC 비교는 이 설계에서 검정력을 버린다. McNemar를 쓴다.")
    pairs_test = [(x, y) for i, x in enumerate(order) for y in order[i + 1:]]
    n_tests = len(pairs_test) + max(0, len(order) - 1)   # McNemar + 미지영역 이항
    bonf = 0.05 / max(1, n_tests)
    for x, y in pairs_test:
        b, c, p = mcnemar(ok[x], ok[y])
        # 여러 번 검정한 뒤 하나 유의한 것은 우연으로 나온다.
        # 보정 전후를 함께 적어 과대 주장을 막는다.
        if p < bonf:
            verdict = "유의(보정 후에도)"
        elif p < 0.05:
            verdict = "**보정 전만** 유의 — 주장 근거로 쓸 수 없다"
        elif b + c < 10:
            verdict = "판단 불가(불일치 %d건뿐)" % (b + c)
        else:
            # ── **«차이 없음» 을 상수로 박으면 안 된다** (결함 151) ────
            #
            #   `CLAUDE.md §4`: *"`p ≥ 0.05` 를 적을 때는 **항상 검정력을
            #   같이** 적는다. «유의하지 않다»는 «차이가 없다»가 아니다."*
            #
            #   `pk.py:146-155` 는 이 규칙을 지킨다. **이 파일만 안 지켰고,
            #   이게 심사위원이 볼 주 재분석기다.** 실측 검정력은 14~17%
            #   였다 — 그 표본으로 «차이 없다» 는 말할 수 없다.
            n_pair = len(ok[x])
            pw = power1(0.5, (b / (b + c)) if (b + c) else 0.5, b + c)
            verdict = ("**모른다** (차이 없음이 아니다) · 검정력 %.0f%%"
                       % (100 * pw))
        print("  %-3s vs %-3s : %s만 %2d · %s만 %2d · p=%.3f  → %s"
              % (x, y, x, b, y, c, p, verdict))
    print("  다중비교 보정: 검정 %d개 → Bonferroni 임계값 %.4f" % (n_tests, bonf))
    print("  주의: 기권은 '맞음'이 아니다. 커버리지가 낮으면 이 검정에서 불리하다.")
    print("        '정답을 더 많이 낸다'는 것이지 '판단이 더 정확하다'가 아니다.")

    print("\n[위험-커버리지] 확신이 높을수록 정확한가")
    # 설명이 거꾸로 적혀 있었다. **왼쪽(확신 상위)이 높고 오른쪽으로 갈수록
    #   내려가는 것이 정상이다.** 확신이 높은 것부터 맞혀야 하니까.
    #   반대로 왼쪽이 낮으면 확신이 거꾸로 붙은 것이고, 그건 정보가 없는 게
    #   아니라 **정보가 뒤집힌 것**이라 더 나쁘다.
    print("  왼쪽 = 확신 상위. **왼쪽이 높고 오른쪽으로 내려가야 정상이다.**")
    print("  왼쪽이 더 낮으면 확신이 거꾸로 붙은 것 — 정보가 없는 게 아니라 뒤집혔다.")
    print("  (기권 항목은 제외한다. 선택적 예측 표와 같은 기준이어야 한다)")
    hdr = "  %-4s" % "구성"
    for f in [i / 6 for i in range(1, 7)]:
        hdr += " %6s" % ("%d%%" % (100 * f))
    print(hdr + "   판단수")
    flip = []
    for k in order:
        rc = risk_coverage(res[k]["scores"], labels, 6,
                           res[k].get("verdicts"), strict=not a.loose, band=a.band)
        line = "  %-4s" % k
        for _, _, acc in rc:
            line += " %6s" % ("%.0f%%" % (100 * acc))
        n_judged = rc[-1][1] if rc else 0
        print(line + "   %d" % n_judged)
        # 사람이 표를 눈으로 읽고 방향을 판단하게 두면 틀린다. 직접 말해준다.
        if len(rc) >= 2 and rc[-1][2] - rc[0][2] > 0.05:
            flip.append((k, rc[0][2], rc[-1][2], n_judged))
    for k, top, allc, n in flip:
        print("  [경고] %s — 확신 상위 %.0f%% < 전체 %.0f%%. **확신이 거꾸로 붙었다.**"
              % (k, 100 * top, 100 * allc))
        print("         가장 확신한 판단이 가장 많이 틀렸다는 뜻이다.")
        if n < 10:
            print("         다만 판단 %d건뿐이라 이것만으로 단정할 수 없다." % n)
        else:
            print("         Platt 보정을 걸어야 할 지점이다. 확률값을 그대로 쓰면 안 된다.")

    # 판정 분포
    print("\n[판정 분포]")
    for k in order:
        v = res[k].get("verdicts") or []
        if not v:
            continue
        cnt = {}
        for x in v:
            cnt[x] = cnt.get(x, 0) + 1
        print("  %-4s %s" % (k, " · ".join("%s %d" % (a_, b_)
                                           for a_, b_ in sorted(cnt.items(),
                                                                key=lambda t: -t[1]))))

    # ═══════════════════════════════════════════════════════════
    # 결정적 분석 — 모델이 모르는 영역
    #
    #   B0의 높은 선택 정확도는 **모델이 안다고 답한 것들**에서 나온다.
    #   그건 기억의 정확도이지 추론의 정확도가 아니다.
    #   파이프라인의 존재 이유는 모델이 모르는 영역에서 문헌을 읽어
    #   답을 내는 것이다. 전체 평균으로 비교하면 그 효과가 기억 영역에
    #   희석돼 사라진다. 반드시 나눠서 봐야 한다.
    # ═══════════════════════════════════════════════════════════
    if "B0" in res and res["B0"].get("verdicts"):
        b0v = res["B0"]["verdicts"]
        unknown = [i for i, v in enumerate(b0v) if v in ABSTAIN]
        known = [i for i, v in enumerate(b0v) if v not in ABSTAIN]
        print("\n[결정적 분석] 모델이 모르는 영역에서 파이프라인이 값을 하는가")
        print("  B0가 '모름'이라 답한 %d건 — 여기가 파이프라인의 존재 이유다." % len(unknown))
        print("  %-4s %-10s %-24s %s" % ("구성", "커버리지", "정확도 [95% CI]", "우연 대비"))
        print("  " + "-" * 70)
        for k in order:
            if k == "B0":
                continue
            sc = [res[k]["scores"][i] for i in unknown]
            vd = [res[k]["verdicts"][i] for i in unknown] if res[k].get("verdicts") else None
            lb = [labels[i] for i in unknown]
            cov, acc, n = selective(sc, lb, a.band, vd, strict=not a.loose)
            if acc is None or n == 0:
                print("  %-4s 판단 없음" % k)
                continue
            hits = round(acc * n)
            lo, hi = wilson(hits, n)
            # 기준선은 50%가 아니라 **이 부분집합의 다수클래스**다.
            #   B0가 답한 항목이 TP 쪽에 쏠려 있으면 남은 집단은 50:50이 아니다.
            #   50%로 검정하면 p값을 유리하게 보고하게 된다.
            base = max(sum(lb), len(lb) - sum(lb)) / len(lb)
            pv = binom_p(hits, n, base)
            mark = ("다수클래스(%.0f%%)보다 높음 p=%.3f" % (100 * base, pv)
                    if pv < 0.05 and acc > base
                    else "다수클래스(%.0f%%)와 구별 불가 p=%.3f" % (100 * base, pv))
            print("  %-4s %-10s %-24s %s"
                  % (k, "%.0f%%" % (100 * cov),
                     "%.0f%% (%d/%d) [%.0f–%.0f%%]" % (100 * acc, hits, n, 100 * lo, 100 * hi),
                     mark))
        print("")
        print("  참고 — B0가 '안다'고 답한 %d건(기억 영역):" % len(known))
        for k in order:
            sc = [res[k]["scores"][i] for i in known]
            vd = [res[k]["verdicts"][i] for i in known] if res[k].get("verdicts") else None
            lb = [labels[i] for i in known]
            cov, acc, n = selective(sc, lb, a.band, vd, strict=not a.loose)
            if acc is not None and n:
                print("    %-4s 커버리지 %3.0f%% · 정확도 %3.0f%% (%d/%d)"
                      % (k, 100 * cov, 100 * acc, round(acc * n), n))
        print("")
        print("  이 두 영역을 합쳐서 보면 안 된다. 기억 영역의 높은 정확도가")
        print("  미지 영역의 성적을 가려 버린다.")

    print("\n" + "=" * 78)
    print("해석 지침")
    print("  · 커버리지가 낮으면 선택 정확도가 높아도 실용성이 떨어진다. 둘을 같이 본다.")
    print("  · McNemar 불일치 건수가 10건 미만이면 어느 쪽도 주장할 수 없다.")
    print("  · 표본이 작다. 유의하지 않은 차이를 '경향'이라 부르지 않는다.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
