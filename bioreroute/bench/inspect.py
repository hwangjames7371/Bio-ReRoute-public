# -*- coding: utf-8 -*-
"""판정 해부 — 등록부 근거가 **판정을 실제로 바꿨는가**. LLM 없이, 무료로.

실측에서 이런 일이 났다.

    등록부: 근거 확보 3후보 · 없음 5 · 오류 2
            시험 16건 읽음 → 채택 3건
    판정 분포: 유망 3 · 조건부 1 · 보류 5 · 기각 1     ← B5와 **완전히 동일**

근거는 붙었는데 판정이 하나도 안 바뀌었다. 이건 셋 중 하나다.

  ① 채택된 근거가 이미 판정이 정해진 후보(TP·유망)에 붙었다
  ② 가중치가 작아 임계를 못 넘었다
  ③ 방향이 지지라서 기각 쪽으로 안 갔다

**셋은 대응이 완전히 다르다.** ①이면 검색 대상이 문제고, ②면 가중치
설계가 문제고, ③이면 등록부가 반증원이라는 전제 자체가 틀린 것이다.

이 도구는 저장된 상태에서 등록부 근거만 빼고 **판정을 다시 계산해**
그 차이를 직접 보여준다. 추정이 아니라 같은 판정 함수를 다시 돌린다.

실행
  py -m bioreroute.bench.inspect s.json
  py -m bioreroute.bench.inspect s.json --all      # 전 후보 상세
"""

import argparse
import json
import sys

from ..core import gates
from ..core.scoring import adjudicate
from ..core.state import Candidate


def rebuild(d, drop_ctgov=False):
    """저장된 dict → Candidate. drop_ctgov면 등록부 근거를 빼고 세운다."""
    c = Candidate(name=d.get("name", ""), origin=d.get("label", ""),
                  query="", drug=d.get("drug", ""), disease=d.get("disease", ""))
    fc = list(d.get("factcheck") or [])
    if drop_ctgov:
        fc = [r for r in fc if r.get("source") != "ctgov"]
    c.factcheck = fc
    c.f0 = d.get("f0") or {}
    c.veto, c.veto_reason = d.get("veto"), d.get("veto_reason")
    gates._rebuild_evidence(c)
    return c


def wsum(evs):
    return sum(e.weight for e in evs)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("state", nargs="?", default="bench_run_state.json")
    ap.add_argument("--all", action="store_true", help="등록부 근거 없는 후보도 전부")
    a = ap.parse_args(argv)

    d = json.load(open(a.state, encoding="utf-8"))
    cands = d.get("candidates", [])
    print("=" * 78)
    print("판정 해부 — 구성 %s · 후보 %d" % (d.get("config", "?"), len(cands)))
    print("=" * 78)

    # ── 등록부 게이트 기록 ────────────────────────────────────
    errs = []
    for x in cands:
        for t in x.get("trail") or []:
            if t.get("gate") == "registry" and t.get("outcome") == "ERROR":
                errs.append((x.get("name", ""), t.get("detail", "")))
    if errs:
        print("\n[등록부 오류] %d건 — 조회가 실패한 만큼 근거를 못 봤다" % len(errs))
        for n, why in errs[:10]:
            print("  %-40s %s" % (n[:40], (why or "")[:34]))

    # ── 등록부 근거가 왜 죽었는가 ─────────────────────────────
    #
    #   실측 사고: 시험 25건을 읽고 **채택 0건**이 나왔다. 화면에는
    #   "채택된 근거가 0건"까지만 나오고 **무엇이 걸렀는지**가 없었다.
    #   인용 검증인지, 관련성인지, 운영중단 방어인지 알 수 없으면
    #   어느 것도 못 고친다. 사유를 세어 보여준다.
    reg_all = [r for x in cands for r in (x.get("factcheck") or [])
               if r.get("source") == "ctgov"]
    if reg_all:
        kept_n = sum(1 for r in reg_all if r.get("kept"))
        print("\n[등록부 근거의 운명] 읽음 %d · 채택 %d · 강등 %d"
              % (len(reg_all), kept_n, len(reg_all) - kept_n))
        from collections import Counter
        why = Counter()
        for r in reg_all:
            if r.get("kept"):
                continue
            s_ = r.get("skip") or "(사유 없음)"
            for tag in ("인용 검증 실패", "인용 교차오염", "무관", "운영상 중단",
                        "라벨 출처", "철회 논문", "초록 없음", "응답 누락"):
                if tag in s_:
                    s_ = tag
                    break
            why[s_[:40]] += 1
        for s_, n in why.most_common(8):
            print("  %-28s %d건" % (s_, n))
        if kept_n == 0 and reg_all:
            top = why.most_common(1)[0][0] if why else "?"
            print("  → **한 건도 못 살았다.** 주 사유: %s" % top)
            print("     방어가 과했는지 근거가 정말 무관한지 아래 표본을 보고 판단하라.")
        drops = [r for r in reg_all if not r.get("kept")][:4]
        for r in drops:
            print("    %-13s %-9s %s" % (r.get("pmid"), r.get("direction"),
                                         (r.get("skip") or "")[:44]))
            if r.get("quote"):
                print("        인용: %s" % (r.get("quote") or "")[:58])

    # ── 판정 변화 ────────────────────────────────────────────
    print("\n[등록부 근거를 빼면 판정이 어떻게 되는가]")
    print("  같은 판정 함수를 다시 돌린다. 추정이 아니다.\n")
    # **판정이 바뀐 것**과 **확신만 움직인 것**은 다르다.
    #   유망 95% → 유망 97% 은 결정이 바뀐 게 아니다. 그걸 '기여'로 세면
    #   등록부가 한 일을 부풀리게 된다. 셋으로 나눈다.
    changed, shifted, same, none_reg = [], [], [], 0
    for x in cands:
        reg = [r for r in (x.get("factcheck") or [])
               if r.get("source") == "ctgov" and r.get("kept")]
        if not reg:
            none_reg += 1
            if not a.all:
                continue
        c_with = rebuild(x)
        c_without = rebuild(x, drop_ctgov=True)
        v1, p1, _ = adjudicate(c_with)
        v0, p0, _ = adjudicate(c_without)
        row = (x, reg, (v0, p0), (v1, p1),
               wsum(c_with.support), wsum(c_with.refute))
        if v0 != v1:
            changed.append(row)
        elif p0 != p1:
            shifted.append(row)
        else:
            same.append(row)

    def show(rows, head):
        if not rows:
            return
        print("  %s" % head)
        for x, reg, (v0, p0), (v1, p1), ws, wr in rows:
            mark = x.get("label", "")
            print("    [%s] %-38s %s%% → %s%%"
                  % (mark, x.get("name", "")[:38],
                     "%s %s" % (v0, p0 if p0 is not None else "-"),
                     "%s %s" % (v1, p1 if p1 is not None else "-")))
            print("         지지 %.2f · 반박 %.2f | 등록부 근거 %d건"
                  % (ws, wr, len(reg)))
            for r in reg[:3]:
                print("           %-11s w=%-5s %s" % (r.get("direction"),
                                                      r.get("weight"),
                                                      (r.get("quote") or "")[:40]))
        print("")

    show(changed, "▶ 판정이 **바뀐** 후보 — 이게 등록부의 실제 기여다")
    show(shifted, "▷ 판정은 같고 확신만 움직인 후보 (결정이 바뀐 것은 아니다)")
    show(same, "· 근거는 붙었으나 아무것도 안 바뀐 후보")

    rest = shifted + same
    n_reg = len(changed) + len(rest)
    print("  등록부 근거가 붙은 후보 %d · 판정 변경 %d · 확신만 이동 %d · 무변화 %d"
          % (n_reg, len(changed), len(shifted), len(same)))
    if n_reg and not changed:
        print("\n  [진단] 근거는 들어왔는데 **판정을 하나도 못 바꿨다.**")
        sup = sum(1 for _, reg, _, _, _, _ in rest
                  for r in reg if r.get("direction") == "support")
        ref = sum(1 for _, reg, _, _, _, _ in rest
                  for r in reg if r.get("direction") == "refute")
        print("   · 등록부 근거의 방향: 지지 %d · 반박 %d" % (sup, ref))
        if sup > ref:
            print("     → **등록부가 반증원이라는 전제가 이 표본에서는 성립하지 않는다.**")
            print("        중단 시험을 찾겠다고 만든 게이트가 지지 근거를 더 물어왔다.")
            print("        검색 질의가 '결과 게시된 시험 전체'라 그렇다. 좁혀야 한다.")
        else:
            tp = sum(1 for x, _, _, _, _, _ in rest if x.get("label") == "TP")
            print("     → 반박이 더 많은데도 판정이 안 바뀌었다. 가중치가 임계를")
            print("        못 넘은 것이다. 등록부 근거 %d건 중 TP에 붙은 것 %d건."
                  % (n_reg, tp))
            print("        TP에 붙었으면 판정이 안 바뀌는 게 정상이다.")
    if none_reg:
        print("\n  등록부 근거가 아예 없는 후보 %d — bench.ceiling 의 '독립 시험 없음'과"
              % none_reg)
        print("  숫자가 맞는지 대조하라. 안 맞으면 검색 단계에서 새는 것이다.")
        print("  전부 0건이면 표본 문제일 수 있다. bench.run --with-registry 로")
        print("  근거가 **있는** 쌍만 골라 돌려야 B6를 시험할 수 있다.")

    # ── 오답 해부 ────────────────────────────────────────────
    #
    #   실측: gabapentin/유방암은 TN인데 **유망 98%**가 나왔다.
    #   지지 5.90, 반박 0.00. 근거를 안 보면 왜 틀렸는지 알 수 없고,
    #   모르면 못 고친다. 총점만 보고 "성능이 낮다"고 적는 것은 진단이 아니다.
    #
    #   유방암 환자의 **안면홍조**를 가바펜틴으로 다스린 논문이 지지로
    #   읽혔을 가능성이 크다. bench.regaudit이 등록부에서 잡아낸 그 오염이
    #   PubMed 쪽에도 있는지 여기서 확인한다.
    print("\n[오답 해부] 왜 틀렸는지는 근거를 봐야 안다")
    WRONG = {("TN", "유망"), ("TP", "기각")}
    bad = []
    for x in cands:
        v = (adjudicate(rebuild(x))[0] if x.get("factcheck") is not None
             else x.get("verdict"))
        if (x.get("label"), v) in WRONG:
            bad.append((x, v))
    if not bad:
        print("  방향이 뒤집힌 오답 없음. (보류는 오답이 아니라 기권이다)")
    for x, v in bad:
        c = rebuild(x)
        print("\n  [%s → %s] %s" % (x.get("label"), v, x.get("name", "")))
        kept = sorted([r for r in (x.get("factcheck") or []) if r.get("kept")],
                      key=lambda r: -(r.get("weight") or 0))
        for r in kept[:5]:
            print("    %-8s w=%-5s %s [%s]"
                  % (r.get("direction"), r.get("weight"),
                     (r.get("title") or "")[:44],
                     r.get("source") or "pubmed"))
            print("        인용: %s" % (r.get("quote") or "")[:62])
        drop = [r for r in (x.get("factcheck") or []) if not r.get("kept")]
        if drop:
            print("    (강등 %d건 — 무관·인용실패 등)" % len(drop))
    if bad:
        print("\n  제목과 인용문을 읽어라. **가설과 다른 것을 재고 있으면 오염이다.**")
        print("  예: 유방암 환자의 안면홍조 완화는 '유방암을 치료한다'가 아니다.")
        print("  그런 항목이 보이면 팩트체커의 관련성 규칙이 안 먹은 것이다.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
