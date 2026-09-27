# -*- coding: utf-8 -*-
"""시험이 **저장소 폴더에 쓰지 못하게** 막는다 — 09-25 신설. 결함 335.

## 왜 — 규약이 네 번 샜다

09-25 에 전수 탐침을 돌렸다(감사 훅으로 저장소 폴더 쓰기를 전부 막고 기록하며
phase2 160개 · phase1 전부). **시험 넷이 저장소의 실제 자료 파일에 쓰고 있었다** —

    [138] run_pair 계측     pubmed_cache.json(48MB)을 읽고 **통째로 다시 썼다** · budget.json
    [134] 병명 입구         budget.json
    [116] 봉인 자기시험     archive/_봉인자기시험.md · 그 봉인 json
    [6]·zero ceiling CLI   ctgov_search_cache.json 에 **모의 응답이 섞였다**(7개 · 무해 확인)

첫째가 09-25 02:20 의 **48.9MB → 17.9MB** 를 만든 자리다 — 쓰는 도중에 끊겼다.
시험마다 «임시 경로를 써라» 는 **안내문**이었고, 안내문은 방어가 아니다.

## 무엇을 하나

시험이 도는 동안 저장소 폴더 아래로의 **쓰기 · 지우기 · 옮기기**를 막고
(`PermissionError`), **어느 시험이 어디에** 쓰려 했는지 모은다. 읽기는 그대로다.
부르는 쪽(`test_phase2._run_seq`)이 그것을 **실패로** 올린다 — 시험 안에서
`except Exception: pass` 로 삼켜져도 여기 기록은 남는다.

허용 — `__pycache__`(파이썬이 스스로 쓴다) · 임시 폴더(저장소 밖).

⚠ **자식 프로세스는 못 본다.** 감사 훅은 프로세스 안에서만 돈다. 09-25 탐침은
자식까지 봤고(sitecustomize) 자식 쪽 쓰기는 0이었다 — 그 사실에 기대는 것이다.
"""

import os
import sys
import threading

HITS = []                  # (시험, 사건, 경로) — 막은 것
_ON = [False]
_TEST = [""]
_ROOT = [None]
_INSTALLED = [False]
_TL = threading.local()
_W = (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def _inside(p, dir_fd=None):
    """`p` 가 저장소 폴더 안이고 `__pycache__` 가 아닌가."""
    if p is None or isinstance(p, int) or _ROOT[0] is None:
        return False
    try:
        s = os.fsdecode(p)
    except Exception:
        return False
    if isinstance(dir_fd, int) and not os.path.isabs(s):
        # rmtree 는 dir_fd 기준 **상대 이름**으로 지운다 — 현재 폴더로 풀면 오탐이다
        try:
            s = os.path.join(os.readlink("/proc/self/fd/%d" % dir_fd), s)
        except OSError:
            return False           # 모르면 막지 않는다 (윈도우에는 dir_fd 가 없다)
    a, r = _norm(s), _ROOT[0]
    if a != r and not a.startswith(r + os.sep):
        return False
    return "__pycache__" not in a[len(r):].split(os.sep)


def _hook(ev, args):
    if not _ON[0] or getattr(_TL, "busy", False):
        return
    _TL.busy = True
    try:
        bad = None
        if ev == "open":
            path, mode, flags = (tuple(args) + (None, None, None))[:3]
            wr = ((isinstance(mode, str) and any(c in mode for c in "wax+"))
                  or (isinstance(flags, int) and bool(flags & _W)))
            if wr and _inside(path):
                bad = path
        elif ev in ("os.rename", "shutil.move"):
            if _inside(args[0]) or _inside(args[1]):      # 옮겨 가는 것도 지우는 것이다
                bad = args[1] if _inside(args[1]) else args[0]
        elif ev in ("shutil.copyfile", "shutil.copystat", "shutil.copymode",
                    "os.link", "os.symlink"):
            if _inside(args[1]):                          # 읽어 오는 복사는 괜찮다
                bad = args[1]
        elif ev in ("os.remove", "os.rmdir", "os.mkdir"):
            if _inside(args[0], args[-1]):
                bad = args[0]
        elif ev in ("os.truncate", "os.chmod", "os.utime", "shutil.rmtree", "os.chown"):
            if _inside(args[0]):
                bad = args[0]
        if bad is not None:
            where = os.fsdecode(bad)
            HITS.append((_TEST[0], ev, where))
            raise PermissionError("[liveguard] 시험이 저장소 폴더에 쓰려 했다 — %s %s"
                                  % (ev, where))
    finally:
        _TL.busy = False


def install(root):
    """저장소 폴더를 정하고 훅을 한 번 건다. (훅은 뗄 수 없다 — `stop()` 으로 끈다)"""
    _ROOT[0] = _norm(root)
    if not _INSTALLED[0]:
        sys.addaudithook(_hook)
        _INSTALLED[0] = True


def start(name):
    _TEST[0] = name
    _ON[0] = True


def stop():
    _ON[0] = False


def rel(path):
    """보고용 — 저장소 기준 상대 경로."""
    try:
        return os.path.relpath(path, _ROOT[0]) if _ROOT[0] else path
    except ValueError:
        return path
