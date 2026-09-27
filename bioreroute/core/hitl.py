# -*- coding: utf-8 -*-
"""HITL 음성 지식베이스 (제안서 §2 · §3.3-9 · §6 · §7)

  > 셋째, **전문가의 거절 판단(HITL, human-in-the-loop)이 음성 지식베이스에
  > 축적돼 유사 골격을 자동으로 차단하는 피드백 루프**다.
  > **세 축의 통합**으로 각 가설에 확률이 부여된다.

## 이걸 안 하겠다고 한 판단이 틀렸다

08-06에 나는 `제안서_대조표.md §D` 에 *"HITL 은 평가할 전문가가 없어
안 한다"* 고 적었다. 승우가 *"그래도 넣어야 하는 거 아니야?"* 라고 물어서
제안서를 다시 세어 보니 HITL이 **네 곳**에 있었다.

| | 위치 | 무엇 |
|---|---|---|
| §2 | **세 축 중 셋째** | 라우터·반증 깔때기와 **나란한 지위** |
| §3.3 | 4주 내(본선) | 2축 대시보드와 묶여 있음 |
| §3.3 끝 | **핵심 경로** | *"일정이 지연되는 경우에도"* 지킬 6개 중 하나 |
| §7 | 운영 비용 | *"**HITL로 불필요한 호출을 차단해** 일 300~500회"* |

**§7이 결정적이다.** HITL은 있으면 좋은 부가 기능이 아니라 **비용 모델의
전제**다. 그걸 빼면 일 300~500회라는 숫자의 근거가 사라진다.

그리고 내 사유 자체가 두 가지를 섞은 것이었다.

```
HITL 기능      거절을 기록하고 유사 골격을 다음에 걸러낸다   ← 전문가 없어도 만들고 시험한다
HITL 효과 측정  전문가 피드백이 성능을 올리는가              ← 전문가가 있어야 잰다
```

**제안서가 약속한 것은 루프이지 그 루프의 효과 측정이 아니다.**
결함 41과 똑같은 형태다 — *안 한 이유*를 검증 없이 썼다. 그래서 결함 42다.

## 제안서와 **다르게** 만든 곳 — 먼저 적는다

제안서는 *"유사 골격을 **자동으로 차단**"* 이라고 썼다. 그대로 하면
이 시스템의 규율을 깬다.

> **구조가 비슷하다는 것은 안 듣는다는 근거가 아니다.**
> 근거 없이 기각하는 것은 반증이 아니라 사전확률이다 — 전향 봉인 예측에서
> 제안서 자신의 예측이 빗나갔을 때 배운 것과 같다.

그래서 둘로 나눈다.

| 무엇 | 어떻게 | 왜 |
|---|---|---|
| **같은 쌍**을 사람이 거절 | **차단**(하드 비토) | 사람이 *바로 그 가설*을 봤다. 정당한 근거다 |
| **유사 골격** (Tanimoto ≥ 0.85) | **경보**만. 기각 안 함 | 유사는 근거가 아니다. 사람에게 되돌린다 |

제안서의 문구보다 **약하게** 만든 것이고, 그 사실을 여기 적는다.

## 되돌릴 수 있어야 한다

사람도 틀린다. `revoke()` 로 취소되고, 취소 기록도 남는다.
**지워지지 않고 append 만 된다** — 감사 추적이 본체라는 원칙 그대로다.

## 유사도 문턱

Morgan 지문(r=2, 2048비트) Tanimoto **0.85**. 화학정보학에서 "매우 유사"에
관용적으로 쓰는 값이고 **우리 자료를 보고 고른 값이 아니다.**
RDKit이 없으면 유사도를 **계산하지 않는다** — 0으로 채우지 않는다.
"""

import datetime
import json
import os
from typing import Any, Dict, List, Optional

KB_PATH = os.environ.get("BIOREROUTE_HITL", "hitl_kb.jsonl")

# 화학정보학 관용값. 자료를 보고 고르지 않았다.
TANIMOTO_BLOCK = 0.85
FP_RADIUS, FP_BITS = 2, 2048


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _key(drug: str, disease: str) -> str:
    return "%s||%s" % (_norm(drug), _norm(disease))


def record(drug: str, disease: str, reason: str, who: str = "expert",
           smiles: Optional[str] = None, path: Optional[str] = None) -> Dict[str, Any]:
    """전문가 거절을 음성 KB에 적는다. **append 만 한다.**

    `reason` 을 필수로 받는 이유 — 이유 없는 거절은 나중에 되짚을 수 없고,
    그러면 감사 추적이 아니라 그냥 목록이다.
    """
    if not (reason or "").strip():
        return {"ok": False, "error": "거절 사유가 없다 — 이유 없는 거절은 안 받는다"}
    rec = {"act": "reject", "drug": drug, "disease": disease,
           "reason": reason.strip(), "who": who, "smiles": smiles,
           "at": datetime.datetime.now().isoformat(timespec="seconds")}
    with open(path or KB_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True, "record": rec}


def revoke(drug: str, disease: str, why: str, who: str = "expert",
           path: Optional[str] = None) -> Dict[str, Any]:
    """거절을 취소한다. **지우지 않고 취소를 덧쓴다.**"""
    rec = {"act": "revoke", "drug": drug, "disease": disease,
           "reason": why, "who": who,
           "at": datetime.datetime.now().isoformat(timespec="seconds")}
    with open(path or KB_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True, "record": rec}


def load(path: Optional[str] = None) -> Dict[str, Any]:
    """KB → {pairs, entries, revoked}. 파일이 없으면 **빈 KB 라고 말한다.**"""
    p = path or KB_PATH
    out = {"pairs": {}, "entries": [], "revoked": 0, "path": p, "error": None}
    if not os.path.exists(p):
        return out
    try:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                out["entries"].append(r)
                k = _key(r.get("drug", ""), r.get("disease", ""))
                if r.get("act") == "revoke":
                    out["pairs"].pop(k, None)
                    out["revoked"] += 1
                else:
                    out["pairs"][k] = r
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    return out


def _tanimoto(a: str, b: str) -> Optional[float]:
    """Morgan 지문 Tanimoto. **RDKit이 없으면 None** — 0이 아니다."""
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem, DataStructs
    except Exception:
        return None
    ma, mb = Chem.MolFromSmiles(a or ""), Chem.MolFromSmiles(b or "")
    if ma is None or mb is None:
        return None
    fa = AllChem.GetMorganFingerprintAsBitVect(ma, FP_RADIUS, nBits=FP_BITS)
    fb = AllChem.GetMorganFingerprintAsBitVect(mb, FP_RADIUS, nBits=FP_BITS)
    return float(DataStructs.TanimotoSimilarity(fa, fb))


def consult(drug: str, disease: str, smiles: Optional[str] = None,
            kb: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """새 후보를 음성 KB에 물어본다.

      verdict "block" : **같은 쌍**을 사람이 거절했다 → 하드 비토
              "warn"  : 유사 골격이 거절된 적 있다 → **경보만**
              "clear" : 해당 없음
              "unknown": 유사도를 계산할 수 없었다(RDKit·SMILES 없음)
                         → **clear 로 읽으면 안 된다**
    """
    K = kb if kb is not None else load()
    out = {"verdict": "clear", "why": "", "match": None,
           "similar": [], "kb_size": len(K["pairs"])}

    hit = K["pairs"].get(_key(drug, disease))
    if hit:
        out.update(verdict="block", match=hit,
                   why="전문가가 **이 쌍을** 거절했다 (%s · %s): %s"
                       % (hit.get("who"), hit.get("at", "")[:10], hit.get("reason")))
        return out

    if not smiles:
        out["verdict"] = "unknown"
        out["why"] = "SMILES 없음 — 유사 골격을 확인하지 못했다. **없다는 뜻이 아니다**"
        return out

    calc = 0
    for k, r in K["pairs"].items():
        if _norm(r.get("disease", "")) != _norm(disease):
            continue                      # 질환이 다르면 골격 유사는 의미가 없다
        t = _tanimoto(smiles, r.get("smiles") or "")
        if t is None:
            continue
        calc += 1
        if t >= TANIMOTO_BLOCK:
            out["similar"].append({"drug": r.get("drug"), "tanimoto": round(t, 3),
                                   "reason": r.get("reason"), "who": r.get("who")})
    if out["similar"]:
        out["similar"].sort(key=lambda s: -s["tanimoto"])
        s = out["similar"][0]
        out.update(verdict="warn",
                   why=("거절된 유사 골격 %d건 (최고 Tanimoto %.2f · %s). "
                        "**기각하지 않는다** — 구조 유사는 무효의 근거가 아니다"
                        % (len(out["similar"]), s["tanimoto"], s["drug"])))
    elif calc == 0 and K["pairs"]:
        out["verdict"] = "unknown"
        out["why"] = "유사도를 계산하지 못했다(RDKit 미설치 또는 SMILES 부재)"
    return out


def savings(kb: Optional[Dict[str, Any]] = None,
            calls_per_candidate: float = 3.0) -> Dict[str, Any]:
    """§7 주장 검산 — *"HITL로 불필요한 호출을 차단해"* 가 얼마인가.

    제안서가 일 300~500회를 이 차단으로 정당화했으므로 **수치로 확인한다.**
    차단 1건이 아끼는 것은 실측 평균 LLM 호출 약 3회다.
    """
    K = kb if kb is not None else load()
    n = len(K["pairs"])
    return {"차단_쌍": n, "회당_LLM_호출": calls_per_candidate,
            "아끼는_호출": round(n * calls_per_candidate, 1),
            "취소": K["revoked"],
            "주의": "경보(warn)는 세지 않는다 — 경보는 실행을 막지 않는다"}
