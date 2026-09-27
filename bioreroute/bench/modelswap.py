# -*- coding: utf-8 -*-
"""모델 교체 실측 — **명세 `사전명세_모델교체.md`(봉인 `8112fe04f798`) 집행기.**

    py -m bioreroute.bench.modelswap              98쌍 · A·A′·B · 27호출
    py -m bioreroute.bench.modelswap --dry        배관만
    py -m bioreroute.bench.modelswap --small gpt-4o-mini

## 무엇을 재고 무엇을 안 재나 (명세 §1)

| | |
|---|---|
| 잰다 | **모델을 바꾸면 판정 경로가 달라지는가** |
| **안 잰다** | **비용.** 두 모델의 단가를 실측 안 했다 |
| **안 잰다** | **어느 쪽이 옳은가.** 라벨을 안 쓴다 |

*"더 싼 모델로 내려도 된다"* 를 말하려면 가격표가 필요한데 우리는 그걸
안 쟀다. **모르는 것을 주장하지 않는다.**

## 왜 라우터인가 (명세 §2)

`ROLE_OF` 의 소형 역할 넷 중 **`router` 가 판정 경로를 직접 가른다** —
기전 5분류가 `ROUTE` 를 거쳐 **「도킹을 돌리나」** 가 된다. 제안서 §2.4 가
*«도킹을 건너뛰는 판단»* 을 창의성으로 내세운 그 자리다.

`discover` 는 **안 잰다** — 모델과 무관하게 이미 흔들린다(결함 236).
흔들리는 것 위에 모델 비교를 얹으면 원인을 못 가른다.

## 왜 **세 번** 도는가 (명세 §8)

```
A   gpt-5.4-mini      ← 현행
A′  gpt-5.4-mini      ← **같은 모델 두 번.** 잔여 비결정성의 크기
B   gpt-4o-mini(소형) ← 교체
```

오늘 실측에서 **온도 0 인데도 발굴이 10개와 2개로 갈렸다.** 그러면
«A vs B 불일치» 를 그냥 모델 탓으로 못 돌린다. **A vs A′ 이 잡음의
크기를 준다.** 그 위에서 읽는다.

> **A vs A′ 불일치 ≥ A vs B 불일치** 이면 «모델 교체의 영향이 잡음보다
> 작다» 이고, 그건 **합격보다 강한 결과**다.

## ⚠ 캐시를 끈다

같은 프롬프트·같은 모델이면 A′ 이 A 의 답을 그대로 받아 **불일치가
구조적으로 0** 이 된다. 그러면 이 모듈은 아무것도 안 재고 «잡음 없음» 이라
말한다 — 그게 이 설계에서 가장 위험한 자기기만이다.
"""
from __future__ import annotations

import argparse
import collections
import csv
import os
import sys
from typing import Any, Dict, List, Tuple

from ..agents import router as _router
from ..io import cache, llm, safeio
from . import stats as _st

SAMPLE = "bench_matched.csv"
SMALL_ENV = "BIOREROUTE_MODEL_SMALL"
THRESH = 0.05        # 명세 §4 — 불일치율 문턱. **내리지 않는다**
CI_MAX = 0.15        # 명세 §4 — Wilson 95% 상한


# ── 09-25 · BYOM 점들 — **결과 파일에서** 읽는다 ─────────────────────
#   08-18 첫 점(mini↔4o-mini)과 09-25 본선 점 둘(terra↔luna · terra↔sol).
#   발표 장 · 결과 문서 · 대본이 이 함수 하나에서 수를 받는다(손 숫자 금지).
POINTS = (("08-18 첫 점", "모델교체결과.json"),
          ("09-25 본선 · luna", "모델교체_본선_luna.json"),
          ("09-25 본선 · sol", "모델교체_본선_sol.json"))


def points(root: str = ".") -> List[Dict[str, Any]]:
    """있는 점만 돌려준다. **«확인실패» 는 점이 아니다**(결함 242 — 요청하지 않은 모델이 답함)."""
    import json as _json
    out = []
    for tag, f in POINTS:
        p = os.path.join(root, f)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            d = _json.load(fh)
        if d.get("판정") == "확인실패":
            continue
        out.append({"점": tag, "파일": f, "소형": d.get("소형"), "판정": d.get("판정"),
                    "명세": d.get("명세"), "n": d.get("n"),
                    "교체": d.get("교체_AB") or {}, "잡음": d.get("잡음_AA") or {}})
    return out


def load_pairs(path: str = SAMPLE) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8-sig") as fh:
        return [{"drug": r["drug"], "disease": r["indication"]}
                for r in csv.DictReader(fh) if r.get("drug")]


def run_once(pairs, small: str = "") -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """소형 배정을 걸고 라우터를 돌린다. `small` 이 빈 문자열이면 현행.

    **누가 실제로 답했는지를 같이 돌려준다** — 결함 242.

    `llm.py:194` 가 429 때 `FALLBACKS` 로 자동 대체하는데, 이 저장소의
    `.env` 는 **첫 예비 모델이 `gpt-4o-mini`** 다. **그게 B 팔의 모델이다.**
    A 가 한도에 걸려 예비로 넘어가면 **A 도 `gpt-4o-mini` 가 답하고**
    «불일치 0» 이 나온다 — 그러면 이 실험은 **아무것도 안 재고 합격**한다.

    라벨(`BIOREROUTE_MODEL_SMALL`)은 **무엇을 요청했나**이지
    **무엇이 답했나**가 아니다. 둘을 구별하지 않으면 안 된다.
    """
    old = os.environ.get(SMALL_ENV)
    if small:
        os.environ[SMALL_ENV] = small
    else:
        os.environ.pop(SMALL_ENV, None)
    n0 = len(llm.call_log())
    try:
        out = _router.classify(pairs)
    finally:
        if old is None:
            os.environ.pop(SMALL_ENV, None)
        else:
            os.environ[SMALL_ENV] = old
    served: Dict[str, int] = {}
    for rec in llm.call_log()[n0:]:
        if rec.get("cached"):
            continue
        k = rec.get("served_by") or "?"
        served[k] = served.get(k, 0) + 1
    return out, served


def compare(x: List[Dict], y: List[Dict], pairs) -> Dict[str, Any]:
    """두 실행을 짝비교. **경로가 주지표, 5분류는 부지표.**"""
    dock = [(_router.docking_advised(a), _router.docking_advised(b))
            for a, b in zip(x, y)]
    mech = [((a or {}).get("mech", "?"), (b or {}).get("mech", "?"))
            for a, b in zip(x, y)]
    dis_d = [i for i, (a, b) in enumerate(dock) if a != b]
    dis_m = [i for i, (a, b) in enumerate(mech) if a != b]
    n = len(dock)
    lo, hi = _st.wilson(len(dis_d), n) if n else (0.0, 0.0)
    return {
        "n": n,
        "경로불일치": len(dis_d), "경로불일치율": len(dis_d) / n if n else 0.0,
        "Wilson": [round(lo, 4), round(hi, 4)],
        "분류불일치": len(dis_m),
        "분류일치율": (n - len(dis_m)) / n if n else 0.0,
        "kappa": round(_kappa([a for a, _ in mech], [b for _, b in mech]), 4),
        "경로불일치쌍": [{"약": pairs[i]["drug"], "질환": pairs[i]["disease"][:28],
                     "A": mech[i][0], "B": mech[i][1],
                     "A도킹": dock[i][0], "B도킹": dock[i][1]} for i in dis_d],
    }


def _kappa(a: List[str], b: List[str]) -> float:
    """Cohen κ. **직접 센다** — 손계산해서 문서에 옮기지 않는다(§4)."""
    n = len(a)
    if not n:
        return 0.0
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = collections.Counter(a), collections.Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 0.0 if pe >= 1.0 else (po - pe) / (1 - pe)


def _fmt(d: Dict[str, int]) -> str:
    return ", ".join("%s×%d" % kv for kv in sorted(d.items(), key=lambda x: -x[1])) or "**0회**"


def _check_served(sA, sA2, sB, small: str) -> List[str]:
    """**요청한 모델이 실제로 답했나.** 아니면 판정을 안 낸다."""
    out = []
    for tag, s, want in (("A", sA, llm.MODEL), ("A′", sA2, llm.MODEL),
                         ("B", sB, small)):
        if not s:
            out.append("%s: 실호출 0회 — 전부 캐시였다. 비교가 성립 안 한다" % tag)
        elif set(s) != {want}:
            out.append("%s: `%s` 를 요청했는데 **%s** 가 답했다 — 예비 모델로 넘어갔다"
                       % (tag, want, _fmt(s)))
    if not out and set(sA) == set(sB):
        out.append("A 와 B 를 **같은 모델**이 답했다(%s) — 교체가 안 일어났다"
                   % _fmt(sA))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="모델 교체 실측 (명세 8112fe04f798)")
    ap.add_argument("--sample", default=SAMPLE)
    ap.add_argument("--small", default="gpt-4o-mini")
    ap.add_argument("--out", default="모델교체결과.json")
    ap.add_argument("--dry", action="store_true")
    # 09-25 · 본선 BYOM(명세 `사전명세_모델교체_본선.md` §5)도 이 집행기를 쓴다.
    #   결과 파일의 «명세» 칸이 08-18 해시로 박혀 있으면 **어느 명세의 집행인지**
    #   가 틀리게 남는다 — 라벨만 받는다(판정 규칙·문턱은 안 바뀐다).
    ap.add_argument("--spec", default="8112fe04f798",
                    help="이 실행을 다스리는 봉인 명세의 해시(앞 12자리) — 기록용")
    a = ap.parse_args(argv)

    pairs = load_pairs(a.sample)
    calls = -(-len(pairs) // 12)
    print("명세 : 봉인 %s%s" % (a.spec, " (사전명세_모델교체.md)" if a.spec == "8112fe04f798" else ""))
    print("표본 : %s · **%d쌍** (라벨 안 씀)" % (a.sample, len(pairs)))
    print("배정 : A=%s · A′=%s(같은 것) · B 소형=%s"
          % (llm.MODEL, llm.MODEL, a.small))
    print("호출 : %d회 × 3 = **%d회**" % (calls, calls * 3))
    print("기준 : 경로 불일치율 ≤%.0f%% **그리고** Wilson 상한 ≤%.0f%%"
          % (THRESH * 100, CI_MAX * 100))
    print("       ⓘ **비용은 안 잰다**(명세 §1). 가격표를 실측 안 했다.")
    print()
    if a.dry:
        print("--dry — 실호출을 안 한다. 배관만 확인하고 끝낸다.")
        return 0
    if not llm.available():
        print("⛔ LLM 이 설정돼 있지 않다. `.env` 를 봐라.")
        return 2

    tmp, old = "_swap_cache.json", llm.BYPASS_CACHE
    cache.configure(tmp)
    llm.BYPASS_CACHE = True     # 안 끄면 A′ 이 A 의 답을 받아 잡음이 0이 된다
    try:
        print("A  … 현행 배정")
        A, sA = run_once(pairs)
        print("     답한 모델: %s" % _fmt(sA))
        print("A′ … 같은 배정 (잡음 측정)")
        A2, sA2 = run_once(pairs)
        print("     답한 모델: %s" % _fmt(sA2))
        print("B  … 소형 = %s" % a.small)
        B, sB = run_once(pairs, a.small)
        print("     답한 모델: %s" % _fmt(sB))
    finally:
        llm.BYPASS_CACHE = old
        cache.configure("pubmed_cache.json")
        try:
            os.path.exists(tmp) and os.remove(tmp)
        except OSError:
            pass

    noise = compare(A, A2, pairs)
    swap = compare(A, B, pairs)

    # ── **누가 답했나를 먼저 본다** — 결함 242 ─────────────────────
    #   라벨은 «무엇을 요청했나» 이지 «무엇이 답했나» 가 아니다.
    #   A 가 예비 모델(첫 항목이 gpt-4o-mini!)로 넘어갔으면 A 도 B 도
    #   같은 모델이 답한 것이고, 그러면 이 실험은 **아무것도 안 잰다.**
    bad = _check_served(sA, sA2, sB, a.small)
    if bad:
        print()
        print("  ⛔ **모델 확인 실패 — 판정을 안 낸다**")
        for line in bad:
            print("     %s" % line)
        print("     `.env` 의 `BIOREROUTE_MAX_CALLS`·한도·429 를 확인하고 다시 돌려라.")
        safeio.save_json({"명세": a.spec, "판정": "확인실패",
                          "사유": bad, "답한모델": {"A": sA, "A2": sA2, "B": sB}},
                         a.out, indent=1)
        return 3

    print()
    print("=" * 72)
    print("  %-26s %10s %10s" % ("", "A vs A′ (잡음)", "A vs B (교체)"))
    print("  %-26s %10s %10s"
          % ("경로 불일치", "%d/%d" % (noise["경로불일치"], noise["n"]),
             "%d/%d" % (swap["경로불일치"], swap["n"])))
    print("  %-26s %9.1f%% %9.1f%%"
          % ("경로 불일치율", noise["경로불일치율"] * 100,
             swap["경로불일치율"] * 100))
    print("  %-26s %10s %10s"
          % ("Wilson 95%",
             "[%.1f–%.1f%%]" % (noise["Wilson"][0] * 100, noise["Wilson"][1] * 100),
             "[%.1f–%.1f%%]" % (swap["Wilson"][0] * 100, swap["Wilson"][1] * 100)))
    print("  %-26s %9.1f%% %9.1f%%"
          % ("5분류 일치율", noise["분류일치율"] * 100, swap["분류일치율"] * 100))
    print("  %-26s %10.3f %10.3f" % ("Cohen κ", noise["kappa"], swap["kappa"]))
    print("=" * 72)

    # ── 명세 §8 반증조건을 **먼저** 본다 ──────────────────────────
    if noise["경로불일치"] >= swap["경로불일치"] and swap["경로불일치"] > 0:
        verdict, why = "잡음보다 작다", (
            "A vs A′ 불일치 %d ≥ A vs B 불일치 %d — **모델 교체의 영향이 "
            "잔여 비결정성보다 크지 않다.** 합격보다 강한 결과다."
            % (noise["경로불일치"], swap["경로불일치"]))
    elif noise["경로불일치"] > 0 and swap["경로불일치"] <= noise["경로불일치"]:
        verdict, why = "못 가른다", (
            "같은 모델로도 %d건이 갈린다. 그 크기 안에서는 «모델 탓» 을 "
            "못 돌린다(명세 §8)." % noise["경로불일치"])
    else:
        ok = (swap["경로불일치율"] <= THRESH and swap["Wilson"][1] <= CI_MAX)
        verdict = "합격" if ok else "미달"
        why = ("불일치율 %.1f%%(≤%.0f%%) · Wilson 상한 %.1f%%(≤%.0f%%)"
               % (swap["경로불일치율"] * 100, THRESH * 100,
                  swap["Wilson"][1] * 100, CI_MAX * 100))
        if noise["경로불일치"]:
            why += "  ⚠ 잡음 %d건 위에서 읽은 값이다" % noise["경로불일치"]
    print("  → **%s**  — %s" % (verdict, why))

    if swap["경로불일치쌍"]:
        print()
        print("  경로가 갈린 쌍 (몇 건인지보다 **무엇이** 갈렸나가 쓰인다)")
        for d in swap["경로불일치쌍"][:12]:
            print("    %-22s %-26s %s→%s  도킹 %s→%s"
                  % (d["약"][:22], d["질환"], d["A"], d["B"],
                     d["A도킹"], d["B도킹"]))
    print()
    print("  ⓘ **어느 쪽이 옳은지는 안 쟀다.** 둘이 똑같이 틀렸을 수도 있다(명세 §7).")
    print("  ⓘ 이 결과가 좋아도 **`BIOREROUTE_MODEL` 기본값을 안 바꾼다**(명세 §5-5).")

    w = safeio.save_json({"명세": a.spec, "표본": a.sample,
                          "n": len(pairs), "소형": a.small,
                          "판정": verdict, "사유": why,
                          "답한모델": {"A": sA, "A′": sA2, "B": sB},
                          "잡음_AA": noise, "교체_AB": swap}, a.out, indent=1)
    print("=" * 72)
    print("→ %s (백업 %s)" % (w["경로"], w["상태"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
