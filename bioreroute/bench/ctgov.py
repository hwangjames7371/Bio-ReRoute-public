# -*- coding: utf-8 -*-
"""ClinicalTrials.gov 원본 조회 — 라벨 검증의 최종 심판.

RepoDB의 적응증 문자열만으로는 두 가지를 구분할 수 없다.
  · 질환 자체를 치료하려던 시험
  · 그 질환 **환자에게서** 다른 증상을 다루던 시험
실측 사례: `gabapentin / Malignant neoplasm of breast`. 가바펜틴이 유방암
치료제일 리 없다. 유방암 환자의 안면홍조 시험이 적응증 유방암으로 색인된 것이다.

시험 제목과 1차 평가변수를 읽으면 갈린다. 그래서 원본을 직접 본다.
덤으로 시작·종료 날짜를 얻는데, 이게 시점 차단(Tier 2) 검증의 유일한 통로다.
RepoDB에는 날짜 컬럼이 없다.

실행: py -m bioreroute.bench.ctgov bench_labels.csv
"""

import argparse
import csv
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://clinicaltrials.gov/api/v2/studies/%s?format=json"
TIMEOUT = 20
DELAY = 0.2
_ctx = ssl.create_default_context()

# 증상 완화·지지 요법을 시사하는 제목 표현.
# 질환 자체를 치료하는 시험이 아니므로 "X가 Y에 효능이 있다" 가설의 반례가 아니다.
# 주의: 이 정규식은 한 번 크게 틀렸다.
#   `diagnos` 를 넣었더니 "Newly **Diagnosed** Glioblastoma", "Patients
#   **Diagnosed** With COVID-19" 같은 평범한 표현을 진단 시험으로 오인해
#   멀쩡한 TN 3건을 지웠다. 넓은 패턴은 오염을 지우는 게 아니라 데이터를 지운다.
#   진단·영상은 반드시 명시적 어구로만 잡는다.
SYMPTOM = re.compile(
    r"hot flash|hot flush|mucositis|xerostomia|pruritus|cachexia|anorexia"
    r"|nausea|vomit|fatigue|insomnia|neuropathy"
    r"|pain (management|control|relief)"
    r"|quality of life|palliat|supportive care|end[- ]of[- ]life"
    r"|prevention of [a-z ]*(induced|related)|premedicat|antiemetic"
    r"|sedation|anesthesia|anaesthesia|bowel prep"
    r"|diagnostic (accuracy|performance|study|trial|test|imaging)"
    r"|contrast (agent|medium|media|enhanced)"
    r"|imaging (study|agent|trial)", re.I)


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Bio-ReRoute"})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
        return json.loads(r.read().decode("utf-8"))


def _dig(d, *path, default=None):
    for k in path:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d


def fetch(nct: str, cache: dict):
    """NCT 하나 조회. 실패하면 error를 담아 돌려준다(허위 통과 금지)."""
    if nct in cache:
        return cache[nct]
    out = {"nct": nct, "error": None}
    try:
        d = _get(API % urllib.parse.quote(nct))
        p = d.get("protocolSection", {})
        out.update(
            title=_dig(p, "identificationModule", "briefTitle", default="") or "",
            official=_dig(p, "identificationModule", "officialTitle", default="") or "",
            conditions=_dig(p, "conditionsModule", "conditions", default=[]) or [],
            why_stopped=_dig(p, "statusModule", "whyStopped", default="") or "",
            overall=_dig(p, "statusModule", "overallStatus", default="") or "",
            start=_dig(p, "statusModule", "startDateStruct", "date", default="") or "",
            completion=(_dig(p, "statusModule", "completionDateStruct", "date", default="")
                        or _dig(p, "statusModule", "primaryCompletionDateStruct",
                                "date", default="") or ""),
            phases=_dig(p, "designModule", "phases", default=[]) or [],
            enrolled=_dig(p, "designModule", "enrollmentInfo", "count", default=None),
            outcome=(_dig(p, "outcomesModule", "primaryOutcomes", default=[]) or [{}])[0]
                    .get("measure", "") if _dig(p, "outcomesModule", "primaryOutcomes")
                    else "",
        )
    except urllib.error.HTTPError as e:
        out["error"] = "HTTP %s" % e.code
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    cache[nct] = out
    time.sleep(DELAY)
    return out


def year_of(s: str):
    m = re.search(r"(19|20)\d{2}", s or "")
    return int(m.group(0)) if m else None


def judge(row, info):
    """CT.gov 원본으로 라벨을 재판정한다. (판정, 사유)"""
    if info.get("error"):
        return "조회실패", info["error"]

    text = " ".join([info.get("title", ""), info.get("official", ""),
                     info.get("outcome", "")])
    m = SYMPTOM.search(text)
    if m:
        # 그 증상이 곧 적응증이면 증상완화 시험이 아니라 본 치료 시험이다.
        #   실측 오탐: dexamethasone / "Postoperative Nausea and Vomiting".
        #   구토를 치료하는 게 목적인데 "nausea"에 걸려 제외됐다.
        if m.group(0).lower() in (row.get("indication") or "").lower():
            pass
        else:
            return "제외", ("증상완화·지지요법 시험(%s) — 질환 치료 가설의 반례가 아니다"
                           % m.group(0))

    # 적응증이 시험 조건 목록에 실제로 있는가
    conds = " ; ".join(info.get("conditions", [])).lower()
    ind = re.findall(r"[a-z0-9]{4,}", (row.get("indication") or "").lower())
    if conds and ind and not any(t in conds for t in ind):
        return "확인필요", "적응증이 시험 조건과 안 맞음 (조건: %s)" % conds[:60]

    why = info.get("why_stopped", "")
    if not why:
        return "확인필요", "중단 사유 미기재 — 사람이 봐야 한다"
    return "유지", why[:90]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("labels", nargs="?", default="bench_labels.csv")
    ap.add_argument("--out", default="bench_tn_verified.csv")
    ap.add_argument("--cache", default="ctgov_cache.json")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)

    rows = [r for r in csv.DictReader(open(a.labels, encoding="utf-8-sig"))
            if r["label"] == "TN" and r["nct"].startswith("NCT")]
    if a.limit:
        rows = rows[:a.limit]

    try:
        cache = json.load(open(a.cache, encoding="utf-8"))
    except Exception:
        cache = {}

    print("=" * 78)
    print("ClinicalTrials.gov 원본 대조 — TN %d건" % len(rows))
    print("=" * 78)

    out, tally = [], {}
    for i, r in enumerate(rows, 1):
        info = fetch(r["nct"], cache)
        verdict, why = judge(r, info)
        tally[verdict] = tally.get(verdict, 0) + 1
        yr = year_of(info.get("completion") or info.get("start") or "")
        out.append(dict(r, ctgov_verdict=verdict, ctgov_why=why,
                        ctgov_title=info.get("title", ""),
                        ctgov_why_stopped=info.get("why_stopped", ""),
                        ctgov_start=info.get("start", ""),
                        ctgov_completion=info.get("completion", ""),
                        ctgov_year=yr or "",
                        ctgov_enrolled=info.get("enrolled") or ""))
        if i % 10 == 0 or i == len(rows):
            print("  %d/%d 조회" % (i, len(rows)))
            json.dump(cache, open(a.cache, "w", encoding="utf-8"), ensure_ascii=False)

    json.dump(cache, open(a.cache, "w", encoding="utf-8"), ensure_ascii=False)
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else ["nct"])
        w.writeheader()
        w.writerows(out)

    print("\n[재판정]")
    for k, v in sorted(tally.items(), key=lambda x: -x[1]):
        print("  %-8s %3d" % (k, v))

    keep = [o for o in out if o["ctgov_verdict"] == "유지"]
    yrs = [o["ctgov_year"] for o in keep if o["ctgov_year"]]
    print("\n[유지 %d건]" % len(keep))
    if yrs:
        print("  종료 연도 범위 %d–%d (시점 차단 검증에 쓸 수 있다)" % (min(yrs), max(yrs)))

    print("\n[제외된 것 — 자동 필터가 놓쳤던 오염]")
    for o in out:
        if o["ctgov_verdict"] == "제외":
            print("  %-22s %-26s %s" % (o["drug"][:22], o["indication"][:26], o["ctgov_why"][:44]))

    print("\n[사람이 봐야 할 것]")
    n = 0
    for o in out:
        if o["ctgov_verdict"] == "확인필요":
            n += 1
            if n <= 10:
                print("  %-20s %-24s %s" % (o["drug"][:20], o["indication"][:24],
                                            o["ctgov_title"][:40]))
    if n > 10:
        print("  … 외 %d건" % (n - 10))

    print("\n저장: %s" % a.out)
    print("=" * 78)
    print("자동 필터로 여기까지다. 남은 건 사람이 읽어야 한다.")
    print("작고 검증된 벤치마크가 크고 오염된 것보다 낫다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
