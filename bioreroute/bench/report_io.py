# -*- coding: utf-8 -*-
"""보고서 출력이 **리디렉션되면 깨지던 것**을 한 곳에서 막는다

## 무엇이 났나 (2026-08-12)

한국어 Windows 에서 이렇게 하면 죽는다 —

    py -m bioreroute.bench.reversecheck --report > 역발상결과.md

    UnicodeEncodeError: 'cp949' codec can't encode character '\\u2014'

**콘솔에 찍을 때는 멀쩡하다.** PowerShell 이 `>` 로 파일에 쓸 때만
시스템 코드페이지(`cp949`)로 인코딩하기 때문이다. 우리 보고서는 한국어에
`—`(em dash)와 `«»` 를 쓰므로 전부 걸린다.

승우에게 `$env:PYTHONIOENCODING="utf-8"` 을 걸라고 했는데 **그건 임시
방편이다** — 사람이 매번 기억해야 하는 것은 방어가 아니다. 이 저장소의
표어가 *"안내문은 방어가 아니다. 구조로 막아야 한다"* 다.

## 왜 한 곳에 두나

`graphcheck` · `calibrate` · `skepticrate` · `reversecheck` 가 전부 같은
문제를 갖는다. 네 곳에 두 줄씩 복사하면 **언젠가 갈라진다**(결함 82 —
목록을 코드에 다시 적었다가 문서와 어긋난 것).
"""

from __future__ import annotations

import sys


def utf8_stdout() -> bool:
    """표준출력을 UTF-8 로 고정한다. **리디렉션돼도 안 깨진다.**

    돌려주는 값은 «바꿨는가» 다 — 이미 UTF-8 이면 `False`.
    실패해도 예외를 안 던진다. 인코딩 하나 때문에 보고서를 못 내면
    그게 더 나쁘다.
    """
    try:
        enc = (getattr(sys.stdout, "encoding", "") or "").lower()
        if enc.replace("-", "") == "utf8":
            return False
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        return True
    except Exception:
        return False
