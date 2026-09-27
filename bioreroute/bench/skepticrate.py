# -*- coding: utf-8 -*-
"""반박 증거 회수율 — 제안서 §4 B3 이 지표로 지정했는데 안 재고 있었다

## 왜 이걸 만드나

제안서 §4 의 기준선 표가 이렇게 적혀 있다 —

    B3  + 회의주의자 토론 | 반박 능동 탐색 | **반박 증거 회수율**

**지표를 이름까지 지정해 놓고 한 번도 수치로 낸 적이 없다.**
그래서 §3.3-4(다중 에이전트 토론)가 🟡 에 머물러 있었다.

그리고 그동안 §3.3-4 를 🟡 로 둔 **사유가 틀려 있었다**(결함 121).
*"`gate_skeptic` 있으나 토론 구조는 아님"* 이라 적었는데 —

> 제안서 §2: *"생성기와 회의주의자(Red-Team) 에이전트의 토론 구조다.
> **다만 대칭적 논쟁이 아니다.** … 그 역할도 자유 논쟁이 아니라
> **반박 증거의 회수로 좁혀져 있다.** 목표가 토론의 양이 아니라
> 반박 회수율이기 때문이다."*

**제안서가 스스로 «대칭 논쟁 아님» 이라 정의했다.** 없는 걸 못 만든 게
아니라 제안서보다 엄격한 잣대를 우리가 만들어 우리를 깎고 있었다.

## 무엇을 세는가 — **회의주의자가 «새로» 가져온 것만**

`gate_skeptic` 은 별도 질의로 확증 설계·부정 결과를 강제로 끌어오고
**이미 읽은 PMID 는 건너뛴다.** 그래서 trail 에 적히는 `반박 +N` 은
**RAG 단계에서 안 보였던 것**이다. 즉 이 수치가 곧 B2→B3 제거실험의
효과이고, 따로 B3 를 다시 돌릴 필요가 없다.

    "추가 초록 3건 → 반박 +0 · 지지 +2  (3건 중 신규 2 | 1건 중 신규 1)"
                      ↑ 이것만 센다

## 이 수치가 말하지 않는 것 — 먼저 적는다

- **판정이 바뀌었는지는 못 잰다.** 그건 B2 와 B3 를 같은 표본에 돌려
  짝비교해야 하고, 저장된 state 는 B5 하나뿐이다
- **회수율이 높은 게 좋은 것도 아니다.** 반박이 많다는 건 후보가 나빴다는
  뜻일 수도 있다. 이건 «회의주의자가 일을 하는가» 의 검사이지 성능이 아니다
- 표본이 작다. **Wilson 구간을 항상 같이 낸다**(`CLAUDE.md §4`)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

STATE_DEFAULT = "gen_state.json"

# "추가 초록 3건 → 반박 +0 · 지지 +2  (3건 중 신규 2 | 1건 중 신규 1)"
PAT = re.compile(r"반박 \+(\d+) · 지지 \+(\d+)")
PAT_ABS = re.compile(r"추가 초록 (\d+)건")


def wilson(k: int, n: int) -> Tuple[float, float]:
    if not n:
        return (0.0, 0.0)
    z, p = 1.959963985, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def measure(path: str = STATE_DEFAULT) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"ok": False, "error": "state 파일 없음: %s — 없는 걸 0으로 세지 않는다" % path}
    d = json.load(open(path, encoding="utf-8"))
    cfg = d.get("config")
    cands = d.get("candidates") or []
    out: Dict[str, Any] = {"ok": True, "path": path, "config": cfg,
                           "n_candidates": len(cands), "n_with_skeptic": 0,
                           "n_refute_ge1": 0, "n_support_ge1": 0,
                           "sum_refute": 0, "sum_support": 0,
                           "n_no_new_abstract": 0, "unparsed": []}
    for c in cands:
        sk = [t for t in (c.get("trail") or []) if t.get("gate") == "skeptic"]
        if not sk:
            continue
        det = sk[-1].get("detail") or ""
        m = PAT.search(det)
        if not m:
            # ⚠ **분모에 넣고 분자에서 빼면 «못 읽었다» 가 «0건» 이 된다**
            #   (결함 150). 이 파일 보고서가 스스로 *"형식이 안 맞아 못 센
            #   것 — **0으로 세지 않는다**"* 라고 적어 놓고 코드는 세고
            #   있었다. 결함 141·144 와 같은 유형 — 서로 다른 실패를 한 칸에.
            out["unparsed"].append(det[:80])
            continue
        out["n_with_skeptic"] += 1          # **파싱된 것만 분모에 든다**
        ref, sup = int(m.group(1)), int(m.group(2))
        out["sum_refute"] += ref
        out["sum_support"] += sup
        if ref:
            out["n_refute_ge1"] += 1
        if sup:
            out["n_support_ge1"] += 1
        ma = PAT_ABS.search(det)
        if ma and int(ma.group(1)) == 0:
            out["n_no_new_abstract"] += 1
    n = out["n_with_skeptic"]
    out["n_unparsed"] = len(out["unparsed"])
    out["rate"] = out["n_refute_ge1"] / n if n else None
    out["rate_ci"] = wilson(out["n_refute_ge1"], n) if n else None
    return out


def report(path: str = STATE_DEFAULT) -> str:
    r = measure(path)
    if not r["ok"]:
        return "**측정 불가** — %s" % r["error"]
    n = r["n_with_skeptic"]
    lo, hi = r["rate_ci"] or (0, 0)
    L = ["# 반박 증거 회수율 — 제안서 §4 B3 지표", "",
         "> 자료 `%s` (구성 **%s**) · **LLM 0회** — 이미 저장된 trail 을 셀 뿐이다"
         % (r["path"], r["config"]), ""]
    L += ["## 주지표", "", "```",
          "회의주의자가 돈 후보                  %d" % n,
          "**반박을 1건 이상 새로 회수한 후보**   %d  = **%.1f%%**  [%.1f–%.1f]"
          % (r["n_refute_ge1"], 100 * (r["rate"] or 0), 100 * lo, 100 * hi),
          "```", "",
          "**«새로» 가 요점이다.** `gate_skeptic` 은 이미 읽은 PMID 를 건너뛰므로",
          "여기 세어진 반박은 **RAG 단계에서 안 보였던 것**이다. 그래서 이 수치가",
          "B2→B3 제거실험의 효과와 같고, B3 를 따로 다시 돌릴 필요가 없다.", ""]
    L += ["## 같이 나온 불리한 숫자 — **먼저 적는다**", "", "```",
          "회수한 반박 총건수   %3d" % r["sum_refute"],
          "회수한 지지 총건수   %3d" % r["sum_support"], "```", ""]
    if r["sum_refute"] and r["sum_support"]:
        ratio = r["sum_support"] / r["sum_refute"]
        L += ["**부정 결과를 노린 전용 질의가 지지 증거를 %.1f배 더 물어 온다.**" % ratio,
              "",
              "이걸 두 가지로 읽을 수 있고, 우리 자료로는 **가르지 못한다** —", "",
              "- 문헌 자체가 긍정 편향이다 (그렇다면 이 비율은 회의주의자의 실패가 아니다)",
              "- 질의가 충분히 선택적이지 않다 (그렇다면 고칠 여지가 있다)", "",
              "> **둘을 가르려면** 같은 질의를 «부정 결과» 어구 없이 돌려 비율을",
              "> 견줘야 한다. 그건 대조군을 새로 박는 일이고 **명세가 필요하다.**",
              "> 지금은 **모른다고 적는다.**", ""]
    L += ["## 이 수치가 말하지 않는 것", "",
          "- **판정이 바뀌었는지는 못 잰다.** B2·B3 를 같은 표본에 돌려 짝비교해야 하는데",
          "  저장된 state 는 %s 하나뿐이다" % r["config"],
          "- **회수율이 높은 게 좋은 것이 아니다.** 반박이 많다는 건 후보가 나빴다는",
          "  뜻일 수도 있다. 이건 «회의주의자가 일을 하는가» 의 검사이지 성능이 아니다",
          "- 표본 %d 은 작다. 구간이 넓은 것을 그대로 읽어라" % n, ""]
    if r["unparsed"]:
        L += ["## 형식이 안 맞아 못 센 것 — **0으로 세지 않는다**", ""]
        for u in r["unparsed"][:5]:
            L.append("- `%s`" % u)
        L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    # 리디렉션돼도 안 깨지게 한다 (결함 131) — `report_io` 참조
    from .report_io import utf8_stdout
    utf8_stdout()
    ap = argparse.ArgumentParser(description="반박 증거 회수율 (LLM 0회)")
    ap.add_argument("--state", default=STATE_DEFAULT)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.json:
        print(json.dumps(measure(a.state), ensure_ascii=False, indent=1))
        return 0
    print(report(a.state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
