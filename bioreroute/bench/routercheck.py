# -*- coding: utf-8 -*-
"""라우터 병원체 분기 실증 — 명세 `사전명세_라우터분기.md`

    py -m bioreroute.bench.routercheck --run --out routercheck.json
    py -m bioreroute.bench.routercheck --report routercheck.json

## 왜 필요한가

실행 기록 27건에서 라우터가 **한 번도** `structure` 로 보내지 않았다.
우리는 그걸 "도킹을 안 만든 것이 옳다"의 근거로 썼는데, 같은 숫자는
**"라우터가 상수 함수다"** 로도 읽힌다. 둘을 가르는 것이 이 실험이다.

## 표본 설계 — 지름길을 막는다

숙주·간접 대조군 8쌍 중 **6쌍이 감염성 질환**이고, COVID-19와 HIV는
**양쪽에 다** 있다. 라우터가 *"감염병이면 structure"* 로 자르고 있으면
여기서 반드시 틀린다.

`maraviroc / HIV` 가 핵심이다 — HIV 치료제인데 표적이 숙주 CCR5 다.

## 이 파일이 하지 않는 것

성능을 재지 않는다. 16쌍은 교과서 기전이고 **내가 골랐다.**
`--report` 는 정확도를 "성능"이라 부르지 않는다.
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List

from ..agents import router as router_agent
from .stats import fisher, wilson

# ── 표본. **사전명세 §2 와 글자 단위로 같아야 한다** ──────────────
# 정답표는 내가 매겼다. 틀렸을 수 있고, 미달이 나오면 그 가능성을 먼저 본다.
PATHOGEN: List[Dict[str, str]] = [
    {"drug": "remdesivir",    "disease": "COVID-19",  "target": "SARS-CoV-2 RdRp"},
    {"drug": "nirmatrelvir",  "disease": "COVID-19",  "target": "SARS-CoV-2 3CL protease"},
    {"drug": "oseltamivir",   "disease": "Influenza", "target": "influenza neuraminidase"},
    {"drug": "sofosbuvir",    "disease": "Hepatitis C", "target": "HCV NS5B"},
    {"drug": "raltegravir",   "disease": "HIV Infections", "target": "HIV integrase"},
    {"drug": "acyclovir",     "disease": "Herpes Simplex", "target": "HSV DNA polymerase"},
    {"drug": "rifampin",      "disease": "Tuberculosis", "target": "bacterial RNA polymerase"},
    {"drug": "ciprofloxacin", "disease": "Urinary Tract Infections", "target": "bacterial DNA gyrase"},
]
HOST: List[Dict[str, str]] = [
    {"drug": "baricitinib",   "disease": "COVID-19", "target": "JAK1/2 (숙주)"},
    {"drug": "camostat",      "disease": "COVID-19", "target": "TMPRSS2 (숙주)"},
    {"drug": "dexamethasone", "disease": "COVID-19", "target": "글루코코르티코이드 수용체 (숙주)"},
    {"drug": "chloroquine",   "disease": "COVID-19", "target": "엔도솜 pH (간접)"},
    {"drug": "maraviroc",     "disease": "HIV Infections", "target": "CCR5 (숙주)"},
    {"drug": "ibalizumab",    "disease": "HIV Infections", "target": "CD4 (숙주)"},
    {"drug": "hydroxychloroquine", "disease": "Malaria", "target": "헴 해독 (간접)"},
    {"drug": "metformin",     "disease": "Diabetes Mellitus", "target": "Complex I → AMPK (간접)"},
]

# 사전명세 §4. **실행 후 고치지 않는다.**
THRESH = {"주①_병원체_structure_최소": 6,
          "주②_숙주간접_structure_최대": 1,
          "주③_Fisher_p_미만": 0.05}


def run(out_path: str) -> int:
    from ..io import llm

    if not llm.available():
        print("LLM 미설정 — 실행하지 않는다. 모의로 이 실험을 하면 아무것도 증명 못 한다.",
              file=sys.stderr)
        return 2
    if os.path.exists(out_path):
        print("이미 있다: %s — 덮어쓰지 않는다 (CLAUDE.md §3-3)" % out_path, file=sys.stderr)
        return 2

    pairs = [{"drug": p["drug"], "disease": p["disease"]} for p in PATHOGEN + HOST]
    recs = router_agent.classify(pairs)

    rows = []
    for src, grp in ((PATHOGEN, "병원체"), (HOST, "숙주·간접")):
        for p in src:
            i = pairs.index({"drug": p["drug"], "disease": p["disease"]})
            r = recs[i] or {}
            rows.append({
                "drug": p["drug"], "disease": p["disease"],
                "정답표_표적": p["target"], "정답표_군": grp,
                "mech": r.get("mech"), "route": r.get("route"),
                "confidence": r.get("confidence"), "target": r.get("target"),
                "why": r.get("why"), "error": r.get("error"),
                "docking_advised": bool(router_agent.docking_advised(r)),
                "provenance": r.get("provenance"),
            })

    json.dump({"명세": "사전명세_라우터분기.md", "문턱": THRESH, "행": rows},
              open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("기록: %s (%d행)" % (out_path, len(rows)))
    return 0


def report(path: str) -> int:
    d = json.load(open(path, encoding="utf-8"))
    rows = d["행"]

    err = [r for r in rows if r.get("error")]
    if err:
        # 결함 35의 교훈 — 조회 실패를 0으로 세면 네트워크 장애가 발견이 된다.
        print("⚠ 분류 실패 %d건. **판단하지 않는다.**" % len(err))
        for r in err:
            print("   %s / %s — %s" % (r["drug"], r["disease"], r["error"]))
        return 1

    def cut(grp):
        g = [r for r in rows if r["정답표_군"] == grp]
        return g, sum(1 for r in g if r["docking_advised"])

    pat, a = cut("병원체")
    hos, c = cut("숙주·간접")
    b, dd = len(pat) - a, len(hos) - c
    p = fisher(a, b, c, dd)

    print("=" * 66)
    print("라우터 병원체 분기 실증 — 명세 %s" % d["명세"])
    print("=" * 66)
    for grp in ("병원체", "숙주·간접"):
        print("\n[%s]" % grp)
        for r in rows:
            if r["정답표_군"] != grp:
                continue
            mark = "◆ structure" if r["docking_advised"] else "  evidence  "
            print("  %s  %-16s %-26s %-9s %-6s  %s"
                  % (mark, r["drug"], r["disease"][:26], r["mech"] or "?",
                     r["confidence"] or "?", (r["target"] or "")[:28]))

    lo1, hi1 = wilson(a, len(pat))
    lo2, hi2 = wilson(c, len(hos))
    print("\n" + "-" * 66)
    print("병원체    structure %d/%d = %.0f%% [%.0f–%.0f]"
          % (a, len(pat), 100 * a / len(pat), 100 * lo1, 100 * hi1))
    print("숙주·간접 structure %d/%d = %.0f%% [%.0f–%.0f]"
          % (c, len(hos), 100 * c / len(hos), 100 * lo2, 100 * hi2))
    print("Fisher 정확검정 p = %.4f" % p)

    t = d.get("문턱", THRESH)
    ok1 = a >= t["주①_병원체_structure_최소"]
    ok2 = c <= t["주②_숙주간접_structure_최대"]
    ok3 = p < t["주③_Fisher_p_미만"]
    print("\n[사전 기준 대조]")
    print("  주① 병원체 structure ≥ %d      → %d   %s"
          % (t["주①_병원체_structure_최소"], a, "통과" if ok1 else "**미달**"))
    print("  주② 숙주·간접 structure ≤ %d    → %d   %s"
          % (t["주②_숙주간접_structure_최대"], c, "통과" if ok2 else "**미달**"))
    print("  주③ Fisher p < %.2f            → %.4f  %s"
          % (t["주③_Fisher_p_미만"], p, "통과" if ok3 else "**미달**"))

    # 부지표 — 지름길을 쓰는지 보는 곳이다
    cov = [r for r in rows if "COVID" in r["disease"]]
    cp = sum(1 for r in cov if r["정답표_군"] == "병원체" and r["docking_advised"])
    ch = sum(1 for r in cov if r["정답표_군"] != "병원체" and r["docking_advised"])
    mv = next((r for r in rows if r["drug"] == "maraviroc"), None)
    print("\n[부지표 — 같은 질환 안에서 갈리는가]")
    print("  COVID-19  병원체 %d/2 · 숙주간접 %d/4" % (cp, ch))
    if mv:
        print("  maraviroc/HIV (숙주 CCR5) → %s  %s"
              % (mv["mech"], "OK" if not mv["docking_advised"] else "**structure로 갔다**"))

    print("\n" + "=" * 66)
    if ok1 and ok2 and ok3:
        print("판정: **통과** — structure 분기는 열린다. 라우터는 상수가 아니다.")
        print("      → S1 구조 게이트(§3.3-7)가 도달 가능한 코드가 된다.")
    else:
        print("판정: **미달.** 기준을 고치지 않는다.")
        print("      정답표가 틀렸을 가능성을 먼저 본다 (명세 §5).")
    print("주의: 16쌍은 교과서 기전이고 내가 골랐다. **성능 수치가 아니다.**")
    return 0 if (ok1 and ok2 and ok3) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="라우터 병원체 분기 실증")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--report", metavar="JSON")
    ap.add_argument("--out", default="routercheck.json")
    a = ap.parse_args(argv)
    if a.report:
        return report(a.report)
    if a.run:
        return run(a.out)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
