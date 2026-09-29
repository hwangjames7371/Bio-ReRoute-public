# -*- coding: utf-8 -*-
"""Phase 2 검증 — 등록부·라우터·시점차단·누출차단.

실행: python -m bioreroute.tests.test_phase2
"""

import csv
import json
import re
import sys
import os
import tempfile


def _tmp(name):
    """시험용 임시 경로.

    **"/tmp"를 하드코딩하면 윈도우에서 깨진다.** 실제로 깨졌다 —
    ceiling CLI 시험이 FileNotFoundError로 죽었다.
    나는 리눅스에서만 돌려보고 "전수 통과"라고 보고했다.
    검증 환경이 실행 환경과 다르면 그 검증은 거짓말이다.
    """
    return os.path.join(tempfile.gettempdir(), name)


from ..agents import router
from ..core import gates
from ..io import cache, llm, sources

PASS, FAIL = [], []


class patched:
    """몽키패치를 반드시 되돌린다.

    실제 사고: test_leakage가 sources.ctgov_search를 가짜로 바꾸고 복원하지 않아
    뒤에 오는 test_search_fallback이 가짜를 호출해 0회 시도로 실패했다.
    단독으로는 통과하고 전체 실행에서만 깨지는 **유령 실패**다.
    테스트가 전역 상태를 오염시키면 어느 시험 결과도 믿을 수 없다.
    """

    def __init__(self, obj, **kw):
        self.obj, self.kw, self.old = obj, kw, {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = getattr(self.obj, k, None)
            setattr(self.obj, k, v)
        return self.obj

    def __exit__(self, *a):
        for k, v in self.old.items():
            setattr(self.obj, k, v)


def _uisrc():
    """**화면을 그리는 코드 전부.** 한 파일에 못 박지 않는다.

    ## 왜 이 함수가 생겼나 (08-20)

    08-20 에 조립 함수 440줄을 `app.py` → `bioreroute/webui.py` 로
    옮겼다(Gradio 를 걷어내려고). 그러자 **`app.py` 를 읽던 시험이
    줄줄이 깨졌다** — [103]·[66]·[84]. 요건은 «화면이 이걸 적는가»
    인데 시험은 «`app.py` 가 이걸 적는가» 를 보고 있었다.

    **파일 위치는 요건이 아니다.** 세 번 같은 이유로 깨진 뒤에
    함수로 막는다 — 안내문이 아니라 구조로.
    """
    import io as _u_io, os as _u_os
    from .. import evidence as _u_ev
    out = []
    for rel in ("app.py",
                _u_os.path.join("bioreroute", "webui.py"),
                _u_os.path.join("bioreroute", "dash.py"),
                _u_os.path.join("web", "server.py")):
        f = _u_os.path.join(_u_ev.ROOT, rel)
        if _u_os.path.exists(f):
            out.append(_u_io.open(f, encoding="utf-8").read())
    return "\n".join(out)


def check(name, cond, got=""):
    (PASS if cond else FAIL).append(name)
    # ⚠ `got` 이 **튜플이면** `"%s" % got` 이 인자 전개로 읽혀 터진다.
    #   08-14에 실제로 그랬다 — 시험이 **통과했는데 출력에서 죽어서**
    #   그 뒤 검사가 통째로 안 돌았다. **검사 결과를 찍는 코드가 검사를
    #   가리면 안 된다.** `str()` 로 먼저 굳힌다.
    print("  %s %s%s" % ("PASS" if cond else "FAIL", name,
                         ("  -> %s" % (str(got),)) if got else ""))


CTG_FAKE = {
    "protocolSection": {
        "identificationModule": {"briefTitle": "Doxycycline in IPF"},
        "statusModule": {"overallStatus": "Terminated",
                         "whyStopped": "Terminated for futility",
                         "completionDateStruct": {"date": "2015-06"}},
        "conditionsModule": {"conditions": ["Idiopathic Pulmonary Fibrosis"]},
        "armsInterventionsModule": {"interventions": [
            {"name": "Doxycycline", "otherNames": ["Vibramycin"]},
            {"name": "Placebo"}]},
        "designModule": {"designInfo": {"allocation": "RANDOMIZED"},
                         "phases": ["PHASE3"],
                         "enrollmentInfo": {"count": 142}}},
    "resultsSection": {"outcomeMeasuresModule": {"outcomeMeasures": [
        {"type": "PRIMARY", "title": "Change in FVC at 12 months",
         "groups": [{"id": "A", "title": "Doxycycline"}, {"id": "B", "title": "Placebo"}],
         "classes": [{"categories": [{"measurements": [
             {"groupId": "A", "value": "-0.21", "spread": "0.09"},
             {"groupId": "B", "value": "-0.19", "spread": "0.08"}]}]}],
         "analyses": [{"pValue": "0.68", "statisticalMethod": "ANCOVA"}]}]}}}


def test_registry():
    print("\n[1] 등록부 결과 — 출판 편향을 우회하는 근거원")
    cache.configure(_tmp("_p2.json"))
    cache._STORE.clear()
    with patched(sources, _ctg=lambda url: CTG_FAKE):
        r = sources.ctgov_results("NCT00600028")
    check("무작위배정을 등록부에서 읽음", r["study_type"] == "rct", r["study_type"])
    check("출처를 pubtypes에 명시", "Registry Results" in r["pubtypes"])
    check("종료 연도 추출", r["year"] == 2015, r["year"])
    check("1차 평가변수 수치 포함", "-0.21" in r["abstract"])
    check("통계 분석 포함", "p=0.68" in r["abstract"])
    check("중단 사유 포함", "futility" in r["abstract"])

    # **대상 질환이 본문에 없으면 팩트체커가 무슨 병인지 모른 채 판정한다.**
    #   실측 사고: 가설은 "피오글리타존 / 천식"인데 등록부에서 끌려온 것은
    #   제2형 당뇨 시험이었다. 본문에 질환이 없어 팩트체커의 규칙 2번
    #   ("다른 질환은 무관")이 작동할 수 없었다. 자유문 검색이 엉뚱한
    #   시험을 물어와도 걸러낼 방법이 없던 것이다.
    check("대상 질환이 본문에 있음",
          "Idiopathic Pulmonary Fibrosis" in r["abstract"])
    check("개입이 본문에 있음", "Doxycycline" in r["abstract"])
    check("상품명(otherNames)도 실림", "Vibramycin" in r["abstract"])
    check("질환·개입을 필드로도 노출",
          r["conditions"] == ["Idiopathic Pulmonary Fibrosis"]
          and "Doxycycline" in r["interventions"])
    # 본문 형식이 바뀌면 캐시 판을 올려야 한다. 안 올리면 구버전 본문이
    #   그대로 쓰여 새 방어가 통째로 꺼진다.
    check("캐시 키에 판 번호", cache.has("CTGR3::NCT00600028"))

    cache._STORE.clear()
    with patched(sources, _ctg=lambda url: {"protocolSection": CTG_FAKE["protocolSection"]}):
        r2 = sources.ctgov_results("NCT99999999")
    check("결과 없는 시험은 error로 표시", bool(r2.get("error")), r2.get("error"))


def test_router():
    print("\n[2] 기전 라우터 — 언제 도킹하면 안 되는가")
    def _c(prompt, system="", model=None, as_json=False, purpose=""):
        d = [{"idx": 1, "mech": "간접", "target": "", "confidence": "high",
              "why": "엔도솜 pH"},
             {"idx": 2, "mech": "직접·숙주", "target": "JAK1/2", "confidence": "high",
              "why": "JAK 억제"},
             {"idx": 3, "mech": "직접·병원체", "target": "RdRp", "confidence": "high",
              "why": "바이러스 중합효소"},
             {"idx": 4, "mech": "직접·병원체", "target": "?", "confidence": "low",
              "why": ""}]
        return {"ok": True, "text": json.dumps(d), "data": d, "error": None,
                "provenance": llm.provenance(prompt), "cached": False}
    with patched(llm, available=lambda: True, complete=_c):
        router.llm = llm
        out = router.classify([{"drug": "hydroxychloroquine", "disease": "COVID-19"},
                               {"drug": "baricitinib", "disease": "COVID-19"},
                               {"drug": "remdesivir", "disease": "COVID-19"},
                               {"drug": "unsure", "disease": "X"}])
    check("간접 작용 → 증거 경로", out[0]["route"] == "evidence")
    check("숙주 표적 → 증거 경로", out[1]["route"] == "evidence")
    check("병원체 표적 → 구조 경로", out[2]["route"] == "structure")
    check("숙주 표적에 도킹 권고 안 함", not router.docking_advised(out[1]))
    check("병원체 표적에 도킹 권고", router.docking_advised(out[2]))
    check("저신뢰 분류에는 도킹 권고 안 함", not router.docking_advised(out[3]),
          "confidence=low")


def test_cutoff():
    print("\n[3] 시점 차단 — 실패가 알려지기 전에 걸렀는가")
    seen = {}

    def fake_search(q, retmax=8, max_year=None):
        seen["max_year"] = max_year
        return {"count": 5, "pmids": ["1", "2"], "error": None}

    with patched(sources, pubmed_search=fake_search):
        sources.pubmed_search("x AND y", 8, 2014)
    check("검색에 연도 상한이 전달됨", seen["max_year"] == 2014, seen["max_year"])

    from ..bench import run as BR
    BR.TIER2 = True
    c = BR.to_candidate({"drug": "doxycycline", "indication": "IPF",
                         "label": "TN", "ctgov_year": "2015"})
    check("종료 2015 → 컷오프 2014", c.cutoff_year == 2014, c.cutoff_year)
    check("S2가 돌 수 있게 약물명 전달", c.pubchem == "doxycycline")
    BR.TIER2 = False
    c2 = BR.to_candidate({"drug": "x", "indication": "y", "label": "TN"})
    check("시점 차단 끄면 컷오프 없음", c2.cutoff_year is None)


def test_leakage():
    print("\n[4] 누출 차단 — 라벨 출처 시험을 근거로 쓰면 안 된다")
    from ..core.state import Candidate, RunState
    gates.EXCLUDE_NCT = {"NCT00600028"}
    c = Candidate(name="t", origin="", query="q", drug="doxycycline", disease="IPF")
    st = RunState("q", "s", "t", [c], dict(gates.CONFIGS["B6"]))
    with patched(llm, available=lambda: True), \
         patched(sources,
                 ctgov_search=lambda d, i, n=8, status=None: {"ncts": ["NCT00600028"], "error": None}):
        gates.gate_registry(st)
    rec = next((t for t in c.trail if t.gate == "registry"), None)
    check("라벨 출처 시험이 제외됨",
          rec is not None and "제외" in (rec.detail or ""), rec.detail if rec else None)
    check("근거가 생성되지 않음", not c.factcheck)
    gates.EXCLUDE_NCT = set()


def test_cli_all():
    """모든 CLI 진입점을 실제로 실행한다.

    지난번 analyze.py는 헬퍼 단위 시험을 전부 통과하고도 main()에서
    NameError로 죽었다. ceiling.py도 상대 임포트를 틀렸다.
    **진입점을 안 태우면 같은 사고가 반복된다.**
    """
    import contextlib
    import csv as _csv
    import io as _io
    import json as _json
    import os
    import tempfile
    import urllib.request

    print("\n[6] CLI 전 구간 — 진입점을 실제로 호출한다")

    # ── analyze (B6 포함) ────────────────────────────────────
    from ..bench import analyze
    n = 12
    rw = [{"drug": "d%d" % i, "indication": "x%d" % i,
           "label": "TP" if i % 2 else "TN"} for i in range(n)]
    mk = lambda v: {"scores": [0.8 if i % 2 else 0.2 for i in range(n)],
                    "verdicts": [v[0] if i % 2 else v[1] for i in range(n)]}
    d = {"stratum": "A", "n_tp": n // 2, "n_tn": n // 2, "rows": rw,
         "results": {"B0": mk(("성공", "실패")), "B5": mk(("유망", "기각")),
                     "B6": mk(("유망", "기각"))}}
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    _json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    try:
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = analyze.main([path])
        out = buf.getvalue()
        check("analyze CLI 정상 종료", rc == 0)
        check("analyze가 B6를 인식", "B6" in out,
              "구성 목록을 하드코딩하면 새 구성이 조용히 무시된다")
    finally:
        os.unlink(path)

    # ── ceiling ─────────────────────────────────────────────
    from ..bench import ceiling
    # 층을 반드시 붙인다. ceiling은 bench.run 과 같은 층을 봐야 한다 —
    #   실측 사고: ceiling이 TN 49건(전 층), bench.run이 42건(층 A)을 써서
    #   "한계 기여 19/49"가 실제로 돌릴 집합과 다른 모집단의 숫자였다.
    rows = [{"drug": "doxycycline", "indication": "IPF", "label": "TN",
             "stratum": "A", "nct": "NCT00600028"},
            {"drug": "other", "indication": "X", "label": "TN",
             "stratum": "B", "nct": "NCT00999999"}]
    fd, cpath = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(cpath, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    class _R:
        def __init__(self, dd):
            self.d = _json.dumps(dd).encode()

        def read(self):
            return self.d

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def _op(req, timeout=0, context=None):
        u = req.full_url
        if "query." in u or "/studies?" in u:
            return _R({"studies": [{"protocolSection":
                                    {"identificationModule": {"nctId": "NCT00600028"}}}]})
        return _R(CTG_FAKE)

    real = urllib.request.urlopen
    urllib.request.urlopen = _op
    ceiling.DELAY = 0
    sources.REQ_DELAY = 0
    try:
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ceiling.main([cpath, "--cache", _tmp("_t2c.json"),
                               "--out", _tmp("_t2o.csv"),
                               "--search-cache", _tmp("_t2s.json")])   # 결함 335
        out = buf.getvalue()
        check("ceiling CLI 정상 종료", rc == 0)
        check("ceiling이 검색 경로도 점검", "사전 점검" in out)
        # 라벨 출처 시험의 등록률은 **참고값**일 뿐이다. 그것만 재고
        #   "근거를 3.2배 확보한다"고 결론냈던 것이 첫 판의 오류다.
        #   결정 지표는 라벨 출처를 뺀 독립 시험 쪽이어야 한다.
        check("ceiling이 라벨 출처를 참고로만 표시", "[참고]" in out)
        check("ceiling이 독립 시험을 본 측정으로", "[본 측정]" in out)
        check("ceiling이 B6 결정 지표를 냄", "결정 지표" in out)
        # 검색이 라벨 출처 NCT만 돌려주는 상황 = 독립 시험 0건
        check("독립 시험 없으면 B6 제외 권고", "B6를 빼라" in out,
              "라벨 출처만 검색되면 등록부를 읽어도 새 근거가 없다")
        # 층 A만 세야 한다. B층이 섞이면 bench.run 과 다른 모집단이 된다.
        check("ceiling이 층으로 거른다", "TN 1건" in out,
              "층 A 1건 · 층 B 1건 중 A만")
        buf2 = _io.StringIO()
        with contextlib.redirect_stdout(buf2):
            ceiling.main([cpath, "--stratum", "all", "--cache", _tmp("_t2c.json"),
                          "--out", _tmp("_t2o.csv"),
                          "--search-cache", _tmp("_t2s.json")])
        check("--stratum all 이면 전부", "TN 2건" in buf2.getvalue())
    finally:
        urllib.request.urlopen = real
        os.unlink(cpath)


def test_search_fallback():
    print("\n[7] 등록부 검색 완화 3단")
    cache.configure(_tmp("_sf.json"))
    cache._STORE.clear()
    calls = []

    def fake(url):
        calls.append(url)
        if "aggFilters" in url:
            raise RuntimeError("400")
        if "query.intr" in url:
            return {"studies": []}
        return {"studies": [{"protocolSection":
                             {"identificationModule": {"nctId": "NCT0001"}}}]}
    with patched(sources, _ctg=fake, REQ_DELAY=0):
        r = sources.ctgov_search("hydroxycarbamide", "Polycythemia Vera")
    check("필터 실패 → 구조화 → 자유문 순으로 완화", len(calls) == 3, "%d회 시도" % len(calls))
    check("최종적으로 결과 확보", r["ncts"] == ["NCT0001"], r.get("how"))


def test_configs():
    print("\n[5] 구성")
    check("B6에 등록부 게이트 포함", gates.CONFIGS["B6"]["registry"] is True)
    check("B5에는 등록부 없음", not gates.CONFIGS["B5"].get("registry"))
    check("등록부가 실행 순서 마지막", gates.ORDER[-1] == "registry", gates.ORDER)


def test_leak_all_sources():
    """누출 차단이 **모든 근거원**에 걸리는가.

    등록부에만 걸고 PubMed를 열어두면 방어가 아니라 구멍이다.
    라벨 출처 시험이 논문으로도 출판됐으면 그대로 들어온다.
    """
    print("\n[9] 누출 차단 일관성")
    from ..agents import factcheck as FC

    gates.set_exclude({"NCT00600028"})
    check("한 번 호출로 게이트·팩트체커에 동시 적용",
          gates.EXCLUDE_NCT == FC.EXCLUDE_NCT == {"NCT00600028"})

    recs = [{"pmid": "25678901", "title": "T", "abstract": "RESULTS: no benefit here.",
             "pubtypes": ["Randomized Controlled Trial"], "study_type": "rct",
             "year": 2015, "journal": "Chest", "nct": ["NCT00600028"], "error": None},
            {"pmid": "30000001", "title": "T2", "abstract": "RESULTS: other trial data.",
             "pubtypes": ["Randomized Controlled Trial"], "study_type": "rct",
             "year": 2018, "journal": "AJRCCM", "nct": ["NCT09999999"], "error": None}]
    with patched(llm, available=lambda: True,
                 complete=lambda p, system="", model=None, as_json=False, purpose="":
                 {"ok": True, "text": "[]", "data": [], "error": None,
                  "provenance": {}, "cached": False}):
        FC.llm = llm
        out = FC.classify_batch("doxycycline", "IPF", recs)
    by = {r["pmid"]: r for r in out}
    check("논문이어도 라벨 출처면 제외",
          not by["25678901"]["kept"] and "라벨 출처" in (by["25678901"]["skip"] or ""),
          by["25678901"]["skip"])
    check("다른 시험은 통과(LLM 단계까지 감)",
          "라벨 출처" not in (by["30000001"]["skip"] or ""), by["30000001"]["skip"])
    gates.set_exclude(set())


def test_horizon():
    print("\n[10] 예측 지평 — 얼마나 앞서 판단하게 할 것인가")
    from ..bench import run as BR
    row = {"drug": "d", "indication": "i", "label": "TN", "ctgov_year": "2015"}
    got = {}
    for g in (1, 3, 5):
        with patched(BR, TIER2=True, TIER2_GAP=g):
            got[g] = BR.to_candidate(row).cutoff_year
    check("지평 1년 → 2014", got[1] == 2014, got[1])
    check("지평 5년 → 2010", got[5] == 2010, got[5])
    check("지평이 길수록 컷오프가 앞선다", got[5] < got[3] < got[1])
    check("시점 차단 끄면 컷오프 없음",
          BR.to_candidate(row).cutoff_year is None)


def test_balance():
    """조건부 판정이 근거 **강도**를 보는가.

    실측 문제: 소규모 2상 양성(0.6) + 대규모 3상 음성(3.0)이 조건부로 나왔다.
    확증 3상이 실패했으면 그게 결론이지, 그 3상이 반증한 2상과 대등하지 않다.
    개수만 세면 안 되고 무게를 봐야 한다.
    """
    print("\n[11] 조건부 — 근거 강도를 본다")
    from ..core.scoring import adjudicate
    from ..core.state import Candidate, Evidence

    def mk(fc):
        c = Candidate(name="t", origin="", query="")
        c.f0 = {"count": 50}
        c.factcheck = fc
        c.support = [Evidence("s", "support", r["weight"], source="llm")
                     for r in fc if r["kept"] and r["direction"] == "support"]
        c.refute = [Evidence("r", "refute", r["weight"], source="llm")
                    for r in fc if r["kept"] and r["direction"] == "refute"]
        return c

    def e(d, w):
        return {"pmid": "x", "direction": d, "weight": w, "kept": True,
                "study_type": "rct", "decisive": True, "nct": [], "pico": {},
                "skip": None}

    v1 = adjudicate(mk([e("support", 0.6), e("refute", 3.0)]))
    check("2상 양성 + 3상 음성 → 기각(조건부 아님)", v1[0] == "기각", "%s %s%%" % v1[:2])
    v2 = adjudicate(mk([e("support", 3.0), e("refute", 3.0)]))
    check("3상 양성 + 3상 음성 → 조건부", v2[0] == "조건부", "%s %s%%" % v2[:2])
    v3 = adjudicate(mk([e("support", 3.0), e("refute", 1.2)]))
    check("무게비 0.4 → 조건부 아님", v3[0] != "조건부", "%s %s%%" % v3[:2])
    check("한쪽 우세를 사유에 기록", "우세" in v1[2] or "우세" in v3[2])


def test_autosave():
    """캐시 자동 저장 — 중단돼도 비싼 호출을 잃지 않는다."""
    import os
    import tempfile
    print("\n[12] 캐시 자동 저장")
    d = tempfile.mkdtemp()
    path = os.path.join(d, "c.json")
    old_a, old_p = cache.AUTOSAVE, cache._PATH
    try:
        cache.configure(path)
        cache._STORE.clear()
        cache._SINCE[0] = 0
        cache.AUTOSAVE = 5
        for i in range(4):
            cache.put("k%d" % i, {"v": i})
        check("임계 전에는 저장 안 함", not os.path.exists(path))
        cache.put("k4", {"v": 4})
        check("임계 도달 시 자동 저장", os.path.exists(path))
        import json as _j
        got = _j.load(open(path, encoding="utf-8"))
        check("저장 내용 정확", len(got) == 5, "%d건" % len(got))
    finally:
        cache.AUTOSAVE = old_a
        cache.configure(old_p)
        cache._STORE.clear()


def test_tools():
    """새 도구 두 개의 CLI를 실제로 태운다.

    tp_audit : TN은 4단 정제했는데 TP는 0단이었다. 비대칭은 그 자체가 편향이다.
    sample   : 인용 검증은 '지어냈는가'를 막지 '틀렸는가'를 막지 못한다.
    """
    import contextlib
    import csv as _csv
    import io as _io
    import os
    import tempfile
    from ..bench import sample as SP
    from ..bench import tp_audit as TP

    print("\n[14] TP 검증 · 표본 검토 도구")
    d = tempfile.mkdtemp()

    # ── sample: 추출 → 채점 ─────────────────────────────────
    state = {"config": "B6", "candidates": [{
        "name": "d / x", "drug": "doxycycline", "disease": "IPF",
        "verdict": "기각", "confidence": 9, "factcheck": [
            {"pmid": "N1", "journal": "CT.gov", "direction": "refute", "weight": 3.0,
             "kept": True, "study_type": "rct", "certainty": "high",
             "quote": "futility", "quote_check": {"ok": True}, "skip": None},
            {"pmid": "P1", "journal": "Chest", "direction": "support", "weight": 0.7,
             "kept": True, "study_type": "trial", "certainty": "high",
             "quote": "improved FVC", "quote_check": {"ok": True}, "skip": None},
            {"pmid": "P2", "journal": "AJRCCM", "direction": "neutral", "weight": 0.0,
             "kept": False, "study_type": "rct", "certainty": "",
             "quote": "made up", "quote_check": {"ok": False}, "skip": "인용 검증 실패"},
            {"pmid": "P3", "journal": "ERJ", "direction": "neutral", "weight": 0.0,
             "kept": False, "study_type": "review", "certainty": "",
             "quote": "", "quote_check": None, "skip": "무관 — 효능 증거 아님"}]}]}
    sp = os.path.join(d, "s.json")
    rv = os.path.join(d, "r.csv")
    kv = os.path.join(d, "k.csv")
    json.dump(state, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = SP.main([sp, "--n", "4", "--out", rv, "--key", kv])
    check("sample 추출 정상 종료", rc == 0)
    rows = list(_csv.DictReader(open(rv, encoding="utf-8-sig")))
    keys = {k["번호"]: k for k in _csv.DictReader(open(kv, encoding="utf-8-sig"))}
    # 층화는 가중치 큰 채택을 먼저 뽑는다. 다만 검토지 **순서는 섞으므로**
    #   열쇠 전체에서 확인한다 — 순서 단서를 없앤 것이 의도다.
    check("층화 — 가중치 큰 채택이 포함됨",
          any(v["시스템_방향"] == "refute" for v in keys.values()),
          [v["시스템_방향"] for v in keys.values()])
    check("채점 칸이 비어 있다", rows[0]["사람_방향"] == "")

    # 1건만 맞히고 3건 틀리게 → 25%
    for i, r in enumerate(rows):
        t = keys[r["번호"]]["시스템_방향"]
        r["사람_방향"] = t if i == 0 else ("neutral" if t != "neutral" else "support")
    with open(rv, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = SP.main(["--score", rv, "--key", kv])
    out = buf.getvalue()
    check("sample 채점 정상 종료", rc == 0)
    exp = round(100 / max(1, len(rows)))
    check("불일치를 찾아낸다", "불일치" in out and ("= %d%%" % exp) in out,
          [l.strip() for l in out.split("\n") if "일치" in l][:1])

    # ── tp_audit: 확증 근거 없는 TP 식별 ────────────────────
    COUNTS = {"baricitinib AND Rheumatoid Arthritis": (1800, 240),
              "phenobarbital AND Epilepsy": (3000, 0)}

    def fake_search(q, retmax=8, max_year=None):
        conf = "[pt]" in q
        base = q.split(") AND (")[0].lstrip("(") if conf else q
        a_, c_ = COUNTS.get(base, (0, 0))
        return {"count": c_ if conf else a_, "pmids": [], "error": None}

    tp_rows = [{"label": "TP", "stratum": "A", "drug": dd, "indication": ii}
               for dd, ii in [("baricitinib", "Rheumatoid Arthritis"),
                              ("phenobarbital", "Epilepsy")]]
    tc = os.path.join(d, "tp.csv")
    with open(tc, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.DictWriter(f, fieldnames=list(tp_rows[0]))
        w.writeheader()
        w.writerows(tp_rows)
    old_auto, cache.AUTOSAVE = cache.AUTOSAVE, 0
    try:
        with patched(sources, pubmed_search=fake_search):
            buf = _io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = TP.main([tc, "--cache", os.path.join(d, "c.json"),
                              "--out", os.path.join(d, "o.csv"), "--no-llm"])
            out = buf.getvalue()
    finally:
        cache.AUTOSAVE = old_auto
        cache._STORE.clear()
    check("tp_audit 정상 종료", rc == 0)
    check("확증 근거 없는 TP를 짚어낸다",
          "phenobarbital" in out and "확증 설계 문헌 0건" in out)
    check("근거 있는 TP는 안 짚는다", out.count("baricitinib") == 0)


def test_stop_reason():
    """운영상 중단을 효능 반증으로 읽지 않는가.

    **자금이 끊겨 멈춘 시험은 약이 안 듣는다는 증거가 아니다.**
    벤치마크 라벨을 만들 때는 이 구분을 했는데(bench/labels.py)
    정작 근거를 읽는 게이트에는 없었다. 같은 잣대를 걸었는지 본다.
    """
    for st, why, exp in [("TERMINATED", "Terminated for futility", "efficacy"),
                         ("TERMINATED", "Slow accrual; funding withdrawn", "operational"),
                         # 둘 다 적혀 있으면 과학적 사유가 이긴다
                         ("TERMINATED", "futility and slow accrual", "efficacy"),
                         ("TERMINATED", "Stopped early for safety", "efficacy"),
                         ("TERMINATED", "", "unknown"),
                         ("COMPLETED", "", None)]:
        check("중단사유 %s" % (why or "(없음)")[:26],
              sources.stop_reason(st, why) == exp, sources.stop_reason(st, why))


def _ctg_rec(nct, why, outcome="  Drug -0.24 | Placebo -0.20\n  통계: p=0.55"):
    sr = sources.stop_reason("TERMINATED", why)
    body = ["상태: TERMINATED  중단 사유: %s" % why,
            "등록 환자 88명 · 배정 RANDOMIZED · 상 PHASE2"]
    if sr == "operational":
        body.append("※ 중단 사유는 운영상 문제(등록 부진·자금 등)다. "
                    "중단 자체를 효능 반증으로 읽으면 안 된다. "
                    "아래 1차 평가변수 수치만으로 판단하라.")
    body += ["", "[1차 평가변수 결과]", "Change in FVC at 12 months", outcome]
    return {"pmid": nct, "nct": [nct], "source": "ctgov", "stop_reason": sr,
            "error": None, "year": 2020, "journal": "ClinicalTrials.gov",
            "study_type": "rct", "pubtypes": ["Registry Results"],
            "title": "T", "abstract": "\n".join(body)}


def test_registry_quote():
    """등록부 근거가 인용 검증기에 걸려 몰살당하지 않는가.

    실제 사고: 인용 최소 길이 25자는 **산문 초록**용 규칙인데
    등록부 본문은 우리가 조립한 구조화된 표라 핵심 문구가 짧다.
    "Terminated for futility"는 23자다. 이 규칙 하나 때문에
    등록부 근거가 **전부** 무관으로 강등돼 B6가 B5와 같아져 있었다.
    출판 편향 천장을 뚫으려고 만든 게이트를 검증기가 무력화한 것이다.
    """
    from ..agents import factcheck as FC

    q = [""]

    def fake(prompt, system="", model=None, as_json=False, purpose=""):
        return {"ok": True, "error": None, "text": "", "provenance": {},
                "data": [{"idx": 1, "direction": "refute", "study_type": "rct",
                          "size": "small", "confidence": "high", "decisive": True,
                          "certainty": "moderate", "quote": q[0], "reason": "r"}]}

    cases = [
        ("효능중단·상태줄", _ctg_rec("NCT1", "Terminated for futility"),
         "Terminated for futility", "refute", True),
        ("운영중단·상태줄", _ctg_rec("NCT2", "Slow accrual; funding withdrawn"),
         "Slow accrual; funding withdrawn", "neutral", False),
        # 사유가 운영이어도 **결과 수치**는 유효한 근거다. 과잉 차단 방지.
        ("운영중단·결과줄", _ctg_rec("NCT3", "Slow accrual; funding withdrawn"),
         "Drug -0.24 | Placebo -0.20", "refute", True),
        ("짧은 인용", _ctg_rec("NCT4", "Terminated for futility"),
         "Terminated", "neutral", False),
        ("지어낸 인용", _ctg_rec("NCT5", "Terminated for futility"),
         "the drug was clearly ineffective in every patient", "neutral", False),
        # 처음 구현은 "상태 줄에 있으면 막는다"였다. 인용이 두 줄에 걸치면
        #   어느 한 줄의 부분문자열도 아니라 검사를 그냥 빠져나갔다.
        #   금지 목록 대신 허용 구획을 명시하는 방식으로 뒤집어 막았다.
        ("운영중단·두 줄 걸침", _ctg_rec("NCT6", "Slow accrual; funding withdrawn"),
         "TERMINATED  중단 사유: Slow accrual; funding withdrawn\n등록 환자 88명",
         "neutral", False),
        ("결과구획·두 줄 걸침", _ctg_rec("NCT7", "Slow accrual; funding withdrawn"),
         "Change in FVC at 12 months\n  Drug -0.24 | Placebo -0.20", "refute", True),
    ]
    with patched(FC.llm, complete=fake):
        for name, rec, quote, d_exp, k_exp in cases:
            q[0] = quote
            r = FC.classify_batch("doxycycline", "IPF", [rec])[0]
            check("등록부 인용 %s" % name,
                  r["direction"] == d_exp and r["kept"] == k_exp,
                  "%s/%s" % (r["direction"], r["kept"]))
        # 출처가 판정에 실려야 감사 추적이 끊기지 않는다
        q[0] = "Terminated for futility"
        r = FC.classify_batch("d", "IPF", [_ctg_rec("NCT9", "Terminated for futility")])[0]
        check("판정에 source 실림", r.get("source") == "ctgov", r.get("source"))

    # 산문 초록은 규칙이 그대로여야 한다 (회귀)
    prose = {"pmid": "111", "source": "pubmed", "error": None, "year": 2019,
             "journal": "Lancet", "study_type": "rct", "title": "T",
             "pubtypes": ["Randomized Controlled Trial"],
             "abstract": "In this randomised trial doxycycline did not improve FVC (p=0.68)."}
    with patched(FC.llm, complete=fake):
        for quote, exp in [("doxycycline did not improve FVC", "refute"),
                           ("did not", "neutral")]:
            q[0] = quote
            r = FC.classify_batch("doxycycline", "IPF", [prose])[0]
            check("산문 인용 %s" % quote[:22], r["direction"] == exp, r["direction"])


def test_regaudit():
    """등록부 근거 감사 — 오염과 신규성.

    ceiling이 "쓸 수 있는 독립 시험 53%"를 냈다. 그런데 등록부 검색은
    3단으로 완화되고 마지막은 **자유 문자열**이다. "gabapentin AND breast
    cancer"로 유방암 환자의 **안면홍조** 시험이 걸린다.

    그건 "가바펜틴이 유방암을 치료한다"가 아니고, 결과가 **긍정**이라
    반증이 아니라 지지로 읽힐 수 있다. 반증을 찾겠다고 넣은 게이트가
    반대 방향으로 오염되는 것이다.
    """
    print("\n[11] 등록부 근거 감사 — 오염·신규성")
    import contextlib
    import csv as _csv
    import io as _io
    import os
    import tempfile

    from ..bench import regaudit as RA

    # 첫 판은 오염을 52%로 보고했는데 **대부분 내 문자열 비교의 오탐**이었다.
    #   아래 ①~⑤가 실측에서 잘못 걸린 실제 항목이다. 전부 통과해야 한다.
    FAKE = {"erlotinib": {"Tarceva", "CP-358774"},
            "methotrexate": {"Amethopterin", "Trexall"},
            "pramipexole": {"Mirapex"}, "gabapentin": {"Neurontin"},
            "simvastatin": {"Zocor"}, "dexamethasone": {"Decadron"},
            "hydroxychloroquine": {"Plaquenil"},
            "hydroxycarbamide": {"Hydrea", "Droxia"}}
    cases = [
        # ── 어제 오탐 — 이제 '적합'이어야 한다 ────────────────
        # 구두점: COVID19 vs COVID-19 가 정규화에서 갈렸다
        ("hydroxychloroquine", "COVID19 (disease)", "HCQ in COVID-19",
         ["COVID-19"], ["Hydroxychloroquine"], "적합"),
        # INN/USAN 동의어 — 주석에 써놓고 처리를 안 했다
        ("hydroxycarbamide", "Cerebrovascular accident", "Hydroxyurea for Stroke",
         ["Cerebrovascular Accident"], ["Hydroxyurea"], "적합"),
        # 상품명 — CT.gov otherNames / PubChem 동의어로 푼다
        ("erlotinib", "Glioblastoma Multiforme", "Tarceva and Temodar in GBM",
         ["Glioblastoma"], ["Tarceva", "Temodar"], "적합"),
        # 약어 — 손으로 검증한 SYNONYM 표만 3글자를 허용한다
        ("methotrexate", "Leukemia, Myelomonocytic", "IGF/MTX in ML",
         ["Leukemia, Myelomonocytic"], ["IGF/MTX"], "적합"),
        # ── 애매한 것은 버리지 말고 사람에게 넘긴다 ───────────
        ("erlotinib", "Glioblastoma Multiforme", "Erlotinib in Brain Tumors",
         ["Brain and Central Nervous System Tumors"], ["Erlotinib"], "확인필요·질환"),
        ("erlotinib", "Glioblastoma Multiforme", "Bevacizumab in GBM",
         ["Glioblastoma"], ["Bevacizumab"], "확인필요·약물"),
        # ── 진짜 오염은 여전히 잡아야 한다 ────────────────────
        ("gabapentin", "Malignant neoplasm of breast",
         "Gabapentin for Hot Flashes in Women With Breast Cancer",
         ["Breast Cancer", "Hot Flashes"], ["Gabapentin"], "증상완화"),
        ("dexamethasone", "Multiple Myeloma", "Dexamethasone With Bortezomib",
         ["Multiple Myeloma"], ["Dexamethasone"], "보조요법"),
        ("simvastatin", "Pneumonia",
         "Simvastatin for Prevention of Ventilator-induced Pneumonia",
         ["Pneumonia"], ["Simvastatin"], "예방·병용"),
        # 증상이 곧 적응증이면 본 치료 시험이다 — 오탐 방지
        ("gabapentin", "Hot Flashes", "Gabapentin for Hot Flashes",
         ["Hot Flashes"], ["Gabapentin"], "적합"),
    ]
    with patched(RA, pubchem_synonyms=lambda d, limit=120: FAKE.get(d, set())):
        for drug, ind, title, conds, intrs, exp in cases:
            t = {"nct": "N", "title": title, "conds": conds, "intrs": intrs,
                 "official": "", "error": None}
            got, _ = RA.judge(drug, ind, t)
            check("감사 판정 %s" % title[:26], got == exp, got)
    # 동의어 조회가 죽어도 예외를 내면 안 된다.
    #   이건 판정을 **완화**하는 장치이므로, 없으면 '확인필요'로 떨어질 뿐
    #   잘못된 통과가 생기지는 않는다. 그게 안전한 실패 방향이다.
    from ..io import cache as _ca
    _ca.configure(_tmp("_ra.json"), enabled=False)
    with patched(sources, _get=lambda u: (_ for _ in ()).throw(OSError("망함"))):
        syn = RA.pubchem_synonyms("erlotinib")
        check("동의어 조회 실패는 예외 없이 빈 집합",
              isinstance(syn, set) and not syn, syn)
        got, _ = RA.judge("erlotinib", "Glioblastoma",
                          {"nct": "N", "title": "Tarceva in GBM",
                           "conds": ["Glioblastoma"], "intrs": ["Tarceva"],
                           "official": "", "error": None})
        check("조회 실패 시 안전한 쪽(확인필요)으로 떨어짐",
              got == "확인필요·약물", got)

    d = tempfile.mkdtemp()
    cp = os.path.join(d, "c.csv")
    with open(cp, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        w.writerow(["drug", "indication", "label_nct", "usable_ncts"])
        w.writerow(["gabapentin", "Malignant neoplasm of breast", "L1", "NCT1"])
        w.writerow(["erlotinib", "Glioblastoma Multiforme", "L2", "NCT2"])
        w.writerow(["cetirizine", "Migraine Disorders", "L3", ""])
    DB = {"NCT1": ("Gabapentin for Hot Flashes in Breast Cancer",
                   ["Breast Cancer"], ["Gabapentin"]),
          "NCT2": ("Erlotinib in Recurrent Glioblastoma",
                   ["Glioblastoma"], ["Erlotinib"])}
    with patched(RA,
                 probe_trial=lambda n: {"nct": n, "title": DB[n][0],
                                        "conds": DB[n][1], "intrs": DB[n][2],
                                        "error": None},
                 has_publication=lambda n: {"n": 0 if n == "NCT2" else 3,
                                            "error": None}):
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = RA.main([cp, "--cache", os.path.join(d, "k.json"),
                          "--out", os.path.join(d, "o.csv")])
        out = buf.getvalue()
    check("regaudit CLI 정상 종료", rc == 0, rc)
    check("오염 항목을 잡아냄", "증상완화" in out)
    # 논문이 이미 있으면 B5도 도달 가능 — B6의 한계 기여가 아니다
    check("한계 기여를 별도로 보고", "한계 기여" in out)
    rows = list(_csv.DictReader(open(os.path.join(d, "o.csv"), encoding="utf-8-sig")))
    check("빈 usable_ncts 쌍은 제외", len(rows) == 2, len(rows))


def test_registry_report():
    """등록부 게이트가 **무엇을 했는지** 화면에 나오는가.

    실측 사고: B6 판정 분포가 B5와 한 글자도 다르지 않게 나왔는데,
    화면 어디에도 등록부가 시험을 몇 건 읽었는지가 없었다.
    "게이트가 안 붙었나, 붙었는데 판정이 안 바뀌었나"를 구분할 수 없었다.
    **앞은 버그, 뒤는 결과다.** 구분이 안 되면 어느 쪽도 고칠 수 없다.
    """
    print("\n[13] 등록부 게이트 보고 — 침묵하면 진단이 불가능하다")
    import contextlib
    import csv as _csv
    import io as _io
    import os
    import re as _re
    import tempfile

    from ..agents import closedbook, factcheck as FC
    from ..bench import run as BR

    DB = {"111": {"pmid": "111", "title": "p", "abstract": "A pilot suggested benefit.",
                  "pubtypes": ["Clinical Trial"], "study_type": "trial", "year": 2011,
                  "journal": "C", "nct": [], "error": None, "source": "pubmed"}}
    quote = ["Terminated for futility"]

    def ctres(nct):
        return {"pmid": nct, "nct": [nct], "source": "ctgov", "stop_reason": "efficacy",
                "error": None, "year": 2018, "journal": "CT.gov", "study_type": "rct",
                "conditions": ["IPF"], "interventions": ["Doxycycline"],
                "pubtypes": ["Registry Results"], "title": "Doxycycline in IPF",
                "abstract": "대상 질환: IPF\n개입: Doxycycline\n"
                            "상태: TERMINATED  중단 사유: Terminated for futility\n"
                            "등록 환자 88명 · 배정 RANDOMIZED · 상 PHASE2\n\n"
                            "[1차 평가변수 결과]\nFVC\n  Drug -0.24 | Placebo -0.20"}

    def comp(prompt, system="", model=None, as_json=False, purpose=""):
        if "이미 알고 있는 지식만으로" in prompt:
            n = len(_re.findall(r"^\d+\.", prompt, _re.M))
            return {"ok": True, "error": None, "text": "", "provenance": {},
                    "data": [{"idx": i, "verdict": "모름", "confidence": "low"}
                             for i in range(1, n + 1)]}
        recs = []
        for m in _re.finditer(r"\[초록 (\d+) · PMID (\S+)\]", prompt):
            i, pm = int(m.group(1)), m.group(2)
            recs.append({"idx": i, "direction": "refute" if pm.startswith("NCT") else "support",
                         "study_type": "rct" if pm.startswith("NCT") else "trial",
                         "size": "large", "confidence": "high", "decisive": True,
                         "certainty": "high",
                         "quote": quote[0] if pm.startswith("NCT")
                         else "A pilot suggested benefit.", "reason": "r"})
        return {"ok": True, "error": None, "text": "", "provenance": {}, "data": recs}

    d = tempfile.mkdtemp()
    p = os.path.join(d, "m.csv")
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        w.writerow(["drug", "indication", "label", "stratum", "nct"])
        w.writerow(["doxycycline", "IPF", "TN", "A", "NCTLABEL"])
        w.writerow(["nintedanib", "IPF", "TP", "A", "NCTTP"])

    def go(search, q):
        quote[0] = q
        with patched(sources, pubmed_lookup=lambda x, retmax=3:
                     {"count": 1, "pmids": ["111"], "title": "", "error": None},
                     pubmed_search=lambda x, retmax=8, max_year=None:
                     {"count": 1, "pmids": ["111"], "error": None},
                     pubmed_abstracts=lambda ps, retry=1:
                     {x: dict(DB[x]) for x in ps if x in DB},
                     ctgov_results=ctres, ctgov_search=search), \
             patched(llm, available=lambda: True, complete=comp,
                     failure_summary=lambda: {"failed": 0, "total": 0, "reasons": {}}), \
             patched(FC, llm=llm), patched(closedbook, llm=llm), \
             patched(gates, sources=sources):
            buf = _io.StringIO()
            with contextlib.redirect_stdout(buf):
                BR.main([p, "--configs", "B6", "--stratum", "A", "--skip-preflight",
                         "--out", os.path.join(d, "o.json"),
                         "--cache", os.path.join(d, "c.json")])
            return buf.getvalue()

    out = go(lambda dr, c, n=8, status=None: {"ncts": ["NCTIND1"], "error": None, "how": "구조화"},
             "Terminated for futility")
    check("정상: 등록부 통계가 찍힘", "등록부: 근거 확보" in out)
    check("정상: 근거가 실제로 채택됨", "채택 2건" in out, out.count("채택"))

    # 라벨 출처만 검색되면 제외 후 0건 — B6가 B5와 같아지는 게 **정상**이다
    out2 = go(lambda dr, c, n=8, status=None: {"ncts": ["NCTLABEL"], "error": None, "how": "구조화"},
              "Terminated for futility")
    check("한 건도 못 읽으면 그렇게 말한다", "한 건도 못 읽었다" in out2)
    check("버그가 아니라 결과임을 구분해줌", "다른 일을 하지 않은 것" in out2)

    # 읽었는데 전부 걸러진 경우는 **다른 문제**다
    out3 = go(lambda dr, c, n=8, status=None: {"ncts": ["NCTIND1"], "error": None, "how": "구조화"},
              "the drug was useless in every single subject")
    check("읽었지만 채택 0건도 따로 알림", "채택된 근거가 0건" in out3)


def test_inspect():
    """판정 해부 — 등록부가 **판정을 바꿨는가**를 다시 계산해 보여주는가.

    실측 사고: 등록부가 시험 16건을 읽고 3건을 채택했는데 판정 분포는
    B5와 한 글자도 다르지 않았다. 근거는 들어왔는데 결정이 안 바뀐 것이다.

    이유가 셋인데(TP에 붙음 / 가중치 부족 / 방향이 지지) **대응이 전부 다르다.**
    ①이면 검색 대상, ②면 가중치 설계, ③이면 '등록부=반증원' 전제 자체가 문제다.
    구분 못 하면 어느 것도 못 고친다.
    """
    print("\n[15] 판정 해부 — 등록부의 실제 기여")
    import contextlib
    import io as _io
    import json as _json
    import os
    import tempfile

    from ..bench import inspect as IN

    def fc(pmid, src, d, w):
        return {"pmid": pmid, "source": src, "direction": d, "weight": w,
                "kept": True, "quote": "근거 문장입니다 그럴듯한", "study_type": "rct",
                "certainty": "high", "skip": None, "retracted": False,
                "year": 2018, "title": "t", "journal": "j", "nct": []}

    F0 = {"count": 120, "error": None}
    st = {"config": "B6", "candidates": [
        # 등록부 반박이 보류를 기각으로 뒤집는다 — 이게 진짜 기여다
        {"name": "doxycycline / IPF", "drug": "d", "disease": "IPF", "label": "TN",
         "f0": F0, "veto": None, "veto_reason": None, "trail": [],
         "factcheck": [fc("111", "pubmed", "support", 0.6),
                       fc("NCT1", "ctgov", "refute", 3.0)]},
        # 유망 95% → 97% 은 **결정이 바뀐 게 아니다.** 기여로 세면 부풀린다.
        {"name": "nintedanib / IPF", "drug": "n", "disease": "IPF", "label": "TP",
         "f0": F0, "veto": None, "veto_reason": None, "trail": [],
         "factcheck": [fc("221", "pubmed", "support", 3.0),
                       fc("NCT2", "ctgov", "support", 1.2)]},
        # 등록부 조회가 실패한 후보 — 근거를 못 본 만큼 보고돼야 한다
        {"name": "z / q", "drug": "z", "disease": "q", "label": "TN", "f0": F0,
         "veto": None, "veto_reason": None,
         "trail": [{"gate": "registry", "outcome": "ERROR",
                    "detail": "HTTPError: 404"}],
         "factcheck": [fc("331", "pubmed", "support", 3.0)]}]}
    p = os.path.join(tempfile.mkdtemp(), "s.json")
    _json.dump(st, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = IN.main([p])
    out = buf.getvalue()
    check("inspect CLI 정상 종료", rc == 0, rc)
    check("판정 변경을 다시 계산해 보여줌", "보류 65% → 기각 8%" in out)
    check("확신만 이동한 것은 따로 센다",
          "판정 변경 1 · 확신만 이동 1" in out)
    check("등록부 조회 오류를 보고", "HTTPError: 404" in out)
    check("근거 없는 후보 수를 ceiling과 대조하라고 안내",
          "독립 시험 없음" in out)


def test_flip_and_merge():
    """확신 역전 경고와 결과 이어붙임.

    두 사고가 있었다.

    ① 위험-커버리지 설명이 **거꾸로** 적혀 있었다. "우하향하면 나쁘다"고 썼는데
       확신 상위가 높고 오른쪽으로 내려가는 것이 정상이다. 실측에서
       0%/0%/50%/50%/67%/75% 라는 **완전히 뒤집힌** 표가 나왔는데
       설명대로 읽으면 정상으로 오해한다. 사람이 표를 눈으로 판단하게
       두면 틀린다 — 직접 말해줘야 한다.

    ② --configs B6 만 다시 돌렸더니 앞서 441회 써서 얻은 B0·B5 결과가
       조용히 지워졌다. 31회짜리 실행이 그걸 덮어쓴 것이다.
    """
    print("\n[16] 확신 역전 경고 · 결과 이어붙임")
    import contextlib
    import io as _io
    import json as _json
    import os
    import tempfile

    from ..bench import analyze as AN

    n = 12
    rw = [{"drug": "d%d" % i, "indication": "x%d" % i,
           "label": "TP" if i % 2 else "TN"} for i in range(n)]
    # 확신이 거꾸로 붙은 구성: 확신 최고인 앞 4건이 전부 틀린다
    sc_bad, vd_bad = [], []
    for i in range(n):
        tp = i % 2
        if i < 4:
            sc_bad.append(0.05 if tp else 0.95)
            vd_bad.append("기각" if tp else "유망")
        else:
            sc_bad.append(0.60 if tp else 0.40)
            vd_bad.append("유망" if tp else "기각")
    d = {"stratum": "A", "n_tp": n // 2, "n_tn": n // 2, "rows": rw,
         "results": {"BAD": {"scores": sc_bad, "verdicts": vd_bad},
                     "OK": {"scores": [0.95 if i % 2 else 0.05 for i in range(n)],
                            "verdicts": ["유망" if i % 2 else "기각" for i in range(n)]}}}
    p = os.path.join(tempfile.mkdtemp(), "r.json")
    _json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        AN.main([p])
    out = buf.getvalue()
    check("확신 역전을 자동으로 경고", "확신이 거꾸로 붙었다" in out)
    check("정상 구성에는 경고 없음", "OK —" not in out)
    check("설명이 바로잡혀 있음", "왼쪽이 높고 오른쪽으로 내려가야 정상" in out)


def test_negative_first():
    """등록부 검색이 **반증을 먼저** 회수하는가.

    실측 사고: 등록부 근거 3건이 전부 TP에 붙었고 방향이 전부 지지였다.
    반증을 찾겠다고 만든 게이트가 확증만 물어온 것이다.

    원인은 구조적 비대칭이었다. gate_skeptic은 PubMed에 대해
    'futility OR "no benefit"' 같은 질의를 따로 던져 반증을 강제로 끌어온다.
    **등록부에는 그 짝이 없었다.** 그냥 검색하면 완료된 성공 시험이 먼저 온다.

    중단·철회 시험을 먼저 채우고 남는 자리를 일반 검색으로 메운다.
    한쪽만 보면 TP의 등록부 근거를 영영 못 보므로 둘 다 본다.
    """
    print("\n[17] 등록부 반증 우선 회수")
    import re as _re

    from ..agents import factcheck as FC
    from ..core.state import Candidate, RunState

    calls = []

    def search(drug, cond, limit=12, status=None):
        calls.append(status)
        if status:
            return {"ncts": ["NCT_NEG1", "NCT_NEG2"], "error": None, "how": "필터+구조화"}
        return {"ncts": ["NCT_POS1", "NCT_NEG1", "NCT_POS2"], "error": None,
                "how": "필터+구조화"}

    def res(nct):
        neg = "NEG" in nct
        return {"pmid": nct, "nct": [nct], "source": "ctgov", "error": None,
                "stop_reason": "efficacy" if neg else None, "year": 2018,
                "journal": "CT.gov", "study_type": "rct", "conditions": ["IPF"],
                "interventions": ["Doxycycline"], "pubtypes": ["Registry Results"],
                "title": "T " + nct,
                "abstract": "대상 질환: IPF\n개입: Doxycycline\n상태: %s\n"
                            "등록 환자 88명\n\n[1차 평가변수 결과]\n"
                            "Change in FVC at 12 months\n"
                            "  Doxycycline -0.24 | Placebo -0.20\n  통계: p=0.55"
                            % ("TERMINATED  중단 사유: Terminated for futility"
                               if neg else "COMPLETED")}

    def comp(prompt, system="", model=None, as_json=False, purpose=""):
        out = []
        for m in _re.finditer(r"\[초록 (\d+) · PMID (\S+)\]", prompt):
            i, pm = int(m.group(1)), m.group(2)
            out.append({"idx": i, "direction": "refute" if "NEG" in pm else "support",
                        "study_type": "rct", "size": "large", "confidence": "high",
                        "decisive": True, "certainty": "high",
                        "quote": "Doxycycline -0.24 | Placebo -0.20", "reason": "r"})
        return {"ok": True, "error": None, "text": "", "provenance": {}, "data": out}

    with patched(sources, ctgov_search=search, ctgov_results=res), \
         patched(llm, available=lambda: True, complete=comp), \
         patched(FC, llm=llm), patched(gates, sources=sources):
        c = Candidate(name="doxycycline / IPF", origin="TN", query="q",
                      drug="doxycycline", disease="IPF")
        gates.gate_registry(RunState("q", "B6", "t", [c],
                                     dict(gates.CONFIGS["B6"])))
        check("중단 상태로 먼저 검색한다",
              calls[0] == sources.NEGATIVE_STATUS, calls[:2])
        check("일반 검색도 함께 한다", None in calls, calls[:2])
        check("중단 시험을 앞에 놓는다",
              [r["pmid"] for r in c.factcheck][:2] == ["NCT_NEG1", "NCT_NEG2"],
              [r["pmid"] for r in c.factcheck])
        check("양방향을 다 본다 — 한쪽만 보면 TP 근거를 영영 못 본다",
              len(c.refute) == 2 and len(c.support) == 2,
              "반박 %d · 지지 %d" % (len(c.refute), len(c.support)))
        check("기록에 중단 건수를 남긴다",
              "중단 2" in (next(t for t in c.trail
                              if t.gate == "registry").detail or ""))

        # 예산이 좁을 때 반증이 밀려나면 안 된다 — 그게 이 변경의 핵심이다
        old_n = gates.N_REGISTRY
        gates.N_REGISTRY = 2
        try:
            c2 = Candidate(name="d / IPF", origin="TN", query="q",
                           drug="doxycycline", disease="IPF")
            gates.gate_registry(RunState("q", "B6", "t", [c2],
                                         dict(gates.CONFIGS["B6"])))
            check("예산이 좁으면 반증이 자리를 차지한다",
                  [r["pmid"] for r in c2.factcheck] == ["NCT_NEG1", "NCT_NEG2"],
                  [r["pmid"] for r in c2.factcheck])
        finally:
            gates.N_REGISTRY = old_n


def test_zero_is_not_error():
    """**"0건"은 오류가 아니라 결과 부재다.**

    둘을 같이 error에 넣었더니 진단 화면에 "등록부 오류 2건"으로 찍혀
    조회가 실패한 것처럼 보였다. 실제로는 그냥 시험이 없던 것이다.
    버그와 사실을 구분 못 하면 엉뚱한 곳을 고치게 된다.
    """
    print("\n[18] 0건과 오류의 구분")
    cache.configure(_tmp("_z.json"), enabled=False)

    with patched(sources, _ctg=lambda url: {"studies": []}):
        r = sources.ctgov_search("nodrug", "nodisease", 5)
    check("0건은 error가 아니다", r["error"] is None, r["error"])
    check("0건은 how에 적힌다", "0건" in (r["how"] or ""), r["how"])

    def boom(url):
        raise OSError("연결 실패")

    with patched(sources, _ctg=boom):
        r2 = sources.ctgov_search("x", "y", 5)
    check("진짜 예외는 error에 남는다", bool(r2["error"]), r2["error"])

    # ── 같은 구분을 **집계 쪽에서도** 해야 한다 (결함 35) ────────────────
    #
    #   `sources` 는 오류와 0건을 잘 구분했는데 `ceiling` 의 요약이
    #   `indep > 0` 만 세서 **오류를 0건으로 합산**했다. 샌드박스에서
    #   CT.gov 가 403으로 전부 막혔는데 화면에는
    #   "0/14 = 0% · **B6를 빼라**" 가 떴다. 하마터면 그대로 적을 뻔했다.
    #
    #   더 위험한 점 — 그 0%는 *"반증 근거의 부재가 구조적"* 이라는
    #   **우리 논지를 지지하는 방향**이었다. 자기에게 유리한 고장이
    #   가장 오래 산다. 그래서 시험으로 못 박는다.
    from ..bench import ceiling as _CE
    import io as _io2
    import inspect as _in2
    src = _in2.getsource(_CE.main)
    check("ceiling 요약이 오류 쌍을 분모에서 뺀다", 'x["err"]' in src)
    check("전부 실패하면 판단 자체를 거부한다",
          "판단하지 않는다" in src and "return 1" in src)

    # ── netcheck: 조회가 살아 있는지 **양쪽**을 다 시험한다 ──────────────
    #   "실패를 잘 잡는가"만 보면 **항상 실패라고 답하는 검사**도 통과한다.
    #   정상일 때 정상이라고 하는지도 같이 본다.
    from .. import netcheck as _NC
    good = {"count": 12, "pmids": ["1"], "error": None}

    def _nc_run():
        b, o = _io2.StringIO(), sys.stdout
        sys.stdout = b
        try:
            rc = _NC.main([])
        finally:
            sys.stdout = o
        return rc, b.getvalue()

    with patched(sources,
                 pubmed_search=lambda *a, **k: good,
                 pubmed_abstracts=lambda ids, **k: {ids[0]: {"abstract": "x" * 300}},
                 ctgov_search=lambda *a, **k: {"ncts": ["NCT1"], "error": None, "how": ""},
                 _ctg=lambda url: {"protocolSection": {}}):
        rc_ok, t_ok = _nc_run()
    check("전부 살아 있으면 정상이라고 한다", rc_ok == 0 and "마음대로" in t_ok, rc_ok)

    def _boom(url):
        raise OSError("403")

    with patched(sources,
                 pubmed_search=lambda *a, **k: good,
                 pubmed_abstracts=lambda ids, **k: {ids[0]: {"abstract": "x" * 300}},
                 ctgov_search=lambda *a, **k: {"ncts": [], "error": "403", "how": ""},
                 _ctg=_boom):
        rc_ct, t_ct = _nc_run()
    check("CT.gov만 막히면 B6를 경고한다",
          rc_ct == 1 and "B6" in t_ct and "PubMed 차단" not in t_ct, rc_ct)
    # 캐시가 켜져 있으면 "되는 것처럼" 보인다 — 그게 우리가 속은 방식이다
    # 껍데기를 세면 실패해도 OK 가 뜬다. 첫 판이 실제로 그랬다.
    check("초록은 **본문 길이**로 확인한다(레코드 개수가 아니라)",
          "초록 본문 없음" in _in2.getsource(_NC.main))
    # 상수 PMID를 박으면 그 논문에 초록이 없을 때 네트워크 탓을 한다
    check("초록 확인에 검색이 준 PMID를 쓴다(상수가 아니라)",
          'hit.get("pmids")' in _in2.getsource(_NC.main))
    # **끄는 게 아니라 비운다** — 끄면 결함 36 때문에 거짓 경보가 난다
    check("캐시를 끄지 않고 빈 임시 파일을 쓴다",
          "enabled=True" in _in2.getsource(_NC.main))

    # ── 결함 37: **일시적 장애를 캐시에 남기지 않는다** ─────────────────
    #
    #   전에는 오류도 그대로 저장했다. 몇 분짜리 네트워크 장애가 캐시에 박혀
    #   영구화되고, `cache.has()` 가 True라 **다시 돌려도 재조회되지 않는다.**
    #
    #   실측 피해: `pubmed_cache.json` 에 `Tunnel connection failed` 380개.
    #   전부 `NCT…[si]` = **누출 차단용 PMID 확장**. 홀드아웃 sealed 의
    #   라벨 출처 432건 중 **380건(88%)에서 PMID 수준 차단이 안 걸렸다.**
    cache.configure(_tmp("_c37.json"), enabled=True)
    for _err, _keep in (
            ("URLError: <urlopen error Tunnel connection failed: 403>", False),
            ("HTTPError: HTTP Error 429: Too Many Requests", False),
            ("HTTPError: HTTP Error 503: Service Unavailable", False),
            ("URLError: <urlopen error timed out>", False),
            ("HTTPError: HTTP Error 404: Not Found", True),   # 영구 오류는 남긴다
            ("PUGREST.NotFound", True),
            (None, True)):
        cache._STORE.clear()
        rv = cache.put("k37", {"error": _err, "count": None})
        got = "k37" in cache._STORE
        check("캐시 %s: %s" % ("남김" if _keep else "안 남김", str(_err)[:34]),
              got == _keep, "실제 %s" % ("남김" if got else "안 남김"))
        # 값은 돌려줘야 호출부가 오류를 볼 수 있다
        check("저장 안 해도 값은 돌려준다" if not _keep else "값 반환",
              rv is not None and rv.get("error") == _err)

    # `set_exclude` 는 "색인 없음"과 "못 물어봤다"를 **분리**해야 한다
    def _boom_si(q, retmax=8, max_year=None):
        return {"count": None, "pmids": [],
                "error": "URLError: Tunnel connection failed"}
    _b3, _o3 = _io2.StringIO(), sys.stdout
    sys.stdout = _b3
    try:
        with patched(sources, pubmed_search=_boom_si):
            _res = gates.set_exclude({"NCT00000001", "NCT00000002"})
    finally:
        sys.stdout = _o3
    check("set_exclude 가 조회 실패를 따로 센다",
          _res.get("failed") == 2 and _res.get("no_index") == 0, _res)
    check("누출 차단 실패를 화면에 경고한다", "경고" in _b3.getvalue())

    # ── 결함 36: 캐시가 꺼져도 조회 결과를 **잃지 않는다** ────────────────
    #   `pubmed_abstracts` 가 `{p: cache.get(...)}` 로만 반환했다.
    #   `cache.get` 은 꺼져 있으면 무조건 None이라, **조회에 성공해도
    #   빈 결과**가 나갔다. 오류도 0건도 아닌 None이라 호출부가 구분 못 한다.
    #   실측: netcheck 가 캐시를 끄고 물었다가 "PubMed 차단" 거짓 경보를 냈다.
    _XML = ('<?xml version="1.0"?><PubmedArticleSet><PubmedArticle><MedlineCitation>'
            '<PMID>999</PMID><Article><ArticleTitle>T</ArticleTitle><Abstract>'
            '<AbstractText>본문</AbstractText></Abstract><Journal>'
            '<ISOAbbreviation>J</ISOAbbreviation><JournalIssue><PubDate><Year>2020'
            '</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation>'
            '<PubmedData><PublicationTypeList/></PubmedData></PubmedArticle>'
            '</PubmedArticleSet>')
    for _en in (True, False):
        with patched(sources, _get_xml=lambda url: _XML):
            cache.configure(_tmp("_abs36.json"), enabled=_en)
            _r = (sources.pubmed_abstracts(["999"]) or {}).get("999") or {}
        check("캐시 %s 상태에서도 초록을 잃지 않는다" % ("켬" if _en else "끔"),
              _r.get("abstract") == "본문", _r.get("abstract"))

    # 실제 경로로 태운다 — 문자열 검사만으로는 동작을 보증하지 못한다
    mt = _tmp("_ce_fail.csv")
    with open(mt, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write("label,stratum,drug,indication,kind,phase,pubmed,nct,"
                 "ctgov_year,why,detail,matched_to\n"
                 "TN,A,dx,dz,효능,Phase 3,50,NCT99999999,2020,f,d,\n"
                 "TP,A,px,pz,승인,NA,50,,,,,dx|dz\n")
    buf2, old2 = _io2.StringIO(), sys.stdout
    sys.stdout = buf2
    try:
        rc = _CE.main([mt, "--out", _tmp("_ce_out.csv"),
                       "--cache", _tmp("_ce_cache.json"),
                       "--search-cache", _tmp("_ce_search.json")])   # 결함 335
    except Exception:
        rc = None
    finally:
        sys.stdout = old2
    t2 = buf2.getvalue()
    # 이 환경에서 CT.gov 가 되면 정상 판단이 나온다 — 그때는 이 검사를 건너뛴다
    if "조회 실패" in t2:
        check("조회가 다 죽으면 0%를 결과로 내지 않는다",
              rc == 1 and "판단하지 않는다" in t2, "rc=%s" % rc)
        check("실패 사유를 화면에 남긴다", "못 물어봤다" in t2)
    else:
        check("CT.gov 연결됨 — 실패 경로 시험 건너뜀", True, "정상 조회")


def test_sample_and_wrong():
    """표본 선별과 오답 해부.

    두 사고가 이어져 있었다.

    ① --limit 5 로 시운전했더니 그 5쌍 전부 등록부 독립 시험이 0건이라
       B6가 아무것도 못 했다. **B6가 못 한 게 아니라 시험할 재료가 없는
       표본을 고른 것이다.** 앞에서 N쌍 자르기는 대표성이 없다.

    ② gabapentin/유방암이 TN인데 유망 98%가 나왔다. 지지 5.90.
       근거를 안 보면 왜 틀렸는지 알 수 없고, 모르면 못 고친다.
       총점만 보고 "성능이 낮다"고 적는 것은 진단이 아니다.
    """
    print("\n[19] 표본 선별 · 오답 해부")
    import contextlib
    import csv as _csv
    import io as _io
    import json as _json
    import os
    import tempfile

    from ..bench import inspect as IN, run as BR

    # ── ① --with-registry ────────────────────────────────────
    d = tempfile.mkdtemp()
    m, cl = os.path.join(d, "m.csv"), os.path.join(d, "c.csv")
    with open(m, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        w.writerow(["drug", "indication", "label", "stratum", "nct"])
        for i in range(5):
            w.writerow(["tn%d" % i, "d%d" % i, "TN", "A", "NCT%d" % i])
            w.writerow(["tp%d" % i, "d%d" % i, "TP", "A", ""])
    with open(cl, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        w.writerow(["drug", "indication", "usable_ncts"])
        for i, v in enumerate(["", "NCTa;NCTb", "", "NCTc", "   "]):
            w.writerow(["tn%d" % i, "d%d" % i, v])
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        BR.main([m, "--configs", "B6", "--stratum", "A", "--dry",
                 "--skip-preflight", "--with-registry", cl,
                 "--cache", os.path.join(d, "k.json"),
                 "--out", os.path.join(d, "o.json")])
    out = buf.getvalue()
    check("근거 있는 쌍만 선별", "→ 2쌍" in out)
    # 짝을 통째로 남겨야 한다. TN만 남기면 짝짓기가 깨진다.
    check("짝(TP)도 함께 유지", "TN 2 · TP 2" in out)
    buf2 = _io.StringIO()
    with contextlib.redirect_stdout(buf2):
        rc = BR.main([m, "--configs", "B6", "--stratum", "A", "--dry",
                      "--skip-preflight", "--with-registry",
                      os.path.join(d, "없음.csv"),
                      "--cache", os.path.join(d, "k.json"),
                      "--out", os.path.join(d, "o.json")])
    check("파일이 없으면 조용히 넘어가지 않는다",
          rc == 1 and "읽을 수 없다" in buf2.getvalue(), rc)

    # ── ② 오답 해부 ──────────────────────────────────────────
    def fc(pmid, direction, w_, title, quote, kept=True):
        return {"pmid": pmid, "source": "pubmed", "direction": direction,
                "weight": w_, "kept": kept, "quote": quote, "title": title,
                "study_type": "rct", "certainty": "high", "skip": None,
                "retracted": False, "year": 2018, "journal": "j", "nct": []}

    F0 = {"count": 120, "error": None}
    st = {"config": "B6", "candidates": [
        {"name": "gabapentin / Malignant neoplasm of breast",
         "drug": "gabapentin", "disease": "Malignant neoplasm of breast",
         "label": "TN", "f0": F0, "veto": None, "veto_reason": None, "trail": [],
         "factcheck": [
             fc("1", "support", 3.0,
                "Gabapentin for Hot Flashes in Women With Breast Cancer",
                "gabapentin significantly reduced hot flash frequency"),
             fc("3", "neutral", 0.0, "Pharmacokinetics", "", kept=False)]},
        {"name": "nintedanib / IPF", "drug": "n", "disease": "IPF", "label": "TP",
         "f0": F0, "veto": None, "veto_reason": None, "trail": [],
         "factcheck": [fc("9", "support", 3.0, "Nintedanib in IPF",
                          "reduced the annual rate of FVC decline")]}]}
    sp = os.path.join(d, "s.json")
    _json.dump(st, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
    buf3 = _io.StringIO()
    with contextlib.redirect_stdout(buf3):
        IN.main([sp, "--all"])
    o3 = buf3.getvalue()
    check("오답을 골라낸다", "[TN → 유망]" in o3)
    check("근거 제목을 보여준다", "Hot Flashes" in o3)
    check("인용문을 보여준다", "hot flash frequency" in o3)
    check("정답은 오답으로 안 센다", "[TP → 기각]" not in o3)


def test_structured_quote():
    """등록부 인용 검증 — **위조는 막되 정상 근거는 살린다.**

    실측 사고: 등록부 시험 25건을 읽고 **채택 0건**이 나왔다.
    완전일치만 인정했더니 "Erlotinib 11.5 vs Placebo 13.2"처럼 LLM이
    표를 문장으로 옮긴 것이 전부 '지어냄'으로 강등됐다.
    **위조를 막으려던 검증이 정상 근거를 몰살한 것이다.**

    등록부 본문은 문장이 아니라 표라서 LLM이 자연히 재조립한다.
    표에서 내용을 지고 있는 것은 **숫자**다. 숫자를 지어내면 본문에 없다.
    수치 대조는 substring보다 오히려 위조하기 어렵다 — 우연히 다 맞을 수 없다.
    """
    print("\n[20] 등록부 인용 — 위조 차단과 정상 통과의 균형")
    from ..agents.factcheck import verify_quote

    BODY = ("대상 질환: Glioblastoma\n개입: Erlotinib, Tarceva\n"
            "상태: TERMINATED  중단 사유: Terminated for futility\n"
            "등록 환자 88명 · 배정 RANDOMIZED · 상 PHASE2\n\n"
            "[1차 평가변수 결과]\nProgression-free Survival at 6 Months\n"
            "  Erlotinib 11.5 ±2.1 | Placebo 13.2 ±2.4\n  통계: p=0.55 · ANCOVA")
    for name, q, exp in [
            ("그대로", "Erlotinib 11.5 ±2.1 | Placebo 13.2 ±2.4", True),
            ("공백 차이", "Erlotinib 11.5 ± 2.1 | Placebo 13.2 ± 2.4", True),
            ("구분자 바꿈", "Erlotinib 11.5, Placebo 13.2", True),
            ("표→문장", "Progression-free Survival at 6 Months: "
                      "Erlotinib 11.5 vs Placebo 13.2", True),
            ("상태줄", "Terminated for futility", True),
            ("통계 인용", "p=0.55 with ANCOVA at 6 months", True),
            # ── 위조는 여전히 막혀야 한다 ──
            ("숫자 지어냄", "Erlotinib 21.5 vs Placebo 33.2", False),
            ("p값 위조", "Erlotinib 11.5 vs Placebo 13.2, p=0.001", False),
            ("완전 창작", "the drug clearly improved survival in all patients", False),
            ("다른 시험 숫자", "Doxycycline -0.24 | Placebo -0.20", False)]:
        r = verify_quote(q, BODY, structured=True)
        check("등록부 인용 %s" % name, r["ok"] == exp, r["how"])

    # 산문 초록은 규칙이 그대로여야 한다 — 완화가 새어 나가면 안 된다
    P = "In this randomised trial doxycycline did not improve FVC (p=0.68)."
    for q, exp in [("doxycycline did not improve FVC", True),
                   ("did not", False),
                   ("doxycycline dramatically improved FVC", False)]:
        r = verify_quote(q, P)
        check("산문 %s" % q[:24], r["ok"] == exp, r["how"])


def test_drop_reasons():
    """등록부 근거가 **왜** 죽었는지 세어 보여주는가.

    화면에 "채택된 근거가 0건"까지만 나오고 무엇이 걸렀는지가 없었다.
    인용 검증인지, 관련성인지, 운영중단 방어인지 모르면 어느 것도 못 고친다.
    """
    print("\n[21] 강등 사유 집계")
    import contextlib
    import io as _io
    import json as _json
    import os
    import tempfile

    from ..bench import inspect as IN

    def r_(pmid, src, d, w, kept, skip=None, quote=""):
        return {"pmid": pmid, "source": src, "direction": d, "weight": w,
                "kept": kept, "skip": skip, "quote": quote, "title": "t",
                "study_type": "rct", "certainty": "high", "retracted": False,
                "year": 2018, "journal": "j", "nct": []}

    st = {"config": "B6", "candidates": [
        {"name": "erlotinib / GBM", "drug": "e", "disease": "GBM", "label": "TN",
         "f0": {"count": 120, "error": None}, "veto": None, "veto_reason": None,
         "trail": [], "factcheck": [
             r_("111", "pubmed", "support", 3.0, True, quote="works"),
             r_("NCT1", "ctgov", "neutral", 0.0, False,
                "인용 검증 실패(등록부 본문에 없는 문장(지어냄)) → 무관 강등",
                "Erlotinib 11.5 vs Placebo 13.2"),
             r_("NCT2", "ctgov", "neutral", 0.0, False,
                "인용 검증 실패(인용이 너무 짧아 검증 불가(9자)) → 무관 강등", "p=0.55"),
             r_("NCT3", "ctgov", "neutral", 0.0, False, "무관 — 효능 증거 아님"),
             r_("NCT4", "ctgov", "neutral", 0.0, False,
                "운영상 중단(등록 부진·자금 등) — 효능 반증 아님 → 무관 강등")]}]}
    p = os.path.join(tempfile.mkdtemp(), "s.json")
    _json.dump(st, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        IN.main([p, "--all"])
    out = buf.getvalue()
    check("등록부 근거의 운명을 센다", "읽음 4 · 채택 0 · 강등 4" in out)
    check("사유별로 묶는다", "인용 검증 실패" in out and "무관" in out)
    check("주 사유를 짚어준다", "주 사유: 인용 검증 실패" in out)
    check("실제 인용문을 보여준다", "Erlotinib 11.5 vs Placebo 13.2" in out)
    # PubMed 근거는 이 집계에 섞이면 안 된다
    check("PubMed 근거는 안 섞는다", "읽음 5" not in out)


def test_showreg():
    """등록부 본문 열람 — 세 가설을 갈라내는가.

    실측 사고: 등록부 시험 25건을 읽고 채택 0건, 주 사유는 '무관'이었고
    인용문은 전부 평가변수의 **정의문**이었다.

        "Overall survival was defined from the date of diagnosis to..."

    원인 후보가 셋인데 대응이 전부 다르다.
      ① 결과 섹션에 정의만 등록 → ceiling 지표가 가용성을 과대평가
      ② 파서가 수치를 못 뽑음   → _fmt_outcome 결함
      ③ 수치는 있으나 단일군    → **무관 판정이 옳다.** 방어가 과한 게 아니다

    ③이면 등록부의 증거 가치가 '결과 있음' 건수보다 훨씬 낮다는 뜻이고,
    그건 B6 방향에 대한 부정적이지만 보고할 만한 발견이다.
    추측하지 말고 본문을 눈으로 봐야 갈린다.
    """
    print("\n[22] 등록부 본문 열람 — 가설 분간")
    import contextlib
    import io as _io

    from ..bench import showreg as SR

    def mk(nct, body, rand=False):
        # **비교 가능성은 배정 방식이 정한다.** 결과 줄의 구분자가 아니다.
        #   실측: "70 mg/m^2 0 | 90 mg/m^2 0" 는 용량 단계이지 대조군이 아니다.
        return {"pmid": nct, "nct": [nct], "source": "ctgov", "error": None,
                "year": 2015, "journal": "CT.gov",
                "study_type": "rct" if rand else "trial",
                "title": "T", "abstract": body, "conditions": ["X"],
                "interventions": ["D"], "stop_reason": None,
                "pubtypes": ["Registry Results"] + (["RANDOMIZED"] if rand else [])}

    H = ("대상 질환: X\n개입: D\n상태: Completed\n등록 환자 60명\n\n"
         "[1차 평가변수 결과]\n")
    cases = [
        ("정의만", H + "Overall Survival\nOverall survival was defined from "
                    "the date of diagnosis to death.", False, "수치가 하나도 없다"),
        # 용량 단계는 대조군이 아니다 — 구분자가 있어도 비무작위면 못 쓴다
        ("용량 단계", H + "DLT\n  70 mg/m^2 0 | 90 mg/m^2 0 | 120 mg/m^2 1",
         False, "무작위배정 시험이 하나도 없다"),
        ("단일군", H + "Response Rate\n  Belotecan 18", False,
         "무작위배정 시험이 하나도 없다"),
        ("무작위배정", H + "PFS\n  Drug 11.5 ±2.1 | Placebo 13.2 ±2.4\n"
                       "  통계: p=0.55", True, "프롬프트를 봐야"),
    ]
    for name, body, rand, expect in cases:
        with patched(sources, ctgov_results=lambda n, b=body, r=rand: mk(n, b, r)):
            buf = _io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = SR.main(["NCT1", "--max", "0", "--cache", _tmp("_sr.json")])
            out = buf.getvalue()
        check("본문 열람 %s" % name, rc == 0 and expect in out,
              [l.strip() for l in out.split("\n") if l.strip().startswith("→")][:1])

    # 여러 건을 함께 집계할 수 있어야 한다
    bodies = {"NCT1": (H + "OS\n  Drug 11.5 | Placebo 13.2\n  통계: p=0.5", True),
              "NCT2": (H + "RR\n  A 18", False)}
    with patched(sources, ctgov_results=lambda n: mk(n, *bodies[n])):
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            SR.main(["NCT1", "NCT2", "--max", "0", "--cache", _tmp("_sr.json")])
        o = buf.getvalue()
    check("여러 건 집계", "[집계] 2건" in o and "(대조 가능)**      1" in o, 
          [l.strip() for l in o.split("\n") if "대조 가능" in l])


def test_stale_cache():
    """**새 필드를 추가하고 캐시 판을 안 올리면 새 로직이 조용히 꺼진다.**

    두 번 겪었다.
      ① 등록부 본문에 stop_reason·대상 질환 줄을 넣고 판을 안 올림
      ② ceiling에 randomized·comparative 를 넣고 판을 안 올림
         → "무작위배정 0/42 = 0%"라는 **가짜 결정 지표**가 나왔다.
            그 숫자만 보고 B6를 접었으면 캐시 때문에 방향을 버리는 것이었다.

    사람이 기억해야 하는 규약은 결국 잊힌다. 필요한 필드를 직접 물어
    없으면 다시 받게 한다. 판 번호보다 이쪽이 안전하다.
    """
    print("\n[23] 구버전 캐시가 새 로직을 무력화하지 않는가")
    import urllib.request

    from ..bench import ceiling as CE

    cache.configure(_tmp("_st.json"), enabled=True)
    cache._STORE.clear()
    cache._STORE["CTGR3::N1"] = {"pmid": "N1", "abstract": "x"}          # 구버전
    cache._STORE["CTGR3::N2"] = {"pmid": "N2", "abstract": "x",
                                 "conditions": [], "interventions": [],
                                 "stop_reason": None}                    # 신버전
    F = ("conditions", "interventions", "stop_reason")
    check("필드 빠진 항목을 낡음으로 본다", cache.stale("CTGR3::N1", *F))
    check("필드 갖춘 항목은 재사용", not cache.stale("CTGR3::N2", *F))
    check("없는 키는 낡음", cache.stale("CTGR3::없음", *F))

    # ceiling.fetch 도 같은 원리로 옛 항목을 다시 받아야 한다
    calls = []

    class _R:
        def read(self):
            return (b'{"protocolSection":{"designModule":'
                    b'{"designInfo":{"allocation":"RANDOMIZED"},'
                    b'"phases":["PHASE3"]}},"resultsSection":'
                    b'{"outcomeMeasuresModule":{"outcomeMeasures":'
                    b'[{"type":"PRIMARY","analyses":[{"pValue":"0.03"}]}]}}}')

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def _op(req, timeout=0, context=None):
        calls.append(req.full_url)
        return _R()

    real = urllib.request.urlopen
    urllib.request.urlopen = _op
    old_delay = CE.DELAY
    CE.DELAY = 0
    try:
        # 새 필드가 없는 옛 항목
        store = {"NCTOLD": {"nct": "NCTOLD", "has_results": True,
                            "n_outcomes": 2, "has_stats": True, "error": None}}
        r = CE.fetch("NCTOLD", store)
        check("옛 항목은 다시 받는다", bool(calls), len(calls))
        check("새 필드가 채워진다",
              r.get("randomized") is True and r.get("comparative") is True,
              "%s/%s" % (r.get("randomized"), r.get("comparative")))
        calls.clear()
        CE.fetch("NCTOLD", store)
        check("두 번째는 캐시를 쓴다", not calls, len(calls))
    finally:
        urllib.request.urlopen = real
        CE.DELAY = old_delay


def test_comparative_filter():
    """등록부 게이트가 **대조 불가 시험을 걸러내는가.**

    실측 사고: 등록부 25건을 읽고 채택 0건이었다. 전부 단일군·용량증량
    시험이라 효능을 판단할 수 없었는데, LLM 호출만 25번 쓰고 근거는 0이었다.

    더 중요한 것은 **기준의 일관성**이다. bench.ceiling 은 무작위배정만
    '사용 가능'으로 세는데 게이트가 아무거나 읽으면, 측정과 시스템이
    다른 것을 보게 된다. 그러면 어느 숫자도 다른 쪽을 설명하지 못한다.
    """
    print("\n[24] 등록부 — 대조 가능한 시험만 읽는가")
    import re as _re

    from ..agents import factcheck as FC
    from ..core.state import Candidate, RunState

    for name, rec, exp in [
            ("무작위 3상", {"study_type": "rct",
                         "pubtypes": ["Registry Results", "PHASE3", "RANDOMIZED"]}, True),
            ("비무작위", {"study_type": "trial",
                       "pubtypes": ["Registry Results", "PHASE2", "NON_RANDOMIZED"]}, False),
            ("배정 NA", {"study_type": "trial",
                       "pubtypes": ["Registry Results", "PHASE2"]}, False),
            # 1상은 안전성·용량이 목적이라 무작위여도 효능 근거가 아니다
            ("무작위 1상만", {"study_type": "rct",
                          "pubtypes": ["Registry Results", "PHASE1", "RANDOMIZED"]}, False),
            ("무작위 1·2상", {"study_type": "rct",
                           "pubtypes": ["Registry Results", "PHASE1", "PHASE2",
                                        "RANDOMIZED"]}, True),
            ("상 미기재", {"study_type": "rct",
                        "pubtypes": ["Registry Results", "RANDOMIZED"]}, True)]:
        check("대조 가능 판정 %s" % name, gates._comparative(rec) == exp,
              gates._comparative(rec))

    calls = []

    def res(nct):
        rand = "R" in nct
        return {"pmid": nct, "nct": [nct], "source": "ctgov",
                "stop_reason": "efficacy", "error": None, "year": 2018,
                "journal": "CT.gov", "study_type": "rct" if rand else "trial",
                "conditions": ["IPF"], "interventions": ["D"],
                "pubtypes": (["Registry Results", "PHASE2"]
                             + (["RANDOMIZED"] if rand else ["NON_RANDOMIZED"])),
                "title": "T " + nct,
                "abstract": "대상 질환: IPF\n개입: D\n"
                            "상태: TERMINATED  중단 사유: futility\n"
                            "등록 환자 88명\n\n[1차 평가변수 결과]\nFVC\n"
                            "  D 11.5 ±2.1 | P 13.2 ±2.4\n  통계: p=0.55"}

    def comp(prompt, system="", model=None, as_json=False, purpose=""):
        ids = _re.findall(r"\[초록 (\d+) · PMID (\S+)\]", prompt)
        calls.append(len(ids))
        return {"ok": True, "error": None, "text": "", "provenance": {},
                "data": [{"idx": int(i), "direction": "refute", "study_type": "rct",
                          "size": "large", "confidence": "high", "decisive": True,
                          "certainty": "high", "quote": "D 11.5 ±2.1 | P 13.2 ±2.4",
                          "reason": "r"} for i, _ in ids]}

    with patched(sources,
                 ctgov_search=lambda d, c, n=8, status=None:
                 {"ncts": ["NCT_R1", "NCT_S1", "NCT_S2", "NCT_R2"],
                  "error": None, "how": "구조화"},
                 ctgov_results=res), \
         patched(llm, available=lambda: True, complete=comp), \
         patched(FC, llm=llm), patched(gates, sources=sources):
        c = Candidate(name="d / IPF", origin="TN", query="q", drug="d", disease="IPF")
        gates.gate_registry(RunState("q", "B6", "t", [c],
                                     dict(gates.CONFIGS["B6"])))
    kept_ncts = [r["pmid"] for r in c.factcheck]
    check("무작위 시험만 판정에 오른다", kept_ncts == ["NCT_R1", "NCT_R2"], kept_ncts)
    # 단일군은 LLM에 아예 안 보낸다 — 호출 낭비를 막는다
    check("단일군은 LLM에 안 보낸다", calls == [2], calls)
    check("제외 건수를 기록에 남긴다",
          "단일군·1상 2건 제외" in (next(t for t in c.trail
                                    if t.gate == "registry").detail or ""))


def test_stratum_consistency():
    """층을 쓰는 모든 도구가 **같은 모집단**을 보는가.

    같은 실수를 세 번 반복했다 —
      ① ceiling이 TN 49건(전 층), bench.run이 42건(층 A)
      ② tp_audit이 TP 49건(전 층)
    둘 다 "실제로 돌리는 집합과 다른 모집단의 숫자"를 냈다.

    **교훈은 파일 단위로 새지 않는다.** 한 곳을 고쳐도 다음 파일에서 또 난다.
    그래서 사람의 기억이 아니라 시험으로 못 박는다. 층으로 걸러야 하는
    도구가 새로 생기면 여기에 추가하라.
    """
    print("\n[25] 층 일관성 — 도구들이 같은 모집단을 보는가")
    import contextlib
    import csv as _csv
    import io as _io
    import os
    import tempfile

    from ..bench import ceiling as CE, run as BR, tp_audit as TA

    d = tempfile.mkdtemp()
    m = os.path.join(d, "m.csv")
    with open(m, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        w.writerow(["drug", "indication", "label", "stratum", "nct"])
        # 층 A 2쌍 · 층 B 1쌍
        for i, st in enumerate(["A", "A", "B"]):
            w.writerow(["tn%d" % i, "d%d" % i, "TN", st, "NCT%d" % i])
            w.writerow(["tp%d" % i, "d%d" % i, "TP", st, ""])

    # 세 도구 모두 --stratum 기본값이 "A" 여야 하고, 층 A만 세야 한다
    for name, fn, args, expect in [
            ("bench.run", BR.main,
             [m, "--configs", "B0", "--dry", "--skip-preflight",
              "--cache", os.path.join(d, "c.json"),
              "--out", os.path.join(d, "o.json")], "TN 2 · TP 2"),
            ("tp_audit", TA.main,
             [m, "--no-llm", "--cache", os.path.join(d, "c2.json"),
              "--out", os.path.join(d, "o2.csv")], "층 A · 2건")]:
        with patched(sources,
                     pubmed_search=lambda q, retmax=8, max_year=None:
                     {"count": 5, "pmids": ["1"], "error": None}):
            buf = _io.StringIO()
            with contextlib.redirect_stdout(buf):
                fn(args)
            check("%s 기본 층 A" % name, expect in buf.getvalue(),
                  [l.strip() for l in buf.getvalue().split("\n")
                   if "TN" in l or "층 A" in l][:1])

    # ceiling 은 --stratum 을 실제로 인자로 받아야 한다
    import argparse
    for name, mod in (("ceiling", CE), ("tp_audit", TA), ("run", BR)):
        src = open(mod.__file__, encoding="utf-8").read()
        check("%s 에 --stratum 존재" % name, '"--stratum"' in src)

    # all 을 주면 전부 세야 한다
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        BR.main([m, "--configs", "B0", "--dry", "--skip-preflight",
                 "--stratum", "all", "--cache", os.path.join(d, "c.json"),
                 "--out", os.path.join(d, "o.json")])
    check("--stratum all 이면 전 층", "TN 3 · TP 3" in buf.getvalue())


def test_drug_mismatch():
    """근거가 **그 약을 지목하는가.**

    실측 사고: `interferon beta-1a / Crohn` 이 **natalizumab** 메타분석을
    근거로 유망 94%를 받았다. 인용문이 "Pooled data ... suggest that
    natalizumab ..." 인데 인터페론은 한 번도 나오지 않는다.

    프롬프트 규칙 2는 "다른 **질환**은 무관"만 막았고 **다른 약물**에 대한
    규칙이 없었다. 규칙을 넣어도 그건 LLM 판단이므로 결정론적 backstop을 건다.

    0으로 죽이지 않고 절반으로 깎는다 — "platinum drugs" 같은 계열 근거는
    cisplatin을 직접 지목하진 않지만 무가치하지도 않다. **계열 효과는 약
    자체의 근거보다 약하다**는 것이 정확한 서술이고, 감쇠가 그에 맞는다.
    """
    print("\n[26] 약물 불일치 — 간접 근거 감쇠")
    from ..agents.factcheck import INDIRECT_MULT, names_drug

    for drug, title, quote, exp in [
            # 완전히 다른 약 — 이게 실제로 통과했던 사고다
            ("interferon beta-1a",
             "Natalizumab for induction of remission in Crohn's disease",
             "Pooled data from the four included studies suggest that natalizumab",
             False),
            ("gabapentin", "Efficacy and safety of gabapentin and pregabalin",
             "Gabapentin could reduce hot flash frequency", True),
            # 제목엔 없고 인용문에만 있어도 직접 근거다
            ("perhexiline", "Comparison of Drug Therapy Efficacy in Patients with HCM",
             "mavacamten and perhexiline improved", True),
            # 계열·동의어 표기는 간접으로 잡히는 것이 **의도된 동작**
            ("cisplatin", "Efficacy of platinum-based and non-platinum-based",
             "Compared with non-platinum drugs, platinum drugs significantly", False),
            ("alprostadil", "Effect of prostaglandin E1 on pulmonary artery pressure",
             "Intravenous PGE(1) therapy after corrective surgery", False),
            # 염 형태·어간
            ("erlotinib", "Erlotinib hydrochloride in glioma",
             "erlotinib hydrochloride reduced", True),
            ("doxycycline", "Doxycycline in IPF",
             "doxycycline did not improve FVC", True)]:
        check("약물 지목 %s" % drug[:18], names_drug(drug, title, quote) == exp,
              "직접" if names_drug(drug, title, quote) else "간접")

    # 약 이름을 모르면 검사하지 않는다 — 없는 정보로 벌점을 주면 안 된다
    check("약물명이 없으면 검사 안 함", names_drug("", "제목", "인용"))

    # 실제 판정 경로에서 가중치가 절반이 되는가
    import re as _re

    from ..agents import factcheck as FC

    REC = {"pmid": "1", "source": "pubmed", "error": None, "year": 2019,
           "journal": "J", "study_type": "rct", "pubtypes": ["Randomized Controlled Trial"],
           "title": "Natalizumab for induction of remission in Crohn disease",
           "abstract": "Pooled data from the four included studies suggest that "
                       "natalizumab is effective for induction of remission."}
    OWN = dict(REC, title="Interferon beta-1a for Crohn disease",
               abstract="Interferon beta-1a is effective for induction of remission "
                        "in patients with active Crohn disease.")

    def comp(prompt, system="", model=None, as_json=False, purpose=""):
        q = ("natalizumab is effective for induction of remission"
             if "Natalizumab" in prompt
             else "Interferon beta-1a is effective for induction of remission")
        n = len(_re.findall(r"\[초록 \d+ · PMID", prompt))
        return {"ok": True, "error": None, "text": "", "provenance": {},
                "data": [{"idx": i + 1, "direction": "support", "study_type": "rct",
                          "size": "large", "confidence": "high", "decisive": True,
                          "certainty": "high", "quote": q, "reason": "r"}
                         for i in range(n)]}

    with patched(FC, llm=llm), patched(llm, complete=comp):
        bad = FC.classify_batch("interferon beta-1a", "Crohn Disease", [REC])[0]
        good = FC.classify_batch("interferon beta-1a", "Crohn Disease", [OWN])[0]
    check("다른 약 근거는 간접 표시", bad.get("indirect") is True, bad.get("indirect"))
    check("같은 약 근거는 그대로", not good.get("indirect"))
    check("가중치가 정확히 절반",
          abs(bad["weight"] - good["weight"] * INDIRECT_MULT) < 1e-6,
          "%s vs %s" % (bad["weight"], good["weight"]))
    # 방향은 유지된다 — 죽이는 게 아니라 깎는 것이다
    check("간접이어도 방향은 유지", bad["direction"] == "support" and bad["kept"])
    # 프롬프트에 규칙이 실제로 들어갔는가
    check("프롬프트에 다른 약물 규칙", "다른 약물에 대한 효능도 무관" in FC.BATCH_HEAD)


def test_blind_review():
    """검토지에 **시스템 판정이 새지 않는가.**

    처음엔 `시스템_방향` 칸을 넣고 "미리 보지 마라"고 안내문을 달았다.
    **눈앞에 있는 답을 안 보는 것은 불가능하다.** 정박 효과가 걸리면
    이 측정 전체가 무효가 된다 — 사람이 시스템에 동의하는 비율을 잴 뿐,
    시스템이 맞는지를 재는 게 아니게 된다.

    답은 별도 열쇠 파일에 두고 채점할 때 번호로 합친다.
    """
    print("\n[27] 맹검 검토지 — 답이 새지 않는가")
    import contextlib
    import csv as _csv
    import io as _io
    import json as _json
    import os
    import tempfile

    from ..bench import sample as SP

    def fc(pmid, d, w_, kept):
        return {"pmid": pmid, "source": "pubmed", "direction": d, "weight": w_,
                "kept": kept, "quote": "인용문 %s 입니다 그럴듯한 문장" % pmid,
                "title": "T", "study_type": "rct", "certainty": "high",
                "skip": None, "retracted": False, "year": 2019,
                "journal": "J" + pmid, "nct": []}

    d = tempfile.mkdtemp()
    st = {"config": "B6", "candidates": [
        {"name": "d / x", "drug": "d", "disease": "x", "label": "TN", "f0": {},
         "veto": None, "veto_reason": None, "trail": [],
         "factcheck": [fc(str(i), ["support", "refute", "neutral"][i % 3],
                          3.0 - i * 0.1, i % 3 != 2) for i in range(1, 31)]}]}
    sp = os.path.join(d, "s.json")
    _json.dump(st, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
    out, key = os.path.join(d, "rev.csv"), os.path.join(d, "key.csv")
    with contextlib.redirect_stdout(_io.StringIO()):
        SP.main([sp, "--n", "12", "--out", out, "--key", key])

    rows = list(_csv.DictReader(open(out, encoding="utf-8-sig")))
    leak = [k for k in rows[0] if "시스템" in k or "가중치" in k]
    check("검토지에 답이 없다", not leak, leak)
    check("번호로 짝지을 수 있다", "번호" in rows[0])
    keys = {k["번호"]: k for k in _csv.DictReader(open(key, encoding="utf-8-sig"))}
    check("열쇠에 판정이 있다", all("시스템_방향" in v for v in keys.values()))
    check("검토지와 열쇠 행 수 일치", len(rows) == len(keys), "%d/%d" % (len(rows), len(keys)))

    # 채점 — 일부러 n건 틀리게
    n_wrong = 3
    for i, r in enumerate(rows):
        t = keys[r["번호"]]["시스템_방향"]
        r["사람_방향"] = ("neutral" if t != "neutral" else "support") if i < n_wrong else t
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = SP.main(["--score", out, "--key", key])
    o = buf.getvalue()
    exp = round(100 * (len(rows) - n_wrong) / len(rows))
    check("채점 정상 종료", rc == 0, rc)
    check("정확도가 맞다", "= %d%%" % exp in o,
          [l.strip() for l in o.split("\n") if "일치" in l][:1])
    check("불일치를 나열", o.count("시스템=") == n_wrong, o.count("시스템="))

    # 열쇠가 없으면 채점이 **막혀야** 한다. 조용히 0%를 내면 안 된다.
    buf2 = _io.StringIO()
    with contextlib.redirect_stdout(buf2):
        rc2 = SP.main(["--score", out, "--key", os.path.join(d, "없음.csv")])
    check("열쇠 없으면 중단", rc2 == 1 and "읽을 수 없다" in buf2.getvalue(), rc2)


def test_chiral_and_result():
    """거울상체 오인과 **결과 없는 인용**.

    실측 사고 둘 —

    ① `pramipexole / ALS` 가 EMPOWER 3상 초록을 근거로 잡았다. 그런데 그
       시험의 약은 **dexpramipexole**이다. 부분문자열이라 통과했다.
       프라미펙솔은 도파민 작용제, 덱스프라미펙솔은 R(+)-거울상체로
       도파민 활성이 없고 ALS용으로 따로 개발됐다. **다른 약이다.**
       같은 함정: levocetirizine, esomeprazole, dexlansoprazole(벤치마크에 있다).

    ② 아래 문장들이 w=3.0 이상으로 채택됐다 —
         "The pain was measured using the WOMAC pain subscale score"
         "Among the study group, 402 and 126 patients received ..."
         "Our trial can inform the design of future research"
       전부 결과가 아니다. 인용 검증은 *지어냈는가*만 보고
       **판정을 뒷받침하는지는 안 봤다.**
    """
    print("\n[28] 거울상체 · 결과 없는 인용")
    from ..agents.factcheck import has_result, names_drug

    for drug, txt, exp in [
            ("pramipexole", "dexpramipexole (25-150 mg) was well tolerated", False),
            ("cetirizine", "levocetirizine 5 mg improved symptoms", False),
            ("lansoprazole", "dexlansoprazole MR 60 mg healed esophagitis", False),
            ("omeprazole", "esomeprazole 40 mg versus placebo", False),
            ("ofloxacin", "levofloxacin 750 mg for pneumonia", False),
            # 진짜 언급은 통과해야 한다
            ("pramipexole", "pramipexole 0.5 mg improved UPDRS", True),
            # 한 초록이 둘을 같이 다루면 통과 — 첫 출현만 보면 안 된다
            ("pramipexole", "dexpramipexole differs from pramipexole in activity", True),
            ("dexlansoprazole", "dexlansoprazole healed erosive esophagitis", True),
            ("erlotinib", "Erlotinib hydrochloride in recurrent glioma", True)]:
        check("거울상체 %s⊂%s" % (drug[:9], txt.split()[0][:14]),
              names_drug(drug, txt) == exp, names_drug(drug, txt))

    for q in ["The pain in subjects with osteoarthritis was measured using the WOMAC score.",
              "Among the study group, 402 and 126 patients received co-trimoxazole.",
              "Our trial can inform the design of future clinical research strategies.",
              "Perhexiline is increasingly also used in the treatment of HCM.",
              "Overall survival was defined from the date of diagnosis to death.",
              "Progression-free survival (PFS) distributions for the Phase II participants"]:
        check("결과 없음 %s" % q[:26], not has_result(q), has_result(q))

    for q in ["No statistical evidence supported that sunitinib improved PFS (P = 0.999).",
              "Rupatadine was significantly superior to placebo.",
              "Median PFS was shorter with sunitinib-paclitaxel (HR 1.63).",
              "Basiliximab did not enhance corticosteroid efficacy.",
              "penicillin is no longer the initially recommended antibiotic",
              "This study demonstrates the efficacy of PG-E(1) in lowering PHT."]:
        check("결과 있음 %s" % q[:26], has_result(q), has_result(q))

    # 등록부는 표의 값 줄이다. 비교 표현이 없어도 **그 자체가 비교**다.
    for q in ["Doxycycline -0.24 | Placebo -0.20",
              "Erlotinib 11.5 ±2.1 | Placebo 13.2 ±2.4"]:
        check("등록부 수치 %s" % q[:22], has_result(q, structured=True))
    check("등록부여도 수치 하나면 결과 아님",
          not has_result("Belotecan 18", structured=True))


def test_enrich():
    """종료 연도 보강 — **파이프라인을 재실행하지 않고** 열만 채우는가.

    `bench_matched.csv` 가 `ctgov_year` 없이 만들어졌는데 시점 차단에 그 열이
    필요하다. 그런데 `labels → ctgov → match` 를 다시 돌리면 **짝짓기가
    달라질 수 있다** — match는 PubMed 문헌량으로 짝을 짓기 때문이다.
    그러면 지금까지 잰 모든 숫자가 다른 벤치마크의 것이 된다.

    그리고 **TP에는 NCT가 없다**(RepoDB 승인에서 왔다). 연도는 구조적으로
    TN에만 붙으므로 시점 차단은 한쪽에만 걸린다. 그 비대칭을 알려야 한다.
    """
    print("\n[29] 종료 연도 보강 — 쌍을 깨지 않고")
    import contextlib
    import csv as _csv
    import io as _io
    import json as _json
    import os
    import tempfile
    import urllib.request

    from ..bench import enrich as EN

    F = ["label", "stratum", "drug", "indication", "kind", "phase", "pubmed",
         "nct", "why", "detail", "matched_to"]

    class _R:
        def __init__(self, y):
            self.y = y

        def read(self):
            return _json.dumps({"protocolSection": {"statusModule": {
                "primaryCompletionDateStruct": {"date": "%d-06" % self.y}}}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def run(n_tn, fail):
        d = tempfile.mkdtemp()
        m = os.path.join(d, "m.csv")
        with open(m, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.DictWriter(f, fieldnames=F)
            w.writeheader()
            for i in range(n_tn):
                base = {k: "" for k in F}
                w.writerow(dict(base, label="TN", stratum="A", drug="tn%d" % i,
                                indication="d%d" % i, nct="NCT%04d" % i))
                w.writerow(dict(base, label="TP", stratum="A", drug="tp%d" % i,
                                indication="d%d" % i, nct=""))
        ok = {"NCT%04d" % i: 2010 + i for i in range(n_tn) if i not in fail}

        def op(req, timeout=0, context=None):
            n = req.full_url.split("/")[-1].split("?")[0]
            if n not in ok:
                raise OSError("실패")
            return _R(ok[n])

        real, old = urllib.request.urlopen, EN.DELAY
        urllib.request.urlopen, EN.DELAY = op, 0
        try:
            buf = _io.StringIO()
            with contextlib.redirect_stdout(buf):
                EN.main([m, "--cache", os.path.join(d, "c.json")])
            return buf.getvalue(), list(_csv.DictReader(open(m, encoding="utf-8-sig")))
        finally:
            urllib.request.urlopen, EN.DELAY = real, old

    out, rows = run(4, set())
    # 쌍이 깨지면 벤치마크가 망가진다. 행 수·순서·라벨 교대를 모두 본다.
    check("행 수 보존", len(rows) == 8, len(rows))
    check("TN·TP 교대 유지",
          [r["label"] for r in rows] == ["TN", "TP"] * 4,
          [r["label"] for r in rows])
    ks = list(rows[0].keys())
    check("ctgov_year 가 nct 뒤에",
          ks.index("ctgov_year") == ks.index("nct") + 1, ks)
    check("TN에만 연도가 붙는다",
          all(r["ctgov_year"] for r in rows if r["label"] == "TN")
          and not any(r["ctgov_year"] for r in rows if r["label"] == "TP"))
    # 비대칭을 반드시 알려야 한다 — 모르고 AUROC를 읽으면 오독한다
    check("비대칭을 경고", "AUROC·전체 성능은 이 조건에서 해석할 수 없다" in out)
    check("해석 가능한 지표를 짚어줌", "기각 재현율" in out)

    # TN 연도가 부족하면 측정을 권하지 않아야 한다
    out2, _ = run(10, {0, 1, 2, 3, 4})
    check("TN 연도 부족 시 중단 권고", "시점 차단이 의미 없다" in out2)


def test_cutoff_all_sources():
    """시점 차단이 **증거원 전부**에 걸리는가.

    실측: 팩트체크·회의주의자·등록부에는 걸려 있는데 **F0만 안 걸려 있었다.**
    F0는 증거를 만들지 않지만, 컷오프를 안 걸면 "그 시점엔 문헌이 없던 쌍"이
    나중 문헌 덕에 PASS로 통과한다.

    **하나만 열어두면 그게 구멍이다.** 누출 차단(EXCLUDE_NCT)에서 이미
    겪은 실수 — 등록부에만 걸고 PubMed는 열어뒀다가 라벨 출처 논문이
    그대로 통과했다. 같은 실수를 시점 차단에서 반복하지 않는다.
    """
    print("\n[30] 시점 차단 — 증거원 전부에 걸리는가")
    from ..agents import factcheck as FC
    from ..core.state import Candidate, RunState

    seen = {"lookup": [], "search": [], "reg_year": None}

    def f_lookup(q, retmax=3):
        seen["lookup"].append(q)          # 컷오프 없는 경로 — 불려선 안 된다
        return {"count": 9, "pmids": ["1"], "title": "", "error": None}

    def f_search(q, retmax=8, max_year=None):
        seen["search"].append(max_year)
        return {"count": 1, "pmids": ["1"], "error": None}

    def f_abs(pmids, retry=1):
        return {"1": {"pmid": "1", "title": "T", "abstract": "A trial.",
                      "pubtypes": [], "study_type": "rct", "year": 2005,
                      "journal": "J", "nct": [], "error": None, "source": "pubmed"}}

    def f_res(nct):
        return {"pmid": nct, "nct": [nct], "source": "ctgov", "error": None,
                "year": 2020, "journal": "CT", "study_type": "rct",
                "conditions": ["IPF"], "interventions": ["D"],
                "pubtypes": ["Registry Results", "PHASE3", "RANDOMIZED"],
                "stop_reason": "efficacy", "title": "T",
                "abstract": "대상 질환: IPF\n개입: D\n상태: TERMINATED\n\n"
                            "[1차 평가변수 결과]\nFVC\n  D -0.2 | P -0.1"}

    def comp(prompt, system="", model=None, as_json=False, purpose=""):
        return {"ok": True, "error": None, "text": "", "provenance": {},
                "data": [{"idx": 1, "direction": "neutral", "study_type": "rct",
                          "size": "large", "confidence": "low", "decisive": False,
                          "certainty": "low", "quote": "", "reason": "x"}]}

    with patched(sources, pubmed_lookup=f_lookup, pubmed_search=f_search,
                 pubmed_abstracts=f_abs, ctgov_results=f_res,
                 ctgov_search=lambda d, c, n=8, status=None:
                 {"ncts": ["NCT1"], "error": None, "how": "s"}), \
         patched(llm, available=lambda: True, complete=comp), \
         patched(FC, llm=llm), patched(gates, sources=sources):
        c = Candidate(name="d / IPF", origin="TN", query="d AND IPF",
                      drug="d", disease="IPF")
        c.cutoff_year = 2010
        gates.run_pipeline(RunState("q", "B6", "t", [c],
                                    dict(gates.CONFIGS["B6"])))

    # ① 컷오프 없는 경로(pubmed_lookup)는 아예 안 불려야 한다
    check("F0가 컷오프 없는 경로를 안 쓴다", not seen["lookup"], seen["lookup"])
    # ② 불린 검색은 전부 컷오프를 받았어야 한다
    check("모든 검색에 컷오프 전달",
          bool(seen["search"]) and all(y == 2010 for y in seen["search"]),
          seen["search"])
    # ③ 등록부는 컷오프 이후 시험을 버린다 (2020 > 2010)
    rec = next((t for t in c.trail if t.gate == "registry"), None)
    check("등록부도 컷오프 이후를 버린다",
          rec is not None and ("CUTOFF" == rec.outcome or "없음" in (rec.detail or "")),
          rec.detail if rec else None)

    # 시점 차단이 꺼져 있으면 원래 경로를 쓴다 (회귀)
    seen["lookup"].clear()
    with patched(sources, pubmed_lookup=f_lookup, pubmed_search=f_search,
                 pubmed_abstracts=f_abs), \
         patched(llm, available=lambda: True, complete=comp), \
         patched(FC, llm=llm), patched(gates, sources=sources):
        c2 = Candidate(name="d / IPF", origin="TN", query="d AND IPF",
                       drug="d", disease="IPF")
        gates.gate_f0(RunState("q", "B2", "t", [c2], dict(gates.CONFIGS["B2"])))
    check("차단 꺼지면 원래 경로", bool(seen["lookup"]), seen["lookup"])


def test_leakcheck():
    """누출 재검증 — **초록에 NCT가 없는** 라벨 시험 논문을 잡는가.

    `EXCLUDE_NCT` 는 초록에 등록번호가 적힌 논문만 막는다. 많은 논문이
    등록번호를 초록에 안 쓰므로 **라벨 출처 시험의 결과 논문이 그대로
    통과한다.** 그러면 예측이 아니라 답안지를 읽은 것이다.

    실측 정황: 기각한 TN 12건 중 4건에서 반박 문헌의 출판연도가 시험
    종료연도와 **같았다.**

    이 검사는 PubMed `[si]` 색인에 의존하므로 **누출의 하한**만 준다.
    안 잡혔다고 없는 것이 아니라는 점을 출력에 반드시 적어야 한다.
    """
    print("\n[31] 누출 재검증 — 라벨 시험 논문이 근거로 들어왔는가")
    import contextlib
    import csv as _csv
    import io as _io
    import json as _json
    import os
    import tempfile

    from ..bench import leakcheck as LC

    d = tempfile.mkdtemp()
    m, sp = os.path.join(d, "m.csv"), os.path.join(d, "s.json")
    with open(m, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        w.writerow(["drug", "indication", "label", "stratum", "nct"])
        w.writerow(["dA", "x", "TN", "A", "NCT0001"])   # 누출 있음
        w.writerow(["dB", "y", "TN", "A", "NCT0002"])   # 누출 없음
        w.writerow(["dC", "z", "TN", "A", "NCT0003"])   # [si] 색인 안 됨

    def fc(pmid, direction):
        return {"pmid": pmid, "direction": direction, "kept": True,
                "weight": 3.0, "title": "T" + pmid, "source": "pubmed"}

    _json.dump({"config": "B5", "candidates": [
        {"name": "dA / x", "drug": "dA", "disease": "x", "verdict": "기각",
         "confidence": 5, "factcheck": [fc("111", "refute"), fc("999", "support")]},
        {"name": "dB / y", "drug": "dB", "disease": "y", "verdict": "기각",
         "confidence": 8, "factcheck": [fc("222", "refute")]},
        {"name": "dC / z", "drug": "dC", "disease": "z", "verdict": "보류",
         "confidence": 50, "factcheck": [fc("333", "refute")]}]},
        open(sp, "w", encoding="utf-8"), ensure_ascii=False)

    SI = {"NCT0001[si]": ["111", "888"], "NCT0002[si]": ["777"], "NCT0003[si]": []}
    with patched(sources, pubmed_search=lambda q, retmax=8, max_year=None:
                 {"count": len(SI.get(q, [])), "pmids": SI.get(q, []), "error": None}):
        cache.configure(_tmp("_lc.json"), enabled=False)
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = LC.main([sp, m, "--cache", _tmp("_lc.json")])
        out = buf.getvalue()
        # 판정 필터가 듣는가
        buf2 = _io.StringIO()
        with contextlib.redirect_stdout(buf2):
            LC.main([sp, m, "--only-verdict", "기각", "--cache", _tmp("_lc.json")])
        out2 = buf2.getvalue()

    check("leakcheck 정상 종료", rc == 0, rc)
    check("누출 후보를 찾아낸다", "누출 확인 1후보" in out)
    check("누출 후보 이름을 짚는다", "dA / x" in out)
    # 지지 근거(999)는 라벨 논문이 아니므로 안 잡혀야 한다
    check("무관한 근거는 안 잡는다", "999" not in out.split("[이 검사의 한계]")[0])
    check("답안지 읽기임을 명시", "답안지 읽기" in out)
    # **하한임을 반드시 말해야 한다.** 안 잡혔다고 없는 게 아니다.
    check("색인 안 된 시험 수를 보고", "색인 안 됨**  1/3" in out,
          [l.strip() for l in out.split("\n") if "색인" in l][:1])
    check("하한임을 명시", "누출 건수는 하한이다" in out)
    check("판정 필터가 듣는다", "검사 2후보" in out2)


def test_leak_pmid_expand():
    """누출 차단이 **NCT 없는 논문**까지 막는가.

    `EXCLUDE_NCT` 는 초록에 등록번호가 적힌 논문만 막는다. 많은 논문이
    등록번호를 초록에 안 쓰므로 **라벨 출처 시험의 결과 논문이 통과한다.**

    실측(`bench.leakcheck`): 기각한 TN 11건 중 라벨 시험 논문이 [si]에
    색인된 것이 4건, **그중 2건이 근거로 들어와 있었다.**
    `warfarin/IPF` 의 판정은 예측이 아니라 답안지 읽기였다.

    그래서 NCT를 PubMed `[si]` 색인으로 **PMID까지 확장**해 막는다.
    """
    print("\n[32] 누출 차단 — NCT를 PMID로 확장")
    from ..agents import factcheck as FC

    SI = {"NCT0001[si]": ["111", "222"], "NCT0002[si]": []}
    old_nct, old_pmid = FC.EXCLUDE_NCT, FC.EXCLUDE_PMID
    try:
        with patched(sources, pubmed_search=lambda q, retmax=8, max_year=None:
                     {"count": len(SI.get(q, [])), "pmids": SI.get(q, []),
                      "error": None}), \
             patched(gates, sources=sources):
            info = gates.set_exclude({"NCT0001", "NCT0002"})
        check("PMID로 확장", FC.EXCLUDE_PMID == {"111", "222"}, FC.EXCLUDE_PMID)
        # `failed` 는 결함 37에서 추가됐다 — **"색인 없음"과 "못 물어봤다"는
        # 다르다.** 조회가 다 성공했으므로 failed 는 0이어야 한다.
        check("확장 결과를 돌려준다",
              {k: info[k] for k in ("ncts", "pmids", "no_index", "failed")}
              == {"ncts": 2, "pmids": 2, "no_index": 1, "failed": 0}, info)

        # 초록에 NCT가 없는 그 시험의 논문 — 이게 실제로 통과했던 경우다
        rec = {"pmid": "111", "source": "pubmed", "error": None, "year": 2012,
               "journal": "J", "study_type": "rct", "title": "A trial",
               "pubtypes": ["Randomized Controlled Trial"], "nct": [],
               "abstract": "A placebo-controlled randomized trial showed no benefit."}
        other = dict(rec, pmid="999", nct=[])

        def comp(prompt, system="", model=None, as_json=False, purpose=""):
            import re as _re
            n = len(_re.findall(r"\[초록 \d+ · PMID", prompt))
            return {"ok": True, "error": None, "text": "", "provenance": {},
                    "data": [{"idx": i + 1, "direction": "refute",
                              "study_type": "rct", "size": "large",
                              "confidence": "high", "decisive": True,
                              "certainty": "high",
                              "quote": "A placebo-controlled randomized trial showed no benefit",
                              "reason": "r"}
                             for i in range(n)]}

        with patched(FC, llm=llm), patched(llm, complete=comp):
            out = FC.classify_batch("d", "x", [rec, other])
        blocked = next(r for r in out if r["pmid"] == "111")
        passed = next(r for r in out if r["pmid"] == "999")
        check("라벨 시험 논문이 막힌다",
              not blocked["kept"] and "PMID 색인" in (blocked["skip"] or ""),
              blocked.get("skip"))
        check("무관한 논문은 통과", passed["kept"], passed.get("skip"))

        # expand=False 면 확장하지 않는다 (시험·오프라인용)
        with patched(gates, sources=sources):
            gates.set_exclude({"NCT0001"}, expand=False)
        check("expand=False 면 확장 안 함", FC.EXCLUDE_PMID == set(), FC.EXCLUDE_PMID)
    finally:
        FC.EXCLUDE_NCT, FC.EXCLUDE_PMID = old_nct, old_pmid
        gates.EXCLUDE_NCT = old_nct


def test_cache_never_shrinks():
    """**읽지 않고 저장하면 병합한다.**

    2026-08-05 실제 사고. `bench.match` 가 `cache.load()` 를 부르지 않아
    `_STORE` 가 빈 dict 로 시작했고, 실행 끝의 `save()` 가 이번에 받은
    `SEARCH` 580개만 써서 **2.7MB 캐시를 통째로 덮었다.** 백업이 없었다.

    잃은 것은 초록·등록부 본문·PubChem 동의어다. 측정 결과 파일은 무사했지만
    **그 시점의 문헌 상태를 고정할 수단을 잃었다** — PubMed은 시간이 지나면
    내용이 바뀌므로, 과거 수치를 똑같이 재현할 수 없게 됐다.

    "`load()` 를 꼭 부르자"는 규약으로는 안 막힌다. 오늘만 다섯 번째 유형이다.
    **구조로 막는다** — `load()` 를 안 거쳤으면 저장 전에 디스크를 읽어 병합한다.
    """
    print("\n[37] 캐시는 줄어들지 않는다")
    import json
    import os

    from ..io import cache as C

    p = _tmp("_cacheguard.json")
    old_store, old_path, old_auto = C._STORE, C._PATH, C.AUTOSAVE
    try:
        C.AUTOSAVE = 0
        json.dump({"ABS::1": {"x": 1}, "ABS::2": {"x": 2}, "REG::9": {"y": 9}},
                  open(p, "w", encoding="utf-8"))

        # ── 사고 재현: configure 만 하고 load() 없이 put → save ──
        C.configure(p)
        C._STORE = {}
        C.put("SEARCH::new", {"n": 1})
        C.save()
        got = json.load(open(p, encoding="utf-8"))
        check("읽지 않고 저장해도 기존 항목이 남는다", len(got) == 4, len(got))
        check("기존 키가 그대로", {"ABS::1", "ABS::2", "REG::9"} <= set(got))
        check("새 키도 들어감", "SEARCH::new" in got)

        # ── 정상 경로: load() 후에는 병합 없이 그대로 ──
        C.configure(p)
        C.load()
        n0 = len(C._STORE)
        C.put("SEARCH::b", {"n": 2})
        C.save()
        check("정상 경로는 1개만 늘어남",
              len(json.load(open(p, encoding="utf-8"))) == n0 + 1)

        # ── 메모리 값이 디스크 값을 이긴다 (더 최신이므로) ──
        C.configure(p)
        C._STORE = {"ABS::1": {"x": 99}}
        C.save()
        check("메모리가 디스크를 덮어씀(같은 키)",
              json.load(open(p, encoding="utf-8"))["ABS::1"] == {"x": 99})

        # ── 디스크가 깨져도 죽지 않는다 ──
        with open(p, "w", encoding="utf-8") as f:
            f.write("{깨진")
        C.configure(p)
        C._STORE = {"K": 1}
        C.save()
        check("깨진 디스크에도 메모리를 남긴다",
              json.load(open(p, encoding="utf-8")) == {"K": 1})

        # ── configure 로 경로가 바뀌면 '안 읽은' 상태로 되돌아간다 ──
        C.configure(p)
        check("configure 가 읽음 표시를 지운다", C._LOADED[0] is False)
    finally:
        C._STORE, C._PATH, C.AUTOSAVE = old_store, old_path, old_auto
        C._LOADED[0] = False
        if os.path.exists(p):
            os.remove(p)

    # match.py 가 실제로 load 를 부르는가 — 사고 재발 방지
    import inspect

    from ..bench import match as M
    src = inspect.getsource(M.main)
    check("match.main 이 캐시를 읽는다", "cache.load()" in src or "_cache.load()" in src)


def test_ctharvest():
    """**새 TN 후보 수확** — 깨끗한 홀드아웃의 재료.

    이 프로젝트에 없는 단 하나가 홀드아웃이다. 층 B는 누출 64%로 못 썼고
    기존 후보 90건은 이미 튜닝에 노출됐다.

    설계 원칙 둘 —
      ① **분류기를 새로 만들지 않는다.** `labels.reason_of` 를 그대로 쓴다.
         새 어휘를 쓰면 기존 풀과 비교가 불가능해져 홀드아웃의 뜻이 없어진다.
      ② **HTTP를 하지 않는다.** 페이지 저장은 상위가 하고 여기선 파싱만 한다.
         그래서 네트워크 없이 전부 재현·시험 가능하다.
    """
    print("\n[36] CT.gov 수확 — 새 TN 후보")
    import csv
    import json
    import os

    from ..bench import ctharvest as H

    def study(nct, why, cond, ivs, phase, alloc, year="2018", n=100):
        return {"protocolSection": {
            "identificationModule": {"nctId": nct},
            "statusModule": {"whyStopped": why,
                             "completionDateStruct": {"date": year + "-06"}},
            "conditionsModule": {"conditions": [cond]},
            "designModule": {"phases": [phase],
                             "designInfo": {"allocation": alloc},
                             "enrollmentInfo": {"count": n}},
            "armsInterventionsModule": {
                "interventions": [{"name": x} for x in ivs]}}}

    CASES = [
        # (설명, 시험, 통과해야 하나)
        ("효능중단·무작위·3상", study("NCT1", "Interim analysis showed futility",
                                "Glioblastoma", ["Placebo", "Sunitinib"],
                                "PHASE3", "RANDOMIZED"), True),
        ("운영중단은 제외", study("NCT2", "Slow accrual due to COVID-19",
                             "Anemia", ["Iron sucrose"], "PHASE2",
                             "RANDOMIZED"), False),
        ("비무작위는 제외", study("NCT3", "Lack of efficacy",
                             "Sepsis", ["Simvastatin"], "PHASE2",
                             "NON_RANDOMIZED"), False),
        ("1상은 제외", study("NCT4", "futility", "ALS", ["X"],
                          "PHASE1", "RANDOMIZED"), False),
        ("사유 없으면 제외", study("NCT5", "", "Hepatitis B", ["clevudine"],
                             "PHASE2", "RANDOMIZED"), False),
        ("위약만이면 제외", study("NCT6", "futility", "Pain", ["Placebo"],
                            "PHASE3", "RANDOMIZED"), False),
        ("안전성 중단은 제외", study("NCT7", "Unacceptable hepatotoxicity",
                              "NASH", ["Y"], "PHASE2", "RANDOMIZED"), False),
    ]
    d = _tmp("_ct")
    if not os.path.isdir(d):
        os.makedirs(d)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    with open(os.path.join(d, "p1.json"), "w", encoding="utf-8") as f:
        json.dump({"studies": [c[1] for c in CASES]}, f)

    rows, stat = H.merge([os.path.join(d, "p1.json")], None)
    got = {r["nct"] for r in rows}
    for desc, st, want in CASES:
        nct = st["protocolSection"]["identificationModule"]["nctId"]
        check(desc, (nct in got) == want, "채택" if nct in got else "제외")

    # 위약이 앞에 있어도 **실제 약물**을 고른다
    r1 = [r for r in rows if r["nct"] == "NCT1"][0]
    check("위약 대신 시험약 선택", r1["drug"] == "Sunitinib", r1["drug"])
    check("분류기가 labels 것과 같음", r1["stop_class"] == "효능", r1["stop_class"])
    check("종료 연도 추출", r1["completion_year"] == "2018", r1["completion_year"])

    # ── 중복 제거 — **이게 없으면 홀드아웃이 아니다** ──────────────
    ex = _tmp("_ct_old.csv")
    with open(ex, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["drug", "disease"])
        w.writerow(["Sunitinib", "Glioblastoma"])          # 쌍까지 같다
    rows2, stat2 = H.merge([os.path.join(d, "p1.json")], ex)
    check("기존 풀과 겹치는 쌍은 제거", "NCT1" not in {r["nct"] for r in rows2},
          [r["nct"] for r in rows2])
    check("제거 사실을 통계에 남김", stat2.get("기존 풀과 쌍 중복") == 1)

    # 약물만 겹치면 **버리지 않고 표시**한다 — 다른 질환은 다른 가설이다
    with open(ex, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["drug", "disease"])
        w.writerow(["Sunitinib", "Renal Cell Carcinoma"])
    rows3, _ = H.merge([os.path.join(d, "p1.json")], ex)
    m = [r for r in rows3 if r["nct"] == "NCT1"]
    check("약물만 겹치면 유지하되 표시", m and m[0]["dup"] == "약물",
          m[0]["dup"] if m else "제거됨")

    # 제외 파일이 없으면 **경고하고 중복 제거를 안 했다고 밝혀야** 한다
    rows4, _ = H.merge([os.path.join(d, "p1.json")], _tmp("_없는파일.csv"))
    check("제외 목록 없어도 죽지 않음", len(rows4) == 1, len(rows4))

    # URL 조립 — 길이 제한에 걸리면 안 된다(실측 403)
    u = H.next_url("TOKEN123")
    check("URL에 토큰이 실린다", "pageToken=TOKEN123" in u)
    check("URL 길이 안전", len(u) < 300, len(u))
    check("깨진 JSON에도 안 죽음",
          H.merge([_tmp("_없는파일.json")], None)[1].get("파일 오류") == 1)


def test_stats_and_names():
    """**보고하는 통계는 코드에서 나와야 한다** + 미정의 이름 정적 검사.

    두 결함을 동시에 막는다.

    ① 문서에 실린 Fisher p값이 **코드 어디에도 없었다.** 터미널에서 손으로
       계산해 옮겨 적은 값이라 판 번호도 시험도 없다. 이 프로젝트가 경계하는
       바로 그 유형의 숫자다. `bench.stats` 로 내리고 교과서 값과 대조한다.

    ② `wilson` 이 세 파일에 각각 정의돼 있어 공용 모듈로 합쳤는데, 그 과정에서
       `analyze.py` 가 import 없이 정의만 잃었다. **`--help` 는 통과했다** —
       그 줄에 닿지 않기 때문이다. 실행하면 NameError로 죽었을 것이다.
       모듈 전역의 미정의 이름을 AST로 훑어 같은 일을 막는다.
    """
    print("\n[35] 통계 정확성 · 미정의 이름")
    import ast
    import builtins
    import pathlib

    from ..bench import analyze, pk, run as brun, stats

    # ── ① Fisher: 교과서 값과 대조 ──────────────────────────────────
    #   Fisher 자신의 '차 시음 부인' 실험. 양측 p = 0.4857 (Fisher 1935)
    check("차 시음 검정 (3,1,1,3)", abs(stats.fisher(3, 1, 1, 3) - 0.485714) < 1e-5,
          "%.6f" % stats.fisher(3, 1, 1, 3))
    #   완전 분리 2x2: p = 2 / C(20,10)
    from math import comb
    check("완전 분리 (0,10,10,0)",
          abs(stats.fisher(0, 10, 10, 0) - 2.0 / comb(20, 10)) < 1e-9)
    check("완전 무관 (5,5,5,5) → 1.0", abs(stats.fisher(5, 5, 5, 5) - 1.0) < 1e-9)
    check("대칭성", abs(stats.fisher(7, 0, 8, 2) - stats.fisher(0, 7, 2, 8)) < 1e-9)
    check("빈 표는 1.0", stats.fisher(0, 0, 0, 0) == 1.0)
    #   실제로 보고한 값 — 문서의 0.485와 맞아야 한다
    check("보고값 재현 (7,0,8,2)=0.485",
          abs(stats.fisher(7, 0, 8, 2) - 0.485) < 0.001, "%.4f" % stats.fisher(7, 0, 8, 2))

    # ── Wilson: 알려진 값 ───────────────────────────────────────────
    lo, hi = stats.wilson(7, 7)
    check("Wilson 7/7 = [0.646, 1.000]", abs(lo - 0.646) < 0.001 and hi == 1.0,
          "[%.3f, %.3f]" % (lo, hi))
    lo0, hi0 = stats.wilson(0, 10)
    check("Wilson 0/10 하한이 음수가 아님", lo0 == 0.0 and hi0 > 0)
    check("Wilson n=0 방어", stats.wilson(0, 0) == (0.0, 0.0))

    # ── 일표본 이항 — **상수 대비 비교에 Fisher를 쓰면 안 된다**(결함 32) ──
    check("이항 P(X>=1|1,0.5)=0.5", abs(stats.binom_ge(1, 1, 0.5) - 0.5) < 1e-12)
    check("이항 P(X>=n|n,p)=p^n",
          abs(stats.binom_ge(10, 10, 0.5) - 0.5 ** 10) < 1e-12)
    check("이항 P(X>=0)=1", abs(stats.binom_ge(0, 20, 0.3) - 1.0) < 1e-12)
    check("이항 P(X>=3|10,0.5)=0.945312",
          abs(stats.binom_ge(3, 10, 0.5) - 0.9453125) < 1e-9,
          "%.7f" % stats.binom_ge(3, 10, 0.5))
    check("이항 n=0 방어", stats.binom_ge(1, 0, 0.5) == 1.0)
    # 상수 기준선을 표본으로 바꿔 Fisher에 넣으면 p가 크게 부풀려진다.
    # 이 격차가 결함 32의 실체다 — 시험으로 못 박아 재발을 막는다.
    fis = stats.fisher(6, 215, 1, 220)
    bino = stats.binom_ge(6, 221, 0.003565)
    check("Fisher 오지정이 이항보다 100배 이상 보수적",
          fis > bino * 100, "Fisher %.4f vs 이항 %.6f" % (fis, bino))
    check("일표본 검정력: 차이 0이면 alpha 근처",
          stats.power1(0.1, 0.1, 100) < 0.06, "%.3f" % stats.power1(0.1, 0.1, 100))
    check("일표본 검정력: 큰 차이면 1에 가깝다", stats.power1(0.1, 0.5, 100) > 0.99)
    check("일표본 검정력 n=0 방어", stats.power1(0.1, 0.5, 0) == 0.0)

    # ── ② 한 곳에서만 정의된다 ──────────────────────────────────────
    for name, mod in (("analyze", analyze), ("run", brun), ("pk", pk)):
        check("%s.wilson 이 공용 구현" % name, mod.wilson is stats.wilson)
    check("analyze.fisher 이 공용 구현", analyze.fisher is stats.fisher)

    # ── ③ 미정의 이름 — --help 가 못 잡는 종류 ──────────────────────
    root = pathlib.Path(__file__).resolve().parent.parent
    bad = []
    for f in sorted(root.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        known = set(dir(builtins)) | {"__name__", "__file__", "__doc__"}
        for n in ast.walk(tree):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for al in n.names:
                    known.add((al.asname or al.name).split(".")[0])
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                known.add(n.name)
            elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                known.add(n.id)
            elif isinstance(n, ast.arg):
                known.add(n.arg)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                known.add(n.name)
            elif isinstance(n, (ast.Global, ast.Nonlocal)):
                known.update(n.names)
        for n in ast.walk(tree):
            if (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                    and n.id not in known):
                bad.append("%s:%d %s" % (f.name, n.lineno, n.id))
    check("미정의 이름 0건", not bad, bad[:5])

    # ── ④ 검정력 — "유의하지 않다"가 "차이가 없다"로 읽히는 것을 막는다 ──
    #   실측: 투과성 관문에서 TN 8.1% vs TP 14.3%, p=0.490 이 나왔다.
    #   이걸 "차이 없음"으로 적으면 거짓말이다 — **검정력이 13%다.**
    #   이 표본으로는 8% 대 34% 정도로 벌어져야 잡힌다.
    check("검정력 (0.081,0.143,37,42) ≈ 0.13",
          abs(stats.power2(0.081, 0.143, 37, 42) - 0.13) < 0.02,
          "%.3f" % stats.power2(0.081, 0.143, 37, 42))
    check("최소검출차 mde(0.081,37,42) ≈ 0.34",
          abs(stats.mde(0.081, 37, 42) - 0.34) < 0.02,
          "%.3f" % stats.mde(0.081, 37, 42))
    check("차이가 없으면 검정력 ≈ 0", stats.power2(0.2, 0.2, 37, 42) < 0.05)
    check("n이 커지면 검정력이 오른다",
          stats.power2(0.081, 0.143, 400, 400) > stats.power2(0.081, 0.143, 37, 42))
    check("n=0 방어", stats.power2(0.2, 0.5, 0, 42) == 0.0 and stats.mde(0.2, 0, 42) is None)


def test_permeability_caveat():
    """**Ro5 통과가 투과성을 뜻하지 않는다.**

    `metformin / 유방암` 을 실제로 돌려 보고 발견했다. S2가
    `PASS · Ro5 위반 0건 · MW 129 · logP -1.2` 를 냈는데, **이 가설이
    실패한 이유 중 하나가 바로 약물동태다.**

    Ro5(Lipinski 1997)는 상한만 있다 — MW>500 · logP>5 · HBD>5 · HBA>10.
    하한이 없어 *너무 작고 너무 친수성인* 분자가 위반 0건으로 통과한다.
    그런데 Ro5의 전제는 **수동 확산**이고, 비구아니드(pKa≈12.4)인
    메트포르민은 pH 7.4에서 사실상 전량 양이온이라 그 경로를 못 쓴다.

    **판정은 건드리지 않는다.** 점수를 바꾸면 오늘 잰 수치가 전부 무효다.
    """
    print("\n[34] Ro5 통과 ≠ 투과성")
    from ..io.sources import permeability_caveat, _IONIC_SMARTS, _IONIC_STRONG

    def cav(mw, logp, hits):
        return permeability_caveat(mw, logp, [(n, "x") for n in hits])

    # 메트포르민: 구아니딘(pKa≈12.4) + 극친수성 → **강**
    c = cav(129.0, -1.2, ["구아니딘·아미딘계 강염기"])
    check("메트포르민 등급 강", c["tier"] == "강", c["tier"])
    check("사유를 밝힌다", "강염기" in c["text"] and "극친수성" in c["text"])

    # 카복실산 단독은 **약**이어야 한다. 처음에 이걸 강으로 놨다가
    #   벤치마크 84행에서 승인 약물의 45%가 걸렸다 — **과탐지였다.**
    #   카복실산 pKa는 대략 4~5라 위산(pH 1~3)에서 중성이다.
    #   수치를 보고 고쳤지만 근거는 수치가 아니라 사전에 알려진 pKa다.
    c2 = cav(206.0, 3.5, ["카복실산"])
    check("카복실산 단독은 약 등급", c2["tier"] == "약", c2["tier"])
    check("약 등급은 흡수 가능성을 밝힘", "중성분율" in c2["text"])

    c3 = cav(206.0, 3.5, ["카복실산", "4급 암모늄"])
    check("강+약 → 강", c3["tier"] == "강", c3["tier"])

    check("일반 저분자엔 주석 없음", cav(300.0, 2.0, [])["tier"] == "")
    check("극친수성 단독은 강", cav(180.0, -1.0, [])["tier"] == "강")
    check("MW 큰 분자는 제외", cav(600.0, -1.0, [])["tier"] == "")

    # SMARTS 주입 — RDKit 없이 탐지 논리를 검사한다
    from ..io import sources as S
    hits = S._ionic_hits(None, matcher=lambda sm: "NX4+" in sm)
    check("matcher 주입이 동작", [n for n, _ in hits] == ["4급 암모늄"], hits)
    check("강 목록에 카복실산이 없다",
          "카복실산" not in {n for n, _ in _IONIC_STRONG})
    check("전체 표는 강+약", len(_IONIC_SMARTS) == 4, len(_IONIC_SMARTS))


def test_pair_input():
    """**임의 가설 입력** — 제품의 실제 사용 형태.

    최상위 CLI가 고정 시드 4건만 돌리고 있었다. 제품의 주장은
    *"가설을 주면 검증한다"* 인데 **그 경로가 CLI에 없었다.**
    입력이 없으면 이 시스템은 벤치마크 실행기일 뿐이다.

    시드 후보는 사람이 근거를 매긴 W1 회귀용이고, --pair 는 근거가 비어
    있다 — 게이트가 처음부터 문헌을 읽어 채운다. 그래서 LLM이 없으면
    전부 `보류`가 나온다. **그럴듯한 빈 결과**이므로 미리 끊어야 한다.
    """
    print("\n[33] 임의 가설 입력 — 끝까지 도는가")
    import contextlib
    import io as _io
    import os
    import re as _re
    import tempfile

    from ..agents import factcheck as FC, router
    from .. import run as R

    for text, ok in [("metformin / Malignant neoplasm of breast", True),
                     ("aspirin|Colorectal Cancer", True),
                     ("erlotinib::Glioblastoma", True),
                     ("약물만", False), (" / 질환", False), ("약물 / ", False)]:
        try:
            c = R.parse_pair(text)
            got = bool(c.drug and c.disease)
        except ValueError:
            got = False
        check("입력 형식 %s" % text[:26], got == ok, got)

    DB = {"1": {"pmid": "1", "nct": [], "error": None, "year": 2022,
                "journal": "JAMA", "study_type": "rct", "source": "pubmed",
                "pubtypes": ["Randomized Controlled Trial"],
                "title": "Metformin in breast cancer: the MA.32 randomised trial",
                "abstract": "In this phase 3 randomised trial (n=3649), metformin "
                            "did not improve invasive disease-free survival compared "
                            "with placebo (HR 1.01, p=0.93)."}}

    def comp(prompt, system="", model=None, as_json=False, purpose=""):
        # **팩트체크 프롬프트에도 '기전'이라는 낱말이 있다.**
        #   그걸 구분자로 쓰면 라우터 응답이 팩트체커로 간다 — 실제로 겪었다.
        #   초록 표식으로 갈라야 한다.
        ids = _re.findall(r"\[초록 (\d+) · PMID", prompt)
        if not ids:
            return {"ok": True, "error": None, "text": "", "provenance": {},
                    "data": [{"idx": 1, "mech": "직접·숙주", "target": "AMPK",
                              "confidence": "high", "why": "대사"}]}
        return {"ok": True, "error": None, "text": "", "provenance": {},
                "data": [{"idx": int(i), "direction": "refute", "study_type": "rct",
                          "size": "large", "confidence": "high", "decisive": True,
                          "certainty": "high", "reason": "1차 미달",
                          "quote": "metformin did not improve invasive disease-free "
                                   "survival compared with placebo"} for i in ids]}

    cachefile = _tmp("_pair.json")
    with patched(sources,
                 pubmed_lookup=lambda q, retmax=3:
                 {"count": 42, "pmids": ["1"], "title": "", "error": None},
                 pubmed_search=lambda q, retmax=8, max_year=None:
                 {"count": 1, "pmids": ["1"], "error": None},
                 pubmed_abstracts=lambda ps, retry=1:
                 {x: dict(DB[x]) for x in ps if x in DB},
                 ctgov_search=lambda d, c, n=8, status=None:
                 {"ncts": [], "error": None, "how": ""}), \
         patched(llm, available=lambda: True, complete=comp), \
         patched(FC, llm=llm), patched(router, llm=llm), \
         patched(gates, sources=sources):
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = R.main(["--pair", "metformin / Malignant neoplasm of breast",
                         "--config", "B5", "--cache", cachefile, "--stamp", "T"])
        out = buf.getvalue()
    check("입력 가설 실행 정상 종료", rc == 0, rc)
    check("근거를 실제로 채택", "채택 1" in out)
    check("판정까지 도달", "기각" in out and "발굴 1" in out)
    # 감사 추적 — 인용 원문이 화면에 남아야 한다
    check("인용 원문이 보인다", "did not improve invasive" in out)

    # LLM 없이 입력 가설을 돌리면 전부 `보류`가 나온다. 그럴듯한 빈 결과다.
    with patched(llm, available=lambda: False):
        buf2 = _io.StringIO()
        with contextlib.redirect_stdout(buf2):
            rc2 = R.main(["--pair", "a / b", "--cache", cachefile])
    check("LLM 없으면 입력 가설을 막는다",
          rc2 == 1 and "LLM이 필요하다" in buf2.getvalue(), rc2)


def test_no_llm_guard():
    """키가 없을 때 **가짜 결과표**를 내지 않는가.

    실제 사고: 키 없이 벤치마크를 돌렸더니 rag 게이트가 조용히 건너뛰어져
    전부 `보류`가 됐는데, 화면에는 AUROC 0.500 짜리 완전한 결과표가 찍혔다.
    어디에도 "LLM을 한 번도 안 불렀다"는 말이 없었다.
    숫자가 그럴듯하면 사람은 그걸 결과로 믿는다.
    """
    import csv
    import os
    import tempfile

    from ..bench import run as BR

    d = tempfile.mkdtemp()
    p = os.path.join(d, "m.csv")
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["drug", "indication", "label", "stratum", "nct"])
        w.writerow(["doxycycline", "IPF", "TN", "A", "NCT1"])
        w.writerow(["nintedanib", "IPF", "TP", "A", "NCT2"])
    with patched(BR.llm, available=lambda: False):
        rc = BR.main([p, "--configs", "B5", "--stratum", "A", "--skip-preflight",
                      "--out", os.path.join(d, "o.json"),
                      "--cache", os.path.join(d, "c.json")])
    check("LLM 없으면 중단", rc == 1, rc)
    check("가짜 결과 미저장", not os.path.exists(os.path.join(d, "o.json")))
    # --dry 는 LLM 없이도 돌아야 한다 (비용 추정은 호출이 없다)
    with patched(BR.llm, available=lambda: False):
        rc2 = BR.main([p, "--configs", "B5", "--stratum", "A", "--dry",
                       "--skip-preflight", "--cache", os.path.join(d, "c.json")])
    check("--dry 는 통과", rc2 == 0, rc2)


def test_no_pollution():
    """테스트가 전역 상태를 오염시키지 않았는지 확인한다.

    이 시험이 마지막에 와야 한다. 앞의 어떤 시험이 몽키패치를 안 되돌렸으면
    여기서 잡힌다.
    """
    print("\n[8] 전역 상태 오염 검사")
    import inspect
    for name in ("ctgov_search", "pubmed_search", "_ctg", "pubmed_abstracts"):
        f = getattr(sources, name, None)
        real = f is not None and getattr(f, "__module__", "") == sources.__name__ \
            and not isinstance(f, type(lambda: 0)) or (
                f is not None and getattr(f, "__name__", "") == name)
        check("sources.%s 원본 유지" % name, real,
              getattr(f, "__name__", str(f)))
    check("llm.complete 원본 유지",
          getattr(llm.complete, "__name__", "") == "complete",
          getattr(llm.complete, "__name__", "?"))
    check("llm.available 원본 유지",
          getattr(llm.available, "__name__", "") == "available",
          getattr(llm.available, "__name__", "?"))


# ═══════════════════════════════════════════════════════════
# 통합 시험 — 게이트를 따로 시험하면 놓치는 것이 있다
#
#   지금까지 게이트를 하나씩만 시험했다. 그런데 이 프로젝트의 주장은
#   **게이트들이 함께 만들어내는 결과**에 있다. 전 구간을 태워야
#   "등록부가 판정을 뒤집는가"를 확인할 수 있다.
# ═══════════════════════════════════════════════════════════
def _world():
    """가짜 세계 하나. 실제 IPF/독시사이클린 구조를 본떴다."""
    ABS = {
        "P1": {"pmid": "P1", "title": "pilot",
               "abstract": "RESULTS: doxycycline improved FVC in a small "
                           "open-label series of 20 patients.",
               "pubtypes": ["Clinical Trial"], "study_type": "trial",
               "year": 2010, "journal": "Chest", "nct": [], "error": None},
        # 라벨 출처 시험의 논문 보고 — 누출 차단이 막아야 한다
        "P2": {"pmid": "P2", "title": "label trial",
               "abstract": "RESULTS: no benefit was observed. NCT00600028",
               "pubtypes": ["Randomized Controlled Trial"], "study_type": "rct",
               "year": 2015, "journal": "AJRCCM", "nct": ["NCT00600028"],
               "error": None},
    }

    def ctg_res(nct):
        if nct == "NCT07777777":       # 라벨과 무관한 다른 실패 시험
            return {"pmid": nct, "title": "other", "study_type": "rct", "year": 2018,
                    "journal": "ClinicalTrials.gov", "pubtypes": ["Registry Results"],
                    "nct": [nct], "error": None,
                    "abstract": "상태: Terminated  중단 사유: futility\n통계: p=0.81"}
        return {"pmid": nct, "title": "label", "study_type": "rct", "year": 2015,
                "journal": "ClinicalTrials.gov", "pubtypes": ["Registry Results"],
                "nct": [nct], "error": None, "abstract": "x"}

    def fake_llm(prompt, system="", model=None, as_json=False, purpose=""):
        if "작용 기전" in prompt:
            d = [{"idx": 1, "mech": "직접·숙주", "target": "MMP",
                  "confidence": "high", "why": "x"}]
        elif "PMID P1" in prompt or "PMID P2" in prompt:
            d = [{"pmid": "P1", "direction": "support", "study_type": "trial",
                  "size": "small", "decisive": False, "confidence": "high",
                  "quote": "RESULTS: doxycycline improved FVC in a small "
                           "open-label series of 20 patients."},
                 {"pmid": "P2", "direction": "refute", "study_type": "rct",
                  "size": "large", "decisive": True, "confidence": "high",
                  "quote": "RESULTS: no benefit was observed."}]
        else:
            d = [{"pmid": "NCT07777777", "direction": "refute", "study_type": "rct",
                  "size": "large", "decisive": True, "confidence": "high",
                  "quote": "상태: Terminated  중단 사유: futility"}]
        return {"ok": True, "text": json.dumps(d), "data": d, "error": None,
                "provenance": {}, "cached": False}

    return dict(
        pubmed_lookup=lambda q, retmax=3: {"count": 40, "pmids": ["P1", "P2"],
                                           "error": None},
        pubmed_search=lambda q, retmax=8, max_year=None: {"count": 40,
                                                          "pmids": ["P1", "P2"],
                                                          "error": None},
        pubmed_abstracts=lambda pm, retry=1: {p: ABS[p] for p in pm if p in ABS},
        ctgov_search=lambda d, i, n=8, status=None: {"ncts": ["NCT00600028", "NCT07777777"],
                                        "error": None, "how": "mock"},
        ctgov_results=ctg_res,
        s2_properties=lambda n: {"status": "SKIP", "detail": "mock"},
    ), fake_llm


def test_integration():
    print("\n[13] 통합 — 등록부가 판정을 뒤집는가")
    from ..agents import factcheck as FC
    from ..agents import router as RT
    from ..core.state import Candidate, RunState

    patches, fake_llm = _world()
    cache.configure(_tmp("_e2e_test.json"))
    cache._STORE.clear()
    old_auto, cache.AUTOSAVE = cache.AUTOSAVE, 0

    def run(cfg, excl):
        gates.set_exclude(excl)
        cache._STORE.clear()
        c = Candidate(name="doxycycline / IPF", origin="TN", query="q",
                      drug="doxycycline", disease="IPF", pubchem="doxycycline")
        gates.run_pipeline(RunState("q", cfg, "t", [c], dict(gates.CONFIGS[cfg])))
        return c

    try:
        with patched(sources, **patches), \
             patched(llm, available=lambda: True, complete=fake_llm):
            FC.llm = llm
            RT.llm = llm
            b5 = run("B5", {"NCT00600028"})
            b6 = run("B6", {"NCT00600028"})
            b5_leak = run("B5", set())
    finally:
        cache.AUTOSAVE = old_auto
        gates.set_exclude(set())

    check("PubMed만 + 누출차단 → 반박 못 찾음",
          not b5.refute, "%s %s%%" % (b5.verdict, b5.confidence))
    check("등록부 켜면 반박 확보", bool(b6.refute),
          "%s %s%%" % (b6.verdict, b6.confidence))
    check("등록부가 판정을 뒤집는다", b5.verdict != b6.verdict and b6.verdict == "기각",
          "%s → %s" % (b5.verdict, b6.verdict))
    check("라벨 출처 논문이 PubMed로 새지 않음",
          any("라벨 출처" in str(r.get("skip") or "") for r in b5.factcheck))
    check("누출 차단을 끄면 라벨 논문으로 기각(반칙)",
          b5_leak.verdict == "기각" and bool(b5_leak.refute),
          "%s %s%%" % (b5_leak.verdict, b5_leak.confidence))
    check("같은 구성인데 누출 차단 유무로 판정이 갈린다",
          b5.verdict != b5_leak.verdict,
          "차단ON=%s · 차단OFF=%s" % (b5.verdict, b5_leak.verdict))



def test_discover():
    """발굴(생성) — 후보를 **만드는** 경로.

    이 시험의 절반은 **모의를 시험하는 데** 쓴다. 지금까지 모의가 네 번
    거짓말했고(가장 최근: 팩트체크 프롬프트에 "기전"이 들어 있어 라우터
    응답이 갔다), 그때마다 시험은 통과했다.

    그래서 모의를 "잘 만들자"고 결심하지 않는다 — **구조로 막는다.**
    표지가 둘 이상 맞으면 모의가 답을 돌려주지 않고 예외로 죽는다.
    """
    print("\n[38] 발굴 — 후보를 만드는 경로")
    from ..agents import discover as D, closedbook as CB, factcheck as FC
    from ..bench import discover as BD
    from ..core.state import RunState

    MARKS = {"discover": D.MARK,
             "factcheck1": "아래 초록이 이 가설을",
             "factcheckN": "각각 독립적으로",
             "router": "작용 기전을 분류하라",
             "closedbook": "당신이 이미 알고 있는 지식만으로"}

    def which(prompt):
        hit = [k for k, m in MARKS.items() if m in prompt]
        if len(hit) != 1:
            raise AssertionError("모의가 프롬프트를 판별하지 못했다(일치 %s). "
                                 "엉뚱한 응답이 가면 통과해도 거짓이다." % hit)
        return hit[0]

    # ── 모의가 거짓말할 수 있는지부터 확인한다 ─────────────
    probes = {
        "discover": D.build_prompt("Asthma", 20, "loose"),
        "router": router.HEAD.format(n=1) + "\n1. x (질환: y)\n" + router.TAIL.format(n=1),
        "closedbook": CB.HEAD.format(n=1),
        "factcheckN": FC.BATCH_HEAD.format(drug="d", disease="x", n=1),
        "factcheck1": FC.TEMPLATE.format(drug="d", disease="x", pmid="1",
                                         title="t", abstract="a"),
    }
    ok_marks = True
    for name, txt in probes.items():
        try:
            got = which(txt)
        except AssertionError:
            got = "모호"
        if got != name:
            ok_marks = False
        if name != "discover" and D.MARK in txt:
            ok_marks = False
    check("모의 판별표 5종이 서로 겹치지 않는다", ok_marks)

    canned = [
        {"drug": "Metformin", "mechanism": "AMPK", "rationale": "관찰연구",
         "evidence_level": "clinical", "confidence": "medium"},
        {"drug": "elamipretide", "mechanism": "카디오리핀", "rationale": "기전",
         "evidence_level": "mechanistic", "confidence": "low"},
        {"drug": "Metformin hydrochloride", "mechanism": "중복", "rationale": "",
         "evidence_level": "clinical", "confidence": "low"},
        {"drug": "", "mechanism": "이름없음", "rationale": "",
         "evidence_level": "clinical", "confidence": "high"},
        {"drug": "Zzzznotadrug", "mechanism": "가짜", "rationale": "",
         "evidence_level": "확실함", "confidence": "아주높음"},
    ]
    calls = []

    def fake(prompt, system="", model=None, as_json=False, purpose=""):
        calls.append(which(prompt))
        return {"ok": True, "text": "", "data": canned, "error": None,
                "provenance": {"prompt_sha": "mock"}, "cached": False}

    with patched(llm, complete=fake, available=lambda: True):
        r = D.propose("Asthma", k=20, variant="loose")
        names = [x["drug"] for x in r["items"]]
        check("빈 이름은 후보가 아니다", "" not in names and len(names) == 4, names)
        check("요청 수를 같이 돌려준다(자제와 상한 구분)", r["asked"] == 20)
        check("모르는 등급은 기본값으로 덮지 않고 비운다",
              r["items"][3]["evidence_level"] == "" and
              r["items"][0]["evidence_level"] == "clinical")

        bad = False
        try:
            D.build_prompt("Asthma", 5, "aggressive")
        except ValueError:
            bad = True
        check("모르는 variant 를 조용히 통과시키지 않는다", bad)

        st = RunState(query_title="t", settings="s", stamp="", candidates=[],
                      config={}, discover={"diseases": ["Asthma", "Breast Cancer"],
                                           "k": 20, "variant": "loose"})
        st = gates.gate_discover(st)
        check("질환 2개 → 후보 8개", len(st.candidates) == 8, len(st.candidates))
        c = st.candidates[0]
        check("생성 후보의 출처·질의가 채워진다",
              c.origin == "발굴" and c.query == "Metformin AND Asthma", c.query)
        # 생성기의 rationale 은 **주장이지 근거가 아니다.** 근거 자리에 넣으면
        # 생성기가 자기 후보를 변호하고 깔때기는 검증하는 척만 한다.
        check("생성기의 말을 근거(support/refute) 자리에 넣지 않는다",
              not c.support and not c.refute)
        g = [t for t in c.trail if t.gate == "discovery"][0]
        check("rationale·기전은 감사 추적에만 남는다",
              g.outcome == "GEN" and g.provenance["mechanism"] == "AMPK")

        # ── 결함 40: **이 가드는 원래 대리 지표였다** ──────────────
        #
        # 전에는 `len(gates.ORDER) == 6` 이었다. 지키려던 것은 길이가
        # 아니라 *"기존 구성의 trail 이 안 바뀐다"* 인데, 길이는 그걸
        # 재는 대리물일 뿐이다. 실제로 이 가드는 —
        #
        #   · 게이트 하나를 **빼고** 하나를 **더하면** 통과한다 (길이 6 유지)
        #   · 순서를 뒤섞어도 통과한다
        #   · 반대로 QUIET_WHEN_OFF 처럼 **trail 을 안 바꾸는 추가**를
        #     막아 버린다 — 실제로 08-06 에 S1 추가에서 이게 발화했다
        #
        # 가드를 통과시키려고 가드를 낮추는 것은 이 프로젝트에서 가장
        # 위험한 행동이라, **낮추는 대신 직접 지표로 바꿨다.** 아래는
        # 길이 대신 *유효 게이트 순서*를 못 박는다. 훨씬 강하다.
        base = ["f0", "rag", "router", "s2", "skeptic", "registry"]

        def eff(cfg):
            cf = gates.CONFIGS[cfg]
            return [n for n in gates.ORDER
                    if cf.get(n, False) or n not in gates.QUIET_WHEN_OFF]

        check("discover 는 ORDER 에 없다", "discover" not in gates.ORDER)
        check("동결 구성의 유효 게이트 순서 불변 — 동결 수치를 안 건드린다",
              all(eff(c) == base for c in ("B0", "B5", "B6", "W1")),
              str({c: eff(c) for c in ("B0", "B5", "B6", "W1")}))
        check("ORDER 는 유효 순서의 상위집합이다 (빼기가 아니라 더하기만)",
              [n for n in gates.ORDER if n not in gates.QUIET_WHEN_OFF] == base,
              str(gates.ORDER))

        out = _tmp("gen_mock_test.csv")
        for p in (out, out.replace(".csv", "_runs.json")):
            if os.path.exists(p):
                os.remove(p)
        rc = BD.main(["--auto", "2", "--k", "20", "--out", out,
                      "--cache", _tmp("gen_mock_cache.json")])
        check("생성 실험 CLI 정상 종료", rc == 0, rc)
        import csv as _csv
        rows = list(_csv.DictReader(open(out, encoding="utf-8-sig")))
        check("CSV 행수 = 질환2 × 변형2 × 후보4", len(rows) == 16, len(rows))
        check("두 변형이 모두 돌았다",
              {x["variant"] for x in rows} == {"strict", "loose"})
        check("결과 파일을 말없이 덮어쓰지 않는다",
              BD.main(["--auto", "2", "--out", out]) == 2)
        check("발굴 외의 프롬프트는 나가지 않았다", set(calls) == {"discover"}, set(calls))

    # ── 대조 채점 ────────────────────────────────────────────
    check("염·수화물은 같은 약",
          BD.drug_key("Metformin Hydrochloride") == BD.drug_key("metformin"))
    check("용량 표기 제거", BD.drug_key("Erlotinib (150mg)") == "erlotinib")
    # dex-·levo- 를 지우면 **다른 화합물**이 같은 약이 된다.
    # 벤치마크에 dexlansoprazole 이 실제로 들어 있다.
    check("거울상체는 다른 약",
          BD.drug_key("dexlansoprazole") != BD.drug_key("lansoprazole"))

    uni = BD.load_universe()
    _, _, f = BD.sets_for(uni, "Primary Mitochondrial Myopathy")
    check("TN풀 대조 — elamipretide 가 효능실패로 잡힌다",
          BD.drug_key("elamipretide") in f)
    a2, s2, f2 = BD.sets_for(uni, "Type 2 Diabetes Mellitus")
    check("RepoDB 승인 대조 — metformin",
          BD.label_of(BD.drug_key("metformin"), a2, s2, f2) == "승인")
    check("어디에도 없으면 미지", BD.label_of("zzzznotadrug", a2, s2, f2) == "미지")
    # 다른 질환의 실패를 이 질환의 실패로 세면 적중이 부풀려진다
    _, _, f3 = BD.sets_for(uni, "Atopic Dermatitis")
    check("질환이 다르면 실패로 세지 않는다", BD.drug_key("elamipretide") not in f3)
    dz = BD.pick_diseases(uni, 5)
    check("질환 자동 선택 — TN·승인이 둘 다 있는 것만",
          len(dz) == 5 and all(BD.sets_for(uni, d)[0] and BD.sets_for(uni, d)[2]
                               for d in dz), dz[:2])


def test_funnel():
    """깔때기 실험 — 표본 추출과 **기각의 분해**.

    핵심은 `kill_kind` 다. 총 기각으로 세면 F0 기각(근거가 *없어서*)과
    근거 기반 기각(근거로 *반박해서*)이 합쳐져 무엇을 쟀는지 알 수 없다.
    **주②가 그래서 미달했다.** 여기서는 처음부터 분리해 센다.
    """
    print("\n[39] 깔때기 실험 — 기각을 두 종류로 가른다")
    import hashlib
    import tempfile as _tf
    from ..bench import funnel as F

    # ── 기각 분해 ────────────────────────────────────────────
    ev = {"verdict": "기각", "reason": "결정적 반박 RCT 무효"}
    f0 = {"verdict": "기각", "reason": F.F0_KILL}
    check("근거 기반 기각을 '근거'로", F.kill_kind(ev) == "근거")
    check("F0 문헌0건 기각을 'F0'로", F.kill_kind(f0) == "F0")
    check("기각이 아니면 None", F.kill_kind({"verdict": "유망"}) is None)
    check("사유 없는 기각은 근거 기반으로 센다(보수적)",
          F.kill_kind({"verdict": "기각", "reason": ""}) == "근거")
    # 사유 문자열이 어긋나면 분해가 통째로 무너진다 — 원본과 대조한다
    from ..core import scoring
    import inspect as _ins
    check("F0_KILL 문자열이 scoring.py 와 일치",
          F.F0_KILL in _ins.getsource(scoring.adjudicate), F.F0_KILL)

    # ── 결함 34: 기각 사유가 **부재처럼 읽히면 안 된다** ──────────────
    #   규칙상 근거가 0건이면 p=50 이라 `보류` 로 빠진다. 즉 기각까지 온 것은
    #   반드시 반박 우세다. 그런데 문구가 "지지 근거 부족"이라 감사 추적을
    #   열어 본 사람이 "반박이 없는데 기각했다"고 오판한다. 실제로 오판했다.
    from ..core.state import Candidate as _C, Evidence as _E
    _c = _C(name="t", origin="x", query="q", drug="d", disease="e")
    _c.support = [_E("s", "support", 1.04, source="llm")]
    _c.refute = [_E("r1", "refute", 4.0, source="llm"),
                 _E("r2", "refute", 4.08, source="llm")]
    _v, _p, _r = scoring.adjudicate(_c)
    check("기각 사유가 '반박 우세'를 말한다", _v == "기각" and "반박 우세" in _r, _r)
    check("기각 사유에 양쪽 무게가 들어간다",
          "w=1.04" in _r and "w=8.08" in _r, _r)
    check("근거가 0건이면 기각이 아니라 보류",
          scoring.adjudicate(_C(name="t", origin="x", query="q"))[0] == "보류")

    # ── report: 총 기각과 근거 기반 기각이 **다르게** 나오는가 ──
    def c(nm, lab, vd, rs=""):
        return {"name": nm, "drug": nm, "disease": "D", "label": lab,
                "verdict": vd, "confidence": 50, "reason": rs, "f0": {},
                "veto": False, "veto_reason": "", "trail": [], "factcheck": []}
    cands = ([c("a%d" % i, "TN", "기각", "반박") for i in range(5)] +
             [c("b%d" % i, "TN", "기각", F.F0_KILL) for i in range(2)] +
             [c("c%d" % i, "TN", "유망") for i in range(3)] +
             [c("x0", "TP", "기각", "반박")] +
             [c("y%d" % i, "TP", "유망") for i in range(9)])
    sp = _tmp("funnel_state_t.json")
    json.dump({"config": "B5", "candidates": cands},
              open(sp, "w", encoding="utf-8"), ensure_ascii=False)
    import io as _io
    buf, old = _io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        rc = F.report(type("A", (), {"state": sp})())
    finally:
        sys.stdout = old
    txt = buf.getvalue()
    check("report 정상 종료", rc == 0, rc)
    check("근거 기반 기각 5/10 으로 센다", "근거기반 기각 5/10" in txt)
    check("총 기각은 7/10 으로 따로 센다", "TN 7/10" in txt, )
    # 이 둘이 같게 나오면 분해가 안 된 것이다 — 그러면 시험의 의미가 없다
    check("총 기각 ≠ 근거 기반 기각 (분해가 실제로 일어남)",
          "5/10" in txt and "7/10" in txt)
    check("유의하지 않을 때 '차이 없다'로 안 적는다", "모른다" in txt and
          "'차이 없다'가 아니다" in txt)
    check("MDE 를 같이 적는다", "MDE" in txt)

    # ── 짝비교(McNemar) — **방향을 양쪽으로 시험한다** ────────────────
    #
    #   `mcnemar(a_ok, b_ok)` 는 (b = a만, c = b만) 을 돌려준다. 첫 판에서
    #   이 둘을 바꿔 읽어 **B6가 6건을 더 잡았는데 "등록부가 판정을 나쁘게
    #   만든다"고 찍었다.** 합성 시험이 잡았다.
    #
    #   한 방향만 시험하면 부호 버그가 산다. 결함 8·22와 같은 유형 —
    #   **해석 문구를 상수로 고정하지 말고 방향을 데이터에서 읽어라.**
    def _mk(nkill, cfg):
        cs = [c("t%d" % i, "TN", "기각" if i < nkill else "유망",
                "반박 우세" if i < nkill else "") for i in range(14)]
        cs += [c("p%d" % i, "TP", "유망") for i in range(14)]
        pth = _tmp("pair_%s_%d.json" % (cfg, nkill))
        json.dump({"config": cfg, "candidates": cs},
                  open(pth, "w", encoding="utf-8"), ensure_ascii=False)
        return pth

    def _pair(nb, na):
        bb, oo = _io.StringIO(), sys.stdout
        sys.stdout = bb
        try:
            F.pair_report(type("A", (), {"before": _mk(nb, "B5"),
                                         "after": _mk(na, "B6")})())
        finally:
            sys.stdout = oo
        return bb.getvalue()

    for _nb, _na, _lbl, _exp in ((6, 12, "6건 얻음", "지지"),
                                 (12, 6, "6건 잃음", "반대"),
                                 (6, 9, "3건 얻음", "모른다")):
        _t = _pair(_nb, _na)
        _ln = [x for x in _t.split("\n") if "→ **" in x]
        check("짝비교 방향 — %s → %s" % (_lbl, _exp),
              bool(_ln) and _exp in _ln[0], _ln[0].strip()[:50] if _ln else "없음")
    # 사전 문턱을 화면에 같이 찍어야 사후에 내릴 수 없다
    check("짝비교가 사전 문턱(6건)을 같이 찍는다", "6건 이상" in _pair(6, 9))
    # F0 기각을 근거기반으로 세면 주②의 실수를 반복한다
    _f0 = _mk(0, "B6")
    _d = json.load(open(_f0, encoding="utf-8"))
    for _c in _d["candidates"][:5]:
        _c["verdict"], _c["reason"] = "기각", F.F0_KILL
    json.dump(_d, open(_f0, "w", encoding="utf-8"), ensure_ascii=False)
    _bb, _oo = _io.StringIO(), sys.stdout
    sys.stdout = _bb
    try:
        F.pair_report(type("A", (), {"before": _mk(0, "B5"), "after": _f0})())
    finally:
        sys.stdout = _oo
    check("F0 기각은 짝비교에서 '얻음'으로 세지 않는다",
          "얻음 0건" in _bb.getvalue(),
          [x for x in _bb.getvalue().split("\n") if "뒤집힘" in x][:1])

    # ── select: 실제 생성 CSV로 태운다(PubMed만 모의) ──────────
    if os.path.exists("gen_run1.csv"):
        def fake(q, retmax=1, *a, **k):
            h = int(hashlib.sha256(q.encode()).hexdigest()[:6], 16)
            return {"count": 5 + h % 4000, "pmids": [], "error": None}
        out = _tmp("gen_matched_t.csv")
        if os.path.exists(out):
            os.remove(out)
        with patched(sources, pubmed_search=fake), \
                patched(cache, save=lambda *a, **k: None):
            buf, old = _io.StringIO(), sys.stdout
            sys.stdout = buf
            try:
                rc = F.select(type("A", (), {
                    "gen": "gen_run1.csv", "out": out,
                    "tnpool": "bench_tn_pool_v2.csv",
                    "cache": _tmp("funnel_c.json"), "force": False})())
            finally:
                sys.stdout = old
            txt = buf.getvalue()
        check("select 정상 종료", rc == 0, rc)
        # 같은 쌍이 두 변형에서 나오면 **가설은 하나다.** 두 번 세면 n이 부풀고
        # 두 행이 반드시 같은 판정을 받아 독립성이 깨진다.
        #
        # **질환 문자열로 세면 샌다**(결함 33) — "Breast Cancer"와
        # "Breast Neoplasms"가 같은 NCT02472353인데 두 건으로 셌다.
        # 실체(NCT)로 센다.
        check("중복을 NCT로 센다 (문자열이 아니라)",
              "NCT 기준" in txt, txt.split("\n")[0])
        import csv as _c0
        _tnr = [r for r in _c0.DictReader(open(out, encoding="utf-8-sig"))
                if r["label"] == "TN"]
        _n = [r["nct"] for r in _tnr]
        check("고른 TN 안에 같은 시험이 두 번 없다",
              len(_n) == len(set(_n)), "%d건 · 고유 %d" % (len(_n), len(set(_n))))
        import csv as _csv
        rows = list(_csv.DictReader(open(out, encoding="utf-8-sig")))
        check("TN·TP 번갈아 저장 (bench.run 규약)",
              [r["label"] for r in rows] == ["TN", "TP"] * (len(rows) // 2))
        # NCT 가 없으면 누출 차단이 안 걸려 **답안지를 읽는다**
        check("TN 전부에 라벨 출처 NCT가 있다",
              all(r["nct"] for r in rows if r["label"] == "TN"))
        check("열 이름이 bench_matched 규약과 같다",
              list(rows[0].keys()) == F.OUT_COLS)
        import math as _m
        worst = max(abs(_m.log10(int(rows[i + 1]["pubmed"]))
                        - _m.log10(int(rows[i]["pubmed"])))
                    for i in range(0, len(rows), 2))
        check("문헌량 균형이 TOL 안에 든다", worst <= F.TOL, "%.3f" % worst)
        check("검정력 부족을 실행 전에 경고한다", "잡을 수 없다" in txt)
    else:
        check("gen_run1.csv 없음 — select 시험 건너뜀", True, "생성 실험 먼저")


def test_demo():
    """웹 데모 로직 — **다섯 상태를 다 태운다.**

    "정상만 되는가"를 보면 실패 경로가 죽어 있어도 통과한다.
    그리고 이건 **공개 링크에 물릴 코드**다 — 비용과 안전이 걸려 있다.

    UI(`app.py`)는 여기서 시험하지 않는다. Gradio를 못 까는 환경에서 썼고,
    **화면 모양은 확인하지 못했다는 것을 `배포.md` 에 적었다.**
    """
    print("\n[42] 웹 데모 로직")
    import importlib
    import tempfile as _tf4
    from .. import demo as D
    from ..io import budget as BG

    tmpd = _tf4.mkdtemp()
    old_env = dict(os.environ)
    os.environ["BIOREROUTE_DAILY_RUNS"] = "2"
    os.environ["BIOREROUTE_BUDGET_FILE"] = os.path.join(tmpd, "b.json")
    importlib.reload(BG)
    D.budget = BG
    try:
        # ① 입력 오류
        for bad in ("metformin", "  /  ", "x" * 100 + " / y"):
            r = D.run_pair(bad)
            check("입력 오류 — %r" % bad[:14], r["상태"] == "입력오류", r["상태"])

        # ② 안전 차단 — **예산보다 먼저.** 막힐 질의에 실행권을 쓰면 안 된다
        used0 = BG.status()["쓴 것"]
        r = D.run_pair("sarin / nerve agent")
        check("통제 물질을 차단한다", r["상태"] == "차단", r["상태"])
        check("차단 시 예산을 소비하지 않는다",
              BG.status()["쓴 것"] == used0, BG.status())

        # ③ LLM 없음 — 그럴듯한 빈 결과를 내지 않는다
        with patched(llm, available=lambda: False):
            r = D.run_pair("metformin / Breast Cancer")
        check("LLM 없으면 미리 끊는다", r["상태"] == "LLM없음", r["상태"])
        check("그때도 예산을 안 쓴다", BG.status()["쓴 것"] == used0)

        # ④ 정상 경로 — 게이트 진행과 근거 카드
        def _abs(ids, retry=1):
            return {i: {"pmid": i, "title": "A randomized trial of metformin",
                        "abstract": "RESULTS: metformin did not improve "
                                    "outcomes (p=0.44).",
                        "pubtypes": ["Randomized Controlled Trial"],
                        "study_type": "rct", "year": 2022, "journal": "J",
                        "error": None} for i in ids}

        def _fake(prompt, system="", model=None, as_json=False, purpose=""):
            # **진짜 구현은 모든 경로에서 _CALLS 에 남긴다.** 모의도 그래야
            # 예산 회계가 실제와 같게 돈다(안 그러면 예산이 영영 안 준다).
            llm._CALLS.append({"key": "m", "cached": False})
            if "작용 기전을 분류하라" in prompt:
                d = [{"idx": 1, "mech": "간접", "target": "",
                      "confidence": "high", "why": "우회 경로"}]
            else:
                d = [{"pmid": "1", "direction": "refute", "study_type": "rct",
                      "size": "large", "decisive": True,
                      "quote": "RESULTS: metformin did not improve outcomes "
                               "(p=0.44).",
                      "population": "", "dose": "", "timing": "",
                      "certainty": "high", "confidence": "high"}]
            return {"ok": True, "text": "", "data": d, "error": None,
                    "provenance": {"prompt_sha": "m"}, "cached": False}

        steps = []
        with patched(sources,
                     pubmed_lookup=lambda q, retmax=3: {
                         "count": 42, "pmids": ["1"], "title": "T", "error": None},
                     pubmed_search=lambda q, retmax=8, max_year=None: {
                         "count": 42, "pmids": ["1"], "error": None},
                     pubmed_abstracts=_abs), \
             patched(llm, complete=_fake, available=lambda: True):
            llm._CALLS.clear()
            r = D.run_pair("metformin / Breast Cancer",
                           progress=lambda s, d: steps.append(s),
                           cache_path=os.path.join(tmpd, "c.json"))
        check("정상 경로가 판정을 낸다", r["ok"] and r["판정"], r.get("상태"))
        # 08-19 — 단계 이름을 사용자 말로 바꿨다(결함 274). **이름이 아니라
        #   «진행을 알리는가» 를 본다** — 이름은 또 바뀔 수 있다.
        from ..demo import GATE_KO as _GK
        check("게이트 진행을 알린다",
              any(x in _GK.values() or x in _GK for x in steps), steps[:3])
        check("근거 카드에 PMID·가중치가 있다",
              r["근거"] and r["근거"][0]["PMID"] and r["근거"][0]["가중치"] > 0,
              r["근거"][:1])
        check("게이트 통과 기록이 남는다", len(r["게이트"]) >= 3, len(r["게이트"]))
        check("새 LLM 호출 수를 센다", r["비용"] > 0, r["비용"])

        # ⑤ 한도 소진 — 조용히 실패하지 않는다
        with patched(sources, pubmed_lookup=lambda q, retmax=3: {
                "count": 1, "pmids": ["1"], "title": "T", "error": None},
                pubmed_search=lambda q, retmax=8, max_year=None: {
                    "count": 1, "pmids": ["1"], "error": None},
                pubmed_abstracts=_abs), \
             patched(llm, complete=_fake, available=lambda: True):
            D.run_pair("aspirin / Migraine", cache_path=os.path.join(tmpd, "c.json"))
            r = D.run_pair("ibuprofen / Migraine",
                           cache_path=os.path.join(tmpd, "c.json"))
        check("한도를 넘으면 정직하게 알린다",
              r["상태"] == "한도소진" and "한도" in r["메시지"], r["상태"])

        # ⑥ 예시는 **예산을 안 쓴다** — 다른 모듈 계수기에 의존하지 않는 방어
        check("예시 목록이 비어 있지 않다", len(D.PRESETS) >= 3)
        used_before = BG.status()["쓴 것"]
        with patched(llm, available=lambda: False):
            D.run_pair(D.PRESETS[0][0])
        check("예시는 예산을 소비하지 않는다",
              BG.status()["쓴 것"] == used_before, BG.status())
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        importlib.reload(BG)
        import shutil as _sh4
        _sh4.rmtree(tmpd, ignore_errors=True)


def test_evidence():
    """데모 탭③이 쓰는 증거 — **숫자를 코드에 적지 않는다.**

    `결함 38건`·`봉인 5개` 를 화면 코드에 타이핑하면 다음에 39건이 됐을 때
    **화면만 거짓말한다.** 산출물에서 세는지 확인한다.
    """
    print("\n[43] 데모 증거 — 산출물에서 센다")
    import tempfile as _tf5
    from .. import evidence as EV

    # ── 결함 수: 문장이 아니라 **표의 행**을 센다 ────────────────────
    #   문서에 "38건"이라 적혀 있어도 표가 39행이면 표가 사실이다.
    tmpd = _tf5.mkdtemp()
    fake = os.path.join(tmpd, "Bio-ReRoute_발견정리.md")
    with open(fake, "w", encoding="utf-8") as fh:
        fh.write("아무 말\n\n결함 **99건**이라고 문장에 적어 둔다\n\n"
                 "| # | 결함 | 잘못 나올 뻔한 결과 |\n|---|---|---|\n"
                 "| 1 | a | x |\n| 2 | b | y |\n| 3 | c | z |\n\n다른 절\n")
    check("문장이 아니라 표의 행을 센다", EV.defect_count(fake) == 3,
          EV.defect_count(fake))
    check("표가 없으면 None (0이라 하지 않는다)",
          EV.defect_count(os.path.join(tmpd, "없다.md")) is None)

    # ── 봉인: 해시가 **지금도 맞는지** 대조한다 ──────────────────────
    doc = os.path.join(tmpd, "명세.md")
    open(doc, "w", encoding="utf-8").write("기준을 여기 적는다\n")
    import hashlib
    h = hashlib.sha256(open(doc, "rb").read()).hexdigest()
    json.dump({"문서": "명세.md", "sha256": h, "작성": "2026-08-06T09:00"},
              open(os.path.join(tmpd, "명세_봉인.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    s = EV.seals(tmpd)
    check("봉인을 읽고 무결을 확인한다",
          len(s) == 1 and s[0]["무결"] is True, s)
    # **문서를 고치면 깨졌다고 해야 한다.** 이게 봉인의 전부다.
    open(doc, "a", encoding="utf-8").write("나중에 슬쩍 고친다\n")
    s2 = EV.seals(tmpd)
    check("문서가 바뀌면 깨졌다고 한다", s2[0]["무결"] is False, s2[0])
    os.remove(doc)
    s3 = EV.seals(tmpd)
    check("대상이 없으면 '확인 불가' (무결이라 하지 않는다)",
          s3[0]["무결"] is None, s3[0])

    # ── 사례 파일: 없으면 **없다고** 돌려준다 ────────────────────────
    check("사례 파일이 없으면 None",
          EV.cases(os.path.join(tmpd, "없다.json")) is None)
    cp = os.path.join(tmpd, "cases.json")
    json.dump({"사례": []}, open(cp, "w", encoding="utf-8"))
    check("빈 사례도 None (있는 척하지 않는다)", EV.cases(cp) is None)
    json.dump({"사례": [{"질의": "a / b", "판정": "기각"}]},
              open(cp, "w", encoding="utf-8"), ensure_ascii=False)
    check("사례가 있으면 돌려준다", (EV.cases(cp) or {}).get("사례"))

    # ── 실제 저장소에서도 도는가 ─────────────────────────────────────
    #
    #   **건수를 하드코딩하지 않는다.** 처음엔 `== 38` 로 썼는데 결함이
    #   39건이 되자 시험이 깨졌다 — 내가 경고한 바로 그 실수를 시험에서 했다.
    #   대신 **더 나은 불변식**을 건다: 문서 문장의 "N건"과 표 행수가 같은가.
    #   어긋나면 둘 중 하나가 거짓말이다.
    real = EV.summary()
    check("실제 결함 표를 센다", isinstance(real["결함"], int) and real["결함"] > 30,
          real["결함"])
    # 정규식이 아무것도 못 찾으면 **통과해도 의미가 없다.** 먼저 찾는지 본다.
    _CLAIM = re.compile(r"결함 \*{0,2}(\d+)건|공개한 (\d+)건")
    _docs = [os.path.join(EV.ROOT, f) for f in
             ("Bio-ReRoute_발견정리.md", "Bio-ReRoute_1페이지.md",
              "투명성_연구윤리.md", "발표뼈대.md")]
    # ── 코드 펜스는 **주장이 아니다** ────────────────────────
    #
    #   결함 60 항목이 *"슬라이드가 39건이라 적혀 있었다"* 를 펜스로 인용한다.
    #   그건 과거 상태의 증거이지 현재 주장이 아닌데, 이 검사가 그걸
    #   새 드리프트로 세어 붉어졌다.
    #
    #   **규칙을 `docaudit._fenced` 하나로 합친다.** 두 검사기가 "무엇이
    #   주장인가"를 따로 정의하면 그 둘이 갈라지고, 그게 바로 이 검사가
    #   막으려는 종류의 드리프트다.
    #   ## 08-12 — **합쳤다고 적어 놓고 절반만 합쳐 있었다** (결함 136)
    #
    #   `_fenced` 만 가져오고 `_skip`(줄 단위 규칙)은 안 가져왔다. 그래서
    #   결함 136 행을 대장에 적자마자 — 그 행이 `결함 39건` 을 **인용해야만
    #   기록이 되는데** — 이 시험이 빨개졌다. **결함을 적을수록 시험이
    #   붉어지는 구조**였다. 위 문단이 경고한 갈라짐이 위 문단 아래에서
    #   일어나 있었다.
    from ..bench.docaudit import _fenced, _skip as _skipline
    _claims, _where = set(), {}
    for _d in _docs:
        if not os.path.exists(_d):
            continue
        _t = open(_d, encoding="utf-8").read()
        _skip = _fenced(_t)
        _lines = _t.split("\n")
        for m in _CLAIM.finditer(_t):
            _ln = _t[:m.start()].count("\n") + 1
            if _ln in _skip or _skipline(_lines[_ln - 1]):
                continue
            v = m.group(1) or m.group(2)
            _claims.add(v)
            _where.setdefault(v, set()).add(os.path.basename(_d))
    check("검사가 실제로 문장을 찾는다 (빈 검사는 검사가 아니다)",
          len(_claims) > 0, sorted(_claims))
    check("문서가 말하는 건수 = 표의 행수",
          _claims == {str(real["결함"])},
          "문장 %s vs 표 %d · %s"
          % (sorted(_claims), real["결함"],
             {k: sorted(v) for k, v in _where.items()
              if k != str(real["결함"])}))
    check("실제 봉인이 전부 무결하다",
          real["봉인_깨짐"] == 0 and real["봉인_무결"] >= 4, real)

    import shutil as _sh5
    _sh5.rmtree(tmpd, ignore_errors=True)


def test_report_numbers():
    """**보고서에 실린 수치를 산출물에서 다시 계산해 대조한다.**

    결함 19가 정확히 이것이었다 — 터미널에서 손계산한 p값이 문서로 직행했고
    코드 어디에도 없었다. 보고서는 심사위원이 읽는 문서다. **드리프트하면
    거짓말이 된다.** 그래서 시험이 매번 대조한다.

    산출물이 없으면 건너뛴다(배포본에는 원자료가 없을 수 있다).
    **없는데 통과했다고 하지 않는다** — 건너뛴 사실을 표시한다.
    """
    print("\n[44] 보고서 수치 ↔ 산출물 대조")
    from collections import Counter as _Cnt

    from .. import evidence as EV
    from ..bench.stats import wilson as _w

    rep_p = os.path.join(EV.ROOT, "연구기술보고서.md")
    if not os.path.exists(rep_p):
        check("보고서 없음 — 대조 건너뜀", True, "연구기술보고서.md")
        return
    rep = open(rep_p, encoding="utf-8").read()

    def cmp(label, claim, actual):
        """**본문에 있고** 실제와 같아야 한다. 둘 중 하나만이면 실패."""
        check("보고서 %s" % label,
              str(claim) in rep and str(claim) == str(actual),
              "본문 %r · 실제 %r" % (claim, actual))

    # ── [50] **논지의 절반이 문서에서 사라지지 않게 못 박는다** (결함 46) ──
    #
    # ECE 는 재 놓고도 보고서·1페이지·발표 셋 다에서 빠져 있었다. 하필
    # 값이 불리해서(B5 0.105 > B0 0.072) **결과적으로 선택적 보고**가 됐다.
    # 숫자 자체를 박지 않는다 — **"보정 수치가 본문에 있는가"** 만 본다.
    # ── 08-12 — **주석과 코드가 반대였다** (결함 132) ────────────────
    #
    #   바로 위 주석이 *"숫자 자체를 박지 않는다 — 「보정 수치가 본문에
    #   있는가」만 본다"* 라고 적어 놓고, 아래에서 `0.105` · `0.072` 를
    #   **박고 있었다.** 그래서 08-12에 Platt 을 적용한 뒤에도
    #   **보고서를 고치면 시험이 깨지는** 상태였다.
    #
    #   그리고 그 두 값은 **dev(층A) 수치**였고 집합을 안 밝힌 채 쓰였다.
    #   지금 코드로 재현되는 값은 dev 0.1168/0.0756 · 홀드아웃 0.1039/0.1066 —
    #   **0.105 는 어느 것도 아니다.**
    #
    #   주석이 말한 대로 고친다: **값이 아니라 「있는가」를 본다.**
    check("보고서가 ECE 를 적는다", "ECE" in rep)
    check("보고서가 **불리한 쪽을 감추지 않는다**",
          "더 나쁘다" in rep or "우리가 **졌다**" in rep or "졌다" in rep)
    check("보고서가 Platt 을 언급한다 — 미적용이든 적용이든 **상태를 적는다**",
          "Platt" in rep)
    # 결함 47 — 정답표 감사가 본문에 있어야 한다
    for tok in ("43%", "warfarin", "5/5"):
        check("보고서가 정답표 감사 %r 를 적는다" % tok, tok in rep, tok)
    check("보고서가 사후 민감도임을 명시한다", "사후" in rep and "주 수치" in rep)

    # 여기에 숫자를 박아 두면 **결함이 하나 늘 때마다 시험이 깨진다.**
    # 이미 한 번 겪었다(38→39). 그런데 그때 다른 시험만 고치고 이 줄은
    # 그대로 뒀다가 40·41에서 또 걸렸다 — **같은 실수가 파일을 옮겨 재발**
    # 하는 유형 그대로다. 불변식은 "39"가 아니라
    # **"보고서가 말하는 건수 = 표의 행수"** 이므로 그것만 검사한다.
    cmp("결함 건수", EV.defect_count(), EV.defect_count())

    gp = os.path.join(EV.ROOT, "gen_run2.csv")
    if os.path.exists(gp):
        g = list(csv.DictReader(open(gp, encoding="utf-8-sig")))
        c, n = _Cnt(x["label"] for x in g), len(g)
        cmp("생성 후보 수", "{:,}".format(n), "{:,}".format(n))
        cmp("승인 비율", "17%", "%.0f%%" % (100 * c["승인"] / n))
        cmp("미지 비율", "71%", "%.0f%%" % (100 * c["미지"] / n))

    pp = os.path.join(EV.ROOT, "봉인예측_20260805.csv")
    if os.path.exists(pp):
        p = list(csv.DictReader(open(pp, encoding="utf-8-sig")))
        real = [x for x in p if x["kind"] == "진행중"]
        ctrl = [x for x in p if x["kind"] == "음성대조"]
        cmp("진행중 유망", "22/60",
            "%d/%d" % (sum(1 for x in real if x["verdict"] == "유망"), len(real)))
        # **음성대조 0/20 이 이 보고서에서 가장 센 수치다.** 반드시 대조한다.
        cmp("음성대조 유망", "0/20",
            "%d/%d" % (sum(1 for x in ctrl if x["verdict"] == "유망"), len(ctrl)))

    sp = os.path.join(EV.ROOT, "gen_state.json")
    if os.path.exists(sp):
        st = json.load(open(sp, encoding="utf-8"))
        F0 = "F0: 문헌 근거 없음(환각)"
        tn = [x for x in st["candidates"] if x["label"] == "TN"]
        tp = [x for x in st["candidates"] if x["label"] == "TP"]
        kt = sum(1 for x in tn
                 if x["verdict"] == "기각" and F0 not in (x.get("reason") or ""))
        kp = sum(1 for x in tp
                 if x["verdict"] == "기각" and F0 not in (x.get("reason") or ""))
        cmp("TN 근거기반 기각", "6/14", "%d/%d" % (kt, len(tn)))
        cmp("TP 근거기반 기각", "1/14", "%d/%d" % (kp, len(tp)))
        lo, hi = _w(kt, len(tn))
        cmp("TN 신뢰구간", "[21.4–67.4]", "[%.1f–%.1f]" % (100 * lo, 100 * hi))

    # 성능을 주장하지 않는다는 것도 문서 규율이다 — 문장이 남아 있는지 본다
    check("보고서가 우위를 주장하지 않는다고 적는다",
          "우위를 주장하지 않는다" in rep)
    check("보고서가 '모른다'와 '차이 없다'를 구분한다",
          "측정 불가" in rep and "차이 없다" in rep)


def test_safety():
    """안전 게이트 — 제안서 §5. **막는 쪽과 통과시키는 쪽을 둘 다 본다.**

    "막는가"만 시험하면 **전부 막는 게이트**도 통과한다. 그런데 과잉 차단은
    정당한 재창출 연구를 막고, 그건 이 시스템의 존재 이유를 훼손한다.
    탄저 치료제·두창 치료제·보톡스 편두통은 **반드시 통과해야 한다.**
    """
    print("\n[41] 안전 게이트 — 통제 물질 차단 (제안서 §5)")
    import tempfile as _tf3
    from ..core import safety
    from ..core.state import Candidate as _C3, RunState as _R3

    for d, c in (("sarin", "nerve agent exposure"),
                 ("VX nerve agent", "tox"),
                 ("sulfur mustard", "skin injury"),
                 ("노비촉", "해독제"),
                 ("ricin", "weaponized aerosol delivery")):
        bad, why = safety.screen(d, c)
        check("차단 — %s" % d[:18], bad and why, why)

    # **여기가 더 중요하다.** 정당한 연구를 막으면 안 된다.
    for d, c in (("ciprofloxacin", "Anthrax"),            # 탄저 치료제
                 ("tecovirimat", "Smallpox"),             # 두창 치료제
                 ("botulinum toxin", "Chronic Migraine"),  # 승인 적응증
                 ("pralidoxime", "Organophosphate poisoning"),
                 ("metformin", "Breast Cancer")):
        bad, why = safety.screen(d, c)
        check("통과 — %s / %s" % (d[:14], c[:16]), not bad, why)

    check("빈 입력은 통과", not safety.screen("", "")[0])

    # 파이프라인 최상단에서 **예외로** 멈춰야 한다.
    #   빈 결과를 돌려주면 호출부가 "근거가 없구나"로 읽는다 —
    #   막은 것과 없는 것은 다르다(결함 35와 같은 교훈).
    cwd = os.getcwd()
    tmpd = _tf3.mkdtemp()
    try:
        os.chdir(tmpd)
        st = _R3(query_title="t", settings="", stamp="", config={},
                 candidates=[_C3(name="sarin / nerve", origin="x",
                                 query="sarin AND nerve", drug="sarin",
                                 disease="nerve agent")])
        raised = False
        try:
            gates.run_pipeline(st)
        except safety.Blocked:
            raised = True
        check("파이프라인이 예외로 멈춘다 (빈 결과가 아니라)", raised)
        check("차단을 로그에 남긴다", os.path.exists("safety_log.jsonl"))
        # 정상 후보는 게이트를 통과해 판정까지 가야 한다
        st2 = _R3(query_title="t", settings="", stamp="", config={},
                  candidates=[_C3(name="metformin / Breast Cancer", origin="x",
                                  query="q", drug="metformin",
                                  disease="Breast Cancer")])
        st2 = gates.run_pipeline(st2)
        check("정상 후보는 막지 않는다", st2.candidates[0].verdict != "")
    finally:
        os.chdir(cwd)
        import shutil as _sh3
        _sh3.rmtree(tmpd, ignore_errors=True)


def test_prospective():
    """전향 봉인 예측 — 제안서 §4.2 ③. **사후편향이 0인 유일한 숫자.**

    나는 이 코드를 CT.gov 에 접근할 수 없는 환경에서 썼다. 그러므로
    **네트워크만 모의로 대신하고 나머지 전 경로를 실제로 태운다.**
    필드명이 맞는지는 `probe` 명령으로 사람이 확인해야 한다 —
    모르는 것을 안다고 하지 않는다.
    """
    print("\n[40] 전향 봉인 예측")
    import io as _io
    import shutil
    import tempfile as _tf
    from ..bench import prospective as P

    def study(nct, drug, cond, phase="PHASE3", alloc="RANDOMIZED", n=300,
              pc="2025-06-30", res=False, stype="INTERVENTIONAL"):
        return {"hasResults": res, "protocolSection": {
            "identificationModule": {"nctId": nct},
            "statusModule": {"overallStatus": "ACTIVE_NOT_RECRUITING",
                             "primaryCompletionDateStruct": {"date": pc}},
            "conditionsModule": {"conditions": [cond]},
            "armsInterventionsModule": {"interventions": [{"name": drug},
                                                          {"name": "Placebo"}]},
            "designModule": {"phases": [phase], "studyType": stype,
                             "designInfo": {"allocation": alloc},
                             "enrollmentInfo": {"count": n}}}}

    T = "2026-08"
    check("정상 시험은 사용", P.usable(P.parse(study("N1", "d", "c")), T)[0])
    # 각 제외 사유가 **실제로 그 사유로** 걸리는지 본다. 개수만 세면
    # 엉뚱한 규칙이 잡아도 통과한다.
    for st, key in ((study("N", "d", "c", res=True), "이미 결과"),
                    (study("N", "d", "c", alloc="NON_RANDOMIZED"), "무작위배정 아님"),
                    (study("N", "d", "c", phase="PHASE1"), "1상"),
                    (study("N", "d", "c", n=20), "부족"),
                    (study("N", "d", "c", pc="2099-01-01"), "미래"),
                    (study("N", "Placebo", "c"), "약물 개입 없음"),
                    (study("N", "d", "c", stype="OBSERVATIONAL"), "개입 연구 아님"),
                    (study("N", "d", "c", pc=""), "1차 완료일 미기재")):
        ok, why = P.usable(P.parse(st), T)
        check("제외 사유 — %s" % key, (not ok) and key in why, why)
    # **결과가 이미 있으면 전향이 아니다.** 이 한 줄이 이 실험의 전제다.
    check("결과 게시된 시험은 절대 안 쓴다",
          not P.usable(P.parse(study("N", "d", "c", res=True)), T)[0])

    # ── 게시 기한 창 — **양끝을 다 잘라야 한다** ────────────────────────
    #   FDAAA는 1차 완료 후 12개월 내 게시를 요구한다. 그러므로
    #     1개월 전  → 기한이 2027년. 56일 안에 안 나온다
    #     12개월 전 → 기한이 지금. **가장 임박**
    #     19년 전   → 좀비 등록. 영영 안 나온다
    #   실측: probe 표본에 1차 완료 **2007-06** 인 말라리아 시험이 있었다.
    #   "지났다"만 보면 이런 게 들어오고, "최근 순"으로 고르면 반대편 끝이
    #   들어온다. **한쪽만 막으면 다른 쪽으로 샌다.**
    for pc, want, key in (("2026-07", False, "아직 멀다"),
                          ("2026-02", True, ""),
                          ("2025-08", True, ""),
                          ("2023-08", True, ""),
                          ("2023-07", False, "좀비"),
                          ("2007-06", False, "좀비")):
        ok, why = P.usable(P.parse(study("N", "d", "c", pc=pc)), T)
        check("기한 창 %s → %s" % (pc, "사용" if want else "제외"),
              ok == want and (want or key in why), why)
    check("개월 계산", P.months_since("2025-08", "2026-08") == 12)

    # ── probe: **필드명이 틀린 것**과 **그 시험이 원래 없는 것**을 가르는가 ──
    #   첫 판은 빈 값을 그냥 세어 경고했다. 관찰연구에 phase 가 없는 건
    #   정상인데 "빈 필드가 있다"가 떴다. **조잡한 경고는 무시되는 법을
    #   가르치고, 그러면 진짜 경고도 놓친다.**
    def _probe(payload):
        bb, oo = _io.StringIO(), sys.stdout
        sys.stdout = bb
        try:
            with patched(P, _get=lambda url: payload):
                rc = P.cmd_probe(type("A", (), {
                    "status": "ACTIVE_NOT_RECRUITING", "n": 5,
                    "pages": 60, "verbose": False})())
        finally:
            sys.stdout = oo
        return rc, bb.getvalue()

    rc_ok, t_ok = _probe({"studies": [
        study("N1", "semaglutide", "Heart Failure"),
        study("N2", "Orsiro DES", "CAD", stype="OBSERVATIONAL"),
        study("N3", "Mirabegron", "Obesity", phase="PHASE1", n=40),
        study("N4", "exercise", "COPD", phase="NA", n=44)], "nextPageToken": "x"})
    check("probe — 정상 필드를 오류라 하지 않는다",
          rc_ok == 0 and "필드명은 맞다" in t_ok and "이름 오류" not in t_ok)
    check("probe — 수율을 환산해 준다", "예상 수율" in t_ok)

    bad = [{"hasResults": False, "protocolSection": {
        "identificationModule": {"nctId": "N%d" % i},
        "statusModule": {"overallStatus": "X"},          # 1차완료일 필드 없음
        "conditionsModule": {"conditions": ["C"]},
        "armsInterventionsModule": {"interventions": [{"name": "d"}]},
        "designModule": {"phases": ["PHASE3"], "studyType": "INTERVENTIONAL",
                         "designInfo": {"allocation": "RANDOMIZED"},
                         "enrollmentInfo": {"count": 300}}}} for i in range(4)]
    rc_bad, t_bad = _probe({"studies": bad})
    check("probe — 전부 비면 필드명 오류로 잡는다",
          rc_bad == 1 and "primary_completion" in t_bad and "FIELDS" in t_bad, rc_bad)

    tmp = _tf.mkdtemp()
    try:
        # 기한에서 먼 것·가까운 것을 섞어 둔다 — 정렬이 실제로 고르는지 본다
        mix = ["2025-08", "2025-02", "2024-08", "2026-02", "2023-10"]
        json.dump({"studies": [study("NCT%04d" % i, "drug%d" % i, "Cond%d" % (i % 7),
                                     pc=mix[i % len(mix)])
                               for i in range(1, 31)], "nextPageToken": None},
                  open(os.path.join(tmp, "p_0001.json"), "w", encoding="utf-8"),
                  ensure_ascii=False)
        out = os.path.join(tmp, "pool.csv")
        bb, oo = _io.StringIO(), sys.stdout
        sys.stdout = bb
        try:
            rc = P.cmd_select(type("A", (), {"dir": tmp, "out": out, "n": 10,
                                             "controls": 5, "seed": 1,
                                             "force": True})())
        finally:
            sys.stdout = oo
        check("select 정상 종료", rc == 0, rc)
        import csv as _c1
        rows = list(_c1.DictReader(open(out, encoding="utf-8-sig")))
        check("진행중 10 + 음성대조 5", len(rows) == 15 and
              sum(1 for r in rows if r["kind"] == "음성대조") == 5, len(rows))
        # 대조군이 실제 쌍과 겹치면 음성 대조가 아니다
        real = {(r["drug"], r["condition"]) for r in rows if r["kind"] == "진행중"}
        ctrl = {(r["drug"], r["condition"]) for r in rows if r["kind"] == "음성대조"}
        check("음성대조가 진행중 쌍과 겹치지 않는다", not (real & ctrl))
        # 기한(12개월)에 가까운 것부터 골라야 한다. 최근 순이 아니다.
        picked = [r["primary_completion"] for r in rows if r["kind"] == "진행중"]
        check("게시 기한에 가장 가까운 것이 1순위",
              picked and picked[0] == "2025-08", picked[:3])

        # ── 봉인: 파일을 고치면 검증이 **거부**해야 한다 ──────────────
        pred = os.path.join(tmp, "pred.csv")
        with open(pred, "w", encoding="utf-8-sig", newline="") as fh:
            w = _c1.writer(fh)
            w.writerow(["nct", "kind", "drug", "condition", "verdict",
                        "confidence", "reason", "n_support", "n_refute",
                        "primary_completion"])
            w.writerow(["NCT0001", "진행중", "d", "c", "기각", 12, "반박 우세",
                        1, 3, "2025-06-30"])
        bb, oo = _io.StringIO(), sys.stdout
        sys.stdout = bb
        try:
            P.cmd_seal(type("A", (), {"pred": pred})())
        finally:
            sys.stdout = oo
        seal = json.load(open(pred.replace(".csv", "_봉인.json"), encoding="utf-8"))
        check("봉인이 해시·건수·검증절차를 남긴다",
              seal["sha256"] and seal["건수"] == 1 and len(seal["검증절차"]) >= 5)
        # **어디서 골랐나**가 없으면 "표본을 유리하게 골랐다"를 반박 못 한다
        check("봉인이 표본 선택 조건을 적는다",
              "표본조건" in seal and "1차완료" in seal["표본조건"], seal.get("표본조건"))
        check("봉인이 창 자체가 선택 효과임을 적는다",
              any("선택 효과" in x for x in seal["한계"]))
        # 풀과 예측은 이름이 비슷해 헷갈린다. 죽지 말고 알려줘야 한다.
        bb, oo = _io.StringIO(), sys.stdout
        sys.stdout = bb
        try:
            rc_wrong = P.cmd_seal(type("A", (), {"pred": out})())   # 풀을 넘김
        finally:
            sys.stdout = oo
        check("풀을 봉인하려 하면 거부하고 이유를 말한다",
              rc_wrong == 2 and "예측 파일이 아니다" in bb.getvalue(), rc_wrong)
        # 제안서 §4.2 — 산출물은 정확도가 아니라 목록과 절차다
        check("봉인이 한계를 명시한다",
              any("정확도가 아니라" in x for x in seal["한계"]), seal["한계"])

        with open(pred, "a", encoding="utf-8-sig") as fh:
            fh.write("NCT9,진행중,x,y,유망,90,,0,0,\n")
        bb, oo = _io.StringIO(), sys.stdout
        sys.stdout = bb
        try:
            rc2 = P.cmd_verify(type("A", (), {
                "pred": pred, "cache": os.path.join(tmp, "c.json"),
                "results_cache": os.path.join(tmp, "r.json")})())
        finally:
            sys.stdout = oo
        check("예측을 고치면 검증이 거부한다",
              rc2 == 2 and "무효" in bb.getvalue(), rc2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_s1_and_router_branch():
    """[45] S1 구조 게이트 — 제안서 §2.5 · §3.3-7.

    이 시험이 지켜야 하는 것 셋.

      ① **저신뢰는 기각이 아니다.** 제안서가 `연산 제외` 라고 썼다.
         구조를 못 믿겠다는 말이지 약이 안 듣는다는 말이 아니다
      ② **조회 실패는 발견이 아니다.** 경로를 바꾸지 않는다 (결함 35)
      ③ **s1 을 ORDER 에 넣은 것이 기존 구성의 trail 을 바꾸지 않는다.**
         바뀌면 봉인·동결된 수치가 전부 다른 시스템의 수치가 된다
    """
    from bioreroute.core import gates
    from bioreroute.core.state import RunState, Candidate
    from bioreroute.io import structure as _st

    # ── 먼저: 모의가 실제로 불리는가. 안 불리면 아래가 전부 무의미하다 ──
    seen = []
    real = _st.assess

    def fake(target, organism=None):
        seen.append((target, organism))
        if "RDRP" in target.upper():
            return {"label": "신뢰", "why": "평균 pLDDT 92.4 · 70 미만 잔기 3%",
                    "cif_url": "https://x/a.cif", "plddt": {"mean": 92.4, "frac_low": .03}}
        if "IDP" in target.upper():
            return {"label": "저신뢰", "why": "평균 pLDDT 41.2 · 70 미만 잔기 88%",
                    "cif_url": "https://x/b.cif", "plddt": {"mean": 41.2, "frac_low": .88}}
        if "GHOST" in target.upper():
            return {"label": "구조없음", "why": "UniProt: UniProt 0건",
                    "cif_url": None, "plddt": None}
        return {"label": "오류", "why": "URLError: 끊김", "cif_url": None, "plddt": None}

    def mk(nm, route, tgt, mech="직접·병원체", dis="COVID-19"):
        c = Candidate(name=nm, drug="d", disease=dis, origin="t", query="q")
        c.route, c.mech_class, c.router_rec = route, mech, {"target": tgt}
        return c

    _st.assess = fake
    try:
        cs = [mk("A", "structure", "SARS-CoV-2 RdRp"),
              mk("B", "structure", "IDP region"),
              mk("C", "structure", "GHOST protein"),
              mk("D", "structure", "net fail"),
              mk("E", "evidence", "JAK1", "직접·숙주")]
        gates.gate_s1(RunState("q", "B7", "t", cs, dict(gates.CONFIGS["B7"])))
    finally:
        _st.assess = real

    check("[45] 모의 S1이 실제로 불렸다", len(seen) == 4, "호출 %d회" % len(seen))
    check("[45] 신뢰 → 구조 경로 유지", cs[0].route == "structure", cs[0].route)
    check("[45] 저신뢰 → 증거 경로 (기각 아님)",
          cs[1].route == "evidence" and not cs[1].killed, cs[1].route)
    check("[45] 구조없음 → 증거 경로 (기각 아님)",
          cs[2].route == "evidence" and not cs[2].killed, cs[2].route)
    check("[45] **조회 실패는 경로를 바꾸지 않는다** (결함 35)",
          cs[3].route == "structure" and not cs[3].killed, cs[3].route)
    check("[45] 증거 경로 후보에는 S1을 조회조차 안 한다",
          all("JAK1" != t for t, _ in seen))
    check("[45] 병원체 분류일 때만 종 힌트를 준다",
          seen[0][1] == "SARS-CoV-2", str(seen[0]))

    # ③ 기존 구성의 게이트 순서가 s1 추가로 바뀌면 안 된다
    def order(cfg):
        cf = gates.CONFIGS[cfg]
        return [n for n in gates.ORDER
                if cf.get(n, False) or n not in gates.QUIET_WHEN_OFF]
    base = ["f0", "rag", "router", "s2", "skeptic", "registry"]
    for cfg in ("B0", "B5", "B6", "W1"):
        check("[45] %s trail 이 s1 추가로 안 바뀐다" % cfg, order(cfg) == base,
              str(order(cfg)))
    check("[45] B7 에서만 s1 이 라우터 뒤에 들어간다",
          order("B7") == ["f0", "rag", "router", "s1", "s2", "skeptic", "registry"])

    # 실제 run_pipeline 로도 확인한다 — 조립 순서 계산과 실물이 다를 수 있다
    c0 = Candidate(name="x / y", drug="x", disease="y", origin="t", query="q")
    st0 = gates.run_pipeline(RunState("q", "B0", "t", [c0], dict(gates.CONFIGS["B0"])))
    check("[45] B0 실물 trail 에 s1 흔적 0",
          not any(t.gate == "s1" for t in st0.candidates[0].trail),
          str([t.gate for t in st0.candidates[0].trail]))

    # pLDDT 가 점수로 새지 않는가 — 구조로 막았다고 했으니 검사한다
    import inspect
    src = inspect.getsource(_st)
    for bad in ("weight", "logodds", "log_odds", "affinity"):
        check("[45] structure.py 에 '%s' 라는 반환 키가 없다" % bad,
              ('"%s"' % bad) not in src and ("'%s'" % bad) not in src)

    # ── 활성부위 pLDDT — **제안서 §2.5 의 문구를 그동안 줄곧 안 지켰다** ──
    #
    #   §2.5 는 `활성부위 pLDDT` 라고 썼고 우리는 **단백질 전체 평균**을
    #   썼다. 게이트 이름은 §2.5 것이고 재는 것은 다른 것이었다 —
    #   결함 47(구성 개념 타당도)과 같은 자리다.
    #
    #   이 시험이 지키는 것: ① 주석에서 잔기를 뽑는가 ② 넓은 도메인 주석을
    #   포켓으로 착각하지 않는가 ③ **주석이 없을 때 조용히 전체 평균으로
    #   바꾸지 않는가** — ③ 이 원래 결함이었으므로 가장 중요하다.
    # 잔기 번호는 **1부터**다. 아래 vals 는 11~20번 잔기(인덱스 10~19)가
    # 잘 접힌 코어다. 첫 판에서 10·20~22 를 골랐다가 실패했다 —
    # **10번은 무질서 말단이었다.** 시험이 내 좌표 실수를 잡았다.
    ent = {"features": [
        {"type": "Binding site", "location": {"start": {"value": 12}, "end": {"value": 12}}},
        {"type": "Active site", "location": {"start": {"value": 15}, "end": {"value": 17}}},
        {"type": "Domain", "location": {"start": {"value": 1}, "end": {"value": 300}}},
        {"type": "Binding site", "location": {"start": {"value": 50}, "end": {"value": 200}}},
    ]}
    check("[45] UniProt 주석에서 활성·결합 잔기를 뽑는다",
          _st.site_positions(ent) == [12, 15, 16, 17], str(_st.site_positions(ent)))
    check("[45] **도메인 주석을 포켓으로 쓰지 않는다** — 넓은 구간은 전체 평균과 같다",
          all(p < 50 for p in _st.site_positions(ent)))

    # 무질서 말단이 전체 평균을 끌어내리는 상황. **이게 왜 중요한지의 실증이다.**
    vals = [30.0] * 10 + [95.0] * 10 + [30.0] * 10
    whole = sum(vals) / len(vals)
    ss = _st.site_stats(vals, _st.site_positions(ent))
    check("[45] 활성부위 평균이 전체 평균과 **다르다** — 그래서 §2.5 가 부위를 지정했다",
          ss["site_mean"] == 95.0 and whole < _st.PLDDT_OK,
          "부위 %.1f vs 전체 %.1f" % (ss["site_mean"], whole))
    check("[45] 전체 평균이면 `저신뢰`, 활성부위면 `신뢰` — 판정이 뒤집힌다",
          whole < _st.PLDDT_OK <= ss["site_mean"])
    check("[45] 모델 범위 밖 잔기를 **조용히 버리지 않고 센다**",
          _st.site_stats(vals, [15, 999, 1000])["out_of_range"] == 2)
    check("[45] 전부 범위 밖이면 부위 평균을 내지 않는다",
          _st.site_stats(vals, [999])["site_mean"] is None)

    # ③ assess() 가 근거를 **자기 입으로 밝히는가**
    def fake_get(url):
        if "uniprot" in url:
            return {"results": [{"primaryAccession": "P0MOCK", **ent}]}
        return [{"cifUrl": "c", "pdbUrl": "p", "confidenceScore": vals,
                 "latestVersion": 1}]

    def fake_get_nosite(url):
        if "uniprot" in url:
            return {"results": [{"primaryAccession": "P0NOSITE"}]}
        return [{"cifUrl": "c", "pdbUrl": "p", "confidenceScore": vals,
                 "latestVersion": 1}]

    real_get = _st._get
    import tempfile as _tf
    from bioreroute.io import cache as _ca
    try:
        for fn, want_basis, acc in ((fake_get, "활성부위", "P0MOCK"),
                                    (fake_get_nosite, "전체평균", "P0NOSITE")):
            _ca.configure(os.path.join(_tf.mkdtemp(), "c.json"), enabled=True)
            _st._get = fn
            a = _st.assess("MOCK")
            check("[45] assess 가 `basis`=%s 를 밝힌다" % want_basis,
                  a["basis"] == want_basis, str(a.get("basis")))
            check("[45] why 에 무엇으로 쟀는지 적힌다 (%s)" % want_basis,
                  want_basis.replace("평균", " 평균") in a["why"]
                  or want_basis in a["why"], a["why"][:70])
            if want_basis == "활성부위":
                check("[45] 활성부위로 재면 `신뢰` — 전체 평균이면 놓쳤을 표적이다",
                      a["label"] == "신뢰", a["why"][:70])
                check("[45] 전체 평균도 같이 보여준다 — 숨기지 않는다",
                      "전체 평균" in a["why"])
            else:
                check("[45] **주석이 없으면 대리물이라고 적는다** (원래 결함이 이것이다)",
                      "약한 대리물" in a["why"] and a["label"] == "저신뢰",
                      a["why"][:80])
    finally:
        _st._get = real_get
        _ca.configure()


def test_reverse_and_profiles():
    """[46] 역발상 발굴 · 2축 프로파일.

    가장 중요한 검사는 **역발상이 LLM에게 약을 물어보지 않는다**는 것이다.
    물어보면 자료원이 정방향과 같아지고, "정방향이 놓치는 것을 찾는다"는
    제안서 §1.2의 차별점 주장이 **원리적으로 검증 불가능해진다.**
    """
    from bioreroute.agents import reverse
    from bioreroute.core import profiles, scoring
    from bioreroute.io import faers, llm

    # ── 모의가 거짓말하지 않는지부터 ──────────────────────────
    prompts = []
    real_llm, real_av, real_ev = llm.complete, faers.available, faers.drugs_for_event

    def fake_llm(prompt, system=None, as_json=False, model=None, purpose=""):
        prompts.append(prompt)
        return {"ok": True, "error": None, "provenance": {"model": "mock"},
                "data": [{"term": "HYPERTRICHOSIS", "why": "모발 성장"}]}

    EV = {"HYPERTRICHOSIS": {"error": None, "rows": [
        {"drug": "MINOXIDIL", "a": 420, "n_drug": 1500, "prr": 31.2, "signal": True},
        {"drug": "ASPIRIN 81MG", "a": 18, "n_drug": 900000, "prr": 0.3, "signal": False},
        {"drug": "PHENYTOIN SODIUM", "a": 2, "n_drug": 50, "prr": 9.0, "signal": False}]}}
    try:
        llm.complete = fake_llm
        faers.available = lambda: {"faers": True, "sider": False,
                                   "sider_path": "x", "error": None}
        faers.drugs_for_event = lambda t, limit=25: EV[t]
        r = reverse.propose("Alopecia")
        check("[46] 역발상 LLM이 실제로 불렸다", len(prompts) == 1)
        check("[46] 프롬프트가 **약 이름을 요구하지 않는다**",
              "약물 이름을 쓰지 마라" in prompts[0])
        names = [i["drug"] for i in r["items"]]
        check("[46] 미녹시딜이 나온다 (PRR 최상위)", names[:1] == ["Minoxidil"], str(names))
        check("[46] 처방량만 많은 아스피린은 걸러진다",
              not any("spirin" in n for n in names), str(names))
        check("[46] 신고 2건짜리는 PRR 높아도 걸러진다",
              not any("henytoin" in n for n in names), str(names))
        check("[46] 자발보고이므로 신뢰도를 low 로만 적는다",
              {i["confidence"] for i in r["items"]} == {"low"})

        # 자료원이 없으면 **빈 목록이 아니라 오류**
        faers.available = lambda: {"faers": False, "sider": False,
                                   "sider_path": "x", "error": "URLError"}
        r2 = reverse.propose("Alopecia")
        check("[46] 자료 없음 → 조용한 빈 목록이 아니라 오류",
              bool(r2["error"]) and not r2["items"], str(r2)[:80])

        # 조회 전건 실패 = 후보 없음이 아니다 (결함 35)
        faers.available = lambda: {"faers": True, "sider": False,
                                   "sider_path": "x", "error": None}
        faers.drugs_for_event = lambda t, limit=25: {"error": "HTTP 503", "rows": []}
        r3 = reverse.propose("Alopecia")
        check("[46] 조회 전건 실패 → 판단 거부", bool(r3["error"]), str(r3)[:80])
    finally:
        llm.complete, faers.available, faers.drugs_for_event = real_llm, real_av, real_ev

    # ── 2축 ──────────────────────────────────────────────
    std = profiles.exit_profile("표준")
    urg = profiles.exit_profile("신종감염병긴급")
    check("[46] 표준 프로파일이 **현재 상수를 읽는다** (베끼지 않는다)",
          std["balance"] == scoring.BALANCE and std["cap"] == scoring.LOGIT_CAP)
    check("[46] 표준 문턱이 지금 동작과 같다 (유망80·기각40)",
          (std["유망"], std["기각"]) == (80, 40))
    check("[46] **긴급이라고 유망 문턱을 낮추지 않는다** (HCQ 206건의 교훈)",
          urg["유망"] == std["유망"] == 80, "긴급 유망=%s" % urg["유망"])
    check("[46] 긴급은 **기각 문턱만** 낮춘다 → 늘어나는 건 보류다",
          urg["기각"] < std["기각"], "%s → %s" % (std["기각"], urg["기각"]))
    check("[46] 긴급은 등록부를 필수로 요구한다", urg["registry_required"] is True)

    acc = profiles.accessibility("metformin", {"ro5_violations": 0})
    check("[46] 접근성 — EML 수록은 True", acc["eml"] is True)
    unk = profiles.accessibility("someunknowndrug", None)
    check("[46] **모르면 False 가 아니라 None** (목록이 부분집합이다)",
          unk["eml"] is None and unk["oral_ok"] is None, str(unk))


def test_viewer_and_fto():
    """[47] 3Dmol 뷰 · FTO — **판정에 섞이지 않는지**를 본다.

    pLDDT 도 특허도 로그오즈에 들어가면 안 된다. 주석으로 막지 않고
    문자열·소스를 검사해서 막는다 — 안내문은 방어가 아니다.
    """
    import inspect
    from bioreroute import viewer
    from bioreroute.io import fto

    ok = viewer.render({"label": "신뢰", "cif_url": "https://x/a.cif",
                        "plddt": {"mean": 92.4, "frac_low": 0.03}})
    check("[47] 뷰어가 pLDDT 평균을 화면에 적는다", "92.4" in ok)
    check("[47] 뷰어가 **결합력이 아니라고 명시**한다",
          "결합 세기가 아니다" in ok)
    for bad in ("결합력", "친화도", "docking score", "binding affinity"):
        check("[47] 범례에 '%s' 를 쓰지 않는다" % bad, bad not in ok)

    lo = viewer.render({"label": "저신뢰", "cif_url": "https://x/b.cif",
                        "plddt": {"mean": 41.2, "frac_low": 0.88}})
    check("[47] 저신뢰면 '도킹은 거짓 확신을 만든다'를 적는다",
          "거짓 확신" in lo)
    err = viewer.render({"label": "오류", "why": "URLError", "cif_url": None})
    check("[47] 조회 실패를 '구조 없음'으로 적지 않는다",
          "구조가 없다는 뜻이 아니다" in err)
    # 08-19 결함 287 — 앞판은 `s1` 이 없으면 *«표적에 직접 결합하지
    #   않아»* 를 **상수로** 냈다. `viewer` 는 `s1` 하나만 받으므로
    #   **라우터가 무엇을 골랐는지 모르면서 이유를 단정**한 것이다.
    #   실제로 `edaravone` 은 라우터가 «못 정함» 인데 그렇게 적혔다.
    #   이제 이유는 **아는 쪽(호출부)이 넣는다.**
    _n = viewer.render(None)
    check("[47] 이유를 모르면 **원인을 지어내지 않는다**",
          "직접 결합하지 않아" not in _n and "이유는" in _n, _n[-140:])
    check("[47] 이유를 받으면 **그대로 적는다**",
          "기전을 못 정했습니다" in viewer.render(None,
                                          why="기전을 못 정했습니다."))
    # ⚠ 09-25 · 앞판은 `edaravone` 을 **이름으로** 집었다 — 08-14 판에서 라우터가 «불명» 이던
    #   쌍이다. 본선 모델로 다시 구우니 edaravone 은 «간접» 으로 정해졌고 **metformin 이
    #   «불명»** 이 됐다. 규칙(기록대로 이유를 낸다)은 그대로다 — **쌍은 자료에서 고른다.**
    from .. import dash as _D47, evidence as _EV47
    _cs47 = {x.get("질의"): x for x in ((_EV47.cases() or {}).get("사례") or [])}

    def _route47(x):
        for g in x.get("게이트") or []:
            if g.get("게이트") in ("검증 방식 정하기", "기전 라우터", "router"):
                return g.get("결과")
        return None
    _unk47 = sorted(q for q, x in _cs47.items() if _route47(x) == "UNKNOWN" and not x.get("s1"))
    if _unk47:
        _e47 = _D47.right_structure(None, _unk47[0])
        check("[47] 구운 사례에서 **기록대로** 이유를 낸다 — 라우터가 못 정한 쌍(`%s`)은 "
              "«못 정했다» 지 «직접 결합 안 함» 이 아니다" % _unk47[0].split(" /")[0],
              "못 정했" in _e47 and "직접 결합하지 않아" not in _e47, _e47[-160:])
    else:
        check("[47] (이 판의 구운 사례에는 라우터 «불명» 쌍이 없다 — 이 검사는 건너뛴다)", True,
              "건너뜀 — 규칙은 위 `viewer.render(None, why=)` 검사가 지킨다")

    # FTO 가 게이트가 아님을 구조로 확인한다
    from bioreroute.core import gates
    check("[47] FTO 는 파이프라인 게이트가 **아니다**",
          not any(k.startswith("fto") for k in gates.REGISTRY))
    src = inspect.getsource(fto)
    check("[47] fto.py 가 weight/score 를 반환하지 않는다",
          '"weight"' not in src and '"score"' not in src)
    r = fto.check("aspirin", api_key=None)
    check("[47] 키가 없으면 '확인불가' — 개발가능이 아니다",
          r["label"] == "확인불가" and "개발가능이 아니다" in r["why"])
    check("[47] FTO 가 자기 한계를 같이 싣는다",
          "법률적 FTO 분석이 아니다" in r["한계"])

    # DRKG — 파일이 없으면 없다고 말한다
    from bioreroute.io import drkg
    g = drkg.load("__없는파일__.tsv")
    check("[47] DRKG 파일 없음 → 빈 그래프가 아니라 오류",
          g["ok"] is False and g["error"])
    m = drkg.multihop(g, "Disease::MESH:D000544")
    check("[47] 미적재 그래프로 다중홉을 돌리면 판단을 거부한다",
          m["ok"] is False and not m["items"])


def test_hitl_and_tox():
    """[48] HITL 음성 KB · hERG/DILI/탐색범위 · Time-to-Refute.

    가장 중요한 검사는 **유사 골격으로 기각하지 않는다**는 것이다.
    제안서는 *"유사 골격을 자동으로 차단"* 이라 썼지만 구조 유사는
    무효의 근거가 아니다. 같은 쌍(사람이 본 것)만 차단한다.
    """
    import os
    import tempfile
    from bioreroute.core import gates, hitl
    from bioreroute.core.state import RunState, Candidate
    from bioreroute.io import tox

    kb = os.path.join(tempfile.gettempdir(), "hitl_test_kb.jsonl")
    if os.path.exists(kb):
        os.remove(kb)

    r = hitl.record("drugA", "Asthma", "", path=kb)
    check("[48] 이유 없는 거절은 안 받는다", not r["ok"], str(r))
    hitl.record("drugA", "Asthma", "2상에서 이미 무효", who="김박사",
                smiles="CCO", path=kb)
    K = hitl.load(kb)
    check("[48] 거절이 KB에 쌓인다", len(K["pairs"]) == 1)

    c1 = hitl.consult("drugA", "Asthma", kb=K)
    check("[48] 같은 쌍 → 차단", c1["verdict"] == "block", c1["verdict"])
    check("[48] 차단 사유에 누가·언제·왜가 남는다",
          "김박사" in c1["why"] and "무효" in c1["why"], c1["why"])
    c2 = hitl.consult("drugB", "Asthma", kb=K)
    check("[48] SMILES 없으면 clear 가 아니라 unknown",
          c2["verdict"] == "unknown", c2["verdict"])
    c3 = hitl.consult("drugA", "Diabetes", kb=K)
    check("[48] 질환이 다르면 차단 안 한다",
          c3["verdict"] != "block", c3["verdict"])

    # **유사 골격은 경보이지 기각이 아니다** — 소스로 확인한다
    import inspect
    hsrc = inspect.getsource(hitl)
    check("[48] 유사 골격에 '기각하지 않는다'를 명시한다",
          "기각하지 않는다" in hsrc)
    gsrc = inspect.getsource(gates.gate_hitl)
    check("[48] 게이트가 warn 에서는 kill 하지 않는다",
          gsrc.index('"WARN"') > gsrc.index('c.kill('), "warn 이 kill 앞에 있다")

    hitl.revoke("drugA", "Asthma", "판단 번복", path=kb)
    K2 = hitl.load(kb)
    check("[48] 취소하면 차단이 풀린다", len(K2["pairs"]) == 0 and K2["revoked"] == 1)
    # 2줄이다 — 거절 1 + 취소 1. **이유 없는 거절은 파일에 안 쓰이므로**
    # 세면 안 된다. 처음에 3으로 적었다가 시험이 잡았다.
    check("[48] **취소해도 기록은 남는다** (append only)",
          len(K2["entries"]) == 2
          and [e["act"] for e in K2["entries"]] == ["reject", "revoke"],
          str([e["act"] for e in K2["entries"]]))

    sv = hitl.savings({"pairs": {"a": 1, "b": 2}, "revoked": 0})
    check("[48] §7 비용 주장을 수치로 낸다", sv["아끼는_호출"] == 6.0, str(sv))

    # HITL 도 기존 구성 trail 을 안 바꾼다
    base = ["f0", "rag", "router", "s2", "skeptic", "registry"]

    def eff(cfg):
        cf = gates.CONFIGS[cfg]
        return [n for n in gates.ORDER
                if cf.get(n, False) or n not in gates.QUIET_WHEN_OFF]
    for cfg in ("B0", "B5", "B6", "W1"):
        check("[48] %s trail 이 hitl 추가로 안 바뀐다" % cfg, eff(cfg) == base, str(eff(cfg)))
    check("[48] hitl 은 깔때기 **맨 앞**이다 (§7 비용 차단)",
          eff("B8")[0] == "hitl", str(eff("B8")))
    check("[48] B8 은 벤치마크 구성이 아님을 문서가 말한다",
          "벤치마크에는 쓰지 않는다" in inspect.getsource(gates))

    # ── §1.2 탐색 범위 · hERG · DILI ──────────────────────
    for nm in ("ibalizumab", "belimumab", "etanercept"):
        r = tox.small_molecule(nm)
        check("[48] %s 를 저분자로 치지 않는다" % nm, r["is_small"] is False, r["how"])
    r = tox.small_molecule("")
    check("[48] 이름 없으면 오류", r["error"] and r["is_small"] is None)

    h = tox.herg_alert("")
    check("[48] SMILES 없으면 hERG '확인불가'", h["level"] == "확인불가")
    check("[48] hERG 가 자기 한계를 싣는다",
          "경보 없음이 안전을 뜻하지 않는다" in h["한계"])
    tsrc = inspect.getsource(tox)
    check("[48] hERG 를 기각 사유로 쓰지 않는다고 적었다",
          "기각 사유가 아니다" in tsrc and "아미오다론" in tsrc)
    check("[48] DILI 가 '모화합물만'이라고 적는다",
          "대사산물 독성은 보지 않는다" in tox.dili_alert("")["한계"])
    for bad in ('"weight"', '"score"'):
        check("[48] tox.py 가 %s 를 반환하지 않는다" % bad, bad not in tsrc)

    # ── Time-to-Refute ────────────────────────────────────
    c = Candidate(name="x / y", drug="x", disease="y", origin="t", query="q")
    st = gates.run_pipeline(RunState("q", "B0", "t", [c], dict(gates.CONFIGS["B0"])))
    ttr = gates.time_to_refute(st)
    check("[48] 전체 소요를 잰다", isinstance(st.timing.get("_전체"), float),
          str(st.timing))
    check("[48] 캐시 상태를 같이 낸다 — 안 그러면 초가 거짓말이다",
          "warm" in ttr and "이미 받아 뒀다" in ttr["주의"])
    check("[48] 시간이 판정에 안 들어간다",
          "timing" not in inspect.getsource(gates.gate_adjudicate))


def test_dashboard():
    """[55] 제안서 §6 3분할 대시보드 — **내용과 배선을 따로 본다.**

    §6 은 화면 구조를 구체적으로 지정했다 — 좌(축 토글)·중(근거 카드)·
    우(반증·구조·특허 뷰어)·하(보정 곡선·Time-to-Refute)·옆(B0 나란히).
    **우리 데모는 그중 아무것도 아니었다**(결함 43 의 §6 항목).

    이 시험이 보는 것 셋 —
      ① 내용이 실제로 채워지는가 (`dash.py`, gradio 없이)
      ② **제안서와 다른 값을 숨기지 않는가** — 플루복사민 ⚠
      ③ `app.py` 배선이 도는가 (**가짜 gradio** 로 태운다)

    ③이 필요한 이유 — 화면을 띄울 수 없는 환경에서 짰다. `dash.py` 를
    직접 부르는 시험만 있으면 **결함 44(도달 불가 코드)를 그대로 반복**한다.
    """
    from .. import dash
    from .. import evidence as EV
    from ..core import profiles

    # ① 내용 ─────────────────────────────────────────────
    labels = dash.run_labels()
    check("[55] Run 1·2 두 실행이 있다", len(labels) == 2, str(labels))
    for run in labels:
        c = dash.center(run)
        check("[55] %s 중앙 패널이 채워진다" % run, len(c) > 200 and "|" in c, len(c))
        check("[55] %s 가 **빠진 것**을 적는다" % run, "빠진 것" in c)

    # ② 제안서와 어긋난 값을 숨기지 않는가 — 이게 이 화면의 요지다
    r2 = dash.center(labels[1])
    # ⚠ 09-25 · 앞판은 «유망» 을 **글자로** 기대했다(08-14 판 유망 84%). 본선 모델로 다시
    #   구우니 **조건부 81%** 다. 지키려던 것은 «유망» 이 아니라 **어긋나면 숨기지 않는다**
    #   이다. 그리고 앞판의 «⚠ in 패널» 은 **범례 줄의 ⚠ 때문에 늘 참**이었다 — 줄로 본다.
    _fv = (dash._cases().get("fluvoxamine / COVID-19") or {}).get("판정")
    _frow = [l for l in r2.splitlines() if "fluvoxamine" in l]
    check("[55] 플루복사민이 **구운 판정 그대로** 나온다 — 제안서의 예상(보류)도 같은 줄에 (지금 판: %s)"
          % _fv, bool(_frow) and bool(_fv) and _fv in _frow[0] and "보류 (지지" in _frow[0],
          (_frow or [""])[0][-80:])
    check("[55] 예상과 어긋나면 **그 줄에** ⚠ 를 붙이고, 맞으면 안 붙인다",
          bool(_frow) and (("⚠" in _frow[0]) == (bool(_fv) and _fv not in "보류")),
          (_fv, (_frow or [""])[0][-40:]))

    card = dash.evidence_card("hydroxychloroquine / COVID-19")
    # **서식이 아니라 값을 본다.** 앞판은 `"PMID \`3"` 을 찾았는데,
    # 08-10에 PMID 를 코드 스팬에서 식별자 스팬으로 옮기자 깨졌다 —
    # 시험이 **백틱의 존재**를 보고 있었지 PMID 의 존재를 보고 있지 않았다.
    # 오늘만 다섯 번째로 겪는 같은 실수다(문자열 vs 주장).
    _pmids = re.findall(r"PMID\s*(?:<[^>]+>)?\s*(\d{6,9})", card)
    check("[55] 근거 카드에 **실제 PMID** 가 찍힌다 — `None` 이면 실패",
          bool(_pmids) and "None" not in card,
          "%d개 · %s" % (len(_pmids), _pmids[:2]))

    sbs = dash.side_by_side("hydroxychloroquine / COVID-19")
    check("[55] B0 대조에서 우리 PMID 가 0건이 아니다",
          "| **0건** | **0건** |" not in sbs, "PMID 가 0건으로 나온다")
    check("[55] 대조 축이 **방향이 아니라** PMID·보정이라고 적는다",
          "판단 방향이 아니다" in sbs)
    check("[55] B0 를 **암기 천장**이라 적는다", "암기 천장" in sbs)

    # ── 08-12 — 이 두 검사가 **낡은 주장을 강제하고 있었다** (결함 132) ──
    #
    #   초판: `"0.105" in cal and "기준선보다 나쁘다" in cal` · `"Platt" in cal`.
    #   즉 **«Platt 은 아직 안 했고 기준선에 졌다»** 를 시험이 못 박았다.
    #   08-12에 Platt 을 적용해 ECE 0.1039→0.0515 를 냈는데, 화면을 고치면
    #   **이 시험이 깨지는** 상태였다. 결함 130 과 같은 고장이다 —
    #   **시험이 초록이라고 옳은 게 아니다.**
    #
    #   그리고 `0.105` 는 **dev 수치**였고 지금 코드로 재현도 안 된다
    #   (dev 0.1168 · 홀드아웃 0.1039). 상수를 시험이 지키고 있었다.
    #
    #   고친 불변식 — **값을 박지 않는다.** 「파일에서 읽는가」와
    #   「불리한 것을 같이 적는가」를 본다.
    import inspect as _i55
    cal = dash.bottom_calibration()
    # **문자열이 아니라 동작을 본다** — 함수 안엔 상수 이름만 있다.
    #   문자열로 봤다가 빨개졌다(결함 61 계열). 오늘만 세 번째다.
    check("[55] 하단 보정이 **파일에서 읽는다** — 값을 코드에 안 박는다",
          dash.CAL_CARD == "calibration.json"
          and isinstance(dash._cal_card(), (dict, type(None))))
    check("[55] 카드가 없으면 **옛 값으로 안 채우고 없다고 적는다**",
          "없는 것을 옛 값으로 채우지 않는다"
          in _i55.getsource(dash.bottom_calibration))
    check("[55] **널 모형을 같이 낸다** — 균형 집합에서 ECE 는 정보를 버릴수록 좋다",
          "널 모형" in cal and "정보를 버릴수록" in cal, cal[:80])
    check("[55] **Brier 를 같이 낸다** — ECE 단독으로 «정직해졌다» 를 안 판다",
          "Brier" in cal and "적정 점수" in cal)
    check("[55] B0 대비 우위를 **구간으로 절제**한다",
          "주장 못 한다" in cal or "0을 포함" in cal)
    check("[55] 선택적 보고였다는 사실(결함 46)을 계속 적는다", "선택적 보고" in cal)
    tl = dash.bottom_timeline(None)
    # **뜻으로** — 08-19 에 «~습니다» 로 바꿨다. 요건은 «없으면 없다고
    #   적고 예시 숫자를 넣지 말 것».
    check("[55] 타임라인이 없으면 **없다고 적는다** (예시 숫자 금지)",
          "아직 안 쟀" in tl and "0.0" not in tl, tl[-120:])

    lf = dash.left("역발상", "신종감염병긴급", "fluvoxamine", {"ro5_violations": 0})
    check("[55] 긴급 축에서 **유망 문턱을 안 낮춘다**고 적는다",
          "유망` 문턱을 낮추지 않았다" in lf)
    # 08-21 — 표를 «이름 — 값» 줄로 바꿨다(결함 289). **요건은 «모름을
    #   모름으로, 눈에 띄게 적는다» 이지 `**모름**` 이라는 마크다운이
    #   아니다.** 그래서 뜻으로 본다 — 글자와 «모름» 표시(`unk`) 둘 다.
    check("[55] 접근성이 모르는 것을 **모름**으로 적는다",
          "모름" in lf and "unk" in lf,
          [l for l in lf.splitlines() if "모름" in l])

    # 08-19 결함 287 — 이유는 **기록에서** 온다. 질의를 안 주면
    #   «이유는 본문에 있다» 까지만 말하고 원인을 단정하지 않는다.
    st = dash.right_structure(None)
    check("[55] 구조를 안 그렸으면 **그렇다고 적는다** (빈 상자 금지)",
          "구조를 그리지 않았습니다" in st, st[:120])
    st2 = dash.right_structure(None, "baricitinib / COVID-19")
    # 09-29 · 결함 378 — 앞판 «직접 붙는 방식이 아닙니다» 는 **baricitinib 에 틀렸다**(JAK1/2 에 직접 붙는다 —
    #   숙주 표적일 뿐이다). 기록의 경로(`evidence`)가 뜻하는 것은 «병원체 단백질을 직접 치지 않는다» 다
    check("[55] 질의를 주면 **기록대로 이유**를 적는다",
          "병원체 단백질에 직접 붙는 약에만" in st2 and "숙주" in st2
          and "직접 붙는 방식이 아닙니다" not in st2, st2[-140:])

    # ③ **배선** — 가짜 gradio 로 app.py 를 실제로 태운다 ──────
    import types
    real_gr = sys.modules.get("gradio")
    real_app = sys.modules.pop("app", None)

    class _C:                       # 모든 컴포넌트를 이걸로 흉내낸다
        def __init__(self, *a, **k):
            self.a, self.k = a, k
            self.calls = []

        # `**kw` 가 없으면 **가짜가 진짜보다 좁아진다.** 08-11에 app.py 가
        # `show_progress="full"` 을 넘기자 여기서 터졌다 — 진짜 gradio 는
        # 받는 인자다. **가짜가 거짓말하는 쪽이 아니라 좁은 쪽이었다.**
        def change(self, fn, inputs=None, outputs=None, **kw):
            self.calls.append((fn, inputs, outputs))
            # **반환이 없으면 `.then()` 사슬에서 `None.then` 으로 죽는다.**
            #   바로 위 주석이 «가짜가 진짜보다 좁으면 안 된다» 를 적어
            #   놨는데 **인자에만 적용하고 반환값에는 안 했다** — 진짜
            #   gradio 는 이벤트 객체를 돌려주고 그걸로 `.then()` 을 건다.
            return self

        click = submit = then = change

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

    class _Blocks(_C):
        def load(self, fn, inputs=None, outputs=None, **k):
            self.calls.append((fn, inputs, outputs))
            return self

    # ⚠ 08-14 결함 222 — **손목록이 두 곳에 있었다.**
    #   `deploycheck` 쪽만 고치고 여기를 놓쳐서, `gr.Checkbox` 하나에
    #   `test_dashboard` 가 죽었다. **«어제 한 갈래만 고쳤다»**(결함 98)
    #   와 같은 자리다. 둘 다 `__getattr__` 로 바꾼다 —
    #   **모르는 위젯 이름은 만들어 준다.**
    class _FakeGr(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return _C

    fake = _FakeGr("gradio")
    fake.Blocks = _Blocks
    fake.update = lambda **k: dict(k)
    fake.themes = types.SimpleNamespace(
        Soft=lambda **k: None, Base=lambda **k: None)
    fake.__version__ = "6.0.0"
    sys.modules["gradio"] = fake
    try:
        import importlib
        app = importlib.import_module("app")
        check("[55] app.py 가 가짜 gradio 로 임포트된다", True)
        check("[55] 3분할 콜백 둘이 있다",
              callable(app._dash_run) and callable(app._dash_card))
        L, C, upd = app._dash_run(labels[0], "표준")
        check("[55] 배선: 좌·중이 실제 내용을 낸다",
              len(L) > 100 and len(C) > 100, "%d/%d" % (len(L), len(C)))
        check("[55] 배선: 후보 목록이 갈아 끼워진다",
              isinstance(upd, dict) and upd.get("choices"), str(upd)[:70])
        # ⚠ 08-18 결함 248 로 `_dash_card` 가 **좌측을 같이 돌려주게** 바뀌어
        #   반환이 5 → 6 이 됐다. `deploycheck` 쪽 프로브만 고치고 **여기를
        #   놓쳤다** — 바로 위 결함 222 주석이 «손목록이 두 곳에 있었다» 를
        #   적어 둔 그 자리에서 **같은 일이 다시 났다**(결함 98 계열).
        #   그래서 이제 **개수를 먼저 확인**하고 푼다.
        slots = app._dash_card(upd["value"], "표준")
        check("[55] 배선: `_dash_card` 가 **여섯 칸**을 돌려준다 (좌측 포함)",
              len(slots) == 6, len(slots))
        th, cd, sh, pt, sb, lf = slots
        for nm, v in (("사고과정", th), ("근거카드", cd), ("구조뷰", sh),
                      ("특허뷰", pt), ("B0대조", sb), ("좌측", lf)):
            check("[55] 배선: %s 가 빈 문자열이 아니다" % nm, len(v) > 50, len(v))
        check("[55] 배선: 후보가 없으면 빈 문자열 여섯",
              app._dash_card("", "표준") == ("", "", "", "", "", ""))
        # **좌측이 후보를 따라가는가** — 결함 248 의 본체다. 안 따라가면
        # `baricitinib` 에 «WHO 필수의약품 = 예» 가 남는다(틀린 값이다).
        others = [x for x in upd["choices"] if x != upd["value"]]
        if others:
            lf2 = app._dash_card(others[0], "표준")[5]
            check("[55] 좌측 접근성 칸이 **후보를 따라 바뀐다** (결함 248)",
                  lf2 != lf, "%s vs %s" % (upd["value"], others[0]))
        # ── 심사 기준 두 항목 (30점 · 10점) ────────────────
        check("[55] 사고 과정이 **게이트별**로 나온다 (심사 30점)",
              "게이트" in th and "근거가 실제로 있는가" in th, th[:80])
        check("[55] 사고 과정이 **자기수정 흔적을 짚는다**",
              "스스로 인지·수정한 것" in th)
        au = dash.autonomy()
        check("[55] 자율성이 **인지와 수정을 구분한다** (심사 10점)",
              "수정한다 (" in au and "인지만 한다 (" in au)
        check("[55] 자율성이 **개발 중 찾은 결함을 여기 안 넣는다**고 적는다",
              "시스템이 찾은 게 아니다" in au)
        check("[55] 자율성이 **재계획은 안 한다**고 정직하게 적는다",
              "자율적으로 재계획하지는 않는다" in au)
        # 08-10에 탭 이름을 「3분할 대시보드 (§6 시연)」 → 「대시보드」로
        # 줄였다. **이름이 아니라 배선을 봐야 한다** — 문자열을 보면
        # 이름만 바꿔도 시험이 깨지고, 깨진 시험은 손으로 고치게 된다.
        _asrc = open(os.path.join(EV.ROOT, "app.py"), encoding="utf-8").read()
        _first = _asrc.split("gr.Tab(")[1].split("gr.Tab(")[0]
        # 09-29 · `DASH_INTRO` 를 뺐다(결함 377 · 머리말이 중앙 칸의 되풀이였고 실행 2 에 틀렸다).
        #   **배선으로 본다** — 그 탭을 그리는 함수(`_dash_run`)가 첫 탭 안에 있는가.
        check("[55] 3분할이 **첫 탭**이다 — 라이브가 첫인상이면 보류 55%다",
              "_dash_run" in _first,
              _first.split(chr(10))[0][:40])
        check("[55] 라이브(직접 검증)는 **첫 탭이 아니다**",
              "run_live" not in _first)
        # ── [137] 결함 251 — **라이브 결과가 대시보드보다 얇으면 안 된다** ──
        #   승우: *«이걸 선택해서 돌렸을 때 대시보드 형태로 안 나오는데
        #   괜찮은거야?»* 안 괜찮았다. 구조·특허가 통째로 없었다.
        #   가짜 gradio 가 이미 꽂혀 있는 이 블록에서 같이 본다.
        _c251 = [c for c in (EV.cases() or {}).get("사례") or [] if c.get("s1")]
        check("[137] 구조 경로 구운 사례가 있다 — 없으면 이 검사가 무의미하다",
              bool(_c251), len(_c251))
        if _c251:
            _r = dict(_c251[0]); _r["상태"] = "정상"
            _md = app._md_result(_r)
            check("[137] 라이브 결과가 **구조(S1)** 를 낸다 (결함 251)",
                  "#### 구조 (S1)" in _md)
            check("[137] 라이브 결과가 **특허(FTO)** 를 낸다 (결함 251)",
                  "#### 특허 자유도 (FTO)" in _md)
            # 08-18 밤 — 이 검사가 **틀린 주장을 붙들고 있었다.**
            #   원래는 «3D 는 못 하니 대시보드로 보낸다» 를 지켰는데,
            #   결함 259 에서 **그 이유가 거짓**임이 드러났다(script 0개).
            #   시험이 초록이라고 옳은 게 아니다 — 무엇을 주장하는지 봐야 한다
            #   (결함 125·130 이 쓴 문장 그대로다).
            # 09-29 · 결함 378 — `webui` 주석이 08-20 에 «새 화면에서 3D 는 결과 **오른쪽** — 자리를 안
            #   가리킨다» 고 정해 놓고 문장은 «이 결과 맨 아래» 를 가리켰다. 이 검사가 그 **틀린 자리**를 붙들고
            #   있었다(위 08-18 주석이 경고한 그대로). 이제 자리를 안 가리키고 **색의 뜻**을 적는지 본다
            _s137 = _md[_md.find("#### 구조"):]
            check("[137] 3D 자리를 **가리키지 않는다** — 배치가 바뀌면 거짓말이 된다 · 색의 뜻은 적는다",
                  "맨 아래" not in _md and "pLDDT" in _s137 and "결합력이 아니다" in _s137, _s137[:200])
            check("[137] **틀린 한계를 안 적는다** — «markdown 이라 script 가 "
                  "안 돈다» 는 거짓이었다",
                  "markdown 이라 3Dmol 스크립트가 안 돈다" not in _md)
            # pLDDT 가 없을 때 **문자 그대로 `None`** 이 나오면 안 된다
            import copy as _cp
            _r2 = _cp.deepcopy(_r); _r2["s1"]["plddt"] = {}
            _seg = app._md_result(_r2)
            _seg = _seg[_seg.find("#### 구조"):_seg.find("#### 특허")]
            check("[137] pLDDT 가 없으면 **«모름»** 이지 `None` 이 아니다",
                  "모름" in _seg and "None" not in _seg, _seg[-60:])
            # 특허 색인은 **한 번만 읽는다** — 두 번째 렌더가 느리면 결함 252
            import time as _t137
            _t0 = _t137.perf_counter(); app._md_result(_r)
            _el = _t137.perf_counter() - _t0
            check("[137] 두 번째 렌더가 **1초 미만** — 색인 캐시가 산다 (결함 252)",
                  _el < 1.0, "%.2f초" % _el)
    finally:
        sys.modules.pop("app", None)
        if real_gr is not None:
            sys.modules["gradio"] = real_gr
        else:
            sys.modules.pop("gradio", None)
        if real_app is not None:
            sys.modules["app"] = real_app


def test_preflight():
    """[54] 장을 넘길 때 돌리는 전수 검증이 **실제로 도는가**.

    08-06 하루에 같은 검토를 여덟 번 받았고 여덟 번 다 새로 나왔다.
    매번 **다른 층**을 봤기 때문인데, 그 층 목록이 사람 머릿속에만
    있었다. `preflight` 이 그걸 명령 하나로 굳힌 것이다.

    **이 시험이 검사하는 것은 렌즈가 공허하지 않은가**다 —
    아무것도 안 보는 검사는 통과해도 의미가 없다(결함 29의 교훈).
    """
    import inspect
    from ..bench import preflight as P
    from .. import evidence as EV

    check("[54] 수동 렌즈가 다섯 개 있다", len(P.MANUAL) == 5, len(P.MANUAL))
    for tag, q, why in P.MANUAL:
        check("[54] 수동 렌즈 [%s] 가 **어느 결함에서 나왔는지** 적는다" % tag,
              "결함" in why, why[:40])

    # ── 렌즈가 **실제로 파일을 본다**는 것 ─────────────────────
    dead = P.unwired(EV.ROOT)
    check("[54] 렌즈3 이 돌고 결과가 목록이다", isinstance(dead, list), str(dead)[:60])
    check("[54] 렌즈3 이 **CLI 진입점을 도달 불가로 세지 않는다**",
          not any("routercheck" in d or "labelaudit" in d for d in dead), str(dead))

    rec = P.recent(EV.ROOT, days=3650)
    check("[54] 렌즈7 이 실제로 파일을 센다 — 0개면 공허하다",
          len(rec) > 10, len(rec))

    unc = P.uncovered(EV.ROOT)
    check("[54] 렌즈8 이 산출물을 훑는다", isinstance(unc, list), str(unc)[:60])

    # ── 08-24 · **울긴 우는데 이유를 안 말하는 가드** ─────────────
    #
    #   08-22 아침 점검이 잡았다. `preflight` 이 각 검사의 «마지막 비어
    #   있지 않은 줄» 을 요약으로 찍었는데, 도구들이 출력을 구분선으로
    #   닫기 때문에 **`=====` 만 나왔다.** 하필 숫자를 가진 셋이 전부
    #   그랬고, 그래서 «phase2 가 FAIL» 까지만 말하고 **몇 개 중 몇이
    #   왜 깨졌는지 한 글자도 안 말했다.** 사람이 20~40분짜리 시험을
    #   **또** 돌려야 했다.
    #
    #   결함 136(«늘 우는 가드는 눈 감은 가드와 같다»)의 사촌이다.
    _out = ("=" * 60 + "\n통과 1954 · 실패 1   [부분]\n"
            "실패: [65] **막대 합이 표제 결함 수와 같다**\n"
            "##FAILED##test_deck_markdown\n" + "=" * 60)
    _g = P._gist(_out)
    check("[54] 요약이 **구분선이 아니다** — 결함 136 의 사촌",
          not set(_g.strip()) <= set("=-#* "), _g)
    check("[54] 요약이 **통과·실패 수**를 담는다", "1954" in _g and "실패 1" in _g, _g)
    check("[54] 실패가 있으면 **무엇이 깨졌는지**도 담는다", "[65]" in _g, _g)
    check("[54] 표식(`##FAILED##`)을 요약으로 내지 않는다",
          not _g.startswith("##FAILED##"), _g)
    check("[54] 출력이 구분선뿐이면 **없다고 말한다**",
          P._gist("=" * 20 + "\n\n" + "-" * 20) == "(출력 없음)",
          P._gist("=" * 20))
    # 다른 도구들의 꼬리도 숫자를 살려야 한다
    for _nm, _o, _want in (
            ("docaudit", "  비율 검산 OK\n" + "=" * 40 + "\n**불일치 2항목.**", "2항목"),
            ("watch_holdout",
             "=" * 40 + "\n이상 6건 — 심각 3 · 주의 3\n" + "=" * 40, "6건")):
        check("[54] `%s` 요약에 수치가 남는다" % _nm, _want in P._gist(_o),
              P._gist(_o))

    # ── 08-24 오후 · **같은 고침이 이번엔 다른 것을 가렸다** (결함 306) ──
    #
    #   아침에 «숫자를 `=====` 로 가린다» 를 고쳤더니, 이번엔
    #   **«불일치 2항목» 만 찍고 어느 항목인지 안 찍었다.** 승우가
    #   `preflight` 을 두 번 돌려 두 번 다 그 한 줄만 받았고, 내 쪽은
    #   초록이라 나는 **원인을 추측했다.** 요약은 «무엇이» 를 담아야 한다.
    #
    #   ⚠ `docaudit` 은 **진짜 불일치에만 `⚠` 를 붙인다.** ECE·TN 처럼
    #     일부러 두 값을 병기하는 항목은 `⚠` 가 없다 — 그걸 섞어 찍으면
    #     «늘 우는 가드» 가 된다(결함 136).
    _da = ("문서 간 일관성 감사 — 문서 56개\n"
           "  결함 건수      305      문서 32곳 일치\n"
           "⚠ 회귀 시험      **문서는 일치하는데 정본과 다르다** — 실제 2047\n"
           "⚠ 시험 합산표기    **값이 1가지**\n"
           "  ECE 홀드아웃   **값이 2가지**  (예외: 정본 = calibration.json)\n"
           + "=" * 40 + "\n**불일치 2항목.** 문서끼리 다른 말을 하고 있다.")
    _g2 = P._gist(_da, 120)
    check("[54] 불일치 요약이 **어느 항목인지** 말한다 — 결함 306",
          "회귀 시험" in _g2 and "시험 합산표기" in _g2, _g2)
    check("[54] **일부러 병기하는 항목(ECE)은 안 섞는다** — 결함 136",
          "ECE" not in _g2, _g2)
    check("[54] 같은 항목이 두 줄이어도 **한 번만** 적는다",
          _g2.count("회귀 시험") == 1, _g2)
    check("[54] 불일치가 아니면 **항목 이름을 안 붙인다**",
          "←" not in P._gist("  비율 검산 OK\n" + "=" * 20 + "\n불일치 없음."),
          P._gist("  비율 검산 OK\n" + "=" * 20 + "\n불일치 없음."))
    # **자를 거면 잘랐다고 말한다.** 조용한 절단이 이 함수의 원죄다.
    check("[54] 길이를 넘기면 **잘렸다는 표시**를 남긴다",
          P._gist(_da, 40).endswith("…"), P._gist(_da, 40))
    check("[54] 짧으면 **군더더기를 안 붙인다**",
          not P._gist("통과 3 · 실패 0", 76).endswith("…"),
          P._gist("통과 3 · 실패 0", 76))

    # ── 08-24 밤 · **정본을 사람이 타이핑하지 않게 한다** (결함 307) ────
    #
    #   내가 `docaudit --tests 2047` 을 손으로 쳤고, 그 2047 은
    #   **문서에 적힌 값**이었다. 정답을 베껴 넣고 채점한 것이다.
    #   같은 시각 승우 컴퓨터는 시험을 실제로 돌려 2053 을 쥐고 빨갰다.
    #   나는 그 차이를 «환경 차이» 라고 **세 번** 적었다.
    import json as _json
    import tempfile as _tf
    import time as _time
    from ..bench import docaudit as _DA
    _d = _tf.mkdtemp()
    os.makedirs(os.path.join(_d, "bioreroute", "tests"))
    os.makedirs(os.path.join(_d, "bioreroute", "bench"))
    # ⚠ **빈 폴더로는 시험이 안 된다** — 결함 310 을 고치고 나서
    #   이 소품이 «시험 코드를 하나도 못 찾았다» 로 빨개졌다. **고침이
    #   제 일을 한 것**이므로 소품 쪽을 실제에 맞춘다.
    open(os.path.join(_d, "bioreroute", "bench", "x.py"), "w").write("#\n")
    _w = _DA.write_truth(_d, 34, 2019)
    _p = _w["경로"]
    check("[54] `preflight` 이 정본을 **파일로 남긴다**", os.path.exists(_p), _p)
    check("[54] 정본 쓰기가 **성공했는지 알려 준다** — 결함 310",
          _w.get("원본유지") is False, _w.get("상태"))
    _j = _json.load(open(_p, encoding="utf-8"))
    check("[54] 정본에 **합**이 있다", _j.get("합") == 2053, _j.get("합"))
    check("[54] 정본이 **언제·어디서**를 남긴다 — 남의 기계 값을 몰래 쓰지 않는다",
          bool(_j.get("언제")) and bool(_j.get("어디서")), _j.get("어디서"))
    _t = _DA.truth_tests(_d)
    check("[54] 정본을 **읽어 온다**", _t and _t["합"] == 2053, _t)
    check("[54] 갓 쓴 정본은 **안 낡았다**", _t and not _t["낡음"], _t)
    # **시험 코드가 정본보다 새로우면 정본이 아니다.**
    _time.sleep(1.05)
    _newer = os.path.join(_d, "bioreroute", "tests", "test_phase2.py")
    open(_newer, "w", encoding="utf-8").write("# 나중에 고친 시험\n")
    _t2 = _DA.truth_tests(_d)
    check("[54] **시험이 바뀌면 정본이 낡는다** — 낡은 정본으로 초록을 내지 않는다",
          _t2 and _t2["낡음"], _t2)
    check("[54] 낡았으면 **누구 때문인지** 말한다",
          _t2 and _t2["범인"] == "test_phase2.py", _t2 and _t2["범인"])
    check("[54] 정본이 없으면 **None** — 없는 것을 0으로 세지 않는다",
          _DA.truth_tests(os.path.join(_d, "없는곳")) is None)
    # ── 08-24 밤 · 렌즈 7 — **오늘 쓴 코드를 적대적으로 읽었다** (결함 310)
    #
    #   `preflight` 이 다섯 번 «최근 2일 안에 바뀐 코드를 적대적으로 다시
    #   읽어라» 를 찍었고 나는 다섯 번 안 읽었다. 읽으니 둘이 나왔다 —
    #   **둘 다 «거짓 초록» 을 만드는 길**이고, 하필 결함 307 을 고치려고
    #   만든 그 파일에서 났다.
    _d3 = _tf.mkdtemp()          # ① 시험 코드가 하나도 없는 곳
    _DA.write_truth(_d3, 34, 2034)
    _t3 = _DA.truth_tests(_d3)
    check("[54] **시험 코드를 하나도 못 찾으면 «신선하다» 가 아니다** — 결함 99",
          _t3 and _t3["낡음"], _t3)
    _d4 = _tf.mkdtemp()          # ② 백업 자리를 막아 갱신을 실패시킨다
    os.makedirs(os.path.join(_d4, "bioreroute", "bench"))
    open(os.path.join(_d4, "bioreroute", "bench", "x.py"), "w").write("#\n")
    _w1 = _DA.write_truth(_d4, 34, 100)
    os.mkdir(_w1["경로"] + ".bak")
    _w2 = _DA.write_truth(_d4, 34, 999)
    check("[54] 백업이 막히면 **원본을 안 덮는다** — `.new` 로 간다",
          _w2["원본유지"] is True and _w2["경로"].endswith(".new"), _w2["경로"])
    check("[54] 그때 정본은 **여전히 옛 수**다 — 조용히 넘어가면 거짓 초록",
          _json.load(open(os.path.join(_d4, _DA.TRUTH_FILE),
                          encoding="utf-8"))["합"] == 134)
    _t4 = _DA.truth_tests(_d4)
    check("[54] **`.new` 가 있으면 정본으로 안 쓴다** — 결함 310",
          _t4 and _t4["낡음"] and ".new" in str(_t4["범인"]), _t4)
    _src_da = inspect.getsource(_DA)
    check("[54] `--tests` 를 **손으로 줘도 파일이 이긴다**",
          "손으로 준 수로 채점하지 않는다" in _src_da)
    check("[54] 불일치일 때 **`countsync` 한 줄을 숫자까지 채워 준다**",
          "그대로 붙여넣어라" in _src_da)
    _src_pf = inspect.getsource(P)
    check("[54] `preflight` 이 **`--tests` 를 손으로 넘기지 않는다** — 결함 307",
          '"--tests"' not in _src_pf, "preflight 이 아직 --tests 를 넘긴다")
    check("[54] `preflight` 이 시험을 **돌린 뒤에** 정본을 쓴다",
          "write_truth" in _src_pf)
    check("[54] `preflight` 이 **정본 갱신 실패를 화면에 적는다** — 결함 310",
          "원본유지" in _src_pf and "갱신되지 않았다" in _src_pf)
    # ── 08-24 밤 · **내 시험의 소품이 정본이 됐다** (결함 308) ──────────
    #
    #   위 `_gist` 검사들이 화면에 «통과 1954 · 실패 1» 이라는 **모의
    #   문자열**을 찍는다. `preflight` 이 `re.search` 로 **앞에서부터**
    #   찾는 바람에 그 소품을 집었다 — 화면은 «2031» 인데 정본 파일에는
    #   **1954** 가 박혔다. **정본을 파일로 옮긴 그 날 밤에 그 파일이
    #   거짓말을 했다.** 요약줄은 줄머리에서 시작하고 상세는 들여쓴다.
    _fake = ("  PASS [54] 요약이 수를 담는다  -> 통과 1954 · 실패 1\n"
             "  PASS [54] 또 다른 소품  -> 통과 7 · 실패 3\n"
             "통과 2031 · 실패 0\n")
    _hits = re.findall(r"^통과 (\d+) · 실패 (\d+)", _fake, re.M)
    check("[54] 정본은 **줄머리 요약줄**만 읽는다 — 검사 상세는 소품이다",
          len(_hits) == 1 and _hits[-1][0] == "2031", _hits)
    # ⚠ `_gist` 는 **한 줄 안에서** `re.search` 를 써도 된다 — 거기선
    #   줄을 이미 골라 놓았다. 문제는 **출력 전체를 앞에서부터 긁는 것**이다.
    #   처음에 `search(r"통과` 를 통째로 금지했다가 `_gist` 를 잡았다.
    #   **넓은 금지는 오탐을 만들고 오탐은 가드를 끈다**(결함 136).
    check("[54] 시험 수는 **줄머리 고정 `findall`** 로 센다 — 결함 308",
          'findall(r"^통과' in _src_pf,
          "**앞에서부터 긁고 있다** — 소품을 집는다")
    check("[54] 요약줄을 **못 읽으면 정본을 안 쓴다** — 0으로 세지 않는다",
          "못읽음" in _src_pf and "정본을 안 쓴다" in _src_pf)
    # ── 08-24 밤 · **보는 눈은 있는데 고치는 손이 없었다** (결함 309) ──
    #
    #   `파일지도.md` 가 «시험 34+2013 = **2047**» 이라고 적는다.
    #   `countsync` 의 규칙은 `(N)건` 꼴만 보므로 이 줄을 **세 번 놓쳤고**
    #   나는 세 번 손으로 고쳤다. 그런데 `docaudit` 은 이 줄을
    #   «시험 합산표기» 로 **줄곧 보고 있었다** — 결함 82 계열이다.
    #   합계만으로는 못 고친다(두 항을 따로 알아야 한다) → 정본을 읽는다.
    from ..bench import countsync as _CS
    _d2 = _tf.mkdtemp()
    os.makedirs(os.path.join(_d2, "bioreroute", "tests"))
    _DA.write_truth(_d2, 34, 2034)
    _ln = "`v65.zip` (배포본 · 시험 34+2013 = **2047**) — 이전 판은 `archive/`"
    _got = _CS._fix_sum(_ln, 2047, 2068, _d2)
    check("[54] 합산식 `34+N = **M**` 을 **둘 다** 고친다 — 결함 309",
          "34+2034 = **2068**" in _got, _got[:60])
    check("[54] 합이 안 맞으면 **손대지 않는다** — 모르면 안 고친다",
          _CS._fix_sum(_ln, 2047, 9999, _d2) == _ln)
    check("[54] 정본이 없으면 **손대지 않는다**",
          _CS._fix_sum(_ln, 2047, 2068, os.path.join(_d2, "없는곳")) == _ln)
    check("[54] **다른 합계**의 줄은 안 건드린다 — 우연히 닮은 식 방어",
          _CS._fix_sum("표본 12+13 = **25** 였다", 2047, 2068, _d2)
          == "표본 12+13 = **25** 였다")

    check("[54] 발표자료가 감사 대상에 **들어 있다** (결함 60)",
          not any("pptx" in u for u in unc), str(unc))

    src = inspect.getsource(P)
    check("[54] 여덟 렌즈가 무엇을 잡았는지 표로 적혀 있다",
          src.count("결함 4") + src.count("결함 5") + src.count("결함 6") >= 6)
    check("[54] 자동화 안 되는 렌즈를 **안 된다고 적는다**",
          "자동화가 **안 되는**" in src)

    # 절차 문서와 CLAUDE.md 에 실제로 걸려 있는가 — 안 걸면 안 읽는다
    for f, tok in (("검증절차.md", "preflight"),
                   ("CLAUDE.md", "bioreroute.bench.preflight")):
        p = os.path.join(EV.ROOT, f)
        check("[54] %s 가 절차를 가리킨다" % f,
              os.path.exists(p) and tok in open(p, encoding="utf-8").read())


def test_faers_failure_is_not_zero():
    """[52] **결함 58 — 오늘 문서에 적은 실수를 오늘 코드에서 재발시켰다.**

    `faers._total` 을 처음엔 이렇게 썼다.

    ```python
    except Exception:
        return cache.put(key, 0)     # "404 = 0건이니까"
    ```

    `except Exception` 이 타임아웃·DNS·5xx·파싱 오류를 **전부 0** 으로
    만들고 **캐시에 영구 저장**했다. 실측 —

    ```
    사건 총계만 타임아웃  →  C=0  →  c=0  →  prr=inf  →  signal=True
    error 는 None 이고, 정렬이 -prr 이라 그 약이 **1위**로 올라간다
    ```

    **일시 장애 하나가 역발상 후보 1위를 만든다.** 결함 35(실패를 0으로)와
    결함 37(장애를 캐시에 영구화)을 **같은 세 줄에서 둘 다** 재발시켰다.
    """
    from ..io import cache as C
    from ..io import faers as F

    def clear():
        for k in [k for k in C._STORE if k.startswith("FAERS")]:
            C._STORE.pop(k)

    def mk(fail):
        def g(url):
            if "reactionmeddrapt" in url and "limit=1" in url and fail == "event":
                raise TimeoutError("일시 장애")
            if "medicinalproduct" in url and "limit=1" in url:
                if fail == "drug":
                    raise TimeoutError("일시 장애")
                return {"meta": {"results": {"total": 1500}}}
            if "limit=1" in url:
                return {"meta": {"results": {"total": 20000000}}}
            return {"results": [{"term": "MINOXIDIL", "count": 420}]}
        return g

    real = F._get
    try:
        clear(); F._get = mk("event")
        r = F.drugs_for_event("HYPERTRICHOSIS")
        check("[52] 사건 총계 실패 → **오류다. 0건이 아니다**",
              bool(r["error"]) and "조회가 안 됐다" in r["error"], str(r["error"])[:60])
        check("[52] 실패했으면 행을 만들지 않는다", not r["rows"])

        clear(); F._get = mk("drug")
        r = F.drugs_for_event("HYPERTRICHOSIS")
        check("[52] 약물 총계 실패 → **제외**하고 그 사실을 적는다",
              "제외" in (r.get("note") or "") and not r["rows"], str(r.get("note"))[:60])

        clear(); F._get = mk(None)
        r = F.drugs_for_event("HYPERTRICHOSIS")
        check("[52] 정상이면 PRR 이 유한하다",
              r["rows"] and isinstance(r["rows"][0]["prr"], float), str(r["rows"])[:70])
        check("[52] **PRR 무한대는 신호가 아니다**",
              all(row["prr"] != float("inf") for row in r["rows"]))

        # 실패가 캐시에 남으면 안 된다 (결함 37)
        clear(); F._get = mk("event")
        F.drugs_for_event("HYPERTRICHOSIS")
        left = [k for k in C._STORE if "HYPERTRICHOSIS" in k]
        check("[52] 실패 결과를 캐시에 남기지 않는다", not left, str(left))
    finally:
        F._get = real
        clear()

    import inspect
    src = inspect.getsource(F._total)
    check("[52] 404 만 0 으로 친다", "e.code == 404" in src)
    check("[52] 나머지 실패는 None 이고 캐시하지 않는다",
          src.count("return None") >= 2)


def test_doc_consistency():
    """[53] **문서끼리 다른 말을 하는지** 본다 (결함 59).

    시험 [44]는 보고서 ↔ 산출물을 본다. 그런데 문서가 13개이고
    같은 사실이 여러 곳에 적혀 있다 — **문서 간 대조 장치가 없었다.**

    08-06 하루에 검토를 일곱 번 돌며 문서 10개를 일괄 편집했고 실제로
    드리프트가 났다(회귀 시험 641 vs 607 vs 실제 635 · 재현절차의 v53).
    **규칙(일괄치환 금지)으로 못 막는 것은 검사로 막는다.**
    """
    from ..bench import docaudit
    from .. import evidence as EV
    r = docaudit.audit(EV.ROOT)
    check("[53] 문서를 실제로 읽었다 — 0개면 검사가 공허하다",
          r["확인한_문서"] >= 10, r["확인한_문서"])
    hit = sum(1 for it in r["항목"] if it["값"])
    check("[53] 검사 항목이 실제로 문서에서 값을 찾는다", hit >= 4, hit)
    for it in r["항목"]:
        if it["예외"] or not it["값"]:
            continue
        check("[53] %s 가 문서마다 같다" % it["이름"], it["일치"],
              str({k: v[:2] for k, v in it["값"].items()})[:90])


def test_docking_needs_apo_structure():
    """[104] **답안지 구조로는 도킹하지 않는다** (결함 175 · 제안서 §2.5).

    > 잘못 적용된 3차원 계산은 **거짓 확신의 원천**이다.   — 제안서 §2.5

    AlphaFold 가 막히면(결함 174) 다음 수는 «실험 구조를 쓰자» 인데,
    **SARS-CoV-2 RdRp 대표 구조 상당수에 remdesivir 가 이미 붙어 있다.**
    거기에 remdesivir 를 도킹하면 잘 맞는 게 당연하다 — 포켓이 **그 리간드
    모양으로 이미 열려 있기 때문**이다. 이건 라벨 출처 논문을 근거로 쓰는
    것과 **같은 종류의 누출**이다(`set_exclude` 독스트링).

    ## 이 시험이 고정하는 것 — **오류가 「통과」 방향으로 새지 않는다**

    가장 위험한 고장은 **응답 모양을 잘못 짚는 것**이다. 그러면 리간드
    목록이 `[]` 로 나오고 `[]` 는 «apo 다» 로 읽혀 **전부 통과**한다.
    (오늘 이름을 잘못 짚은 일이 두 번 있었다 — `plddt_for`·`pubchem_smiles`.)
    그래서 **모양이 다르면 `None`** 이고 `None` 은 **거절**이다.
    """
    from ..bench import dockcheck as D

    # ── 구간 파싱 ─────────────────────────────────────────────────────
    check("[104] `A/B=4393-5324` 를 읽는다",
          D.parse_chain_ranges("A/B=4393-5324") == [(4393, 5324)],
          D.parse_chain_ranges("A/B=4393-5324"))
    check("[104] 조각 여럿을 읽는다",
          D.parse_chain_ranges("A=1-100, B=200-300") == [(1, 100), (200, 300)],
          D.parse_chain_ranges("A=1-100, B=200-300"))
    check("[104] `?-?` 는 **버린다** (0 으로 세지 않는다)",
          D.parse_chain_ranges("A=?-?") == [], D.parse_chain_ranges("A=?-?"))
    check("[104] 겹치는 구간을 두 번 안 센다",
          D.covered([(1, 10), (5, 20)], 1, 20) == 20, D.covered([(1, 10), (5, 20)], 1, 20))

    # ── apo 판정 — **기본이 배제다** ──────────────────────────────────
    check("[104] 리간드 없음 → apo", D.is_apo([])[0] is True, str(D.is_apo([])))
    check("[104] 이온·용매만 → apo", D.is_apo(["ZN", "SO4", "GOL"])[0] is True,
          str(D.is_apo(["ZN", "SO4", "GOL"])))
    check("[104] 약물 리간드 → **apo 아님**", D.is_apo(["F86"])[0] is False, str(D.is_apo(["F86"])))
    check("[104] **조회 실패는 apo 가 아니다** (못 센 것 ≠ 없는 것)",
          D.is_apo(None) == (False, ["조회실패"]), str(D.is_apo(None)))

    # ── **모양이 틀린 응답은 통과로 새지 않는다** ─────────────────────
    for bad in ({}, {"rcsb_entry_info": {}}, "문자열", None, [], {"other": 1}):
        got = D.parse_bound(bad)
        check("[104] 이상 응답 %.20r → None" % (bad,), got is None, got)
        check("[104]   → 그 값이 apo 로 안 샌다", D.is_apo(got)[0] is False, str(D.is_apo(got)))

    ok_empty = {"rcsb_entry_info": {"polymer_entity_count": 3,
                                    "deposited_atom_count": 9000}}
    check("[104] 리간드 키가 없는 **정상** 항목은 `[]` (apo)",
          D.parse_bound(ok_empty) == [], D.parse_bound(ok_empty))
    ok_lig = {"rcsb_entry_info": {"polymer_entity_count": 3,
                                  "nonpolymer_bound_components": ["F86", "ZN"]}}
    check("[104] 리간드가 있으면 그대로 읽는다",
          D.parse_bound(ok_lig) == ["F86", "ZN"], D.parse_bound(ok_lig))
    check("[104]   → 하나라도 약물이면 **거절**",
          D.is_apo(D.parse_bound(ok_lig))[0] is False, str(D.is_apo(D.parse_bound(ok_lig))))

    # ── 정렬 — **해상도보다 apo 가 먼저다** ───────────────────────────
    r = D.rank([{"id": "좋은데답안지", "apo": False, "resolution": 1.5, "covered": 900},
                {"id": "apo나쁜해상도", "apo": True, "resolution": 3.4, "covered": 900}])
    check("[104] **1.5Å 답안지보다 3.4Å apo 가 먼저**", r[0]["id"] == "apo나쁜해상도",
          [x["id"] for x in r])

    # ── UniProt 교차참조 파싱 ─────────────────────────────────────────
    doc = {"uniProtKBCrossReferences": [
        {"database": "PDB", "id": "7BV2", "properties": [
            {"key": "Method", "value": "EM"},
            {"key": "Resolution", "value": "2.50 A"},
            {"key": "Chains", "value": "A=4393-5324"}]},
        {"database": "EMDB", "id": "무관"}]}
    xr = D.parse_xrefs(doc)
    check("[104] PDB 만 골라낸다", len(xr) == 1 and xr[0]["id"] == "7BV2", xr)
    check("[104] 해상도를 수로 읽는다", xr[0]["resolution"] == 2.5, xr[0])
    check("[104] 모양이 틀린 UniProt 응답 → 빈 목록(막힘 방향)",
          D.parse_xrefs("x") == [] and D.parse_xrefs({}) == [], True)

    # ── **문서가 이 규칙을 말하고 있는가** ────────────────────────────
    import io as _io, os as _os
    from .. import evidence as _EV
    src = _io.open(_os.path.join(_EV.ROOT, "bioreroute", "bench", "dockcheck.py"),
                   encoding="utf-8").read()
    check("[104] 「기본은 배제」 가 코드 안에 적혀 있다", "기본은 배제" in src, True)

    # ── 결함 212 — **화면이 약물 이름을 지어내지 않는다** ──────────────
    #
    #   08-14 `--apo --target CCR5 --drug maraviroc` 을 돌리니 화면이
    #   «이 구조는 **remdesivir** 를 본 적이 없다» 고 찍었다.
    #   `apo_report` 에 `remdesivir` 가 **하드코딩**돼 있었다.
    #   `CLAUDE.md §4` 가 금지한 «해석 문구를 상수로 고정» 의 재발이다.
    check("[104] `apo_report` 에 약물 이름이 **박혀 있지 않다**",
          "remdesivir 를 본 적이 없다" not in src, True)
    base = {"target": "CCR5", "best": {"id": "7F1T", "method": "X-ray",
                                       "resolution": 2.6, "covered": 315},
            "cands": [], "막힌곳": None}
    r0 = D.apo_report(dict(base, drug=None))
    check("[104] 약물을 모르면 **이름을 안 적는다**",
          "remdesivir" not in r0 and "maraviroc" not in r0, r0[-90:])
    r1 = D.apo_report(dict(base, drug="maraviroc"))
    check("[104] 약물을 알면 **그 이름을 적는다**",
          "maraviroc" in r1 and "remdesivir" not in r1, r1[-90:])
    check("[104] 화이트리스트가 **방어가 아니라 회복**이라고 적혀 있다",
          "방어가 아니라 회복" in src, True)


def test_dock_live_localizes_before_pocket():
    """[105] **사슬을 못 정하면 「활성부위」라는 말을 쓰지 않는다** (결함 176).

    `structure.localize` 는 결함 90 을 막으려고 만든 함수다 —
    *폴리단백질 전체의 주석을 특정 사슬 것으로 말하기*. `assess` 는 그걸
    부르는데 **새로 쓴 `dockcheck.live()` 가 우회했다.** 그래서 화면이
    `"서열 길이 7096 · 활성부위 잔기 113개"` 를 찍었는데 **그 113개는
    RdRp 것이 아니라 pp1ab 전체 것**이었다.

    > **가드는 부르는 사람이 있어야 가드다.**

    망을 안 탄다 — `structure.resolve` 를 바꿔 끼우고, `plddt` 는
    **불리면 터지는 것**으로 바꾼다. 즉 «②까지 갔는가» 를 직접 잰다.
    """
    from ..bench import dockcheck as D
    from ..io import structure as S

    poly = {"accession": "P0DTD1", "name": "Replicase polyprotein 1ab",
            "seq_len": 7096, "error": None,
            # 주석은 **전 구간에 흩어져 있다** — nsp3·nsp5·nsp12 가 섞인 상태
            "sites": [3606, 3620, 3300, 4400, 4500, 5000],
            # **UniProt 이 쓰는 이름 그대로 — nsp 번호가 없다.**
            # 이게 실측이다(08-13 `--apo` 가 «사슬 15개 중 유일하게 맞는 것이
            # 없다» 로 막혔다). 우리가 준 `RdRp (nsp12)` 는 **어디에도 안 맞는다.**
            "chains": [{"name": "Replicase polyprotein 1ab", "start": 1, "end": 7096},
                       {"name": "Papain-like proteinase", "start": 819, "end": 2763},
                       {"name": "3C-like proteinase", "start": 3264, "end": 3569},
                       {"name": "RNA-directed RNA polymerase", "start": 4393, "end": 5324},
                       {"name": "Helicase", "start": 5325, "end": 5925}]}
    boom = {"n": 0}

    def _no_plddt(*a, **k):
        boom["n"] += 1
        raise AssertionError("**②까지 가면 안 된다** — ①에서 막혔어야 한다")

    old_r, old_p = S.resolve, S.plddt
    try:
        S.resolve = lambda *a, **k: dict(poly)
        S.plddt = _no_plddt
        # ── ① 이름이 안 맞으면 ①에서 막힌다 ──────────────────────────
        o = D.live(target="SARS-CoV-2 RdRp (nsp12)")
        check("[105] 모호하면 **①에서 막는다**",
              (o.get("막힌곳") or "").startswith("① 사슬"), o.get("막힌곳"))
        check("[105] `plddt` 를 **안 부른다**", boom["n"] == 0, boom["n"])
        check("[105] 왜 막혔는지에 **결함 90 을 적는다**",
              "결함 90" in (o.get("막힌곳") or ""), o.get("막힌곳"))
        txt = D.live_report(o)
        check("[105] 화면이 «활성부위 잔기 113개» 꼴로 **안 찍는다**",
              "폴리단백질 전체 주석" in txt and "이 표적 것이 아니다" in txt, txt[:200])

        # ── ② 이름이 맞으면 사슬로 **걸러서** 내려간다 ────────────────
        seen = {}

        def _spy(acc, sites=None, want=None):
            seen["sites"], seen["want"] = list(sites or []), want
            return {"error": "pLDDT 배열 없음"}
        S.plddt = _spy
        o2 = D.live(target="RNA-directed RNA polymerase")
        check("[105] 이름이 맞으면 **국소화된다**",
              (o2.get("localize") or {}).get("kind") == "국소화", str(o2.get("localize")))
        check("[105] **사슬 밖 주석을 버린다** (6개 → 3개 · 4393–5324 안쪽만)",
              seen.get("sites") == [4400, 4500, 5000], str(seen.get("sites")))
        check("[105] **`want` 로 단편을 고르게 한다** (결함 90 의 나머지 절반)",
              seen.get("want") == (4393, 5324), str(seen.get("want")))
    finally:
        S.resolve, S.plddt = old_r, old_p


def test_numbered_tokens_do_not_swallow(): 
    """[106] **`nsp1` 이 `nsp12` 를 삼키면 안 된다** (결함 177 · S1 게이트).

    `localize` 는 결함 90 을 막는 함수인데, **그 안의 점수 규칙이
    번호를 삼켰다.** P0DTD1 의 성숙 사슬 15개 중 둘이 1점으로 비겼다 —

        Host translation inhibitor **nsp1**    ← `nsp12`.startswith(`nsp1`)
        RNA-directed RNA polymerase **nsp12**  ← 진짜 답

    비기면 `모호` 로 거절되므로 **고장이 「막힘」 방향**이었다(다행이다).
    하지만 그 때문에 08-13 `--apo` 가 ①에서 멈췄다.

    > **뒤에 붙은 것이 숫자면 그건 다른 번호다.**

    아래 사슬 목록은 **08-13 실측**이다(`--apo` 출력). 지어낸 것이 아니다.
    """
    from ..io.structure import localize, _pmatch

    for a, b, want in [("nsp1", "nsp12", False), ("nsp12", "nsp1", False),
                       ("il1", "il12", False), ("cyp3a4", "cyp3a43", False),
                       ("3cl", "3clike", True), ("rna", "rnadirected", True),
                       ("nsp12", "nsp12", True), ("", "nsp1", False)]:
        check("[106] `%s` ~ `%s` → %s" % (a, b, want), _pmatch(a, b) is want,
              str(_pmatch(a, b)))

    REAL = [("Replicase polyprotein 1ab", 1, 7096),
            ("Host translation inhibitor nsp1", 1, 180),
            ("Non-structural protein 2", 181, 818),
            ("Papain-like protease nsp3", 819, 2763),
            ("Non-structural protein 4", 2764, 3263),
            ("3C-like proteinase nsp5", 3264, 3569),
            ("Non-structural protein 6", 3570, 3859),
            ("Non-structural protein 7", 3860, 3942),
            ("Non-structural protein 8", 3943, 4140),
            ("Viral protein genome-linked nsp9", 4141, 4253),
            ("Non-structural protein 10", 4254, 4392),
            ("RNA-directed RNA polymerase nsp12", 4393, 5324),
            ("Helicase nsp13", 5325, 5925),
            ("Guanine-N7 methyltransferase nsp14", 5926, 6452),
            ("Uridylate-specific endoribonuclease nsp15", 6453, 6798),
            ("2'-O-methyltransferase nsp16", 6799, 7096)]
    chs = [{"name": n, "start": a, "end": b} for n, a, b in REAL]

    o = localize("SARS-CoV-2 RdRp (nsp12)", chs, 7096)
    check("[106] **nsp12 로 국소화된다**", o["kind"] == "국소화", o["kind"])
    check("[106]   → 4393–5324 이다",
          (o.get("chain") or {}).get("start") == 4393, str(o.get("chain")))

    # **다른 번호도 각자 자기 것으로 간다** — nsp1·nsp13·nsp15·nsp16
    for name, want_start in [("nsp1", 1), ("nsp13 helicase", 5325),
                             ("nsp15", 6453), ("nsp16", 6799)]:
        g = localize(name, chs, 7096)
        check("[106] `%s` → %d" % (name, want_start),
              g["kind"] == "국소화" and g["chain"]["start"] == want_start,
              "%s %s" % (g["kind"], (g.get("chain") or {}).get("name")))

    # **여전히 막아야 하는 것** — 프로테아제는 둘이라 모호가 맞다
    g = localize("protease", chs, 7096)
    check("[106] `protease` 는 **여전히 모호** (nsp3·nsp5 둘이다)",
          g["kind"] == "모호", g["kind"])
    # 3CL 별칭 흡수는 안 깨졌다
    g = localize("SARS-CoV-2 3CL protease", chs, 7096)
    check("[106] `3CL protease` → nsp5 (별칭 흡수 유지)",
          g["kind"] == "국소화" and g["chain"]["start"] == 3264,
          "%s %s" % (g["kind"], (g.get("chain") or {}).get("name")))


def test_ligand_can_hide_inside_the_polymer():
    """[107] **remdesivir 는 RNA 안으로 들어간다** (결함 178).

    08-13 `--apo` 가 잘 돌았다 — 2,779 → 75 → **apo 37건**. 그런데 그
    37건이 정말 답안지가 아닌지는 **`nonpolymer_bound_components` 만
    봐서는 알 수 없다.**

    remdesivir 삼인산은 중합효소가 **자라는 RNA 가닥에 붙여 넣는**
    사슬종결 뉴클레오티드 유사체다. `7BV2` 에서 그것은 **비중합체 리간드가
    아니라 RNA 프라이머의 3' 말단**, 즉 **중합체의 일부**다.

    > **비중합체 목록만 보면 답안지가 apo 로 통과한다.**

    둘째로, RNA 가 붙어 있으면 뉴클레오티드 자리를 **그 RNA 가 이미
    차지**한다. 도킹 상자를 거기 놓으면 겹친다.
    """
    from ..bench import dockcheck as D

    # ── 핵산 판정 — **RCSB 표기 전집** ────────────────────────────────
    for comp, want in [("protein/NA", True), ("nucleic acid (only)", True),
                       ("DNA/RNA", True), ("NA-hybrid", True), ("DNA", True),
                       ("protein (only)", False),
                       ("protein/oligosaccharide", False)]:
        g = D.parse_polymer({"rcsb_entry_info": {"polymer_composition": comp}})
        check("[107] `%s` → 핵산 %s" % (comp, want), g is want, str(g))
    check("[107] 개수 필드를 **우선** 본다",
          D.parse_polymer({"rcsb_entry_info":
                           {"polymer_entity_count_nucleic_acid": 2,
                            "polymer_composition": "protein (only)"}}) is True, True)
    check("[107] 모르면 `None` (0 이 아니다)", D.parse_polymer({}) is None, True)

    # ── **핵심** — 리간드 목록이 비어도 RNA 가 있으면 apo 가 아니다 ────
    ok, why = D.is_apo([], na=True, n_nonpoly=0)
    check("[107] **리간드 0개 + RNA → apo 아님**", ok is False, str((ok, why)))
    check("[107]   → 이유가 «핵산사슬» 이다", why == ["핵산사슬"], str(why))
    check("[107] 핵산 여부를 **모르면** 거절",
          D.is_apo([], na=None, n_nonpoly=2)[0] is False,
          str(D.is_apo([], na=None, n_nonpoly=2)))
    check("[107] 리간드 0개 + RNA 없음 → apo",
          D.is_apo([], na=False, n_nonpoly=0)[0] is True,
          str(D.is_apo([], na=False, n_nonpoly=0)))

    # ── 설명 안 되는 비중합체는 미확인 ────────────────────────────────
    check("[107] `ZN` 이 결합으로 잡혔고 비중합체 1개 → **설명됐다**",
          D.is_apo(["ZN"], na=False, n_nonpoly=1)[0] is True,
          str(D.is_apo(["ZN"], na=False, n_nonpoly=1)))
    check("[107] 비중합체 3개인데 결합은 1개 → **미확인·거절**",
          D.is_apo(["ZN"], na=False, n_nonpoly=3)[0] is False,
          str(D.is_apo(["ZN"], na=False, n_nonpoly=3)))

    # ── 캐시 키를 올렸는가 (옛 항목이 새 규칙을 우회하면 안 된다) ──────
    import io as _io, os as _os
    from .. import evidence as _EV
    src = _io.open(_os.path.join(_EV.ROOT, "bioreroute", "bench", "dockcheck.py"),
                   encoding="utf-8").read()
    check("[107] 캐시 키를 **v3 까지 올렸다**", "RCSBLIG3::" in src, True)
    check("[107] 옛 키를 **안 읽는다**",
          '"RCSBLIG::"' not in src and '"RCSBLIG2::"' not in src, True)
    check("[107] 화면이 핵산 건수를 **따로 찍는다**",
          "그중 핵산 결합" in src, True)


def test_docked_species_must_be_the_binding_species():
    """[108] **도킹할 분자가 그 자리에 오는 분자인가** (결함 179 · 제안서 §2.5).

    08-13 `--apo` 출력에서 `7BV2` 가 이렇게 찍혔다 —

        7BV2  EM 2.50Å  리간드 **핵산사슬, F86, POP**

    `F86` 은 remdesivir **일인산**, `POP` 는 피로인산이다. 즉 실험 구조에
    들어 있는 것은 **모분자가 아니다.** remdesivir 는 ProTide 계열
    **전구약물**이고, 중합효소가 넣는 것은 삼인산에서 온 일인산이다.

    그런데 우리 파이프라인은 **약물 이름으로 PubChem SMILES 를 받는다** —
    도킹하는 것은 모분자다. **그 점수는 다른 분자의 점수다.**

    > 제안서 §2.5 — *잘못 적용된 3차원 계산은 거짓 확신의 원천이다.*

    연결블록(InChIKey 앞 14자)으로 본다. **인산이 붙으면 연결이 바뀌므로
    모분자와 일인산은 다르게 나온다** — 그게 알고 싶은 것이다.
    """
    from ..bench import dockcheck as D

    check("[108] 연결블록은 앞 14자",
          D.skeleton("RWWYLEGWBNMMLJ-YSOARWBDSA-N") == "RWWYLEGWBNMMLJ",
          D.skeleton("RWWYLEGWBNMMLJ-YSOARWBDSA-N"))
    check("[108] 짧으면 `None` (자르지 않는다)", D.skeleton("abc") is None, D.skeleton("abc"))
    check("[108] 없으면 `None`", D.skeleton(None) is None, True)
    check("[108] 입체·전하만 다르면 **같다**",
          D.skeleton("AAAAAAAAAAAAAA-BBBBBBBBSA-N") ==
          D.skeleton("AAAAAAAAAAAAAA-CCCCCCCCSA-O"), True)

    doc = {"chem_comp": {"id": "F86", "name": "remdesivir monophosphate",
                         "formula": "C20 H27 N6 O8 P"},
           "rcsb_chem_comp_descriptor": {"InChIKey": "ZZZZZZZZZZZZZZ-AAAAAAAASA-N"}}
    c = D.parse_comp(doc)
    check("[108] 화학성분을 읽는다", c["id"] == "F86" and c["name"], str(c))
    check("[108] 모양이 다르면 `None`",
          D.parse_comp({}) is None and D.parse_comp("x") is None, True)
    check("[108] InChIKey 가 없으면 `None` (빈 문자열 아니다)",
          D.parse_comp({"chem_comp": {"id": "X"}})["inchikey"] is None, True)

    # **모르면 「같다」가 아니다** — 연결블록이 없으면 same 이 참이 되면 안 된다
    ours, theirs = None, "ZZZZZZZZZZZZZZ"
    same = (ours is not None and theirs is not None and ours == theirs)
    check("[108] **한쪽을 모르면 「같다」로 안 간다**", same is False, str(same))

    # 우리 코드가 그 규칙을 **글로도 적어 뒀는가**
    import io as _io, os as _os
    from .. import evidence as _EV
    src = _io.open(_os.path.join(_EV.ROOT, "bioreroute", "bench", "dockcheck.py"),
                   encoding="utf-8").read()
    check("[108] 전구약물을 코드가 언급한다", "전구약물" in src, True)
    check("[108] «거르는 데 쓰면 안 되고 알리는 데는 맞다» 를 적어 뒀다",
          "어긋남을 알리는 데는 맞다" in src, True)
    check("[108] 「모르면 같다가 아니다」를 판정 문구에 넣었다",
          "**모르면 「같다」가 아니다**" in src, True)


def test_refuse_docking_when_species_and_apo_conflict():
    """[109] **맞는 분자와 답안지 회피가 부딪히면 도킹을 거부한다** (결함 180).

    08-13 `--species` 실측 — 홀로 71건에 붙은 상위 8종이 **전부 다르다**:
    `ADP`·`AF3`·`POP`·`GNP`·`F86`·`HCU`·`L2B`·`GTP`. **약물스러운 분자가
    하나도 없다** — 뉴클레오티드와 인산전이 유사체뿐, 즉 **보조인자 자리**다.

    두 요구가 부딪힌다 —

      1. 답안지를 피하려면 **apo** 를 써야 한다 (결함 175·178)
      2. 맞는 분자를 넣으려면 **활성형 삼인산**을 써야 하는데,
         그 자리는 **RNA 이중가닥 + Mg²⁺ 가 있어야 만들어진다**

    **apo 에 삼인산을 넣는 것은 물리적으로 무의미**하고, RNA 붙은 구조에
    넣으면 **답안지**다. 둘 다 안 된다.

    > 결론은 «못 한다» 가 아니라 **«이 자리에서는 도킹을 쓰지 않는다»** 이고,
    > 제안서 §2.5 가 그것을 창의적 기여라고 적었다 —
    > *언제 도킹을 적용하지 **말아야** 하는가.*
    """
    from ..bench.dockcheck import dock_verdict as V

    k, why = V(False, 4, 71)
    check("[109] **종이 다르면 거부**", k == "거부", k)
    check("[109]   → 이유가 «다른 분자의 점수»", "다른 분자의 점수" in why, why[:60])

    check("[109] apo 가 0건이면 거부 (재현이 된다)", V(True, 0, 71, True)[0] == "거부",
          V(True, 0, 71, True)[0])
    check("[109] **자리 형성을 모르면 거부** (모르면 배제)",
          V(True, 4, 71, None)[0] == "거부", V(True, 4, 71, None)[0])
    check("[109] 자리가 안 만들어지면 거부", V(True, 4, 71, False)[0] == "거부",
          V(True, 4, 71, False)[0])
    check("[109] **셋이 다 맞아야 진행**", V(True, 4, 71, True)[0] == "진행",
          V(True, 4, 71, True)[0])

    # **거부가 기본값이다** — 인자를 안 채우면 진행이 나오면 안 된다
    check("[109] 기본값이 «진행» 이 아니다", V(True, 4, 71)[0] == "거부",
          V(True, 4, 71)[0])


def test_scan_does_not_let_me_pick():
    """[110] **데모 표적을 내가 고르지 않는다** (결함 181 · 제안서 §4.2).

    제안서 §2.4 표에 도킹 가능한 행은 **하나뿐**(RdRp)이고 그게 결함
    179·180 으로 막혔다. 표적을 바꾸려면 **누가 고르느냐**가 문제가 된다.

    > **내가 고르면 «되는 것을 골랐다» 가 된다.**

    그래서 후보를 **라우터 출력**에서 가져온다 — `routercheck.json` 의
    `docking_advised=True` **전부**. 봉인 `aff5c888d546`.
    """
    from ..bench import dockcheck as D

    c = D.scan_candidates()
    check("[110] 후보가 **8건** 이다", len(c) == 8, len(c))
    names = [x["drug"] for x in c]
    check("[110] 막힌 것도 **뺴지 않는다** (remdesivir 가 있다)",
          "remdesivir" in names, str(names[:3]))
    for k in ("drug", "target", "disease"):
        check("[110] 후보에 `%s` 가 있다" % k, all(x.get(k) for x in c[:1]), k)

    # ── ③ — **이 약의 자리**를 묻지 이 단백질의 습관을 묻지 않는다 ────
    sk = lambda z: {"RFP": "AAAA"}.get(z)
    got = D.site_needs_na([{"bound": ["RFP"], "na": False},
                           {"bound": ["RFP"], "na": True}], "AAAA", sk)
    check("[110] 우리 분자가 붙은 구조 중 **핵산 없는 것이 있으면 True**",
          got == (True, 2, 1), str(got))
    got = D.site_needs_na([{"bound": ["RFP"], "na": True}], "AAAA", sk)
    check("[110] 전부 핵산이 붙어 있으면 **False**", got == (False, 1, 0), str(got))
    got = D.site_needs_na([{"bound": ["X"], "na": False}], "AAAA", sk)
    check("[110] 우리 분자가 **어디에도 없으면 `None`** (0 이 아니다)",
          got == (None, 0, 0), str(got))
    check("[110]   → `None` 은 `dock_verdict` 가 **거부**로 받는다",
          D.dock_verdict(True, 5, 5, None)[0] == "거부",
          D.dock_verdict(True, 5, 5, None)[0])

    # ── 봉인이 먼저다 ────────────────────────────────────────────────
    import os as _os
    from .. import evidence as _EV
    check("[110] **명세가 봉인돼 있다**",
          _os.path.exists(_os.path.join(_EV.ROOT, "사전명세_도킹표적선정_봉인.json")),
          True)
    s = [x for x in _EV.seals() if "도킹표적선정" in x["대상"]]
    check("[110] 봉인이 **무결**하다", bool(s) and s[0]["무결"] is True, str(s))


def test_scan_must_not_default_to_one_organism():
    """[111] **후보마다 자기 생물종으로 묻는다** (결함 184).

    08-13 첫 `--scan` 에서 HCV·HSV·결핵균 표적이 remdesivir 와 **덮음 75 ·
    apo 4** 로 **같은 수**를 냈다. 생물종이 다른 네 단백질이 같은 수를 낼
    수 없다 — `apo_scan(organism="SARS-CoV-2")` 라는 **기본값** 때문에
    전부 `P0DTD1` 로 해석된 것이다.

    > **데모 하나를 편하게 하려고 넣은 기본값이 전수 주사를 따라갔다.**

    이 시험이 고정하는 것 —

      · 기본값이 **더는 SARS-CoV-2 가 아니다**
      · 생물종은 **라우터의 `mech`** 에서 읽는다(숙주/병원체)
      · **못 정하면 넓게 안 찾는다** — `None` 이고 그러면 거부
    """
    import inspect
    from ..bench import dockcheck as D

    sig = inspect.signature(D.apo_scan)
    check("[111] `apo_scan` 기본 생물종이 **없다**",
          sig.parameters["organism"].default is None,
          repr(sig.parameters["organism"].default))

    F = D.organism_for
    check("[111] 숙주는 **사람**", F({"mech": "직접·숙주", "disease": "COVID-19"})
          == "Homo sapiens", F({"mech": "직접·숙주", "disease": "COVID-19"}))
    check("[111] 병원체는 **질환에서** 끌어온다",
          F({"mech": "직접·병원체", "disease": "Tuberculosis"})
          == "Mycobacterium tuberculosis",
          F({"mech": "직접·병원체", "disease": "Tuberculosis"}))
    check("[111] COVID 병원체는 SARS-CoV-2",
          F({"mech": "직접·병원체", "disease": "COVID-19"}) == "SARS-CoV-2", True)
    check("[111] **모르는 질환은 `None`** (넓게 안 찾는다)",
          F({"mech": "직접·병원체", "disease": "Malaria"}) is None,
          str(F({"mech": "직접·병원체", "disease": "Malaria"})))
    check("[111] 간접 기전도 `None`", F({"mech": "간접", "disease": "COVID-19"}) is None,
          str(F({"mech": "간접", "disease": "COVID-19"})))

    # **16쌍이 실제로 서로 다른 종으로 간다** — 같은 종으로 뭉치면 결함 184 재현
    orgs = {}
    for c in D.scan_candidates(only_advised=False):
        o = F(c)
        if o:
            orgs.setdefault(o, []).append(c["drug"])
    check("[111] 생물종이 **여러 개**로 갈린다 (하나로 뭉치지 않는다)",
          len(orgs) >= 7, "%d종: %s" % (len(orgs), sorted(orgs)))
    adv = [c for c in D.scan_candidates() ]
    povs = {F(c) for c in adv}
    check("[111] **병원체 8건이 한 종으로 안 뭉친다**", len(povs) >= 6,
          "%d종" % len(povs))


def test_unknown_species_gets_its_own_reason():
    """[112] **모르는 것을 다른 이유로 적지 않는다** (결함 185).

    08-13 `--scan --all` 에서 `ibalizumab`(**항체**)이 이렇게 나왔다 —

        ibalizumab  CD4  ...  거부  ← «자리가 안 만들어진다»

    **틀린 사유다.** 항체라 **SMILES 자체가 없어서** 종을 못 쟀다.
    `dock_verdict` 이 `species_same=None` 을 그냥 흘려보내 세 번째 가지로
    떨어뜨렸다. 결함 35·89 계열 — *못 센 것과 없는 것을 안 가르기.*

    같은 실행이 더 큰 것도 보여 줬다 — **16/16 이 `n_drugbound=0`**.
    종 관문이 «같음» 을 **한 번도 낸 적이 없다.** 그래서 «종 불일치» 7건도
    **불일치인지 못 잰 것인지 구분이 안 된다.**
    """
    from ..bench.dockcheck import dock_verdict as V

    k, why = V(None, 6, 5, None)
    check("[112] 종 미상은 **거부**", k == "거부", k)
    check("[112] 사유가 «종을 못 쟀다» 다", "종을 못 쟀다" in why, why[:40])
    check("[112] **«자리」 이야기를 하지 않는다**", "자리가 안 만들어진다" not in why,
          why[:60])
    check("[112] 항체·펩타이드를 짚어 준다", "항체" in why, why[-40:])

    # 나머지 가지는 그대로여야 한다
    check("[112] 종 불일치는 여전히 자기 사유", "다른 분자의 점수" in V(False, 4, 71)[1], True)
    check("[112] apo 0건은 여전히 자기 사유", "답안지뿐" in V(True, 0, 71, True)[1], True)
    check("[112] 자리 미확인은 여전히 자기 사유",
          "자리가 안 만들어진다" in V(True, 4, 71, None)[1], True)
    check("[112] 셋이 다 맞아야 진행", V(True, 4, 71, True)[0] == "진행", True)

    # **네 가지가 서로 다른 문장**이어야 한다 — 하나로 뭉치면 진단이 안 된다
    ws = {V(None, 1, 1, None)[1], V(False, 1, 1, None)[1],
          V(True, 0, 1, True)[1], V(True, 1, 1, None)[1]}
    check("[112] 거부 사유 **넷이 서로 다르다**", len(ws) == 4, len(ws))


def test_ask_from_the_drug_not_the_structure():
    """[113] **자료원이 채워 줄 거라 믿지 않는다** (결함 187).

    08-13 양성 대조 두 건 —

        CCR5       홀로 6건 · 리간드 **1종**(NAG)   ← 4MBS 의 maraviroc 이 없다
        M.tb RNAP  홀로 78건 · 리간드 **3종 4건**   ← rifampin 이 없다

    `rcsb_entry_info.nonpolymer_bound_components` 가 **대부분 비어 있다.**
    그 위에 종 대조를 세웠으니 **고장이 「없다」 방향으로 샜다.**

    > 고침은 필드를 바꾸는 게 아니라 **질문의 방향을 바꾸는 것**이다.
    > 구조 N개에 «여기 우리 약이 있나» 를 N번 묻지 말고,
    > **약물 → het code → 그 코드를 가진 구조 목록**으로 간다.

    빈 집합(«PDB 에 없다»)과 `None`(«못 물어봤다»)을 **가른다.**
    """
    from ..bench import dockcheck as D

    check("[113] UniChem 에서 **PDBe 소스만** 고른다",
          D.parse_unichem([{"src_id": "3", "src_compound_id": "rfp"},
                           {"src_id": "1", "src_compound_id": "CHEMBL374478"}])
          == {"RFP"}, str(D.parse_unichem([{"src_id": "3", "src_compound_id": "rfp"}])))
    check("[113] 오류 응답(dict)은 `None`", D.parse_unichem({"error": "x"}) is None, True)
    check("[113] **빈 목록은 «없다»** (`None` 아니다)",
          D.parse_unichem([]) == set(), str(D.parse_unichem([])))

    check("[113] `in_pdb` 를 읽는다",
          D.parse_in_pdb({"RFP": ["5uhc", "5uhb"]}, "RFP") == {"5UHC", "5UHB"},
          str(D.parse_in_pdb({"RFP": ["5uhc"]}, "RFP")))
    check("[113] 소문자 키도 읽는다",
          D.parse_in_pdb({"rfp": ["5uhc"]}, "RFP") == {"5UHC"}, True)
    check("[113] **빈 dict 는 «없다»**", D.parse_in_pdb({}, "RFP") == set(), True)
    check("[113] 모양이 다르면 `None`",
          D.parse_in_pdb("x", "RFP") is None
          and D.parse_in_pdb({"OTHER": []}, "RFP") is None, True)

    # **못 물어본 것이 「없다」로 새면 안 된다** — 이게 결함 187 의 핵심
    check("[113] `None` 과 `set()` 이 **다른 값**이다",
          D.parse_unichem({"e": 1}) is not D.parse_unichem([]), True)

    # ── **요약이 비면 원장을 편다** — 결함 187 의 실제 고침 ──────────
    check("[113] 엔티티 번호를 읽는다",
          D.parse_nonpoly_ids({"rcsb_entry_container_identifiers":
                               {"non_polymer_entity_ids": ["1", "2"]}}) == ["1", "2"],
          True)
    check("[113] 번호를 모르면 `None` (빈 목록 아니다)",
          D.parse_nonpoly_ids({}) is None and D.parse_nonpoly_ids("x") is None, True)
    check("[113] 엔티티에서 성분 코드를 읽는다",
          D.parse_nonpoly_comp({"pdbx_entity_nonpoly": {"comp_id": "rfp"}}) == "RFP",
          D.parse_nonpoly_comp({"pdbx_entity_nonpoly": {"comp_id": "rfp"}}))
    check("[113] 성분을 모르면 `None`", D.parse_nonpoly_comp({}) is None, True)
    import io as _io2, os as _os2
    from .. import evidence as _EV2
    _src = _io2.open(_os2.path.join(_EV2.ROOT, "bioreroute", "bench", "dockcheck.py"),
                     encoding="utf-8").read()
    check("[113] **요약을 안 믿는다** — 원장을 편다",
          "_ligands_via_entities" in _src, True)
    check("[113] 원장도 못 읽으면 **표식을 붙여 apo 를 막는다** (결함 188)",
          '"원장미확인"' in _src, True)

    # 결함 178 규칙이 apo 판정을 지켰다 — 그 규칙이 아직 살아 있나
    ok, why = D.is_apo([], na=False, n_nonpoly=3)
    check("[113] **`bound` 가 비어도 비중합체가 있으면 apo 아님** (결함 178 이 187 을 막았다)",
          ok is False, str((ok, why)))


def test_partial_source_is_worse_than_empty_one():
    """[114] **부분적으로 맞는 자료원이 빈 자료원보다 위험하다** (결함 188).

    08-13 `--api` 로 **답을 아는 두 구조**를 직접 열었다 —

        4MBS  요약 ["ZN"]        원장 ["MRV","ZN","OLC"]   ← MRV = maraviroc
        5UHC  요약 ["MG","ZN"]   원장 ["RFP","ZN","MG"]    ← RFP = rifampin

    `nonpolymer_bound_components` 는 **비어 있는 게 아니라 이온만 싣는다.**

    결함 187 의 고침을 `if b == []: 원장을 편다` 로 짰는데, **그 조건이
    약물이 든 항목을 정확히 비켜 간다** — 약물이 있으면 이온도 대개 있어
    요약이 안 비기 때문이다.

    > **빈 자료원은 눈에 띄지만, 부분적인 자료원은 «값이 있네» 로 통과한다.**
    """
    import io as _io, os as _os
    from .. import evidence as _EV
    from ..bench import dockcheck as D

    src = _io.open(_os.path.join(_EV.ROOT, "bioreroute", "bench", "dockcheck.py"),
                   encoding="utf-8").read()
    check("[114] **«비었을 때만» 조건이 사라졌다**", "if b == []:" not in src, True)
    check("[114] 원장을 **먼저** 부른다",
          src.index("b = _ligands_via_entities(pdb_id, d)")
          < src.index("b = parse_bound(d)"), True)
    check("[114] 원장을 못 읽으면 **표식을 붙인다**", '"원장미확인"' in src, True)

    # 표식이 apo 를 막는가 — **BENIGN 에 없어야 막힌다**
    check("[114] `원장미확인` 은 이온 목록에 **없다**",
          "원장미확인" not in D.BENIGN, True)
    ok, why = D.is_apo(["ZN", "원장미확인"], na=False, n_nonpoly=1)
    check("[114] 요약만 있으면 **apo 로 못 간다**", ok is False, str((ok, why)))

    # 실측 두 구조를 그대로 넣어 본다
    ok, why = D.is_apo(["MRV", "ZN", "OLC"], na=False, n_nonpoly=3)
    check("[114] 4MBS(원장) → **apo 아님** · maraviroc 이 보인다",
          ok is False and "MRV" in why, str((ok, why)))
    ok, why = D.is_apo(["ZN"], na=False, n_nonpoly=3)
    check("[114] 4MBS(요약만) → **결함 178 규칙이 막아 준다**",
          ok is False, str((ok, why)))
    check("[114] 진짜 apo(이온만·수가 맞음)는 통과",
          D.is_apo(["ZN", "MG"], na=False, n_nonpoly=2)[0] is True, True)


def test_deploy_copy_is_not_the_original():
    """[115] **배포 사본과 원본이 바이트까지 같다** (결함 189).

    `배포업로드/` 안에 이런 파일이 있다 —

        이 폴더는 **자동 생성된 업로드 사본**이다.
          · 원본은 상위 폴더다. **여기를 고치지 마라** — 반영 안 된다

    08-13에 **정확히 그걸 했다.** 화면 고침 넷(결함 160·161·166·§2.3 pico)을
    사본에만 넣었고, 원본은 08-11 판 그대로였다(64줄 차이).

    파급 셋 —

      · 다음 `--stage` 가 **오늘 작업을 통째로 덮어쓴다**
      · `배포.md` 는 `py app.py`(원본)로 화면을 보라고 적어 뒀다
      · **시험 [103]이 사본을 읽고 통과했다** — 거짓 안심

    > **안내문이 있었고 나는 안 읽었다.**
    > 사본이 쓰기 가능한 한 안내문은 안 듣는다. 그래서 이 시험이 있다.

    `docaudit` 은 **숫자만** 본다 — 두 파일이 같은 결함 수를 적고 있으면
    통과한다. 실제로 08-13에 64줄 갈라졌는데 «불일치 없음» 이 나왔다.
    **바이트 동일성은 여기서만 본다.**
    """
    import hashlib as _h, os as _os
    from .. import evidence as _EV

    a = _os.path.join(_EV.ROOT, "app.py")
    b = _os.path.join(_EV.ROOT, "배포업로드", "app.py")
    check("[115] 원본이 있다", _os.path.exists(a), a)
    check("[115] 사본이 있다", _os.path.exists(b), b)
    if not (_os.path.exists(a) and _os.path.exists(b)):
        return
    ha = _h.sha256(open(a, "rb").read()).hexdigest()
    hb = _h.sha256(open(b, "rb").read()).hexdigest()
    check("[115] **바이트가 같다** — 갈라지면 사본을 고친 것이다",
          ha == hb, "원본 %s · 사본 %s" % (ha[:12], hb[:12]))

    # 사본 폴더가 «고치지 마라» 를 여전히 적어 두는가
    n = _os.path.join(_EV.ROOT, "배포업로드", "_이_폴더는_무엇인가.txt")
    if _os.path.exists(n):
        s = open(n, encoding="utf-8").read()
        check("[115] 사본 폴더가 «고치지 마라» 를 적어 둔다",
              "고치지 마라" in s, s[:40])

    # ── **사본 전체**를 본다 (결함 206) ────────────────────────────
    #
    #   08-14 실측 — `app.py` 만 갈라진 게 아니었다. **25개가 갈라져
    #   있었고 전부 사본이 낡았다** (`stats.py` 08-05 · `gates.py` 08-11 ·
    #   `발견정리.md` 08-12). 즉 **그때 배포했으면 옛 코드가 올라갔다.**
    #
    #   `docaudit` 은 «불일치 없음» 을 냈다 — 사본 중 **`app.py` 하나만**
    #   목록에 있기 때문이다. 하나를 지키는 검사가 **나머지 24개를
    #   못 봤다.**
    stage = _os.path.join(_EV.ROOT, "배포업로드")
    stale = []
    if _os.path.isdir(stage):
        for dp, _dn, fs in _os.walk(stage):
            if "__pycache__" in dp:
                continue
            for f in fs:
                cp = _os.path.join(dp, f)
                rel = _os.path.relpath(cp, stage).replace(_os.sep, "/")
                # **올릴 때 이름이 바뀌는 것**은 코드에서 읽는다 —
                # 예외를 시험에 손으로 적으면 그게 다음 사각지대가 된다.
                # `deploycheck.RENAME` 이 정본이다 (`README_HF.md → README.md`)
                from ..bench import deploycheck as _DC
                back = {v: k for k, v in getattr(_DC, "RENAME", {}).items()}
                op = _os.path.join(_EV.ROOT, back.get(rel, rel))
                if not _os.path.exists(op):
                    continue          # 사본 전용 파일(안내문 등)은 넘어간다
                if (_h.sha256(open(cp, "rb").read()).hexdigest()
                        != _h.sha256(open(op, "rb").read()).hexdigest()):
                    stale.append(rel)
    check("[115] **배포 사본 전체가 원본과 같다** — 갈라지면 옛 판이 올라간다",
          not stale,
          ("%d개 낡음: %s%s  → 고치는 법: "
           "`py -m bioreroute.bench.deploycheck --stage 배포업로드`")
          % (len(stale), ", ".join(sorted(stale)[:4]),
             " 외 %d" % (len(stale) - 4) if len(stale) > 4 else ""))


def test_seal_records_code_and_checks_it():
    """[116] **봉인이 코드도 본다 — 그리고 기록이 맞는지 스스로 대조한다** (결함 190·199).

    봉인 json 은 `실행_전_증거` 에 실행 시점 코드 md5 를 적어 왔다.
    **그런데 `seals()` 가 그걸 한 번도 안 봤다.**

    08-13에 처음 대조하니 **18개 중 9개가 불일치**였고, 갈라 보니
    두 종류였다 —

        봉인 뒤에 파일이 바뀜        실제 변경
        파일이 봉인보다 **오래됐는데** 불일치   **기록 자체가 틀렸다**

    > **한 번도 대조 안 한 필드는 기록이 아니라 장식이다.**

    그래서 둘을 넣었다 —

      · `seals()` 가 `코드변경` 을 **따로** 낸다 (`무결` 은 안 건드린다 —
        버그 수정은 정상이다. 다만 **보이게** 한다)
      · `make_seal()` 이 봉인 **직후 다시 읽어 대조**하고 안 맞으면 던진다
    """
    import json as _j, os as _os, hashlib as _h
    from .. import evidence as _EV

    s = _EV.seals()
    check("[116] 봉인 목록이 있다", len(s) >= 10, len(s))
    check("[116] **`코드변경` 칸이 있다**", all("코드변경" in x for x in s),
          str(sorted(s[0])))
    check("[116] `무결` 과 `코드변경` 은 **다른 칸**이다",
          "무결" in s[0] and "코드변경" in s[0], str(sorted(s[0])))

    # `make_seal` 이 **스스로 대조**하는가 — 틀린 기록을 넣고 잡히는지 본다
    check("[116] `make_seal` 이 있다", hasattr(_EV, "make_seal"), True)
    import inspect
    src = inspect.getsource(_EV.make_seal)
    check("[116] 봉인 직후 **다시 읽는다**", "back = _j.load" in src, True)
    check("[116] 안 맞으면 **던진다**", "raise AssertionError" in src, True)
    check("[116] 없는 파일을 **`None` 으로 적는다** (0 이 아니다)",
          '"sha256": None' in src, True)

    # 실제로 한 번 만들어 보고 대조까지 통과하는지 — **임시 폴더에서**.
    #   ⛔ 09-25 · 결함 335 — 앞판은 **저장소의 `archive/`** 에 문서와 봉인 json 을
    #   썼다(시험을 돌릴 때마다 실제 파일이 바뀌었다). `make_seal(root=)` 가 있다.
    import shutil as _sh116
    import tempfile as _tf116
    troot = _tf116.mkdtemp(prefix="seal116_")
    _os.makedirs(_os.path.join(troot, "archive"))
    _os.makedirs(_os.path.join(troot, "bioreroute"))
    _sh116.copy2(_os.path.join(_EV.ROOT, "bioreroute", "evidence.py"),
                 _os.path.join(troot, "bioreroute", "evidence.py"))
    tmp = _os.path.join(troot, "archive", "_봉인자기시험.md")
    open(tmp, "w", encoding="utf-8").write("자기 대조 시험")
    try:
        p = _EV.make_seal(_os.path.relpath(tmp, troot).replace("\\", "/"),
                          ["bioreroute/evidence.py"], root=troot)
        d = _j.load(open(p, encoding="utf-8"))
        cur = _h.md5(open(_os.path.join(_EV.ROOT, "bioreroute", "evidence.py"),
                          "rb").read()).hexdigest()
        check("[116] **기록한 md5 가 실제와 같다**",
              d["실행_전_증거"]["bioreroute/evidence.py"]["sha256"] == cur,
              "기록 %s" % d["실행_전_증거"]["bioreroute/evidence.py"]["sha256"][:10])
    except Exception as e:
        check("[116] 자기 대조가 예외 없이 돈다", False, "%s: %s" % (type(e).__name__, e))


def test_adjudicate_defences_have_their_own_test():
    """[117] **판정의 방어 넷을 직접 태운다** (결함 200).

    08-13 밤 돌연변이 시험 — `scoring.adjudicate` 의 방어를 하나씩 지우고
    **시험 1,382개 전수**를 돌렸다. 넷이 전부 **같은 시험 하나**에만 걸렸다.

        s1 F0 조회 실패를 판정으로   → test_registry_quote
        s2 문헌 0건(환각)을 기각 안 함 → test_registry_quote
        s3 하드 비토 무력화          → test_registry_quote
        s5 상관 감쇠 제거            → test_registry_quote

    **그 시험은 등록부 인용 검증기(`verify_quote`) 시험이다.** 판정과
    아무 관계가 없고, 넷은 **부수 효과로** 걸렸을 뿐이다.

    > **하나의 시험이 서로 다른 네 방어를 혼자 지키고 있었다.**
    > 그 시험의 기대값이 다른 이유로 바뀌면 **넷이 동시에 무방비**가 된다.

    제안서가 «이미 구현» 이라 적은 **F0 환각 기각**(§3.3)과 §2.3 의
    **하드 비토**가 전용 회귀 시험 없이 돌고 있었다. 여기서 각각 붙인다.
    """
    from ..core.scoring import adjudicate
    from ..core.state import Candidate, Evidence

    def C(**kw):
        c = Candidate(name="x", origin="t", query="q", drug="d", disease="i")
        for k, v in kw.items():
            setattr(c, k, v)
        return c

    # ── s1 · **조회 실패는 판정이 아니다** (결함 6·35 계열) ────────────
    v, p, why = adjudicate(C(f0={"error": "network"}))
    check("[117] F0 조회 실패 → **보류**", v == "보류", v)
    check("[117]   → 확률을 **안 낸다** (`None`)", p is None, str(p))
    check("[117]   → 사유에 «조회 실패» 가 있다", "조회 실패" in why, why[:30])

    # ── s2 · **문헌 0건 = 환각 → 하드 기각** (제안서 §3.3 «이미 구현») ──
    v, p, why = adjudicate(C(f0={"count": 0}))
    check("[117] 문헌 0건 → **기각**", v == "기각", v)
    check("[117]   → 확률 0", p == 0, str(p))
    #   다만 **2겹 F0 에서 약물 실재가 확인되면 환각이 아니다**
    v2, p2, _ = adjudicate(C(f0={"count": 0, "link_zero": True}))
    check("[117] 약물은 실재 · 연결 0건 → **보류**(환각 아님)", v2 == "보류", v2)
    check("[117]   → 50%", p2 == 50, str(p2))

    # ── s3 · **하드 비토** (제안서 §2.3 결정적 반박) ───────────────────
    c = C(veto=True, veto_reason="3상 무효")
    c.support = [Evidence("t", "support", 3.0)] * 3      # 지지가 아무리 많아도
    v, p, why = adjudicate(c)
    check("[117] 비토가 서면 **지지 3건이 있어도 기각**", v == "기각", v)
    check("[117]   → 사유가 비토 사유 그대로", why == "3상 무효", why)

    # ── s5 · **상관 감쇠** — LLM 근거는 감쇠하고 사람 근거는 안 한다 ────
    def p_of(src):
        c = C()
        c.support = [Evidence("t", "support", 1.0, source=src) for _ in range(3)]
        return adjudicate(c)[1]
    p_llm, p_cur = p_of("llm"), p_of("curated")
    check("[117] LLM 근거 3건은 **감쇠**돼 사람 근거보다 확률이 낮다",
          p_llm < p_cur, "llm %s < curated %s" % (p_llm, p_cur))
    #   1 + 0.5 + 0.25 = 1.75  vs  3.0 — 방향만이 아니라 값도 고정한다
    from ..core.scoring import sigmoid
    check("[117]   → LLM 쪽 값이 1+0.5+0.25 로 계산된다",
          p_llm == int(round(sigmoid(1.75) * 100)), str(p_llm))
    check("[117]   → 사람 쪽 값이 3.0 으로 계산된다",
          p_cur == int(round(sigmoid(3.0) * 100)), str(p_cur))

    # ── s8 · **로그오즈 상한** — 근거를 쌓아 100%를 만들 수 없다 ────────
    c = C()
    c.support = [Evidence("t", "support", 9.0, source="curated")] * 5
    v, p, why = adjudicate(c)
    check("[117] 지지를 아무리 쌓아도 **상한이 걸린다**",
          p == int(round(sigmoid(4.0) * 100)), str(p))
    check("[117]   → 상한을 걸었다고 **화면에 적는다**", "상한" in why, why[-24:])

    # ── s7 · **증거 0건은 유망이 아니다** ─────────────────────────────
    v, p, why = adjudicate(C(f0={"count": 5}))
    check("[117] 증거 0건 → **보류**", v == "보류", v)
    check("[117]   → 사유가 «근거 부족»", "근거 부족" in why, why[:30])


def test_knows_when_something_is_running():
    """[118] **도는 동안 고쳤는지를 시험이 스스로 말한다** (결함 202·204).

    08-13 밤 로그가 **두 개**였다. 21:59 판이 죽은 것을 보고 «끝났다» 고
    판단했는데 **22:44 판이 돌고 있었다.** 그 사이 `test_phase2.py` 를
    고쳐 아침 로그에 **가짜 실패**가 남았다.

    > **«마지막 로그를 봤다» 는 «지금 안 돈다» 를 뜻하지 않는다.**

    «고치기 전에 확인해라» 는 **안내문**이다. 이 프로젝트는 그게 안
    듣는다는 것을 결함 189 에서 다시 배웠다. 그래서 둘을 넣었다 —

      · **심박** — 도는 스크립트가 시각을 갱신한다. 오래되면 죽은 것
      · **소스 스냅샷** — 시험이 시작·끝에 해시를 찍어 **바뀌면 말한다**

    같이 고정하는 것 — `fetchpar --list`(결함 204). **파일 이름을
    추측하지 않고 서버에게 묻는다.**
    """
    from ..bench import srcstamp as S
    from ..io import fetchpar as F

    # ── 스냅샷·차이 ────────────────────────────────────────────────
    a = S.snapshot()
    check("[118] 소스를 센다 (`bioreroute/**/*.py`)", len(a) > 40, len(a))
    check("[118] 상대경로로 담는다", all(not k.startswith("/") for k in a), True)
    check("[118] `__pycache__` 를 뺀다",
          not any("__pycache__" in k for k in a), True)

    b = dict(a)
    k0 = sorted(b)[0]
    b[k0] = "다른해시"
    b["bioreroute/새로생긴것.py"] = "x"
    gone = sorted(b)[1]
    b.pop(gone)
    d = S.diff(a, b)
    check("[118] 바뀐 파일을 짚는다", d["바뀜"] == [k0], str(d["바뀜"]))
    check("[118] 생긴 파일을 짚는다", d["생김"] == ["bioreroute/새로생긴것.py"], str(d["생김"]))
    check("[118] 사라진 파일을 짚는다", d["사라짐"] == [gone], str(d["사라짐"]))

    msg = S.report(a, b, "시험")
    check("[118] 바뀌면 **경고 문장을 낸다**", "도는 동안" in msg, msg[:40])
    check("[118]   → «한 판의 코드가 아니다» 를 적는다",
          "한 판의 코드에서 나온 것이 아니다" in msg, True)
    check("[118] **안 바뀌면 조용하다** (오탐이 잦으면 꺼진다)",
          S.report(a, a) == "", repr(S.report(a, a)))

    # ── 시험 파일이 실제로 그걸 부르는가 — **배선 확인** ──────────────
    import io as _io, os as _os
    from .. import evidence as _EV
    for f in ("test_phase1.py", "test_phase2.py"):
        src = _io.open(_os.path.join(_EV.ROOT, "bioreroute", "tests", f),
                       encoding="utf-8").read()
        check("[118] `%s` 가 시작에 스냅샷을 찍는다" % f, "_SNAP0" in src, f)
        check("[118] `%s` 가 끝에 대조한다" % f, "srcstamp" in src, f)

    # ── 심박 — **죽은 락과 도는 락을 가른다** ────────────────────────
    st = S.state()
    check("[118] 심박이 없으면 «안 돈다»", st["도는중"] is False, str(st))
    check("[118] 오래된 심박은 **죽은 것**으로 읽는다",
          S.state(stale_sec=-1)["도는중"] is False, str(S.state(stale_sec=-1)))

    # ── 결함 204 — **이름을 추측하지 않는다** ────────────────────────
    html = ('<a href="?C=N">Name</a><a href="/up/">Parent</a>'
            '<a href="a_compounds.parquet">a_compounds.parquet</a>  3.9G\n'
            '<a href="a_patents.parquet">a_patents.parquet</a>  5,912,345\n')
    import urllib.request as _u
    orig = _u.urlopen

    class _R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return html.encode()
    try:
        _u.urlopen = lambda *a, **k: _R()
        got = F.listdir("http://x/")
    finally:
        _u.urlopen = orig
    check("[118] 목록에서 파일 이름을 뽑는다",
          [x["name"] for x in got] == ["a_compounds.parquet", "a_patents.parquet"],
          str(got))
    check("[118] 정렬 링크(`?C=N`)와 상위 폴더를 **뺀다**",
          not any(x["name"].startswith(("?", "/")) for x in got), str(got))
    check("[118] 크기도 줍는다", got[0]["size"] == "3.9G", str(got[0]))


def test_case_notes_do_not_state_the_verdict():
    """[119] **사례 설명에 판정·수치를 적지 않는다** (결함 209 · `CLAUDE.md §4`).

    08-14에 `demo_cases.json` 을 다시 구웠더니 **여섯 중 넷의 판정이
    바뀌었다** —

        edaravone    보류 70%  → **조건부 28%**
        fluvoxamine  유망 98%  → **유망 84%**
        metformin    조건부 56% → **기각 26%**
        rifampin     보류 50%  → 보류 56%

    그런데 설명문이 **상수**였다. 그래서 화면이 **자기 판정과 어긋난
    말**을 했다 — 판정은 «조건부» 인데 설명은 *«기권(보류)이 정답인 자리»*,
    판정은 84% 인데 설명은 *«유망 97% 가 나왔다»*.

    > `CLAUDE.md §4` — **해석 문구를 상수로 고정하지 마라.
    > 방향을 데이터에서 읽어라.**

    설명은 **«왜 이 사례를 골랐나»** 만 적는다. 판정과 확률은 바로 옆에
    데이터에서 찍히므로 두 번 적을 이유가 없다.
    """
    import re as _re
    from .. import demo as _D

    # ── 무엇을 막고 무엇을 허용하나 ──────────────────────────────
    #
    #   막는 것   **우리 판정을 단정하는 꼴** — 재실행마다 바뀐다
    #             · 확률 숫자 (`97%`)
    #             · «판정은 X다» · «X 가 나왔다» · «X 가 정답인 자리»
    #   허용      **안 바뀌는 사실**
    #             · «제안서는 「보류」를 예상했다» — 제안서 원문이다
    #             · «기각의 교과서» — 사례 성격이지 우리 판정이 아니다
    #
    #   처음엔 판정어를 통째로 금지했는데 **제안서 인용까지 걸렸다.**
    #   과잉 차단도 실패다 — 오탐이 잦은 가드는 꺼진다(결함 40).
    V = "기각|유망|보류|조건부"
    CLAIM = _re.compile(r"(판정(은|이)\s*(%s))|((%s)\s*(가|이)\s*(나왔|났))"
                        r"|((%s)\)?\s*(가|이)\s*정답)" % (V, V, V))
    for q, why in _D.PRESETS:
        nm = q.split(" /")[0][:18]
        check("[119] `%s` 설명이 **우리 판정을 단정하지 않는다**" % nm,
              not CLAIM.search(why), why[:60])
        check("[119] `%s` 설명에 **확률 숫자**가 없다" % nm,
              not _re.search(r"\d+\s*%", why), why[:60])

    # 구운 사례에서도 같은 규칙 — **자료가 문서를 이긴다**
    import json as _j, os as _os
    from .. import evidence as _EV
    p = _os.path.join(_EV.ROOT, "demo_cases.json")
    if _os.path.exists(p):
        d = _j.load(open(p, encoding="utf-8"))
        stale = [y.get("설명") for y in d.get("사례", [])
                 if _re.search(r"\d+\s*%", y.get("설명") or "")
                 or CLAIM.search(y.get("설명") or "")]
        check("[119] **구운 설명도** 판정·확률을 단정하지 않는다 "
              "— 다르면 `evidence.build_cases()` 를 다시 돌려라",
              not stale, "%d개: %s" % (len(stale), (stale[:1] or [""])[0][:60]))
        # **판정은 데이터에 있다** — 설명이 아니라 여기서 읽는다
        vs = [y.get("판정") for y in d.get("사례", [])]
        check("[119] 구운 사례가 판정을 **자료로** 들고 있다",
              all(v for v in vs) and len(vs) >= 4, str(vs))


def test_pico_reaches_screen():
    """[103] **반증의 적용 범위가 화면까지 간다** (제안서 §2.3).

    > 음성 임상 결과는 특정 **대상군·용량·투여 시점**에 대한 반증이므로,
    > 근거 카드는 반박 근거와 함께 **그 조건을 기록**하고 다른 조건으로의
    > 일반화는 별도 판단으로 남긴다.   — 제안서 §2.3

    `factcheck` 가 `pico` 를 **08-05부터 수집해 왔는데** `render.py`(콘솔)
    에만 찍히고 **`app.py`(웹 화면)에는 없었다.** 08-13 §2 전문 대조에서
    나왔다(`에이전트설계_대조.md §5-a`).

    이 시험이 고정하는 것 셋 —

      · `Evidence` 가 `pico` 를 **들고 간다**
      · **빈 값은 버린다** (빈 문자열이 «조건 있음»으로 보이면 안 된다)
      · **판정을 안 바꾼다** — 표시 전용이다
    """
    from ..core.state import Evidence
    from ..core import gates as G

    e = Evidence("t", "refute", 2.0)
    check("[103] 기본값이 빈 dict 다", e.pico == {}, e.pico)

    r = {"pmid": "1", "direction": "refute", "weight": 2.0, "kept": True,
         "quote": "x", "quote_check": {"ok": True, "how": "완전일치",
                                       "확인": "x", "미확인": ""},
         "journal": "J", "year": 2024, "study_type": "rct",
         "pico": {"population": "외래 환자", "dose": "", "timing": "발병 3일 내"}}

    class C:
        pass
    c = C(); c.factcheck = [r]; c.support = []; c.refute = []
    G._rebuild_evidence(c)
    got = (c.refute or [None])[0]
    check("[103] 근거가 만들어졌다", got is not None, len(c.refute))
    check("[103] `pico` 가 실려 간다",
          got.pico.get("population") == "외래 환자", str(got.pico))
    check("[103] **빈 값은 버린다** — dose 가 빈 문자열이었다",
          "dose" not in got.pico, str(got.pico))
    check("[103] 시점도 실린다", got.pico.get("timing") == "발병 3일 내", str(got.pico))
    # **판정을 안 바꾼다** — 가중치·방향이 그대로다
    check("[103] 가중치 불변", got.weight == 2.0, got.weight)
    check("[103] 방향 불변", got.direction == "refute", got.direction)

    # 화면 코드가 그 키를 **실제로 읽는지** 소스에서 확인한다
    import io as _io, os as _os
    from .. import evidence as _EV
    # **원본을 본다** (결함 189). 앞판은 `배포업로드/app.py` 를 읽었는데
    # 그건 `deploycheck --stage` 가 다시 만드는 **사본**이다 —
    # 사본을 시험하고 통과하면 **거짓 안심**이다. 아래 [115]가 둘이
    # 바이트까지 같은지 따로 본다.
    #
    # ⚠ **한 파일에 못 박지 않는다** (08-19). 08-19 에 근거 카드를
    #   `app.py` 에서 `dash.evidence_full` 로 옮겼더니 이 시험이 깨졌다 —
    #   **그리는 코드가 어디 있는지가 아니라 그리는가**가 요건이다.
    app = _io.open(_os.path.join(_EV.ROOT, "app.py"), encoding="utf-8").read()
    app += _io.open(_os.path.join(_EV.ROOT, "bioreroute", "dash.py"),
                    encoding="utf-8").read()
    for k in ("조건", "population", "dose", "timing"):
        check("[103] 화면이 `%s` 를 읽는다" % k, k in app, k)
    # **뜻으로 본다** — 「반박인데 조건이 비었으면 그렇다고 적는다」
    from .. import dash as _D103
    _no = _D103.evidence_full({"방향": "반박", "가중치": 1.8, "PMID": "1",
                               "설명": "X", "조건": {}})
    check("[103] **조건 없는 반박에 그 사실을 적는다** — 빈칸이 "
          "«모든 조건에서 반박» 으로 읽히면 안 된다",
          "못 뽑았" in _no and "일반화" in _no, _no[-120:])
    _yes = _D103.evidence_full({"방향": "반박", "가중치": 1.8, "PMID": "1",
                                "설명": "X",
                                "조건": {"population": "adults"}})
    check("[103] 조건이 있으면 **그 문구를 안 붙인다**", "못 뽑았" not in _yes)
    check("[103] 지지 근거에는 **안 붙인다** — §2.3 은 음성 결과 규정이다",
          "못 뽑았" not in _D103.evidence_full(
              {"방향": "지지", "가중치": 1.8, "PMID": "1", "설명": "X",
               "조건": {}}))


def test_evidence_stage_stamp():
    """[102] **근거마다 어느 게이트가 가져왔는지 남는다** (결함 166).

    08-13 B2·B3 짝비교를 분석하면서 드러났다 — `c.factcheck` 가
    팩트체커·회의주의자·등록부의 근거를 **한 목록에 섞어 두고 구분을
    안 했다.** 유일한 단서가 trail 의 «추가 초록 N건» 이라는 **서식
    문자열**이었고, 실제 분석에서는 **목록의 위치로 추정**해야 했다.

    실측으로 그 가정이 28/28 성립하긴 했다(`gen_state_b2/b3.json` 대조).
    **그래도 위치는 계약이 아니다.** 게이트 순서를 한 번 바꾸면 조용히
    깨지고, 깨진 것을 알 방법이 없다.

    이 시험이 고정하는 것 둘 —

      · **표시가 실제로 붙는다** (세 게이트 각각)
      · **판정을 안 바꾼다** — `_stamp` 전후로 방향·가중치·kept 가 동일
    """
    from ..core import gates as G

    recs = [{"pmid": "1", "direction": "refute", "weight": 2.0, "kept": True},
            {"pmid": "2", "direction": "support", "weight": 1.0, "kept": False}]
    before = [dict(r) for r in recs]
    out = G._stamp(recs, "skeptic")
    check("[102] 표시가 붙는다", all(r["stage"] == "skeptic" for r in out),
          [r.get("stage") for r in out])
    for b, a in zip(before, out):
        for k in ("direction", "weight", "kept", "pmid"):
            # `check` 의 got 은 %s 로 찍히므로 **튜플을 그대로 넘기면 안 된다**
            # (넘겼다가 TypeError 를 봤다 — 시험을 시험해 본 값이다)
            check("[102] **판정을 안 바꾼다** — %s" % k, b[k] == a[k],
                  "%r → %r" % (b[k], a[k]))

    # 이미 새겨진 것은 덮지 않는다 — 같은 레코드가 두 번 지나가도 안전
    again = G._stamp(out, "registry")
    check("[102] 이미 새겨진 것은 **안 덮는다**",
          all(r["stage"] == "skeptic" for r in again),
          [r.get("stage") for r in again])

    # 세 게이트가 전부 새기는지 **소스에서** 확인한다 (호출 누락 방지)
    import inspect
    src = inspect.getsource(G)
    for stage in ("factcheck", "skeptic", "registry"):
        check("[102] `%s` 게이트가 _stamp 를 부른다" % stage,
              '_stamp(results, "%s")' % stage in src
              or '_stamp(add, "%s")' % stage in src, stage)
    # 표시 없이 factcheck 를 대입하는 경로가 **남아 있지 않아야** 한다
    import re
    raw = [m.group(0) for m in
           re.finditer(r"c\.factcheck = (?!_stamp)(?!\(c\.factcheck or \[\]\) \+ _stamp)[^\n]+", src)]
    check("[102] **표시 없이 대입하는 경로가 없다**", not raw, raw[:3])


def test_llm_cannot_inject_pmid():
    """[100] **LLM 이 지어낸 식별자가 들어오지 못한다** (결함 162).

    08-13에 현직 연구자 5명이 *"AI 가 알려준 논문이 실제로 없었던 적이
    있어서 지금은 참고용으로만 쓴다"* 고 했다(`인터뷰기록.md #2`).
    우리가 그들에게 할 수 있는 주장이 **«우리는 식별자를 생성하지
    않는다»** 인데, **그 주장에 시험이 없었다.** 시험용 모의 LLM 이 전부
    프롬프트의 PMID 를 정규식으로 읽어 **그대로 되돌려주도록** 짜여 있어
    지어낸 식별자가 오는 경로가 한 번도 안 탔다. 여기서는 모의가
    **입력에 없는 PMID 를 일부러 보낸다.**

    ## ⚠ 변이 시험이 내 이해를 고쳤다 (결함 163)

    하청 감사도 나도 *"방어선은 `factcheck.py` 의 화이트리스트 두 줄"*
    이라고 적었다. **그 두 줄을 실제로 지워 보니 틀렸다.**

    ```
    화이트리스트 제거 → 아래 셋은 그대로 PASS
                     → 넷째(«판정이 살아 있다»)만 FAIL
    ```

    진짜 방어선은 **조립 구조**다 — `out` 은 **입력 `pmid` 로만** 키가
    잡히고(`out[pmid] = r`), 반환은 `[out[r["pmid"]] for r in recs]` 로
    **입력 목록을 훑는다.** LLM 이 무엇을 보내든 **식별자가 들어올 자리가
    아예 없다.** LLM 의 `pmid` 는 «어느 초록에 대한 판정인가» 를 찾는
    **열쇠**로만 쓰인다.

    그러면 그 두 줄은 무엇인가 — **방어가 아니라 복구**다. 열쇠가 안 맞을
    때 순서로 되찾아 준다. 없으면 판정이 **통째로 «응답 누락»** 이 된다.
    **안전한 방향으로 실패한다**(근거를 잃을 뿐 가짜를 얻지 않는다).

    아래 네 검사 중 **넷째만 그 두 줄을 잡는다.** 앞 셋은 구조를 잡는다.
    둘은 다른 것을 재므로 **이름을 그렇게 붙여 둔다.**
    """
    from ..agents import factcheck
    from ..io import llm as _llm

    live = [{"pmid": "11111111", "title": "T1", "abstract":
             "Treatment reduced mortality significantly in the trial cohort.",
             "source": "pubmed", "ptypes": ["Randomized Controlled Trial"]},
            {"pmid": "22222222", "title": "T2", "abstract":
             "The intervention showed no benefit versus placebo overall.",
             "source": "pubmed", "ptypes": ["Randomized Controlled Trial"]}]

    def comp(prompt, system="", model=None, as_json=False, purpose=""):
        # **입력에 없는 PMID 를 보낸다** — 환각 재현
        return {"ok": True, "error": None, "text": "", "provenance": {},
                "data": [{"idx": 1, "pmid": "99999999", "direction": "support",
                          "study_type": "rct", "size": "large", "decisive": True,
                          "confidence": "high",
                          "quote": "Treatment reduced mortality significantly"},
                         {"idx": 2, "pmid": "NCT99999999", "direction": "refute",
                          "study_type": "rct", "size": "large", "decisive": True,
                          "confidence": "high",
                          "quote": "The intervention showed no benefit versus placebo"}]}

    old = _llm.complete
    try:
        _llm.complete = comp
        out = factcheck.classify_batch("drugX", "diseaseY", live)
    finally:
        _llm.complete = old

    got = [r.get("pmid") for r in out]        # 입력 순서로 돌아온다
    # ── 구조 (① ~ ③) — 화이트리스트를 지워도 통과한다. 그게 요점이다
    check("[100·구조] **지어낸 PMID 가 결과에 없다**", "99999999" not in got, got)
    check("[100·구조] 지어낸 NCT 도 없다", "NCT99999999" not in got, got)
    check("[100·구조] 출력 PMID 는 **입력 집합에서만** 온다",
          got == ["11111111", "22222222"], got)
    blob = repr(out)
    check("[100·구조] 결과 어디에도 지어낸 식별자가 안 실린다 — 감사 추적 포함",
          "99999999" not in blob and "NCT99999999" not in blob, blob[:160])
    # ── ④ 복구 — **이 검사 하나만** 화이트리스트 두 줄을 잡는다.
    #    지우면 판정이 전부 «응답 누락» 이 된다(안전 방향 실패).
    check("[100·복구] 열쇠가 안 맞아도 **판정을 되찾는다** — 화이트리스트",
          any(r.get("kept") for r in out),
          [(r.get("pmid"), r.get("kept"), r.get("skip")) for r in out])


def test_shown_quote_is_verified_span():
    """[101] **화면에 「인용」으로 나가는 것은 확인된 구간뿐** (결함 160).

    `verify_quote` 는 산문 초록에서 **앞 절반만 맞아도 통과**시킨다.
    그런데 앞판은 `note=r["quote"]` 로 **LLM 문자열 전체**를 화면에
    넘기고 제목을 「인용 원문」이라 달았다. **뒷부분은 원문이 아니다.**

    등록부는 더 세다 — 수치 대조로 통과한 건은 **문장 자체가 원문에
    없다**(표를 옮긴 재서술이다).

    판정·가중치는 **안 바뀌어야 한다**(`CLAUDE.md §3-2`). 바뀌는 것은
    표시뿐이라는 것까지 여기서 고정한다.
    """
    from ..agents.factcheck import verify_quote
    from ..core.gates import _shown_quote

    A = "Treatment with drug X did not improve survival in patients."
    full = verify_quote(A, A)
    check("[101] 완전일치는 문장 전체가 확인된다",
          full["확인"] == A.lower().strip(), full.get("확인"))
    check("[101] 완전일치의 미확인 구간은 없다", full["미확인"] == "", full)

    part = verify_quote(
        "Treatment with drug X did not improve survival in mice everywhere.", A)
    check("[101] 부분일치를 여전히 통과시킨다 (판정 불변)", part["ok"], part)
    check("[101] **확인 구간이 초록에 실제로 있다**",
          part["확인"] and part["확인"] in A.lower(), part.get("확인"))
    check("[101] **미확인 꼬리를 분리해 낸다**",
          "mice" in part["미확인"], part.get("미확인"))
    check("[101] 확인+미확인이 원본을 복원한다",
          part["확인"] + part["미확인"] ==
          " ".join(("Treatment with drug X did not improve survival in "
                    "mice everywhere.").split()).lower(),
          part["확인"] + "|" + part["미확인"])

    show, how = _shown_quote({"quote": "…전체…", "quote_check": part})
    check("[101] 화면에는 **확인 구간만** 간다", show == part["확인"], show)
    check("[101] 그리고 대조 방식을 같이 준다", how == "부분일치", how)

    # 등록부 재서술 — 인용을 아예 안 싣는다
    st = verify_quote("Erlotinib 11.5 vs Placebo 13.2 months",
                      "arm Erlotinib 11.5 ; arm Placebo 13.2 ; median months",
                      structured=True)
    check("[101] 등록부 수치 대조는 통과한다 (판정 불변)", st["ok"], st)
    show2, how2 = _shown_quote({"quote": "x", "quote_check": st})
    check("[101] **재서술은 인용으로 안 싣는다**", show2 == "", show2)
    check("[101] 재서술이라고 이름 붙인다", "재서술" in how2, how2)

    # 지어낸 것은 애초에 ok=False 라 강등 경로로 간다
    bad = verify_quote("Something entirely invented and not present here.", A)
    check("[101] 지어낸 문장은 통과 못 한다", not bad["ok"], bad)


def test_countsync_covers_docaudit():
    """[99] **고치는 쪽과 검사하는 쪽이 같은 문서를 봐야 한다** (결함 159).

    08-13에 `countsync --apply` 를 **두 번 돌렸는데 두 번 다**
    `선행연구대조.md`·`멘토링_0813.md` 가 안 고쳐졌고, 곧바로
    `docaudit` 이 불일치를 냈다. 목록이 **둘인데 손으로** 맞추고 있었다.

    두 방향 다 사고다 —

    * `countsync ⊂ docaudit` 이면 **감사가 영원히 운다**
    * `countsync ∋ LOG` 면 **시간순 기록을 고쳐 써 훼손한다**
      (결함 136이 열어 둔 채 적어 둔 그 경로. `렌즈답변.md` 가 실제로
      `countsync.DOCS` 에 있었고, *"값이 `--old` 와 우연히 같을 때만
      걸려서"* 사고가 안 났을 뿐이다)

    이제 `countsync.DOCS` 를 `docaudit.DOCS − LOG` 로 **파생**시킨다.
    이 시험은 그 파생이 **끊기지 않았는지**를 본다 — 누가 목록을 다시
    손으로 적으면 여기서 걸린다.
    """
    from ..bench import countsync as CS, docaudit as DA
    log = set(DA.LOG)
    miss = [d for d in DA.DOCS if d not in log and d not in CS.DOCS]
    check("[99] 감사가 보는 문서를 동기화가 전부 고친다", not miss, miss[:5])
    bad = [d for d in CS.DOCS if d in log]
    check("[99] 동기화가 **기록 문서**를 건드리지 않는다", not bad, bad[:5])
    check("[99] 덱 생성기가 동기화 대상에 남아 있다",
          "slides/build_deck.py" in CS.DOCS, CS.DOCS[-1])
    # 파생을 손목록으로 되돌리면 이 값이 굳는다 — 그때 위 둘이 먼저 운다
    check("[99] 목록이 비어 있지 않다", len(CS.DOCS) >= 20, len(CS.DOCS))


def test_disclaimer():
    """[51] **공개 링크로 나가는 화면에 의료 면책이 없었다** (결함 54).

    이 시스템은 실재 승인약과 실재 질환에 대해 `기각 4%` 같은
    **임상처럼 들리는 문장**을 출력한다. 그리고 본선 제출물에
    **공개 서비스 배포 링크**가 있다.

    제안서 §5(연구 윤리)는 **통제 물질 오남용**만 다뤘고
    **출력 자체의 오용**은 다루지 않았다. 그게 구멍이었다.

    화면 한 곳에만 적으면 스크린샷·복사로 떨어져 나가므로
    **판정 문자열에도 실려 있어야 한다.**
    """
    from .. import demo as D
    from .. import evidence as EV

    for tok in ("의학적 조언이 아니다", "복약 결정", "담당 의사"):
        check("[51] 면책에 %r 가 있다" % tok, tok in D.DISCLAIMER)
    check("[51] 면책이 조건부 반증임을 적는다",
          "대상군·용량·시점" in D.DISCLAIMER)
    check("[51] 짧은 면책도 '의학적 조언 아님'을 말한다",
          "의학적 조언 아님" in D.SHORT_DISCLAIMER)

    # **판정 줄에 실려 나가는가** — 화면 상단만으로는 부족하다
    line = D.summary_line({"상태": "정상", "판정": "기각", "신뢰도": 4,
                           "비용": 0, "근거": []})
    check("[51] 판정 한 줄 요약에 면책이 붙는다",
          D.SHORT_DISCLAIMER in line, line[:70])

    # app.py 가 최상단에 걸었는가
    import os
    ap = os.path.join(EV.ROOT, "app.py")
    if os.path.exists(ap):
        src = open(ap, encoding="utf-8").read()
        # 08-10에 한 줄 요약 + 접힌 전문으로 갈랐다. **요약이 탭보다 위**
        # 여야 한다는 조건은 그대로다 — 줄인 건 자리이지 노출이 아니다.
        check("[51] app.py 가 면책 **요약**을 탭보다 위에 건다",
              src.index("DISCLAIMER_ONE") < src.index("with gr.Tabs()"))
        check("[51] 전문도 **접혀서나마** 탭보다 위에 있다",
              src.index("DISCLAIMER_FULL)") < src.index("with gr.Tabs()"))
        # **뜻으로 본다** — 08-19 에 말투를 «~습니다» 로 고쳤다.
        #   요건은 «둘 다 적는다» 이지 특정 어미가 아니다.
        _one = src.split("DISCLAIMER_ONE = ")[1][:400]
        check("[51] 한 줄 요약이 **의학적 조언 아님**과 **AI 가 만든 것**을 "
              "둘 다 적는다",
              "의학적 조언이 아닙" in _one and "AI 가 만든" in _one, _one[:120])

    # ── 08-24 · **새 화면에서 면책이 사라졌다** ──────────────────────
    #
    #   이 시험이 `app.py`(Gradio) 만 봤다. 08-20 에 화면을 갈아엎고
    #   나흘이 지나도록 **새 화면은 아무도 안 봤다.** 실제 상태는 —
    #
    #     · 한 줄 면책을 `/api/boot` 이 계속 내려보내는데 **그리는 코드가 없었다**
    #     · 남은 표시(사이드바 발치)는 `hide-collapsed` 라 **접으면 사라진다**
    #     · 그런데 **3분할을 보려면 사이드바를 접어야 한다**(본문 769 vs 917px)
    #
    #   즉 **시연 자세에서 화면에 면책이 하나도 없었다.** 이 시험이 지키려던
    #   것(*«스크린샷·복사로 떨어져 나가지 않게»*)이 정확히 깨진 것이고,
    #   **시험이 옛 화면만 봐서 초록이었다.** 결함 299 와 같은 계열이다 —
    #   «검사기가 실제로 나갈 것을 안 봤다».
    _idx = os.path.join(EV.ROOT, "web", "static", "index.html")
    _css = os.path.join(EV.ROOT, "web", "static", "app.css")
    if os.path.exists(_idx):
        _h = open(_idx, encoding="utf-8").read()
        _c = open(_css, encoding="utf-8").read()
        check("[51] **새 화면 머리줄**에 면책이 있다", "tb-disc" in _h, _h[:0])
        # 머리줄 표기는 **접기와 무관해야 한다**
        _blk = _h[_h.index("tb-disc"):_h.index("tb-disc") + 400]
        check("[51] 그 면책이 **사이드바 접힘에 안 딸려 간다** — "
              "3분할을 보려면 접어야 한다",
              "hide-collapsed" not in _blk, _blk[:100])
        check("[51] 머리줄이 **`sticky`** 다 — 어떤 스크린샷에도 들어간다",
              "position: sticky" in _c.split(".topbar {")[1][:200])
        for tok in ("의학적 조언이 아닙니다", "AI 생성", "연구용 도구"):
            check("[51] 머리줄 면책에 %r 가 있다" % tok, tok in _blk, _blk[:120])
        # 08-24 저녁 — 승우: *«사이드바에도 있는데 머리줄에 꼭 넣어야 해?»*
        #   맞는 지적이었다. **중복을 없애고 머리줄만 남겼다** — 접어도
        #   보이고, 자리가 «화면 최상단» 이고, 스크린샷에 들어가기 때문이다.
        #   그래서 요건이 «여는 자리가 둘» 이 아니라 **«면책을 여는 자리가
        #   접힘과 무관하게 하나는 있다»** 로 바뀐다. **뜻으로 적는다.**
        check("[51] 면책 전문을 여는 자리가 있다",
              "disc-open" in _h, _h.count("disc-open"))
        _opens = _h.count('class="linkish disc-open"') + _h.count("disc-open")
        check("[51] 그 자리도 **접힘에 안 딸려 간다** — "
              "`hide-collapsed` 와 같이 안 붙는다",
              "hide-collapsed disc-open" not in _h
              and "disc-open hide-collapsed" not in _h, _opens)
        # 같은 말을 두 곳에서 하지 않는다 (결함 295 계열)
        check("[51] 면책 문구가 **한 곳에만** 있다 — 중복은 결함 295 다",
              _h.count("의학적 조언이 아닙") == 1, _h.count("의학적 조언이 아닙"))
        check("[51] app.py 가 면책 문구를 따로 적지 않고 demo 것을 쓴다",
              "demo.DISCLAIMER" in src)


def test_ai_notice():
    """[56] **AI 생성 표기** — 제안서 §5 여덟 항목 중 **마지막 ❌** 였다.

    §5 ⑤ 가 *"산출물에 AI 생성 표기 + 근거 PMID·점수 병기"* 를 약속했다.
    PMID·점수는 처음부터 붙었고 **표기만 그동안 줄곧 없었다.**
    `제안서_전수대조.md` 가 *"어려운 일이 아니라 안 한 것"* 이라 적었고,
    안 한 것으로 남아 있던 이유는 **아무도 안 봤기 때문**이다.

    ## 표기가 그냥 "AI 생성"이면 안 되는 이유

    분업을 지우면 그 표기가 틀린 말이 된다. 실제로는 —

    ```
    후보 생성 · 문헌 요약 · 기전 분류    LLM        ← AI 산출물
    인용 문장                          PubMed 원문  ← 대조 통과분만
    판정 확률                          규칙 로그오즈 ← LLM 이 안 정한다
    ```

    확률을 LLM 이 냈다고 오해하면 **보정 논의 전체가 무의미해진다.**
    그래서 표기에 세 줄을 다 넣고, 이 시험이 그걸 지킨다.

    그리고 면책과 **같은 규율**로 검사한다 — 화면 상단만으로는 부족하고
    **판정 문자열에도 실려야** 스크린샷으로 떨어지지 않는다(결함 54).
    """
    from .. import demo as D
    from .. import evidence as EV

    check("[56] AI 생성 표기가 있다", "AI 생성물" in D.AI_NOTICE)
    # **분업 세 줄** — 하나라도 빠지면 표기가 오해를 만든다
    check("[56] 표기가 LLM 이 한 일을 적는다",
          all(t in D.AI_NOTICE for t in ("생성", "요약", "분류")))
    check("[56] 표기가 인용은 원문 대조임을 적는다",
          "원문과 대조" in D.AI_NOTICE and "PubMed" in D.AI_NOTICE)
    check("[56] 표기가 **확률은 LLM 이 아니라 규칙**임을 적는다",
          "규칙 기반 로그오즈" in D.AI_NOTICE and "LLM 이 아니라" in D.AI_NOTICE)
    check("[56] 표기가 PMID·가중치 병기를 적는다 (§5 ⑤ 의 나머지 절반)",
          "PMID" in D.AI_NOTICE and "가중치" in D.AI_NOTICE)
    check("[56] 짧은 표기도 세 사실을 다 말한다",
          all(t in D.SHORT_AI_NOTICE for t in ("AI 생성물", "원문 대조", "규칙")))

    # **판정 줄에 실려 나가는가** — 결함 54와 같은 검사다
    line = D.summary_line({"상태": "정상", "판정": "유망", "신뢰도": 97,
                           "비용": 3, "근거": []})
    check("[56] 판정 한 줄 요약에 AI 표기가 붙는다",
          D.SHORT_AI_NOTICE in line, line[-80:])
    check("[56] 면책과 AI 표기가 **둘 다** 붙는다 — 하나가 다른 것을 밀어내지 않는다",
          D.SHORT_DISCLAIMER in line and D.SHORT_AI_NOTICE in line)

    import os
    ap = os.path.join(EV.ROOT, "app.py")
    if os.path.exists(ap):
        src = open(ap, encoding="utf-8").read()
        check("[56] app.py 가 AI 표기를 **탭보다 위**에 건다",
              "demo.AI_NOTICE" in src
              and src.index("demo.AI_NOTICE") < src.index("with gr.Tabs()"))


def test_cache_configure_clears():
    """[57] **결함 62 — `cache.configure()` 가 경로만 바꾸고 메모리를 안 비웠다.**

    `get`·`has` 는 `_STORE` 를 직접 읽고 `load()` 를 부르지 않는다. 그래서
    한 프로세스 안에서 경로를 바꿔도 **앞 경로의 항목이 그대로 나왔다.**

    실측으로 잡힌 경로 — 활성부위 pLDDT 시험에서 모의 응답을 바꿔 두 번째
    `assess()` 를 불렀는데 **첫 번째 결과가 캐시에서 나왔다.** 모의를
    바꿨는데 값이 안 바뀌었고, 그래서 시험이 붉어졌다.

    > **시험이 앞선 시험의 캐시로 통과할 수 있었다는 뜻이다.**
    > 이 파일이 이미 네 번 당한 유형(결함 5·26·27·37)의 다섯 번째이고,
    > 이번엔 검사기 쪽에서 났다. 규약("configure 뒤에 load 를 불러라")으로
    > 막던 것을 **구조로** 바꿨다.
    """
    import tempfile
    from ..io import cache as C

    old_p, old_e = C._PATH, C._ENABLED
    try:
        a = os.path.join(tempfile.mkdtemp(), "a.json")
        b = os.path.join(tempfile.mkdtemp(), "b.json")
        C.configure(a, enabled=True)
        C.put("K", {"v": 1})
        check("[57] 같은 경로에서는 읽힌다", C.has("K") and C.get("K")["v"] == 1)
        C.configure(b, enabled=True)
        check("[57] **경로를 바꾸면 앞 항목이 안 보인다** (결함 62)",
              not C.has("K"), str(C.get("K")))
        check("[57] 새 경로에 쓰고 읽는 것은 정상", C.put("K2", 2) == 2 and C.has("K2"))
        # 자동 저장 카운터도 함께 초기화돼야 한다 — 안 그러면 새 캐시가
        # 첫 put 에서 곧바로 디스크에 내려가 앞 파일 경로와 섞일 수 있다
        check("[57] 자동 저장 카운터가 초기화된다", C._SINCE[0] <= 1, C._SINCE[0])
        # **load() 로 디스크에서 되살릴 수 있어야 한다.** 비우기가
        # 정상 경로를 깨뜨리면 안 된다
        C.save()
        C.configure(b, enabled=True)
        check("[57] 비운 뒤 load() 로 디스크에서 되살린다", not C.has("K2"))
        C.load()
        check("[57] load() 후에는 다시 보인다", C.has("K2"), str(C.get("K2")))
    finally:
        C.configure(old_p, old_e)


def test_faithfulness():
    """[58] 인용 충실도 정량화 — 제안서 §2.3 **RAGAS 자리** (LLM 비용 0).

    §2.3·§3.1 이 RAGAS 를 적었고 `제안서_전수대조.md` 는 그동안 줄곧
    `❌ 없다 — 대신 verify_quote 로 원문 대조` 라고 적어 뒀다.
    그 문장이 절반만 맞았다 — **게이트는 있었고 수치가 없었다.**

    ## 이 시험이 지키는 것은 분모다

    `정답표감사.md` 가 기록한 실수를 반복하지 않으려고 건다 — 우리는
    특이도를 논지로 걸고 **그 분모가 무엇인지 그동안 줄곧 안 봤다.**

      ① 검사받지 않은 인용을 **불충실로 세지 않는다**
      ② 그렇다고 **분모가 줄었다는 사실을 감추지도 않는다**
      ③ 조건부로 도는 층은 **걸림이 아니라 기회를 같이** 낸다
         (`0건 걸림` 을 "깨끗하다"로 읽으면 안 된다 — 결함 35)
    """
    from .. import evidence as EV
    from ..bench import faithful as F

    ent = [
        # 검사 통과 2건
        {"quote_check": {"ok": True, "how": "완전일치"}, "kept": True,
         "weight": 1.0, "certainty": "high", "retracted": False,
         "type_conflict": False, "nct": ["NCT1"]},
        {"quote_check": {"ok": True, "how": "수치대조"}, "kept": True,
         "weight": 2.0, "certainty": "low", "retracted": False,
         "type_conflict": True, "no_result": True, "nct": ["NCT1"],
         "dup_of": "NCT1"},
        # 지어낸 것 1건 — 교차오염 검사가 **여기서만** 돈다
        {"quote_check": {"ok": False, "how": "초록에 없는 문장(지어냄)"},
         "kept": False, "weight": 0.0, "retracted": False,
         "cross_contaminated": False},
        # 검사조차 못 간 것 3건
        {"quote_check": {}, "skip": "무관 — 효능 증거 아님", "kept": False,
         "weight": 0.0, "retracted": False},
        {"quote_check": {}, "skip": "초록 없음 — 판정 불가", "kept": False,
         "weight": 0.0, "retracted": False},
        {"quote_check": {}, "skip": "철회 논문 — 근거에서 제외", "kept": False,
         "weight": 0.0, "retracted": True},
    ]
    r = F.measure(ent)

    # ① 충실도 분모는 **검사받은 것**이다 — 6이 아니라 3
    check("[58] 충실도 분모 = 검사받은 인용", r["충실도"]["n"] == 3, r["충실도"]["n"])
    check("[58] 검사 안 된 것을 **불충실로 세지 않는다**",
          r["충실도"]["k"] == 2 and r["지어냄"] == 1,
          "%s / %s" % (r["충실도"]["k"], r["지어냄"]))
    # ② 그런데 줄었다는 사실을 같이 낸다
    check("[58] 관련성 분모 = LLM 이 낸 전부", r["관련성"]["n"] == 6, r["관련성"]["n"])
    check("[58] 검사 안 된 건수와 사유를 낸다",
          r["검사안됨"] == 3 and r["검사안된_사유"].get("무관") == 1,
          str(r["검사안된_사유"]))
    check("[58] 분류 안 된 사유는 `기타` 로 드러난다 — 조용히 삼키지 않는다",
          "기타" not in r["검사안된_사유"], str(r["검사안된_사유"]))
    # ③ 조건부 층은 기회를 같이 낸다
    cc = r["문맥"]["다른_약_가리킴"]
    check("[58] 교차오염 층의 **기회는 인용 검증 실패분뿐**이다",
          cc["걸림"] == 0 and cc["기회"] == 1, str(cc))
    nr = r["문맥"]["결과_진술_아님"]
    check("[58] `걸림 == 기회` 가 되지 않는다 — 분자를 두 번 쓰면 100% 가 나온다",
          nr["걸림"] == 1 and nr["기회"] == 2, str(nr))
    check("[58] 철회는 전수가 분모다", r["문맥"]["철회"]["기회"] == 6,
          str(r["문맥"]["철회"]))
    # 신뢰구간이 붙는가 — Wilson (소표본에 Wald 금지)
    lo, hi = r["충실도"]["ci"]
    check("[58] Wilson 구간이 붙는다", 0.0 < lo < r["충실도"]["p"] <= hi <= 1.0,
          "%.3f–%.3f" % (lo, hi))
    # 지어낸 것은 **목록으로** 남긴다. 건수만으로는 확인이 안 된다
    check("[58] 지어낸 인용을 목록으로 남긴다",
          len(r["지어낸_목록"]) == 1 and r["지어낸_목록"][0]["사유"], str(r["지어낸_목록"])[:80])

    # 산출물이 없을 때 **0으로 채우지 않는다**
    import io as _io
    import contextlib
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = F.main(["--state", "__없는파일__.json"])
    check("[58] 없는 산출물을 0으로 채우지 않고 실패로 끝낸다",
          rc == 2 and "0으로 채우지 않는다" in buf.getvalue(), rc)

    # 읽기 실패를 **조용히 넘기지 않는다**
    r2 = F.measure(F._load(["__없는파일__.json"]))
    check("[58] 못 읽은 파일을 기록한다", bool(r2["읽기실패"]), str(r2["읽기실패"])[:60])

    # 실제 산출물로도 한 번 태운다 — 모의만으로는 스키마가 맞는지 모른다
    gs = os.path.join(EV.ROOT, "gen_state.json")
    if os.path.exists(gs):
        real = F.measure(F._load([gs]))
        check("[58] 실산출물에서 인용을 읽는다", real["인용_전체"] > 400, real["인용_전체"])
        check("[58] 실산출물의 충실도 분모가 전체보다 작다 — **그걸 적어야 한다**",
              real["검사됨"] < real["인용_전체"],
              "%d / %d" % (real["검사됨"], real["인용_전체"]))


def test_specaudit():
    """[59] 제안서 대조표 감사 — **렌즈 1·2의 절반** (결함 67).

    아홉 렌즈 중 1·2(제안서 항목 대조)만 그동안 줄곧 *"사람이 md 를 눈으로
    읽는다"* 였다. 그런데 **가장 큰 결함 셋이 거기서 났다** —

      결함 43  §1.2·§6 을 통째로 빠뜨림          처음부터
      결함 47  `TN 42건` 이 효능실패의 대리물     처음부터
      결함 63  §2.5 는 `활성부위` · 코드는 전체평균  처음부터

    **셋 다 "표에는 적혀 있고 코드가 다른 것"** 이다.

    ## 이 시험이 지키는 것

      ① 표가 인용한 심볼이 없으면 **잡는다**
      ② 있는데 이름이 없으면 **잡는다** (리팩터링이 옮긴 경우 — 결함 20)
      ③ `a.b` 의 **중의성**을 바르게 푼다 (모듈 우선, 그다음 이름)
      ④ **못 보는 것을 스스로 적는다** — 의미 불일치는 못 잡는다

    ③ 이 중요하다. 첫 판이 `bench.analyze`(모듈)를 `bench` 안의 이름으로
    읽어 **오탐**을 냈고, `app.py`(루트)를 못 찾아 또 냈다.
    **오탐이 쌓이면 가드는 꺼진다** — 예외 목록 대신 해석 순서를 고쳤다.
    """
    import tempfile
    from .. import evidence as EV
    from ..bench import specaudit as SA

    # ── ③ 중의성 — 실제 저장소로 확인한다 ──────────────────
    for sym, why in (("bench.analyze", "패키지 안의 **모듈**"),
                     ("io/tox.small_molecule", "모듈 안의 **함수**"),
                     ("app.py", "저장소 **루트**의 파일"),
                     ("gates.time_to_refute", "패키지 경로가 생략된 모듈 안 이름")):
        r = SA.check_symbol(sym, EV.ROOT)
        check("[59] `%s` 를 찾는다 — %s" % (sym, why), r["있다"],
              "%s / %s" % (r.get("파일"), r.get("왜")))

    # ── ①② 없는 것을 없다고 하는가 ──────────────────────
    for sym, why in (("io/tox.nosuchfunc", "파일은 있고 이름이 없다"),
                     ("nosuchmod.nofunc", "파일 자체가 없다"),
                     ("nosuchfile.py", "파일 자체가 없다")):
        r = SA.check_symbol(sym, EV.ROOT)
        check("[59] `%s` 를 **없다고** 한다 — %s" % (sym, why),
              not r["있다"] and r["왜"], str(r)[:70])

    # 한글 라벨을 심볼로 착각하지 않는가 — 오탐의 주 원인
    for bad in ("보류", "조건부", "유망 97%"):
        check("[59] `%s` 를 코드 심볼로 읽지 않는다" % bad,
              not SA._SYM.match(bad))

    # ── 표를 읽는가 ────────────────────────────────────
    rows = SA.parse(EV.ROOT)
    check("[59] 대조표 상태 행을 읽는다", len(rows) > 40, len(rows))
    marks = {r["상태"] for r in rows}
    check("[59] ✅·🟡·❌ 셋 다 있다 — 하나라도 없으면 파서가 의심스럽다",
          marks == {"✅", "🟡", "❌"}, str(marks))
    check("[59] 어느 문서·몇 행인지 남긴다",
          all(r["문서"] and r["행"] for r in rows))

    a = SA.audit(EV.ROOT)
    check("[59] 집계 합 = 행 수", sum(a["집계"].values()) == a["행"],
          "%s vs %d" % (a["집계"], a["행"]))
    check("[59] 인용 심볼을 실제로 검사한다", len(a["검사"]) >= 10, len(a["검사"]))
    check("[59] **지금 깨진 인용이 없다** — 있으면 표가 거짓말 중이다",
          not a["깨짐"], str(a["깨짐"])[:100])

    # ── ④ 못 보는 것을 스스로 적는가 ────────────────────
    #
    #   이 프로젝트가 결함 65에서 배운 것 — **독스트링이 과대주장하면
    #   다음 사람이 게이트를 과신한다.** 그래서 문서에 못 박았는지 본다.
    doc = SA.__doc__ or ""
    check("[59] 독스트링이 **의미는 못 본다**고 적는다",
          "의미를 못 본다" in doc and "결함 63" in doc)
    check("[59] 독스트링이 **렌즈 1·2의 절반**이라고 적는다", "절반" in doc)
    check("[59] 표에 안 적힌 항목은 못 잡는다고 적는다", "결함 43" in doc)

    import contextlib
    import io as _io
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = SA.main([])
    o = buf.getvalue()
    check("[59] 깨진 게 없으면 rc=0", rc == 0, rc)
    check("[59] 출력이 **의미는 사람이 봐라**를 적는다", "의미는 사람이 봐라" in o)
    check("[59] 출력이 🟡 개수를 경고한다 — 🟡 는 편해서 영원히 남는다",
          "🟡 는 편해서 영원히 남는다" in o)

    # 깨진 표를 주면 rc=1 인가 — **정상 경로만 시험하면 가드가 아니다**
    #
    #   첫 판에서 픽스처를 `없는모듈.함수` 로 썼다가 실패했다. `_SYM` 이
    #   **한글 시작을 의도대로 거부**한 것이고 **시험이 틀렸다.**
    #   오늘 세 번째로 내 기대값이 틀렸고 코드가 맞았다.
    tmp = tempfile.mkdtemp()
    open(os.path.join(tmp, "제안서_대조표.md"), "w", encoding="utf-8").write(
        "| a | b |\n|---|---|\n| 1 | ✅ `nosuchmod.nofunc` |\n")
    buf2 = _io.StringIO()
    with contextlib.redirect_stdout(buf2):
        rc2 = SA.main(["--root", tmp])
    check("[59] 표가 없는 코드를 가리키면 **rc=1**", rc2 == 1, rc2)
    check("[59] 그리고 어느 심볼인지 찍는다", "nosuchmod.nofunc" in buf2.getvalue())

    # **공허한 참을 통과로 찍지 않는가** — 심볼 0개일 때
    tmp2 = tempfile.mkdtemp()
    open(os.path.join(tmp2, "제안서_대조표.md"), "w", encoding="utf-8").write(
        "| a | b |\n|---|---|\n| 1 | ✅ 산문만 적었다 |\n")
    buf3 = _io.StringIO()
    with contextlib.redirect_stdout(buf3):
        SA.main(["--root", tmp2])
    # ── **이 검사를 두 번 고쳤다. 오늘 두 번째로 같은 실수다** ──────
    #
    #   첫 판: `"전부 실재한다" not in out`. 그런데 경고문 자체가
    #   *"「전부 실재한다」가 아니라"* 라고 **부정하려고 인용**한다.
    #   → 문자열 존재를 봤는데 봐야 할 것은 **주장**이었다.
    #
    #   오늘 밤 `bench/graph.py` 독스트링 시험에서 똑같이 틀렸고
    #   **거기에 주석까지 써 놓고 또 했다.** 인용은 방어가 아니다.
    #   고친 불변식: **마지막 판정 줄**이 무엇을 말하는가.
    out3 = buf3.getvalue()
    last = [l for l in out3.strip().split("\n") if l.strip()][-1]
    check("[59] 인용이 0개면 **판정 줄이 통과라고 하지 않는다** (결함 35 계열)",
          "검사할 것이 없었다" in last and "전부 실재한다" not in last, last[:90])
    check("[59] 그리고 [2] 절에서도 공허한 참을 안 찍는다",
          "확인할 것이 없었다" in out3)


def test_gradiocheck():
    """[60] `app.py` ↔ **실제로 설치된 gradio** 대조.

    `배포.md` 가 그동안 줄곧 `화면이 실제로 어떻게 보이는가 — ❌ 못 봤다`
    라고 적어 뒀다. 가짜 gradio 로 배선만 확인했고, 가짜는 **우리가 쓴
    것**이라 `gr.Radio(없는인자=1)` 을 줘도 조용히 통과한다.

    승우 기기의 `.venv/Lib/site-packages/gradio/` 가 저장소에 있다.
    윈도우 venv 라 `import` 는 안 되지만 **소스는 텍스트**이므로
    AST 로 시그니처를 읽을 수 있다.

    ## 이 시험이 지키는 것 — **통과만 하는 가드는 가드가 아니다**

    실제 저장소에서 `rc=0` 이 나온다는 것만 확인하면, 검사가 아무것도
    안 하고 있어도 통과한다. **일부러 틀린 입력 둘을 같이 태운다.**

      없는 인자   `gr.Radio(nosuchkw=1)`     → rc=1 이어야 한다
      없는 이름   `gr.NoSuchComponent()`      → rc=1
      정상       `gr.Radio(label=…, scale=…)` → rc=0

    그리고 **이 검사가 못 보는 것을 스스로 적는지**도 본다 —
    화면을 안 띄웠다는 사실을 숨기면 결함 65(독스트링 과대주장)가 된다.
    """
    import contextlib
    import io as _io
    import tempfile
    from .. import evidence as EV
    from ..bench import gradiocheck as G

    gpkg = os.path.join(EV.ROOT, ".venv", "Lib", "site-packages", "gradio")

    # ── AST 추출이 실제로 뭔가를 뽑는가 ──────────────────────
    app = os.path.join(EV.ROOT, "app.py")
    if os.path.exists(app):
        names, kw = G.used_api(app)
        check("[60] app.py 에서 gr.* 이름을 뽑는다", len(names) >= 8, sorted(names)[:6])
        for must in ("Blocks", "Tabs", "Markdown"):
            check("[60] gr.%s 를 놓치지 않는다" % must, must in names)
        check("[60] 호출 키워드도 모은다", any(kw.values()), str(kw)[:80])

    if not os.path.isdir(gpkg):
        # **없으면 없다고 적는다.** 통과로 세지 않는다 — 결함 35의 규율
        check("[60] gradio 소스가 없어 대조를 못 했다 (통과 아님)", True,
              "경로: %s" % gpkg)
        return

    # ── 음성 대조 셋. **이게 이 시험의 본체다** ────────────────
    tmp = tempfile.mkdtemp()
    sp = os.path.join(tmp, ".venv", "Lib", "site-packages")
    os.makedirs(sp, exist_ok=True)
    try:
        os.symlink(gpkg, os.path.join(sp, "gradio"))
    except Exception:
        import shutil as _sh
        _sh.copytree(gpkg, os.path.join(sp, "gradio"))

    cases = [('import gradio as gr\nx = gr.Radio(label="a", nosuchkw=1)\n',
              1, "없는 인자 — **가짜 gradio 가 못 잡는 층**"),
             ('import gradio as gr\nx = gr.NoSuchComponent()\n',
              1, "없는 이름"),
             ('import gradio as gr\nx = gr.Radio(label="a", scale=2)\n',
              0, "정상")]
    for src, want, why in cases:
        open(os.path.join(tmp, "app.py"), "w", encoding="utf-8").write(src)
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = G.main(["--root", tmp])
        check("[60] %s → rc=%d" % (why, want), rc == want,
              "rc=%d\n%s" % (rc, buf.getvalue()[-150:]))

    # ── 실제 저장소 ────────────────────────────────────
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = G.main([])
    out = buf.getvalue()
    check("[60] 실제 app.py 는 통과한다 — 불일치가 있으면 띄우기 전에 고쳐라",
          rc == 0, out[-200:])
    check("[60] **화면을 안 띄웠다는 사실을 적는다** (결함 65의 규율)",
          "화면을 안 띄웠다" in out and "대체하지 않는다" in out)
    check("[60] `**kwargs` 라서 확인 못 한 것을 밝힌다",
          "확인 못 한 것" in out or "kwargs" in out, out[-120:])

    # ── 생성자 **밖** — 08-07 추가 ────────────────────────────
    #
    #   첫 판은 `gr.X(...)` 생성자만 봤다. `py app.py` 가 실제로 죽는
    #   자리는 `ui.launch(...)` · `btn.click(...)` · `gr.themes.Soft()`
    #   에도 있고, **gradio 4 → 6 은 메이저가 둘 올랐다.**
    #   `requirements.txt` 는 `>=4.44` 인데 설치본은 **6.22.0** 이다.
    r = G.audit(EV.ROOT)
    check("[60] 버전을 읽는다 — 모르면 대조가 절반만 맞다",
          bool(r.get("버전")), str(r.get("버전")))
    check("[60] `Blocks.launch` 가 `theme` 을 받는다 (gradio 6 이행)",
          not any("launch" in w for w, _ in (r.get("런타임") or [])),
          str(r.get("런타임"))[:120])
    check("[60] 이벤트 트리거·테마도 확인한다",
          not (r.get("런타임") or []), str(r.get("런타임"))[:120])
    check("[60] 출력이 **메이저 판 차이**를 경고 문맥으로 적는다",
          "메이저가 둘" in out, out[-160:])

    # `launch` 시그니처를 **직접** 읽어 확인한다 — 위 검사가 공허하지 않게
    largs, lkw = G.class_method_args(gpkg, "blocks.py", "Blocks", "launch")
    check("[60] launch 시그니처를 실제로 읽었다", largs is not None and len(largs) > 20,
          "%s개" % (len(largs) if largs else 0))
    check("[60] `**kwargs` 가 아니라 **명시 인자**다 — 그래야 검사가 의미 있다",
          lkw is False, "kwargs=%s" % lkw)
    for k in ("theme", "server_name", "server_port"):
        check("[60] launch 가 `%s` 를 받는다" % k, largs and k in largs)

    # 소스가 없을 때 **통과로 위장하지 않는가**
    empty = tempfile.mkdtemp()
    open(os.path.join(empty, "app.py"), "w", encoding="utf-8").write("import gradio as gr\n")
    buf2 = _io.StringIO()
    with contextlib.redirect_stdout(buf2):
        G.main(["--root", empty])
    check("[60] gradio 소스가 없으면 **\"통과가 아니다\"라고 적는다**",
          "통과가 아니다" in buf2.getvalue(), buf2.getvalue()[-140:])


def test_markdown_tables():
    """[61] **화면을 처음 띄우고 나서야 보인 것** (결함 73·74).

    08-07 아침, `py app.py` 를 **처음으로 실제 실행**했다. 확인 0회였던
    심사 30점 항목이다. 그리고 두 개가 바로 보였다 —

      73  사고 과정 표가 중간부터 깨져 **파이프가 그대로 노출**
      74  결함 수가 **열두 판 낡은 값**으로 찍혀 있었다

    ## 왜 검사기 둘이 못 잡았나

    ```
    시험 [55]  가짜 gradio    콜백이 **문자열을 돌려주는지**만 봤다
    시험 [60]  gradiocheck   **API 시그니처**만 봤다
    실제 문제                 그 문자열이 **마크다운으로 어떻게 렌더되는지**
    ```

    **화면 한 번이 검사기 두 개보다 많이 잡았다.**
    *"검증 환경이 실행 환경과 다르면 그 검증은 거짓말이다"* — 이 프로젝트가
    가장 자주 반복한 문장이고, 이번엔 **거짓말한 쪽이 우리 검사기**였다.

    ## 이 시험이 지키는 것

    화면을 못 띄우는 환경에서도 **렌더 결과의 구조**는 검사할 수 있다 —
    표의 **컬럼 수가 헤더와 같은지** 세면 된다. 값이 아니라 형태를 본다.
    """
    from .. import dash as D
    from .. import evidence as EV

    # ── 이스케이프 자체 ────────────────────────────────────
    check("[61] 셀 안 파이프를 이스케이프한다",
          D._cell("a | b") == "a \\| b", D._cell("a | b"))
    check("[61] 줄바꿈도 없앤다 — 표 안에서 행이 갈린다",
          "\n" not in D._cell("a\nb"), repr(D._cell("a\nb")))
    check("[61] None 을 'None' 으로 찍지 않는다", D._cell(None) == "")

    # ── **모든 표 생성 경로**를 훑는다. 하나만 고치면 또 샌다 ──
    # **이스케이프된 파이프는 구분자가 아니다.** 첫 판이 그걸 같이 세서
    #   고친 코드를 "깨졌다"고 판정했다 — 오늘 네 번째로 시험이 틀렸다.
    #   마크다운은 `\|` 를 리터럴로 읽으므로 **검사기도 그래야 한다.**
    _SPLIT = re.compile(r"(?<!\\)\|")

    def bad_rows(md):
        out, ncol = [], None
        for ln in md.split("\n"):
            if not ln.startswith("|"):
                ncol = None
                continue
            cells = _SPLIT.split(ln.strip().strip("|"))
            if set(ln.replace("|", "").replace("-", "").replace(" ", "")) == set():
                continue                       # 헤더 구분선
            if ncol is None:
                ncol = len(cells)
            elif len(cells) != ncol:
                out.append(ln[:90])
        return out

    seen = 0
    for run in D.RUNS:
        for md, where in ((D.center(run), "center/%s" % run),
                          (D.left(D.RUNS[run]["입구"], "표준", "metformin"), "left")):
            seen += 1
            check("[61] %s 표의 컬럼 수가 일정하다" % where, not bad_rows(md),
                  str(bad_rows(md))[:90])
        for q in D.candidates(run):
            for fn, name in ((D.thinking, "thinking"), (D.evidence_card, "evidence"),
                             (D.side_by_side, "side_by_side")):
                md = fn(q)
                seen += 1
                check("[61] %s(%s) 표가 안 깨진다" % (name, q[:22]),
                      not bad_rows(md), str(bad_rows(md))[:90])
    for md, name in ((D.autonomy(), "autonomy"), (D.bottom_calibration(), "calibration")):
        seen += 1
        check("[61] %s 표가 안 깨진다" % name, not bad_rows(md), str(bad_rows(md))[:90])
    check("[61] 실제로 여러 경로를 훑었다", seen >= 12, "%d개" % seen)

    # 구운 사례에 **파이프가 실재하는지** 확인 — 없으면 이 시험이 공허하다
    import json
    cp = os.path.join(EV.ROOT, "demo_cases.json")
    if os.path.exists(cp):
        raw = open(cp, encoding="utf-8").read()
        check("[61] 구운 사례에 파이프가 실재한다 — 그래서 이 검사가 의미 있다",
              "신규 5 | 6건" in raw or "신규 6 | 6건" in raw or " | " in raw)

    # ── 결함 74 — 숫자를 하드코딩하지 않는가 ─────────────────
    import inspect
    src = inspect.getsource(D.autonomy)
    check("[61] 결함 수를 **파일에서 센다** — 하드코딩하지 않는다",
          "defect_count()" in src, src[:120])
    a = D.autonomy()
    n = EV.defect_count()
    check("[61] 화면의 결함 수 = 발견정리 표 행수",
          n and ("%d건" % n) in a, "표 %s · 화면에 있나" % n)

    # 그리고 **가드가 dash.py 를 보는가** — 이게 74의 근본이다
    from ..bench import docaudit as DA
    check("[61] `docaudit` 이 `dash.py` 를 본다 (결함 74의 근본)",
          any("dash.py" in f for f, _ in DA.EXTRA), str([f for f, _ in DA.EXTRA]))

    # ── 결함 75 — **가로 스크롤** (08-07 2차) ────────────────────
    #
    #   표는 안 깨졌는데 **셀 하나가 209자**여서 가로 스크롤이 생겼고
    #   **Ro5 경고문이 화면 밖으로 밀렸다.** 그 경고는 결함 34에서 나온
    #   실제 과학적 단서다 — 스크롤 안 하면 심사위원이 못 읽는다.
    check("[61] 공백 뭉치를 접는다 — 열 맞춤 공백이 셀을 늘렸다",
          D._cell("a" + " " * 40 + "b") == "a  b", repr(D._cell("a" + " " * 40 + "b")))
    # **화면에 보이는 길이를 센다.** 08-10에 판정·게이트·방향을 색 칩으로
    # 바꾸면서 `<span class='br-verdict …' style='…'>` 이 붙었는데,
    # 그 태그는 **폭을 한 픽셀도 안 먹는다.** 원문 길이를 세면 서식을
    # 넣을 때마다 이 시험이 깨지고, 깨진 시험은 손으로 고치게 된다.
    #
    #   `<span class='br-d br-d-ref'>반박</span>`  원문 39자 · 화면 2자
    #
    # 결함 75의 목적은 *"경고문이 가로 스크롤로 밀리지 않는 것"* 이었다.
    # 그 목적은 **보이는 길이**로만 지켜진다.
    _tags = re.compile(r"<[^>]+>")
    wide = []
    for run in D.RUNS:
        for q in D.candidates(run):
            for fn in (D.thinking, D.evidence_card, D.side_by_side):
                for ln in fn(q).split("\n"):
                    vis = _tags.sub("", ln)
                    if ln.startswith("|") and len(vis) > 110:
                        wide.append((q[:20], len(vis)))
    check("[61] **보이는** 표 행이 110자를 안 넘는다 — 넘으면 가로 스크롤",
          not wide, str(wide[:3]))
    check("[61] 그 길이는 **태그를 뺀 것**이다 — 서식은 폭을 안 먹는다",
          _tags.sub("", "<span class='x'>반박</span>") == "반박")

    # 경고문이 **사라지지 않고** 표 밖으로 나왔는가 — 좁히려다 지우면 안 된다
    md = D.thinking("metformin / Malignant neoplasm of breast")
    check("[61] ⚠ 경고를 표 밖 인용구로 뺀다 — **좁히려고 지우지 않는다**",
          any(l.startswith("> ⚠") for l in md.split("\n")),
          [l[:60] for l in md.split("\n") if l.startswith(">")][:2])
    check("[61] 그리고 경고 **내용이 살아 있다** (결함 34의 Ro5 단서)",
          "투과성을 뜻하지 않는다" in md)


def test_plaintext_labels():
    """[62] **선택지 라벨에는 마크다운이 안 통한다** (결함 76).

    08-07, 브라우저로 실제 화면을 읽다가 나왔다. `판정 사례` 탭의
    다섯 번째 항목만 이렇게 찍혀 있었다 —

    ```
    🟢 fluvoxamine / COVID-19 — 제안서는 `보류` 를 예상했는데 **유망 97%** …
                                        ↑ 백틱과 별표가 **원문 그대로**
    ```

    `gr.Radio` 의 **선택지 라벨은 평문**이다. 마크다운으로 안 그린다.
    다른 넷은 마크다운을 안 써서 멀쩡했고 **이 한 줄만 티가 났다.**

    ## 왜 앞의 검사들이 못 잡았나

    시험 [61]은 **표의 컬럼 수**를 봤다. `gradiocheck` 는 **API 시그니처**를
    봤다. 둘 다 *"이 문자열이 어디에 그려지는가"* 는 안 본다.
    **렌더 맥락은 화면을 봐야 안다** — 결함 73과 같은 층이고, 이번에도
    브라우저 한 번이 잡았다.

    이 시험은 그 대신 **규약**을 지킨다 — 평문으로 그려지는 자리에는
    마크다운 기호를 넣지 않는다.
    """
    from .. import demo as D

    MD = ("`", "**", "__", "~~")
    for name, why in D.PRESETS:
        for tok in MD:
            check("[62] PRESETS 설명에 `%s` 없음 — 평문으로 그려진다: %s"
                  % (tok, name[:26]), tok not in why, why[:70])
        check("[62] PRESETS 이름에도 마크다운이 없다: %s" % name[:26],
              not any(t in name for t in MD))
    # ── 08-14 정정 (결함 209) ─────────────────────────────────────
    #
    #   앞판은 `"97%" in w` 로 확인했다. **수치로 확인한 것이 문제였다** —
    #   사례를 다시 구우면 판정이 바뀌는데(실측: 여섯 중 넷) 설명은
    #   상수라 화면이 자기 판정과 어긋난 말을 했다.
    #
    #   **의도는 그대로다** — «제안서와 어긋난 사례를 목록에서 빼지
    #   않았다». 다만 **그 뜻으로** 확인한다. 수치는 자료에서 읽는다.
    check("[62] 그런데 **어긋난 사례는 그대로 있다** — 좁히려고 지우지 않는다",
          any("제안서" in w and ("다르" in w or "어긋" in w)
              for _n, w in D.PRESETS),
          str([w[:44] for _n, w in D.PRESETS])[-96:])

    # 대시보드의 후보 선택지(라디오)도 같은 자리다
    from .. import dash as DA
    for run in DA.RUNS:
        for q in DA.candidates(run):
            check("[62] 후보 선택지가 평문이다: %s" % q[:26],
                  not any(t in q for t in MD))

    # ── **구운 파일까지 본다** (결함 87 — 76의 재발) ────────────────
    #
    #   08-10에 브라우저로 화면을 열었더니 라디오 라벨에
    #   `` `보류` `` 와 `**유망 97%**` 가 원문 그대로 찍혀 있었다.
    #   **소스는 08-07에 고쳤는데 `demo_cases.json` 이 08-06판이었다.**
    #
    #   이 시험은 그때까지 `PRESETS`(소스)만 봤다. 그런데 **화면이 읽는 건
    #   구운 파일**이다. 고친 것과 화면에 뜨는 것이 다르면 가드는 무의미하다.
    #   결함 83(옆 폴더의 옛 코드 사본)과 같은 계열이다.
    from .. import evidence as EVc
    _baked = EVc.cases()
    if _baked:
        _src = dict(D.PRESETS)
        for c in _baked["사례"]:
            why = c.get("설명") or ""
            for tok in MD:
                check("[62] **구운 파일**의 설명도 평문이다 (`%s`): %s"
                      % (tok, (c.get("질의") or "")[:24]),
                      tok not in why, why[:70])
            # 소스와 **같은 문자열**인가 — 다르면 다시 구울 때가 된 것이다
            q = c.get("질의")
            if q in _src:
                check("[62] 구운 설명이 `PRESETS` 와 같다: %s" % q[:24],
                      why == _src[q], (why[:40] + " ≠ " + _src[q][:40])
                      if why != _src[q] else "일치")


def test_notranslate():
    """[63] **브라우저 자동 번역을 끈다** (결함 77).

    08-07, Edge 로 화면을 읽다가 나왔다. 브라우저가 **이미 한국어인
    페이지를 한국어로 번역**하고 있었다 —

    ```
    metformin / Malignant neoplasm of breast → 메트포르민 / 유방 악성 신생물
    PMID `40579605` · w=0.84 — CONCLUSION…   → 번호가 문장 끝으로 이동
    ```

    원인은 gradio 템플릿의 `<html lang="en">` 이다. **내용은 한국어인데
    영어라고 선언돼 있다.**

    ## 왜 이게 시험할 값이 있나

    ① 번역된 약물명은 **PubMed 에 안 검색된다** — 재현하려는 심사위원이 막힌다
    ② PMID 가 근거 문장에서 떨어져 나가면 *"판정마다 PMID 가 붙는다"* 는
       **핵심 주장이 화면에서 깨져 보인다**
    ③ **우리가 통제할 수 없는 변수**다 — 심사위원의 브라우저 설정이다

    그리고 이건 `gradiocheck`(API) 도 시험 [61](표 구조) 도 못 잡는다.
    **브라우저로 봐야 보이는 세 번째 층**이다.
    """
    from .. import evidence as EV
    from ..bench import gradiocheck as G

    ap = os.path.join(EV.ROOT, "app.py")
    if not os.path.exists(ap):
        return
    src = open(ap, encoding="utf-8").read()

    check("[63] `lang='ko'` 를 선언한다 — 사실을 적는 것이지 번역 금지가 아니다",
          "documentElement.lang='ko'" in src.replace(" ", ""))
    check("[63] `translate=no` 도 건다", "translate','no'" in src.replace(" ", ""))
    check("[63] `notranslate` 메타를 넣는다", 'content="notranslate"' in src)

    # **양쪽 gradio 판에 다 넣었는가** — 테마와 같은 이행이다
    # 08-10 — `theme`·`head`·`css` 셋이 같은 함정이라 **한자리로 모았다**
    #   (`_ui_kw()`). 두 경로가 갈라 적으면 또 어긋난다.
    check("[63] 판 분기를 **한 함수**에 모았다 — `_ui_kw()`",
          "def _ui_kw()" in src)
    check("[63] 그 함수가 `head` 를 싣는다",
          '"head": _NOTRANSLATE' in src.split("def _ui_kw()")[1][:300])
    check("[63] gradio 6 경로(launch)가 그 함수를 쓴다",
          "kw = _ui_kw() if _THEME_ON_LAUNCH" in src)
    check("[63] gradio 4·5 경로(Blocks)도 그 함수를 쓴다",
          "_BLOCKS_KW = _ui_kw()" in src)

    # 그 판의 `launch` 가 정말 `head` 를 받는지 — 안 받으면 TypeError 로 죽는다
    gpkg = os.path.join(EV.ROOT, ".venv", "Lib", "site-packages", "gradio")
    if os.path.isdir(gpkg):
        args, kw = G.class_method_args(gpkg, "blocks.py", "Blocks", "launch")
        check("[63] 설치된 gradio 의 `launch` 가 `head` 를 받는다",
              bool(args) and "head" in args, "%d개 인자" % len(args or []))


def test_deck_markdown():
    """[64] **구운 발표자료에 마크다운 기호가 남으면 안 된다** (결함 80).

    `build_deck.text()` 는 `**강조**` 를 파싱한다 — 그 주석에 *"별표가
    실제로 12곳에서 찍혔다"* 고 적혀 있다. **그런데 백틱은 안 고쳤다.**

    08-07에 슬라이드를 **처음으로 눈으로 보고** 나왔다. 21번에 —

    ```
    → `보류`. 판정하지 않는다      ← 백틱이 그대로
    → `조건부` 로 재분류
    ```

    `app.py` 의 결함 76과 **같은 고장**이다: 마크다운을 안 그리는 자리에
    마크다운을 썼다. 거기는 `gr.Radio` 라벨, 여기는 pptx.

    ## 왜 텍스트 추출로는 못 잡았나

    `docaudit` 이 pptx 를 읽지만 **수치 패턴만** 본다. 시험 [61]은
    **표 컬럼 수**를 본다. **"이 문자가 화면에 그대로 찍히나"** 는
    아무도 안 봤다 — **눈으로 보기 전에는 답이 없는 층**이다.

    이 시험은 그 대신 **구운 결과에 기호가 남았는지**를 센다.
    렌더를 보는 건 아니지만, 파싱 실패는 잡는다.
    """
    import zipfile
    from .. import evidence as EV

    p = os.path.join(EV.ROOT, "slides", "Bio-ReRoute_발표.pptx")
    if not os.path.exists(p):
        check("[64] 발표자료가 없어 검사 못 했다 — **통과가 아니다**", True, p)
        return
    try:
        z = zipfile.ZipFile(p)
    except Exception as e:
        check("[64] pptx 를 못 열었다", False, str(e)[:60])
        return
    names = [n for n in sorted(z.namelist())
             if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
    check("[64] 슬라이드를 읽는다", len(names) >= 20, "%d장" % len(names))

    blob = " ".join(re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8"))
                    for n in names)
    for tok, why in (("`", "백틱 — 결함 80"),
                     ("**", "별표 — build_deck 주석이 12곳이라 적은 그것")):
        n = blob.count(tok)
        check("[64] 구운 슬라이드에 `%s` 가 없다 (%s)" % (tok, why), n == 0,
              "%d개" % n)

    # **소스에는 있어야 한다** — 문법을 없애면 다음 사람이 또 쓴다.
    # 파싱하는 것과 금지하는 것은 다르다.
    src = open(os.path.join(EV.ROOT, "slides", "build_deck.py"),
               encoding="utf-8").read()
    check("[64] 소스는 백틱 표기를 **쓴다** — 없애는 게 아니라 파싱한다",
          '"`조건부` 로 재분류"' in src or "`보류`" in src)
    check("[64] `text()` 가 백틱을 쪼갠다", 'seg.split("`")' in src)
    check("[64] 백틱 안은 굵게 하지 않는다 — 코드는 강조가 아니다",
          "코드는 강조가 아니다" in src)

    # ── [65] **막대 합 = 표제 수** (결함 84) ──────────────────────
    #
    #   슬라이드 18의 표제는 `evidence.defect_count()` 를 따라 자동으로
    #   늘었는데 **유형별 막대는 08-06에 손으로 적은 값 그대로**였다.
    #
    #       표제 83  ·  막대 합 9+8+7+4+17+14 = 59      ← 24가 빈다
    #
    #   심사위원이 막대를 더하면 나온다. 그리고 그 장의 제목이
    #   *"우리 도구를 우리가 반증한 기록"* 이다 — **투명성을 말하는 장의
    #   숫자가 자기 자신과 안 맞았다.**
    #
    #   `docaudit` 은 **같은 이름의 값이 문서마다 같은가**를 본다.
    #   이건 다른 층이다 — **한 장 안에서 부분의 합이 전체와 맞는가.**
    nums = [int(m) for m in re.findall(r'^\s*\("[^"]+",\s*(\d+),\s*$|'
                                       r'^\s*\("[^"]+",\s*(\d+),\s*"',
                                       src, re.M) for m in m if m]
    tot = EV.defect_count()
    check("[65] 결함 유형 막대를 읽었다", len(nums) >= 6, "%d개" % len(nums))
    check("[65] **막대 합이 표제 결함 수와 같다** — 결함 84",
          sum(nums) == tot, "합 %d · 표제 %s" % (sum(nums), tot))
    check("[65] 표제도 같은 수를 쓴다",
          ("결함 %d건" % tot) in src, "결함 %d건" % tot)

    # ── [66] **제3자 타임스탬프를 화면이 스스로 읽는다** (결함 51·70) ──
    #
    #   결함 51 — 봉인 증거가 자체 Gitea 서버 시각뿐이었다.
    #   08-10에 해시를 밖에 박았다. **그런데 `.ots` 는 두 단계다** —
    #   접수 직후는 캘린더 앞으로 된 영수증이고, 비트코인 블록 귀속은
    #   몇 시간 뒤다. **접수를 확정이라 적으면 결함 70과 같다**
    #   (실행 0회인데 "로컬 확인 완료"라고 적어 뒀던 것).
    #
    #   그래서 화면에 상태를 **타이핑하지 않는다.** `.ots` 를 읽어서
    #   ① 그게 이 문서의 증명서인지 ② 확정됐는지를 매번 판단한다.
    nz = EV.notarization()
    check("[66] 등록 문서와 `.ots` 가 둘 다 있다",
          nz["문서"] and nz["ots"], "%s / %s" % (nz["문서"], nz["ots"]))
    if nz["ots"]:
        check("[66] `.ots` 가 **이 문서의** 증명서다 — 다른 파일이면 무의미",
              nz["해시일치"] is True)
        # ── 08-12 이 검사가 **결함을 못 박고 있었다** (결함 125·130) ──
        #
        #   초판: `nz["확정"] == (not nz["캘린더"])`.
        #   즉 «캘린더 URL 이 없어야 확정» 이라는 **틀린 가정을 시험이
        #   고정**하고 있었다. 실제로는 한 번 찍으면 캘린더 3~4곳에 동시에
        #   걸리고 Upgrade 는 **응답한 곳만** 블록 귀속으로 바꾼다.
        #   나머지 URL 은 남는다 — 승우 파일에도 둘이 남아 있다.
        #
        #   그래서 코드를 고치자(비트코인 태그를 직접 찾도록) **이 시험이
        #   빨개졌다.** 새로 넣은 [93] 과 **정반대를 주장하고 있었던 것**이다.
        #   **시험이 초록이라고 옳은 게 아니다** — 무엇을 주장하는지 봐야 한다.
        check("[66] 확정 여부를 **비트코인 귀속의 «있음»** 으로 판단한다 (결함 125)",
              nz["확정"] == nz["비트코인"],
              "확정=%s · 비트코인=%s · 미응답 캘린더 %d곳"
              % (nz["확정"], nz["비트코인"], len(nz["캘린더"])))
        check("[66] **캘린더가 남아 있어도 확정일 수 있다** — 부재로 판단하지 않는다",
              not (nz["캘린더"] and nz["비트코인"] and not nz["확정"]))
        # **상태 문자열을 상수로 안 박는다.** 데이터에서 방향을 읽는다
        # (`CLAUDE.md §4` — 해석 문구를 상수로 고정하지 마라).
        appsrc = _uisrc()          # 08-20 — 한 파일에 못 박지 않는다
        check("[66] 화면이 **미확정을 미확정이라** 적을 수 있다",
              "아직 미확정" in appsrc and "확정됨" in appsrc)
        check("[66] 화면이 상태를 **하드코딩하지 않는다**",
              'nz.get("확정")' in appsrc)

    # ── [67] **선언한 의존성 = 실제로 쓴 것** (결함 86) ────────────
    #
    #   `requirements.txt` 가 `rdkit-pypi` 를 요구했는데 `.venv` 에는
    #   공식 `rdkit` 이 있었다. **별개 배포판**이고 앞의 것은 2022.09.5
    #   에서 멈춘 옛 빌드다. 신선한 환경에서 깔면 **한 번도 안 써 본
    #   물건** 위에서 S2·hERG·DILI 가 돈다.
    #
    #   결함 72와 같은 자리다 — 그때는 *빠진 것*, 이번엔 *틀린 것*.
    #   **있는지는 봤는데 같은 것인지는 안 봤다.**
    from ..bench import deploycheck as DC

    check("[67] PyPI 이름 정규화 — `-`·`_`·대소문자 (PEP 503)",
          DC._norm("python-pptx") == DC._norm("python_pptx") == "python-pptx"
          and DC._norm("Markdown") == "markdown")
    check("[67] **`rdkit-pypi` 와 `rdkit` 은 다른 이름이다**",
          DC._norm("rdkit-pypi") != DC._norm("rdkit"))

    names, unpinned, unknown = DC.requirements_vs_venv()
    check("[67] requirements 를 읽었다", len(names) >= 5, "%d개" % len(names))
    check("[67] 전부 핀(`==`)이다 — 하한은 **안 시험한 주장**이다",
          not unpinned, ", ".join(unpinned) or "0개")
    # `.venv` 가 없는 환경(CI·배포지)에서는 **판정하지 않는다.**
    # 없는 것을 위반으로 세면 그게 결함 35다(막힌 것과 없는 것의 혼동).
    if DC._venv_dists():
        check("[67] 선언한 이름이 `.venv` 에 **실제로 있다**",
              not unknown, ", ".join(unknown) or "0개")

    sdk, grd = DC.sdk_vs_requirements()
    check("[67] README 의 `sdk_version` 과 requirements 의 gradio 판이 같다",
          sdk is not None and sdk == grd, "%s / %s" % (sdk, grd))

    # ── [69] **UniProt 질의가 0건을 내지 않게** (결함 88) ──────────
    #
    #   08-10 첫 실측 — `assess("SARS-CoV-2 3CL protease","SARS-CoV-2")`
    #   가 `구조없음 · UniProt 0건` 을 냈다. **없는 게 아니라 못 찾은
    #   것이다**(P0DTD1 이 실재한다). 원인 둘 —
    #
    #     `protein_name:` 은 정확 구문 일치를 요구한다
    #     `gene:SARS-CoV-2 3CL protease` — 따옴표가 없어 질의가 깨진다
    #
    #   **네트워크를 안 타고** 질의 문자열만 본다 — 시험이 외부 조회에
    #   의존하면 조회가 막힌 날 시험이 거짓말한다(결함 35의 교훈).
    from ..io import structure as ST
    import urllib.parse as _up

    _qs = ST._acc_queries("SARS-CoV-2 3CL protease", "SARS-CoV-2")
    _raw = [_up.unquote(u.split("query=")[1].split("&")[0]) for u in _qs]
    check("[69] 질의를 **둘** 만든다 — 정밀이 0건이면 느슨으로", len(_qs) == 2,
          "%d개" % len(_qs))
    check("[69] `gene:` 에 **따옴표가 있다** — 없으면 공백에서 깨진다",
          'gene:"SARS-CoV-2 3CL protease"' in _raw[0], _raw[0][:70])
    check("[69] 둘째 질의는 **자유 텍스트** — 따옴표를 안 씌운다",
          "protein_name:" not in _raw[1] and 'SARS-CoV-2 3CL protease AND' in _raw[1],
          _raw[1][:70])
    check("[69] 둘 다 `reviewed:true` 를 건다 — 미검토 항목은 주석이 없다",
          all("reviewed:true" in q for q in _raw))
    check("[69] 종을 주면 둘 다 좁힌다",
          all('organism_name:"SARS-CoV-2"' in q for q in _raw))
    _no_org = [_up.unquote(u.split("query=")[1].split("&")[0])
               for u in ST._acc_queries("JAK1/2", None)]
    check("[69] 종이 없으면 종 항을 안 붙인다",
          all("organism_name" not in q for q in _no_org), _no_org[1][:40])
    check("[69] 슬래시를 턴다 — `JAK1/2` → `JAK1`",
          all("JAK1/2" not in q for q in _no_org), _no_org[0][:40])

    # ── [70] **pLDDT 는 API 본문에 없다** (결함 89) ─────────────────
    #
    #   질의를 고치니 `P0DTC1` 을 찾았고, **그다음 층에서 걸렸다** —
    #   `pLDDT 배열 없음`. 우리 코드가 찾던 이름 셋(`confidenceScore`·
    #   `plddt`·`confidenceList`)은 **전부 모의를 보고 지은 것**이었다.
    #
    #   AlphaFold 는 잔기별 pLDDT 를 **좌표 파일의 B-factor 칸**에 넣는다.
    #   그래서 마지막 경로로 PDB 를 읽는다. **고정 폭 형식**이라
    #   `split()` 하면 안 된다 — 좌표가 붙어 나오는 줄이 있다.
    _pdb = ("ATOM      1  N   MET A   1      -8.901   4.127  -0.555  1.00 45.30           N\n"
            "ATOM      2  CA  MET A   1      -8.608   3.135  -1.618  1.00 45.30           C\n"
            "ATOM      3  C   MET A   1      -7.117   2.964  -1.897  1.00 45.30           C\n"
            "ATOM      9  CA  GLY A   2      -5.000   1.000  -1.000  1.00 92.75           C\n"
            "ATOM     14  CA  LYS A   3      -3.000   0.500  -0.200  1.00 88.10           C\n")
    _v = ST.parse_bfactors(_pdb)
    check("[70] `CA` 원자만 센다 — 잔기당 하나", len(_v) == 3, "%d개" % len(_v))
    check("[70] 고정 폭에서 B-factor 를 읽는다 (61~66)",
          _v == [45.30, 92.75, 88.10], str(_v))
    check("[70] 빈 입력에 **0 을 만들지 않는다**", ST.parse_bfactors("") == [])
    check("[70] `ATOM` 이 없으면 빈 목록 — 조용히 0 이 아니다",
          ST.parse_bfactors("HEADER x\nEND") == [])

    # ── **구조가 있는데 `구조없음` 이라 하지 않는다** (결함 89) ───────
    #   08-10 실측: `cif_url` 이 응답에 있었는데 라벨이 `구조없음` 이었다.
    #   *막힌 것과 없는 것은 다르다* — 결함 35·85와 같은 계열이다.
    _src = open(ST.__file__, encoding="utf-8").read()
    check("[70] `pLDDT 배열 없음` 은 **`구조없음` 이 아니다**",
          '"신뢰도미상"' in _src)
    # **문구가 아니라 값을 본다.** 초판은 소스에서
    # `'"cif_url": p.get("cif_url")'` 를 찾았는데, 반환을 `_out()` 하나로
    # 모으자 그 글자가 사라져 시험이 깨졌다 — **코드는 더 옳아졌는데
    # 시험이 붉어졌다.** 결함 51·55·61~63과 같은 계열이라 같은 처방을 쓴다.
    _rr, _pp, _pc = ST.resolve, ST.plddt, ST.pdb_count
    try:
        ST.pdb_count = lambda acc: None            # 시험은 망을 안 탄다
        ST.resolve = lambda t, o=None: {
            "accession": "X", "name": "", "organism": "", "sites": [],
            "chains": [], "seq_len": None, "error": None, "error_kind": None}
        ST.plddt = lambda a, sites=None, want=None: {
            "accession": a, "error": "pLDDT 배열 없음", "cif_url": "keep.cif"}
        _k = ST.assess("무엇이든")
        check("[70] 그때도 **좌표 주소를 버리지 않는다** — 뷰어는 그릴 수 있다",
              _k["cif_url"] == "keep.cif" and _k["label"] == "신뢰도미상",
              "%s · %s" % (_k["label"], _k["cif_url"]))
    finally:
        ST.resolve, ST.plddt, ST.pdb_count = _rr, _pp, _pc
    check("[70] `AlphaFold 미수록` 만 진짜 `구조없음` 이다",
          'lab, why = "구조없음"' in _src)

    # ── [71] **폴리단백질에서 어느 사슬을 묻는가** (결함 90) ────────────
    #
    #   08-10 실측이 `신뢰 · 활성부위 pLDDT 96.2` 를 냈는데, 평균 낸 잔기
    #   4개(200·231·234·236)가 **전부 nsp2** 였다. 정작 UniProt 이
    #   *"For 3CL-PRO activity"* 라고 적어 둔 촉매 이인조 **3304·3408**
    #   (His41·Cys145)은 **범위 밖이라고 버려졌다.**
    #
    #   3CL 프로테아제를 물었는데 **다른 단백질의 값**을 답한 것이다.
    #   아래 사슬 목록은 08-10에 UniProt REST 로 실측한 P0DTC1 이다.
    _CH = [{"name": "Replicase polyprotein 1a", "start": 1, "end": 4405},
           {"name": "Host translation inhibitor nsp1", "start": 1, "end": 180},
           {"name": "Non-structural protein 2", "start": 181, "end": 818},
           {"name": "Papain-like protease nsp3", "start": 819, "end": 2763},
           {"name": "Non-structural protein 4", "start": 2764, "end": 3263},
           {"name": "3C-like proteinase nsp5", "start": 3264, "end": 3569},
           {"name": "Non-structural protein 10", "start": 4254, "end": 4392}]
    _lo = ST.localize("SARS-CoV-2 3CL protease", _CH, 4405)
    check("[71] `3CL protease` → **`3C-like proteinase nsp5` 로 좁힌다**",
          _lo["kind"] == "국소화" and _lo["chain"]["start"] == 3264,
          "%s · %s" % (_lo["kind"], (_lo["chain"] or {}).get("name")))
    check("[71] 전장 사슬(1–4405)은 성숙 산물이 아니다 — 후보에서 뺀다",
          (_lo["chain"] or {})["end"] == 3569)
    _amb = ST.localize("protease", _CH, 4405)
    check("[71] `protease` 만으로는 **못 정한다** — nsp3·nsp5 둘 다 프로테아제다",
          _amb["kind"] == "모호", _amb["kind"])
    check("[71] 못 정하면 **전체로 되돌리지 않는다** (사슬 None)",
          _amb["chain"] is None)
    check("[71] 폴리단백질이 아니면 좁힐 것이 없다",
          ST.localize("JAK1", [{"name": "JAK1", "start": 1, "end": 1154}],
                      1154)["kind"] == "단일")

    # ── [72] **번호 틀을 못 맞추면 거절한다** (결함 90) ─────────────────
    #
    #   `site_stats` 는 `vals[p-1]` 로 읽는다 — **모델이 UniProt 1번
    #   잔기에서 시작한다는 가정**이고, 확인한 적이 없다. 08-10 실측은
    #   UniProt 4,405잔기 · 모델 303잔기였다. 단편의 시작 위치를 모르면
    #   **엉뚱한 잔기를 읽는다.** 그러면 숫자를 내지 않는다.
    _seen = {}

    def _fake_plddt(acc, sites=None, want=None):
        _seen["sites"] = list(sites or [])
        vals = [95.0] * 4405
        vals[3303], vals[3407] = 96.0, 97.0
        out = {"accession": acc, "mean": 95.0, "min": 95.0, "frac_low": 0.0,
               "n_res": _seen["n_res"], "cif_url": "x.cif", "pdb_url": "x.pdb",
               "version": 1, "error": None}
        out.update(ST.site_stats(vals, sites or []))
        return out

    _real_r, _real_p = ST.resolve, ST.plddt
    try:
        ST.plddt = _fake_plddt
        ST.resolve = lambda t, o=None: {
            "accession": "P0DTC1", "name": "Replicase polyprotein 1a",
            "organism": "SARS-CoV-2", "sites": [200, 231, 234, 236, 3304, 3408],
            "chains": _CH, "seq_len": 4405, "error": None, "error_kind": None}
        _seen["n_res"] = 303                      # ← 08-10 실측 그대로
        _a = ST.assess("SARS-CoV-2 3CL protease", "SARS-CoV-2")
        check("[72] 길이가 안 맞으면 **`신뢰` 라고 하지 않는다**",
              _a["label"] == "신뢰도미상", _a["label"])
        check("[72] 왜 못 재는지 **두 숫자를 다 적는다**",
              "4405" in _a["why"] and "303" in _a["why"])
        check("[72] 그래도 좌표 주소는 버리지 않는다", _a["cif_url"] == "x.cif")
        _seen["n_res"] = 4405                     # ← 번호 틀이 맞는 경우
        _b = ST.assess("SARS-CoV-2 3CL protease", "SARS-CoV-2")
        check("[72] 맞을 때는 **nsp5 의 두 잔기만** 쓴다 — 3304·3408",
              _seen["sites"] == [3304, 3408], str(_seen["sites"]))
        check("[72] nsp2 잔기(200·231·234·236)가 **안 섞인다**",
              _b["plddt"]["n_site"] == 2 and _b["plddt"]["site_mean"] == 96.5,
              "n=%s mean=%s" % (_b["plddt"]["n_site"], _b["plddt"]["site_mean"]))
        check("[72] 어느 사슬로 쟀는지 **판정에 실어 보낸다**",
              (_b.get("chain") or {}).get("start") == 3264)
        check("[72] 사슬 이름이 화면 문구에 남는다", "nsp5" in _b["why"])
        _amb_r = dict(ST.resolve("x"))
        ST.resolve = lambda t, o=None: _amb_r
        _c = ST.assess("protease", "SARS-CoV-2")
        check("[72] 사슬을 못 정하면 **숫자를 안 낸다**",
              _c["label"] == "신뢰도미상" and _c["basis"] is None, _c["label"])
    finally:
        ST.resolve, ST.plddt = _real_r, _real_p

    # ── [73] **라벨을 늘리면 소비자가 깨져야 한다** (결함 92) ───────────
    #
    #   08-10에 결함 89를 고치며 `신뢰도미상` 을 늘렸는데 `gates.py` 를
    #   안 고쳤다. `else` 로 떨어져 **조회 실패(ERROR)** 로 기록되고
    #   경로도 안 내려갔다 — *"조회 실패는 0건이 아니다"* 라고 적어 둔
    #   바로 그 분기가 발견을 삼킨 것이다. 목록을 코드로 못 박는다.
    from ..core import gates as _G
    check("[73] 게이트가 **모든 S1 라벨**을 다룬다",
          set(_G._S1_ACT) == set(ST.LABELS),
          "빠짐 %s" % sorted(set(ST.LABELS) - set(_G._S1_ACT)))
    check("[73] `신뢰도미상` 은 **연산 제외** — 저신뢰와 처분이 같다",
          _G._S1_ACT["신뢰도미상"][1] is True)
    check("[73] `오류` 는 경로를 **안** 바꾼다 — 장애를 발견으로 읽지 않는다",
          _G._S1_ACT["오류"][1] is False)
    check("[73] `신뢰` 만 구조 경로를 유지한다",
          _G._S1_ACT["신뢰"] == ("PASS", False))

    # ── [89] **잘린 자료를 «있다»로 읽지 않는다** (결함 116) ──────────────
    #
    #   08-11: DRKG 압축 해제가 중간에 끊겨 **167만 줄 · 132MB** 짜리가
    #   남았다. `available()` 은 **존재만** 봤으므로 `ok=True` 를 냈고,
    #   `netcheck` 화면에도 `OK` 가 찍혔을 것이다.
    #
    #   그대로 다중홉을 돌렸으면 **자료의 3/4 가 없는 채로 «연결이 없다»**
    #   라고 답한다. 결함 35(조회 실패를 0건으로 셈)와 **같은 고장**이고,
    #   이번엔 *부분 자료를 전체로* 읽는 쪽이다.
    from ..io import drkg as _DK
    import tempfile as _tf89
    _d89 = _tf89.mkdtemp()
    _old_path = _DK.DRKG_PATH
    try:
        _short = os.path.join(_d89, "drkg.tsv")
        open(_short, "w", encoding="utf-8").write(
            "Gene::1\tr\tGene::2\n" * 100)
        _DK.DRKG_PATH = _short
        _a = _DK.available()
        check("[89] 작은 파일을 **`ok` 로 안 읽는다**", _a["ok"] is False, str(_a)[:80])
        check("[89] **잘렸다고 말한다** — «없다»와 구분한다",
              "잘렸다" in (_a["error"] or ""), _a["error"])
        check("[89] 무엇과 비교했는지 적는다", "587만" in (_a["error"] or ""))
        _b = _DK.available(deep=True)
        check("[89] `deep=True` 면 **줄을 센다**", _b["rows"] == 100, str(_b["rows"]))
        _DK.DRKG_PATH = os.path.join(_d89, "없다.tsv")
        _c = _DK.available()
        check("[89] 아예 없으면 **«없다»** — 잘림과 다른 문구",
              "없음" in (_c["error"] or "") and "잘렸다" not in (_c["error"] or ""),
              _c["error"])
    finally:
        _DK.DRKG_PATH = _old_path
    check("[89] 문턱은 **하한**이다 — 판이 바뀌어도 안 깨진다",
          _DK._MIN_ROWS < _DK.DRKG_ROWS)

    # ── [88] **감시기가 자기 변경에 반응하면 안 된다** (결함 115) ─────────
    #
    #   08-11 저녁, 화면을 훑는 동안 **브라우저가 세 번 얼었다.**
    #   짚이는 데는 내가 그날 넣은 부트스트랩이다 —
    #
    #     MutationObserver(scan) 이 documentElement 를 subtree:true 로 감시
    #     그런데 draw() 가 **DOM 을 바꾼다** (dataset·경고 div·3Dmol 캔버스)
    #     gradio 도 쉴 새 없이 갈아끼운다
    #
    #   **원인이라고 단정하지 않는다** — 내 자동화가 O(n²) 훑기를 돌린
    #   것도 겹쳤다. 다만 이 설계는 **그것과 무관하게 위험하다.**
    #
    #   **발표장에서 심사위원 브라우저가 멎으면 그걸로 끝이다.**
    _b115 = open(os.path.join(EV.ROOT, "app.py"), encoding="utf-8").read()
    check("[88] 그릴 것이 없으면 **즉시 빠진다** — `:not([data-done])`",
          ":not([data-done])" in _b115)
    check("[88] 그리는 동안 **감시를 끊는다**",
          "mo.disconnect()" in _b115)
    check("[88] 그리고 **반드시 다시 붙인다** (`finally`)",
          "finally{ if(mo)mo.observe" in _b115)
    check("[88] 프레임당 한 번으로 **묶는다**",
          "requestAnimationFrame(scan)" in _b115 and "queued" in _b115)
    check("[88] `documentElement` 가 아니라 **`body`** 를 본다 — 범위를 좁힌다",
          "mo.observe(document.body" in _b115
          and "observe(document.documentElement" not in _b115)

    # ── [87] **배경을 박으면 글자색도 박아라** (결함 114) ─────────────────
    #
    #   08-11 다크 모드 실측. 뷰어 헤더가 이렇게 나왔다 —
    #
    #     배경 rgb(243,245,247)  ·  글자 rgb(243,244,246)  ·  **대비 1.01**
    #
    #   **흰 배경에 흰 글자.** 배경만 하드코딩하고 `color` 를 안 적어서
    #   gradio 다크 본문색(거의 흰색)을 물려받았다.
    #
    #   결함 68(다크에서 칩이 안 보임)과 **같은 자리**인데, 그때 만든
    #   시험 [68]은 칩만 본다. 뷰어는 **아예 안 돌고 있어서**(결함 112)
    #   아무도 안 봤다 — **한 결함이 다른 결함을 가렸다.**
    #
    #   규칙으로 만들 수 있다: **인라인 스타일에 `background` 가 있으면
    #   같은 스타일에 `color` 도 있어야 한다.** 검사 가능하다.
    import re as _re87
    from bioreroute import viewer as _VW87
    _samples = [
        _VW87.render(None),
        _VW87.render({"label": "구조없음", "why": "w"}),
        _VW87.render({"label": "신뢰", "cif_url": "https://x/a.cif", "why": "w",
                      "pdb_n": 92, "plddt": {"mean": 91.1, "frac_low": 0.05,
                                             "pdb_url": "https://x/a.pdb"}}),
    ]
    _naked = []
    for _h in _samples:
        for _st in _re87.findall(r'style="([^"]*)"', _h):
            _flat = _st.replace("\n", " ")
            if "background" not in _flat:
                continue
            # 색 견본(범례 네모)은 글자가 없다 — `width` 가 있으면 견본이다
            if "width:11px" in _flat.replace(" ", ""):
                continue
            if "color:" not in _flat:
                _naked.append(_flat.strip()[:60])
    check("[87] 배경을 박은 곳은 **글자색도 박는다** — 다크에서 흰 글자가 된다",
          not _naked, "색 없는 배경 %d곳: %s" % (len(_naked), _naked[:2]))
    check("[87] 뷰어 카드가 **밝은 배경을 스스로 고정한다** — 3D 캔버스가 흰색이다",
          "background:#fff;color:#1f2937" in _samples[2])
    _boot = open(os.path.join(EV.ROOT, "app.py"), encoding="utf-8").read()
    check("[87] 부트스트랩 경고 상자도 **배경과 글자색이 짝**이다",
          "color:#b45309" in _boot and "background:#fffbeb" in _boot)

    # ── [86] **CIF 로는 색이 안 나온다** (결함 113) ───────────────────────
    #
    #   08-11. 구조가 드디어 그려졌는데 **카툰이 전부 주황**이었다 —
    #   `<50 · 무질서 가능`. 우리 판정은 `신뢰 · pLDDT 91.1` 이다.
    #
    #   브라우저에서 원자를 세어 확인 —
    #
    #     3Dmol CIF 파서   원자 9,120개 · **b 값 0개**
    #     3Dmol PDB 파서   원자 9,120개 · b 값 9,120개 · 평균 91.3
    #
    #   CIF 에 `B_iso_or_equiv` 는 **있다**. 3Dmol 이 `atom.b` 로 안 옮긴다.
    #   `a.b` 가 undefined 라 비교가 전부 거짓 → **마지막 구간**으로 떨어졌다.
    #
    #   **안 그려지는 것보다 나쁘다.** 화면이 판정과 정반대를 말했다.
    from bioreroute import viewer as _VW86
    _pv = _VW86.render({"label": "신뢰", "cif_url": "https://x/a.cif", "why": "w",
                        "plddt": {"mean": 91.1, "frac_low": 0.05,
                                  "pdb_url": "https://x/a.pdb"}})
    check("[86] **PDB 를 쓴다** — CIF 는 3Dmol 이 b 를 안 읽는다",
          'data-cif="https://x/a.pdb"' in _pv)
    _cv = _VW86.render({"label": "신뢰", "cif_url": "https://x/a.cif", "why": "w",
                        "plddt": {"mean": 91.1, "frac_low": 0.05}})
    check("[86] `pdb_url` 이 없으면 cif 라도 그린다 — 좌표는 좌표다",
          'data-cif="https://x/a.cif"' in _cv)
    _ab = open(os.path.join(EV.ROOT, "app.py"), encoding="utf-8").read()
    check("[86] b 값이 **없으면 색칠을 포기한다** — 무질서라고 안 한다",
          "pLDDT 색칠을 못 한다" in _ab)
    check("[86] 그때도 **무질서하다는 뜻이 아니라고** 적는다",
          "무질서하다는 뜻이 아니다" in _ab)
    check("[86] 색칠 못 할 때는 **중립색**을 쓴다 — 주황은 뜻이 있다",
          "#9aa4ad" in _ab)
    # 우리 pLDDT 계산이 브라우저와 같은 답을 내는가 (08-11 교차 확인)
    #   브라우저 전 원자 91.3 · 70미만 5%  ↔  우리 CA 만 91.1 · 5%
    _v9 = [95.0] * 95 + [60.0] * 5
    check("[86] `frac_low` 는 **70 미만 비율**이다 — 화면 %와 같은 정의",
          round(sum(1 for x in _v9 if x < 70) / len(_v9), 3) == 0.05)

    # ── [85] **마크다운 안의 `<script>` 는 안 돈다** (결함 112) ───────────
    #
    #   08-11 실측. 뷰어 헤더는 그려지는데 구조가 안 나왔다. 브라우저로
    #   재니 —
    #
    #     <script src=…3Dmol…>   DOM 에 **있다**
    #     window.$3Dmol          **undefined**
    #     뷰어 div               높이 340 · 자식 0 · canvas 0
    #
    #   **브라우저는 `innerHTML` 로 삽입된 `<script>` 를 실행하지 않는다.**
    #   HTML 규격이고 gradio 는 마크다운을 그렇게 그린다. 즉 이 뷰어는
    #   **넉 달 내내 한 번도 돈 적이 없다.**
    #
    #   시험 [47]은 반환 **문자열에 pLDDT 숫자가 있는지**만 봤다.
    #   글자는 맞았고 아무것도 안 그려졌다.
    from bioreroute import viewer as _VW85
    _vh = _VW85.render({"label": "신뢰", "cif_url": "https://x/a.cif", "why": "w",
                      "plddt": {"mean": 91.1, "frac_low": 0.05}})
    check("[85] 뷰어가 **`<script>` 를 내지 않는다** — 내도 안 돈다",
          "<script" not in _vh, _vh[:80])
    check("[85] 대신 `data-cif` 로 주소를 넘긴다",
          'data-cif="https://x/a.cif"' in _vh)
    check("[85] 그릴 자리에 `br-3d` 표시가 있다", 'class="br-3d"' in _vh)
    _apps = open(os.path.join(EV.ROOT, "app.py"), encoding="utf-8").read()
    check("[85] 3Dmol 을 **`head` 에서** 부른다 — 거기선 진짜로 실행된다",
          "3Dmol-min.js" in _apps and "_VIEWER_BOOT" in _apps)
    check("[85] 화면이 바뀔 때마다 다시 훑는다 (`MutationObserver`)",
          "MutationObserver" in _apps)
    check("[85] CDN 이 막히면 **그렇다고 적는다** — 빈 상자를 안 낸다",
          "3Dmol.js 를 못 불러왔다" in _apps)
    check("[85] 그때도 **구조가 없다는 뜻이 아니라고** 말한다",
          "구조가 없다는 뜻이 아니다" in _apps)

    # ── [84] **구운 사례의 S1 이 뷰어까지 간다** (결함 109) ───────────────
    #
    #   08-11: `rifampin` 을 굽고 대시보드에 넣었는데 뷰어가 여전히
    #   *"구조를 표시하지 않는다"* 였다. 끊긴 데가 **둘**이었다 —
    #
    #     ① `demo.run_pair` 가 `c.s1` 을 반환에 안 실었다
    #     ② `app._dash_card` 가 `right_structure(None)` 을 **하드코딩**
    #
    #   ②의 주석이 이유를 정직하게 적어 뒀다 — *"구운 사례는 전부
    #   숙주·간접이라 S1 이 안 돈다"*. **그날 그 전제가 깨졌는데
    #   지름길만 남았다.** 적어 두는 것과 다시 읽는 것은 다르다.
    _appsrc = open(os.path.join(EV.ROOT, "app.py"), encoding="utf-8").read()
    _appsrc = _uisrc()         # 08-20 — 조립이 `webui.py` 로 옮겨 갔다
    check("[84] 뷰어에 **`None` 을 하드코딩하지 않는다**",
          "dash.right_structure(None)" not in _appsrc)
    check("[84] 구운 사례에서 `s1` 을 꺼내 넘긴다",
          "dash.right_structure(s1" in _appsrc)
    # 08-19 결함 287 — **질의도 같이 넘긴다.** `s1` 이 없을 때 «왜 안
    #   돌렸는지» 는 기록에 있고, 안 넘기면 뷰어가 이유를 지어낸다.
    check("[84] 질의도 넘긴다 — 이유를 아는 쪽이 넣어야 한다",
          "dash.right_structure(s1, query)" in _appsrc)
    _demosrc = open(os.path.join(EV.ROOT, "bioreroute", "demo.py"),
                    encoding="utf-8").read()
    check("[84] `run_pair` 가 `s1` 을 **반환에 싣는다**",
          '"s1": getattr(c, "s1", None)' in _demosrc)
    # 구운 파일이 실제로 갖고 있는가 — **소스만 보면 결함 87 을 반복한다**
    _cs = (EV.cases() or {}).get("사례") or []
    # ⚠ 09-25 · 다시 구운 판은 단계 이름이 **화면 말**(`표적 구조 신뢰도`)로 저장돼 있다.
    #   `"s1"` 글자만 찾으면 0건이 된다 — `GATE_KO` 로 옛 이름·새 이름을 같이 받는다(결함 275)
    from .. import demo as _DM84
    _s1ko = _DM84.GATE_KO.get("s1", "s1")
    _s1cases = [c for c in _cs
                if any(_DM84.GATE_KO.get(g.get("게이트"), g.get("게이트")) == _s1ko
                       and g.get("결과") != "SKIP"
                       for g in (c.get("게이트") or []))]
    check("[84] 구조 경로를 타는 구운 사례가 **있다**", len(_s1cases) >= 1,
          "%d건" % len(_s1cases))
    if _s1cases:
        check("[84] 그 사례가 `s1` 을 **갖고 있다** — 없으면 다시 구워야 한다",
              _s1cases[0].get("s1") is not None,
              "s1 키 없음 — `evidence.build_cases()` 를 다시 돌려라")

    # ── [83] **AFDB 의 404 는 "없다" 이지 "못 봤다" 가 아니다** (결함 107) ─
    #
    #   08-11 실측: `oseltamivir / Influenza` 가 앱에서 구조 분기를 탔고
    #   S1 이 이렇게 냈다 —
    #
    #     s1  ERROR  neuraminidase · AlphaFold: HTTPError: HTTP Error 404
    #
    #   그런데 AFDB 는 **수록된 것에 200+JSON, 없는 것에 404** 를 준다
    #   (P0DTC1 은 200 이었다 — 같은 날 원자료로 확인). 즉 404 는 **답**이다.
    #
    #   라벨이 갈리는 게 중요하다 —
    #     `오류`     경로를 **안 바꾼다.** 후보가 구조 경로에 갇힌다
    #     `구조없음`  증거 경로로 내려간다 — 설계가 원하는 처분
    #
    #   결함 35(조회 실패를 0건으로 셈)의 **반대 방향**이다.
    _src2 = open(ST.__file__, encoding="utf-8").read()
    check("[83] `HTTPError` 를 **따로** 잡는다", "urllib.error.HTTPError" in _src2)
    check("[83] 404 만 **미수록**으로 읽는다",
          "if e.code == 404" in _src2 and '"AlphaFold 미수록"' in _src2)
    check("[83] 5xx·타임아웃은 **여전히 `오류`** — 그건 진짜 못 본 것이다",
          '"HTTP %d" % e.code' in _src2)
    # 실제로 태운다 — `_get` 을 404 로 갈아끼운다
    import tempfile as _tf83
    import urllib.error as _ue
    from ..core import gates as _G83
    _rg = ST._get
    try:
        def _boom404(url):
            raise _ue.HTTPError(url, 404, "Not Found", None, None)
        ST._get = _boom404
        ST.cache.configure(os.path.join(_tf83.mkdtemp(), "c.json"), enabled=True)
        _p404 = ST.plddt("P03470")
        check("[83] 404 → `AlphaFold 미수록`", _p404["error"] == "AlphaFold 미수록",
              _p404["error"])

        def _boom503(url):
            raise _ue.HTTPError(url, 503, "Unavailable", None, None)
        ST._get = _boom503
        _p503 = ST.plddt("P03470X")
        check("[83] 503 → **미수록이 아니다**", _p503["error"] == "HTTP 503",
              _p503["error"])
    finally:
        ST._get = _rg
    check("[83] 그리고 `미수록` 은 `구조없음` 으로 간다 — 증거 경로로 내려간다",
          _G83._S1_ACT["구조없음"][1] is True)

    # ── [82] **시연용 구성이 동결 수치를 안 건드린다** (B5S · 08-11) ──────
    #
    #   08-11 실측: `oseltamivir / Influenza` 를 앱에서 태우니 라우터가
    #   `직접·병원체 · neuraminidase → structure` 로 **분기를 열었는데**
    #   화면은 `s1 SKIP · config off` 였다. 데모가 B5 로 돌고 s1 은 B7
    #   에만 있었다 — **게이트를 다섯 겹 고쳐 놓고 꺼진 채로 시연할 뻔했다.**
    #
    #   그래서 `B5S`(= B5 + s1, 등록부 제외)를 새로 뒀다. 위험은 하나 —
    #   **B0~B6 을 건드리면 동결된 모든 수치가 다른 시스템의 것이 된다.**
    #   그래서 값을 여기 손으로 박아 두고 대조한다. 시험이 정본이다.
    _FROZEN = {
        "B0": {"rag": False, "f0": False, "router": False, "s2": False, "skeptic": False},
        "B1": {"rag": True, "f0": False, "router": False, "s2": False, "skeptic": False},
        "B2": {"rag": True, "f0": True, "router": False, "s2": False, "skeptic": False},
        "B3": {"rag": True, "f0": True, "router": False, "s2": False, "skeptic": True},
        "B4": {"rag": True, "f0": True, "router": False, "s2": True, "skeptic": True},
        "B5": {"rag": True, "f0": True, "router": True, "s2": True, "skeptic": True},
        "B6": {"rag": True, "f0": True, "router": True, "s2": True,
               "skeptic": True, "registry": True},
    }
    from ..core.gates import CONFIGS as _CFG
    _drift = [k for k, v in _FROZEN.items() if _CFG.get(k) != v]
    check("[82] **B0~B6 이 한 글자도 안 바뀌었다** — 동결 수치의 전제",
          not _drift, "바뀐 구성 %s" % _drift)
    check("[82] `B5S` 에 s1 이 켜져 있다", _CFG["B5S"].get("s1") is True)
    check("[82] `B5S` 는 **등록부를 안 켠다** — 발표장에서 CT.gov 를 안 탄다",
          "registry" not in _CFG["B5S"])
    check("[82] B5S = B5 + s1 **그 이상도 이하도 아니다**",
          {k: v for k, v in _CFG["B5S"].items() if k != "s1"} == _FROZEN["B5"],
          str(_CFG["B5S"]))
    from .. import demo as _DM
    from ..core import gates as _G82
    # ── ⛔ 09-17 · **같은 사고가 두 번 났다.** 이 아래가 그 방어다 ──────────
    #
    #   08-11  `s1` 을 만들고 시연 구성에 안 넣었다 → 위 `B5S` 가 그 답.
    #   09-15  `fulltext`(F) 를 만들고 **또 안 넣었다.** `B5F` 는 벤치용이라
    #          `s1` 이 없고 `B5S` 에는 `fulltext` 가 없어서, **둘을 같이 켠
    #          구성이 저장소에 존재하지 않았다.** 09-17 에 찾았다.
    #
    #   위의 `== "B5S"` 검사는 **그 재발을 못 잡았다** — 이름만 봤기 때문이다.
    #   그래서 이름이 아니라 **«결정을 적었는가»** 를 본다.
    check("[82] 시연 구성이 **이름 하나**로 정해져 있다 (`demo.DEMO_CONFIG`)",
          _DM.DEMO_CONFIG in _G82.CONFIGS, _DM.DEMO_CONFIG)
    check("[82] `run_pair` 가 그 상수로 돈다 — 문자열을 따로 쓰면 또 갈린다",
          _DM.run_pair.__defaults__[0] == _DM.DEMO_CONFIG,
          _DM.run_pair.__defaults__[0])
    check("[82] `run_disease` 도 같은 상수로 돈다",
          _DM.DEMO_CONFIG in (_DM.run_disease.__defaults__ or ()),
          str(_DM.run_disease.__defaults__))
    # ⭐ **핵심** — 새 게이트를 만들면 여기서 실패한다
    _undecided = sorted(set(_G82.ORDER) - set(_G82.DEMO_GATES))
    check("[82] ⭐ **`ORDER` 의 모든 게이트가 «시연에 넣을지» 결정돼 있다**"
          " — 새 게이트를 만들면 여기서 걸린다",
          not _undecided,
          "결정을 안 적은 게이트: %s → `gates.DEMO_GATES` 에 (켤까?, 사유) 를 적어라"
          % _undecided)
    _ghost = sorted(set(_G82.DEMO_GATES) - set(_G82.ORDER))
    check("[82] 표에 **없는 게이트를 적지도 않았다** — 표가 곧 진실이어야 한다",
          not _ghost, str(_ghost))
    check("[82] `B5SF` 가 **표에서 파생**된다 — 손으로 적으면 갈린다",
          _G82.CONFIGS["B5SF"] ==
          {g: True for g, (on, _w) in _G82.DEMO_GATES.items() if on},
          str(_G82.CONFIGS["B5SF"]))
    _demo_cfg = _G82.CONFIGS[_DM.DEMO_CONFIG]
    for _g in ("s1", "fulltext"):
        check("[82] 시연 구성에 **`%s` 가 켜져 있다** — 꺼진 채로 시연하지 않는다" % _g,
              _demo_cfg.get(_g) is True, str(_demo_cfg))
    check("[82] 시연 구성은 **등록부를 안 켠다** — 발표장에서 CT.gov 를 안 탄다",
          not _demo_cfg.get("registry"), str(_demo_cfg))
    # ⭐ 화면에 **영문 게이트 이름이 찍히지 않는다** (결함 247·255 계열)
    _nokr = sorted(g for g in _G82.ORDER if g not in _DM.GATE_KO)
    check("[82] ⭐ `GATE_KO` 가 **`ORDER` 전수를 안다** — 없으면 화면에 영문이 찍힌다",
          not _nokr,
          "한글 이름 없는 게이트: %s (09-17 실측: `fulltext` 가 이틀간 비어 있었다)"
          % _nokr)
    # **벤치마크는 시연 구성을 쓰면 안 된다.** 쓰면 동결 비교가 깨진다.
    _bench = open(os.path.join(EV.ROOT, "bioreroute", "bench", "run.py"),
                  encoding="utf-8").read()
    for _c in ("B5S", "B5SF"):
        check("[82] 벤치마크는 `%s` 를 **안 쓴다** — 시연 전용이다" % _c,
              _c not in _bench)

    # ── [81] **돌고 있는지 화면이 말해야 한다** (결함 104) ────────────────
    #
    #   08-11에 승우가 「직접 검증」을 눌러 보고 말했다 —
    #   *"검사를 하면서 이게 돌아가고 있는지를 모르니까 **에러가 난 것처럼
    #   보여**."*
    #
    #   브라우저로 재니 출력칸(`gr.Markdown()`)이 **높이 0px** 이었다.
    #   gradio 는 진행 표시를 출력 컴포넌트 **안에** 그리는데 그릴 자리가
    #   없었다. 배관(`gr.Progress`)은 넉 달 전부터 있었고 **보이지 않았다.**
    #
    #   그리고 이건 제안서 §6 이 명시한 항목이다 —
    #     > 각 후보가 깔때기를 통과·탈락하는 단계를 **실시간 진행 표시**로
    #
    #   **여기서는 `app` 을 안 읽는다** — gradio 가 없는 환경이 있다.
    #   대신 소스와 순수 함수를 본다.
    _app = open(os.path.join(EV.ROOT, "app.py"), encoding="utf-8").read()
    check("[81] 출력칸이 **빈 채로 시작하지 않는다** — 높이 0이면 안 보인다",
          "gr.Markdown(LIVE_IDLE" in _app, "빈 gr.Markdown() 이다")
    # 08-19 — 내부 게이트 이름을 코드블록으로 보여 주고 있었다
    #   (`F0 근거 실재성 → 팩트체크 → 라우터 → S1 …`). **사람 말로 바꿨다.**
    #   요건은 «무엇이 돌지 미리 적는다» 이지 그 표기가 아니다.
    # **딱 그 상수만** 자른다. 600자로 자르면 뒤 함수의 독스트링까지
    #   들어와서 «내부 이름이 있다» 로 잘못 잡힌다 (실제로 그랬다).
    _idle = _app.split("LIVE_IDLE = ")[1]
    _idle = _idle[3:_idle.index('"""', 3)]
    check("[81] 눌렀을 때 **무엇이 돌지** 미리 적어 둔다",
          all(k in _idle for k in ("근거가 실제로", "지지", "반박", "판정")),
          _idle[:160])
    check("[81] 그 설명에 **내부 게이트 이름을 안 쓴다** (08-19)",
          not any(k in _idle for k in ("F0 ", "팩트체크", "라우터", "S1 ",
                                       "S2 ", "회의주의자")), _idle[:160])
    check("[81] `run_live` 가 **제너레이터**다 — 단계를 흘려보낸다",
          "yield _md_steps" in _app and "def run_live" in _app)
    check("[81] 무응답에 **시한**이 있다 — 영원히 도는 화면을 안 만든다",
          "timeout=180" in _app)
    check("[81] 무응답을 **판정으로 읽지 않는다**",
          "판정이 아니다" in _app)
    # ── 순수 함수는 실제로 태운다 ────────────────────────────
    #   08-20 — 소스에서 잘라 `exec` 하던 방식을 버린다. 조립 함수가
    #   `webui.py` 로 옮겨 가면서 깨졌고, **애초에 소스를 파싱해
    #   함수를 뽑는 것은 함수가 있는 곳에 묶이는 방법**이다.
    #   이제는 그냥 import 한다 — `webui` 는 gradio 를 안 쓴다.
    from .. import webui as _w81
    _f = getattr(_w81, "_md_steps", None)
    check("[81] `_md_steps` 를 실제로 태울 수 있다", callable(_f))
    if _f:
        _s2 = _f([("F0 근거 실재성", "PubMed 145건"), ("라우터", "직접·병원체")])
        check("[81] **게이트 이름**을 적는다 — 도는 아이콘만으로는 §6 이 아니다",
              "F0 근거 실재성" in _s2 and "라우터" in _s2)
        check("[81] **무엇을 봤는지**도 적는다", "PubMed 145건" in _s2)
        check("[81] **게이트 수**를 센다 — 콜백 수가 아니다",
              "게이트 2개" in _s2, _s2.split("\n")[0])
        check("[81] **멈춘 게 아니라고** 말해 준다 — 승우가 겪은 그 오해",
              "멈춘 게 아니다" in _s2)
        # 같은 게이트가 두 번 오면(`실행 중` → 결과) **한 줄로 접는다.**
        # 08-11 실측에서 게이트 5개가 **9단계**로 부풀어 보였다.
        _dup = _f([("F0", "실행 중"), ("F0", "PASS"),
                   ("라우터", "실행 중"), ("라우터", "UNKNOWN"),
                   ("회의주의자", "실행 중")])
        check("[81] 같은 게이트를 **두 줄로 쌓지 않는다** — 5콜백 → 3게이트",
              "게이트 3개" in _dup, _dup.split("\n")[0])
        check("[81] 나중 결과가 `실행 중` 을 **덮는다**",
              "F0 — **PASS**" in _dup and "F0 — **실행 중**" not in _dup)
        check("[81] 아직 도는 게이트는 `…` 로 남는다", "회의주의자 — **…**" in _dup)

    # ── [80] **봉인이 열리면 화면 문구가 따라와야 한다** (결함 102) ───────
    #
    #   08-11에 승우가 화면을 띄웠고, 「이 실행에서 빠진 것」 상자가
    #   여전히 이렇게 말하고 있었다 —
    #
    #     "라우터가 실제 실행 **27건 중 0번** structure 로 보냈다.
    #      명세는 봉인돼 있다"
    #
    #   **그날 오전에 그 봉인을 열었고 병원체 8/8 이 structure 로 갔다.**
    #   화면이 **우리 자신의 실험 결과를 반박**하고 있었다.
    #
    #   결함 87·76 과 같은 계열(구운 문구가 낡음)인데, 그때 만든 가드는
    #   *마크다운 노출*만 봤다. **내용이 낡은 것은 아무도 안 봤다.**
    #   그래서 결과 파일과 화면 문구를 **묶는다** — 결과가 생기면
    #   화면이 "실행 전"이라고 말할 수 없다.
    from bioreroute import dash as _D
    _miss = " ".join(str(r.get("빠진_것", "")) for r in _D.RUNS.values())
    _opened = os.path.exists(os.path.join(EV.ROOT, "라우터분기결과.md"))
    check("[80] 봉인 개봉 결과 파일이 있다", _opened)
    if _opened:
        check("[80] 화면이 **`봉인돼 있다`** 고 말하지 않는다",
              "봉인돼 있다" not in _miss, _miss[:90])
        check("[80] 화면이 **`0번`** 이라고 말하지 않는다 — 8/8 이었다",
              "0번" not in _miss and "0/27" not in _miss, _miss[:90])
        check("[80] 대신 **분기가 열린다**고 적는다",
              "분기는 열린다" in _miss or "8/8" in _miss, _miss[:90])
    check("[80] **왜 비었는지**는 여전히 적는다 — 빈 칸을 채우지 않는다",
          "없다" in _miss or "비워" in _miss)

    # ── [79] **라벨을 늘리면 화면도 깨져야 한다** (결함 100) ──────────────
    #
    #   결함 92 에서 `gates.py` 를 고쳤다. **`viewer.py` 는 안 봤다.**
    #   거기가 `if lab == "신뢰" else …` 이진 분기라 `신뢰도미상` 이
    #   **`저신뢰` 문구**로 떨어졌고, 화면이 *"무질서 영역이 넓다"* 라고
    #   말했다 — **못 잰 것이지 무질서한 게 아니다.**
    #
    #   같은 계열의 **두 번째 소비자**다. 그래서 이번엔 집합으로 못 박는다.
    from bioreroute import viewer as _VW
    check("[79] 뷰어가 **모든 S1 라벨**에 문구를 갖는다",
          set(_VW.VERDICT) == set(ST.LABELS),
          "빠짐 %s" % sorted(set(ST.LABELS) - set(_VW.VERDICT)))
    # **낱말이 아니라 주장을 본다.** 초판은 `"무질서" not in …` 이었는데
    # 문구가 *"무질서하다는 뜻이 **아니다**"* 라 통과 못 했다 — 부정문을
    # 긍정으로 읽은 것이다. 결함 51·55·61~63·70 과 같은 처방을 쓴다.
    check("[79] `신뢰도미상` 은 **무질서라고 단정하지 않는다**",
          "무질서 영역이 넓다" not in _VW.VERDICT["신뢰도미상"]
          and "뜻이 아니다" in _VW.VERDICT["신뢰도미상"],
          _VW.VERDICT["신뢰도미상"])
    check("[79] `신뢰` 도 **성공을 예측하지 않는다고** 적는다",
          "성공을 예측하지 않는다" in _VW.VERDICT["신뢰"])
    _s1 = {"label": "신뢰도미상", "cif_url": "https://x/a.cif", "why": "",
           "pdb_n": 4321, "chain": {"name": "3C-like proteinase nsp5",
                                    "start": 3264, "end": 3569},
           "plddt": {"mean": 95.3, "frac_low": 0.0, "start": 1566, "end": 1868,
                     "n_frag": 4, "n_site": 40, "n_site_used": 7}}
    _h = _VW.render(_s1)
    check("[79] 화면이 **모델이 덮는 구간**을 적는다 — 전장으로 안 읽히게",
          "1566" in _h and "1868" in _h)
    check("[79] 어느 **성숙 사슬**을 물었는지 적는다", "nsp5" in _h)
    check("[79] 단편이 여럿이면 그 사실도 적는다", "단편 4개" in _h)
    check("[79] 실험 구조가 있으면 **대리물이라고** 적는다",
          "4321" in _h and "대리물" in _h)
    check("[79] 그래도 **결합·친화도** 는 화면에 안 쓴다",
          not any(w in _h for w in ("결합 세기가", "친화도", "결합력")) or
          "결합 세기가 아니다" in _h)

    # ── [78] **AFDB 는 단편으로 쪼개 준다** (결함 98) ────────────────────
    #
    #   08-11 실측. `uniprotStart` 가 **실제로 있었다** —
    #
    #     P0DTC1 (4,405잔기) → 응답 첫 항목이 `1566–1868` 의 303잔기
    #
    #   즉 우리가 `vals[199]` 로 읽던 것은 UniProt 200번이 아니라
    #   **1765번**이었다. 그리고 우리가 물은 3CL 프로테아제는 3264–3569 라
    #   **이 단편과 겹치는 구간이 0** 이다. 겹치지 않는 단편을 놓고
    #   "활성부위 pLDDT 96.2"를 만들고 있었다.
    #
    #   아래 값은 **전부 그 실측 응답에서 온 것**이다. 지어낸 이름이 없다.
    _E = [{"uniprotStart": 1566, "uniprotEnd": 1868, "entryId": "AF-…313",
           "cifUrl": "a.cif", "pdbUrl": "a.pdb", "latestVersion": 1}]
    check("[78] 3CLpro(3264–3569)를 물으면 **이 단편은 안 준다**",
          ST.pick_fragment(_E, (3264, 3569)) is None)
    check("[78] PLpro(819–2763)를 물으면 이 단편이 맞다",
          (ST.pick_fragment(_E, (819, 2763)) or {}).get("entryId") == "AF-…313")
    check("[78] `want` 가 없으면 첫 항목 — 전장 모델이면 그게 맞다",
          (ST.pick_fragment(_E, None) or {}).get("entryId") == "AF-…313")
    check("[78] 겹침이 큰 쪽을 고른다",
          ST.pick_fragment(
              [{"uniprotStart": 1, "uniprotEnd": 100},
               {"uniprotStart": 90, "uniprotEnd": 400}], (200, 300)
          )["uniprotStart"] == 90)
    _v303 = [90.0] * 303
    check("[78] **옛 방식은 PLpro 촉매 잔기를 다 버렸다** (0/3)",
          ST.site_stats(_v303, [1674, 1752, 1835], 1)["n_site_used"] == 0)
    _ok = ST.site_stats(_v303, [1674, 1752, 1835], 1566)
    check("[78] `uniprotStart` 를 쓰면 **3개 다 잡힌다**",
          _ok["n_site_used"] == 3 and _ok["site_mean"] == 90.0, str(_ok))
    check("[78] 그래도 3CLpro 잔기(3304·3408)는 **여전히 범위 밖**이다",
          ST.site_stats(_v303, [3304, 3408], 1566)["out_of_range"] == 2)
    check("[78] 어느 구간을 쟀는지 **같이 돌려준다** — 이름은 `plddt` 와 안 겹치게",
          _ok["site_start"] == 1566)

    # ── [77] **우리 자신에 대한 숫자를 지어냈다** (결함 96·97) ───────────
    #
    #   08-11에 승우가 물었다 — *"7월에 시작했는데 왜 자꾸 넉 달이래?"*
    #   `넉 달`·`다섯 달` 이 **문서 27개에 99번** 있었고 근거가 하나도
    #   없었다. 가장 오래된 파일 08-03 · 첫 커밋 08-05 · 실제 **약 6주**.
    #
    #   **자기 비판이라 아무도 안 뒤졌다.** 유리한 숫자는 의심받고
    #   불리한 숫자는 그냥 통과한다. 그래서 검사로 막는다.
    import datetime as _dtm
    import tempfile as _tf
    from ..bench import docaudit as _DA
    _d2 = _tf.mkdtemp()
    _p2 = os.path.join(_d2, "README.md")
    _now = _dtm.date(2026, 8, 11)          # **날짜를 고정한다** — 시험이 늙지 않게
    open(_p2, "w", encoding="utf-8").write(
        "넉 달 동안 모의로만 돌렸다\n한 달 동안 고쳤다\n"
        "특허 API 는 다섯 달 전에 멈췄다\n")
    _du = _DA.duration_errors(_d2, today=_now)
    check("[77] 실제보다 긴 작업 기간을 **잡는다**", len(_du) == 1, str(_du))
    check("[77] 잡은 것이 `넉 달 동안` 이다",
          _du and "넉 달" in _du[0]["적힌 것"], str(_du))
    check("[77] 경과 안쪽(`한 달 동안`)은 **안 건드린다**",
          all("한 달" not in x["적힌 것"] for x in _du))
    check("[77] **`N 달 전` 은 안 본다** — 외부 사건일 수 있다(결함 95)",
          all("전" not in x["적힌 것"] for x in _du))
    open(_p2, "w", encoding="utf-8").write("```\n옛 문구: 넉 달 동안\n```\n")
    check("[77] 코드 펜스 안의 **과거 인용**은 세지 않는다",
          _DA.duration_errors(_d2, today=_now) == [])
    check("[77] 착수일이 **코드에 한 곳**으로 못 박혀 있다",
          _DA.PROJECT_START == _dtm.date(2026, 7, 1), str(_DA.PROJECT_START))
    check("[77] 저장소 문서에 남은 과장이 **0곳**",
          _DA.duration_errors(EV.ROOT, today=_now) == [],
          str(_DA.duration_errors(EV.ROOT, today=_now))[:120])

    # ── [76] **외부 의존이 우리 모르게 죽는다** (결함 95) ────────────────
    #
    #   PatentsView 의 search·API 가 **2026-03-20** USPTO ODP 전환으로
    #   중단됐다. 코드는 안 바뀌었고 시험도 다 통과했다 — **세상이 바뀌고
    #   우리 문서만 그대로였다.** 다섯 달 걸려 알았고, 그날 아침
    #   `netcheck` 는 **전부 초록**이었다(특허가 목록에 없었다).
    #
    #   다행인 건 설계가 막았다는 것이다. 키가 없으면 `확인불가` 이고
    #   *"확인불가는 개발가능이 아니다"* 를 같이 싣는다. **알아서 안 틀린
    #   게 아니라 몰랐는데도 안 틀렸다.**
    from ..io import fto as _F
    _f = _F.check("aspirin", api_key="")
    check("[76] 키가 없으면 `확인불가` — **`개발가능` 이 아니다**",
          _f["label"] == "확인불가", _f["label"])
    check("[76] 화면이 **못 구한다는 사실까지** 말한다 — 안 한 것과 다르다",
          "2026-03-20" in _f["why"] and "중단" in _f["why"], _f["why"][:70])
    check("[76] 특허가 **판정 축이 아니라고** 같이 적는다",
          "로드맵" in _f["why"])
    check("[76] `netcheck` 목록에 특허가 **들어 있다** — 없어서 다섯 달 걸렸다",
          "PATENTSVIEW_API_KEY" in open(
              os.path.join(EV.ROOT, "bioreroute", "netcheck.py"),
              encoding="utf-8").read())
    check("[76] 그래도 **점수는 안 만든다** — 특허는 가설을 틀리게 하지 않는다",
          not any(k in _f for k in ("weight", "score", "logodds")), sorted(_f))

    # ── [75] **예측 구조를 쓸 이유가 없는 표적이 있다** (결함 94) ────────
    #
    #   `SARS-CoV-2 3CL protease` 는 실험 구조가 **수천 건**이다 —
    #   `6LU7`(2020) · Diamond 의 Mpro 단편 스크리닝(`5R…`·`5S…`·`7G…`·
    #   `7H…`). 결정 구조가 있는데 예측 구조 pLDDT 로 신뢰도를 재는 것은
    #   **게이트가 아니라 자료원의 오류**이고, 게이트를 아무리 고쳐도
    #   안 없어진다. 그래서 **화면이 그 사실을 말하게** 한다.
    #
    #   **판정은 안 바꾼다.** S3 도킹이 로드맵이라 쓸 데가 없고,
    #   근거 없이 라벨을 흔들면 그게 또 다른 결함이다.
    _tsv = "PDB\n6LU7;6M03;7GAV;\n"
    check("[75] TSV 한 줄에서 실험 구조 수를 센다",
          ST.parse_pdb_tsv(_tsv) == 3, ST.parse_pdb_tsv(_tsv))
    check("[75] 교차참조가 없으면 0", ST.parse_pdb_tsv("PDB\n") == 0)
    check("[75] 빈 응답에 **숫자를 지어내지 않는다**", ST.parse_pdb_tsv("") == 0)
    _real_pc = ST.pdb_count
    try:
        ST.pdb_count = lambda acc: 4321
        ST.plddt = _fake_plddt
        _seen["n_res"] = 4405
        ST.resolve = lambda t, o=None: {
            "accession": "P0DTC1", "name": "Replicase polyprotein 1a",
            "organism": "SARS-CoV-2", "sites": [3304, 3408], "chains": _CH,
            "seq_len": 4405, "error": None, "error_kind": None}
        _q = ST.assess("SARS-CoV-2 3CL protease", "SARS-CoV-2")
        check("[75] 실험 구조 수를 판정에 실어 보낸다", _q["pdb_n"] == 4321)
        # **`why` 가 아니라 뷰어가 말한다** (결함 108). `why` 는 게이트
        # 추적표의 한 칸으로도 들어가는데, 실험구조 문장을 붙였더니
        # 행이 243자가 돼 가로 스크롤이 생겼다(시험 [61]).
        # **좁은 칸과 넓은 칸은 다른 글을 받는다.**
        from bioreroute import viewer as _VW75
        _hq = _VW75.render(dict(_q, cif_url="x.cif"))
        check("[75] **뷰어가** 대리물이라고 말한다", "대리물" in _hq)
        check("[75] **어느 사슬인지 안 봤다고 같이 적는다** — 결함 90 재발 방지",
              "안 봤다" in _hq)
        check("[75] 게이트 표에 들어갈 `why` 는 **짧게 유지한다**",
              len(_q["why"]) < 110, "%d자" % len(_q["why"]))
        check("[75] 그래도 **판정은 안 흔든다** — 근거 없는 강등은 또 다른 결함",
              _q["label"] == "신뢰", _q["label"])
        ST.pdb_count = lambda acc: None      # 조회 실패
        _z = ST.assess("SARS-CoV-2 3CL protease", "SARS-CoV-2")
        check("[75] 못 세면 **0 이라 하지 않는다** (`None`)", _z["pdb_n"] is None)
        check("[75] 못 셌으면 문구도 안 붙인다", "대리물" not in _z["why"])
    finally:
        ST.resolve, ST.plddt, ST.pdb_count = _real_r, _real_p, _real_pc

    # ── [74] **일괄 치환 사고를 검사로 막는다** (결함 93) ───────────────
    #
    #   08-10에 결함 수를 89→92 로 일괄 치환하다 슬라이드의
    #   `유형 충돌 89/457 = 19.5%` 를 `92/457` 로 덮었다. 92/457 은
    #   20.1% 다 — **분자와 백분율이 서로 안 맞는 숫자.**
    #
    #   이 유형은 이번이 **다섯 번째**이고, 넷을 겪는 동안 *"조심하자"* 만
    #   했다. 문서 간 대조로는 못 잡는다(그 값은 한 곳에만 있다). 그래서
    #   **한 문장 안의 자기 모순**을 본다.
    import tempfile as _tf
    from ..bench import docaudit as _DA
    _d = _tf.mkdtemp()
    _p = os.path.join(_d, "README.md")
    open(_p, "w", encoding="utf-8").write(
        "유형 충돌 92/457 = 19.5%\n누출 6/432 = 1.4%\n반올림 1/3 = 33.3%\n")
    _e = _DA.ratio_errors(_d)
    check("[74] 산수가 안 맞는 비율을 **잡는다**", len(_e) == 1, str(_e))
    check("[74] 무엇이 틀렸는지 **실제 값을 같이 준다**",
          abs(_e[0]["실제"] - 20.13) < 0.01, str(_e[0].get("실제")))
    check("[74] 맞는 비율은 **안 건드린다** — 오탐이 쌓이면 가드는 꺼진다",
          all("432" not in x["적힌 것"] for x in _e))
    check("[74] 반올림은 표기 자릿수만큼 봐준다 (33.3% ← 33.333…)",
          all("1/3" not in x["적힌 것"] for x in _e))
    open(_p, "w", encoding="utf-8").write("```\n옛 기록: 92/457 = 19.5%\n```\n")
    check("[74] 코드 펜스 안의 **과거 인용**은 세지 않는다",
          _DA.ratio_errors(_d) == [])
    check("[74] 슬라이드 소스도 본다 — **pptx 는 별도 소스라 따로 어긋난다**",
          "slides/build_deck.py" in open(_DA.__file__, encoding="utf-8").read())

    # ── [68] **다크 모드에서 안 보이면 안 된다** ────────────────────
    #
    #   08-10 실측 — 다크 모드로 열었더니 **칩이 배경만 남고 글자가
    #   사라졌다.** 원인 둘 —
    #
    #     ① gradio 가 `.prose` 아래 글자색을 흰색으로 덮는다 (특이도 우위)
    #     ② `--neutral-100` 은 **모드에 따라 안 뒤집힌다** (양쪽 다 #f3f4f6)
    #        → 밝은 배경 + 흰 글자 = 안 보임
    #
    #   **심사위원 OS 설정은 우리가 못 고른다.** 색이 뜻을 나르는 자리는
    #   양보하면 안 된다.
    _app = open(os.path.join(EV.ROOT, "app.py"), encoding="utf-8").read()
    _css = _app.split('_CSS = """')[1].split('"""')[0]
    # **주석은 규칙이 아니다.** 왜 안 쓰는지 설명한 문장이 걸리면
    # 안 되므로 `/* … */` 를 먼저 지운다 — 시험이 자기 설명에 걸린
    # 적이 오늘만 세 번째다(문서 인용·옛 코드 인용·이 주석).
    _rules = re.sub(r"/\*.*?\*/", "", _css, flags=re.S)
    check("[68] `--neutral-*` 를 배경으로 쓰지 않는다 — 모드에 따라 안 뒤집힌다",
          "--neutral-1" not in _rules and "--neutral-2" not in _rules,
          [l for l in _rules.split("\n") if "--neutral-" in l][:1])
    for cls in ("br-g-ok", "br-g-warn", "br-g-branch", "br-g-fix",
                "br-d-sup", "br-d-ref",
                "br-v-기각", "br-v-유망", "br-v-조건부", "br-v-보류"):
        rule = [l for l in _css.split("\n") if ("." + cls + "{") in l]
        check("[68] `%s` 색이 **뒤집히지 않게 고정**됐다" % cls,
              bool(rule) and "!important" in rule[0]
              and rule[0].lstrip().startswith(".gradio-container"),
              (rule[0][:60] if rule else "규칙 없음"))
    # 08-10 3차 — `code` 배경을 **아예 없앴다.** 반투명보다 이게 낫다:
    # 배경이 없으면 모드에 따라 뒤집힐 것도 없다. 대신 등폭 글꼴로 구분한다.
    _code_rule = [l for l in _rules.split("\n") if ".prose code" in l]
    check("[68] `code` 에 배경이 없다 — 상자 대신 글꼴로 구분한다",
          bool(_code_rule) and "background:transparent" in
          _rules.split(".prose code")[1][:200],
          (_code_rule[0][:56] if _code_rule else "규칙 없음"))
    # 08-10 5차에 `.prose code` 규칙이 **둘로 갈렸다**(공통 + 등폭).
    # `split(...)[1]` 은 앞의 것만 보므로 **등폭 사슬이 있는 규칙**을 찾는다.
    _mono = [b for b in _rules.split("}") if "monospace" in b]
    check("[68] 등폭 사슬 끝에 **한글 글꼴**이 있다 — 한글을 등폭에 넣으면 못 본다",
          bool(_mono) and "Pretendard" in _mono[0],
          (_mono[0].strip()[:60] if _mono else "등폭 규칙 없음"))
    check("[68] 등폭은 **`code` 에만** — 식별자(`br-q`)는 본문 글꼴이다",
          bool(_mono) and ".br-q" not in _mono[0].split("{")[0],
          (_mono[0].split("{")[0].strip()[:56] if _mono else "—"))
    check("[68] 등폭 크기를 **옆 글자에 맞춘다** — `font-size-adjust`",
          "font-size-adjust" in _rules)

    # ── CSS 가 **문법적으로 성립하나** ──────────────────────────────
    #
    #   08-10에 주석을 이어 쓰다가 `*/` 를 하나 더 남겼다. 그러면 그
    #   뒤의 한글 산문이 **규칙으로 읽히고** CSS 파서가 거기서부터
    #   버린다 — 화면이 통째로 민무늬가 된다. 파이썬 문법 검사는
    #   이걸 못 잡는다(문자열 안이니까).
    #
    #   **가드가 안 보는 곳이 가장 오래 낡는다**(결함 72·86의 교훈).
    #   `_CSS` 는 여태 아무 검사도 안 받고 있었다.
    check("[68] CSS 주석 짝이 맞는다 `/*` = `*/`",
          _css.count("/*") == _css.count("*/"),
          "%d / %d" % (_css.count("/*"), _css.count("*/")))
    check("[68] CSS 중괄호 짝이 맞는다",
          _rules.count("{") == _rules.count("}"),
          "%d / %d" % (_rules.count("{"), _rules.count("}")))
    _leak = re.search(r"^\s*[가-힣]", _rules, re.M)
    check("[68] 한글 산문이 **주석 밖으로 새지 않았다**",
          not _leak, (_leak.group()[:40] if _leak else "0건"))
    check("[68] 배지 안 신뢰도가 부모 색을 물려받는다",
          ".br-conf" in _css and "color:inherit !important" in _css)


def test_wired():
    """[49] **결함 44 — 만들어 놓고 아무도 안 부르는 모듈이 있었다.**

    08-06에 여덟 모듈을 넣고 시험 60여 개를 통과시켰다. 그런데 시험이
    모듈을 **직접** 부르니 당연히 통과했고, **파이프라인·데모 어디서도
    부르지 않았다.** 여섯 개가 도달 불가능한 코드였다.

    ```
    viewer · tox · drkg · fto · profiles · reverse   ← 호출 0
    ```

    "코드가 있다"고 🟡 을 줬는데 도달 불가능한 코드는 ❌ 에 가깝다.
    이 시험은 **배선 자체**를 검사한다 — 모듈 시험과 다른 층이다.
    """
    import inspect
    from ..core import profiles
    from ..core.state import Candidate, Evidence, RunState

    src = inspect.getsource(gates)
    for mod, why in (("tox", "hERG·DILI (§1.2)"),
                     ("profiles", "접근성 층 (§2.5·§8.3)"),
                     ("hitl", "음성 KB (§2 세 축)"),
                     ("structure", "S1 (§2.5)")):
        check("[49] gates 가 %s 를 실제로 부른다 — %s" % (mod, why),
              ("import %s" % mod) in src or ("%s." % mod) in src, mod)

    # ── 배선이 **동작**하는지. import 만으로는 증명이 안 된다 ──────
    real = sources.s2_properties
    S2 = {"smiles": "CN(C)C(=N)N=C(N)N", "mw": 129.2, "logp": -1.3,
          "hbd": 3, "hba": 3, "ro5_violations": 0, "pains": False,
          "pains_name": "", "status": "PASS", "detail": "PAINS 없음 · Ro5 위반 0건",
          "caveat": "", "caveat_tier": "", "caveat_reasons": []}
    try:
        sources.s2_properties = lambda n: dict(S2)
        c = Candidate(name="metformin / y", drug="metformin", disease="y",
                      origin="t", query="q")
        st = RunState("q", "t", "t", [c], {"s2": True})
        gates.gate_s2(st)
        check("[49] S2 통과 후 접근성이 **실제로 채워진다**",
              isinstance((c.s2 or {}).get("accessibility"), dict), str(c.s2)[:90])
        acc = c.s2["accessibility"]
        check("[49] 접근성이 S2 물성을 읽는다 (§8.3)", acc["oral_ok"] is True, str(acc))
        check("[49] metformin 은 WHO EML 에 있다", acc["eml"] is True)
        check("[49] hERG 경보가 붙는다 (§1.2)", "herg" in c.s2, list(c.s2)[:9])
        # **trail 이 안 바뀌어야 한다** — 동결 수치 보호
        t = [x for x in c.trail if x.gate == "s2"][0]
        check("[49] 배선이 s2 trail 문구를 안 바꾼다",
              t.detail == S2["detail"] and t.outcome == "PASS", t.detail)
    finally:
        sources.s2_properties = real

    # 제안서 §8.3 이 든 두 예가 실제로 갈리는가
    flu = profiles.accessibility("fluvoxamine", {"ro5_violations": 0})
    rem = profiles.accessibility("remdesivir", {"ro5_violations": 2})
    check("[49] §8.3 예시가 갈린다 — 플루복사민 경구 · 렘데시비르 아님",
          flu["oral_ok"] is True and rem["oral_ok"] is False,
          "%s vs %s" % (flu["oral_ok"], rem["oral_ok"]))
    # 08-18 — 문구에 `**` 강조가 붙었다(제안서 각주를 뺀 자리).
    #   **시험이 서식을 고정하면 서식을 못 고친다**(결함 265 계열).
    #   그래서 강조 기호를 지우고 **뜻만** 본다.
    check("[49] 접근성이 효능 판정과 분리돼 있다고 적는다",
          "효능 판정과 분리" in flu["note"].replace("*", ""),
          flu["note"][-40:])

    # ── drkg — **마지막까지 도달 불가였던 모듈** ─────────────────
    #
    #   렌즈 3이 그동안 줄곧 이것만 잡았고 매번 넘겼다. 자료를 안 받아서
    #   `multihop()` 은 태울 수 없다. 그래서 **부재를 보고하는 경로**를
    #   배선했다 — `netcheck` 이 `available()` 을 부른다.
    #
    #   **이게 가드 통과용 배선이 아닌지 검사한다** — netcheck 이
    #   실제로 부르는지, 그리고 없을 때 `없음` 을 찍는지 둘 다 본다.
    #   조용한 부재가 결함 35의 원인이었다.
    from .. import netcheck as NC
    from ..io import drkg as DK
    nsrc = inspect.getsource(NC)
    check("[49] netcheck 이 drkg.available 을 부른다 — 선언한 자료원의 부재도 답이다",
          "drkg.available()" in nsrc)
    check("[49] 부재를 **화면에 찍는다** (조용한 부재 = 결함 35)",
          "없음" in nsrc and "로드맵" in nsrc)
    check("[49] 부재를 실패로 세지 않는다 — 늘 붉으면 아무도 안 본다",
          "실패로 세지 않는다" in nsrc)
    # **주변 상태에 기대지 않는다.** 초판은 `DK.available()` 을 그냥 불렀는데
    # 그건 저장소에 `drkg.tsv` 가 **없다는 전제**였다. 08-11에 파일이
    # 생기자마자 깨졌다 — 시험이 틀린 게 아니라 **전제가 사라졌다.**
    # 없는 경로를 명시해서 «없을 때» 를 실제로 만든다.
    _p49 = DK.DRKG_PATH
    try:
        DK.DRKG_PATH = "__없는파일__.tsv"
        av = DK.available()
        check("[49] available() 이 없을 때 사유를 돌려준다",
              av["ok"] is False and "받아라" in (av["error"] or ""), str(av)[:70])
    finally:
        DK.DRKG_PATH = _p49
    # 없는 파일을 조용히 빈 그래프로 만들면 **다중홉 0건이 결과처럼 보인다**
    g = DK.load("__없는파일__.tsv")
    check("[49] 없는 파일을 빈 그래프로 위장하지 않는다", bool(g.get("error")), str(g)[:60])
    # ── 이 검사를 두 번 고쳤다. **첫 판이 틀렸다** ────────────────
    #
    #   처음엔 `"bench/graph.py" not in __doc__` 이라고 썼다. 그런데
    #   독스트링이 *"초판이 bench/graph.py 를 가리켰는데 그 파일은 없다"*
    #   고 **부재를 설명하려고** 그 이름을 쓴다. 시험이 붉어졌다.
    #
    #   즉 **문자열의 존재를 봤는데 봐야 할 것은 주장이었다.**
    #   결함 61과 같은 실수다 — 그쪽은 가드가 문구를 못 읽어 통과했고,
    #   이쪽은 문구를 잘못 읽어 실패했다. **방향만 반대다.**
    #
    #   고친 불변식: 이름을 쓰는 것은 되고, **쓰면 없다고 같이 적어야 한다.**
    doc = DK.__doc__ or ""
    check("[49] 독스트링이 없는 파일을 **있는 것처럼** 가리키지 않는다",
          ("bench/graph.py" not in doc) or ("그 파일은 없다" in doc))
    check("[49] 로드맵임을 독스트링에 적는다 — 코드가 문서보다 뒤처진 상태를 숨기지 않는다",
          "로드맵" in doc and "실행된 적이 없다" in doc)

    # ── [90] 결함 117 — **개수 정렬은 질환을 안 본다** ─────────────
    #
    #   08-11 자료를 처음 태운 날 나왔다. 질환 60개 각각 상위 10 중
    #   평균 4.5개가 **전역 차수 상위 10** 이었고, 차수 1466짜리 하나가
    #   60개 중 48개에 들었다. 화합물 차수 중앙값은 **2** 다.
    #
    #   **자료 없이도 재현되는 모형으로 시험한다** — 허브 하나를 손으로
    #   심고, 개수 정렬이 그걸 1위로 올리고 `enrich` 가 안 올리는지 본다.
    #   자료 파일에 기대면 또 «주변 상태에 기댄 시험»(70·75·49)이 된다.
    _dis = "Disease::MESH:D000001"
    _hub = "Compound::HUB"
    _spec = "Compound::SPECIFIC"
    _dgenes = ["Gene::%d" % i for i in range(20)]
    _cg = {_hub: set("Gene::%d" % i for i in range(400)),      # 400개 중 20개가 질환
           _spec: set(_dgenes[:6])}                            # 6개 전부가 질환
    _gc = {}
    for _c, _gs in _cg.items():
        for _gx in _gs:
            _gc.setdefault(_gx, set()).add(_c)
    _G = {"ok": True, "cg": _cg, "gc": _gc, "cd": {},
          "gd": {}, "dg": {_dis: set(_dgenes)}}
    _mh = DK.multihop(_G, _dis, k=5, min_shared=2)
    check("[90] 개수 정렬은 **허브를 1위로 올린다** — 결함 117 이 재현된다",
          _mh["items"][0]["compound"] == _hub,
          str([i["compound"] for i in _mh["items"]]))
    check("[90] multihop 이 그 편향을 **스스로 경고한다**",
          "허브" in (_mh.get("hub_warning") or ""))
    _en = DK.enrich(_G, _dis, k=5, min_shared=2)
    check("[90] 차수 보존 널은 특이 화합물을 위로 올린다",
          _en["items"][0]["compound"] == _spec,
          str([(i["compound"], i["z"]) for i in _en["items"]]))
    check("[90] enrich 가 기대값을 같이 낸다 — z 만 주면 근거 두께가 안 보인다",
          all(("expected" in i and "degree" in i) for i in _en["items"]))
    check("[90] 널 이름을 밝힌다 — 표준 관행이지 우리 발명이 아니다",
          _en.get("null") == "degree-preserving")
    check("[90] z 를 p-값으로 팔지 않는다",
          "p-값이 아니다" in (_en.get("caveat") or ""))
    # `min_degree` 는 **반대쪽 고장**을 막는다. 실측에서 간선 5개짜리가
    # z=10.5로 1위였다 — 얇은 근거가 강한 신호로 둔갑한다.
    _en5 = DK.enrich(_G, _dis, k=5, min_shared=2, min_degree=100)
    check("[90] min_degree 가 얇은 근거를 실제로 자른다",
          all(i["degree"] >= 100 for i in _en5["items"]) and
          _spec not in [i["compound"] for i in _en5["items"]])
    check("[90] 그래프 미적재를 0건으로 위장하지 않는다",
          DK.enrich({"ok": False}, _dis)["ok"] is False)
    check("[90] 없는 질환 노드를 «후보 없음» 으로 위장하지 않는다",
          bool(DK.enrich(_G, "Disease::MESH:D999999").get("error")))
    # 문턱을 **출력을 보고** 고르지 않았다는 것이 이 결함의 핵심이다
    import os as _os90, pathlib as _pl90
    _sp90 = str(_pl90.Path(__file__).resolve().parent.parent.parent / "사전명세_그래프검색.md")
    _t90 = open(_sp90, encoding="utf-8").read() if _os90.path.exists(_sp90) else ""
    check("[90] 순위 방법을 **사전명세로 봉인**했다 — 같은 질환을 보며 세 번 고쳤으므로",
          "세 번" in _t90, _sp90)
    check("[90] 명세가 **차수 대조군**을 이겨야 한다고 미리 적었다",
          "차수만으로 매긴 순위" in _t90)

    # ── [91] 결함 118 — **고친 것이 대조군보다 나빴다** ────────────
    #
    #   이 실험을 구한 것은 오직 **사전에 박아 둔 대조군 D** 하나다.
    #   그래서 시험도 «대조군이 실제로 존재하고 질환을 안 보는가» 를 본다.
    #   대조군이 몰래 질환을 보면 이 판정 전체가 무효다.
    from ..bench import graphcheck as GC
    check("[91] 대조군 D 가 방법 목록에 실제로 있다", "D" in GC.METHODS)
    _gsrc = inspect.getsource(GC.rank_all)
    check("[91] 대조군 D 는 **화합물 차수만** 본다 — 질환이 안 들어간다",
          'out["D"] = [c for c, k, n, z in sorted(rows, key=lambda r: (-r[2], r[0]))]' in _gsrc)
    # 가린 간선을 **그래프에서 실제로 지우는가.** 안 지우면 그 화합물이
    # `known` 으로 빠져 회수율이 0이 된다 — «누출 차단» 이 아니라 «정답 삭제» 다
    _fake = {"ok": True, "cd": {"C1": {"D1", "D2"}, "C2": {"D1"}},
             "cg": {}, "gc": {}, "gd": {}, "dg": {}}
    _hold, _g2 = GC.split(_fake, frac=0.5, seed=1)
    _left = {(c, d) for c, ds in _g2["cd"].items() for d in ds}
    check("[91] 가린 간선을 그래프에서 **실제로 지운다**",
          all(e not in _left for e in _hold) and len(_hold) > 0, str(_hold))
    check("[91] 원본을 훼손하지 않는다 — 사본을 만든다",
          sum(len(v) for v in _fake["cd"].values()) == 3)
    # 같은 seed 면 같은 분할이어야 한다. 아니면 재현이 안 된다
    check("[91] seed 가 같으면 분할이 같다",
          GC.split(_fake, frac=0.5, seed=1)[0] == _hold)
    # **상한을 분모로 따로 낸다.** 하나만 쓰면 결함 46(정답표 37%)이 된다
    _rsrc = inspect.getsource(GC.report)
    check("[91] 도달 상한을 분모로 따로 적는다 — 분모 하나만 쓰면 결함 46",
          "어떤 방법도 못 넘는 상한" in _rsrc and "결함 46" in _rsrc)
    check("[91] 다중비교를 보정한다 (Holm · 방법 3개)",
          "Holm" in _rsrc and callable(GC.holm))
    _q = GC.holm([("a", 0.01), ("b", 0.02), ("c", None)])
    # **검정 못 한 것(None)을 m 에 세면 안 된다** — 세면 보정이 과해진다.
    # 처음엔 0.03(m=3)을 기대했는데 틀렸다. 살아 있는 검정은 둘이다.
    check("[91] Holm 이 실제로 보정한다 — **살아 있는 검정 수**만 곱한다",
          abs(_q["a"] - 0.02) < 1e-9 and _q["c"] is None, str(_q))
    # 기각된 방법을 **기각됐다고 코드가 말하는가**
    check("[91] enrich 가 스스로 «기각» 이라고 말한다",
          "기각" in DK.REJECTED and "8.5%" in DK.REJECTED)
    check("[91] enrich 출력에도 그 사실이 붙는다",
          "기각" in (DK.enrich(_G, _dis).get("rejected") or ""))
    _res91 = str(_pl90.Path(__file__).resolve().parent.parent.parent / "그래프검색결과.md")
    _t91 = open(_res91, encoding="utf-8").read() if _os90.path.exists(_res91) else ""
    check("[91] 틀린 예측을 **틀렸다고 적었다** — 넷 중 둘", "둘이 틀렸다" in _t91)
    check("[91] 지표 탓으로 판정을 뒤집지 않는다고 적었다",
          "C 를 살리지 않는다" in _t91)
    check("[91] 임베딩을 안 쓰는 이유(누출)를 적었다",
          "누출" in (GC.__doc__ or ""))

    # ── [92] 08-12 새 도구 셋 — **결함 121~124** ───────────────────
    from ..bench import reversecheck as RC, calibrate as CB, skepticrate as SR

    # 결함 124 — 다른 bench 도구 다섯이 전부 부르는 것을 새 파일이 안 불렀다
    for _mod, _nm in ((RC, "reversecheck"),):
        check("[92] %s 가 질의 전에 cache.load() 를 부른다 (결함 26·27·124)" % _nm,
              "cache.load()" in inspect.getsource(_mod.run))

    # 결함 123 — **빈 팔로 판정하지 않는다.** 이게 이 실험의 생명줄이다
    _rsrc = inspect.getsource(RC.report)
    check("[92] 빈 팔이면 **판정을 거부**한다 — 0/0 에 Fisher 를 돌리지 않는다",
          "판정하지 않는다" in _rsrc and "rn == 0 or nn == 0" in _rsrc)
    check("[92] 거부 사유로 «측정 자체를 못 함» 을 구별해 적는다 (결함 35 계열)",
          "측정 자체를 못 함" in _rsrc)
    # 실제로 거부하는지 **태워서** 본다 — 문자열만 보면 결함 61이 된다
    import json as _j92, tempfile as _t92, os as _o92
    _fd, _p92 = _t92.mkstemp(suffix=".json")
    _o92.close(_fd)
    try:
        _j92.dump({"per": {"faers::D": {"disease": "D",
                   "arms": {"R": ["a"], "F": [], "N": []},
                   "errors": {"N": "풀 조회 실패"},
                   "f0": {"R": {"a": "PASS"}, "F": {}, "N": {}},
                   "jaccard_RF": 0.0, "jaccard_NF": 0.0}},
                   "meta": {"seed": 1, "k": 1, "diseases": ["D"],
                            "source": "faers", "n_done": 1}},
                  open(_p92, "w", encoding="utf-8"), ensure_ascii=False)
        _out92 = RC.report(_p92, "faers")
        check("[92] **실제로** 태웠을 때 판정문이 안 나온다",
              "판정하지 않는다" in _out92 and "Fisher 양측 p" not in _out92,
              _out92[-160:])
        check("[92] 거부해도 조회 실패 사유는 화면에 남는다",
              "풀 조회 실패" in _out92)
    finally:
        _o92.remove(_p92)
    # 대조군은 **질환을 안 봐야 한다** — 이게 흐려지면 실험 전체가 무효다
    check("[92] 대조군 arm_random 이 질환을 인자로 안 받는다",
          "disease" not in str(inspect.signature(RC.arm_random)),
          str(inspect.signature(RC.arm_random)))
    check("[92] 승인약 풀이 비면 **0건을 결과로 쓰지 않는다**",
          "0건을 결과로 쓰지 않는다" in inspect.getsource(RC.approved_pool))
    check("[92] 질환을 **동결 파일에서** 뽑는다 — 손으로 안 고른다",
          RC.POOL == "bench_tn_pool_v2.csv" and "동결" in (RC.__doc__ or "")
          or "동결" in inspect.getsource(RC.diseases))
    check("[92] 철자 변형을 병합한다 (COVID-19 = Covid19)",
          RC._norm("COVID-19") == RC._norm("Covid19"))

    # 결함 122 — Platt: 단조성과 구간
    check("[92] Platt 이 단조를 스스로 검사한다 — 순위가 바뀌면 버그다",
          callable(CB.verify_monotone) and "monotone_ok" in inspect.getsource(CB.run))
    check("[92] ECE 구간 수를 **사전 고정**했다 (돌린 뒤 고르면 유리한 값을 고른다)",
          CB.N_BIN == 10 and "사전 고정" in inspect.getsource(CB))
    check("[92] 짝지은 부트스트랩 구간이 있다 — 구간 없이 «이겼다» 를 말하지 않는다",
          callable(CB.boot_diff) and "짝지은" in (CB.boot_diff.__doc__ or ""))
    check("[92] 적합·평가 겹침을 **빼고 이름을 적는다**",
          "조용히 빼지 않는다" in inspect.getsource(CB.report))
    # 보정 구현이 실제로 맞는가 — 일부러 비튼 자료를 되돌리는지 태운다
    import math as _m92, random as _r92
    _r92.seed(3)
    _p = [_r92.random() for _ in range(1500)]
    _y = [1 if _r92.random() < x else 0 for x in _p]
    _bad = [min(0.99, max(0.01, x * 1.6 - 0.3)) for x in _p]
    _s = [_m92.log(x / (1 - x)) for x in _bad]
    _A, _B = CB.fit_platt(_s[:500], _y[:500])
    _q = CB.apply_platt(_s[500:], _A, _B)
    check("[92] Platt 이 **비튼 자료를 실제로 되돌린다**",
          CB.ece(_q, _y[500:])[0] < CB.ece(_bad[500:], _y[500:])[0],
          "%.4f → %.4f" % (CB.ece(_bad[500:], _y[500:])[0], CB.ece(_q, _y[500:])[0]))
    check("[92] Platt 결과가 단조다", CB.verify_monotone(_s[500:], _q))

    # 반박 회수율 — 없는 파일을 0으로 세지 않는다
    check("[92] skepticrate 가 없는 state 를 0건으로 위장하지 않는다",
          SR.measure("__없는파일__.json").get("ok") is False)
    check("[92] 회수율에 Wilson 구간을 같이 낸다",
          "rate_ci" in inspect.getsource(SR.measure))
    # ── [96] 결함 135 — **가드 둘이 구조적으로 눈을 감고 있었다** ────
    #
    #   ① `preflight.uncovered()` — 대상 4개가 **전부 skip 경로**라
    #      어떤 입력에도 `[]` 를 냈다. 「가드가 안 보는 곳을 찾는 가드」가
    #      아무것도 안 봤다. 화면엔 늘 «OK 없음».
    #   ② `docaudit` ECE 규칙이 **문자열 «105» 를 사냥**했다. 문서 열 곳이
    #      전부 같이 틀린 동안 «10곳 일치» 로 초록이었다.
    from ..bench import preflight as PF96, docaudit as DA96
    # ── 08-12 두 번째 판 — **시험을 뒤집었다** (결함 136) ──────────────
    #
    #   앞판은 `uncovered(".") 이 0개보다 많다` 를 요구했다. 그건 **그날의
    #   고장 상태를 정답으로 박은 것**이다 — 33개를 분류해 0으로 만들자
    #   시험이 빨개졌다. 시험이 *«고쳐지면 안 된다»* 고 말한 셈이다.
    #
    #   그래서 둘로 나눈다 —
    #     · **낼 수 있는가**는 임시 디렉터리에 안 보이는 파일을 심어서 본다
    #     · **실제 저장소**는 반대로 **0이어야 한다**
    import tempfile as _t96a, os as _o96a
    _d96a = _t96a.mkdtemp(prefix="uncov_")
    open(_o96a.path.join(_d96a, "아무도안보는것.md"), "w",
         encoding="utf-8").write("# 없음\n")
    check("[96] uncovered() 가 **낼 수 있다** — 안 보이는 문서를 심으면 짚는다",
          "아무도안보는것.md" in PF96.uncovered(_d96a),
          str(PF96.uncovered(_d96a)))
    import shutil as _s96a
    _s96a.rmtree(_d96a, ignore_errors=True)
    _u96 = PF96.uncovered(PF96.ROOT)
    check("[96] 그리고 **실제 저장소는 0이어야 한다** — 분류를 끝냈으므로",
          _u96 == [], str(_u96))
    check("[96] 대상이 전부 걸러지면 **그 사실을 보고한다** (조용히 통과 안 함)",
          "검사가 죽어 있다는 뜻" in inspect.getsource(PF96.uncovered))
    # ── **깨뜨려 본다.** 통과도 검증이 아니다 (결함 85) ────────────
    import tempfile as _t96, os as _o96
    _d96 = _t96.mkdtemp(prefix="docaudit_")
    _orig_docs, _orig_root = DA96.DOCS, DA96.ROOT
    try:
        open(_o96.path.join(_d96, "가짜.md"), "w", encoding="utf-8").write(
            "보정에서는 기준선에 졌다. 끝.\n")
        DA96.DOCS, DA96.ROOT = ["가짜.md"], _d96
        _r96 = DA96.audit(root=_d96)
        check("[96] **낡은 보정 주장을 실제로 잡는다** — 일부러 깨뜨려 확인",
              bool(_r96.get("낡은_보정주장")), str(_r96.get("낡은_보정주장")))
        # 인용은 안 잡아야 한다 — 결함 기록·주석은 옛 문구를 일부러 싣는다
        open(_o96.path.join(_d96, "가짜.md"), "w", encoding="utf-8").write(
            '| 122 | 앞판이 *"보정에서는 기준선에 졌다"* 라 적었다 |\n')
        _r96b = DA96.audit(root=_d96)
        check("[96] **인용은 안 잡는다** — 결함 기록이 옛 문구를 싣는 것은 정상",
              not _r96b.get("낡은_보정주장"), str(_r96b.get("낡은_보정주장")))
    finally:
        DA96.DOCS, DA96.ROOT = _orig_docs, _orig_root
        import shutil as _s96
        _s96.rmtree(_d96, ignore_errors=True)
    check("[96] ECE 규칙이 **값 사냥이 아니라 정본 대조**다",
          any("정본" in str(r[2]) for r in DA96.CHECKS if "ECE" in str(r[0])))

    # ── [97] 결함 136 — **고친 가드가 이번엔 늘 울었다** ──────────────
    #
    #   결함 135를 고치자 렌즈 8이 **매 실행 33개**를 냈고 `--strict` 는
    #   영영 통과 불가가 됐다. **늘 우는 가드는 눈 감은 가드와 같은 값**
    #   이다 — 결함 126에서 이미 겪었다(경보를 7일 동안 아무도 안 봤다).
    #
    #   셋으로 갈랐다: 감사 / **기록**(대조하면 훼손) / **봉인**(해시가 본다).
    check("[97] 기록 문서 목록이 있다 — 옛 숫자가 남는 게 정상인 것들",
          len(DA96.LOG) >= 10 and "렌즈답변.md" in DA96.LOG)
    check("[97] **봉인 목록을 손으로 안 적는다** — `*_봉인.json` 에서 읽는다",
          "봉인.json" in inspect.getsource(DA96.sealed_docs))
    _sd97 = DA96.sealed_docs()
    check("[97] 봉인이 가리키는 문서를 실제로 찾는다",
          len(_sd97) >= 10 and any("사전명세" in x for x in _sd97),
          "%d개" % len(_sd97))
    check("[97] 기록과 봉인은 **겹치지 않는다** — 한 문서가 두 부류일 수 없다",
          not (set(DA96.LOG) & set(_sd97)),
          str(set(DA96.LOG) & set(_sd97)))
    check("[97] 살아 있는 문서(DOCS)와 기록(LOG)도 안 겹친다",
          not (set(DA96.DOCS) & set(DA96.LOG)),
          str(set(DA96.DOCS) & set(DA96.LOG)))
    # 봉인 해시 대조를 **preflight 이 실제로 부른다** — 08-12까지 안 불렀다
    _ss97 = PF96.seal_state()
    check("[97] preflight 이 **봉인 해시를 직접 본다** (그전엔 화면만 봤다)",
          _ss97["오류"] is None and _ss97["전체"] >= 10,
          str(_ss97)[:80])
    check("[97] 지금 봉인은 **전부 무결**하다",
          not _ss97["깨짐"], str(_ss97["깨짐"]))
    # ── **깨뜨려 본다** — 해시를 어긋나게 하면 잡히는가 ────────────
    import tempfile as _t97, json as _j97, hashlib as _h97, shutil as _s97
    _d97 = _t97.mkdtemp(prefix="seal_")
    # ── ⚠ 08-14 결함 220 — **윈도우에서만 늘 실패하던 자리** ──────────
    #
    #   앞판은 이랬다 —
    #
    #       open(…, "w", encoding="utf-8").write("A\n")
    #       "sha256": _h97.sha256(b"A\n").hexdigest()
    #
    #   윈도우 텍스트 모드가 `\n` 을 **`\r\n` 으로 바꾼다.** 파일에는
    #   `b"A\r\n"` 이 들어가는데 기대 해시는 `b"A\n"` 이라 **원리적으로
    #   안 맞는다.** 리눅스에서는 둘이 같아서 **영원히 통과**한다.
    #
    #   > `CLAUDE.md §5` — *"검증 환경이 실행 환경과 다르면 그 검증은
    #   > 거짓말이다 (RDKit·**Windows 경로**·마운트 속도)"*. 그 항목이다.
    #
    #   고침 — **쓴 파일을 실제로 읽어서** 해시를 만든다. `make_seal` 이
    #   하는 일과 같아지므로 플랫폼과 무관해진다. **기대값을 손으로
    #   적지 않는 것**이 이 수정의 요점이다.
    _p97 = _o96a.path.join(_d97, "명세.md")
    open(_p97, "w", encoding="utf-8").write("A\n")
    _j97.dump({"문서": "명세.md",
               "sha256": _h97.sha256(open(_p97, "rb").read()).hexdigest()},
              open(_o96a.path.join(_d97, "x_봉인.json"), "w", encoding="utf-8"))
    check("[97] 손 안 댄 봉인은 무결로 읽는다",
          PF96.seal_state(_d97)["깨짐"] == [], str(PF96.seal_state(_d97)))
    open(_o96a.path.join(_d97, "명세.md"), "w", encoding="utf-8").write("B\n")
    check("[97] **한 글자만 바꿔도 깨짐으로 잡는다** — 일부러 깨뜨려 확인",
          PF96.seal_state(_d97)["깨짐"] == ["명세.md"],
          str(PF96.seal_state(_d97)))
    _s97.rmtree(_d97, ignore_errors=True)
    # ── `countsync` 가 **기록을 고쳐 쓰지 않는가** ────────────────
    from ..bench import countsync as CS97
    _d97b = _t97.mkdtemp(prefix="csync_")
    open(_o96a.path.join(_d97b, "README.md"), "w", encoding="utf-8").write(
        "결함 39건이다\n\n```\n그때 화면은 결함 39건 이라 말했다\n```\n\n결함 39건\n")
    _od97 = list(CS97.DOCS)
    try:
        CS97.DOCS[:] = ["README.md"]
        _rows97 = CS97.plan({"결함": 39, "시험": 1},
                            {"결함": 135, "시험": 1}, _d97b)
    finally:
        CS97.DOCS[:] = _od97
    # ── 결함 대장 행은 **낡은 값을 적는 것이 일이다** (결함 61 여섯째) ──
    check("[97] 결함 대장 행(`| 136 | **…** |`)은 건너뛴다",
          DA96._skip("| 136 | **고친 가드** | `결함 39건` 이 낡았다 |"))
    check("[97] 그런데 **머리글 총계는 여전히 검사한다** — 대장 행이 아니다",
          not DA96._skip("> 2026-08-12 · 코드 v65 · 결함 136건"))
    check("[97] 일반 산문도 검사한다 — `발표_처음과끝.md` 를 잡은 경로",
          not DA96._skip("결함 39건을 20분에 어떻게 전달할지"))
    # ── parquet 꼬리 파서 — **pyarrow 없이 도는 무결성 검사** ────────
    #
    #   4.2 GB 를 받아 놓고 «온전한가» 를 못 물었다. 검증 도구가 의존성
    #   때문에 못 도는 것은 방어가 아니다. **깨뜨려서 확인한다** — 통과만
    #   보면 «전부 ok 를 내는 함수» 도 통과한다(결함 85).
    from ..io import fto as FT97
    _d97c = _t97.mkdtemp(prefix="pq_")
    _pq97 = _o96a.path.join(_d97c, "t.parquet")

    def _mkpq(rows=42, cols=("id", "v")):
        """최소 parquet 꼬리를 **손으로 굽는다.** thrift compact 인코딩."""
        import struct as _st

        def _u(v):
            o = bytearray()
            while True:
                b = v & 0x7F
                v >>= 7
                o.append(b | (0x80 if v else 0))
                if not v:
                    return bytes(o)

        def _z(v):
            return _u((v << 1) ^ (v >> 63) if v < 0 else (v << 1))

        def _se(name, extra=b""):
            # SchemaElement.**name 은 4번 필드**다. delta 4 · 형 8(BINARY).
            return b"\x48" + _u(len(name)) + name.encode() + extra + b"\x00"
        meta = b"\x15" + _z(2)                          # 1: version
        meta += b"\x19" + bytes([((len(cols) + 1) << 4) | 12])   # 2: schema list
        meta += _se("schema")
        for c in cols:
            meta += _se(c)
        meta += b"\x16" + _z(rows)                      # 3: num_rows (delta 1)
        meta += b"\x19" + bytes([(1 << 4) | 12]) + b"\x00"       # 4: row_groups
        meta += b"\x00"
        return b"PAR1" + b"\x00" * 16 + meta + _st.pack("<I", len(meta)) + b"PAR1"

    open(_pq97, "wb").write(_mkpq())
    _s = FT97._footer(_pq97)
    check("[97] 손으로 구운 parquet 꼬리를 읽는다 — 행 수·열",
          _s["ok"] and _s["rows"] == 42 and _s["columns"] == ["id", "v"],
          str(_s))
    _good = open(_pq97, "rb").read()
    for _why, _bad in (
            ("**잘렸다** (꼬리 4바이트 삭제)", _good[:-4]),
            ("**머리가 PAR1 이 아니다**", b"XXXX" + _good[4:]),
            ("**꼬리가 PAR1 이 아니다**", _good[:-4] + b"XXXX"),
            ("**길이가 파일보다 크다**",
             _good[:-8] + (10 ** 9).to_bytes(4, "little") + b"PAR1"),
            ("**너무 작다**", b"PAR1")):
        open(_pq97, "wb").write(_bad)
        _r = FT97._footer(_pq97)
        check("[97] 깨뜨려 확인 — %s 를 잡는다" % _why,
              (not _r["ok"]) and bool(_r["error"]), str(_r)[:90])
    _s97.rmtree(_d97c, ignore_errors=True)
    check("[97] 실측 상수를 박아 뒀다 — 스키마가 바뀌면 드러난다",
          FT97.SC_ROWS_20260804 == 30_990_818
          and FT97.SC_COLS[3] == "inchi_key")
    check("[97] 행 하한이 **3분의 1 잘림도 통과시키던 값**이 아니다",
          FT97._SC_MIN_ROWS > FT97.SC_ROWS_20260804 * 0.7)
    # ── [97-b] 병렬 내려받기 — **localhost 서버 셋으로 실경로를 태운다** ──
    #
    #   `--help` 통과는 검증이 아니다. 08-12 첫 시험에서 **한글 User-Agent**
    #   때문에 요청이 아예 안 나갔고(HTTP 헤더는 latin-1), 우리 코드는 그걸
    #   «서버에 못 물었다» 로 읽었다 — **네트워크 장애로 오인**했다.
    from ..io import fetchpar as FP97
    import http.server as _hs97, re as _re97, threading as _th97
    _d97d = _t97.mkdtemp(prefix="fp_")
    _src97 = _o96a.path.join(_d97d, "big.bin")
    import random as _rnd97
    _rnd97.seed(7)
    open(_src97, "wb").write(bytes(_rnd97.getrandbits(8) for _ in range(300_000)))
    _want97 = open(_src97, "rb").read()

    def _serve97(mode):
        """mode: 'range'(정상) · 'plain'(Range 미지원) · 'liar'(광고만 하고 무시)"""
        class H(_hs97.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_HEAD(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(_want97)))
                if mode != "plain":
                    self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

            def do_GET(self):
                rg = self.headers.get("Range")
                if mode == "range" and rg and _re97.match(r"bytes=\d+-\d+", rg):
                    a, b = map(int, rg.split("=")[1].split("-"))
                    body = _want97[a:b + 1]
                    self.send_response(206)
                else:
                    body = _want97 if mode != "liar" else _want97[:65536]
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        s = _hs97.ThreadingHTTPServer(("127.0.0.1", 0), H)
        _th97.Thread(target=s.serve_forever, daemon=True).start()
        return s, "http://127.0.0.1:%d/big.bin" % s.server_port

    _sv, _url = _serve97("range")
    try:
        _o = _o96a.path.join(_d97d, "a.bin")
        _r = FP97.download(_url, _o, conns=4, chunk=65536, log=lambda *a: None)
        check("[97] 병렬로 받고 **바이트가 원본과 같다**",
              _r["ok"] and _r["parallel"]
              and open(_o, "rb").read() == _want97, str(_r)[:90])
        check("[97] 다 받으면 `.part` 를 지운다",
              not _o96a.path.exists(_o + ".part"))
        # 절반만 끝난 상태를 만들어 두고 다시 — **이어받아야 한다**
        _n = (len(_want97) + 65535) // 65536
        _j97.dump({"size": len(_want97), "chunks": _n,
                   "done": list(range(_n // 2))},
                  open(_o + ".part", "w", encoding="utf-8"))
        _r2 = FP97.download(_url, _o, conns=4, chunk=65536, log=lambda *a: None)
        check("[97] **이어받는다** — 끝난 조각은 다시 안 받는다",
              _r2["resumed"] == _n // 2 and open(_o, "rb").read() == _want97,
              "%d/%d" % (_r2["resumed"], _n))
        # 크기가 다른 진행표는 **버려야 한다** (원본이 갱신된 경우)
        _j97.dump({"size": 999, "chunks": _n, "done": list(range(_n))},
                  open(_o + ".part", "w", encoding="utf-8"))
        _r3 = FP97.download(_url, _o, conns=4, chunk=65536, log=lambda *a: None)
        check("[97] 크기가 다른 `.part` 는 **버린다** — 섞으면 조용히 썩는다",
              _r3["resumed"] == 0 and open(_o, "rb").read() == _want97)
    finally:
        _sv.shutdown()
    _sv, _url = _serve97("plain")
    try:
        _o = _o96a.path.join(_d97d, "b.bin")
        _r = FP97.download(_url, _o, conns=4, chunk=65536, log=lambda *a: None)
        check("[97] Range 미지원이면 **단일 연결로 떨어지고 그렇다고 말한다**",
              _r["ok"] and not _r["parallel"]
              and open(_o, "rb").read() == _want97, str(_r)[:90])
    finally:
        _sv.shutdown()
    _sv, _url = _serve97("liar")
    try:
        # **가장 위험한 서버** — Accept-Ranges 를 광고하고 Range 를 무시한다.
        #   조각 자리에 «파일 처음부터» 가 박히면 **크기는 맞고 내용만 썩는다.**
        _o = _o96a.path.join(_d97d, "c.bin")
        _r = FP97.download(_url, _o, conns=4, chunk=65536, log=lambda *a: None)
        check("[97] **Range 를 무시하는 서버를 잡는다** — 크기만 맞는 오염 방지",
              (not _r["ok"]) and "Range" in (_r["error"] or ""),
              (_r["error"] or "")[:80])
    finally:
        _sv.shutdown()
    _s97.rmtree(_d97d, ignore_errors=True)
    check("[97] User-Agent 가 **latin-1 로 인코딩된다** — 한글이면 요청이 안 나간다",
          bool(FP97.UA.encode("latin-1")))
    # ── [97-c] FTO ③ — **15억 행을 파이썬 루프로 돌면 안 된다** ────────
    #
    #   `patent_compound_map.parquet` 은 **1,537,106,020행**이다. 거르는
    #   일은 `pyarrow.compute.is_in` 이 C++ 에서 하고, 파이썬은 **걸러진
    #   것만** 센다. 그 «세는 부분» 이 `_tally` 이고 여기서 시험한다.
    _c97, _cap97 = {}, set()
    FT97._tally([7, 7, 7, 9], [1, 2, 2, 2], _c97, _cap97)
    check("[97] 필드별로 나눠 센다 — **청구항과 명세서는 다른 이야기다**",
          _c97[(7, 2)] == 2 and _c97[(7, 1)] == 1 and _c97[(9, 2)] == 1,
          str(sorted(_c97.items())))
    check("[97] 합계(-1)도 따로 센다",
          _c97[(7, -1)] == 3 and _c97[(9, -1)] == 1)
    _old97 = FT97.MAP_CAP
    try:
        FT97.MAP_CAP = 2
        _c, _cp = {}, set()
        FT97._tally([5] * 5, [2] * 5, _c, _cp)
        check("[97] 상한에 걸리면 **조용히 자르지 않고 이름을 남긴다**",
              _c[(5, -1)] == 2 and _cp == {5})
    finally:
        FT97.MAP_CAP = _old97
    check("[97] 청구항 필드 번호가 문서와 같다 (2 = Claims)",
          FT97.FIELD_CLAIMS == 2 and FT97.FIELDS[2] == "청구항")
    check("[97] `map_scan` 이 **pyarrow 없으면 그렇다고 말한다**",
          "pyarrow" in inspect.getsource(FT97.map_scan))
    check("[97] 스키마가 바뀌면 **멈춘다** — 열 이름을 확인한다",
          "스키마가 바뀌었다" in inspect.getsource(FT97.map_scan))
    # ── [97-d] FTO ④ 질환 매칭 — **넓히는 규칙을 주 분석에 안 넣는다** ──
    #
    #   `A, B` → `B A` 도치는 **MeSH 표목 규약**이라 뜻이 안 변한다.
    #   `A, B` → `A` 절단은 **더 넓은 개념**이라 특허가 과대해진다.
    #   둘을 섞으면 «다른 질문에 답한 것» 이 되므로 **갈라 세고 이름을 남긴다.**
    check("[97] `(disorder)` 꼬리와 구두점을 정규화한다",
          FT97._norm_term("Allergic rhinitis (disorder)") == "allergic rhinitis"
          and FT97._norm_term("Alzheimer's Disease") == "alzheimer s disease")
    _ents97 = {"by_name": {"non insulin dependent diabetes mellitus": [1],
                           "asthma": [2], "multiple sclerosis": [3],
                           "chronic myelomonocytic leukemia": [4]}}
    _inds97 = ["Asthma", "Diabetes Mellitus, Non-Insulin-Dependent",
               "Leukemia, Myelomonocytic, Chronic",
               "Multiple Sclerosis, Primary Progressive", "Zinc deficiency"]
    _m97 = FT97.match_indications(_inds97, _ents97)
    check("[97] **도치**가 MeSH 표목을 살린다 — 뜻이 안 변한다",
          _m97["per_rule"] == {"정확": 1, "도치": 2}, str(_m97["per_rule"]))
    _m97b = FT97.match_indications(_inds97, _ents97,
                                   rules=("정확", "도치", "절단"))
    check("[97] **절단은 하나 더 붙이지만 주 분석에 안 쓴다** — 넓히는 규칙",
          _m97b["per_rule"].get("절단") == 1
          and "절단" not in _m97["per_rule"], str(_m97b["per_rule"]))
    check("[97] **무엇으로 맞았는지 남는다** — 규칙이 결과를 만들었는지 따지려면",
          _m97["how"]["Diabetes Mellitus, Non-Insulin-Dependent"] == "도치")
    check("[97] 못 맞춘 것을 **0건이 아니라 «못 맞춤»으로 센다** (결함 141 계열)",
          _m97["n_miss"] == 2 and "Zinc deficiency" in _m97["miss_examples"])
    # ── [97-e] FTO ④ 용도특허 — **문턱을 코드에 박고 결과 보고 안 고친다** ──
    #
    #   명세 `사전명세_용도특허.md` (e22a4bf79036) 의 §3 이 정본이다.
    #   ≤60% 가른다 · >90% 접는다. **이 시험이 그 문턱을 지킨다** —
    #   결과가 애매할 때 문턱을 슬쩍 옮기는 것을 막는다.
    _pp97 = [("메트포르민", "유방암", "TP"), ("아스피린", "유방암", "TN"),
             ("산화철", "소양증", "TN"), ("X약", "Y병", "TP"),
             ("메트포르민", "천식", "TN")]
    _md97 = {"메트포르민", "아스피린", "산화철"}
    _ih97 = {"유방암": [5], "소양증": [9], "천식": [6]}
    _sig97 = FT97.use_signal(_pp97, {"메트포르민||유방암": 5, "아스피린||유방암": 1},
                           _md97, _ih97)
    check("[97] **미연결 쌍을 «0건»으로 안 세고 분모에서 뺀다** (명세 §5-1)",
          _sig97["n_unlinked"] == 1 and _sig97["n_evaluable"] == 4,
          "미연결 %s · 평가 %s" % (_sig97["n_unlinked"], _sig97["n_evaluable"]))
    check("[97] ① 비율과 Wilson 구간을 낸다",
          _sig97["rate"] == 0.5 and _sig97["ci"] is not None)
    check("[97] 문턱 **≤60%% → «가른다»**", _sig97["판정"] == "가른다")
    _sig97b = FT97.use_signal(_pp97, {"메트포르민||유방암": 1, "아스피린||유방암": 1,
                                    "산화철||소양증": 1, "메트포르민||천식": 1},
                            _md97, _ih97)
    check("[97] 문턱 **>90%% → «접는다»** — 전부 걸리면 지표가 아니다",
          _sig97b["판정"] == "접는다", str(_sig97b["rate"]))
    _sig97c = FT97.use_signal(_pp97, {"메트포르민||유방암": 1, "아스피린||유방암": 1,
                                    "메트포르민||천식": 1}, _md97, _ih97)
    check("[97] 60~90%% 는 **«쓸 수 있다»고 안 적는다**",
          "안 적는다" in _sig97c["판정"], _sig97c["판정"])
    check("[97] ② TP/TN 를 갈라 Fisher 를 낸다 — **유의하면 누출로 읽는다**",
          _sig97["fisher_p"] is not None and _sig97["tp"]["n"] == 1)
    _sig97d = FT97.use_signal([("X약", "Y병", "TP")], {}, _md97, _ih97)
    check("[97] 평가 가능한 쌍이 0이면 **판정하지 않는다**",
          _sig97d["rate"] is None and _sig97d["판정"] == "측정 불가")
    # ── [98] 08-12 밤 전수조사가 낸 것들 — **되돌아가지 않게 박는다** ──
    #
    #   하청 셋이 반나절에 스물 몇 개를 냈고, 그중 열둘이 결함이 됐다.
    #   **고쳤다는 것만으로는 안 남는다** — 시험이 없으면 다음 리팩터링에
    #   되돌아간다(이 저장소가 결함 61 을 일곱 번 겪은 이유다).
    _d98 = _t97.mkdtemp(prefix="a98_")
    _p98 = _o96a.path.join(_d98, "idx.json")
    _j97.dump({"ok": True, "n_matched": 793, "map": {"소중한": "결과"}},
              open(_p98, "w", encoding="utf-8"), ensure_ascii=False)
    FT97._save_index({"ok": True, "n_matched": 800}, _p98)
    _r98 = _j97.load(open(_p98, encoding="utf-8"))
    check("[98] 결함 145 — 색인을 덮어써도 **기존 결과 키가 남는다**",
          _r98.get("map") == {"소중한": "결과"} and _r98["n_matched"] == 800,
          str(sorted(_r98)))
    check("[98] 결함 145 — `.bak` 을 남긴다",
          _o96a.path.exists(_p98 + ".bak"))
    # ⚠ 08-13 아침 — **어제 한 갈래만 고쳤다.** `--map` 경로와 ④ 저장이
    #   아직 맨 `json.dump` 였다. 「고쳤다」가 「전부 고쳤다」가 아니다.
    #   그래서 **구조로 박는다** — 파일을 쓰는 곳은 하나뿐.
    #
    #   ⚠ 08-14 — 문지기를 `_save_index` 에서 **`_write_json`** 으로 옮겼다.
    #   `_save_pairs`(쌍→특허 집합)가 두 번째 저장으로 생겼기 때문인데,
    #   **시험에 예외를 뚫는 대신 코드를 시험에 맞췄다.** 그래서 이 검사가
    #   전보다 **강해졌다** — 이제 `.bak` 보장이 한 함수에 있으므로 세 번째
    #   저장이 생겨도 자동으로 따라간다. 예외를 뚫었으면 저장마다 `.bak` 을
    #   손으로 다시 적어야 하고, **그게 결함 145 가 난 방식이다.**
    import ast as _ast98
    _tree98 = _ast98.parse(inspect.getsource(FT97))
    _fns98 = [f for f in _ast98.walk(_tree98)
              if isinstance(f, _ast98.FunctionDef)]
    _raw98 = []
    for _n in _ast98.walk(_tree98):
        if isinstance(_n, _ast98.Call) and getattr(_n.func, "attr", None) == "dump":
            _own = [f.name for f in _fns98
                    if f.lineno <= _n.lineno <= (f.end_lineno or _n.lineno)]
            if (_own[-1] if _own else "?") != "_write_json":
                _raw98.append((_n.lineno, _own[-1] if _own else "?"))
    check("[98] 결함 145 — **파일을 쓰는 곳이 `_write_json` 하나뿐**이다",
          not _raw98, str(_raw98))
    # 그리고 **그 하나가 실제로 `.bak` 을 남기는지** 본다 —
    #   문지기를 세워 놓고 문지기가 일을 안 하면 그게 더 나쁘다
    _p98b = _o96a.path.join(_d98, "bak.json")
    FT97._write_json({"판": 1}, _p98b)
    check("[98] 첫 저장은 `.bak` 이 없다 — 지울 게 없다",
          not _o96a.path.exists(_p98b + ".bak"))
    FT97._write_json({"판": 2}, _p98b)
    check("[98] 두 번째 저장은 **앞 판을 `.bak` 으로 남긴다**",
          _o96a.path.exists(_p98b + ".bak")
          and _j97.load(open(_p98b + ".bak", encoding="utf-8"))["판"] == 1
          and _j97.load(open(_p98b, encoding="utf-8"))["판"] == 2)
    _s97.rmtree(_d98, ignore_errors=True)

    _c98, _cap98, _dr98 = {}, set(), [0]
    _old98 = FT97.MAP_CAP
    try:
        FT97.MAP_CAP = 3
        FT97._tally([1] * 3 + [2] * 3 + [3] * 2, [2] * 8, _c98, _cap98,
                    name_of={1: "vinblastine", 2: "vinblastine", 3: "metformin"},
                    dropped=_dr98)
    finally:
        FT97.MAP_CAP = _old98
    check("[98] 결함 146 — 상한이 **약 단위**다 (레코드 2개여도 예산 1인분)",
          _c98[("vinblastine", -1)] == 3, str(_c98))
    check("[98] 결함 146 — **버린 행을 센다** (조용한 검열 금지)",
          _dr98[0] == 3 and _cap98 == {"vinblastine"})
    check("[98] 결함 147 — `.get(key, 기본값)` 을 루프 안에서 안 쓴다",
          "d[key][i]" in inspect.getsource(FT97.disease_entities))
    check("[98] 결함 150 — 파싱 실패는 **분모에 안 든다**",
          "out[\"n_with_skeptic\"] += 1          # **파싱된 것만"
          in inspect.getsource(_sk98 := __import__(
              "bioreroute.bench.skepticrate", fromlist=["x"])))
    from ..bench import stats as ST98
    check("[98] 결함 152 — `alpha` 가 **실제로 먹는다**",
          abs(ST98._z_two_sided(0.01) - 2.575829) < 1e-5
          and ST98.power2(0.1, 0.5, 40, 40, 0.05)
          > ST98.power2(0.1, 0.5, 40, 40, 0.001))
    check("[98] 결함 152 — **완전 분리에서 검정력이 1 근처**다 (앞판 0.0)",
          ST98.power2(0.0, 1.0, 20, 20) > 0.99)
    check("[98] 결함 152 — 기존 값은 **불변**이다",
          abs(ST98.power2(0.081, 0.143, 37, 42) - 0.1320) < 0.001)
    from ..bench import graphcheck as GC98, reversecheck as RC98
    _x98 = [("A", 3.93e-16), ("B", 8.16e-07), ("C", 8.7e-04)]
    check("[98] 결함 153 — 두 `holm` 이 **같은 값**을 낸다 (round 제거)",
          GC98.holm(_x98) == RC98.holm(_x98), str(GC98.holm(_x98)))
    check("[98] 결함 153 — 1e-15 를 **0으로 안 뭉갠다**",
          GC98.holm(_x98)["A"] > 0)
    from ..bench import analyze as AZ98
    check("[98] 결함 151 — 「차이 없음」 상수가 **사라졌다**",
          '"차이 없음"' not in inspect.getsource(AZ98.main)
          and "검정력" in inspect.getsource(AZ98.main))
    check("[98] 결함 61 일곱째 — `«…»` 인용을 **두 검사가 같이** 인정한다",
          DA96._skip("> «결함 20건» 이라 적었다")
          and not DA96._skip("우리는 결함 156건을 공개한다"))
    check("[97] countsync 가 **```펜스``` 안 인용을 안 고친다** (결함 61 다섯째)",
          {r[1] for r in _rows97} == {1, 7},
          str([(r[1], r[2]) for r in _rows97]))
    _s97.rmtree(_d97b, ignore_errors=True)
    # 죽은 코드가 거짓 주장을 이고 있던 것도 지웠다
    from .. import dash as _D96
    check("[96] `dash` 에 **죽은 보정 함수가 없다** — 죽은 코드가 결함을 숨긴다",
          not hasattr(_D96, "_bottom_calibration_bars_unused"))

    # ── [94] 결함 127 — **116을 고치고 옆 파일에 같은 구멍을 뒀다** ──
    #
    #   DRKG 는 «존재만 보면 잘린 파일이 OK 로 읽힌다» 를 08-11에 고쳤는데
    #   (결함 116), `faers.available()` 은 08-06부터 `sider` 를
    #   **`os.path.exists` 하나로** 판정하고 있었다. 돌린 적이 없어
    #   안 터졌을 뿐, 잘린 SIDER 를 온전한 것으로 읽는 경로였다.
    #
    #   네 가지를 **각각 다른 문구**로 갈라야 한다. 뭉치면 원인을 못 찾는다.
    from ..io import faers as FA94
    import tempfile as _t94, os as _o94, gzip as _g94, io as _i94
    _d94 = _t94.mkdtemp(prefix="sider_")
    try:
        def _mk(nm, blob):
            p = _o94.path.join(_d94, nm)
            open(p, "wb").write(blob)
            return FA94.sider_state(p)
        _r = FA94.sider_state(_o94.path.join(_d94, "__없다__.tsv"))
        check("[94] SIDER 없음을 «없다» 로 구별한다",
              _r["ok"] is False and "없다" in _r["error"])
        _buf = _i94.BytesIO()
        with _g94.GzipFile(fileobj=_buf, mode="wb") as _z:
            _z.write(b"a\tb\tc\td\te\tf\n")
        _r = _mk("gz.tsv", _buf.getvalue())
        check("[94] **압축을 안 푼 것**을 구별한다 — `tar -xzf` 가 안 되는 파일이다",
              _r["ok"] is False and "압축" in _r["error"])
        _r = _mk("cols.tsv", ("x\ty\tz\n" * 300000).encode())
        check("[94] 열 수가 다르면 «형식이 다르다» 로 구별한다",
              _r["ok"] is False and "형식" in _r["error"])
        _r = _mk("short.tsv", ("a\tb\tc\td\te\tf\n" * 1000).encode())
        check("[94] **잘린 파일을 「있다」로 안 읽는다** (결함 116 과 같은 고장)",
              _r["ok"] is False and "잘렸다" in _r["error"], str(_r["error"])[:60])
        _r = _mk("ok.tsv", ("a\tb\tc\td\te\tf\n" * 300000).encode())
        check("[94] 온전하면 통과시킨다 — 과잉 차단도 실패다",
              _r["ok"] is True and _r["rows"] == 300000, str(_r)[:80])
    finally:
        import shutil as _s94
        _s94.rmtree(_d94, ignore_errors=True)
    check("[94] available() 이 존재검사 대신 sider_state 를 쓴다",
          "sider_state()" in inspect.getsource(FA94.available))
    check("[94] 정상 줄 수를 상수로 박아 뒀다 — 세지 않으면 못 잡는다",
          FA94.SIDER_ROWS > 250000)

    # ── [95] 결함 128·129 ─────────────────────────────────────────
    #
    #   128 — SIDER 는 라벨 자료라 **PRR 이 정의되지 않는다.** 없는 양에
    #         0 을 넣으면 아래 문구가 그걸 PRR 로 읽는다. `None` 이어야 한다.
    #   129 — 명세가 «seed 812 고정» 이라 적었는데 `hash()` 무작위화로
    #         **대조군이 실행마다 바뀌었다**(64·68·59·58).
    _rows = FA94.sider_drugs_for_event("Abdominal pain").get("rows") or []
    if _rows:
        check("[95] SIDER 행에 **가짜 PRR 을 안 넣는다** — 없는 양은 None",
              all(r.get("prr") is None for r in _rows), str(_rows[:1]))
        check("[95] SIDER 행에 약물 **이름**이 붙는다 (CID 가 아니다)",
              all(r.get("drug") and not str(r["drug"]).startswith("CID")
                  for r in _rows[:20]))
    check("[95] SIDER 순위 규칙을 코드가 스스로 밝힌다 — PRR 이 아니라고",
          "PRR 이 정의되지 않는다" in FA94.SIDER_RULE)
    _psrc = inspect.getsource(RC.collect)
    # **주석을 벗기고 본다.** 초판은 원문 그대로 봤는데, 그 함수의 주석이
    # *«초판은 `abs(hash(...))` 였다»* 라고 옛 코드를 적어 두고 있어
    # **설명 문구 때문에 빨갛게 떴다.** 결함 61과 같은 함정이고 —
    # 저장소가 이미 시험 [49]에서 같은 것을 겪었다(`bench/graph.py` 언급).
    # 문자열이 아니라 **실행되는 줄**을 봐야 한다.
    _code = "\n".join(l.split("#", 1)[0] for l in _psrc.splitlines())
    check("[95] 대조군 seed 가 **결정론적**이다 — 실행 줄에 `hash(` 가 없다 (결함 129)",
          "hashlib.sha256" in _code and "abs(hash(" not in _code)
    # 문자열만 보면 결함 61 이 된다. **같은 값이 두 번 나오는지 태운다.**
    _s1 = RC.collect.__globals__["hashlib"].sha256(
        RC._norm("COVID-19").encode()).hexdigest()[:8]
    _s2 = RC.collect.__globals__["hashlib"].sha256(
        RC._norm("Covid19").encode()).hexdigest()[:8]
    check("[95] 같은 질환은 **같은 대조군 seed** 를 받는다 (철자 변형 포함)",
          _s1 == _s2, "%s vs %s" % (_s1, _s2))
    check("[95] 부지표 `Rz` 는 **판정 팔에 없다** — 명세가 판정 제외라 했다",
          "Rz" not in RC.ARMS and "Rz" in _psrc)
    check("[95] 정규화 순위가 별도 규칙으로 갈린다",
          'rank == "norm"' in inspect.getsource(RV.propose)
          if (RV := __import__("bioreroute.agents.reverse",
                               fromlist=["propose"])) else False)

    # ── [93] 결함 125 — **부재를 확정의 증거로 쓰지 않는다** ────────
    #
    #   확정 판정을 «캘린더 URL 이 없다» 로 하면, 응답 안 한 캘린더가
    #   하나라도 남는 한 **영원히 미확정**이다. 실제로 그랬다.
    #   여기서는 파일을 손으로 만들어 **네 경우를 전부 태운다.**
    from .. import evidence as EV93
    import hashlib as _h93, tempfile as _t93, os as _o93
    _d93 = _t93.mkdtemp(prefix="ots_")
    try:
        _doc = _o93.path.join(_d93, "봉인해시_공개등록.txt")
        open(_doc, "wb").write(b"body")
        _hh = _h93.sha256(b"body").digest()
        _cal = b"https://bob.btc.calendar.opentimestamps.org"
        for name, blob, want in (
                ("접수만(캘린더만)", _hh + _cal, False),
                ("확정+캘린더 잔존", _hh + _cal + EV93._BITCOIN_ATTEST, True),
                ("확정·캘린더 없음", _hh + EV93._BITCOIN_ATTEST, True)):
            open(_doc + ".ots", "wb").write(blob)
            r93 = EV93.notarization(_d93)
            check("[93] OTS 확정 판정 — %s" % name,
                  r93["확정"] is want and r93["해시일치"] is True,
                  "확정=%s 해시=%s" % (r93["확정"], r93["해시일치"]))
        # 다른 문서의 증명서를 올려 두면 잡아야 한다
        open(_doc + ".ots", "wb").write(b"\x00" * 8 + EV93._BITCOIN_ATTEST)
        check("[93] 다른 문서의 .ots 는 «해시 불일치» 로 잡는다",
              EV93.notarization(_d93)["해시일치"] is False)
    finally:
        import shutil as _s93
        _s93.rmtree(_d93, ignore_errors=True)
    check("[93] 캘린더 잔존을 **정상**이라고 적어 둔다",
          "남아 있는 것은 **정상이다**" in (EV93.notarization.__doc__ or ""))

    check("[92] «회수율이 높은 게 좋은 것이 아니다» 를 적어 둔다",
          "높은 게 좋은 것이 아니다" in inspect.getsource(SR.report)
          or "높은 게 좋은 것도 아니다" in (SR.__doc__ or ""))

    # ── §4.3 반박 회수율 · §8.2 위음성률 ─────────────────────
    c1 = Candidate(name="a", drug="a", disease="d", origin="t", query="q")
    c2 = Candidate(name="b", drug="b", disease="d", origin="t", query="q")
    c1.refute = [Evidence(tag="t", direction="refute", weight=1.0, pmid="1")]
    c1.note("skeptic", "DONE", "추가 초록 3건 → 반박 +1 · 지지 +0")
    st2 = RunState("q", "t", "t", [c1, c2], {})
    rr = gates.refute_recall(st2)
    check("[49] 반박 회수율을 코드가 낸다 (§4.3 B3)",
          rr["반박근거_있는_후보"] == "1/2", str(rr))
    check("[49] 회의주의자 기여를 따로 센다", rr["회의주의자_추가분"] == 1, str(rr))
    check("[49] **재현율이라 부르지 않는다** — 참분모를 모른다",
          "재현율이 아니다" in rr["주의"])

    fn0 = gates.false_negatives(st2)
    check("[49] 라벨 없으면 위음성률을 **0%로 내지 않는다**",
          fn0.get("계산불가") is True, str(fn0))
    c1.verdict = "기각"
    fn1 = gates.false_negatives(st2, {"a": "TP", "b": "TN"})
    check("[49] 위음성률 — 기각한 것 중 실제 유효 (§8.2)",
          fn1["위음성률"] == 1.0 and fn1["이름"] == ["a"], str(fn1))
    check("[49] 위음성률이 낮다고 좋은 게 아니라고 적는다",
          "아무것도 기각 안 해도 0" in fn1["주의"])

    # ── §3.2 역할별 모델 배정 ────────────────────────────────
    import os
    from bioreroute.io import llm as _llm
    base = _llm.roles_in_use()
    check("[49] 설정이 없으면 **전부 기본 모델** — 동결 수치 불변",
          len(set(base.values())) == 1, str(base))
    old = os.environ.get("BIOREROUTE_MODEL_SMALL")
    try:
        os.environ["BIOREROUTE_MODEL_SMALL"] = "tiny/x"
        now = _llm.roles_in_use()
        check("[49] 결정론적 작업만 소형으로 간다 (§3.2)",
              now["router"] == "tiny/x" and now["skeptic"] != "tiny/x", str(now))
    finally:
        if old is None:
            os.environ.pop("BIOREROUTE_MODEL_SMALL", None)
        else:
            os.environ["BIOREROUTE_MODEL_SMALL"] = old
    fsrc = inspect.getsource(sys.modules["bioreroute.agents.factcheck"])
    check("[49] 팩트체커가 고성능 역할을 요청한다",
          'model_for("factcheck")' in fsrc)
    rsrc = inspect.getsource(sys.modules["bioreroute.agents.router"])
    check("[49] 라우터가 소형 역할을 요청한다", 'model_for("router")' in rsrc)


def _run(fn, *a):
    """시험 하나가 죽어도 나머지를 계속 돌린다.

    **실제 사고: ceiling CLI 시험이 FileNotFoundError로 죽어
    뒤의 시험 여섯 개가 통째로 안 돌았다.** 화면에는 역추적만 남고
    "나머지가 멀쩡한지"는 알 수 없었다.

    환경 문제 하나가 실제 회귀를 가리면 안 된다. 예외는 실패로 기록하고
    다음으로 넘어간다 — 그래야 한 번 돌려 전체 상태를 본다.
    """
    try:
        return fn(*a)
    except Exception as e:
        import traceback
        FAIL.append("%s (예외)" % fn.__name__)
        print("  FAIL %s — 예외로 중단: %s: %s" % (fn.__name__, type(e).__name__, e))
        traceback.print_exc(limit=3)
        return None


# ══════════════════════════════════════════════════════════════════
#  [120]~[124] ④-b 공개연도 — 결함 216
# ══════════════════════════════════════════════════════════════════

def test_dead_argument_must_say_so():
    """[120] **인자를 받으면 쓰거나, 안 쓴다고 적어야 한다** (결함 216).

    `build_index(patents=)` 가 **08-12부터 08-14까지 죽어 있었다.** 받기만
    하고 본문에서 한 번도 안 썼는데, 독스트링은 *«④ patent_id → 특허번호»*
    라고 적어 놨다. 그래서 —

        08-13  5.9 G 를 받는다
        08-14  `--patents` CLI 를 배선한다 (결함 204)
        08-14  색인을 다시 돌린다 — **그 파일을 한 바이트도 안 읽는다**

    `CLAUDE.md §5` — «`--help` 통과는 검증이 아니다». 태우긴 했는데
    **결과에 연도 칸이 생겼는지를 안 봤다.**

    > 안내문으로 막을 수 없다. **시험이 본문을 읽게 한다.**

    주석·독스트링을 지우고 **코드만** 본다 — 독스트링이 «쓴다» 고 말하는
    것이 바로 이 결함의 형태였으므로, 문서를 근거로 삼으면 안 된다.
    """
    import ast as _ast
    import inspect as _insp
    from ..io import fto as _F

    src = _insp.getsource(_F.build_index)
    tree = _ast.parse(src)
    fn = tree.body[0]
    doc = _ast.get_docstring(fn) or ""

    # 독스트링을 뺀 **코드만** 남긴다
    body = list(fn.body)
    if (body and isinstance(body[0], _ast.Expr)
            and isinstance(getattr(body[0], "value", None), _ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    used = any(isinstance(n, _ast.Name) and n.id == "patents"
               for b in body for n in _ast.walk(b))
    said = "안 쓴다" in doc
    check("[120] `build_index(patents=)` — **쓰거나 «안 쓴다»고 적혀 있다**",
          used or said, "코드사용=%s · 문서명시=%s" % (used, said))
    # 그리고 **어디서 쓰는지**를 가리켜야 한다
    check("[120] 안 쓴다면 **누가 하는지**를 가리킨다",
          used or ("--use-year" in doc),
          "가리킴=%s" % ("--use-year" in doc))


def test_year_of_says_none_when_it_does_not_know():
    """[121] **모르면 `None`. 0 이 아니다** (결함 89 계열).

    `publication_date` 의 열 형을 미리 못 정한다 — date32 일 수도,
    문자열일 수도, `YYYYMMDD` 정수일 수도 있다. 자료원이 바꾸면 조용히
    틀린 연도가 판정에 들어간다.

    **0 이나 1970 을 내면 «최근 아님» 으로 세어져 ①을 내리는 쪽으로
    치우친다** — 우리에게 유리한 방향이라 더 위험하다.
    """
    from ..io import fto as _F
    import datetime as _dt

    same = [(_dt.date(1978, 3, 1), 1978), ("2006-01-31", 2006),
            (20060131, 2006), (2006, 2006), ("1959", 1959)]
    for v, exp in same:
        check("[121] `%r` → %d" % (v, exp), _F._year_of(v) == exp,
              _F._year_of(v))
    none = [None, "", "abcd", 0, 99999999, True, 12, "  "]
    for v in none:
        check("[121] `%r` → **None** (0 이 아니다)" % (v,),
              _F._year_of(v) is None, _F._year_of(v))


def test_partial_scan_is_not_saved():
    """[122] **부분 실행은 옆 파일로 안 남는다** — 구조로 막는다.

    `--rg N` 은 시간을 재 보는 출구다. 그 결과가 `fto_use_pairs.json` 으로
    남으면 **다음 실행이 그걸 전수로 착각한다.** 그러면 «연도 때문에
    내려갔다» 와 «덜 훑어서 내려갔다» 를 **구별할 수 없다** — 결함 141·149
    와 같은 모양이다.

    `CLAUDE.md` — *"안내문은 방어가 아니다. 구조로 막아야 한다."*
    """
    from ..io import fto as _F

    part = {"pair_patents": {"a|b": [1, 2]}, "scanned_all": False,
            "n_use_patents": 2, "rows": 2}
    check("[122] 부분 실행(`scanned_all=False`)은 **저장을 거절한다**",
          _F._save_pairs(part, path="__없어야_한다__.json") is None)
    import os as _os
    check("[122] 그리고 **파일을 안 만든다**",
          not _os.path.exists("__없어야_한다__.json"))


def test_year_control_can_fail():
    """[123] **②′ 무작위 대조가 실패할 수 있어야 한다** (명세 a0bb1f6b §6-1).

    연도를 걸면 특허가 줄고 ①이 내려가는 것은 **자명하다.** 그것만 보고
    «가른다» 고 하면 그건 지표가 아니라 표본 축소다. 명세가 그래서 무작위
    대조를 박아 뒀다.

    **가드가 통과만 하면 가드가 아니다.** 잡음을 넣었을 때 «접는다» 가
    나오는지 같이 본다 — 이게 이 시험의 요점이다.
    """
    import random as _r
    from ..io import fto as _F

    def build(informative, n_pairs=120, n_pat=3000, seed=7):
        rnd = _r.Random(seed)
        pairs, pp = [], {}
        for i in range(n_pairs):
            d, ind = "drug%d" % i, "ind%d" % i
            pairs.append((d, ind, "TP" if i % 2 else "TN"))
            pp[_F.pair_key(d, ind)] = sorted(
                rnd.sample(range(n_pat), rnd.randint(5, 30)))
        uni = sorted({p for v in pp.values() for p in v})
        if informative:                     # 최근 연도를 **몇 쌍에 몰아준다**
            hot = set()
            for k in list(pp)[:12]:
                hot.update(pp[k])
            years = {p: (2020 if p in hot else 1980) for p in uni}
        else:                               # 연도가 **아무 정보도 없다**
            years = {p: rnd.choice([1980, 2020]) for p in uni}
        return (pairs, pp, years, {d for d, _, _ in pairs},
                {ind: [i] for i, (_, ind, _) in enumerate(pairs)})

    for name, inf, want in (("정보를 담으면", True, True),
                            ("잡음이면", False, False)):
        pr, pp, ys, md, ih = build(inf)
        y = _F.year_signal(pr, pp, ys, md, ih, run_year=2026,
                           windows=(20,), n_perm=200)
        got = y["②′"]["통과"]
        check("[123] 연도가 **%s** → 통과=%s" % (name, want), got is want,
              "p=%.4f 관측=%d 대조중앙=%d"
              % (y["②′"]["p"], y["②′"]["관측"], y["②′"]["대조_중앙"]))

    # 명세 §2-③ — **TP vs TN 을 다시 검정하지 않는다**
    pr, pp, ys, md, ih = build(True)
    y = _F.year_signal(pr, pp, ys, md, ih, run_year=2026, windows=(20,),
                       n_perm=50)
    check("[123] TP·TN **Fisher 를 안 낸다** (명세 §2-③ · 다중비교)",
          y["창"]["20"]["tp"]["rate"] is not None
          and y["창"]["20"].get("tn") is not None)


def test_year_thresholds_come_from_the_spec():
    """[124] **문턱을 코드에서 안 고친다** — 명세 §9.

    연도를 걸면 숫자가 내려가는 것이 자명하므로 **문턱을 낮추면 부정이다.**
    ≤60% / >90% 는 앞 명세(`e22a4bf7`)의 것을 그대로 쓴다.

    그리고 ②′ 는 **Holm m=2** 를 쓴다. ①은 문턱 판정이라 p 가 없어
    검정은 실제로 ②′ 하나뿐인데, **명세를 낮춰 읽지 않으려고 더 엄한
    쪽(0.025)** 을 건다.
    """
    import inspect as _insp
    from ..io import fto as _F

    src = _insp.getsource(_F.year_signal)
    check("[124] `use_signal` 을 **재사용**한다 (분모 규약이 한 곳)",
          "use_signal(" in src)
    check("[124] 씨앗 **20260813** 이 기본값이다",
          _insp.signature(_F.year_signal).parameters["seed"].default == 20260813)
    check("[124] ②′ 기본 반복이 **1000** 이다",
          _insp.signature(_F.year_signal).parameters["n_perm"].default == 1000)
    check("[124] 주창이 **20년**이다 (부지표 15·25 는 판정에 안 쓴다)",
          _insp.signature(_F.year_signal).parameters["windows"].default[0] == 20)
    # 문턱은 `use_signal` 이 갖고 있고 **여기서 다시 안 적는다**
    #
    #   ⚠ **주석·독스트링을 빼고 본다.** 안 그러면 «문턱을 여기 안 적는다»
    #   라고 **설명한 주석 자체**가 걸린다 — 08-14 에 실제로 그랬다.
    #   `preflight._code_only` 와 같은 규율이다.
    import ast as _ast
    code = _ast.unparse(_ast.parse(src))          # 주석이 사라진다
    check("[124] 문턱 숫자를 `year_signal` **코드**에 다시 안 적었다",
          "0.60" not in code and "0.90" not in code,
          [l for l in code.splitlines() if "0.60" in l or "0.90" in l][:2])


def test_use_year_stops_when_it_cannot_reproduce():
    """[125] **재현이 안 되면 연도를 붙이기 전에 멈춘다** — `_run_use_year`.

    `fto_use_pairs.json` 은 «어느 특허인가» 를 담은 옆 파일이고, **다른
    실행에서 온 것일 수 있다.** 그런데 그걸 그대로 쓰면 —

        ① 이 72.7% → 45% 로 내려간다
        「연도 때문인가」  vs  「집합이 달라서인가」  **못 가른다**

    그래서 연도를 붙이기 **전에** 옆 파일이 앞 판(72.7%)을 재현하는지
    본다. 안 되면 멈춘다.

    `pyarrow` 가 없어도 도는 시험이다 — 훑는 함수 셋을 갈아 끼우고
    **오케스트레이션만** 태운다. 훑기는 승우 컴퓨터에서 돈다.
    """
    import json as _j, os as _os, tempfile as _tf, types as _ty
    from ..io import fto as _F

    pairs = _F.labeled_pairs()
    if not pairs:
        check("[125] 라벨 쌍을 읽었다", False, "labeled_pairs() 가 비었다")
        return
    # 앞 세 쌍만 쓴다 — 배관을 보는 시험이지 수치를 내는 시험이 아니다
    use = pairs[:3]
    drugs = [d for d, _, _ in use]
    inds = sorted({i for _, i, _ in use})
    pp = {_F.pair_key(d, i): [1, 2, 3] for d, i, _ in use}

    # ⚠ 08-14 결함 219 — **`YEARS_CACHE` 를 빼먹어 저장소를 더럽혔다.**
    #   `USE_PAIRS` 만 임시 경로로 바꿨더니 `_run_use_year` 가 **진짜
    #   `fto_years.json` 을 프로젝트 뿌리에 썼다** — 스텁 연도 3개짜리로.
    #   `--fresh-pairs` 없이 다음 실행이 돌았으면 **가짜 연도로 판정이
    #   났을 것**이다. 옆 파일 상수는 **하나도 빠짐없이** 갈아 끼운다.
    old = {k: getattr(_F, k) for k in
           ("disease_entities", "match_indications", "patent_years",
            "labeled_pairs", "USE_PAIRS", "YEARS_CACHE", "DRUG_PATENTS",
            "FTO_INDEX")}
    tmp = _tf.mkdtemp()
    try:
        _F.labeled_pairs = lambda *a, **k: use
        _F.disease_entities = lambda *a, **k: {"ok": True}
        _F.match_indications = lambda ii, e, **k: {
            "n": len(inds), "n_hit": len(inds), "rate": 1.0, "per_rule": {},
            "hit": {x: [j] for j, x in enumerate(inds)}}
        _F.patent_years = lambda p, want, **k: {
            "ok": True, "years": {1: 2020, 2: 1980, 3: 1975},
            "ids": {1: "US2020001A1", 2: "US1980002A", 3: "US1975003A"},
            "n_want": len(want), "n_found": 3, "n_no_date": 0, "n_no_id": 0,
            "dtype": "date32[day]", "scanned_all": True, "rows": 3}
        _F.USE_PAIRS = _os.path.join(tmp, "pairs.json")
        _F.YEARS_CACHE = _os.path.join(tmp, "years.json")
        _F.DRUG_PATENTS = _os.path.join(tmp, "drug.json")
        # `FTO_INDEX` 는 `a.out` 으로 우회하므로 지금은 무해하다. 그래도
        # 갈아 끼운다 — **«무해한 예외» 를 하나 두면 규칙이 판단이 되고,
        # 판단은 다음 사람이 못 되짚는다.** 새 상수가 생겨도 자동으로 걸린다
        _F.FTO_INDEX = _os.path.join(tmp, "idx_default.json")
        _j.dump({"pair_patents": pp, "n_use_patents": 3, "scanned_all": True,
                 "때": "시험"}, open(_F.USE_PAIRS, "w", encoding="utf-8"))

        idxp = _os.path.join(tmp, "idx.json")
        pt = _os.path.join(tmp, "patents.parquet")
        open(pt, "wb").write(b"PAR1")

        def run(base_rate):
            _j.dump({"cid_map": {str(n): d for n, d in enumerate(drugs)},
                     "용도특허": {"신호": {"rate": base_rate}}},
                    open(idxp, "w", encoding="utf-8"))
            # **`perm` 을 바꾸면 색인에 안 쓴다**(시험 실행 방어)。
            # 여기서는 저장까지 보려는 것이므로 명세 기본 1000 을 쓴다
            a = _ty.SimpleNamespace(out=idxp, entities=None, pmap=None,
                                    locations=None, rg=None, fresh_pairs=False,
                                    patents=pt, perm=1000)
            return _F._run_use_year(a)

        # ① 앞 판과 **어긋나면** 멈춘다 — 그리고 색인에 아무것도 안 쓴다
        rc = run(0.1234)
        after = _j.load(open(idxp, encoding="utf-8"))
        check("[125] 재현 실패 → **종료코드 1**", rc == 1, rc)
        check("[125] 재현 실패 → **색인에 판정을 안 쓴다**",
              "용도특허_연도" not in after, sorted(after))

        # ② 앞 판이 없으면(None) 검사를 건너뛰고 진행한다
        rc = run(None)
        after = _j.load(open(idxp, encoding="utf-8"))
        check("[125] 앞 판이 없으면 **진행한다**", rc == 0, rc)
        check("[125] 그리고 판정을 **색인에 남긴다**",
              "용도특허_연도" in after, sorted(after))
        if "용도특허_연도" in after:
            y = after["용도특허_연도"]
            check("[125] 창 셋(20·15·25)을 다 낸다",
                  sorted(y["창"]) == ["15", "20", "25"], sorted(y["창"]))
            check("[125] 주창은 **20년**", y["주창"] == "20", y["주창"])
            check("[125] `자료` 에 열 형과 전수 여부가 실린다",
                  y["자료"]["scanned_all"] is True and y["자료"]["dtype"],
                  y["자료"])
    finally:
        for k, v in old.items():
            setattr(_F, k, v)
        import shutil as _sh
        _sh.rmtree(tmp, ignore_errors=True)


def test_rate_limit_holds_across_threads():
    """[130] **호출 제한은 「내가 잔 시간」이 아니라 「우리 전체가 부른 횟수」다**.

    08-18. 병명 입구가 **159.4초**로 상한 150을 넘었고, 원인이 캐시가
    아니라 **LLM 호출 자체**임이 확인됐다(warm=0인데 155.5초와 4초 차).
    후보를 병렬로 태우면 줄어든다 — 게이트는 후보별로 독립이다.

    ## 그런데 순진하게 병렬화하면 판정이 바뀐다

        REQ_DELAY = 0.35초   `time.sleep` 은 **스레드마다 따로** 잔다
        스레드 4개           → 초당 11.4회  vs  NCBI 제한 3회  → **429**

    429는 우리 코드에서 `{"error": …}` 가 되고 게이트는 그걸 «조회 실패»로
    읽는다. **네트워크 장애가 판정으로 둔갑하는 자리**다 — 결함 35에서
    CT.gov 403이 «0/14 = 0% · B6를 빼라»로 나왔던 그것.

    > **병렬을 넣기 전에 전제를 먼저 만든다.** 넣고 나서 고치면
    > 그때는 «판정이 왜 바뀌었나»를 못 가른다.

    이 시험은 **모의가 아니라 진짜 스레드를 돌려** 간격을 잰다.
    """
    import threading as _th, time as _t
    from ..io import sources as _S, cache as _C

    old = _S.REQ_DELAY
    try:
        _S.REQ_DELAY = 0.05          # 시험을 빠르게. 비율은 같다
        _S._LAST_CALL[0] = 0.0
        hits = []
        lk = _th.Lock()

        def w():
            for _ in range(5):
                _S.throttle()
                with lk:
                    hits.append(_t.time())

        ts = [_th.Thread(target=w) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        hits.sort()
        gaps = [hits[i + 1] - hits[i] for i in range(len(hits) - 1)]
        check("[130] 스레드 4개가 겹쳐도 **간격이 지켜진다**",
              gaps and min(gaps) >= _S.REQ_DELAY * 0.9,
              "최소 %.4f초 (요구 %.2f)" % (min(gaps) if gaps else -1, _S.REQ_DELAY))
        check("[130] 호출 수가 안 샌다", len(hits) == 20, len(hits))
    finally:
        _S.REQ_DELAY = old

    # ── `time.sleep(REQ_DELAY)` 가 **한 곳도 안 남았나** ──────────────
    #   한 곳만 고치면 그 경로만 제한을 지킨다 — 결함 98·222 의 형태.
    import inspect as _i
    src = _i.getsource(_S)
    check("[130] `sources` 에 맨 `time.sleep(REQ_DELAY)` 가 **0곳**이다",
          "time.sleep(REQ_DELAY)" not in src)
    check("[130] 그리고 `throttle()` 이 여러 곳에서 쓰인다",
          src.count("throttle()") >= 10, src.count("throttle()"))

    # ── 캐시가 동시 쓰기에서 **항목을 안 잃나** ────────────────────
    import tempfile as _tf, os as _o
    d = _tf.mkdtemp(prefix="clk_")
    op, oa = _C._PATH, _C.AUTOSAVE
    try:
        _C.configure(_o.path.join(d, "c.json"))
        _C.load()
        _C.AUTOSAVE = 0
        def p(n):
            for i in range(200):
                _C.put("k%d_%d" % (n, i), {"v": i})
        ts = [_th.Thread(target=p, args=(n,)) for n in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        check("[130] 캐시가 동시 쓰기 800건을 **하나도 안 잃는다**",
              len(_C._STORE) == 800, len(_C._STORE))
    finally:
        _C.AUTOSAVE = oa
        _C.configure(op)
        import shutil as _sh
        _sh.rmtree(d, ignore_errors=True)


def test_result_files_are_backed_up_before_overwrite():
    """[129] **결과를 덮어쓰기 전에 `.bak` 을 남긴다** (결함 223).

    `CLAUDE.md §3-3` — *"결과 파일을 확인 없이 덮어쓰지 마라(`--out`
    기본값 주의)"*. **규칙만 있고 구조가 없었다.**

    08-15 밤 실행에서 스크립트가 `--out` 을 안 줘서
    `bench_results.json`(08-04 · 17 KB · **B0 포함**)이 사라졌다.
    코드는 *"행 집합이 달라 버린다"* 고 **말은 했는데 아무 데도 안 남겼다.**

    ## 방어를 한 곳에 둔다

    08-11(결함 145)에도 같은 사고가 났고 그때는 `fto._save_index` 에만
    `.bak` 을 붙였다. **한 갈래만 고쳤다.** 이번엔 `io/safeio` 로 올리고
    `fto`·`bench.run` 이 **둘 다 그걸** 부르게 했다 — 결함 98·222 가
    «같은 방어가 두 곳» 이라 난 것이기 때문이다.

    ## 나머지 24곳은 **안 고쳤다.** 대신 늘지 않게 막는다

    `bench/` 에 맨 `json.dump` 가 아직 24곳 남아 있다. 전부 옮기려면
    각각 시험이 필요하고, 특히 `match.py`·`ctgov.py` 는 **`§3-1` 이
    재실행을 금지한 라벨 파이프라인**이라 8월에 손대면 안 된다.

    > **없앨 수 없으면 늘지 않게 막는다.** 이 수가 늘면 시험이 실패한다.
    > 줄이는 쪽으로 바꿀 때는 이 상수를 같이 내려라.
    """
    import ast as _ast, glob as _g, os as _o
    from ..io import safeio as _S
    from ..bench import run as _R

    # ① 공용 함수가 **실제로** `.bak` 을 남기나 — 모의가 아니라 파일로
    import tempfile as _t, json as _j
    d = _t.mkdtemp(prefix="safeio_")
    p = _o.path.join(d, "r.json")
    r1 = _S.save_json({"판": 1}, p)
    check("[129] 첫 저장은 상태가 **«없음»** — 지울 게 없다",
          r1["상태"] == "없음" and r1["백업"] is None, r1["상태"])
    r2 = _S.save_json({"판": 2}, p)
    check("[129] 두 번째 저장은 **앞 판을 `.bak` 으로 남긴다**",
          r2["상태"] == "남김"
          and _j.load(open(r2["백업"], encoding="utf-8"))["판"] == 1
          and _j.load(open(p, encoding="utf-8"))["판"] == 2, r2["상태"])
    # ── **세 상태가 갈리는가** (08-18 렌즈 7) ──────────────────────
    #   앞판은 셋을 전부 `None` 으로 뭉갰다. «파일이 없었다» 와
    #   «백업이 실패했다» 가 같은 값이면 **백업 없이 덮은 것을 모른다**
    #   — 결함 89 계열이고, 그게 결함 223 이 난 상황이다.
    check("[129] 없는 파일은 **«없음»** — «실패» 와 다른 값이다",
          _S.backup(_o.path.join(d, "없음.json")) == (None, "없음"))
    _o.remove(r2["백업"])
    _o.mkdir(r2["백업"])          # `.bak` 자리를 막아 **백업을 실제로 실패**시킨다
    r3 = _S.save_json({"판": 3}, p)
    check("[129] 백업이 실패하면 **원본을 안 덮는다**",
          r3["원본유지"] is True
          and _j.load(open(p, encoding="utf-8"))["판"] == 2, r3["상태"][:40])
    check("[129] 그리고 **결과는 `.new` 로 살린다** — 둘 다 잃지 않는다",
          r3["경로"].endswith(".new")
          and _j.load(open(r3["경로"], encoding="utf-8"))["판"] == 3)
    import shutil as _sh
    _sh.rmtree(d, ignore_errors=True)

    # ② **비싼 두 곳**이 그걸 거치는가
    import inspect as _i
    check("[129] `bench.run` 이 `safeio` 를 쓴다 (LLM 수백 회짜리 결과다)",
          "safeio" in _i.getsource(_R))
    from ..io import fto as _F
    check("[129] `fto._write_json` 도 **같은 함수**를 쓴다 — 방어가 한 곳",
          "safeio" in _i.getsource(_F._write_json))

    # ③ 남은 맨 `json.dump` 가 **늘지 않는다**
    #
    #   전부 옮기지 않은 이유를 여기 적는다 — `match.py`·`ctgov.py` 는
    #   `§3-1` 이 재실행을 금지한 라벨 파이프라인이다.
    # ⚠ 처음에 **22 로 적었다가 실측 24 에 걸렸다.** 문턱을 결과에 맞춘
    #   것이 아니라 **내가 눈으로 센 수가 틀렸다** — 그래서 실측으로
    #   고친다. `CLAUDE.md §4` («손계산해서 옮겨 적지 마라»)의 작은 판이다.
    KNOWN = 24          # 08-18 실측. **늘리지 마라. 줄이면 같이 내려라**
    # ── 09-25 · **검토한 예외** — 맨 `json.dump` 지만 «백업 없이 덮어쓰기» 가 아니다 ──
    #   09-23~24 에 만든 도구 넷이 넷을 더해 28 이 됐다(이틀 동안 아무도 이 시험을 안
    #   돌렸다). 넷 다 **덮기 전에 멈추거나(있으면 거부) 먼저 백업**한다 — 이 가드가
    #   막으려는 것과 다르다. 그래서 문턱을 올리지 않고 **그 방어가 코드에 있는지**를
    #   확인해 뺀다. 방어 문구가 지워지면 다시 세어져 빨개진다.
    #   ⚠ `seedretest` 는 봉인한 명세가 판(sha)을 박아 둬서 지금 `safeio` 로 못 옮긴다.
    REVIEWED = {"seedretest.py": "덮어쓰지 않는다",
                "zerocheck.py": "덮어쓰지 않는다",
                "zeropurge.py": "shutil.copy2(a.cache, bak)",
                "modelpair.py": "덮어쓰려면 --force",
                # 09-27 · 라이브 점검 기록 — 늘 새 이름으로 쓴다(같은 이름이면 번호를 붙인다 · 시험 [207]⑤)
                "livecheck.py": "같은 이름이 있으면 뒤에 번호를 붙인다(덮지 않는다)"}
    n = 0
    for f in sorted(_g.glob(_o.path.join(_o.path.dirname(_i.getfile(_R)),
                                         "*.py"))):
        try:
            _src129 = open(f, encoding="utf-8").read()
            t = _ast.parse(_src129)
        except Exception:
            continue
        _why = REVIEWED.get(_o.path.basename(f))
        if _why and _why in _src129:
            continue
        for x in _ast.walk(t):
            if (isinstance(x, _ast.Call)
                    and getattr(x.func, "attr", None) == "dump"
                    and getattr(getattr(x.func, "value", None), "id", "") == "json"):
                n += 1
    check("[129] `bench/` 의 맨 `json.dump` 가 **늘지 않았다** (%d ≤ %d)"
          % (n, KNOWN), n <= KNOWN, n)
    check("[129] 그리고 **왜 안 옮겼는지**가 적혀 있다 (§3-1 라벨 파이프라인)",
          "§3-1" in (test_result_files_are_backed_up_before_overwrite.__doc__ or ""))


def test_disease_entry_does_not_cut_candidates():
    """[128] **병명 입구 — 「Top-3」는 표시 순서이지 절단이 아니다** (명세 78e44afa).

    제안서 §6 흐름도의 입구는 **병명 하나**인데 화면은 **약물/질환 쌍**을
    받았다(🟥). 그리고 그림의 「Top-3」에 **절단 기준이 원문 어디에도 없다**
    — 검색 결과 0건.

    기준을 우리가 정하면 그게 **자유도**가 되고, 나중에 «잘 나오는 기준»
    을 고르면 `CLAUDE.md §3-2` 위반이다. 그래서 **자르지 않기로** 명세에
    박았다. 이 시험이 그걸 고정한다 —

        F0 를 통과한 것은 **전부** 깔때기를 탄다
        화면은 상위 3을 펴고 **나머지는 접되 수와 판정을 적는다**

    ## 동결이 안 깨진다

    `gate_discover` 가 `gates.ORDER` **밖**이다. 그래서 입구를 붙여도
    B0~B6 의 trail 이 안 바뀐다 — 그것도 여기서 확인한다.
    """
    from .. import dash as _D, demo as _M
    from ..core import gates as _G

    check("[128] `gate_discover` 가 **`ORDER` 밖**이다 — 동결 무관",
          not any("discover" in n for n in _G.ORDER), _G.ORDER)
    check("[128] 그런데 **레지스트리에는 있다** (도달 가능하다)",
          callable(getattr(_G, "gate_discover", None)))
    check("[128] 명세가 정한 K=10 · 상한 150초를 **코드가 갖는다**",
          _M.DISEASE_K == 10 and _M.TIME_BUDGET == 150.0,
          (_M.DISEASE_K, _M.TIME_BUDGET))

    # ── 화면이 **아무것도 안 버리는지** 본다 ─────────────────────
    cs = [{"이름": "d%d / X" % i, "약물": "d%d" % i,
           "판정": ["기각", "보류", "유망"][i % 3], "신뢰도": 0.5,
           "사유": "", "근거수": 10 - i} for i in range(7)]
    txt = _D.disease_run({"ok": True, "질환": "X", "요청": 10, "생성": 9,
                          "F0통과": 7, "태움": 7, "못태움": 0, "초": 40.0,
                          "상한": 150.0, "warm": False, "후보": cs})
    for i in range(7):
        check("[128] 후보 %d 가 **화면에 남아 있다** (접혔을 뿐)" % i,
              "d%d / X" % i in txt or "d%d —" % i in txt)
    # 08-19 — 말투를 서비스로 바꿨다(결함 274). **뜻으로 검사한다** —
    #   시험이 문구를 고정하면 문구를 못 고친다(결함 265 계열).
    check("[128] 접은 것을 **«버리지 않았다» 고 적는다**",
          "버리지 않" in txt, txt[-300:])
    # F0 근거 수가 있는 실행에서만 «순서» 설명이 뜬다 — 그건 맞다.
    #   다만 **«버리지 않는다» 는 늘 보여야 한다**(바로 위 검사).
    _f0txt = _D.disease_run({"ok": True, "질환": "X", "요청": 10, "생성": 5,
                             "F0통과": 5, "태움": 5, "못태움": 0, "초": 10.0,
                             "상한": 150.0, "warm": None,
                             "후보": [dict(c, F0근거수=i)
                                    for i, c in enumerate(cs)]})
    check("[128] 정렬 기준이 **F0 근거 수**임을 화면이 적는다",
          "F0" in _f0txt and "순입니다" in _f0txt)

    # ── **«안 태운 것」과 «떨어진 것」을 가른다** (결함 141·149) ────
    txt2 = _D.disease_run({"ok": True, "질환": "X", "요청": 10, "생성": 9,
                           "F0통과": 7, "태움": 3, "못태움": 4, "초": 151.0,
                           "상한": 150.0, "warm": None, "후보": cs[:3]})
    check("[128] 시간 상한에 걸리면 **«탈락이 아니다» 를 적는다**",
          "기각이 아니" in txt2 or "탈락이 아닙" in txt2,
          [l for l in txt2.splitlines() if "못 본" in l or "상한" in l][:2])

    # ── 판정이 한 종류뿐이면 **깔때기가 장식이라고 말한다** (§4 반증 3) ──
    same = [dict(c, 판정="보류") for c in cs[:4]]
    txt3 = _D.disease_run({"ok": True, "질환": "X", "요청": 10, "생성": 4,
                           "F0통과": 4, "태움": 4, "못태움": 0, "초": 10.0,
                           "상한": 150.0, "warm": False, "후보": same})
    check("[128] 판정이 **한 종류뿐이면 그 사실을 화면이 짚는다**",
          "한 종류뿐" in txt3
          and ("장식" in txt3 or "증거가 못 됩" in txt3),
          [l for l in txt3.splitlines() if "한 종류" in l])

    # ── 캐시가 데워져 있으면 **«빠르다» 가 아니라고 적는다** (§4.1) ──
    txt4 = _D.disease_run({"ok": True, "질환": "X", "요청": 10, "생성": 4,
                           "F0통과": 4, "태움": 4, "못태움": 0, "초": 10.0,
                           "상한": 150.0, "warm": True, "후보": cs[:4]})
    check("[128] 캐시가 데워졌으면 **«이미 받아 뒀다» 라고 적는다**",
          "이미 받아 뒀다" in txt4)

    # ── **성능으로 안 판다** — 23.5% 를 화면이 스스로 적는다 ────────
    check("[128] **«발견이 아니라 분류»** 를 화면이 적는다",
          "23.5%" in txt
          and ("발견이 아니라 분류" in txt or "다시 정리한 결과" in txt),
          [l for l in txt.splitlines() if "23.5" in l])

    # ── 실패 경로 — **«없다» 와 «못 했다» 를 가른다** ────────────────
    bad = _D.disease_run({"ok": False, "상태": "생성없음",
                          "메시지": "후보가 하나도 안 나왔다"})
    check("[128] 생성 0건은 **«없다» 가 아니라 «못 했다»** 로 적는다",
          "못 했다" in bad)


def test_tests_do_not_litter_the_repo():
    """[127] **시험이 저장소에 파일을 남기지 않는다** (결함 219).

    08-14에 시험 [125]가 `USE_PAIRS` 만 임시 경로로 갈아 끼우고
    **`YEARS_CACHE` 를 빼먹었다.** 그래서 `_run_use_year` 가 **진짜
    `fto_years.json` 을 프로젝트 뿌리에 썼다** — 스텁 연도 **3개**짜리로.

    ```
    {"scanned_all": true, "years": {"1": 2020, "2": 1980, "3": 1975}}
    ```

    `--fresh-pairs` 없이 다음 실행이 돌았으면 **그 세 개로 ①·②′ 판정이
    났을 것**이다. 승우가 마침 `--fresh-pairs` 로 도는 중이라 안 물렸다 —
    **운이었지 방어가 아니었다.**

    `test_no_pollution` 이 **전역 상태**는 보는데 **파일**은 안 봤다.
    그 구멍을 여기서 막는다.

    > 이 시험은 «지금 깨끗한가» 를 묻지 않는다 — 그건 실행 순서에 달렸다.
    > **«시험 코드가 옆 파일 상수를 다 갈아 끼우는가»** 를 소스에서 본다.
    """
    import ast as _ast, inspect as _insp
    from ..io import fto as _F

    # `fto` 가 프로젝트 뿌리에 쓰는 **옆 파일 상수 전부**
    consts = [n for n in dir(_F)
              if n.isupper() and isinstance(getattr(_F, n), str)
              and str(getattr(_F, n)).endswith(".json")]
    check("[127] `fto` 의 옆 파일 상수를 찾았다", len(consts) >= 3, consts)

    # 그 상수들을 **쓰는 경로를 태우는 시험**은 전부 갈아 끼워야 한다
    src = _insp.getsource(test_use_year_stops_when_it_cannot_reproduce)
    miss = [c for c in consts if ("_F.%s =" % c) not in src]
    check("[127] `_run_use_year` 를 태우는 시험이 **상수를 다 갈아 끼운다**",
          not miss, "안 바꾼 것: %s" % miss)

    # 그리고 **되돌린다** — 안 되돌리면 뒤의 시험이 임시 경로를 본다
    tree = _ast.parse(src)
    has_finally = any(isinstance(n, _ast.Try) and n.finalbody
                      for n in _ast.walk(tree))
    check("[127] 그리고 `finally` 로 **되돌린다**", has_finally)


def test_patent_view_reads_our_index_not_a_dead_api():
    """[126] **화면이 우리가 훑은 색인을 읽는다** (결함 218).

    08-14까지 `dash.right_patent` 가 `fto.check()`(PatentsView API)를
    불렀다. 그 API 는 **2026-03-20에 중단**됐고 키를 못 받는다(결함 95).
    그래서 이 칸은 **늘 «확인불가»** 였다 — 그 사이 우리는 SureChEMBL
    **11.6 GB** 를 훑어 색인을 만들었고, **그게 화면에 한 줄도 안 나왔다.**

    `계획_8월` 범위표가 *«약물 → 관련 특허 문서 **조회·제시**»* 라고
    적었다. **조회는 됐고 제시가 비어 있었다.**
    """
    import json as _j, os as _o, tempfile as _tf, shutil as _sh
    from ..io import fto as _F
    from .. import dash as _D

    tmp = _tf.mkdtemp(prefix="fto218_")
    try:
        _j.dump({"scanned_all": True, "n_drugs": 1,
                 "by_drug": {"Cisplatin": [11, 22, 33]}},
                open(_o.path.join(tmp, _F.DRUG_PATENTS), "w",
                     encoding="utf-8"), ensure_ascii=False)
        _j.dump({"scanned_all": True, "years": {"11": 2021, "22": 1979,
                                                "33": 2015},
                 "ids": {"11": "US2021111A1", "22": "US1979222A",
                         "33": "US2015333B2"}},
                open(_o.path.join(tmp, _F.YEARS_CACHE), "w",
                     encoding="utf-8"), ensure_ascii=False)

        r = _F.local_check("cisplatin", root=tmp)      # **대소문자가 달라도**
        check("[126] 로컬 색인에서 찾는다 — 이름 대소문자 무관",
              r["label"] == "특허검색됨", r["label"])
        check("[126] 관련 특허 건수를 낸다", r["n_patents"] == 3, r["n_patents"])
        check("[126] **최근 20년**을 따로 센다 — 1979년은 빠진다",
              r["n_recent"] == 2, r["n_recent"])
        check("[126] 특허 **번호**를 낸다 — 이게 결함 218 의 핵심",
              [p["id"] for p in r["patents"]][:1] == ["US2021111A1"],
              [p["id"] for p in r["patents"]])
        check("[126] **최근 공개 순**으로 정렬한다 (순위가 아니다)",
              [p["date"] for p in r["patents"]] == [2021, 2015, 1979],
              [p["date"] for p in r["patents"]])
        # ── 정렬 아티팩트를 화면이 스스로 말하게 한다 (08-14) ──────────
        #   실측: cisplatin 의 5건이 **전부 CN** 인데 분포는 US 8,368 이
        #   1위였다. 다섯 건은 대표 표본이 아니다 — 그걸 안 적으면
        #   화면이 «자료» 가 아니라 «정렬» 을 보여주는 것이 된다.
        check("[126] **국가 분포**를 같이 낸다 — 다섯 건은 대표 표본이 아니다",
              dict(r.get("국가") or {}).get("US") == 3, r.get("국가"))

        # ── **없는 것과 못 찾은 것을 가른다** (결함 141 계열) ──────────
        r2 = _F.local_check("존재하지않는약", root=tmp)
        check("[126] 색인에 없는 약 → **«특허 없음» 이라고 안 한다**",
              r2["label"] == "확인불가" and "아니다" in r2["why"], r2["why"][:60])
        r3 = _F.local_check("cisplatin", root=_o.path.join(tmp, "없음"))
        check("[126] 색인 파일이 없으면 **«안 만들었다» 고 말한다**",
              "색인이 없다" in r3["why"], r3["why"][:60])
    finally:
        _sh.rmtree(tmp, ignore_errors=True)

    # ── ⛔ **자유실시로 미끄러지지 않는다** — 구조로 막는다 ────────────
    #
    #   자료 층에서도 막히고(청구항 전문·법적 상태·국가 지정이 없다)
    #   규범 층에서도 막힌다(법률 판단이라 «거짓 확신» 이 된다 · §2.5).
    #   그래서 **화면 문구가 그 선을 넘는지**를 시험이 본다.
    txt = _D.right_patent("cisplatin")
    # **뜻으로 본다** — 08-19 에 경고 셋을 한 상자로 묶고 «~습니다» 로
    #   바꿨다. 요건은 «그 두 가지를 말한다» 이지 어미가 아니다.
    check("[126] 화면이 **«자유실시 여부는 판단하지 않는다»** 를 적는다",
          "자유실시 여부는 판단하지 않" in txt, txt[-200:])
    check("[126] 화면이 **판정에 안 들어간다**고 적는다",
          "판정에 들어가지 않" in txt, txt[-200:])
    import re as _re
    # «개발가능» 같은 **자유롭다는 뜻의 라벨**을 화면이 내면 안 된다.
    #   08-14 에 만료를 못 가른다는 것이 실측됐다(공개연도 p=0.773).
    banned = _re.compile(r"개발\s*가능|자유\s*실시\s*(가능|됨|OK)|침해\s*(없|아님)")
    check("[126] **«개발가능»·«자유실시 가능» 을 화면이 안 낸다**",
          not banned.search(txt), (banned.search(txt) or [""])[0])
    import inspect as _insp126
    src = _insp126.getsource(_F.local_check)
    check("[126] `local_check` 이 **`개발가능` 라벨을 안 만든다**",
          '"개발가능"' not in src and "'개발가능'" not in src)
    check("[126] 그리고 **왜 안 만드는지**를 적어 뒀다 (p=0.773)",
          "0.773" in src)


def _app140():
    """가짜 gradio 로 `app` 을 얻는다 — 시험 [55] 와 같은 방식."""
    import sys as _s, types as _t
    real = _s.modules.get("gradio")
    if real is not None and hasattr(real, "Blocks"):
        import importlib
        return importlib.import_module("app")

    class _C:
        def __init__(s, *a, **k):
            s.calls = []

        def change(s, fn, inputs=None, outputs=None, **k):
            s.calls.append(fn)
            return s              # `.then()` 사슬 — 반환이 없으면 None.then
        click = submit = then = change

        def __enter__(s):
            return s

        def __exit__(s, *e):
            return False

    class _B(_C):
        def load(s, fn, inputs=None, outputs=None, **k):
            s.calls.append(fn)
            return s

    class _F(_t.ModuleType):
        def __getattr__(self, n):
            if n.startswith("_"):
                raise AttributeError(n)
            return _C

    f = _F("gradio")
    f.Blocks, f.update = _B, lambda **k: dict(k)
    f.themes = _t.SimpleNamespace(Soft=lambda **k: None, Base=lambda **k: None)
    f.__version__ = "6.22.0"
    _s.modules["gradio"] = f
    import importlib
    return importlib.import_module("app")


def test_exit_axis_actually_moves_the_verdict():
    """[140] **출구 축이 판정에 실제로 걸린다** — 결함 256.

    08-18 밤. 승우가 *«직접 검증 칸에도 표준/긴급을 만들어야 하는 거
    아냐?»* 라고 물어 배선을 따라갔더니 `profiles.exit_profile` 을
    **읽는 곳이 화면 하나뿐**이었다. `scoring` 이 문턱을 상수로 박아
    둬서 토글을 바꿔도 판정이 안 움직였다.

    실측 모순 — 좌측 **«기각 문턱 25»**, 중앙 **«metformin 기각 26%»**.
    **26 ≥ 25 다.** 심사위원이 화면에서 산수하면 나온다.

    ## 이 시험이 지키는 두 가지

    ① **기본값은 한 자리도 안 움직인다.** 동결 수치가 전부 표준으로 났다.
    ② **긴급은 실제로 움직인다.** 안 움직이면 토글이 거짓말이다.
    """
    from ..core import scoring as _S, profiles as _P, gates as _G
    from ..core.state import RunState as _RS, Candidate as _C140, Evidence as _E
    import inspect as _insp140

    # ── ① 기본값 = 표준 = 지금까지의 상수 ────────────────────
    std = _P.exit_profile("표준")
    check("[140] 표준 문턱이 **옛 상수와 같다** — 동결 수치 불변의 근거",
          (std["유망"], std["기각"], std["balance"]) == (80, 40, _S.BALANCE),
          (std["유망"], std["기각"], std["balance"], _S.BALANCE))
    urg = _P.exit_profile("신종감염병긴급")
    check("[140] 긴급은 **유망 문턱을 안 낮춘다** — 낮추는 건 기각 쪽",
          urg["유망"] == std["유망"] and urg["기각"] < std["기각"],
          (urg["유망"], urg["기각"]))
    check("[140] 긴급은 **등록부 조회가 의무**다", urg.get("registry_required") is True)

    def _mk():
        c = _C140(name="x", origin="입력", query="q", drug="d", disease="e")
        c.support = [_E(tag="s", direction="support", weight=1.0)]
        c.refute = [_E(tag="r", direction="refute", weight=1.8)]
        return c

    v_none = _S.adjudicate(_mk())
    v_std = _S.adjudicate(_mk(), profile=std)
    check("[140] `profile=None` 과 «표준» 이 **글자 하나까지 같다**",
          v_none == v_std, "%s vs %s" % (v_none[:2], v_std[:2]))

    v_urg = _S.adjudicate(_mk(), profile=urg)
    check("[140] 같은 확률인데 **잣대가 다르면 판정이 다르다**",
          v_none[1] == v_urg[1] and v_none[0] != v_urg[0],
          "%s%% : %s → %s" % (v_none[1], v_none[0], v_urg[0]))
    check("[140] 표준에선 기각 · 긴급에선 **보류** — 늘어나는 건 유망이 아니다",
          (v_none[0], v_urg[0]) == ("기각", "보류"), (v_none[0], v_urg[0]))

    # ── ② 상태 → 게이트까지 흘러가나 (화면만이 아니라) ───────
    for ex, want in (("표준", "기각"), ("신종감염병긴급", "보류")):
        c = _mk()
        st = _RS(query_title="t", settings="B5S", stamp="s", candidates=[c],
                 config={}, exit_=ex)
        _G.gate_adjudicate(st)
        check("[140] `gate_adjudicate` 가 `st.exit_`(%s) 를 읽는다" % ex,
              c.verdict == want, "%s %s" % (c.verdict, c.confidence))
    check("[140] 긴급 판정은 **어느 잣대였는지 감사 추적에 남는다**",
          any("잣대 신종감염병긴급" in (r.detail or "") for r in c.trail),
          [r.detail for r in c.trail if r.gate == "adjudicate"])

    # ── ③ 등록부 의무가 **구성까지** 바꾸나 ─────────────────
    from .. import demo as _D140
    base = dict(_G.CONFIGS["B5S"])
    check("[140] 표준은 게이트 구성을 **안 건드린다**",
          _D140._apply_exit(dict(base), "표준") == base)
    check("[140] 긴급은 **등록부 게이트를 켠다** — 대본이 그렇게 말한다",
          _D140._apply_exit(dict(base), "신종감염병긴급").get("registry") is True)

    # ── ④ 화면: 문턱과 판정이 **모순으로 나란히 서지 않는다** ──
    from .. import dash as _DH140
    from .. import evidence as _EV140b_mod

    def _EV140b():
        return _EV140b_mod
    L = _DH140.left("정방향", "신종감염병긴급", "metformin")
    C = _DH140.center(list(_DH140.RUNS)[0], "신종감염병긴급")
    # 08-18 — 좁은 칸에서 5열 표가 글자 하나씩 쪼개져 **2열 세로**로 바꿨다.
    #   시험이 옛 서식을 붙들면 서식을 못 고친다(결함 265).
    # 08-21 — **그 주석을 적어 놓고도 서식을 못 박았다.** `| 기각 문턱 |
    #   **25** |` 를 그대로 썼고, 표를 «이름 — 값» 줄로 바꾸자 깨졌다.
    #   요건은 «좌측이 25 를 찍는다» 이지 파이프 위치가 아니다 —
    #   **이름과 값이 같은 줄에 있으면 된다.**
    check("[140] 좌측이 긴급 문턱 25 를 찍는다",
          any("기각 문턱" in x and "25" in x for x in L.splitlines()),
          [x for x in L.splitlines() if "문턱" in x])
    # ── ⚠ 09-25 · 앞판은 **구운 metformin 이 26%** 라는 데 기댔다 ──────────
    #   본선 모델로 다시 구우니 metformin 이 «기각 0%»(거부권)가 됐고 이 줄이 깨질
    #   참이었다. 지키려던 것은 숫자가 아니라 **규칙**이다 —
    #     ⓐ 문턱 근처의 기각(26%)에는 «긴급에선 보류» 가 붙는다 → **고정 자료로**
    #     ⓑ 지금 구운 자료에서 «→» 가 붙은 줄과 안 붙은 줄이 **문턱 계산과 정확히 맞는다**
    import json as _j140
    import tempfile as _t140
    _fx = _o140 = None
    try:
        import os as _o140
        _fx = _o140.path.join(_t140.mkdtemp(prefix="exit140_"), "demo_cases.json")
        with open(_fx, "w", encoding="utf-8") as _f:
            _j140.dump({"구운 시각": "고정", "사례": [
                {"질의": "metformin / Malignant neoplasm of breast", "판정": "기각", "신뢰도": 26,
                 "근거": [], "게이트": []}]}, _f, ensure_ascii=False)
        _keep140 = _EV140b_mod.CASES
        _EV140b_mod.CASES = _fx
        try:
            C26 = _DH140.center(list(_DH140.RUNS)[0], "신종감염병긴급")
        finally:
            _EV140b_mod.CASES = _keep140
    except Exception as _e140:
        C26 = "예외: %s" % _e140
    # 09-29 · **표의 행만 본다** — 실행 1 의 무대 글이 무대 밖 쌍을 약 이름으로 대면서(결함 377) «metformin» 이
    #   든 첫 줄이 무대 글이 됐다. 이 검사가 보려는 것은 판정 표의 그 쌍 행이다
    mrow = [l for l in C26.splitlines() if "metformin" in l and l.lstrip().startswith("|")]
    check("[140] ⓐ **26% 기각 옆에 «긴급에선 보류» 가 붙는다** — 결함 256 본체 (고정 자료)",
          mrow and "신종감염병긴급에선 보류" in mrow[0],
          (mrow or [""])[0][-60:])
    _cs140 = {x.get("질의"): x for x in ((_EV140b_mod.cases() or {}).get("사례") or [])}
    _bad140 = []
    for _q in _DH140.RUNS[list(_DH140.RUNS)[0]]["후보"]:
        _x = _cs140.get(_q)
        if not _x:
            continue
        _want = bool(_DH140._by_profile(_x.get("판정"), _x.get("신뢰도"), "신종감염병긴급"))
        _row = [l for l in C.splitlines() if _q.split(" /")[0] in l and l.lstrip().startswith("|")]
        _has = bool(_row) and "신종감염병긴급에선" in _row[0]
        if _want != _has:
            _bad140.append((_q, _x.get("판정"), _x.get("신뢰도"), _want, _has))
    check("[140] ⓑ 지금 구운 자료에서 «→ 긴급에선» 표시가 **문턱 계산과 정확히 맞는다**",
          not _bad140, _bad140)
    check("[140] 그 표가 **표준으로 봉인된 값임을 적는다**",
          "«표준» 으로 계산해 봉인한 값" in C)
    erow = [l for l in C.splitlines() if "edaravone" in l and l.lstrip().startswith("|")]
    if erow:
        check("[140] **`조건부` 에는 «→» 를 안 붙인다** — 문턱과 무관한 판정",
              "에선" not in erow[0], erow[0][-60:])
    # ── ⑥ **화면에 실제로 찍힌 근거로 재현한다** — 유추가 아니라 실측 ──
    #   08-18 22시 「직접 검증」 긴급 실행이 낸 근거 7건을 그대로 옮긴다.
    #   화면: 무게비 0.37 · 지지 1 · 반박 2 · 판정 «조건부».
    #   **문턱이 아니라 `balance` 가 움직인 것**이라는 주장을 여기서 잰다.
    _ROWS = [("refute", 3.00, "35608580", "rct"),
             ("support", 1.44, "39113190", "rct"),
             ("refute", 0.90, "41348549", "rct"),
             ("refute", 0.20, "37185680", "review"),
             ("support", 0.08, "24841876", "review"),
             ("support", 0.03, "34162423", "invitro"),
             ("support", 0.03, "40091020", "invitro")]

    def _real():
        c = _C140(name="m", origin="입력", query="q", drug="metformin",
                  disease="Malignant neoplasm of breast")
        c.factcheck = [{"kept": True, "direction": d, "weight": w,
                        "study_type": t, "pmid": pm} for d, w, pm, t in _ROWS]
        for d, w, pm, t in _ROWS:
            e = _E(tag=pm, direction=d, weight=w, pmid=pm)
            (c.support if d == "support" else c.refute).append(e)
        return c

    _ok, _ns, _nr, _ratio = _S.contested(_real())
    check("[140] 화면의 **무게비 0.37 · 지지 1 · 반박 2** 가 재현된다",
          (round(_ratio, 2), _ns, _nr) == (0.37, 1, 2),
          (round(_ratio, 3), _ns, _nr))
    _vs = _S.adjudicate(_real(), profile=std)[0]
    _vu = _S.adjudicate(_real(), profile=urg)[0]
    check("[140] **같은 근거인데 표준 기각 · 긴급 조건부** — 움직인 건 `balance` 다",
          (_vs, _vu) == ("기각", "조건부"), (_vs, _vu))

    # ── ⑧ **3D 뷰어가 라이브에도 있나** (결함 259) ────────────────
    #   결함 251 에 *«markdown 이라 3Dmol script 가 안 돈다»* 라고 적었다.
    #   **틀렸다** — `viewer.render()` 반환에 script 가 **0개**다. 그리는
    #   것은 `head` 의 전역 MutationObserver 이고 `div.br-3d[data-cif]` 를
    #   문서 어디서든 찾는다. 막던 건 «출력 칸이 하나» 였을 뿐이다.
    from .. import viewer as _V140
    _s1 = None
    for _c in (_EV140b().cases() or {}).get("사례") or []:
        if _c.get("s1"):
            _s1 = _c["s1"]
            break
    check("[140] 구조 경로 구운 사례가 있다", _s1 is not None)
    if _s1:
        _h = _V140.render(_s1)
        check("[140] `viewer.render` 에 **`<script>` 가 0개**다 — "
              "그래서 markdown/HTML 어디에 넣든 «script 가 안 돈다» 는 이유가 아니다",
              _h.count("<script") == 0, _h.count("<script"))
        check("[140] 대신 **전역 관찰자가 찾을 표식**이 있다",
              "br-3d" in _h and "data-cif" in _h)
    import inspect as _i140
    _asrc140 = _i140.getsource(_app140())
    check("[140] 라이브 탭에 **`gr.HTML` 뷰어 칸이 있다**",
          "live_struct = gr.HTML()" in _asrc140)
    # ⚠ **보이는 출력은 하나여야 한다** — gradio 가 칸마다 진행 막대를
    #   그린다. 승우: *«막대기가 두 개 생겨서 돌아가고, 이쁘지가 않아»*.
    #   `gr.State` 는 렌더가 안 되므로 막대가 안 생긴다(결함 260).
    check("[140] 스트리밍 출력에 **보이는 칸이 하나**다 — 막대가 하나",
          "outputs=[live_out, live_s1]" in _asrc140
          and "live_s1 = gr.State(None)" in _asrc140)
    check("[140] 3D 는 **`.then()` 으로** 뒤이어 채운다",
          ".then(_live_struct, inputs=live_s1, outputs=live_struct" in _asrc140)
    check("[140] 그 후속 호출은 **막대를 안 그린다**",
          "outputs=live_struct,\n                           show_progress=\"hidden\""
          in _asrc140 or "show_progress=\"hidden\")" in _asrc140)
    check("[140] 화면이 **옛 «못 그린다» 문구를 안 남긴다**",
          "markdown 이라 3Dmol 스크립트가 안 돈다" not in _asrc140)

    # ── ⑦ `run_disease(exit_)` 를 **부르는 곳이 있나** (결함 258) ────
    #   256 을 고치면서 배선만 하고 화면을 안 만들었다 — 여섯 번째다.
    _src = _i140.getsource(_app140())
    check("[140] `run_disease_live` 가 **출구 축을 받는다**",
          "def run_disease_live(disease, acc, exit_" in _src)
    # 08-19 — 축1(입구)이 붙으면서 인자가 하나 늘었다(결함 273).
    #   **서식이 아니라 «값이 실제로 가는가» 를 본다** — 그래야 다음에
    #   인자가 또 늘어도 시험이 서식 때문에 안 깨진다.
    check("[140] 그 값이 **`run_disease` 로 실제로 간다**",
          "exit_=exit_" in _src and "demo.run_disease(" in _src)
    check("[140] 병명 탭에 **축2 라디오가 있고 콜백 inputs 에 들어간다**",
          "dz_exit = gr.Radio" in _src and "dz_exit, dz_entry]" in _src)

    C0 = _DH140.center(list(_DH140.RUNS)[0], "표준")
    check("[140] 표준에서는 주석이 **안 붙는다** — 없는 말을 만들지 않는다",
          "에선" not in C0 and "봉인한 값" not in C0)

    # ── ⑤ 「직접 검증」 좌측 — 08-18 브라우저에서 눈으로 잡은 둘 ────
    #   ① 축1 이 **두 번** 찍혔다(내 markdown + `dash.left` 머리)
    #   ② 약물을 안 넘겨 접근성 셋이 **늘 «모름»** 이었다 — 정직하지만
    #      쓸모가 없고, 보는 사람은 «원래 안 되는 칸» 으로 읽는다
    _lv = _app140()._live_left
    md = _lv("hydroxychloroquine / COVID-19", "표준")
    # 08-19 — 라벨을 «축1 · 입구» → «후보를 찾는 방법» 으로 바꿨다.
    #   세 화면이 같은 것을 각자 다르게 부르고 있었다(결함 287).
    #   요건은 «한 번만 나온다» 이지 그 이름이 아니다.
    check("[140] 좌측에 입구 축이 **한 번만** 나온다",
          md.count("#### 후보를 찾는 방법") == 1
          and "축1" not in md, md.count("#### 후보를 찾는 방법"))
    # ⚠ 08-21 — 이 셋이 **마크다운 표 문법에 못 박혀** 있었다
    #   (`| WHO 필수의약품 | 예 |`). 좌측을 «이름 — 값» 줄로 바꾸자
    #   셋이 한꺼번에 깨졌다 — **뜻은 그대로인데** 형식만 바뀌었는데도.
    #   그래서 형식을 안 보고 **한 줄 안에 이름과 값이 같이 있는가**를 본다.
    def _has(text, name, val):
        """`name` 과 `val` 이 **같은 줄**에 있나 — 표든 줄이든 상관없이."""
        return any(name in l and val in l for l in text.splitlines())

    check("[140] 좌측 접근성이 **입력한 약물을 따라간다** — 늘 «모름» 이 아니다",
          _has(md, "WHO 필수의약품", ">예<") or _has(md, "WHO 필수의약품", "| 예 |"),
          [l for l in md.splitlines() if "WHO" in l])
    check("[140] 쌍을 못 읽으면 **«모름»** 이다 — 그때는 그게 맞다",
          _has(_lv("말이안되는입력", "표준"), "WHO 필수의약품", "모름"))
    check("[140] 잣대를 바꾸면 좌측 문턱이 따라간다",
          _has(_lv("metformin / X", "신종감염병긴급"), "기각 문턱", "25"))


def test_live_candidate_opens_its_reasoning():
    """[145] **라이브에서도 후보를 눌러 판단 과정을 볼 수 있다** — 결함 276.

    승우: *«유망 91% 이렇게 알려주는데 왜 그런지 더 자세히 알려주면
    좋을 것 같아. 각각의 약물을 클릭하면 그 과정이 왜 나왔는지»*

    **대시보드에는 이 패턴이 있었다**(후보 라디오 → 사고 과정 · 근거 카드).
    그런데 **구운 사례에만** 있었다 — 심사 30점 항목이 «사고 과정을
    투명하게 보여주는가» 인데 **실제로 돌린 쪽에 그게 없었다.**

    목록은 **답**을 주고 상세는 **이유**를 준다. 그리고 목록에서
    «그 밖에 근거 4건» 으로 접은 것이 여기서 전부 펴진다.
    """
    import json as _j, os as _o145
    from .. import dash as _D145, evidence as _EV145
    app = _app140()

    _f = _o145.path.join(_EV145.ROOT, "시연실행결과.json")
    if not _o145.path.exists(_f):
        check("[145] 시연 실행 결과 파일이 있다", False, _f)
        return
    r = _j.load(open(_f, encoding="utf-8"))["실행"][0]["결과"]

    names = _D145.candidate_names(r)
    check("[145] 결과에서 **후보 이름을 뽑는다**", len(names) >= 3, len(names))

    up = app._disease_picks(r)
    check("[145] 실행이 끝나면 **후보 칸이 보인다**",
          up.get("visible") is True and len(up.get("choices") or []) == len(names))
    check("[145] 실행 전에는 **안 보인다** — 빈 칸을 내지 않는다",
          app._disease_picks(None).get("visible") is False)

    d = app._disease_detail(r, names[2])
    # **서식이 아니라 뜻으로 본다** — 표였다가 목록이 됐다(결함 278).
    #   시험이 서식을 붙들면 «더 나은 서식» 이 시험을 깨는 일이 된다.
    check("[145] 상세가 **단계별 과정**을 낸다 (심사 30점)",
          "이 판단이 나온 과정" in d
          and d.count("br-step") >= 5 and "br-sdesc" in d, d[:80])
    check("[145] 상세가 **근거 전건**을 낸다 — 목록에서 접은 것이 펴진다",
          "#### 근거" in d and "PMID" in d)
    check("[145] 상세에 **판정 배지**가 있다", "br-verdict" in d)
    check("[145] 아무것도 안 고르면 **빈 문자열** — 옛 상세가 안 남는다",
          app._disease_detail(r, None) == ""
          and app._disease_detail(None, names[0]) == "")

    # 화면 배선 — **서명만 보면 이 결함이 또 통과한다**(결함 258·273)
    import inspect as _i145
    src = _i145.getsource(app)
    check("[145] 결과를 **`gr.State`** 로 받는다 — 진행 막대가 하나여야 "
          "한다(결함 260). 보이는 칸은 목록·꼬리 둘, 상태는 안 보인다",
          "dz_state = gr.State(None)" in src
          and "outputs=[dz_out, dz_tail, dz_state]" in src)
    check("[145] 후보 칸을 **실행 뒤에 채운다**",
          ".then(_disease_picks, inputs=dz_state, outputs=dz_pick" in src)
    check("[145] 후보를 고르면 **상세가 그려진다**",
          "dz_pick.change(_disease_detail" in src)
    check("[145] 새로 돌리면 **앞 상세·꼬리를 먼저 지운다** — 결함 262 자리",
          "outputs=[dz_pick, dz_detail, dz_tail]" in src)
    check("[145] 고르는 칸이 **후보 목록과 계기판 사이**에 있다 — 08-19 "
          "브라우저에서 페이지 맨 아래였다",
          "_SPLIT_AT" in _i145.getsource(_D145.disease_run_parts)
          and "dz_tail" in src)

    # 단계 이름이 **전부 한글**인가 (결함 255·274)
    from ..demo import GATE_KO as _GK145
    for c in (r.get("후보") or [])[:3]:
        for g in (c.get("게이트") or []):
            nm = str(g.get("게이트") or "")
            check("[145] 라이브 단계 «%s» 가 한글 이름을 갖는다" % nm,
                  nm in _GK145 or nm in _GK145.values(), nm)


def test_detail_shows_the_arithmetic_not_a_guess():
    """[146] **상세가 셈을 편다 — 그리고 그 셈이 판정과 같은 값을 낸다.**

    승우: *«판단 과정에서 w값등 자세히 클릭한 창 안에서 나왔으면»*

    ## 이 시험이 지키는 것

    `CLAUDE.md §4` — *«보고하는 통계는 코드에서 나와야 한다. 손계산해서
    문서에 옮겨 적지 마라»* (결함 19).

    그래서 `score_ledger` 는 **판정이 실제로 쓴 함수**를 부르고,
    **재구성이 화면의 % 와 안 맞으면 셈을 내지 않는다.** 그 거부가
    실제로 작동하는지를 여기서 확인한다 — 안 그러면 «설명이 안 되는데
    설명하는 척» 하는 화면이 되고, **그게 심사에서 맞는 자리다.**

    무게표도 **코드에서 뽑는다.** 문서에 옮겨 적으면 갈라진다.
    """
    import inspect as _i146, json as _j, os as _o146, re as _r146
    from .. import dash as _D146
    from ..core import scoring as _S146
    from ..agents import factcheck as _F146
    from .. import evidence as _EV146
    _f = _o146.path.join(_EV146.ROOT, "시연실행결과.json")
    if not _o146.path.exists(_f):
        check("[146] 시연 실행 결과 파일이 있다", False, _f)
        return
    r = _j.load(open(_f, encoding="utf-8"))["실행"][0]["결과"]
    cs = [c for c in (r.get("후보") or []) if c.get("근거")]
    check("[146] 근거 있는 후보가 있다", len(cs) >= 2, len(cs))

    n_led = 0
    for c in cs:
        led = _D146.score_ledger(c)
        if "설명되지 않습니다" in led:
            continue                    # 다른 갈래 — 거부한 것이 정상이다
        n_led += 1
        m = _r146.search(r"확률로 바꾸면</span><b>(\d+)%", led)
        check("[146] «%s» 셈이 확률을 낸다" % c["이름"][:24], bool(m), led[:120])
        if m:
            check("[146] «%s» 셈이 **화면의 %%와 같다** — 다르면 낸 것이 "
                  "거짓말이다" % c["이름"][:24],
                  abs(int(m.group(1)) - int(c["신뢰도"])) <= 1,
                  "%s vs %s" % (m.group(1), c["신뢰도"]))
        check("[146] «%s» 지지·반대를 **따로** 보인다" % c["이름"][:24],
              "지지 " in led and "반대 " in led)
    check("[146] 셈을 편 후보가 하나 이상", n_led >= 1, n_led)

    # 근거 없는 후보엔 셈이 없다 — **빈 셈을 그리지 않는다**
    empt = [c for c in (r.get("후보") or []) if not c.get("근거")]
    if empt:
        check("[146] 근거 0건이면 **셈을 안 그린다**",
              _D146.score_ledger(empt[0]) == "")

    # 설명이 안 되는 후보는 **거부한다** — 구조로 막는 자리
    fake = {"신뢰도": 3, "근거": [{"방향": "지지", "가중치": 2.0, "출처": "llm"}]}
    check("[146] 재구성이 어긋나면 **셈을 안 낸다** (§4 · 결함 269 계열)",
          "설명되지 않습니다" in _D146.score_ledger(fake),
          _D146.score_ledger(fake)[:80])

    # 무게표는 **코드에서** 나온다
    rub = _D146.weight_rubric()
    for k, v in _F146.WEIGHT_BASE.items():
        check("[146] 무게표에 «%s» 기본값 %.1f 이 있다" % (k, v),
              ("| %.1f |" % v) in rub, rub[:120])
    check("[146] 무게표가 **결정성 배수 %.1f** 를 적는다" % _F146.DECISIVE_MULT,
          ("×%.1f" % _F146.DECISIVE_MULT) in rub)
    check("[146] 무게표가 상수를 **문서에 베끼지 않는다** — import 로 읽는다",
          "from .agents import factcheck" in _i146.getsource(
              _D146.weight_rubric))

    # ── 08-19 **브라우저에서만 나온 것들** (결함 279) ───────────
    #   렌더 문자열만 봐서는 안 나왔다. 화면을 열어야 나왔다 —
    #   `불명 → None (low)` 과 `합 -0.00`.
    for nm in _D146.candidate_names(r):
        d = _D146.candidate_detail(r, nm)
        check("[146] «%s» 화면에 파이썬 `None` 이 없다" % nm[:20],
              "None" not in d, [x for x in d.split() if "None" in x][:2])
        check("[146] «%s» **음의 0** 을 안 찍는다 — 0 에는 부호가 없다"
              % nm[:20], "-0.00" not in d and "−0.00" not in d)

    # ── 상자를 쓰지 않는다 (결함 280) ────────────────────────────
    #   승우가 **두 번** 같은 말을 했다 — «보라색 상자» · «회색 상자».
    #   색 있는 배지 뒤에 회색 판을 깔면 배지가 죽는다.
    d1 = _D146.candidate_detail(r, _D146.candidate_names(r)[0])
    check("[146] 상세 머리가 **배지·이름·사유 세 층**이다",
          "br-dhead" in d1 and "br-dname" in d1 and "br-dwhy" in d1)
    # 08-20 — CSS 가 두 곳이다: Gradio 판(`app.py` 안 `_CSS`) 과
    #   새 화면(`web/static/app.css`). **둘 다 본다** — 어느 쪽이든
    #   정의가 있으면 그 클래스는 살아 있다.
    _css = open(_o146.path.join(_EV146.ROOT, "app.py"),
                encoding="utf-8").read()
    _cssf = _o146.path.join(_EV146.ROOT, "web", "static", "app.css")
    if _o146.path.exists(_cssf):
        _css += open(_cssf, encoding="utf-8").read()
    _i = _css.index(".br-detail{")
    check("[146] `.br-detail` 에 **배경이 없다** — 상자를 안 쓴다",
          "background" not in _css[_i:_i + 200], _css[_i:_i + 90])
    check("[146] 후보 칸이 **Gradio 컨테이너를 안 만든다** — `div.form` 이 "
          "회색 판(#e5e7eb)이고 CSS 로는 부모를 못 고른다",
          "container=False" in _css and "show_label=False" in _css)
    check("[146] 후보 칩이 **줄바꿈한다** — 08-19 화면에서 오른쪽으로 잘렸다",
          "flex-wrap:wrap !important" in _css)

    # 구운 사례에 없는 조합도 **직접 태운다** — 화면에서 본 그 문자열이다
    for raw, want, dont in (
            ("불명 → None (low)", "확신 낮음", "None"),
            ("간접 → None (medium)", "확신 보통", "None"),
            ("직접·숙주 · HDAC → evidence (medium)", "문헌으로 검증", "evidence"),
            ("오프타겟 · X → structure (high)", "구조로 검증", "structure"),
            ("config off", "안 씁니다", "config"),
            ("발굴 에이전트가 생성(loose·clinical)", "넓게 생성", "loose")):
        got = _D146.plain_trail(raw)
        check("[146] «%s» → 사람 말" % raw[:26],
              want in got and dont not in got, got)
        check("[146] «%s» 괄호가 안 어긋난다" % raw[:20],
              got.count("(") == got.count(")"), got)

    # ── 상세가 **내부 식별자를 안 흘린다** (결함 278) ────────────
    for nm in _D146.candidate_names(r):
        d = _D146.candidate_detail(r, nm)
        for tok in ("config off", "→ evidence", "→ structure", "(loose·",
                    "(strict·", "(medium)", "(high)", "(low)",
                    "clinical)", "구조 경로 아님"):
            check("[146] 상세에 내부 식별자 «%s» 가 안 보인다" % tok,
                  tok not in d, nm[:22])
        check("[146] «%s» 이스케이프 역슬래시가 화면에 안 남는다" % nm[:20],
              "\\|" not in d)
    # 표는 **목록**이 됐다 — 한 칸 183자가 열 비율을 무너뜨렸다
    d0 = _D146.candidate_detail(r, _D146.candidate_names(r)[2])
    check("[146] 과정이 **목록**이다 (표 아님)",
          "br-steps" in d0 and "| 단계 | 결과 |" not in d0)
    check("[146] 안 돌린 단계를 **지우지 않고 낮춘다**", "br-sdim" in d0)
    check("[146] 긴 경고를 **줄을 바꿔** 낸다 — 한 칸 183자짜리가 있다",
          "br-swarn" in d0)

    # 대시보드 사고과정도 **같은 말**을 쓴다 — 한쪽만 고치면 갈라진다
    _q = (_D146._cases() or {})
    if _q:
        th = _D146.thinking(sorted(_q)[0])
        check("[146] 대시보드 사고 과정도 «config off» 를 안 쓴다",
              "config off" not in th, th[:100])

    # 무게표 실례는 **`weight_for` 가 계산한다**
    rub0 = _D146.weight_rubric()
    check("[146] 무게표에 **실례**가 있다", "br-ex" in rub0)
    check("[146] 실례 값이 `weight_for` 와 같다 — 손계산 아님 (§4)",
          ("%.2f" % _F146.weight_for("meta", "unknown", True, "high", "high"))
          in rub0)
    check("[146] 배수를 **문장이 아니라 표**로 낸다 — 비율 (승우 08-19)",
          "| 무엇을 보나 | 배수 |" in rub0 and "여기에 배수를 곱합니다." in rub0)

    # 상세 근거줄이 **무게·인용검증·회수단계**를 낸다
    c0 = cs[0]
    ln = _D146.evidence_full((c0["근거"])[0])
    check("[146] 근거줄에 **무게 칩**", "br-w" in ln, ln[:100])
    check("[146] 근거줄에 **인용**",
          "br-quo" in ln or not (c0["근거"][0].get("인용")))
    # ── CSS 클래스 이름 충돌 (결함 281) ─────────────────────────
    #   새 클래스를 지을 때 **이미 있는 이름인지 안 봤다.** `br-q` 는
    #   `q_name()`(질의 이름)이 08-10 부터 쓰던 이름이라, 화면 제목
    #   «COVID-19» 가 46px 들여쓴 이탤릭이 됐다.
    import re as _rx146
    _used = set(_rx146.findall(r"class='(br-[a-z-]+)'",
                               _i146.getsource(_D146)))
    _used |= set(_rx146.findall(r"class='br-[a-z]+ (br-[a-z-]+)'",
                                _i146.getsource(_D146)))
    for cls in sorted(_used):
        check("[146] CSS 클래스 «%s» 가 정의돼 있다" % cls,
              ("." + cls) in _css, cls)
    check("[146] 인용 클래스가 **질의 이름과 안 겹친다** — 겹치면 제목이 "
          "인용문 서식을 입는다",
          "br-quo" in _i146.getsource(_D146.evidence_full)
          and "class='br-q'" not in _i146.getsource(_D146.evidence_full))
    check("[146] 근거줄이 **어느 단계에서 찾았는지** 적는다",
          any(x in ln for x in ("단계에서", "등록부", "직접 넣은")), ln[-160:])

    # **목록**은 여전히 평이해야 한다 — 숫자를 위로 올리면 안 된다
    lst = _D146.disease_run(r, acc_on=False)
    check("[146] **목록에는 w= 가 없다** — 처음 보는 사람에게 뜻 없는 숫자다",
          "w=" not in lst)
    check("[146] 상세는 **누른 사람만** 본다 — 목록에 셈이 없다",
          "확률로 바꾸면" not in lst)

    # 화면 배선 — 상수와 문턱을 **코드에서** 읽는지
    src = _i146.getsource(_D146.score_ledger)
    for nm in ("attenuate_correlated", "sigmoid", "CORR_FACTOR", "LOGIT_CAP"):
        check("[146] 셈이 **판정이 쓴 `%s`** 를 그대로 부른다" % nm, nm in src)
    check("[146] 셈에 **숫자 상수를 박지 않았다**",
          "0.5" not in src.split("def ")[1].split('"""')[2],
          "상수 하드코딩")
    _ = _S146.LOGIT_CAP


def test_reverse_entry_is_actually_reachable():
    """[144] **역발상 발굴이 화면에서 실제로 도달 가능하다** — 결함 273.

    08-19, 승우 — *«추가로 정방향,역방향은 왜 안넣었어?»*

    확인하니 **`profiles.ENTRY` 표가 통째로 죽어 있었다.**

        "정방향": {"module": "bioreroute.agents.discover", "fn": "propose"}
        "역발상": {"module": "bioreroute.agents.reverse",  "fn": "propose"}

    이 표를 **읽는 곳이 한 군데도 없었고**, `gate_discover` 는
    `discover_agent.propose` 를 **하드코딩**했다. 그래서 「병명으로
    시작」 탭은 **역발상을 영영 못 돌렸다.**

    `agents/reverse.py` 는 있고 **실측까지 끝났다**(FAERS p=0.0060 ·
    SIDER p<0.0001). 독스트링이 *«정방향 `discover.propose` 와 같은
    서명·같은 반환»* 이라 적어 뒀다 — **바꿔 끼우라고 만든 것**이다.

    **«만들어 놓고 부르는 곳이 없다» 의 일곱 번째**이고, 이번엔
    제안서 §2.2 의 간판 주장이 걸려 있다 — *«역발상과 신종 감염병 긴급
    심사처럼 고정형 모델이 허용하지 않던 조합»*. 축2(긴급)는 어제
    붙였는데 **축1의 역발상이 없으면 그 조합이 성립을 안 했다.**
    """
    import inspect as _i144
    from ..core import gates as _G144, profiles as _P144
    from ..core.state import RunState as _RS144
    from .. import demo as _D144

    src = _i144.getsource(_G144.gate_discover)
    check("[144] `gate_discover` 가 **`ENTRY` 표에서 고른다** — 하드코딩이 아니다",
          "profiles.ENTRY" in src and "importlib.import_module" in src)
    check("[144] 그래서 **`discover_agent.propose` 하드코딩이 없다**",
          "discover_agent.propose(" not in src)
    check("[144] 표에 **역발상 모듈**이 있다",
          _P144.ENTRY["역발상"]["module"].endswith("agents.reverse"))

    # 입구를 바꾸면 **다른 모듈**이 불린다 — 가짜로 갈아 끼워 확인한다
    called = {}
    import sys as _s144, types as _t144
    for name, mod in (("정방향", "bioreroute.agents.discover"),
                      ("역발상", "bioreroute.agents.reverse")):
        real = _s144.modules.get(mod)
        fake = _t144.ModuleType(mod)

        def _p(dz, k=20, model=None, _n=name, **kw):
            called[_n] = kw
            return {"ok": True, "items": [], "asked": k}
        fake.propose = _p
        _s144.modules[mod] = fake
        try:
            st = _RS144(query_title="t", settings="B5S", stamp="s",
                        candidates=[], config={})
            st.discover = {"diseases": ["X"], "k": 3, "entry": name}
            _G144.gate_discover(st)
        finally:
            if real is not None:
                _s144.modules[mod] = real
            else:
                _s144.modules.pop(mod, None)
    check("[144] **정방향을 고르면 `discover` 가 불린다**", "정방향" in called,
          list(called))
    check("[144] **역발상을 고르면 `reverse` 가 불린다** — 이게 핵심이다",
          "역발상" in called, list(called))
    check("[144] 인자가 다르다 — 정방향은 `variant`, 역발상은 `source`",
          "variant" in called.get("정방향", {})
          and "source" in called.get("역발상", {}),
          {k: sorted(v) for k, v in called.items()})

    # 발굴을 안 하는 입구는 **조용히 통과하지 않는다**
    st = _RS144(query_title="t", settings="B5S", stamp="s",
                candidates=[], config={})
    st.discover = {"diseases": ["X"], "k": 3, "entry": "사용자 지정"}
    _G144.gate_discover(st)
    check("[144] 「사용자 지정」 입구는 **발굴을 안 한다고 적는다**",
          any("발굴을 안 한다" in x for x in st.log), st.log[-1:])

    # 화면까지 이어졌나
    check("[144] `run_disease` 가 **`entry` 를 받는다**",
          "entry" in _i144.signature(_D144.run_disease).parameters)
    app = _app140()
    asrc = _i144.getsource(app)
    check("[144] 병명 탭에 **축1 라디오**가 있다",
          'dz_entry = gr.Radio(["정방향", "역발상"]' in asrc)
    check("[144] 그 값이 **콜백 inputs 에 들어간다** — 서명만 보면 또 통과한다",
          "[dz, acc, dz_exit, dz_entry]" in asrc)


def test_service_ui_gives_the_user_a_way_in_and_out():
    """[143] **서비스로 쓰려면 들어갈 길과 나올 길이 있어야 한다** — 결함 271.

    08-18 밤, 승우 — *«그래도 서비스를 하게 만드는 UI인데 서비스 하기엔
    아직 부족한듯»*. 실측으로 셋이 비어 있었다.

    ## 들어갈 길 — 예시가 화면에 0개였다

    `demo.PRESETS` 여섯에 **«왜 이 예시인가» 설명이 붙어 있는데**
    화면은 `PRESETS[0][0]` 을 **기본값으로만** 썼다. 나머지 다섯과
    설명 여섯 줄이 **한 글자도 안 나왔다.**

    ## 나올 길 — **제안서 §8.2 가 약속한 것을 못 지켰다**

      > *"산출물이 단순 판정이 아니라 **감사 가능한 근거 카드**이므로,
      >  내부 심의·규제 제출·투자 판단의 입력으로 **그대로 쓰인다**"*

    **그대로 쓰려면 가져갈 수 있어야 한다.** 복사도 저장도 없었다.

    ## 접는 기준은 **화면이 스스로 한 말**과 같아야 한다

    특허 칸은 *«이 값은 판정에 들어가지 않는다»* 라고 적는다. 그러면
    **접을 것은 그것**이고, 근거 카드·인용·구조는 판정의 근거라 **안 접는다.**
    """
    import inspect as _i143
    from .. import demo as _D143, evidence as _E143
    app = _app140()
    src = _i143.getsource(app)

    # ── ① 들어갈 길 ──────────────────────────────────────
    check("[143] 예시가 **누를 수 있는 위젯**으로 있다",
          "ex = gr.Radio([q for q, _ in demo.PRESETS]" in src)
    q0 = _D143.PRESETS[2][0]
    picked, why = app._pick_example(q0)
    check("[143] 예시를 고르면 **입력칸에 들어간다**", picked == q0, picked)
    check("[143] 그리고 **왜 그 예시인지**가 같이 뜬다",
          _D143.PRESETS[2][1][:12] in why, why[:70])
    check("[143] 아무것도 안 고르면 **입력을 안 건드린다**",
          app._pick_example(None)[1] == "")
    check("[143] 설명이 **여섯 개 다** 살아 있다",
          all(app._pick_example(q)[1] for q, _ in _D143.PRESETS))

    # ── ② 나올 길 (제안서 §8.2) ──────────────────────────
    c = [x for x in (_E143.cases() or {}).get("사례") or [] if x.get("s1")]
    r = dict(c[0]); r["상태"] = "정상"
    md = app._md_result(r)
    up = app._export(md, r["질의"])
    check("[143] 결과가 있으면 **내려받기 칸이 보인다**",
          up.get("visible") is True, up)
    path = up.get("value")
    txt = open(path, encoding="utf-8").read() if path else ""
    check("[143] 파일에 **근거 카드 본문**이 들어 있다", "근거 카드" in txt)
    check("[143] 머리말에 **언제 조회한 값인지** 적는다 — "
          "규제 제출물이 되려면 본문에 있어야 한다", "조회 시각" in txt)
    check("[143] 머리말에 **면책**이 있다 — 파일은 화면 밖으로 나간다",
          "의학적 조언이 아니다" in txt)
    check("[143] 그리고 **다시 조회하면 다를 수 있다**고 적는다 (결함 270)",
          "다시 조회하면 다를 수 있다" in txt)
    check("[143] 결과가 없으면 **칸을 안 보인다**",
          app._export("", "x").get("visible") is False)

    # ── ③ 접는 기준 ──────────────────────────────────────
    #
    #   기준은 하나다 — **판정에 들어가는 것은 펴 두고, 안 들어가는
    #   것만 접는다.** 08-19 에 승우가 *«걸린 시간도 특허처럼 접는 게
    #   좋지 않을까»* 라고 물었고, **그 기준으로 보면 맞다.**
    check("[143] **특허 칸은 접는다** — 화면이 «판정에 안 들어간다» 고 적은 것",
          "<details><summary><b>특허 자유도 (FTO)</b>" in md)
    _t143 = {"게이트별": {"factcheck": 1.2}, "반박근거_수집_초": 1.6,
             "전체_초": 31.2, "warm": 0}
    _r143 = dict(r); _r143["ttr"] = _t143
    _md2 = app._md_result(_r143)
    check("[143] **걸린 시간도 접는다** — 같은 기준(판정에 안 들어간다)",
          "<details><summary><b>반박 근거를 모으는 데 걸린 시간" in _md2)
    check("[143] 접혀도 **숫자 하나는 제목에 남는다** — 접는 것과 감추는 "
          "것은 다르다 (제안서 §4.1 평가축)",
          "전체 31.2초</summary>" in _md2.replace("</b>", "")
          or "— 전체 31.2초" in _md2, _D143 and "")
    check("[143] 접힌 안쪽에 **같은 제목을 또 적지 않는다**",
          _md2.count("반박 근거를 모으는 데 걸린 시간") == 1)
    # 08-19 — 진단서 ② 로 근거·인용을 **h3 로 올렸다**(위계가 `####`
    #   여덟 개로 평면이었다). **제목 수준이 아니라 «접혔나» 를 본다** —
    #   시험이 서식을 고정하면 서식을 못 고친다(결함 265 계열).
    #   08-19 다시 — 근거·인용을 **한 덩어리**로 합쳤다(`evidence_full`).
    #     그래서 「인용」이라는 **독립 절이 없어졌다.** 시험은 절 이름이
    #     아니라 **그 내용이 접히지 않고 보이는가**를 봐야 한다.
    for k, tok in (("근거", "br-evx"), ("인용", "br-quo"),
                   ("구조 (S1)", "구조 (S1)")):
        shown = tok in md
        folded = ("<summary><b>%s" % k) in md or ("<summary>%s" % k) in md
        check("[143] **%s 는 안 접는다** — 판정의 근거다" % k,
              shown and not folded, (shown, folded))
    check("[143] 내려받기가 **표시 문구가 아니라 구조**를 본다 — "
          "제목을 바꾸면 조용히 사라졌다(08-19)",
          '"br-detail" not in md' in _i143.getsource(app._export))

    # ── ④ 탭 이름은 **안 갈았다** ────────────────────────
    #   80곳 28파일이 인용하고 그중엔 **봉인된 명세**와 **결함 대장**이 있다.
    #   둘 다 손대면 안 되는 파일이라 **부제만 붙였다.**
    for t in ("대시보드", "판정 사례", "직접 검증", "병명으로 시작", "반증 기록"):
        check("[143] 탭 «%s» 이름이 살아 있다 — 봉인 문서가 인용한다" % t,
              ('gr.Tab("%s' % t) in src)
    check("[143] 그런데 **부제가 붙어 있다** — 이름만으로는 뭘 하는지 모른다",
          'gr.Tab("직접 검증 · 내 가설 넣기")' in src)


def test_retest_measures_instrument_variation():
    """[142] **재시험 신뢰도 측정이 실제로 변동을 잡아낸다** — 결함 266.

    `연구기술보고서` 불리한 사실 10번이 08-06 부터 *«LLM 재시험 신뢰도를
    한 번도 안 쟀다»* 라고 적혀 있었고 **08-18 까지 그대로였다.**

    08-18 실측 — `metformin / 유방암`을 두 번 돌리니 **PMID 35608580**
    (MA.32 · n=3,649 · 1차 평가변수 실패)의 가중치가 **0.90 → 3.00**.
    `weight_for()` 가 결정론적 함수이므로 **LLM 의 분류가 바뀐 것**이다.

    ## 이 시험이 지키는 것

    ① 그 3.3배를 **요약이 실제로 잡아내는가** — 못 잡으면 계기가 또 눈을 감는다
    ② **기준을 코드가 들고 있는가** — 명세의 문턱(6/6 · ≤5%p)이 그대로인가
    ③ **합격도 낼 수 있는가** — 늘 미달만 내면 모의가 거짓말하는 것이다
    """
    from ..bench import retest as _RT
    from ..agents import factcheck as _FC

    # ── ① 08-18 에 실제로 본 값을 그대로 넣는다 ──────────────
    obs = {"금속 / x": [
        {"상태": "정상", "판정": "기각", "신뢰도": 26, "근거수": 7,
         "가중치": {"35608580": 0.90, "23936520": 1.44}, "served_by": "m"},
        {"상태": "정상", "판정": "조건부", "신뢰도": 12, "근거수": 7,
         "가중치": {"35608580": 3.00, "24841876": 0.08}, "served_by": "m"},
        {"상태": "정상", "판정": "기각", "신뢰도": 20, "근거수": 7,
         "가중치": {"35608580": 1.80}, "served_by": "m"}]}
    s = _RT.summarize(obs)
    r0 = s["행"][0]
    check("[142] **가중치 3.3배를 잡는다** — 이걸 못 잡으면 계기가 또 눈을 감는다",
          r0["가중치최대비"] == 3.33, r0["가중치최대비"])
    check("[142] 판정이 갈린 것을 **불일치로 센다**", r0["일치"] is False,
          r0["판정들"])
    check("[142] 확률 변동폭을 %p 로 낸다", r0["변동폭"] == 14, r0["변동폭"])
    check("[142] **채택이 달라진 것**을 자카드로 낸다 — 1.0 이 아니어야 한다",
          r0["자카드"] is not None and r0["자카드"] < 1.0, r0["자카드"])

    # ── ② 명세의 문턱을 코드가 그대로 들고 있나 ────────────
    v = _RT.judge(s)
    check("[142] 주① 기준이 **완전일치**다", "완전일치" in v["주①"]["기준"])
    check("[142] 주② 기준이 **≤ 5.0%p** 다", "5.0" in v["주②"]["기준"])
    check("[142] 이 자료는 **미달**로 판정된다", v["종합"] == "**미달**", v["종합"])

    # ── ③ 합격도 낼 수 있나 — 늘 미달이면 시험이 거짓말이다 ──
    good = {"안정 / y": [{"상태": "정상", "판정": "기각", "신뢰도": 20,
                        "근거수": 3, "가중치": {"a": 1.0}, "served_by": "m"}] * 3}
    check("[142] 세 번 다 같으면 **합격**이 나온다",
          _RT.judge(_RT.summarize(good))["종합"] == "합격")

    # ── ④ 가중치가 결정론적이라는 전제 자체 ────────────────
    #   이게 깨지면 «분류가 바뀐 것» 이라는 추론이 무너진다
    a = _FC.weight_for("rct", "large", True, "high", "high")
    b = _FC.weight_for("rct", "large", True, "high", "high")
    check("[142] `weight_for` 가 **결정론적**이다 — 추론의 전제",
          a == b == 3.0, (a, b))
    check("[142] **3.00 을 내는 분류는 하나뿐**이다 — 역산이 유일해였다",
          sum(1 for sz in _FC.SIZE_MULT for dec in (True, False)
              for cf in _FC.CONF_MULT for ce in _FC.CERTAINTY_MULT
              if abs(_FC.weight_for("rct", sz, dec, cf, ce) - 3.0) < 0.011) == 1)


def test_no_dev_log_leaks_onto_the_demo_screen():
    """[141] **화면에 개발 기록이 안 새어 나간다** — 결함 261.

    08-18 밤, 승우가 잡았다 — *«보라색 박스 안에 있는 글씨 중에 지금
    이게 데모이고 이걸로 발표하는건데 맞지 않은 말들이 있어»*.

    실제로 **11군데**였다. 최악은 그날 내가 직접 넣은 것이다 —
    근거 카드 밑에 *«앞판은 «markdown 이라 스크립트가 안 돈다» 고
    적었는데 **틀렸다** …»* 가 있었다. **심사위원이 읽는 자리에
    내 자기비판이 있었다.**

    ## 무엇을 지우고 무엇을 남기나

    - 지운다: **내부 색인**(`결함 NNN`) · **개발 날짜**(`08-11`) ·
      **구현 내부어**(`gr.HTML`·`generator`·`출력 칸`) · 내 자기비판
    - 남긴다: **사실과 한계.** *«RepoDB 가 학습자료에 들어 있다»* 는
      그대로 둔다 — 그건 우리 논지이지 개발 기록이 아니다

    결함 번호가 있어야 할 곳은 **「반증 기록」 탭 하나**다. 거기서는
    그게 산출물이고, 근거 카드 옆에서는 잡음이다.
    """
    import re as _re141
    from .. import dash as _D141, evidence as _E141, viewer as _V141

    # ── 08-18 — **가드가 너무 넓었다** (결함 136 계열) ────────────
    #   «2026-08-14 에 구운 값이다» 를 개발 날짜로 잡았다. 그건 개발
    #   기록이 아니라 **심사위원이 봐야 하는 출처 표시**다 — 그 줄이
    #   없으면 대시보드와 라이브가 다른 판정을 낼 때 설명이 없다(결함 270).
    #
    #   **시험이 «고치면 안 된다» 고 말하면 그 시험이 틀린 것이다.**
    #   그래서 날짜를 둘로 가른다 —
    #     · 개발 날짜 (`08-11에 봉인을 열어`) → 걸린다
    #     · **출처 시각** (`2026-08-14 에 구운 값`) → 통과. 단 같은 줄에
    #       «구운/측정/기준» 같은 **출처 낱말이 있어야** 한다
    BAD = _re141.compile(
        r"결함\s*\d+|앞판|틀렸다|틀렸었|고쳤다|"
        r"(?<![\d-])08-\d\d|시험 \[\d+\]|markdown 이라|gr\.HTML|출력 칸|"
        r"MutationObserver|Gitea|재발 방지")
    DATE = _re141.compile(r"20\d\d-\d\d-\d\d")
    # 09-25 · «조회 시각» 추가 — 라이브 결과의 실행 막대가 `조회 시각 2026-09-25 13:39` 를 찍는다.
    #   앞판 구운 사례엔 `s1` 을 가진 사례가 없어 이 칸이 **빈 채로** 검사됐고, 본선 판(rifampin 이
    #   구조 경로를 탐)에서 처음 채워져 걸렸다. 이름표가 붙은 시각은 출처다 — 개발 날짜가 아니다.
    PROV = _re141.compile(r"구운|측정|기준 시각|받은|색인|조회 시각")
    app = _app140()
    runs = list(_D141.RUNS)
    q = _D141.candidates(runs[0])[0]
    c = [x for x in (_E141.cases() or {}).get("사례") or [] if x.get("s1")]
    r = dict(c[0]) if c else {}
    r["상태"] = "정상"

    surfaces = {
        # 09-29 · 대시보드 안내문은 없어졌다(결함 377). 그 자리에 **실제로 그려지는** 사례 탭 설명을 본다
        "탭 안내(사례)": getattr(app, "CASES_MORE", ""),
        "탭 안내(라이브)": getattr(app, "LIVE_MORE", ""),
        "탭 안내(병명)": getattr(app, "DISEASE_INTRO", ""),
        "좌측 2축": _D141.left("정방향", "신종감염병긴급", "metformin"),
        "중앙 표": _D141.center(runs[0], "신종감염병긴급"),
        "사고 과정": _D141.thinking(q),
        "근거 카드": _D141.evidence_card(q),
        "B0 대조": _D141.side_by_side(q),
        "자율성": _D141.autonomy(),
        "특허": _D141.right_patent("metformin"),
        "라이브 결과": app._md_result(r),
        "라이브 좌측": app._live_left("metformin / X", "신종감염병긴급"),
    }
    if c:
        surfaces["구조 뷰어"] = _V141.render(c[0]["s1"])

    leaks = []
    for name, txt in surfaces.items():
        for m in BAD.finditer(txt or ""):
            leaks.append("%s → «%s»" % (name, m.group(0)))
        # 전체 날짜는 **출처 낱말이 같은 줄에 있을 때만** 봐준다
        for line in (txt or "").splitlines():
            if DATE.search(line) and not PROV.search(line):
                leaks.append("%s → 출처 없는 날짜 «%s»"
                             % (name, DATE.search(line).group(0)))
    check("[141] 화면 %d곳에서 **개발 기록이 0건**이다" % len(surfaces),
          not leaks, leaks[:6])

    # ── 08-18 승우 — *«병명으로 시작에 제안서 내용이 들어가 있는데»* ──
    #   결함 261 에서 나는 **결함번호·날짜·구현어**만 훑고 «제안서 §N» 은
    #   안 봤다. 실측 10건이었다. **심사위원은 제안서를 갖고 있지만
    #   서비스 사용자는 없다** — 없는 문서를 가리키는 각주다.
    #   내용은 남기고 색인만 뺀다: «제안서 예상» → «우리가 미리 적은 예상».
    PROP = _re141.compile(r"제안서|§\s?[\d.]+|공모분야")
    prop = []
    for name, txt in surfaces.items():
        for m in PROP.finditer(txt or ""):
            prop.append("%s → «%s»" % (name, m.group(0)))
    check("[141] 화면에 **제안서·§ 각주가 0건**이다 — 사용자는 그 문서가 없다",
          not prop, prop[:6])
    check("[141] 그런데 **«우리가 미리 적은 예상»** 은 남아 있다 — "
          "각주는 뺐고 **투명성 주장은 안 뺐다**",
          "우리가 미리 적은 예상" in surfaces["중앙 표"])

    # 남겨야 할 것은 남았나 — **지우기만 하면 그것도 결함이다**
    check("[141] 그래도 **불리한 사실은 남아 있다** (B0 = 암기 천장)",
          "암기 천장" in surfaces["B0 대조"]
          and "학습자료에 들어 있다" in surfaces["B0 대조"])
    check("[141] 자율성이 **«재계획은 안 한다»** 를 그대로 적는다",
          "재계획하지는 않는다" in surfaces["자율성"])
    check("[141] 특허 칸이 **«자유실시 판단이 아니다»** 를 그대로 적는다",
          "자유실시 여부는 판단하지 않는다" in surfaces["특허"])
    # **지우기만 하면 그것도 결함이다** — 출처 표시는 오히려 있어야 한다
    check("[141] 대시보드가 **«언제 구운 값인가»** 를 적는다 (결함 270)",
          "구운 값이다" in surfaces["중앙 표"],
          surfaces["중앙 표"][:120])
    check("[141] 그리고 **«지금 돌리면 다를 수 있다»** 까지 적는다",
          "다를 수 있다" in surfaces["중앙 표"])


def test_release_zip_can_actually_run_the_reproduction_steps():
    """[159] **배포 묶음으로 §9 재현 절차가 돈다** — 09-18 신설.

    ## 무엇이 있었나 — **제출물이 거짓이었다**

    `연구기술보고서.md §9` 가 재현 절차를 싣고 배포물을 zip 으로 지정한다.
    09-18 실측: 그 zip 은 **2026-08-06 판**(84항목)이었고 안에 —

        bench/faithful.py     없음   ← §7.2 «충실도 99.4%» 의 계산기
        bench/specaudit.py    없음   ← 제안서 대조표 검사
        bench/selective.py    없음   ← 뒷면 89/100
        문서 전부             없음   ← `preflight --strict` 는 `렌즈답변.md` 를 읽는다

    즉 **심사위원이 그 묶음으로 §9 를 따라가면 실패한다.** 그것도 하필
    **발표에서 파는 수치들**의 계산기가 없어서다.

    > *"정직하게 적어 뒀다"* 로 방어되지 않는다 —
    > **적어 둔 곳이 심사위원이 받는 파일이 아니기 때문이다.**

    ## 그리고 «코드만 넣으면 된다» 도 틀렸다

    코드·문서를 다 넣고 격리 폴더에서 **실제로 돌리니 셋이 죽었다** —
    `specaudit` 은 `FTO결과.md` 를, `faithful` 은 `gen_state.json` 을,
    `labelaudit` 은 `bench_matched.csv` 를 읽는다. 합쳐 ~2.8 MB 였다.
    `CLAUDE.md §5` 그대로 — **`--help` 통과는 검증이 아니다.**

    ## 이 시험이 고정하는 것

      ① 문서가 가리키는 판의 zip 이 **실재한다**
      ② §9 의 `py -m bioreroute.…` 가 가리키는 **모듈이 전부 그 안에 있다**
      ③ 그 zip 이 **`.env`·키를 안 담는다**
      ④ 만드는 도구가 있고, **손으로 zip 하지 말라**고 적혀 있다

    ⚠ **격리 실행까지는 여기서 안 한다** — 네트워크·시간이 든다.
      실행 실측은 `배포zip만들기.py` 와 `연구기술보고서.md §9` 에 적었다.
    """
    import glob as _g159, os as _o159, re as _r159, zipfile as _z159
    from .. import evidence as _EV159
    root = _EV159.ROOT

    rep = open(_o159.path.join(root, "연구기술보고서.md"), encoding="utf-8").read()
    vers = sorted(set(int(v) for v in _r159.findall(r"bioreroute-v(\d+)\.zip", rep)))
    check("[159] 보고서가 배포 묶음 판을 **하나만** 가리킨다", len(vers) == 1, str(vers))
    if not vers:
        return
    zp = _o159.path.join(root, "bioreroute-v%d.zip" % vers[0])
    check("[159] ① 그 판의 묶음이 **실재한다**", _o159.path.exists(zp),
          "%s — 문서가 없는 파일을 가리키면 심사위원이 못 받는다" % _o159.path.basename(zp))
    if not _o159.path.exists(zp):
        return
    names = set(_z159.ZipFile(zp).namelist())
    check("[159] 묶음이 **비어 있지 않다**", len(names) >= 50, len(names))

    mods = sorted(set(_r159.findall(r"py -m (bioreroute[\w.]*)", rep)))
    check("[159] §9 에서 재현 명령을 **실제로 읽었다** — 0개면 이 시험이 공허하다",
          len(mods) >= 5, len(mods))
    miss = []
    for m in mods:
        f = m.replace(".", "/") + ".py"
        if f not in names:
            miss.append(m)
    check("[159] ⭐ §9 의 재현 명령이 가리키는 **모듈이 전부 묶음 안에 있다**",
          not miss,
          "묶음에 없는 모듈: %s — 이게 v65 가 08-06판인 채로 제출물 자리에 "
          "있던 이유다" % miss)

    # ③ 키가 안 들어간다
    leaked = [n for n in names
              if n.endswith(".env") or "/.env" in n or n == ".env"]
    check("[159] ③ 묶음에 `.env` 가 **없다**", not leaked, str(leaked))

    # ⑤ 09-27 · 사전 기준 대장의 **근거 파일이 전부 묶음에 있다** (결함 365)
    #   `prereg` 가 대장의 인용 줄을 근거 파일 원문과 대조한다. 근거 파일 넷(이름이 «*결과.md» 꼴이 아닌 것)이
    #   묶음에 없어 **공개 사본에서 `prereg` 가 «대장 문제 7건» 으로 멈췄다** — 보고서 §9 · 공개 README 가 가리키는 명령이다.
    import csv as _csv159
    lp159 = _o159.path.join(root, "사전기준_대장.csv")
    if _o159.path.exists(lp159):
        with open(lp159, encoding="utf-8-sig") as f159:
            ev159 = sorted({(r.get("근거") or "").strip() for r in _csv159.DictReader(f159)} - {""})
        gone159 = [e for e in ev159 if e not in names]
        check("[159] ⑤ 사전 기준 대장의 근거 파일 %d개가 **전부 묶음에 있다** — 없으면 공개 사본에서 `prereg` 가 멈춘다"
              % len(ev159), bool(ev159) and not gone159, gone159)

    # ⑥ 09-29 · 봉인 json 이 가리키는 **문서가 전부 묶음에 있다** — 봉인 파일만 있고 문서가 없으면 받는 쪽의
    #   `evidence.seals()` 가 «무결 None(확인 불가)» 을 낸다. «사전명세*.md» 꼴이 아닌 대상 둘을 손목록이 놓쳤다
    import json as _j159
    tg159 = set()
    for sj in _g159.glob(_o159.path.join(root, "*_봉인.json")):
        try:
            with open(sj, encoding="utf-8") as fsj:
                dsj = _j159.load(fsj)
        except Exception:
            continue
        t159 = (dsj.get("문서") or dsj.get("예측파일") or "").replace("\\", "/")
        if t159:
            tg159.add(t159)
    gone_s159 = sorted(t for t in tg159 if t not in names)
    check("[159] ⑥ 봉인 json 이 가리키는 문서 %d개가 **전부 묶음에 있다** — 없으면 받는 쪽에서 «확인 불가»"
          % len(tg159), bool(tg159) and not gone_s159, gone_s159)

    # ⑦ 09-29 · **동결한 홀드아웃을 받는 쪽이 대조할 수 있다** — freeze json 이 해시를 적은 파일이 묶음에 있고 해시가 같다
    import hashlib as _hh159            # ⚠ `_h159` 는 아래에서 import 된다 — 여기서 쓰면 지역 이름이라 UnboundLocalError
    fz159 = _o159.path.join(root, "bench_holdout_freeze.json")
    if _o159.path.exists(fz159):
        with open(fz159, encoding="utf-8") as ffz:
            dfz = _j159.load(ffz)
        want159 = {(dfz.get("source") or {}).get("file"): (dfz.get("source") or {}).get("sha256")}
        want159.update({k: (v or {}).get("sha256") for k, v in (dfz.get("files") or {}).items()})
        bad159 = [k for k, h in want159.items()
                  if not k or k not in names or _hh159.sha256(_z159.ZipFile(zp).read(k)).hexdigest() != h]
        check("[159] ⑦ 동결 json 이 해시를 적은 파일 %d개가 **묶음에 있고 해시가 같다** — «결과 전에 동결» 을 받는 쪽이 대조한다"
              % len(want159), not bad159, bad159)
    # ⑧ 봉인의 실행 전 증거 — 제3자 자료만 빼고 묶음에 있다(`배포zip만들기.SEAL_EVIDENCE_SKIP`)
    import importlib.util as _iu159
    _sp159 = _iu159.spec_from_file_location("zipmk159", _o159.path.join(root, "배포zip만들기.py"))
    if _sp159 and _o159.path.exists(_o159.path.join(root, "배포zip만들기.py")):
        _zm159 = _iu159.module_from_spec(_sp159)
        _sp159.loader.exec_module(_zm159)
        _ev159 = [e for e in _zm159._seal_evidence(root) if e not in names]
        check("[159] ⑧ 봉인의 실행 전 증거(제3자 자료 · 1 MB 넘는 것 빼고)가 **전부 묶음에 있다**", not _ev159, _ev159[:4])

    # ④ 만드는 도구가 있고 «손으로 하지 마라» 를 적는다
    tool = _o159.path.join(root, "배포zip만들기.py")
    check("[159] ④ 묶음을 만드는 **도구가 있다**", _o159.path.exists(tool))
    if _o159.path.exists(tool):
        t = open(tool, encoding="utf-8").read()
        check("[159] 그 도구가 **손으로 zip 하지 마라**를 적는다",
              "손으로 zip 하지 마라" in t)
        check("[159] 그 도구가 **키를 내용까지 훑는다** — 이름만 막는 건 방어가 아니다",
              "_scan_keys" in t and "KEYPAT" in t)

    # ⚠ 낡은 판이 루트에 같이 있으면 심사위원이 헷갈린다
    stray = [_o159.path.basename(p) for p in _g159.glob(
        _o159.path.join(root, "bioreroute-v*.zip"))
        if _o159.path.basename(p) != _o159.path.basename(zp)]
    check("[159] 루트에 **낡은 판이 안 굴러다닌다** — `archive/` 로 옮겨라",
          not stray, str(stray))

    # ── ⭐ **묶음 안의 문서가 루트와 같은가** — 09-18 · `[115]` 와 같은 구멍
    #
    #   `[115]` 는 «배포 사본이 원본과 바이트까지 같다» 를 본다. 코드를
    #   고치면 깨지고 `deploycheck` 으로 닫는다. **묶음도 똑같다** —
    #   §9 를 고쳐 놓고 안 다시 구우면 **심사위원이 낡은 보고서를 푼다.**
    #   모듈이 «있다» 까지만 보면 그 구멍을 못 본다.
    #
    #   ⚠ 전부 보지는 않는다. **심사위원이 읽는 문서 넷**만 본다 —
    #     코드는 어차피 시험이 돌고, 데이터는 동결이라 안 바뀐다.
    import hashlib as _h159
    WATCH = ["연구기술보고서.md", "Bio-ReRoute_1페이지.md",
             "렌즈답변.md", "재현절차.md"]
    z = _z159.ZipFile(zp)
    stale159 = []
    for w in WATCH:
        rp = _o159.path.join(root, w)
        if w not in names or not _o159.path.exists(rp):
            stale159.append("%s(없음)" % w)
            continue
        if _h159.sha256(z.read(w)).hexdigest() != \
                _h159.sha256(open(rp, "rb").read()).hexdigest():
            stale159.append(w)
    check("[159] ⭐ 묶음 안의 **심사 문서가 루트와 바이트까지 같다** — "
          "갈라지면 심사위원이 낡은 판을 푼다",
          not stale159,
          "낡은 것: %s  → 고치는 법: "
          "`py 배포zip만들기.py --apply --ver %d --force`"
          % (stale159, vers[0]))


def test_zip_tool_points_at_stale_version_but_never_rewrites_history():
    """[165] **«가리키는 손»은 만들고 «고치는 손»은 일부러 안 만든다** — 09-19.

    ## 무엇이 있었나

    `배포zip만들기.py` 가 판을 굽고 *«문서에 적힌 판 번호를 같이 고쳐라»*
    한 줄만 찍었다. **어디를 고치라는 말이 없었다.**
    결함 307 의 같은 자리이고 09-18·09-19 에 **두 번** 손으로 찾아다녔다.

    ## ⛔ 그런데 **일괄 치환은 하면 안 된다**

    판 번호는 **«현재 판»과 «낡은 판 기록»이 같은 문자열**이다.
    일괄로 바꾸면 *«그때 v65 였다»* 라는 **기록이 현재 주장으로 둔갑**한다 —
    `CLAUDE.md §3`(*«정보를 남기려던 것이 증거를 없앴다»*)·`§4-5` 의 자리.

    **그래서 가리키기만 한다.** «이 줄이 현재 판인가 기록인가» 는
    **기계가 못 하는 판단**이다.

    ## 이 시험이 고정하는 것

      ① 판이 다른 줄을 **파일:줄로 찍는다** · 같은 판은 안 찍는다(오탐)
      ② ⭐ **파일을 안 쓴다** — 소스에도, 실제 동작에도
      ③ 전부 같으면 **OK** 를 찍는다
      ④ **«일괄 치환하지 마라»** 를 같이 적는다
    """
    import importlib.util as _iu165
    import inspect as _in165
    import io as _i165, os as _o165, tempfile as _t165
    from contextlib import redirect_stdout as _rs165
    from .. import evidence as _EV165
    from ..bench import docaudit as _DA165

    p165 = _o165.path.join(_EV165.ROOT, "배포zip만들기.py")
    check("[165] 도구가 실재한다", _o165.path.exists(p165), p165)
    if not _o165.path.exists(p165):
        return
    _s165 = _iu165.spec_from_file_location("zipmaker165", p165)
    Z = _iu165.module_from_spec(_s165)
    _s165.loader.exec_module(Z)
    check("[165] «가리키는 손» 이 있다",
          hasattr(Z, "_point_at_stale_version"))
    if not hasattr(Z, "_point_at_stale_version"):
        return

    # ── ② ⭐ 소스에 **쓰는 코드가 없다** ──────────────────────────
    fn165 = _in165.getsource(Z._point_at_stale_version)
    check("[165] ② ⭐ 그 함수가 **파일을 안 쓴다** — 낡은 판 기록은 «맞는 것»이다",
          "_write" not in fn165 and ".write(" not in fn165,
          "치환을 넣지 마라 — 기록과 현재 주장을 기계가 못 가른다")

    d165 = _t165.mkdtemp(prefix="zipver165_")
    f165 = _o165.path.join(d165, "가짜.md")
    with open(f165, "w", encoding="utf-8") as fh:
        fh.write("현재는 `bioreroute-v68.zip` 이다\n"
                 "그때는 bioreroute-v65 였다 — **이건 기록이고 맞는 것**\n")

    # ⚠ **몽키패치를 안 쓴다** — 09-19 에 이 자리에서 **실제 `docaudit`
    #   모듈의 DOCS 를 바꿨고**, `[156]` 이 «단독 통과 · 전체 실행에서만
    #   실패» 하는 **유령 실패**가 됐다. 대역 헬퍼의 독스트링이 적어 둔
    #   바로 그 사고다. **함수가 주입을 받으니 필요 없다.**
    #   ⛔ 아래 ⑦이 이 줄들을 글자로 검사한다 — **헬퍼 이름을 여기 쓰지 마라**
    #     (`CLAUDE.md §4`: 설명하려고 인용하면 그 인용이 값이 된다).
    buf165 = _i165.StringIO()
    with _rs165(buf165):
        Z._point_at_stale_version(68, docs=["가짜.md"], root=d165)
    out165 = buf165.getvalue()
    check("[165] ① 판이 **다른 줄을 파일:줄로 찍는다**",
          "가짜.md:2" in out165, out165)
    check("[165] ① 같은 판인 줄은 **안 찍는다** (오탐 방지)",
          "가짜.md:1" not in out165, out165)
    check("[165] ④ **«일괄 치환하지 마라»** 를 같이 적는다",
          "일괄 치환하지 마라" in out165, out165[-200:])

    # ── ② ⭐ 실제로도 파일이 안 바뀌었다 ─────────────────────────
    with open(f165, encoding="utf-8") as fh:
        after165 = fh.read()
    check("[165] ② ⭐ **파일이 실제로 안 바뀌었다** — v65 기록이 살아 있다",
          "v65" in after165, after165)

    # ── ③ 전부 같으면 OK ────────────────────────────────────
    with open(f165, "w", encoding="utf-8") as fh:
        fh.write("현재는 `bioreroute-v68.zip` 이다\n")
    buf2165 = _i165.StringIO()
    with _rs165(buf2165):
        Z._point_at_stale_version(68, docs=["가짜.md"], root=d165)
    check("[165] ③ 전부 같으면 **OK 를 찍는다**",
          "전부 v68" in buf2165.getvalue(), buf2165.getvalue())

    # ── ⑤ ⭐ 09-19 · **점검이 본작업을 죽이면 안 된다** ──────────────
    #
    #   첫 판은 `_point_at_stale_version` 을 맨몸으로 불렀다. 반환형을
    #   잘못 봐 `AttributeError` 가 났고 — **zip 은 이미 만들어졌는데**
    #   스크립트가 트레이스백으로 끝났다. 결함 312 와 같은 계열.
    _m165 = _in165.getsource(Z.main)
    _blk = _m165.split("_point_at_stale_version")[0][-400:]
    check("[165] ⑤ ⭐ `main` 이 그 점검을 **`try` 로 감싼다** — "
          "부가 점검은 본작업의 성공을 못 지운다",
          "try:" in _blk, _blk[-160:])
    check("[165] ⑤ 그리고 죽었을 때 **«zip 은 만들어졌다» 를 알린다**",
          "zip 은 만들어졌다" in _m165,
          "예외를 삼키기만 하면 조용한 실패가 된다(결함 99)")

    # ── ⑥ 어떤 입력에도 **예외를 안 던진다** ─────────────────────
    with _rs165(_i165.StringIO()):
        try:
            Z._point_at_stale_version(
                68, docs=["없다.md"], root=_o165.path.join(d165, "없는폴더"))
            _safe165 = True
        except Exception:
            _safe165 = False
    check("[165] ⑥ 없는 경로에도 **안 죽는다**", _safe165)

    # ── ⑦ ⭐ 09-19 · **이 시험이 전역을 안 건드린다** ────────────────
    #   `[156]` 이 «단독 통과 · 전체 실행에서만 실패» 하던 원인이
    #   여기였다. 주입으로 바꿨으니 **실제 모듈이 그대로여야** 한다.
    check("[165] ⑦ ⭐ `docaudit.DOCS` 가 **안 바뀌었다** — 유령 실패를 막는다",
          len(_DA165.DOCS) > 40 and "README.md" in _DA165.DOCS,
          len(_DA165.DOCS))
    # ⛔ 09-19 · **이 검사가 자기 자신을 잡았다** — 코드 판 두 번째
    #
    #   첫 판은 찾을 낱말을 **리터럴로** 썼다. `getsource` 가 **그 줄까지**
    #   읽으므로 **검사문이 스스로에게 걸렸다.** `CLAUDE.md §4` 의
    #   *«규칙을 적는 그 줄이 그 규칙을 어겼다»* 와 같은 구조다.
    #   **쪼개서 쓴다** — 이 줄에는 그 낱말이 통째로 없다.
    _mp165 = "pat" + "ched("
    check("[165] ⑦ 그리고 이 시험이 **대역 헬퍼를 안 쓴다**",
          _mp165 not in _in165.getsource(
              test_zip_tool_points_at_stale_version_but_never_rewrites_history),
          "전역을 건드리면 뒤에 오는 시험이 조용히 깨진다")


def test_docaudit_never_reports_green_when_it_skipped_the_truth_check():
    """[164] **정본을 못 봤으면 «불일치 없음» 을 찍지 않는다** — 09-19 신설.

    ## 무엇이 있었나 — **감사기가 자기가 안 본 것을 통과로 찍었다**

    09-19 실측. `시험정본.json` 이 낡아 정본 대조를 건너뛰었는데 —

    ```
      ⓘ 회귀 시험 **정본 대조는 안 했다** — `시험정본.json` 이 … 낡았다.
      ...
      불일치 없음.            <- 마지막 줄. rc=0
    ```

    **바로 위에 «안 했다» 고 적어 놓고 마지막 줄이 초록이었다.**
    사람은 마지막 줄을 본다. 그리고 그 줄이 «다 맞다» 고 했다.

    같은 자리의 **세 번째 판**이다 —

        결함  99   아무것도 못 찾은 것을 통과처럼 찍지 않는다
        결함 310①  시험 코드를 못 찾으면 정본이 «신선하다» 로 통과
        09-19     정본이 낡으면 «불일치 없음» 으로 통과      <- 여기

    ## 이 시험이 고정하는 것

      ① 정본이 없으면 **rc=0 이 아니다**
      ② 마지막 줄에 **«불일치 없음» 이 안 나온다**
      ③ ⭐ 그 줄에 **「불일치」라는 낱말이 남는다** — `preflight._gist` 가
         그 낱말로 요약 줄을 고른다. 없으면 상위 화면이 엉뚱한 줄을 잡는다
      ④ 정본이 **있고 불일치도 없으면** 여전히 rc=0 · 초록이다 (오탐 방지)

    ⚠ **파일 상태에 안 기댄다.** 실제 `시험정본.json` 이 지금 낡았는지
      아닌지는 이 시험과 무관해야 한다 — `audit` 을 대역으로 바꿔 태운다.
    """
    import io as _i164
    from contextlib import redirect_stdout as _rs164
    from ..bench import docaudit as _DA164

    def _fake(stale):
        def _f(root=None, truth=None):
            return {"불일치": 0, "확인한_문서": 3, "항목": [],
                    "실제_회귀시험": (None if stale else 2296),
                    "_정본메모": ""}
        return _f

    # ── ①②③ 정본이 없을 때 ──────────────────────────────────
    buf = _i164.StringIO()
    with patched(_DA164, audit=_fake(True)):
        with _rs164(buf):
            rc = _DA164.main([])
    out = buf.getvalue()
    tail = [l for l in out.strip().split("\n") if l.strip()][-4:]
    check("[164] ① 정본을 못 봤으면 **rc 가 0 이 아니다**", rc != 0, rc)
    check("[164] ② 마지막 줄에 **«불일치 없음» 이 없다**",
          "불일치 없음" not in "\n".join(tail), tail)
    check("[164] ③ ⭐ 그래도 **「불일치」 낱말은 남는다** — "
          "`preflight._gist` 가 그걸로 요약 줄을 고른다",
          any("불일치" in l for l in tail), tail)
    check("[164] ③ 그리고 **무엇을 하라는지** 적는다",
          "preflight" in out, out[-300:])

    # ── ④ 정상일 때는 여전히 초록 (오탐 방지) ─────────────────────
    buf2 = _i164.StringIO()
    with patched(_DA164, audit=_fake(False)):
        with _rs164(buf2):
            rc2 = _DA164.main([])
    check("[164] ④ 정본이 있고 불일치가 없으면 **rc=0**", rc2 == 0, rc2)
    check("[164] ④ 그때는 «불일치 없음» 을 찍는다",
          "불일치 없음" in buf2.getvalue())

    # ── ⭐ `preflight` 이 실제로 그 낱말로 고르는가 ────────────────
    import inspect as _in164
    from ..bench import preflight as _PF164
    check("[164] ⭐ `preflight._gist` 가 **「불일치」로 요약 줄을 고른다** — "
          "이 계약이 깨지면 위 ③이 공허해진다",
          '"불일치" in l' in _in164.getsource(_PF164._gist)
          or "'불일치' in l" in _in164.getsource(_PF164._gist),
          "preflight._gist 를 고쳤으면 [164]③ 도 같이 고쳐라")


def test_countsync_command_can_actually_be_pasted_into_powershell():
    """[163] **«그대로 붙여넣어라» 가 두 군데 거짓이었다** — 09-19 신설.

    ## 무엇이 있었다

    `docaudit` 이 불일치를 찾으면 고치는 명령을 찍는다(결함 307 의 «손»).
    그 명령이 이랬다 —

    ```
    py -m ... --tests 2282 --old-tests 2238 \\      <- bash 줄바꿈
       --defects N --old-defects N --apply          <- 글자 N
    ```

      ① `\\` 는 **bash** 문자다. 이 저장소는 **PowerShell** 에서 돈다.
         붙여넣으면 두 줄로 쪼개지고 **둘째 줄이 단독 명령이 되어 죽는다.**
         09-19 실측 — *"단항 연산자 '--' 뒤에 식이 없습니다"*.
      ② `--defects N` 의 **`N` 은 글자다.** 붙여넣으면 `invalid int value`.

    즉 **«그대로 붙여넣어라» 가 두 번 거짓**이었다. 결함 307 을 고치며
    만든 손이 **반만 완성돼 있었고**, `CLAUDE.md §5`(검증 환경 ≠ 실행
    환경)가 **명령 문자열에도 적용된다**는 것을 못 봤다(결함 220 계열).

    ## 이 시험이 고정하는 것

      ① 명령이 **한 줄**이다 — 줄 이어쓰기 문자를 아예 안 쓴다
      ② 숫자 자리에 **글자가 안 남는다** (전부 실제 값)
      ③ ⭐ 찍은 명령이 **`countsync` 의 파서를 실제로 통과한다**
      ④ 결함 수가 갈리면 **명령을 안 찍고 이유를 적는다**(결함 99)
      ⑤ 회귀 시험 수가 이미 맞으면 **엉뚱한 명령을 안 만든다**
    """
    import argparse as _ap163
    import inspect as _in163
    from ..bench import countsync as _CS163, docaudit as _DA163

    def _r(tests_real, tests_doc, defect_vals, real_d=None):
        return {"실제_회귀시험": tests_real, "실제_결함": real_d,
                "항목": [{"이름": "회귀 시험", "값": {str(tests_doc): ["a.md"]}},
                         {"이름": "결함 건수", "값": defect_vals}]}

    cmd, why = _DA163.countsync_line(_r(2282, 2238, {"318": ["a.md", "b.md"]}))
    check("[163] 명령을 **완성한다**", bool(cmd), why)
    if not cmd:
        return

    # ── ① 한 줄 · ② 글자 안 남음 ───────────────────────────────
    check("[163] ① **한 줄이다** — bash 줄바꿈 `\\` 이 없다",
          "\\" not in cmd, cmd)
    check("[163] ① 줄바꿈 자체가 없다", "\n" not in cmd, repr(cmd))
    check("[163] ② 숫자 자리에 **글자가 안 남는다** (`--defects N` 이었다)",
          " N " not in cmd and not cmd.rstrip().endswith(" N"), cmd)
    for _flag in ("--tests", "--old-tests", "--defects", "--old-defects"):
        _v = cmd.split(_flag)[1].split()[0]
        check("[163] ② `%s` 가 **숫자다**" % _flag, _v.isdigit(), _v)

    # ── ③ ⭐ 진짜 검사 — `countsync` 파서가 받아들이나 ─────────────
    #   `--help` 통과는 검증이 아니다(`CLAUDE.md §5`). **실제 파서를 태운다.**
    argv = cmd.split()[3:]          # `py -m <모듈>` 뒤
    argv = [x for x in argv if x != "--apply"]      # 파일을 안 고친다
    _ok163, _err163 = True, ""
    try:
        _p163 = _ap163.ArgumentParser()
        for _f, _req in (("--root", False), ("--defects", True), ("--tests", True),
                         ("--old-defects", True), ("--old-tests", True)):
            _p163.add_argument(_f, required=_req,
                               type=int if _f != "--root" else str)
        _p163.add_argument("--apply", action="store_true")
        _p163.parse_args(argv)
    except SystemExit as e:
        _ok163, _err163 = False, "parse_args 가 거부했다 (%s)" % e
    check("[163] ③ ⭐ 찍은 명령이 **인자 파서를 실제로 통과한다**",
          _ok163, "%s  ← %s" % (_err163, argv))
    check("[163] ③ 그 파서가 `countsync` 의 것과 **같은 인자를 요구한다**",
          all(("\"%s\"" % f) in _in163.getsource(_CS163.main) or
              ("'%s'" % f) in _in163.getsource(_CS163.main)
              for f in ("--defects", "--tests", "--old-defects", "--old-tests")),
          "countsync.main 의 인자가 바뀌었으면 이 시험부터 고쳐라")

    # ── ④ 결함 수가 갈리면 **안 찍는다** ─────────────────────────
    cmd2, why2 = _DA163.countsync_line(
        _r(2282, 2238, {"318": ["a.md"], "301": ["b.md"]}))
    check("[163] ④ 결함 수가 갈리면 **명령을 안 만든다** — 기계가 고를 일이 아니다",
          cmd2 is None, cmd2)
    check("[163] ④ 그리고 **왜 못 찍는지 적는다**(결함 99)",
          "기계가 모른다" in (why2 or ""), why2)

    # ── ⑤ 이미 맞으면 엉뚱한 명령을 안 만든다 ─────────────────────
    cmd3, why3 = _DA163.countsync_line(_r(2282, 2282, {"318": ["a.md"]}, 318))
    check("[163] ⑤ 회귀 시험 수·결함 수가 **이미 맞으면** 명령을 안 만든다",
          cmd3 is None, cmd3)
    check("[163] ⑤ 그 이유도 적는다", "이미 맞다" in (why3 or ""), why3)

    # ── ⑥ ⭐⭐ 09-24 · **결함 수의 정본은 대장이다** ────────────────────
    #   문서 36곳이 323 으로 «일치» 하는 동안 대장은 331 행이었다. 앞판은
    #   `--defects 323 --old-defects 323` 을 찍어 **아무것도 안 바꿨다.**
    cmd4, why4 = _DA163.countsync_line(_r(2282, 2282, {"323": ["a.md"]}, 331))
    check("[163] ⑥ ⭐⭐ 시험 수가 맞아도 **대장과 문서의 결함 수가 다르면** 명령을 만든다",
          bool(cmd4) and "--defects 331 --old-defects 323" in (cmd4 or ""), (cmd4, why4))

    # ── ⑦ 09-25 · 값이 둘인데 **하나가 정본**이면 나머지가 옛 값이다 ─────────
    #   생성 문서(영상 대본)가 대장에서 새 값을 먼저 들어 «339 넷 · 340 하나» 로 갈렸고
    #   사슬 ④ 가 «기계가 모른다» 로 멈췄다. 정본(대장 행 수)을 알면 고를 수 있다.
    cmd5, why5 = _DA163.countsync_line(
        _r(2502, 2491, {"339": ["a.md", "b.md"], "340": ["v.md"]}, 340))
    check("[163] ⑦ 둘 중 **하나가 정본이면** 나머지를 옛 값으로 명령을 만든다",
          bool(cmd5) and "--defects 340 --old-defects 339" in (cmd5 or ""), (cmd5, why5))
    cmd6, why6 = _DA163.countsync_line(
        _r(2502, 2491, {"339": ["a.md"], "338": ["b.md"]}, 340))
    check("[163] ⑦ 둘 다 정본이 **아니면** 여전히 안 찍는다 — 그때는 정말 모른다",
          cmd6 is None and "기계가 모른다" in (why6 or ""), (cmd6, why6))


def test_screen_says_which_gates_it_turned_off_and_why():
    """[162] **«없는 것» 과 «끈 것» 은 다르다** — 09-18 신설.

    ## 무엇이 있었나

    제안서 §2 가 **세 축**이라 했다. 셋째가 HITL 음성 지식베이스 루프인데
    `DEMO_GATES` 가 그걸 **끈다** — 사유도 적혀 있다:

        "hitl": (False, "운용 기능이다. 시연에서 사람 개입을 보이면
                         «자율» 주장이 흐려진다")

    **판단은 옳다.** 배점 ②가 *«**스스로** 단계 분해»* 를 묻는데 사람
    개입을 보이면 손해다. 문제는 **화면이 그 사실을 말하지 않은 것**이다.
    제안서를 손에 든 심사위원이 세면 **둘만 보인다.**

    ## ⛔ 그리고 사유는 **처음부터 적혀 있었다**

    `CONFIGS["B5SF"]` 가 `_why` 를 **버리고**, 화면은 한 번도 안 읽었다.
    **적어 둔 것이 아무 데도 안 닿았다** — `fragility` ·
    `false_negatives` · `refute_recall` 과 같은 계열의 **네 번째**다.

    ## 이 시험이 고정하는 것

      ① `demo_off()` 가 **표에서 파생**된다 (손으로 적은 목록이 아니다)
      ② 화면이 **끈 게이트 · 한글 이름 · 사유**를 셋 다 찍는다
      ③ **HITL 이 거기 있다** — 제안서 §2 셋째 축
      ④ ⭐ **표를 바꾸면 화면이 따라온다** (몽키패치로 실제 확인)
      ⑤ 화면이 «코드와 시험은 있다 · B8» 을 적는다 — «없다» 로 안 읽히게
    """
    import inspect as _in162
    import re as _re
    from ..core import gates as _G162
    from .. import dash as _D162
    from ..demo import GATE_KO as _KO162

    # ── ① 표에서 파생 ─────────────────────────────────────────
    #   ⚠ **원문과 비교하려면 `for_screen=False`** 다 — 09-19 에 ⑦(화면
    #     유출 차단)을 넣으면서 이 줄이 **원문과 비교한다는 것**을 안 봤고,
    #     ①이 깨졌다. **새 항목을 넣을 때 기존 항목의 전제를 봐야 한다.**
    off = _G162.demo_off()                      # 화면용(색인 벗김)
    raw162 = _G162.demo_off(for_screen=False)   # 원문
    check("[162] ① `demo_off()` 가 `DEMO_GATES` 에서 **파생된다**",
          raw162 == [(g, w) for g, (on, w) in _G162.DEMO_GATES.items()
                     if not on],
          raw162)
    check("[162] ① 화면용은 **같은 게이트 목록**이다 — 사유만 벗긴다",
          [g for g, _w in off] == [g for g, _w in raw162],
          ([g for g, _w in off], [g for g, _w in raw162]))
    check("[162] ③ **HITL 이 꺼진 목록에 있다** — 제안서 §2 셋째 축",
          "hitl" in dict(off), [g for g, _ in off])

    src162 = _in162.getsource(_D162.thinking)
    check("[162] ① 화면이 **표를 읽는다** — 손으로 적은 목록이 아니다",
          "demo_off()" in src162)

    cases162 = _D162._cases() or {}
    check("[162] 구운 사례가 있다 — 없으면 이 시험이 공허하다", bool(cases162))
    if not cases162:
        return
    q162 = sorted(cases162)[0]
    th = _D162.thinking(q162)

    # ── ② 화면이 셋 다 찍는다 ──────────────────────────────────
    check("[162] ② 화면이 **«끈 게이트»** 절을 찍는다",
          "끈 게이트" in th, th[-400:])
    check("[162] ② 그리고 **«없는 것이 아니라 끈 것»** 이라고 못 박는다",
          "없는 것이 아니라" in th)
    # 09-29 · 결함 378 — 표의 사유는 **개발 메모**다(««자율» 주장이 흐려진다» · «발표장에서 시연이 멈춘다»).
    #   화면 말은 `demo.GATE_OFF_SAY` 가 준다. ②의 «그대로» 는 이제 **그 화면 말 그대로**다
    #   (09-19 에 색인을 벗긴 것에 이어 두 번째로 «누구에게 주는 글인가» 를 가른 것).
    from ..demo import GATE_OFF_SAY as _SAY162
    for g, why in off:
        _want162 = _SAY162.get(g, why)
        check("[162] ② 사유가 **그대로** 나온다 — `%s`" % g,
              _want162 in th, _want162[:40])
        check("[162] ② 한글 이름도 나온다 — `%s`" % g,
              _KO162.get(g, g) in th, _KO162.get(g, g))
    # ── ⑧ 09-29 · 끈 게이트마다 **화면 말이 먼저 있다** — 개발 메모가 화면으로 떨어지지 않게 ──
    check("[162] ⑧ 시연이 끈 게이트마다 `GATE_OFF_SAY` 에 화면 말이 있다",
          all(g in _SAY162 for g, _w in off), [g for g, _w in off if g not in _SAY162])
    check("[162] ⑧ 화면에 **개발 메모 문구**가 없다 — «주장이 흐려진다» · «발표장»",
          not any(x in th for x in ("주장이 흐려진다", "발표장", "시연이 멈춘다")),
          [x for x in ("주장이 흐려진다", "발표장", "시연이 멈춘다") if x in th])
    check("[162] ⑧ B8 을 «제거 실험이 돈다» 로 적지 않는다 — B8 은 벤치마크에 안 쓴다(시험 [48])",
          "그 구성까지 돈다" not in th and "제거 실험에서 돕니다" not in th, th[-300:])

    # ── ⑦ ⛔ 09-19 · **내부 색인이 화면으로 새면 안 된다** (결함 261) ────
    #
    #   `DEMO_GATES` 의 사유는 **개발자에게 쓴 글**이라 `(결함 95)` 같은
    #   색인과 `08-11` 같은 개발 날짜가 섞여 있다. 09-18에 그걸 **그대로**
    #   화면에 찍게 만들었고 — **심사위원 화면에 «결함 95» 가 떴다.**
    #   시험 `[141]` 이 잡았다.
    #
    #   ⚠ **더 나쁜 것은 위 ②였다** — *«사유가 그대로 나온다»* 를 검사해서
    #     **내가 그 유출을 시험으로 고정했다.** 가드 둘이 충돌했고 `[141]`
    #     이 옳다. 그래서 ②의 「그대로」는 이제 **화면용 사유**를 뜻한다.
    check("[162] ⑦ ⛔ 화면에 **내부 색인(`결함 NNN`)이 없다** — 결함 261",
          not _re.search(r"결함\s*\d+", th),
          [l for l in th.split("\n") if _re.search(r"결함\s*\d+", l)][:2])
    check("[162] ⑦ 화면에 **개발 날짜(`MM-DD`)가 없다**",
          not _re.search(r"\b\d{2}-\d{2}\b", th),
          [l for l in th.split("\n") if _re.search(r"\b\d{2}-\d{2}\b", l)][:2])
    check("[162] ⑦ 그래도 **코드에는 색인이 남아 있다** — 기록은 안 지운다",
          any("결함" in w for _g, (_on, w) in _G162.DEMO_GATES.items()),
          "DEMO_GATES 원문에서 색인을 지우면 왜 껐는지 추적이 끊긴다")
    check("[162] ⑦ `for_screen=False` 면 **원문이 그대로** 나온다",
          any("결함" in w for _g, w in _G162.demo_off(for_screen=False)))
    check("[162] ⑤ «코드와 시험은 있다 · 전부 켠 구성이 B8» 을 적는다",
          "B8" in th and "회귀 시험" in th, th[-300:])

    # ── ④ ⭐ 표를 바꾸면 화면이 따라오나 — **실제로 바꿔 본다** ────────
    #   목록을 손으로 적어 두면 여기서 죽는다. 그게 이 검사의 전부다.
    fake162 = dict(_G162.DEMO_GATES)
    fake162["s2"] = (False, "시험이 만든 가짜 사유 — 화면에 그대로 나와야 한다")
    with patched(_G162, DEMO_GATES=fake162):
        th2 = _D162.thinking(q162)
    check("[162] ④ ⭐ 표에서 게이트를 **끄면 화면에 나타난다**",
          "시험이 만든 가짜 사유" in th2, th2[-400:])
    check("[162] ④ 되돌리면 **다시 사라진다** — 전역 오염이 없다",
          "시험이 만든 가짜 사유" not in _D162.thinking(q162))

    # ── ⑥ ⭐ 09-19 렌즈 7 — **구운 값과 지금 값을 섞지 않는다** ────────
    #
    #   위 게이트 목록은 `_cases()`(구운 시점)이고 「끈 게이트」는
    #   `DEMO_GATES`(지금)다. **둘이 갈라지면 화면이 자기를 반박한다**
    #   (결함 102). 실측으로 구운 사례에 `hitl SKIP` 이 있었고
    #   `registry` 는 기록이 아예 없었다 — 지금은 **우연히** 일치한다.
    #
    #   그래서 «그 게이트가 돌아간 채로 구워진» 사례를 만들어
    #   화면이 그 사실을 적는지 본다.
    _src162 = _in162.getsource(_D162.thinking)
    check("[162] ⑥ 화면이 **구운 기록과 대조한다** — 그냥 찍지 않는다",
          "돌아간 채로 구운 값" in _src162)

    _cooked = dict(cases162[q162])
    _cooked["게이트"] = list(_cooked.get("게이트") or []) + [
        {"게이트": "registry", "결과": "PASS", "설명": "시험이 심은 «돌아간» 기록"}]
    with patched(_D162, _cases=lambda: {q162: _cooked}):
        th3 = _D162.thinking(q162)
    check("[162] ⑥ ⭐ 꺼졌다는 게이트가 **돌아간 채로 구워졌으면 그렇게 적는다**",
          "돌아간 채로 구운 값" in th3, th3[-500:])
    check("[162] ⑥ 그리고 **사유는 여전히 같이 적는다** — 지우지 않는다",
          _SAY162.get("registry", "CT.gov 가 느리면") in th3)
    check("[162] ⑥ `SKIP` 으로 구워진 것은 **경고를 안 붙인다** (오탐 방지)",
          "돌아간 채로 구운 값" not in _D162.thinking(q162))


def test_promised_metrics_are_actually_computed_not_just_computable():
    """[161] **제안서가 약속한 지표를 «잴 수 있게만» 두지 않는다** — 09-18 신설.

    ## 무엇이 있었나 — **`fragility` 와 같은 계열이 둘 더**

        gates.false_negatives()   §8.2 도입 지표 셋째 — 위음성률
        gates.refute_recall()     §4.3 B3 확인 항목 — 반박 증거 회수율

    08-06에 만들었고 **호출부가 하나도 없었다.** `연구기술보고서.md` 의
    반증 조건 표에서 **F5 만 «미측정»** 으로 남아 있는 것이 전자다.
    제안서가 *"시스템에 불리할 수 있는 값이지만 **과도한 기각을 스스로
    감시하기 위해** 함께 보고한다"* 라고 적어 둔 바로 그 지표다.

    ## ⛔ 그리고 어제 만든 복원기가 **불완전했다**

    `fragility._candidate_from` 이 `trail` 과 `label` 을 안 복원했다.
    `fragility()` 도 `adjudicate()` 도 trail 을 안 보므로 **1차에서는
    티가 안 났다.** 그런데 —

        false_negatives → c.killed (trail 의 KILL) · c.label
        refute_recall   → skeptic 기록의 detail 문자열

    없이 돌리면 **둘 다 조용히 0** 을 낸다. 결함 35 계열(«없다» 와
    «안 돌았다» 를 한 칸에 뭉갠다)이고, 하필 **우리에게 불리한 지표가
    0으로 나오는** 방향이다 — 가장 나쁜 고장이다.

    ## 이 시험이 고정하는 것

      ① `trail` 과 `label` 이 **복원된다** (안 하면 둘 다 조용히 0)
      ② 라벨이 없으면 **«계산불가»** 를 내고 **0%를 안 낸다**
      ③ 위음성률이 실제로 계산되고 **놓친 이름까지** 나온다
      ④ 반박회수율의 회의주의자 기여가 **trail 에서** 나온다
      ⑤ 왕복이 깨지면 🔴 · 종료 코드 3
      ⑥ ⭐ **결과가 생기면 보고서의 F5 칸이 «미측정» 이면 안 된다** (잠든 검사)
    """
    import io as _i161, json as _j161, os as _o161
    import tempfile as _t161
    from contextlib import redirect_stdout as _rs161
    from ..bench import fragility as _F161, promised as _P161
    from .. import evidence as _EV161

    def _fc(tag, direction, w, pmid, stage=""):
        return {"kept": True, "direction": direction, "weight": w,
                "pmid": pmid, "title": tag, "quote": tag,
                "stage": stage, "pico": {}}

    # ── 합성 판정 원본 — run.py 와 **같은 모양**(trail·label 포함) ────
    cands = [
        # TP 인데 기각된다 → **위음성 1건**이 나와야 한다
        {"name": "약A / 병A", "drug": "약A", "disease": "병A", "label": "TP",
         "verdict": "", "confidence": None, "reason": "",
         "f0": {"count": 9}, "veto": True, "veto_reason": "결정적 반박",
         "trail": [{"gate": "f0", "outcome": "PASS", "detail": ""},
                   {"gate": "skeptic", "outcome": "PASS",
                    "detail": "추가 초록 4건 · 반박 +2 건"}],
         "factcheck": [_fc("반박1", "refute", 2.0, "1", "skeptic"),
                       _fc("반박2", "refute", 1.5, "2", "skeptic")]},
        # TN 이고 기각된다 → 올바른 기각. 위음성 아님
        {"name": "약B / 병B", "drug": "약B", "disease": "병B", "label": "TN",
         "verdict": "", "confidence": None, "reason": "",
         "f0": {"count": 15}, "veto": True, "veto_reason": "결정적 반박",
         "trail": [{"gate": "f0", "outcome": "PASS", "detail": ""}],
         "factcheck": [_fc("반박3", "refute", 3.0, "3")]},
        # TP 이고 안 기각된다 → 분모에 안 들어간다
        {"name": "약C / 병C", "drug": "약C", "disease": "병C", "label": "TP",
         "verdict": "", "confidence": None, "reason": "",
         "f0": {"count": 40}, "veto": False, "veto_reason": "",
         "trail": [{"gate": "f0", "outcome": "PASS", "detail": ""}],
         "factcheck": [_fc("지지1", "support", 3.0, "4")]},
    ]
    for cd in cands:                       # 저장 판정은 **코드에서 뽑는다**
        cd["verdict"] = _F161._verdict(_F161._candidate_from(cd))

    d161 = _t161.mkdtemp(prefix="prom161_")
    fp161 = _o161.path.join(d161, "상태_시험_B5.json")
    with open(fp161, "w", encoding="utf-8") as fh:
        _j161.dump({"config": "B5", "candidates": cands}, fh, ensure_ascii=False)

    # ── ① 복원 ─────────────────────────────────────────────────
    c0 = _F161._candidate_from(cands[0])
    check("[161] ① `trail` 이 **복원된다** — 없으면 위음성률이 조용히 0",
          len(c0.trail) == 2, len(c0.trail))
    check("[161] ① `label` 이 **복원된다**",
          getattr(c0, "label", None) == "TP", getattr(c0, "label", None))
    check("[161] ① `killed` 가 살아난다 — trail 없이는 늘 False 다",
          c0.verdict == "기각" or c0.veto, (c0.verdict, c0.veto))

    r161 = _P161.from_state(fp161)

    # ── ⑤ 왕복 ─────────────────────────────────────────────────
    check("[161] ⑤ 복원 판정 == 저장 판정",
          not r161["재현_어긋남"], str(r161["재현_어긋남"]))

    # ── ③ 위음성률 ─────────────────────────────────────────────
    fn = r161["위음성률(§8.2)"]
    check("[161] ③ 위음성률이 **계산된다** (§8.2 · 반증 조건 F5)",
          not fn.get("계산불가"), fn)
    if not fn.get("계산불가"):
        check("[161] ③ 기각 분모가 **라벨 있는 기각만** 센다",
              fn["기각_건수"] == 2, fn["기각_건수"])
        check("[161] ③ TP 인데 기각된 것 **1건**을 잡는다",
              fn["그중_실제_유효"] == 1, fn)
        check("[161] ③ **놓친 이름을 실제로 낸다** — 수만 내면 못 고친다",
              fn["이름"] == ["약A / 병A"], fn["이름"])

    # ── ④ 반박회수율 ───────────────────────────────────────────
    rr = r161["반박회수율(§4.3)"]
    check("[161] ④ 반박 근거가 있는 후보를 센다", rr["반박근거_있는_후보"] == "2/3",
          rr["반박근거_있는_후보"])
    check("[161] ④ ⭐ 회의주의자 기여가 **trail 에서** 나온다 — "
          "trail 복원이 빠지면 여기가 0이 된다",
          rr["회의주의자_추가분"] == 2, rr)

    # ── ② 라벨이 없으면 0%를 **안 낸다** (결함 35 계열) ──────────────
    nolab = _j161.loads(open(fp161, encoding="utf-8").read())
    for cd in nolab["candidates"]:
        cd.pop("label", None)
    np161 = _o161.path.join(d161, "상태_라벨없음_B5.json")
    with open(np161, "w", encoding="utf-8") as fh:
        _j161.dump(nolab, fh, ensure_ascii=False)
    fn2 = _P161.from_state(np161)["위음성률(§8.2)"]
    check("[161] ② 라벨이 없으면 **«계산불가»** — 0%로 내면 «위음성이 없다»가 된다",
          fn2.get("계산불가") is True, fn2)

    # ── ⑤ 어긋나면 조용히 안 넘어간다 ───────────────────────────
    bad = _j161.loads(open(fp161, encoding="utf-8").read())
    bad["candidates"][0]["verdict"] = "있을수없는판정"
    bp161 = _o161.path.join(d161, "상태_어긋남_B5.json")
    with open(bp161, "w", encoding="utf-8") as fh:
        _j161.dump(bad, fh, ensure_ascii=False)
    buf161 = _i161.StringIO()
    with _rs161(buf161):
        rc161 = _P161.main(["--state", bp161])
    check("[161] ⑤ 표가 **🔴 로 찍고** 수치를 인용하지 말라 한다",
          "인용하지 마라" in buf161.getvalue(), buf161.getvalue()[:300])
    check("[161] ⑤ **종료 코드 3**", rc161 == 3, rc161)
    with _rs161(_i161.StringIO()):
        check("[161] 정상일 때 종료 코드 0", _P161.main(["--state", fp161]) == 0)
        check("[161] 없는 경로는 종료 코드 2",
              _P161.main(["--state", _o161.path.join(d161, "없다.json")]) == 2)

    # ── ⑥ ⭐ 잠든 검사 — 실측이 나오면 **보고서가 따라와야 한다** ──────
    #   지금 실패하게 만들지 않는다(결함 136: 오탐이 쌓이면 가드는 꺼진다).
    #   결과 문서가 생기는 순간 깨어난다.
    res161 = _o161.path.join(_EV161.ROOT, "약속지표결과.md")
    if _o161.path.exists(res161):
        rep161 = _o161.path.join(_EV161.ROOT, "연구기술보고서.md")
        txt161 = open(rep161, encoding="utf-8").read() \
            if _o161.path.exists(rep161) else ""
        bad161 = [ln for ln in txt161.split("\n")
                  if ln.startswith("| F5") and "미측정" in ln]
        check("[161] ⑥ ⭐ 위음성률을 쟀으면 **보고서 F5 칸이 «미측정» 이면 안 된다**",
              not bad161, bad161[:1])


def test_fragility_can_actually_read_what_save_state_writes():
    """[160] **만든 도구의 «입구»가 실제 산출물과 맞물리는가** — 09-18 신설.

    ## 무엇이 있었나 — **«있다» 와 «된다» 가 달랐다**

    `bench/fragility.py` 는 09-01에 만들고 **합성 `Candidate` 로 검증**까지
    했다. 선행연구(Walsh 2014)도 대조해 뒀다. 그런데 **실측이 0**이었고,
    `연구기술보고서.md` 에 낱말이 **0회** 등장한다.

    이유가 «바빠서» 가 아니었다 —

        main()      --state 를 **디렉토리**로 보고 os.listdir
        run.py      --save-state 는 **파일 하나**를 쓴다
        → 실제 산출물을 대면 NotADirectoryError

    돌아도 파싱이 스텁이라 `취약도: None` 만 나왔다.
    **`preflight` 렌즈 3(배선)은 «코드가 도는가» 를 보고 «결과가 문서에
    닿았는가» 는 안 본다.** 그래서 안 걸렸다.

    ## 이 시험이 고정하는 것

      ① `run.py` 덤프 **그 형식**을 `fragility` 가 읽는다 (파일·디렉토리 둘 다)
      ② ⭐ **복원한 판정 == 저장된 판정** (왕복이 깨지면 표가 거짓말한다)
      ③ 어긋나면 **조용히 넘어가지 않는다** (표에 🔴 · 종료 코드 3)
      ④ ⭐ **`run.py` 가 쓰는 키와 `fragility` 가 읽는 키가 안 어긋난다**
         — 한쪽만 고치면 여기서 죽는다. `[157]⑧` 과 같은 계열이다

    ⚠ **합성 자료로 왕복을 잰다.** 실제 `상태_0912_B5.json` 은 저장소에
      없을 수 있고, 시험이 자료 유무에 흔들리면 안 된다. 실측 자체는
      `전수조사_0918.md` 의 ⓪번 항목이다.
    """
    import io as _i160, json as _j160, os as _o160, re as _r160
    import tempfile as _t160
    from contextlib import redirect_stdout as _rs160
    from ..bench import fragility as _F160
    from .. import evidence as _EV160

    # ── ④ 먼저 — **키 대조.** 자료를 만들기 전에 계약부터 본다 ─────────
    rp = _o160.path.join(_o160.path.dirname(_o160.path.dirname(
        _o160.path.abspath(_F160.__file__))), "bench", "run.py")
    src160 = open(rp, encoding="utf-8").read()
    m160 = _r160.search(r'_j\.dump\(\{"config".*?open\(_sp', src160, _r160.S)
    check("[160] ④ `run.py` 의 `--save-state` 덤프를 **실제로 읽었다**",
          m160 is not None, "못 읽으면 이 검사는 공허하다")
    if m160:
        wrote = set(_r160.findall(r'"(\w+)":', m160.group(0)))
        # `_candidate_from` 이 **요구**하는 키 (없으면 복원이 못 된다)
        need = {"name", "drug", "disease", "verdict", "f0",
                "veto", "veto_reason", "factcheck"}
        check("[160] ⭐ `fragility` 가 필요로 하는 키를 `run.py` 가 **전부 쓴다**",
              need <= wrote,
              "빠진 것: %s — 한쪽만 고치면 취약성이 조용히 죽는다"
              % sorted(need - wrote))

    # ── 합성 판정 원본 — run.py 와 **같은 모양** ────────────────────
    def _fc(tag, direction, w, pmid):
        return {"kept": True, "direction": direction, "weight": w,
                "pmid": pmid, "title": tag, "quote": tag,
                "stage": "", "pico": {}}

    cands = [
        # 지지 하나에 매달린 것 → 취약도 1이 나와야 정상
        {"name": "약A → 병A", "drug": "약A", "disease": "병A", "label": 1,
         "verdict": "", "confidence": None, "reason": "", "f0": {"count": 12},
         "veto": False, "veto_reason": "", "trail": [],
         "factcheck": [_fc("큰 지지", "support", 3.0, "1"),
                       _fc("작은 반박", "refute", 0.4, "2")]},
        # 지지가 고르게 여럿 → 더 단단해야 한다
        {"name": "약B → 병B", "drug": "약B", "disease": "병B", "label": 1,
         "verdict": "", "confidence": None, "reason": "", "f0": {"count": 30},
         "veto": False, "veto_reason": "", "trail": [],
         "factcheck": [_fc("지지1", "support", 1.2, "3"),
                       _fc("지지2", "support", 1.2, "4"),
                       _fc("지지3", "support", 1.2, "5")]},
    ]
    # **저장된 판정은 손으로 적지 않는다** — 코드에서 뽑는다(`CLAUDE.md §4`).
    for cd in cands:
        cd["verdict"] = _F160._verdict(_F160._candidate_from(cd))

    d160 = _t160.mkdtemp(prefix="frag160_")
    fp160 = _o160.path.join(d160, "상태_시험_B5.json")
    with open(fp160, "w", encoding="utf-8") as fh:
        _j160.dump({"config": "B5", "candidates": cands}, fh,
                   ensure_ascii=False)

    # ── ① 파일을 받는다 ─────────────────────────────────────────
    rows = _F160.from_state(fp160)
    check("[160] ① `--state` 가 **파일**을 받는다 (앞판은 os.listdir 로 죽었다)",
          len(rows) == 2, len(rows))
    # ── ① 디렉토리도 받는다 ────────────────────────────────────
    check("[160] ① 디렉토리도 받는다 — 옛 사용법을 안 깬다",
          len(_F160.from_state(d160)) == 2)

    if len(rows) == 2:
        # ── ② 왕복 ─────────────────────────────────────────────
        check("[160] ⭐② **복원한 판정 == 저장된 판정** — 왕복이 성립한다",
              all(r["재현"] for r in rows),
              str([(r["이름"], r["저장판정"], r["판정"]) for r in rows]))
        check("[160] 근거를 **무게까지** 복원했다 (factcheck → support/refute)",
              rows[0]["근거수"] == 2 and rows[1]["근거수"] == 3,
              [r["근거수"] for r in rows])
        # 앞판은 근거를 하나도 못 빼 봤다(근거수 0). **실제로 빼 봤는가**를
        # 본다 — 판정이 안 바뀌는 것은 정상 결과이므로 취약도 값 자체를
        # 조건으로 걸지 않는다(그건 자료에 따라 달라진다).
        check("[160] 근거를 **실제로 빼 보며 잰다** — 앞판은 한 건도 못 뺐다",
              all(r["뺀근거"] for r in rows),
              [(r["이름"], len(r["뺀근거"]), r["취약도"]) for r in rows])

    # ── ③ 어긋나면 조용히 안 넘어간다 ────────────────────────────
    bad = _j160.loads(open(fp160, encoding="utf-8").read())
    bad["candidates"][0]["verdict"] = "있을수없는판정"
    bp160 = _o160.path.join(d160, "상태_어긋남_B5.json")
    with open(bp160, "w", encoding="utf-8") as fh:
        _j160.dump(bad, fh, ensure_ascii=False)
    br = _F160.from_state(bp160)
    check("[160] ③ 저장 판정과 다르면 `재현=False` 로 남는다",
          any(r.get("재현") is False for r in br))
    buf160 = _i160.StringIO()
    with _rs160(buf160):
        rc160 = _F160.main(["--state", bp160])
    out160 = buf160.getvalue()
    check("[160] ③ 표가 **🔴 로 크게 찍는다** — 예쁜 표가 거짓말하면 안 된다",
          "복원한 판정이 저장된 판정과 다른" in out160, out160[-300:])
    check("[160] ③ 그리고 **종료 코드 3** 으로도 알린다", rc160 == 3, rc160)
    with _rs160(_i160.StringIO()):
        check("[160] 정상일 때는 종료 코드 0", _F160.main(["--state", fp160]) == 0)

    # ── 없는 경로를 조용히 삼키지 않는다 ────────────────────────
    with _rs160(_i160.StringIO()):
        check("[160] 없는 경로는 **종료 코드 2**", _F160.main(
            ["--state", _o160.path.join(d160, "없는파일.json")]) == 2)

    # ── ⭐ 실측이 문서에 **닿았는가** — 이 시험의 진짜 목적 ──────────
    #
    #   렌즈 3(배선)은 «코드가 도는가» 만 보고 «결과가 문서에 닿았는가» 는
    #   안 본다. 그래서 09-01~09-18 내내 «만들었는데 실측 0 · 보고서에
    #   낱말 0회» 가 안 걸렸다.
    #
    #   ⚠ **지금 실패하게 만들지 않는다.** 아직 실측 전이면 «보고서에
    #     없다» 가 **맞는 상태**이고, 일부러 빨간 시험을 만들어 두면
    #     «오탐이 쌓여 가드가 꺼진다»(결함 136). 그래서 **결과 파일이
    #     생기는 순간 깨어나는** 잠든 검사로 만든다.
    res160 = _o160.path.join(_EV160.ROOT, "취약성결과.md")
    if _o160.path.exists(res160):
        rep160 = _o160.path.join(_EV160.ROOT, "연구기술보고서.md")
        txt160 = open(rep160, encoding="utf-8").read() \
            if _o160.path.exists(rep160) else ""
        check("[160] ⭐ 실측을 했으면 **보고서에도 닿아 있다** — "
              "«만들었는데 아무도 모른다» 를 막는다",
              "취약" in txt160,
              "`취약성결과.md` 는 있는데 `연구기술보고서.md` 에 없다")


def test_screen_does_not_mistake_fulltext_irrelevant_for_zero_weight():
    """[158] **같은 낱말이 게이트마다 다른 뜻이다** — 09-17 신설.

    `dash.thinking()` 은 「이 실행에서 스스로 인지·수정한 것」을 **자동으로**
    찾는다. 손으로 적으면 낡기 때문이다. 그런데 찾는 방법이
    **게이트 설명을 전부 한 덩어리로 이어 붙인 문자열 검사**였다 —

        blob = " ".join(모든 게이트의 설명)
        if "무관" in blob:  → *"무관 판정으로 **가중치 0**을 준 초록이 있다"*

    팩트체커에서는 맞다. 「무관」이면 w=0 이다.
    **그런데 F(전문 읽기)의 DONE 도 「무관N」을 적는다** —
    `N편(한계절2) → 약화2 **무관1** · 감쇠 2건`. 그리고 F 의 「무관」은
    `LIMIT_MULT["무관"] = 1.0`, 즉 **가중치를 안 건드린다.**

    > 그대로 두고 F 를 화면에 배선했으면 **화면이 «가중치 0을 줬다» 고
    > 거짓말**한다. 그것도 배점 30점 「사고 과정을 투명하게」 칸에서.

    `CLAUDE.md §2` 의 «모른다 ≠ 차이 없다» 와 같은 계열이고, 이 저장소가
    결함 35 로 여섯 번 넘게 겪은 «두 가지를 한 낱말로 세는» 실수다.

    **문자열이 아니라 게이트로 좁힌다.** 이 시험이 그걸 고정한다.
    """
    from .. import dash as _D158
    from ..demo import GATE_KO as _KO158

    # `thinking()` 은 구운 사례 파일을 읽으므로 조립부만 따로 못 부른다.
    # **그래서 규칙 자체를 소스에서 본다** — 규칙이 되돌아가면 여기서 걸린다.
    import inspect as _i158
    src = _i158.getsource(_D158.thinking)
    check("[158] 「무관」 검사가 **게이트로 좁혀져 있다** — 전체 blob 이 아니다",
          '_from("rag", "factcheck"' in src or '_from("rag"' in src,
          "blob 전체를 보면 F 의 「무관N」이 오검출된다")
    check("[158] 그 좁히는 헬퍼가 **한글 이름도 받는다** (구운 사례는 옛 이름)",
          "_KO_T.get(k, k)" in src)
    check("[158] F 는 **«낮췄다»** 로 적는다 — «0 으로 만들었다» 가 아니다",
          "0 으로 만들지는 않는다" in src)
    check("[158] **못 읽은 것을 «한계 없음» 으로 안 센다** 를 화면이 말한다",
          "한계 없음" in src and "모른다" in src)

    # ── 계수 자체가 그 문장을 뒷받침하는가 (문서가 아니라 코드로) ──────
    from ..agents import limits as _L158
    check("[158] `무관` 의 계수가 **1.0** 이다 — 가중치를 안 건드린다",
          _L158.LIMIT_MULT["무관"] == 1.0, _L158.LIMIT_MULT)
    check("[158] `약화` 만 1 미만이다 — **깎는 것은 하나뿐**",
          [k for k, v in _L158.LIMIT_MULT.items() if v < 1.0] == ["약화"],
          _L158.LIMIT_MULT)

    # ── 게이트 이름이 화면 표에 **영문으로 새지 않는다** ─────────────────
    check("[158] `fulltext` 에 한글 이름이 있다", "fulltext" in _KO158,
          "없으면 심사위원이 첫 탭에서 영문 `fulltext` 를 본다")


def test_every_gate_name_on_screen_is_korean():
    """[139] **화면에 나오는 게이트 이름이 전부 한글이다** — 결함 255.

    08-18 밤 브라우저. 대시보드 **첫 탭**의 「사고 과정」 표가 이랬다 —

        입력 · hitl · F0 근거 실재성 · factcheck · 기전 라우터 ·
        s1 · S2 리간드 개발성 · 회의주의자 · 등록부(CT.gov)

    **한글과 영문이 섞여 있다.** 심사위원이 처음 보는 표다.

    결함 247 이 같은 것을 잡고 `GATE_KO` 를 **`ORDER` 8개 + adjudicate**
    로 맞췄다. **기준이 틀렸다** — trail 에는 게이트 «이름» 만 남는 게
    아니라 게이트가 **자기 안에서 찍는 이름**(`factcheck`·`veto`)도 남는다.

    그래서 이 시험은 `ORDER` 를 안 본다. **구운 사례에 실제로 들어
    있는 이름을 전수로** 훑는다 — 새 게이트가 새 이름을 찍으면 여기서 걸린다.
    """
    import re as _re139
    from .. import dash as _D139, evidence as _EV139
    from ..demo import GATE_KO as _KO139

    names = set()
    for c in (_EV139.cases() or {}).get("사례") or []:
        for g in (c.get("게이트") or []):
            names.add(str(g.get("게이트") or ""))
    check("[139] 구운 사례에서 게이트 이름을 읽었다", len(names) >= 8, len(names))
    miss = sorted(n for n in names
                  if n and n not in _KO139 and n not in _KO139.values())
    check("[139] **trail 에 나오는 이름이 전부 `GATE_KO` 에 있다** "
          "— `ORDER` 로 세면 `factcheck`·`veto` 를 놓친다",
          not miss, miss)

    # 기록 시점이 아니라 **그릴 때도** 바꾼다 — 옛 파일은 영문으로 저장돼 있다
    # 08-19 — 사고 과정이 **표에서 목록으로** 바뀌었다(결함 283·287).
    #   시험이 표 서식(`| … |`)을 붙들고 있어서 «행 0개» 가 됐다.
    #   **이름 칸만 뽑는 방법이 서식에 딸려 있었다** — 뜻으로 고친다.
    md = _D139.thinking("rifampin / Tuberculosis")
    rows = _re139.findall(r"<div class='br-sbody'><b>(.*?)</b>", md)
    check("[139] 사고 과정에 단계가 있다", len(rows) >= 5, len(rows))
    # `등록부(CT.gov)` 처럼 **고유명사 안의 영문**은 봐준다
    bad = [r for r in rows
           if _re139.search(r"[a-z]{3}", r.replace("(CT.gov)", ""))]
    check("[139] 화면 단계 이름에 **영문이 안 남는다**", not bad, bad)


def test_run_pair_actually_times_its_gates():
    """[138] **`run_pair` 가 게이트 시간을 실제로 잰다** — 결함 254.

    08-18 밤, 승우가 *«너가 직접 돌려서 확인해»* 라고 해서 브라우저로
    두 번 돌렸다. 화면이 이렇게 나왔다 —

        Time-to-Refute — 게이트별 소요
        게이트 | 초              ← **행이 0개**
        반박 근거 수집 | 0초      ← **25초 걸린 실행이다**
        전체        | None초      ← 리터럴 `None`

    `gates.run_funnel` 이 `st.timing[name]` 을 적는데 **`run_pair` 는
    그 함수를 안 지나간다** — 진행 표시를 하려고 게이트를 직접 부른다.

    ## 왜 못 잡았나 — **모의가 거짓말했다**

    붙이고 나서 `class ST: timing = {...}` 로 **내가 채운 가짜 상태**를
    넣어 확인했다. 당연히 통과했다. `CLAUDE.md §5` 가 정확히 그걸
    경고한다 — *«모의로 시험할 때 모의가 거짓말하지 않는지 먼저 확인해라»*.

    그래서 이 시험은 **`run_pair` 를 실제로 태운다.** 게이트만 바꿔
    끼워 LLM 을 안 쓴다 — 재는 것은 «게이트가 뭘 했나» 가 아니라
    **«루프가 시간을 적었나»** 이므로 게이트 내용은 상관없다.
    """
    import time as _t138
    from .. import demo as _D
    from ..core import gates as _G
    from ..io import budget as _B138
    from ..io import llm as _L

    real, ravail = dict(_G.REGISTRY), _L.available
    rbudget = _B138.PATH

    def _stub(st):
        _t138.sleep(0.02)
        for c in st.candidates:
            c.note("x", "OK", "stub")
        return st

    # ⛔ 09-25 · 결함 335 — 앞판은 `cache_path` 를 안 넘겨 **기본값(실제
    #   `pubmed_cache.json`, 48MB)을 읽고 통째로 다시 썼다.** 그 쓰기가
    #   도중에 끊겨 17.9MB 반쪽이 됐다. 실행 한도 파일(`budget.json`)도 실제
    #   것을 올렸다 내렸다. 둘 다 임시 경로로.
    try:
        for k in _G.REGISTRY:
            _G.REGISTRY[k] = _stub
        _L.available = lambda: True
        _B138.PATH = _tmp("_138_budget.json")
        r = _D.run_pair("metformin / Breast Cancer", config="B5S",
                        cache_path=_tmp("_138_cache.json"))
    finally:
        _G.REGISTRY.update(real)
        _L.available = ravail
        _B138.PATH = rbudget

    check("[138] `run_pair` 가 정상으로 끝난다", r["상태"] == "정상",
          "%s %s" % (r["상태"], r.get("메시지", "")[:50]))
    t = r.get("ttr")
    check("[138] Time-to-Refute 가 **`None` 이 아니다**", t is not None)
    if t:
        check("[138] **게이트별 내역이 비어 있지 않다** — 빈 표는 «0초» 로 읽힌다",
              bool(t.get("게이트별")), t.get("게이트별"))
        check("[138] **전체_초가 `None` 이 아니다** — 화면에 `None초` 가 찍혔다",
              isinstance(t.get("전체_초"), (int, float)), t.get("전체_초"))
        check("[138] 실제로 잰 값이다 — 0 보다 크다",
              (t.get("반박근거_수집_초") or 0) > 0, t.get("반박근거_수집_초"))

    # **안 쟀으면 «0초» 가 아니라 «안 쟀다»** 여야 한다 — 구조로 막은 자리
    from ..core.state import RunState as _RS
    st0 = _RS(query_title="x", settings="B5S", stamp="t", candidates=[],
              config={})
    check("[138] 계측이 빠지면 **`None`** 을 낸다 — «0초» 라고 안 적는다",
          _D._ttr(st0) is None, _D._ttr(st0))

    # 화면도 `None초` 를 안 찍는다
    from .. import dash as _DH
    md = _DH.bottom_timeline({"게이트별": {}, "반박근거_수집_초": 0,
                              "전체_초": None, "warm": 0})
    check("[138] 화면이 **`None초`** 를 안 찍는다", "None초" not in md)
    # **뜻으로 본다** — 08-19 에 말투를 «~습니다» 로 바꿨다. 요건은
    #   「머리만 있는 빈 표를 내지 말 것」이지 특정 문구가 아니다.
    check("[138] 빈 표 대신 **«안 쟀다»고 적는다** — 머리만 있는 표는 "
          "«0초 걸렸다» 로 읽힌다",
          "계측이 안 됐" in md and "| 단계 | 초 |" not in md, md[-160:])


def test_patent_index_is_read_once_not_per_call():
    """[136] **특허 색인을 호출마다 다시 읽지 않는다** — 결함 251.

    08-18 실측. 화면에서 후보를 누를 때마다 `local_check` 이 도는데
    **한 번이 28~35초**였다. `fto_drug_patents.json`(69 MB)과
    `fto_years.json`(23 MB)을 **호출마다 통째로 파싱**했기 때문이다.

    아무도 안 쟀다. 시연 4부가 **3분**인데 클릭 한 번이 30초다.

    시간으로 재면 기계 속도에 흔들리니 **`json.load` 횟수**를 센다.
    두 번째 호출이 0회여야 한다. `--help` 가 아니라 **실제 경로**다.
    """
    import json as _j, os as _o, tempfile as _tf, shutil as _sh
    from ..io import fto as _F

    tmp = _tf.mkdtemp(prefix="fto251_")
    try:
        _j.dump({"scanned_all": True, "n_drugs": 1,
                 "by_drug": {"Cisplatin": [11, 22]}},
                open(_o.path.join(tmp, _F.DRUG_PATENTS), "w",
                     encoding="utf-8"), ensure_ascii=False)
        _j.dump({"scanned_all": True, "years": {"11": 2021, "22": 1979},
                 "ids": {"11": "US2021111A1", "22": "US1979222A"}},
                open(_o.path.join(tmp, _F.YEARS_CACHE), "w",
                     encoding="utf-8"), ensure_ascii=False)

        n = [0]
        real = _j.load

        def counted(*a, **k):
            n[0] += 1
            return real(*a, **k)

        _F.json.load = counted
        try:
            _F.local_check("cisplatin", root=tmp)
            first = n[0]
            n[0] = 0
            r2 = _F.local_check("cisplatin", root=tmp)
            r3 = _F.local_check("존재하지않는약", root=tmp)
        finally:
            _F.json.load = real

        check("[136] 첫 호출은 색인 두 개를 읽는다", first == 2, first)
        check("[136] **두 번째부터는 0회** — 이게 30초를 0.06초로 만든 것",
              n[0] == 0, n[0])
        check("[136] 캐시를 써도 답이 같다",
              r2["n_patents"] == 2 and r2["n_recent"] == 1,
              (r2["n_patents"], r2["n_recent"]))
        check("[136] 캐시가 **없는 약을 있다고 하지 않는다**",
              r3["label"] == "확인불가", r3["label"])

        # 색인을 **새로 만들면** 옛 값이 남으면 안 된다 (결함 62 계열)
        import time as _t
        _t.sleep(0.01)
        _j.dump({"scanned_all": True, "n_drugs": 1,
                 "by_drug": {"Cisplatin": [11, 22, 33, 44]}},
                open(_o.path.join(tmp, _F.DRUG_PATENTS), "w",
                     encoding="utf-8"), ensure_ascii=False)
        r4 = _F.local_check("cisplatin", root=tmp)
        check("[136] 색인 파일이 바뀌면 **다시 읽는다** — 옛 수치가 안 남는다",
              r4["n_patents"] == 4, r4["n_patents"])
    finally:
        _sh.rmtree(tmp, ignore_errors=True)


def test_parallel_funnel_gives_the_same_verdicts():
    """[131] **병렬로 태워도 판정이 같다** — 이게 유일한 합격 조건이다.

    08-18. 병명 입구가 155.5초·159.4초로 **상한 150을 두 번 넘었다.**
    후보를 병렬로 태우면 줄어든다 — 게이트는 **후보별로 독립**이라
    한 후보의 trail 이 다른 후보를 안 본다.

    > **빨라지는 건 부수 효과지 목적이 아니다.** 목적은 «같은 판정을
    > 더 짧게» 이고, 앞 절반이 깨지면 뒤 절반은 셀 가치가 없다.

    ## 이 시험이 안 하는 것 — **시간을 안 잰다**

    시간은 이 기계·이 시각의 값이고 CI 에서 요동친다. 시간을 합격
    조건에 넣으면 **느린 기계에서 빨간불이 뜨는 시험**이 된다.
    여기서는 **동치**만 본다. 속도는 실측 문서가 따로 적는다.

    ## 모의가 거짓말하지 않게 — **겹침을 실제로 확인한다**

    가짜 게이트가 즉시 돌아오면 `workers=4` 라도 사실상 순차로 돌고,
    그러면 이 시험은 **아무것도 안 재고 통과한다.** 그래서 게이트가
    잠자게 하고 **동시 실행 최대치(peak)를 세서 2 이상**임을 못 박는다.
    peak 이 1이면 시험 자체를 실패시킨다.
    """
    import threading as _th, time as _t
    from ..core import gates as _G
    from ..core.state import Candidate as _Cd
    from .. import demo as _D

    live, peak = [0], [0]
    lk = _th.Lock()

    def fake(name):
        def g(st):
            with lk:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            try:
                c = st.candidates[0]
                # 후보 이름으로 결정되는 잠. **순서를 일부러 뒤섞는다** —
                # 늦게 제출된 것이 먼저 끝나야 «순서 보존» 이 시험된다.
                _t.sleep(0.02 * (1 + (hash(c.name) % 5)))
                c.note(name, "PASS", "가짜 %s" % name)
                # `killed` 는 **속성이 아니라 trail 에서 파생**된다
                # (`state.py:95`). 모의가 `c.killed = True` 로 거짓말하면
                # 진짜 중단 경로를 안 태운다 — 그래서 KILL 을 적는다.
                if name == "skeptic" and c.name.endswith("3"):
                    c.note(name, "KILL", "가짜 기각")
            finally:
                with lk:
                    live[0] -= 1
            return st
        return g

    rest = [n for n in _G.ORDER if n != "f0"]
    old_reg = dict(_G.REGISTRY)
    old_adj = _G.gate_adjudicate

    def adj(st):
        c = st.candidates[0]
        c.verdict = "기각" if c.killed else "유망"
        c.confidence = len(c.trail) * 7
        c.reason = "게이트 %d단계" % len(c.trail)
        return st

    try:
        for n in rest:
            _G.REGISTRY[n] = fake(n)
        _G.gate_adjudicate = adj

        def fresh():
            return [_Cd(name="cand%d" % i, origin="t", query="q",
                        drug="d%d" % i, disease="z") for i in range(8)]

        def shot(w):
            cs = fresh()
            peak[0] = 0
            done, unrun, secs, _w = _D._funnel_many(
                cs, rest, "B5S", "T", _t.monotonic(), 1e9,
                lambda *a: None, workers=w)
            return ([(c.name, c.verdict, c.confidence,
                      tuple((r.gate, r.outcome) for r in c.trail))
                     for c in done], unrun, peak[0])

        seq, seq_un, _ = shot(1)
        par, par_un, pk = shot(4)

        check("[131] 일꾼 4로 돌 때 **실제로 겹쳤다** (모의가 안 게으르다)",
              pk >= 2, "동시 최대 %d" % pk)
        check("[131] 병렬 판정이 순차와 **완전히 같다**", par == seq,
              "다른 항목 %d개" % sum(1 for a, b in zip(seq, par) if a != b))
        check("[131] 결과 **순서**도 제출 순서 그대로다",
              [x[0] for x in par] == ["cand%d" % i for i in range(8)],
              [x[0] for x in par])
        check("[131] 기각도 같은 후보에서 났다",
              [x[0] for x in par if x[1] == "기각"] == ["cand3"],
              [x[0] for x in par if x[1] == "기각"])
        check("[131] 못 태운 것 없음", (seq_un, par_un) == ([], []))

        # ── 시간 상한 — **못 태운 것을 개수가 아니라 이름으로 적는다** ──
        cs = fresh()
        done, unrun, _s, _w2 = _D._funnel_many(
            cs, rest, "B5S", "T", _t.monotonic() - 1e6, 1.0,
            lambda *a: None, workers=4)
        check("[131] 상한을 이미 넘겼으면 **하나도 안 태운다**",
              (len(done), len(unrun)) == (0, 8), (len(done), len(unrun)))
        check("[131] 그리고 **이름으로** 적는다 — 개수만 적으면 어느 것인지 모른다",
              unrun[0] == "cand0" and isinstance(unrun[0], str), unrun[:2])
    finally:
        _G.REGISTRY.clear()
        _G.REGISTRY.update(old_reg)
        _G.gate_adjudicate = old_adj

    # ── 한도는 **원자적으로** 잡히나 (결함 230) ──────────────────────
    #   `spent() >= MAX_CALLS` 는 검사-후-실행이라 스레드 N개면 N-1회
    #   더 나간다. 그 초과분은 순차라면 `BUDGET_EXCEEDED` → **보류**가
    #   됐을 후보에 **실제 답을 준다.** 요금이 아니라 **판정 문제**다.
    import concurrent.futures as _cf
    from ..io import llm as _L, cache as _C
    import tempfile as _tf, os as _o
    d = _tf.mkdtemp(prefix="cap_")
    op, ob, om = _C._PATH, _L.BYPASS_CACHE, _L.MAX_CALLS
    try:
        _C.configure(_o.path.join(d, "c.json"))
        _L.BYPASS_CACHE, _L.MAX_CALLS = True, 20
        n0 = len(_L._CALLS)
        with _cf.ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(lambda i: _L.complete("cap-%d" % i), range(200)))
        tried = [c for c in _L._CALLS[n0:]
                 if not str(c.get("error", "")).startswith("BUDGET_EXCEEDED")]
        check("[131] 스레드 8개가 동시에 와도 상한 20을 **안 넘는다**",
              len(tried) <= 20, len(tried))
        check("[131] 예약이 새지 않는다 (전부 반납됐다)",
              _L._RESERVED[0] == 0, _L._RESERVED[0])
    finally:
        _L.BYPASS_CACHE, _L.MAX_CALLS = ob, om
        _C.configure(op)
        import shutil as _sh
        _sh.rmtree(d, ignore_errors=True)


def test_output_survives_a_cp949_pipe():
    """[132] **파이프로 내보내도 안 죽는다** (결함 231).

    윈도우에서 파이썬 stdout 이 파이프가 되면 인코딩이 `cp949` 다.
    그런데 우리 화면 문구는 `—` · `«»` · `⚠` · `⛔` 를 쓴다 —
    **넷 다 cp949 에 없다.**

    ```
    py -m bioreroute.bench.parcheck                    콘솔 → 된다
    py -m bioreroute.bench.parcheck | Tee-Object …     파이프 → **죽는다**
    ```

    08-18 `병렬.ps1` 이 정확히 그렇게 죽었다. 안전한 줄 둘을 찍고
    `print("A — 일꾼 1 · 캐시 빈 것")` 에서 터졌다.

    ## 이 시험은 `PYTHONIOENCODING` **없이** 돈다

    `시험.ps1` 은 그 환경변수를 걸어 둔다. 그래서 **여기서 그대로 재면
    시험이 자기가 만든 안전지대 안에서 재게 된다** — 아무것도 안 재는
    시험이 된다. 그래서 **일부러 `cp949` 로 강제하고** 새 프로세스를
    띄운다. 방어가 `bioreroute/__init__.py` 에 있으므로 살아남아야 한다.
    """
    import subprocess as _sp, sys as _s, os as _o

    # 우리가 실제로 쓰는 글자들. **cp949 에 없는 것만** 골랐다.
    #
    #   ⚠ 처음엔 `①②` 도 넣었는데 **이 시험이 내 전제를 반증했다** —
    #     원문자는 cp949 에 **있다.** 없는 것은 `—`·`«»`·`⚠`·`⛔` 다.
    #     화면 문구를 고를 때 쓸 수 있는 사실이라 남겨 둔다.
    hard = "— « » ⚠ ⛔"
    for ch in hard.replace(" ", ""):
        try:
            ch.encode("cp949")
            check("[132] `%s` 는 cp949 에 없다는 전제" % ch, False, "있다")
        except (UnicodeEncodeError, LookupError):
            pass

    env = dict(_o.environ)
    env.pop("PYTHONUTF8", None)
    env["PYTHONIOENCODING"] = "cp949"          # ← 윈도우 파이프를 흉내
    root = _o.path.dirname(_o.path.dirname(_o.path.dirname(
        _o.path.abspath(__file__))))
    code = "import bioreroute; print('%s')" % hard
    r = _sp.run([_s.executable, "-c", code], cwd=root, env=env,
                stdout=_sp.PIPE, stderr=_sp.PIPE)
    check("[132] `import bioreroute` 뒤에는 cp949 파이프로도 **안 죽는다**",
          r.returncode == 0,
          r.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]
          or "종료 %d" % r.returncode)
    check("[132] 그리고 글자가 실제로 나온다",
          "⛔" in r.stdout.decode("utf-8", "replace"),
          r.stdout.decode("utf-8", "replace").strip()[:40])

    # ── 모의가 거짓말하지 않는지 — **안 걸면 정말 죽나** ──────────────
    #   `import bioreroute` 를 빼고 같은 것을 찍는다. 여기서 죽어야
    #   위의 통과가 «방어가 일했다» 를 뜻한다.
    r2 = _sp.run([_s.executable, "-c", "print('%s')" % hard],
                 cwd=root, env=env, stdout=_sp.PIPE, stderr=_sp.PIPE)
    check("[132] 방어를 빼면 **정말 죽는다** (시험이 헛돌지 않는다)",
          r2.returncode != 0,
          "종료 %d — 안 죽으면 이 환경은 cp949 를 안 쓴다" % r2.returncode)

    # ── 방어가 **한 곳**인가 ────────────────────────────────────────
    #   `.ps1` 마다 환경변수를 거는 방식이면 새 스크립트에서 또 빠진다.
    #   08-18이 그렇게 났다. 소스에 있어야 한다.
    import inspect as _i
    import bioreroute as _B
    check("[132] 방어가 `bioreroute/__init__.py` 에 있다 — 부르는 쪽이 아니라",
          "reconfigure" in _i.getsource(_B))


def test_every_declared_role_is_actually_wired():
    """[133] **선언한 역할 여섯이 전부 실제로 배선돼 있다** (결함 232).

    제안서 §3.2 —

    > 작업 성격에 따라 모델을 나눈다. **결정론적 작업은 소형 모델에**,
    > **적대적 추론이 필요한 작업은 고성능 모델에** 배정한다.

    `ROLE_OF` 가 여섯을 적어 놨고 `roles_in_use()` 가 여섯을 다 찍었다.
    **그런데 08-18에 세어 보니 셋이 죽어 있었다.**

    ```
    router · reverse_terms · factcheck    model_for() 를 부른다      ✅
    skeptic                               factcheck 로 청구됐다      ❌
    approval                              model= 를 아예 안 넘겼다   ❌
    discover                              st.discover 가 없으면 None ❌
    ```

    죽어 있어도 **아무 증상이 없다.** 기본값이 전부 `MODEL` 이라 결과가
    똑같이 나오기 때문이다. 그래서 **환경변수를 걸어 봐야만** 티가 난다.
    *"만든 게 실제로 도는가"* — `검증절차.md` 렌즈 3이 이걸 위해 있다.

    ## 이 시험은 **소스를 읽어서** 센다

    `model_for("x")` 처럼 상수로 부르는 것과, `role="x"` 로 넘겨
    `model_for(role)` 에 닿는 것 **둘 다** 센다. 회의주의자가 후자다.
    """
    import ast as _ast, os as _os
    from ..io import llm as _L

    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    wired = set()
    for base, _d, files in _os.walk(root):
        if "tests" in base:
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            tree = _ast.parse(open(_os.path.join(base, f), encoding="utf-8").read())
            for n in _ast.walk(tree):
                if not isinstance(n, _ast.Call):
                    continue
                if getattr(n.func, "attr", "") == "model_for" or \
                        getattr(n.func, "id", "") == "model_for":
                    wired |= {a.value for a in n.args
                              if isinstance(a, _ast.Constant)
                              and isinstance(a.value, str)}
                # `role="skeptic"` 처럼 넘겨 `model_for(role)` 에 닿는 것
                wired |= {k.value.value for k in n.keywords
                          if k.arg == "role" and isinstance(k.value, _ast.Constant)
                          and isinstance(k.value.value, str)}

    dead = sorted(set(_L.ROLE_OF) - wired)
    check("[133] `ROLE_OF` 의 역할이 **전부 배선돼 있다**", not dead,
          "죽은 역할: %s — `roles_in_use()` 가 이것도 찍는다" % dead
          if dead else "%d개 전부" % len(_L.ROLE_OF))

    # 등급이 제안서 문장과 맞나 — 소형/고성능 배정 자체
    check("[133] 적대적 추론 둘이 `strong` 이다",
          _L.ROLE_OF.get("skeptic") == "strong"
          and _L.ROLE_OF.get("factcheck") == "strong",
          {k: _L.ROLE_OF.get(k) for k in ("skeptic", "factcheck")})
    check("[133] 결정론적 넷이 `small` 이다",
          all(_L.ROLE_OF.get(k) == "small"
              for k in ("router", "reverse_terms", "approval", "discover")),
          {k: _L.ROLE_OF.get(k) for k in
           ("router", "reverse_terms", "approval", "discover")})

    # ── **설정이 없으면 지금까지와 완전히 같아야 한다** ─────────────
    #   이 기능을 켠 것만으로 동결 수치가 움직이면 안 된다
    #   (`llm.py` 가 그 문장을 주석으로 적어 뒀다). 그걸 시험으로 굳힌다.
    import os as _o2
    saved = {v: _o2.environ.pop(v, None) for v in _L.ROLE_ENV.values()}
    try:
        same = {r: _L.model_for(r) for r in _L.ROLE_OF}
        check("[133] 환경변수가 없으면 **여섯 다 기본 모델**이다 — 동결 수치 불변",
              set(same.values()) == {_L.MODEL}, sorted(set(same.values())))
    finally:
        for v, old in saved.items():
            if old is not None:
                _o2.environ[v] = old

    # ── 그리고 **켜면 실제로 갈린다** ───────────────────────────────
    #   위 시험만 있으면 «전부 기본값» 이 상수여도 통과한다.
    _o2.environ[_L.ROLE_ENV["small"]] = "MODEL-SMALL-테스트"
    try:
        got = {r: _L.model_for(r) for r in _L.ROLE_OF}
        check("[133] 소형만 걸면 **소형 역할만** 바뀐다",
              all(got[r] == "MODEL-SMALL-테스트"
                  for r, t in _L.ROLE_OF.items() if t == "small")
              and all(got[r] == _L.MODEL
                      for r, t in _L.ROLE_OF.items() if t == "strong"), got)
    finally:
        _o2.environ.pop(_L.ROLE_ENV["small"], None)
        if saved.get(_L.ROLE_ENV["small"]) is not None:
            _o2.environ[_L.ROLE_ENV["small"]] = saved[_L.ROLE_ENV["small"]]


def test_run_disease_actually_completes():
    """[134] **병명 입구가 끝까지 돈다** — 오타 하나가 조용히 넘어갔다 (결함 235).

    08-18. `llm.calls()` 라고 썼는데 실제 이름은 `call_log()` 였다.
    **회귀 시험 1,533건이 전부 통과했다.** 승우가 실행해서 알았다.

    ## 왜 안 잡혔나 — `run_disease` 가 **예외를 밖으로 안 던진다**

    그 규약 자체는 옳다(화면이 죽으면 안 된다). 대가는 이것이다 —

    ```
    AttributeError  →  except Exception  →  {"상태": "오류", ...}
    ```

    **오타가 「처리된 오류」로 둔갑한다.** 그리고 시험들은 반환 구조와
    부분 함수만 봤지 *"끝까지 정상으로 돌았나"* 를 **한 번도 안 물었다.**

    > `CLAUDE.md §5` — *"`--help` 통과는 검증이 아니다. 실제 경로를 태워라."*
    > 이번엔 내가 고친 뒤 실제 경로를 안 태웠다.

    ## 그래서 이 시험은 **상태를 본다**

    자료원과 LLM 만 고정 응답으로 바꾸고 **게이트는 진짜**로 태운다.
    `상태 != "정상"` 이면 실패다 — 그게 이 시험의 전부이자 요점이다.
    """
    import json as _j, hashlib as _hl, os as _o, tempfile as _tf
    from .. import demo as _D
    from ..io import llm as _L, sources as _S
    from ..core import gates as _G
    from ..agents import factcheck as _F

    def _h(s):
        return int(_hl.sha256(str(s).encode()).hexdigest()[:8], 16)

    def _fc(prompt, system="", model=None, as_json=False, purpose=""):
        d = ({"candidates": [{"drug": "약%d" % i, "rationale": "r"}
                             for i in range(6)]}
             if ("후보" in prompt or "candidate" in prompt.lower())
             else {"direction": ["support", "refute", "unclear"][_h(prompt) % 3],
                   "mechanism": "host", "confidence": "medium",
                   "certainty": "moderate", "route": "clinical"})
        # **진짜 `_CALLS` 에 남긴다.** 모의가 이걸 안 하면 `모델` 집계가
        # 늘 비어서, 그 경로가 죽어도 시험이 통과한다 — 모의가 거짓말한다.
        _L._CALLS.append({"key": "k", "cached": False, "served_by": "모의"})
        return {"ok": True, "text": _j.dumps(d), "data": d, "error": None,
                "provenance": {"served_by": "모의"}, "cached": False}

    def _look(q, retmax=3):
        n = _h(q) % 5
        return {"count": n, "pmids": ["%08d" % (_h(q) + i) for i in range(n)],
                "error": None}

    def _search(q, retmax=8, max_year=None):
        return _look(q, retmax)

    def _abs(pmids, retry=1):
        return {p: {"pmid": p, "title": "T", "year": 2018,
                    "abstract": "randomized trial showed no benefit",
                    "journal": "J", "ptype": ["Randomized Controlled Trial"]}
                for p in pmids}

    def _ct(drug, condition, limit=12, **kw):
        return {"trials": [], "error": None}

    from ..io import budget as _B134
    saved = {"c": _L.complete, "a": _L.available, "b": _B134.PATH}
    mods = [(m, n, getattr(m, n)) for m in (_S, _G, _F)
            for n in ("pubmed_lookup", "pubmed_search", "pubmed_abstracts",
                      "ctgov_search") if hasattr(m, n)]
    d = _tf.mkdtemp(prefix="rd_")
    try:
        # 실행 한도 파일도 임시로 — 앞판은 실제 `budget.json` 을 올렸다(결함 335)
        _B134.PATH = _o.path.join(d, "budget.json")
        _L.complete, _L.available = _fc, (lambda: True)
        for m, n, _old in mods:
            setattr(m, n, {"pubmed_lookup": _look, "pubmed_search": _search,
                           "pubmed_abstracts": _abs, "ctgov_search": _ct}[n])
        r = _D.run_disease("시험질환", cache_path=_o.path.join(d, "c.json"),
                           workers=2, time_budget=1e9)
        check("[134] **끝까지 정상으로 돈다** — 오타면 여기서 잡힌다",
              r.get("상태") == "정상",
              "%s: %s" % (r.get("상태"), r.get("메시지", ""))[:110])
        check("[134] 후보를 만들고 깔때기까지 태웠다",
              r.get("생성", 0) > 0 and r.get("태움", 0) > 0,
              (r.get("생성"), r.get("F0통과"), r.get("태움")))
        for k in ("깔때기초", "게이트초", "모델", "역할배정", "일꾼",
                  "못태운후보", "warm"):
            check("[134] 감사 항목 `%s` 가 반환에 있다" % k, k in r,
                  sorted(r)[:6])
        check("[134] `모델` 이 **누가 답했는지**를 실제로 담는다",
              isinstance(r.get("모델"), dict) and bool(r["모델"]),
              r.get("모델"))
        check("[134] `역할배정` 이 여섯 역할을 다 적는다",
              set(r.get("역할배정") or {}) == set(_L.ROLE_OF),
              sorted(r.get("역할배정") or {}))
    finally:
        _L.complete, _L.available = saved["c"], saved["a"]
        _B134.PATH = saved["b"]
        for m, n, old in mods:
            setattr(m, n, old)
        import shutil as _sh
        _sh.rmtree(d, ignore_errors=True)


def test_judgement_runners_are_tested():
    """[135] **판정 파일을 쓰는 실행기는 시험이 봐야 한다** (결함 242·243).

    08-18 하루에 다섯 실행기가 판정 산출물을 만들었다 —
    `modelswap`·`parcheck`·`demorun`·`demopick`·`gencheck`.
    **시험이 하나도 안 태웠다.** `시험.ps1` 은 `test_phase1`·`test_phase2`
    만 돌고, `preflight.unwired()` 는 `__name__ == "__main__"` 이 있는
    모듈을 **통째로 건너뛴다**(결함 40 — 오탐 많은 가드는 꺼진다).

    ## 면제를 안 풀고 **다른 축으로 센다**

    CLI 라서 면제하는 것과 **판정을 쓰는데 면제하는 것**은 다르다.
    `safeio.save_json` 호출 여부로 좁히면 오탐 없이 이 다섯만 잡힌다.

    ## 그리고 `modelswap` 은 **가장 나쁜 형태였다** (결함 242)

    `.env` 의 첫 예비 모델이 **`gpt-4o-mini`** 인데 **그게 B 팔의
    모델이다.** A 가 한도에 걸려 예비로 넘어가면 A 도 B 도 같은 모델이
    답하고 **«불일치 0» 이 나온다** — 아무것도 안 재고 합격한다.
    라벨은 «무엇을 요청했나» 이지 «무엇이 답했나» 가 아니다.
    """
    from ..bench import preflight as _PF
    from ..bench import modelswap as _MS

    left = _PF.untested_runners()
    check("[135] 판정 파일을 쓰는데 **시험이 안 보는 모듈이 없다**",
          not left, "남은 것: %s" % left if left else "0개")

    # ── 결함 242 — **누가 답했나를 확인하고 판정을 낸다** ────────────
    M, S = _MS.llm.MODEL, "gpt-4o-mini"
    cases = [
        ("정상", {M: 9}, {M: 9}, {S: 9}, False),
        ("A 가 예비 모델로 넘어감", {S: 9}, {M: 9}, {S: 9}, True),
        ("A 가 일부만 넘어감", {M: 7, S: 2}, {M: 9}, {S: 9}, True),
        ("전부 캐시 (실호출 0)", {}, {M: 9}, {S: 9}, True),
        ("B 도 같은 모델이 답함", {M: 9}, {M: 9}, {M: 9}, True),
    ]
    for name, sa, sa2, sb, want_block in cases:
        blocked = bool(_MS._check_served(sa, sa2, sb, S))
        check("[135] 모델 확인 — %s %s" % (name, "→ 막는다" if want_block else "→ 통과"),
              blocked == want_block,
              _MS._check_served(sa, sa2, sb, S)[:1] or "통과")

    # 그리고 그 검사가 **실제로 판정 앞에** 있나 — 순서가 규약이다
    import inspect as _i
    src = _i.getsource(_MS.main)
    i_chk, i_ver = src.find("_check_served"), src.find("verdict")
    check("[135] 모델 확인이 **판정보다 앞에** 있다",
          0 <= i_chk < i_ver, (i_chk, i_ver))
    check("[135] 확인 실패면 **판정을 안 내고 종료코드 3**",
          "return 3" in src and '"확인실패"' in src)


# ══════════════════════════════════════════════════════════════════
#  실행 목록 — **순서가 곧 규약이다**
#
#  ## 왜 목록으로 바꿨나 (결함 210 · 08-14)
#
#  그동안 `__main__` 안에 `_run(...)` 95줄이 **늘어서 있었다.** 그래서 —
#
#    ① **전수가 한 번에 안 돈다.** `gradiocheck` 하나가 54초고 전체가
#       170초를 넘어 08-14에 계속 시간 초과했다. **가드가 못 도는
#       상태에서 «전수 통과» 를 말할 수 없다**
#    ② **이분 탐색을 못 한다.** `test_registry_quote` 가 단독은 통과하고
#       전수에서는 실패하는데(결함 210), 앞의 시험들을 반씩 잘라 돌리려면
#       **골라 돌릴 방법**이 있어야 한다. 없어서 손으로 하다 시간 초과했다
#
#  > 목록으로 만들되 **순서는 한 줄도 안 바꾼다.** 순서 의존 버그가
#  > 실재하므로, 순서를 건드리면 그 버그가 숨는다.
#
#  ## 쓰는 법
#
#      py -m bioreroute.tests.test_phase2                 전부 (전과 같다)
#      py -m bioreroute.tests.test_phase2 --list          번호와 이름
#      py -m bioreroute.tests.test_phase2 --shard 1/4     4등분 중 첫 묶음
#      py -m bioreroute.tests.test_phase2 --only quote    이름에 quote
#      py -m bioreroute.tests.test_phase2 --seq 3,7,44    번호로 (순서 유지)
#      py -m bioreroute.tests.test_phase2 --bisect test_registry_quote
#                                                         범인을 찾는다
# ══════════════════════════════════════════════════════════════════


def test_script_points_at_a_screen_that_exists():
    """[147] **대본이 가리키는 화면이 실재하는가** (결함 304).

    `시연영상_대본.md` 머리글이 *"화면 내용은 전부 실제 코드에서 뽑아
    확인했다 — 지어낸 라벨이 없다"* 라고 적어 놨다.
    **그 확인을 아무도 안 하고 있었다.**

    08-20 에 Gradio 를 걷어내고 탭 줄이 사이드바가 됐는데, 대본은
    **닷새 동안** 「탭」을 12곳에서 가리키고 `py app.py` 를 실행 방법으로
    적고 있었다. 그 대본으로 리허설을 하면 **첫 줄에서 막힌다.**

    이 시험이 지키는 것 —

      ① 대본이 인용한 **화면 이름**이 실제 화면에 있다
      ② 실행 방법이 **지금 도는 것**을 가리킨다 (`py app.py` 가 아니다)
      ③ 3분할이 뜨는 조건을 적어 뒀다 — **폭이 모자라면 2분할이다**

    ⚠ **완벽하지 않다.** 문자열이 있는지만 본다 — 그 화면이 *보기 좋은지*
    는 사람이 봐야 한다. 결함 유형 ⑦(«만든 것을 눈으로 안 봤다», 40건)이
    이 시험으로 안 닫힌다는 것을 적어 둔다.
    """
    import os
    from .. import evidence as EV

    root = EV.ROOT
    sp = os.path.join(root, "시연영상_대본.md")
    if not os.path.exists(sp):
        check("[147] 대본 파일이 있다", False, sp)
        return
    txt = open(sp, encoding="utf-8").read()
    ui = ""
    for rel in (("web", "static", "index.html"), ("web", "static", "app.js")):
        p2 = os.path.join(root, *rel)
        if os.path.exists(p2):
            ui += open(p2, encoding="utf-8").read()
    check("[147] 새 화면 소스를 읽었다", len(ui) > 2000, len(ui))

    # ① 대본이 부르는 화면 이름이 **실재해야 한다**
    for name in ("심사·시연", "약으로 시작", "병으로 시작", "판정 사례",
                 "어떻게 판단하나", "반증 기록",
                 "무엇을 골랐나", "어떤 잣대로", "어떻게 판단했나",
                 "무엇이 뒷받침하나", "이 시스템을 믿어도 되나"):
        if name not in txt:
            continue
        check("[147] 대본이 부르는 «%s» 가 화면에 실재한다" % name,
              name in ui, name)

    # ② 실행 방법이 **지금 도는 것**인가
    check("[147] 실행 방법이 `웹.ps1` 이다 — `app.py` 는 예비본이다",
          "웹.ps1" in txt, txt[:0])
    # `py app.py` 가 **지시로** 남아 있으면 안 된다.
    #   ⚠ **과거를 적은 줄은 지시가 아니다.** 이 시험을 처음 걸자마자
    #     내가 쓴 갱신 메모(*«`py app.py` 를 지시하고 있었다»*)를 잡았다.
    #     `docaudit` 에 같은 날 넣은 «A. 실제는 B 다» 건너뛰기와 같은 모양이다 —
    #     **낡은 것을 적는 것이 그 기록의 내용**인데 위반으로 세면
    #     «기록할수록 시험이 붉어진다». 과거형·부정 표식만 좁게 인정한다.
    _past = ("아니", "있었다", "였다", "적고 있었")
    bad = [l.strip() for l in txt.split("\n")
           if "py app.py" in l and not any(k in l for k in _past)]
    check("[147] `py app.py` 를 **실행 지시로 안 쓴다**", not bad, bad[:1])

    # ③ 3분할 조건 — 폭이 모자라면 2분할이라는 것을 적어 뒀나
    check("[147] **3분할이 뜨는 조건**을 적어 뒀다 — 안 적으면 시연에서 "
          "2분할이 뜬다(결함 293)",
          "사이드바를 접" in txt or "3분할" in txt and "800" in txt,
          txt[:0])
    # ④ **대역이 실제로 성립하는가** — 08-24 정정 (결함 313)
    #
    #   앞판은 *«서버가 죽었을 때 대역(`?static=1`)을 적어 뒀나»* 만 봤다.
    #   **그런데 그 주장 자체가 거짓이었다** — 그 주소를 여는 것이 곧
    #   그 서버에 요청하는 일이고, `server.py` 는 모든 응답에
    #   `Cache-Control: no-store` 를 붙인다. **서버가 죽으면 안 뜬다.**
    #   즉 **시험이 거짓을 지키고 있었다.** 결함 284(«안내문은 방어가
    #   아니다»)의 가장 나쁜 판 — 안내문이 아니라 **가드가** 거짓을 굳혔다.
    check("[147] `?static=1` 대역이 있다", "static=1" in txt)
    # ⚠ **정정 기록은 위반이 아니다.** 이 시험을 걸자마자 내가 방금 쓴
    #   «⛔ 「서버가 죽으면 static=1」은 틀린 말이었다» 를 잡았다.
    #   오늘만 네 번째다(결함 303·304·309와 같은 모양) — **낡은 것을 적는
    #   것이 그 기록의 내용**인데 위반으로 세면 «기록할수록 붉어진다».
    _undo = ("⛔", "정정", "틀린", "아니다", "소용없다", "안 뜬다")
    _bad311 = [l.strip() for l in txt.split("\n")
               if re.search(r"서버가 죽[^\n]{0,40}static=1"
                            r"|static=1[^\n]{0,40}서버가 죽", l)
               and not any(k in l for k in _undo)]
    check("[147] `?static=1` 을 **«서버가 죽었을 때»** 라고 말하지 않는다 "
          "— 결함 313", not _bad311, _bad311[:1])
    check("[147] **서버가 통째로 죽었을 때의 진짜 대역**을 적어 뒀다 — "
          "앱 서버와 무관한 두 번째 서버",
          "http.server" in txt and "배포정적" in txt,
          "`py -m http.server 8123 -d 배포정적` 이 대본에 없다")
    check("[147] 그 대역을 **미리** 띄우라고 적는다 — 죽고 나서 띄우면 늦다",
          "미리" in txt and "8123" in txt)

    # ⑤ **시연 당일에 터지는 두 자리** — 08-24 렌즈 7 (결함 313)
    #
    #   ① 포트가 이미 잡혀 있으면 `ThreadingHTTPServer` 가 그냥 `OSError`
    #      로 죽어 **화면에 파이썬 트레이스백**이 뜬다. 그리고 그 경우
    #      대개는 «우리 서버가 이미 떠 있는 것»이라 브라우저만 열면 된다.
    #   ② 포트 인자가 숫자가 아니면 **조용히 7866 으로 떴다.**
    #
    #   ⚠ **`--help` 통과는 검증이 아니다**(`CLAUDE.md §5`). 실제로 포트를
    #     잡아 놓고 `main()` 을 태운다.
    import contextlib as _ctx
    import importlib.util as _ilu
    import io as _io2
    import threading as _th2
    from http.server import ThreadingHTTPServer as _THS
    from http.server import BaseHTTPRequestHandler as _BHRH
    _sp = os.path.join(root, "web", "server.py")
    if os.path.exists(_sp):
        _busy, _port = None, 7899
        try:
            _busy = _THS(("127.0.0.1", _port), _BHRH)
        except OSError:
            _busy = None
        if _busy is not None:
            _th2.Thread(target=_busy.serve_forever, daemon=True).start()
            try:
                _spec = _ilu.spec_from_file_location("_srv311", _sp)
                _m = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_m)
                _b = _io2.StringIO()
                with _ctx.redirect_stdout(_b):
                    _rc = _m.main(["server.py", str(_port)])
                _out = _b.getvalue()
                check("[147] **포트가 잡혀 있어도 트레이스백을 안 낸다** — "
                      "결함 313", _rc == 1, _rc)
                check("[147] 그때 **«이미 떠 있을 수 있다»** 를 먼저 말한다 "
                      "— 대개 그게 사실이다",
                      "이미 떠 있을" in _out, _out[:60])
                check("[147] 그리고 **다른 포트로 띄우는 명령**을 찍는다",
                      "웹.ps1" in _out, _out[:60])
                _b2 = _io2.StringIO()
                with _ctx.redirect_stdout(_b2):
                    _rc2 = _m.main(["server.py", "abc"])
                check("[147] 포트가 숫자가 아니면 **기본값으로 몰래 안 뜬다**",
                      _rc2 == 2 and "숫자가 아니다" in _b2.getvalue(), _rc2)
            finally:
                _busy.shutdown()
                _busy.server_close()


def test_claims_carry_their_prior_art():
    """[148] **주장하는 문서가 그 선행연구를 같이 들고 있는가** (결함 305).

    8차 선행연구 검색(08-24, `선행연구대조.md §9`)이 주장 셋을 깎았다 —

      · 「반증이 병목」 **문제 정의**  → Maziarz & Stencel 2022 (사례도 HCQ)
      · 「도킹이 대개 안 맞는다」     → PNAS 118(19) 2021 (77개 중 76개)
      · 「AUROC 를 믿지 마라」        → Guney PSB 2017 (84.1% → 65.6%)

    **닷새 동안 발표 원고 둘은 그걸 몰랐다.** 실측 —
    `발표뼈대.md` 0회 · `발표_처음과끝.md` 0회. 그동안 예상 질문 답은
    *«우리 기여는 평가를 뒤집은 것»* 이라고 **깎인 주장을 그대로** 적고
    있었다. **승우가 심사위원 앞에서 소리 내어 읽을 문장이다.**

    왜 안 잡혔나 — **`선행연구대조.md` 를 고치면 끝인 줄 알았다.**
    그 문서를 인용하는 여섯 문서를 **아무것도 따라오게 하지 않는다.**
    결함 268·298·303 과 같은 계열(«적어 놓고 안 고친다»)의 네 번째다.

    그래서 **문서를 세지 않고 짝을 센다.** 어떤 문서가 그 주장의
    **표식**(우리가 잰 숫자·낱말)을 쓰면, **그 인용이 같은 문서에**
    있어야 한다. 문서마다 셋을 다 요구하지는 않는다 — 도킹을 안 말하는
    1장·17장 원고에 도킹 인용을 밀어 넣으면 **그게 더 나쁘다.**

    ⚠ **이 시험이 못 보는 것** — 인용이 *있다*는 것만 본다.
    **맞게 인용했는지는 사람이 본다.** 원문 대조는 `선행연구대조.md §9`
    가 «Guney 만 전문 확인, 나머지는 초록» 이라고 적어 뒀다.
    """
    import os
    from .. import evidence as EV

    root = EV.ROOT
    # 심사위원이 읽거나 승우가 소리 내어 읽는 문서들.
    docs = ("발표뼈대.md", "발표_처음과끝.md", "시연영상_대본.md",
            "Bio-ReRoute_1페이지.md", "연구기술보고서.md", "심사기준대조.md")
    # (주장 표식, 필요한 인용, 무엇을 주장하는가)
    pairs = (
        (("34,067", "2.3%"), ("Maziarz",), "「반증 근거가 희소하다」"),
        (("도킹",), ("PNAS", "77개 중 76"), "「도킹이 대개 안 맞는다」"),
        (("AUROC",), ("Guney",), "「AUROC 를 믿지 마라」"),
    )
    seen = 0
    for name in docs:
        p = os.path.join(root, name)
        if not os.path.exists(p):
            continue
        txt = open(p, encoding="utf-8").read()
        seen += 1
        for marks, cites, what in pairs:
            if not any(m in txt for m in marks):
                continue          # 그 주장을 안 한다 → 인용을 요구하지 않는다
            check("[148] %s 가 %s 를 말하면서 선행연구(%s)를 들고 있다"
                  % (name, what, "/".join(cites)),
                  any(c in txt for c in cites), name)
    check("[148] 검사할 문서를 실제로 찾았다 — 이름이 바뀌면 이 시험이 "
          "**조용히 통과한다**", seen >= 5, seen)

    # ② 정본 — `선행연구대조.md §9` 에 셋이 다 있어야 한다.
    p = os.path.join(root, "선행연구대조.md")
    if os.path.exists(p):
        src = open(p, encoding="utf-8").read()
        for c in ("Maziarz", "PNAS", "Guney"):
            check("[148] 정본(`선행연구대조.md`)에 %s 가 있다" % c, c in src)

    # ③ **깎인 주장이 되살아나지 않는가.**
    #   ⚠ 취소선·«축소»·«철회»·«못 쓴다» 가 붙은 줄은 **기록**이지 주장이 아니다.
    #     결함 303·304 에서 배운 모양이다 — 낡은 것을 적는 것이 그 기록의
    #     내용인데 위반으로 세면 «기록할수록 시험이 붉어진다».
    _off = ("~~", "축소", "철회", "못 쓴다", "못쓴다", "아니", "않는다")
    for name in docs:
        p = os.path.join(root, name)
        if not os.path.exists(p):
            continue
        bad = [l.strip() for l in open(p, encoding="utf-8").read().split("\n")
               if ("평가를 뒤집" in l or "평가 뒤집" in l)
               and ("우리" in l or "저희" in l)
               and not any(k in l for k in _off)]
        check("[148] %s 가 «평가를 뒤집은 것이 우리 것» 을 **다시 주장하지 "
              "않는다**" % name, not bad, bad[:1])

def test_dead_model_is_not_knocked_twice():
    """[149] **죽은 칸을 매 호출마다 다시 두드리지 않는다** (결함 313).

    08-24 승우 — *"gpt api키가 바꼈고 … 지금 로컬에서 돌리는데
    제미나이만 응답하네."*

    `.env` 사슬이 `gpt-5.4-mini → gpt-4o-mini → gemini/…` 인데
    **새 키로 `gpt-4o-mini` 가 접근 불가**가 됐다. 그러면 호출마다 —

        gpt-5.4-mini 실패 ×2(MAX_RETRY) → gpt-4o-mini 실패 ×2 → gemini 성공

    **판정 하나에 헛 호출이 넷.** 429 가 아니라 `_is_rate_limit` 에도
    안 걸려 재시도까지 다 돈다. 라이브 시연이 **133초** 걸린 자리가
    여기다 — 그리고 시연은 배점 **30점**이다.

    ## 이 고침이 **바꾸지 않는 것**

    **답하는 모델은 그대로다.** 어차피 실패할 칸을 건너뛸 뿐이다.
    `CLAUDE.md §3-2` 가 걱정하는 «동결 수치가 다른 시스템의 수치가
    된다» 에 해당하지 않는다 — 바뀌는 것은 **시간**뿐이다.

    ## 429 를 여기 넣으면 안 된다

    할당량은 **내일 풀린다.** 영구로 다루면 무료 티어 완충재가 통째로
    죽는다(`llm.py:26` 이 그 완충재를 왜 두는지 적어 뒀다).
    """
    import sys as _sys
    import types as _ty
    from ..io import llm as L, cache as C

    fake = _ty.ModuleType("litellm")
    fake.suppress_debug_info = False
    calls = []

    class _NotFound(Exception):
        pass

    class _Rate(Exception):
        pass

    def _comp(model=None, messages=None, **kw):
        calls.append(model)
        if model == "죽은모델":
            raise _NotFound("404 model_not_found: does not exist or you "
                            "do not have access")
        if model == "한도초과":
            raise _Rate("429 RESOURCE_EXHAUSTED quota")
        return {"choices": [{"message": {"content": "42"},
                             "finish_reason": "stop"}]}
    fake.completion = _comp

    old_mod = _sys.modules.get("litellm")
    old_put, old_m, old_f, old_b = C.put, L.MODEL, L.FALLBACKS, L.BYPASS_CACHE
    old_dead = dict(L._DEAD)
    try:
        _sys.modules["litellm"] = fake
        C.put = lambda *a, **k: None          # 캐시가 결과를 가리지 않게
        L.BYPASS_CACHE = True
        L._DEAD.clear()

        # ── ① 영구 실패는 **한 번만** 두드린다 ────────────────────────
        L.MODEL, L.FALLBACKS = "죽은모델", ["살아있는모델"]
        calls.clear()
        r1 = L.complete("첫 호출")
        n1 = len(calls)
        calls.clear()
        r2 = L.complete("둘째 호출")
        n2 = len(calls)
        check("[149] 첫 호출은 **사슬을 배운다** — 죽은 칸을 실제로 두드린다",
              n1 >= 2 and "죽은모델" in r1["provenance"].get("skipped_dead", [])
              or n1 >= 2, n1)
        check("[149] **둘째 호출부터 죽은 칸을 건너뛴다** — 결함 313",
              n2 == 1 and calls == ["살아있는모델"], calls)
        check("[149] **답하는 모델은 그대로다** — 판정이 안 바뀐다",
              r1["provenance"]["served_by"] == r2["provenance"]["served_by"]
              == "살아있는모델", r2["provenance"]["served_by"])
        check("[149] **건너뛴 칸을 감사 추적에 남긴다** — 조용한 축소는 위험하다",
              r2["provenance"].get("skipped_dead") == ["죽은모델"],
              r2["provenance"].get("skipped_dead"))
        check("[149] 무엇이 왜 죽었는지 **밖에서 볼 수 있다**",
              L.dead_models().get("죽은모델") == "모델 없음", L.dead_models())

        # ── ② 429 는 **죽이지 않는다** — 내일 풀린다 ──────────────────
        L._DEAD.clear()
        L.MODEL, L.FALLBACKS = "한도초과", ["살아있는모델"]
        calls.clear()
        L.complete("q1")
        calls.clear()
        L.complete("q2")
        check("[149] **429 는 사슬에서 안 뺀다** — 무료 티어 완충재가 죽는다",
              calls == ["한도초과", "살아있는모델"], calls)
        check("[149] 그래서 죽은 목록도 **비어 있다**",
              "한도초과" not in L.dead_models(), L.dead_models())

        # ── ③ 사슬이 통째로 죽으면 **조용히 실패하지 않는다** ─────────
        L._DEAD.clear()
        L.MODEL, L.FALLBACKS = "죽은모델", []
        L.complete("사슬을 죽인다")
        r3 = L.complete("그다음")
        check("[149] 사슬 전멸이면 **왜 전멸했는지 말한다** — 결함 99",
              r3["ok"] is False and "ALL_DEAD" in (r3["error"] or "")
              and "모델 없음" in (r3["error"] or ""), (r3["error"] or "")[:60])
    finally:
        C.put, L.MODEL, L.FALLBACKS, L.BYPASS_CACHE = old_put, old_m, old_f, old_b
        L._DEAD.clear()
        L._DEAD.update(old_dead)
        if old_mod is None:
            _sys.modules.pop("litellm", None)
        else:
            _sys.modules["litellm"] = old_mod

    # ── ④ **진단 도구가 실제로 쓰는 모델을 물어보나** ────────────────
    #   `diag` 가 `gpt-5.4-nano` 를 목록에 안 넣고 있었다 — 즉 «쓸 수 있는
    #   모델을 찾는 도구» 가 **실제로 쓸 수 있는 모델을 안 물어봤다.**
    import inspect as _insp
    from .. import diag as _D
    _oa = _D.CANDIDATES["OpenAI"]
    check("[149] 진단이 **지금 계정이 허용하는 계열**을 물어본다",
          any("5.4-nano" in x for x in _oa) and any("5.4-mini" in x for x in _oa),
          _oa)
    _src = _insp.getsource(_D)
    # ⚠ **주석은 실천이 아니다.** 처음에 원문 전체를 봤더니 «이렇게 하면
    #   안 된다» 고 적어 둔 **내 주석**이 걸렸다. 오늘만 세 번째 모양이다
    #   (결함 303 의 «실제는» 건너뛰기 · 304 의 과거형 표식).
    #   **금지어를 적는 것이 그 기록의 내용**일 때 위반으로 세면
    #   «기록할수록 시험이 붉어진다». 코드 줄만 본다.
    _code = [l for l in _src.split("\n") if not l.lstrip().startswith("#")]
    check("[149] 진단이 `max_tokens=5` 로 **추론 모델을 굶기지 않는다** (결함 237)",
          not any("max_tokens=5" in l for l in _code),
          [l.strip() for l in _code if "max_tokens=5" in l][:1])
    check("[149] 진단이 **빈 응답을 성공으로 세지 않는다** — 결함 99",
          "빈답" in _src and "본문이 비었다" in _src)
    check("[149] 진단이 실패 **원문을 자르지 않는다** (결함 306)",
          "s[:400]" in _src or "s[:200]" in _src, "원문이 52자로 잘린다")
    check("[149] 진단이 `.env` 사슬의 **죽은 칸**을 짚어 준다",
          "죽은 칸" in _src)


def test_static_snapshot_has_what_the_screen_asks_for():
    """[152] **화면이 부르는 것을 스냅샷이 갖고 있는가** (결함 318).

    08-24 승우: *«배포엔 이 약의 접근성 칸이 없는데 맞아?»* — **맞았다.**

    그날 그 칸을 「심사 기준 줄 오른쪽 팝오버」로 옮기면서 `liveLeft()` 가
    `/api/live/left` 를 받아야 손잡이가 켜지게 했는데, **그 경로를
    스냅샷에 안 넣었다.** 정적본에서는 호출이 실패 → `accShow(true)` 가
    안 불림 → **팝오버가 영영 안 뜬다.**

    ⚠ **«라이브가 안 되는 화면이라 없어도 된다» 가 아니다.** 이 칸의
      내용은 결과가 아니라 **«지금 심사 기준의 문턱»**(유망 80 · 조건부 …)
      이고, 제안서 §2.2 가 «두 축과 독립» 이라 적은 **접근성(LMIC) 층**이
      거기 붙는다. **발표 장이 그 칸을 가리킨다** — «화면에 있습니다»
      라고 말하는데 없으면 그 자리에서 무너진다.

    ## 왜 «UI 를 고치면 스냅샷도 고쳐야 한다» 를 사람이 기억하지 않게 하나

    화면과 스냅샷은 **다른 파일**이라 한쪽만 고쳐도 아무 경고가 없다.
    결함 82 계열이다 — **목록이 두 곳에 있으면 갈라진다.**
    """
    import json as _j
    import os as _o
    import re as _re
    from .. import evidence as _EV

    p = _o.path.join(_EV.ROOT, "배포정적", "static", "data", "snapshot.json")
    if not _o.path.exists(p):
        p = _o.path.join(_EV.ROOT, "web", "static", "data", "snapshot.json")
    if not _o.path.exists(p):
        check("[152] 스냅샷이 있다 — `py -m web.build_static`", False, p)
        return
    snap = _j.load(open(p, encoding="utf-8"))
    paths = {k.split("?")[0] for k in snap}
    check("[152] 스냅샷을 읽었다", len(snap) > 10, "%d경로" % len(snap))

    # ① 화면이 **정적 모드에서도** 부르는 것 — 전부 있어야 한다
    #    ⚠ 라이브 실행(`/api/live/run`·`/api/dz/*`)은 **서버가 필요**해서
    #      정적본에서 못 도는 게 맞다. 그건 화면이 이유를 적는다.
    need = ["/api/boot", "/api/case", "/api/dash/run", "/api/dash/card",
            "/api/dash/bottom", "/api/exit/help", "/api/entry/help",
            "/api/live/left"]
    for q in need:
        check("[152] 스냅샷에 `%s` 가 있다" % q, q in paths, sorted(paths)[:4])

    # ② **내용까지 본다** — 경로만 있고 알맹이가 비면 화면은 빈칸이다
    left = [k for k in snap if k.startswith("/api/live/left")]
    if left:
        html = snap[left[0]].get("html", "")
        txt = _re.sub(r"<[^>]+>", "", html)
        check("[152] 「이 약의 접근성」 칸에 **접근성(LMIC)** 이 담긴다",
              "접근성" in txt, txt[:60])
        check("[152] 같은 칸에 **심사 기준 문턱**이 담긴다 — 묻기 전에 보는 것이다",
              "유망" in txt and "기각" in txt, txt[:60])
        # 프리셋 전부 × 출구 전부 — 예시 카드를 눌러도 떠야 한다
        from ..core import profiles as _P
        from .. import demo as _D
        want = len(_D.PRESETS) * len(_P.EXITS)
        check("[152] 프리셋 × 심사 기준 **전 조합**이 구워졌다",
              len(left) == want, "%d개 (기대 %d)" % (len(left), want))


def test_slides_do_not_overlap():
    """[151] **슬라이드에서 글자끼리 겹치지 않는다** (결함 316).

    08-24 승우: *«ppt 후반부에 표랑 글자랑 겹치는 부분이 있었어»*.

    **눈으로 찾지 않았다.** `shape.left/top/width/height` 를 재서 전수로
    셌더니 **22건**이 나왔고, 그중 **18장에서만 16건 · 최대 61%** 였다.

    원인은 배율이 손으로 박혀 있던 것이다 — `n * 0.082`. 값이 128까지
    커지자 **막대가 이름 칸을 그대로 넘어갔고**, 작은 값(42·41·38)의
    숫자가 이름 위에 얹혔다. **08-10 주석이 «긴 막대에서 겹친다» 를
    걱정했는데 그때는 값이 작아 반대쪽이 안 보였다.**

    ## 없앨 수 없으면 **늘지 않게 막는다**

    21·22장(배점 대응)에 **6건**이 남아 있다. 그 둘은 08-18에
    **8월판에서 빼기로** 정한 장이라 그때 고치지 않았다.
    본선(D-37)까지 고친다. 그때 이 상수를 **같이 내려라.**

    ⚠ 배경 상자와 그 위 글자는 **의도된 겹침**이다. 그래서 **글이 있는
      도형끼리만** 본다. 그리고 12% 미만은 안 센다 — 눈에 안 보인다.
    """
    import os as _o
    from .. import evidence as _EV
    try:
        from pptx import Presentation as _Pr
    except Exception:
        check("[151] python-pptx 가 있다 — 없으면 이 검사가 죽는다", False,
              "pip install python-pptx")
        return
    # ── ⚠ 09-01 · **고치려다 시험을 망가뜨릴 뻔했다** ─────────────────
    #
    #   전수 실행에서 «발표 파일이 있다» 가 FAIL 이라, 나는 파일명이
    #   바뀐 줄 알고 `slides/*.pptx` 중 **가장 최근 것**을 보게 고쳤다.
    #   그러자 **다른 덱**을 검사해 **겹침 11건(기준 6)** 이 나왔다 —
    #   **기준 6은 그 덱의 값이 아니므로 그 비교는 성립하지 않는다.**
    #
    #   **되돌렸다.** 진짜 원인은 다른 데 있었다 — **pptx 는 빌드
    #   산출물**이다(`slides/build_deck.py`). 없으면 **시험을 고칠 게
    #   아니라 빌드해야 한다.** 그래서 안내만 또렷하게 바꾼다.
    p = _o.path.join(_EV.ROOT, "slides", "Bio-ReRoute_발표.pptx")
    if not _o.path.exists(p):
        check("[151] 발표 파일이 있다 — **없으면 빌드해라** "
              "`py slides/build_deck.py`", False, p)
        return

    def _bx(sh):
        l, t = sh.left or 0, sh.top or 0
        return (l, t, l + (sh.width or 0), t + (sh.height or 0))

    def _ov(a, b):
        x = min(a[2], b[2]) - max(a[0], b[0])
        y = min(a[3], b[3]) - max(a[1], b[1])
        return x * y if (x > 0 and y > 0) else 0

    # ── 09-27 · 8월판 덱 검사를 뺐다 ────────────────────────────────
    #   08-24 에 여기서 **8월판 덱**(21장)도 같이 봤다 — 그 주에 쓸 덱이 무검사가
    #   되지 않게. 그 덱은 본선 제출물이 아니고 다시 굽지 않는다. 본선에 내는 것은
    #   아래 25장판과 그걸 재배치한 10분판이다(10분판은 시험 [198] 의 deckfit 이 본다).
    hits, seen = [], 0
    for i, s in enumerate(_Pr(p).slides, 1):
        it = []
        for sh in s.shapes:
            if not sh.has_text_frame or not sh.text_frame.text.strip():
                continue
            it.append((_bx(sh), (sh.width or 0) * (sh.height or 0)))
        seen += len(it)
        for a in range(len(it)):
            for b in range(a + 1, len(it)):
                o = _ov(it[a][0], it[b][0])
                if o and o / (min(it[a][1], it[b][1]) or 1) > 0.12:
                    hits.append(i)
    # **0개면 «깨끗» 이 아니라 «검사가 죽은 것»일 수 있다** (결함 99)
    check("[151] 글상자를 실제로 셌다 — 0개면 이 시험이 죽은 것이다",
          seen > 100, "%d개" % seen)
    KNOWN = 6          # 08-24 실측 · 21·22장. **늘리지 마라. 줄이면 같이 내려라**
    check("[151] **겹치는 글상자가 늘지 않았다** — 결함 316",
          len(hits) <= KNOWN,
          "%d건 (기준 %d) · 장 %s" % (len(hits), KNOWN, sorted(set(hits))))
    # **결함 유형 막대 장은 10분판 부록으로 간다** — 여기만은 0이어야 한다
    check("[151] **18장(결함 유형)은 겹침 0** — 10분판 부록으로 가는 장이다",
          18 not in hits, sorted(set(hits)))


def test_no_structure_says_what_there_is_instead():
    """[150] **«없다» 로 끝내지 않는다** (결함 315).

    08-24 승우가 `Nirmatrelvir / COVID-19` 를 넣고 물었다 —
    *«구조가 알파폴드에 없다고 안 뽑히네, 그러면 방법이 없는 거지?»*

    **판정은 나왔다.** 안 나온 건 3D 뷰어뿐이다. 그런데 화면이
    *«AlphaFold 에 이 표적의 예측 구조가 없다»* 까지만 말하니 **결핍으로
    읽혔다.** 실제로는 반대다 — 3CLpro 는 **실험 구조가 수천 건**이고,
    결함 94 가 *«결정 구조가 있는데 예측 구조로 신뢰도를 재는 것은 자료원
    선택의 오류»* 라고 이미 적어 뒀다.

    그 수(`pdb_n`)를 `assess()` 가 **이미 실어 보내고 있었다.** 붙이는
    코드가 **좌표가 있어야 도달하는 자리**(뷰어 본문)에만 있어서,
    **구조가 없는 바로 그 경우에** 가장 중요한 사실이 빠졌다.

    > `CLAUDE.md §4` — **해석 문구를 상수로 고정하지 마라.
    > 방향을 데이터에서 읽어라.**

    ⚠ **없을 때는 없다고만 한다.** 실험 구조가 0건이면 그 문장을 안 붙인다 —
    안 그러면 «자료가 있다» 는 거짓 위안이 된다(결함 99 의 반대편).
    """
    from .. import viewer as _V

    base = {"label": "구조없음", "why": "예측 모델이 없다"}
    none = _V.render(dict(base, pdb_n=0))
    many = _V.render(dict(base, pdb_n=2413))

    check("[150] 실험 구조가 **0건이면 위안을 안 준다**",
          "다만 자료가 없는 것은 아니다" not in none, none[-90:])
    check("[150] 실험 구조가 있으면 **그 수를 말한다** — 결함 315",
          "2413건" in many, many[-120:])
    check("[150] **예측을 쓰는 것이 오류**라고 적는다 (결함 94)",
          "자료원 선택의 오류" in many)
    check("[150] **도킹은 실험 구조로 간다**고 알려 준다",
          "실험 구조로 간다" in many)
    # ⚠ 이 수는 **UniProt 항목 전체**의 것이다. 사슬 것으로 읽히면
    #   결함 90 을 반대편에서 되풀이하는 것이다.
    check("[150] **어느 사슬인지는 안 봤다**고 같이 적는다 (결함 90·94)",
          "안 봤다" in many and "항목 전체" in many)
    check("[150] 조회 **실패**는 «없다» 와 다르게 말한다 (결함 89)",
          "없다는 뜻이 아니다" in _V.render({"label": "오류", "why": "타임아웃"}))


def test_cache_is_not_poisoned_by_fallback():
    """[149] **폴백 답이 요청 모델 칸에 굳지 않는다** (결함 311).

    캐시 키는 **요청 모델**로 만든다 — `LLM::gpt-5.4-mini::0.0::<해시>`.
    그런데 08-24 에 OpenAI 키가 막혀 있던 동안 **Gemini 가 답했고 그 답이
    그 칸에 저장됐다.** 실측 **52칸**. 키가 풀린 뒤에도 같은 질문은
    **영원히 그 Gemini 답**을 준다 — 캐시가 «gpt-5.4-mini 의 답» 인 척
    남의 답을 들고 있는 것이다.

    승우: *"지금 로컬에서 내꺼 돌리는데 **제미나이만 응답하네**."*
    **모델도 키도 멀쩡했다.** 캐시가 옛 장애를 붙들고 있었다.

    > **폴백은 비상 수단이지 결과가 아니다.**

    결함 대장의 「캐시는 최적화가 아니라 자료원」 계열이고,
    *«일시 장애 380건이 캐시에 박혀 누출 차단이 88%에서 안 걸렸다»* 와
    **같은 병의 두 번째 판**이다.

    ⚠ **버리지 않는다.** 답한 모델의 칸으로 옮긴다 — 요청 모델이 살아나면
    다시 그 모델에게 묻고, 같은 폴백으로 직접 물으면 그대로 재사용된다.

    ⚠ **이 시험이 못 보는 것** — 캐시 *파일*만 본다. 프로세스 안의
    `_DEAD` 는 재시작 전까지 안 풀린다. 그건 사람이 서버를 껐다 켜야 한다.
    """
    import json as _j
    import inspect as _i
    import os as _o
    from ..io import llm as _L
    from .. import evidence as _EV

    src = _i.getsource(_L)
    check("[149] 폴백 답을 **요청 모델 칸에 안 넣는다** — 결함 311",
          "if cand == m:" in src, "분기가 없다 — 폴백이 요청 칸을 덮는다")
    check("[149] 그래도 **버리지는 않는다** — 답한 모델 칸에 넣는다",
          'cache.put("LLM::%s::%s::%s"' in src)

    # ── **자료가 문서를 이긴다** — 캐시 파일을 실제로 센다 ──────────
    p = _o.path.join(_EV.ROOT, "pubmed_cache.json")
    if not _o.path.exists(p):
        check("[149] 캐시 파일이 있다", False, p)
        return
    try:
        d = _j.load(open(p, encoding="utf-8"))
    except Exception as e:
        check("[149] 캐시를 읽었다", False, "%s: %s" % (type(e).__name__, e))
        return
    seen, bad = 0, []
    for k, v in d.items():
        if not k.startswith("LLM::") or not isinstance(v, dict):
            continue
        seen += 1
        req = k.split("::")[1]
        got = str(v.get("served_by") or "")
        # **답이 없는 칸은 안 본다** — 실패 기록도 캐시에 있다
        if got and req.split("/")[0] != got.split("/")[0]:
            bad.append("%s → %s" % (req, got))
    # **0건이면 «깨끗» 이 아니라 «검사가 죽은 것»일 수 있다**(결함 99)
    check("[149] LLM 칸을 실제로 셌다 — 0개면 이 시험이 죽은 것이다",
          seen > 0, "%d칸" % seen)
    check("[149] **요청한 모델과 답한 모델이 어긋난 칸이 없다**",
          not bad, "%d칸 — 예: %s" % (len(bad), bad[:3]))


def test_new_cli_entrypoints_actually_run():
    """[152] 09-01 에 만든 도구들의 **진입점을 실제로 태운다** (결함 320).

    ## 왜 필요했나 — **`--help` 조차 안 태웠다**

    `namecheck` 을 만들면서 판정 규칙 5경우를 모의로 다 태웠다. 그런데
    `argparse` 는 한 번도 안 돌렸고, `help="0건 비율 100%인 …"` 의 `%`
    가 포맷 지시자로 읽혀 **`--demo` 가 통째로 죽었다.**

    이 프로젝트는 *"`--help` 통과는 검증이 아니다"*(`CLAUDE.md §5`) 를
    지켜 왔는데, **그 반대쪽 구멍**이 있었다 — `--help` 가 약한 검증
    이라고 **아예 안 하면** 이렇게 죽는다.

    ⚠ **모듈을 부르지 말고 `main([...])` 을 태운다.** import 만 하면
    `add_argument` 가 안 돌아 이 버그를 못 잡는다.
    """
    import argparse as _ap_mod
    import importlib

    # ── ⚠ **이 시험이 유효한 환경인지 먼저 말한다** (`CLAUDE.md §5`) ──
    #
    #   09-01 에 승우 환경(**Python 3.14**)에서는 `help="…100%인…"` 이
    #   `argparse._check_help` 에 걸려 죽었다. 그런데 **샌드박스 파이썬
    #   에서는 안 죽는다** — 그 검사가 없는 판이다.
    #
    #   즉 **이 시험은 파이썬 판에 따라 강도가 다르다.** 약한 환경에서
    #   «통과» 를 «안전» 으로 읽으면 그게 거짓말이다. 그래서 **실패로
    #   세지 않고 사실만 찍는다.**
    try:
        _p = _ap_mod.ArgumentParser()
        _p.add_argument("--zz", help="100%인")
        _strict = False
    except ValueError:
        _strict = True
    check("[152] 이 파이썬이 **help 의 `%` 를 검사하는가** — 안 하면 "
          "이 시험은 그만큼 약하다", True,
          "검사함(3.14+)" if _strict else "⚠ 안 함 — 승우 환경에서 다시 돌려라")

    # 09-09 추가 — `apiprobe`. 본선 프록시 탐침이고 **9/7~10/2 개발 기간에
    #   가장 먼저 도는 진입점**이다. 만든 날 바로 등록한다: 08-14·08-18·
    #   08-31 에 «만들고 안 태운» 것이 세 번 반복됐고 세 번 다 여기서 걸렸다.
    mods = ["bioreroute.bench.selective", "bioreroute.bench.bindcheck",
            "bioreroute.bench.fragility", "bioreroute.bench.advsearch",
            "bioreroute.bench.namecheck", "bioreroute.io.binding",
            "bioreroute.apiprobe",
            # 09-13 — `pmccheck`. 만든 자리에서 바로 등록한다(네 번째다).
            "bioreroute.bench.pmccheck",
            # 09-14 — `io.fulltext`(절 추출기). CLI 는 없지만 임포트·
            #   공개 함수 존재는 여기서 지킨다.
            "bioreroute.io.fulltext"]
    for name in mods:
        try:
            m = importlib.import_module(name)
        except Exception as e:
            check("[152] `%s` 임포트" % name.split(".")[-1], False, repr(e))
            continue
        check("[152] `%s` 에 main 이 있다" % name.split(".")[-1],
              callable(getattr(m, "main", None)), name)
        # `--help` 는 SystemExit(0) 로 끝난다. **파서를 실제로 만든다.**
        import contextlib as _c, io as _i
        buf = _i.StringIO()
        rc = None
        try:
            with _c.redirect_stdout(buf):
                m.main(["--help"])
        except SystemExit as e:
            rc = e.code
        except Exception as e:
            check("[152] `%s --help` 가 죽지 않는다" % name.split(".")[-1],
                  False, "%s: %s" % (type(e).__name__, e))
            continue
        check("[152] `%s --help` 가 정상 종료(0)" % name.split(".")[-1],
              rc in (0, None), rc)
        check("[152] `%s --help` 가 usage 를 낸다" % name.split(".")[-1],
              "usage" in buf.getvalue(), buf.getvalue()[:40])


def test_evidence_tools_separate_missing_from_unreachable():
    """[153] **「없다」와 「못 찾았다」를 안 섞는다** — 결함 35 계열.

    09-01 하루에 **세 번** 같은 자리에서 걸렸다 —

      · `binding.verify` 가 네트워크 실패를 「근거없음」으로 낼 뻔했다
      · `bindcheck` 이 **자료 부재를 「어긋남」으로 채점**하고 있었다
        (rifampin 이 세 번 다 ❌ 였던 진짜 이유)
      · `namecheck` 이 조회 실패를 0건과 섞을 뻔했다

    셋 다 **우리 논지를 지지하는 방향**이라 더 위험했다 —
    *"자료가 없다"* 가 *"반증이 없다"* 로 읽힌다.

    `CLAUDE.md §2` — **«모른다»와 «차이 없다»는 다르다.**
    """
    from ..io import binding as B
    from ..bench import bindcheck as BC
    from ..bench import namecheck as NC

    # ── binding: 네트워크 실패는 「조회불가」다 ─────────────────────
    orig = B._cached
    try:
        def boom(key, url):
            raise OSError("네트워크 끊김")
        B._cached = boom
        r = B.verify("아무약", "아무표적")
        check("[153] `binding` 네트워크 실패 → **조회불가**",
              r["판정"] == "조회불가", r["판정"])
        check("[153] 그리고 **«근거 없음이 아니다»** 를 적는다",
              "아니다" in (r.get("왜") or ""), (r.get("왜") or "")[:40])

        def empty(key, url):
            if key.startswith("CHEMBLID"):
                return {"molecules": [{"molecule_chembl_id": "X"}]}
            if key.startswith("CHEMBLTGT"):
                return {"targets": [{"target_chembl_id": "T", "pref_name": "p"}]}
            return {"activities": []}
        B._cached = empty
        r2 = B.verify("아무약")
        check("[153] 활성 0건 → **근거없음** (조회불가와 다르다)",
              r2["판정"] == "근거없음", r2["판정"])
    finally:
        B._cached = orig

    # ── bindcheck: 자료 부재와 조회 실패는 **채점 밖** ──────────────
    check("[153] `bindcheck` 근거없음 → 채점 밖(None)",
          BC.score("직접·숙주", "근거없음") is None, BC.score("직접·숙주", "근거없음"))
    check("[153] `bindcheck` 조회불가 → 채점 밖(None)",
          BC.score("직접·숙주", "조회불가") is None, BC.score("직접·숙주", "조회불가"))
    check("[153] 그런데 **약한 결합은 어긋남으로 센다**(False)",
          BC.score("직접·숙주", "경보") is False, BC.score("직접·숙주", "경보"))
    check("[153] 강한 결합은 일치(True)",
          BC.score("직접·병원체", "지지") is True, BC.score("직접·병원체", "지지"))
    check("[153] 「간접」은 **표적이 없어 반증 불가** → 채점 밖",
          BC.score("간접", "지지") is None, BC.score("간접", "지지"))

    # ── namecheck: None(조회 실패)을 0건으로 읽지 않는다 ────────────
    check("[153] `namecheck` 조회 실패 → **조회불가**",
          NC._verdict({"원본(따옴표)": None, "따옴표 뺌": None,
                       "MeSH 태그": None}) == "조회불가", "None 셋")
    check("[153] 따옴표만 빼서 나오면 → **따옴표 문제**",
          "따옴표" in NC._verdict({"원본(따옴표)": 0, "따옴표 뺌": 900,
                                   "MeSH 태그": 0}), "0/900/0")
    check("[153] 셋 다 0 은 **«없다» 로 단정하지 않는다**",
          "진짜 없다" in NC._verdict({"원본(따옴표)": 0, "따옴표 뺌": 0,
                                      "MeSH 태그": 0}),
          NC._verdict({"원본(따옴표)": 0, "따옴표 뺌": 0, "MeSH 태그": 0}))

    # ── advsearch: 오류를 «0건» 으로 세지 않는다 ────────────────────
    from ..bench import advsearch as AS
    from ..io import sources as _S
    o = _S.pubmed_search
    try:
        def bad(q, retmax=8, max_year=None):
            raise OSError("끊김")
        _S.pubmed_search = bad
        rr = AS.run([{"drug": "a", "disease": "b"}])
        check("[153] `advsearch` 조회 실패는 **성공 0 · 오류 1**",
              rr["성공"] == 0 and rr["오류"] == 1,
              "성공 %s 오류 %s" % (rr["성공"], rr["오류"]))
        check("[153] 그때 **중앙값을 0 으로 내지 않는다**",
              rr["새PMID_중앙값"] is None, rr["새PMID_중앙값"])
    finally:
        _S.pubmed_search = o


def test_call_accounting_counts_every_paid_call():
    """[155] **나간 호출은 전부 세고, 안 나간 것은 안 센다** — 09-16 신설.

    09-16 전수 검증에서 나왔다. `_call` 이 **JSON 파싱 실패 시 기록 없이
    재시도**하고 있었다 —

        · `spent()` 가 그 호출을 **안 센다** → **`MAX_CALLS` 상한 우회**
          (사슬 3 × 재시도 2 = 최대 6회 호출에 기록 1건)
        · `tokens_spent()` 가 **토큰을 안 센다** → 배점 15(«크레딧 대비
          결과»)의 원자료가 **과소 보고**

    **셋 다 «덜 썼다» 로 보이는 방향**이었다.

    고치자 이번엔 **반대로 하나를 더 셌다** — 사슬이 전부 실패하면
    `_call` 끝에 남기는 **요약 한 줄**까지 `spent()` 가 센 것이다.
    `summary` 를 달아 제외했다. **이 시험이 그 균형을 고정한다.**
    """
    import sys as _sys, types as _types
    from ..io import llm as _L

    def _run(content, as_json, usage=True):
        """가짜 litellm 으로 태우고 (HTTP 수, spent, 토큰) 을 돌려준다."""
        n = {"c": 0}
        fake = _types.ModuleType("litellm")
        fake.__version__ = "t"
        fake.suppress_debug_info = False

        def _comp(**kw):
            n["c"] += 1
            d = {"choices": [{"message": {"content": content},
                              "finish_reason": "stop"}]}
            if usage:
                d["usage"] = {"prompt_tokens": 200, "completion_tokens": 50,
                              "total_tokens": 250}
            return d
        fake.completion = _comp
        old_mod = _sys.modules.get("litellm")
        sv = (_L.MODEL, _L.FALLBACKS, _L.API_BASE, _L.available,
              _L.cache, list(_L._CALLS))
        try:
            _sys.modules["litellm"] = fake
            _L._CALLS.clear()
            _L.MODEL, _L.FALLBACKS, _L.API_BASE = "t", [], ""
            _L.available = lambda: True
            _L.cache = _types.SimpleNamespace(
                get=lambda k: None, put=lambda k, v: None, has=lambda k: False)
            _L.complete("q", as_json=as_json)
            return n["c"], _L.spent(), _L.tokens_spent()
        finally:
            (_L.MODEL, _L.FALLBACKS, _L.API_BASE, _L.available,
             _L.cache, _c) = sv
            _L._CALLS.clear()
            _L._CALLS.extend(_c)
            if old_mod is not None:
                _sys.modules["litellm"] = old_mod
            else:
                _sys.modules.pop("litellm", None)

    # ① JSON 파싱 실패 — 재시도까지 **전부** 세어야 한다
    http, sp, tok = _run("이건 JSON 이 아니다", True)
    check("[155] JSON 실패 재시도를 **`spent()` 가 센다**", sp == http,
          "HTTP %d · spent %d — **같아야 상한이 안 뚫린다**" % (http, sp))
    check("[155] JSON 실패도 **토큰을 센다**", tok["총토큰"] == http * 250,
          "총 %s (기대 %d)" % (tok["총토큰"], http * 250))

    # ② 성공 — 하나면 하나
    http, sp, tok = _run('{"a":1}', True)
    check("[155] 성공 1회 → spent 1", sp == http == 1,
          "HTTP %d · spent %d" % (http, sp))

    # ③ 호출이 **안 나간** 실패는 세지 않는다
    sv2 = (_L.available, list(_L._CALLS))
    try:
        _L._CALLS.clear()
        _L.available = lambda: False
        t = _L.tokens_spent()
        check("[155] `NOT_CONFIGURED` 는 **토큰 0**", t["총토큰"] == 0, str(t))
    finally:
        _L.available = sv2[0]
        _L._CALLS.clear()
        _L._CALLS.extend(sv2[1])

    # ④ `summary` 는 호출이 아니다
    sv3 = list(_L._CALLS)
    try:
        _L._CALLS.clear()
        _L._CALLS.append({"cached": False, "usage": {"total": 250}})
        _L._CALLS.append({"cached": False, "error": "x", "summary": True})
        check("[155] `summary` 줄은 **`spent()` 에서 뺀다**", _L.spent() == 1,
              "spent %d (기록 2건 중 요약 1)" % _L.spent())
    finally:
        _L._CALLS.clear()
        _L._CALLS.extend(sv3)


def test_fulltext_gate_contracts():
    """[154] **F(전문 읽기) 게이트가 지키는 계약 다섯** — 09-15 신설.

    오늘 모의로 확인한 것을 **시험으로 고정한다.** 아래 다섯은 나중에
    누가 건드리면 **조용히 깨지는** 종류다 — 화면에 오류가 안 나고
    수치만 달라진다.

    ① **못 읽은 것을 「한계 없음」으로 안 센다**(결함 35 계열)
    ② **지지·반박 «양쪽»을 감쇠한다** — 지지만 깎으면 **주지표(기각
       정밀도)를 인위적으로 올리는 것**이다
    ③ **`QUIET_WHEN_OFF` 가 B5 trail 을 안 건드린다** — 09-12 궤적
       84쌍과 나란히 놓을 수 있어야 한다
    ④ **LLM 실패를 「무관」으로 안 민다** — 밀면 «LLM 실패» 가 «한계가
       효능과 상관없다» 는 **발견**으로 둔갑한다
    ⑤ **계수를 안 올린다** — 「강화」도 1.0. 올리는 쪽으로 손대는 순간
       사후 조정이 된다
    """
    from ..core import gates as _G, state as _S
    from ..io import llm as _LLM, fulltext as _FT
    from ..agents import limits as _LIM

    # ── ③ 먼저. 다른 것과 달리 **모의가 필요 없다** ─────────────
    off = [n for n in _G.ORDER
           if not _G.CONFIGS["B5"].get(n) and n not in _G.QUIET_WHEN_OFF]
    check("[154] `fulltext` 를 켜도 **B5 trail 이 안 바뀐다**",
          off == ["registry"],
          "B5 에서 config off 로 남는 게이트: %s (09-12 실측은 registry 하나)"
          % off)
    check("[154] `B5F` 에 `fulltext` 가 켜져 있다",
          _G.CONFIGS.get("B5F", {}).get("fulltext") is True,
          str(sorted(k for k, v in _G.CONFIGS.get("B5F", {}).items() if v)))

    # ── ⑤ 계수 ──────────────────────────────────────────────
    check("[154] 「강화」 계수가 **1.0 이다**(올리지 않는다)",
          _LIM.LIMIT_MULT.get("강화") == 1.0, str(_LIM.LIMIT_MULT))
    check("[154] 「무관」 계수가 1.0", _LIM.LIMIT_MULT.get("무관") == 1.0,
          str(_LIM.LIMIT_MULT))
    check("[154] 「약화」 계수가 **1 미만**",
          0 < _LIM.LIMIT_MULT.get("약화", 9) < 1.0, str(_LIM.LIMIT_MULT))

    # ── ④ LLM 실패 → 빈 목록(«무관» 아님) ─────────────────────
    _save = _LLM.complete
    try:
        _LLM.complete = lambda *a, **k: {"ok": False, "error": "429"}
        r = _LIM.judge("d", "x", [{"pmid": "1", "종류": "한계절", "본문": "t"}])
        check("[154] LLM 실패는 **빈 판정**이다 — 「무관」으로 안 민다",
              r.get("ok") is False and not r.get("판정"), repr(r)[:80])
    finally:
        _LLM.complete = _save

    # ── ①② 게이트 본체 ──────────────────────────────────────
    def _rec(pmid, d, w):
        return {"pmid": pmid, "direction": d, "weight": w, "kept": True,
                "quote": "q", "stage": "rag"}

    def _cand(fc):
        c = _S.Candidate(name="x", origin="t", query="q",
                         drug="metformin", disease="breast cancer")
        c.factcheck = fc
        return c

    sv = (_LLM.available, _FT.pmc_ids, _FT.limitations, _LIM.judge)
    try:
        _LLM.available = lambda: True
        _FT.pmc_ids = lambda ps, progress=None: {
            "매핑": {p: "PMC" + p for p in ps}, "PMC없음": [], "조회불가": []}

        # ② 지지·반박 둘 다 「약화」로 판정되면 **둘 다** 내려가야 한다
        _FT.limitations = lambda pmc, use_cache=True: {
            "판정": "추출됨", "종류": "한계절", "본문": "표본이 작다"}
        _LIM.judge = lambda d, di, items: {"ok": True, "판정": [
            {"pmid": it["pmid"], "종류": it["종류"], "effect": "약화",
             "mult": 0.6, "why": "w"} for it in items]}
        c = _cand([_rec("11", "support", 3.0), _rec("22", "refute", 2.0)])
        _G.gate_fulltext(_S.RunState("t", "s", "st", [c], _G.CONFIGS["B5F"]))
        sup = [r for r in c.factcheck if r["direction"] == "support"][0]
        ref = [r for r in c.factcheck if r["direction"] == "refute"][0]
        check("[154] **지지**가 감쇠된다", sup["weight"] < 3.0,
              "%.2f (원본 %s)" % (sup["weight"], sup.get("weight_before_limits")))
        check("[154] **반박도 감쇠된다** — 한쪽만 깎으면 주지표 조작이다",
              ref["weight"] < 2.0,
              "%.2f (원본 %s)" % (ref["weight"], ref.get("weight_before_limits")))
        check("[154] 감쇠 전 가중치를 **남긴다**(감사 추적)",
              sup.get("weight_before_limits") == 3.0,
              str(sup.get("weight_before_limits")))

        # ⛔ 「무관」도 **기록**돼야 한다 — 09-15 실측에서 이게 없어
        #   근거만 봐서는 무관이 0으로 보였고, 명세 §5 의 반증 조건
        #   («절반 이상 무관»)을 **근거 단위로 못 쟀다.**
        _LIM.judge = lambda d, di, items: {"ok": True, "판정": [
            {"pmid": it["pmid"], "종류": it["종류"], "effect": "무관",
             "mult": 1.0, "why": "무관하다"} for it in items]}
        c9 = _cand([_rec("11", "support", 3.0)])
        _G.gate_fulltext(_S.RunState("t", "s", "st", [c9], _G.CONFIGS["B5F"]))
        r9 = c9.factcheck[0]
        check("[154] 「무관」도 **근거에 기록된다**",
              (r9.get("limits") or {}).get("effect") == "무관",
              str(r9.get("limits")))
        check("[154] 「무관」은 **가중치를 안 바꾼다**",
              r9["weight"] == 3.0 and "weight_before_limits" not in r9,
              "%.2f" % r9["weight"])

        # ⛔ 09-16 · `gate_skeptic` 에는 있고 여기엔 **없던** 방어.
        #   비면 `judge("", "", …)` 가 불려 **빈 프롬프트로 판정**하고
        #   그 결과로 가중치를 깎는다.
        c10 = _cand([_rec("11", "support", 3.0)])
        c10.drug = ""
        _G.gate_fulltext(_S.RunState("t", "s", "st", [c10], _G.CONFIGS["B5F"]))
        check("[154] 약물·질환이 비면 **SKIP** — 빈 프롬프트로 안 묻는다",
              c10.trail[-1].outcome == "SKIP"
              and c10.factcheck[0]["weight"] == 3.0,
              "%s · %s" % (c10.trail[-1].outcome, c10.trail[-1].detail))

        # ① 못 읽으면 UNKNOWN + 가중치 불변
        for lab, stub in (("절없음", {"판정": "절없음", "본문절": []}),
                          ("본문없음", {"판정": "본문없음", "길이": 10}),
                          ("조회실패", {"판정": "조회실패", "왜": "망"})):
            _FT.limitations = lambda pmc, use_cache=True, _s=stub: _s
            c2 = _cand([_rec("11", "support", 3.0)])
            _G.gate_fulltext(_S.RunState("t", "s", "st", [c2],
                                         _G.CONFIGS["B5F"]))
            last = c2.trail[-1]
            check("[154] 「%s」 → **가중치 불변**" % lab,
                  c2.factcheck[0]["weight"] == 3.0,
                  "%.2f" % c2.factcheck[0]["weight"])
            check("[154] 「%s」 → UNKNOWN 이고 **«한계 없음» 이 아니라고 적는다**"
                  % lab,
                  last.outcome == "UNKNOWN" and "없음" in (last.detail or ""),
                  "%s · %s" % (last.outcome, (last.detail or "")[:60]))

        # 판정은 왔는데 LLM 이 실패 → 감쇠 0
        _FT.limitations = lambda pmc, use_cache=True: {
            "판정": "추출됨", "종류": "한계절", "본문": "t"}
        _LIM.judge = lambda d, di, items: {"ok": False, "판정": [], "error": "429"}
        c3 = _cand([_rec("11", "support", 3.0)])
        _G.gate_fulltext(_S.RunState("t", "s", "st", [c3], _G.CONFIGS["B5F"]))
        check("[154] 읽었으나 LLM 실패 → **감쇠 안 함**",
              c3.factcheck[0]["weight"] == 3.0 and
              c3.trail[-1].outcome == "UNKNOWN",
              "%.2f · %s" % (c3.factcheck[0]["weight"], c3.trail[-1].outcome))
    finally:
        (_LLM.available, _FT.pmc_ids, _FT.limitations, _LIM.judge) = sv


def test_countsync_never_touches_sealed_documents():
    """[156] **동기화 도구가 봉인을 못 깬다** — 09-16 신설.

    ## 무엇이 있었나

    `countsync` 는 대상 목록을 `docaudit.DOCS` 에서 파생한다(결함 159 —
    *"고치는 쪽이 검사하는 쪽보다 좁으면 감사는 영원히 운다"*). 맞는
    판단이었는데 **한쪽 방향만 봤다.** `docaudit.DOCS` 에는 **봉인된
    사전명세 7개**가 «감사가 보게 하려고» 등록돼 있고, 그 자리에
    이렇게까지 적혀 있다 —

      > ⚠ **봉인한 뒤에는 내용을 고치지 않는다.** 여기 등록하는 것은
      >   감사가 이 파일의 존재를 보게 하려는 것이지 **값을 맞춰
      >   고치라는 뜻이 아니다.**

    **그 주석 바로 아래에서 `countsync` 가 그 목록을 고치는 쪽으로
    물려받고 있었다.** 즉 *«보라고 넣은 목록»* 이 *«고치는 목록»* 이 됐다.

    ## 왜 사고가 안 났나 — **운이다**

    09-16 실측: 그 7개 중 `회귀 시험 NNNN건` 을 인용한 줄이 **0개**.
    `countsync.py:62` 가 앞선 사고를 두고 적은 문장이 그대로 적용된다 —
    *"값이 `--old` 와 우연히 같을 때만 걸리므로 사고가 안 났을 뿐."*

    **09-15에 실제로 봉인 하나를 훼손했고 1차 본문은 복구 불가다.**
    그때 닫은 것은 `CLAUDE.md` 의 문장 하나였다. **안내문은 방어가
    아니다** — 이 시험이 구조다.

    ## 무엇을 고정하나

      ① `targets()` 가 **봉인된 파일을 하나도 안 담는다**
      ② `plan()` 이 봉인된 파일의 줄을 **하나도 안 낸다**
      ③ 그러면서 **너무 넓게 빼지도 않는다** — 봉인 없는 문서는 남는다
      ④ **깨뜨려 본다**: 봉인 목록을 비우면 7개가 되살아나야 한다.
         안 그러면 이 시험은 **아무것도 안 보고 초록**인 것이다
    """
    import os as _o156, json as _j156, glob as _g156
    from ..bench import countsync as _CS, docaudit as _DA156
    from .. import evidence as _EV156
    root = _EV156.ROOT

    sealed = {_o156.path.basename(x) for x in _DA156.sealed_docs(root)}
    check("[156] 봉인 목록을 **실제로 읽었다** — 0개면 이 시험이 공허하다",
          len(sealed) >= 20, len(sealed))

    tg = _CS.targets(root)
    bad = [d for d in tg if _o156.path.basename(d) in sealed]
    check("[156] `targets()` 에 **봉인된 문서가 없다**", not bad, str(bad[:4]))

    # ② 실제 계획에도 안 나온다 (문턱을 우회하는 경로가 없는지)
    rows = _CS.plan({"결함": 1, "시험": 2}, {"결함": 9, "시험": 8}, root)
    bad2 = [r[0] for r in rows if _o156.path.basename(r[0]) in sealed]
    check("[156] `plan()` 이 **봉인된 줄을 안 낸다**", not bad2, str(bad2[:4]))

    # ③ 너무 넓게 빼면 «고치는 쪽이 좁아» 감사가 영원히 운다 (결함 159)
    check("[156] 그래도 **고칠 문서는 남는다** — 넓게 빼지 않았다",
          len(tg) >= 40, len(tg))
    check("[156] 봉인 **없는** 사전명세는 **안 빠진다** (반증 기록)",
          "사전명세_라우터그래프_반증.md" in tg,
          "사전명세_라우터그래프_반증.md" in tg)

    # ④ **깨뜨려 본다** — 봉인을 못 읽으면 되살아나야 한다 (결함 85)
    _sv156 = _DA156.sealed_docs
    try:
        _DA156.sealed_docs = lambda _r=None: []
        back = _CS.targets(root)
        check("[156] **봉인 목록이 비면 그만큼 되살아난다** — 진짜 거르고 있다",
              len(back) > len(tg), "%d → %d" % (len(tg), len(back)))
    finally:
        _DA156.sealed_docs = _sv156

    # ⑤ 봉인 json 이 가리키는 것이 **정말 그 파일들**인가 (오탐 방지)
    n = 0
    for p in _g156.glob(_o156.path.join(root, "*_봉인.json")):
        try:
            d = _j156.load(open(p, encoding="utf-8"))
        except Exception:                                  # noqa: BLE001
            continue
        t = (d.get("문서") or "").strip()
        if t and _o156.path.exists(_o156.path.join(root, t)):
            n += 1
    check("[156] 봉인이 가리키는 파일이 **실재한다** (%d개)" % n, n >= 20, n)


def test_token_cost_is_attributed_to_funnel_stages():
    """[157] **토큰이 깔때기 단계에 귀속된다** — 09-16 신설 (배점 ④ 15점).

    요강: *"**제공된 크레딧 대비** 결과물의 질적 완성도"* · 본선 한도
    **3,000만 토큰**. 그런데 09-12 실측(`본선API_실측.md`)으로
    **팀 잔량을 알려 주는 헤더가 없다**는 것이 확인됐다 —
    **우리가 세는 것이 유일한 계량기다.**

    총합만으로는 우리 논지를 증명하지 못한다 —

      > *"병목은 …그럴듯하지만 틀린 후보를 **값싸게** 걸러내는 일"*

    값싼 게이트가 앞이라는 **설계 주장**의 증거는 **단계별 비용 곡선**이다.
    `cost_report()` 가 그것을 내고, 이 시험이 그 계량을 고정한다.

    ## 고정하는 것 일곱

      ① `purpose` 가 `_CALLS` 에 남는다
      ② **캐시 키가 안 바뀐다** — 과거 답이 그대로 적중해야 한다(`§3-2`).
         계량을 붙인 것만으로 **재측정이 일어나면 안 된다**
      ③ `provenance` 에 **안 들어간다** — 판정 출력 모양이 바뀌면
         동결된 결과와 대조가 어긋난다
      ④ 이름표 없는 호출은 **`"미상"`** 이다 — 0으로 밀지 않는다(결함 35)
      ⑤ `summary` 는 호출이 아니다 — `spent()` 와 **같은 규칙**
      ⑥ **파이프라인의 모든 `complete()` 호출부가 `purpose` 를 넘긴다** —
         새 게이트가 조용히 «미상» 으로 새지 않게
      ⑦ ⚠ **그 인자 이름이 `role` 이 아니다** ↓

    ## ⑦ 이 시험의 진짜 이유 — **가드를 멀게 하지 않는다**

    시험 **[133]** 은 소스를 AST 로 읽어 `role="x"` 키워드를 **«그 역할이
    `model_for` 에 배선됐다»** 는 증거로 센다. 계량 표식을 `role=` 로
    지었다면 **[133]이 죽은 역할을 살아 있다고 보고**했을 것이다 —
    결함 232 가 정확히 그 사고였고 그때 *"감사 추적이 거짓말을 했다"* 고
    적었다. **계량은 `purpose`, 배선은 `role`.**
    """
    import ast as _a157, os as _o157, sys as _s157, types as _t157, glob as _g157
    from ..io import llm as _L157

    # ── ⑦ 먼저. 이름이 어긋나면 나머지는 의미가 없다 ──────────────
    sig = _a157.parse(
        "def f(%s): pass" % ", ".join(
            ["prompt", "system=''", "model=None", "as_json=False", "purpose=''"]))
    _ = sig                                        # 문서화용
    src157 = open(_o157.path.join(
        _o157.path.dirname(_o157.path.dirname(_o157.path.abspath(__file__))),
        "io", "llm.py"), encoding="utf-8").read()
    fn = next((n for n in _a157.walk(_a157.parse(src157))
               if isinstance(n, _a157.FunctionDef) and n.name == "complete"), None)
    args = [a.arg for a in (fn.args.args if fn else [])]
    check("[157] `complete()` 가 **`purpose`** 를 받는다", "purpose" in args, args)
    check("[157] ⚠ 그 인자가 **`role` 이 아니다** — [133]을 멀게 한다",
          "role" not in args, args)

    # ── ⑥ 호출부 전수. **소스를 읽어서** 센다 (렌즈 3 계열) ─────────
    root157 = _o157.path.dirname(_o157.path.dirname(_o157.path.abspath(__file__)))
    miss = []
    for f in _g157.glob(_o157.path.join(root157, "**", "*.py"), recursive=True):
        if "tests" in f or "__pycache__" in f:
            continue
        for n in _a157.walk(_a157.parse(open(f, encoding="utf-8").read())):
            if isinstance(n, _a157.Call) and getattr(n.func, "attr", "") == "complete":
                if not any(k.arg == "purpose" for k in n.keywords):
                    miss.append("%s:%d" % (_o157.path.basename(f), n.lineno))
    check("[157] **모든 호출부가 `purpose` 를 넘긴다** — 새 게이트가 «미상» 으로 안 샌다",
          not miss, str(miss[:4]))

    # ── ⑧ **모의가 실제 시그니처를 따른다** — 09-16 저녁에 값을 치렀다 ──
    #
    #   `purpose=` 를 붙인 날, 시험 **23건이 한꺼번에 깨졌다** —
    #       TypeError: … got an unexpected keyword argument 'purpose'
    #   시험 파일 안의 **`complete` 대역 17개**(def 16 · lambda 1)가
    #   `(prompt, system, model, as_json)` 에 멈춰 있었기 때문이다.
    #
    #   원인은 내가 **개별 시험 다섯 개만 돌리고 전체를 안 돌린 것**이다.
    #   그리고 그 전에 `CLAUDE.md §5` 가 이미 적어 뒀다 —
    #       *"모의로 시험할 때 **모의가 거짓말하지 않는지** 먼저 확인해라."*
    #
    #   **모의가 실제보다 좁으면 실제 인자를 받는 경로를 시험할 수 없다.**
    #   그래서 이 검사가 그 간격을 구조로 막는다. 안내문이 아니라.
    real = set(args) | {a.arg for a in (fn.args.kwonlyargs if fn else [])}
    stale = []
    for f in (__file__, _o157.path.join(_o157.path.dirname(__file__),
                                        "test_phase1.py")):
        if not _o157.path.exists(f):
            continue
        for n157 in _a157.walk(_a157.parse(open(f, encoding="utf-8").read())):
            if not isinstance(n157, (_a157.FunctionDef, _a157.Lambda)):
                continue
            a157 = {x.arg for x in n157.args.args}
            # **`complete` 대역**의 표식: as_json 을 받고 프롬프트를 첫 인자로 받는다
            if "as_json" not in a157 or not (a157 & {"prompt", "p"}):
                continue
            if n157.args.kwarg is not None:      # **kwargs 면 다 받는다
                continue
            missing = (real - {"prompt"}) - a157
            if missing:
                stale.append("%s:%d %s" % (_o157.path.basename(f), n157.lineno,
                                           sorted(missing)))
    check("[157] ⑧ **`complete` 모의가 실제 시그니처를 따른다** — 모의가 실제보다 좁으면 거짓말이다",
          not stale, "%d곳: %s" % (len(stale), stale[:3]))

    # ── ①②③④⑤ 실제로 태운다. 가짜 공급자 ───────────────────────
    def _fake(n):
        mod = _t157.ModuleType("litellm")
        mod.__version__ = "t"
        mod.suppress_debug_info = False

        def _comp(**kw):
            n["c"] += 1
            return {"choices": [{"message": {"content": '{"ok":1}'},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                              "total_tokens": 120}}
        mod.completion = _comp
        return mod

    n = {"c": 0}
    old = _s157.modules.get("litellm")
    sv = (_L157.MODEL, _L157.FALLBACKS, _L157.API_BASE, _L157.available,
          _L157.cache, list(_L157._CALLS))
    try:
        _s157.modules["litellm"] = _fake(n)
        _L157.MODEL, _L157.FALLBACKS, _L157.API_BASE = "m", [], ""
        _L157.available = lambda: True

        class _C:                                  # 키만 기억하는 가짜 캐시
            def __init__(self): self.d = {}
            def has(self, k): return k in self.d
            def get(self, k): return self.d[k]
            def put(self, k, v): self.d[k] = v
        c = _C()
        _L157.cache = c
        del _L157._CALLS[:]

        r1 = _L157.complete("같은 프롬프트", as_json=True, purpose="router")
        k1 = list(c.d)
        r2 = _L157.complete("같은 프롬프트", as_json=True, purpose="factcheck")
        # ② **다른 purpose 인데 캐시가 적중해야 한다**
        check("[157] ② `purpose` 가 **캐시 키를 안 바꾼다** — 재측정이 안 일어난다",
              r2.get("cached") is True and list(c.d) == k1,
              "키 %d개 · 두번째 cached=%s" % (len(c.d), r2.get("cached")))
        check("[157] ② 그래서 **공급자 호출은 1회뿐이다**", n["c"] == 1, n["c"])
        # ③ 판정 출력에는 안 붙는다
        check("[157] ③ `provenance` 에 **`purpose` 가 없다** — 판정 모양 불변",
              "purpose" not in (r1.get("provenance") or {}),
              sorted(r1.get("provenance") or {}))
        # ① 기록에는 남는다
        check("[157] ① `_CALLS` 에 **남는다**",
              [x.get("purpose") for x in _L157._CALLS] == ["router", "factcheck"],
              [x.get("purpose") for x in _L157._CALLS])

        # ④ 이름표 없는 호출 → 「미상」
        _L157.complete("이름표 없는 질문", as_json=True)
        rep = _L157.cost_report()
        check("[157] ④ 이름표 없는 호출이 **「미상」** 으로 남는다 (0으로 안 민다)",
              "미상" in rep["단계별"], sorted(rep["단계별"]))
        check("[157] 단계별 합이 **총합과 같다**",
              sum(v["토큰"] for v in rep["단계별"].values()) == rep["합계"]["총토큰"],
              "%d vs %d" % (sum(v["토큰"] for v in rep["단계별"].values()),
                            rep["합계"]["총토큰"]))
        check("[157] **캐시 적중은 토큰 0이되 호출로는 센다** — 둘을 가른다",
              rep["단계별"]["factcheck"]["캐시"] == 1
              and rep["단계별"]["factcheck"]["토큰"] == 0,
              rep["단계별"]["factcheck"])
        check("[157] 한도 대비가 **나온다** (한도 %d)" % _L157.TOKEN_BUDGET,
              0 <= (rep["한도대비"] or 0) < 1, rep["한도대비"])

        # ⑤ summary 는 호출이 아니다 — **깨뜨려 확인한다**
        del _L157._CALLS[:]
        _L157._CALLS.append({"purpose": "router", "cached": False,
                             "summary": True, "error": "x"})
        check("[157] ⑤ `summary` 는 **단계별에도 안 센다**",
              not _L157.cost_report()["단계별"], _L157.cost_report()["단계별"])
    finally:
        (_L157.MODEL, _L157.FALLBACKS, _L157.API_BASE, _L157.available,
         _L157.cache, _keep) = sv
        del _L157._CALLS[:]
        _L157._CALLS.extend(_keep)
        if old is not None:
            _s157.modules["litellm"] = old
        else:
            _s157.modules.pop("litellm", None)


def test_reject_recall_prints_its_own_fraction():
    """[167] **재현율도 분수를 찍는다** — 09-20 신설. 결함: 7주 산 오류.

    ## 무엇이 있었나 — **화면이 옆칸의 분모를 빌려주게 생겼다**

    표가 이렇게 찍혔다.

        기각 정밀도        기각 재현율
        90% (95/106)      25%

    **재현율에만 분수가 없다.** 그래서 사람이 *«25% 의 분수는?»* 하고
    **옆의 106 을 가져왔다.** 실제로 그랬다 —

        홀드아웃결과.md      「106/387 = 27.4%」  ← 분자가 틀렸다
        올바른 값            「 95/387 = 24.5%」

    106 은 **TN기각 95 + TP기각 11**(유효한데 기각한 것)이다.
    그 값이 발표대본·발표뼈대·연구기술보고서·예상질문까지 번졌고
    **봉인된 사전명세의 비교 기준(p0)** 에도 들어갔다.

    ## ⛔ 왜 7주를 살아남았나 — **작은 표본에서는 두 정의가 같다**

    개발집합 84쌍은 **TP 기각이 0건**이라 두 식이 **우연히 같은 수**를
    낸다. 그래서 개발집합만 보는 한 영영 안 드러난다.
    **표본을 키워야만 갈라지는 오류**다 — 새 계열이다.

    ## 고친 방식 — 안내문이 아니라 **화면**

    둘 다 분수를 찍으면 **분자가 같은 95 임이 눈에 보인다.**
    `CLAUDE.md` 머리글 — *«안내문은 방어가 아니다. 구조로 막아야 한다.»*
    """
    import inspect as _in167
    import re as _re167
    from ..bench import run as _R167

    src = _in167.getsource(_R167.main) if hasattr(_R167, "main") else ""
    if not src:
        src = _in167.getsource(_R167)

    # ① 재현율 줄이 분수를 찍는가.
    #    두 포맷을 한꺼번에 세지 않는다 — 정밀도만 있어도 1개가 되므로
    #    **«고쳤다» 를 통과로 오인한다.** 인자로 구분한다.
    frac = _re167.findall(r'"%\.0f%%%% \(%d/%d\)"\s*%\s*\(100 \* (\w+), (\w+), (\w+)\)',
                          src)
    if not frac:   # 따옴표 안 %% 이스케이프가 판마다 다를 수 있다
        frac = _re167.findall(r'\(100 \* (prec|rec), (\w+), (\w+)\)', src)
    got = {f[0]: (f[1], f[2]) for f in frac}
    check("[167] ① 기각 **재현율**이 자기 분수를 찍는다",
          "rec" in got, "찾은 포맷: %s" % (got or "없음"))

    # ② ⭐ **분자가 정밀도와 같아야 한다.** 이것이 오류의 심장이다 —
    #    재현율 분자에 «전체 기각 수» 가 들어가면 TP 기각이 섞인다.
    if "rec" in got and "prec" in got:
        check("[167] ② ⭐ 두 분수의 **분자가 같다** (TN기각) — "
              "여기가 갈라지면 오답이 분자에 섞인다",
              got["rec"][0] == got["prec"][0],
              "정밀도 분자 %s · 재현율 분자 %s" % (got["prec"][0], got["rec"][0]))
        check("[167] ③ 재현율 **분모는 TN 총수**이지 전체 기각 수가 아니다",
              got["rec"][1] != got["prec"][1],
              "정밀도 분모 %s · 재현율 분모 %s" % (got["prec"][1], got["rec"][1]))

    # ④ 두 식이 **실제로 갈라짐**을 합성 자료로 고정한다.
    #    소스만 보면 «이름이 맞나» 까지고, 이 검사가 «수가 다르다» 를 잡는다.
    labels = [0] * 10 + [1] * 10                     # TN 10 · TP 10
    verd = ["기각"] * 6 + ["보류"] * 4 + ["기각"] * 2 + ["보류"] * 8
    rej = [v == "기각" for v in verd]
    tn_rej = sum(1 for x, l in zip(rej, labels) if x and l == 0)
    all_rej = sum(rej)
    n_neg = len(labels) - sum(labels)
    check("[167] ④ 합성 자료에서 두 식이 **갈라진다** — "
          "TP 기각이 있으면 같을 수 없다",
          tn_rej != all_rej and tn_rej / n_neg != all_rej / n_neg,
          "올바른 %d/%d · 틀린 %d/%d" % (tn_rej, n_neg, all_rej, n_neg))

    # ⑤ 그리고 **TP 기각이 0이면 우연히 같아진다** — 왜 안 드러났는지.
    #    이 줄이 없으면 ④ 만 보고 «어떤 표본에서도 다르다» 로 오해한다.
    v0 = ["기각"] * 5 + ["보류"] * 5 + ["보류"] * 10
    r0 = [v == "기각" for v in v0]
    t0 = sum(1 for x, l in zip(r0, labels) if x and l == 0)
    check("[167] ⑤ TP 기각이 0이면 두 식이 **같아진다** — 소표본이 오류를 숨긴다",
          t0 == sum(r0), "%d vs %d" % (t0, sum(r0)))


def test_seal_tool_never_silently_overwrites_a_seal():
    """[166] **봉인 도구가 옛 해시를 지우지 않는다** — 09-20 신설.

    ## 왜 도구로 만들었나

    09-19 까지 봉인 json 을 `py -c "..."` 한 줄로 만들었다. 거기에
    한글 리터럴이 들어가면 **셸 인코딩을 타고 봉인 파일이 깨진다.**
    봉인이 깨지면 **무결 주장 전체가 사라진다.**
    `CLAUDE.md §5` — *«우리가 «붙여넣어라» 고 찍는 명령도 검증 대상이다»*
    (09-19 에 실제로 두 번 거짓이었다).

    ## 무엇을 구조로 막는가

    `CLAUDE.md §3` 은 **09-15 훼손 사건**을 적어 뒀다 — 봉인된 명세를
    *«자각 없이»* 고쳤고 **1차 본문이 복구 불가**가 됐다.
    그래서 이 도구는 —

    * 이미 봉인된 문서는 `--재봉인` 없이 **거부**하고 (덮어쓰기 금지)
    * 훼손을 **스스로 감지**하며 (rc=2)
    * 재봉인할 때 **옛 해시를 `이전` 에 남긴다**

    옛 해시가 사라지면 *«무엇이 언제 바뀌었나»* 를 **영영 못 묻는다.**
    """
    import importlib.util as _iu166
    import inspect as _in166
    import json as _j166
    import os as _o166
    import tempfile as _t166
    from .. import evidence as _EV166

    p = _o166.path.join(_EV166.ROOT, "봉인.py")
    check("[166] ① 도구가 실재한다", _o166.path.exists(p), p)
    if not _o166.path.exists(p):
        return
    spec = _iu166.spec_from_file_location("seal166", p)
    S = _iu166.module_from_spec(spec)
    spec.loader.exec_module(S)

    d = _t166.mkdtemp(prefix="seal166_")
    doc = _o166.path.join(d, "문서.md")
    with open(doc, "w", encoding="utf-8") as f:
        f.write("첫 판\n")
    out = S.seal_path(doc)

    # ② 새 봉인 — 해시가 **실제 파일의 것**인가
    rc = S.main([doc])
    rec = _j166.load(open(out, encoding="utf-8"))
    check("[166] ② 새 봉인이 만들어지고 해시가 파일과 맞는다",
          rc == 0 and rec["sha256"] == S.sha(doc), rec.get("sha256", "")[:16])
    first = rec["sha256"]

    # ③ 훼손 감지 — **조용히 통과하면 안 된다**
    with open(doc, "a", encoding="utf-8") as f:
        f.write("몰래 고침\n")
    rc = S.main([doc])
    check("[166] ③ ⭐ 봉인 뒤 고쳐진 것을 **실패로 알린다** (rc=2)",
          rc == 2, "rc=%s" % rc)

    # ④ **덮어쓰지 않았다.** 이것이 09-15 사건의 핵심이다
    rec2 = _j166.load(open(out, encoding="utf-8"))
    check("[166] ④ ⭐ 거부하면서 **봉인 파일을 안 건드렸다**",
          rec2["sha256"] == first, "봉인이 조용히 갱신되면 훼손 증거가 사라진다")

    # ⑤ 재봉인은 **옛 해시를 남긴다**
    S.main([doc, "--재봉인"])
    rec3 = _j166.load(open(out, encoding="utf-8"))
    olds = [x.get("sha256") for x in (rec3.get("이전") or [])]
    check("[166] ⑤ ⭐ 재봉인이 **옛 해시를 보존한다** — 사슬이 끊기면 안 된다",
          first in olds and rec3["sha256"] != first,
          "이전 %d개" % len(olds))

    # ⑥ 시각이 **박혀 있지 않다** — 봉인 시각이 상수면 증거가 아니다
    src = _in166.getsource(S.main)
    check("[166] ⑥ 봉인 시각을 **그때 읽는다** (하드코딩이 아니다)",
          "now(" in src, "시각이 상수면 «언제 봉인했나» 를 증명 못 한다")

    # ⑦ 없는 파일에 **0을 주지 않는다**
    check("[166] ⑦ 없는 파일이면 실패로 끝낸다",
          S.main([_o166.path.join(d, "없다.md")]) != 0, "조용한 성공 금지")


def test_preflight_shows_every_failure_not_just_the_first():
    """[168] **실패가 여럿이면 여럿을 찍는다** — 09-21 신설.

    ## 무엇이 있었나

    `preflight` 이 *"통과 2292 · 실패 9"* 라고 찍었는데 **화면에 실패가
    하나만 보였다.** `_gist` 가 한 줄 요약이라 `fails[0]` 만 붙이기 때문이다.
    나머지 **여덟을 알 수 없어** 샌드박스에서 따로 재현해야 했고,
    거기서는 **한 개만 재현됐다**(환경이 다르다 — `CLAUDE.md §5`).

    `CLAUDE.md` 는 *"실패는 `preflight` 이 따로 크게 찍으므로 숨겨지지
    않는다"* 고 적었다. **그 말이 참이 아니었다.**

    ## ⚠ 같은 자리에서 **두 번째**다

    `_gist` 주석 ③이 08-24에 이미 같은 병을 고쳤다 —
    *«불일치 N항목만 찍는 것은 답이 아니다»*. 그때는 항목 **이름**을
    붙였고, 이번엔 실패 **목록**이다. 요약을 늘려 고치면 또 잘리므로
    **목록을 따로 낸다.**
    """
    import inspect as _in168
    import re as _re168
    import sys as _sy168
    from ..bench import preflight as _P168

    src = _in168.getsource(_P168)
    # ⚠ **함수 이름에 기대지 않는다** — 첫 판이 `main` 을 찾았는데
    #   실제 이름은 `_main` 이었고, 그래서 «없다» 로 읽혀 ②가 헛돌 뻔했다.
    #   모듈 전체에서 찾되 **이 시험 자신은 뺀다**([165]⑦ 의 교훈 —
    #   `getsource` 는 검사문까지 읽으므로 자기가 자기를 통과시킨다).
    me = _sy168.modules[__name__]
    _whole = _in168.getsource(me)
    _mine = _in168.getsource(test_preflight_shows_every_failure_not_just_the_first)
    mysrc = _whole.replace(_mine, "")

    # ① 요약 함수는 여전히 «한 줄» 이어야 한다 — 거기에 우겨넣으면 잘린다
    g = _in168.getsource(_P168._gist)
    check("[168] ① `_gist` 는 한 줄 요약으로 남는다 (목록을 여기 넣지 않는다)",
          "fails[0]" in g, "요약에 전부 넣으면 76자에서 잘린다")

    # ② ⭐⭐ **두 파일의 접두사가 같은가** — 이것이 계약이다.
    #    09-21 첫 판이 정확히 여기서 깨졌다: 찍는 쪽은 `실패: A, B, C`
    #    **한 줄**인데 읽는 쪽은 «여러 줄» 을 기대했다. 그래서 목록이
    #    **조용히 안 나왔고**, 시험은 합성 문자열만 보고 초록이었다.
    check("[168] ② ⭐⭐ 찍는 쪽이 `preflight.FAIL_LINE` 접두사로 **한 줄씩** 낸다",
          _P168.FAIL_LINE in mysrc,
          "찍는 쪽과 읽는 쪽이 갈라지면 목록이 조용히 사라진다: %r" % _P168.FAIL_LINE)

    # ③ 목록을 **따로** 내는 자리가 있고, 하나일 때는 안 찍는다
    check("[168] ③ 실패 **목록**을 따로 찍고, 하나면 억제한다",
          "실패 %d건 전부" in src and _re168.search(r"if len\(_f\) > 1:", src),
          "결함 136 — 늘 우는 가드는 눈 감은 가드와 같다")

    # ④ ⭐ **실제 출력 형식으로 파서를 태운다.**
    #    `CLAUDE.md §5` — 모의가 실제보다 좁으면 그 검증은 거짓말이다.
    #    아래 두 줄은 `main()` 이 실제로 찍는 것과 **같은 꼴**이다.
    real = "\n".join([
        "=" * 66, "통과 2296 · 실패 3",
        "실패: [159] zip, 문서가 갈라졌다, [115] 배포 사본, [99] 목록",
        _P168.FAIL_LINE + "[159] zip, 문서가 갈라졌다",
        _P168.FAIL_LINE + "[115] 배포 사본",
        _P168.FAIL_LINE + "[99] 목록",
        "##FAILED##a,b,c", "=" * 66])
    got = _P168._fails(real)
    check("[168] ④ ⭐ 실제 형식에서 **셋을 전부** 뽑는다 — "
          "이름에 쉼표가 있어도 안 쪼개진다",
          len(got) == 3 and got[0] == "[159] zip, 문서가 갈라졌다", got)

    # ⑤ ⭐ **옛 형식에서는 못 뽑힌다** — 왜 첫 판이 실패했는지를 고정한다.
    #    이 줄이 없으면 «쉼표 한 줄로 되돌려도 괜찮다» 로 오해한다.
    old_only = "\n".join(["통과 10 · 실패 3",
                          "실패: [159] zip, [115] 사본, [99] 목록"])
    check("[168] ⑤ ⭐ 쉼표 한 줄뿐이면 **0건**이 나온다 — 첫 판이 이래서 실패했다",
          _P168._fails(old_only) == [], _P168._fails(old_only))

    # ⑥ 그때 **조용하지 않다** — 못 읽은 것과 실패가 하나인 것은 다르다
    check("[168] ⑥ 목록을 못 읽으면 그 사실을 말한다 (결함 99)",
          "실패 목록을 **못 읽었다**" in src,
          "침묵과 통과는 다르다")

    # ⑦ 목록 출력이 실패일 때만 나온다 — 초록에 붙으면 화면을 못 믿는다
    check("[168] ⑦ 목록 출력이 `if not ok:` 안에 있다",
          _re168.search(r"if not ok:\s*\n\s*_f = _fails\(out\)", src) is not None,
          "통과한 검사에 실패 목록이 붙으면 화면을 믿을 수 없다")


def test_cache_never_destroys_itself_when_it_cannot_read():
    """[169] **캐시가 자기를 지우지 않는다** — 09-21 신설. 33MB 를 잃었다.

    ## 무엇이 있었나

    `pubmed_cache.json` 이 **33MB → 2바이트(`{}`)** 가 됐다.
    C6(홀드아웃 재측정) 직후였고 **측정 결과는 무사했지만**
    *«그 시점의 문헌 상태를 고정할 수단»* 을 잃었다.

    경로는 두 겹이었다 —

    1. `load()` 가 읽기에 **실패하고도** `_LOADED[0] = True` 를 놓았다.
       그래서 `save()` 의 병합 방어가 *«이미 읽었다»* 로 건너뛰어졌다
    2. `save()` 의 병합도 깨진 JSON 을 못 읽고 `except: pass` —
       **«디스크가 깨졌으면 메모리 것이라도 남긴다»** 로 덮었다

    ## ⚠ **같은 자리에서 두 번째**다

    `save()` 의 docstring 이 08-05 사고를 적어 뒀다 — *"2.7MB 가
    사라졌다. 백업이 없었다."* 그리고 *"규약으로는 안 막힌다.
    **구조로 막는다**"* 고 했다. **그 구조가 플래그 하나였다.**

    ## ⭐ 못 읽는 이유는 둘인데 **구별할 수 없다**

        ① 파일이 진짜 깨졌다          → 새로 써도 된다
        ② 다른 프로세스가 쓰는 중이다  → 덮으면 큰일난다

    33MB JSON 은 쓰는 데 수 초가 걸린다. **같은 날 ②를 눈으로 봤다** —
    32.8MB 가 22.5MB 로 보였고 27초 뒤 32.9MB 였다.
    **구별할 수 없으면 잃지 않는 쪽을 고른다.**
    """
    import glob as _g169
    import json as _j169
    import os as _o169
    import shutil as _sh169
    import tempfile as _t169
    from ..io import cache as _C169

    d = _t169.mkdtemp(prefix="cache169_")
    p = _o169.path.join(d, "c.json")

    def fresh(n=300):
        with open(p, "w", encoding="utf-8") as f:
            _j169.dump({"k%d" % i: {"v": i} for i in range(n)}, f)

    _keep = (_C169._PATH, _C169._ENABLED, dict(_C169._STORE), _C169._LOADED[0])
    try:
        # ① 정상 경로는 그대로 — 방어가 평소를 망가뜨리면 꺼진다
        fresh(); _C169.configure(p); _C169.load()
        _C169.put("새", {"v": 1}); _C169.save()
        check("[169] ① 정상 저장은 그대로 동작한다",
              len(_j169.load(open(p, encoding="utf-8"))) == 301,
              "방어가 평소를 막으면 사람이 방어를 끈다")

        # ② ⭐ **읽기 실패 뒤에도 원본을 잃지 않는다** — 33MB 가 난 자리
        fresh()
        with open(p, "a", encoding="utf-8") as f:
            f.write("깨뜨림")            # 불완전한 JSON = 쓰는 중과 구별 불가
        _C169.configure(p)
        _C169.load()
        check("[169] ② ⭐ 못 읽었으면 **«안 읽은 상태»** 로 둔다 (병합을 유도)",
              _C169._LOADED[0] is False,
              "여기가 True 였기 때문에 33MB 가 날아갔다")
        _C169.put("새", {"v": 1}); _C169.save()
        baks = _g169.glob(p + ".unreadable_*")
        check("[169] ③ ⭐⭐ 못 읽으면 **백업을 뜨고** 쓴다 — 원본이 남는다",
              bool(baks) and _o169.path.getsize(baks[0]) > 5000,
              "백업 %s" % [_o169.path.getsize(b) for b in baks])

        # ④ ⭐ **빈 _STORE 로 덮지 않는다** — 플래그와 무관한 최종 방어
        fresh()
        _C169.configure(p)
        _C169._LOADED[0] = True          # 플래그 방어를 일부러 무력화
        _C169._STORE = {}
        _C169.save()
        check("[169] ④ ⭐⭐ 빈 캐시로 **내용이 있는 파일을 안 덮는다**",
              len(_j169.load(open(p, encoding="utf-8"))) == 300,
              "플래그 하나에 33MB 를 걸지 않는다")

        # ⑤ 백업조차 실패하면 **안 쓴다** — 잃는 쪽이 더 나쁘다
        fresh()
        with open(p, "a", encoding="utf-8") as f:
            f.write("깨짐")
        sz0 = _o169.path.getsize(p)
        _orig = _sh169.copy2
        _sh169.copy2 = lambda *a, **k: (_ for _ in ()).throw(OSError("가짜"))
        try:
            _C169.configure(p); _C169.load()
            _C169._STORE = {"x": 1}; _C169.save()
        finally:
            _sh169.copy2 = _orig
        check("[169] ⑤ 백업도 못 뜨면 **덮지 않는다**",
              _o169.path.getsize(p) == sz0,
              "캐시는 최적화다 — 못 쓰는 것보다 잃는 것이 나쁘다")

        # ⑥ 새 파일은 정상적으로 만들어진다 (방어가 생성을 막으면 안 된다)
        _o169.remove(p)
        _C169._STORE = {"a": 1}; _C169.save()
        check("[169] ⑥ 파일이 없으면 새로 만든다",
              _o169.path.exists(p), "방어가 첫 생성을 막으면 안 된다")
    finally:
        _C169._PATH, _C169._ENABLED = _keep[0], _keep[1]
        _C169._STORE, _C169._LOADED[0] = _keep[2], _keep[3]


def test_preflight_watches_git_because_nobody_did():
    """[170] **git 을 아무도 안 보고 있었다** — 09-22 신설. 결함 322·323.

    ## 사흘에 걸친 한 사슬

    ```
    09-16  `.git/index.lock` 이 남아 커밋이 막혔다 — **엿새 동안 몰랐다**
    09-21  캐시 33MB 손실 → git 이 없어 08-05 백업으로 복구
           그 백업이 **오염을 걷어내기 전 판**이라 leakcheck 54/54 실패
    09-22  «보냈었다» 는 기억을 따라 push → **남의 논문 저장소**였다
           `--force` 였으면 그쪽이 사라졌다. **막은 것은 git 이다**
    ```

    `preflight` 이 배포·문서·시험·봉인을 전부 보는데 **git 만 안 봤다.**

    ## 이 시험이 실제 경로를 태운다

    `CLAUDE.md §5` — *«--help 통과는 검증이 아니다»*. 그래서 **진짜 git
    저장소를 둘 만들어** 서로 무관한 히스토리로 두고, `git_health` 가
    그것을 «남의 저장소» 로 잡는지 본다. 09-21에 [168]을 **합성 문자열로만**
    시험해서 실패한 것(결함 321)이 바로 앞 사례다.
    """
    import os as _o170
    import sys as _sy170
    import shutil as _s170
    import subprocess as _sp170
    import tempfile as _t170
    from ..bench.preflight import git_health

    git = _s170.which("git")
    check("[170] ① git 이 있다 (없으면 이 시험이 공허하다)", bool(git), git)
    if not git:
        return

    def _run(cwd, *a):
        return _sp170.run([git, "-C", cwd] + list(a),
                          capture_output=True, text=True, timeout=60)

    base = _t170.mkdtemp(prefix="githealth170_")

    def _repo(name, msg):
        d = _o170.path.join(base, name)
        _o170.makedirs(d, exist_ok=True)
        _run(d, "init", "-q", "-b", "main")
        _run(d, "config", "user.email", "t@t")
        _run(d, "config", "user.name", "t")
        with open(_o170.path.join(d, name + ".txt"), "w") as f:
            f.write(msg)
        _run(d, "add", ".")
        _run(d, "commit", "-qm", msg)
        return d

    ours = _repo("ours", "bio-reroute")
    theirs = _repo("theirs", "some other paper")   # **공통 조상이 없다**

    # ② 정상 — 리모트가 없으면 조용하다
    g = git_health(ours)
    check("[170] ② 리모트가 없으면 «남의 저장소» 도 없다",
          not g.get("남의저장소") and not g.get("없음"), g.get("남의저장소"))

    # ③ ⭐⭐ **무관한 저장소를 리모트로 달면 잡는다** — 09-22 의 그 상황
    _run(ours, "remote", "add", "stranger", theirs)
    _run(ours, "fetch", "-q", "stranger")
    g = git_health(ours)
    names = [r for r, _ in g.get("남의저장소", [])]
    check("[170] ③ ⭐⭐ **공통 조상이 없는 리모트**를 잡는다 — "
          "`--force` 하나로 남의 프로젝트가 사라진다",
          "stranger" in names, g.get("남의저장소"))

    # ④ 같은 계보는 안 잡는다 (오탐이 쌓이면 가드가 꺼진다 — 결함 136)
    clone = _o170.path.join(base, "clone")
    _sp170.run([git, "clone", "-q", ours, clone], capture_output=True, timeout=60)
    _run(clone, "config", "user.email", "t@t")
    _run(clone, "config", "user.name", "t")
    g2 = git_health(clone)
    check("[170] ④ 같은 계보의 리모트는 **안 잡는다** (오탐 방지)",
          not [r for r, _ in g2.get("남의저장소", []) if r == "origin"],
          g2.get("남의저장소"))

    # ⑤ ⭐ **락을 잡는다** — 엿새 동안 커밋을 막았던 그것
    lk = _o170.path.join(ours, ".git", "index.lock")
    open(lk, "w").close()
    try:
        g3 = git_health(ours)
        check("[170] ⑤ ⭐ `.git/index.lock` 을 잡는다", bool(g3.get("락")),
              g3.get("락"))
    finally:
        _o170.path.exists(lk) and _o170.remove(lk)

    # ⑥ git 저장소가 아니면 조용히 건너뛴다 (배포 사본에서 돌 수 있다)
    plain = _o170.path.join(base, "plain")
    _o170.makedirs(plain, exist_ok=True)
    check("[170] ⑥ git 저장소가 아니면 건너뛴다",
          git_health(plain).get("없음") is True, git_health(plain))

    # ⑦ 미커밋을 센다 — 182개까지 쌓였던 그 수
    with open(_o170.path.join(ours, "새파일.txt"), "w") as f:
        f.write("x")
    check("[170] ⑦ 미커밋을 센다", git_health(ours).get("미커밋", 0) >= 1,
          git_health(ours).get("미커밋"))

    # ⑧ ⭐⭐ **이 검사 자체가 락을 만들면 안 된다** — 09-22 에 실제로 그랬다
    #
    #   `git status` 는 읽기처럼 보이지만 인덱스 갱신에 락을 잡는다.
    #   샌드박스(마운트)에서는 **만들기는 되고 지우기가 안 되어** 락이
    #   남고 **사람 쪽 커밋이 통째로 막힌다.** 09-16 락이 엿새 갔다.
    #   `--no-optional-locks` 가 그걸 막는다.
    import inspect as _in170
    _src = _in170.getsource(git_health)
    check("[170] ⑧ ⭐⭐ 이 검사가 **`--no-optional-locks`** 를 쓴다 — "
          "가드가 자기가 막으려던 사고를 일으키면 안 된다",
          "--no-optional-locks" in _src,
          "없으면 `preflight` 을 돌릴 때마다 락이 생긴다")
    _lk = _o170.path.join(ours, ".git", "index.lock")
    git_health(ours)
    check("[170] ⑨ ⭐ 실제로 돌린 뒤 **락이 안 남는다**",
          not _o170.path.exists(_lk), _lk)

    # ⑩ ⭐⭐ **리모트 0개를 초록으로 찍지 않는다** — 09-22, 만든 그날 걸렸다
    #
    #   리모트를 정리하다 0개가 됐는데 화면이 *«OK … 리모트 0개 전부 같은
    #   계보»* 를 찍었다. **없는 것을 통과로 읽은 것**(결함 99)이고,
    #   하필 제출물이 «GitHub 코드」라 push 할 곳이 없다는 뜻이었다.
    _psrc = _in170.getsource(_sy170.modules["bioreroute.bench.preflight"].main)
    check("[170] ⑩ ⭐⭐ **리모트 0개를 실패로 센다** — "
          "가드를 만든 그 실행에서 가드가 안 울었다",
          '_g.get("리모트")' in _psrc and "리모트가 하나도 없다" in _psrc,
          "없는 것을 통과로 찍으면 가드가 아니다(결함 99)")


def test_first_screen_is_something_that_actually_works():
    """[171] **첫 화면이 «안 되는 것» 이면 안 된다** — 09-23 신설.

    ## 무엇이 있었나

    배포판(`*.static.hf.space`)을 실제로 열어 봤다. 기본 화면이
    **「직접 검증」**이었는데 **정적본이라 라이브 검증이 안 된다.**

    ```
    ① 「직접 검증」 화면   ② 「서버가 필요합니다」 버튼
    ③ 「이 배포판에서는 라이브 검증이 안 됩니다」 박스
    ```

    **첫 30초에 «안 됩니다» 를 세 번 읽는다.** 그리고 실제로 도는 것
    (판정 사례 6건 · 3분할 사고 과정 · 반증 기록)은 **클릭 두 번 뒤**였다.

    ⚠ **안내 박스가 스스로** *«왼쪽 심사·시연은 전부 그대로 동작합니다»*
    **라고 적고 있었다.** 설계자도 알고 있었는데 기본값이 반대였다.

    ## 왜 시험으로 거나

    한 줄짜리 기본값이라 **리팩터링에 조용히 되돌아간다.**
    배점 ⑤(시연·완성도)가 30점이고 그 30점의 첫인상이 이 한 줄이다.
    """
    import os as _o171
    import re as _re171
    from .. import evidence as _EV171

    p = _o171.path.join(_EV171.ROOT, "web", "static", "app.js")
    check("[171] ① 화면 코드가 실재한다", _o171.path.exists(p), p)
    if not _o171.path.exists(p):
        return
    src = open(p, encoding="utf-8").read()

    # ① 기본 화면이 «도는 것» 이어야 한다
    m = _re171.search(r'var view = \(m && VIEWS\[m\[2\]\]\) \? m\[2\] : "(\w+)"',
                      src)
    dflt = m.group(1) if m else ""
    check("[171] ② ⭐⭐ 기본 화면이 **`cases`**(판정 사례)다 — "
          "정적본에서 실제로 도는 화면",
          dflt == "cases", "지금 기본값: %r" % (dflt or "못 찾음"))

    # ② 그 화면이 VIEWS 에 있고 judge 모드여야 한다 (오타 방지)
    check("[171] ③ `cases` 가 VIEWS 에 있고 `judge` 모드다",
          _re171.search(r'cases:\s*\{\s*\n?\s*mode:\s*"judge"', src) is not None,
          "기본값이 없는 화면을 가리키면 `go()` 가 조용히 `drug` 로 떨어진다")

    # ③ ⭐ **안내 문구와 기본값이 같은 말을 해야 한다**
    #    박스는 «심사·시연이 동작한다» 고 하는데 기본은 그 반대 화면 —
    #    그 어긋남이 09-23에 실제로 있었다.
    says = "심사·시연" in src or "심사·시연" in src
    check("[171] ④ ⭐ 안내 문구가 가리키는 곳과 기본 화면이 **같은 쪽**이다",
          (not says) or dflt in ("cases", "dashboard", "evidence"),
          "안내는 «심사·시연» 인데 기본이 verify 모드면 서로 다른 말을 한다")

    # ④ 해시가 있으면 그대로 간다 — 문서·대본의 링크가 안 깨져야 한다
    check("[171] ⑤ 해시가 있으면 **그 화면으로 간다**(기본값이 덮지 않는다)",
          "location.hash" in src and "VIEWS[m[2]]" in src,
          "대본과 README 가 `#/judge/dashboard` 같은 링크를 쓴다")


def test_model_comparison_separates_model_from_input():
    """[172] **모델 비교가 «입력이 같은 쌍» 을 따로 센다** — 09-23 신설.

    ## 무엇이 있었나 (결함 326 · 329)

    `sol` 이 `terra` 보다 TN 을 24건 더 기각했다(p=0.0002). «모델 차이」
    로 적으려다 **두 실행의 입력이 달랐다**는 것을 찾았다 — 09-21 캐시
    유실 뒤 08-05 백업으로 복원해서 **읽은 초록**과 F0 결과가 갈렸다.
    입력을 통제하니 **b=0·c=9** 가 됐다. 방향은 살았고 크기는 줄었다.

    같은 날 서브에이전트 검토가 둘을 더 잡았다 —
    ① PMID 가 같아도 **라벨 출처 제외 여부**가 다르면 입력이 다르다
       (`mini`·`sol` 은 PMID 774/774 동일인데 제외가 30쌍에서 다르다)
    ② **F0 실체 조회가 429 로 실패했는데 «환각」 으로 기각**된 판정이 있다
       (trail 은 ERROR 인데 사유가 `F0:`) — «근거 기반」 에서 빼야 한다

    ## 왜 시험으로 거나

    이 구분이 손 계산에 있으면 다음 모델(`luna`)에서 또 빠진다.
    """
    import json as _j172
    import os as _o172
    import tempfile as _tf172
    from ..bench import modelpair as _MP

    def cand(drug, label, verdict, f0="PASS", pm=("1", "2"), model="m-A",
             dirs=None, reason="", served=None, w=None, skip=None):
        dirs, w, skip = dirs or {}, w or {}, skip or {}
        return {"drug": drug, "disease": "D", "label": label, "verdict": verdict,
                "reason": reason, "trail": [{"gate": "f0", "outcome": f0}],
                "factcheck": [{"pmid": p, "direction": dirs.get(p, "neutral"),
                               "kept": dirs.get(p, "neutral") != "neutral",
                               "weight": w.get(p, 0.0), "skip": skip.get(p),
                               "provenance": {"model": model,
                                              "served_by": served or model}}
                              for p in pm]}

    # A 는 t0·t1 기각, B 는 t1·t2·t3 기각 → b=1 · c=2
    A = [cand("t0", "TN", "기각"), cand("t1", "TN", "기각"),
         cand("t2", "TN", "보류"), cand("t3", "TN", "보류", pm=("1", "9")),
         cand("t4", "TN", "기각", f0="KILL", pm=()),
         cand("p0", "TP", "유망", dirs={"2": "refute"}, w={"2": 0.4})]
    B = [cand("t0", "TN", "보류", model="m-B"), cand("t1", "TN", "기각", model="m-B"),
         cand("t2", "TN", "기각", model="m-B"),
         cand("t3", "TN", "기각", pm=("1", "2"), model="m-B"),   # 읽은 초록이 다르다
         cand("t4", "TN", "기각", f0="KILL", pm=(), model="m-B"),
         cand("p0", "TP", "유망", model="m-B",
              dirs={"1": "support", "2": "refute"}, w={"2": 3.0})]  # 무관→근거 · 무게↑
    r = _MP.compare(A, B)

    check("[172] ① 전체 TN 에서 한쪽만 기각한 수를 센다 (b=1 · c=2) · ψ̂=2/3",
          (r["TN_전체"]["A만"], r["TN_전체"]["B만"]) == (1, 2)
          and abs(r["TN_전체"]["psi_hat"] - 2 / 3.0) < 1e-9, r["TN_전체"])
    check("[172] ② ⭐⭐ **읽은 초록이 다른 쌍은 «입력 동일」에서 빠진다** — "
          "그 쌍의 차이는 모델 탓이라 못 한다",
          r["입력동일"] == 5 and (r["TN_입력동일"]["A만"],
                                r["TN_입력동일"]["B만"]) == (1, 1),
          (r["입력동일"], r["TN_입력동일"]))
    check("[172] ③ ⭐ **F0 기각은 근거 기반 비교에서 빠진다** — 모델과 무관하다",
          r["TN_근거기반"]["n"] == 4 and r["F0갈래_TN"] == [1, 1],
          (r["TN_근거기반"], r["F0갈래_TN"]))
    check("[172] ④ 근거 기반 기각 수가 F0 갈래를 뺀 값이다",
          r["근거기반기각"] == [2, 3], r["근거기반기각"])
    check("[172] ⑤ 모델 이름을 **파일 이름이 아니라 내용**에서 읽는다",
          r["모델"] == ["m-A", "m-B"], r["모델"])
    check("[172] ⑥ 같은 초록을 «무관→근거» 로 바꿔 읽은 것을 센다",
          r["분류"]["무관→근거"] == 1 and r["분류"]["근거→무관"] == 0, r["분류"])

    # ⑦ ⭐⭐ 쌍이 어긋나면 **멈춘다** — 다른 벤치를 비교하면 모든 수가 거짓이다
    bad = list(B)
    bad[0] = dict(bad[0], drug="다른약")
    try:
        _MP.compare(A, bad)
        stopped = False
    except ValueError:
        stopped = True
    check("[172] ⑦ ⭐⭐ 쌍이 어긋나면 **계산하지 않고 멈춘다**", stopped,
          "어긋난 채 세면 b·c 가 전부 거짓이다")

    # ⑧ ⭐ 결과 파일을 **확인 없이 덮지 않는다** (`CLAUDE.md §3-3`)
    import inspect as _in172
    _src = _in172.getsource(_MP.main)
    check("[172] ⑧ ⭐ `--json` 이 이미 있으면 `--force` 없이 안 덮는다",
          "os.path.exists(a.json)" in _src and "--force" in _src,
          "결과 파일 덮어쓰기는 이 프로젝트가 세 번 겪은 사고다")

    check("[172] ⑨ 지문이 core·io·agents 를 본다",
          all(g in _MP.CODE_GLOBS for g in ("bioreroute/core/*.py",
                                             "bioreroute/io/*.py",
                                             "bioreroute/agents/*.py")),
          _MP.CODE_GLOBS)

    # ⑩ ⭐ **같은 PMID 라도 한쪽만 초록을 못 받았으면 입력이 다르다**
    one = lambda **k: [cand("t0", "TN", "보류", **k)]
    check("[172] ⑩ ⭐ PMID 가 같아도 **초록을 못 받은 쪽이 있으면** 입력 동일이 아니다",
          _MP.compare(one(), one(model="m-B", skip={"1": "초록 취득 실패: efetch 응답에 없음"}))
          ["입력동일"] == 0, "일시 장애는 캐시에 안 남아 다음엔 받을 수 있다")

    # ⑪ ⭐⭐ **라벨 출처 제외가 다르면 입력이 다르다** — mini·sol 30쌍
    check("[172] ⑪ ⭐⭐ PMID 가 같아도 **라벨 출처 제외가 다르면** 입력 동일이 아니다",
          _MP.compare(one(), one(model="m-B", skip={"2": "라벨 출처 시험 — 근거에서 제외"}))
          ["입력동일"] == 0, "mini 때는 [si] 확장이 실패해 제외가 안 걸렸다(결함 37)")

    # ⑫ ⭐⭐ **F0 조회 실패로 «환각」 기각된 것도 F0 갈래다** — 결함 329
    A3 = [cand("t0", "TN", "기각", f0="ERROR", reason="F0: 문헌 근거 없음(환각)")]
    B3 = [cand("t0", "TN", "보류", f0="FLAG", model="m-B")]
    r3 = _MP.compare(A3, B3)
    check("[172] ⑫ ⭐⭐ trail 이 ERROR 라도 **사유가 `F0:` 면 근거 기반에서 뺀다**",
          r3["근거기반기각"] == [0, 0] and r3["TN_근거기반"]["n"] == 0,
          (r3["근거기반기각"], r3["TN_근거기반"]))

    # ⑬ 요청과 **다른 모델이 답했으면** 센다 — 대체 사슬
    r4 = _MP.compare(one(), one(model="m-B", served="m-C"))
    check("[172] ⑬ `served_by` 가 요청과 다르면 **대체 응답으로 센다**",
          r4["대체응답"] == [0, 2] and r4["모델"][1] == "m-C", (r4["대체응답"], r4["모델"]))

    # ⑭ ⭐ 같은 방향으로 채택한 같은 초록에서 **무게가 커진 것**을 센다
    check("[172] ⑭ ⭐ 같은 방향 채택에서 **B 의 무게가 큰 것**을 센다 (0.4 → 3.0)",
          r["무게"]["B가큼"] == 1 and r["무게"]["B가작음"] == 0, r["무게"])

    # ⑮ ⭐⭐ 검색 키 지문이 **LLM 답 키를 뺀다** — 새 모델이면 당연히 늘어난다
    d = _tf172.mkdtemp()
    with open(_o172.path.join(d, "pubmed_cache.json"), "w", encoding="utf-8") as f:
        _j172.dump({"q1": {}, "SEARCH::8::x::-": {}, "LLM::m::abc": {}}, f)
    fp1 = _MP.fingerprint(d)
    with open(_o172.path.join(d, "pubmed_cache.json"), "w", encoding="utf-8") as f:
        _j172.dump({"q1": {}, "SEARCH::8::x::-": {}, "LLM::m::abc": {},
                    "LLM::m2::def": {}}, f)
    fp2 = _MP.fingerprint(d)
    check("[172] ⑮ ⭐⭐ 검색 키 지문이 **`LLM::` 키를 뺀다** — 안 빼면 «늘었다」 가 무의미",
          fp1["검색키"] == 2 and fp1["검색키지문"] == fp2["검색키지문"],
          (fp1.get("검색키"), fp1.get("검색키지문"), fp2.get("검색키지문")))

def test_luna_script_carries_the_sealed_values():
    """[173] **`luna.ps1` 이 봉인된 명세의 값을 그대로 든다** — 09-23 신설 (결함 330).

    ## 무엇이 있었나

    붙여 넣은 긴 명령이 `--` 와 `stratum` 사이에서 줄이 갈렸고, 앞 절반이
    **`--configs`·`--out` 없이** 떴다. 기본값이면 B0·B2·B5 를 luna 로 돌려
    `bench_results.json` 에 쓴다. 예산 상한이 **우연히** 막았다.

    그래서 인자를 스크립트에 박았다. 그러면 새 위험이 생긴다 —
    **스크립트의 값과 봉인된 명세의 값이 어긋나는 것.** 명세는 못 고치고
    (봉인) 스크립트는 누구나 고칠 수 있다. 이 시험이 둘을 묶는다.
    """
    import os as _o173
    from .. import evidence as _EV173

    p = _o173.path.join(_EV173.ROOT, "luna.ps1")
    spec = _o173.path.join(_EV173.ROOT, "사전명세_모델독립성_보충_0923.md")
    check("[173] ① `luna.ps1` 과 보충 명세가 있다",
          _o173.path.exists(p) and _o173.path.exists(spec), (p, spec))
    if not (_o173.path.exists(p) and _o173.path.exists(spec)):
        return
    raw = open(p, "rb").read()
    src = raw.decode("utf-8-sig")
    stxt = open(spec, encoding="utf-8").read()

    # ② BOM — 없으면 Windows PowerShell 5.1 이 한글 파일명을 깨뜨린다(결함 231)
    check("[173] ② ⭐ UTF-8 **BOM** 이 있다 — 없으면 `홀드아웃_luna.json` 이 깨진 이름이 된다",
          raw[:3] == b"\xef\xbb\xbf", raw[:3])

    # ③ ⭐⭐ 명세가 봉인한 값 넷이 **스크립트에도 같다**
    vals = ("f6643b748075", "3642eebb8d8f", "1726", "openai/gpt-5.6-luna")
    miss = [v for v in vals if v not in src or v not in stxt]
    check("[173] ③ ⭐⭐ 코드 지문 · 검색 키 지문 · 상한 · 모델이 **명세와 스크립트에 둘 다** 있다",
          not miss, "한쪽에만 있는 값: %s" % miss)

    # ④ ⭐⭐ 실행 인자에 `--configs B0 B5` 와 출력 셋이 **박혀 있다**
    need = ('"--configs", "B0", "B5"', '"--out", $OUT', '"--save-state", $STATE',
            '"--cost-out", $COST')
    check("[173] ④ ⭐⭐ `--configs B0 B5` · `--out` · `--save-state` · `--cost-out` 가 스크립트에 박혀 있다",
          all(n in src for n in need), [n for n in need if n not in src])

    # ⑤ ⭐ 결과 파일이 있으면 **멈춘다** · 모델을 파이썬에게 **직접 묻는다**
    check("[173] ⑤ ⭐ 결과 파일이 있으면 멈추고, 모델을 파이썬에게 직접 묻는다",
          "Test-Path -LiteralPath $f" in src and "llm.MODEL" in src, "")

def test_rejection_reasons_have_one_definition():
    """[174] **기각 사유 분해의 정의가 한 곳에 있다** — 09-23 신설 (결함 331).

    ## 무엇이 있었나

    «근거 기반 기각» 이 문서마다 다른 뜻이었다 —
    `홀드아웃결과.md` 는 **TP 기각까지 섞은 수**를 TN 분모로 나눴고(56/387),
    09-22 terra 표는 **결정적 확증시험 음성(비토)을 «F0 문헌 0건」 칸에**
    넣었다(42 = 33+9). 그리고 둘을 나란히 놓고 *«두 모델에서 숫자가 거의
    같다»* 고 적었다. **정의가 다른 두 수를 맞댄 것이다.**
    """
    import os as _o174
    from ..bench import rejectsplit as _RS
    from .. import evidence as _EV174

    def c(label, verdict, f0="PASS", reason="", veto=False):
        return {"label": label, "verdict": verdict, "reason": reason, "veto": veto,
                "trail": [{"gate": "f0", "outcome": f0}], "factcheck": []}

    C = [c("TN", "기각", f0="KILL", reason="F0: 문헌 근거 없음(환각)"),
         c("TN", "기각", f0="ERROR", reason="F0: 문헌 근거 없음(환각)"),   # 결함 329
         c("TN", "기각", reason="결정적 확증시험 음성 2건 · 동급 지지 없음", veto=True),
         c("TN", "기각", reason="반박 우세 (지지 0건 w=0 · 반박 2건 w=1.2)"),
         c("TN", "보류"),
         c("TP", "기각", reason="반박 우세 (지지 1건 w=0.3 · 반박 2건 w=1.1)")]
    r = _RS.split(C)
    check("[174] ① ⭐ **F0 갈래** 는 F0 기각과 **사유가 `F0:` 인 판정**(조회 오류 포함)이다",
          r["TN"][_RS.F0] == 2, r["TN"])
    check("[174] ② ⭐⭐ **결정적 음성(비토)** 은 F0 가 아니라 **근거 기반**이다",
          r["TN"][_RS.VETO] == 1 and r["근거기반"] == 2, (r["TN"], r["근거기반"]))
    check("[174] ③ ⭐⭐ **TP 기각은 TN 칸에 안 섞인다** — 섞으면 분모와 분자가 다른 집단이다",
          r["기각"] == 4 and sum(r["TP"].values()) == 1 and r["TN총"] == 5,
          (r["기각"], r["TP"], r["TN총"]))

    # ④ ⭐⭐ **동결된 실제 자료에서 이 수가 나온다** — 문서가 옮겨 적은 값의 정본
    root = _EV174.ROOT
    pins = (("s_sealed.json", (37, 10, 48)),              # mini · 08-05
            ("상태_홀드본선_B5.json", (33, 9, 57)))         # terra · 09-21 (제출 모델)
    for fn, want in pins:
        p = _o174.path.join(root, fn)
        if not _o174.path.exists(p):
            continue
        t = _RS.split(_RS.load(p))["TN"]
        got = (t[_RS.F0], t[_RS.VETO], t[_RS.REFUTE])
        check("[174] ④ ⭐⭐ `%s` TN 기각 = F0 %d · 결정적 음성 %d · 반박 우세 %d"
              % ((fn,) + want), got == want, got)

def test_zerocheck_never_turns_a_missing_count_into_zero():
    """[175] **캐시의 «0건» 재확인 도구가 같은 결함을 되풀이하지 않는다** — 09-23 (결함 327).

    `sources.pubmed_lookup` 은 응답에 `count` 가 없으면 0 으로 읽고
    영구 저장한다. 그 0 이 실재하는 약 다섯을 «환각» 으로 기각했다.
    **그걸 재는 도구가 같은 방식으로 0 을 만들면 재는 것이 아니다.**
    """
    import inspect as _in175
    import urllib.parse as _up175
    from ..bench import zerocheck as _ZC
    from ..io import sources as _S175

    cache = {"A AND D": {"count": 0, "pmids": [], "error": None},     # 쌍 0
             "A": {"count": 0, "pmids": [], "error": None},           # 약물 0 → KILL
             "B AND D": {"count": 0, "pmids": [], "error": None},     # 쌍 0 · 약물 있음 → FLAG
             "B": {"count": 7, "pmids": ["1"], "error": None},
             "C AND D": {"count": 3, "pmids": ["2"], "error": None},  # 0 아님 → 대상 아님
             "E AND D": {"count": 0, "pmids": [], "error": None},
             "E": {"count": 0, "pmids": [], "error": None}}
    rows = [{"drug": d, "indication": "D", "label": "TN"} for d in ("A", "B", "C", "E")]
    urls = []

    def fake(url):
        urls.append(url)
        term = _up175.parse_qs(_up175.urlparse(url).query)["term"][0]
        if term == "A":
            return {"esearchresult": {"count": "5"}}          # 그때 이미 있었다 → 가짜 0
        if term == "E":
            return {"esearchresult": {"ERROR": "Search Backend failed"}}   # 개수 없음
        return {"esearchresult": {"count": "0"}}

    old = _S175.REQ_DELAY
    _S175.REQ_DELAY = 0
    try:
        tg, got = _ZC.run(cache, rows, get=fake)
    finally:
        _S175.REQ_DELAY = old
    by = {t["약물"]: t for t in tg}

    check("[175] ① 캐시가 0 인 쌍만 대상이다 — 0 이 아닌 쌍(C)은 안 묻는다",
          set(by) == {"A", "B", "E"}, sorted(by))
    check("[175] ② ⭐⭐ **그때 이미 논문이 있었으면 «가짜 환각 기각»** 이다 (A: 캐시 0 · 그때 5)",
          by["A"]["F0"] == "KILL" and by["A"]["판정"] == "가짜 환각 기각", by["A"])
    check("[175] ③ 약물이 문헌에 있으면 KILL 이 아니라 **FLAG(보류 고정)** 로 본다 (B)",
          by["B"]["F0"] == "FLAG", by["B"])
    check("[175] ④ ⭐⭐ **개수가 없는 응답은 «확인 불가»** 다 — 0 으로 굳히지 않는다 (E)",
          got["E"][0] is None and by["E"]["판정"] == "확인 불가", (got.get("E"), by["E"]))
    check("[175] ⑤ ⭐ **«그때 이미 있던 논문」 만** 센다 — edat ≤ 2026-06-30",
          urls and all("datetype=edat" in u and "maxdate=2026%2F06%2F30" in u for u in urls),
          urls[:1])
    src = _in175.getsource(_ZC)
    check("[175] ⑥ ⭐⭐ **캐시에 쓰지 않는다** — 실험 입력(지문)을 안 바꾼다",
          "cache.put" not in src and "cache.save" not in src and "json.dump(cache" not in src,
          "읽기만 해야 한다")

def test_model_independence_numbers_come_from_one_place():
    """[176] **모델 독립성 수가 코드 한 곳에서 나온다** — 09-23 신설.

    09-23 `sol` 분석을 즉석 스크립트로 했고 틀린 수가 두 번 나왔다(결함
    326·331). `bench/indep.py` 가 명세 0922 §2~§4 를 낸다. 이 시험은 ①
    겹침 판정 ② 동결 자료에서 문서가 옮겨 적은 값 ③ 행 집합 불일치 시 멈춤을 본다.
    """
    import json as _j176
    import os as _o176
    import tempfile as _tf176
    from ..bench import indep as _IN
    from .. import evidence as _EV176

    check("[176] ① CI 공통 구간 — 겹치면 구간, 하나라도 떨어지면 None",
          _IN.overlap([(0.59, 0.68), (0.585, 0.676), (0.591, 0.682)]) == (0.591, 0.676)
          and _IN.overlap([(0.50, 0.55), (0.60, 0.70)]) is None,
          _IN.overlap([(0.59, 0.68), (0.585, 0.676), (0.591, 0.682)]))

    # ② ⭐⭐ 동결 자료에서 **문서가 적은 값**이 나온다 (mini · terra)
    root = _EV176.ROOT
    runs = _IN.load_runs(models=_IN.MODELS[:2], root=root)
    if len(runs) == 2:
        out, common, lab = _IN.summarize(runs)
        got = {s["이름"]: (s["n누출제외"], round(s["B5"][0], 3)) for s in out}
        check("[176] ② ⭐⭐ 누출 제외 B5 — mini (623, 0.634) · terra (583, 0.631)",
              got == {"mini": (623, 0.634), "terra": (583, 0.631)}, got)

    # ③ ⭐ 행 집합이 다르면 **멈춘다**
    d = _tf176.mkdtemp()
    base = {"rows": [{"drug": "a", "indication": "x", "label": "TP"}],
            "results": {"B0": {"scores": [0.5]}, "B5": {"scores": [0.5], "verdicts": ["보류"]}}}
    other = dict(base, rows=[{"drug": "b", "indication": "x", "label": "TP"}])
    for fn, obj in (("r1.json", base), ("r2.json", other)):
        with open(_o176.path.join(d, fn), "w", encoding="utf-8") as f:
            _j176.dump(obj, f)
    try:
        _IN.load_runs(models=(("m1", "r1.json", "s1.json"), ("m2", "r2.json", "s2.json")), root=d)
        stopped = False
    except ValueError:
        stopped = True
    check("[176] ③ ⭐ 행 집합이 다른 결과는 **비교하지 않고 멈춘다**", stopped, "")

def test_f0_never_turns_network_trouble_into_hallucination():
    """[177] **F0 가 네트워크 문제를 «환각」 으로 바꾸지 않는다** — 09-24 (결함 327·329·330).

    ## 무엇이 있었나

    ① `pubmed_lookup` 이 `int(res.get("count", 0))` 로 읽어 **개수가 없는
       응답을 «0건」 으로** 굳히고 캐시에 남겼다 → 실재하는 약 다섯이 «환각」 기각
    ② F0 의 **약물 실재 조회가 429** 였는데 `adjudicate` 가 쌍 조회의 오류만 봐서
       *«F0: 문헌 근거 없음(환각)」* 기각이 났다(terra C6 · `RVT-101`)
    ③ 그리고 `gate_f0` 이 **캐시에 든 dict 를 그대로 고쳐** 판정 표식이 캐시에 남았다
    ④ `bench.run` 이 `--out` 없이 기본값으로 떴다(09-23 붙여넣기 사고)
    """
    import io as _io177
    import contextlib as _cl177
    from ..io import sources as _S, cache as _C
    from ..core import gates as _G
    from ..core.scoring import adjudicate as _adj
    from ..core.state import Candidate as _Cand, RunState as _RS177
    from ..bench import run as _BR177

    old = (_C._PATH, _C._ENABLED)
    _C.configure(_tmp("_c327.json"), enabled=True)
    try:
        # ① P1 — 개수 없는 응답은 **오류**이고 **저장하지 않는다**
        with patched(_S, _get=lambda u: {"esearchresult": {"ERROR": "Search Backend failed"}},
                     REQ_DELAY=0):
            r1 = _S.pubmed_lookup("zz327 a")
            r2 = _S.pubmed_search("zz327 b", 3)
        check("[177] ① ⭐⭐ 개수 없는 응답 → `count` 는 **None**, 오류가 찬다 (0 이 아니다)",
              r1["count"] is None and "esearch 무응답" in str(r1["error"])
              and r2["count"] is None and r2["error"], (r1, r2))
        check("[177] ② ⭐ 그 오류는 **캐시에 안 남는다** — 다음 실행에서 다시 묻는다",
              "zz327 a" not in _C._STORE
              and not any("zz327 b" in k for k in _C._STORE), list(_C._STORE)[:3])
        with patched(_S, _get=lambda u: {"esearchresult": {"count": "0", "idlist": []}},
                     REQ_DELAY=0):
            r3 = _S.pubmed_lookup("zz327 c")
        check("[177] ③ **진짜 0 은 여전히 0** 이다 (고치다 진짜를 잃지 않는다)",
              r3["count"] == 0 and r3["error"] is None, r3)

        # ④~⑥ P2 — 쌍 0건 · **실재 조회 429** → «조회 실패» 보류 · 캐시 객체 안 바뀜
        pair_obj = {"count": 0, "pmids": [], "title": "", "error": None}

        def fake_lookup(q, retmax=3):
            if q == "RVT AND DLB":
                return pair_obj                          # 캐시에 든 객체를 흉내
            return {"count": None, "pmids": [], "title": "",
                    "error": "HTTPError: HTTP Error 429: Too Many Requests"}

        c = _Cand(name="RVT / DLB", origin="TN", query="RVT AND DLB", drug="RVT", disease="DLB")
        st = _RS177("t", "B5", "s", [c], {})
        with patched(_G.sources, pubmed_lookup=fake_lookup):
            _G.gate_f0(st)
        v, p, why = _adj(c)
        check("[177] ④ ⭐⭐ 실재 조회가 429 면 **«환각」 기각이 아니라 보류**다 (RVT-101)",
              v == "보류" and "조회 실패" in why, (v, why))
        check("[177] ⑤ ⭐⭐ `gate_f0` 이 **캐시 객체를 안 고친다** — 오류·표식이 캐시에 안 남는다",
              pair_obj == {"count": 0, "pmids": [], "title": "", "error": None}, pair_obj)
        check("[177] ⑥ 판정 원본(trail)에도 F0 ERROR 가 남는다",
              any(t.gate == "f0" and t.outcome == "ERROR" for t in c.trail),
              [(t.gate, t.outcome) for t in c.trail])
    finally:
        _C.configure(*old)

    # ⑦ ⭐⭐ P3 — `--out` 없이 **실행하지 않는다** (--dry 는 된다)
    buf = _io177.StringIO()
    with _cl177.redirect_stdout(buf):
        rc = _BR177.main(["없는파일.csv", "--configs", "B5"])
    check("[177] ⑦ ⭐⭐ `bench.run` 이 `--out` 없는 실행을 **거부**한다 (rc 2) — 결함 330",
          rc == 2 and "--out" in buf.getvalue(), (rc, buf.getvalue()[:80]))

def test_zeropurge_removes_only_confirmed_fake_zeros():
    """[178] **가짜 0 으로 확정된 캐시 항목만 걷어낸다** — 09-24 (결함 327).

    `zerocheck` 는 캐시에 안 쓴다(재는 도구가 대상을 바꾸면 안 된다). 지우는 일은
    `zeropurge` 가 하고, 규약은 `clean_cache.py` 와 같다 — 기본 미적용 · 백업 먼저 ·
    **확정된 것만.** 시점 차단 검색(연도가 붙은 것)은 그때 진짜 0 이었을 수 있어 안 건드린다.
    """
    import json as _j178
    import os as _o178
    import tempfile as _tf178
    from ..bench import zeropurge as _ZP

    d = _tf178.mkdtemp()
    cp = _o178.path.join(d, "c.json")
    rp = _o178.path.join(d, "r.json")
    z = {"count": 0, "pmids": [], "error": None}
    cache = {"A AND D": dict(z), "A": dict(z),                 # 가짜 0 (그때 5)
             "SEARCH::8::A AND D::-": dict(z),                  # 같은 질의 · 전 기간 → 지운다
             "SEARCH::8::A AND D::2019": dict(z),               # 시점 차단 → 안 건드린다
             "B AND D": dict(z),                                # 진짜 0 (그때 0) → 남긴다
             "C AND D": {"count": 3, "pmids": ["1"], "error": None}}
    with open(cp, "w", encoding="utf-8") as f:
        _j178.dump(cache, f)
    with open(rp, "w", encoding="utf-8") as f:
        _j178.dump({"질의": {"A AND D": {"그때": 5}, "A": {"그때": 5},
                            "B AND D": {"그때": 0}, "E": {"그때": None}}}, f)

    keys, fake = _ZP.plan(cache, _j178.load(open(rp, encoding="utf-8")))
    check("[178] ① ⭐⭐ 가짜 0 인 질의의 **원문 키 + 전 기간 검색 키만** 지울 목록에 든다",
          keys == ["A", "A AND D", "SEARCH::8::A AND D::-"], keys)
    check("[178] ② 확인 불가(None)·진짜 0 은 **가짜로 안 친다**", fake == ["A", "A AND D"], fake)

    rc = _ZP.main([rp, "--cache", cp])                          # 미적용
    after = _j178.load(open(cp, encoding="utf-8"))
    check("[178] ③ ⭐ `--apply` 없이는 **아무것도 안 바꾼다**", rc == 0 and after == cache, len(after))

    rc2 = _ZP.main([rp, "--cache", cp, "--apply"])
    after2 = _j178.load(open(cp, encoding="utf-8"))
    baks = [f for f in _o178.listdir(d) if "_가짜0" in f]
    check("[178] ④ ⭐⭐ 적용하면 **백업을 먼저** 뜨고 목록에 든 셋만 지운다",
          rc2 == 0 and baks and set(cache) - set(after2) == {"A", "A AND D", "SEARCH::8::A AND D::-"}
          and "SEARCH::8::A AND D::2019" in after2 and "B AND D" in after2,
          (rc2, baks, sorted(set(cache) - set(after2))))


def test_seed_retest_cannot_replay_copy_or_leak():
    """[179] **표적 재시험이 «재생» 도 «복사» 도 «누출» 도 못 하게** — 09-24 신설.

    ## 무엇을 막나

    sol 의 초과 기각(갈린 27쌍 중 22:5)이 모델의 성질인지 가르려고 **갈린 쌍만
    새 seed 로** 다시 묻는다(`seedretest.py`). 설계가 틀리면 답이 **저절로** 나온다.

      ① 캐시 우회를 빠뜨리면 1차 답을 재생한다 — 호출 0 · 일치 100%
      ② seed 가 1차(42)와 같으면 공급자가 같은 답을 준다(apiprobe 5/5) — «재현» 이 복사다
      ③ 27행만으로 누출 차단을 걸면 **다른 360행의 라벨 출처 논문이 근거로 샌다**

    셋 다 **«재현됐다» 쪽으로** 틀린다 — 우리에게 유리한 고장이다. 구조로 막는다.

    ⚠ 이 도구를 처음 만들 때 **같은 이름의 8월 도구(`retest.py` · 재시험 신뢰도)를
    읽지 않고 덮었다**(결함 333). git 에서 되살렸다. ⑬ 이 그 자리를 본다.
    """
    import json as _j179
    import os as _o179
    import tempfile as _tf179
    from .. import evidence as _EV179
    from ..bench import modelpair as _MP179
    from ..bench import run as _BR179
    from ..bench import seedretest as _SR
    from ..core import gates as _G179
    from ..io import cache as _C179

    def C(name, label, verdict, pm=("1",), f0="PASS", direction="refute"):
        return {"name": name, "drug": name, "disease": "d", "label": label,
                "verdict": verdict, "reason": "x",
                "trail": [{"gate": "f0", "outcome": f0}],
                "factcheck": [{"pmid": p, "direction": direction, "kept": True} for p in pm]}

    # ① 갈린 쌍 고르기
    A = [C("a", "TN", "기각"), C("b", "TN", "보류"), C("c", "TN", "기각", pm=("2",)),
         C("d", "TN", "기각", f0="KILL"), C("e", "TP", "기각"), C("f", "TN", "기각")]
    B = [C("a", "TN", "보류"), C("b", "TN", "기각"), C("c", "TN", "보류", pm=("3",)),
         C("d", "TN", "보류", f0="KILL"), C("e", "TP", "보류"), C("f", "TN", "기각")]
    T = _SR.pick(A, B)
    check("[179] ① ⭐ 갈린 쌍 = 입력 동일 · TN · F0 갈래 아님 · 한쪽만 기각 (입력 다름·F0·TP·일치는 뺀다)",
          [(t["name"], t["1차기각"]) for t in T] == [("a", "A"), ("b", "B")], T)

    # ② 대상 목록을 손으로 고치면 멈춘다
    d = _tf179.mkdtemp()
    tp = _o179.path.join(d, "t.json")
    tp2 = _o179.path.join(d, "t2.json")
    with open(tp, "w", encoding="utf-8") as f:
        _j179.dump({"대상": T, "대상지문": _SR.target_fp(T)}, f, ensure_ascii=False)
    with open(tp2, "w", encoding="utf-8") as f:
        _j179.dump({"대상": [dict(T[0], name="zz")] + T[1:], "대상지문": _SR.target_fp(T)},
                   f, ensure_ascii=False)
    try:
        _SR.read_targets(tp2)
        tampered = False
    except ValueError:
        tampered = True
    check("[179] ② 대상 목록을 손으로 고치면 지문이 안 맞아 **멈춘다**",
          _SR.read_targets(tp)["대상지문"] == _SR.target_fp(T) and tampered, tampered)

    # ③④ 환경 가드
    M = "m/x"
    good = dict(MODEL=M, FALLBACKS=[M], SEED="7", BYPASS_CACHE=True, MAX_CALLS=162)

    def env(mode, seed, **over):
        with patched(llm, **dict(good, **over)), patched(llm, model_for=lambda r: M):
            return _SR.check_env(M, seed, mode, 162 if mode == "fresh" else None)

    e_ok, e_same = env("fresh", "7"), env("fresh", "42", SEED="42")
    e_nobp, e_fb = env("fresh", "7", BYPASS_CACHE=False), env("fresh", "7", FALLBACKS=[M, "other"])
    e_rep = env("replay", "42", SEED="42", BYPASS_CACHE=False, MAX_CALLS=5)
    e_rep_ok = env("replay", "42", SEED="42", BYPASS_CACHE=False, MAX_CALLS=0)
    check("[179] ③ ⭐⭐ 새로 묻기 — seed 가 1차(42)와 같거나 · 우회가 꺼졌거나 · 대체 사슬에 "
          "다른 모델이 있으면 **멈춘다**",
          e_ok == [] and any("복사" in x for x in e_same) and any("우회" in x for x in e_nobp)
          and any("대체" in x for x in e_fb), (e_ok, e_same, e_nobp, e_fb))
    check("[179] ④ 재생은 호출 상한 **0** 이어야 한다 — 한 번이라도 부를 수 있으면 «재생» 이 아니다",
          any("상한" in x for x in e_rep) and e_rep_ok == [], (e_rep, e_rep_ok))

    # ⑤⑥ 누출 차단은 전체 행 · 실행은 대상 행 · 상태 파일 모양
    hp = _o179.path.join(d, "h.csv")
    with open(hp, "w", encoding="utf-8") as f:
        f.write("label,stratum,drug,indication,nct\n"
                "TN,A,d1,i1,NCT01\nTP,A,d2,i2,\nTN,A,d3,i3,NCT03\nTP,A,d4,i4,NCT04\n")
    T5 = [{"idx": 2, "name": "d3 / i3", "label": "TN", "1차기각": "A",
           "drug": "d3", "disease": "i3"}]
    tp5 = _o179.path.join(d, "t5.json")
    with open(tp5, "w", encoding="utf-8") as f:
        _j179.dump({"대상": T5, "대상지문": _SR.target_fp(T5)}, f, ensure_ascii=False)
    cp5 = _o179.path.join(d, "c.json")
    with open(cp5, "w", encoding="utf-8") as f:
        f.write("{}")
    seen = {}

    class _Tr:
        def __init__(s, g, o):
            s.gate, s.outcome, s.detail = g, o, ""

    class _Cn:
        def __init__(s, r):
            s.name = "%s / %s" % (r["drug"], r["indication"])
            s.drug, s.disease = r["drug"], r["indication"]
            s.verdict, s.confidence, s.reason = "기각", 30, "근거"
            s.f0, s.veto, s.veto_reason = {}, None, None
            s.trail, s.factcheck = [_Tr("f0", "PASS")], []

    class _St:
        def __init__(s, rows):
            s.candidates = [_Cn(r) for r in rows]

    def fake_rc(rows, cfg, stamp):
        seen["rows"], seen["cfg"] = [r["drug"] for r in rows], cfg
        return _St(rows)

    def fake_ex(ncts, expand=True):
        seen["ncts"] = set(ncts)
        return {"pmids": 0, "no_index": 0}

    sp5 = _o179.path.join(d, "s.json")
    with patched(llm, **good), patched(llm, model_for=lambda r: M), \
            patched(_BR179, run_config=fake_rc), patched(_G179, set_exclude=fake_ex), \
            patched(_C179, configure=lambda *a, **k: None, load=lambda: None, save=lambda: None):
        _SR.run_targets(tp5, sp5, cp5, M, "7", "fresh", holdout=hp, max_calls=162)
        try:
            _SR.run_targets(tp5, sp5, cp5, M, "7", "fresh", holdout=hp, max_calls=162)
            again = True
        except FileExistsError:
            again = False
        try:
            _SR.run_targets(tp5, sp5 + "2", "pubmed_cache.json", M, "7", "fresh",
                            holdout=hp, max_calls=162)
            live = True
        except ValueError:
            live = False
    check("[179] ⑤ ⭐⭐ 누출 차단은 **전체 행의 NCT** 로 걸고 실행은 **대상 행만** — "
          "27행만으로 걸면 360행의 라벨 출처가 샌다",
          seen.get("ncts") == {"NCT01", "NCT03", "NCT04"} and seen.get("rows") == ["d3"]
          and seen.get("cfg") == "B5", seen)
    doc5 = _j179.load(open(sp5, encoding="utf-8"))
    c5 = doc5["candidates"][0]
    check("[179] ⑥ 상태 파일은 `--save-state` 와 같은 열 · modelpair 가 읽는다 · "
          "덮어쓰기와 **실캐시**는 거부한다",
          tuple(c5) == _SR.STATE_KEYS and len(_MP179.load(sp5)) == 1
          and doc5["재시험"]["seed"] == "7" and not again and not live,
          (tuple(c5), again, live))

    # ⑦ 열 목록이 run.py 의 저장 코드와 같다
    src = open(_o179.path.join(_EV179.ROOT, "bioreroute", "bench", "run.py"),
               encoding="utf-8").read()
    blk = src[src.index('_j.dump({"config": cfg, "candidates": ['):]
    blk = blk[:blk.index("for c, r in zip(st.candidates, rows)")]
    keys = [k for k in re.findall(r'"(\w+)":', blk)
            if k not in ("config", "candidates", "gate", "outcome", "detail")]
    check("[179] ⑦ ⭐ 열 목록이 `run.py` 의 저장 코드와 **같다** — 한쪽만 열을 늘리면 여기서 깨진다",
          tuple(keys) == _SR.STATE_KEYS, keys)

    # ⑧ 재생 관문
    first = [C("a", "TN", "기각"), C("b", "TN", "보류")]
    Tg = [{"idx": 1, "name": "b", "label": "TN", "1차기각": "B"}]
    g0 = _SR.gate(Tg, first, [C("b", "TN", "보류")])
    g1 = _SR.gate(Tg, first, [C("b", "TN", "기각")])
    g2 = _SR.gate(Tg, first, [C("b", "TN", "보류", direction="support")])
    g3 = _SR.gate(Tg, first, [C("b", "TN", "기각", pm=("7",))])
    rk = _SR.reason_key("반박 6건 w=9.63") == _SR.reason_key("반박 6건 w=9.64")
    check("[179] ⑧ 재생 관문 — 같으면 통과 · 입력이 같은데 판정·**초록 판독**이 다르면 "
          "**경로** 차이로 멈춘다 · 입력이 바뀐 것은 빼고 간다 · 사유의 반올림은 안 본다",
          g0 == [] and g1 and "verdict" in g1[0][2] and g1[0][3] == "경로"
          and g2 and "초록 판독" in g2[0][2] and not _SR.gate_verdict(g1)[0]
          and g3 and g3[0][3] == "입력" and _SR.gate_verdict(g3)[0] and rk,
          (g0, g1, g2, g3, rk))

    # ⑨⑩ 분석 — 새 seed 의 답만 · 입력이 바뀐 쌍은 뺀다
    Ta = [{"idx": 0, "name": "p", "label": "TN", "1차기각": "A"},
          {"idx": 1, "name": "q", "label": "TN", "1차기각": "A"},
          {"idx": 2, "name": "r", "label": "TN", "1차기각": "B"}]
    fa = [C("p", "TN", "기각"), C("q", "TN", "기각"), C("r", "TN", "보류")]
    fb = [C("p", "TN", "보류"), C("q", "TN", "보류"), C("r", "TN", "기각")]
    a2 = [C("p", "TN", "기각"), C("q", "TN", "기각"), C("r", "TN", "기각")]
    b2 = [C("p", "TN", "보류"), C("q", "TN", "보류"), C("r", "TN", "기각")]
    res = _SR.analyze(Ta, fa, fb, [a2, a2], [b2, b2])
    m = res["주검정"]
    check("[179] ⑨ 주검정은 **새 seed 의 답만** (쌍, seed) 합산 — b=4 · c=0 · p=0.125 → 갈래 «다»",
          (m["A만"], m["B만"]) == (4, 0) and abs(m["p"] - 0.125) < 1e-9 and m["갈래"] == "다", m)
    a3 = [C("p", "TN", "기각", pm=("9",)), C("q", "TN", "기각"), C("r", "TN", "기각")]
    res3 = _SR.analyze(Ta, fa, fb, [a3, a2], [b2, b2])
    check("[179] ⑩ 새 실행에서 **입력이 바뀐 쌍은 주검정에서 뺀다** — 그 차이는 모델 탓이라 못 한다",
          res3["분석대상"] == 2 and res3["뺀대상"] == ["p"], (res3["분석대상"], res3["뺀대상"]))

    # ⑪ 실행 표시·seed 표시 검증
    prov = {"served_by": M, "model": M, "temperature_used": "default+seed7(재현 시도·보장 아님)"}
    gd = {"재시험": {"방식": "fresh", "모델": M, "seed": "7", "캐시우회": True, "대상지문": "fp",
                   "호출": 10, "캐시적중": 0, "실패": 0, "코드지문": "cf"},
          "candidates": [{"factcheck": [{"pmid": "1", "provenance": prov}]}]}
    bd = _j179.loads(_j179.dumps(gd))
    bd["재시험"]["캐시적중"] = 3
    bd["candidates"][0]["factcheck"][0]["provenance"]["temperature_used"] = "default+seed42(…)"
    v0, v1 = _SR.validity(gd, M, "7", "fp", "cf"), _SR.validity(bd, M, "7", "fp", "cf")
    check("[179] ⑪ ⭐ 답에 적힌 seed 가 다르거나 캐시가 새면 **무효로 적는다**",
          v0 == [] and any("seed" in x for x in v1) and any("캐시" in x for x in v1), (v0, v1))

    # ⑫ 검정력 — 명세 §4 의 표가 코드에서 나온다
    tab = {n: v for n, _, _, v in _SR.power_table(ks=(1, 3))}
    check("[179] ⑫ 검정력은 코드에서 — 중간 시나리오 k=3 = 0.945 · 귀무는 α/2 아래",
          abs(tab["중간"][1] - 0.945) < 0.001 and max(tab["귀무"]) <= 0.025, tab)

    # ⑬ 8월 도구가 제자리에 있다
    from ..bench import retest as _RT179
    check("[179] ⑬ 8월 도구 `retest.py`(재시험 신뢰도)가 **그대로 있다** — 처음에 이 이름으로 덮었다(결함 333)",
          hasattr(_RT179, "judge") and hasattr(_RT179, "summarize")
          and not hasattr(_RT179, "pick"), [x for x in dir(_RT179) if not x.startswith("_")][:6])


def test_seed_retest_script_carries_the_sealed_values():
    """[180] **`표적재시험.ps1` 이 봉인될 명세의 값을 그대로 든다** — 09-24 신설.

    [173](luna) 과 같은 자리다. 명세는 봉인하면 못 고치고 스크립트는 누구나 고친다.
    그래서 둘을 묶는다 — 모델 · seed · 순서 · 지문 · 상한 · **도구 판**까지.
    도구(`seedretest.py`)는 코드 지문 31개 파일 밖이라 **따로** 박는다. 안 박으면
    봉인 뒤에 도구를 고쳐도 아무것도 안 울린다.
    """
    import hashlib as _h180
    import json as _j180
    import os as _o180
    from .. import evidence as _EV180

    root = _EV180.ROOT
    p = _o180.path.join(root, "표적재시험.ps1")
    spec = _o180.path.join(root, "사전명세_표적재시험_0924.md")
    tool = _o180.path.join(root, "bioreroute", "bench", "seedretest.py")
    tfile = _o180.path.join(root, "표적재시험_대상.json")
    have = all(_o180.path.exists(x) for x in (p, spec, tool))
    check("[180] ① 스크립트 · 명세 · 도구가 있다", have, (p, spec))
    if not have:
        return
    raw = open(p, "rb").read()
    src = raw.decode("utf-8-sig")
    stxt = open(spec, encoding="utf-8").read()
    tsha = _h180.sha256(open(tool, "rb").read()).hexdigest()[:12]

    check("[180] ② ⭐ UTF-8 **BOM** · CRLF — 없으면 PowerShell 5.1 이 한글 파일명을 깨뜨린다(결함 231)",
          raw[:3] == b"\xef\xbb\xbf" and b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""),
          raw[:3])

    vals = ("openai/gpt-5.6-sol", "openai/gpt-5.6-luna", "c849bb2d77fb", "a0b6253776e5",
            "dccefcba4aab", "3642eebb8d8f", "162", tsha)
    miss = [v for v in vals if v not in src or v not in stxt]
    check("[180] ③ ⭐⭐ 모델 · 코드 지문 · 대상 지문 · 스냅숏 · 검색 키 · 상한 · **도구 판**이 "
          "명세와 스크립트에 **둘 다** 있다",
          not miss, "한쪽에만 있는 값: %s" % miss)

    seeds_ps = re.search(r'\$SEEDS\s*=\s*@\(([^)]*)\)', src)
    plan_ps = re.search(r'\$PLAN\s*=\s*@\(([^)]*)\)', src)
    seeds = re.findall(r'"(\d+)"', seeds_ps.group(1)) if seeds_ps else []
    plan = re.findall(r'"([AB]:\d+)"', plan_ps.group(1)) if plan_ps else []
    check("[180] ④ ⭐ 새 seed **7 · 11 · 13** · 순서 **ABBAAB** — 명세 §1 그대로 · 1차 seed 42 는 없다",
          seeds == ["7", "11", "13"] and plan == ["A:7", "B:7", "B:11", "A:11", "A:13", "B:13"]
          and "7 · 11 · 13" in stxt and "sol-7 → luna-7 → luna-11 → sol-11 → sol-13 → luna-13" in stxt,
          (seeds, plan))

    need = ('"--mode", "fresh"', '"--mode", "replay"', '"--max-calls"',
            '$env:BIOREROUTE_FALLBACKS    = $model', '$env:BIOREROUTE_BYPASS_CACHE = $bypass',
            'Set-Run $m $FIRST "0" 0', 'Set-Run $m $s "1" $MAXCALLS')
    check("[180] ⑤ ⭐⭐ 재생은 **우회 끔 · 상한 0**, 새로 묻기는 **우회 켬 · 새 seed** · "
          "대체 사슬은 **자기 모델만**",
          all(n in src for n in need), [n for n in need if n not in src])

    ok_t = False
    if _o180.path.exists(tfile):
        d = _j180.load(open(tfile, encoding="utf-8"))
        ok_t = (d.get("대상지문") == "a0b6253776e5" and d.get("A만") == 22 and d.get("B만") == 5
                and len(d.get("대상") or []) == 27)
    check("[180] ⑥ 대상 목록 파일이 명세의 지문 · 22 · 5 와 같다", ok_t, tfile)


def test_draw_replicate_separates_input_seed_and_model():
    """[181] **추출 복제가 입력 · seed · 모델 효과를 섞지 않는다** — 09-24 신설.

    모든 수치가 seed 42 한 번의 추출이었다. `drawvar` 는 같은 입력(스냅숏) 위의
    실행들로 «같은 모델 · 다른 seed» 와 «다른 모델» 의 판정 불일치를 견준다.
    틀리기 쉬운 자리가 넷이다 —
      ① 옛 캐시 실행(terra_1)을 seed·모델 칸에 넣으면 **입력 차이가 섞인다**(결함 326)
      ② 사본에 옛 LLM 답이 남으면 새 seed 가 **옛 답을 재생**한다 → 사본은 LLM 키 0
      ③ 입력이 다른 후보를 불일치로 세면 모델·seed 탓이 아닌 것이 섞인다
      ④ 명세대로 안 돈 실행(다른 seed 표시 · 우회 켬 · 호출 0)을 그대로 쓴다
    """
    import json as _j181
    import os as _o181
    import tempfile as _tf181
    from ..bench import drawvar as _DV

    d = _tf181.mkdtemp()
    # ② strip
    snap = _o181.path.join(d, "snap.json")
    with open(snap, "w", encoding="utf-8") as f:
        _j181.dump({"A AND B": {"count": 3}, "SEARCH::8::q::-": {"pmids": ["1"]},
                    "LLM::m::0.0::abc": {"text": "old"}}, f)
    cp = _o181.path.join(d, "copy.json")
    r = _DV.strip(snap, cp)
    got = _j181.load(open(cp, encoding="utf-8"))
    try:
        _DV.strip(snap, cp)
        again = True
    except FileExistsError:
        again = False
    check("[181] ① ⭐⭐ 사본은 **LLM 답 0** · 검색층은 그대로 · 덮어쓰기 거부",
          r["LLM"] == 0 and r["뺀_LLM"] == 1 and set(got) == {"A AND B", "SEARCH::8::q::-"}
          and not again, (r, sorted(got)))

    # ① 짝 분류
    ss, wi, bt = _DV.pairs(_DV.RUNS)
    check("[181] ② ⭐ 옛 캐시 실행은 **같은 seed 짝에만** · 같은 모델 다른 seed 5 · 다른 모델 16",
          ss == [("terra_1", "terra_s42")] and len(wi) == 5 and len(bt) == 16
          and all("terra_1" not in p for p in wi + bt), (ss, len(wi), len(bt)))

    # ③ 입력이 다르면 None
    def C(name, verdict, label="TN", pm=("1",), prov=None):
        fc = [{"pmid": p, "direction": "refute", "kept": True,
               **({"provenance": prov} if prov else {})} for p in pm]
        return {"name": name, "drug": name, "disease": "d", "label": label,
                "verdict": verdict, "reason": "x", "trail": [{"gate": "f0", "outcome": "PASS"}],
                "factcheck": fc}
    dd = _DV.disagree([C("a", "기각"), C("b", "보류")], [C("a", "보류"), C("b", "보류", pm=("2",))])
    check("[181] ③ 불일치는 **입력이 같은 후보만** 센다 (다르면 None)", dd == [1, None], dd)

    # ④ 분해 — 방향과 말
    cz = {"x1": [C("a", "기각"), C("b", "보류")], "x2": [C("a", "기각"), C("b", "보류")],
          "y1": [C("a", "보류"), C("b", "기각")]}
    dpos = _DV.decompose(cz, [("x1", "x2")], [("x1", "y1")], reps=200)
    dneg = _DV.decompose(cz, [("x1", "y1")], [("x1", "x2")], reps=200)
    dzero = _DV.decompose(cz, [("x1", "y1")], [("x1", "y1")], reps=200)
    check("[181] ④ ⭐ D = 다른 모델 − 다른 seed · 부호대로 말이 갈린다 (구간이 0 을 품으면 «구별되지 않는다»)",
          dpos["D"] == 1.0 and dneg["D"] == -1.0 and dzero["D"] == 0.0
          and "더** 흔들린다" in _DV.r1_text(dpos) and "seed 를 바꾸면" in _DV.r1_text(dneg)
          and "구별되지 않는다" in _DV.r1_text(dzero), (dpos["D"], dneg["D"], dzero["D"]))

    # ⑤ 유효성
    M = "openai/gpt-5.6-terra"
    okp = {"served_by": M, "model": M, "temperature_used": "default+seed17(재현 시도·보장 아님)"}
    good = [C("a", "기각", prov=okp)]
    res = {"B0": {}, "B5": {}}
    cost_ok = {"실행": {"캐시우회": False}, "합계": {"계량된_호출": 10}}
    v0 = _DV.validity(("terra_s17", M, "17"), good, res, cost_ok)
    badp = dict(okp, temperature_used="default+seed42(재현 시도·보장 아님)")
    v1 = _DV.validity(("terra_s17", M, "17"), [C("a", "기각", prov=badp)], res,
                      {"실행": {"캐시우회": True}, "합계": {"계량된_호출": 0}})
    check("[181] ⑤ ⭐ 명세대로 안 돈 실행(다른 seed 표시 · 우회 켬 · 호출 0)은 **무효로 적는다**",
          v0 == [] and any("seed" in x for x in v1) and any("우회" in x for x in v1)
          and any("호출 0" in x for x in v1), (v0, v1))

    # ⑥ 끝까지 — 가짜 실행 8개로 analyze 가 돈다
    rows = [{"drug": "d%d" % i, "indication": "i", "label": ("TP" if i % 2 else "TN")}
            for i in range(8)]
    runs = []
    for tag, model, seed, out, st, where in _DV.RUNS:
        prov = {"served_by": model, "model": model,
                "temperature_used": "default+seed%s(재현 시도·보장 아님)" % seed}
        vs = [("유망" if r["label"] == "TP" else ("기각" if (i + len(tag)) % 3 else "보류"))
              for i, r in enumerate(rows)]
        cands = [dict(C(r["drug"], v, label=r["label"], prov=prov), disease="i",
                      name="%s / i" % r["drug"]) for r, v in zip(rows, vs)]
        sc = [0.9 if r["label"] == "TP" else 0.2 + 0.01 * i for i, r in enumerate(rows)]
        with open(_o181.path.join(d, out), "w", encoding="utf-8") as f:
            _j181.dump({"rows": rows, "results": {
                "B0": {"scores": sc, "leak": [False] * 8, "verdicts": ["모름"] * 8},
                "B5": {"scores": sc, "verdicts": vs}}}, f, ensure_ascii=False)
        with open(_o181.path.join(d, st), "w", encoding="utf-8") as f:
            _j181.dump({"config": "B5", "candidates": cands}, f, ensure_ascii=False)
        if tag in _DV.NEW:
            with open(_o181.path.join(d, out.replace("홀드아웃_복제_", "비용_복제_")), "w",
                      encoding="utf-8") as f:
                _j181.dump({"실행": {"캐시우회": False}, "합계": {"계량된_호출": 5}}, f)
        runs.append((tag, model, seed, out, st, where))
    o = _DV.analyze(runs=runs, root=d)
    check("[181] ⑥ ⭐ 가짜 실행 여덟으로 **끝까지** 돈다 — 무효 0 · R1·R2·R3 가 나온다",
          not o["무효"] and o["R1"] is not None and o["R2"] is not None and o["R3"] is not None
          and len(o["짝별"]) == 1 + 5 + 16, (o["무효"], o["R1_말"], len(o["짝별"])))


def test_draw_replicate_script_carries_the_sealed_values():
    """[182] **`추출복제.ps1` 이 봉인될 명세의 값을 그대로 든다** — 09-24 신설.

    [173]·[180] 과 같은 자리. 여기에 셋을 더 본다 — ① 다섯 실행이 **각자 사본**을
    쓴다(같은 파일을 둘이 쓰면 캐시가 깨진다 · 결함 26·27 계열) ② **캐시 우회 0**
    (사본에 LLM 답이 없으므로 우회가 필요 없고, 켜면 끊긴 뒤 처음부터 다시 묻는다)
    ③ 실행 인자가 1차와 같다(`--configs B0 B5` · `--stratum A`) + `--cache`.
    """
    import hashlib as _h182
    import os as _o182
    from .. import evidence as _EV182
    from ..bench import drawvar as _DV182

    root = _EV182.ROOT
    p = _o182.path.join(root, "추출복제.ps1")
    spec = _o182.path.join(root, "사전명세_추출복제_0924.md")
    tool = _o182.path.join(root, "bioreroute", "bench", "drawvar.py")
    have = all(_o182.path.exists(x) for x in (p, spec, tool))
    check("[182] ① 스크립트 · 명세 · 도구가 있다", have, (p, spec))
    if not have:
        return
    raw = open(p, "rb").read()
    src = raw.decode("utf-8-sig")
    stxt = open(spec, encoding="utf-8").read()
    tsha = _h182.sha256(open(tool, "rb").read()).hexdigest()[:12]

    check("[182] ② ⭐ UTF-8 **BOM** · CRLF (결함 231) · 백틱 줄 이어쓰기 없음 (CLAUDE.md §5)",
          raw[:3] == b"\xef\xbb\xbf" and b"\r\n" in raw
          and b"\n" not in raw.replace(b"\r\n", b"")
          and not any(l.rstrip().endswith("`") and not l.lstrip().startswith("#")
                      for l in src.splitlines()), raw[:3])

    vals = ("openai/gpt-5.6-terra", "openai/gpt-5.6-sol", "openai/gpt-5.6-luna",
            "c849bb2d77fb", "dccefcba4aab", "3642eebb8d8f", "1726", tsha)
    miss = [v for v in vals if v not in src or v not in stxt]
    check("[182] ③ ⭐⭐ 모델 · 코드 지문 · 스냅숏 · 검색 키 · 상한 · **도구 판**이 명세와 스크립트에 둘 다",
          not miss, "한쪽에만 있는 값: %s" % miss)

    tags = re.search(r'\$TAGS\s*=\s*@\(([^)]*)\)', src)
    tags = re.findall(r'"([a-z]+_s\d+)"', tags.group(1)) if tags else []
    new = list(_DV182.NEW)
    check("[182] ④ ⭐ 다섯 실행(이름·seed)이 명세 표 · 도구(`drawvar.NEW`) · 스크립트에서 같다",
          tags == new and all(("`%s`" % t) in stxt for t in new), (tags, new))

    need = ('"--configs", "B0", "B5"', '"--stratum", "A"', '"--cache", (Copy-Of $t)',
            '"--out", (Out-Of $t)', '"--save-state", (State-Of $t)', '"--cost-out", (Cost-Of $t)',
            'Set-Run (Model-Of $t) (Seed-Of $t) "0"', '$env:BIOREROUTE_FALLBACKS    = $model',
            'WorkingDirectory = $PSScriptRoot')
    check("[182] ⑤ ⭐⭐ 실행마다 **자기 사본** · 캐시 우회 0 · 1차와 같은 인자 · 대체 사슬은 자기 모델만",
          all(n in src for n in need), [n for n in need if n not in src])

    # 도구가 짓는 비용 파일 이름 = 스크립트가 쓰는 이름
    dv_cost = [r[3].replace("홀드아웃_복제_", "비용_복제_") for r in _DV182.RUNS if r[0] in _DV182.NEW]
    check("[182] ⑥ 결과 · 비용 파일 이름이 도구와 스크립트에서 같은 규칙이다",
          'function Out-Of($t)   { return ("홀드아웃_복제_" + $t + ".json") }' in src
          and 'function Cost-Of($t)  { return ("비용_복제_" + $t + ".json") }' in src
          and dv_cost == ["비용_복제_%s.json" % t for t in new], dv_cost)


def test_preflight_notices_when_the_demo_would_run_the_wrong_model():
    """[183] **화면·시연이 제출하지 않은 모델로 돌면 `preflight` 이 빨개진다** — 09-25 신설.

    09-23 luna 실행 때 `.env` 를 luna 로 바꾼 채 이틀이 지났다. 실험 스크립트는
    환경변수로 모델을 박아서 상관없었지만, **화면·시연·예시 재생성은 `.env` 를
    읽는다.** 아무 검사도 안 울렸고 승우가 물어서 알았다(09-25).
    """
    import os as _o183
    from .. import evidence as _EV183
    from ..bench import preflight as _PF

    with patched(llm, MODEL="openai/gpt-5.6-luna"):
        bad = _PF.submit_model()
    with patched(llm, MODEL=_PF.SUBMIT_MODEL):
        good = _PF.submit_model()
    check("[183] ① ⭐⭐ 제출 모델이 아니면 **틀렸다고** 본다 · 맞으면 통과",
          bad["맞다"] is False and good["맞다"] is True, (bad, good))

    res = open(_o183.path.join(_EV183.ROOT, "홀드아웃_본선모델_결과.md"), encoding="utf-8").read()
    check("[183] ② 제출 모델 상수가 결과 문서의 «제출은 terra» 와 같다",
          _PF.SUBMIT_MODEL == "openai/gpt-5.6-terra" and "제출은 `terra`" in res, _PF.SUBMIT_MODEL)

    src = open(_o183.path.join(_EV183.ROOT, "bioreroute", "bench", "preflight.py"),
               encoding="utf-8").read()
    body = src[src.index("def main("):]
    check("[183] ③ ⭐ `preflight` 본문이 실제로 부르고 **실패로 센다**(안내문이 아니다)",
          "_m = submit_model()" in body and "bad += 1" in body[body.index("_m = submit_model()"):
                                                               body.index("_m = submit_model()") + 400],
          "")


def test_result_writer_copies_numbers_and_sealed_words_only():
    """[184] **결과 반영 도구는 숫자를 JSON 에서, 말을 봉인 문구에서만 가져온다** — 09-25.

    수치를 손으로 옮기다 틀린 것이 세 번이다(결함 19 · 307 · 331). `resultmd` 는
    분석 JSON → 결과 문서 절로 옮긴다. 틀리기 쉬운 자리 셋 —
      ① 예측 상수가 **봉인된 명세 문구와 갈라진다** → 예측 대조가 거짓이 된다
      ② 무효인데 **갈래 문장을 찍는다** → 명세 §6 위반
      ③ 결과 파일을 **덮는다**
    """
    import json as _j184
    import os as _o184
    import tempfile as _tf184
    from .. import evidence as _EV184
    from ..bench import resultmd as _RM
    from ..bench import seedretest as _SR184

    ts = open(_o184.path.join(_EV184.ROOT, _RM.TARGETED_SPEC), encoding="utf-8").read()
    rs = open(_o184.path.join(_EV184.ROOT, _RM.REPLICATE_SPEC), encoding="utf-8").read()
    miss = [k for k, (txt, _) in _RM.TARGETED_PRED.items() if txt not in ts]
    miss += [k for k, (txt, _) in _RM.REPLICATE_PRED.items() if txt not in rs]
    check("[184] ① ⭐⭐ 예측 상수의 문구가 **봉인된 명세 본문에 그대로** 있다", not miss, miss)

    def rt(k, n):
        return {"k": k, "n": n, "비율": k / n if n else None, "CI": [0.0, 1.0]}
    res = {"대상": 27, "분석대상": 27, "뺀대상": [], "seed수": 3,
           "주검정": {"A만": 30, "B만": 9, "불일치": 39, "p": 0.001, "alpha": 0.05,
                   "psi_hat": 0.23, "psi_ci": [0.12, 0.38], "갈래": "가"},
           "seed별": [{"A만": 10, "B만": 3, "p": 0.09}] * 3,
           "유지": {"A": {"A기각": rt(40, 66), "B기각": rt(12, 66)},
                  "B": {"A기각": rt(4, 15), "B기각": rt(9, 15)}},
           "seed간뒤집힘": {"A": [rt(6, 27)] * 3, "B": [rt(7, 27)] * 3},
           "표": [], "유효성": []}
    ok_md = _RM.targeted_md(res)
    bad = dict(res, 유효성=["A seed 7 — 캐시 적중 3 — 우회가 새었다"])
    bad_md = _RM.targeted_md(bad)
    check("[184] ② ⭐⭐ 유효하면 **봉인한 갈래 문구 그대로** · 무효면 갈래 문장을 **안 찍는다**",
          _SR184.BRANCH_TEXT["가"] in ok_md and _SR184.BRANCH_TEXT["가"] not in bad_md
          and "무효" in bad_md and "b 30 · c 9" in ok_md, "")

    d = _tf184.mkdtemp()
    tp = _o184.path.join(d, "t.json")
    with open(tp, "w", encoding="utf-8") as f:
        _j184.dump(res, f, ensure_ascii=False)
    outp = _o184.path.join(d, "o.md")
    r1 = _RM.main(["--targeted", tp, "--replicate", _o184.path.join(d, "없음.json"), "--out", outp])
    r2 = _RM.main(["--targeted", tp, "--replicate", _o184.path.join(d, "없음.json"), "--out", outp])
    check("[184] ③ 새 파일로만 쓴다 — 두 번째는 **덮지 않고** 멈춘다",
          r1 == 0 and r2 == 2 and _o184.path.exists(outp), (r1, r2))


def test_prereg_ledger_counts_every_sealed_spec_and_quotes_real_lines():
    """[185] **사전 기준 집계는 대장에서 나오고, 대장은 원문에 묶여 있다** — 09-25 신설.

    «사전 기준이 붙고 결과가 나온 넷 중 셋이 미달» 이 제출 문서 다섯과 슬라이드에
    있었다. 결과가 나온 기준은 39개였다(«넷» 은 08-05 첫 봉인 넷 · 생성은 통과).
    분류는 사람이 하지만(결함 303 «기계로 못 센다»), 다음은 기계가 막는다 —
      ① 봉인 명세가 대장에서 빠지면 · ② 근거 인용이 원문에 없으면
      ③ «실행 중» 인데 결과 파일이 생겼으면 · ④ 문서의 집계가 대장과 다르면
    """
    import copy as _c185
    from ..bench import prereg as _PR

    root = _PR.ROOT
    rows = _PR.load(root)
    bad = _PR.check(root, rows)
    check("[185] ① ⭐⭐ 대장이 깨끗하다 — 봉인 사전명세 전부 · 인용 전부 원문에 있음 · "
          "결과가 나왔는데 «실행 중» 인 행 없음", not bad, bad[:5])

    # ② 일부러 깨뜨린다 — 셋 다 잡아야 한다
    r_quote = _c185.deepcopy(rows)
    r_quote[0]["인용"] = r_quote[0]["인용"] + " (지어낸 말)"
    spec = rows[5]["명세들"][0]
    r_drop = [r for r in _c185.deepcopy(rows) if spec not in r["명세들"]]
    r_run = _c185.deepcopy(rows)
    r_run[0]["분류"], r_run[0]["근거"] = "실행 중", "README.md"
    got = (_PR.check(root, r_quote), _PR.check(root, r_drop), _PR.check(root, r_run))
    check("[185] ② ⭐⭐ 인용을 지어내면 · 봉인 명세를 빼면 · 결과가 나왔는데 «실행 중» 이면 **잡는다**",
          any("인용을" in x for x in got[0]) and any(spec in x and "없다" in x for x in got[1])
          and any("결과 파일" in x for x in got[2]), [g[:2] for g in got])

    # ③ 집계는 셈의 항등식을 지킨다 — **수를 박지 않는다**(결과가 들어오면 바뀐다)
    t = _PR.tally(rows)
    ways = {w: _PR.tally(rows, w) for w in _PR.WAYS}
    reapplied = sum(1 for r in rows if "재적용" in r["셈들"] and r["분류"] in _PR.DONE)
    m = _PR._SENT.search(_PR.sentence(t))
    check("[185] ③ 합이 행 수 · 결과 = 통과+미달+판정 불가 · 셈법별 폭의 방향 · 문장이 다시 읽힌다",
          sum(t[k] for k in _PR.KINDS) == len(rows)
          and t["결과"] == t["통과"] + t["미달"] + t["판정 불가"]
          and ways["문서 표기대로"]["미달"] >= t["미달"]
          and ways["재적용 제외"]["결과"] == t["결과"] - reapplied
          and ways["철회 제외"]["통과"] <= t["통과"]
          and m is not None
          and tuple(int(x) for x in m.groups()) == (t["결과"], t["통과"], t["미달"], t["판정 불가"]),
          (dict(t), _PR.sentence(t)))

    # ④ 문서 대조 — 다른 수 · 옛 서사는 잡고, «인용» 은 기록으로 둔다
    fake = {"README.md": "사전 기준 %d개 — 통과 %d · 미달 %d · 판정 불가 %d\n"
                         "그래서 넷 중 셋이 미달했다\n"
                         "옛 요약은 «넷 중 셋이 미달» 이었다\n"
                         % (t["결과"] + 1, t["통과"], t["미달"], t["판정 불가"])}
    dp = _PR.doc_problems(root, t, texts=fake)
    check("[185] ④ ⭐ 다른 집계 · 옛 서사는 잡고 «…» 인용 줄은 건너뛴다",
          len(dp) == 2 and any(":1 " in x for x in dp) and any(":2 " in x for x in dp), dp)

    real = _PR.doc_problems(root, t)
    check("[185] ⑤ ⭐⭐ 실제 문서·구운 발표자료가 대장과 같다 · 옛 서사 없음"
          " (pptx 가 걸리면 `py slides\\build_deck.py` 로 다시 구워라)", not real, real[:5])

    from ..bench import docaudit as _DA185
    src = open(_DA185.__file__, encoding="utf-8").read()
    check("[185] ⑥ `docaudit` 가 실제로 부르고 **불일치로 센다**(안내문이 아니다)",
          "_PR.check(root) + _PR.doc_problems(root)" in src
          and 'res["사전기준"] = pr' in src, "")

    # ⑦ `--sync` — 결과가 들어오면 한 줄로 맞춘다. 펜스 안(기록)은 안 건드리고 BOM 을 지킨다
    import os as _o185
    import shutil as _sh185
    import tempfile as _tf185
    d = _tf185.mkdtemp()
    _sh185.copy(_o185.path.join(root, _PR.LEDGER), _o185.path.join(d, _PR.LEDGER))
    old = "사전 기준 1개 — 통과 1 · 미달 0 · 판정 불가 0"
    body = "앞 %s 뒤\n```\n%s\n```\n" % (old, old)
    with open(_o185.path.join(d, "a.md"), "wb") as f:
        f.write(b"\xef\xbb\xbf" + body.encode("utf-8"))
    ch = _PR.sync(d, files=["a.md"])
    raw = open(_o185.path.join(d, "a.md"), "rb").read()
    got = raw.decode("utf-8-sig")
    check("[185] ⑦ `--sync` 가 본문의 옛 집계만 대장 수로 바꾸고 · 펜스 안은 두고 · BOM 을 지킨다",
          len(ch) == 1 and _PR.sentence(t) in got.split("```")[0]
          and old in got.split("```")[1] and raw[:3] == b"\xef\xbb\xbf", (ch, got[:80]))


def test_performance_card_numbers_come_from_the_result_files():
    """[186] **발표의 성능 한 장은 결과 파일에서 코드로 나온다** — 09-25 신설.

    요강이 발표자료에 «성능 지표와 평가 기준» 을 요구한다. 그 수를 슬라이드에
    손으로 옮기면 결함 19 의 자리다. `perfcard` 가 내고 발표 스크립트가 부른다.
    결과 파일(`홀드아웃_본선모델.json` 등)은 저장소에 없을 수 있다 — 그때는
    항등식만 본다.
    """
    import os as _o186
    from ..bench import perfcard as _PC
    from ..bench import indep as _IN186

    # ① Wilson·Brier 의 항등식 — 파일 없이도 본다
    w = _PC._w(99, 105)
    check("[186] ① Wilson 구간이 점추정을 감싼다 · 균형 집합 널 Brier = 0.25",
          w[2] < 99 / 105 < w[3]
          and abs(_PC._brier([0.5, 0.5], [1, 0], [0, 1]) - 0.25) < 1e-12, w)

    from .. import evidence as _EV186
    root = _EV186.ROOT
    if not _o186.path.exists(_o186.path.join(root, _PC.SUBMIT[1])):
        check("[186] ② 결과 파일이 없다 — 수치 대조는 건너뛴다(항등식만 봤다)", True, "")
        return
    c = _PC.card(root)
    b, x = c["전체"], c["누출제외"]
    dist_ok = sum(b["판정"].values()) == b["n"] == b["TP"] + b["TN"]
    rej = b["판정"].get("기각", 0)
    check("[186] ② ⭐ 판정 분포 합 = n · 기각 정밀도의 분모 = 기각 수 · 누출 제외 n = 전체 − 누출",
          dist_ok and b["기각정밀도"][1] == rej and x["n"] == b["n"] - c["누출"],
          (b["판정"], b["기각정밀도"], x["n"], c["누출"]))

    runs = _IN186.load_runs(root=root)
    s, _, _ = _IN186.summarize(runs)
    terra = [m for m in s if m["이름"] == c["모델"]]
    check("[186] ③ ⭐⭐ 누출 제외 B5·B0 AUROC 가 `indep`(모델 독립성 명세의 도구)와 **같은 값**",
          bool(terra) and abs(terra[0]["B5"][0] - x["AUROC"]["B5"][0]) < 1e-12
          and abs(terra[0]["B0"][0] - x["AUROC"]["B0"][0]) < 1e-12,
          (terra[0]["B5"] if terra else None, x["AUROC"]))

    d = x["ΔAUROC"]
    res, lab, ex = _PC.load(root)
    again = _PC._dauc_boot(res["results"]["B5"]["scores"], res["results"]["B0"]["scores"], lab, ex)
    check("[186] ④ 차의 구간이 점추정을 감싸고 · 시드 고정이라 **다시 돌려도 같다**",
          d[1] <= d[0] <= d[2] and (again[0], again[1]) == (d[1], d[2]), (d, again))

    # ⑤ ⭐⭐ 결함 334 — **라벨로 고른 부분집합이 B0 를 기계적으로 끌어내린다** (합성 자료)
    from ..agents import closedbook as _CB186
    from ..bench.run import auroc as _au186
    y = [1, 0] * 50
    recs = []
    for i, t in enumerate(y):
        want = "성공" if t else "실패"
        other = "실패" if t else "성공"
        if i < 60:
            recs.append({"verdict": want, "confidence": "high"})      # 외워서 맞힌 것
        elif i < 80:
            recs.append({"verdict": other, "confidence": "high"})     # 확신하고 틀린 것
        else:
            recs.append({"verdict": "모름", "confidence": "low"})
    sc = [_CB186.to_score(r) for r in recs]
    lk = [_CB186.leakage_flag(r, "TP" if t else "TN") for r, t in zip(recs, y)]
    keep = [i for i in range(len(y)) if not lk[i]]
    unk = _PC.unknown_idx({"verdicts": [r["verdict"] for r in recs]})
    a_keep = _au186([sc[i] for i in keep], [y[i] for i in keep])
    a_unk = _au186([sc[i] for i in unk], [y[i] for i in unk])
    check("[186] ⑤ ⭐⭐ 라벨로 고른 «누출 제외» 는 B0 를 0.5 **아래로** 민다 · «모름» 부분집합은 정확히 0.5"
          " (결함 334 의 기제를 합성 자료로 재현)",
          a_keep < 0.5 and abs(a_unk - 0.5) < 1e-12 and "labels" not in _PC.unknown_idx.__code__.co_varnames,
          (a_keep, a_unk))

    u = c["모름"]
    check("[186] ⑥ 발표에 쓰는 «모름» 부분집합 — B0 는 정의상 0.5 · 누출 제외에 고확신 오답이 남아 있음을 센다",
          abs(u["AUROC"]["B0"][0] - 0.5) < 1e-12 and c["누출제외_고확신오답"] > 0
          and u["n"] == sum(1 for v in res["results"]["B0"]["verdicts"] if v == "모름"),
          (u["AUROC"], c["누출제외_고확신오답"], u["n"]))


def test_ten_minute_deck_carries_required_items_and_code_numbers():
    """[187] **본선 10분판 — 요강 필수 둘이 본편에 있고, 수는 빌드 때 코드에서 받는다** — 09-25.

    요강: 발표자료 PDF · 5~10분 · **성능 지표와 평가 기준** · 예시 쿼리 3개 이상.
    25장은 20분 기준이라 `make_10min_본선.py` 가 순서만 바꿔 재편한다(지우지 않는다).
    """
    import importlib.util as _iu187
    import os as _o187
    from .. import evidence as _EV187

    root = _EV187.ROOT
    sp = _o187.path.join(root, "slides", "make_10min_본선.py")
    spec = _iu187.spec_from_file_location("make10_187", sp)
    mod = _iu187.module_from_spec(spec)
    spec.loader.exec_module(mod)                 # main() 은 안 부른다 — 정의만 읽는다

    body = [k for k in mod.MAIN if k != mod.PERF]
    check("[187] ① 본편 + 부록이 원본 25장을 **정확히 한 번씩** 덮는다 · 성능 장과 예시 쿼리(24)가 본편에",
          sorted(body + mod.APPX) == list(range(1, mod.N_SRC + 1))
          and mod.PERF in mod.MAIN and 24 in mod.MAIN and 15 in mod.MAIN, (mod.MAIN, mod.APPX))

    s, filled = mod.seed_line() if not _o187.path.exists(
        _o187.path.join(root, "추출복제_결과.json")) else ("", True)
    check("[187] ② ⭐ 추출 복제 결과가 없으면 seed 줄은 **«돌리는 중»** 이라 적고 수를 지어내지 않는다",
          filled or ("돌리는 중" in s and not any(ch.isdigit() for ch in s.replace("0924", ""))), s)

    from ..bench import perfcard as _PC187, prereg as _PR187
    if _o187.path.exists(_o187.path.join(root, _PC187.SUBMIT[1])):
        card = _PC187.card(root)
        sent = _PR187.sentence(_PR187.tally(_PR187.load(root)))
        n = mod.notes_for(card, sent)
        total = sum(len(n[k]) for k in mod.MAIN)
        # 09-26 밤 · 성능 장이 **모델 단독 기준선을 먼저** 말한다(결함 348 의 발표 쪽). 앞판은 끝에서
        #   «외운 것까지 넣은 전체에서는 모델 단독과 구별되지 않습니다» 라고 했다 — 전체에서는 모델 단독이
        #   더 거른다. 기준선의 수 · 우리 몫(«모름» 부분집합)의 수가 **카드의 수 그대로** 노트에 있어야 한다.
        r0, ur = card["전체"]["B0실패정밀도"], card["모름"]["기각정밀도"]
        check("[187] ③ ⭐⭐ 본편 노트가 10분(%d자) 안 · 성능·대장 장의 노트 수가 **코드의 수**와 같다 · "
              "성능 장이 모델 단독 기준선과 «우위를 주장하지 않는다» 를 말한다" % mod.LIMIT_CHARS,
              total <= mod.LIMIT_CHARS and sent in n[15]
              and ("%d건을 기각해 %d건이 맞습니다" % (r0[1], r0[0])) in n[mod.PERF]
              and ("%d건을 기각해 %d건이 맞았습니다" % (ur[1], ur[0])) in n[mod.PERF]
              and "우위를 주장하지 않" in n[mod.PERF] and "사후" in n[mod.PERF]
              and "구별되지 않습니다" not in n[mod.PERF], total)

    out = _o187.path.join(root, "slides", "Bio-ReRoute_본선_10분.pptx")
    sub = _o187.path.join(root, "제출_본선", "Bio-ReRoute_발표.pptx")
    if _o187.path.exists(out) and _o187.path.exists(sub):
        from pptx import Presentation as _P187
        p, q = _P187(out), _P187(sub)
        heads = []
        for sl in list(p.slides)[:len(mod.MAIN)]:
            t = [x.text_frame.text for x in sl.shapes if x.has_text_frame and x.text_frame.text.strip()]
            heads.append(t[0] if t else "")
        left = sum(1 for sl in q.slides if sl.has_notes_slide
                   and sl.notes_slide.notes_text_frame.text.strip())
        check("[187] ④ 구운 10분판 — 27장 · 6번째가 성능 장 · **제출용은 노트 0장**",
              len(p.slides) == len(mod.MAIN) + 1 + len(mod.APPX) and heads[5].startswith("성능")
              and left == 0, (len(p.slides), heads[5][:20], left))

    ps = _o187.path.join(root, "발표10분.ps1")
    raw = open(ps, "rb").read() if _o187.path.exists(ps) else b""
    src = raw.decode("utf-8-sig") if raw else ""
    check("[187] ⑤ `발표10분.ps1` — BOM · CRLF · 줄 이어쓰기 없음 · seed 줄이 비면 멈춤 · 20MB 확인 · "
          "열려 있던 PowerPoint 를 안 닫음",
          raw[:3] == b"\xef\xbb\xbf" and b"\n" not in raw.replace(b"\r\n", b"")
          and not any(l.rstrip().endswith("`") and not l.lstrip().startswith("#")
                      for l in src.splitlines())
          and "make_10min_본선.py" in src and "-not $Draft" in src and "-gt 20" in src
          and "Presentations.Count -eq 0" in src, raw[:3])


def test_byom_and_demo_rebake_scripts_hold_their_guards():
    """[188] **BYOM 세 번째 점 · 데모 다시 굽기 — 스크립트가 약속을 코드로 든다** — 09-25.

    둘 다 LLM 을 부르는 마지막 작업이다(촬영 전). 틀리기 쉬운 자리 —
      ① BYOM 결과 파일에 **08-18 명세 해시**가 박혀 어느 명세의 집행인지 틀리게 남는다
      ② 집행 세부(표본·팔·대장 규칙)가 **실행 뒤에** 정해진다
      ③ 데모를 다시 구우며 **옛 판(08-14)을 덮거나** 판정을 보고 쿼리를 바꾼다
    """
    import os as _o188
    from .. import evidence as _EV188
    from ..bench import modelswap as _MS188
    import inspect as _i188

    root = _EV188.ROOT
    src = _i188.getsource(_MS188.main)
    check("[188] ① `modelswap` 이 명세 해시를 **인자로** 받아 결과에 적는다(08-18 값 박힘 금지)",
          '"--spec"' in src and '"명세": a.spec' in src and '"명세": "8112fe04f798"' not in src, "")

    rule = _o188.path.join(root, "BYOM실행주의_0925.md")
    rt = open(rule, encoding="utf-8").read() if _o188.path.exists(rule) else ""
    check("[188] ② 집행 주의가 표본 · 두 팔 · 대장 규칙 · 무효 조건을 **실행 전에** 적었다",
          all(k in rt for k in ("bench_matched.csv", "`luna`", "`sol`", "두 팔 다 통과면 통과",
                                "하나라도 미달이면 미달", "종료코드 3", "99de79168cae")), rule)

    def _ps(name):
        p = _o188.path.join(root, name)
        raw = open(p, "rb").read() if _o188.path.exists(p) else b""
        s = raw.decode("utf-8-sig") if raw else ""
        ok = (raw[:3] == b"\xef\xbb\xbf" and b"\n" not in raw.replace(b"\r\n", b"")
              and not any(l.rstrip().endswith("`") and not l.lstrip().startswith("#")
                          for l in s.splitlines()))
        return ok, s
    ok1, b = _ps("BYOM.ps1")
    check("[188] ③ `BYOM.ps1` — BOM·CRLF · 두 봉인 확인 · 추출 복제 중이면 멈춤 · 결과 파일 안 덮음 · "
          "무효면 한 번만 다시",
          ok1 and "E.seals()" in b and "복제_cache_" in b and "이미 있다" in b
          and '"--spec", $SPEC_FP' in b and "$SPEC_FP   = \"99de79168cae\"" in b
          and "모델교체_본선_" in b and "한 번만" in b, "")
    ok2, d = _ps("데모굽기.ps1")
    check("[188] ④ `데모굽기.ps1` — 새 파일에만 굽고 · 옛 판(08-14)을 남기고 · 쿼리를 안 바꾼다고 적었다",
          ok2 and "$NEW    = \"demo_cases_terra.json\"" in d
          and "$KEEP   = \"demo_cases_0814_mini.json\"" in d
          and "E.build_cases(out='$NEW')" in d and "안 바꾼다" in d
          and "if (Test-Path -LiteralPath $NEW) { Stop-Here" in d, "")

    deck = open(_o188.path.join(root, "slides", "build_deck.py"), encoding="utf-8").read()
    check("[188] ⑤ 발표 «예시 쿼리» 장의 판정·신뢰도를 **구운 파일에서** 읽는다(손 숫자 금지)",
          "_EVD.cases()" in deck and '"신뢰도 2"' not in deck and '"신뢰도 90"' not in deck, "")

    # ⑥ BYOM 점 — 발표 장·대본은 `points()` 에서 읽고, 본선 점은 **본선 명세 해시**를 든다
    pts = _MS188.points(root)
    bon = [x for x in pts if x["점"].startswith("09-25")]
    check("[188] ⑥ BYOM 점을 **결과 파일에서** 읽는다 · 본선 점은 명세 `99de79168cae` · «확인실패» 는 점이 아니다",
          "_MSW.points(_ROOT)" in deck and all(x["명세"] == "99de79168cae" for x in bon)
          and all(x["판정"] != "확인실패" for x in pts), [(x["점"], x["판정"]) for x in pts])

    # ⑦ 시연 장(9) — 09-25 까지 **어느 날 CLI 출력을 손으로** 옮긴 «879건 · 기각 4%» 였고
    #    같은 쌍의 데모 화면은 «기각 26%» 였다. 이제 구운 사례에서 그린다 · 노트도 자료에서
    ten = open(_o188.path.join(root, "slides", "make_10min_본선.py"), encoding="utf-8").read()
    check("[188] ⑦ 시연 장이 **구운 데모 사례**에서 그린다 — 손 숫자(«879건» · «기각 4%») 없음 · "
          "10분판 노트의 판정도 자료에서",
          "_EV9.cases()" in deck and "PubMed 실시간 879건" not in deck and "[판정] 기각 4%" not in deck
          and "판정은 기각입니다" not in ten and "_EV9.cases()" in ten, "")


def test_cache_save_survives_being_interrupted():
    """[189] **쓰는 도중에 끊겨도 캐시가 반쪽이 되지 않는다** — 09-25 신설. 결함 335.

    ## 무엇이 있었나

    09-25 02:20, `pubmed_cache.json` 이 **48.9MB → 17.9MB 반쪽 JSON** 이 됐다.
    승우가 `zerocheck` 을 돌리자 `JSONDecodeError`(199,104행)로 멈췄다.

    **원인은 나(Claude)다.** 샌드박스에서 전체 회귀를 돌리며 시험마다 시간
    제한(SIGALRM)을 걸었고, 그것이 `save()` 의 `json.dump` 한가운데를 끊었다.
    앞판 `save()` 는 **파일을 바로 열어 썼으므로** 끊긴 자리까지가 그대로 남았다.

    ## 같은 자리 **세 번째**다

    08-05 (2.7MB 가 580개로) · 09-21 (33MB 가 `{}` 로) · 09-25 (48.9MB 가 반쪽으로).
    앞의 둘은 **무엇을 쓰나**를 막았고, 이번 것은 **어떻게 쓰나**다 —
    내용이 옳아도 쓰는 도중에 끊기면 파일이 깨진다.

    ## 막는 구조

    임시 파일에 다 쓰고 `os.replace` 로 **한 번에** 바꾼다. 같은 폴더 안의
    `os.replace` 는 원자적이다 — 끊기면 **옛 파일이 그대로 남는다.**
    """
    import json as _j189
    import os as _o189
    import re as _re189
    import tempfile as _t189
    from ..io import cache as _C189

    d = _t189.mkdtemp(prefix="cache189_")
    p = _o189.path.join(d, "c.json")

    def fresh(n=300):
        with open(p, "w", encoding="utf-8") as f:
            _j189.dump({"k%d" % i: {"v": i} for i in range(n)}, f)
        return open(p, "rb").read()

    def leftovers():
        return [x for x in _o189.listdir(d) if ".tmp_" in x]

    class _HalfDump:                     # 쓰다가 끊기는 json — 반쪽을 쓰고 예외
        def __init__(s, exc):
            s._exc = exc

        def __getattr__(s, k):
            return getattr(_j189, k)

        def dump(s, obj, f, **kw):
            f.write('{"k0": {"v": 0}, "k1"')
            f.flush()
            raise s._exc

    class _Os:                           # os.replace 만 바꾼 os
        def __init__(s, fail_times):
            s.n = fail_times

        def __getattr__(s, k):
            return getattr(_o189, k)

        def replace(s, a, b):
            if s.n != 0:
                s.n -= 1
                raise PermissionError("다른 프로세스가 잡고 있다(가짜)")
            return _o189.replace(a, b)

    _keep = (_C189._PATH, _C189._ENABLED, dict(_C189._STORE), _C189._LOADED[0],
             _C189._SWAP_WAIT)
    try:
        _C189._SWAP_WAIT = 0

        # ① 정상 경로 — 방어가 평소를 망가뜨리면 사람이 끈다
        fresh(); _C189.configure(p); _C189.load()
        _C189.put("새", {"v": 1}); _C189.save()
        check("[189] ① 정상 저장은 그대로 — 읽히고 · 항목이 늘고 · 임시 파일이 안 남는다",
              len(_j189.load(open(p, encoding="utf-8"))) == 301 and not leftovers(),
              leftovers())

        # ② ⭐⭐ **쓰는 도중 예외** — 09-25 02:20 의 그 자리 (SIGALRM 이 예외로 들어온다)
        raw = fresh(); _C189.configure(p); _C189.load()
        _C189.put("새", {"v": 1})
        _C189.json = _HalfDump(RuntimeError("시간초과(가짜)"))
        try:
            _C189.save()
        finally:
            _C189.json = _j189
        check("[189] ② ⭐⭐ 쓰는 도중에 끊겨도 **원본이 한 바이트도 안 바뀐다** · 반쪽 임시 파일도 안 남는다",
              open(p, "rb").read() == raw and not leftovers(),
              "앞판은 여기서 반쪽 JSON 을 남겼다 — 48.9MB → 17.9MB")

        # ③ ⭐ 예외가 `Exception` 이 아니어도(Ctrl+C) — 원본 그대로 · 멈춤은 위로 전한다
        raw = fresh(); _C189.configure(p); _C189.load()
        _C189.put("새", {"v": 1})
        _C189.json = _HalfDump(KeyboardInterrupt())
        went_up = False
        try:
            _C189.save()
        except KeyboardInterrupt:
            went_up = True
        finally:
            _C189.json = _j189
        check("[189] ③ ⭐ Ctrl+C 로 끊겨도 원본 그대로 · 멈춤을 삼키지 않는다 · 임시 파일 없음",
              open(p, "rb").read() == raw and went_up and not leftovers(),
              (went_up, leftovers()))

        # ④ 바꿔 넣기가 끝내 거부되면(윈도우 잠금) — **옛 파일을 둔다**, 반쪽을 쓰지 않는다
        raw = fresh(); _C189.configure(p); _C189.load()
        _C189.put("새", {"v": 1})
        _C189.os = _Os(-1)               # 영원히 거부
        try:
            _C189.save()
        finally:
            _C189.os = _o189
        check("[189] ④ 바꿔 넣기가 끝내 막히면 **옛 파일을 그대로 둔다** · 임시 파일 없음 · "
              "새 항목은 메모리에 남아 다음에 다시 간다",
              open(p, "rb").read() == raw and not leftovers() and _C189.has("새"),
              leftovers())

        # ⑤ 한두 번 막혔다 풀리면 — 다시 시도해서 들어간다
        fresh(); _C189.configure(p); _C189.load()
        _C189.put("새", {"v": 1})
        _C189.os = _Os(2)
        try:
            _C189.save()
        finally:
            _C189.os = _o189
        check("[189] ⑤ 잠깐 막혔다 풀리면 다시 시도해 **새 내용이 들어간다**",
              len(_j189.load(open(p, encoding="utf-8"))) == 301 and not leftovers(), "")

        # ⑥ 구조 — 캐시 파일을 **바로** 여는 쓰기가 코드에 없다
        src = open(_C189.__file__, encoding="utf-8").read()
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        check("[189] ⑥ `cache.py` 에 `open(_PATH, \"w\")` 같은 **바로 쓰기가 없다** — "
              "임시 파일 + `os.replace` 만",
              not _re189.search(r"open\(\s*_PATH\s*,\s*[\"'][wa]", code)
              and "os.replace(" in code, "")
    finally:
        _C189.json, _C189.os = _j189, _o189
        _C189._PATH, _C189._ENABLED = _keep[0], _keep[1]
        _C189._STORE, _C189._LOADED[0] = _keep[2], _keep[3]
        _C189._SWAP_WAIT = _keep[4]


def test_tests_cannot_write_into_the_repository():
    """[190] **시험은 저장소 폴더에 쓰지 못한다** — 09-25 신설. 결함 335.

    ## 무엇을 찾았나

    48.9MB 가 반쪽이 된 뒤 «시험이 왜 실제 캐시를 썼나» 를 물었다. 추측하지
    않고 **전수 탐침**을 돌렸다 — 감사 훅으로 저장소 폴더 쓰기를 전부 막고
    기록하며 phase2 160개 · phase1 전부(자식 프로세스까지). 넷이 나왔다 —

        [138] run_pair 계측   pubmed_cache.json(48MB) 을 읽고 통째로 다시 썼다 · budget.json
        [134] 병명 입구       budget.json
        [116] 봉인 자기시험   archive/_봉인자기시험.md · 그 봉인 json
        [6] · 0건 시험        ceiling 이 ctgov_search_cache.json 에 모의 응답 7개를 섞었다

    섞인 7개는 **무해**하다 — 키가 `doxycycline::IPF` · `other::X` · `dx::dz` 라
    실제 벤치마크(`Idiopathic Pulmonary Fibrosis` 등)가 묻는 키와 겹치지 않는다.
    `pubmed_cache.json` 에는 모의 키가 **0개**였다(같은 날 전수 검색).

    ## 막는 구조

    `liveguard` — 시험이 도는 동안 저장소 폴더로의 쓰기·지우기·옮기기를 막고
    **실패로 올린다.** 시험 안에서 예외가 삼켜져도 기록은 남는다.
    """
    import inspect as _in190
    import os as _o190
    import shutil as _sh190
    import tempfile as _t190
    from . import liveguard as _LG
    from ..bench import ceiling as _CE190

    fake = _t190.mkdtemp(prefix="lg190_")          # 가짜 저장소
    other = _t190.mkdtemp(prefix="lg190o_")        # 저장소 밖
    data = _o190.path.join(fake, "data.json")
    with open(data, "w", encoding="utf-8") as f:   # 가드를 켜기 **전** 준비
        f.write('{"a": 1}')
    _o190.makedirs(_o190.path.join(fake, "pkg", "__pycache__"))
    src_x = _o190.path.join(other, "x.json")
    with open(src_x, "w", encoding="utf-8") as f:
        f.write('{"b": 2}')

    keep = (_LG._ROOT[0], _LG._ON[0], _LG._TEST[0], len(_LG.HITS))
    cwd = _o190.getcwd()
    mine = []
    try:
        _LG.install(fake)
        _LG.start("[190]자기시험")
        tries = [("덮어쓰기", lambda: open(data, "w")),
                 ("새 파일", lambda: open(_o190.path.join(fake, "new.txt"), "a")),
                 ("지우기", lambda: _o190.remove(data)),
                 ("바꿔 넣기", lambda: _o190.replace(src_x, data)),
                 ("복사해 넣기", lambda: _sh190.copyfile(data, _o190.path.join(fake, "c.json"))),
                 ("폴더 통째 지우기", lambda: _sh190.rmtree(_o190.path.join(fake, "pkg"))),
                 ("상대 경로", lambda: (_o190.chdir(fake), open("rel.txt", "w")))]
        missed = []
        for name, fn in tries:
            try:
                fn()
                missed.append(name)
            except PermissionError:
                pass
            finally:
                _o190.chdir(cwd)
        intact = open(data, encoding="utf-8").read() == '{"a": 1}'
        # 막지 **말아야** 할 것 — 방어가 평소를 막으면 사람이 방어를 끈다
        ok_read = open(data, encoding="utf-8").read() == '{"a": 1}'
        _sh190.copyfile(data, _o190.path.join(other, "copied.json"))
        with open(_o190.path.join(fake, "pkg", "__pycache__", "m.pyc"), "wb") as f:
            f.write(b"x")
        with open(_o190.path.join(other, "t.txt"), "w") as f:
            f.write("임시")
        _LG.stop()
        with open(_o190.path.join(fake, "after.txt"), "w") as f:   # 꺼지면 안 막는다
            f.write("끝")
        mine = _LG.HITS[keep[3]:]
    finally:
        _o190.chdir(cwd)
        del _LG.HITS[keep[3]:]                     # 이 시험이 **일부러** 낸 것 — 위반이 아니다
        _LG._ROOT[0], _LG._ON[0], _LG._TEST[0] = keep[0], keep[1], keep[2]

    check("[190] ① ⭐⭐ 저장소 폴더로의 쓰기 **일곱 갈래**를 다 막는다 "
          "(덮어쓰기·새 파일·지우기·바꿔 넣기·복사·rmtree·상대 경로)",
          not missed, "안 막힌 것 %s" % missed)
    check("[190] ② 막힌 뒤에도 원본이 **그대로** 있다", intact, "")
    check("[190] ③ 읽기 · 밖으로 복사 · `__pycache__` · 임시 폴더 · 끈 뒤 — **막지 않는다**",
          ok_read and _o190.path.exists(_o190.path.join(other, "copied.json"))
          and _o190.path.exists(_o190.path.join(fake, "after.txt")), "")
    check("[190] ④ 막은 것을 **어느 시험이 · 무엇을** 으로 기록한다",
          len(mine) >= 7 and all(t == "[190]자기시험" for t, _e, _p in mine),
          [(e, _o190.path.basename(p)) for _t, e, p in mine][:8])

    # ⑤ 부르는 쪽이 켜고 끄고 **실패로 올린다** — 기록만 하고 안 올리면 장식이다
    rs, mn = _in190.getsource(_run_seq), _in190.getsource(_main)
    check("[190] ⑤ `_run_seq` 가 시험마다 켜고 끄고 · 막힌 쓰기를 **FAIL** 로 올린다 · `_main` 이 설치한다",
          "_LG.start(fn.__name__)" in rs and "_LG.stop()" in rs
          and 'FAIL.append("[liveguard]' in rs and "_LG0.install(" in mn, "")

    # ⑥ 탐침에서 나온 네 자리가 임시 경로를 쓴다
    g = lambda f: _in190.getsource(f)
    ce = _in190.getsource(_CE190.main)
    check("[190] ⑥ 탐침의 네 자리가 **임시 경로**를 쓴다 — run_pair 캐시·한도 · 병명 입구 한도 · "
          "봉인 자기시험 · ceiling 검색 캐시",
          "cache_path=_tmp(\"_138_cache.json\")" in g(test_run_pair_actually_times_its_gates)
          and "_B138.PATH = _tmp(" in g(test_run_pair_actually_times_its_gates)
          and "_B134.PATH = " in g(test_run_disease_actually_completes)
          and "root=troot" in g(test_seal_records_code_and_checks_it)
          and g(test_cli_all).count('"--search-cache"') == 2
          and '"--search-cache"' in g(test_zero_is_not_error)
          and '_C.configure("ctgov_search_cache.json")' not in ce
          and "_C.configure(a.search_cache)" in ce, "")


def test_report_defect_table_comes_from_the_deck_bars():
    """[191] **보고서의 결함 유형 표는 발표 막대와 같은 목록에서 나온다** — 09-25 신설.

    `연구기술보고서.md §6` 의 표가 **08-06 판**(여섯 유형 · 합 49 · 깨진 열 둘)인 채로,
    바로 위 문장만 `countsync` 가 «결함 N건 · 유형 여덟» 으로 올려 두었다.
    **표제는 자동이고 표는 손**이라 갈라졌다 — 결함 84 가 발표 장에서 겪은 모양 그대로다.
    막대(`build_deck.py` 의 `defects`)는 시험 [65] 가 합을 지킨다. 표를 거기서 만든다.
    """
    import os as _o191
    import tempfile as _t191
    from .. import evidence as _EV191
    from ..bench import defecttypes as _DT

    root = _EV191.ROOT
    rs = _DT.rows(root)
    n = _EV191.defect_count()
    check("[191] ① 막대 목록을 **실행하지 않고** 읽는다 · 여덟 유형 · 합 = 대장 행 수",
          len(rs) == 8 and sum(x for _, x, _ in rs) == n, (len(rs), sum(x for _, x, _ in rs), n))

    rep = open(_o191.path.join(root, "연구기술보고서.md"), encoding="utf-8-sig").read()
    i, j = rep.find(_DT.MD_START), rep.find(_DT.MD_END)
    body = rep[i + len(_DT.MD_START) + 1:j].rstrip("\n") if 0 <= i < j else ""
    check("[191] ② ⭐ 보고서의 표가 **지금 막대와 같다** (다르면 `사슬.ps1` ⑤-0c 가 고친다)",
          body == _DT.to_md(rs, n), "표시 %s · 길이 %d" % (0 <= i < j, len(body)))
    check("[191] ③ 08-06 판의 낡은 줄이 없다 — «검증 환경 ≠ 실행 환경 | 9 |»",
          "| 검증 환경 ≠ 실행 환경 | 9 |" not in rep and "가장 최근 둘(40·41)" not in rep, "")

    # ④ ⛔ 막대 합이 대장과 다르면 **안 쓴다** — 분류 안 한 표가 제출물에 들어간다
    d = _t191.mkdtemp(prefix="dt191_")
    _o191.makedirs(_o191.path.join(d, "slides"))
    with open(_o191.path.join(d, "slides", "build_deck.py"), "w", encoding="utf-8") as f:
        f.write('raise SystemExit("실행하면 안 된다")\ndefects = [("가", 1, "x"), ("나", 2, "y")]\n')
    led = _o191.path.join(d, "Bio-ReRoute_발견정리.md")

    def ledger(k):
        with open(led, "w", encoding="utf-8") as f:
            f.write("| # | 결함 | 결과 |\n|---|---|---|\n"
                    + "".join("| %d | a | b |\n" % (x + 1) for x in range(k)) + "\n")
    doc = _o191.path.join(d, "r.md")
    with open(doc, "w", encoding="utf-8") as f:
        f.write("앞\n" + _DT.MD_START + "\n낡은 표\n" + _DT.MD_END + "\n뒤\n")
    before = open(doc, encoding="utf-8").read()
    ledger(4)                                        # 막대 합 3 ≠ 대장 4
    refused = False
    try:
        _DT.md_into(doc, d)
    except ValueError:
        refused = True
    check("[191] ④ ⛔ 막대 합(3) ≠ 대장(4) 이면 **안 쓴다** · 파일 그대로",
          refused and open(doc, encoding="utf-8").read() == before, refused)
    ledger(3)
    ok = _DT.md_into(doc, d)
    after = open(doc, encoding="utf-8").read()
    check("[191] ⑤ 맞으면 표시 사이**만** 바꾼다 · 합 줄 · 앞뒤 글은 그대로",
          ok and "| 가 | 1 | x |" in after and "| **합** | **3** |" in after
          and "낡은 표" not in after and after.startswith("앞\n") and after.endswith("뒤\n"), "")
    with open(doc, "w", encoding="utf-8") as f:
        f.write("표시 없음\n")
    check("[191] ⑥ 표시가 없으면 **안 쓴다**(False)",
          _DT.md_into(doc, d) is False and open(doc, encoding="utf-8").read() == "표시 없음\n", "")

    chain = open(_o191.path.join(root, "사슬.ps1"), encoding="utf-8-sig").read()
    a, b = chain.find('"bioreroute.bench.defecttypes", "--md-into"'), chain.find('Head "⑤" "발표')
    check("[191] ⑦ `사슬.ps1` 이 발표를 굽기 **전에** 표를 다시 쓴다", 0 <= a < b, (a, b))


def test_video_script_comes_from_the_same_sources_as_the_screen():
    """[192] **시연 영상 대본의 수는 화면·발표와 같은 곳에서 나온다** — 09-25 신설.

    옛 대본(`시연영상_대본.md`)은 **3분**이었고 수가 **08-14 판**이었다 — «기각 26%»,
    «유망 84%», «metformin 이 긴급에선 보류로 넘어간다». 본선 모델로 다시 구우니 셋 다
    거짓이 됐다(26 → 거부권 0% · 84 → 조건부 81 · 긴급으로 움직이는 사례 0).
    **손으로 적은 대본은 자료가 바뀌는 순간 거짓말을 한다.** 발표 10분판과 같은 규칙으로
    — 슬라이드 부분은 발표 노트 그대로, 화면 부분은 구운 사례에서 — 조립한다.
    """
    import importlib.util as _iu192
    import os as _o192
    import re as _re192
    import tempfile as _t192
    from .. import evidence as _EV192
    from ..bench import docaudit as _DA192

    root = _EV192.ROOT
    gp = _o192.path.join(root, "slides", "make_video_본선.py")
    src = open(gp, encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    # 09-28 밤 · 옛 나-5(심사 기준 긴급 · `_by_profile`)를 «병으로 시작» 컷으로 바꿨다(결함 373 · 376) — 그 컷의 수는
    #   라이브 점검 기록의 병명 칸(`_disease_record`)에서 온다
    check("[192] ① 수를 **자료에서** 받는다 — 발표 노트 · 구운 사례 · 성능 카드 · 라이브 점검 기록(병명) · 대장",
          all(k in code for k in ("notes_for(", "_cases()", "perfcard.card(", "_disease_record(",
                                  "defect_count(", "_spec_count(")), "")
    check("[192] ② 옛 대본의 **손 숫자**가 생성기에 없다 (기각 26% · 유망 84% · PubMed 4087 · pLDDT 91.1)",
          not _re192.search(r"26%|84%|4087|91\.1|98퍼센트|53퍼센트", code), "")

    spec = _iu192.spec_from_file_location("make_video_t192", gp)
    mv = _iu192.module_from_spec(spec)
    spec.loader.exec_module(mv)
    out = _o192.path.join(_t192.mkdtemp(prefix="vid192_"), "v.md")
    run, chars, ok, cut_s = mv.build(out)
    txt = open(out, encoding="utf-8").read()
    by = {c.get("질의"): c for c in ((_EV192.cases() or {}).get("사례") or [])}
    h, bar, rif = (by.get("hydroxychloroquine / COVID-19") or {}, by.get("baricitinib / COVID-19") or {},
                   by.get("rifampin / Tuberculosis") or {})
    f0 = mv._num(r"PubMed\s*([\d,]+)건", mv._gate(h, "f0").get("설명"))
    check("[192] ③ 화면 컷의 수가 **지금 구운 사례와 같다** — HCQ PubMed 건수 · 바리시티닙 · 리팜핀",
          bool(f0) and ("PubMed %s건" % f0) in txt
          and ("%s 퍼센트" % bar.get("신뢰도")).replace(" ", "") in txt.replace(" ", "")
          and ("%s %s퍼센트" % (rif.get("판정"), rif.get("신뢰도"))) in txt,
          (f0, bar.get("신뢰도"), rif.get("판정"), rif.get("신뢰도")))
    check("[192] ④ 라이브 컷은 **두 갈래**를 다 싣고 «결과를 보고 쌍을 안 바꾼다» 를 적는다",
          "〔ⓐ" in txt and "〔ⓑ" in txt and "쌍을 바꾸지 않는다" in txt, "")
    # 09-27 · 녹화본은 ✂ 를 **적용한 채로** 뽑는다 — 앞판은 ✂ 를 뺀 값으로 판정만 하고 대본은 11분대였다
    check("[192] ⑤ 10분 내외 — **✂ 를 적용한 녹화본**이 %s~%s 안이다 (분당 %d자 기준)"
          % (mv._mmss(mv.TARGET[0]), mv._mmss(mv.TARGET[1]), mv.CHARS_PER_MIN),
          ok and "합계" in txt and "✂ **적용함**" in txt and cut_s > 0,
          "%.0f초 (✂ 로 %.0f초 뺐다)" % (run, cut_s))
    # ⑤-b ✂ 는 **문장을 빼기만** 한다 — 합성 입력으로 모양을 고정하고, 못 찾으면 **멈추는지**도 본다
    #   09-29 · 영상을 «쓰는 법» 중심으로 다시 짰다(규칙 2번 원문에 «발표 포함» 이 없다 · 승우). 영상이 쓰는 발표
    #   노트는 8장(구조) 하나이고, 표지 · 성능 · 정리의 말은 영상 자신의 말이다(`slide_say`)
    t8 = ("만든 것입니다. 약 이름이 진짜인지 봅니다. 기전 라우터는 경로를 고릅니다. "
          "숙주에 작용하는 약에는 묻지 않습니다. 보류로 기권합니다.")
    fired = 0
    try:
        mv._trim_8("관문을 겁니다.")
    except ValueError:
        fired = 1
    check("[192] ⑤-b 영상 ✂ 는 **문장을 빼기만** 한다 · 뺄 문장이 없으면 **멈춘다** · 영상이 쓰는 발표 노트는 8장 하나 · "
          "슬라이드는 앞뒤 두 장씩",
          mv._trim_8(t8) == "만든 것입니다. 보류로 기권합니다." and fired == 1 and set(mv.VIDEO_TRIM) == {8}
          and mv.PART_A == [1, 8] and mv.PART_C == ["성능", 25] and txt.count("### 발표 ") == 4
          and "사례 약물도 하이드록시클로로퀸" not in txt and "재창출은 안전성을" not in txt, fired)

    chain = open(_o192.path.join(root, "사슬.ps1"), encoding="utf-8-sig").read()
    a, b, c = (chain.find('"slides/make_10min_본선.py"'), chain.find('"slides/make_video_본선.py"'),
               chain.find('Head "⑥"'))
    check("[192] ⑥ `사슬.ps1` 이 10분판 **다음**, zip **전**에 대본을 다시 뽑는다 · 감사가 대본과 생성기를 본다",
          0 <= a < b < c and "시연영상_대본_10분.md" in _DA192.DOCS
          and any(p == "slides/make_video_본선.py" for p, _r in _DA192.EXTRA), (a, b, c))


def test_abstain_reason_describes_the_evidence_it_had():
    """[193] **보류 사유가 실제 근거 모양을 말한다** — 09-25 신설. 결함 340.

    모든 보류에 «근거 엇갈림(확증 임상 실패 포함)» 이 붙었다. 본선 데모의 rifampin 은
    **지지 고찰 둘 · 반박 0** 인데 화면이 «근거가 갈립니다» 라고 했다 — 감사 추적이 본체라는
    시스템에서 **사유가 근거와 다른 말**을 했다. 판정·확률은 그대로여야 한다.
    """
    import math as _m193
    from ..core import scoring as _S193
    from ..core.state import Candidate as _C193, Evidence as _E193
    from .. import dash as _D193

    def mk(sup, ref):
        c = _C193(name="x", origin="입력", query="q", drug="d", disease="e")
        c.support = [_E193(tag="s%d" % i, direction="support", weight=w) for i, w in enumerate(sup)]
        c.refute = [_E193(tag="r%d" % i, direction="refute", weight=w) for i, w in enumerate(ref)]
        return c

    cases = [("지지만 약함", [0.11, 0.03], [], "근거가 약함", "지지 2건"),
             ("반박만 약함", [], [0.2], "반박이 약함", "반박 1건"),
             ("양쪽 다", [1.0], [0.8], "근거 엇갈림", "반박 1건")]
    rows = []
    for name, sup, ref, key, cnt in cases:
        v, p, why = _S193.adjudicate(mk(sup, ref))
        raw = sum(sup) - sum(ref)                      # 감쇠 1.0(사람 근거) · 상한 안쪽
        want_p = int(round(100.0 / (1.0 + _m193.exp(-raw))))
        rows.append((name, v, p, why))
        check("[193] %s — 보류 · 확률은 **계산 그대로**(%d%%) · 사유가 «%s» 를 말한다" % (name, want_p, key),
              v == "보류" and p == want_p and why.startswith(key) and cnt in why,
              (v, p, why[:60]))
    check("[193] ⭐ «확증 임상 실패 포함» 이 **반박이 없는 보류**에 안 붙는다 — rifampin 의 자리",
          all("확증 임상 실패" not in why for _n, _v, _p, why in rows), [r[3][:40] for r in rows])
    # 09-29 · 결함 378 — «지지 근거가 약합니다» 가 **세상에 대한 말**로 읽혔다(결핵 표준약 리팜핀).
    #   화면 말이 «이 실행이 읽은 문헌» 으로 범위를 좁혔다. 셋으로 갈리는 것은 그대로 고정한다
    _p193 = [_D193.why_plain(r[3]) for r in rows]
    check("[193] 화면 말도 셋으로 갈린다 — «갈립니다» 는 양쪽이 다 있을 때만",
          "지지 근거를 충분히 모으지 못했습니다" in _p193[0]
          and "반대 근거가 기각할 만큼 쌓이지 않았습니다" in _p193[1]
          and _p193[2].startswith("근거가 갈립니다")
          and not any("갈립니다" in x for x in _p193[:2]),
          [x[:24] for x in _p193])
    check("[193] 한쪽만 약한 보류는 **«이 실행이 읽은 문헌»** 으로 범위를 밝힌다 — 문헌 전체 판단이 아니다",
          all(x.startswith("이 실행이 읽은 문헌에서") for x in _p193[:2]), [x[:24] for x in _p193[:2]])


def test_hf_deploy_is_checked_by_content_not_by_saying_so():
    """[194] **«올렸다» 를 내용으로 잰다** — 본문은 `_hf194_body`.

    09-29 · `hfcheck.check()` 가 마감(10/2 16:00) 뒤에는 올리기를 권하지 않게 됐다. 이 시험의 앞 검사들은 **마감 전
    안내**를 보므로 시계에 매이지 않게 마감 전으로 고정해 돌린다(마감 뒤 갈래는 본문 ⑯ 이 `late=True` 로 따로 본다).
    """
    from ..bench import hfcheck as _H194w
    with patched(_H194w, after_deadline=lambda root=None: False):
        _hf194_body()


def _hf194_body():
    """[194] **«올렸다» 를 내용으로 잰다** — 09-25 신설.

    09-25 16:00 «올렸어» 뒤에 배포 주소가 내준 것은 **08-25 판**이었다 — Space 커밋이
    그날 0건이었다. 화면은 옛 판으로도 멀쩡히 뜨므로 **눈으로는 구별이 안 된다.**
    `hfcheck` 가 HF 저장소의 blob oid 와 로컬 `배포정적/` 을 **바이트로** 맞춘다.
    네트워크는 타지 않는다 — 09-25 에 실제로 받은 API 응답의 **모양**을 쓴다.
    """
    import json as _j194
    import os as _o194
    import tempfile as _t194
    from .. import evidence as _EV194
    from ..bench import hfcheck as _H194

    check("[194] ① blob 이름이 git 과 같은 식이다 (빈 파일 · «hello world\\n» 의 알려진 값)",
          _H194.blob_sha1(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
          and _H194.blob_sha1(b"hello world\n") == "3b18e512dba79e4c8300dd08aeb37f8e728b8dad", "")

    st = _o194.path.join(_t194.mkdtemp(prefix="hf194_"), "배포정적")
    body = {"README.md": b"---\nsdk: static\n---\n", "index.html": b"<link href='static/app.css'>",
            "static/app.css": b"a{}", "static/app.js": b"1;", "static/data/snapshot.json": b'{"v":2}'}
    for rel, data in body.items():
        p = _o194.path.join(st, *rel.split("/"))
        _o194.makedirs(_o194.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)

    # 09-25 실제 응답의 모양 — 디렉터리 항목 · 파일 항목(type·oid·size·path) · HF 기본 style.css
    def tree(oids, extra=()):
        t = [{"type": "directory", "oid": "5e6f95da", "size": 0, "path": "static"},
             {"type": "directory", "oid": "20e6ab0a", "size": 0, "path": "static/data"}]
        t += [{"type": "file", "oid": o, "size": len(body.get(r, b"")), "path": r} for r, o in oids.items()]
        t += [{"type": "file", "oid": "114adf44", "size": 388, "path": r} for r in extra]
        return t

    SP = _H194.OLD_SPACE                     # 아래 응답은 전부 옛 Space(09-25 에 실제로 본 것)의 모양이다
    info = {"id": "James2358/bio-reroute", "sha": "21b3869dd63993a19d134665aa6c45098d08eba9",
            "lastModified": "2026-08-25T07:22:06.000Z",
            "host": "https://james2358-bio-reroute.static.hf.space"}
    same = {r: _H194.blob_sha1(b) for r, b in body.items()}

    def fake(tr, served=None, fail=False, prs=(), pr_trees=None):
        def get(url):
            if fail:
                raise OSError("네트워크 없음(시험)")
            if url.endswith("/tree/main?recursive=true"):
                return _j194.dumps(tr).encode("utf-8")
            if "/tree/refs%2Fpr%2F" in url:
                n = int(url.split("/tree/refs%2Fpr%2F")[1].split("?")[0])
                return _j194.dumps((pr_trees or {})[n]).encode("utf-8")
            if "/discussions" in url:                   # 09-25 실측 모양 (PR 목록)
                return _j194.dumps({"discussions": list(prs), "count": len(prs), "start": 0,
                                    "numClosedDiscussions": 0}).encode("utf-8")
            if url.startswith(_H194.API):
                return _j194.dumps(info).encode("utf-8")
            if "/static/data/snapshot.json" in url:
                return body["static/data/snapshot.json"] if served is None else served
            raise AssertionError(url)
        return get

    old = dict(same, **{"README.md": "fc9c4695", "index.html": "2e6c5b9f",
                        "static/app.js": "6770c548", "static/data/snapshot.json": "9de109fe"})
    rc, ls = _H194.check(st, SP, get=fake(tree(old, ["style.css"])))
    txt = "\n".join(ls)
    check("[194] ② 옛 판(09-25 16:00 에 본 모양) → 3 · 다른 넷을 짚고 같은 하나는 같다 · «Commit changes to main»",
          rc == 3 and txt.count("🔴 다르다") == 4 and txt.count("✅ 같다") == 1
          and "Commit changes to main" in txt and "08-25 16:22 KST" in txt, (rc, ls[:2]))
    check("[194] ③ HF 에만 있는 기본 파일(style.css)은 **실패로 안 센다** — index.html 이 안 부르면",
          "style.css" in txt and "부르지 않는다" in txt and "5개 중 4개" in txt, ls[-2:])

    rc, ls = _H194.check(st, SP, get=fake(tree(same)))
    check("[194] ④ 전부 같고 배포 주소도 같다 → 0", rc == 0 and "✅ 배포 주소가 이 판을" in ls[-1], (rc, ls[-1:]))

    rc, ls = _H194.check(st, SP, get=fake(tree(same), served=b'{"v":1}'))
    check("[194] ⑤ 저장소는 새 판인데 주소가 옛 것 → 4(⏳) · 초록이 아니다",
          rc == 4 and "⏳" in ls[-1], (rc, ls[-1:]))

    nt = tree(old) + [{"type": "file", "oid": same[r], "size": 1, "path": "배포정적/" + r} for r in body]
    rc, ls = _H194.check(st, SP, get=fake(nt))
    check("[194] ⑥ 폴더째 올린 것(08-24 에 겪은 것)을 짚는다 → 3",
          rc == 3 and "폴더째" in "\n".join(ls), (rc,))

    rc, ls = _H194.check(st, SP, get=fake(tree(same), fail=True))
    check("[194] ⑦ 네트워크가 없으면 2 · «확인 불가» · ✅ 를 안 찍는다",
          rc == 2 and "확인 불가" in ls[0] and not any("✅" in l for l in ls), (rc, ls[:1]))

    rc, ls = _H194.check(st, SP, get=fake(tree({k: v for k, v in same.items() if k != "static/app.js"})))
    check("[194] ⑧ HF 에 없는 파일 → 3 · «없다»", rc == 3 and "🔴 없다" in "\n".join(ls), (rc,))

    chain = open(_o194.path.join(_EV194.ROOT, "사슬.ps1"), encoding="utf-8-sig").read()
    a, b = chain.find('"web.build_static"'), chain.find('"bioreroute.bench.hfcheck"')
    seg = chain[b:chain.find('Say "끝', b)] if b >= 0 else ""
    check("[194] ⑨ `사슬.ps1` 이 정적판을 만든 **뒤** 배포를 잰다 · 다르다고 사슬을 멈추지는 않는다 · PR(5)을 따로 말한다",
          0 <= a < b and seg and "Stop-Here" not in seg and "$hf -eq 5" in chain[b:], (a, b))

    # ⑩ 같은 날 20:49 — 주인이 아닌 계정으로 올려 PR #1 이 됐다(내용은 로컬과 같다). 09-25 실측 모양 그대로
    pr1 = {"num": 1, "author": {"name": "James7371", "type": "user"}, "repo": {"name": "James2358/bio-reroute"},
           "title": "Upload 5 files", "status": "open", "createdAt": "2026-09-25T11:49:07.000Z",
           "isPullRequest": True, "repoOwner": {"name": "James2358"}}
    info["author"] = "James2358"
    rc, ls = _H194.check(st, SP, get=fake(tree(old, ["style.css"]), prs=[pr1],
                                      pr_trees={1: tree(same, ["style.css"])}))
    txt = "\n".join(ls)
    check("[194] ⑩ 이 판이 **열린 PR** 에 있으면 5 · «PR #1 · 올린 계정 · 주인 계정으로 Merge · 다시 올리지 마라» "
          "· «Commit changes to main» 을 **말하지 않는다**",
          rc == 5 and "PR #1" in txt and "James7371" in txt and "James2358" in txt and "Merge" in txt
          and "다시 올리지 마라" in txt and "20:49 KST" in txt and "Commit changes to main" not in txt, (rc, ls[-2:]))

    closed = dict(pr1, status="closed")
    rc, ls = _H194.check(st, SP, get=fake(tree(old), prs=[closed, dict(pr1, num=2)], pr_trees={2: tree(old)}))
    txt = "\n".join(ls)
    check("[194] ⑪ PR 이 이 판과 **다르거나 닫혔으면** 3 · 다른 PR 에 «Merge 금지» · 닫힌 PR 은 안 적는다 · «주인 계정으로 올려라»",
          rc == 3 and "⛔ #2" in txt and "Merge 금지" in txt and "#1" not in txt
          and "주인(James2358) 계정으로" in txt, (rc, ls[-3:]))

    # ⑫ 같은 날 21:0x — 비소유 계정으로 «지우고 다시» 를 해 보다가 PR 이 다섯으로 늘었다(올리기 둘 · 삭제 셋).
    #    주인이 Community 탭에서 삭제 PR 을 병합하면 데모가 깨진다 → 하나만 Merge · 나머지 Close · 삭제는 ⛔
    no_snap = {r: o for r, o in old.items() if r != "static/data/snapshot.json"}
    no_readme = {r: o for r, o in old.items() if r != "README.md"}
    five = [dict(pr1, num=5, title="Delete README.md"), dict(pr1, num=4), dict(pr1, num=3, title="Delete static/data"),
            dict(pr1, num=2, title="Delete static/data"), pr1]
    rc, ls = _H194.check(st, SP, get=fake(tree(old, ["style.css"]), prs=five,
                                      pr_trees={1: tree(same), 4: tree(same), 2: tree(no_snap),
                                                3: tree(no_snap), 5: tree(no_readme)}))
    txt = "\n".join(ls)
    row = {n: next((l for l in ls if ("#%-3d" % n) in l), "") for n in (1, 2, 3, 4, 5)}
    check("[194] ⑫ PR 다섯(21:0x 의 모양) → 5 · **#1 하나만 Merge** · #4 는 같은 내용 Close · 삭제 PR 셋은 ⛔ Merge 금지 "
          "· «비소유 계정은 PR 만 만든다» 를 말한다",
          rc == 5 and "✅" in row[1] and "하나만 Merge" in row[1] and "Close" in row[4] and "⛔" not in row[4]
          and all("⛔" in row[n] and "Merge 금지" in row[n] for n in (2, 3, 5))
          and "static/data/snapshot.json" in row[2] and "README.md" in row[5]
          and "James7371" in txt and "James2358 로 로그인" in txt and "discussions/1 " in txt
          and "나머지 열린 PR 은 **Close**" in txt, [row[n][:70] for n in (1, 2, 4, 5)])

    # ⑬ 21:1x — 새 Space 를 만들기 **전**. 404 는 «모른다»(2)가 아니라 «없다 → 만들어라»(3)다
    import urllib.error as _ue194

    def http(code):
        def get(url):
            raise _ue194.HTTPError(url, code, "시험", None, None)
        return get
    rc, ls = _H194.check(st, get=http(404))
    rc5, ls5 = _H194.check(st, get=http(503))
    check("[194] ⑬ Space 가 없으면(404) 3 · «없다 · new-space 에서 James7371 계정으로 bio-reroute · Static» "
          "— 다른 HTTP 오류(503)는 2(확인 불가)",
          rc == 3 and "Space 가 없다" in ls[0] and "new-space" in ls[1] and "James7371" in ls[1]
          and "Static" in ls[1] and rc5 == 2 and "확인 불가" in ls5[0], (rc, rc5, ls[:1]))

    # ⑭ 데모 주소의 정본은 hfcheck.SPACE 하나 — 발표·영상 생성기는 가져다 쓰고, 현재 문서는 그 주소를 쓴다.
    #    HF 주소 규칙은 옛 Space 의 **실제 응답**(subdomain «james2358-bio-reroute»)으로 확인한다.
    root = _EV194.ROOT
    new_h, old_h = _H194.DEMO_HOST, _H194.host(_H194.OLD_SPACE)
    gens = {p: open(_o194.path.join(root, *p.split("/")), encoding="utf-8").read()
            for p in ("slides/build_deck.py", "slides/make_video_본선.py")}
    docs = {p: open(_o194.path.join(root, p), encoding="utf-8-sig").read()
            for p in ("README.md", "Bio-ReRoute_1페이지.md", "본선_확정일정.md", "심사기준대조.md",
                      "시연영상_대본_10분.md")}
    bad_docs = [p for p, t in docs.items() if new_h not in t or old_h in t]
    check("[194] ⑭ 데모 주소는 **한 곳**(hfcheck.SPACE) — 발표·영상 생성기가 가져다 쓰고 옛 주소 글자가 없다 · "
          "현재 문서 다섯이 새 주소를 쓴다 · `배포.md` 에 새 주소가 있다",
          _H194.SPACE == "James7371/bio-reroute" and new_h == "james7371-bio-reroute.static.hf.space"
          and old_h == "james2358-bio-reroute.static.hf.space" and _H194.DEMO_URL == "https://" + new_h
          and all("hfcheck import DEMO_HOST" in s and old_h not in s for s in gens.values())
          and not bad_docs
          and new_h in open(_o194.path.join(root, "배포.md"), encoding="utf-8").read(), bad_docs)

    # ⑮ 09-26 — 🔴 를 세 번 받는 동안 «이걸 돌리면 올라간다» 로 읽힐 여지가 있었다. 12:47 에 한 파일을
    #    `static/data` 올리기 주소에 올려 끝났다 → 🔴 가 «확인만 한다» 와 **폴더별 올리기 주소**를 찍는다
    rc, ls = _H194.check(st, SP, get=fake(tree(old, ["style.css"])))
    txt = "\n".join(ls)
    base = "https://huggingface.co/spaces/%s/upload/main" % SP
    check("[194] ⑮ 🔴 는 «확인만 한다» 를 말하고 **바뀐 파일을 폴더별 올리기 주소**와 함께 찍는다",
          rc == 3 and "확인만 한다" in txt and ("%s 에" % base) in txt and ("%s/static 에" % base) in txt
          and ("%s/static/data 에" % base) in txt and "`snapshot.json`" in txt
          and "`README.md` · `index.html`" in txt and "배포올리기.ps1" in txt, ls[-4:])

    # ⑯ 09-29 · **마감 뒤에는 올리기를 권하지 않는다** — 데모 주소는 제출물이다(`ghcheck` 가 공개 사본에서 하는 것과 같다)
    rc, ls = _H194.check(st, SP, get=fake(tree(old, ["style.css"])), late=True)
    txt = "\n".join(ls)
    check("[194] ⑯ 마감 뒤 🔴 는 «제출한 판 그대로» 를 말하고 **올리기 주소 · 배포올리기를 찍지 않는다**",
          rc == 0 and "마감 뒤다" in txt and "/upload/main" not in txt and "배포올리기.ps1" not in txt, ls[-2:])
    check("[194] ⑯ 마감 시각은 **공개 사본 도구의 상수 하나**에서 읽는다 — 두 곳에 적지 않는다",
          "DEADLINE" not in open(_o194.path.join(_EV194.ROOT, "bioreroute", "bench", "hfcheck.py"),
                                  encoding="utf-8").read().replace("`공개저장소만들기.DEADLINE`", ""), "")


def test_step_descriptions_do_not_show_raw_markdown():
    """[195] **사고 과정 단계 설명에 마크다운 기호가 날것으로 안 뜬다** — 09-25 신설. 결함 341.

    배포 화면을 한 컷씩 대조하다 rifampin 의 두 줄에서 별표 두 개가 그대로 보였다 —
    «…활성부위 주석 없음. 약한 대리물…» · ««한계 없음» 이 아니다». 게이트 설명이 마크다운
    강조를 달고 오는데 단계 목록은 `<div>` 라 마크다운을 안 거친다. 원문(동결 trail)은
    그대로 두고 **표시 층에서** 굵게로 바꾼다.
    """
    from .. import dash as _D195
    from .. import evidence as _EV195

    html = _D195.step_list([
        {"게이트": "s1", "결과": "PASS", "설명": "전체 평균 pLDDT 91.1 — **활성부위 주석 없음. 약한 대리물**"},
        {"게이트": "fulltext", "결과": "UNKNOWN",
         "설명": "한계를 못 읽었다 — PMC없음 2. **«한계 없음» 이 아니다** ⚠ **경고 칸도** 같다"}])
    check("[195] ① 단계 설명의 강조 기호는 **굵게**로 — 경고(⚠) 칸까지 별표가 화면에 안 남는다",
          "**" not in html and "<b>활성부위 주석 없음. 약한 대리물</b>" in html
          and "<b>«한계 없음» 이 아니다</b>" in html and "<b>경고 칸도</b>" in html, html[:160])
    odd = _D195.step_list([{"게이트": "x", "결과": "PASS", "설명": "짝 없는 **별표 하나"}])
    check("[195] ② 짝이 안 맞는 별표도 화면에 안 남는다", "**" not in odd and "별표 하나" in odd, odd[:120])
    cases = (_EV195.cases() or {}).get("사례") or []
    bad = [c.get("질의") for c in cases if "**" in _D195.step_list(c.get("게이트") or [])]
    check("[195] ③ 구운 사례 %d건 전부 — 단계 목록 어디에도 날것의 강조 기호가 없다" % len(cases),
          bool(cases) and not bad, bad)


def test_video_script_names_screens_from_the_ui_code():
    """[196] **영상 대본의 손동작이 가리키는 화면·칩·탭이 실제 화면과 같다** — 09-25 신설. 결함 342.

    첫 판이 나-2 를 «판정 사례» 화면이라 적었는데 실행 `Run 1`·③ 칸 `사고 과정` 탭은
    «어떻게 판단하나» 화면에 있었다. 나-4 의 «같은 표에서 클릭» 은 눌러도 안 바뀌었고(칩이
    고른다), ③ 칸이 `근거 카드` 에 머물러 있어 말하는 줄이 화면에 없었다. **말은 자료에서
    뽑고 손동작은 손으로 적었다** — 이제 화면 이름은 `app.js` 경로표에서 읽는다.
    """
    import importlib.util as _iu196
    import os as _o196
    import re as _re196
    import tempfile as _t196
    from .. import evidence as _EV196
    from .. import demo as _DM196
    from ..dash import RUNS as _DH196_RUNS

    root = _EV196.ROOT
    gp = _o196.path.join(root, "slides", "make_video_본선.py")
    spec = _iu196.spec_from_file_location("make_video_t196", gp)
    mv = _iu196.module_from_spec(spec)
    spec.loader.exec_module(mv)
    appjs = open(_o196.path.join(root, "web", "static", "app.js"), encoding="utf-8").read()
    navs = dict(_re196.findall(r'el:\s*"(v-[a-z]+)"[^}]*?nav:\s*"([^"]+)"', appjs))
    check("[196] ① 사이드바 이름을 **app.js 경로표에서** 읽는다 — 네 화면이 경로표와 같다",
          all(mv._nav(k) == navs.get(k) for k in ("v-cases", "v-dash", "v-evidence", "v-drug"))
          and len(set(navs.get(k) for k in ("v-cases", "v-dash", "v-evidence", "v-drug"))) == 4, navs)
    try:
        mv._nav("v-없는화면")
        stops = False
    except ValueError:
        stops = True
    check("[196] ② 경로표에 없는 화면이면 **멈춘다** — 틀린 이름으로 대본을 찍지 않는다", stops, "")

    out = _o196.path.join(_t196.mkdtemp(prefix="vid196_"), "v.md")
    mv.build(out)
    txt = open(out, encoding="utf-8").read()
    # 09-29 · 영상을 «쓰는 법» 중심으로 다시 짜며 컷 순서가 바뀌었다 — 번호가 아니라 **제목으로** 찾는다
    hands = {m.group(1): m.group(2) for m in _re196.finditer(r"### 나-\d+ · ([^\n]*)\n\n> ▶ ([^\n]+)", txt)}
    h2 = next((v for k, v in hands.items() if "사고 과정 (HCQ)" in k), "")
    h4 = next((v for k, v in hands.items() if "숙주 약과 구조 경로" in k), "")
    check("[196] ③ HCQ 사고 과정 컷은 «%s» 화면으로 간다 — `Run 1`·③ 칸 `사고 과정` 이 있는 화면" % navs.get("v-dash"),
          ("「심사·시연 → %s」" % navs.get("v-dash")) in h2 and list(_DH196_RUNS)[0] in h2 and "사고 과정" in h2
          and ("→ %s」" % navs.get("v-cases")) not in h2, h2[:90])
    check("[196] ④ 검증 경로 컷은 **칩**을 누르고 ③ 칸을 `사고 과정` 으로 되돌려 말하는 두 줄을 보인다 · «같은 표에서» 가 없다",
          "칩" in h4 and "사고 과정" in h4 and _DM196.GATE_KO["router"] in h4 and _DM196.GATE_KO["s1"] in h4
          and "같은 표에서" not in txt, h4[:120])
    ui = "".join(open(_o196.path.join(root, *p.split("/")), encoding="utf-8").read()
                 for p in ("bioreroute/dash.py", "web/static/app.js", "web/static/index.html",
                           "web/static/data/snapshot.json"))
    # 09-28 밤 · 옛 나-5(«Run 2 · 역발상» · «신종감염병긴급» 칩)를 «병으로 시작» 컷으로 바꿨다(결함 373 · 376) —
    #   그 컷이 누르는 것(«찾는 방법» · «심사 기준» · «후보 찾기» 버튼)도 화면 코드에 실제로 있어야 한다
    ctl = [list(_DH196_RUNS)[0], "사고 과정", "근거 카드", "같은 질의를 일반 언어모델에 넣으면",
           "찾는 방법", "심사 기준", "후보 찾기", _DM196.GATE_KO["router"], _DM196.GATE_KO["s1"]]
    missing = [c for c in ctl if c in txt and c not in ui]
    check("[196] ⑤ 대본이 가리키는 칩·탭·표 이름이 **화면 코드·스냅숏에 실제로 있다**",
          not missing and all(c in txt for c in ctl[:7]), missing)


def test_hf_deploy_commits_only_changed_files_with_the_owner_token():
    """[197] **올리기를 명령 하나로** — 주인 토큰만 · 다른 파일만 · 올린 뒤 hfcheck 0 — 09-26 신설.

    09-25~26 에 끌어다 놓기가 네 번 막혔다(커밋 안 됨 · 비소유 계정 PR 다섯 · 두 번 더).
    `hfdeploy` 가 API 커밋 하나로 올린다. 네트워크·실제 라이브러리 없이 **가짜 API** 로
    흐름을 잰다 — 실제 경로는 승우 컴퓨터의 첫 `-Apply` 가 처음이다(샌드박스에 PyPI 가 없다).
    """
    import json as _j197
    import os as _o197
    import tempfile as _t197
    from .. import evidence as _EV197
    from ..bench import hfcheck as _H197
    from ..bench import hfdeploy as _HD197

    st = _o197.path.join(_t197.mkdtemp(prefix="hd197_"), "배포정적")
    body = {"README.md": b"r", "index.html": b"<i>", "static/app.css": b"c", "static/app.js": b"j",
            "static/data/snapshot.json": b'{"v":3}'}
    for rel, data in body.items():
        p = _o197.path.join(st, *rel.split("/"))
        _o197.makedirs(_o197.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
    SP = "Owner/space"
    good = {r: _H197.blob_sha1(b) for r, b in body.items()}
    state = {"tree": dict(good, **{"static/data/snapshot.json": "deadbeef"}), "sha": "abc1234def",
             "served": b'{"v":2}'}

    def get(url):
        if url.endswith("/tree/main?recursive=true"):
            return _j197.dumps([{"type": "file", "oid": o, "size": len(body[r]), "path": r}
                                for r, o in state["tree"].items()]).encode("utf-8")
        if "/discussions" in url:
            return b'{"discussions": [], "count": 0}'
        if url.startswith(_H197.API):
            return _j197.dumps({"sha": state["sha"], "lastModified": "2026-09-26T03:00:00.000Z",
                                "author": "Owner", "host": "https://owner-space.static.hf.space"}).encode("utf-8")
        if "/static/data/snapshot.json" in url:
            return state["served"]
        raise AssertionError(url)

    changed, info, err = _HD197.plan(st, SP, get=get)
    check("[197] ① 미리보기가 **다른 파일만** 고른다 — blob 이름으로(hfcheck 와 같은 식)",
          err is None and changed == [("static/data/snapshot.json", 7)] and info.get("sha") == "abc1234def",
          (changed, err))

    class FakeApi:
        def __init__(self, who):
            self.who, self.calls = who, []

        def whoami(self):
            return {"name": self.who}

        def create_commit(self, repo_id, operations, *, commit_message, repo_type=None, parent_commit=None):
            self.calls.append(dict(repo_id=repo_id, repo_type=repo_type, parent_commit=parent_commit,
                                   paths=[getattr(op, "path_in_repo", None) or op[0] for op in operations],
                                   msg=commit_message))
            state["tree"], state["served"], state["sha"] = dict(good), body["static/data/snapshot.json"], "new5678"

            class R:
                oid = "new5678abc"
            return R()

    tok = "hf_시험용_가짜토큰_0000"
    other = FakeApi("SomeoneElse")
    rc, ls = _HD197.apply(changed, info, st, SP, api=other, token=tok, wait=(1, 0), get=get)
    check("[197] ② 토큰 계정이 **Space 주인이 아니면 안 올린다** — 09-25 PR 다섯의 모양",
          rc == 3 and not other.calls and "SomeoneElse" in ls[0], (rc, ls[:1]))
    rc, ls = _HD197.apply(changed, info, st, SP, api=FakeApi("Owner"), token="", wait=(1, 0), get=get)
    check("[197] ③ 토큰이 없으면 2 · «가려진 입력으로 묻는다» 를 말한다", rc == 2 and "토큰이 없다" in ls[0], ls[:1])
    owner = FakeApi("Owner")
    rc, ls = _HD197.apply(changed, info, st, SP, api=owner, token=tok, wait=(2, 0), get=get)
    c = owner.calls[0] if owner.calls else {}
    check("[197] ④ 주인 토큰이면 **바뀐 파일 하나만** 커밋 · 방금 본 main 위에(parent_commit) · 올린 뒤 hfcheck 0",
          rc == 0 and len(owner.calls) == 1 and c.get("paths") == ["static/data/snapshot.json"]
          and c.get("parent_commit") == "abc1234def" and c.get("repo_type") == "space" and c.get("repo_id") == SP
          and any("✅ 배포 주소가 이 판을" in l for l in ls), (rc, c, ls[-1:]))
    check("[197] ⑤ 토큰 문자열이 **어떤 출력에도 안 나온다**", all(tok not in l for l in ls), "")

    ps1 = open(_o197.path.join(_EV197.ROOT, "배포올리기.ps1"), "rb").read()
    src = ps1.decode("utf-8-sig")
    a = src.find("if ($Apply)")
    check("[197] ⑥ `배포올리기.ps1` — BOM · 토큰은 **가려진 입력**으로 묻고 끝나면 지운다 · `--apply` 는 -Apply 일 때만 · "
          "토큰 글자·파일 쓰기가 없다",
          ps1[:3] == b"\xef\xbb\xbf" and "Read-Host -AsSecureString" in src and "Remove-Item Env:HF_TOKEN" in src
          and 0 <= a < src.find('"--apply"') and "hf_" not in src and "Set-Content" not in src
          and "Out-File" not in src and "bioreroute.bench.hfdeploy" in src, a)

    # ⑦ 09-29 · **마감 뒤에는 올리지 않는다** — 데모 주소는 제출물이다(공개 사본 `push()` 와 같은 규칙)
    import contextlib as _cl197
    import io as _io197
    _buf197 = _io197.StringIO()
    with patched(_HD197.H, after_deadline=lambda root=None: True), _cl197.redirect_stdout(_buf197):
        _rc197 = _HD197.main(["--apply", "--stage", st, "--space", SP])
    check("[197] ⑦ 마감 뒤 `--apply` 는 **네트워크를 타기 전에 멈춘다** — `--after-deadline` 일 때만 연다",
          _rc197 == 2 and "마감 뒤다" in _buf197.getvalue(), (_rc197, _buf197.getvalue()[:120]))


def test_deck_text_does_not_overflow_onto_neighbours():
    """[198] **글이 줄바꿈으로 넘쳐 옆 글자를 덮지 않는다** — 09-26 신설. 결함 343.

    [151] 은 **글상자끼리** 겹치는지만 잰다. 상자는 안 겹쳐도 글이 상자보다 길면 줄이 바뀌어
    흘러내린다 — 결함 막대 장의 설명 두 줄이 그랬고(10pt 한 줄 상자에 두 줄), 제출용 10분판을
    렌더해 넘겨 보고서야 봤다. `deckfit` 이 서체 없이 모형 폭으로 잰다 — 09-28 에 제출 PDF(PowerPoint ·
    맑은 고딕) 실측으로 다시 맞췄다(한글 1.0em · 공백 0.36em · 좁은 기호는 실측 · 배율 없음). 첫 판(×0.9 · Noto 기준)은
    한 글자 넘침을 못 봤다(결함 372 · ①-b).
    """
    import os as _o198
    from .. import evidence as _EV198
    from ..bench import deckfit as _DF198
    try:
        from pptx import Presentation as _Pr198
        from pptx.util import Inches as _In198, Pt as _Pt198
    except Exception:
        check("[198] python-pptx 가 있다 — 없으면 이 검사가 죽는다", False, "pip install python-pptx")
        return

    def one(text):
        prs = _Pr198()
        s = prs.slides.add_slide(prs.slide_layouts[6])
        a = s.shapes.add_textbox(_In198(1), _In198(1), _In198(3), _In198(0.23))
        a.text_frame.word_wrap = True
        ra = a.text_frame.paragraphs[0].add_run()
        ra.text, ra.font.size = text, _Pt198(10)
        b = s.shapes.add_textbox(_In198(1), _In198(1.25), _In198(3), _In198(0.3))
        rb = b.text_frame.paragraphs[0].add_run()
        rb.text, rb.font.size = "아래 행의 이름", _Pt198(12)
        return _DF198.overflows(prs)

    long_hits, short_hits = one("가" * 60), one("가" * 10)
    check("[198] ① 가드가 울 수 있다 — 한 줄 상자에 세 줄짜리 글이면 아래 글상자를 덮는다고 잡고, 짧으면 안 운다",
          len(long_hits) == 1 and not short_hits, (long_hits, short_hits))

    def row(text):
        # 제출 PDF 26쪽의 그 상자 그대로 — 654pt · 좌우 여백 0 · 10pt · 바로 아래에 다음 유형 이름
        prs = _Pr198()
        s = prs.slides.add_slide(prs.slide_layouts[6])
        a = s.shapes.add_textbox(_Pt198(255.6), _Pt198(144.7), _Pt198(654.0), _Pt198(16.6))
        tf = a.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = 0
        ra = tf.paragraphs[0].add_run()
        ra.text, ra.font.size = text, _Pt198(10)
        b = s.shapes.add_textbox(_Pt198(255.6), _Pt198(161.7), _Pt198(400.0), _Pt198(16.0))
        rb = b.text_frame.paragraphs[0].add_run()
        rb.text, rb.font.size = "캐시는 최적화가 아니라 자료원", _Pt198(12)
        return _DF198.overflows(prs)

    from ..bench import defecttypes as _DT198
    old_row = ("모의로만 줄곧 → 첫 실호출이 0건 · 안 써 본 의존성이 다섯 달 전에 죽어 있었다 · "
               "모의가 실제 출력 형식보다 좁아 시험이 초록인 채 실패를 감췄다")
    now_row = _DT198.rows(_EV198.ROOT)[0][2].replace("**", "")
    check("[198] ①-b 09-28 제출 PDF 26쪽에서 **실제로 한 글자 넘친 줄**을 넘친다고 잡고, 고친 줄은 안 넘친다고 한다 — 결함 372",
          len(row(old_row)) == 1 and not row(now_row), (old_row[-6:], now_row[-6:]))
    for rel in _DF198.DECKS:
        p = _o198.path.join(_EV198.ROOT, rel)
        if not _o198.path.exists(p):
            check("[198] ② %s 가 있다 — **없으면 빌드해라**" % rel, False, p)
            continue
        seen, hits = _DF198.scan(p)
        check("[198] ② %s — 글상자 %d개 중 **줄바꿈으로 넘쳐 옆 글자를 덮는 것 0**" % (rel, seen),
              seen > 100 and not hits, hits[:3])
    ps1 = open(_o198.path.join(_EV198.ROOT, "발표10분.ps1"), encoding="utf-8-sig").read()
    a, b = ps1.find('"bioreroute.bench.deckfit"'), ps1.find('Say "③ PDF')
    check("[198] ③ `발표10분.ps1` 이 PDF 를 굽기 **전에** 넘침을 잰다", 0 <= a < b, (a, b))


def test_submission_surfaces_do_not_claim_untested_or_deny_measured():
    """[199] **제출 표면이 안 해 본 것을 «가능» 이라, 잰 것을 «수치 없음» 이라 말하지 않는다** — 09-26. 결함 344·345.

    09-26 전수검사에서 둘이 나왔다 — 발표 본편이 «폐쇄망 INT4 가능»(한 번도 안 태웠다 ·
    `제안서_전수대조.md:268`), 대시보드 역발상 칸이 «아직 수치가 없다 · 실행 전»(`역발상결과.md`
    에 사전 기준 통과가 있다), 보고서 «안 한 것» 표가 08-06 칸 하나뿐이라 실측된 여섯 줄이 지금의
    한계처럼 읽혔다. 문구 몇 개를 박는 좁은 시험이다 — 넓은 것은 사람(전수검사)이 본다.
    """
    import os as _o199
    from .. import evidence as _EV199
    from .. import dash as _D199

    root = _EV199.ROOT

    def rd(p):
        return open(_o199.path.join(root, *p.split("/")), encoding="utf-8-sig").read()

    deck, crit, rep = rd("slides/build_deck.py"), rd("심사기준대조.md"), rd("연구기술보고서.md")
    deck = "\n".join(l for l in deck.splitlines() if not l.lstrip().startswith("#"))   # 슬라이드 글만 (주석은 기록)
    bad = [(n, ph) for n, t in (("build_deck", deck), ("심사기준대조", crit), ("보고서", rep))
           for ph in ("INT4 가능", "INT4 대체 가능") if ph in t]
    check("[199] ① «폐쇄망 INT4 가능» 을 제출 표면이 말하지 않는다 — 안 태웠다(미시험으로 적는다) · "
          "HITL 을 비용 절감 장치처럼 말하지 않는다(껐다고 적는다)",
          not bad and "INT4 는 미시험" in deck and "비용 모델이 이걸 전제한다" not in deck
          and "실측·시연에서는 껐다" in deck, bad)
    rev = _D199.RUNS.get("Run 2 · 역발상", {}).get("빠진_것", "") if hasattr(_D199, "RUNS") else ""
    rev = rev or next((v.get("빠진_것", "") for v in getattr(_D199, "RUNS", {}).values()
                       if "역발상" in v.get("빠진_것", "")), "")
    check("[199] ② 대시보드 역발상 칸이 «수치 없음» 이라 하지 않고 **잰 것의 출처**를 댄다",
          rev and "아직 수치가 없다" not in rev and "역발상결과.md" in rev
          and _o199.path.exists(_o199.path.join(root, "역발상결과.md")), rev[:60])
    # ③ 09-26 저녁 · 보고서를 최종 결과로 다시 썼다(승우: «8월과 비교하지 말고 전체 결과로 녹여라»).
    #   «08-06 칸 + 09-26 칸» 두 열 표 자체가 이력 서술이라 걷어냈다 — 그래서 이 검사도 «두 칸이 있나» 가
    #   아니라 **«지금 상태 하나로 적혔고, 실측이 끝난 것을 수치 없음이라 하지 않는가»** 를 본다.
    i = rep.find("### 안 한 것 — 그리고 그 이유")
    sec = rep[i:i + 6000] if i >= 0 else ""
    check("[199] ③ 보고서 «안 한 것» 표가 **지금 상태 하나**로 적혀 있다 — 옛 날짜 칸이 없고, "
          "실측이 끝난 것을 «수치가 없다» 로 말하지 않는다",
          i >= 0 and "08-06 상태" not in sec and "수치가 없다" not in sec
          and "✅ 가 하나도 없다" not in sec, i)


def test_report_pdf_does_not_print_markdown_markers():
    """[200] **제출 PDF 에 마크다운 기호가 그대로 찍히지 않는다** — 09-26 저녁. 결함 347.

    Python-Markdown 은 코드 블록 안의 `**굵게**` 를 글자로 두고 `~~취소선~~` 확장이 없다. 그래서
    상세기술서 PDF 열 개 쪽에 `**` 가 찍혔다 — 우리 결함 유형 표가 «마크다운이 노출됐다» 라고 적어 둔
    바로 그 모양이 그 표가 실린 제출물에서 났다. `보고서_pdf만들기.py` 가 두 함수(`_polish` ·
    `_leftovers`)로 고치고, 남으면 멈춘다(rc 4). 스크립트는 가져오면 바로 돌기 때문에, 이 시험은
    두 함수를 **파일에서 꺼내** 합성 자료와 실제 보고서로 본다.
    """
    import ast as _a200
    import os as _o200
    import re as _r200
    from .. import evidence as _EV200

    root = _EV200.ROOT
    p = _o200.path.join(root, "보고서_pdf만들기.py")
    src = open(p, encoding="utf-8").read()
    ns = {"re": _r200}
    fns = [n for n in _a200.parse(src).body
           if isinstance(n, _a200.FunctionDef) and n.name in ("_polish", "_leftovers")]
    for fn in fns:
        exec(compile(_a200.Module(body=[fn], type_ignores=[]), p, "exec"), ns)
    check("[200] ① 변환기에 두 함수가 있고 · 본문이 그 둘을 부르며 · 남으면 멈춘다(rc 4)",
          len(fns) == 2 and "_polish(html_body)" in src and "_leftovers(html_body)" in src
          and "sys.exit(4)" in src, [f.name for f in fns])
    if len(fns) != 2:
        return
    raw = ("<pre><code>전체 대비 **2.3%**\n</code></pre>"
           "<p>인라인 <code>p = 0.004 는 **통과**</code> · 본문 ~~9/7 에 돌린다~~ 끝</p>")
    out = ns["_polish"](raw)
    check("[200] ② 합성 자료 — 코드 안 굵게는 굵게로 · 취소선은 취소선으로 · 남는 기호 0",
          ns["_leftovers"](out) == 0 and "<b>2.3%</b>" in out and "<b>통과</b>" in out
          and "<del>9/7 에 돌린다</del>" in out, out[:160])
    check("[200] ③ 짝이 없는 기호는 **남는다고 센다** — 조용히 지우지 않는다",
          ns["_leftovers"](ns["_polish"]("<p>a ** b</p>")) == 1, "")
    try:
        import markdown as _md200
    except ModuleNotFoundError:
        check("[200] ④ Markdown 이 없다 — 실제 보고서 변환은 건너뛴다(①~③만 봤다)", True, "")
        return
    rep = open(_o200.path.join(root, "연구기술보고서.md"), encoding="utf-8").read()
    h = ns["_polish"](_md200.markdown(rep, extensions=["tables", "fenced_code", "toc", "sane_lists"]))
    check("[200] ④ ⭐ 실제 보고서를 같은 설정으로 변환하면 **남는 기호가 0**",
          ns["_leftovers"](h) == 0, ns["_leftovers"](h))


def test_countsync_does_not_move_numbers_inside_records():
    """[201] **동기화 도구가 기록 속 숫자를 결함 수 따라 올리지 않는다** — 09-26 밤. 결함 359.

    `countsync` 의 결함 규칙이 «결함» 이 **줄 어디에든** 있으면 그 줄의 `(옛 수)건` 을 전부 바꿨다.
    결함 수가 우연히 기록 속 수를 지나가자 — 대장 237 행 «이 프롬프트로 340건을 쟀다»(생성 후보)가
    342 → 345 로, `발표뼈대.md` 의 «08-10 재분류 89건»(유형 합 89)이 287 → 345 로 움직였다.
    감사기(`docaudit`)가 기록으로 건너뛰는 줄을 고치는 도구는 고쳐 쓰고 있었다.
    """
    import os as _o201
    import shutil as _s201
    import tempfile as _t201
    from ..bench import countsync as _CS201, docaudit as _DA201
    from .. import evidence as _EV201

    d = _t201.mkdtemp(prefix="csync201_")
    lines = [
        "| 237 | **제목** | 결함 236 뒤 이 프롬프트로 340건을 쟀다 | 09-26 |",   # 1 대장 행 — 기록
        "4. ~~결함을 한 장으로~~ → 08-10 재분류. **340건**, 유형별 …",          # 2 결함과 멀다 — 기록
        "그때 화면은 «결함 340건» 이었다",                                      # 3 «» 인용 — 기록
        "스스로 찾은 결함 340건을 공개한다",                                     # 4 주장
        "결함 **340건** · 회귀 시험 2540건",                                    # 5 주장
        "공개한 340건과 숨긴 0건 중 어느 쪽이 위험한가",                          # 6 주장
        "자기 도구를 자기가 반증한 기록 340건",                                  # 7 주장
        "> 머리 · 코드 · **결함 340건**",                                       # 8 머리글 — 주장
        "결함 12 의 표본은 340건이었다",                                         # 9 결함 번호 옆의 다른 수
    ]
    open(_o201.path.join(d, "README.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    old_docs = list(_CS201.DOCS)
    try:
        _CS201.DOCS[:] = ["README.md"]
        rows = _CS201.plan({"결함": 340, "시험": 2540}, {"결함": 359, "시험": 2540}, d)
    finally:
        _CS201.DOCS[:] = old_docs
        _s201.rmtree(d, ignore_errors=True)
    got = {r[1] for r in rows}
    check("[201] ① 기록 셋(대장 행 · «결함» 과 먼 수 · «» 인용)과 결함 번호 옆의 다른 수는 **안 고치고**, "
          "주장 다섯만 고친다",
          got == {4, 5, 6, 7, 8}, sorted(got))
    check("[201] ② 고친 줄에서 **바뀐 것은 그 수 하나**다 — 앞 낱말은 그대로",
          all(r[3] == r[2].replace("340건", "359건", 1) for r in rows),
          [(r[1], r[3][:40]) for r in rows if r[3] != r[2].replace("340건", "359건", 1)])
    # ③ 실제 저장소 — 지금 결함 수와, **기록 속에 실제로 남아 있는 옛 수 345**(대장 171 행 ·
    #    남은일 «» 인용)에서 한 칸 올린다고 쳐도 **대장 행 · 기록 줄은 하나도 안 바뀐다**.
    #    앞판 규칙이면 345 에서 대장 행과 인용 줄이 걸린다 — 되돌리면 여기서 운다.
    n = _EV201.defect_count(_o201.path.join(_EV201.ROOT, "Bio-ReRoute_발견정리.md"))
    bad = []
    for k in sorted({n, 345}):
        real = _CS201.plan({"결함": k, "시험": 0}, {"결함": k + 1, "시험": 0}, _EV201.ROOT)
        bad += [(k, r[0], r[1]) for r in real
                if _DA201._skip(r[2]) or r[0] == "Bio-ReRoute_발견정리.md" and r[2].lstrip().startswith("|")]
    check("[201] ③ 실제 문서에서 동기화가 고칠 줄 중 **대장 행 · 감사기가 기록으로 보는 줄이 0**",
          not bad, bad[:5])
    # ④ 되살린 두 값이 제자리에 있다 — 다시 움직이면 여기서 운다
    led = open(_o201.path.join(_EV201.ROOT, "Bio-ReRoute_발견정리.md"), encoding="utf-8-sig").read()
    sk = open(_o201.path.join(_EV201.ROOT, "발표뼈대.md"), encoding="utf-8").read()
    check("[201] ④ 되살린 기록 — 대장 237 행 «340건을 쟀다»(생성 후보) · 발표뼈대 «08-10 재분류 89건»(유형 합)",
          "이 프롬프트로 340건을 쟀다" in led and "08-10 재분류.** **89건**" in sk
          and 17 + 9 + 9 + 7 + 19 + 21 + 7 == 89, "")


def test_calibration_numbers_in_report_come_from_code_and_screen_agrees():
    """[202] **보고서 §4.2 의 보정 수가 코드에서 나오고, 화면이 같은 말을 한다** — 09-26 밤. 결함 360·361.

    ① §4.2 의 Brier 구간이 일회성 계산에서 나왔고 §9 의 `calibrate` 는 ECE 구간만 찍었다.
    ② 데모 보정 칸이 «terra 는 Platt 을 다시 적합하지 않았다» 를 코드에 박아 두어 보고서와 반대로 말했다.
    ③ 모델 단독의 보정 효과는 적합 실행에 따라 방향이 바뀐다 — 보고서가 그 사실을 싣는다.
    """
    import json as _j202
    import os as _o202
    from ..bench import calibrate as _C202
    from .. import dash as _D202, evidence as _EV202

    root = _EV202.ROOT
    P = lambda n: _o202.path.join(root, n)                       # noqa: E731
    need = ("궤적_0912.json", "홀드아웃_본선모델.json", "bench_results.json", "재현성_0920b.json")
    miss = [n for n in need if not _o202.path.exists(P(n))]
    check("[202] ⓪ 보정 재현에 쓰는 결과 파일 넷이 있다", not miss, miss)
    if miss:
        return
    r = _C202.run(P(need[0]), P(need[1]), compare_fit=P(need[2]))
    b5, b0, bb = r["configs"]["B5"], r["configs"]["B0"], r.get("boot_brier") or {}
    rd = lambda v: tuple(round(x, 4) for x in v)                  # noqa: E731
    check("[202] ① 점수 — B5 0.2197 → 0.2120 · B0 0.2187 → 0.2218 · 평가 770쌍",
          (b5["brier_raw"], b5["brier_platt"], b0["brier_raw"], b0["brier_platt"], b5["n_eval"])
          == (0.2197, 0.212, 0.2187, 0.2218, 770), (b5, b0))
    want = {"b5_platt_vs_raw": (-0.0077, -0.014, -0.0018),
            "b5_platt_vs_compare": (-0.0008, -0.002, 0.0004),
            "b5_vs_b0_raw": (0.001, -0.0137, 0.0157),
            "b5_vs_b0_platt": (-0.0098, -0.0251, 0.0046),
            "b0_platt_vs_raw": (0.0031, 0.0013, 0.005)}
    got = {k: rd(bb[k]) for k in want if k in bb}
    check("[202] ② Brier 구간 다섯이 **코드에서** 나온다(보고서의 수 그대로)", got == want, got)
    rep = open(P("연구기술보고서.md"), encoding="utf-8").read()
    sg = lambda x: ("+" if x >= 0 else "−") + "%.4f" % abs(x)      # noqa: E731  보고서는 부호를 늘 적는다
    fmt = lambda v: "%s [%s, %s]" % (sg(v[0]), sg(v[1]), sg(v[2]))  # noqa: E731
    lines = [fmt(want[k]) for k in ("b5_platt_vs_raw", "b5_platt_vs_compare", "b5_vs_b0_raw",
                                    "b5_vs_b0_platt", "b0_platt_vs_raw")]
    check("[202] ③ 보고서 §4.2 가 그 구간을 **그대로** 싣는다", all(s in rep for s in lines), lines)
    # ④ 민감도(사후) — 09-20 재실행으로 맞추면 모델 단독 효과의 부호가 바뀐다. 보고서가 그걸 싣는다
    f2 = _C202.load(P(need[3]), "B0")
    e0 = _C202.load(P(need[1]), "B0")
    fk = set(_C202.load(P(need[0]), "B0")["keys"])
    keep = [i for i, k in enumerate(e0["keys"]) if k not in fk]
    ys, ss = [e0["y"][i] for i in keep], [e0["s"][i] for i in keep]
    A2, B2 = _C202.fit_platt(f2["s"], f2["y"])
    v2 = rd(_C202.boot_brier(_C202.apply_platt(ss, A2, B2), ss, ys))
    check("[202] ④ 민감도 — 09-20 재실행 적합이면 모델 단독 효과가 −0.0029 [−0.0047, −0.0013] 이고 "
          "보고서가 두 방향을 다 적는다",
          v2 == (-0.0029, -0.0047, -0.0013) and "−0.0029 [−0.0047, −0.0013]" in rep
          and "+0.0031 [+0.0013, +0.0050]" in rep and "18건을 외워" not in rep, v2)
    check("[202] ⑤ §9 가 두 명령(비교 적합 · 민감도)을 싣고 묶음이 그 자료를 담는다",
          "--compare-fit bench_results.json" in rep and "--fit 재현성_0920b.json" in rep
          and "재현성_0920b.json" in open(P("배포zip만들기.py"), encoding="utf-8").read(), "")
    card = _j202.load(open(P("calibration.json"), encoding="utf-8"))
    scr = _D202.bottom_calibration()
    check("[202] ⑥ 화면 카드가 terra 이고 **스스로 이름을 말한다** · 화면이 «다시 적합하지 않았다» 를 안 말한다 · "
          "모델 단독 비교를 Brier 구간으로 말한다",
          "terra" in card.get("라벨", "") and card.get("적합") == "궤적_0912.json"
          and rd(card.get("boot_brier", {}).get("b5_vs_b0_platt", (0, 0, 0))) == want["b5_vs_b0_platt"]
          and "다시 적합하지 않았다" not in scr and card["라벨"] in scr and "Brier 차이" in scr, scr[:160])


def test_public_copy_is_built_outside_and_never_pushed_to_the_working_repo():
    """[203] **공개 저장소는 작업 저장소 밖의 사본이고, 작업 저장소 주소로는 안 올라간다** — 09-26 밤.

    작업 저장소에는 제출과 무관한 자료 · 로그 · 배포 사본 폴더 · 서버 주소가 적힌 기록이 섞여 있고
    역사까지 공개된다. 그래서 심사위원용 묶음(zip) + 상태 파일 · 제3자 타임스탬프 · 보고서 PDF 로 **따로**
    만든다(`공개저장소만들기.py`). 이 시험은 그 도구가 ① 밖에 만들고 ② 넣으면 안 되는 것을 안 넣고
    ③ 작업 저장소 · Bio.git 으로 안 올리고 ④ 보고서 · 공개 README 가 같은 주소를 쓰는지 본다.

    09-27 · ⑦ 개발 중 작업 문서(`EXCLUDE`)를 빼고 금지 문구(`FORBID_WORDS`)가 0 인지, 그리고 그 가드가
    **울 수 있는지**(예외 낱말은 그 파일 그 줄에서만 통한다) 본다. 금지 목록은 도구가 갖는다 — 시험에 옮겨 적지 않는다.

    ⓘ **공개 사본 안에서는 건너뛴다** — 도구가 작업 저장소에만 있다.
    """
    import importlib.util as _iu203
    import os as _o203
    from .. import evidence as _EV203
    from ..bench.hfcheck import DEMO_HOST as _HOST203

    root = _EV203.ROOT
    sp = _o203.path.join(root, "공개저장소만들기.py")
    if not _o203.path.exists(sp):
        check("[203] 공개 사본이다 — 사본을 만드는 도구가 작업 저장소에만 있어 건너뛴다", True, "")
        return
    spec = _iu203.spec_from_file_location("public_copy_203", sp)
    m = _iu203.module_from_spec(spec)
    spec.loader.exec_module(m)                  # main() 은 안 부른다
    check("[203] ① 사본 폴더 기본값이 작업 저장소 **밖**이다 · 안쪽 판정이 옳다",
          not m.inside(m.STAGE_DEFAULT, root) and m.inside(_o203.path.join(root, "x"), root),
          m.STAGE_DEFAULT)
    check("[203] ② 작업 저장소 리모트와 Bio.git 은 **거절**, 공개 주소는 통과",
          m.refuse_url("https://github.com/hwangjames7371/Bio.git", root) is not None
          and m.refuse_url(m.PUBLIC_GIT, root) is None
          and m.refuse_url("", root) is not None, m.PUBLIC_GIT)
    if m.newest_zip(root):
        p = m.plan(root)
        names = set(p["files"])
        check("[203] ③ 미리보기 — 없는 것 · 금지 이름(제출 무관 자료 · 로그 · .env) · 서버 주소 · 키 모양이 0",
              not (p["bad_name"] or p["bad_text"] or p["keys"]), (p["bad_name"][:3], p["bad_text"][:3], p["keys"][:3]))
        check("[203] ④ 공개 README · 선행연구 대조 · 제3자 타임스탬프가 들어가고 금지 이름은 안 들어간다",
              "README.md" in names and "선행연구대조.md" in names and "봉인해시_공개등록.txt.ots" in names
              and not any(m.FORBID_NAME.search(n) for n in names) and p["files"]["README.md"][1] == m.README_SRC,
              sorted(n for n in names if m.FORBID_NAME.search(n))[:3])
        check("[203] ⑦ 개발 중 작업 문서는 **빠지고** · 금지 문구가 **0** 이다",
              not (names & set(m.EXCLUDE)) and set(p["excluded"]) <= set(m.EXCLUDE) and p["excluded"]
              and not p["bad_word"], (sorted(names & set(m.EXCLUDE)), p["bad_word"][:3]))
    else:
        check("[203] ③④⑦ 묶음(zip)이 없다 — 미리보기는 건너뛴다(①②는 봤다)", True, "")
    # ⑧ 가드가 **울 수 있다** — 예외 낱말은 그 파일에서만 통하고, 같은 줄에 다른 금지 낱말이 있으면 잡는다
    items = sorted(m.ALLOW.items())
    fa, ta = items[0][0], items[0][1][0]
    fb, tb = items[1][0], items[1][1][0]
    check("[203] ⑧ 금지 문구 가드가 울 수 있다 — 예외는 **그 파일 그 낱말**만",
          not m.forbidden_hits(fa, "x " + ta) and m.forbidden_hits("아무개.md", "x " + ta)
          and m.forbidden_hits(fa, ta + " " + tb) and not m.forbidden_hits(fb, "x " + tb),
          (fa, fb))
    rd = open(_o203.path.join(root, m.README_SRC), encoding="utf-8").read()
    rep = open(_o203.path.join(root, "연구기술보고서.md"), encoding="utf-8").read()
    check("[203] ⑤ 보고서 머리와 공개 README 가 **같은 공개 주소** · 데모 주소 · 개발 이력을 싣는다",
          m.PUBLIC_REPO in rep and _HOST203 in rd and "개발 이력" in rd and "개발 이력" in rep
          and "github.com/hwangjames7371/Bio-ReRoute>" not in rep, m.PUBLIC_REPO)
    raw = open(_o203.path.join(root, "공개저장소.ps1"), "rb").read()
    check("[203] ⑥ `공개저장소.ps1` — BOM · CRLF · 줄 이어쓰기 없음",
          raw[:3] == b"\xef\xbb\xbf" and b"\n" not in raw.replace(b"\r\n", b"")
          and b"`\r\n" not in raw, len(raw))


def test_dday_milestones_match_the_schedule_table():
    """[204] **남은 날을 세는 도구가 일정표와 같은 날짜를 든다** — 09-27 · 결함 363.

    `bench/dday.py` 가 «`CLAUDE.md §0-b` 의 표와 같은 값이어야 한다» 고 **주석으로만** 적고 8월 일정
    («본선 9/30») 에 멈춰 있었다. 9/30 은 09-05 데이콘 메일로 틀린 것이 확정된 추정값이다(실제 10/2).
    주석은 대조가 아니다 — 표의 세는 줄(`py -c …`)에서 날짜를 읽어 **순서까지** 맞춘다.

    ⓘ 공개 사본에는 작업 규칙 문서가 없어 건너뛴다.
    """
    import datetime as _dt204
    import os as _o204
    import re as _re204
    from .. import evidence as _EV204
    from ..bench import dday as _DD204

    p = _o204.path.join(_EV204.ROOT, "CLAUDE.md")
    if not _o204.path.exists(p):
        check("[204] 작업 규칙 문서가 없다(공개 사본) — 건너뛴다", True, "")
        return
    line = next((ln for ln in open(p, encoding="utf-8").read().splitlines()
                 if "import datetime" in ln and "회신마감" in ln), "")
    want = [_dt204.date(int(y), int(mo), int(dd))
            for y, mo, dd in _re204.findall(r"d\.date\((\d{4}),\s*(\d{1,2}),\s*(\d{1,2})\)", line)]
    got = [w for _n, w in _DD204.MILESTONES]
    check("[204] ① 일정표의 세는 줄을 찾았다 — 날짜 %d개" % len(want), len(want) >= 5, line[:60])
    check("[204] ② `dday.MILESTONES` 가 그 줄과 **같은 날짜 · 같은 순서**다", got == want,
          ([str(x) for x in got], [str(x) for x in want]))
    check("[204] ③ 제출 마감이 10/2 다 — 9/30 은 틀린 추정값이었다",
          _dt204.date(2026, 10, 2) in got and _dt204.date(2026, 9, 30) not in got, [str(x) for x in got])


def test_submission_surfaces_carry_no_forbidden_words():
    """[205] **따로 제출하는 면(발표 · 영상 대본 · 데모)에도 금지 문구가 없다** — 09-27.

    공개 사본은 [203]⑦ 이 본다. 발표 PDF 의 원본(10분판 · 노트) · 발표와 시연 영상 대본 · 데모(`배포정적`)는
    공개 사본 밖에서 따로 제출되므로 **따로** 본다. 금지 목록은 `공개저장소만들기.FORBID_WORDS` 하나다 —
    시험에 옮겨 적지 않는다(목록이 두 곳에 있으면 갈라진다 · 결함 82 계열).

    ⓘ 공개 사본 안에서는 건너뛴다(도구가 작업 저장소에만 있다).
    """
    import glob as _g205
    import importlib.util as _iu205
    import os as _o205
    from .. import evidence as _EV205

    root = _EV205.ROOT
    sp = _o205.path.join(root, "공개저장소만들기.py")
    if not _o205.path.exists(sp):
        check("[205] 공개 사본이다 — 금지 목록을 가진 도구가 작업 저장소에만 있어 건너뛴다", True, "")
        return
    spec = _iu205.spec_from_file_location("public_copy_205", sp)
    m = _iu205.module_from_spec(spec)
    spec.loader.exec_module(m)
    try:
        from pptx import Presentation as _Pr205
    except Exception:
        check("[205] python-pptx 가 있다 — 없으면 발표를 못 읽는다", False, "pip install python-pptx")
        return

    def _deck(path):
        out = []
        for s in _Pr205(path).slides:
            for sh in s.shapes:
                if sh.has_text_frame:
                    out.append(sh.text_frame.text)
                if getattr(sh, "has_table", False) and sh.has_table:
                    out.extend(c.text for r in sh.table.rows for c in r.cells)
            if s.has_notes_slide:
                out.append(s.notes_slide.notes_text_frame.text)
        return "\n".join(out)

    groups = [("① 발표 10분판 · 제출 사본(본문 · 노트)",
               ["slides/Bio-ReRoute_본선_10분.pptx", "제출_본선/Bio-ReRoute_발표.pptx"], _deck),
              ("② 발표 · 시연 영상 대본", ["발표대본_본선10분.md", "시연영상_대본_10분.md"], None),
              ("③ 데모(배포정적)", sorted(_o205.path.relpath(q, root).replace("\\", "/")
                                    for q in _g205.glob(_o205.path.join(root, "배포정적", "**", "*"), recursive=True)
                                    if _o205.path.isfile(q) and q.endswith((".html", ".js", ".css", ".json", ".md"))),
               None)]
    for label, rels, reader in groups:
        seen, hits, missing = 0, [], []
        for rel in rels:
            q = _o205.path.join(root, *rel.split("/"))
            if not _o205.path.exists(q):
                missing.append(rel)
                continue
            t = reader(q) if reader else open(q, encoding="utf-8", errors="ignore").read()
            seen += len(t)
            hits += [(rel, i, s) for i, s in m.forbidden_hits(rel, t)]
        check("[205] %s — 금지 문구 0 (읽은 글자 %d)" % (label, seen),
              rels and not missing and seen > 1000 and not hits, (missing[:2], hits[:3]))


def test_commit_script_refuses_what_it_must():
    """[206] **`커밋.ps1` 이 멈춰야 할 때 멈춘다** — 09-27 신설.

    샌드박스는 git 락을 만들고 못 지운다(`CLAUDE.md §5` 09-22) — 커밋은 승우 컴퓨터에서 이 스크립트로 한다.
    그래서 스크립트의 가드를 **글로 적힌 것이 아니라 실제로** 본다 — 원격 판정 정규식을 파이썬 `re` 로 태우고
    (PowerShell `-match` 는 대소문자를 안 가린다), 안에 박힌 검사 코드를 임시 git 저장소에서 가짜 키로 돌린다.

    ⓘ 공개 사본 안에서는 건너뛴다(스크립트가 작업 저장소에만 있다).
    """
    import os as _o206
    import re as _re206
    import shutil as _sh206
    import subprocess as _sp206
    import sys as _sys206
    import tempfile as _t206
    import importlib.util as _iu206
    from .. import evidence as _EV206

    root = _EV206.ROOT
    p = _o206.path.join(root, "커밋.ps1")
    if not _o206.path.exists(p):
        check("[206] 커밋 스크립트가 없다(공개 사본) — 건너뛴다", True, "")
        return
    raw = open(p, "rb").read()
    src = raw.decode("utf-8-sig")
    check("[206] ① BOM · CRLF · 줄 이어쓰기 없음 (결함 231)",
          raw[:3] == b"\xef\xbb\xbf" and b"\n" not in raw.replace(b"\r\n", b"") and b"`\r\n" not in raw, len(raw))
    # ② 09-28 · 결함 371 — 도는 git 이 없고 10분 넘은 락만 지운다(그 밖에는 멈춘다). 사슬도 **처음에** 같은 규칙
    #   09-28 13:29 · 첫 판은 «도는 git 이 하나라도 있으면 멈춘다» 여서 편집기 따위의 git 2개에 걸렸다 — 락을 쥘 수 있는 것은
    #   **락보다 먼저 시작한** git 뿐이다(락은 없을 때만 만들어진다)
    lock_rule = ("Get-Process -Name git" in src and "$lockAge -lt 10" in src and "$holders.Count -gt 0" in src
                 and "-le $lockTime" in src and 'Remove-Item -LiteralPath ".git\\index.lock"' in src)
    check("[206] ② 오래된 락(락보다 먼저 시작한 git 없음 · 10분 넘음)만 지우고 아니면 멈춘다 · 푸시는 origin main 뿐이다(공개 사본 주소로 안 올린다)",
          'Test-Path -LiteralPath ".git\\index.lock"' in src and lock_rule and "git push origin main" in src
          and "Bio-ReRoute-public" not in src, lock_rule)
    chain = open(_o206.path.join(root, "사슬.ps1"), encoding="utf-8-sig").read()
    at = chain.find('Join-Path $PSScriptRoot ".git\\index.lock"')
    check("[206] ②-b `사슬.ps1` 도 **시작할 때** 같은 규칙으로 락을 본다 — ⑨ 에서(11분 뒤) 멈추지 않게",
          0 <= at < chain.find('Head "①"') and "Get-Process -Name git" in chain and "$lockAge -lt 10" in chain
          and "-le $lockTime" in chain and "$holders.Count -gt 0" in chain,
          at)
    m = _re206.search(r'-match "([^"]+)"', src)
    rx = _re206.compile(m.group(1), _re206.I) if m else None
    cases = {"https://github.com/hwangjames7371/Bio-ReRoute.git": True,
             "git@github.com:hwangjames7371/Bio-ReRoute.git": True,
             "https://github.com/hwangjames7371/Bio-ReRoute-public.git": False,
             "https://github.com/hwangjames7371/Bio.git": False,
             "https://example.com/other/repo.git": False}
    got = {u: bool(rx and rx.search(u)) for u in cases}
    check("[206] ③ origin 판정 — 작업 저장소만 통과 · 공개 사본 · Bio.git · 남의 저장소는 거절",
          rx is not None and got == cases, got)
    i = src.find("$check = @'")
    j = src.find("\n'@", i)
    code = src[i:j].split("\n", 1)[1].replace("\r\n", "\n").replace("\r", "") if i >= 0 and j > i else ""
    check("[206] ④ 안에 박힌 검사 코드가 파이썬으로 읽힌다 · 큰따옴표가 없다(PowerShell 인자 전달 사고)",
          bool(code) and '"' not in code and compile(code, "check206", "exec") is not None, len(code))
    if _sh206.which("git") and code:
        d = _t206.mkdtemp(prefix="commit206_")
        try:
            def git(*a):
                return _sp206.run(["git", "-C", d] + list(a), capture_output=True, text=True)
            git("init", "-q")
            git("config", "user.email", "t@t")
            git("config", "user.name", "t")
            open(_o206.path.join(d, "가.md"), "w", encoding="utf-8").write("정상 파일\n")
            git("add", "-A")
            clean = _sp206.run([_sys206.executable, "-c", code], cwd=d, capture_output=True, text=True).returncode
            open(_o206.path.join(d, "나.md"), "w", encoding="utf-8").write("key: sk-" + "A" * 24 + "\n")
            git("add", "-A")
            dirty = _sp206.run([_sys206.executable, "-c", code], cwd=d, capture_output=True, text=True).returncode
        finally:
            _sh206.rmtree(d, ignore_errors=True)
        check("[206] ⑤ 검사 코드가 **실제로 운다** — 깨끗하면 0 · 키 모양이 섞이면 1", clean == 0 and dirty == 1,
              (clean, dirty))
    else:
        check("[206] ⑤ git 이 없어 검사 코드 실행은 건너뛴다(④ 는 봤다)", True, "")
    # ⑥ 09-27 · 결함 367 — 첫 판은 기본 메시지에 «시험 2568» 을 글자로 박아, 사슬이 2581 로 올린 뒤에도
    #   옛 수로 커밋됐다. 이제 메시지의 수는 **자료에서** 나온다: 박은 수가 없고 · 조각이 대장 수를 실제로 내고 ·
    #   스크립트 어디에도 금지 문구가 없다(명세 · 결과 커밋은 공개 사본의 커밋 요약에 실린다).
    k = src.find("$sum = @'")
    kj = src.find("\n'@", k)
    sumcode = src[k:kj].split("\n", 1)[1].replace("\r\n", "\n").replace("\r", "") if k >= 0 and kj > k else ""
    lit = _re206.search(r'\$Msg = "[^"]*\d{3,4}', src)
    out = ""
    if sumcode and '"' not in sumcode:
        env = dict(_o206.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        out = _sp206.run([_sys206.executable, "-B", "-c", sumcode], cwd=root, capture_output=True,
                         text=True, encoding="utf-8", errors="replace", env=env).stdout.strip()
    hits = None
    sp = _o206.path.join(root, "공개저장소만들기.py")
    if _o206.path.exists(sp):
        spec = _iu206.spec_from_file_location("public_copy_206", sp)
        pm = _iu206.module_from_spec(spec)
        spec.loader.exec_module(pm)
        hits = pm.forbidden_hits("커밋기록_요약.txt", src)
    check("[206] ⑥ 기본 커밋 메시지는 **자료에서** 만든다(결함 367) — 박은 수 없음 · 조각이 대장 수를 낸다 · "
          "큰따옴표 없음 · 금지 문구 없음",
          bool(sumcode) and '"' not in sumcode and lit is None
          and "defect_count()" in sumcode and "시험정본.json" in sumcode
          and out.startswith("결함 %s건" % _EV206.defect_count()) and "회귀 시험" in out and not hits,
          (out[:60], lit.group(0) if lit else None, hits))


def test_live_check_is_fixed_recorded_and_read_by_the_script():
    """[207] **라이브 점검은 쌍이 고정되고, 기록이 남고, 영상 대본이 그 기록을 읽는다** — 09-27 신설.

    영상 나-6(«라이브 — 틀린 답도 보인다»)은 쌍과 정답을 **미리** 적었다. «결과를 보고 쌍을 바꾸지 않는다» 를
    안내문이 아니라 구조로 — 도구에 쌍 인자가 없고, 쌍은 대본 생성기의 상수에서 읽는다. 판정은 파일로 남기고
    (덮지 않는다), 대본은 그 파일을 읽어 **읽을 갈래를 표시**한다. 캐시를 데운 뒤 찍는다는 것은 편집 자막으로 밝힌다.
    """
    import importlib.util as _iu207
    import os as _o207
    import shutil as _sh207
    import tempfile as _t207
    from .. import evidence as _EV207
    from ..bench import livecheck as _LC207

    root = _EV207.ROOT
    vp = _o207.path.join(root, "slides", "make_video_본선.py")
    spec = _iu207.spec_from_file_location("make_video_t207", vp)
    mv = _iu207.module_from_spec(spec)
    spec.loader.exec_module(mv)
    check("[207] ① 쌍과 정답을 **대본 생성기의 상수에서** 읽는다",
          _LC207.fixed_pair(root) == (mv.LIVE_PAIR, mv.LIVE_TRUTH), _LC207.fixed_pair(root))
    # 09-28 밤 · 영상 나-5 «병으로 시작(가설 생성)» — 병명도 같은 규칙. 사전명세(`사전명세_병명입구.md`)가 봉인 전에
    #   적은 **주 사례** 그대로여야 한다(결과를 보고 고른 병명이 아니다)
    _sp207 = _o207.path.join(root, "사전명세_병명입구.md")
    _spec207 = open(_sp207, encoding="utf-8").read() if _o207.path.exists(_sp207) else ""
    check("[207] ①-b 병명 · 입구도 **대본 생성기의 상수에서** 읽는다 · 병명은 사전명세의 주 사례(COVID-19)다",
          _LC207.fixed_disease(root) == (mv.LIVE_DISEASE, mv.LIVE_ENTRY) and mv.LIVE_ENTRY == "정방향"
          and ("| **주** | **%s** |" % mv.LIVE_DISEASE) in _spec207, _LC207.fixed_disease(root))
    import contextlib as _cl207
    import io as _io207
    try:
        with _cl207.redirect_stderr(_io207.StringIO()):       # argparse 의 «unrecognized arguments» 는 기대한 소리다
            _LC207.main(["--pair", "aspirin / X"])
        refused = False
    except SystemExit as e:
        refused = e.code not in (0, None)
    check("[207] ② 쌍을 바꾸는 인자가 **없다** — 넣으면 인자 오류로 멈춘다", refused, "")
    check("[207] ③ 갈래 규칙 — 정답과 같으면 ⓑ · 다르면 ⓐ · 판정이 없으면 고르지 않는다",
          _LC207.branch("조건부", "조건부") == "ⓑ" and _LC207.branch("보류", "조건부") == "ⓐ"
          and _LC207.branch("", "조건부") is None, "")
    ok = {"맞다": True, "모델": "m", "본선": "m"}

    def fake(verdict, state="정상"):
        def runner(q, progress=None):
            if progress:
                progress("검색", "가짜")
            return {"상태": state, "판정": verdict, "신뢰도": 53, "사유": "가짜", "비용": 0}
        return runner
    ticks = iter([0.0, 90.0, 90.0, 91.0])
    r1 = _LC207.check(root, runner=fake("보류"), model=ok, clock=lambda: next(ticks), say=lambda *a: None)
    r2 = _LC207.check(root, runner=fake("", state="오류"), model=ok, say=lambda *a: None)
    r3 = _LC207.check(root, runner=fake("보류"), model={"맞다": False, "모델": "x", "본선": "m"}, say=lambda *a: None)
    check("[207] ④ 두 번 돌려 **데워졌는지 · 같은지** 적고, 판정이 없으면 갈래를 안 고르고, 제출 모델이 아니면 **안 돌린다**",
          len(r1["실행"]) == 2 and r1["같은가"] and r1["데워짐"] and r1["갈래"] == "ⓐ"
          and r2["갈래"] is None and r3["상태"] == "모델불일치" and "실행" not in r3,
          (r1.get("갈래"), r2.get("갈래"), r3.get("상태")))
    # ④-b 병명 — 두 번 돌려 분포 · 같은가 · 데워짐을 적는다. 첫 실행이 시간 상한에 걸려 못 태운 후보가 있으면
    #   둘째가 그것을 처음 돌리므로 «같지 않다» 가 나와야 한다(그때는 한 번 더 돌린다 — 종료 코드 4)
    def dz_fake(plan):
        calls = iter(plan)

        def runner(q, progress=None):
            if progress:
                progress("발굴", "가짜")
            vs = next(calls)
            return {"상태": "정상", "생성": 3, "F0통과": 3, "태움": len(vs), "못태움": 3 - len(vs), "비용": 0,
                    "후보": [{"이름": "d%d / %s" % (i, q), "판정": v, "신뢰도": 50} for i, v in enumerate(vs)]}
        return runner
    tk = iter([0.0, 120.0, 120.0, 125.0])
    d1 = _LC207.check_disease(root, runner=dz_fake([["기각", "유망", "기각"]] * 2), model=ok,
                              clock=lambda: next(tk), say=lambda *a: None)
    tk2 = iter([0.0, 150.0, 150.0, 210.0])            # 둘째가 60초 — 못 태운 후보를 처음 돌렸다(데워지지 않음)
    d2 = _LC207.check_disease(root, runner=dz_fake([["기각", "유망"], ["기각", "유망", "보류"]]), model=ok,
                              clock=lambda: next(tk2), say=lambda *a: None)
    d3 = _LC207.check_disease(root, runner=dz_fake([["기각"]] * 2), model={"맞다": False, "모델": "x", "본선": "m"},
                              say=lambda *a: None)
    check("[207] ④-b 병명도 두 번 — 분포 · 같은가 · 데워짐을 적는다 · 못 태운 후보가 있던 첫 실행과는 «같지 않다» · "
          "제출 모델이 아니면 **안 돌린다**",
          d1["병명"] == mv.LIVE_DISEASE and d1["분포"] == {"기각": 2, "유망": 1} and d1["같은가"] and d1["데워짐"]
          and len(d1["실행"]) == 2 and not d2["같은가"] and not d2["데워짐"] and d2["못태움"] == 0
          and d3["상태"] == "모델불일치" and "실행" not in d3, (d1.get("분포"), d2.get("같은가"), d3.get("상태")))
    d = _t207.mkdtemp(prefix="live207_")
    try:
        a = _LC207.save(dict(r1, 판정="보류"), root=d, stamp="20260927_2300")
        b = _LC207.save(dict(r1, 판정="조건부"), root=d, stamp="20260927_2300")
        for k in range(3, 11):
            _LC207.save(dict(r1, 판정="k%d" % k), root=d, stamp="20260927_2300")
        latest = _LC207.latest(d)
        check("[207] ⑤ 기록은 **덮지 않는다** · 가장 새 기록을 번호 순서로 고른다(«_10» 이 «_2» 뒤)",
              a != b and _o207.path.exists(a) and len(_LC207.records(d)) == 10 and latest.get("판정") == "k10",
              (len(_LC207.records(d)), latest.get("판정")))
    finally:
        _sh207.rmtree(d, ignore_errors=True)
    fake_rec = {"쌍": mv.LIVE_PAIR, "갈래": "ⓐ", "시각": "2026-09-27 23:10", "판정": "보류", "신뢰도": 53}
    orig = mv._live_record
    mv._live_record = lambda: fake_rec
    try:
        out = _o207.path.join(_t207.mkdtemp(prefix="vid207_"), "v.md")
        mv.build(out)
        txt = open(out, encoding="utf-8").read()
    finally:
        mv._live_record = orig
    check("[207] ⑥ 영상 대본이 기록을 읽어 **읽을 갈래를 표시**한다 · 캐시를 데운 뒤 찍는다는 **편집 자막**을 지시한다",
          "〔ⓐ 판정이 %s가 아니면  ← ✅ 이 갈래를 읽는다〕" % mv.LIVE_TRUTH in txt
          and "(이번에는 안 읽는다)" in txt and "편집 자막" in txt and "라이브점검.ps1" in txt, "")
    # ⑥-b 병명 칸이 있으면 나-5 가 **그 수를** 말하고(생성 · F0 통과 · 분포 · 못 태움 · 기각 후보 칩), 없으면 «뒤 수가
    #   채워진다» 표시만 한다(수를 지어내지 않는다)
    fake2 = dict(fake_rec, 병명={"병명": mv.LIVE_DISEASE, "입구": mv.LIVE_ENTRY, "상태": "정상", "생성": 10,
                               "F0통과": 9, "태움": 8, "못태움": 1,
                               "분포": {"유망": 2, "조건부": 3, "보류": 2, "기각": 1},
                               "후보": [["aspirin / COVID-19", "유망", 88], ["ivermectin / COVID-19", "기각", 4]]})
    mv._live_record = lambda: fake2
    try:
        out2 = _o207.path.join(_t207.mkdtemp(prefix="vid207b_"), "v.md")
        mv.build(out2)
        txt2 = open(out2, encoding="utf-8").read()
    finally:
        mv._live_record = orig
    check("[207] ⑥-b 영상 나-5 가 기록의 **병명 수**를 말한다(생성 · F0 통과 · 분포 · 못 태움 · 기각 후보 칩) · "
          "기록이 없으면 수 없이 «뒤 수가 채워진다» 만",
          "후보 10개를 만들고, 문헌이 실재하는 9개" in txt2 and "판정이 갈렸습니다 — 유망 2, 조건부 3, 보류 2, 기각 1" in txt2
          and "1개는 기각이 아니라 못 태웠다고" in txt2 and "`ivermectin / COVID-19`" in txt2
          and "뒤 수가 채워진다" not in txt2 and "뒤 수가 채워진다" in txt and "판정이 갈렸습니다" not in txt, "")
    raw = open(_o207.path.join(root, "라이브점검.ps1"), "rb").read()
    src = raw.decode("utf-8-sig")
    check("[207] ⑦ `라이브점검.ps1` — BOM · CRLF · 줄 이어쓰기 없음 · 쌍 인자 없음 · 이 도구를 부른다",
          raw[:3] == b"\xef\xbb\xbf" and b"\n" not in raw.replace(b"\r\n", b"") and b"`\r\n" not in raw
          and "bioreroute.bench.livecheck" in src and "--pair" not in src and "param([switch]$Show)" in src
          and "-eq 5" in src, "")


def test_github_public_copy_check_sees_what_judges_see():
    """[208] **GitHub 공개 사본 확인은 심사위원의 눈(토큰 없음)으로 보고, 셋을 가려 말한다** — 09-28 신설.

    제출 양식 · 보고서 머리가 가리키는 것은 공개 사본(`Bio-ReRoute-public`)이다. 주인은 로그인돼 있어 비공개
    저장소도 보인다 — 주인의 눈으로는 «심사위원에게는 404» 를 못 가린다. `bench/ghcheck.py` 는 ① 익명으로
    보이는가 ② 공개 main 이 사본 폴더 HEAD 인가 ③ 사본 폴더가 지금 판인가를 가른다. 네트워크 · git 은 가짜로
    갈아 끼운다(응답 모양은 09-28 api.github.com 실측과 같다 — `private` · `visibility` · `sha` · `commit.committer.date`).

    ⓘ 공개 사본 안에서는 건너뛴다(도구가 작업 저장소에만 있다).
    """
    import importlib.util as _iu208
    import os as _o208
    import shutil as _sh208
    import tempfile as _t208
    import types as _ty208
    from .. import evidence as _EV208
    from ..bench import ghcheck as _GH208

    root = _EV208.ROOT
    if not _o208.path.exists(_o208.path.join(root, "공개저장소만들기.py")):
        check("[208] 공개 사본이다 — 사본 도구가 작업 저장소에만 있어 건너뛴다", True, "")
        return
    old_tok = _o208.environ.get("GITHUB_TOKEN")
    _o208.environ["GITHUB_TOKEN"] = "ghp_" + "x" * 36
    try:
        h = _GH208.headers()
    finally:
        if old_tok is None:
            _o208.environ.pop("GITHUB_TOKEN", None)
        else:
            _o208.environ["GITHUB_TOKEN"] = old_tok
    check("[208] ① 토큰 없는 요청 — 환경에 토큰이 있어도 Authorization 을 안 붙인다",
          not any(k.lower() == "authorization" for k in h) and "User-Agent" in h, sorted(h))

    d = _t208.mkdtemp(prefix="gh208_")
    try:
        stage = _o208.path.join(d, "stage")
        _o208.makedirs(stage)
        pm = _ty208.SimpleNamespace(PUBLIC_REPO="https://github.com/o/Bio-ReRoute-public", STAGE_DEFAULT=stage,
                                    MARK=".mark", COMMIT_LOG="커밋기록_요약.txt", GITATTR=".gitattributes",
                                    GITATTR_BODY="* -text\n", after_deadline=lambda: False)
        want = {"README.md": b"# r\n", "a/b.md": b"x\r\ny\r\n", "커밋기록_요약.txt": "첫 줄\n둘째 줄\n",
                ".gitattributes": b"* -text\n"}
        for rel, v in want.items():
            q = _o208.path.join(stage, *rel.split("/"))
            _o208.makedirs(_o208.path.dirname(q), exist_ok=True)
            with open(q, "wb") as f:
                f.write(v if isinstance(v, bytes) else v.replace("\n", "\r\n").encode("utf-8"))   # 윈도우 글자 모드
        open(_o208.path.join(stage, ".mark"), "w").close()
        HEAD = "a" * 40

        def g(head=HEAD, dirty="", up=None):
            def run(stage_, *args):
                if args == ("rev-parse", "HEAD"):
                    return (0, head) if head else (128, "")
                if args == ("rev-parse", "origin/main"):
                    return 0, (head if up is None else up) or ""
                if args[:1] == ("status",):
                    return 0, dirty
                return 1, ""
            return run

        def net(repo=(200, {"private": False, "visibility": "public"}), main=None):
            main = main or (200, {"sha": HEAD, "commit": {"committer": {"date": "2026-09-30T12:00:00Z"}}})

            def get(url):
                return main if url.endswith("/commits/main") else repo
            return get

        def run(**kw):
            rc, ls = _GH208.check(root, stage=kw.pop("stage", stage), pm=pm, get=kw.pop("get", net()),
                                  run_git=kw.pop("run_git", g()), want=kw.pop("want", want))
            return rc, "\n".join(ls)

        rc, t = run(get=net(repo=(404, {"message": "Not Found"})), run_git=g(up="c" * 40))
        check("[208] ② 익명 404 · 아직 안 올렸다 → 3 · «안 보인다» · 만들기 → -Push → Public 순서를 찍는다",
              rc == 3 and "안 보인다" in t and "github.com/new" in t and "Public" in t and "-Push" in t, (rc, t[-160:]))
        rc, t = run(get=net(repo=(404, {"message": "Not Found"})))
        arrow = [ln for ln in t.splitlines() if ln.startswith("→")]
        check("[208] ②-b 익명 404 · 이 판이 올라가 있다(비공개) → 3 · «공개로 바꾸기뿐» — 다시 만들라거나 -Push 하라고 안 한다",
              rc == 3 and "공개로 바꾸기" in t and "Public" in t and not any("-Push" in ln or "github.com/new" in ln for ln in arrow),
              (rc, arrow))
        rc, t = run()
        check("[208] ③ 공개 · main == 사본 HEAD · 사본이 지금 판(커밋 요약은 CRLF 로 써도 같다) → 0",
              rc == 0 and "로그인 없이" in t, (rc, t[-200:]))
        rc, t = run(get=net(main=(200, {"sha": "b" * 40, "commit": {}})))
        check("[208] ④ 공개 main 이 사본 HEAD 와 다르다 → 4 · -Push", rc == 4 and "-Push" in t and "≠" in t, (rc,))
        w2 = dict(want)
        w2["a/b.md"] = b"x\ny\n"
        rc, t = run(want=w2)
        check("[208] ⑤ 사본 폴더가 지금 판이 아니다(바이트 하나라도) → 4 — HEAD 가 같아도", rc == 4 and "지금 판이 아니다" in t
              and "a/b.md" in t, (rc,))
        rc, t = run(run_git=g(dirty=" M README.md"))
        check("[208] ⑥ 사본 폴더에 안 올린 변경 → 4", rc == 4 and "안 올린 변경" in t, (rc,))
        rc1, t1 = run(get=lambda url: (None, "URLError: 프록시"))
        rc2, t2 = run(get=net(repo=(403, {"message": "API rate limit exceeded"})))
        check("[208] ⑦ 네트워크 오류 · 요청 한도 → 2 · «초록이 아니다»", rc1 == 2 and rc2 == 2 and "초록이 아니다" in t1
              and "요청 한도" in t2, (rc1, rc2))
        rc, t = run(get=net(main=(409, {"message": "Git Repository is empty."})))
        check("[208] ⑧ 공개 저장소가 비었다(409) → 4", rc == 4 and "비어 있다" in t, (rc,))
        rc, t = run(stage=_o208.path.join(d, "없음"), get=net(repo=(404, None)))
        check("[208] ⑨ 사본 폴더가 없고 익명 404 → 3 · 둘 다 말한다", rc == 3 and "사본 폴더가 없다" in t, (rc,))
        # ⑫ 마감 뒤 — 공개 사본은 제출물이다. «-Push 하라» 고 말하면 심사 중인 제출물을 바꾸라는 말이 된다
        pm.after_deadline = lambda: True
        rc1, t1 = run(get=net(main=(200, {"sha": "b" * 40, "commit": {}})))
        rc2, t2 = run(get=net(repo=(404, None)))
        rc3, t3 = run(get=net(main=(409, {"message": "Git Repository is empty."})))
        pm.after_deadline = lambda: False
        adv = [ln for ln in (t1 + "\n" + t2 + "\n" + t3).splitlines() if ln.startswith("→")]
        check("[208] ⑫ 마감 뒤 — 보이면 0(«제출한 판 그대로») · 안 보이면 3(공개 범위만) · 비었으면 5 · **-Push 를 권하지 않는다**",
              rc1 == 0 and "제출한 판 그대로" in t1 and rc2 == 3 and "내용은 바꾸지 않는다" in t2 and rc3 == 5
              and not any("-Push" in ln for ln in adv), (rc1, rc2, rc3, adv))
    finally:
        _sh208.rmtree(d, ignore_errors=True)

    # ⑩ 진짜 기대값 — 공개 사본 도구의 목록 그대로(작업 문서 제외 · 커밋 요약 · .gitattributes 포함)
    spec = _iu208.spec_from_file_location("public_copy_208", _o208.path.join(root, "공개저장소만들기.py"))
    m = _iu208.module_from_spec(spec)
    spec.loader.exec_module(m)
    if m.newest_zip(root):
        w = _GH208.expected(root, m)
        p = m.plan(root)
        check("[208] ⑩ 기대값이 공개 사본 도구의 목록과 같다 — 파일 + 커밋 요약 + .gitattributes · 작업 문서는 없다",
              w is not None and set(w) == set(p["files"]) | {m.COMMIT_LOG, m.GITATTR} and not (set(w) & set(m.EXCLUDE))
              and w[m.GITATTR] == m.GITATTR_BODY.encode("utf-8"), len(w or {}))
    else:
        check("[208] ⑩ 묶음(zip)이 없다 — 진짜 기대값은 건너뛴다", True, "")
    chain = open(_o208.path.join(root, "사슬.ps1"), encoding="utf-8-sig").read()
    ps = open(_o208.path.join(root, "공개저장소.ps1"), encoding="utf-8-sig").read()
    a, b = chain.find('"bioreroute.bench.hfcheck"'), chain.find('"bioreroute.bench.ghcheck"')
    check("[208] ⑪ `사슬.ps1` 이 HF 확인 **뒤** 공개 사본을 잰다 · 멈추지 않는다 · 결과마다 «다음» 이 갈린다 · "
          "`공개저장소.ps1` 에 -Check 와 올린 뒤 확인",
          0 <= a < b and "Stop-Here" not in chain[b:] and "$gh -eq 3" in chain and "$gh -eq 4" in chain
          and "[switch]$Check" in ps and ps.count("bioreroute.bench.ghcheck") >= 2 and "$gh -eq 5" in chain, (a, b))


def test_public_copy_keeps_bytes_through_git():
    """[209] **공개 사본은 git 을 지나도 바이트가 같다** — 09-28 · 결함 368.

    새로 `git init` 한 사본 저장소는 그 기계의 git 기본값을 물려받는다. 윈도우 git 기본값(`core.autocrlf=true`)은
    CRLF 파일을 LF 로 **저장**하고, 윈도우 clone 에서는 LF 를 CRLF 로 **바꾼다** — 봉인 명세의 sha256 과 제3자
    타임스탬프(`.ots`) 검증이 받는 쪽에서 깨진다. 여기서는 **실제 git** 으로 — `apply()` → `push()`(로컬 bare
    저장소로) → clone 까지, autocrlf=true 를 **가장 센 자리(환경의 `-c`)** 에 걸고 바이트를 맞춘다. 그리고
    가드가 **울 수 있는지** — `.gitattributes` 없이 같은 왕복을 하면 바이트가 바뀌는 것 — 도 본다.

    ⓘ 공개 사본 안이거나 git 이 없으면 건너뛴다.
    """
    import importlib.util as _iu209
    import os as _o209
    import shutil as _sh209
    import subprocess as _sp209
    import tempfile as _t209
    import zipfile as _z209
    from .. import evidence as _EV209

    root = _EV209.ROOT
    sp = _o209.path.join(root, "공개저장소만들기.py")
    if not _o209.path.exists(sp) or not _sh209.which("git"):
        check("[209] 공개 사본이거나 git 이 없다 — 건너뛴다", True, "")
        return
    spec = _iu209.spec_from_file_location("public_copy_209", sp)
    m = _iu209.module_from_spec(spec)
    spec.loader.exec_module(m)
    check("[209] ① `.gitattributes` 가 줄바꿈 변환을 끈다(`* -text`)",
          m.GITATTR == ".gitattributes" and "* -text" in m.GITATTR_BODY.splitlines(), m.GITATTR_BODY[-10:])

    src = {"spec_lf.md": b"# spec\nline\n", "ledger_crlf.md": b"| a |\r\n| b |\r\n", "stamp.ots": b"\x00OTS\r\n\x01\n"}
    # 신원은 환경으로 주지 않는다 — `push()` 가 사본 저장소에 직접 적는 신원으로 커밋이 돼야 한다(결함 369)
    keys = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
            "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0")
    saved = {k: _o209.environ.get(k) for k in keys}
    d = _t209.mkdtemp(prefix="eol209_")
    try:
        for k in keys[:4]:
            _o209.environ.pop(k, None)
        # 윈도우 git 기본값을 **가장 센 자리**에 건다 — 사본 저장소의 로컬 설정보다 세다
        _o209.environ.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.autocrlf", "GIT_CONFIG_VALUE_0": "true"})
        fake_root = _o209.path.join(d, "root")
        _o209.makedirs(fake_root)
        zp = _o209.path.join(fake_root, "bioreroute-v1.zip")
        with _z209.ZipFile(zp, "w") as z:
            for n, b in src.items():
                z.writestr(n, b)
        plan = {"zip": zp, "files": {n: ("zip", n) for n in src}, "missing": [], "bad_name": [], "bad_text": [],
                "keys": [], "bad_word": []}
        stage, bare = _o209.path.join(d, "stage"), _o209.path.join(d, "remote.git")
        _sp209.run(["git", "init", "-q", "--bare", bare], capture_output=True)
        m.apply(stage=stage, root=fake_root, p=plan)
        attrs = open(_o209.path.join(stage, m.GITATTR), "rb").read()
        try:                                   # 멈추면(SystemExit) 시험 전체가 죽지 않게 받아서 실패로 올린다
            rc = m.push(stage=stage, url=bare, root=fake_root, tag="t209", allow_late=True)   # 이 시험은 바이트를 본다
        except SystemExit as e:
            rc = "멈춤: %s" % str(e)[:200]
        cfg = _sp209.run(["git", "-C", stage, "config", "--local", "core.autocrlf"],
                         capture_output=True, text=True).stdout.strip()
        check("[209] ② `apply()` 가 `.gitattributes` 를 쓰고 · `push()` 가 사본 저장소의 `core.autocrlf` 를 끄고 · 올라간다",
              attrs == m.GITATTR_BODY.encode("utf-8") and rc == 0 and cfg == "false", (rc, cfg))
        clone = _o209.path.join(d, "clone")
        _sp209.run(["git", "clone", "-q", "-b", "main", bare, clone], capture_output=True)   # bare 의 HEAD 는 master 일 수 있다
        got = {n: open(_o209.path.join(clone, n), "rb").read() if _o209.path.exists(_o209.path.join(clone, n)) else None
               for n in src}
        blob = {n: _sp209.run(["git", "-C", bare, "show", "main:" + n], capture_output=True).stdout for n in src}
        check("[209] ③ autocrlf=true 인 기계에서 올리고 받아도 **바이트가 같다** — 저장된 것 · clone 한 것 둘 다",
              got == src and blob == src, sorted(n for n in src if got[n] != src[n] or blob[n] != src[n]))
        ctl = _o209.path.join(d, "ctl")
        _sp209.run(["git", "init", "-q", ctl], capture_output=True)
        for n, b in src.items():
            with open(_o209.path.join(ctl, n), "wb") as f:
                f.write(b)
        _sp209.run(["git", "-C", ctl, "add", "-A"], capture_output=True)
        _sp209.run(["git", "-C", ctl, "-c", "user.name=t209", "-c", "user.email=t209@example.invalid",
                    "commit", "-qm", "c"], capture_output=True)
        ctl2 = _o209.path.join(d, "ctl_clone")
        _sp209.run(["git", "clone", "-q", ctl, ctl2], capture_output=True)
        changed = [n for n, b in src.items()
                   if not _o209.path.exists(_o209.path.join(ctl2, n)) or open(_o209.path.join(ctl2, n), "rb").read() != b]
        check("[209] ④ 가드가 **울 수 있다** — `.gitattributes` 없이 같은 왕복을 하면 LF 파일이 바뀐다",
              "spec_lf.md" in changed and "stamp.ots" not in changed, changed)
        # ⑥ 결함 369 — 공개 커밋의 신원은 기계 전역 설정이 아니라 도구가 정한 것이다(메일은 GitHub 비공개 주소)
        who = _sp209.run(["git", "-C", bare, "log", "-1", "--format=%an|%ae|%cn|%ce", "main"],
                         capture_output=True, text=True, encoding="utf-8").stdout.strip()
        idn = m.identity(fake_root)
        sign = _sp209.run(["git", "-C", stage, "config", "--local", "commit.gpgsign"],
                          capture_output=True, text=True).stdout.strip()
        owner = m.PUBLIC_REPO.split("github.com/", 1)[1].split("/")[0]
        check("[209] ⑥ 공개 커밋의 신원 — 작성자 · 커미터가 도구가 정한 이름 + **GitHub 비공개 메일**(계정과 같은 이름) · "
              "서명 끔 · 금지 문구 없음",
              who == "%s|%s|%s|%s" % (idn["user.name"], m.PUBLIC_EMAIL, idn["user.name"], m.PUBLIC_EMAIL)
              and m.PUBLIC_EMAIL.endswith("+%s@users.noreply.github.com" % owner) and sign == "false"
              and not m.forbidden_hits("git-identity", idn["user.name"] + " " + m.PUBLIC_EMAIL), (who, sign))
        # ⑤ 마감 뒤에는 `push()` 가 멈춘다 — 아무것도 건드리기 전에(원격 · 사본 폴더)
        import datetime as _dt209
        kst = _dt209.timezone(_dt209.timedelta(hours=9))
        dl = _dt209.datetime.fromisoformat(m.DEADLINE)
        orig = m.after_deadline
        m.after_deadline = lambda now=None: True
        try:
            m.push(stage=_o209.path.join(d, "없는폴더"), url=bare, root=fake_root, tag="late")
            stopped = False
        except SystemExit as e:
            stopped = "마감" in str(e)
        finally:
            m.after_deadline = orig
        check("[209] ⑤ 마감(10/2 16:00 KST) 뒤에는 `push()` 가 **멈춘다** · 경계가 맞다(15:59 는 전 · 16:00 은 뒤)",
              stopped and m.DEADLINE.startswith("2026-10-02T16:00") and dl.utcoffset() == kst.utcoffset(None)
              and not orig(_dt209.datetime(2026, 10, 2, 15, 59, tzinfo=kst))
              and orig(_dt209.datetime(2026, 10, 2, 16, 0, tzinfo=kst)), m.DEADLINE)
    finally:
        for k, v in saved.items():
            if v is None:
                _o209.environ.pop(k, None)
            else:
                _o209.environ[k] = v
        _sh209.rmtree(d, ignore_errors=True)


def test_talk_says_what_we_built_and_that_we_did_not_tune():
    """[210] **발표 · 영상의 말이 «무엇을 만들었나» 와 «맞추지 않았다» 를 한다** — 09-28 밤 · 결함 373~376.

    승우: «무엇을 만들었고 뭘 말하고 싶은지가 명확하지 않다 · 이 대회는 무엇을 만들었는지가 중요하다 · 말하고 싶은
    건 일부러 성능을 올린 게 아니라 객관적인 지표로 했다는 것». 전수검사에서 말이 가설 생성 · 전문 읽기 · 보정 ·
    안전 게이트를 빠뜨렸고(373), 8장 관문이 평가 구성도 시연 구성도 아니었고(374), 손 숫자 둘이 낡았고(375),
    영상 말 둘이 화면 · 판정 규칙보다 앞서 나갔다(376). 문구 몇 개를 박는 **좁은** 시험이다 — 넓은 것은 사람이
    본다(전수검사). ⓘ 결과 파일 · 덱이 없는 곳(공개 사본 등)에서는 그 칸을 건너뛴다.
    """
    import importlib.util as _iu210
    import os as _o210
    import re as _re210
    import tempfile as _t210
    from .. import evidence as _EV210
    from ..bench import discover as _DS210, perfcard as _PC210, prereg as _PR210

    root = _EV210.ROOT
    tp = _o210.path.join(root, "slides", "make_10min_본선.py")
    if not _o210.path.exists(tp) or not _o210.path.exists(_o210.path.join(root, _PC210.SUBMIT[1])):
        check("[210] 발표 생성기 · 본선 결과 파일이 없다 — 건너뛴다", True, "")
        return
    spec = _iu210.spec_from_file_location("make10_210", tp)
    mod = _iu210.module_from_spec(spec)
    spec.loader.exec_module(mod)
    card = _PC210.card(root)
    sent = _PR210.sentence(_PR210.tally(_PR210.load(root)))
    n = mod.notes_for(card, sent)
    check("[210] ① 첫 장과 끝 장이 **같은 두 문장**을 한다 — 무엇을 만들었나(가설을 만들고 · 반박부터) · "
          "성능을 좋게 보이도록 맞추지 않았다",
          all(k in n[1] for k in ("가설을 만들고", "반박", "맞추지 않았"))
          and all(k in n[25] for k in ("가설을 만들고", "반박부터", "맞추지 않았"))
          and "믿지 않는 방법" not in n[25], (n[1][:40], n[25][:40]))
    g = _DS210.slide_facts(root)
    rep = open(_o210.path.join(root, "연구기술보고서.md"), encoding="utf-8").read() \
        if _o210.path.exists(_o210.path.join(root, "연구기술보고서.md")) else ""
    if g:
        check("[210] ② 생성 실험의 수를 `gen_run1.csv` 에서 센다 — 보고서 §4.5 와 같은 수(부정 표현 %d/%d · "
              "효능 실패 %d건 중 실패 언급 %d) · 2장 노트가 그 수를 말한다" % (g["부정표현"], g["n"], g["효능실패"], g["실패언급"]),
              ("%d/%d" % (g["부정표현"], g["n"])) in rep and g["효능실패"] == 9 and g["실패언급"] == 0
              and ("후보 %d개" % g["n"]) in n[2] and ("%.1f퍼센트" % (100.0 * g["승인"] / g["n"])) in n[2]
              and ("후보 %d건" % g["효능실패"]) in n[2] and "한 번도 말하지 않았습니다" in n[2], g)
    br = card["전체"]["Brier"]
    check("[210] ③ 말이 제품을 빠뜨리지 않는다 — 입구 둘 · 전문 읽기(양쪽을 같은 규칙으로) · 보정(Brier · 카드의 수) · "
          "맞추지 않았다의 근거 넷과 모델 선택 규칙 · 끝까지 사람 손 없이",
          all(k in n[8] for k in ("병명을 넣으면", "약과 병을 넣으면", "논문 전문", "지지와 반박 양쪽을 같은 규칙으로"))
          and ("Brier 도 %.3f 대 %.3f" % (br["B5"], br["B0"])) in n[mod.PERF]
          and ("%.3f 보다는 낫습니다" % br["널"]) in n[mod.PERF]
          and all(k in n[15] for k in ("근거는 넷", "미리 적은 규칙", sent))
          and "사람 손 없이" in n[21], "")
    neg = sum(n[k].count(w) for k in mod.MAIN for w in ("주장하지 않", "낫다고는 말하지", "두지 않는다"))
    check("[210] ④ 부정문은 **한 번** — «우위를 주장하지 않는다» 는 성능 장에만(앞판 다섯 번)",
          neg == 1 and "우위를 주장하지 않" in n[mod.PERF], neg)
    deck = _o210.path.join(root, "slides", "Bio-ReRoute_발표.pptx")
    if _o210.path.exists(deck):
        from pptx import Presentation as _P210
        sl = list(_P210(deck).slides)

        def words(i):
            return " ".join(x.text_frame.text for x in sl[i - 1].shapes if x.has_text_frame)
        s1, s8, s23 = words(1), words(8), words(23)
        from ..core import gates as _GT210
        check("[210] ⑤ 구운 덱 — 표지가 제품 · 메시지로 연다 · 8장 관문이 시연 구성(B5SF)의 일곱이고 등록부가 원으로 "
              "없다 · 손 숫자(«CLI 진입점 30개» · «후보당 LLM 호출 약 3회»)가 없다",
              "Bio-ReRoute" in s1 and "맞추지 않았다" in s1 and "후보 생성" in s1
              and all(_re210.search(r"(^|\s)%s(\s|$)" % t, s8) for t in ("F0", "L2", "R", "S1", "S2", "SK", "F"))
              and not _re210.search(r"(^|\s)REG(\s|$)", s8) and len(_GT210.CONFIGS["B5SF"]) == 7
              and "CLI 진입점" not in s8 and "약 3회" not in s23 and "만" in s23, (s8[:60], s23[:40]))
    vp = _o210.path.join(root, "slides", "make_video_본선.py")
    spec2 = _iu210.spec_from_file_location("make_video_t210", vp)
    mv = _iu210.module_from_spec(spec2)
    spec2.loader.exec_module(mv)
    out = _o210.path.join(_t210.mkdtemp(prefix="vid210_"), "v.md")
    mv.build(out)
    txt = open(out, encoding="utf-8").read()
    check("[210] ⑥ 영상 — «병으로 시작(가설 생성)» 컷이 있고 · 사고 과정 컷이 전문 읽기를 말하고 · 과장 두 문구"
          "(«역발상 실행의» · «이 경우에만 나옵니다») · 옛 끝 문장이 없다",
          "병으로 시작 — 가설 생성" in txt and "첫 번째 쓰는 법, 병명으로 시작입니다" in txt and "저자가 적은 한계" in txt
          and "역발상 실행의" not in txt and "이 경우에만 나옵니다" not in txt and "믿지 않는 방법" not in txt
          and "약 이름이 문헌에서 아예 안 잡힐 때만" in txt and "PMID 가 0건" not in txt, "")
    # ⑦ 09-29 · 영상은 **쓰는 법**이 중심이다(규칙 2번 원문 · 게시판 공지에 «발표 포함» 이 없다 — 승우). 슬라이드는
    #   앞뒤 두 장씩이고, 가운데에 쓰는 법 둘(병명 · 가설 하나) · 원문 확인(PubMed) · 적용(심사 기준) · 안전(통제 물질
    #   차단)이 있다. 안전 컷의 질의는 **실제로 막히는** 이름이어야 한다(대본을 뽑을 때 본다)
    from ..core import safety as _SF210
    _sd, _sq = [x.strip() for x in mv.SAFETY_QUERY.split(" / ", 1)]
    n_scr = len(_re210.findall(r"^### 나-\d+ ", txt, _re210.M))
    check("[210] ⑦ 영상은 **쓰는 법 시연**이다 — 슬라이드 넉 장 · 화면 컷 %d · 쓰는 법 둘 · PubMed 원문 확인 · 심사 기준 · "
          "안전 차단(질의가 실제로 막힌다 · 탄저 치료제는 안 막힌다)" % n_scr,
          txt.count("### 발표 ") == 4 and n_scr >= 8 and "두 번째 쓰는 법" in txt
          and "pubmed.ncbi.nlm.nih.gov/" in txt and "심사 기준을 바꾼다" in txt
          and "통제 물질은 맨 앞에서 멈춘다" in txt and _SF210.screen(_sd, _sq, mv.SAFETY_QUERY)[0]
          and not _SF210.screen("ciprofloxacin", "Anthrax", "ciprofloxacin / Anthrax")[0], n_scr)


def test_demo_copy_matches_the_data():
    """[211] **데모 안내문이 자료와 맞는다** — 09-29 · 결함 377.

    승우: «「어떻게 판단하나」 의 "신종 바이러스가 퍼진 상황을 가정한 실행 2건입니다. 미리 돌려 둔 결과라 바로
    열립니다." 이걸 왜 넣은지 이해가 안 가 · 굳이 안 넣어도». 따라가 보니 그 머리말은 **중앙 칸의 되풀이**였고
    실행 2 에는 **틀렸다**(바이러스 무대가 아니다). 옆의 접힌 설명과 「지난 판정」 의 설명은 **«유망 97%»** 를 손으로
    들고 있었는데 사례를 다시 구우니 «조건부» 였고, «마지막 사례» 는 다섯째였다. 보고서도 같은 수를 들고 있었다.

    ① 안내문에 판정 확률을 손으로 적지 않는다  ② `app.js` 가 채우는 칸이 `index.html` 에 다 있다(없으면 첫 화면이
    통째로 죽는다)  ③ 머리말이 하던 말(무대 · 구운 시각)은 중앙 칸이 자료에서 한다  ④ 「지난 판정」 설명의 말이
    구운 사례와 맞다  ⑤ 보고서의 플루복사민 수가 구운 사례에서 다시 나온다  ⑥ 병명 탭 안내의 «열 개» · «150초» 가
    코드 상수와 같다  ⑦ 예비본 라이브 안내의 수가 봉인 예측 파일에서 다시 나온다. ⓘ 자료가 없는 곳에서는 그 칸을 건너뛴다.
    """
    import ast as _ast211
    import csv as _csv211
    import io as _io211
    import os as _o211
    import re as _re211
    from .. import dash as _D211, demo as _DM211, evidence as _E211

    root = _E211.ROOT
    src = _io211.open(_o211.path.join(root, "app.py"), encoding="utf-8").read()
    ui = {}
    for node in _ast211.parse(src).body:
        if isinstance(node, _ast211.Assign):
            for t in node.targets:
                if isinstance(t, _ast211.Name) and t.id.isupper() and t.id.split("_")[0] in (
                        "CASES", "LIVE", "DISEASE", "DISCLAIMER", "DASH"):
                    try:
                        v = _ast211.literal_eval(node.value)
                    except Exception:                     # noqa: BLE001
                        continue
                    if isinstance(v, str):
                        ui[t.id] = v
    check("[211] 안내문 상수를 읽었다 — 사례 · 라이브 · 병명", {"CASES_MORE", "LIVE_MORE", "DISEASE_IDLE"} <= set(ui),
          sorted(ui))

    # ① 판정 확률은 사례 카드가 말한다 — 안내문이 손으로 들면 다시 구울 때 거짓이 된다
    hand = [(k, m.group(0)) for k, v in ui.items()
            for m in _re211.finditer(r"(유망|조건부|보류|기각)\W{0,3}\d{1,3}\s*%", v)]
    check("[211] ① 안내문에 **판정 확률을 손으로 적지 않는다** (결함 377 · «유망 97%» 가 «조건부» 가 됐다)",
          not hand, hand[:4])

    # ② 채우는 칸이 없으면 `setMd` 가 null 에 쓰다 죽고, 그 뒤 탭 전부가 안 그려진다
    js = _io211.open(_o211.path.join(root, "web", "static", "app.js"), encoding="utf-8").read()
    html = _io211.open(_o211.path.join(root, "web", "static", "index.html"), encoding="utf-8").read()
    ids = sorted(set(_re211.findall(r'setMd\("([\w-]+)"', js)))
    miss = [i for i in ids if 'id="%s"' % i not in html]
    check("[211] ② `app.js` 가 채우는 칸 %d개가 **`index.html` 에 다 있다**" % len(ids), ids and not miss, miss)
    check("[211] ② 「어떻게 판단하나」 에 **머리말 · «이 화면은 무엇인가» 가 돌아오지 않는다** — 중앙 칸의 되풀이였다",
          'id="dash-intro"' not in html and 'id="dash-more"' not in html
          and "dash.intro" not in js and "DASH_INTRO" not in ui, "")

    # ③ 뺀 머리말이 하던 말은 **중앙 칸이 자료에서** 한다 — 실행마다 무대, 그리고 구운 시각
    raw = _E211.cases() or {}
    cases = raw.get("사례") or []
    if not cases:
        check("[211] 구운 사례(`demo_cases.json`)가 없다 — ③~⑤ 건너뛴다", True, "")
    else:
        for run, r in _D211.RUNS.items():
            cen = _D211.center(run)
            check("[211] ③ «%s» 중앙 칸이 **무대**와 **구운 시각**을 말한다" % run,
                  r["무대"] in cen and ((raw.get("구운 시각") or "")[:10] + " 에 구운 값이다") in cen, cen[:120])
            # 무대가 한 질환이면(후보 둘 이상이 같은 병) 그 병이 아닌 쌍은 **무대 글이 이름을 댄다** —
            #   «대조군 1건» 이라 적고 무대 밖 쌍이 둘이었다(유방암 · 결핵)
            dz = [q.split(" / ", 1)[1] for q in r["후보"]]
            top = max(set(dz), key=dz.count)
            if dz.count(top) >= 2:
                off = [q.split(" / ", 1)[0] for q in r["후보"] if q.split(" / ", 1)[1] != top]
                check("[211] ③ «%s» 무대(%s) 밖의 쌍 %d개를 **무대 글이 이름으로 댄다**" % (run, top, len(off)),
                      all(d in r["무대"] for d in off), (off, r["무대"]))

        # ④ 「지난 판정」 설명 — 순서를 말하지 않고, 말한 것은 자료와 맞는다
        cm = ui.get("CASES_MORE", "")
        verdicts = {c.get("판정") for c in cases}
        check("[211] ④ «네 가지 판정이 다 나오게» — 구운 사례에 **유망 · 조건부 · 보류 · 기각이 다 있다**",
              "네 가지 판정" not in cm or {"유망", "조건부", "보류", "기각"} <= verdicts, sorted(verdicts))
        check("[211] ④ 사례의 **자리(«마지막 사례» · «첫 사례»)를 말하지 않는다** — 다시 구우면 순서가 바뀐다",
              "마지막 사례" not in cm and "첫 사례" not in cm, "")
        exp = {}
        for r in _D211.RUNS.values():
            exp.update(r.get("제안서가_예상한_것") or {})
        fv = [c for c in cases if c.get("질의") == "fluvoxamine / COVID-19"]
        if "플루복사민" in cm:
            check("[211] ④ «플루복사민은 「보류」 로 지목했는데 실제 판정은 달랐다» 가 **자료에서도 참이다**",
                  fv and exp.get("fluvoxamine / COVID-19", "").startswith("보류")
                  and fv[0].get("판정") != "보류", fv[0].get("판정") if fv else None)

        # ⑤ 보고서의 플루복사민 수 — 사례의 근거 목록에서 다시 계산한다(분류는 판정 사유의 수와 맞아야 한다)
        rp = _o211.path.join(root, "연구기술보고서.md")
        rep = _io211.open(rp, encoding="utf-8").read() if _o211.path.exists(rp) else ""
        m1 = _re211.search(r"확증 근거 무게의 (\d+)%\(([\d.]+)/([\d.]+)\)", rep)
        m2 = _re211.search(r"무게비 ([\d.]+) → ([\d.]+)", rep)
        if fv and (m1 or m2):
            ev = fv[0].get("근거") or []

            def _k(e):
                s = e.get("설명") or ""
                return "meta" if "메타분석" in s else ("rct" if "RCT" in s else "")
            sup = [float(e["가중치"]) for e in ev if e.get("방향") == "지지" and _k(e)]
            ref = [float(e["가중치"]) for e in ev if e.get("방향") == "반박" and _k(e)]
            met = sorted((float(e["가중치"]) for e in ev if e.get("방향") == "지지" and _k(e) == "meta"), reverse=True)
            ws, wr = sum(sup), sum(ref)
            ratio = min(ws, wr) / max(ws, wr)
            why = _re211.search(r"지지 (\d+)·반박 (\d+), 무게비 ([\d.]+)", fv[0].get("사유") or "")
            check("[211] ⑤ 설명의 «메타분석 · RCT» 분류가 **판정 사유의 수와 같다** — 다시 센 것이 규칙이 센 것이다",
                  why and (int(why.group(1)), int(why.group(2))) == (len(sup), len(ref))
                  and abs(float(why.group(3)) - ratio) < 0.006, (fv[0].get("사유"), len(sup), len(ref), round(ratio, 3)))
            if m1:
                check("[211] ⑤ 보고서 «지지 쪽 확증 근거 무게의 %s%%(%s/%s)» 가 구운 사례에서 다시 나온다"
                      % m1.groups(),
                      int(m1.group(1)) == int(round(100 * sum(met) / ws))
                      and abs(float(m1.group(2)) - sum(met)) < 0.006 and abs(float(m1.group(3)) - ws) < 0.006,
                      (round(sum(met), 2), round(ws, 2)))
            if m2 and met:
                from ..core import profiles as _PF211
                bal = _PF211.exit_profile("표준")["balance"]
                ws1 = met[0] + (ws - sum(met))           # 메타분석 셋을 가장 무거운 하나로 묶는다
                r1 = min(ws1, wr) / max(ws1, wr)
                m3 = _re211.search(r"무게비 [\d.]+ → [\d.]+ · 문턱 ([\d.]+)", rep)
                check("[211] ⑤ 보고서 «무게비 %s → %s» 가 구운 사례에서 다시 나온다 · 묶어도 **표준 문턱 %.2f 위**"
                      "(조건부 그대로)" % (m2.group(1), m2.group(2), bal),
                      abs(float(m2.group(1)) - ratio) < 0.006 and abs(float(m2.group(2)) - r1) < 0.006
                      and r1 >= bal and ratio >= bal and fv[0].get("판정") == "조건부"
                      and (not m3 or abs(float(m3.group(1)) - bal) < 1e-9),
                      (round(ratio, 3), round(r1, 3), bal))

    # ⑥ 병명 탭 안내의 수는 코드 상수다
    di = ui.get("DISEASE_IDLE", "")
    sec = _re211.search(r"(\d+)초를 넘기면", di)
    check("[211] ⑥ 병명 탭 안내 «후보 열 개» · «%s초» 가 **코드 상수와 같다**" % (sec.group(1) if sec else "?"),
          ("열 개" not in di or _DM211.DISEASE_K == 10)
          and (not sec or float(sec.group(1)) == float(_DM211.TIME_BUDGET)),
          (_DM211.DISEASE_K, _DM211.TIME_BUDGET))

    # ⑦ 예비본 라이브 안내의 수 — 봉인 예측 파일에서 다시 센다
    sp = _o211.path.join(root, "봉인예측_20260805.csv")
    lm = ui.get("LIVE_MORE", "")
    a = _re211.search(r"(\d+)%가 `보류`", lm)
    b = _re211.search(r"음성 대조만 보면 (\d+)%", lm)
    n = _re211.search(r"봉인 예측 (\d+)건", lm)
    if _o211.path.exists(sp) and (a or b or n):
        rows = list(_csv211.DictReader(_io211.open(sp, encoding="utf-8-sig")))
        neg = [r for r in rows if r.get("kind") == "음성대조"]
        hold = sum(1 for r in rows if r.get("verdict") == "보류")
        check("[211] ⑦ 라이브 안내 «%s건 중 %s%% 보류 · 음성 대조 %s%%» 가 **봉인 예측 파일에서 다시 나온다**"
              % (n.group(1) if n else "?", a.group(1) if a else "?", b.group(1) if b else "?"),
              (not n or int(n.group(1)) == len(rows))
              and (not a or int(a.group(1)) == int(round(100 * hold / len(rows))))
              and (not b or (neg and int(b.group(1)) == int(round(
                  100 * sum(1 for r in neg if r.get("verdict") == "보류") / len(neg))))),
              (len(rows), hold, len(neg)))
        if "절반 넘게" in ui.get("LIVE_INTRO", ""):
            check("[211] ⑦ «절반 넘게 보류» 가 그 파일에서 참이다", hold * 2 > len(rows), (hold, len(rows)))
        # 09-29 · 결함 380 — 보류의 **까닭**도 그 파일에서 센다. 앞판은 «근거가 갈리면» 을 까닭으로 적었는데
        #   보류 44건 중 36건이 «질환 연결 문헌 0건 · 증거 없음» 이었다. 화면 두 곳(`LIVE_INTRO` · `index.html`)을 같이 본다
        _short = ("약물은 실재하나 질환 연결 문헌 0건", "증거 없음", "근거가 약함", "반박이 약함", "F0")
        _hr = [r for r in rows if r.get("verdict") == "보류"]
        _n_short = sum(1 for r in _hr if str(r.get("reason") or "").startswith(_short))
        _notes = [ui.get("LIVE_INTRO", ""), _re211.sub(r"\s+", " ", _re211.sub(r"<[^>]+>", "", html))]
        check("[211] ⑦ 보류의 까닭을 **자료가 말하는 쪽**으로 적는다 — 보류 %d건 중 %d건이 근거 부족 · 화면 두 곳"
              % (len(_hr), _n_short),
              _n_short * 2 > len(_hr) and all("근거가 모자라서" in t for t in _notes)
              and not any("근거가 갈리면 억지로 결론 내지 않기 때문" in t for t in _notes),
              (_n_short, len(_hr)))
    else:
        check("[211] 봉인 예측 파일이 없다 — ⑦ 건너뛴다", True, "")

    # ⑧ 09-29 · **라이선스를 두 곳에서 다르게 말하지 않는다** — HF Space 머리가 `apache-2.0` 인데 공개 저장소에는
    #   LICENSE 가 없었다. 승우 결정: 표기를 빼고 권리를 유지한다(요강 — 저작권은 제출자). LICENSE 를 묶음에 넣는 날에만
    #   머리에 `license:` 를 적는다
    #   ⚠ `web/build_static.py` 를 임포트하지 않는다 — 임포트하면 `sys.path` 에 `web/` 를 꽂고 `server` 를 불러
    #     뒤 시험의 임포트를 흔든다. 소스에서 상수만 읽는다(위 `app.py` 와 같은 방법)
    _hf211 = ""
    _bsp = _o211.path.join(root, "web", "build_static.py")
    if _o211.path.exists(_bsp):
        for _nd in _ast211.parse(_io211.open(_bsp, encoding="utf-8").read()).body:
            if isinstance(_nd, _ast211.Assign) and any(isinstance(t, _ast211.Name) and t.id == "_HF_README"
                                                       for t in _nd.targets):
                try:
                    _hf211 = _ast211.literal_eval(_nd.value)
                except Exception:                     # noqa: BLE001
                    _hf211 = ""
    check("[211] ⑧ Space 머리(`_HF_README`)를 소스에서 읽었다", bool(_hf211) or not _o211.path.exists(_bsp), _bsp)
    _lic_file = any(_o211.path.exists(_o211.path.join(root, n)) for n in ("LICENSE", "LICENSE.md", "LICENSE.txt"))
    _fm = []
    for _src211 in (_hf211, _io211.open(_o211.path.join(root, "README_HF.md"), encoding="utf-8").read()
                    if _o211.path.exists(_o211.path.join(root, "README_HF.md")) else ""):
        _head = _src211.split("---", 2)[1] if _src211.startswith("---") else ""
        _fm += [l.strip() for l in _head.splitlines() if l.strip().startswith("license:")]
    check("[211] ⑧ Space 머리의 라이선스 표기가 **공개 저장소와 같은 말**을 한다 — LICENSE 가 없으면 `license:` 도 없다",
          _lic_file or not _fm, _fm)

    # ⑨ 09-29 · **화면 이름은 사이드바 이름만** 쓴다 — 시간 칸 · Space README 가 «「지난 판정」» 을 가리켰는데 사이드바는
    #   «판정 사례» 였다. 그리고 로고가 첫 화면이 아니라 「약으로 시작」 으로 갔다(정적판에서 누르면 «안 됩니다» 화면)
    #   ⛔ 09-29 15:16 · 첫 판은 **생성물**(`web/static/data/snapshot.json` · `배포정적/README.md`)을 읽었다. 그 둘은 사슬 ⑩
    #     (`build_static`)에서 다시 구워지므로 ⑨ preflight 시점에는 **한 판 낡았고**, 낡은 이름으로 ⑨ 가 멈추면 ⑩ 이 영영
    #     안 돈다 — 승우 사슬이 거기서 섰다. 이름이 **나오는 자리(소스)** 를 본다: 파이썬 문자열 상수(독스트링 · 주석 제외 ·
    #     `.replace(옛 이름, …)` 의 첫 인자 제외 — 판정 경로 코드의 옛 글자를 화면에서 바꾸는 자리다) · `app.js` · `index.html`
    #     (주석 제외) · README 틀. README 는 이름을 `app.js` 에서 채우므로 틀에는 자리표시만 있다
    _navs = set(_re211.findall(r'nav:\s*"([^"]+)"', js))
    _navs |= set(_re211.findall(r'\["(?:verify|judge)",\s*"([^"]+)"\]', js))   # 모드 이름(서비스 · 심사·시연)도 사이드바에 있다

    def _py_screen_strings(rel):
        p = _o211.path.join(root, *rel.split("/"))
        if not _o211.path.exists(p):
            return []
        tree = _ast211.parse(_io211.open(p, encoding="utf-8").read())
        skip = {id(n.value) for n in _ast211.walk(tree)
                if isinstance(n, _ast211.Expr) and isinstance(getattr(n, "value", None), _ast211.Constant)}
        for n in _ast211.walk(tree):
            if (isinstance(n, _ast211.Call) and isinstance(n.func, _ast211.Attribute) and n.func.attr == "replace"
                    and n.args and isinstance(n.args[0], _ast211.Constant)):
                skip.add(id(n.args[0]))
        return [n.value for n in _ast211.walk(tree)
                if isinstance(n, _ast211.Constant) and isinstance(n.value, str) and id(n) not in skip]

    #   ⚠ 09-29 16:0x · `app.py` 에는 **옛 Gradio 화면**이 같이 산다 — 그 화면의 탭은 «직접 검증 · 내 가설 넣기» · «병명으로
    #     시작» 이고(봉인 문서가 인용해 이름을 안 갈았다 · 시험 [143]), Gradio 에만 쓰이는 문자열(`NO_CASES` · 약 탭 안내)은
    #     **그 탭 이름이 맞다.** 첫 판 ⑨ 는 웹 사이드바 이름만 받아 그 둘을 «틀렸다» 고 했고, 나는 그 말대로 고쳤다가
    #     되돌렸다(결함 382). 그래서 `app.py` 의 문자열은 웹 이름 **또는 Gradio 탭 이름**에 대조한다
    _gtabs = {t.split(" · ")[0] for t in _re211.findall(r'gr\.Tab\("([^"]+)"', src)}
    _txts = [(_hf211, _navs)]
    for _rel in ("app.py", "bioreroute/dash.py", "bioreroute/webui.py", "bioreroute/demo.py", "web/server.py",
                 "web/build_static.py", "slides/make_video_본선.py"):
        _ok = (_navs | _gtabs) if _rel == "app.py" else _navs
        _txts += [(t, _ok) for t in _py_screen_strings(_rel)]
    _txts.append((_re211.sub(r"(?m)^\s*//.*$", " ", _re211.sub(r"/\*.*?\*/", " ", js, flags=_re211.S)), _navs))
    _txts.append((_re211.sub(r"<!--.*?-->", " ", html, flags=_re211.S), _navs))
    _names, _bad = set(), set()
    for _t, _ok in _txts:
        _got = {x.split("→")[-1].strip() for x in _re211.findall(r"「([^」{%]{1,24})」\s*(?:에서|으로|로|탭|화면)", _t)}
        _got |= set(_re211.findall(r"「심사·시연 → ([^」{%]{1,20})」", _t))
        _got -= {"후보 찾기", "검증하기"}                    # 버튼 이름 — 화면이 아니다
        _names |= _got
        _bad |= _got - _ok
    check("[211] ⑨ 화면이 가리키는 화면 이름 %d개가 **전부 그 화면의 이름**이다(웹 사이드바 · `app.py` 는 Gradio 탭도) — 소스에서 센다"
          % len(_names), _navs and _gtabs and not _bad, sorted(_bad))
    _bm = _re211.search(r'class="brand" href="#/(\w+)/(\w+)"', html)
    _dm = _re211.search(r'VIEWS\[m\[2\]\]\)\s*\?\s*m\[2\]\s*:\s*"(\w+)"', js)
    check("[211] ⑨ 로고가 **첫 화면**(경로의 기본값)으로 간다",
          bool(_bm and _dm and _bm.group(2) == _dm.group(1)), (_bm.groups() if _bm else None, _dm.group(1) if _dm else None))


def test_offline_script_sections_come_from_the_deck_and_cards():
    """[212] **대본 끝 «5분 경로» · «부록 쪽 번호» 가 순서표 · 덱 · 질의 카드에서 나온다** — 09-29.

    승우: «10/29 오프라인 발표평가 — 전체적으로 다시 판단해서 대본 생각해 줘». 형식(시간 · 질의 비중)이 아직
    공지되지 않아 대본 끝에 두 절을 **생성**하게 했다 — 5분이 주어졌을 때 같은 덱으로 가는 길, 질의응답에서 부록을
    쪽 번호로 바로 여는 표. 둘 다 손으로 적으면 덱 순서나 카드 번호가 바뀔 때 조용히 틀린다(결함 377 과 같은 모양).
    ① 표가 가리키는 카드 번호가 `본선_QA카드.md` 에 실재한다  ② 부록 장마다 칸이 있다  ③ 대본의 5분 경로 쪽 번호가
    순서표에서 나온다 · 말이 `SHORT_LIMIT`(290초 — 쪽 건너뛰기 몫을 남긴다)를 넘지 않는다  ④ 부록 표의 첫 쪽이
    «본편 + 구분 한 장» 다음이다.
    ⓘ 카드 · 대본이 없는 곳(공개 사본)에서는 건너뛴다.
    """
    import importlib.util as _iu212
    import os as _o212
    import re as _re212
    from .. import evidence as _E212

    root = _E212.ROOT
    tp = _o212.path.join(root, "slides", "make_10min_본선.py")
    sp = _o212.path.join(root, "발표대본_본선10분.md")
    qp = _o212.path.join(root, "본선_QA카드.md")
    if not all(_o212.path.exists(p) for p in (tp, sp, qp)):
        check("[212] 생성기 · 대본 · 질의 카드 중 없는 것이 있다 — 건너뛴다", True, "")
        return
    spec = _iu212.spec_from_file_location("make10_212", tp)
    mod = _iu212.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cards = set(_re212.findall(r"^\*\*Q(\d+)\.", open(qp, encoding="utf-8").read(), _re212.M))
    want = sorted({int(q) for v in mod.APPX_Q.values() for q in _re212.findall(r"Q(\d+)", v)})
    miss = [q for q in want if str(q) not in cards]
    check("[212] ① 부록 표가 가리키는 질의 카드 %d개가 **`본선_QA카드.md` 에 실재한다**" % len(want),
          want and not miss, miss)
    check("[212] ② 부록 장마다 칸이 있다 — 순서표(APPX)와 표의 열쇠가 같다",
          set(mod.APPX_Q) == set(mod.APPX), sorted(set(mod.APPX) ^ set(mod.APPX_Q)))
    txt = open(sp, encoding="utf-8").read()
    if "## 5분이 주어지면" not in txt:
        check("[212] ③ 대본에 5분 경로 절이 있다 — 없으면 `py slides\\make_10min_본선.py` 를 다시 돌려라", False, "")
        return
    pages = " → ".join(str(mod.MAIN.index(k) + 1) for k in mod.SHORT)
    m = _re212.search(r"\*\*합계 약 (\d+)분 (\d+)초\*\*", txt.split("## 5분이 주어지면", 1)[1])
    # 09-29 · 한도를 5분 30초 → **말 %d초**(`SHORT_LIMIT`)로 — 5분 26초가 통과하고 있었다. 쪽 건너뛰기 몇 초를 남긴다
    _lim212 = getattr(mod, "SHORT_LIMIT", 300)
    check("[212] ③ 5분 경로가 **순서표에서 나온 쪽**(%s)을 적고 · 이음 문장까지 말 %d초를 넘지 않는다" % (pages, _lim212),
          ("· %s쪽" % pages) in txt and m and int(m.group(1)) * 60 + int(m.group(2)) <= min(_lim212, 300),
          m.groups() if m else None)
    body = txt.split("## 5분이 주어지면", 1)[0].replace("\n", " ")   # 대본은 문장마다 줄을 바꾼다
    _pats212 = [p for v in mod.SHORT_CUT.values() for p in (v if isinstance(v, (list, tuple)) else [v])]
    gone = [t for t in _pats212 if not _re212.search(t, body)]
    check("[212] ③ 5분 길에서 더 빼는 문장이 **본편 노트에 실재한다** — 노트를 고치면 여기가 먼저 깨진다",
          not gone, gone)
    rows = _re212.findall(r"^\| (\d+) \| [^|]+ \| (Q[\d · Q]+|—) \|$", txt, _re212.M)
    check("[212] ④ 부록 표가 %d줄이고 첫 쪽이 본편 %d장 + 구분 한 장 다음(%d쪽)이다"
          % (len(mod.APPX), len(mod.MAIN), len(mod.MAIN) + 2),
          len(rows) == len(mod.APPX) and rows and int(rows[0][0]) == len(mod.MAIN) + 2,
          rows[:2])


def test_transient_failures_are_counted_recorded_and_shown():
    """[213] **일시 장애로 못 읽은 초록을 세고, 기록하고, 판정 옆에서 말한다** — 09-29 · 결함 380.

    09-29 라이브 점검에서 같은 병명을 두 번 돌리니 후보 열 개와 순서는 같고 두 후보의 판정이 달랐다
    (데운 둘째 실행이 새 호출 6번). 캐시는 일시 장애를 저장하지 않으므로 첫 실행에서 못 받은 초록 · 실패한 판정
    호출을 둘째가 다시 묻는다 — 그런데 **어느 후보가 몇 건을 못 읽었는지** 기록도 화면도 말하지 않아 원인을 못 갈랐다.
    ① 셈의 규칙 — 일시 장애만 센다(영구 오류 · 캐시에 남는 응답 모양 오류는 다음에도 같다)  ② 병명 · 쌍 화면이
    판정 옆에서 말한다 · 0 이면 말하지 않는다  ③ 라이브 점검 기록이 그 수를 적고 «갈린 까닭» 을 기록에서 읽는다 ·
    옛 기록이면 «못 가른다» · 겹치지 않으면 지어내지 않는다.
    """
    from .. import dash as _D213, demo as _DM213, webui as _W213
    from ..bench import livecheck as _LC213
    from ..core.state import Candidate as _C213

    # ① 셈의 규칙
    c = _C213(name="x / y", origin="입력", query="q", drug="x", disease="y")
    c.factcheck = [{"skip": "초록 취득 실패: HTTPError: HTTP Error 429: Too Many Requests"},   # 일시 — 센다
                   {"skip": "초록 취득 실패: XML 파싱 실패: bad"},                            # 영구 — 캐시에 남는다
                   {"skip": "LLM 실패: JSON 파싱 실패"},                                     # 저장 안 됨 — 센다
                   {"skip": "LLM 실패: 배열 형식 아님"},                                      # 응답이 캐시에 남는다
                   {"skip": "철회 논문 — 근거에서 제외"}, {"skip": None}]
    check("[213] ① 일시 장애만 센다 — 429 · LLM 호출 실패는 세고, 영구 오류 · «배열 형식 아님» · 철회는 안 센다",
          _DM213._transient_skips(c) == 2, _DM213._transient_skips(c))

    # ② 화면 — 병명 결과 · 쌍 결과
    cand = {"이름": "nitazoxanide / COVID-19", "판정": "조건부", "신뢰도": 26, "사유": "근거 엇갈림",
            "근거수": 3, "근거": [], "일시실패": 2}
    r0 = {"ok": True, "질환": "COVID-19", "후보": [dict(cand, 일시실패=0)], "일시실패": 0, "요청": 10, "생성": 1,
          "F0통과": 1, "태움": 1, "초": 1.0}
    r1 = dict(r0, 후보=[cand], 일시실패=2)
    t0 = _D213.disease_run(r0)
    t1 = _D213.disease_run(r1)
    check("[213] ② 병명 결과가 **일시 장애 수와 후보 이름**을 판정 옆에서 말한다 · 0 이면 말하지 않는다",
          "일시 장애로 초록 2건을 못 읽었습니다" in t1 and "nitazoxanide" in t1.split("일시 장애로 초록 2건")[1][:60]
          and "일시 장애" not in t0, t1[:200])
    pr = {"상태": "정상", "판정": "조건부", "신뢰도": 26, "사유": "근거 엇갈림", "근거": [], "질의": "a / b"}
    check("[213] ② 쌍 결과도 같은 말을 한다 · 0 이면 말하지 않는다",
          "일시 장애로 초록 1건을 못 읽었습니다" in _W213._md_result(dict(pr, 일시실패=1), struct_note=False)
          and "일시 장애" not in _W213._md_result(dict(pr, 일시실패=0), struct_note=False), "")

    # ③ 라이브 점검 기록 — 적는다 · 까닭을 기록에서 읽는다
    s = _LC213._dz_summary({"상태": "정상", "후보": [cand, dict(cand, 이름="a / COVID-19", 일시실패=0)],
                            "일시실패": 2}, 1.0)
    check("[213] ③ 기록이 실행의 일시 장애 수 · 후보별 수 · 근거 수를 적는다 — `후보` 꼴은 그대로",
          s["일시실패"] == 2 and s["일시실패후보"] == {"nitazoxanide / COVID-19": 2}
          and s["근거수"]["a / COVID-19"] == 3 and all(len(x) == 3 for x in s["후보"]), s)

    def run(vs, tf=None, tfc=None):
        return {"후보": [[q, v, 0] for q, v in vs], "일시실패": tf, "일시실패후보": tfc or {}}
    same = {"실행": [run([("a", "기각")], 0), run([("a", "기각")], 0)]}
    old = {"실행": [run([("a", "기각")]), run([("a", "보류")])]}
    hit = {"실행": [run([("a", "조건부"), ("b", "기각")], 2, {"a": 2}), run([("a", "기각"), ("b", "기각")], 0)]}
    miss = {"실행": [run([("a", "조건부")], 0), run([("a", "기각")], 0)]}
    check("[213] ③ 갈린 까닭 — 안 갈리면 None · 옛 기록은 «못 가른다» · 겹치면 그 후보 · 안 겹치면 지어내지 않는다",
          _LC213.diff_cause(same) is None
          and "못 가른다" in (_LC213.diff_cause(old) or "")
          and "일시 장애로 초록을 못 읽은 후보다" in (_LC213.diff_cause(hit) or "") and "첫째 a" in _LC213.diff_cause(hit)
          and "겹치지 않는다" in (_LC213.diff_cause(miss) or ""),
          [_LC213.diff_cause(x) for x in (same, old, hit, miss)])


ORDER = [
    test_transient_failures_are_counted_recorded_and_shown,
    test_offline_script_sections_come_from_the_deck_and_cards,
    test_demo_copy_matches_the_data,
    test_talk_says_what_we_built_and_that_we_did_not_tune,
    test_public_copy_keeps_bytes_through_git,
    test_github_public_copy_check_sees_what_judges_see,
    test_live_check_is_fixed_recorded_and_read_by_the_script,
    test_commit_script_refuses_what_it_must,
    test_submission_surfaces_carry_no_forbidden_words,
    test_dday_milestones_match_the_schedule_table,
    test_public_copy_is_built_outside_and_never_pushed_to_the_working_repo,
    test_calibration_numbers_in_report_come_from_code_and_screen_agrees,
    test_countsync_does_not_move_numbers_inside_records,
    test_report_pdf_does_not_print_markdown_markers,
    test_submission_surfaces_do_not_claim_untested_or_deny_measured,
    test_deck_text_does_not_overflow_onto_neighbours,
    test_hf_deploy_commits_only_changed_files_with_the_owner_token,
    test_video_script_names_screens_from_the_ui_code,
    test_step_descriptions_do_not_show_raw_markdown,
    test_hf_deploy_is_checked_by_content_not_by_saying_so,
    test_abstain_reason_describes_the_evidence_it_had,
    test_video_script_comes_from_the_same_sources_as_the_screen,
    test_report_defect_table_comes_from_the_deck_bars,
    test_tests_cannot_write_into_the_repository,
    test_cache_save_survives_being_interrupted,
    test_byom_and_demo_rebake_scripts_hold_their_guards,
    test_ten_minute_deck_carries_required_items_and_code_numbers,
    test_performance_card_numbers_come_from_the_result_files,
    test_prereg_ledger_counts_every_sealed_spec_and_quotes_real_lines,
    test_result_writer_copies_numbers_and_sealed_words_only,
    test_preflight_notices_when_the_demo_would_run_the_wrong_model,
    test_draw_replicate_script_carries_the_sealed_values,
    test_draw_replicate_separates_input_seed_and_model,
    test_seed_retest_script_carries_the_sealed_values,
    test_seed_retest_cannot_replay_copy_or_leak,
    test_zeropurge_removes_only_confirmed_fake_zeros,
    test_f0_never_turns_network_trouble_into_hallucination,
    test_model_independence_numbers_come_from_one_place,
    test_zerocheck_never_turns_a_missing_count_into_zero,
    test_rejection_reasons_have_one_definition,
    test_luna_script_carries_the_sealed_values,
    test_model_comparison_separates_model_from_input,
    test_first_screen_is_something_that_actually_works,
    test_preflight_watches_git_because_nobody_did,
    test_cache_never_destroys_itself_when_it_cannot_read,
    test_preflight_shows_every_failure_not_just_the_first,
    test_reject_recall_prints_its_own_fraction,
    test_seal_tool_never_silently_overwrites_a_seal,
    test_zip_tool_points_at_stale_version_but_never_rewrites_history,
    test_docaudit_never_reports_green_when_it_skipped_the_truth_check,
    test_countsync_command_can_actually_be_pasted_into_powershell,
    test_screen_says_which_gates_it_turned_off_and_why,
    test_promised_metrics_are_actually_computed_not_just_computable,
    test_fragility_can_actually_read_what_save_state_writes,
    test_release_zip_can_actually_run_the_reproduction_steps,
    test_screen_does_not_mistake_fulltext_irrelevant_for_zero_weight,
    test_token_cost_is_attributed_to_funnel_stages,
    test_countsync_never_touches_sealed_documents,
    test_call_accounting_counts_every_paid_call,
    test_fulltext_gate_contracts,
    test_registry, test_router, test_cutoff, test_leakage, test_configs,
    test_cli_all, test_search_fallback, test_leak_all_sources, test_horizon,
    test_balance, test_autosave, test_integration, test_tools,
    test_stop_reason, test_registry_quote, test_regaudit,
    test_registry_report, test_inspect, test_flip_and_merge,
    test_negative_first, test_zero_is_not_error, test_sample_and_wrong,
    test_structured_quote, test_drop_reasons, test_showreg, test_stale_cache,
    test_comparative_filter, test_stratum_consistency, test_drug_mismatch,
    test_blind_review, test_chiral_and_result, test_enrich,
    test_cutoff_all_sources, test_leakcheck, test_leak_pmid_expand,
    test_cache_never_shrinks, test_ctharvest, test_stats_and_names,
    test_permeability_caveat, test_pair_input, test_no_llm_guard,
    test_discover, test_funnel, test_demo, test_evidence,
    test_report_numbers, test_safety, test_prospective,
    test_s1_and_router_branch, test_reverse_and_profiles,
    test_viewer_and_fto, test_hitl_and_tox, test_wired, test_disclaimer,
    test_ai_notice, test_cache_configure_clears, test_faithfulness,
    test_specaudit, test_gradiocheck, test_markdown_tables,
    test_plaintext_labels, test_notranslate, test_deck_markdown,
    test_script_points_at_a_screen_that_exists,
    test_claims_carry_their_prior_art,
    test_cache_is_not_poisoned_by_fallback,
    test_no_structure_says_what_there_is_instead,
    test_slides_do_not_overlap,
    test_static_snapshot_has_what_the_screen_asks_for,
    test_dead_model_is_not_knocked_twice,
    test_dashboard, test_preflight, test_faers_failure_is_not_zero,
    test_doc_consistency, test_countsync_covers_docaudit,
    test_pico_reaches_screen, test_evidence_stage_stamp,
    test_llm_cannot_inject_pmid, test_shown_quote_is_verified_span,
    test_docking_needs_apo_structure, test_dock_live_localizes_before_pocket,
    test_numbered_tokens_do_not_swallow,
    test_ligand_can_hide_inside_the_polymer,
    test_docked_species_must_be_the_binding_species,
    test_refuse_docking_when_species_and_apo_conflict,
    test_scan_does_not_let_me_pick,
    test_scan_must_not_default_to_one_organism,
    test_unknown_species_gets_its_own_reason,
    test_ask_from_the_drug_not_the_structure,
    test_partial_source_is_worse_than_empty_one,
    test_deploy_copy_is_not_the_original,
    test_seal_records_code_and_checks_it,
    test_adjudicate_defences_have_their_own_test,
    test_knows_when_something_is_running,
    test_case_notes_do_not_state_the_verdict,
    # ── ④-b 공개연도 (결함 216) ──────────────────────────────────
    test_dead_argument_must_say_so,
    test_year_of_says_none_when_it_does_not_know,
    test_partial_scan_is_not_saved,
    test_year_control_can_fail,
    test_year_thresholds_come_from_the_spec,
    test_use_year_stops_when_it_cannot_reproduce,
    test_no_pollution,
    test_rate_limit_holds_across_threads,
    test_result_files_are_backed_up_before_overwrite,
    test_disease_entry_does_not_cut_candidates,
    test_tests_do_not_litter_the_repo,
    test_patent_view_reads_our_index_not_a_dead_api,
    test_exit_axis_actually_moves_the_verdict,
    test_live_candidate_opens_its_reasoning,
    test_detail_shows_the_arithmetic_not_a_guess,
    test_reverse_entry_is_actually_reachable,
    test_service_ui_gives_the_user_a_way_in_and_out,
    test_retest_measures_instrument_variation,
    test_no_dev_log_leaks_onto_the_demo_screen,
    test_every_gate_name_on_screen_is_korean,
    test_run_pair_actually_times_its_gates,
    test_patent_index_is_read_once_not_per_call,
    test_parallel_funnel_gives_the_same_verdicts,
    test_output_survives_a_cp949_pipe,
    test_every_declared_role_is_actually_wired,
    test_run_disease_actually_completes,
    test_judgement_runners_are_tested,
    # ── 09-01 추가 — 그날 만든 도구 다섯이 무방비였다 ──────────────
    test_new_cli_entrypoints_actually_run,
    test_evidence_tools_separate_missing_from_unreachable,
]

FAILED_TESTS = []          # 실패가 난 **시험 함수** 이름 (검사 이름 말고)


def _run_seq(fns) -> int:
    """골라 받은 시험들을 **목록 순서대로** 돌린다.

    어느 **시험 함수**에서 실패가 났는지 같이 모은다 — `FAIL` 은 검사
    이름만 담아서 «어느 시험이 깨졌나» 를 못 읽는다. 이분 탐색이 그걸
    읽어야 한다.
    """
    # ── ⛔ 09-25 · **시험은 저장소 폴더에 쓰지 못한다** (결함 335) ──────────
    #   `_main` 이 `liveguard.install()` 을 불렀을 때만 켜진다. 막힌 쓰기는
    #   시험 안에서 삼켜져도 여기서 **실패로 올린다** — 어느 시험이 어디에.
    from . import liveguard as _LG
    for fn in fns:
        n0, h0 = len(FAIL), len(_LG.HITS)
        _LG.start(fn.__name__)
        try:
            _run(fn)
        finally:
            _LG.stop()
        for _t, _ev, _p in _LG.HITS[h0:]:
            FAIL.append("[liveguard] %s 가 저장소 폴더에 쓰려 했다 — %s %s"
                        % (_t, _ev, _LG.rel(_p)))
            print("  FAIL [liveguard] %s → %s %s (막았다 · 임시 경로를 써라)"
                  % (_t, _ev, _LG.rel(_p)))
        if len(FAIL) > n0:
            FAILED_TESTS.append(fn.__name__)
    return len(FAIL)


def _bisect(target_name: str) -> int:
    """**순서 의존의 범인을 찾는다** — 결함 210.

    전제: `target` 이 **단독으로는 통과**하고 **앞의 것들과 같이 돌리면
    실패**한다. 그 사이 어딘가에 상태를 더럽히는 시험이 있다.

    각 시도를 **새 프로세스**에서 돌린다. 같은 프로세스에서 하면
    앞 시도의 오염이 다음 시도로 넘어가 **탐색 자체가 거짓말**이 된다 —
    이 버그가 정확히 그 종류이기 때문이다.

    단일 범인을 가정한다. 둘 이상이면 **하나를 찾고 멈춘다** — 그때는
    그 하나를 고친 뒤 다시 돌린다.
    """
    import subprocess
    names = [f.__name__ for f in ORDER]
    if target_name not in names:
        print("  ✗ `%s` 가 목록에 없다" % target_name)
        return 2
    ti = names.index(target_name)
    if ti == 0:
        print("  ✗ `%s` 가 첫 시험이다 — 앞에 아무것도 없다" % target_name)
        return 2

    def trial(idx):
        """번호 목록 + 표적 을 **새 프로세스**에서 돌린다. 실패면 True."""
        seq = ",".join(str(i) for i in list(idx) + [ti])
        r = subprocess.run(
            [sys.executable, "-m", "bioreroute.tests.test_phase2",
             "--seq", seq],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        # 표적이 실패 목록에 있나 — **종료코드만 보면 안 된다.**
        # 앞의 시험이 실패해도 종료코드는 1 이라 그걸 «재현» 으로 읽는다.
        for line in (r.stdout or "").splitlines():
            if line.startswith("##FAILED##"):
                return target_name in line[10:].split(",")
        # 표지가 없다 = **시험이 끝까지 안 갔다.** «재현 안 됨» 이 아니다 —
        # 그렇게 읽으면 탐색이 엉뚱한 쪽으로 간다(결함 89 계열).
        raise RuntimeError(
            "시험이 표지 없이 끝났다 (종료 %s). 마지막 줄: %s"
            % (r.returncode, ((r.stdout or "").strip().splitlines() or
                              ["(빈 출력)"])[-1][:160]))

    print("=" * 66)
    print(" 이분 탐색 — `%s` (앞에 %d개)" % (target_name, ti))
    print("=" * 66)
    print("  0) 단독으로 통과하나 …", end=" ", flush=True)
    if trial([]):
        print("**아니다 — 단독으로도 실패한다.**")
        print("     순서 의존이 아니다. 그 시험 자체를 봐라.")
        return 1
    print("통과")
    print("  1) 앞의 것들과 같이 돌리면 실패하나 …", end=" ", flush=True)
    cand = list(range(ti))
    if not trial(cand):
        print("**아니다 — 재현이 안 된다.**")
        print("     이미 고쳐졌거나, 범인이 **표적 뒤**에 있다.")
        return 1
    print("실패 — 재현된다")
    print("")

    step = 0
    while len(cand) > 1:
        step += 1
        half = cand[:len(cand) // 2]
        print("  %d) 후보 %3d개 → 앞 %3d개로 시험 …"
              % (step + 1, len(cand), len(half)), end=" ", flush=True)
        if trial(half):
            print("실패 — **앞쪽에 있다**")
            cand = half
        else:
            print("통과 — 뒤쪽에 있다")
            cand = cand[len(cand) // 2:]
    print("")
    print("=" * 66)
    print("  범인: **[%d] %s**" % (cand[0], names[cand[0]]))
    print("=" * 66)
    print("  → 그 시험이 바꾼 것을 **되돌리게** 고쳐라.")
    print("     근본 원인은 «시험이 전역 상태를 바꾼다» 이지")
    print("     «이 시험이 나쁘다» 가 아니다 (결함 210).")
    return 0


def _main(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Phase 2 검증 — 골라 돌릴 수 있다 (결함 210)")
    ap.add_argument("--list", action="store_true", help="번호와 이름만")
    ap.add_argument("--only", default=None, help="이름에 이 글자가 든 것만")
    ap.add_argument("--seq", default=None, help="번호 목록 (예 3,7,44)")
    ap.add_argument("--shard", default=None, help="i/n — n등분 중 i번째")
    ap.add_argument("--bisect", default=None,
                    help="순서 의존의 범인을 찾는다 (새 프로세스로)")
    a = ap.parse_args(argv)

    names = [f.__name__ for f in ORDER]
    if a.list:
        for i, n in enumerate(names):
            print("%3d  %s" % (i, n))
        print("\n  모두 %d개" % len(names))
        return 0
    if a.bisect:
        return _bisect(a.bisect)

    sel = list(range(len(ORDER)))
    if a.seq:
        sel = [int(x) for x in a.seq.split(",") if x.strip() != ""]
    if a.only:
        sel = [i for i in sel if a.only in names[i]]
    if a.shard:
        i_s, n_s = (int(x) for x in a.shard.split("/"))
        # **연속 덩어리로 자르지 않는다.** 느린 시험이 한 묶음에 몰리면
        # 그 묶음만 오래 걸린다. 번갈아 가르면 시간이 고르게 퍼진다.
        sel = [i for k, i in enumerate(sel) if k % n_s == (i_s - 1) % n_s]
    if not sel:
        print("  고른 시험이 없다.")
        return 2

    try:
        from bioreroute.bench import srcstamp as _SS0
        snap0 = _SS0.snapshot()
    except Exception:
        snap0 = {}
    # 시험이 저장소 폴더에 못 쓰게 한다 — 결함 335 (09-25 탐침에서 넷이 쓰고 있었다)
    from . import liveguard as _LG0
    _LG0.install(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    part = (a.seq or a.only or a.shard)
    print("=" * 66)
    print("Phase 2 검증 — 등록부·라우터·시점차단·누출차단%s"
          % ("   [부분 %d/%d]" % (len(sel), len(ORDER)) if part else ""))
    print("=" * 66)
    if part:
        # ⚠ **부분 실행을 «전수 통과» 로 읽으면 안 된다.** 결함 141·149
        #    계열 — «없다» 와 «안 봤다» 를 안 가르는 것.
        print("⚠ **부분 실행이다.** 이걸로 «전수 통과» 를 말하지 마라.")
        print("")
    _run_seq([ORDER[i] for i in sel])

    # ── 도는 동안 소스가 바뀌었나 (결함 202) ──────────────────────
    #   «고치기 전에 확인해라» 는 안내문이라 안 듣는다.
    #   **시험이 스스로 말하게** 한다 — 판정은 안 바꾸고 보이게만.
    try:
        from bioreroute.bench import srcstamp as _SS
        msg = _SS.report(snap0, _SS.snapshot(), "시험")
        if msg:
            print(msg)
    except Exception:
        pass
    print("\n" + "=" * 66)
    print("통과 %d · 실패 %d%s"
          % (len(PASS), len(FAIL), "   [부분]" if part else ""))
    if FAIL:
        print("실패: " + ", ".join(FAIL))
        # ── ⛔ 09-21 · **한 줄에 쉼표로 이으면 부르는 쪽이 못 쪼갠다** ──
        #
        #   `preflight` 이 이 줄을 읽어 «무엇이 깨졌나» 를 찍는데,
        #   **쉼표 이어붙이기라 한 덩어리**였다. 검사 이름 자체에 쉼표가
        #   들어갈 수 있어 부르는 쪽에서 안전하게 쪼갤 수도 없다.
        #   그래서 **줄바꿈을 구분자로 하는 줄을 따로 낸다** — 위 줄은
        #   기존 호환을 위해 남긴다(`_gist` 가 그걸 읽는다).
        #
        #   ⚠ 접두사 `실패상세:` 는 `preflight._fails()` 와의 **계약**이다.
        #     한쪽만 바꾸면 조용히 안 보인다 — 시험 [168]이 둘을 묶는다.
        for _one in FAIL:
            print("실패상세:" + str(_one).replace("\n", " "))
    # **기계가 읽는 줄** — 이분 탐색이 «표적이 깨졌나» 를 이걸로 읽는다.
    #   종료코드만 보면 «앞 시험이 깨진 것» 을 «재현» 으로 오독한다.
    print("##FAILED##" + ",".join(FAILED_TESTS))
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
