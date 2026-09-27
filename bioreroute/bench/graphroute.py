# -*- coding: utf-8 -*-
"""라우터 분류에 **지식그래프 근거가 있는가** — 명세 `391fcfb7…`

제안서 §2 게이트 표가 라우터를 이렇게 적었다.

    라우터 | 직접 결합인가 간접 경로인가 | **LLM 분류 + 지식그래프**

우리 라우터는 **LLM 분류만** 한다(`제안서_전수대조.md:367` · ❌).
이 도구는 그 빈칸을 **먼저 재고**, 그 다음에 게이트를 만들지 정한다.

## 왜 «재고 나서» 인가

DRKG 를 붙이는 것 자체는 반나절이다. 그런데 **붙여서 뭘 보일지**가
결과에 달려 있다 — 명세 §2 가 세 갈래를 미리 적었다.

    간접 전부 공유 유전자 ≥2   → «그래프가 라우터를 뒷받침한다»
    하나라도 0                → 화면에 «경로 없음» 을 그대로 적는다
    직접과 구별 안 됨          → «라우터 검증» 이라 **부르지 않는다**

**셋 다 게이트는 만든다. 다른 것은 화면 문구다.**

## LLM 0회

라우터 분류는 `gen_state.json`(B5) 의 trail 에 **이미 있다.**
이 도구는 그 파일을 **읽기만** 한다 — 덮어쓰지 않는다(`CLAUDE.md §3-3`).
"""

import argparse
import json
import os
import statistics
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 라우터 trail 의 `detail` 첫 토막이 분류다.
#   "직접·숙주 · PIK3CA → evidence (high)"  →  직접
#   "간접 → evidence (medium)"              →  간접
_CLASS = ("직접", "간접", "오프타겟", "불명")


def router_class(cand: Dict[str, Any]) -> Optional[str]:
    """후보의 라우터 분류. 없으면 None.

    **문자열을 파싱한다는 것 자체가 결함의 씨앗**이지만(결함 166 과 같은
    유형), 저장된 state 를 다시 만들 수는 없다. 그래서 **못 읽은 것을
    «불명» 으로 섞지 않고 None 으로 따로 센다.**
    """
    for t in (cand.get("trail") or []):
        if t.get("gate") != "router":
            continue
        d = str(t.get("detail") or "")
        for c in _CLASS:
            if d.startswith(c):
                return c
        return None          # router 는 돌았는데 형식이 다르다
    return None              # router 자체가 안 돌았다 (config off)


# ══════════════════════════════════════════════════════════════════
#  ⛔ 이름으로는 **절대** 못 맞춘다 — 결함 244
#
#  08-18 첫 실행이 **커버리지 0.0% (28건 전부 미등재)** 를 냈다.
#  metformin·chloroquine 이 DRKG 에 없을 리가 없는데 0% 다.
#
#  실물을 열어 보니 노드가 **이름이 아니라 ID** 였다.
#
#      Compound::DB00331          ← DrugBank ID
#      Disease::MESH:D001943      ← MeSH ID (4,871/5,103 = 95%)
#      Disease::DOID:1725         ← 127개
#
#  `drkg.tsv` 에 문자열 `metformin` 은 **한 번도 안 나온다.**
#  즉 **이름 매칭은 구조적으로 100% 실패**한다(그래서 `_norm` 을 지웠다).
#  명세 §4-4 가 *"노드 이름과 우리 약물명이 다르면 «미상» 이 된다"* 로
#  이 실패 모드를 **예고했는데**, 예측은 «30~50%» 였다. **100% 였다.**
#
#  **자료가 없는 게 아니라 배선이 없었다** — 결함 216·218·234 와 같은 계열.
#  RepoDB 가 `drug_name → drugbank_id` 를 **2,322종** 갖고 있고,
#  우리 28쌍 중 **27개(96%)** 가 거기서 나오며 **27/27 이 DRKG 에 있다.**
# ══════════════════════════════════════════════════════════════════

REPODB = "RepoDB.csv"


def drugbank_map(root: str = ROOT) -> Dict[str, str]:
    """`약이름(소문자) → DrugBank ID`. **로컬 파일만 쓴다.**"""
    import csv
    out: Dict[str, str] = {}
    p = os.path.join(root, REPODB)
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            d = (r.get("drug_name") or "").strip().lower()
            i = (r.get("drugbank_id") or "").strip()
            if d and i and d != "na":
                out.setdefault(d, i)
    return out


def mesh_map(diseases: List[str], cache_path: str = "mesh_ids.json",
             root: str = ROOT) -> Dict[str, str]:
    """`질환명 → MeSH ID`. **NCBI 에 묻고 파일에 굳힌다.**

    질환 21개 × 1회 = **21 조회.** LLM 은 0회다(명세 §1).
    한 번 받으면 `mesh_ids.json` 에 남아 **다음부터는 조회 0회**다 —
    그래야 이 분석이 망 상태에 안 묶인다.

    못 찾은 것은 **빈 문자열로 굳힌다.** 그래야 «안 찾아봤다» 와
    «찾았는데 없다» 가 구별된다(결함 141 계열).
    """
    p = os.path.join(root, cache_path)
    got: Dict[str, str] = {}
    if os.path.exists(p):
        try:
            got = json.load(open(p, encoding="utf-8"))
        except Exception:
            got = {}
    need = [d for d in diseases if d and d not in got]
    if need:
        from ..io import sources as _S
        from ..io import cache as _cache
        # ⚠ **캐시를 먼저 읽는다** — 결함 240 이 같은 날 재발했다.
        #   `mesh_id` 가 `cache.put` 을 쓰는데 아무도 `load()` 를 안 불러서
        #   *«캐시를 읽지 않고 저장하려 했다 — 디스크 14101개와 병합»* 이
        #   화면에 찍혔다. 병합이라 잃진 않지만 **읽고 쓰는 게 규약**이다
        #   (결함 26·27 이 그걸로 났다).
        _cache.load()
        for d in need:
            got[d] = _S.mesh_id(d)
        from ..io import safeio as _io
        _io.save_json(got, p, indent=1)
    return got


def shared_genes(graph: Dict[str, Any], drug: str, disease: str,
                 top: int = 6) -> Dict[str, Any]:
    """약물 ∩ 질환 의 공유 유전자.

    **«미등재» 와 «경로 0개» 를 따로 센다** — 섞으면 결함 141 이 된다.

    ## ⛔ 08-18 — 이 함수가 **세 곳에서 틀려 있었다** (결함 244)

    08-13에 쓰고 **오늘 처음 돌렸더니 커버리지 0.0%** 였다. 원인 셋 —

    ```
    ① 반환 키   `compound_gene`·`gene_disease` 를 찾았다
                실제는 `cg`·`gc`·`gd`·`dg`·`cd`      ← **항상 빈 dict**
    ② 노드 형식 이름(`metformin`)으로 찾았다
                실제는 `Compound::DB00331`·`Disease::MESH:D001943`
    ③ 역색인   `gd`(gene→disease)를 뒤집어 만들었다
                **`dg` 가 이미 있다** — 두 번 만들었다
    ```

    셋 다 **돌려 봤으면 즉시 보였다.** «만들고 안 돌렸다» 의 표본이다.
    """
    cg = graph.get("cg") or {}
    dg = graph.get("dg") or {}          # disease → genes. **이미 있다**

    # ID 로 찾는다. 이름 매칭은 **구조적으로 0%** 라 폴백조차 안 둔다.
    dbid = (graph.get("_db") or {}).get((drug or "").strip().lower(), "")
    meid = (graph.get("_mesh") or {}).get(disease or "", "")
    dk = ("Compound::" + dbid) if dbid else ""
    sk = ("Disease::" + meid) if meid else ""

    out = {"drug_in_graph": bool(dk and dk in cg),
           "disease_in_graph": bool(sk and sk in dg),
           "drug_id": dbid, "disease_id": meid,
           "n_shared": None, "top": []}
    if not out["drug_in_graph"] or not out["disease_in_graph"]:
        return out
    sh = sorted(set(cg.get(dk) or ()) & set(dg.get(sk) or ()))
    out["n_shared"] = len(sh)
    out["top"] = [g.replace("Gene::", "") for g in sh[:top]]
    return out


def run(state: str = "gen_state.json", drkg_path: Optional[str] = None,
        limit: Optional[int] = None) -> Dict[str, Any]:
    from ..io import drkg

    p = state if os.path.isabs(state) else os.path.join(ROOT, state)
    d = json.load(open(p, encoding="utf-8"))
    cands = d.get("candidates") or []
    g = drkg.load(drkg_path, limit=limit)

    # ── **ID 매핑을 먼저 붙인다** — 이름으로는 0% 다 (결함 244) ──────
    g["_db"] = drugbank_map()
    g["_mesh"] = mesh_map(sorted({c.get("disease") or "" for c in cands}))
    n_db = sum(1 for c in cands
               if g["_db"].get((c.get("drug") or "").strip().lower()))
    n_me = sum(1 for c in cands if g["_mesh"].get(c.get("disease") or ""))
    print("  매핑  약물 %d/%d (RepoDB) · 질환 %d/%d (MeSH)"
          % (n_db, len(cands), n_me, len(cands)))

    rows: List[Dict[str, Any]] = []
    for c in cands:
        cls = router_class(c)
        s = shared_genes(g, c.get("drug") or "", c.get("disease") or "")
        rows.append({"name": c.get("name"), "label": c.get("label"),
                     "router": cls, **s})

    by: Dict[str, List[int]] = {}
    miss = miss_drug = miss_dis = 0
    for r in rows:
        if r["n_shared"] is None:
            miss += 1
            if not r.get("drug_in_graph"):
                miss_drug += 1
            if not r.get("disease_in_graph"):
                miss_dis += 1
            continue
        by.setdefault(r["router"] or "미분류", []).append(r["n_shared"])

    out = {"state": state, "config": d.get("config"), "n": len(rows),
           "n_not_in_graph": miss,
            "miss_drug": miss_drug, "miss_disease": miss_dis,
           "coverage": round(1 - miss / len(rows), 4) if rows else None,
           "by_class": {k: {"n": len(v), "median": statistics.median(v),
                            "zero": sum(1 for x in v if x == 0),
                            "values": sorted(v, reverse=True)[:12]}
                        for k, v in sorted(by.items())},
           "rows": rows}

    # ── 명세 §2-② 판정. **여기서 문턱을 안 고친다** ──────────────
    ind = by.get("간접") or []
    dirc = by.get("직접") or []
    if not ind:
        out["판정"] = "측정 불가 — 간접으로 분류된 쌍이 0건이다"
    elif any(x == 0 for x in ind):
        out["판정"] = ("**경로 없음이 있다** — 간접 %d건 중 %d건이 공유 유전자 0개. "
                      "화면에 «경로 없음» 을 그대로 적는다" % (len(ind), sum(1 for x in ind if x == 0)))
    elif all(x >= 2 for x in ind):
        out["판정"] = "**뒷받침한다** — 간접 전부 공유 유전자 ≥2"
    else:
        out["판정"] = "**애매** — 간접에 1개짜리가 있다. 뒷받침이라 안 적는다"
    if dirc and ind:
        md, mi = statistics.median(dirc), statistics.median(ind)
        out["직접_대_간접"] = {"직접_중앙": md, "간접_중앙": mi,
                          "메모": ("**직접이 더 많다 — 그래프가 기전이 아니라 인기도를 잰다는 신호**"
                                 if md > mi else "간접이 같거나 많다")}
    return out


def report(o: Dict[str, Any]) -> str:
    L = ["=" * 68,
         "라우터 ↔ 지식그래프 — 명세 `391fcfb7…`",
         "=" * 68,
         "  상태 파일 %s (구성 %s) · 후보 %d" % (o["state"], o["config"], o["n"]),
         "  **DRKG 미등재 %d건 · 커버리지 %.1f%%**"
         % (o["n_not_in_graph"], 100 * (o["coverage"] or 0)),
         # **약물이 없어서인지 질환이 없어서인지 가른다** — 결함 244.
         #   0% 를 보고 «자료에 없다» 로 읽으면 원인을 못 찾는다.
         "     그중 약물 미등재 %d · 질환 미등재 %d  (겹칠 수 있다)"
         % (o.get("miss_drug", -1), o.get("miss_disease", -1)),
         ""]
    L.append("  분류별 공유 유전자")
    for k, v in o["by_class"].items():
        L.append("    %-8s n=%-3d 중앙 %-5s 0개 %-3d  값 %s"
                 % (k, v["n"], v["median"], v["zero"], v["values"][:8]))
    if o.get("직접_대_간접"):
        t = o["직접_대_간접"]
        L += ["", "  직접 중앙 %s vs 간접 중앙 %s" % (t["직접_중앙"], t["간접_중앙"]),
              "    %s" % t["메모"]]
    L += ["", "  판정 — **명세에 적힌 그대로**", "    %s" % o["판정"], ""]
    L.append("  간접으로 분류된 쌍")
    for r in o["rows"]:
        if r["router"] != "간접":
            continue
        L.append("    %-42s 공유 %s  %s"
                 % (r["name"], r["n_shared"] if r["n_shared"] is not None else "미등재",
                    ", ".join(r["top"][:5])))
    L += ["", "  ⚠ n 이 작다. **검정이 아니라 사례 확인이다**(명세 §2-①).",
          "  ⚠ 공유 유전자는 **기전이 아니다** — 허브면 허브라고 적는다.",
          "=" * 68]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state", default="gen_state.json")
    ap.add_argument("--drkg", default=None)
    ap.add_argument("--limit", type=int, default=None,
                    help="DRKG 줄 수 상한 (시운전용)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    o = run(a.state, a.drkg, a.limit)
    print(json.dumps(o, ensure_ascii=False, indent=1) if a.json else report(o))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
