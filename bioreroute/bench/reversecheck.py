# -*- coding: utf-8 -*-
"""역발상 발굴이 정방향과 다른가 — `사전명세_역발상.md` 실행기 (§3.3-5)

## 무엇을 재는가

제안서 §3.3-5 가 역발상을 **"정방향이 구조적으로 놓치는 후보를 발굴하는
차별점"** 이라 썼다. 그 문장을 그대로 잰다.

**세 팔을 돌린다. 셋째가 대조군이고 그게 이 실험의 핵심이다.**

    R  역발상   reverse.propose(source="faers"|"sider")
    F  정방향   discover.propose
    N  무작위   승인약 풀에서 seed 812 로 뽑는다   ← **질환을 아예 안 본다**

**겹침이 낮은 것은 차별점의 증거가 아니다.** 무작위로 뽑아도 안 겹친다.
그래서 주지표는 겹침이 아니라 **F0 통과율을 N 과 견주는 것**이다.

## 08-11에 배운 것 때문에 이렇게 만들었다

어제 DRKG 에서 내가 만든 순위 보정이 **«질환을 아예 안 보는» 대조군에
졌다.** 그걸 잡은 것은 오직 사전에 박아 둔 대조군 하나였다(결함 118).
그 전에는 «허브를 뺐으니 나아졌다» 고 믿고 있었다.

## 검정력을 **미리** 계산해서 설계를 바꿨다

질환 5개면 Wilcoxon 짝비교의 최소 p 가 **0.0625** 다. 즉 어떤 결과가
나와도 p<0.05 가 **원리적으로 불가능하다.** 깔때기 실험이 n=14 로
p=0.077 을 받고 «측정 불가» 였던 것과 같은 함정이다 — 그건 **돌린 뒤에**
알았고, 이번엔 **돌리기 전에** 안다.

그래서 **판정은 후보 단위 2×2 Fisher(n=200)** 로 하고, 질환 단위
Wilcoxon 은 **참고로만** 같이 낸다.

## LLM 비용

    질환당 R 1회(MedDRA 용어 변환) + F 1회(생성) = 질환 5개면 **약 10회**
    F0 는 PubMed 기반이라 **LLM 0회**. 후보 300개가 전부 네트워크다

**FAERS·PubMed 가 필요하다.** 개발 샌드박스에서는 막혀 있어 실행이 안 된다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import sys
import time

# `fmt_p` 는 지역 복제를 안 만든다 — 정확검정 p 를 `0.0000` 으로 찍지
# 않기 위한 유일한 정본이다(결함 153). `fisher`·`wilson`·`holm` 은
# 이 파일에 복제가 있고 값은 6자리까지 같다(실측 3,000표) — 다만
# `CLAUDE.md §4` 위반이라 결함으로 적었다.
from .stats import fmt_p
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

SPEC = "사전명세_역발상.md"
SPEC_SHA = None                     # 봉인 json 에서 읽는다
POOL = "bench_tn_pool_v2.csv"       # **동결 파일** — 질환을 여기서 뽑는다
N_DISEASE = 5
K = 20
SEED = 812
ARMS = ("R", "F", "N")
OUT_DEFAULT = "reverse_eval.json"


def _norm(s: str) -> str:
    """철자 변형 병합 — `COVID-19` 과 `Covid19` 은 같은 질환이다."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def diseases(path: str = POOL, n: int = N_DISEASE) -> List[str]:
    """동결 풀에서 빈도 상위 n개. **손으로 고르지 않는다.**

    동점은 알파벳순. 표기는 그 그룹에서 가장 흔한 원문 철자를 쓴다.
    """
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    groups: Dict[str, Counter] = {}
    for r in rows:
        c = (r.get("condition") or "").strip()
        if not c:
            continue
        groups.setdefault(_norm(c), Counter())[c] += 1
    ranked = sorted(groups.items(),
                    key=lambda kv: (-sum(kv[1].values()), min(kv[1])))
    return [kv[1].most_common(1)[0][0] for kv in ranked[:n]]


# ── 세 팔 ────────────────────────────────────────────────────────────
POOL_FILES = ("bench_tn_pool_v2.csv", "bench_matched.csv", "gen_matched.csv")


def approved_pool(files: Sequence[str] = POOL_FILES) -> Dict[str, Any]:
    """대조군용 승인약 풀. **`tox.approved` 는 한 약을 확인하는 함수다.**

    08-12 실측: 초판이 `tox.approved()` 를 목록 반환으로 착각해 불렀고
    **대조군이 통째로 비었다**(결함 123). 서명은 `(name: str) -> Optional[bool]`,
    즉 ChEMBL `max_phase == 4` 인지 **하나씩** 묻는 것이다.

    그래서 우리 자료 파일들의 약물 이름을 모아 그 함수로 **거른다.**
    명세가 말한 "ChEMBL max_phase=4 풀" 이 정확히 이 거름망이다.

    **편향을 적어 둔다** — 이 이름들은 재창출 시험에 등장한 약이다.
    «중립적인 승인약 무작위 표본» 이 아니다. 대조군으로서는 오히려
    보수적이다(정방향과 같은 세계에서 뽑히므로 겹칠 여지가 크다).
    """
    from ..io import tox
    names: Dict[str, str] = {}
    seen_file = 0
    for f in files:
        if not os.path.exists(f):
            continue
        seen_file += 1
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            d = (r.get("drug") or "").strip()
            if d:
                names.setdefault(_norm(d), d)
    if not seen_file:
        return {"pool": [], "error": "풀 자료 파일이 하나도 없다: %s" % ", ".join(files)}
    if not names:
        return {"pool": [], "error": "풀 파일에서 약물 이름을 못 읽었다"}
    ok, unknown = [], 0
    for key in sorted(names):
        try:
            v = tox.approved(names[key])
        except Exception:
            v = None
        if v is True:
            ok.append(names[key])
        elif v is None:
            unknown += 1
    if not ok:
        return {"pool": [], "error":
                "승인 확인된 약이 0건이다(이름 %d · 확인불가 %d) — "
                "**0건을 결과로 쓰지 않는다**" % (len(names), unknown)}
    return {"pool": ok, "n_names": len(names), "n_unknown": unknown, "error": None}


def arm_random(k: int, seed: int, pool: Optional[Sequence[str]] = None,
               exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
    """대조군 — 승인약 풀에서 무작위. **질환을 안 본다.**"""
    if pool is None:
        got = approved_pool()
        if got.get("error"):
            return {"items": [], "error": got["error"]}
        pool = got["pool"]
    ex = {_norm(x) for x in (exclude or ())}
    cand = [d for d in pool if _norm(d) not in ex]
    if not cand:
        return {"items": [], "error": "제외 후 남은 약이 없다"}
    rng = random.Random(seed)
    pick = rng.sample(cand, min(k, len(cand)))
    return {"items": [{"drug": d, "mechanism": "무작위 대조군"} for d in pick],
            "error": None}


def collect(disease: str, k: int = K, seed: int = SEED,
            source: str = "faers") -> Dict[str, Any]:
    from ..agents import reverse as RV, discover as DS
    out: Dict[str, Any] = {"disease": disease, "arms": {}, "errors": {}}
    r = RV.propose(disease, k=k, source=source)
    out["arms"]["R"] = [x.get("drug") or x.get("name") for x in r.get("items", [])]
    out["errors"]["R"] = r.get("error")
    # ── 부지표 `Rz` — **명세 §1 이 요구했는데 초판이 빠뜨렸다** ────────
    #
    #   `사전명세_역발상_SIDER.md §1`: *"부 순위: |SE(약)| 정규화 z ←
    #   부지표로만. 판정에 안 씀"*. 예측 ④(«정규화판이 원시보다 나쁠 것»)이
    #   이것 없이는 **미측정**으로 남는다. 재기로 적어 놓고 안 잰 것은
    #   «안 재기로 했다» 와 다르다 — 명세를 쓰는 의미를 갉아먹는다.
    #
    #   **판정 경로에 안 넣는다.** `ARMS` 에 없으므로 Fisher 는 R vs N 이다.
    if source == "sider":
        rz = RV.propose(disease, k=k, source=source, rank="norm")
        out["arms"]["Rz"] = [x.get("drug") or x.get("name")
                             for x in rz.get("items", [])]
        out["errors"]["Rz"] = rz.get("error")
    f = DS.propose(disease, k=k)
    out["arms"]["F"] = [x.get("drug") or x.get("name") for x in f.get("items", [])]
    out["errors"]["F"] = f.get("error")
    # ── 결함 129 — **`hash()` 는 실행마다 달라진다** ───────────────────
    #
    #   초판은 `seed + abs(hash(_norm(disease))) % 1000` 이었다. 파이썬은
    #   문자열 해시를 **프로세스마다 무작위화**한다(PEP 456). 그래서
    #   명세가 «seed 812 고정» 이라 적어 놨는데 **대조군이 실행마다 바뀌었다.**
    #
    #   실측: 같은 코드로 세 번 부르면 850 · 727 · 369 이 나온다.
    #   N 팔이 64 → 68 → 59 → 58 로 흔들린 것이 이 때문이다.
    #
    #   **재현 안 되는 대조군은 사전등록의 의미를 깎는다.** 결정론적
    #   해시로 바꾼다. 자료를 봉인해 놓고 표본이 흔들리면 봉인이 헛것이다.
    _h = int(hashlib.sha256(_norm(disease).encode()).hexdigest()[:8], 16)
    n = arm_random(k, seed + _h % 1000)
    out["arms"]["N"] = [x["drug"] for x in n["items"]]
    out["errors"]["N"] = n.get("error")
    return out


# ── F0 (LLM 0회) ─────────────────────────────────────────────────────
def f0_outcome(drug: str, disease: str) -> str:
    """PASS / FLAG / KILL / ERROR — `gates.gate_f0` 를 그대로 태운다."""
    from ..core import gates as G
    from ..core.state import Candidate, RunState
    c = Candidate(name="%s / %s" % (drug, disease), origin="reversecheck",
                  query="%s %s" % (drug, disease), drug=drug, disease=disease)
    st = RunState(query_title=disease, settings="reversecheck", stamp="",
                  candidates=[c], config={})
    try:
        G.gate_f0(st)
    except Exception as e:
        return "ERROR:%s" % type(e).__name__
    for rec in reversed(c.trail):
        if getattr(rec, "gate", "") == "f0":
            return getattr(rec, "outcome", "?")
    return "?"


# ── 통계 ─────────────────────────────────────────────────────────────
def fisher(a: int, b: int, c: int, d: int) -> float:
    """2×2 양측 Fisher 정확검정. 소표본에 Wald 를 쓰지 않는다(`CLAUDE.md §4`)."""
    def lf(n): return math.lgamma(n + 1)
    def lp(x, y, z, w):
        return (lf(x + y) + lf(z + w) + lf(x + z) + lf(y + w)
                - lf(x) - lf(y) - lf(z) - lf(w) - lf(x + y + z + w))
    obs = lp(a, b, c, d)
    tot, r1, c1 = a + b + c + d, a + b, a + c
    p = 0.0
    for i in range(max(0, c1 - (tot - r1)), min(r1, c1) + 1):
        cur = lp(i, r1 - i, c1 - i, tot - r1 - c1 + i)
        if cur <= obs + 1e-9:
            p += math.exp(cur)
    return min(1.0, p)


def wilson(k: int, n: int) -> Tuple[float, float]:
    if not n:
        return (0.0, 0.0)
    z, p = 1.959963985, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    A, B = {_norm(x) for x in a}, {_norm(x) for x in b}
    return len(A & B) / len(A | B) if (A | B) else 0.0


def holm(pairs):
    """Holm 보정. `graphcheck` 와 같은 구현 — **명세 §5 가 요구했다.**"""
    live = sorted([(k, p) for k, p in pairs if p is not None], key=lambda r: r[1])
    m, out, prev = len(live), {}, 0.0
    for i, (k, p) in enumerate(live):
        q = min(1.0, max(prev, p * (m - i)))
        out[k] = q
        prev = q
    for k, p in pairs:
        if p is None:
            out[k] = None
    return out


# ── 실행 ─────────────────────────────────────────────────────────────
def run(out_p: str = OUT_DEFAULT, source: str = "faers",
        k: int = K, resume: bool = True, budget: float = 900.0) -> Dict[str, Any]:
    t0 = time.time()
    # **질의 전에 읽는다** (결함 26·27 · 124). 안 부르면 `_STORE` 가 빈 dict 로
    # 시작해 저장할 때마다 디스크와 병합 경고가 뜨고, 무엇보다 **캐시가
    # 하나도 안 먹어 전건을 새로 조회한다.** 08-12 실측: 그래서 846초 걸렸다.
    from ..io import cache as _cache
    _cache.load()
    st: Dict[str, Any] = {"per": {}}
    if resume and os.path.exists(out_p):
        try:
            st = json.load(open(out_p, encoding="utf-8"))
            st.setdefault("per", {})
        except Exception:
            st = {"per": {}}
    ds = diseases()
    for dis in ds:
        key = "%s::%s" % (source, dis)
        if key in st["per"] or time.time() - t0 > budget:
            continue
        got = collect(dis, k=k, source=source)
        rec: Dict[str, Any] = {"disease": dis, "arms": got["arms"],
                               "errors": got["errors"], "f0": {}}
        for arm in list(got["arms"]):          # Rz 도 태운다 (판정엔 안 씀)
            rec["f0"][arm] = {}
            for drug in got["arms"][arm]:
                if not drug:
                    continue
                rec["f0"][arm][drug] = f0_outcome(drug, dis)
        rec["jaccard_RF"] = jaccard(got["arms"]["R"], got["arms"]["F"])
        rec["jaccard_NF"] = jaccard(got["arms"]["N"], got["arms"]["F"])
        st["per"][key] = rec
        json.dump(st, open(out_p, "w", encoding="utf-8"), ensure_ascii=False)
    st["meta"] = {"spec": SPEC, "seed": SEED, "k": k, "diseases": ds,
                  "source": source, "n_done": len(st["per"])}
    json.dump(st, open(out_p, "w", encoding="utf-8"), ensure_ascii=False)
    _mine = [k for k in st["per"] if k.startswith(source + "::")]
    # **자료원별로 센다.** 앞판이 `len(st["per"])` 를 써서 faers 항목까지
    #   세는 바람에 `"done": 10, "of": 5` 가 찍혔다. 자료엔 영향이 없지만
    #   **화면이 거짓말하면 사람이 화면을 안 믿게 된다.**
    return {"ok": True, "source": source, "done": len(_mine), "of": len(ds),
            "sec": round(time.time() - t0, 1)}


def report(out_p: str = OUT_DEFAULT, source: str = "faers") -> str:
    st = json.load(open(out_p, encoding="utf-8"))
    per = {k: v for k, v in st["per"].items() if k.startswith(source + "::")}
    L = ["# 역발상 실측 — 사전명세 실행 결과", "",
         "> 명세 `%s` · 자료원 **%s** · seed %d · k %d" % (SPEC, source, SEED, K),
         "> **LLM 은 질환당 2회(용어 변환·생성)뿐이고 F0 는 0회다.**", ""]
    if not per:
        return "\n".join(L + ["**결과 없음** — `--run --source %s` 를 먼저 돌려라." % source])

    L += ["## 질환 — **동결 파일에서 뽑았다. 손으로 안 골랐다**", "",
          "```", "출처  %s (동결)" % POOL]
    for k_ in sorted(per):
        L.append("  " + per[k_]["disease"])
    L += ["```", "", "## 주지표 — F0 통과율(PASS)", "",
          "| 팔 | | PASS | 시도 | 통과율 | 95% CI |", "|---|---|---|---|---|---|"]
    name = {"R": "**역발상**", "F": "정방향", "N": "**무작위 (대조군)**"}
    tot: Dict[str, List[int]] = {a: [0, 0] for a in ARMS}
    for k_ in sorted(per):
        for a in ARMS:
            for _d, o in per[k_]["f0"][a].items():
                tot[a][1] += 1
                if o == "PASS":
                    tot[a][0] += 1
    for a in ARMS:
        p, n = tot[a]
        lo, hi = wilson(p, n)
        L.append("| `%s` | %s | %d | %d | **%.1f%%** | [%.1f–%.1f] |"
                 % (a, name[a], p, n, 100 * p / n if n else 0, 100 * lo, 100 * hi))
    L += ["", "## 판정 — R vs N (Fisher 정확검정)", ""]
    rp, rn = tot["R"]
    np_, nn = tot["N"]

    # ── **빈 팔로 판정하지 않는다** (결함 123) ────────────────────────
    #
    #   초판은 대조군이 0/0 인데도 Fisher 를 돌려 p=1.0000 을 받고
    #   *"구별되지 않는다 → 「차별점」 철회"* 라는 판정문을 냈다.
    #   **조회 실패를 결과로 센 것**이고 결함 35 와 같은 고장이다.
    #   그때도 «조회 실패» 절에 사유가 찍혀 있었는데 **판정 경로가
    #   그걸 안 봤다.** 안내문은 방어가 아니다 — 여기서 구조로 막는다.
    if rn == 0 or nn == 0:
        which = [n for n, v in (("역발상 R", rn), ("무작위 N", nn)) if v == 0]
        L += ["> ⛔ **판정하지 않는다.** %s 팔이 비었다(시도 0건)."
              % " · ".join(which),
              ">",
              "> 0/0 에 Fisher 를 돌리면 p=1.0 이 나오고 그건 «구별 안 됨» 이",
              "> 아니라 **«측정 자체를 못 함»** 이다. 아래 「조회 실패」 절을 보고",
              "> 그 원인을 먼저 고쳐라. **결과가 없는 것을 결과로 쓰지 않는다.**", ""]
        L += ["## 조회 실패 — **«후보 없음» 이 아니다**(결함 35)", ""]
        for k_ in sorted(per):
            for a, e in per[k_]["errors"].items():
                if e:
                    L.append("- `%s` %s — %s" % (a, per[k_]["disease"], str(e)[:140]))
        return "\n".join(L + [""])

    pv = fisher(rp, rn - rp, np_, nn - np_)
    win = (rp / rn if rn else 0) > (np_ / nn if nn else 0)
    L += ["```",
          "역발상  %3d/%3d" % (rp, rn),
          "무작위  %3d/%3d" % (np_, nn),
          "Fisher 양측 p = %.4f" % pv,
          "```", ""]

    # ── **KILL 을 빼고 다시 잰다** (08-12 전수조사) ────────────────────
    #
    #   F0 실패는 두 종류다 —
    #     FLAG  약은 실재하는데 **질환 연결 문헌이 0건**   ← 우리가 재려던 것
    #     KILL  **약 이름 자체가 PubMed 에 없다**          ← 이름 해석 실패
    #
    #   둘을 같이 세면 «이름을 못 읽은 것» 이 «연결이 없다» 로 계산된다.
    #   실측: 대조군 N 에 KILL 이 8건 있고, **그걸 빼면 SIDER 의 p 가
    #   0.0072 → 0.0527 로 문턱을 넘는다.** FAERS 는 반대로 강해진다.
    #
    #   **이 분해가 없으면 결론이 이름 해석 실패에 얹혀 있는지 모른다.**
    def _cnt(arm, kinds):
        n = k = 0
        for kk in sorted(per):
            for _d, o in (per[kk]["f0"].get(arm) or {}).items():
                if o in kinds:
                    n += 1
                    if o == "PASS":
                        k += 1
        return k, n
    rp2, rn2 = _cnt("R", {"PASS", "FLAG"})
    np2, nn2 = _cnt("N", {"PASS", "FLAG"})
    if rn2 and nn2 and (rn2 != rn or nn2 != nn):
        pv2 = fisher(rp2, rn2 - rp2, np2, nn2 - np2)
        L += ["### KILL 을 빼면 — **이름 해석 실패를 「연결 없음」과 안 섞는다**", "",
              "```",
              "                    전체            KILL 제외",
              "역발상  %3d/%3d → %3d/%3d" % (rp, rn, rp2, rn2),
              "무작위  %3d/%3d → %3d/%3d" % (np_, nn, np2, nn2),
              # ⚠ `%.4f` 는 **정확검정 p 를 0.0000 으로 찍는다** —
              #   실측 2.98e-05 가 «p=0.0000» 이 됐다. 정확검정은 0 을
              #   내지 않는다. `stats.fmt_p` 가 정확히 이걸 위해 있는데
              #   여기서 안 썼다 (결함 153).
              "Fisher   %s  →  **%s**" % (fmt_p(pv), fmt_p(pv2)),
              "```", ""]
        if pv < 0.05 <= pv2:
            L += ["> ⚠ **문턱을 넘는다.** 이 결과는 대조군의 «약 이름이 문헌에 "
                  "없다» 를 «질환 연결이 없다» 와 **같이 세는 데 의존**한다.",
                  "> 전체 수치를 성능으로 팔 때 이 줄을 같이 말해야 한다.", ""]
        elif pv2 < pv:
            L += ["> KILL 을 빼면 **오히려 강해진다** — 결론이 이름 해석 실패에 "
                  "얹혀 있지 않다는 뜻이다.", ""]
    if pv < 0.05 and win:
        L.append("**대조군을 이겼다.** §3.3-5 「차별점」 문구가 실측으로 뒷받침된다 —")
        L.append("다만 **F0 통과는 «좋은 후보» 가 아니라 «정보가 있다» 는 최소 검사**다.")
    elif pv < 0.05:
        L.append("**대조군에 졌다.** 「차별점」 주장을 철회한다.")
    else:
        L.append("**구별되지 않는다(%s).** 사전 기준대로 「차별점」 주장을 철회하고" % fmt_p(pv))
        L.append("역발상은 *«자료원이 다른 두 번째 생성기»* 라고만 적는다.")
        L.append("")
        L.append("> **«차이가 없다» 가 아니라 «측정하지 못했다» 이다.**")
    # ── 부지표(명세 §1) — 정규화판. **판정에 안 쓴다** ─────────────
    if source == "sider":
        zp = zn = 0
        for k_ in sorted(per):
            for _d, o in (per[k_]["f0"].get("Rz") or {}).items():
                zn += 1
                if o == "PASS":
                    zp += 1
        if zn:
            lo, hi = wilson(zp, zn)
            rp, rn = tot["R"]
            L += ["", "## 부지표 — **정규화판 `Rz`** (명세 §1 · 판정 제외)", "",
                  "```",
                  "원시   R   %3d/%3d = %.1f%%" % (rp, rn, 100 * rp / rn if rn else 0),
                  "정규화 Rz  %3d/%3d = %.1f%%  [%.1f–%.1f]"
                  % (zp, zn, 100 * zp / zn, 100 * lo, 100 * hi),
                  "```", "",
                  "**예측 ④는 «정규화판이 원시보다 나쁠 것»이었다.** "
                  + ("맞았다." if (zp / zn) < (rp / rn if rn else 1) else "**틀렸다.**"),
                  "",
                  "> 어제 DRKG 에서 차수로 나눴다가 **대조군한테도 졌다**(결함 118).",
                  "> 같은 방향인지 보는 것이 이 칸의 목적이다.",
                  "> **판정은 원시 순위가 한다** — 명세가 그렇게 고정했다.", ""]

    # ── 명세 §3 진단 — **라벨 길이를 재고 있는가** (SIDER 전용) ────────
    #
    #   원시 공유 수로 정렬하면 «라벨에 부작용을 많이 적은 약» 이 위로 온다.
    #   그건 생물학이 아니라 **라벨 작성 성실도**다. 사전에 정한 문턱 —
    #   **상위 후보의 |SE| 중앙값이 전체 중앙값의 3배를 넘으면**
    #   이겼더라도 **순위를 성능으로 팔지 않는다.**
    if source == "sider":
        from ..io import faers as _FA
        sz = _FA.sider_label_sizes()
        nm = {v.lower(): k for k, v in (_FA.sider_names() or {}).items()}
        allv = sorted(sz.values())
        if allv:
            med_all = allv[len(allv) // 2]
            picked = sorted(sz[nm[(d or "").lower()]]
                            for k_ in sorted(per) for d in per[k_]["arms"]["R"]
                            if (d or "").lower() in nm and nm[(d or "").lower()] in sz)
            L += ["", "## 진단 — **라벨 길이를 재고 있는가** (명세 §3)", "", "```"]
            if picked:
                med_top = picked[len(picked) // 2]
                ratio = med_top / med_all if med_all else float("inf")
                L += ["상위 후보 %d개의 |SE| 중앙값   %d" % (len(picked), med_top),
                      "SIDER 전체 %d약의 |SE| 중앙값  %d" % (len(allv), med_all),
                      "배수                          **%.1f배**  (문턱 3배)" % ratio,
                      "```", ""]
                L += (["> ⚠ **문턱을 넘었다.** 이 순위는 «질환과의 관련» 보다",
                       "> **«라벨에 부작용을 많이 적었나»** 를 재고 있을 가능성이 크다.",
                       "> 사전 기준대로 **순위를 성능으로 팔지 않는다** — 대조군을",
                       "> 이겼더라도 그렇다. **기준을 고치지 않는다.**", ""]
                      if ratio > 3 else
                      ["> 문턱 안이다. 그래도 **높은 쪽으로 치우친 것은 사실**이고,",
                       "> 원시 개수 정렬이므로 설계상 당연하다.", ""])
            else:
                L += ["상위 후보가 없어 진단 불가", "```", ""]

    # ── **자료원 둘을 「독립 재현」이라 부르지 않는다** (08-12) ─────────
    #
    #   내가 08-12에 *"두 자료원이 독립으로 같은 답을 냈다"* 고 적었다.
    #   **틀렸다.** 대조군 N 이 두 실행에서 **완전히 동일**하다 —
    #   질환 5개 전부 20/20 같은 약이다. 두 Fisher 검정이 **관측치 100개를
    #   공유**한다. 독립이 아니다. (R 팔끼리는 겹침 0 이라 그건 맞다.)
    #
    #   그리고 명세 §5 가 *"자료원 둘 다 돌리면 **Holm 보정**한다"* 고
    #   적어 놨는데 **안 걸었다.** 여기서 건다.
    other = "sider" if source == "faers" else "faers"
    op = {k: v for k, v in st["per"].items() if k.startswith(other + "::")}
    if op:
        on = {tuple(v["arms"]["N"]) for v in op.values()}
        mn = {tuple(v["arms"]["N"]) for v in per.values()}
        shared = bool(on & mn)
        oR, oN = [0, 0], [0, 0]
        for v in op.values():
            for _d, o in (v["f0"].get("R") or {}).items():
                oR[1] += 1
                oR[0] += (o == "PASS")
            for _d, o in (v["f0"].get("N") or {}).items():
                oN[1] += 1
                oN[0] += (o == "PASS")
        if oR[1] and oN[1]:
            po = fisher(oR[0], oR[1] - oR[0], oN[0], oN[1] - oN[0])
            hq = holm([(source, pv), (other, po)])
            L += ["## 다른 자료원과 — **「독립 재현」이 아니다**", "", "```",
                  "%-6s  %-9s  Holm q%s" % (source, fmt_p(pv),
                                           fmt_p(hq[source])[1:]),
                  "%-6s  p=%.4f   Holm q=%.4f" % (other, po, hq[other]),
                  "```", ""]
            if shared:
                L += ["> ⚠ **두 검정이 대조군을 공유한다** — N 팔이 같은 약 "
                      "목록이다. 그러므로 **«두 자료원이 독립으로 확인했다» 는",
                      "> 말을 쓰면 안 된다.** 공유하지 않는 것은 R 팔뿐이다.",
                      "> (명세 §5 가 요구한 Holm 을 여기서 건다 — 08-12까지 "
                      "안 걸고 있었다.)", ""]

    L += ["", "## 부지표 — 겹침 (판정에 안 씀)", "",
          "| 질환 | J(역발상, 정방향) | J(무작위, 정방향) |", "|---|---|---|"]
    for k_ in sorted(per):
        r = per[k_]
        L.append("| %s | %.3f | %.3f | " % (r["disease"], r["jaccard_RF"], r["jaccard_NF"]))
    L += ["", "**겹침이 낮은 것은 차별점의 증거가 아니다** — 무작위도 안 겹친다.",
          "이 표는 서술이고 판정 근거가 아니다.", ""]
    errs = [(per[k_]["disease"], a, e)
            for k_ in sorted(per) for a, e in per[k_]["errors"].items() if e]
    if errs:
        L += ["## 조회 실패 — **«후보 없음» 이 아니다**(결함 35)", ""]
        for d, a, e in errs:
            L.append("- `%s` %s — %s" % (a, d, str(e)[:120]))
        L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    # 리디렉션돼도 안 깨지게 한다 (결함 131) — `report_io` 참조
    from .report_io import utf8_stdout
    utf8_stdout()
    ap = argparse.ArgumentParser(description="역발상 실측 (사전명세 실행)")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--diseases", action="store_true", help="뽑힌 질환만 본다 (비용 0)")
    ap.add_argument("--source", default="faers", choices=("faers", "sider"))
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--k", type=int, default=K)
    ap.add_argument("--budget", type=float, default=900.0)
    a = ap.parse_args(argv)
    if a.diseases:
        for d in diseases():
            print(" ", d)
        return 0
    if a.run:
        print(json.dumps(run(a.out, a.source, a.k, budget=a.budget), ensure_ascii=False))
        return 0
    if a.report:
        print(report(a.out, a.source))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
