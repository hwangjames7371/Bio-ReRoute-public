# -*- coding: utf-8 -*-
"""기각을 **사유별로** 나눈다 — 정의를 한 곳에 둔다 (결함 331).

    py -m bioreroute.bench.rejectsplit                      아는 실행 전부
    py -m bioreroute.bench.rejectsplit 상태_luna_B5.json     하나만

## 왜 있나

«근거 기반 기각» 이 문서마다 다른 뜻이었다 (09-23 발견) —

```
홀드아웃결과.md (mini · 08-05)   TP 기각까지 섞은 수를 TN 분모로 나눴다     56/387
09-22 terra 표                    «결정적 확증시험 음성» 을 «F0» 칸에 넣었다  42 = 33+9
그리고 둘을 나란히 놓고           «두 모델에서 숫자가 거의 같다» 고 적었다
```

**정의가 다른 두 수를 맞대면 «같다」 도 «다르다」 도 거짓이다.**
손으로 세지 않고 여기서만 센다(`CLAUDE.md §4`).

## 정의 — 여기서만 정한다

```
분모          TN 쌍 전부 (기각 재현율과 같은 분모)
F0 갈래       F0 에서 기각됐거나 판정 사유가 `F0:` — 근거를 읽고 내린 판정이 아니다
결정적 음성    하드 비토 — 확증 설계의 결정적 음성 2건 이상 · 동급 지지 없음
반박 우세      그 밖의 기각 — 근거의 무게로
근거 기반      결정적 음성 + 반박 우세
```

TP 기각(위음성)은 **따로** 센다. 섞지 않는다.
**LLM 0회 · 네트워크 0회.**
"""

import json
import os
import sys

from .modelpair import f0_branch, load, rejected
from .stats import wilson

F0 = "F0 갈래"
VETO = "결정적 음성"
REFUTE = "반박 우세"
KINDS = (F0, VETO, REFUTE)

# 알려진 실행 — 없는 파일은 건너뛴다
KNOWN = (
    ("mini · 전 기간", "s_sealed.json"),
    ("mini · gap 1년", "s_sealed_gap1.json"),
    ("terra · 전 기간", "상태_홀드본선_B5.json"),
    ("terra · gap 1년", "상태_홀드본선_gap1_B5.json"),
    ("sol · 전 기간", "상태_sol_B5.json"),
    ("luna · 전 기간", "상태_luna_B5.json"),
)


def kind(c):
    """기각 한 건의 사유. 기각이 아니면 None."""
    if not rejected(c):
        return None
    if f0_branch(c):
        return F0
    if str(c.get("reason") or "").startswith("결정적") or c.get("veto"):
        return VETO
    return REFUTE


def split(cands):
    out = {"TN": dict.fromkeys(KINDS, 0), "TP": dict.fromkeys(KINDS, 0),
           "TN총": 0, "TP총": 0}
    for c in cands:
        lab = c.get("label")
        if lab not in ("TN", "TP"):
            continue
        out[lab + "총"] += 1
        k = kind(c)
        if k:
            out[lab][k] += 1
    tn = out["TN"]
    out["근거기반"] = tn[VETO] + tn[REFUTE]
    out["기각"] = sum(tn.values())
    return out


def _pct(k, n):
    lo, hi = wilson(k, n)
    return "%3d = %4.1f%% [%4.1f–%4.1f]" % (k, 100.0 * k / n if n else 0.0,
                                           100 * lo, 100 * hi)


def report(rows):
    print("=" * 84)
    print("TN 기각의 사유 분해 — 분모는 TN 전부 · TP 기각은 따로  (LLM 0회)")
    print("=" * 84)
    print("  %-16s %5s %6s %6s %6s   %-26s %s"
          % ("실행", "기각", F0, VETO, REFUTE, "근거 기반 [Wilson 95%]", "위음성(TP)"))
    for name, r in rows:
        tn = r["TN"]
        print("  %-16s %5d %6d %6d %6d   %-26s %d"
              % (name, r["기각"], tn[F0], tn[VETO], tn[REFUTE],
                 _pct(r["근거기반"], r["TN총"]), sum(r["TP"].values())))
    got = dict(rows)
    for m in ("mini", "terra"):
        a, b = got.get(m + " · 전 기간"), got.get(m + " · gap 1년")
        if a and b and a["근거기반"]:
            print("\n  %s · 근거 기반 전 기간 → gap 1년   %d → %d   비율 %.3f"
                  "   (반박 우세만 %d → %d · 비율 %.3f)"
                  % (m, a["근거기반"], b["근거기반"], b["근거기반"] / float(a["근거기반"]),
                     a["TN"][REFUTE], b["TN"][REFUTE],
                     b["TN"][REFUTE] / float(a["TN"][REFUTE] or 1)))
    print("\n  ⚠ 사후 분해다. 사전명세가 정한 지표(기각 재현율)의 판정을 **대체하지 않는다**.")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    pairs = ([(os.path.basename(p), p) for p in argv] if argv
             else [(n, p) for n, p in KNOWN if os.path.exists(p)])
    rows = []
    for name, p in pairs:
        try:
            rows.append((name, split(load(p))))
        except (OSError, ValueError) as e:
            print("  🔴 %s — %s" % (p, e))
            return 2
    if not rows:
        print("  읽을 상태 파일이 없다.")
        return 2
    report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
