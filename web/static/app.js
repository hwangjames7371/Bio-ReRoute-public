/* Bio-ReRoute — 화면 배선 (08-20 재설계). **의존성 없음.**
 *
 * ## 구조
 *
 *   모드 ─┬─ 서비스   약으로 시작 · 병으로 시작
 *         └─ 심사·시연 판정 사례 · 어떻게 판단하나 · 반증 기록
 *
 * 주소(`#/verify/drug`)에 상태를 담는다 — **새로고침해도 그 자리다.**
 * 리허설에서 «그 탭 다시 열어 주세요» 가 URL 하나가 된다.
 *
 * 판단도 조립도 여기 없다. 그건 `dash.py`·`webui.py` 가 한다.
 */
"use strict";

var $ = function (id) { return document.getElementById(id); };

/* ── 화면 목록 — **이름은 리허설 대본이 인용한다** ────────── */
var VIEWS = {
  drug: {
    mode: "verify", el: "v-drug", ico: "Rx", nav: "약으로 시작",
    hint: "약과 질환을 직접 넣습니다",
    title: "직접 검증 · 내 가설 넣기",
    sub: "약과 질환을 넣으면 그 가설을 «반박하는 근거»부터 찾습니다."
  },
  disease: {
    mode: "verify", el: "v-disease", ico: "Dx", nav: "병으로 시작",
    hint: "후보 약물부터 찾습니다",
    title: "병명으로 시작 · 후보 찾기",
    sub: "질환 이름만 넣으면 후보 약물을 찾아 하나씩 검증합니다."
  },
  cases: {
    mode: "judge", el: "v-cases", ico: "▣", nav: "판정 사례",
    hint: "지난 결과 6건",
    title: "판정 사례 · 지난 결과 6건",
    sub: "실제로 돌린 결과입니다. 판정이 서로 갈리도록 골랐습니다."
  },
  dashboard: {
    mode: "judge", el: "v-dash", ico: "◈", nav: "어떻게 판단하나",
    hint: "3분할 · 사고 과정",
    title: "대시보드 · 어떻게 판단하나",
    sub: "심사 기준을 바꾸면 좌·중·우가 함께 움직입니다."
  },
  evidence: {
    mode: "judge", el: "v-evidence", ico: "◎", nav: "반증 기록",
    hint: "우리가 우리를 반증한 것",
    title: "반증 기록 · 우리가 우리를 반증한 것",
    sub: "이 프로젝트가 파는 것은 성능이 아니라 틀렸을 때 알아채는 절차입니다."
  }
};
var MODES = [
  ["verify", "서비스"],
  ["judge", "심사·시연"]
];
var VIEW = "drug", MODE = "verify", BOOT = null;

/* ── 사이드바 ────────────────────────────────────────── */
function buildMode() {
  var host = $("mode"); host.innerHTML = "";
  MODES.forEach(function (m) {
    var b = document.createElement("button");
    b.textContent = m[1];
    b.setAttribute("role", "tab");
    b.onclick = function () {
      // 모드를 바꾸면 **그 모드의 첫 화면**으로 간다
      var first = Object.keys(VIEWS).filter(function (k) {
        return VIEWS[k].mode === m[0];
      })[0];
      go(first);
    };
    host.appendChild(b);
  });
}
function buildMenu() {
  var host = $("menu"); host.innerHTML = "";
  var g = document.createElement("div");
  g.className = "grp";
  g.textContent = (MODE === "verify") ? "검증하기" : "이 시스템";
  host.appendChild(g);
  Object.keys(VIEWS).forEach(function (k) {
    if (VIEWS[k].mode !== MODE) { return; }
    var v = VIEWS[k];
    var a = document.createElement("a");
    a.href = "#/" + v.mode + "/" + k;
    a.title = v.nav + " — " + v.hint;      // 접었을 때도 뭔지 알게
    a.innerHTML = "<span class='ico'>" + v.ico + "</span>"
      + "<span class='mtxt'>" + v.nav + "<small>" + v.hint + "</small></span>";
    if (k === VIEW) { a.setAttribute("aria-current", "page"); }
    host.appendChild(a);
  });
}
function paint() {
  Object.keys(VIEWS).forEach(function (k) {
    $(VIEWS[k].el).hidden = (k !== VIEW);
  });
  $("page-title").textContent = VIEWS[VIEW].title;
  $("page-sub").textContent = VIEWS[VIEW].sub;
  Array.prototype.forEach.call($("mode").children, function (b, i) {
    b.setAttribute("aria-selected", MODES[i][0] === MODE ? "true" : "false");
  });
  buildMenu();
  document.body.classList.remove("drawer");
  window.scrollTo(0, 0);
  syncTopbar();
  draw3d();
}

/* 머리줄 **높이를 CSS 에 알려준다** — 붙는 표 머리글이 그 아래에 선다.
 *
 * 값을 CSS 에 숫자로 박지 않는 이유: 부제가 좁은 화면에서 **두 줄로
 * 접히면** 머리줄이 76px → 96px 이 된다. 박아 두면 그때 표 머리글이
 * 머리줄 **뒤로 숨는다** — 화면 폭에 따라 조용히 틀리는 값이다. */
function syncTopbar() {
  var h = document.querySelector(".topbar").getBoundingClientRect().height;
  document.documentElement.style.setProperty("--topbar-h",
                                             Math.round(h) + "px");
}
window.addEventListener("resize", syncTopbar);
function go(view) {
  if (!VIEWS[view]) { view = "drug"; }
  location.hash = "#/" + VIEWS[view].mode + "/" + view;
}
/* ── ⛔ 09-23 · **첫 화면이 «안 되는 것» 이었다** ────────────────────
 *
 *   앞판의 기본값은 `drug`(직접 검증)였다. 그런데 **배포판은 정적본이라
 *   라이브 검증이 안 된다.** 그래서 처음 여는 사람이 보는 것이 —
 *
 *     ① 「직접 검증」 화면   ② 「서버가 필요합니다」 버튼
 *     ③ 「이 배포판에서는 라이브 검증이 안 됩니다」 박스
 *
 *   **첫 30초에 «안 됩니다» 를 세 번 읽는다.** 그리고 실제로 도는
 *   것(판정 사례 6건 · 3분할 사고 과정 · 반증 기록)은 **클릭 두 번 뒤**다.
 *
 *   ⚠ 그 안내 박스가 스스로 *«왼쪽 심사·시연은 전부 그대로 동작합니다»*
 *     라고 적고 있었다. **설계자도 그쪽을 봐야 한다는 걸 알고 있었다.**
 *     그러면 거기서 시작하는 것이 맞다.
 *
 *   서버판에서도 `cases` 로 둔다 — 구운 판정을 먼저 보고 직접 검증으로
 *   가는 흐름이 자연스럽고, **모드에 따라 기본을 가르면** 그 분기가
 *   또 하나의 «조용히 다른 화면» 을 만든다(결함 82 계열).
 *
 *   ⚠ **해시가 있으면 그대로 간다.** 대본·문서가 특정 화면을 링크로
 *     가리키는 경우는 안 바뀐다. */
function route() {
  var m = (location.hash || "").match(/^#\/(\w+)\/(\w+)$/);
  var view = (m && VIEWS[m[2]]) ? m[2] : "cases";
  VIEW = view; MODE = VIEWS[view].mode;
  paint();
  if (view === "dashboard" && !dashLoaded) { dashLoad(); dashBottom(); }
}

/* ── 서버 ──────────────────────────────────────────────
 *
 * ## 두 가지 모드 — **한 코드로** (08-21)
 *
 *   서버판   `/api/*` 를 그때그때 부른다. 라이브 검증이 된다
 *   정적판   `data/snapshot.json` 하나를 읽는다. **서버가 없다**
 *
 * 정적판이 필요한 이유는 셋이다 —
 *
 *   ① **무료로 배포할 길이 그것뿐이다.** 2026-07-08 부터 HF Spaces 의
 *      Gradio·Docker 가 둘 다 유료가 됐고 Static 만 무료로 남았다
 *   ② 심사위원이 보는 세 화면(판정 사례·대시보드·반증 기록)은
 *      **이미 LLM 0회**다 — 구운 파일을 조립해 보여 줄 뿐이다
 *   ③ **시연 중에 죽을 서버가 없다.** 08-21 에 탭 하나가 먹통이 돼
 *      요청이 서버에 닿지도 않았다. 정적판은 그때의 예비본이다
 *
 * 어느 모드인지는 **물어보지 않고 알아낸다** — `/api/boot` 이 실패하면
 * 정적판이다. 정적 호스팅에서는 그 주소가 404 를 준다.
 */
var STATIC = false, SNAP = null;

/* ⚠ **스냅샷 열쇠는 인자를 이름순으로 정렬한다.**
 *   `build_static.py:key()` 와 **글자 하나까지 같아야** 한다.
 *   URL 이 아니므로 퍼센트 인코딩을 **하지 않는다** —
 *   `URLSearchParams` 를 쓰면 `q=a / b` 가 `q=a+%2F+b` 가 돼서
 *   파이썬이 구운 열쇠와 어긋난다. 그러면 **오류 없이 빈 화면**이
 *   된다. 이 프로젝트에서 가장 오래 사는 고장의 모양이다. */
function snapKey(path, params) {
  if (!params) { return path; }
  return path + "?" + Object.keys(params).sort().map(function (k) {
    return k + "=" + params[k];
  }).join("&");
}
function api(path, params) {
  if (STATIC) {
    var k = snapKey(path, params);
    return Object.prototype.hasOwnProperty.call(SNAP, k)
      ? Promise.resolve(SNAP[k])
      : Promise.reject("정적판에 없는 자료입니다 — " + k);
  }
  var q = params ? ("?" + new URLSearchParams(params).toString()) : "";
  return fetch(path + q).then(function (r) { return r.json(); });
}
function post(path, body) {
  return fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then(function (r) { return r.json(); });
}
function setMd(id, h) { $(id).innerHTML = h || ""; draw3d(); }
function esc(s) {
  return String(s).replace(/[&<>]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
  });
}
function fail(id, e) {
  $(id).innerHTML = "<div class='err'><b>화면이 자료를 못 받았습니다</b><br>"
    + esc(e) + "</div>";
}

/* ── 라디오 칩 ────────────────────────────────────────
 * `:has()` 를 못 쓰는 브라우저가 있다 — `.on` 을 JS 가 붙인다. */
function seg(host, name, items, value, onchange) {
  host.innerHTML = "";
  items.forEach(function (it) {
    var val = (typeof it === "string") ? it : it.value;
    var lab = (typeof it === "string") ? it : it.label;
    var l = document.createElement("label");
    var r = document.createElement("input");
    r.type = "radio"; r.name = name; r.value = val;
    r.checked = (val === value);
    if (r.checked) { l.className = "on"; }
    r.onchange = function () {
      Array.prototype.forEach.call(host.children, function (x) {
        x.className = x.contains(r) ? "on" : "";
      });
      onchange(val);
    };
    l.appendChild(r);
    l.appendChild(document.createTextNode(lab));
    host.appendChild(l);
  });
}

/* ── 3D ────────────────────────────────────────────────
 *
 * ⚠ **옛 판의 로직을 그대로 옮긴다.** 08-20 에 내가 `fetch` +
 *   `addModel` 로 **새로 썼다가 안 그려졌다.** 검증된 코드는
 *   `$3Dmol.download('url:'+cif, ...)` 이고, 거기엔 결함 113·115 의
 *   대책이 박혀 있다 —
 *
 *   · **113** — CIF 파서가 `B_iso_or_equiv` 를 `atom.b` 로 안 옮긴다.
 *     그러면 비교가 전부 거짓이 되어 **마지막 구간(주황·무질서)** 으로
 *     떨어진다. 08-11 에 신뢰 91.1 짜리를 통째로 주황으로 칠했다 —
 *     **안 그려지는 것보다 나쁘다. 판정과 정반대를 말한다.**
 *   · **115** — 감시기가 자기 변경에 반응해 브라우저가 세 번 얼었다.
 *
 *   «돌아가는 코드를 다시 쓰지 마라» 를 내가 어겼다. */
function draw1(el) {
  if (el.dataset.done) { return; }
  if (!window.$3Dmol) {
    el.innerHTML = "<div class='v-warn'><b>3Dmol.js 를 못 불러왔습니다.</b>"
      + "<br>구조가 없다는 뜻이 아닙니다 — 그리는 라이브러리가 안 왔습니다."
      + "</div>";
    return;
  }
  el.dataset.done = "1";
  var v = window.$3Dmol.createViewer(el, { backgroundColor: "white" });
  window.$3Dmol.download("url:" + el.dataset.cif, v, {}, function (m) {
    var at = m.selectedAtoms({});
    var ok = at.some(function (a) {
      return typeof a.b === "number" && !isNaN(a.b);
    });
    if (!ok) {
      // **«색을 못 칠한다» 와 «무질서하다» 는 다르다** (결함 113)
      v.setStyle({}, { cartoon: { color: "#9aa4ad" } });
      v.zoomTo(); v.render();
      var n = document.createElement("div");
      n.className = "v-warn amber";
      n.innerHTML = "<b>pLDDT 색칠을 못 합니다</b> — 이 좌표 파일에 "
        + "신뢰도 값이 안 들어 있습니다. <b>무질서하다는 뜻이 아닙니다.</b>";
      el.parentNode.insertBefore(n, el.nextSibling);
      return;
    }
    v.setStyle({}, { cartoon: { colorfunc: function (a) {
      return a.b > 90 ? "#0053D6" : a.b > 70 ? "#65CBF3"
           : a.b > 50 ? "#FFDB13" : "#FF7D45";
    } } });
    v.zoomTo(); v.render();
  });
}
function draw3d() {
  var t = document.querySelectorAll("div.br-3d[data-cif]:not([data-done])");
  for (var i = 0; i < t.length; i++) { draw1(t[i]); }
}
window.addEventListener("load", draw3d);
setTimeout(draw3d, 800);

/* ── 실행 (SSE) — 제안서 §6 «실시간 진행 표시» ───────────── */
function run(kind, params, o) {
  var bar = $(o.bar), out = $(o.out), btn = $(o.btn);
  bar.classList.remove("idle");
  bar.firstElementChild.style.width = "4%";
  btn.disabled = true;
  o.before && o.before();
  var n = 0;
  var es = new EventSource("/api/run?" + new URLSearchParams(
    Object.assign({ kind: kind }, params)).toString());
  function stop() {
    es.close(); btn.disabled = false;
    bar.classList.add("idle"); bar.firstElementChild.style.width = "0";
  }
  es.onmessage = function (ev) {
    var m = JSON.parse(ev.data);
    if (m.t === "step") {
      n += 1;
      // **분모를 모른다** — 후보 수가 실행 중에 정해진다.
      bar.firstElementChild.style.width = Math.min(95, n * 100 / 24) + "%";
      out.innerHTML = m.html;
      return;
    }
    if (m.t === "error") {
      out.innerHTML = "<div class='err'><b>판정이 아니라 실행이 실패한 "
        + "것입니다</b><br>" + esc(m.message)
        + (m.detail ? "<pre>" + esc(m.detail) + "</pre>" : "") + "</div>";
      stop(); return;
    }
    if (m.t === "done") { o.done(m); stop(); }
  };
  es.onerror = function () {
    if (es.readyState === 2) {
      out.innerHTML = "<div class='err'><b>연결이 끊겼습니다</b><br>"
        + "서버가 살아 있는지 확인하십시오 — 판정이 아닙니다.</div>";
      stop();
    }
  };
}

/* ── 정적판에서 «라이브는 안 된다» 를 화면이 말한다 ─────────
 *
 * **못 하는 것을 못 한다고 적는다.** 이 프로젝트의 규칙이고, 여기가
 * 그 규칙이 가장 쉽게 깨지는 자리다 — 버튼을 회색으로만 만들어 두면
 * 누른 사람은 «고장» 으로 읽는다. `보류` 를 `기각` 으로 읽는 것과
 * 같은 종류의 오독이다.
 *
 * 그래서 셋을 한다 — 버튼을 잠그고 · **왜인지** 적고 · **어떻게 하면
 * 되는지**까지 적는다. 그리고 심사·시연 모드는 **전부 그대로 돈다**는
 * 것을 같이 말한다. 안 되는 것만 크게 적으면 되는 것도 안 되는 줄 안다.
 */
function markStatic() {
  document.body.classList.add("static-mode");
  var msg = "<div class='nolive'><b>이 배포판에서는 라이브 검증이 "
    + "안 됩니다</b><span>논문을 실제로 받아 읽고 모델을 부르는 일이라 "
    + "서버가 있어야 합니다. 이 판은 <b>서버 없이 도는 정적본</b>입니다 — "
    + "그래서 API 키도, 요금도, 죽을 서버도 없습니다.</span>"
    + "<span>왼쪽 <b>심사·시연</b> 은 <b>전부 그대로 동작합니다</b> — "
    + "판정 사례 6건 · 3분할 대시보드 · 반증 기록. 그 셋은 원래 "
    + "<b>LLM 호출 0회</b>로 도는 화면입니다.</span>"
    // ⚠ 명령을 **실제로 도는 것**으로 적는다. `py 웹.ps1` 이라 적었다가
    //   고쳤다 — 그건 PowerShell 스크립트를 파이썬으로 돌리라는 말이다.
    //   그리고 이 화면은 **공개 배포판**이라 보는 사람이 윈도우라는
    //   보장이 없다. 윈도우 편의 스크립트는 `.\웹.ps1` 이다.
    + "<span class='how'>직접 돌려 보려면 저장소를 받아 "
    + "<code>python web/server.py</code> 로 띄우고 <code>.env</code> 에 "
    + "키를 넣으면 됩니다. 윈도우는 <code>.\\웹.ps1</code>.</span></div>";
  ["live-starter", "dz-out"].forEach(function (id) {
    var el = $(id); if (el) { el.innerHTML = msg; el.hidden = false; }
  });
  ["live-go", "dz-go", "live-q", "dz-q"].forEach(function (id) {
    var el = $(id); if (el) { el.disabled = true; }
  });
  $("live-go").textContent = "서버가 필요합니다";
  $("dz-go").textContent = "서버가 필요합니다";
}

/* ── 약으로 시작 ─────────────────────────────────────── */
var liveExit = "표준", liveMd = "";
/* ── 「이 약의 접근성」 팝오버 (08-24 승우) ─────────────────────────
 *
 *   결과 오른쪽 칸의 `<details>` 를 **심사 기준 줄 오른쪽 끝**으로 옮겼다.
 *   누르면 앞으로 뜬다 — 줄 높이가 안 변하므로 **결과 화면이 안 밀린다.**
 *
 *   ⚠ 팝오버를 만들 때 늘 빠뜨리는 셋을 다 건다 —
 *     · **바깥을 누르면 닫힌다** (안 닫히면 화면에 붙어 다닌다)
 *     · **ESC 로 닫힌다** (키보드만 쓰는 사람이 갇힌다)
 *     · **화면을 옮기면 닫힌다** (다른 서비스로 갔는데 떠 있으면 유령이다)
 */
/* **뷰포트 기준으로 자리를 잡는다** (`position:fixed`).
 *   ⚠ 남은 높이를 재서 `max-height` 를 준다 — 안 주면 팝오버가 화면
 *     아래로 나가고, 그걸 보려고 페이지를 스크롤하게 된다.
 *   돌려주는 값: **버튼이 아직 화면 안에 있나.** 밖이면 부르는 쪽이 닫는다.
 */
function accPlace() {
  var b = $("live-accbtn"), p = $("live-accpop");
  if (!b || !p || p.hidden) return true;
  var r = b.getBoundingClientRect();
  if (r.bottom < 0 || r.top > window.innerHeight) return false;
  var gap = 8, pad = 16;
  var below = window.innerHeight - r.bottom - gap - pad;
  var above = r.top - gap - pad;
  var up = below < 220 && above > below;      // 아래가 좁으면 위로 편다
  p.style.maxHeight = Math.max(160, Math.min(460, up ? above : below)) + "px";
  p.style.top = up ? "auto" : (r.bottom + gap) + "px";
  p.style.bottom = up ? (window.innerHeight - r.top + gap) + "px" : "auto";
  // 오른쪽 끝을 버튼에 맞추되 **화면 밖으로 안 나가게** 왼쪽을 지킨다
  var w = p.offsetWidth || 420;
  var left = Math.max(pad, Math.min(r.right - w, window.innerWidth - w - pad));
  p.style.left = left + "px";
  p.style.right = "auto";
  return true;
}
function accOpen(on) {
  var b = $("live-accbtn"), p = $("live-accpop");
  if (!b || !p) return;
  p.hidden = !on;
  b.setAttribute("aria-expanded", on ? "true" : "false");
  if (on) { p.scrollTop = 0; accPlace(); }
}
function accShow(on) {
  var w = $("live-accwrap");
  if (!w) return;
  w.hidden = !on;
  if (!on) accOpen(false);          // 숨길 땐 열린 채로 두지 않는다
}
(function () {
  var b = $("live-accbtn"), p = $("live-accpop"), x = $("live-accx");
  if (!b || !p) return;
  b.onclick = function (e) {
    e.stopPropagation();
    accOpen(p.hidden);
  };
  if (x) x.onclick = function () { accOpen(false); b.focus(); };
  document.addEventListener("click", function (e) {
    if (p.hidden) return;
    if (!p.contains(e.target) && e.target !== b) accOpen(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !p.hidden) { accOpen(false); b.focus(); }
  });
  window.addEventListener("hashchange", function () { accOpen(false); });
  // ⚠ **닫지 말고 따라오게 한다** — 08-24 승우: «스크롤하려고 하면
  //   창이 바로 내려가 버린다». 앞판은 `scroll` 을 **캡처(`true`)** 로
  //   잡아서 **팝오버 안에서 굴린 스크롤까지** 닫기로 셌다. 읽으려고
  //   굴리는 순간 닫히니 **내용을 볼 수가 없었다.**
  //
  //   이제 —
  //     · 팝오버 **안** 스크롤 → 아무 일도 안 한다
  //     · 페이지 스크롤 → **자리를 다시 잡는다**(버튼을 따라간다)
  //     · 버튼이 화면 밖으로 나가면 → 그때 닫는다
  //   `rAF` 로 한 프레임에 한 번만 계산한다.
  var tick = false;
  function follow(e) {
    if (p.hidden) return;
    if (e && e.target && e.target !== document && p.contains(e.target)) return;
    if (tick) return;
    tick = true;
    requestAnimationFrame(function () {
      tick = false;
      if (!p.hidden && !accPlace()) accOpen(false);
    });
  }
  window.addEventListener("scroll", follow, true);
  window.addEventListener("resize", follow);
})();

function liveLeft() {
  api("/api/live/left", { q: $("live-q").value, exit: liveExit })
    .then(function (d) {
      setMd("live-left", d.html);
      // ⚠ **결과를 기다리지 않는다** (08-24 승우: «아예 사라짐»).
      //   앞판에서 이건 `.result-side` 안에 있어 **결과가 나와야** 보였다.
      //   그래서 팝오버로 옮기면서 나도 «결과 있을 때만» 으로 걸었는데,
      //   **이 칸의 내용은 결과가 아니라 «지금 심사 기준의 문턱»** 이다
      //   (유망 80 · 조건부 … 후보를 찾는 방법). **묻기 전에 봐야 하는 것**이다.
      accShow(!!(d.html || "").trim());
    });
}
function liveRun() {
  liveMd = "";
  $("live-result").hidden = false;
  $("live-starter").hidden = true;
  run("live", { q: $("live-q").value, exit: liveExit }, {
    bar: "live-bar", out: "live-out", btn: "live-go",
    before: function () {
      $("live-struct").innerHTML = ""; $("live-dl").hidden = true;
      // **새 약을 물으면 그 약 기준으로 다시 받는다** — 비우지는 않는다.
      //   앞판처럼 지워 버리면 도는 동안 손잡이가 사라졌다 나타난다.
      liveLeft();
    },
    done: function (m) {
      setMd("live-out", m.main);
      $("live-struct").innerHTML = m.struct || "";
      // **구조 얘기는 구조 자리에서** — 본문 한가운데 큰 인용 상자였다
      var wb = $("live-structwhy");
      wb.hidden = !m.structwhy;
      wb.innerHTML = m.structwhy
        ? "<span class='t'>3D 구조를 안 그린 이유</span>"
          + m.structwhy.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>") : "";
      if (m.left) { setMd("live-left", m.left); accShow(true); }
      $("live-dl").hidden = !m.download;
      liveMd = $("live-out").innerText;
      draw3d();
    }
  });
}

/* ── 병으로 시작 ─────────────────────────────────────── */
var dzEntry = "정방향", dzExit = "표준", dzResult = null;
function dzRun() {
  run("disease", {
    q: $("dz-q").value, exit: dzExit, entry: dzEntry,
    acc: $("dz-acc").checked ? "1" : "0"
  }, {
    bar: "dz-bar", out: "dz-out", btn: "dz-go",
    before: function () {
      // **앞 상세를 먼저 지운다** (결함 262 자리)
      $("dz-pickbox").hidden = true; $("dz-pick").innerHTML = "";
      setMd("dz-detail", ""); setMd("dz-tail", "");
    },
    done: function (m) {
      setMd("dz-out", m.main); setMd("dz-tail", m.tail);
      dzResult = m.result;
      var picks = m.picks || [];
      $("dz-pickbox").hidden = !picks.length;
      seg($("dz-pick"), "dzpick", picks.map(function (q) {
        // 질환은 열 개가 다 같다 — **다르지 않은 것은 구별에 쓸모가 없다**
        return { value: q, label: q.indexOf(" / ") > 0 ? q.split(" / ")[0] : q };
      }), null, dzDetail);
    }
  });
}
function dzDetail(name) {
  post("/api/disease/detail", { result: dzResult, name: name })
    .then(function (d) { setMd("dz-detail", d.html); });
}

/* ── 어떻게 판단하나 (대시보드) ──────────────────────── */
var dashRun = null, dashExit = "표준", dashLoaded = false;
function dashLoad() {
  dashLoaded = true;
  api("/api/dash/run", { run: dashRun, exit: dashExit }).then(function (d) {
    setMd("dash-left", d.left); setMd("dash-center", d.center);
    seg($("dash-cand"), "dashcand", d.picks, d.first, dashCard);
    dashCard(d.first);
  }).catch(function (e) { fail("dash-center", e); });
}
/* 중앙 탭 — **한 번에 하나만.** 3,800자를 동시에 펴지 않는다 */
var CTABS = [["dash-think", "사고 과정"], ["dash-card", "근거 카드"]];
function buildCtabs() {
  var host = $("dash-tabs");
  if (host.children.length) { return; }
  CTABS.forEach(function (t, i) {
    var b = document.createElement("button");
    b.textContent = t[1];
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", i === 0 ? "true" : "false");
    b.onclick = function () {
      CTABS.forEach(function (u, j) {
        $(u[0]).hidden = (j !== i);
        host.children[j].setAttribute("aria-selected", j === i ? "true" : "false");
      });
    };
    host.appendChild(b);
  });
}
function dashCard(q) {
  if (!q) { return; }
  api("/api/dash/card", { q: q, exit: dashExit }).then(function (d) {
    setMd("dash-think", d.think); setMd("dash-card", d.card);
    $("dash-struct").innerHTML = d.struct || "";
    setMd("dash-patent", d.patent); setMd("dash-side", d.side);
    setMd("dash-left", d.left); buildCtabs(); draw3d();
  }).catch(function (e) { fail("dash-card", e); });
}
function dashBottom() {
  api("/api/dash/bottom").then(function (d) {
    setMd("dash-cal", d.cal); setMd("dash-tl", d.tl);
  });
}

/* ── 내려받기 ────────────────────────────────────────── */
function download() {
  post("/api/export", { md: liveMd, query: $("live-q").value })
    .then(function (d) {
      if (!d.ok) { alert(d["이유"] || "내보낼 것이 없습니다"); return; }
      var a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([d.text], { type: "text/markdown" }));
      a.download = d.name; a.click();
      URL.revokeObjectURL(a.href);
    });
}

/* ── 시작 ────────────────────────────────────────────── */
function boot(b) {
  BOOT = b;
  $("disc-full").innerHTML = b.head.disclaimer_full;
  // 심사 기준 «?» — **낱말만 주고 뜻을 안 주면 화면이 절반만 말한 것**
  var HELP = {
    exit: ["/api/exit/help", "심사 기준이 무엇을 바꾸나"],
    entry: ["/api/entry/help", "정방향과 역발상은 무엇이 다른가"]
  };
  document.querySelectorAll("button.q[data-help]").forEach(function (btn) {
    btn.onclick = function () {
      var h = HELP[btn.dataset.help] || HELP.exit;
      api(h[0]).then(function (d) {
        $("help-title").textContent = h[1];
        $("help-body").innerHTML = d.html;
        $("help-dlg").showModal();
      });
    };
  });
  $("help-close").onclick = function () { $("help-dlg").close(); };
  // 면책 전문 — **두 자리**(머리줄·사이드바)에서 연다.
  //   머리줄 쪽은 사이드바를 접어도 살아 있어야 한다(08-24 결함).
  document.querySelectorAll(".disc-open").forEach(function (b) {
    b.onclick = function () { $("disc-dlg").showModal(); };
  });
  $("disc-close").onclick = function () { $("disc-dlg").close(); };

  /* 약으로 시작 */
  $("live-q").value = b.live.presets.length ? b.live.presets[0].q : "";
  seg($("live-exit"), "liveexit", b.live.exits, liveExit,
      function (v) { liveExit = v; liveLeft(); });
  var host = $("live-ex"); host.innerHTML = "";
  b.live.presets.forEach(function (p) {
    var c = document.createElement("button");
    c.className = "card";
    c.innerHTML = "<b>" + esc(p.q) + "</b><span>" + esc(p.why) + "</span>";
    c.onclick = function () { $("live-q").value = p.q; liveLeft(); liveRun(); };
    host.appendChild(c);
  });
  $("live-go").onclick = liveRun;
  $("live-q").addEventListener("keydown", function (e) {
    if (e.key === "Enter") { liveRun(); }
  });
  $("live-dl").onclick = download;
  liveLeft();

  /* 병으로 시작 */
  setMd("dz-out", b.disease.idle);
  seg($("dz-entry"), "dzentry", b.disease.entries.filter(function (x) {
    return x !== "사용자 지정";        // 이 화면은 후보를 **찾는** 자리다
  }), dzEntry, function (v) { dzEntry = v; });
  seg($("dz-exit"), "dzexit", b.disease.exits, dzExit,
      function (v) { dzExit = v; });
  $("dz-go").onclick = dzRun;
  $("dz-q").addEventListener("keydown", function (e) {
    if (e.key === "Enter") { dzRun(); }
  });

  /* 판정 사례 —
   * ⚠ **머리글을 다시 찍지 않는다** (08-21). `_CASES_INTRO` 는
   *   «실제로 돌린 결과를 그대로 저장해 뒀습니다. 판정이 서로 갈리도록
   *   골랐습니다» 인데, 이 화면의 `sub` 가 **같은 말**이다. 둘이 58px
   *   간격으로 나란히 서 있었다. 앞판(Gradio)에는 머리줄이 없어서
   *   그 상수가 필요했고, **여기서는 머리줄이 그 일을 한다.**
   *   상수를 지우지 않는 이유 — `app.py` 가 아직 쓴다. */
  setMd("cases-more", b.cases.more);
  seg($("cases-pick"), "casepick", b.cases.labels, b.cases.labels[0],
      function (v) {
        api("/api/case", { label: v })
          .then(function (d) { setMd("cases-out", d.html); });
      });
  setMd("cases-out", b.cases.first);

  /* 어떻게 판단하나 — 안내문 없이 ① 칸이 스스로 말한다 */
  dashRun = b.dash.runs[0];
  seg($("dash-run"), "dashrun", b.dash.runs, dashRun,
      function (v) { dashRun = v; dashLoad(); });
  seg($("dash-exit"), "dashexit", b.dash.exits, dashExit,
      function (v) { dashExit = v; dashLoad(); });

  /* 반증 기록 */
  setMd("ev-body", b.evidence.body);

  route();
}

buildMode();
$("drawer-btn").onclick = function () {
  document.body.classList.toggle("drawer");
};
/* 접기 — **기억한다.** 시연 중에 매번 다시 접게 하면 안 된다 */
(function () {
  var KEY = "br-side-collapsed";
  function apply(on) {
    document.body.classList.toggle("collapsed", on);
    // ⚠ **`textContent` 를 쓰지 마라** (08-24). 이 버튼은 이제 `BR` 로고와
    //   화살표 두 겹을 자식으로 들고 있다 — 텍스트로 갈아치우면 **둘 다
    //   날아가고 로고가 사라진다.** 화살표는 CSS `content` 가 넣는다.
    var b = $("collapse");
    b.setAttribute("aria-expanded", on ? "false" : "true");
    b.setAttribute("aria-label", on ? "메뉴 펴기" : "메뉴 접기");
  }
  try { apply(localStorage.getItem(KEY) === "1"); } catch (e) { apply(false); }
  $("collapse").onclick = function () {
    var on = !document.body.classList.contains("collapsed");
    apply(on);
    try { localStorage.setItem(KEY, on ? "1" : "0"); } catch (e) { /* 무시 */ }
  };
}());
$("scrim").onclick = function () { document.body.classList.remove("drawer"); };
window.addEventListener("hashchange", route);

/* ── 시작: 서버판인가 정적판인가 ───────────────────────────
 *
 * **묻지 않고 알아낸다.** `/api/boot` 이 살아 있으면 서버판, 아니면
 * `data/snapshot.json` 을 읽어 정적판으로 간다.
 *
 * ⚠ 정적판으로 떨어진 것을 **조용히 넘어가지 않는다.** 라이브 검증이
 *   안 되는데 화면이 아무 말도 안 하면, 누른 사람은 «고장» 으로 읽는다.
 *   `markStatic()` 이 서비스 두 화면에 이유를 적는다.
 */
function startStatic(why) {
  return fetch("static/data/snapshot.json")
    .then(function (r) {
      if (!r.ok) { throw new Error("snapshot.json " + r.status); }
      return r.json();
    })
    .then(function (s) {
      STATIC = true; SNAP = s;
      return api("/api/boot").then(function (b) { boot(b); markStatic(); });
    })
    .catch(function (e2) {
      document.querySelector(".page").innerHTML =
        "<div class='err'><b>화면 자료를 못 받았습니다</b><br>"
        + "서버도 정적 스냅샷도 읽지 못했습니다 — <b>판정이 아닙니다.</b>"
        + "<br><small>" + esc(why) + " · " + esc(e2) + "</small></div>";
    });
}
/* `?static=1` — **정적판을 일부러 켠다.** 두 가지 쓸모가 있다:
 *   ① 배포 전에 정적본이 진짜로 도는지 **여기서** 확인한다
 *      («검증 환경이 실행 환경과 다르면 그 검증은 거짓말이다»)
 *   ② 시연 중 **라이브만** 죽으면(LLM·망·키) 붙여서 그대로 이어 간다
 *
 * ⛔ **08-24 정정 — 「서버가 죽으면」이 아니다** (결함 311).
 *    이 주소를 여는 것 자체가 **그 서버에 요청하는 일**이고,
 *    `server.py` 는 모든 응답에 `Cache-Control: no-store` 를 붙인다.
 *    **서버가 죽으면 이 화면은 아예 안 뜬다.** 그때의 대역은
 *    `py -m http.server 8123 -d 배포정적` 을 **미리 띄워 둔 탭**이다. */
if (/[?&]static=1/.test(location.search)) {
  startStatic("?static=1 — 일부러 켠 정적판");
} else {
  fetch("/api/boot")
    .then(function (r) {
      if (!r.ok) { throw new Error("boot " + r.status); }
      return r.json();
    })
    .then(boot)
    .catch(function (e) { startStatic(e); });
}
