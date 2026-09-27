# -*- coding: utf-8 -*-
"""약물동태 관문 — **투과성 주석이 TN에 편중되는가.**

`metformin / 유방암` 시연에서 나온 물음이다. Ro5는 상한만 있어서 운반체
의존 약물에 `PASS` 를 준다(결함 17). 그렇다면 이런 물음이 선다 —

> 재창출 실패의 일부는 표적이 틀린 것이 아니라 **약이 거기 못 간 것**인가?

**교란을 먼저 적는다.** TP는 그 적응증으로 *승인된* 약이다. 승인됐다는 것은
이미 도달성 시험을 통과했다는 뜻이므로 **편중은 어느 정도 당연하다.**
그러므로 이 수치는 인과가 아니라 **기술 통계**다. 다만 임상시험 실패의
대부분은 전달이 아니라 효능·표적 문제로 알려져 있으므로, 편중의 *크기*는
정보를 준다.

LLM을 쓰지 않는다. SMILES는 캐시에서 오고 계산은 전부 국소적이다.

사용법
  py -m bioreroute.bench.pk bench_matched.csv --stratum A
"""

import argparse
import csv
import sys
from collections import Counter

from ..io import cache, sources
from .stats import fisher, mde, power2, wilson




def flag(drug):
    """(등급, 사유목록, 상태). 등급은 강 / 약 / "" — 상태는 ok / skip / error."""
    r = sources.s2_properties(drug)
    if not r:
        return "", [], "error"
    if r.get("status") in ("SKIP", "ERROR"):
        return "", [], ("skip" if r.get("status") == "SKIP" else "error")
    return r.get("caveat_tier") or "", r.get("caveat_reasons") or [], "ok"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("matched", nargs="?", default="bench_matched.csv")
    ap.add_argument("--cache", default="pubmed_cache.json")
    ap.add_argument("--out", default="bench_pk.csv")
    ap.add_argument("--stratum", default="A",
                    help="A | B | all — bench.run 과 반드시 같아야 한다")
    a = ap.parse_args(argv)

    cache.configure(a.cache)
    cache.load()

    rows = [r for r in csv.DictReader(open(a.matched, encoding="utf-8-sig"))
            if a.stratum == "all" or r.get("stratum") == a.stratum]
    if not rows:
        print("해당 층에 행이 없다. --stratum 을 확인하라.")
        return 1

    print("=" * 78)
    print("투과성 관문 — 층 %s · %d행 (LLM 미사용)" % (a.stratum, len(rows)))
    print("=" * 78)
    print("Ro5는 상한만 있어 운반체 의존 약물에 PASS를 준다(결함 17).")
    print("여기서는 그 주석이 **TN 쪽에 편중되는지**만 본다.\n")

    got = {"TN": Counter(), "TP": Counter()}      # 강 / 약 / 없음 / 계산불가
    why = {"TN": Counter(), "TP": Counter()}      # 어떤 작용기가 걸렸나
    lost = {"TN": [], "TP": []}                   # SMILES 취득 실패 — 라벨별로
    out = []
    seen = {}
    for r in rows:
        drug, lab = r["drug"], r["label"]
        if drug not in seen:
            seen[drug] = flag(drug)
            sys.stdout.write("."); sys.stdout.flush()
        tier, reasons, st = seen[drug]
        if st != "ok":
            got[lab]["계산불가"] += 1
            lost[lab].append(drug)
            out.append([drug, r.get("disease", ""), lab, st, "", ""])
            continue
        got[lab][tier or "없음"] += 1
        for n in reasons:
            why[lab][n.split("(")[0]] += 1
        out.append([drug, r.get("disease", ""), lab, "ok", tier,
                    " · ".join(reasons)])
    print("\n")

    if all(g["강"] + g["약"] + g["없음"] == 0 for g in got.values()):
        print("!" * 78)
        print("[중단] 한 행도 계산하지 못했다. RDKit이 필요하다.  pip install rdkit")
        print("!" * 78)
        return 1

    # ── SMILES 취득 실패는 **라벨별로** 보고해야 한다 ────────────────────
    #   한 줄로 "5행 실패"라고만 적으면 그 5행이 어느 쪽인지 숨는다.
    #   생물학적 제제(항체·인터페론)는 SMILES가 없어 전부 여기로 빠지는데,
    #   **그것들이야말로 막을 못 넘는 극단**이다. 한쪽에 몰리면 편향이다.
    if any(lost.values()):
        print("[주의] SMILES 취득 실패 — 분모에서 빠졌다")
        for lab in ("TN", "TP"):
            if lost[lab]:
                # **자르지 마라.** 앞서 58자에서 잘려 5건 중 1건이 숨었다.
                #   결측 목록은 그 자체가 편향 진단 자료다.
                print("   %s %2d건: %s" % (lab, len(lost[lab]),
                                           ", ".join(sorted(set(lost[lab])))))
        if bool(lost["TN"]) != bool(lost["TP"]):
            print("   ** 한쪽에만 발생했다. 생물학적 제제라면 이 탈락은")
            print("      투과성 제한이 가장 큰 것들을 지운 것이므로 **편향이다.**")
        print("")

    print("%-6s %6s %6s %6s %6s   %s"
          % ("라벨", "강", "약", "없음", "불가", "강 비율 [95% CI]"))
    print("-" * 78)
    for lab in ("TN", "TP"):
        g = got[lab]
        n = g["강"] + g["약"] + g["없음"]
        lo, hi = wilson(g["강"], n)
        print("%-6s %6d %6d %6d %6d   %5.1f%%  [%.0f–%.0f%%]"
              % (lab, g["강"], g["약"], g["없음"], g["계산불가"],
                 100 * g["강"] / n if n else 0, 100 * lo, 100 * hi))

    print("\n[걸린 작용기]")
    for lab in ("TN", "TP"):
        items = " · ".join("%s %d" % (k, v) for k, v in why[lab].most_common())
        print("  %s  %s" % (lab, items or "없음"))

    for tier in ("강", "약"):
        a_n = got["TN"]["강"] + got["TN"]["약"] + got["TN"]["없음"]
        b_n = got["TP"]["강"] + got["TP"]["약"] + got["TP"]["없음"]
        if not (a_n and b_n):
            continue
        a_k, b_k = got["TN"][tier], got["TP"][tier]
        p = fisher(a_k, a_n - a_k, b_k, b_n - b_k)
        ra, rb = a_k / a_n, b_k / b_n
        # **방향을 데이터에서 읽는다.** 문구를 고정하면 부호가 뒤집혀도
        #   못 알아챈다 — 위험-커버리지 설명에서 이미 한 번 당했다(결함 8).
        if p >= 0.05:
            verdict = "차이를 주장할 수 없다"
        elif ra > rb:
            verdict = "**TN 쪽에 편중** (실패 쪽에 더 많다)"
        else:
            verdict = "**TP 쪽에 편중** (승인 쪽에 더 많다 — 가설과 반대 방향)"
        print("\n[%s 등급] TN %.0f%% vs TP %.0f%% · Fisher p=%.3f → %s"
              % (tier, 100 * ra, 100 * rb, p, verdict))
        # **검정력을 반드시 같이 적는다.** 안 적으면 "유의하지 않다"가
        #   "차이가 없다"로 읽힌다. 이 표본은 웬만한 차이를 못 잡는다.
        if p >= 0.05:
            pw = power2(ra, rb, a_n, b_n)
            m = mde(min(ra, rb), a_n, b_n)
            msg = ("   검정력 %.0f%% — 이 표본으로는 " % (100 * pw))
            msg += ("%.0f%% 대 %.0f%% 정도로 벌어져야 잡힌다."
                    % (100 * min(ra, rb), 100 * m)) if m else "어떤 차이도 잡기 어렵다."
            print(msg)
            print("   → **'차이가 없다'가 아니라 '모른다'이다.**")

    print("\n" + "=" * 78)
    print("교란 — 이 수치를 인과로 읽으면 안 된다")
    print("=" * 78)
    print("① TP는 그 적응증으로 **승인된** 약이다. 승인은 도달성 시험을 이미")
    print("   통과했다는 뜻이므로 두 군은 애초에 대등한 비교 대상이 아니다.")
    print("② SMARTS는 **작용기 존재**만 본다. 실제 pKa·운반체 기질성을 재지")
    print("   않는다. 등급 '약'은 특히 약한 신호다(중성분율이 있다).")
    print("③ 생물학적 제제는 SMILES가 없어 아예 빠진다. 위 [주의]를 보라.")
    print("이 표는 **기술 통계**이지 '전달 실패가 재창출 실패의 원인'이라는")
    print("주장이 아니다. 그 주장을 하려면 실패 사유가 기록된 자료가 필요하다.")

    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["drug", "disease", "label", "status", "tier", "reasons"])
        w.writerows(out)
    cache.save()
    print("\n저장: %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
