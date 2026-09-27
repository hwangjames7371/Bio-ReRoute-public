# -*- coding: utf-8 -*-
"""역발상 발굴 — 부작용을 원하는 효과로 뒤집는다 (제안서 §1.2 · §3.3-5)

  > 역발상은 부작용 데이터베이스(SIDER·FAERS)에서 거꾸로 새 적응증을
  > 찾는 방식이다(미녹시딜·실데나필 형).
  > **역발상은 정방향이 구조적으로 놓치는 후보를 발굴하는 차별점이다.**

두 번째 문장이 **검증 가능한 주장**이다. 정방향과 역발상을 같은 질환에
돌려 후보 집합의 겹침을 재면 된다. 많이 겹치면 차별점이 아니다.
`bench/reverse.py` 가 그걸 잰다.

## 설계에서 가장 중요한 한 가지

**부작용 목록을 LLM에게 물어보지 않는다.**

물어보면 편하다. 그런데 그 순간 역발상은 정방향과 **같은 자료원**(모델
가중치)을 쓰게 되고, "정방향이 놓치는 것을 찾는다"는 주장이 원리적으로
검증 불가능해진다. 두 축이 겹치는 게 당연해진다.

그래서 LLM은 **한 곳에서만** 쓴다 —

```
①  질환 → 그 질환의 치료 효과에 해당하는 MedDRA 부작용 용어   ← LLM (용어 번역만)
②  용어 → 그 부작용을 특이하게 일으키는 약물                  ← FAERS/SIDER (자료)
③  이미 그 질환 승인약이면 제외                              ← 규칙
```

②가 자료다. LLM은 ①에서 *어휘를 옮기는 일*만 한다. 미녹시딜을 찾는 것은
LLM이 아니라 **"탈모 = 다모증(hypertrichosis)의 반대"** 라는 어휘 사상과
FAERS의 신고 분포다.

## 미녹시딜·실데나필이 왜 예시인가

둘 다 **부작용이 적응증이 된** 사례다.

| 약 | 원래 용도 | 부작용 | 새 적응증 |
|---|---|---|---|
| 미녹시딜 | 고혈압 | 다모증 | 탈모 |
| 실데나필 | 협심증 | 발기 | 발기부전 |

정방향 문헌 연결(A–B–C)로는 이런 걸 못 찾는다. **문헌이 그 연결을 아직
안 썼기 때문**이고, 그게 "구조적으로 놓친다"의 뜻이다.
"""

from typing import Any, Dict, List, Optional

from ..io import faers, llm

MARK = "[역발상 · 부작용→적응증]"

SYSTEM = ("당신은 약물감시(pharmacovigilance) 용어 전문가다. "
          "질환의 치료 효과를 부작용 용어로 옮기는 일만 한다. "
          "약물 이름을 제안하지 마라.")

PROMPT = """{mark}

질환: {disease}

이 질환이 **치료되었을 때 나타나는 변화**를, 다른 약에서라면
**부작용으로 신고되었을** MedDRA 용어로 옮겨라.

예시 (원리만 보여주는 것이다 · 이 답을 쓰지 마라)
  탈모        → HYPERTRICHOSIS, HAIR GROWTH ABNORMAL
  발기부전     → PENILE ERECTION, PRIAPISM
  저체중·악액질 → WEIGHT INCREASED, INCREASED APPETITE

규칙
1. **영문 대문자 MedDRA 선호용어(PT)** 형태로 적어라
2. 질환 자체의 이름이 아니라 **효과의 이름**이다.
   (당뇨 → "DIABETES MELLITUS" 는 틀렸다. "BLOOD GLUCOSE DECREASED" 가 맞다)
3. 3~6개. **억지로 채우지 마라.** 마땅한 용어가 없으면 빈 배열을 내라
4. **약물 이름을 쓰지 마라.** 약은 자료에서 찾는다

JSON 배열만 출력하라.
[{{"term": "HYPERTRICHOSIS", "why": "모발 성장 증가"}}]
"""


def effect_terms(disease: str, model: Optional[str] = None) -> Dict[str, Any]:
    """① 질환 → 부작용 용어. **LLM 은 여기까지만 쓴다.**"""
    r = llm.complete(PROMPT.format(mark=MARK, disease=disease),
                     system=SYSTEM, as_json=True,
                     model=model or llm.model_for("reverse_terms"),  # §3.2 소형
                     purpose="reverse_terms")   # 계량
    out = {"ok": False, "disease": disease, "terms": [],
           "error": r.get("error"), "provenance": r.get("provenance")}
    data = r.get("data")
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), None)
    if not r.get("ok") or not isinstance(data, list):
        out["error"] = out["error"] or "배열 형식 아님"
        return out
    seen = set()
    for d in data:
        if not isinstance(d, dict):
            continue
        t = str(d.get("term", "")).strip().upper()
        if not t or t in seen:
            continue
        seen.add(t)
        out["terms"].append({"term": t, "why": str(d.get("why", ""))[:80]})
    out["ok"] = True
    return out


# 명세 `사전명세_역발상_SIDER.md`(`7b906515…`) §1 — **결과 보기 전에 정했다.**
#   FAERS 의 `COUNT_MIN=3`(신고 건수)에 대응하는 SIDER 쪽 문턱이다.
#   이진 자료라 «건수» 가 아니라 **질환 용어를 몇 개 적었나** 로 옮긴다.
SIDER_MIN_TERMS = 2


def propose(disease: str, k: int = 20, model: Optional[str] = None,
            source: str = "faers", rank: str = "raw",
            exclude_approved: Optional[set] = None) -> Dict[str, Any]:
    """질환 → 역발상 후보. 정방향 `discover.propose` 와 같은 서명·같은 반환.

    **자료원이 없으면 후보를 만들지 않는다.** 빈 목록이 아니라 error 를
    채운다 — 자료 없음과 후보 없음은 다르다.
    """
    out = {"ok": False, "disease": disease, "variant": "역발상", "asked": k,
           "items": [], "terms": [], "error": None, "source": source,
           "caveat": faers.CAVEAT, "provenance": None}

    av = faers.available()
    if source == "faers" and not av["faers"]:
        out["error"] = ("FAERS 조회 불가: %s — 역발상은 자료가 자료원이다. "
                        "추정으로 채우지 않는다." % (av.get("error") or "미상"))
        return out
    if source == "sider" and not av["sider"]:
        out["error"] = "SIDER 파일 없음: %s" % av["sider_path"]
        return out

    et = effect_terms(disease, model=model)
    out["provenance"] = et.get("provenance")
    out["terms"] = et["terms"]
    if et.get("error"):
        out["error"] = "부작용 용어 변환 실패: %s" % et["error"]
        return out
    if not et["terms"]:
        # **오류가 아니다.** 마땅한 용어가 없는 질환이 실제로 있다.
        out["ok"] = True
        out["error"] = None
        out["note"] = "치료 효과에 대응하는 부작용 용어가 없다 — 역발상 대상이 아니다"
        return out

    ex = {s.strip().lower() for s in (exclude_approved or set())}
    hits: Dict[str, Dict[str, Any]] = {}
    errs = []
    for t in et["terms"]:
        r = (faers.drugs_for_event(t["term"]) if source == "faers"
             else faers.sider_drugs_for_event(t["term"]))
        if r.get("error"):
            errs.append("%s: %s" % (t["term"], r["error"]))
            continue
        for row in r.get("rows", []):
            if not row.get("signal"):
                continue                       # PRR·건수 문턱 미달
            name = _clean(row["drug"])
            if not name or name.lower() in ex:
                continue
            cur = hits.get(name)
            # ── 자료원마다 **순위 기준이 다르다** (결함 128 · 명세 `7b906515…`)
            #
            #   FAERS  PRR — 자발보고 «건수» 에서 정의된다
            #   SIDER  **공유 용어 수** — 라벨 표기라 건수가 없어 PRR 이
            #          정의되지 않는다. `prr` 은 `None` 으로 온다.
            #
            #   초판은 `row["prr"] > cur["prr"]` 하나로 처리했고, SIDER 를
            #   붙이자 `None > None` 이 됐다. **없는 양에 0 을 넣지 않는다** —
            #   넣으면 아래 문구가 그걸 PRR 로 읽는다.
            if cur is None:
                hits[name] = {"drug": name, "prr": row.get("prr"),
                              "n": row["a"], "terms": {t["term"]},
                              "term": t["term"], "why": t["why"]}
            else:
                cur["terms"].add(t["term"])
                cur["n"] = max(cur["n"], row["a"])
                if row.get("prr") is not None and (
                        cur["prr"] is None or row["prr"] > cur["prr"]):
                    cur.update(prr=row["prr"], term=t["term"], why=t["why"])

    # 조회가 **전부** 실패했으면 판단하지 않는다 (결함 35)
    if errs and not hits and len(errs) == len(et["terms"]):
        out["error"] = "부작용 조회 전건 실패 — 후보 없음이 아니라 조회 실패다: " + " · ".join(errs[:3])
        return out

    if source == "faers":
        rows = sorted(hits.values(), key=lambda r: -(r["prr"] or 0.0))[:k]
    else:
        # 명세 §1 — **주 순위는 원시 공유 용어 수.** 정규화는 부지표다.
        #   질환 용어를 **2개 이상** 적은 약만 후보다(FAERS 의 a≥3 대응).
        cand = [r for r in hits.values() if len(r["terms"]) >= SIDER_MIN_TERMS]
        out["n_before_term_floor"] = len(hits)
        if rank == "raw":
            rows = sorted(cand, key=lambda r: (-len(r["terms"]), r["drug"]))[:k]
        elif rank == "norm":
            # ── 부지표(명세 §1) — **라벨 길이로 나눈다** ──────────────
            #
            #   `|SE(약)|` 로 나누면 «라벨에 부작용을 적게 적은 약» 이
            #   위로 온다. 그게 교란을 빼는 것인지 **신호까지 같이 빼는
            #   것인지**가 예측 ④의 질문이다.
            #
            #   어제 DRKG 에서 차수로 나눴다가 **대조군한테도 졌다**
            #   (결함 118). 같은 방향인지 여기서 확인한다.
            #   **판정에는 안 쓴다.** 그건 원시 순위가 한다.
            sizes = faers.sider_label_sizes()
            names = faers.sider_names()
            cid = {v.lower(): kk for kk, v in (names or {}).items()}

            def _z(r):
                c = cid.get(r["drug"].lower())
                n = sizes.get(c) if c else None
                return len(r["terms"]) / n if n else 0.0

            rows = sorted(cand, key=lambda r: (-_z(r), r["drug"]))[:k]
            out["rank"] = "norm"
        else:
            out["error"] = "알 수 없는 순위 규칙: %s" % rank
            return out

    def _mech(r):
        if r.get("prr") is not None:
            return "부작용 역전 (FAERS PRR %.1f · 신고 %d건)" % (r["prr"], r["n"])
        return ("부작용 역전 (SIDER 라벨 — 질환 용어 %d개 표기). "
                "**PRR 아님**: 라벨 자료라 건수 분모가 없다" % len(r["terms"]))

    out["items"] = [{
        "drug": r["drug"],
        "mechanism": _mech(r),
        "rationale": "%s 를 부작용으로 %s — %s"
                     % (r["term"], "신고" if r.get("prr") is not None else "라벨에 표기",
                        r["why"]),
        "evidence_level": "pharmacovigilance" if r.get("prr") is not None else "label",
        "confidence": "low",          # **자발보고·라벨이다.** 높게 쓰지 않는다
        "prr": r.get("prr"), "n_terms": len(r["terms"]), "term": r["term"],
    } for r in rows]
    out["ok"] = True
    if errs:
        out["partial_error"] = errs
    return out


def _clean(name: str) -> str:
    """FAERS 제품명 정리. 상품명·용량·제형이 붙어 온다.

    `LIPITOR (ATORVASTATIN CALCIUM)` · `ASPIRIN 81MG` 같은 형태다.
    괄호 안이 성분명인 경우가 많아 그쪽을 쓴다.
    """
    s = (name or "").strip()
    if "(" in s and ")" in s:
        inner = s[s.find("(") + 1:s.rfind(")")].strip()
        if len(inner) >= 4:
            s = inner
    s = s.split(",")[0].strip()
    for suf in (" TABLET", " CAPSULE", " INJECTION", " SODIUM", " HCL",
                " HYDROCHLORIDE", " CALCIUM", " SULFATE"):
        if s.upper().endswith(suf):
            s = s[: -len(suf)].strip()
    import re
    s = re.sub(r"\s*\d+\s*(MG|MCG|G|ML|IU)\b.*$", "", s, flags=re.I).strip()
    return s.title() if s.isupper() else s
