# -*- coding: utf-8 -*-
"""GitHub 공개 사본 확인 — 심사위원이 **로그인 없이** 이 판을 보는가 (09-28 신설 · 읽기만).

    py -m bioreroute.bench.ghcheck

## 왜

저장소가 둘이다. 작업 저장소(`Bio-ReRoute` · 비공개)는 `커밋.ps1` 이 올리고, 공개 사본
(`Bio-ReRoute-public`)은 `.\\공개저장소.ps1 -Push` 만 올린다. 제출 양식 · 보고서 머리 · 공개 README 가
가리키는 것은 **공개 사본**이다.

주인은 로그인돼 있어 비공개 저장소도 보인다 — **주인의 눈으로는 «심사위원에게는 404» 를 못 가린다.**
`hfcheck` 가 HF 배포를 바이트로 맞추듯, 여기서는 **토큰 없는 요청**(심사위원과 같은 눈)으로 본다.
환경에 토큰이 있어도 붙이지 않는다.

## 보는 것 — 셋

    ① 익명으로 보이는가          api.github.com/repos/{주인/이름} → 200 · private 아님
    ② 올라간 것이 사본 폴더인가   공개 main 의 커밋 == 사본 폴더 HEAD · 사본 폴더에 안 올린 변경이 없다
    ③ 사본 폴더가 지금 판인가     사본 폴더의 파일 == 지금 `--apply` 하면 들어갈 파일
                                  (묶음 · 보고서 PDF · 상태 파일 · 커밋 요약 · .gitattributes)

돌려주는 값 — 0 전부 ✅ · 2 확인 못 함(네트워크 · 요청 한도) · 3 익명으로 안 보인다(없음 · 비공개) ·
4 보이지만 이 판이 아니다(사본 폴더가 없다 · 옛 판 · 안 올렸다) · 5 마감 뒤인데 비어 있다(올리지 않는다).

## 마감 뒤 (`공개저장소만들기.DEADLINE` · 10/2 16:00)

공개 사본은 **제출물**이다. 마감 뒤에 문서를 고치고 사슬을 돌리면 «이 판이 아니다» 가 나오는 게 당연하다 —
그때 «`-Push` 하라» 고 말하면 심사 중인 제출물을 바꾸라는 말이 된다. 그래서 마감 뒤에는 **보이기만 하면 0** 이고
«올리지 않는다» 고 말한다. 안 보이면(3) 공개 범위만 바꾸라고 한다(내용은 그대로). `push()` 도 마감 뒤에는 멈춘다.

**읽기만 한다.** 올리기는 `.\\공개저장소.ps1 -Push`, 공개로 바꾸기는 GitHub 설정 — 사람 일이다.
git 은 락을 잡지 않는 읽기 명령만 쓴다(`--no-optional-locks` · `CLAUDE.md §5`).
"""

import argparse
import datetime as _dt
import importlib.util
import json
import os
import subprocess
import urllib.error
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API = "https://api.github.com/repos/"
KST = _dt.timezone(_dt.timedelta(hours=9))


def _pm(root=ROOT):
    """공개 사본 도구 — 주소 · 사본 폴더 · 파일 목록은 **그 도구의 것을 그대로** 쓴다(두 곳에 두면 갈라진다)."""
    spec = importlib.util.spec_from_file_location("public_copy_for_ghcheck", os.path.join(root, "공개저장소만들기.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def slug(url):
    """`https://github.com/주인/이름(.git)` → `주인/이름`."""
    u = (url or "").strip().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    return u.split("github.com/", 1)[-1]


def headers():
    """토큰 없는 요청 머리 — **Authorization 을 붙이지 않는다**(심사위원과 같은 눈 · 시험 [208]⑥)."""
    return {"User-Agent": "bioreroute-ghcheck/1", "Accept": "application/vnd.github+json",
            "Cache-Control": "no-cache"}


def fetch(url, timeout=20):
    """(상태 코드, 본문 json). 네트워크 오류는 (None, 사유 문자열)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers()), timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8") or "null")
        except Exception:                                  # noqa: BLE001 — 본문이 json 이 아닐 수 있다
            body = None
        return e.code, body
    except Exception as e:                                 # noqa: BLE001 — 네트워크 · 프록시 · 시간 초과
        return None, "%s: %s" % (type(e).__name__, str(e)[:160])


def git(stage, *args):
    """읽기만 하는 git — (돌려준 값, 출력)."""
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", stage] + list(args),
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        return r.returncode, (r.stdout or "").strip()
    except Exception as e:                                 # noqa: BLE001 — git 이 없을 수 있다
        return 1, str(e)


def _kst(iso):
    try:
        t = _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return t.astimezone(KST).strftime("%m-%d %H:%M KST")
    except (TypeError, ValueError):
        return str(iso or "?")


def expected(root=ROOT, pm=None):
    """지금 `--apply` 하면 사본 폴더에 들어갈 것 — {상대 경로: bytes 또는 str}. 만들 수 없으면 None.

    커밋 요약은 **글자로** 비교한다 — `apply()` 가 글자 모드로 써서 윈도우에서는 CRLF 가 된다."""
    pm = pm or _pm(root)
    p = pm.plan(root)
    if not p.get("zip") or p.get("missing"):
        return None
    out = {}
    with zipfile.ZipFile(p["zip"]) as z:
        for dst, (src, name) in p["files"].items():
            if src == "zip":
                out[dst] = z.read(name)
            else:
                with open(os.path.join(root, name), "rb") as f:
                    out[dst] = f.read()
    out[pm.COMMIT_LOG] = pm.commit_log(root)
    out[pm.GITATTR] = pm.GITATTR_BODY.encode("utf-8")
    return out


def stage_diff(stage, want, mark):
    """사본 폴더와 기대값의 차이 — (빠진 것, 다른 것, 남는 것). `.git` 과 표시 파일은 안 본다."""
    have = {}
    for d, dirs, files in os.walk(stage):
        dirs[:] = [x for x in dirs if x != ".git"]
        for fn in files:
            rel = os.path.relpath(os.path.join(d, fn), stage).replace(os.sep, "/")
            if rel != mark:
                have[rel] = os.path.join(d, fn)
    differ = []
    for rel in sorted(set(want) & set(have)):
        w = want[rel]
        if isinstance(w, str):
            with open(have[rel], encoding="utf-8", errors="replace") as f:     # 줄바꿈은 \n 으로 읽힌다
                same = f.read() == w.replace("\r\n", "\n")
        else:
            with open(have[rel], "rb") as f:
                same = f.read() == w
        if not same:
            differ.append(rel)
    return sorted(set(want) - set(have)), differ, sorted(set(have) - set(want))


def _few(xs, n=3):
    return ", ".join(xs[:n]) + (" …" if len(xs) > n else "")


def check(root=ROOT, stage=None, pm=None, get=None, run_git=None, want=None):
    """(돌려줄 값, 찍을 줄들). 네트워크는 `get(url) -> (상태, json)`, git 은 `run_git(폴더, *인자)` 로만 탄다."""
    if pm is None and not os.path.exists(os.path.join(root, "공개저장소만들기.py")):
        return 2, ["⚪ 이 확인은 작업 저장소에서만 돈다 — 공개 사본 도구(`공개저장소만들기.py`)가 없다"]
    pm = pm or _pm(root)
    get = get or fetch
    run_git = run_git or git
    stage = stage or pm.STAGE_DEFAULT
    sl = slug(pm.PUBLIC_REPO)
    late = bool(getattr(pm, "after_deadline", lambda: False)())
    lines = ["GitHub 공개 사본 확인 — %s (토큰 없는 요청 · 읽기만)" % sl]

    # ③ 사본 폴더 — 네트워크 없이 먼저 본다
    local_ok, head = False, None
    if not (os.path.isdir(stage) and os.path.exists(os.path.join(stage, pm.MARK))):
        lines.append("  🔴 사본 폴더가 없다 — %s (아직 `.\\공개저장소.ps1 -Push` 를 안 돌렸다)" % stage)
    else:
        w = want if want is not None else expected(root, pm)
        if w is None:
            lines.append("  🔴 지금 판을 만들 수 없다(묶음 · 필수 파일) — `.\\공개저장소.ps1` 미리보기를 보라")
        else:
            miss, differ, extra = stage_diff(stage, w, pm.MARK)
            if miss or differ or extra:
                lines.append("  🔴 사본 폴더가 지금 판이 아니다 — 다른 것 %d · 빠진 것 %d · 남는 것 %d (%s)"
                             % (len(differ), len(miss), len(extra), _few(differ + miss + extra)))
            else:
                lines.append("  ✅ 사본 폴더가 지금 판이다 — 파일 %d개가 묶음 · 보고서 · 커밋 요약과 같다" % len(w))
                local_ok = True
        rc_h, head = run_git(stage, "rev-parse", "HEAD")
        head = head if rc_h == 0 and head else None
        rc_s, dirty = run_git(stage, "status", "--porcelain")
        if head is None:
            lines.append("  🔴 사본 폴더에 커밋이 없다 — `.\\공개저장소.ps1 -Push`")
            local_ok = False
        elif rc_s != 0 or dirty:
            lines.append("  🔴 사본 폴더에 안 올린 변경이 있다 — `.\\공개저장소.ps1 -Push`")
            local_ok = False

    # ① 익명으로 보이는가
    st, info = get(API + sl)
    if st is None or st in (403, 429) or (st != 404 and not (st == 200 and isinstance(info, dict))):
        why = info if st is None else "GitHub 가 %s 로 답했다%s" % (st, " (요청 한도)" if st in (403, 429) else "")
        lines += ["  ⚪ 확인 못 함 — %s" % why,
                  "→ **초록이 아니다.** 네트워크가 되는 곳에서 다시: py -m bioreroute.bench.ghcheck"]
        return 2, lines
    if st == 404 or info.get("private"):
        lines.append("  🔴 익명으로 **안 보인다**(404) — 아직 안 만들었거나 비공개다. 심사위원에게는 이 주소가 404 다")
        if head:
            rc_u, up = run_git(stage, "rev-parse", "origin/main")
            pushed = rc_u == 0 and up == head
            lines.append("  %s 사본 폴더 HEAD %s — %s" % ("✅" if pushed else "🔴", head[:7],
                         "마지막 push 와 같다(로컬 기록)" if pushed else "아직 push 안 됐다"))
        if late:
            lines.append("→ 🔴 심사위원에게 404 다 — Settings → Change visibility → Public (마감 뒤라 **내용은 바꾸지 않는다**)")
        else:
            lines.append("→ 🔴 제출 양식에 링크를 넣기 **전에** — (처음이면) github.com/new 에서 **빈** 저장소 %s → "
                         "`.\\공개저장소.ps1 -Push` → 비공개로 만들었으면 Settings → Change visibility → Public → "
                         "이 확인이 0" % sl.split("/")[-1])
        return 3, lines
    lines.append("  ✅ 익명으로 보인다 — %s (%s)" % (pm.PUBLIC_REPO, info.get("visibility") or "public"))

    # ② 공개 main 이 사본 폴더 HEAD 인가
    st2, c = get(API + sl + "/commits/main")
    if st2 == 409:
        if late:
            lines += ["  🔴 공개 저장소가 **비어 있다** — 마감 뒤다", "→ ⏹ 올리지 않는다 — 주최측 안내를 따른다"]
            return 5, lines
        lines += ["  🔴 공개 저장소가 **비어 있다**", "→ 🔴 `.\\공개저장소.ps1 -Push`"]
        return 4, lines
    if st2 != 200 or not isinstance(c, dict) or not c.get("sha"):
        lines += ["  ⚪ 공개 main 을 못 읽었다 — %s" % (c if st2 is None else "HTTP %s" % st2),
                  "→ **초록이 아니다.** 잠시 뒤 다시: py -m bioreroute.bench.ghcheck"]
        return 2, lines
    sha = c["sha"]
    when = _kst(((c.get("commit") or {}).get("committer") or {}).get("date"))
    same = bool(head) and sha == head
    lines.append("  %s 공개 main %s (%s) %s" % ("✅" if same else "🔴", sha[:7], when,
                 "== 사본 폴더 HEAD" if same else "≠ 사본 폴더 HEAD %s" % (head[:7] if head else "없음")))
    if same and local_ok:
        lines.append("→ ✅ 심사위원이 로그인 없이 이 판을 본다 (%s)" % pm.PUBLIC_REPO)
        return 0, lines
    if late:
        lines.append("→ ✅ 마감 뒤 — 공개 사본은 **제출한 판 그대로** 둔다(지금 판과 달라도 올리지 않는다 · %s)"
                     % pm.PUBLIC_REPO)
        return 0, lines
    lines.append("→ 🔴 공개 사본이 이 판이 아니다 — `.\\공개저장소.ps1 -Push` 뒤 다시 확인")
    return 4, lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="GitHub 공개 사본이 익명으로 보이고 이 판인가 (읽기만)")
    ap.add_argument("--stage", default=None, help="사본 폴더 (기본: 공개저장소만들기.STAGE_DEFAULT)")
    a = ap.parse_args(argv)
    rc, lines = check(stage=a.stage)
    for line in lines:
        print(line)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
