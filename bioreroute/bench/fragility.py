# -*- coding: utf-8 -*-
"""판정 취약성 — **근거 몇 건을 빼면 결론이 뒤집히나** (2026-09-01).

## 왜 만드나

두 물음이 사실 같은 물음이었다.

**① 사용자 물음** — *"우리 랩 미공개 결과를 넣고 판단해 줘."*
넣는 것은 쉽다. 어려운 건 **«그 근거가 결론을 얼마나 떠받치나»** 다.
미공개 근거 3건을 넣어 「유망」이 나왔는데 **그 3건을 빼면 「보류」**
라면, 그 판정은 **재현 불가능한 자료에 의존**하는 것이다.

**② 일반 물음** — *"이 판정은 얼마나 단단한가?"*

②의 답이 ①을 포함한다. 그래서 일반형으로 만들었다.

## 선행연구 — **우리가 만든 개념이 아니다**

임상통계에 **fragility index** 가 있다(Walsh et al. 2014, *J Clin
Epidemiol*). *"통계적 유의성을 없애려면 몇 명의 사건을 바꿔야 하는가"*
를 세는 지표다. **p 값 하나로 «유의함»을 말하는 것이 얼마나 취약한지**
드러내려고 만들어졌다.

우리 판은 **근거 단위**다 —

    취약도 k = 판정을 바꾸는 데 빼야 하는 **최소 근거 수**
      k = 1  근거 하나에 매달린 판정. **약하다**
      k ≥ 3  여러 근거가 같은 방향. **단단하다**
      k = ∞  무엇을 빼도 안 바뀐다 (대개 근거가 아주 적을 때)

## ⚠ 정확히 세지 않는다 — **탐욕적 근사**

엄밀히는 모든 부분집합을 봐야 하지만 조합이 폭발한다. 여기서는
**무거운 근거부터 하나씩 빼며** 판정이 바뀌는 지점을 찾는다.
따라서 **이 값은 진짜 최소값의 상한**이다 — *"적어도 k개는 빼야
한다"* 가 아니라 *"k개를 빼면 바뀐다"* 로 읽어야 한다.

## 사용법

    py -m bioreroute.bench.fragility --demo
    py -m bioreroute.bench.fragility --state 상태_0912_B5.json

`--state` 는 `bench.run --save-state` 가 남긴 **파일**이다(디렉토리도 받는다).
구성이 둘 이상이면 `run.py` 가 이름에 구성을 붙인다 — `상태_0912_B5.json`.

## ⛔ 09-18 — **입구가 없어서 실측이 0이었다**

알고리즘은 09-01에 만들고 검증했는데 **한 번도 실측이 안 됐다.**
이유가 «바빠서» 가 아니었다 — `main()` 이 `--state` 를 **디렉토리로
보고 `os.listdir`** 했고, 실제 산출물은 **파일**이라 그대로 죽었다.
게다가 파싱이 스텁이라 돌아도 `취약도: None` 만 나왔다.

> `preflight` 렌즈 3(배선)은 «코드가 도는가» 를 보고 **«결과가 문서에
> 닿았는가» 는 안 본다.** 그래서 여드레를 못 잡았다. 시험 [160] 이
> 이 계열을 구조로 막는다.
"""
import argparse
import copy
import json
import os
import sys
from typing import Any, Dict, List, Optional

from ..core import scoring


def _verdict(c) -> str:
    try:
        return scoring.adjudicate(c)[0]
    except Exception:
        return "오류"


def fragility(c, max_k: int = 8) -> Dict[str, Any]:
    """**판정을 바꾸는 데 빼야 하는 최소 근거 수**(탐욕적 근사).

    무거운 것부터 뺀다 — 결론을 가장 크게 떠받치는 것이 그쪽이므로
    **가장 적은 수로 뒤집히는 경로에 가깝다.**
    """
    base = _verdict(c)
    ev = [(e, "support") for e in getattr(c, "support", [])] + \
         [(e, "refute") for e in getattr(c, "refute", [])]
    ev.sort(key=lambda x: -getattr(x[0], "weight", 0.0))
    out = {"판정": base, "근거수": len(ev), "취약도": None,
           "뺀근거": [], "바뀐판정": None}
    if base == "오류" or not ev:
        return out
    work = copy.deepcopy(c)
    removed = []
    for k in range(1, min(max_k, len(ev)) + 1):
        e, side = ev[k - 1]
        lst = getattr(work, side)
        # 같은 tag 를 지운다 (deepcopy 라 객체 동일성이 깨졌다)
        for i, x in enumerate(lst):
            if getattr(x, "tag", None) == getattr(e, "tag", None):
                lst.pop(i)
                break
        removed.append({"tag": getattr(e, "tag", "")[:48],
                        "side": side, "w": getattr(e, "weight", 0.0)})
        v = _verdict(work)
        if v != base:
            out.update(취약도=k, 뺀근거=removed, 바뀐판정=v)
            return out
    out["뺀근거"] = removed
    return out


def review_dependence(c, review_of, tier: str = "internal") -> Dict[str, Any]:
    """**그 등급의 근거를 전부 빼면 판정이 바뀌나** — 사용자 물음 ①.

    `review_of(evidence) -> "peer_reviewed"|"preprint"|"internal"`
    """
    base = _verdict(c)
    work = copy.deepcopy(c)
    n = 0
    for side in ("support", "refute"):
        keep = []
        for e in getattr(work, side, []):
            if review_of(e) == tier:
                n += 1
            else:
                keep.append(e)
        setattr(work, side, keep)
    v = _verdict(work)
    return {"등급": tier, "뺀건수": n, "원판정": base, "뺀뒤판정": v,
            "바뀌나": (v != base) if n else None}


def _table(rows: List[Dict[str, Any]]) -> str:
    L = ["=" * 72,
         "판정 취약성 — **근거 몇 건을 빼면 뒤집히나**",
         "  fragility index (Walsh et al. 2014) 의 근거 단위 판 · LLM 0회",
         "=" * 72,
         "",
         "  %-26s %-8s %6s %8s  %s" % ("후보", "판정", "근거", "취약도", "바뀌면")]
    L.append("  " + "-" * 68)
    hard = frag1 = 0
    for r in rows:
        k = r.get("취약도")
        ks = str(k) if k else "안 바뀜"
        if k == 1:
            frag1 += 1
        if k is None:
            hard += 1
        L.append("  %-26s %-8s %6d %8s  %s"
                 % (r.get("이름", "")[:25], r.get("판정", ""),
                    r.get("근거수", 0), ks, r.get("바뀐판정") or "-"))
    n = len(rows) or 1
    bad = [r for r in rows if r.get("재현") is False]
    L += ["",
          "  **근거 하나로 뒤집히는 판정 %d/%d (%.0f%%)**" % (frag1, len(rows),
                                                            100.0 * frag1 / n),
          "  무엇을 빼도 안 바뀌는 것 %d" % hard]
    # ── ⭐ 재현 대조 — **복원이 원본과 같은가** (09-18) ────────────────
    #   이 줄이 없으면 «예쁜 표» 와 «맞는 표» 를 구별할 수 없다.
    if any("재현" in r for r in rows):
        if bad:
            L += ["",
                  "  🔴 **복원한 판정이 저장된 판정과 다른 건 %d/%d**"
                  % (len(bad), len(rows)),
                  "     복원이 원본과 다른 시스템이다 — **이 표의 취약도를",
                  "     인용하지 마라.** 어긋난 것:",
                  ]
            for r in bad[:5]:
                L.append("       %-26s 저장 %s ≠ 복원 %s"
                         % (r.get("이름", "")[:25], r.get("저장판정", "?"),
                            r.get("판정", "?")))
        else:
            L.append("  ✅ 복원한 판정이 저장된 판정과 **전부 일치** "
                     "(%d/%d) — 취약도를 읽어도 된다" % (len(rows), len(rows)))
    L += ["",
          "  ⚠ **탐욕적 근사**다 — 무거운 근거부터 뺀다. 이 값은 진짜",
          "     최소값의 **상한**이다(*«k개를 빼면 바뀐다»* 로 읽어라).",
          "  ⚠ 취약도가 낮은 것이 **틀렸다는 뜻이 아니다.** 근거가 적은",
          "     것뿐일 수 있다 — 「근거수」와 같이 봐라.",
          "=" * 72]
    return "\n".join(L)


def _candidate_from(d: Dict[str, Any]):
    """저장된 **판정 원본 한 건** → `Candidate` 복원 (09-18 신설).

    ## 왜 여태 없었나

    앞판 `main()` 은 `--state` 를 **디렉토리로 보고 `os.listdir`** 했고,
    파일 이름만 줄로 찍은 뒤 `취약도: None` 을 냈다. 주석에
    *"상태 파일 형식은 9/7 에 실물을 보고 맞춘다 — 추측으로 파싱하지
    않는다"* 라고 적어 두고 **그 뒤로 안 맞췄다.** 그 사이
    `bench/run.py` 는 디렉토리가 아니라 **파일 하나**를 쓰고 있었으므로
    `--state` 를 실제 산출물에 대면 `NotADirectoryError` 가 났다.

    > **«만들었다» 와 «된다» 는 다르다**(`CLAUDE.md §5`). 알고리즘
    > `fragility()` 는 검증돼 있었고, **입구가 없었다.**

    ## 추측이 아니다 — 키를 대조했다

    아래 키는 전부 `bench/run.py` 의 `--save-state` 덤프가 **실제로 쓰는**
    키다(09-18 원문 대조). `support`/`refute` 는 저장되지 **않지만**
    `gates._rebuild_evidence()` 가 `factcheck` 하나에서 무게까지 복원한다
    — 그래서 상태 파일만으로 판정을 다시 계산할 수 있다.

    `scoring.adjudicate()` 가 읽는 것은 `factcheck`·`f0`·`veto`·
    `veto_reason`·`support`·`refute` **여섯뿐**이고, 여섯이 다 복원된다.
    """
    from ..core import gates
    from ..core.state import Candidate, GateRecord
    nm = d.get("name") or ("%s → %s" % (d.get("drug", ""), d.get("disease", "")))
    # ⚠ **09-19 렌즈 7 — `origin` 은 복원이 아니라 표시다.**
    #   원본 벤치에서는 `origin = row["label"]`("TP"|"TN")이었다
    #   (`bench/run.py:to_candidate`). 상태 파일이 `origin` 을 안 실으므로
    #   **여기서 «save-state» 로 바꾼다** — 어디서 온 후보인지를 정직하게
    #   적는 쪽을 골랐다. 라벨은 아래에서 `label` 속성으로 따로 붙인다.
    #   ⛔ **`origin` 을 라벨로 읽는 코드를 새로 쓰지 마라.** 여기서 끊긴다.
    c = Candidate(name=nm, origin="save-state", query=nm,
                  drug=d.get("drug", ""), disease=d.get("disease", ""))
    c.factcheck = d.get("factcheck") or []
    c.f0 = d.get("f0") or {}
    c.veto = bool(d.get("veto"))
    c.veto_reason = d.get("veto_reason") or ""
    c.verdict = d.get("verdict") or ""
    c.confidence = d.get("confidence")
    # ── ⚠ 09-18 2차 — **trail 과 label 을 안 복원하고 있었다** ──────────
    #
    #   `fragility()` 도 `adjudicate()` 도 trail 을 안 보므로 1차에서는
    #   티가 안 났다. 그런데 `gates.false_negatives` 는 `c.killed`(trail 의
    #   KILL)를, `gates.refute_recall` 은 **skeptic 기록의 detail 문자열**을
    #   읽는다. 없이 돌리면 **둘 다 조용히 0** 을 낸다 — 결함 35 계열
    #   («없다» 와 «안 돌았다» 를 한 칸에 뭉개는 것).
    #
    #   ⚠ **`provenance` 는 저장되지 않는다.** 복원한 trail 은 감사 추적의
    #     절반이다 — 그 사실을 여기 적어 두고, 이 trail 로 «감사 추적이
    #     있다» 고 주장하지 않는다.
    c.trail = [GateRecord(t.get("gate", ""), t.get("outcome", ""),
                          t.get("detail", ""), {})
               for t in (d.get("trail") or [])]
    if d.get("label"):
        # `Candidate` 에 없는 필드다. `false_negatives` 가 getattr 로 읽는다.
        setattr(c, "label", d["label"])
    gates._rebuild_evidence(c)      # factcheck → support/refute (무게 포함)
    return c


def from_state(path: str, max_k: int = 8) -> List[Dict[str, Any]]:
    """`--save-state` 산출물(파일 **또는** 그 파일들이 든 디렉토리)을 읽는다.

    ## ⭐ 스스로 검산한다 — **재현 대조**

    복원이 틀렸는데 표가 예쁘게 나오는 것이 **가장 나쁜 실패**다.
    그래서 매 건마다 **저장된 판정**과 **복원해서 다시 계산한 판정**을
    맞춰 보고, 어긋나면 `재현=False` 로 남긴다. `_table()` 이 그 수를
    맨 아래에 **크게** 찍는다.

    어긋나는 건이 하나라도 있으면 **그 실행의 취약도는 인용하지 마라** —
    복원이 원본과 다른 시스템이라는 뜻이다(`CLAUDE.md §5`).
    """
    if os.path.isdir(path):
        files = [os.path.join(path, f) for f in sorted(os.listdir(path))
                 if f.endswith(".json")]
    else:
        files = [path]
    rows: List[Dict[str, Any]] = []
    for fp in files:
        with open(fp, encoding="utf-8") as fh:
            d = json.load(fh)
        cands = d.get("candidates")
        if not isinstance(cands, list):
            # **조용히 건너뛰지 않는다.** 형식이 다르면 그 사실이 결과다.
            rows.append({"이름": os.path.basename(fp)[:25], "판정": "형식오류",
                         "근거수": 0, "취약도": None, "재현": False,
                         "저장판정": "", "구성": d.get("config", "")})
            continue
        for cd in cands:
            c = _candidate_from(cd)
            r = fragility(c, max_k=max_k)
            r["이름"] = c.name
            r["구성"] = d.get("config", "")
            r["저장판정"] = cd.get("verdict") or ""
            r["재현"] = (not r["저장판정"]) or (r["판정"] == r["저장판정"])
            rows.append(r)
    return rows


def from_demo(path: str = "demo_cases.json") -> List[Dict[str, Any]]:
    """구운 사례에는 `Candidate` 객체가 없다 — **왜 못 쓰는지 적는다.**

    `demo_cases.json` 은 화면용 요약(판정·근거 문자열)이라 무게를 가진
    `Evidence` 목록이 없다. 취약성은 **무게를 빼 보며** 재는 것이므로
    이 파일로는 계산할 수 없다.

    → `bench.run --save-state` 가 남기는 **판정 원본**이 필요하다.
      9/7 실행에 `--save-state 상태_0907` 을 넣어 두었다.
    """
    return []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="판정 취약성 — 근거 몇 건을 빼면 뒤집히나 (LLM 0회)")
    ap.add_argument("--state", default="",
                    help="bench.run --save-state 가 남긴 **파일**(또는 그런 "
                         "파일들이 든 디렉토리)")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-k", type=int, default=8)
    a = ap.parse_args(argv)
    if a.demo or not a.state:
        print("  ⚠ **판정 원본이 필요하다.**")
        print("     `demo_cases.json` 은 화면용 요약이라 무게를 가진")
        print("     근거 목록이 없다 — 취약성은 무게를 빼 보며 잰다.")
        print("")
        print("     py -m bioreroute.bench.run --stratum A --configs B5 \\")
        print("        --out 궤적_0907.json --save-state 상태_0907.json")
        print("     py -m bioreroute.bench.fragility --state 상태_0907.json")
        print("")
        print("     ⚠ 구성이 둘 이상이면 run.py 가 이름에 구성을 붙인다")
        print("        (`상태_0912_B5.json`). 그 파일을 직접 가리켜라.")
        return 1
    if not os.path.exists(a.state):
        print("  ⛔ 그런 경로가 없다: %s" % a.state)
        return 2
    rows = from_state(a.state, max_k=a.max_k)
    print(json.dumps(rows, ensure_ascii=False, indent=1) if a.json
          else _table(rows))
    # **재현이 깨지면 종료 코드로도 알린다** — 표만 보고 넘기는 것을 막는다
    return 3 if any(r.get("재현") is False for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
