# -*- coding: utf-8 -*-
"""발굴 안정성 — **같은 병명에 같은 프롬프트를 N번 던져 후보 수를 센다.**

    py -m bioreroute.bench.gencheck                          IPF · 8회
    py -m bioreroute.bench.gencheck --n 12 --disease "COVID-19"
    py -m bioreroute.bench.gencheck --dry                    배관만

## 왜 이걸 따로 재는가 — 결함 236·237

08-18 병렬 실측에서 **같은 병명·같은 코드로 10개와 2개가 갈렸다.**
12초 간격 두 실행이다. 그 위에서 잰 «배속» 은 **비교 자체가 성립 안 했다.**

감사 줄이 범인 둘을 먼저 지웠다 —

```
예비 모델 교체?   ✗  답한 모델이 `gpt-5.4-mini` 하나뿐
온도가 튀었나?    ✗  캐시 1,105건 전부 `@0.0` — 온도는 실제로 0이다
```

남은 후보가 셋이다.

```
① 추론 모델의 잔여 비결정성      온도 0이어도 완전 결정적이지 않다
② **출력이 잘렸다**              `finish_reason == "length"` 면 JSON 이 짧아진다
③ 모델이 그냥 적게 답한다        `finish_reason == "stop"` 인데 2개
```

**셋은 화면에서 갈린다.** ②면 출력 예산 문제라 고칠 수 있고, ①·③이면
프롬프트나 재시도로 가야 한다. **그래서 `finish_reason` 을 같이 찍는다.**

## 이 모듈은 깔때기를 안 태운다

병명 입구 한 번이 27호출인데 여기는 **N호출**이다. 재고 싶은 것이
발굴 하나뿐이라 나머지를 태울 이유가 없다.

## ⚠ 캐시를 **끈다**

캐시가 살아 있으면 두 번째부터 첫 답을 그대로 돌려줘 **분산이 0으로**
나온다. `llm.BYPASS_CACHE` 가 정확히 이걸 위해 있다(재시험 신뢰도 측정).
끄지 않으면 이 모듈은 **아무것도 안 재고 «완전히 안정적» 이라고 말한다.**
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
from typing import Any, Dict, List, Optional

from ..agents import discover as _dis
from ..io import cache, llm, safeio


# ══════════════════════════════════════════════════════════════════
#  «생성 수» 와 «재창출 후보 수» 는 다르다 — 결함 237
#
#  발굴 프롬프트 **규칙 2** 가 이렇게 적혀 있다 —
#
#    > **이 질환에 이미 승인된 약물은 제외한다.**
#    > 그건 재창출이 아니라 표준치료다.
#
#  08-18 IPF 실측에서 모델이 **8/8 전부** 그 규칙을 어겼다.
#  `Nintedanib`·`Pirfenidone` 이 매번 1·2위로 나오는데 **둘 다 IPF 승인약**이다.
#  그리고 **6/8 은 그 둘만** 냈다 — 즉 **재창출 후보가 0개**다.
#
#  «생성 2개» 라고 적으면 «적게 나왔다» 로 읽힌다. **틀렸다.**
#  실제로는 **하나도 안 나왔고**, 나온 둘은 규칙 위반이다.
#
#  ⚠ **프롬프트는 안 고친다.** `사전명세_생성실험` 이 이 프롬프트로 340건을
#    쟀다. 결과를 보고 프롬프트를 고치면 그건 `CLAUDE.md §3-2` 다.
#    **고치는 대신 센다.** 자료(RepoDB)는 처음부터 있었고 배선만 없었다.
# ══════════════════════════════════════════════════════════════════

REPODB = "RepoDB.csv"


def _toks(s: str) -> List[str]:
    import re as _re
    return [t for t in _re.split(r"[^a-z0-9]+", (s or "").lower()) if t]


def repodb_status(disease: str, path: str = REPODB,
                  seen: Optional[set] = None) -> Dict[str, str]:
    """이 질환에 대해 RepoDB 가 아는 약 → 상태.

    ## 병명 대조는 **토큰 전부 포함**으로 한다 — 결함 239

    처음엔 통짜 부분 일치(`q in ind_name`)를 썼다. **넷 중 둘이 0종으로
    나왔다** — 표기가 한 글자씩 달라서다.

    ```
    "COVID-19"           vs  "COVID19 (disease)"    ← 하이픈
    "Alzheimer Disease"  vs  "Alzheimer's Disease"  ← 아포스트로피
    ```

    0종이면 **모든 후보가 「미상」** 이 되고, 「미상」은 재창출 후보로
    세므로 **그 질환은 자동으로 만점**을 받는다. 즉 그 지표는
    «생성이 잘 되나» 가 아니라 **«RepoDB 가 그 병명을 못 찾나»** 를 쟀다.

    이제 **질의의 토큰이 전부** `ind_name` 에 있으면 매치한다.
    `covid`+`19` ⊂ `covid19disease` · `alzheimer`+`disease` ⊂
    `alzheimersdisease`. 토큰을 **전부** 요구하므로 과매치가 어렵다.

    `seen` 을 주면 **실제로 매치된 `ind_name` 을 담아 돌려준다** —
    사람이 과매치를 눈으로 볼 수 있어야 한다. 안 보이면 이 함수가
    또 조용히 틀린다.
    """
    out: Dict[str, str] = {}
    if not os.path.exists(path):
        return out
    import csv
    qt = _toks(disease)
    if not qt:
        return out
    with open(path, encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            raw = str(r.get("ind_name", ""))
            flat = "".join(_toks(raw))
            if not all(t in flat for t in qt):
                continue
            if seen is not None:
                seen.add(raw)
            d = str(r.get("drug_name", "")).strip().lower()
            if not d or d == "na":
                continue
            s = str(r.get("status", "")).strip()
            # 같은 약에 여러 행이면 **Approved 를 우선**한다.
            if out.get(d) != "Approved":
                out[d] = s
    return out


def classify(drugs: List[str], known: Dict[str, str]) -> Dict[str, List[str]]:
    """후보를 셋으로 가른다.

    `승인`   이 질환에 **이미 승인**됨 → **규칙 2 위반**. 재창출이 아니다
    `실패`   RepoDB 가 Terminated·Withdrawn 로 아는 것
             → **우리 깔때기가 걸러야 할 바로 그것**이다
    `미상`   RepoDB 에 없다 → 진짜 재창출 후보 자리
    """
    g = {"승인": [], "실패": [], "미상": []}
    for d in drugs:
        s = known.get(d.strip().lower())
        g["승인" if s == "Approved" else
          "실패" if s in ("Terminated", "Withdrawn", "Suspended") else
          "미상"].append(d)
    return g


def once(disease: str, k: int, variant: str) -> Dict[str, Any]:
    r = _dis.propose(disease, k=k, variant=variant,
                     model=llm.model_for("discover"))
    log = llm.call_log()
    last = log[-1] if log else {}
    return {"ok": r.get("ok"), "asked": r.get("asked"),
            "got": len(r.get("items") or []),
            "error": r.get("error") or "",
            "모델": last.get("served_by") or "?",
            "온도": last.get("temperature_used", "?"),
            "종료사유": last.get("finish_reason", "?"),
            "약": [x["drug"] for x in (r.get("items") or [])]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="발굴 안정성 실측")
    ap.add_argument("--disease", default="Idiopathic Pulmonary Fibrosis")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--variant", default="loose")
    ap.add_argument("--out", default="발굴안정성.json")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)

    print("병명 : %s" % a.disease)
    print("요청 : k=%d · variant=%s · %d회" % (a.k, a.variant, a.n))
    print("모델 : %s   (역할 `discover`)" % llm.model_for("discover"))
    print()
    if a.dry:
        print("--dry — 실호출을 안 한다. 배관만 확인하고 끝낸다.")
        return 0
    if not llm.available():
        print("⛔ LLM 이 설정돼 있지 않다. `.env` 를 봐라.")
        return 2

    known = repodb_status(a.disease)
    print("RepoDB : 이 질환에 아는 약 **%d종** (승인 %d)"
          % (len(known), sum(1 for v in known.values() if v == "Approved")))
    if not known:
        print("     ⚠ **0종이다.** 규칙 2 위반을 셀 수 없다 —")
        print("       «위반 0» 과 «자료 없음» 이 구별 안 된다. 병명 표기를 확인해라.")
    print()

    old = llm.BYPASS_CACHE
    llm.BYPASS_CACHE = True          # **껐다.** 안 끄면 분산이 0으로 나온다
    cache.configure("_gen_cache.json")
    rows: List[Dict[str, Any]] = []
    try:
        for i in range(a.n):
            r = once(a.disease, a.k, a.variant)
            g = classify(r["약"], known)
            r["분류"] = {k2: len(v) for k2, v in g.items()}
            r["재창출후보"] = len(g["실패"]) + len(g["미상"])
            rows.append(r)
            print("  %2d/%d  생성 %2d/%d → **재창출 후보 %2d** "
                  "(승인 %d · 실패 %d · 미상 %d) · %-6s · %s"
                  % (i + 1, a.n, r["got"], r["asked"], r["재창출후보"],
                     len(g["승인"]), len(g["실패"]), len(g["미상"]),
                     r["종료사유"], r["모델"]))
            if g["승인"]:
                print("        ⚠ 규칙 2 위반(이미 승인): %s" % ", ".join(g["승인"]))
            if r["error"]:
                print("        오류: %s" % r["error"][:90])
    finally:
        llm.BYPASS_CACHE = old
        try:
            os.path.exists("_gen_cache.json") and os.remove("_gen_cache.json")
        except OSError:
            pass

    got = [r["got"] for r in rows]
    dist = collections.Counter(got)
    fins = collections.Counter(r["종료사유"] for r in rows)
    full = sum(1 for g in got if g >= a.k)

    print()
    print("=" * 68)
    print("  후보 수 분포 : %s"
          % " · ".join("%d개×%d" % kv for kv in sorted(dist.items())))
    print("  요청대로(%d개) : %d/%d = **%.0f%%**"
          % (a.k, full, a.n, 100.0 * full / max(1, a.n)))
    print("  최소 %d · 최대 %d · 폭 %d" % (min(got), max(got), max(got) - min(got)))
    print("  종료사유 : %s"
          % " · ".join("%s×%d" % kv for kv in fins.most_common()))
    # ── **여기가 요점이다** — 생성 수가 아니라 재창출 후보 수 ────────
    if known:
        viol = [r for r in rows if r["분류"]["승인"] > 0]
        empty = [r for r in rows if r["재창출후보"] == 0]
        rep = [r["재창출후보"] for r in rows]
        print()
        print("  ── 규칙 2 «이 질환에 이미 승인된 약물은 제외한다» ──")
        print("     위반한 실행      : **%d/%d**" % (len(viol), a.n))
        print("     재창출 후보 0개  : **%d/%d**  ← 생성이 «적게» 가 아니라 «없음»"
              % (len(empty), a.n))
        print("     재창출 후보 수   : 최소 %d · 최대 %d · 중앙 %d"
              % (min(rep), max(rep), sorted(rep)[len(rep) // 2]))
        if len(viol) == a.n:
            print()
            print("     → **프롬프트에 규칙이 있는데 매번 어긴다.** 그리고")
            print("       우리는 그걸 세는 코드를 안 갖고 있었다 — 자료(RepoDB)는")
            print("       처음부터 있었다. **안내문은 방어가 아니다.**")

    print()
    if fins.get("length"):
        print("  → **출력이 잘렸다**(`length`). 후보가 적은 게 아니라 **말이 끊겼다.**")
        print("     출력 토큰 상한 문제다 — 프롬프트가 아니라 호출 설정을 고친다.")
    elif max(got) - min(got) >= 2:
        print("  → 종료사유가 `stop` 인데도 갈린다. **모델이 그냥 다르게 답한다.**")
        print("     온도 0이 «완전히 같은 답» 을 뜻하지 않는다는 실측이다.")
    else:
        print("  → 이 표본에서는 안 갈렸다. **«안 난다» 는 «고쳤다» 가 아니다**(결함 217).")

    # 같은 약이 매번 나오는가 — 수가 같아도 **내용**이 갈릴 수 있다
    if rows:
        sets = [set(x.lower() for x in r["약"]) for r in rows]
        common = set.intersection(*sets) if sets else set()
        allx = set().union(*sets) if sets else set()
        print()
        print("  약 이름 : 매번 나온 것 **%d종** · 한 번이라도 나온 것 %d종"
              % (len(common), len(allx)))
        print("     ⓘ 수가 같아도 **내용이 갈리면** 시연이 매번 달라진다.")

    w = safeio.save_json({"병명": a.disease, "k": a.k, "variant": a.variant,
                          "n": a.n, "실행": rows}, a.out, indent=1)
    print("=" * 68)
    print("→ %s (백업 %s)" % (w["경로"], w["상태"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
