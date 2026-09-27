# -*- coding: utf-8 -*-
"""모델 독립성 — `사전명세_모델독립성_0922.md` §2~§4 의 수를 **코드로** 낸다.

    py -m bioreroute.bench.indep             아는 모델 전부 (없는 파일은 건너뛴다)

## 왜 있나

09-23 `sol` 분석을 **즉석 스크립트**로 했고, 그 과정에서 틀린 수가 두 번
나왔다(결함 326·331). 명세가 정한 수는 명세가 정한 방식으로 **한 곳에서**
낸다(`CLAUDE.md §4`). `luna.ps1 -After` 가 이것을 부른다.

## 무엇을 내나

```
§2 주지표   누출 제외 B5 AUROC [Hanley–McNeil 95%] · n · 폭 → CI 가 **전부 겹치나**
§3 예측     누출 제외 B0 AUROC · 기각 재현율(TN 기각/TN) · ECE(B5)
§4 반증     CI 불겹침 · B0 > 0.6 · 기각 재현율 차 > 10%p · F0 조회 실패 ≥ 6
보충 §5     라우터 «불명» 20% 이상 (형식 실패 경보)
사후        모든 모델이 안 외운 **공통 부분집합**의 B0·B5 AUROC
```

통계 함수는 `bench.run` 의 것을 **그대로** 쓴다(AUROC · Hanley–McNeil · ECE).
**LLM 0회 · 네트워크 0회.**
"""

import json
import os
import sys

MODELS = (("mini", "bench_results_sealed.json", "s_sealed.json"),
          ("terra", "홀드아웃_본선모델.json", "상태_홀드본선_B5.json"),
          ("sol", "홀드아웃_sol.json", "상태_sol_B5.json"),
          ("luna", "홀드아웃_luna.json", "상태_luna_B5.json"))


def overlap(cis):
    """CI 들의 공통 구간. 겹치지 않으면 None."""
    lo = max(c[0] for c in cis)
    hi = min(c[1] for c in cis)
    return (lo, hi) if lo <= hi else None


def _auc(scores, lab, idx):
    from .run import auroc, auroc_ci
    s = [scores[i] for i in idx]
    y = [lab[i] for i in idx]
    a = auroc(s, y)
    n1 = sum(y)
    lo, hi = auroc_ci(a, n1, len(y) - n1)
    return a, lo, hi


def _trail_counts(state_path):
    """F0 조회 실패(ERROR) 수 · 라우터 «불명» 수 — 판정 원본(trail)에서."""
    if not state_path or not os.path.exists(state_path):
        return None, None, 0
    with open(state_path, encoding="utf-8") as f:
        cands = json.load(f).get("candidates") or []
    f0err = unk = 0
    for c in cands:
        for t in c.get("trail") or []:
            if t.get("gate") == "f0" and t.get("outcome") == "ERROR":
                f0err += 1
            if t.get("gate") == "router" and t.get("outcome") == "UNKNOWN":
                unk += 1
    return f0err, unk, len(cands)


def load_runs(models=MODELS, root="."):
    runs = []
    for name, res, st in models:
        rp = os.path.join(root, res)
        if not os.path.exists(rp):
            continue
        with open(rp, encoding="utf-8") as f:
            d = json.load(f)
        runs.append({"이름": name, "행": [(r["drug"], r["indication"], r["label"])
                                        for r in d["rows"]],
                     "결과": d["results"], "상태": os.path.join(root, st)})
    if runs:
        k0 = runs[0]["행"]
        for r in runs[1:]:
            if r["행"] != k0:
                raise ValueError("%s 의 행 집합이 %s 와 다르다 — 비교할 수 없다"
                                 % (r["이름"], runs[0]["이름"]))
    return runs


def summarize(runs):
    from .run import ece
    lab = [1 if k[2] == "TP" else 0 for k in runs[0]["행"]]
    n = len(lab)
    tn = [i for i in range(n) if not lab[i]]
    out = []
    for r in runs:
        b0, b5 = r["결과"]["B0"], r["결과"]["B5"]
        leak = b0.get("leak") or [False] * n
        ex = [i for i in range(n) if not leak[i]]
        v = b5["verdicts"]
        rej_tn = sum(1 for i in tn if v[i] == "기각")
        rej_all = sum(1 for i in range(n) if v[i] == "기각")
        f0err, unk, ncand = _trail_counts(r["상태"])
        out.append({
            "이름": r["이름"], "n누출제외": len(ex),
            "B5": _auc(b5["scores"], lab, ex), "B0": _auc(b0["scores"], lab, ex),
            "B5전체": _auc(b5["scores"], lab, range(n)),
            "ECE": ece(b5["scores"], lab),
            "재현율": (rej_tn, len(tn)), "정밀도": (rej_tn, rej_all),
            "F0오류": f0err, "라우터불명": (unk, ncand), "누출": leak})
    common = [i for i in range(n) if not any(s["누출"][i] for s in out)]
    for s, r in zip(out, runs):
        s["공통B5"] = _auc(r["결과"]["B5"]["scores"], lab, common)
        s["공통B0"] = _auc(r["결과"]["B0"]["scores"], lab, common)
    return out, common, lab


def report(out, common, lab):
    print("=" * 84)
    print("모델 독립성 — 명세 0922 §2~§4 · 보충 §5  (LLM 0회)")
    print("=" * 84)
    print("  %-6s %5s  %-26s %6s  %-8s %-18s %6s"
          % ("모델", "n", "§2 누출 제외 B5 AUROC [95%]", "폭", "B0", "기각 재현율(TN)", "ECE"))
    for s in out:
        a, lo, hi = s["B5"]
        k, m = s["재현율"]
        print("  %-6s %5d  %.3f [%.3f–%.3f]        %.3f  %.3f    %3d/%d = %4.1f%%   %.3f"
              % (s["이름"], s["n누출제외"], a, lo, hi, hi - lo, s["B0"][0],
                 k, m, 100.0 * k / m, s["ECE"]))
    ov = overlap([(s["B5"][1], s["B5"][2]) for s in out])
    pts = [s["B5"][0] for s in out]
    print("\n  §2 주지표 — CI 전부 겹치나:  %s   · 점추정 범위 %.3f"
          % (("✅ 겹친다 · 공통 [%.3f, %.3f]" % ov) if ov else "🔴 **안 겹친다**",
             max(pts) - min(pts)))
    print("\n  §4 반증 조건")
    b0hi = [s["이름"] for s in out if s["B0"][0] > 0.6]
    rr = [100.0 * s["재현율"][0] / s["재현율"][1] for s in out]
    print("    B0 > 0.6            %s" % ("🔴 " + ", ".join(b0hi) if b0hi else "없음"))
    print("    기각 재현율 차       %.1f%%p  %s" % (max(rr) - min(rr),
          "🔴 10%p 초과" if max(rr) - min(rr) > 10 else "(10%p 이하)"))
    for s in out:
        u, nc = s["라우터불명"]
        uu = ("%d/%d = %.1f%%%s" % (u, nc, 100.0 * u / nc, "  🔴 20% 이상" if u >= 0.2 * nc else "")
              if nc else "—")
        print("    %-6s F0 조회 실패 %s%s · 라우터 불명 %s"
              % (s["이름"], "—" if s["F0오류"] is None else s["F0오류"],
                 "  🔴 6건 이상" if (s["F0오류"] or 0) >= 6 else "", uu))
    n1 = sum(lab[i] for i in common)
    print("\n  사후 — 모두가 안 외운 공통 %d쌍 (TP %d · TN %d)" % (len(common), n1, len(common) - n1))
    for s in out:
        print("    %-6s B0 %.3f   B5 %.3f [%.3f–%.3f]" % ((s["이름"], s["공통B0"][0]) + s["공통B5"]))
    print("\n  ⚠ 주지표가 AUROC 인 것은 명세의 오류다(결함 325). 판정(기각)은 `modelpair`·`rejectsplit` 로 본다.")


def main(argv=None):
    try:
        runs = load_runs()
    except ValueError as e:
        print("  🔴 %s" % e)
        return 2
    if len(runs) < 2:
        print("  비교할 결과 파일이 둘 미만이다.")
        return 2
    out, common, lab = summarize(runs)
    report(out, common, lab)
    return 0


if __name__ == "__main__":
    sys.exit(main())
