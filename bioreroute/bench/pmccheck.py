# -*- coding: utf-8 -*-
"""PMC 전문 커버리지 실측 — **F 를 할지 말지를 30분에 정한다** (LLM 0회)

`본선_보완계획.md §F` 가 «전문 읽기»를 이렇게 적었다 —

  > 초록은 **팔기 위해 쓴 글**이고 Limitations 는 **심사를 통과하려고
  > 쓴 글**이다. 반박을 찾는 도구라면 뒤쪽을 읽어야 한다.

맞는 말이지만 **그 앞에 답해야 할 것이 있다** — *"우리가 실제로 읽은
논문 중 몇 편이나 전문이 열리나?"* 30~50% 라는 수는 **일반 통계이지
우리 표본의 실측이 아니다.** 이 도구가 그걸 잰다.

  py -m bioreroute.bench.pmccheck --probe               # ⚠ **먼저 이것부터**
  py -m bioreroute.bench.pmccheck --fetch 60 --out 결과.json

## ⚠ 두 층을 섞지 않는다

    elink (pubmed→pmc)   PMC 에 **레코드가 있는가**   → 상한 (45.2% 실측)
    efetch (`--fetch`)   **본문을 받아 절을 뽑을 수 있나** → 실제 (80% 실측)

PMC 에 있어도 본문이 안 오는 것이 있다(구독 전용 12/60). `--fetch`
없이 나온 수는 **상한**이고, 그렇게 적는다.

⚠ `--oa`(OA Service)는 **보조**로만 남겼다. 구 주소가 404 이고, 그쪽은
*"다운로드 패키지가 있나"* 를 답할 뿐 **우리가 알아야 하는 «절을 뽑을
수 있나»가 아니다.**

## ⚠ 「조회 실패」와 「PMC 없음」을 섞지 않는다 — 결함 35 계열

09-01 에 `binding.py` 에서 *"네트워크가 끊겼을 때 «결합 근거 없음»으로
세면 **망 장애가 «발견»이 된다**"* 를 겪었다. 여기도 같다 — 응답을 못
받은 것을 **«전문 없음»으로 세면 커버리지가 거짓으로 낮아진다.**
셋을 따로 센다: `있음` · `없음` · **`조회불가`**.

## ⚠ 파서를 추측으로 쓰지 않는다

내 개발 환경은 NCBI 가 막혀 있어 **응답 실물을 못 본다**(`CLAUDE.md §5`).
그래서 `--probe` 가 **키 구조만 찍는다.** 09-01 `binding.py` 에서 같은
방식으로 파서를 맞췄고, 그때 승우가 한 번 돌려 준 것으로 확정했다.
"""

from __future__ import annotations

from .. import config as _config          # noqa: F401  (.env 먼저)

import argparse
import collections
import json
import random
import sys
import time
from typing import Any, Dict, List, Optional

from ..io import cache, fulltext, sources

# ⛔ 09-13 실측 — **200은 URL 이 너무 길다.**
#
#   `&id=` 를 개별로 반복해야 id 별 결과가 오는데(위 `_elink` 주석),
#   200건이면 URL 이 **2,600자**를 넘는다. NCBI 가 `IncompleteRead(0 bytes)`
#   로 끊었다 — **9배치 전부 실패**했고 **마지막 102건짜리 배치만 통과**했다.
#   E-utilities 문서도 *"UID 가 약 200개를 넘으면 POST 를 쓰라"* 고 적는다.
#
#   ⚠ 그때 «조회불가»를 «없음»으로 셌다면 `9/1902 = 0.5%` 가 나와
#     **«F 를 접는다» 는 결론이 거짓 근거 위에 섰을 것**이다. 분모에서
#     뺀 덕에 *"못 물어봤다"* 가 화면에 남았다 — 결함 35 방어가 작동했다.
# ⚠ 09-15 · 배치·재시도·매핑은 **`io/fulltext` 하나가 갖는다.**
#   여기 사본을 두면 나중에 한쪽만 고치는 사고가 난다(결함 98·222).
OA_URLS = [
    # 09-13 — 구 주소가 404 다. PMC 가 별도 도메인으로 옮겨 갔다.
    "https://pmc.ncbi.nlm.nih.gov/utils/oa/oa.fcgi",
    "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi",
]


def our_pmids(limit: Optional[int] = None) -> List[str]:
    """**우리가 실제로 읽은** PMID. 캐시의 초록 키가 정본이다.

    일반 통계(«PMC OA 30~50%»)가 아니라 **우리 표본**을 재는 것이
    이 도구의 요점이다.
    """
    cache.load()
    out = sorted({k.split("::")[-1] for k in cache._STORE
                  if k.startswith("ABS::")} - {""})
    out = [p for p in out if p.isdigit()]
    return out[:limit] if limit else out


def probe(pmids: List[str]) -> int:
    """응답 **키 구조만** 찍는다. 파서를 맞추기 위한 것.

    ⚠ **표본을 앞에서 자르지 않는다** — 09-13. 캐시 키를 문자열로 정렬해
      앞 3개를 쓰면 **가장 오래된 논문**만 뽑힌다(PMID 가 작을수록 옛것).
      실제로 `1000510`·`10022407` 같은 1970~90년대 논문이 나왔고 셋 다
      전문이 없었다. **그러면 파서가 맞는지 안 맞는지를 못 가른다** —
      «0건» 이 «없음» 인지 «못 읽음» 인지 구별이 안 되기 때문이다.

      그래서 **가장 최근 것 위주로** 섞는다. 최근 논문에서도 0이면
      그때는 진짜 파서를 의심한다.
    """
    nums = sorted(pmids, key=int)
    sample = nums[-3:] + nums[:1]          # 최근 3 + 가장 옛것 1(대조)
    print("⚠ 표본 = **최근 3 + 옛것 1**. 최근에서도 0건이면 파서를 의심해라.")
    print("PMID 3건으로 elink 응답 구조를 본다 — %s" % ", ".join(sample))
    r = fulltext._elink(sample)
    if not r["ok"]:
        print("⛔ 조회 실패: %s" % r["error"])
        print("   ⚠ 이건 «PMC 없음» 이 아니라 **«확인 실패»** 다.")
        return 1
    d = r["data"]
    print("\n최상위 키: %s" % list(d) if isinstance(d, dict) else type(d).__name__)
    try:
        print("linksets %d개  ← **입력 %d건과 같아야 한다**"
              % (len(d.get("linksets") or []), len(sample)))
        for j, ls in enumerate(d.get("linksets") or []):
            ids = ls.get("ids") or []
            flag = "" if len(ids) == 1 else "  ⛔ **묶여 있다 — 못 가른다**"
            print("  [%d] ids=%s%s" % (j, ids, flag))
            for db in ls.get("linksetdbs") or []:
                ok = "✅" if db.get("linkname") == fulltext.LINKNAME else "⛔ 이건 아니다"
                print("      dbto=%s · linkname=%s · links %d건   %s"
                      % (db.get("dbto"), db.get("linkname"),
                         len(db.get("links") or []), ok))
    except Exception as e:
        print("⚠ 구조가 예상과 다르다: %s" % e)
        print(json.dumps(d, ensure_ascii=False)[:600])
        return 1
    p = fulltext._parse_links(d)
    print("\n파서 결과: %s" % json.dumps(p, ensure_ascii=False)[:200])
    print("→ 위가 {pmid: [pmcid…]} 로 보이면 파서가 맞다.")

    # ── OA Service 도 **실물을 보고** 판정한다 (09-13) ──────────────
    #   `elink` 에서 `linkname` 을 안 걸어 인용 수를 전문 수로 셀 뻔했다.
    #   **같은 실수를 OA 쪽에서 반복하지 않는다.**
    pmc = [v[0] for v in p.values() if v]
    print()
    if not pmc:
        print("⚠ 이 표본엔 PMC 레코드가 없어 **OA 응답은 못 봤다.**")
        print("   `--n` 을 늘려 다시 돌리면 OA 구조까지 확인된다.")
        return 0
    cid = pmc[0]

    # ⭐ **본문을 실제로 받아 본다** — 이게 F 의 값을 직접 잰다.
    print("본문 efetch — PMC%s" % cid)
    ft = _fulltext(cid)
    print("  판정 **%s** · %s" % (ft["판정"], {k: v for k, v in ft.items()
                                              if k != "판정"}))
    if ft["판정"] == "본문있음":
        print("  → 본문이 온다. `절` 에 limitation/discussion 이 있으면")
        print("     **F 가 뽑을 것이 실재한다**는 뜻이다.")
    elif ft["판정"] == "본문없음":
        print("  → 초록만 온다(구독 전용). **이 건은 F 대상이 아니다.**")
    else:
        print("  ⚠ **«없음» 이 아니라 «확인 실패»** 다 — 분모에서 뺀다.")

    # OA Service 는 보조로만 본다. 주소가 바뀌어 404 가 났었다.
    print()
    print("OA Service(보조) — PMC%s" % cid)
    print("  판정: **%s**   ← `None` 이면 두 주소 다 실패한 것"
          % {True: "OA 가능", False: "OA 아님", None: "확인 실패"}[_oa_ok(cid)])
    return 0


def _oa_ok(pmcid: str) -> Optional[bool]:
    """OA Service — **전문을 써도 되나.** 모르면 `None`(≠ False).

    ⚠ 09-13 · 구 주소가 **404** 다. PMC 가 `pmc.ncbi.nlm.nih.gov` 로
      옮겨 갔다. **둘 다 시도**하고, 그래도 안 되면 `None` 이다 —
      «OA 아님» 으로 세지 않는다.
    """
    for base in OA_URLS:
        sources.throttle()
        try:
            xml = sources._get_xml(base + "?id=PMC" + str(pmcid).lstrip("PMC"))
        except Exception:
            continue
        if "<error" in xml:
            return False                   # 명시적 «OA 아님»
        return "<link" in xml or "href=" in xml
    return None


# ── ⭐ 09-13 · **본문을 실제로 받아 본다** ─────────────────────────
#
#   OA Service 는 *"다운로드 패키지가 있나"* 를 답한다. 우리가 알아야
#   하는 것은 *"본문 XML 을 받아 **Limitations 를 뽑을 수 있나**"* 다.
#   **`efetch` 가 그걸 직접 답하고, 우리가 이미 쓰는 API 다**(초록도
#   `efetch` 로 받는다). 새 자료원이 0개라는 뜻이다.
#
#   그리고 한 번에 **F 의 진짜 값**까지 나온다 — 본문이 와도 그 안에
#   Limitations 절이 없으면 F 는 값이 없다.
#
#   ⚠ 09-15 · 여기 있던 `SECTIONS` 상수를 **지웠다.** 절 목록은
#     `io/fulltext.WANT` 하나가 갖는다 — 두 곳에 두면 한쪽만 고친다.


def _fulltext(pmcid: str) -> Dict[str, Any]:
    """PMC 본문을 받아 **실제로 절을 뽑아 본다.**

    ⚠ 09-14 · 처음엔 `"limitation" in xml.lower()` 로 **문자열만** 봤다.
      그건 *"그 낱말이 어딘가 있다"* 이지 *"절을 뽑을 수 있다"* 가
      아니다 — 참고문헌 제목에 걸려도 참이 된다. **`io/fulltext` 의
      실제 추출기를 태운다.** 그래야 «절 추출 실패 30%» 라는 명세 §5
      반증 조건을 잴 수 있다.
    """
    r = fulltext.limitations(pmcid)
    v = r.get("판정")
    if v == "추출됨":
        return {"판정": "본문있음", "절": [r["절"]],
                "종류": r.get("종류"),          # 한계절 / 한계문단 / 논의뒤
                "글자수": r["글자수"],
                # ⚠ **실제로 넣는 글자수**는 상한에 걸린다. 원본 길이로
                #   토큰을 추정하면 09-14처럼 **부풀려진다.**
                "넣는글자수": min(r["글자수"], fulltext.MAX_CHARS),
                "잘림": r.get("잘림"), "본문절": r.get("본문절")}
    if v == "절없음":
        return {"판정": "본문있음", "절": [], "본문절": r.get("본문절")}
    if v == "본문없음":
        return {"판정": "본문없음", "길이": r.get("길이")}
    return {"판정": "조회실패", "왜": r.get("왜")}


def run(pmids: List[str], oa: bool = False) -> Dict[str, Any]:
    # ⚠ 09-15 · 매핑·재시도 로직을 **`io/fulltext` 하나로 모았다.**
    #   여기 사본을 두면 «같은 방어가 두 곳» 이 되고 그게 결함 98·222 다.
    #   나중에 한쪽만 고치는 사고가 정확히 그 자리에서 난다.
    def _tick(done, total, nf, nn, nu, err):
        if err:
            print("  ⚠ 조회 실패 — %s" % str(err)[:50])
        print("  %d/%d … PMC 있음 %d · 없음 %d · 조회불가 %d"
              % (done, total, nf, nn, nu))

    m = fulltext.pmc_ids(pmids, progress=_tick)
    pmc_of = m["매핑"]
    have = list(pmc_of)
    none_ = m["PMC없음"]
    unreach = m["조회불가"]

    out: Dict[str, Any] = {"전체": len(pmids), "PMC있음": len(have),
                           "PMC없음": len(none_), "조회불가": len(unreach),
                           "pmids_pmc": have[:50], "pmc맵": pmc_of}
    return out


def fetch_sample(pmc_ids: List[str], n: int = 60, seed: int = 42) -> Dict[str, Any]:
    """PMC 레코드 중 **무작위 N건의 본문을 실제로 받아 본다.**

    ⚠ **앞에서 자르지 않는다** — 09-13에 그러다 연식 편향에 두 번 물렸다
      (문자열 정렬 → 1970년대만 / URL 절단 → 최신만). `seed` 를 고정해
      **재현 가능한 무작위**로 뽑는다.
    """
    rng = random.Random(seed)
    pool = list(pmc_ids)
    rng.shuffle(pool)
    sample = pool[:n]
    got = blocked = failed = 0
    with_sec = 0
    chars: List[int] = []          # 09-14 — **토큰 예측의 원자료**
    cut = 0
    kinds: Dict[str, int] = collections.Counter()   # 한계절/한계문단/논의뒤
    rows = []
    for i, c in enumerate(sample, 1):
        r = _fulltext(c)
        rows.append({"pmc": c, **r})
        if r["판정"] == "본문있음":
            got += 1
            if r.get("절"):
                with_sec += 1
                if isinstance(r.get("넣는글자수"), int):
                    chars.append(r["넣는글자수"])      # **실제 들어갈 양**
                if r.get("잘림"):
                    cut += 1
                kinds[r.get("종류") or "?"] += 1
        elif r["판정"] == "본문없음":
            blocked += 1
        else:
            failed += 1
        if i % 20 == 0 or i == len(sample):
            print("  %d/%d … 본문 %d · 막힘 %d · 실패 %d · 절추출 %d"
                  % (i, len(sample), got, blocked, failed, with_sec))
    srt = sorted(chars)
    return {"표본": len(sample), "본문있음": got, "본문없음": blocked,
            "조회실패": failed, "절있음": with_sec, "seed": seed,
            "절_글자수_중앙": srt[len(srt) // 2] if srt else None,
            "절_글자수_최대": srt[-1] if srt else None,
            "상한에_잘림": cut, "종류별": dict(kinds), "사례": rows[:10]}


def _report(r: Dict[str, Any]) -> None:
    n, have = r["전체"], r["PMC있음"]
    askable = n - r["조회불가"]              # 실제로 물어본 것
    print()
    print("=" * 70)
    print("PMC 전문 커버리지 — 우리가 실제로 읽은 논문 %d편" % n)
    print("=" * 70)
    print("  PMC 레코드 있음   %5d" % have)
    print("  PMC 없음          %5d" % r["PMC없음"])
    print("  ⚠ 조회불가        %5d   ← **«없음»이 아니다**" % r["조회불가"])
    if askable:
        print()
        print("  **상한 커버리지 %.1f%%** (%d / 물어본 %d)"
              % (100.0 * have / askable, have, askable))
        print("  ⚠ «상한» 인 이유 — PMC 에 레코드가 있어도 **본문을 써도**")
        print("     **되는지는 다른 문제**다. `--oa` 가 그걸 잰다.")
    if "OA가능" in r:
        print()
        print("  OA 전문 가능      %5d" % r["OA가능"])
        print("  OA 아님           %5d" % r["OA아님"])
        print("  ⚠ OA 조회불가     %5d" % r["OA조회불가"])
        d = r["OA가능"] + r["OA아님"]
        if d:
            print()
            print("  **실제 커버리지 %.1f%%** (%d / 확인된 %d)"
                  % (100.0 * r["OA가능"] / d, r["OA가능"], d))
    print()
    print("  ── F(전문 읽기) 판단 기준 — **결과 보기 전에 적는다** ──")
    print("   ≥30%  하면 값이 크다. Limitations·Methods 두 절만 뽑는다")
    print("   10~30% 표본이 작아 «사례»로만 쓴다. 수치 주장 안 한다")
    print("   <10%  **접는다.** 이유를 수치로 적고 로드맵으로 옮긴다")
    print("=" * 70)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="PMC 전문 커버리지 실측 — F 를 할지 정한다 (LLM 0회)")
    ap.add_argument("--n", type=int, default=None, help="앞에서 N건만")
    ap.add_argument("--probe", action="store_true",
                    help="⚠ **먼저 이것부터** — elink 응답 키 구조만 찍는다")
    ap.add_argument("--oa", action="store_true",
                    help="OA Service 까지 확인 (건마다 1회 — 느리다)")
    ap.add_argument("--fetch", type=int, default=0, metavar="N",
                    help="⭐ PMC 레코드 중 **무작위 N건의 본문을 실제로 "
                         "받아 본다.** OA 여부와 Limitations 절 존재를 "
                         "한 번에 잰다 (권장 60)")
    ap.add_argument("--out", default=None, help="결과 저장 경로")
    a = ap.parse_args(argv)

    pmids = our_pmids(a.n)
    if not pmids:
        print("⛔ 캐시에 초록(ABS::) 이 없다. 벤치를 한 번 돌린 뒤에 써라.")
        return 2
    print("우리가 읽은 PMID **%d건** (캐시 `ABS::` 기준)" % len(pmids))

    if a.probe:
        return probe(pmids)

    r = run(pmids, oa=a.oa)
    _report(r)

    if a.fetch:
        pmc = list((r.get("pmc맵") or {}).values())
        if not pmc:
            print("\n⛔ PMC 레코드가 없어 본문 시도를 건너뛴다.")
        else:
            print()
            print("=" * 70)
            print("본문 실측 — PMC %d건 중 **무작위 %d건**(seed 42)을 받아 본다"
                  % (len(pmc), min(a.fetch, len(pmc))))
            print("=" * 70)
            f = fetch_sample(pmc, n=a.fetch)
            r["본문실측"] = f
            ok = f["본문있음"]
            asked = f["표본"] - f["조회실패"]
            print()
            print("  본문 받음     %3d" % ok)
            print("  구독 전용     %3d" % f["본문없음"])
            print("  ⚠ 조회 실패   %3d   ← **«없음» 이 아니다**" % f["조회실패"])
            if asked:
                print()
                print("  **본문 접근률 %.1f%%** (%d / 물어본 %d)"
                      % (100.0 * ok / asked, ok, asked))
                print("  → 전체 %d편 기준 **약 %d편**이 열린다"
                      % (r["전체"], round(r["PMC있음"] * ok / max(1, asked))))
            if ok:
                print()
                print("  그중 **절을 실제로 뽑아낸 것 %d건** (%.0f%%)"
                      % (f["절있음"], 100.0 * f["절있음"] / ok))
                fail_rate = 100.0 * (ok - f["절있음"]) / ok
                print("  절 추출 실패 %.0f%%   ← 명세 §5: **30%% 넘으면 접는다**"
                      % fail_rate)
                if f.get("종류별"):
                    print()
                    print("  ⭐ **어떻게 얻었나** — 근거의 질이 다르다")
                    for k, label in (("한계절", "독립 «Limitations» 절 (가장 강하다)"),
                                     ("한계문단", "논의에서 **단서로 골라낸 문단**"),
                                     ("논의뒤", "단서 없어 **논의 뒤쪽**만 (가장 약하다)")):
                        n_ = f["종류별"].get(k, 0)
                        if n_:
                            print("     %-6s %3d건  %s" % (k, n_, label))
                if f.get("절_글자수_중앙"):
                    med = f["절_글자수_중앙"]
                    print()
                    print("  넣는 글자수(상한 %d 적용 **후**) — 중앙 %s · 최대 %s"
                          % (fulltext.MAX_CHARS, med, f["절_글자수_최대"]))
                    print("  원본이 상한에 잘린 것 %d건" % f["상한에_잘림"])
                    print("  → 후보당 추가 토큰 **약 %d**" % int(med * 0.67))
                    print("     ⚠ 09-14 첫 판은 **원본 길이**로 계산해 부풀렸다.")
                    print("     명세 §6 예측은 «후보당 2~4배». **이 수치로 검산해라.**")
    if a.out:
        # ⚠ **맨 `json.dump` 를 쓰지 않는다** — 09-16 시험 [129]가 잡았다.
        #   09-15에 이 줄을 맨손으로 썼고 `bench/` 의 맨 dump 가 24 → 25로
        #   늘었다. 결함 223(`--out` 이 앞 판을 지웠다)의 방어가
        #   `io/safeio` 한 곳에 있는데 **새 코드가 그 통로를 비켜 갔다.**
        #   `CLAUDE.md` — *"안내문은 방어가 아니다. 구조로 막아야 한다."*
        from ..io.safeio import save_json
        w = save_json(r, a.out, indent=1)
        if w.get("원본유지"):
            print("⚠ **백업이 실패해 원본을 안 덮었다** — %s (%s)"
                  % (w.get("경로"), w.get("상태")))
        else:
            print("저장 %s" % w.get("경로", a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
