# -*- coding: utf-8 -*-
"""RepoDB → 벤치마크 라벨.

라벨이 틀리면 그 뒤 모든 숫자가 무의미하다. 그래서 이 파일은 걸러내는 규칙과
그 근거를 전부 명시한다. 통과율이 낮아도 통과율을 올리려고 규칙을 느슨하게
하지 않는다. 그건 자기기만이다.

실행: py -m bioreroute.bench.labels RepoDB.csv
"""

import argparse
import collections
import csv
import re
import sys

# ─────────────────────────────────────────────────────────────
# 1. 실패 사유 판별
# ─────────────────────────────────────────────────────────────
# 효능 실패 — 우리 가설("X는 Y에 효능이 있다")의 직접적 반례
EFFICACY = re.compile(
    r"lack of efficacy|inefficac|ineffective|futilit|futile"
    r"|no (benefit|efficacy|improvement|clinical benefit)"
    r"|did not (meet|show|demonstrate)|failed to (meet|show|demonstrate)"
    r"|(insufficient|inadequate|limited|poor) (efficacy|response|activity)"
    r"|efficacy (reasons?|concerns?|criteria)"
    r"|(primary )?(end ?point|outcome)[^.]{0,30}(not met|failed)", re.I)

# 안전성 실패 — 효능과는 다른 축이다. 반드시 따로 센다.
#   독성으로 중단된 약이 효능까지 없다는 보장은 없다. 우리 팩트체커는
#   효능만 판정하므로, 두 층을 섞으면 시스템이 맞았는데 틀렸다고 세게 된다.
SAFETY = re.compile(
    r"toxicit|hepatotox|cardiotox|nephrotox|neurotox"
    r"|safety (signal|concern|issue|reason)|serious adverse"
    r"|unacceptable|dose[- ]limiting|\bdlt\b|\bsae\b"
    r"|(increased|excess) (death|mortalit)|qt prolong", re.I)

# 부정문 — "안전성 문제 없음"을 안전성 실패로 읽으면 위양성이 된다.
#   실측 48건. 이 필터가 없으면 라벨이 오염된다.
NEGATED = re.compile(
    r"no (safety|toxicity|serious|significant|adverse|efficacy)[^.]{0,20}(concern|issue|signal|problem)?s?"
    r"|without (safety|toxicity|efficacy)"
    r"|not (due to|related to|because of|for) (safety|toxicity|efficacy)"
    r"|unrelated to (safety|efficacy|toxicity)"
    r"|non[- ]?(safety|efficacy|toxicity)"        # "terminated for non-safety reasons"
    r"|no concerns?", re.I)

# 운영 사유 — 과학적 반례가 아니다. 실측상 실패의 대부분이 여기 속한다.
OPERATIONAL = re.compile(
    r"accrual|enroll|recruit|funding|budget|sponsor decision|business"
    r"|administrative|staffing|logistic|supply|manufactur|covid|pandemic"
    r"|investigator (left|departure)|pi (left|departure)|strateg", re.I)

# ─────────────────────────────────────────────────────────────
# 2. 보조·지지 요법 차단
#    이 약들은 질환을 치료하는 게 아니라 다른 치료를 돕는다.
#    "X가 Y에 효능이 있다"는 가설 자체가 성립하지 않으므로 벤치마크에서 뺀다.
# ─────────────────────────────────────────────────────────────
ADJUNCT = {
    "leucovorin", "folinic acid", "levoleucovorin", "mesna", "dexrazoxane",
    "amifostine", "filgrastim", "pegfilgrastim", "sargramostim", "epoetin alfa",
    "darbepoetin alfa", "ondansetron", "granisetron", "palonosetron",
    "aprepitant", "dexamethasone", "prednisone", "prednisolone",
    "diphenhydramine", "ranitidine", "famotidine", "allopurinol", "rasburicase",
    "heparin", "saline", "water", "glucose", "dextrose", "sodium chloride",
    "lidocaine", "midazolam", "propofol", "fentanyl", "morphine",
    "acetaminophen", "paracetamol", "ibuprofen", "aspirin",
    "vitamin d", "calcium carbonate", "folic acid", "cyanocobalamin",
    "oxygen", "nitrous oxide", "ethanol", "alcohol",
}
# 염·에스터 형태가 별도 이름으로 들어오면 차단 목록을 빠져나간다.
#   실측: "dexamethasone" 은 막았는데 "dexamethasone phosphate" 가 통과했다.
_SALT = ("phosphate", "sodium", "succinate", "acetate", "hydrochloride", "hcl",
         "sulfate", "sulphate", "citrate", "tartrate", "maleate", "mesylate",
         "besylate", "fumarate", "palmitate", "valerate", "propionate")
ADJUNCT |= {"%s %s" % (d, s_) for d in list(ADJUNCT) for s_ in _SALT}

# 진단·조영 목적 — 치료제가 아니다
DIAGNOSTIC = re.compile(
    r"gadolinium|iohexol|iopamidol|technetium|fluorodeoxyglucose|contrast"
    r"|indocyanine|fluorescein|barium", re.I)

# 질환명에서 의미 없는 수식어. 세분도 비교 시 제거한다.
IND_STOP = {
    "disease", "diseases", "disorder", "disorders", "syndrome", "syndromes",
    "of", "the", "and", "or", "with", "in", "to", "nos", "unspecified",
    "malignant", "benign", "neoplasm", "neoplasms", "carcinoma", "cancer",
    "tumor", "tumour", "type", "stage", "grade", "primary", "secondary",
    "chronic", "acute", "severe", "moderate", "mild", "advanced",
}

FAIL_STATUS = {"Terminated", "Withdrawn", "Suspended"}
PHASE_RANK = {"Phase 3": 4, "Phase 2/Phase 3": 3, "Phase 2": 2,
              "Phase 1/Phase 2": 1, "Phase 1": 0, "Early Phase 1": 0, "NA": -1}


def reason_of(text: str):
    """실패 사유 분류. (효능|안전성|운영|불명, 근거문구)"""
    t = (text or "").strip()
    if not t or t.upper() == "NA":
        return "불명", ""
    # 대조약·병용약의 문제는 시험약의 실패가 아니다.
    if re.search(r"(active )?(control|comparator|reference) (drug|arm|agent|group)"
                 r"|other (arm|group)|concomitant (drug|medication)", t, re.I):
        return "불명", "대조약 사유 — 시험약의 실패로 볼 수 없다"

    if NEGATED.search(t):
        # 부정문이 있으면 그 문장은 실패 사유가 아니다. 남은 부분만 본다.
        stripped = NEGATED.sub(" ", t)
        if not (EFFICACY.search(stripped) or SAFETY.search(stripped)):
            return ("운영" if OPERATIONAL.search(t) else "불명"), "부정문 제외"
        t = stripped
    # 우선순위: 효능 > 운영 > 안전성
    #   운영을 안전성보다 앞에 두는 이유 — "strategic sponsor decision" 같은 문구에
    #   safety 단어가 섞여 들어오면 운영 중단이 안전성 실패로 둔갑한다.
    #   실측 오탐: warfarin/심방세동(표준 항응고제인데 TN으로 잡혔다).
    #   효능은 명시적 표현("lack of efficacy", "futility")이라 오탐이 적어 맨 앞에 둔다.
    if EFFICACY.search(t):
        return "효능", EFFICACY.search(t).group(0)
    if OPERATIONAL.search(t):
        return "운영", OPERATIONAL.search(t).group(0)
    if SAFETY.search(t):
        return "안전성", SAFETY.search(t).group(0)
    return "불명", ""


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def ind_tokens(s: str) -> frozenset:
    """질환명의 내용어 집합."""
    toks = re.findall(r"[a-z0-9]+", norm(s))
    return frozenset(t for t in toks if t not in IND_STOP and len(t) > 2)


# 토큰 희귀도 — 전체 적응증에서 몇 번 등장하는가. 흔한 토큰은 병을 특정하지 못한다.
_TOK_FREQ = {}
RARE = 40


def index_tokens(names):
    _TOK_FREQ.clear()
    for nm in set(names):
        for t in ind_tokens(nm):
            _TOK_FREQ[t] = _TOK_FREQ.get(t, 0) + 1


def disease_relation(a: frozenset, b: frozenset) -> str:
    """두 적응증의 관계. "동일" | "확인필요" | "무관"

    문자열만으로는 다음 둘을 구분할 수 없다.
      · 같은 병의 다른 이름   — "Brain Glioblastoma" / "Glioblastoma Multiforme"
      · 같은 병의 다른 아형   — "MS, Primary Progressive" / "MS, Relapsing-Remitting"
    앞은 반드시 제외해야 하고(테모졸로마이드는 GBM 표준치료제다),
    뒤는 반드시 살려야 한다(핀골리모드는 일차진행형에서 실제로 실패했다).

    부분집합이면 세분도 차이가 확실하므로 자동 제외한다.
    희귀 토큰만 공유하면 둘 중 어느 쪽인지 알 수 없으므로 사람에게 넘긴다.
    자동화가 감당 못 하는 지점을 감추지 않는 것이 요점이다.
    """
    if not a or not b:
        return "무관"
    if a <= b or b <= a:
        return "동일"
    shared = a & b
    if any(_TOK_FREQ.get(t, 999) <= RARE for t in shared):
        return "확인필요"
    return "무관"


def same_disease(a: frozenset, b: frozenset) -> bool:
    """세분도만 다른 같은 질환인가 — 부분집합 관계로 판정한다.

    "Diabetes Mellitus" ⊂ "Diabetes Mellitus, Non-Insulin-Dependent"  → 같은 질환
    "Pain"              ⊂ "Neuropathic Pain"                          → 같은 질환
    "MS, Primary Progressive" vs "MS, Relapsing-Remitting"            → 다른 질환 ✓

    마지막 사례가 중요하다. 핀골리모드는 재발완화형 MS에 승인됐지만
    일차진행형 MS 시험은 실패했다. 이건 진짜 TN이므로 살려야 한다.
    문자열 완전일치로는 메트포르민·가바펜틴 같은 오염을 못 막고,
    단순 토큰 겹침으로는 이 사례를 잘못 죽인다. 부분집합이 그 사이를 가른다.
    """
    if not a or not b:
        return False
    return a <= b or b <= a


def build(path: str):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))

    # ── 같은 쌍이 승인된 적 있으면 실패 라벨을 쓸 수 없다 ──────
    #   시험 하나가 멈춘 것이지 약이 안 듣는 게 아니다. 실측 250쌍.
    index_tokens(r["ind_name"] for r in rows)
    approved_by_drug = collections.defaultdict(list)
    for r in rows:
        if r["status"] == "Approved":
            approved_by_drug[norm(r["drug_name"])].append(
                (r["ind_name"], ind_tokens(r["ind_name"])))

    stats = collections.Counter()
    tn = {}
    for r in rows:
        if r["status"] not in FAIL_STATUS:
            continue
        stats["실패행"] += 1
        drug, ind = norm(r["drug_name"]), norm(r["ind_name"])

        # 결측치를 약 이름으로 쓰면 안 된다. RepoDB에 "NA" 문자열이 들어 있다.
        if drug in ("na", "n/a", "", "unknown", "none", "placebo"):
            stats["제외: 약물명 결측"] += 1
            continue

        # 같은 질환(세분도만 다른 경우 포함)으로 승인된 적이 있으면 TN이 아니다.
        it = ind_tokens(r["ind_name"])
        rels = [(disease_relation(it, at), an)
                for an, at in approved_by_drug.get(drug, ())]
        if any(k == "동일" for k, _ in rels):
            stats["제외: 같은 질환으로 승인됨"] += 1
            continue
        near = next((an for k, an in rels if k == "확인필요"), None)
        if drug in ADJUNCT:
            stats["제외: 보조·지지 요법"] += 1
            continue
        if DIAGNOSTIC.search(drug):
            stats["제외: 진단·조영제"] += 1
            continue

        kind, why = reason_of(r["DetailedStatus"])
        stats["사유: " + kind] += 1
        if kind not in ("효능", "안전성"):
            continue

        key = (drug, ind)
        rank = PHASE_RANK.get(r["phase"], -1)
        # 같은 쌍에 여러 실패가 있으면 가장 확증적인 상(Phase 3)을 남긴다
        prev = tn.get(key)
        if prev is None or rank > prev["phase_rank"] or \
           (rank == prev["phase_rank"] and kind == "효능" and prev["kind"] == "안전성"):
            tn[key] = {"drug": r["drug_name"].strip(), "indication": r["ind_name"].strip(),
                       "drugbank": r["drugbank_id"], "ind_id": r["ind_id"],
                       "nct": r["NCT"].strip(), "status": r["status"],
                       "phase": r["phase"], "phase_rank": rank,
                       "kind": kind, "why": why,
                       "near_approved": near or "",
                       "detail": r["DetailedStatus"].strip()[:200]}

    # ── TP: 승인 쌍 ────────────────────────────────────────────
    tp = {}
    for r in rows:
        if r["status"] != "Approved":
            continue
        drug, ind = norm(r["drug_name"]), norm(r["ind_name"])
        if drug in ("na", "n/a", "", "unknown", "none", "placebo"):
            continue
        if drug in ADJUNCT or DIAGNOSTIC.search(drug):
            continue
        tp.setdefault((drug, ind), {
            "drug": r["drug_name"].strip(), "indication": r["ind_name"].strip(),
            "drugbank": r["drugbank_id"], "ind_id": r["ind_id"],
            "nct": "", "status": "Approved", "phase": "NA", "phase_rank": 9,
            "kind": "승인", "why": "", "near_approved": "", "review": "", "detail": ""})
    return list(tn.values()), list(tp.values()), stats


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", default="RepoDB.csv")
    ap.add_argument("--out", default="bench_labels.csv")
    a = ap.parse_args(argv)

    tn, tp, stats = build(a.csv)

    # 자동화가 못 가른 8건에 대한 사람 판정을 적용한다.
    # 판정과 근거는 bench/review.py 에 기록돼 있다 — 코드에 숨기지 않는다.
    from . import review
    tn, dropped = review.apply(tn)

    print("=" * 74)
    print("RepoDB → 벤치마크 라벨")
    print("=" * 74)
    print("\n[걸러낸 내역]")
    for k in ("실패행", "제외: 약물명 결측", "제외: 같은 질환으로 승인됨",
              "제외: 보조·지지 요법",
              "제외: 진단·조영제", "사유: 효능", "사유: 안전성",
              "사유: 운영", "사유: 불명"):
        if stats[k]:
            print("  %-22s %5d" % (k, stats[k]))

    ke = collections.Counter(t["kind"] for t in tn)
    kp = collections.Counter(t["phase"] for t in tn)
    print("\n[TN 확정] %d쌍 (중복 제거 후)" % len(tn))
    print("  효능 실패 %d · 안전성 실패 %d" % (ke["효능"], ke["안전성"]))
    print("  상(phase): " + " · ".join("%s %d" % (k, v) for k, v in kp.most_common()))
    if dropped:
        print("\n[사람 판정으로 제외] %d건 — 같은 병의 다른 이름" % len(dropped))
        for t in dropped:
            print("  %-20s %-30s" % (t["drug"][:20], t["indication"][:30]))
            print("     %s" % t["review"][:88])

    near = [t for t in tn if t["near_approved"]]
    if near:
        judged = [t for t in near if t.get("review")]
        open_ = [t for t in near if not t.get("review")]
        print("\n[사람 확인 대상] %d건 중 판정 완료 %d · 미판정 %d"
              % (len(near), len(judged), len(open_)))
        for t in sorted(near, key=lambda x: x["drug"])[:14]:
            mark = "판정됨" if t.get("review") else "미판정"
            print("    [%s] %-18s 실패:%-26s 승인:%s"
                  % (mark, t["drug"][:18], t["indication"][:26], t["near_approved"][:24]))
        if len(near) > 14:
            print("    … 외 %d건" % (len(near) - 14))

    print("\n[TP 후보] %d쌍" % len(tp))

    print("\n[중요] 이 둘을 그대로 비교하면 안 된다.")
    print("  TP는 유명 승인약에 쏠려 있고 TN은 무명 실패다.")
    print("  분류기가 문헌 양만 보고 갈라낼 수 있어 AUROC가 허수가 된다.")
    print("  → 다음 단계(match)에서 PubMed 문헌량으로 짝을 맞춘다.")

    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[
            "label", "drug", "indication", "kind", "phase", "status",
            "nct", "drugbank", "ind_id", "why", "near_approved", "review", "detail"])
        w.writeheader()
        for t in tn:
            w.writerow(dict(label="TN",
                            **{k: t.get(k, "") for k in w.fieldnames if k != "label"}))
        for t in tp:
            w.writerow(dict(label="TP", **{k: t[k] for k in w.fieldnames if k != "label"}))
    print("\n저장: %s  (TN %d + TP %d)" % (a.out, len(tn), len(tp)))

    print("\n[TN 표본 12건 — 라벨이 맞는지 눈으로 확인하라]")
    for t in sorted(tn, key=lambda x: -x["phase_rank"])[:12]:
        print("  %-26s %-34s %-6s %-9s %s"
              % (t["drug"][:26], t["indication"][:34], t["kind"],
                 t["phase"], t["detail"][:44]))
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
