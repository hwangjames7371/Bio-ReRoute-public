# -*- coding: utf-8 -*-
"""Phase 1 검증 — API 키 없이 로직을 전부 시험한다.

실제 호출로만 확인하면 실패했을 때 원인이 모델인지 코드인지 구분이 안 된다.
모의 LLM으로 코드를 먼저 고정하고, 그다음 실제 키로 모델 품질을 본다.

실행: python -m bioreroute.tests.test_phase1
"""

import json
import sys
import os
import tempfile


def _tmp(name):
    """시험용 임시 경로.

    **"/tmp"를 하드코딩하면 윈도우에서 깨진다.** 실제로 깨졌다 —
    나는 리눅스에서만 돌려보고 통과했다고 보고했다.
    검증 환경이 실행 환경과 다르면 그 검증은 거짓말이다.
    """
    return os.path.join(tempfile.gettempdir(), name)


from ..agents import factcheck
from ..io import cache, llm, sources

PASS, FAIL = [], []


def check(name, cond, got=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if cond else "FAIL", name, ("  -> %s" % got) if got else ""))


# ═══════════════════════════════════════════════════════════
# 1. 인용문 검증 — 지어낸 근거를 잡아내는가
# ═══════════════════════════════════════════════════════════
def test_quote():
    print("\n[1] 인용문 검증 (에이전트 자신에 대한 반증)")
    abs_ = ("BACKGROUND: We assessed fluvoxamine. RESULTS: Clinical deterioration "
            "occurred in 0 of 80 patients in the fluvoxamine group and in 6 of 72 "
            "patients in the placebo group (absolute difference 8.7%).")

    check("완전일치 통과",
          factcheck.verify_quote("Clinical deterioration occurred in 0 of 80 patients", abs_)["ok"])
    check("공백·대소문자 정규화",
          factcheck.verify_quote("clinical   deterioration  occurred  in 0 of 80 PATIENTS", abs_)["ok"])
    r = factcheck.verify_quote("Fluvoxamine reduced mortality by 45% in all patients", abs_)
    check("지어낸 문장 차단", not r["ok"], r["how"])
    r = factcheck.verify_quote("we assessed", abs_)
    check("너무 짧은 인용 차단", not r["ok"], r["how"])
    r = factcheck.verify_quote("", abs_)
    check("빈 인용 차단", not r["ok"], r["how"])


# ═══════════════════════════════════════════════════════════
# 2. 가중치 표 — 손으로 매긴 기준점을 재현하는가
# ═══════════════════════════════════════════════════════════
def test_weight():
    print("\n[2] 가중치 표 (LLM이 아닌 코드가 숫자를 정한다)")
    w = factcheck.weight_for("rct", "large", True, "high")
    check("대규모 결정적 RCT = 3.0 (W1의 RECOVERY와 일치)", abs(w - 3.0) < 1e-9, w)
    w = factcheck.weight_for("rct", "small", False, "high")
    check("소규모 파일럿 RCT = 1.2 (W1의 Lenze와 일치)", abs(w - 1.2) < 1e-9, w)

    w_rct = factcheck.weight_for("rct", "large", False, "high")
    w_obs = factcheck.weight_for("observational", "large", False, "high")
    w_vit = factcheck.weight_for("in_vitro", "unknown", False, "high")
    check("RCT > 관찰연구 > 시험관 (설계 위계 보존)", w_rct > w_obs > w_vit,
          "%.2f > %.2f > %.2f" % (w_rct, w_obs, w_vit))
    check("결정성 배수는 확증 설계에만",
          factcheck.weight_for("observational", "large", True, "high") ==
          factcheck.weight_for("observational", "large", False, "high"))
    check("저신뢰 판정은 감쇠",
          factcheck.weight_for("rct", "large", False, "low") <
          factcheck.weight_for("rct", "large", False, "high"))


# ═══════════════════════════════════════════════════════════
# 3. efetch XML 파싱 — 철회·연구유형·구조화 초록
# ═══════════════════════════════════════════════════════════
XML = """<?xml version="1.0"?><PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>32205204</PMID><Article>
<Journal><ISOAbbreviation>Int J Antimicrob Agents</ISOAbbreviation>
<JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>
<ArticleTitle>Hydroxychloroquine and azithromycin as a treatment of COVID-19</ArticleTitle>
<Abstract><AbstractText Label="BACKGROUND">Chloroquine was reported.</AbstractText>
<AbstractText Label="RESULTS">Hydroxychloroquine was significantly associated with viral load reduction.</AbstractText></Abstract>
<PublicationTypeList><PublicationType>Journal Article</PublicationType>
<PublicationType>Retracted Publication</PublicationType></PublicationTypeList>
</Article></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>33031652</PMID><Article>
<Journal><ISOAbbreviation>N Engl J Med</ISOAbbreviation>
<JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>
<ArticleTitle>Effect of Hydroxychloroquine in Hospitalized Patients with Covid-19</ArticleTitle>
<Abstract><AbstractText Label="RESULTS">Death within 28 days occurred in 421 of 1561 patients in the hydroxychloroquine group and in 790 of 3155 in the usual-care group.</AbstractText></Abstract>
<PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList>
</Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


def test_xml():
    print("\n[3] efetch XML 파싱")
    cache.configure(_tmp("_t1.json"))
    cache._STORE.clear()
    sources._get_xml = lambda url: XML            # 네트워크 차단
    recs = sources.pubmed_abstracts(["32205204", "33031652"])

    r1, r2 = recs["32205204"], recs["33031652"]
    check("철회 논문 색인 인식", "Retracted Publication" in r1["pubtypes"])
    check("RCT 유형 자동 인식", r2["study_type"] == "rct", r2["study_type"])
    check("철회 논문은 유형 미부여", r1["study_type"] is None, r1["study_type"])
    check("구조화 초록 Label 보존", r2["abstract"].startswith("RESULTS:"))
    check("연도·저널 추출", r2["year"] == 2020 and r2["journal"] == "N Engl J Med",
          "%s / %s" % (r2["year"], r2["journal"]))
    return recs


# ═══════════════════════════════════════════════════════════
# 4. 팩트체커 통합 — 모의 LLM
# ═══════════════════════════════════════════════════════════
def mock_llm(responses):
    """prompt에 들어간 PMID로 응답을 고른다."""
    def _complete(prompt, system="", model=None, as_json=False, purpose=""):
        for pmid, data in responses.items():
            if "PMID %s" % pmid in prompt:
                return {"ok": True, "text": json.dumps(data), "data": data,
                        "error": None, "provenance": llm.provenance(prompt),
                        "cached": False}
        return {"ok": False, "text": "", "data": None, "error": "mock 미정의",
                "provenance": llm.provenance(prompt), "cached": False}
    return _complete


def test_classify(recs):
    print("\n[4] 팩트체커 통합")
    llm.available = lambda: True
    llm.complete = mock_llm({
        # 철회 논문 — LLM까지 가면 안 된다
        "32205204": {"direction": "support", "study_type": "trial", "size": "small",
                     "decisive": False, "quote": "Hydroxychloroquine was significantly "
                     "associated with viral load reduction", "confidence": "high"},
        # RECOVERY — 진짜 반박. study_type을 일부러 틀리게 준다.
        "33031652": {"direction": "refute", "study_type": "observational",
                     "size": "large", "decisive": True,
                     "quote": "Death within 28 days occurred in 421 of 1561 patients "
                              "in the hydroxychloroquine group",
                     "population": "입원 환자", "dose": "", "timing": "입원 후",
                     "confidence": "high"},
    })
    factcheck.llm = llm

    r1 = factcheck.classify("hydroxychloroquine", "COVID-19", recs["32205204"])
    check("철회 논문 근거 제외", r1["retracted"] and not r1["kept"] and r1["weight"] == 0.0,
          r1["skip"])

    r2 = factcheck.classify("hydroxychloroquine", "COVID-19", recs["33031652"])
    check("반박 근거 채택", r2["kept"] and r2["direction"] == "refute", r2.get("skip"))
    check("PubMed 색인이 LLM 오분류를 이김",
          r2["study_type"] == "rct" and r2["study_type_src"] == "pubmed",
          "LLM=observational -> 채택=%s" % r2["study_type"])
    check("유형 불일치 기록", r2.get("type_conflict") is True)
    check("가중치 3.0 (대규모 결정적 RCT)", abs(r2["weight"] - 3.0) < 1e-9, r2["weight"])
    check("PICO 반증 범위 포착", r2["pico"]["population"] == "입원 환자", r2["pico"])
    check("근거명에 출처 포함", "N Engl J Med" in factcheck.tag_for(r2),
          factcheck.tag_for(r2))

    # 지어낸 인용 → 강등
    llm.complete = mock_llm({"33031652": {
        "direction": "refute", "study_type": "rct", "size": "large", "decisive": True,
        "quote": "Hydroxychloroquine increased mortality threefold in every subgroup",
        "confidence": "high"}})
    r3 = factcheck.classify("hydroxychloroquine", "COVID-19", recs["33031652"])
    check("지어낸 인용 -> 무관 강등·가중치 0",
          r3["direction"] == "neutral" and r3["weight"] == 0.0 and not r3["kept"],
          r3["skip"])


# ═══════════════════════════════════════════════════════════
# 5. 비토 유도 — PICO 규율을 지키는가
# ═══════════════════════════════════════════════════════════
def test_veto():
    print("\n[5] 비토 유도 (PICO 규율)")
    from ..core import gates
    from ..core.state import Candidate

    def mk(fc):
        c = Candidate(name="t", origin="", query="")
        c.factcheck = fc
        return c

    hard = {"kept": True, "direction": "refute", "study_type": "rct", "decisive": True}
    soft = {"kept": True, "direction": "refute", "study_type": "observational",
            "decisive": True}
    sup = {"kept": True, "direction": "support", "study_type": "rct", "decisive": True}

    check("결정적 음성 1건만으로는 비토 안 함",
          gates.propose_veto(mk([hard]))[0] is False)
    check("결정적 음성 2건 · 동급 지지 없음 -> 비토",
          gates.propose_veto(mk([hard, hard]))[0] is True)
    check("조건이 갈리면(동급 지지 존재) 비토 안 함 -> 보류",
          gates.propose_veto(mk([hard, hard, sup]))[0] is False)
    check("관찰연구만으로는 비토 안 함",
          gates.propose_veto(mk([soft, soft]))[0] is False)


# ═══════════════════════════════════════════════════════════
# 6. 안전 실패 — 키 없을 때 스텁을 유지하는가
# ═══════════════════════════════════════════════════════════
def test_degrade():
    print("\n[6] 안전 실패")
    from ..core import gates
    from ..core.state import RunState, build_candidates

    llm.available = lambda: False
    st = RunState("q", "s", "t", build_candidates(), dict(gates.CONFIGS["B5"]))
    st = gates.gate_factcheck(st)
    c = st.candidates[0]
    check("LLM 없으면 curated 유지",
          all(e.source == "curated" for e in c.refute) and len(c.refute) == 3)
    check("스텁 잔존을 감사 추적에 기록",
          any(r.gate == "factcheck" and r.outcome == "SKIP" for r in c.trail))


# ═══════════════════════════════════════════════════════════
# 7. CLI 전 구간 — 단위 함수만 시험하면 놓치는 것이 있다
#
#    실제 사고: analyze.py 의 헬퍼는 전부 단위 시험을 통과했는데
#    main() 안의 리스트 컴프리헨션에서 zip에 라벨을 안 넣어
#    NameError 로 죽었다. 도구를 한 번도 실행해보지 않고 보낸 탓이다.
#    이제 합성 데이터로 CLI를 실제로 태운다.
# ═══════════════════════════════════════════════════════════
def test_cli():
    import json
    import os
    import tempfile
    print("\n[7] CLI 전 구간 (합성 데이터)")
    from ..bench import analyze

    n = 24
    rows = [{"drug": "d%d" % i, "indication": "x%d" % i,
             "label": "TP" if i % 2 else "TN"} for i in range(n)]

    def mk(verds):
        sc, vd = [], []
        for i, r in enumerate(rows):
            if i % 3 == 0:
                sc.append(0.5); vd.append(verds[0])
            elif r["label"] == "TP":
                sc.append(0.85); vd.append(verds[1])
            else:
                sc.append(0.15); vd.append(verds[2])
        return {"scores": sc, "verdicts": vd}

    d = {"stratum": "A", "n_tp": n // 2, "n_tn": n // 2, "rows": rows,
         "results": {"B0": mk(["모름", "성공", "실패"]),
                     "B5": mk(["보류", "유망", "기각"])}}
    d["results"]["B5"]["verdicts"][1] = "조건부"
    d["results"]["B5"]["verdicts"][5] = "조건부"

    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    try:
        import io as _io
        import contextlib
        for args, label in (([path], "엄격"), ([path, "--loose"], "완화")):
            buf = _io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = analyze.main(args)
            out = buf.getvalue()
            check("analyze CLI %s 정상 종료" % label, rc == 0)
            check("analyze CLI %s 표 출력" % label, "선택적 예측" in out and "McNemar" in out)
        # 조건부가 두 기준에서 다르게 세어지는가
        cov_s = analyze.selective(d["results"]["B5"]["scores"],
                                  [1 if r["label"] == "TP" else 0 for r in rows],
                                  verdicts=d["results"]["B5"]["verdicts"], strict=True)[0]
        cov_l = analyze.selective(d["results"]["B5"]["scores"],
                                  [1 if r["label"] == "TP" else 0 for r in rows],
                                  verdicts=d["results"]["B5"]["verdicts"], strict=False)[0]
        check("조건부가 엄격/완화에서 다르게 계산됨", cov_l > cov_s,
              "엄격 %.2f < 완화 %.2f" % (cov_s, cov_l))
    finally:
        os.unlink(path)



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


if __name__ == "__main__":
    try:
        from bioreroute.bench import srcstamp as _SS0
        _SNAP0 = _SS0.snapshot()
    except Exception:
        _SNAP0 = {}
    print("=" * 66)
    print("Phase 1 검증 — 모의 LLM (실제 호출 전 코드 고정)")
    print("=" * 66)
    _run(test_quote)
    _run(test_weight)
    recs = _run(test_xml)
    _run(test_classify, recs)
    _run(test_veto)
    _run(test_degrade)
    _run(test_cli)
    # ── 도는 동안 소스가 바뀌었나 (결함 202) ──────────────────────
    #   «고치기 전에 확인해라» 는 안내문이라 안 듣는다.
    #   **시험이 스스로 말하게** 한다 — 판정은 안 바꾸고 보이게만.
    try:
        from ..bench import srcstamp as _SS
        _msg = _SS.report(_SNAP0, _SS.snapshot(), "시험")
        if _msg:
            print(_msg)
    except Exception:
        pass
    print("\n" + "=" * 66)
    print("통과 %d · 실패 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("실패 목록: " + ", ".join(FAIL))
    print("=" * 66)
    sys.exit(1 if FAIL else 0)
