# -*- coding: utf-8 -*-
"""성능 한 장 — 발표의 «성능 지표 · 평가 기준» 칸을 **코드로** 낸다 (09-25).

    py -m bioreroute.bench.perfcard            사람용
    py -m bioreroute.bench.perfcard --json     발표 스크립트가 읽는 꼴 (표준 출력)

## 왜 있나

요강이 발표자료에 **성능 지표와 평가 기준**을 요구한다. 그 수를 슬라이드에
손으로 옮기면 결함 19(손계산을 문서로 옮김)의 자리다. 발표 스크립트
(`slides/make_10min_본선.py`)가 이 모듈을 **직접 불러** 수를 받는다.

## 평가 기준 — 무엇을 먼저 보나 (제안서 §4 · `CLAUDE.md §2`)

  1. **기각 정밀도** — 기각한 것 중 실제로 실패한 약의 비율 (기각이 맞았나 · «걸렀나» 는 재현율의 물음이다)
  2. **TP 오기각** — 성공한 약을 잘못 버린 비율 (걸러서는 안 될 것을 걸렀나)
  3. **Brier** — 확률이 정직한가. 널 모형(항상 기저율)과 **같이** 적는다.
     ECE 는 쓰지 않는다 — 균형 집합에서 널 모형의 ECE 가 0 이다(`README`)
  4. **AUROC 는 보조다** — 시스템은 «보류» 로 기권하고, AUROC 는 기권을
     0.5 쪽으로 밀어 넣는다. 그래도 **모델 기억과 파이프라인을 가르는 데**는
     쓴다(누출 제외 부분집합 · `홀드아웃_본선모델_결과 §2-⭐⭐`)

통계 함수는 `bench.run`(AUROC · Hanley–McNeil) 과 `bench.stats`(Wilson) 의
것을 **그대로** 쓴다. 차이의 구간은 짝지은 부트스트랩(시드 고정)이다.
**LLM 0회 · 네트워크 0회 · 파일을 쓰지 않는다.**
"""

import argparse
import json
import os
import random
import sys

SUBMIT = ("terra", "홀드아웃_본선모델.json")
# 같은 실행의 **상태 파일** — 기각 한 건마다 사유(F0 · 거부권 · 반박 우세)가 있다. 결과 파일에는 판정만 있다
SUBMIT_STATE = "상태_홀드본선_B5.json"
BOOT_N = 2000
BOOT_SEED = 20260925


def _w(k, n):
    from .stats import wilson
    lo, hi = wilson(k, n)
    return [k, n, lo, hi]


def _auc(scores, lab, idx):
    from .run import auroc, auroc_ci
    s = [scores[i] for i in idx]
    y = [lab[i] for i in idx]
    a = auroc(s, y)
    n1 = sum(y)
    lo, hi = auroc_ci(a, n1, len(y) - n1)
    return [a, lo, hi]


def _brier(scores, lab, idx):
    return sum((scores[i] - lab[i]) ** 2 for i in idx) / len(idx)


def _dauc_boot(s5, s0, lab, idx, reps=BOOT_N, seed=BOOT_SEED):
    """짝지은 부트스트랩 — 같은 문항을 뽑아 B5−B0 AUROC 차의 95% 구간."""
    from .run import auroc
    rnd = random.Random(seed)
    idx = list(idx)
    ds = []
    for _ in range(reps):
        b = [idx[rnd.randrange(len(idx))] for _ in idx]
        y = [lab[i] for i in b]
        if 0 < sum(y) < len(y):
            ds.append(auroc([s5[i] for i in b], y) - auroc([s0[i] for i in b], y))
    ds.sort()
    lo = ds[int(0.025 * len(ds))]
    hi = ds[int(0.975 * len(ds)) - 1]
    return lo, hi, len(ds)


def _tn_pair(v5, v0, tn):
    from .stats import mcnemar
    b = sum(1 for i in tn if v5[i] == "기각" and v0[i] != "실패")
    c = sum(1 for i in tn if v5[i] != "기각" and v0[i] == "실패")
    return {"B5만": b, "B0만": c, "p": mcnemar(b, c), "사후": True}


def block(d, idx):
    """한 부분집합(`idx`)의 수. B5 판정은 기각/보류/조건부/유망, B0 는 실패/모름/성공."""
    lab = [1 if r["label"] == "TP" else 0 for r in d["rows"]]
    b0, b5 = d["results"]["B0"], d["results"]["B5"]
    v5, v0 = b5["verdicts"], b0["verdicts"]
    idx = list(idx)
    tp = [i for i in idx if lab[i]]
    tn = [i for i in idx if not lab[i]]
    rej = [i for i in idx if v5[i] == "기각"]
    rej0 = [i for i in idx if v0[i] == "실패"]
    pro = [i for i in idx if v5[i] == "유망"]
    dist = {}
    for i in idx:
        dist[v5[i]] = dist.get(v5[i], 0) + 1
    base = sum(lab[i] for i in idx) / len(idx)
    a5 = _auc(b5["scores"], lab, idx)
    a0 = _auc(b0["scores"], lab, idx)
    return {
        "n": len(idx), "TP": len(tp), "TN": len(tn), "판정": dist,
        "기각정밀도": _w(sum(1 for i in rej if not lab[i]), len(rej)),
        "기각재현율": _w(sum(1 for i in tn if v5[i] == "기각"), len(tn)),
        "TP오기각": _w(sum(1 for i in tp if v5[i] == "기각"), len(tp)),
        "유망정밀도": _w(sum(1 for i in pro if lab[i]), len(pro)),
        "보류": _w(dist.get("보류", 0), len(idx)),
        "B0실패정밀도": _w(sum(1 for i in rej0 if not lab[i]), len(rej0)),
        "B0실패재현율": _w(sum(1 for i in tn if v0[i] == "실패"), len(tn)),
        "B0TP오기각": _w(sum(1 for i in tp if v0[i] == "실패"), len(tp)),
        "B0모름": _w(sum(1 for i in idx if v0[i] == "모름"), len(idx)),
        # 모델 단독이 «성공» 이라 한 것 중 실제 성공 — **사후 관찰**(명세에 없다)
        "B0성공정밀도": _w(sum(1 for i in idx if v0[i] == "성공" and lab[i]),
                        sum(1 for i in idx if v0[i] == "성공")),
        # TN 기각의 짝 비교 — B5 만 기각 · B0 만 «실패» (McNemar · **사후**)
        "TN기각짝": _tn_pair(v5, v0, tn),
        "AUROC": {"B0": a0, "B5": a5},
        "Brier": {"B0": _brier(b0["scores"], lab, idx), "B5": _brier(b5["scores"], lab, idx),
                  "널": base * (1 - base)},
    }


def load(root="."):
    """제출 모델 결과 · 라벨(TP=1) · 누출 제외 색인."""
    with open(os.path.join(root, SUBMIT[1]), encoding="utf-8") as f:
        d = json.load(f)
    lab = [1 if r["label"] == "TP" else 0 for r in d["rows"]]
    leak = d["results"]["B0"].get("leak") or [False] * len(lab)
    ex = [i for i in range(len(lab)) if not leak[i]]
    return d, lab, ex


def unknown_idx(b0):
    """모델 단독(B0)이 **«모름»** 이라 답한 문항 — **라벨을 안 보고** 고른 부분집합.

    ## ⛔ 09-25 · 왜 «누출 제외» 대신 이것인가 (결함 334)

    «누출 제외» 는 `closedbook.leakage_flag` 로 고른다 — **«라벨과 일치 + 고확신»**
    인 것만 뺀다. 그러면 **고확신 오답은 남는다**(terra 37 · mini 40 · sol 41 ·
    luna 40). 남은 부분집합에서 B0 의 가장 센 답은 **정의상 전부 틀린 답**이 되고,
    B0 AUROC 가 0.5 **아래로** 기계적으로 밀린다(0.490~0.505). *«모델 단독은 동전
    던지기»* 는 **일부가 선택의 산물**이었다.

    «모름» 은 B0 의 **출력만으로** 고른다 — 정답을 안 본다. 여기서 B0 는 정의상
    0.5(정보 없음)이고, 파이프라인이 그 위에서 얼마나 가르는지가 곧 **모델 기억
    밖에서의 값**이다. ⚠ 09-25 에 결과를 본 뒤 정한 부분집합이다 — **사후**라고 적는다.
    """
    return [i for i, v in enumerate(b0["verdicts"]) if v == "모름"]


def reject_split(root, d):
    """기각을 **두 갈래**로 — F0(약 이름이 문헌에서 한 건도 안 잡혀 끊음) · 근거 기반(거부권 + 반박 우세).

    ## 왜 (09-29 · 결함 379)

    외부 감사가 잡았다 — 헤드라인 «기각 99/105» 와 «모름 445쌍의 38/41» 에 **근거를 읽지 않고 끊은
    기각**이 섞여 있다(F0 · 대부분 개발 코드 · 용량이 붙은 개입 이름). 정의는 `rejectsplit` 한 곳을 쓴다.
    상태 파일이 없거나 결과 파일과 **행 · 라벨 · 판정이 하나라도 안 맞으면 None** — 섞어 세지 않는다.
    반환: {"전체"|"모름": {"F0": [TN, TP], "근거": [TN, TP]}}
    """
    p = os.path.join(root, SUBMIT_STATE)
    if not os.path.exists(p):
        return None
    from . import rejectsplit as _RS
    with open(p, encoding="utf-8") as f:
        cands = (json.load(f) or {}).get("candidates") or []
    rows, v5 = d["rows"], d["results"]["B5"]["verdicts"]
    if len(cands) != len(rows) or any(c.get("label") != r["label"] or c.get("verdict") != v
                                      for c, r, v in zip(cands, rows, v5)):
        return None

    def tally(idx):
        t = {"F0": [0, 0], "근거": [0, 0]}
        for i in idx:
            k = _RS.kind(cands[i])
            if k:
                t["F0" if k == _RS.F0 else "근거"][0 if cands[i]["label"] == "TN" else 1] += 1
        return t
    return {"전체": tally(range(len(cands))), "모름": tally(unknown_idx(d["results"]["B0"]))}


def card(root="."):
    name, path = SUBMIT
    d, lab, ex = load(root)
    n = len(lab)
    leak = d["results"]["B0"].get("leak") or [False] * n
    unk = unknown_idx(d["results"]["B0"])
    out = {"모델": name, "파일": path, "전체": block(d, range(n)),
           "모름": block(d, unk),
           "누출제외": block(d, ex), "누출": sum(1 for x in leak if x),
           "누출제외_고확신오답": sum(1 for i in ex if d["results"]["B0"]["conf"][i] == "high"
                                and d["results"]["B0"]["verdicts"][i] != "모름"),
           "기각갈래": reject_split(root, d)}
    lo, hi, k = _dauc_boot(d["results"]["B5"]["scores"], d["results"]["B0"]["scores"], lab, ex)
    a = out["누출제외"]["AUROC"]
    out["누출제외"]["ΔAUROC"] = [a["B5"][0] - a["B0"][0], lo, hi, k]
    # 네 모델 — ① 누출 제외 B5 (명세 0922 §2 · `indep` 와 같은 함수 · 라벨 의존)
    #          ② 자기 B0 가 «모름» 인 문항의 B5 (라벨 무관 · 사후)
    from . import indep
    from .run import auroc, auroc_ci
    runs = indep.load_runs(root=root)
    s, common, _ = indep.summarize(runs)
    out["모델들"] = []
    for x, r in zip(s, runs):
        u = unknown_idx(r["결과"]["B0"]) if r["결과"]["B0"].get("verdicts") else []
        y = [lab[i] for i in u]
        au = auroc([r["결과"]["B5"]["scores"][i] for i in u], y) if u else None
        ci = auroc_ci(au, sum(y), len(y) - sum(y)) if u else (None, None)
        out["모델들"].append({"이름": x["이름"], "n": x["n누출제외"], "B5": list(x["B5"]),
                           "B0": list(x["B0"]), "모름n": len(u), "모름B5": [au, ci[0], ci[1]]})
    out["공통구간"] = list(indep.overlap([(x["B5"][1], x["B5"][2]) for x in s]) or [])
    mm = [m["모름B5"] for m in out["모델들"] if m["모름B5"][0] is not None]
    out["모름공통구간"] = list(indep.overlap([(m[1], m[2]) for m in mm]) or []) if mm else []
    return out


def _pct(w):
    k, n, lo, hi = w
    if not n:
        return "0/0 — 해당 없음"          # 0% 로 찍지 않는다 — 침묵과 0 은 다르다
    return "%d/%d = %.1f%% [%.1f–%.1f]" % (k, n, 100.0 * k / n, 100 * lo, 100 * hi)


def report(c):
    print("성능 한 장 — %s (%s)" % (c["모델"], c["파일"]))
    head = {"전체": "전체",
            "모름": "모델 단독이 «모름» — 라벨 무관 · 사후 (발표에 쓰는 쪽)",
            "누출제외": "누출 제외 — ⚠ 라벨 의존: 고확신 오답 %d 이 남아 B0 가 기계적으로 낮다(결함 334)"
                      % c["누출제외_고확신오답"]}
    for key in ("전체", "모름", "누출제외"):
        b = c[key]
        print("\n[%s] n=%d (TP %d · TN %d)" % (head[key], b["n"], b["TP"], b["TN"]))
        print("  판정     " + " · ".join("%s %d" % kv for kv in sorted(b["판정"].items())))
        print("  기각 정밀도   " + _pct(b["기각정밀도"]))
        print("  기각 재현율   " + _pct(b["기각재현율"]))
        print("  TP 오기각     " + _pct(b["TP오기각"]))
        print("  유망 정밀도   " + _pct(b["유망정밀도"]))
        print("  보류          " + _pct(b["보류"]))
        print("  (B0 «실패» 정밀도 " + _pct(b["B0실패정밀도"]) + " · 재현율 "
              + _pct(b["B0실패재현율"]) + ")")
        print("  (B0 «성공» 정밀도 " + _pct(b["B0성공정밀도"]) + " — 사후)")
        tp_ = b["TN기각짝"]
        print("  (TN 기각 짝 — B5 만 %d · B0 만 %d · McNemar p = %.3g — 사후)"
              % (tp_["B5만"], tp_["B0만"], tp_["p"]))
        a = b["AUROC"]
        print("  AUROC   B0 %.3f [%.3f–%.3f] · B5 %.3f [%.3f–%.3f]" % (tuple(a["B0"]) + tuple(a["B5"])))
        br = b["Brier"]
        print("  Brier   B0 %.4f · B5 %.4f · 널 %.4f" % (br["B0"], br["B5"], br["널"]))
        if "ΔAUROC" in b:
            print("  ΔAUROC(B5−B0) %.3f [%.3f, %.3f]  (짝지은 부트스트랩 %d회)" % tuple(b["ΔAUROC"]))
    print("\n[모델들] B5 AUROC — 누출 제외(명세 0922 · 라벨 의존) · 자기 B0 «모름»(라벨 무관 · 사후)")
    for m in c["모델들"]:
        mu = m["모름B5"]
        print("  %-6s 누출 제외 %.3f [%.3f–%.3f] n=%d (B0 %.3f)  ·  모름 %s n=%d"
              % ((m["이름"],) + tuple(m["B5"]) + (m["n"], m["B0"][0])
                 + (("%.3f [%.3f–%.3f]" % tuple(mu)) if mu[0] is not None else "—", m["모름n"])))
    if c["공통구간"]:
        print("  → 누출 제외 CI 공통 [%.3f, %.3f]" % tuple(c["공통구간"]))
    if c.get("모름공통구간"):
        print("  → 모름 CI 공통 [%.3f, %.3f]" % tuple(c["모름공통구간"]))


MD_START = "<!-- perfcard:start — 이 사이는 `py -m bioreroute.bench.perfcard --md-into` 가 쓴다. 손으로 고치지 마라 -->"
MD_END = "<!-- perfcard:end -->"


def _cell(w):
    k, n, lo, hi = w
    return ("%d/%d = %.1f%% [%.1f–%.1f]" % (k, n, 100.0 * k / n, 100 * lo, 100 * hi)) if n else "—"


def _n(w):
    """분수만 — `k/n`. 분모가 0 이면 «—» (침묵과 0 은 다르다)."""
    return ("%d/%d" % (w[0], w[1])) if w[1] else "—"


def _split_rows(c):
    """§4.1 표의 기각 정밀도 아래 두 줄 — F0 갈래 · 근거 기반. 상태 파일이 없으면 줄이 없다."""
    sp = c.get("기각갈래")
    if not sp:
        return []

    def _p2(t):
        return _cell(_w(t[0], t[0] + t[1]))
    return ["| └ 근거로 한 기각만 (거부권 + 반박 우세) | %s | — | %s |" % (_p2(sp["전체"]["근거"]), _p2(sp["모름"]["근거"])),
            "| └ F0 기각 — 약 이름이 문헌에서 한 건도 안 잡힘 | %s | — | %s |" % (_p2(sp["전체"]["F0"]), _p2(sp["모름"]["F0"]))]


def to_md(c, root="."):
    """보고서 §4.1 — 수는 전부 `card()` 에서. 표적 재시험 · 추출 복제는 결과 파일이 있을 때만.

    09-26 · 보고서를 최종 결과로 다시 쓰면서 이 절도 바꿨다 —
      · **모델 단독(B0) 열을 같이 싣는다.** 헤드라인 지표(기각 정밀도)의 기준선이 표에 없었고,
        그 기준선이 더 높았다(96.8% 대 94.3%). 기준선 없는 수는 선택적 보고다.
      · «조건부» 줄을 더했다 — 판정 칸의 합이 n 과 같아야 한다.
      · «순위는 모델에 안 달렸다» → «이 표본으로는 못 가른다». 구간이 겹친다 ≠ 같다.
      · 제목에서 날짜·«지금 이 시스템» 같은 이력 말투를 뺐다. 내부 절 표시(§2-⭐)도 뺐다.
    """
    from . import resultmd as RM
    b, u = c["전체"], c["모름"]
    rej5, rej0 = b["판정"].get("기각", 0), b["B0실패정밀도"][1]
    uk = u["판정"]
    L = ["### 4.1 본선 홀드아웃 %d쌍 — 파이프라인과 모델 단독" % b["n"],
         "",
         "> 수는 `py -m bioreroute.bench.perfcard` 가 결과 파일(`%s`)에서 낸다 — 손으로 옮기지 않았다. "
         "발표의 성능 장도 같은 함수를 부른다. 모델 `gpt-5.6-terra` · seed 42 · 결과를 보기 전에 봉인한 "
         "명세대로 돌린 **첫 실행**이 이 표다 — 같은 홀드아웃의 **두 번째 개봉**이다(첫 개봉은 개발 단계 모델). "
         "그 뒤 같은 홀드아웃에서 seed 복제 · 시점 차단 · 다른 모델 둘(sol · luna)을 더 돌렸고(§4.4 · §4.7), "
         "뒤의 실행은 이 표의 수를 고르는 데 쓰지 않았다." % c["파일"],
         "",
         "**평가 기준 — 이 순서로 본다** (제안서 §4)",
         "",
         "1. **기각이 맞았나** — 기각 정밀도(기각한 것 중 실제로 실패한 약)",
         "2. **맞는 것을 버렸나** — 성공한 약을 기각한 비율",
         "3. **모르면 모른다고 하나** — 보류 비율 · Brier 를 **널 모형(늘 기저율)과 나란히**. "
         "ECE 는 쓰지 않는다 — 균형 집합에서 널 모형의 ECE 가 0 이다",
         "4. **모델 기억이 아닌가** — 모델 단독(B0)을 같은 쌍에 나란히 적고, 모델이 문헌 없이 «모름» 이라 한 "
         "문항에서 따로 잰다. AUROC 는 보조다(«보류» 를 0.5 로 뭉갠다)",
         "",
         "| 지표 | 파이프라인 B5 · 전체 %d쌍 | 모델 단독 B0 · 전체 %d쌍 | B5 · 모델이 «모름» 이라 한 %d쌍 (**사후**) |"
         % (b["n"], b["n"], u["n"]),
         "|---|---|---|---|",
         "| 기각 정밀도 (B0 는 «실패») | %s | %s | %s |"
         % (_cell(b["기각정밀도"]), _cell(b["B0실패정밀도"]), _cell(u["기각정밀도"])),
         ] + _split_rows(c) + [
         "| 기각 재현율 (TN 중) | %s | %s | %s |"
         % (_cell(b["기각재현율"]), _cell(b["B0실패재현율"]), _cell(u["기각재현율"])),
         "| 성공한 약을 버림 (TP 중) | %s | %s | %s |"
         % (_cell(b["TP오기각"]), _cell(b["B0TP오기각"]), _cell(u["TP오기각"])),
         "| «유망» 정밀도 (B0 는 «성공») | %s | %s | %s |"
         % (_cell(b["유망정밀도"]), _cell(b["B0성공정밀도"]), _cell(u["유망정밀도"])),
         "| 보류 (B0 는 «모름») | %s | %s | %s |"
         % (_cell(b["보류"]), _cell(b["B0모름"]), _cell(u["보류"])),
         "| 조건부 | %d/%d | — | %d/%d |" % (b["판정"].get("조건부", 0), b["n"], uk.get("조건부", 0), u["n"]),
         "| AUROC [95%% CI] | %.3f [%.3f–%.3f] | %.3f [%.3f–%.3f] | %.3f [%.3f–%.3f] · B0 는 정의상 0.500 |"
         % (tuple(b["AUROC"]["B5"]) + tuple(b["AUROC"]["B0"]) + tuple(u["AUROC"]["B5"])),
         "| Brier (널 모형) | %.3f (%.3f) | %.3f (%.3f) | %.3f (%.3f) |"
         % (b["Brier"]["B5"], b["Brier"]["널"], b["Brier"]["B0"], b["Brier"]["널"],
            u["Brier"]["B5"], u["Brier"]["널"]),
         ""]
    tp = b["TN기각짝"]
    sp = c.get("기각갈래")
    if sp:
        f0t, evt = sp["전체"]["F0"], sp["전체"]["근거"]
        f0u, evu = sp["모름"]["F0"], sp["모름"]["근거"]
        L.append("**기각의 3분의 1은 근거를 읽지 않고 끊은 것이다.** 기각 %d건 중 %d건은 약 이름이 문헌에서 한 건도 "
                 "안 잡혀 F0 에서 끊었다(%d건이 실패한 약) — 대부분 임상 등록부의 개입명이 개발 코드나 용량이 붙은 "
                 "문자열이라서다. **근거로 기각한 %d건만 보면 %d건이 실패한 약이다**(%s). 헤드라인 정밀도는 F0 갈래가 "
                 "만든 수가 아니다. 다만 F0 갈래는 자료원 차이(실패한 쪽에 개발 코드가 많다)를 그대로 싣는다."
                 % (f0t[0] + f0t[1] + evt[0] + evt[1], f0t[0] + f0t[1], f0t[0], evt[0] + evt[1], evt[0],
                    _cell(_w(evt[0], evt[0] + evt[1]))))
        L.append("")
    L.append("**전체 표본에서는 모델 기억이 더 잘 거른다.** 모델 단독은 %d건을 «실패» 로 버렸고 파이프라인은 "
             "%d건을 기각했다. TN 에서 짝지어 보면 모델 단독만 버린 쌍 %d · 파이프라인만 버린 쌍 %d "
             "(McNemar p = %.2g · **사후**). AUROC 와 Brier 도 구별되지 않는다 — **이 표본에서 모델 단독에 대한 "
             "우위를 주장하지 않는다.**" % (rej0, rej5, tp["B0만"], tp["B5만"], tp["p"]))
    L.append("")
    # 09-26 · «모델 단독은 하나도 거르지 못한다» 는 **정의상 참**이다(«모름» 이라 답한 쌍만 모았으므로).
    #   그것을 모델의 실패처럼 읽히게 두면 동어반복을 성과로 파는 셈이다. 비교 대상은 모델 단독이 아니라
    #   **이 부분집합의 실패 기저율**(무작위로 기각할 때의 정밀도)이다 — 그 수를 같이 적는다.
    tn_u = u["B0실패재현율"][1]
    L.append("**파이프라인의 몫은 모델이 모르는 곳이다.** 모델 단독이 «모름» 이라 답한 %d쌍에서 모델 단독은 "
             "정의상 아무것도 거르지 않는다(%s). 여기서 파이프라인은 %d건을 기각했고 %d건이 맞았다 — 이 부분집합의 "
             "실패 비율은 %d/%d = %.1f%% 라, 무작위로 기각하면 정밀도가 그 근처다. 이 부분집합은 결과를 본 뒤 "
             "정했다(**사후**) — 다만 라벨이 아니라 **모델의 출력만으로** 고른다.%s"
             % (u["n"], _n(u["B0실패재현율"]), u["기각정밀도"][1], u["기각정밀도"][0],
                tn_u, u["n"], (100.0 * tn_u / u["n"]) if u["n"] else 0.0,
                (" **그 기각 %d건 중 %d건은 F0(약 이름 미검출)이고, 근거로 기각한 것은 %d건(%d건 맞음)이다** — "
                 "표본이 작아 방향으로만 읽는다. 문헌량 균형은 이 부분집합에서 재지 않았다(§4.9 의 교란과 같은 모양일 수 있다)."
                 % (sum(sp["모름"]["F0"]) + sum(sp["모름"]["근거"]), sum(sp["모름"]["F0"]),
                    sum(sp["모름"]["근거"]), sp["모름"]["근거"][0])) if sp else ""))
    L.append("")
    mods = [m for m in c["모델들"] if m["모름B5"][0] is not None]
    L.append("**모델 %d개** — «모름» 문항의 파이프라인 AUROC: %s · 95%% CI 가 모두 겹친다(공통 %s · 사후). "
             "**이 표본으로는 모델 간 차이를 가르지 못한다.**"
             % (len(mods), " · ".join("%s %.3f" % (m["이름"], m["모름B5"][0]) for m in mods),
                ("[%.3f, %.3f]" % tuple(c["모름공통구간"])) if c.get("모름공통구간") else "없음"))
    L.append("")
    res = RM.load(os.path.join(root, RM.TARGETED_JSON))
    if res and not res.get("유효성"):
        m = res["주검정"]
        # 09-29 · 결함 379 — «기각 문턱은 모델에 달렸다» 는 sol 한 모델의 관찰을 일반화했고, p 는 같은 27쌍을
        #   seed 셋으로 합친 값이다(독립 과대평가). seed 별 p 와 확인 검정(terra–luna · 못 갈랐다)을 같이 적는다
        per = [x.get("p") for x in (res.get("seed별") or []) if isinstance(x, dict) and x.get("p") is not None]
        L.append("**기각을 많이 하는 정도는 sol 에서 되풀이해 달랐다** — 표적 재시험(사전 지정 · 새 seed 셋): sol 만 기각 %d · "
                 "luna 만 기각 %d · 합산 McNemar p = %.2g — 같은 27쌍을 seed 셋으로 합친 값이라 독립을 과대평가한다%s. "
                 "두 모델이 처음 갈렸던 27쌍에 한정한 결과이고, terra 와 luna 의 확인 검정은 갈리지 않았다."
                 % (m["A만"], m["B만"], m["p"],
                    (" (seed 별 p = %s)" % " · ".join("%.2g" % v for v in per)) if per else ""))
        L.append("")
    o = RM.load(os.path.join(root, RM.REPLICATE_JSON))
    sl = RM.slide_lines(None, o) if o else {}
    if sl.get("seed"):
        L.append("**seed 흔들림** — 같은 모델·다른 seed 판정 불일치 %s · 다른 모델 %s → %s "
                 "(추출 복제 · 사전 지정)." % (sl["seed"], sl["모델"], sl.get("말", "")))
    else:
        L.append("**seed 흔들림** — 추출 복제(명세 `사전명세_추출복제_0924.md`)가 **돌고 있다.** "
                 "결과가 나오면 이 줄을 `--md-into` 로 다시 쓴다.")
    L.append("")
    L.append("⚠ **한계** — ① TP(RepoDB 승인)는 모델이 학습 중 봤을 가능성이 크다 — 전체 표본의 모델 단독은 "
             "**암기 천장**이다 ② «모름» 부분집합은 **사후**다 ③ 라벨로 걸러 낸 «누출 제외» 부분집합은 모델 "
             "단독을 기계적으로 낮춘다(고확신 오답 %d건이 남는다) — 비교에 쓰지 않는다." % c["누출제외_고확신오답"])
    return "\n".join(L)


def md_into(path, c, root="."):
    """`path` 안의 표시 사이를 새 절로 바꾼다. 표시가 없으면 **안 쓰고** 알린다."""
    raw = open(path, "rb").read()
    text = raw.decode("utf-8-sig")
    i, j = text.find(MD_START), text.find(MD_END)
    if i < 0 or j < i:
        return False
    new = text[:i] + MD_START + "\n" + to_md(c, root) + "\n" + text[j:]
    with open(path, "wb") as f:
        f.write((b"\xef\xbb\xbf" if raw[:3] == b"\xef\xbb\xbf" else b"") + new.encode("utf-8"))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="성능 한 장")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--md", action="store_true", help="보고서 절(마크다운)을 표준 출력으로")
    ap.add_argument("--md-into", default=None,
                    help="그 파일의 perfcard 표시 사이를 새 절로 바꾼다 (표시가 없으면 안 쓴다)")
    a = ap.parse_args(argv)
    c = card(a.root)
    if a.md_into:
        ok = md_into(a.md_into, c, a.root)
        print(("→ %s 의 성능 절을 다시 썼다" if ok else "⛔ %s 에 perfcard 표시가 없다 — 안 썼다") % a.md_into)
        return 0 if ok else 2
    if a.json:
        print(json.dumps(c, ensure_ascii=False, indent=1))
    elif a.md:
        print(to_md(c, a.root))
    else:
        report(c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
