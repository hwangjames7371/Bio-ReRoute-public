# -*- coding: utf-8 -*-
"""독성 조기 신호 — hERG · DILI · 탐색 범위 (제안서 §1.2)

  > 독성·규제 판단에는 Lipinski 규칙(Ro5)·PAINS(실험 교란 골격)·
  > **hERG(심장독성, ICH S7B)** 기준을 RDKit으로 자동 반영하되,
  > **대사산물 간독성(DILI)은 모화합물 1차 스크리닝으로 한정**하고
  > 최종 검증은 후속 실험에 위임한다.
  >
  > 탐색 범위는 **저분자 승인 약물(ChEMBL max_phase=4)로 한정**하며 …

세 가지가 다 빠져 있었다. 08-06에 넣는다.

## 먼저 — **이건 예측 모델이 아니다**

진짜 hERG 예측은 patch-clamp 실측으로 학습한 QSAR 모델이 한다. 여기서
하는 것은 **구조 경보**뿐이다. 문헌에 잘 알려진 hERG 결합 약물의 공통
특징(염기성 질소 + 소수성 + 방향족)을 세는 것이고, 이건 —

  · **양성 예측도가 낮다.** 승인 약물 상당수가 경보에 걸린다
  · **음성이 안전을 뜻하지 않는다.** 경보 없음 ≠ hERG 안전

그래서 PAINS와 **같은 규율**로 다룬다 — `기각이 아니라 경보`.
제안서 §2.5가 PAINS에 대해 세운 원칙을 그대로 적용한 것이다.

이 원칙을 안 지키면 어떻게 되는지 실측 예가 있다. **아미오다론·소타롤·
도페틸리드는 hERG를 막는 것이 곧 약효**다(class III 항부정맥제).
hERG 경보로 기각하는 시스템은 이들을 전부 잃는다.

## 탐색 범위 — 항체가 섞여 있었다

실측: 깔때기 표본 28건 중 **ibalizumab·belimumab 2건이 항체**다.
제안서가 저분자로 한정했는데 걸러지지 않았다. 저분자 여부는 —

  1. ChEMBL 조회가 가장 정확하지만 API가 하나 더 는다
  2. **이름 접미사**(-mab·-cept·-ase)가 값싸고 거의 정확하다
  3. 분자량(SMILES 취득 후 MW > 1000)

여기서는 1을 쓰되 실패하면 2로 떨어지고, **둘 다 안 되면 "모른다"** 를
돌려준다. 모르는 것을 저분자로 치면 조용히 범위를 넘는다.
"""

from .. import config as _config

import json
import re
import ssl
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from . import cache

TIMEOUT = 20
UA = "Bio-ReRoute"
CHEMBL = ("https://www.ebi.ac.uk/chembl/api/data/molecule/search"
          "?q=%s&format=json&limit=1")
_ctx = ssl.create_default_context()

# 생물학제제 접미사 (INN 명명 규칙). 저분자가 아니다.
BIO_SUFFIX = ("mab", "cept", "ase", "kin", "ximab", "zumab", "tide",
              "parin", "poetin", "grastim", "gene", "cel")

CAVEAT_HERG = ("구조 경보이지 예측이 아니다. 양성 예측도가 낮고 "
               "**경보 없음이 안전을 뜻하지 않는다**. ICH S7B 실측을 대체하지 않는다.")
CAVEAT_DILI = ("모화합물 1차 스크리닝만이다(제안서 §1.2). "
               "**대사산물 독성은 보지 않는다** — 후속 실험에 위임한다.")


def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
        return json.loads(r.read().decode("utf-8"))


# ── 탐색 범위 ────────────────────────────────────────────────
def small_molecule(name: str) -> Dict[str, Any]:
    """저분자 승인약인가 (제안서 §1.2 탐색 범위).

    반환 `is_small` 은 **True / False / None** 셋이다.
    None 은 "모른다"이고 **False 로 읽으면 안 된다.**
    """
    n = (name or "").strip()
    out = {"drug": n, "is_small": None, "max_phase": None,
           "how": "", "error": None}
    if not n:
        out["error"] = "약물명 없음"
        return out

    # 값싼 규칙 먼저 — 접미사는 조회 없이 확정적으로 아니라고 말한다
    low = n.lower()
    for s in BIO_SUFFIX:
        if low.endswith(s):
            out.update(is_small=False, how="INN 접미사 -%s → 생물학제제" % s)
            return out

    key = "CHEMBL::" + low
    if cache.has(key):
        return cache.get(key)
    try:
        d = _get(CHEMBL % urllib.parse.quote(n))
        ms = d.get("molecules") or []
        if not ms:
            out["error"] = "ChEMBL 0건"
            out["how"] = "**모른다** — 저분자로 치지 않는다"
            return cache.put(key, out)
        m = ms[0]
        out["max_phase"] = m.get("max_phase")
        typ = (m.get("molecule_type") or "").lower()
        out["is_small"] = (typ == "small molecule")
        out["how"] = "ChEMBL molecule_type=%r · max_phase=%s" % (typ, out["max_phase"])
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
        out["how"] = "조회 실패 — **모른다**"
        return out                      # 실패는 캐시하지 않는다 (결함 37)
    return cache.put(key, out)


def approved(name: str) -> Optional[bool]:
    """ChEMBL max_phase == 4 인가. 모르면 None."""
    r = small_molecule(name)
    mp = r.get("max_phase")
    try:
        return int(float(mp)) == 4 if mp is not None else None
    except Exception:
        return None


# ── hERG 구조 경보 ────────────────────────────────────────────
def herg_alert(smiles: str) -> Dict[str, Any]:
    """hERG 결합 경향의 **구조 경보** (제안서 §1.2 · ICH S7B).

    잘 알려진 hERG 차단제의 공통 특징 셋을 센다 — 문헌 합의 수준의
    거친 규칙이고 **우리가 자료를 보고 만든 게 아니다.**

      ① 염기성 질소 (양전하 상태로 Tyr652 와 상호작용)
      ② 소수성       (cLogP ≥ 3.7)
      ③ 방향족 고리 2개 이상 (Phe656 π 상호작용)

    셋 다면 `경보`, 둘이면 `주의`, 아니면 `해당없음`.
    **기각 사유가 아니다** — PAINS와 같은 규율(제안서 §2.5).
    """
    out = {"level": "확인불가", "hits": [], "why": "", "한계": CAVEAT_HERG,
           "logp": None, "n_aromatic": None, "basic_n": None}
    if not smiles:
        out["why"] = "SMILES 없음"
        return out
    try:
        from rdkit import Chem
        from rdkit.Chem import Crippen, Descriptors
    except Exception:
        out["why"] = "RDKit 미설치 — 경보를 계산하지 않았다. **없다는 뜻이 아니다**"
        return out
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        out["why"] = "SMILES 해석 실패"
        return out

    # ① 염기성 질소 — 아마이드·니트로·방향족 N 을 뺀 sp3 아민
    basic = Chem.MolFromSmarts("[NX3;H0,H1,H2;!$(N[C,S]=[O,S,N]);!$(N=*);!$([N+](=O))]")
    nb = len(m.GetSubstructMatches(basic)) if basic else 0
    logp = round(Crippen.MolLogP(m), 2)
    nar = Descriptors.NumAromaticRings(m)
    out.update(basic_n=nb, logp=logp, n_aromatic=nar)

    if nb >= 1:
        out["hits"].append("염기성 질소 %d" % nb)
    if logp >= 3.7:
        out["hits"].append("cLogP %.1f ≥ 3.7" % logp)
    if nar >= 2:
        out["hits"].append("방향족 고리 %d" % nar)

    n = len(out["hits"])
    out["level"] = "경보" if n == 3 else ("주의" if n == 2 else "해당없음")
    out["why"] = ("%s — %s. **기각 사유가 아니다**: 아미오다론·소타롤·도페틸리드는 "
                  "hERG 차단이 곧 약효다" % (out["level"], " · ".join(out["hits"]) or "특징 없음"))
    return out


# ── DILI 모화합물 1차 스크리닝 ────────────────────────────────
def dili_alert(smiles: str) -> Dict[str, Any]:
    """간독성 조기 신호 — **모화합물만** (제안서 §1.2).

    문헌에서 반복되는 규칙 하나를 쓴다 — *Rule-of-Two*
    (cLogP ≥ 3 **그리고** 일일 용량 ≥ 100mg 이면 DILI 위험 증가,
    Chen et al. 2013). **용량을 우리는 모른다.** 그래서 절반만 쓰고,
    나머지 절반이 없다는 것을 반환값에 적는다.

    반응성 대사산물을 만들 수 있는 구조 경보(니트로방향족·아닐린 등)를
    같이 센다. **대사산물 자체는 보지 않는다** — 제안서가 후속 실험에 위임했다.
    """
    out = {"level": "확인불가", "hits": [], "why": "", "한계": CAVEAT_DILI,
           "logp": None, "dose_known": False}
    if not smiles:
        out["why"] = "SMILES 없음"
        return out
    try:
        from rdkit import Chem
        from rdkit.Chem import Crippen
    except Exception:
        out["why"] = "RDKit 미설치 — 계산하지 않았다"
        return out
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        out["why"] = "SMILES 해석 실패"
        return out

    logp = round(Crippen.MolLogP(m), 2)
    out["logp"] = logp
    if logp >= 3.0:
        out["hits"].append("cLogP %.1f ≥ 3 (Rule-of-Two 절반)" % logp)

    # 반응성 대사산물 구조 경보 — 관용 목록
    alerts = {"니트로방향족": "[$(c[N+](=O)[O-])]",
              "아닐린": "[NX3;H2][c]",
              "티오펜": "c1ccsc1",
              "퓨란": "c1ccoc1",
              "하이드라진": "[NX3][NX3]"}
    for label, sma in alerts.items():
        pat = Chem.MolFromSmarts(sma)
        if pat is not None and m.HasSubstructMatch(pat):
            out["hits"].append(label)

    out["level"] = "주의" if len(out["hits"]) >= 2 else (
        "약한신호" if out["hits"] else "해당없음")
    out["why"] = ("%s — %s. **일일 용량을 모르므로 Rule-of-Two 를 절반만 적용했다.** "
                  "기각 사유가 아니다"
                  % (out["level"], " · ".join(out["hits"]) or "특징 없음"))
    return out
