# -*- coding: utf-8 -*-
"""결함 수·시험 수를 문서에 반영한다 — **맨손 치환 대신** (결함 101)

    py -m bioreroute.bench.countsync --defects 100 --tests 1011 --p2 977
    py -m bioreroute.bench.countsync --defects 100 --tests 1011 --p2 977 --apply

## 왜 이 파일이 생겼나 — **같은 사고를 일곱 번 냈다**

결함 수가 오를 때마다 이렇게 했다.

    s = s.replace("94건", "95건")

`94건` 은 결함 수만 가리키지 않는다. `검사 못 간 **294건**` 이 있었고,
89→92→93→94→95→97→98→99→100 을 거치는 동안 **한 번에 한 자리씩
갉아먹혀 `2100건` 이 됐다.** 문서 넷에 박혔고, 08-11에 다른 걸 세다가
우연히 눈에 띄었다.

일괄 치환 사고는 이것으로 **일곱 번째**다. 그때마다 *"다음엔 세면서
하자"* 로 끝냈고 — **실제로 세면서 했는데도 났다.** 세는 것으로는 안
막힌다. 문제는 **어느 줄을 건드릴지 정하지 않은 것**이다.

## 규칙 둘

  ① **문맥이 맞는 줄만 건드린다.** `결함`·`기록`·`공개` 가 같은 줄에
     없으면 그 `N건` 은 결함 수가 아니다
  ② **바뀐 줄을 전부 찍는다.** `--apply` 없이는 아무것도 안 쓴다.
     08-11에 98줄을 눈으로 읽어서 31곳을 살렸다 — 그게 유일하게
     작동한 방어였다

> 이 파일은 **가드가 아니라 도구**다. 가드는 `docaudit` 이 한다.
> 도구를 만든 이유는 *"조심하자"* 가 일곱 번 실패했기 때문이다.
"""

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 08-13 구조 변경 (결함 159) ──────────────────────────────────
#
#   **손으로 관리하던 목록을 없앴다.** `docaudit.DOCS` 에서 파생시킨다.
#
#   왜 — 08-13 하루에 `countsync` 를 **두 번 돌렸는데 두 번 다**
#   `선행연구대조.md` · `멘토링_0813.md` 를 안 고쳤고, 그 뒤 `docaudit`
#   이 **매번 불일치를 냈다.** 목록이 둘인데 손으로 맞추고 있었기 때문이다.
#
#   ```
#   countsync 만 있던 것   렌즈답변.md ← LOG 다. 고치면 훼손이다
#   docaudit 만 있던 것    정답표감사 · 선행연구대조 · README_HF ·
#                          멘토링_0813 · FTO결과   ← 5개가 안 고쳐졌다
#   ```
#
#   **고치는 쪽이 검사하는 쪽보다 좁으면 감사는 영원히 운다.**
#   반대로 넓으면 로그를 훼손한다. **양쪽 다 사고**이므로 파생으로 막는다.
#
#   덤 — `렌즈답변.md` 가 빠지면서 `docaudit.py:71` 이 열어 둔 채로
#   적어 둔 **결함 136 의 남은 절반**(로그를 고쳐 쓸 수 있는 경로)이 닫힌다.
#   *"값이 `--old` 와 우연히 같을 때만 걸리므로 사고가 안 났을 뿐"* 이었다.
#
#   **안내문은 방어가 아니다. 구조로 막는다** — `CLAUDE.md`
from . import docaudit as _da

DOCS = [d for d in _da.DOCS if d not in set(_da.LOG)] + ["slides/build_deck.py"]


def targets(root: str = ROOT) -> List[str]:
    """실제로 **고칠 문서**. `DOCS` 에서 **봉인된 것을 뺀다** — 09-16 신설.

    ## 09-16 실측 — **봉인 7개가 이 도구의 사정권 안에 있었다**

        사전명세_도킹데모_maraviroc · 도킹표적선정 · 모델교체_본선 ·
        병명입구 · 용도특허_연도 · 전문읽기 · 종관문_16쌍

    `docaudit.DOCS` 는 *"감사가 보게 하려고"* 이것들을 등록했고
    (`docaudit.py` 가 그 자리에 **«값을 맞춰 고치라는 뜻이 아니다»** 라고
    적어 뒀다), `countsync` 는 그 목록을 **그대로 물려받아 고치는 쪽**으로
    썼다. **보라고 넣은 목록이 고치는 목록이 됐다.**

    그중 하나가 `회귀 시험 NNNN건` 을 인용하기만 하면 `--apply` 가
    **봉인을 조용히 깬다.** 오늘은 그런 줄이 **0개**라 사고가 안 났다 —
    `countsync.py:62` 가 앞선 사고를 두고 적은 그 문장 그대로다:
    *"값이 `--old` 와 우연히 같을 때만 걸리므로 사고가 안 났을 뿐."*

    **09-15에 실제로 봉인 하나를 훼손했고 1차 본문은 복구 불가다**
    (`CLAUDE.md §3`). 그때 닫은 방법은 안내문이었다. 이번엔 구조다.

    ⚠ **넓게 빼지 않는다.** 「이름에 `사전명세` 가 들어가면 뺀다」로
      하면 *봉인이 없는* `사전명세_*_반증.md` 까지 빠져 **고쳐야 할 것을
      안 고친다**(결함 159: *"고치는 쪽이 검사하는 쪽보다 좁으면 감사는
      영원히 운다"*). **봉인 json 이 실제로 가리키는 것만** 뺀다.
    """
    # `sealed_docs` 는 **봉인 json 에 적힌 대로의 경로**를 준다.
    # 이름으로 맞춘다 — `DOCS` 는 `slides/build_deck.py` 처럼 폴더가
    # 붙은 것이 섞여 있어 문자열 그대로 비교하면 어긋난다.
    sealed = {os.path.basename(x) for x in _da.sealed_docs(root)}
    return [d for d in DOCS if os.path.basename(d) not in sealed]


# (이름, 그 줄에 **반드시** 있어야 하는 말, 값 정규식)
#   문맥 낱말이 없으면 안 건드린다. `294건`(검사 못 간 인용)이 결함 수로
#   읽히지 않게 하는 것이 이 표의 전부다.
#
# ── 09-26 · **문맥이 «줄» 이면 우연히 같은 수가 따라 올라간다** (결함 359) ──
#
#   앞판의 결함 규칙은 «결함» 이 **줄 어디에든** 있으면 그 줄의 `(옛 수)건` 을
#   **전부** 새 수로 바꿨다. 결함 수가 우연히 그 줄의 다른 수를 지나가면 —
#
#       결함 237 행  «`사전명세_생성실험` 이 이 프롬프트로 340건을 쟀다»
#                    ← 생성 후보 340(보고서 §4.5). 대장이 340행을 지난 09-26 에
#                      342 → 345 로 바뀌었다(git: 08-20 ~ 09-25 21:41 은 340)
#       발표뼈대:94  «08-10 재분류. 89건, 유형별 17·9·9·7·19·21·7» ← 합이 89 다.
#                    08-20 커밋에 이미 287 · 지금 345
#
#   **기록이 결함 수를 따라 움직였다.** 그래서 결함 수는 `docaudit` 이 **감사하는
#   꼴 그대로만** 고친다 — «결함» 바로 뒤(4자 안) · «공개한» · «반증한 기록» 바로 뒤의
#   수. 무엇이 주장인가를 **두 도구가 같은 모양으로** 본다(결함 136 의 원칙).
#   시험 수는 네 자리라 우연한 충돌이 드물어 앞판 그대로 둔다(한계로 적는다).
RULES: List[Tuple[str, str, str]] = [
    ("결함", r"결함|반증한 기록|공개한",
     r"(결함[^\n]{0,4}?|공개한\s*\**\s*|반증한 기록\s*\**\s*)(?<![0-9])(%s)건"),
    ("시험", r"회귀 시험|시험 \d+\s*\+", r"()(?<![0-9])(%s)건"),
]


_SUM = re.compile(r"(?<![0-9])(\d+)\s*\+\s*(\d+)\s*=\s*(\*{0,2})(\d+)\3")


def _fix_sum(line: str, old_total: int, new_total: int, root: str) -> str:
    """`34+2013 = **2047**` 꼴을 고친다 (결함 309).

    **합계만으로는 못 고친다** — 두 항을 따로 알아야 한다.
    `시험정본.json` 이 `phase1`·`phase2` 를 들고 있으므로 그것을 쓴다.
    **정본이 없거나 합이 안 맞으면 손대지 않는다** — 모르면 안 고치고
    `docaudit` 이 빨간 채로 두는 편이 낫다(결함 99: 침묵과 통과는 다르다).
    """
    m = _SUM.search(line)
    if not m or int(m.group(4)) != old_total:
        return line
    t = _da.truth_tests(root)
    if not t or t["합"] != new_total:
        return line
    try:
        d = json.load(open(os.path.join(root, _da.TRUTH_FILE), encoding="utf-8"))
        p1, p2 = int(d["phase1"]), int(d["phase2"])
    except Exception:
        return line
    if p1 + p2 != new_total:
        return line
    return line[:m.start()] + "%d+%d = %s%d%s" % (
        p1, p2, m.group(3), new_total, m.group(3)) + line[m.end():]


# ── **줄바꿈을 보존한다** — 09-16 (결함 220 계열) ──────────────────
#
#   앞판은 `open(p, encoding="utf-8")` 으로 읽고 `open(p, "w", …)` 로 썼다.
#   **윈도우에서 돌리면 아무 일도 안 난다** — 읽을 때 `\r\n`→`\n`,
#   쓸 때 `\n`→`\r\n` 이라 왕복이 같다.
#
#   09-16 실측: 저장소가 **섞여 있다** — `발견정리`·`재현절차`·`다음할일`·
#   `slides/build_deck.py` 가 **CRLF**, `연구기술보고서`·`파일지도` 가 **LF**.
#   그래서 **리눅스(또는 CI)에서 한 번만 돌려도 CRLF 파일 넷이 통째로
#   LF 로 바뀐다.** 숫자 한 줄을 고치려고 **파일 전체가 diff 가 된다** —
#   그중 하나는 코드다.
#
#   `newline=""` 은 **양쪽에서 번역을 끈다.** 읽은 그대로 쓴다.
#   *"검증 환경이 실행 환경과 다르면 그 검증은 거짓말이다"* — `CLAUDE.md §5`.
def _read(path: str) -> List[str]:
    """줄바꿈을 **번역하지 않고** 읽는다. `\r` 은 줄 끝에 붙어 온다."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().split("\n")


def _write(path: str, lines: List[str]) -> None:
    """읽은 그대로 쓴다. `\n` 을 OS 규약으로 바꾸지 않는다."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines))


def plan(old: Dict[str, int], new: Dict[str, int],
         root: str = ROOT) -> List[Tuple[str, int, str, str]]:
    """바꿀 줄 목록. **파일은 안 건드린다.**

    ⚠ `DOCS` 가 아니라 **`targets(root)`** 를 돈다 — 봉인된 문서를 뺀
    목록이다. 이유는 `targets` 의 독스트링.
    """
    out = []
    for fn in targets(root):
        p = os.path.join(root, fn)
        if not os.path.exists(p):
            continue
        lines = _read(p)
        fence = False
        for i, line in enumerate(lines, 1):
            # ── **기록을 고쳐 쓰지 않는다** (결함 136) ────────────────
            #
            #   08-12 실측: `발견정리.md:1604` 은 ```펜스``` 안에서 *"그때
            #   슬라이드가 `결함 39건` 이라 말했다"* 를 **인용**하는 줄인데
            #   이 도구가 그걸 `135건` 으로 바꾸려 했다. 바꿨으면 **결함을
            #   발견한 기록 자체가 사라진다.**
            #
            #   결함 61 계열의 다섯 번째다 — 가드가 인용을 주장으로 읽는다.
            if line.lstrip().startswith("```"):
                fence = not fence
                continue
            if fence:
                continue
            # ── 09-26 · **`docaudit` 이 기록으로 건너뛰는 줄은 이 도구도 안 고친다** (결함 359) ──
            #   대장 행(`| 237 | **…** |`) · «…결함 N건…» 인용 · 날짜 열 이력 표 · 명령 주석 ·
            #   «실제는» 줄. 감사기는 이 줄들을 «그때 그랬다» 로 읽어 안 보는데, 이 도구는
            #   고쳐 쓰고 있었다 — 한 줄이 두 도구에게 **다른 종류**였다. 판정은 `_skip` 한 곳.
            if _da._skip(line):
                continue
            new_line = line
            for key, ctx, pat in RULES:
                if key not in old or old[key] == new[key]:
                    continue
                if not re.search(ctx, new_line):
                    continue
                new_line = re.sub(pat % old[key],
                                  lambda m, _n=new[key]: "%s%d건" % (m.group(1), _n), new_line)
            # ── **합산식은 `건` 이 안 붙는다** (결함 309) ──────────────
            #
            #   `파일지도.md` 가 *"시험 34+2013 = **2047**"* 라고 적는다.
            #   위 규칙은 `(N)건` 꼴만 보므로 **이 줄을 세 번 놓쳤고**
            #   나는 세 번 손으로 고쳤다. `docaudit` 은 이 줄을 «시험
            #   합산표기» 로 **보고 있었다** — 즉 **보는 눈은 있는데
            #   고치는 손이 없었다.** 결함 82 계열이다.
            #
            #   합계만으로는 못 고친다(34 와 2013 을 따로 알아야 한다).
            #   그래서 **`시험정본.json` 을 읽는다** — 사람이 안 센다.
            if old.get("시험") != new.get("시험"):
                new_line = _fix_sum(new_line, old["시험"], new["시험"], root)
            if new_line != line:
                out.append((fn, i, line, new_line))
    return out


def apply(rows: List[Tuple[str, int, str, str]], root: str = ROOT) -> int:
    by: Dict[str, Dict[int, str]] = {}
    for fn, i, _, nl in rows:
        by.setdefault(fn, {})[i] = nl
    for fn, m in by.items():
        p = os.path.join(root, fn)
        lines = _read(p)
        for i, nl in m.items():
            lines[i - 1] = nl
        _write(p, lines)
    return len(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="결함·시험 수 동기화 (결함 101)")
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--defects", type=int, required=True, help="새 결함 수")
    ap.add_argument("--tests", type=int, required=True, help="새 회귀 시험 합계")
    ap.add_argument("--old-defects", type=int, required=True)
    ap.add_argument("--old-tests", type=int, required=True)
    ap.add_argument("--apply", action="store_true",
                    help="**없으면 아무것도 안 쓴다.** 먼저 눈으로 읽어라")
    a = ap.parse_args(argv)

    rows = plan({"결함": a.old_defects, "시험": a.old_tests},
                {"결함": a.defects, "시험": a.tests}, a.root)
    print("=" * 66)
    print("결함 %d→%d · 시험 %d→%d   바꿀 줄 %d개"
          % (a.old_defects, a.defects, a.old_tests, a.tests, len(rows)))
    print("=" * 66)
    for fn, i, old, new in rows:
        print("%s:%d" % (fn, i))
        print("  - %s" % old.strip()[:110])
        print("  + %s" % new.strip()[:110])
    if not rows:
        print("바꿀 것이 없다.")
        return 0
    if not a.apply:
        print("\n**아무것도 안 썼다.** 위를 다 읽고 `--apply` 를 붙여라.")
        print("  08-11에 98줄을 읽어 31곳을 살렸다. 읽는 것이 방어다.")
        return 0
    n_applied = apply(rows, a.root)
    print("\n%d줄 적용." % n_applied)
    # ── ⛔ 09-19 · **소스를 고쳐도 산출물은 안 따라온다** (결함 307 계열) ──
    #
    #   `slides/build_deck.py` 의 숫자를 고쳐도 **`.pptx` 는 그대로**다.
    #   그런데 `docaudit` 은 **pptx 안의 글자까지** 센다. 그래서
    #   *«고쳤는데 또 빨갛다»* 가 되고, 09-19 에 이걸로 **두 번** 왕복했다.
    #
    #   고치는 손이 **소스까지만** 있었다. 굽는 것은 사람 몫이므로
    #   **적어도 말은 해 준다** — `재현절차.md` 에 있지만 **도구가
    #   말해 주는 편이 낫다**(오늘 배운 것).
    if any("build_deck" in r[0] for r in rows):
        print("  ⚠ **슬라이드 소스를 고쳤다 — `.pptx` 는 아직 옛 숫자다.**")
        print("     py slides/build_deck.py        ← 다시 구워야 한다")
        print("     (`docaudit` 은 pptx 안의 글자도 센다)")
    print("  → `py -m bioreroute.bench.docaudit --tests %d` 로 확인해라." % a.tests)
    return 0


if __name__ == "__main__":
    sys.exit(main())
