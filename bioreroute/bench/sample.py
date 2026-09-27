# -*- coding: utf-8 -*-
"""팩트체커 표본 검토지 — 가장 값싼 품질 점검인데 아직 안 했다.

인용 검증·GRADE·가중치 표는 전부 단위 시험했다. 그런데
**"이 초록에 대한 판정이 실제로 맞는가"를 사람이 읽어본 적이 없다.**

방향이 틀려도 인용문만 실재하면 통과한다. 인용 검증은 *지어냈는가*를 막지
*틀렸는가*를 막지 못한다. 둘은 다른 문제다.

이 도구는 판정 표본을 사람이 채점할 수 있는 형태로 뽑는다.
전부 읽을 필요 없다. 20~30건이면 방향 정확도의 대략적 구간이 나온다.

층화 표본을 쓴다 — 채택/기각/무관을 골고루, 가중치 큰 것 우선.
무작위로 뽑으면 대부분 '무관'이 나와 정보가 적다.

실행
  py -m bioreroute.bench.sample bench_run_state.json --n 24
  (채점 후)  py -m bioreroute.bench.sample --score factcheck_review.csv
"""

import argparse
import csv
import json
import random
import sys


def collect(path):
    """저장된 실행 상태에서 팩트체크 판정을 모은다."""
    d = json.load(open(path, encoding="utf-8"))
    out = []
    for cand in d.get("candidates", []):
        for r in cand.get("factcheck", []):
            out.append(dict(r, _cand=cand.get("name", ""),
                            _drug=cand.get("drug", ""),
                            _disease=cand.get("disease", "")))
    return out


def stratify(recs, n, seed=20260804):
    """채택·강등·무관을 골고루, 가중치 큰 것 우선.

    무작위로 뽑으면 대부분 '무관'이 나온다. 그건 정보가 적다.
    판정을 뒤집을 힘이 있는 항목을 봐야 한다.
    """
    rnd = random.Random(seed)
    kept = [r for r in recs if r.get("kept")]
    demoted = [r for r in recs
               if not r.get("kept") and r.get("quote_check")
               and not r["quote_check"].get("ok")]
    neutral = [r for r in recs
               if not r.get("kept") and "무관" in str(r.get("skip") or "")]

    kept.sort(key=lambda r: -(r.get("weight") or 0))
    rnd.shuffle(demoted)
    rnd.shuffle(neutral)

    # 가중치 큰 채택 절반, 나머지는 강등·무관에서
    n_k = min(len(kept), max(1, n // 2))
    n_d = min(len(demoted), max(1, n // 6))
    n_n = max(0, n - n_k - n_d)
    return kept[:n_k] + demoted[:n_d] + neutral[:n_n]


# 검토지에는 **시스템 판정을 넣지 않는다.**
#
#   처음엔 `시스템_방향` 칸을 넣고 "미리 보지 마라"고 안내문을 달았다.
#   **눈앞에 있는 답을 안 보는 것은 불가능하다.** 정박 효과가 걸리면
#   이 측정 전체가 무효가 된다 — 사람이 시스템에 동의하는 비율을 잴 뿐,
#   시스템이 맞는지를 재는 게 아니게 된다.
#
#   답은 별도 열쇠 파일에 두고 채점할 때 합친다. 사람은 근거만 보고 적는다.
FIELDS = ["번호", "약물", "질환", "출처", "자료원", "연구유형",
          "GRADE", "인용문", "사람_방향", "사람_메모"]
KEY_FIELDS = ["번호", "약물", "질환", "출처", "시스템_방향", "가중치"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("state", nargs="?", default="bench_run_state.json")
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--out", default="factcheck_review.csv")
    ap.add_argument("--key", default="factcheck_key.csv",
                    help="시스템 판정 보관 파일 — **채점 전에 열지 마라**")
    ap.add_argument("--score", default="", help="채점 완료된 파일을 읽어 정확도 산출")
    a = ap.parse_args(argv)

    # ── 채점 모드 ────────────────────────────────────────────
    if a.score:
        rows = list(csv.DictReader(open(a.score, encoding="utf-8-sig")))
        try:
            key = {r["번호"]: r for r in
                   csv.DictReader(open(a.key, encoding="utf-8-sig"))}
        except Exception as e:
            print("열쇠 파일을 읽을 수 없다(%s): %s" % (a.key, e))
            print("검토지와 같은 실행에서 나온 %s 가 있어야 채점된다." % a.key)
            return 1
        # 사람이 적은 것과 시스템 판정을 **번호로** 합친다
        for r in rows:
            k = key.get(r.get("번호", ""))
            if k:
                r["시스템_방향"] = k["시스템_방향"]
                r["가중치"] = k["가중치"]
        done = [r for r in rows
                if (r.get("사람_방향") or "").strip() and r.get("시스템_방향")]
        if not done:
            print("채점된 행이 없다. '사람_방향' 칸을 채워라 (support/refute/neutral).")
            return 1
        ok = sum(1 for r in done
                 if r["사람_방향"].strip().lower() == r["시스템_방향"].strip().lower())
        n = len(done)
        import math
        p, z = ok / n, 1.96
        dd = 1 + z * z / n
        c = (p + z * z / (2 * n)) / dd
        h = z * math.sqrt(max(p * (1 - p) / n + z * z / (4 * n * n), 0)) / dd
        print("=" * 66)
        print("팩트체커 방향 판정 정확도")
        print("=" * 66)
        print("  채점 %d건 · 일치 %d건 = %.0f%%  [95%% CI %.0f–%.0f%%]"
              % (n, ok, 100 * p, 100 * max(0, c - h), 100 * min(1, c + h)))
        wrong = [r for r in done
                 if r["사람_방향"].strip().lower() != r["시스템_방향"].strip().lower()]
        if wrong:
            print("\n  [불일치 — 여기서 개선점이 나온다]")
            for r in wrong[:12]:
                print("    %-18s 시스템=%-8s 사람=%-8s w=%s"
                      % (r["약물"][:18], r["시스템_방향"], r["사람_방향"], r["가중치"]))
                if r.get("사람_메모"):
                    print("      %s" % r["사람_메모"][:70])
        print("\n  주의: 이 정확도는 **방향**만 본 것이다.")
        print("        가중치가 맞는지는 별도 문제다.")
        print("=" * 66)
        return 0

    # ── 표본 추출 ────────────────────────────────────────────
    try:
        recs = collect(a.state)
    except Exception as e:
        print("실행 상태 파일을 읽을 수 없다: %s" % e)
        print("bench.run 을 --save-state 로 돌려 상태를 남겨야 한다.")
        return 1
    if not recs:
        print("팩트체크 판정이 없다.")
        return 1

    sel = stratify(recs, a.n)
    # 표본 순서를 섞는다. 층화 추출은 채택→강등→무관 순으로 쌓이므로
    #   그대로 두면 "앞쪽은 다 지지겠구나" 하는 순서 단서가 생긴다.
    random.Random(20260804).shuffle(sel)
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f, \
         open(a.key, "w", newline="", encoding="utf-8-sig") as g:
        w, wk = csv.writer(f), csv.writer(g)
        w.writerow(FIELDS)
        wk.writerow(KEY_FIELDS)
        for i, r in enumerate(sel, 1):
            # 자료원을 안 보여주면 사람이 잘못 채점한다. 등록부 인용은
            #   "Terminated for futility" 처럼 짧은 게 정상인데, 논문 초록
            #   기준으로 읽으면 "근거가 빈약하다"고 잘못 표시하게 된다.
            src = "등록부" if r.get("source") == "ctgov" else "논문"
            if r.get("stop_reason") == "operational":
                src += "(운영중단)"
            ref = r.get("journal") or r.get("pmid", "")
            w.writerow([i, r.get("_drug", ""), r.get("_disease", ""), ref, src,
                        r.get("study_type", ""), r.get("certainty", ""),
                        (r.get("quote") or "")[:200], "", ""])
            wk.writerow([i, r.get("_drug", ""), r.get("_disease", ""), ref,
                         r.get("direction", ""), r.get("weight", "")])

    kept = sum(1 for r in sel if r.get("kept"))
    n_reg = sum(1 for r in sel if r.get("source") == "ctgov")
    print("=" * 66)
    print("팩트체커 검토지 — %d건 (전체 %d건에서 층화 추출)" % (len(sel), len(recs)))
    print("=" * 66)
    print("  채택 %d · 강등/무관 %d · 등록부 출처 %d  (순서는 섞었다)"
          % (kept, len(sel) - kept, n_reg))
    print("\n저장: %s" % a.out)
    print("      %s   ← **채점 끝날 때까지 열지 마라**" % a.key)
    print("""
채점 방법 — 검토지에 **시스템 판정이 없다.** 일부러 뺐다.
  눈앞에 답이 있으면 안 볼 수가 없고, 그러면 '사람이 시스템에 동의하는 비율'을
  재게 된다. 우리가 재려는 것은 **시스템이 맞는가**다.

  1. '인용문'을 읽고 그 문장이 "약물이 질환에 효능이 있다"를
     지지하는지·반박하는지·무관한지 판단한다.
     '자료원'이 등록부면 인용이 짧은 게 정상이다(구조화된 표에서 뽑는다).
     '(운영중단)' 표시는 자금·등록 부진으로 멈춘 시험이라는 뜻이다 —
     **중단 자체는 효능 반증이 아니다.** 결과 수치만 근거로 본다.
  2. '사람_방향' 칸에 support / refute / neutral 중 하나를 적는다.
  3. 애매하면 neutral 로 적고 메모를 남겨라. 억지로 방향을 정하지 마라.
  4. 다 적었으면:  py -m bioreroute.bench.sample --score %s

전부 볼 필요 없다. 20~30건이면 방향 정확도의 대략적 구간이 나온다.
인용 검증은 '지어냈는가'를 막지 '틀렸는가'를 막지 못한다 — 그걸 여기서 잰다.""" % a.out)
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
