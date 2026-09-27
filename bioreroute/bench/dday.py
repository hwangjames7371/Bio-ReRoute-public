# -*- coding: utf-8 -*-
"""남은 날을 **세어서** 찍는다.

    py -m bioreroute.bench.dday

## 왜 모듈인가 — 결함 228

08-18에 **샌드박스 시계를 믿고 사흘을 틀렸다.** *"8/21까지 7일"* 이라
적었는데 실제로는 **D-3** 이었고, 그 위에 «코드 동결» 을 제안했다.
**계획 판단이 바뀌는 오류다.**

`CLAUDE.md §0-b` 가 그래서 «남은 날은 세어서 적는다» 를 넣었는데
**한 줄짜리 `py -c` 로 넣어 뒀다.** 그게 `.ps1` 안에서 cp949 로 깨져
`SyntaxError` 를 냈다(08-18). **안내문은 방어가 아니다** — 세는 일을
파일로 만들어 둔다.
"""
from __future__ import annotations

import datetime as _d

# `CLAUDE.md §0-b` 의 표와 **같은 값**이어야 한다 — 시험 [204] 가 그 표의 세는 줄과 대조한다.
#
# ⛔ 09-27 · **여기가 8월 일정에 멈춰 있었다**(결함 363). «본선 9/30» 은 09-05 데이콘 메일로
#   틀린 것이 확정된 추정값인데(실제 10/2), `CLAUDE.md` 만 고치고 이 목록은 안 고쳤다.
#   주석으로 «같은 값이어야 한다» 고 적어 둔 것이 **대조가 아니었다.**
MILESTONES = [
    ("회신 마감", _d.date(2026, 9, 6)),
    ("제출 마감", _d.date(2026, 10, 2)),
    ("평가 시작", _d.date(2026, 10, 6)),
    ("오프라인 말", _d.date(2026, 10, 30)),
    ("결과 발표", _d.date(2026, 11, 6)),
    ("시상식", _d.date(2026, 11, 16)),
]


def lines(today=None):
    t = today or _d.date.today()
    out = ["오늘 %s (%s)" % (t.isoformat(), "월화수목금토일"[t.weekday()])]
    for name, when in MILESTONES:
        n = (when - t).days
        out.append("  %-9s %s   %s"
                   % (name, when.strftime("%m/%d"),
                      "D-%d" % n if n > 0 else
                      "**오늘**" if n == 0 else "지났다 (%d일)" % -n))
    return out


def main() -> int:
    print("\n".join(lines()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
