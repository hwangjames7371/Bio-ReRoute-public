# -*- coding: utf-8 -*-
"""Platt 보정 — `사전명세_보정.md` 실행기 (제안서 §4 「보정」)

명세 sha256 `bc42dc33e7cbb9749f3953324d522ab065b973270a579fe63a6bef43dae282d3`

## 제안서가 절차까지 정해 놨다

> §4: *"원점수는 **캘리브레이션 분할에서** 로지스틱 보정(Platt scaling)으로
> 확률화한다. 표본이 충분해지면 등위회귀로 대체하되, **소표본에서는
> 등위회귀가 과적합하기 쉬우므로 로지스틱 보정을 기본값으로 둔다.**
> 보정 품질은 신뢰도-적중률 도표와 보정오차(ECE)로 측정한다."*

적합은 층 A(84), 평가는 홀드아웃(774−4=770). **LLM 0회** — 점수가 이미 있다.

## 이 모듈이 스스로 조심하는 것

**Platt 은 단조변환이라 순위를 보존한다.** 그러므로 특이도·민감도는
**정확히 그대로여야 한다.** 바뀌면 개선이 아니라 **구현 버그**다.
`verify_monotone()` 이 그걸 검사하고, 어긋나면 결과를 내지 않는다.

**적합 집합과 평가 집합에 같은 쌍이 4개 있다.** 명세대로 뺀다.
빼는 것을 조용히 하지 않는다 — 뺀 이름을 결과에 적는다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

FIT_DEFAULT = "bench_results.json"
EVAL_DEFAULT = "bench_results_sealed.json"
N_BIN = 10                      # **사전 고정.** 돌린 뒤 고르면 유리한 값을 고른다
SPEC_SHA = "bc42dc33e7cbb9749f3953324d522ab065b973270a579fe63a6bef43dae282d3"


def _key(r: Dict[str, Any]) -> Tuple[str, str]:
    return ((r.get("drug") or "").strip().lower(),
            (r.get("indication") or "").strip().lower())


def load(path: str, config: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    d = json.load(open(path, encoding="utf-8"))
    res = (d.get("results") or {}).get(config)
    if not res or not res.get("scores"):
        return None
    rows = d.get("rows") or []
    sc = res["scores"]
    if len(sc) != len(rows):
        return None
    return {"keys": [_key(r) for r in rows],
            "y": [1 if (r.get("label") == "TP") else 0 for r in rows],
            "s": [float(x) for x in sc]}


# ── Platt (2모수 로지스틱) ────────────────────────────────────────────
def fit_platt(s: Sequence[float], y: Sequence[int],
              iters: int = 500) -> Tuple[float, float]:
    """뉴턴법. p = sigmoid(-(A*s + B)) 형태로 A·B 를 찾는다.

    Platt(1999) 의 목표값 완화를 쓴다 — 0/1 대신 (N+1)/(N+2), 1/(M+2).
    소표본에서 A 가 발산하는 것을 막는다.
    """
    n1 = sum(y)
    n0 = len(y) - n1
    hi = (n1 + 1.0) / (n1 + 2.0)
    lo = 1.0 / (n0 + 2.0)
    t = [hi if v else lo for v in y]
    A, B = 0.0, math.log((n0 + 1.0) / (n1 + 1.0))
    for _ in range(iters):
        g1 = g2 = h11 = h22 = h12 = 0.0
        for si, ti in zip(s, t):
            z = A * si + B
            p = 1.0 / (1.0 + math.exp(z)) if z > -700 else 1.0
            d = p - ti
            w = max(p * (1.0 - p), 1e-12)
            g1 += -si * d
            g2 += -d
            h11 += si * si * w
            h22 += w
            h12 += si * w
        det = h11 * h22 - h12 * h12
        if abs(det) < 1e-14:
            break
        dA = (h22 * g1 - h12 * g2) / det
        dB = (h11 * g2 - h12 * g1) / det
        A -= dA
        B -= dB
        if abs(dA) < 1e-10 and abs(dB) < 1e-10:
            break
    return (A, B)


def apply_platt(s: Sequence[float], A: float, B: float) -> List[float]:
    out = []
    for si in s:
        z = A * si + B
        out.append(1.0 / (1.0 + math.exp(z)) if -700 < z < 700 else (0.0 if z > 0 else 1.0))
    return out


# ── 지표 ─────────────────────────────────────────────────────────────
def ece(p: Sequence[float], y: Sequence[int], nbin: int = N_BIN) -> Tuple[float, List[Dict[str, Any]]]:
    """등폭 구간 가중평균. **구간 수는 사전 고정이다.**"""
    bins: List[List[int]] = [[] for _ in range(nbin)]
    for i, pi in enumerate(p):
        b = min(nbin - 1, max(0, int(pi * nbin)))
        bins[b].append(i)
    tot, e, table = len(p), 0.0, []
    for b, idx in enumerate(bins):
        if not idx:
            table.append({"bin": b, "n": 0})
            continue
        conf = sum(p[i] for i in idx) / len(idx)
        acc = sum(y[i] for i in idx) / len(idx)
        e += len(idx) / tot * abs(conf - acc)
        table.append({"bin": b, "n": len(idx), "lo": b / nbin, "hi": (b + 1) / nbin,
                      "conf": round(conf, 4), "acc": round(acc, 4)})
    return (e, table)


def brier(p: Sequence[float], y: Sequence[int]) -> float:
    return sum((pi - yi) ** 2 for pi, yi in zip(p, y)) / len(p)


def spec_sens(p: Sequence[float], y: Sequence[int], thr: float = 0.5) -> Tuple[float, float]:
    tp = sum(1 for pi, yi in zip(p, y) if yi == 1 and pi >= thr)
    tn = sum(1 for pi, yi in zip(p, y) if yi == 0 and pi < thr)
    n1 = sum(y)
    n0 = len(y) - n1
    return (tn / n0 if n0 else 0.0, tp / n1 if n1 else 0.0)


def boot_diff(pa: Sequence[float], pb: Sequence[float], y: Sequence[int],
              n: int = 2000, seed: int = 812) -> Tuple[float, float, float]:
    """ECE(a) − ECE(b) 의 **짝지은** 부트스트랩 구간.

    **이게 없으면 «이겼다» 를 말할 수 없다.** 두 구성이 같은 후보에 매겨진
    점수이므로 표본을 같이 뽑아야 한다 — 따로 뽑으면 상관을 버려 구간이
    부풀고, 차이가 실제보다 불확실해 보인다.

    ECE 는 구간화에 의존하는 통계라 정규근사를 안 쓴다(`CLAUDE.md §4`).
    """
    import random as _r
    rng = _r.Random(seed)
    m = len(y)
    obs = ece(pa, y)[0] - ece(pb, y)[0]
    ds: List[float] = []
    for _ in range(n):
        idx = [rng.randrange(m) for _ in range(m)]
        ya = [y[i] for i in idx]
        if 0 < sum(ya) < m:            # 한쪽 라벨만 뽑히면 ECE 가 무의미하다
            ds.append(ece([pa[i] for i in idx], ya)[0]
                      - ece([pb[i] for i in idx], ya)[0])
    ds.sort()
    if len(ds) < 100:
        return (obs, float("nan"), float("nan"))
    return (obs, ds[int(0.025 * len(ds))], ds[int(0.975 * len(ds))])


def boot_brier(pa: Sequence[float], pb: Sequence[float], y: Sequence[int],
               n: int = 2000, seed: int = 812) -> Tuple[float, float, float]:
    """Brier(a) − Brier(b) 의 **짝지은** 부트스트랩 구간 — 09-26 밤 신설 (결함 361).

    ## 왜 이게 필요했나

    보고서 §4.2 의 Brier 구간(보정 효과 · 모델 단독 대비 · 개발 단계 사상 대비)이 **일회성
    스크립트**에서 나왔다. §9 가 «4.2 보정» 의 재현 명령으로 가리키는 이 모듈은 **ECE 구간만**
    찍어 그 수를 재현하지 못했다 — «보고하는 통계는 코드에서 나와야 한다»(`CLAUDE.md §4`)의 위반이다.

    난수는 `boot_diff` 와 **같게** 쓴다(seed · 뽑는 방식). 그래서 보고서의 구간이 이 함수에서
    그대로 나온다(시험 [202]). Brier 는 한쪽 라벨만 뽑혀도 정의되므로 표본을 버리지 않는다.
    """
    import random as _r
    rng = _r.Random(seed)
    m = len(y)
    obs = brier(pa, y) - brier(pb, y)
    ds: List[float] = []
    for _ in range(n):
        idx = [rng.randrange(m) for _ in range(m)]
        ya = [y[i] for i in idx]
        ds.append(brier([pa[i] for i in idx], ya) - brier([pb[i] for i in idx], ya))
    ds.sort()
    return (obs, ds[int(0.025 * len(ds))], ds[int(0.975 * len(ds))])


def verify_monotone(s: Sequence[float], p: Sequence[float]) -> bool:
    """Platt 은 단조여야 한다. 순위가 바뀌면 **버그다.**"""
    pair = sorted(zip(s, p))
    return all(pair[i][1] <= pair[i + 1][1] + 1e-9 for i in range(len(pair) - 1))


# ── 실행 ─────────────────────────────────────────────────────────────
def run(fit_p: str = FIT_DEFAULT, eval_p: str = EVAL_DEFAULT,
        configs: Sequence[str] = ("B5", "B0"),
        compare_fit: Optional[str] = None) -> Dict[str, Any]:
    """`compare_fit` — 다른 적합 집합(예: 개발 단계 모델의 층 A)으로 맞춘 **B5 사상**을 같은 평가
    점수에 걸어 Brier 차이를 잰다. 보고서 §4.2 «개발 단계 모델로 맞춘 사상과도 구별되지 않는다»
    의 계산기다(09-26 · 결함 361)."""
    out: Dict[str, Any] = {"ok": True, "spec_sha256": SPEC_SHA, "nbin": N_BIN,
                           "configs": {}, "dropped": [], "error": None}
    base = load(fit_p, configs[0])
    ev0 = load(eval_p, configs[0])
    if not base or not ev0:
        return {"ok": False, "error": "점수 자료 없음 — 없는 걸 0으로 세지 않는다"}
    fit_keys = set(base["keys"])
    drop = sorted({k for k in ev0["keys"] if k in fit_keys})
    out["dropped"] = ["%s / %s" % k for k in drop]
    for cfg in configs:
        f = load(fit_p, cfg)
        e = load(eval_p, cfg)
        if not f or not e:
            out["configs"][cfg] = {"error": "%s 점수 없음(적합 %s · 평가 %s)"
                                   % (cfg, bool(f), bool(e))}
            continue
        keep = [i for i, k in enumerate(e["keys"]) if k not in fit_keys]
        ys = [e["y"][i] for i in keep]
        ss = [e["s"][i] for i in keep]
        A, B = fit_platt(f["s"], f["y"])
        ps = apply_platt(ss, A, B)
        raw_e, raw_t = ece(ss, ys)
        cal_e, cal_t = ece(ps, ys)
        sp0, se0 = spec_sens(ss, ys)
        sp1, se1 = spec_sens(ps, ys)
        out["configs"][cfg] = {
            "A": round(A, 5), "B": round(B, 5),
            "n_fit": len(f["s"]), "n_eval": len(ys), "n_dropped": len(e["y"]) - len(ys),
            "ece_raw": round(raw_e, 4), "ece_platt": round(cal_e, 4),
            "brier_raw": round(brier(ss, ys), 4), "brier_platt": round(brier(ps, ys), 4),
            "spec_raw": round(sp0, 4), "spec_platt": round(sp1, 4),
            "sens_raw": round(se0, 4), "sens_platt": round(se1, 4),
            "monotone_ok": verify_monotone(ss, ps),
            "table_raw": raw_t, "table_platt": cal_t,
            "_p_raw": ss, "_p_platt": ps, "_y": ys,
        }
    b5, b0 = out["configs"].get("B5") or {}, out["configs"].get("B0") or {}
    if "_y" in b5:
        boot: Dict[str, Any] = {"b5_platt_vs_raw":
                                boot_diff(b5["_p_platt"], b5["_p_raw"], b5["_y"])}
        if "_y" in b0 and len(b0["_y"]) == len(b5["_y"]):
            boot["b5_vs_b0_platt"] = boot_diff(b5["_p_platt"], b0["_p_platt"], b5["_y"])
            boot["b5_vs_b0_raw"] = boot_diff(b5["_p_raw"], b0["_p_raw"], b5["_y"])
        out["boot"] = boot
        # ── 09-26 밤 · **Brier 구간 — 보고서 §4.2 의 주지표** (결함 361) ─────────────
        #   ECE 구간(위)은 사전명세 `사전명세_보정.md` 의 원래 판정용으로 남긴다. 보고서는 ECE 를
        #   주장에 안 쓴다(균형 집합에서 널 모형의 ECE 가 0). 주장은 아래 Brier 구간에서 나온다.
        yb = b5["_y"]
        half = [0.5] * len(yb)
        bb: Dict[str, Any] = {
            "b5_platt_vs_raw": boot_brier(b5["_p_platt"], b5["_p_raw"], yb),
            "b5_platt_vs_null": boot_brier(b5["_p_platt"], half, yb),
            "b5_raw_vs_null": boot_brier(b5["_p_raw"], half, yb)}
        if "_y" in b0 and b0["_y"] == yb:
            bb["b0_platt_vs_raw"] = boot_brier(b0["_p_platt"], b0["_p_raw"], yb)
            bb["b5_vs_b0_raw"] = boot_brier(b5["_p_raw"], b0["_p_raw"], yb)
            bb["b5_platt_vs_b0_raw"] = boot_brier(b5["_p_platt"], b0["_p_raw"], yb)
            bb["b5_vs_b0_platt"] = boot_brier(b5["_p_platt"], b0["_p_platt"], yb)
        cf = load(compare_fit, configs[0]) if compare_fit else None
        if cf:
            Ac, Bc = fit_platt(cf["s"], cf["y"])
            pc = apply_platt(b5["_p_raw"], Ac, Bc)
            bb["b5_platt_vs_compare"] = boot_brier(b5["_p_platt"], pc, yb)
            out["compare_fit"] = {"file": os.path.basename(compare_fit), "config": configs[0],
                                  "A": round(Ac, 5), "B": round(Bc, 5),
                                  "brier_platt": round(brier(pc, yb), 4)}
        out["boot_brier"] = bb
    for c in out["configs"].values():
        for k in ("_p_raw", "_p_platt", "_y"):
            c.pop(k, None)
    return out


def _brier_lines(r: Dict[str, Any]) -> List[str]:
    """Brier 구간 — 보고서 §4.2 가 인용하는 줄을 **이 함수가** 찍는다(결함 361)."""
    bb = r.get("boot_brier") or {}
    if not bb:
        return []
    L = ["## Brier — 주지표 (보고서 §4.2 · 짝지은 부트스트랩 2,000회 · seed 812)", "",
         "> ECE 는 참고다 — 1:1 균형 집합에서 «늘 기저율» 널 모형의 ECE 가 0 이라 주장에 안 쓴다.", "",
         "```"]
    names = (("b5_platt_vs_raw", "B5 보정 − B5 원점수"),
             ("b5_platt_vs_compare", "B5 보정 − B5 (비교 적합 사상)"),
             ("b5_platt_vs_null", "B5 보정 − 널(늘 0.5)"),
             ("b5_raw_vs_null", "B5 원점수 − 널(늘 0.5)"),
             ("b5_vs_b0_raw", "B5 원점수 − B0 원점수"),
             ("b5_platt_vs_b0_raw", "B5 보정 − B0 원점수"),
             ("b5_vs_b0_platt", "B5 보정 − B0 보정"),
             ("b0_platt_vs_raw", "B0 보정 − B0 원점수"))
    for k, lab in names:
        v = bb.get(k)
        if not v:
            continue
        sig = ("0을 안 넘는다" if (v[1] < 0 and v[2] < 0) or (v[1] > 0 and v[2] > 0)
               else "0을 포함 — 구별 못 한다")
        L.append("%-24s %+.4f  [%+.4f, %+.4f]   %s" % (lab, v[0], v[1], v[2], sig))
    L += ["```", ""]
    cf = r.get("compare_fit")
    if cf:
        L += ["> 비교 적합 — `%s`(%s) 로 맞춘 사상 A %.4f · B %.4f · 같은 평가 점수에 걸면 Brier %.4f"
              % (cf["file"], cf["config"], cf["A"], cf["B"], cf["brier_platt"]), ""]
    return L


def report(fit_p: str = FIT_DEFAULT, eval_p: str = EVAL_DEFAULT,
           compare_fit: Optional[str] = None) -> str:
    r = run(fit_p, eval_p, compare_fit=compare_fit)
    if not r["ok"]:
        return "**측정 불가** — %s" % r["error"]
    C = r["configs"]
    L = ["# Platt 보정 — 사전명세 실행 결과", "",
         "> 명세 `사전명세_보정.md` sha256 `%s…`" % SPEC_SHA[:8],
         "> 적합 **층 A 84** → 평가 **홀드아웃** · ECE **%d구간 등폭(사전 고정)** · **LLM 0회**"
         % r["nbin"], ""]
    if r["dropped"]:
        L += ["## 뺀 것 — **조용히 빼지 않는다**", "",
              "적합 집합과 평가 집합에 같은 쌍이 **%d개** 있었다. 명세대로 평가에서 뺐다."
              % len(r["dropped"]), ""]
        for d in r["dropped"]:
            L.append("- `%s`" % d)
        L += ["", "> 약물만 겹치는 것(적응증은 다름)은 안 뺐다 — Platt 은 점수 2모수",
              "> 변환이라 약물 정체성을 학습하지 않는다. **그 사실도 여기 적는다.**", ""]
    L += ["## 주지표", "",
          "| 구성 | | ECE 원점수 | **ECE Platt** | Brier 원→Platt |",
          "|---|---|---|---|---|"]
    nm = {"B5": "**우리 전체**", "B0": "기준선(LLM 단독)"}
    for cfg in ("B5", "B0"):
        c = C.get(cfg) or {}
        if c.get("error"):
            L.append("| `%s` | %s | — | — | %s |" % (cfg, nm.get(cfg, ""), c["error"]))
            continue
        L.append("| `%s` | %s | %.4f | **%.4f** | %.4f → %.4f |"
                 % (cfg, nm.get(cfg, ""), c["ece_raw"], c["ece_platt"],
                    c["brier_raw"], c["brier_platt"]))
    L.append("")
    L += _brier_lines(r)
    L += ["## 먼저 — **문서의 «B0 0.072» 는 dev 수치였다**", "",
          "`제안서_대조표.md` 가 *«B5 0.105 > B0 0.072 — 기준선이 더 정직하다»* 라고",
          "적어 놨는데, 그건 **층 A(dev) 에서 잰 것**이다. 집합을 갈라 보면 —", "",
          "```",
          "               B0        B5",
          "층 A (dev 84)  0.0756    0.1168     ← 문서가 근거로 쓴 것",
          "홀드아웃 (770) %.4f    %.4f     ← 순서가 뒤집힌다" % (
              (C.get("B0") or {}).get("ece_raw", float("nan")),
              (C.get("B5") or {}).get("ece_raw", float("nan"))),
          "```", "",
          "**문서가 dev 수치로 일반화된 문장을 쓰고 있었다.** 다만 홀드아웃의",
          "차이는 매우 작다 — **«뒤집혔으니 우리가 이겼다» 로 읽으면 안 된다.**",
          "그래서 아래에 짝지은 부트스트랩 구간을 같이 낸다.", ""]
    b5, b0 = C.get("B5") or {}, C.get("B0") or {}
    if "ece_platt" in b5:
        ok1 = b5["ece_platt"] < b5["ece_raw"]
        L += ["## 사전 판정", "", "```",
              "주①  Platt 이 B5 의 ECE 를 낮추는가     %s   %.4f → %.4f"
              % ("**충족**" if ok1 else "**미달**", b5["ece_raw"], b5["ece_platt"]),
              ]
        if "ece_platt" in b0:
            ok2 = b5["ece_platt"] < b0["ece_platt"]
            L.append("주②  보정 후 B5 가 B0 를 이기는가     %s   B5 %.4f vs B0 %.4f"
                     % ("**충족**" if ok2 else "**미달**", b5["ece_platt"], b0["ece_platt"]))
        L.append("```")
        L.append("")
        bd = r.get("boot") or {}
        if bd:
            L += ["### 구간 없이 «이겼다» 를 말하지 않는다", "", "```"]
            for k, lab in (("b5_platt_vs_raw", "B5  Platt − 원점수"),
                           ("b5_vs_b0_platt", "B5 − B0  (둘 다 Platt 후)"),
                           ("b5_vs_b0_raw", "B5 − B0  (둘 다 원점수)")):
                v = bd.get(k)
                if not v:
                    continue
                sig = "**0을 안 넘는다**" if (v[1] < 0 and v[2] < 0) or (v[1] > 0 and v[2] > 0) else "0을 포함 — **구별 못 한다**"
                L.append("%-26s %+.4f  [%+.4f, %+.4f]   %s" % (lab, v[0], v[1], v[2], sig))
            L += ["```", "",
                  "> 음수면 앞쪽이 더 잘 보정된 것이다. 짝지은 부트스트랩 2000회.", ""]
        v2 = bd.get("b5_vs_b0_platt")
        if v2 and (v2[1] < 0 < v2[2]) and b5.get("ece_platt", 1) < b0.get("ece_platt", 0):
            L += ["### 주② 는 **점추정만** 충족이다 — 그렇게 적는다", "",
                  "사전 기준을 *«B5_ECE < B0_ECE 이면 ✅»* 라고 **점추정으로만** 썼다.",
                  "그 기준으로는 충족이다. 그런데 짝지은 구간이 **0을 포함한다.**", "",
                  "```",
                  "B5 − B0 (Platt 후)   %+.4f  [%+.4f, %+.4f]   ← 0을 넘나든다"
                  % (v2[0], v2[1], v2[2]),
                  "```", "",
                  "**기준을 고치지 않는다.** 사전에 적은 대로 «충족» 이라 적고,",
                  "동시에 **«이겼다» 고는 말하지 않는다.** 둘 다 사실이다.", "",
                  "> **내 명세가 부족했다.** `CLAUDE.md §4` 가 *«구간을 항상 같이»* 라고",
                  "> 하는데 주② 기준을 맨 점추정으로 썼다. 하필 그게 **나에게 유리한**",
                  "> 판정을 내주는 기준이었다. 다음 명세에서는 판정 기준 자체에",
                  "> 구간을 넣는다.", "",
                  "발표에서 말할 수 있는 것은 하나뿐이다 —",
                  "***«보정을 걸면 우리 확률이 정직해진다. 기준선보다 낫다고는 아직 못 한다.»***", ""]
        if "ece_platt" in b0 and not (b5["ece_platt"] < b0["ece_platt"]):
            L += ["**주② 미달.** 보정 후에도 **기준선이 더 정직하다.**",
                  "제안서 §4 「보정」 항목을 ⚠️ 로 유지하고, 발표에서",
                  "*«보정 축은 우리가 이기지 못했다»* 고 말한다. **기준을 고치지 않는다.**", ""]
    L += ["## 검증용 — 성과가 아니다", "",
          "Platt 은 단조변환이라 **순위를 보존한다.** 특이도·민감도가 바뀌면",
          "그건 개선이 아니라 **구현 버그**다.", "",
          "| 구성 | 단조 | 특이도 원→Platt | 민감도 원→Platt |", "|---|---|---|---|"]
    for cfg in ("B5", "B0"):
        c = C.get(cfg) or {}
        if c.get("error"):
            continue
        L.append("| `%s` | %s | %.3f → %.3f | %.3f → %.3f |"
                 % (cfg, "✅" if c["monotone_ok"] else "❌ **버그**",
                    c["spec_raw"], c["spec_platt"], c["sens_raw"], c["sens_platt"]))
    L += ["", "> 문턱 0.5 기준이라 **값 자체는 바뀔 수 있다** — 보정이 점수를 옮기기",
          "> 때문이다. 바뀌면 안 되는 것은 **순위**이고 그게 `단조` 칸이다.", "",
          "## 신뢰도-적중률 (B5 · Platt 적용 후)", "",
          "| 구간 | n | 평균 신뢰도 | 적중률 |", "|---|---|---|---|"]
    for row in (b5.get("table_platt") or []):
        if not row.get("n"):
            continue
        L.append("| %.1f–%.1f | %d | %.3f | %.3f |"
                 % (row["lo"], row["hi"], row["n"], row["conf"], row["acc"]))
    L += ["", "## 미리 적어 둔 한계", "",
          "- **평가 집합은 이미 두 번 열렸다**(홀드아웃 주①·②). 이건 **세 번째 질문**이다",
          "- 적합 표본 84 는 작다. 2모수라 과적합 위험은 낮지만 구간이 넓다",
          "- ECE 는 구간화에 민감하다. **10구간으로 사전 고정**했고 다른 값은 안 본다",
          "- **Platt 은 보정만 고친다. 변별력은 못 고친다** — 그게 이 절의 한계다",
          "- B6 는 평가 집합에 점수가 없어 **못 잰다.** 없는 걸 추정하지 않는다", ""]
    return "\n".join(L)


CARD_DEFAULT = "calibration.json"


def write_card(path: str = CARD_DEFAULT, fit_p: str = FIT_DEFAULT,
               eval_p: str = EVAL_DEFAULT, label: Optional[str] = None) -> Dict[str, Any]:
    """화면이 읽을 **작은 카드**를 굽는다. (`dash.py` · 배포본)

    ## 왜 이게 필요한가 (결함 132)

    `dash.py` 가 ECE 를 **상수로 박아** 두고 있었다 —

        ECE = [("B0 폐쇄형", 0.072, …), ("B5 전체", 0.105, "**기준선보다 나쁘다**")]

    그런데 `evidence.py` 독스트링이 스스로 이렇게 적어 뒀다 —
    *"`결함 38건` 을 `app.py` 에 타이핑하면 다음에 39건이 됐을 때 **화면만
    거짓말한다.** 파일에서 센다."* **보정 수치는 그 규칙 밖에 있었다.**

    그래서 08-12에 Platt 을 적용하고도 화면은 *"Platt 보정은 아직 안 했다 ·
    기준선보다 나쁘다"* 를 계속 찍었다. 심사위원이 볼 화면이 우리 최신
    결과를 부정하는 상태였다.

    ## 카드에 **Brier 를 같이 넣는다** — ECE 만으로는 못 판다

    평가집합이 1:1 균형(기저율 0.497)이라 **«항상 기저율만 답하는» 상수
    예측기의 ECE 가 0.0000** 이다(실측). 즉 ECE 는 정보를 버릴수록 좋아진다.
    **Brier 는 적정 점수 규칙이라 그 속임수가 안 통한다** — 상수 예측기
    0.2500, 우리 0.2137. 화면에는 **둘 다** 싣는다.
    """
    r = run(fit_p, eval_p)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    b5, b0 = r["configs"].get("B5") or {}, r["configs"].get("B0") or {}
    ev = load(eval_p, "B5")
    keep = [i for i, k in enumerate(ev["keys"])
            if k not in set(load(fit_p, "B5")["keys"])]
    ys = [ev["y"][i] for i in keep]
    base = sum(ys) / len(ys) if ys else 0.0
    # 09-26 밤 · **어느 시스템의 수인지 카드가 스스로 말한다** (결함 360) — 화면이 파일 이름 대신
    #   «08-05 · mini» 를 코드에 박아 두고 있어서, 카드를 terra 로 바꾸면 화면이 거짓말을 했다.
    card = {
        "생성": "bioreroute.bench.calibrate.write_card",
        "라벨": label or "",
        "적합": os.path.basename(fit_p), "평가": os.path.basename(eval_p),
        "명세": SPEC_SHA[:8], "n_eval": len(ys), "기저율": round(base, 4),
        "널모형": {"설명": "항상 기저율만 답하는 상수 예측기",
                 "ece": round(ece([base] * len(ys), ys)[0], 4),
                 "brier": round(brier([base] * len(ys), ys), 4)},
        "B5": {"ece_raw": b5.get("ece_raw"), "ece_platt": b5.get("ece_platt"),
               "brier_raw": b5.get("brier_raw"), "brier_platt": b5.get("brier_platt")},
        "B0": {"ece_raw": b0.get("ece_raw"), "ece_platt": b0.get("ece_platt"),
               "brier_raw": b0.get("brier_raw"), "brier_platt": b0.get("brier_platt")},
        "boot": {k: [round(x, 4) for x in v] for k, v in (r.get("boot") or {}).items()},
        "boot_brier": {k: [round(x, 4) for x in v]
                       for k, v in (r.get("boot_brier") or {}).items()},
        "경고": ("**균형 집합에서 ECE 는 정보를 버릴수록 좋아진다** — 널 모형 참조. "
                "ECE 단독으로 «정직해졌다» 를 주장하지 마라. Brier 를 같이 봐라."),
    }
    tmp = path + ".tmp"                      # 끊기면 반쪽이 남지 않게 (결함 335 와 같은 자리)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(card, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    card["ok"] = True
    return card


def main(argv=None) -> int:
    # 리디렉션돼도 안 깨지게 한다 (결함 131) — `report_io` 참조
    from .report_io import utf8_stdout
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Platt 보정 (사전명세 실행 · LLM 0회)")
    ap.add_argument("--fit", default=FIT_DEFAULT)
    ap.add_argument("--eval", default=EVAL_DEFAULT)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--card", action="store_true",
                    help="화면이 읽을 calibration.json 을 굽는다")
    ap.add_argument("--compare-fit", default=None,
                    help="다른 적합 집합(예: 개발 단계 모델의 층 A)으로 맞춘 B5 사상과 Brier 를 비교한다")
    ap.add_argument("--label", default=None,
                    help="카드에 적을 시스템 이름(예: «본선 홀드아웃 · gpt-5.6-terra · seed 42»)")
    a = ap.parse_args(argv)
    if a.card:
        print(json.dumps(write_card(fit_p=a.fit, eval_p=a.eval, label=a.label),
                         ensure_ascii=False, indent=1))
        return 0
    if a.json:
        print(json.dumps(run(a.fit, a.eval, compare_fit=a.compare_fit), ensure_ascii=False, indent=1))
        return 0
    print(report(a.fit, a.eval, compare_fit=a.compare_fit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
