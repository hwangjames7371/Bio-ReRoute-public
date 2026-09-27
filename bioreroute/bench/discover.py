# -*- coding: utf-8 -*-
"""생성 실험 — 발굴기가 만든 후보를 **이미 아는 사실**과 대조한다.

    py -m bioreroute.bench.discover --auto 12 --k 20 --out gen_run1.csv

## 무엇을 묻는가

이 프로젝트의 논지는 하나다.

    병목은 후보를 만드는 일이 아니라, 그럴듯하지만 틀린 후보를
    값싸게 걸러내는 일이다.

지금까지 이걸 **주장만** 했다. 후보가 사람이 쓴 5개뿐이라 버리는 장면이
안 나왔다. 이 실험이 그 자리를 메운다.

    LLM에 질환 D의 재창출 후보 K개를 시킨다.
      → 그중 몇 개가 **이미 효능 실패로 중단된 시험의 약**인가?

이건 HCQ 서사(제안서 §1.1)의 정량판이다. *"결정적 반박이 나온 뒤에도
시험이 계속 등록됐다"* 를, 생성기가 반박된 후보를 다시 내놓는 비율로 잰다.

## 무엇이 이 실험을 반증하는가 — **먼저 적는다**

논지를 지지하는 결과만 세면 실험이 아니다. 다음이 나오면 **논지가 약해진다.**

  · 생성 후보 중 `효능실패` 비율이 무작위 기준선과 **구별되지 않는다**
    → 생성기는 반박된 후보를 특별히 더 내놓지 않는다. 거를 게 별로 없다.
  · `승인` 비율이 매우 높다
    → 생성기는 발견을 하는 게 아니라 **교과서를 외워 읊는** 것이다.
      후보의 신규성이 없으니 "생성이 값싸다"는 말도 공허해진다.
  · strict 와 loose 의 차이가 없다
    → 프롬프트의 신중함이 무의미하다는 뜻이고, 그러면 "생성기를 다그치면
      된다"는 반론이 성립하지 않는다는 우리 주장의 근거도 같이 사라진다.

세 번째가 특히 중요하다. **양쪽 프롬프트를 다 돌리는 이유가 그것이다** —
한쪽만 돌리면 프롬프트 한 줄로 결론을 만들어낼 수 있다.

## 채점의 한계 — 과장하지 않는다

1. **`미지` 는 "신규 후보"가 아니라 "우리 자료에 없다"이다.**
   RepoDB(2017년경)와 우리 TN풀(CT.gov 종료 시험)은 세상의 부분집합이다.
2. **생성기의 학습자료에 RepoDB 시대의 승인 정보가 들어 있다.**
   그러므로 `승인` 적중은 발견이 아니라 회상일 수 있다. 그렇게 읽는다.
3. **약물명 대조는 엄격하게 맞춘다**(염·수화물만 제거한 완전일치).
   느슨하게 맞추면 없는 적중이 생긴다. 엄격하면 적중을 **놓친다** —
   즉 이 수치는 **하한**이고, 편향 방향은 논지에 불리한 쪽이다.
"""

import argparse
import csv
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

from ..core.state import RunState
from ..core import gates
from ..io import cache, llm
from . import labels as L
from .stats import binom_ge, fisher, fmt_p, power1, power2, wilson

# ── 약물명 정규화 ─────────────────────────────────────────
# 염·에스터·수화물은 같은 약이다. 그 외에는 **다른 약으로 본다** —
# 거울상체 접두어(dex-·levo-·es-)를 지우면 안 된다. 다른 화합물이다.
_SALT = {
    "hydrochloride", "hcl", "hydrobromide", "sodium", "disodium", "potassium",
    "calcium", "magnesium", "sulfate", "sulphate", "phosphate", "diphosphate",
    "acetate", "citrate", "tartrate", "bitartrate", "maleate", "mesylate",
    "mesilate", "besylate", "besilate", "fumarate", "hemifumarate", "succinate",
    "tosylate", "bromide", "chloride", "nitrate", "oxalate", "malate", "lactate",
    "gluconate", "carbonate", "pamoate", "palmitate", "propionate", "valerate",
    "dipropionate", "furoate", "xinafoate", "trihydrate", "dihydrate",
    "monohydrate", "hydrate", "anhydrous", "salt", "base", "free",
}


def drug_key(s: str) -> str:
    """대조용 약물 키. 염·수화물·용량 표기만 지운다."""
    t = re.sub(r"\([^)]*\)", " ", (s or "").lower())
    toks = [w for w in re.split(r"[^a-z0-9]+", t) if w]
    keep = [w for w in toks if w not in _SALT and not w.isdigit()
            and not re.fullmatch(r"\d+(mg|mcg|g|ml|iu|%)", w)]
    return "".join(keep or toks)


# ── 자료 적재 ─────────────────────────────────────────────
def load_universe(repodb="RepoDB.csv", tnpool="bench_tn_pool_v2.csv"):
    """질환별 승인/중단/효능실패 약물 집합 + 전체 약물 어휘."""
    repo = list(csv.DictReader(open(repodb, encoding="utf-8-sig")))
    tn = list(csv.DictReader(open(tnpool, encoding="utf-8-sig")))

    names = [r["ind_name"] for r in repo] + [r["condition"] for r in tn]
    L.index_tokens(names)                       # 토큰 희귀도 — same_disease 가 쓴다

    appr, stop, fail = [], [], []
    for r in repo:
        tok = L.ind_tokens(r["ind_name"])
        rec = (tok, drug_key(r["drug_name"]), r["drug_name"], r["ind_name"])
        (appr if r["status"] == "Approved" else stop).append(rec)
    for r in tn:
        fail.append((L.ind_tokens(r["condition"]), drug_key(r["drug"]),
                     r["drug"], r["condition"], r.get("nct", "")))

    vocab = sorted({k for _, k, _, _ in appr + stop} |
                   {k for _, k, _, _, _ in fail})
    return {"appr": appr, "stop": stop, "fail": fail, "vocab": vocab,
            "n_repo": len(repo), "n_tn": len(tn)}


def sets_for(uni, disease):
    """질환 하나에 대한 (승인, 중단, 효능실패) 약물 키 집합."""
    dt = L.ind_tokens(disease)
    a = {k for tok, k, _, _ in uni["appr"] if L.same_disease(dt, tok)}
    s = {k for tok, k, _, _ in uni["stop"] if L.same_disease(dt, tok)}
    f = {k for tok, k, _, _, _ in uni["fail"] if L.same_disease(dt, tok)}
    return a, s, f


def label_of(key, a, s, f):
    """우선순위: 승인 > 효능실패 > 중단 > 미지.

    승인을 맨 앞에 두는 이유 — 같은 쌍이 과거 실패 시험과 현재 승인을
    둘 다 가질 수 있다(재시도 후 승인). 그때 강한 사실은 승인이다.
    겹침 건수는 따로 세어 보고한다.
    """
    if key in a:
        return "승인"
    if key in f:
        return "효능실패"
    if key in s:
        return "중단"
    return "미지"


def pick_diseases(uni, n, min_tn=3, min_appr=3):
    """TN·승인이 둘 다 있는 질환을 TN 많은 순으로 고른다.

    양쪽이 다 있어야 적중과 오적중을 같은 질환 안에서 비교할 수 있다.
    한쪽만 있는 질환을 섞으면 질환 구성이 곧 결과가 된다.
    """
    by = defaultdict(int)
    for tok, k, _, cond, _ in uni["fail"]:
        by[cond] += 1
    rows = []
    for cond, n_tn in by.items():
        if n_tn < min_tn:
            continue
        a, _, f = sets_for(uni, cond)
        if len(a) >= min_appr:
            rows.append((n_tn, len(a), cond))
    rows.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [c for _, _, c in rows[:n]]


# ── 무지성 기준선 ─────────────────────────────────────────
def trivial_baseline(uni, diseases, k, trials=2000, seed=20260805):
    """약물 어휘에서 **아무거나** k개 뽑으면 몇 개나 맞는가.

    이건 **바닥값이지 경쟁 상대가 아니다.** 무작위 이름 대기는 그럴듯한
    후보를 내지 않으므로, 이 값을 넘었다고 발굴기가 훌륭한 것은 아니다.
    이 기준선이 답하는 질문은 하나뿐이다 —
    **`효능실패` 적중이 우연히 나올 수 있는 수준인가?**
    """
    rnd = random.Random(seed)
    vocab = uni["vocab"]
    tot = {"승인": 0, "효능실패": 0, "중단": 0, "미지": 0}
    n = 0
    pre = [sets_for(uni, d) for d in diseases]
    for _ in range(trials):
        for a, s, f in pre:
            for key in rnd.sample(vocab, min(k, len(vocab))):
                tot[label_of(key, a, s, f)] += 1
                n += 1
    return {kk: v / n for kk, v in tot.items()}, n


# ── 실행 ──────────────────────────────────────────────────
COLS = ["disease", "variant", "drug", "drug_key", "label", "evidence_level",
        "gen_confidence", "mechanism", "rationale"]


def generate(diseases, k, variant, model=None):
    st = RunState(query_title="발굴 실험", settings=variant, stamp="",
                  candidates=[], config={},
                  discover={"diseases": diseases, "k": k,
                            "variant": variant, "model": model})
    st = gates.gate_discover(st)
    return st


def main(argv=None):
    ap = argparse.ArgumentParser(description="생성 실험 — 발굴기 후보를 기존 사실과 대조")
    ap.add_argument("--disease", action="append", default=[],
                    help="질환명. 여러 번. 없으면 --auto")
    ap.add_argument("--auto", type=int, default=0, help="TN 많은 순으로 N개 자동 선택")
    ap.add_argument("--k", type=int, default=20, help="질환당 요청 후보 수")
    ap.add_argument("--variant", action="append", default=[],
                    choices=["strict", "loose"], help="기본: 둘 다")
    ap.add_argument("--model", default=None, help="생성기 모델(검증기와 분리하려면 지정)")
    ap.add_argument("--cache", default="pubmed_cache.json")
    ap.add_argument("--repodb", default="RepoDB.csv")
    ap.add_argument("--tnpool", default="bench_tn_pool_v2.csv")
    ap.add_argument("--out", required=True, help="결과 CSV. 이미 있으면 거부한다")
    ap.add_argument("--force", action="store_true", help="덮어쓰기 허용")
    a = ap.parse_args(argv)

    # 결과 파일을 말없이 덮어쓰지 않는다 (CLAUDE.md §3-3)
    if os.path.exists(a.out) and not a.force:
        print("이미 있는 파일이다: %s\n  덮어쓰려면 --force 를 붙여라." % a.out)
        return 2

    cache.configure(a.cache)
    cache.load()                    # **질의 전에** 읽는다 (결함 26·27)

    uni = load_universe(a.repodb, a.tnpool)
    diseases = list(a.disease)
    if a.auto:
        diseases += [d for d in pick_diseases(uni, a.auto) if d not in diseases]
    if not diseases:
        print("질환이 없다. --disease 또는 --auto 를 써라.")
        return 1
    variants = a.variant or ["strict", "loose"]

    print("자료  RepoDB %d행 · TN풀 %d행 · 약물 어휘 %d개"
          % (uni["n_repo"], uni["n_tn"], len(uni["vocab"])))
    print("질환  %d개 · 변형 %s · 질환당 요청 %d개  → 호출 %d회"
          % (len(diseases), "+".join(variants), a.k, len(diseases) * len(variants)))
    if not llm.available():
        print("\nLLM이 없다. 후보를 만들 수 없다 — py -m bioreroute.diag 로 확인하라.")
        return 1

    rows, runs = [], []
    for v in variants:
        st = generate(diseases, a.k, v, a.model)
        runs += st.discover.get("runs", [])
        for c in st.candidates:
            dz = c.disease
            aa, ss, ff = sets_for(uni, dz)
            key = drug_key(c.drug)
            g = next((r for r in c.trail if r.gate == "discovery"), None)
            p = (g.provenance if g else {}) or {}
            rows.append({
                "disease": dz, "variant": v, "drug": c.drug, "drug_key": key,
                "label": label_of(key, aa, ss, ff),
                "evidence_level": p.get("evidence_level") or "",
                "gen_confidence": p.get("gen_confidence") or "",
                "mechanism": p.get("mechanism") or "",
                "rationale": p.get("rationale") or "",
            })
    cache.save()

    with open(a.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.splitext(a.out)[0] + "_runs.json", "w", encoding="utf-8") as fh:
        json.dump({"diseases": diseases, "k": a.k, "variants": variants,
                   "model": a.model or llm.MODEL, "runs": runs},
                  fh, ensure_ascii=False, indent=1)

    report(rows, uni, diseases, a.k, variants, runs)
    print("\n저장: %s  (%d행)" % (a.out, len(rows)))
    return 0


def report(rows, uni, diseases, k, variants, runs):
    print("\n" + "=" * 66)
    print("생성 결과")
    print("=" * 66)

    asked = {v: sum(r["asked"] for r in runs if r["variant"] == v) for v in variants}
    for v in variants:
        got = sum(1 for r in rows if r["variant"] == v)
        fails = [r for r in runs if r["variant"] == v and not r["ok"]]
        print("  %-6s 요청 %3d → 생성 %3d  (충족률 %.0f%%%s)"
              % (v, asked[v], got, 100.0 * got / max(1, asked[v]),
                 " · 호출 실패 %d" % len(fails) if fails else ""))
    print("\n  ※ strict 가 적게 내놓는 것은 정상 동작이다 —"
          " '근거 없으면 빼라'고 시켰다. 충족률 자체가 측정값이다.")

    order = ["승인", "효능실패", "중단", "미지"]
    print("\n" + "-" * 66)
    print("대조 결과 — 생성 후보가 이미 알려진 사실과 겹치는가")
    print("-" * 66)
    print("  %-8s %5s  %s" % ("변형", "n", "  ".join("%8s" % o for o in order)))
    per = {}
    for v in variants:
        sub = [r for r in rows if r["variant"] == v]
        c = Counter(r["label"] for r in sub)
        per[v] = (c, len(sub))
        print("  %-8s %5d  %s" % (v, len(sub), "  ".join(
            "%3d %4.0f%%" % (c[o], 100.0 * c[o] / max(1, len(sub))) for o in order)))

    base, nb = trivial_baseline(uni, diseases, k)
    print("  %-8s %5s  %s" % ("무작위", "—", "  ".join(
        "    %4.1f%%" % (100 * base[o]) for o in order)))
    print("\n  무작위 = 약물 어휘 %d개에서 아무거나 k개 (모의 %s회)"
          % (len(uni["vocab"]), format(nb, ",")))

    # ── 핵심 검정: 효능실패 적중이 우연 수준인가 ──────────
    print("\n" + "-" * 66)
    print("① 발굴기는 **이미 효능 실패한 약**을 다시 내놓는가")
    print("-" * 66)
    # **기준선은 상수다.** 48만 회 모의로 얻었으므로 자체 오차가 없다.
    #   여기에 2×2 Fisher를 쓰면 없는 표본 오차를 집어넣어 p를 부풀린다 —
    #   실제로 그랬다(결함 32: Fisher p=0.122 vs 이항 p=0.0002, 600배).
    #   상수 대비 비교는 **일표본 이항 정확검정**이다.
    p0 = base["효능실패"]
    for v in variants:
        c, n = per[v]
        hit = c["효능실패"]
        lo, hi = wilson(hit, n)
        print("  %-6s %d/%d = %.1f%%  [%.1f–%.1f]   무작위 %.2f%% (기대 %.1f건)"
              % (v, hit, n, 100.0 * hit / max(1, n), 100 * lo, 100 * hi,
                 100 * p0, p0 * n))
        if n:
            p = binom_ge(hit, n, p0)
            pw = power1(p0, hit / n, n)
            print("         이항 정확검정 %s · 검정력 %.0f%% · 배율 %.1f배 · "
                  "사전 기준(CI 하한>기준선) %s"
                  % (fmt_p(p), 100 * pw, (hit / n) / p0 if p0 else 0,
                     "통과" if lo > p0 else "미달"))

    print("\n" + "-" * 66)
    print("② 발굴기는 **이미 승인된 약**을 내놓는가 (규칙 2 위반 = 회상)")
    print("-" * 66)
    for v in variants:
        c, n = per[v]
        lo, hi = wilson(c["승인"], n)
        print("  %-6s %d/%d = %.1f%%  [%.1f–%.1f]"
              % (v, c["승인"], n, 100.0 * c["승인"] / max(1, n), 100 * lo, 100 * hi))
    print("\n  프롬프트 규칙 2는 '이미 승인된 약은 제외'다. 여기 잡힌 것은")
    print("  지시 위반이면서 동시에 **생성기가 회상에 기대고 있다**는 신호다.")

    if len(variants) == 2:
        print("\n" + "-" * 66)
        print("③ 프롬프트의 신중함이 후보의 질을 바꾸는가")
        print("-" * 66)
        (cs, ns), (cl, nl) = per["strict"], per["loose"]
        for lab in ("효능실패", "미지"):
            p = fisher(cs[lab], ns - cs[lab], cl[lab], nl - cl[lab])
            pw = power2(cs[lab] / max(1, ns), cl[lab] / max(1, nl), ns, nl)
            print("  %-6s strict %.1f%% vs loose %.1f%%   %s · 검정력 %.0f%%"
                  % (lab, 100.0 * cs[lab] / max(1, ns), 100.0 * cl[lab] / max(1, nl),
                     fmt_p(p), 100 * pw))
        print("\n  차이가 없으면 '생성기를 다그치면 된다'는 반론도, 그 반론에 대한")
        print("  우리 방어도 둘 다 근거를 잃는다. 어느 쪽이든 그대로 적는다.")

    # 질환별 — 한 질환이 전체를 끌고 가는지 확인
    print("\n" + "-" * 66)
    print("질환별 (효능실패 적중 순)")
    print("-" * 66)
    byd = defaultdict(Counter)
    for r in rows:
        byd[r["disease"]][r["label"]] += 1
    for dz, c in sorted(byd.items(), key=lambda x: -x[1]["효능실패"]):
        n = sum(c.values())
        print("  %-38s n=%3d  실패 %2d · 승인 %2d · 미지 %2d"
              % (dz[:38], n, c["효능실패"], c["승인"], c["미지"]))

    print("\n" + "=" * 66)
    print("다음 단계 — 여기까지는 **생성만** 했다. 깔때기는 아직 안 태웠다.")
    print("  py -m bioreroute.bench.run 으로 라벨 있는 부분집합을 태우면")
    print("  '깔때기가 효능실패 후보를 골라 죽이는가'를 잴 수 있다.")
    print("=" * 66)


if __name__ == "__main__":
    sys.exit(main())
