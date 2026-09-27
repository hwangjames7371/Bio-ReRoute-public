# -*- coding: utf-8 -*-
"""제안서 대조표 감사 — **렌즈 1·2를 기계가 보게 한다** (결함 67)

    py -m bioreroute.bench.specaudit
    py -m bioreroute.bench.specaudit --stale-days 30

## 왜 이 파일이 생겼나

승우가 물었다 — *"길을 잃어버리지 않게 파이프라인 가이드라인 역할도
이게 해주는 거야? 중간에 놓칠 수도 있을 것 같아서, 제안서에 있는 내용을."*

**안 해 줬다.** `검증절차.md` 의 아홉 렌즈 중 **1·2번(제안서 항목 대조)만
아직 🟡 "문서 대조"** 다. 뜻이 이렇다 —

    렌즈 3~9   preflight 이 본다
    렌즈 1·2   **사람이 md 를 눈으로 읽는다**

그런데 렌즈 1·2가 **제안서를 지키는 렌즈**다. 가장 중요한 둘이 가장
자동화가 안 돼 있었다. 그리고 그 결과가 기록에 남아 있다 —

| 결함 | 무엇 | 걸린 시간 |
|---|---|---|
| 43 | §1.2(hERG·저분자)와 §6(3분할)을 통째로 빠뜨림 | 처음부터 |
| 47 | `TN 42건` 이 `효능 실패 42건` 의 대리물이었음 | 처음부터 |
| 63 | §2.5 는 `활성부위` 인데 코드는 **전체 평균** | 처음부터 |

**셋 다 "표에는 적혀 있는데 코드가 다른 것"** 이다. 표를 사람이 읽으면
*적혀 있다*는 사실만 확인하고 넘어간다. **적힌 것과 코드가 같은지는
안 본다.**

## 이 감사가 보는 것 — 셋

    ① 표가 인용한 코드 심볼이 **실재하는가**
       `io/tox.small_molecule` 이라 적혀 있으면 그 함수가 있어야 한다
       없으면 표가 **없는 것을 있다고 말하는 중**이다

    ② ✅ 로 적은 것이 **실제로 도는가**
       `unwired` 검사와 연결한다 — 아무도 안 부르는 모듈을 ✅ 로
       적어 둔 것이 결함 44 였다

    ③ 🟡 가 **얼마나 오래 🟡 인가**
       🟡 는 "부분"이라 편하다. 그래서 영원히 🟡 로 남는다.
       마감이 22일 남았을 때 **오래된 🟡 은 사실상 ❌** 다

## 이 감사가 **못 보는 것** — 먼저 적는다

**의미를 못 본다.** `io/structure.py` 가 존재하는지는 보지만, 그것이
§2.5 가 요구한 *활성부위* 를 재는지는 **모른다.** 결함 63 을 이 검사가
잡을 수 있었을까 — **못 잡는다.**

    잡는 것    표 → 코드의 **존재** 불일치
    못 잡는 것  표 → 코드의 **의미** 불일치   ← 결함 47·63이 여기다

그러니 이건 렌즈 1·2의 **절반**이다. 나머지 절반(구성 개념 타당도)은
렌즈 4이고 여전히 사람이 봐야 한다. **절반이라고 적어 두는 것이
이 파일의 정직한 위치다.**

그리고 **표 자체가 진실이라고 가정한다.** 표에 아예 안 적힌 제안서 항목은
이 검사에 안 잡힌다 — 그게 결함 43 이었고, 그때 만든 방어가
`제안서_전수대조.md`(§3.3 밖까지 훑기) 그 자체다. **문서를 늘리는 것이
그 층의 방어이고 코드가 할 수 있는 일이 아니다.**
"""

import argparse
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SPEC_DOCS = ("제안서_전수대조.md", "제안서_대조표.md")

# 표 행에서 상태 기호를 읽는다. **첫 기호를 쓴다** — 한 행에 여러 개가
# 나오면(`❌ / 🟡(ChEMBL)`) 더 나쁜 쪽을 먼저 적는 것이 이 문서의 규약이다.
_MARK = re.compile(r"[✅🟡❌]")

# 백틱 안에서 코드 심볼로 볼 것.
#   `io/tox.small_molecule`  `core/profiles.py`  `gates.time_to_refute`
#   `dash.left`  `bench/faithful.py`
# **한글이 섞이면 코드가 아니다** — `보류` · `조건부` 같은 판정 라벨을
# 심볼로 착각하면 오탐이 쌓이고, 오탐이 쌓이면 가드는 꺼진다.
_SYM = re.compile(r"^[A-Za-z_][\w]*(?:[./][\w_]+)+(?:\.py)?$")


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse(root: str = ROOT) -> List[Dict[str, Any]]:
    """대조표의 상태 행을 읽는다. **어느 문서·몇 행인지 같이 남긴다.**"""
    out = []
    for d in SPEC_DOCS:
        p = os.path.join(root, d)
        if not os.path.exists(p):
            continue
        lines = open(p, encoding="utf-8").read().split("\n")
        for i, line in enumerate(lines, 1):
            if not line.startswith("|"):
                continue
            m = _MARK.search(line)
            if not m:
                continue
            syms = [t for t in re.findall(r"`([^`]+)`", line) if _SYM.match(t)]
            out.append({"문서": d, "행": i, "상태": m.group(0),
                        "심볼": syms, "원문": line.strip()[:120]})
    return out


def _find_file(rel: str, root: str) -> Optional[str]:
    """`io/tox.py` 같은 상대 경로를 찾는다. **루트도 본다.**

    첫 판이 `bioreroute/` 아래만 봐서 `app.py`(저장소 루트)를 없다고 했다.
    """
    for base in (os.path.join(root, "bioreroute"), root):
        p = os.path.join(base, rel)
        if os.path.exists(p):
            return p
    # 파일명만 주어졌으면 전수 탐색 (`gates.py` 처럼 패키지 경로 생략)
    name = os.path.basename(rel)
    for dirpath, _dn, files in os.walk(os.path.join(root, "bioreroute")):
        if "__pycache__" in dirpath:
            continue
        if name in files:
            return os.path.join(dirpath, name)
    return None


def _module_path(sym: str, root: str) -> Tuple[Optional[str], bool]:
    """심볼 → (파일 경로, 파일 자체를 가리키는가). 없으면 (None, False).

    ## 첫 판이 오탐 둘을 냈다 — 그 기록을 남긴다

    ```
    app.py          ← 저장소 **루트**에 있는데 bioreroute/ 아래만 봤다
    bench.analyze   ← `bench/analyze.py` **모듈**인데 `bench` 안의 이름으로 읽었다
    ```

    둘째가 구조적인 문제다. **`a.b` 는 중의적이다** —
    `bench.analyze`(모듈)일 수도 `gates.time_to_refute`(모듈 안 이름)일
    수도 있다. 그래서 **모듈로 먼저 해석하고, 파일이 없으면 이름으로
    내려간다.** 순서를 뒤집으면 모듈 참조가 전부 "이름 없음"이 된다.

    > 이 프로젝트의 규율 — **오탐이 쌓이면 가드는 꺼진다.**
    > 예외 목록을 만들지 않고 해석 순서를 고쳤다.
    """
    if sym.endswith(".py"):
        return _find_file(sym, root), True
    if "." not in sym:
        return None, False
    # ① 심볼 전체를 모듈 경로로 본다 — `bench.analyze` → `bench/analyze.py`
    whole = _find_file(sym.replace(".", os.sep) + ".py", root)
    if whole:
        return whole, True
    # ② 마지막 점 뒤를 이름으로 본다 — `io/tox.small_molecule`
    mod = sym.rpartition(".")[0]
    return _find_file(mod.replace(".", os.sep) + ".py", root), False


def check_symbol(sym: str, root: str = ROOT) -> Dict[str, Any]:
    """심볼이 실재하는가. **파일과 이름을 따로 본다.**

    파일은 있는데 이름이 없는 경우가 가장 위험하다 — 리팩터링이 함수를
    옮겼는데 표는 그대로인 상태이고, `--help` 로는 안 잡힌다(결함 20).
    """
    r = {"심볼": sym, "파일": None, "있다": False, "왜": None}
    # ── 08-12 — **자료 파일은 코드 심볼이 아니다** (결함 135) ──────────
    #
    #   `calibration.json` 을 표에 적었더니 이 검사가 «모듈 파일을 못
    #   찾았다» 로 빨개졌다. 화면이 읽는 산출물을 표에 적는 것은 **정상**
    #   이고, 오히려 그걸 적으라고 우리가 규칙을 만들었다.
    #
    #   확장자가 붙은 것은 **디스크에서 찾는다.** 없으면 그것도 결함이다 —
    #   «표가 없는 파일을 가리킨다» 는 심볼일 때와 똑같이 위험하다.
    if re.search(r"\.(json|csv|tsv|md|pptx|pdf|zip|ots|txt)$", sym):
        q = os.path.join(root, sym)
        r["파일"] = sym
        r["있다"] = os.path.exists(q)
        if not r["있다"]:
            r["왜"] = "표가 가리키는 **파일이 디스크에 없다**"
        return r
    p, is_file = _module_path(sym, root)
    if not p:
        r["왜"] = "모듈 파일을 못 찾았다"
        return r
    r["파일"] = os.path.relpath(p, root)
    if is_file:
        r["있다"] = True
        return r
    name = sym.rpartition(".")[2]
    try:
        src = open(p, encoding="utf-8").read()
    except Exception as e:
        r["왜"] = "%s: %s" % (type(e).__name__, e)
        return r
    # 정의를 찾는다. 상수·함수·클래스 셋 다.
    pat = re.compile(r"^\s*(?:def|class)\s+%s\b|^%s\s*[:=]" % (re.escape(name),
                                                               re.escape(name)),
                     re.M)
    if pat.search(src):
        r["있다"] = True
    else:
        r["왜"] = "파일은 있는데 `%s` 정의가 없다" % name
    return r


def git_age(path: str, root: str = ROOT) -> Optional[int]:
    """이 행이 마지막으로 바뀐 뒤 며칠 지났나. git 이 없으면 None.

    **mtime 을 쓰지 않는다** — 문서를 한 줄 고치면 전체가 새로워진다.
    git 이 없는 환경에서는 **모른다고 답한다.** 0으로 채우지 않는다.
    """
    try:
        # ⚠ encoding 명시 — 파일명에 한글이 있으면 cp949 로 터진다(08-27)
        p = subprocess.run(["git", "log", "-1", "--format=%ct", "--", path],
                           cwd=root, capture_output=True, text=True, timeout=20,
                           encoding="utf-8", errors="replace")
        t = (p.stdout or "").strip()
        return int((time.time() - int(t)) / 86400) if t else None
    except Exception:
        return None


def audit(root: str = ROOT, stale_days: int = 30) -> Dict[str, Any]:
    rows = parse(root)
    counts = {"✅": 0, "🟡": 0, "❌": 0}
    for r in rows:
        counts[r["상태"]] += 1

    checks, broken = [], []
    for r in rows:
        for sym in r["심볼"]:
            c = check_symbol(sym, root)
            c["상태"] = r["상태"]
            c["문서"] = "%s:%d" % (r["문서"], r["행"])
            checks.append(c)
            if not c["있다"]:
                broken.append(c)

    # ✅ 인데 인용 심볼이 하나도 없는 행 — **근거 없는 ✅**
    #   "구현했다"고만 적고 어디인지 안 적으면 다음 사람이 확인할 수 없다.
    no_evidence = [r for r in rows if r["상태"] == "✅" and not r["심볼"]]

    return {"행": len(rows), "집계": counts, "검사": checks, "깨짐": broken,
            "근거없는_✅": no_evidence, "stale_days": stale_days,
            "문서나이": {d: git_age(d, root) for d in SPEC_DOCS
                     if os.path.exists(os.path.join(root, d))}}


def report(r: Dict[str, Any]) -> int:
    c = r["집계"]
    tot = r["행"]
    print("=" * 70)
    print("제안서 대조표 감사 — **렌즈 1·2의 절반** (존재만 본다)")
    print("=" * 70)
    print("\n[1] 약속 대비 현재 — 표 %d행" % tot)
    print("─" * 70)
    for k, label in (("✅", "완료"), ("🟡", "부분"), ("❌", "없음")):
        n = c[k]
        bar = "█" * int(40 * n / tot) if tot else ""
        print("    %s %-4s %3d  %4.1f%%  %s" % (k, label, n, 100 * n / tot, bar))
    print("\n    **🟡 가 %d개다.** 🟡 는 편해서 영원히 남는다 —" % c["🟡"])
    print("    마감이 가까울 때 오래된 🟡 은 사실상 ❌ 다.")

    print("\n[2] 표가 인용한 코드가 **실재하는가** — %d개" % len(r["검사"]))
    print("─" * 70)
    if r["깨짐"]:
        print("  ⚠ **%d개가 없다. 표가 없는 것을 있다고 말하는 중이다.**"
              % len(r["깨짐"]))
        for b in r["깨짐"]:
            print("     %s  `%s`" % (b["상태"], b["심볼"]))
            print("       %s — %s" % (b["문서"], b["왜"]))
    elif not r["검사"]:
        # **공허한 참을 통과로 찍지 않는다.** 검사한 게 0개면 "전부 실재한다"는
        # 아무 말도 아니다 — `faithful.py` 의 `0건 걸림 ≠ 깨끗하다` 와 같은 층이고,
        # 이 프로젝트가 결함 35에서 배운 것(안 돌린 것과 통과한 것은 다르다)이다.
        print("    ⚠ **인용 심볼이 0개다.** \"전부 실재한다\"가 아니라")
        print("      **확인할 것이 없었다**는 뜻이다. 표에 코드를 안 적었다.")
    else:
        print("    전부 실재한다 (%d개)" % len(r["검사"]))
        by = {}
        for x in r["검사"]:
            by.setdefault(x["상태"], []).append(x["심볼"])
        for k in ("✅", "🟡", "❌"):
            if by.get(k):
                print("      %s %s" % (k, ", ".join(sorted(set(by[k])))[:100]))

    print("\n[3] **근거 없는 ✅** — 어디인지 안 적은 완료 표시")
    print("─" * 70)
    if r["근거없는_✅"]:
        print("    %d행. 심볼을 안 적으면 다음 사람이 확인할 수 없다."
              % len(r["근거없는_✅"]))
        for x in r["근거없는_✅"][:6]:
            print("      %s:%d  %s" % (x["문서"], x["행"], x["원문"][:78]))
        if len(r["근거없는_✅"]) > 6:
            print("      … 외 %d행" % (len(r["근거없는_✅"]) - 6))
        print("\n    **이걸 실패로 세지 않는다** — 표에는 산문 근거가 붙은 행도")
        print("    있고, 전부 심볼을 달게 하면 문서가 읽기 어려워진다.")
    else:
        print("    없음")

    print("\n[4] 대조표 자체가 낡았나")
    print("─" * 70)
    for d, age in r["문서나이"].items():
        if age is None:
            print("    %-22s git 이력 없음 — **모른다고 적는다**" % d)
        else:
            mark = "  ⚠ %d일 지났다" % age if age > r["stale_days"] else ""
            print("    %-22s %s일 전%s" % (d, age, mark))

    print("\n" + "=" * 70)
    print("이 감사가 **못 보는 것**")
    print("=" * 70)
    print("  · **의미를 못 본다.** `io/structure.py` 가 있는지는 보지만")
    print("    그것이 §2.5 의 *활성부위* 를 재는지는 모른다.")
    print("    **결함 63 을 이 검사는 못 잡았을 것이다** — 렌즈 4가 봐야 한다")
    print("  · **표에 안 적힌 제안서 항목**은 안 잡힌다 (결함 43 이 그것이다)")
    print("  · 🟡 의 나이를 **행 단위로는** 모른다. 문서 단위만 본다")

    print("\n" + "=" * 70)
    if r["깨짐"]:
        print("**표가 가리키는 코드 %d개가 없다.** 표를 고치거나 코드를 만들어라."
              % len(r["깨짐"]))
        return 1
    if not r["검사"]:
        # 여기도 같은 함정이었다 — [2] 에서는 고쳤는데 **마지막 줄에 남아
        # 있었다.** 시험이 마지막 줄까지 봐서 잡았다.
        print("확인한 인용이 **0개다.** 통과가 아니라 **검사할 것이 없었다.**")
        return 0
    print("표가 가리키는 코드는 전부 실재한다. **의미는 사람이 봐라.**")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="제안서 대조표 감사 — 렌즈 1·2의 절반 (결함 67)")
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--stale-days", type=int, default=30,
                    help="대조표가 이보다 오래됐으면 경고")
    a = ap.parse_args(argv)
    return report(audit(a.root, a.stale_days))


if __name__ == "__main__":
    sys.exit(main())
