# -*- coding: utf-8 -*-
"""**돌고 있는 동안 코드가 바뀌었나** — 결함 202.

    py -m bioreroute.bench.srcstamp          지금 상태를 찍는다
    py -m bioreroute.bench.srcstamp --json    기계가 읽는 형식

## 왜 필요한가

08-13 밤 실행(21:59)이 죽은 로그를 보고 **«끝났다» 고 판단**했는데,
승우가 **22:44 에 다시 돌렸다.** 나는 그걸 모르고 01:15~01:17 사이에
`test_phase2.py` 를 고쳤고, 그 시각 스크립트가 **시험 전수를 돌리는
중**이었다. 아침 로그에 실패가 하나 남았다 —
`[97] 손 안 댄 봉인은 무결로 읽는다`.

> ⚠ **08-14 정정 (결함 220).** 이 줄은 그 실패를 *«경쟁 상태가 만든 가짜
> 실패이고 지금 돌리면 통과한다»* 라고 단정했다. **그 진단이 틀렸을
> 가능성이 높다.** 그 시험은 기대 해시를 손으로 적어 놓고 파일은 텍스트
> 모드로 써서, **윈도우에서는 줄바꿈(`\n`→`\r\n`) 때문에 «항상» 실패**한다.
> 리눅스에서만 통과한다 — 즉 *"지금 돌리면 통과한다"* 는 **다른 환경에서
> 본 것**이었다.
>
> **경쟁 상태는 실재한다**(로그가 둘이었고 소스를 고친 것도 사실이다).
> 다만 **여기 인용된 증거가 그 원인이 아니었다.** 지금은 둘을 못 가른다.
> 원인을 하나로 단정한 것이 이 문서의 실수다.

> **로그 파일이 하나가 아니다.** «마지막 로그를 봤다» 는 «지금 안 돈다»
> 를 뜻하지 않는다.

## 안내문이 아니라 구조로

«고치기 전에 확인해라» 는 안내문이고, 이 프로젝트는 그게 안 듣는다는
것을 70번 배웠다. 그래서 **시험이 스스로 말하게** 한다 —

    시작할 때  `bioreroute/` 전체의 해시를 찍는다
    끝날 때    다시 찍어 **바뀐 파일을 나열**한다

바뀌었으면 결과 마지막 줄에 그 사실이 찍히므로, **아침에 그 실패가
진짜인지 경쟁 상태인지 즉시 갈린다.** 판정을 바꾸지는 않는다 —
**보이게 할 뿐이다.**
"""

import hashlib
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BEAT = os.path.join(ROOT, ".실행중.json")

# 감시 대상 — **소스와 시험.** 결과 파일·캐시는 도는 동안 바뀌는 게 정상이다
WATCH_DIRS = ("bioreroute",)
WATCH_EXT = (".py",)


def snapshot(root=None):
    """`bioreroute/` 전체 → `{상대경로: sha256[:16]}`."""
    r = root or ROOT
    out = {}
    for d in WATCH_DIRS:
        for dp, _dn, fs in os.walk(os.path.join(r, d)):
            if "__pycache__" in dp:
                continue
            for f in sorted(fs):
                if not f.endswith(WATCH_EXT):
                    continue
                p = os.path.join(dp, f)
                try:
                    h = hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
                except Exception:
                    h = "읽기실패"
                out[os.path.relpath(p, r).replace(os.sep, "/")] = h
    return out


def diff(a, b):
    """두 스냅샷 → `{바뀜, 생김, 사라짐}`."""
    ka, kb = set(a), set(b)
    return {"바뀜": sorted(k for k in ka & kb if a[k] != b[k]),
            "생김": sorted(kb - ka),
            "사라짐": sorted(ka - kb)}


def report(a, b, label="시험"):
    """바뀐 게 있으면 사람이 읽는 경고를, 없으면 빈 문자열을 돌려준다."""
    d = diff(a, b)
    n = sum(len(v) for v in d.values())
    if not n:
        return ""
    L = ["", "=" * 66,
         "⚠ **도는 동안 소스가 %d개 바뀌었다** (%s · 결함 202)" % (n, label),
         "   이 결과는 **한 판의 코드에서 나온 것이 아니다.**",
         "   실패가 있으면 «진짜인지 경쟁 상태인지» 부터 갈라라 —",
         "   지금 다시 돌려서 같은 실패가 나오는지 보면 된다.", ""]
    for k, v in d.items():
        if v:
            L.append("   %s %d개: %s" % (k, len(v), ", ".join(v[:6])))
    L += ["=" * 66, ""]
    return "\n".join(L)


# ── 심박 — **죽은 락과 도는 락을 가른다** ──────────────────────────
#
#   락 파일만 두면 스크립트가 죽었을 때 **영원히 «도는 중»** 이 된다.
#   그래서 시각을 계속 갱신하고, **오래되면 죽은 것**으로 읽는다.

def beat(stage="", log=""):
    """심박을 찍는다. 실패해도 조용히 넘어간다 — 이건 보조 장치다."""
    try:
        prev = {}
        if os.path.exists(BEAT):
            prev = json.load(open(BEAT, encoding="utf-8"))
        d = {"pid": os.getpid(), "시작": prev.get("시작") or time.time(),
             "마지막": time.time(), "단계": stage or prev.get("단계", ""),
             "로그": log or prev.get("로그", "")}
        json.dump(d, open(BEAT, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def state(stale_sec=600):
    """`{도는중, 마지막_초전, 단계, …}`. 심박이 없으면 `도는중=False`.

    **`stale_sec` 초 넘게 심박이 없으면 죽은 것으로 본다.** 기본 10분 —
    B2/B3 한 구성이 80분 걸리는데 그 사이 심박이 없으면 죽은 것이다
    (`밤새.ps1` 의 `Say` 가 단계마다 찍는다).
    """
    if not os.path.exists(BEAT):
        return {"도는중": False, "이유": "심박 파일 없음"}
    try:
        d = json.load(open(BEAT, encoding="utf-8"))
    except Exception as e:
        return {"도는중": False, "이유": "심박을 못 읽었다: %s" % e}
    age = time.time() - float(d.get("마지막") or 0)
    return {"도는중": age <= stale_sec, "마지막_초전": int(age),
            "단계": d.get("단계", ""), "pid": d.get("pid"),
            "로그": d.get("로그", ""),
            "이유": "" if age <= stale_sec else "심박이 %d초 전 — 죽은 것으로 본다" % age}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    st = state()
    snap = snapshot()
    if a.json:
        print(json.dumps({"실행": st, "파일수": len(snap)}, ensure_ascii=False, indent=1))
        return 0
    print("=" * 66)
    print(" 지금 무언가 돌고 있나 — **고치기 전에 본다** (결함 202)")
    print("=" * 66)
    if st["도는중"]:
        print("  ⛔ **돌고 있다.** 단계: %s · 심박 %d초 전 · pid %s"
              % (st["단계"] or "?", st["마지막_초전"], st["pid"]))
        print("     로그: %s" % (st["로그"] or "?"))
        print("\n  → `bioreroute/` 를 지금 고치면 **그 실행의 결과가 오염된다.**")
        return 1
    print("  ✅ 안 돈다 — %s" % (st.get("이유") or ""))
    print("  감시 대상 파일 %d개" % len(snap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
