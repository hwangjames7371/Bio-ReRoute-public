# -*- coding: utf-8 -*-
"""시연 질환 고르기 — **명세 `사전명세_시연질환.md`(봉인 `b9e45c7b662f`) 집행기.**

    py -m bioreroute.bench.demopick            넷 다 · 각 8회 (실호출 32회)
    py -m bioreroute.bench.demopick --dry      배관만

## 이 모듈이 존재하는 이유 — **고르는 행위가 자유도다**

08-18 IPF 실측에서 «재창출 후보 0개」가 **6/8** 이었다. 시연에 못 쓴다.
그래서 질환을 바꾸는 선택지가 생겼는데, 그냥 바꾸면 *"좋게 나오는 걸
골랐다"* 가 된다.

**그래서 규칙을 코드에 박는다.** 사람이 표를 보고 «이게 나아 보인다» 로
고르면 명세를 쓴 의미가 없다 — `CLAUDE.md` 머리말 그대로다.

> **안내문은 방어가 아니다. 구조로 막아야 한다.**

## 규칙 (명세 §3 · 이 순서로)

```
주기준   「재창출 후보 ≥ 5개」인 실행 수        →  최다
1차 동점 8회 교집합(매번 나온 약) 수가 큰 쪽
2차 동점 RepoDB 가 「실패」로 아는 후보를 낸 실행 수가 많은 쪽
3차 동점 명세에 적힌 순서
반증조건 넷 다 「≥5개」가 0회면 → **질환을 안 바꾼다. IPF 로 간다**
```

## 안 고른 것도 적는다

명세 §4-3 — *"안 고른 것을 안 적으면 이 절차 전체가 무의미하다."*
그래서 이 모듈은 **넷 전부의 수치**를 표로 찍고 JSON 에 남긴다.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List

from ..io import llm, safeio
from . import gencheck

# 명세 §1 의 표 **그대로**. 순서가 곧 3차 동점 규칙이다.
CANDIDATES: List[str] = [
    "COVID-19",
    "Amyotrophic Lateral Sclerosis",
    "Alzheimer Disease",
    "Glioblastoma",
]
THRESHOLD = 5          # 명세 §3 «재창출 후보 ≥ 5개». **내리지 않는다**
RUNS = 8               # 명세 §2 «질환당 8회». 나쁘게 나온 걸 더 안 돌린다
FALLBACK = "Idiopathic Pulmonary Fibrosis"   # 반증조건 발동 시


def measure(disease: str, n: int, k: int, variant: str) -> Dict[str, Any]:
    seen: set = set()
    known = gencheck.repodb_status(disease, seen=seen)
    print("    RepoDB %d종 (승인 %d) ← %s"
          % (len(known), sum(1 for v in known.values() if v == "Approved"),
             " | ".join(sorted(seen)) or "**매치 0건**"))
    rows = []
    for i in range(n):
        r = gencheck.once(disease, k, variant)
        g = gencheck.classify(r["약"], known)
        r["분류"] = {a: len(b) for a, b in g.items()}
        r["재창출후보"] = len(g["실패"]) + len(g["미상"])
        rows.append(r)
        print("    %d/%d  생성 %2d → 재창출 %2d  (승인 %d · 실패 %d · 미상 %d) · %s"
              % (i + 1, n, r["got"], r["재창출후보"], len(g["승인"]),
                 len(g["실패"]), len(g["미상"]), r["종료사유"]))
    sets = [set(x.lower() for x in r["약"]) for r in rows] or [set()]
    rep = [r["재창출후보"] for r in rows]
    return {
        "질환": disease, "RepoDB종수": len(known), "RepoDB매치": sorted(seen),
        "RepoDB승인": sum(1 for v in known.values() if v == "Approved"),
        "주기준": sum(1 for x in rep if x >= THRESHOLD),
        "교집합": len(set.intersection(*sets)),
        "실패후보낸실행": sum(1 for r in rows if r["분류"]["실패"] > 0),
        "규칙2위반실행": sum(1 for r in rows if r["분류"]["승인"] > 0),
        "재창출중앙": sorted(rep)[len(rep) // 2],
        "재창출최소": min(rep), "재창출최대": max(rep),
        "실행": rows,
    }


def pick(res: List[Dict[str, Any]]):
    """명세 §3 규칙을 **그대로** 적용한다. 사후 판단을 안 끼운다."""
    if all(r["주기준"] == 0 for r in res):
        return None, "반증조건 발동 — 넷 다 「≥%d개」가 0회다" % THRESHOLD
    order = {r["질환"]: i for i, r in enumerate(res)}
    best = sorted(res, key=lambda r: (-r["주기준"], -r["교집합"],
                                      -r["실패후보낸실행"], order[r["질환"]]))[0]
    tie = [r["질환"] for r in res if r["주기준"] == best["주기준"]]
    why = "주기준 %d/%d" % (best["주기준"], RUNS)
    if len(tie) > 1:
        why += " (동점 %d개 → 교집합 %d · 실패후보 %d · 순서)" % (
            len(tie), best["교집합"], best["실패후보낸실행"])
    return best, why


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="시연 질환 고르기 (명세 b9e45c7b662f)")
    ap.add_argument("--n", type=int, default=RUNS)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--variant", default="loose")
    ap.add_argument("--out", default="시연질환결과.json")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)

    print("명세 : 사전명세_시연질환.md (봉인 b9e45c7b662f)")
    print("후보 : %s" % " · ".join(CANDIDATES))
    print("규칙 : 「재창출 후보 ≥ %d개」인 실행 수 최다  →  동점이면 교집합 → 실패후보 → 순서"
          % THRESHOLD)
    print("비교군 : %s 는 **이미 8회 쟀다. 다시 안 돌린다.**" % FALLBACK)
    print("호출 : %d개 × %d회 = **%d회**" % (len(CANDIDATES), a.n,
                                          len(CANDIDATES) * a.n))
    print()
    if a.dry:
        print("--dry — 실호출을 안 한다. 배관만 확인하고 끝낸다.")
        return 0
    if not llm.available():
        print("⛔ LLM 이 설정돼 있지 않다. `.env` 를 봐라.")
        return 2

    # ⚠ **캐시 경로를 먼저 정한다** — 결함 240
    #
    #   `gencheck.main` 은 정하는데 이 모듈은 `gencheck.once` 를 직접 불러서
    #   **기본 경로(`pubmed_cache.json`)** 로 갔다. `BYPASS_CACHE` 는 **읽기만**
    #   끄고 **쓰기는 그대로**라, 08-18 첫 실행이 저장소 캐시에 항목을 썼다
    #   (화면에 «디스크 14099개와 병합한다(3 → 14101)» 이 찍혔다).
    #
    #   판정이 바뀌진 않지만 **동결에 가까운 파일을 실험이 건드렸다.**
    #   `CLAUDE.md §3-3`(*결과 파일을 확인 없이 덮어쓰지 마라*)의 이웃이다.
    import os as _o
    from ..io import cache as _cache
    scratch = "_demopick_cache.json"
    _cache.configure(scratch)

    old = llm.BYPASS_CACHE
    llm.BYPASS_CACHE = True        # 안 끄면 2회차부터 첫 답을 돌려줘 분산이 0
    res = []
    try:
        for d in CANDIDATES:
            print("── %s" % d)
            r = measure(d, a.n, a.k, a.variant)
            if not r["RepoDB종수"]:
                print("    ⚠ RepoDB 가 이 병명으로 **0종**이다 — 「위반 0」과")
                print("      「자료 없음」이 구별 안 된다. 이 줄을 그대로 적어라.")
            res.append(r)
            print()
    finally:
        llm.BYPASS_CACHE = old
        _cache.configure("pubmed_cache.json")     # 원래대로 돌려놓는다
        try:
            _o.path.exists(scratch) and _o.remove(scratch)
        except OSError:
            pass

    print("=" * 74)
    print("  %-30s %6s %6s %6s %6s %s"
          % ("질환", "≥%d회" % THRESHOLD, "교집합", "실패", "위반", "재창출(최소~최대·중앙)"))
    for r in res:
        print("  %-30s %4d/%d %6d %6d %6d   %d~%d · %d"
              % (r["질환"][:30], r["주기준"], a.n, r["교집합"],
                 r["실패후보낸실행"], r["규칙2위반실행"],
                 r["재창출최소"], r["재창출최대"], r["재창출중앙"]))
    print("  %-30s %4s   %6s %6s %6s   %s"
          % ("(비교) " + FALLBACK[:23], "0/8", "2", "2", "8", "0~8 · 0"))

    best, why = pick(res)
    print("=" * 74)
    if best is None:
        print("  ⛔ %s" % why)
        print("     **질환을 안 바꾼다. IPF 로 간다**(명세 §3 반증조건).")
        print("     넷을 재 봤지만 더 나은 것이 없었다 — 그대로 적는다.")
        chosen = FALLBACK
    else:
        chosen = best["질환"]
        print("  → **%s**   (%s)" % (chosen, why))
        print("     명세 §5 예측은 «COVID-19». %s"
              % ("맞았다." if chosen == "COVID-19"
                 else "**빗나갔다 — 그대로 적는다.**"))
    print()
    print("  ⓘ 넷 **전부**의 수치가 위 표와 JSON 에 있다. 안 고른 것도 남는다")
    print("    (명세 §4-3 — 안 고른 것을 안 적으면 이 절차가 무의미하다).")
    print("  ⓘ 이건 **발굴만** 본 것이다. 판정이 갈리는지는 깔때기를 태워야 안다.")

    w = safeio.save_json({"명세": "b9e45c7b662f", "문턱": THRESHOLD, "n": a.n,
                          "선택": chosen, "사유": why, "결과": res},
                         a.out, indent=1)
    print("=" * 74)
    print("→ %s (백업 %s)" % (w["경로"], w["상태"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
