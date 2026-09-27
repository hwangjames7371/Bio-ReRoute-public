# -*- coding: utf-8 -*-
"""정답표 감사 — TN 이 정말 효능 실패인가 (제안서 §4.1 · 결함 47)

    py -m bioreroute.bench.labelaudit
    py -m bioreroute.bench.labelaudit --sensitivity bench_results_clean.json

제안서 §4.1이 요구한 것 —

  > 실패 50건을 **실패 모드별로 라벨링**하고, 시스템이 **원리상 커버하는
  > 모드**에서의 특이도를 보고한다. **예측하지 않는 모드(특발성 DILI 등)는
  > 정직하게 구분한다.**

이걸 안 해서 `기각 정밀도 100% (7/7)` 의 분모가 무엇인지 모르는 채로
줄곧 썼다. 실측하니 **TN 의 43%가 효능 실패가 아니었다.**

## 이 도구가 하는 일과 하지 않는 일

- **한다** — CT.gov `detail` 원문을 규칙으로 분류하고 건수를 낸다
- **한다** — 기존 결과의 부분집합으로 사후 민감도 분석
- **안 한다** — **정답표를 고치지 않는다.** 결과를 보고 정답표를 고치면
  그 숫자는 측정이 아니라 조작이다(`CLAUDE.md §3-2`)
- **안 한다** — 라벨 파이프라인을 재실행하지 않는다(`§3-1`)

## 분류 규칙의 순서가 결과를 정한다

`toxicity` 와 `lack of efficacy` 가 **같은 문장에 함께** 나오는 경우가 있다
(`cisplatin`: why=lack of efficacy, detail=production stopped for toxicity).
그래서 순서를 못 박는다 —

```
① 모집·사업상 이유    약과 무관하므로 가장 먼저 뺀다
② 안전성·독성        단, 효능 표현이 같이 있으면 ③으로 넘긴다
③ 타 연구 근거        이 시험이 실패한 게 아니다
④ 효능 실패          위 셋에 안 걸린 것 중 효능 표현이 있는 것
⑤ 판단 불가          **효능으로 치지 않는다**
```

**⑤를 효능으로 치면 분모가 부풀고, 그러면 이 감사가 자기 목적을 배신한다.**
"모르는 것"은 "적법한 TN"이 아니다.
"""

import argparse
import collections
import csv
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from .stats import wilson

MATCHED = "bench_matched.csv"

# 분류 규칙. **자료를 보고 만든 것이지만, 만든 뒤에 고치지 않았다** —
# 이 파일의 sha256 을 감사 문서에 남긴다.
RE_ADMIN = re.compile(r"accrual|enrollment|recruit|business reason", re.I)
RE_TOX = re.compile(r"toxicit|safety|mortalit|adverse", re.I)
RE_EFF = re.compile(r"futilit|lack of efficac|no benefit|did not meet"
                    r"|failed to demonstrate|insufficient activity|efficacy", re.I)
RE_OTHER = re.compile(r"from other studies|in a preceding study", re.I)

MODES = ("효능 실패", "안전성·독성", "모집·사업상", "타 연구 근거", "판단 불가")


def classify(why: str, detail: str) -> str:
    """중단 사유 → 실패 모드. **순서가 규칙의 전부다**(독스트링 참조)."""
    d = detail or ""
    w = why or ""
    if RE_ADMIN.search(d):
        return "모집·사업상"
    if RE_TOX.search(d) and not RE_EFF.search(d):
        return "안전성·독성"
    if RE_OTHER.search(d):
        return "타 연구 근거"
    if RE_EFF.search(d + " " + w):
        return "효능 실패"
    return "판단 불가"


def load(path: str = MATCHED) -> List[Dict[str, str]]:
    # **utf-8-sig 다.** BOM 때문에 `label` 열이 `﻿label` 이 되어
    # 라벨이 전부 None 이 된 채로 "모순 0건"을 출력한 적이 있다.
    # 그 검사는 통과한 게 아니라 **아무것도 안 본 것**이었다.
    with open(path, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows or "label" not in rows[0]:
        raise SystemExit("label 열이 없다 — 인코딩(BOM)을 확인해라: %s" % path)
    return rows


def audit(path: str = MATCHED) -> Dict[str, Any]:
    rows = [r for r in load(path) if r["label"] == "TN"]
    cnt = collections.Counter(classify(r["why"], r["detail"]) for r in rows)
    n = len(rows) or 1
    bad = sum(v for k, v in cnt.items() if k != "효능 실패")

    # 오귀속 — 중단 사유가 **다른 약**의 것
    mis = []
    for r in rows:
        d = r["detail"] or ""
        for tag in ("MyVax", "AIM-HIGH", "Carfilzomib", "Pertuzumab"):
            if tag in d and tag.lower() not in (r["drug"] or "").lower():
                mis.append({"drug": r["drug"], "원문_약": tag, "detail": d[:70]})
    dup = [k for k, v in collections.Counter(
        (r["drug"].lower(), r["nct"] or "") for r in rows).items() if v > 1]

    return {"n_tn": len(rows), "모드별": dict(cnt),
            "효능_아님": bad, "효능_아님_비율": round(bad / n, 3),
            "오귀속": mis, "중복": [k[0] for k in dup]}


def sensitivity(results: str, path: str = MATCHED) -> Dict[str, Any]:
    """**사후** 민감도 분석 — 효능 실패만 남기고 다시 센다.

    파이프라인을 재실행하지 않는다. 기존 결과의 부분집합이다.
    **주 수치를 대체하지 않는다** — 결과를 보고 정한 부분집합이라 사후편향이 있다.
    """
    d = json.load(open(results, encoding="utf-8"))
    rows, det = d["rows"], {}
    for r in load(path):
        det[(r["drug"].lower(), r["indication"].lower())] = (r["why"], r["detail"])

    out = {"주의": "**사전 지정 아님.** 주 수치를 대체하지 않는다", "구성": {}}
    for cfg, R in d["results"].items():
        V = R.get("verdicts") or []
        if len(V) != len(rows):
            out["구성"][cfg] = {"오류": "verdicts 길이 불일치 — 판단하지 않는다"}
            continue
        idx_tn = [i for i, r in enumerate(rows) if r["label"] == "TN"]
        idx_cl = [i for i in idx_tn
                  if classify(*det.get((rows[i]["drug"].lower(),
                                        rows[i]["indication"].lower()),
                                       ("", ""))) == "효능 실패"]
        ktp = sum(1 for i, r in enumerate(rows) if r["label"] == "TP" and V[i] == "기각")

        def blk(idx):
            k = sum(1 for i in idx if V[i] == "기각")
            tot = k + ktp
            plo, phi = wilson(k, tot) if tot else (0.0, 0.0)
            rlo, rhi = wilson(k, len(idx)) if idx else (0.0, 0.0)
            return {"기각": k, "n": len(idx),
                    "정밀도": (round(k / tot, 3) if tot else None),
                    "정밀도_CI": [round(100 * plo, 1), round(100 * phi, 1)],
                    "재현율": (round(k / len(idx), 3) if idx else None),
                    "재현율_CI": [round(100 * rlo, 1), round(100 * rhi, 1)]}
        out["구성"][cfg] = {"전체TN": blk(idx_tn), "효능실패만": blk(idx_cl),
                           "TP_오기각": ktp}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="정답표 감사 (결함 47)")
    ap.add_argument("--matched", default=MATCHED)
    ap.add_argument("--sensitivity", metavar="RESULTS_JSON")
    a = ap.parse_args(argv)

    r = audit(a.matched)
    print("=" * 64)
    print("정답표 감사 — TN %d건을 CT.gov 원문으로 재분류" % r["n_tn"])
    print("=" * 64)
    for k in MODES:
        v = r["모드별"].get(k, 0)
        mark = "  " if k == "효능 실패" else "← "
        print("  %s%-14s %3d  %5.1f%%" % (mark, k, v, 100 * v / max(r["n_tn"], 1)))
    print("\n  **효능 실패가 아닌 것: %d/%d = %.0f%%**"
          % (r["효능_아님"], r["n_tn"], 100 * r["효능_아님_비율"]))
    if r["오귀속"]:
        print("\n  오귀속 %d건 — 중단 사유가 다른 약의 것" % len(r["오귀속"]))
        for m in r["오귀속"]:
            print("    %-16s ← 원문 '%s'" % (m["drug"][:16], m["원문_약"]))
    if r["중복"]:
        print("  중복 행: %s" % ", ".join(sorted(set(r["중복"]))))

    if a.sensitivity:
        if not os.path.exists(a.sensitivity):
            print("\n결과 파일 없음: %s" % a.sensitivity, file=sys.stderr)
            return 1
        s = sensitivity(a.sensitivity, a.matched)
        print("\n" + "=" * 64)
        print("사후 민감도 분석 — %s" % s["주의"])
        print("=" * 64)
        for cfg, c in s["구성"].items():
            if "오류" in c:
                print("  %s: %s" % (cfg, c["오류"]))
                continue
            for lbl in ("전체TN", "효능실패만"):
                b = c[lbl]
                print("  %-4s %-8s 정밀도 %d/%d %s  재현율 %d/%d %s"
                      % (cfg, lbl, b["기각"], b["기각"] + c["TP_오기각"],
                         b["정밀도_CI"], b["기각"], b["n"], b["재현율_CI"]))
    print("\n**정답표를 고치지 않는다.** 재고, 적고, 다음 명세에 사전 반영한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
