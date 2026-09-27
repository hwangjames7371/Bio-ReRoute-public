# -*- coding: utf-8 -*-
"""누출 재검증 — 라벨 출처 시험의 **논문**이 근거로 들어왔는가. 무료.

`EXCLUDE_NCT` 는 **초록에 NCT 번호가 적힌** 논문만 막는다. 그런데 많은 논문이
등록번호를 초록에 안 쓴다(본문·메타데이터에만 있다). 그러면 **라벨 출처 시험의
결과 논문이 그대로 통과한다.**

  TN 라벨이 "NCT12345가 futility로 중단"에서 왔는데 그 시험의 논문을 읽고
  기각하면, 예측이 아니라 **답안지를 읽은 것**이다.

실측 정황: 기각한 TN 12건 중 4건에서 반박 문헌의 출판연도가 시험 종료연도와
**같았다.** 그 시험 자신의 보고서일 수 있다.

PubMed는 등록번호를 `[si]`(Secondary Source ID) 필드에 색인한다. 라벨 NCT로
검색해 나온 PMID가 우리가 쓴 근거에 있으면 **누출이 확정된다.**

한계 — `[si]` 색인은 논문이 등록번호를 명시했을 때만 걸린다. 즉 이 검사는
누출의 **하한**이다. 안 잡혔다고 없는 것이 아니다.

실행: py -m bioreroute.bench.leakcheck s84.json bench_matched.csv
"""

import argparse
import csv
import json
import sys

from ..io import cache, sources


def trial_papers(nct):
    """그 시험의 논문 PMID들. [si] 색인으로 찾는다."""
    key = "SIPMID::" + nct
    if cache.has(key):
        return cache.get(key)
    r = sources.pubmed_search("%s[si]" % nct, 20)
    out = {"pmids": [] if r.get("error") else list(r.get("pmids") or []),
           "error": r.get("error")}
    return cache.put(key, out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("state", nargs="?", default="s84.json")
    ap.add_argument("matched", nargs="?", default="bench_matched.csv")
    ap.add_argument("--cache", default="pubmed_cache.json")
    ap.add_argument("--only-verdict", default="",
                    help="이 판정을 받은 후보만 (예: 기각)")
    a = ap.parse_args(argv)

    cache.configure(a.cache)
    cache.load()
    nct_of = {r["drug"] + "|" + r["indication"]: (r.get("nct") or "").strip()
              for r in csv.DictReader(open(a.matched, encoding="utf-8-sig"))}
    d = json.load(open(a.state, encoding="utf-8"))
    cands = d.get("candidates", [])
    if a.only_verdict:
        cands = [c for c in cands if c.get("verdict") == a.only_verdict]

    print("=" * 78)
    print("누출 재검증 — 라벨 출처 시험의 논문이 근거로 들어왔는가")
    print("=" * 78)
    print("EXCLUDE_NCT 는 **초록에 NCT가 적힌** 논문만 막는다.")
    print("초록에 등록번호를 안 쓴 논문은 그대로 통과한다. 그걸 여기서 잡는다.\n")

    rows, leaked, checked = [], [], 0
    for c in cands:
        nct = nct_of.get(c.get("drug", "") + "|" + c.get("disease", ""), "")
        used = [r for r in (c.get("factcheck") or []) if r.get("kept")]
        if not nct.startswith("NCT") or not used:
            continue
        checked += 1
        tp = trial_papers(nct)
        hit = [r for r in used if r.get("pmid") in set(tp["pmids"])]
        rows.append((c, nct, tp, used, hit))
        if hit:
            leaked.append((c, nct, hit))
        if checked % 10 == 0:
            cache.save()
    cache.save()

    print("[결과] 검사 %d후보 · **누출 확인 %d후보**" % (checked, len(leaked)))
    if leaked:
        print("\n  라벨 출처 시험의 논문이 근거로 쓰였다 —")
        for c, nct, hit in leaked:
            print("\n    %s   (판정 %s %s%%)"
                  % (c.get("name", "")[:52], c.get("verdict"), c.get("confidence")))
            print("      라벨 NCT %s" % nct)
            for r in hit:
                print("      PMID %-9s %-8s w=%-5s %s"
                      % (r.get("pmid"), r.get("direction"), r.get("weight"),
                         (r.get("title") or "")[:38]))
        print("\n  → **이 후보들의 판정은 예측이 아니라 답안지 읽기다.**")
        print("     성능 보고 시 제외하거나 별도로 표시해야 한다.")
    else:
        print("\n  → 라벨 출처 논문이 근거로 들어온 흔적이 없다.")

    # 색인이 안 된 시험은 이 검사로 못 잡는다. 그 규모를 함께 낸다.
    no_idx = [(c, nct) for c, nct, tp, _, _ in rows
              if not tp["pmids"] and not tp["error"]]
    err = [(c, nct) for c, nct, tp, _, _ in rows if tp["error"]]
    print("\n[이 검사의 한계]")
    print("  라벨 시험의 논문이 [si]에 **색인 안 됨**  %d/%d" % (len(no_idx), checked))
    if err:
        print("  조회 실패                              %d" % len(err))
    print("  → 색인 안 된 시험은 논문이 있어도 못 잡는다.")
    print("     **따라서 위 누출 건수는 하한이다.** 없다고 단정하면 안 된다.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
