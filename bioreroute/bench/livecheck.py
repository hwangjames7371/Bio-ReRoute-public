# -*- coding: utf-8 -*-
"""라이브 점검 — 촬영 전에 **미리 고정한 한 쌍 · 병명 하나**를 돌려 판정을 적고 캐시를 데운다 (09-27 신설 · 09-28 병명).

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

## 09-28 밤 · 병명 하나도 — 영상 나-5 «병으로 시작(가설 생성)»

영상에 **가설 생성이 한 번도 안 나왔다**(결함 373 — 공모분야 앞 절반). 나-5 를 «병으로 시작» 컷으로 바꾸면서
그 병명도 쌍과 같은 규칙을 따른다 — 병명 · 입구는 대본 생성기의 상수(`LIVE_DISEASE` · `LIVE_ENTRY`)에서 읽고
(사전명세 `사전명세_병명입구.md` 가 봉인 전에 적은 주 사례 COVID-19), 바꾸는 인자는 없다. 화면(`.\\웹.ps1`
「병으로 시작」)과 **같은 함수**(`demo.run_disease` · 표준 잣대 · 서버와 같은 기본값)로 두 번 돌린다. 첫 실행이
시간 상한(150초)에 걸려 못 태운 후보가 있으면 둘째 실행이 그것을 처음 돌리므로 «같다» 가 안 나온다 — 그때는
한 번 더 돌린다(종료 코드 4). 기록은 같은 파일의 `병명` 칸에 들어간다.

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


def _video(root=ROOT):
    p = os.path.join(root, "slides", "make_video_본선.py")
    spec = importlib.util.spec_from_file_location("make_video_for_livecheck", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fixed_pair(root=ROOT):
    """쌍과 정답 — **대본 생성기의 상수에서** 읽는다(`LIVE_PAIR` · `LIVE_TRUTH`)."""
    m = _video(root)
    return m.LIVE_PAIR, m.LIVE_TRUTH


def fixed_disease(root=ROOT):
    """병명과 입구 — **대본 생성기의 상수에서** 읽는다(`LIVE_DISEASE` · `LIVE_ENTRY` · 09-28 밤)."""
    m = _video(root)
    return m.LIVE_DISEASE, m.LIVE_ENTRY


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
                     "사유": r.get("사유"), "비용": r.get("비용"), "초": round(clock() - t0, 1),
                     # 09-29 · 결함 380 — 이 실행에서 일시 장애로 못 읽은 초록 수(다음 실행이 다시 묻는다)
                     "일시실패": r.get("일시실패")})
    a, b = runs
    rec.update(실행=runs, 상태=a["상태"], 판정=a["판정"], 신뢰도=a["신뢰도"], 사유=a["사유"],
               같은가=(a["판정"], a["신뢰도"]) == (b["판정"], b["신뢰도"]),
               데워짐=b["초"] < max(10.0, a["초"] / 3.0),
               갈래=branch(a["판정"] if a["상태"] == "정상" else None, truth))
    return rec


def _dz_summary(r, secs):
    """`run_disease` 결과 → 기록 한 줄. 후보는 [이름, 판정, 신뢰도] 로 줄여 적는다(근거 전문은 캐시에 있다)."""
    cands = [[c.get("이름"), c.get("판정"), c.get("신뢰도")] for c in (r.get("후보") or [])]
    dist = {}
    for _n, v, _p in cands:
        if v:
            dist[v] = dist.get(v, 0) + 1
    # 09-29 · 결함 380 — 두 실행이 왜 갈렸는지 **기록에서** 가르려고 일시 장애 수를 같이 적는다.
    #   09-29 01:35 기록은 두 실행이 10개 중 2개 달랐는데 이 칸이 없어 원인을 못 갈랐다.
    #   `후보` 의 꼴([이름, 판정, 신뢰도])은 그대로 둔다 — 영상 대본 · 시험이 그 꼴을 읽는다
    return {"상태": r.get("상태"), "메시지": (r.get("메시지") or "")[:200], "생성": r.get("생성"),
            "F0통과": r.get("F0통과"), "태움": r.get("태움"), "못태움": r.get("못태움"), "분포": dist,
            "후보": cands, "비용": r.get("비용"), "초": secs,
            "일시실패": r.get("일시실패"),
            "일시실패후보": {c.get("이름"): c.get("일시실패") for c in (r.get("후보") or []) if c.get("일시실패")},
            "근거수": {c.get("이름"): c.get("근거수") for c in (r.get("후보") or [])}}


def diff_cause(dz):
    """병명 두 실행이 갈렸을 때 **기록이 말하는 까닭** — 안 갈렸으면 None (09-29 · 결함 380).

    갈린 후보가 한쪽 실행에서 **일시 장애로 초록을 못 읽은** 후보면 그것이 까닭이다 — 실패는 캐시에
    안 남아 다음 실행이 다시 묻고, 받으면 근거가 채워진다. 그 칸이 없는 옛 기록이면 «못 가른다» 고 말한다.
    겹치지 않으면 **추측하지 않고** 겹치지 않는다고만 말한다.
    """
    runs = (dz or {}).get("실행") or []
    if len(runs) < 2:
        return None
    a, b = runs[0], runs[1]
    va = {q: v for q, v, _c in a.get("후보") or []}
    vb = {q: v for q, v, _c in b.get("후보") or []}
    diff = sorted(q for q in set(va) | set(vb) if va.get(q) != vb.get(q))
    if not diff:
        return None
    if a.get("일시실패") is None or b.get("일시실패") is None:
        return ("기록에 일시 장애 칸이 없다(09-29 전 기록) — 원인을 못 가른다. `.\\라이브점검.ps1` 을 한 번 더")
    ha = [q for q in diff if (a.get("일시실패후보") or {}).get(q)]
    hb = [q for q in diff if (b.get("일시실패후보") or {}).get(q)]
    if ha or hb:
        return ("갈린 %d개 중 %d개가 한쪽 실행에서 일시 장애로 초록을 못 읽은 후보다(첫째 %s · 둘째 %s) — "
                "실패는 저장하지 않아 다음 실행이 다시 묻고, 받으면 근거가 채워진다"
                % (len(diff), len(set(ha) | set(hb)), " · ".join(ha[:3]) or "없음", " · ".join(hb[:3]) or "없음"))
    return ("갈린 %d개(%s)는 초록 일시 장애 기록과 겹치지 않는다 — 이 기록으로는 원인을 못 가른다"
            % (len(diff), " · ".join(diff[:4])))


def check_disease(root=ROOT, runner=None, model=None, clock=time.monotonic, say=print):
    """병명 입구를 두 번 돌리고(데우기 · 확인) 기록 사전을 돌려준다. `runner`·`model` 은 시험에서만 바꾼다."""
    disease, entry = fixed_disease(root)
    if model is None:
        from . import preflight as _PF
        model = _PF.submit_model()
    if runner is None:
        from .. import demo as _D

        def runner(q, progress=None):
            # 서버(`web/server.py` · 「병으로 시작」)와 같은 부름 — 나머지는 전부 기본값
            return _D.run_disease(q, progress=progress, exit_="표준", entry=entry)
    rec = {"병명": disease, "입구": entry, "모델": model.get("모델")}
    if not model.get("맞다"):
        rec.update(상태="모델불일치")
        return rec
    runs = []
    for i in (1, 2):
        say("  병명 %d번째 실행 — %s (%s)" % (i, disease, entry))
        t0 = clock()
        r = runner(disease, progress=lambda st, note="": say("     · %s %s" % (st, note or "")))
        runs.append(_dz_summary(r, round(clock() - t0, 1)))
    a, b = runs
    # 화면은 **데워진 뒤의 실행**(둘째)과 같은 것을 보인다 — 그 값을 위로 올린다
    rec.update(실행=runs, **{k: b[k] for k in ("상태", "생성", "F0통과", "태움", "못태움", "분포", "후보")})
    rec["같은가"] = a["상태"] == b["상태"] and a["후보"] == b["후보"]
    rec["데워짐"] = b["초"] < max(10.0, a["초"] / 3.0)
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
    dz = rec.get("병명")
    if not dz:
        print("  병명      기록 없음 — 09-28 밤 전의 기록이다. `.\\라이브점검.ps1` 을 한 번 더")
        return
    print("\n  병명      %s (%s)" % (dz.get("병명"), dz.get("입구")))
    for i, r in enumerate(dz.get("실행") or [], 1):
        print("  %d번째     %s · 생성 %s · F0 통과 %s · 태움 %s · 못 태움 %s · %.1f초 · 새 호출 %s · 일시 장애 %s"
              % (i, r.get("상태"), r.get("생성"), r.get("F0통과"), r.get("태움"), r.get("못태움"),
                 r.get("초") or 0, r.get("비용"),
                 "기록 없음(09-29 전 기록)" if r.get("일시실패") is None else "초록 %s건" % r.get("일시실패")))
    if dz.get("상태") == "정상":
        print("  판정      %s" % " · ".join("%s %d" % kv for kv in (dz.get("분포") or {}).items()))
        print("  두 번 같다 %s · 캐시 데워짐 %s" % ("예" if dz.get("같은가") else "**아니다**",
                                                "예" if dz.get("데워짐") else "**아니다**"))
        # 09-29 · 결함 380 — 갈렸으면 **왜** 를 기록에서 읽는다
        _why = diff_cause(dz)
        if _why:
            print("  갈린 까닭 %s" % _why)
        print("  → 영상 나-5 는 이 수를 읽는다")
    else:
        print("  ⛔ 병명 실행이 정상이 아니다(%s) — %s" % (dz.get("상태"), (dz.get("메시지") or "")[:120]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="라이브 점검 — 고정한 한 쌍 · 병명 하나를 두 번 돌려 판정·갈래를 적는다")
    ap.add_argument("--show", action="store_true", help="마지막 기록만 본다(호출 0)")
    a = ap.parse_args(argv)
    print("=" * 66)
    print("라이브 점검 — 쌍 · 병명은 대본이 정한 것 하나씩 · 결과를 보고 안 바꾼다")
    print("=" * 66)
    if a.show:
        _show(latest())
        return 0
    rec = check()
    if rec.get("상태") != "모델불일치":
        rec["병명"] = check_disease()
    path = save(rec)
    rec["_파일"] = os.path.basename(path)
    _show(rec)
    print("\n  기록 → %s" % path)
    if rec.get("상태") == "모델불일치":
        return 3
    if not rec.get("갈래"):
        return 2
    dz = rec.get("병명") or {}
    if dz.get("상태") != "정상":
        return 5
    if not (rec.get("같은가") and rec.get("데워짐") and dz.get("같은가") and dz.get("데워짐")):
        print("  ⚠ 두 번째가 첫 번째와 다르거나 느렸다(쌍 또는 병명) — 촬영 전에 한 번 더 돌려 본다")
        return 4
    print("  다음 — `.\\사슬.ps1` 이 영상 대본을 다시 뽑으며 이 갈래를 표시한다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
