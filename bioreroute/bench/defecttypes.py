# -*- coding: utf-8 -*-
"""결함 유형 표 — **발표 막대에서 읽어** 보고서에 넣는다 (09-25 신설).

## 왜

`연구기술보고서.md §6` 의 유형 표가 **08-06 판**이었다 — 여섯 유형 · 합 49 ·
열이 깨진 줄 둘. 그런데 바로 위 문장은 `countsync` 가 따라 올려서
«결함 N건 · 유형 여덟» 을 말했다. **표제는 자동이고 표는 손**이라 갈라졌다.
결함 84 가 발표 장에서 겪은 것과 같은 모양이다(그때는 막대가 손이었다).

막대는 `slides/build_deck.py` 의 `defects` 목록이 정본이고, 시험 [65] 가
**막대 합 = 대장 행 수** 를 지킨다. 그래서 **표를 그 목록에서 만든다.**
사람이 분류하는 곳은 한 곳(막대)으로 남는다 — 분류는 사람 일이다.

⚠ `build_deck.py` 를 **실행하지 않는다**(실행하면 발표 파일을 굽는다).
`ast` 로 읽어 `defects = [...]` 의 값만 꺼낸다.
"""

import argparse
import ast
import os

DECK = os.path.join("slides", "build_deck.py")
MD_START = ("<!-- defecttypes:start — 이 사이는 `py -m bioreroute.bench.defecttypes --md-into` "
            "가 쓴다. 손으로 고치지 마라 -->")
MD_END = "<!-- defecttypes:end -->"


def rows(root="."):
    """[(유형, 건수, 대표 사례)] — `build_deck.py` 의 `defects` 에서 (실행하지 않고)."""
    src = open(os.path.join(root, DECK), encoding="utf-8").read()
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "defects" for t in node.targets)):
            return [(str(a), int(b), str(c)) for a, b, c in ast.literal_eval(node.value)]
    raise ValueError("%s 에 `defects` 목록이 없다" % DECK)


def total(root="."):
    """대장의 행 수 — `evidence.defect_count()` 와 같은 셈."""
    from .. import evidence as EV
    return EV.defect_count(os.path.join(root, "Bio-ReRoute_발견정리.md"))


def to_md(rs, n_ledger):
    s = sum(n for _, n, _ in rs)
    out = ["| 유형 | 건수 | 대표 사례 |", "|---|---:|---|"]
    for name, n, ex in rs:
        out.append("| %s | %d | %s |" % (name.replace("|", "\\|"), n, ex.replace("|", "\\|")))
    # 09-26 · «시험 [65]» 가 보고서에서 참고문헌 번호([n])처럼 읽혔다 — 괄호 없이 적는다
    out.append("| **합** | **%d** | 대장(`Bio-ReRoute_발견정리.md`)의 행 수%s — 회귀 시험 65번이 지킨다 |"
               % (s, "와 같다" if s == n_ledger else " **%s 와 다르다**" % n_ledger))
    out += ["", "*(이 표는 발표 «우리 도구를 우리가 반증한 기록» 장의 막대와 **같은 목록**에서 "
            "나온다 — `py -m bioreroute.bench.defecttypes`)*"]
    return "\n".join(out)


def md_into(path, root="."):
    """표시 사이를 새 표로 바꾼다. 표시가 없으면 **안 쓴다**(False).

    ⛔ 막대 합이 대장 행 수와 다르면 **안 쓴다**(ValueError) — 새 결함을 분류하지
    않은 채 표를 구우면 «합이 안 맞는 표» 가 제출물에 들어간다.
    """
    rs, n = rows(root), total(root)
    s = sum(x for _, x, _ in rs)
    if s != n:
        raise ValueError("막대 합 %d ≠ 대장 %s — `slides/build_deck.py` 의 막대부터 분류하라" % (s, n))
    raw = open(path, "rb").read()
    text = raw.decode("utf-8-sig")
    i, j = text.find(MD_START), text.find(MD_END)
    if i < 0 or j < i:
        return False
    new = text[:i] + MD_START + "\n" + to_md(rs, n) + "\n" + text[j:]
    if new != text:
        with open(path, "wb") as f:
            f.write((b"\xef\xbb\xbf" if raw[:3] == b"\xef\xbb\xbf" else b"") + new.encode("utf-8"))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="결함 유형 표 (발표 막대 → 보고서)")
    ap.add_argument("--root", default=".")
    ap.add_argument("--md-into", default=None,
                    help="그 파일의 defecttypes 표시 사이를 새 표로 바꾼다 (표시가 없으면 안 쓴다)")
    a = ap.parse_args(argv)
    if a.md_into:
        try:
            ok = md_into(a.md_into, a.root)
        except ValueError as e:
            print("⛔ %s" % e)
            return 3
        print(("→ %s 의 결함 유형 표를 다시 썼다" if ok
               else "⛔ %s 에 defecttypes 표시가 없다 — 안 썼다") % a.md_into)
        return 0 if ok else 2
    rs, n = rows(a.root), total(a.root)
    print(to_md(rs, n))
    return 0 if sum(x for _, x, _ in rs) == n else 3


if __name__ == "__main__":
    raise SystemExit(main())
