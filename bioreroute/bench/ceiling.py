# -*- coding: utf-8 -*-
"""천장 측정 — 우리가 못 찾은 것인가, 애초에 없는 것인가.

실측 기각 재현율은 21%(9/42)였다. 이걸 시스템 실패로 읽기 전에 확인할 것이 있다.

  중단된 임상시험의 1차 결과가 **논문으로 출판되는 비율은 22%**다
  (Williams et al., PLOS One 2015, 198/905).

우리 재현율 21%와 거의 같다. 즉 **PubMed만 읽는 한 우리 성능의 상한이
출판 편향에 의해 정해져 있을 수 있다.** 이건 알고리즘으로 못 넘는다.

그런데 같은 연구가 결정적인 사실을 하나 더 준다.
**시험 데이터에 근거해 중단한 경우, ClinicalTrials.gov 결과 등록률은 91%인
반면 논문 출판률은 46%다.** 우리 TN은 정확히 그 부류(효능·안전성 실패)다.

  → 근거는 존재한다. PubMed가 아니라 등록부에 있을 뿐이다.

이 도구는 우리 TN 각각에 대해 CT.gov 결과 등록 여부를 세어 **실제 천장**을
측정한다. 추정이 아니라 우리 데이터에서 직접 잰다.

━━━ 첫 판에서 이 도구가 틀린 것을 쟀다 ━━━

  처음에는 `r["nct"]`, 즉 **라벨 출처 시험 자체**만 조회했다. 71%가 나왔고
  "근거를 3.2배 확보할 수 있다"고 출력했다. **그 숫자는 쓸 수 없다.**

  라벨 출처 시험은 누출 차단으로 근거에서 제외된다. TN 라벨이 "NCT12345가
  futility로 중단"에서 왔는데 그 NCT의 결과를 읽어 기각하면, 예측이 아니라
  답안지를 베낀 것이다. **답을 정한 시험이 등록부에 있는 건 당연하다.**

  물어야 할 것은 이것이다 —
      "라벨 출처를 뺀 **독립** 시험 중 결과가 올라온 게 있는가"

  그게 있어야만 B6가 B5보다 나을 수 있다. 없으면 등록부를 읽어도
  새 근거가 안 들어오므로 두 구성은 같아진다.

  그래서 두 숫자를 따로 낸다. 앞의 것은 참고, 뒤의 것이 결정 지표다.

실행: py -m bioreroute.bench.ceiling bench_matched.csv
"""

import argparse
import csv
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request

API = "https://clinicaltrials.gov/api/v2/studies/%s?format=json"
TIMEOUT = 25
DELAY = 0.2
_ctx = ssl.create_default_context()


# 캐시 항목의 판 번호. **필드를 추가하면 반드시 올려라.**
#
#   실측 사고: randomized·comparative 필드를 추가했는데 판 번호를 안 올려
#   옛 캐시 항목이 그대로 반환됐다. 그 항목엔 새 필드가 없어 전부 거짓이 되어
#   "무작위배정 0/42 = 0%"라는 **가짜 결정 지표**가 나왔다.
#   그 숫자만 보고 B6를 접었으면 캐시 때문에 방향을 버리는 것이었다.
#
#   등록부 본문(CTGR2→CTGR3)에서 같은 실수를 이미 겪고 고쳤는데
#   이 파일에는 적용하지 않았다. 교훈은 파일 단위로 새지 않는다.
SCHEMA = 2


def fetch(nct, cache):
    # 판 번호와 필드 존재를 **둘 다** 본다. 어느 하나만으로는 새 필드를
    #   추가하면서 판 올리기를 잊었을 때 잡지 못한다.
    hit = cache.get(nct)
    if (hit is not None and hit.get("_v") == SCHEMA
            and all(k in hit for k in ("randomized", "comparative", "phase1_only"))):
        return hit
    out = {"nct": nct, "_v": SCHEMA, "has_results": False, "n_outcomes": 0,
           "has_stats": False, "randomized": False, "phase1_only": False,
           "comparative": False, "error": None}
    try:
        req = urllib.request.Request(API % urllib.parse.quote(nct),
                                     headers={"User-Agent": "Bio-ReRoute"})
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
            d = json.loads(r.read().decode("utf-8"))
        rs = d.get("resultsSection") or {}
        om = (rs.get("outcomeMeasuresModule") or {}).get("outcomeMeasures") or []
        out["has_results"] = bool(rs)
        out["n_outcomes"] = len(om)
        # 통계 분석까지 올라와 있으면 효능 판단에 직접 쓸 수 있다
        out["has_stats"] = any((o.get("analyses") or []) for o in om)

        # **결과가 있다고 반증에 쓸 수 있는 게 아니다.**
        #   실측: 등록부에서 끌어온 25건이 전부 단일군·용량증량 시험이었다.
        #   대조군이 없으면 반응률이 얼마든 효능을 반증할 수 없다.
        #   결과 존재만 세면 근거 가용성을 크게 과대평가한다.
        p = d.get("protocolSection", {})
        alloc = (((p.get("designModule") or {}).get("designInfo") or {})
                 .get("allocation") or "")
        phases = (p.get("designModule") or {}).get("phases") or []
        out["randomized"] = "RANDOMIZED" == alloc.upper()
        out["phase1_only"] = bool(phases) and all("PHASE1" in x for x in phases)
        # 반증에 쓸 수 있는 조건: 무작위배정 + 1차 평가변수 결과 + 1상 전용 아님
        out["comparative"] = bool(out["randomized"] and len(om) > 0
                                  and not out["phase1_only"])
        out["participants"] = ((rs.get("participantFlowModule") or {})
                               .get("groups") and True or False)
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    cache[nct] = out
    time.sleep(DELAY)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("matched", nargs="?", default="bench_matched.csv")
    ap.add_argument("--cache", default="ctgov_results_cache.json")
    ap.add_argument("--out", default="bench_ceiling.csv")
    ap.add_argument("--stratum", default="A",
                    help="A | B | all — bench.run 과 반드시 같아야 한다")
    ap.add_argument("--search-limit", type=int, default=20,
                    help="쌍당 등록부 검색 결과 상한")
    ap.add_argument("--max-fetch", type=int, default=8,
                    help="쌍당 실제로 열어볼 독립 시험 수 (시간 제한)")
    # ⛔ 09-25 · 결함 335 — 이 경로가 **박혀 있어서** 시험(`[6]`)이 모의 검색
    #   응답을 실제 `ctgov_search_cache.json` 에 섞었다(7개 · 무해 확인).
    #   기본값은 그대로, 시험은 임시 경로를 준다.
    ap.add_argument("--search-cache", default="ctgov_search_cache.json",
                    help="등록부 **검색** 캐시 (기본값이 실제 파일이다)")
    a = ap.parse_args(argv)

    # 층을 안 맞추면 **다른 집합을 재게 된다.**
    #   실측 사고: ceiling은 TN 49건(전 층), bench.run은 42건(기본값 층 A)을
    #   써서 "한계 기여 19/49"가 실제로 돌릴 42건과 다른 모집단의 숫자였다.
    #   기본값을 run.py와 같게 맞춘다.
    rows = [r for r in csv.DictReader(open(a.matched, encoding="utf-8-sig"))
            if r["label"] == "TN" and r.get("nct", "").startswith("NCT")
            and (a.stratum == "all" or r.get("stratum") == a.stratum)]
    try:
        cache = json.load(open(a.cache, encoding="utf-8"))
    except Exception:
        cache = {}

    print("=" * 78)
    print("천장 측정 — 반증 근거가 어디에 있는가")
    print("=" * 78)
    print("층 %s · TN %d건의 등록 시험에 결과가 올라와 있는지 확인한다."
          % (a.stratum, len(rows)))
    print("  ※ 이 층은 bench.run 의 --stratum 과 **같아야** 비교가 성립한다.\n")
    if not rows:
        print("해당 층에 NCT가 있는 TN이 없다. --stratum 을 확인하라.")
        return 1

    # 직접 조회만 되고 **검색**이 안 되면 등록부 게이트는 무용지물이다.
    #   ceiling이 통과했는데 본 측정에서 0건이 나오는 사고를 막는다.
    from ..io import sources as _S
    from ..io import cache as _C
    _C.configure(a.search_cache)
    _C.load()
    print("[사전 점검] 등록부 검색 경로")
    ok_s = 0
    for r in rows[: min(5, len(rows))]:
        q = _S.ctgov_search(r["drug"], r["indication"], 5)
        mark = "OK  " if q["ncts"] else "0건 "
        if q.get("error"):
            mark = "실패"
        print("  %s %-22s %-26s %s" % (mark, r["drug"][:22], r["indication"][:26],
                                       q.get("error") or "%d건 (%s)" % (len(q["ncts"]),
                                                                        q.get("how", ""))))
        ok_s += 1 if q["ncts"] else 0
    _C.save()
    if ok_s == 0:
        print("  → 검색이 하나도 안 된다. 등록부 게이트가 작동하지 않는다.")
        print("     약물명 동의어(hydroxycarbamide vs hydroxyurea)를 의심하라.")
    print("")

    # ── ① 라벨 출처 시험 자체 (참고용, **근거로는 못 쓴다**) ────
    res = []
    for i, r in enumerate(rows, 1):
        res.append((r, fetch(r["nct"], cache)))
        if i % 10 == 0 or i == len(rows):
            print("  %d/%d" % (i, len(rows)))
            json.dump(cache, open(a.cache, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(cache, open(a.cache, "w", encoding="utf-8"), ensure_ascii=False)

    err = sum(1 for _, x in res if x["error"])
    ok = [(r, x) for r, x in res if not x["error"]]
    m = max(1, len(ok))
    has = sum(1 for _, x in ok if x["has_results"])
    with_om = sum(1 for _, x in ok if x["n_outcomes"] > 0)
    with_st = sum(1 for _, x in ok if x["has_stats"])

    print("\n[참고] 라벨 출처 시험 자체의 결과 등록률 (조회 성공 %d · 실패 %d)"
          % (len(ok), err))
    print("  결과 섹션 존재       %3d/%d = %.0f%%" % (has, m, 100 * has / m))
    print("  1차 평가변수 수치    %3d/%d = %.0f%%" % (with_om, m, 100 * with_om / m))
    print("  통계 분석까지 있음   %3d/%d = %.0f%%" % (with_st, m, 100 * with_st / m))
    print("  ※ **이 숫자는 성능 근거가 아니다.** 라벨 출처 시험은 누출 차단으로")
    print("     근거에서 제외된다(bench/run.py --allow-label-nct 없이는 안 읽는다).")
    print("     '답을 정한 시험이 등록부에 있다'는 것은 당연한 이야기다.")

    # ── ② 독립 시험 — 이게 B6의 생사를 정한다 ──────────────────
    print("\n[본 측정] 라벨 출처를 뺀 **독립** 시험이 있는가")
    print("  실제로 쓸 수 있는 근거만 센다. 각 쌍을 등록부에서 검색해")
    print("  라벨 출처 NCT를 제외하고, 남은 시험에 결과가 있는지 본다.\n")
    indep = []
    for i, r in enumerate(rows, 1):
        q = _S.ctgov_search(r["drug"], r["indication"], a.search_limit)
        cands = [n for n in q["ncts"] if n != r["nct"]][: a.max_fetch]
        got = [fetch(n, cache) for n in cands]
        with_res = [g for g in got if not g["error"] and g["n_outcomes"] > 0]
        # **결과가 있다 ≠ 반증에 쓸 수 있다.** 대조군이 없으면 못 쓴다.
        usable = [g for g in with_res if g.get("comparative")]
        with_stats = [g for g in usable if g["has_stats"]]
        indep.append({"row": r, "found": len(q["ncts"]), "indep": len(cands),
                      "with_res": len(with_res),
                      "usable": len(usable), "stats": len(with_stats),
                      "how": q.get("how", ""), "err": q.get("error"),
                      "ncts": [g["nct"] for g in usable]})
        if i % 10 == 0 or i == len(rows):
            print("  %d/%d" % (i, len(rows)))
            json.dump(cache, open(a.cache, "w", encoding="utf-8"), ensure_ascii=False)
            _C.save()
    json.dump(cache, open(a.cache, "w", encoding="utf-8"), ensure_ascii=False)
    _C.save()

    # ── **조회 실패와 '찾았는데 없음'을 섞지 않는다** (결함 35) ──────────
    #
    #   전에는 `x["indep"] > 0` 만 셌다. 검색이 오류로 죽어도 indep=0 이라
    #   "독립 시험 0건"으로 집계돼 **네트워크가 막힌 환경에서 0%가 결과로
    #   보고됐다.** 그리고 그 0%는 *"반증 근거의 부재가 구조적"* 이라는
    #   우리 논지를 **지지하는** 방향이라 더 위험했다.
    #
    #   실측: 샌드박스에서 CT.gov 가 403으로 전부 막혔는데 화면에는
    #   "0/14 = 0% · **B6를 빼라**" 가 떴다. 하마터면 그대로 적을 뻔했다.
    #
    #   결함 6("LLM 없이 돌려도 완전한 결과표")과 같은 유형이고,
    #   `[18] 0건과 오류의 구분` 시험이 이미 다른 모듈에 있었다.
    #   **교훈은 파일 단위로 전파되지 않는다**(실패 양상 4).
    bad = [x for x in indep if x["err"]]
    good = [x for x in indep if not x["err"]]
    N_all, N = len(indep), len(good)

    print("\n" + "=" * 78)
    print("결정 지표 — B6(등록부 게이트)를 돌릴 가치가 있는가")
    print("=" * 78)
    if bad:
        print("  [조회 실패] %d/%d 쌍 — **이 쌍들은 분모에서 뺀다.**"
              % (len(bad), N_all))
        for x in bad[:3]:
            print("     %-22s %-24s %s" % (x["row"]["drug"][:22],
                                           x["row"]["indication"][:24],
                                           str(x["err"])[:40]))
        if len(bad) > 3:
            print("     … 외 %d건" % (len(bad) - 3))
    if not N:
        print("\n  **성공한 조회가 하나도 없다. 판단하지 않는다.**")
        print("  0%는 '근거가 없다'가 아니라 '못 물어봤다'이다. 둘을 섞으면")
        print("  네트워크 장애가 발견으로 둔갑한다. 연결을 고치고 다시 돌려라.")
        return 1
    if len(bad) > N_all * 0.2:
        print("\n  [경고] 실패율 %.0f%% — 아래 수치를 **신뢰하지 마라.**"
              % (100.0 * len(bad) / N_all))

    indep = good
    any_indep = sum(1 for x in indep if x["indep"] > 0)
    any_res = sum(1 for x in indep if x["with_res"] > 0)
    any_use = sum(1 for x in indep if x["usable"] > 0)
    any_stat = sum(1 for x in indep if x["stats"] > 0)
    tot_use = sum(x["usable"] for x in indep)
    print("  (성공한 %d쌍 기준)" % N)
    print("  독립 시험이 검색됨          %3d/%d = %.0f%%" % (any_indep, N, 100 * any_indep / N))
    print("  그중 결과 수치까지 있음     %3d/%d = %.0f%%" % (any_res, N, 100 * any_res / N))
    print("  **그중 무작위배정(대조 가능)** %3d/%d = %.0f%%"
          % (any_use, N, 100 * any_use / N))
    if any_res > any_use:
        print("     ↑ 결과가 있어도 단일군·용량증량이면 효능을 반증할 수 없다.")
        print("       실측에서 등록부 시험 25건이 전부 비무작위였다.")
        print("       '결과 있음'만 세면 근거 가용성을 크게 과대평가한다.")
    print("  통계 분석까지 있음          %3d/%d = %.0f%%" % (any_stat, N, 100 * any_stat / N))
    print("  총 사용 가능 독립 시험      %d건 (쌍당 평균 %.1f)" % (tot_use, tot_use / N))

    pct = 100.0 * any_use / N
    print("\n[판단]")
    if pct >= 40:
        print("  %.0f%% — 등록부에 **쓸 수 있는** 반증 근거가 실재한다." % pct)
        print("  B6를 돌려라. 이게 이 프로젝트의 핵심 주장이 된다.")
    elif pct >= 20:
        print("  %.0f%% — 절반의 승리. B6를 돌리되 주장은 '천장이 올라간다'까지만." % pct)
        print("  '문제를 풀었다'가 아니다. 과장하면 심사에서 그 지점이 공격당한다.")
    else:
        print("  %.0f%% — 라벨 출처 말고는 쓸 시험이 거의 없다." % pct)
        print("  **B6를 빼라.** 등록부를 읽어도 새 근거가 안 들어오므로 B5와 같아진다.")
        print("  이건 실패가 아니라 결과다 — 반증 근거의 부재가 구조적이라는 발견이다.")
        print("  그 자체가 보고할 만한 사실이고, 제안서의 문제의식과도 맞는다.")

    print("\n[근거를 어디서도 못 찾는 TN] 벤치마크의 '풀 수 없는 문제'")
    dead = [x for x in indep
            if x["usable"] == 0
            and not next((y for rr, y in ok if rr["nct"] == x["row"]["nct"]
                          and y["n_outcomes"] > 0), None)]
    for x in dead[:12]:
        print("  %-24s %-30s %s" % (x["row"]["drug"][:24],
                                    x["row"]["indication"][:30], x["row"]["nct"]))
    if len(dead) > 12:
        print("  … 외 %d건" % (len(dead) - 12))
    print("  이 %d건은 성능 상한 계산에서 빼야 한다. 못 푸는 문제로 감점되면 안 된다."
          % len(dead))

    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["drug", "indication", "label_nct", "label_has_results",
                    "label_n_outcomes", "search_found", "independent",
                    "independent_with_results", "independent_usable",
                    "independent_with_stats",
                    "usable_ncts", "search_how", "error"])
        by = {x["row"]["nct"]: x for x in indep}
        for r, x in res:
            v = by.get(r["nct"], {})
            w.writerow([r["drug"], r["indication"], r["nct"], x["has_results"],
                        x["n_outcomes"], v.get("found", 0), v.get("indep", 0),
                        v.get("with_res", 0), v.get("usable", 0), v.get("stats", 0),
                        ";".join(v.get("ncts", [])), v.get("how", ""),
                        x["error"] or v.get("err") or ""])
    print("\n저장: %s" % a.out)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
