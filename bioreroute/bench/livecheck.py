# -*- coding: utf-8 -*-
"""라이브 점검 — 촬영 전에 **미리 고정한 한 쌍**을 돌려 판정을 적고 캐시를 데운다 (09-27 신설).

    py -m bioreroute.bench.livecheck           # 돌린다(LLM · 검색 호출 · 처음이면 1~3분) → 기록 파일
    py -m bioreroute.bench.livecheck --show    # 마지막 기록만 본다(호출 0)

붙여 넣지 말고 `.\\라이브점검.ps1` 을 쓴다(`CLAUDE.md §5` — 인자가 여럿인 실행은 .ps1 에).

## 왜 있나

시연 영상의 «라이브» 컷(나-6)은 대본(`slides/make_video_본선.py`)이 **쌍과 정답을 미리** 적었다 —
`LIVE_PAIR` · `LIVE_TRUTH`. 판정이 정답과 같으면 〔ⓑ〕, 다르면 〔ⓐ〕 를 읽는다.
«결과를 보고 쌍을 바꾸지 않는다» 를 **안내문이 아니라 구조로** 둔다 — 이 도구에는 쌍을 바꾸는 인자가
없고, 쌍과 정답은 대본 생성기의 상수에서 **읽는다**(두 곳에 적지 않는다).

## 무엇을 하나

1. **제출 모델인가**(`preflight.submit_model`) — 아니면 멈춘다. 시연이 제출하지 않은 모델로 돌면 안 된다
2. 화면과 **같은 함수**(`demo.run_pair` · `demo.DEMO_CONFIG` · 표준 잣대)로 한 번 — 처음이면 1~3분
3. 같은 것을 **한 번 더** — 캐시가 데워졌는지(시간)와 판정이 같은지
4. 기록 `라이브점검_YYYYMMDD_HHMM.json` — **새 파일만** 쓴다(덮지 않는다). 영상 대본 생성기가 이 기록을
   읽어 **읽을 갈래를 표시**한다

## 정직하게 — 영상은 «데운 뒤» 찍는다

촬영 때는 둘째 실행처럼 **캐시에서** 판정이 바로 뜬다. 처음 보는 쌍은 1~3분 걸린다는 것을 영상 편집에서
자막 한 줄로 밝힌다(대본 ▶ 줄). 판정은 첫 실행과 같다 — 같은 모델 · 같은 프롬프트 · 같은 검색 결과다.
"""
import argparse
import glob
import importlib.util
import json
import os
import sys
import time
from datetime import datetime

from .. import evidence as _EV

ROOT = _EV.ROOT
PREFIX = "라이브점검_"


def fixed_pair(root=ROOT):
    """쌍과 정답 — **대본 생성기의 상수에서** 읽는다(`LIVE_PAIR` · `LIVE_TRUTH`)."""
    p = os.path.join(root, "slides", "make_video_본선.py")
    spec = importlib.util.spec_from_file_location("make_video_for_livecheck", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.LIVE_PAIR, m.LIVE_TRUTH


def branch(verdict, truth):
    """읽을 갈래 — 판정이 정답과 같으면 ⓑ, 다르면 ⓐ. 판정이 없으면 None(촬영 전에 고쳐야 한다)."""
    if not verdict:
        return None
    return "ⓑ" if verdict == truth else "ⓐ"


def _order(path):
    """`라이브점검_20260927_2300_2.json` → ('20260927_2300', 2). 번호가 없으면 1 — 글자 순서(«_10» < «_2»)를 안 믿는다."""
    stem = os.path.basename(path)[len(PREFIX):-len(".json")]
    parts = stem.split("_")
    if len(parts) >= 3 and parts[-1].isdigit():
        return ("_".join(parts[:-1]), int(parts[-1]))
    return (stem, 1)


def records(root=ROOT):
    return sorted(glob.glob(os.path.join(root, PREFIX + "*.json")), key=_order)


def latest(root=ROOT):
    """가장 새 기록 — 없거나 못 읽으면 None."""
    rs = records(root)
    if not rs:
        return None
    try:
        with open(rs[-1], encoding="utf-8") as f:
            d = json.load(f)
        d["_파일"] = os.path.basename(rs[-1])
        return d
    except Exception:
        return None


def save(rec, root=ROOT, stamp=None):
    """**새 파일만** 쓴다 — 같은 이름이 있으면 뒤에 번호를 붙인다(덮지 않는다)."""
    stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M")
    base = os.path.join(root, "%s%s" % (PREFIX, stamp))
    path, k = base + ".json", 2
    while os.path.exists(path):
        path, k = "%s_%d.json" % (base, k), k + 1
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def _code_fp(root):
    try:
        from . import modelpair as _MP
        return _MP.fingerprint(root=root, cache="__캐시는_안_읽는다__")["코드지문"]
    except Exception as e:                                   # noqa: BLE001
        return "못 읽음(%s)" % type(e).__name__


def check(root=ROOT, runner=None, model=None, clock=time.monotonic, say=print):
    """두 번 돌리고 기록 사전을 돌려준다. `runner`·`model` 은 시험에서만 바꾼다."""
    pair, truth = fixed_pair(root)
    if model is None:
        from . import preflight as _PF
        model = _PF.submit_model()
    if runner is None:
        from .. import demo as _D

        def runner(q, progress=None):
            return _D.run_pair(q, config=_D.DEMO_CONFIG, progress=progress, exit_="표준")
    rec = {"쌍": pair, "정답": truth, "모델": model.get("모델"), "제출모델": model.get("본선"),
           "시각": datetime.now().strftime("%Y-%m-%d %H:%M"), "코드지문": _code_fp(root)}
    if not model.get("맞다"):
        rec.update(상태="모델불일치", 갈래=None)
        return rec
    runs = []
    for i in (1, 2):
        say("  %d번째 실행 — %s" % (i, pair))
        t0 = clock()
        r = runner(pair, progress=lambda st, note="": say("     · %s %s" % (st, note or "")))
        runs.append({"상태": r.get("상태"), "판정": r.get("판정"), "신뢰도": r.get("신뢰도"),
                     "사유": r.get("사유"), "비용": r.get("비용"), "초": round(clock() - t0, 1)})
    a, b = runs
    rec.update(실행=runs, 상태=a["상태"], 판정=a["판정"], 신뢰도=a["신뢰도"], 사유=a["사유"],
               같은가=(a["판정"], a["신뢰도"]) == (b["판정"], b["신뢰도"]),
               데워짐=b["초"] < max(10.0, a["초"] / 3.0),
               갈래=branch(a["판정"] if a["상태"] == "정상" else None, truth))
    return rec


def _show(rec):
    if not rec:
        print("  기록이 없다 — `.\\라이브점검.ps1` 로 한 번 돌려라")
        return
    print("  기록      %s" % rec.get("_파일", "(방금)"))
    print("  쌍 · 정답  %s · %s" % (rec.get("쌍"), rec.get("정답")))
    print("  모델      %s (제출 모델 %s)" % (rec.get("모델"), rec.get("제출모델")))
    if rec.get("상태") == "모델불일치":
        print("  ⛔ 제출 모델이 아니다 — `.env` 의 BIOREROUTE_MODEL 을 되돌린 뒤 다시(승우 손)")
        return
    runs = rec.get("실행") or []
    for i, r in enumerate(runs, 1):
        print("  %d번째     %s · %s %s · %.1f초 · 새 호출 %s"
              % (i, r.get("상태"), r.get("판정"), r.get("신뢰도"), r.get("초") or 0, r.get("비용")))
    print("  사유      %s" % (rec.get("사유") or "")[:120])
    print("  두 번 같다 %s · 캐시 데워짐 %s" % ("예" if rec.get("같은가") else "**아니다**",
                                            "예" if rec.get("데워짐") else "**아니다**"))
    g = rec.get("갈래")
    if g:
        print("\n  → 영상 나-6 은 **〔%s〕** 갈래를 읽는다 (판정 %s · 정답 %s)" % (g, rec.get("판정"), rec.get("정답")))
    else:
        print("\n  ⛔ 판정이 안 나왔다(%s) — 촬영 전에 원인을 고쳐야 한다. 쌍은 바꾸지 않는다" % rec.get("상태"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="라이브 점검 — 고정한 한 쌍을 두 번 돌려 판정·갈래를 적는다")
    ap.add_argument("--show", action="store_true", help="마지막 기록만 본다(호출 0)")
    a = ap.parse_args(argv)
    print("=" * 66)
    print("라이브 점검 — 쌍은 대본이 정한 것 하나 · 결과를 보고 안 바꾼다")
    print("=" * 66)
    if a.show:
        _show(latest())
        return 0
    rec = check()
    path = save(rec)
    rec["_파일"] = os.path.basename(path)
    _show(rec)
    print("\n  기록 → %s" % path)
    if rec.get("상태") == "모델불일치":
        return 3
    if not rec.get("갈래"):
        return 2
    if not (rec.get("같은가") and rec.get("데워짐")):
        print("  ⚠ 두 번째가 첫 번째와 다르거나 느렸다 — 촬영 전에 한 번 더 돌려 본다")
        return 4
    print("  다음 — `.\\사슬.ps1` 이 영상 대본을 다시 뽑으며 이 갈래를 표시한다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
