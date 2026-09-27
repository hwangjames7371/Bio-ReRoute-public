# -*- coding: utf-8 -*-
"""app.py ↔ **실제로 설치된 gradio** 대조

**이 파일은 결함에서 나오지 않았다.** `배포.md` 가 적어 둔 ❌ 하나를
줄이려고 만들었고, **돌려 보니 불일치가 0이었다.** 결함 번호를 붙이지
않는다 — 없는 결함을 만들면 그 기록 전체의 값이 떨어진다.

> 다만 **이 가드가 진짜 잡는지는 확인했다.** 일부러 틀린 `app.py`
> 둘(없는 인자 · 없는 이름)을 주면 `rc=1` 이고 정상은 `rc=0` 이다.
> **통과만 하는 가드는 가드가 아니다** — 시험 [60]이 그 셋을 다 태운다.

    py -m bioreroute.bench.gradiocheck
    py -m bioreroute.bench.gradiocheck --venv .venv/Lib/site-packages

## 왜 이 파일이 생겼나

`배포.md` 가 그동안 줄곧 이렇게 적어 뒀다 —

> **화면이 실제로 어떻게 보이는가** — ❌ **못 봤다**
> gradio 를 설치할 수 없는 환경이라 **가짜 gradio 로 배선만 확인**했다
> (시험 [55] · 콜백 4개 실제 호출)

그리고 이 프로젝트가 여러 번 배운 문장이 바로 —

> **검증 환경이 실행 환경과 다르면 그 검증은 거짓말이다.**

가짜 gradio 는 **우리가 쓴 것**이다. 그래서 `gr.Radio(scale=...)` 처럼
**실제 gradio 에 없는 인자를 줘도 조용히 통과한다.** 배선은 맞는데
`py app.py` 가 `TypeError` 로 죽는 상태를 가짜는 절대 못 잡는다.

## 그런데 실행은 여전히 못 한다 — 무엇이 달라졌나

승우 기기의 **`.venv/Lib/site-packages/gradio/`** 가 저장소에 있다.
윈도우 venv 라 리눅스에서 `import` 는 안 되지만 **소스는 텍스트다.**

    실행         ❌ 여전히 못 한다 (컴파일 확장이 윈도우용)
    API 대조     ✅ **AST 로 할 수 있다**

그래서 이 검사가 답하는 질문은 좁다 —

> **가짜 gradio 가 거짓말했는가?**
> `app.py` 가 부르는 이름과 넘기는 인자가 **실제 gradio 에 있는가?**

## 이 검사가 **못 보는 것** — 먼저 적는다

- **화면이 어떻게 보이는지 모른다.** 레이아웃·색·줄바꿈은 여전히 미확인
- **런타임 오류를 못 잡는다.** 타입이 맞아도 값이 틀리면 죽는다
- **이벤트 배선의 의미를 못 본다.** `outputs` 개수가 콜백 반환수와
  맞는지는 시험 [55]가 본다 (그건 가짜로도 되는 층이다)
- `**kwargs` 를 받는 함수는 **어떤 인자든 통과**시킨다 — 그런 함수에
  대해서는 이 검사가 아무 말도 안 한다. 그렇다고 적는다

**즉 `py app.py` 를 대체하지 않는다.** 실행 전 죽을 이유 하나를 줄일 뿐이다.
"""

import argparse
import ast
import os
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_VENV = os.path.join(".venv", "Lib", "site-packages")


def used_api(path: str) -> Tuple[Set[str], Dict[str, Set[str]]]:
    """`app.py` 가 쓰는 `gr.*` 이름과 호출 키워드."""
    t = ast.parse(open(path, encoding="utf-8").read())
    names: Set[str] = set()
    kw: Dict[str, Set[str]] = {}
    for n in ast.walk(t):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) \
                and n.value.id == "gr":
            names.add(n.attr)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "gr":
            kw.setdefault(n.func.attr, set()).update(
                k.arg for k in n.keywords if k.arg)
    return names, kw


def _iter_py(root: str):
    for dirpath, _dn, files in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def index_gradio(pkg: str) -> Dict[str, Any]:
    """gradio 소스에서 **클래스·함수 정의와 `__init__` 인자**를 뽑는다.

    `import` 를 안 한다 — 윈도우 venv 이고 컴파일 확장이 있다.
    **AST 로 읽는다.** 이 프로젝트가 결함 20에서 배운 것과 같은 도구다.
    """
    out: Dict[str, Any] = {"defs": {}, "err": []}
    for p in _iter_py(pkg):
        try:
            t = ast.parse(open(p, encoding="utf-8", errors="replace").read())
        except Exception as e:
            out["err"].append((os.path.relpath(p, pkg), str(e)[:60]))
            continue
        for n in t.body:
            if isinstance(n, (ast.ClassDef, ast.FunctionDef)):
                # 같은 이름이 여러 곳에 있으면 **인자가 많은 쪽**을 남긴다.
                # 재수출(`from .x import Y`)로 정의가 흩어져 있기 때문이다.
                info = _sig(n)
                old = out["defs"].get(n.name)
                if old is None or len(info["args"]) > len(old["args"]):
                    info["파일"] = os.path.relpath(p, pkg)
                    out["defs"][n.name] = info
    return out


def _sig(node) -> Dict[str, Any]:
    """클래스면 `__init__` 의, 함수면 자신의 인자 이름 집합."""
    fn = node
    if isinstance(node, ast.ClassDef):
        fn = next((b for b in node.body
                   if isinstance(b, ast.FunctionDef) and b.name == "__init__"), None)
        if fn is None:
            # `__init__` 이 상속돼 있으면 **모른다.** 통과시킨다.
            return {"args": set(), "kwargs": True, "종류": "class(상속)"}
    a = fn.args
    args = {x.arg for x in list(a.args) + list(a.posonlyargs) + list(a.kwonlyargs)}
    args.discard("self")
    return {"args": args, "kwargs": a.kwarg is not None,
            "종류": "class" if isinstance(node, ast.ClassDef) else "func"}


def installed_version(sp: str, name: str) -> Optional[str]:
    """`site-packages` 의 `*.dist-info` 에서 버전을 읽는다.

    **버전을 모르면 이 대조가 절반만 맞다.** 승우가 실제로 띄울 gradio 와
    여기서 읽은 소스가 다른 판이면 *"실제와 대조했다"* 는 말이 거짓이 된다.
    `렌즈답변.md` 에 *"버전 미확인"* 을 미해결로 적어 뒀고, 그걸 지운다.

    `__init__.py` 의 `__version__` 을 정규식으로 읽으려다 실패했다 —
    gradio 는 `version.txt` 를 읽어 넣는 방식이라 소스에 문자열이 없다.
    **`dist-info` 디렉터리 이름이 더 확실하다.**
    """
    import glob as _g
    for d in _g.glob(os.path.join(sp, name + "-*.dist-info")):
        m = re.match(r"^%s-(.+)\.dist-info$" % re.escape(name),
                     os.path.basename(d))
        if m:
            return m.group(1)
    return None


def class_method_args(pkg: str, rel: str, cls: str, fn: str):
    """`gradio/<rel>` 안의 `cls.fn` 인자 집합. 없으면 `(None, None)`."""
    p = os.path.join(pkg, rel)
    if not os.path.exists(p):
        return None, None
    try:
        t = ast.parse(open(p, encoding="utf-8", errors="replace").read())
    except Exception:
        return None, None
    for n in ast.walk(t):
        if isinstance(n, ast.ClassDef) and n.name == cls:
            for b in n.body:
                if isinstance(b, ast.FunctionDef) and b.name == fn:
                    a = b.args
                    s = {x.arg for x in list(a.args) + list(a.kwonlyargs)}
                    s.discard("self")
                    return s, a.kwarg is not None
    return None, None


def check_runtime_surface(pkg: str, app_src: str) -> List[Tuple[str, str]]:
    """생성자 밖의 **띄울 때 죽는 자리** 셋 (08-07 추가).

    첫 판은 `gr.X(...)` **생성자 인자**만 봤다. 그런데 `py app.py` 가
    실제로 죽는 자리는 거기만이 아니다 —

        ui.launch(server_name=…, server_port=…, theme=…)
        btn.click(fn, inputs=…, outputs=…)
        gr.themes.Soft()

    **gradio 4 → 6 은 메이저가 둘 올랐다.** `requirements.txt` 는
    `gradio>=4.44` 라 적혀 있고 승우 기기엔 **6.22.0** 이 깔려 있다.
    `app.py` 가 `_GR_MAJOR >= 6` 으로 `theme` 을 `Blocks` 에서
    `launch` 로 옮기는 분기를 갖고 있는데, **그 분기가 맞는지 아무도
    확인한 적이 없었다.** 08-07 아침에 손으로 확인했고, 손으로 한 확인은
    다음에 안 하므로 여기로 옮긴다.

    돌려주는 것은 **문제 목록**이다. 비어 있으면 이 층은 깨끗하다.
    """
    out: List[Tuple[str, str]] = []

    # ① Blocks.launch — app.py 가 넘기는 키워드
    launch_kw = set(re.findall(r"launch\([^)]*?(\w+)\s*=", app_src, re.S))
    launch_kw |= {"theme"} if "\"theme\": _THEME" in app_src else set()
    args, has_kwargs = class_method_args(pkg, "blocks.py", "Blocks", "launch")
    if args is None:
        out.append(("Blocks.launch", "시그니처를 못 찾았다 — **확인 못 했다**"))
    elif not has_kwargs:
        for k in sorted(launch_kw):
            if k not in args:
                out.append(("Blocks.launch(%s=…)" % k,
                            "이 판에 그 인자가 없다 — **띄우면 TypeError**"))

    # ② 이벤트 트리거 — `.click` · `.change` · `.submit`
    ev = os.path.join(pkg, "events.py")
    ev_src = open(ev, encoding="utf-8", errors="replace").read() if os.path.exists(ev) else ""
    for need in ("fn", "inputs", "outputs"):
        if not re.search(r"\b%s\s*[:=]" % need, ev_src):
            out.append(("이벤트 트리거", "`%s` 를 못 찾았다 — 배선이 안 붙을 수 있다" % need))

    # ③ 테마 — `gr.themes.Soft`
    ti = os.path.join(pkg, "themes", "__init__.py")
    if "themes.Soft" in app_src or "themes.Soft()" in app_src:
        ok = os.path.exists(ti) and "Soft" in open(
            ti, encoding="utf-8", errors="replace").read()
        if not ok:
            out.append(("gr.themes.Soft", "이 판에 없다"))
    return out


def audit(root: str = ROOT, venv: Optional[str] = None) -> Dict[str, Any]:
    sp = os.path.join(root, venv or DEFAULT_VENV)
    pkg = os.path.join(sp, "gradio")
    r: Dict[str, Any] = {"pkg": pkg, "있다": os.path.isdir(pkg),
                         "없는이름": [], "없는인자": [], "확인": 0,
                         "모름": [], "parse_err": 0,
                         "버전": installed_version(sp, "gradio"),
                         "rdkit": installed_version(sp, "rdkit")}
    if not r["있다"]:
        return r
    app = os.path.join(root, "app.py")
    if not os.path.exists(app):
        r["있다"] = False
        return r
    names, kw = used_api(app)
    g = index_gradio(pkg)
    r["parse_err"] = len(g["err"])
    r["정의수"] = len(g["defs"])

    # 모듈 속성(`gr.themes` · `gr.__version__`)은 클래스·함수가 아니다.
    MODULE_ATTR = {"themes", "__version__", "utils", "processing_utils"}
    for n in sorted(names):
        if n in MODULE_ATTR:
            # 디렉터리·파일로 존재하는지만 본다
            ok = (os.path.isdir(os.path.join(pkg, n))
                  or os.path.exists(os.path.join(pkg, n + ".py"))
                  or n.startswith("__"))
            if not ok:
                r["없는이름"].append((n, "모듈 속성인데 파일이 없다"))
            r["확인"] += 1
            continue
        if n not in g["defs"]:
            r["없는이름"].append((n, "gradio 소스에 정의가 없다"))
            continue
        r["확인"] += 1
        d = g["defs"][n]
        if d["kwargs"]:
            # **kwargs 를 받으면 무엇이든 통과한다 — 확인 못 했다고 적는다
            if kw.get(n):
                r["모름"].append((n, "**kwargs 를 받는다 — 인자 검사 불가"))
            continue
        for k in sorted(kw.get(n, ())):
            if k not in d["args"]:
                r["없는인자"].append((n, k, d["파일"]))

    # 생성자 밖 — launch · 이벤트 · 테마 (08-07)
    r["런타임"] = check_runtime_surface(pkg, open(app, encoding="utf-8").read())
    return r


def report(r: Dict[str, Any]) -> int:
    print("=" * 70)
    print("app.py ↔ 실제 gradio 대조 — **가짜 gradio 가 거짓말했는가**")
    print("=" * 70)
    if not r["있다"]:
        print("\n  gradio 소스를 못 찾았다: %s" % r["pkg"])
        print("  **이 검사는 확인한 것이 없다.** 통과가 아니다.")
        print("  `--venv` 로 경로를 주거나, 이 환경에 gradio 가 없는 것이다.")
        return 0
    print("\n  소스   %s" % r["pkg"])
    if r.get("버전"):
        print("  버전   gradio **%s** — 이 판과 대조했다" % r["버전"])
    else:
        print("  버전   **모른다** (dist-info 없음) — 승우가 띄울 판과")
        print("         같다는 보장이 없다. **이 대조는 절반만 맞다**")
    if r.get("rdkit"):
        print("  덤     rdkit **%s** 도 설치돼 있다 — S2·hERG·DILI 가"
              % r["rdkit"])
        print("         **SKIP 되지 않는다**(배포.md 의 위험 하나 해소)")
    print("  정의   %d개 (AST · import 안 함)" % r.get("정의수", 0))
    if r["parse_err"]:
        print("  ⚠ 파싱 실패 %d파일 — 그만큼 **덜 본 것이다**" % r["parse_err"])

    print("\n[1] `app.py` 가 부르는 이름이 실재하나")
    print("─" * 70)
    if r["없는이름"]:
        for n, why in r["없는이름"]:
            print("  ⚠ gr.%-14s %s" % (n, why))
    else:
        print("    확인한 이름 %d개 전부 실재" % r["확인"])

    print("\n[2] 넘기는 인자가 실제 시그니처에 있나 — **가짜는 이걸 못 본다**")
    print("─" * 70)
    if r["없는인자"]:
        print("  ⚠ **%d개가 없다. `py app.py` 가 TypeError 로 죽는다.**"
              % len(r["없는인자"]))
        for n, k, f in r["없는인자"]:
            print("     gr.%s(%s=…)  ← %s 에 그 인자가 없다" % (n, k, f))
    else:
        print("    불일치 없음")
    if r["모름"]:
        print("\n    확인 못 한 것 —")
        for n, why in r["모름"]:
            print("      gr.%-12s %s" % (n, why))

    print("\n[3] 생성자 **밖** — `launch` · 이벤트 배선 · 테마")
    print("─" * 70)
    print("    gradio 4 → 6 은 **메이저가 둘** 올랐다. `theme` 이 `Blocks` 에서")
    print("    `launch` 로 옮겨 갔고, `app.py` 가 그 분기를 갖고 있다.")
    rt = r.get("런타임") or []
    if rt:
        for where, why in rt:
            print("  ⚠ %-22s %s" % (where, why))
    else:
        print("    `Blocks.launch(theme·server_name·server_port)` ✅")
        print("    이벤트 트리거 `fn`·`inputs`·`outputs` ✅ · `gr.themes.Soft` ✅")

    print("\n" + "=" * 70)
    print("이 검사가 **하지 않는** 것")
    print("=" * 70)
    print("  · **화면을 안 띄웠다.** 레이아웃·색·줄바꿈은 여전히 미확인")
    print("  · 런타임 오류를 못 잡는다 — 타입이 맞아도 값이 틀리면 죽는다")
    print("  · **`py app.py` 를 대체하지 않는다.** 죽을 이유 하나를 줄일 뿐이다")

    print("\n" + "=" * 70)
    if r["없는이름"] or r["없는인자"] or r.get("런타임"):
        print("**불일치가 있다.** 띄우기 전에 고쳐라.")
        return 1
    print("불일치 없음 — **가짜 gradio 가 이 층에서는 거짓말하지 않았다.**")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="app.py ↔ 실제 gradio 대조")
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--venv", default=None,
                    help="site-packages 경로 (기본 .venv/Lib/site-packages)")
    a = ap.parse_args(argv)
    return report(audit(a.root, a.venv))


if __name__ == "__main__":
    sys.exit(main())
