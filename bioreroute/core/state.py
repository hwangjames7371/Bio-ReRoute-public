# -*- coding: utf-8 -*-
"""상태 모델 — 파이프라인을 흐르는 자료구조.

설계 원칙
  · 게이트는 (state) -> state 로 동작하고, 자신이 무엇을 했는지 trail에 남긴다.
  · 판정에 쓰인 근거는 출처(curated/llm/pubmed)를 반드시 기록한다.
    W1에서 사람이 정한 값(스텁)과 이후 에이전트가 만든 값을 구분하기 위함이다.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Evidence:
    """지지 또는 반박 근거 한 건."""
    tag: str                       # 근거명 (예: "ACTT-2(Kalil 2021) 양성")
    direction: str                 # "support" | "refute"
    weight: float                  # 로그오즈 가중치
    source: str = "curated"        # curated | llm | pubmed  ← 스텁 여부 추적
    pmid: str = ""
    note: str = ""                 # **초록 원문과 대조해 확인된 구간만** 넣는다
    # 그 `note` 가 **어떻게 확인됐는가** (결함 160).
    #   완전일치 / 부분일치 / 재서술(등록부 표→문장) / 검증 기록 없음
    # 빈 값은 «사람이 매긴 근거»(curated) 라 검증 대상이 아니라는 뜻이다.
    # **화면이 이 값을 안 보이면 「인용 원문」이 실제보다 세게 읽힌다.**
    quote_how: str = ""
    # **어느 게이트가 이 근거를 가져왔는가** (결함 166).
    #   factcheck | skeptic | registry — `source` 와 다르다.
    #   `source` 는 curated/llm 이고 **`scoring.py:140` 이 그 값을 읽는다.**
    #   그래서 안 건드리고 칸을 따로 뒀다. **판정에 안 쓴다.**
    #
    #   화면에 이게 없으면 «회의주의자가 능동적으로 찾아온 반박» 을
    #   보여줄 수가 없다 — 그게 그 게이트를 만든 이유인데도.
    stage: str = ""
    # **반증의 적용 범위** — 제안서 §2.3 이 명시로 요구한 것 (결함 172 곁가지).
    #
    #   > 음성 임상 결과는 특정 **대상군·용량·투여 시점**에 대한 반증이므로,
    #   > 근거 카드는 반박 근거와 함께 **그 조건을 기록**하고 다른 조건으로의
    #   > 일반화는 별도 판단으로 남긴다.
    #
    #   `factcheck` 가 `pico` 를 **08-05부터 수집해 왔는데** 콘솔(`render.py`)
    #   에만 찍히고 **웹 화면에는 없었다.** «기록한다」의 그 화면이 웹이다.
    #   **판정에 안 쓴다** — 표시 전용이다(하드 비토에 쓰는 것은 별개 · 결함 172).
    pico: Dict[str, str] = field(default_factory=dict)


@dataclass
class GateRecord:
    """게이트 1회 실행 기록 (감사 추적)."""
    gate: str
    outcome: str                   # PASS | KILL | FLAG | SKIP | BRANCH | STUB
    detail: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Candidate:
    name: str
    origin: str
    query: str
    drug: str = ""          # 팩트체커가 판정할 가설의 주어
    disease: str = ""       # 팩트체커가 판정할 가설의 대상
    cutoff_year: Optional[int] = None   # 이 연도 이후 문헌은 보지 않는다(시점 차단)
    pubchem: Optional[str] = None

    # ── 게이트가 채우는 영역 ──────────────────────────────
    f0: Dict[str, Any] = field(default_factory=dict)
    f0_entity: Dict[str, Any] = field(default_factory=dict)  # 2겹 F0: 실체 검증
    mech_class: Optional[str] = None
    mech_note: Optional[str] = None
    route: Optional[str] = None            # "structure" | "evidence" | None
    router_rec: Dict[str, Any] = field(default_factory=dict)  # 라우터 원본 판정
    s2: Optional[Dict[str, Any]] = None
    # S1 구조 신뢰도 (제안서 §2.5). **라벨이지 점수가 아니다** —
    # 로그오즈에 들어가지 않는다. io/structure.py 독스트링 참조.
    s1: Optional[Dict[str, Any]] = None
    # HITL 음성 KB 조회 결과 (제안서 §2 세 축 중 셋째).
    hitl: Optional[Dict[str, Any]] = None
    factcheck: List[Dict[str, Any]] = field(default_factory=list)  # L2 판정 원본
    support: List[Evidence] = field(default_factory=list)
    refute: List[Evidence] = field(default_factory=list)
    veto: bool = False
    veto_reason: str = ""

    # ── 최종 판정 ────────────────────────────────────────
    verdict: str = ""
    confidence: Optional[int] = None
    reason: str = ""
    trail: List[GateRecord] = field(default_factory=list)

    def note(self, gate: str, outcome: str, detail: str = "", **prov) -> None:
        self.trail.append(GateRecord(gate, outcome, detail, prov))

    @property
    def killed(self) -> bool:
        """F0에서 기각됐으면 이후 게이트를 태우지 않는다(비용 순서 원칙)."""
        return any(r.outcome == "KILL" for r in self.trail)


@dataclass
class RunState:
    query_title: str
    settings: str
    stamp: str
    candidates: List[Candidate]
    config: Dict[str, bool]
    log: List[str] = field(default_factory=list)
    # 발굴 명세 {diseases, k, variant, model} 와 실행 후 기록 {runs}.
    #   기본값이 있으므로 기존 호출부는 그대로 동작한다 — 동결 수치를 안 건드린다.
    discover: Dict[str, Any] = field(default_factory=dict)
    # Time-to-Refute 계측 (제안서 §4.1). 게이트별 벽시계 초.
    #   **재기만 하고 판정에 쓰지 않는다** — 빠른 판정이 옳은 판정이 아니다.
    timing: Dict[str, Any] = field(default_factory=dict)
    # 축2 · 출구 — **어떤 규제 잣대로 심사하는가** (제안서 §2.2 · 결함 256).
    #   기본값 `"표준"` 이고 **동결 수치는 전부 이 값으로 났다.**
    #   여기 있는 것이 판정 게이트까지 흘러간다 — 앞판은 화면에만 있었다.
    exit_: str = "표준"


# ─────────────────────────────────────────────────────────────
# 후보 시드
#   ※ Phase 2에서 발굴 에이전트(정방향 Swanson + 역발상 SIDER)로 대체된다.
#     현재는 사람이 지정한 값이며, trail에 STUB으로 기록된다.
# ─────────────────────────────────────────────────────────────
SEED_CANDIDATES: List[Dict[str, Any]] = [
    {
        "name": "하이드록시클로로퀸(HCQ)", "drug": "hydroxychloroquine", "disease": "COVID-19", "origin": "정방향",
        "query": "hydroxychloroquine AND COVID-19", "pubchem": "hydroxychloroquine",
        # HCQ는 바이러스 단백질에 직접 결합하지 않는다(엔도솜 pH·ACE2 당화·TLR).
        "mech_class": "숙주 지향(간접·비결합) — 엔도솜 pH·ACE2 당화",
        "mech_note": "바이러스 단백질 직접 결합 아님 → 도킹 무의미",
        "route": "evidence",
        "support": [],
        "refute": [("RECOVERY 2020 RCT 무효", 3.0), ("WHO SOLIDARITY 2021 무효", 3.0),
                   ("QT 연장(hERG) 심장독성", 1.5)],
        "veto": True, "veto_reason": "결정적 반박 RCT + 독성",
    },
    {
        "name": "바리시티닙", "drug": "baricitinib", "disease": "COVID-19", "origin": "정방향",
        "query": "baricitinib AND COVID-19", "pubchem": "baricitinib",
        "mech_class": "직접·숙주(host-directed) — JAK1/2 결합",
        "mech_note": "표적이 숙주 단백질 → 바이러스 도킹 무의미, 면역조절 임상 증거로",
        "route": "evidence",
        "support": [("ACTT-2(Kalil 2021) 양성", 2.0), ("지식그래프 재창출 선례(Richardson 2020)", 0.5)],
        "refute": [], "veto": False, "veto_reason": "",
    },
    {
        "name": "RdRp 억제제(remdesivir 계열)", "drug": "remdesivir", "disease": "COVID-19", "origin": "정방향",
        # 질의는 drug·disease와 일치해야 한다. 분류명으로 검색하면 임상 근거가
        # 안 잡히고, 그 공백을 회의주의자가 메워 제거 실험이 오염된다.
        "query": "remdesivir AND COVID-19", "pubchem": "remdesivir",
        "mech_class": "직접·병원체 표적 — RdRp 활성부위",
        "mech_note": "보존 촉매부위 → 구조 게이트·도킹 타당",
        "route": "structure",
        "support": [("표적 구조 규명(Cryo-EM)", 2.0), ("동계열 승인 선례", 0.5)],
        "refute": [], "veto": False, "veto_reason": "",
    },
    {
        "name": "플루복사민(fluvoxamine)", "drug": "fluvoxamine", "disease": "COVID-19", "origin": "역발상(SIDER 오프타겟)",
        "query": "fluvoxamine AND COVID-19", "pubchem": "fluvoxamine",
        "mech_class": "오프타겟·숙주(면역조절) — S1R/FIASMA",
        "mech_note": "숙주 표적 → 임상·발현 증거로 검증",
        "route": "evidence",
        "support": [("Lenze 2020 JAMA 파일럿", 1.20), ("TOGETHER(Reis 2022) 양성", 1.00)],
        "refute": [("ACTIV-6 무효", 1.00), ("STOP COVID 2 조기중단(futility)", 1.00),
                   ("인지질증 아티팩트 경고(Tummino 2021)", 0.12)],
        "veto": False, "veto_reason": "",
    },
    {
        "name": "[환각 테스트] Fakezolimab-XQ7", "drug": "Fakezolimab-XQ7", "disease": "COVID-19", "origin": "정방향(LLM 가짜 제안 가정)",
        "query": "Fakezolimab-XQ7", "pubchem": None,
        "mech_class": None, "mech_note": None, "route": None,
        "support": [], "refute": [], "veto": False, "veto_reason": "",
    },
]


def build_candidates() -> List[Candidate]:
    out = []
    for s in SEED_CANDIDATES:
        c = Candidate(name=s["name"], origin=s["origin"], query=s["query"],
                      drug=s.get("drug",""), disease=s.get("disease",""), pubchem=s["pubchem"])
        c.mech_class, c.mech_note, c.route = s["mech_class"], s["mech_note"], s["route"]
        c.veto, c.veto_reason = s["veto"], s["veto_reason"]
        c.support = [Evidence(t, "support", w, source="curated") for t, w in s["support"]]
        c.refute = [Evidence(t, "refute", w, source="curated") for t, w in s["refute"]]
        c.note("discovery", "STUB", "후보 목록은 사람이 지정한 값 (Phase 2에서 발굴 에이전트로 대체)")
        out.append(c)
    return out
