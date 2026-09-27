# -*- coding: utf-8 -*-
"""등록부 근거 감사 — 53%가 진짜인지 두 가지를 캔다. LLM 없이, 무료로.

ceiling이 "쓸 수 있는 독립 시험 53%"를 냈다. 쓰기 전에 두 번 의심해야 한다.

━━━ ① 오염 — 그 시험이 정말 그 가설을 시험했는가 ━━━

  등록부 검색은 3단으로 완화된다. 마지막 단은 **자유 문자열**이다.
  "gabapentin AND breast cancer"로 찾으면 유방암 환자의 **안면홍조**를
  가바펜틴으로 다스린 시험이 걸린다. 그건 "가바펜틴이 유방암을 치료한다"가
  아니다 — 우리가 벤치마크에서 명시적으로 제외한 부류(보조·증상 완화)다.

  더 나쁜 경우: 그 시험에서 안면홍조가 **개선됐으면** 팩트체커가 support로
  읽을 수 있다. 반증을 찾겠다고 넣은 게이트가 반대 방향으로 오염된다.

  팩트체커 규칙 2번이 "다른 질환에 대한 효능은 무관"이라 막게 되어 있지만,
  그건 LLM 판단이다. **LLM 판단만 믿지 않는 것이 이 프로젝트의 전제다.**

━━━ ② 신규성 — PubMed가 이미 찾은 것 아닌가 ━━━

  등록부 결과가 있어도 **그 시험의 논문이 이미 있으면 B5가 이미 읽었다.**
  B6의 진짜 기여는 "결과는 등록됐는데 논문이 없는" 시험뿐이다.

  PubMed는 NCT 번호를 [si] 필드에 색인한다. 그걸로 직접 센다.
  이 숫자가 B6의 **한계 기여**다. 53%가 아니라 이쪽을 보고해야 정직하다.

실행: py -m bioreroute.bench.regaudit bench_ceiling.csv
"""

import argparse
import csv
import re
import sys

from ..io import cache, sources
from .ctgov import SYMPTOM
from .labels import ADJUNCT

# 이 약을 이 질환에 "쓴다"가 아니라 "곁들인다"는 신호
PREVENT = re.compile(r"prevention of|prophylax|induced|related|secondary to"
                     r"|in patients (receiving|undergoing|treated with)", re.I)


def _norm(s):
    """비교용 정규화 — 공백까지 없앤다.

    처음엔 구두점을 **공백으로** 바꿨다. 그래서 "COVID19"와 "COVID-19"가
    각각 covid19 / covid 19 로 갈라져 **불일치로 판정됐다.**
    실측에서 hydroxychloroquine/COVID 쌍 넷이 전부 이 이유로 오탐이었다.
    """
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _words(s):
    return [w for w in re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split() if w]


# 상품명·동의어를 다 적을 수는 없다. CT.gov가 otherNames 로 주는 것을 쓰되,
#   등록부에 안 적힌 흔한 INN/USAN 차이만 손으로 보탠다.
#   RepoDB는 INN(hydroxycarbamide), 시험은 USAN(hydroxyurea)을 쓴다.
SYNONYM = {
    "hydroxycarbamide": {"hydroxyurea", "hydrea", "droxia", "siklos"},
    "hydroxyurea": {"hydroxycarbamide"},
    "methotrexate": {"mtx", "amethopterin", "trexall", "otrexup"},
    "acetylsalicylic acid": {"aspirin", "asa"},
    "paracetamol": {"acetaminophen", "apap"},
    "salbutamol": {"albuterol"},
    "epinephrine": {"adrenaline"},
    "norepinephrine": {"noradrenaline"},
    "ciclosporin": {"cyclosporine", "cyclosporin"},
    "cyclosporine": {"ciclosporin"},
    "rifampicin": {"rifampin"},
    "glibenclamide": {"glyburide"},
    "furosemide": {"frusemide"},
    "pethidine": {"meperidine"},
    "dipyrone": {"metamizole"},
    "5-fluorouracil": {"fluorouracil", "5fu"},
    "fluorouracil": {"5fu", "5 fluorouracil"},
}


def probe_trial(nct):
    """시험 하나의 개입·질환·제목을 가져온다. 결과는 안 본다(빠르게).

    **otherNames를 반드시 같이 읽는다.** 상품명(Tarceva)이나 개발코드로만
    적힌 시험이 흔하다. 이걸 안 읽어서 erlotinib 시험이 '약물불일치'로
    잘못 걸렸다 — Tarceva가 곧 erlotinib이다.
    """
    key = "AUDIT2::" + nct
    if cache.has(key):
        return cache.get(key)
    out = {"nct": nct, "title": "", "conds": [], "intrs": [], "error": None}
    try:
        d = sources._ctg("%s/%s?format=json" % (sources.CTG, nct))
        p = d.get("protocolSection", {})
        out["title"] = (sources._dig(p, "identificationModule", "briefTitle",
                                     default="") or "")
        out["conds"] = sources._dig(p, "conditionsModule", "conditions",
                                    default=[]) or []
        # 공식 제목에도 약 이름이 자주 들어간다
        out["official"] = (sources._dig(p, "identificationModule",
                                        "officialTitle", default="") or "")
        arms = sources._dig(p, "armsInterventionsModule", "interventions",
                            default=[]) or []
        names = []
        for i in arms:
            if i.get("name"):
                names.append(i["name"])
            names += list(i.get("otherNames") or [])
        out["intrs"] = names
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    return cache.put(key, out)


def has_publication(nct):
    """이 시험의 논문이 PubMed에 있는가. NCT는 [si] 필드에 색인된다."""
    key = "PUBOF::" + nct
    if cache.has(key):
        return cache.get(key)
    r = sources.pubmed_search("%s[si]" % nct, 1)
    out = {"n": None if r.get("error") else (r.get("count") or 0),
           "error": r.get("error")}
    return cache.put(key, out)


STOP = {"malignant", "neoplasm", "disease", "diseases", "disorder", "disorders",
        "chronic", "acute", "primary", "secondary", "syndrome", "type",
        "unspecified", "other", "and", "the", "of"}


PUBCHEM_SYN = ("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/%s"
               "/synonyms/JSON")
USE_PUBCHEM = True


def pubchem_synonyms(drug, limit=120):
    """PubChem 동의어 — 상품명·약어를 자동으로 푼다.

    손으로 만든 표로는 상품명을 못 따라간다. Tarceva=erlotinib,
    MTX=methotrexate 같은 것이 실측에서 '약물불일치'로 잘못 걸렸다.
    브랜드는 수천 개라 표로 적을 수 없다. PubChem이 이미 갖고 있다.

    실패해도 조용히 빈 집합을 준다 — 이건 판정을 **완화**하는 용도이므로
    없으면 '확인필요'로 떨어질 뿐 잘못된 통과가 생기지는 않는다.
    """
    if not USE_PUBCHEM:
        return set()
    key = "PCSYN::" + (drug or "").lower()
    if cache.has(key):
        return set(cache.get(key) or [])
    out = []
    try:
        import urllib.parse
        d = sources._get(PUBCHEM_SYN % urllib.parse.quote(drug))
        info = (d.get("InformationList") or {}).get("Information") or []
        for it in info:
            out += list(it.get("Synonym") or [])
    except Exception:
        out = []
    # 짧은 약어(MTX)도 살려야 하지만 노이즈가 크므로 길이 3 이상만
    out = [s for s in out[:limit] if 3 <= len(s) <= 40]
    cache.put(key, out)
    return set(out)


def drug_terms(drug):
    """이 약을 가리킬 수 있는 문자열들. 표 + 낱말 조각 + PubChem 동의어.

    길이 문턱을 출처에 따라 다르게 둔다.

      · 손으로 적은 SYNONYM 표 → 3글자 허용 (MTX 같은 약어)
      · 그 외(PubChem 자동, 낱말 조각) → 4글자 이상

    이유: 3글자는 우연히 걸릴 위험이 크다. 내가 하나씩 확인한 것만
    그 위험을 감수한다. 자동으로 긁어온 수백 개에는 안 준다 —
    거기에 우연 일치가 하나라도 섞이면 오염을 '적합'으로 통과시킨다.
    **판정을 완화하는 장치일수록 근거의 출처를 따져야 한다.**
    """
    d = (drug or "").lower().strip()
    terms = {t for t in ({_norm(d)} | {_norm(x) for x in SYNONYM.get(d, set())})
             if len(t) >= 3}
    loose = set()
    for w in _words(d):
        if len(w) > 4 and w not in ("acid", "sodium", "hydrochloride"):
            loose.add(_norm(w))
    for s in pubchem_synonyms(d):
        n = _norm(s)
        # 순수 숫자·등록번호(CAS, CHEMBL…)는 제목에 우연히 걸릴 수 있어 뺀다
        if not n.isdigit():
            loose.add(n)
    return terms | {t for t in loose if len(t) >= 4}


def judge(drug, indication, t):
    """이 시험을 근거로 써도 되는가.

    판정은 넷이다 — 적합 / 확인필요 / (오염 부류) / 조회실패.
    **애매한 것을 불일치로 밀면 멀쩡한 근거를 버린다.** 실측에서
    52%가 오염으로 나왔는데 대부분 상품명·동의어·구두점 문제였다.
    확신이 없으면 버리지 말고 사람에게 넘긴다.
    """
    if t.get("error"):
        return "조회실패", t["error"]
    ind_words = [w for w in _words(indication) if len(w) > 3 and w not in STOP]
    hay_drug = _norm(" ".join(t["intrs"] + [t.get("title", ""),
                                            t.get("official", "")]))
    hay_dis = _norm(" ".join(t["conds"] + [t.get("title", ""),
                                           t.get("official", "")]))

    if not any(x in hay_drug for x in drug_terms(drug)):
        # 상품명·개발코드로만 적혔을 수 있다. otherNames까지 봤는데도 없으면
        #   다른 약 시험일 가능성이 높지만, 단정하지 않고 사람에게 넘긴다.
        return "확인필요·약물", "개입: %s" % (", ".join(t["intrs"])[:60] or "(없음)")

    if ind_words and not any(_norm(w) in hay_dis for w in ind_words):
        return "확인필요·질환", "질환: %s" % (", ".join(t["conds"])[:60] or "(없음)")

    # ── 여기부터는 진짜 오염 부류 ────────────────────────────
    head = (drug or "").lower().split()[0] if drug else ""
    if head in ADJUNCT:
        return "보조요법", "약물이 보조·지지요법 목록에 있음"
    m = SYMPTOM.search(t.get("title", "") + " " + " ".join(t["conds"]))
    if m and m.group(0).lower() not in (indication or "").lower():
        return "증상완화", "제목/질환에 '%s'" % m.group(0)
    if PREVENT.search(t.get("title", "")):
        return "예방·병용", t.get("title", "")[:60]
    return "적합", ""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("ceiling", nargs="?", default="bench_ceiling.csv")
    ap.add_argument("--cache", default="pubmed_cache.json")
    ap.add_argument("--out", default="bench_regaudit.csv")
    ap.add_argument("--skip-pub", action="store_true",
                    help="논문 존재 확인을 건너뛴다(빠름)")
    a = ap.parse_args(argv)

    cache.configure(a.cache)
    cache.load()
    rows = [r for r in csv.DictReader(open(a.ceiling, encoding="utf-8-sig"))
            if (r.get("usable_ncts") or "").strip()]
    pairs = [(r, [n for n in r["usable_ncts"].split(";") if n]) for r in rows]
    total = sum(len(n) for _, n in pairs)

    print("=" * 78)
    print("등록부 근거 감사 — 쌍 %d · 독립 시험 %d건" % (len(pairs), total))
    print("=" * 78)
    print("ceiling은 '대조 가능한 결과가 있다'까지만 쟀다.")
    print("정말 그 가설을 시험했는지, 논문이 이미 있는지는 안 봤다.\n")

    recs, i = [], 0
    for r, ncts in pairs:
        for n in ncts:
            i += 1
            t = probe_trial(n)
            verdict, why = judge(r["drug"], r["indication"], t)
            pub = {"n": None, "error": None} if a.skip_pub else has_publication(n)
            recs.append({"drug": r["drug"], "indication": r["indication"],
                         "nct": n, "verdict": verdict, "why": why,
                         "title": t.get("title", ""), "pubs": pub["n"]})
            if i % 20 == 0 or i == total:
                print("  %d/%d" % (i, total))
                cache.save()
    cache.save()

    # ── ① 오염 ──────────────────────────────────────────────
    from collections import Counter
    cnt = Counter(x["verdict"] for x in recs)
    fit = cnt.get("적합", 0)
    DIRTY = ("증상완화", "보조요법", "예방·병용")
    CHECK = ("확인필요·약물", "확인필요·질환")
    print("\n[① 오염 검사] 그 시험이 정말 '약물이 질환을 치료하는가'를 시험했는가")
    for k in ("적합",) + DIRTY + CHECK + ("조회실패",):
        if cnt.get(k):
            print("  %-12s %3d/%d = %2.0f%%" % (k, cnt[k], total, 100 * cnt[k] / total))

    dirty = sum(cnt.get(k, 0) for k in DIRTY)
    ck = sum(cnt.get(k, 0) for k in CHECK)
    if dirty:
        print("\n  [오염 — 근거로 쓰면 안 된다] %d건 (%.0f%%)" % (dirty, 100.0 * dirty / total))
        for x in [y for y in recs if y["verdict"] in DIRTY][:10]:
            print("    %-16s %-22s %-8s %s" % (x["drug"][:16], x["indication"][:22],
                                               x["verdict"], x["why"][:34]))
        print("  '증상완화'는 결과가 **긍정**이라 반증이 아니라 지지로 읽힐 수 있다.")
    if ck:
        print("\n  [확인필요 — 자동 판정 불가] %d건 (%.0f%%)" % (ck, 100.0 * ck / total))
        print("  상품명·동의어·약어 때문일 수 있다. **불일치로 단정하지 않는다.**")
        print("  실측 사례: Tarceva=erlotinib, hydroxycarbamide=hydroxyurea,")
        print("            MTX=methotrexate, COVID19 vs COVID-19(구두점).")
        for x in [y for y in recs if y["verdict"] in CHECK][:10]:
            print("    %-16s %-20s %-12s %s" % (x["drug"][:16], x["indication"][:20],
                                                x["verdict"], x["why"][:30]))
        print("  bench_regaudit.csv 에서 이 행들을 눈으로 확인하라.")

    # 쌍 단위 — 적합한 시험이 하나라도 있는 쌍
    ok_pairs = len({(x["drug"], x["indication"]) for x in recs
                    if x["verdict"] == "적합"})
    print("\n  쌍 기준: 적합한 독립 시험이 1건 이상인 쌍 %d개" % ok_pairs)

    # ── ② 신규성 ────────────────────────────────────────────
    if not a.skip_pub:
        got = [x for x in recs if x["verdict"] == "적합" and x["pubs"] is not None]
        nopub = [x for x in got if x["pubs"] == 0]
        print("\n[② 신규성 검사] PubMed가 이미 찾은 것 아닌가")
        print("  적합 시험 중 조회 성공 %d건" % len(got))
        if got:
            print("  논문 **없음**(등록부에만 존재)  %3d/%d = %.0f%%"
                  % (len(nopub), len(got), 100 * len(nopub) / len(got)))
            print("  논문 있음(B5가 이미 읽을 수 있음) %3d/%d = %.0f%%"
                  % (len(got) - len(nopub), len(got),
                     100 * (len(got) - len(nopub)) / len(got)))
        np_pairs = len({(x["drug"], x["indication"]) for x in nopub})
        print("\n  **B6의 한계 기여는 이 쌍 %d개다.**" % np_pairs)
        print("  나머지는 논문이 있으므로 B5도 원리상 도달할 수 있다.")
        print("  보고할 숫자는 '결과 있음 비율'이 아니라 이쪽이다.")
        print("")
        print("  [이 숫자의 한계 — 반드시 같이 말해야 한다]")
        print("   · PubMed [si] 필드는 논문이 NCT를 **명시했을 때만** 걸린다.")
        print("     저자가 등록번호를 안 적으면 논문이 있어도 '없음'으로 잡힌다.")
        print("     따라서 위 %.0f%% 는 신규성의 **상한**이다."
              % (100 * len(nopub) / max(1, len(got))))
        print("   · 반대 방향 오차는 없다 — '논문 있음'으로 잡힌 건 확실히 있다.")
        print("     즉 '한계 기여 %d쌍'은 낙관적 추정이고, 실제로는 더 적다." % np_pairs)

    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["drug", "indication", "nct", "verdict", "why",
                    "pubmed_papers", "title"])
        for x in recs:
            w.writerow([x["drug"], x["indication"], x["nct"], x["verdict"],
                        x["why"], "" if x["pubs"] is None else x["pubs"],
                        x["title"]])
    print("\n저장: %s" % a.out)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
