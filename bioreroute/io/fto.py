# -*- coding: utf-8 -*-
"""FTO 특허 자유도 (제안서 §1.1 · §3.3-8)

  > 상업화·규제 간극: **타사 물질 특허가 살아 있으면 개발 가치가 없다**
  > (특허 자유도, FTO: Freedom to Operate).

## 이 게이트는 **판정에 들어가지 않는다** — 구조로 막는다

특허는 가설을 **틀리게 만들지 않는다.** 물질특허가 살아 있어도 그 약이
그 병에 듣는다는 명제의 참거짓은 그대로다. 특허가 바꾸는 것은
*개발할 가치가 있는가* 이지 *맞는가* 가 아니다.

이 시스템의 판정 축은 **반증**이다. 상업 판단을 로그오즈에 섞으면
`기각` 이 두 가지 뜻을 갖게 되고, 그러면 특이도라는 지표 자체가 무의미해진다.
S1 pLDDT를 결합력으로 환산하지 않는 것과 **같은 규율**이다.

그래서 —

  · 반환값에 `weight` · `score` 를 두지 않는다
  · 라벨은 `개발가능 | 특허생존 | 확인불가` 셋이다
  · `gate_*` 함수로 만들지 않는다. 파이프라인에 못 꽂도록 **아예 게이트가
    아니다.** 주석으로 "쓰지 마세요"라고 쓰면 언젠가 쓴다

## ⚠ 2026-03-20 — **이 API 는 중단됐다** (결함 95)

08-10에 승우가 키를 신청하려다 확인했다. 신청 페이지
`patentsview.org/apis/keyrequest` 가 **ODP 전환 안내로 넘어간다.**
USPTO 자기 공지(2026-03-18 게시 · 06-04 갱신)가 이렇게 적었다 —

  > As part of the transition to ODP, some PatentsView functions —
  > **including search, APIs**, visualizations, and support services —
  > **will pause temporarily starting March 20.**

**다섯 달 전에 멈췄고 우리는 오늘 알았다.** 그런데 계획서에는
*"특허 API 키 신청 — 5분. 리드타임을 우리가 통제 못 한다"* 가
할 일로 적혀 있었다. 리드타임이 문제가 아니라 **신청할 곳이 없었다.**

이 모듈은 그래도 **정직하게 실패한다** — 키가 없으면 `확인불가` 를 내고
*"확인불가는 개발가능이 아니다"* 를 같이 싣는다. 설계가 막아 준 것이지
우리가 알아서 막은 게 아니다. **알았기 때문에 안 틀린 게 아니라
몰랐는데도 안 틀렸다.**

## 자료원과 그 한계

`PatentsView`(USPTO 공개 API)로 **미국 등록특허 제목·초록**을 찾는다.

**이건 진짜 FTO 분석이 아니다.** 진짜는 청구항(claim)을 읽어 침해 여부를
따지는 법률 업무이고, 제안서도 그걸 로드맵(`용도특허 청구항 NLP`)에 뒀다.
여기서 하는 것은 **"살아 있을 법한 물질특허가 보이는가"** 라는 조기 신호뿐이고,
반환 문자열에 그 한계를 같이 싣는다.

미국만 본다. EP·JP·KR 은 안 본다. 그것도 적는다.
"""

from .. import config as _config

import datetime
import json
import os
import ssl
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import cache

TIMEOUT = 30
UA = "Bio-ReRoute"
PV = "https://search.patentsview.org/api/v1/patent/"
_ctx = ssl.create_default_context()

# 미국 물질특허 존속기간은 출원일로부터 20년이다. 등록일 기준으로 거칠게
# 20년을 잡는다 — **존속기간 연장(PTE)·조정(PTA)을 반영하지 않는다.**
TERM_YEARS = 20

LIMITS = ("미국 등록특허의 제목·초록만 본다. 청구항을 읽지 않으므로 "
          "**법률적 FTO 분석이 아니다.** EP·JP·KR 미포함. "
          "존속기간 연장(PTE/PTA) 미반영. 조기 신호로만 써라.")


def _get(url: str, key: Optional[str] = None) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if key:
        req.add_header("X-Api-Key", key)
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
        return json.loads(r.read().decode("utf-8"))


# ── SureChEMBL 벌크 (2026-08-12 추가) ────────────────────────────────
#
# 제안서 §3.3-8 원문이 **「FTO 특허 (SureChEMBL·USPTO)」** 이고 SureChEMBL
# 이 먼저다. PatentsView 는 죽었지만(결함 95) **SureChEMBL 은 살아 있고
# 키도 국적 제한도 없다** — EBI 가 FTP 로 연다.
#
#   https://ftp.ebi.ac.uk/pub/databases/chembl/SureChEMBL/bulk_data/latest/
#     compounds.parquet            3.9 G   InChIKey → compound_id
#     patent_compound_map.parquet  4.6 G   compound_id → patent_id (+ field_id)
#     patents.parquet              5.5 G   patent_id → 특허번호·공개일·출원인
#
# **통째로 14 GB 다. 배포본에 넣지 않는다.** 로컬에서 갈아 우리 약
# 목록만 담은 작은 색인(`fto_index.json`)을 만들고 배포본은 그것만 읽는다.
# 그래서 `pyarrow` 는 **로컬 전용**이고 `requirements.txt` 에 안 들어간다.
#
# ## 이 자료로 **못 하는 것**을 먼저 적는다
#
#   · 자유실시 판단을 **안 한다.** 그건 변리사의 일이다
#   · 청구항 해석을 **안 한다** (제안서가 「용도특허 청구항 NLP」를 스스로
#     로드맵으로 미뤄 뒀다)
#   · SureChEMBL 은 **특허에 그 화합물이 나오는가**를 담을 뿐,
#     **그 특허가 살아 있는가(존속기간·포기·무효)** 는 담지 않는다
#
# 그래서 라벨을 `개발가능` 으로 올리지 않는다. 낼 수 있는 것은
# **「관련 특허 N건이 검색됨 · 자유실시 여부는 판단하지 않음」** 뿐이다.
SURECHEMBL_DIR = "https://ftp.ebi.ac.uk/pub/databases/chembl/SureChEMBL/bulk_data/latest/"
FTO_INDEX = "fto_index.json"
# ── 08-12 **실측으로 고쳤다** ─────────────────────────────────
#   내가 «1,700만» 이라 적어 뒀는데 실제로 받아 세니 **30,990,818** 이다.
#   근거 없이 적은 수였다(결함 136 곁가지). 하한도 같이 올린다 —
#   1,000만은 **3분의 1이 잘려도 통과**하는 하한이라 방어가 아니었다.
SC_ROWS_20260804 = 30_990_818    # 2026-08-04 판 · 꼬리 메타데이터에서 실측
SC_COLS = ("id", "smiles", "inchi", "inchi_key", "mol_weight")
_SC_MIN_ROWS = 25_000_000


def _save_index(new: Dict[str, Any], path: str) -> None:
    """색인을 쓴다. **기존 결과를 지우지 않는다** (결함 145).

    ## 실제로 잃었다

    08-12 23:15, `cid_map` 을 넣으려고 `py -m bioreroute.io.fto` 를 다시
    돌렸더니 **③(map) 결과가 통째로 사라졌다.** `--map` 없이 돌리면
    `build_index` 가 ②까지만 담은 dict 를 **같은 경로에 그대로 덮어쓴다.**
    복구하려면 4.98 GB · 15억 행을 다시 훑어야 한다.

    `CLAUDE.md §3-3` 이 *"결과 파일을 확인 없이 덮어쓰지 마라 (`--out`
    기본값 주의)"* 라고 **정확히 이 사고를 적어 뒀다.** 규칙을 읽고도
    당했으므로 **규칙이 아니라 구조로 막는다.**

      · 기존 파일의 키 중 **이번에 안 만든 것은 그대로 둔다**
      · 덮어쓸 때 `.bak` 을 남긴다
    """
    old: Dict[str, Any] = {}
    if os.path.exists(path):
        try:
            old = json.load(open(path, encoding="utf-8"))
        except Exception:
            old = {}
    kept = [k for k in old if k not in new]
    merged = dict(old)
    merged.update(new)
    if kept:
        merged.setdefault("_보존", []).append(
            {"때": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
             "지킨_키": kept})
    _write_json(merged, path, indent=1)


def _write_json(obj: Any, path: str, indent: Optional[int] = None) -> None:
    """JSON 을 쓴다 — **덮어쓰기 전에 반드시 `.bak` 을 남긴다** (결함 145).

    ## 이 함수가 왜 따로 있나 (08-14)

    08-13에 «색인을 쓰는 곳은 `_save_index` 하나뿐» 을 시험 [98]로 박았다.
    그런데 08-14에 `_save_pairs`(쌍→특허 집합)가 생기면서 **파일을 쓰는
    두 번째 곳**이 됐고, 그 시험이 걸렸다.

    선택지가 둘이었다 —

        ⓐ 시험에 `_save_pairs` 를 **예외로 등록**한다 → 가드가 약해진다
        ⓑ **쓰기를 한 곳으로 모은다**                  → 가드가 강해진다

    ⓑ 를 골랐다. 이제 `.bak` 보장이 **한 함수에** 있으므로, 다음에 세
    번째 저장이 생겨도 그 보장이 자동으로 따라간다. ⓐ 였으면 새 저장마다
    `.bak` 을 다시 손으로 적어야 하고 — **그게 결함 145 가 난 방식이다.**

    > 가드에 예외를 뚫는 것과 코드를 가드에 맞추는 것은 다르다.
    """
    # ⚠ 08-15 — **여기 있던 `.bak` 로직을 `io/safeio` 로 올렸다**(결함 223).
    #   `bench/run.py` 도 같은 방어가 필요해졌는데, 거기 하나 더 만들면
    #   **같은 방어가 두 곳**이 되고 그게 결함 98·222 가 난 방식이다.
    from .safeio import save_json as _sj
    r = _sj(obj, path, indent=indent)
    if r.get("원본유지"):
        # **백업을 못 했으므로 원본을 안 덮었다.** 조용히 넘기면
        # 「저장했다」고 믿은 채 옛 파일을 읽게 된다 — 결함 223 의 반대 방향
        print("  ⚠ 백업 실패로 **원본을 안 덮었다** → %s\n     %s"
              % (r["경로"], r["상태"]))


def _footer(path: str) -> Dict[str, Any]:
    """**pyarrow 없이** parquet 꼬리를 읽는다 — 행 수·열 이름·행그룹.

    ## 왜 손으로 파나 (결함 136 곁가지)

    08-12에 4.2 GB 를 받아 놓고 **온전한지 확인할 방법이 없었다.**
    `parquet_state` 가 `pyarrow` 를 못 찾자 «없다» 만 말하고 끝냈기 때문이다.
    **검증 도구가 의존성 때문에 못 도는 것은 방어가 아니다** — DRKG·SIDER 는
    표준 라이브러리만으로 확인했는데 여기만 못 할 이유가 없다.

    parquet 은 구조가 `PAR1 … <FileMetaData> <len:u32> PAR1` 이다. 꼬리
    메타데이터는 **Thrift compact** 인코딩이고, 우리가 필요한 셋은 앞쪽에
    있다 — `1:version` `2:schema(list)` `3:num_rows` `4:row_groups(list)`.
    그래서 **행그룹 통계 전체를 파싱하지 않고** 필요한 데까지만 읽는다.

    **한계를 적는다** — 이건 무결성 확인용이지 자료를 읽는 도구가 아니다.
    값을 읽으려면 snappy 해제와 인코딩 처리가 필요하고, 그건 `pyarrow` 가
    한다. 여기서 «온전하다» 가 나와도 **내용이 맞다는 뜻은 아니다.**
    """
    import struct
    out: Dict[str, Any] = {"ok": False, "rows": None, "columns": None,
                           "row_groups": None, "error": None}
    n = os.path.getsize(path)
    if n < 12:
        out["error"] = "**파일이 너무 작다** — %d바이트. 받다 만 것이다" % n
        return out
    with open(path, "rb") as f:
        if f.read(4) != b"PAR1":
            out["error"] = "**parquet 이 아니다** — 머리 4바이트가 `PAR1` 이 아니다"
            return out
        f.seek(-8, 2)
        t = f.read(8)
        if t[4:] != b"PAR1":
            out["error"] = ("**꼬리가 잘렸다** — 마지막 4바이트가 `PAR1` 이 "
                            "아니다. 내려받다 끊긴 파일이다")
            return out
        flen = struct.unpack("<I", t[:4])[0]
        if 8 + flen > n:
            out["error"] = ("**꼬리 메타데이터 길이가 파일보다 크다** — "
                            "%d > %d. 깨졌다" % (8 + flen, n))
            return out
        f.seek(n - 8 - flen)
        B = f.read(flen)

    pos = 0

    def uv() -> int:                       # unsigned varint
        nonlocal pos
        r = s = 0
        while True:
            b = B[pos]
            pos += 1
            r |= (b & 0x7F) << s
            if not b & 0x80:
                return r
            s += 7

    def zz() -> int:                       # zigzag varint
        v = uv()
        return (v >> 1) ^ -(v & 1)

    def skip(t: int) -> None:
        nonlocal pos
        if t in (1, 2):                    # BOOL — 값이 헤더에 실린다
            return
        if t == 3:
            pos += 1
        elif t in (4, 5, 6):
            zz()
        elif t == 7:
            pos += 8
        elif t == 8:
            pos += uv()
        elif t in (9, 10):
            h = B[pos]
            pos += 1
            sz, et = h >> 4, h & 0x0F
            if sz == 15:
                sz = uv()
            for _ in range(sz):
                skip(et)
        elif t == 12:
            struct_()
        else:
            raise ValueError("알 수 없는 thrift 형 %d" % t)

    def struct_(names: Optional[List[str]] = None) -> None:
        nonlocal pos
        fid = 0
        while True:
            h = B[pos]
            pos += 1
            if h == 0:
                return
            d, t = h >> 4, h & 0x0F
            fid = fid + d if d else zz()
            if names is not None and fid == 4 and t == 8:   # SchemaElement.name
                L = uv()
                names.append(B[pos:pos + L].decode("utf-8", "replace"))
                pos += L
                continue
            skip(t)

    try:
        names: List[str] = []
        fid = 0
        while pos < len(B):
            h = B[pos]
            pos += 1
            if h == 0:
                break
            d, t = h >> 4, h & 0x0F
            fid = fid + d if d else zz()
            if fid == 2 and t == 9:                     # schema
                hh = B[pos]
                pos += 1
                sz, et = hh >> 4, hh & 0x0F
                if sz == 15:
                    sz = uv()
                for _ in range(sz):
                    struct_(names)
                # 첫 원소는 **루트**다(보통 `schema`). 열이 아니다.
                out["columns"] = names[1:]
                continue
            if fid == 3 and t == 6:                     # num_rows
                out["rows"] = zz()
                continue
            if fid == 4 and t == 9:                     # row_groups
                hh = B[pos]
                pos += 1
                sz = hh >> 4
                if sz == 15:
                    sz = uv()
                out["row_groups"] = sz
                break                                   # **여기서 멈춘다**
            skip(t)
    except Exception as e:
        out["error"] = ("**꼬리 메타데이터를 못 읽었다** — %s: %s. 깨졌거나 "
                        "parquet 판이 우리가 아는 것과 다르다"
                        % (type(e).__name__, str(e)[:100]))
        return out
    if out["rows"] is None or out["columns"] is None:
        out["error"] = "**행 수나 열 이름을 못 찾았다** — 꼬리가 온전하지 않다"
        return out
    out["ok"] = True
    return out


def parquet_state(path: str, min_rows: int = _SC_MIN_ROWS) -> Dict[str, Any]:
    """Parquet 이 **온전한가.** DRKG·SIDER 와 같은 검사인데 방식이 다르다.

    텍스트가 아니라 **줄을 셀 수 없다.** 대신 parquet 은 꼬리에 메타데이터가
    있어서 **잘리면 열 때 예외가 난다** — 그건 오히려 다행이다. 여기서는
    ① 열리는가 ② 행 수가 하한을 넘는가 ③ 필요한 열이 있는가를 본다.

    ## 08-12 — **`pyarrow` 없이도 여기까지는 본다** (결함 136 곁가지)

    앞판은 `pyarrow` 가 없으면 «없다» 만 말하고 끝냈다. 그래서 4.2 GB 를
    받아 놓고 **온전한지 확인할 방법이 없었다.** 이제 `_footer()` 가
    표준 라이브러리만으로 행 수·열 이름을 읽는다.

    `pyarrow` 는 **자료를 실제로 읽을 때** 필요하다(snappy·인코딩).
    그건 `read_ok` 로 따로 알린다 — **«온전하다» 와 «읽을 수 있다» 는 다르다.**
    """
    out: Dict[str, Any] = {"ok": False, "path": path, "rows": None,
                           "columns": None, "size_mb": None, "error": None,
                           "read_ok": False, "row_groups": None}
    if not os.path.exists(path):
        out["error"] = ("**없다** — 받아라: %s (로컬 전용, 배포본엔 안 넣는다)"
                        % (SURECHEMBL_DIR + os.path.basename(path)))
        return out
    out["size_mb"] = round(os.path.getsize(path) / 1e6, 1)
    ft = _footer(path)
    if not ft["ok"]:
        out["error"] = ft["error"]
        return out
    out["rows"] = ft["rows"]
    out["columns"] = ft["columns"]
    out["row_groups"] = ft["row_groups"]
    try:
        import pyarrow.parquet as pq          # noqa: F401
        out["read_ok"] = True
    except Exception:
        out["note"] = ("무결성은 확인했지만 **자료를 읽으려면 pyarrow 가 "
                       "필요하다** — `py -m pip install pyarrow`. 로컬 전용 "
                       "의존이고 `requirements.txt` 에 안 넣는다")
    if out["rows"] < min_rows:
        out["error"] = ("**행이 모자란다** — %d행 (하한 %d). 온전한 판이 맞는지 "
                        "봐라" % (out["rows"], min_rows))
        return out
    out["ok"] = True
    return out


def our_drugs(files: Optional[List[str]] = None) -> List[str]:
    """우리가 실제로 판정하는 약 이름. **색인은 이만큼만 만든다.**

    3,099만 화합물 중 우리에게 필요한 것은 수백 종이다. 전부 색인하면
    배포본에 못 넣는다.
    """
    import csv as _csv
    import re as _re
    fs = files or ["bench_matched.csv", "bench_holdout_matched_sealed.csv",
                   "bench_holdout_matched_dev.csv", "gen_matched.csv"]
    seen: Dict[str, str] = {}
    for f in fs:
        if not os.path.exists(f):
            continue
        for r in _csv.DictReader(open(f, encoding="utf-8-sig")):
            d = (r.get("drug") or "").strip()
            if not d:
                continue
            key = _re.sub(r"\s+", " ", d.lower())
            seen.setdefault(key, d)
    return sorted(seen.values())


def build_index(compounds: str = "surechembl_compounds.parquet",
                pmap: Optional[str] = None,
                patents: Optional[str] = None,
                out_path: str = FTO_INDEX,
                drugs: Optional[List[str]] = None,
                log=None) -> Dict[str, Any]:
    """벌크 parquet → **우리 약만 담은 작은 색인.**

    ## 단계와 그 사이에서 멈출 수 있는 곳

        ① 약 이름 → InChIKey        PubChem (`io/pubchem`) · 캐시
        ② InChIKey → compound_id    compounds.parquet   3.9 G
        ③ compound_id → patent_id   patent_compound_map 4.6 G   ← 없으면 여기서 멈춘다

    ## ⚠ `patents=` 는 **여기서 안 쓴다** (결함 216)

    08-12~08-14 동안 이 인자가 **받기만 하고 소비되지 않았다.** 독스트링에
    «④ patent_id → 특허번호» 라고 적혀 있어서 **있는 줄 알았다.** 5.9 G 를
    받고 색인을 다시 돌리고도 그 파일을 한 바이트도 안 읽었다.

    ④(공개연도)는 **`--use-year`** 가 한다 — `patent_years()`. 그쪽은
    `use_patents` 가 남긴 쌍→특허 집합이 있어야 하므로 이 함수의 일이
    아니다. 인자는 **호환을 위해 남기고 여기서 무시한다고 적는다.**

    **②까지만 있어도 «우리 약이 SureChEMBL 에 몇 종 있나» 를 낼 수 있다.**
    그 커버리지가 낮으면 나머지 9.6 G 를 안 받는다 — 그게 이 단계 분리의
    목적이다. DRKG 때 14GB 를 받아 놓고 못 쓰는 상황을 피한다.

    **없는 단계를 «0건» 으로 세지 않는다.** 각 단계가 `None` 과 `0` 을
    구별해서 돌려준다(결함 35).
    """
    from . import sources
    st = parquet_state(compounds)
    if not st["ok"]:
        return {"ok": False, "stage": "compounds", "error": st["error"]}
    if not st["read_ok"]:
        # 형제 다섯은 전부 이렇게 하는데 **여기만 그냥 터졌다**
        return {"ok": False, "stage": "compounds",
                "error": "**pyarrow 가 없다** — `py -m pip install pyarrow`"}
    import pyarrow.parquet as pq

    names = drugs if drugs is not None else our_drugs()
    keys: Dict[str, str] = {}          # InChIKey → 약 이름
    miss: List[str] = []
    fail: List[str] = []
    why: List[str] = []                # **실패 사유.** 세기만 하면 못 고친다
    got = 0                            # **키를 얻은 «약» 수** (≠ 고유 키 수)
    for _i, d in enumerate(names, 1):
        if log and (_i % 50 == 0 or _i == len(names)):
            log("  ① InChIKey  %4d/%d  얻음 %d · 없음 %d · 실패 %d"
                % (_i, len(names), len(keys), len(miss), len(fail)))
        # ── **차단기** (08-12 · 결함 141) ────────────────────────────
        #
        #   첫 판에서 **1,207건이 전부 실패**했고 그걸 7분 뒤에야 알았다.
        #   사유도 안 남겨서 화면만 보고는 **왜 실패했는지 알 수 없었다.**
        #   조회가 구조적으로 막혔으면 스물이면 안다 — 거기서 멈춘다.
        if len(fail) >= 20 and not keys and not miss:
            out_err = ("**앞 %d건이 전부 조회 실패다.** 네트워크나 PubChem "
                       "쪽이 막힌 것이지 «그 약이 없다» 가 아니다.\n"
                       "     첫 사유: %s" % (len(fail), why[0] if why else "?"))
            return {"ok": False, "stage": "inchikey", "error": out_err,
                    "n_drugs": len(names), "n_inchikey": 0,
                    "n_not_in_pubchem": 0, "n_lookup_failed": len(fail),
                    "failed_examples": why[:5], "no_key_examples": [],
                    "한계": LIMITS_SC}
        r = sources.fetch_inchikey(d)
        if r.get("error") and len(why) < 5:
            why.append("%s → %s" % (d[:40], str(r["error"])[:120]))
        if r.get("inchikey"):
            # ⚠ **여러 약이 같은 InChIKey 를 낸다** (염·수화물·표기 차이).
            #   dict 라 뒤엣것이 앞엣것을 덮어써 **깔때기에서 약이 증발한다** —
            #   실측 803+391+3 = 1,197 ≠ 1,207, **10종이 사라졌다**(결함 155).
            #   키를 얻은 **약 수**와 **고유 InChIKey 수**는 다른 값이다.
            got += 1
            keys[r["inchikey"]] = d
        elif r.get("error"):
            fail.append(d)             # **조회 실패** — 없는 것과 다르다
        else:
            miss.append(d)             # PubChem 에 그 이름이 없다(404)

    out: Dict[str, Any] = {
        "ok": False, "stage": "compounds",
        "n_drugs": len(names), "n_inchikey": len(keys),
        # 깔때기가 **맞아떨어지게** 한다: got + miss + fail == n_drugs
        "n_got_key": got, "n_dup_key": got - len(keys),
        # **셋을 갈라 센다** — 결함 35 계열. «PubChem 에 없다» 와
        #   «조회가 실패했다» 를 뭉치면 커버리지가 거짓말한다.
        "n_not_in_pubchem": len(miss), "n_lookup_failed": len(fail),
        # **이름만 남기면 못 고친다.** 사유를 같이 싣는다 (결함 141)
        "no_key_examples": miss[:10], "failed_examples": why[:5],
        "compounds_rows": st["rows"], "compounds_cols": st["columns"],
        "hits": {}, "error": None,
        "한계": LIMITS_SC,
    }
    if not keys:
        out["error"] = ("InChIKey 를 하나도 못 얻었다 — PubChem 조회를 먼저 "
                        "확인해라. **«특허 없음» 이 아니라 «조회 실패» 다**")
        return out

    # ② compounds.parquet 을 **조각 단위로** 훑는다. 3.9G 를 통째로 안 올린다.
    want = set(keys)
    cid: Dict[int, str] = {}
    f = pq.ParquetFile(compounds)
    col = "inchi_key" if "inchi_key" in (st["columns"] or []) else None
    if col is None:
        out["error"] = ("`inchi_key` 열이 없다 — 열: %s. 스키마가 바뀌었을 수 "
                        "있다(2주마다 새로 올라오고 «schema might change» 라고 "
                        "공지돼 있다)" % (st["columns"] or [])[:8]
        )
        return out
    _seen = 0
    _tot = st["rows"] or 1
    for batch in f.iter_batches(batch_size=200_000, columns=["id", col]):
        ids = batch.column("id").to_pylist()
        ks = batch.column(col).to_pylist()
        for i, k in zip(ids, ks):
            if k and k.upper() in want:
                cid[i] = keys[k.upper()]
        _seen += len(ids)
        if log and _seen % 4_000_000 < 200_000:
            log("  ② compounds  %5.1f%%  (%d/%d행) · 맞은 것 %d"
                % (100 * _seen / _tot, _seen, _tot, len(cid)))
    # ── **분자와 분모의 단위를 맞춘다** (결함 142) ────────────────────
    #
    #   첫 실측에서 **커버리지 170.7%** 가 나왔다. 100을 넘는 비율은 없다.
    #   원인: `cid` 는 `compound_id → 약 이름` 이고 **한 InChIKey 가
    #   SureChEMBL 의 여러 `compound_id` 에 걸린다.** 그래서 분자는
    #   «화합물 레코드 수», 분모는 «고유 InChIKey 수» 로 **단위가 달랐다.**
    #
    #   실측: InChIKey 803개 → compound_id 1,371개 (1.7배).
    #   렌즈 4번 «재는 것이 잰다고 말하는 것인가» 에 그대로 걸린다.
    out["n_matched_cids"] = len(cid)                 # 화합물 레코드 수
    out["n_matched"] = len(set(cid.values()))        # **약 수** — 분모와 같은 단위
    out["coverage"] = (round(out["n_matched"] / len(keys), 4) if keys else 0.0)
    # ④ 가 이걸 다시 만들려면 3.9 G 를 또 훑어야 한다. **저장한다.**
    out["cid_map"] = {str(k): v for k, v in cid.items()}
    out["ok"] = True
    if not pmap:
        out["note"] = ("②까지만 돌렸다. **커버리지 %.1f%%.** 특허 연결은 "
                       "`patent_compound_map.parquet`(4.6G)가 있어야 한다"
                       % (100 * out["coverage"]))
        _save_index(out, out_path)
        return out
    out["stage"] = "map"
    m = map_scan(pmap, cid, log=log)
    out["map"] = m
    if m.get("error"):
        out["error"] = m["error"]
        out["ok"] = False
        return out
    out["ok"] = True
    _save_index(out, out_path)     # **여기도** — 어제 한 갈래만 고쳤다
    return out


# ── ③ compound_id → patent_id (08-12) ───────────────────────────────
#
# **필드를 갈라 세지 않으면 이 수치는 못 쓴다.**
#
#   화합물이 **청구항(Claims)** 에 나오는 것과 **명세서 본문(Description)**
#   에 예시로 스쳐 지나가는 것은 FTO 에서 완전히 다른 이야기다. 실시예
#   표에 수백 개가 나열되는 일이 흔하고, 그걸 «관련 특허 N건» 으로 합치면
#   **N 이 커질수록 무의미해진다.**
#
# SureChEMBL 문서(`chembl.gitbook.io/surechembl/downloads/bulk-data`)의 값.
# **`fields.parquet`(1.7 KB)가 있으면 그걸로 대조한다** — 문서와 파일이
# 어긋나면 파일이 정본이다.
FIELDS = {1: "명세서", 2: "청구항", 3: "초록", 4: "제목",
          5: "이미지", 6: "MOL 첨부"}
FIELD_CLAIMS = 2

# 한 화합물이 너무 많은 행을 물면 메모리가 아니라 **해석**이 깨진다.
#   물(水)처럼 흔한 것이 걸리면 수백만 행이 나오고 그건 신호가 아니다.
MAP_CAP = 200_000


def _tally(cids, fids, counts, capped, name_of=None, dropped=None):
    """걸러진 **작은** 조각을 세는 순수 함수. 여기만 파이썬 루프다.

    큰 배치는 `pyarrow.compute` 가 C++ 에서 거른다. 1.5억이 아니라
    **1.5억 중 우리 것만** 이 함수에 온다.

    ## 08-12 밤 — **상한이 47%를 조용히 버리고 있었다** (결함 146)

    앞판은 상한을 **`compound_id` 단위**로 걸었다. 두 문제가 나왔다.

    1. **한 약이 레코드 여러 개면 예산도 여러 배**가 된다. 실측:
       `vinblastine`·`streptomycin` 이 레코드 2개라 400,000 을 썼고,
       그래서 **레코드 수가 많은 약일수록 순위가 올라갔다.**
       결함 142(분자·분모 단위)와 **같은 고장이 한 함수 뒤에서 재발**했다
    2. 버린 행을 **아무도 안 셌다.** `matched_rows` 는 58,275,698 인데
       필드별 표의 합은 30,875,536 — **27,400,162행(47%)이 표에 없었고
       그 사실이 문서 어디에도 없었다.**

    그래서 **상한을 약 단위로 옮기고, 버린 행을 센다.**
    """
    for c, f in zip(cids, fids):
        key = name_of[c] if name_of else c            # **약 단위로 센다**
        if counts.get((key, -1), 0) >= MAP_CAP:
            capped.add(key)
            if dropped is not None:                   # **조용히 안 버린다**
                dropped[0] = dropped[0] + 1
            continue
        counts[(key, f)] = counts.get((key, f), 0) + 1
        counts[(key, -1)] = counts.get((key, -1), 0) + 1   # -1 = 합계
    return counts


def map_scan(pmap: str, cid2name: Dict[int, str], log=None,
             max_row_groups: Optional[int] = None) -> Dict[str, Any]:
    """`patent_compound_map.parquet` 을 훑어 **필드별 특허 건수**를 센다.

    ## 15억 행을 파이썬 루프로 돌면 안 된다

    이 파일은 **1,537,106,020행**이다(2026-08-04 판). 행마다 파이썬이
    조건을 보면 몇 시간 걸린다. 그래서 **`pyarrow.compute.is_in` 으로
    C++ 에서 거르고**, 걸러진 것만 파이썬이 센다. 우리 화합물이 1천 종이면
    남는 것은 수만 행이라 파이썬으로 충분하다.

    **행 수 = 그 필드에서의 특허 건수**다 — `(patent_id, compound_id,
    field_id)` 가 매핑 표의 한 줄이므로. 다만 같은 특허가 여러 필드에
    나오면 **필드별 합계는 특허 수보다 크다.** 그래서 합계를 «특허 N건»
    이라 부르지 않는다.
    """
    out: Dict[str, Any] = {"ok": False, "error": None, "rows_seen": 0,
                           "matched_rows": 0, "by_field": {}, "per_drug": {},
                           "capped": [], "row_groups": None}
    st = parquet_state(pmap, min_rows=1)
    if not st["ok"]:
        out["error"] = st["error"]
        return out
    if not st["read_ok"]:
        out["error"] = "**pyarrow 가 없다** — `py -m pip install pyarrow`"
        return out
    cols = st["columns"] or []
    for need in ("compound_id", "field_id"):
        if need not in cols:
            out["error"] = ("`%s` 열이 없다 — 열: %s. **스키마가 바뀌었다**"
                            % (need, cols))
            return out
    out["row_groups"] = st["row_groups"]

    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    want = pa.array(sorted(cid2name), type=pa.int64())
    f = pq.ParquetFile(pmap)
    counts: Dict[Any, int] = {}
    capped: set = set()
    dropped = [0]                       # **상한에 걸려 버린 행** (결함 146)
    seen = 0
    tot = st["rows"] or 1
    ngroups = f.num_row_groups if max_row_groups is None else min(
        max_row_groups, f.num_row_groups)
    for g in range(ngroups):
        t = f.read_row_group(g, columns=["compound_id", "field_id"])
        seen += t.num_rows
        # ── **여기가 핵심.** 거르는 일을 파이썬에 시키지 않는다 ──────
        mask = pc.is_in(t.column("compound_id"), value_set=want)
        sel = t.filter(mask)
        if sel.num_rows:
            _tally(sel.column("compound_id").to_pylist(),
                   sel.column("field_id").to_pylist(), counts, capped,
                   name_of=cid2name, dropped=dropped)
            out["matched_rows"] += sel.num_rows
        if log and (g % 250 == 0 or g == ngroups - 1):
            log("  ③ map  행그룹 %4d/%d (%.1f%%) · 맞은 행 %s"
                % (g + 1, ngroups, 100 * (g + 1) / ngroups,
                   "{:,}".format(out["matched_rows"])))
    out["rows_seen"] = seen
    out["scanned_all"] = (ngroups == f.num_row_groups)

    by_field: Dict[str, int] = {}
    per: Dict[str, Dict[str, int]] = {}
    for (drug, fid), n in counts.items():
        if fid == -1:
            continue
        name = FIELDS.get(fid, "미상(%d)" % fid)
        by_field[name] = by_field.get(name, 0) + n
        d = per.setdefault(drug, {})
        d[name] = d.get(name, 0) + n
    out["by_field"] = by_field
    out["per_drug"] = per
    out["capped"] = sorted(capped)                 # 이미 약 이름이다
    out["dropped_rows"] = dropped[0]
    # **합이 안 맞으면 그 사실을 낸다.** 앞판은 47%가 조용히 빠졌다
    out["tally_sum"] = sum(by_field.values())
    out["tally_gap"] = out["matched_rows"] - out["tally_sum"]
    out["n_drugs_with_claims"] = sum(
        1 for v in per.values() if v.get(FIELDS[FIELD_CLAIMS], 0) > 0)
    out["n_drugs_hit"] = len(per)
    out["ok"] = True
    return out


# ── 커버리지 게이트 CLI (08-12) ──────────────────────────────────────
#
#   `build_index` 를 손으로 부르면 **15분 동안 화면이 비어 있다.**
#   그러면 사람은 «멈춘 건가» 를 의심하고, 의심하면 끊는다.
#   진행을 찍는 것이 기능이다.
# ── ④ 질환을 같이 건다 (08-12 밤) ───────────────────────────────────
#
# ## 왜 이걸 하나 — **셋는 대상이 틀렸다**
#
# ③까지는 «이 화합물이 특허 청구항에 나오는가» 를 셌다. 그런데 FTO 가
# 묻는 것은 **«이 화합물을 이 용도로 청구한 특허가 있는가»** 다.
# 물음이 다르니 아무리 잘 세도 안 맞는다 — 그래서 상위가 산화철·질소가
# 됐다(결함 143). **정규화로는 못 고친다. 조건을 붙여야 고쳐진다.**
#
# SureChEMBL 이 `biomedical_locations` 에 **질환도 필드별로** 담아 뒀다.
#
#   biomedical_entities.parquet    32 M   id · type_id · original/corrected · resolved_form
#   biomedical_locations.parquet  1.6 G   entity_id · patent_id · **field_id** · count
#   biomedical_types.parquet      3.1 K   type_id → 이름
#
# **청구항(field 2)에 우리 질환이 있는 특허** ∩ **청구항에 우리 화합물이
# 있는 특허** = 용도특허 신호. 산화철 단독은 수만 건이어도
# **산화철 + 소양증**은 드물다. 편향이 «줄어드는» 게 아니라 **조건이
# 안 맞아 애초에 안 걸린다.**
#
# ⚠ **그래도 FTO 판단이 아니다.** 같은 청구항에 함께 등장한다는 것이
#   그 용도를 청구했다는 뜻은 아니다. 청구항 해석은 여전히 안 한다.
DISEASE_TYPE_ID = 2          # biomedical_types: 1 유전자/단백질 · 2 질환 · 3 기전


def _norm_term(s: str) -> str:
    """질환 이름을 맞춰 보기 위한 정규화.

    우리 적응증은 `Malignant neoplasm of breast` · `Allergic rhinitis
    (disorder)` 처럼 **SNOMED 계열 문자열**이고 SureChEMBL 은 MeSH·Disease
    Ontology 로 푼다. 그래서 **그대로는 거의 안 맞는다.**

    여기서 하는 것은 소문자화·괄호 꼬리 제거·구두점 제거·공백 정규화까지다.
    **동의어 사전은 안 만든다** — 만들면 그 사전이 결과를 만들고,
    그러면 이 지표가 «우리가 쓴 사전» 을 재게 된다.
    """
    import re as _r
    s = (s or "").lower().strip()
    # ── SNOMED CT **의미 태그**를 지운다 (08-12 · 실측으로 넓혔다) ──────
    #   앞판은 넷만 지워 `COVID19 (disease)` 를 놓쳤다. 의미 태그는
    #   **SNOMED 의 문서화된 규약**이라 목록을 다 적는 것이 동의어 사전을
    #   만드는 것과 다르다 — 뜻을 바꾸지 않고 **형식만 벗긴다.**
    s = _r.sub(r"\s*\((disorder|disease|finding|situation|event|procedure"
               r"|morphologic abnormality|qualifier value|observable entity"
               r"|body structure|substance|product)\)\s*$", "", s)
    s = _r.sub(r"[^a-z0-9가-힣 ]+", " ", s)
    return _r.sub(r"\s+", " ", s).strip()


def disease_entities(path: str = "surechembl_biomedical_entities.parquet",
                     log=None) -> Dict[str, Any]:
    """질환 엔티티를 **이름 → id 목록** 으로 올린다. 32 MB 라 통째로 읽는다."""
    out: Dict[str, Any] = {"ok": False, "error": None, "by_name": {},
                           "n_rows": None, "n_disease": 0}
    st = parquet_state(path, min_rows=1)
    if not st["ok"]:
        out["error"] = st["error"]
        return out
    if not st["read_ok"]:
        out["error"] = "**pyarrow 가 없다** — `py -m pip install pyarrow`"
        return out
    cols = st["columns"] or []
    need = ("id", "type_id")
    for c in need:
        if c not in cols:
            out["error"] = "`%s` 열이 없다 — 열: %s. 스키마가 바뀌었다" % (c, cols)
            return out
    out["n_rows"] = st["rows"]

    import pyarrow.parquet as pq
    take = [c for c in ("id", "type_id", "corrected_text",
                        "original_text", "resolved_form") if c in cols]
    f = pq.ParquetFile(path)
    by: Dict[str, List[int]] = {}
    n_dis = 0
    _keys = [k for k in ("corrected_text", "original_text", "resolved_form")
             if k in take]                     # 루프 밖에서 한 번만
    for batch in f.iter_batches(batch_size=200_000, columns=take):
        d = {c: batch.column(c).to_pylist() for c in take}
        for i in range(len(d["id"])):
            if d["type_id"][i] != DISEASE_TYPE_ID:
                continue
            n_dis += 1
            for key in _keys:
                # ⚠ `d.get(key, [None]*n)` 을 쓰면 안 된다 — **파이썬은 키가
                #   있어도 기본값을 먼저 만든다.** 20만짜리 리스트를 매
                #   반복 3개씩 새로 할당해 **O(N²)** 이 됐다(결함 147).
                #   실측 외삽: 106만 행에 **35분** → 고치면 **32초**.
                v = d[key][i]
                k = _norm_term(v) if isinstance(v, str) else ""
                if k:
                    by.setdefault(k, []).append(d["id"][i])
        if log:
            log("  ④ entities  질환 %s개 · 이름 %s개"
                % ("{:,}".format(n_dis), "{:,}".format(len(by))))
    out["by_name"] = by
    out["n_disease"] = n_dis
    out["ok"] = True
    return out


def _variants(s: str) -> List[Tuple[str, str]]:
    """맞춰 볼 형태들. **각각에 규칙 이름을 붙인다** — 무엇으로 맞았는지
    모르면 나중에 그 규칙이 결과를 만들었는지 못 따진다.

    ## 도치는 **형식 변환**이지 동의어가 아니다

    실측(08-12): 못 맞춘 309개의 다수가 이 모양이었다 —

        Diabetes Mellitus, Non-Insulin-Dependent
        Multiple Sclerosis, Primary Progressive
        Leukemia, Myelomonocytic, Chronic

    **MeSH 표목의 도치 규약**이다. `A, B` → `B A` 는 같은 개념을 다른
    순서로 적은 것이라 **뜻이 안 변한다.** 그래서 주 분석에 넣는다.

    ## 절단은 **넓히는 것**이라 따로 센다

    `Multiple Sclerosis, Primary Progressive` → `Multiple Sclerosis` 는
    **더 넓은 개념**이다. 1차 진행형 MS 후보를 MS 일반 특허에 이으면
    **특허 건수가 과대**해진다. 그건 매칭이 아니라 **다른 질문에 답하는 것**
    이므로 `절단` 으로 이름을 달아 **민감도 분석에서만** 쓴다.
    """
    out = [("정확", _norm_term(s))]
    if "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        if len(parts) >= 2:
            out.append(("도치", _norm_term(" ".join(reversed(parts)))))
            out.append(("절단", _norm_term(parts[0])))
    return [(r, k) for r, k in out if k]


def match_indications(indications: List[str], ents: Dict[str, Any],
                      rules: Tuple[str, ...] = ("정확", "도치")) -> Dict[str, Any]:
    """우리 적응증 ↔ SureChEMBL 질환 엔티티. **매칭률이 이 실험의 관문이다.**

    **못 맞춘 것을 «특허 0건» 으로 세면 안 된다.** 그건 «없다» 가 아니라
    «못 찾았다» 이고, 오늘 결함 141 이 정확히 그 모양이었다.
    """
    by = ents.get("by_name") or {}
    hit: Dict[str, List[int]] = {}
    how: Dict[str, str] = {}                 # **무엇으로 맞았나**
    miss: List[str] = []
    for ind in indications:
        got = None
        for rule, k in _variants(ind):
            if rule not in rules:
                continue
            ids = by.get(k)
            if ids:
                got = (rule, sorted(set(ids)))
                break
        if got:
            how[ind], hit[ind] = got[0], got[1]
        else:
            miss.append(ind)
    n = len(indications)
    per_rule: Dict[str, int] = {}
    for r in how.values():
        per_rule[r] = per_rule.get(r, 0) + 1
    return {"n": n, "n_hit": len(hit), "n_miss": len(miss),
            "rate": round(len(hit) / n, 4) if n else 0.0,
            "hit": hit, "how": how, "per_rule": per_rule,
            "rules": list(rules), "miss_examples": miss[:15]}


def claim_patents(pmap: str, cid2name: Dict[int, str], log=None,
                  max_row_groups: Optional[int] = None) -> Dict[str, Any]:
    """A단계 — **청구항에 우리 화합물이 있는 특허**를 모은다.

    ③(`map_scan`)은 세기만 했다. 교집합을 하려면 **patent_id 자체**가
    필요하다. 청구항(field 2)만 본다 — 명세서까지 넣으면 2,736만 행이라
    교집합이 무의미해진다.

    **질환 쪽을 먼저 모으지 않는 이유** — 질환은 특허에 아주 흔해서
    `질환 → 특허` 는 수천만 건이 된다. 화합물 쪽은 청구항 기준 279만 행
    이라 **상한이 잡힌다.** 그래서 이쪽을 먼저 모으고 B단계에서 그걸로
    거른다(명세 §7).
    """
    out: Dict[str, Any] = {"ok": False, "error": None, "by_patent": {},
                           "n_patents": 0, "rows": 0}
    st = parquet_state(pmap, min_rows=1)
    if not st["ok"]:
        out["error"] = st["error"]
        return out
    if not st["read_ok"]:
        out["error"] = "**pyarrow 가 없다** — `py -m pip install pyarrow`"
        return out
    cols = st["columns"] or []
    for need in ("patent_id", "compound_id", "field_id"):
        if need not in cols:
            out["error"] = "`%s` 열이 없다 — 열: %s. 스키마가 바뀌었다" % (need, cols)
            return out

    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    want = pa.array(sorted(cid2name), type=pa.int64())
    f = pq.ParquetFile(pmap)
    ng = f.num_row_groups if max_row_groups is None else min(
        max_row_groups, f.num_row_groups)
    by: Dict[int, set] = {}
    for g in range(ng):
        t = f.read_row_group(g, columns=["patent_id", "compound_id", "field_id"])
        m = pc.and_(pc.is_in(t.column("compound_id"), value_set=want),
                    pc.equal(t.column("field_id"), FIELD_CLAIMS))
        sel = t.filter(m)
        if sel.num_rows:
            ps = sel.column("patent_id").to_pylist()
            cs = sel.column("compound_id").to_pylist()
            for p, c in zip(ps, cs):
                by.setdefault(p, set()).add(cid2name[c])
            out["rows"] += sel.num_rows
        if log and (g % 250 == 0 or g == ng - 1):
            log("  A map  행그룹 %4d/%d (%.1f%%) · 특허 %s"
                % (g + 1, ng, 100 * (g + 1) / ng, "{:,}".format(len(by))))
    out["by_patent"] = by
    # ── **약물 단위도 낸다** (결함 218) ───────────────────────────
    #
    #   화면(`dash.right_patent`)은 **약물 하나**를 받는다. 그런데 여태
    #   저장한 것은 `by_patent`(특허→약물)와 쌍 단위뿐이라, 화면이 쓸
    #   «이 약이 청구항에 나오는 특허 집합» 이 어디에도 없었다.
    #   쌍에서 합치면 **용도특허(약∩질환)만** 세어져 벤치 수치와 어긋난다.
    bd: Dict[str, set] = {}
    for p, names in by.items():
        for nm in names:
            bd.setdefault(nm, set()).add(p)
    out["by_drug"] = bd
    out["n_drugs_with_patents"] = len(bd)
    out["n_patents"] = len(by)
    out["scanned_all"] = (ng == f.num_row_groups)
    out["ok"] = True
    return out


def use_patents(locs: str, drug_patents: Dict[int, set],
                ent2ind: Dict[int, List[str]], log=None,
                max_row_groups: Optional[int] = None) -> Dict[str, Any]:
    """B단계 — 그 특허들 중 **청구항에 우리 질환도 있는** 것.

    결과는 `(약, 적응증) → 특허 수`. **쌍 단위**다 — 화합물 단위가
    앞 지표의 실패 원인이었다(결함 143).
    """
    out: Dict[str, Any] = {"ok": False, "error": None, "pairs": {},
                           "rows": 0, "n_use_patents": 0}
    st = parquet_state(locs, min_rows=1)
    if not st["ok"]:
        out["error"] = st["error"]
        return out
    if not st["read_ok"]:
        out["error"] = "**pyarrow 가 없다** — `py -m pip install pyarrow`"
        return out
    cols = st["columns"] or []
    for need in ("entity_id", "patent_id", "field_id"):
        if need not in cols:
            out["error"] = "`%s` 열이 없다 — 열: %s. 스키마가 바뀌었다" % (need, cols)
            return out

    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    wp = pa.array(sorted(drug_patents), type=pa.int64())
    we = pa.array(sorted(ent2ind), type=pa.int64())
    f = pq.ParquetFile(locs)
    ng = f.num_row_groups if max_row_groups is None else min(
        max_row_groups, f.num_row_groups)
    # ⚠ **값이 정수면 안 된다** (결함 148). `match_indications` 가 한
    #   적응증에 엔티티 id 를 여럿 물리므로, 세면 **같은 특허가 엔티티
    #   수만큼 중복**된다. 「특허 N건」이라 부르려면 **특허 집합**이어야 한다.
    pairs: Dict[str, set] = {}
    hitp = set()
    for g in range(ng):
        t = f.read_row_group(g, columns=["entity_id", "patent_id", "field_id"])
        m = pc.and_(pc.and_(pc.is_in(t.column("patent_id"), value_set=wp),
                            pc.is_in(t.column("entity_id"), value_set=we)),
                    pc.equal(t.column("field_id"), FIELD_CLAIMS))
        sel = t.filter(m)
        if sel.num_rows:
            es = sel.column("entity_id").to_pylist()
            ps = sel.column("patent_id").to_pylist()
            for e_, p in zip(es, ps):
                hitp.add(p)
                for drug in drug_patents.get(p, ()):
                    for ind in ent2ind[e_]:
                        # **정본 키.** 세 곳이 같은 규약을 쓴다 (결함 144)
                        k = pair_key(drug, ind)
                        pairs.setdefault(k, set()).add(p)   # **특허 집합**
            out["rows"] += sel.num_rows
        if log and (g % 250 == 0 or g == ng - 1):
            log("  B loc  행그룹 %4d/%d (%.1f%%) · 쌍 %s"
                % (g + 1, ng, 100 * (g + 1) / ng, "{:,}".format(len(pairs))))
    out["pairs"] = {k: len(v) for k, v in pairs.items()}
    # ⚠ **집합을 세고 버리면 안 된다** (결함 216). 연도·출원인 같은 뒤
    #   분석은 **어느 특허인지**를 알아야 하는데, 그걸 버리면 4.98 G +
    #   1.71 G 를 **처음부터 다시 훑어야** 한다. 08-14 에 실제로 그랬다.
    out["pair_patents"] = {k: sorted(v) for k, v in pairs.items()}
    out["n_use_patents"] = len(hitp)
    out["scanned_all"] = (ng == f.num_row_groups)
    out["ok"] = True
    return out


def pair_key(drug: str, ind: str) -> str:
    """`(약, 적응증)` 의 **정본 키**. 세 곳이 같은 규약을 써야 한다 —
    `claim_patents`(약 이름) · `use_patents`(쌍 키) · `use_signal`(조회).

    ## 왜 필요한가 (결함 144)

    `our_drugs()` 는 소문자로 중복을 없애고 **처음 본 표기**를 남긴다.
    `labeled_pairs()` 는 CSV 원본 표기를 쓴다. 그래서 실측으로 **46종이
    `Ambrisentan` vs `ambrisentan` 처럼 갈렸다** — 그 쌍들은 조회에 실패해
    **«적응증을 못 이었다»(미연결)로 잘못 세어진다.**

    미연결은 **명세 §5-1이 분모에서 빼기로 한 칸**이라, 우리 버그가
    그 칸에 섞이면 **«못 이었다»와 «대소문자가 달랐다»가 뭉개진다.**
    결함 35 계열 — 서로 다른 실패를 한 칸에 넣는 것.

    **`_norm_term` 을 안 쓴다.** 그건 구두점까지 지워서 서로 다른 적응증을
    합칠 수 있다. 여기서는 **소문자·공백 정규화까지만** 한다.
    """
    import re as _r
    d = _r.sub(r"\s+", " ", (drug or "").strip().lower())
    i = _r.sub(r"\s+", " ", (ind or "").strip().lower())
    return "%s||%s" % (d, i)


def _dkey(drug: str) -> str:
    import re as _r
    return _r.sub(r"\s+", " ", (drug or "").strip().lower())


def labeled_pairs(files: Optional[List[str]] = None) -> List[Tuple[str, str, str]]:
    """`(약, 적응증, 라벨)` 고유 쌍. **단위가 쌍이다** — 결함 143의 교훈."""
    import csv as _csv
    fs = files or ["bench_matched.csv", "gen_matched.csv",
                   "bench_holdout_matched_dev.csv",
                   "bench_holdout_matched_sealed.csv"]
    seen, out = set(), []
    for f in fs:
        if not os.path.exists(f):
            continue
        for r in _csv.DictReader(open(f, encoding="utf-8-sig")):
            d = (r.get("drug") or "").strip()
            i = (r.get("indication") or "").strip()
            lab = (r.get("label") or "").strip()
            if not (d and i and lab):
                continue
            k = (d.lower(), i.lower())
            if k in seen:
                continue
            seen.add(k)
            out.append((d, i, lab))
    return out


def use_signal(pairs: List[Tuple[str, str, str]], hit_pairs: Dict[str, int],
               matched_drugs: set, ind_hit: Dict[str, List[int]]) -> Dict[str, Any]:
    """명세 `e22a4bf7…` 의 주지표 둘을 **코드에서** 낸다.

    **미연결 쌍을 «0건» 으로 안 센다** — 분모에서 뺀다(명세 §5-1).
    그게 결함 141 과 같은 모양이기 때문이다.
    """
    from ..bench import stats as S
    ev, un = [], 0
    # **대소문자로 갈리면 우리 버그가 «미연결» 칸에 섞인다** (결함 144)
    md = {_dkey(x) for x in matched_drugs}
    ih = {_dkey(x) for x in ind_hit}
    for d, i, lab in pairs:
        if _dkey(d) not in md or _dkey(i) not in ih:
            un += 1                                  # **미연결.** 0건이 아니다
            continue
        n = hit_pairs.get(pair_key(d, i), 0)
        ev.append((d, i, lab, n))
    n_all = len(ev)
    hit = [x for x in ev if x[3] > 0]
    out: Dict[str, Any] = {
        "n_pairs_total": len(pairs), "n_unlinked": un, "n_evaluable": n_all,
        "n_with_patent": len(hit),
        "rate": round(len(hit) / n_all, 4) if n_all else None,
        "ci": S.wilson(len(hit), n_all) if n_all else None,
    }
    # ② TP vs TN — **유의하면 시점 누출로 읽는다**(명세 §3-②)
    tp = [x for x in ev if x[2] == "TP"]
    tn = [x for x in ev if x[2] == "TN"]
    a = sum(1 for x in tp if x[3] > 0)
    b = sum(1 for x in tn if x[3] > 0)
    out["tp"] = {"n": len(tp), "hit": a,
                 "rate": round(a / len(tp), 4) if tp else None}
    out["tn"] = {"n": len(tn), "hit": b,
                 "rate": round(b / len(tn), 4) if tn else None}
    out["fisher_p"] = (S.fisher(a, len(tp) - a, b, len(tn) - b)
                       if tp and tn else None)
    # 문턱 판정 — **명세에 적힌 그대로. 여기서 안 고친다**
    r = out["rate"]
    out["판정"] = ("측정 불가" if r is None else
                  "가른다" if r <= 0.60 else
                  "접는다" if r > 0.90 else "애매 — 쓸 수 있다고 안 적는다")
    counts = sorted((x[3] for x in hit), reverse=True)
    if counts:
        out["median"] = counts[len(counts) // 2]
        out["max"] = counts[0]
        out["top"] = [(x[0], x[1], x[3]) for x in
                      sorted(hit, key=lambda y: -y[3])[:10]]
    return out


def report_use(s: Dict[str, Any], log=print) -> None:
    """④ 판정. **문턱은 명세에 있고 여기서 안 고친다.**"""
    log("")
    log("=" * 68)
    log("판정 — 명세 `사전명세_용도특허.md` (e22a4bf79036)")
    log("=" * 68)
    log("  쌍 %d개 중 **미연결 %d** (적응증을 못 이었다 — «0건»이 아니다)"
        % (s["n_pairs_total"], s["n_unlinked"]))
    log("  평가 가능 **%d쌍**" % s["n_evaluable"])
    if s["rate"] is None:
        log("  ⛔ **판정하지 않는다** — 평가 가능한 쌍이 없다")
        return
    ci = s.get("ci") or (None, None)
    log("")
    log("  ① 공동청구 특허 ≥1건  **%d / %d = %.1f%%**  [%.1f–%.1f]"
        % (s["n_with_patent"], s["n_evaluable"], 100 * s["rate"],
           100 * ci[0], 100 * ci[1]))
    log("     문턱: ≤60%% 가른다 · >90%% 접는다  →  **%s**" % s["판정"])
    log("     (앞 지표는 97.2% 였다)")
    tp, tn = s["tp"], s["tn"]
    log("")
    log("  ② TP vs TN — **유의하면 좋은 게 아니라 시점 누출이다**")
    log("     TP %d/%d = %s · TN %d/%d = %s"
        % (tp["hit"], tp["n"],
           "%.1f%%" % (100 * tp["rate"]) if tp["rate"] is not None else "—",
           tn["hit"], tn["n"],
           "%.1f%%" % (100 * tn["rate"]) if tn["rate"] is not None else "—"))
    p = s.get("fisher_p")
    if p is None:
        log("     Fisher: **못 잰다** — 한쪽이 비었다")
    else:
        log("     Fisher p = %.4f%s" % (p, "" if p >= 0.05 else
                                        "   ⚠ **누출 의심. 이 지표를 안 쓴다**"))
    if s.get("top"):
        log("")
        log("  건수 — 최대 %s · 중앙 %s" % (s["max"], s["median"]))
        log("  상위 (**여기에 또 원소·무기염이 오면 실패다**):")
        for d, i, n in s["top"][:6]:
            log("     %-26s %-30s %s" % (d[:26], i[:30], "{:,}".format(n)))
    log("")
    log("  **자유실시 판단이 아니다.** `field_id` 는 절 단위이지 청구항")
    log("  단위가 아니라 «같은 청구항에서 그 용도를 청구» 를 뜻하지 않는다.")


# ══════════════════════════════════════════════════════════════════
#  ④-b 공개연도 — 명세 `사전명세_용도특허_연도.md` (a0bb1f6b)
#
#  ## 왜 이게 08-14 에야 생겼나 (결함 216)
#
#  `build_index(patents=)` 가 **인자만 받고 안 썼다.** 08-13 에 5.9 G 를
#  받고 08-14 에 `--patents` CLI 를 배선했는데, **인자가 소비되는지는
#  안 봤다.** 색인을 12시간 다시 돌리고도 그 파일을 한 바이트도 안 읽었다.
#
#  > `CLAUDE.md §5` — «`--help` 통과는 검증이 아니다. 실제 경로를 태워라».
#  > 태우긴 했다. **결과 파일에 연도 칸이 생겼는지를 안 봤다.**
#
#  ## 무엇을 고치나
#
#  72.7% 에는 **만료 특허가 다 세어져 있다** — cisplatin(1978) ·
#  cyclophosphamide(1959) · doxorubicin(1974) 가 상위다. 자유실시 위험이
#  0 인 특허를 위험으로 센다. 그래서 «최근 20년» 창을 건다.
#
#  ## 그런데 그것만으로는 아무것도 안 보인다
#
#  **연도를 걸면 특허가 줄고 ①이 내려가는 것은 자명하다.** 그래서
#  명세가 ②′ **무작위 대조**를 같이 박아 뒀다 — 같은 수 K 개를 무작위로
#  남겼을 때의 분포와 비교한다. 하위 5% 밖이면 «표본을 줄인 효과» 일
#  뿐이고 **그러면 접는다.**
# ══════════════════════════════════════════════════════════════════

def _year_of(v: Any) -> Optional[int]:
    """`publication_date` 한 칸 → 연도. **모르면 `None`. 0 이 아니다.**

    스키마가 date32 인지 문자열인지 정수인지 **미리 정하지 않는다** —
    자료원이 바꿀 수 있고, 그때 조용히 틀린 연도를 내면 판정이 오염된다.
    """
    if v is None:
        return None
    y = getattr(v, "year", None)              # date · datetime · Timestamp
    if isinstance(y, int):
        return y if 1700 <= y <= 2100 else None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        if 1700 <= v <= 2100:
            return v                          # 연도 그 자체
        if 17000101 <= v <= 21001231:
            return v // 10000                 # YYYYMMDD
        return None
    s = str(v).strip()
    if len(s) >= 4 and s[:4].isdigit():
        n = int(s[:4])
        return n if 1700 <= n <= 2100 else None
    return None


def patent_years(patents: str, want: set, log=None,
                 max_row_groups: Optional[int] = None,
                 with_id: bool = False) -> Dict[str, Any]:
    """④-b — `patent_id` → **공개연도** (+ 선택적으로 **특허번호·국가**).

    ## 명세와의 관계 — **판정과 표시를 가른다**

    명세 `a0bb1f6b §1` 이 *«`patent_id` → 공개연도 하나. 출원인·번호는
    안 쓴다»* 라고 박았다. 그건 **그 명세의 판정(①·②′)에 안 쓴다**는
    뜻이고, 지금도 그렇다 — `year_signal` 은 연도만 본다.

    `with_id=True` 로 읽는 **번호·국가는 화면 표시 전용**이다. FTO 는
    애초에 판정 밖 층이라(§2.3 «G(FTO)는 판정 밖») 이 둘이 안 섞인다.

    **제목(`title`)은 안 읽는다** — 08-10 실측에서 우측 칸 247px 에
    제목 다섯 건이 340px 글벽이 됐다. `dash` 주석이 그때 적었다:
    *«전문은 특허 번호로 찾으면 된다 — 번호가 진짜 식별자다.»*
    """
    out: Dict[str, Any] = {"ok": False, "error": None, "years": {},
                           "ids": {}, "rows": 0, "n_want": len(want),
                           "n_found": 0, "n_no_date": 0, "n_no_id": 0,
                           "dtype": None, "scanned_all": False}
    st = parquet_state(patents, min_rows=1)
    if not st["ok"]:
        out["error"] = st["error"]
        return out
    if not st["read_ok"]:
        out["error"] = "**pyarrow 가 없다** — `py -m pip install pyarrow`"
        return out
    cols = st["columns"] or []
    for need in ("id", "publication_date"):
        if need not in cols:
            # **몰래 맞추지 않는다** — 명세 §1 이 그렇게 적었다
            out["error"] = ("`%s` 열이 없다 — 열: %s. **명세(a0bb1f6b §1)를 "
                            "고친 뒤 다시 봉인해라**" % (need, cols))
            return out
    take = ["id", "publication_date"]
    if with_id:
        # 표시용 두 열. **없으면 조용히 넘어가지 않는다** — 화면이
        # «번호 없음» 을 «특허 없음» 으로 보이게 하면 그게 결함 141 이다.
        for need in ("patent_number", "country"):
            if need not in cols:
                out["error"] = ("`%s` 열이 없다 — 열: %s. 표시용 열이 "
                                "바뀌었다" % (need, cols))
                return out
        take += ["patent_number", "country"]

    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    wp = pa.array(sorted(want), type=pa.int64())
    f = pq.ParquetFile(patents)
    ng = f.num_row_groups if max_row_groups is None else min(
        max_row_groups, f.num_row_groups)
    years: Dict[int, int] = {}
    pids: Dict[int, str] = {}
    n_no = n_no_id = 0
    for g in range(ng):
        t = f.read_row_group(g, columns=take)
        if out["dtype"] is None:
            out["dtype"] = str(t.schema.field("publication_date").type)
        sel = t.filter(pc.is_in(t.column("id"), value_set=wp))
        if sel.num_rows:
            ids = sel.column("id").to_pylist()
            ds = sel.column("publication_date").to_pylist()
            nums = sel.column("patent_number").to_pylist() if with_id else None
            cts = sel.column("country").to_pylist() if with_id else None
            for k in range(len(ids)):
                i, d = ids[k], ds[k]
                y = _year_of(d)
                if y is None:
                    n_no += 1
                else:
                    years[i] = y
                if with_id:
                    num = (nums[k] or "").strip()
                    if not num:
                        n_no_id += 1        # **«없다» 를 «빈 문자열» 로 안 센다**
                    else:
                        ct = (cts[k] or "").strip()
                        pids[i] = (ct + num) if ct and not num.startswith(ct) else num
            out["rows"] += sel.num_rows
        if log and (g % 100 == 0 or g == ng - 1):
            log("  ④-b 행그룹 %4d/%d (%.1f%%) · 연도 %s%s"
                % (g + 1, ng, 100 * (g + 1) / ng, "{:,}".format(len(years)),
                   " · 번호 %s" % "{:,}".format(len(pids)) if with_id else ""))
    out["years"] = years
    out["ids"] = pids
    out["n_found"] = len(years)
    out["n_no_date"] = n_no
    out["n_no_id"] = n_no_id
    out["scanned_all"] = (ng == f.num_row_groups)
    out["ok"] = True
    return out


def year_signal(pairs: List[Tuple[str, str, str]],
                pair_patents: Dict[str, List[int]],
                years: Dict[int, int],
                matched_drugs: set, ind_hit: Dict[str, List[int]],
                run_year: int, windows: Tuple[int, ...] = (20, 15, 25),
                n_perm: int = 1000, seed: int = 20260813,
                log=None) -> Dict[str, Any]:
    """명세 `a0bb1f6b` 의 ①·②′·③ 을 **코드에서** 낸다.

    `use_signal` 을 **그대로 재사용**한다 — 미연결/평가가능/TP·TN 규약이
    한 곳에만 있어야 두 지표가 같은 분모를 쓴다(결함 141·144 계열).
    """
    import random

    uni = sorted({p for v in pair_patents.values() for p in v})
    n_uni = len(uni)
    # 평가 가능 쌍의 **특허 집합** — ②′ 가 이걸로 재계산한다
    md = {_dkey(x) for x in matched_drugs}
    ih = {_dkey(x) for x in ind_hit}
    ev_sets: List[set] = []
    for d, i, lab in pairs:
        if _dkey(d) not in md or _dkey(i) not in ih:
            continue
        ev_sets.append(set(pair_patents.get(pair_key(d, i), ())))

    out: Dict[str, Any] = {
        "명세": "사전명세_용도특허_연도.md · a0bb1f6b",
        "실행연도": run_year, "seed": seed, "n_perm": n_perm,
        "n_universe": n_uni, "n_evaluable_sets": len(ev_sets),
        "n_no_year": sum(1 for p in uni if p not in years),
        "창": {}, "주창": None, "②′": None,
    }

    for w in windows:
        cut = run_year - w
        keep = {p for p in uni if years.get(p) is not None and years[p] >= cut}
        hp = {k: sum(1 for p in v if p in keep)
              for k, v in pair_patents.items()}
        sig = use_signal(pairs, hp, matched_drugs, ind_hit)
        # ── 명세 §2-③ — **TP vs TN 을 여기서 검정하지 않는다** ──────
        #   앞 명세가 이미 쟀고(p=0.169), 못 읽는 것을 다시 재면
        #   다중비교만 는다. **값은 남기고 p 만 지운다.**
        sig["fisher_p"] = None
        sig["fisher_생략_이유"] = ("명세 §2-③ — 앞 명세 ②를 되풀이하지 "
                                "않는다. 결함 164(TP·TN 매칭률 91% vs 41%)로 "
                                "**비교군이 서로 닮게 걸러졌다**")
        out["창"][str(w)] = {"cutoff": cut, "K": len(keep),
                            "n_with_patent": sig["n_with_patent"],
                            "n_evaluable": sig["n_evaluable"],
                            "rate": sig["rate"], "ci": sig["ci"],
                            "판정": sig["판정"], "tp": sig["tp"],
                            "tn": sig["tn"], "median": sig.get("median"),
                            "max": sig.get("max"), "top": sig.get("top")}
        if w == windows[0]:
            out["주창"] = str(w)
            obs = sig["n_with_patent"]
            K = len(keep)

    # ── ②′ 무작위 대조 — **명세대로 K 개를 무작위로 남긴다** ─────────
    #
    #   초기하 근사로 대신하지 않는다. 명세가 «무작위로 K 개를 남기고 ①
    #   재계산 → 1,000회» 라고 절차까지 적어 뒀고, 그걸 바꾸면 사전명세가
    #   아니게 된다.
    rnd = random.Random(seed)
    dist: List[int] = []
    for t in range(n_perm):
        samp = set(rnd.sample(uni, K)) if 0 < K < n_uni else (
            set(uni) if K >= n_uni else set())
        dist.append(sum(1 for s in ev_sets if s and not s.isdisjoint(samp)))
        if log and (t + 1) % 200 == 0:
            log("  ②′ 무작위 %4d/%d" % (t + 1, n_perm))
    le = sum(1 for c in dist if c <= obs)
    p = (le + 1) / (n_perm + 1)               # **+1 보정.** p=0 을 안 낸다
    dist_s = sorted(dist)
    out["②′"] = {
        "K": K, "관측": obs, "n_perm": n_perm,
        "대조_중앙": dist_s[n_perm // 2],
        "대조_5퍼센타일": dist_s[max(0, int(0.05 * n_perm) - 1)],
        "대조_최소": dist_s[0], "대조_최대": dist_s[-1],
        "p": round(p, 5),
        # ── 다중비교 — 명세 §2 가 «Holm · m=2» 라 적었다 ─────────────
        #   그런데 **①은 문턱 판정이라 p 가 없다.** 검정은 실제로 ②′
        #   하나뿐이다. 명세를 낮춰 읽지 않으려고 **더 엄한 쪽**을 쓴다 —
        #   m=2 의 첫 문턱 0.05/2 = 0.025 를 ②′에 그대로 건다.
        "holm_m": 2, "holm_문턱": 0.025,
        "통과": bool(p <= 0.025),
        "판정": ("연도가 정보를 담는다" if p <= 0.025 else
               "무작위와 구별 안 된다 — 접는다 (명세 §6-1)"),
    }

    # ── 최종 — 명세 §7 표 그대로 ────────────────────────────────
    #
    #   ⚠ **문턱 숫자를 여기 다시 적지 않는다.** `use_signal` 이 이미
    #   ≤60% / >90% 로 `판정` 을 냈고, 그걸 여기서 또 쓰면 **두 곳이
    #   따로 흘러간다.** 결함 101(수치가 문서마다 갈라짐)과 같은 모양이라
    #   시험 [124]가 이 함수 본문에 `0.60`·`0.90` 이 없는지를 본다.
    main_w = out["창"][out["주창"]]
    v = main_w["판정"]
    ok2 = out["②′"]["통과"]
    #   그리고 **문구를 상수로 고정하지 않는다**(`CLAUDE.md §4`) —
    #   «미달» 과 «초과» 는 반대 방향인데 명세 §7 표가 둘을 한 칸에 묶어
    #   놨다. 방향은 `use_signal` 이 낸 판정에서 읽는다.
    #   ⚠ 08-14 — **명세 §7 표에 빈칸이 있었다.** 표는 ②′ 실패를
    #   «① ≤60% 인 경우» 에만 적었고, «① >60% **이면서** ②′ 실패» 칸이
    #   없다. 그런데 실측이 정확히 그 칸으로 왔다(① 72.1% · p=0.773).
    #
    #   그때 §6-1 이 위다 — *«②′가 무작위와 구별 안 되면 접는다»* 는
    #   조건 없이 적혀 있다. 그래서 **②′ 실패를 문구에 반드시 싣는다.**
    #
    #   이건 결과를 보고 기준을 바꾼 것이 아니다 — **문턱은 하나도 안
    #   건드렸고**, 고친 방향이 «우리에게 더 불리한 쪽»이다. 유리한 쪽으로
    #   고쳤으면 그게 §3-2 위반이다.
    if main_w["rate"] is None:
        out["§3.3-8"] = "측정 불가"
    elif not ok2:
        # **②′ 가 먼저다.** ①이 몇이든 «표본을 줄인 효과» 와 구별이 안 되면
        # 그 수치는 아무 뜻이 없다(명세 §6-1 반증조건 1).
        out["§3.3-8"] = ("🟡 유지 — **②′ 실패(p=%.3f). 연도가 정보를 안 담는다.**"
                         " 이 지표를 쓰지 않는다 (명세 §6-1)" % out["②′"]["p"])
    elif v == "가른다":
        out["§3.3-8"] = "✅ — 최근 %s년 내 공동청구로 가른다" % out["주창"]
    elif v == "접는다":
        out["§3.3-8"] = ("❌ 접는다 — ①이 상한을 **넘었다**. "
                         "연도를 걸어도 안 갈린다 (명세 §6-2)")
    else:
        out["§3.3-8"] = "🟡 유지 — ②′ 는 통과했으나 ①이 **애매 구간**이다"
    return out


def report_year(y: Dict[str, Any], base_rate: Optional[float] = None,
                log=print) -> None:
    """④-b 판정. **문턱은 명세에 있고 여기서 안 고친다.**"""
    log("")
    log("=" * 68)
    log("판정 — `사전명세_용도특허_연도.md` (a0bb1f6b)")
    log("=" * 68)
    log("  실행연도 %d · 공동청구 특허 %s개 · 그중 **연도 미상 %s개**"
        % (y["실행연도"], "{:,}".format(y["n_universe"]),
           "{:,}".format(y["n_no_year"])))
    if y["n_no_year"]:
        log("     ↳ 연도 미상은 «최근» 에 **안 넣는다** — 명세 ①이")
        log("       «공개연도가 X 이후인» 이라 적었고, 모르는 것은 그게 아니다")
    log("")
    w0 = y["주창"]
    for w, d in sorted(y["창"].items(), key=lambda x: -int(x[0])):
        mark = "①" if w == w0 else "부"
        ci = d["ci"] or (0, 0)
        log("  %s 최근 %2s년(≥%d) · 남은 특허 %9s · **%d/%d = %.1f%%** [%.1f–%.1f]"
            % (mark, w, d["cutoff"], "{:,}".format(d["K"]),
               d["n_with_patent"], d["n_evaluable"], 100 * (d["rate"] or 0),
               100 * ci[0], 100 * ci[1]))
        if w == w0:
            log("     문턱: ≤60%% 가른다 · >90%% 접는다  →  **%s**" % d["판정"])
    if base_rate is not None:
        log("")
        log("  **연도 없음 판(앞 명세)은 %.1f%% 였다. 지우지 않는다**(명세 §9)"
            % (100 * base_rate))
    t, n = y["창"][w0]["tp"], y["창"][w0]["tn"]
    log("")
    log("  ③ 층화 — **TP·TN 을 검정하지 않는다**(명세 §2-③)")
    log("     TP %d/%d = %s · TN %d/%d = %s"
        % (t["hit"], t["n"],
           "%.1f%%" % (100 * t["rate"]) if t["rate"] is not None else "—",
           n["hit"], n["n"],
           "%.1f%%" % (100 * n["rate"]) if n["rate"] is not None else "—"))
    p = y["②′"]
    log("")
    log("  ②′ 무작위 대조 — **이게 진짜 검정이다**")
    log("     같은 K=%s 개를 무작위로 %d회 남겼을 때"
        % ("{:,}".format(p["K"]), p["n_perm"]))
    log("     대조 분포  최소 %d · 5퍼센타일 %d · 중앙 %d · 최대 %d"
        % (p["대조_최소"], p["대조_5퍼센타일"], p["대조_중앙"], p["대조_최대"]))
    log("     관측 %d  →  **p = %.5f**  (Holm m=%d · 문턱 %.3f)"
        % (p["관측"], p["p"], p["holm_m"], p["holm_문턱"]))
    log("     → **%s**" % p["판정"])
    if y["창"][w0].get("top"):
        log("")
        log("  상위 — **1970년대 약이 빠졌나** (명세 §5 예측)")
        for d_, i_, n_ in y["창"][w0]["top"][:6]:
            log("     %-26s %-30s %s" % (d_[:26], i_[:30], "{:,}".format(n_)))
        log("  건수 — 최대 %s · 중앙 %s"
            % (y["창"][w0]["max"], y["창"][w0]["median"]))
    log("")
    log("  §3.3-8  →  **%s**" % y["§3.3-8"])
    log("")
    log("  ⚠ **여전히 자유실시 판단이 아니다.** 공개연도는 만료 시점의")
    log("     **대리 지표**이지 존속·포기·무효·국가별 지정을 모른다.")


USE_PAIRS = "fto_use_pairs.json"
YEARS_CACHE = "fto_years.json"
DRUG_PATENTS = "fto_drug_patents.json"      # 약물 → 특허 id (화면용 · 결함 218)

# 저장소 뿌리 — **화면은 cwd 가 어디일지 모른다.** CLI 는 cwd 에 쓰지만
# `dash` 는 gradio 가 띄우므로, 읽을 때 **cwd 와 뿌리를 둘 다 본다.**
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _find(name: str, root: Optional[str] = None) -> Optional[str]:
    """옆 파일을 찾는다 — cwd 먼저, 없으면 저장소 뿌리."""
    for base in ([root] if root else [os.getcwd(), ROOT]):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    return None


def _save_pairs(B: Dict[str, Any], path: str = USE_PAIRS) -> Optional[str]:
    """B단계 결과(쌍 → 특허 id)를 옆 파일로 남긴다. **덮어쓰지 않는다.**

    `CLAUDE.md §3-3`. 있으면 `.bak` 을 남기고 쓴다 — 이걸 잃으면 6.7 G 를
    다시 훑어야 한다(결함 216 이 정확히 그 값이었다).

    ## ⛔ 부분 실행은 **안 남긴다**

    `--rg N` 으로 시간을 재 보는 것은 정상인데, 그 결과가 옆 파일로 남으면
    **다음 실행이 그걸 전수로 착각한다.** 그러면 «연도 때문에 내려갔다» 를
    «덜 훑어서 내려갔다» 와 구별할 수 없다.

    안내문으로 막지 않는다 — **`scanned_all` 이 아니면 여기서 거절한다.**
    """
    if not B.get("scanned_all"):
        return None                          # **부분 실행. 안 남긴다**
    d = {"때": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
         "n_use_patents": B.get("n_use_patents"),
         "scanned_all": B.get("scanned_all"),
         "rows": B.get("rows"),
         "pair_patents": B.get("pair_patents") or {}}
    _write_json(d, path)                     # **`.bak` 은 거기서 남긴다**
    return path


def report_map(r: Dict[str, Any], log=print) -> None:
    """③ 결과를 찍는다. **색인 파일만으로도 다시 찍을 수 있다** — 15억 행을
    다시 훑지 않는다(결함 142를 고치고 재보고할 때 필요했다)."""
    m = r.get("map")
    if not (m and m.get("ok")):
        return
    n_drug = r["n_matched"]                       # **약 수.** cid 수가 아니다
    log("")
    log("=" * 68)
    log("③ 특허 연결 — **필드를 갈라 센다**")
    log("=" * 68)
    log("  훑은 행 %s / 맞은 행 %s%s"
        % ("{:,}".format(m["rows_seen"]), "{:,}".format(m["matched_rows"]),
           "" if m.get("scanned_all") else "   ⚠ **일부만 훑었다**"))
    log("")
    for k, v in sorted(m["by_field"].items(), key=lambda x: -x[1]):
        mark = "  ← **FTO 는 이것만 본다**" if k == FIELDS[FIELD_CLAIMS] else ""
        log("    %-8s %12s%s" % (k, "{:,}".format(v), mark))
    log("")
    hit, cl = m["n_drugs_hit"], m["n_drugs_with_claims"]
    log("  특허에 등장하는 약        %4d / %d  (%.1f%%)"
        % (hit, n_drug, 100 * hit / max(n_drug, 1)))
    log("  **청구항**에 등장하는 약   %4d / %d  (%.1f%%)"
        % (cl, n_drug, 100 * cl / max(n_drug, 1)))

    # ── **여기가 판정이다** ────────────────────────────────────────
    #   «수록됨» 이 아니라 «가르는가» 를 본다. 승인약이 거의 다 걸리면
    #   그 지표는 **아무도 못 거른다** — 있으나 마나다.
    if hit:
        share = cl / hit
        log("")
        if share >= 0.9:
            log("  ⚠ **등장하는 약의 %.0f%% 가 청구항에도 나온다.**" % (100 * share))
            log("     즉 «청구항 등장 여부» 는 **승인약을 거의 못 가른다.**")
            log("     이걸 게이트로 쓰면 전부 통과하거나 전부 걸린다 —")
            log("     **쓸 수 있는 신호는 여부가 아니라 건수의 분포**다.")
        else:
            log("  등장하는 약 중 청구항까지 가는 것은 %.0f%% 다 — 가른다."
                % (100 * share))

    # 건수 분포. **평균을 안 쓴다** — 아스피린 하나가 평균을 끌고 간다
    per = m.get("per_drug") or {}
    claims = sorted((v.get(FIELDS[FIELD_CLAIMS], 0) for v in per.values()),
                    reverse=True)
    claims = [c for c in claims if c > 0]
    if claims:
        def q(p):
            return claims[min(len(claims) - 1, int(len(claims) * p))]
        log("")
        log("  청구항 건수 분포 (약 %d종 · **중앙값을 본다**)" % len(claims))
        log("     최대 %s · 상위10%% %s · 중앙 %s · 하위10%% %s · 최소 %s"
            % tuple("{:,}".format(x) for x in
                    (claims[0], q(0.10), q(0.50), q(0.90), claims[-1])))
        top = sorted(per.items(),
                     key=lambda kv: -kv[1].get(FIELDS[FIELD_CLAIMS], 0))[:5]
        log("     상위: %s" % ", ".join(
            "%s %s" % (k, "{:,}".format(v.get(FIELDS[FIELD_CLAIMS], 0)))
            for k, v in top))
    # ── **버린 행을 먼저 적는다** (결함 146) ──────────────────────────
    gap = m.get("tally_gap")
    if gap:
        log("")
        log("  ⚠ **필드별 표가 맞은 행의 %.0f%%만 설명한다** — %s행이 상한에"
            % (100 * m["tally_sum"] / max(m["matched_rows"], 1),
               "{:,}".format(gap)))
        log("     걸려 빠졌다. **표의 합(%s) ≠ 맞은 행(%s).**"
            % ("{:,}".format(m["tally_sum"]), "{:,}".format(m["matched_rows"])))
        log("     즉 아래 순위는 **검열된 값 위에 서 있다.**")
    if m["capped"]:
        log("")
        log("  ⚠ 상한(%s행)에 걸린 약 **%d종** — 이들 수치는 **하한이고,**"
            % ("{:,}".format(MAP_CAP), len(m["capped"])))
        log("     **서로 비교할 수 없다**(전부 같은 천장에서 잘렸다)")
        log("     %s …" % ", ".join(m["capped"][:6]))
        _top = {d for d, _i, _n in (m.get("top") or [])} if m.get("top") else set()
        _both = sorted(set(m["capped"]) & {d for d in (m.get("per_drug") or {})}
                       & _top) if _top else []
        if _both:
            log("     ⚠ **상위 목록 중 %d개가 여기 있다**: %s"
                % (len(_both), ", ".join(_both[:5])))
    log("")
    log("  **필드별 합계를 «특허 N건» 이라 부르지 않는다** — 같은 특허가")
    log("  여러 필드에 나오면 중복된다. 그리고 **자유실시 판단이 아니다**:")
    log("  SureChEMBL 은 특허가 **살아 있는지**(존속·포기·무효)를 안 담는다.")


def _run_use_year(a) -> int:
    """④-b 실행부 — 명세 `a0bb1f6b`. **문턱·씨앗을 여기서 안 고친다.**"""
    print("=" * 68)
    print("④-b 용도특허 **공개연도** (명세 a0bb1f6b · 결함 216)")
    print("=" * 68)
    try:
        idx = json.load(open(a.out, encoding="utf-8"))
    except Exception as e:
        print("  ✗ 색인을 먼저 만들어라 — %s" % e)
        return 1
    cmap = idx.get("cid_map")
    if not cmap:
        print("  ✗ 색인에 `cid_map` 이 없다 — 구판이다")
        return 1
    cid2name = {int(k): v for k, v in cmap.items()}
    pairs = labeled_pairs()
    e = disease_entities(a.entities)
    if not e["ok"]:
        print("  ✗ %s" % e["error"])
        return 1
    m = match_indications(sorted({p[1] for p in pairs}), e)
    ent2ind: Dict[int, List[str]] = {}
    for ind, ids in m["hit"].items():
        for i in ids:
            ent2ind.setdefault(i, []).append(ind)
    matched = set(cid2name.values())

    # ── ① 쌍→특허 집합을 얻는다 — **옆 파일이 있으면 안 훑는다** ──────
    pp: Optional[Dict[str, List[int]]] = None
    if os.path.exists(USE_PAIRS) and not a.fresh_pairs:
        try:
            d = json.load(open(USE_PAIRS, encoding="utf-8"))
            pp = {k: list(v) for k, v in (d.get("pair_patents") or {}).items()}
            print("  옆 파일에서 읽었다 — %s · 쌍 %d · %s"
                  % (USE_PAIRS, len(pp), d.get("때", "?")))
            print("  (다시 훑으려면 `--fresh-pairs`)")
        except Exception as ex:
            print("  ⚠ 옆 파일을 못 읽었다(%s) — 다시 훑는다" % ex)
            pp = None
    if pp is None:
        print("  옆 파일이 없다 — **A·B 를 훑는다** (4.98 G + 1.71 G)")
        A = claim_patents(a.pmap or "surechembl_patent_compound_map.parquet",
                          cid2name, log=print, max_row_groups=a.rg)
        if not A["ok"]:
            print("  ✗ A단계 — %s" % A["error"])
            return 1
        if not A["n_patents"]:
            print("\n  ⛔ **판정하지 않는다** — A단계가 0건이다 (결함 149)")
            return 1
        # ── 약물 단위를 **여기서** 남긴다 (결함 218) ──────────────
        #   화면은 약물 하나를 받는다. 쌍에서 합치면 용도특허만 세어져
        #   벤치 수치와 어긋난다 — 그래서 A단계 결과를 그대로 쓴다.
        if A.get("scanned_all"):
            _write_json({"때": datetime.datetime.now().strftime(
                             "%Y-%m-%dT%H:%M:%S"),
                         "scanned_all": True,
                         "n_drugs": A.get("n_drugs_with_patents"),
                         "n_patents": A.get("n_patents"),
                         "by_drug": {k: sorted(v)
                                     for k, v in (A.get("by_drug") or {}).items()}},
                        DRUG_PATENTS)
            print("  약물 단위를 %s 로 남겼다 — 약 %s종 (화면이 이걸 읽는다)"
                  % (DRUG_PATENTS,
                     "{:,}".format(A.get("n_drugs_with_patents") or 0)))
        else:
            print("  ⚠ **부분 실행이라 약물 단위를 안 남긴다** (`--rg %s`)" % a.rg)
        B = use_patents(a.locations, A["by_patent"], ent2ind,
                        log=print, max_row_groups=a.rg)
        if not B["ok"]:
            print("  ✗ B단계 — %s" % B["error"])
            return 1
        if _save_pairs(B):
            print("  옆 파일로 남겼다 — %s (**이걸 잃으면 6.7 G 를 다시 훑는다**)"
                  % USE_PAIRS)
        else:
            print("  ⚠ **부분 실행이라 옆 파일을 안 남긴다** (`--rg %s`)" % a.rg)
        pp = B["pair_patents"]

    # ── ② **되풀이 검사** — 이 집합이 앞 지표를 재현하나 ──────────────
    #
    #   옆 파일이 다른 실행에서 왔을 수 있다. 재현이 안 되면 **연도를
    #   붙이기 전에 멈춘다** — 안 그러면 «연도 때문에 내려갔다» 를
    #   자료가 바뀐 것과 구별할 수 없다.
    base = ((idx.get("용도특허") or {}).get("신호") or {}).get("rate")
    chk = use_signal(pairs, {k: len(v) for k, v in pp.items()}, matched,
                     m["hit"])
    print("")
    print("  되풀이 검사 — 앞 판 %s vs 지금 %s"
          % ("%.4f" % base if base is not None else "없음",
             "%.4f" % chk["rate"] if chk["rate"] is not None else "없음"))
    if base is not None and chk["rate"] is not None and abs(base - chk["rate"]) > 1e-9:
        print("  ⛔ **재현이 안 된다. 여기서 멈춘다.**")
        print("     연도를 붙이기 전에 «무엇이 바뀌었나» 를 먼저 갈라라 —")
        print("     `--fresh-pairs` 로 다시 훑거나, 옆 파일의 출처를 확인해라.")
        return 1
    print("  ✅ 같다 — 연도만 붙이면 된다")

    # ── ③ 연도 ────────────────────────────────────────────────
    pt = a.patents or ("surechembl_patents.parquet"
                       if os.path.exists("surechembl_patents.parquet") else None)
    if not pt:
        print("\n  ✗ `surechembl_patents.parquet` 이 없다."
              " `--patents` 로 지정하거나 `.\\FTO받기.ps1` 로 받아라")
        return 1
    uni = {p for v in pp.values() for p in v}
    # ── 연도도 옆 파일로 남긴다 — **5.5 G 를 두 번 훑지 않으려고** ────
    #
    #   08-14 첫 실행이 이 조회에 15분을 썼다. 판정 문구 하나를 고치려고
    #   그걸 다시 훑는 것은 낭비이고, 낭비는 «그러면 안 돌려 보지 뭐» 로
    #   이어진다 — **다시 돌리기 싫게 만드는 것이 가장 나쁜 설계다.**
    Y = None
    if os.path.exists(YEARS_CACHE) and not a.fresh_pairs:
        try:
            d = json.load(open(YEARS_CACHE, encoding="utf-8"))
            ys = {int(k): v for k, v in (d.get("years") or {}).items()}
            ids = {int(k): v for k, v in (d.get("ids") or {}).items()}
            miss = len(uni - set(ys))
            # **번호가 없는 옛 판이면 다시 훑는다.** 「연도는 있으니 됐다」로
            # 넘어가면 화면이 또 번호 없이 돌고, 그게 결함 218 이다.
            if d.get("scanned_all") and miss == 0 and ids:
                print("\n  연도·번호를 옆 파일에서 읽었다 — %s · 연도 %s · 번호 %s · %s"
                      % (YEARS_CACHE, "{:,}".format(len(ys)),
                         "{:,}".format(len(ids)), d.get("때", "?")))
                Y = {"ok": True, "years": ys, "ids": ids, "n_want": len(uni),
                     "n_found": len(ys), "n_no_date": d.get("n_no_date", 0),
                     "n_no_id": d.get("n_no_id", 0),
                     "dtype": d.get("dtype"), "scanned_all": True, "rows": 0}
            elif d.get("scanned_all") and miss == 0:
                print("\n  ⚠ 옆 연도 파일에 **특허번호가 없다**(옛 판) — 다시 훑는다")
            else:
                # **덮지 않는다** — 못 채운 특허가 있으면 다시 훑는다.
                # 「일부만 있다」를 「다 있다」로 읽는 것이 결함 141 이다.
                print("\n  ⚠ 옆 연도 파일이 %s개를 못 덮는다 — 다시 훑는다"
                      % "{:,}".format(miss))
        except Exception as ex:
            print("\n  ⚠ 옆 연도 파일을 못 읽었다(%s) — 다시 훑는다" % ex)
    if Y is None:
        print("\n  공동청구 특허 %s개 → 공개연도 조회 (%s)"
              % ("{:,}".format(len(uni)), pt))
        Y = patent_years(pt, uni, log=print, max_row_groups=a.rg, with_id=True)
        if Y["ok"] and Y["scanned_all"]:
            _write_json({"때": datetime.datetime.now().strftime(
                             "%Y-%m-%dT%H:%M:%S"),
                         "scanned_all": True, "dtype": Y["dtype"],
                         "n_no_date": Y["n_no_date"], "n_no_id": Y["n_no_id"],
                         "years": {str(k): v for k, v in Y["years"].items()},
                         "ids": {str(k): v for k, v in Y["ids"].items()}},
                        YEARS_CACHE)
            print("  연도·번호를 %s 로 남겼다 — 다음부터 5.5 G 를 안 훑는다"
                  % YEARS_CACHE)
    if not Y["ok"]:
        print("  ✗ %s" % Y["error"])
        return 1
    print("  연도 얻음 %s개 · **날짜 없음 %s개** · 열 형 `%s` · 전수 %s"
          % ("{:,}".format(Y["n_found"]), "{:,}".format(Y["n_no_date"]),
             Y["dtype"], Y["scanned_all"]))

    run_year = datetime.date.today().year
    print("\n  ②′ 무작위 %d회 (seed=20260813) — 명세 §2" % a.perm)
    ysig = year_signal(pairs, pp, Y["years"], matched, m["hit"],
                       run_year=run_year, n_perm=a.perm, log=print)
    ysig["자료"] = {k: Y[k] for k in
                  ("n_want", "n_found", "n_no_date", "dtype", "scanned_all")}
    ysig["앞판_rate"] = base
    # ── ⛔ 부분 실행은 **색인에 안 넣는다** ─────────────────────────
    #
    #   `--rg N` 은 시간을 재 보는 출구다. 그 판정이 색인에 들어가면
    #   문서·화면이 그걸 **전수 결과로 읽는다.** 결함 141·149 와 같은
    #   모양 — «없다» 와 «덜 봤다» 를 안 가르면 판정이 오염된다.
    if a.rg or a.perm != 1000 or not Y["scanned_all"]:
        print("")
        print("  ⚠ **시험 실행이라 색인에 안 넣는다** — "
              "rg=%s · perm=%s · 전수=%s" % (a.rg, a.perm, Y["scanned_all"]))
        print("     명세 판정은 `--use-year` 를 옵션 없이 돌렸을 때만 남는다.")
        report_year(ysig, base_rate=base, log=print)
        return 0
    idx["용도특허_연도"] = ysig
    _save_index(idx, a.out)
    report_year(ysig, base_rate=base, log=print)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import sys
    try:                                   # PowerShell 은 cp949 다
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description="SureChEMBL 커버리지 게이트 (§3.3-8 · 결정 지점)")
    ap.add_argument("--compounds", default="surechembl_compounds.parquet")
    ap.add_argument("--map", dest="pmap", default=None,
                    help="patent_compound_map.parquet — **없으면 ②에서 멈춘다**")
    ap.add_argument("--patents", default=None,
                    help="patents.parquet — ④ **특허번호·공개일**. "
                         "없으면 번호 없이 건수만 (`build_index` §④)")
    ap.add_argument("--out", default=FTO_INDEX)
    ap.add_argument("--limit", type=int, default=None,
                    help="약 이름을 앞에서 N개만 (예행용)")
    ap.add_argument("--report", action="store_true",
                    help="**다시 안 훑는다.** 저장된 색인만 읽어 보고한다")
    ap.add_argument("--match-only", action="store_true",
                    help="**32 MB 만으로 관문을 잰다** — 적응증 매칭률")
    ap.add_argument("--entities",
                    default="surechembl_biomedical_entities.parquet")
    ap.add_argument("--use-year", action="store_true",
                    help="④-b **공개연도**를 붙여 명세 a0bb1f6b 를 이행한다. "
                         "`fto_use_pairs.json` 이 있으면 A·B 를 건너뛴다")
    ap.add_argument("--fresh-pairs", action="store_true",
                    help="--use-year 에서 옆 파일을 무시하고 A·B 를 다시 훑는다")
    ap.add_argument("--perm", type=int, default=1000,
                    help="②′ 무작위 반복 수. **명세 기본 1000 을 바꾸지 마라** "
                         "— 시험용 출구다")
    ap.add_argument("--use-patents", action="store_true",
                    help="④ **질환을 같이 건다** — 명세 `e22a4bf7…`")
    ap.add_argument("--locations",
                    default="surechembl_biomedical_locations.parquet")
    ap.add_argument("--rg", type=int, default=None,
                    help="행그룹 N개만 (예행용)")
    a = ap.parse_args(argv)

    if a.use_year:
        return _run_use_year(a)

    if a.use_patents:
        print("=" * 68)
        print("④ 용도특허 신호 — **화합물 ∩ 질환, 청구항** (명세 e22a4bf7…)")
        print("=" * 68)
        try:
            idx = json.load(open(a.out, encoding="utf-8"))
        except Exception as e:
            print("  ✗ 색인을 먼저 만들어라 (`py -m bioreroute.io.fto`) — %s" % e)
            return 1
        cmap = idx.get("cid_map")
        if not cmap:
            print("  ✗ 색인에 `cid_map` 이 없다 — **구판이다.**")
            print("    `py -m bioreroute.io.fto` 를 한 번 다시 돌려라"
                  " (InChIKey 는 캐시라 빠르다)")
            return 1
        cid2name = {int(k): v for k, v in cmap.items()}
        print("  화합물 %s개 → 약 %d종"
              % ("{:,}".format(len(cid2name)), len(set(cid2name.values()))))

        e = disease_entities(a.entities)
        if not e["ok"]:
            print("  ✗ %s" % e["error"])
            return 1
        pairs = labeled_pairs()
        m = match_indications(sorted({p[1] for p in pairs}), e)
        print("  적응증 %d개 → 매칭 %d (%.1f%%) · 규칙 %s"
              % (m["n"], m["n_hit"], 100 * m["rate"], m["per_rule"]))
        ent2ind: Dict[int, List[str]] = {}
        for ind, ids in m["hit"].items():
            for i in ids:
                ent2ind.setdefault(i, []).append(ind)

        A = claim_patents(a.pmap or "surechembl_patent_compound_map.parquet",
                          cid2name, log=print, max_row_groups=a.rg)
        if not A["ok"]:
            print("  ✗ A단계 — %s" % A["error"])
            return 1
        print("  A: 청구항에 우리 약이 있는 특허 **%s개** (행 %s)"
              % ("{:,}".format(A["n_patents"]), "{:,}".format(A["rows"])))
        if not A["n_patents"]:
            # **배관이 0건인데 rate=0.0 → «가른다» 로 통과하던 우회로**
            #   (결함 149). 적응증 매칭 실패는 «측정 불가» 로 막혀 있었는데
            #   A단계 실패는 그 방어를 비켜 갔다.
            print("\n  ⛔ **판정하지 않는다** — A단계가 0건이다.")
            print("     이건 «특허가 없다» 가 아니라 **«배관이 안 돌았다»** 다.")
            return 1

        B = use_patents(a.locations, A["by_patent"], ent2ind,
                        log=print, max_row_groups=a.rg)
        if not B["ok"]:
            print("  ✗ B단계 — %s" % B["error"])
            return 1
        print("  B: 그중 청구항에 우리 질환도 있는 특허 **%s개**"
              % "{:,}".format(B["n_use_patents"]))
        _save_pairs(B)          # 결함 216 — **집합을 버리지 않는다**
        print("     쌍→특허 집합을 %s 로 남겼다 (④-b 가 이걸 쓴다)" % USE_PAIRS)

        sig = use_signal(pairs, B["pairs"], set(cid2name.values()), m["hit"])
        idx["용도특허"] = {"신호": sig, "A": {k: A[k] for k in
                                        ("n_patents", "rows", "scanned_all")},
                        "B": {k: B[k] for k in
                              ("n_use_patents", "rows", "scanned_all")},
                        "매칭": {k: m[k] for k in ("n", "n_hit", "rate", "per_rule")},
                        "명세": "사전명세_용도특허.md · e22a4bf79036"}
        _save_index(idx, a.out)        # 결함 145 — 저장 경로는 **전부** 이걸 쓴다
        report_use(sig, print)
        return 0

    if a.match_only:
        # ── **1.6 G 를 받기 전에 될지부터 잰다** ──────────────────────
        #   매칭이 안 되면 그 뒤는 전부 «0건» 이 나오고, 그건 «특허가
        #   없다» 가 아니라 **«우리가 못 이었다»** 다. 결함 141 과 같은 모양.
        import csv as _csv
        print("=" * 68)
        print("④ 관문 — **적응증을 SureChEMBL 질환 엔티티에 이을 수 있나**")
        print("=" * 68)
        e = disease_entities(a.entities, log=None)
        if not e["ok"]:
            print("  ✗ %s" % e["error"])
            return 1
        print("  엔티티 %s행 중 **질환 %s개** · 이름 키 %s개"
              % ("{:,}".format(e["n_rows"]), "{:,}".format(e["n_disease"]),
                 "{:,}".format(len(e["by_name"]))))
        inds, seen = [], set()
        for fn in ("bench_matched.csv", "gen_matched.csv",
                   "bench_holdout_matched_dev.csv",
                   "bench_holdout_matched_sealed.csv"):
            if not os.path.exists(fn):
                continue
            for row in _csv.DictReader(open(fn, encoding="utf-8-sig")):
                v = (row.get("indication") or "").strip()
                if v and v.lower() not in seen:
                    seen.add(v.lower())
                    inds.append(v)
        # 엔티티가 **어떤 문자열을 담고 있는지** 먼저 보여 준다.
        #   `resolved_form` 이 MeSH **ID** 면 이름 매칭은 원문 쪽으로만
        #   되고, 그러면 도치 규칙이 먹을 자리가 다르다.
        _samp = sorted(e["by_name"])[:6]
        print("  이름 키 예시: %s" % ", ".join(_samp))

        m = match_indications(inds, e)
        print("\n  우리 적응증 %d개 → **매칭 %d개 (%.1f%%)**"
              % (m["n"], m["n_hit"], 100 * m["rate"]))
        print("     규칙별: %s   (주 분석 = %s)"
              % (" · ".join("%s %d" % kv for kv in
                            sorted(m["per_rule"].items(), key=lambda x: -x[1]))
                 or "없음", "+".join(m["rules"])))
        # **절단은 안 쓴다.** 얼마나 더 붙는지만 보고한다 — 넓히는 규칙이라
        #   주 분석에 넣으면 «다른 질문에 답한 것» 이 된다.
        m3 = match_indications(inds, e, rules=("정확", "도치", "절단"))
        print("     ⓘ `절단` 까지 허용하면 %d개(%.1f%%) 지만 **안 쓴다** —"
              % (m3["n_hit"], 100 * m3["rate"]))
        print("       `A, B`→`A` 는 **더 넓은 개념**이라 특허가 과대해진다."
              " 민감도 분석에서만")
        print("  못 맞춘 예: %s" % ", ".join(m["miss_examples"][:6]))
        print()
        if m["rate"] >= 0.5:
            print("  **관문 통과.** 1.6 G 를 받을 값이 있다.")
        else:
            print("  ⚠ **관문 미달(50% 문턱).** 여기서 «특허 0건» 이 나와도")
            print("     그건 «없다» 가 아니라 **«못 이었다»** 다 — 결함 141 과")
            print("     같은 모양이다. 받기 전에 이름 맞추기를 먼저 봐라.")
        return 0

    if a.report:
        # 결함 142를 고치고 **15억 행을 다시 훑을 이유가 없다.**
        try:
            r = json.load(open(a.out, encoding="utf-8"))
        except Exception as e:
            print("색인을 못 읽었다 — %s: %s" % (type(e).__name__, e))
            return 1
        cids = r.get("n_matched_cids")
        if cids is None and r.get("map"):
            # 구판 색인: `n_matched` 가 **화합물 레코드 수**였다(결함 142).
            #   약 수는 `per_drug` 의 길이가 정본이다.
            per = r["map"].get("per_drug") or {}
            r["n_matched_cids"] = r.get("n_matched")
            r["n_matched"] = len(per)
            r["coverage"] = (round(r["n_matched"] / r["n_inchikey"], 4)
                             if r.get("n_inchikey") else 0.0)
            print("  ⚠ **구판 색인이다.** `n_matched` 가 화합물 레코드 수였고")
            print("    약 수(%d)로 고쳐 읽었다 — 결함 142" % r["n_matched"])
        print("  약 %d → InChIKey %d → **적중 %d (커버리지 %.1f%%)**"
              % (r["n_drugs"], r["n_inchikey"], r["n_matched"],
                 100 * r["coverage"]))
        report_map(r, print)
        return 0

    print("=" * 68)
    print("SureChEMBL 커버리지 — **이 수치로 나머지 9.6G 를 받을지 정한다**")
    print("=" * 68)
    st = parquet_state(a.compounds)
    if not st["ok"]:
        print("  ✗ %s" % st["error"])
        return 1
    print("  compounds  %.2f GB · %s행 · 열 %s%s"
          % (st["size_mb"] / 1000, "{:,}".format(st["rows"]),
             st["columns"], "" if st["read_ok"] else "  ⚠ pyarrow 없음"))
    if not st["read_ok"]:
        print("\n  **자료를 읽으려면 pyarrow 가 필요하다** — `py -m pip install pyarrow`")
        return 1
    if st["rows"] != SC_ROWS_20260804:
        print("  ⚠ 행 수가 우리가 실측한 판(%s)과 다르다 — **판이 바뀌었다.**"
              % "{:,}".format(SC_ROWS_20260804))
        print("    2주마다 새로 올라오고 «스키마가 바뀔 수 있다» 고 공지돼 있다")

    ds = our_drugs()
    if a.limit:
        ds = ds[:a.limit]
    print("\n  우리 약 %d종 → InChIKey 조회 (PubChem · 캐시)" % len(ds))
    # **CLI 에 `--patents` 가 없어서** 5.5G 를 받아도 못 넘겼다(08-13).
    # `build_index` 는 08-12부터 `patents=` 를 받고 있었는데 배선이 빠졌다.
    _pt = a.patents
    if _pt is None and os.path.exists("surechembl_patents.parquet"):
        _pt = "surechembl_patents.parquet"      # 있으면 **알아서 쓴다**
    r = build_index(a.compounds, pmap=a.pmap, patents=_pt, out_path=a.out,
                    drugs=ds, log=print)
    print("-" * 68)
    if not r["ok"]:
        print("  ✗ %s" % (r.get("error") or "알 수 없는 실패"))
        return 1

    n_key = r["n_inchikey"]
    got = r.get("n_got_key", n_key)
    print("깔때기 — **세 손실을 갈라 센다** (결함 35)")
    print("  약 이름            %5d" % r["n_drugs"])
    print("  → InChIKey 얻은 약  %5d  (%.1f%%)   ← 이 셋의 합이 위와 같다"
          % (got, 100 * got / max(r["n_drugs"], 1)))
    if r.get("n_dup_key"):
        print("     그중 **같은 키를 낸 중복 %d종** → 고유 InChIKey %d개"
              % (r["n_dup_key"], n_key))
    print("     PubChem 에 없음  %5d   ← 이름이 «10 mg TZP-102» 같은 것들이다"
          % r["n_not_in_pubchem"])
    print("     조회 실패        %5d   ← **«없다» 가 아니다. 다시 돌리면 준다**"
          % r["n_lookup_failed"])
    print("  → SureChEMBL 적중  %5d  (**커버리지 %.1f%%**)"
          % (r["n_matched"], 100 * r["coverage"]))
    print("     (화합물 레코드로는 %d개 — **한 약이 여러 id 에 걸린다.**"
          % r.get("n_matched_cids", r["n_matched"]))
    print("      그걸 분자로 쓰면 100%% 를 넘는다. 결함 142)")
    print()
    if r["coverage"] >= 0.8:
        print("  **높다.** 나머지 9.6 G 를 받을 값이 있다.")
        print("  다만 «수록됨» 은 승인약이면 거의 다 그럴 것이다 —")
        print("  **판별력이 있는지는 특허 건수를 봐야 안다**(map 필요).")
    elif r["coverage"] >= 0.5:
        print("  **중간이다.** 어느 쪽이 빠졌는지 먼저 봐라 — 이름 문제인지")
        print("  자료 문제인지 가르지 않으면 다음 결정이 근거 없이 된다.")
    else:
        print("  **낮다.** 여기서 멈추는 것을 진지하게 보라.")
        print("  InChIKey 를 얻고도 안 맞았다면 **우리 열쇠가 틀렸을** 수 있다.")
    report_map(r, print)
    print("\n  색인 → %s" % a.out)
    if not a.pmap:
        print("  ③ 특허 연결은 `--map surechembl_patent_compound_map.parquet` 로.")
    return 0




# ⚠ 이 문구는 **화면에 그대로 나간다.** 굵게를 최소로 둔다 —
#   `화면진단_0818 §②`: 경고가 잦으면 사람이 경고를 안 읽는다(결함 126).
LIMITS_SC = ("검색한 자료(SureChEMBL)는 특허 본문에 그 화합물이 나오는가만 "
             "담습니다. 그 특허가 살아 있는지(존속기간·포기·무효)는 담지 "
             "않고 청구항도 읽지 않으므로, 여기서 나오는 것은 "
             "«관련 특허 N건이 검색됨»이지 자유실시 판단이 아닙니다. "
             "2주마다 갱신되지만 출원 후 18개월은 원리적으로 미공개입니다.")


_BY_DRUG: Dict[str, Any] = {}          # 경로 → {정규화된 약이름: 항목}


def _by_drug(path: str) -> Dict[str, Any]:
    """색인을 **한 번만 읽어** 정규화 키로 들고 있는다 — 결함 251.

    08-18 실측: `local_check` 한 번이 **28~35초**다. `fto_drug_patents.json`
    이 **69 MB** 이고 **호출마다 통째로 파싱**했다. 게다가 그 뒤에
    `for k, v in by.items()` 로 **771종을 선형 탐색**했다.

    그래서 **대시보드에서 후보를 클릭할 때마다 30초씩 멈췄다.**
    시연 4부가 3분인데 클릭 한 번이 30초다 — 아무도 안 재 봤다.

    파일 수정 시각이 바뀌면 다시 읽는다. **그래야 색인을 새로 만든 뒤
    옛 값이 남지 않는다**(결함 62 가 그 형태였다).

    갱신은 **`clear()` 뒤 재대입이 아니라 한 칸 통째 대입**이다. 나눠 쓰면
    두 스레드 사이에서 «태그는 맞는데 값이 아직 없는» 순간이 생긴다 —
    Gradio 는 이벤트를 동시에 처리한다. **안내문이 아니라 구조로 막는다.**
    """
    st = os.stat(path)
    tag = (path, st.st_mtime_ns, st.st_size)
    v = _BY_DRUG.get("_v")               # **한 칸에 통째로** — 아래 주석
    if v is not None and v[0] == tag:
        return v[1]
    d = json.load(open(path, encoding="utf-8"))
    m = {_dkey(k): v2 for k, v2 in (d.get("by_drug") or {}).items()}
    _BY_DRUG["_v"] = (tag, m)
    return m


_YEARS: Dict[str, Any] = {}            # 연도 색인(23 MB)도 같은 이유로 한 번만


def _years_ids(path: str):
    """`fto_years.json` 을 한 번만 읽는다 — `_by_drug` 과 같은 이유다."""
    st = os.stat(path)
    tag = (path, st.st_mtime_ns, st.st_size)
    v = _YEARS.get("_v")
    if v is not None and v[0] == tag:
        return v[1], v[2]
    yd = json.load(open(path, encoding="utf-8"))
    y = {int(k): x for k, x in (yd.get("years") or {}).items()}
    i = {int(k): x for k, x in (yd.get("ids") or {}).items()}
    _YEARS["_v"] = (tag, y, i)
    return y, i


def local_check(drug: str, root: Optional[str] = None) -> Dict[str, Any]:
    """약물명 → **우리가 훑은 SureChEMBL 색인**에서 특허 신호. 망 안 씀.

    ## 왜 이게 필요했나 (결함 218)

    화면(`dash.right_patent`)이 `check()` 를 부르는데 그건 **PatentsView
    API** 경로다. 그 API 는 2026-03-20 에 중단됐고 키를 못 받는다
    (결함 95). 그래서 화면은 **늘 «확인불가»** 를 찍었다.

    그 사이 우리는 SureChEMBL 벌크 **11.6 GB** 를 훑어 색인을 만들었다.
    **그게 화면에 한 줄도 안 나왔다.** 두 경로가 이름만 같고 따로 놀았다.

    > `계획_8월` 범위표가 *«약물 → 관련 특허 문서 **조회·제시**»* 라고
    > 적었다. 조회는 됐고 **제시가 비어 있었다.**

    ## 무엇을 말하고 무엇을 안 말하나

        말한다      «청구항에 이 약이 나오는 특허 N건» · 특허번호 · 공개연도
        안 말한다   자유실시 여부 · 청구항 해석 · 침해 · 존속 여부

    **`개발가능` 라벨을 안 낸다.** 만료를 못 가르기 때문이다 — 08-14 에
    공개연도로 시도했고 **무작위와 구별이 안 됐다**(p=0.773 · `FTO연도결과.md`).
    라벨이 둘뿐이다: `특허검색됨` · `확인불가`.
    """
    out: Dict[str, Any] = {"drug": (drug or "").strip(), "label": "확인불가",
                           "why": "", "patents": [], "n_patents": None,
                           "n_recent": None, "출처": "SureChEMBL 벌크(로컬 색인)",
                           "한계": LIMITS_SC, "error": None}
    if not out["drug"]:
        out["why"] = "약물명 없음"
        return out
    dp = _find(DRUG_PATENTS, root)
    if not dp:
        # **«없다» 가 아니라 «안 만들었다» 라고 말한다** (결함 141 계열)
        out["why"] = ("로컬 특허 색인이 없다 — `.\\연도.ps1` 로 만든다. "
                      "**확인불가는 «특허 없음» 이 아니다**")
        return out
    try:
        by = _by_drug(dp)
    except Exception as e:
        out["error"] = str(e)
        out["why"] = "로컬 색인을 못 읽었다: %s" % e
        return out
    hit = by.get(_dkey(out["drug"]))
    if hit is None:
        out["label"] = "확인불가"
        out["why"] = ("이 약이 **SureChEMBL 색인에 없다.** 이름이 안 맞거나"
                      "(개발 코드명 등) 자료원에 수록이 안 된 것이다 — "
                      "**«특허가 없다» 가 아니다**")
        return out
    years, ids = {}, {}
    yp = _find(YEARS_CACHE, root)
    if yp:
        try:
            years, ids = _years_ids(yp)
        except Exception:
            pass
    cut = datetime.date.today().year - 20
    recent = [p for p in hit if years.get(p) is not None and years[p] >= cut]
    out["label"] = "특허검색됨"
    out["n_patents"] = len(hit)
    out["n_recent"] = len(recent) if years else None
    out["why"] = ("청구항에 이 약이 나오는 특허 **%s건**%s. "
                  "**자유실시 여부는 판단하지 않는다.**"
                  % ("{:,}".format(len(hit)),
                     " (그중 최근 20년 %s건)" % "{:,}".format(len(recent))
                     if years else " · 공개연도 미조회"))
    # 화면에 실을 것 — **최근 공개 순 5건.** 순위가 아니라 정렬이다
    show = sorted((p for p in hit if p in ids),
                  key=lambda p: (-(years.get(p) or 0), ids[p]))[:5]
    out["patents"] = [{"id": ids[p], "date": years.get(p)} for p in show]
    # ── 국가 분포 — **정렬 아티팩트를 그대로 두지 않는다** (08-14) ──────
    #
    #   정렬이 `(-연도, 번호)` 라 같은 해 안에서는 **번호 알파벳 순**이다.
    #   `CN-` 이 앞이라 실측에서 **다섯 건이 전부 중국 특허**로 나왔다.
    #   그걸 그대로 보이면 화면이 **자료가 아니라 정렬을 보여주는 것**이고,
    #   심사위원이 «왜 전부 중국인가요» 라고 물으면 답이 «알파벳 순» 이다.
    #
    #   순서를 자의적으로 섞지 않는다 — 대신 **분포를 같이 찍어** 다섯 건이
    #   대표 표본이 아니라는 것을 화면이 스스로 말하게 한다.
    from collections import Counter as _C
    cc = _C(str(ids[p]).split("-")[0][:2] for p in hit if p in ids)
    out["국가"] = cc.most_common(4)
    out["n_번호있음"] = sum(cc.values())
    if hit and not out["patents"]:
        out["why"] += " (번호를 아직 안 붙였다 — `.\\연도.ps1` 재실행)"
    return out


def check(drug: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    """약물명 → 특허 신호. **점수가 아니라 라벨이다.**

      개발가능  : 20년 안쪽 등록특허가 안 보인다
      특허생존  : 살아 있을 수 있는 등록특허가 보인다
      확인불가  : 조회 실패 · 키 없음 — **개발가능으로 읽으면 안 된다**
    """
    import os
    key = api_key or os.environ.get("PATENTSVIEW_API_KEY", "")
    d = (drug or "").strip()
    out = {"drug": d, "label": "확인불가", "why": "", "patents": [],
           "한계": LIMITS, "error": None}
    if not d:
        out["why"] = "약물명 없음"
        return out
    if not key:
        # **키를 구할 수 없다는 사실까지 말한다** (결함 95). "키 없음" 만
        # 적으면 *"넣으면 되는데 안 넣었다"* 로 읽힌다 — 사실은 발급처가
        # 2026-03-20 에 중단됐다. 못 한 것과 안 한 것은 다르다.
        out["why"] = (
            "PatentsView API 키 없음(PATENTSVIEW_API_KEY). **확인불가는 "
            "개발가능이 아니다.** 그리고 **2026-03-20 부터 PatentsView 의 "
            "search·API 가 USPTO ODP 전환으로 중단됐다** — 키를 새로 발급받을 "
            "수 없다. 특허 층은 **로드맵**이다")
        return out

    ck = "FTO::%s" % d.lower()
    if cache.has(ck):
        return cache.get(ck)

    cutoff = (datetime.date.today()
              - datetime.timedelta(days=365 * TERM_YEARS)).isoformat()
    q = {"_and": [{"_text_any": {"patent_title": d}},
                  {"_gte": {"patent_date": cutoff}}]}
    url = PV + "?" + urllib.parse.urlencode({
        "q": json.dumps(q),
        "f": json.dumps(["patent_id", "patent_title", "patent_date"]),
        "o": json.dumps({"size": 10})})
    try:
        r = _get(url, key)
        pats = r.get("patents") or []
        out["patents"] = [{"id": p.get("patent_id"),
                           "title": (p.get("patent_title") or "")[:90],
                           "date": p.get("patent_date")} for p in pats]
        if pats:
            out["label"] = "특허생존"
            out["why"] = ("%d년 이내 등록특허 %d건 — 청구항 확인 필요"
                          % (TERM_YEARS, r.get("total_hits") or len(pats)))
        else:
            out["label"] = "개발가능"
            out["why"] = "%s 이후 등록된 관련 특허가 검색되지 않았다" % cutoff
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
        out["why"] = "조회 실패 — **개발가능이 아니다**"
        return out            # 실패는 캐시하지 않는다 (결함 37)
    return cache.put(ck, out)


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
