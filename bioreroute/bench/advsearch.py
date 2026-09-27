# -*- coding: utf-8 -*-
"""적대적 검색 — **반박을 찾아 나서는가** (2026-09-01).

## 우리 논지의 자기모순

제안서는 *"병목은 후보를 만드는 일이 아니라 그럴듯하지만 틀린 후보를
값싸게 걸러내는 일"* 이라고 적었다. 그런데 검색은 **한 갈래**뿐이다 —

    "<약>" AND "<병>"

**그 쿼리는 반박을 찾도록 설계되지 않았다.** 긍정 결과가 더 많이
출판되고 더 많이 인용되므로(publication bias), 중립 쿼리는 **구조적으로
지지 쪽으로 기운 표본**을 준다. 우리는 그 기운 표본 안에서 반박을 센다.

심사에서 *"기존 문헌 검색과 뭐가 다르냐"* 는 반드시 온다. 지금은
**«우리는 반대 증거를 따로 찾아 나선다»** 고 답할 수 없다.

## ⛔ 반증 조건을 **먼저** 적는다

`CLAUDE.md §1-b` 수동 렌즈 4. 이 기능이 **불필요하다는 관찰**은 —

> **적대적 검색이 새 논문을 거의 안 가져오면**(쌍당 새 PMID 중앙값
> ≤ 1) **중립 검색만으로 충분하다는 뜻이고, 이 기능은 버린다.**

반대로 새 PMID 가 많으면 **중립 표본이 편향돼 있었다**는 증거다.

## 무엇을 재나 — **건수가 아니라 «상위 N 안에 뭐가 들어오나»**

건수 비교(`적대적/중립`)는 이미 아는 것을 반복할 뿐이다 — 반박
문헌이 희소하다는 것은 `34,067건 중 2.3%` 로 이미 쟀다.

**진짜 물음은 우리가 실제로 읽는 상위 8건이 달라지는가**다.

    중립   "metformin" AND "breast cancer"                  → 상위 8 PMID
    적대적  … AND (failed OR "no significant" OR …)          → 상위 8 PMID
    ────────────────────────────────────────────────────────────────
    새 PMID = 적대적에만 있는 것 ← **이만큼을 지금 놓치고 있다**

## ⚠ 두 표본을 **합치지 마라**

합치면 «찾으면 나온다» 를 «많다» 로 착각한다. 나란히 놓고 **차이
자체를 신호로** 쓴다 — *"중립에서 지지 5·반박 1, 적대적에서 반박 7
→ 편향이 크다 → 신뢰도 강등."*

⚠ 그리고 **적대적 쿼리로 찾은 것을 그냥 반박으로 세면 안 된다.**
`failed` 가 들어간 논문이 그 약의 실패를 말한다는 보장이 없다
(*"previous therapies failed, so we tried X"*). **판정은 여전히
팩트체커가 한다** — 이 도구는 **표본을 넓힐 뿐**이다.

## LLM 0회

PubMed `esearch` 만 쓴다. 판정을 안 하므로 모델을 안 부른다.

    py -m bioreroute.bench.advsearch --demo          구운 사례 6쌍
    py -m bioreroute.bench.advsearch --n 30          개발집합 앞 30쌍
"""
import argparse
import json
import os
import statistics
import sys
from typing import Any, Dict, List, Optional

from ..io import sources

# ── 적대적 어휘 — **사전에 고정한다.** 결과를 보고 안 고친다(§3-2) ──
#
#   임상시험 보고의 부정 결과에 쓰이는 표준 표현들이다. 늘리면 더 많이
#   찾겠지만 **늘린 뒤에 늘렸다고 적지 않으면 그게 사냥**이다.
ADV_TERMS = ('failed', '"no significant"', 'negative', 'terminated',
             '"did not improve"', 'futility', '"no benefit"',
             'discontinued', '"lack of efficacy"')

NEUTRAL = '"%s" AND "%s"'
RETMAX = 8          # 우리가 실제로 읽는 초록 수와 같게 맞춘다


def adversarial(drug: str, disease: str) -> str:
    return (NEUTRAL % (drug, disease)) + " AND (" + " OR ".join(ADV_TERMS) + ")"


def compare(drug: str, disease: str, retmax: int = RETMAX,
            titles: bool = False) -> Dict[str, Any]:
    """중립 · 적대적 상위 N 을 나란히 놓는다. **합치지 않는다.**

    `titles=True` 면 **새로 나온 PMID 의 제목**을 같이 받는다(LLM 0회).
    수치만 보면 «8/8 새로» 가 편향인지 도구 결함인지 못 가른다.
    """
    out: Dict[str, Any] = {"drug": drug, "disease": disease,
                           "n_neutral": None, "n_adv": None,
                           "count_neutral": None, "count_adv": None,
                           "새PMID": None, "겹침": None, "오류": None}
    try:
        a = sources.pubmed_search(NEUTRAL % (drug, disease), retmax=retmax)
        b = sources.pubmed_search(adversarial(drug, disease), retmax=retmax)
    except Exception as e:
        out["오류"] = "%s: %s" % (type(e).__name__, e)
        return out
    if (a or {}).get("error") or (b or {}).get("error"):
        out["오류"] = (a or {}).get("error") or (b or {}).get("error")
        return out
    pa = set((a or {}).get("pmids") or [])
    pb = set((b or {}).get("pmids") or [])
    out.update(n_neutral=len(pa), n_adv=len(pb),
               count_neutral=(a or {}).get("count"),
               count_adv=(b or {}).get("count"),
               새PMID=len(pb - pa), 겹침=len(pa & pb),
               새PMID목록=sorted(pb - pa)[:8])
    # ── ⚠ 09-01 · **8/8 이 전부 새 논문이라 오히려 의심스러웠다** ──────
    #
    #   적대적 쿼리는 `AND` 로 좁힌 것이므로 그 결과는 중립 결과의
    #   **부분집합**이다. 그런데 상위 8이 하나도 안 겹쳤다. 해석 둘 —
    #     ① **반박 논문이 중립 검색에서 relevance 상위에 안 온다**
    #        (= 우리가 찾던 편향)
    #     ② 쿼리가 뭔가 다른 것을 보고 있다 (= 도구 결함)
    #   **제목을 봐야 갈린다.** LLM 없이 받을 수 있으므로 옵션으로 둔다.
    if titles and (pb - pa):
        try:
            recs = sources.pubmed_abstracts(sorted(pb - pa)[:5])
            out["새논문제목"] = [
                {"pmid": k, "title": (v or {}).get("title", "")[:110],
                 "year": (v or {}).get("year")}
                for k, v in (recs or {}).items()]
        except Exception as e:
            out["새논문제목"] = []
            out["제목오류"] = "%s: %s" % (type(e).__name__, e)
    return out


def _pairs_from_demo(path: str = "demo_cases.json") -> List[Dict[str, str]]:
    if not os.path.exists(path):
        return []
    d = json.load(open(path, encoding="utf-8"))
    out = []
    for one in d.get("사례") or []:
        q = str(one.get("질의") or "")
        if "/" in q:
            drug, dis = q.split("/", 1)
            out.append({"drug": drug.strip(), "disease": dis.strip()})
    return out


def _pairs_from_matched(path: str = "bench_matched.csv",
                        stratum: str = "A", n: int = 0) -> List[Dict[str, str]]:
    import csv
    if not os.path.exists(path):
        return []
    out = []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if stratum and r.get("stratum") != stratum:
            continue
        out.append({"drug": r.get("drug", ""), "disease": r.get("indication", "")})
        if n and len(out) >= n:
            break
    return out


def run(pairs: List[Dict[str, str]], retmax: int = RETMAX,
        titles: bool = False) -> Dict[str, Any]:
    rows = [compare(p["drug"], p["disease"], retmax, titles) for p in pairs]
    ok = [r for r in rows if not r["오류"] and r["새PMID"] is not None]
    news = [r["새PMID"] for r in ok]
    return {"쌍": rows, "성공": len(ok), "오류": len(rows) - len(ok),
            "새PMID_중앙값": statistics.median(news) if news else None,
            "새PMID_평균": (sum(news) / float(len(news))) if news else None,
            "새PMID_0인쌍": sum(1 for x in news if x == 0),
            "retmax": retmax}


def _table(r: Dict[str, Any]) -> str:
    L = ["=" * 76,
         "적대적 검색 — **반박을 따로 찾으면 새 논문이 나오는가** (LLM 0회)",
         "=" * 76,
         "  ⛔ 반증 조건(사전) — 새 PMID **중앙값 ≤ 1** 이면 이 기능은 버린다",
         "",
         "  %-30s %6s %6s %6s  %s" % ("쌍", "중립", "적대", "새", "전체 건수")]
    L.append("  " + "-" * 72)
    for x in r["쌍"]:
        nm = ("%s / %s" % (x["drug"], x["disease"]))[:29]
        if x["오류"]:
            L.append("  %-30s  ⚠ %s" % (nm, str(x["오류"])[:34]))
            continue
        L.append("  %-30s %6d %6d %6d  %s → %s"
                 % (nm, x["n_neutral"], x["n_adv"], x["새PMID"],
                    x["count_neutral"], x["count_adv"]))
        for t in (x.get("새논문제목") or [])[:3]:
            L.append("        · %s (%s) %s" % (t["pmid"], t.get("year") or "?",
                                               t["title"]))
    med = r["새PMID_중앙값"]
    L += ["", "  성공 %d · 오류 %d" % (r["성공"], r["오류"])]
    if med is not None:
        L += ["  **새 PMID 중앙값 %.1f** · 평균 %.1f · 0건인 쌍 %d"
              % (med, r["새PMID_평균"], r["새PMID_0인쌍"]),
              "",
              ("  → **중앙값 ≤ 1 이므로 반증 조건에 걸린다.** 이 기능은 버린다."
               if med <= 1 else
               "  → 중앙값 > 1 — **중립 검색만으로는 상위 %d건 안에서"
               " 이만큼을 놓친다**" % r["retmax"])]
    L += ["",
          "  ⚠ **두 표본을 합치지 않았다.** 적대적 쿼리로 찾았다고 반박이",
          "     아니다 — *«이전 치료가 실패해서 X를 썼다»* 도 걸린다.",
          "     **판정은 여전히 팩트체커가 한다.** 이건 표본을 넓힐 뿐이다.",
          "=" * 76]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="적대적 검색으로 새 논문이 나오는지 잰다 (LLM 0회)")
    ap.add_argument("--demo", action="store_true", help="구운 사례 6쌍")
    ap.add_argument("--n", type=int, default=0, help="개발집합 앞 N쌍")
    ap.add_argument("--stratum", default="A")
    ap.add_argument("--retmax", type=int, default=RETMAX)
    ap.add_argument("--titles", action="store_true",
                    help="새로 나온 논문의 **제목**도 받는다 (LLM 0회) — "
                         "수치만으로는 편향인지 도구 결함인지 못 가른다")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    pairs = (_pairs_from_demo() if a.demo
             else _pairs_from_matched(stratum=a.stratum, n=a.n or 20))
    if not pairs:
        print("  ⚠ 쌍을 못 읽었다 — `--demo` 또는 `bench_matched.csv` 확인")
        return 1
    r = run(pairs, a.retmax, a.titles)
    print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else _table(r))
    if a.out:
        from ..io.safeio import save_json
        w = save_json(r, a.out, indent=1)
        print("\n→ %s" % w.get("경로", a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
