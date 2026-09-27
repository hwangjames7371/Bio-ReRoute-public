# -*- coding: utf-8 -*-
"""`zerocheck` 가 **가짜 0** 으로 확정한 캐시 항목만 걷어낸다 — 결함 327.

    py -m bioreroute.bench.zeropurge 영점확인_0924.json            무엇을 지울지 보여 주기만
    py -m bioreroute.bench.zeropurge 영점확인_0924.json --apply    백업 뜨고 실제로 지운다

## 왜 따로 있나

`zerocheck` 는 **캐시에 쓰지 않는다**(시험 `[175]⑥`) — 재는 도구가 재는 대상을
바꾸면 안 된다. 지우는 일은 여기서만 한다. 규약은 `clean_cache.py` 와 같다 —

- 기본은 **미적용**이다. `--apply` 없이는 아무것도 안 바꾼다
- 적용 전에 **백업을 뜨고 경로를 찍는다**
- **가짜 0 으로 확정된 질의의 «0건» 항목만** 지운다 — 원문 질의(F0)와
  `SEARCH::n::질의::-`(전 기간 팩트체크 검색). 시점 차단(연도가 붙은) 검색은
  **안 건드린다** — 그때는 진짜로 0 이었을 수 있다

## ⚠ 실험 캐시와 섞지 않는다

홀드아웃 비교(sol · luna)의 입력 캐시는 `pubmed_cache.json.bak_20260923_luna전`
으로 따로 남아 있다(sha256 `dccefcba…`). 여기서 지우는 것은 **앞으로 쓸 캐시**다.
**지운 뒤 홀드아웃을 다시 돌려 수를 바꾸지 않는다**(`CLAUDE.md §3-2`).
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

CACHE = "pubmed_cache.json"


def _zero(v):
    return isinstance(v, dict) and not v.get("error") and (v.get("count") or 0) == 0


def plan(cache, report):
    """지울 키 목록. 가짜 0 으로 확정된(그때 이미 논문이 있던) 질의의 0건 항목만."""
    fake = {q for q, v in (report.get("질의") or {}).items() if (v.get("그때") or 0) > 0}
    keys = [q for q in sorted(fake) if _zero(cache.get(q))]
    for k in cache:
        if not k.startswith("SEARCH::"):
            continue
        try:
            _, _n, rest = k.split("::", 2)
            q, year = rest.rsplit("::", 1)
        except ValueError:
            continue
        if year == "-" and q in fake and _zero(cache[k]):
            keys.append(k)
    return sorted(set(keys)), sorted(fake)


def main(argv=None):
    ap = argparse.ArgumentParser(description="가짜 0 으로 확정된 캐시 항목만 걷어낸다 (결함 327)")
    ap.add_argument("report", help="`zerocheck --out` 이 쓴 JSON")
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--apply", action="store_true", help="실제로 지운다 (백업 먼저)")
    a = ap.parse_args(argv)
    with open(a.report, encoding="utf-8") as f:
        rep = json.load(f)
    with open(a.cache, encoding="utf-8") as f:
        cache = json.load(f)
    keys, fake = plan(cache, rep)
    print("=" * 72)
    print("가짜 0 걷어내기 — %s%s" % (a.cache, "" if a.apply else "   [미적용 · 보여 주기만]"))
    print("=" * 72)
    print("  ⚠ 다른 bioreroute 프로세스(화면·벤치)가 떠 있으면 먼저 닫아라 — 그쪽이 저장할 때")
    print("    메모리의 옛 0 을 디스크와 **병합해 되살린다**(결함 322 방어의 부작용)")
    print("  가짜 0 으로 확정된 질의 %d · 지울 캐시 항목 %d" % (len(fake), len(keys)))
    for k in keys:
        print("    - %s" % k[:96])
    if not a.apply or not keys:
        if keys:
            print("\n  지우려면 같은 줄 끝에 --apply")
        return 0
    bak = "%s.bak_%s_가짜0" % (a.cache, datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(a.cache, bak)
    print("\n  백업 → %s" % bak)
    n0 = len(cache)
    for k in keys:
        cache.pop(k, None)
    tmp = a.cache + ".tmp_zeropurge"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, a.cache)
    with open(a.cache, encoding="utf-8") as f:
        n1 = len(json.load(f))
    ok = (n0 - n1) == len(keys)
    print("  항목 %d → %d (−%d) %s" % (n0, n1, n0 - n1, "✅" if ok else "🔴 수가 안 맞는다 — 백업으로 되돌려라"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
