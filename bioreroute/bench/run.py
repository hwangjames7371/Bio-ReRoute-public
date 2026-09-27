# -*- coding: utf-8 -*-
"""벤치마크 실측 — 제거 실험 + 누출 측정.

핵심 대조는 하나다.

    폐쇄형(B0, 문헌 없음)  vs  전체 시스템(B5, 문헌 읽음)

전체 시스템이 폐쇄형보다 낫지 않다면 우리가 만든 파이프라인은 값을 못 한 것이다.
반대로 폐쇄형이 이미 잘 맞힌다면 그건 모델이 외운 것이고, 그 항목에서는
전체 시스템이 맞혀도 "근거를 읽어서"라고 말할 수 없다.

실행
  py -m bioreroute.bench.run bench_matched.csv --configs B0 B2 B5
  py -m bioreroute.bench.run bench_matched.csv --configs B0 --dry   # 비용 추정만
"""

import argparse
import csv
import json
import os
import math
import re
import sys
import time

from ..agents import closedbook
from .stats import wilson
from ..core import gates
from ..core.state import Candidate, RunState
from ..io import cache, llm, sources
from . import query as Q


# ─────────────────────────────────────────────────────────────
# 지표
# ─────────────────────────────────────────────────────────────
def auroc(scores, labels):
    """labels: 1=TP, 0=TN. 동점은 평균 순위로 처리한다."""
    pairs = sorted(zip(scores, labels))
    n1 = sum(labels)
    n0 = len(labels) - n1
    if n1 == 0 or n0 == 0:
        return None
    ranks, i = [0.0] * len(pairs), 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    s1 = sum(r for r, (_, l) in zip(ranks, pairs) if l == 1)
    return (s1 - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def auroc_ci(a, n1, n0):
    """Hanley–McNeil 근사 95% 신뢰구간. n이 작으면 반드시 붙여야 한다."""
    if a is None or n1 == 0 or n0 == 0:
        return None, None
    q1 = a / (2 - a)
    q2 = 2 * a * a / (1 + a)
    se = math.sqrt(max(a * (1 - a) + (n1 - 1) * (q1 - a * a)
                       + (n0 - 1) * (q2 - a * a), 0) / (n1 * n0))
    return max(0.0, a - 1.96 * se), min(1.0, a + 1.96 * se)


def ece(scores, labels, bins=5):
    """기대 보정 오차. 확률이 실제 빈도와 맞는가."""
    tot, n = 0.0, len(scores)
    if n == 0:
        return None
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(s, l) for s, l in zip(scores, labels)
               if (s > lo or (b == 0 and s >= lo)) and s <= hi]
        if not sel:
            continue
        conf = sum(s for s, _ in sel) / len(sel)
        acc = sum(l for _, l in sel) / len(sel)
        tot += len(sel) / n * abs(conf - acc)
    return tot


TIER2 = False       # 시점 차단 여부
TIER2_GAP = 1       # 종료 몇 년 전까지 볼 것인가 (예측 지평)


def trail_summary(c):
    """궤적 요약 — **자율성 지표의 원자료** (09-01 추가).

    ## 왜 필요했나 — 08-31 에 **잴 데이터가 없다**는 걸 알았다

    심사기준의 「에이전트 자율성 10점」이 100점 중 유일한 🟡 였다.
    재려고 보니 `bench_results*.json` 에 **점수와 판정만** 있었다 —
    어느 경로로 갈렸는지, 무엇을 건너뛰었는지가 **버려지고 있었다.**

    파이프라인은 이미 `c.trail` 에 전부 남긴다(`state.note`). 여기서
    하는 일은 **만드는 것이 아니라 버리지 않는 것**이다.

    ## 무엇을 남기나 — 자율성 항목이 묻는 것만

        route     라우터가 고른 검증 경로 (structure / evidence / None)
        skip      **스스로 건너뛴** 관문 — 상황을 보고 내린 판단만
        skip_off  ⛔ **구성에서 꺼진 것**(`config off`). 자율성 근거가
                  **아니다.** 09-12에 이 둘이 섞여 있었다 — 아래 참조
        killed    F0 조기 종료 — 비용 순서 원칙이 실제로 작동했는가
        flips     veto 가 **스스로 뒤집힌** 횟수. 자기수정의 실물
        abstain   ⚠ **판단 자체를 못 한 것**

    ## ⚠ `abstain` 을 따로 남기는 이유 — 08-31 결함 ⑤

    점수는 `0.5 if p is None else p/100.0` 으로 저장된다. 그래서
    **«판단 못 함»과 «신뢰도 50»이 똑같이 `0.5`** 가 된다. 08-31 에
    선택적 예측을 재면서 그 `0.5` 를 전부 **«양성이라고 답한 것»** 으로
    셌고, **부등호 하나가 «유의한 우세»를 만들고 있었다.**

    실측으로 B5 의 `0.500` 283건 중 **282건이 「보류」이고 1건이
    「조건부」** 였다 — 거의 기권이지만 **섞여 있다.** 이 칸이 있으면
    다음부터는 섞이지 않는다. **안내문이 아니라 구조로 막는다.**
    """
    route, skip, flips = None, [], 0
    skip_off = []           # ⚠ 09-12 신설 — 아래 주석을 반드시 읽어라
    mech, target = "", ""
    outcomes = {}
    for r in getattr(c, "trail", []) or []:
        # ⚠ 같은 게이트가 여러 번 나오면 **마지막 결과**가 남는다
        #    (veto 가 CHANGED 두 번인 경우). 횟수는 `flips` 가, 원본
        #    건수는 `n_gates` 가 지키므로 정보는 안 잃는다.
        outcomes[r.gate] = r.outcome
        if r.outcome == "SKIP":
            # ── ⛔ 09-12 · **«구성에서 껐다» 와 «스스로 건너뛰었다» 를
            #        절대 섞지 않는다** ─────────────────────────────
            #
            #   09-12 첫 궤적 실측(84쌍)에서 `skip` 이 **88건**이었는데
            #   그중 **84건이 `registry` 이고 사유가 «config off»** 였다.
            #   즉 **B5 구성에 애초에 없는 게이트**를 «스스로 건너뛴 것»
            #   으로 세고 있었다.
            #
            #   이 칸은 **자율성 10점의 근거**로 쓰려던 것이다. 그대로
            #   냈으면 심사에서 *"왜 건너뛰었나"* → *"설정에서 껐습니다"*
            #   가 된다. **주장이 그 자리에서 무너진다.**
            #
            #   결함 35 계열이다 — 그때는 «조회 실패»와 «근거 없음»을
            #   섞지 말라였고, 이번은 **«구성 부재»와 «자율 판단»**이다.
            #   그리고 **하필 우리에게 유리한 방향**이라 더 위험했다.
            if "config off" in (r.detail or ""):
                skip_off.append(r.gate)
            else:
                skip.append(r.gate)
        elif r.outcome == "CHANGED" and "veto" in (r.gate or ""):
            flips += 1
        elif r.outcome == "BRANCH" and route is None:
            # detail 형식: "간접 → evidence (high)" ·
            #              "직접·병원체 · RNA pol → structure (high)"
            d = r.detail or ""
            for tag in ("structure", "evidence"):
                if tag in d:
                    route = tag
                    break
            # ── ⚠ 09-01 재검토 · **`route` 만으로는 채점을 못 한다** ──
            #
            #   `bench/bindcheck` 는 라우터의 「직접 결합」 주장을 ChEMBL
            #   로 검증하는데, 그 채점은 **`mech`** 를 본다
            #   (「직접·병원체」·「직접·숙주」만 채점 대상).
            #
            #   그런데 `route` 는 **「직접·숙주」와 「간접」을 못 가른다**
            #   — 둘 다 `evidence` 다. 그래서 `mech` 를 안 남기면
            #   `from_trail` 이 빈 값을 내고 **84쌍을 돌려도 채점이
            #   0건**이 된다. 09-01 재검토에서 모의 궤적으로 태워 보고
            #   알았다 — **9/7 에 돌렸으면 그때 알았을 것이다.**
            head = d.split("→")[0]
            for full in ("직접·병원체", "직접·숙주", "오프타겟", "간접", "불명"):
                if full in head:
                    mech = full
                    break
            if "·" in head:                     # "직접·숙주 · JAK1" → "JAK1"
                tail = head.split("·")[-1].strip()
                if tail and tail not in ("병원체", "숙주"):
                    target = tail
        elif r.outcome == "UNKNOWN" and not mech:
            mech = "불명"
    p = getattr(c, "confidence", None)
    return {"route": route, "mech": mech, "target": target,
            "skip": skip, "skip_off": skip_off, "flips": flips,
            "killed": bool(getattr(c, "killed", False)),
            "abstain": p is None,          # ⚠ 0.5 와 구별한다 (결함 ⑤)
            "n_gates": len(getattr(c, "trail", []) or []),
            "outcomes": outcomes}


def to_candidate(row):
    c = Candidate(name="%s / %s" % (row["drug"], row["indication"]),
                  origin=row["label"], query=Q.pair(row["drug"], row["indication"]),
                  drug=Q.clean(row["drug"]), disease=Q.clean(row["indication"]),
                  pubchem=Q.clean(row["drug"]) or None)
    if TIER2:
        # 시험 종료보다 GAP년 앞까지의 문헌만 준다.
        #
        #   GAP=1 : 종료 직전 — "결과가 나오기 직전에 걸렀는가"
        #   GAP=5 : 시험 설계 무렵 — 2상 결과조차 아직 없을 수 있다
        #
        #   지평을 늘려가며 성능이 어떻게 무너지는지 보는 것이 핵심이다.
        #   지평 1년에서만 잘하면 "이미 알려진 걸 읽은 것"에 가깝고,
        #   지평 5년에서도 버티면 진짜 예측에 가깝다.
        y = row.get("ctgov_year") or row.get("year") or ""
        try:
            c.cutoff_year = int(str(y)[:4]) - TIER2_GAP
        except Exception:
            c.cutoff_year = None
    return c


def preflight(rows, n=8):
    """실제 실행 전에 질의가 살아 있는지 확인한다.

    30분 돌린 뒤에 "전부 0건이었다"를 알게 되면 늦다.
    """
    # 09-24 · 문구를 사실에 맞췄다 — `pubmed_lookup` 은 **캐시에 있으면 캐시를 읽는다.**
    #   동결 실험에는 맞는 동작이지만 «실제로 조회한다» 는 거짓이었다(망 상태를 모른다).
    print("\n[사전 점검] 질의 %d건 — 캐시에 있으면 캐시를 읽는다(그때는 망 상태를 모른다)"
          % min(n, len(rows)))
    step = max(1, len(rows) // n)
    bad = 0
    for r in rows[::step][:n]:
        c = to_candidate(r)
        res = sources.pubmed_lookup(c.query)
        cnt = res.get("count")
        mark = "OK  " if (cnt or 0) > 0 else "0건 "
        if res.get("error"):
            mark = "실패"
        if (cnt or 0) == 0 or res.get("error"):
            bad += 1
        print("  %s %-58s %s" % (mark, c.query[:58],
                                 res.get("error") or ("%s건" % cnt)))
    if bad:
        print("  → %d/%d 가 0건 또는 실패다." % (bad, min(n, len(rows))))
        if bad > n / 2:
            print("     절반을 넘었다. 이 상태로 돌리면 대부분 '환각'으로 기각된다.")
            return False
    else:
        print("  → 전부 정상.")
    return True


def run_config(rows, cfg_name, stamp):
    st = RunState("벤치마크", cfg_name, stamp,
                  [to_candidate(r) for r in rows], dict(gates.CONFIGS[cfg_name]))
    return gates.run_pipeline(st)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("matched", nargs="?", default="bench_matched.csv")
    ap.add_argument("--configs", nargs="+", default=["B0", "B2", "B5"])
    ap.add_argument("--stratum", default="A", help="A | B | all")
    ap.add_argument("--cache", default="pubmed_cache.json")
    # ── 결함 330 — **기본값이 없다** ──
    #   09-23 붙여 넣은 명령이 `--` 뒤에서 갈려 `--configs`·`--out` 없이 떴다.
    #   기본값이면 B0·B2·B5 를 돌려 옛 결과(`bench_results.json`)에 쓴다.
    #   예산 상한이 **우연히** 막았다. 실행에는 `--out` 을 **반드시** 적는다.
    ap.add_argument("--out", default=None,
                    help="결과 파일 — **실행에는 필수**(--dry 는 없어도 된다 · 결함 330)")
    ap.add_argument("--dry", action="store_true", help="호출 수만 추정하고 끝낸다")
    ap.add_argument("--limit", type=int, default=0,
                    help="앞에서 N쌍만 (소규모 시운전용)")
    ap.add_argument("--with-registry", default="",
                    help="bench_ceiling.csv 경로. 독립 시험이 있는 쌍만 남긴다")
    ap.add_argument("--skip-preflight", action="store_true")
    ap.add_argument("--tier2", action="store_true",
                    help="시점 차단 — 시험 종료 이전 문헌만 준다")
    ap.add_argument("--gap", type=int, default=1,
                    help="예측 지평(년). 종료 N년 전까지만 본다. 1=직전, 5=설계 무렵")
    ap.add_argument("--allow-label-nct", action="store_true",
                    help="라벨 출처 시험도 근거로 쓴다(누출 발생)")
    ap.add_argument("--save-state", default="",
                    help="팩트체크 판정 원본을 남긴다(사람 표본 검토용)")
    ap.add_argument("--cost-out", default="",
                    help="깔때기 **단계별 토큰**을 파일로 남긴다 "
                         "(배점 ④ · `사전명세_비용곡선.md`). "
                         "캐시가 살아 있으면 토큰 0이다 — "
                         "재려면 BIOREROUTE_BYPASS_CACHE=1")
    a = ap.parse_args(argv)
    if not a.out:
        if not a.dry:
            print("  🔴 --out 을 적어라 — 기본값으로 쓰면 옛 결과를 덮거나 섞는다(결함 330).")
            print("     예:  --out 홀드아웃_새실행.json   (확인만 하려면 --dry)")
            return 2
        a.out = ""                       # --dry 는 결과 파일을 안 쓴다
    global TIER2, TIER2_GAP
    TIER2, TIER2_GAP = a.tier2, a.gap

    # 결과 파일을 조용히 덮어쓰면 **앞서 돌린 구성이 통째로 사라진다.**
    #   실측: B0·B5·B6를 다 돌린 뒤 B6만 다시 돌렸더니 비교 대상이 없어졌다.
    #   441회를 쓴 결과가 31회짜리 실행에 지워지는 것이다.
    prev = {}
    if a.out and os.path.exists(a.out):
        try:
            with open(a.out, encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:
            prev = {}
    lost = [k for k in (prev.get("results") or {}) if k not in a.configs]

    rows = list(csv.DictReader(open(a.matched, encoding="utf-8-sig")))
    if a.stratum != "all":
        rows = [r for r in rows if r.get("stratum") == a.stratum]
    # 등록부 근거가 **있는** 쌍만 남긴다.
    #
    #   실측 사고: --limit 5 로 시운전했더니 그 5쌍 전부 독립 시험이 0건이라
    #   B6가 아무것도 못 했다. B6가 못 한 게 아니라 **시험할 재료가 없는
    #   표본을 고른 것**이다. 앞에서 N쌍 자르기는 대표성이 없다.
    #   ceiling이 이미 어느 쌍에 근거가 있는지 안다. 그걸 쓴다.
    if a.with_registry:
        try:
            has = {(r["drug"], r["indication"])
                   for r in csv.DictReader(open(a.with_registry,
                                                encoding="utf-8-sig"))
                   if (r.get("usable_ncts") or "").strip()}
        except Exception as e:
            print("ceiling 결과를 읽을 수 없다: %s" % e)
            return 1
        # 짝을 통째로 남긴다 — TN만 남기면 짝짓기가 깨진다
        keep_idx = set()
        for i in range(0, len(rows) - 1, 2):
            if (rows[i]["drug"], rows[i]["indication"]) in has:
                keep_idx |= {i, i + 1}
        rows = [r for i, r in enumerate(rows) if i in keep_idx]
        print("  [선별] 등록부 독립 시험이 있는 쌍만 → %d쌍" % (len(rows) // 2))
    if a.limit:
        # 짝을 유지한 채로 앞에서 N쌍만 (TN, TP가 번갈아 저장돼 있다)
        rows = rows[:a.limit * 2]
    tn = [r for r in rows if r["label"] == "TN"]
    tp = [r for r in rows if r["label"] == "TP"]

    # **캐시를 여기서 읽는다 — set_exclude 보다 먼저.**
    #
    #   `set_exclude` 는 NCT→PMID 확장을 위해 PubMed을 조회한다. 그런데
    #   `cache.configure`/`load` 가 한참 아래(전처리 뒤)에 있었다.
    #   그래서 `_STORE` 가 빈 dict 인 채로 조회가 시작되고, 자동 저장이
    #   걸리는 순간 **디스크의 캐시를 그만큼으로 덮었다.**
    #
    #   2026-08-05 `io.cache.save()` 에 병합 방어를 넣고서야 드러났다
    #   ("읽지 않고 저장하려 했다"가 실행 내내 찍혔다). 방어가 없었다면
    #   `bench.run` 을 돌릴 때마다 캐시가 조용히 날아갔을 것이다.
    #
    #   방어에 기대지 말고 순서를 바로잡는다. 병합은 매번 파일 전체를
    #   다시 읽으므로 호출이 많은 실행에서는 그 자체가 비용이다.
    cache.configure(a.cache)
    cache.load()

    # 라벨의 출처가 된 시험을 근거로 쓰면 답을 알려주는 것이다.
    excl = None
    if not a.allow_label_nct:
        excl = gates.set_exclude({r["nct"] for r in rows
                                  if str(r.get("nct", "")).startswith("NCT")})

    print("=" * 78)
    print("벤치마크 실측 — 층 %s · TN %d · TP %d" % (a.stratum, len(tn), len(tp)))
    if TIER2:
        ys = [c.cutoff_year for c in map(to_candidate, rows) if c.cutoff_year]
        print("  [Tier 2 시점 차단] 예측 지평 %d년 · 컷오프 %s~%s · 적용 %d/%d건"
              % (TIER2_GAP, min(ys) if ys else "-", max(ys) if ys else "-",
                 len(ys), len(rows)))
        print("      지평이 길수록 '예측'에 가깝다. 1년은 결과 직전, 5년은 설계 무렵이다.")
    if gates.EXCLUDE_NCT:
        print("  [누출 차단] 라벨 출처 시험 %d건" % len(gates.EXCLUDE_NCT))
        if excl:
            # NCT만 막으면 초록에 등록번호를 안 쓴 그 시험의 논문이 통과한다.
            #   실측에서 그런 누출이 2건 확인됐다. PMID까지 확장해 막는다.
            print("               + 그 시험의 논문 %d건(PMID 색인)도 제외"
                  % excl["pmids"])
            print("               ※ [si] 미색인 %d건은 이 방법으로 못 막는다 — "
                  "차단은 **하한**이다" % excl["no_index"])
    print("=" * 78)
    if not tn or not tp:
        print("표본이 없다. --stratum 을 확인하라.")
        return 1

    # ── 비용 추정 ─────────────────────────────────────────────
    n = len(rows)

    # 비용을 표에 적어두면 구성을 추가할 때마다 잊는다.
    #   실제로 B6를 추가하고 표를 안 고쳐 비용이 과소 추정됐다.
    #   켜진 게이트에서 직접 계산한다.
    def cost(cfg):
        g = gates.CONFIGS.get(cfg, {})
        if cfg == "B0":
            return max(1, n // 12)          # 폐쇄형은 12건씩 묶는다
        c = 0
        if g.get("rag"):
            c += n                          # 후보당 초록 묶음 1회
        if g.get("router"):
            c += max(1, n // 12)            # 기전 분류도 묶음
        if g.get("skeptic"):
            c += n                          # 추가 회수분 1회
        if g.get("registry"):
            c += n                          # 등록부 결과 1회
        if g.get("fulltext"):
            # 09-15 · F — 후보당 **1회**. 한계 절 최대 3편을 **묶어서**
            #   한 번에 묻는다(`agents/limits.judge`). 건마다 부르면 3회다.
            #   ⚠ 이 줄을 빼면 **B5F 비용이 B5 와 같게 나와** 명세 §6
            #     («후보당 2~4배») 검산이 통째로 무의미해진다.
            c += n
        return c or n

    total = sum(cost(c) for c in a.configs)
    per = " · ".join("%s %d" % (c, cost(c)) for c in a.configs)
    print("\n[비용 추정] 후보 %d개 → LLM 호출 최대 %d회" % (n, total))
    print("  구성별: %s" % per)
    # ⚠ **«실제로는 더 적다» 를 무조건 찍으면 안 된다** — 09-12.
    #   모델을 바꾸면 캐시 키(`LLM::{모델}::…`)가 통째로 달라져 **적중이
    #   0** 이 된다. 그때도 저 문장을 찍으면 화면이 **비용을 낮게 보이게
    #   거짓말**한다. 세어서 말한다.
    try:
        from ..io import cache as _cache, llm as _llm
        _cache.load()
        _pre = "LLM::%s::" % _llm.MODEL
        _hit = sum(1 for k in _cache._STORE if k.startswith(_pre))
        if _hit:
            print("  현재 모델 캐시 %d건 — **적중분만큼 실제 호출은 준다**"
                  % _hit)
        else:
            print("  ⚠ 현재 모델(%s) 캐시 **0건** — 적중 기대 없음."
                  % _llm.MODEL)
            print("     **위 수가 곧 실제 호출 수다.** 옛 모델 캐시는")
            print("     키가 달라 안 쓰인다(그게 맞다 — 다른 시스템이다).")
    except Exception as _e:
        print("  (캐시 적중 확인 실패: %s — 위 수는 상한이다)" % _e)
    # 예산 경고를 --dry 뒤에 두면 **비용 확인하러 돌린 사람이 못 본다.**
    #   실측: --dry가 "441회"라고만 찍고 끝나서, 본 실행에서야
    #   상한 60에 걸려 시작도 못 하는 것을 알게 됐다.
    #   미리 알려주는 게 --dry의 존재 이유다.
    if total > llm.MAX_CALLS:
        print("\n  [예산] 현재 상한 %d회 < 필요 %d회 — **이대로는 시작도 못 한다.**"
              % (llm.MAX_CALLS, total))
        print("       PowerShell:  $env:BIOREROUTE_MAX_CALLS=%d" % (total + 50))
        print("       상한은 사고 방지용이다. 끄지 말고 필요한 만큼만 올려라.")
    if a.dry:
        print("\n--dry 이므로 여기서 멈춘다.")
        return 0
    if total > llm.MAX_CALLS:
        print("  [경고] 예산 상한 %d회를 넘는다. BIOREROUTE_MAX_CALLS 를 올려라."
              % llm.MAX_CALLS)
        print("         지금 진행하면 도중에 BUDGET_EXCEEDED 로 끊긴다.")
        return 1

    # LLM이 없으면 rag 게이트가 **조용히** 건너뛰어진다.
    #   그런데 파이프라인은 끝까지 돌고 AUROC 표까지 정상적으로 출력한다.
    #   실측 사고: 키 없이 돌려 전부 `보류` → AUROC 0.500 이 나왔는데
    #   화면 어디에도 "LLM을 한 번도 안 불렀다"는 말이 없었다.
    #   숫자가 그럴듯하면 사람은 그걸 결과로 믿는다. 여기서 끊는다.
    if total > 0 and not llm.available():
        print("\n  [중단] LLM을 쓸 수 없다. 그런데 요청한 구성은 LLM이 필요하다.")
        print("         이대로 돌리면 팩트체크가 통째로 건너뛰어지고,")
        print("         전부 '보류'가 되어 **AUROC 0.500 짜리 가짜 결과표**가 나온다.")
        print("         원인: litellm 미설치 또는 API 키 미설정")
        print("           py -m bioreroute.diag   로 확인하라.")
        return 1

    # 캐시는 위(set_exclude 앞)에서 이미 읽었다. 여기서 다시 configure 하면
    #   `_LOADED` 표시가 지워져 이후 저장마다 병합 경로를 타게 된다.
    if not a.skip_preflight and not preflight(rows):
        print("\n중단한다. --skip-preflight 로 강행할 수 있으나 권하지 않는다.")
        return 1
    stamp = time.strftime("%Y-%m-%d %H:%M")
    labels = [1 if r["label"] == "TP" else 0 for r in rows]
    results = {}

    # ── B0: 폐쇄형 (문헌 없이 기억으로만) ──────────────────────
    if "B0" in a.configs:
        print("\n[B0] 폐쇄형 — 문헌 없이 모델 기억으로만")
        probe = closedbook.probe([{"drug": r["drug"], "indication": r["indication"]}
                                  for r in rows])
        scores = [closedbook.to_score(p) for p in probe]
        leaks = [closedbook.leakage_flag(p, r["label"])
                 for p, r in zip(probe, rows)]
        known = sum(1 for p in probe if p["verdict"] != "모름")
        correct = sum(1 for p, r in zip(probe, rows)
                      if (p["verdict"] == "실패") == (r["label"] == "TN")
                      and p["verdict"] != "모름")
        results["B0"] = {"scores": scores, "leak": leaks,
                         "verdicts": [p["verdict"] for p in probe],
                         "conf": [p["confidence"] for p in probe]}
        print("  응답 %d/%d (모름 %d)" % (known, len(rows), len(rows) - known))
        if known:
            lo, hi = wilson(correct, known)
            print("  아는 것 중 정답 %d/%d = %.0f%%  [95%% CI %.0f–%.0f%%]"
                  % (correct, known, 100 * correct / known, 100 * lo, 100 * hi))
        nl = sum(leaks)
        print("  누출 의심(라벨과 일치 + 고확신) %d/%d = %.0f%%"
              % (nl, len(rows), 100 * nl / len(rows)))
        if nl > len(rows) * 0.2:
            print("     → 5건 중 1건 이상을 외우고 있다. 전체 시스템 성적을")
            print("        '근거를 읽어서'라고 해석하면 안 된다. 누출 제외 부분집합을")
            print("        따로 보고해야 한다.")

    # ── 파이프라인 구성들 ─────────────────────────────────────
    for cfg in a.configs:
        if cfg == "B0":
            continue
        print("\n[%s] %s" % (cfg, ",".join(k for k, v in gates.CONFIGS[cfg].items() if v)))
        st = run_config(rows, cfg, stamp)
        # F0 결과가 라벨별로 치우치면 그 자체가 공짜 신호가 된다.
        # TN만 문헌이 없어 기각되면 실력이 아니라 데이터 편향이다.
        f0k = {"TP": 0, "TN": 0}
        f0z = {"TP": 0, "TN": 0}
        for c, r in zip(st.candidates, rows):
            for t in c.trail:
                if t.gate == "f0" and t.outcome == "KILL":
                    f0k[r["label"]] += 1
                elif t.gate == "f0" and t.outcome == "FLAG":
                    f0z[r["label"]] += 1
        if any(f0k.values()) or any(f0z.values()):
            print("  F0 기각(환각) TP %d · TN %d | 연결0건 TP %d · TN %d"
                  % (f0k["TP"], f0k["TN"], f0z["TP"], f0z["TN"]))
            if abs(f0z["TN"] - f0z["TP"]) > max(3, 0.1 * len(rows)):
                print("     [주의] 연결 문헌 부재가 한쪽에 치우쳤다.")
                print("            성능 일부가 실력이 아니라 문헌 부재에서 나온다.")

        # 등록부 게이트가 **실제로 무엇을 했는지** 반드시 찍는다.
        #
        #   실측 사고: B6 판정 분포가 B5와 한 글자도 다르지 않게 나왔는데,
        #   화면 어디에도 등록부가 시험을 몇 건 읽었는지가 없었다.
        #   "게이트가 안 붙었나, 붙었는데 판정이 안 바뀌었나"를 구분할 수 없었다.
        #   **둘은 완전히 다른 문제다.** 앞은 버그, 뒤는 결과다.
        if st.config.get("registry"):
            n_done = n_none = n_err = n_ev = n_excl = 0
            for c in st.candidates:
                for t in c.trail:
                    if t.gate != "registry":
                        continue
                    if t.outcome == "DONE":
                        n_done += 1
                    elif t.outcome in ("NONE", "SKIP"):
                        n_none += 1
                    elif t.outcome == "ERROR":
                        n_err += 1
                    if "라벨 출처" in (t.detail or ""):
                        n_excl += 1
            n_ev = sum(1 for c in st.candidates
                       for r in (c.factcheck or [])
                       if r.get("source") == "ctgov")
            n_kept = sum(1 for c in st.candidates
                         for r in (c.factcheck or [])
                         if r.get("source") == "ctgov" and r.get("kept"))
            print("  등록부: 근거 확보 %d후보 · 없음 %d · 오류 %d"
                  % (n_done, n_none, n_err))
            print("          시험 %d건 읽음 → 채택 %d건 (라벨 출처 제외 발생 %d후보)"
                  % (n_ev, n_kept, n_excl))
            if n_ev == 0:
                print("     [주의] **등록부가 시험을 한 건도 못 읽었다.**")
                print("            B6는 B5와 같아질 수밖에 없다. 성능 차이가 없는 게")
                print("            아니라 애초에 다른 일을 하지 않은 것이다.")
                print("            bench.ceiling --stratum 으로 독립 시험 유무를 확인하라.")
            elif n_kept == 0:
                print("     [주의] 시험은 읽었는데 **채택된 근거가 0건**이다.")
                print("            인용 검증·관련성·운영중단 방어 중 하나가 전부 걸렀다.")
                print("            --save-state 로 판정 원본을 남겨 확인하라.")
        sc, vd, tr = [], [], []
        for c in st.candidates:
            p = c.confidence
            sc.append(0.5 if p is None else p / 100.0)
            vd.append(c.verdict)
            tr.append(trail_summary(c))
        results[cfg] = {"scores": sc, "verdicts": vd, "trail": tr}
        if a.save_state:
            # ── ⚠ 08-18 결함 224 — **마지막 구성만 남기고 있었다** ──────
            #
            #   앞판은 `cfg == a.configs[-1]` 이었다. 그래서 B5·B6 를 돌린
            #   08-15 밤 실행에서 **B6 상태만 남고 B5 가 사라졌다.**
            #   명세 `e79b641b` 의 주지표가 **B5→B6 짝비교**인데
            #   짝의 한쪽이 없었다.
            #
            #   이번엔 불일치가 0건이라 결론이 안 바뀌었다. **운이었다** —
            #   뒤집힘이 있었으면 «어느 게이트가 뒤집었나» 를 못 봤다.
            #
            #   구성이 둘 이상이면 **파일명에 구성을 붙여 각각 남긴다.**
            #   하나면 준 이름 그대로 쓴다(기존 호출을 안 깬다).
            import json as _j
            import os as _o
            _sp = a.save_state
            if len(a.configs) > 1:
                _b, _e = _o.path.splitext(a.save_state)
                _sp = "%s_%s%s" % (_b, cfg, _e or ".json")
            # f0·veto·trail 까지 남긴다. 이게 없으면 저장된 상태만으로는
            #   **판정을 다시 계산할 수 없다.** 다시 계산할 수 없으면
            #   "등록부 근거를 빼면 판정이 어떻게 되나" 같은 질문에
            #   답하려고 매번 실제 실행을 다시 해야 한다 — 비싸고 느리다.
            _j.dump({"config": cfg, "candidates": [
                {"name": c.name, "drug": c.drug, "disease": c.disease,
                 "label": r["label"],
                 "verdict": c.verdict, "confidence": c.confidence,
                 "reason": c.reason, "f0": c.f0 or {},
                 "veto": c.veto, "veto_reason": c.veto_reason,
                 "trail": [{"gate": t.gate, "outcome": t.outcome,
                            "detail": t.detail} for t in c.trail],
                 "factcheck": c.factcheck or []}
                for c, r in zip(st.candidates, rows)]},
                open(_sp, "w", encoding="utf-8"),
                ensure_ascii=False, indent=1)
            print("  판정 원본 저장: %s%s"
                  % (_sp, "  (구성이 %d개라 이름에 구성을 붙였다)"
                     % len(a.configs) if len(a.configs) > 1 else ""))
        f = llm.failure_summary()
        print("  판정 분포: " + " · ".join(
            "%s %d" % (k, vd.count(k)) for k in ("유망", "조건부", "보류", "기각")))
        if f["failed"]:
            print("  [경고] LLM 실패 %d회 — 결과가 오염됐을 수 있다" % f["failed"])
        cache.save()

    # ── 표 ────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("결과 — 층 %s (TP %d · TN %d)" % (a.stratum, len(tp), len(tn)))
    print("=" * 78)
    print("  %-6s %-22s %-16s %-16s %s"
          % ("구성", "AUROC [95% CI]", "기각 정밀도", "기각 재현율", "ECE"))
    print("  %-6s %-22s %-16s %-16s"
          % ("", "", "TN기각/전체기각", "TN기각/TN총수"))
    print("  " + "-" * 74)
    for cfg in a.configs:
        r = results.get(cfg)
        if not r:
            continue
        au = auroc(r["scores"], labels)
        lo, hi = auroc_ci(au, sum(labels), len(labels) - sum(labels))
        if cfg == "B0":
            rej = [v == "실패" for v in r["verdicts"]]
        else:
            rej = [v == "기각" for v in r["verdicts"]]
        tp_rej = sum(1 for x, l in zip(rej, labels) if x and l == 0)
        n_rej = sum(rej)
        n_neg = len(labels) - sum(labels)
        prec = tp_rej / n_rej if n_rej else None
        rec = tp_rej / n_neg if n_neg else None
        e = ece(r["scores"], labels)
        # ── ⛔ 09-20 · **재현율도 분수를 찍는다** ─────────────────────
        #
        #   앞판은 정밀도만 `(95/106)` 을 찍고 재현율은 `25%` 만 찍었다.
        #   화면에 나란히 놓이면 사람이 **재현율의 분모를 옆에서 가져온다** —
        #   실제로 그랬다. `홀드아웃결과.md` 가 7주 동안
        #   *«106/387»* 을 기각 재현율로 적고 있었다. **분자가 틀렸다**
        #   (106 = TN기각 95 + **TP기각 11**). 그 값이 발표대본·발표뼈대·
        #   연구기술보고서까지 번졌다.
        #
        #   개발집합 84쌍은 **TP 기각이 0건**이라 두 정의가 우연히 같은
        #   수를 냈다. 그래서 작은 표본에서는 영영 안 드러난다.
        #
        #   **둘 다 분수를 찍으면 분자가 같은 95 임이 눈에 보인다.**
        #   안내문이 아니라 화면이 막는다 — `CLAUDE.md` 머리글.
        print("  %-6s %-22s %-16s %-16s %s"
              % (cfg,
                 "%.3f [%.2f–%.2f]" % (au, lo, hi) if au is not None else "—",
                 ("%.0f%% (%d/%d)" % (100 * prec, tp_rej, n_rej)) if prec is not None else "—",
                 ("%.0f%% (%d/%d)" % (100 * rec, tp_rej, n_neg)) if rec is not None else "—",
                 "%.3f" % e if e is not None else "—"))

    # ── 누출 제외 재계산 ──────────────────────────────────────
    if "B0" in results:
        keep = [i for i, x in enumerate(results["B0"]["leak"]) if not x]
        if keep and len(keep) < len(rows):
            kl = [labels[i] for i in keep]
            print("\n  [누출 제외 %d건] — 모델이 외우지 않은 항목만" % len(keep))
            for cfg in a.configs:
                r = results.get(cfg)
                if not r:
                    continue
                ks = [r["scores"][i] for i in keep]
                au = auroc(ks, kl)
                lo, hi = auroc_ci(au, sum(kl), len(kl) - sum(kl))
                print("    %-6s AUROC %s" % (cfg, "%.3f [%.2f–%.2f]" % (au, lo, hi)
                                             if au is not None else "—"))

    # 같은 행 집합에 대한 앞선 구성 결과는 살린다.
    #   행이 다르면(--limit·--stratum이 바뀌었으면) 섞으면 안 된다 — 버린다.
    keep = {}
    if lost:
        same_rows = (prev.get("rows") == [{"drug": r["drug"],
                                           "indication": r["indication"],
                                           "label": r["label"]} for r in rows]
                     and prev.get("stratum") == a.stratum)
        if same_rows:
            keep = {k: v for k, v in (prev.get("results") or {}).items() if k in lost}
            print("\n  [이어붙임] 같은 행 집합의 앞선 구성 %s 을(를) 유지한다."
                  % ", ".join(sorted(keep)))
        else:
            print("\n  [주의] 결과 파일에 %s 이(가) 있었으나 **행 집합이 달라 버린다.**"
                  % ", ".join(sorted(lost)))
            print("         --limit·--stratum 이 바뀌면 같은 파일에 섞을 수 없다.")
            print("         비교하려면 두 실행의 조건을 맞춰서 다시 돌려야 한다.")
            print("         ↳ **앞 판은 `%s.bak` 에 남는다.**" % a.out)
    merged = dict(keep)
    merged.update(results)
    # ── ⚠ 08-18 결함 223 — **덮어쓰기 전에 `.bak` 을 남긴다** ──────────
    #
    #   `CLAUDE.md §3-3` 이 *"결과 파일을 확인 없이 덮어쓰지 마라
    #   (`--out` 기본값 주의)"* 라고 적어 뒀는데, **경고만 있고 백업이
    #   없었다.** 08-15 밤에 스크립트가 `--out` 을 안 줘서 08-04 판
    #   `bench_results.json`(17 KB · B0 포함)이 그대로 사라졌다.
    #
    #   위 `[주의] … 버린다` 는 **버린다고 말만 했지 어디에도 안 남겼다.**
    #   `io/fto._write_json` 은 같은 상황에서 `.bak` 을 남긴다 —
    #   **같은 병에 방어가 한 곳에만 있었다**(결함 98 계열).
    #
    #   되돌릴 수 있게 한 판 남긴다. **`io/safeio` 하나만 쓴다** — 여기
    #   따로 만들면 같은 방어가 두 곳이 되고 그게 결함 98·222 다.
    from ..io.safeio import save_json as _save_json
    # ── ⚠ 09-13 · **토큰을 저장한다** ────────────────────────────────
    #
    #   09-12에 182회를 돌리고도 **토큰을 못 쟀다.** `llm.tokens_spent()`
    #   를 만들어 놓고 **결과 파일에 남기는 배선을 안 넣어서**, 프로세스가
    #   끝나며 `_CALLS` 가 통째로 날아갔다. 배점 15점(«크레딧 대비 결과»)
    #   의 원자료를 **한 번 통째로 버린 것**이다.
    #
    #   「만들고 안 태운」 것의 변종이다 — 만들었고, 돌기도 했는데,
    #   **결과를 안 남겼다.** 08-14·08-18·08-31·09-01 과 같은 계열.
    try:
        from ..io import llm as _llm
        _tok = _llm.tokens_spent()
        _tok["모델"] = _llm.MODEL
        _tok["seed"] = _llm.SEED or None
        _tok["프록시"] = bool(_llm.API_BASE)
    except Exception as _e:
        _tok = {"오류": "%s: %s" % (type(_e).__name__, _e)}
    _bak = _save_json({"stratum": a.stratum, "n_tp": len(tp), "n_tn": len(tn),
               "rows": [{"drug": r["drug"], "indication": r["indication"],
                         "label": r["label"]} for r in rows],
               "results": merged, "토큰": _tok},
              a.out, indent=1)
    if isinstance(_tok, dict) and "총토큰" in _tok:
        print("\n[토큰] 총 %s (입력 %s · 출력 %s) · 계량된 호출 %s"
              % (_tok["총토큰"], _tok["입력"], _tok["출력"], _tok["계량된_호출"]))
        if _tok.get("계량_안된_호출"):
            # ⚠ 0 으로 밀지 않는다 — «안 썼다» 와 «모른다» 는 다르다.
            print("  ⚠ **계량 안 된 호출 %d건** — 응답에 usage 가 없었다."
                  % _tok["계량_안된_호출"])
            print("     위 합계는 **하한**이다. 0으로 세지 마라.")
        print("  캐시 적중 %d건 (토큰 0)" % _tok.get("캐시적중", 0))

    # ── **깔때기 비용 곡선** — 09-16 · `사전명세_비용곡선.md` ────────────
    #
    #   총합만으로는 *"값싼 게이트를 앞에 뒀다"* 를 증명하지 못한다.
    #   단계별 귀속은 `llm.cost_report()` 가 내고, 이 옵션이 그걸 파일로
    #   남긴다. **`--cost-out` 을 안 주면 아무 일도 안 한다.**
    #
    #   ⚠ 캐시가 살아 있으면 토큰이 0으로 나온다 — «공짜다» 가 아니라
    #     «못 쟀다» 이다. 재려면 `BIOREROUTE_BYPASS_CACHE=1` 이 필요하고,
    #     그때는 **판정이 달라질 수 있으므로 비용만 쓴다**(명세 §4).
    if getattr(a, "cost_out", ""):
        # ⚠ `_llm` 은 위 `try:` 안에서 잡혔다 — 거기서 터졌으면 없다.
        #   **여기서 다시 잡는다.** 이름이 살아 있겠거니 하면 결함이 된다.
        from ..io import llm as _llm
        _rep = _llm.cost_report()
        _rep["실행"] = {"구성": sorted(merged), "n쌍": len(tp),
                      "캐시우회": bool(_llm.BYPASS_CACHE)}
        _cw = _save_json(_rep, a.cost_out, indent=1)
        _mi = _rep["단계별"].get("미상", {}).get("호출", 0)
        _all = sum(v["호출"] for v in _rep["단계별"].values()) or 1
        print("\n[비용곡선] → %s" % _cw.get("경로", a.cost_out))
        for k, v in sorted(_rep["단계별"].items(),
                           key=lambda x: -x[1]["호출"]):
            print("   %-14s 호출 %3d · 캐시 %3d · 토큰 %7d%s"
                  % (k, v["호출"], v["캐시"], v["토큰"],
                     "  ⚠ 계량안됨 %d" % v["계량_안됨"] if v["계량_안됨"] else ""))
        if _mi:
            # 명세 §2 R3 — 「미상」 5% 초과면 **수치를 발표에 쓰지 않는다**
            print("   ⚠ **「미상」 %d건 (%.1f%%)** — 5%% 를 넘으면 명세 R3 에 걸린다."
                  % (_mi, 100.0 * _mi / _all))
        if not _llm.BYPASS_CACHE:
            print("   ⚠ **캐시를 안 우회했다** — 토큰 0은 «공짜» 가 아니라 «못 쟀다» 다.")
    if _bak.get("원본유지"):
        print("\n⚠ **백업을 못 해서 원본을 안 덮었다** → %s" % _bak["경로"])
        print("   %s" % _bak["상태"])
        print("   **`%s` 는 앞 판 그대로다.** 확인하고 손으로 옮겨라." % a.out)
    else:
        print("\n저장: %s  (구성 %s)%s"
              % (a.out, ", ".join(sorted(merged)),
                 "  · 앞 판은 %s" % _bak["백업"] if _bak.get("백업") else ""))
    print("=" * 78)
    print("해석 원칙")
    print("  · B5가 B0보다 낫지 않으면 파이프라인이 값을 못 한 것이다.")
    print("  · B0가 이미 잘 맞히면 그건 외운 것이다. 누출 제외 수치를 봐야 한다.")
    print("  · n이 작으므로 점추정이 아니라 신뢰구간으로 말한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
