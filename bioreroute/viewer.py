# -*- coding: utf-8 -*-
"""3Dmol.js 구조 뷰 (제안서 §3.3-10)

## 도킹 없이도 보여줄 것이 있다

보고서 초판에 *"도킹이 없으면 볼 것이 없다"* 고 적었다. **틀렸다.**
제안서 §1이 지적한 문제가 바로 여기 있다 —

  > 다수 접근이 구조 예측 신뢰도(pLDDT)를 **결합력으로 오인**하나,
  > 본 시스템은 신뢰도 게이트로만 사용한다.

그러면 화면에 그릴 것은 도킹 포즈가 아니라 **pLDDT 그 자체**다.
무질서 영역이 빨갛게 늘어져 있는 그림 한 장이 *"여기에 도킹을 돌리면
안 된다"* 를 문장 열 줄보다 잘 말한다.

**색은 AlphaFold 공식 배색을 그대로 쓴다.** 우리가 고른 색이 아니다.

    pLDDT > 90   진한 파랑   매우 높음
    70–90        하늘        높음
    50–70        노랑        낮음
    < 50         주황        매우 낮음 — 무질서 가능

## 구조로 막은 것

이 모듈은 **결합·친화도·점수라는 낱말을 화면에 쓰지 않는다.** 범례는
"예측 신뢰도"라고만 적는다. 시험 [47]이 그 문자열을 검사한다 —
안내문이 아니라 검사로 막는다.
"""

from typing import Any, Dict, Optional

from .io.structure import LABELS

# ── 라벨 → 화면 문구. **`structure.LABELS` 를 전부 덮어야 한다** ────────
#
#   08-11 실측(결함 100). 이 자리가 `if lab == "신뢰" else …` 이진 분기라
#   08-10에 늘린 `신뢰도미상` 이 **`저신뢰` 문구로 떨어졌다** —
#   화면이 *"무질서 영역이 넓다"* 고 말했는데 **그건 거짓**이다.
#   못 잰 것이지 무질서한 게 아니다.
#
#   결함 92와 **같은 계열이고 두 번째 소비자**다. 그때 `gates.py` 만 고치고
#   여기를 안 봤다. 이번엔 시험 [79]가 두 집합이 같은지 본다.
VERDICT = {
    "신뢰": "이 표적은 <b>구조 기반 검증의 전제 조건</b>을 만족한다"
            " — <b>성공을 예측하지 않는다</b>(PMC9852548)",
    "저신뢰": "<b>무질서 영역이 넓다 — 도킹은 여기서 거짓 확신을 만든다.</b>"
              " 증거 경로로 돌렸다",
    "신뢰도미상": "<b>구조는 있는데 신뢰도를 못 쟀다.</b> 좌표는 그릴 수 있으나"
                  " 판정은 못 한다 — <b>무질서하다는 뜻이 아니다</b>",
    "구조없음": "AlphaFold 에 이 표적의 예측 구조가 <b>없다</b>",
    "오류": "구조 조회에 <b>실패</b>했다 — <b>없다는 뜻이 아니다</b>",
}

CDN = "https://cdnjs.cloudflare.com/ajax/libs/3Dmol/2.0.4/3Dmol-min.js"

# AlphaFold 공식 배색 (EBI). 우리가 고른 값이 아니다.
BANDS = [(90, "#0053D6", "매우 높음 (>90)"),
         (70, "#65CBF3", "높음 (70–90)"),
         (50, "#FFDB13", "낮음 (50–70)"),
         (0,  "#FF7D45", "매우 낮음 (<50) · 무질서 가능")]

# **배경을 박으면 글자색도 박는다** (결함 114). 08-11 다크 실측에서
# 뷰어 헤더가 `배경 #f3f5f7 · 글자 #f3f4f6` 이 돼 **대비 1.01** 이었다 —
# 흰 배경에 흰 글자. 배경만 박고 `color` 를 안 적어 gradio 다크 본문색을
# 물려받은 것이다. 결함 68과 같은 자리인데, **그때는 뷰어가 아예 안 돌아서
# (결함 112) 아무도 못 봤다.** 시험 [87]이 이제 짝을 강제한다.
# ⚠ **제목은 본문보다 진해야 한다.** 앞판은 상자 전체를 `#5a6570` 으로
#   칠하고 제목만 `<b>` 로 뒀는데, 굵기만으로는 대비가 안 산다 — 다크
#   모드에서 «구조를 표시하지 않는다» 가 **거의 안 보였다**(결함 264).
#   상자 배경을 고정하므로 글자색도 같이 고정한다. 둘 중 하나만 고정하면
#   테마가 바뀔 때 대비가 무너진다.
_EMPTY = """<div style="padding:14px;border:1px solid #d8dde3;border-radius:8px;
 background:#fafbfc;color:#5a6570;font-size:13px;line-height:1.7">
<b style="color:#1f2937;font-size:13.5px">구조를 그리지 않았습니다</b><br>%s</div>"""


def render(s1: Optional[Dict[str, Any]], height: int = 340,
           why: str = "") -> str:
    """S1 결과 → 3Dmol 임베드 HTML.

    **없으면 없다고 적는다.** 빈 상자를 내면 "구조가 없다"와 "조회가
    실패했다"가 같아 보인다 — 이 프로젝트가 반복해서 틀린 지점이다.

    ## `why` — 08-19 · 결함 282 와 **같은 자리**

    앞판은 `s1` 이 없으면 *«표적에 직접 결합하지 않아 구조 검증을
    건너뛴다»* 를 **상수로** 냈다. 그런데 이 함수는 `s1` 하나만 받는다 —
    **라우터가 무엇을 골랐는지 알 방법이 없으면서 이유를 단정했다.**
    라우터가 기전을 못 정한 경우에도 «직접 결합하지 않아» 라고 적힌다.

    이제 이유는 **아는 쪽(호출부)이 넣는다.** 안 주면 «이유는 위에
    적혀 있다» 까지만 말하고 **원인을 지어내지 않는다.**
    """
    if not s1:
        return _EMPTY % (_esc(why) if why else
                         "구조 검증을 돌리지 않았습니다. "
                         "이유는 결과 본문에 적혀 있습니다.")
    lab = s1.get("label")
    url = s1.get("cif_url")
    if lab == "오류":
        return _EMPTY % ("구조 조회에 <b>실패</b>했다 — %s<br>"
                         "<b>구조가 없다는 뜻이 아니다.</b>"
                         % _esc(s1.get("why", "")))
    if not url:
        # ── **«없다» 로 끝내면 «방법이 없다» 로 읽힌다** (08-24) ──────────
        #
        #   승우가 `Nirmatrelvir / COVID-19` 를 넣고 물었다 —
        #   *«구조가 알파폴드에 없다고 안 뽑히네, 그러면 방법이 없는 거지?»*
        #   **판정은 나왔다.** 안 나온 건 3D 뷰어뿐이다. 그런데 화면이
        #   «AlphaFold 에 없다» 까지만 말하니 **결핍으로 읽혔다.**
        #
        #   실제로는 반대다. 3CLpro 는 **실험 구조가 수천 건**이고
        #   (`6LU7`·`5R…`·`7G…` 계열), 결함 94 가 *«결정 구조가 있는데
        #   예측 구조로 신뢰도를 재는 것은 자료원 선택의 오류»* 라고
        #   적어 뒀다. **예측이 없는 것이 여기서는 정답에 가깝다.**
        #
        #   그 수(`pdb_n`)를 `assess()` 가 **이미 실어 보내고 있었다.**
        #   붙이는 코드가 **좌표가 있어야 도달하는 자리**에만 있었을 뿐이다
        #   — 즉 **구조가 없는 바로 그 경우에** 가장 중요한 사실이 빠졌다.
        #   `CLAUDE.md §4` — **해석 문구를 상수로 고정하지 마라. 방향을
        #   데이터에서 읽어라.**
        #
        #   ⚠ 문구는 결함 90·94 의 경계를 지킨다 — 이 수는 **UniProt 항목
        #     전체**에 붙은 것이라 여러 성숙 사슬 구조가 섞여 있다.
        #     *«이 사슬의 실험 구조가 N건»* 이라고 적으면 결함 90 을
        #     반대편에서 되풀이하는 것이다.
        msg = ("AlphaFold에 이 표적의 예측 구조가 없다 — %s"
               % _esc(s1.get("why", "")))
        n = s1.get("pdb_n")
        if n:
            msg += ("<br><b>다만 자료가 없는 것은 아니다.</b> 이 UniProt "
                    "항목에는 <b>실험 구조가 %d건</b> 연결돼 있다 — "
                    "결정 구조가 있는 표적에서는 <b>예측 구조를 쓰는 것이 "
                    "오히려 자료원 선택의 오류</b>다. 도킹 경로는 예측 대신 "
                    "실험 구조로 간다. <span style=\"color:#8a94a0\">(어느 "
                    "성숙 사슬을 덮는 구조인지는 안 봤다 · 이 수는 항목 "
                    "전체의 것이다)</span>" % n)
        return _EMPTY % msg

    p = s1.get("plddt") or {}
    # ── **PDB 를 쓴다. CIF 로는 색이 안 나온다** (결함 113) ────────────
    #
    #   08-11 실측. CIF 로 그렸더니 카툰이 **전부 주황**(<50 · 무질서
    #   가능)이었다. 브라우저에서 원자를 세어 보니 —
    #
    #     3Dmol CIF 파서  원자 9,120개 · **b 값 0개**
    #     3Dmol PDB 파서  원자 9,120개 · b 값 9,120개 · 평균 91.3
    #
    #   CIF 에 `B_iso_or_equiv` 는 **있다**(첫 원자 31.95). 3Dmol 의 CIF
    #   파서가 그걸 `atom.b` 로 안 옮긴다. 그래서 `a.b` 가 undefined 가
    #   되고 `>90 / >70 / >50` 이 전부 거짓이라 **마지막 구간**으로 떨어졌다.
    #
    #   **이게 오늘 것 중 가장 나쁘다.** 안 그려지는 것보다 나쁘다 —
    #   화면이 우리 판정(`신뢰 91.1`)과 **정반대**를 말했다.
    #
    #   덤으로 우리 수치가 독립 확인됐다. 브라우저는 전 원자로 91.3·
    #   70미만 5%, 우리는 CA 만으로 91.1·5%. **같은 답이다.**
    url = p.get("pdb_url") or url
    mean = p.get("mean")
    frac = p.get("frac_low")
    verdict = VERDICT.get(lab)
    if verdict is None:
        # 라벨이 늘었는데 여기를 안 고친 것이다. **조용히 남의 문구를
        # 빌려 쓰지 않는다** — 그게 결함 100이었다.
        verdict = "이 라벨(<b>%s</b>)에 대한 화면 문구가 <b>없다</b>" % _esc(lab)

    # ── 무엇을 보고 있는지 적는다 (결함 90·98) ────────────────────────
    #   AFDB 는 긴 단백질을 **단편으로** 준다. 구간을 안 적으면 심사위원이
    #   전장 구조라고 읽는다 — 실측에서 P0DTC1(4,405잔기)의 첫 단편이
    #   **1566–1868** 이었다.
    bits = []
    ch = s1.get("chain")
    if ch:
        bits.append("성숙 사슬 <b>%s</b> (%d–%d)"
                    % (_esc(ch.get("name", "")), ch["start"], ch["end"]))
    if p.get("start") and p.get("end"):
        bits.append("모델이 덮는 구간 <b>%d–%d</b>%s"
                    % (p["start"], p["end"],
                       (" · 단편 %d개 중 하나" % p["n_frag"])
                       if (p.get("n_frag") or 0) > 1 else ""))
    if p.get("n_site"):
        bits.append("활성부위 주석 <b>%d개 중 %d개</b>가 이 구간 안"
                    % (p["n_site"], p.get("n_site_used") or 0))
    if s1.get("pdb_n"):
        # **괄호를 빼면 안 된다** (결함 94). 이 수는 UniProt 항목 전체에
        # 붙은 것이라 여러 성숙 사슬 구조가 섞여 있다. *"이 사슬의 실험
        # 구조가 N건"* 이라고 읽히면 그게 결함 90을 반대편에서 되풀이하는
        # 것이다. 08-11에 이 문장을 `why` 에서 여기로 옮겼다(결함 108) —
        # **넓은 칸이니까 끝까지 적을 수 있다.**
        bits.append("이 UniProt 항목에 <b>실험 구조 %d건</b> — 예측 구조는 "
                    "<b>대리물</b>이다 (어느 성숙 사슬을 덮는 구조인지는 "
                    "<b>안 봤다</b>)" % s1["pdb_n"])
    if bits:
        verdict += "<br>" + " · ".join(bits)

    legend = "".join(
        '<span style="display:inline-block;margin-right:10px;white-space:nowrap">'
        '<span style="display:inline-block;width:11px;height:11px;background:%s;'
        'border-radius:2px;vertical-align:-1px"></span> %s</span>' % (c, t)
        for _, c, t in BANDS)

    grad = "".join('if(a.b>%d)return"%s";' % (lo, col) for lo, col, _ in BANDS[:-1])
    uid = "v%d" % (abs(hash(url)) % 10 ** 8)

    return """
<div style="border:1px solid #d8dde3;border-radius:8px;overflow:hidden;
     background:#fff;color:#1f2937">
  <div style="padding:9px 12px;background:#f3f5f7;color:#1f2937;
       font-size:12.5px;border-bottom:1px solid #e3e7eb">
    <b>예측 구조 신뢰도 (pLDDT)</b> — 평균 %s · 70 미만 잔기 %s<br>
    <span style="color:#5a6570">%s</span>
  </div>
  <div class="br-3d" data-cif="%s"
       style="position:relative;height:%dpx;background:#fff;color:#1f2937"></div>
  <div style="padding:8px 12px;background:#fff;font-size:11.5px;
       color:#5a6570;border-top:1px solid #e3e7eb;line-height:1.9">%s<br>
    <b>이 색은 예측 신뢰도다. 결합 세기가 아니다.</b>
    구조를 얼마나 믿을 수 있는지만 나타낸다.
  </div>
</div>""" % (
        ("%.1f" % mean) if mean is not None else "?",
        ("%.0f%%" % (100 * frac)) if frac is not None else "?",
        verdict, _esc(url), height, legend)


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
