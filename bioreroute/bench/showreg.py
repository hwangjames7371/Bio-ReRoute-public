# -*- coding: utf-8 -*-
"""등록부 본문 열람 — 팩트체커가 **실제로 무엇을 읽었는지** 그대로 찍는다.

LLM을 한 번도 안 부른다. 무료다.

왜 필요한가.

    등록부 시험 25건을 읽고 채택 0건, 주 사유는 '무관'이었다.
    인용문은 전부 이런 것들이었다 —

        "Lack of disease progression indicates response to treatment"
        "Overall survival was defined from the date of diagnosis to..."

    **평가변수의 정의문이다. 결과 수치가 아니다.**

가설이 셋인데 눈으로 보면 즉시 갈린다.

  ① 그 시험에 애초에 수치가 없다 (결과 섹션에 정의만 등록)
  ② 수치는 있는데 _fmt_outcome 이 못 뽑는다 (내 파서 결함)
  ③ 수치는 있으나 **단일군**이라 비교가 안 된다
     → 대조군 없는 반응률은 효능을 지지도 반박도 못 한다.
        LLM이 '무관'이라 한 것이 **옳다.**

③이면 등록부의 증거 가치가 '결과 있음' 건수보다 훨씬 낮다는 뜻이고,
그건 B6 방향에 대한 **부정적이지만 보고할 만한 발견**이다.

실행
  py -m bioreroute.bench.showreg NCT00124657 NCT00112736
  py -m bioreroute.bench.showreg --from s.json          # 강등된 등록부 근거 전부
"""

import argparse
import json
import sys

from ..io import cache, sources


def survey(recs):
    """단일군인가 대조군인가. 이게 증거 가치를 가른다.

    처음엔 결과 줄의 구분자 '|' 를 세어 "군이 둘 이상"이라고 했다. **틀렸다.**
    실측 본문을 보니 그 군들은 대조군이 아니었다 —

        "70 mg/m^2 0 | 90 mg/m^2 0 | 120 mg/m^2 1"   → 용량 단계
        "WHO Grade III .438 | WHO Grade IV .292"      → 환자 하위군

    비교 가능성을 정하는 것은 **배정 방식**이다. 등록부가 명시해 준다.
    무작위배정이 아니면 대조가 없고, 대조가 없으면 효능을 반증할 수 없다.
    """
    out = {"n": len(recs), "num": 0, "rand": 0, "stats": 0, "empty": 0,
           "early": 0}
    for r in recs:
        body = r.get("abstract") or ""
        pts = [str(p).upper() for p in (r.get("pubtypes") or [])]
        if "RANDOMIZED" in pts or r.get("study_type") == "rct":
            out["rand"] += 1
        # 1상은 안전성·용량이 목적이라 효능 근거가 될 수 없다
        if any("PHASE1" in p for p in pts):
            out["early"] += 1
        if "[1차 평가변수 결과]" not in body:
            out["empty"] += 1
            continue
        tail = body.split("[1차 평가변수 결과]", 1)[1]
        out["num"] += 1 if any(ch.isdigit() for ch in tail) else 0
        out["stats"] += 1 if "통계:" in tail else 0
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("ncts", nargs="*", help="NCT 번호들")
    ap.add_argument("--from", dest="state", default="",
                    help="저장된 실행 상태에서 등록부 근거의 NCT를 읽는다")
    ap.add_argument("--cache", default="pubmed_cache.json")
    ap.add_argument("--max", type=int, default=6, help="본문을 펼쳐 볼 건수")
    a = ap.parse_args(argv)

    cache.configure(a.cache)
    cache.load()

    ncts = list(a.ncts)
    if a.state:
        d = json.load(open(a.state, encoding="utf-8"))
        for c in d.get("candidates", []):
            for r in (c.get("factcheck") or []):
                if r.get("source") == "ctgov" and r.get("pmid") not in ncts:
                    ncts.append(r["pmid"])
    if not ncts:
        print("NCT를 지정하거나 --from 으로 상태 파일을 줘라.")
        return 1

    print("=" * 78)
    print("등록부 본문 열람 — %d건 (LLM 호출 없음)" % len(ncts))
    print("=" * 78)

    recs = []
    for n in ncts:
        r = sources.ctgov_results(n)
        recs.append(r)
    cache.save()

    for r in recs[: a.max]:
        print("\n" + "─" * 78)
        print("%s  %s" % (r["pmid"], (r.get("title") or "")[:56]))
        if r.get("error"):
            print("  오류: %s" % r["error"])
        print("─" * 78)
        for line in (r.get("abstract") or "(본문 없음)").split("\n"):
            print("  | %s" % line[:74])
    if len(recs) > a.max:
        print("\n… 외 %d건 (--max 로 더 볼 수 있다)" % (len(recs) - a.max))

    s, n = survey(recs), max(1, len(recs))
    print("\n" + "=" * 78)
    print("[집계] %d건" % s["n"])
    print("  결과 구획 자체가 없음        %3d" % s["empty"])
    print("  수치가 하나라도 있음         %3d" % s["num"])
    print("  **무작위배정(대조 가능)**    %3d  = %.0f%%" % (s["rand"],
                                                       100 * s["rand"] / n))
    print("  통계 분석까지 있음           %3d  = %.0f%%" % (s["stats"],
                                                       100 * s["stats"] / n))
    print("  1상 포함(효능 근거 아님)     %3d" % s["early"])
    print("")
    # 더 근본적인 원인부터 묻는다. 수치가 아예 없는데 "대조가 없다"고
    #   말하면 한 단계 아래를 못 보고 지나친다.
    if s["n"] and s["num"] == 0:
        print("  → **수치가 하나도 없다.** 결과 섹션에 정의만 등록된 시험들이다.")
        print("     ceiling의 '1차 평가변수 있음'은 평가변수 **개수**를 센 것이라")
        print("     증거 가용성을 과대평가한다. 그 지표부터 고쳐야 한다.")
        print("     (또는 _fmt_outcome 이 수치를 못 뽑는 것일 수도 있다 —")
        print("      위 본문에 제목·설명만 있고 값 줄이 없으면 그쪽이다)")
    elif s["rand"] == 0:
        print("  → **무작위배정 시험이 하나도 없다.** 전부 단일군·용량증량이다.")
        print("     대조군 없는 반응률은 효능을 지지도 반박도 **못 한다.**")
        print("     팩트체커가 '무관'이라 한 것이 옳다. 방어가 과한 게 아니다.")
        print("")
        print("     이건 B6에 대한 부정적 결과이지만 **그 자체로 보고할 발견**이다 —")
        print("     문헌의 'CT.gov 결과 게시율 91%'는 반증 **가능한** 근거의")
        print("     가용성을 크게 과대평가한다. 게시된 것 대부분이 비교 불가다.")
        print("     출판 편향만이 병목이 아니라, 미출판 근거 자체가 비교 설계가")
        print("     아니라는 것 — 제안서의 문제의식을 오히려 강화한다.")
    elif s["rand"] < n * 0.3:
        print("  → 무작위배정이 %.0f%%뿐이다. 나머지는 효능 판단에 못 쓴다."
              % (100 * s["rand"] / n))
        print("     ceiling·regaudit의 가용성 수치를 **무작위배정 기준으로**")
        print("     다시 세야 한다. 지금 숫자는 상한이지 실제 근거량이 아니다.")
    else:
        print("  → 대조 가능한 시험이 있는데도 무관 판정이 났다면 프롬프트를 봐야 한다.")
        print("     위 본문에서 1차 평가변수 줄이 제대로 렌더링됐는지 눈으로 확인하라.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
