# -*- coding: utf-8 -*-
"""배포 확인 — HF Space 가 **로컬 `배포정적/` 과 같은 판**을 내주는가 (09-25 신설).

## 왜

09-25 16:00 «올렸어» 를 받고 배포 주소의 파일을 받아 보니 **08-25 판**이었다.
Space 커밋 기록에 그날 것이 **0건** — 업로드 화면에서 커밋까지 가지 않은 것이다.
화면은 옛 판으로도 멀쩡히 뜬다. **눈으로는 «올렸다» 와 «안 올라갔다» 가 구별되지
않는다.** `배포.md §6` 은 09-16 부터 «재배포가 필요하다» 고 적고 있었고, 그 문장은
그동안 아무것도 막지 못했다 — **안내문은 방어가 아니다.** 그래서 잰다:

    py -m bioreroute.bench.hfcheck

## 무엇을 비교하나

HF 저장소 API(`/api/spaces/<id>/tree/main?recursive=true`)는 파일마다 **git blob
sha1**(`oid`)을 준다. 로컬 파일도 같은 식 — `sha1(b"blob <크기>\\0" + 내용)` — 으로
계산해 **내용**을 맞춘다. 크기·시각으로 재지 않는다(크기가 같은 옛 판이 있을 수 있다).

⚠ **배포 주소가 내주는 바이트로 재지 않는다.** `*.static.hf.space` 는 `index.html`
을 저장소와 **다른 바이트로** 내준다(09-25 실측: 저장소 16,697B · 서빙 16,798B —
HF 가 무언가를 덧붙인다). 그래서 기준은 저장소 oid 이고, 서빙 쪽은
**`snapshot.json` 하나만** 따로 본다(09-25 실측: 저장소와 바이트가 같았다). 저장소는
새 판인데 주소가 아직 옛 것이면 «⏳» 다.

## 같은 날 두 번째 — **PR 로 들어갔다** (20:49)

다시 올렸는데 `main` 은 그대로였다. 파일은 **Space 주인이 아닌 계정**으로 올라가
HF 가 커밋 대신 **PR #1** 을 만들어 두었다 — 내용은 로컬과 바이트까지 같았다.
이때 «다르다 → 다시 올려라» 라고 말하면 **PR 이 하나 더 생길 뿐이다.** 그래서
`main` 이 다르면 **열린 PR 들**(`refs/pr/N`)도 맞춰 보고, 이 판이 거기 있으면
«주인 계정으로 병합하라» 로 갈라 말한다(5).

## 21:1x — **주소를 옮겼다** (James2358 → James7371)

옛 Space 의 주인 계정으로는 들어갈 수 없어, 늘 쓰는 계정(James7371)에 **새 Space** 를
만들기로 했다(승우 결정). 옛 주소는 08-25 판에 멈춰 있다 — 본선 제출물이 아니고, 고치지 않는다. **데모 주소의 정본은 여기 `SPACE` 하나다** — 발표 슬라이드
(`slides/build_deck.py`)와 영상 대본 생성기(`slides/make_video_본선.py`)가 `DEMO_HOST` 를
가져다 쓴다. 문서 쪽은 시험 [194]⑭ 가 «현재 문서가 이 주소를 쓰는가» 를 본다.

## 돌려주는 값

    0  같다 — 배포 주소가 이 판을 내준다
    3  다르다 · HF 에 없다 · 폴더째 올렸다 · **Space 가 없다(404)** — **다시 올려라 / 만들어라**
    5  이 판이 **열린 PR** 에 있다 — 주인 계정으로 **Merge** (다시 올리지 마라)
    4  저장소는 이 판인데 배포 주소가 아직 옛 것 — 잠시 뒤 다시
    2  확인 불가(네트워크·응답 모양·로컬 폴더 없음) — **초록이 아니다**

⚠ **읽기만 한다.** 아무 파일도 쓰지 않는다. 네트워크는 `check(get=…)` 하나로만
타므로 시험이 바꿔 끼운다(시험 [194] — 네트워크 없이 09-25 응답의 모양으로 잰다).
"""

import argparse
import datetime as _dt
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

SPACE = "James7371/bio-reroute"            # 09-25 21:1x 부터 — 데모 주소의 정본 (위 «주소를 옮겼다»)
OLD_SPACE = "James2358/bio-reroute"        # 08-24~09-25 · 08-25 판에 멈춤 · 본선 제출물이 아니다
STAGE = "배포정적"
API = "https://huggingface.co/api/spaces/"
SERVED = "static/data/snapshot.json"       # 서빙 쪽은 이것 하나만 본다 (위 ⚠)
SKIP = {"desktop.ini", "Thumbs.db", ".DS_Store"}
HF_DEFAULTS = {".gitattributes"}           # HF 가 만든 채로 두는 파일 — 목록에서 뺀다
KST = _dt.timezone(_dt.timedelta(hours=9))


def host(space=SPACE) -> str:
    """정적 Space 의 전체화면 주소 — HF 규칙: `<주인>-<이름>` 소문자 + `.static.hf.space`."""
    return "%s.static.hf.space" % space.lower().replace("/", "-")


DEMO_HOST = host()                         # 발표·영상 대본이 이것을 쓴다 — 손으로 적지 않는다
DEMO_URL = "https://" + DEMO_HOST


def after_deadline(root=None) -> bool:
    """제출 마감이 지났나 — 09-29 · 마감 시각은 `공개저장소만들기.DEADLINE` **하나**에서 읽는다(두 곳에 적으면 갈린다).

    데모 주소도 **제출물**이다. 마감 뒤에 사슬을 돌리면 배포정적이 바뀌어 🔴 가 나는 게 당연하고, 그때 «올려라» 를
    찍으면 심사 중인 제출물을 바꾸라는 말이 된다 — `ghcheck` 가 공개 사본에서 같은 이유로 그렇게 한다.
    도구를 못 읽으면 **마감 전으로** 본다(확인만 하는 명령이라 올리기를 막지 못해도 해가 없다 · 안내만 달라진다).
    """
    import importlib.util as _iu
    r = root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    p = os.path.join(r, "공개저장소만들기.py")
    try:
        spec = _iu.spec_from_file_location("pubcopy_hf", p)
        m = _iu.module_from_spec(spec)
        spec.loader.exec_module(m)
        return bool(m.after_deadline())
    except Exception:                                    # noqa: BLE001
        return False


def blob_sha1(data: bytes) -> str:
    """git 이 파일 내용에 매기는 이름 — HF tree API 의 `oid` 와 같은 식."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def local_files(stage):
    """{상대경로('/' 구분): 내용 bytes} — 숨은 파일·윈도우 부산물은 뺀다."""
    out = {}
    for root, dirs, files in os.walk(stage):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(files):
            if f.startswith(".") or f in SKIP:
                continue
            p = os.path.join(root, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, stage).replace(os.sep, "/")] = fh.read()
    return out


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "bioreroute-hfcheck/1",
                                               "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _same(entry, data):
    """저장소 항목과 로컬 내용이 같은가. LFS 로 올라간 파일은 sha256 으로 잰다."""
    lfs = entry.get("lfs") or {}
    if lfs.get("oid"):
        return hashlib.sha256(data).hexdigest() == str(lfs["oid"]).split(":")[-1]
    return entry.get("oid") == blob_sha1(data)


def _kst(iso):
    try:
        t = _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return t.astimezone(KST).strftime("%m-%d %H:%M KST")
    except (TypeError, ValueError):
        return str(iso or "?")


def _b(n):
    return format(int(n or 0), ",")


def _json(get, url):
    return json.loads(get(url).decode("utf-8"))


def _files(tree):
    return {e.get("path"): e for e in (tree if isinstance(tree, list) else [])
            if isinstance(e, dict) and e.get("type") == "file"}


def _open_prs(space, get):
    """열린 PR 목록 — 새것부터. (09-25 실측 모양: `{"discussions": [{num, author{name}, status,
    isPullRequest, createdAt, …}], "count": …}`)"""
    d = _json(get, API + space + "/discussions?type=pull_request")
    items = d.get("discussions") if isinstance(d, dict) else None
    prs = [x for x in (items or []) if isinstance(x, dict)
           and x.get("isPullRequest") and x.get("status") == "open" and isinstance(x.get("num"), int)]
    return sorted(prs, key=lambda x: -x["num"])


def _pr_diff(space, num, loc, get):
    """PR #num 의 트리를 로컬 판과 견준다 → (이 판에서 빠지는 것, 이 판과 다른 것). 둘 다 비면 같은 판."""
    files = _files(_json(get, API + space + "/tree/refs%%2Fpr%%2F%d?recursive=true" % num))
    missing = [r for r in sorted(loc) if r not in files]
    differ = [r for r in sorted(loc) if r in files and not _same(files[r], loc[r])]
    return missing, differ


def _pr_lines(rows, hit, owner):
    """열린 PR 마다 «Merge 하나 · Close · ⛔ Merge 금지» 를 붙인다 (21:0x — 삭제 PR 셋이 섞여 쌓였다).

    주인이 Community 탭에서 PR 다섯을 보면 **어느 것을 눌러야 하는지 모른다.** 삭제 PR 을
    병합하면 `snapshot.json` 이나 `README.md`(Space 설정)가 main 에서 지워져 데모가 깨진다.
    """
    out = ["  열린 PR %d개:" % len(rows)]
    for x, miss, diff in rows:
        n, title = x["num"], str(x.get("title") or "")[:28]
        if not miss and not diff:
            tag = ("✅", "이 판과 같다 → **이것 하나만 Merge**") if x is hit else \
                  ("· ", "#%d 과 같은 내용 → Close" % hit["num"])
        elif miss:
            tag = ("⛔", "이 판에서 %d개가 빠진다(%s) → **Merge 금지** · Close" % (len(miss), ", ".join(miss)))
        else:
            tag = ("⛔", "이 판과 %d개가 다르다 → **Merge 금지** · Close" % len(diff))
        out.append("    %s #%-3d %-28s %s" % (tag[0], n, title, tag[1]))
    others = sorted({(x.get("author") or {}).get("name") for x, _m, _d in rows} - {owner, None})
    if others:
        out.append("  ⚠ 올린 계정 %s 은 Space 주인(%s)이 아니다 — 그 계정으로 하는 올리기·삭제는 **전부 PR 이 될 뿐** "
                   "main 을 못 바꾼다. **%s 로 로그인**해서 처리하라" % (", ".join(others), owner, owner))
    return out


def check(stage=STAGE, space=SPACE, get=None, late=None):
    """(돌려줄 값, 찍을 줄들). 네트워크는 `get(url) -> bytes` 하나로만 탄다. `late` 는 시험에서만 준다."""
    get = get or _get
    late = after_deadline() if late is None else bool(late)
    if not os.path.isdir(stage):
        return 2, ["⚪ 확인 불가 — 로컬 `%s` 폴더가 없다. `py -m web.build_static --stage %s` 부터"
                   % (stage, stage)]
    loc = local_files(stage)
    if not loc:
        return 2, ["⚪ 확인 불가 — 로컬 `%s` 폴더가 비었다" % stage]
    try:
        info = json.loads(get(API + space).decode("utf-8"))
        tree = json.loads(get(API + space + "/tree/main?recursive=true").decode("utf-8"))
        if not isinstance(info, dict) or not isinstance(tree, list):
            raise ValueError("응답 모양이 다르다 (info=%s · tree=%s)"
                             % (type(info).__name__, type(tree).__name__))
    except urllib.error.HTTPError as e:
        if e.code == 404:                           # 모르는 게 아니라 **없다** — 만들 차례다
            return 3, ["🔴 Space 가 없다 — %s (HF 404)" % space,
                       "→ https://huggingface.co/new-space 에서 **%s** 계정으로 이름 **%s** · SDK **Static** 으로 "
                       "만든 뒤 `%s` 폴더 **안의** 것을 올린다 (배포.md §2)"
                       % (space.split("/")[0], space.split("/")[-1], stage)]
        return 2, ["⚪ 확인 불가 — HF 가 %s 로 답했다" % e.code,
                   "   **초록이 아니다.** 잠시 뒤 다시: py -m bioreroute.bench.hfcheck"]
    except Exception as e:                          # 네트워크·JSON·모양 — 전부 «모른다»
        return 2, ["⚪ 확인 불가 — HF 에 묻지 못했다: %s" % ((str(e) or type(e).__name__)[:160],),
                   "   **초록이 아니다.** 네트워크가 되는 곳에서 다시: py -m bioreroute.bench.hfcheck"]

    files = _files(tree)
    top = os.path.basename(os.path.normpath(stage))
    lines = ["HF 배포 확인 — %s · 저장소 마지막 커밋 %s (%s)"
             % (space, _kst(info.get("lastModified")), str(info.get("sha") or "?")[:7])]
    bad = 0
    w = max(len(k) for k in loc)
    for rel in sorted(loc):
        data, e = loc[rel], files.get(rel)
        if e is None:
            bad += 1
            lines.append("  🔴 없다    %-*s  로컬 %s B · HF 에 없다" % (w, rel, _b(len(data))))
        elif _same(e, data):
            lines.append("  ✅ 같다    %-*s  %s B" % (w, rel, _b(len(data))))
        else:
            bad += 1
            lines.append("  🔴 다르다  %-*s  로컬 %s B · HF %s B"
                         % (w, rel, _b(len(data)), _b(e.get("size"))))

    nested = sorted(p for p in files if p.split("/")[0] == top)
    if nested:
        bad += 1
        lines.append("  🔴 폴더째 올라갔다 — `%s` 등 %d개가 `%s/` 아래에 있다. 폴더를 **열고** "
                     "안의 것을 올려라 (배포.md §2)" % (nested[0], len(nested), top))
    idx = (loc.get("index.html") or b"").decode("utf-8", "replace")
    for p in sorted(set(files) - set(loc) - set(nested) - HF_DEFAULTS):
        used = p in idx
        lines.append("  %s HF 에만 있다  %s — %s"
                     % ("⚠" if used else "·", p,
                        "**index.html 이 부른다**" if used else "index.html 이 부르지 않는다 (화면과 무관)"))

    if bad and late:
        # 09-29 · 마감 뒤에는 올리기 · 병합을 권하지 않는다 — 데모 주소는 제출물이다(`after_deadline` 독스트링)
        lines.append("→ ⏹ 마감 뒤다 — 데모 주소는 **제출한 판 그대로** 둔다(지금 판과 %d개가 달라도 올리지 않는다 · "
                     "주최측이 고치라고 한 경우에만)" % bad)
        return 0, lines
    if bad:
        # 20:49 — 주인이 아닌 계정으로 올리면 커밋 대신 PR 이 생긴다. 그때 «다시 올려라» 는 PR 을 하나 더 만든다.
        owner = str(info.get("author") or space.split("/")[0])
        rows, hit = [], None
        try:
            for x in _open_prs(space, get):
                rows.append((x,) + _pr_diff(space, x["num"], loc, get))
            same = [x for x, m, d in rows if not m and not d]
            hit = min(same, key=lambda x: x["num"]) if same else None   # 같은 판이 여럿이면 먼저 연 것
        except Exception as e:
            rows, hit = [], None
            lines.append("  ⚪ 열린 PR 은 확인하지 못했다 (%s)" % ((str(e) or type(e).__name__)[:80],))
        if rows:
            lines += _pr_lines(rows, hit, owner)
        if hit:
            lines.append("→ 🟡 이 판은 **PR #%d** 에 있다 — 올린 계정 %s · %s · `main` 에는 아직 없다"
                         % (hit["num"], (hit.get("author") or {}).get("name", "?"), _kst(hit.get("createdAt"))))
            lines.append("   Space 주인(%s) 계정으로 https://huggingface.co/spaces/%s/discussions/%d 에서 **Merge**"
                         "%s. **다시 올리지 마라** — PR 이 하나 더 생긴다"
                         % (owner, space, hit["num"], " · 나머지 열린 PR 은 **Close**" if len(rows) > 1 else ""))
            return 5, lines
        # 09-26 · 이 명령은 **확인만** 한다 — 🔴 를 세 번 받는 동안 «이걸 돌리면 올라간다» 로 읽힐 여지가
        #   있었다. 그래서 **바뀐 파일을 폴더별로** 모아 그 폴더의 올리기 주소를 찍는다(12:47 에 실제로
        #   `static/data` 주소에 한 파일을 올려 끝났다 — 폴더째 끌어다 놓기보다 틀릴 자리가 적다).
        lines.append("→ 🔴 %d개 중 %d개가 이 판과 다르다 — **이 명령은 확인만 한다.** 올리는 법 "
                     "(**주인(%s) 계정으로** — 아니면 PR 이 된다 · 배포.md §2):" % (len(loc), bad, owner))
        todo = {}
        for rel in sorted(loc):
            e = files.get(rel)
            if e is None or not _same(e, loc[rel]):
                d, _s, name = rel.rpartition("/")
                todo.setdefault(d, []).append(name)
        for d in sorted(todo):
            lines.append("   · %s → https://huggingface.co/spaces/%s/upload/main%s 에 끌어다 놓고 «Commit changes to main»"
                         % (" · ".join("`%s`" % n for n in todo[d]), space, ("/" + d) if d else ""))
        lines.append("   · 또는  .\\배포올리기.ps1 -Apply   (쓰기 토큰이 있을 때 · 선택)")
        return 3, lines

    host = str(info.get("host") or "").rstrip("/")
    if not host or SERVED not in loc:
        lines.append("→ ✅ 저장소가 이 판이다 (배포 주소는 안 봤다 — host 또는 `%s` 없음)" % SERVED)
        return 0, lines
    try:
        got = get("%s/%s?v=%d" % (host, urllib.parse.quote(SERVED), int(time.time())))
    except Exception as e:
        lines.append("→ 저장소는 이 판이다 · ⚪ 배포 주소는 확인 불가 (%s)" % ((str(e) or type(e).__name__)[:80],))
        return 2, lines
    if got != loc[SERVED]:
        lines.append("→ ⏳ 저장소는 이 판인데 배포 주소(%s)가 아직 옛 `%s` 를 내준다 — 1~2분 뒤 다시"
                     % (host, SERVED))
        return 4, lines
    lines.append("→ ✅ 배포 주소가 이 판을 내준다 (%d개 전부 같다 · %s)" % (len(loc), host))
    return 0, lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="HF 배포가 로컬 배포정적과 같은 판인가 (읽기만)")
    ap.add_argument("--stage", default=STAGE, help="비교할 로컬 폴더 (기본 배포정적)")
    ap.add_argument("--space", default=SPACE, help="HF Space id (기본 %s)" % SPACE)
    a = ap.parse_args(argv)
    rc, lines = check(a.stage, a.space)
    for line in lines:
        print(line)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
