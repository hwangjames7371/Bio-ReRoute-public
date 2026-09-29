# -*- coding: utf-8 -*-
"""발표 덱 — **글이 줄바꿈으로 넘쳐 옆 글자를 덮는가** (09-26 신설 · 결함 343).

    py -m bioreroute.bench.deckfit                          두 덱(25장 · 제출용 10분판)
    py -m bioreroute.bench.deckfit 어떤.pptx …               골라서

## 왜

시험 [151] 은 **글상자끼리** 겹치는지만 잰다(결함 316). 그런데 상자는 안 겹쳐도
**글이 상자보다 길면 줄이 바뀌어 상자 밖으로 흘러내린다** — 높이 0.23인치(10pt 한 줄)
상자에 두 줄이 들어가면 둘째 줄이 바로 아래 행의 이름 위에 얹힌다. 09-26 에 제출용
10분판을 **실제로 렌더해 넘겨 보니** 결함 막대 장(원본 18장 · 10분판 부록 26쪽)의 설명
둘이 그랬다 — 09-22 · 08-20 에 대표 사례를 늘리면서 생겼고, 상자 좌표는 그대로라
[151] 은 계속 초록이었다.

## 어떻게 재나 — 서체 없이

샌드박스에도 승우 컴퓨터에도 **같은 서체가 있다는 보장이 없어서** 글자 폭을 모형으로 잰다.

**09-28 다시 맞췄다(결함 372)** — 첫 판(한글 1.0em · ASCII 0.6em · 공백 0.3em · **×0.9**)은 Noto 실측에 맞춘 것이었고
«맑은 고딕은 더 좁다» 고 적었는데, **PowerPoint 가 내보낸 제출 PDF 를 재니 반대였다** — 단어 3,098개의 상자에서
한글 **1.00em**(중앙값 · 90%도 1.00) · ASCII 0.575em(90% 0.71) · `·` 0.22em · 공백 0.36em. 첫 판은 한글을 10% 작게 봐서
26쪽 결함 막대 장 첫 줄(«…실패를 감췄다») 의 **마지막 한 글자가 다음 줄로 넘어가 아래 유형 이름을 덮은 것**을 «0개» 라
했다(모형 597.6pt · 실제 약 660pt · 상자 654pt). 지금 모형 — 한글 · 그 밖의 비ASCII 1.0em · ASCII 0.6em · 공백 0.36em ·
좁은 기호(`·` `›` `×` `≠` 등)는 실측값 · 배율 없음. 같은 PDF 에서 그 한 줄만 넘친다고 하고 나머지는 맞다고 한다(오탐 0).
상자의 좌우 안쪽 여백은 **상자에 적힌 값**을 쓴다(없으면 기본 0.1in × 2). 한두 글자짜리(›)는 줄이 안 바뀐다고 본다.

⚠ **표시가 아니라 추정이다.** PowerPoint 로 내보낸 PDF 를 한 번 넘겨 보는 것은 그대로 한다.
"""

import math
import os
import sys

EMU_PT = 12700.0
INSET_PT = 14.4          # 글상자 좌우 안쪽 여백 기본값 0.1in × 2 (상자에 값이 있으면 그 값 · `insets()`)
SCALE = 1.0              # 09-28 · 배율 없음 — 제출 PDF(PowerPoint · 맑은 고딕) 실측에 맞췄다(위 docstring)
# 실측 폭이 1em 보다 한참 좁은 기호 — 제출 PDF 09-28 (그 밖의 비ASCII 는 1.0em 으로 본다 · 넘친다는 쪽으로)
NARROW = {"·": 0.25, "›": 0.35, "‹": 0.35, "×": 0.72, "≠": 0.72, "−": 0.72}
DECKS = (os.path.join("slides", "Bio-ReRoute_발표.pptx"),
         os.path.join("제출_본선", "Bio-ReRoute_발표.pptx"))


def em(ch):
    if ch == " ":
        return 0.36
    if ord(ch) < 128:
        return 0.60
    return NARROW.get(ch, 1.00)


def insets(sh):
    """좌우 안쪽 여백(pt) — 상자에 적힌 값(`lIns` · `rIns`), 없으면 기본 0.1in 씩."""
    try:
        bp = sh.text_frame._txBody.bodyPr
        l, r = bp.get("lIns"), bp.get("rIns")
    except Exception:                          # noqa: BLE001 — 모양이 다르면 기본값
        return INSET_PT
    return (int(l) / EMU_PT if l is not None else INSET_PT / 2) + (int(r) / EMU_PT if r is not None else INSET_PT / 2)


def _size(p, default=18.0):
    for r in p.runs:
        if r.font.size:
            return r.font.size.pt
    return default


def need(tf, width_pt):
    """(줄 수, 필요한 높이 pt) — 문단마다 모형 폭으로 줄 수를 센다."""
    lines, h = 0, 0.0
    for p in tf.paragraphs:
        size = _size(p)
        txt = "".join(r.text for r in p.runs)
        n = 1 if len(txt.strip()) <= 2 else max(1, math.ceil(sum(em(c) for c in txt) * size * SCALE
                                                           / max(1.0, width_pt)))
        lines += n
        h += n * size * 1.2
    return lines, h


def overflows(prs):
    """[(쪽, 넘친 글, 덮인 글)] — 넘친 부분(상자 아래)이 다른 글상자와 겹치는 것만."""
    hits = []
    for i, s in enumerate(prs.slides, 1):
        bx = []
        for sh in s.shapes:
            if not sh.has_text_frame or not sh.text_frame.text.strip():
                continue
            w = (sh.width or 0) / EMU_PT
            h = (sh.height or 0) / EMU_PT
            n, hn = need(sh.text_frame, w - insets(sh))
            bx.append((sh, (sh.left or 0) / EMU_PT, (sh.top or 0) / EMU_PT, w, h, hn, n))
        for sh, x, y, w, h, hn, n in bx:
            if n <= 1 or hn <= h + 2:
                continue
            for sh2, x2, y2, w2, h2, _hn, _n in bx:
                if sh2 is sh:
                    continue
                ox = min(x + w, x2 + w2) - max(x, x2)
                oy = min(y + hn, y2 + h2) - max(y + h, y2)
                if ox > 5 and oy > 2:
                    hits.append((i, sh.text_frame.text.replace("\n", " ")[:40],
                                 sh2.text_frame.text.replace("\n", " ")[:20]))
                    break
    return hits


def scan(path):
    """(글상자 수, 넘침 목록)."""
    from pptx import Presentation
    prs = Presentation(path)
    seen = sum(1 for s in prs.slides for sh in s.shapes
               if sh.has_text_frame and sh.text_frame.text.strip())
    return seen, overflows(prs)


def main(argv=None):
    paths = list(argv if argv is not None else sys.argv[1:]) or list(DECKS)
    bad = 0
    for p in paths:
        if not os.path.exists(p):
            print("⚪ %s 가 없다 — `py slides/build_deck.py` · `py slides/make_10min_본선.py` 부터" % p)
            bad += 1
            continue
        seen, hits = scan(p)
        print("%s %s — 글상자 %d개 · 줄바꿈으로 넘쳐 옆 글자를 덮는 것 %d개"
              % ("✅" if not hits else "🔴", p, seen, len(hits)))
        for i, a, b in hits:
            print("   · %d쪽  «%s…»  →  «%s…» 를 덮는다" % (i, a, b))
        bad += len(hits)
    return 0 if not bad else 3


if __name__ == "__main__":
    raise SystemExit(main())
