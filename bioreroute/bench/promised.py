# -*- coding: utf-8 -*-
"""**제안서가 약속한 지표 중 «잴 수 있게만 만들어 둔 것»을 잰다** (2026-09-18).

## 왜 이 파일이 생겼나

승우 물음 — *"프로젝트의 기능으론 더 이상 추가할 것이 없다는 거지?"*
기능을 전수로 훑었더니 **없는 것은 기능이 아니라 «수치»** 였다.

    gates.false_negatives()   §8.2 도입 지표 셋째 — 위음성률
    gates.refute_recall()     §4.3 B3 확인 항목 — 반박 증거 회수율

둘 다 **08-06에 만들었고 호출부가 하나도 없다.** `연구기술보고서.md` 의
반증 조건 표에서 **F5 만 «미측정»** 으로 남아 있는 것이 전자다.

> `bench/fragility.py` 와 **정확히 같은 계열**이다 — 만들었는데 입구가
> 없었다. `preflight` 렌즈 3(배선)은 «코드가 도는가» 를 보고
> **«결과가 문서에 닿았는가» 는 안 본다.**

## 왜 지금 할 수 있나 — **LLM 0회**

둘 다 `RunState.candidates` 만 본다. `bench.run --save-state` 가 남긴
판정 원본에 필요한 것이 **전부 들어 있다** —

    c.refute       ← factcheck 에서 gates._rebuild_evidence 가 복원
    c.trail        ← 저장돼 있다 (09-18 2차에 복원 추가)
    c.label        ← 저장돼 있다 ("TP"|"TN")
    c.verdict      ← 저장돼 있다

**새로 돌릴 것이 없다.** 이미 있는 `상태_*.json` 으로 잰다.

## ⛔ 이것이 `§3-2` 에 안 걸리는 이유

게이트·문턱·프롬프트를 **하나도 안 건드린다.** 이미 난 판정을 **다르게
집계**할 뿐이다. 새 수치가 나오지만 **판정은 한 건도 안 바뀐다** —
`fragility` 와 같은 성질이다.

## 사용법

    py -m bioreroute.bench.promised --state 상태_0912_B5.json
    py -m bioreroute.bench.promised --state 상태_0912_B5.json --json
"""
import argparse
import json
import os
import sys
from typing import Any, Dict, List

from ..core import gates
from ..core.state import RunState
from .fragility import _candidate_from, _verdict


def from_state(path: str) -> Dict[str, Any]:
    """저장된 판정 원본 → 제안서 약속 지표 둘 + **왕복 검산**.

    ⭐ `fragility.from_state` 와 같은 검산을 붙인다 — 복원한 판정이
    저장된 판정과 다르면 **집계도 믿을 수 없다.**
    """
    if os.path.isdir(path):
        files = [os.path.join(path, f) for f in sorted(os.listdir(path))
                 if f.endswith(".json")]
    else:
        files = [path]
    cands, cfg, mismatch = [], "", []
    for fp in files:
        with open(fp, encoding="utf-8") as fh:
            d = json.load(fh)
        cfg = cfg or d.get("config", "")
        for cd in d.get("candidates") or []:
            c = _candidate_from(cd)
            saved = cd.get("verdict") or ""
            if saved and _verdict(c) != saved:
                mismatch.append((c.name, saved, _verdict(c)))
            cands.append(c)
    # ⚠ **09-19 렌즈 7** — `config={}` 는 «구성을 모른다» 가 아니라
    #   «이 집계가 구성을 안 본다» 는 뜻이다. `refute_recall` 도
    #   `false_negatives` 도 `st.config` 를 읽지 않는다(09-19 소스 확인).
    #   **구성을 보는 지표를 여기 더하면 이 줄부터 고쳐야 한다** —
    #   빈 dict 를 그대로 두면 «전부 꺼짐» 으로 조용히 읽힌다.
    #   실제 구성 이름은 `settings` 에 들어 있다.
    st = RunState(query_title="save-state 재집계", settings=cfg,
                  stamp="", candidates=cands, config={})
    labeled = sum(1 for c in cands if getattr(c, "label", None))
    return {
        "구성": cfg,
        "후보수": len(cands),
        "라벨_있는_후보": labeled,
        "재현_어긋남": mismatch,
        "위음성률(§8.2)": gates.false_negatives(st),
        "반박회수율(§4.3)": gates.refute_recall(st),
    }


def _table(r: Dict[str, Any]) -> str:
    fn = r["위음성률(§8.2)"]
    rr = r["반박회수율(§4.3)"]
    L = ["=" * 74,
         "제안서가 약속한 지표 — **잴 수 있게만 만들어 둔 것을 잰다** · LLM 0회",
         "=" * 74, "",
         "  구성 %s · 후보 %d · 라벨 있는 후보 %d"
         % (r["구성"] or "?", r["후보수"], r["라벨_있는_후보"]), ""]

    # ── ⭐ 검산 먼저 — 틀린 집계를 예쁘게 찍지 않는다 ────────────────
    bad = r["재현_어긋남"]
    if bad:
        L += ["  🔴 **복원한 판정이 저장된 판정과 다른 건 %d** — "
              "아래 수치를 인용하지 마라" % len(bad)]
        for nm, s, g in bad[:5]:
            L.append("       %-26s 저장 %s ≠ 복원 %s" % (nm[:25], s, g))
        L.append("")
    else:
        L += ["  ✅ 복원 판정이 저장 판정과 전부 일치 — 집계를 읽어도 된다", ""]

    L += ["  ── ① 위음성률 (제안서 §8.2 · 반증 조건 F5) " + "─" * 26]
    if fn.get("계산불가"):
        L += ["     ⚠ **계산 불가** — %s" % fn.get("왜", ""),
              "        `bench.run` 이 라벨을 실은 상태 파일이 필요하다"]
    else:
        L += ["     기각한 후보            %d건" % fn["기각_건수"],
              "     그중 **실제로 유효**   %d건" % fn["그중_실제_유효"],
              "     **위음성률**           %s   95%%CI %s"
              % (fn["위음성률"], fn["95%CI"])]
        if fn["이름"]:
            L.append("     놓친 것: %s" % ", ".join(fn["이름"][:6]))
        L += ["     ⚠ %s" % fn["주의"]]
    L += [""]

    L += ["  ── ② 반박 증거 회수율 (제안서 §4.3 B3 · §2) " + "─" * 22,
          "     반박 근거가 있는 후보   %s" % rr["반박근거_있는_후보"],
          "     반박 근거 총건          %d" % rr["반박근거_총건"],
          "     회의주의자가 **추가**   %d건 (기여율 %s)"
          % (rr["회의주의자_추가분"], rr["회의주의자_기여율"]),
          "     ⚠ %s" % rr["주의"],
          "",
          "  ⚠ **복원한 trail 에는 `provenance` 가 없다.** 상태 파일이 안 싣는다 —",
          "     이 집계로 «감사 추적이 있다» 를 주장하지 않는다.",
          "=" * 74]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="제안서 약속 지표 재집계 — 위음성률·반박회수율 (LLM 0회)")
    ap.add_argument("--state", default="",
                    help="bench.run --save-state 가 남긴 파일(또는 디렉토리)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.state:
        print("  ⚠ **판정 원본이 필요하다.**")
        print("     py -m bioreroute.bench.run --stratum A --configs B5 \\")
        print("        --out 궤적.json --save-state 상태.json")
        print("     py -m bioreroute.bench.promised --state 상태.json")
        return 1
    if not os.path.exists(a.state):
        print("  ⛔ 그런 경로가 없다: %s" % a.state)
        return 2
    r = from_state(a.state)
    print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else _table(r))
    # **어긋나면 종료 코드로도 알린다** — 표만 보고 넘기는 것을 막는다
    return 3 if r["재현_어긋남"] else 0


if __name__ == "__main__":
    sys.exit(main())
