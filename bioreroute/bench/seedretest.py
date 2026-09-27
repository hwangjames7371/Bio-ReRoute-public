# -*- coding: utf-8 -*-
"""표적 재시험 — 두 모델의 판정이 **갈린 쌍만**, **새 seed 로** 다시 묻는다.  (09-24)

## 무엇을 가르나

`sol` 은 TN 에서 `luna` 보다 많이 기각했다. 갈린 27쌍 중 sol 만 기각 22 ·
luna 만 기각 5 · McNemar p = 0.0015 · 두 실행의 입력은 774쌍 전부 같다
(`modelpair_sol_luna.json`). **쌍 단위 우연은 이 p 가 배제한다.** 남은 설명은 둘이다.

    (모델)  sol 이 **원래** 더 엄격하다
    (실행)  그 한 번의 실행 — **seed 42 로 뽑힌 그 답** — 이 엄격했다

실행 한 번으로는 둘을 못 가른다. **같은 모델을 다른 seed 로 다시 뽑아야** 한다.

## ⛔ 그냥 다시 돌리면 **아무것도 안 잰다** — 함정 둘

1. **캐시 키에 seed 가 없다**(`LLM::{모델}::{온도}::{프롬프트}` · `llm.py`).
   우회하지 않으면 1차 답을 그대로 재생한다 — 호출 0 · 일치 100%.
   09-20 에 실제로 그랬다(`재현성결과_0920.md §1`).
2. **지금까지의 실행이 전부 seed 42 였다**(상태 파일 provenance 가 전부
   `seed42`). 우회해도 seed 가 같으면 공급자가 대부분 **같은 답**을 준다
   (apiprobe 5/5). 그러면 «재현됐다» 가 **설계로 보장**된다 — 확인이 아니라 복사다.

그래서 **우회 + 새 seed** 가 둘 다 필요하다. 이 도구는 하나라도 빠지면 멈춘다.

## 왜 전체가 아니라 갈린 쌍만인가 — **토큰 때문이 아니다**

(첫 판은 «예산» 을 이유로 들었는데 틀렸다 — 09-22 에 한도가 3,000만 늘었다 ·
결함 332.) 이 질문의 정보는 **갈린 쌍에 몰려 있다.** 1차에서 같게 판정한 쌍은
새 seed 에서도 대부분 같아 거의 말을 안 한다. 전체를 한 번 더 뽑으면 갈린 쌍은
k = 1 이고(중간 시나리오 검정력 0.43), 갈린 쌍만 세 번 뽑으면 0.945 다. 그리고
시간이 병목이다(전체 1회 약 5시간 · 이것 1~1.5시간). **전체 수치의 seed 복제**는
질문이 달라서 따로 한다(`사전명세_추출복제_0924.md`).

**1차 결과로 골랐는데 괜찮은가 — 괜찮다.** 두 모델이 같다(귀무)면 한 쌍에서
sol·luna 의 새 답은 **같은 분포에서 독립으로 뽑힌 것**이라, 한쪽만 기각한 경우
어느 쪽인지는 동전 던지기다. 쌍을 무엇으로 골랐든 **새로 뽑은 답의 방향**은
공평하다. 그래서 새 답만으로 하는 McNemar 는 유효하다. seed 를 여럿 쓰면
(쌍, seed) 단위로 합쳐도 같은 이유로 유효하다 — 다른 seed 의 추출은 독립이다.

**대가** — 이것이 답하는 것은 «갈린 쌍에서 그 차이가 되풀이되는가» 이다.
«TN 전체의 기각률이 다른가» 가 아니다. 1차에서 일치했다가 새 seed 에서 갈리는
쌍은 안 본다(검정력을 잃을 뿐 치우치지는 않는다).

## ⚠ 누출 차단은 **홀드아웃 전체 행**으로 건다

`gates.set_exclude` 는 **실행에 든 모든 행의 NCT 를 합쳐** 전역으로 막는다
(`run.py` 의 `set_exclude({r["nct"] for r in rows …})`). 27행만 넣고 돌리면
**다른 행의 라벨 출처 논문이 근거로 샌다** — 입력이 1차와 달라진다.
그래서 차단은 전체 행으로 먼저 걸고, 실행만 대상 행으로 한다.

`bench.run` 은 TN 만으로는 안 돌고(`표본이 없다`) 행 필터도 없다. 그래서 이
도구를 따로 둔다. **판정 경로 코드는 안 고친다** — `run.run_config` 를 그대로
부른다(코드 지문 대상 31개 파일 밖이다).

## 실행은 `표적재시험.ps1` 이 한다

인자가 여럿이라 손으로 붙이지 않는다(결함 330 · `CLAUDE.md §5`). 명세는
`사전명세_표적재시험_0924.md` — 스크립트의 값이 명세와 같은지 시험 [180] 이 본다.

⚠ **이름** — 처음에 `retest.py` 로 만들면서 **8월의 «재시험 신뢰도» 도구를 읽지
않고 덮었다**(결함 333). git 에서 그대로 되살렸고(`0caeace2c550`), 이 도구는
`seedretest.py` 다. 시험 [179]⑬ 이 옛 도구가 제자리에 있는지 본다.

## 하위 명령

    prepare   캐시 사본 — sol 이 끝난 시점의 스냅숏 + 다른 모델의 LLM 답 (실캐시는 읽기만)
    targets   갈린 쌍 목록                                   (LLM 0회)
    run       대상 쌍만 B5 로 — 방식 replay | fresh
    gate      재생 관문 — 캐시로 다시 낸 판정이 1차와 같은가     (LLM 0회)
    ping      새로 묻는 길이 사는가 — 1회 · 사본을 안 쓴다
    analyze   주검정 · 보조 지표 · 해석 갈래                   (LLM 0회)
    power     명세의 검정력 표 — 정확 계산                      (LLM 0회)
"""

import argparse
import csv
import hashlib
import json
import os
import sys
import time

from . import modelpair as mp
from .stats import mcnemar, wilson

HOLDOUT = "bench_holdout_matched_sealed.csv"
STRATUM = "A"
CONFIG = "B5"
LIVE = "pubmed_cache.json"
FIRST_SEED = "42"
ALPHA = 0.05

# 상태 파일 한 줄 — `run.py --save-state` 와 **같은 열**이다. 시험 [179] 가 고정한다.
STATE_KEYS = ("name", "drug", "disease", "label", "verdict", "confidence",
              "reason", "f0", "veto", "veto_reason", "trail", "factcheck")


# ── 작은 도구 ─────────────────────────────────────────────────────

def _same(p, q):
    return os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(q))


def sha(path, n=12):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:n]


def fp(obj, n=12):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()[:n]


def write_new(path, obj):
    """**새 파일로만** 쓴다 — 있으면 멈춘다 (결함 330 · `CLAUDE.md §3-3`)."""
    if os.path.exists(path):
        raise FileExistsError("%s 가 이미 있다 — 덮어쓰지 않는다" % path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def load_doc(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def code_fp():
    """판정 경로 코드 지문만 — 캐시(50MB)는 안 읽는다."""
    return mp.fingerprint(cache="__캐시는_안_읽는다__")["코드지문"]


# ── prepare — 캐시 사본 ────────────────────────────────────────────

def prepare(snapshot, live, out, add_models):
    """스냅숏(1차 입력 그대로) 에 **다른 모델의 LLM 답만** 얹은 사본을 만든다.

    - 스냅숏 = sol 이 끝난 시점의 캐시(`…bak_20260923_luna전`). luna 도 **같은
      검색층**에서 돌았다(09-24 실측: 검색 키 14,843 · 값까지 0건 다름).
    - luna 의 1차 답은 스냅숏 뒤에 생겼으므로 실캐시에서 **그 모델의 LLM 키만**
      가져온다. 그래야 luna 도 재생 관문을 지날 수 있다.
    - 실캐시는 **읽기만** 한다. 가짜 0 정리(`zeropurge`)를 먼저 돌렸어도 LLM 키는
      안 건드리므로 결과가 같다.
    """
    if _same(out, live) or _same(out, snapshot):
        raise ValueError("사본 경로가 원본과 같다 — 원본을 건드리지 않는다")
    if os.path.exists(out):
        raise FileExistsError("%s 가 이미 있다 — 덮어쓰지 않는다" % out)
    s = load_doc(snapshot)
    live_d = load_doc(live)
    pre = tuple("LLM::%s::" % m for m in add_models)
    add = {k: v for k, v in live_d.items() if k.startswith(pre) and k not in s}
    s.update(add)
    write_new(out, s)
    f = mp.fingerprint(cache=out)
    return {"스냅숏": sha(snapshot), "더한_LLM": len(add),
            "더한_지문": fp(sorted(add.items())),
            "검색키": f.get("검색키"), "검색키지문": f.get("검색키지문"), "사본": out}


# ── targets — 갈린 쌍 ─────────────────────────────────────────────

def pick(a, b):
    """입력 동일 · TN · 두 실행 다 F0 갈래 아님 · **한쪽만 기각.**"""
    mp.align(a, b)
    out = []
    for i, (x, y) in enumerate(zip(a, b)):
        if x.get("label") != "TN":
            continue
        if mp.f0(x) != mp.f0(y) or mp.inputs(x) != mp.inputs(y):
            continue                      # 입력이 다르면 모델 탓이라 못 한다
        if mp.f0_branch(x) or mp.f0_branch(y):
            continue                      # F0 갈래는 모델과 무관하다
        ra, rb = mp.rejected(x), mp.rejected(y)
        if ra != rb:
            out.append({"idx": i, "name": x.get("name"), "drug": x.get("drug"),
                        "disease": x.get("disease"), "label": "TN",
                        "1차기각": "A" if ra else "B"})
    return out


def target_fp(t):
    return fp([[x["idx"], x["name"], x["1차기각"]] for x in t])


def targets_doc(a_path, b_path):
    a, b = mp.load(a_path), mp.load(b_path)
    t = pick(a, b)
    return {"A": a_path, "B": b_path, "A_sha": sha(a_path), "B_sha": sha(b_path),
            "모델": [mp.model_of(a)[0], mp.model_of(b)[0]], "대상": t,
            "A만": sum(1 for x in t if x["1차기각"] == "A"),
            "B만": sum(1 for x in t if x["1차기각"] == "B"),
            "대상지문": target_fp(t)}


def read_targets(path):
    d = load_doc(path)
    if target_fp(d["대상"]) != d.get("대상지문"):
        raise ValueError("대상 목록이 지문과 다르다 — 손으로 고쳤나")
    return d


def subset(cands, t):
    """1차(전체) 상태에서 대상만 **대상 순서대로** 뽑는다. 이름이 어긋나면 멈춘다."""
    out = []
    for x in t:
        c = cands[x["idx"]]
        if c.get("name") != x["name"] or c.get("label") != x["label"]:
            raise ValueError("%d번째 후보가 대상과 다르다: %r vs %r"
                             % (x["idx"], c.get("name"), x["name"]))
        out.append(c)
    return out


# ── run — 대상 쌍만 ────────────────────────────────────────────────

def check_env(model, seed, mode, max_calls=None, first_seed=FIRST_SEED):
    """환경이 명세와 다르면 **다른 것을 전부** 돌려준다 (첫 것만이 아니라)."""
    from ..io import llm
    bad = []
    if mode not in ("replay", "fresh"):
        return ["방식은 replay | fresh — %r" % mode]
    if llm.MODEL != model:
        bad.append("MODEL %s ≠ %s  (BIOREROUTE_MODEL)" % (llm.MODEL, model))
    odd = {r: llm.model_for(r) for r in llm.ROLE_OF if llm.model_for(r) != model}
    if odd:
        bad.append("역할별 모델이 섞였다 %s  (BIOREROUTE_MODEL_SMALL/STRONG)" % odd)
    if any(x != model for x in llm.FALLBACKS):
        bad.append("대체 사슬 %s — 다른 모델이 답할 수 있다  (BIOREROUTE_FALLBACKS=%s)"
                   % (llm.FALLBACKS, model))
    if str(llm.SEED or "") != str(seed):
        bad.append("SEED %r ≠ %r  (BIOREROUTE_SEED)" % (llm.SEED, str(seed)))
    if mode == "fresh":
        if str(seed) == str(first_seed):
            bad.append("새 seed 가 1차 seed(%s)와 같다 — 재시험이 아니라 복사가 된다" % first_seed)
        if not llm.BYPASS_CACHE:
            bad.append("캐시 우회가 꺼졌다 — 1차 답을 재생한다  (BIOREROUTE_BYPASS_CACHE=1)")
        if max_calls is not None and llm.MAX_CALLS != int(max_calls):
            bad.append("호출 상한 %d ≠ 명세 %d  (BIOREROUTE_MAX_CALLS)"
                       % (llm.MAX_CALLS, int(max_calls)))
    else:
        if llm.BYPASS_CACHE:
            bad.append("재생인데 캐시 우회가 켜졌다 — 새로 묻는다  (BIOREROUTE_BYPASS_CACHE=0)")
        if llm.MAX_CALLS != 0:
            bad.append("재생인데 호출 상한이 %d — 0 이어야 한 번도 안 부른 것이 보장된다"
                       % llm.MAX_CALLS)
    return bad


def holdout_rows(holdout=HOLDOUT, stratum=STRATUM):
    with open(holdout, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if stratum == "all" or r.get("stratum") == stratum]


def select_rows(rows, t):
    sub = []
    for x in t:
        i = x["idx"]
        if i >= len(rows):
            raise ValueError("대상 %d 가 행 수 %d 를 넘는다" % (i, len(rows)))
        r = rows[i]
        name = "%s / %s" % (r["drug"], r["indication"])
        if name != x["name"] or r["label"] != x["label"]:
            raise ValueError("%d번째 행이 대상과 다르다: %r vs %r" % (i, name, x["name"]))
        sub.append(r)
    return sub


def all_ncts(rows):
    """누출 차단에 넣을 NCT — **전체 행**에서. `run.py` 와 같은 식이다."""
    return {r["nct"] for r in rows if str(r.get("nct", "")).startswith("NCT")}


def state_record(c, r):
    return {"name": c.name, "drug": c.drug, "disease": c.disease,
            "label": r["label"],
            "verdict": c.verdict, "confidence": c.confidence,
            "reason": c.reason, "f0": c.f0 or {},
            "veto": c.veto, "veto_reason": c.veto_reason,
            "trail": [{"gate": t.gate, "outcome": t.outcome, "detail": t.detail}
                      for t in c.trail],
            "factcheck": c.factcheck or []}


def run_targets(tpath, save_state, cache_path, model, seed, mode,
                holdout=HOLDOUT, stratum=STRATUM, max_calls=None,
                first_seed=FIRST_SEED):
    if os.path.exists(save_state):
        raise FileExistsError("%s 가 이미 있다 — 덮어쓰지 않는다" % save_state)
    if _same(cache_path, LIVE):
        raise ValueError("실캐시(%s)에 쓰지 않는다 — prepare 로 만든 사본을 줘라" % LIVE)
    if not os.path.exists(cache_path):
        raise FileNotFoundError("캐시 사본이 없다: %s" % cache_path)
    bad = check_env(model, seed, mode, max_calls, first_seed)
    if bad:
        raise RuntimeError("환경이 명세와 다르다:\n  - " + "\n  - ".join(bad))
    td = read_targets(tpath)
    rows = holdout_rows(holdout, stratum)
    sub = select_rows(rows, td["대상"])

    from ..core import gates
    from ..io import cache, llm
    from . import run as R
    R.TIER2 = False                              # 1차와 같게 — 시점 차단 없음
    cache.configure(cache_path)
    cache.load()
    excl = gates.set_exclude(all_ncts(rows)) or {}
    t0 = time.strftime("%Y-%m-%dT%H:%M:%S")
    st = R.run_config(sub, CONFIG, time.strftime("%Y-%m-%d %H:%M"))
    cache.save()
    fs = llm.failure_summary()
    # ── 실패는 **끝내 실패한 호출**만 센다 ──────────────────────────────
    #   `failure_summary()["failed"]` 는 **재시도하다 난 오류**(JSON 파싱 실패
    #   뒤 같은 모델로 다시 물어 성공한 것)까지 센다. 그건 답을 오염시키지
    #   않는다. 끝내 실패한 것은 요약 줄(`summary`)이거나 즉시 반환한 셋이다.
    final = [c for c in llm._CALLS if c.get("error") and (
        c.get("summary") or str(c["error"]).startswith(
            ("BUDGET_EXCEEDED", "NOT_CONFIGURED", "ALL_DEAD")))]
    meta = {"방식": mode, "모델": model, "seed": str(seed), "캐시": cache_path,
            "캐시우회": bool(llm.BYPASS_CACHE), "대상지문": td["대상지문"],
            "행": len(rows), "대상": len(sub),
            "누출차단": {"NCT": len(getattr(gates, "EXCLUDE_NCT", ()) or ()),
                      "PMID": excl.get("pmids"), "미색인": excl.get("no_index"),
                      "조회실패": excl.get("failed")},
            "호출": llm.spent(), "캐시적중": fs.get("cached"), "실패": len(final),
            "재시도오류": fs.get("failed", 0) - len(final),
            "실패사유": fs.get("reasons"), "답한모델": fs.get("served"),
            "토큰": llm.tokens_spent(), "코드지문": code_fp(),
            "도구": sha(os.path.abspath(__file__)), "시작": t0,
            "끝": time.strftime("%Y-%m-%dT%H:%M:%S")}
    write_new(save_state, {"config": CONFIG, "재시험": meta,
                           "candidates": [state_record(c, r)
                                          for c, r in zip(st.candidates, sub)]})
    return meta


# ── gate — 재생 관문 ───────────────────────────────────────────────

def _reading(c):
    return {p: (it.get("direction"), bool(it.get("kept")), it.get("weight"))
            for p, it in mp._items(c).items()}


def reason_key(s):
    """사유 문장에서 **숫자만 지운다**.

    09-24 샌드박스 재생에서 27쌍 중 하나가 사유만 달랐다 —
    `반박 6건 w=9.63` 대 `w=9.64`. 초록마다의 무게는 **여섯 개 다 같았고**
    합이 9.635 라 더하는 순서에 따라 반올림이 갈린 것이다. 무게 자체는
    `_reading` 이 **정확히** 비교하므로, 사유에서는 숫자를 빼고 말만 본다.
    """
    import re
    return re.sub(r"\d+(?:\.\d+)?", "#", str(s or ""))


def gate(t, first, replay):
    """대상마다 **판정 · 확신 · 사유(말) · 입력 · 초록 판독(무게까지)**이 1차와 같은가.

    같은 코드 경로 + 같은 캐시면 전부 같아야 한다. 다르면 그 차이는 LLM 이
    아니라 **코드나 입력**에서 온 것이고, 그러면 새 seed 의 차이도 LLM 탓이라
    못 한다. 그래서 새로 묻기 전에 이것부터 본다.

    ⚠ **라우터는 재생되지 않는다** — 약 12후보씩 **묶어서** 묻기 때문에
    (`gates.py` 의 `todo` 묶음), 27쌍만 돌리면 묶음이 달라져 캐시 키가 다르다.
    호출 상한 0 이라 라우터는 `UNKNOWN` 이 된다. 그래도 판정이 1차와 같으면
    **이 27쌍에서는 라우터가 판정을 움직이지 않는다**는 뜻이다(09-24 샌드박스
    재생: 27쌍 전부 판정·확신 같음). 새 seed 실행에서는 라우터도 새로 묻는다 —
    sol·luna 가 **같은 묶음**을 받으므로 둘 사이 비교는 공평하다.
    """
    f = subset(first, t)
    if len(replay) != len(f):
        return [(-1, "후보 수", ["%d vs %d" % (len(f), len(replay))], "경로")]
    bad = []
    for x, a, b in zip(t, f, replay):
        if mp._key(a) != mp._key(b):
            bad.append((x["idx"], x["name"], ["쌍이 다르다"], "경로"))
            continue
        d = [k for k in ("verdict", "confidence") if a.get(k) != b.get(k)]
        if reason_key(a.get("reason")) != reason_key(b.get("reason")):
            d.append("reason")
        same_in = mp.f0(a) == mp.f0(b) and mp.inputs(a) == mp.inputs(b)
        if not same_in:
            d.append("입력")
        if _reading(a) != _reading(b):
            d.append("초록 판독")
        if d:
            # **입력이 같은데** 결정이 다르면 코드 경로 탓이다 → 멈춘다.
            # 입력이 달라졌으면(망에서 새로 받은 누출 차단 등) 그 쌍은 분석에서
            # 빠진다(`analyze` 가 1차와 입력이 같은 쌍만 쓴다) → 멈추지 않는다.
            bad.append((x["idx"], x["name"], d, "경로" if same_in else "입력"))
    return bad


def gate_verdict(bad, max_drop=3):
    """관문 판정 — 경로 차이 0 · 입력 차이 ≤ max_drop 이면 통과 (명세 §5)."""
    path = [x for x in bad if x[3] == "경로"]
    drop = [x for x in bad if x[3] == "입력"]
    return (not path and len(drop) <= max_drop), path, drop


# ── analyze — 주검정 · 보조 ────────────────────────────────────────

def _seed_tag(c):
    """그 후보의 LLM 답에 적힌 seed 표시들 (예: {'default+seed7(…)'})."""
    return {(it.get("provenance") or {}).get("temperature_used")
            for it in (c.get("factcheck") or []) if it.get("provenance")}


def validity(doc, model, seed, tfp, code_fp=None):
    """새 seed 실행 하나가 **명세대로 돌았나**. 문제를 전부 돌려준다."""
    m = doc.get("재시험") or {}
    c = doc.get("candidates") or []
    bad = []
    want = {"방식": "fresh", "모델": model, "seed": str(seed), "캐시우회": True,
            "대상지문": tfp}
    for k, v in want.items():
        if m.get(k) != v:
            bad.append("%s %r ≠ %r" % (k, m.get(k), v))
    if not m.get("호출"):
        bad.append("호출 0 — 새로 묻지 않았다")
    if m.get("캐시적중"):
        bad.append("캐시 적중 %s — 우회가 새었다" % m.get("캐시적중"))
    if m.get("실패"):
        bad.append("LLM 실패 %s회 %s" % (m.get("실패"), m.get("실패사유")))
    if code_fp and m.get("코드지문") != code_fp:
        bad.append("코드 지문 %s ≠ %s" % (m.get("코드지문"), code_fp))
    served, off = mp.model_of(c)
    if served != model or off:
        bad.append("답한 모델 %s · 대체 %d" % (served, off))
    tags = set().union(*[_seed_tag(x) for x in c]) if c else set()
    wrong = sorted(x for x in tags if not str(x).startswith("default+seed%s(" % seed))
    if wrong:
        bad.append("다른 seed 표시 %s" % wrong[:3])
    return bad


def _rate(k, n):
    lo, hi = wilson(k, n) if n else (None, None)
    return {"k": k, "n": n, "비율": (k / n) if n else None, "CI": [lo, hi]}


def analyze(t, first_a, first_b, fresh_a, fresh_b, alpha=ALPHA):
    """t = 대상 · first_* = 1차(전체) 후보 · fresh_* = 새 seed 실행들(seed 순서 같게).

    **주검정** — (쌍, seed) 단위로 합친 McNemar 정확검정, 양측 α.
      b = A(sol)만 기각 · c = B(luna)만 기각 · 새 seed 의 답만 쓴다.
    """
    if len(fresh_a) != len(fresh_b) or not fresh_a:
        raise ValueError("새 seed 실행 수가 짝이 안 맞는다")
    fa, fb = subset(first_a, t), subset(first_b, t)
    for runs in (fresh_a, fresh_b):
        for r in runs:
            if [mp._key(x) for x in r] != [mp._key(x) for x in fa]:
                raise ValueError("새 실행의 대상 순서가 목록과 다르다")

    def same_in(x, y):
        return mp.f0(x) == mp.f0(y) and mp.inputs(x) == mp.inputs(y)

    ok = [j for j in range(len(t))
          if same_in(fa[j], fb[j])
          and all(same_in(fa[j], r[j]) for r in list(fresh_a) + list(fresh_b))]
    dropped = [t[j]["name"] for j in range(len(t)) if j not in ok]

    b = c = 0
    per_seed = []
    for ra, rb in zip(fresh_a, fresh_b):
        bs = sum(1 for j in ok if mp.rejected(ra[j]) and not mp.rejected(rb[j]))
        cs = sum(1 for j in ok if mp.rejected(rb[j]) and not mp.rejected(ra[j]))
        per_seed.append({"A만": bs, "B만": cs, "p": mcnemar(bs, cs)})
        b += bs
        c += cs
    p = mcnemar(b, c)
    nd = b + c
    lo, hi = wilson(c, nd) if nd else (None, None)
    if p <= alpha and b > c:
        branch = "가"
    elif p <= alpha and b < c:
        branch = "나"
    else:
        branch = "다"

    k = len(fresh_a)
    grp = {"A": [j for j in ok if t[j]["1차기각"] == "A"],
           "B": [j for j in ok if t[j]["1차기각"] == "B"]}
    keep = {}
    for g, idx in grp.items():
        n = len(idx) * k
        keep[g] = {"A기각": _rate(sum(1 for r in fresh_a for j in idx if mp.rejected(r[j])), n),
                   "B기각": _rate(sum(1 for r in fresh_b for j in idx if mp.rejected(r[j])), n)}

    def flips(runs):
        """같은 모델의 seed 끼리 — 대상 판정(기각 여부)이 갈린 비율."""
        out = []
        for u in range(len(runs)):
            for v in range(u + 1, len(runs)):
                d = sum(1 for j in ok if mp.rejected(runs[u][j]) != mp.rejected(runs[v][j]))
                out.append(_rate(d, len(ok)))
        return out

    table = []
    for j in range(len(t)):
        table.append({"name": t[j]["name"], "1차기각": t[j]["1차기각"],
                      "A": [mp.rejected(fa[j])] + [mp.rejected(r[j]) for r in fresh_a],
                      "B": [mp.rejected(fb[j])] + [mp.rejected(r[j]) for r in fresh_b],
                      "분석": j in ok})
    return {"대상": len(t), "분석대상": len(ok), "뺀대상": dropped, "seed수": k,
            "주검정": {"A만": b, "B만": c, "불일치": nd, "p": p, "alpha": alpha,
                    "psi_hat": (c / nd) if nd else None, "psi_ci": [lo, hi],
                    "갈래": branch},
            "seed별": per_seed, "유지": keep,
            "seed간뒤집힘": {"A": flips(fresh_a), "B": flips(fresh_b)}, "표": table}


BRANCH_TEXT = {
    "가": "재현 — sol 의 초과 기각이 새 seed 에서도 되풀이됐다. **모델의 성질**로 쓴다"
          "(단 1차에서 갈린 쌍 한정 · TN 전체 비율의 추정은 아니다).",
    "나": "반대 방향 — 새 seed 에서는 luna 가 더 기각했다. seed 에 따른 흔들림이 "
          "모델 차이를 덮는다. 1차 차이를 모델의 성질로 **쓰지 않는다**.",
    "다": "가르지 못했다 — 1차 차이를 모델의 성질로 **쓰지 않는다**. "
          "«seed 42 한 번에서 관측된 차이» 로만 적는다.",
}


# ── power — 정확 계산 ──────────────────────────────────────────────

def power_exact(units, alpha=ALPHA):
    """units = [(q, r)] — 한 단위가 «A만 기각» 일 확률 q, «B만 기각» 일 확률 r.

    (b, c) 의 결합분포를 합성곱으로 **정확히** 만들고, **b > c 이면서 p ≤ α** 인
    칸의 확률을 더한다(방향까지 맞아야 «재현» 이다). 몬테카를로를 안 쓴다 —
    명세의 수가 실행마다 흔들리면 안 된다.
    """
    dist = {(0, 0): 1.0}
    for q, r in units:
        nd = {}
        for (b, c), pr in dist.items():
            for db, dc, w in ((1, 0, q), (0, 1, r), (0, 0, 1.0 - q - r)):
                if w > 0:
                    key = (b + db, c + dc)
                    nd[key] = nd.get(key, 0.0) + pr * w
        dist = nd
    return sum(pr for (b, c), pr in dist.items() if b > c and mcnemar(b, c) <= alpha)


# 시나리오 — (sol, luna) 의 기각 확률. 앞은 1차에 **sol 만** 기각한 쌍,
#   뒤는 1차에 **luna 만** 기각한 쌍. 명세 §4 가 이 표를 인용한다.
SCENARIOS = [
    ("강함", (0.85, 0.15), (0.40, 0.60)),
    ("중간", (0.70, 0.30), (0.40, 0.60)),
    ("약함", (0.60, 0.40), (0.45, 0.55)),
    ("귀무", (0.30, 0.30), (0.50, 0.50)),
]


def scenario_units(n_a, n_b, pa, pb, k):
    qa = (pa[0] * (1 - pa[1]), pa[1] * (1 - pa[0]))
    qb = (pb[0] * (1 - pb[1]), pb[1] * (1 - pb[0]))
    return [qa] * (n_a * k) + [qb] * (n_b * k)


def power_table(n_a=22, n_b=5, ks=(1, 2, 3, 4), alpha=ALPHA):
    out = []
    for name, pa, pb in SCENARIOS:
        out.append((name, pa, pb,
                    [round(power_exact(scenario_units(n_a, n_b, pa, pb, k), alpha), 3)
                     for k in ks]))
    return out


# ── ping — 새로 묻는 길 ────────────────────────────────────────────

def ping(model):
    """한 번 묻는다. **캐시를 안 읽고**(우회 필수) · **디스크에 안 쓴다**."""
    from ..io import cache, llm
    if not llm.BYPASS_CACHE:
        raise RuntimeError("ping 은 우회를 켜고 한다 — 캐시에 남은 옛 답이 «산다» 로 보이면 안 된다")
    cache.configure("_재시험_ping_없는파일.json", enabled=False)
    r = llm.complete("Reply with the single word OK.", purpose="ping")
    p = r.get("provenance") or {}
    return {"ok": bool(r.get("ok")), "served": p.get("served_by"), "model": model,
            "seed": p.get("temperature_used"), "err": str(r.get("error"))[:120]}


# ── CLI ───────────────────────────────────────────────────────────

def _print_analysis(res):
    m = res["주검정"]
    print("=" * 76)
    print("표적 재시험 — 갈린 쌍을 새 seed 로  (LLM 0회 · 분석만)")
    print("=" * 76)
    print("  대상 %d · 분석 %d · seed %d개%s" % (
        res["대상"], res["분석대상"], res["seed수"],
        (" · 입력이 달라 뺌 %s" % res["뺀대상"]) if res["뺀대상"] else ""))
    lo, hi = m["psi_ci"]
    print("\n[주검정]  (쌍, seed) 합산 McNemar 정확 · 양측 α=%.2f" % m["alpha"])
    print("  A(sol)만 기각 %d · B(luna)만 기각 %d · p = %.4g · ψ̂ = %s [%s–%s]"
          % (m["A만"], m["B만"], m["p"],
             "%.2f" % m["psi_hat"] if m["psi_hat"] is not None else "—",
             "%.2f" % lo if lo is not None else "—", "%.2f" % hi if hi is not None else "—"))
    print("  갈래 (%s) — %s" % (m["갈래"], BRANCH_TEXT[m["갈래"]]))
    print("\n[seed 별]  " + " · ".join("A만 %d B만 %d p=%.3g" % (s["A만"], s["B만"], s["p"])
                                      for s in res["seed별"]))
    for g, name in (("A", "1차 sol 만 기각"), ("B", "1차 luna 만 기각")):
        v = res["유지"][g]
        print("[%s 쌍] sol 기각 %s/%s · luna 기각 %s/%s" % (
            name, v["A기각"]["k"], v["A기각"]["n"], v["B기각"]["k"], v["B기각"]["n"]))
    for g in ("A", "B"):
        print("[seed 간 뒤집힘 · %s] %s" % ("sol" if g == "A" else "luna", " · ".join(
            "%d/%d" % (x["k"], x["n"]) for x in res["seed간뒤집힘"][g])))


def main(argv=None):
    ap = argparse.ArgumentParser(description="갈린 쌍만 새 seed 로 다시 묻는다")
    sp = ap.add_subparsers(dest="cmd")

    p = sp.add_parser("prepare")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--live", default=LIVE)
    p.add_argument("--out", required=True)
    p.add_argument("--add-llm", nargs="+", required=True, help="실캐시에서 가져올 모델 LLM 키")

    p = sp.add_parser("targets")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--out", required=True)

    p = sp.add_parser("run")
    p.add_argument("targets")
    p.add_argument("--save-state", required=True)
    p.add_argument("--cache", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--seed", required=True)
    p.add_argument("--mode", required=True, choices=("replay", "fresh"))
    p.add_argument("--max-calls", type=int, default=None)
    p.add_argument("--holdout", default=HOLDOUT)

    p = sp.add_parser("gate")
    p.add_argument("targets")
    p.add_argument("first")
    p.add_argument("replay")

    p = sp.add_parser("ping")
    p.add_argument("--model", required=True)

    p = sp.add_parser("analyze")
    p.add_argument("targets")
    p.add_argument("--first", nargs=2, required=True, metavar=("A", "B"))
    p.add_argument("--fresh-a", nargs="+", required=True)
    p.add_argument("--fresh-b", nargs="+", required=True)
    p.add_argument("--seeds", nargs="+", required=True)
    p.add_argument("--models", nargs=2, required=True, metavar=("A", "B"))
    p.add_argument("--code-fp", default=None)
    p.add_argument("--json", default=None)

    p = sp.add_parser("power")
    p.add_argument("--ks", nargs="+", type=int, default=[1, 2, 3, 4])

    a = ap.parse_args(argv)
    try:
        if a.cmd == "prepare":
            r = prepare(a.snapshot, a.live, a.out, a.add_llm)
            print(json.dumps(r, ensure_ascii=False))
            print("검색 키 %s개 · 지문 %s · 더한 LLM %s" % (r["검색키"], r["검색키지문"], r["더한_LLM"]))
            return 0
        if a.cmd == "targets":
            d = targets_doc(a.a, a.b)
            write_new(a.out, d)
            print("대상 %d (A만 %d · B만 %d) · 지문 %s → %s"
                  % (len(d["대상"]), d["A만"], d["B만"], d["대상지문"], a.out))
            return 0
        if a.cmd == "run":
            m = run_targets(a.targets, a.save_state, a.cache, a.model, a.seed, a.mode,
                            holdout=a.holdout, max_calls=a.max_calls)
            print("RUN_OK 방식=%s 모델=%s seed=%s 호출=%s 적중=%s 실패=%s 토큰=%s"
                  % (m["방식"], m["모델"], m["seed"], m["호출"], m["캐시적중"], m["실패"],
                     (m["토큰"] or {}).get("총토큰")))
            return 0
        if a.cmd == "gate":
            t = read_targets(a.targets)["대상"]
            bad = gate(t, mp.load(a.first), mp.load(a.replay))
            ok, path, drop = gate_verdict(bad)
            for x in path:
                print("  X 경로 %s" % (x[:3],))
            for x in drop:
                print("  - 입력 %s  (분석에서 빠진다)" % (x[:3],))
            print("GATE_%s 경로차이 %d · 입력차이 %d / 대상 %d"
                  % ("OK" if ok else "FAIL", len(path), len(drop), len(t)))
            return 0 if ok else 3
        if a.cmd == "ping":
            r = ping(a.model)
            print("PING=%s" % r["ok"])
            print("SERVED=%s" % r["served"])
            print("SEEDTAG=%s" % r["seed"])
            print("ERR=%s" % r["err"])
            return 0 if (r["ok"] and r["served"] == a.model) else 4
        if a.cmd == "analyze":
            td = read_targets(a.targets)
            t = td["대상"]
            if len(a.fresh_a) != len(a.seeds) or len(a.fresh_b) != len(a.seeds):
                print("  X seed 수와 실행 파일 수가 다르다")
                return 2
            docs_a = [load_doc(x) for x in a.fresh_a]
            docs_b = [load_doc(x) for x in a.fresh_b]
            bad = []
            for s, d in zip(a.seeds, docs_a):
                bad += ["A seed %s — %s" % (s, x) for x in validity(d, a.models[0], s, td["대상지문"], a.code_fp)]
            for s, d in zip(a.seeds, docs_b):
                bad += ["B seed %s — %s" % (s, x) for x in validity(d, a.models[1], s, td["대상지문"], a.code_fp)]
            res = analyze(t, mp.load(a.first[0]), mp.load(a.first[1]),
                          [d["candidates"] for d in docs_a], [d["candidates"] for d in docs_b])
            res["유효성"] = bad
            _print_analysis(res)
            if bad:
                print("\n  🔴 **명세대로 돌지 않은 실행이 있다 — 이 결과는 무효다** (명세 §6)")
                for x in bad:
                    print("    - %s" % x)
            if a.json:
                write_new(a.json, res)
                print("\n→ %s" % a.json)
            return 0 if not bad else 5
        if a.cmd == "power":
            print("시나리오 (1차 sol만 22쌍의 sol·luna 기각확률 | 1차 luna만 5쌍)   k = seed 수")
            for name, pa, pb, pw in power_table(ks=tuple(a.ks)):
                print("  %-4s %s | %s   " % (name, pa, pb)
                      + " · ".join("k=%d %.3f" % (k, v) for k, v in zip(a.ks, pw)))
            return 0
    except (FileExistsError, FileNotFoundError, ValueError, RuntimeError) as e:
        print("  🔴 %s" % e)
        return 2
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
