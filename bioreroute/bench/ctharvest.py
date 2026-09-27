# -*- coding: utf-8 -*-
"""CT.gov 수확 → **새 TN 후보 풀.**

이 프로젝트에 없는 단 하나: **깨끗한 홀드아웃.** 층 B는 폐쇄형 누출률이
64%라 못 썼고, 기존 후보 90건은 이미 튜닝에 노출됐다. 새 재료가 필요하다.

이 파일은 **HTTP를 하지 않는다.** 페이지를 받아 파일로 저장하는 일은 상위
에이전트가 하고, 여기서는 그 JSON을 **파싱·분류·중복제거**만 한다.
그래서 네트워크 없이도 전부 재현·시험 가능하다.

    수집   (에이전트가 web_fetch로 pageN.json 저장)
      └─ ctharvest --merge pages/ → bench_tn_pool_v2.csv

**분류기는 `labels.reason_of` 를 그대로 쓴다.** 새 어휘를 만들면 기존 풀과
비교가 불가능해진다 — 홀드아웃의 존재 이유가 사라진다.

사용법
  py -m bioreroute.bench.ctharvest --merge pages/ --exclude bench_tn_candidates.csv
  py -m bioreroute.bench.ctharvest --url            # 다음 질의 URL을 찍는다
"""

import argparse
import csv
import glob
import json
import os
import re
import sys
from collections import Counter

from . import labels as L

BASE = "https://clinicaltrials.gov/api/v2/studies"
FIELDS = ("NCTId,WhyStopped,Condition,InterventionName,Phase,"
          "CompletionDate,DesignAllocation,EnrollmentCount")
STATUS = ("TERMINATED", "WITHDRAWN", "SUSPENDED")

# 개입명에서 걸러낼 것 — 약물 재창출 가설의 대상이 아니다.
_NOT_DRUG = re.compile(
    r"^(placebo|saline|vehicle|sham|standard of care|best supportive care|"
    r"observation|no intervention|questionnaire|survey|exercise|diet|"
    r"radiation|surgery|counsel|education|physical therapy)\b", re.I)


def next_url(token=None, status="TERMINATED", size=200):
    """다음 페이지 URL. **URL 길이 제한이 있으니 필드를 늘리지 마라.**"""
    u = "%s?filter.overallStatus=%s&pageSize=%d&fields=%s" % (
        BASE, status, size, FIELDS)
    return u + ("&pageToken=" + token if token else "")


def _dig(d, *path, default=None):
    for k in path:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d


def parse_study(st):
    """CT.gov 한 건 → dict. 못 쓰는 건 None."""
    p = st.get("protocolSection") or {}
    nct = _dig(p, "identificationModule", "nctId")
    if not nct:
        return None
    why = _dig(p, "statusModule", "whyStopped", default="") or ""
    date = _dig(p, "statusModule", "completionDateStruct", "date", default="") or ""
    conds = _dig(p, "conditionsModule", "conditions", default=[]) or []
    ivs = [i.get("name", "") for i in
           (_dig(p, "armsInterventionsModule", "interventions", default=[]) or [])]
    drugs = [x for x in ivs if x and not _NOT_DRUG.match(x.strip())]
    phases = _dig(p, "designModule", "phases", default=[]) or []
    alloc = _dig(p, "designModule", "designInfo", "allocation", default="") or ""
    n = _dig(p, "designModule", "enrollmentInfo", "count", default="")

    cls, quote = L.reason_of(why)
    return {"nct": nct, "drug": drugs[0] if drugs else "",
            "all_drugs": " | ".join(drugs), "condition": conds[0] if conds else "",
            "all_conditions": " | ".join(conds),
            "phase": ",".join(phases), "allocation": alloc, "enrollment": n,
            "completion_year": date[:4], "why_stopped": why,
            "stop_class": cls, "stop_quote": quote}


def usable(r):
    """홀드아웃 후보로 쓸 수 있는가. **이유를 함께 돌려준다.**"""
    if not r["drug"]:
        return False, "약물 개입 없음"
    if not r["condition"]:
        return False, "질환 없음"
    if r["stop_class"] != "효능":
        return False, "중단 사유: %s" % r["stop_class"]
    # 단일군은 효능을 반증할 수 없다 — 발견 ①에서 가장 큰 손실 지점이었다.
    if r["allocation"] != "RANDOMIZED":
        return False, "무작위배정 아님(%s)" % (r["allocation"] or "미기재")
    ph = r["phase"]
    if not ph or ph in ("NA", "PHASE1", "EARLY_PHASE1"):
        return False, "1상 또는 미분류(%s)" % (ph or "없음")
    return True, ""


def merge(pages, exclude_csv=None):
    """페이지 JSON들 → (후보목록, 통계)."""
    seen, rows, stat = set(), [], Counter()
    for path in sorted(pages):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            stat["파일 오류"] += 1
            print("  [건너뜀] %s — %s" % (os.path.basename(path), e))
            continue
        for st in d.get("studies", []):
            r = parse_study(st)
            stat["총 시험"] += 1
            if not r:
                stat["파싱 실패"] += 1
                continue
            if r["nct"] in seen:
                stat["페이지 간 중복"] += 1
                continue
            seen.add(r["nct"])
            ok, why = usable(r)
            stat["사용가능" if ok else why] += 1
            if ok:
                rows.append(r)

    # ── 기존 풀과의 중복 제거 ────────────────────────────────────────
    #   **이걸 안 하면 홀드아웃이 아니다.** 이미 본 쌍이 섞이면 그 순간
    #   "한 번도 안 본 자료"라는 성질이 사라진다.
    if exclude_csv and os.path.exists(exclude_csv):
        old = list(csv.DictReader(open(exclude_csv, encoding="utf-8-sig")))
        old_pairs = {(L.norm(o.get("drug", "")), L.norm(o.get("disease", "")))
                     for o in old}
        old_drugs = {L.norm(o.get("drug", "")) for o in old}
        kept = []
        for r in rows:
            key = (L.norm(r["drug"]), L.norm(r["condition"]))
            if key in old_pairs:
                stat["기존 풀과 쌍 중복"] += 1
                r["dup"] = "쌍"
            elif L.norm(r["drug"]) in old_drugs:
                # 약물만 겹치는 것은 **버리지 않는다.** 다른 질환이면 다른
                #   가설이다. 다만 표시해 두어 필요하면 뺄 수 있게 한다.
                stat["약물만 겹침(유지)"] += 1
                r["dup"] = "약물"
                kept.append(r)
            else:
                r["dup"] = ""
                kept.append(r)
        rows = kept
    else:
        for r in rows:
            r["dup"] = ""
        if exclude_csv:
            print("  [경고] 제외 목록 %s 이 없다 — **중복 제거를 못 했다.**"
                  % exclude_csv)
    return rows, stat


COLS = ("nct", "drug", "condition", "phase", "allocation", "enrollment",
        "completion_year", "stop_class", "stop_quote", "why_stopped",
        "all_drugs", "all_conditions", "dup")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge", metavar="DIR",
                    help="페이지 JSON이 있는 디렉터리")
    ap.add_argument("--out", default="bench_tn_pool_v2.csv")
    ap.add_argument("--exclude", default="bench_tn_candidates.csv",
                    help="기존 후보 풀 — 중복을 뺀다")
    ap.add_argument("--url", action="store_true", help="첫 질의 URL을 찍는다")
    ap.add_argument("--token", default=None, help="--url 과 함께: 이어받을 토큰")
    ap.add_argument("--status", default="TERMINATED", choices=STATUS)
    a = ap.parse_args(argv)

    if a.url:
        print(next_url(a.token, a.status))
        return 0
    if not a.merge:
        ap.error("--merge DIR 또는 --url 중 하나가 필요하다")

    pages = glob.glob(os.path.join(a.merge, "*.json"))
    if not pages:
        print("%s 에 JSON이 없다." % a.merge)
        return 1

    print("=" * 78)
    print("CT.gov 수확 병합 — 페이지 %d개" % len(pages))
    print("=" * 78)
    rows, stat = merge(pages, a.exclude)

    for k, v in stat.most_common():
        print("  %-28s %5d" % (k, v))

    if not rows:
        print("\n쓸 수 있는 후보가 없다.")
        return 1

    yrs = [int(r["completion_year"]) for r in rows if r["completion_year"].isdigit()]
    print("\n%s" % ("-" * 78))
    print("최종 후보 %d건" % len(rows))
    if yrs:
        print("  종료 연도 %d~%d · 중앙값 %d"
              % (min(yrs), max(yrs), sorted(yrs)[len(yrs) // 2]))
    print("  상 분포 %s" % dict(Counter(r["phase"] for r in rows).most_common(5)))
    print("  약물만 겹치는 것 %d건 (dup 열로 표시)"
          % sum(1 for r in rows if r["dup"] == "약물"))

    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("\n저장: %s" % a.out)

    print("\n" + "=" * 78)
    print("다음에 할 일 — **여기서 끝이 아니다**")
    print("=" * 78)
    print("① 승인 적응증 교차검증. 승인된 쌍이 TN으로 섞이면 라벨이 틀린다")
    print("   (기존 풀에서 23% 오염이 나왔다).")
    print("② 보조요법·증상완화 제외. `leucovorin`·`ondansetron` 류가 남아 있다.")
    print("③ 문헌량 매칭으로 TP 짝 만들기 — **PubMed이 필요하므로 로컬에서.**")
    print("④ 짝짓기 전까지는 성능을 재지 마라. 교란이 통제되지 않는다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
