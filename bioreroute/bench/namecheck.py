# -*- coding: utf-8 -*-
"""질환명 표기 진단 — **0건이 진짜인가, 검색어가 안 맞은 것인가**
(2026-09-01).

## 무엇을 봤나

`bench_counts.json` 1,182개 중 **238개(20%)가 0건**이다. 그런데
질환별로 묶으니 —

    Malignant neoplasm of breast   **12 / 12 = 100%**
    Cerebrovascular accident         2 /  2 = 100%
    Diabetes Mellitus, Non-Insulin-Dependent  3 / 3 = 100%

**어떤 약과 짝지어도 0건인 질환이 있다.** 유방암에 문헌이 없을 리
없으므로 **약이 아니라 질환명이 문제다.**

## ⚠ 왜 위험한가 — 「없다」와 「못 찾았다」

`gate_f0` 는 쌍 문헌 0건을 **기각이 아니라 보류**로 보낸다(좋은 설계).
그런데 docstring 이 *"연결 문헌 0건은 오히려 **신규성 신호**"* 라고
적는다. **검색 실패가 「신규성」으로 읽힌다** — 결함 35 계열이고
하필 **우리에게 유리한 방향**이라 더 위험하다.

## 가설 셋 — **어느 것인지 이 도구가 가른다**

    ① 따옴표     "…" 로 감싸면 **구문 검색**이 된다. 빼면 PubMed 가
                 **자동 용어 매핑**(ATM)을 해서 동의어까지 찾는다
    ② MeSH 태그   `Diabetes Mellitus, Non-Insulin-Dependent` 는 정식
                 MeSH 인데도 0건이다 → `[MeSH]` 가 빠진 것일 수 있다
    ③ 라벨 표기   `Malignant neoplasm of breast` 는 논문 본문 표현이
                 아니다(`breast cancer`) → 표기 자체가 안 맞는다

**셋을 각각 조회해 건수를 비교한다.** ①이 크게 늘면 따옴표 문제,
②가 늘면 태그 문제, 둘 다 0인데 ③만 늘면 표기 문제다.

## ⛔ 이 도구는 **고치지 않는다**

검색 경로를 바꾸면 **봉인된 홀드아웃과 비교가 끊긴다**(`§3-2`).
여기서는 **진단만** 한다. 고칠 거면 사전명세를 새로 적고 감도 분석으로
재야 한다.

**LLM 0회.** PubMed `esearch` 만 쓴다.

    py -m bioreroute.bench.namecheck --demo        대표 질환 몇 개
    py -m bioreroute.bench.namecheck --all         0건 질환 전부
"""
import argparse
import collections
import json
import os
import re
import sys
from typing import Any, Dict, List

from ..io import sources

COUNTS = "bench_counts.json"


def zero_diseases(path: str = COUNTS) -> List[Dict[str, Any]]:
    """0건 비율이 높은 질환을 뽑는다. **약이 아니라 질환이 문제인지** 본다."""
    if not os.path.exists(path):
        return []
    d = json.load(open(path, encoding="utf-8"))
    z, nz = collections.Counter(), collections.Counter()
    for k, v in d.items():
        m = re.search(r'AND "([^"]+)"', k)
        if not m:
            continue
        (z if v == 0 else nz)[m.group(1)] += 1
    out = []
    for dis, c in z.most_common():
        tot = c + nz.get(dis, 0)
        out.append({"disease": dis, "zero": c, "total": tot,
                    "ratio": c / float(tot)})
    return out


def variants(drug: str, disease: str) -> Dict[str, str]:
    """같은 쌍의 **표기 세 갈래**. 자연어 변환은 LLM 이 필요해 안 한다."""
    return {
        "원본(따옴표)": '"%s" AND "%s"' % (drug, disease),
        "따옴표 뺌": '%s AND %s' % (drug, disease),
        "MeSH 태그": '"%s" AND "%s"[MeSH]' % (drug, disease),
    }


def probe(drug: str, disease: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"drug": drug, "disease": disease, "건수": {},
                           "오류": None}
    for name, q in variants(drug, disease).items():
        try:
            r = sources.pubmed_lookup(q, retmax=1)
            out["건수"][name] = (r or {}).get("count")
            if (r or {}).get("error"):
                out["오류"] = r["error"]
        except Exception as e:
            out["건수"][name] = None
            out["오류"] = "%s: %s" % (type(e).__name__, e)
    return out


def _verdict(cnt: Dict[str, Any]) -> str:
    """⚠ **「0건」과 「조회 실패」를 섞지 않는다** (결함 35)."""
    a = cnt.get("원본(따옴표)")
    b = cnt.get("따옴표 뺌")
    c = cnt.get("MeSH 태그")
    if a is None or b is None:
        return "조회불가"
    if a > 0:
        return "원본도 나온다"
    if (b or 0) > 0 and (c or 0) > 0:
        return "**따옴표+태그 둘 다**"
    if (b or 0) > 0:
        return "**따옴표 문제**"
    if (c or 0) > 0:
        return "**MeSH 태그 문제**"
    return "셋 다 0 — **표기 자체**이거나 진짜 없다"


def run(pairs: List[Dict[str, str]]) -> Dict[str, Any]:
    rows = [probe(p["drug"], p["disease"]) for p in pairs]
    for r in rows:
        r["판정"] = _verdict(r["건수"])
    tally = collections.Counter(r["판정"] for r in rows)
    return {"쌍": rows, "판정분포": dict(tally)}


def _table(r: Dict[str, Any]) -> str:
    L = ["=" * 82,
         "질환명 표기 진단 — **0건이 진짜인가, 검색어가 안 맞은 것인가** (LLM 0회)",
         "=" * 82,
         "  ⛔ 이 도구는 **진단만** 한다. 검색 경로를 바꾸면 봉인 수치와 비교가 끊긴다",
         "",
         "  %-34s %9s %9s %9s  %s"
         % ("쌍", "원본", "따옴표뺌", "MeSH", "판정")]
    L.append("  " + "-" * 78)
    for x in r["쌍"]:
        nm = ("%s / %s" % (x["drug"], x["disease"]))[:33]
        c = x["건수"]
        f = lambda k: ("-" if c.get(k) is None else str(c[k]))
        L.append("  %-34s %9s %9s %9s  %s"
                 % (nm, f("원본(따옴표)"), f("따옴표 뺌"), f("MeSH 태그"),
                    x["판정"]))
    L += ["", "  판정 분포: " + " · ".join("%s %d" % (k, v)
                                          for k, v in r["판정분포"].items()),
          "",
          "  ⚠ **「셋 다 0」 을 «문헌이 없다» 로 읽지 마라.** 질환 표기가",
          "     라벨 계열이면 셋 다 안 맞을 수 있다 — 그건 **못 찾은 것**이다.",
          "  ⚠ 「조회불가」(네트워크)는 **0건이 아니다** — 결함 35.",
          "=" * 82]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="질환명 표기 때문에 0건이 나오는지 진단한다 (LLM 0회)")
    ap.add_argument("--demo", action="store_true",
                    # ⚠ argparse 는 help 를 `%` 포맷으로 확장한다 —
                    #   `100%인` 이 «잘못된 포맷 문자» 로 죽는다.
                    #   09-01 에 실제로 죽었다. **`--help` 도 안 태웠던 것.**
                    help="0건 비율 100%% 인 질환 몇 개만")
    ap.add_argument("--all", action="store_true", help="0건 질환 전부")
    ap.add_argument("--drug", default="metformin",
                    help="대조용 약 — 문헌이 많은 약이어야 한다")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)

    zs = zero_diseases()
    if not zs:
        print("  ⚠ `%s` 를 못 읽었다" % COUNTS)
        return 1
    if a.all:
        pick = [z for z in zs if z["ratio"] >= 0.5]
    else:
        pick = [z for z in zs if z["ratio"] >= 1.0][:6]
    print("  0건 비율이 높은 질환 %d개를 본다 (전체 0건 질환 %d개 중)\n"
          % (len(pick), len(zs)))
    r = run([{"drug": a.drug, "disease": z["disease"]} for z in pick])
    print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else _table(r))
    if a.out:
        from ..io.safeio import save_json
        w = save_json(r, a.out, indent=1)
        print("\n→ %s" % w.get("경로", a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
