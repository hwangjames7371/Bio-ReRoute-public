# -*- coding: utf-8 -*-
"""TP 라벨 검증 — 비대칭 정제는 그 자체가 편향이다.

TN은 4단으로 정제했다(자동필터 → CT.gov → 승인교차 → 사람판정).
**TP는 RepoDB `Approved`를 그대로 썼다. 검증 0단이다.**

한쪽만 깨끗하게 만들면 그 차이가 성능으로 보인다. 두 가지를 검사한다.

① **확증 근거가 문헌에 존재하는가**
   1962년 효능 요건 도입 이전 승인 약물은 RCT 없이 승인됐다.
   그런 TP는 문헌을 아무리 읽어도 확증 근거가 안 나온다.
   시스템이 `보류`를 내는 게 **정답**인데 오답으로 세어진다.
   → PubMed 출판유형 필터로 RCT·메타분석 존재 여부를 센다. LLM 없이, 객관적으로.

② **승인이 나중에 철회됐는가**
   베바시주맙/유방암처럼 승인 후 효능 미입증으로 철회된 쌍은
   TP가 아니라 TN이다. RepoDB는 철회를 반영하지 않는다.

이건 라벨 청소이지 시스템 평가가 아니다. 표시만 하고 사람이 확인한다.

실행: py -m bioreroute.bench.tp_audit bench_matched.csv
"""

import argparse
import csv
import sys

from ..io import cache, llm, sources
from . import query as Q

# 확증 설계 출판유형. PubMed가 사람 손으로 색인한 값이라 LLM 추정보다 낫다.
CONFIRMATORY_PT = ('"randomized controlled trial"[pt] OR "meta-analysis"[pt] '
                   'OR "systematic review"[pt]')

SYSTEM = "당신은 규제 이력에 밝은 약사다. 확실하지 않으면 모른다고 답한다."

HEAD = """아래 약물-적응증 쌍 {n}개 각각에 대해 답하라.

묻는 것은 둘이다.
1. 그 적응증 승인이 이후 **철회·취소**된 적이 있는가.
   (예: 베바시주맙의 전이성 유방암 적응증은 2011년 FDA가 철회했다)
2. 최초 승인이 대략 **1962년 이전**인가.
   (1962년 이전 승인 약물은 효능 입증 요건 이전이라 RCT 근거가 없을 수 있다)

확실하지 않으면 반드시 "모름"이라고 답하라. 추측하지 마라.

"""

TAIL = """
JSON 배열만 출력하라. 원소 {n}개, 위 순서 그대로.
[{{"idx": 1, "withdrawn": "예|아니오|모름", "pre1962": "예|아니오|모름",
   "note": "근거 한 문장 (없으면 빈 문자열)"}}]"""


def evidence_counts(drug, indication, cache_hits):
    """확증 설계 문헌이 존재하는가. LLM 없이 PubMed 색인으로만 센다."""
    base = Q.pair(drug, indication)
    key = "TPEV::" + base
    if cache.has(key):
        cache_hits[0] += 1
        return cache.get(key)
    out = {"all": None, "confirmatory": None, "error": None}
    r_all = sources.pubmed_search(base, 1)
    if r_all.get("error"):
        out["error"] = r_all["error"]
        return cache.put(key, out)
    out["all"] = r_all.get("count") or 0
    r_c = sources.pubmed_search("(%s) AND (%s)" % (base, CONFIRMATORY_PT), 1)
    out["confirmatory"] = None if r_c.get("error") else (r_c.get("count") or 0)
    return cache.put(key, out)


def probe(pairs, chunk=12):
    out = [None] * len(pairs)
    for s in range(0, len(pairs), chunk):
        part = pairs[s:s + chunk]
        body = "\n".join("%d. %s / %s" % (i + 1, p["drug"], p["indication"])
                         for i, p in enumerate(part))
        r = llm.complete(HEAD.format(n=len(part)) + body + "\n" + TAIL.format(n=len(part)),
                         system=SYSTEM, as_json=True,
                         purpose="tp_audit")   # 계량 — 감사 도구(파이프라인 밖)
        data = r.get("data")
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), None)
        idx = {}
        if isinstance(data, list):
            for j, dd in enumerate(data):
                if isinstance(dd, dict):
                    try:
                        k = int(dd.get("idx", j + 1)) - 1
                    except Exception:
                        k = j
                    if 0 <= k < len(part):
                        idx[k] = dd
        for i in range(len(part)):
            dd = idx.get(i) or {}
            norm = lambda v: v if v in ("예", "아니오", "모름") else "모름"
            out[s + i] = {"withdrawn": norm(str(dd.get("withdrawn", "모름")).strip()),
                          "pre1962": norm(str(dd.get("pre1962", "모름")).strip()),
                          "note": str(dd.get("note", ""))[:100]}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("matched", nargs="?", default="bench_matched.csv")
    ap.add_argument("--cache", default="pubmed_cache.json")
    ap.add_argument("--out", default="bench_tp_audit.csv")
    ap.add_argument("--no-llm", action="store_true",
                    help="문헌 조사만 한다(무료). 철회·연대 검사는 건너뛴다")
    ap.add_argument("--stratum", default="A",
                    help="A | B | all — bench.run 과 반드시 같아야 한다")
    a = ap.parse_args(argv)

    cache.configure(a.cache)
    cache.load()
    # 층을 안 맞추면 **다른 모집단을 재게 된다.**
    #   ceiling에서 이미 같은 실수를 겪고 고쳤는데 이 파일에는 안 옮겼다.
    #   실측: TP 49건(전 층)을 쟀는데 bench.run은 42건(층 A)을 쓴다.
    #   "확증 근거 없는 TP 20%"가 실제로 돌리는 집합의 숫자가 아니었다.
    #   같은 실수를 세 번째 반복했다 — 교훈은 파일 단위로 새지 않는다.
    rows = [r for r in csv.DictReader(open(a.matched, encoding="utf-8-sig"))
            if r["label"] == "TP"
            and (a.stratum == "all" or r.get("stratum") == a.stratum)]
    if not rows:
        print("해당 층에 TP가 없다. --stratum 을 확인하라.")
        return 1

    print("=" * 78)
    print("TP 라벨 검증 — 층 %s · %d건" % (a.stratum, len(rows)))
    print("=" * 78)
    print("TN은 4단으로 정제했는데 TP는 0단이다. 비대칭 정제는 그 자체가 편향이다.")
    print("  ※ 이 층은 bench.run 의 --stratum 과 **같아야** 비교가 성립한다.\n")

    print("[① 확증 근거 존재 여부] PubMed 출판유형 색인 — LLM 없이 객관적으로")
    hits = [0]
    for i, r in enumerate(rows, 1):
        r["_ev"] = evidence_counts(r["drug"], r["indication"], hits)
        if i % 10 == 0 or i == len(rows):
            print("  %d/%d" % (i, len(rows)))
            cache.save()
    cache.save()

    ok = [r for r in rows if not r["_ev"].get("error")]
    none_conf = [r for r in ok if (r["_ev"]["confirmatory"] or 0) == 0]
    none_any = [r for r in ok if (r["_ev"]["all"] or 0) == 0]
    m = max(1, len(ok))
    print("\n  조회 성공 %d/%d" % (len(ok), len(rows)))
    print("  확증 설계 문헌 0건    %3d/%d = %.0f%%" % (len(none_conf), m,
                                                 100 * len(none_conf) / m))
    print("  문헌 자체가 0건       %3d/%d = %.0f%%" % (len(none_any), m,
                                                 100 * len(none_any) / m))
    if none_conf:
        print("\n  [확증 근거가 없는 TP] — 시스템이 '보류'를 내는 게 정답인 항목")
        for r in none_conf[:12]:
            print("    %-24s %-30s 전체 %s건"
                  % (r["drug"][:24], r["indication"][:30], r["_ev"]["all"]))
        if len(none_conf) > 12:
            print("    … 외 %d건" % (len(none_conf) - 12))
        print("\n  이 항목들을 '오답'으로 세면 시스템 성능이 부당하게 낮아진다.")
        print("  성능 보고 시 **확증 근거 있는 TP만**으로 낸 수치를 함께 제시해야 한다.")

    if not a.no_llm:
        print("\n[② 승인 철회·연대 검사] (LLM)")
        res = probe([{"drug": r["drug"], "indication": r["indication"]} for r in rows])
        cache.save()
        wd = [(r, x) for r, x in zip(rows, res) if x["withdrawn"] == "예"]
        old = [(r, x) for r, x in zip(rows, res) if x["pre1962"] == "예"]
        print("  승인 철회 표시  %d건 — TP가 아니라 TN일 수 있다" % len(wd))
        for r, x in wd[:10]:
            print("    %-24s %-28s %s" % (r["drug"][:24], r["indication"][:28],
                                          x["note"][:34]))
        print("  1962년 이전 승인 표시  %d건 — RCT 근거 없이 승인됐을 수 있다" % len(old))
        for r, x in old[:10]:
            print("    %-24s %-28s %s" % (r["drug"][:24], r["indication"][:28],
                                          x["note"][:34]))
        print("\n  주의: 이 표시는 선별 장치다. 승인 검증 때 도구가 환각 3건을 냈다.")
        print("        그대로 받지 말고 사람이 확인해야 한다.")
    else:
        res = [{"withdrawn": "", "pre1962": "", "note": ""} for _ in rows]

    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["drug", "indication", "stratum", "pubmed_all",
                    "pubmed_confirmatory", "withdrawn", "pre1962", "note", "error"])
        for r, x in zip(rows, res):
            e = r["_ev"]
            w.writerow([r["drug"], r["indication"], r.get("stratum", ""),
                        e.get("all"), e.get("confirmatory"), x["withdrawn"],
                        x["pre1962"], x["note"], e.get("error") or ""])
    print("\n저장: %s" % a.out)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
