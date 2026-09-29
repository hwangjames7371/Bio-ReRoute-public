# -*- coding: utf-8 -*-
"""Bio-ReRoute 웹 데모 — **얇은 껍데기다. 로직은 `bioreroute/` 에 있다.**

    py app.py                      # 로컬 (http://localhost:7866)
    (Hugging Face Spaces 는 이 파일을 자동으로 찾는다)

## 탭 순서가 이 화면의 설계다

| 탭 | 왜 그 자리인가 |
|---|---|
| ① 판정 사례 | **기본값.** 미리 구운 실제 실행 결과 — 즉시 뜨고 강한 것부터 보인다 |
| ② 직접 검증 | 라이브. 느리거나 죽어도 **①은 멀쩡하다** |
| ③ 우리가 우리를 반증한 기록 | 결함·봉인. 이 프로젝트의 실제 기여 |

**라이브를 기본값에서 내린 이유는 우리 실측이다.** 봉인 예측 80건에서
임의 가설의 **55%가 `보류`** 로 나왔다(음성대조만 보면 85%).
근거가 없으면 기권하는 것이 옳은 동작인데, 첫 화면이 그거면 무능으로 읽힌다.

## 숫자를 이 파일에 적지 않는다

`결함 N건`·`봉인 M개` 를 여기 타이핑하면 다음에 하나 늘었을 때
**화면만 거짓말한다.** `bioreroute/evidence.py` 가 산출물에서 센다.

> 이 문단이 실제로 `docaudit` 에 걸린 적이 있다 — *"하드코딩하지 마라"*
> 를 설명하려고 적은 예시 숫자가 **현재 주장으로 읽혔다.**
> 예외를 늘리는 대신 **문구에서 숫자를 뺐다.** 예외가 쌓이면 가드가 썩는다.

> **이 파일은 실제 Gradio로 띄워 보지 않았다** (설치가 막힌 환경에서 썼다).
> 로직은 `demo.py`·`evidence.py` 에서 전 경로를 시험했고, 배선은 가짜
> gradio로 확인했다. **화면 모양은 로컬에서 한 번 봐야 한다.**
"""

import os
import sys

import gradio as gr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bioreroute import dash, demo, evidence, viewer, webui   # noqa: E402
from bioreroute.core import profiles             # noqa: E402

# ── 조립은 **`webui.py` 가 한다** (08-20) ─────────────────────
#
#   프레임워크를 갈아도 안 바뀌는 440줄을 거기로 옮겼다. 여기는
#   **조립된 문자열을 위젯에 꽂는 일**만 한다.
#
#   ⚠ **사본을 두지 않는다.** 08-19 하루에 «같은 것을 두 곳에서
#     그려서 갈라진» 결함이 셋 나왔다(283·287). 이름을 다시 묶어
#     두는 것은 옛 호출부가 그대로 돌게 하기 위한 것이고,
#     **정의는 한 곳뿐**이다.
_plddt_cell = webui._plddt_cell
_md_result = webui._md_result
_case_labels = webui._case_labels
show_case = webui.show_case
_md_steps = webui._md_steps
_disease_detail = webui._disease_detail
_live_struct = webui._live_struct
_live_left = webui._live_left
_md_evidence = webui._md_evidence
_entry_of = webui._entry_of
_s2_of = webui._s2_of
_dash_card = webui._dash_card

# ── Gradio 6.0 에서 `theme` 이 Blocks → launch 로 옮겨졌다 ──────────────
#   버전을 가려서 넣는다. 한쪽에 고정하면 다른 쪽에서 경고나 오류가 난다.
#   **배포지의 Gradio 판을 내가 고를 수 없으므로** 양쪽을 다 받는다.
try:
    _GR_MAJOR = int(str(gr.__version__).split(".")[0])
except Exception:
    _GR_MAJOR = 6
_THEME_ON_LAUNCH = _GR_MAJOR >= 6
_THEME = gr.themes.Soft()

# ── 브라우저 자동 번역을 끈다 (결함 77) ────────────────────────────────
#
#   08-07, 브라우저로 화면을 읽다가 발견했다. Edge 가 이 페이지를
#   **한국어로 번역하고 있었다** — 이미 한국어인 페이지를.
#
#     hydroxychloroquine                       → 하이드록시클로로퀸
#     metformin / Malignant neoplasm of breast → 메트포르민 / 유방 악성 신생물
#     factcheck → 팩트체크        veto → 거부권
#     명세는 봉인돼 있다(`사전명세_라우터분기.md`). → 코드 스팬이 문장 밖으로 밀림
#     PMID `40579605` · w=0.84 — CONCLUSION…    → 번호가 문장 끝으로 이동
#
#   원인은 gradio 템플릿의 `<html lang="en">` 이다. 내용은 한국어인데
#   **영어라고 선언돼 있으니** 브라우저가 번역 대상으로 본다.
#
#   ## 왜 이게 심사에서 위험한가
#
#   ① **약물명이 번역된다.** `메트포르민 / 유방 악성 신생물` 은 PubMed 에
#      검색되지 않는 문자열이다. 재현하려는 심사위원이 막힌다
#   ② **인라인 코드가 문장 밖으로 밀린다.** PMID 가 근거 문장에서 떨어져
#      나가면 *"판정마다 PMID 가 붙는다"* 는 우리 핵심 주장이 화면에서
#      깨져 보인다
#   ③ 우리가 통제할 수 없다 — **심사위원 브라우저 설정**이다
#
#   `lang="ko"` 를 선언하고 `translate=no` 를 건다. 번역을 금지하는 게
#   아니라 **"이미 한국어다"라고 사실을 적는 것**이다.
# ── 뷰어 부트스트랩 ────────────────────────────────────────────────
#
#   마크다운 안의 `<script>` 는 안 돈다(결함 112). 그래서 **화면이 바뀔
#   때마다 감시**해서 초기화한다. gradio 는 탭·후보를 바꿀 때 DOM 을
#   갈아끼우므로 한 번만 도는 초기화로는 부족하다.
#
#   `viewer.render()` 는 이제 `<script>` 를 안 낸다 — `data-cif` 를 단
#   빈 div 만 낸다. **그리는 일은 전부 여기서** 한다.
_VIEWER_BOOT = (
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/3Dmol/2.0.4/'
    '3Dmol-min.js"></script>'
    "<script>(function(){"
    "function draw(el){"
    "  if(el.dataset.done)return; "
    "  if(!window.$3Dmol){"
    "    el.innerHTML='<div style=\"padding:14px;font-size:12.5px;color:#5a6570\">"
    "<b>3Dmol.js 를 못 불러왔다.</b><br>구조가 없다는 뜻이 아니다 — "
    "그리는 라이브러리가 안 왔다.</div>'; return;}"
    "  el.dataset.done=1;"
    "  var v=$3Dmol.createViewer(el,{backgroundColor:'white'});"
    "  $3Dmol.download('url:'+el.dataset.cif,v,{},function(m){"
    # ── **b 값이 없으면 «무질서»로 칠하지 않는다** (결함 113) ──
    #   3Dmol 의 CIF 파서는 `B_iso_or_equiv` 를 `atom.b` 로 안 옮긴다.
    #   그러면 `a.b` 가 undefined 라 비교가 전부 거짓이 되고 **마지막
    #   구간(주황·무질서 가능)** 으로 떨어진다. 08-11에 화면이 그렇게
    #   `신뢰 91.1` 짜리를 통째로 주황으로 칠했다.
    #   **안 그려지는 것보다 나쁘다** — 판정과 정반대를 말한다.
    "    var at=m.selectedAtoms({});"
    "    var ok=at.some(function(a){return typeof a.b==='number'&&!isNaN(a.b);});"
    "    if(!ok){"
    "      v.setStyle({},{cartoon:{color:'#9aa4ad'}}); v.zoomTo(); v.render();"
    "      var n=document.createElement('div');"
    "      n.style.cssText='padding:8px 12px;font-size:11.5px;color:#b45309;"
    "background:#fffbeb';"
    "      n.innerHTML='<b>pLDDT 색칠을 못 한다</b> — 이 좌표 파일에 신뢰도"
    " 값이 안 들어 있다. <b>무질서하다는 뜻이 아니다.</b>';"
    "      el.parentNode.insertBefore(n,el.nextSibling); return;}"
    "    v.setStyle({},{cartoon:{colorfunc:function(a){"
    "      if(a.b>90)return'#0053D6'; if(a.b>70)return'#65CBF3';"
    "      if(a.b>50)return'#FFDB13'; return'#FF7D45';}}});"
    "    v.zoomTo(); v.render();});}"
    # ── **감시기가 자기 변경에 반응하면 안 된다** (결함 115) ──────
    #   초판은 `MutationObserver(scan)` 이 `document.documentElement` 를
    #   `subtree:true` 로 감시했다. 그런데 `draw()` 가 **DOM 을 바꾼다** —
    #   `dataset.done`, 경고 div 삽입, 그리고 3Dmol 이 캔버스를 만든다.
    #   gradio 도 쉴 새 없이 갈아끼운다. 08-11에 브라우저가 **세 번 얼었다.**
    #
    #   셋으로 막는다 —
    #     ① 그릴 것이 없으면 **즉시 빠진다** (선택자에 `:not([data-done])`)
    #     ② 그리는 동안 **감시를 끊는다**
    #     ③ 프레임당 한 번으로 **묶는다**
    #
    #   **발표장에서 심사위원 브라우저가 멎으면 그걸로 끝이다.**
    "var mo=null, queued=false;"
    "function scan(){"
    "  queued=false;"
    "  var t=document.querySelectorAll('div.br-3d[data-cif]:not([data-done])');"
    "  if(!t.length)return;"
    "  if(mo)mo.disconnect();"
    "  try{ for(var i=0;i<t.length;i++) draw(t[i]); }"
    "  finally{ if(mo)mo.observe(document.body,{childList:true,subtree:true}); }}"
    "function ping(){ if(queued)return; queued=true;"
    "  requestAnimationFrame(scan); }"
    "mo=new MutationObserver(ping);"
    "mo.observe(document.body,{childList:true,subtree:true});"
    "window.addEventListener('load',ping); setTimeout(ping,800);"
    "})();</script>"
)

_NOTRANSLATE = (
    '<meta name="google" content="notranslate">'
    "<script>document.documentElement.lang='ko';"
    "document.documentElement.setAttribute('translate','no');"
    "document.documentElement.classList.add('notranslate');</script>"
    # ── 한글 글꼴 (08-10) ───────────────────────────────────────
    #   실측: gradio 6 의 body 글꼴이 `Arial, Helvetica, sans-serif` 다.
    #   한글이 없으니 OS 대체 글꼴로 떨어지고, 그게 화면이 딱딱해 보이는
    #   가장 큰 원인이었다. **`<link>` 로 건다** — `css` 안의 `@import` 는
    #   gradio 가 어떻게 감싸는지에 따라 안 먹을 수 있다.
    #   CDN 이 막히면 아래 대체 글꼴 사슬로 떨어질 뿐 화면은 안 죽는다.
    '<link rel="stylesheet" as="style" crossorigin '
    'href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/'
    'dist/web/variable/pretendardvariable-dynamic-subset.min.css">'
    # ── 3Dmol.js — **`head` 에 건다** (결함 112) ────────────────────
    #
    #   08-11 실측. 뷰어가 `<script src=…3Dmol…>` 을 마크다운에 담아
    #   내보내고 있었는데 화면에서 재 보니 —
    #
    #     script 태그   DOM 에 **있다**
    #     window.$3Dmol **undefined**
    #     뷰어 div      높이 340 · 자식 0
    #
    #   **브라우저는 `innerHTML` 로 삽입된 `<script>` 를 실행하지 않는다.**
    #   HTML 규격이 그렇고, gradio 는 마크다운을 그렇게 그린다. 즉 이
    #   뷰어는 **처음부터 한 번도 돈 적이 없다** — 시험 [47]은 반환
    #   문자열에 pLDDT 숫자가 있는지만 봤다.
    #
    #   `head` 에 넣으면 브라우저가 문서를 파싱하며 진짜로 실행한다.
    #   CDN 이 막히면 `$3Dmol` 이 안 뜨고 아래 부트스트랩이 그렇다고
    #   적는다 — **빈 상자를 내지 않는다.**
    + _VIEWER_BOOT)
# gradio 6 은 `head` 도 launch 로 옮겼다(테마와 같다). 4·5 는 Blocks 에 있다.
#
# **`css` 도 같은 자리에 있다** — 08-10에 판정 배지를 넣으려고
# `gr.Blocks(css=…)` 라고 썼다가, 진짜 gradio 6.22.0 소스를 읽어 보니
# `Blocks.__init__` 인자가 **`title`·`fill_height` 둘뿐**이었다.
# `css`·`css_paths`·`theme`·`head`·`head_paths` 는 전부 `launch()` 로 갔다.
# **세 번째로 같은 함정이다**(theme → head → css).
def _ui_kw():
    """판 차이를 한자리에서 가른다. 여기 말고 다른 데서 갈라 쓰면 또 어긋난다."""
    return {"theme": _THEME, "head": _NOTRANSLATE, "css": _CSS}


_BLOCKS_KW = {} if _THEME_ON_LAUNCH else None   # 아래 `_CSS` 정의 뒤에 채운다

HEAD = """
# Bio-ReRoute
**기존 약을 새 질환에 써도 될까 — 그 가설을 «반박하는 근거»부터 찾아 드립니다.**
판정마다 **논문 번호(PMID)·인용 원문·가중치**가 함께 남습니다.
"""
# 대회 이름은 뺐다 — 이름을 박으면 쓰는 자리마다 고쳐야 하고,
# **고치는 걸 잊으면 낡은 이름이 화면에 남는다.**

# ── 화면 조각은 `dash` 가 갖는다 ──────────────────────────────────
#   `app` 과 `dash` 가 각자 배지를 만들면 **두 화면의 색이 갈린다.**
#   숫자를 두 곳에 적지 않는 것과 같은 이유다.
VERDICT_ICON = webui.VERDICT_ICON
verdict_badge = webui.verdict_badge
# ── 화면 서식 (08-10) ────────────────────────────────────────────
#
#   **브라우저로 직접 보고 고쳤다.** 실측한 것 —
#
#     body 글꼴이 `Arial, Helvetica, sans-serif` 였다.
#       → 한글이 OS 기본 대체 글꼴로 떨어진다. 가장 큰 원인이 이거였다
#     표가 `border: 0.667px solid rgb(31,41,55)` 전면 격자였다
#       → 칸마다 진한 선이 그어져 **딱딱해 보인다**
#     좁은 칸에서 머리글이 `유\n망`, `기\n각` 으로 **글자 단위로 쪼개졌다**
#       → 한국어에 `word-break` 기본값이 맞지 않는다
#
#   ## 색을 하드코딩하지 않는다
#
#   gradio 가 `--body-text-color`·`--border-color-primary` 같은 변수를
#   내주고 **그게 다크 모드에서 뒤집힌다.** `rgba(0,0,0,…)` 을 박으면
#   어두운 화면에서 안 보인다 — 심사위원 OS 설정은 우리가 못 고른다.
#   판정 배지 넷만 고정 색이다. **그건 장식이 아니라 뜻**이라서 그렇다.
#
#   ## 폭 — gradio 가 `.main` 을 **1024px 로 가둔다** (08-10 실측)
#
#     .main.fillable   max-width 1024px · margin 0 116px   ← 좌우가 버려진다
#     실제 본문 폭      960px  (1272px 화면에서)
#
#   1201px 로 넓혔다(+25%). **무한정 넓히지는 않는다** — 1680px 에서 멈춘다.
#   4K 모니터에서 글이 화면 끝까지 가면 눈이 줄을 놓친다.
_CSS = """
/* ── 진단서 ⑤ — **강약이 `**굵게**` 하나뿐이었다** ──────────────
   출처·주석·부연을 **작은 회색**으로 내려 세 층을 만든다:
     숫자·판정(가장 강) / 근거 본문(보통) / **출처·주석(약함)**
   지금까지는 셋이 다 같은 크기라 굵은 글씨가 신호를 잃었다. */
/* 판정별 개수 알약 — 배지보다 작고 한 줄에 나란히 선다 */
.br-pill{display:inline-block;padding:3px 11px;border-radius:999px;
  font-size:13px;font-weight:600;margin-right:4px;line-height:1.7}
.br-pill b{font-size:14.5px;margin-left:2px}

.br-sub, .br-sub *{font-size:12.5px !important;
  color:var(--body-text-color-subdued) !important;line-height:1.65 !important}

/* `!important` 없이는 진다 — gradio 규칙이 `.main.fillable.svelte-…` 로
   특이도가 더 높다. 08-10에 `!important` 없이 넣었다가 **화면에서 아무
   변화가 없는 것을 보고** 알았다. 커밋했다고 적용된 게 아니다. */
.gradio-container .main{max-width:min(100%,1680px) !important;
  margin:0 auto !important;padding:14px 28px !important}
.gradio-container, .gradio-container button, .gradio-container input,
.gradio-container label, .gradio-container .prose{
  font-family:'Pretendard Variable',Pretendard,-apple-system,'Segoe UI',
    'Malgun Gothic',system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;letter-spacing:-.01em}
.gradio-container .prose,.gradio-container .prose th,
.gradio-container .prose td,.gradio-container label{
  word-break:keep-all;overflow-wrap:break-word}
.gradio-container .prose{font-size:15px;line-height:1.72}
.gradio-container .prose table{border:0;border-collapse:separate;border-spacing:0;
  width:100%;margin:.9rem 0 1.2rem;font-size:13.5px;font-variant-numeric:tabular-nums}
.gradio-container .prose th{border:0;
  border-bottom:1.5px solid var(--table-border-color);
  padding:8px 12px;text-align:left;font-weight:600;font-size:12.5px;
  letter-spacing:.02em;color:var(--body-text-color-subdued);
  background:transparent;white-space:normal}
.gradio-container .prose td{border:0;
  border-bottom:1px solid var(--border-color-primary);
  padding:9px 12px;vertical-align:top}
.gradio-container .prose tr:last-child td{border-bottom:0}
.gradio-container .prose h1{font-size:26px;font-weight:700;
  letter-spacing:-.03em;margin:0 0 .3rem}
.gradio-container .prose h2{font-size:19px;margin:1.6rem 0 .5rem}
.gradio-container .prose h3{font-size:16.5px;margin:1.4rem 0 .45rem}
.gradio-container .prose h4{font-size:14px;margin:1.3rem 0 .4rem;
  color:var(--body-text-color-subdued);letter-spacing:.01em;font-weight:600}
.gradio-container .prose blockquote{
  border-left:2.5px solid var(--border-color-accent);
  background:var(--color-accent-soft);border-radius:0 8px 8px 0;
  margin:.9rem 0;padding:.6rem .9rem;font-size:13.5px;line-height:1.65}
.gradio-container .prose blockquote p{margin:.15rem 0}
/* ── 상자를 **없앤다** (08-10 3차) ──────────────────────────────
   승우: *"아직도 회색 바탕에 글씨 있는 것처럼 보여."* 맞다 —
   약 이름을 `br-q` 로 뺐는데도 **15개가 남아 있었다.** 세어 보니
   대부분 PMID 였고, 나머지는 `보류`·`모름`·`철회` 같은 **판정 낱말**이다.
   셋 다 코드가 아니다.

   낱말을 하나씩 고치는 대신 **규칙을 고쳤다** — 배경을 지우고
   등폭 글꼴만 남긴다. 식별자는 글꼴로 구분되지 상자로 구분되지 않는다.

   글꼴 사슬이 요점이다: `Consolas` 에 한글 글자가 없으므로 브라우저가
   **글자 단위로** Pretendard 로 떨어진다. 그래서 `39264960` 은 등폭,
   `보류` 는 한글 본문 글꼴로 나온다. 한글을 등폭에 넣으면 못 봐준다.

   다크 모드 대응은 `color:inherit` 하나로 끝난다 — 배경이 없으니
   `--neutral-*` 가 안 뒤집히는 문제(위 참조)도 같이 사라졌다.

   ## 크기를 옆 글자에 맞춘다 (08-10 4차)

   승우: *"글자가 혼자 작다."* 실측하니 원인이 둘이었다 —

     ① `font-size:.95em` 이 **곱해진다.** 표 셀은 이미 13.5px 라
        13.5 × .95 = **12.8px** 로 떨어졌다
     ② 등폭 글꼴은 같은 px 에서도 **글자가 작다.**
        x-높이 비율 실측 — Pretendard **0.53** · Consolas **0.49** (8% 작다)

   `font-size:1em` 으로 ①을 없애고, `font-size-adjust:0.53` 으로 ②를
   없앤다. 이 속성은 **x-높이를 맞춰 주는 것**이라, 한글이 Pretendard 로
   떨어질 때는 이미 0.53 이라 아무 일도 안 일어난다. 딱 등폭 글자만 커진다.

   못 받는 브라우저는 `1em` 만 적용된다 — 조금 작을 뿐 안 깨진다.

   ## 등폭은 **진짜 코드에만** (08-10 5차)

   승우: *"글꼴도 같은 걸로는 안 되나."* 화면에 남은 것을 세어 보니 —

     진짜 코드 2개   `사전명세_라우터분기.md` · `verify_quote`
     식별자 6개      PMID (숫자만)
     판정 낱말 5개   `철회` `모름` `보류` `조건부` `97%`

   **11개가 코드가 아니다.** 등폭은 *"그대로 쳐야 한다"* 는 신호인데
   PMID 는 숫자만이라 `0`/`O` 혼동이 없고 약물명은 한 줄에 하나다.
   **식별자(`br-q`)는 본문 글꼴로, `code` 만 등폭으로** 가른다. */
.gradio-container .prose code, .gradio-container .br-q{
  background:transparent !important;border:0 !important;padding:0 !important;
  color:inherit !important;font-weight:500;font-size:1em !important}
/* 파일명·함수명 — **그대로 쳐야 하는 것**이라 글꼴이 신호다 */
.gradio-container .prose code{font-size-adjust:0.53;
  font-family:ui-monospace,'SFMono-Regular',Consolas,'Liberation Mono',
    'Pretendard Variable',Pretendard,monospace,sans-serif !important}
/* 식별자 — 옆 글자와 **같은 글꼴**. 굵기로만 구분한다 */
.gradio-container .br-q{letter-spacing:-.005em}

/* ECE 막대 — 앞판은 `"▓"*N` 이었다. 터미널 글자로 그린 막대가 화면에서
   **회색 상자 안의 검은 블록**으로 보였다. 진짜 막대로 바꾼다.
   **ECE 는 낮을수록 좋다** — 그래서 긴 쪽이 붉다. */
.br-bar{display:inline-block;width:64px;height:6px;border-radius:3px;
  background:rgba(127,127,127,.18);vertical-align:middle;
  margin-right:.45em;overflow:hidden}
.br-bar > i{display:block;height:100%;background:#E24B4A;border-radius:3px}
.br-bar-best > i{background:#639922}
.gradio-container .prose ul{margin:.5rem 0;padding-left:1.15rem}
.gradio-container .prose li{margin:.22rem 0}
.br-verdict{display:inline-flex;align-items:center;gap:.4rem;
  padding:.28rem .7rem;border-radius:9px;font-weight:600;font-size:1.02rem;
  line-height:1.25;letter-spacing:-.01em;white-space:nowrap}
/* 목록용 작은 배지 — 제목용(1.02rem)을 목록에 쓰면 줄마다 «제목» 이 선다.
   폭을 고정해 **왼쪽 끝이 세로로 정렬**된다 — 훑을 때 그게 제일 중요하다. */
.br-verdict.sm{font-size:.84rem;padding:.16rem .5rem;border-radius:7px;
  min-width:74px;justify-content:center;vertical-align:middle}
.br-verdict.sm .br-conf{font-size:.74rem;margin-left:.15rem}
.br-conf{font-weight:400;font-size:.82rem;opacity:.72;color:inherit !important}

/* 옵션 줄 — 주 입력보다 한 단 낮게. **체크박스는 부가 선택이므로
   주 입력(질환·라디오·버튼)과 같은 덩치를 가지면 안 된다.** 승우:
   «접근성 칸이 너무 커. 비율에 맞게 줄여줘» — Gradio 기본 블록이
   padding·min-height 를 입력 칸과 똑같이 준다. 그걸 걷어낸다. */
.br-optrow{margin-top:-10px !important;align-items:center !important;
  gap:.5rem !important}
.br-optrow>div:first-child{flex:0 0 auto !important;
  min-width:0 !important;width:auto !important;
  padding:0 !important;margin:0 !important;border:0 !important;
  background:transparent !important;box-shadow:none !important;
  min-height:0 !important}
.br-optrow>div:first-child .wrap,
.br-optrow>div:first-child .block{padding:0 !important;border:0 !important;
  background:transparent !important;min-height:0 !important}
.br-optrow label{font-size:12.5px !important;padding:0 !important;
  margin:0 !important;min-height:0 !important;gap:.32rem !important}
.br-optrow input[type=checkbox]{width:14px !important;height:14px !important;
  margin:0 !important}

/* ── 후보 상세 — «누른 사람은 이유를 물은 사람» ─────────────── */
/* 후보 상세 머리 — **상자를 쓰지 않는다.** 판정 배지가 이미 색을
   갖고 있어서 회색 판을 깔면 배지가 죽는다. 강조는 활자로 낸다 */
.br-detail{margin:.4rem 0 .8rem;padding:0 0 .55rem;
  border-bottom:2px solid var(--border-color-primary)}
.br-dhead{margin-bottom:.3rem}
.br-dname{font-size:17px;font-weight:700;line-height:1.35;
  color:var(--body-text-color)}
.br-dwhy{font-size:13px;margin-top:.1rem;
  color:var(--body-text-color-subdued)}
/* 셈 — 숫자를 오른쪽으로 세워 **자릿수가 눈에 맞게** */
.br-ledger{max-width:340px;margin:.1rem 0 .5rem;font-size:13px}
.br-lrow{display:flex;justify-content:space-between;gap:1rem;
  padding:.2rem .1rem}
.br-lrow b{font-variant-numeric:tabular-nums;font-weight:600}
.br-plus{color:#15803d}
.br-minus{color:#b91c1c}
.br-lsum{border-top:1px solid var(--border-color-primary);
  margin-top:.1rem;padding-top:.3rem}
.br-lend{border-top:2px solid var(--border-color-primary);
  margin-top:.15rem;padding-top:.3rem;font-size:15px}
.br-lend b{font-size:1.05rem}
/* 근거 무게 — **왼쪽 고정폭**이라 세로로 훑을 수 있다 */
.br-egrp{font-weight:600;font-size:.88rem;margin:.7rem 0 .25rem}
.br-evx{margin-left:0 !important;font-size:13px;padding:.35rem 0 .35rem .1rem;
  border-bottom:1px solid var(--border-color-primary)}
.br-evx b{color:var(--body-text-color);font-weight:500}
.br-w{display:inline-block;min-width:38px;text-align:right;
  margin-right:.5rem;padding:.05rem .3rem;border-radius:5px;
  font-variant-numeric:tabular-nums;font-size:11.5px;font-weight:700;
  background:var(--background-fill-secondary);
  color:var(--body-text-color-subdued)}
/* 근거 인용 — 이름이 `br-q` 면 `q_name()`(질의 이름)과 부딪힌다.
   실제로 화면 제목 «COVID-19» 가 들여쓴 이탤릭이 됐다(08-19) */
.br-quo{margin:.15rem 0 .15rem 46px;font-style:italic;opacity:.8;
  font-size:12.5px}
.br-evx .br-etail{margin-left:46px;display:block}

/* 단계 목록 — **표가 아니다.** 한 칸이 183자까지 가는데 표는 열 폭을
   가장 긴 칸에 맞춘다. 칩을 왼쪽 고정폭에 두면 근거 줄의 무게 칩과
   같은 리듬이 된다: [PASS] 약물다움 점검 · [2.88] 메타분석 */
.br-steps{margin:.1rem 0 .6rem}
.br-step{display:flex;gap:.55rem;align-items:flex-start;
  padding:.3rem 0;border-bottom:1px solid var(--border-color-primary)}
.br-step>.br-g{flex:0 0 62px;text-align:center;margin-top:.12rem}
.br-sbody{min-width:0;flex:1}
.br-sbody>b{font-size:13px;font-weight:600}
.br-sdesc{font-size:12.5px;line-height:1.5;
  color:var(--body-text-color-subdued)}
/* 안 돌린 단계는 **지우지 않고 낮춘다** — 무엇을 안 했나도 정보다 */
.br-sdim{opacity:.45}
.br-swarn{margin-top:.15rem;padding-left:.5rem;
  border-left:2px solid var(--color-accent-soft, #d1d5db);font-size:12px}

/* 무게표 실례 — 표 두 개 뒤에 오는 **결론 줄**이라 중앙에 세운다 */
.br-ex{margin:.3rem 0 .1rem;padding:.55rem .75rem;border-radius:8px;
  max-width:560px;border:1px solid var(--border-color-primary);
  background:var(--background-fill-secondary);font-size:12.5px;
  line-height:1.9;color:var(--body-text-color-subdued)}
.br-ex b{font-variant-numeric:tabular-nums;font-size:14px;
  color:var(--body-text-color)}
.br-ex span{font-size:11.5px;opacity:.8}
.br-exw{font-size:16px !important;color:var(--body-text-color) !important}
/* 접힘 — 열었을 때 본문이 여백 없이 붙어 비율이 깨졌다 */
.br-live details{margin:.5rem 0;padding:0}
.br-live details>summary{cursor:pointer;font-size:12.5px;font-weight:600;
  padding:.35rem 0;color:var(--body-text-color-subdued)}
.br-live details>summary:hover{color:var(--body-text-color)}
.br-live details[open]>summary{margin-bottom:.35rem;
  border-bottom:1px solid var(--border-color-primary)}
.br-live details table{font-size:12.5px;margin:.2rem 0 .6rem}
.br-live details table td,.br-live details table th{padding:.28rem .55rem}
/* 짧은 2열 표가 **전폭(1200px)으로 늘어나** 「무게」가 오른쪽 끝에
   가 있었다(08-19 화면). 열 폭은 내용에 맞춘다 */
.br-live details table{width:auto !important;min-width:0 !important;
  max-width:560px}
.br-live details table td:last-child,
.br-live details table th:last-child{white-space:nowrap}

/* 제목 위계 — `####` 가 자식(`.br-egrp`)보다 약했다. 부모가 자식보다
   가벼우면 그건 위계가 아니라 뒤집힌 순서다 */
.br-live h4{font-size:14.5px !important;font-weight:700 !important;
  color:var(--body-text-color) !important;margin:1.1rem 0 .35rem !important}
.br-egrp{font-weight:600;font-size:12px;letter-spacing:.02em;
  color:var(--body-text-color-subdued);margin:.7rem 0 .2rem}

/* 내려받기 — **부가 기능**이다. 주 버튼(검증하기)만 한 덩치면
   눈이 «다음에 누를 것» 을 잘못 고른다 */
.br-dl{max-width:210px !important;min-height:0 !important}
.br-dl button,.br-dl .wrap{font-size:12.5px !important;
  padding:.35rem .7rem !important;min-height:0 !important}
.br-dl label{font-size:12.5px !important;min-height:0 !important;
  padding:.35rem .7rem !important}

/* 안내 상자(`br-note`) — **굵게를 여기서 잠근다.** 문구마다 손으로
   `**` 를 빼도 다음 사람이 또 넣는다. 안내문은 «읽고 넘기는 층» 이라
   본문보다 가벼워야 하고, 그 안에서 다시 강약을 주면 층이 무너진다.
   ⚠ 다만 **하나만** 남긴다 — 진짜 못 넘길 문장이 있을 때 쓴다 */
.br-note{font-size:.86rem;line-height:1.55;opacity:.75}
.br-note strong,.br-note b{font-weight:600 !important;
  color:inherit !important}

/* 후보 고르기 — **목록 바로 아래.** 상자를 안 쓴다.
   `container=False` 로 Gradio 의 `div.form`(회색 #e5e7eb)을 아예 없애고,
   혹시 남는 판이 있으면 `:has()` 로 한 번 더 지운다 */
.br-pick{border:0 !important;background:transparent !important;
  padding:0 !important;margin:.1rem 0 .5rem !important}
.form:has(> .br-pick){background:transparent !important;border:0 !important}
/* 칩이 **줄바꿈 없이** 흘러 오른쪽 밖으로 잘렸다 (08-19 화면) */
.br-pick .wrap{flex-wrap:wrap !important;gap:.3rem !important;
  overflow:visible !important}
.br-pick label{font-size:12.5px !important;padding:.28rem .6rem !important;
  min-width:0 !important}

.br-cand{display:flex;align-items:baseline;gap:.55rem;margin:.15rem 0}
.br-cand b{font-size:1.0rem}
/* 근거 한 줄 — 들여쓰기로 «이 후보에 딸린 것» 임을 보인다 */
.br-ev{margin:.1rem 0 .1rem 84px;font-size:12.5px;
  color:var(--body-text-color-subdued)}
.br-ev q{font-style:italic;opacity:.85}

/* 게이트 결과 — 통과·건너뜀·분기·모름·수정을 색으로 가른다 */
.br-g{display:inline-block;padding:.16em .52em;border-radius:6px;
  font-size:11px;font-weight:600;letter-spacing:.03em;white-space:nowrap}
/* 근거 방향 — 칩 + 행 왼쪽 띠. `:has()` 가 없으면 칩만 남는다 */
.br-d{display:inline-block;padding:.14em .5em;border-radius:6px;
  font-size:11.5px;font-weight:600;white-space:nowrap}

/* ── 칩 색은 **뜻이라 절대 안 뒤집는다** ────────────────────────
   다크 모드에서 실측: gradio 가 `.prose` 아래 글자색을 흰색으로 덮어
   **칩이 배경만 남고 글자가 사라졌다.** 특이도를 올리고 `!important`
   를 건다 — 장식이면 양보하겠지만 **이건 판정이라 못 양보한다.**
   밝은 칩이 어두운 배경에 뜨는 것은 의도다(섬처럼 읽힌다). */
.gradio-container .br-g-ok{background:#E1F5EE !important;color:#0F6E56 !important}
.gradio-container .br-g-skip{background:#F1EFE8 !important;color:#5F5E5A !important}
.gradio-container .br-g-warn{background:#FAEEDA !important;color:#854F0B !important}
.gradio-container .br-g-branch{background:#E6F1FB !important;color:#185FA5 !important}
.gradio-container .br-g-fix{background:#EEEDFE !important;color:#534AB7 !important}
.gradio-container .br-g-muted{background:transparent !important;
  color:var(--body-text-color-subdued) !important;padding-left:0}
.gradio-container .br-d-sup{background:#EAF3DE !important;color:#3B6D11 !important}
.gradio-container .br-d-ref{background:#FCEBEB !important;color:#A32D2D !important}
.gradio-container .br-d-na{background:#F1EFE8 !important;color:#5F5E5A !important}
.gradio-container .br-v-기각{background:#FCEBEB !important;color:#A32D2D !important}
.gradio-container .br-v-유망{background:#EAF3DE !important;color:#3B6D11 !important}
.gradio-container .br-v-조건부{background:#FAEEDA !important;color:#854F0B !important}
.gradio-container .br-v-보류{background:#F1EFE8 !important;color:#5F5E5A !important}
.gradio-container .prose tr:has(.br-d-sup) td:first-child{
  box-shadow:inset 3px 0 0 #639922}
.gradio-container .prose tr:has(.br-d-ref) td:first-child{
  box-shadow:inset 3px 0 0 #E24B4A}
.gradio-container .prose tr:has(.br-v-기각) td:first-child{
  box-shadow:inset 3px 0 0 #E24B4A}
.gradio-container .prose tr:has(.br-v-유망) td:first-child{
  box-shadow:inset 3px 0 0 #639922}
.gradio-container .prose tr:has(.br-v-조건부) td:first-child{
  box-shadow:inset 3px 0 0 #EF9F27}
.gradio-container .prose tr:has(.br-v-보류) td:first-child{
  box-shadow:inset 3px 0 0 #B4B2A9}
.gradio-container .prose tr:has(.br-verdict) td{padding-top:11px;padding-bottom:11px}

/* 3분할이 **세 칸으로 보이게** — 제안서 §6 이 그렇게 썼다.
   `min-width` 를 안 풀면 gradio 가 칸마다 320px 를 요구해
   **셋째 칸이 아래로 접힌다**(실측). `sticky` 도 시도했다가 되돌렸다 —
   안쪽 스크롤바가 생기고 패널이 잘렸다. 겹 스크롤은 안 쓴다. */
.gradio-container .br-pane{background:var(--block-background-fill);
  border:1px solid var(--border-color-primary);border-radius:14px;
  padding:12px 16px 4px;min-width:0 !important;box-sizing:border-box;
  align-self:flex-start}
.gradio-container .br-pane > *{background:transparent}

/* ── 좁은 화면에서 **가로 스크롤바가 생기면 안 된다** (결함 103) ────────
   08-11 실측: 뷰포트 1045px 에서 왼쪽 칸이 194px 인데 4열 표(`유망·기각·
   조건부 균형·등록부 조회`)가 **274px** 를 요구해 넘쳤다. 발표는 우리가
   고른 해상도에서 안 돌아간다 — 프로젝터가 1280×720 이면 **가려진 칸이
   생기고, 가려진 것은 없는 것처럼 보인다.**
   `table-layout:fixed` 로 칸을 나눠 갖게 하고 머리글을 접는다. */
.gradio-container .br-pane table{width:100% !important;table-layout:fixed}
.gradio-container .br-pane th,.gradio-container .br-pane td{
  word-break:keep-all;overflow-wrap:anywhere}

/* ── 그런데 **칩이 든 표는 예외다** (결함 105) ─────────────────────
   위 `table-layout:fixed` 를 전 표에 걸었더니 칸이 **균등 분할**됐고,
   판정 칩(138px)이 139px 칸을 **12px 침범**했다. 08-11 실측 —
   승우가 *"살짝 겹치는 게 있는 것 같아"* 라고 한 것이 이것이다.

   `fixed` 는 **첫 행**으로 칸 폭을 정한다. 첫 행은 `th` 인데
   `td:has(.br-verdict){width:1%}` 는 `td` 만 본다 — 그래서 폭 힌트가
   통째로 무시됐다. **좁은 칸을 고치려다 넓은 칸을 깨뜨렸다.**

   칩이 있는 표만 `auto` 로 되돌린다. 브라우저에서 둘 다 쟀다 —
   칩 넘침 +12px → **−20px**, 좁은 칸(194px) 표 넘침 **0**. */
.gradio-container .br-pane table:has(.br-verdict),
.gradio-container .br-pane table:has(.br-g){table-layout:auto !important}
.gradio-container .br-pane table:has(.br-verdict) td,
.gradio-container .br-pane table:has(.br-g) td{white-space:normal}
.gradio-container .br-pane td:has(.br-verdict),
.gradio-container .br-pane td:has(.br-g),
.gradio-container .br-pane td:has(.br-d){white-space:nowrap !important;width:1% !important}

/* 칩이 든 칸은 **내용만큼만** 차지한다 — 안 그러면 게이트 이름이
   `S2 리간드 / 개발성` 으로 쪼개지고 설명 칸이 눌린다 */
.gradio-container .prose td:has(.br-g),
.gradio-container .prose td:has(.br-verdict),
.gradio-container .prose td:has(.br-d){width:1%;white-space:nowrap}
.gradio-container .prose td code{font-size:.82em}
"""
# `_CSS` 가 정의된 뒤라야 채울 수 있다.
if _BLOCKS_KW is None:
    _BLOCKS_KW = _ui_kw()


# ─────────────────────────────────────────────────────────────
# 공통 렌더
# ─────────────────────────────────────────────────────────────




# ─────────────────────────────────────────────────────────────
# 탭 ① 판정 사례
# ─────────────────────────────────────────────────────────────
_CASES = webui._CASES






CASES_INTRO = ("실제로 돌린 결과를 그대로 저장해 뒀습니다. "
               "판정이 서로 갈리도록 골랐습니다.")

# ⛔ 09-29 · 안내문에 **판정 확률을 손으로 적지 않는다** (결함 377)
#   «실측은 유망 97%» 와 «마지막 사례» 를 적어 뒀는데, 사례를 다시 구우니 플루복사민은
#   «조건부» 가 됐고 순서도 다섯째가 됐다. 확률은 사례 카드가 말한다. 여기 남는 말은
#   **자료와 맞는지 시험 [211] 이 본다**(네 판정이 다 있나 · 플루복사민이 정말 예상과 다른가).
CASES_MORE = """
바로 열리고 API 키가 없어도 보입니다. **전부 기각하는 시스템이 아니라는
것**을 먼저 보이려고 네 가지 판정이 다 나오게 골랐습니다.

**우리가 미리 적어 둔 예상과 어긋난 사례도 빼지 않았습니다.** 플루복사민은
「보류」의 대표 사례로 지목해 뒀는데 실제 판정은 달랐습니다 — 근거를 열면
왜 그렇게 됐는지 그대로 보입니다. 기록이 산출물이라는 주장의 가장 좋은 증명은
자기 오류를 보이는 것입니다.
"""

NO_CASES = """
### 저장된 사례가 없습니다

`demo_cases.json` 이 없습니다. 로컬에서 한 번 만들어 올려야 합니다.

```
py -c "from bioreroute import evidence; evidence.build_cases()"
```

<span class='br-sub'>없는 것을 있는 척하지 않습니다. 「직접 검증」 탭은
그대로 쓸 수 있습니다.</span>
"""


# ─────────────────────────────────────────────────────────────
# 탭 ② 직접 검증
# ─────────────────────────────────────────────────────────────
# ⚠ **시간은 실측으로 적는다** (08-21). 여기 «30~60초» 가 있었는데
#   처음 보는 쌍을 실제로 태워 보니 **133초**였다 —
#   `sildenafil / Alzheimer disease` · 새 LLM 3회. 단계별로는
#   초록 받아 읽기 71초 · 라우터 26초 · 회의주의자 32초.
#   `렌즈답변.md §796` 이 이미 *«30~60초라 적어 놓고 근거가 없다»* 고
#   적어 뒀는데 **화면 문구는 그대로였다** — 대장에 적는 것과 고치는 것은
#   다르다. 시연에서 1분에 심사위원이 「멈췄나」 한다.
#
# ⚠ **그 133초는 `gemini-2.5-flash` 다.** 그날 OpenAI 키가 막혀
#   폴백이 돌았다. 구운 사례는 `gpt-5.4-mini` 로 만들어져 있으니
#   **둘을 같은 시간이라고 말하면 안 된다.** 표본도 하나다.
#   그래서 화면에는 **범위만** 적는다. 키가 돌아오면 같은 쌍을 다시 재고
#   그때 숫자를 정한다 — `계획_8월` 에 남길 것.
# 09-29 · 결함 380 — «보류» 의 까닭을 **근거가 갈려서** 라고 적었는데, 봉인 예측 80건의 보류 44건 중 36건이
#   «질환 연결 문헌 0건 · 증거 없음» 이고 홀드아웃도 대부분 근거가 모자란 보류다. 까닭은 자료가 말하는 쪽으로 쓴다
#   (시험 [211]⑦ 이 봉인 예측 파일에서 다시 센다). `index.html` 의 같은 문장도 같이 고친다
LIVE_INTRO = ("약과 질환을 넣으면 논문을 실제로 읽고 판단합니다 — 처음 "
              "보는 쌍은 1~3분, 이미 읽은 쌍은 1초 안에 나옵니다. "
              "절반 넘게 「보류」가 나오는데, 대부분 판단할 근거가 모자라서입니다 — "
              "근거가 모자라거나 갈리면 억지로 결론 내지 않습니다.")

LIVE_MORE = """
우리 실측으로 임의 가설의 **55%가 `보류`** 다(봉인 예측 80건 기준.
음성 대조만 보면 85%). 근거가 없으면 판단하지 않는 것이 설계이고,
**그게 이 시스템이 파는 것이다.**

느리거나 죽어도 다른 탭은 멀쩡하다 — 미리 구운 결과를 읽기 때문이다.
"""


# 출력칸이 **비어 있으면 안 된다** (결함 104). gradio 는 진행 표시를
# 출력 컴포넌트 **안에** 그리는데, 빈 `gr.Markdown()` 은 높이가 0 이라
# 그릴 자리가 없다. 08-11 실측 — 승우가 *"에러가 난 것처럼 보인다"* 고 했고,
# 브라우저로 재니 그 칸이 **높이 0px** 이었다.
LIVE_IDLE = """### 아직 실행 전입니다

「검증하기」를 누르면 아래에 단계가 하나씩 쌓입니다 — 근거가 실제로
있는지 확인하고, 논문을 읽어 지지와 반박을 가르고, 검증 방식을 정하고,
반대 근거를 더 찾은 뒤 종합해 판정합니다.

<span class='br-sub'>처음 보는 쌍은 1~3분, 이미 읽은 쌍은 1초 안입니다.</span>
"""

_STAGES = webui._STAGES




def _disease_picks(res):
    """실행이 끝나면 후보 목록을 **고를 수 있게** 채운다.

    ## 라벨에서 질환을 뺀다 (08-19 화면)

    후보 이름이 `metformin / Tuberculosis` 라 **질환이 열 번 반복**됐다.
    질환은 바로 위 입력 칸에 있고 열 개가 전부 같다 — **다르지 않은
    것은 구별에 쓸모가 없다.** 칩이 넓어져 두 줄로 접혔다.

    Gradio 라디오는 `(보이는 값, 실제 값)` 쌍을 받는다. **실제 값은
    원래 이름 그대로** 두어 `candidate_detail` 이 안 깨진다.
    """
    names = dash.candidate_names(res)
    if not names:
        return gr.update(choices=[], value=None, visible=False)
    ch = []
    for n in names:
        short = n.split(" / ")[0].strip() if " / " in n else n
        ch.append((short or n, n))
    return gr.update(choices=ch, value=None, visible=True)






_WHY = webui._WHY


def _export(md, query):
    """근거 카드를 **파일로 내보낸다** — 제안서 §8.2 이행.

    §8.2 원문: *"산출물이 단순 판정이 아니라 **감사 가능한 근거 카드**
    이므로, 내부 심의·규제 제출·투자 판단의 입력으로 **그대로 쓰인다**"*

    **«그대로 쓰려면 가져갈 수 있어야 한다.»** 08-18 까지 화면에서
    복사도 저장도 안 됐다 — 약속한 산출물을 **손에 못 쥐어 줬다.**

    파일 안에 **언제·무엇으로 잰 값인지**를 머리말로 넣는다. 근거 카드가
    규제 제출물이 되려면 «언제 조회한 문헌인가» 가 본문에 있어야 한다.
    """
    import datetime as _dt
    import tempfile as _tf
    # ⚠ **표시 문구로 판단하지 않는다** (08-19). 앞판은
    #   `"근거 카드" not in md` 였는데, 그 제목을 «근거 N건» 으로
    #   바꾸자 **내려받기 칸이 조용히 사라졌다.** 시험 [143] 이
    #   잡았다 — «고친 자리의 이웃을 안 본다» 의 그 자리다.
    #
    #   이제 **구조 표식**(`br-detail` = 판정 머리)을 본다.
    #   문구는 갈아도 되고 구조는 시험이 지킨다.
    if not md or "br-detail" not in md:
        return gr.update(visible=False)
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    head = ("# Bio-ReRoute 근거 카드\n\n"
            "| | |\n|---|---|\n"
            "| 질의 | %s |\n| 조회 시각 | **%s** |\n"
            "| 모델 | %s |\n\n"
            "> **이 문서는 판정 근거이지 의학적 조언이 아니다.**\n"
            "> 문헌은 계속 늘고 판정은 그에 따라 움직인다 — "
            "**다시 조회하면 다를 수 있다.**\n\n---\n\n"
            % (query or "—", now, os.environ.get("BIOREROUTE_MODEL", "—")))
    d = _tf.mkdtemp(prefix="bioreroute_")
    safe = "".join(c if c.isalnum() or c in " -_" else "_"
                   for c in (query or "결과"))[:60].strip() or "결과"
    path = os.path.join(d, "%s.md" % safe)
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + md)
    return gr.update(value=path, visible=True)






# ── 위젯 껍데기 — **뜻을 위젯 값으로 번역만 한다** ────────────
#
#   `webui` 는 프레임워크를 모른다. «안 건드림» 을 `None` 으로,
#   후보 목록을 `dict` 로 돌려준다 — 그걸 gradio 말로 바꾸는 것이
#   여기 하는 일 전부다. **판단은 한 줄도 여기 없다.**
def _pick_example(q):
    box, why = webui._pick_example(q)
    return (gr.update() if box is None else box), why


def _dash_run(run, exit_):
    left, center, pick = webui._dash_run(run, exit_)
    return left, center, gr.update(**pick)


def run_live(text, exit_="표준", progress=gr.Progress()):
    """**제너레이터다.** 단계가 생길 때마다 화면에 흘려보낸다.

    `run_pair` 는 동기 함수이고 콜백으로만 단계를 알린다. 그래서 별
    스레드에서 돌리고 큐로 받는다. **스레드가 죽어도 화면은 안 멈춘다** —
    `finally` 에서 종료 표시를 넣고, 큐 대기에 시한을 둔다.
    """
    import queue
    import threading

    q: "queue.Queue" = queue.Queue()
    box = {}

    def on(stage, detail):
        q.put((stage, detail))

    def work():
        try:
            box["r"] = demo.run_pair(text or "", progress=on, exit_=exit_)
        except Exception as e:                     # 화면이 죽으면 안 된다
            box["e"] = "%s: %s" % (type(e).__name__, e)
        finally:
            q.put(None)

    th = threading.Thread(target=work, daemon=True)
    th.start()

    # ── 출력이 **둘**이다: 마크다운 + 3D 뷰어 (결함 259) ──────────
    #
    #   결함 251 에 *«3D canvas 는 여기 못 붙인다 — `gr.HTML` 이 아니면
    #   script 가 안 돈다»* 라고 적었다. **틀렸다.** `viewer.render()` 의
    #   반환에는 **`<script>` 가 한 개도 없다**(실측 0개). 그리는 것은
    #   `head` 에 걸린 **전역 MutationObserver** 이고, 그건
    #   `div.br-3d[data-cif]` 를 문서 어디서든 찾아 그린다.
    #
    #   즉 막고 있던 것은 «script 실행» 이 아니라 **출력 칸이 하나**라는
    #   것뿐이었다. 제너레이터는 **튜플로 여러 칸에 흘려보낼 수 있다.**
    #
    #   ⚠ **둘째 칸은 `gr.HTML` 이 아니라 `gr.State` 다** (결함 260).
    #     보이는 출력이 둘이면 gradio 가 **각 칸마다 진행 막대를 그린다** —
    #     승우가 *«막대기가 두 개 생겨서 돌아가고, 이쁘지가 않아»* 라고
    #     잡은 그것이다. `gr.State` 는 **렌더되지 않으므로 막대가 없다.**
    #     3D 는 `.then()` 으로 그 State 를 받아 채운다.
    steps = []
    yield _md_steps(steps), None
    while True:
        try:
            item = q.get(timeout=180)
        except Exception:                          # 180초 무응답
            yield ("### 응답이 없다\n\n180초 동안 아무 단계도 안 왔다. "
                   "**네트워크나 LLM 이 막힌 것**이지 판정이 아니다 — "
                   "`py -m bioreroute.netcheck` 로 확인해라."), False
            return
        if item is None:
            break
        steps.append(item)
        progress(min(0.95, len(steps) / float(_STAGES)),
                 desc="%s — %s" % (item[0], item[1] or ""))
        yield _md_steps(steps), None

    th.join(timeout=5)
    if box.get("e"):
        yield ("### 오류\n\n`%s`\n\n**판정이 아니다.** 조회나 실행이 실패한 것이다."
               % box["e"]), False
        return
    r = box.get("r") or {"상태": "오류", "메시지": "결과가 비었다"}
    # 정상일 때만 구조를 넘긴다. 구조 경로가 아니면 `s1` 이 `None` 이고,
    # 그때 `render(None)` 이 **«구조 경로가 아니다» 라고 적는다** — 빈 상자가 아니다.
    yield _md_result(r), (r.get("s1") if r.get("상태") == "정상" else False)


DISEASE_INTRO = (
    "질환 이름을 넣으면 후보 약물을 찾아 하나씩 검증합니다. "
    "볼 약이 이미 정해져 있다면 옆 탭에서 바로 검증하세요."
)
DISEASE_IDLE = (
    "질환 이름을 넣고 「후보 찾기」를 누르세요. 후보 열 개를 만들어 "
    "하나씩 논문으로 검증합니다.\n\n"
    # 09-29 · 라이브 점검 실측(COVID-19 · 제출 모델) — 처음 196초 · 다시 46초. 상한은 **시작 시점**에 건다
    #   (`demo._funnel_many` — 시작한 후보는 끝까지 간다) · «N초를 넘기면» 꼴은 시험 [211]⑥ 이 상수와 맞춘다
    "<span class='br-sub'>처음 도는 병명은 3분 남짓, 한 번 돌린 병명은 1분 안쪽입니다. 150초를 넘기면 "
    "아직 시작하지 못한 후보를 «못 봤다» 고 적습니다 — 그건 기각이 아니라 시간이 모자란 것입니다.</span>"
)


def run_disease_live(disease, acc, exit_="표준", entry="정방향",
                     progress=gr.Progress()):
    """병명 입구 — `run_live` 와 **같은 규약**으로 흘려보낸다.

    스레드 + 큐 구조를 그대로 쓴다. 다르게 만들면 한쪽만 고쳐지는 자리가
    생긴다(결함 189 계열 — 사본이 갈라지는 것과 같은 병).
    """
    import queue
    import threading

    q: "queue.Queue" = queue.Queue()
    box = {}

    def on(stage, detail):
        q.put((stage, detail))

    def work():
        try:
            box["r"] = demo.run_disease(disease or "", progress=on, exit_=exit_,
                                        entry=entry)
        except Exception as e:
            box["e"] = "%s: %s" % (type(e).__name__, e)
        finally:
            q.put(None)

    th = threading.Thread(target=work, daemon=True)
    th.start()

    # 출력이 **셋**이다: 후보 목록 · 그 뒤 · 결과 dict(`gr.State`).
    #   사이에 «후보 고르기» 칸이 들어간다(08-19).
    #   State 는 렌더가 안 되므로 **진행 막대가 하나**로 유지된다(결함 260).
    steps = []
    yield _md_steps(steps), "", None
    while True:
        try:
            item = q.get(timeout=200)      # 상한 150초 + 여유
        except Exception:
            yield ("### 응답이 없습니다\n\n200초 동안 아무 단계도 오지 "
                   "않았습니다. 네트워크나 모델이 막힌 것이지 판정이 "
                   "아닙니다."), "", None
            return
        if item is None:
            break
        steps.append(item)
        # 진행률 분모를 모른다 — 후보 수가 실행 중에 정해진다.
        # **모르는 것을 아는 척하지 않는다**: 상한에 천천히 붙인다.
        progress(min(0.95, len(steps) / 24.0),
                 desc="%s — %s" % (item[0], item[1] or ""))
        yield _md_steps(steps), "", None

    th.join(timeout=5)
    if box.get("e"):
        yield ("### 오류\n\n`%s`\n\n판정이 아니라 실행이 실패한 것입니다."
               % box["e"]), "", None
        return
    res = box.get("r") or {"ok": False, "상태": "오류", "메시지": "결과가 비었다"}
    head, tail = dash.disease_run_parts(res, acc_on=bool(acc))
    yield head, tail, res


# ─────────────────────────────────────────────────────────────
# 탭 ③ 우리가 우리를 반증한 기록
# ─────────────────────────────────────────────────────────────


NOT_DOING = """
- 새 후보를 발굴하지 않는다 (그건 `bioreroute.bench.discover` 다)
- 도킹·구조 예측을 하지 않는다 — **라우터가 건너뛰는 것이 설계다**
- 성능 우위를 주장하지 않는다. **검정력이 없다**
- 제안서 §3.3-9 「2축 대시보드·HITL」의 **일부**다. 전부가 아니다
- **의학적 조언을 하지 않는다**
"""

# ── 면책·AI 표기 (결함 54 · 제안서 §5 ⑤) ─────────────────────────
#
#   **한 줄로 눌렀지 없애지 않았다.** 요약은 항상 보이고 전문은 접힌다.
#   결함 54의 교훈은 *"스크린샷으로 떨어져 나가면 안 된다"* 였는데,
#   그건 **판정 문자열 안에도 같은 문구가 실려 있어서**(`demo.py`) 지켜진다.
#   여기서 줄이는 건 자리이지 노출이 아니다.
#
#   문구는 `demo` 상수를 그대로 읽는다 — 두 곳에 따로 적으면 갈라진다.
DISCLAIMER_ONE = ("⚠ 연구용 도구입니다 · 의학적 조언이 아닙니다 ｜ "
                  "🤖 AI 가 만든 결과입니다 — 다만 **판정 확률은 AI 가 "
                  "아니라 규칙으로 계산**하고, 인용은 초록 원문과 대조한 "
                  "것만 싣습니다.")
DISCLAIMER_FULL = (demo.AI_NOTICE + "\n\n" + demo.DISCLAIMER)

# ── 「어떻게 판단하나」 에는 안내문을 두지 않는다 (09-29 · 결함 377) ──────────
#   승우: «"신종 바이러스가 퍼진 상황을 가정한 실행 2건입니다. 미리 돌려 둔 결과라 바로
#   열립니다." 이걸 왜 넣은지 이해가 안 가 · 굳이 안 넣어도».
#   이 탭이 첫 화면이던 때(라이브가 첫인상이면 보류부터 보인다)의 머리말이었다. 지금은
#     · 중앙 칸이 실행마다 **무대 · 구운 시각 · ⚠ 의 뜻 · 빠진 것**을 이미 말한다 — 되풀이였다
#     · 실행 2 는 바이러스 무대가 아니고(부작용에서 거꾸로) 실행 1 에도 유방암 · 결핵이 있다 — 틀렸다
#     · 접힌 «이 화면은 무엇인가» 는 **«유망 97%»**(지금 조건부) · **«두 입구를 보인다»**(실행 2 의
#       «빠진 것» 이 «두 후보는 정방향으로 얻었다» 고 말한다)를 들고 있었다 — 화면이 화면을 반박했다
#   그래서 둘 다 뺐다. 웹(`web/server.py` · `index.html` · `app.js`)과 이 예비본이 같이 뺀다.










with gr.Blocks(title="Bio-ReRoute", **_BLOCKS_KW) as ui:
    gr.Markdown(HEAD)
    # **최상단 고정.** 탭보다 위다 (결함 54). 한 줄 요약은 항상 보이고
    # 전문은 접힌다 — 노출을 줄인 게 아니라 자리를 줄였다.
    gr.Markdown(DISCLAIMER_ONE, elem_classes=["br-note"])
    with gr.Accordion("면책·AI 표기 전문", open=False):
        gr.Markdown(DISCLAIMER_FULL)

    with gr.Tabs():
        # ── 제안서 §6 이 지정한 3분할 대시보드 ────────────────────
        #
        #   좌  두 축 토글 + 접근성      중  후보 + 근거 카드
        #   우  반증·구조·특허 뷰어      하  보정 곡선 + Time-to-Refute
        #   옆  같은 질의를 일반 LLM(B0)에 넣은 결과 나란히
        #
        # **첫 탭이다.** 제안서가 시연 무대로 지정한 화면이고, 라이브 입력이
        # 아니라 **고정 Run 1·2** 라 첫인상이 `보류 50%` 로 시작하지 않는다.
        # 내용은 전부 `bioreroute/dash.py` 가 만든다 — 이 파일은 배선만 한다.
        with gr.Tab("대시보드 · 어떻게 판단하나"):
            with gr.Row():
                run_pick = gr.Radio(dash.run_labels(), value=dash.run_labels()[0],
                                    label="실행", interactive=True, scale=2)
                exit_pick = gr.Radio(list(profiles.EXITS), value="표준",
                                     label="심사 기준",
                                     interactive=True, scale=2)
            # **후보를 세 칸 위로 올렸다** (08-10). 좁은 가운데 칸에 두면
            # 후보 셋이 두 줄로 접힌다(실측 724px 필요, 칸은 600px).
            # 그리고 후보 선택은 **세 칸 전부**를 바꾸는 컨트롤이라
            # 실행·출구 축과 같은 자리에 있는 것이 맞다.
            cand_pick = gr.Radio([], label="후보를 고르면 판단 과정이 열립니다",
                                 interactive=True)
            with gr.Row(equal_height=False):
                with gr.Column(scale=3, elem_classes=["br-pane"]):   # 좌
                    left_md = gr.Markdown()
                with gr.Column(scale=7, elem_classes=["br-pane"]):   # 중
                    center_md = gr.Markdown()
                    # **사고 과정이 먼저다.** 심사 기준 30점 항목이
                    # *"에이전트의 사고 과정을 투명하게 보여주는가"* 다.
                    think_md = gr.Markdown()
                    card_md = gr.Markdown()
                with gr.Column(scale=3, elem_classes=["br-pane"]):   # 우
                    gr.Markdown("#### 뷰어")
                    struct_html = gr.HTML()
                    patent_md = gr.Markdown()
            gr.Markdown("---")
            with gr.Row():                      # 하
                bottom_cal = gr.Markdown()
                bottom_tl = gr.Markdown()
            gr.Markdown("---")
            with gr.Row():
                side_md = gr.Markdown()         # 옆 (B0 대조)
                auto_md = gr.Markdown()         # 자율성 (심사 10점)

            run_pick.change(_dash_run, inputs=[run_pick, exit_pick],
                            outputs=[left_md, center_md, cand_pick])
            exit_pick.change(_dash_run, inputs=[run_pick, exit_pick],
                             outputs=[left_md, center_md, cand_pick])
            cand_pick.change(_dash_card, inputs=[cand_pick, exit_pick],
                             outputs=[think_md, card_md, struct_html,
                                      patent_md, side_md, left_md])
            ui.load(_dash_run, inputs=[run_pick, exit_pick],
                    outputs=[left_md, center_md, cand_pick])
            ui.load(lambda: (dash.bottom_calibration(), dash.bottom_timeline()),
                    outputs=[bottom_cal, bottom_tl])
            ui.load(dash.autonomy, outputs=auto_md)

        with gr.Tab("판정 사례 · 지난 결과 6건"):
            if _CASES:
                gr.Markdown(CASES_INTRO, elem_classes=["br-note"])
                with gr.Accordion("사례를 어떻게 골랐나", open=False):
                    gr.Markdown(CASES_MORE)
                # 다른 세 화면(대시보드·직접 검증·병명)이 모두
                #   «회색 판 없는 칩 + 위에 작은 안내» 로 통일돼 있다.
                #   **여기만 Gradio 기본 상자였다** (결함 280 ②와 같은 자리).
                labels = _case_labels()
                gr.Markdown("<span class='br-sub'>사례를 고르면 판정과 "
                            "근거가 열립니다</span>")
                picker = gr.Radio(labels, value=labels[0], show_label=False,
                                  container=False, interactive=True,
                                  elem_classes=["br-pick"])
                case_out = gr.Markdown(show_case(labels[0]))
                picker.change(show_case, inputs=picker, outputs=case_out)
            else:
                gr.Markdown(NO_CASES)

        with gr.Tab("직접 검증 · 내 가설 넣기"):
            gr.Markdown(LIVE_INTRO, elem_classes=["br-note"])
            with gr.Accordion("왜 보류가 많은가", open=False):
                gr.Markdown(LIVE_MORE)
            # ── 2축 (제안서 §2.2) — 결함 256 ────────────────────
            #
            #   승우: *«직접 검증 칸에도 대시보드처럼 정방향/역방향,
            #   표준/감염병 긴급을 만들어야 하는 거 아냐?»*
            #
            #   **축2(출구)는 진짜 토글이다** — `run_pair(exit_=)` 로 가서
            #   판정 문턱과 `registry_required` 를 실제로 바꾼다.
            #
            #   **축1(입구)은 라디오로 안 만든다.** §2.2 가 축1 을
            #   *«후보를 어떻게 찾을지»* 로 정의했는데 이 탭은 사용자가
            #   쌍을 직접 준다 — 찾는 단계가 없다. 라디오를 놓으면
            #   **눌러도 아무 일도 안 하는 칸**이 되고, 그건 오늘 고친
            #   결함 250 과 같은 것이다. 그래서 **값을 고정해 보여 준다.**
            #   진짜 축1 은 「병명으로 시작」 탭이다.
            # ── 배치: **할 일이 먼저, 설명은 접어서** ────────────
            #   앞판은 잣대 표(긴 글)가 입력칸 **위**에 통째로 펼쳐져 있어
            #   쓰려면 그걸 다 지나쳐 스크롤해야 했다. 시연에서 첫 화면에
            #   보여야 하는 건 **«무엇을 넣고 무엇을 누르나»** 다.
            # ── **한 줄에 넣는다** — 입력 · 잣대 · 버튼 (진단서 ④)
            with gr.Row():
                box = gr.Textbox(label="검증할 가설", placeholder="약물 / 질환",
                                 value=demo.PRESETS[0][0], scale=6)
                live_exit = gr.Radio(["표준", "신종감염병긴급"], value="표준",
                                     label="심사 기준", scale=3,
                                     min_width=240)
                # 이 탭은 입력이 **둘**뿐이라(「병명으로 시작」은 셋)
                #   같은 `scale` 을 쓰면 심사 기준과 버튼 사이에 350px
                #   쯤 빈칸이 생긴다 (08-19 화면). 버튼 쪽 비중을 올려
                #   **빈칸을 버튼이 흡수**하게 한다.
                with gr.Column(scale=3, min_width=150):
                    btn = gr.Button("검증하기", variant="primary", size="lg")
            gr.Markdown(
                "<span class='br-sub'>약과 질환을 직접 넣으므로 후보를 "
                "찾는 단계는 건너뜁니다. 후보부터 찾으려면 옆의 "
                "「병명으로 시작」 탭을 쓰세요. 신종감염병긴급을 고르면 "
                "임상시험 등록부까지 확인해 5초쯤 더 걸립니다.</span>")
            # ── 예시를 **누를 수 있게** 한다 ──────────────────────
            #   `demo.PRESETS` 6개에는 «왜 이 예시인가» 설명이 붙어 있는데
            #   앞판은 `PRESETS[0][0]` 을 **기본값으로만** 썼다. 나머지
            #   다섯과 설명 여섯 줄이 **화면에 한 글자도 안 나왔다** —
            #   처음 온 사람이 «약물 / 질환» 형식을 스스로 알아내야 했다.
            gr.Markdown("<span class='br-sub'>눌러 보세요 — 여섯 개가 "
                        "각각 다르게 갈립니다. 「판정 사례」 탭에 지난 "
                        "결과가 있고, 여기서 누르면 지금 다시 돌립니다 — "
                        "문헌이 늘어 판정이 달라지기도 합니다.</span>")
            ex = gr.Radio([q for q, _ in demo.PRESETS], show_label=False,
                          container=False, value=None,
                          elem_classes=["br-pick"])
            ex_why = gr.Markdown("", elem_classes=["br-note"])
            with gr.Accordion("이 잣대가 무엇을 바꾸나 · 이 약의 접근성",
                              open=False):
                live_left = gr.Markdown(_live_left(demo.PRESETS[0][0], "표준"))
            # **빈 칸으로 두지 않는다** (결함 104). 높이 0 이면 gradio 가
            # 진행 표시를 그릴 자리가 없어 *"눌러도 아무 일이 없는"* 화면이 된다.
            live_out = gr.Markdown(LIVE_IDLE, elem_classes=["br-live"])
            # 3D 는 **State 를 거쳐** 채운다 — 보이는 출력이 하나여야
            # 진행 막대가 하나다(결함 260).
            live_s1 = gr.State(None)
            live_struct = gr.HTML()
            # 내려받기 — **판마다 위젯 이름이 다르다.** 없으면 `File` 로
            #   떨어진다(둘 다 «값이 파일 경로» 규약이라 배선이 같다).
            _DL = getattr(gr, "DownloadButton", gr.File)
            # **작게.** 부가 기능이 주 버튼(검증하기)만 한 덩치면
            #   눈이 «다음에 누를 것» 을 잘못 고른다 (08-19 승우).
            live_dl = _DL("근거 카드 내려받기 (.md)", visible=False,
                          size="sm", scale=0, min_width=180,
                          elem_classes=["br-dl"])
            # 잣대를 바꿔도, **약물을 바꿔도** 좌측이 따라간다 — 결함 248 자리.
            ex.change(_pick_example, inputs=ex, outputs=[box, ex_why],
                      show_progress="hidden")
            live_exit.change(_live_left, inputs=[box, live_exit],
                             outputs=live_left, show_progress="hidden")
            box.change(_live_left, inputs=[box, live_exit],
                       outputs=live_left, show_progress="hidden")
            # ── 순서: **지우고 → 돌리고 → 그린다** (결함 262) ──────
            #   앞판은 «돌리고 → 그린다» 뿐이라, 새 질의를 돌리는 동안
            #   **앞 후보의 뷰어가 화면에 그대로 남아 있었다.** 실행 중
            #   화면에 다른 후보의 구조가 있으면 그건 틀린 화면이다.
            #   지우는 이벤트는 `show_progress="hidden"` 이라 막대를 안 늘린다.
            for _ev in (btn.click, box.submit):
                _ev(lambda: "", inputs=None, outputs=live_struct,
                    show_progress="hidden"
                    ).then(run_live, inputs=[box, live_exit],
                           outputs=[live_out, live_s1], show_progress="minimal"
                    ).then(_live_struct, inputs=live_s1, outputs=live_struct,
                           show_progress="hidden"
                    ).then(_export, inputs=[live_out, box], outputs=live_dl,
                           show_progress="hidden")

        # ── 병명 입구 (제안서 §6 흐름도 왼쪽) — 명세 `78e44afa1b3b` ──────
        #
        #   기존 「직접 검증」은 **약물/질환 쌍**을 받는다. 그림의 입구는
        #   **병명 하나**다. 그 칸이 08-14까지 🟥 였다.
        #
        #   **탭을 나눈 이유** — 동결 수치가 전부 쌍 입구에서 나왔다.
        #   같은 칸에 섞으면 «어느 입구로 잰 수인가» 를 화면이 못 말한다.
        with gr.Tab("병명으로 시작 · 후보 찾기"):
            gr.Markdown(DISEASE_INTRO, elem_classes=["br-note"])
            # ── 축2 를 여기에도 (결함 258) ────────────────────────
            #
            #   `run_disease(exit_=)` 를 배선해 놓고 **부르는 곳을 안
            #   만들었다.** `s1`(109)·`served_by`(234)·`graphroute`(244)·
            #   `time_to_refute`(250)·`exit_profile`(256)에 이어 **여섯 번째**다.
            #   결함 256 을 고치면서 같은 형태를 또 만든 것이다.
            #
            #   그리고 여기가 **제안서 §2.2 의 그 주장이 서는 유일한 자리**다 —
            #   *«역발상과 신종 감염병 긴급 심사처럼 고정형 모델이 허용하지
            #   않던 조합이 가능»*. 축1 이 진짜인 탭은 여기뿐이고(발굴을
            #   실제로 돌린다), 축2 가 없으면 **조합이 성립할 곳이 없다.**
            # ── **한 줄에 넣는다** — 입력·두 축·버튼 (진단서 ④) ────
            #   앞판은 입력 한 줄 + 라디오 한 줄 + 긴 info 로 세 덩이였다.
            #   할 일이 셋으로 흩어지면 «무엇부터 하나» 를 사용자가 정해야 한다.
            # ── 체크박스가 입력 줄에 **끼어 있었다** ──────────────
            #   질환 이름 · 라디오 둘 · 버튼 사이에 체크박스를 끼우니
            #   **다섯 가지가 같은 무게로 나란히** 섰다. 그런데 셋은
            #   «무엇을 검색할까»(주 입력)이고 하나는 «결과에 뭘 더 볼까»
            #   (부가 선택)다. **성격이 다른 것을 같은 줄에 두면 낀다.**
            #   → 주 입력 한 줄, 부가 선택은 **아래 옵션 줄**로 내린다.
            with gr.Row():
                dz = gr.Textbox(label="질환 이름", placeholder="예: COVID-19",
                                value="COVID-19", scale=5)
                dz_entry = gr.Radio(["정방향", "역발상"], value="정방향",
                                    label="후보를 찾는 방법", scale=3)
                dz_exit = gr.Radio(["표준", "신종감염병긴급"], value="표준",
                                   label="심사 기준", scale=3)
                with gr.Column(scale=2, min_width=132):
                    dbtn = gr.Button("후보 찾기", variant="primary", size="lg")
            with gr.Row(elem_classes=["br-optrow"]):
                acc = gr.Checkbox(label="접근성 보기", value=False,
                                  min_width=150)
                gr.Markdown(
                    "<span class='br-sub'>역발상은 부작용 기록에서 거꾸로 "
                    "후보를 찾고, 신종감염병긴급은 임상시험 등록부까지 "
                    "확인합니다.</span>")
            dz_out = gr.Markdown(DISEASE_IDLE, elem_classes=["br-live"])
            # ── 후보를 누르면 **판단 과정과 근거 전건**이 열린다 ──────
            #   승우: *«각각의 약물을 클릭하면 그 과정이 왜 나왔는지»*
            #   대시보드에는 이 패턴이 있는데 **구운 사례에만** 있었다.
            #   심사 30점이 «사고 과정을 투명하게 보여주는가» 인데
            #   **실제로 돌린 쪽에 그게 없었다.**
            #
            #   결과는 **`gr.State`** 에 담는다 — 보이는 출력이 하나여야
            #   진행 막대가 하나다(결함 260).
            dz_state = gr.State(None)
            # **고르는 칸은 고를 대상 옆에 둔다.** 08-19 브라우저에서
            #   보니 페이지 맨 아래였다 — 목록에서 스무 줄 내려가 누르고
            #   상세를 보려고 또 내려가야 했다.
            # `container=False` — **Gradio 가 씌우는 `div.form` 이
            #   회색 판(#e5e7eb)이다.** CSS 로는 부모를 못 고르므로
            #   컨테이너 자체를 안 만든다. 라벨도 «보라 알약» 으로
            #   나와서 떼고 위에 평범한 작은 글씨로 적는다.
            gr.Markdown("<span class='br-sub'>후보를 고르면 "
                        "판단 과정이 열립니다</span>")
            dz_pick = gr.Radio([], show_label=False, container=False,
                               interactive=True, visible=False,
                               elem_classes=["br-pick"])
            dz_detail = gr.Markdown(elem_classes=["br-live"])
            dz_tail = gr.Markdown(elem_classes=["br-live"])
            for _e in (dbtn.click, dz.submit):
                _e(lambda: (gr.update(choices=[], value=None, visible=False),
                            "", ""), inputs=None,
                   outputs=[dz_pick, dz_detail, dz_tail],
                   show_progress="hidden"
                   ).then(run_disease_live,
                          inputs=[dz, acc, dz_exit, dz_entry],
                          outputs=[dz_out, dz_tail, dz_state],
                          show_progress="minimal"
                   ).then(_disease_picks, inputs=dz_state, outputs=dz_pick,
                          show_progress="hidden")
            dz_pick.change(_disease_detail, inputs=[dz_state, dz_pick],
                           outputs=dz_detail, show_progress="hidden")

        with gr.Tab("반증 기록 · 우리가 우리를 반증한 것"):
            gr.Markdown(_md_evidence())

    with gr.Accordion("이 데모가 하지 않는 것", open=False):
        gr.Markdown(NOT_DOING)

if __name__ == "__main__":
    kw = _ui_kw() if _THEME_ON_LAUNCH else {}
    ui.launch(server_name="0.0.0.0",
              server_port=int(os.environ.get("PORT", 7866)), **kw)
