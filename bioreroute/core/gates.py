# -*- coding: utf-8 -*-
"""게이트와 파이프라인.

각 게이트는 (state) -> state 이며, config로 켜고 끌 수 있다.
이 구조가 제안서의 B0~B5 단계별 제거 실험을 for 루프 하나로 만들어 준다.
모놀리식으로 짜면 제거 실험이 전면 재작성이 되므로 처음부터 강제한다.

비용 순서 원칙: 값싼 결정론적 게이트(F0)를 먼저 통과한 후보에만
비싼 단계(라우터·S2·회의주의자)를 태운다.
"""

import re as _re
from typing import Any, Callable, Dict, List, Optional

from ..agents import factcheck, router as router_agent
from ..io import sources
from . import profiles
from .scoring import adjudicate, prepare
from .state import Candidate, Evidence, RunState

N_ABSTRACTS = 8            # 후보당 팩트체크할 초록 수
N_SKEPTIC = 6              # 회의주의자가 추가로 회수할 초록 수(질의당)
N_REGISTRY = 8             # 등록부에서 읽을 시험 결과 수

# 벤치마크에서 라벨의 출처가 된 시험은 근거로 쓰면 안 된다.
#   TN 라벨이 "NCT12345가 futility로 중단"에서 왔는데 그 NCT의 결과를
#   근거로 주면 답을 알려주는 것이다. 실사용에서는 정당한 근거지만
#   **일반화 성능을 재려면 제외해야 한다.**
EXCLUDE_NCT = set()


def set_exclude(ncts, expand=True):
    """제외 목록을 모든 게이트·팩트체커에 동시에 건다.

    한 곳에만 걸면 다른 경로로 새어 들어온다. 실제로 등록부에만 걸어두고
    PubMed는 열어둔 상태였다 — 라벨 출처 시험이 논문으로 출판됐으면
    그대로 통과했다.

    **NCT 번호만으로는 부족하다.** 초록에 등록번호를 안 쓴 논문이 흔하고,
    그러면 라벨 출처 시험의 결과 논문이 그대로 근거가 된다.

      실측(`bench.leakcheck`): 기각한 TN 11건 중 라벨 시험 논문이 PubMed
      `[si]`에 색인된 것이 4건, **그중 2건이 근거로 들어와 있었다.**
      `warfarin/IPF` 의 "A placebo-controlled randomized trial" 이 그 예다 —
      초록에 NCT가 없어 통과했고, 그 판정은 예측이 아니라 답안지 읽기였다.

    그래서 NCT를 **PMID로 확장**한다. PubMed가 등록번호를 [si] 필드에
    색인하므로 그걸로 그 시험의 논문을 찾아 함께 막는다.
    LLM 호출은 없고 조회는 캐시된다.

    한계 — [si] 색인은 논문이 등록번호를 명시했을 때만 걸린다.
    **이 확장도 누출의 하한만 막는다.** 완전한 차단이 아니다.
    """
    global EXCLUDE_NCT
    EXCLUDE_NCT = set(ncts)
    factcheck.EXCLUDE_NCT = EXCLUDE_NCT
    # ── **"색인이 없다"와 "물어보지 못했다"를 섞지 않는다** (결함 37) ──────
    #
    #   전에는 `got = [] if error else pmids` 로 끝내고 둘을 `no_idx` 에
    #   합쳐 셌다. 그래서 조회가 죽어도 "색인 없음"으로 조용히 넘어갔다.
    #
    #   실측: 홀드아웃 sealed 의 라벨 출처 432건 중 **380건에서 이 질의가
    #   `Tunnel connection failed` 로 실패**했고, 그 실패가 캐시에 박혀
    #   영구화됐다. **PMID 수준 누출 차단이 88%에서 안 걸린 것이다.**
    #   그런데 화면에는 아무 경고도 안 나왔다.
    #
    #   NCT 수준 차단은 결정론이라 그대로 동작한다. 새는 것은 **초록에
    #   등록번호를 안 쓴 논문**이고, 그게 정확히 이 확장이 막으려던 것이다.
    pmids, no_idx, failed = set(), 0, []
    if expand:
        for n in sorted(EXCLUDE_NCT):
            r = sources.pubmed_search("%s[si]" % n, 20)
            if r.get("error"):
                failed.append(n)
                continue
            got = list(r.get("pmids") or [])
            pmids |= set(got)
            no_idx += 0 if got else 1
    factcheck.EXCLUDE_PMID = pmids
    if failed:
        print("  [경고] 누출 차단 PMID 확장이 %d/%d건 **실패**했다 (%s…)"
              % (len(failed), len(EXCLUDE_NCT), failed[0]))
        print("         NCT 수준 차단은 걸리지만 **초록에 등록번호를 안 쓴")
        print("         논문은 막지 못한다.** 이 실행의 누출 수치는 하한이 아니다.")
        print("         py -m bioreroute.netcheck 로 연결을 확인하고 다시 돌려라.")
    return {"ncts": len(EXCLUDE_NCT), "pmids": len(pmids), "no_index": no_idx,
            "failed": len(failed), "failed_ncts": failed}

# 회의주의자 질의. 관련도 정렬이 놓치는 것을 겨냥한다.
#   1행: 무작위배정 임상시험으로 한정 — 확증 설계를 강제로 끌어온다
#   2행: 부정 결과 표현 — 관련도 순위에서 밀리는 실패 보고를 찾는다
SKEPTIC_QUERIES = [
    '{drug} AND {disease} AND randomized controlled trial[pt]',
    '{drug} AND {disease} AND ("no significant" OR "did not improve" OR '
    '"no benefit" OR "did not reduce" OR futility OR "failed to" OR '
    '"no difference" OR ineffective)',
]

# ─────────────────────────────────────────────────────────────
# 제거 실험 구성 (제안서 §4.3)
# ─────────────────────────────────────────────────────────────
CONFIGS: Dict[str, Dict[str, bool]] = {
    "B0": {"rag": False, "f0": False, "router": False, "s2": False, "skeptic": False},
    "B1": {"rag": True,  "f0": False, "router": False, "s2": False, "skeptic": False},
    "B2": {"rag": True,  "f0": True,  "router": False, "s2": False, "skeptic": False},
    "B3": {"rag": True,  "f0": True,  "router": False, "s2": False, "skeptic": True},
    "B4": {"rag": True,  "f0": True,  "router": False, "s2": True,  "skeptic": True},
    "B5": {"rag": True,  "f0": True,  "router": True,  "s2": True,  "skeptic": True},
    # B6: 등록부 결과까지 읽는다. 출판 편향 천장을 넘는 유일한 경로다.
    "B6": {"rag": True,  "f0": True,  "router": True,  "s2": True,
           "skeptic": True, "registry": True},
    # B7: B6 + S1 구조 신뢰도 게이트 (제안서 §3.3-7 · 08-06 추가).
    #     **기존 구성에는 s1 을 넣지 않았다.** 넣으면 동결된 수치가
    #     다른 시스템의 수치가 된다 — QUIET_WHEN_OFF 주석 참조.
    "B7": {"rag": True,  "f0": True,  "router": True, "s1": True, "s2": True,
           "skeptic": True, "registry": True},
    # B8: B7 + HITL. **운용 구성**이다 — 제안서 §7의 비용 모델이 이걸 전제한다.
    #     벤치마크에는 쓰지 않는다. 음성 KB 내용에 따라 결과가 달라지므로
    #     **재현 가능한 측정이 아니기 때문이다.** 시험 [48]이 그걸 못 박는다.
    "B8": {"hitl": True, "rag": True, "f0": True, "router": True, "s1": True,
           "s2": True, "skeptic": True, "registry": True},
    # B5S: **시연 전용.** B5 + S1 구조 게이트. 등록부는 끈다.
    #
    #   08-11에 `oseltamivir / Influenza` 를 앱에서 처음 태웠더니 라우터가
    #   `직접·병원체 · neuraminidase → structure` 로 **분기를 열었다.**
    #   그런데 화면은 `s1 SKIP · config off` 였다 — 데모가 B5 로 돌고
    #   s1 은 B7 에만 있기 때문이다. **게이트를 다섯 겹 고쳐 놓고
    #   꺼진 채로 시연할 뻔했다.**
    #
    #   B7 로 바꾸지 않는 이유: B7 은 등록부(CT.gov)까지 켠다. 발표장에서
    #   CT.gov 가 느리면 **시연이 멈춘다.** 외부 의존을 하나 더 다는 것은
    #   결함 95(남의 서비스가 우리 모르게 죽음)를 겪은 뒤로는 그냥 위험이다.
    #
    #   **B0~B8 은 한 글자도 안 바꿨다.** 동결 수치와 시험 [45](B0~B6
    #   trail 동일성)가 그대로 간다. 이 구성은 **벤치마크에 안 쓴다** —
    #   `demo.run_pair` 와 「직접 검증」탭 전용이다.
    #
    #   추가 비용은 **LLM 0회**다. S1 은 UniProt·AlphaFold 조회만 한다.
    # B5F: **B5 + 전문 읽기(F).** 명세 `사전명세_전문읽기.md`(봉인
    #   `acc3525cd1da…`). 누적이 아니라 **B5 에서 갈라지는 가지**라
    #   번호를 잇지 않았다 — `B8` 은 이미 HITL 운용 구성이고, 거기에
    #   이어 붙이면 «재현 불가능한 구성으로 벤치를 돌리는» 일이 된다.
    #   주지표는 **기각 정밀도의 B5 → B5F 변화**.
    "B5F": {"rag": True, "f0": True, "router": True, "s2": True,
            "skeptic": True, "fulltext": True},
    "B5S": {"rag": True, "f0": True, "router": True, "s1": True,
            "s2": True, "skeptic": True},
    # W1: 팩트체커도 회의주의자도 없이 사람이 매긴 근거만 쓰는 구성.
    #     Phase 0 회귀 시험을 계속 돌리기 위해 남겨 둔다.
    #     원래 W1에는 회의주의자가 없었으므로 skeptic=False가 맞다.
    "W1": {"rag": False, "f0": True,  "router": True,  "s2": True,  "skeptic": False},
}

# ── 시연 구성은 **표에서 파생한다** — 09-17 (같은 사고 두 번째) ──────────
#
#   ## 무엇이 두 번 났나
#
#     08-11  `s1` 을 만들고 **시연 구성에 안 넣었다.** 앱에서 라우터가
#            구조 분기를 열었는데 화면은 `s1 SKIP · config off` 였다.
#            위 `B5S` 주석이 그때 적은 것이다 —
#            *"게이트를 다섯 겹 고쳐 놓고 꺼진 채로 시연할 뻔했다."*
#
#     09-15  `fulltext`(F) 를 만들고 **또 안 넣었다.** `B5F` 는 벤치용이라
#            `s1` 이 없고, `B5S` 에는 `fulltext` 가 없다. 즉 **둘을 같이
#            켠 구성이 저장소에 없었다.** 09-17 에 찾았다.
#
#   ## 그래서 안내문 대신 구조로 막는다
#
#   새 게이트를 `ORDER` 에 추가하면 **여기에도 적어야 한다.** 안 적으면
#   시험 [82]가 *"시연에 넣을지 결정을 안 적었다"* 로 실패한다.
#   `CONFIGS["B5SF"]` 는 이 표에서 **파생**되므로 표와 구성이 갈릴 수 없다.
#
#   ⚠ **벤치마크에 쓰지 마라.** `B5S` 와 같은 이유다 — 동결 수치는
#     `B0`~`B6` 에서 나왔고 이 구성은 화면 전용이다.
DEMO_GATES: Dict[str, "tuple"] = {
    "hitl":     (False, "운용 기능이다. 시연에서 사람 개입을 보이면 «자율» 주장이 흐려진다"),
    "f0":       (True,  "값싼 첫 관문 — 깔때기의 시작을 보여준다"),
    "rag":      (True,  "지지·반박 가르기. 근거 카드의 원천"),
    "router":   (True,  "경로가 갈리는 것이 자율성 10점의 실물이다"),
    "s1":       (True,  "08-11 — 꺼진 채로 시연할 뻔했다"),
    "s2":       (True,  "약물다움. RDKit 실호출을 보여준다"),
    "skeptic":  (True,  "반증 우선이라는 논지의 본체"),
    "fulltext": (True,  "09-15 — s1 과 **같은 사고가 반복**됐다. 09월 대표 기능"),
    "registry": (False, "CT.gov 가 느리면 발표장에서 시연이 멈춘다 (결함 95)"),
}

# **표에서 파생한다.** 손으로 적으면 표와 갈린다 (결함 159 계열).
CONFIGS["B5SF"] = {g: True for g, (on, _why) in DEMO_GATES.items() if on}

FULL = CONFIGS["B5"]


# ── ⛔ 09-19 · **내부 색인이 심사위원 화면으로 샜다** (결함 261 재발) ──────
#
#   `DEMO_GATES` 의 사유는 **개발자에게 쓴 글**이다 — `(결함 95)` 같은
#   내부 색인과 `08-11` 같은 개발 날짜가 들어 있다. 그런데 09-18에
#   `dash.thinking()` 이 그 사유를 **그대로 화면에 찍게** 만들었다.
#   **심사위원 화면에 «결함 95» 가 떴다.**
#
#   시험 `[141]`(*«화면에 개발 기록이 안 새어 나간다»* · 결함 261)이
#   잡았다. ⚠ **더 나쁜 것** — 내가 `[162]②` 로 *«사유가 그대로 나온다»*
#   를 검사해서 **그 유출을 시험으로 고정까지 했다.** 가드 둘이 충돌했고
#   **`[141]` 이 옳다.**
#
#   **고침은 «어느 쪽을 지울까» 가 아니라 «누구에게 주는 글인가» 다** —
#   코드에는 색인을 남기고, **화면에 줄 때만 벗긴다.**
_SCREEN_STRIP = _re.compile(
    r"\s*[(（]\s*결함\s*\d+[^)）]*[)）]"      # (결함 95)
    r"|\s*\b\d{2}-\d{2}\b\s*[—–-]*\s*"        # 08-11 — / 09-15 —
)


def demo_off(for_screen: bool = True) -> List[tuple]:
    """시연 구성에서 **끈** 게이트와 그 사유 — 09-18 신설.

    ⚠ **`for_screen=True`(기본)면 내부 색인·개발 날짜를 벗긴다.**
    사유는 개발자에게 쓴 글이라 `(결함 NNN)` 이 섞여 있고, 그게 그대로
    화면에 나가면 **결함 261 의 재발**이다(09-19 실측 · `[141]` 이 잡았다).
    원문이 필요하면 `for_screen=False` 로 부른다.

    ## 왜 이게 필요한가 — **«없는 것» 과 «끈 것» 은 다르다**

    제안서 §2 가 **세 축**이라고 했다. 셋째가 HITL 음성 지식베이스
    루프인데 `DEMO_GATES` 가 그걸 **끈다**(사유: *«시연에서 사람 개입을
    보이면 «자율» 주장이 흐려진다»*). 판단은 옳다 — 배점 ②가
    *«**스스로** 단계 분해»* 를 묻는데 사람 개입을 보이면 손해다.

    **문제는 화면이 그 사실을 말하지 않는 것**이다. 심사위원이 세면
    **둘만 보인다.** 제안서를 손에 들고 있으면 바로 나온다.

    > ⛔ **사유는 08-27부터 `DEMO_GATES` 에 적혀 있었다.** 그런데
    > `CONFIGS["B5SF"]` 가 `_why` 를 **버리고**, 화면은 그걸 한 번도
    > 안 읽었다. **적어 둔 것이 아무 데도 안 닿았다** —
    > `fragility` · `false_negatives` · `refute_recall` 과 같은 계열의
    > **네 번째**다(`기능전수_0918`).

    `dash.thinking()` 이 이걸 화면 맨 아래에 찍는다.
    """
    out = []
    for g, (on, why) in DEMO_GATES.items():
        if on:
            continue
        out.append((g, _SCREEN_STRIP.sub(" ", why).strip() if for_screen else why))
    return out


def gate_f0(st: RunState) -> RunState:
    """F0 근거 실재성 — 2겹으로 나눈다.

      1겹 실체 검증  : 그 약물이 문헌에 존재하는가
      2겹 연결 근거  : 그 약물-질환 쌍에 대한 문헌이 있는가

    둘을 합치면 안 되는 이유가 실측으로 드러났다.
    `gentamicin AND Paronychia Inflammation` 은 0건이지만 젠타마이신은 실재한다.
    쌍에 대한 문헌이 없을 뿐인데 "환각"으로 기각하면 두 가지를 잃는다.
      · 라벨이 틀린다 — 실재하는 약을 환각이라 부른다
      · Swanson형 신규 발견을 원천 차단한다. 연결 문헌 0건은 오히려 신규성 신호다

    그래서 1겹이 통과하고 2겹만 0이면 기각이 아니라 보류로 보낸다.
    """
    for c in st.candidates:
        # 시점 차단이 켜지면 **F0도 그 시점 이전만 봐야 한다.**
        #
        #   F0는 증거를 만들지 않고 실재 여부만 보지만, 컷오프를 안 걸면
        #   "그 시점엔 문헌이 없던 쌍"이 나중 문헌 덕에 PASS로 통과한다.
        #   증거원 네 곳(팩트체크·회의주의자·등록부·F0) 중 하나만 열어두면
        #   그게 새는 구멍이 된다 — 누출 차단에서 이미 겪은 실수다.
        if c.cutoff_year:
            f0 = sources.pubmed_search(c.query, 3, c.cutoff_year)
            f0 = {"count": f0.get("count"), "pmids": f0.get("pmids") or [],
                  "title": "", "error": f0.get("error"), "cutoff": c.cutoff_year}
        else:
            # ── 결함 329 ① — **캐시 객체를 고치지 않는다** ──
            #   `pubmed_lookup` 이 돌려주는 것은 캐시에 든 dict **그 자체**다.
            #   아래에서 `entity_count`·`link_zero`(·`error`)를 써 넣으면 그게
            #   캐시에 남는다(`RVT-101` 쌍 항목에서 실측). 복사해서 쓴다.
            f0 = dict(sources.pubmed_lookup(c.query))
        c.f0 = f0
        if f0.get("error"):
            c.note("f0", "ERROR", f0["error"])
            continue
        if (f0.get("count") or 0) > 0:
            c.note("f0", "PASS", "PubMed %d건" % f0["count"], pmids=f0.get("pmids"))
            continue

        # 쌍은 0건이다. 약물 자체가 실재하는지 따로 확인한다.
        if not c.drug:
            c.note("f0", "KILL", "PubMed 0건 → 문헌 근거 없음(환각)")
            continue
        # 약물 실재 확인도 같은 시점 기준으로. 그 시점에 아직 문헌이 없던
        #   약을 나중 문헌으로 "실재한다"고 판정하면 시점 차단이 아니다.
        ent = (sources.pubmed_search(c.drug, 1, c.cutoff_year) if c.cutoff_year
               else sources.pubmed_lookup(c.drug, retmax=1))
        c.f0_entity = ent
        if ent.get("error"):
            c.note("f0", "ERROR", "실체 확인 실패: %s" % ent["error"])
            # ── 결함 329 ② — 실재 조회가 실패하면 **«환각」 이 아니라 «조회 실패」** ──
            #   `adjudicate` 는 `c.f0["error"]` 만 본다. 여기 안 올리면 쌍 0건 ·
            #   연결 표시 없음으로 읽혀 *«F0: 문헌 근거 없음(환각)」* 기각이 된다.
            #   09-21 terra C6 의 `RVT-101 35 mg` 이 정확히 그랬다(HTTP 429).
            f0["error"] = "실체 확인 실패: %s" % ent["error"]
        elif (ent.get("count") or 0) == 0:
            c.note("f0", "KILL", "약물 자체가 문헌에 없음 → 환각")
        else:
            # 실체는 있고 연결만 없다. 기각하지 않는다.
            f0["entity_count"] = ent["count"]
            f0["link_zero"] = True
            c.note("f0", "FLAG",
                   "약물 실재(%d건)하나 질환 연결 문헌 0건 — 신규성 신호이거나 미탐색 영역"
                   % ent["count"])
    return st


def gate_factcheck(st: RunState) -> RunState:
    """L2 팩트체커 — 문헌을 실제로 읽어 지지/반박 근거를 만든다.

    이 게이트가 켜지면 사람이 매긴 근거(curated)를 **버리고** LLM 판정으로 갈아탄다.
    스텁을 지우는 것이 Phase 1의 목적이므로 병행하지 않는다.
    LLM을 못 쓰면 갈아타지 않고 curated를 유지하되 그 사실을 기록한다.
    """
    from ..io import llm as _llm

    if not _llm.available():
        for c in st.candidates:
            c.note("factcheck", "SKIP",
                   "LLM 미설정 — 사람이 매긴 근거 유지(스텁 잔존)")
        st.log.append("factcheck: LLM 미설정")
        return st

    for c in st.candidates:
        if c.killed:
            c.note("factcheck", "SKIP", "F0 기각 — 초록 읽지 않음(비용 순서)")
            continue

        s = sources.pubmed_search(c.query, N_ABSTRACTS, c.cutoff_year)
        if s.get("error"):
            c.note("factcheck", "ERROR", "검색 실패: %s" % s["error"])
            continue
        recs = sources.pubmed_abstracts(s["pmids"])
        if c.cutoff_year:
            recs = {k: v for k, v in recs.items()
                    if not v.get("year") or v["year"] <= c.cutoff_year}
        if not recs:
            c.note("factcheck", "SKIP", "초록 0건 — 사람이 매긴 근거 유지")
            continue

        # 초록마다 호출하면 후보 4개에 32회다. 무료 티어 일일 한도를 한 번에 넘는다.
        # 묶어서 후보당 1회로 보낸다.
        results = factcheck.classify_batch(
            c.drug, c.disease, [recs[p] for p in s["pmids"] if p in recs])
        c.factcheck = _stamp(results, "factcheck")

        kept = [r for r in results if r["kept"]]
        _rebuild_evidence(c)

        n_excl = sum(1 for r in results
                     if r.get("skip") and "라벨 출처" in str(r["skip"]))
        n_retract = sum(1 for r in results if r["retracted"])
        n_fabric = sum(1 for r in results
                       if r.get("quote_check") and not r["quote_check"]["ok"])
        c.note("factcheck", "DONE",
               "초록 %d건 → 지지 %d · 반박 %d · 무관 %d (철회 %d · 인용실패 %d%s)"
               % (len(results), len(c.support), len(c.refute),
                  len(results) - len(kept), n_retract, n_fabric,
                  (" · 라벨출처 %d" % n_excl) if n_excl else ""),
               model=(results[0].get("provenance") or {}).get("model") if results else None)

        # 비토는 사람이 매긴 스텁이었다. 팩트체커가 돌았으면 근거에서 다시 유도한다.
        v, why = propose_veto(c)
        if v != c.veto:
            c.note("veto", "CHANGED", "사람 지정 %s → 근거 유도 %s · %s" % (c.veto, v, why))
        c.veto, c.veto_reason = v, why
    return st


def propose_veto(c) -> tuple:
    """근거에서 하드 비토를 유도한다.

    §2.3 PICO 규율: 조건이 갈리면 기각이 아니라 보류다. 따라서 비토는
    확증 설계(RCT·메타분석)의 결정적 음성이 2건 이상이고 같은 급의 지지가
    전혀 없을 때로 좁힌다. 한 건만으로는 비토하지 않는다.
    """
    hard = [r for r in (c.factcheck or [])
            if r["kept"] and r["direction"] == "refute"
            and r.get("study_type") in factcheck.DECISIVE_OK and r.get("decisive")]
    strong_sup = [r for r in (c.factcheck or [])
                  if r["kept"] and r["direction"] == "support"
                  and r.get("study_type") in factcheck.DECISIVE_OK]
    if len(hard) >= 2 and not strong_sup:
        return True, "결정적 확증시험 음성 %d건 · 동급 지지 없음" % len(hard)
    if len(hard) >= 2 and strong_sup:
        return False, ""      # 조건이 갈린다 → 비토하지 않고 보류로
    return False, ""


def gate_router(st: RunState) -> RunState:
    """기전 라우터 — 직접/간접 × 병원체/숙주로 검증 경로를 분기.

    시드에 분류가 이미 있으면 그걸 쓰고(사람이 지정한 값), 없으면 LLM으로 분류한다.
    벤치마크 후보에는 시드 분류가 없어 지금까지 이 게이트가 무동작이었다.
    """
    from ..io import llm as _llm

    todo = [c for c in st.candidates if not c.killed and c.mech_class is None]
    if todo and _llm.available():
        res = router_agent.classify([{"drug": c.drug, "disease": c.disease}
                                     for c in todo])
        for c, r in zip(todo, res):
            c.mech_class = r["mech"]
            c.mech_note = (r["why"] or "")[:80]
            c.route = r["route"]
            c.router_rec = r
            c.note("router", "BRANCH" if r["route"] else "UNKNOWN",
                   "%s%s → %s (%s)" % (r["mech"],
                                       (" · " + r["target"]) if r["target"] else "",
                                       r["route"], r["confidence"]),
                   source="llm", provenance=r.get("provenance"))
    for c in st.candidates:
        if c.killed:
            c.note("router", "SKIP", "F0 기각 — 분류하지 않음")
        elif c.mech_class is None:
            c.note("router", "SKIP", "LLM 미설정 — 분류 불가")
        elif not any(t.gate == "router" for t in c.trail):
            c.note("router", "BRANCH" if c.route else "STUB",
                   "%s → %s" % (c.mech_class, c.route), source="seed")
    return st


def gate_hitl(st: RunState) -> RunState:
    """HITL 음성 지식베이스 조회 (제안서 §2 세 축 중 셋째 · §7).

    **F0 앞에 둔다.** 사람이 이미 거절한 쌍에 LLM 호출 세 번을 쓸 이유가 없다 —
    제안서 §7이 *"HITL로 불필요한 호출을 차단해 일 300~500회"* 라고 쓴 게
    이 위치를 말한다. 값싼 것부터라는 깔때기 원칙과도 맞는다.

    ## 차단과 경보를 가른다

    같은 쌍을 사람이 거절했으면 **차단**한다. 유사 골격은 **경보만** 내고
    기각하지 않는다 — 구조가 비슷하다는 것은 안 듣는다는 근거가 아니다.
    제안서 문구(*"유사 골격을 자동으로 차단"*)보다 약하게 만든 것이고
    그 이유는 `core/hitl.py` 독스트링에 적었다.
    """
    from . import hitl as _hitl

    kb = _hitl.load()
    if kb.get("error"):
        for c in st.candidates:
            c.note("hitl", "ERROR", "KB 읽기 실패: %s" % kb["error"])
        return st                      # 못 읽었으면 아무것도 막지 않는다
    for c in st.candidates:
        if c.killed:
            continue
        r = _hitl.consult(c.drug, c.disease, (c.s2 or {}).get("smiles"), kb=kb)
        c.hitl = r
        if r["verdict"] == "block":
            c.kill("HITL: " + r["why"])
            c.note("hitl", "KILL", r["why"])
        elif r["verdict"] == "warn":
            c.note("hitl", "WARN", r["why"])
        elif r["verdict"] == "unknown":
            c.note("hitl", "UNKNOWN", r["why"])
        else:
            c.note("hitl", "PASS", "음성 KB %d건 중 해당 없음" % r["kb_size"])
    return st


def gate_s1(st: RunState) -> RunState:
    """S1 구조 신뢰도 — **구조 경로로 분기된 후보만** (제안서 §2.5 · §3.3-7).

    제안서가 S1과 S2를 갈라 놓은 이유를 그대로 따른다.

      > S1과 S3는 표적 구조에 의존하므로 **직접 결합으로 분류된 후보만**
      > 거친다. 반면 S2 리간드 개발성은 분자 자체의 성질이라 **경로와
      > 무관하게 모든 후보에** 적용한다.

    그래서 이 게이트는 라우터가 `structure` 로 보낸 후보에만 돈다.
    실측으로 그건 27건 중 0건이었다 — **분기가 비어 있는 것이 정상이고,
    비어 있음을 SKIP 으로 남기는 것이 이 게이트가 하는 일의 절반이다.**

    ## 저신뢰는 기각이 아니다

    제안서는 `무질서 영역/환각 구조 → 연산 제외` 라고 적었다. **탈락이
    아니라 제외다.** 구조를 못 믿겠다는 말이지 약이 안 듣는다는 말이 아니다.
    그래서 `c.kill()` 을 부르지 않고 경로만 `evidence` 로 되돌린다 —
    구조로 검증할 수 없으니 임상·발현 증거로 보라는 뜻이다.

    이 구분을 안 하면 **구조가 없는 표적을 전부 기각**하게 되고, 그건
    "근거 없음"을 "반증됨"으로 읽는 것이다. 결함 34에서 겪은 것과 같다.
    """
    from ..io import structure as _struct

    for c in st.candidates:
        if c.killed:
            c.note("s1", "SKIP", "이미 기각")
            continue
        if c.route != "structure":
            c.note("s1", "SKIP", "구조 경로 아님 (%s)" % (c.route or "미분류"))
            continue
        tgt = (c.router_rec or {}).get("target") or ""
        r = _struct.assess(tgt, _organism_hint(c))
        c.s1 = r
        tag, downgrade = _S1_ACT.get(r["label"], (None, None))
        if tag is None:
            # 라벨이 늘었는데 여기를 안 고친 것이다. **조용히 넘기지 않는다** —
            # 그게 결함 92였다(`신뢰도미상` 이 조회 실패로 취급됨).
            c.note("s1", "ERROR", "처리 안 된 S1 라벨 `%s` — %s"
                                  % (r["label"], r["why"]))
            continue
        if downgrade:
            c.route = "evidence"          # 탈락이 아니라 **연산 제외**
        # **표적 이름을 줄인다** (결함 108). 바로 윗줄 라우터 행이 이미
        # 전체 이름을 적는다 — `rpoB` 는 48자다. 08-11 실측에서 이 행이
        # 119자가 돼 가로 스크롤 가드([61])에 걸렸다. **같은 사실을 두 줄에
        # 다 적으면 좁은 칸이 넘친다.**
        short = tgt if len(tgt) <= 24 else tgt[:23] + "…"
        c.note("s1", tag, "%s · %s%s"
                          % (short, r["why"],
                             " → 증거 경로로 전환" if downgrade else ""))
    return st


# S1 라벨 → (기록 태그, 증거 경로로 내릴 것인가).
# **`structure.LABELS` 를 전부 덮어야 한다** — 시험 [73]이 그걸 본다.
#
#   `오류` 만 경로를 안 바꾼다. 조회 실패는 **0건이 아니다** — 네트워크
#   장애를 발견으로 읽는 것이 결함 35였다.
#   `신뢰도미상` 은 08-10에 늘어난 라벨이다(결함 89·90). 구조는 있으나
#   신뢰도를 못 재므로 **연산 제외**다 — `저신뢰` 와 처분이 같고 이유가 다르다.
_S1_ACT = {
    "신뢰":       ("PASS", False),
    "저신뢰":     ("DOWNGRADE", True),
    "신뢰도미상": ("UNKNOWN", True),
    "구조없음":   ("NOSTRUCT", True),
    "오류":       ("ERROR", False),
}


# 병원체 표적이면 숙주(사람)에서 찾으면 안 된다. 질환명에서 힌트를 얻는다.
_ORG = [("SARS-CoV-2", ("covid", "sars-cov-2", "sars cov 2")),
        ("Human immunodeficiency virus 1", ("hiv",)),
        ("Mycobacterium tuberculosis", ("tubercul",)),
        ("Plasmodium falciparum", ("malaria",)),
        ("Influenza A virus", ("influenza",)),
        ("Hepatitis C virus", ("hepatitis c", "hcv"))]


def _organism_hint(c) -> Optional[str]:
    """직접·병원체로 분류됐을 때만 병원체 종을 좁힌다.

    숙주 표적인데 바이러스로 검색하면 0건이 나오고, 그 0건은 **"구조없음"
    으로 읽혀 조용히 틀린다.** 그래서 분류가 병원체일 때만 쓴다.
    """
    if (c.mech_class or "") != "직접·병원체":
        return None
    d = (c.disease or "").lower()
    for name, keys in _ORG:
        if any(k in d for k in keys):
            return name
    return None


def gate_s2(st: RunState) -> RunState:
    """S2 리간드 개발성 — 분자 자체의 성질이므로 경로와 무관하게 전체 적용."""
    for c in st.candidates:
        if c.killed:
            c.s2 = None
            c.note("s2", "SKIP", "F0 기각")
            continue
        # pubchem 이름이 없으면 약물명으로 조회한다. 없으면 S2가 영원히 SKIP된다.
        r = sources.s2_properties(c.pubchem or c.drug or None)
        c.s2 = r
        if r is None:
            c.note("s2", "SKIP", "실체 없음, 대상 아님")
        else:
            # ── hERG · DILI · 접근성을 여기 붙인다 (제안서 §1.2 · §2.5 · §8.3)
            #
            #   **trail 문구를 건드리지 않는다.** status·detail 이 바뀌면
            #   동결된 실행 기록과 대조가 어긋난다. dict 에 키만 더한다.
            #
            #   셋 다 **판정에 들어가지 않는다** — hERG·DILI 는 경보이고
            #   접근성은 제안서 §2.5가 "효능 판정에서 떼어내 접근성 층으로
            #   보낸다"고 못 박았다.
            _annotate(c, r)
            c.note("s2", r["status"], r["detail"])
    return st


def _annotate(c, r: Dict[str, Any]) -> None:
    """S2 결과에 독성 경보·접근성 신호를 덧붙인다. **판정에는 안 쓴다.**

    제안서 §8.3: *"이 판단은 정성적 선호가 아니라 **S2가 산출한 물성에
    근거한다**"* — 그래서 S2 가 이미 계산한 값을 재사용하고 새 조회를
    하지 않는다.
    """
    from ..io import tox
    from . import profiles
    sm = (r.get("smiles") or "") if isinstance(r, dict) else ""
    if sm:
        r["herg"] = tox.herg_alert(sm)
        r["dili"] = tox.dili_alert(sm)
    r["accessibility"] = profiles.accessibility(c.drug or "", r)


def _shown_quote(r) -> tuple:
    """화면에 **인용으로 내보낼 문자열**과 그 검증 방식 (결함 160).

    앞판은 `note=r["quote"]` 로 **LLM 이 보낸 문자열 전체**를 넘겼다.
    그런데 `verify_quote` 는 산문 초록에서 **앞 절반만 맞아도 통과**시키고
    (`factcheck.py` 부분일치), 등록부에서는 **수치 대조**로 통과시킨다.
    즉 화면이 「인용 원문」이라 부르는 것의 **뒷부분이 원문이 아닐 수 있고,
    등록부 건은 아예 문장이 원문에 없다**(표를 옮긴 재서술이다).

    현직 연구자 5명이 *"AI 가 알려준 논문이 실제로 없었던 적이 있어서
    지금은 참고용으로만 쓴다"* 고 했다(`인터뷰기록.md #2`). **그들이 겪은
    실패의 축소판이 우리 화면에 있었다.** 우리가 파는 것이 「보정된
    신뢰」인데 표시가 실제보다 세면 그 주장 전체가 무너진다.

    **확인된 구간만** 인용으로 내보내고 나머지는 방식 라벨로 알린다.
    판정·가중치·`r["quote"]` 원본은 **건드리지 않는다** — 벤치마크 값이
    바뀌면 `CLAUDE.md §3-2` 위반이다. 바뀌는 것은 표시뿐이다.
    """
    chk = r.get("quote_check") or {}
    how = chk.get("how", "")
    ok_span = chk.get("확인")
    if ok_span:                                   # 완전일치 · 부분일치
        return ok_span, how
    if chk.get("재서술"):                          # 등록부 수치 대조
        return "", "재서술(등록부 표 → 문장) · %s" % how
    # 검증을 안 탄 경로(구판 기록 등)는 **원문이라고 부르지 않는다.**
    return (r.get("quote") or ""), (how or "검증 기록 없음")


def _stamp(recs, stage):
    """근거마다 **어느 게이트가 가져왔는지** 새긴다 (결함 166).

    08-13 B2·B3 짝비교를 분석하면서 드러났다 — `c.factcheck` 는
    팩트체커가 읽은 것과 **회의주의자·등록부가 뒤에 덧붙인 것**을
    **구분하지 않았다.** 유일한 단서가 trail 의 «추가 초록 N건» 이라는
    **서식 문자열**이었고, 그 외에는 **목록의 위치로 추정**해야 했다.

    실측으로 위치 가정이 28/28 성립하긴 했다(`회의주의자결과.md`).
    **그래도 위치는 계약이 아니다** — 게이트 순서를 한 번 바꾸면 조용히
    깨지고, 깨진 걸 알 방법이 없다. 우리가 파는 것이 «감사 가능한 근거»
    인데 **근거의 출처가 감사 대상에서 빠져 있었다.**

    **판정에 안 쓴다.** 가중치·방향·`kept` 를 건드리지 않는 메타데이터
    한 칸이다(시험 [102] 가 그걸 고정한다). 이미 값이 있으면 덮지 않는다 —
    같은 레코드가 두 번 새겨지는 일이 없어야 한다.
    """
    for r in recs:
        if not r.get("stage"):
            r["stage"] = stage
    return recs


def _rebuild_evidence(c) -> None:
    """factcheck 결과 전체에서 지지/반박 목록을 다시 만든다."""
    kept = [r for r in (c.factcheck or []) if r["kept"]]

    def _ev(r, d):
        q, how = _shown_quote(r)
        return Evidence(factcheck.tag_for(r), d, r["weight"], source="llm",
                        pmid=r["pmid"], note=q, quote_how=how,
                        stage=r.get("stage") or "",
                        pico={k: v for k, v in (r.get("pico") or {}).items() if v})

    c.support = [_ev(r, "support") for r in kept if r["direction"] == "support"]
    c.refute = [_ev(r, "refute") for r in kept if r["direction"] == "refute"]


def gate_skeptic(st: RunState) -> RunState:
    """회의주의자 — 반박 증거를 능동적으로 회수한다.

    PubMed 관련도 정렬은 인용이 많고 결론이 선명한 논문을 위로 올린다.
    그건 대체로 긍정 결과다. 그 순위를 그대로 받아 읽으면 시스템 전체가
    확증 편향에 노출된다. 반증 우선을 표방하면서 증거 수집이 수동이면 모순이다.

    그래서 별도 질의로 확증 설계와 부정 결과를 강제로 끌어온다.
    이미 읽은 PMID는 건너뛰므로 추가 비용은 새 초록에만 든다.
    """
    from ..io import llm as _llm

    if not _llm.available():
        for c in st.candidates:
            if not c.killed:
                c.note("skeptic", "SKIP", "LLM 미설정 — 반박 회수 불가")
        return st

    for c in st.candidates:
        if c.killed:
            c.note("skeptic", "SKIP", "F0 기각")
            continue
        if not c.drug or not c.disease:
            c.note("skeptic", "SKIP", "약물·질환 미지정")
            continue

        seen = {r["pmid"] for r in (c.factcheck or [])}
        fresh, qlog = [], []
        for t in SKEPTIC_QUERIES:
            q = t.format(drug=c.drug, disease=c.disease)
            r = sources.pubmed_search(q, N_SKEPTIC, c.cutoff_year)
            if r.get("error"):
                qlog.append("질의 실패")
                continue
            new = [p for p in r["pmids"] if p not in seen and p not in fresh]
            fresh += new
            qlog.append("%d건 중 신규 %d" % (len(r["pmids"]), len(new)))

        if not fresh:
            c.note("skeptic", "NONE", "새 문헌 없음 · " + " | ".join(qlog))
            continue

        recs = sources.pubmed_abstracts(fresh)
        # **역할을 넘긴다** — 안 넘기면 회의주의자 호출이 `factcheck` 로
        # 청구돼 `model_for("skeptic")` 이 죽은 설정이 된다(결함 232).
        add = factcheck.classify_batch(c.drug, c.disease,
                                       [recs[p] for p in fresh if p in recs],
                                       role="skeptic")
        before_r = len(c.refute)
        c.factcheck = (c.factcheck or []) + _stamp(add, "skeptic")
        _rebuild_evidence(c)
        gained = len(c.refute) - before_r
        c.note("skeptic", "DONE",
               "추가 초록 %d건 → 반박 +%d · 지지 +%d  (%s)"
               % (len(add), gained,
                  len([r for r in add if r["kept"] and r["direction"] == "support"]),
                  " | ".join(qlog)))

        v, why = propose_veto(c)
        if v != c.veto:
            c.note("veto", "CHANGED", "회의주의자 반영 → %s · %s" % (v, why))
        c.veto, c.veto_reason = v, why
    return st


def _comparative(rec) -> bool:
    """이 등록부 결과로 효능을 판단할 수 있는가.

    조건 둘 — **무작위배정**이고, **1상 전용이 아닐 것.**

      · 대조군이 없으면 반응률이 얼마든 효능을 지지도 반박도 못 한다.
      · 1상은 안전성·용량이 목적이라 효능 근거가 될 수 없다.

    bench.ceiling 의 `comparative` 와 **같은 기준**이어야 한다.
    측정과 시스템이 다른 것을 보면 어느 숫자도 다른 쪽을 설명하지 못한다.
    """
    pts = [str(p).upper() for p in (rec.get("pubtypes") or [])]
    if rec.get("study_type") != "rct" and "RANDOMIZED" not in pts:
        return False
    phases = [p for p in pts if p.startswith("PHASE")]
    if phases and all("PHASE1" in p for p in phases):
        return False
    return True


def gate_registry(st: RunState) -> RunState:
    """등록부 결과 — 출판되지 않은 반증 근거를 회수한다.

    PubMed만 읽으면 상한이 출판 편향에 묶인다. 중단 시험의 논문 출판률은 22%인데
    시험 데이터에 근거해 중단한 경우 등록부 결과 게시율은 91%다.
    **근거가 없는 게 아니라 논문이 아닌 곳에 있는 것이다.**

    이 게이트가 제안서의 핵심 주장을 직접 구현한다 —
    반증 근거를 찾지 않는 것이 병목이라면, 아무도 안 보는 곳을 보는 것이 답이다.
    """
    from ..io import llm as _llm

    if not _llm.available():
        for c in st.candidates:
            if not c.killed:
                c.note("registry", "SKIP", "LLM 미설정")
        return st

    for c in st.candidates:
        if c.killed or not c.drug or not c.disease:
            c.note("registry", "SKIP", "대상 아님")
            continue
        # ── 반증 우선 회수 ───────────────────────────────────
        #
        #   그냥 검색하면 **완료된 성공 시험이 먼저 온다.** 실측에서
        #   등록부 근거 3건이 전부 TP에 붙었고 방향이 전부 지지였다.
        #   반증을 찾겠다고 만든 게이트가 확증만 물어온 것이다.
        #
        #   gate_skeptic은 PubMed에 대해 이미 이 문제를 푼다 —
        #   'futility OR "no benefit"' 같은 질의를 따로 던진다.
        #   **등록부에는 그 짝이 없었다.** 그 비대칭이 원인이다.
        #
        #   중단·철회 시험을 먼저 채우고 남는 자리만 일반 검색으로 메운다.
        #   한쪽만 보면 TP의 등록부 근거를 영영 못 보므로 둘 다 본다.
        neg = sources.ctgov_search(c.drug, c.disease, N_REGISTRY,
                                   status=sources.NEGATIVE_STATUS)
        gen = sources.ctgov_search(c.drug, c.disease, N_REGISTRY)
        if neg.get("error") and gen.get("error"):
            c.note("registry", "ERROR", gen["error"])
            continue
        found, order = [], (neg.get("ncts") or []) + (gen.get("ncts") or [])
        for n in order:
            if n not in found:
                found.append(n)
        s_ = {"ncts": found, "how": "중단우선"}
        seen = {r["pmid"] for r in (c.factcheck or [])}
        ncts = [n for n in found if n not in seen and n not in EXCLUDE_NCT][:N_REGISTRY]
        excluded = [n for n in found if n in EXCLUDE_NCT]
        n_neg = len([n for n in ncts if n in (neg.get("ncts") or [])])
        if not ncts:
            c.note("registry", "NONE",
                   "결과 게시 시험 없음%s"
                   % ("  (라벨 출처 %d건 제외)" % len(excluded) if excluded else ""))
            continue

        recs = [sources.ctgov_results(n) for n in ncts]
        recs = [r for r in recs if not r.get("error") and r.get("abstract")]

        # 대조군이 없는 시험은 효능을 반증할 수 없다. 읽어도 `무관`이 나온다.
        #
        #   실측: 등록부 25건을 읽고 채택 0건이었는데, 전부 단일군·용량증량
        #   시험이었다. LLM 호출만 25번 쓰고 근거는 0이었다.
        #
        #   더 중요한 것은 **기준의 일관성**이다. bench.ceiling은 무작위배정만
        #   '사용 가능'으로 세는데 게이트가 아무거나 읽으면, 측정과 시스템이
        #   다른 것을 보게 된다. 그러면 어느 숫자도 다른 쪽을 설명하지 못한다.
        n_before = len(recs)
        recs = [r for r in recs if _comparative(r)]
        n_single = n_before - len(recs)
        if c.cutoff_year:
            # 시점 차단은 등록부에도 걸어야 한다. 안 그러면 한쪽만 미래를 본다.
            n_all = len(recs)
            recs = [r for r in recs if not r.get("year") or r["year"] <= c.cutoff_year]
            if n_all != len(recs):
                c.note("registry", "CUTOFF",
                       "%d년 이후 %d건 제외" % (c.cutoff_year, n_all - len(recs)))
        if not recs:
            c.note("registry", "NONE",
                   "쓸 수 있는 결과 없음%s"
                   % ("  (단일군·1상 %d건 제외 — 대조 불가)" % n_single
                      if n_single else ""))
            continue

        before = len(c.refute)
        add = factcheck.classify_batch(c.drug, c.disease, recs)
        c.factcheck = (c.factcheck or []) + _stamp(add, "registry")
        _rebuild_evidence(c)
        c.note("registry", "DONE",
               "등록부 %d건(중단 %d) → 반박 +%d · 지지 +%d%s%s"
               % (len(recs), n_neg, len(c.refute) - before,
                  len([r for r in add if r["kept"] and r["direction"] == "support"]),
                  ("  (단일군·1상 %d건 제외)" % n_single) if n_single else "",
                  ("  (라벨 출처 %d건 제외)" % len(excluded)) if excluded else ""))
        v, why = propose_veto(c)
        c.veto, c.veto_reason = v, why
    return st


FT_MAX_PAPERS = 3      # 명세 §6 — 후보당 **최대 3편**
FT_TRY_PAPERS = 6      # 그 3편을 «종류 우선»으로 고르려면 더 많이 떠 봐야 한다


def gate_fulltext(st: RunState) -> RunState:
    """저자가 스스로 적은 한계를 읽고 **근거 가중치를 감쇠한다** (F).

    명세: `사전명세_전문읽기.md`(봉인 `acc3525cd1da…`).
    판정 반영 방식의 근거는 `agents/limits.py` 독스트링에 있다 —
    **새 반박 근거를 만들지 않는다.** 그 논문은 초록으로 이미 목록에
    있으므로, 새 레코드를 넣으면 **같은 논문을 두 번 센다.**

    ## ⛔ 지지·반박 **양쪽**을 대상으로 한다

    지지만 감쇠하면 기각 쪽이 유리해진다 — 그런데 **주지표가 기각
    정밀도**다. 한쪽만 깎는 것은 **지표를 인위적으로 올리는 것**이고,
    명세 §1 이 *"전문을 읽으면 판정이 좋아진다 — 안 주장한다"* 고
    적은 것과도 어긋난다. **반박 논문의 한계도 똑같이 읽는다.**

    ## ⛔ 못 읽은 것을 «한계 없음» 으로 세지 않는다

    PMC 매핑 실패 · 본문 없음 · 절 추출 실패 · LLM 실패는 전부
    **«확인 못 함»** 이다. 감쇠를 안 할 뿐이고, **그 사실을 trail 에
    적는다.** 조용히 넘어가면 «전문을 읽었는데 한계가 없더라» 로
    읽힌다(결함 35 계열).
    """
    from ..io import llm as _llm, fulltext as _ft
    from ..agents import limits as _limits

    if not _llm.available():
        for c in st.candidates:
            if not c.killed:
                c.note("fulltext", "SKIP", "LLM 미설정 — 한계 판정 불가")
        return st

    for c in st.candidates:
        if c.killed:
            c.note("fulltext", "SKIP", "F0 기각")
            continue
        # ⛔ 09-16 · `gate_skeptic` 에는 있는 방어가 **여기 없었다.**
        #   비면 `judge("", "", …)` 가 불려 **약·질환이 빈 프롬프트**로
        #   판정하고, 그 결과로 **가중치를 깎는다.** 벤치는 둘 다 차 있지만
        #   앱 입력·`discover` 경로에서는 빌 수 있다.
        if not c.drug or not c.disease:
            c.note("fulltext", "SKIP", "약물·질환 미지정")
            continue
        recs = [r for r in (c.factcheck or []) if r.get("kept")]
        if not recs:
            c.note("fulltext", "SKIP", "읽을 근거 없음")
            continue

        # ① 가중치 큰 것부터 떠 본다. **지지·반박을 안 가린다.**
        recs.sort(key=lambda r: -(r.get("weight") or 0.0))
        head = recs[:FT_TRY_PAPERS]
        pmids = [str(r["pmid"]) for r in head if r.get("pmid")]
        m = _ft.pmc_ids(pmids)

        got, why = [], {"PMC없음": 0, "조회불가": 0, "본문없음": 0, "절없음": 0}
        why["PMC없음"] = len(m["PMC없음"])
        why["조회불가"] = len(m["조회불가"])
        for p in pmids:
            pmc = m["매핑"].get(p)
            if not pmc:
                continue
            r = _ft.limitations(pmc)
            v = r.get("판정")
            if v == "추출됨":
                got.append({"pmid": p, "pmc": pmc, "종류": r["종류"],
                            "본문": r["본문"]})
            elif v == "본문없음":
                why["본문없음"] += 1
            elif v == "절없음":
                why["절없음"] += 1
            else:
                why["조회불가"] += 1

        if not got:
            c.note("fulltext", "UNKNOWN",
                   "한계를 못 읽었다 — %s. **«한계 없음» 이 아니다**"
                   % " · ".join("%s %d" % (k, v) for k, v in why.items() if v))
            continue

        # ② 명세 §6 — **종류 우선**(한계절 > 한계문단 > 논의뒤), 그다음 상위 3편
        rank = {"한계절": 0, "한계문단": 1, "논의뒤": 2}
        got.sort(key=lambda x: rank.get(x["종류"], 9))
        use = got[:FT_MAX_PAPERS]

        j = _limits.judge(c.drug, c.disease, use)
        if not j.get("ok"):
            c.note("fulltext", "UNKNOWN",
                   "%d편 읽었으나 판정 실패(%s) — **감쇠 안 함**"
                   % (len(use), (j.get("error") or "")[:40]))
            continue

        # ③ 감쇠. **원본을 남긴다**(감사 추적).
        by_pmid = {str(r["pmid"]): r for r in head if r.get("pmid")}
        hit = 0
        for d in j["판정"]:
            rec = by_pmid.get(str(d["pmid"]))
            if rec is None:
                continue
            # ⛔ 09-15 · **판정은 「무관」도 남긴다.** 처음엔 `mult >= 1.0`
            #   이면 `continue` 로 건너뛰어 **기록조차 안 했다.** 그러면
            #   근거만 봐서는 «무관이 몇 건인지» 를 알 수 없고,
            #   **명세 §5 의 반증 조건(«절반 이상 무관»)을 못 잰다.**
            #   84쌍 실측에서 근거에는 「약화」 43건만 남아 **무관이 0으로
            #   보였다** — trail 문자열을 파싱해서야 14% 인 걸 알았다.
            #   ⚠ **가중치는 여전히 안 건드린다.** 기록과 반영은 다른 일이다.
            rec["limits"] = {"effect": d["effect"], "종류": d["종류"],
                             "why": d["why"], "mult": d["mult"]}
            if d["mult"] >= 1.0:
                continue                   # 「무관」·「강화」는 **안 깎는다**
            if "weight_before_limits" not in rec:
                rec["weight_before_limits"] = rec.get("weight")
            rec["weight"] = round((rec.get("weight") or 0.0) * d["mult"], 4)
            hit += 1

        if hit:
            _rebuild_evidence(c)
        eff = {}
        for d in j["판정"]:
            eff[d["effect"]] = eff.get(d["effect"], 0) + 1
        kinds = {}
        for x in use:
            kinds[x["종류"]] = kinds.get(x["종류"], 0) + 1
        c.note("fulltext", "DONE",
               "%d편(%s) → %s · 감쇠 %d건%s"
               % (len(use),
                  " ".join("%s%d" % (k, v) for k, v in kinds.items()),
                  " ".join("%s%d" % (k, v) for k, v in eff.items()) or "판정0",
                  hit,
                  (" · 못읽음 %s" % " ".join("%s%d" % (k, v)
                                            for k, v in why.items() if v))
                  if any(why.values()) else ""))
    return st


def gate_adjudicate(st: RunState) -> RunState:
    """판정 — **선택된 출구 축의 잣대로** 낸다 (제안서 §2.2 · 결함 256).

    앞판은 `adjudicate(c)` 를 인자 없이 불렀고, `scoring` 은 문턱을
    상수로 박고 있었다. 그래서 **`profiles.exit_profile` 을 읽는 곳이
    화면 하나뿐**이었다 — 토글을 바꿔도 판정이 안 움직였다.

    `st.exit_` 기본값이 `"표준"` 이므로 **기존 호출부는 그대로**이고
    동결 수치도 그대로다.
    """
    prof = profiles.exit_profile(getattr(st, "exit_", "표준") or "표준")
    for c in st.candidates:
        n = prepare(c)
        if n:
            _rebuild_evidence(c)
            c.note("dedupe", "DONE", "같은 시험 중복 %d건 제거(NCT 대조)" % n)
        c.verdict, c.confidence, c.reason = adjudicate(c, profile=prof)
        detail = "%s %s" % (c.verdict, c.confidence)
        if prof["이름"] != "표준":
            # **어느 잣대로 낸 판정인지 감사 추적에 남긴다.** 안 남기면
            # 나중에 이 수치를 표준 것과 섞어 본다(결함 234 계열).
            detail += " · 잣대 %s(유망 %d/기각 %d)" % (
                prof["이름"], prof["유망"], prof["기각"])
        c.note("adjudicate", "DONE", detail)
    return st


def gate_discover(st: RunState) -> RunState:
    """발굴 — 질환 목록에서 **후보를 만들어** st.candidates에 넣는다.

    `st.discover` 명세를 읽는다: {diseases: [...], k: int, variant: str, model: str}

    지금까지 후보는 `SEED_CANDIDATES` 5개, 사람이 손으로 쓴 값이었다
    (`state.py` 가 STUB으로 기록해 왔다). 이 게이트가 그 자리를 채운다.

    ## 왜 ORDER 에 넣지 않았는가 — 의도된 것이다

    두 가지 이유가 있고 둘 다 이 프로젝트의 규칙에서 나온다.

    ① **성격이 다르다.** ORDER의 여섯은 후보를 *받아서 거르는* 게이트다.
       이건 후보를 *만든다*. 깔때기 앞이지 안이 아니다.

    ② **동결된 수치를 건드리기 때문이다.** ORDER에 이름을 하나 넣으면
       `run_pipeline` 이 모든 구성에서 후보마다 `SKIP` 기록을 하나씩 더 남긴다.
       trail 이 바뀌면 홀드아웃·사전명세로 봉인한 실행과 대조가 어긋난다.
       **결과를 다시 재야 하는 변경은 지금 하지 않는다** (`CLAUDE.md §3`).

    그래서 호출부가 명시적으로 부른다 — `gate_discover(st)` 후 `run_pipeline(st)`.
    발굴은 껐다 켜는 옵션이 아니라 **다른 실행 모드**다.

    ## 근거를 비워서 넘긴다

    생성된 후보에는 support/refute 를 하나도 넣지 않는다. 생성기가 rationale
    을 적어 주지만 **그건 근거가 아니라 주장이다.** 근거는 게이트가 문헌에서
    읽어 채워야 한다. 생성기의 말을 근거 자리에 넣으면 생성기가 자기 후보를
    변호하게 되고, 깔때기는 그걸 검증하는 척만 한다.
    """
    # ── 입구(축1)를 **표에서 고른다** — 결함 273 ────────────────────
    #
    #   `profiles.ENTRY` 가 08월 초부터 이렇게 적혀 있다 —
    #     "정방향": {"module": "bioreroute.agents.discover", "fn": "propose"}
    #     "역발상": {"module": "bioreroute.agents.reverse",  "fn": "propose"}
    #
    #   **그 표를 읽는 곳이 한 군데도 없었다.** 이 함수는
    #   `discover_agent.propose` 를 **하드코딩**했고, 그래서
    #   「병명으로 시작」 탭은 **역발상을 영영 못 돌렸다.**
    #
    #   `agents/reverse.py` 는 있고 **실측까지 끝났다**(FAERS p=0.0060 ·
    #   SIDER p<0.0001). 독스트링이 *«정방향 `discover.propose` 와 같은
    #   서명·같은 반환»* 이라 적어 뒀다 — **바꿔 끼우라고 만든 것**이다.
    #
    #   그리고 이건 제안서 §2.2 의 간판 주장이 서는 자리다 —
    #   *«역발상과 신종 감염병 긴급 심사처럼 고정형 모델이 허용하지
    #   않던 조합»*. 축2(긴급)는 어제 붙였는데 **축1의 역발상이 없으면
    #   그 조합이 성립을 안 한다.**
    import importlib

    spec = dict(getattr(st, "discover", None) or {})
    entry = spec.get("entry") or "정방향"
    _e = profiles.ENTRY.get(entry) or profiles.ENTRY["정방향"]
    if not _e.get("module"):
        st.log.append("discover: 입구 '%s' 는 발굴을 안 한다" % entry)
        return st
    discover_agent = importlib.import_module(_e["module"])
    _propose = getattr(discover_agent, _e["fn"])
    diseases = list(spec.get("diseases") or [])
    if not diseases:
        st.log.append("discover: 질환 목록이 비어 아무것도 생성하지 않았다")
        return st
    k = int(spec.get("k") or 20)
    variant = spec.get("variant") or "loose"
    # 명세가 모델을 안 주면 **역할 배정**을 쓴다(§3.2). 배정이 비어 있으면
    # `MODEL` 이라 **지금까지와 완전히 같은 동작**이다.
    from ..io import llm as _llm_mod
    model = spec.get("model") or _llm_mod.model_for("discover")

    made, runs = [], []
    for dz in diseases:
        # **정방향은 `variant` 를 받고 역발상은 `source` 를 받는다.**
        #   서명이 같다고 인자까지 같지는 않다 — 그 차이를 여기서 흡수한다.
        if entry == "역발상":
            r = _propose(dz, k=k, model=model,
                         source=spec.get("source") or "faers")
        else:
            r = _propose(dz, k=k, variant=variant, model=model)
        runs.append({"disease": dz, "ok": r["ok"], "n": len(r["items"]),
                     "asked": r["asked"], "variant": variant, "입구": entry,
                     "error": r.get("error"), "cached": r.get("cached")})
        if not r["ok"]:
            st.log.append("discover 실패 [%s]: %s" % (dz, r.get("error")))
            continue
        for it in r["items"]:
            c = Candidate(
                name="%s / %s" % (it["drug"], dz), origin="발굴",
                query="%s AND %s" % (it["drug"], dz),
                drug=it["drug"], disease=dz, pubchem=it["drug"])
            # 생성기의 말은 감사 추적에만 남긴다. 근거(support/refute)는 비운다.
            c.note("discovery", "GEN",
                   "발굴 에이전트가 생성(%s·%s) — 근거는 게이트가 수집한다"
                   % (variant, it.get("evidence_level") or "등급없음"),
                   mechanism=it.get("mechanism"), rationale=it.get("rationale"),
                   evidence_level=it.get("evidence_level"),
                   gen_confidence=it.get("confidence"),
                   provenance=r.get("provenance"))
            made.append(c)

    st.candidates = list(st.candidates) + made
    spec["runs"] = runs
    st.discover = spec
    st.log.append("discover: 질환 %d개 → 후보 %d개 생성(%s, k=%d)"
                  % (len(diseases), len(made), variant, k))
    return st


REGISTRY: Dict[str, Callable[[RunState], RunState]] = {
    "f0": gate_f0,
    "rag": gate_factcheck,
    "registry": gate_registry,
    "hitl": gate_hitl,
    "router": gate_router,
    "s1": gate_s1,
    "s2": gate_s2,
    "skeptic": gate_skeptic,
    "fulltext": gate_fulltext,     # 09-15 · F (`사전명세_전문읽기.md`)
}
# F0(값싼 결정론)를 먼저 통과한 후보에만 팩트체커(비싼 LLM)를 태운다.
# discover 는 여기 없다 — 이유는 gate_discover 독스트링 참조(동결 수치 보호).
# s1 은 라우터 **뒤**다. 구조 경로로 분기된 후보만 타기 때문이다(제안서 §2.5).
# hitl 은 **맨 앞**이다. 사람이 이미 거절한 쌍에 LLM 세 번을 쓸 이유가 없다
# (제안서 §7 — "HITL로 불필요한 호출을 차단해 일 300~500회").
# `fulltext` 는 `skeptic` **뒤**다 — 회의주의자가 반박 근거를 더 모은
# 뒤라야 **그 전체**에 한계 읽기가 적용된다.
ORDER: List[str] = ["hitl", "f0", "rag", "router", "s1", "s2", "skeptic",
                    "fulltext", "registry"]

# ─────────────────────────────────────────────────────────────
# **끄면 흔적도 남기지 않는 게이트**
#
# 보통 게이트는 꺼져 있어도 `SKIP · config off` 를 trail 에 남긴다. 그게
# 기본값인 이유는 "안 돌았다"를 "없었다"로 읽히지 않게 하기 위해서다.
#
# 그런데 **나중에 추가된** 게이트에까지 그 규칙을 적용하면, 이미 봉인해 둔
# 실행 기록과 새 실행의 trail 길이가 어긋난다. 홀드아웃·깔때기·전향 예측이
# 전부 그 trail 로 대조된다. 게이트 하나를 더했다는 이유로 **지금까지 잰
# 모든 수치가 다른 시스템의 수치**가 되는 것이다(`CLAUDE.md §3-2`).
#
# 그래서 s1 은 켠 구성에서만 기록을 남긴다. gate_discover 를 ORDER 에
# 넣지 않은 것과 같은 이유이고, 이쪽은 깔때기 위치가 의미를 가지므로
# ORDER 에는 넣되 기록만 뺐다.
#
# 시험 [45]가 **B0~B6 의 trail 이 s1 추가 전후로 동일한지** 검사한다.
# ⛔ 09-15 · `fulltext` 를 **반드시 여기 넣는다.**
#
#   안 넣으면 B5 를 다시 돌릴 때 trail 에 `fulltext SKIP · config off` 가
#   **하나 더** 생긴다. 판정은 안 바뀌지만 **09-12 궤적(84쌍)과 trail 이
#   어긋나** 두 실행을 나란히 놓을 수 없게 된다. B7 이 `s1` 을 여기 넣은
#   것과 **정확히 같은 이유**다 — 위 CONFIGS 의 B7 주석 참조.
QUIET_WHEN_OFF = {"s1", "hitl", "fulltext"}


def run_pipeline(st: RunState) -> RunState:
    """설정에 따라 게이트를 조립 실행한 뒤 판정한다.

    **최상단에 안전 게이트가 있다**(제안서 §5). 통제 물질 질의는 여기서
    멈추고 `safety_log.jsonl` 에 남는다. 조용히 빈 결과를 내지 않는다 —
    막은 것과 근거가 없는 것은 다르다.
    """
    import time
    from . import safety
    st = safety.gate(st)
    # ── Time-to-Refute 계측 (제안서 §4.1) ────────────────────
    #
    #   > 새 증거를 만드는 속도가 아니라, **이미 존재하는 반증 증거를
    #   > 통합·제시하는 속도**를 실측한다.
    #
    # 게이트별 벽시계 시간을 잰다. 잴 뿐 **판정에 쓰지 않는다** —
    # 빠른 판정이 옳은 판정이 아니다. pLDDT·특허와 같은 규율이다.
    #
    # 캐시가 데워져 있으면 시간이 실제보다 짧게 나온다. 그래서 캐시
    # 적중 여부를 같이 남기지 않으면 이 수치는 거짓말이 된다.
    t0 = time.perf_counter()
    for name in ORDER:
        if st.config.get(name, False):
            s = time.perf_counter()
            st = REGISTRY[name](st)
            st.timing[name] = round(time.perf_counter() - s, 3)
        elif name in QUIET_WHEN_OFF:
            continue                       # 위 QUIET_WHEN_OFF 주석 참조
        else:
            for c in st.candidates:
                c.note(name, "SKIP", "config off")
            st.log.append("gate off: %s" % name)
    st = gate_adjudicate(st)
    st.timing["_전체"] = round(time.perf_counter() - t0, 3)
    st.timing["_후보수"] = len(st.candidates)
    return st


def time_to_refute(st: RunState) -> Dict[str, Any]:
    """§4.1 Time-to-Refute — **반박 근거를 손에 넣기까지** 걸린 시간.

    전체 시간이 아니다. 반박 증거를 실제로 만드는 게이트만 센다
    (팩트체커·회의주의자·등록부). F0·S2 는 근거를 만들지 않는다.

    **캐시가 데워져 있으면 짧게 나온다.** 그래서 `warm` 을 같이 낸다 —
    이걸 빼고 초를 보고하면 "빠르다"가 아니라 "이미 받아 뒀다"이다.
    """
    t = st.timing or {}
    ref = [g for g in ("rag", "skeptic", "registry") if g in t]
    n = max(int(t.get("_후보수") or 0), 1)
    kills = sum(1 for c in st.candidates if c.killed or c.verdict == "기각")
    return {
        "반박근거_수집_초": round(sum(t[g] for g in ref), 2),
        "게이트별": {g: t[g] for g in ref},
        "전체_초": t.get("_전체"),
        "후보당_초": round((t.get("_전체") or 0) / n, 2),
        "기각_건수": kills,
        "warm": _cache_warm(),
        "주의": ("캐시가 데워져 있으면 짧게 나온다. warm 을 같이 보지 않으면 "
                "이 수치는 '빠르다'가 아니라 '이미 받아 뒀다'를 뜻한다."),
    }


def refute_recall(st: RunState) -> Dict[str, Any]:
    """§4.3 B3 확인 항목 — **반박 증거 회수율**.

    제안서 §4.3이 B3(회의주의자)의 확인 대상을 *"반박 증거 회수율"* 로
    정했고, §2가 *"목표가 토론의 양이 아니라 반박 회수율"* 이라고 못 박았다.
    그런데 이 수치를 코드가 낸 적이 없다. 08-06에 넣는다.

    분모를 무엇으로 잡느냐가 이 지표의 전부다. **"반박이 존재하는 후보"를
    우리가 모르므로** 재현율의 참분모를 알 수 없다. 그래서 두 가지를 낸다 —

      회수한_후보_비율 : 반박 근거를 하나라도 얻은 후보 / 전체
      회의주의자_기여  : 회의주의자가 **추가로** 얻은 반박 / 전체 반박

    두 번째가 B3가 실제로 값을 하는지를 본다. 첫 번째는 참분모를 모르므로
    **재현율이라 부르지 않는다.**
    """
    n = len(st.candidates) or 1
    with_ref = sum(1 for c in st.candidates if c.refute)
    total_ref = sum(len(c.refute) for c in st.candidates)
    by_skeptic = 0
    for c in st.candidates:
        for t in c.trail:
            if t.gate == "skeptic" and "반박 +" in (t.detail or ""):
                try:
                    by_skeptic += int((t.detail.split("반박 +")[1]).split()[0])
                except Exception:
                    pass
    return {
        "반박근거_있는_후보": "%d/%d" % (with_ref, n),
        "반박근거_총건": total_ref,
        "회의주의자_추가분": by_skeptic,
        "회의주의자_기여율": (round(by_skeptic / total_ref, 3) if total_ref else None),
        "주의": ("**재현율이 아니다.** 반박이 실제로 존재하는 후보 수를 모르므로 "
                "참분모를 알 수 없다. 회수한 비율과 회의주의자 기여만 낸다."),
    }


def false_negatives(st: RunState, truth: Optional[Dict[str, str]] = None
                    ) -> Dict[str, Any]:
    """§8.2 도입 지표 셋째 — **위음성률. 우리에게 불리한 값이다.**

      > 셋째, **기각한 후보 가운데 사후에 유효로 밝혀진 비율, 즉 위음성률**이다.
      > 이 지표는 시스템에 불리할 수 있는 값이지만,
      > **과도한 기각을 스스로 감시하기 위해 함께 보고한다.**

    `truth` 는 {후보이름: "TP"|"TN"} 다. 없으면 후보에 붙은 라벨을 쓴다.
    라벨이 없으면 **계산하지 않는다** — 0%로 내면 "위음성이 없다"로 읽힌다.
    """
    from ..bench.stats import wilson
    lab = {}
    for c in st.candidates:
        v = (truth or {}).get(c.name) or getattr(c, "label", None)
        if v:
            lab[c.name] = v
    if not lab:
        return {"계산불가": True,
                "왜": "라벨이 없다. **0%로 내지 않는다** — 없는 것과 0은 다르다"}
    killed = [c for c in st.candidates if (c.killed or c.verdict == "기각")
              and c.name in lab]
    fn = [c.name for c in killed if lab[c.name] == "TP"]
    n = len(killed)
    lo, hi = wilson(len(fn), n) if n else (0.0, 0.0)
    return {
        "기각_건수": n,
        "그중_실제_유효": len(fn),
        "위음성률": (round(len(fn) / n, 3) if n else None),
        "95%CI": [round(100 * lo, 1), round(100 * hi, 1)] if n else None,
        "이름": fn,
        "주의": "이 값이 낮다고 좋은 게 아니다 — 아무것도 기각 안 해도 0이 된다",
    }


def _cache_warm() -> Optional[int]:
    try:
        from ..io import cache as _c
        return len(getattr(_c, "_MEM", {}) or {})
    except Exception:
        return None
