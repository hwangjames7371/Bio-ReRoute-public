# -*- coding: utf-8 -*-
"""결과 반영 — 두 분석 JSON 을 결과 문서의 절과 발표 한 장으로 옮긴다  (LLM 0회 · 09-25)

    py -m bioreroute.bench.resultmd                        화면으로
    py -m bioreroute.bench.resultmd --out 결과반영_0925.md  새 파일로 (있으면 멈춘다)

입력 — `표적재시험_결과.json`(`seedretest analyze`) · `추출복제_결과.json`(`drawvar analyze`).
없는 쪽은 건너뛴다.

## 왜 이 도구가 있나

수치를 손으로 옮기다 틀린 것이 세 번이다(결함 19 · 307 · 331). 그래서 —

1. **수치는 JSON 에서 바로** 찍는다. 사람이 숫자를 다시 치지 않는다
2. **말은 봉인한 갈래 문구 그대로** 쓴다 — 표적 재시험은 `seedretest.BRANCH_TEXT` 를
   불러 쓰고, 추출 복제는 `drawvar.analyze` 가 이미 고른 `R1_말` 을 옮긴다(여기 다시 적지 않는다)
3. **예측 대조**를 같이 낸다 — 명세 §5 의 예측을 아래 상수로 옮겨 두었고, 그 문구가
   봉인된 명세 본문에 **그대로 있는지** 시험 [184] 가 본다(상수와 명세가 갈라지면 깨진다)
4. **무효면 말을 고르지 않는다** — 명세 §6. 무효 사유만 적고 갈래 문장은 안 찍는다
"""

import argparse
import json
import os
import sys

from . import seedretest as SR

TARGETED_JSON = "표적재시험_결과.json"
REPLICATE_JSON = "추출복제_결과.json"

# ── 명세 §5 예측 — **봉인된 문구를 그대로 옮긴다** (시험 [184] 가 대조) ──────
#   (이름, 명세에 있는 문구, 판정 함수의 인자)
TARGETED_SPEC = "사전명세_표적재시험_0924.md"
TARGETED_PRED = {
    "갈래": ("| 갈래 | **가 (약 55%)** · 다 (약 43%) · 나 (약 2%) |", "가"),
    "합산": ("| 합산 b · c | b ≈ 25 (15~40) · c ≈ 10 (4~18) |", ((15, 40), (4, 18))),
    "sol유지": ("| sol 이 자기 22쌍을 다시 기각 | 약 60% (40~80%) |", (0.40, 0.80)),
    "luna22": ("| luna 가 그 22쌍을 기각 | 약 25% (10~40%) |", (0.10, 0.40)),
    "뒤집힘": ("| 같은 모델 seed 끼리 대상 판정이 갈리는 비율 | 약 25% (15~40%) |", (0.15, 0.40)),
}
REPLICATE_SPEC = "사전명세_추출복제_0924.md"
REPLICATE_PRED = {
    "W": ("| R1 W (같은 모델·다른 seed) | 약 10% (6~15%) |", (0.06, 0.15)),
    "B": ("| R1 B (다른 모델) | 약 11% (7~16%) |", (0.07, 0.16)),
    "R1말": ("| **R1 말** | **«구별되지 않는다» 약 60%**", "구별되지 않는다"),
    "R2_AUROC": ("| R2 AUROC | 차의 크기 ≤ 0.02 일 확률 약 65% |", True),
    "R2_기각": ("| R2 기각률 | 차의 크기 ≤ 2%p 일 확률 약 55% |", True),
    "R3": ("| R3 | 약 90% (84~95%) |", (0.84, 0.95)),
    "s42_AUROC": ("| terra_s42 누출 제외 B5 AUROC | 0.60~0.64 |", (0.60, 0.64)),
    "표적교차": ("| 표적 교차(보조) | 1차 sol 만 22쌍 → sol_s17 12~16 · luna_s17 4~7 |",
             ((12, 16), (4, 7))),
}


# ── 작은 도구 ─────────────────────────────────────────────────────

def pct(x, d=1):
    return "—" if x is None else ("%.*f%%" % (d, 100.0 * x))


def rate(r):
    """{"k","n","비율","CI"} → «k/n = x% [lo–hi]»."""
    if not r or not r.get("n"):
        return "—"
    lo, hi = r.get("CI") or (None, None)
    return "%d/%d = %s [%s–%s]" % (r["k"], r["n"], pct(r.get("비율")),
                                   pct(lo), pct(hi))


def within(x, lohi):
    return x is not None and lohi[0] <= x <= lohi[1]


def mark(ok):
    return "✅" if ok else "❌"


def load(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── 표적 재시험 ────────────────────────────────────────────────────

def targeted_branch_word(res):
    m = res["주검정"]
    return {"가": "되풀이됐다", "나": "뒤집혔다", "다": "가르지 못했다"}[m["갈래"]]


def targeted_predictions(res):
    """명세 §5 예측 대조 — (항목, 예측, 결과, 맞았나)."""
    m = res["주검정"]
    keep = res["유지"]["A"]
    rows = [
        ("갈래", "가 (약 55%)", m["갈래"], m["갈래"] == TARGETED_PRED["갈래"][1]),
    ]
    (blo, bhi), (clo, chi) = TARGETED_PRED["합산"][1]
    rows.append(("합산 b · c", "b 15~40 · c 4~18", "b %d · c %d" % (m["A만"], m["B만"]),
                 blo <= m["A만"] <= bhi and clo <= m["B만"] <= chi))
    sr = keep["A기각"]["비율"]
    lr = keep["B기각"]["비율"]
    rows.append(("sol 이 자기 22쌍을 다시 기각", "40~80%", pct(sr),
                 within(sr, TARGETED_PRED["sol유지"][1])))
    rows.append(("luna 가 그 22쌍을 기각", "10~40%", pct(lr),
                 within(lr, TARGETED_PRED["luna22"][1])))
    for g, name in (("A", "sol"), ("B", "luna")):
        fl = res["seed간뒤집힘"].get(g) or []
        k = sum(x["k"] for x in fl)
        n = sum(x["n"] for x in fl)
        v = (k / n) if n else None
        rows.append(("seed 끼리 갈림 · %s" % name, "15~40%", pct(v),
                     within(v, TARGETED_PRED["뒤집힘"][1])))
    return rows


def targeted_md(res):
    m = res["주검정"]
    bad = res.get("유효성") or []
    lo, hi = m.get("psi_ci") or (None, None)
    L = []
    title = ("무효 — 명세 §6" if bad else "sol 의 초과 기각은 새 seed 에서 **%s**"
             % targeted_branch_word(res))
    L.append("## 2-⭐⭐⭐ 09-25 · 표적 재시험 — %s" % title)
    L.append("")
    L.append("> 명세 `사전명세_표적재시험_0924.md`(봉인 09-25 00:11:03) · 도구 `seedretest` · "
             "이 절의 수치는 `resultmd` 가 `%s` 에서 옮겼다(손으로 안 옮김)." % TARGETED_JSON)
    L.append("")
    if bad:
        L.append("🔴 **명세대로 돌지 않은 실행이 있다 — 갈래를 말하지 않는다**(명세 §6)")
        L.append("")
        for x in bad:
            L.append("- %s" % x)
        L.append("")
    L.append("### 주검정 — (쌍, seed) 합산 McNemar 정확 · 양측 α = %.2f" % m["alpha"])
    L.append("")
    L.append("```")
    L.append("대상 %d · 분석 %d · 새 seed %d개%s" % (
        res["대상"], res["분석대상"], res["seed수"],
        (" · 입력이 달라 뺌 %s" % ", ".join(res["뺀대상"])) if res["뺀대상"] else ""))
    L.append("sol 만 기각 %d · luna 만 기각 %d · p = %.4g · ψ̂(luna 쪽) = %s [%s–%s]"
             % (m["A만"], m["B만"], m["p"],
                "—" if m.get("psi_hat") is None else "%.2f" % m["psi_hat"],
                "—" if lo is None else "%.2f" % lo, "—" if hi is None else "%.2f" % hi))
    L.append("seed 별  " + " · ".join("A만 %d B만 %d p=%.3g" % (s["A만"], s["B만"], s["p"])
                                     for s in res["seed별"]))
    L.append("```")
    L.append("")
    if not bad:
        L.append("**갈래 «%s»** — %s" % (m["갈래"], SR.BRANCH_TEXT[m["갈래"]]))
        L.append("")
        if m["갈래"] == "다":
            L.append("⚠ p ≥ 0.05 는 «차이가 없다» 가 아니다 — ψ̂ 와 구간을 같이 본다(`CLAUDE.md §4`).")
            L.append("")
    L.append("### 보조 — 검정 없이")
    L.append("")
    ka, kb = res["유지"]["A"], res["유지"]["B"]
    L.append("| 1차에 | sol 새 seed 기각 | luna 새 seed 기각 |")
    L.append("|---|---|---|")
    L.append("| sol 만 기각한 쌍 | %s | %s |" % (rate(ka["A기각"]), rate(ka["B기각"])))
    L.append("| luna 만 기각한 쌍 | %s | %s |" % (rate(kb["A기각"]), rate(kb["B기각"])))
    L.append("")
    for g, name in (("A", "sol"), ("B", "luna")):
        fl = res["seed간뒤집힘"].get(g) or []
        L.append("- seed 끼리 대상 판정이 갈린 비율 · %s — %s"
                 % (name, " · ".join(rate(x) for x in fl) or "—"))
    L.append("")
    L.append("### 예측 대조 (명세 §5)")
    L.append("")
    L.append("| 항목 | 예측 | 결과 | |")
    L.append("|---|---|---|---|")
    for name, pred, got, ok in targeted_predictions(res):
        L.append("| %s | %s | %s | %s |" % (name, pred, got, mark(ok)))
    L.append("")
    L.append("<details><summary>대상 27쌍 — 1차 + 새 seed 셋의 기각 여부</summary>")
    L.append("")
    L.append("```")
    for r in res.get("표") or []:
        a = "".join("●" if x else "·" for x in r["A"])
        b = "".join("●" if x else "·" for x in r["B"])
        L.append("%-4s sol %s  luna %s  %s%s" % (
            "sol" if r["1차기각"] == "A" else "luna", a, b, r["name"][:48],
            "" if r.get("분석", True) else "  (뺌)"))
    L.append("```")
    L.append("(● 기각 · 앞 칸이 1차 seed 42, 뒤 셋이 새 seed)")
    L.append("")
    L.append("</details>")
    return "\n".join(L) + "\n"


# ── 추출 복제 ─────────────────────────────────────────────────────

def r1_branch(o):
    d = o.get("R1")
    if not d:
        return None
    lo, hi = d["D_CI"]
    return "모델이 더" if lo > 0 else ("seed 가 더" if hi < 0 else "구별되지 않는다")


def replicate_predictions(o):
    rows = []
    d = o.get("R1")
    if d:
        # 경계 근처는 **소수 둘째 자리까지** 찍는다 — 09-25 첫 판이 5.99% 를 «6.0%» 로
        #   반올림해 찍고 옆에 ❌ 를 달아 **표가 자기 말과 어긋났다.**
        rows.append(("R1 W (같은 모델·다른 seed)", "6~15%", pct(d["같은모델_다른seed"], 2),
                     within(d["같은모델_다른seed"], REPLICATE_PRED["W"][1])))
        rows.append(("R1 B (다른 모델)", "7~16%", pct(d["다른모델"], 2),
                     within(d["다른모델"], REPLICATE_PRED["B"][1])))
        br = r1_branch(o)
        rows.append(("R1 말", "구별되지 않는다 (약 60%)", br, br == REPLICATE_PRED["R1말"][1]))
    r2 = o.get("R2")
    if r2:
        rows.append(("R2 AUROC 차 ≤ 0.02", "약 65%", "%+.4f" % r2["AUROC차"], r2["AUROC안정"]))
        rows.append(("R2 기각률 차 ≤ 2%p", "약 55%", "%+.1f%%p" % r2["기각률차"], r2["기각안정"]))
    r3 = o.get("R3")
    if r3:
        rows.append(("R3 같은 seed 판정 일치", "84~95%", pct(r3["비율"]),
                     within(r3["비율"], REPLICATE_PRED["R3"][1])))
    s42 = (o.get("수치") or {}).get("terra_s42")
    if s42:
        a = s42["누출제외B5"][0]
        rows.append(("terra_s42 누출 제외 B5 AUROC", "0.60~0.64", "%.3f" % a,
                     within(a, REPLICATE_PRED["s42_AUROC"][1])))
    t = o.get("표적교차")
    if t:
        (slo, shi), (llo, lhi) = REPLICATE_PRED["표적교차"][1]
        rows.append(("표적 교차 — 1차 sol 만 22쌍", "sol 12~16 · luna 4~7",
                     "sol %d · luna %d" % (t["A"]["sol"], t["A"]["luna"]),
                     slo <= t["A"]["sol"] <= shi and llo <= t["A"]["luna"] <= lhi))
    return rows


def replicate_md(o):
    L = []
    d = o.get("R1")
    head = o.get("R1_말") or "—"
    L.append("## 2-⭐⭐⭐⭐ 09-25 · 추출 복제 — seed 를 바꾸면 · 모델을 바꾸면")
    L.append("")
    L.append("> 명세 `사전명세_추출복제_0924.md`(봉인 09-25 00:11:39) · 도구 `drawvar` · "
             "이 절의 수치는 `resultmd` 가 `%s` 에서 옮겼다." % REPLICATE_JSON)
    L.append("")
    if o.get("없음"):
        L.append("⚠ 결과가 없는 실행 — %s" % " · ".join(o["없음"]))
        L.append("")
    if o.get("무효"):
        L.append("🔴 **무효인 실행** — 그 칸은 기술통계로만 적고 말을 고르지 않는다(명세 §6)")
        L.append("")
        for k, v in o["무효"].items():
            L.append("- `%s` — %s" % (k, " / ".join(v)))
        L.append("")
    L.append("### R1 (주) — 판정 불일치: 같은 모델·다른 seed 대 다른 모델 (입력 동일 후보)")
    L.append("")
    if d:
        L.append("```")
        L.append("같은 모델 · 다른 seed   %s [%s–%s]" % (pct(d["같은모델_다른seed"]), pct(d["W_CI"][0]), pct(d["W_CI"][1])))
        L.append("다른 모델               %s [%s–%s]" % (pct(d["다른모델"]), pct(d["B_CI"][0]), pct(d["B_CI"][1])))
        L.append("D = 다른 모델 − 다른 seed   %+.1f%%p [%+.1f, %+.1f]   후보 %d · 부트스트랩 %d · seed %s"
                 % (100 * d["D"], 100 * d["D_CI"][0], 100 * d["D_CI"][1], d["후보"], d["반복"], d["seed"]))
        L.append("```")
        L.append("")
    L.append("**%s**" % head.replace("**", ""))     # 안쪽 굵게가 바깥 굵게를 깬다
    L.append("")
    rb = o.get("R1b_TN기각")
    if rb:
        w, b = rb["같은모델"], rb["다른모델"]
        L.append("R1b — 근거 기반 TN 기각 갈림: 같은 모델 %d/%d = %s · 다른 모델 %d/%d = %s"
                 % (w["불일치"], w["n"], pct(w["비율"]), b["불일치"], b["n"], pct(b["비율"])))
        L.append("")
    L.append("<details><summary>짝별 — 판정 일치 · 입력 다름 · TN 기각 갈림</summary>")
    L.append("")
    L.append("| 짝 | 판정 일치(입력 동일) | 입력 다름 | TN 기각 갈림 |")
    L.append("|---|---|---|---|")
    for k, g in (o.get("짝별") or {}).items():
        rj = g["근거기반기각"]
        L.append("| %s | %d/%d = %s | %d | %d : %d |" % (
            k.replace("~", " ~ "), g["일치"], g["입력동일"], pct(g["비율"]),
            g["입력다름"], rj["A만"], rj["B만"]))
    L.append("")
    L.append("</details>")
    L.append("")
    L.append("### 실행별 수치 (공통 부분집합 %d)" % o.get("공통부분집합", 0))
    L.append("")
    L.append("| 실행 | 공통 B5 AUROC | 누출 제외 B5 | 전체 B5 | ECE | 근거 기반 TN 기각 |")
    L.append("|---|---|---|---|---|---|")
    for k, v in (o.get("수치") or {}).items():
        a, lo, hi = v["공통B5"]
        ek, en = v["근거기반기각"]
        L.append("| %s | %.3f [%.3f–%.3f] | %.3f | %.3f | %.3f | %d/%d = %s |" % (
            k, a, lo, hi, v["누출제외B5"][0], v["B5전체"][0], v["ECE"], ek, en,
            pct(ek / en if en else None)))
    L.append("")
    r2 = o.get("R2")
    if r2:
        L.append("**R2 — terra 의 seed 폭** (s17 대 s19) — 공통 AUROC 차 %+.4f → %s · "
                 "근거 기반 기각률 %.1f%% 대 %.1f%% (차 %+.1f%%p) → %s"
                 % (r2["AUROC차"],
                    "«seed 에 안정»" if r2["AUROC안정"] else
                    "«헤드라인 옆에 seed 폭 ±%.3f 를 적는다»" % (abs(r2["AUROC차"]) / 2),
                    r2["기각률"][0], r2["기각률"][1], r2["기각률차"],
                    "«안정»" if r2["기각안정"] else "«폭을 적는다»"))
        L.append("")
    r3 = o.get("R3")
    if r3:
        L.append("**R3 — 같은 seed 재현** (terra_1 대 terra_s42 · 입력 동일 %d) — 판정 일치 %s "
                 "(개발집합 72/84 = 85.7%% 와 나란히)"
                 % (r3["입력동일"], rate({"k": r3["일치"], "n": r3["입력동일"],
                                          "비율": r3["비율"], "CI": r3["CI"]})))
        L.append("")
    r4 = o.get("R4")
    if r4:
        t1 = (o.get("수치") or {}).get("terra_1")
        s42 = (o.get("수치") or {}).get("terra_s42")
        extra = ""
        if t1 and s42:
            extra = (" · 누출 제외 B5 AUROC 헤드라인 %.3f → 스냅숏 seed 42 %.3f "
                     "(차이는 «캐시 복원 + 패치(F0 오류 경로)» 의 합 — 둘을 못 가른다)"
                     % (t1["누출제외B5"][0], s42["누출제외B5"][0]))
        L.append("**R4 — 캐시 효과** — 입력이 다른 %d 후보 중 판정 같음 %d%s"
                 % (r4["입력다름"], r4["판정같음"], extra))
        L.append("")
    t = o.get("표적교차")
    if t:
        L.append("표적 교차(보조) — 1차 sol 만 기각 %d쌍에서 sol_s17 %d · luna_s17 %d · "
                 "1차 luna 만 %d쌍에서 sol_s17 %d · luna_s17 %d"
                 % (t["A"]["n"], t["A"]["sol"], t["A"]["luna"],
                    t["B"]["n"], t["B"]["sol"], t["B"]["luna"]))
        L.append("")
    L.append("### 예측 대조 (명세 §5)")
    L.append("")
    rows = replicate_predictions(o)
    if not rows:
        L.append("(유효한 새 실행이 없어 대조할 것이 없다)")
    else:
        L.append("| 항목 | 예측 | 결과 | |")
        L.append("|---|---|---|---|")
        for name, pred, got, ok in rows:
            L.append("| %s | %s | %s | %s |" % (name, pred, got, mark(ok)))
    return "\n".join(L) + "\n"


def slide_lines(res, o):
    """발표 한 장에 들어갈 **숫자 넷과 한 문장** — 없는 쪽은 비운다."""
    out = {}
    d = (o or {}).get("R1")
    if d:
        out["seed"] = pct(d["같은모델_다른seed"], 1)
        out["모델"] = pct(d["다른모델"], 1)
        out["말"] = (o.get("R1_말") or "").split(" (D =")[0].replace("**", "")
    r2 = (o or {}).get("R2")
    if r2:
        out["AUROC폭"] = "%+.4f" % r2["AUROC차"]    # «-0.000» 으로 찍히지 않게 넷째 자리까지
    if res:
        m = res["주검정"]
        out["표적"] = "sol 만 %d · luna 만 %d · p = %.3g → «%s»" % (
            m["A만"], m["B만"], m["p"], targeted_branch_word(res))
    return out


def render(targeted=TARGETED_JSON, replicate=REPLICATE_JSON):
    res, o = load(targeted), load(replicate)
    parts = []
    if res:
        parts.append(targeted_md(res))
    if o:
        parts.append(replicate_md(o))
    s = slide_lines(res, o)
    if s:
        parts.append("## 발표 한 장 — 재료\n\n```\n%s\n```\n" % "\n".join(
            "%-6s %s" % (k, v) for k, v in s.items()))
    return "\n---\n\n".join(parts) if parts else ""


def main(argv=None):
    ap = argparse.ArgumentParser(description="분석 JSON → 결과 문서 절 (LLM 0회)")
    ap.add_argument("--targeted", default=TARGETED_JSON)
    ap.add_argument("--replicate", default=REPLICATE_JSON)
    ap.add_argument("--out", default=None, help="새 파일로 쓴다 (있으면 멈춘다)")
    a = ap.parse_args(argv)
    text = render(a.targeted, a.replicate)
    if not text:
        print("  두 결과 파일이 다 없다 — %s · %s" % (a.targeted, a.replicate))
        return 2
    if a.out:
        if os.path.exists(a.out):
            print("  🔴 %s 가 이미 있다 — 덮어쓰지 않는다" % a.out)
            return 2
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("→ %s" % a.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
