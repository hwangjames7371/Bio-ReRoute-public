# -*- coding: utf-8 -*-
"""DRKG 다중홉 그래프 검색 (제안서 §2.1 · §3.3-6)

  > 정방향 발굴의 A–B–C 연결은 본질적으로 다단계 그래프 추론이므로,
  > 벡터 검색 대신 기존 오픈 재창출 지식그래프(DRKG, 약 9.7만 노드·
  > 587만 관계)를 그래프 검색으로 조회해 다중홉 후보를 찾는다.
  > **다만 지식그래프의 관계는 검증된 근거가 아니라 주장이다.**
  > 따라서 그래프가 제안한 연결은 그대로 신뢰하지 않고 F0 근거 실재성
  > 게이트와 회의주의 에이전트를 통과시켜, **그래프 스스로가 만든
  > 그럴듯한 오답까지 반증한다.**

마지막 문장이 이 모듈의 위치를 정한다. **DRKG는 생성기다.** 우리 논지는
생성이 병목이 아니라는 것이므로, DRKG를 붙이는 목적은 후보를 늘리는 것이
아니라 **다른 생성기가 내는 오답도 같은 깔때기로 걸리는지 보는 것**이다.

## 지금 상태 — **로드맵이다. 그리고 그 말이 핑계가 되지 않게 적는다**

제안서 §2.1 이 DRKG 다중홉·GraphRAG 를 **로드맵**으로 적었다. 자료를
받지 않았으므로 `multihop()` 은 실행된 적이 없다.

초판 독스트링이 *"`bench/graph.py` 가 그걸 잰다"* 고 적어 뒀는데
**그 파일은 없다.** 계획을 현재형으로 쓴 것이고, 그런 문장이 쌓이면
문서가 코드보다 앞서 나간다(결함 41과 같은 계열). 지웠다.

그리고 이 모듈은 **그동안 줄곧 아무도 안 불렀다** — `preflight` 렌즈 3이
매번 잡았고 매번 넘겼다. 지금은 `netcheck` 이 `available()` 을 불러
**화면에 `없음` 을 찍는다.** 조용한 부재가 결함 35의 원인이었다.

## 자료

    https://dgl-data.s3-us-west-2.amazonaws.com/dataset/DRKG/drkg.tar.gz

풀면 `drkg.tsv` 한 장이고 `head <TAB> relation <TAB> tail` 이다.
노드 이름은 `Compound::DB00331` · `Gene::5290` · `Disease::MESH:D003924` 형태다.

**받지 않았으면 받지 않았다고 말하고 멈춘다.** 없는 걸 추정으로 채우면
그래프 검색이 아니라 LLM 이 한 번 더 도는 것이다.

## 라이선스 — 먼저 읽어라

DRKG 는 DrugBank 유래 관계를 포함하며 그 부분은 **CC BY-NC** 다.
경진대회·연구 용도는 비영리라 해당하지만, **상업 배포 시에는 별도
라이선스가 필요하다**(`투명성_연구윤리.md` §7).
"""

import gzip
import os
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

DRKG_PATH = os.environ.get("BIOREROUTE_DRKG", "drkg.tsv")

# A–B–C 다중홉에서 쓸 관계만 고른다. 전부 쓰면 587만 개가 다 이어져
# **아무 후보나 나온다** — 연결이 흔하면 정보가 아니다.
GENE_REL = ("Gene", )
CPD, GENE, DIS = "Compound", "Gene", "Disease"


# 공식 배포본의 관계 수. **줄 수를 안 세면 잘린 파일이 「있다」로 읽힌다.**
#   08-11 실측: 압축 해제가 중간에 끊겨 **167만 줄 · 132MB** 짜리가 남았는데
#   `available()` 이 크기만 보고 `ok=True` 를 냈다. 그대로 다중홉을 돌렸으면
#   **자료의 3/4 가 없는 채로 «연결이 없다»** 라고 답했을 것이다 —
#   결함 35(조회 실패를 0건으로 셈)와 **같은 고장**이다(결함 116).
#
#   정확히 일치를 요구하지 않는다. 판이 바뀔 수 있으므로 **하한만** 본다.
DRKG_ROWS = 5_874_261
_MIN_ROWS = 5_000_000
_MIN_MB = 300


def available(deep: bool = False) -> Dict[str, Any]:
    """DRKG 파일이 있는가 — 그리고 **온전한가**.

    `deep=True` 면 줄까지 센다(587만 줄 · 수 초). 기본은 크기만 보고
    **의심스러우면 그렇다고 적는다** — 조용히 통과시키지 않는다.
    """
    p = DRKG_PATH
    if not os.path.exists(p):
        return {"ok": False, "path": p, "size_mb": None, "rows": None,
                "error": "DRKG 파일 없음: %s — dgl-data S3 에서 "
                         "drkg.tar.gz 를 받아라" % p}
    mb = round(os.path.getsize(p) / 1e6, 1)
    rows = None
    if deep:
        with _open(p) as f:
            rows = sum(1 for _ in f)
    small = mb < _MIN_MB and not p.endswith(".gz")
    short = rows is not None and rows < _MIN_ROWS
    if small or short:
        return {"ok": False, "path": p, "size_mb": mb, "rows": rows,
                "error": ("**파일이 잘렸다** — %s MB%s. 온전한 판은 약 %d만 줄이다. "
                          "압축을 다시 풀어라"
                          % (mb, (" · %d줄" % rows) if rows else "",
                             DRKG_ROWS // 10000))}
    return {"ok": True, "path": p, "size_mb": mb, "rows": rows, "error": None}


def _open(p: str):
    return gzip.open(p, "rt", encoding="utf-8") if p.endswith(".gz") \
        else open(p, encoding="utf-8")


def _kind(node: str) -> str:
    return node.split("::", 1)[0] if "::" in node else ""


def load(path: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """DRKG → 인접표 두 장. 필요한 두 종류만 들고 있는다.

    587만 줄을 통째로 dict 에 넣으면 메모리가 몇 GB 로 뜬다.
    **Compound–Gene 과 Gene–Disease 만** 남긴다. 그 둘이 A–B–C 다.
    """
    p = path or DRKG_PATH
    av = available() if p == DRKG_PATH else {"ok": os.path.exists(p), "path": p}
    if not av.get("ok"):
        return {"ok": False, "error": av.get("error") or ("없음: " + p)}

    cg: Dict[str, Set[str]] = defaultdict(set)     # compound → genes
    gc: Dict[str, Set[str]] = defaultdict(set)     # gene → compounds
    gd: Dict[str, Set[str]] = defaultdict(set)     # gene → diseases
    dg: Dict[str, Set[str]] = defaultdict(set)     # disease → genes
    cd: Dict[str, Set[str]] = defaultdict(set)     # compound → diseases (이미 알려진 것)
    n = 0
    with _open(p) as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 3:
                continue
            h, _r, t = parts
            kh, kt = _kind(h), _kind(t)
            if {kh, kt} == {CPD, GENE}:
                c, g = (h, t) if kh == CPD else (t, h)
                cg[c].add(g)
                gc[g].add(c)
            elif {kh, kt} == {GENE, DIS}:
                g, d = (h, t) if kh == GENE else (t, h)
                gd[g].add(d)
                dg[d].add(g)
            elif {kh, kt} == {CPD, DIS}:
                c, d = (h, t) if kh == CPD else (t, h)
                cd[c].add(d)
            n += 1
            if limit and n >= limit:
                break
    return {"ok": True, "lines": n, "cg": cg, "gc": gc, "gd": gd, "dg": dg,
            "cd": cd, "path": p}


def multihop(graph: Dict[str, Any], disease: str, k: int = 20,
             min_shared: int = 2) -> Dict[str, Any]:
    """질환 → 유전자 → 화합물. **이미 알려진 직접 연결은 뺀다.**

    `min_shared` 는 공유 유전자 수 문턱이다. 1로 두면 흔한 유전자
    (TNF·IL6 같은 허브) 하나만 걸쳐도 후보가 되어 **수천 개가 나온다.**
    허브를 통한 연결은 정보가 아니다.
    """
    out = {"ok": False, "disease": disease, "items": [], "error": None,
           "min_shared": min_shared}
    if not graph.get("ok"):
        out["error"] = graph.get("error") or "그래프 미적재"
        return out
    genes = graph["dg"].get(disease) or set()
    if not genes:
        out["error"] = "그래프에 그 질환 노드가 없다: %s" % disease
        return out

    known = {c for c, ds in graph["cd"].items() if disease in ds}
    score: Dict[str, Set[str]] = defaultdict(set)
    for g in genes:
        for c in graph["gc"].get(g, ()):
            if c in known:                 # 이미 알려진 적응증은 발굴이 아니다
                continue
            score[c].add(g)

    rows = [{"compound": c, "shared_genes": len(gs), "via": sorted(gs)[:5]}
            for c, gs in score.items() if len(gs) >= min_shared]
    rows.sort(key=lambda r: -r["shared_genes"])
    out["items"] = rows[:k]
    out["n_candidates_total"] = len(rows)
    out["n_disease_genes"] = len(genes)
    out["n_known_excluded"] = len(known)
    out["ok"] = True
    out["hub_warning"] = HUB_WARNING
    out["caveat"] = ("DRKG 관계는 **검증된 근거가 아니라 주장**이다. "
                     "여기 나온 것은 후보이지 판정이 아니며 F0·회의주의자를 "
                     "통과해야 한다 (제안서 §2.1).")
    return out


# ── 결함 117 — **공유 유전자 수로 세면 질환을 안 본다** ──────────────
#
# 08-11 실측. `multihop` 의 `min_shared` 는 **유전자 허브**(TNF·IL6)를 막으려고
# 넣은 것인데, 실제로 올라온 것은 **화합물 허브**였다. 방향이 반대다.
#
#   질환 60개(유전자 20개 이상) 각각 상위 10 을 뽑았더니 —
#     · 전역 차수 상위 10 과 평균 **4.5 / 10** 이 겹친다
#     · `DB09341`(차수 1466)이 **60개 중 48개(80%)** 의 상위 10 에 있다
#     · 화합물 차수 중앙값은 **2** 다. 허브는 중앙값의 700배다
#
# **질환을 바꿔도 답이 거의 같으면 그건 질환별 후보가 아니라 인기 순위다.**
HUB_WARNING = ("`shared_genes` 정렬은 **화합물 허브**를 올린다 — 질환 60개 중 "
               "48개에서 같은 화합물이 상위 10에 들었다(결함 117). "
               "순위를 쓰려면 `enrich()` 를 써라.")

# 첫 수정은 **실패했다.** 초기하 검정(과대표현 분석)을 붙였더니 결핵에서
# 557개 중 **484개가 FDR<0.05** 로 나왔다. 유전자를 균등추출로 보는 널이
# 틀렸기 때문이다 — 유전자–질환 간선과 유전자–화합물 간선이 **둘 다 잘
# 연구된 유전자에 몰려 있어서**(문헌 편향) 겹침이 전부 부풀려진다.
# 거의 다 유의하면 후보를 484개 찾은 게 아니라 **널이 틀린 것**이다.
#
# 그래서 **차수를 보존하는 널**을 쓴다. 유전자 g 가 뽑힐 확률을 그 유전자의
# 관측 화합물 차수에 비례시키고(문헌 편향을 널에 넣는다), 차수 n 인 화합물이
# 질환 유전자 g 를 건드릴 확률을 p_g = 1-(1-w_g)^n 로 본다. 겹침은 포아송
# 이항이고 그 평균·분산으로 z 를 낸다.
#
# **이건 우리가 만든 방법이 아니다** — 차수 보존 널은 그래프 분석의 표준
# 관행이다(configuration model). 혁신으로 팔지 마라(`심사기준대조.md` ①).


# ── 판정 — **이 방법은 기각됐다** (`그래프검색결과.md`) ─────────────
#
#   08-11 저녁, 사전명세대로 가린 간선 16,368개로 재 봤더니 —
#
#     A 공유 개수(현행)      Recall@20 13.6%   ← 대조군을 크게 이김
#     C 차수 보존 z(이것)              8.5%   ← **대조군에도 졌다**
#     D 화합물 차수만(대조군)          10.2%
#
#   **허브를 뺀 것이 신호를 뺀 것이었다.** 간선이 많은 화합물은 실제로
#   적응증이 많다. 차수를 편향으로만 보고 나누면 진짜 정보까지 나간다.
#
#   **그래도 지우지 않는다** — 결함 117(상위 10칸이 질환을 안 본다)은
#   이 평가로 반박되지 않았다. 그건 순위의 **머리**를 본 것이고 Recall 은
#   **전체**를 본다. 둘 다 참이다. 다만 **기본값으로 쓰지 않는다.**
REJECTED = ("사전명세 `587c700e…` 평가에서 **기각**됐다 — Recall@20 8.5% 로 "
            "차수만 보는 대조군(10.2%)에도 졌다. `그래프검색결과.md` 참조. "
            "기본 순위로 쓰지 마라.")


def enrich(graph: Dict[str, Any], disease: str, k: int = 20,
           min_shared: int = 2, min_degree: int = 1) -> Dict[str, Any]:
    """차수 보존 널 대비 z. **사전 평가에서 기각됐다** — `REJECTED` 를 보라.

    `min_degree` 는 **반대쪽 고장**을 막는다. z 만 쓰면 간선이 2개뿐인
    화합물이 둘 다 맞아 z=8 로 1위가 된다 — 결핵 상위 6개가 차수 2~12
    였다. 얇은 근거가 강한 신호로 둔갑한다. 기본값 1은 **아무것도 안
    막는다**; 문턱은 사전명세에서 정하고 여기서 눈으로 고르지 않는다.
    """
    import math

    out: Dict[str, Any] = {"ok": False, "disease": disease, "items": [],
                           "error": None, "min_shared": min_shared,
                           "min_degree": min_degree, "null": "degree-preserving"}
    if not graph.get("ok"):
        out["error"] = graph.get("error") or "그래프 미적재"
        return out
    cg, gc, dg, cd = graph["cg"], graph["gc"], graph["gd"], graph["cd"]
    gc_deg = graph["gc"]
    total = sum(len(v) for v in gc_deg.values())
    if not total:
        out["error"] = "화합물–유전자 간선이 없다"
        return out
    dis_genes = [x for x in (graph["dg"].get(disease) or ()) if x in gc_deg]
    if not dis_genes:
        out["error"] = "그래프에 그 질환 노드가 없다(또는 화합물과 이어진 유전자가 없다): %s" % disease
        return out
    w = [len(gc_deg[x]) / total for x in dis_genes]
    dset = set(dis_genes)
    known = {c for c, ds in cd.items() if disease in ds}

    rows = []
    for c, gs in cg.items():
        if c in known:
            continue
        ov = len(gs & dset)
        if ov < min_shared:
            continue
        n = len(gs)
        if n < min_degree:
            continue
        ps = [1.0 - (1.0 - x) ** n for x in w]
        exp = sum(ps)
        var = sum(p * (1.0 - p) for p in ps)
        if var <= 0:
            continue
        rows.append({"compound": c, "shared_genes": ov, "degree": n,
                     "expected": round(exp, 2),
                     "z": round((ov - exp) / math.sqrt(var), 2),
                     "via": sorted(gs & dset)[:5]})
    rows.sort(key=lambda r: -r["z"])
    out["items"] = rows[:k]
    out["n_candidates_total"] = len(rows)
    out["n_disease_genes"] = len(dis_genes)
    out["n_known_excluded"] = len(known)
    out["ok"] = True
    out["rejected"] = REJECTED
    out["caveat"] = ("z 는 **순위용이지 p-값이 아니다.** 포아송 이항 정규근사이고 "
                     "다중비교 보정을 안 했다. 그리고 DRKG 관계는 검증된 근거가 "
                     "아니라 주장이다 — F0·회의주의자를 통과해야 한다(제안서 §2.1).")
    return out
