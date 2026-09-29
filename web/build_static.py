"""정적 스냅샷 — **서버 없이 도는 판**을 굽는다.

    py -m web.build_static          →  web/static/data/snapshot.json

## 왜 만드나 (08-21)

### ① 무료로 배포할 길이 이것뿐이다

`배포.md` 는 Hugging Face Spaces 를 전제로 썼는데, **2026-07-08 부터
Gradio·Docker Space 가 둘 다 유료(PRO)** 가 됐다. 무료 계정에 남은 것은
**Static Space** 다. 포럼 실측 — *"Static Spaces are free for everyone,
but hosting Gradio and Docker Spaces on free cpu-basic requires a PRO
subscription."* 무료 ZeroGPU 2개는 **계정마다 달라서** 기댈 수 없다
(*"some users are stuck at static space only"*).

### ② 심사위원이 보는 세 화면은 **이미 LLM 0회**다

판정 사례 · 3분할 대시보드 · 반증 기록은 전부 **구워 둔 파일**을 읽는다
(`demo_cases.json` · `calibration.json` · 봉인 파일들). 서버가 하는 일은
그걸 마크다운으로 조립해 내려보내는 것뿐이다. **그 결과를 미리 구우면
서버가 필요 없다.**

### ③ 시연 중에 죽을 서버가 없다

08-21 에 오래 열어 둔 탭의 렌더러가 죽어 요청이 서버에 닿지도 않았다.
시연에서 한 번 삐끗하면 심사 배점 30점이 걸린 화면이 날아간다.
**정적판은 서버가 죽어도 열리는 예비본**이기도 하다.

## 무엇을 못 하나 — **적어 둔다**

`약으로 시작`·`병으로 시작`(라이브 검증)은 **못 돈다.** LLM·PubMed 를
실제로 부르는 일이라 서버가 있어야 한다. 정적판은 그 자리에 «왜 안 되고
어떻게 돌리는가» 를 적는다 — **빈 화면이나 «오류» 로 두지 않는다.**

## 목록을 여기 다시 적지 않는다

경로 목록은 `server.get_json` **하나**에서 온다. 두 곳에 적으면 갈라진다
— 결함 82 가 배포 목록에서 정확히 그랬다(문서와 코드가 각자 목록을 들고
있었고, 한쪽만 고쳐졌다). 여기서는 **인자 조합만** 만든다.
"""
import hashlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
_WEB = os.path.join(ROOT, "web")
if _WEB not in sys.path:
    sys.path.insert(0, _WEB)

import server as S                                    # noqa: E402
from bioreroute import dash, demo, webui                # noqa: E402
from bioreroute.core import profiles                  # noqa: E402

OUT = os.path.join(_WEB, "static", "data", "snapshot.json")


def key(path, params=None):
    """경로+인자 → 열쇠.

    ⚠ **인자를 이름순으로 정렬한다.** 브라우저(`app.js`)도 같은 규칙을
      쓴다. dict 순서에 기대면 «파이썬이 만든 열쇠» 와 «자바스크립트가
      찾는 열쇠» 가 **조용히 어긋난다** — 화면은 빈칸이 되고 오류는 안
      난다. 이 프로젝트에서 가장 오래 사는 고장의 모양이다.
    """
    if not params:
        return path
    return path + "?" + "&".join(
        "%s=%s" % (k, params[k]) for k in sorted(params))


def _combos():
    """구울 (경로, 인자) 목록. **자료에서 세어서 만든다** — 손으로 안 적는다."""
    exits = list(profiles.EXITS.keys())
    out = [("/api/boot", None),
           ("/api/dash/bottom", None),
           ("/api/entry/help", None),
           ("/api/exit/help", None)]

    for label in webui._case_labels():
        out.append(("/api/case", {"label": label}))

    # ── **「이 약의 접근성」 칸도 굽는다** (08-24 · 결함 318) ──────────
    #
    #   승우: *«배포엔 이 약의 접근성 칸이 없는데 맞아?»* — **맞다.**
    #   08-24 에 그 칸을 «심사 기준 줄 오른쪽 팝오버» 로 옮기면서
    #   `liveLeft()` 가 `/api/live/left` 를 받아야 손잡이가 켜지게 했다.
    #   그런데 **그 경로를 스냅샷에 안 넣었다.** 정적본에서는 호출이
    #   실패하고 → `accShow(true)` 가 안 불리고 → **팝오버가 영영 안 뜬다.**
    #
    #   ⚠ **라이브가 안 되는 화면이라 없어도 된다고 볼 수 없다.**
    #     이 칸의 내용은 **결과가 아니라 «지금 심사 기준의 문턱»** 이다
    #     (유망 80 · 조건부 … · 후보를 찾는 방법). **묻기 전에 봐야 하는
    #     것**이고, 제안서 §2.2 가 «두 축과 독립» 이라고 적은 접근성 층이
    #     거기 붙는다. 그리고 **발표 장이 그 칸을 가리킨다** —
    #     «화면에 있습니다» 라고 말하는데 없으면 그 자리에서 무너진다.
    #   ⚠ 프리셋은 **`demo.PRESETS` 가 정본**이다(`dash` 가 아니다).
    #     화면의 예시 카드도 거기서 나오므로, 카드를 눌러도 칸이 뜬다.
    for q, _why in demo.PRESETS:
        for ex in exits:
            out.append(("/api/live/left", {"q": q, "exit": ex}))

    seen = set()
    for run in dash.RUNS:
        for ex in exits:
            out.append(("/api/dash/run", {"run": run, "exit": ex}))
            # 후보 목록은 실행마다 다르다 — **그 실행에서 꺼낸다**
            for q in (dash.candidates(run) or []):
                if (q, ex) in seen:
                    continue
                seen.add((q, ex))
                out.append(("/api/dash/card", {"q": q, "exit": ex}))
    return out


def build(path=OUT, quiet=False):
    snap, sizes = {}, []
    for p, params in _combos():
        data = S.get_json(p, {k: str(v) for k, v in (params or {}).items()})
        if data is None:                              # 경로가 사라졌다
            raise SystemExit("굽지 못한 경로: %s — `server.get_json` 확인" % p)
        k = key(p, params)
        snap[k] = data
        sizes.append((len(json.dumps(data, ensure_ascii=False)), k))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(body)

    if not quiet:
        sizes.sort(reverse=True)
        print("=" * 66)
        print("정적 스냅샷 — 서버 없이 도는 판")
        print("=" * 66)
        print("  경로 %d개 · %.2f MB" % (len(snap), len(body.encode()) / 1e6))
        print("  가장 큰 것 다섯 —")
        for n, k in sizes[:5]:
            print("    %7.1f KB  %s" % (n / 1024.0, k[:70]))
        print()
        print("  올릴 때는 이것만 있으면 된다 —")
        print("    index.html · app.css · app.js · data/snapshot.json")
        print("  **키도 파이썬도 필요 없다.**")
    return snap


# ── 올릴 폴더로 배치한다 ────────────────────────────────────────
#
#   저장소에서는 `index.html` 이 `web/static/` **안에** 있는데, 정적
#   호스팅에서는 **최상위**에 있어야 한다. 손으로 옮기면 언젠가 한 번은
#   틀린다 — 결함 83(옆 폴더에 사본을 두고 잊었다)이 그 모양이었다.
#
#       배포정적/
#         index.html
#         README.md                ← HF Space 머리말(`sdk: static`)
#         static/app.css
#         static/app.js
#         static/data/snapshot.json
#
#   `index.html` 이 `static/…` 을 **상대 경로**로 부르므로 두 배치가
#   같은 코드로 돈다.
_HF_README = """---
title: Bio-ReRoute
emoji: 🔬
colorFrom: gray
colorTo: blue
sdk: static
pinned: false
short_description: 반증 우선 약물 재창출 에이전트 — 판정이 아니라 감사 추적을 남긴다
---

# Bio-ReRoute — 정적 배포본

**서버 없이 도는 판입니다.** 심사·시연 세 화면({nav_cases} · {nav_dash} ·
{nav_evid})이 **그대로 동작합니다** — 그 셋은 원래 **LLM 호출
0회**로, 미리 구워 둔 결과를 읽는 화면이기 때문입니다.

**라이브 검증(약으로 시작 · 병으로 시작)은 안 됩니다.** 논문을 실제로
받아 읽고 모델을 부르는 일이라 서버가 필요합니다. 화면이 그 자리에
이유와 실행 방법을 적습니다 — **못 하는 것을 못 한다고 적습니다.**

## 실행 방법 — 예시 쿼리

{examples}
2. **판단 과정 보기 (이 주소)** — 「심사·시연 → {nav_dash}」 에서 실행 · 후보 칩 · 심사 기준
   (`표준` ↔ `신종감염병긴급`)을 바꿔 사고 과정 · 근거 카드 · 모델 단독 대조를 봅니다.
3. **라이브 (로컬)** — 공개 저장소(https://github.com/hwangjames7371/Bio-ReRoute-public)를 받아
   `.env` 에 키를 넣고 `python web/server.py` 로 띄웁니다.
   - 약으로 시작: `minocycline / Schizophrenia`
   - 병으로 시작: `COVID-19` (찾는 방법 `정방향` · `역발상`)
   - 안전 차단: `sarin / Alzheimer's disease` → 검색 · LLM 호출 전에 멈춥니다
4. **명령줄 (로컬)** — `python -m bioreroute.run --pair "metformin / Breast Cancer"`

> ⚠ **연구용 도구입니다. 의학적 조언이 아닙니다.**
> 이 화면의 문장은 대형언어모델이 생성한 것을 포함합니다.
"""


# 09-29 · 결함 378 — 요강의 «demo URL(실행 가능한 예시 쿼리 등 3가지 이상의 실행 방법 기술)» 을 Space README 가 안
#   채웠다(실행법 하나 · 예시 0). 예시의 판정은 **구운 사례에서 읽는다** — 손으로 적으면 다시 구울 때 낡는다
_EXAMPLES = ("hydroxychloroquine / COVID-19", "baricitinib / COVID-19", "rifampin / Tuberculosis")


def _nav(el):
    """사이드바 이름 — `app.js` 경로표(`el: "v-…", … nav: "…"`)가 정본이다(영상 생성기 `_nav` 와 같은 규칙).

    09-29 · 이 README 가 «지난 판정» 이라 적었는데 사이드바는 «판정 사례» 였다 — 손으로 적은 화면 이름이 갈렸다.
    못 찾으면 **멈춘다** — 틀린 이름으로 README 를 굽는 것보다 낫다.
    """
    import re as _re
    src = open(os.path.join(_WEB, "static", "app.js"), encoding="utf-8").read()
    m = _re.search(r'el:\s*"%s"[^}]*?nav:\s*"([^"]+)"' % _re.escape(el), src)
    if not m:
        raise ValueError("app.js 경로표에서 %s 의 사이드바 이름을 못 찾았다 — README 를 안 굽는다" % el)
    return m.group(1)


def hf_readme():
    """Space README — 예시 쿼리와 화면 이름을 **자료와 화면 코드에서** 채운다."""
    return (_HF_README.replace("{examples}", _examples())
            .replace("{nav_cases}", _nav("v-cases")).replace("{nav_dash}", _nav("v-dash"))
            .replace("{nav_evid}", _nav("v-evidence")))


def _examples():
    from bioreroute import evidence as _E
    by = {c.get("질의"): c for c in ((_E.cases() or {}).get("사례") or [])}
    rows = ["1. **설치 없이 (이 주소)** — 「심사·시연 → %s」 에서 칩을 누릅니다." % _nav("v-cases")]
    for q in _EXAMPLES:
        c = by.get(q) or {}
        rows.append("   - `%s` → %s" % (q, ("%s · 근거 %d건" % (c.get("판정"), len(c.get("근거") or [])))
                                        if c.get("판정") else "구운 사례에 없음"))
    return "\n".join(rows)


def stage(dest):
    """올릴 폴더를 **그 자리에 새로 만든다**. 매번 지우고 다시 만든다."""
    import shutil
    src = os.path.join(_WEB, "static")
    dest = os.path.abspath(dest)
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(os.path.join(dest, "static", "data"), exist_ok=True)

    # ── **캐시를 깨뜨린다** (08-24 · 승우: «사이드바 맨 위에 이상한 글자») ──
    #
    #   고친 판을 올렸는데 화면이 안 바뀌었다. 원인은 우리 코드가 아니라
    #   **CDN·브라우저 캐시**였다 — 실측으로 확인했다:
    #     저장소의 `app.css`      → `mark-ic` **있다** (최신)
    #     `*.static.hf.space` 응답 → `mark-ic` **없다** (옛 판)
    #
    #   그러면 **새 HTML + 옛 CSS** 가 물린다. 새 HTML 은 로고를
    #   `.collapse` 안으로 옮겼는데 옛 CSS 는 `.brand .mark` 만 알아서
    #   **규칙이 아무것도 안 걸리고 «BR» 이 맨 글자로 뜬다.** 그게
    #   승우가 본 것이다.
    #
    #   ⚠ **시연 당일에 이게 나면 끝이다.** 심사위원이 옛 화면을 보고
    #     우리는 그걸 알 방법이 없다. 그래서 **내용 해시를 파일 이름 뒤에
    #     붙인다** — 내용이 바뀌면 URL 이 바뀌고, URL 이 바뀌면 캐시가
    #     통째로 무효가 된다. 사람이 «새로고침 하세요» 를 부탁할 필요가 없다.
    html = io.open(os.path.join(src, "index.html"),
                   encoding="utf-8").read()
    for name in ("app.css", "app.js"):
        raw = io.open(os.path.join(src, name), "rb").read()
        ver = hashlib.sha256(raw).hexdigest()[:8]
        with io.open(os.path.join(dest, "static", name), "wb") as f:
            f.write(raw)
        # `static/app.css` → `static/app.css?v=1a2b3c4d`
        html = html.replace("static/%s\"" % name, "static/%s?v=%s\"" % (name, ver))
    with io.open(os.path.join(dest, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    build(os.path.join(dest, "static", "data", "snapshot.json"), quiet=True)
    with io.open(os.path.join(dest, "README.md"), "w", encoding="utf-8") as f:
        f.write(hf_readme())

    tot = sum(os.path.getsize(os.path.join(r, f))
              for r, _d, fs in os.walk(dest) for f in fs)
    print()
    print("  올릴 폴더를 만들었다 — **통째로 끌어다 놓으면 된다**")
    print("    %s" % dest)
    print("    파일 %d개 · %.2f MB"
          % (sum(len(fs) for _r, _d, fs in os.walk(dest)), tot / 1e6))
    print("  HF Spaces → New Space → **SDK: Static** (무료)")
    return dest


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="정적 스냅샷 — 서버 없이 도는 판")
    ap.add_argument("--stage", metavar="DIR",
                    help="올릴 폴더를 그 자리에 만든다 (끌어다 놓기용)")
    a = ap.parse_args(argv)
    build()
    if a.stage:
        stage(a.stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
