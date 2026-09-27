# -*- coding: utf-8 -*-
"""배포 올리기 — `배포정적/` 을 HF Space 에 **명령 하나로** (09-26 신설).

## 왜 — 그리고 **선택**이다

09-25 에 끌어다 놓기가 두 번 막혔다 — 커밋까지 안 감(16:0x) · 주인이 아닌 계정이라 PR 이
됨(20:49~21:02 · 다섯). 화면 조작은 **어디서 멈췄는지 안 남는다.** 그래서 API 커밋 하나로
올리는 길을 **하나 더** 둔다. ⚠ 09-26 낮에 `hfcheck` 🔴 가 세 번 이어져 이 파일을 만들었는데,
그 셋은 **올리기 전에 확인만 돌린 것**이었다(`hfcheck` 는 확인만 한다) — 12:47 에 한 파일을
`static/data` 올리기 주소에 끌어다 놓아 **토큰 없이** 끝났다. 나는 그걸 «네 번째로 막혔다» 로
잘못 읽었다. **기본 길은 여전히 끌어다 놓기**(`hfcheck` 🔴 가 폴더별 주소를 찍는다)이고 이건
쓰기 토큰이 있을 때 쓰는 선택이다 —

    .\배포올리기.ps1            무엇이 다른지만 본다 (안 올린다 · 토큰 필요 없음)
    .\배포올리기.ps1 -Apply     다른 파일만 커밋하고 hfcheck 로 잰다

## 지키는 것

- **토큰은 환경변수(`HF_TOKEN`)로만 받는다.** 파일에 안 적고 화면에 안 찍는다.
  `.ps1` 이 비어 있으면 **가려진 입력**으로 묻고(명령 기록에 안 남는다) 끝나면 지운다
- 토큰의 계정이 **Space 주인이 아니면 안 올린다** — 09-25 의 PR 다섯이 그 모양이었다
- **다른 파일만** 올린다(blob 이름으로 비교 · `hfcheck` 와 같은 식). 같으면 아무것도 안 한다
- 커밋은 **방금 본 main 위에만** 얹는다(`parent_commit`) — 그 사이 누가 올렸으면 실패한다
- 올린 뒤 **`hfcheck` 가 0 이어야** 성공이다 — 서빙이 늦으면(4) 잠깐 기다려 다시 잰다

## 돌려주는 값

    0  같다 — 이미 같거나, 올린 뒤 hfcheck 0
    1  미리보기만 했다(-Apply 없음) — 올릴 파일이 있다
    2  못 했다(토큰 · 라이브러리 · 네트워크 · 커밋 거절)
    3  토큰 계정이 Space 주인이 아니다 · 올린 뒤에도 다르다
    4  커밋은 됐는데 배포 주소가 아직 옛 것 — 1~2분 뒤 `hfcheck`

⚠ `huggingface_hub` 는 `gradio` 가 같이 깐다(따로 적지 않았다). 없으면 설치 안내만 찍는다.
⚠ 이 파일은 **실제 라이브러리로 샌드박스에서 못 돌렸다**(PyPI 가 막혀 있다) — 시험 [197] 은
   가짜 API 로 흐름을 잰다. 실제 경로는 승우 컴퓨터의 첫 `-Apply` 가 처음이다.
"""

import argparse
import datetime as _dt
import inspect
import os
import time

from . import hfcheck as H

TOKEN_ENV = "HF_TOKEN"


def plan(stage=H.STAGE, space=H.SPACE, get=None):
    """(바뀐 파일 [(경로, 크기)], Space 정보, 오류) — `hfcheck` 와 같은 비교(blob 이름)."""
    get = get or H._get
    loc = H.local_files(stage) if os.path.isdir(stage) else {}
    if not loc:
        return None, None, "로컬 `%s` 가 없거나 비었다 — 사슬 ⑩(정적판)부터" % stage
    try:
        info = H._json(get, H.API + space)
        files = H._files(H._json(get, H.API + space + "/tree/main?recursive=true"))
    except Exception as e:
        return None, None, "HF 에 묻지 못했다: %s" % ((str(e) or type(e).__name__)[:160],)
    changed = [(rel, len(data)) for rel, data in sorted(loc.items())
               if rel not in files or not H._same(files[rel], data)]
    return changed, info, None


def _ops(changed, stage):
    """커밋할 파일들 — `huggingface_hub` 가 있으면 그 객체, 없으면 (경로, 파일) 짝(시험용)."""
    try:
        from huggingface_hub import CommitOperationAdd
    except ImportError:
        CommitOperationAdd = None
    out = []
    for rel, _n in changed:
        p = os.path.join(stage, *rel.split("/"))
        out.append(CommitOperationAdd(path_in_repo=rel, path_or_fileobj=p) if CommitOperationAdd else (rel, p))
    return out


def apply(changed, info, stage=H.STAGE, space=H.SPACE, api=None, token=None,
          wait=(6, 10), get=None, now=None):
    """(돌려줄 값, 줄들). `api` 는 시험이 바꿔 끼운다 — 없으면 `HfApi(token)`."""
    owner = space.split("/")[0]
    token = token if token is not None else os.environ.get(TOKEN_ENV, "")
    if not token:
        return 2, ["⛔ 토큰이 없다 — `.\\배포올리기.ps1 -Apply` 가 가려진 입력으로 묻는다 (환경변수 %s)"
                   % TOKEN_ENV]
    if api is None:
        try:
            from huggingface_hub import HfApi
        except ImportError:
            return 2, ["⛔ huggingface_hub 가 없다 — `py -m pip install huggingface_hub` 뒤 다시 (gradio 가 보통 같이 깐다)"]
        api = HfApi(token=token)
    try:
        who = (api.whoami() or {}).get("name")
    except Exception as e:                      # 토큰 문자열은 절대 찍지 않는다 — 예외 종류만
        return 2, ["⛔ 토큰으로 계정을 못 읽었다 — 만료·오타·권한(쓰기)을 보라 (%s)" % type(e).__name__]
    if str(who).lower() != owner.lower():
        return 3, ["⛔ 이 토큰은 **%s** 계정이다 — Space 주인(**%s**)이 아니면 안 올린다 "
                   "(09-25 의 PR 다섯이 그 모양이었다)" % (who, owner)]
    ops = _ops(changed, stage)
    msg = "배포 %s · %d개 (배포올리기)" % ((now or _dt.datetime.now()).strftime("%m-%d %H:%M"), len(ops))
    kw = dict(repo_id=space, repo_type="space", operations=ops, commit_message=msg)
    try:
        if "parent_commit" in inspect.signature(api.create_commit).parameters and (info or {}).get("sha"):
            kw["parent_commit"] = info["sha"]    # 방금 본 main 위에만 — 그 사이 바뀌었으면 거절된다
    except (TypeError, ValueError):
        pass
    try:
        res = api.create_commit(**kw)
    except Exception as e:
        return 2, ["⛔ 커밋이 거절됐다 — %s: %s" % (type(e).__name__, str(e)[:200])]
    lines = ["→ 커밋했다 — %s (%s) · %s" % (msg, str(getattr(res, "oid", "") or "?")[:7],
                                           ", ".join(r for r, _n in changed))]
    tries, pause = wait
    rc, ls = 2, []
    for i in range(max(1, tries)):
        rc, ls = H.check(stage, space, get=get)
        if rc != 4:
            break
        if i < tries - 1:
            time.sleep(pause)
    return (0 if rc == 0 else (3 if rc in (3, 5) else rc)), lines + ls


def main(argv=None):
    ap = argparse.ArgumentParser(description="배포정적 → HF Space (다른 파일만 · 토큰은 환경변수로만)")
    ap.add_argument("--stage", default=H.STAGE)
    ap.add_argument("--space", default=H.SPACE)
    ap.add_argument("--apply", action="store_true", help="실제로 올린다 (없으면 미리보기)")
    a = ap.parse_args(argv)
    changed, info, err = plan(a.stage, a.space)
    if err:
        print("⚪ " + err)
        return 2
    print("배포 올리기 — %s · HF main %s" % (a.space, str((info or {}).get("sha") or "?")[:7]))
    if not changed:
        print("→ ✅ 이미 같다 — 올릴 것 없음")
        return 0
    for rel, n in changed:
        print("  · %-28s %s B" % (rel, format(n, ",")))
    if not a.apply:
        print("→ 미리보기다 — 위 %d개를 올리려면  .\\배포올리기.ps1 -Apply" % len(changed))
        return 1
    rc, lines = apply(changed, info, a.stage, a.space)
    for line in lines:
        print(line)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
