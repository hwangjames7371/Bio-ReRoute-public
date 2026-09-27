# -*- coding: utf-8 -*-
"""외부 데이터 소스 — PubMed(NCBI E-utilities), PubChem, RDKit.

원칙: 조회 실패 시 절대 허위 PASS를 만들지 않는다. error를 그대로 올린다.
"""

from .. import config as _config  # .env를 먼저 올린다 (순서 중요)

import json
import os
import re
import ssl
import threading
import time
import urllib.error       # **함수 안에서 올리면 안 된다** — 결함 141
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from . import cache

NCBI_TOOL = "Bio-ReRoute"
# NCBI는 연락처를 요구한다. 미설정 시에도 동작하지만 대량 조회 시 차단될 수 있다.
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "")
# API 키가 있으면 초당 3회 → 10회로 완화된다.
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
REQ_DELAY = 0.12 if os.environ.get("NCBI_API_KEY") else 0.35
TIMEOUT = 20

# ── **전역 호출 간격** — 스레드가 생기면 `time.sleep` 은 방어가 아니다 ──
#
#   지금까지는 한 스레드였으므로 `throttle()` 가 초당 ~2.9회를
#   보장했다. **스레드를 넷 쓰면 각자 따로 자므로 초당 11.4회가 된다** —
#   NCBI 제한(키 없이 3회)을 넘고 **429** 가 온다.
#
#   그리고 429 는 우리 코드에서 `{"error": …}` 가 되고, 그건 게이트에서
#   «조회 실패» 로 읽힌다. **네트워크 장애가 판정으로 둔갑하는 그 자리**다
#   (결함 35 — CT.gov 403 이 «0/14 = 0% · B6를 빼라» 로 나왔던 것).
#
#   > **`sleep` 은 «내가 얼마나 기다렸나» 이고, 제한은 «우리 전체가 초당
#   > 몇 번 불렀나» 다.** 둘은 스레드가 하나일 때만 같다.
#
#   그래서 **마지막 호출 시각을 전역으로 공유**하고 잠금으로 간격을 지킨다.
#   스레드가 없어도 동작이 같다 — 있을 때만 달라진다.
_RATE_LOCK = threading.Lock()
_LAST_CALL = [0.0]


def throttle() -> float:
    """NCBI 호출 간격을 **전체 스레드에 걸쳐** 지킨다. 잔 시간을 돌려준다."""
    with _RATE_LOCK:
        wait = REQ_DELAY - (time.time() - _LAST_CALL[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[0] = time.time()
        return max(0.0, wait)

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
PUBCHEM = ("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/%s"
           "/property/CanonicalSMILES/JSON")
_ctx = ssl.create_default_context()


def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": NCBI_TOOL})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
        return json.loads(r.read().decode("utf-8"))


def _params(**kw) -> str:
    p = {"db": "pubmed", "retmode": "json", "tool": NCBI_TOOL}
    if NCBI_EMAIL:
        p["email"] = NCBI_EMAIL
    if NCBI_API_KEY:
        p["api_key"] = NCBI_API_KEY
    p.update(kw)
    return urllib.parse.urlencode(p)


def _esearch_result(s: Any) -> Dict[str, Any]:
    """esearch 응답의 본체. **개수가 없으면 오류다 — 0 이 아니다** (결함 327).

    앞판은 `int(res.get("count", 0))` 였다. 응답에 개수가 없으면 **«문헌 0건」
    으로 읽고 캐시에 영구히 남겼다.** 그 0 이 실재하는 약 다섯을 «환각」 으로
    기각했다(difelikefalin · conbercept · bapineuzumab · povidone-iodine · M5049).
    파일 머리의 *«조회 실패 시 절대 허위 PASS를 만들지 않는다」* 는 지켰는데
    **허위 KILL 은 막지 않았다.**

    여기서 올리는 오류는 `cache._TRANSIENT` 가 «일시 장애» 로 읽어 **저장하지
    않는다** — 다음 실행에서 다시 묻는다(결함 37 과 같은 자리).
    """
    res = s.get("esearchresult") if isinstance(s, dict) else None
    if not isinstance(res, dict) or "count" not in res or res.get("ERROR"):
        raise ValueError("esearch 무응답(개수 없음): %s" % str(s)[:160])
    return res


def pubmed_lookup(query: str, retmax: int = 3) -> Dict[str, Any]:
    """PubMed 실시간 조회 → {count, pmids, title, error}."""
    if cache.has(query):
        return cache.get(query)

    out = {"count": None, "pmids": [], "title": "", "error": None}
    try:
        s = _get(EUTILS + "esearch.fcgi?" + _params(term=query, retmax=retmax, sort="relevance"))
        res = _esearch_result(s)
        out["count"] = int(res["count"])
        out["pmids"] = list(res.get("idlist", []))
        throttle()
        if out["pmids"]:
            d = _get(EUTILS + "esummary.fcgi?" + _params(id=out["pmids"][0]))
            rec = d.get("result", {}).get(out["pmids"][0], {})
            out["title"] = (rec.get("title") or "").strip().rstrip(".")
            throttle()
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    return cache.put(query, out)


def pubmed_search(query: str, retmax: int = 8, max_year=None) -> Dict[str, Any]:
    """팩트체크용 다건 검색. F0(retmax=3)와 캐시 키를 분리한다.

    max_year를 주면 그 연도까지 출판된 문헌만 본다(시점 차단, Tier 2).
    이게 없으면 "실패가 이미 문헌에 적힌 걸 읽었다"는 비판을 막을 수 없다.
    """
    key = "SEARCH::%d::%s::%s" % (retmax, query, max_year or "-")
    if cache.has(key):
        return cache.get(key)
    out = {"count": None, "pmids": [], "error": None}
    try:
        kw = dict(term=query, retmax=retmax, sort="relevance")
        if max_year:
            kw.update(datetype="pdat", mindate="1800", maxdate=str(max_year))
        s = _get(EUTILS + "esearch.fcgi?" + _params(**kw))
        res = _esearch_result(s)
        out["count"] = int(res["count"])
        out["pmids"] = list(res.get("idlist", []))
        throttle()
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    return cache.put(key, out)


# ─────────────────────────────────────────────────────────────
# 초록 수집 (efetch)
#   PubMed는 PublicationType으로 연구 유형을 자체 색인한다. 이건 사람이 붙인
#   MeSH 메타데이터이므로 LLM 추론보다 신뢰도가 높다. 가능한 한 이걸 쓰고,
#   LLM에는 판단이 필요한 것(방향·PICO·근거 문장)만 맡긴다.
# ─────────────────────────────────────────────────────────────
_PT_MAP = [                      # 위에서부터 우선 (더 결정적인 설계 우선)
    ("Meta-Analysis", "meta"),
    ("Systematic Review", "meta"),
    ("Randomized Controlled Trial", "rct"),
    ("Clinical Trial, Phase III", "rct"),
    ("Clinical Trial, Phase II", "rct"),
    ("Controlled Clinical Trial", "rct"),
    ("Clinical Trial", "trial"),
    ("Observational Study", "observational"),
    ("Review", "review"),
]


# 초록에 흔히 박혀 있는 임상시험 등록번호. 같은 시험의 본 논문·추적 논문·
# 하위분석을 묶는 유일하게 결정론적인 단서다.
_NCT = re.compile(r"\b(NCT\d{8})\b")


def mesh_id(term: str) -> str:
    """질환명 → **MeSH ID**(`MESH:D001943` 꼴). 못 찾으면 빈 문자열.

    DRKG 의 Disease 노드가 **4,871/5,103 = 95% 가 MeSH ID** 다(결함 244).
    우리 질환명은 MeSH 용어 그대로(`Breast Neoplasms`·`HIV Infections`)라
    `db=mesh` 로 물으면 이어진다.

    **LLM 0회다.** 색인 조회이지 추론이 아니다.
    """
    key = "MESH::%s" % (term or "").strip().lower()
    if cache.has(key):
        return cache.get(key)
    out = ""
    try:
        s = _get(EUTILS + "esearch.fcgi?"
                 + _params(db="mesh", term='"%s"[MeSH Terms]' % term, retmax=1))
        ids = list((s.get("esearchresult") or {}).get("idlist") or [])
        throttle()
        if ids:
            # esummary 가 `DS_MeshUI` 로 D-번호를 준다. UID 는 그게 아니다.
            d = _get(EUTILS + "esummary.fcgi?" + _params(db="mesh", id=ids[0]))
            throttle()
            res = (d.get("result") or {}).get(ids[0]) or {}
            ui = str(res.get("ds_meshui") or res.get("DS_MeshUI") or "").strip()
            if ui:
                out = "MESH:%s" % ui
    except Exception:
        out = ""          # **못 찾은 것과 오류를 «빈 문자열» 로 같이 굳힌다**
    return cache.put(key, out)


def trial_ids(text: str):
    return sorted(set(_NCT.findall(text or "")))


def _get_xml(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": NCBI_TOOL})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
        return r.read().decode("utf-8", "replace")


def pubmed_abstracts(pmids, retry: int = 1) -> Dict[str, Dict[str, Any]]:
    """PMID 목록 → {pmid: {title, abstract, pubtypes, study_type, year, journal}}

    study_type이 None이면 PubMed가 유형을 색인하지 않은 것이므로
    호출부(팩트체커)가 LLM 추정으로 보완한다.
    """
    import xml.etree.ElementTree as ET

    pmids = [p for p in pmids if p]
    if not pmids:
        return {}

    # 이번 실행에서 실제로 만든 값. 캐시가 꺼져 있어도 잃지 않는다(결함 36).
    _fetched = {}

    def keep(pmid, rec):
        cache.put("ABS::" + pmid, rec)
        _fetched[pmid] = rec

    todo = [p for p in pmids if not cache.has("ABS::" + p)]
    if todo:
        url = EUTILS + "efetch.fcgi?" + _params(id=",".join(todo), retmode="xml")
        raw = None
        for _ in range(retry + 1):
            try:
                raw = _get_xml(url)
                break
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, e)
                throttle()
        if raw is None:
            for p in todo:
                keep(p, {"pmid": p, "error": err, "abstract": "",
                         "title": "", "pubtypes": [],
                         "study_type": None, "year": None, "journal": ""})
        else:
            try:
                root = ET.fromstring(raw)
            except Exception as e:
                root = None
                err = "XML 파싱 실패: %s" % e
            seen = set()
            if root is not None:
                for art in root.iter("PubmedArticle"):
                    pid_el = art.find(".//MedlineCitation/PMID")
                    pid = (pid_el.text or "").strip() if pid_el is not None else ""
                    if not pid:
                        continue
                    seen.add(pid)
                    # 구조화 초록은 Label을 살려 붙인다(BACKGROUND/RESULTS 구분이 판정에 유용)
                    parts = []
                    for a in art.iter("AbstractText"):
                        txt = "".join(a.itertext()).strip()
                        if not txt:
                            continue
                        lab = a.get("Label")
                        parts.append(("%s: %s" % (lab, txt)) if lab else txt)
                    t_el = art.find(".//Article/ArticleTitle")
                    title = "".join(t_el.itertext()).strip() if t_el is not None else ""
                    pts = [(e.text or "").strip() for e in art.iter("PublicationType")]
                    stype = None
                    for label, code in _PT_MAP:
                        if label in pts:
                            stype = code
                            break
                    y_el = art.find(".//Article/Journal/JournalIssue/PubDate/Year")
                    j_el = art.find(".//Article/Journal/ISOAbbreviation")
                    keep(pid, {
                        "pmid": pid, "title": title, "abstract": " ".join(parts),
                        "pubtypes": pts, "study_type": stype,
                        "year": int(y_el.text) if (y_el is not None and
                                                   (y_el.text or "").isdigit()) else None,
                        "journal": (j_el.text or "").strip() if j_el is not None else "",
                        "nct": trial_ids(" ".join(parts)),
                        "error": None})
            for p in todo:                       # 응답에 없던 PMID도 기록(허위 방지)
                if p not in seen:
                    keep(p, {"pmid": p, "title": "", "abstract": "",
                                            "pubtypes": [], "study_type": None,
                                            "year": None, "journal": "",
                                            "error": "efetch 응답에 없음"})
        throttle()
    # ── **캐시를 거쳐 돌려주면 캐시가 꺼졌을 때 통째로 잃는다** (결함 36) ──
    #
    #   `cache.get` 은 `_ENABLED` 가 False면 무조건 None을 준다. 그래서
    #   `{p: cache.get(...)}` 로만 반환하면 **조회에 성공해도 빈 결과**가 나간다.
    #   오류도 아니고 0건도 아니고 그냥 None이라 호출부가 구분할 수 없다.
    #
    #   실측: `netcheck` 가 캐시를 끄고 물었더니 efetch가 정상 동작하는데도
    #   "빈 응답 → PubMed 차단"이 떴다. **진단기가 거짓 경보를 냈다.**
    #   캐시를 끈 이유가 "되는 것처럼 보이는 것"을 막으려던 것이었는데
    #   정반대로 "안 되는 것처럼 보이는" 결과를 만들었다.
    #
    #   그래서 이번 실행에서 실제로 만든 값을 따로 들고 있다가 보충한다.
    #   캐시가 켜져 있을 때의 동작은 완전히 같다.
    return {p: (cache.get("ABS::" + p) or _fetched.get(p)) for p in pmids}


# ═══════════════════════════════════════════════════════════════
# ClinicalTrials.gov 결과 등록부
#
#   PubMed만 읽으면 성능 상한이 출판 편향에 묶인다.
#   중단 시험의 논문 출판률은 22%인 반면(Williams 2015),
#   시험 데이터에 근거해 중단한 경우 등록부 결과 게시율은 91%다.
#   **반증 근거는 존재한다. 논문이 아니라 등록부에 있을 뿐이다.**
#
#   등록부 결과에는 동료심사가 없지만 1차 평가변수의 원자료와 통계 분석이
#   그대로 올라온다. 효능 판단에는 오히려 초록의 수사(spin)보다 낫다.
# ═══════════════════════════════════════════════════════════════
CTG = "https://clinicaltrials.gov/api/v2/studies"


def _ctg(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": NCBI_TOOL})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
        return json.loads(r.read().decode("utf-8"))


def _dig(d, *path, default=None):
    for k in path:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d


# 과학적 사유로 멈춘 시험. 반증 근거는 여기에 있다.
NEGATIVE_STATUS = "TERMINATED,WITHDRAWN,SUSPENDED"


def ctgov_search(drug: str, condition: str, limit: int = 12,
                 status: Optional[str] = None) -> Dict[str, Any]:
    """약물-질환 쌍의 등록 시험 중 **결과가 게시된 것**만 찾는다.

    status를 주면 그 상태의 시험만 본다(예: 중단·철회). 반증을 우선
    회수하려면 이걸 써야 한다 — 그냥 검색하면 완료된 성공 시험이 먼저 온다.
    """
    key = "CTGQ::%s::%s::%d::%s" % (drug, condition, limit, status or "-")
    if cache.has(key):
        return cache.get(key)
    out = {"ncts": [], "error": None, "how": ""}
    hard = False                 # 예외가 났는가(진짜 오류) vs 그냥 0건인가

    # 질의를 세 단계로 완화한다. 앞의 것이 실패하면 다음으로 간다.
    #   ① 결과 게시 필터 + 구조화 질의  — 가장 정확하지만 API 파라미터에 의존
    #   ② 필터 없이 구조화 질의        — aggFilters 표기가 바뀌었을 때 대비
    #   ③ 자유 문자열 질의             — 약물명 동의어 문제 대비
    #                                    (RepoDB는 hydroxycarbamide, 시험은 hydroxyurea)
    attempts = [
        ("필터+구조화", {"query.intr": drug, "query.cond": condition,
                     "aggFilters": "results:with",
                     "pageSize": limit, "format": "json", "fields": "NCTId"}),
        ("구조화", {"query.intr": drug, "query.cond": condition,
                 "pageSize": limit, "format": "json", "fields": "NCTId"}),
        ("자유문", {"query.term": "%s AND %s" % (drug, condition),
                 "pageSize": limit, "format": "json", "fields": "NCTId"}),
    ]
    last = None
    for how, params in attempts:
        if status:
            params = dict(params, **{"filter.overallStatus": status})
        try:
            d = _ctg(CTG + "?" + urllib.parse.urlencode(params))
            ncts = []
            for st in d.get("studies", []):
                n = _dig(st, "protocolSection", "identificationModule", "nctId")
                if n:
                    ncts.append(n)
            throttle()
            if ncts:
                out["ncts"], out["how"] = ncts, how
                return cache.put(key, out)
            last, hard = "%s: 0건" % how, False
        except Exception as e:
            last, hard = "%s: %s" % (how, e), True
            throttle()
    # **"0건"은 오류가 아니라 결과 부재다.**
    #   둘을 같이 error에 넣었더니 진단 화면에 "등록부 오류 2건"으로 찍혀
    #   조회가 실패한 것처럼 보였다. 실제로는 그냥 시험이 없던 것이다.
    #   버그와 사실을 구분 못 하면 엉뚱한 곳을 고치게 된다.
    if hard:
        out["error"] = last
    else:
        out["how"] = last
    return cache.put(key, out)


def _fmt_outcome(om: Dict[str, Any]) -> str:
    """1차 평가변수 하나를 사람이 읽을 수 있는 문장으로."""
    lines = [om.get("title", "")]
    if om.get("description"):
        lines.append(om["description"][:200])
    groups = {g.get("id"): g.get("title", "") for g in (om.get("groups") or [])}
    for cl in (om.get("classes") or [])[:2]:
        for cat in (cl.get("categories") or [])[:2]:
            vals = []
            for m in (cat.get("measurements") or []):
                g = groups.get(m.get("groupId"), m.get("groupId", ""))
                v = m.get("value", "")
                sp = m.get("spread")
                vals.append("%s %s%s" % (g, v, (" ±%s" % sp) if sp else ""))
            if vals:
                lines.append("  " + " | ".join(vals[:4]))
    for an in (om.get("analyses") or [])[:2]:
        bits = []
        if an.get("pValue"):
            bits.append("p=%s" % an["pValue"])
        if an.get("statisticalMethod"):
            bits.append(an["statisticalMethod"])
        if an.get("paramType") and an.get("paramValue"):
            bits.append("%s=%s" % (an["paramType"], an["paramValue"]))
        if bits:
            lines.append("  통계: " + " · ".join(bits))
    return "\n".join(x for x in lines if x)


# 중단 사유 판정. bench/labels.py 의 OPERATIONAL 과 같은 어휘를 쓴다 —
#   라벨을 만들 때와 근거를 읽을 때 잣대가 다르면 그 차이가 성능으로 보인다.
_STOP_OPS = re.compile(
    r"accrual|enroll|recruit|funding|budget|sponsor decision|business"
    r"|administrative|staffing|logistic|supply|manufactur|covid|pandemic"
    r"|investigator (left|departure)|pi (left|departure)|strateg", re.I)
_STOP_EFF = re.compile(
    r"futility|lack of efficacy|no (benefit|efficacy)|did not meet"
    r"|failed to (meet|show|demonstrate)|interim analysis|safety|toxicit"
    r"|adverse event|harm", re.I)


def stop_reason(status: str, why: str) -> Optional[str]:
    """중단 사유를 과학적 사유·운영상 사유로 가른다. 애매하면 판단하지 않는다.

    반환 "efficacy"는 **효능과 안전성을 함께** 가리킨다. 독성으로 멈춘 시험도
    그 적응증에 그 약을 쓰지 말라는 과학적 근거이므로 같이 묶는다.

    과학적 사유가 함께 있으면 그쪽을 우선한다 —
    "terminated for futility; also slow accrual"은 효능 근거가 맞다.
    """
    if "TERMINAT" not in (status or "").upper() and \
       "WITHDRAWN" not in (status or "").upper():
        return None
    if not (why or "").strip():
        return "unknown"
    if _STOP_EFF.search(why):
        return "efficacy"
    if _STOP_OPS.search(why):
        return "operational"
    return "unknown"


def ctgov_results(nct: str) -> Dict[str, Any]:
    """등록부 결과를 초록처럼 읽을 수 있는 형태로 만든다.

    팩트체커가 PubMed 초록과 같은 경로로 처리할 수 있게 형식을 맞춘다.
    출처는 pubtypes에 'Registry Results'로 명시해 감사 추적을 남긴다.

    캐시 키에 판 번호가 붙어 있다. 본문 형식이나 필드를 바꾸면 반드시 올려라.
    안 올리면 **구버전 캐시가 새 로직을 조용히 무력화한다** — v2에서
    stop_reason 필드와 운영중단 경고 줄을 추가했는데, v1 캐시를 그대로 읽으면
    두 가지가 다 빠진 채로 들어와 중단 사유 방어가 통째로 꺼진다.
    사람에게 "캐시를 지우세요"라고 말하는 것은 방어가 아니다.
    """
    key = "CTGR3::" + nct
    # 판 번호에만 기대지 않는다. 필요한 필드가 실제로 있는지 직접 묻는다.
    #   판 올리기를 잊으면 새 방어가 조용히 꺼지는데, 그 사고를 두 번 겪었다.
    if not cache.stale(key, "conditions", "interventions", "stop_reason"):
        return cache.get(key)
    out = {"pmid": nct, "title": "", "abstract": "", "pubtypes": [],
           "study_type": None, "year": None, "journal": "ClinicalTrials.gov",
           "nct": [nct], "source": "ctgov", "stop_reason": None,
           "conditions": [], "interventions": [], "error": None}
    try:
        d = _ctg("%s/%s?format=json" % (CTG, urllib.parse.quote(nct)))
        p = d.get("protocolSection", {})
        rs = d.get("resultsSection", {}) or {}
        out["title"] = _dig(p, "identificationModule", "briefTitle", default="") or ""
        why = _dig(p, "statusModule", "whyStopped", default="") or ""
        status = _dig(p, "statusModule", "overallStatus", default="") or ""
        comp = (_dig(p, "statusModule", "completionDateStruct", "date", default="")
                or _dig(p, "statusModule", "primaryCompletionDateStruct", "date",
                        default="") or "")
        m = re.search(r"(19|20)\d{2}", comp)
        out["year"] = int(m.group(0)) if m else None

        alloc = _dig(p, "designModule", "designInfo", "allocation", default="") or ""
        phases = _dig(p, "designModule", "phases", default=[]) or []
        n_enr = _dig(p, "designModule", "enrollmentInfo", "count", default=None)
        # 무작위배정 여부는 등록부에 명시돼 있다. LLM 추정보다 신뢰도가 높다.
        out["study_type"] = "rct" if "RANDOMIZED" == alloc.upper() else "trial"
        out["pubtypes"] = ["Registry Results"] + phases + ([alloc] if alloc else [])

        # 중단 사유를 효능/운영으로 가른다.
        #
        #   **자금이 끊겨 멈춘 시험은 약이 안 듣는다는 증거가 아니다.**
        #   그런데 본문에 "Terminated"만 보이면 LLM은 반증으로 읽는다.
        #   벤치마크 라벨 생성부(bench/labels.py)는 이 구분을 하는데
        #   정작 근거를 읽는 게이트에는 없었다. 같은 잣대를 여기에도 건다.
        out["stop_reason"] = stop_reason(status, why)

        # 대상 질환과 개입을 반드시 본문에 넣는다.
        #
        #   **없으면 팩트체커가 "무슨 병을 대상으로 한 시험인지 모른 채" 판정한다.**
        #   실측 사고: 가설은 "피오글리타존이 천식에 효능이 있다"인데,
        #   등록부에서 끌어온 시험은 제2형 당뇨 시험이었다. 본문에 질환이
        #   없으니 팩트체커의 규칙 2번("다른 질환은 무관")이 작동할 수 없었다.
        #   자유문 검색이 엉뚱한 시험을 물어와도 걸러낼 방법이 없던 것이다.
        #
        #   개입도 같이 넣는다. 대조약만 다르고 같은 시험인지, 아예 다른
        #   약을 본 시험인지는 개입 목록을 봐야 안다.
        conds = _dig(p, "conditionsModule", "conditions", default=[]) or []
        arms = _dig(p, "armsInterventionsModule", "interventions", default=[]) or []
        inames = []
        for it in arms:
            if it.get("name"):
                inames.append(it["name"])
            inames += list(it.get("otherNames") or [])
        out["conditions"], out["interventions"] = conds, inames
        body = ["대상 질환: %s" % (", ".join(conds) or "미기재"),
                "개입: %s" % (", ".join(inames[:8]) or "미기재"),
                "상태: %s%s" % (status, ("  중단 사유: " + why) if why else ""),
                "등록 환자 %s명 · 배정 %s · 상 %s"
                % (n_enr if n_enr is not None else "미상", alloc or "미상",
                   ",".join(phases) or "미상")]
        if out["stop_reason"] == "operational":
            body.append("※ 중단 사유는 운영상 문제(등록 부진·자금 등)다. "
                        "중단 자체를 효능 반증으로 읽으면 안 된다. "
                        "아래 1차 평가변수 수치만으로 판단하라.")
        oms = (rs.get("outcomeMeasuresModule") or {}).get("outcomeMeasures") or []
        prim = [o for o in oms if (o.get("type") or "").upper() == "PRIMARY"] or oms[:1]
        body += ["", "[1차 평가변수 결과]"]
        for o in prim[:3]:
            body.append(_fmt_outcome(o))
        out["abstract"] = "\n".join(body).strip()
        if not prim:
            out["error"] = "결과 섹션에 1차 평가변수 없음"
        throttle()
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    return cache.put(key, out)


PUBCHEM_KEY = ("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/%s"
               "/property/InChIKey/JSON")


def fetch_inchikey(name: str) -> Dict[str, Any]:
    """PubChem에서 InChIKey 취득. **SureChEMBL 과 잇는 열쇠다** (§3.3-8).

    SMILES 로 안 잇는 이유 — 같은 분자도 표기가 여러 가지라 문자열 대조가
    안 된다. **InChIKey 는 표준화된 해시**라 그대로 맞춰진다.
    SureChEMBL `compounds.parquet` 이 `inchi_key` 열을 갖고 있다.

    **실패를 캐시한다는 점을 조심해라** — `fetch_smiles` 와 같은 틀을 쓰되,
    여기서는 오류를 캐시하면 일시 장애가 «그 약은 InChIKey 가 없다» 로
    굳는다(결함 37·58). 그래서 **성공만 캐시한다.**
    """
    key = "INCHIKEY::" + name
    if cache.has(key):
        return cache.get(key)
    out = {"inchikey": None, "error": None}
    try:
        d = _get(PUBCHEM_KEY % urllib.parse.quote(name))
        props = d.get("PropertyTable", {}).get("Properties", [])
        if props and props[0].get("InChIKey"):
            out["inchikey"] = props[0]["InChIKey"].strip().upper()
        throttle()
    except Exception as e:
        # 404(그 이름이 PubChem 에 없음)는 **진짜 «없다»** 라 캐시한다.
        # 나머지(타임아웃·5xx)는 **실패이므로 캐시하지 않는다.**
        #
        # ## ⚠ 여기에 `import urllib.error` 를 쓰면 안 된다 (결함 141)
        #
        #   함수 안 어디서든 `import urllib` 을 하면 파이썬은 **함수 전체에서**
        #   `urllib` 을 지역 이름으로 본다. 그러면 위 `try` 첫 줄의
        #   `urllib.parse.quote(name)` 이 **대입 전 참조**가 되어
        #   `UnboundLocalError` 로 터진다 — **네트워크에 나가지도 못한다.**
        #
        #   실측: 1,207건이 전부 «조회 실패» 로 찍혔고, 그건 PubChem 이
        #   막힌 게 아니라 **요청이 한 번도 안 나간 것**이었다.
        #   그래서 `urllib.error` 는 **모듈 상단에서** 올린다.
        if isinstance(e, urllib.error.HTTPError) and e.code == 404:
            out["error"] = None
            return cache.put(key, out)
        out["error"] = "%s: %s" % (type(e).__name__, e)
        return out
    return cache.put(key, out)


def fetch_smiles(name: str) -> Dict[str, Any]:
    """PubChem에서 SMILES 취득. 코드에 SMILES를 적어 넣지 않아 표기 오류를 원천 차단."""
    key = "SMILES::" + name
    if cache.has(key):
        return cache.get(key)

    out = {"smiles": None, "error": None}
    try:
        d = _get(PUBCHEM % urllib.parse.quote(name))
        props = d.get("PropertyTable", {}).get("Properties", [])
        if props:
            rec = props[0]
            for k in ("CanonicalSMILES", "SMILES", "ConnectivitySMILES", "IsomericSMILES"):
                if rec.get(k):
                    out["smiles"] = rec[k]
                    break
            if not out["smiles"]:
                for k, v in rec.items():
                    if "SMILES" in k.upper() and v:
                        out["smiles"] = v
                        break
        throttle()
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    return cache.put(key, out)


# 하전 작용기. **강도를 나눈다** — 이걸 안 나눠서 처음에 틀렸다.
#
#   강: 생리 pH 전 구간에서 사실상 전량 하전. 중성분율이 없어 수동확산이 막힌다.
#   약: pKa가 생리 범위 안이라 **중성분율이 존재**한다. 위 십이지장 pH에서
#       흡수되는 산성 약물이 많다(이부프로펜·나프록센·스타틴 등).
#
# 처음엔 카복실산을 강으로 넣었다. 그 결과 승인 약물의 절반이 걸렸다 —
# **과탐지였다.** 카복실산 pKa는 대략 4~5로 위산(pH 1~3)에서 중성이다.
# 구아니딘(pKa≈12.4)·4급암모늄(영구)과 같이 놓을 근거가 없다.
_IONIC_STRONG = (
    ("구아니딘·아미딘계 강염기", "[NX3][CX3]=[NX2]"),   # pKa 대략 12~13
    ("4급 암모늄",              "[NX4+]"),             # 영구 하전
    ("설폰산",                  "[SX4](=O)(=O)[OX2H1,OX1-]"),   # pKa < 1
)
_IONIC_WEAK = (
    ("카복실산", "[CX3](=O)[OX2H1,OX1-]"),             # pKa 대략 4~5
)
_IONIC_SMARTS = _IONIC_STRONG + _IONIC_WEAK


def permeability_caveat(mw, logp, hits):
    """Ro5 통과가 **투과성을 뜻하지 않는** 경우. 반환은 dict.

    Ro5(Lipinski 1997)는 **상한만** 있다 — MW>500, logP>5, HBD>5, HBA>10.
    하한이 없으므로 *너무 작고 너무 친수성인* 분자는 위반 0건으로 통과한다.
    그러나 Ro5의 전제는 **수동 세포막 확산**이고, 생리 pH에서 전량 하전된
    분자는 그 경로를 쓰지 못한다 — 운반체(OCT/MATE/PMAT 등)에 의존한다.

    실례: 메트포르민은 MW 129 · logP −1.2로 위반 0건이지만, 비구아니드
    pKa가 약 12.4라 생리 pH에서 사실상 전량이 양이온이다. 경구 흡수는
    PMAT·OCT3, 간 유입은 OCT1, 신배설은 OCT2·MATE에 의존한다.
    **표적 조직 도달은 그 운반체의 발현에 좌우되며 Ro5는 이를 보지 못한다.**

    `tier` 는 "강" · "약" · "" 셋이다. 벤치마크 84행에 돌렸더니 승인 약물의
    45%가 걸려 **선택성이 없었다** — 원인이 카복실산이었다. 등급을 나눈 것은
    수치를 보고 한 수정이지만, 근거는 수치가 아니라 **사전에 알려진 pKa**다.
    그래도 사후 수정임을 보고에 반드시 적어야 한다.

    판정을 바꾸지 않는다 — **주석만 단다.** 점수에 손대면 벤치마크 수치가
    전부 무효가 된다(재현절차 §0-②).
    """
    strong = {n for n, _ in _IONIC_STRONG}
    hit = [n for n, _ in hits]
    r_strong = [n for n in hit if n in strong]
    r_weak = [n for n in hit if n not in strong]
    if logp is not None and logp < -0.4 and (mw or 0) < 350:
        r_strong.append("극친수성(logP %.1f)" % logp)

    reasons = r_strong + r_weak
    if not reasons:
        return {"text": "", "tier": "", "reasons": []}
    tier = "강" if r_strong else "약"
    body = ("위반 0건이 투과성을 뜻하지 않는다(운반체 의존 가능)" if tier == "강"
            else "약산이라 중성분율이 있다 — 경구 흡수는 가능할 수 있다")
    return {"text": "Ro5는 수동확산 전제 [%s] — %s이므로 %s"
                    % (tier, " · ".join(reasons), body),
            "tier": tier, "reasons": reasons}


def _ionic_hits(mol, matcher=None):
    """하전 작용기 탐지. matcher를 주입할 수 있어 RDKit 없이도 시험 가능하다."""
    if matcher is None:
        from rdkit import Chem

        def matcher(smarts):
            patt = Chem.MolFromSmarts(smarts)
            return bool(patt) and mol.HasSubstructMatch(patt)
    return [(n, s) for n, s in _IONIC_SMARTS if matcher(s)]


def s2_properties(name: Optional[str]) -> Optional[Dict[str, Any]]:
    """S2 리간드 개발성 — PAINS는 경보, Ro5 위반은 접근성 신호.

    PAINS를 하드 비토로 쓰지 않는 이유: 필터가 특정 HTS 데이터에서 유도돼
    적용 범위가 좁고 승인 약물의 약 5%가 경보를 일으킨다(Baell & Nissink 2017).
    탐색 범위가 승인 약물인 본 시스템에서 하드 비토는 정당한 후보를 대량으로 잃는다.
    """
    if not name:
        return None
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, FilterCatalog
    except Exception:
        return {"status": "SKIP", "detail": "RDKit 미설치 — S2 생략"}

    sm = fetch_smiles(name)
    if sm.get("error") or not sm.get("smiles"):
        return {"status": "ERROR",
                "detail": "SMILES 취득 실패: %s" % (sm.get("error") or "결과 없음")}

    mol = Chem.MolFromSmiles(sm["smiles"])
    if mol is None:
        return {"status": "ERROR", "detail": "SMILES 파싱 실패"}

    mw = Descriptors.MolWt(mol)
    logp = Descriptors.MolLogP(mol)
    hbd = Descriptors.NumHDonors(mol)
    hba = Descriptors.NumHAcceptors(mol)
    viol = sum([mw > 500, logp > 5, hbd > 5, hba > 10])

    params = FilterCatalog.FilterCatalogParams()
    params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS)
    cat = FilterCatalog.FilterCatalog(params)
    pains = cat.HasMatch(mol)
    pains_name = ""
    if pains:
        m = cat.GetFirstMatch(mol)
        pains_name = m.GetDescription() if m is not None else ""

    try:
        cav = permeability_caveat(mw, logp, _ionic_hits(mol))
    except Exception:
        cav = {"text": "", "tier": "", "reasons": []}   # 주석 실패가 S2를 죽이면 안 된다
    caveat = cav["text"]

    prop = "MW %.0f · logP %.1f · HBD %d · HBA %d" % (mw, logp, hbd, hba)
    # smiles 를 같이 돌려준다 — hERG·DILI·HITL Tanimoto 가 이걸 재사용한다.
    #   **다시 조회하지 않는다.** 같은 분자를 두 번 받아 오면 그 사이에
    #   PubChem 이 다른 걸 줄 수 있고, 그러면 판정과 경보가 다른 분자를 본다.
    res = {"smiles": sm.get("smiles"),
           "mw": mw, "logp": logp, "hbd": hbd, "hba": hba,
           "ro5_violations": viol, "pains": pains, "pains_name": pains_name,
           "caveat": caveat, "caveat_tier": cav["tier"],
           "caveat_reasons": cav["reasons"]}
    if pains:
        res.update(status="ALERT",
                   detail="PAINS 경보(%s) — 근거 어세이 재검토 · %s" % (pains_name, prop))
    elif viol >= 2:
        res.update(status="FLAG",
                   detail="Ro5 위반 %d건 — 경구 개발성 이탈 · %s" % (viol, prop))
    else:
        res.update(status="PASS",
                   detail="PAINS 없음 · Ro5 위반 %d건 · %s" % (viol, prop))
    if caveat:
        res["detail"] += "\n                                       ⚠ " + caveat
    return res
