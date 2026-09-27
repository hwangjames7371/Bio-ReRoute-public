# -*- coding: utf-8 -*-
"""부작용 자료원 — openFDA FAERS · SIDER (제안서 §1.2 역발상)

  > 역발상은 부작용 데이터베이스(SIDER·FAERS)에서 거꾸로 새 적응증을
  > 찾는 방식이다(미녹시딜·실데나필 형).

## 왜 **원시 건수를 쓰면 안 되는가**

FAERS에서 어떤 부작용으로 신고가 많은 약을 세면, 나오는 것은
*그 부작용을 특이하게 일으키는 약*이 아니라 **그냥 많이 처방되는 약**이다.
아스피린과 메트포르민이 거의 모든 부작용 상위에 뜬다.

그래서 약물감시의 표준 지표인 **PRR(비례보고비, Proportional Reporting
Ratio)** 을 쓴다.

```
            a / (a+b)        a = 그 약 · 그 부작용        b = 그 약 · 다른 부작용
    PRR = ─────────────      c = 다른 약 · 그 부작용      d = 나머지 전부
            c / (c+d)
```

PRR ≥ 2 이고 a ≥ 3 이면 신호로 본다(EMA·MHRA 관행). **우리가 정한 값이
아니다** — 자료를 보고 고르면 사후 조정이다.

## 이 모듈이 **하지 않는** 것

- **부작용을 LLM에게 물어보지 않는다.** 그러면 역발상이 정방향과 같은
  자료원을 쓰게 되고, "정방향이 놓치는 것을 찾는다"는 주장이 **검증
  불가능해진다.** 자료원이 다른 것이 역발상의 전부다
- 자료가 없으면 **없다고 말하고 멈춘다.** 추정으로 채우지 않는다
- FAERS는 **자발보고**다. 인과가 아니라 신고 편향이 섞인 상관이다.
  반환값에 그 경고를 문자열로 같이 싣는다
"""

from .. import config as _config

import json
import os
import ssl
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from . import cache

OPENFDA = "https://api.fda.gov/drug/event.json"
TIMEOUT = 30
UA = "Bio-ReRoute"
_ctx = ssl.create_default_context()

# 약물감시 관행값. 자료를 보고 고른 값이 아니다.
PRR_MIN = 2.0
COUNT_MIN = 3

CAVEAT = ("FAERS는 자발보고다. PRR은 신고 편향이 섞인 상관이며 인과가 아니다. "
          "분모(처방량)를 모르므로 발생률로 읽으면 안 된다.")

# SIDER 로컬 파일을 쓰려면 이 경로에 둔다(내려받아야 한다).
SIDER_PATH = os.environ.get("BIOREROUTE_SIDER", "sider_meddra_all_se.tsv")


def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
        return json.loads(r.read().decode("utf-8"))


def _q(**kw) -> str:
    return OPENFDA + "?" + urllib.parse.urlencode(kw)


# SIDER 4.1(2015-10-21) 공식 배포본의 실측값. **줄 수를 안 세면 잘린
# 파일이 「있다」로 읽힌다** — DRKG 에서 정확히 그렇게 당했다(결함 116).
#   08-12 실측: meddra_all_se.tsv = 309,849줄 · 6열 · 고유 약물 1,430
#   (사이트 통계와 일치: 약물 1,430 · 부작용 5,868)
SIDER_ROWS = 309_849
_SIDER_MIN_ROWS = 250_000
_SIDER_COLS = 6


def sider_state(path: Optional[str] = None) -> Dict[str, Any]:
    """SIDER 파일이 **온전한가.** 존재만 보지 않는다.

    ## 왜 있는 검사인가

    DRKG 에서 압축 해제가 중간에 끊겨 167만 줄(정상 587만)짜리가 남았는데
    `os.path.exists` 만 보던 코드가 **`ok=True`** 를 냈다(결함 116).
    자료의 3/4 가 없는 채로 «연결이 없다» 고 답할 뻔했다.

    **「없다」와 「잘렸다」와 「형식이 다르다」를 각각 다른 문구로 낸다.**
    셋을 뭉치면 사람이 원인을 못 찾는다.

    ## 이 파일에서 특히 조심할 것

    받는 파일이 `meddra_all_se.tsv.gz` 인데 **순수 gzip 이지 tar 가 아니다.**
    `tar -xzf` 로 풀면 `Unrecognized archive format` 이 난다(08-12 실측).
    그래서 **압축 파일을 그대로 둔 채 이름만 바꾼 경우**도 잡아야 한다 —
    앞 두 바이트가 `1f 8b` 면 안 푼 것이다.
    """
    p = path or SIDER_PATH
    out: Dict[str, Any] = {"ok": False, "path": p, "rows": None,
                           "size_mb": None, "error": None}
    if not os.path.exists(p):
        out["error"] = ("**없다** — SIDER 를 받아라: "
                        "http://sideeffects.embl.de/media/download/"
                        "meddra_all_se.tsv.gz (2.3MB) 를 풀어 `%s` 로 둔다" % p)
        return out
    n = os.path.getsize(p)
    out["size_mb"] = round(n / 1e6, 1)
    try:
        with open(p, "rb") as fh:
            head = fh.read(2)
    except Exception as e:
        out["error"] = "읽기 실패: %s" % e
        return out
    if head == b"\x1f\x8b":
        out["error"] = ("**아직 압축 파일이다** — 이름만 바꿨다. gzip 을 풀어라: "
                        "`py -c \"import gzip,shutil; shutil.copyfileobj("
                        "gzip.open('sider.tsv.gz','rb'), open('%s','wb'))\"`. "
                        "**`tar -xzf` 는 안 된다 — tar 가 아니라 순수 gzip 이다**" % p)
        return out
    rows, cols = 0, None
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if cols is None:
                    cols = line.count("\t") + 1
                rows += 1
    except Exception as e:
        out["error"] = "줄 세기 실패: %s" % e
        return out
    out["rows"], out["cols"] = rows, cols
    if cols != _SIDER_COLS:
        out["error"] = ("**형식이 다르다** — 열이 %s개다(정상 %d). "
                        "`meddra_all_se.tsv` 가 맞는지 봐라 "
                        "(`meddra_all_label_se` 등 다른 파일일 수 있다)"
                        % (cols, _SIDER_COLS))
        return out
    # **줄 수만 문턱으로 쓴다. 크기는 참고값이다.**
    #
    #   초판은 `size_mb < 15` 도 같이 걸었는데, 시험에서 **온전한 파일을
    #   막았다** — 줄이 짧으면 줄 수가 맞아도 크기가 안 찬다. 잘리면 줄
    #   수가 먼저 줄어드니 크기 문턱은 **아무것도 더 못 잡으면서 오차단만
    #   만든다.** 이 저장소는 과잉 차단도 실패로 센다(`core/safety.py` 와
    #   같은 규칙).
    if rows < _SIDER_MIN_ROWS:
        out["error"] = ("**파일이 잘렸다** — %d줄 (%s MB). 온전한 판은 약 %d줄이다. "
                        "압축을 다시 풀어라" % (rows, out["size_mb"], SIDER_ROWS))
        return out
    out["ok"] = True
    return out


def available() -> Dict[str, Any]:
    """자료원이 살아 있는가. **LLM 비용 0.**

    `netcheck` 와 같은 규칙 — 못 쓰면 못 쓴다고 말한다.
    """
    _sd = sider_state()
    out = {"faers": False, "sider": _sd["ok"], "sider_state": _sd,
           "sider_path": SIDER_PATH, "error": None}
    try:
        d = _get(_q(limit=1))
        out["faers"] = bool((d.get("meta") or {}).get("results"))
        out["total"] = ((d.get("meta") or {}).get("results") or {}).get("total")
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    return out


def _total(search: Optional[str] = None) -> Optional[int]:
    """총 신고 건수. **실패하면 None 이다. 0 이 아니다.**

    ## 결함 58 — 여기서 결함 35·37 을 그대로 재발시켰다

    처음에 이렇게 썼다.

    ```python
    except Exception:
        return cache.put(key, 0)     # "404 = 0건이니까"
    ```

    `except Exception` 이 **타임아웃·DNS 실패·500·JSON 파싱 오류를 전부**
    0으로 만들고, 게다가 **캐시에 영구 저장**한다. 실측 결과 —

    ```
    사건 총계 조회만 타임아웃  →  C = 0
      c = max(C - a, 0) = 0   →  prr = inf   →  signal = True
      error 는 None
      정렬이 -prr 이므로 그 약이 **1위**로 올라간다
    ```

    **일시 장애 하나가 약 하나를 역발상 후보 1위로 만든다.**
    결함 35(조회 실패를 0으로 셈)와 결함 37(일시 장애를 캐시에 영구화)을
    **둘 다** 같은 세 줄에서 재발시켰고, 그 둘을 문서에 적은 날 썼다.

    그래서 지금은 —
      · **404 이고 실제로 0건일 때만** 0 을 돌려준다
      · 나머지 실패는 **None** 이고 **캐시하지 않는다**
    """
    import urllib.error
    kw = {"limit": 1}
    if search:
        kw["search"] = search
    key = "FAERS::TOTAL::" + (search or "*")
    if cache.has(key):
        return cache.get(key)
    try:
        d = _get(_q(**kw))
        n = ((d.get("meta") or {}).get("results") or {}).get("total")
        return cache.put(key, int(n)) if n is not None else None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # openFDA 는 **결과 없음**을 404로 준다. 이것만 진짜 0이다.
            return cache.put(key, 0)
        return None                    # 5xx·429 — 실패다. 캐시 안 한다
    except Exception:
        return None                    # 타임아웃·DNS·파싱 — 전부 실패다


def drugs_for_event(term: str, limit: int = 25) -> Dict[str, Any]:
    """부작용 용어 → 그 부작용을 신고한 약물 상위 + PRR.

    돌려주는 것은 `{"rows": [...], "error": ...}` 이고, 조회가 실패하면
    **빈 rows 가 아니라 error 가 찬다.** 둘을 섞으면 네트워크 장애가
    "그런 약이 없다"로 읽힌다(결함 35).
    """
    t = (term or "").strip().upper()
    out = {"term": t, "rows": [], "n_total": None, "n_event": None,
           "caveat": CAVEAT, "error": None}
    if not t:
        out["error"] = "부작용 용어 없음"
        return out
    key = "FAERS::EV::%s::%d" % (t, limit)
    if cache.has(key):
        return cache.get(key)

    ev = 'patient.reaction.reactionmeddrapt:"%s"' % t
    try:
        N = _total()
        C = _total(ev)
        # **둘 다 따로 본다.** 예전엔 `not N or C is None` 이라 C=0(실패)이
        # 통과했다 — 결함 58. 이제 None 이 곧 실패다.
        if N is None or C is None:
            out["error"] = ("총계 조회 실패 (전체=%s · 사건=%s) — "
                            "**0건이 아니라 조회가 안 됐다**" % (N, C))
            return out                 # 실패는 캐시하지 않는다 (결함 37)
        if N <= 0:
            out["error"] = "전체 신고가 0건 — 자료원이 비었다"
            return out
        out["n_total"], out["n_event"] = N, C
        d = _get(_q(search=ev, count="patient.drug.medicinalproduct.exact",
                    limit=limit))
        skipped = []
        for r in (d.get("results") or []):
            drug, a = r.get("term"), int(r.get("count") or 0)
            ab = _total('patient.drug.medicinalproduct:"%s"' % drug)
            if ab is None:
                skipped.append(drug)   # 조회 실패 — **없는 것으로 치지 않는다**
                continue
            if ab <= 0 or a < 1:
                continue
            c = max(C - a, 0)
            cd = max(N - ab, 1)
            if c <= 0:
                # 분모가 0이면 PRR 은 정의되지 않는다. 예전엔 여기서
                # `inf` 를 넣었고 그게 정렬 1위로 올라갔다 — 결함 58.
                # **무한대는 신호가 아니라 계산 불가다.**
                out["rows"].append({
                    "drug": drug, "a": a, "n_drug": ab, "prr": None,
                    "signal": False,
                    "why": "PRR 분모 0 — 총계가 서로 모순이다. 계산 불가"})
                continue
            prr = (a / ab) / (c / cd)
            out["rows"].append({
                "drug": drug, "a": a, "n_drug": ab, "prr": round(prr, 2),
                "signal": bool(a >= COUNT_MIN and prr >= PRR_MIN),
            })
        if skipped:
            out["skipped"] = skipped
            out["note"] = ("약물 총계 조회 실패 %d건은 **제외**했다 — "
                           "0으로 세지 않는다: %s" % (len(skipped), ", ".join(skipped[:5])))
        out["rows"].sort(key=lambda r: -(r["prr"] if r["prr"] is not None else -1))
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    return cache.put(key, out)


SIDER_NAMES = os.environ.get("BIOREROUTE_SIDER_NAMES", "drug_names.tsv")
_NAMES: Dict[str, str] = {}

# **PRR 은 SIDER 에서 정의되지 않는다** — 자발보고 «건수» 가 없기 때문이다.
# 그래서 규칙이 다르고, 그 규칙은 `사전명세_역발상_SIDER.md`(`7b906515…`)에
# **결과를 보기 전에** 박아 뒀다. 여기서 바꾸면 그 봉인이 무의미해진다.
SIDER_RULE = ("SIDER 는 라벨 표기 자료라 PRR 이 정의되지 않는다. "
              "**질환 용어 중 몇 개를 라벨에 적었나(원시 공유 수)** 로 순위를 낸다. "
              "정규화는 부지표다 — 나누면 «라벨을 적게 쓴 약» 이 1위가 되고 "
              "그건 생물학이 아니라 라벨 작성 성실도다(결함 118 과 같은 함정). "
              "명세 `사전명세_역발상_SIDER.md` sha256 `7b906515…`")


def sider_names(path: Optional[str] = None) -> Dict[str, str]:
    """STITCH CID → 약물 이름. **없으면 빈 dict 이고 조용히 안 넘어간다.**"""
    global _NAMES
    p = path or SIDER_NAMES
    if _NAMES:
        return _NAMES
    if not os.path.exists(p):
        return {}
    m: Dict[str, str] = {}
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[0]:
                m[parts[0]] = parts[1].strip()
    _NAMES = m
    return m


def sider_label_sizes(path: Optional[str] = None) -> Dict[str, int]:
    """약마다 라벨에 적힌 부작용 수 `|SE(약)|`. **진단 지표용이다.**

    명세 §3 — 상위 후보의 이 값이 전체 중앙값의 **3배를 넘으면** 순위가
    «라벨 길이» 를 재고 있는 것이므로 **이겼더라도 성능으로 팔지 않는다.**
    """
    p = path or SIDER_PATH
    if not os.path.exists(p):
        return {}
    seen: Dict[str, set] = {}
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 6 and parts[0]:
                seen.setdefault(parts[0], set()).add(parts[2])
    return {k: len(v) for k, v in seen.items()}


def sider_drugs_for_event(term: str) -> Dict[str, Any]:
    """SIDER 라벨에 이 부작용을 적은 약. **PRR 이 아니라 표기 여부다.**

    ## 08-12 — 이 함수는 «구현된 것처럼 보이는» 상태였다 (결함 128)

    함수가 있고 배선도 돼 있고 dict 도 돌려줬다. **그런데 계약이 달랐다** —
    돌려준 행이 `{"drug_stitch", "n"}` 인데 `agents/reverse.propose` 는
    `row["signal"]` · `row["drug"]` · `row["prr"]` · `row["a"]` 를 읽는다.

        for row in r.get("rows", []):
            if not row.get("signal"):
                continue          # ← **865행이 전부 여기서 걸렸다**

    **후보 0건인데 `error` 는 `None`** 이었다 — 조용한 0건이고 결함 35와
    같은 고장이다. 승우가 SIDER 를 받아 돌려서 드러났다. 빈 팔로 판정을
    거부하는 가드(결함 123 수정)가 없었으면 *"SIDER 0% — 대조군에 크게
    졌다"* 는 **완전히 틀린 판정문**이 나갔다.

    ## 지금은 계약을 맞춘다. **다만 `prr` 자리에 가짜를 넣지 않는다**

    `signal` 은 «질환 용어를 라벨에 적었나» 이고 `a` 는 그 표기 건수다.
    `prr` 은 **`None` 으로 둔다** — 정의되지 않는 양에 숫자를 넣으면
    아래 단계가 그걸 PRR 로 읽는다. **없는 것은 없다고 둔다.**
    """
    out = {"term": term, "rows": [], "error": None, "source": SIDER_PATH,
           "rule": SIDER_RULE}
    st = sider_state()
    if not st["ok"]:
        out["error"] = st["error"]
        return out
    names = sider_names()
    if not names:
        out["error"] = ("**약물 이름 파일이 없다**: %s — SIDER 는 STITCH CID 만 "
                        "담고 있어 이름을 못 붙인다. "
                        "http://sideeffects.embl.de/media/download/drug_names.tsv "
                        "(34KB) 를 받아라" % SIDER_NAMES)
        return out
    raw = _sider_raw_counts(term)
    if raw.get("error"):
        out["error"] = raw["error"]
        return out
    rows = []
    for r in raw["rows"]:
        nm = names.get(r["drug_stitch"])
        if not nm:
            continue
        rows.append({"drug": nm, "stitch": r["drug_stitch"],
                     "a": r["n"], "prr": None,      # **정의되지 않는다**
                     "signal": True})               # 라벨에 적혔으면 신호다
    out["rows"] = rows
    if not rows:
        out["error"] = "SIDER 에 그 용어로 적힌 약이 없다 (파일은 온전하다)"
    return out


def _sider_raw_counts(term: str) -> Dict[str, Any]:
    """SIDER 원자료 조회 — **STITCH CID 와 라벨 건수만.** PRR 이 아니다.

    `sider_drugs_for_event` 가 못 쓴다고 막고 있으므로, 원자료를 직접
    보고 싶을 때만 쓴다. **판정 경로에 꽂지 마라** — 그래서 이름이
    밑줄로 시작한다.
    """
    out = {"term": term, "rows": [], "error": None, "source": SIDER_PATH}
    if not os.path.exists(SIDER_PATH):
        out["error"] = ("SIDER 파일 없음: %s — 내려받아 두거나 FAERS를 써라"
                        % SIDER_PATH)
        return out
    t = (term or "").strip().lower()
    seen = {}
    with open(SIDER_PATH, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) < 6 or t not in p[-1].lower():
                continue
            seen[p[0]] = seen.get(p[0], 0) + 1
    out["rows"] = [{"drug_stitch": k, "n": v} for k, v in
                   sorted(seen.items(), key=lambda kv: -kv[1])]
    if not out["rows"]:
        out["error"] = "SIDER 0건 (파일은 있다)"
    return out
