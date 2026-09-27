# -*- coding: utf-8 -*-
"""안전 게이트 — 제안서 §5가 약속한 것.

> 오남용 방지를 위해, 통제 물질(Australia Group·화학무기금지협약 목록)이
> 질의되거나 도출되면 프로세스를 강제 종료하고 로그를 남기는 안전
> 에이전트를 파이프라인 최상단에 배치한다.

## 이 방어의 한계를 먼저 적는다

**이름 대조는 약한 방어다.** 철자를 바꾸거나 CAS 번호를 쓰거나 별칭을
쓰면 빠져나간다. 이 프로젝트의 원칙이 *"안내문은 방어가 아니다. 구조로
막아야 한다"* 인데, **이건 구조가 아니라 목록이다.**

그래도 두는 이유는 둘이다.

1. **제안서가 약속했다.** 안 하면 안 한 것이고, 하면 한 것이다
2. 실수로 들어오는 것은 막는다. 작정하고 우회하는 것은 못 막는다

**이 파일이 하는 일은 차단이지 탐지가 아니다.** 목록에 있는 이름이 오면
멈추고 기록한다. 목록을 늘려 탐지력을 높이려 하지 않는다 — 그러면
"무엇이 통제 물질인가"를 이 파일이 가르치는 꼴이 된다.

## 무엇을 넣었나

화학무기금지협약(CWC) 표1 작용제와 Australia Group 목록의 **널리 알려진
작용제명**만 넣는다. 전구체 합성 경로·제법·구조는 **적지 않는다.**
차단 목록은 차단에만 쓴다.

생물작용제는 질환명 쪽에서 들어올 수 있어 따로 둔다. 다만
**연구 대상으로서의 감염병은 막지 않는다** — 탄저·두창 치료제 재창출은
정당한 연구다. 막는 것은 **작용제 자체를 개발 대상으로 삼는 질의**다.
"""

import re

# CWC 표1 작용제 · Australia Group 화학작용제 — **이름만.** 제법은 없다.
_CW_AGENTS = (
    "sarin", "soman", "tabun", "cyclosarin", "vx nerve", "novichok",
    "sulfur mustard", "sulphur mustard", "nitrogen mustard gas", "lewisite",
    "phosgene oxime", "tear gas agent", "chlorine gas weapon",
    "사린", "소만", "타분", "노비촉", "겨자가스", "루이사이트", "신경작용제",
)

# 생물작용제를 **무기화 맥락에서** 다루는 질의만 막는다.
#   "탄저 치료제"는 정당한 연구다. "탄저 무기화"는 아니다.
_BIO_AGENTS = ("anthrax", "botulinum toxin", "ricin", "smallpox", "variola",
               "탄저", "보툴리눔", "리신", "두창")
_WEAPON_CTX = re.compile(
    r"weapon|aerosoliz|militar|warfare|무기|살포|에어로졸화|대량살상", re.I)

_WS = re.compile(r"\s+")


def _norm(s):
    return _WS.sub(" ", (s or "")).strip().lower()


def screen(*texts):
    """통제 물질 질의인가. (차단여부, 사유) 를 돌려준다.

    **판단이 애매하면 통과시킨다.** 과잉 차단은 정당한 재창출 연구를
    막고, 그건 이 시스템의 존재 이유를 훼손한다. 명백한 것만 막는다.
    """
    hay = _norm(" ".join(str(t or "") for t in texts))
    if not hay:
        return False, ""
    for a in _CW_AGENTS:
        if a in hay:
            return True, "통제 물질(화학작용제) 질의 — CWC 표1 · Australia Group"
    for a in _BIO_AGENTS:
        if a in hay and _WEAPON_CTX.search(hay):
            return True, "생물작용제의 무기화 맥락 질의"
    return False, ""


class Blocked(Exception):
    """안전 게이트가 막았다. **조용히 빈 결과를 내지 않는다.**"""


def gate(st, log_path="safety_log.jsonl"):
    """파이프라인 최상단. 걸리면 기록하고 예외를 던진다.

    빈 결과를 돌려주지 않는 이유 — 그러면 호출부가 "근거가 없구나"로
    읽는다. **막은 것과 없는 것은 다르다**(결함 35에서 배운 것과 같다).
    """
    import json
    from datetime import datetime

    hits = []
    for c in st.candidates:
        bad, why = screen(c.name, c.drug, c.disease, c.query)
        if bad:
            hits.append({"후보": c.name, "사유": why})
    if not hits:
        return st

    rec = {"시각": datetime.now().isoformat(timespec="seconds"),
           "질의": st.query_title, "차단": hits}
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass                      # 기록 실패가 차단을 막으면 안 된다
    raise Blocked("안전 게이트가 %d건을 막았다: %s"
                  % (len(hits), hits[0]["사유"]))
