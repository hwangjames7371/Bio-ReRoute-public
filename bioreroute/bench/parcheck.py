# -*- coding: utf-8 -*-
"""깔때기 병렬화 실측 — **판정이 같은가**를 먼저, 시간은 그 다음.

    py -m bioreroute.bench.parcheck                       IPF (기본)
    py -m bioreroute.bench.parcheck --disease "COVID-19"
    py -m bioreroute.bench.parcheck --dry                 실호출 없이 배관만

## 이 모듈이 재는 것과 안 재는 것

| | |
|---|---|
| 잰다 | ① 순차와 병렬의 **판정이 같은가** ← 유일한 합격 조건 |
| 잰다 | ② 병렬이 실제로 몇 초인가 ← **사후 측정.** 명세 판정이 아니다 |
| **안 잰다** | «③ 시간 미달» 판정을 뒤집는 것 |

155.5 · 159.4초는 **이미 난 판정**이고 이 모듈이 그걸 안 지운다
(`병명입구결과.md §③`·`§6`).

## 왜 세 번 도는가 — LLM이 흔드는 것과 병렬이 흔드는 것을 가른다

```
A   일꾼 1 · 캐시 빈 것        → 판정_A · 초_A     (실호출)
B   일꾼 4 · **A 의 캐시 복사** → 판정_B            (LLM 0회 · 공짜)
C   일꾼 4 · 캐시 빈 것        → 판정_C · 초_C     (실호출)
```

**B 가 동치 증명이다.** 캐시가 같으면 LLM 응답이 완전히 고정되므로
`판정_B ≠ 판정_A` 면 원인은 **오직 병렬**이다.

C 는 **시간만** 본다. `판정_C ≠ 판정_A` 는 LLM 비결정성일 수 있어
병렬 탓으로 못 돌린다 — B 가 이미 그쪽을 지웠기 때문이다.

## ⛔ 왜 `.ps1` 안의 heredoc 이 아니라 모듈인가 — 08-18

처음엔 `py -X utf8 - @"…"@` 로 넣었고 **윈도우에서 두 번 터졌다** —
① `.ps1` 에 BOM 이 없어 PowerShell 이 cp949 로 읽어 한글이 깨졌고
② `@"…"@` 는 **stdin 이 아니라 인자**라 `py -` 가 REPL 을 띄웠다.

`CLAUDE.md §5` — *"검증 환경이 실행 환경과 다르면 그 검증은 거짓말이다."*
파이썬 본문은 리눅스에서 태워 봤지만 **PowerShell 껍데기는 아무 데서도
안 태웠다.** 껍데기를 얇게 만들어 그 자리를 없앤다.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import Any, Dict, List

from .. import demo
from ..io import safeio

TMP = ("_par_A.json", "_par_B.json", "_par_C.json")


def key(r: Dict[str, Any]) -> List[tuple]:
    """판정을 비교 가능한 모양으로.

    **이름·판정·신뢰도로 끝내지 않는다** — 게이트 흔적까지 본다.
    판정만 같고 경로가 다르면 그건 «같다» 가 아니라 «우연히 만났다» 다.
    """
    return [(c["이름"], c["판정"], c["신뢰도"],
             tuple((g["게이트"], g["결과"]) for g in c.get("게이트", [])))
            for c in r.get("후보", [])]


def show(tag: str, r: Dict[str, Any]) -> None:
    print("  %-2s 상태 %-6s 생성 %2d · F0통과 %2d · 태움 %2d · 못태움 %d"
          % (tag, r.get("상태"), r.get("생성", 0), r.get("F0통과", 0),
             r.get("태움", 0), r.get("못태움", 0)))
    # **깔때기 초를 전체 옆에 같이 적는다.** 전체만 적으면 병렬화가
    # 손대지 않은 구간(첫 실행 비용)까지 성과로 읽힌다 — 결함 233.
    print("     전체 %6.1f초  |  깔때기 %5.1f초  |  그 밖 %5.1f초"
          % (r.get("초", 0.0), r.get("깔때기초", 0.0),
             round(r.get("초", 0.0) - r.get("깔때기초", 0.0), 1)))
    print("     일꾼 %d · 새 LLM 호출 %d회 · warm %s"
          % (r.get("일꾼", 0), r.get("비용", 0), r.get("warm")))
    # **누가 답했나.** `FALLBACKS` 로 넘어가면 같은 프롬프트에 다른 답이
    # 오고 그건 판정을 흔든다 — 결함 234.
    m = r.get("모델") or {}
    if m:
        print("     답한 모델: %s" % ", ".join("%s×%d" % kv for kv in
                                            sorted(m.items(), key=lambda x: -x[1])))
        if len(m) > 1:
            print("     ⚠ **모델이 둘 이상이다.** 429 로 FALLBACKS 를 탔을 수 있고,")
            print("       그러면 이 실행의 판정을 다른 실행과 나란히 못 놓는다.")
    if r.get("못태운후보"):
        print("     못 태운 것: %s" % ", ".join(r["못태운후보"]))
    gs = r.get("게이트초") or {}
    for g, v in sorted(gs.items(), key=lambda kv: -kv[1].get("중앙", 0)):
        print("       %-12s 중앙 %5.2f초  합 %6.1f  (n=%d)"
              % (g, v.get("중앙", 0), v.get("합", 0), v.get("n", 0)))


def _conc(r: Dict[str, Any]) -> float:
    """**동시성** = 게이트에 실제로 쓴 시간의 합 ÷ 깔때기 벽시계.

    «동시에 평균 몇 개가 돌았나» 다. 순차면 1.0, 일꾼 k 로 꽉 채우면 k.

    ## 왜 «배속» 대신 이걸 쓰나 — 결함 236

    08-18 실측에서 **A 는 후보 10개, C 는 2개**가 나왔다(생성이 흔들린다).
    그러면 **A 와 C 는 다른 양의 일을 한 것**이라 «100초 → 14.6초 = 6.85배»
    는 **비교 자체가 성립 안 한다.** 실제로 그 줄이 이론 최대 4배를 넘어
    가드에 걸렸다.

    동시성은 **후보 수에 안 묶인다.** 한 실행 안에서만 나눈 값이라
    양쪽 실행이 달라도 각자 «얼마나 겹쳐 돌았나» 를 말한다.
    """
    tot = sum(v.get("합", 0.0) for v in (r.get("게이트초") or {}).values())
    w = r.get("깔때기초", 0.0)
    return (tot / w) if w else 0.0


def _speed(A: Dict[str, Any], C: Dict[str, Any], workers: int) -> None:
    na, nc = A.get("태움", 0), C.get("태움", 0)
    print("     %-3s 후보 %2d · 일꾼 1 · 깔때기 %6.1f초 → **동시성 %.2f**"
          % ("A", na, A.get("깔때기초", 0.0), _conc(A)))
    print("     %-3s 후보 %2d · 일꾼 %d · 깔때기 %6.1f초 → **동시성 %.2f**  "
          "(이론 최대 %.1f)"
          % ("C", nc, workers, C.get("깔때기초", 0.0), _conc(C),
             float(max(1, min(nc, workers)))))
    print("     ⓘ 동시성 = 게이트 시간 합 ÷ 깔때기 벽시계. **후보 수에 안 묶인다.**")

    # ── 후보 수가 다르면 **배속을 아예 안 찍는다** ─────────────────
    #   다른 양의 일을 한 두 실행을 나누면 그건 배속이 아니다.
    #   경고를 붙여 찍느니 안 찍는 쪽이 낫다 — 숫자는 인용되고 경고는 안 된다.
    if na != nc:
        print()
        print("     ⛔ **배속을 안 적는다** — A 는 후보 %d개, C 는 %d개다."
              % (na, nc))
        print("        다른 양의 일을 한 둘을 나누면 배속이 아니라 잡음이다.")
        if na and _conc(A) > 0:
            tot = sum(v.get("합", 0.0)
                      for v in (A.get("게이트초") or {}).values())
            print("        A 의 %d개를 일꾼 %d로 돌렸다면 **추정** %.0f초"
                  " (합 %.1f ÷ %d) — 실측이 아니다."
                  % (na, workers, tot / workers, tot, workers))
    else:
        fa, fc = A.get("깔때기초", 0.0), C.get("깔때기초", 0.0)
        print()
        print("     같은 후보 %d개 · 깔때기 %.1f초 → %.1f초  **%.2f배**"
              % (na, fa, fc, (fa / fc) if fc else 0.0))

    lim = A.get("상한", 150.0)
    sa, sc = A.get("초", 0.0), C.get("초", 0.0)
    print()
    print("     전체(첫 실행 비용 포함)  A %.1f초 %s · C %.1f초 %s  (상한 %.0f)"
          % (sa, "넘김" if sa > lim else "이내",
             sc, "넘김" if sc > lim else "이내", lim))
    print("     ⓘ 명세 §③ 은 155.5·159.4 로 **이미 미달 판정**이다. 이 줄이 그걸 안 지운다.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="깔때기 병렬화 실측")
    ap.add_argument("--disease", default=os.environ.get(
        "BR_DISEASE", "Idiopathic Pulmonary Fibrosis"))
    ap.add_argument("--workers", type=int, default=demo.DISEASE_WORKERS)
    ap.add_argument("--out", default="병렬결과.json")
    ap.add_argument("--dry", action="store_true",
                    help="실호출 없이 배관만 — 껍데기 시험용")
    ap.add_argument("--keep", action="store_true",
                    help="임시 캐시 셋을 남긴다 (기본은 지운다)")
    a = ap.parse_args(argv)
    try:
        return _main(a)
    finally:
        # **저장소에 쓰레기를 안 남긴다.** 결함 219 가 그것이었다 —
        # 시험이 스텁 `fto_years.json` 을 남겨 다음 실행이 그걸 읽었다.
        if not a.keep:
            for p in TMP:
                try:
                    os.path.exists(p) and os.remove(p)
                except OSError:
                    pass


def _main(a) -> int:

    # 묵은 캐시가 남아 있으면 A 가 **데워진 채로** 돌아 측정이 통째로
    # 거짓이 된다. 못 지우면 **조용히 넘어가지 않고 멈춘다** —
    # «캐시가 비었다» 는 이 실측의 전제다.
    for p in TMP:
        if not os.path.exists(p):
            continue
        try:
            os.remove(p)
        except OSError as e:
            print("⛔ 묵은 캐시 %s 를 못 지웠다 — %s" % (p, e))
            print("   그대로 두면 A 가 **데워진 채로** 돌아 초가 거짓이 된다.")
            print("   손으로 지우고 다시 돌려라.")
            return 3

    print("질환 : %s" % a.disease)
    print("일꾼 : 1 (A)  vs  %d (B·C)" % a.workers)
    print()

    if a.dry:
        print("--dry — 실호출을 안 한다. 배관만 확인하고 끝낸다.")
        return 0

    print("A — 일꾼 1 · 캐시 빈 것")
    A = demo.run_disease(a.disease, cache_path=TMP[0], workers=1)
    show("A", A)

    # A 가 못 돌았으면 **여기서 멈춘다.** 안 그러면 B 가 «파일 없음» 이라는
    # 엉뚱한 말로 죽는다 — 한도 소진·LLM없음·차단이 그 경로다.
    if A.get("상태") != "정상" or not os.path.exists(TMP[0]):
        print()
        print("  ⛔ A 가 못 돌았다 — %s: %s"
              % (A.get("상태"), A.get("메시지", "")))
        print("     B·C 는 A 를 기준으로 삼는다. **여기서 멈춘다.**")
        print("     한도 소진이면 budget.json, LLM없음이면 .env 를 봐라.")
        return 2

    print()
    print("B — 일꾼 %d · A 의 캐시 복사  (새 LLM 호출이 0이어야 한다)" % a.workers)
    shutil.copyfile(TMP[0], TMP[1])
    B = demo.run_disease(a.disease, cache_path=TMP[1], workers=a.workers)
    show("B", B)

    print()
    print("C — 일꾼 %d · 캐시 빈 것" % a.workers)
    C = demo.run_disease(a.disease, cache_path=TMP[2], workers=a.workers)
    show("C", C)

    kA, kB, kC = key(A), key(B), key(C)
    same = kA == kB
    print()
    print("=" * 68)
    print("  ① 동치 (A vs B · 캐시 동일)  : %s" % ("같다" if same else "**다르다**"))
    if not same:
        if len(kA) != len(kB):
            print("     후보 수부터 다르다 — %d vs %d" % (len(kA), len(kB)))
        for x, y in zip(kA, kB):
            if x != y:
                print("     A %s" % (x,))
                print("     B %s" % (y,))
    print("     B 의 새 LLM 호출          : %d회" % B.get("비용", -1))
    if B.get("비용", -1) != 0:
        print("     ⚠ **0이 아니다.** 캐시가 같지 않다는 뜻이라")
        print("       ①의 «같다/다르다» 를 병렬 탓으로 못 돌린다.")

    print()
    print("  ② 시간 — **사후 측정이다. 명세 판정을 안 바꾼다**")
    _speed(A, C, a.workers)

    print()
    print("  ③ 판정 (A vs C · 둘 다 실호출) : %s"
          % ("같다" if kA == kC else
             "다르다 — LLM 비결정성일 수 있다. **판단 근거는 ①이다**"))
    print("=" * 68)

    w = safeio.save_json({"질환": a.disease, "일꾼": a.workers,
                          "A": A, "B": B, "C": C,
                          "동치_AB": same, "동치_AC": kA == kC},
                         a.out, indent=1)
    print("→ %s (백업 %s)" % (w["경로"], w["상태"]))
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
