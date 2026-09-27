# -*- coding: utf-8 -*-
"""인용 충실도 정량화 — 제안서 §2.3·§3.1 의 RAGAS 자리 (LLM 비용 0)

    py -m bioreroute.bench.faithful
    py -m bioreroute.bench.faithful --state gen_state.json

## 왜 이 파일이 생겼나

제안서 §2.3·§3.1 이 **RAGAS(RAG 충실도)** 를 적었고 `제안서_전수대조.md` 는
그동안 줄곧 그 칸에 `❌ 없다 — 대신 verify_quote 로 원문 대조` 라고 적어 뒀다.

그 문장이 절반만 맞았다.

    게이트는 있었다        verify_quote 가 인용을 초록 원문과 대조한다
    **수치가 없었다**      그래서 "얼마나 충실한가"에 답할 수가 없었다

심사 기준 ③이 *"생성된 정보가 실제 데이터와 일치하는가"* 를 묻는다.
**그 질문의 답은 설명이 아니라 숫자여야 한다.**

## 왜 LLM 을 다시 부르지 않는가

`quote_check` 결과가 **판정할 때 이미 기록됐다.** 인용 475건 전부에 대해
`ok` 와 `how`(완전일치·구두점무시·수치대조) 가 남아 있다. 다시 부를 이유가
없고, 부르면 **같은 자료에 두 번 값을 매기는 것**이다.

## 우리 것은 RAGAS 가 아니다 — 그리고 **우리 발명도 아니다**

| | RAGAS | 여기 |
|---|---|---|
| 충실도 판정자 | **LLM 심판** | 원문 문자열·수치 대조 |
| 잡는 것 | 의미상 불일치까지 | **원문에 없는 문장** |
| 못 잡는 것 | — | 원문에 있지만 **맥락이 틀린** 인용 |

### 초판이 여기서 과대주장을 했다 — 철회한다 (결함 66)

초판 독스트링에 *"LLM 이 LLM 을 채점하지 않는다는 것이 이 방식의
요점이다"* 라고 적었다. **차별점처럼 읽히게 썼고, 그건 틀렸다.**

08-06 심야 선행연구 검색에서 —

| 선행연구 | 무엇 |
|---|---|
| **CiteCheck** (arXiv 2605.27700) | spaCy 정규화 **verbatim match** → **BERTScore** 로 패러프레이즈 |
| **CiteGuard** (arXiv 2510.17853) | LLM 을 **외부 근거 위의 비교기로만** 쓴다 |
| 생의학 주장 검증 (arXiv 2608.01409) | **사람 합의를 주 기준**, LLM 은 민감도 진단 |

**CiteCheck 의 verbatim → BERTScore 2단은 우리 3겹보다 넓다** —
우리는 패러프레이즈 층이 아예 없다. 그리고 *"LLM 심판을 안 쓴다"* 는
CiteGuard 도 지키는 규율이다.

> **문자열 대조는 우리 발명이 아니다.** 이 파일이 하는 일은
> *"약물 재창출 판정 파이프라인에 그걸 붙이고 분모를 둘로 나눠 보고하는
> 것"* 이고, **그건 조합이지 방법이 아니다.**

남는 좁은 주장 하나 — **충실도와 관련성을 분모를 밝혀 나란히 내는 것**은
못 찾았다. 다만 *"못 찾았다"는 "없다"가 아니다*(F0 게이트의 원칙 그대로).

실재하는 문장을 엉뚱하게 가져오는 것은 이 검사가 아니라 `has_result` ·
`names_drug` 층이 잡는다. 그래서 세 층을 따로 보고한다.

## 분모를 정직하게 정하는 것이 이 파일의 핵심이다

`정답표감사.md` 가 기록한 실수를 반복하지 않으려고 적는다 — **우리는
특이도를 논지로 걸고 그 분모가 무엇인지 그동안 줄곧 안 봤다.**

인용 475건 중 **294건은 인용 검사를 받지 않았다.** 이유가 이렇다.

    무관 — 효능 증거 아님          276    LLM 이 스스로 효능 근거가 아니라고 분류
    초록 없음 — 판정 불가            7    조회가 본문을 못 줬다
    라벨 출처 시험 · 철회 논문       11    근거에서 제외한 것

**이 294건을 충실도 분모에 넣으면 안 된다.** 검사를 못 한 것과 검사에
떨어진 것은 다르다. 그런데 **빼고 나면 분모가 181로 줄고, 그 사실을
같이 적지 않으면 99% 라는 수치가 거짓말이 된다.**

그래서 **두 수를 나란히** 낸다.

    충실도    검사받은 인용 중 원문에 실재한 비율
    관련성    LLM 이 낸 것 중 **애초에 쓸 수 있었던** 비율   ← 여기가 낮다

## 사후 분석이다

동결된 산출물을 나중에 읽은 것이고 **사전 지정이 아니다.** 문턱을 정해
두고 잰 게 아니라 나온 값을 적는다. `사전명세.md` 의 봉인 항목이 아니다.
"""

import argparse
import glob
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List, Optional

from . import stats

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 인용 검사를 **받지 않은** 사유를 층으로 묶는다. 문자열 접두로 가른다 —
# `skip` 은 사람이 읽을 문장이고 코드가 파싱할 열이 아니다. 늘어나면
# `기타` 로 떨어지고, `기타` 가 0이 아니면 화면에 찍는다(조용히 삼키지 않는다).
SKIP_GROUPS = (
    ("무관", "무관 — 효능 증거가 아니라고 LLM 이 스스로 분류"),
    ("초록 없음", "초록 본문을 못 받음 — **조회 실패는 0건이 아니다**"),
    ("라벨 출처", "정답표가 인용한 그 시험 — 누출 방지로 제외"),
    ("철회", "철회 논문 — 근거에서 제외"),
)


def _load(paths: List[str]) -> List[Dict[str, Any]]:
    """산출물에서 인용 항목을 모은다. **한 파일이라도 못 읽으면 적는다.**"""
    out, bad = [], []
    for p in paths:
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            bad.append((os.path.basename(p), "%s: %s" % (type(e).__name__, e)))
            continue
        cs = d.get("candidates") if isinstance(d, dict) else None
        for c in (cs or []):
            for e in (c.get("factcheck") or []):
                e = dict(e)
                e["_cand"] = c.get("name")
                e["_src"] = os.path.basename(p)
                out.append(e)
    if bad:
        out.append({"_read_error": bad})
    return out


def _group(skip: Optional[str]) -> str:
    s = skip or ""
    for pre, _ in SKIP_GROUPS:
        if s.startswith(pre):
            return pre
    return "기타"


def measure(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """세 층을 센다. **분모를 각각 명시해서 돌려준다.**"""
    errs = [e["_read_error"] for e in entries if "_read_error" in e]
    ent = [e for e in entries if "_read_error" not in e]

    checked = [e for e in ent if (e.get("quote_check") or {}).get("ok") is not None]
    unchecked = [e for e in ent if (e.get("quote_check") or {}).get("ok") is None]
    ok = [e for e in checked if (e.get("quote_check") or {}).get("ok") is True]
    bad = [e for e in checked if (e.get("quote_check") or {}).get("ok") is False]

    r: Dict[str, Any] = {
        "읽기실패": errs,
        "인용_전체": len(ent),
        "검사됨": len(checked),
        "검사안됨": len(unchecked),
        "충실": len(ok),
        "지어냄": len(bad),
        "지어낸_목록": [{"후보": e.get("_cand"), "pmid": e.get("pmid"),
                     "사유": (e.get("quote_check") or {}).get("how"),
                     "인용": (e.get("quote") or "")[:120]} for e in bad],
        "대조방식": dict(Counter((e.get("quote_check") or {}).get("how")
                             for e in checked)),
        "검사안된_사유": dict(Counter(_group(e.get("skip")) for e in unchecked)),
    }

    # ── ① 충실도 — 분모는 **검사받은 인용** ──────────────────
    if checked:
        lo, hi = stats.wilson(len(ok), len(checked))
        r["충실도"] = {"k": len(ok), "n": len(checked),
                    "p": len(ok) / len(checked), "ci": (lo, hi)}
    # ── ② 관련성 — 분모는 **LLM 이 낸 전부** ────────────────
    #
    #   RAGAS 의 answer relevancy 자리다. `무관` 은 실패가 아니라
    #   **LLM 이 스스로 걸러낸 것**이지만, 62% 가 쓸 수 없는 것이었다는
    #   사실 자체가 결과다 — 제안서 §1.1 「아이디어 과잉」의 실측이다.
    if ent:
        lo, hi = stats.wilson(len(checked), len(ent))
        r["관련성"] = {"k": len(checked), "n": len(ent),
                    "p": len(checked) / len(ent), "ci": (lo, hi)}
    # ── ③ 문맥 정밀도 — 실재하지만 **엉뚱한** 인용 ────────────
    #
    #   여기가 `verify_quote` 로 못 잡는 층이다. 실측 사고 셋(natalizumab ·
    #   dexpramipexole · "측정 방법" 문장)이 전부 이 층에서 났다.
    #
    #   **분자만 세면 안 된다.** 어떤 검사는 조건부로 돌아서 기회 자체가
    #   적다 — 실측: `cross_contaminated` 는 인용 검증에 **실패한 1건에서만**
    #   돌았고 결과가 `False` 였다. 그걸 "0건 걸림"이라고만 적으면
    #   *"이 층이 깨끗하다"* 로 읽힌다. **안 돌린 것과 통과한 것은 다르다** —
    #   결함 35가 정확히 그 혼동이었다. 그래서 **k / 검사 기회**로 낸다.
    #
    #   ## 기회를 "키가 있느냐"로 세면 틀린다 — 첫 판이 그랬다
    #
    #   `no_result` 는 **참일 때만** 기록된다. 그래서 키 유무로 세면
    #   29/29 = 100% 가 나오고, 그건 분자를 두 번 쓴 것이다.
    #   **각 층이 실제로 도달하는 조건을 코드에서 읽어 와 분모로 쓴다.**
    def _reached_weighting(e):
        # `certainty` 는 가중 단계 진입 직후에 기록된다 (factcheck.py)
        return e.get("certainty") is not None

    def _quote_failed(e):
        return (e.get("quote_check") or {}).get("ok") is False

    def _dedupable(e):
        # 같은 NCT 가 둘 이상일 때만 후보가 된다 (scoring.dedupe_trials)
        return bool(e.get("kept")) and bool(e.get("nct"))

    LAYERS = (
        ("결과_진술_아님", "no_result", _reached_weighting, "가중 단계까지 간 인용"),
        ("간접_근거", "indirect", _reached_weighting, "가중 단계까지 간 인용"),
        ("중복_시험", "dup_of", _dedupable, "NCT 를 가진 채택 인용"),
        ("다른_약_가리킴", "cross_contaminated", _quote_failed, "인용 검증 실패분"),
        ("철회", "retracted", lambda e: "retracted" in e, "전수"),
        ("유형_충돌", "type_conflict",
         lambda e: e.get("type_conflict") is not None, "PubMed 로 유형 확인된 것"),
    )
    ctx = {}
    for name, key, opp, what in LAYERS:
        ctx[name] = {"걸림": sum(1 for e in ent if e.get(key)),
                     "기회": sum(1 for e in ent if opp(e)), "분모": what}
    r["문맥"] = ctx
    # 강등 합에서 `유형_충돌` 은 뺀다 — 그건 강등이 아니라 **출처 대조 결과**다
    r["강등_합"] = sum(v["걸림"] for k, v in ctx.items() if k != "유형_충돌")
    # 채택까지 간 것
    r["채택"] = sum(1 for e in ent if e.get("kept"))
    r["가중_0"] = sum(1 for e in ent if not e.get("weight"))
    return r


def _pct(x):
    return "%.1f%%" % (100 * x)


def report(r: Dict[str, Any]) -> None:
    print("=" * 70)
    print("인용 충실도 — 제안서 §2.3 RAGAS 자리 · **LLM 비용 0 · 사후 분석**")
    print("=" * 70)
    if r["읽기실패"]:
        print("⚠ 못 읽은 파일이 있다 — 아래 수치의 분모가 줄어 있다")
        for f, why in r["읽기실패"][0]:
            print("    %s  %s" % (f, why))
        print()
    if not r["인용_전체"]:
        print("인용이 0건이다. 산출물을 못 찾았다 — `--state` 로 경로를 줘라.")
        return

    print("\n[1] 충실도 — **인용한 문장이 초록 원문에 실재하는가**")
    print("─" * 70)
    f = r.get("충실도")
    if f:
        print("    %d / %d = %s   [%s–%s]"
              % (f["k"], f["n"], _pct(f["p"]), _pct(f["ci"][0]), _pct(f["ci"][1])))
    for how, n in sorted(r["대조방식"].items(), key=lambda x: -x[1]):
        if how and how != "None":
            print("      %-22s %d" % (how, n))
    if r["지어냄"]:
        print("\n  ⚠ **초록에 없는 문장 %d건.** 지어낸 것이다 — 숨기지 않는다"
              % r["지어냄"])
        for b in r["지어낸_목록"]:
            print("      %s · PMID %s" % (b["후보"], b["pmid"]))
            print("        %s" % b["사유"])
            print("        \"%s…\"" % b["인용"][:90])
    else:
        print("\n    지어낸 문장 0건 — **그런데 n=%d 다.** 0/%d 의 상한은 %s 다"
              % (f["n"], f["n"], _pct(stats.wilson(0, f["n"])[1])))

    print("\n[2] 관련성 — **LLM 이 낸 것 중 애초에 쓸 수 있었던 비율**")
    print("─" * 70)
    g = r.get("관련성")
    if g:
        print("    %d / %d = %s   [%s–%s]"
              % (g["k"], g["n"], _pct(g["p"]), _pct(g["ci"][0]), _pct(g["ci"][1])))
    print("\n    검사조차 못 간 %d건의 사유 —" % r["검사안됨"])
    for pre, why in SKIP_GROUPS:
        n = r["검사안된_사유"].get(pre, 0)
        if n:
            print("      %-14s %4d   %s" % (pre, n, why))
    etc = r["검사안된_사유"].get("기타", 0)
    if etc:
        print("      %-14s %4d   ← **분류 안 된 사유다. 코드를 고쳐라**"
              % ("기타", etc))

    print("\n[3] 문맥 정밀도 — **실재하지만 엉뚱한 인용** (이 층이 더 어렵다)")
    print("─" * 70)
    lab = {"결과_진술_아님": "결과를 진술하지 않음 (측정 방법·환자 배정 문장)",
           "간접_근거": "그 약을 지목하지 않음 (계열·병용)",
           "중복_시험": "같은 시험이 두 번 (NCT 로 잡음)",
           "다른_약_가리킴": "다른 약의 결과 (거울상체·병용 상대)",
           "철회": "철회 논문",
           "유형_충돌": "연구 유형이 LLM 주장과 다름 (PubMed 대조)"}
    print("    %-13s %-26s %s" % ("걸림 / 기회", "분모가 무엇인가", "층"))
    thin = []
    for k, v in r["문맥"].items():
        n, m = v["걸림"], v["기회"]
        rate = ("%5.1f%%" % (100 * n / m)) if m else "  n/a"
        # **기회가 거의 없는 층을 표시한다.** 0/1 은 "깨끗하다"가 아니다
        if m < 10:
            thin.append("%s(%d)" % (k, m))
        print("    %3d /%4d %s  %-24s %s" % (n, m, rate, v["분모"], lab[k]))
    print("\n    강등·제외 합 %d건 — **문자열 대조로는 하나도 안 걸리는 것들이다**"
          % r["강등_합"])
    if thin:
        print("\n  ⚠ **기회가 10건 미만인 층: %s**" % ", ".join(thin))
        print("      이 층들은 이번 실행에서 **사실상 시험되지 않았다.**")
        print("      단위 시험은 통과하지만 실측 노출이 없다 — 결함 44와 같은 자리다.")
        print("      `0건 걸림` 을 **\"깨끗하다\"로 읽으면 안 된다.**")

    print("\n[4] 그래서 무엇이 남았나")
    print("─" * 70)
    print("    인용 %d → 검사 %d → 채택 %d   (가중치 0 으로 내린 것 %d)"
          % (r["인용_전체"], r["검사됨"], r["채택"], r["가중_0"]))

    print("\n" + "=" * 70)
    print("이 수치가 주장하지 **않는** 것")
    print("=" * 70)
    print("  · **RAGAS 가 아니다.** RAGAS 는 LLM 심판을 쓰고 의미 불일치까지 본다")
    print("  · **이 방식은 우리 발명이 아니다** — CiteCheck(2605.27700)이")
    print("    verbatim match + BERTScore 로 하고, **그쪽이 더 넓다**")
    print("    (우리는 패러프레이즈 층이 없다). 결함 66 으로 기록했다")
    print("  · **사전 지정이 아니다.** 동결 산출물을 나중에 읽었다.")
    print("    문턱을 미리 정해 두고 잰 것이 아니다")
    print("  · **한 번의 실행이다.** 질환·프롬프트가 바뀌면 값이 움직인다")
    print("  · 충실도 %s 는 **검사받은 인용 기준**이다. LLM 이 낸 전부로 보면"
          % (_pct(r["충실도"]["p"]) if r.get("충실도") else "—"))
    print("    관련성이 먼저 걸린다 — 두 수를 같이 읽어야 한다")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="인용 충실도 정량화 (§2.3 RAGAS 자리 · LLM 비용 0)")
    ap.add_argument("--state", action="append", default=None,
                    help="산출물 경로. 여러 번 줄 수 있다. 기본은 gen_state.json")
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--json", action="store_true", help="수치만 JSON 으로")
    a = ap.parse_args(argv)

    paths = a.state or [os.path.join(a.root, "gen_state.json")]
    paths = [p if os.path.isabs(p) else os.path.join(a.root, p) for p in paths]
    miss = [p for p in paths if not os.path.exists(p)]
    if miss:
        print("산출물이 없다: %s" % ", ".join(os.path.basename(p) for p in miss))
        print("**없는 것을 0으로 채우지 않는다.** 경로를 확인해라.")
        return 2

    r = measure(_load(paths))
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return 0
    report(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
