# -*- coding: utf-8 -*-
"""캐시의 «0건» 이 진짜 0건인가 — 결함 327.

    py -m bioreroute.bench.zerocheck                    홀드아웃 F0 의 0건
    py -m bioreroute.bench.zerocheck --out 영점확인.json  결과를 파일로도 (있으면 거부)

## 왜 있나

09-23 — 복원한 캐시의 «0건» 다섯이 실재하는 약을 «환각» 으로 기각했다
(`difelikefalin 0.25 mg` 은 캐시 0 · PubMed 5). `sources.pubmed_lookup` 은
응답에 `count` 가 없으면 **오류가 아니라 0** 으로 읽고 영구히 저장한다.
**캐시에 그런 0 이 몇 개 박혀 있는지는 아무도 안 셌다.**

F0 의 0건은 판정을 **직접** 정한다 —

```
약물 0건   → «약물 자체가 문헌에 없음 → 환각» · 기각
쌍 0건     → «질환 연결 문헌 0건» · 보류로 고정 (근거를 안 본다)
```

## 어떻게 — «그때 이미 있던 논문» 만 센다

지금 PubMed 에 물으면 **그 뒤에 나온 논문**도 잡힌다. 그건 가짜 0 이 아니다.
그래서 **Entrez 등록일(edat) ≤ 2026-06-30** — 이 프로젝트 착수 전날 — 으로 자른다.
캐시는 그 뒤에 만들어졌으므로, **그 조건에서 1건 이상이면 캐시가 이미 있던
논문을 못 본 것**이다. 가짜 0 이다.

## 하지 않는 것

- **캐시에 쓰지 않는다.** 읽기만 한다 — 실험 입력(지문)을 안 바꾼다
- LLM 0회. NCBI 는 `sources.throttle()` 간격을 지킨다(홀드아웃 기본 수백 회 · 1~2분)
- 개수를 못 받으면 **«확인 불가»** 로 센다. 0 으로 굳히지 않는다 — 고치려는 결함을
  도구가 되풀이하면 안 된다
"""

import argparse
import csv
import json
import os
import sys
import time

from . import query as Q
from ..io import sources as S

MAXDATE = "2026/06/30"          # 착수(07-01) 전날 — 그때 이미 있던 논문만
HOLDOUT = "bench_holdout_matched_sealed.csv"
CACHE = "pubmed_cache.json"


def ask(term, get=None, tries=3):
    """(그때 있던 논문 수, 오류). 개수를 못 받으면 수는 **None** 이다."""
    get = get or S._get
    url = S.EUTILS + "esearch.fcgi?" + S._params(
        term=term, retmax=0, datetype="edat", mindate="1800/01/01", maxdate=MAXDATE)
    err = None
    for k in range(tries):
        S.throttle()
        try:
            d = get(url)
            res = d.get("esearchresult") if isinstance(d, dict) else None
            if isinstance(res, dict) and "count" in res and not res.get("ERROR"):
                return int(res["count"]), None
            err = "응답에 개수 없음: %s" % str(d)[:120]
        except Exception as e:                        # 429 · 시간 초과 · JSON 아님
            err = "%s: %s" % (type(e).__name__, e)
        time.sleep(0.6 * (k + 1))
    return None, err


def _zero(v):
    return isinstance(v, dict) and not v.get("error") and (v.get("count") or 0) == 0


def targets(cache, rows):
    """홀드아웃 F0 입력 중 캐시가 «0건» 이라고 적은 질의."""
    out = []
    for i, r in enumerate(rows):
        pq = Q.pair(r["drug"], r["indication"])
        if not _zero(cache.get(pq)):
            continue
        ent = Q.clean(r["drug"])            # F0 실재 조회의 캐시 키 (`run.to_candidate`)
        ev = cache.get(ent)
        # 실재 조회가 캐시에 없으면 그 행은 KILL 도 FLAG 도 아니다 — 조회가
        # 실패해(일시 장애는 안 남는다) F0 가 ERROR 였을 수 있다. 짐작하지 않는다
        f0 = "KILL" if _zero(ev) else ("FLAG" if isinstance(ev, dict) else "약물 미캐시")
        out.append({"행": i, "라벨": r.get("label"), "쌍": pq, "약물": ent, "F0": f0})
    return out


def run(cache, rows, get=None):
    tg = targets(cache, rows)
    qs = sorted({t["쌍"] for t in tg} | {t["약물"] for t in tg if t["F0"] == "KILL"})
    got = {}
    for q in qs:
        got[q] = ask(q, get=get)
    for t in tg:
        pn, _ = got[t["쌍"]]
        t["쌍_그때"] = pn
        if t["F0"] == "KILL":
            en, _ = got[t["약물"]]
            t["약물_그때"] = en
            # 환각 기각이 가짜인가 — 약물이 그때 이미 문헌에 있었다
            t["판정"] = ("확인 불가" if en is None else
                        "가짜 환각 기각" if en > 0 else "문헌 없음(진짜 0)")
        elif t["F0"] == "FLAG":
            t["판정"] = ("확인 불가" if pn is None else
                        "가짜 보류 고정" if pn > 0 else "연결 문헌 없음(진짜 0)")
        else:
            t["판정"] = "약물 미캐시 — 판정 경로 불명"
    return tg, got


def report(tg, got):
    from collections import Counter
    print("=" * 78)
    print("캐시의 «0건» 재확인 — 홀드아웃 F0 · edat ≤ %s · 캐시에 안 쓴다" % MAXDATE)
    print("=" * 78)
    bad = sum(1 for v in got.values() if v[0] is None)
    fake = sum(1 for v in got.values() if v[0])
    print("  질의 %d개 — 그때 이미 논문이 있었다(가짜 0) %d · 진짜 0 %d · 확인 불가 %d"
          % (len(got), fake, len(got) - fake - bad, bad))
    c = Counter((t["F0"], t["판정"], t["라벨"]) for t in tg)
    print("\n  %-6s %-22s %5s %5s" % ("F0", "판정", "TN", "TP"))
    for f0 in ("KILL", "FLAG", "약물 미캐시"):
        for pj in sorted({k[1] for k in c if k[0] == f0}):
            print("  %-6s %-22s %5d %5d" % (f0, pj, c[(f0, pj, "TN")], c[(f0, pj, "TP")]))
    fk = [t for t in tg if t["판정"].startswith("가짜")]
    if fk:
        print("\n  가짜 0 — 판정이 바뀌었을 수 있는 쌍")
        for t in fk:
            n = t.get("약물_그때") if t["F0"] == "KILL" else t["쌍_그때"]
            print("   [%s] %-4s %s → 그때 %s건" % (t["라벨"], t["F0"],
                                               (t["약물"] if t["F0"] == "KILL" else t["쌍"])[:70], n))
    if bad:
        print("\n  ⚠ 확인 불가 %d — 다시 돌려라. **0 으로 치지 않는다**" % bad)


def main(argv=None):
    ap = argparse.ArgumentParser(description="캐시의 0건이 진짜 0건인가 (결함 327)")
    ap.add_argument("--holdout", default=HOLDOUT)
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--out", default=None, help="결과 JSON (있으면 거부)")
    a = ap.parse_args(argv)
    if a.out and os.path.exists(a.out):
        print("  🔴 %s 가 이미 있다 — 덮어쓰지 않는다 (CLAUDE.md §3-3)" % a.out)
        return 2
    rows = [r for r in csv.DictReader(open(a.holdout, encoding="utf-8-sig"))
            if r.get("stratum") == "A"]
    with open(a.cache, encoding="utf-8") as f:
        cache = json.load(f)                 # **읽기만** — cache 모듈을 안 쓴다
    tg, got = run(cache, rows)
    report(tg, got)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"기준": "edat<=" + MAXDATE, "쌍": tg,
                       "질의": {q: {"그때": n, "오류": e} for q, (n, e) in got.items()}},
                      f, ensure_ascii=False, indent=1)
        print("\n  → %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
