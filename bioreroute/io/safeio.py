# -*- coding: utf-8 -*-
"""**되돌릴 수 있게 쓴다** — 결과 파일 저장의 유일한 통로.

    from ..io.safeio import save_json
    save_json(obj, "결과.json")        # 있으면 `.bak` 을 남기고 쓴다

## 왜 이 파일이 생겼나 (결함 223)

`CLAUDE.md §3-3` 이 *"결과 파일을 확인 없이 덮어쓰지 마라 (`--out`
기본값 주의)"* 라고 적어 뒀다. 그런데 **규칙만 있고 구조가 없었다.**

08-15 밤 실행에서 내가 만든 스크립트가 `--out` 을 안 줬고,
`bench_results.json`(08-04 · 17 KB · **B0 포함**)이 그대로 사라졌다.
코드는 *"행 집합이 달라 버린다"* 고 **말은 했는데 아무 데도 안 남겼다.**

> **경고는 방어가 아니다.** 08-11에도 같은 사고가 났고(결함 145) 그때는
> `io/fto._save_index` 에만 `.bak` 을 붙였다. **한 곳만 고쳤다.**

## 왜 새 함수를 만들지 않고 옮겼나

`fto._write_json` 이 이미 이 일을 하고 있었다. 거기 두고 `bench/` 에
비슷한 걸 하나 더 만들면 **같은 방어가 두 곳**이 되고, 그건 결함 98
(«어제 한 갈래만 고쳤다»)·222(«손목록이 두 곳») 가 난 방식이다.

그래서 **여기로 올리고 `fto` 가 이걸 부르게** 했다. 방어가 한 곳이다.

## 무엇을 보장하고 무엇을 안 하나

    보장한다   덮어쓰기 전에 **직전 판이 `.bak` 으로 남는다**
    안 한다    판(版)을 여러 개 쌓지 않는다 — `.bak` 은 **한 판**이다
               두 번 연속 덮으면 두 판 전은 사라진다

**한 판이면 충분하다고 판단한 근거** — 실제 사고 둘(145·223)이 전부
*"방금 돌린 것이 앞 판을 지웠다"* 였다. 여러 판이 필요한 자료는
`--out` 을 다르게 주거나 `archive/` 로 옮기는 것이 맞다.
"""

import json
import os
from typing import Any, Optional


def backup(path: str) -> "tuple[Optional[str], str]":
    """`(백업경로, 상태)` 를 돌려준다. **상태는 셋이다.**

        ("…bak", "남김")     덮어쓸 것이 있었고 백업했다
        (None,   "없음")     원래 파일이 없다 — 백업할 게 없다
        (None,   "실패: …")  **파일이 있는데 백업을 못 했다** ← 위험

    ## 왜 셋으로 나누나 (08-18 렌즈 7)

    앞판은 셋을 **전부 `None`** 으로 뭉갰다. 그래서 «파일이 없었다» 와
    «백업이 실패했다» 가 구별이 안 됐고, 부른 쪽은 **백업 없이 덮어쓴
    것을 알 방법이 없었다.** 결함 89 계열 — «없는 것과 못 잰 것을 안 가름».

    그리고 그게 정확히 **결함 223 이 난 상황**이다: 디스크가 차거나
    파일이 잠겨 백업이 실패했는데 조용히 덮으면 원본을 잃는다.
    """
    if not os.path.exists(path):
        return None, "없음"
    try:
        import shutil
        shutil.copyfile(path, path + ".bak")
        return path + ".bak", "남김"
    except Exception as e:
        return None, "실패: %s: %s" % (type(e).__name__, e)


def save_json(obj: Any, path: str, indent: Optional[int] = None) -> dict:
    """JSON 을 쓴다. **덮어쓰기 전에 `.bak`.**

    ## 백업이 실패하면 **원본을 안 덮는다** (08-18)

    앞판은 *"백업이 안 되는 것보다 결과를 아예 못 쓰는 것이 더 나쁘다"*
    는 이유로 그냥 덮었다. **그 절충이 틀렸다** — 둘 다 살릴 수 있다.

        백업 실패  →  `path.new` 에 쓴다. **원본도 살고 결과도 산다**

    `CLAUDE.md` — *"안내문은 방어가 아니다. 구조로 막아야 한다."*
    경고를 찍고 덮는 것은 안내문이다.

    돌려주는 것: `{경로, 백업, 상태, 원본유지}`
    """
    b, why = backup(path)
    if why.startswith("실패"):
        alt = path + ".new"
        json.dump(obj, open(alt, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=indent)
        return {"경로": alt, "백업": None, "상태": why, "원본유지": True}
    json.dump(obj, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=indent)
    return {"경로": path, "백업": b, "상태": why, "원본유지": False}
