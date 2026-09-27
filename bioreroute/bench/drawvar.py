# -*- coding: utf-8 -*-
"""추출 복제 — **모든 수치가 seed 42 한 번의 추출**이었다. seed 를 바꾸면 얼마나 움직이나.  (09-24)

명세: `사전명세_추출복제_0924.md` · 실행: `추출복제.ps1` · 시험 [181]·[182]

## 왜

발표·보고서의 수치(terra 헤드라인 AUROC · 기각 재현율 · ECE)와 네 모델 비교가
전부 **LLM 답을 한 번 뽑은 값**이다. 그 한 번이 seed 42 였다(상태 파일 provenance
전부 `seed42`). 재현성은 **같은 seed** 로만 쟀다(`재현성결과_0920.md` · 84쌍 72/84).
**다른 seed 는 한 번도 안 쟀다.** 그래서 두 가지를 모른다 —

1. 헤드라인이 seed 를 바꾸면 얼마나 움직이나
2. «모델을 바꿔도 안 움직인다(모델 독립성)» 가 참이려면 **모델을 바꾼 차이가 seed 를
   바꾼 차이보다 크지 않아야** 한다. 그 기준선(seed 폭)이 없다

## 무엇을 돌리나 — 같은 입력(스냅숏) 위에서 다섯

    terra_s42   terra · seed 42   — 옛 캐시로 돈 헤드라인(terra_1)과 **입력만** 다르다
    terra_s17   terra · seed 17   ┐ terra 의 seed 폭
    terra_s19   terra · seed 19   ┘
    sol_s17     sol   · seed 17   — 1차 sol(seed 42)과 짝
    luna_s17    luna  · seed 17   — 1차 luna(seed 42)와 짝

기존 셋과 합치면 — terra_1(옛 캐시 · s42) · sol_s42 · luna_s42.

## ⚠ 캐시 우회 대신 **LLM 답을 뺀 사본**

캐시 키에 seed 가 없다(`llm.py`). 스냅숏에는 sol·terra(gap1)·mini 의 옛 답이 있어서
그대로 쓰면 **옛 답을 재생**한다. 우회(`BYPASS_CACHE`)로 막으면 끊겼을 때 다시
시작하면서 **처음부터** 다시 묻는다(5시간). 그래서 **실행마다 LLM 답을 뺀 사본**을
준다 — 옛 답이 없으니 전부 새로 묻고, 새 답은 그 사본에 쌓여서 **끊겨도 이어서**
돈다(같은 seed 의 답이다). 실행 안에서 같은 질문이 두 번 나오면 두 번째는 첫 답을
쓴다 — **1차 실행과 같은 동작이다**(1차 캐시 적중 24건이 그것이다).

## 하위 명령

    strip     스냅숏 → LLM 답을 뺀 사본 (검색 키 · 지문은 그대로)
    analyze   입력 · seed · 모델 효과 분해 · 헤드라인 안정성 (LLM 0회)
"""

import argparse
import json
import os
import random
import sys

from . import modelpair as mp
from .seedretest import fp, sha, write_new, load_doc
from .stats import wilson

LLM_PREFIX = "LLM::"
BOOT_REPS = 4000
BOOT_SEED = 20260924
AUROC_TOL = 0.02          # R2 — seed 두 개의 공통 부분집합 AUROC 차가 이 안이면 «안정»
REJECT_TOL = 2.0          # R2 — 근거 기반 TN 기각률 차(%p)가 이 안이면 «안정»

TERRA = "openai/gpt-5.6-terra"
SOL = "openai/gpt-5.6-sol"
LUNA = "openai/gpt-5.6-luna"

# (이름, 모델, seed, 결과 파일, 상태 파일, 입력)
RUNS = [
    ("terra_1",   TERRA, "42", "홀드아웃_본선모델.json",       "상태_홀드본선_B5.json",       "옛캐시"),
    ("terra_s42", TERRA, "42", "홀드아웃_복제_terra_s42.json", "상태_복제_terra_s42_B5.json", "스냅숏"),
    ("terra_s17", TERRA, "17", "홀드아웃_복제_terra_s17.json", "상태_복제_terra_s17_B5.json", "스냅숏"),
    ("terra_s19", TERRA, "19", "홀드아웃_복제_terra_s19.json", "상태_복제_terra_s19_B5.json", "스냅숏"),
    ("sol_s42",   SOL,   "42", "홀드아웃_sol.json",            "상태_sol_B5.json",            "스냅숏"),
    ("sol_s17",   SOL,   "17", "홀드아웃_복제_sol_s17.json",   "상태_복제_sol_s17_B5.json",   "스냅숏"),
    ("luna_s42",  LUNA,  "42", "홀드아웃_luna.json",           "상태_luna_B5.json",           "스냅숏"),
    ("luna_s17",  LUNA,  "17", "홀드아웃_복제_luna_s17.json",  "상태_복제_luna_s17_B5.json",  "스냅숏"),
]
NEW = ("terra_s42", "terra_s17", "terra_s19", "sol_s17", "luna_s17")


# ── strip — LLM 답을 뺀 사본 ────────────────────────────────────────

def strip(snapshot, out, live="pubmed_cache.json"):
    """스냅숏에서 `LLM::` 키만 뺀 사본. **검색층은 한 글자도 안 바뀐다.**"""
    if os.path.normcase(os.path.abspath(out)) in {os.path.normcase(os.path.abspath(p))
                                                  for p in (snapshot, live)}:
        raise ValueError("사본 경로가 원본과 같다 — 원본을 건드리지 않는다")
    if os.path.exists(out):
        raise FileExistsError("%s 가 이미 있다 — 덮어쓰지 않는다" % out)
    s = load_doc(snapshot)
    kept = {k: v for k, v in s.items() if not k.startswith(LLM_PREFIX)}
    write_new(out, kept)
    f = mp.fingerprint(cache=out)
    return {"스냅숏": sha(snapshot), "뺀_LLM": len(s) - len(kept),
            "LLM": sum(1 for k in kept if k.startswith(LLM_PREFIX)),
            "검색키": f.get("검색키"), "검색키지문": f.get("검색키지문"), "사본": out}


# ── 짝 분류 ─────────────────────────────────────────────────────────

def pairs(runs):
    """(같은 seed · 입력만 다름) · (같은 모델 · 다른 seed) · (다른 모델) 로 가른다.

    옛 캐시 실행(terra_1)은 **같은 seed 짝**에만 쓴다 — 입력이 354쌍에서 달라
    seed·모델 효과 칸에 넣으면 입력 차이가 섞인다(결함 326).
    """
    snap = [r for r in runs if r[5] == "스냅숏"]
    same_seed, within, between = [], [], []
    for r in runs:
        if r[5] != "스냅숏":
            same_seed += [(r[0], s[0]) for s in snap if s[1] == r[1] and s[2] == r[2]]
    for i, a in enumerate(snap):
        for b in snap[i + 1:]:
            if a[1] == b[1]:
                within.append((a[0], b[0]))
            else:
                between.append((a[0], b[0]))
    return same_seed, within, between


# ── 불일치 ──────────────────────────────────────────────────────────

def same_input(x, y):
    return mp.f0(x) == mp.f0(y) and mp.inputs(x) == mp.inputs(y)


def disagree(a, b):
    """후보마다 — 입력이 같으면 판정(유망·조건부·보류·기각)이 다른가(0/1), 다르면 None."""
    mp.align(a, b)
    return [None if not same_input(x, y) else int(x.get("verdict") != y.get("verdict"))
            for x, y in zip(a, b)]


def reject_split(a, b):
    """TN · 입력 동일 · 둘 다 F0 갈래 아님 — 근거 기반 기각 (b = a 만, c = b 만)."""
    bb = cc = n = 0
    for x, y in zip(a, b):
        if x.get("label") != "TN" or not same_input(x, y):
            continue
        if mp.f0_branch(x) or mp.f0_branch(y):
            continue
        n += 1
        ra, rb = mp.rejected(x), mp.rejected(y)
        bb += ra and not rb
        cc += rb and not ra
    return {"n": n, "A만": bb, "B만": cc}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else None


def decompose(cands, within, between, reps=BOOT_REPS, seed=BOOT_SEED):
    """후보마다 W_i(같은 모델 다른 seed 불일치 평균) · B_i(다른 모델 불일치 평균).

    D = 평균(B_i − W_i) — **모델을 바꾼 효과가 seed 를 바꾼 효과보다 얼마나 큰가.**
    불확실성은 **후보를 다시 뽑는** 부트스트랩(짝지은 · 고정 seed)으로 낸다.
    ⚠ 실행 자체의 변동(모델마다 추출 1~3번)은 이 구간에 안 들어간다 — 명세 §11.
    """
    dw = [disagree(cands[a], cands[b]) for a, b in within]
    db = [disagree(cands[a], cands[b]) for a, b in between]
    n = len(next(iter(cands.values())))
    rows = []
    for i in range(n):
        w = _mean([d[i] for d in dw])
        bt = _mean([d[i] for d in db])
        if w is not None and bt is not None:
            rows.append((w, bt))
    if not rows:
        return None
    W = sum(r[0] for r in rows) / len(rows)
    B = sum(r[1] for r in rows) / len(rows)
    rng = random.Random(seed)
    ds, ws, bs = [], [], []
    m = len(rows)
    for _ in range(reps):
        smp = [rows[rng.randrange(m)] for _ in range(m)]
        sw = sum(r[0] for r in smp) / m
        sb = sum(r[1] for r in smp) / m
        ws.append(sw)
        bs.append(sb)
        ds.append(sb - sw)

    def ci(v):
        v = sorted(v)
        return [v[int(0.025 * len(v))], v[int(0.975 * len(v)) - 1]]

    return {"후보": m, "같은모델_다른seed": W, "다른모델": B, "D": B - W,
            "D_CI": ci(ds), "W_CI": ci(ws), "B_CI": ci(bs), "반복": reps, "seed": seed}


def r1_text(d, why=None):
    """R1 — 결과를 보기 전에 정한 말 (명세 §3)."""
    if d is None:
        return "계산 안 함 — %s" % (why or "입력이 같은 후보가 없다")
    lo, hi = d["D_CI"]
    if lo > 0:
        return ("모델을 바꾸면 seed 를 바꿀 때보다 판정이 **더** 흔들린다 (D = %+.1f%%p) — "
                "조작점은 모델에 달렸다" % (100 * d["D"]))
    if hi < 0:
        return ("seed 를 바꾸면 모델을 바꿀 때보다 판정이 **더** 흔들린다 (D = %+.1f%%p) — "
                "단일 추출 비교로는 모델 차이를 말할 수 없다" % (100 * d["D"]))
    return ("모델을 바꾸는 효과는 seed 를 바꾸는 효과와 **구별되지 않는다** (D = %+.1f%%p · "
            "구간이 0 을 포함) — 판정 수준의 모델 독립성과 맞다" % (100 * d["D"]))


# ── 유효성 ─────────────────────────────────────────────────────────

def validity(run, cands, res, cost=None):
    """새 실행이 **명세대로 돌았나**. 문제를 전부 돌려준다."""
    name, model, seed = run[0], run[1], run[2]
    bad = []
    served, off = mp.model_of(cands)
    if served != model:
        bad.append("답한 모델 %s ≠ %s" % (served, model))
    if off:
        bad.append("다른 모델이 답한 초록 %d" % off)
    tags = set()
    for c in cands:
        for it in c.get("factcheck") or []:
            p = it.get("provenance")
            if p:
                tags.add(p.get("temperature_used"))
    wrong = sorted(str(t) for t in tags if not str(t).startswith("default+seed%s(" % seed))
    if wrong:
        bad.append("seed 표시가 %s 가 아닌 답 %s" % (seed, wrong[:3]))
    if not tags:
        bad.append("답 기록(provenance)이 없다 — LLM 을 안 불렀다")
    if not (res and "B0" in res and "B5" in res):
        bad.append("결과에 B0·B5 가 다 없다")
    if cost is not None:
        run_info = cost.get("실행") or {}
        if run_info.get("캐시우회"):
            bad.append("캐시 우회가 켜져 있었다 — 명세는 «LLM 답을 뺀 사본 · 우회 없음»")
        if not (cost.get("합계") or {}).get("계량된_호출"):
            bad.append("계량된 호출 0 — 새로 묻지 않았다")
    return bad


# ── 실행별 수치 ─────────────────────────────────────────────────────

def evidence_rejects(cands):
    tn = [c for c in cands if c.get("label") == "TN"]
    k = sum(1 for c in tn if mp.rejected(c) and not mp.f0_branch(c))
    return k, len(tn)


def metrics(runs, root="."):
    """`indep.summarize` 를 그대로 쓴다 — 명세 0922 와 **같은 식**이다."""
    from . import indep
    models = [(r[0], r[3], r[4]) for r in runs]
    loaded = indep.load_runs(models, root=root)
    out, common, lab = indep.summarize(loaded)
    return {s["이름"]: s for s in out}, common, lab


def r2(ms, cands, a="terra_s17", b="terra_s19"):
    """R2 — 헤드라인 안정성: 공통 부분집합 AUROC 차 · 근거 기반 TN 기각률 차."""
    if a not in ms or b not in ms:
        return None
    da = ms[a]["공통B5"][0] - ms[b]["공통B5"][0]
    ka, n = evidence_rejects(cands[a])
    kb, _ = evidence_rejects(cands[b])
    dr = 100.0 * (ka - kb) / n
    return {"AUROC차": da, "AUROC안정": abs(da) <= AUROC_TOL,
            "기각률": [100.0 * ka / n, 100.0 * kb / n], "기각률차": dr,
            "기각안정": abs(dr) <= REJECT_TOL}


def agreement(a, b):
    d = disagree(a, b)
    same = [x for x in d if x is not None]
    k = sum(1 for x in same if x == 0)
    lo, hi = wilson(k, len(same)) if same else (None, None)
    return {"입력동일": len(same), "일치": k, "입력다름": sum(1 for x in d if x is None),
            "비율": (k / len(same)) if same else None, "CI": [lo, hi]}


def cache_effect(a, b):
    """입력이 **다른** 후보에서 판정이 얼마나 같았나 (옛 캐시 대 스냅숏 · 같은 seed)."""
    mp.align(a, b)
    idx = [i for i, (x, y) in enumerate(zip(a, b)) if not same_input(x, y)]
    k = sum(1 for i in idx if a[i].get("verdict") == b[i].get("verdict"))
    return {"입력다름": len(idx), "판정같음": k}


# ── 전체 ────────────────────────────────────────────────────────────

def analyze(runs=RUNS, root=".", targets=None):
    have = [r for r in runs if os.path.exists(os.path.join(root, r[3]))
            and os.path.exists(os.path.join(root, r[4]))]
    missing = [r[0] for r in runs if r not in have]
    cands = {r[0]: mp.load(os.path.join(root, r[4])) for r in have}
    res = {}
    cost = {}
    for r in have:
        res[r[0]] = load_doc(os.path.join(root, r[3])).get("results")
        cp = os.path.join(root, r[3].replace("홀드아웃_복제_", "비용_복제_"))
        cost[r[0]] = load_doc(cp) if (r[0] in NEW and os.path.exists(cp)) else None
    bad = {}
    for r in have:
        if r[0] in NEW:
            v = validity(r, cands[r[0]], res[r[0]], cost[r[0]])
            if cost[r[0]] is None:
                v.append("비용 파일이 없다")
            if v:
                bad[r[0]] = v
    ok = [r for r in have if r[0] not in bad]
    same_seed, within, between = pairs(ok)
    out = {"실행": [r[0] for r in ok], "없음": missing, "무효": bad}
    need = {"terra_s17", "terra_s19", "sol_s17", "luna_s17"}
    lack = sorted(need - {r[0] for r in ok})
    out["R1"] = decompose(cands, within, between) if not lack else None
    out["R1_말"] = r1_text(out["R1"], ("유효한 새 실행이 없다: %s (명세 §6)" % " · ".join(lack))
                           if lack else None)
    out["짝"] = {"같은seed": same_seed, "같은모델": within, "다른모델": between}
    out["짝별"] = {}
    for a, b in same_seed + within + between:
        g = agreement(cands[a], cands[b])
        g["근거기반기각"] = reject_split(cands[a], cands[b])
        out["짝별"]["%s~%s" % (a, b)] = g
    if within and between:
        out["R1b_TN기각"] = {
            "같은모델": _pool([out["짝별"]["%s~%s" % p]["근거기반기각"] for p in within]),
            "다른모델": _pool([out["짝별"]["%s~%s" % p]["근거기반기각"] for p in between])}
    ms, common, lab = metrics(ok, root=root) if len(ok) >= 2 else ({}, [], [])
    out["수치"] = {k: {"누출제외B5": v["B5"], "공통B5": v["공통B5"], "B0": v["B0"],
                     "B5전체": v["B5전체"], "ECE": v["ECE"], "재현율": v["재현율"],
                     "근거기반기각": evidence_rejects(cands[k]), "F0오류": v["F0오류"]}
                 for k, v in ms.items()}
    out["공통부분집합"] = len(common)
    out["R2"] = r2(ms, cands)
    out["R3"] = (agreement(cands["terra_1"], cands["terra_s42"])
                 if {"terra_1", "terra_s42"} <= set(cands) and "terra_s42" in {r[0] for r in ok}
                 else None)
    out["R4"] = (cache_effect(cands["terra_1"], cands["terra_s42"])
                 if out["R3"] is not None else None)
    if targets and {"sol_s17", "luna_s17"} <= {r[0] for r in ok}:
        t = load_doc(targets)["대상"]
        out["표적교차"] = {g: {"sol": sum(1 for x in t if x["1차기각"] == g
                                         and mp.rejected(cands["sol_s17"][x["idx"]])),
                               "luna": sum(1 for x in t if x["1차기각"] == g
                                          and mp.rejected(cands["luna_s17"][x["idx"]])),
                               "n": sum(1 for x in t if x["1차기각"] == g)}
                          for g in ("A", "B")}
    return out


def _pool(parts):
    n = sum(p["n"] for p in parts)
    d = sum(p["A만"] + p["B만"] for p in parts)
    lo, hi = wilson(d, n) if n else (None, None)
    return {"n": n, "불일치": d, "비율": (d / n) if n else None, "CI": [lo, hi]}


def report(o):
    print("=" * 80)
    print("추출 복제 — 입력 · seed · 모델 효과  (LLM 0회)")
    print("=" * 80)
    print("  실행 %s" % " · ".join(o["실행"]))
    if o["없음"]:
        print("  ⚠ 없음 %s" % " · ".join(o["없음"]))
    for k, v in o["무효"].items():
        print("  🔴 무효 %s — %s" % (k, " / ".join(v)))
    d = o["R1"]
    print("\n[R1 · 주] 판정 불일치 — 같은 모델 다른 seed 대 다른 모델 (입력 동일 후보)")
    if d:
        print("  같은 모델·다른 seed  %4.1f%% [%4.1f–%4.1f]" % tuple(100 * x for x in [d["같은모델_다른seed"]] + d["W_CI"]))
        print("  다른 모델            %4.1f%% [%4.1f–%4.1f]" % tuple(100 * x for x in [d["다른모델"]] + d["B_CI"]))
        print("  D = 다른 모델 − 다른 seed  %+.1f%%p [%+.1f, %+.1f]  (후보 %d · 부트스트랩 %d)"
              % (100 * d["D"], 100 * d["D_CI"][0], 100 * d["D_CI"][1], d["후보"], d["반복"]))
    print("  → %s" % o["R1_말"])
    if o.get("R1b_TN기각"):
        w, b = o["R1b_TN기각"]["같은모델"], o["R1b_TN기각"]["다른모델"]
        print("  [R1b] 근거 기반 TN 기각 불일치 — 같은 모델 %d/%d · 다른 모델 %d/%d"
              % (w["불일치"], w["n"], b["불일치"], b["n"]))
    print("\n[짝별] 판정 일치 (입력 동일)")
    for k, g in o["짝별"].items():
        rj = g["근거기반기각"]
        print("  %-24s %4d/%-4d = %5.1f%%   입력다름 %3d   TN기각 갈림 %d:%d"
              % (k, g["일치"], g["입력동일"], 100 * (g["비율"] or 0), g["입력다름"],
                 rj["A만"], rj["B만"]))
    print("\n[수치] 실행별 (공통 부분집합 %d)" % o["공통부분집합"])
    for k, v in o["수치"].items():
        a, lo, hi = v["공통B5"]
        ek, en = v["근거기반기각"]
        print("  %-10s 공통 B5 %.3f [%.3f–%.3f] · 누출제외 B5 %.3f · 전체 %.3f · ECE %.3f · 근거기반 %d/%d"
              % (k, a, lo, hi, v["누출제외B5"][0], v["B5전체"][0], v["ECE"], ek, en))
    r = o["R2"]
    if r:
        print("\n[R2] terra seed 폭 — 공통 AUROC 차 %+.3f (%s) · 근거기반 기각률 %.1f%% vs %.1f%% (차 %+.1f%%p · %s)"
              % (r["AUROC차"], "안정" if r["AUROC안정"] else "**폭 병기**",
                 r["기각률"][0], r["기각률"][1], r["기각률차"], "안정" if r["기각안정"] else "**폭 병기**"))
    if o["R3"]:
        g = o["R3"]
        print("[R3] 같은 seed(42) · 옛 캐시 대 스냅숏 — 입력 동일 %d 중 판정 같음 %d (%.1f%%)"
              % (g["입력동일"], g["일치"], 100 * (g["비율"] or 0)))
        c = o["R4"]
        print("[R4] 입력이 다른 %d 후보 — 판정 같음 %d" % (c["입력다름"], c["판정같음"]))
    if o.get("표적교차"):
        t = o["표적교차"]
        print("[표적 교차] 1차 sol 만 기각 %d쌍 → sol_s17 %d · luna_s17 %d  |  1차 luna 만 %d쌍 → sol_s17 %d · luna_s17 %d"
              % (t["A"]["n"], t["A"]["sol"], t["A"]["luna"], t["B"]["n"], t["B"]["sol"], t["B"]["luna"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="추출 복제 — 입력·seed·모델 효과")
    sp = ap.add_subparsers(dest="cmd")
    p = sp.add_parser("strip")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--out", required=True)
    p = sp.add_parser("analyze")
    p.add_argument("--json", default=None)
    p.add_argument("--targets", default="표적재시험_대상.json")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "strip":
            r = strip(a.snapshot, a.out)
            print(json.dumps(r, ensure_ascii=False))
            print("STRIP_OK 검색 키 %s개 · 지문 %s · LLM %s" % (r["검색키"], r["검색키지문"], r["LLM"]))
            return 0
        if a.cmd == "analyze":
            o = analyze(targets=a.targets if os.path.exists(a.targets) else None)
            report(o)
            if a.json:
                write_new(a.json, o)
                print("\n→ %s" % a.json)
            return 5 if o["무효"] else 0
    except (FileExistsError, FileNotFoundError, ValueError) as e:
        print("  🔴 %s" % e)
        return 2
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
