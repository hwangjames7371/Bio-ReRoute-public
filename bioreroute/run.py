# -*- coding: utf-8 -*-
"""Bio-ReRoute 실행부.

사용법
  python -m bioreroute.run              # 시드 후보, 전체 구성(B5)
  python -m bioreroute.run --config B2  # 제거 실험 특정 단
  python -m bioreroute.run --ablation   # B0~B5 전부 실행

  # **임의 가설 검증** — 이게 실제 사용 형태다
  python -m bioreroute.run --pair "metformin / Malignant neoplasm of breast"
  python -m bioreroute.run --pair "A / X" --pair "B / Y" --config B6

임의 가설 입력이 없으면 이 시스템은 벤치마크 실행기일 뿐이다. 제품의 주장은
*"가설을 주면 검증한다"* 이므로 그 경로가 CLI에 있어야 한다.
시드 후보는 사람이 근거를 매긴 W1 회귀용이고, --pair 는 근거가 비어 있다 —
게이트가 처음부터 문헌을 읽어 채운다.
"""

import argparse
import sys
from datetime import datetime

from .core import gates
from .core.state import Candidate, RunState, build_candidates
from .io import cache, llm
from .render import render_console


def parse_pair(text):
    """'약물 / 질환' → Candidate. 근거는 비운다 — 게이트가 채운다."""
    for sep in ("/", "|", "::"):
        if sep in text:
            drug, disease = [x.strip() for x in text.split(sep, 1)]
            break
    else:
        raise ValueError("'약물 / 질환' 형식이어야 한다: %r" % text)
    if not drug or not disease:
        raise ValueError("약물과 질환이 모두 있어야 한다: %r" % text)
    c = Candidate(name="%s / %s" % (drug, disease), origin="입력",
                  query="%s AND %s" % (drug, disease),
                  drug=drug, disease=disease, pubchem=drug)
    c.note("discovery", "INPUT", "사용자가 입력한 가설 — 근거는 게이트가 수집한다")
    return c

QUERY_TITLE = "신종 필로바이러스 아웃브레이크 (RdRp 표적 / 사이토카인 폭풍 위험)"
SETTINGS = "축1=정방향+역발상 | 렌즈=신종 감염병 긴급 | 접근성=ON"


def make_state(config, stamp=None, pairs=None) -> RunState:
    cands = [parse_pair(x) for x in pairs] if pairs else build_candidates()
    title = ("입력 가설 %d건" % len(cands)) if pairs else QUERY_TITLE
    return RunState(
        query_title=title, settings=SETTINGS if not pairs else "직접 입력",
        stamp=stamp or datetime.now().strftime("%Y-%m-%d %H:%M"),
        candidates=cands, config=dict(config),
    )


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="B5", choices=list(gates.CONFIGS))
    ap.add_argument("--ablation", action="store_true")
    ap.add_argument("--cache", default="pubmed_cache.json")
    ap.add_argument("--stamp", default=None, help="재현 비교용 고정 타임스탬프")
    ap.add_argument("--pair", action="append", default=[], metavar="'약물 / 질환'",
                    help="검증할 가설. 여러 번 쓸 수 있다. 없으면 시드 후보를 쓴다")
    a = ap.parse_args(argv)

    try:
        pairs = [x for x in a.pair]
        for x in pairs:
            parse_pair(x)          # 형식 오류를 **실행 전에** 잡는다
    except ValueError as e:
        print("입력 오류: %s" % e)
        return 1
    if pairs and not llm.available():
        # 입력 가설은 근거가 비어 있다. LLM이 없으면 게이트가 아무것도 못 채우고
        #   전부 `보류`가 나온다 — 그럴듯한 빈 결과다. 미리 끊는다.
        print("입력 가설을 검증하려면 LLM이 필요하다(근거를 문헌에서 읽어야 한다).")
        print("  py -m bioreroute.diag  로 설정을 확인하라.")
        return 1

    cache.configure(a.cache)
    cache.load()

    if a.ablation:
        print("=" * 78)
        print("단계별 제거 실험 (B0~B5)")
        print("=" * 78)
        for name, cfg in gates.CONFIGS.items():
            st = gates.run_pipeline(make_state(cfg, a.stamp, pairs))
            n = {"유망": 0, "보류": 0, "기각": 0}
            for c in st.candidates:
                n[c.verdict] = n.get(c.verdict, 0) + 1
            on = ",".join(k for k, v in cfg.items() if v) or "없음"
            print("  %-3s 게이트[%-32s] → 기각 %d · 보류 %d · 유망 %d"
                  % (name, on, n["기각"], n["보류"], n["유망"]))
        cache.save()
        return 0

    st = gates.run_pipeline(make_state(gates.CONFIGS[a.config], a.stamp, pairs))
    print(render_console(st, run_s2=st.config.get("s2", False)))
    cache.save()

    f = llm.failure_summary()
    if f["failed"]:
        print("")
        print("!" * 78)
        print("[경고] LLM 호출 %d건 중 %d건 실패 — 위 판정은 사람이 매긴 근거에 기댄 것이다."
              % (f["total"], f["failed"]))
        for msg, n in sorted(f["reasons"].items(), key=lambda x: -x[1]):
            print("   %3d회  %s" % (n, msg))
        print("   원인을 보려면: py -m bioreroute.diag")
        print("!" * 78)
    if f["total"]:
        served = " · ".join("%s %d" % (k, v) for k, v in f["served"].items())
        print("")
        print("[LLM] 조회 %d건 · 캐시 %d · 실제 호출 %d/%d%s"
              % (f["total"], f["cached"], f["spent"], f["budget"],
                 (" · " + served) if served else ""))

    print("")
    print("[캐시] %s" % a.cache)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
