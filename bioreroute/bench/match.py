# -*- coding: utf-8 -*-
"""TP–TN 짝 맞추기 + 층 분리.

두 가지 교란을 동시에 막는다.

① **문헌량 교란**
   TP(승인약)는 유명하고 TN(실패 시험)은 무명이다. 그대로 비교하면 분류기가
   근거의 질이 아니라 **문헌이 많은지 적은지**만 보고 갈라낼 수 있다.
   AUROC가 높게 나와도 그건 시스템 능력이 아니다.
   → PubMed 문헌량이 비슷한 것끼리 짝짓는다.

② **사전학습 누출**
   HCQ·이버멕틴이 COVID에 실패한 건 어떤 LLM이든 학습 데이터로 안다.
   문헌을 읽어서 맞힌 건지 외워서 맞힌 건지 구분할 수 없다.
   → 문헌량 상위를 층 B(유명)로 떼어내고, 주 지표는 층 A로만 낸다.
     층 B는 부차 지표로 보고하되 누출 가능성을 명시한다.

실행: py -m bioreroute.bench.match bench_labels.csv
"""

import argparse
import csv
import json
import math
import random
import re
import sys
import time

from ..io import sources
from . import query as Q


LOOSE = False


def query_of(drug: str, ind: str) -> str:
    """본 측정(bench.run)과 **완전히 같은** 질의를 쓴다.

    예전에는 여기만 따옴표 엄격 질의였다. 그러면 문헌량을 A 기준으로 맞춰놓고
    실제로는 B 기준 문헌을 읽게 되어, 교란을 통제했다고 말할 수 없다.
    """
    return Q.pair(drug, ind)


HITS = {"cache": 0, "fetch": 0}


def count_for(drug, ind, cache):
    key = "CNT::" + query_of(drug, ind)
    if key in cache:
        HITS["cache"] += 1
        return cache[key]
    HITS["fetch"] += 1
    r = sources.pubmed_search(query_of(drug, ind), retmax=1)
    n = None if r.get("error") else (r.get("count") or 0)
    cache[key] = n
    return n


def bucket(n):
    """log10 구간. 0건과 결측을 구분한다."""
    if n is None:
        return None
    return 0 if n <= 0 else int(math.log10(n)) + 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("labels", nargs="?", default="bench_labels.csv")
    ap.add_argument("--verified", default="", help="ctgov 검증 결과가 있으면 그걸 쓴다")
    ap.add_argument("--pool", type=int, default=400, help="TP 후보 표본 수")
    ap.add_argument("--famous", type=int, default=500,
                    help="이 문헌량 이상은 층 B(유명, 누출 위험)")
    ap.add_argument("--cache", default="bench_counts.json")
    ap.add_argument("--out", default="bench_matched.csv")
    ap.add_argument("--seed", type=int, default=20260803)
    ap.add_argument("--loose", action="store_true", help="질의 완화(0건이 많을 때)")
    a = ap.parse_args(argv)
    global LOOSE
    LOOSE = a.loose

    # **PubMed 캐시를 반드시 먼저 읽는다.**
    #
    #   `--cache` 는 *문헌량* 캐시(bench_counts.json)이고, 그것과 별개로
    #   `sources.pubmed_*` 는 `io.cache` 모듈(`pubmed_cache.json`)을 쓴다.
    #   여기서 `cache.load()` 를 부르지 않으면 `_STORE` 가 **빈 dict** 로
    #   시작하고, 실행 끝의 `save()` 가 이번에 받은 것만 써서
    #   **기존 캐시를 통째로 덮는다.**
    #
    #   실제로 당했다 — 2026-08-05 홀드아웃 짝짓기에서 2.7MB(초록·등록부
    #   본문·PubChem 동의어)가 SEARCH 580개만 남기고 사라졌다. 백업이
    #   없었다. 측정 결과 파일은 무사했지만 **그 시점의 문헌 상태를 고정할
    #   수단을 잃었다** — PubMed은 시간이 지나면 내용이 바뀐다.
    from ..io import cache as _cache
    _cache.configure("pubmed_cache.json")
    _cache.load()

    rows = list(csv.DictReader(open(a.labels, encoding="utf-8-sig")))
    tn = [r for r in rows if r["label"] == "TN"]
    tp_all = [r for r in rows if r["label"] == "TP"]

    if a.verified:
        from . import review
        keep, rescued, years = set(), [], {}
        for r in csv.DictReader(open(a.verified, encoding="utf-8-sig")):
            k = (r["drug"], r["indication"])
            if r.get("ctgov_year"):
                years[k] = r["ctgov_year"]      # Tier 2 시점 차단에 쓴다
            v = r.get("ctgov_verdict")
            if v == "유지":
                keep.add(k)
            elif v == "확인필요":
                # 자동 폐기하면 안 된다. 사람 판정이 있으면 그걸 따른다.
                d = review.lookup(r["drug"], r["indication"])
                if d and d[0] == "유지":
                    keep.add(k)
                    rescued.append(k)
        before = len(tn)
        tn = [r for r in tn if (r["drug"], r["indication"]) in keep]
        for r in tn:
            r["ctgov_year"] = years.get((r["drug"], r["indication"]), "")
        print("CT.gov 검증 반영: TN %d → %d" % (before, len(tn)))
        got = sum(1 for r in tn if r.get("ctgov_year"))
        print("  시점 차단용 종료 연도 확보: %d/%d" % (got, len(tn)))
        if rescued:
            print("  사람 판정으로 복원 %d건 (CT.gov '확인필요'였으나 진짜 TN):" % len(rescued))
            for d_, i_ in rescued:
                print("    %-24s %s" % (d_[:24], i_[:34]))

    try:
        cache = json.load(open(a.cache, encoding="utf-8"))
    except Exception:
        cache = {}

    print("=" * 76)
    print("문헌량 조사 — TN %d건" % len(tn))
    print("=" * 76)
    for i, r in enumerate(tn, 1):
        r["pubmed"] = count_for(r["drug"], r["indication"], cache)
        if i % 10 == 0 or i == len(tn):
            print("  %d/%d" % (i, len(tn)))
            json.dump(cache, open(a.cache, "w", encoding="utf-8"), ensure_ascii=False)

    n_err = sum(1 for r in tn if r["pubmed"] is None)
    n_zero = sum(1 for r in tn if r["pubmed"] == 0)
    tn = [r for r in tn if r["pubmed"] is not None]
    if n_err or n_zero:
        print("\n  [점검] 조회 실패 %d건 · 0건 반환 %d건" % (n_err, n_zero))
        if n_err:
            print("     실패는 조용히 버려진다. 네트워크나 NCBI 차단을 의심하라.")
        if n_zero > len(tn) * 0.3:
            print("     0건이 30%%를 넘는다. 질의가 너무 엄격할 수 있다(따옴표 구문).")
            print("     그러면 층 분리·짝짓기가 무의미해진다.")
    strat_a = [r for r in tn if r["pubmed"] < a.famous]
    strat_b = [r for r in tn if r["pubmed"] >= a.famous]

    got = sorted(r["pubmed"] for r in tn)
    if got:
        q = lambda p: got[min(len(got) - 1, int(len(got) * p))]
        print("\n  [문헌량 분포] 최소 %d · 25%% %d · 중앙 %d · 75%% %d · 최대 %d"
              % (got[0], q(.25), q(.5), q(.75), got[-1]))
        print("  0건 %d · 10건 미만 %d / 총 %d"
              % (sum(1 for x in got if x == 0), sum(1 for x in got if x < 10), len(got)))

    print("\n[TN 층 분리]  기준: 문헌 %d건" % a.famous)
    print("  층 A (저문헌) %3d건 — 주 지표" % len(strat_a))
    print("  층 B (고문헌) %3d건 — 부차 지표" % len(strat_b))
    print("  주의: 문헌량은 '그 실패가 유명한가'의 대리 지표가 못 된다.")
    print("        gabapentin/Pain은 문헌이 많아도 그 futility 시험은 무명이고,")
    print("        HCQ/COVID는 실패 자체가 뉴스였다. 누출은 문헌량이 아니라")
    print("        폐쇄형 질의(bench.run --closedbook)로 직접 측정한다.")
    if strat_b:
        print("  층 B 목록:")
        for r in sorted(strat_b, key=lambda x: -x["pubmed"])[:10]:
            print("    %-22s %-28s %6d건" % (r["drug"][:22], r["indication"][:28], r["pubmed"]))

    # ── TP 표본 조사 ──────────────────────────────────────────
    random.seed(a.seed)
    pool = random.sample(tp_all, min(a.pool, len(tp_all)))
    print("\n문헌량 조사 — TP 표본 %d건" % len(pool))
    for i, r in enumerate(pool, 1):
        r["pubmed"] = count_for(r["drug"], r["indication"], cache)
        if i % 25 == 0 or i == len(pool):
            print("  %d/%d" % (i, len(pool)))
            json.dump(cache, open(a.cache, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(cache, open(a.cache, "w", encoding="utf-8"), ensure_ascii=False)
    pool = [r for r in pool if r["pubmed"] is not None]

    # ── 짝짓기: 같은 log10 구간에서, 같은 약은 재사용하지 않는다 ──
    by_b = {}
    for r in pool:
        by_b.setdefault(bucket(r["pubmed"]), []).append(r)
    for v in by_b.values():
        random.shuffle(v)

    matched, used_drug, unmatched = [], set(), []
    for r in tn:
        b = bucket(r["pubmed"])
        cand = None
        for db in (0, 1, -1, 2, -2):            # 같은 구간 → 인접 구간 순
            for c in by_b.get(b + db, []):
                if c.get("_used") or c["drug"].lower() in used_drug:
                    continue
                cand = c
                break
            if cand:
                break
        if cand is None:
            unmatched.append(r)
            continue
        cand["_used"] = True
        used_drug.add(cand["drug"].lower())
        r["stratum"] = "B" if r["pubmed"] >= a.famous else "A"
        cand["stratum"] = r["stratum"]
        cand["matched_to"] = "%s|%s" % (r["drug"], r["indication"])
        matched += [r, cand]

    print("\n[짝짓기]")
    print("  성사 %d쌍 · 실패 %d건" % (len(matched) // 2, len(unmatched)))
    if unmatched:
        print("  짝 못 찾은 TN (문헌량 구간에 TP가 없음):")
        for r in unmatched[:6]:
            print("    %-22s %-26s %6d건" % (r["drug"][:22], r["indication"][:26], r["pubmed"]))

    pairs = [(matched[i], matched[i + 1]) for i in range(0, len(matched), 2)]
    for lab, sel in (("A", [p for p in pairs if p[0]["stratum"] == "A"]),
                     ("B", [p for p in pairs if p[0]["stratum"] == "B"])):
        if not sel:
            continue
        # 절대값만 보면 방향을 숨긴다. TP가 체계적으로 많으면 교란이 그대로
        # 남는데 |차이| 지표는 같게 나온다. 부호 있는 평균을 반드시 함께 본다.
        d_sign = [math.log10(max(y["pubmed"], 1)) - math.log10(max(x["pubmed"], 1))
                  for x, y in sel]          # TP − TN
        d_abs = [abs(v) for v in d_sign]
        mean_s = sum(d_sign) / len(d_sign)
        print("  층 %s: %d쌍 · |차이| %.2f · 부호평균(TP−TN) %+.2f"
              % (lab, len(sel), sum(d_abs) / len(d_abs), mean_s))
        if abs(mean_s) > 0.15:
            print("     → 한쪽으로 %.1f배 치우쳤다. 문헌량 교란이 남아 있다."
                  % (10 ** abs(mean_s)))
        else:
            print("     → 편향 없음(부호평균 0에 가깝다). 짝짓기 성공.")

    print("\n  [조회 내역] 신규 %d회 · 캐시 %d회" % (HITS["fetch"], HITS["cache"]))
    if HITS["fetch"] and HITS["cache"] > HITS["fetch"]:
        print("     캐시 적중이 많아 빨랐던 것이다. 정상이다.")

    fields = ["label", "stratum", "drug", "indication", "kind", "phase", "pubmed",
              "nct", "ctgov_year", "why", "detail", "matched_to"]
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(matched)

    print("\n저장: %s  (%d행)" % (a.out, len(matched)))
    print("=" * 76)
    print("주의: 층 A만으로 주 지표를 낸다. 층 B는 사전학습 누출 가능성을 명시하고")
    print("      부차 지표로만 보고한다. 이걸 섞으면 시스템 능력이 아니라")
    print("      모델 기억력을 재게 된다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
