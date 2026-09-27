# -*- coding: utf-8 -*-
"""Bio-ReRoute 웹 서버 — **표준 라이브러리만.**

    py web\\server.py            # http://127.0.0.1:7866

## 왜 Gradio 를 걷어냈나 (08-20 · 승우)

> *«Gradio로 하니깐 디자인의 한계도 있어서 바로 고치자»*

**근거가 수치로 있다.** 08-19 하루에 승우가 화면을 보고 짚은 결함 중
**다섯이 프레임워크 때문**이었다 —

| | 무엇 | 왜 Gradio 탓인가 |
|---|---|---|
| 280② | 회색 판(`div.form`)이 안 지워짐 | 위젯 **바깥**에 감싸는데 CSS 로는 부모를 못 고른다 |
| 280③ | 칩이 오른쪽으로 잘림 | `flex-wrap:nowrap` 이 기본 |
| 277 | 체크박스가 입력칸 덩치 | 모든 위젯에 같은 `padding`·`min-height` |
| 283 | 입력줄 오른쪽 350px 빈칸 | `scale` 이 열 수에 따라 달라진다 |
| 274① | 버튼이 행 높이(95px) | `equal_height=True` |

**다섯 다 «CSS 를 우리가 못 쥔다» 는 한 원인**이다.

## 왜 FastAPI 가 아니라 표준 라이브러리인가

`requirements.txt` 가 스스로 적어 놨다 — *«본체는 표준 라이브러리만 쓴다
— 재현하는 사람이 설치에 막히면 안 된다»*. FastAPI+uvicorn 을 넣으면
**의존성이 둘 늘고 그만큼 신선한 설치가 깨질 자리가 는다**(결함 72·86 이
정확히 그렇게 났다).

`http.server.ThreadingHTTPServer` 로 충분하다 — 요청마다 스레드가 서고,
`wfile.write` + `flush` 로 **SSE 가 그대로 된다.**

## 층이 셋으로 갈렸다

    bioreroute/dash.py    조각을 만든다   (gradio 0줄 · 1627줄)
    bioreroute/webui.py   페이지로 조립   (gradio 0줄 ·  470줄)
    web/server.py         HTTP 로 낸다   ← 이 파일

**앞의 둘은 이 교체에서 한 줄도 안 바뀌었다.**

## ⚠ `app.py` 는 안 지운다

`재현절차.md §0` — 삭제 금지. 되돌릴 수 있어야 하고, 8/22 리허설 전에
새 화면이 흔들리면 **옛 화면으로 돌아갈 길**이 있어야 한다.
"""
import html
import io
import json
import os
import queue
import re
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bioreroute import dash, demo, evidence, webui   # noqa: E402
from bioreroute.core import profiles                 # noqa: E402

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PORT = int(os.environ.get("BIOREROUTE_PORT", "7866"))

# ── 마크다운 → HTML ──────────────────────────────────────────
#
#   `dash.py` 는 마크다운 문자열을 낸다. Gradio 가 그걸 렌더했었다.
#   이제 우리가 한다 — `Markdown==3.10.3` 은 **이미 의존성에 있다**
#   (`보고서_pdf만들기.py` 가 쓴다). 새로 추가한 것이 아니다.
#
#   ⚠ `md_in_html` 이 반드시 있어야 한다. 우리 문자열은 `<details>`
#     안에 표를 넣는다 — 그 확장이 없으면 **표가 통째로 안 그려진다.**
# ⚠ **`<details>` 안의 마크다운은 그냥 두면 안 바뀐다** (08-20 화면)
#
#   승우: *«3D 구조를 안 돌린 부터 다 깨지고, 특허 부분부터도 다 깨짐»*
#
#   원인 하나였다. Python-Markdown 의 `md_in_html` 은 **`markdown="1"`
#   속성이 붙은 HTML 블록만** 안쪽을 파싱한다. `dash.py` 는
#   `<details><summary>…</summary>` 안에 표와 `####` 를 넣는데,
#   속성이 없으니 **날 텍스트로 그대로 나왔다** —
#   `| 약물 | hydroxychloroquine |` 이 화면에 파이프째 보였다.
#
#   Gradio 는 자체 렌더러라 알아서 해 줬다. **프레임워크가 해 주던
#   일을 우리가 넘겨받은 것이고, 넘겨받은 목록에 이게 빠져 있었다.**
#
#   ⚠ **`dash.py` 를 안 고친다.** 거기는 프레임워크를 모르는 층이고,
#     «마크다운을 HTML 로 바꾸는 규칙» 은 **이 층의 일**이다.
_DETAILS = re.compile(r"<details(?![^>]*markdown=)")

# ── 「찾는 방법」 도움말 (08-20 승우) ─────────────────────────
#
#   *«찾는 방법에도 ? 넣어서 추가설명 있으면 좋을 것 같고»*
#
#   화면이 «정방향 / 역발상» 두 낱말만 준다. **역발상은 이 시스템의
#   간판 주장(제안서 §2.2)인데 이름만으로는 아무 뜻도 전달이 안 된다.**
def _entry_help():
    return "\n".join([
        "| 방법 | 어디서 출발하나 | 무엇을 쓰나 |",
        "|---|---|---|",
        "| **정방향** | 질환에서 출발 | 논문·지식그래프에서 그 병과 "
        "이어진 약을 찾습니다 |",
        "| **역발상** | **부작용 기록에서 거꾸로** | 어떤 약을 먹은 "
        "사람에게 그 병이 **덜 생겼다**면, 그 약이 병을 막고 있을 수 "
        "있습니다(FAERS·SIDER) |",
        "",
        "> 역발상은 «치료 효과» 를 안 보고 **«안 걸렸다» 를 봅니다.** "
        "그래서 논문이 아직 없는 조합도 나옵니다 — 대신 교란이 커서 "
        "**뒤에 오는 검증 단계가 더 중요해집니다.**",
    ])

# ── 접힘 제목을 **둘로 가른다** (08-20 승우: «접는 부분 글자가 디자인에
#    알맞지 않다») ────────────────────────────────────────────
#
#   `dash.py` 가 만드는 제목은 이렇다 —
#
#       <summary><b>특허 자유도 (FTO)</b> — 판정에 안 들어갑니다. 펼쳐 보기</summary>
#
#   **제목과 부연과 조작 안내가 한 줄에 뭉쳐 있다.** 셋은 무게가 다르다.
#   그리고 «펼쳐 보기» 는 ▸ 아이콘이 이미 말하므로 **글자로 또 말하면
#   같은 말을 두 번 하는 것**이다.
#
#   ⚠ **`dash.py` 를 안 고친다.** Gradio 판도 그 문자열을 쓰고, 거기서는
#     한 줄로 나오는 게 맞다. **서식 결정은 렌더 층의 일**이다.
_SUM = re.compile(r"<summary>(.*?)</summary>", re.S)
_OPENHINT = re.compile(r"\s*[·.]?\s*펼쳐\s*보기\s*$")


def _summary(m):
    body = _OPENHINT.sub("", m.group(1)).strip()
    # 첫 «—» 에서 가른다. 태그 안에 있는 «—» 는 없다(제목은 <b>…</b>).
    i = body.find(" — ")
    if i < 0:
        return "<summary><span class='s-t'>%s</span></summary>" % body
    return ("<summary><span class='s-t'>%s</span>"
            "<span class='s-m'>%s</span></summary>"
            % (body[:i].strip(), body[i + 3:].strip()))


def _mdready(text: str) -> str:
    t = _DETAILS.sub('<details markdown="1"', str(text or ""))
    # `dash.py` 가 홑따옴표로 쓴 `markdown='1'` 도 Python-Markdown 이
    #   읽게 겹따옴표로 맞춘다 — 확장이 속성값을 문자열로 비교한다.
    t = t.replace("markdown='1'", 'markdown="1"')
    return _SUM.sub(_summary, t)


try:
    import markdown as _md

    _MD = _md.Markdown(extensions=["tables", "md_in_html", "sane_lists"])

    def md(text: str) -> str:
        _MD.reset()
        return _EMPTY_THEAD.sub("", _MD.convert(_mdready(text)))
except Exception:                                    # pragma: no cover
    def md(text: str) -> str:
        """**없으면 없다고 적는다.** 조용히 날 문자열을 내지 않는다."""
        return ("<pre class='br-nomd'>⚠ markdown 패키지가 없습니다 — "
                "`pip install Markdown==3.10.3`\n\n%s</pre>"
                % html.escape(str(text or "")))


# ── **머리 없는 표의 빈 띠를 지운다** (08-20 승우) ────────────
#
#   *«표의 윗부분을 보면 빈칸으로 조금 나와 있는 것»*
#
#   `dash.py` 는 «이름 | 값» 두 열짜리 표를 이렇게 낸다 —
#
#       | | |
#       |---|---|
#       | 판정 | 유망 |
#
#   **머리가 일부러 비어 있다** (이름·값 표라 머리가 뜻이 없다). 그런데
#   Python-Markdown 은 `<thead><tr><th></th><th></th></tr></thead>` 를
#   만들고, 우리 CSS 가 머리줄에 배경을 깔아 **빈 회색 띠**가 생겼다.
#
#   ⚠ **마크다운 문법을 바꾸지 않는다.** `dash.py` 의 `| | |` 는
#     Gradio 판에서도 쓰고, 표 문법상 머리줄은 있어야 한다.
#     **비었으면 그리지 않는 것**이 렌더 층의 일이다.
_EMPTY_THEAD = re.compile(
    r"<thead>\s*<tr>(?:\s*<th[^>]*>\s*</th>)+\s*</tr>\s*</thead>", re.S)


def _j(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


# ── 실행 (스트리밍) ──────────────────────────────────────────
#
#   제안서 §6 — *«각 후보가 깔때기를 통과·탈락하는 단계를 실시간 진행
#   표시로»*. Gradio 는 제너레이터를 그냥 받아 줬다. 여기서는 **SSE**
#   (`text/event-stream`)로 같은 일을 한다.
#
#   ⚠ 게이트 함수는 **콜백**으로 단계를 흘린다(`progress=`). 그 콜백은
#     작업 스레드에서 불리므로 **큐로 넘겨서** HTTP 스레드가 쓴다.
#     스레드 두 개가 같은 소켓에 쓰면 응답이 섞인다.
def _run_stream(kind, params, emit):
    """한 번 돌리고 단계를 `emit(dict)` 로 흘린다. 마지막에 결과."""
    q = queue.Queue()
    box = {}

    def on(name, note=""):
        q.put({"t": "step", "name": name, "note": note})

    def work():
        try:
            if kind == "live":
                box["r"] = demo.run_pair(
                    params.get("q", ""), config=demo.DEMO_CONFIG, progress=on,
                    exit_=params.get("exit", "표준"))
            else:
                box["r"] = demo.run_disease(
                    params.get("q", ""), progress=on,
                    exit_=params.get("exit", "표준"),
                    entry=params.get("entry", "정방향"))
        except Exception as e:                        # noqa: BLE001
            box["e"] = "%s: %s" % (type(e).__name__, e)
            box["tb"] = traceback.format_exc()[-800:]
        finally:
            q.put(None)

    th = threading.Thread(target=work, daemon=True)
    th.start()
    steps = []
    while True:
        try:
            item = q.get(timeout=200)      # 상한 150초 + 여유
        except Exception:
            emit({"t": "error",
                  "message": "200초 동안 아무 단계도 오지 않았습니다. "
                             "네트워크나 모델이 막힌 것이지 판정이 "
                             "아닙니다."})
            return
        if item is None:
            break
        steps.append((item["name"], item["note"]))
        item["html"] = md(webui._md_steps(steps))
        emit(item)
    th.join(timeout=5)
    if box.get("e"):
        emit({"t": "error", "message": box["e"], "detail": box.get("tb", "")})
        return
    # ── **화면이 조용해지는 구간을 막는다** (08-20 실측) ──────────
    #
    #   SSE 를 처음 재 보니 마지막 단계(2.15초) 뒤 **15.5초 정적**이었다.
    #   원인은 `_md_result` 첫 호출이 **특허 색인을 읽기 때문**이다
    #   (1회차 5.68초 · 2회차 0.17초 — 결함 252 에서 35초→0.06초로
    #   줄인 그 색인이고, 첫 로딩은 여전히 든다).
    #
    #   **판정은 이미 끝났다.** 그런데 화면은 그걸 모른다 — 한 줄을
    #   더 흘려서 «무엇을 기다리는지» 를 말한다. 진행률 막대만 도는
    #   것과 «지금 무엇을 하는가» 를 적는 것은 다르다(제안서 §6).
    steps.append(("결과 정리", "근거 카드와 특허 색인을 읽는 중"))
    emit({"t": "step", "name": "결과 정리",
          "note": "근거 카드와 특허 색인을 읽는 중",
          "html": md(webui._md_steps(steps))})
    emit({"t": "done", **_render(kind, box.get("r") or {}, params)})


def _render(kind, r, params):
    """결과 dict → 화면 조각들. **조립은 `webui` 가 한다.**"""
    if kind == "live":
        s1 = r.get("s1")
        # **구조 얘기는 구조 자리에서.** 본문 한가운데 큰 인용 상자로
        #   있던 «3D 를 왜 안 그렸나» 를 오른쪽 칸으로 옮긴다(08-20).
        return {
            "main": md(webui._md_result(r, struct_note=False)),
            "struct": webui._live_struct(s1) if s1 else "",
            "structwhy": ("" if s1 else
                          (dash.route_note(r) if r.get("게이트") else "")),
            "left": md(webui._live_left(params.get("q", ""),
                                        params.get("exit", "표준"))),
            "download": bool(r.get("근거")),
        }
    head, tail = dash.disease_run_parts(
        r, acc_on=params.get("acc") in ("1", "true", True))
    return {
        "main": md(head), "tail": md(tail),
        "picks": dash.candidate_names(r),
        "result": r,
    }


# ── 페이지 조각 (정적) ───────────────────────────────────────
def _boot():
    """첫 화면에 필요한 것을 **한 번에** 내려보낸다.

    앞판(Gradio)은 위젯마다 왕복이 있었다. 여기서는 **한 요청**이다 —
    탭 다섯 개의 정적 본문과 목록이 같이 온다.
    """
    labels = webui._case_labels()
    runs = list(dash.RUNS.keys())
    return {
        "head": {
            "title": "Bio-ReRoute",
            "lead": "기존 약을 새 질환에 써도 될까 — 그 가설을 "
                    "«반박하는 근거»부터 찾아 드립니다. 판정마다 "
                    "논문 번호(PMID)·인용 원문·가중치가 함께 남습니다.",
            "disclaimer": md(_DISCLAIMER_ONE),
            "disclaimer_full": md(demo.AI_NOTICE + "\n\n" + demo.DISCLAIMER),
        },
        "dash": {"intro": md(_DASH_INTRO), "more": md(_DASH_MORE),
                 "runs": runs, "exits": list(profiles.EXITS.keys())},
        "cases": {"intro": md(_CASES_INTRO), "more": md(_CASES_MORE),
                  "labels": labels,
                  "first": md(webui.show_case(labels[0])) if labels else ""},
        "live": {"intro": md(_LIVE_INTRO), "more": md(_LIVE_MORE),
                 "idle": md(_LIVE_IDLE),
                 "presets": [{"q": q, "why": w} for q, w in demo.PRESETS],
                 "exits": list(profiles.EXITS.keys())},
        "disease": {"intro": md(_DISEASE_INTRO), "idle": md(_DISEASE_IDLE),
                    "entries": list(profiles.ENTRY.keys()),
                    "exits": list(profiles.EXITS.keys())},
        # 제목·머리글은 **머리줄이 이미 말한다** — 두 번 안 적는다
        "evidence": {"body": md(webui._md_evidence(head=False))},
    }


# 안내문은 **`app.py` 에서 그대로 가져온다** — 두 벌을 두지 않는다.
def _load_texts():
    """`app.py` 의 안내문 상수를 **실행해서** 읽는다.

    파싱하지 않는다 — 문자열 이어붙이기(`(... "a" "b")`)를 정규식으로
    풀면 반드시 틀린다. `ast.literal_eval` 이 그 일을 정확히 한다.
    """
    import ast
    src = io.open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    want = {"DISCLAIMER_ONE", "DASH_INTRO", "DASH_MORE", "CASES_INTRO",
            "CASES_MORE", "LIVE_INTRO", "LIVE_MORE", "LIVE_IDLE",
            "DISEASE_INTRO", "DISEASE_IDLE"}
    got = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in want:
                try:
                    got[t.id] = ast.literal_eval(node.value)
                except Exception:                     # noqa: BLE001
                    pass
    missing = sorted(want - set(got))
    if missing:
        # **없으면 없다고 적는다.** 빈 문자열을 조용히 내지 않는다.
        for k in missing:
            got[k] = "⚠ 안내문 `%s` 를 `app.py` 에서 못 읽었습니다." % k
    return got


_T = _load_texts()
_DISCLAIMER_ONE = _T["DISCLAIMER_ONE"]
_DASH_INTRO = _T["DASH_INTRO"]
_DASH_MORE = _T["DASH_MORE"]
_CASES_INTRO = _T["CASES_INTRO"]
_CASES_MORE = _T["CASES_MORE"]
_LIVE_INTRO = _T["LIVE_INTRO"]
_LIVE_MORE = _T["LIVE_MORE"]
_LIVE_IDLE = _T["LIVE_IDLE"]
_DISEASE_INTRO = _T["DISEASE_INTRO"]
_DISEASE_IDLE = _T["DISEASE_IDLE"]


# ── GET 이 돌려주는 JSON — **한 곳에서만 정한다** ─────────────────
#
#   08-21. 이 표가 `do_GET` 안에 있었다. 그런데 **정적 배포**(서버 없이
#   도는 판)를 구우려면 같은 목록이 빌더에도 있어야 한다. 두 곳에 적으면
#   갈라진다 — **결함 82 가 배포 목록에서 정확히 그랬다**(문서와 코드가
#   각자 목록을 들고 있었다).
#
#   그래서 함수 하나로 뺀다. `do_GET` 도 `build_static.py` 도 **이것만**
#   본다. 새 경로를 여기 적으면 정적판이 자동으로 따라온다.
#
#   ⚠ `/api/run` 은 여기 없다 — SSE 라 JSON 이 아니고, **정적판에서는
#     애초에 못 돈다.** 그건 화면이 정직하게 적는다.
def get_json(p, qs):
    """GET 경로 → 응답 dict. **`None` 이면 우리 경로가 아니다.**"""
    if p == "/api/boot":
        return _boot()
    if p == "/api/case":
        return {"html": md(webui.show_case(qs.get("label", "")))}
    if p == "/api/dash/run":
        left, center, pick = webui._dash_run(
            qs.get("run", ""), qs.get("exit", "표준"))
        return {"left": md(left), "center": md(center),
                "picks": pick["choices"], "first": pick["value"]}
    if p == "/api/dash/card":
        (think, card, struct, patent, side,
         left) = webui._dash_card(qs.get("q", ""), qs.get("exit", "표준"))
        return {"think": md(think), "card": md(card), "struct": struct,
                "patent": md(patent), "side": md(side), "left": md(left)}
    if p == "/api/dash/bottom":
        return {"cal": md(dash.bottom_calibration()),
                "tl": md(dash.bottom_timeline(None))}
    if p == "/api/entry/help":
        return {"html": md(_entry_help())}
    if p == "/api/exit/help":
        return {"html": md(_exit_help())}
    if p == "/api/live/left":
        return {"html": md(webui._live_left(qs.get("q", ""),
                                            qs.get("exit", "표준")))}
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "BioReRoute"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        """기본 로그는 요청마다 한 줄을 찍는다 — 시연 중엔 시끄럽다."""
        if os.environ.get("BIOREROUTE_HTTP_LOG"):
            super().log_message(fmt, *args)

    # ── 내보내기 ────────────────────────────────────────────
    def _send(self, code, body, ctype="application/json; charset=utf-8",
              extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _static(self, rel):
        # ⚠ **경로 탈출을 막는다.** `..` 로 상위 파일을 읽히면 안 된다.
        p = os.path.normpath(os.path.join(STATIC, rel.lstrip("/")))
        if not p.startswith(STATIC) or not os.path.isfile(p):
            return self._send(404, _j({"error": "없음"}))
        ct = {".html": "text/html", ".css": "text/css",
              ".js": "text/javascript", ".svg": "image/svg+xml"}.get(
                  os.path.splitext(p)[1], "application/octet-stream")
        with open(p, "rb") as f:
            self._send(200, f.read(), ct + "; charset=utf-8")

    # ── SSE ─────────────────────────────────────────────────
    def _sse(self, kind, params):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        # ⚠ `Content-Length` 를 안 준다 → HTTP/1.1 은 chunked 를 쓴다.
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        alive = [True]

        def emit(obj):
            if not alive[0]:
                return
            try:
                data = b"data: " + _j(obj) + b"\n\n"
                self.wfile.write(b"%X\r\n" % len(data) + data + b"\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                # 브라우저가 탭을 닫은 것이다 — **오류가 아니다.**
                alive[0] = False

        try:
            _run_stream(kind, params, emit)
        except Exception as e:                        # noqa: BLE001
            emit({"t": "error", "message": "%s: %s" % (type(e).__name__, e),
                  "detail": traceback.format_exc()[-800:]})
        if alive[0]:
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except Exception:                         # noqa: BLE001
                pass

    def do_GET(self):                                 # noqa: N802
        u = urlparse(self.path)
        p, qs = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if p in ("/", "/index.html"):
                return self._static("index.html")
            if p.startswith("/static/"):
                return self._static(p[len("/static/"):])
            if p == "/api/run":                       # SSE — JSON 이 아니다
                return self._sse(qs.get("kind", "live"), qs)
            data = get_json(p, qs)
            if data is not None:
                return self._send(200, _j(data))
            return self._send(404, _j({"error": "없는 주소: %s" % p}))
        except Exception as e:                        # noqa: BLE001
            self._send(500, _j({"error": "%s: %s" % (type(e).__name__, e),
                                "detail": traceback.format_exc()[-1200:]}))

    def do_POST(self):                                # noqa: N802
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:                             # noqa: BLE001
            return self._send(400, _j({"error": "JSON 이 아닙니다"}))
        try:
            if u.path == "/api/disease/detail":
                return self._send(200, _j({"html": md(
                    webui._disease_detail(body.get("result"),
                                          body.get("name")))}))
            if u.path == "/api/export":
                return self._send(200, _j(_export(body)))
            return self._send(404, _j({"error": "없는 주소: %s" % u.path}))
        except Exception as e:                        # noqa: BLE001
            self._send(500, _j({"error": "%s: %s" % (type(e).__name__, e),
                                "detail": traceback.format_exc()[-1200:]}))


def _exit_help():
    """심사 기준이 **실제로 무엇을 바꾸는가** — 코드에서 읽는다.

    08-20 승우: *«심사기준에 대해서도 옆에 ? 같은걸 누르면 기준을
    보여주는 것도 좋지 않을까»*

    좋은 지적이다. 화면이 «표준 / 신종감염병긴급» 두 낱말만 주고
    **그게 무엇을 바꾸는지는 말하지 않았다.** 문턱이 40 에서 25 로
    내려가는 것은 판정을 뒤집는 변화인데.

    ⚠ **문서에 옮겨 적지 않는다.** `profiles.EXITS` 를 그대로 읽는다 —
    한쪽만 고치면 화면이 거짓말을 한다(`CLAUDE.md §4`).
    """
    L = ["| 무엇을 | %s |" % " | ".join(profiles.EXITS.keys()),
         "|---|%s" % ("--:|" * len(profiles.EXITS))]
    rows = [("유망으로 올리는 문턱", "유망", "%s%%"),
            ("기각으로 내리는 문턱", "기각", "%s%%"),
            ("조건부로 가르는 균형", "balance", "%.2f")]
    for ko, key, fmt in rows:
        vals = []
        for name in profiles.EXITS:
            v = profiles.exit_profile(name).get(key)
            try:
                vals.append(fmt % v)
            except (TypeError, ValueError):
                vals.append("—")
        L.append("| %s | %s |" % (ko, " | ".join(vals)))
    reg = []
    for name in profiles.EXITS:
        p = profiles.exit_profile(name)
        reg.append("필수" if p.get("등록부") or p.get("registry_required")
                   else "선택")
    L.append("| 임상시험 등록부 조회 | %s |" % " | ".join(reg))
    L += ["", "> 신종감염병긴급은 **기각 문턱만** 내립니다 — 유망 문턱은 "
          "그대로입니다. 급하다고 «될 것 같다» 를 쉽게 말하지 않고, "
          "«아니다» 를 조금 늦게 말할 뿐입니다."]
    return "\n".join(L)


def _export(body):
    """근거 카드를 **파일 내용으로** 돌려준다 (제안서 §8.2).

    Gradio 는 임시 파일을 만들어 경로를 넘겼다. 여기서는 **내용을
    그대로 내려보내고 브라우저가 저장**한다 — 서버에 파일이 안 쌓인다.
    """
    import datetime as _dt
    q = body.get("query") or "—"
    text = body.get("md") or ""
    if not text:
        return {"ok": False, "이유": "결과가 없습니다"}
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    head = ("# Bio-ReRoute 근거 카드\n\n"
            "| | |\n|---|---|\n"
            "| 질의 | %s |\n| 조회 시각 | **%s** |\n"
            "| 모델 | %s |\n\n"
            "> **이 문서는 판정 근거이지 의학적 조언이 아니다.**\n"
            "> 문헌은 계속 늘고 판정은 그에 따라 움직인다 — "
            "**다시 조회하면 다를 수 있다.**\n\n---\n\n"
            % (q, now, os.environ.get("BIOREROUTE_MODEL", "—")))
    safe = re.sub(r"[^0-9A-Za-z가-힣]+", "_", q)[:40] or "결과"
    return {"ok": True, "name": "bioreroute_%s.md" % safe,
            "text": head + text}


def _warm():
    """색인을 **미리 읽어 둔다.**

    첫 결과가 15초 늦게 그려지는 이유가 이것이었다(08-20 실측).
    시연 중에 그 15초를 쓰면 안 된다.

    ⚠ **판정을 데우는 게 아니다.** 특허 색인은 화면이 스스로
    «판정에 안 들어간다» 고 적는 층이다. LLM 도 안 부른다 —
    부르면 그건 예산을 쓰는 것이고 «미리 돌려 뒀다» 가 된다.
    """
    import time as _t
    try:
        t0 = _t.time()
        dash.right_patent("aspirin")
        print("  특허 색인 준비 %.1f초" % (_t.time() - t0))
    except Exception as e:      # noqa: BLE001
        # **못 데워도 서버는 뜬다.** 그때는 첫 결과가 느릴 뿐이다.
        print("  특허 색인 준비 못 함: %s" % e)


def main(argv=None):
    """⚠ **시연 당일에 터지는 두 자리를 여기서 막는다** (결함 312).

    ① **포트가 이미 잡혀 있으면** `ThreadingHTTPServer` 가 그냥 `OSError`
       로 죽는다 — 화면에 파이썬 트레이스백이 뜬다. 흔한 상황이다:
       앞 실행이 안 죽었거나 두 번 띄웠을 때. **그리고 그 경우 대개는
       «우리 서버가 이미 떠 있는 것»** 이라 브라우저만 열면 된다.
    ② **포트 인자가 숫자가 아니면 조용히 7866 으로 떴다.** 사람은 7900
       을 기대하고 주소창을 친다 — **조용한 실패**(결함 99 계열).
    """
    port = PORT
    if argv and len(argv) > 1:
        try:
            port = int(argv[1])
        except ValueError:
            print("포트가 숫자가 아니다: %r" % (argv[1],))
            print("  예)  .\\웹.ps1 7900     (기본값은 %d)" % PORT)
            print("  **기본 포트로 몰래 뜨지 않는다** — 주소를 모른 채 "
                  "브라우저를 열게 되기 때문이다")
            return 2
    try:
        # ⚠ **08-31 · 바인드가 실패하기를 기다리면 안 된다** (결함 314)
        #
        #   `ThreadingHTTPServer` 는 `allow_reuse_address = 1` 이 기본이고,
        #   **`SO_REUSEADDR` 의 뜻이 OS 마다 다르다.**
        #
        #     Linux    활성 리스닝 소켓이 있으면 그래도 `EADDRINUSE` → 아래
        #              `except` 로 떨어진다. **시험이 통과한다**
        #     Windows  활성 소켓에도 **바인드가 성공한다.** 예외가 안 난다
        #              → `serve_forever()` 로 들어가 **영영 안 끝난다**
        #
        #   그래서 08-24 에 넣은 결함 312·313 방어가 **정작 승우 컴퓨터
        #   에서만 작동하지 않았다.** 08-31 에 `test_phase2` 가 [147] 에서
        #   **30분 넘게 멈춘 것**이 그 증상이다. 서버가 조용히 **둘** 뜨고
        #   요청이 어디로 갈지 모르게 되는 쪽이 트레이스백보다 나쁘다.
        #
        #   `CLAUDE.md §5` — «검증 환경이 실행 환경과 다르면 그 검증은
        #   거짓말이다». RDKit·경로에 이어 **소켓 의미**가 세 번째다.
        #
        #   고침은 OS 에 안 기댄다 — **바인드하기 전에 직접 물어본다.**
        import socket as _sk
        with _sk.socket() as _probe:
            _probe.settimeout(0.3)
            if _probe.connect_ex(("127.0.0.1", port)) == 0:
                raise OSError("이미 그 포트를 듣고 있는 서버가 있다")
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        print("=" * 60)
        print("포트 %d 를 못 잡았다 — %s" % (port, e))
        print("")
        print("  ① **우리 서버가 이미 떠 있을 가능성이 가장 크다.**")
        print("     브라우저에서 먼저 열어 봐라 →  http://127.0.0.1:%d"
              % port)
        print("  ② 그게 아니면 다른 포트로 띄운다 →  .\\웹.ps1 %d"
              % (port + 34))
        print("=" * 60)
        return 1
    print("=" * 60)
    print("Bio-ReRoute  http://127.0.0.1:%d" % port)
    print("  Gradio 없음 · 표준 라이브러리만 · Ctrl+C 로 종료")
    threading.Thread(target=_warm, daemon=True).start()
    print("=" * 60)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
