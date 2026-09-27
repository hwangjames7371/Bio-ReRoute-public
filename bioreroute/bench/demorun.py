# -*- coding: utf-8 -*-
"""고른 질환으로 **병명 입구를 한 번 태운다** — `시연질환결과.md §5` 집행기.

    py -m bioreroute.bench.demorun            Glioblastoma (선택된 것)
    py -m bioreroute.bench.demorun --dry      배관만
    py -m bioreroute.bench.demorun --no-fallback   미달이어도 2위를 안 태운다

## 왜 또 태우는가

`demopick` 은 **발굴만** 봤다. 후보가 10개 나와도 깔때기에서 **전부
보류**면 시연은 여전히 빈약하다. 명세 §6 이 그걸 미리 적어 뒀다 —

> 판정이 갈리는지는 안 잰다. … 그건 한 번 태워 봐야 안다.

## 합격 기준 — **태우기 전에 `시연질환결과.md §5` 에 적었다**

```
합격  판정이 **두 종류 이상**  그리고  근거(PMID)가 붙은 후보 **3개 이상**
미달  전부 같은 판정  또는  근거 붙은 후보 2개 이하
```

**사람이 표를 보고 «괜찮네» 라고 하면 안 된다.** 그러면 기준을 쓴 의미가
없다 — `CLAUDE.md` 머리말(*안내문은 방어가 아니다*) 그대로다.

## 미달이면 — **이것도 미리 적었다**

1. **질환을 또 바꾸지 않는다.** 그러면 «될 때까지 돌린 것» 이 된다
2. 2위였던 **COVID-19 로 한 번만** 태운다. `demopick` 순위가 이미 정해
   놨으므로 **새 자유도가 아니다**
3. **거기서도 미달이면 둘 다 미달로 적고 멈춘다**

## 덤 — 동시성을 **제대로** 잰다

08-18 병렬 실측은 후보가 2개라 이론 최대가 2였다(결함 236).
여기서 10개가 나오면 **일꾼 4를 꽉 채운 값**을 처음 보게 된다.
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
from typing import Any, Dict, List, Tuple

from .. import demo
from ..io import cache, llm, safeio

CHOSEN = "Glioblastoma"          # `시연질환결과.md §1` 에서 규칙이 뽑았다
RUNNER_UP = "COVID-19"           # 같은 표의 2위. 미달 시에만 쓴다
MIN_KINDS = 2                    # 명세 §5 — 판정 종류
MIN_CITED = 3                    # 명세 §5 — 근거 붙은 후보 수


def judge(r: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """합격 기준을 **코드가** 적용한다."""
    cs = r.get("후보") or []
    kinds = collections.Counter(c.get("판정") or "?" for c in cs)
    cited = [c for c in cs
             if any((e.get("PMID") or "").strip() for e in (c.get("근거") or []))]
    m = {"판정종류": dict(kinds), "종류수": len(kinds),
         "근거붙은후보": len(cited),
         "근거붙은이름": [c["이름"] for c in cited][:5]}
    ok = len(kinds) >= MIN_KINDS and len(cited) >= MIN_CITED
    why = ("종류 %d(≥%d) · 근거 붙은 후보 %d(≥%d)"
           % (len(kinds), MIN_KINDS, len(cited), MIN_CITED))
    return ok, why, m


def show(tag: str, disease: str, r: Dict[str, Any]) -> Tuple[bool, str, Dict]:
    print("── %s : %s" % (tag, disease))
    if r.get("상태") != "정상":
        print("   ⛔ %s — %s" % (r.get("상태"), r.get("메시지", "")))
        return False, "못 돌았다", {}
    tot = sum(v.get("합", 0.0) for v in (r.get("게이트초") or {}).values())
    fw = r.get("깔때기초", 0.0)
    print("   생성 %d · F0통과 %d · 태움 %d · 못태움 %d · 새 LLM 호출 %d회"
          % (r.get("생성", 0), r.get("F0통과", 0), r.get("태움", 0),
             r.get("못태움", 0), r.get("비용", 0)))
    print("   전체 %.1f초 | 깔때기 %.1f초 | 그 밖 %.1f초 | 일꾼 %d"
          % (r.get("초", 0.0), fw, round(r.get("초", 0.0) - fw, 1),
             r.get("일꾼", 0)))
    if fw:
        n = r.get("태움", 0)
        print("   **동시성 %.2f**  (게이트 합 %.1f ÷ 깔때기 %.1f · 이론 최대 %.1f)"
              % (tot / fw, tot, fw, float(max(1, min(n, r.get("일꾼", 1))))))
    m = r.get("모델") or {}
    if m:
        print("   답한 모델: %s" % ", ".join("%s×%d" % kv for kv in m.items()))
    print()
    for c in (r.get("후보") or []):
        pm = [e.get("PMID") for e in (c.get("근거") or []) if e.get("PMID")]
        print("     %-28s %-6s %3s%%  근거 %d (PMID %d)"
              % (c["이름"][:28], c.get("판정"), c.get("신뢰도"),
                 c.get("근거수", 0), len(pm)))
    ok, why, met = judge(r)
    print()
    print("   판정 분포: %s" % met.get("판정종류"))
    print("   → **%s**  (%s)" % ("합격" if ok else "미달", why))
    return ok, why, met


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="고른 질환으로 병명 입구 1회")
    ap.add_argument("--disease", default=CHOSEN)
    ap.add_argument("--workers", type=int, default=demo.DISEASE_WORKERS)
    ap.add_argument("--out", default="시연실행결과.json")
    ap.add_argument("--no-fallback", action="store_true",
                    help="미달이어도 2위를 안 태운다 (호출 절약)")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)

    print("질환   : %s   (규칙이 뽑았다 — `시연질환결과.md §1`)" % a.disease)
    print("기준   : 판정 종류 ≥%d **그리고** 근거 붙은 후보 ≥%d"
          % (MIN_KINDS, MIN_CITED))
    print("         **태우기 전에 §5 에 적었다.** 보고 정하지 않는다.")
    print("미달 시 : 2위 %s 를 **한 번만**. 거기서도 미달이면 둘 다 미달로 적고 멈춘다."
          % RUNNER_UP)
    print("일꾼   : %d" % a.workers)
    print()
    if a.dry:
        print("--dry — 실호출을 안 한다. 배관만 확인하고 끝낸다.")
        return 0
    if not llm.available():
        print("⛔ LLM 이 설정돼 있지 않다. `.env` 를 봐라.")
        return 2

    tmp = "_demorun_cache.json"
    out: List[Dict[str, Any]] = []
    try:
        for p in (tmp, tmp + "2"):
            if os.path.exists(p):
                os.remove(p)
        r1 = demo.run_disease(a.disease, cache_path=tmp, workers=a.workers)
        ok1, why1, m1 = show("①", a.disease, r1)
        out.append({"질환": a.disease, "합격": ok1, "사유": why1,
                    "지표": m1, "결과": r1})

        ok, chosen = ok1, a.disease
        if not ok1 and not a.no_fallback:
            print()
            print("=" * 70)
            print("  ① 이 미달이다. 명세대로 **2위 %s 를 한 번만** 태운다."
                  % RUNNER_UP)
            print("=" * 70)
            print()
            r2 = demo.run_disease(RUNNER_UP, cache_path=tmp + "2",
                                  workers=a.workers)
            ok2, why2, m2 = show("②", RUNNER_UP, r2)
            out.append({"질환": RUNNER_UP, "합격": ok2, "사유": why2,
                        "지표": m2, "결과": r2})
            ok, chosen = ok2, RUNNER_UP
    finally:
        cache.configure("pubmed_cache.json")
        for p in (tmp, tmp + "2"):
            try:
                os.path.exists(p) and os.remove(p)
            except OSError:
                pass

    print()
    print("=" * 70)
    if ok:
        print("  ✅ **%s 로 간다.**" % chosen)
        print("     판정이 갈렸고 근거가 붙었다 — 깔때기가 화면에서 보인다.")
    elif len(out) >= 2:
        print("  ❌ **둘 다 미달이다.** 그대로 적는다.")
        print("     명세대로 **더 안 돌린다.** 시연은 구운 사례(`PRESETS` 6개)로 가고,")
        print("     병명 입구는 «돌아가는 것을 보이되 판정은 구운 것을 쓴다» 로 적는다.")
    else:
        print("  ❌ **%s 미달.** `--no-fallback` 이라 2위를 안 태웠다." % a.disease)
    print("=" * 70)

    w = safeio.save_json({"기준": {"종류": MIN_KINDS, "근거후보": MIN_CITED},
                          "합격": ok, "선택": chosen if ok else None,
                          "실행": out}, a.out, indent=1)
    print("→ %s (백업 %s)" % (w["경로"], w["상태"]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
