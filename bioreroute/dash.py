# -*- coding: utf-8 -*-
"""3분할 대시보드 — 제안서 §6 시연 시나리오

  > **3분할 대시보드**로 구성한다. 좌측은 두 축과 접근성 토글, 중앙은 후보와
  > 근거 카드, 우측은 반증·구조·특허 뷰어다. 시연 무대는 신종 바이러스
  > 아웃브레이크이며, 두 번의 실행으로 두 입구를 각각 보인다.
  >
  > 하단에는 **신뢰도 보정 곡선과 Time-to-Refute 타임라인**을 배치한다.
  > 같은 질의를 **일반 언어모델에 넣은 결과도 나란히** 놓되, 대조 축은
  > **판단 방향이 아니라 검증 가능한 PMID 제시 여부와 신뢰도 보정의 유무**다.

## 이 파일에 gradio 가 없다

`app.py`(UI 얇게) ↔ `dash.py`(내용 만들기) 로 나눈다. 화면을 띄울 수 없는
환경에서 짜고 있으므로 **내용은 시험으로 확인하고 배선만 UI에 남긴다.**
`demo.py` ↔ `app.py` 와 같은 구조다.

## 제안서와 **다르게** 나오는 것 — 숨기지 않는다

제안서 §6 Run 2 는 플루복사민이 **`보류`** 로 판정된다고 썼다.
**실측은 `유망 97%` 다**(결함 39 — 메타분석 4건을 독립 근거로 셈).

무대를 꾸며서 `보류` 로 만들 수 있다. **안 한다.**
실제 출력을 보이고 왜 어긋났는지 근거 카드로 연다 — 감사 추적이 본체라는
주장의 가장 좋은 증명은 **자기 오류를 그대로 보이는 것**이다.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from . import evidence, viewer
import re as _re

from .core import profiles

# ── 제안서 §6 이 지정한 두 실행 ──────────────────────────────
#   Run 1 정방향 : HCQ 기각 · 바리시티닙 생존 · RdRp 유망
#   Run 2 역발상 : 플루복사민을 부작용에서 캐낸다
#
# **병원체 표적은 구운 사례에 없다.** 08-10까지는 이유가 *"라우터가
# 0/27 로 안 보낸다"* 였다. **08-11에 봉인을 열어 그게 아님이 밝혀졌다** —
# 병원체 8쌍이 8/8 structure 로 갔다(`라우터분기결과.md`).
#
# 그러니 지금의 이유는 하나뿐이다 — **이 무대에 병원체 후보를 안 구웠다.**
# 둘은 완전히 다른 말이고, 화면이 낡은 쪽을 말하고 있었다(결함 102).
# 자리를 비워 두는 것이 채워 넣는 것보다 정직하지만, **왜 비었는지는
# 사실대로 적어야 한다.**
RUNS: Dict[str, Dict[str, Any]] = {
    "Run 1 · 정방향": {
        "입구": "정방향",
        # **무대는 §6 이 지정한 대로 바이러스 아웃브레이크다.** 08-11에
        # `rifampin / Tuberculosis` 를 하나 붙였는데, 그건 무대가 아니라
        # **구조 경로 대조군**이다 — 앞의 셋이 전부 숙주·간접이라 S1 이
        # 한 번도 안 돌았다(결함 106). 무대에 섞어 놓고 말 안 하면
        # *"결핵이 왜 바이러스 무대에 있나"* 를 심사위원이 먼저 묻는다.
        "무대": "신종 바이러스 아웃브레이크 — 문헌 연결로 후보를 찾는다 "
              "(+ 구조 경로 대조군 1건)",
        "후보": ["hydroxychloroquine / COVID-19",
               "baricitinib / COVID-19",
               "metformin / Malignant neoplasm of breast",
               "rifampin / Tuberculosis"],
        "제안서가_예상한_것": {
            "hydroxychloroquine / COVID-19": "기각 (RECOVERY·SOLIDARITY 반박)",
            "baricitinib / COVID-19": "유망 (숙주 직접결합 → 도킹 대신 임상 근거)",
        },
        # ── 08-11 갱신 — **봉인이 열렸다** (결함 102) ────────────────
        #   초판은 *"27건 중 0번 · 명세는 봉인돼 있다"* 였다. 08-11에
        #   개봉했고 **병원체 8/8 이 structure 로 갔다.** 화면이 낡은 채로
        #   *"라우터가 안 보낸다"* 고 말하고 있었다 — 결함 87·76 계열이다.
        #
        #   **비워 두는 이유가 바뀌었다.** 라우터가 못 보내는 게 아니라
        #   **이 무대에 병원체 표적 후보를 안 구워 뒀다.** 그 구분을
        #   안 하면 우리 자신의 실험 결과를 화면이 반박한다.
        "빠진_것": ("**COVID-19 병원체 표적**(RdRp·3CL 프로테아제)이 이 무대에 "
                 "없다. 봉인을 열어 확인하니 병원체 8쌍이 **8/8 structure 로 "
                 "갔고**(`라우터분기결과.md` · Fisher p=0.0002) 대조군으로 "
                 "`rifampin / Tuberculosis` 를 붙여 **S1 이 실제로 도는 것**을 "
                 "보인다. 그런데 정작 이 무대의 표적은 아직 못 굽는다 — "
                 "**3CL 프로테아제는 AlphaFold 단편이 그 사슬을 안 덮고**"
                 "(`신뢰도미상`), **뉴라미니다아제는 AFDB 에 아예 없다**"
                 "(404 · `구조없음`). 셋 다 다른 실패이고, 화면이 셋을 "
                 "구분해서 말하는 것이 이 게이트가 하는 일의 전부다."),
    },
    "Run 2 · 역발상": {
        "입구": "역발상",
        "무대": "부작용 데이터에서 거꾸로 — 미녹시딜·실데나필 형",
        "후보": ["fluvoxamine / COVID-19",
               "edaravone / Amyotrophic Lateral Sclerosis"],
        "제안서가_예상한_것": {
            "fluvoxamine / COVID-19": "보류 (지지·반박을 함께 제시해 정직하게 보정)",
        },
        # 09-26 · 결함 344 — 앞판은 «역발상 발굴은 아직 수치가 없다 · 실행 전» 이었다.
        #   실측은 이미 있었다(`역발상결과.md` · FAERS·SIDER 둘 다 사전 기준 통과). 잰 것과 안 잰 것을 가른다.
        "빠진_것": ("역발상 **발굴**은 «문헌이 있는 후보를 무작위보다 많이 내는가» 까지만 쟀다 — "
                 "F0 통과 **82.3%** 대 무작위 64.0% (`역발상결과.md` · Fisher p=0.006). "
                 "**그 후보가 맞는지는 안 쟀고**, 여기 두 후보는 **정방향으로 얻은 것**이다. "
                 "화면이 '역발상으로 찾았다'고 말하지 않는다."),
    },
}


def _cases() -> Dict[str, Dict[str, Any]]:
    d = evidence.cases() or {}
    return {c.get("질의", ""): c for c in (d.get("사례") or [])}


# ── 좌: 2축 + 접근성 (제안서 §2.2) ──────────────────────────
# ── 화면 조각 (08-10) — **결과마다 눈으로 갈리게** ────────────────
#
#   승우: *"각 결과마다 구분을 쉽게 할 수 있게."*
#
#   글자만으로는 `PASS` 와 `UNKNOWN` 과 `CHANGED` 가 같은 무게로 보인다.
#   그런데 **그 셋은 우리 주장에서 하는 일이 전혀 다르다** —
#
#     PASS·DONE   통과했다            (배경)
#     SKIP        일부러 건너뛰었다     (라우터가 도킹을 안 한다 — §2.4 창의성)
#     BRANCH      경로가 갈렸다        (라우터 그 자체)
#     UNKNOWN     **모른다고 답했다**   (심사 10점 "스스로 인지")
#     CHANGED     **스스로 고쳤다**     (심사 10점 "스스로 수정")
#
#   뒤의 셋이 이 시스템이 파는 것이다. 배경과 같은 색이면 안 보인다.
#
#   **색은 뜻이라 고정한다.** 나머지 서식은 gradio 변수를 쓰지만
#   이 칩들은 다크 모드에서도 같은 뜻이어야 한다.
VERDICT_ICON = {"기각": "🔴", "조건부": "🟡", "보류": "⚪", "유망": "🟢"}
_V_COLOR = {
    "기각":   ("#FCEBEB", "#A32D2D"),
    "유망":   ("#EAF3DE", "#3B6D11"),
    "조건부": ("#FAEEDA", "#854F0B"),
    "보류":   ("#F1EFE8", "#5F5E5A"),
}
_GATE_TONE = {
    "INPUT": "muted", "PASS": "ok", "DONE": "ok", "SKIP": "skip",
    "UNKNOWN": "warn", "BRANCH": "branch", "CHANGED": "fix",
}


def verdict_badge(v, conf=None, small=False) -> str:
    """판정 한 조각. **색이 안 나와도 뜻이 남게** 이모지·글자를 같이 싣는다.

    `small=True` 는 **목록용**이다. 제목용 크기(1.02rem)를 목록에 쓰면
    줄마다 «제목» 이 서서 무엇이 중요한지 안 보인다 — 배지가 커서
    부자연스러운 게 아니라 **자리에 안 맞는 크기**였다.
    """
    bg, fg = _V_COLOR.get(v, ("#F1EFE8", "#5F5E5A"))
    tail = ("<span class='br-conf'>%s%%</span>" % conf) if conf is not None else ""
    return ("<span class='br-verdict%s br-v-%s' style='background:%s;color:%s'>"
            "%s %s%s</span>" % (" sm" if small else "", v, bg, fg,
                                VERDICT_ICON.get(v, "·"), v,
                                (" " + tail) if tail else ""))


_WHY = {
    "반박 우세": "반대 근거가 더 무겁습니다",
    "강한 지지": "지지 근거가 뚜렷하고 결정적 반박이 없습니다",
    "근거 엇갈림": "근거가 갈립니다 — 확증 임상이 더 필요합니다",
    # 09-25 · 결함 340 — 보류 사유가 근거 모양을 따른다. «갈립니다» 는 양쪽이 다 있을 때만
    "근거가 약함": "지지 근거가 약합니다 — 판단할 만큼 쌓이지 않았습니다",
    "반박이 약함": "반대 근거가 약합니다 — 기각할 만큼 쌓이지 않았습니다",
    "확증 설계 양방향": "잘 설계된 근거가 양쪽으로 팽팽합니다",
    "증거 없음": "판단할 근거를 못 찾았습니다",
    "F0": "이 약과 질환을 함께 다룬 근거가 없습니다",
    "결정적 반박": "결정적인 반대 임상이 있습니다",
}


def why_plain(reason: str) -> str:
    """판정 사유를 **사람 말 한 줄**로. 원문은 상세에 그대로 남는다.

    앞판은 목록에 «반박 우세 (지지 0건 w=0.00 · 반박 1건 w=1.80)» 을
    그대로 찍었다. `w=1.80` 은 **우리 내부 가중치**이고, 처음 보는
    사람에게는 숫자만 있고 뜻이 없다.

    **원문을 버리지 않는다** — 아래 근거 줄에 저널·PMID·인용이 그대로
    나오고, 가중치는 상세 화면에 있다. 여기서는 «왜» 만 한 줄로 답한다.
    """
    r = str(reason or "")
    for k, v in _WHY.items():
        if k in r:
            return v
    return r.split("·")[0].strip()[:60] or "판정 사유 없음"


def evidence_line(e: dict) -> str:
    """근거 한 건 — **저널·연도·설계 + PMID + 인용 첫 구절.**

    앞판은 «근거 6건» 이라고 **수만** 적었다. 수는 «얼마나» 를 말하지
    «무엇을» 은 안 말한다 — 이 시스템이 파는 것은 그 «무엇» 이다.
    """
    d = "반대" if e.get("방향") == "반박" else "지지"
    tag = str(e.get("설명") or "").strip()
    pmid = e.get("PMID") or ""
    q = (e.get("인용") or "").strip()
    bits = ["<b>%s</b>" % d]
    if tag:
        bits.append(tag)
    if pmid:
        bits.append("PMID %s" % pmid)
    out = "<div class='br-ev'>%s" % " · ".join(bits)
    if q:
        out += "<br><q>%s</q>" % (q[:120] + ("…" if len(q) > 120 else ""))
    return out + "</div>"


class _E:
    """`attenuate_correlated` 가 요구하는 최소 형태 — `.weight` 하나."""
    __slots__ = ("weight",)

    def __init__(self, w):
        self.weight = float(w or 0.0)


def score_ledger(c) -> str:
    """**이 % 가 어떻게 나왔는지 셈을 편다.**

    승우: *«유망 91% 이렇게 알려주는데 왜 그런지 더 자세히»* ·
    *«판단 과정에서 w값등 자세히 클릭한 창 안에서»*

    ## 왜 목록이 아니라 여기인가

    목록은 **답**을 준다 — `w=1.80` 을 거기 두면 처음 보는 사람에게는
    뜻 없는 숫자다(그래서 `why_plain` 이 걷어냈다). 상세는 **누른 사람**이
    보는 곳이고, 누른 사람은 **이유를 물은 사람**이다. 같은 숫자가
    한 층 아래에서는 자산이 된다.

    ## ⚠ 손으로 셈하지 않는다 — `CLAUDE.md §4`

    *«보고하는 통계는 코드에서 나와야 한다. 손계산해서 문서에 옮겨
    적지 마라»* — 결함 19 가 그렇게 났다.

    그래서 **판정이 실제로 쓴 함수**(`attenuate_correlated`·`sigmoid`·
    `CORR_FACTOR`·`LOGIT_CAP`)를 그대로 부른다. 그리고 **재구성이
    화면의 % 와 안 맞으면 셈을 내지 않는다.** 틀린 셈을 그럴듯하게
    보여 주는 것이 아무것도 안 보여 주는 것보다 나쁘다 —
    **안내문이 아니라 구조로 막는다.**
    """
    from .core import scoring as _S
    ev = c.get("근거") or []
    if not ev:
        return ""
    sup = [_E(e.get("가중치")) for e in ev if e.get("방향") != "반박"]
    ref = [_E(e.get("가중치")) for e in ev if e.get("방향") == "반박"]
    # 판정과 **같은 규칙**: LLM 이 회수한 근거가 섞이면 겹침 보정을 건다.
    llm_src = any((e.get("출처") or "") == "llm" for e in ev)
    f = _S.CORR_FACTOR if llm_src else 1.0
    a, b = _S.attenuate_correlated(sup, f), _S.attenuate_correlated(ref, f)
    raw = a - b
    cap = _S.LOGIT_CAP
    logit = max(-cap, min(cap, raw))
    p = int(round(_S.sigmoid(logit) * 100))

    shown = c.get("신뢰도")
    if not isinstance(shown, (int, float)):
        return ""
    # ── 재구성이 화면 값과 어긋나면 **셈을 내지 않는다** ────────
    #   판정 경로에는 거부권·F0·조건부 같은 갈래가 더 있다. 그 갈래를
    #   탄 후보는 이 산수로 설명되지 않는다 — **설명이 안 되는데
    #   설명하는 척하면 그게 심사에서 맞는 자리다.**
    if abs(p - int(shown)) > 1:
        return ("<div class='br-sub'>이 후보는 로그오즈 합만으로 설명되지 "
                "않습니다 — 거부권이나 F0 규칙 같은 다른 갈래를 탔습니다. "
                "아래 단계 표를 보십시오.</div>\n")

    L = ["<div class='br-ledger'>",
         "<div class='br-lrow'><span>지지 %d건</span>"
         "<b class='br-plus'>+%.2f</b></div>" % (len(sup), a),
         "<div class='br-lrow'><span>반대 %d건</span>"
         "<b class='br-minus'>%s%.2f</b></div>"
         % (len(ref), "−" if b else "", b),
         # **음의 0 을 찍지 않는다.** 지지 3.00 − 반대 3.00 이
         #   `%+.2f` 로 «-0.00» 이 됐다(08-19 화면). 0 에는 부호가 없다.
         "<div class='br-lrow br-lsum'><span>합</span><b>%s</b></div>"
         % ("0.00" if abs(raw) < 0.005 else "%+.2f" % raw)]
    if abs(raw) > cap:
        L.append("<div class='br-lrow'><span>상한 ±%.1f 에서 자름</span>"
                 "<b>%+.2f</b></div>" % (cap, logit))
    L.append("<div class='br-lrow br-lend'><span>확률로 바꾸면</span>"
             "<b>%d%%</b></div>" % p)
    L.append("</div>")
    notes = []
    if f < 1.0:
        notes.append("겹치는 근거는 깎습니다 — 메타분석이 개별 임상시험을 "
                     "품고 있으면 같은 환자를 두 번 세게 됩니다. 무거운 "
                     "것부터 세워 두 번째부터 ×%.1f 씩 줄여 더합니다." % f)
    if abs(raw) > cap:
        notes.append("합이 ±%.1f 를 넘어 잘랐습니다. 논문만으로 100%% 는 "
                     "내지 않습니다 — 그런 판정기는 그 자체로 틀렸습니다."
                     % cap)
    for n in notes:
        L.append("<div class='br-sub'>· %s</div>" % n)
    return "\n".join(L) + "\n"


# 감사 기록에 남는 **내부 식별자** → 화면 말. 확인한 것만 넣는다.
#
#   `config off` · `evidence` · `medium` · `loose·clinical` 이 그대로
#   찍히고 있었다. 결함 274 ④(«말투가 논문 같아»)를 고칠 때 **라벨과
#   안내문만 봤고 감사 기록 본문은 안 봤다.** 심사위원이 «config off»
#   를 보면 읽는 것은 게이트가 아니라 **덜 다듬은 화면**이다.
#
#   ⚠ **기록 자체는 안 바꾼다.** 여기는 그리는 자리다 — 원문은
#   `trail` 에 그대로 남아야 재현·감사가 된다. `GATE_KO` 와 같은 원칙.
#
#   ⚠ **확인한 값만 넣는다.** route ∈ {structure, evidence}
#   (`agents/router.py:30-33`) · evidence_level ∈ {clinical, preclinical,
#   mechanistic, speculative} (`agents/discover.py:61`) · variant ∈
#   {strict, loose} (`discover.py:66,72`). 모르는 토큰은 **손대지 않는다** —
#   틀린 번역은 영문보다 나쁘다.
_TRAIL_KO = [
    ("config off", "이 구성에서는 안 씁니다"),
    ("구조 경로 아님 (evidence)", "구조 경로가 아닙니다 — 문헌으로 검증"),
    ("구조 경로 아님 (structure)", "구조 경로가 아닙니다"),
    ("구조 경로 아님 (미분류)", "구조 경로가 아닙니다 — 분류되지 않음"),
    ("→ evidence (", "→ 문헌으로 검증 ("),
    ("→ structure (", "→ 구조로 검증 ("),
    ("(loose·", "(넓게 생성 · "), ("(strict·", "(엄격 생성 · "),
    ("clinical)", "임상 근거)"), ("preclinical)", "전임상 근거)"),
    ("mechanistic)", "기전 근거)"), ("speculative)", "추정)"),
    ("검증 (high)", "검증 (확신 높음)"),
    ("검증 (medium)", "검증 (확신 보통)"),
    ("검증 (low)", "검증 (확신 낮음)"),
    ("F0 기각 — 분류하지 않음", "근거가 없어 기각 — 분류하지 않았습니다"),
    # ⚠ **화면에 파이썬 `None` 이 찍혔다** — 08-19 브라우저에서 발견.
    #   라우터가 갈래를 못 정하면 `route=None` 이고, 기록 서식이
    #   `"%s → %s (%s)"` 라 **«불명 → None (low)»** 로 나온다.
    #   `None` 은 사용자에게 아무 뜻이 없다. **모른다고 적는다.**
    ("불명 → None", "기전도 검증 갈래도 못 정했습니다"),
    ("→ None", "→ 검증 갈래를 못 정했습니다"),
    # ⚠ 09-25 · **파이썬 `True`·`False` 도 찍혔다** — 본선 모델로 다시 구우니 거부권이
    #   발동한 사례가 둘 나왔고, 기록 서식(`gates.py:371·731`)이 bool 을 그대로 쓴다.
    #   «회의주의자 반영 → True» 는 사용자에게 «발동» 이다. **그 두 서식만** 옮긴다.
    ("근거 유도 True", "근거 유도 발동"), ("근거 유도 False", "근거 유도 해제"),
    ("사람 지정 True", "사람 지정 발동"), ("사람 지정 False", "사람 지정 없음"),
    ("반영 → True", "반영 → 발동"), ("반영 → False", "반영 → 해제"),
]

# 확신 등급은 **줄 끝 괄호**로만 온다. 문자열 치환으로 하면 괄호가
#   어긋난다 — 08-19 에 «못 정함 · 확신 낮음)» 이 나왔다(여는 괄호 없음).
_CONF_KO = {"high": "확신 높음", "medium": "확신 보통", "low": "확신 낮음"}
_CONF_RE = _re.compile(r"\((high|medium|low)\)\s*$")


def plain_trail(text: str, table: bool = True) -> str:
    """감사 기록 한 줄을 **화면 말**로. 기록 자체는 안 바꾼다.

    `table=False` 는 **표가 아닌 곳**용이다. `_cell` 이 파이프를 `\\|`
    로 막는데(결함 73) 그건 마크다운 표 안에서만 필요하다. `<div>` 안에
    그대로 두면 **역슬래시가 화면에 보인다** — 실제로 단계 목록에서
    `(1건 중 신규 1 \\| 6건 중 신규 6)` 으로 나왔다.

    **표를 목록으로 바꾸면 이스케이프도 같이 따라와야 한다.**
    한쪽만 옮기면 앞 서식의 흔적이 남는다.
    """
    t = str(text or "")
    for a, b in _TRAIL_KO:
        t = t.replace(a, b)
    t = _CONF_RE.sub(lambda m: "(%s)" % _CONF_KO[m.group(1)], t)
    if not table:
        t = t.replace("\\|", "|")
    return t


def weight_rubric() -> str:
    """무게표 — **코드에서 뽑는다.** 문서에 옮겨 적으면 갈라진다.

    ## 08-19 다시 짬 — 승우: *«맨밑에 설명해준 글이 비율이 안 좋아»*

    앞판은 깔끔한 표 아래에 **배수 열 개를 한 문장에 욱여넣었다.**
    위는 정렬된 격자인데 아래는 글 덩어리라 **같은 종류의 정보가
    두 가지 형태**로 놓였다. 눈이 표에서 흐르다 벽에 부딪힌다.

    배수도 «이름 → 값» 이다. **표여야 할 것이 문장으로 있었다.**
    """
    from .agents import factcheck as _F
    ko = {"meta": "메타분석·체계적 고찰", "rct": "무작위배정 임상시험",
          "trial": "무작위배정 아닌 임상시험", "observational": "관찰연구",
          "review": "서술적 고찰", "in_vitro": "시험관·전임상",
          "case": "증례", "other": "그 밖"}
    # ── 표 둘을 **가로로 세운다** (08-20 승우: «길게 늘리지 말고
    #    한번에 보기 쉽게 가로로») ────────────────────────────
    #
    #   세로로 쌓으면 12행이라 스크롤이 생기고, **둘을 같이 봐야
    #   곱셈이 이해된다**(기본 무게 × 배수). 떨어뜨려 놓으면 눈이
    #   위아래를 오간다.
    #
    #   `markdown="1"` 은 Python-Markdown 이 안쪽을 파싱하게 하는 표시다.
    #   Gradio 는 그 속성을 무시하므로 **양쪽 다 안전하다.**
    L = ["<div class='br-cols' markdown='1'>", "", "<div markdown='1'>",
         "기본 무게는 **연구 설계**로 정합니다.", "",
         "| 연구 설계 | 무게 |", "|---|---:|"]
    for k, v in sorted(_F.WEIGHT_BASE.items(), key=lambda x: -x[1]):
        L.append("| %s | %.1f |" % (ko.get(k, k), v))
    L += ["", "</div>", "", "<div markdown='1'>",
          "여기에 배수를 곱합니다.", "",
          "| 무엇을 보나 | 배수 |", "|---|---|",
          "| 시험 규모 | 큼 ×%.1f · 작음 ×%.1f · 모름 ×%.1f |"
          % (_F.SIZE_MULT["large"], _F.SIZE_MULT["small"],
             _F.SIZE_MULT["unknown"]),
          "| 결정성 — 사전 등록한 1차 평가변수를 결정적으로 만족·기각 "
          "| ×%.1f |" % _F.DECISIVE_MULT,
          "| 판독 확신 | 높음 ×%.1f · 보통 ×%.1f · 낮음 ×%.1f |"
          % (_F.CONF_MULT["high"], _F.CONF_MULT["medium"],
             _F.CONF_MULT["low"]),
          "| GRADE 확실성 | 높음 ×%.1f · 보통 ×%.1f · 낮음 ×%.1f |"
          % (_F.CERTAINTY_MULT["high"], _F.CERTAINTY_MULT["moderate"],
             _F.CERTAINTY_MULT["low"]), "", "</div>", "", "</div>", ""]
    # 보기(곱셈 실례)와 주석은 **두 열 아래 전폭**이다 — 결론이니까
    # 실례 — **손으로 적지 않는다.** `weight_for` 를 그대로 부른다.
    w = _F.weight_for("meta", "unknown", True, "high", "high")
    L += ["<div class='br-ex'>보기 — 규모를 안 밝힌 메타분석이 "
          "1차 평가변수를 결정적으로 만족한 경우<br>"
          "<b>%.1f</b> <span>메타분석</span> × <b>%.1f</b> <span>규모 모름</span>"
          " × <b>%.1f</b> <span>결정적</span> = <b class='br-exw'>%.2f</b></div>"
          % (_F.WEIGHT_BASE["meta"], _F.SIZE_MULT["unknown"],
             _F.DECISIVE_MULT, w), "",
          "<span class='br-sub'>결정성 배수는 확증 설계(%s)에만 줍니다. "
          "관찰연구가 «결정적»이라고 주장해도 올리지 않습니다.</span>"
          % " · ".join(sorted(ko.get(k, k) for k in _F.DECISIVE_OK))]
    return "\n".join(L)


def candidate_names(r) -> list:
    """실행 결과 → 후보 이름 목록. **화면이 고를 수 있게.**"""
    return [c.get("이름", "?") for c in ((r or {}).get("후보") or [])]


def evidence_full(e) -> str:
    """상세용 근거 한 건 — **무게·인용검증·회수단계·조건까지.**"""
    w = e.get("가중치")
    chip = ("<span class='br-w'>%.2f</span>" % w) if isinstance(
        w, (int, float)) else "<span class='br-w'>—</span>"
    head = "%s <b>%s</b>" % (chip, _cell(e.get("설명") or ""))
    L = ["<div class='br-ev br-evx'>%s" % head]
    q = (e.get("인용") or "").strip()
    if q:
        # ⚠ `br-q` 가 **아니다.** 그 이름은 `q_name()`(질의 이름)이
        #   08-10 부터 쓰고 있다 — 같은 이름을 쓰면 **제목이 인용문
        #   서식을 입는다.** 실제로 화면 제목 «COVID-19» 가 46px
        #   들여쓰기된 이탤릭이 됐다(08-19).
        L.append("<div class='br-quo'>%s</div>" % _cell(q[:240]))
    tail = []
    if e.get("PMID"):
        tail.append("PMID %s" % e["PMID"])
    chk = {"완전일치": "인용이 초록과 완전히 일치", "부분일치": "인용이 부분만 일치",
           "불일치": "⚠ 인용이 초록에 없음"}.get(e.get("검증"))
    if chk:
        tail.append(chk)
    stage = {"factcheck": "논문 읽기 단계에서", "skeptic": "반대 근거 더 찾기 단계에서",
             "registry": "임상시험 등록부에서", "curated": "직접 넣은 자료"}.get(
        e.get("회수"))
    if stage:
        tail.append(stage)
    cond = e.get("조건") or {}
    n_cond = 0
    for k, ko in (("population", "대상"), ("dose", "용량"), ("timing", "시점")):
        v = (cond.get(k) or "").strip()
        if v and "not stated" not in v.lower():
            tail.append("%s %s" % (ko, v[:60]))
            n_cond += 1
    # ── 제안서 §2.3 — **반박에 조건이 없으면 그 사실을 적는다** ─────
    #
    #   *«음성 임상 결과는 특정 대상군·용량·투여 시점에 대한 반증»* 이다.
    #   조건 칸이 비었는데 안 보이면 «조건 없는 반박» 이 «모든 조건에서
    #   반박» 으로 읽힌다 — **빈칸이 강한 주장으로 둔갑한다.**
    if not n_cond and e.get("방향") == "반박":
        tail.append("반증 조건을 못 뽑았습니다 — 다른 조건으로 일반화할 수 "
                    "없습니다")
    if tail:
        L.append("<div class='br-sub br-etail'>%s</div>"
                 % _cell(" · ".join(tail)))
    L.append("</div>")
    return "\n".join(L)


def step_list(gates) -> str:
    """게이트 기록 → **단계 목록.** 표가 아니다.

    ## 왜 표를 안 쓰나

    「무엇을 봤나」 한 칸이 실측 **183자**(S2 의 Ro5 경고)다. 표는 열 폭을
    **가장 긴 칸에 맞추므로** 단계·결과가 눌려 찌그러진다. 그리고
    설명 안에 파이프(`|`)가 들어 있으면 **표가 그 자리에서 깨진다** —
    08-19 에 직접 검증 탭이 실제로 그렇게 부서져 있었다
    (`(6건 중 신규 5 | 6건 중 신규 4)`).

    **목록에는 파이프가 아무 뜻이 없다.** 서식을 바꾸는 것이 이스케이프를
    더 거는 것보다 낫다.

    ## 한 군데서만 그린다

    앞판은 「병명으로 시작」과 「직접 검증」이 **각자 그렸다.** 그래서
    한쪽만 고쳐졌고 다른 쪽은 표가 깨진 채로, `config off` 를 찍은 채로
    남아 있었다. **같은 것을 두 곳에서 그리면 반드시 갈라진다.**
    """
    from .demo import GATE_KO as _KO
    # ── **번호를 붙인다** (08-20 승우: «판단 과정 더 보완») ────────
    #
    #   세로선만으로는 «위에서 아래» 가 보이지만 «몇 번째» 는 안 보인다.
    #   시연에서 «네 번째 단계를 보십시오» 라고 말할 자리가 없었다.
    #
    #   ⚠ **안 돌린 단계도 센다.** 건너뛴 것을 빼고 번호를 매기면
    #     화면의 번호와 실제 순서가 어긋난다 — 그건 조용한 거짓말이다.
    out = ["<div class='br-steps'>"]
    n_all = len(gates or [])
    for i, g in enumerate(gates or [], 1):
        desc = plain_trail(
            _re.sub(r"\s*[—·]?\s*제안서\s*§?[\d.\-]*", "",
                    str(g.get("설명") or "")).strip(), table=False)
        res = str(g.get("결과") or "")
        # 안 돌린 단계는 **지우지 않고 낮춘다** — «무엇을 안 했나»도
        #   심사에서는 정보다. 다만 눈이 먼저 갈 자리는 아니다.
        dim = " br-sdim" if res in ("SKIP", "NONE") else ""
        body = plain_trail(_cell(desc), table=False)
        # ── 09-25 · 결함 341 — **별표가 화면에 날것으로 떴다** ────────────
        #   게이트 설명 둘(`structure` 의 «활성부위 주석 없음. 약한 대리물» ·
        #   `gates` 의 ««한계 없음» 이 아니다»)이 마크다운 강조를 달고 오는데,
        #   이 칸은 `<div>` 라 마크다운을 안 거친다. 배포 화면(rifampin)을 한
        #   컷씩 대조하다 봤다. 원문(동결 trail)은 안 고치고 **표시 층에서**
        #   굵게로 바꾼다 — `_cell` 이 파이프를 막는 것과 같은 자리 원칙이다.
        #   짝이 안 맞는 별표는 지운다(화면에 기호를 남기지 않는다).
        body = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", body).replace("**", "")
        if "⚠" in body:
            head, _, warn = body.partition("⚠")
            body = "%s<div class='br-swarn'>⚠ %s</div>" % (head.strip(),
                                                           warn.strip())
        # 마지막 단계(종합 판정)는 **결론이다.** 눈이 거기서 멎게 한다.
        last = " br-slast" if i == n_all else ""
        out.append("<div class='br-step%s%s'><span class='br-sn'>%d</span>"
                   "%s<div class='br-sbody'><b>%s</b>"
                   "<div class='br-sdesc'>%s</div></div></div>"
                   % (dim, last, i, gate_chip(res),
                      _KO.get(str(g.get("게이트") or ""), g.get("게이트")),
                      body))
    out.append("</div>")
    return "\n".join(out)


def route_of(r) -> str:
    """감사 기록에서 **라우터가 실제로 고른 갈래**를 읽는다.

    ## 왜 필요한가 — 08-19 승우: *«aspirin 도 3D 가 나와야 하는 거 아니야?»*

    화면이 **두 말을 하고 있었다.** 단계 표는 «검증 방식 정하기 · UNKNOWN ·
    불명 → None» 인데, 바로 아래 안내문은 **«라우터가 `evidence` 로
    보냈으므로»** 라고 단정했다. 그 문장이 **상수로 박혀 있었기** 때문이다.

    실제로는 **라우터가 기전을 못 정한 것**이고, 그건 «문헌 갈래로
    보냈다» 와 **다른 사실**이다. 제안서 §2.5(«거짓 확신을 만들지 마라»)를
    인용하는 바로 그 문장이 거짓 확신을 만들고 있었다.

    돌려주는 값: `"structure"` · `"evidence"` · `""`(못 정함).

    ## ⚠ **게이트 이름으로 찾지 않는다**

    처음엔 `게이트 == "router"` 로 걸렀는데 **구운 사례에는
    «기전 라우터»** 로 저장돼 있다. 결함 275 와 같은 덫이다 —
    **이름의 집합을 내가 안다고 가정하면 반드시 하나를 빠뜨린다.**

    그래서 **기록 전체에서 표식을 찾는다.** `→ evidence` · `→ structure`
    는 라우터만 쓰는 문구다. 이름이 바뀌어도 안 깨진다.
    """
    for g in (r or {}).get("게이트") or []:
        d = str(g.get("설명") or "")
        if "→ structure" in d:
            return "structure"
        if "→ evidence" in d:
            return "evidence"
    # 라우터 줄을 못 찾았으면 `s1` 이 남긴 «구조 경로 아님 (X)» 를 본다
    for g in (r or {}).get("게이트") or []:
        d = str(g.get("설명") or "")
        if "구조 경로 아님" in d:
            if "(evidence)" in d:
                return "evidence"
            if "(structure)" in d:
                return "structure"
            return ""
    return ""


def route_note(r) -> str:
    """구조 검증을 **왜 안 돌렸는지** — 실제 기록대로 적는다.

    앞판은 *«라우터가 `evidence` 로 보냈으므로»* 를 **상수로 박아** 뒀다.
    실제로 `route=None` 인 후보에도 그렇게 적혔다 — **제안서 §2.5
    («거짓 확신을 만들지 마라»)를 인용하는 그 문장이 거짓 확신이었다.**
    """
    rt = route_of(r)
    if rt == "evidence":
        return ("이 약은 병원체 단백질에 **직접 붙는 방식이 아닙니다.** "
                "몸(숙주) 쪽에 작용하거나 간접 경로라 **구조를 볼 대상이 "
                "없어서** 문헌으로만 검증했습니다 — 건너뛴 것이지 "
                "실패가 아닙니다.")
    if rt == "structure":
        return ("**구조 경로인데 구조 검증이 안 돌았습니다.** "
                "이건 건너뛴 것이 아니라 **못 한 것**입니다 — "
                "표적 주석이나 구조 파일을 못 찾았을 때 이렇게 됩니다.")
    return ("**기전을 못 정했습니다.** 이 약이 병원체에 직접 붙는지 "
            "몸 쪽에 작용하는지 판단하지 못해서 구조 검증도 안 돌렸습니다 — "
            "모르는 것을 안다고 하지 않습니다.")


def candidate_detail(r, name: str) -> str:
    """후보 하나의 **판단 과정 전부** — 단계별 기록 + 근거 전건.

    ## 왜 필요한가

    승우: *«유망 91% 이렇게 알려주는데 왜 그런지 더 자세히 알려주면
    좋을 것 같아. 각각의 약물을 클릭하면 그 과정이 왜 나왔는지»*

    맞다. 목록은 **답**을 주고 여기는 **이유**를 준다. 그리고 목록에서
    «그 밖에 근거 4건» 으로 접어 둔 것도 여기서 다 펴진다.

    **대시보드에 이미 같은 패턴이 있다**(후보 라디오 → 사고 과정).
    구운 사례에만 있고 **라이브에는 없었다** — 심사 30점 항목이
    «사고 과정을 투명하게 보여주는가» 인데 **실제로 돌린 쪽에 그게 없었다.**
    """
    cs = (r or {}).get("후보") or []
    c = next((x for x in cs if x.get("이름") == name), None)
    if not c:
        return ""
    conf = c.get("신뢰도")
    pct = conf if isinstance(conf, int) else (
        int(round(100 * conf)) if isinstance(conf, float) else None)
    # ── 머리 — **상자를 쓰지 않는다** (08-19 승우: «회색 상자 너무 별로») ─
    #
    #   앞판은 연회색 배경 + 왼쪽 보라 띠였다. 그런데 **판정 배지가
    #   이미 색을 갖고 있다.** 색 있는 것 뒤에 회색 판을 깔면 배지가
    #   죽는다 — 상자가 강조를 **더한** 게 아니라 **뺏었다.**
    #
    #   강조는 **활자로** 낸다: 배지(색) → 이름(17px 700) → 사유(13px 회색).
    #   세 줄이 무게순으로 내려가고 아래를 실선으로 닫는다. 승우가
    #   앞서 «보라색 상자만 강조돼 보인다 · 판정 결과를 더 강조해 달라»
    #   고 한 것과 **같은 처방**이다 — 상자를 지우면 내용이 산다.
    L = ["<div class='br-detail'>",
         "<div class='br-dhead'>%s</div>"
         % verdict_badge(c.get("판정") or "?", pct),
         "<div class='br-dname'>%s</div>" % c.get("이름", "?"),
         "<div class='br-dwhy'>%s</div>" % why_plain(c.get("사유")),
         "</div>", ""]

    # ── ① 이 % 가 나온 셈 — **누른 사람이 물은 것이 이것이다** ──
    led = score_ledger(c)
    if led:
        L += ["#### %s%% 는 이렇게 나왔습니다" % pct if pct is not None
              else "#### 이렇게 나왔습니다", "", led, ""]

    # ── 단계별로 무엇을 봤나 ──────────────────────────────────
    gs = c.get("게이트") or []
    if gs:
        L += ["#### 이 판단이 나온 과정", "", step_list(gs), ""]

    # ── 근거 **전건** — 목록에서 접은 것이 여기서 펴진다 ────────
    ev = sorted((c.get("근거") or []), key=lambda e: -(e.get("가중치") or 0))
    sup = [e for e in ev if e.get("방향") != "반박"]
    ref = [e for e in ev if e.get("방향") == "반박"]
    L += ["#### 근거 %d건" % len(ev), ""]
    if not ev:
        L += ["<span class='br-sub'>채택된 근거가 없습니다. "
              "그래서 판단을 보류합니다 — 근거 없이 기각하는 것은 "
              "반증이 아니라 선입견입니다.</span>", ""]
    for title, lst in (("반대 %d건" % len(ref), ref),
                       ("지지 %d건" % len(sup), sup)):
        if not lst:
            continue
        L += ["<div class='br-egrp'>%s</div>" % title]
        L += [evidence_full(e) for e in lst]
        L.append("")
    if ev:
        L += ["<details><summary>왼쪽 숫자를 매기는 법</summary>", "",
              weight_rubric(), "", "</details>", ""]
    return "\n".join(L)


def count_pill(v, n) -> str:
    """«유망 2» 처럼 **판정별 개수**를 색 알약으로. 배지보다 작다.

    앞판은 «판정 분포 — 보류 5 · 기각 2 …» 라는 **통계 표기**였다.
    사용자가 묻는 것은 «쓸 만한 게 있나» 이고, 그 답은 **색**으로 오는 게
    가장 빠르다 — 초록이 몇 개인지 세는 데 글을 읽을 필요가 없다.
    """
    bg, fg = _V_COLOR.get(v, ("#F1EFE8", "#5F5E5A"))
    return ("<span class='br-pill' style='background:%s;color:%s'>%s %s "
            "<b>%d</b></span>" % (bg, fg, VERDICT_ICON.get(v, "·"), v, n))


def gate_chip(v) -> str:
    """게이트 결과. **모르는 것과 고친 것을 통과와 다른 색으로 낸다.**"""
    v = str(v or "")
    return "<span class='br-g br-g-%s'>%s</span>" % (_GATE_TONE.get(v, "muted"), v)


def q_name(q) -> str:
    """식별자 — 약물·질환·PMID·특허번호. **코드가 아니다.**

    앞판은 `` `hydroxychloroquine / COVID-19` `` 였다. 마크다운 코드
    스팬은 *"이건 코드다"* 라는 뜻인데 약 이름은 코드가 아니고,
    화면에서는 **회색 상자**로 보여 표가 통째로 딱딱해진다.

    ## 등폭도 뺐다 (08-10)

    처음엔 등폭을 남겼다 — *"PubMed 에 복사할 문자열이니 글자 구분이
    되는 편이 낫다"* 는 이유였다. 승우가 *"글꼴도 같은 걸로 안 되냐"*
    고 물었고, 다시 보니 **그 이유가 여기서는 약하다** —

      · PMID 는 **숫자만** 이라 `0`/`O` 혼동이 안 생긴다
      · 약물명은 **한 줄에 하나**라 문자 단위로 셀 일이 없다
      · 화면에 15개가 흩어져 있어 **일관성 손해가 더 크다**

    등폭은 `code` 에만 남긴다 — 파일명·함수명은 **그대로 쳐야 하는 것**
    이라 글꼴이 신호가 된다. 여기는 아니다.
    """
    return "<span class='br-q'>%s</span>" % q


def dir_chip(v) -> str:
    """근거 방향. 지지=초록 · 반박=빨강. 행 왼쪽 띠도 이 클래스로 그린다."""
    v = str(v or "")
    return "<span class='br-d br-d-%s'>%s</span>" % (
        "sup" if v == "지지" else ("ref" if v == "반박" else "na"), v or "—")


def left(entry: str = "정방향", exit_: str = "표준",
         drug: Optional[str] = None, s2: Optional[Dict] = None) -> str:
    """축1 입구 · 축2 출구 · 접근성. **세 개가 독립이다.**"""
    try:
        p = profiles.exit_profile(exit_)
    except KeyError:
        return "> 모르는 출구 축: `%s`" % exit_
    acc = profiles.accessibility(drug or "", s2)
    ent = profiles.ENTRY.get(entry, {}).get("설명", "?")

    urgent = (exit_ != "표준")
    lines = [
        "#### 후보를 찾는 방법",
        "**%s** — %s" % (entry, ent), "",
        "#### 심사 기준",
        "**%s**" % exit_,
        "",
        # ── 프로파일이 바꾸는 것을 **전부** 보인다 ─────────────────
        #
        #   08-10 — 시연 대본을 쓰다가 나왔다. 이 표가 문턱 둘만 보여 줘서
        #   *"긴급은 기각 문턱만 낮춘다"* 로 읽힌다. **실제로는 셋이 바뀐다** —
        #   `balance` 0.5→0.35 와 `registry_required` False→True 도 같이 바뀐다.
        #
        #   화면이 일부만 보여 주면 보는 사람은 그게 전부인 줄 안다.
        #   **재는 것과 잰다고 말하는 것이 다른 것**과 같은 층이다.
        #   그리고 감춘 둘이 오히려 우리 논지를 강화한다.
        kv([("유망 문턱", p["유망"], "num"),
            ("기각 문턱", p["기각"], "num"),
            ("조건부 균형", "%.2f" % p["balance"], "num"),
            ("등록부 조회",
             "의무" if p.get("registry_required") else "선택",
             "hot" if p.get("registry_required") else "")]),
    ]
    if urgent:
        lines += [
            "",
            # ⚠ 08-24 · 렌즈 5 8차 — **더 아픈 근거로 바꿨다.**
            #   전에는 «HCQ 임상 206건» 이었다. 그건 «많이 돌렸다» 는
            #   말이라 «문턱을 낮췄다» 의 증거로는 한 단계 약하다.
            #   실제로 무슨 일이 있었나 — **HCQ 의 긴급사용승인(EUA)은
            #   발표된 연구가 «단일 증례 보고 하나» 인 상태에서 났고,
            #   그 뒤 철회됐다.** 그게 «긴급이 문턱을 낮춘다» 의 실물이다.
            "> **긴급이라고 `유망` 문턱을 낮추지 않았다.** 낮춘 것은 `기각` 쪽이다.",
            "> 2020년 HCQ 의 **긴급사용승인은 발표된 연구가 «증례 보고 하나»**",
            "> 인 상태에서 났고 **그 뒤 철회됐다.** 긴급이 낮춘 것은 확신의",
            "> 문턱이었다. **늘어나는 것은 유망이 아니라 보류다.**",
            "",
            "> 그리고 둘이 더 바뀐다 — **조건부 균형이 0.35 로 내려가** 근거가",
            "> 갈릴 때 더 쉽게 `조건부` 로 가고, **등록부 조회가 의무**가 된다.",
            "> **긴급할수록 실패한 임상을 더 봐야 한다.** 덜 보는 게 아니다.",
        ]
    lines += ["", "#### 접근성 (LMIC)",
              "<p class='br-kvn'>위 두 축과 <b>독립</b>이다 — "
              "효능 판정에 섞지 않는다</p>", ""]
    lines.append(kv([("WHO 필수의약품",) + _tri2(acc["eml"]),
                     ("경구 가능성 (Ro5)",) + _tri2(acc["oral_ok"]),
                     ("저분자",) + _tri2(acc.get("small_molecule"))]))
    lines += ["", "> %s" % acc["note"]]
    return "\n".join(lines)


def disease_run_parts(r: Dict[str, Any], show: int = 3,
                      acc_on: bool = False):
    """병명 실행 결과 → (후보 목록, 그 뒤). 명세 `사전명세_병명입구.md`.

    ## 왜 둘로 쪼개나 (08-19)

    사이에 **후보를 고르는 칸**이 들어간다. 한 덩어리로 그리면 그 칸이
    본문 전체 뒤로 밀려 — 실제로 **페이지 맨 아래**에 있었다.

    원래 독스트링: 명세 `사전명세_병명입구.md` · 봉인 `78e44afa1b3b`.

    ## 「Top-3」는 **표시 순서이지 절단이 아니다**

    제안서 원문에 Top-3 **절단 기준이 없다**(그림에만 있다). 기준을 우리가
    정하면 그게 자유도가 되므로 **자르지 않는다** — F0 통과분을 전부 태우고
    여기서 상위 `show` 개를 먼저 편다. 나머지는 **접되 수와 판정은 적는다.**

    ## 판정 문구를 상수로 안 적는다 (`CLAUDE.md §4`)

    결함 209·212·213 이 세 번 재발한 자리다. 여기서는 **방향을 데이터에서
    읽는다** — 판정 종류가 몇이고 무엇인지 세어서 그대로 적는다.
    """
    if not r.get("ok"):
        # ⚠ **모든 return 이 2튜플이어야 한다.** 08-19 에 이 한 줄을
        #   안 고쳐 `too many values to unpack` 이 났다 — 반환 형태를
        #   바꾸면 **이른 반환 경로까지 세어야 한다.**
        return "\n".join(["#### 병명 입구", "",
                          "**%s** — %s" % (r.get("상태", "?"),
                                           r.get("메시지", "")),
                          "", "> **«없다» 가 아니라 «못 했다» 다.**"]), ""
    cs = r.get("후보") or []
    # ── **후보가 먼저다** (결함 274) ─────────────────────────────
    #
    #   앞판은 «요청·생성·F0통과·깔때기·걸린 시간·캐시·일꾼·답한 모델»
    #   이라는 **계기판**을 맨 위에 놓고, 사용자가 실제로 보러 온
    #   **후보 목록을 한참 아래**에 뒀다.
    #
    #   승우: *«후보물질이 제일 중요한데 시간을 먼저 알려주니 잘못된 것
    #   같아»*. 맞다 — **파이프라인이 얼마나 걸렸나는 만든 사람의 관심사**이고
    #   쓰는 사람의 관심사가 아니다. 계기판은 **후보 뒤로 보내고 접는다.**
    #   지우지는 않는다 — 심사에서는 그게 «사고 과정» 이다.
    L = ["### %s" % q_name(r.get("질환", "")), ""]

    # 판정 분포 — **방향을 데이터에서 읽는다.** 문구를 안 박는다
    from collections import Counter as _C
    dist = _C(c.get("판정") or "?" for c in cs)
    if dist:
        # **제목 바로 밑에서 «무엇을 찾았나» 를 말한다.**
        #   앞판은 «판정 분포 — 보류 5 · 기각 2 …» 였다. 그건 통계 표기이지
        #   사용자가 궁금한 문장이 아니다. 사용자는 «쓸 만한 게 있나» 를 묻는다.
        _ORD = ["유망", "조건부", "보류", "기각"]
        _bits = [(k, dist[k]) for k in _ORD if dist.get(k)]
        _bits += [(k, v) for k, v in dist.items() if k not in _ORD]
        L += ["후보 %d개를 찾아 검증했습니다" % len(cs), "",
              " ".join(count_pill(k, v) for k, v in _bits), ""]
        if len(dist) == 1:
            L += ["> 판정이 한 종류뿐입니다. 후보별로 안 갈렸다는 뜻이라, "
                  "이 실행은 검증 단계가 일한 증거가 못 됩니다.", ""]

    # ⚠ **정렬 기준을 화면에 같이 보인다** — 결함 247.
    #   «정렬은 F0 근거 수» 라 적으면서 옆에는 **최종 근거 수**를 찍었다.
    #   둘이 달라서 08-18 실측이 «1건 · 0건 · 6건» 순으로 보였고,
    #   **화면이 자기 정렬을 설명 못 했다.** 명세(`78e44afa1b3b`)가 정렬
    #   기준을 봉인했으므로 **정렬은 안 바꾸고 그 값을 옆에 적는다.**
    # ── 후보 — **판정 배지를 쓴다** ────────────────────────────
    #   앞판은 «1. **이름** — `기각` · 근거 1건» 이라는 밋밋한 번호 목록이었다.
    #   같은 화면의 「직접 검증」은 `verdict_badge()` 로 색 배지를 쓰는데
    #   **여기만 안 썼다.** 사용자가 제일 먼저 볼 것이 판정인데
    #   회색 코드 스팬으로 찍혀 있었다.
    #
    #   정렬 설명(F0 근거 수)은 **접어서 뒤로** 보낸다 — 만든 사람의 규약이지
    #   보는 사람의 정보가 아니다. 지우지는 않는다(명세가 봉인한 규칙이다).
    _has_f0 = any(c.get("F0근거수") is not None for c in cs)
    L += [""]
    for c in cs[:show]:
        conf = c.get("신뢰도")
        pct = conf if isinstance(conf, int) else (
            int(round(100 * conf)) if isinstance(conf, float) else None)
        L.append("<div class='br-cand'>%s <b>%s</b></div>"
                 % (verdict_badge(c.get("판정") or "?", pct, small=True),
                    c.get("이름", "?")))
        L.append("<div class='br-ev'>%s</div>" % why_plain(c.get("사유")))
        # **개수 대신 근거를 보인다** — 가장 무거운 두 건
        ev = sorted((c.get("근거") or []),
                    key=lambda e: -(e.get("가중치") or 0))[:2]
        L += [evidence_line(e) for e in ev]
        n = c.get("근거수", 0)
        if n > len(ev):
            L.append("<div class='br-ev'>그 밖에 근거 %d건</div>"
                     % (n - len(ev)))
        elif not ev and not n:
            L.append("<div class='br-ev'>채택된 근거 없음</div>")
        L.append("")
    if len(cs) > show:
        # ⚠ **보장 문구를 조건부로 두면 안 된다.** 방금 그렇게 만들 뻔했다 —
        #   «아무것도 안 버린다» 를 F0 자료가 있을 때만 적으면, 자료가
        #   없는 실행에서는 **그 약속이 화면에서 사라진다.**
        #   요약(summary)에 넣으면 접혀 있어도 늘 보인다.
        L += ["<details><summary>나머지 %d개 보기 — 아무 후보도 "
              "버리지 않았습니다</summary>" % (len(cs) - show), ""]
        for c in cs[show:]:
            conf = c.get("신뢰도")
            pct = conf if isinstance(conf, int) else (
                int(round(100 * conf)) if isinstance(conf, float) else None)
            L.append("<div class='br-cand'>%s <b>%s</b> "
                     "<span class='br-sub'>· 근거 %d건</span></div>"
                     % (verdict_badge(c.get("판정") or "?", pct, small=True),
                        c.get("이름", "?"), c.get("근거수", 0)))
            L.append("")
        L += ["</details>"]
    if _has_f0:
        L += ["", "<details><summary>후보를 어떤 순서로 보여주나</summary>", "",
              "F0(첫 단계에서 센 근거 수)가 많은 순입니다. 옆에 적힌 "
              "«근거 N건»은 검증을 다 마친 뒤의 수라 순서와 다를 수 "
              "있습니다. 위 셋만 먼저 펼쳐 둘 뿐, 버리는 후보는 없습니다.",
              "", "</details>"]
    L.append(_SPLIT_AT)          # ← 여기에 «후보 고르기» 가 들어간다

    # ── 여기서부터가 **계기판** — 접어서 뒤로 보낸다 ──────────────
    M = []
    # ── **깔때기를 한 번에 보이게** (08-20 승우) ──────────────
    #
    #   *«이 검색이 어떻게 돌았나 이 페이지도 한번에 볼 수 있게»*
    #
    #   앞판은 «요청 → 생성 → 통과 → 태움» 을 **세로 표 네 줄**로 냈다.
    #   그런데 이 넷은 **줄어드는 깔때기**다 — 세로로 읽으면 «네 개의
    #   숫자» 지만 가로로 놓으면 **«어디서 얼마나 줄었나»** 가 보인다.
    #   제안서 §6 이 깔때기라고 부른 그것이 화면에서 깔때기가 아니었다.
    def _stat(k, v, u=""):
        return ("<div class='br-stat'><span class='k'>%s</span>"
                "<span class='v'>%s<span class='u'>%s</span></span></div>"
                % (_cell(k), v, u))

    M += ["", "<div class='br-stats'>",
          _stat("요청한 후보", r.get("요청", 0), "개"),
          _stat("실제로 만든 후보", r.get("생성", 0), "개"),
          _stat("1단계 통과", r.get("F0통과", 0), "개"),
          _stat("끝까지 검증", r.get("태움", 0), "개"),
          _stat("전체 시간", "%.1f" % r.get("초", 0.0), "초"),
          "</div>", ""]
    M += ["| | |", "|---|---|"]
    if r.get("못태움"):
        # **«안 태운 것」과 «떨어진 것」을 가른다** (결함 141·149)
        #   그리고 **이름을 적는다.** 병렬로 태우면 «뒤에서 몇 개» 가
        #   아니라 «이것과 이것» 이라 개수만으로는 어느 것인지 모른다.
        _un = r.get("못태운후보") or []
        M.append("| 시간이 모자라 못 본 후보 | %d개 (상한 %.0f초) — "
                 "탈락이 아닙니다%s |"
                 % (r["못태움"], r.get("상한", 0),
                    (" — " + ", ".join(_un[:5])
                     + ("…" if len(_un) > 5 else "")) if _un else ""))
    # `warm` 은 **캐시에 든 항목 수**(int) 이거나 `None`(모름) 이다.
    #   bool 로 읽으면 0 과 None 이 같아진다 — «비었다» 와 «모른다» 는
    #   다르다(결함 89). 셋을 다 다르게 적는다.
    w = r.get("warm")
    M.append("| 미리 받아 둔 자료 | %s |"
             % ("**%s건 데워짐** — 이 초는 «빠르다» 가 아닙니다"
                % "{:,}".format(w) if isinstance(w, int) and w > 0
                else "**없음** — 이 초는 실제로 조회한 시간입니다" if w == 0
                else "**모름**"))
    if r.get("깔때기초"):
        M.append("| 그중 검증에 쓴 시간 | %.1f초 |" % r["깔때기초"])
    if r.get("일꾼"):
        M.append("| 동시에 처리한 수 | %d개 — 판정은 달라지지 않습니다 |"
                 % r["일꾼"])
    # **누가 답했나** — `FALLBACKS` 로 넘어가면 같은 프롬프트에 다른 답이
    #   오고 그건 판정을 흔든다(결함 234). 하나면 조용히, 둘이면 경고.
    _m = r.get("모델") or {}
    if _m:
        # 08-20 — 꼴이 `{모델: {"새로": n, "캐시": m}}` 로 바뀌었다.
        #   옛 꼴(`{모델: n}`)도 그대로 읽는다 — 구운 사례가 옛 꼴이다.
        M.append("| 사용한 모델 | %s |" % " · ".join(model_line(_m)))
        if len(_m) > 1:
            L += ["", "> ⚠ **모델이 둘 이상이 답했다.** 429 로 예비 모델을 "
                  "탔을 수 있다.", "> 같은 프롬프트라도 모델이 다르면 답이 "
                  "다르므로, 이 실행을 다른 실행과 **나란히 놓지 마라.**"]
    if isinstance(w, int) and w > 0:
        L += ["", "> ⚠ **캐시가 데워져 있다.** 이 초는 «빠르다» 가 아니라",
              "> **«이미 받아 뒀다»** 다 (§4.1 Time-to-Refute 규약)."]
    # ── 시간이 **어디로 갔나** — 합이 아니라 중앙값을 적는다 ────────
    #   합을 적으면 후보 수에 비례해 커져서 «어느 게이트가 느린가» 를
    #   못 읽는다. 병렬이면 합 ≠ 벽시계라 더 그렇다.
    _gs = r.get("게이트초") or {}
    if _gs:
        _rank = sorted(_gs.items(), key=lambda kv: -kv[1].get("중앙", 0))
        # 중첩 `<details>` 를 안 만든다 — 진단서 ③ «중첩 두 겹까지».
        #   이 표는 아래 「이 검색이 어떻게 돌았나」 안에 **평범한 표**로 들어간다.
        # ── 표가 아니라 **막대** (08-20 승우: «밑에 배치하지 말고
        #    한번에 볼 수 있게 가로에») ──────────────────────────
        #
        #   숫자 세 열을 읽고 «어느 단계가 오래 걸렸나» 를 머릿속에서
        #   비교하게 하지 않는다. **길이로 보이면 한 번에 온다.**
        from .demo import GATE_KO as _KO
        _mx = max((v.get("중앙", 0) for _, v in _rank), default=0) or 1.0
        M += ["", "**후보 하나에 걸린 시간** — 단계별 중앙값", "",
              "<div class='br-times'>"]
        for g, v in _rank:
            _md_ = v.get("중앙", 0)
            M.append("<div class='br-trow'><div class='br-thead'>"
                     "<span class='br-tn'>%s <span class='br-tc'>%d건</span>"
                     "</span><b class='br-tv'>%s</b></div>"
                     "<span class='br-tb'><i style='width:%.1f%%'></i></span>"
                     "</div>"
                     % (_cell(_KO.get(g, g)), v.get("n", 0), secs(_md_),
                        100.0 * _md_ / _mx))
        M.append("</div>")
        M += ["", "<span class='br-sub'>전체 %.1f초와 합이 안 맞는 것이 "
                  "정상입니다 — %d개를 동시에 처리했습니다.</span>"
              % (r.get("초", 0.0), r.get("일꾼", 1))]
    # ── F0 가 무엇을 거르는지 화면이 정확히 말한다 ──────────────────
    #
    #   ⚠ 08-15 전수 검증에서 **내가 틀린 것을 찾았다.**
    #   여기 «F0 는 PubMed 에 문헌이 있나를 본다» 라고 적었는데
    #   `gate_f0` 독스트링은 그게 아니라고 말한다 —
    #
    #       1겹 실체 검증  그 **약물**이 문헌에 존재하는가   ← 여기서만 기각
    #       2겹 연결 근거  그 **쌍**에 문헌이 있는가
    #                      → **0건이어도 기각이 아니라 보류다**
    #                      («연결 문헌 0건은 오히려 신규성 신호다»)
    #
    #   즉 F0 는 **환각 약물을 거르는 게이트**다. 생성기가 실재하는 약을
    #   내면 **100% 통과가 정상**이고, 그게 F0 가 고장난 것이 아니다.
    #
    #   **재는 것과 잰다고 말하는 것이 달랐다** — `CLAUDE.md §4` 의 그 자리.
    _g, _f0 = r.get("생성", 0), r.get("F0통과", 0)
    if _g and _f0 == _g:
        # **경고를 본문에서 빼고 「알아 둘 것」으로 접는다.**
        #   앞판은 ⚠ 와 굵은 글씨가 섞인 네 줄이 후보 목록 바로 밑에
        #   있었다. 사용자가 결과를 보러 왔는데 **설명이 결과를 밀어냈다.**
        L += ["", "<details><summary>알아 둘 것 — 첫 단계에서 거른 후보가 "
                  "없습니다</summary>", "",
              "첫 단계는 «이 약이 실제로 있는 약인가»를 봅니다. 후보를 "
              "만드는 쪽이 실재하는 약만 내놓기 때문에 이 단계에서는 "
              "거의 걸리지 않습니다(%d개 중 %d개 통과). 거르는 일은 "
              "뒤 단계가 합니다." % (_g, _f0), "",
              "약과 질환을 함께 다룬 논문이 0건이어도 탈락시키지 않습니다 — "
              "아직 아무도 안 본 조합일 수 있어서입니다.", "", "</details>"]

    L += ["", "<details><summary>이 검색이 어떻게 돌았나 — "
          "단계별 기록과 걸린 시간</summary>", ""] + M + ["", "</details>"]

    # ── 접근성 토글 (제안서 §6 좌측) — 결함 134 로 ❌ 였던 칸 ─────────
    #    **읽기전용 표시가 아니라 실제 컨트롤**이다. 다만 **판정에 안 넣는다** —
    #    LMIC 접근성은 «그 약이 그 병에 듣는가» 의 참거짓을 안 바꾼다.
    if acc_on:
        L += ["", "#### 접근성 (LMIC) — **켜짐.** 두 축과 독립이고 "
              "**판정에 안 들어간다**", "",
              "| 후보 | WHO 필수 | 경구(Ro5) | 저분자 |", "|---|---|---|---|"]
        for c in cs[:show]:
            a = profiles.accessibility(c.get("약물") or "", None)
            L.append("| %s | %s | %s | %s |"
                     % (c.get("약물") or c.get("이름", "?"), _tri(a["eml"]),
                        _tri(a["oral_ok"]), _tri(a.get("small_molecule"))))
        L += ["", "> 신호가 거칠다 — 가격·공급망·규제 승인은 **안 본다.**"]
    L += ["", "<span class='br-sub'>이 후보는 AI 가 제안한 것입니다. "
          "저희 측정에서 이렇게 제안된 후보의 23.5%는 그 질환에 이미 "
          "승인된 약이었습니다(무작위로 고를 때의 22배). "
          "새로운 발견이라기보다 <b>이미 알려진 것을 다시 정리한 결과</b>로 "
          "읽으시는 편이 안전합니다.</span>"]
    if _SPLIT_AT in L:
        i = L.index(_SPLIT_AT)
        return "\n".join(L[:i]), "\n".join(L[i + 1:])
    return "\n".join(L), ""


# 후보 목록과 계기판 사이 표식. **후보를 고르는 칸이 여기 들어간다.**
#
#   08-19 브라우저: 후보 목록은 위인데 **고르는 칸이 페이지 맨 아래**였다.
#   목록에서 스무 줄을 내려가 누르고, 상세를 보려고 또 내려가야 했다.
#   **«고르는 것» 은 «고를 대상» 옆에 있어야 한다.**
_SPLIT_AT = "\u0000SPLIT\u0000"


def disease_run(r: Dict[str, Any], show: int = 3, acc_on: bool = False) -> str:
    """한 덩어리로 — **앞판과 같은 것을 돌려준다.** 시험·문서가 이걸 쓴다."""
    a, b = disease_run_parts(r, show=show, acc_on=acc_on)
    return a + ("\n" + b if b else "")


def _tri(v) -> str:
    """**True/False/모름 을 셋으로 적는다.** 모르는 것을 False 로 쓰면 거짓말이다."""
    if v is True:
        return "예"
    if v is False:
        return "아니오"
    return "**모름**"


def _tri2(v):
    """`_tri` 의 **`kv` 판** — (값, 색) 두 개로 돌려준다.

    표가 아니라 줄이므로 `**모름**` 이라는 마크다운을 쓸 수 없다.
    강조는 색이 맡고, **셋을 구분한다는 요건은 그대로다.**
    """
    if v is True:
        return ("예", "yes")
    if v is False:
        return ("아니오", "no")
    return ("모름", "unk")


def kv(rows) -> str:
    """«이름 — 값» 을 **표가 아니라 줄로** 적는다 (08-21).

    ## 왜 표를 뺐나

    3분할 좌측은 실측 **146px** 다. 거기에 2열 마크다운 표를 넣었더니
    **한 줄이 112px** 이 됐다 — 이름 칸이 «조/건/부/균/형» 으로 접혀서다.
    4행 표 하나가 **450px**, 좌측 전체가 1,060px 이었다.

    앞서 결함 265 에서 «5열 가로 표 → 2열 세로 표» 로 한 번 고쳤고,
    08-20 에는 잘림을 막으려고 이름 칸의 `nowrap` 까지 풀었다.
    **두 번 다 표를 지키면서 고치려 했다.** 그게 틀렸다 —

    > 표는 **행끼리 비교**하려고 쓴다. 여기 있는 건 문턱 넷·신호 셋,
    > 서로 비교할 것이 없는 **제원표**다. 비교하지 않는 것을 표에 넣으면
    > 열 정렬 비용만 내고 얻는 게 없다.

    줄로 적으면 이름과 값이 각각 `nowrap` 이라 **글자 단위로 안 쪼개지고**,
    폭이 모자라면 값이 다음 줄로 통째로 내려간다. 한 줄 26px 이다.

    `rows` 는 `(이름, 값)` 또는 `(이름, 값, 색)`. 색은 `num`·`hot`·
    `yes`·`no`·`unk` 다. **`모름` 은 반드시 `unk`** — 모르는 것이
    아는 것처럼 보이면 그게 이 프로젝트가 막으려는 바로 그것이다.
    """
    out = ["<div class='br-kv'>"]
    for row in rows:
        name, val = row[0], row[1]
        tone = row[2] if len(row) > 2 else ""
        out.append("<div class='br-kvr%s'><span>%s</span><b>%s</b></div>"
                   % ((" " + tone) if tone else "", _cell(name), _cell(val)))
    out.append("</div>")
    return "\n".join(out)


# ── 중: 후보 + 근거 카드 ────────────────────────────────────
def _by_profile(verdict: Optional[str], p: Optional[int], exit_: str) -> str:
    """이 잣대였다면 판정이 어떻게 되나 — **다시 안 돌리고 문턱만 다시 댄다.**

    구운 사례는 **표준으로 계산돼 봉인돼 있다.** 여기서 다시 돌리면
    LLM 호출이 들고 동결 수치가 흔들린다. 그래서 **저장된 확률에
    문턱만 다시 대고**, 달라지면 그 사실을 적는다(결함 256).

    ⚠ **`조건부` 는 건드리지 않는다.** 그건 `contested()` 가 문턱보다
      **먼저** 갈라 낸 판정이라 문턱과 무관하다. 여기서 문턱을 대면
      «조건이 갈렸다» 를 «보류» 로 바꿔 버린다 — 정보를 버리는 것이다.
    """
    if exit_ == "표준" or p is None or verdict in (None, "", "조건부"):
        return ""
    try:
        prof = profiles.exit_profile(exit_)
    except KeyError:
        return ""
    t = "유망" if p >= prof["유망"] else ("보류" if p >= prof["기각"] else "기각")
    if t == verdict:
        return ""
    return " → **%s에선 %s**" % (exit_, t)


def _cases_raw():
    """`demo_cases.json` **원본** — `_cases()` 는 「사례」만 돌려준다.
    «구운 시각» 같은 머리말 값을 읽으려면 원본이 필요하다."""
    try:
        from . import evidence as _ev
        return _ev.cases() or {}
    except Exception:
        return {}


def center(run: str, exit_: str = "표준") -> str:
    r = RUNS.get(run)
    if not r:
        return "> 모르는 실행: `%s`" % run
    cs = _cases()
    # ── **언제 구운 값인지 적는다** (결함 270) ────────────────────
    #   08-18 실측 — 08-14 에 구운 6쌍 중 **2쌍의 판정이 오늘 라이브와
    #   다르다**(`edaravone` 조건부 28% → 유망 90%). 화면 두 곳이 같은
    #   쌍에 다른 말을 하는데 **어느 쪽이 언제 것인지 아무 데도 안 적혀
    #   있었다.** 심사위원이 대시보드를 보고 라이브를 돌리면 그대로 부딪친다.
    stamp = (_cases_raw() or {}).get("구운 시각") or ""
    out = ["### %s" % run, "*%s*" % r["무대"], ""]
    if stamp:
        out += ["> **%s 에 구운 값이다.**  문헌은 계속 늘고 판정은 그에 따라 "
                "움직인다 — 「직접 검증」에서 같은 쌍을 지금 돌리면 **다를 수 "
                "있다.** 이전에 구운 판으로 쟀을 때 6쌍 중 2쌍이 그랬다." % stamp[:10], ""]
    if not cs:
        out.append("> `demo_cases.json` 이 없다. "
                   "`py -c \"from bioreroute import evidence; evidence.build_cases()\"`")
        return "\n".join(out)

    out += ["| 후보 | 판정 | 근거 | 우리가 미리 적은 예상 |", "|---|---|---|---|"]
    moved = 0
    for q in r["후보"]:
        c = cs.get(q)
        if not c:
            out.append("| %s | — | — | **구운 사례에 없음** |" % q)
            continue
        exp = r["제안서가_예상한_것"].get(q, "—")
        mark = ""
        if exp != "—" and c.get("판정") and c["판정"] not in exp:
            mark = " ⚠"
        shift = _by_profile(c.get("판정"), c.get("신뢰도"), exit_)
        if shift:
            moved += 1
        out.append("| %s | %s%s%s | %d건 | %s |"
                   % (q_name(q), verdict_badge(c.get("판정"), c.get("신뢰도")),
                      mark, shift, len(c.get("근거") or []), exp))

    out += ["", "> ⚠ 는 **우리가 미리 적은 예상과 실측이 다른 것**이다. 꾸며 맞추지 않았다."]
    if exit_ != "표준":
        # **여기 있는 판정은 표준으로 계산된 값이다.** 그걸 안 적으면
        # 화면이 «기각 문턱 25» 와 «기각 26%» 를 나란히 찍는다(결함 256).
        out += ["",
                "> **이 표의 판정은 «표준» 으로 계산해 봉인한 값이다.** "
                "잣대를 바꿔 다시 돌리지 않는다 — 그러면 동결 수치가 흔들린다. "
                "대신 **저장된 확률에 이 잣대의 문턱을 다시 대** "
                "달라지는 것만 «→» 로 적었다(**%d건**). "
                "**지금 이 잣대로 실제로 계산한 판정을 보려면 "
                "「직접 검증」 탭에서 축2 를 바꿔 돌려라** — 거기는 "
                "문턱과 등록부 의무가 실제로 걸린다." % moved,
                "",
                "> `조건부` 는 문턱과 무관해 «→» 를 안 붙인다 — "
                "확증 근거가 **양방향으로 대등**해서 갈린 판정이다."]
    out += ["", "#### 이 실행에서 **빠진 것**", "", "> " + r["빠진_것"]]
    return "\n".join(out)


def evidence_card(query: str) -> str:
    """근거 카드 — PMID·**확인된 인용 구간**·가중치. **이게 산출물의 본체다.**"""
    c = _cases().get(query)
    if not c:
        return "> 구운 사례에 없다: %s" % q_name(query)
    # ── **「직접 검증」·「병명으로 시작」과 같은 서식** (08-19) ─────
    #
    #   앞판은 여기만 `- PMID 12345 · w=1.60 · 회의주의자 회수 · 대조
    #   완전일치 — 인용…` 이라는 **한 줄짜리 자체 서식**이었다.
    #   다른 두 화면은 이미 `evidence_full`(무게 칩 · 인용 · 대상/용량/
    #   시점)로 바꿨는데 **대시보드만 낡은 채로 남았다.**
    #
    #   **같은 것을 세 곳에서 각자 그리면 반드시 갈라진다** — 결함 283
    #   에서 두 곳을 합쳤고 여기가 세 번째다.
    ev = sorted((c.get("근거") or []), key=lambda e: -(e.get("가중치") or 0))
    sup = [e for e in ev if e.get("방향") != "반박"]
    ref = [e for e in ev if e.get("방향") == "반박"]
    out = ["#### 근거 %d건" % len(ev), "",
           "<div class='br-detail'>",
           "<div class='br-dhead'>%s</div>"
           % verdict_badge(c.get("판정"), c.get("신뢰도")),
           "<div class='br-dname'>%s</div>" % query,
           "<div class='br-dwhy'>%s</div>" % why_plain(c.get("사유")),
           "</div>", ""]
    for title, lst in (("반대 %d건" % len(ref), ref),
                       ("지지 %d건" % len(sup), sup)):
        if not lst:
            continue
        out += ["<div class='br-egrp'>%s</div>" % title]
        out += [evidence_full(e) for e in lst[:6]]
        out.append("")
    if not ev:
        out += ["<span class='br-sub'>채택된 근거가 없습니다.</span>", ""]
    return "\n".join(out)


# ── 사고 과정 · 자기수정 (심사 기준 30점 · 10점) ─────────────
#
# 주최측 심사 기준이 두 항목을 직접 묻는다 —
#
#   시연 및 완성도 (30점)  "에이전트의 **사고 과정을 투명하게** 보여주는가"
#   자율성 및 지능 (10점)  "오류·잘못된 결과 발생 시 **스스로 인지하고 수정**하는가"
#
# 재료는 다 있었는데 **한 번도 그렇게 제시한 적이 없다.** 게이트 trail 이
# 사고 과정이고, 그 안에 자기인지·자기수정 흔적이 남아 있다.
#
# **인지와 수정을 구분해서 적는다** — 우리가 가진 것은 인지가 많고
# 수정은 부분적이다. 둘을 뭉치면 과장이 된다.
SELF = [
    # (표시, 무엇을 인지, 무엇을 했나, 인지만인가)
    ("인용 검증 실패", "LLM이 댄 문장이 초록에 없다",
     "**가중치 0으로 강등** — 수정", False),
    ("거울상체·타 약물", "인용이 다른 약을 가리킨다",
     "**감쇠** — 수정 (dexpramipexole 사고에서 생겼다)", False),
    ("중복 시험", "메타분석이 같은 RCT를 포함한다",
     "**NCT로 중복 제거** — 수정 (다만 메타분석엔 NCT가 없어 못 잡는다)", False),
    ("확증 양방향", "지지·반박이 대등하다",
     "**`조건부` 로 재분류** — 수정", False),
    ("철회 논문", "근거가 철회됐다", "**근거에서 제외** — 수정", False),
    ("F0 조회 실패", "PubMed 이 안 뜬다",
     "**`보류`. 판정하지 않는다** — 인지", True),
    ("구조 조회 실패", "AlphaFold 응답이 없다",
     "**경로를 바꾸지 않는다.** 0건이 아니므로 — 인지", True),
    ("PRR 분모 0", "총계가 서로 모순이다",
     "**계산 불가.** 무한대를 신호로 쓰지 않는다 — 인지", True),
    ("분류 전건 실패", "라우터 응답이 전부 없다",
     "**판단 자체를 거부**(rc=1) — 인지", True),
]


def autonomy() -> str:
    """자율성 — **인지와 수정을 갈라서** 적는다 (심사 10점)."""
    fix = [s for s in SELF if not s[3]]
    know = [s for s in SELF if s[3]]
    # **결함 수를 하드코딩하지 않는다** (결함 74).
    #
    #   08-07 아침, 화면을 처음 띄우니 여기에 **열두 판 낡은 수**가 찍혀
    #   있었다(당시 실제의 절반 남짓). `docaudit` 은 `.md` ·
    #   `app.py` · `build_deck.py` · `pptx` 를 보는데 **`dash.py` 는
    #   목록에 없었다** — 그런데 이 파일이 **심사위원이 실제로 보는 화면**을
    #   만든다. 결함 60·61·68과 같은 자리다: **가드가 안 보는 곳.**
    #
    #   `evidence.defect_count()` 가 발견정리 표의 **행을 센다.** 문서에
    #   적힌 숫자를 읽지 않으므로 표와 화면이 갈라질 수 없다.
    n_def = evidence.defect_count()
    said = ("결함 **%d건**" % n_def) if n_def else "개발 중 찾은 결함"
    out = ["#### 오류를 스스로 인지하고 수정하는가", "",
           "**런타임에 실제로 도는 것만** 적는다. 개발 중 사람이 찾은 %s은" % said,
           "여기 안 넣는다 — 그건 *우리가* 찾은 것이고 **시스템이 찾은 게 아니다.**", ""]
    out += ["**수정한다 (%d)**" % len(fix), "", "| 인지 | 조치 |", "|---|---|"]
    for _n, k, a, _ in fix:
        out.append("| %s | %s |" % (k, a))
    out += ["", "**인지만 한다 (%d)** — 고칠 수 없으면 **판정을 안 한다**" % len(know),
            "", "| 인지 | 조치 |", "|---|---|"]
    for _n, k, a, _ in know:
        out.append("| %s | %s |" % (k, a))
    out += ["",
            "> **인지만 하는 쪽이 더 중요하다.** 조회가 실패했을 때 0건으로 세면",
            "> 네트워크 장애가 '발견'이 된다 — 실제로 그렇게 *\"반증 근거의 부재는",
            "> 구조적이다\"* 라는 결론이 나온 적이 있다. 우리 논지를",
            "> **지지하는** 방향이라 더 위험했다.",
            "",
            "> 그리고 정직하게 — **자율적으로 재계획하지는 않는다.** 라우터가",
            "> 후보별로 검증 경로를 정하는 것이 자율 계획의 전부다. 실패한 뒤",
            "> 다른 전략을 새로 짜지는 않는다."]
    return "\n".join(out)


def _cell(v: Any) -> str:
    """마크다운 표 **셀 안의 파이프를 이스케이프**한다 (결함 73).

    ## 화면을 처음 띄우고 나서야 보였다

    08-07 아침, `py app.py` 를 **처음으로 실제 실행**했다. 사고 과정 표가
    중간부터 깨져서 파이프가 그대로 노출됐다 —

    ```
    | 회의주의자 | DONE | 추가 초록 10건 → … (6건 중 신규 5 | 6건 중 신규 5) |
                                                        ↑ 여기서 컬럼이 갈린다
    ```

    회의주의자 게이트의 `detail` 이 *"(6건 중 신규 5 **|** 6건 중 신규 4)"*
    형태로 파이프를 담고 있다. 마크다운은 그걸 **컬럼 구분자**로 읽으므로
    그 행부터 표가 무너지고 뒤 행들이 한 줄로 뭉개진다.

    ## 원본 문자열을 안 고치는 이유

    `detail` 은 **동결된 trail 내용**이다. 고치면 시험 [45]가 검사하는
    *"s2 trail 문구가 안 바뀐다"* 류의 불변식과 `QUIET_WHEN_OFF` 전제가
    흔들린다. **표시 층에서 이스케이프하는 것이 옳은 자리다.**

    ## 그리고 이건 가짜 gradio 가 절대 못 잡는 것이었다

    시험 [55]는 콜백이 **문자열을 돌려주는지**만 봤다. 그 문자열이
    **마크다운으로 어떻게 렌더되는지**는 띄워야 보인다 —
    *"검증 환경이 실행 환경과 다르면 그 검증은 거짓말이다."*
    `gradiocheck` 도 API 만 봤지 렌더 결과는 못 본다.
    **화면 한 번이 검사기 두 개보다 많이 잡았다.**

    ## 그리고 공백 뭉치도 접는다 (08-07 2차)

    첫 판은 파이프와 줄바꿈만 처리했다. **가로 스크롤바가 남아 있었다** —
    셀 하나가 **209자**였기 때문이다.

        | S2 리간드 개발성 | `PASS` | … HBA 1<공백 40칸>⚠ Ro5는 수동확산 전제 … |
                                              ↑ 여기

    CLI 출력에서 **열 맞춤용으로 넣은 공백**이 그대로 따라 들어왔다.
    터미널에서는 두 덩이를 갈라 보여 주는 장치인데, 표 셀 안에서는
    **셀을 옆으로 늘리기만** 한다.

    **원본(`demo_cases.json`)을 안 고치는 이유는 파이프 때와 같다** —
    동결된 trail 내용이다. **표시 층에서 접는다.**

    > **정직하게** — 렌더러가 정확히 왜 그 줄을 회색 상자로 뺐는지는
    > 브라우저 없이 확인 못 했다. 다만 **209자 셀은 어느 렌더러에서도
    > 가로로 넘친다.** 원인을 특정하지 못한 채 고친 것이 아니라,
    > **확실한 원인 하나를 제거한 것**이다. 남은 것은 화면으로 봐야 한다.
    """
    s = "" if v is None else str(v)
    s = re.sub(r"\s{2,}", "  ", s.replace("\n", " "))
    return s.replace("|", "\\|").strip()


def thinking(query: str) -> str:
    """사고 과정 — 게이트별 trail (심사 30점 *"투명하게 보여주는가"*).

    **판정만 주지 않는다.** 어느 게이트에서 무엇을 보고 어떻게 갈렸는지가
    이 시스템의 산출물 본체다.
    """
    c = _cases().get(query)
    if not c:
        return "> 구운 사례에 없다: %s" % q_name(query)
    gates = c.get("게이트") or []
    if not gates:
        return "> 게이트 기록이 없다."
    # ── 경고문은 **표 밖으로 뺀다** (08-07 · 화면을 보고 나서) ─────────
    #
    #   S2 게이트의 설명이 `… HBA 1   ⚠ Ro5는 수동확산 전제 …` 형태로
    #   **결과와 경고를 한 셀에** 담고 있었다. 표가 209자로 늘어나
    #   가로 스크롤이 생겼고, **경고문이 화면 밖으로 밀렸다.**
    #
    #   그 경고는 결함 34에서 나온 **실제 과학적 단서**다 —
    #   *"메트포르민은 극친수성이라 Ro5 위반 0건이 투과성을 뜻하지 않는다."*
    #   심사위원이 스크롤을 안 하면 **못 읽는다.** 표를 좁히는 것보다
    #   **경고를 보이게 하는 것**이 목적이다.
    # ── **표가 아니라 목록** (08-19) — 결함 283 과 같은 자리 ────
    #
    #   「직접 검증」·「병명으로 시작」은 이미 `step_list` 로 바꿨는데
    #   **대시보드만 표였다.** 한 칸이 183자까지 가고 설명 안의 파이프가
    #   표를 부순다 — 여기서도 같은 위험이 그대로 있었다.
    out = ["#### 이 판단이 나온 과정", "", step_list(gates), ""]
    caveats = []
    for g in gates:
        d = str(g.get("설명") or "")
        if "⚠" in d:
            t = d.partition("⚠")[2].strip()
            if t:
                caveats.append((str(g.get("게이트") or ""), t))
    # ── 색 범례 (08-10) ─────────────────────────────────────
    #   색이 뜻을 나르면 **뜻을 적어야 한다.** 안 적으면 그건 장식이다.
    #   그리고 여기 다섯 중 뒤의 둘이 심사 10점 항목이다.
    out += ["", "%s %s 통과 · %s 일부러 건너뜀 · %s 경로가 갈림 · "
            "%s **모른다고 답함** · %s **스스로 고침**"
            % (gate_chip("PASS"), gate_chip("DONE"), gate_chip("SKIP"),
               gate_chip("BRANCH"), gate_chip("UNKNOWN"), gate_chip("CHANGED"))]
    for gate, note in caveats:
        out += ["", "> ⚠ **%s** — %s" % (_cell(gate), _cell(note))]
    # 자기수정 흔적을 **자동으로 찾아** 짚는다 — 손으로 적으면 낡는다
    marks = []
    blob = " ".join(str(g.get("설명") or "") for g in gates)

    # ── ⛔ 09-17 · **같은 낱말이 게이트마다 다른 뜻이다** ─────────────────
    #
    #   앞판은 `gates` 전체를 한 덩어리(`blob`)로 이어 붙이고
    #   `if "무관" in blob:` 으로 *"무관 판정으로 **가중치 0**을 준 초록이
    #   있다"* 를 찍었다. 팩트체커에서는 맞다 — 거기서 「무관」은 w=0 이다.
    #
    #   그런데 **F(전문 읽기)의 DONE 도 「무관N」을 적는다**
    #   (`gates.gate_fulltext` — `약화2 무관1 · 감쇠 2건`). F 의 「무관」은
    #   `LIMIT_MULT["무관"] = 1.0`, 즉 **가중치를 안 건드린다.**
    #   그대로 두고 F 를 배선했으면 **화면이 «가중치 0을 줬다» 고 거짓말**한다.
    #
    #   `CLAUDE.md §2` — «모른다» 와 «차이 없다» 를 안 가르는 것과 같은 계열.
    #   **문자열이 아니라 게이트로 좁힌다.**
    from .demo import GATE_KO as _KO_T

    def _from(*keys) -> str:
        """그 게이트들이 적은 설명만 이어 붙인다. **영문 키와 한글 이름을 다 받는다** —
        구운 사례에는 옛 이름이 문자열로 남아 있다(결함 275)."""
        want = set(keys) | {_KO_T.get(k, k) for k in keys}
        return " ".join(str(g.get("설명") or "") for g in gates
                        if str(g.get("게이트") or "") in want)
    if "철회" in blob:
        n = blob.split("철회")[1].split()[0].strip("0123456789") or ""
        marks.append("**철회 논문을 근거에서 제외**했다 (`철회` 표시)")
    if "인용실패" in blob:
        marks.append("**인용 검증 실패**를 세어 가중치를 강등했다")
    if "무관" in _from("rag", "factcheck", "L2 팩트체커"):
        marks.append("**무관 판정**으로 가중치 0을 준 초록이 있다")
    # F 는 **깎기만 한다.** 0으로 만들지 않는다 — 그래서 문구가 다르다.
    _ft = _from("fulltext")
    if "감쇠" in _ft:
        marks.append("**논문 전문에서 저자가 적은 한계**를 읽고 "
                     "그 근거의 가중치를 **낮췄다**(0 으로 만들지는 않는다)")
    if "한계를 못 읽었다" in _ft:
        marks.append("전문을 **못 읽은 것을 «한계 없음» 으로 세지 않았다** — "
                     "그대로 «모른다» 로 남겼다")
    if any(g.get("결과") in ("UNKNOWN", "ERROR") for g in gates):
        marks.append("**분류 불가**를 그대로 적었다 — 억지로 채우지 않았다")
    if marks:
        out += ["", "**이 실행에서 스스로 인지·수정한 것**", ""]
        out += ["- " + m for m in marks]
    out += ["", "> 게이트 하나하나가 켜고 끌 수 있다. 그래서 **제거 실험",
            "> (B0~B8)이 for 루프 하나**로 돈다 — 이 투명성이 곧 확장성이다."]

    # ── ⛔ 09-18 · **«없는 것» 과 «끈 것» 은 다르다** ────────────────────
    #
    #   제안서 §2 가 **세 축**이라 했고 셋째가 HITL 이다. 시연 구성이 그걸
    #   끄는데(사유는 옳다 — 사람 개입을 보이면 「자율」 주장이 흐려진다)
    #   **화면이 그 사실을 말하지 않았다.** 심사위원이 세면 둘만 보인다.
    #
    #   사유는 `gates.DEMO_GATES` 에 **처음부터 적혀 있었다.** 그런데
    #   `CONFIGS["B5SF"]` 가 `_why` 를 버리고 아무도 안 읽었다 —
    #   `fragility`·`false_negatives`·`refute_recall` 과 같은 계열이다.
    #
    #   **손으로 적지 않는다.** 표에서 파생하므로 표를 고치면 화면이 따라온다.
    # ── ⛔ 09-19 렌즈 7 · **한 화면에서 «구운 값» 과 «지금 값» 을 섞었다** ──
    #
    #   위 게이트 목록은 `_cases()` — **구운 시점**의 사실이다.
    #   아래 「끈 게이트」는 `DEMO_GATES` — **지금**의 사실이다.
    #   **둘이 갈라지면 화면이 자기 자신을 반박한다**(결함 102 와 같은 자리:
    #   *«화면이 우리 자신의 실험 결과를 반박한다»*).
    #
    #   실측(09-19) — 구운 사례에 `hitl SKIP` 은 있고 **`registry` 는 기록이
    #   아예 없다.** 지금은 둘 다 꺼져 있어 **우연히 일치**하지만,
    #   구운 사례는 08-14 판이라 **그때 구성이 지금과 같다는 보장이 없다.**
    #   **그건 운이지 방어가 아니다**(결함 224 의 표현 그대로).
    #
    #   그래서 **구운 기록과 대조한다.** 꺼졌다고 한 게이트가 이 사례에서
    #   **돌아간 채로** 구워졌으면 그 사실을 같은 줄에 적는다.
    from .core import gates as _G_OFF
    _off = _G_OFF.demo_off()
    if _off:
        _seen = {}
        for _g0 in gates:
            _seen[str(_g0.get("게이트") or "")] = str(_g0.get("결과") or "")
        out += ["", "**이 시연에서 끈 게이트** — *없는 것이 아니라 끈 것이다*", ""]
        for _g, _why in _off:
            _ko = _KO_T.get(_g, _g)
            _res = _seen.get(_g) or _seen.get(_ko) or ""
            if _res and _res not in ("SKIP", "NONE"):
                out.append(
                    "- **%s** (`%s`) — 지금 구성에서는 끈다(%s). "
                    "⚠ **다만 이 사례는 그 게이트가 돌아간 채로 구운 값이다**"
                    "(`%s`) — 위 단계 목록이 그 시점의 사실이다."
                    % (_ko, _g, _why, _res))
            else:
                out.append("- **%s** (`%s`) — %s" % (_ko, _g, _why))
        out += ["", "> 코드와 회귀 시험은 **있다.** 전부 켠 구성이 `B8` 이고,",
                "> 제거 실험이 그 구성까지 돈다. **끈 이유를 여기 적는 것까지가**",
                "> **투명성이다** — 안 보이는 것을 안 보인다고 말하지 않으면",
                "> 그건 숨긴 것이다."]
    return "\n".join(out)


# ── 우: 반증 · 구조 · 특허 뷰어 ─────────────────────────────
def right_structure(s1: Optional[Dict] = None, query: str = "") -> str:
    """구조 뷰 — 도킹 포즈가 아니라 **pLDDT 색칠**(§3.3-10).

    S1 이 안 돌았으면(구조 경로가 아니면) **그렇다고 적는다.**

    ## `query` — 결함 282 와 **같은 자리** (08-19)

    `viewer.render` 는 `s1` 만 받으므로 **라우터가 무엇을 골랐는지
    모른다.** 그런데 앞판은 *«표적에 직접 결합하지 않아»* 를 상수로
    냈다 — 라우터가 기전을 못 정한 경우에도 그렇게 적혔다.
    **이유를 아는 것은 기록이고, 기록은 여기서 읽는다.**
    """
    if not s1:
        c = _cases().get(query) if query else None
        # `viewer` 는 **날 HTML** 이라 마크다운이 안 돈다. `**` 를 그냥
        #   넘기면 별표가 화면에 보인다(결함 283 ④와 같은 형태).
        why = route_note(c).replace("**", "") if c else ""
        return viewer.render(None, why=why)
    return viewer.render(s1)


def right_patent(drug: str) -> str:
    """특허 뷰 — **판정에 안 섞는다.** 특허는 가설을 틀리게 만들지 않는다.

    ## 08-14 — 자료원을 바꿨다 (결함 218)

    여태 `fto.check()`(PatentsView API)를 불렀다. 그 API 는 2026-03-20 에
    중단됐고 키를 못 받는다(결함 95). 그래서 이 칸은 **늘 «확인불가»**
    였다 — 그 사이 우리가 훑은 SureChEMBL **11.6 GB** 는 화면에 한 줄도
    안 나왔다. **이름만 같고 따로 노는 두 경로였다.**

    이제 `local_check()`(우리 색인 · 망 안 씀)를 먼저 본다. 색인이 없으면
    **그 사실을 적는다** — «특허 없음» 으로 읽히면 안 된다(결함 141).
    """
    from .io import fto
    r = fto.local_check(drug)
    if r["label"] == "확인불가" and not r.get("n_patents"):
        # 로컬이 못 답할 때만 옛 경로를 본다. **거의 «키 없음» 이 온다** —
        # 그걸 숨기지 않는다. 두 자료원 중 무엇이 답했는지 화면에 적는다.
        alt = fto.check(drug)
        if alt.get("patents"):
            r = alt
    out = ["#### 특허 자유도 (FTO)", "",
           "| | |", "|---|---|",
           "| 약물 | %s |" % q_name(drug),
           "| 판정 | **%s** |" % r["label"],
           "| 자료원 | %s |" % r.get("출처", "PatentsView API"),
           "| 사유 | %s |" % r["why"]]
    if r.get("국가"):
        # **다섯 건이 대표 표본이 아니라는 것을 화면이 스스로 말하게 한다.**
        # 정렬이 같은 해 안에서 번호순이라 한 나라로 몰린다(08-14 실측: CN 5/5).
        out.append("| 국가 분포 | %s |"
                   % " · ".join("%s %s" % (c, "{:,}".format(n))
                                for c, n in r["국가"]))
    if r.get("patents"):
        # ── 제목을 자른다 (08-10) ────────────────────────────────
        #   API 키가 없어 지금은 이 가지가 안 돈다. 그래서 **모의로
        #   특허 5건을 우측 칸에 넣어 재 봤다** — 칸 폭 247px 에서
        #   제목 한 건이 **3줄(65~86px)**, 다섯 건이 340px 이 됐다.
        #   칸을 넓힐 필요는 없었지만(전체는 840px 로 중앙보다 짧다)
        #   **제목이 길면 목록이 글벽이 된다.** 80자에서 자른다.
        #   전문은 특허 번호로 찾으면 된다 — 번호가 진짜 식별자다.
        out += ["", "**검색된 특허 — 최근 공개 5건** (순위가 아니라 정렬이다)"]
        for p in r["patents"][:5]:
            t = str(p.get("title") or "")
            if len(t) > 80:
                t = t[:79].rstrip() + "…"
            # 날짜가 없으면 **«?» 라고 적는다.** 빈칸이면 «없다» 로 읽힌다
            d = p.get("date")
            out.append("- %s (%s)%s"
                       % (q_name(p["id"]), d if d is not None else "연도 미상",
                          " %s" % t if t else ""))
    # ── 경고 **셋을 하나로 묶는다** (08-19 화면) ────────────────
    #
    #   앞판은 인용구 세 개가 연달아 섰다 — 「판정에 안 들어간다」·
    #   「자유실시를 판단하지 않는다」·「검색 한계」. `화면진단_0818 §②`
    #   가 이미 적었다: *«경보가 잦으면 사람이 경보를 무시한다»*
    #   (결함 126). 하나하나는 다 옳고 **전부 합치면 아무도 안 읽는다.**
    #
    #   **한 상자에 모으고 층을 준다** — 맨 앞 한 줄만 굵게, 나머지는
    #   작은 글씨. «무엇을 안 하는가» 는 지우지 않는다. 그건 이
    #   프로젝트의 자산이고, 자산을 균등하게 뿌려 희석한 게 문제였다.
    #
    #   ── 08-14 — **여기서 한 글자도 더 안 나간다** ─────────────
    #     `계획_8월` 범위표 · 명세 `e22a4bf7` · `FTO연도결과.md` 셋이
    #     같은 선을 긋는다. 만료조차 못 가른다(공개연도 p=0.773).
    out += ["", "> **이 값은 판정에 들어가지 않습니다.** 특허가 살아 있어도 "
            "그 약이 그 병에 듣는다는 명제의 참거짓은 그대로입니다.",
            ">",
            "> <span class='br-sub'>⛔ 자유실시 여부는 판단하지 않습니다 — "
            "청구항을 읽지 않고 존속·포기·무효·국가별 지정을 모릅니다. "
            "공개연도로 만료를 대신 재 보려다 무작위와 구별이 안 됐습니다"
            "(p=0.773). · %s</span>" % _cell(r["한계"])]
    return "\n".join(out)


# ── 하: 보정 곡선 + Time-to-Refute (제안서 §6 하단) ──────────
#
# ## 결함 132 — **여기가 숫자를 상수로 박고 있었다**
#
# 앞판은 이랬다 —
#
#     ECE = [("B0 폐쇄형", 0.072, …), ("B5 전체", 0.105, "**기준선보다 나쁘다**")]
#
# 그리고 화면에 *"Platt 보정은 아직 안 했다"* 를 찍었다. **08-12에 Platt 을
# 적용하고 ECE 를 0.1039 → 0.0515 로 낮췄는데도 화면은 옛말을 계속 했다.**
#
# `evidence.py` 독스트링이 스스로 이렇게 적어 뒀다 —
# *"결함 건수를 코드에 타이핑하면 늘어났을 때 **화면만 거짓말한다.**
# 파일에서 센다."* **보정 수치만 그 규칙 밖에 있었다.**
#   ↑ 원문의 예시 숫자는 **일부러 안 적는다.** 08-12 실측: 주석에 적었더니
#     `docaudit` 이 그걸 «화면이 주장하는 결함 수» 로 읽고 빨개졌다.
#     **인용은 방어가 아니다** — 오늘 세 번째다(시험 [49]·[95]·여기).
#
# 게다가 `0.072`·`0.105` 는 **dev(층A) 수치**였는데 집합을 안 밝히고 썼고,
# 지금 코드로는 **재현도 안 된다**(dev 0.0756/0.1168 · 홀드아웃 0.1066/0.1039).
#
# 그래서 `calibration.json` 을 읽는다. 없으면 **없다고 적는다** — 옛 상수로
# 안 돌아간다.
CAL_CARD = "calibration.json"


def _cal_card() -> Optional[Dict[str, Any]]:
    import json as _j
    import os as _o
    p = _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))),
                     CAL_CARD)
    if not _o.path.exists(p):
        p = CAL_CARD
    try:
        return _j.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def bottom_calibration() -> str:
    c = _cal_card()
    if not c:
        return ("#### 신뢰도 보정 (ECE) — 논지의 절반\n\n"
                "> **보정 카드가 없다**(`calibration.json`). 숫자를 상수로 적어 "
                "두지 않으므로 화면에도 안 적는다 — `py -m bioreroute.bench."
                "calibrate --card` 로 구워라. **없는 것을 옛 값으로 채우지 않는다.**")
    b5, b0, nul = c.get("B5") or {}, c.get("B0") or {}, c.get("널모형") or {}
    # ── 09-25 · **어느 시스템의 수인지** 적는다 (결함 337) ──────────────
    # ── 09-26 밤 · 그 이름을 **카드에서** 읽는다 (결함 360) ──────────────
    #   앞판은 «08-05 홀드아웃(gpt-5.4-mini)» 과 «본선 모델(terra)은 Platt 을 다시 적합하지
    #   않았다» 를 **코드에 박아** 두었다. 보고서가 terra 로 다시 맞춘 뒤에도 화면은 «안 맞췄다»
    #   를 말했다 — 결함 132(상수로 박은 보정 수치)와 같은 모양이 **이름**에서 재발했다.
    #   이제 카드(`calibrate --card --label …`)가 스스로 무엇을 어디서 맞췄는지 적는다.
    lab = c.get("라벨") or "08-05 홀드아웃(gpt-5.4-mini)"
    fit = c.get("적합") or "층 A"
    out = ["#### 신뢰도 보정 — 논지의 절반", "",
           "> **%s** %d쌍(개발집합과 겹치는 쌍 제외) · 기저율 %.3f · 명세 `%s…` — "
           "개발집합(층 A · `%s`)으로 맞춘 Platt 을 적용한 값이다. **화면 위쪽의 %%는 보정 전 값**이다"
           % (lab, c.get("n_eval", 0), c.get("기저율", 0), c.get("명세", ""), fit), "",
           "| | ECE 원점수 | **ECE Platt** | Brier 원→Platt |",
           "|---|---|---|---|",
           "| **B5 전체** | %.4f | **%.4f** | %.4f → **%.4f** |"
           % (b5.get("ece_raw", 0), b5.get("ece_platt", 0),
              b5.get("brier_raw", 0), b5.get("brier_platt", 0)),
           "| B0 기준선 | %.4f | %.4f | %.4f → %.4f |"
           % (b0.get("ece_raw", 0), b0.get("ece_platt", 0),
              b0.get("brier_raw", 0), b0.get("brier_platt", 0)),
           "| **널 모형** (항상 기저율) | — | **%.4f** | — · **%.4f** |"
           % (nul.get("ece", 0), nul.get("brier", 0)), ""]
    # 09-26 밤 · 모델 단독과의 비교는 **Brier 구간**으로 말한다(보고서 §4.2 와 같은 수 · 결함 361).
    #   Brier 구간이 없는 옛 카드면 ECE 구간으로 돌아가되, 무엇의 구간인지 적는다.
    vb = (c.get("boot_brier") or {}).get("b5_vs_b0_platt")
    v = vb or (c.get("boot") or {}).get("b5_vs_b0_platt")
    what = "Brier" if vb else "ECE"
    out += ["> **널 모형 줄을 먼저 봐라.** 1:1 균형 집합이라 «항상 기저율만»",
            "> 답하는 예측기의 ECE 가 **0.0000** 이다 — **ECE 는 정보를 버릴수록**",
            "> **좋아진다.** 그래서 ECE 단독으로 «정직해졌다» 를 주장하지 않는다.",
            ">",
            "> **Brier 로 보면 다르다.** 적정 점수 규칙이라 상수 예측기가 못 이긴다 —",
            "> 널 %.4f vs 우리 **%.4f**. 여기서만 실질 개선을 말할 수 있다."
            % (nul.get("brier", 0), b5.get("brier_platt", 0))]
    if v:
        out += ["",
                "> **B0 대비 우위는 주장 못 한다** — 둘 다 보정한 %s 차이의 짝지은 부트스트랩 "
                "[%+.4f, %+.4f] 이 **0을 포함**한다." % (what, v[1], v[2])]
    out += ["",
            "> 초판 보고서·1페이지·발표자료 셋 다에서 이 표가 빠져 있었고,",
            "> 그건 **선택적 보고**였다(결함 46)."]
    return "\n".join(out)


def bottom_timeline(timing: Optional[Dict[str, Any]] = None) -> str:
    """Time-to-Refute — **이미 존재하는 반증 증거를 통합·제시하는 속도**(§4.1).

    `timing` 이 없으면 **없다고 적는다.** 예시 숫자를 넣지 않는다.
    """
    # ── 이름을 화면 말로 (08-19) ────────────────────────────────
    #   «Time-to-Refute» 는 제안서 §4.1 의 지표 이름이지 **사용자 말이
    #   아니다.** 심사위원은 알지만 서비스 화면에서 처음 보는 사람은
    #   영어 세 단어를 읽고 넘긴다. 뜻을 한국어로 적고 원어는 괄호에.
    # 제목은 **접힌 `<summary>` 가 이미 말한다.** 안에서 또 적으면
    #   같은 말이 두 번 나온다 (08-19 접기 이후).
    out = []
    if not timing:
        out += ["#### 반박 근거를 모으는 데 걸린 시간", "",
                "<span class='br-sub'>아직 안 쟀습니다. 이 화면은 지난 "
                "결과를 다시 보여 주는 것이라 실행 시간이 없습니다 — "
                "「직접 검증」 탭에서 한 번 돌리면 채워집니다.</span>"]
        return "\n".join(out)
    t = timing if "게이트별" in timing else None
    if t is None:
        return "\n".join(out + ["> 형식을 알 수 없다."])
    # 게이트 이름을 **한글로** — 결함 247 과 같은 자리다(`.get` 폴백이라
    # 안 죽지만 화면에 `rag`·`skeptic` 이 그대로 찍혔다).
    from .demo import GATE_KO as _KO
    per = t.get("게이트별") or {}
    # 표 둘을 **가로로** (08-20 승우) — 단계별과 합계를 같이 봐야
    #   «어디에 시간이 갔나» 가 보인다. 세로로 쌓으면 스크롤이 생긴다.
    out += ["<div class='br-cols' markdown='1'>", "", "<div markdown='1'>"]
    if per:
        # ── 표가 아니라 **막대** (08-20 승우: «검색시간 부분도 수정») ──
        #
        #   숫자 두 열을 읽고 «어디에 시간이 갔나» 를 머릿속에서 비교하게
        #   하는 것보다, **길이로 보이면 한 번에 온다.** 숫자는 그대로 옆에
        #   적는다 — 막대는 비율이고 숫자는 값이라 둘 다 필요하다.
        mx = max(per.values()) or 1.0
        # **왜 빠른지를 그 자리에서 말한다.** 밀리초가 여럿 뜨는데
        #   이유가 화면 아래 표에만 있으면 «안 쟀나» 로 읽힌다.
        if all(v < 1.0 for v in per.values()) and t.get("warm"):
            out.append("<div class='br-note-in'>단계마다 1초 미만입니다 — "
                       "<b>미리 받아 둔 자료가 있어서</b>이고, "
                       "«안 쟀다» 가 아닙니다.</div>")
        out.append("<div class='br-times'>")
        for g, v in sorted(per.items(), key=lambda x: -x[1]):
            # 이름은 **막대 위 한 줄**로 올린다 (08-20 승우: «글자 짤림»).
            #   앞판은 이름·막대·숫자를 한 줄에 넣고 이름 칸에
            #   `ellipsis` 를 걸었다 — 「논문 읽고 지지·반박 가르기」가
            #   「논문 읽고 지지·반…」이 됐다. **자르지 말라고 고친
            #   바로 옆에서 같은 짓을 했다.**
            out.append("<div class='br-trow'>"
                       "<div class='br-thead'><span class='br-tn'>%s</span>"
                       "<b class='br-tv'>%s</b></div>"
                       "<span class='br-tb'><i style='width:%.1f%%'></i></span>"
                       "</div>"
                       % (_cell(_KO.get(g, g)), secs(v), 100.0 * v / mx))
        out.append("</div>")
    else:
        # **빈 표를 내지 않는다.** 08-18 화면에 «게이트 | 초» 머리만 있고
        # 행이 0개인 표가 그대로 찍혔다(결함 254). 머리만 있는 표는
        # «0초 걸렸다» 로 읽힌다 — «안 쟀다» 와 다르다.
        out += ["<span class='br-sub'>단계별 내역이 없습니다 — 근거를 "
                "모으는 단계가 안 돌았거나 계측이 안 됐습니다.</span>", ""]

    _sec = secs   # **`None초` 를 안 찍는다** (결함 254·89) + 눈금을 값에 맞춘다

    w = t.get("warm")
    out += ["", "</div>", "", "<div markdown='1'>",
            "| | |", "|---|---|",
            "| **반박 근거를 모은 시간** | **%s** |"
            % _sec(t.get("반박근거_수집_초")),
            "| 전체 | %s |" % _sec(t.get("전체_초")),
            # **«캐시 항목 0» 과 «모름» 은 다르다**(결함 89).
            "| 미리 받아 둔 자료 | %s |"
            % ("**없음** — 이 초는 실제로 조회한 시간입니다" if w == 0
               else "**%s건 있음** — 이 초는 «빠르다» 가 아니라 "
                    "«이미 받아 뒀다» 는 뜻입니다"
                    % "{:,}".format(w) if isinstance(w, int) and w > 0
               else "**모름**")]
    out += ["", "</div>", "", "</div>", ""]
    note = t.get("주의")
    if note:
        out += ["", "> %s" % note]
    out += ["", "<span class='br-sub'>이 시간은 <b>새 근거를 만드는 "
                "속도가 아니라 이미 나와 있는 반박 근거를 찾아 모으는 "
                "속도</b>입니다. 그래서 "
                "근거를 모으는 단계만 셉니다.</span>"]
    return "\n".join(out)


def model_line(m) -> list:
    """모델 집계 → 사람이 읽는 줄. **새 꼴과 옛 꼴을 둘 다 읽는다.**

    새 꼴 `{"gpt-4o-mini @0.0": {"새로": 5, "캐시": 2}}`
    옛 꼴 `{"gpt-4o-mini @0.0": 7}`   ← 08-14 에 구운 사례
    """
    out = []
    for k, v in sorted((m or {}).items(),
                       key=lambda x: -(x[1] if isinstance(x[1], int)
                                       else sum(x[1].values()))):
        if isinstance(v, int):
            out.append("%s ×%d" % (k, v))
            continue
        bits = []
        if v.get("새로"):
            bits.append("새로 %d" % v["새로"])
        if v.get("캐시"):
            bits.append("캐시 %d" % v["캐시"])
        out.append("%s — %s" % (k, " · ".join(bits) or "0"))
    return out


def secs(v) -> str:
    """초를 **잰 값답게** 적는다.

    ## 08-20 승우: *«반박 시간이 0.00초로 뜨는 게 맞아?»*

    **맞는 값이었다.** 계측은 돌고 있고(`demo.py` 가 게이트마다
    `perf_counter` 를 적는다), 캐시가 데워져 있으면 팩트체크·회의주의자가
    **밀리초에 끝난다.** `%.2f` 로 찍으니 0.004초가 «0.00» 이 됐다.

    문제는 **화면이 잰 값을 «안 쟀다» 처럼 말한다는 것**이다. 이 프로젝트가
    반복해서 경계한 그 자리다 — *«0건»과 «모름»은 다르다*(결함 89).

    그래서 눈금을 값에 맞춘다 —

        1ms 미만  →  «1ms 미만»   (0 이 아니다. 너무 빨라서 못 가른 것)
        1초 미만  →  «12 ms»
        그 이상   →  «1.24초»
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "**모름**"
    if f < 0.001:
        return "1ms 미만"
    if f < 1.0:
        return "%d ms" % round(f * 1000)
    return "%.2f초" % f


def ttr_headline(timing) -> str:
    """접힌 제목에 **숫자 하나**를 남긴다.

    ## 08-19 승우: *«걸린 시간도 특허처럼 접는 게 좋지 않을까»*

    맞다. 접는 기준은 이미 있다 — *«판정에 들어가는 것은 펴 두고,
    안 들어가는 것만 접는다»*. **걸린 시간은 판정에 안 들어간다.**
    특허와 같은 부류다.

    다만 접기만 하면 **제안서 §4.1 의 평가축이 화면에서 사라진다.**
    그래서 제목에 «전체 N초» 를 남긴다 — **접혀 있어도 그 숫자는
    보인다.** 접는 것과 감추는 것은 다르다.
    """
    t = timing if (timing and "게이트별" in timing) else None
    if not t:
        return ""
    v = t.get("전체_초")
    try:
        return " — 전체 %.1f초" % float(v)
    except (TypeError, ValueError):
        return ""


# ── 옆: B0 나란히 (제안서 §6) ───────────────────────────────
#   > 대조 축은 **판단 방향이 아니라 검증 가능한 PMID 제시 여부와
#   > 신뢰도 보정의 유무**로 잡는다.
def side_by_side(query: str) -> str:
    c = _cases().get(query)
    # 대문자 `PMID` — 소문자로 읽어 0건이 나온 적이 있다(위 주석 참조)
    n_pmid = len({e.get("PMID") for e in (c.get("근거") or [])
                  if e.get("PMID")}) if c else 0
    # ── 결함 85 — **없는 것과 0건은 다르다** ────────────────────────
    #
    #   `demo_cases.json` 이 없으면 `c` 가 None 이고 `n_pmid` 가 0 이 된다.
    #   그러면 이 표가 이렇게 뜬다 —
    #
    #       | 검증 가능한 PMID | **0건** | **0건** |
    #
    #   **우리 핵심 주장이 우리 화면에서 반박된다.** 경고도 안 뜬다 —
    #   표가 멀쩡히 그려지기 때문에 보는 사람은 그게 실측인 줄 안다.
    #   배포 사전점검이 이걸 찾았다(길이로는 한 글자 차이라 안 보인다).
    #
    #   결함 35와 같은 계열이다 — **조회 실패를 0건으로 합산**했던 그것.
    #   그때 배운 것을 그대로 쓴다: **막힌 것과 없는 것을 구분해서 적는다.**
    ours = "**%d건**" % n_pmid if c else "— **사례 파일 없음**"
    # ── ⛔ 09-25 · 이 칸이 **상수를 들고 있었다** (결함 337) ────────────────
    #   «ECE 실측 0.105 — 기준선보다 나쁨» · «AUROC 0.704 · 게이트가 더한 것 +0.015».
    #   결함 132 가 **바로 아래 칸**(보정)에서 같은 병을 고쳤는데 이 칸은 안 봤다.
    #   0.105 는 지금 코드로 재현되지 않는 dev 수치이고(결함 135), ECE 는 균형
    #   집합에서 널 모형이 0 이라 주지표에서 뺐다. 그리고 셋 다 **mini 시절** 값이라
    #   발표 성능 장(본선 모델)과 다른 시스템의 수였다.
    #   → 발표 성능 장과 **같은 함수**(`perfcard.card()`)에서 읽는다. 못 읽으면
    #     **숫자를 안 적는다** — 옛 상수로 돌아가지 않는다.
    pc = _perf_card()
    if pc:
        b, u = pc["전체"], pc["모름"]
        br, aa, a5 = b["Brier"], b["AUROC"], u["AUROC"]["B5"]
        honest = ("| 확률의 정직성 (Brier · 낮을수록 좋다) | %.3f | %.3f — 널 %.3f 보다 낫고, "
                  "**B0 보다 낫다고는 못 한다** |" % (br["B0"], br["B5"], br["널"]))
        abst = "1급 판정 — 홀드아웃의 **%.0f%%**" % (100.0 * b["보류"][0] / b["보류"][1])
        ceil = ["> 그리고 B0 는 순진한 기준선이 아니라 **암기 천장**이다 — 우리 양성 집합",
                "> (RepoDB)이 모델 학습자료에 들어 있다. 홀드아웃 %d쌍 전체에서 모델 단독 %.3f ·"
                % (b["n"], aa["B0"][0]),
                "> 파이프라인 %.3f 로 **구별되지 않는다.** 모델이 문헌 없이 «모름» 이라 한"
                % aa["B5"][0],
                "> %d쌍에서만 0.5 대 **%.3f** [%.3f–%.3f] 로 갈린다 — 이 부분집합은 **결과를 본 뒤**"
                % (u["n"], a5[0], a5[1], a5[2]),
                "> 정했다(사후). *(본선 모델 · `py -m bioreroute.bench.perfcard` — 발표 성능 장과 같은 수)*"]
    else:
        honest = "| 확률의 정직성 (Brier) | 없음 | 수는 보고서 §7.0-c · 발표 성능 장 |"
        abst = "1급 판정"
        ceil = ["> 그리고 B0 는 순진한 기준선이 아니라 **암기 천장**이다 — 우리 양성 집합",
                "> (RepoDB)이 모델 학습자료에 들어 있다. *(이 배포본에는 홀드아웃 결과 파일이",
                "> 없어 수를 적지 않는다 — 옛 상수로 채우지 않는다)*"]
    out = ["#### 같은 질의를 일반 언어모델에 넣으면", "",
           "| | 일반 LLM (B0) | Bio-ReRoute (B5) |", "|---|---|---|",
           "| 검증 가능한 PMID | **0건** | %s |" % ours,
           "| 인용 원문 대조 | 없음 | `verify_quote` 3겹 |",
           honest,
           "| 기권(`보류`) | 없음 | %s |" % abst,
           "",
           "> **대조 축이 판단 방향이 아니다.** 우리가 미리 적어 뒀다 —",
           "> *널리 알려진 실패 사례에서는 일반 언어모델도 대체로 옳게 기각한다.*",
           "> HCQ 같은 유명 사례에서 방향은 갈리지 않는다. 갈리는 것은",
           "> **근거를 댈 수 있는가**와 **확률이 정직한가**다.",
           ""] + ceil
    return "\n".join(out)


_PERF: Dict[str, Any] = {}


def _perf_card() -> Optional[Dict[str, Any]]:
    """발표 성능 장과 같은 수 — **한 번만** 잰다(부트스트랩이라 수 초 걸린다)."""
    if "c" not in _PERF:
        try:
            import os as _o
            from .bench import perfcard as _pc
            _PERF["c"] = _pc.card(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
        except Exception:
            _PERF["c"] = None
    return _PERF["c"]


def run_labels() -> List[str]:
    return list(RUNS)


def candidates(run: str) -> List[str]:
    return list(RUNS.get(run, {}).get("후보") or [])
