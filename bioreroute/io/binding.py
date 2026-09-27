# -*- coding: utf-8 -*-
"""결합 활성 조회 — **「직접 결합」 주장을 검증한다** (2026-09-01).

## 왜 만드나

09-01 에 라우터 실측 101건을 셌더니 —

    직접·병원체  13.9%  ┐
    직접·숙주    25.7%  ┘  합쳐 **39.6% 가 「직접 결합」을 주장**한다

그런데 **그 주장을 검증할 도구가 없었다.** 라우터가 *"이 약은 JAK1 에
직접 붙는다"* 고 하면 우리는 그 말을 그대로 받아 경로를 정한다.
**«반증 우선» 을 표방하는 시스템에서 자기 주장만 검증 안 하는 셈이다.**

## 왜 BindingDB 가 아니라 ChEMBL 인가

제안서 §3.1 이 BindingDB 를 적었고 `제안서_전수대조 §모순⑤` 가
*"적어 놓고 안 쓴다"* 로 판정했다. **새로 붙일 필요가 없다** —
`io/tox.small_molecule` 이 **이미 ChEMBL REST 를 쓰고 캐시한다**
(`CHEMBL::` 키). 결합 활성은 **같은 서버의 다른 엔드포인트**다.

    tox.py    /chembl/api/data/molecule/search   ← 이미 쓴다
    여기      /chembl/api/data/activity           ← 같은 곳

## 무엇을 판정하나 — **셋**

    강함    pChEMBL ≥ 7   (IC50 ≤ 100 nM)  → 「직접 결합」 주장 **지지**
    약함    pChEMBL < 5   (IC50 ≥ 10 µM)   → **경보**. 사람 농도에서 의문
    없음    활성 0건                        → **반증 신호**

`pChEMBL = -log10(몰농도)` 다. 6 이 1 µM, 9 가 1 nM 이다.

## ⚠ 이 도구가 **못 하는 것** — 먼저 적는다

* **부재는 부재의 증거가 아니다.** ChEMBL 에 없다고 결합을 안 하는 게
  아니다. 오래된 약·특허에만 있는 데이터는 안 실린다. 그래서 「없음」은
  **기각 사유가 아니라 신뢰도 강등 신호**로만 쓴다(결함 35 계열 —
  «조회 실패»와 «후보 없음»을 섞지 않는다).
* **표적 이름 매칭이 느슨하다.** 라우터가 내는 이름(`JAK1`)과 ChEMBL
  표적명이 다를 수 있다. 매칭 실패는 **「불명」이지 「없음」이 아니다.**
* **활성값의 어세이 맥락을 안 본다.** 세포 기반과 무세포가 섞인다.
* ⚠ **`limit = 200` 에서 잘린다.** ChEMBL 은 페이지네이션하는데 우리는
  첫 200건만 받는다. **인기 약은 활성이 수천 건**이라 그 뒤에 더 강한
  값이 있어도 못 본다 — 즉 `best_pchembl` 은 **하한**이다.
  「강함」 판정은 그래도 안전하지만(이미 강한 걸 봤으므로), **「경보」와
  「근거없음」은 표본 부족일 수 있다.** 표적 ID 로 거르면 대개 200 안에
  들지만, 9/7 에 84쌍을 돌릴 때 **`n` 이 200 에 붙는 쌍이 있는지**
  보고 있으면 늘려야 한다.

## 사용법

    py -m bioreroute.io.binding --probe metformin
        ← **응답 구조만 찍는다.** 파서를 쓰기 전에 실물을 본다(§5)
    py -m bioreroute.io.binding metformin --target AMPK
"""
import argparse
import json
import ssl
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import cache

UA = "Bio-ReRoute/1.0 (research; contact via github)"
TIMEOUT = 20
BASE = "https://www.ebi.ac.uk/chembl/api/data"

MOL = BASE + "/molecule/search?q=%s&format=json&limit=5"
ACT = (BASE + "/activity?molecule_chembl_id=%s"
       "&standard_type__in=IC50,Ki,Kd,EC50&format=json&limit=%d")
TGT = BASE + "/target/search?q=%s&format=json&limit=5"

# 판정 문턱 — **사전에 고정한다.** 결과를 보고 고치지 않는다(§3-2)
STRONG = 7.0        # pChEMBL ≥ 7  → IC50 ≤ 100 nM
WEAK = 5.0          # pChEMBL < 5  → IC50 ≥ 10 µM

_ctx = ssl.create_default_context()


def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _cached(key: str, url: str) -> Any:
    """캐시 우선. `tox.py` 와 같은 규약을 쓴다."""
    if cache.has(key):
        return cache.get(key)
    d = _get(url)
    cache.put(key, d)
    return d


def chembl_id(drug: str) -> Optional[str]:
    """약물명 → ChEMBL ID. 못 찾으면 None (**«없다»가 아니다**)."""
    n = (drug or "").strip()
    if not n:
        return None
    d = _cached("CHEMBLID::" + n.lower(), MOL % urllib.parse.quote(n))
    for m in (d or {}).get("molecules") or []:
        cid = m.get("molecule_chembl_id")
        if cid:
            return cid
    return None


def activities(cid: str, limit: int = 200) -> List[Dict[str, Any]]:
    """그 분자의 결합 활성 목록. **방어적으로 판다** — 키가 없으면 건너뛴다."""
    if not cid:
        return []
    d = _cached("CHEMBLACT::%s::%d" % (cid, limit), ACT % (cid, limit))
    return (d or {}).get("activities") or []


def target_ids(name: str) -> List[Tuple[str, str]]:
    """표적 이름 → ChEMBL target **후보 목록** `[(id, pref_name), …]`.

    ## ⚠ 09-01 · 두 번 틀렸다

    **첫 판** — 활성 레코드를 JSON 으로 덤프해 표적 이름을 문자열로
    찾았다. **활성 레코드에는 `target_chembl_id` 만 있고 이름이 없다.**

    **둘째 판** — 이름으로 검색해 **첫 결과 하나만** 썼다. 그러자
    `rifampin` 이 여전히 「근거없음」이었다. 원인이 둘이다 —
    · 라우터는 «DNA-**dependent** RNA polymerase» 라 하는데 ChEMBL 은
      «DNA-**directed** RNA polymerase» 다
    · 같은 이름의 표적이 **종(species)마다 따로** 있다. rifampin 은
      **결핵균** RpoB 를 치는데 검색 첫 결과는 사람 것일 수 있다
    → 첫 결과만 쓰면 **활성 0건 = 「근거없음」** 이 나오고, 그건
      *"결합 근거가 없다"* 가 아니라 *"내가 엉뚱한 표적을 봤다"* 다.

    **그래서 후보를 돌려주고 `verify` 가 순회한다.** 어느 표적을
    실제로 썼는지도 결과에 남긴다 — 안 남기면 이 실수가 조용해진다.
    """
    n = (name or "").strip()
    if not n:
        return []
    d = _cached("CHEMBLTGT::" + n.lower(), TGT % urllib.parse.quote(n))
    out = []
    for t in (d or {}).get("targets") or []:
        tid = t.get("target_chembl_id")
        if tid:
            out.append((tid, t.get("pref_name") or ""))
    return out


def target_id(name: str) -> Optional[str]:
    """후보 중 첫째. **채점에는 `target_ids` 를 쓴다**(위 ⚠)."""
    ids = target_ids(name)
    return ids[0][0] if ids else None


def _pchembl(a: Dict[str, Any]) -> Optional[float]:
    v = a.get("pchembl_value")
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def verify(drug: str, target: str = "", limit: int = 200) -> Dict[str, Any]:
    """**「직접 결합」 주장을 검증한다.**

    `target` 을 주면 표적명이 어세이·표적 칸에 나오는 활성만 센다.
    비우면 그 약의 결합 활성 전체를 본다.

    반환 `판정` 은 넷 —
        `지지` · `경보` · `근거없음` · `조회불가`
    **`조회불가` 와 `근거없음` 을 절대 섞지 않는다**(결함 35).
    """
    out: Dict[str, Any] = {"drug": drug, "target": target,
                           "chembl_id": None, "n": 0, "n_pchembl": 0,
                           "best_pchembl": None, "median_pchembl": None,
                           "판정": "조회불가", "왜": "", "오류": None}
    try:
        cid = chembl_id(drug)
    except Exception as e:                      # 네트워크·서버 오류
        out["오류"] = "%s: %s" % (type(e).__name__, e)
        out["왜"] = "ChEMBL 조회 실패 — **근거 없음이 아니다**"
        return out
    if not cid:
        out["왜"] = "ChEMBL 에서 약물을 못 찾았다 — **결합 없음이 아니다**"
        return out
    out["chembl_id"] = cid
    try:
        acts = activities(cid, limit)
    except Exception as e:
        out["오류"] = "%s: %s" % (type(e).__name__, e)
        out["왜"] = "활성 조회 실패 — **근거 없음이 아니다**"
        return out

    if target:
        # ⚠ 09-01 · 표적은 이름이 아니라 **ID 로** 거르고, **후보를
        #    순회한다**. 첫 결과만 쓰면 종(species)이 어긋난다 —
        #    위 `target_ids` 의 rifampin 사례.
        try:
            cands = target_ids(target)
        except Exception as e:
            out["오류"] = "%s: %s" % (type(e).__name__, e)
            out["왜"] = "표적 조회 실패 — **근거 없음이 아니다**"
            return out
        if not cands:
            out["왜"] = ("표적 «%s» 를 ChEMBL 에서 못 찾았다 — "
                         "**결합 없음이 아니라 매칭 실패다**" % target)
            return out                      # 판정은 `조회불가` 로 남는다
        out["표적후보"] = ["%s(%s)" % (p or "?", i) for i, p in cands]
        best, used = [], None
        for tid, pname in cands:
            sub = [a for a in acts if a.get("target_chembl_id") == tid]
            if not sub:
                continue
            hi = max([v for v in (_pchembl(a) for a in sub)
                      if v is not None] or [-1.0])
            cur = max([v for v in (_pchembl(a) for a in best)
                       if v is not None] or [-1.0]) if best else -2.0
            if hi > cur:
                best, used = sub, (tid, pname)
        if used:
            out["target_id"], out["target_name"] = used
        else:
            out["왜"] = ("표적 후보 %d개 전부 활성 0건 — "
                         "**이 약이 그 표적에 붙는 자료가 ChEMBL 에 "
                         "없다는 뜻이지, 안 붙는다는 뜻이 아니다**"
                         % len(cands))
        acts = best
    else:
        # 표적이 없으면 **그 약의 모든 활성 중 최고**를 본다. 이것은
        # «이 약이 무언가에 붙는가» 이지 «주장한 표적에 붙는가» 가
        # 아니다. 채점에 쓰면 안 된다 — `bench/bindcheck` 참조.
        out["범위"] = "표적 미지정 — 전체 활성"
    out["n"] = len(acts)
    vals = sorted(v for v in (_pchembl(a) for a in acts) if v is not None)
    out["n_pchembl"] = len(vals)
    if not vals:
        out["판정"] = "근거없음"
        out["왜"] = ("활성 %d건 중 pChEMBL 이 붙은 것 0건 — "
                     "**신뢰도 강등 신호이지 기각 사유가 아니다**" % len(acts))
        return out
    best = vals[-1]
    mid = vals[len(vals) // 2]
    out["best_pchembl"] = best
    out["median_pchembl"] = mid
    if best >= STRONG:
        out["판정"] = "지지"
        out["왜"] = "pChEMBL 최고 %.1f (≥%.0f) — IC50 100 nM 이하급" % (best, STRONG)
    elif best < WEAK:
        out["판정"] = "경보"
        out["왜"] = ("pChEMBL 최고 %.1f (<%.0f) — **10 µM 이상.** "
                     "사람 혈중 농도에서 그 기전이 작동하는지 의문" % (best, WEAK))
    else:
        out["판정"] = "지지"
        out["왜"] = "pChEMBL 최고 %.1f — 중간 강도" % best
    return out


def probe(drug: str) -> Dict[str, Any]:
    """⚠ **파서를 쓰기 전에 실물 응답의 키를 본다** (`CLAUDE.md §5`).

    09-01 작성 시 샌드박스에서 ChEMBL 에 붙지 못했다(rate limit).
    **응답 구조를 추측으로 적지 않으려고** 이 모드를 둔다 — 처음
    돌리는 사람이 **키가 실제로 무엇인지 눈으로 보고** 파서를 맞춘다.
    """
    out: Dict[str, Any] = {"drug": drug}
    try:
        d = _get(MOL % urllib.parse.quote(drug))
        out["molecule_search_keys"] = list(d)[:10]
        ms = d.get("molecules") or []
        out["molecules_n"] = len(ms)
        if ms:
            out["molecule_keys"] = sorted(ms[0])[:20]
            cid = ms[0].get("molecule_chembl_id")
            out["chembl_id"] = cid
            if cid:
                a = _get(ACT % (cid, 3))
                out["activity_keys"] = list(a)[:10]
                acts = a.get("activities") or []
                out["activities_n"] = len(acts)
                if acts:
                    out["activity_row_keys"] = sorted(acts[0])[:30]
                    out["sample"] = {k: acts[0].get(k) for k in
                                     ("standard_type", "standard_value",
                                      "standard_units", "pchembl_value",
                                      "target_chembl_id")}
    except Exception as e:
        out["오류"] = "%s: %s" % (type(e).__name__, e)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="ChEMBL 결합 활성으로 「직접 결합」 주장을 검증한다")
    ap.add_argument("drug")
    ap.add_argument("--target", default="")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--probe", action="store_true",
                    help="응답 구조만 찍는다 — **파서를 맞추기 전에 실물을 본다**")
    a = ap.parse_args(argv)
    r = probe(a.drug) if a.probe else verify(a.drug, a.target, a.limit)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
