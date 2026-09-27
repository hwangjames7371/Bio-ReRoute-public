# -*- coding: utf-8 -*-
"""일일 실행 상한 — **비용 통제가 아니라 폭주 방지다.**

본선에서는 주최측 API를 쓰므로 심사위원이 몇 번 누르는지는 신경 쓰지 않는다.
그래도 상한을 남긴다 — **버그로 루프가 돌면 크레딧이 하루에 없어진다.**
`llm.MAX_CALLS` 는 **실행 1회당** 상한이라 그걸 못 막는다.

기본값 300. 화면에는 남은 횟수를 띄우지 않는다 — 심사위원에게 셈을
보일 이유가 없고, 무료로 쓰는 것에 눈치를 주는 모양이 된다.

## 설계 원칙 셋

1. **디스크에 남긴다.** 메모리에만 두면 프로세스가 재시작될 때마다 초기화된다.
   무료 호스팅은 수시로 재시작한다 — 그게 정확히 공격 표면이다
2. **상한을 넘으면 조용히 실패하지 않는다.** "오늘 한도 소진"이라고 적고
   미리 계산된 예시로 보낸다. **빈 결과를 내는 것이 가장 나쁘다**
3. **캐시 적중은 세지 않는다.** 돈이 안 나가기 때문이다. 예시는 무한히 눌러도 된다
"""

import json
import os
import threading
from datetime import date

PATH = os.environ.get("BIOREROUTE_BUDGET_FILE", "budget.json")
DAILY = int(os.environ.get("BIOREROUTE_DAILY_RUNS", "300"))

_LOCK = threading.Lock()


def _load():
    try:
        with open(PATH, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        d = {}
    today = date.today().isoformat()
    if d.get("날짜") != today:          # 날이 바뀌면 새로 센다
        d = {"날짜": today, "실행": 0, "차단": 0}
    return d


def _save(d):
    try:
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
        os.replace(tmp, PATH)
    except Exception:
        pass                            # 기록 실패가 서비스를 멈추면 안 된다


def status():
    d = _load()
    return {"날짜": d["날짜"], "쓴 것": d["실행"], "상한": DAILY,
            "남은 것": max(0, DAILY - d["실행"]), "차단": d.get("차단", 0)}


def take():
    """실행권 하나를 소비한다. (가능한가, 남은 수) 를 돌려준다.

    **먼저 소비하고 나중에 실행한다.** 반대로 하면 실행이 실패했을 때
    카운트가 안 올라가서, 실패를 반복시키는 것으로 상한을 우회할 수 있다.
    """
    with _LOCK:
        d = _load()
        if d["실행"] >= DAILY:
            d["차단"] = d.get("차단", 0) + 1
            _save(d)
            return False, 0
        d["실행"] += 1
        _save(d)
        return True, max(0, DAILY - d["실행"])


def refund():
    """실행이 **시작도 못 했을 때만** 되돌린다 (예: 입력 오류).

    LLM을 한 번이라도 불렀으면 돈이 나갔으므로 되돌리지 않는다.
    """
    with _LOCK:
        d = _load()
        d["실행"] = max(0, d["실행"] - 1)
        _save(d)
