# -*- coding: utf-8 -*-
"""S3 도킹 **데모 1건** — 실현 가능성부터 잰다 (제안서 §2.4·§2.5)

## 왜 이 파일이 «확인 도구» 인가

결함 170에서 배웠다 — **자료를 안 열고 수를 적으면 봉인이 30분 만에
깨진다.** 그래서 도킹은 **명세를 쓰기 전에 사슬이 실제로 도는지**부터
잰다. 이 파일은 **아무것도 도킹하지 않는다.** 부품이 있는지만 본다.

## 제안서가 요구한 것

    게이트 표  S3 도킹(직접결합만) · 포켓에 실제로 안착하나 · QuickVina2/smina
    §2.4      직접결합·병원체(RdRp) → 구조 게이트 → **도킹(S1–S3)** → **타당(핵심 검증)**
    §2.5      S3 는 **포켓 내 포즈를 실제 생성한 뒤에만** 입체 상보성을 산출한다
              무거운 시뮬레이션은 **데모 1건으로 제한한다**

**«1건»이 요점이다.** 많이 하면 *"잘못 적용된 3차원 계산이 거짓 확신의
원천"*(§2.5)이 되고, 안 하면 §2.4 표의 첫 줄을 **말로만** 하게 된다.

## 사슬 — 어디가 끊기는지 본다

    ① 수용체   UniProt → AlphaFold PDB          ← `io/structure.py` 가 **이미 한다**
    ② 포켓     활성부위 잔기 → 박스 중심·크기    ← `site_positions` 가 **이미 한다**
    ③ 리간드   SMILES → 3D 좌표 → PDBQT          ← **RDKit + 변환기**
    ④ 도킹     Vina/smina 실행 → 포즈            ← **바이너리 또는 파이썬 바인딩**
    ⑤ 판정     «명백한 입체 충돌» 만 본다         ← 결합력 예측을 **안 한다**

**①②는 있다.** 확인해야 하는 것은 **③④** 다.

## ⚠ 이 도구가 통과해도 «할 수 있다» 가 아니다

부품이 있는 것과 **1건이 실제로 도는 것**은 다르다. 통과하면
**명세를 쓰고 그 다음에 1건을 돌린다.** 순서를 지킨다.
"""

import argparse
import importlib
import json
import shutil
from typing import Any, Dict, List

# 후보 도구 — 하나라도 되면 ④가 열린다.
#   `vina` 는 AutoDock Vina 의 파이썬 바인딩(권장). 없으면 실행 파일을 찾는다.
PY_MODULES = ("rdkit", "vina", "meeko", "openbabel")
BINARIES = ("vina", "smina", "qvina2", "qvina02", "obabel")

# 데모 후보 — 제안서 §2.4 표의 **첫 줄**(직접결합·병원체 표적)이어야 한다.
#   RdRp 억제제가 그 예시다. 숙주 표적(바리시티닙)은 §2.4 가 «무의미» 라 적었다.
DEMO = {"drug": "remdesivir", "disease": "COVID-19",
        "target": "SARS-CoV-2 RdRp (nsp12)",
        "왜": "제안서 §2.4 표 첫 줄 — 직접결합 · **병원체 표적** · «타당(핵심 검증)»"}


def probe() -> Dict[str, Any]:
    """부품 재고. **아무것도 실행하지 않는다.**"""
    mods: Dict[str, Any] = {}
    for m in PY_MODULES:
        try:
            mod = importlib.import_module(m)
            mods[m] = getattr(mod, "__version__", "있음")
        except Exception as e:
            mods[m] = "❌ %s" % type(e).__name__
    bins = {b: (shutil.which(b) or "❌ 없다") for b in BINARIES}

    # ①② 는 우리 코드다 — 이름이 실재하는지만 본다(호출은 안 한다)
    ours = {}
    try:
        from ..io import structure
        # **이름을 실측으로 확인했다.** 08-13에 `plddt_for`·`fetch` 라고
        # 적었다가 «❌ 없다» 를 스스로 냈다 — **가드가 자기 오탐을 내면
        # 사람이 진짜 결핍과 못 가른다.**
        for fn in ("site_positions", "plddt", "resolve", "assess", "site_stats"):
            ours[fn] = "있다" if hasattr(structure, fn) else "❌ 없다"
    except Exception as e:
        ours["structure"] = "❌ %s" % e

    ok3 = mods.get("rdkit", "").startswith("❌") is False
    ok4 = (not str(mods.get("vina", "")).startswith("❌")) or \
          any(not v.startswith("❌") for k, v in bins.items() if k != "obabel")
    return {"python_modules": mods, "binaries": bins, "ours": ours,
            "③_리간드_가능": ok3, "④_도킹_가능": ok4,
            "판정": ("**사슬이 열린다** — 명세를 쓰고 1건을 돌린다"
                    if (ok3 and ok4) else
                    "**끊긴다** — 아래 «막힌 곳» 을 보고 접거나 설치한다")}


def live(target: str = None, drug: str = None) -> Dict[str, Any]:
    """**실제로 조회해 본다** — `--help` 통과는 검증이 아니다(`CLAUDE.md §5`).

    ## 왜 이게 따로 필요한가

    `probe()` 는 **함수 이름이 있는지**만 본다. 08-13에 그걸로 «①② 는
    있다» 라고 적었는데 — **이름이 있는 것과 그 표적에 대해 값이 나오는
    것은 다르다.** 특히 이 데모 후보에는 **알려진 함정 둘**이 있다.

      ① **RdRp 는 폴리단백질(pp1ab)의 일부다.** AlphaFold 모델이 전체
         폴리단백질이면 잔기 번호가 어긋난다 — 08-11 에 3CLpro 가
         `신뢰도미상(단편)` 으로 나온 그 문제다(결함 90 → 98)

      ② **활성부위 주석이 없으면 포켓을 못 잡는다.** `sites` 가 비면
         박스 중심을 못 정하고, 그러면 **blind docking** 이 된다.
         그건 §2.5 가 말한 *«포켓 내 포즈»* 가 아니다 — **접어야 한다**

    **실패하면 왜 실패했는지를 가른다** — 조회 실패(네트워크)와
    «주석이 없다」는 다르다(결함 37 과 같은 구분).
    """
    from ..io import structure, sources
    t = target or DEMO["target"]
    d = drug or DEMO["drug"]
    out: Dict[str, Any] = {"target": t, "drug": d}

    r = structure.resolve(t)
    out["resolve"] = {"accession": r.get("accession"), "name": r.get("name"),
                      "seq_len": r.get("seq_len"),
                      "n_sites": len(r.get("sites") or []),
                      "sites": (r.get("sites") or [])[:12],
                      "error": r.get("error")}
    if r.get("error"):
        out["막힌곳"] = "① 표적 조회 — **네트워크/조회 실패**"
        return out
    if not r.get("accession"):
        out["막힌곳"] = "① 표적 조회 — UniProt 에 그 이름이 없다"
        return out
    # ── ⚠ 08-13 밤 정정 (결함 176) ────────────────────────────────
    #
    #   앞판은 **`localize` 를 건너뛰고** 폴리단백질 전체의 주석을 그대로
    #   `plddt` 에 넣었다. 그래서 화면이 이렇게 찍혔다 —
    #
    #     "서열 길이 7096 · **활성부위 잔기 113개**"
    #
    #   **그 113개는 RdRp 것이 아니다.** pp1ab 전체(nsp3·nsp5·…)의 주석이다.
    #   *"특정 사슬의 활성부위"* 라고 부른 것 — **결함 90 그 자체**이고,
    #   `structure.localize` 는 바로 그걸 막으라고 있는 함수다.
    #   `assess` 는 쓰는데 **이 도구만 안 썼다.**
    #
    #   그 결과 «막힌 곳」 진단도 틀렸다. ②라고 적었지만 **①에서 이미
    #   막혀 있었다.** 아래에서 순서를 바로잡는다.
    loc = structure.localize(t, r.get("chains") or [], r.get("seq_len"))
    out["localize"] = {"kind": loc["kind"], "why": loc["why"],
                       "chain": (loc.get("chain") or {}).get("name")}
    if loc["kind"] == "모호":
        out["막힌곳"] = ("① 사슬 — " + loc["why"] + ". **폴리단백질 전체 주석 "
                      "%d개를 이 표적의 활성부위라고 부르면 결함 90 이다.** "
                      "`--apo` 가 사슬 이름 후보를 찍어 준다"
                      % len(r.get("sites") or []))
        return out

    c0 = loc.get("chain")
    want = (c0["start"], c0["end"]) if c0 else None
    sites = r.get("sites") or []
    if c0:
        sites = [x for x in sites if c0["start"] <= x <= c0["end"]]
    out["resolve"]["n_sites_chain"] = len(sites)
    if not sites:
        # **여기서 멈추는 것이 정답이다.**
        out["막힌곳"] = ("② 포켓 — **이 사슬의 활성부위 주석이 0개**. 박스 중심을 "
                      "못 정한다. blind docking 은 §2.5 의 «포켓 내 포즈» 가 "
                      "아니므로 **접는다**")
        return out

    p = structure.plddt(r["accession"], sites, want)
    out["plddt"] = {k: p.get(k) for k in
                    ("mean", "min", "frac_low", "site_mean", "site_min", "error")}
    if p.get("error"):
        out["막힌곳"] = "② 구조 — AlphaFold 조회 실패: %s" % p["error"]
        return out

    a_ = structure.assess(t)
    out["s1_label"] = a_.get("label") or a_.get("판정")

    # ── ⚠ 08-13 저녁 정정 (결함 174) ─────────────────────────────
    #
    #   첫판은 `s1_label not in (None, "구조없음", "오류")` 만 봤다.
    #   **`신뢰도미상` 을 통과시켰다.** 실측에서 정확히 그게 나왔다 —
    #
    #       P0DTD1 (7,096 aa 폴리단백질) · 활성부위 113개
    #       **활성부위 평균 None · 최소 None** · S1 `신뢰도미상`
    #
    #   활성부위 통계가 `None` 이면 **AlphaFold 단편이 그 잔기를 안 덮는
    #   것**이고(결함 90→98), 그러면 **박스 중심을 못 정한다.**
    #   §2.5 가 *«잘못 적용된 3차원 계산은 거짓 확신의 원천»* 이라 한 자리다.
    #
    #   **도구가 함정을 예고해 놓고 판정에서 안 걸렀다.**
    if out["s1_label"] in ("구조없음", "오류", None):
        out["막힌곳"] = "② 구조 — S1 라벨이 %r 이다" % out["s1_label"]
        return out
    if p.get("site_mean") is None:
        n_pdb = structure.pdb_count(r["accession"])
        out["pdb_count"] = n_pdb
        out["막힌곳"] = (
            "② 포켓 — **활성부위 pLDDT 를 못 읽었다**(site_mean=None). "
            "AlphaFold 단편이 그 잔기를 안 덮는다 — 결함 90→98 재현. "
            "**박스 중심을 못 정하므로 이 표적으로는 접는다.** "
            + ("**다만 실험 구조가 %s건 있다**(결함 94) — 예측 구조 대신 "
               "PDB 를 쓰는 경로는 열려 있다" % n_pdb if n_pdb else
               "실험 구조도 못 셌다"))
        return out
    if out["s1_label"] == "신뢰도미상":
        out["막힌곳"] = "② 구조 — S1 이 `신뢰도미상` 이다. **구조를 못 믿으면 도킹은 거짓 확신**"
        return out

    # ③ 리간드 — SMILES 가 실제로 오나
    # **함수 이름을 실측으로 확인했다** — `pubchem_smiles` 라고 짐작해 적었다가
    #   `hasattr` 가드에 걸려 조용히 «없다» 가 될 뻔했다. 실제 이름은
    #   `sources.fetch_smiles` 다. **가드가 내 오타를 덮으면 안 된다.**
    try:
        sm = sources.fetch_smiles(d)
    except Exception as e:
        sm = {"error": "%s: %s" % (type(e).__name__, e)}
    out["smiles"] = sm if isinstance(sm, dict) else {"smiles": sm}
    if isinstance(sm, dict) and sm.get("error"):
        out["막힌곳"] = "③ 리간드 — SMILES 조회 실패: %s" % sm["error"]
        return out

    out["막힌곳"] = None
    out["판정"] = ("**①②③ 가 실제로 나온다** — S1 `%s` · 활성부위 pLDDT %s. "
                 "이제 명세를 쓰고 1건을 돌린다"
                 % (out["s1_label"], p.get("site_mean")))
    return out

# ══════════════════════════════════════════════════════════════════════
#  apo 고르기 — **결함 175. 도킹의 진짜 함정은 구조가 아니라 「답안지」다**
# ══════════════════════════════════════════════════════════════════════
#
#   AlphaFold 로 막히면(결함 174) 다음 수는 «실험 구조를 쓰자» 다.
#   그런데 **SARS-CoV-2 RdRp 의 대표 구조 상당수가 remdesivir 가 이미
#   결합한 상태**다. 거기에 remdesivir 를 도킹하면 잘 맞는 게 당연하다 —
#   포켓이 **이미 그 리간드 모양으로 열려 있기 때문**이다.
#
#   이건 우리 벤치마크가 막는 누출과 **정확히 같은 문제**다.
#   라벨 출처 논문을 근거로 쓰면 «예측이 아니라 답안지 읽기» 라고
#   우리가 적었다(`set_exclude`). **구조에서도 같은 일이 일어난다.**
#
#   ## 왜 «remdesivir 계열만 배제» 가 아니라 «리간드 있으면 전부 배제» 인가
#
#   remdesivir 와 그 삼인산은 **InChIKey 첫 블록이 다르다**(연결이 바뀐다).
#   즉 화합물 동일성으로 거르면 **답안지에 가장 가까운 형태를 놓친다.**
#   그래서 동일성이 아니라 **존재**로 거른다 — 기본이 배제다.

# 이온·용매·결정화 첨가물. **이 목록은 방어가 아니라 회복이다**(결함 163).
# 방어는 아래 `is_apo` 의 구조다 — 통과하려면 **전부** 여기 있어야 한다.
BENIGN = frozenset("""ZN MG MN CA NA K CL BR IOD CD CS RB SR NI CU FE
SO4 PO4 NO3 CO3 ACT ACY FMT CIT TRS EPE MES BTB
GOL EDO PEG PGE PG4 P6G 1PE DMS MPD IPA BME DTT TCE
HOH DOD UNX UNL UNK""".split())

COVER_MIN = 0.5          # 표적 사슬을 이만큼은 덮어야 후보로 센다


def parse_chain_ranges(s):
    """UniProt PDB 교차참조의 `Chains` 문자열 → `[(lo, hi), …]`.

    예 — `"A/B=4393-5324"` · `"A=1-100, B=200-300"` · `"A=1-306"`
    **네트워크를 안 탄다.** 시험 [104]가 여기를 직접 태운다.
    """
    out = []
    for seg in (s or "").split(","):
        if "=" not in seg:
            continue
        rng = seg.split("=", 1)[1].strip()
        if "-" not in rng:
            continue
        a, _, b = rng.partition("-")
        try:
            out.append((int(a), int(b)))
        except ValueError:            # `?-?` 가 실제로 온다. **버린다**
            continue
    return out


def covered(ranges, lo, hi):
    """`[(lo,hi)]` 가 구간 `[lo,hi]` 중 **몇 잔기를 덮나.** 겹침은 한 번만 센다."""
    if not ranges or hi < lo:
        return 0
    seen = set()
    for a, b in ranges:
        seen |= set(range(max(a, lo), min(b, hi) + 1))
    return len(seen)


def is_apo(bound, na=None, n_nonpoly=None):
    """구조 하나 -> `(apo 인가, 걸린 이유)`.

    **기본은 배제다.** `bound` 가 `None`(조회 실패)이면 **apo 가 아니다** —
    못 센 것과 없는 것을 가르는 규칙(결함 35·89)을 여기도 적용한다.

    막는 것 셋 —

      1. **결합 리간드** 중 이온·용매가 아닌 것이 있으면 배제
      2. **핵산 사슬**이 있으면 배제 — remdesivir 는 RNA 안으로 들어간다
         (결함 178). 비중합체 목록만 보면 **답안지가 apo 로 통과한다**
      3. 비중합체 개체가 **있다는데 결합 목록이 비면** 미확인 -> 배제
    """
    if bound is None:
        return False, ["조회실패"]
    bad = sorted({str(c).upper() for c in bound} - BENIGN)
    if na is True:
        bad = ["핵산사슬"] + bad
    elif na is None and n_nonpoly is not None:
        bad = ["핵산미확인"] + bad
    # **결합으로 설명이 안 되는 비중합체가 남으면 미확인이다.**
    # `ZN` 하나가 결합으로 잡혔고 비중합체가 1개면 그건 설명된 것이다.
    if not bad and n_nonpoly and n_nonpoly > len(set(bound)):
        bad = ["비중합체%d개 중 %d개가 설명 안 됨" % (n_nonpoly,
                                                n_nonpoly - len(set(bound)))]
    return (not bad), bad


def rank(cands):
    """후보 정렬 — **apo 먼저, 그 다음 해상도, 그 다음 덮는 범위.**"""
    return sorted(cands, key=lambda c: (not c["apo"],
                                        c.get("resolution") or 99.0,
                                        -c.get("covered", 0)))

RCSB_ENTRY = "https://data.rcsb.org/rest/v1/core/entry/%s"
UNIPROT_JSON = "https://rest.uniprot.org/uniprotkb/%s.json"


RCSB_NONPOLY = "https://data.rcsb.org/rest/v1/core/nonpolymer_entity/%s/%s"


def parse_nonpoly_ids(doc):
    """항목 JSON → **비중합체 엔티티 번호 목록.** 모르면 `None`.

    ## 왜 요약 필드를 안 믿나 — 결함 187

    `nonpolymer_bound_components` 는 **대부분 비어 있다.** 그런데
    `nonpolymer_entity_count` 는 채워져 있다 — 즉 «리간드가 몇 개 있다»
    는 아는데 «무엇인지» 를 그 필드가 안 알려 준다.

    그래서 **엔티티를 직접 센다.** 요약을 믿는 대신 원장을 편다.
    """
    if not isinstance(doc, dict):
        return None
    ids = (doc.get("rcsb_entry_container_identifiers") or {}).get("non_polymer_entity_ids")
    if isinstance(ids, list):
        return [str(x) for x in ids]
    return None


def parse_nonpoly_comp(doc):
    """비중합체 엔티티 JSON → 화학성분 코드. 모르면 `None`."""
    if not isinstance(doc, dict):
        return None
    v = (doc.get("pdbx_entity_nonpoly") or {}).get("comp_id")
    return str(v).strip().upper() if v else None


def _ligands_via_entities(pdb_id, entry_doc):
    """요약이 비었을 때 **엔티티를 하나씩 펴서** 리간드를 센다.

    돌려주는 것 — 성분 코드 목록. **하나라도 못 읽으면 `None`** 이다
    (부분 목록은 «리간드가 적다» 로 읽혀 apo 쪽으로 샌다).
    """
    from ..io import structure as S
    ids = parse_nonpoly_ids(entry_doc)
    if ids is None:
        return None
    if not ids:
        return []
    out = []
    for eid in ids:
        key = "NPE::%s::%s" % (pdb_id, eid)
        if S.cache.has(key):
            c = S.cache.get(key)
        else:
            try:
                c = parse_nonpoly_comp(_json(RCSB_NONPOLY % (pdb_id, eid)))
            except Exception:
                return None
            if c is None:
                return None
            S.cache.put(key, c)
        out.append(c)
    return out


def parse_polymer(doc):
    """RCSB 항목 JSON → **핵산 사슬이 들어 있나.** 모르면 `None`.

    ## 왜 이게 필요한가 — **remdesivir 는 RNA 안으로 들어간다** (결함 178)

    remdesivir 삼인산은 중합효소가 **자라는 RNA 가닥에 붙여 넣는** 사슬종결
    뉴클레오티드 유사체다. 그래서 `7BV2` 같은 구조에서 그것은 **비중합체
    리간드가 아니라 RNA 프라이머의 3' 말단, 즉 중합체 사슬의 일부**다.

    > **`nonpolymer_bound_components` 만 보면 답안지가 apo 로 통과한다.**

    둘째 이유도 있다. RNA 가 붙어 있으면 **뉴클레오티드 자리를 그 RNA 가
    이미 차지**한다. 도킹 상자를 거기에 놓으면 겹친다.

    **비용도 적는다** — RNA 를 뺀 구조는 활성부위가 덜 정돈돼 있을 수 있다.
    그건 **답안지를 안 보는 값**이고, 우리는 그 값을 치르기로 한다.
    """
    if not isinstance(doc, dict):
        return None
    info = doc.get("rcsb_entry_info")
    if not isinstance(info, dict):
        return None
    n = info.get("polymer_entity_count_nucleic_acid")
    if isinstance(n, int):
        return n > 0
    comp = info.get("polymer_composition")
    if isinstance(comp, str):
        # RCSB 표기 — `protein/NA` · `nucleic acid (only)` · `DNA/RNA` ·
        # `NA-hybrid`. **`protein/NA` 에는 «rna» 도 «dna» 도 없다** —
        # 첫판이 여기서 `False` 를 냈다. 시험 [107]이 표기 전집을 태운다.
        c = comp.lower()
        return (("nucleic" in c) or ("dna" in c) or ("rna" in c)
                or ("/na" in c) or c.startswith("na"))
    return None


def parse_bound(doc):
    """RCSB 항목 JSON → 결합 리간드 목록. **모양이 다르면 `None`.**

    ## 여기가 이 도구에서 가장 위험한 줄이다

    응답 모양을 잘못 짚으면 `[]` 가 나오고, `[]` 는 **«apo 다»** 로 읽힌다.
    즉 **오류가 「전부 통과」 방향으로 샌다.** 오늘 두 번 당한 실수다
    (`structure.plddt_for`·`sources.pubchem_smiles` 를 이름만 보고 짚었다).

    그래서 **키가 있는지를 먼저 본다.** `rcsb_entry_info` 가 없으면
    빈 목록이 아니라 `None` 을 돌려주고, `is_apo(None)` 이 **거절**한다.
    """
    if not isinstance(doc, dict):
        return None
    info = doc.get("rcsb_entry_info")
    if not isinstance(info, dict):
        return None                      # **모양이 다르다.** [] 가 아니다
    K = "nonpolymer_bound_components"
    if K not in info:
        # 리간드가 없는 항목에는 이 키가 아예 없을 수 있다. 그 경우와
        # «모양이 틀렸다» 를 가르는 근거 — **다른 필수 키가 있는가.**
        if "polymer_entity_count" not in info and "deposited_atom_count" not in info:
            return None
        return []
    v = info.get(K)
    return [] if v is None else [str(x) for x in v]


def parse_xrefs(doc):
    """UniProt 항목 JSON → PDB 교차참조. 모양이 다르면 **빈 목록**.

    이쪽은 비면 «덮는 구조 0건» 으로 막히므로 **안전한 방향**이다.
    """
    if not isinstance(doc, dict):
        return []
    out = []
    for x in doc.get("uniProtKBCrossReferences") or []:
        if x.get("database") != "PDB":
            continue
        p = {q.get("key"): q.get("value") for q in (x.get("properties") or [])}
        res = None
        for tok in str(p.get("Resolution") or "").split():
            try:
                res = float(tok); break
            except ValueError:
                pass
        out.append({"id": x.get("id"), "method": p.get("Method"),
                    "resolution": res, "chains": p.get("Chains") or ""})
    return out


def _pdb_xrefs(acc):
    """UniProt 항목 → PDB 교차참조 `[{id, method, resolution, chains}]`.

    `structure.pdb_count` 는 **개수만** 센다(그쪽 독스트링이 «어느 사슬을
    덮는지는 안 본다» 고 못 박아 뒀다). 여기서는 **사슬 구간이 필요**하다.
    """
    import json as _j, urllib.request as _u
    from ..io import structure as S
    req = _u.Request(UNIPROT_JSON % acc, headers={"User-Agent": S.UA})
    with _u.urlopen(req, timeout=S.TIMEOUT, context=S._ctx) as r:
        d = _j.loads(r.read().decode("utf-8"))
    return parse_xrefs(d)


def _bound(pdb_id):
    """PDB 항목 → **결합 리간드 목록.** 실패하면 `None`(빈 목록이 아니다)."""
    import json as _j, urllib.request as _u
    from ..io import structure as S
    # **키를 올린다.** v1 은 리간드 목록만 담았고 v2 는 핵산까지 담는다.
    # 안 올리면 옛 항목이 «모양이 다르다» 로 읽혀 전부 거절된다(결함 178).
    # v3 — v2 는 요약 필드만 믿던 판이라 **리간드를 놓친 값이 들어 있다**
    # (결함 187). 키를 안 올리면 옛 「없음」이 그대로 살아난다
    key = "RCSBLIG3::" + pdb_id
    if S.cache.has(key):
        return S.cache.get(key)
    try:
        req = _u.Request(RCSB_ENTRY % pdb_id, headers={"User-Agent": S.UA})
        with _u.urlopen(req, timeout=S.TIMEOUT, context=S._ctx) as r:
            d = _j.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    # ── **원장이 먼저다** (결함 188) ──────────────────────────────
    #
    #   첫 고침은 «요약이 **비면** 원장을 편다» 였다. **그것도 틀렸다.**
    #   08-13 실측 —
    #
    #     4MBS  요약 ["ZN"]        원장 ["MRV","ZN","OLC"]   ← maraviroc
    #     5UHC  요약 ["MG","ZN"]   원장 ["RFP","ZN","MG"]    ← rifampin
    #
    #   요약은 **비어 있는 게 아니라 이온만 싣는다.** 즉 «비었을 때만»
    #   이라는 조건이 **약물이 든 항목을 정확히 비켜 간다.**
    #   부분적으로 맞는 자료원은 **비어 있는 자료원보다 위험하다** —
    #   빈 것은 눈에 띄지만 부분적인 것은 «값이 있네» 로 통과한다.
    #
    #   그래서 **항상 원장을 편다.** 요약은 원장을 못 읽었을 때만 쓴다.
    b = _ligands_via_entities(pdb_id, d)
    if b is None:
        b = parse_bound(d)
        if b is not None:
            b = list(b) + ["원장미확인"]   # **요약만으로는 apo 라 못 한다**
    # `nonpolymer_entity_count` 가 있는데 **결합 목록이 비면 미확인**이다.
    # 결정화 첨가물일 수도 있지만 **모르면 배제**가 이 도구의 규칙이다.
    ne = (d.get("rcsb_entry_info") or {}).get("nonpolymer_entity_count") \
        if isinstance(d, dict) else None
    v = {"lig": b, "na": parse_polymer(d), "n_nonpoly": ne}
    return v if b is None else S.cache.put(key, v)


def apo_scan(target=None, organism=None, max_fetch=120, drug=None):
    """표적 → **답안지가 아닌 실험 구조**를 고른다. 결함 175.

    돌려주는 것 — `{chain, n_xref, n_cover, n_checked, cands, best, 막힌곳}`
    """
    from ..io import structure as S
    target = target or DEMO["target"]
    # **기본값을 없앴다** (결함 184). 앞판은 `organism="SARS-CoV-2"` 가
    # 기본이라, HCV·HSV·결핵균 표적까지 **조용히 P0DTD1 로 해석**했다.
    # 넷이 전부 «덮음 75 · apo 4» 로 **같은 수**를 뱉은 것이 그 증거다.
    if organism is None and target == DEMO["target"]:
        organism = "SARS-CoV-2"
    o = {"target": target, "drug": drug, "막힌곳": None, "cands": [], "best": None}
    r = S.resolve(target, organism)
    if r.get("error"):
        o["막힌곳"] = "① UniProt — " + r["error"]
        return o
    o["accession"] = acc = r["accession"]
    loc = S.localize(target, r.get("chains") or [], r.get("seq_len"))
    o["mature"] = [c for c in (r.get("chains") or [])
                   if not (r.get("seq_len")
                           and c["end"] - c["start"] + 1 >= r["seq_len"])]
    if loc["kind"] == "모호":
        # **전체로 되돌리지 않는다.** 되돌리면 결함 90 재현이다.
        #
        #   다만 **막고 끝내면 사람이 한 번 더 물어야 한다.** 그래서 후보를
        #   같이 찍는다 — 막는 것과 알려 주는 것은 다른 일이다(결함 176).
        o["막힌곳"] = ("① 사슬 — " + loc["why"]
                     + ". **아래 이름 중 하나를 `--target` 으로 다시 줘라**")
        return o
    c = loc.get("chain")
    lo, hi = (c["start"], c["end"]) if c else (1, r.get("seq_len") or 0)
    o["chain"] = {"name": (c or {}).get("name", target), "start": lo, "end": hi}

    xr = _pdb_xrefs(acc)
    o["n_xref"] = len(xr)
    need = int((hi - lo + 1) * COVER_MIN)
    cov = []
    for x in xr:
        n = covered(parse_chain_ranges(x["chains"]), lo, hi)
        if n >= need:
            x["covered"] = n
            cov.append(x)
    o["n_cover"] = len(cov)
    if not cov:
        o["막힌곳"] = ("② 범위 — 이 사슬(%d–%d)의 %d%% 이상을 덮는 실험 구조가 "
                     "**0건**이다. 교차참조 %d건은 **다른 성숙 사슬 것**이다 "
                     "(결함 90 이 경고한 바로 그 착시)" % (lo, hi, COVER_MIN*100, len(xr)))
        return o

    # 해상도 좋은 것부터 리간드를 조회한다. **자른 지점을 숨기지 않는다**
    cov.sort(key=lambda x: (x.get("resolution") or 99.0, -x["covered"]))
    o["n_checked"] = min(len(cov), max_fetch)
    for x in cov[:max_fetch]:
        v = _bound(x["id"])
        v = v if isinstance(v, dict) else {"lig": None, "na": None, "n_nonpoly": None}
        ok, bad = is_apo(v.get("lig"), v.get("na"), v.get("n_nonpoly"))
        x["apo"], x["ligands"], x["na"] = ok, bad, v.get("na")
        x["bound"] = v.get("lig")          # **원본 목록** — 종 대조가 쓴다
        o["cands"].append(x)
    o["cands"] = rank(o["cands"])
    o["n_na"] = sum(1 for x in o["cands"] if x.get("na") is True)
    apo = [x for x in o["cands"] if x["apo"]]
    o["n_apo"] = len(apo)
    if not apo:
        o["막힌곳"] = ("③ apo 없음 — 덮는 구조 %d건 중 **리간드가 안 붙은 것이 "
                     "0건**이다. 이 표적에서는 «답안지 아닌 구조»를 못 구한다 "
                     "→ **결합력 예측이라 부르면 안 된다**(결함 175 선택지 ③으로 간다)"
                     % o["n_checked"])
        return o
    o["best"] = apo[0]
    return o

# ══════════════════════════════════════════════════════════════════════
#  종(種) 대조 — **우리가 도킹하려는 분자가 그 자리에 오는 분자인가**
# ══════════════════════════════════════════════════════════════════════
#
#   remdesivir 는 **전구약물**이다. 세포 안에서 삼인산(RDV-TP)으로 바뀐 뒤
#   중합효소가 그것을 RNA 에 넣는다. 실험 구조 `7BV2` 에 실제로 들어 있는
#   것은 `F86`(remdesivir 일인산) + `POP`(피로인산) — **모분자가 아니다.**
#
#   그런데 우리 파이프라인은 **약물 이름으로 PubChem 에서 SMILES 를 받는다.**
#   즉 도킹하는 것은 **모분자**다. 그 점수는 그럴듯하지만 **다른 분자의
#   점수**다 — 이 프로젝트가 잡겠다고 한 바로 그 종류의 오류다.
#
#   ## 왜 ChEMBL 의 `prodrug` 플래그가 아니라 이 방법인가
#
#   자료원을 하나 더 붙이지 않고 **이미 받은 것으로** 답이 나온다.
#   그리고 더 구체적이다 — *«이 약은 전구약물이다»* 가 아니라
#   **«이 표적의 실험 구조에 붙어 있는 것은 F86 이고 우리 것은 다르다»**.
#
#   앞에서 «동일성으로 거르면 안 된다»(§3)고 적은 것과 모순이 아니다.
#   **거르는 데 쓰면 안 되고, 어긋남을 알리는 데는 맞다.**

RCSB_COMP = "https://data.rcsb.org/rest/v1/core/chemcomp/%s"


def parse_comp(doc):
    """RCSB 화학성분 JSON → `{id, name, formula, inchikey}`. 모양이 다르면 `None`."""
    if not isinstance(doc, dict):
        return None
    cc = doc.get("chem_comp")
    if not isinstance(cc, dict):
        return None
    d = doc.get("rcsb_chem_comp_descriptor") or {}
    ik = (d.get("InChIKey") or "").strip().upper() or None
    return {"id": cc.get("id"), "name": cc.get("name"),
            "formula": cc.get("formula"), "inchikey": ik}


def skeleton(ik):
    """InChIKey → **연결 블록**(앞 14자). 없으면 `None`.

    입체·전하만 다른 것은 같게, **연결이 다르면 다르게** 본다.
    인산이 붙으면 연결이 바뀌므로 **모분자와 일인산은 다르게 나온다** —
    그게 여기서 우리가 알고 싶은 것이다.
    """
    ik = (ik or "").strip().upper()
    return ik[:14] if len(ik) >= 14 else None


def _comp(cid):
    import json as _j, urllib.request as _u
    from ..io import structure as S
    key = "RCSBCOMP::" + cid
    if S.cache.has(key):
        return S.cache.get(key)
    try:
        req = _u.Request(RCSB_COMP % cid, headers={"User-Agent": S.UA})
        with _u.urlopen(req, timeout=S.TIMEOUT, context=S._ctx) as r:
            d = _j.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    c = parse_comp(d)
    return S.cache.put(key, c) if c else None


def species_check(target=None, drug=None, max_fetch=120, top=8, organism=None):
    """**실험 구조에 실제로 붙어 있는 분자**와 우리가 도킹할 분자를 맞대 본다.

    돌려주는 것 — `{our, comps, mismatch, 판정}`
    """
    from ..io import sources
    o = apo_scan(target, organism=organism, max_fetch=max_fetch,
                 drug=drug or DEMO["drug"])
    out = {"target": o.get("target"), "organism": organism,
           "drug": drug or DEMO["drug"],
           "막힌곳": o.get("막힌곳"), "our": None, "comps": [], "판정": None}
    if o.get("막힌곳") and not o.get("cands"):
        return out

    # ── 이 표적 구조들에 붙어 있는 것을 센다 ─────────────────────────
    import collections
    cnt = collections.Counter()
    for x in o.get("cands") or []:
        for c in (x.get("bound") or []):
            c = str(c).upper()
            if c not in BENIGN:
                cnt[c] += 1
    out["n_holo"] = sum(1 for x in (o.get("cands") or []) if not x.get("apo"))

    ik = sources.fetch_inchikey(out["drug"]) or {}
    out["our"] = {"name": out["drug"], "inchikey": ik.get("inchikey"),
                  "skeleton": skeleton(ik.get("inchikey")), "error": ik.get("error")}

    out["n_lig_kinds"] = len(cnt)
    for cid, n in cnt.most_common(top):
        c = _comp(cid) or {"id": cid, "name": None, "inchikey": None}
        c["n"] = n
        c["skeleton"] = skeleton(c.get("inchikey"))
        c["same"] = (c["skeleton"] is not None and out["our"]["skeleton"] is not None
                     and c["skeleton"] == out["our"]["skeleton"])
        out["comps"].append(c)

    if not out["our"]["skeleton"]:
        out["판정"] = ("**대조 불가** — 우리 분자의 InChIKey 를 못 받았다(%s). "
                     "**모르면 「같다」가 아니다**" % (out["our"].get("error") or "이유 미상"))
    elif not out["comps"]:
        out["판정"] = "**대조할 것이 없다** — 이 표적 구조에 결합 리간드가 안 잡혔다"
    elif any(c["same"] for c in out["comps"]):
        out["판정"] = "**같은 분자가 실험 구조에 있다** — 도킹은 재현(redocking)이다"
    else:
        out["판정"] = ("**다른 분자다.** 실험 구조에 붙어 있는 것은 %s 인데 우리가 "
                     "도킹하려는 것은 `%s` 다. **전구약물·활성대사체 문제일 수 있다** "
                     "— 그렇다면 이 점수는 «그럴듯하지만 다른 분자의 점수»다"
                     % (" · ".join("`%s`" % c["id"] for c in out["comps"][:3]),
                        out["drug"]))
    return out


# ══════════════════════════════════════════════════════════════════════
#  방향을 뒤집는다 — **구조에서 리간드를 뒤지지 말고, 약물로 구조를 찾는다**
# ══════════════════════════════════════════════════════════════════════
#
#   08-13 실측이 종 대조의 토대를 무너뜨렸다(결함 187) —
#
#     CCR5        홀로 6건 · 리간드 **1종**(NAG)   ← 4MBS 의 maraviroc 이 없다
#     M.tb RNAP   홀로 78건 · 리간드 **3종 4건**   ← rifampin 결합 구조가 없다
#
#   `rcsb_entry_info.nonpolymer_bound_components` 가 **대부분 비어 있다.**
#   나는 그 필드가 채워져 있을 거라 **믿고** 종 대조를 그 위에 세웠다.
#
#   ## 고침은 필드를 바꾸는 게 아니라 **질문의 방향을 바꾸는 것**이다
#
#     앞판   구조 N개를 열어 «여기 우리 약이 있나» 를 N번 묻는다
#            → 자료원이 안 채워 주면 **전부 「없다」로 읽힌다**
#     새판   **약물 → PDB 화학성분 코드 → 그 코드를 가진 구조 목록**
#            → 「있다」가 자료로 증명되고, 없으면 그냥 빈 목록이다
#
#   `UniChem`(EBI · 키 없음)이 InChIKey → PDBe het code 를 준다.
#   `PDBe in_pdb` 가 het code → 그 코드를 가진 PDB 목록을 준다.

UNICHEM = "https://www.ebi.ac.uk/unichem/rest/inchikey/%s"
PDBE_IN_PDB = "https://www.ebi.ac.uk/pdbe/api/pdb/compound/in_pdb/%s"
UNICHEM_PDBE_SRC = "3"          # UniChem 소스 번호 — PDBe 화학성분


def parse_unichem(doc):
    """UniChem 응답 → **PDB het code 집합**. 모양이 다르면 `None`.

    빈 집합(«이 분자는 PDB 에 없다»)과 `None`(«못 물어봤다»)은 **다르다.**
    결함 35·89 계열을 여기도 적용한다.
    """
    if not isinstance(doc, list):
        return None                      # 오류 응답은 dict 로 온다
    out = set()
    for r in doc:
        if not isinstance(r, dict):
            continue
        if str(r.get("src_id")) == UNICHEM_PDBE_SRC:
            c = r.get("src_compound_id")
            if c:
                out.add(str(c).strip().upper())
    return out


def parse_in_pdb(doc, het):
    """PDBe `in_pdb` 응답 → **PDB ID 집합(대문자)**. 모양이 다르면 `None`."""
    if not isinstance(doc, dict):
        return None
    v = doc.get(het) or doc.get(str(het).lower()) or doc.get(str(het).upper())
    if v is None:
        return set() if doc == {} else None
    if not isinstance(v, list):
        return None
    return {str(x).strip().upper() for x in v if x}


def _json(url):
    import json as _j, urllib.request as _u
    from ..io import structure as S
    req = _u.Request(url, headers={"User-Agent": S.UA, "Accept": "application/json"})
    with _u.urlopen(req, timeout=S.TIMEOUT, context=S._ctx) as r:
        return _j.loads(r.read().decode("utf-8", "replace"))


def drug_hets(inchikey):
    """약물 InChIKey → PDB het code 집합. 실패하면 `None`."""
    if not inchikey:
        return None
    from ..io import structure as S
    key = "HET::" + inchikey
    if S.cache.has(key):
        v = S.cache.get(key)
        return set(v) if isinstance(v, list) else None
    try:
        d = _json(UNICHEM % inchikey)
    except Exception:
        return None
    s = parse_unichem(d)
    if s is None:
        return None
    S.cache.put(key, sorted(s))
    return s


def pdbs_with(het):
    """het code → 그 코드를 가진 PDB ID 집합. 실패하면 `None`."""
    from ..io import structure as S
    key = "INPDB::" + het
    if S.cache.has(key):
        v = S.cache.get(key)
        return set(v) if isinstance(v, list) else None
    try:
        d = _json(PDBE_IN_PDB % het.lower())
    except Exception:
        return None
    s = parse_in_pdb(d, het)
    if s is None:
        return None
    S.cache.put(key, sorted(s))
    return s


def drug_structures(inchikey):
    """약물 InChIKey → `(그 약이 든 PDB 집합, het codes)`. 못 물으면 `(None, None)`."""
    hets = drug_hets(inchikey)
    if hets is None:
        return None, None
    if not hets:
        return set(), set()              # **PDB 에 없다** — 빈 것과 못 문 것은 다르다
    ids = set()
    for h in sorted(hets):
        p = pdbs_with(h)
        if p is None:
            return None, hets            # 하나라도 못 물었으면 **모른다**
        ids |= p
    return ids, hets


def api_probe(drug="rifampin"):
    """**두 끝점이 살아 있나.** 한 번 돌려서 모양을 눈으로 본다.

    추측한 끝점 위에 판정을 세우지 않으려고 만든다 — 오늘 이미 세 번
    이름을 잘못 짚었다(`plddt_for`·`pubchem_smiles`·`bound_components`).
    """
    from ..io import sources
    out = {"drug": drug}
    ik = (sources.fetch_inchikey(drug) or {}).get("inchikey")
    out["inchikey"] = ik
    try:
        raw = _json(UNICHEM % ik) if ik else None
        out["unichem_type"] = type(raw).__name__
        out["unichem_head"] = str(raw)[:220]
        out["hets"] = sorted(parse_unichem(raw) or [])
    except Exception as e:
        out["unichem_error"] = "%s: %s" % (type(e).__name__, e)
        out["hets"] = None
    # ── 진짜 고침 경로: 항목 → 비중합체 엔티티 → 성분 코드 ──────────
    for pdb in ("4MBS", "5UHC"):
        try:
            e = _json(RCSB_ENTRY % pdb)
            info = e.get("rcsb_entry_info") or {}
            out["entry_" + pdb] = {
                "bound_요약": info.get("nonpolymer_bound_components"),
                "비중합체수": info.get("nonpolymer_entity_count"),
                "엔티티번호": parse_nonpoly_ids(e),
                "핵산": parse_polymer(e)}
            ids = parse_nonpoly_ids(e) or []
            comps = []
            for eid in ids[:6]:
                comps.append(parse_nonpoly_comp(_json(RCSB_NONPOLY % (pdb, eid))))
            out["entry_" + pdb]["성분코드"] = comps
        except Exception as ex:
            out["entry_" + pdb] = "%s: %s" % (type(ex).__name__, ex)
    if out.get("hets"):
        h = out["hets"][0]
        try:
            raw = _json(PDBE_IN_PDB % h.lower())
            out["inpdb_type"] = type(raw).__name__
            out["inpdb_head"] = str(raw)[:220]
            ids = parse_in_pdb(raw, h)
            out["n_pdb"] = None if ids is None else len(ids)
            out["pdb_sample"] = sorted(ids)[:8] if ids else []
        except Exception as e:
            out["inpdb_error"] = "%s: %s" % (type(e).__name__, e)
    return out


def _self_hash():
    """**이 파일의 sha256.** 결과가 «어느 판 코드가 냈는지» 를 증언한다.

    봉인 json 의 `실행_전_증거` 와 맞대 보면 «봉인 이후 코드가 바뀌었나» 를
    사람이 즉시 안다(결함 190).
    """
    import hashlib as _h
    return _h.sha256(open(__file__, "rb").read()).hexdigest()[:16]


def dock_verdict(species_same, n_apo, n_holo, site_formed_apo=None):
    """**도킹을 해도 되나.** 결함 180.

    08-13 실측이 두 요구를 정면으로 부딪히게 만들었다 —

      · **답안지를 피하려면** 리간드·RNA 가 없는 `apo` 구조를 써야 한다
      · **맞는 분자를 넣으려면** 활성형(삼인산)을 써야 하는데,
        그 자리는 **RNA 이중가닥 + Mg²⁺ 가 있어야 만들어진다**

    즉 **이 표적에서는 「맞는 분자」와 「답안지 회피」를 동시에 못 한다.**
    `--species` 가 찍은 리간드 census 가 그 근거다 — ADP·GTP·GNP·POP·L2B,
    **전부 뉴클레오티드와 인산전이 유사체**다. 약물스러운 분자가 아니라
    **보조인자 자리**라는 뜻이다.

    ## 그래서 «못 한다» 가 아니라 **«이 자리에서는 도킹을 쓰지 않는다»** 다

    제안서 §2.5 가 스스로 그렇게 적었다 — 창의적 기여는
    *«언제 도킹을 적용하지 **말아야** 하는가»* 를 아는 것이다.

    `site_formed_apo` 가 `None`(모름)이면 **거부**다. 모르면 배제.
    """
    if species_same is None:
        # **모르는 것을 다른 이유로 적으면 안 된다.** 08-13 실측에서
        # `ibalizumab`(항체)이 «자리가 안 만들어진다» 로 나왔다 — 사실은
        # **SMILES 자체가 없어서** 종을 못 잰 것이다(결함 185).
        return ("거부", "**종을 못 쟀다** — 우리 분자의 InChIKey 를 못 받았거나 "
                        "이 표적에 결합 리간드가 안 잡혔다. **모르면 「같다」가 "
                        "아니다**. 항체·펩타이드면 저분자 도킹 대상이 아니다")
    if species_same is False:
        return ("거부", "**종 불일치** — 실험 구조에 오는 분자와 우리가 넣을 "
                        "분자가 다르다. 점수가 나와도 **다른 분자의 점수**다")
    if not n_apo:
        return ("거부", "**답안지뿐** — 리간드·핵산 없는 구조가 0건이다. "
                        "재현(redocking)이 되므로 예측이라 부를 수 없다")
    if site_formed_apo is not True:
        return ("거부", "**자리가 안 만들어진다** — apo 구조에서 그 자리가 "
                        "형성되는지 확인 안 됐다(%s). 보조인자 의존 자리면 "
                        "빈 구조에 넣는 것은 물리적으로 무의미하다"
                        % ("모름" if site_formed_apo is None else "아니오"))
    return ("진행", "종이 맞고 apo 구조가 있고 자리도 형성된다")

# ══════════════════════════════════════════════════════════════════════
#  후보 주사 — **데모 표적을 내가 고르지 않는다** (결함 181)
# ══════════════════════════════════════════════════════════════════════
#
#   제안서 §2.4 표에서 **도킹 가능한 행은 하나뿐**이고(RdRp), 그게 결함
#   179·180 으로 막혔다. 표적을 바꾸려면 **누가 고르느냐**가 문제가 된다.
#
#   **내가 고르면 안 된다.** 고르는 순간 «되는 것을 골랐다» 가 되고,
#   그건 §4.2 가 막는 사후 판단 편향이다.
#
#   그래서 후보를 **우리 라우터의 출력**에서 가져온다 —
#   `routercheck.json` 의 `docking_advised=True` **전부**(8건). 이 파일은
#   `사전명세_라우터분기.md` 봉인을 열고 08-11에 이미 나온 결과다.

SCAN_SRC = "routercheck.json"


def scan_candidates(path=None, only_advised=True):
    """라우터가 «도킹 타당» 이라 한 후보 **전부**. 고르지 않는다.

    `only_advised=False` 면 **16쌍 전부**를 돌려준다. 그건 **채택용이 아니라
    진단용**이다 — 봉인 `aff5c888d546` 는 «`docking_advised=True` 8건» 으로
    고정돼 있고, 그 규칙은 안 건드린다(결함 183 진단 모드).
    """
    import json as _j, os as _os
    from .. import evidence as _EV
    p = path or _os.path.join(_EV.ROOT, SCAN_SRC)
    d = _j.load(open(p, encoding="utf-8"))
    return [{"drug": r.get("drug"), "target": r.get("target"),
             "disease": r.get("disease"), "mech": r.get("mech"),
             "advised": bool(r.get("docking_advised")), "route": r.get("route")}
            for r in (d.get("행") or []) if (r.get("docking_advised") or not only_advised)]


# 질환 → 병원체. **판단이 아니라 사실이고, 재실행 전에 적는다**(결함 184).
#
#   숙주 표적은 여기를 안 본다 — **라우터가 이미 `직접·숙주` 라고 말했으므로**
#   `Homo sapiens` 로 간다. 즉 생물종을 **내가 정하는 게 아니라 라우터의
#   출력에서 끌어온다.**
PATHOGEN = {
    "COVID-19": "SARS-CoV-2",
    "Hepatitis C": "Hepatitis C virus",
    "Influenza": "Influenza A virus",
    "HIV Infections": "Human immunodeficiency virus 1",
    "Herpes Simplex": "Human herpesvirus 1",
    "Tuberculosis": "Mycobacterium tuberculosis",
    "Urinary Tract Infections": "Escherichia coli",
}


def organism_for(c):
    """후보 → 생물종. 못 정하면 `None` 이고 **그러면 거부**다.

    `숙주` 는 라우터가 말한 것이라 사람으로 간다. `병원체` 는 질환에서
    끌어온다. **둘 다 아니면 안 찍는다** — 조용히 넓게 찾다가
    엉뚱한 종의 단백질을 잡는 것이 결함 184 다.
    """
    mech = c.get("mech") or ""
    if "숙주" in mech:
        return "Homo sapiens"
    if "병원체" in mech:
        return PATHOGEN.get(c.get("disease"))
    return None


def site_needs_na(cands, our_skel, skel_of):
    """**우리 분자가 붙은 구조 중 핵산 없는 것이 있나.**

    돌려주는 것 — `(자리가_형성되나, 우리분자_붙은_구조수, 그중_핵산없는수)`

    ## 왜 «이 단백질이 대개 핵산과 함께 풀리나» 가 아닌가

    그건 **단백질의 습관**이지 **이 약의 자리**가 아니다. RNA 중합효소는
    대개 DNA 와 같이 풀리지만 rifampin 의 자리는 β 소단위 통로다.
    질문은 **«이 약이 붙은 구조 중 핵산 없는 것이 있나»** 여야 한다.

    `None` 이면 **우리 분자가 어느 구조에도 없다** — 판단 불가이고,
    `dock_verdict` 가 «모르면 거부» 로 받는다.
    """
    if not our_skel:
        return None, 0, 0
    with_drug = [x for x in cands
                 if any(skel_of(c) == our_skel for c in (x.get("bound") or []))]
    if not with_drug:
        return None, 0, 0
    no_na = [x for x in with_drug if x.get("na") is False]
    return (len(no_na) > 0), len(with_drug), len(no_na)


def scan(max_fetch=150, path=None, only_advised=True):
    """후보 전부에 §3-f 규칙을 적용한다. **채택은 규칙이 한다.**

    `only_advised=False` 는 **진단 모드**다 — 16쌍 전부를 재지만
    **채택은 여전히 `advised=True` 안에서만** 한다(봉인 `aff5c888d546`).
    """
    from ..io import sources
    out = {"rows": [], "pick": None, "mode": "채택" if only_advised else "진단(16쌍)"}
    for c in scan_candidates(path, only_advised=only_advised):
        r = dict(c)
        org = organism_for(c)
        r["organism"] = org
        if not (c.get("target") or "").strip():
            r["판정"], r["why"] = "거부", "**표적이 없다** — 라우터가 표적을 안 냈다"
            out["rows"].append(r); continue
        if not org:
            r["판정"], r["why"] = "거부", ("**생물종 미지정** — 질환 `%s` 를 병원체에 "
                                       "못 붙였다. **넓게 찾지 않는다**(결함 184)"
                                       % c.get("disease"))
            out["rows"].append(r); continue
        try:
            o = apo_scan(c["target"], organism=org, max_fetch=max_fetch)
        except Exception as e:
            r["판정"], r["why"] = "오류", "%s: %s" % (type(e).__name__, e)
            out["rows"].append(r); continue
        r["막힌곳"] = o.get("막힌곳")
        r["n_cover"] = o.get("n_cover"); r["n_apo"] = o.get("n_apo")
        r["n_na"] = o.get("n_na")
        cands = o.get("cands") or []
        r["n_holo"] = sum(1 for x in cands if not x.get("apo"))
        ik = (sources.fetch_inchikey(c["drug"]) or {}).get("inchikey")
        our = skeleton(ik)
        r["our_skeleton"] = our

        _memo = {}

        def _sk(cid):
            cid = str(cid).upper()
            if cid in BENIGN:
                return None
            if cid not in _memo:
                _memo[cid] = skeleton((_comp(cid) or {}).get("inchikey"))
            return _memo[cid]

        same = None
        if our:
            hits = [x for x in cands
                    if any(_sk(z) == our for z in (x.get("bound") or []))]
            same = bool(hits) if cands else None
            r["n_drugbound"] = len(hits)
        r["species_same"] = same
        formed, n_wd, n_wd_free = site_needs_na(cands, our, _sk)
        r["site_formed_apo"] = formed
        r["n_drug_no_na"] = n_wd_free
        k, why = dock_verdict(same, r.get("n_apo") or 0, r.get("n_holo") or 0, formed)
        r["판정"], r["why"] = k, why
        out["rows"].append(r)

    # **채택은 봉인 규칙 안에서만** — 진단 모드여도 넓히지 않는다
    ok = [r for r in out["rows"] if r["판정"] == "진행" and r.get("advised", True)]
    out["pick"] = ok[0] if ok else None
    out["n_ok"] = len(ok)
    return out


def scan_report(o):
    L = ["", "  ══ 후보 주사 — **규칙이 고른다, 내가 고르지 않는다** ══", ""]
    L.append("  모드   %s" % o.get("mode"))
    L.append("  후보는 `routercheck.json` 에서 온다 — **내가 추리지 않는다**")
    L.append("")
    L.append("    %-14s %-24s %-22s %5s %4s %4s %5s %s"
             % ("약물", "표적", "생물종", "덮음", "apo", "약물", "종", "판정"))
    for r in o["rows"]:
        L.append("    %-14s %-24s %-22s %5s %4s %4s %5s %s%s"
                 % (str(r.get("drug"))[:14], str(r.get("target"))[:24],
                    str(r.get("organism") or "**미지정**")[:22],
                    r.get("n_cover"), r.get("n_apo"), r.get("n_drugbound"),
                    {True: "같음", False: "다름", None: "미상"}[r.get("species_same")],
                    r.get("판정"),
                    "" if r.get("advised", True) else "  (진단만)"))
    L += ["", "  사유 —", ""]
    for r in o["rows"]:
        L.append("    %-16s %s" % (str(r.get("drug"))[:16],
                                   (r.get("막힌곳") or r.get("why") or "")[:96]))
    L += [""]
    if o["pick"]:
        p = o["pick"]
        L.append("  ✅ 채택 — **%s → %s** (%s)" % (p["drug"], p["target"], p.get("disease")))
        L.append("     apo %s건 · 우리 분자가 붙은 구조 %s건 중 핵산 없는 것 %s건"
                 % (p.get("n_apo"), p.get("n_drugbound"), p.get("n_drug_no_na")))
    else:
        L.append("  ❌ **진행이 0건이다.** 표적을 바꿔도 조건을 만족하는 것이 없다")
        L.append("     → `S3도킹_설계.md §2` 의 선택지 ①(거부 자체를 데모로)로 돌아간다")
    L.append("")
    return "\n".join(L)



def species_report(o):
    L = ["", "  ══ 종 대조 — 그 자리에 오는 분자가 맞나 ══", ""]
    L.append("  표적   %s" % o.get("target"))
    L.append("  생물종 %s" % (o.get("organism") or "**미지정**"))
    L.append("  약물   %s" % o.get("drug"))
    u = o.get("our") or {}
    L.append("  우리 것 InChIKey  %s  (연결블록 `%s`)"
             % (u.get("inchikey") or "**못 받았다**", u.get("skeleton") or "―"))
    if o.get("comps"):
        L += ["", "  실험 구조에 붙어 있는 것 — 홀로 %s건 · 리간드 **%s종** "
              "(아래는 상위 %s개)" % (o.get("n_holo"), o.get("n_lig_kinds"),
                                 len(o["comps"])), ""]
        for c in o["comps"]:
            L.append("    %-5s %2d건  %-14s %s"
                     % (c["id"], c["n"], c.get("skeleton") or "InChIKey 없음",
                        ("**같은 분자**" if c["same"] else "다름")
                        + ("  " + (c.get("name") or "")[:40] if c.get("name") else "")))
    L += ["", "  → " + (o.get("판정") or o.get("막힌곳") or "판정 없음"), ""]
    return "\n".join(L)



def apo_report(o):
    """apo 주사 결과 → 사람이 읽는 글."""
    L = ["", "  ══ apo 구조 고르기 (결함 175 — 답안지 회피) ══", ""]
    L.append("  표적   %s" % o["target"])
    if o.get("accession"):
        L.append("  항목   %s" % o["accession"])
    c = o.get("chain")
    if c:
        L.append("  사슬   %s  %d–%d  (%d잔기)"
                 % (c["name"], c["start"], c["end"], c["end"] - c["start"] + 1))
    if o.get("mature") and not o.get("n_xref"):
        L += ["", "  성숙 사슬 %d개 — **UniProt 이 쓰는 이름 그대로다**" % len(o["mature"]), ""]
        for c in sorted(o["mature"], key=lambda x: x["start"]):
            L.append("    %6d–%-6d  %s" % (c["start"], c["end"], c["name"] or "(이름 없음)"))
    if o.get("n_xref") is not None:
        L.append("")
        L.append("  PDB 교차참조        %d건   ← 이 수를 표적 구조 수라고 말하면 결함 90" % o["n_xref"])
        L.append("  사슬 %d%% 이상 덮음  %d건   ← **이게 실제 후보다**"
                 % (COVER_MIN * 100, o.get("n_cover", 0)))
    if o.get("n_checked"):
        L.append("  리간드 조회         %d건   (해상도 순 · 나머지는 안 봤다)" % o["n_checked"])
        L.append("  그중 핵산 결합       %d건   ← **RNA 가 붙은 것은 apo 가 아니다**(결함 178)"
                 % o.get("n_na", 0))
        L.append("  남은 apo            %d건" % o.get("n_apo", 0))
    if o["cands"]:
        L += ["", "  상위 8건 —", ""]
        for x in o["cands"][:8]:
            L.append("    %-5s %-6s %-5s 덮음%4d  %s"
                     % (x["id"], x.get("method") or "?",
                        ("%.2fÅ" % x["resolution"]) if x.get("resolution") else "  ―  ",
                        x["covered"],
                        "**apo**" if x["apo"] else "리간드 " + ", ".join(x["ligands"][:4])))
    L.append("")
    if o["막힌곳"]:
        L.append("  ❌ 막힌 곳 — " + o["막힌곳"])
    else:
        b = o["best"]
        L.append("  ✅ 고른 구조 — **%s** (%s · %s · 덮음 %d잔기 · 결합 리간드 없음)"
                 % (b["id"], b.get("method") or "?",
                    ("%.2fÅ" % b["resolution"]) if b.get("resolution") else "해상도 미상",
                    b["covered"]))
        # ⛔ 08-14 결함 212 — 앞판은 **`remdesivir` 를 하드코딩**했다.
        #   `--target CCR5 --drug maraviroc` 으로 돌리니 화면이
        #   «이 구조는 **remdesivir** 를 본 적이 없다» 고 찍었다.
        #   **화면이 거짓말을 한 것**이고, `CLAUDE.md §4` 가 금지한
        #   «해석 문구를 상수로 고정» 의 세 번째 재발이다(결함 209 계열).
        #
        #   `apo_scan` 은 약물 이름을 안 받는다. **모르면 약물을 언급하지
        #   않는다** — 아는 것만 적는 것이 이 프로젝트의 규율이다.
        d = o.get("drug")
        L.append("     이 구조에는 **결합 리간드가 없다** — %s"
                 % ("`%s` 를 본 적이 없으므로 도킹이 재현이 아니다" % d if d
                    else "답안지가 아니다 (약물 이름은 이 단계에서 안 받는다)"))
    L.append("")
    return "\n".join(L)


def live_report(o: Dict[str, Any]) -> str:
    L = ["=" * 68, "S3 — **실제 조회** (부품이 아니라 값이 나오는가)", "=" * 68,
         "  표적 %s" % o["target"], "  약물 %s" % o["drug"], ""]
    r = o.get("resolve") or {}
    L += ["  ① 표적 → UniProt",
          "     accession %s · %s" % (r.get("accession"), r.get("name")),
          "     서열 길이 %s · %s %s"
          % (r.get("seq_len"),
             ("**사슬 `%s` 의 활성부위 잔기 %s개**"
              % ((o.get("localize") or {}).get("chain"), r.get("n_sites_chain")))
             if (o.get("localize") or {}).get("kind") == "국소화"
             else ("**활성부위 주석 %s개**(단일 사슬 — 폴리단백질이 아니다)"
                   % r.get("n_sites")
                   if (o.get("localize") or {}).get("kind") == "단일"
                   else "**폴리단백질 전체 주석 %s개**(사슬 미확정 — 이 표적 것이 아니다)"
                        % r.get("n_sites")),
             r.get("sites")),
          "     error %s" % r.get("error")]
    if o.get("plddt"):
        p = o["plddt"]
        L += ["", "  ② 구조 → AlphaFold pLDDT",
              "     전체 평균 %s · 최소 %s · 낮은비율 %s"
              % (p.get("mean"), p.get("min"), p.get("frac_low")),
              "     **활성부위 평균 %s · 최소 %s**" % (p.get("site_mean"), p.get("site_min")),
              "     S1 라벨 **%s**" % o.get("s1_label")]
    if o.get("pdb_count") is not None:
        L += ["", "  ⓘ **실험 구조 %s건**(결함 94) — 예측 구조를 쓸 이유가 없는 표적일 수 있다"
              % o["pdb_count"]]
    if o.get("smiles"):
        L += ["", "  ③ 리간드 SMILES", "     %s" % str(o["smiles"])[:160]]
    L += ["", ("  ❌ 막힌 곳 — %s" % o["막힌곳"]) if o.get("막힌곳")
          else "  ✅ %s" % o.get("판정"), ""]
    L += ["  ⚠ **함정 둘을 여기서 본다**",
          # ⛔ 08-14 결함 213 — 앞판은 **`RdRp` 를 박아 놨다.**
          #   `--target CCR5` 로 돌려도 «RdRp 는 폴리단백질 일부다» 가 찍혔다.
          #   결함 212 와 같은 병(해석 문구를 상수로 고정)의 **네 번째**다.
          ("     · **이 표적이 폴리단백질이면** 잔기 번호가 어긋난다 — 결함 90→98 재현"
           if (o.get("localize") or {}).get("kind") != "단일"
           else "     · 단일 사슬이라 잔기 번호는 어긋나지 않는다"),
          "     · **활성부위 0개면 접는다** — blind docking 은 §2.5 의 «포켓 내 포즈» 가 아니다",
          "=" * 68]
    return "\n".join(L)


def report(o: Dict[str, Any]) -> str:
    L = ["=" * 68, "S3 도킹 데모 1건 — **부품 재고** (제안서 §2.4·§2.5)", "=" * 68,
         "", "  파이썬 모듈"]
    for k, v in o["python_modules"].items():
        L.append("    %-12s %s" % (k, v))
    L += ["", "  실행 파일"]
    for k, v in o["binaries"].items():
        L.append("    %-12s %s" % (k, v))
    L += ["", "  우리 코드 (①② — 이미 있다)"]
    for k, v in o["ours"].items():
        L.append("    %-16s %s" % (k, v))
    L += ["",
          "  ③ 리간드 3D·PDBQT : %s" % ("가능" if o["③_리간드_가능"] else "**막혔다**"),
          "  ④ 도킹 실행       : %s" % ("가능" if o["④_도킹_가능"] else "**막혔다**"),
          "", "  판정 — %s" % o["판정"], ""]
    if not (o["③_리간드_가능"] and o["④_도킹_가능"]):
        import platform
        win = platform.system() == "Windows"
        L += ["  막힌 곳을 여는 법 (**설치는 사람이 판단한다**)"]
        if not o["③_리간드_가능"]:
            L += ["    ③  pip install rdkit"]
        if "❌" in str(o["python_modules"].get("meeko", "")):
            L += ["    ③  pip install meeko      ← SMILES→PDBQT. 순수 파이썬 · Windows 됨"]
        if not o["④_도킹_가능"]:
            if win:
                # ⚠ **08-13에 여기 «pip install vina» 라고 적었다가 고쳤다.**
                #   그 패키지는 Linux/macOS 중심이고 공식 문서도 CLI 를
                #   «macOS·Linux·WSL» 로 안내한다. **Windows 는 실행 파일이 정답이다.**
                #   확인 안 하고 적을 뻔했다 — 결함 170 과 같은 자리.
                L += ["    ④  **Windows 는 공식 실행 파일을 받는다** (pip 가 아니다)",
                      "        github.com/ccsb-scripps/AutoDock-Vina/releases",
                      "          → vina_1.2.x_windows_x86_64.exe 를 받아",
                      "          → **vina.exe 로 이름을 바꾸고** PATH 에 둔다",
                      "        (`pip install vina` 는 Linux/macOS 중심이다)"]
            else:
                L += ["    ④  pip install vina      ← 파이썬 바인딩",
                      "        또는 실행 파일을 PATH 에 둔다"]
        L += [""]
    L += ["  데모 후보 — **1건만 한다**",
          "    %s / %s" % (DEMO["drug"], DEMO["disease"]),
          "    표적 %s" % DEMO["target"],
          "    %s" % DEMO["왜"], "",
          "  ⚠ 부품이 있는 것과 **1건이 실제로 도는 것**은 다르다.",
          "  ⚠ 통과하면 **명세를 먼저 쓰고** 그 다음에 돌린다 (결함 170).",
          "  ⚠ 판정은 «명백한 입체 충돌» 까지다 — **결합력을 예측하지 않는다.**",
          "=" * 68]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=None,
                    help="결과를 파일로 저장. **이미 있으면 안 덮는다**"
                         " (`CLAUDE.md §3-3`)")
    ap.add_argument("--live", action="store_true",
                    help="**실제로 조회한다** — 표적·구조·SMILES 가 나오는지")
    ap.add_argument("--apo", action="store_true",
                    help="**답안지 아닌 실험 구조**를 고른다 (결함 175 · 망 탄다)")
    ap.add_argument("--all", action="store_true",
                    help="**16쌍 전부** 진단 (채택은 여전히 봉인 8건 안에서만)")
    ap.add_argument("--api", action="store_true",
                    help="**끝점 두 개가 살아 있나** — 추측 위에 판정을 안 세운다")
    ap.add_argument("--scan", action="store_true",
                    help="**라우터가 낸 후보 전부**에 규칙을 적용한다 (결함 181)")
    ap.add_argument("--species", action="store_true",
                    help="**그 자리에 오는 분자가 맞나** (전구약물·활성대사체 · 결함 179)")
    ap.add_argument("--organism", default=None,
                    help="**생물종을 명시한다** (결함 184 — 기본값은 없다)")
    ap.add_argument("--top", type=int, default=8, help="종 대조에서 볼 리간드 수")
    ap.add_argument("--max-fetch", type=int, default=120)
    ap.add_argument("--target", default=None)
    ap.add_argument("--drug", default=None)
    a = ap.parse_args(argv)

    def _save(o):
        """결과 저장. **덮어쓰지 않는다** — 지우려면 사람이 `archive\\` 로 옮긴다.

        ## 화면보다 **먼저** 부른다 (결함 198)

        08-13 밤 실행이 12.3분 조회를 끝내고 **`print` 에서 죽었다**
        (`cp949` 가 `═` 를 못 쓴다). 저장이 출력 뒤였으므로 **결과가
        통째로 사라졌다.**

        > **화면은 실패해도 되지만 결과는 아니다.**

        그리고 **판정에 쓴 상수를 같이 싣는다**(결함 191). 명세가
        `COVER_MIN`·`BENIGN` 을 안 적어 뒀으므로, 결과 파일이 자기
        상수를 증언하게 하는 것이 문서에 다시 적는 것보다 강하다.
        """
        if not a.out:
            return
        o = dict(o)
        o["_상수"] = {"COVER_MIN": COVER_MIN, "BENIGN_n": len(BENIGN),
                     "BENIGN": sorted(BENIGN), "max_fetch": a.max_fetch,
                     "코드_sha256": _self_hash()}
        import os as _os
        if _os.path.exists(a.out):
            print("  ⚠ `%s` 이 이미 있다 — **안 덮는다.** 다시 만들려면 "
                  "`archive\\` 로 옮겨라 (`CLAUDE.md §3-3`)" % a.out)
            return
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(o, f, ensure_ascii=False, indent=1)
        print("  저장: %s" % a.out)

    if a.api:
        o = api_probe(a.drug or "rifampin")
        print(json.dumps(o, ensure_ascii=False, indent=1))
        return 0 if o.get("n_pdb") else 1
    if a.scan:
        o = scan(max_fetch=a.max_fetch, only_advised=not a.all)
        _save(o)          # **저장이 먼저다** (결함 198)
        print(json.dumps(o, ensure_ascii=False, indent=1) if a.json else scan_report(o))
        return 0 if o.get("pick") else 1
    if a.species:
        o = species_check(a.target, a.drug, max_fetch=a.max_fetch,
                          top=a.top, organism=a.organism)
        _save(o)          # **저장이 먼저다** (결함 198)
        print(json.dumps(o, ensure_ascii=False, indent=1) if a.json else species_report(o))
        return 0
    if a.apo:
        o = apo_scan(a.target, organism=a.organism, max_fetch=a.max_fetch,
                     drug=a.drug)
        _save(o)          # **저장이 먼저다** (결함 198)
        print(json.dumps(o, ensure_ascii=False, indent=1) if a.json else apo_report(o))
        return 1 if o.get("막힌곳") else 0
    if a.live:
        o = live(a.target, a.drug)
        print(json.dumps(o, ensure_ascii=False, indent=1) if a.json else live_report(o))
        return 1 if o.get("막힌곳") else 0
    o = probe()
    print(json.dumps(o, ensure_ascii=False, indent=1) if a.json else report(o))
    return 0 if (o["③_리간드_가능"] and o["④_도킹_가능"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
