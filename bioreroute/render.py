# -*- coding: utf-8 -*-
"""콘솔 렌더러 — W1 출력과 글자 단위로 동일해야 한다(이식 성공 판정 기준)."""

import unicodedata

from .agents.factcheck import tag_for as _tag
from .core.state import RunState

ROUTE_LABEL = {"structure": "구조·도킹", "evidence": "증거경로", None: "-"}


def dw(s) -> int:
    """표시 폭 (한글·CJK는 2칸)"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(s))


def pad(s, n: int) -> str:
    s = str(s)
    if dw(s) > n:
        out = ""
        for ch in s:
            if dw(out) + dw(ch) > n:
                break
            out += ch
        s = out
    return s + " " * (n - dw(s))


def render_console(st: RunState, run_s2: bool = True) -> str:
    L = []
    L.append("=" * 78)
    L.append("Bio-ReRoute · W1-L1 프로토타입 — 반증 깔때기   [LIVE (PubMed 실시간)]")
    if st.config.get("rag"):
        L.append("F0=PubMed 실시간 · 지지/반박=L2 LLM 팩트체커(초록 판독, 인용 검증)")
    else:
        L.append("F0(근거 실재성)=PubMed 실시간 · 지지/반박 가중=큐레이션(실제판 L2=LLM 팩트체커)")
    L.append("=" * 78)
    L.append("질의 : %s" % st.query_title)
    L.append("설정 : %s | %s" % (st.settings, st.stamp))
    L.append("-" * 78)

    L.append("")
    L.append("[축1·입구] 후보 발굴")
    for c in st.candidates:
        L.append("  • %s [%s]" % (pad(c.name, 34), c.origin))

    L.append("")
    L.append("[F0·근거 실재성] PubMed 실시간 조회 →")
    for c in st.candidates:
        f0 = c.f0 or {}
        if f0.get("error"):
            L.append("  %s ERROR  %s" % (pad(c.name, 34), f0["error"]))
        elif (f0.get("count") or 0) == 0:
            L.append("  %s KILL   PubMed 0건 → 문헌 근거 없음(환각) 기각" % pad(c.name, 34))
        else:
            pm = "; ".join("PMID " + p for p in f0["pmids"])
            L.append("  %s PASS   PubMed %s건 · 상위: %s"
                     % (pad(c.name, 34), format(f0["count"], ","), pm))
            if f0.get("title"):
                t = f0["title"]
                L.append("    └ PMID %s: %s"
                         % (f0["pmids"][0], t[:62] + ("…" if len(t) > 62 else "")))

    if st.config.get("rag"):
        L.append("")
        L.append("[L2·팩트체커] 초록 판독 → 지지/반박 (근거는 원문 인용으로 검증)")
        for c in st.candidates:
            if not c.factcheck:
                r = next((x for x in reversed(c.trail) if x.gate == "factcheck"), None)
                L.append("  %s -  %s" % (pad(c.name, 34), r.detail if r else "미실행"))
                continue
            kept = [x for x in c.factcheck if x["kept"]]
            drop = len(c.factcheck) - len(kept)
            L.append("  %s 초록 %d건 → 채택 %d · 제외 %d"
                     % (pad(c.name, 34), len(c.factcheck), len(kept), drop))
            for x in c.factcheck:
                if x["kept"]:
                    cert = x.get("certainty", "high")
                    mark = "" if cert == "high" else "  [GRADE %s]" % cert
                    # 결함 166 — **누가 가져온 근거인지**를 콘솔에도 보인다.
                    #   `[회의주의자]` 표시가 곧 그 게이트의 값이다.
                    who = {"skeptic": " [회의주의자]", "registry": " [등록부]"} \
                        .get(x.get("stage") or "", "")
                    L.append("    %s %s w=%.2f · PMID %s%s%s"
                             % ("+" if x["direction"] == "support" else "-",
                                pad(_tag(x), 40), x["weight"], x["pmid"],
                                who, mark))
                    # 결함 160 — `x["quote"]` 는 **LLM 원문 그대로**다.
                    # 확인된 구간은 `quote_check["확인"]` 에 있다.
                    chk = x.get("quote_check") or {}
                    q = (chk.get("확인") or "").strip()
                    how = chk.get("how") or ""
                    if not q and chk.get("재서술"):
                        L.append("      └ (등록부 표를 문장으로 옮긴 **재서술** "
                                 "— 원문에 그 문장은 없다 · %s)" % how)
                    elif q:
                        L.append("      └ “%s”  [%s]"
                                 % (q[:60] + ("…" if len(q) > 60 else ""), how))
            # 제외 사유를 묶어서 보여준다. 왜 떨어졌는지 모르면 고칠 수 없다.
            drops = {}
            for x in c.factcheck:
                if x["kept"]:
                    continue
                why = str(x.get("skip") or "사유 미기록")
                key = ("인용 검증 실패" if "인용" in why else
                       "철회 논문" if "철회" in why else
                       "같은 시험 중복(NCT)" if "중복" in why else
                       "무관(효능 증거 아님)" if "무관" in why else
                       "초록 없음" if "초록 없음" in why else why[:28])
                drops.setdefault(key, []).append(x["pmid"])
            for why, pmids in sorted(drops.items(), key=lambda kv: -len(kv[1])):
                tail = ", ".join(pmids[:4]) + (" 외 %d" % (len(pmids) - 4)
                                               if len(pmids) > 4 else "")
                L.append("    · %s %d건  PMID %s" % (pad(why, 24), len(pmids), tail))

    if st.config.get("skeptic"):
        L.append("")
        L.append("[회의주의자] 반박 증거 능동 회수 (확증설계·부정결과 질의)")
        for c in st.candidates:
            r = next((x for x in reversed(c.trail) if x.gate == "skeptic"), None)
            L.append("  %s %s" % (pad(c.name, 34), r.detail if r else "미실행"))

    L.append("")
    L.append("[라우터] 직접/간접 분기")
    for c in st.candidates:
        if c.mech_class is None:
            L.append("  %s -  (F0 기각, 분류 안 함)" % pad(c.name, 34))
        else:
            L.append("  %s %s" % (pad(c.name, 34), c.mech_class))
            L.append("  %s   └ %s" % (pad("", 34), c.mech_note))

    if run_s2:
        L.append("")
        L.append("[S2·리간드 개발성] RDKit (SMILES=PubChem 실시간)")
        for c in st.candidates:
            r = c.s2
            if r is None:
                L.append("  %s -  (실체 없음, 대상 아님)" % pad(c.name, 34))
            else:
                L.append("  %s %-6s %s" % (pad(c.name, 34), r["status"], r["detail"]))

    # 조건부 판정은 근거만으론 부족하다. 어떤 조건에서 갈리는지 보여야 한다.
    conts = [c for c in st.candidates if c.verdict == "조건부"]
    if conts:
        L.append("")
        L.append("[조건 분기] 확증 설계가 양방향인 후보 — 어느 조건에서 갈리는가")
        for c in conts:
            L.append("  %s" % c.name)
            for r in c.factcheck:
                if not (r.get("kept") and r.get("study_type") in ("rct", "meta")):
                    continue
                pico = r.get("pico") or {}
                bits = [v for v in (pico.get("population"), pico.get("dose"),
                                    pico.get("timing")) if v]
                L.append("    %s %s  %s"
                         % ("지지" if r["direction"] == "support" else "반박",
                            pad("PMID " + r["pmid"], 14),
                            " · ".join(bits) if bits else "(조건 미기재)"))

    L.append("")
    L.append("[판정] 반증 깔때기 통합 결과")
    L.append("  %s %s %s %s %s"
             % (pad("후보", 32), pad("경로", 10), pad("판정", 6), pad("신뢰도", 7), "사유"))
    L.append("  " + "·" * 74)
    n = {"유망": 0, "조건부": 0, "보류": 0, "기각": 0}
    for c in st.candidates:
        n[c.verdict] = n.get(c.verdict, 0) + 1
        conf = "-" if c.confidence is None else "%d%%" % c.confidence
        L.append("  %s %s %s %s %s"
                 % (pad(c.name, 32), pad(ROUTE_LABEL[c.route], 10),
                    pad(c.verdict, 6), pad(conf, 7), c.reason))

    L.append("")
    L.append("  요약: 발굴 %d → 기각 %d · 보류 %d · 조건부 %d · 유망 %d"
             % (len(st.candidates), n["기각"], n["보류"], n["조건부"], n["유망"]))
    return "\n".join(L)
