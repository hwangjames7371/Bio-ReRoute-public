# -*- coding: utf-8 -*-
"""배포 사전점검 — **올릴 파일만 남겼을 때 앱이 도는가.** LLM 비용 0.

    py -m bioreroute.bench.deploycheck
    py -m bioreroute.bench.deploycheck --strict     # 하나라도 걸리면 rc=1

## 왜 이게 필요한가

이 저장소에서 가장 많은 결함 유형이 **「검증 환경 ≠ 실행 환경」 12건**이다.
`/tmp` 하드코딩 · 모의가 실제 API와 다름 · `--help` 통과를 검증으로 착각 ·
그리고 08-10에 나온 결함 83(옆 폴더의 08-05판 코드 사본).

**배포는 실행 환경이 바뀌는 마지막 단계다.**

```
로컬              배포지 (HF Spaces)
─────────────    ─────────────────────────
파일 200여 개      배포.md §2 가 적은 것만
Windows 경로       Linux
cwd = 저장소       cwd = /home/user/app
gradio 6.22.0     Space 가 고르는 판
캐시 데워짐        비어 있을 수 있다
```

**로컬에서 도는 것은 배포지에서 돈다는 증거가 아니다.** 그래서 이 검사는
설명을 읽지 않고 **올릴 파일만 임시 폴더에 복사해 거기서 실제로 태운다.**

## 목록을 문서에서 읽는다 — 코드에 적지 않는다

`배포.md §2` 가 업로드 목록의 정본이다. 여기에 다시 적으면 **둘이 갈라지고,
갈라지면 문서가 맞는지 코드가 맞는지 아무도 모른다.** 결함 82가 그 유형이다.
목록이 바뀌면 이 검사가 자동으로 따라간다.

## 이 검사가 **못 보는** 것 — 먼저 적는다

- **진짜 gradio 로 안 띄운다.** 배선은 가짜로 태운다(시험 [55]와 같은 한계).
  화면 모양은 여전히 사람이 봐야 한다
- **HF Spaces 의 파이썬·gradio 판을 모른다.** `requirements.txt` 가
  `gradio>=4.44` 인데 실측은 **6.22.0 에서만** 했다
- **네트워크를 안 탄다.** 탭②(직접 검증)는 PubMed·LLM 이 필요하고
  여기서는 확인 못 한다. 탭①·③·3분할만 본다
- 업로드를 대신 하지 않는다
"""

import argparse
import ast
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ISSUES = []


def _say(ok, name, detail=""):
    mark = "  OK  " if ok else "  ⚠   "
    print("%s %-42s %s" % (mark, name, detail))
    if not ok:
        _ISSUES.append(name)


# ─────────────────────────────────────────────────────────────
# 1. 업로드 목록을 배포.md 에서 읽는다
# ─────────────────────────────────────────────────────────────
def manifest(path=None):
    """`배포.md §2` 의 업로드 목록을 파싱한다.

    돌려주는 것: `[(패턴, 필수인가), …]`
    *선택* 이라고 적힌 줄은 필수가 아니다 — **문서가 그렇게 말하면 그렇다.**
    """
    p = path or os.path.join(ROOT, "배포.md")
    try:
        s = open(p, encoding="utf-8").read()
    except Exception:
        return []
    i = s.find("아래 파일을 올린다")
    if i < 0:
        return []
    out = []
    for line in s[i:].split("\n")[1:]:
        if re.match(r"^\s*\d+\.\s", line) or line.startswith("```"):
            break
        raw = line.strip()
        if not raw:
            continue
        optional = ("선택" in raw)
        # 꼬리 주석을 떼어 낸다 — `(폴더 통째로)` · `← 필수` · `# …`
        head = re.split(r"\s{2,}|\s*←|\s*\(", raw)[0].strip()
        for tok in head.split("·"):
            tok = tok.strip().rstrip("/")
            if tok and not tok.startswith("#") and _looks_like_path(tok):
                out.append((tok, not optional))
    return out


# ⚠ **줄 단위 파서는 «접힌 주석» 을 파일 이름으로 읽는다** (08-21)
#
#   `web/` 을 목록에 넣으면서 설명을 두 줄로 접었더니, 둘째 줄
#   *«이 목록에 없어서, 올리면 **옛 화면**이 떴다»* 가 **필수 파일 하나**로
#   등록됐다. 그러면 배포 검사가 «없는 파일» 로 걸리고, 원인은
#   문서 줄바꿈이다 — 찾는 데 오래 걸리는 종류다.
#
#   문서를 한 줄로 쓰는 규율에만 기대지 않는다. **구조로 막는다** —
#   경로처럼 안 생긴 토큰은 버린다. (이 프로젝트의 규칙: *«안내문은
#   방어가 아니다»*.)
_PATHY = re.compile(r"^[A-Za-z0-9_.*가-힣][A-Za-z0-9_.*/\\가-힣-]*$")


def _looks_like_path(tok: str) -> bool:
    """파일·폴더 이름처럼 생겼나. **공백이나 문장부호가 있으면 아니다.**"""
    return bool(_PATHY.match(tok)) and len(tok) <= 60


def _expand(pattern):
    hits = glob.glob(os.path.join(ROOT, pattern))
    return sorted(hits)


# ── 올릴 때 이름이 바뀌는 것 ──────────────────────────────────────
#
#   HF Spaces 는 저장소 최상위 `README.md` 의 YAML 머리말로 SDK·판·
#   진입 파일을 정한다. 그런데 **이 저장소에는 이미 다른 `README.md`
#   가 있다** (개발자용). 둘을 한 파일로 합치면 한쪽이 반드시 틀려진다.
#
#   그래서 로컬에서는 `README_HF.md` 로 두고 **올릴 때만 이름을 바꾼다.**
RENAME = {"README_HF.md": "README.md"}


# ─────────────────────────────────────────────────────────────
# 2. 격리 복사 — **올릴 것만** 있는 폴더를 만든다
# ─────────────────────────────────────────────────────────────
def stage(dest, items):
    """업로드 목록만 `dest` 로 복사한다. 없는 것은 없는 채로 둔다."""
    missing = []
    copied = 0
    for pat, required in items:
        hits = _expand(pat)
        if not hits:
            if required:
                missing.append(pat)
            continue
        for src in hits:
            rel = RENAME.get(os.path.relpath(src, ROOT),
                             os.path.relpath(src, ROOT))
            dst = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(dst) or dest, exist_ok=True)
            if os.path.isdir(src):
                # __pycache__ 는 안 올린다 — 판이 섞이면 결함 83과 같은 사고가 난다
                shutil.copytree(src, dst, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(src, dst)
            copied += 1
    return copied, missing


# ─────────────────────────────────────────────────────────────
# 3. 격리 폴더 **안에서** 앱을 태운다
# ─────────────────────────────────────────────────────────────
_PROBE = r'''
# -*- coding: utf-8 -*-
"""격리 폴더 안에서 도는 정찰기. **부모 저장소를 못 보게** sys.path 를 좁힌다."""
import json, os, sys, types
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path = [HERE] + [p for p in sys.path if p and os.path.abspath(p) != HERE]

out = {}
def rec(k, v):
    out[k] = v

# ── 가짜 gradio (시험 [55]와 같은 것) ─────────────────────────
class _C:
    def __init__(s, *a, **k): s.a, s.k, s.calls = a, k, []
    # `**k` — **가짜가 진짜보다 좁으면 안 된다.** 08-11에 app.py 가
    # `show_progress="full"` 을 넘기자 여기서 터졌다(결함 104 곁가지).
    # 진짜 gradio 는 받는 인자다. 좁은 가짜는 **새 인자를 쓸 때마다**
    # 배포 점검을 거짓으로 붉게 만든다.
    def change(s, fn, inputs=None, outputs=None, **k):
        s.calls.append(fn)
        return s                  # `.then()` 사슬 — 없으면 None.then 으로 죽는다
    click = submit = then = change
    def __enter__(s): return s
    def __exit__(s, *e): return False
class _B(_C):
    def load(s, fn, inputs=None, outputs=None, **k):
        s.calls.append(fn)
        return s
class _FakeGradio(types.ModuleType):
    """**모르는 위젯 이름은 만들어 준다.**

    ## 왜 손목록을 버렸나 (08-14)

    앞판은 위젯 이름 열셋을 **손으로 적어 뒀다.** 그래서 `app.py` 에
    `gr.Checkbox` 를 넣자 배포 점검이 **`AttributeError` 로 붉어졌다** —
    코드는 멀쩡한데 **가짜가 좁아서** 난 실패다.

    바로 위 주석이 이미 그 교훈을 적어 놨다 —
    *"**가짜가 진짜보다 좁으면 안 된다.** 좁은 가짜는 새 인자를 쓸 때마다
    배포 점검을 거짓으로 붉게 만든다."* **인자에는 적용하고 이름에는
    적용을 안 했다.** 결함 60 계열 — **손목록은 곧 낡는다.**

    이제 `gr.무엇이든` 이 `_C` 를 돌려준다. 오탐이 0이 되고,
    **진탐은 그대로다** — 진짜로 확인하는 것은 «콜백이 걸렸는가» 이지
    «위젯 이름이 목록에 있는가» 가 아니다.
    """

    def __getattr__(self, name):            # `_` 로 시작하는 건 넘긴다
        if name.startswith("_"):
            raise AttributeError(name)
        return _C


fake = _FakeGradio("gradio")
fake.Blocks = _B
fake.update = lambda **k: dict(k)
fake.themes = types.SimpleNamespace(Soft=lambda **k: None, Base=lambda **k: None)
fake.__version__ = "6.22.0"
sys.modules["gradio"] = fake

try:
    import app
    rec("import", True)
    rec("root_ok", os.path.abspath(app.evidence.ROOT) == HERE)

    # 탭③ — 결함 수·봉인표가 **파일에서** 나오는가
    s = app.evidence.summary()
    rec("defects", s["결함"])
    rec("seals", len(s["봉인"]))
    rec("seals_ok", s["봉인_무결"])
    rec("seals_unknown", s["봉인_확인불가"])
    # **무엇이** 확인불가인지 싣는다 — 09-25 에 «확인불가 1개» 만 찍혀 찾아다녔다
    rec("seals_unknown_names", [x.get("대상") for x in (s["봉인"] or [])
                                if x.get("무결") is None])
    rec("seals_broken", s["봉인_깨짐"])
    rec("tab3_len", len(app._md_evidence()))
    nz = s.get("공개등록") or {}
    rec("nz_ots", bool(nz.get("ots")))
    rec("nz_match", nz.get("해시일치"))
    rec("nz_final", nz.get("확정"))

    # 탭① — 구운 사례
    c = app.evidence.cases()
    rec("cases", len(c["사례"]) if c else 0)

    # 3분할 — 첫 탭. 심사 30점 무대
    labels = app.dash.run_labels()
    L, C, upd = app._dash_run(labels[0], "표준")
    rec("left", len(L)); rec("center", len(C))
    rec("cands", len(upd.get("choices") or []))
    # ⚠ **개수를 박아 언팩하지 않는다** — 08-18에 여기서 걸렸다.
    #   `_dash_card` 가 좌측을 같이 돌려주게 되면서(결함 248) 5 → 6 이 됐고
    #   이 줄이 `too many values to unpack` 으로 죽었다. **가드가 잡은 건
    #   정상**이지만, 개수를 세는 대신 **필요한 것만 이름으로** 꺼내면
    #   화면 칸이 늘어도 안 깨진다.
    #   ⚠ 변수 이름을 `out` 으로 썼다가 **프로브의 결과 dict 를 덮었다**
    #     (`'tuple' object does not support item assignment`). 고치는 자리에서
    #     새로 만든 것 — 오늘 다섯 번째다. `slots` 로 좁힌다.
    slots = app._dash_card(upd.get("value"), "표준")
    rec("card_slots", len(slots))        # 칸 수 자체도 기록에 남긴다
    th, cd, sb = slots[0], slots[1], slots[4]
    rec("think", len(th)); rec("card", len(cd)); rec("side", len(sb))
    # 좌측이 **후보를 따라오는가** — 결함 248 이 여기서 안 보였다
    rec("left_follows", len(slots) >= 6 and bool(slots[5]))
    rec("auto", len(app.dash.autonomy()))
    rec("calib", len(app.dash.bottom_calibration()))
    # 근거 카드에 PMID 가 실제로 찍히는가 — `None` 이면 버그
    rec("pmid_none", "PMID None" in cd or "| None |" in cd)
    # ── B0 대조표의 **우리 칸**. 0건이면 우리 핵심 주장이 화면에서 뒤집힌다
    #    (결함 85). 길이로는 안 보인다 — 한 글자 차이다.
    import re as _re
    # 09-29 · 결함 378 — 행 이름이 «판정의 근거로 대는 것» 으로 바뀌었다(모델 단독의 «PMID 0건» 은 잰 값이
    #   아니라 설계 차이라 그 칸을 «기억하는 시험 이름» 으로 적는다). 우리 칸의 PMID 수를 읽는 것은 그대로다.
    #   옛 행 이름도 받는다 — 못 읽으면 -1 로 **걸린다**(없는 것과 못 읽은 것을 한 칸에 두지 않는다)
    m = (_re.search(r"판정의 근거로 대는 것 \|[^|]*\|[^|\n]*PMID\s*\*\*(\d+)건\*\*", sb)
         or _re.search(r"검증 가능한 PMID \|[^|]*\|\s*\*\*(\d+)건\*\*", sb))
    rec("b0_ours", int(m.group(1)) if m else -1)
except Exception as e:
    import traceback
    rec("import", False)
    rec("error", traceback.format_exc()[-900:])

# ── **새 화면도 여기서 태운다** (08-21) ─────────────────────────
#
#   08-20 에 Gradio 를 걷어내고 `web/server.py` 로 옮겼는데, 이 검사는
#   **`app.py` 만** 태우고 있었다. 즉 «올린 파일만 있을 때 도는가» 를
#   묻는 도구가 **실제로 올릴 화면은 한 번도 안 태웠다.**
#   이 저장소에서 가장 많은 결함 유형이 「검증 환경 ≠ 실행 환경」이고,
#   여기가 그 유형이 숨기 가장 좋은 자리다.
#
#   gradio 가 필요 없다 — 표준 라이브러리 서버라 그냥 임포트된다.
try:
    sys.path.insert(0, os.path.join(HERE, "web"))
    import server as _srv
    _b = _srv.get_json("/api/boot", {})
    rec("web_boot", ",".join(sorted(_b)))
    rec("web_cases", len(_b["cases"]["labels"]))
    rec("web_ev", len(_b["evidence"]["body"]))
    rec("web_cal", len(_srv.get_json("/api/dash/bottom", {})["cal"]))
    # 정적본 스냅샷 — 있으면 **여기서도** 열어 본다
    _snap = os.path.join(HERE, "web", "static", "data", "snapshot.json")
    if os.path.isfile(_snap):
        import json as _json
        rec("web_snap", len(_json.load(open(_snap, encoding="utf-8"))))
except Exception:
    import traceback
    rec("web_error", traceback.format_exc()[-500:])

print("@@JSON@@" + json.dumps(out, ensure_ascii=False))
'''


def probe(dest):
    p = os.path.join(dest, "_deploy_probe.py")
    open(p, "w", encoding="utf-8").write(_PROBE)
    # ⚠ encoding 을 박는다 — 08-27 에 preflight 이 cp949 로 읽다 멈췄다.
    #   `text=True` 만 주면 윈도우 한국어에서 OS 기본(cp949)을 쓴다.
    _env = dict(os.environ)
    _env["PYTHONIOENCODING"] = "utf-8"
    _env["PYTHONUTF8"] = "1"
    r = subprocess.run([sys.executable, p], cwd=dest, capture_output=True,
                       text=True, timeout=300,
                       encoding="utf-8", errors="replace", env=_env)
    for line in (r.stdout or "").split("\n"):
        if line.startswith("@@JSON@@"):
            import json
            return json.loads(line[8:])
    return {"import": False, "error": (r.stderr or r.stdout or "")[-900:]}


# ─────────────────────────────────────────────────────────────
# 4. 정적 검사 — 키·경로·의존성
# ─────────────────────────────────────────────────────────────
_KEY = re.compile(r"sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,}|"
                  r"hf_[A-Za-z0-9]{30,}")
# `C:\...` 나 `/home/...` 같은 **기계에 묶인 경로**. `/tmp` 도 결함 이력이 있다.
_ABSPATH = re.compile(r"[\"'](?:[A-Za-z]:[\\/]|/home/|/Users/|/tmp/)[^\"'\n]{2,}")


def scan_text(dest):
    keys, paths = [], []
    for root, dirs, files in os.walk(dest):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith((".py", ".txt", ".json")):
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, dest)
            if rel == "_deploy_probe.py":
                continue
            try:
                s = open(p, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            for m in _KEY.findall(s):
                keys.append("%s: %s…" % (rel, m[:10]))
            for m in _ABSPATH.findall(s):
                # 주석·독스트링 안의 예시는 실행에 안 쓰인다. 코드 줄만 본다.
                paths.append("%s: %s" % (rel, m[:52]))
    return keys, paths


_STDLIB_OK = {
    "gradio": "gradio", "litellm": "litellm", "rdkit": "rdkit-pypi",
    "pptx": "python-pptx", "markdown": "Markdown", "pypdf": "pypdf",
}


def imports_of(dest):
    """올린 코드가 실제로 부르는 **표준 라이브러리 밖** 모듈."""
    found = set()
    for root, dirs, files in os.walk(dest):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py") or f == "_deploy_probe.py":
                continue
            try:
                t = ast.parse(open(os.path.join(root, f),
                                   encoding="utf-8", errors="ignore").read())
            except Exception:
                continue
            for node in ast.walk(t):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        found.add(a.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        found.add(node.module.split(".")[0])
    return {m for m in found if m in _STDLIB_OK}


def _norm(name):
    """PyPI 이름 정규화 — `-`·`_`·`.` 와 대소문자를 구분하지 않는다 (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _venv_dists(root=None):
    """`.venv` 에 **실제로 깔린** 배포판 이름. 손으로 적은 목록이 아니다."""
    r = root or ROOT
    out = {}
    for pat in ("Lib/site-packages", "lib/python*/site-packages"):
        for sp in glob.glob(os.path.join(r, ".venv", pat)):
            for d in glob.glob(os.path.join(sp, "*.dist-info")):
                base = os.path.basename(d)[:-len(".dist-info")]
                if "-" in base:
                    nm, _, ver = base.rpartition("-")
                    out[_norm(nm)] = ver
    return out


def requirements_vs_venv(root=None):
    """선언한 이름이 **실제로 깔린 것과 같은 물건인가.** 결함 86."""
    r = root or ROOT
    have = _venv_dists(r)
    names, unpinned, unknown = [], [], []
    for line in open(os.path.join(r, "requirements.txt"), encoding="utf-8"):
        line = line.split("#")[0].strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9._-]+)\s*(==|>=|~=|>)?\s*([0-9][^\s;]*)?", line)
        if not m:
            continue
        nm, op, ver = m.group(1), m.group(2), m.group(3)
        names.append(nm)
        if op != "==":
            unpinned.append(nm)
        if not have:           # `.venv` 가 없으면 **판정하지 않는다**
            continue
        if _norm(nm) not in have:
            unknown.append(nm)
        elif op == "==" and ver and have[_norm(nm)] != ver:
            unknown.append("%s(핀 %s ≠ 설치 %s)" % (nm, ver, have[_norm(nm)]))
    return names, unpinned, unknown


def sdk_vs_requirements(root=None):
    """`README_HF.md` 의 `sdk_version` 과 requirements 의 gradio 판."""
    r = root or ROOT
    sdk = grd = None
    try:
        s = open(os.path.join(r, "README_HF.md"), encoding="utf-8").read()
        m = re.search(r"^sdk_version:\s*([0-9][0-9.]*)\s*$", s, re.M)
        sdk = m.group(1) if m else None
    except Exception:
        pass
    try:
        s = open(os.path.join(r, "requirements.txt"), encoding="utf-8").read()
        m = re.search(r"^gradio\s*==\s*([0-9][0-9.]*)", s, re.M)
        grd = m.group(1) if m else None
    except Exception:
        pass
    return sdk, grd


# ─────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description="HF Spaces 배포 사전점검")
    ap.add_argument("--strict", action="store_true",
                    help="하나라도 걸리면 rc=1")
    ap.add_argument("--keep", action="store_true", help="임시 폴더를 남긴다")
    ap.add_argument("--stage", metavar="DIR",
                    help="검사 후 **올릴 폴더를 그 자리에 만든다** (끌어다 놓기용)")
    a = ap.parse_args(argv)

    print("=" * 70)
    print("배포 사전점검 — **올릴 파일만 남겼을 때 도는가**")
    print("=" * 70)

    items = manifest()
    _say(len(items) >= 5, "배포.md §2 에서 업로드 목록을 읽었다",
         "%d 항목" % len(items))
    if not items:
        print("\n  목록을 못 읽었다. `배포.md` 의 *아래 파일을 올린다* 블록을 확인해라.")
        return 1

    dest = tempfile.mkdtemp(prefix="bioreroute_deploy_")
    try:
        n, missing = stage(dest, items)
        _say(not missing, "필수 파일이 전부 있다",
             "복사 %d건" % n if not missing else "없음: " + ", ".join(missing))
        for pat, req in items:
            hits = _expand(pat)
            print("       %-28s %s%s" % (pat, "%d건" % len(hits) if hits else "❌ 없음",
                                         "" if req else "  (선택)"))

        print()
        keys, paths = scan_text(dest)
        _say(not keys, "실제 API 키가 안 섞여 있다",
             "0건" if not keys else "; ".join(keys[:3]))
        _say(not paths, "기계에 묶인 절대경로가 없다",
             "0건" if not paths else "; ".join(paths[:3]))

        need = imports_of(dest)
        req_txt = open(os.path.join(ROOT, "requirements.txt"),
                       encoding="utf-8").read().lower()
        miss = sorted(p for m in need
                      for p in [_STDLIB_OK[m]] if p.lower() not in req_txt)
        _say(not miss, "부르는 외부 모듈이 requirements 에 다 있다",
             "%d개 확인" % len(need) if not miss else "빠짐: " + ", ".join(miss))

        # ── 결함 86 — **있는지** 는 봤는데 **같은 것인지** 는 안 봤다 ──
        #
        #   `requirements.txt` 가 `rdkit-pypi` 를 요구했는데 `.venv` 에
        #   있는 건 공식 `rdkit` 이었다. **별개 배포판**이고 앞의 것은
        #   2022.09.5 에서 멈춘 옛 커뮤니티 빌드다. 신선한 환경에서
        #   설치하면 **한 번도 안 써 본 물건**이 깔린다.
        #
        #   PyPI 이름은 `-`↔`_`, 대소문자를 구분하지 않으므로 정규화해서
        #   비교한다 — `python-pptx`↔`python_pptx` 는 통과해야 하고
        #   `rdkit-pypi`↔`rdkit` 은 걸려야 한다.
        req_names, unpinned, unknown = requirements_vs_venv()
        _say(not unknown,
             "requirements 의 이름이 **`.venv` 에 실제로 있다**",
             "%d개 대조" % len(req_names) if not unknown
             else "없는 이름: " + ", ".join(unknown))
        _say(not unpinned,
             "판을 **핀(`==`)으로** 박았다 — 하한은 안 시험한 주장이다",
             "%d개" % len(req_names) if not unpinned
             else "하한: " + ", ".join(unpinned))

        # `README_HF.md` 의 sdk_version 과 requirements 의 gradio 판이
        # 갈리면 **어느 쪽이 이기는지 우리가 모른다.**
        sdk, grd = sdk_vs_requirements()
        _say(sdk is not None and sdk == grd,
             "README 의 `sdk_version` = requirements 의 gradio 판",
             "sdk %s · req %s" % (sdk, grd))

        print()
        print("[격리 실행] 올린 파일만 있는 폴더에서 **app.py 를 실제로 태운다**")
        r = probe(dest)
        if not r.get("import"):
            _say(False, "app.py 가 격리 폴더에서 임포트된다", "실패")
            print("\n" + (r.get("error") or "")[-900:])
            return 1
        _say(True, "app.py 가 격리 폴더에서 임포트된다")
        _say(bool(r.get("root_ok")), "evidence.ROOT 가 격리 폴더를 가리킨다",
             "부모 저장소를 안 본다")
        _say(bool(r.get("defects")), "탭③ 결함 수를 **파일에서** 셌다",
             "%s건" % r.get("defects"))
        _say(r.get("seals", 0) >= 5, "탭③ 봉인 표",
             "%s개 · 무결 %s · 확인불가 %s · 깨짐 %s"
             % (r.get("seals"), r.get("seals_ok"),
                r.get("seals_unknown"), r.get("seals_broken")))
        _say(r.get("seals_broken") == 0, "봉인이 하나도 안 깨졌다")
        # **확인불가도 실패로 센다.** 반증 시험에서 나온 것 —
        # `봉인예측_20260805.csv` 를 안 올리면 깨진 게 아니라 *확인 불가* 가
        # 되고, 화면은 조용히 "— 확인 불가" 를 찍는다. 봉인표는 이 프로젝트의
        # 가장 강한 증거인데 **그 칸이 비어도 앱은 멀쩡히 뜬다.**
        _say(r.get("seals_unknown") == 0,
             "봉인 대상 파일이 하나도 안 빠졌다",
             "확인불가 %s개%s" % (r.get("seals_unknown"),
                               (" — " + " · ".join(map(str, r.get("seals_unknown_names") or [])))
                               if r.get("seals_unknown_names") else ""))
        if r.get("seals_unknown_names"):
            print("         → 봉인 json 은 올라가는데 **대상 문서가 목록에 없다.** "
                  "`배포.md §2` 의 «아래 파일을 올린다» 에 더해라")
        _say(r.get("cases", 0) >= 3, "탭① 구운 사례가 있다 — **키 없이 열린다**",
             "%s건" % r.get("cases"))
        # 제3자 타임스탬프(결함 51). **증명서가 그 문서의 것인지**까지 본다 —
        # 다른 파일의 `.ots` 를 올려 두면 아무 의미가 없다.
        _say(bool(r.get("nz_ots")), "제3자 타임스탬프 증명서가 같이 올라간다")
        _say(r.get("nz_match") is True,
             "그 증명서가 **이 문서의 것**이다 (sha256 일치)")
        # **확정은 실패로 안 센다.** 접수 직후엔 미확정이 정상이다.
        # 다만 화면에 미확정이라고 적히는지가 중요하다 — 결함 70.
        print("  %s %-42s %s" % ("  OK  " if r.get("nz_final") else "  ⓘ   ",
              "OpenTimestamps 확정 여부",
              "✅ 비트코인 블록 확정" if r.get("nz_final")
              else "🟡 **접수됨 · 미확정** — 몇 시간 뒤 Upgrade 필요"))
        for k, label, floor in (("left", "3분할 좌", 100),
                                ("center", "3분할 중", 100),
                                ("think", "사고 과정 (심사 30점)", 200),
                                ("card", "근거 카드", 100),
                                ("side", "B0 대조", 100),
                                ("auto", "자율성 (심사 10점)", 200),
                                ("calib", "보정 표", 100)):
            _say(r.get(k, 0) >= floor, "%s 가 내용을 낸다" % label,
                 "%s자" % r.get(k))
        _say(r.get("cands", 0) >= 1, "후보 목록이 채워진다",
             "%s건" % r.get("cands"))
        _say(not r.get("pmid_none"), "근거 카드에 `None` PMID 가 없다")
        # 결함 85 — **길이 검사로는 안 보이는 층.** `demo_cases.json` 이
        # 빠지면 이 표가 `0건 | 0건` 으로 뜬다. 우리 핵심 주장(*판정마다
        # PMID 가 붙는다*)이 **화면에서 스스로 반박된다.** 그런데 경고가
        # 안 뜨고 표는 멀쩡히 그려진다 — 결함 35와 같은 계열이다
        # (**막은 것과 없는 것을 구분하지 않았다**).
        _say(r.get("b0_ours", 0) > 0,
             "B0 대조표에서 **우리 칸이 0건이 아니다**",
             "PMID %s건" % r.get("b0_ours"))

        # ── 새 화면(`web/server.py`)도 격리 폴더에서 태웠다 ────────────
        #
        #   08-21 까지 이 검사는 **`app.py` 만** 봤다. Gradio 를 걷어낸
        #   지 하루가 지났는데도 그랬다 — 즉 «올릴 파일만 있을 때 도는가»
        #   를 묻는 도구가 **실제로 올릴 화면은 한 번도 안 태웠다.**
        print()
        print("[격리 실행] 같은 폴더에서 **새 화면(web/server.py)** 도 태운다")
        if r.get("web_error"):
            _say(False, "web/server.py 가 격리 폴더에서 도는다", "실패")
            print("\n" + r["web_error"][-500:])
            return 1
        _say(bool(r.get("web_boot")), "`/api/boot` 이 화면 자료를 낸다",
             r.get("web_boot", ""))
        _say(r.get("web_cases", 0) >= 3, "판정 사례가 채워진다",
             "%s건" % r.get("web_cases"))
        _say(r.get("web_ev", 0) > 500, "반증 기록이 채워진다",
             "%s자" % r.get("web_ev"))
        _say(r.get("web_cal", 0) > 100, "보정 표가 채워진다",
             "%s자" % r.get("web_cal"))
        # 정적본은 **선택**이다 — 없으면 «없다» 고만 적고 실패로 안 센다
        if r.get("web_snap"):
            _say(True, "정적 스냅샷이 같이 올라간다 — `?static=1` 예비본",
                 "경로 %s개" % r.get("web_snap"))
        else:
            print("  --   정적 스냅샷이 없다 — `py -m web.build_static` 로 구우면"
                  " 서버가 죽어도 열리는 예비본이 생긴다")

        # ── --stage : 올릴 폴더를 그 자리에 만든다 ────────────────────
        #
        #   **결함 83 을 여기서 되풀이하면 안 된다.** 그건 `ctgov_pages/` 안에
        #   패키지 사본이 있는 걸 아무도 몰라서 생긴 것이다. 그래서
        #   ① 검사를 통과했을 때만 만들고
        #   ② 폴더 안에 **무엇인지 적은 표식**을 같이 넣고
        #   ③ 매번 지우고 새로 만든다 (낡은 사본이 안 남게)
        if a.stage:
            if _ISSUES:
                print()
                print("  --stage 를 건너뛴다 — **검사가 걸린 상태로 폴더를 만들지 않는다**")
            else:
                sd = os.path.abspath(a.stage)
                shutil.rmtree(sd, ignore_errors=True)
                # **선택 항목은 안 넣는다.** `pubmed_cache.json` 이 29.5MB 인데
                # 탭①은 `demo_cases.json` 을 읽으므로 없어도 돈다 — 탭②만 느려진다.
                sn, _ = stage(sd, [(p, r) for p, r in items if r])
                skipped = [p for p, r in items if not r]
                open(os.path.join(sd, "_이_폴더는_무엇인가.txt"), "w",
                     encoding="utf-8").write(
                    "이 폴더는 **자동 생성된 업로드 사본**이다.\n"
                    "  · 원본은 상위 폴더다. **여기를 고치지 마라** — 반영 안 된다\n"
                    "  · 목록의 정본은 `배포.md §2` 다\n"
                    "  · 다시 만들려면:  py -m bioreroute.bench.deploycheck --stage %s\n"
                    "\n"
                    "**여기서 `py -m bioreroute...` 를 치지 마라.**\n"
                    "옆 폴더에 패키지 사본을 두고 잊은 적이 있다(결함 83).\n"
                    % os.path.basename(sd))
                tot = sum(os.path.getsize(os.path.join(r, f))
                          for r, d, fs in os.walk(sd) for f in fs)
                print()
                print("  올릴 폴더를 만들었다 — **여기 내용을 통째로 끌어다 놓으면 된다**")
                print("     %s" % sd)
                print("     %d건 · %.2f MB" % (sn, tot / 1e6))
                if skipped:
                    print("     선택 항목은 뺐다: %s" % ", ".join(skipped))
                    print("     (탭①은 `demo_cases.json` 을 읽으므로 캐시 없이 돈다."
                          " 탭②만 느려진다)")

        print()
        print("=" * 70)
        if _ISSUES:
            print("**%d 항목이 걸렸다.** 올리기 전에 고쳐라." % len(_ISSUES))
            for x in _ISSUES:
                print("   · " + x)
        else:
            print("격리 실행 통과. **다만 이 검사가 못 보는 것을 읽어라** —")
            print("   · 진짜 gradio 로 안 띄웠다. **화면 모양은 사람이 봐야 한다**")
            print("   · **HF 가 `sdk_version: 6.22.0` 을 받아주는지 모른다** —"
                  " 지원 목록을 확인 못 했다")
            print("   · **신선한 `pip install -r requirements.txt` 를 한 적이"
                  " 없다** — 결함 86이 거기서 나왔다")
            print("   · 탭②(직접 검증)는 네트워크가 필요해 **여기서 확인 못 했다**")
            # 08-21 — 새로 생긴 구멍. **적어 두지 않으면 «다 봤다» 가 된다.**
            print("   · **정적본을 «정적 호스팅에서» 띄워 본 적이 없다** —"
                  " 우리 서버가 파일을 내줬을 뿐이다.")
            print("       닫는 법:  py -m http.server 8123 -d 배포정적"
                  "   → http://127.0.0.1:8123/")
        print("=" * 70)
        return 1 if (_ISSUES and a.strict) else 0
    finally:
        if a.keep:
            print("\n임시 폴더: %s" % dest)
        else:
            shutil.rmtree(dest, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
