# -*- coding: utf-8 -*-
"""Bio-ReRoute.

## 이 파일이 하는 일은 하나다 — **표준출력을 UTF-8 로 고정한다**

### 왜 여기인가 (결함 231 · 08-18)

윈도우에서 파이썬 stdout 이 **파이프**가 되면 인코딩이 `cp949` 로 잡힌다.
그런데 이 프로젝트의 화면 문구는 `—` · `«»` · `⚠` · `⛔` 를 쓴다.
**셋 다 cp949 에 없다.**

```
py -m bioreroute.bench.parcheck                   콘솔 → 된다
py -m bioreroute.bench.parcheck | Tee-Object …    파이프 → UnicodeEncodeError
```

08-18에 `병렬.ps1` 이 정확히 그렇게 죽었다. 첫 안전한 줄 둘을 찍고
**`print("A — 일꾼 1 · 캐시 빈 것")`** 에서 터졌다.

### `PYTHONIOENCODING` 을 걸면 되는데 왜 코드로 막나

`시험.ps1` 은 그 환경변수를 걸어 뒀고 그래서 안 죽는다. **그게 문제다** —
방어가 **부르는 쪽**에 있어서, 새 `.ps1` 을 쓰거나 손으로 치면 사라진다.
08-18에 내가 새 스크립트를 쓰면서 그 두 줄을 빠뜨려 그대로 재현됐다.

> `CLAUDE.md` 머리말 — **안내문은 방어가 아니다. 구조로 막아야 한다.**

`py -m bioreroute.*` 는 **무엇이든 이 파일을 먼저 지난다.** 그래서 여기다.

### `errors="replace"` 를 쓰는 이유

`reconfigure` 가 어떤 이유로 안 먹는 환경이 있을 수 있다. 그때
**죽는 것보다 글자가 깨지는 편이 낫다** — 판정 수치는 ASCII 라 살아남고,
깨진 글자는 눈에 보여서 고칠 수 있다. 조용히 죽으면 그게 안 된다.
"""

import sys as _sys

for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass          # 3.6 이하·재정의 불가 스트림 — 여기서 죽지 않는다
