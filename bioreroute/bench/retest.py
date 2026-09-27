# -*- coding: utf-8 -*-
"""재시험 신뢰도 — **같은 쌍을 여러 번 돌려 계기 변동을 잰다.**

명세: `사전명세_재시험신뢰도.md` · 봉인 `a6a6a381e078`

## 왜 이게 필요한가

`연구기술보고서.md` 불리한 사실 **10번**이 08-06 부터 이렇게 적혀 있다 —

  > *"LLM 재시험 신뢰도를 한 번도 안 쟀다. 온도 0은 결정론이 아니다.
  >  `agreement.py` 가 있는데 결과 파일이 0건이다 — 그래서 위 수치들의
  >  **측정 오차를 모른다.** Wilson CI 는 표본 변동을 재지 **도구 자체의
  >  변동**은 안 잰다"*

**08-18 에 확인하니 아직도 0건이었다.** 적어 두는 것과 재는 것은 다르다.

## 무엇을 재고 무엇을 안 재나

**PubMed 캐시는 일부러 고정한다.** 목적은 «같은 초록 집합에 대한 **판독**
변동» 이다. 검색 변동까지 섞으면 두 원인을 못 가른다 — 그러면 결과가
나빠도 **어디를 고쳐야 하는지 모른다.**

`exit_` 도 「표준」으로 고정한다. 08-18 에 이 변동을 처음 본 두 실행은
`exit_` 가 달라서 **설계 차이와 계기 변동이 섞여 있었다.** 여기서는 안 섞는다.
"""
import argparse
import json
import os
import statistics
from typing import Any, Dict, List

from .. import demo, evidence
from ..io import llm, safeio


def _pairs() -> List[str]:
    """구운 사례의 질의 — **화면에 나가는 그 쌍들**을 그대로 잰다."""
    return [c["질의"] for c in (evidence.cases() or {}).get("사례") or []
            if c.get("질의")]


def run_once(query: str) -> Dict[str, Any]:
    """**호출부는 `llm.BYPASS_CACHE` 를 반드시 켜 놓고 부른다** — `_main` 참조."""
    r = demo.run_pair(query, config="B5S", exit_="표준")
    ev = r.get("근거") or []
    return {
        "상태": r.get("상태"),
        "판정": r.get("판정"),
        "신뢰도": r.get("신뢰도"),
        "근거수": len(ev),
        "가중치": {e["PMID"]: e["가중치"] for e in ev if e.get("PMID")},
        "served_by": (r.get("모델") or ""),
        "비용": r.get("비용"),
    }


def summarize(runs: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """주①·주② 와 부차를 낸다. **기준 판정은 여기서 하지 않는다** —
    `judge()` 가 명세의 문턱을 들고 있다."""
    rows = []
    for q, rs in runs.items():
        ok = [x for x in rs if x.get("상태") == "정상"]
        if len(ok) < 2:
            rows.append({"질의": q, "유효": len(ok), "일치": None, "변동폭": None,
                         "사유": "유효 실행이 2회 미만 — 이 쌍은 뺀다"})
            continue
        vs = [x["판정"] for x in ok]
        ps = [x["신뢰도"] for x in ok if isinstance(x["신뢰도"], (int, float))]
        # **세 번 다 채택된 PMID 에서만** 가중치 비를 본다.
        #   한 번만 나온 것을 «변동» 이라 부르면 채택 변동과 섞인다.
        common = set(ok[0]["가중치"])
        for x in ok[1:]:
            common &= set(x["가중치"])
        wr = []
        for pmid in common:
            ws = [x["가중치"][pmid] for x in ok]
            lo, hi = min(ws), max(ws)
            if lo > 0:
                wr.append(round(hi / lo, 2))
        jac = None
        if len(ok) >= 2:
            us = set()
            for x in ok:
                us |= set(x["가중치"])
            jac = round(len(common) / len(us), 3) if us else None
        rows.append({
            "질의": q, "유효": len(ok),
            "판정들": vs, "일치": len(set(vs)) == 1,
            "확률들": ps,
            "변동폭": (max(ps) - min(ps)) if len(ps) >= 2 else None,
            "공통PMID": len(common), "자카드": jac,
            "가중치최대비": max(wr) if wr else None,
            "모델": sorted({x["served_by"] for x in ok}),
        })
    done = [r for r in rows if r.get("일치") is not None]
    agree = sum(1 for r in done if r["일치"])
    spreads = [r["변동폭"] for r in done if r.get("변동폭") is not None]
    return {
        "쌍": len(rows), "판정가능": len(done),
        "주①_완전일치": "%d/%d" % (agree, len(done)),
        "주①_비율": round(agree / len(done), 3) if done else None,
        "주②_변동폭중앙값": round(statistics.median(spreads), 1) if spreads else None,
        "부차_가중치최대비": max([r["가중치최대비"] for r in done
                             if r.get("가중치최대비")] or [None] or [None])
        if any(r.get("가중치최대비") for r in done) else None,
        "행": rows,
    }


def judge(s: Dict[str, Any]) -> Dict[str, Any]:
    """**명세의 문턱을 그대로 적용한다.** 결과를 보고 고치지 않는다."""
    n_done = s["판정가능"]
    agree = int(str(s["주①_완전일치"]).split("/")[0]) if n_done else 0
    sp = s["주②_변동폭중앙값"]
    p1 = (n_done > 0 and agree == n_done)          # 완전일치 전부
    p2 = (sp is not None and sp <= 5.0)            # 중앙값 ≤ 5%p
    return {
        "주①": {"기준": "판정 완전일치 전 쌍", "실측": s["주①_완전일치"],
                "합격": p1},
        "주②": {"기준": "확률 변동폭 중앙값 ≤ 5.0%p", "실측": sp, "합격": p2},
        "종합": "합격" if (p1 and p2) else "**미달**",
    }


def _main(argv=None) -> int:
    a = argparse.ArgumentParser(description="재시험 신뢰도 — 계기 변동 측정")
    a.add_argument("--repeat", type=int, default=3)
    a.add_argument("--pairs", default="")
    a.add_argument("--out", default="재시험신뢰도결과.md")
    a.add_argument("--json", default="retest.json")
    a = a.parse_args(argv)

    qs = [x.strip() for x in a.pairs.split("|") if x.strip()] or _pairs()
    if not qs:
        print("구운 사례가 없다 — 잴 쌍이 없다.")
        return 2
    print("=" * 66)
    print("재시험 신뢰도 — %d쌍 × %d회 · B5S · 표준 · 온도 0" % (len(qs), a.repeat))
    print("명세 `사전명세_재시험신뢰도.md` (봉인 a6a6a381e078)")
    print("=" * 66)

    # ── ⚠ **LLM 캐시를 끈다** (결함 269) ─────────────────────────
    #
    #   앞판은 이걸 안 켜고 돌렸다. 결과가 **완전일치 6/6 · 변동폭
    #   0.0%p · 합격** 이었는데 **새 LLM 호출이 18회 실행에 6회**였다 —
    #   즉 **LLM 을 다시 안 물었고 아무것도 안 쟀다.**
    #
    #   `llm.BYPASS_CACHE` 는 **이 측정을 위해 존재한다.** 주석이 그렇게
    #   적혀 있고, `agreement`·`demopick`·`gencheck`·`modelswap` **넷이
    #   이미 쓰고 있다.** `gencheck` 은 *«안 끄면 분산이 0으로 나온다»* 라고
    #   적어 뒀고 실제로 0.0 이 나왔다. **네 전례를 안 읽고 새로 만들었다.**
    #
    #   `BYPASS_CACHE` 는 **LLM 캐시만** 건드린다. PubMed 캐시는
    #   `sources.py` 가 따로 쓰므로 **명세의 «검색은 고정, 판독만 잰다»
    #   는 그대로 지켜진다.**
    old_bp, old_max = llm.BYPASS_CACHE, llm.MAX_CALLS
    llm.BYPASS_CACHE = True
    # 기본 상한 60 인데 18회 실행 × 약 3호출 = 54 로 아슬아슬하다.
    #   **일부러 올리고 그 사실을 화면에 적는다.** 일일 예산(`budget`)이
    #   진짜 방어선이고 여긴 폭주 방지선이다.
    llm.MAX_CALLS = max(old_max, a.repeat * len(qs) * 5)
    print("  LLM 캐시 **끔** · 실행당 상한 %d (기본 %d)"
          % (llm.MAX_CALLS, old_max))
    runs: Dict[str, List[Dict[str, Any]]] = {}
    before = llm.spent()
    try:
        for q in qs:
            runs[q] = []
            for i in range(a.repeat):
                r = run_once(q)
                runs[q].append(r)
                print("  %-46s %d회차  %s %s%%  근거 %s"
                      % (q[:44], i + 1, r.get("판정") or r.get("상태"),
                         r.get("신뢰도"), r.get("근거수")))
    finally:
        llm.BYPASS_CACHE, llm.MAX_CALLS = old_bp, old_max
    s = summarize(runs)
    v = judge(s)
    s["새_LLM_호출"] = llm.spent() - before

    # ── **계기가 아무것도 안 쟀으면 판정을 내지 않는다** (결함 269) ──
    #
    #   이게 이 모듈에서 가장 중요한 줄이다. 캐시가 살아 있으면
    #   «완전일치 · 변동폭 0» 이 나오고 그건 **합격**으로 읽힌다 —
    #   **고장이 우리에게 유리한 방향으로 난다.** 이 프로젝트가
    #   «자기에게 유리한 고장이 가장 오래 산다» 고 부른 그것이다.
    #
    #   그래서 **호출 수가 실행 수에 비해 적으면 판정을 거부한다.**
    #   안내문이 아니라 구조로 막는다.
    n_runs = sum(len(v2) for v2 in runs.values())
    floor = max(2, int(n_runs * 1.5))
    s["최소기대호출"] = floor
    if s["새_LLM_호출"] < floor:
        print()
        print("=" * 66)
        print("⛔ **판정을 내지 않는다** — 계기가 아무것도 안 쟀다.")
        print("   실행 %d회에 새 LLM 호출이 **%d회**다 (최소 기대 %d)."
              % (n_runs, s["새_LLM_호출"], floor))
        print("   캐시가 앞 실행의 답을 그대로 돌려준 것이다 —")
        print("   **«변동이 없다» 가 아니라 «안 쟀다» 이다.**")
        print("=" * 66)
        safeio.save_json({"요약": s, "판정": "무효 — 계기 미작동",
                          "원자료": runs}, a.json)
        return 4

    print()
    print("주① 판정 완전일치   %s   → %s" % (v["주①"]["실측"],
                                     "합격" if v["주①"]["합격"] else "**미달**"))
    print("주② 확률 변동폭 중앙값 %s%%p  (기준 ≤5.0) → %s"
          % (v["주②"]["실측"], "합격" if v["주②"]["합격"] else "**미달**"))
    print("종합: %s" % v["종합"])
    print("새 LLM 호출 %d회 (실행 %d회 · 최소 기대 %d) — **캐시를 끄고 잰 값이다**"
          % (s["새_LLM_호출"], n_runs, floor))

    safeio.save_json({"요약": s, "판정": v, "원자료": runs}, a.json)
    _write_md(a.out, s, v)
    print("\n%s · %s 에 적었다." % (a.out, a.json))
    return 0 if v["종합"] == "합격" else 3


def _write_md(path: str, s: Dict[str, Any], v: Dict[str, Any]) -> None:
    L = ["# 재시험 신뢰도 결과", "",
         "> 명세 `사전명세_재시험신뢰도.md` · 봉인 `a6a6a381e078`",
         "> **기준은 결과를 보기 전에 확정했고 고치지 않았다.**", "",
         "## 판정", "",
         "| 지표 | 기준 | 실측 | |", "|---|---|---|---|",
         "| 주① 판정 완전일치 | 전 쌍 | %s | %s |"
         % (v["주①"]["실측"], "합격" if v["주①"]["합격"] else "**미달**"),
         "| 주② 확률 변동폭 중앙값 | ≤ 5.0%%p | %s%%p | %s |"
         % (v["주②"]["실측"], "합격" if v["주②"]["합격"] else "**미달**"),
         "", "**종합 — %s**" % v["종합"], "",
         "## 쌍별", "",
         "| 질의 | 유효 | 판정 | 확률 | 변동폭 | 공통 PMID | 자카드 | 가중치 최대비 |",
         "|---|---|---|---|---|---|---|---|"]
    for r in s["행"]:
        if r.get("일치") is None:
            L.append("| %s | %d | — | — | — | — | — | — |" % (r["질의"], r["유효"]))
            continue
        L.append("| %s | %d | %s | %s | %s%%p | %s | %s | %s |"
                 % (r["질의"], r["유효"], " · ".join(r["판정들"]),
                    " · ".join(str(x) for x in r["확률들"]),
                    r["변동폭"], r["공통PMID"], r["자카드"],
                    r["가중치최대비"] or "—"))
    L += ["", "> **자카드** = 세 실행이 공통으로 채택한 PMID / 한 번이라도 채택된 PMID.",
          "> 1.0 이 아니면 **같은 초록 집합에서 채택이 달라졌다**는 뜻이다.", "",
          "> **가중치 최대비** = 세 번 다 채택된 PMID 의 `max/min`.",
          "> 1.0 이 아니면 **같은 논문을 다르게 분류했다**는 뜻이다 —",
          "> `weight_for()` 가 결정론적 함수이므로 다른 설명이 없다.", "",
          "새 LLM 호출 **%d회**." % s.get("새_LLM_호출", 0)]
    safeio.save_text(path, "\n".join(L)) if hasattr(safeio, "save_text") \
        else open(path, "w", encoding="utf-8").write("\n".join(L))


if __name__ == "__main__":
    raise SystemExit(_main())
