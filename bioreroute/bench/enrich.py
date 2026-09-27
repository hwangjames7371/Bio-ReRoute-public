# -*- coding: utf-8 -*-
"""시험 종료 연도를 기존 벤치마크 파일에 채워 넣는다. LLM 없이, 무료로.

왜 이렇게 하는가 — **파이프라인을 다시 돌리면 안 되기 때문이다.**

  `bench_matched.csv` 가 `ctgov_year` 열 없이 만들어졌다. 시점 차단(Tier 2)에
  그 열이 필요하다. 그런데 `labels → ctgov → match` 를 재실행하면
  **짝짓기가 달라질 수 있다** — match는 PubMed 문헌량으로 TN·TP를 짝지으므로
  문헌량이 바뀌면 다른 쌍이 만들어진다.

  그러면 지금까지 잰 모든 숫자가 **다른 벤치마크의 숫자**가 된다.
  AUROC·깔때기·표본 검토가 전부 비교 불가가 된다.

  그래서 쌍은 그대로 두고 **열만 채운다.** NCT는 이미 파일에 있다.

무엇을 채우는가 — 시험의 **종료 연도**다. 결과가 알려진 시점이므로
시점 차단의 기준이 된다. 1차 완료일을 우선하고 없으면 전체 완료일을 쓴다.

실행: py -m bioreroute.bench.enrich bench_matched.csv
"""

import argparse
import csv
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

API = "https://clinicaltrials.gov/api/v2/studies/%s?format=json"
TIMEOUT = 25
DELAY = 0.2
SCHEMA = 1
_ctx = ssl.create_default_context()
_YEAR = re.compile(r"(19|20)\d{2}")


def fetch_year(nct, cache):
    """종료 연도. 1차 완료일 우선 — 결과가 나오는 시점이 그때다."""
    hit = cache.get(nct)
    if hit is not None and hit.get("_v") == SCHEMA:
        return hit
    out = {"nct": nct, "_v": SCHEMA, "year": None, "which": "", "error": None}
    try:
        req = urllib.request.Request(API % urllib.parse.quote(nct),
                                     headers={"User-Agent": "Bio-ReRoute"})
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
            d = json.loads(r.read().decode("utf-8"))
        st = (d.get("protocolSection") or {}).get("statusModule") or {}
        for key, tag in (("primaryCompletionDateStruct", "1차완료"),
                         ("completionDateStruct", "완료"),
                         ("startDateStruct", "시작")):
            m = _YEAR.search((st.get(key) or {}).get("date") or "")
            if m:
                out["year"], out["which"] = int(m.group(0)), tag
                break
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    cache[nct] = out
    time.sleep(DELAY)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("matched", nargs="?", default="bench_matched.csv")
    ap.add_argument("--cache", default="ctgov_year_cache.json")
    ap.add_argument("--out", default="",
                    help="비우면 입력 파일을 덮어쓴다(백업을 먼저 뜨라)")
    a = ap.parse_args(argv)
    out_path = a.out or a.matched

    rows = list(csv.DictReader(open(a.matched, encoding="utf-8-sig")))
    if not rows:
        print("행이 없다.")
        return 1
    fields = list(rows[0].keys())
    if "ctgov_year" not in fields:
        # nct 바로 뒤에 넣는다. 사람이 볼 때 짝이 붙어 있어야 읽힌다.
        i = fields.index("nct") + 1 if "nct" in fields else len(fields)
        fields.insert(i, "ctgov_year")

    try:
        cache = json.load(open(a.cache, encoding="utf-8"))
    except Exception:
        cache = {}

    print("=" * 78)
    print("종료 연도 보강 — %d행 (LLM 호출 없음)" % len(rows))
    print("=" * 78)
    print("파이프라인을 재실행하지 않는다. **짝짓기가 달라지면 오늘까지 잰")
    print("모든 숫자가 다른 벤치마크의 것이 된다.** 열만 채운다.\n")

    todo = [r for r in rows if str(r.get("nct", "")).startswith("NCT")]
    done = err = 0
    for i, r in enumerate(todo, 1):
        y = fetch_year(r["nct"], cache)
        r["ctgov_year"] = y["year"] or ""
        done += 1 if y["year"] else 0
        err += 1 if y["error"] else 0
        if i % 20 == 0 or i == len(todo):
            print("  %d/%d" % (i, len(todo)))
            json.dump(cache, open(a.cache, "w", encoding="utf-8"),
                      ensure_ascii=False)
    json.dump(cache, open(a.cache, "w", encoding="utf-8"), ensure_ascii=False)
    for r in rows:
        r.setdefault("ctgov_year", "")

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    n = len(rows)
    print("\n[결과] NCT 있는 행 %d · 연도 확보 %d · 조회 실패 %d" % (len(todo), done, err))
    print("       전체 %d행 중 %d행(%.0f%%)에 연도가 있다" % (n, done, 100.0 * done / n))
    ys = sorted(int(r["ctgov_year"]) for r in rows if str(r.get("ctgov_year", "")).strip())
    if ys:
        print("       범위 %d~%d · 중앙값 %d" % (ys[0], ys[-1], ys[len(ys) // 2]))
    which = {}
    for v in cache.values():
        if v.get("which"):
            which[v["which"]] = which.get(v["which"], 0) + 1
    if which:
        print("       출처: " + " · ".join("%s %d" % kv for kv in which.items()))

    # TN·TP를 나눠 봐야 한다. **TP에는 NCT가 없다** — RepoDB 승인에서 왔지
    #   시험에서 온 것이 아니다. 그래서 연도는 구조적으로 TN에만 붙는다.
    tn = [r for r in rows if r.get("label") == "TN"]
    tp = [r for r in rows if r.get("label") == "TP"]
    tn_y = sum(1 for r in tn if str(r.get("ctgov_year", "")).strip())
    tp_y = sum(1 for r in tp if str(r.get("ctgov_year", "")).strip())
    print("\n[판단] 시점 차단(--tier2)을 쓸 수 있는가")
    print("  TN %d행 중 연도 있음 %d · TP %d행 중 %d" % (len(tn), tn_y, len(tp), tp_y))

    if tn and tn_y < len(tn) * 0.7:
        print("\n  TN조차 연도가 %d/%d뿐이다. **시점 차단이 의미 없다.**"
              % (tn_y, len(tn)))
        print("  차단되는 TN과 안 되는 TN이 섞여 결과를 해석할 수 없다.")
        return 0

    print("""
  ※ **비대칭이다. 이 점을 반드시 함께 보고해야 한다.**

     TP에는 시험이 없으므로 컷오프가 안 걸린다. 즉 시점 차단을 켜면
     TN만 문헌이 잘리고 TP는 전 기간을 본다.

     → **AUROC·전체 성능은 이 조건에서 해석할 수 없다.** TP가 유리해진다.
     → 해석 가능한 것은 **TN의 기각 재현율** 하나다 —
        "결과가 나오기 전에 이 실패를 걸러낼 수 있었는가."

     그리고 그것이 반증 우선 시스템에서 물어야 할 질문이다.
     지평을 늘리며 기각 재현율이 무너지는 속도를 보면,
     **우리 성능이 사후 문헌에 얼마나 기대고 있는지**가 드러난다.""")
    print("\n저장: %s" % out_path)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
