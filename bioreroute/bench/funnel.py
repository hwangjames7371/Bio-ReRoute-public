# -*- coding: utf-8 -*-
"""깔때기 실험 — 생성 후보를 실제로 거르는가.

    ① 표본 추출 (문헌량 균형)
       py -m bioreroute.bench.funnel select gen_run2.csv --out gen_matched.csv

    ② 깔때기 실행 — 기존 벤치마크 실행기를 그대로 쓴다
       py -m bioreroute.bench.run gen_matched.csv --configs B0 B5 \
            --out gen_results.json --save-state gen_state.json

    ③ 판정
       py -m bioreroute.bench.funnel report gen_state.json

명세: `사전명세_깔때기실험.md` (실행 전 봉인)

## 주지표는 `근거 기반 기각` 이다 — 총 기각이 아니다

`홀드아웃결과.md` 가 남긴 교훈이다. 총 기각 재현율은 성격이 다른 두 기각을
합산한다 —

    F0 문헌 0건 기각   근거가 **없어서** 기각 (환각 판정)
    근거 기반 기각     근거로 **반박해서** 기각

주②에서 시점을 차단했더니 앞이 39→71로 늘고 뒤가 56→21로 줄었다.
총량은 106→93으로 거의 안 변해 **시간 구조가 통째로 감춰졌다.**
같은 실수를 반복하지 않으려고 여기서는 처음부터 분리해 센다.
"""

import argparse
import csv
import json
import math
import os
import sys
from collections import Counter

from ..io import cache, sources
from . import labels as L
from .discover import drug_key, load_universe, sets_for
from .stats import fisher, fmt_p, mde, power2, wilson

TOL = 0.15          # |log10(TP) − log10(TN)| 상한. **원본 벤치마크와 같은 값**
MIN_DOCS = 5        # 읽을 문헌이 없으면 판정 자체가 불가능하다

OUT_COLS = ["label", "stratum", "drug", "indication", "kind", "phase",
            "pubmed", "nct", "ctgov_year", "why", "detail", "matched_to"]

# F0가 "문헌이 없어서" 기각한 것의 사유 문자열. `core/scoring.py` 와 맞춰야 한다.
F0_KILL = "F0: 문헌 근거 없음(환각)"


# ─────────────────────────────────────────────────────────────
# ① 표본 추출
# ─────────────────────────────────────────────────────────────
def npub(drug, disease, ttl=None):
    """그 쌍의 PubMed 문헌 수. 실패하면 None(제외 대상)."""
    r = sources.pubmed_search("%s AND %s" % (drug, disease), retmax=1)
    if r.get("error"):
        return None
    return r.get("count")


def tn_source_row(tnpool, drug, disease):
    """TN 라벨의 출처가 된 시험 행. 누출 차단(NCT)과 감사에 쓴다."""
    dt = L.ind_tokens(disease)
    k = drug_key(drug)
    for r in tnpool:
        if drug_key(r["drug"]) == k and L.same_disease(dt, L.ind_tokens(r["condition"])):
            return r
    return None


def select(a):
    cache.configure(a.cache)
    cache.load()                       # **조회 전에** 읽는다 (결함 26·27)

    rows = list(csv.DictReader(open(a.gen, encoding="utf-8-sig")))
    tnpool = list(csv.DictReader(open(a.tnpool, encoding="utf-8-sig")))

    # **같은 쌍을 두 번 세지 않는다.** strict·loose 가 같은 약을 내면
    #   후보 목록에는 2행이지만 **검증할 가설은 하나**다. 그대로 두면
    #   n이 부풀고 두 행이 반드시 같은 판정을 받아 독립성이 깨진다.
    #
    #   ## 질환 **문자열**로 세면 안 된다 (결함 33)
    #
    #   처음엔 `(약물키, 질환문자열)` 로 셌다. 실측에서 이렇게 샜다 —
    #
    #       NCT01931566 ×2  Pioglitazone|Alzheimer's Disease
    #                       pioglitazone|Alzheimer Disease
    #       NCT02472353 ×2  metformin|Breast Cancer
    #                       metformin|Breast Neoplasms
    #
    #   **같은 병의 다른 이름**이라 문자열이 다르고, 그래서 14쌍으로 셌는데
    #   고유는 12쌍이었다. Fisher의 독립성 가정이 깨진 채로 p값을 냈다.
    #
    #   TN 은 **출처 시험(NCT)** 으로 센다 — 이름이 아니라 실체가 기준이다.
    #   TP 는 NCT가 없으므로 `(약물키, 질환 토큰집합)` 으로 센다.
    def uniq(label, key_of):
        seen, out = set(), []
        for r in rows:
            if r["label"] != label:
                continue
            k = key_of(r)
            if k is None or k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out

    def tn_key(r):
        src = tn_source_row(tnpool, r["drug"], r["disease"])
        return src["nct"] if src else None          # 출처를 못 찾으면 어차피 제외

    def tp_key(r):
        return (r["drug_key"], L.ind_tokens(r["disease"]))

    tn_raw, tp_raw = uniq("효능실패", tn_key), uniq("승인", tp_key)
    n_dup_tn = sum(1 for r in rows if r["label"] == "효능실패") - len(tn_raw)
    print("표본  효능실패 %d건(중복 %d 제거 · NCT 기준) · 승인 %d건"
          % (len(tn_raw), n_dup_tn, len(tp_raw)))

    def enrich(rs, lab):
        out = []
        for r in rs:
            n = npub(r["drug"], r["disease"])
            if n is None:
                print("  [제외] 문헌 조회 실패 %s / %s" % (r["drug"], r["disease"]))
                continue
            r = dict(r, pubmed=n)
            if lab == "TN":
                src = tn_source_row(tnpool, r["drug"], r["disease"])
                if src is None:
                    print("  [제외] TN 출처 시험을 못 찾음 %s / %s"
                          % (r["drug"], r["disease"]))
                    continue
                r["_src"] = src
            out.append(r)
        return out

    print("\nPubMed 문헌 수 조회 (캐시 사용)…")
    tn, tp = enrich(tn_raw, "TN"), enrich(tp_raw, "TP")
    cache.save()

    # 문헌 하한 — 균형만 맞추고 정보가 없으면 전부 `보류` 가 나온다
    tn = [r for r in tn if r["pubmed"] >= MIN_DOCS]
    tp = [r for r in tp if r["pubmed"] >= MIN_DOCS]
    print("문헌 %d건 이상: TN %d · TP %d" % (MIN_DOCS, len(tn), len(tp)))

    # ── 균형 짝짓기 — TN마다 가장 가까운 TP를 붙인다(재사용 없음) ──
    #   TN을 기준으로 도는 이유: TN이 희소하다. TP를 기준으로 돌면
    #   짝을 못 찾은 TN이 조용히 사라져 "전수"가 아니게 된다.
    used, pairs, unmatched = set(), [], []
    for t in sorted(tn, key=lambda r: r["pubmed"]):
        lt = math.log10(t["pubmed"])
        best, bd = None, 1e9
        for i, p in enumerate(tp):
            if i in used:
                continue
            d = abs(math.log10(p["pubmed"]) - lt)
            if d < bd:
                best, bd = i, d
        if best is None or bd > TOL:
            unmatched.append((t, bd if best is not None else None))
            continue
        used.add(best)
        pairs.append((t, tp[best], bd))

    print("\n짝짓기  성사 %d쌍 · 실패 %d건 (|Δlog10| ≤ %.2f)"
          % (len(pairs), len(unmatched), TOL))
    for t, d in unmatched:
        print("  [짝 없음] %-22s %-24s 문헌 %6d  최근접 Δ%s"
              % (t["drug"][:22], t["disease"][:24], t["pubmed"],
                 "%.2f" % d if d is not None else "—"))

    if not pairs:
        print("\n짝이 하나도 없다. 실행할 것이 없다.")
        return 1

    diffs = [math.log10(p["pubmed"]) - math.log10(t["pubmed"]) for t, p, _ in pairs]
    print("  부호평균(TP−TN) %+.3f · 최대 |Δ| %.3f"
          % (sum(diffs) / len(diffs), max(abs(d) for d in diffs)))

    if os.path.exists(a.out) and not a.force:
        print("\n이미 있는 파일이다: %s — 덮어쓰려면 --force" % a.out)
        return 2
    with open(a.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_COLS)
        w.writeheader()
        for t, p, _ in pairs:                  # TN·TP 번갈아 — bench.run 규약
            src = t["_src"]
            w.writerow({"label": "TN", "stratum": "A", "drug": t["drug"],
                        "indication": t["disease"], "kind": "효능",
                        "phase": src.get("phase", ""), "pubmed": t["pubmed"],
                        "nct": src.get("nct", ""),
                        "ctgov_year": src.get("completion_year", ""),
                        "why": src.get("stop_quote", ""),
                        "detail": src.get("why_stopped", ""), "matched_to": ""})
            w.writerow({"label": "TP", "stratum": "A", "drug": p["drug"],
                        "indication": p["disease"], "kind": "승인",
                        "phase": "NA", "pubmed": p["pubmed"], "nct": "",
                        "ctgov_year": "", "why": "", "detail": "",
                        "matched_to": "%s|%s" % (t["drug"], t["disease"])})
    print("\n저장: %s  (%d쌍 · %d행)" % (a.out, len(pairs), 2 * len(pairs)))

    m = mde(0.05, len(pairs), len(pairs))
    print("\n검정력 — **실행 전에** 적어 둔다")
    print("  n=%d 쌍으로 80%% 검정력에 필요한 TN 기각률: %s"
          % (len(pairs), "%.0f%%" % (100 * m) if m else "달성 불가"))
    print("  기존 벤치마크 B5 기각 재현율은 17%였다.")
    if m and m > 0.4:
        print("  → **이 표본으로는 기존 수준의 효과를 잡을 수 없다.**")
        print("     결과가 유의하지 않게 나오면 '효과 없음'이 아니라 '측정 불가'다.")
    return 0


# ─────────────────────────────────────────────────────────────
# ③ 판정
# ─────────────────────────────────────────────────────────────
def kill_kind(c):
    """기각을 두 종류로 가른다. 합산하면 무엇을 쟀는지 알 수 없다."""
    if c.get("verdict") != "기각":
        return None
    return "F0" if F0_KILL in (c.get("reason") or "") else "근거"


def report(a):
    st = json.load(open(a.state, encoding="utf-8"))
    cands = st["candidates"]
    cfg = st.get("config", "?")
    tn = [c for c in cands if c["label"] == "TN"]
    tp = [c for c in cands if c["label"] == "TP"]

    print("=" * 70)
    print("깔때기 실험 판정 — 구성 %s · TN %d · TP %d" % (cfg, len(tn), len(tp)))
    print("=" * 70)

    def split(rs):
        k = Counter(kill_kind(c) for c in rs)
        return k["근거"], k["F0"], len(rs)

    print("\n판정 분포")
    for lab, rs in (("TN(효능실패)", tn), ("TP(승인)", tp)):
        v = Counter(c["verdict"] for c in rs)
        print("  %-14s %s" % (lab, " · ".join("%s %d" % (x, v[x]) for x in
                                              ("유망", "조건부", "보류", "기각"))))

    print("\n" + "-" * 70)
    print("주지표 — **근거 기반 기각** (F0 문헌0건 기각은 뺀다)")
    print("-" * 70)
    kn, fn, nn = split(tn)
    kp, fp, np_ = split(tp)
    for lab, k, f, n in (("TN", kn, fn, nn), ("TP", kp, fp, np_)):
        lo, hi = wilson(k, n)
        print("  %s  근거기반 기각 %d/%d = %.1f%% [%.1f–%.1f]   (F0 기각 %d건은 별도)"
              % (lab, k, n, 100.0 * k / max(1, n), 100 * lo, 100 * hi, f))

    p = fisher(kn, nn - kn, kp, np_ - kp)
    pw = power2(kp / max(1, np_), kn / max(1, nn), np_, nn)
    m = mde(kp / max(1, np_) if np_ else 0.05, np_, nn)
    print("\n  Fisher 양측 %s · 검정력 %.0f%%" % (fmt_p(p), 100 * pw))
    print("  MDE — 80%% 검정력에 필요한 TN 기각률: %s"
          % ("%.0f%%" % (100 * m) if m else "달성 불가"))

    print("\n  사전 기준(명세 §3): TN > TP 이고 p < 0.05")
    if kn / max(1, nn) > kp / max(1, np_) and p < 0.05:
        v = "**지지** — 깔때기가 효능실패를 골라 기각한다"
    elif kp / max(1, np_) > kn / max(1, nn) and p < 0.05:
        v = "**반대** — 깔때기가 거꾸로 걸러낸다"
    else:
        v = ("**모른다** — 구별 불가. '차이 없다'가 아니다. "
             "위 MDE보다 작은 효과는 이 n으로 잡히지 않는다")
    print("  → %s" % v)

    print("\n" + "-" * 70)
    print("부지표 (결론에 쓰지 않는다)")
    print("-" * 70)
    tk, tpk = sum(1 for c in tn if c["verdict"] == "기각"), \
        sum(1 for c in tp if c["verdict"] == "기각")
    print("  총 기각(F0 포함)  TN %d/%d = %.0f%% · TP %d/%d = %.0f%%"
          % (tk, nn, 100.0 * tk / max(1, nn), tpk, np_, 100.0 * tpk / max(1, np_)))
    print("  ※ 총 기각으로 세면 F0 기각이 섞여 무엇을 쟀는지 알 수 없다 —")
    print("    주②가 그래서 미달했다. 위의 근거 기반 기각이 주지표다.")

    print("\n" + "-" * 70)
    print("TN 전수 — 무엇을 잡고 무엇을 놓쳤나")
    print("-" * 70)
    for c in tn:
        kk = kill_kind(c)
        mark = {"근거": "잡음", "F0": "F0기각", None: "놓침"}[kk]
        print("  %-6s %-38s %s (%s)"
              % (mark, c["name"][:38], c["verdict"], (c.get("reason") or "")[:44]))
    return 0


def pair_report(a):
    """B5 → B6 **짝비교**. 집단 간 비교가 아니다.

    깔때기 실험에서 TN vs TP 집단 간 비교는 n=14로 못 한다는 것이
    확인됐다(p=0.077 · 22쌍 필요). 그래서 질문을 바꾼다 —
    **같은 후보의 판정이 뒤집히는가.** 집단 간 분산이 사라진다.

    명세: `사전명세_등록부실험.md` · 주지표는 `근거 기반 기각` 의 McNemar.
    """
    from .analyze import mcnemar

    # 없는 파일에 역추적을 뱉지 않는다. **무엇이 없고 어떻게 만드는지** 말한다.
    #   실측: `--dry` 로 비용만 보고 바로 `pair` 를 부르면 상태 파일이 없다.
    #   그건 사용자의 실수가 아니라 **자연스러운 순서**다.
    for path, who in ((a.before, "B5"), (a.after, "B6")):
        if not os.path.exists(path):
            print("없는 파일이다: %s" % path)
            print("  %s 실행이 아직 상태를 안 남겼다. `--dry` 는 비용만 세고 끝난다." % who)
            print("  py -m bioreroute.bench.run gen_matched.csv --configs %s \\" % who)
            print("       --out gen_results_%s.json --save-state %s"
                  % (who.lower(), path))
            return 2

    A = json.load(open(a.before, encoding="utf-8"))
    B = json.load(open(a.after, encoding="utf-8"))
    ka, kb = {c["name"]: c for c in A["candidates"]}, \
        {c["name"]: c for c in B["candidates"]}
    names = [c["name"] for c in A["candidates"] if c["name"] in kb]
    if len(names) != len(A["candidates"]):
        print("  [경고] 두 실행의 후보가 다르다 — 공통 %d건만 본다" % len(names))

    print("=" * 70)
    print("짝비교 %s → %s   공통 %d건" % (A.get("config"), B.get("config"), len(names)))
    print("=" * 70)

    for lab in ("TN", "TP"):
        sel = [n for n in names if ka[n]["label"] == lab]
        # **근거 기반 기각만 센다.** F0 문헌0건 기각은 근거로 반박한 것이 아니다.
        va = [1 if kill_kind(ka[n]) == "근거" else 0 for n in sel]
        vb = [1 if kill_kind(kb[n]) == "근거" else 0 for n in sel]
        # **`mcnemar(a_ok, b_ok)` 는 (b = a만, c = b만) 을 돌려준다.**
        #   그러므로 첫 인자에 before, 둘째에 after 를 주면
        #     b_only = before만 기각(= 잃음) · c_only = after만 기각(= 얻음)
        #   이다. 첫 판에 이 둘을 바꿔 읽어 **B6가 6건을 더 잡았는데
        #   "등록부가 판정을 나쁘게 만든다"고 찍었다.** 합성 시험이 잡았다.
        #   결함 8·22와 같은 유형이다 — **방향은 데이터에서 읽어라.**
        lost_n, gain_n, p = mcnemar(va, vb)
        want = "잡아야 정답" if lab == "TN" else "기각하면 오답"
        print("\n%s %d건 (%s)" % (lab, len(sel), want))
        print("  %s 근거기반 기각 %d · %s %d"
              % (A.get("config"), sum(va), B.get("config"), sum(vb)))
        print("  뒤집힘: %s가 얻음 %d건 · 잃음 %d건   McNemar %s"
              % (B.get("config"), gain_n, lost_n, fmt_p(p)))
        if lab == "TN":
            miss = [n for n in sel if not va[n2i(sel, n)]]
            print("  사전 문턱(명세 §3): **놓친 %d건 중 6건 이상**을 잡아야 p<0.05"
                  % len(miss))
            gained = [n for n in sel if kill_kind(kb[n]) == "근거"
                      and kill_kind(ka[n]) != "근거"]
            lost = [n for n in sel if kill_kind(ka[n]) == "근거"
                    and kill_kind(kb[n]) != "근거"]
            for n in gained:
                print("    + %-36s %s" % (n[:36], (kb[n].get("reason") or "")[:40]))
            for n in lost:
                print("    − %-36s **잃음**" % n[:36])
            # 판정 문구를 상수로 고정하지 않는다. **방향을 수에서 읽는다.**
            if p >= 0.05:
                print("  → **모른다.** '효과 없다'가 아니다. "
                      "얻음 %d · 잃음 %d 로는 못 잡는다" % (gain_n, lost_n))
            elif gain_n > lost_n:
                print("  → **지지** — 등록부가 놓친 것을 잡는다")
            else:
                print("  → **반대** — 등록부가 판정을 나쁘게 만든다")
    return 0


def n2i(seq, x):
    return seq.index(x)


def main(argv=None):
    ap = argparse.ArgumentParser(description="깔때기 실험 — 표본 추출과 판정")
    sub = ap.add_subparsers(dest="mode", required=True)

    s = sub.add_parser("select", help="생성 CSV → 문헌량 균형 짝 CSV")
    s.add_argument("gen")
    s.add_argument("--out", required=True)
    s.add_argument("--tnpool", default="bench_tn_pool_v2.csv")
    s.add_argument("--cache", default="pubmed_cache.json")
    s.add_argument("--force", action="store_true")

    r = sub.add_parser("report", help="상태 JSON → 판정")
    r.add_argument("state")

    q = sub.add_parser("pair", help="두 상태 JSON → B5→B6 McNemar 짝비교")
    q.add_argument("before", help="예: gen_state.json (B5)")
    q.add_argument("after", help="예: gen_state_b6.json (B6)")

    a = ap.parse_args(argv)
    return {"select": select, "report": report, "pair": pair_report}[a.mode](a)


if __name__ == "__main__":
    sys.exit(main())
