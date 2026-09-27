# -*- coding: utf-8 -*-
"""DRKG 다중홉 순위의 타당성 — `사전명세_그래프검색.md` 실행기

명세 sha256 `587c700e5ed1315ab82aa3270bf8bef6c46bd1462eb82146324ad3e9ff9cbb98`

## 무엇을 재는가

화합물–질환 간선 81,842개 중 **무작위 20%(seed 2026)를 가리고**, 나머지
그래프만으로 그 가린 쌍을 되찾는가를 본다. 링크 예측의 표준 평가다.

**가린 간선을 그래프에서 실제로 지운다.** 안 지우면 `multihop`/`enrich` 가
그 화합물을 `known` 으로 보고 후보에서 빼 버려 회수율이 0이 된다 —
그건 «누출을 막았다» 가 아니라 «정답을 지웠다» 이다.

## 방법 넷 — **셋을 겨루고 하나가 대조군이다**

| | | |
|---|---|---|
| `A` | 공유 유전자 개수 | 현행 `multihop` |
| `B` | 초기하 검정 p | 08-11에 실패한 수정 |
| `C` | 차수 보존 널 z | `enrich` |
| `D` | **화합물 차수만** | **대조군 — 질환을 아예 안 본다** |

**D 를 못 이기는 방법은 다중홉이 아니라 인기 투표다.** 결함 117이 정확히
그 상태였고, 그래서 D 가 이 실험의 핵심이다.

## 미리 아는 상한 — **39.9%**

가린 간선 16,368개 중 공유 유전자 2개 이상으로 **도달 가능한 것은 6,533개
(39.9%)** 뿐이다. 나머지는 어떤 방법을 써도 못 찾는다. 그래서 회수율을
**두 분모로 낸다** — 전체 대비, 그리고 도달 가능한 것 대비.
분모를 하나만 쓰면 결함 46(정답표 37%)과 같은 실수가 된다.

## 안 하는 것

`embed/` 의 TransE 벡터는 **DRKG 전체로 학습됐고 거기에 가린 간선이 들어
있다.** 쓰면 누출이다. 명세 §7.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from ..io import drkg

SEED = 2026
HOLD_FRAC = 0.20
MIN_SHARED = 2
MIN_DEGREE = 5          # 명세 §2-2 — **출력이 아니라 차수 분포에서 정했다**
K_MAIN = 20
K_WIDE = 100
METHODS = ("A", "B", "C", "D")
OUT_DEFAULT = "graph_eval.json"
HOLD_DEFAULT = "graph_holdout.json"


# ── 초기하 ──────────────────────────────────────────────────────────
def _lc(n: int, k: int) -> float:
    if k < 0 or k > n:
        return -math.inf
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1))


def _hyper_sf(k: int, N: int, K: int, n: int) -> float:
    """P(X >= k). 로그공간에서 더하고 **작아지면 끊는다.**"""
    hi = min(K, n)
    if k > hi:
        return 0.0
    base = _lc(N, n)
    top = -math.inf
    terms = []
    for i in range(k, hi + 1):
        lp = _lc(K, i) + _lc(N - K, n - i) - base
        if lp == -math.inf:
            continue
        terms.append(lp)
        if lp > top:
            top = lp
        elif top - lp > 40:      # e^-40 이하는 합에 영향이 없다
            break
    if not terms:
        return 0.0
    s = sum(math.exp(t - top) for t in terms)
    return min(1.0, math.exp(top) * s)


# ── 가리기 ──────────────────────────────────────────────────────────
def split(graph: Dict[str, Any], frac: float = HOLD_FRAC,
          seed: int = SEED) -> Tuple[List[Tuple[str, str]], Dict[str, Any]]:
    """간선 20%를 가리고 **그래프에서 실제로 지운 사본**을 돌려준다."""
    cd = graph["cd"]
    edges = sorted((c, d) for c, ds in cd.items() for d in ds)   # 정렬 = 재현성
    rng = random.Random(seed)
    hold = rng.sample(edges, int(len(edges) * frac))
    hs = set(hold)
    cd2: Dict[str, Set[str]] = defaultdict(set)
    for c, ds in cd.items():
        keep = {d for d in ds if (c, d) not in hs}
        if keep:
            cd2[c] = keep
    g2 = dict(graph)
    g2["cd"] = cd2
    return hold, g2


# ── 한 질환의 순위 넷 ────────────────────────────────────────────────
def rank_all(graph: Dict[str, Any], disease: str,
             min_shared: int = MIN_SHARED,
             min_degree: int = MIN_DEGREE) -> Dict[str, List[str]]:
    cg, gc, dg, cd = graph["cg"], graph["gc"], graph["gd"], graph["cd"]
    gcd = graph["gc"]
    total = sum(len(v) for v in gcd.values())
    dis_genes = [x for x in (graph["dg"].get(disease) or ()) if x in gcd]
    if not dis_genes:
        return {m: [] for m in METHODS}
    known = {c for c, ds in cd.items() if disease in ds}
    dset = set(dis_genes)
    K = len(dis_genes)
    N = len(gcd)

    # 후보 생성은 **질환 유전자 쪽에서** 훑는다. 화합물 전체를 도는 것보다
    # 훨씬 싸다 — 질환 유전자에 안 닿는 화합물은 애초에 후보가 아니다.
    ov: Counter = Counter()
    for g in dis_genes:
        for c in gcd[g]:
            ov[c] += 1

    w = [len(gcd[x]) / total for x in dis_genes]
    ev_cache: Dict[int, Tuple[float, float]] = {}

    def ev(n: int) -> Tuple[float, float]:
        got = ev_cache.get(n)
        if got is None:
            ps = [1.0 - (1.0 - x) ** n for x in w]
            e = sum(ps)
            v = sum(p * (1.0 - p) for p in ps)
            got = (e, v)
            ev_cache[n] = got
        return got

    rows = []
    for c, k in ov.items():
        if c in known or k < min_shared:
            continue
        n = len(cg[c])
        if n < min_degree:
            continue
        e, v = ev(n)
        z = (k - e) / math.sqrt(v) if v > 0 else 0.0
        rows.append((c, k, n, z))

    out: Dict[str, List[str]] = {}
    out["A"] = [c for c, k, n, z in sorted(rows, key=lambda r: (-r[1], r[0]))]
    out["C"] = [c for c, k, n, z in sorted(rows, key=lambda r: (-r[3], r[0]))]
    out["D"] = [c for c, k, n, z in sorted(rows, key=lambda r: (-r[2], r[0]))]
    hb = [(c, _hyper_sf(k, N, K, n)) for c, k, n, z in rows]
    out["B"] = [c for c, p in sorted(hb, key=lambda r: (r[1], r[0]))]
    return out


# ── Wilcoxon 부호순위 (짝비교) ──────────────────────────────────────
def wilcoxon(a: List[float], b: List[float]) -> Dict[str, Any]:
    d = [x - y for x, y in zip(a, b) if x != y]
    n = len(d)
    if n < 6:
        return {"n": n, "p": None, "note": "짝 %d개 — 검정 불가" % n}
    order = sorted(range(n), key=lambda i: abs(d[i]))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(d[order[j + 1]]) == abs(d[order[i]]):
            j += 1
        r = (i + j) / 2.0 + 1.0
        for t in range(i, j + 1):
            ranks[order[t]] = r
        i = j + 1
    wp = sum(ranks[i] for i in range(n) if d[i] > 0)
    wm = sum(ranks[i] for i in range(n) if d[i] < 0)
    w = min(wp, wm)
    mu = n * (n + 1) / 4.0
    sd = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0)
    z = (w - mu + 0.5) / sd if sd > 0 else 0.0
    p = math.erfc(abs(z) / math.sqrt(2))
    return {"n": n, "W+": wp, "W-": wm, "z": round(z, 3),
            "p": min(1.0, p), "우세": "앞" if wp > wm else "뒤"}


def holm(pairs: List[Tuple[str, Optional[float]]]) -> Dict[str, Any]:
    live = [(k, p) for k, p in pairs if p is not None]
    live.sort(key=lambda r: r[1])
    m = len(live)
    out, prev = {}, 0.0
    for i, (k, p) in enumerate(live):
        q = min(1.0, max(prev, p * (m - i)))
        # ⚠ `round(q, 6)` 을 쓰면 **1e-6 미만이 전부 0 이 된다** —
        #   실측 q=1.179e-15 가 `0.00e+00` 으로 찍혔다. 정확검정은
        #   0 을 내지 않는다. 표는 이미 `%.2e` 로 찍으므로 반올림이
        #   필요 없었다 (결함 153). `reversecheck.holm` 은 안 그런다
        #   — 독스트링이 «같은 구현» 이라 적었는데 같지 않았다.
        out[k] = q
        prev = q
    for k, p in pairs:
        if p is None:
            out[k] = None
    return out


# ── 실행 ────────────────────────────────────────────────────────────
def run(path: Optional[str] = None, out_p: str = OUT_DEFAULT,
        hold_p: str = HOLD_DEFAULT, limit: Optional[int] = None,
        resume: bool = True, budget: float = 120.0) -> Dict[str, Any]:
    t0 = time.time()
    g = drkg.load(path)
    if not g.get("ok"):
        return {"ok": False, "error": g.get("error")}
    hold, g2 = split(g)
    by_dis: Dict[str, Set[str]] = defaultdict(set)
    for c, d in hold:
        by_dis[d].add(c)

    reach = sum(1 for c, d in hold
                if len(g["cg"].get(c, set()) & g["dg"].get(d, set())) >= MIN_SHARED)
    if not os.path.exists(hold_p):
        json.dump({"seed": SEED, "frac": HOLD_FRAC, "n": len(hold),
                   "n_reachable_min_shared": reach,
                   "edges": [list(e) for e in hold]},
                  open(hold_p, "w", encoding="utf-8"), ensure_ascii=False)

    st: Dict[str, Any] = {"per": {}}
    if resume and os.path.exists(out_p):
        try:
            st = json.load(open(out_p, encoding="utf-8"))
            st.setdefault("per", {})
        except Exception:
            st = {"per": {}}

    todo = [d for d in sorted(by_dis) if d not in st["per"]]
    if limit:
        todo = todo[:limit]
    done = 0
    for d in todo:
        if time.time() - t0 > budget:
            break
        want = by_dis[d]
        rk = rank_all(g2, d)
        rec: Dict[str, Any] = {"n_hidden": len(want),
                               "n_cand": len(rk["A"]),
                               "n_hit_possible": 0}
        pos = {m: [] for m in METHODS}
        for m in METHODS:
            idx = {c: i for i, c in enumerate(rk[m])}
            pos[m] = [idx[c] for c in want if c in idx]
        rec["n_hit_possible"] = len(pos["A"])
        for m in METHODS:
            rec[m] = {
                "r20": sum(1 for i in pos[m] if i < K_MAIN),
                "r100": sum(1 for i in pos[m] if i < K_WIDE),
                "rr": (max((1.0 / (i + 1)) for i in pos[m]) if pos[m] else 0.0),
            }
        st["per"][d] = rec
        done += 1

    st["meta"] = {"spec": "사전명세_그래프검색.md",
                  "spec_sha256": "587c700e5ed1315ab82aa3270bf8bef6c46bd1462eb82146324ad3e9ff9cbb98",
                  "seed": SEED, "min_shared": MIN_SHARED,
                  "min_degree": MIN_DEGREE, "k": K_MAIN,
                  "n_hidden_edges": len(hold), "n_reachable": reach,
                  "n_disease_total": len(by_dis), "n_disease_done": len(st["per"])}
    json.dump(st, open(out_p, "w", encoding="utf-8"), ensure_ascii=False)
    return {"ok": True, "done_now": done, "total_done": len(st["per"]),
            "remain": len(by_dis) - len(st["per"]), "sec": round(time.time() - t0, 1)}


def report(out_p: str = OUT_DEFAULT) -> str:
    st = json.load(open(out_p, encoding="utf-8"))
    per, meta = st["per"], st["meta"]
    L = []
    L.append("# DRKG 다중홉 순위 — 사전명세 실행 결과")
    L.append("")
    L.append("> 명세 `%s` · sha256 `%s…`" % (meta["spec"], meta["spec_sha256"][:8]))
    L.append("> seed %d · min_shared %d · **min_degree %d** · k %d"
             % (meta["seed"], meta["min_shared"], meta["min_degree"], meta["k"]))
    L.append("")
    nh = sum(v["n_hidden"] for v in per.values())
    npo = sum(v["n_hit_possible"] for v in per.values())
    L.append("## 분모 셋 — **하나만 쓰면 결함 46이 된다**")
    L.append("")
    L.append("```")
    L.append("가린 간선 전체          %6d  (질환 %d개)" % (meta["n_hidden_edges"], meta["n_disease_total"]))
    L.append("공유유전자 %d개 이상 도달 %6d  = %.1f%%   ← **어떤 방법도 못 넘는 상한**"
             % (meta["min_shared"], meta["n_reachable"],
                100 * meta["n_reachable"] / meta["n_hidden_edges"]))
    L.append("채점한 것              %6d  (질환 %d개 · min_degree %d 적용 후 후보에 남은 것 %d)"
             % (nh, len(per), meta["min_degree"], npo))
    L.append("```")
    L.append("")
    L.append("## 주지표 — Recall@20")
    L.append("")
    L.append("| 방법 | | Recall@20 | Recall@100 | MRR |")
    L.append("|---|---|---|---|---|")
    names = {"A": "공유 개수 (현행)", "B": "초기하 p",
             "C": "차수 보존 z", "D": "**화합물 차수만 (대조군)**"}
    agg = {}
    for m in METHODS:
        r20 = sum(v[m]["r20"] for v in per.values())
        r100 = sum(v[m]["r100"] for v in per.values())
        mrr = [v[m]["rr"] for v in per.values()]
        agg[m] = (r20, r100, sum(mrr) / len(mrr) if mrr else 0.0)
        L.append("| `%s` | %s | **%.1f%%** (%d/%d) | %.1f%% | %.4f |"
                 % (m, names[m], 100 * r20 / npo if npo else 0, r20, npo,
                    100 * r100 / npo if npo else 0, agg[m][2]))
    L.append("")
    L.append("## 대조군 대비 — 질환별 짝비교 (Wilcoxon · Holm 보정)")
    L.append("")
    ks = sorted(per)
    dvec = [per[d]["D"]["rr"] for d in ks]
    tests = []
    for m in ("A", "B", "C"):
        mv = [per[d][m]["rr"] for d in ks]
        w = wilcoxon(mv, dvec)
        tests.append((m, w))
    q = holm([(m, w["p"]) for m, w in tests])
    L.append("| 방법 vs D | 짝 | z | p | q (Holm) | 판정 |")
    L.append("|---|---|---|---|---|---|")
    for m, w in tests:
        if w["p"] is None:
            L.append("| `%s` | %d | — | — | — | %s |" % (m, w["n"], w.get("note", "")))
            continue
        win = w["우세"] == "앞"
        ok = (q[m] is not None and q[m] < 0.05 and win)
        L.append("| `%s` | %d | %.2f | %.2e | %.2e | %s |"
                 % (m, w["n"], w["z"], w["p"], q[m],
                    "**대조군을 이겼다**" if ok else
                    ("대조군에 **졌다**" if (q[m] < 0.05 and not win) else "구별 안 됨")))
    L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    # 리디렉션돼도 안 깨지게 한다 (결함 131) — `report_io` 참조
    from .report_io import utf8_stdout
    utf8_stdout()
    ap = argparse.ArgumentParser(description="DRKG 순위 타당성 (사전명세 실행)")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--path")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--budget", type=float, default=120.0)
    ap.add_argument("--fresh", action="store_true", help="이어하지 않고 새로 시작")
    a = ap.parse_args(argv)
    if a.run:
        r = run(a.path, a.out, limit=a.limit, resume=not a.fresh, budget=a.budget)
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r.get("ok") else 1
    if a.report:
        print(report(a.out))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
