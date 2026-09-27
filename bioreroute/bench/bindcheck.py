# -*- coding: utf-8 -*-
"""라우터 기전 판단을 **결합 데이터로 교차 검증**한다 (2026-09-01).

## 무엇을 묻나

라우터는 *"이 약은 표적에 **직접** 붙는다"* 또는 *"**간접** 작용이다"*
라고 말하고, 그 말에 따라 검증 경로가 갈린다(도킹을 할지 말지).
**그 말이 맞는지 우리는 지금까지 확인한 적이 없다.**

09-01 실측에서 **39.6% 가 「직접 결합」을 주장**한다(직접·병원체 13.9%
+ 직접·숙주 25.7%). 그러면 물어야 한다 — **정말 붙는가?**

## ⛔ 예측을 **실행 전에** 고정한다

`CLAUDE.md §3-2` 와 사전명세 정신이다. 결과를 보고 기준을 고치면
그건 측정이 아니라 조작이다. **아래 표는 첫 실행 전에 적혔다.**

    라우터가 말한 것        ChEMBL 에서 기대하는 것
    ─────────────────────────────────────────────
    직접·병원체 / 직접·숙주   **강함**  pChEMBL ≥ 7
    간접                    **약함 또는 없음**  < 5 · 근거없음
    오프타겟                **예측하지 않는다** ↓
    불명                    **예측하지 않는다**

⚠ **오프타겟을 예측에서 빼는 이유.** 「오프타겟」은 *"본래 표적이
아닌 부수 작용이 치료 효과의 근거"* 라는 뜻이다. 그러면 **본래
표적에는 강하게 붙는 것이 정상**이다 — fluvoxamine 은 SSRI 이므로
SLC6A4 에 강하게 붙고, 그게 COVID 효과의 이유인지는 별개 문제다.
**강해도 약해도 라우터가 틀린 게 아니므로 채점에서 뺀다.**

## ⚠ 「없음」을 「반증」으로 읽지 마라

ChEMBL 에 활성이 없다고 결합을 안 하는 것이 아니다. 오래된 약,
특허에만 있는 데이터는 안 실린다. 그래서 `근거없음` 은 **신뢰도
강등 신호**이지 기각 사유가 아니다(`io/binding` 의 같은 주의).
그리고 **`조회불가`(네트워크 실패)는 채점에서 아예 뺀다** — 결함 35.

## 사용법

    py -m bioreroute.bench.bindcheck                 구운 사례 6건
    py -m bioreroute.bench.bindcheck --trail 궤적_0907.json
        ← 9/7 궤적이 나오면 **84쌍으로 확대**된다

**LLM 0회.** ChEMBL HTTP 조회만 하고 캐시된다.
"""
import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from ..io import binding

# ── 사전 고정 예측 (위 ⛔ 참조) ──────────────────────────────────────
EXPECT = {
    "직접·병원체": "강함",
    "직접·숙주": "강함",
    # ⚠ 09-01 첫 실행에서 **「간접」을 뺐다** — 아래 이유
    # 오프타겟·불명도 **일부러 없다**
}

# ── ⚠ 09-01 · 첫 실행이 25% 였고, **그게 도구의 결함이었다** ─────────
#
#     hydroxychloroquine  간접  지지 6.50  ❌
#     metformin           간접  지지 6.57  ❌
#     rifampin            직접  근거없음   ❌
#
# 셋 다 **약이 아니라 내 설계가 틀렸다.**
#
# **① 「간접」은 이 도구로 반증할 수 없다.** 「간접」의 정의가
#    *"단백질 결합이 아니라 pH·막 성질·대사 경로를 통해 작용한다"*
#    이다. **주장하는 표적이 없다.** 표적을 안 주면 `verify` 는 그
#    약의 **모든 활성 중 최고**를 보는데, 어떤 약이든 어딘가엔 활성이
#    있으므로 **「간접」 예측은 구조적으로 항상 실패한다.**
#    metformin 이 6.57 로 나온 것이 그 예다(승우가 probe 로 본 첫
#    레코드는 4.54 였다 — 다른 표적이다).
#
#    → **채점에서 뺀다.** 「간접」을 반증하려면 *"이 약이 실제로는
#      X 에 강하게 붙는다"* 는 **대안 표적**이 있어야 하고, 그건
#      이 도구가 아니라 사람이 하는 일이다.
#
# **② rifampin 은 도구가 표적을 못 찾은 것**이지 결합이 없는 게
#    아니다. 활성 레코드에 표적 **이름이 없고 ID 만** 있다 —
#    `io/binding.target_id` 로 고쳤다.
#
# 남은 채점 대상은 **「직접·병원체」·「직접·숙주」** 뿐이고, 구운 사례
# 6건에서는 **2건**이다. 표본이 작지만 **틀린 채점보다 낫다.**
# 9/7 궤적(84쌍)이면 라우터 실측상 직접이 약 40% 이므로 **~34건**이다.
STRONG_OK = {"지지"}      # 강함 예측을 **만족**
STRONG_BAD = {"경보"}     # 강함 예측을 **어김** — 약하게 붙는데 「직접」이라 했다

# ── ⚠⚠ 09-01 셋째 실행 · **「없음」을 「틀림」으로 세고 있었다** ──────
#
# rifampin 이 세 번 다 ❌ 였는데, 셋째 판에서 원인이 나왔다 —
# **「근거없음」을 어긋남으로 채점하고 있었다.**
#
# 「근거없음」은 *"라우터가 틀렸다"* 가 아니라 *"ChEMBL 에 그 결합의
# IC50/Ki 자료가 없다"* 다. rifampin 은 **1960년대 약**이고 결핵약
# 활성은 대개 **MIC**(세포 기반)로 재는데 우리는 `IC50,Ki,Kd,EC50`
# 만 조회한다. **자료가 없는 것이지 결합을 안 하는 게 아니다.**
#
# **이것은 결함 35 의 재발이다.** 그때는 *"조회 실패를 0건으로 세면
# 네트워크 장애가 «발견»이 된다"* 였고, 이번은 *"자료 부재를 어긋남
# 으로 세면 데이터가 없다는 사실이 «반증»이 된다"* 다. **같은 실수의
# 다른 얼굴**이고, 하필 **우리 논지를 지지하는 방향**이라 더 위험했다.
#
# `CLAUDE.md §2` — **«모른다»와 «차이 없다»는 다르다.**
# → 「근거없음」은 **채점 밖**(None)으로 뺀다. 그 대신 **몇 건이
#   그렇게 빠졌는지**를 표에 찍는다. 조용히 빠지면 그것도 거짓말이다.


def from_demo(path: str = "demo_cases.json") -> List[Dict[str, str]]:
    """구운 시연 사례에서 (약·기전·표적)을 뽑는다."""
    if not os.path.exists(path):
        return []
    d = json.load(open(path, encoding="utf-8"))
    out = []
    for one in d.get("사례") or []:
        q = str(one.get("질의") or "")
        drug = q.split("/")[0].strip()
        mech, tgt = "", ""
        for g in one.get("게이트") or []:
            if g.get("게이트") == "기전 라우터":
                det = g.get("설명") or ""
                m = re.match(r"([^·→]+)(?:·\s*([^→]+))?→", det)
                if m:
                    mech = m.group(1).strip()
                    tgt = (m.group(2) or "").strip()
                    # "직접" 만 잡히는 경우가 있어 원문에서 보강한다
                    for full in ("직접·병원체", "직접·숙주"):
                        if full in det:
                            mech = full
                    # ⚠ 09-01 · **접두어를 떼지 않으면 매칭이 0 이 된다**
                    #
                    #   detail 은 «직접·숙주 · JAK1 → evidence (high)» 형태라
                    #   위 정규식이 표적을 **«숙주 · JAK1»** 로 집어 온다.
                    #   그대로 `binding.verify(drug, target)` 에 넘기면 활성
                    #   본문에서 그 문자열을 못 찾아 **전부 「근거없음」**이
                    #   된다 — 그러면 「직접」예측이 통째로 어긋난 것처럼
                    #   보이고, **채점이 조용히 거짓말을 한다.**
                    #
                    #   승우가 손으로 `--target JAK1` 을 돌렸을 때는 14건이
                    #   맞았다. 사람이 정리해 준 것을 코드가 안 하고 있었다.
                    for pre in ("병원체", "숙주"):
                        if tgt.startswith(pre):
                            tgt = tgt[len(pre):].lstrip(" ·").strip()
        if drug:
            out.append({"drug": drug, "mech": mech, "target": tgt})
    return out


def from_trail(path: str, cfg: str = "B5") -> List[Dict[str, str]]:
    """9/7 이후 — `run.py` 가 남긴 궤적에서 뽑는다(84쌍).

    ## ⚠ 09-01 재검토에서 **이 함수가 빈 값을 내고 있었다**

    첫 판은 `mech` 와 `target` 을 **빈 문자열로 두었다.** 그러면
    `EXPECT` 에 없으므로 **모든 쌍이 채점 밖**이 되고, **84쌍을
    돌려도 채점 0건**이 나온다.

    원인은 `run.trail_summary` 가 `route` 만 남긴 것이었다 —
    **`route` 로는 「직접·숙주」와 「간접」을 못 가른다**(둘 다
    `evidence`). 그쪽에 `mech`·`target` 을 추가해 고쳤다.

    **한 번도 안 돌려 본 함수였다.** 모의 궤적으로 태워 보고 알았고,
    안 그랬으면 **9/7 에 알았을 것이다.**
    """
    d = json.load(open(path, encoding="utf-8"))
    rows = d.get("rows") or []
    tr = ((d.get("results") or {}).get(cfg) or {}).get("trail") or []
    out = []
    for r, t in zip(rows, tr):
        t = t or {}
        out.append({"drug": r.get("drug", ""),
                    "mech": t.get("mech", ""),
                    "target": t.get("target", ""),
                    "route": t.get("route")})
    return out


def score(mech: str, verdict: str,
          pchembl: Optional[float] = None) -> Optional[bool]:
    """예측이 맞았나. **채점 대상이 아니면 None** (오프타겟·불명·조회불가).

    ## ⛔ 09-13 · **「지지」를 그대로 믿으면 안 된다**

    `io/binding.verify()` 는 판정을 **셋**으로 나눈다 —

        pChEMBL ≥ 7   「지지」  "IC50 100 nM 이하급"
        5 ≤ p < 7     「지지」  **"중간 강도"**      ← 같은 라벨이다
        pChEMBL < 5   「경보」

    그런데 이 파일의 `EXPECT` 는 **「강함」(≥7)** 을 기대한다고 적어 두고
    `STRONG_OK = {"지지"}` 로 채점했다. **두 층의 문턱이 다른데 라벨이
    같아서**, 중간 강도가 «강함 예측 충족» 으로 들어갔다.

    **09-13 실측에서 21건 중 6건이 그랬다** — `rosuvastatin` 5.04 ·
    `erythromycin` 5.79 · `podophyllotoxin` 6.00 · `dasatinib` 6.00 ·
    `ketamine` 6.21. 그래서 **일치율이 67% 가 아니라 95% 로 찍혔다.**

    > 발표에 95%를 그대로 냈으면 *"pChEMBL 5.04 가 어떻게 강한 결합
    > 입니까"* 한 마디에 무너진다. **하필 우리에게 유리한 방향**이라
    > 더 위험했다 — 결함 35 계열이 같은 자리에서 또 나왔다.

    **주지표는 엄격(≥7)** 이고, 완화(≥5)는 **부지표로 병기**한다.
    `pchembl` 을 안 주면 옛 동작(라벨만 보기)으로 돌아가되 그건
    **완화 기준**이라는 뜻이다.
    """
    want = EXPECT.get(mech)
    # 조회불가(네트워크) · 근거없음(자료 부재) 둘 다 **채점 밖**이다.
    # 앞은 결함 35, 뒤는 그 재발 — 위 주석 참조.
    if want is None or verdict in ("조회불가", "근거없음"):
        return None
    if want == "강함":
        if verdict in STRONG_BAD:
            return False
        if verdict in STRONG_OK:
            if pchembl is None:
                return True                      # 옛 동작(=완화 기준)
            return pchembl >= binding.STRONG      # **엄격: ≥7 만 충족**
    return None


def run(cases: List[Dict[str, str]]) -> Dict[str, Any]:
    rows, hit, n = [], 0, 0
    hit_loose, mid_n = 0, 0          # 09-13 — 완화(≥5) 부지표 · 중간 건수
    for c in cases:
        v = binding.verify(c["drug"], c.get("target", ""))
        p = v.get("best_pchembl")
        ok = score(c.get("mech", ""), v["판정"], p)          # **엄격 ≥7**
        ok_loose = score(c.get("mech", ""), v["판정"], None)  # 완화 ≥5
        rows.append({**c, "판정": v["판정"], "pchembl": p,
                     "n_act": v.get("n"), "맞았나": ok,
                     "맞았나_완화": ok_loose, "왜": v.get("왜"),
                     "오류": v.get("오류")})
        if ok is not None:
            n += 1
            hit += 1 if ok else 0
            hit_loose += 1 if ok_loose else 0
            if ok_loose and not ok:
                mid_n += 1          # 중간 강도(5~7)로 통과한 것
    # ⚠ **왜 빠졌는지를 센다.** 조용히 빠지면 그것도 거짓말이다.
    scored_mech = [c for c in cases if c.get("mech", "") in EXPECT]
    none_data = sum(1 for x in rows
                    if x.get("mech") in EXPECT and x["판정"] == "근거없음")
    unreach = sum(1 for x in rows
                  if x.get("mech") in EXPECT and x["판정"] == "조회불가")
    # ⚠ 09-13 — **약이 겹친다.** 같은 약이 질환만 바꿔 여러 번 나오면
    #   결합 데이터는 **같은 값**이라 독립 관측이 아니다. 그대로 두면
    #   분모가 부풀어 보인다. 09-13 실측: 21건 중 독립 약물 18개.
    dr = [x["drug"] for x in rows if x.get("맞았나") is not None]
    return {"사례": rows, "채점대상": n, "일치": hit,
            "예측대상": len(scored_mech),
            "자료부재": none_data, "조회불가": unreach,
            "일치율": (hit / float(n)) if n else None,
            # ── 09-13 신설 ──────────────────────────────────────
            "일치_완화": hit_loose,
            "일치율_완화": (hit_loose / float(n)) if n else None,
            "중간강도": mid_n,
            "독립약물": len(set(dr))}


def _table(r: Dict[str, Any]) -> str:
    L = ["=" * 74,
         "라우터 기전 판단 ↔ ChEMBL 결합 활성 — **교차 검증** (LLM 0회)",
         "=" * 74,
         "  채점 대상은 **「직접·병원체」·「직접·숙주」** 뿐 — 강함(pChEMBL≥7)을 기대한다",
         "  ⚠ 「간접」은 **주장하는 표적이 없어 이 도구로 반증 불가** (09-01 확인)",
         "  ⚠ 「오프타겟」은 본래 표적에 붙는 게 정상이라 예측하지 않는다",
         ""]
    L.append("  %-18s %-12s %-10s %8s  %s" %
             ("약", "라우터", "ChEMBL", "pChEMBL", "판정"))
    L.append("  " + "-" * 70)
    for x in r["사례"]:
        mark = {True: "✅ 일치", False: "❌ 어긋남", None: "— 채점 밖"}[x["맞았나"]]
        pc = "%.2f" % x["pchembl"] if x["pchembl"] is not None else "-"
        L.append("  %-18s %-12s %-10s %8s  %s"
                 % (x["drug"][:17], (x["mech"] or "-")[:11], x["판정"], pc, mark))
    L += ["",
          "  예측 대상(「직접」) %d건 → 그중 **채점 가능 %d건 · 일치 %d건**"
          % (r.get("예측대상", 0), r["채점대상"], r["일치"])]
    if r["일치율"] is not None:
        # ── 09-13 · **두 기준을 나란히 찍는다** ─────────────────────
        #   하나만 찍으면 읽는 사람이 그걸 «그 수치» 로 받는다. 명세가
        #   말한 문턱은 ≥7 이므로 **그쪽이 주지표**다.
        L.append("  **일치율 %.0f%%** — pChEMBL **≥7**(명세가 말한 「강함」)"
                 % (100 * r["일치율"]))
        if r.get("일치율_완화") is not None and r.get("중간강도"):
            L.append("  (완화 기준 ≥5 로 세면 %.0f%% — **중간 강도 %d건**이"
                     % (100 * r["일치율_완화"], r["중간강도"]))
            L.append("   더 들어간다. 09-13까지 이 값이 «일치율» 로 찍혔다)")
    if r.get("독립약물") and r.get("채점대상"):
        L.append("  ⚠ 채점 %d건의 **독립 약물은 %d개** — 같은 약이 질환만"
                 % (r["채점대상"], r["독립약물"]))
        L.append("     바꿔 여러 번 나오면 결합 데이터는 **같은 값**이다.")
    if r.get("자료부재") or r.get("조회불가"):
        L.append("  ⚠ 채점에서 빠진 것 — 자료부재 %d · 조회불가 %d"
                 % (r.get("자료부재", 0), r.get("조회불가", 0)))
        if r.get("예측대상"):
            L.append("     → **「직접」 %d건 중 %.0f%%가 검증 자료 자체가 없다.**"
                     % (r["예측대상"],
                        100.0 * r.get("자료부재", 0) / r["예측대상"]))
            L.append("     ⚠ 이건 «라우터가 틀렸다» 가 **아니다.** 다만")
            L.append("       «반증하려 해도 잴 것이 없다» 는 **발견**이다.")
    L += ["",
          "  ⚠ **표본이 작다.** 9/7 궤적(84쌍)이 나오면 --trail 로 확대한다.",
          "  ⚠ 「근거없음」은 **채점 밖**이다 — *«라우터가 틀렸다»가 아니라*",
          "     *«ChEMBL 에 IC50/Ki 자료가 없다»* 이기 때문이다.",
          "     rifampin(1960년대 약)은 결핵약이라 활성이 대개 **MIC** 로",
          "     기록되고 우리는 IC50/Ki/Kd/EC50 만 조회한다.",
          "  ⚠ 「조회불가」(네트워크)도 채점에서 뺐다 — 결함 35.",
          "=" * 74]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="라우터 기전 판단을 ChEMBL 결합 활성으로 교차 검증 (LLM 0회)")
    # ⚠ 09-01 · **다른 도구와 어긋나 있었다.** `advsearch`·`namecheck` 은
    #   `--demo` 가 플래그인데 여기만 경로를 받아서 `--demo` 만 주면
    #   *"expected one argument"* 로 죽었다. `nargs="?"` 로 **둘 다** 받는다.
    ap.add_argument("--demo", nargs="?", const="demo_cases.json",
                    default="demo_cases.json",
                    help="구운 사례 파일 (경로 생략 가능)")
    ap.add_argument("--trail", default="", help="9/7 궤적 json (84쌍)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    cases = from_trail(a.trail) if a.trail else from_demo(a.demo)
    if not cases:
        print("  ⚠ 사례를 못 읽었다 — 경로를 확인하라")
        return 1
    r = run(cases)
    print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else _table(r))
    if a.out:
        from ..io.safeio import save_json
        w = save_json(r, a.out, indent=1)
        print("\n→ %s" % w.get("경로", a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
