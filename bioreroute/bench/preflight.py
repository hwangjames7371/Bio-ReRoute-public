# -*- coding: utf-8 -*-
"""장(章)을 넘길 때 돌리는 전수 검증 — **명령 하나**

    py -m bioreroute.bench.preflight            # 자동 검사 전부 + 수동 렌즈 출력
    py -m bioreroute.bench.preflight --strict   # 수동 렌즈까지 답해야 통과

## 왜 이 파일이 있나

08-06 하루에 같은 질문(*"제안서랑 비교해서 빠진 게 있나"*)을 여덟 번 받았고,
**여덟 번 다 새로 나왔다** — 결함 43~60, 총 18건.

그런데 여덟 번의 렌즈가 서로 달랐다. 매번 *다른 층*을 봤기 때문에 나왔고,
**그 층 목록이 사람 머릿속에만 있었다.** 그게 이 파일이 생긴 이유다.

이 프로젝트의 원칙 그대로 — **안내문은 방어가 아니다. 구조로 막아야 한다.**
그래서 렌즈를 최대한 **기계가 볼 수 있게** 바꿨고, 못 바꾼 것은
못 바꿨다고 적었다.

## 여덟 렌즈와 각각이 실제로 잡은 것

| # | 렌즈 | 잡은 결함 | 자동화 |
|---|---|---|---|
| 1 | §3.3 항목을 구현했나 | 39·41 | 🟡 문서 대조 |
| 2 | **§1~§8 전수**를 구현했나 | 42·43 (hERG·저분자·§6 화면) | 🟡 |
| 3 | 구현한 것이 **실제로 도는가**(배선) | 44·45 | ✅ 호출부 계수 |
| 4 | **재는 것이 잰다고 말하는 것인가** | 46·47 (정답표 37%) | ✅ `labelaudit` |
| 5 | 우리 기여가 **정말 우리 것인가** | 50~53 (선행연구) | ❌ 사람 |
| 6 | **내놓으면 무슨 일이 생기나** | 54~57 (면책·다중성) | 🟡 면책만 |
| 7 | **오늘 쓴 코드**를 적대적으로 | 58·59 | ✅ 최근 변경 목록 |
| 8 | **가드가 안 보는 곳** | 60 (pptx) | ✅ 산출물 커버리지 |

**5번은 자동화가 안 된다.** 선행연구 검색은 사람이 해야 하고,
그게 가장 늦게(5차) 나온 이유이기도 하다.
"""

import argparse
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 렌즈 3 · 8 — 기계가 볼 수 있는 것 ───────────────────────
# 새 모듈을 만들고 **아무도 안 부르는** 상태로 두는 것이 결함 44였다.
WIRED_EXEMPT = {"__init__", "tests", "run", "netcheck", "diag", "agreement",
                "app", "evidence", "demo", "viewer", "config"}
# 제출물 — 이 중 감사가 안 보는 게 있으면 그게 사각지대다 (결함 60)
DELIVERABLES = ["연구기술보고서.pdf", "slides/Bio-ReRoute_발표.pptx",
                "bioreroute-v*.zip", "app.py"]

# ── 자동화가 **안 되는** 렌즈. 사람이 답해야 한다 ─────────────
MANUAL: List[Tuple[str, str, str]] = [
    ("선행연구", "이번 장에서 새로 주장하는 것이 있나? 있으면 **검색했나?**",
     "결함 50 — 그동안 줄곧 안 찾았고, 첫 검색에서 RareAgent 가 나왔다"),
    ("사전지정", "이번 장의 **주지표를 결과 보기 전에** 적었나?",
     "결함 55 — 서사의 중심 숫자(79%)가 사후였다"),
    ("다중비교", "심사 문서에 실릴 검정이 몇 개인가? **탐색적인 것을 셌나?**",
     "결함 56 — 세어 본 적이 없었다. 세니 통과하지만 그게 요점이 아니다"),
    ("반증 조건", "이번 장의 주장을 **틀리게 만들 관찰**을 적었나?",
     "결함 53 — 포퍼가 참고문헌 [1]인데 중심 명제에 반증 조건이 없었다"),
    ("불리한 수치", "이번 장에서 **우리에게 불리한 값**을 심사 문서에 넣었나?",
     "결함 46 — ECE 가 보고서·1페이지·발표 셋 다에서 빠져 있었다"),
]


LENS_FILE = "렌즈답변.md"


def lens_freshness(root: str = ROOT, days: int = 2) -> dict:
    """`렌즈답변.md` 가 **최근 바뀐 코드보다 새로운가** (결함 64).

    ## 왜 이 검사가 생겼나

    `검증절차.md` 가 여덟 렌즈를 정하고 **자기 한계를 이렇게 적었다** —

      > **수동 5개는 강제할 방법이 없다.** `--strict` 는 화면에 찍을 뿐이다

    **그게 그 문서를 만든 날 밤에 실현됐다.** 08-06 심야에 `faithful.py` 와
    활성부위 pLDDT 를 넣으면서 선행연구를 안 찾았고, 뒤늦게 찾으니
    **둘 다 선행연구가 있었고 하나는 우리 전제를 반증**했다(결함 65·66).

    화면에 찍는 것은 방어가 아니었다. 그래서 **파일의 존재와 최신성**을
    본다 — 이 프로젝트가 예순 번 배운 *"안내문은 방어가 아니다"* 그대로다.

    ## 이 검사가 **못 보는 것** — 먼저 적는다

    **내용이 성실한지 못 본다.** 다섯 항목에 "안 했다"만 다섯 번 써도
    통과한다. 그건 의도한 것이다 — *"안 했다"고 적힌 것과 빈 칸은 다르다.*
    강제할 수 있는 최소가 **빈 칸을 없애는 것**이고, 그 이상은 못 한다.

    그리고 **mtime 은 약한 신호다.** 파일을 열어 저장만 해도 새로워진다.
    그래서 최신 장 제목과 채워진 항목 수를 **같이 찍어** 사람이 볼 수 있게
    한다 — 숫자 하나로 통과·실패를 판단하게 두지 않는다.
    """
    out = {"error": None, "latest": None, "answered": 0,
           "stale": False, "newest_code": None}
    p = os.path.join(root, LENS_FILE)
    if not os.path.exists(p):
        out["error"] = "`%s` 가 없다. **수동 렌즈 답변을 적을 자리가 없다.**" % LENS_FILE
        out["stale"] = True
        return out
    try:
        s = open(p, encoding="utf-8").read()
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
        out["stale"] = True
        return out

    # 최신 장 = 첫 `## ` 블록. 날짜로 정렬하지 않는다 — **맨 위가 최신**이라는
    # 규약을 파일 머리에 적었고, 날짜 파싱은 형식이 흔들리면 조용히 틀린다.
    heads = [l for l in s.split("\n") if l.startswith("## ")]
    blocks = s.split("\n## ")
    body = blocks[1] if len(blocks) > 1 else ""
    for h in heads:
        if re.search(r"20\d\d-\d\d-\d\d", h):
            out["latest"] = h[3:].strip()[:60]
            break
    # 다섯 항목이 최신 블록에 다 있는가. 태그로 센다.
    out["answered"] = sum(1 for tag, _q, _w in MANUAL if tag in body)

    # 최근 바뀐 코드보다 오래됐는가
    rec = recent(root, days)
    if rec:
        out["newest_code"] = rec[0]
        try:
            newest = max(os.path.getmtime(os.path.join(root, r)) for r in rec)
            out["stale"] = os.path.getmtime(p) < newest
        except Exception:
            pass
    return out


def _run(cmd: List[str]) -> Tuple[int, str]:
    """자식 시험을 돌리고 출력을 받는다.

    ## ⚠ `encoding` 을 반드시 박는다 — 08-27 아침에 여기서 멈췄다

        UnicodeDecodeError: 'cp949' codec can't decode byte 0x80

    `text=True` 만 주면 파이썬이 **OS 기본 인코딩**으로 읽는다. 윈도우 한국어는
    그게 **cp949** 다. 그런데 자식 시험은 UTF-8 로 찍으므로 한글이 든 줄에서
    터진다. 부모가 죽지는 않고 **요약줄만 못 읽어서** 시험 수가 0으로 세지는데,
    그게 더 나쁘다 — **조용히 틀린 값이 나온다.**

    `CLAUDE.md` 가 `$env:PYTHONIOENCODING="utf-8"` 규약을 적어 두었지만
    **사람이 매번 기억해야 하는 것은 방어가 아니다.** 여기서 못 박는다.
    자식 환경에도 같이 넣어 자식이 UTF-8 로 찍도록 강제한다.

    `errors="replace"` 는 그래도 깨진 바이트가 오면 **죽지 말고 계속 가라**는
    뜻이다. 요약줄 하나 때문에 전수 검증이 통째로 멈추면 안 된다.
    """
    # ── ⚠ 09-01 · **900초는 애초에 부족했다** ────────────────────────
    #
    #   `재현절차.md` 는 phase2 를 **20~40분**이라 적어 뒀는데 여기
    #   제한이 **15분**이었다. 08-31·09-01 오전에 통과한 것은 **운**이고,
    #   시험 둘([152]·[153])을 더하자 `TimeoutExpired` 가 났다.
    #
    #   ⚠ 그때 화면이 이렇게 나온다 —
    #       FAIL 회귀 시험 (phase2)   TimeoutExpired
    #       OK   문서 간 일관성        불일치 없음
    #   **두 번째 「OK」는 통과가 아니다.** 정본(`시험정본.json`)을 못
    #   써서 **대조를 건너뛴 것**이다. 실패가 다음 검사를 조용히
    #   무력화한다 — 결함 35 계열(«못 함»을 «괜찮음»으로 읽는 것).
    #
    #   40분(2400초)으로 올린다. **시험이 더 늘면 또 봐야 한다.**
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        p = subprocess.run([sys.executable] + cmd, cwd=ROOT,
                           capture_output=True, text=True, timeout=2400,
                           encoding="utf-8", errors="replace", env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 2, "%s: %s" % (type(e).__name__, e)


# ── **울긴 우는데 무엇 때문인지 안 말하는 가드** (08-22 아침 점검) ──────
#
#   08-22 정본 출력의 첫 다섯 줄이 이랬다 —
#
#       OK   회귀 시험 (phase1)     ==========================================
#       FAIL 회귀 시험 (phase2)     ==========================================
#       FAIL 문서 간 일관성           **불일치 2항목.** …
#
#   **다섯 중 셋이 `=====` 였고, 하필 숫자를 가진 셋이 전부 그랬다.**
#   원인은 «마지막 비어 있지 않은 줄» 을 뽑은 것이다. 도구들이 출력을
#   구분선으로 닫기 때문에 **정작 답인 「통과 N · 실패 M」 은 세 줄 위**에
#   남는다.
#
#   그래서 `preflight` 은 «phase2 가 FAIL» 까지만 말하고 **몇 개 중 몇이
#   왜 깨졌는지 한 글자도 안 말했다.** 사람이 20~40분짜리 시험을 **또**
#   돌려야 했다 — 점검 지침이 *«시험을 따로 또 돌리지 마라»* 라고 적은
#   바로 그 비용이다.
#
#   결함 136 이 *«늘 우는 가드는 눈 감은 가드와 같다»* 라고 했다.
#   **이건 그 사촌이다 — 우는데 이유를 안 말하는 가드.**
#
#   고침 — 꼬리에서 **뜻이 있는 줄**을 고른다. 구분선·빈 줄·`##FAILED##`
#   같은 표식은 건너뛰고, 실패가 있으면 **실패 줄을 같이** 붙인다.
_NOISE = re.compile(r"^(=+|-+|#+|\*+|\s*)$|^##FAILED##")


#: `test_phase2` 가 실패를 **한 줄씩** 찍을 때 쓰는 접두사.
#  **두 파일의 계약**이다 — 한쪽만 바꾸면 실패 목록이 조용히 사라진다.
#  시험 [168]이 두 상수를 실제로 대조한다.
FAIL_LINE = "실패상세:"


def _fails(out: str) -> list:
    """시험 출력에서 **실패 목록**을 뽑는다.

    ⛔ **09-21 — 첫 판은 «실패:» 한 줄만 봤고, 그래서 못 뽑았다.**
    `test_phase2` 는 `실패: A, B, C` 처럼 **쉼표로 이어** 찍는다.
    검사 이름에 쉼표가 들어갈 수 있어 **부르는 쪽에서 쪼갤 수 없다.**
    그래서 찍는 쪽이 `FAIL_LINE` 으로 **한 줄씩** 내도록 고쳤고,
    여기서는 그 줄만 읽는다.

    ⚠ **옛 판(`실패:` 한 줄)으로 되돌아가면 빈 목록이 나온다.**
    그때는 목록을 안 찍을 뿐 판정(rc)은 그대로다 — **조용히 틀리지
    않게** 부르는 쪽에서 «목록을 못 읽었다» 를 말한다.
    """
    return [l.strip()[len(FAIL_LINE):].strip()
            for l in (out or "").split("\n")
            if l.strip().startswith(FAIL_LINE)]


def _gist(out: str, limit: int = 76) -> str:
    """명령 출력 → **한 줄 요약.** 구분선을 요약으로 내지 않는다."""
    lines = [l.rstrip() for l in (out or "").strip().split("\n")]
    good = [l.strip() for l in lines if l.strip() and not _NOISE.match(l.strip())]
    if not good:
        return "(출력 없음)"
    # ① 「통과 N · 실패 M」 꼴이 있으면 **그게 답이다** — 뒤에서 찾는다
    head = ""
    for l in reversed(good):
        if re.search(r"통과\s*\d+", l) or "불일치" in l or "이상 " in l:
            head = l
            break
    if not head:
        head = good[-1]
    # ② 실패가 적혀 있으면 **무엇이 깨졌는지**를 붙인다
    fails = [l for l in good if l.startswith("실패:")]
    if fails:
        head = "%s  ← %s" % (head, fails[0][3:].strip())
    # ③ **«불일치 N항목» 만 찍는 것은 답이 아니다** — 08-24 재발.
    #
    #   같은 날 아침에 `_gist` 를 만든 이유가 *«숫자를 `=====` 로 가린다»*
    #   였는데, 그 고침이 이번엔 **«어느 항목이 어긋났는지» 를 가렸다.**
    #   승우가 출력을 붙여넣기 전까지 아무도 몰랐고, 나는 내 쪽에서
    #   초록인 것만 보고 **«왜 다르지» 를 추측했다.** `CLAUDE.md §5` 다 —
    #   **검증 환경이 실행 환경과 다르면 그 검증은 거짓말이다.**
    #   가림을 한 겹 줄인다: `docaudit` 이 진짜 불일치에만 붙이는 `⚠` 를
    #   읽어 **항목 이름**을 같이 낸다(예외 항목은 `⚠` 가 없다).
    if "불일치" in head:
        names, seen = [], set()
        for l in good:
            if not l.startswith("⚠"):
                continue
            nm = re.split(r"\s{2,}|\*\*", l[1:].strip())[0].strip()
            if nm and nm not in seen:
                seen.add(nm)
                names.append(nm)
        if names:
            head = "%s  ← %s" % (head, " · ".join(names))
    # **잘랐으면 잘랐다고 말한다.** 조용히 자르는 것이 이 함수의 원죄다.
    return head if len(head) <= limit else head[:limit - 1] + "…"


# 제출(본선) 모델 — `사전명세_모델교체_본선.md` «terra 그대로 간다» ·
#   `홀드아웃_본선모델_결과.md` «제출은 terra». 바꾸려면 명세부터다.
SUBMIT_MODEL = "openai/gpt-5.6-terra"


def submit_model() -> Dict[str, Any]:
    """이 창의 파이썬이 보는 모델이 **제출 모델**인가 — 09-25 신설.

    ## 왜

    실험 스크립트(`luna.ps1` · `표적재시험.ps1` · `추출복제.ps1`)는 모델을
    **환경변수로 박고 끝나면 되돌리므로** `.env` 와 상관없다. 그런데 **화면
    (`웹.ps1`) · 시연 · 예시 재생성은 `.env` 를 읽는다.** 09-23 luna 실행 때
    `.env` 를 luna 로 바꾼 채 이틀이 지났고 **아무 검사도 안 울렸다** — 승우가
    물어서 알았다. 그대로 두면 시연 영상과 오프라인 발표가 **제출하지 않은
    모델**로 돈다.

    `.env` 파일이 아니라 **파이썬이 실제로 보는 값**(`llm.MODEL`)을 본다 —
    환경변수가 `.env` 를 이기므로(`config.load_env`) 어느 쪽이 원인이든
    **결과가 틀리면** 잡는다.
    """
    from ..io import llm
    return {"모델": llm.MODEL, "본선": SUBMIT_MODEL, "맞다": llm.MODEL == SUBMIT_MODEL}


def git_health(root: str = ROOT) -> Dict[str, Any]:
    """저장소 상태 — **09-22 에 여기서 둘이 터졌다** (결함 322·323).

    ## 왜 이 검사가 생겼나

    `preflight` 이 배포·문서·시험·봉인을 전부 보는데 **git 만 안 봤다.**
    그 결과 —

    ```
    09-16  `.git/index.lock` 이 남아 커밋이 막혔다 — **엿새 동안 아무도 몰랐다**
    09-21  캐시 33MB 를 잃었다 → git 이 없어 **08-05 백업 파일**로 복구
           그 백업이 하필 **오염을 걷어내기 전 판**이라 `leakcheck` 가 54/54 실패
    09-22  «GitHub 에 보냈었다» 는 기억을 따라 push → **남의 논문 저장소**였다
           `--force` 였으면 그쪽이 사라졌다. **막은 것은 git 이지 우리가 아니다**
    ```

    ## 무엇을 «실패» 로 세고 무엇을 «경고» 로 두나

    | | | 왜 |
    |---|---|---|
    | 락이 남았다 | 🔴 **실패** | 커밋이 통째로 막힌다. 판단할 것이 없다 |
    | 리모트에 **공통 조상이 없다** | 🔴 **실패** | 남의 저장소다. `--force` 하나로 파괴된다 |
    | 미커밋이 많다 | ⚠ 경고 | 정상일 수 있다(작업 중) |
    | 마지막 커밋이 오래됐다 | ⚠ 경고 | 쉬는 날이 있다 |

    ⚠ **오탐이 쌓이면 가드는 꺼진다**(결함 136). 그래서 판단이 필요한
    둘은 경고로 둔다. 다만 **울지 않는 가드**(결함 136의 반대편)도
    피해야 하므로 **파괴로 이어지는 둘은 실패**로 센다.

    ⚠ `merge-base` 는 **로컬에 받아 둔 추적 정보**로 답한다. `fetch` 를
    안 했으면 낡은 정보지만, *«완전히 다른 계보»* 는 그래도 잡힌다 —
    그게 09-22 에 필요했던 전부다.
    """
    out: Dict[str, Any] = {"리모트": [], "남의저장소": [], "뒤처짐": []}
    gd = os.path.join(root, ".git")
    if not os.path.isdir(gd):
        return {"없음": True}
    import shutil as _sh
    git = _sh.which("git")
    if not git:
        return {"없음": True}

    lk = os.path.join(gd, "index.lock")
    if os.path.exists(lk):
        out["락"] = "index.lock"
        try:
            age = time.time() - os.path.getmtime(lk)
            out["락나이"] = ("%.0f일 전" % (age / 86400) if age > 86400
                           else "%.0f분 전" % (age / 60))
        except Exception:
            pass

    def _g(*a) -> str:
        """⛔ **`--no-optional-locks` 가 여기 있어야 한다** — 09-22.

        `git status` 는 읽기처럼 보이지만 **인덱스를 갱신하려고
        `.git/index.lock` 을 잡는다.** 샌드박스(마운트)에서는
        **만들기는 되고 지우기가 `Operation not permitted`** 라
        락이 그대로 남고 **사람 쪽 커밋이 통째로 막힌다.**

        09-16 에 그렇게 생긴 락이 **엿새** 있었고, 그 결과가 결함 322·323
        이다. **이 검사가 그 사고를 재발시키면 안 된다.**
        """
        try:
            r = subprocess.run(
                [git, "--no-optional-locks", "-C", root] + list(a),
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30)
            return (r.stdout or "").strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    ts = _g("log", "-1", "--format=%ct")
    if ts.isdigit():
        out["경과일"] = int((time.time() - int(ts)) / 86400)
        out["마지막"] = _g("log", "-1", "--format=%h %s")[:58]

    st = _g("status", "--porcelain")
    out["미커밋"] = len([l for l in st.split("\n") if l.strip()])

    for r in [x for x in _g("remote").split("\n") if x.strip()]:
        out["리모트"].append(r)
        for br in ("main", "master"):
            ref = "%s/%s" % (r, br)
            if not _g("rev-parse", "--verify", "--quiet", ref):
                continue
            if not _g("merge-base", ref, "HEAD"):
                # **공통 조상이 없다** = 같은 프로젝트가 아니다
                out["남의저장소"].append((r, "`%s` 와 공통 조상이 없다" % ref))
            else:
                n = _g("rev-list", "--count", "%s..HEAD" % ref)
                if n.isdigit() and int(n) > 0:
                    out["뒤처짐"].append((r, int(n)))
            break
    return out


def unwired(root: str = ROOT) -> List[str]:
    """

    **아무도 안 부르는 모듈**을 센다 (렌즈 3 · 결함 44).

    `bioreroute/` 안의 모듈을 훑어, 자기 자신과 시험을 뺀 곳에서
    한 번도 언급되지 않으면 도달 불가 후보로 본다.

    **완벽하지 않다** — 동적 import 는 못 잡는다. 그래도 결함 44 는 잡았을 것이다.
    """
    pkg = os.path.join(root, "bioreroute")
    mods = {}
    for dirpath, _dn, files in os.walk(pkg):
        if "tests" in dirpath or "__pycache__" in dirpath:
            continue
        for f in files:
            if f.endswith(".py"):
                name = f[:-3]
                if name not in WIRED_EXEMPT:
                    mods[name] = os.path.join(dirpath, f)
    bodies = {}
    for dirpath, _dn, files in os.walk(pkg):
        if "__pycache__" in dirpath:
            continue
        for f in files:
            if f.endswith(".py"):
                p = os.path.join(dirpath, f)
                try:
                    bodies[p] = open(p, encoding="utf-8").read()
                except Exception:
                    pass
    for p in ("app.py",):
        q = os.path.join(root, p)
        if os.path.exists(q):
            bodies[q] = open(q, encoding="utf-8").read()

    dead = []
    for name, own in mods.items():
        src = bodies.get(own, "")
        # **CLI 진입점은 호출부가 없는 게 정상이다.** `py -m bioreroute.bench.X`
        # 로 돌리는 도구라 아무도 import 하지 않는다. 이걸 도달 불가로 세면
        # 목록이 10개가 되고, **오탐 많은 가드는 꺼진다**(결함 40).
        if '__name__ == "__main__"' in src or "__name__=='__main__'" in src:
            continue
        hit = 0
        for p, t in bodies.items():
            if p == own or os.sep + "tests" + os.sep in p:
                continue
            if re.search(r"\b%s\b" % re.escape(name), _code_only(t)):
                hit += 1
        if hit == 0:
            dead.append(os.path.relpath(own, root))
    return sorted(dead)


def untested_runners(root: str = ROOT) -> List[str]:
    """**판정 파일을 쓰는데 시험이 한 번도 안 태운 실행기** — 결함 243.

    ## 왜 이 검사가 따로 필요한가

    `unwired()` 는 `__name__ == "__main__"` 이 있는 모듈을 **통째로
    건너뛴다.** 이유가 있었다 — CLI 도구는 아무도 import 안 하는 게
    정상이고, 그걸 도달 불가로 세면 목록이 10개가 되어 **오탐 많은
    가드는 꺼진다**(결함 40).

    **그 면제가 08-18에 다섯을 가렸다.** `modelswap`·`parcheck`·
    `demorun`·`demopick`·`gencheck` 이 그날의 판정 산출물
    (`모델교체결과.json`·`병렬결과.json`·`시연실행결과.json`·
    `시연질환결과.json`·`발굴안정성.json`)을 만들었는데 **시험이
    하나도 안 태웠다.** `시험.ps1` 은 `test_phase1`·`test_phase2` 만 돈다.

    ## 규칙을 안 풀고 **다른 축으로 센다**

    면제를 없애면 오탐이 돌아온다. 대신 **«판정 파일을 쓰는가»** 로
    좁힌다 — `safeio.save_json` 호출 여부는 **기계가 판별 가능**하고,
    그걸 부르는 모듈은 **수치를 저장소에 남긴다.** 남기는 것은 봐야 한다.

    > CLI 라서 면제하는 것과 **판정을 쓰는데 면제하는 것**은 다르다.
    """
    import glob as _g
    out = []
    tdir = os.path.join(root, "bioreroute", "tests")
    tests = ""
    for t in _g.glob(os.path.join(tdir, "*.py")):
        tests += open(t, encoding="utf-8", errors="replace").read()
    tests = _code_only(tests)
    for p in _g.glob(os.path.join(root, "bioreroute", "**", "*.py"),
                     recursive=True):
        rel = os.path.relpath(p, root).replace("\\", "/")
        if "/tests/" in rel:
            continue
        src = open(p, encoding="utf-8", errors="replace").read()
        if "safeio.save_json" not in _code_only(src):
            continue
        name = os.path.splitext(os.path.basename(p))[0]
        if not re.search(r"\b%s\b" % re.escape(name), tests):
            out.append(rel)
    return sorted(out)


def _code_only(src: str) -> str:
    """주석·독스트링을 지운 소스. **문자열로 배선을 재면 주석에 속는다.**

    08-13 실증(결함 192) — `io/structure.py` 에 넣은 주석 한 줄

        #  예측 구조 대신 실험 구조로 간다(`bench/dockcheck.apo_scan`).

    때문에 `dockcheck` 이 «배선됨» 으로 셌다. **아무도 안 부르는데.**

    `ast` 로 지운다. 파싱이 안 되면 **원문을 그대로 돌려준다** —
    못 지운 것과 지운 것을 헷갈리느니 오탐 쪽이 낫다.
    """
    import ast
    try:
        tree = ast.parse(src)
    except Exception:
        return src
    drop = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                drop.add(d)
    out = []
    for line in src.splitlines():
        s = line.split("#", 1)[0] if "#" in line else line
        out.append(s)
    body = "\n".join(out)
    for d in drop:
        body = body.replace(d, "")
    return body


def recent(root: str = ROOT, days: int = 2) -> List[str]:
    """최근 바뀐 코드 (렌즈 7 · 결함 58).

    **결함 58 은 그날 쓴 코드에서 나왔다.** 새 코드는 검토를 덜 받은
    코드이므로 따로 세워 놓고 적대적으로 다시 읽어야 한다.
    """
    cut = time.time() - days * 86400
    out = []
    for dirpath, _dn, files in os.walk(os.path.join(root, "bioreroute")):
        if "__pycache__" in dirpath:
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dirpath, f)
            try:
                m = os.path.getmtime(p)
                if m >= cut:
                    out.append((m, os.path.relpath(p, root)))
            except Exception:
                pass
    # **최신순.** mtime 은 약한 신호다 — 한 글자만 고쳐도 갱신되고,
    # 압축·복사로도 바뀐다. 그래도 "새 코드가 덜 검토됐다"는 사실은 남는다.
    return [p for _m, p in sorted(out, reverse=True)]


def uncovered(root: str = ROOT) -> List[str]:
    """감사가 **안 보는 산출물** (렌즈 8 · 결함 60).

    `docaudit` 이 `.md` 만 보던 동안 발표자료가 08-05 에 멈춰 있었다.
    산출물 하나하나에 대해 "이걸 보는 감사가 있나"를 묻는다.
    ## 08-12 — **이 함수가 구조적으로 항상 빈 목록을 냈다** (결함 135)

    `DELIVERABLES` 넷이 **전부 skip 경로로 걸러졌다** —
    `.pdf` 는 확장자 skip, `bioreroute-v*.zip` 은 정규식 skip, 나머지
    둘(`app.py`·`발표.pptx`)은 `docaudit.EXTRA` 에 있어 `seen`.

    즉 **어떤 입력에도 `[]` 를 냈고 화면은 늘 «OK 없음» 이었다.**
    「가드가 안 보는 곳을 찾는 가드」 자체가 아무것도 안 봤다.

    그래서 셋을 바꿨다 —
      · **저장소 루트의 `.md` 전부**를 대상에 넣는다(감사는 15개만 본다)
      · **`배포업로드/`** 를 본다 — **실제 제출물의 소스**인데 대상이 아니었다
      · 대상이 **전부 걸러지면 그 자체를 보고**한다. 조용히 통과하지 않는다

    ## 08-12 두 번째 — **고쳤더니 33개가 나왔고, 그게 또 문제였다** (결함 136)

    첫 수정 뒤 이 검사는 **매 실행 33개를 ⚠ 로 냈고 `--strict` 는 영영
    통과할 수 없게 됐다.** 늘 우는 가드는 눈 감은 가드와 **같은 값**이다 —
    사람이 곧 무시한다(결함 126에서 이미 겪었다. 경보를 7일 동안 아무도
    안 봤다).

    그래서 33개를 **셋으로 갈랐다.**

      · **살아 있는 문서** → `docaudit.DOCS` 로 옮긴다. 진짜로 감사를 받는다
      · **기록**(`docaudit.LOG`) → 옛 숫자가 남는 게 정상. 대조하면 훼손이다
      · **봉인**(`docaudit.sealed_docs()`) → 감사가 아니라 **해시**가 본다

    남는 것만 ⚠ 다. 실측으로 셋이 걸렸다 — `CLAUDE.md`·`계획_8월.md`·
    **`발표_처음과끝.md`(소리 내어 읽을 대본)** 에 `결함 39건` 이
    박혀 있었다.
    """
    import glob
    from . import docaudit
    seen = ({d for d in docaudit.DOCS} | {d for d, _ in docaudit.EXTRA}
            | set(docaudit.LOG) | set(docaudit.sealed_docs(root)))
    out, n_seen, n_skip = [], 0, 0
    pats = list(DELIVERABLES) + ["*.md", "배포업로드/app.py"]
    for pat in pats:
        for p in glob.glob(os.path.join(root, pat)):
            rel = os.path.relpath(p, root).replace("\\", "/")
            if rel in seen:
                n_seen += 1
                continue
            if rel.endswith(".pdf"):
                n_skip += 1
                continue          # md 에서 생성된다. md 가 맞으면 따라온다
            if re.match(r"bioreroute-v\d+\.zip$", rel):
                n_skip += 1
                continue          # 코드 묶음. 회귀 시험이 본다
            out.append(rel)
    if not out and not n_seen:
        # **대상이 하나도 안 남았다** — 필터가 전부 먹은 것이다.
        #   이건 «깨끗하다» 가 아니라 «검사가 죽었다» 이다.
        return ["⚠ 검사 대상이 0개다 — 필터가 전부 걸렀다(skip %d). "
                "이 검사가 죽어 있다는 뜻이다" % n_skip]
    return sorted(set(out))


def seal_state(root: str = ROOT) -> dict:
    """봉인 문서의 **해시가 지금도 맞는가** — 결함 136.

    `evidence.seals()` 가 08-05부터 있었는데 **`preflight` 이 한 번도
    안 불렀다.** 화면(탭③)만 봤다. 즉 «봉인이 살아 있다」는 주장은
    **사람이 화면을 열어 볼 때만** 확인됐다.

    `watch_holdout.py` 는 CSV·JSON 만 지킨다 — `사전명세*.md` 는
    **어느 자동 검사에도 안 걸려 있었다.**
    """
    try:
        from .. import evidence
        s = evidence.seals(root)
    except Exception as e:                       # 못 읽으면 통과로 두지 않는다
        return {"오류": "%s: %s" % (type(e).__name__, e), "깨짐": [],
                "확인불가": [], "무결": 0, "전체": 0}
    return {
        "오류": None,
        "무결": sum(1 for x in s if x["무결"] is True),
        "깨짐": [x["대상"] for x in s if x["무결"] is False],
        "확인불가": [x["대상"] for x in s if x["무결"] is None],
        "전체": len(s),
    }


CHECKS = [
    ("회귀 시험 (phase1)", ["-m", "bioreroute.tests.test_phase1"]),
    ("회귀 시험 (phase2)", ["-m", "bioreroute.tests.test_phase2"]),
    ("문서 간 일관성", ["-m", "bioreroute.bench.docaudit"]),
    ("정답표 감사", ["-m", "bioreroute.bench.labelaudit"]),
    ("동결·봉인 무결성", ["watch_holdout.py"]),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="장을 넘길 때 돌리는 전수 검증 (결함 43~60 의 교훈)")
    ap.add_argument("--strict", action="store_true",
                    help="수동 렌즈에 답을 적기 전에는 통과시키지 않는다")
    ap.add_argument("--days", type=int, default=2, help="'최근 코드' 기준 일수")
    a = ap.parse_args(argv)

    bad = 0
    print("=" * 68)
    print("전수 검증 — 자동 %d항목 + 수동 %d렌즈" % (len(CHECKS) + 3, len(MANUAL)))
    print("=" * 68)

    # 회귀 시험 **전체 수**(통과+실패)를 모아 `docaudit` 에 넘긴다 —
    # 09-18 에 «통과 수» 에서 바꿨다. 이유는 아래 `n = …` 의 주석. 문서가 주장하는
    # 시험 건수가 **정본과 같은지** 보게 하려면 실제 수가 필요하다.
    #
    # ⚠ **손으로 `--tests` 를 치지 마라** — 결함 307. 08-24 저녁에 내가
    #   문서에 적힌 수를 그대로 `--tests` 로 넘겨 «불일치 없음» 을 받았다.
    #   **정답을 넣고 채점한 것**이고, 그 사이 승우 컴퓨터는 계속 빨갰다.
    #   이제 여기서 **시험을 실제로 돌린 직후** 파일로 남기고, `docaudit`
    #   은 그 파일을 읽는다. 사람이 끼어들 자리를 없앤다.
    passed, phases = 0, {}
    for name, cmd in CHECKS:
        rc, out = _run(cmd)
        if name.startswith("회귀 시험"):
            # ⚠ **`re.search` 를 쓰면 안 된다** — 결함 308.
            #   시험 [54]가 `_gist` 를 시험하려고 화면에 넣는 **모의 문자열**
            #   (`통과 1954 · 실패 1`)이 출력 **앞쪽**에 있다. 앞에서부터
            #   찾으면 **내 시험의 소품이 정본이 된다.** 실제로 그렇게 돼서
            #   화면은 «2031» 인데 `시험정본.json` 에는 **1954** 가 박혔다.
            #   요약줄은 **줄머리**에서 시작하고 검사 상세는 들여쓴다 —
            #   그 차이로 가른다. 그리고 **맨 끝 것**을 쓴다.
            hits = re.findall(r"^통과 (\d+) · 실패 (\d+)", out, re.M)
            if hits:
                # ── ⛔ 09-18 · **정본은 «통과 수» 가 아니라 «전체 수» 다** ──
                #
                #   앞판은 `int(hits[-1][0])` — **통과만** 셌다. 그래서
                #   **시험 하나가 실패하면 정본이 1 내려갔다.**
                #
                #   그 결과가 09-16~18 에 **세 번 반복된 «한 칸씩
                #   쫓아다니기»** 다 —
                #
                #     ① 실패가 있는 채로 `preflight` → 정본이 낮게 박힌다
                #     ② 그 수로 `countsync` → 문서가 낮은 수를 든다
                #     ③ 실패를 고치고 다시 `preflight` → 정본이 +1
                #     ④ 문서와 또 어긋난다 → ②로
                #
                #   **문서가 말하는 것은 «시험이 N개 있다» 이지
                #   «N개가 통과했다» 가 아니다.** `연구기술보고서.md` 도
                #   *"회귀 시험 N건"* 이라 적는다 — 개수다.
                #
                #   전체 수로 바꾸면 **실패 여부와 무관해진다.** 실패는
                #   `preflight` 이 따로 크게 찍으므로 숨겨지지 않는다.
                #
                #   ⚠ **실패가 0이면 앞판과 같은 값**이다. 지금까지 대부분
                #     0이었으므로 과거 기록과 어긋나지 않는다.
                n = int(hits[-1][0]) + int(hits[-1][1])
                passed += n
                phases["phase2" if "phase2" in name else "phase1"] = n
            else:
                # **못 읽었으면 0으로 세지 않는다.** 정본을 안 쓴다
                phases["못읽음"] = name
            if "phase1" in phases and "phase2" in phases:
                try:
                    from . import docaudit as _da
                    _w = _da.write_truth(ROOT, phases["phase1"],
                                         phases["phase2"])
                    # ⚠ **썼다고 가정하지 않는다** — 결함 310.
                    #   `safeio` 는 백업이 막히면 **원본을 안 덮고**
                    #   `.new` 에 쓴다. 조용히 넘어가면 정본이 **옛 수를
                    #   든 채** 남고 화면은 초록이다.
                    if _w.get("원본유지"):
                        print("  ⚠ **시험 정본이 갱신되지 않았다** — %s "
                              "(백업: %s). 옛 수가 그대로 있다"
                              % (os.path.basename(_w.get("경로", "?")),
                                 _w.get("상태")))
                except Exception as e:                 # 못 써도 검사는 계속한다
                    print("  ⚠ 시험 정본을 못 남겼다 — %s: %s"
                          % (type(e).__name__, e))
            elif "못읽음" in phases:
                print("  ⚠ **%s 의 요약줄을 못 읽었다** — 정본을 안 쓴다. "
                      "0으로 세는 것보다 안 쓰는 것이 낫다" % phases["못읽음"])
        # ⚠ **구분선을 요약으로 내지 마라** — `_gist` 의 주석을 읽어라.
        #   전에는 `[-1:]` 로 마지막 줄을 뽑아 `=====` 만 찍혔다.
        gist = _gist(out)
        # watch_holdout 은 개봉 이후 경보가 정상이다 — rc 로 판정하지 않는다
        ok = (rc == 0) or name.startswith("동결")
        bad += (not ok)
        print("  %s %-18s %s" % ("OK  " if ok else "FAIL", name, gist))
        # ── ⛔ 09-21 · **실패가 여럿이면 여럿을 찍는다** ─────────────
        #
        #   `_gist` 는 한 줄 요약이라 `fails[0]` 하나만 붙인다. 그래서
        #   09-21 에 *"통과 2292 · 실패 9"* 인데 **화면에 하나만 보였고**,
        #   나머지 여덟을 알 수 없어 샌드박스에서 따로 재현해야 했다.
        #   `CLAUDE.md` 가 *"실패는 `preflight` 이 따로 크게 찍으므로
        #   숨겨지지 않는다"* 고 적었는데 **그 말이 참이 아니었다.**
        #
        #   ⚠ 위 ③ 주석이 같은 병을 이미 한 번 고쳤다 — *«불일치 N항목만
        #   찍는 것은 답이 아니다»*. **같은 자리에서 두 번째다.**
        #   이번엔 요약을 늘리는 대신 **목록을 따로 낸다** — 한 줄에
        #   우겨넣으면 또 잘린다.
        if not ok:
            _f = _fails(out)
            if len(_f) > 1:
                print("       ↓ **실패 %d건 전부** — 하나만 보고 고치면 다음 판에 또 걸린다"
                      % len(_f))
                for _x in _f:
                    print("         · %s" % _x[:150])
            elif not _f and re.search(r"실패\s*[1-9]", out or ""):
                # **조용히 안 찍지 않는다** — 목록을 못 읽은 것과
                #   실패가 하나인 것은 다르다(결함 99 계열).
                print("       ⚠ 실패 목록을 **못 읽었다** — 찍는 쪽이 "
                      "`%s` 로 한 줄씩 내야 한다(계약: 시험 [168])" % FAIL_LINE)
        if name.startswith("동결"):
            print("       ↑ 개봉 이후 경보는 **정상이다**. 해시가 깨졌는지만 본다")

    # ── 렌즈 1·2 — **가장 중요한 둘이 가장 늦게 자동화됐다** ──────
    #
    #   아홉 렌즈 중 1·2(제안서 항목 대조)만 그동안 줄곧 🟡 "사람이 md 를
    #   눈으로 읽는다" 였다. 그런데 결함 43·47·63 이 전부 거기서 났다 —
    #   **표에는 적혀 있고 코드가 다른 것**, 셋 다 오래 안 드러났다.
    #
    #   `specaudit` 은 **존재만** 본다. 의미는 렌즈 4가 봐야 한다.
    #   절반이라고 적어 두는 것이 정직한 위치다(결함 67).
    print("\n[렌즈 1·2] 제안서 대조표가 가리키는 코드가 실재하나 — 결함 43·67")
    from . import specaudit as _sa
    try:
        sp = _sa.audit(ROOT)
        c = sp["집계"]
        print("     ✅ %d · 🟡 %d · ❌ %d  (표 %d행)"
              % (c["✅"], c["🟡"], c["❌"], sp["행"]))
        if sp["깨짐"]:
            bad += 1
            for b in sp["깨짐"]:
                print("  ⚠ `%s` — %s (%s)" % (b["심볼"], b["왜"], b["문서"]))
        else:
            print("  OK   인용 심볼 %d개 전부 실재" % len(sp["검사"]))
        print("     ⓘ **존재만 본다.** §2.5 가 `활성부위` 인데 코드가 전체")
        print("       평균이어도 통과한다 — 결함 63 을 이 검사는 못 잡는다")
    except Exception as e:
        bad += 1
        print("  ⚠ specaudit 실패: %s: %s" % (type(e).__name__, e))

    # ── 가짜로 시험한 것을 진짜와 대조한다 ──────────────────────
    #
    #   `배포.md` 가 그동안 줄곧 `화면이 어떻게 보이는가 — ❌ 못 봤다` 였고
    #   가짜 gradio 로 배선만 봤다. 가짜는 **우리가 쓴 것**이라
    #   `gr.Radio(없는인자=1)` 을 줘도 통과한다.
    #
    #   실행은 여전히 못 한다. **API 대조만** 한다 — 죽을 이유 하나를 줄인다.
    print("\n[가짜 검증 대조] app.py ↔ 실제 gradio 소스")
    from . import gradiocheck as _gc
    try:
        gr_r = _gc.audit(ROOT)
        if not gr_r["있다"]:
            print("     gradio 소스 없음 — **확인한 것이 없다. 통과가 아니다**")
        elif gr_r["없는이름"] or gr_r["없는인자"]:
            bad += 1
            for n, why in gr_r["없는이름"]:
                print("  ⚠ gr.%s — %s" % (n, why))
            for n, k, f in gr_r["없는인자"]:
                print("  ⚠ gr.%s(%s=…) — %s 에 없다. **띄우면 TypeError**" % (n, k, f))
        else:
            print("  OK   이름 %d개 · 인자 불일치 0 — 가짜가 이 층에선 안 속였다"
                  % gr_r["확인"])
            print("     ⓘ **화면은 여전히 안 띄웠다.** 이건 대체가 아니다")
    except Exception as e:
        bad += 1
        print("  ⚠ gradiocheck 실패: %s: %s" % (type(e).__name__, e))

    # ── ⛔ 09-22 · **git 을 아무도 안 보고 있었다** (결함 322·323) ─────
    print("\n[git] 저장소 상태 — **09-22 에 여기서 둘이 터졌다**")
    _g = git_health()
    if _g.get("없음"):
        print("  ⓘ git 저장소가 아니다 — 건너뛴다")
    else:
        # 🔴 **실패로 센다** — 둘 다 «알았으면 안 커졌을 것» 이다
        if _g.get("락"):
            bad += 1
            print("  FAIL **`.git/index.lock` 이 남아 있다** (%s · %s)"
                  % (_g["락"], _g.get("락나이", "?")))
            print("       → 커밋이 **통째로 막힌다.** 09-16 에 엿새 동안 이랬고")
            print("          그래서 캐시 33MB 를 잃었을 때 복구할 것이 없었다")
            print("       → `Get-Process git` 로 확인하고 없으면 지워라")
        for _r, _why in _g.get("남의저장소", []):
            bad += 1
            print("  FAIL 🔴 리모트 **`%s` 가 다른 프로젝트를 가리킨다** — %s"
                  % (_r, _why))
            print("       → `--force` 로 밀면 **그쪽이 통째로 사라진다.**")
            print("          09-22 에 실제로 그럴 뻔했고 막은 것은 git 이었다")
        # ⚠ 아래는 **경고**다 — 판단이 필요하고 오탐이 쌓이면 가드가 꺼진다
        if _g.get("미커밋", 0) > 40:
            print("  ⚠    미커밋 **%d개** — 한 번 잃으면 그만큼 날아간다"
                  % _g["미커밋"])
        if _g.get("경과일") is not None and _g["경과일"] >= 3:
            print("  ⚠    마지막 커밋이 **%d일 전**(%s)"
                  % (_g["경과일"], _g.get("마지막", "?")))
        for _r, _n in _g.get("뒤처짐", []):
            print("  ⚠    리모트 `%s` 가 **%d커밋 뒤처졌다**" % (_r, _n))
        # ⛔ 09-22 · **«0개» 를 초록으로 찍었다** — 결함 99 계열
        #
        #   이 검사를 만든 그날, 리모트를 정리하다 0개가 됐는데 화면이
        #   *«OK 락 없음 · 리모트 0개 전부 같은 계보»* 라고 찍었다.
        #   **없는 것을 통과로 읽은 것**이고, 하필 **제출물이 «GitHub
        #   코드»** 라 push 할 곳이 없다는 뜻이었다.
        #
        #   > 가드를 만든 그 실행에서 가드가 울지 않았다.
        if not _g.get("리모트"):
            bad += 1
            print("  FAIL 🔴 **리모트가 하나도 없다** — push 할 곳이 없다")
            print("       → 제출물이 «GitHub 코드」다. `git remote -v` 로 확인해라")
        elif not _g.get("락") and not _g.get("남의저장소"):
            print("  OK   락 없음 · 리모트 %d개(%s) 전부 같은 계보"
                  % (len(_g["리모트"]), ", ".join(_g["리모트"])))

    # ── ⛔ 09-25 · **제출 모델을 아무도 안 보고 있었다** ─────────────
    print("\n[제출 모델] 이 창의 파이썬이 보는 모델 — 화면·시연·예시가 이것으로 돈다")
    _m = submit_model()
    if _m["맞다"]:
        print("  OK   %s (본선 모델)" % _m["모델"])
    else:
        bad += 1
        print("  FAIL 🔴 **%s** — 본선 모델은 %s" % (_m["모델"], _m["본선"]))
        print("       → `.env` 의 BIOREROUTE_MODEL 을 되돌려라(승우 손).")
        print("          실험 스크립트는 환경변수로 모델을 박으므로 이것과 상관없다")

    print("\n[렌즈 3] 아무도 안 부르는 모듈 — 결함 44")
    dead = unwired()
    if dead:
        bad += 1
        for d in dead:
            print("  ⚠ %s  ← 도달 불가. 🟡 이 아니라 ❌ 다" % d)
    else:
        print("  OK   없음")

    print("\n[렌즈 8] 감사가 안 보는 산출물 — 결함 60·135·136")
    from . import docaudit as _da
    _sd = _da.sealed_docs()
    print("     감사 %d · 기록 %d(대조하면 훼손) · 봉인 %d(해시가 본다)"
          % (len(_da.DOCS) + len(_da.EXTRA), len(_da.LOG), len(_sd)))
    unc = uncovered()
    if unc:
        bad += 1
        for u in unc:
            print("  ⚠ %s  ← 이걸 보는 감사가 없다" % u)
    else:
        print("  OK   없음")

    # ── 봉인 해시 — **08-12까지 어떤 자동 검사도 안 봤다** (결함 136) ──
    ss = seal_state()
    if ss["오류"]:
        bad += 1
        print("  ⚠ 봉인 확인 실패: %s" % ss["오류"])
    elif ss["깨짐"]:
        bad += 1
        print("  ⚠ **봉인이 깨졌다**: %s" % ", ".join(ss["깨짐"]))
    else:
        print("  OK   봉인 %d개 해시 일치%s"
              % (ss["무결"],
                 (" · 확인불가 %d" % len(ss["확인불가"]))
                 if ss["확인불가"] else ""))

    print("\n[렌즈 7] 최근 %d일 안에 바뀐 코드 — **적대적으로 다시 읽어라**" % a.days)
    rec = recent(days=a.days)
    if rec:
        for r in rec[:8]:
            print("     %s" % r)
        if len(rec) > 8:
            print("     … 외 %d개 (최신순)" % (len(rec) - 8))
        print("  결함 58 은 **그날 쓴 코드**에서 나왔다 — 문서에 다섯 번 적은")
        print("  교훈을 같은 날 코드에서 재발시켰다. **인용은 방어가 아니다.**")
    else:
        print("     없음")

    print("\n" + "=" * 68)
    print("자동화가 **안 되는** 렌즈 — 사람이 답해야 한다")
    print("=" * 68)
    for i, (tag, q, why) in enumerate(MANUAL, 1):
        print("  %d. [%s] %s" % (i, tag, q))
        print("       %s" % why)

    # ── 렌즈 답변 파일의 최신성 (결함 64) ─────────────────────
    lens = lens_freshness(ROOT, days=a.days)
    print("\n  " + "─" * 64)
    print("  `렌즈답변.md` — **화면에 찍는 것으로는 안 막혔다**")
    if lens["error"]:
        print("  ⚠ %s" % lens["error"])
    else:
        print("     최신 장  %s" % lens["latest"])
        print("     항목     %d / %d 개 채워짐" % (lens["answered"], len(MANUAL)))
        if lens["stale"]:
            print("  ⚠ **답변이 최근 바뀐 코드보다 낡았다.**")
            print("     %s 보다 새로운 블록이 없다" % lens["newest_code"])
    if lens["stale"] or lens["error"]:
        print("     → 결함 64 가 이것이다. `검증절차.md` 가 *\"수동 5개는")
        print("       강제할 방법이 없다\"* 고 적었고 **그날 밤 실현됐다.**")

    print("\n" + "=" * 68)
    if bad:
        print("**자동 검사 %d항목 실패.** 장을 넘기지 마라." % bad)
        return 1
    print("자동 검사 전부 통과.")
    if a.strict:
        if lens["stale"] or lens["error"] or lens["answered"] < len(MANUAL):
            print("**--strict 실패: `렌즈답변.md` 가 낡았거나 항목이 빈다.**")
            print("장을 끝낼 때 맨 위에 새 블록을 추가해라 — "
                  "답이 \"안 했다\" 여도 적는다.")
            return 1
        print("**--strict 통과.** 다만 이 검사는 **최신성만 본다** — "
              "내용이 성실한지는 못 본다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
