# -*- coding: utf-8 -*-
"""두 실행의 판정 차이를 **모델 탓**과 **입력 탓**으로 가른다 — 결함 326.

    py -m bioreroute.bench.modelpair 상태_terra.json 상태_luna.json
    py -m bioreroute.bench.modelpair A.json B.json --alpha 0.05 --psi 0.80 --json 결과.json
    py -m bioreroute.bench.modelpair --fingerprint

## 왜 있나

09-23 — `sol` 이 `terra` 보다 TN 을 24건 더 기각했다(McNemar p=0.0002).
«모델 차이» 로 적으려다 **두 실행의 입력이 다르다는 것**을 찾았다.

```
09-21  PubMed 캐시 33MB → 2바이트(결함 322) → 08-05 백업으로 복원
       terra 는 유실 «전» 캐시, sol 은 복원 «후» 캐시로 돌았다
```

검색(F0 · 팩트체커 · 회의주의자)은 **전부 캐시가 결정한다** — 질의가
`query.pair` 와 고정 틀(`SKEPTIC_QUERIES`)이라 모델이 안 끼어든다.
모델이 하는 일은 **읽은 초록에 방향·등급을 매기는 것**과 라우팅이다.
그러므로 **«모델만 바꾼 비교」는 입력이 같은 후보에서만 성립한다.**

## 「입력이 같다」 의 뜻 — 셋 다 같아야 한다

1. F0 결과
2. 읽은 PMID 집합(단계 표시와 무관한 합집합)
3. 그 PMID 마다의 **처지** — 초록을 받았나 · 못 받았나 · 초록이 없나 ·
   **라벨 출처라 제외됐나** · 철회됐나

   ⚠ 3 이 빠지면 거짓 «동일」 이 나온다. `mini` 와 `sol` 은 PMID 가 774쌍
   전부 같은데, `mini` 때는 라벨 출처 확장 조회 380건이 실패해(결함 37)
   **제외돼야 할 논문을 근거로 썼다.** 30쌍이 그 차이다(09-23 서브에이전트 검토).

## 무엇을 내나

- TN 기각 비교 셋 — 한쪽만 기각 b·c 와 McNemar 정확검정
    전체        TN 전부
    근거 기반    두 실행 다 **F0 갈래가 아닌** TN (F0 기각은 모델과 무관하다)
    입력 동일    위 1~3 이 같은 TN — **모델 효과를 가르는 칸**
- **F0 갈래** = F0 기각(KILL) **또는** 판정 사유가 `F0:` 로 시작
  (F0 실체 조회가 429 로 실패했는데 «환각」 으로 기각된 경우가 있다 — 결함 329)
- 무게 — 같은 방향으로 채택된 같은 초록에서 누가 더 큰 무게를 줬나
- 분류 — 같은 초록을 «무관」↔«근거」 로 다르게 읽은 수

**LLM 0회 · 네트워크 0회.** 상태 파일(`--save-state` 가 쓴 것) 둘만 읽는다.
"""

import argparse
import json
import sys
from collections import Counter

from .stats import mcnemar, mcnemar_power, wilson

REJECT = "기각"
EVIDENCE = ("support", "refute")


def load(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    cands = d.get("candidates") if isinstance(d, dict) else None
    if not isinstance(cands, list):
        raise ValueError("%s — 상태 파일이 아니다(`candidates` 없음)" % path)
    return cands


def f0(c):
    for t in c.get("trail") or []:
        if t.get("gate") == "f0":
            return t.get("outcome")
    return None


def f0_branch(c):
    """판정이 **F0 갈래**를 탔나 — 근거를 읽고 내린 판정이 아니다."""
    return f0(c) == "KILL" or str(c.get("reason") or "").startswith("F0")


def pmids(c):
    return frozenset(str(it.get("pmid")) for it in (c.get("factcheck") or [])
                     if it.get("pmid"))


def _status(it):
    """그 PMID 의 **처지** — 모델이 아니라 캐시·색인이 정한다."""
    s = str(it.get("skip") or "")
    if s.startswith("초록 취득 실패"):
        return "fail"              # 일시 장애는 캐시에 안 남는다(결함 37) — 다음엔 받을 수 있다
    if s.startswith("초록 없음"):
        return "noabs"
    if "라벨 출처" in s:
        return "excluded"          # 누출 차단 — [si] 확장 조회가 성공해야 걸린다
    if it.get("retracted") or s.startswith("철회"):
        return "retracted"
    return "ok"


def inputs(c):
    """입력 지문 — (PMID, 처지) 의 집합. PMID 만 같아서는 부족하다."""
    return frozenset((str(it.get("pmid")), _status(it))
                     for it in (c.get("factcheck") or []) if it.get("pmid"))


def rejected(c):
    return c.get("verdict") == REJECT


def model_of(cands):
    """실제로 **답한** 모델과, 요청과 다른 모델이 답한 초록 수.

    **파일 이름이 아니라 내용에서 읽는다.** 환경변수가 안 먹어 terra 가 또
    돌았다면 파일 이름은 `luna` 인데 안은 terra 다. 그리고 `llm.py` 는 429·
    형식 실패 때 **다른 모델로 넘길 수 있다** — 그래서 `served_by` 를 본다.
    """
    cnt, off = Counter(), 0
    for c in cands:
        for it in c.get("factcheck") or []:
            p = it.get("provenance") or {}
            m = p.get("served_by") or p.get("model")
            if m:
                cnt[m] += 1
            if p.get("served_by") and p.get("model") and p["served_by"] != p["model"]:
                off += 1
    return (cnt.most_common(1)[0][0] if cnt else None), off


def _key(c):
    return (c.get("drug"), c.get("disease"), c.get("label"))


def align(a, b):
    """두 실행이 **같은 쌍을 같은 순서로** 가졌는지 확인한다. 아니면 멈춘다."""
    if len(a) != len(b):
        raise ValueError("후보 수가 다르다: %d vs %d" % (len(a), len(b)))
    for i, (x, y) in enumerate(zip(a, b)):
        if _key(x) != _key(y):
            raise ValueError("%d번째 쌍이 다르다: %r vs %r" % (i, _key(x), _key(y)))


def _pair(idx, a, b, psi, alpha):
    ra = sum(1 for i in idx if rejected(a[i]))
    rb = sum(1 for i in idx if rejected(b[i]))
    only_a = sum(1 for i in idx if rejected(a[i]) and not rejected(b[i]))
    only_b = sum(1 for i in idx if rejected(b[i]) and not rejected(a[i]))
    nd = only_a + only_b
    # 효과 크기 — 갈린 쌍 중 B 쪽이 기각한 비율 ψ̂ (0.5 = 대칭). p 만으로 말하지 않는다
    lo, hi = wilson(only_b, nd) if nd else (None, None)
    return {"n": len(idx), "A기각": ra, "B기각": rb,
            "A만": only_a, "B만": only_b, "p": mcnemar(only_a, only_b),
            "검정력": mcnemar_power(nd, psi, alpha=alpha),
            "psi_hat": (only_b / nd) if nd else None, "psi_ci": [lo, hi]}


def _items(c):
    return {str(it.get("pmid")): it for it in (c.get("factcheck") or [])
            if it.get("pmid")}


def classify_agreement(a, b, idx=None):
    """같은 후보·같은 PMID 를 두 모델이 **어느 쪽으로** 읽었나."""
    tot = agree = n2e = e2n = flip = neu_a = neu_b = 0
    for i in (idx if idx is not None else range(len(a))):
        da, db = _items(a[i]), _items(b[i])
        for p in set(da) & set(db):
            u = (da[p].get("direction"), bool(da[p].get("kept")))
            v = (db[p].get("direction"), bool(db[p].get("kept")))
            tot += 1
            agree += (u == v)
            ue = u[0] in EVIDENCE and u[1]
            ve = v[0] in EVIDENCE and v[1]
            neu_a += not ue
            neu_b += not ve
            if not ue and ve:
                n2e += 1
            elif ue and not ve:
                e2n += 1
            elif ue and ve and u[0] != v[0]:
                flip += 1
    return {"공통초록": tot, "일치": agree, "무관→근거": n2e, "근거→무관": e2n,
            "지지↔반박": flip, "A무관": neu_a, "B무관": neu_b}


def weight_shift(a, b, idx=None):
    """같은 방향으로 **둘 다 채택한** 같은 초록에서 누가 더 큰 무게를 줬나.

    무게는 고정 공식(`factcheck.weight_for`)이 **모델이 매긴 등급**(규모·결정성·
    확신·확실성)으로 계산한다. 공식이 같으니 차이는 등급에서 온다.
    """
    hi = lo = eq = 0
    for i in (idx if idx is not None else range(len(a))):
        da, db = _items(a[i]), _items(b[i])
        for p in set(da) & set(db):
            x, y = da[p], db[p]
            if (x.get("direction") == y.get("direction") in EVIDENCE
                    and x.get("kept") and y.get("kept")):
                wx, wy = abs(x.get("weight") or 0), abs(y.get("weight") or 0)
                if wy > wx + 1e-9:
                    hi += 1
                elif wy < wx - 1e-9:
                    lo += 1
                else:
                    eq += 1
    return {"B가큼": hi, "B가작음": lo, "같음": eq}


def compare(a, b, psi=0.80, alpha=0.05):
    align(a, b)
    n = len(a)
    tn = [i for i in range(n) if a[i].get("label") == "TN"]
    tp = [i for i in range(n) if a[i].get("label") == "TP"]
    same_in = [i for i in range(n)
               if f0(a[i]) == f0(b[i]) and inputs(a[i]) == inputs(b[i])]
    same_set = set(same_in)
    only_status = [i for i in range(n) if f0(a[i]) == f0(b[i])
                   and pmids(a[i]) == pmids(b[i]) and inputs(a[i]) != inputs(b[i])]
    ev = [i for i in tn if not f0_branch(a[i]) and not f0_branch(b[i])]
    tn_same = [i for i in tn if i in same_set]
    ma, off_a = model_of(a)
    mb, off_b = model_of(b)

    def ev_rej(c):
        return rejected(c) and not f0_branch(c)

    return {
        "모델": [ma, mb], "대체응답": [off_a, off_b],
        "n": n, "TN": len(tn), "TP": len(tp),
        "입력동일": len(same_in), "입력동일_TN": len(tn_same),
        "F0다름": [(i, f0(a[i]), f0(b[i])) for i in range(n) if f0(a[i]) != f0(b[i])],
        "처지만다름": len(only_status),
        "TN_전체": _pair(tn, a, b, psi, alpha),
        "TN_근거기반": _pair(ev, a, b, psi, alpha),
        "TN_입력동일": _pair(tn_same, a, b, psi, alpha),
        "TP_전체": _pair(tp, a, b, psi, alpha),
        "근거기반기각": [sum(1 for i in tn if ev_rej(a[i])),
                      sum(1 for i in tn if ev_rej(b[i]))],
        "F0갈래_TN": [sum(1 for i in tn if f0_branch(a[i])),
                     sum(1 for i in tn if f0_branch(b[i]))],
        "분류": classify_agreement(a, b),
        "분류_입력동일": classify_agreement(a, b, same_in),
        "무게": weight_shift(a, b),
        "무게_입력동일": weight_shift(a, b, same_in),
        "psi": psi, "alpha": alpha,
    }


def _pct(k, n):
    lo, hi = wilson(k, n)
    return "%3d/%d = %4.1f%% [%.1f–%.1f]" % (k, n, 100.0 * k / n if n else 0,
                                             100 * lo, 100 * hi)


def report(r, name_a="A", name_b="B"):
    ma, mb = r["모델"]
    print("=" * 76)
    print("모델 쌍 비교 — 판정 차이를 **모델 탓 / 입력 탓** 으로 가른다  (LLM 0회)")
    print("=" * 76)
    print("  A = %s   (%s)" % (name_a, ma or "모델 표시 없음"))
    print("  B = %s   (%s)" % (name_b, mb or "모델 표시 없음"))
    if ma and mb and ma == mb:
        print("\n  🔴 **두 실행의 모델이 같다** — 환경변수가 안 먹었을 수 있다."
              " 이 비교는 모델 비교가 아니다.")
    if any(r["대체응답"]):
        print("  ⚠ 요청과 **다른 모델이 답한** 초록 — A %d · B %d (대체 사슬)"
              % tuple(r["대체응답"]))
    print("\n[입력 동일성]  F0 결과 · 읽은 PMID · PMID 마다의 처지(받음/실패/없음/제외/철회)")
    print("  %d / %d  (TN %d)   · F0 다름 %d · PMID 는 같고 처지만 다름 %d"
          % (r["입력동일"], r["n"], r["입력동일_TN"], len(r["F0다름"]), r["처지만다름"]))
    if r["입력동일"] < r["n"]:
        print("  ⚠ 입력이 다른 쌍이 있다 — 그 쌍의 판정 차이는 **모델 탓이라 못 한다**")
    print("\n[TN 기각]  b = A만 기각 · c = B만 기각 · McNemar 양측 정확검정")
    print("  %-12s %5s %6s %6s %5s %5s %9s %8s   %s"
          % ("", "n", "A기각", "B기각", "b", "c", "p", "검정력*", "ψ̂ = c/(b+c) [95%]"))
    for k, lab in (("TN_전체", "전체"), ("TN_근거기반", "근거 기반 쌍"),
                   ("TN_입력동일", "입력 동일")):
        x = r[k]
        ps = ("%.2f [%.2f–%.2f]" % (x["psi_hat"], x["psi_ci"][0], x["psi_ci"][1])
              if x["psi_hat"] is not None else "—")
        print("  %-12s %5d %6d %6d %5d %5d %9.4f %8.2f   %s"
              % (lab, x["n"], x["A기각"], x["B기각"], x["A만"], x["B만"],
                 x["p"], x["검정력"], ps))
    print("  * 관측 불일치 수에서, 미리 정한 ψ=%.2f · α=%.3f 일 때 (사후 관측효과 아님)"
          % (r["psi"], r["alpha"]))
    print("  «근거 기반 쌍» = 두 실행 다 F0 갈래(F0 기각 · 사유가 `F0:`)가 아닌 TN")
    print("\n[근거 기반 기각 재현율 — 모델별]  F0 갈래를 뺀 TN 기각 / TN 전체")
    print("  A  " + _pct(r["근거기반기각"][0], r["TN"]))
    print("  B  " + _pct(r["근거기반기각"][1], r["TN"]))
    print("  (F0 갈래 TN — A %d · B %d)" % tuple(r["F0갈래_TN"]))
    t = r["TP_전체"]
    print("\n[위음성]  TP 기각 — A %d · B %d  (A만 %d · B만 %d)"
          % (t["A기각"], t["B기각"], t["A만"], t["B만"]))
    for tag, ck, wk in (("전체", "분류", "무게"), ("입력 동일", "분류_입력동일", "무게_입력동일")):
        c, w = r[ck], r[wk]
        if not c["공통초록"]:
            continue
        print("\n[같은 초록을 어떻게 읽었나 · %s]  %d건" % (tag, c["공통초록"]))
        print("  방향 일치 %d (%.1f%%) · 무관→근거 %d · 근거→무관 %d · 지지↔반박 %d"
              % (c["일치"], 100.0 * c["일치"] / c["공통초록"], c["무관→근거"],
                 c["근거→무관"], c["지지↔반박"]))
        print("  같은 방향 채택에서 무게 — B 가 큼 %d · B 가 작음 %d · 같음 %d"
              % (w["B가큼"], w["B가작음"], w["같음"]))
    print("\n⚠ 이 도구는 **비교를 계산**할 뿐이다. 무엇이 사전 지정이고 무엇이")
    print("  탐색인지는 명세가 정한다 — 여기서 고르지 않는다.")


# ── 실행 조건 지문 — **모델만 바꿨다는 것을 실행 «전» 에 박아 둔다** ──
#
#   `modelpair` 는 실행 «뒤» 에 입력이 같았는지 본다. 실행 전에는
#   **판정 경로 코드**와 **검색 캐시 키 집합**의 지문을 명세에 적고,
#   끝난 뒤 다시 찍어 대조한다.
#
#   ⚠ **`LLM::` 키는 뺀다** — LLM 답도 같은 `pubmed_cache.json` 에 쌓인다.
#     새 모델을 돌리면 그건 **당연히** 는다. 빼지 않으면 «키가 늘었다» 가
#     아무 뜻도 없다(09-23 서브에이전트 검토가 잡았다).
#   캐시는 **파일 해시가 아니라 키 집합**으로 본다 — 저장할 때 디스크와
#   병합해 다시 쓰므로(결함 322 방어) 바이트는 바뀔 수 있다.
CODE_GLOBS = ("bioreroute/core/*.py", "bioreroute/io/*.py",
              "bioreroute/agents/*.py",          # 분류·라우팅 프롬프트가 여기 있다
              "bioreroute/bench/run.py", "bioreroute/bench/query.py",
              "bioreroute/config.py")
MODEL_KEY = "LLM::"


def fingerprint(root=".", cache="pubmed_cache.json"):
    import glob
    import hashlib
    import os
    files = sorted({p.replace("\\", "/") for g in CODE_GLOBS
                    for p in glob.glob(os.path.join(root, g))})
    h = hashlib.sha256()
    per = []
    for p in files:
        with open(p, "rb") as f:
            d = hashlib.sha256(f.read()).hexdigest()
        rel = os.path.relpath(p, root).replace("\\", "/")
        per.append((rel, d[:12]))
        h.update(("%s %s\n" % (rel, d)).encode("utf-8"))
    out = {"코드파일": len(per), "코드지문": h.hexdigest()[:12], "파일별": per}
    cp = os.path.join(root, cache)
    if os.path.exists(cp):
        with open(cp, encoding="utf-8") as f:
            allk = json.load(f).keys()
        keys = sorted(k for k in allk if not k.startswith(MODEL_KEY))
        out["검색키"] = len(keys)
        out["검색키지문"] = hashlib.sha256(
            "\n".join(keys).encode("utf-8")).hexdigest()[:12]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="두 실행의 판정 차이를 모델/입력으로 가른다")
    ap.add_argument("a", nargs="?", help="상태 파일 A (예: 상태_홀드본선_B5.json)")
    ap.add_argument("b", nargs="?", help="상태 파일 B (예: 상태_luna_B5.json)")
    ap.add_argument("--fingerprint", action="store_true",
                    help="판정 경로 코드와 검색 캐시 키 집합의 지문만 찍는다")
    ap.add_argument("--psi", type=float, default=0.80,
                    help="검정력 계산용 사전 효과크기 ψ = c/(b+c) (기본 0.80)")
    ap.add_argument("--alpha", type=float, default=0.05,
                    help="검정력 계산의 유의수준 (기본 0.05)")
    ap.add_argument("--json", default=None, help="결과를 JSON 으로도 쓴다")
    ap.add_argument("--force", action="store_true",
                    help="--json 파일이 이미 있어도 덮어쓴다")
    a = ap.parse_args(argv)
    if a.fingerprint:
        fp = fingerprint()
        print("코드 지문   %s  (판정 경로 %d개 파일)" % (fp["코드지문"], fp["코드파일"]))
        if "검색키" in fp:
            print("검색 키     %d개 · 지문 %s   (LLM 답 키는 뺐다)"
                  % (fp["검색키"], fp["검색키지문"]))
        else:
            print("검색 키     pubmed_cache.json 없음")
        return 0
    if not (a.a and a.b):
        ap.error("상태 파일 둘이 필요하다 (또는 --fingerprint)")
    # `CLAUDE.md §3-3` — 결과 파일을 확인 없이 덮어쓰지 마라
    if a.json and not a.force:
        import os
        if os.path.exists(a.json):
            print("  🔴 %s 가 이미 있다 — 덮어쓰려면 --force" % a.json)
            return 2
    try:
        r = compare(load(a.a), load(a.b), psi=a.psi, alpha=a.alpha)
    except ValueError as e:
        print("  🔴 %s" % e)
        return 2
    report(r, a.a, a.b)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        print("\n  → %s" % a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
