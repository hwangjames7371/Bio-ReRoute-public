# -*- coding: utf-8 -*-
"""데모가 보여줄 **증거**를 산출물에서 읽는다. 숫자를 코드에 적지 않는다.

이 프로젝트의 규칙 하나 —

> 보고하는 통계는 **코드에서 나와야 한다.** 손계산해서 문서에 옮겨 적지 마라.

화면도 같은 규칙을 받는다. `결함 38건`·`사전명세 4회` 를 `app.py` 에
타이핑하면 다음에 39건이 됐을 때 화면만 거짓말한다. **파일에서 센다.**

읽는 것 셋 —

| | 어디서 |
|---|---|
| 사전명세·봉인 | `사전명세*_봉인.json` · `봉인예측_*_봉인.json` |
| 결함 건수 | `Bio-ReRoute_발견정리.md` 의 결함 표 행수 |
| 판정 사례 | `demo_cases.json` (미리 구워 둔 실제 실행 결과) |

**없으면 없다고 돌려준다.** 배포지에 파일이 빠져도 화면이 죽으면 안 되고,
있는 척해서도 안 된다.
"""

import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = os.path.join(ROOT, "demo_cases.json")

_DEFECT_ROW = re.compile(r"^\|\s*(\d+)\s*\|")


def defect_count(path=None):
    """결함 표의 **행을 센다.** 문서에 적힌 '38건'을 읽지 않는다 —
    표와 문장이 어긋나면 표가 사실이다."""
    p = path or os.path.join(ROOT, "Bio-ReRoute_발견정리.md")
    try:
        s = open(p, encoding="utf-8").read()
    except Exception:
        return None
    i = s.find("| # | 결함 |")
    if i < 0:
        return None
    n = 0
    for line in s[i:].split("\n")[2:]:
        if not line.startswith("|"):
            break
        if _DEFECT_ROW.match(line):
            n += 1
    return n or None


def make_seal(doc, files, root=None, **extra):
    """봉인 json 을 만든다. **기록 직후 스스로 다시 읽어 대조한다.**

    ## 왜 함수로 만드나 — 결함 199

    그동안 봉인 json 을 **매번 손으로 짰다.** 08-13에 처음으로
    `실행_전_증거` 를 대조해 보니 **18개 중 9개가 안 맞았고, 그중 9건은
    파일이 봉인 시각보다 «오래됐는데도» 해시가 달랐다** — 즉 **기록
    자체가 틀렸다.** 대조를 안 했으므로 아무도 몰랐다.

    > **한 번도 대조 안 한 필드는 기록이 아니라 장식이다.**

    그래서 여기서 두 가지를 강제한다 —

      ① 파일 해시는 **바이너리로 읽어** md5 를 낸다 (한 곳에서만)
      ② 다 쓰고 나서 **다시 읽어 대조**하고, 안 맞으면 **예외를 던진다**
    """
    import hashlib, json as _j, datetime, os as _o
    r = root or ROOT
    dp = _o.path.join(r, doc)
    rec = {"문서": doc,
           "작성": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
           "sha256": hashlib.sha256(open(dp, "rb").read()).hexdigest(),
           "실행_전_증거": {}}
    for f in files:
        fp = _o.path.join(r, f)
        if not _o.path.exists(fp):
            rec["실행_전_증거"][f] = {"sha256": None, "최종수정": None,
                                  "비고": "봉인 시점에 없었다"}
            continue
        rec["실행_전_증거"][f] = {
            "sha256": hashlib.md5(open(fp, "rb").read()).hexdigest(),
            "최종수정": datetime.datetime.fromtimestamp(
                _o.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M:%S")}
    rec.update(extra)
    out = _o.path.join(r, doc.replace(".md", "_봉인.json"))
    with open(out, "w", encoding="utf-8") as fh:
        _j.dump(rec, fh, ensure_ascii=False, indent=1)

    # ── **자기 대조** — 안 하면 결함 199 가 그대로 재발한다 ──────────
    back = _j.load(open(out, encoding="utf-8"))
    if hashlib.sha256(open(dp, "rb").read()).hexdigest() != back["sha256"]:
        raise AssertionError("봉인 직후 문서 해시가 안 맞는다: %s" % doc)
    for f, v in back["실행_전_증거"].items():
        if v.get("sha256") is None:
            continue
        cur = hashlib.md5(open(_o.path.join(r, f), "rb").read()).hexdigest()
        if cur != v["sha256"]:
            raise AssertionError("봉인 직후 코드 해시가 안 맞는다: %s" % f)
    return out


def seals(root=None):
    """봉인 목록. 해시가 **지금도 맞는지** 대조해서 돌려준다."""
    import hashlib
    r = root or ROOT
    out = []
    for j in sorted(glob.glob(os.path.join(r, "*_봉인.json"))):
        try:
            d = json.load(open(j, encoding="utf-8"))
        except Exception:
            continue
        target = d.get("문서") or d.get("예측파일") or ""
        tp = os.path.join(r, target)
        ok = None
        if target and os.path.exists(tp):
            ok = (hashlib.sha256(open(tp, "rb").read()).hexdigest()
                  == d.get("sha256"))
        # ── 결함 190 — **문서만 잠그고 코드는 안 잠갔다** ──────────
        #
        #   봉인 json 은 `실행_전_증거` 에 실행 시점 코드 md5 를 적는데
        #   **아무도 대조하지 않았다.** 08-13 실측: `dockcheck.py` 가
        #   봉인 뒤 세 번 바뀌었는데 «무결» 이 그대로 떴다.
        #
        #   **`무결` 을 False 로 만들지 않는다** — 버그 수정은 정상이다.
        #   다만 **보이게** 한다. 안 보이면 «안 바꿨다» 가 주장으로만 남는다.
        changed = []
        for f, rec in (d.get("실행_전_증거") or {}).items():
            fp = os.path.join(r, f)
            if not os.path.exists(fp):
                changed.append(f + "(없음)")
                continue
            cur = hashlib.md5(open(fp, "rb").read()).hexdigest()
            if cur != rec.get("sha256"):
                changed.append(f)
        out.append({
            "대상": target or os.path.basename(j),
            "해시": (d.get("sha256") or "")[:12],
            "코드변경": changed,
            "시각": d.get("작성") or d.get("봉인시각") or "",
            "무결": ok,                      # None = 대상 파일이 없어 확인 불가
            "건수": d.get("건수"),
            "판정분포": d.get("판정분포"),
        })
    return out


def cases(path=None):
    """미리 구워 둔 판정 사례. **캐시에 의존하지 않는다.**

    배포지에서 캐시가 비어 있거나 키가 없어도 이 탭은 돌아야 한다.
    그래서 실행 결과를 파일로 굽는다(`build_cases`).
    """
    p = path or CASES
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return None
    return d if isinstance(d, dict) and d.get("사례") else None


def build_cases(out=None, cache_path="pubmed_cache.json"):
    """예시를 **실제로 돌려** 파일로 굽는다. 로컬에서 한 번만 하면 된다.

        py -c "from bioreroute import evidence; evidence.build_cases()"

    캐시가 데워져 있으면 LLM 호출이 0회로 끝난다.
    """
    from datetime import datetime

    from . import demo
    from .io import llm

    p = out or CASES
    made, total = [], 0
    for q, why in demo.PRESETS:
        before = llm.spent()
        r = demo.run_pair(q, cache_path=cache_path)
        total += llm.spent() - before
        r["설명"] = why
        made.append(r)
        print("  %-46s %s" % (q, demo.summary_line(r)))
    body = {"구운 시각": datetime.now().isoformat(timespec="seconds"),
            "새 LLM 호출": total, "사례": made}
    json.dump(body, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n저장: %s (사례 %d건 · 새 호출 %d회)" % (p, len(made), total))
    return body


# OTS 비트코인 attestation 태그(명세 고정값). **확정의 «있음» 증거다.**
#   캘린더 URL 의 «없음» 으로 판정하던 것이 결함 125였다.
_BITCOIN_ATTEST = bytes.fromhex("0588960d73d71901")


def notarization(root=None):
    """**제3자 타임스탬프가 실제로 붙었나.** 설명이 아니라 파일을 본다.

    결함 51이 이것이다 — 우리 봉인 증거가 **자체 Gitea 서버 시각**뿐이었다.
    자기가 통제하는 서버의 시각은 제3자 증명이 아니다.

    ## `.ots` 는 두 단계다 — **접수증과 증명은 다르다**

    OpenTimestamps 로 찍으면 먼저 **캘린더 서버 앞으로 된 미확정 증명**이
    내려온다. 비트코인 블록에 실제로 박히는 데 몇 시간 걸리고, 그 뒤
    같은 사이트에 `.ots` 를 다시 올려 **Upgrade** 해야 완성된다.

        접수 직후   584 바이트 · 블록 귀속 **없음**        ← 아직 증명 아님
        Upgrade 후  2409 바이트 · 블록 귀속 **있음**       ← 증명

    **이걸 안 보고 "등록 완료"라고 적으면 결함 70과 같은 실수다**
    (실행 0회인데 "로컬 확인 완료"라고 적어 둔 것).

    ## 캘린더 URL 이 남아 있는 것은 **정상이다** (결함 125)

    한 번 찍으면 캘린더 서버 3~4곳에 동시에 걸린다. Upgrade 는 **응답한
    곳만** 블록 귀속으로 채우고 나머지 URL 은 그대로 남는다. 08-12 실측:
    확정 뒤에도 `bob.btc…` · `catallaxy…` 둘이 남아 있다.

    그러므로 **«캘린더 URL 이 없으면 확정» 은 틀린 판정이다.** 초판이
    그렇게 돼 있어 확정된 증명서를 영원히 🟡 로 읽었다.
    **없는 것으로 판단하지 말고 있는 것을 찾는다.**
    """
    import hashlib
    r = root or ROOT
    doc = os.path.join(r, "봉인해시_공개등록.txt")
    ots = doc + ".ots"
    out = {"문서": os.path.exists(doc), "ots": os.path.exists(ots),
           "해시일치": None, "확정": None, "캘린더": []}
    if not (out["문서"] and out["ots"]):
        return out
    h = hashlib.sha256(open(doc, "rb").read()).digest()
    raw = open(ots, "rb").read()
    out["해시일치"] = h in raw            # 다른 파일의 증명서가 아닌가
    cal = re.findall(rb"https?://[a-zA-Z0-9.\-/]+", raw)
    out["캘린더"] = sorted({c.decode() for c in cal})
    # ── 결함 125 — **부재를 증거로 쓰고 있었다** ──────────────────
    #
    #   초판: `확정 = not 캘린더`. *"캘린더 URL 이 남아 있으면 미확정"* 이라는
    #   가정인데 **틀렸다.** 한 번 찍으면 캘린더 3~4곳에 동시에 걸리고,
    #   Upgrade 는 **응답한 곳만** 블록 귀속으로 바뀐다. 나머지는 URL 이
    #   그대로 남는다. 그래서 **확정돼도 영원히 «미확정»** 으로 읽혔다.
    #
    #   08-12 실측: 승우가 Upgrade 해서 `Success! Timestamp complete` 를
    #   받고 파일이 584 → 2409 바이트가 됐는데도 화면은 🟡 였다.
    #
    #   **없는 것을 근거로 삼지 말고 있는 것을 찾는다** — 비트코인 블록
    #   귀속 표식이 실제로 들어 있는가. OTS 명세의 attestation 태그다.
    out["비트코인"] = _BITCOIN_ATTEST in raw
    out["확정"] = out["비트코인"]
    out["미응답_캘린더"] = len(out["캘린더"])     # 남아 있어도 정상이다
    out["크기"] = len(raw)
    return out


def summary(root=None):
    """탭 3이 보여줄 것. **전부 파일에서 온다.**"""
    s = seals(root)
    return {
        "결함": defect_count(),
        "봉인": s,
        "봉인_무결": sum(1 for x in s if x["무결"] is True),
        "봉인_확인불가": sum(1 for x in s if x["무결"] is None),
        "봉인_깨짐": sum(1 for x in s if x["무결"] is False),
        "공개등록": notarization(root),
    }
