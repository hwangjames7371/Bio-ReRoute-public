# -*- coding: utf-8 -*-
"""전향 봉인 예측 — 제안서 §4.2 ③. **사후편향이 0인 유일한 숫자.**

    ① py -m bioreroute.bench.prospective probe              ← 필드가 맞는지 먼저 본다
    ② py -m bioreroute.bench.prospective harvest --status RECRUITING
    ③ py -m bioreroute.bench.prospective select --out prospective_pool.csv
    ④ py -m bioreroute.bench.prospective predict prospective_pool.csv --out 예측.csv
    ⑤ py -m bioreroute.bench.prospective seal 예측.csv      ← **즉시. 보기 전에.**
    ⑥ (몇 달 뒤) py -m bioreroute.bench.prospective verify 예측.csv

## 왜 이게 다른 것보다 급한가 — **시간 비대칭**

```
8/5  봉인 → 결과 축적 56일
8/25 봉인 → 결과 축적 36일
```

다른 항목은 나중에 해도 같은 결과가 나온다. **이것만 하루 미루면 하루치를
잃는다.** 그래서 완성도보다 **날짜**가 우선이다.

## 산출물은 정확도가 아니다

제안서 §4.2가 미리 못 박았다 —

> 본선 기간 내에 임상 결과가 확정되지 않을 수 있으므로, 산출물은 정확도
> 수치가 아니라 **봉인된 예측 목록과 사후 검증 절차**임을 분명히 한다.

**결과가 0건이어도 항목은 충족된다.** 그러니 "맞출 것 같은 것"을 고르는
유혹이 없다 — 오히려 그러면 안 된다.

## 표본 선택의 핵심 — **게시 기한 근처만 집는다**

FDAAA는 1차 완료 후 **12개월 내** 결과 게시를 요구한다. 그러므로
"1차 완료일이 지났는가"만 보면 안 되고 **얼마나 지났는가**를 봐야 한다.

```
 1개월 전   게시 기한이 2027년   → 56일 안에 안 나온다
12개월 전   기한이 바로 지금     → **가장 임박**
19년  전   좀비 등록           → 영영 안 나온다
```

실측으로 양끝을 다 봤다. `probe` 표본 50건에
`Sulfadoxine-pyrimethamine / Malaria` (1차 완료 **2007-06**, 아직
`ACTIVE_NOT_RECRUITING`)가 있었다. **"지났다"만 보면 이런 게 들어오고,
"최근 순"으로 고르면 반대편 끝(막 끝난 것)이 들어온다.**

그래서 창을 양쪽으로 자른다 — **1차 완료 후 6~36개월**, 그 안에서
**12개월에 가까운 순**(동률이면 큰 시험 우선).

## 음성 대조군을 같이 넣는다

제안서 §4.2 —

> 무작위 약물–질환 쌍을 음성 대조군으로 함께 투입한다. 대부분은 유효
> 적응증이 아니므로 보정이 잘 된 시스템은 낮은 신뢰도로 기각해야 한다.

단 **확정 음성이 아니라 추정 음성**으로 다룬다. 기각 안 된 쌍을 오류로
단정하지 않는다(제안서가 그렇게 쓰라고 했다).
"""

import argparse
import csv
import glob
import hashlib
import json
import os
import random
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime

from ..core import gates
from ..core.state import Candidate, RunState
from ..io import cache, llm, sources
from . import labels as L
from .ctharvest import _NOT_DRUG, _dig
from .discover import drug_key

BASE = "https://clinicaltrials.gov/api/v2/studies"
# **URL 길이 제한이 있으니 필드를 늘리지 마라** (ctharvest 에서 얻은 교훈)
FIELDS = ("NCTId,Condition,InterventionName,Phase,OverallStatus,"
          "PrimaryCompletionDate,DesignAllocation,EnrollmentCount,StudyType")
STATUS = ("RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION")

PAGES = "ctgov_ongoing"
COLS = ["nct", "kind", "drug", "condition", "phase", "allocation", "enrollment",
        "primary_completion", "status", "all_drugs", "all_conditions"]


def url_for(status, token=None, size=200):
    u = "%s?filter.overallStatus=%s&pageSize=%d&fields=%s" % (
        BASE, status, size, FIELDS)
    return u + ("&pageToken=" + token if token else "")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Bio-ReRoute"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def parse(st):
    """CT.gov 진행 중 시험 한 건 → dict. 못 쓰면 None.

    `ctharvest.parse_study` 와 나눈 이유 — 그쪽은 `whyStopped` 를 읽는다.
    진행 중 시험에는 그 필드가 없다. **없는 필드를 읽어 빈 값으로 처리하면
    "사유 불명"이라는 가짜 분류가 생긴다.**
    """
    p = st.get("protocolSection") or {}
    nct = _dig(p, "identificationModule", "nctId")
    if not nct:
        return None
    conds = _dig(p, "conditionsModule", "conditions", default=[]) or []
    ivs = [i.get("name", "") for i in
           (_dig(p, "armsInterventionsModule", "interventions", default=[]) or [])]
    drugs = [x for x in ivs if x and not _NOT_DRUG.match(x.strip())]
    pc = _dig(p, "statusModule", "primaryCompletionDateStruct", "date",
              default="") or ""
    return {
        "nct": nct, "kind": "진행중",
        "drug": drugs[0] if drugs else "", "all_drugs": " | ".join(drugs),
        "condition": conds[0] if conds else "",
        "all_conditions": " | ".join(conds),
        "phase": ",".join(_dig(p, "designModule", "phases", default=[]) or []),
        "allocation": _dig(p, "designModule", "designInfo", "allocation",
                           default="") or "",
        "enrollment": _dig(p, "designModule", "enrollmentInfo", "count",
                           default=""),
        "primary_completion": pc,
        "status": _dig(p, "statusModule", "overallStatus", default="") or "",
        "study_type": _dig(p, "designModule", "studyType", default="") or "",
        "has_results": bool(st.get("hasResults")),
    }


def usable(r, today=None):
    """예측 대상으로 쓸 수 있는가. **이유를 함께 돌려준다.**"""
    if r.get("has_results"):
        return False, "이미 결과가 게시됨 — 전향이 아니다"
    if (r.get("study_type") or "INTERVENTIONAL") != "INTERVENTIONAL":
        return False, "개입 연구 아님"
    if not r["drug"]:
        return False, "약물 개입 없음"
    if not r["condition"]:
        return False, "질환 없음"
    if r["allocation"] != "RANDOMIZED":
        return False, "무작위배정 아님(%s)" % (r["allocation"] or "미기재")
    ph = r["phase"]
    if not ph or ph in ("NA", "PHASE1", "EARLY_PHASE1"):
        return False, "1상 또는 미분류(%s)" % (ph or "없음")
    try:
        n = int(r["enrollment"] or 0)
    except Exception:
        n = 0
    if n < 50:
        return False, "등록 %d명 — 효능 판정에 부족" % n
    # ── **1차 완료일이 언제 지났는가**가 이 실험의 전부다 ────────────────
    #
    #   FDAAA는 1차 완료 후 **12개월 내** 결과 게시를 요구한다. 그러므로
    #   "지났다"만 보면 안 되고 **얼마나 지났는가**를 봐야 한다.
    #
    #     1개월 전   → 게시 기한이 2027년. **56일 안에 안 나온다**
    #     12개월 전  → 기한이 지금. **가장 임박했다**
    #     19년 전    → 좀비 등록. 영영 안 나온다
    #
    #   실측: probe 표본에 `Sulfadoxine-pyrimethamine / Malaria`
    #   (1차 완료 **2007-06**, 아직 ACTIVE_NOT_RECRUITING)이 있었다.
    #   "최근 순"으로만 고르면 반대편 끝(막 끝난 것)이 뽑혀 역시 안 나온다.
    #
    #   **양쪽 끝을 다 잘라내고 기한 근처만 남긴다.**
    pc = (r.get("primary_completion") or "")[:7]
    if not pc or len(pc) < 7:
        return False, "1차 완료일 미기재"
    m = months_since(pc, today)
    if m is None:
        return False, "1차 완료일 형식 이상(%s)" % pc
    if m < 0:
        return False, "1차 완료일이 아직 미래(%s · %d개월 뒤)" % (pc, -m)
    if m < MIN_MONTHS:
        return False, "1차 완료 %d개월 전 — 게시 기한이 아직 멀다" % m
    if m > MAX_MONTHS:
        return False, "1차 완료 %d개월 전 — 좀비 등록 의심" % m
    return True, ""


# 게시 기한(FDAAA 12개월) 근처만 남긴다. 양끝은 둘 다 "결과가 안 나온다".
MIN_MONTHS = 6
MAX_MONTHS = 36
DEADLINE = 12          # 이 값에 가까운 순으로 고른다


def months_since(pc, today=None):
    """'YYYY-MM' → 지금으로부터 몇 달 전인가. 못 읽으면 None."""
    t = today or datetime.now().strftime("%Y-%m")
    try:
        y0, m0 = int(pc[:4]), int(pc[5:7])
        y1, m1 = int(t[:4]), int(t[5:7])
    except Exception:
        return None
    return (y1 - y0) * 12 + (m1 - m0)


# ─────────────────────────────────────────────────────────────
def cmd_probe(a):
    """**필드 이름이 실제로 맞는지 한 쪽만 받아 확인한다.**

    나는 이 코드를 CT.gov 에 접근할 수 없는 환경에서 썼다. 필드명을
    추측으로 적었으면 수확을 다 돌린 뒤에야 빈 값을 발견한다.
    **모르는 것은 모른다고 하고, 한 쪽으로 확인한다.**
    """
    url = url_for(a.status, size=a.n)
    print("질의: %s\n" % url)
    try:
        d = _get(url)
    except Exception as e:
        print("실패: %s: %s" % (type(e).__name__, e))
        print("  py -m bioreroute.netcheck 로 연결을 확인하라.")
        return 1
    studies = d.get("studies") or []
    print("받은 시험 %d건 · 다음 쪽 있음 %s\n"
          % (len(studies), bool(d.get("nextPageToken"))))
    if not studies:
        print("0건이다. 필터가 틀렸을 수 있다.")
        return 1

    parsed = [r for r in (parse(st) for st in studies) if r]
    # ── **필드명이 틀린 것**과 **그 시험이 원래 없는 것**을 가른다 ──────────
    #   첫 판은 빈 값을 그냥 세어 "빈 필드가 있다"고 경고했다. 관찰연구에
    #   phase·drug 가 없는 건 **정상**인데 경고가 떴다. 진단이 조잡하면
    #   사람이 경고를 무시하는 법을 배우고, 그러면 진짜 경고도 놓친다.
    KEYS = ("nct", "condition", "primary_completion", "status", "study_type",
            "allocation", "phase", "drug")
    filled = {k: sum(1 for r in parsed if r.get(k)) for k in KEYS}
    print("필드 점검 — **전부 비면 이름이 틀린 것**, 일부만 비면 정상")
    dead = []
    for k in KEYS:
        n = filled[k]
        mark = "★ 이름 오류 의심" if n == 0 else ""
        if n == 0:
            dead.append(k)
        print("   %-20s %2d/%-2d 채워짐  %s" % (k, n, len(parsed), mark))
    if dead:
        print("\n**%s 가 전부 비었다. FIELDS 를 고쳐야 한다.**" % ", ".join(dead))
        return 1
    print("\n필드명은 맞다.\n")

    print("표본 %d건의 통과·탈락" % len(parsed))
    stat, keep = Counter(), 0
    for r in parsed:
        ok, why = usable(r)
        stat[why or "**사용 가능**"] += 1
        keep += ok
        if a.verbose or ok:
            print("  %s %s  %-24s %-20s %s %s명 %s"
                  % ("O" if ok else "·", r["nct"], (r["drug"] or "—")[:24],
                     (r["condition"] or "—")[:20], r["phase"] or "—",
                     r["enrollment"] or "?", r["primary_completion"] or "—"))
            if not ok:
                print("      → %s" % why)
    print()
    for k, v in stat.most_common():
        print("   %-42s %3d" % (k[:42], v))

    rate = keep / len(parsed)
    print("\n예상 수율 %.0f%% — %d쪽 × 200건이면 대략 **%d건** 확보"
          % (100 * rate, a.pages, int(rate * a.pages * 200)))
    if keep == 0:
        print("  이 표본에선 0건이다. 표본이 작아서일 수 있으니 --n 50 으로 다시 보라.")
        print("  그래도 0이면 필터가 너무 빡빡한 것이다 — 등록 하한이나 상 조건을 보라.")
    return 0


def cmd_harvest(a):
    os.makedirs(a.dir, exist_ok=True)
    token, n, page = None, 0, 0
    while page < a.max_pages:
        try:
            d = _get(url_for(a.status, token, a.size))
        except Exception as e:
            print("  중단 — %s: %s" % (type(e).__name__, e))
            print("  받은 데까지는 저장돼 있다. 연결 고치고 다시 돌리면 이어진다.")
            return 1
        studies = d.get("studies") or []
        if not studies:
            break
        page += 1
        n += len(studies)
        p = os.path.join(a.dir, "%s_%04d.json" % (a.status.lower(), page))
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        token = d.get("nextPageToken")
        if page % 10 == 0 or not token:
            print("  %d쪽 · %d건" % (page, n))
        if not token:
            break
    print("저장 %d쪽 · %d건 → %s/" % (page, n, a.dir))
    return 0


def _existing_pairs():
    """이미 벤치마크에 쓴 쌍. **겹치면 전향이 아니다.**"""
    seen = set()
    for path, dc, cc in (("bench_matched.csv", "drug", "indication"),
                         ("bench_holdout_matched_sealed.csv", "drug", "indication"),
                         ("bench_tn_pool_v2.csv", "drug", "condition"),
                         ("gen_matched.csv", "drug", "indication")):
        if not os.path.exists(path):
            continue
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            if r.get(dc) and r.get(cc):
                seen.add((drug_key(r[dc]), L.ind_tokens(r[cc])))
    return seen


def cmd_select(a):
    files = sorted(glob.glob(os.path.join(a.dir, "*.json")))
    if not files:
        print("수확본이 없다: %s/ — harvest 를 먼저 돌려라." % a.dir)
        return 1
    rows, stat, seen = [], Counter(), set()
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            stat["파일 오류"] += 1
            continue
        for st in d.get("studies") or []:
            r = parse(st)
            if r is None:
                stat["파싱 실패"] += 1
                continue
            if r["nct"] in seen:
                continue
            seen.add(r["nct"])
            ok, why = usable(r)
            stat[why or "사용 가능"] += 1
            if ok:
                rows.append(r)

    print("수확 %d건 → 필터 결과" % len(seen))
    for k, v in stat.most_common():
        print("  %-40s %5d" % (k[:40], v))

    # 이미 쓴 쌍 제외 — 겹치면 전향이 아니다
    prev = _existing_pairs()
    before = len(rows)
    rows = [r for r in rows
            if (drug_key(r["drug"]), L.ind_tokens(r["condition"])) not in prev]
    print("\n기존 벤치마크와 겹치는 쌍 제외: %d → %d" % (before, len(rows)))

    # ── 게시 기한(12개월)에 **가까운 순**으로 고른다 ────────────────────
    #   "최근 순"이 아니다. 막 끝난 시험은 기한이 아직 멀어 안 나오고,
    #   너무 오래된 것은 좀비다. 양끝을 피해 기한 근처를 집는다.
    for r in rows:
        r["_m"] = months_since(r["primary_completion"][:7]) or 999
    rows.sort(key=lambda x: (abs(x["_m"] - DEADLINE), -int(x["enrollment"] or 0)))

    # 같은 (약물, 질환) 쌍은 하나로 — 시험이 여럿이어도 가설은 하나다
    uniq, out = set(), []
    for r in rows:
        k = (drug_key(r["drug"]), L.ind_tokens(r["condition"]))
        if k in uniq:
            continue
        uniq.add(k)
        out.append(r)
    print("중복 쌍 제거: %d → %d" % (len(rows), len(out)))

    out = out[:a.n]
    if out:
        ms = sorted(r["_m"] for r in out)
        print("게시 기한(%d개월) 근처 순으로 %d건 선택 — 1차 완료 후 %d~%d개월"
              % (DEADLINE, len(out), ms[0], ms[-1]))
    for r in out:
        r.pop("_m", None)

    # ── 음성 대조군 (제안서 §4.2) ────────────────────────────
    if a.controls:
        rnd = random.Random(a.seed)
        drugs = sorted({r["drug"] for r in out})
        conds = sorted({r["condition"] for r in out})
        made, tries = [], 0
        real = {(drug_key(r["drug"]), r["condition"]) for r in out}
        while len(made) < a.controls and tries < a.controls * 200:
            tries += 1
            d0, c0 = rnd.choice(drugs), rnd.choice(conds)
            if (drug_key(d0), c0) in real:
                continue
            if (drug_key(d0), L.ind_tokens(c0)) in prev:
                continue
            if any(x["drug"] == d0 and x["condition"] == c0 for x in made):
                continue
            made.append({"nct": "", "kind": "음성대조", "drug": d0,
                         "condition": c0, "phase": "", "allocation": "",
                         "enrollment": "", "primary_completion": "",
                         "status": "", "all_drugs": d0, "all_conditions": c0})
        out += made
        print("음성 대조군 %d쌍 추가 (**추정 음성** — 확정 음성이 아니다)" % len(made))

    if os.path.exists(a.out) and not a.force:
        print("\n이미 있는 파일이다: %s — 덮어쓰려면 --force" % a.out)
        return 2
    with open(a.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    # ── **어디서 뽑았는지를 남긴다** ─────────────────────────────────────
    #   봉인 예측의 값어치는 "무엇을 예측했나"만이 아니라 "무엇 중에서
    #   골랐나"에 있다. 수확 범위를 안 적으면 나중에 **표본을 유리하게
    #   골랐다**는 의심을 반박할 수 없다.
    man = os.path.splitext(a.out)[0] + "_manifest.json"
    json.dump({
        "만든시각": datetime.now().isoformat(timespec="seconds"),
        "수확": {"쪽수": len(files), "고유 시험": len(seen), "디렉터리": a.dir},
        "필터결과": dict(stat),
        "선택조건": {"창": "1차완료 %d~%d개월 전" % (MIN_MONTHS, MAX_MONTHS),
                  "정렬": "%d개월 기한에 가까운 순 · 동률이면 큰 시험" % DEADLINE,
                  "제외": "기존 벤치마크 겹침 · (약물,질환) 중복"},
        "결과": {"진행중": sum(1 for r in out if r["kind"] == "진행중"),
               "음성대조": sum(1 for r in out if r["kind"] == "음성대조")},
    }, open(man, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n저장: %s (%d행 · 진행중 %d · 대조 %d)"
          % (a.out, len(out), sum(1 for r in out if r["kind"] == "진행중"),
             sum(1 for r in out if r["kind"] == "음성대조")))
    print("      %s — 수확 범위·필터 내역" % man)
    return 0


def cmd_predict(a):
    rows = list(csv.DictReader(open(a.pool, encoding="utf-8-sig")))
    if os.path.exists(a.out) and not a.force:
        print("이미 있는 예측 파일이다: %s — 덮어쓰려면 --force" % a.out)
        print("  **예측을 다시 만드는 것은 봉인의 의미를 지운다.** 정말인지 확인해라.")
        return 2
    if not llm.available():
        print("LLM이 없다. 예측할 수 없다 — py -m bioreroute.diag")
        return 1
    cache.configure(a.cache)
    cache.load()                       # **질의 전에** 읽는다 (결함 26·27)

    # 진행 중 시험은 라벨 출처가 아니다. 다만 **그 시험 자신의 등록부 기록**은
    # 근거로 쓰면 안 된다 — 아직 결과가 없으니 새어도 얻을 게 없지만,
    # 설계·중간분석 기술이 지지 근거로 읽힐 수 있다.
    ncts = {r["nct"] for r in rows if r.get("nct")}
    info = gates.set_exclude(ncts)
    print("[제외] 대상 시험 %d건 + 그 논문 %d건" % (info["ncts"], info["pmids"]))
    if info.get("failed"):
        print("**누출 차단 확장이 %d건 실패했다. 여기서 멈춘다.**" % info["failed"])
        print("  py -m bioreroute.netcheck 로 연결을 확인하고 다시 돌려라.")
        return 1

    cands = []
    for r in rows:
        c = Candidate(name="%s / %s" % (r["drug"], r["condition"]),
                      origin=r["kind"], query="%s AND %s" % (r["drug"], r["condition"]),
                      drug=r["drug"], disease=r["condition"], pubchem=r["drug"])
        c.note("prospective", "INPUT", "%s · NCT %s" % (r["kind"], r["nct"] or "—"))
        cands.append(c)
    st = RunState(query_title="전향 봉인 예측", settings=a.config,
                  stamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
                  candidates=cands, config=dict(gates.CONFIGS[a.config]))
    print("\n예측 %d건 · 구성 %s …" % (len(cands), a.config))
    st = gates.run_pipeline(st)
    cache.save()

    with open(a.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["nct", "kind", "drug", "condition", "verdict", "confidence",
                    "reason", "n_support", "n_refute", "primary_completion"])
        for r, c in zip(rows, st.candidates):
            w.writerow([r.get("nct", ""), r["kind"], r["drug"], r["condition"],
                        c.verdict, c.confidence, c.reason,
                        len(c.support), len(c.refute),
                        r.get("primary_completion", "")])
    v = Counter(c.verdict for c in st.candidates)
    print("\n판정 분포: " + " · ".join("%s %d" % (k, v[k])
                                   for k in ("유망", "조건부", "보류", "기각")))
    print("저장: %s" % a.out)
    print("\n**지금 즉시 봉인해라.** 봉인 없는 예측은 예측이 아니다.")
    print("  py -m bioreroute.bench.prospective seal %s" % a.out)
    return 0


def cmd_seal(a):
    rows = list(csv.DictReader(open(a.pred, encoding="utf-8-sig")))
    # **풀과 예측을 헷갈리기 쉽다.** 파일 이름이 비슷하고 순서가 붙어 있다.
    #   전에는 KeyError 로 죽었다 — 무엇이 잘못됐는지 안 알려주는 죽음이다.
    need = {"verdict", "confidence", "kind", "drug", "condition"}
    have = set(rows[0].keys()) if rows else set()
    if not rows or not need <= have:
        print("예측 파일이 아니다: %s" % a.pred)
        print("  없는 열: %s" % ", ".join(sorted(need - have)))
        print("  풀(pool)이 아니라 **predict 가 만든 파일**을 넘겨라.")
        print("  py -m bioreroute.bench.prospective predict <풀> --out <예측>")
        return 2
    h = hashlib.sha256(open(a.pred, "rb").read()).hexdigest()
    v = Counter(r["verdict"] for r in rows)
    out = os.path.splitext(a.pred)[0] + "_봉인.json"
    seal = {
        "예측파일": a.pred, "sha256": h,
        "봉인시각": datetime.now().isoformat(timespec="seconds"),
        "건수": len(rows),
        "표본조건": {
            "상태": "ACTIVE_NOT_RECRUITING 등 진행 중",
            "결과": "미게시(hasResults=false)",
            "설계": "무작위배정 · 2상 이상 · 등록 50명 이상 · 개입연구",
            "1차완료": "%d~%d개월 전 (%d개월 기한에 가까운 순)"
                    % (MIN_MONTHS, MAX_MONTHS, DEADLINE),
            "제외": "기존 벤치마크와 겹치는 쌍 · 같은 (약물,질환) 중복",
        },
        "진행중": sum(1 for r in rows if r["kind"] == "진행중"),
        "음성대조": sum(1 for r in rows if r["kind"] == "음성대조"),
        "판정분포": dict(v),
        "검증절차": [
            "1. 각 NCT의 결과 게시 여부를 CT.gov에서 재조회한다",
            "2. 1차 평가변수 달성 여부를 읽는다 (달성=양성 · 미달성=음성)",
            "3. 결과 미게시는 **미확정**으로 두고 정확도 계산에서 뺀다",
            "4. `보류` 판정은 기권이다. 커버리지와 선택정확도를 따로 보고한다",
            "5. 음성대조는 **추정 음성**이다. 기각 안 됐다고 오류로 단정하지 않는다",
            "6. 검증 시점의 코드 판번호를 함께 기록한다",
        ],
        "한계": [
            "본선 기간 내에 결과가 확정되지 않을 수 있다 (제안서 §4.2가 명시)",
            "산출물은 정확도가 아니라 **봉인된 예측 목록과 검증 절차**다",
            "LLM 사전학습에 이 시험들의 중간 정보가 있을 수 있다 — 완전한 전향이 아니다",
            "CT.gov 전수가 아니라 **수확한 범위 안에서** 골랐다 (manifest 참조)",
            "게시 기한 창(6~36개월)은 결과가 나올 확률을 높이려 정한 것이고, "
            "그 자체가 시험을 골라내는 선택 효과다",
        ],
    }
    # ── **진짜 시각은 git 커밋에 있다** ─────────────────────────────────
    #
    #   이 파일의 `봉인시각` 은 **이 컴퓨터의 시계**가 찍은 값이라 증거로
    #   약하다. 시스템 시각을 바꾸면 그만이다. 반면 push 된 커밋의 시각은
    #   서버가 찍는다.
    #
    #   그러므로 **예측 CSV를 먼저 push 하고 나중에 봉인해도 된다.**
    #   오히려 그쪽이 강하다 — 서버 시각이 더 앞서기 때문이다.
    #   (사전명세는 다르다. 그건 **실행**보다 앞서야 하므로 분 단위로 엄격하다.
    #    전향 예측이 앞서야 하는 것은 **임상 결과 게시**이고 그건 개월 단위다.)
    #
    #   여기서는 git 명령을 부르지 않고 `.git` 파일을 읽기만 한다.
    head = None
    try:
        with open(os.path.join(".git", "HEAD"), encoding="utf-8") as fh:
            ref = fh.read().strip()
        if ref.startswith("ref: "):
            with open(os.path.join(".git", ref[5:]), encoding="utf-8") as fh:
                head = fh.read().strip()
        elif len(ref) == 40:
            head = ref
    except Exception:
        pass
    seal["git_HEAD"] = head or "읽지 못함"
    seal["시각근거"] = ("서버가 찍은 **커밋 시각**이 증거다. 아래 봉인시각은 "
                    "이 컴퓨터의 시계이므로 보조 기록일 뿐이다.")

    # 표본 출처를 봉인에 같이 넣는다 — "어디서 골랐나"가 없으면 반박할 수 없다
    man = None
    for cand in (os.path.splitext(a.pred)[0] + "_manifest.json",
                 "prospective_pool_manifest.json"):
        if os.path.exists(cand):
            man = cand
            break
    if man:
        seal["표본출처"] = json.load(open(man, encoding="utf-8"))
        seal["표본출처파일"] = man
    else:
        seal["표본출처"] = "manifest 없음 — select 를 다시 돌리면 남는다"
    json.dump(seal, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("봉인: %s" % out)
    print("  sha256 %s" % h)
    print("  %d건 (진행중 %d · 대조 %d) · %s"
          % (seal["건수"], seal["진행중"], seal["음성대조"], dict(v)))
    print("\n**지금 커밋하고 푸시해라. 서버측 시각이 증거다.**")
    print("  git add %s %s" % (a.pred, out))
    print('  git commit -m "전향 봉인 예측 %d건 — 결과 확정 전"' % len(rows))
    print("  git push")
    return 0


def cmd_verify(a):
    """몇 달 뒤. 결과가 나온 것만 채점한다."""
    from .ceiling import fetch
    rows = list(csv.DictReader(open(a.pred, encoding="utf-8-sig")))
    seal_p = os.path.splitext(a.pred)[0] + "_봉인.json"
    if os.path.exists(seal_p):
        s = json.load(open(seal_p, encoding="utf-8"))
        now = hashlib.sha256(open(a.pred, "rb").read()).hexdigest()
        print("봉인 대조: %s" % ("**동일**" if now == s["sha256"] else "★★ 바뀌었다 ★★"))
        print("  봉인 %s · 지금 %s" % (s["sha256"][:16], now[:16]))
        if now != s["sha256"]:
            print("  **예측 파일이 바뀌었다. 이 검증은 무효다.**")
            return 2
        print("  봉인 시각 %s\n" % s["봉인시각"])

    cache.configure(a.cache)
    cache.load()
    rc = {}
    if os.path.exists(a.results_cache):
        rc = json.load(open(a.results_cache, encoding="utf-8"))
    done, pend = [], 0
    for r in rows:
        if r["kind"] != "진행중" or not r["nct"]:
            continue
        f = fetch(r["nct"], rc)
        if f.get("error") or not f.get("has_results"):
            pend += 1          # 조회 실패와 미게시를 여기서는 같이 센다 —
            continue           #   둘 다 "아직 채점 못 함"이다
        done.append((r, f))
    json.dump(rc, open(a.results_cache, "w", encoding="utf-8"), ensure_ascii=False)
    cache.save()
    print("결과 게시됨 %d건 · 미게시 %d건" % (len(done), pend))
    if not done:
        print("\n아직 채점할 것이 없다. **그것도 결과다** — 제안서 §4.2가")
        print("'결과 확정에 시간 소요'를 이 방법의 한계로 미리 적었다.")
        return 0
    print("\n게시된 시험 — **1차 평가변수는 사람이 읽어야 한다**")
    for r, f in done:
        print("  %-12s %-22s %-20s 예측 %s(%s) · 결과 수치 %d개"
              % (r["nct"], r["drug"][:22], r["condition"][:20],
                 r["verdict"], r["confidence"], f.get("n_outcomes", 0)))
    print("\n  자동 채점하지 않는다 — 1차 평가변수 달성 여부는 판단이 필요하다.")
    print("  위 목록을 읽고 `전향예측결과.md` 에 손으로 적어라. 그게 정직하다.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="전향 봉인 예측 (제안서 §4.2 ③)")
    sub = ap.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("probe", help="한 쪽만 받아 **필드·수율**을 확인")
    p.add_argument("--status", default="ACTIVE_NOT_RECRUITING", choices=STATUS)
    p.add_argument("-n", type=int, default=50, help="표본 몇 건")
    p.add_argument("--pages", type=int, default=60, help="수율 환산에 쓸 쪽수")
    p.add_argument("--verbose", action="store_true", help="탈락한 것도 전부 출력")

    h = sub.add_parser("harvest", help="진행 중 시험 수확")
    h.add_argument("--status", default="ACTIVE_NOT_RECRUITING", choices=STATUS)
    h.add_argument("--dir", default=PAGES)
    h.add_argument("--size", type=int, default=200)
    h.add_argument("--max-pages", type=int, default=60)

    s = sub.add_parser("select", help="수확본 → 예측 대상 풀")
    s.add_argument("--dir", default=PAGES)
    s.add_argument("--out", required=True)
    s.add_argument("-n", type=int, default=60, help="진행중 시험 몇 건")
    s.add_argument("--controls", type=int, default=20, help="음성 대조 몇 쌍")
    s.add_argument("--seed", type=int, default=20260805)
    s.add_argument("--force", action="store_true")

    d = sub.add_parser("predict", help="풀 → 예측 (LLM 씀)")
    d.add_argument("pool")
    d.add_argument("--out", required=True)
    d.add_argument("--config", default="B5", choices=list(gates.CONFIGS))
    d.add_argument("--cache", default="pubmed_cache.json")
    d.add_argument("--force", action="store_true")

    z = sub.add_parser("seal", help="예측을 해시로 봉인")
    z.add_argument("pred")

    v = sub.add_parser("verify", help="(나중에) 결과가 나온 것만 채점")
    v.add_argument("pred")
    v.add_argument("--cache", default="pubmed_cache.json")
    v.add_argument("--results-cache", default="ctgov_results_cache.json")

    a = ap.parse_args(argv)
    return {"probe": cmd_probe, "harvest": cmd_harvest, "select": cmd_select,
            "predict": cmd_predict, "seal": cmd_seal, "verify": cmd_verify}[a.mode](a)


if __name__ == "__main__":
    sys.exit(main())
