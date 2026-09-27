# -*- coding: utf-8 -*-
"""승인 여부 교차 검증 — RepoDB 불완전성 대응.

실측으로 드러난 문제: RepoDB의 Approved 목록이 불완전하다.

    capecitabine  RepoDB 승인 = 위암·대장암     실제 = 유방암도 승인(Xeloda 1998)
    fulvestrant   RepoDB 승인 = 0개              실제 = 유방암 승인(Faslodex 2002)
    exenatide     RepoDB 승인 = 0개              실제 = 2형 당뇨 승인(Byetta 2005)

"같은 질환으로 승인된 적 있으면 TN에서 뺀다"는 필터는 **RepoDB가 아는 것만**
뺄 수 있다. 없는 승인은 그대로 남아 TN을 오염시킨다. 효과가 입증된 약을
실패로 라벨하면, 시스템이 옳게 판정해도 오답으로 세게 된다.

여기서 하는 일은 **라벨 청소**이지 시스템 평가가 아니다. 그 구분이 중요하다.
  · 시스템 평가에 LLM 기억을 쓰면 순환 논증이다 → 그래서 폐쇄형 B0는 따로 잰다.
  · 라벨 청소에 쓰는 건 다르다. "이 약이 규제기관 승인을 받았는가"는
    효능 판단이 아니라 사실 조회이고, 사람 전문가에게 묻는 것과 같은 성격이다.
그래도 최종 판단은 아니다. **표시만 하고 사람이 확인한다.**

실행: py -m bioreroute.bench.approval bench_matched.csv
"""

import argparse
import csv
import json
import sys

from ..io import cache, llm

SYSTEM = "당신은 규제 승인 이력에 밝은 약사다. 확실하지 않으면 모른다고 답한다."

HEAD = """아래 약물-적응증 쌍 {n}개 각각에 대해, 그 약물이 **그 적응증으로 규제기관
(FDA·EMA·PMDA·MFDS 등) 승인을 받은 적이 있는지** 답하라.

중요
1. 효능이 있는지를 묻는 게 아니다. **승인 이력**만 묻는다.
2. 같은 질환의 다른 이름·아형도 승인으로 본다.
   예: "Malignant neoplasm of breast" 와 "Breast Carcinoma" 는 같은 질환이다.
3. 확실하지 않으면 "모름"이라고 답하라. 추측하지 마라.
4. brand에는 기억나는 제품명·승인연도를 적어라. 없으면 빈 문자열.

"""

TAIL = """
JSON 배열만 출력하라. 원소 {n}개, 위 순서 그대로.
[{{"idx": 1, "approved": "예|아니오|모름",
   "confidence": "high|medium|low", "brand": "제품명·연도 (없으면 빈 문자열)"}}]"""


def probe(pairs, chunk=12):
    out = [None] * len(pairs)
    for s in range(0, len(pairs), chunk):
        part = pairs[s:s + chunk]
        body = "\n".join("%d. %s / %s" % (i + 1, p["drug"], p["indication"])
                         for i, p in enumerate(part))
        r = llm.complete(HEAD.format(n=len(part)) + body + "\n" + TAIL.format(n=len(part)),
                         system=SYSTEM, as_json=True,
                         model=llm.model_for("approval"),   # §3.2 소형
                         purpose="approval")   # 계량
        data = r.get("data")
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), None)
        idx = {}
        if isinstance(data, list):
            for j, d in enumerate(data):
                if isinstance(d, dict):
                    try:
                        k = int(d.get("idx", j + 1)) - 1
                    except Exception:
                        k = j
                    if 0 <= k < len(part):
                        idx[k] = d
        for i in range(len(part)):
            d = idx.get(i) or {}
            v = str(d.get("approved", "모름")).strip()
            out[s + i] = {"approved": v if v in ("예", "아니오", "모름") else "모름",
                          "confidence": str(d.get("confidence", "low")).lower(),
                          "brand": str(d.get("brand", ""))[:80]}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("matched", nargs="?", default="bench_matched.csv")
    ap.add_argument("--cache", default="pubmed_cache.json")
    ap.add_argument("--out", default="bench_approval_flags.csv")
    a = ap.parse_args(argv)

    cache.configure(a.cache)
    cache.load()
    rows = [r for r in csv.DictReader(open(a.matched, encoding="utf-8-sig"))
            if r["label"] == "TN"]

    print("=" * 78)
    print("승인 여부 교차 검증 — TN %d건" % len(rows))
    print("=" * 78)
    print("RepoDB의 Approved 목록이 불완전해 실제 승인약이 TN에 섞인다.")
    print("이건 라벨 청소이지 시스템 평가가 아니다. 표시만 하고 사람이 확인한다.\n")

    res = probe([{"drug": r["drug"], "indication": r["indication"]} for r in rows])
    cache.save()

    flagged = [(r, x) for r, x in zip(rows, res) if x["approved"] == "예"]
    maybe = [(r, x) for r, x in zip(rows, res)
             if x["approved"] == "모름" and x["confidence"] != "low"]

    print("[승인 이력 있음으로 표시 %d건] — TN 라벨이 틀렸을 가능성" % len(flagged))
    for r, x in sorted(flagged, key=lambda t: -{"high": 2, "medium": 1}.get(t[1]["confidence"], 0)):
        print("  [%-6s] %-24s %-30s %s"
              % (x["confidence"], r["drug"][:24], r["indication"][:30], x["brand"][:30]))

    n = len(rows)
    print("\n[요약] %d/%d = %.0f%% 가 승인 이력 있음으로 표시됐다." % (len(flagged), n, 100 * len(flagged) / n))
    if len(flagged) > n * 0.15:
        print("  → 15%를 넘는다. TN 오염이 심각하다.")
        print("     이 상태로 낸 성능 수치는 실제보다 낮게 나온다 —")
        print("     시스템이 '유망'이라 옳게 판정한 것을 오답으로 세기 때문이다.")
        print("     표시된 건을 사람이 확인해 bench/review.py 에 판정을 넣어야 한다.")
    high = [t for t in flagged if t[1]["confidence"] == "high"]
    print("  고확신 %d건은 우선 확인 대상이다." % len(high))

    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["drug", "indication", "stratum", "approved", "confidence", "brand", "detail"])
        for r, x in zip(rows, res):
            w.writerow([r["drug"], r["indication"], r.get("stratum", ""),
                        x["approved"], x["confidence"], x["brand"], r.get("detail", "")[:120]])
    print("\n저장: %s" % a.out)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
