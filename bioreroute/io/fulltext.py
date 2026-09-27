# -*- coding: utf-8 -*-
"""PMC 전문에서 **Limitations 절만** 뽑는다 (제안서 §2.3 · `사전명세_전문읽기.md`)

  > 초록은 **팔기 위해 쓴 글**이고 Limitations 는 **심사를 통과하려고
  > 쓴 글**이다. 반박을 찾는 도구라면 뒤쪽을 읽어야 한다.

## ⛔ 본문을 통째로 넣지 않는다

09-13 실측에서 PMC 본문 한 편이 **147 KB** 였다(초록은 1~2 KB).
그대로 넣으면 토큰이 **50배**가 되고, 그러면 배점 15(«크레딧 대비
결과»)를 **우리가 스스로 깎는다.** 명세가 절 추출을 선택이 아니라
**필수**로 못 박은 이유다.

**절 추출이 실패하면 그 건은 건너뛴다.** 통째로 넣는 폴백을 두지
않는다 — 폴백이 있으면 «실패» 가 조용히 «비싼 성공» 이 된다.

## ⛔ 판정 넷을 섞지 않는다 — 결함 35 계열

    추출됨     절을 찾았다
    절없음     본문은 읽었는데 그 절이 **없다**
    본문없음   `<body>` 가 없다 — 구독 전용의 모습
    조회실패   못 받았거나 XML 이 깨졌다   ← **«없음» 이 아니다**

뒤 둘을 «반박 근거 없음» 으로 세면 **망 장애가 «발견» 이 된다.**
09-01 `binding.py` 에서 겪었고 09-13 `pmccheck` 에서 두 번 더 겪었다.
"""

from __future__ import annotations

from .. import config as _config          # noqa: F401  (.env 먼저)

import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from . import cache, sources

# 명세 §2 — 뽑을 절과 **우선순위**. 앞이 이긴다.
WANT = (
    ("limitations", ("limitation",)),
    ("strengths_limitations", ("strength and limitation",
                               "strengths and limitations")),
    ("discussion", ("discussion",)),
)
MAX_CHARS = 4000          # 명세 §2 — 절당 상한. 넘으면 자르고 **기록한다**
CACHE_PRE = "PMCXML::"    # ⚠ 원본 XML — **기본으로 안 쓴다**(아래 KEEP_XML)
SEC_PRE = "PMCSEC::"      # 뽑은 절만. 한 편 ~4 KB

# 개발용 — 파서를 고쳐 재추출할 때만 켠다. **켜면 캐시가 20배로 뛴다.**
KEEP_XML = (os.environ.get("BIOREROUTE_PMC_KEEP_XML") or "").strip() in ("1", "true")

# ── ⛔ 09-14 실물이 설계 결함을 드러냈다 ──────────────────────────
#
#   표본 10건에서 뽑힌 절이 **전부 `discussion`** 이었다. `limitations`
#   **0건.** 독립 «Limitations» 절을 가진 논문이 드물다.
#
#   그런데 **Discussion 을 그대로 쓰면 역효과**다 —
#     · Discussion 은 «논의 전체» 다. 저자의 주장·해석이 대부분이고
#       **초록과 성격이 비슷하다**(= 팔기 위해 쓴 글)
#     · 한계 서술은 보통 **Discussion 뒤쪽**에 온다
#     · 그런데 앞에서 4,000자를 자르면 **결과 요약(긍정 서술)만** 들어간다
#   실측: 41건 중 **35건(85%)이 상한에 잘렸다.** 즉 대부분이 그랬을 것이다.
#
#   **F 의 전제가 *"심사를 통과하려고 쓴 글을 읽는다"* 인데, 고치지
#   않으면 정확히 그 반대를 읽는다.**
#
#   → Discussion 은 **문단으로 쪼개 한계 단서가 있는 것만** 고른다.
#     못 고르면 **뒤쪽**을 쓰고, **판정을 달리 매겨 섞이지 않게** 한다.
LIMIT_CUES = (
    "limitation", "caveat", "interpreted with caution",
    "cannot exclude", "cannot be excluded", "not generaliz",
    "may not generaliz", "small sample", "underpowered",
    "not powered", "further studies are needed",
    "should be confirmed", "residual confounding",
)


# ── PMID → PMC 매핑 ───────────────────────────────────────────────
#
#   ⚠ 09-15 · `bench/pmccheck` 에 있던 것을 **여기로 옮겼다.** 파이프라인
#     (`core/gates`)이 `bench/` 를 부르면 의존 방향이 거꾸로다. 검증은
#     09-13에 끝난 로직이고 **한 글자도 안 고쳐 옮긴다.**
#
#   ⛔ 두 가지를 지킨다(09-13 `--probe` 가 잡은 것) —
#     ① `linkname=pubmed_pmc` 를 **반드시** 건다. 안 걸면
#        `pubmed_pmc_refs`(**이 논문을 인용한** 논문들)가 온다
#     ② `&id=` 를 **따로 반복**한다. `id=a,b,c` 로 묶으면 한 `linkset`
#        으로 합쳐 와서 **어느 PMID 의 결과인지 못 가른다**
LINKNAME = "pubmed_pmc"
ELINK_BATCH = 50          # 200이면 URL 이 2,600자를 넘어 서버가 끊는다


def _elink(pmids: List[str]) -> Dict[str, Any]:
    sources.throttle()
    base = sources._params(dbfrom="pubmed", db="pmc",
                           linkname=LINKNAME, retmode="json")
    url = (sources.EUTILS + "elink.fcgi?" + base
           + "".join("&id=%s" % p for p in pmids))
    try:
        return {"ok": True, "data": sources._get(url)}
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}


def _parse_links(d: Any) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    try:
        for ls in (d or {}).get("linksets") or []:
            ids = ls.get("ids") or []
            if len(ids) != 1:
                return {}                  # 묶여 오면 **못 읽은 것**이다
            got: List[str] = []
            for db in ls.get("linksetdbs") or []:
                if db.get("linkname") == LINKNAME:
                    got += [str(x) for x in (db.get("links") or [])]
            out[str(ids[0])] = got
    except Exception:
        return {}
    return out


MAX_SPLIT = 3             # 실패하면 절반으로 쪼개 다시 — 이 깊이까지


def _ask(chunk: List[str], depth: int = 0) -> Dict[str, Any]:
    """한 덩이를 묻는다. **실패하면 절반으로 쪼개 다시.**

    ⚠ 09-13 · 배치 200건이 URL 길이로 끊겨 **9/10 배치가 실패**했다.
      쪼개 재시도를 넣자 **1,800건이 전부 복구**돼 조회불가가 0이 됐다.
      그 전 수치(8.8%)는 «F 를 접는다» 구간이었다 — 이 재시도가
      **결론을 뒤집었다.**
    """
    r = _elink(chunk)
    if r.get("ok"):
        got = _parse_links(r["data"])
        if got:
            return {"got": got, "unreach": []}
    if len(chunk) > 1 and depth < MAX_SPLIT:
        mid = len(chunk) // 2
        a = _ask(chunk[:mid], depth + 1)
        b = _ask(chunk[mid:], depth + 1)
        merged = dict(a["got"])
        merged.update(b["got"])
        return {"got": merged, "unreach": a["unreach"] + b["unreach"]}
    return {"got": {}, "unreach": list(chunk),
            "error": r.get("error") or "응답을 못 읽었다"}


def pmc_ids(pmids: List[str], progress=None) -> Dict[str, Any]:
    """PMID 목록 → `{pmid: pmcid}`. **못 물어본 것을 따로 돌려준다.**

    ⚠ 「PMC 없음」과 「조회 실패」를 섞지 않는다 — 결함 35 계열.
      섞으면 망 장애가 «전문 없음» 이라는 **발견**으로 둔갑한다.
    """
    found: Dict[str, str] = {}
    none_: List[str] = []
    unreach: List[str] = []
    for i in range(0, len(pmids), ELINK_BATCH):
        chunk = pmids[i:i + ELINK_BATCH]
        r = _ask(chunk)
        got, bad = r["got"], set(r["unreach"])
        for p in chunk:
            if p in bad:
                unreach.append(p)
            elif got.get(p):
                found[p] = got[p][0]
            elif p in got:
                none_.append(p)
            else:
                unreach.append(p)
        if progress:
            progress(min(i + ELINK_BATCH, len(pmids)), len(pmids),
                     len(found), len(none_), len(unreach), r.get("error"))
    return {"매핑": found, "PMC없음": none_, "조회불가": unreach}


def fetch_xml(pmcid: str, use_cache: bool = True,
              keep: bool = False) -> Dict[str, Any]:
    """PMC 본문 XML. **예외를 던지지 않고** 실패를 값으로 돌려준다.

    ⚠ `keep=False`(기본)면 **캐시에 안 남긴다** — 한 편 91 KB 라
      캐시를 통째로 잡아먹는다. 절만 남기는 이유는 `limitations()` 참조.
    """
    key = CACHE_PRE + str(pmcid).lstrip("PMC")
    if use_cache:
        hit = cache.get(key)
        if hit:
            return {"ok": True, "xml": hit, "cached": True}
    sources.throttle()
    url = (sources.EUTILS + "efetch.fcgi?"
           + sources._params(db="pmc", id=str(pmcid).lstrip("PMC"),
                             retmode="xml"))
    try:
        xml = sources._get_xml(url)
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                "cached": False}
    # ⛔ 09-15 · **`keep` 을 실제로 본다.** 처음엔 인자만 만들고
    #   `cache.put(key, xml)` 을 무조건 했다 — **죽은 인자**였고,
    #   그래서 «절만 캐시한다» 는 수정이 **아무 효과가 없었다**
    #   (모의로 태워 보니 절약 1배). 09-01 `REVIEW_MULT` 와 같은 계열이다.
    if keep:
        cache.put(key, xml)
    return {"ok": True, "xml": xml, "cached": False}


def _text(el) -> str:
    """하위 태그를 벗기고 글자만. 문단 사이는 줄바꿈."""
    out: List[str] = []
    for node in el.iter():
        if node.tag.split("}")[-1] == "title":
            continue                       # 제목은 본문에 안 넣는다
        if node.text:
            out.append(node.text)
        if node.tail:
            out.append(node.tail)
    s = " ".join(" ".join(out).split())
    return s


def _one(el) -> str:
    """이 요소 **하나**의 글자만. `_text` 와 달리 하위 `<sec>` 를 안 탄다."""
    return " ".join(" ".join(el.itertext()).split())


def _paras(sec) -> List[str]:
    """절을 `<p>` 단위로 쪼갠다. **빈 문단은 버린다.**"""
    out: List[str] = []
    for p in sec.iter():
        if p.tag.split("}")[-1] != "p":
            continue
        t = _one(p)
        if len(t) > 40:            # 표 캡션·각주 같은 짧은 조각은 뺀다
            out.append(t)
    return out


def _title_of(sec) -> str:
    for ch in sec:
        if ch.tag.split("}")[-1] == "title":
            return " ".join((ch.itertext()))
    return ""


def sections(xml: str) -> Dict[str, Any]:
    """XML → 절. **중첩 `<sec>` 까지 훑는다.**

    ⚠ `Limitations` 는 독립 절일 때도 있고 **`Discussion` 안에 중첩**될
      때도 있다. 바깥만 보면 흔한 경우를 통째로 놓친다.
    """
    try:
        root = ET.fromstring(xml)
    except Exception as e:
        return {"판정": "조회실패", "왜": "XML 파싱 실패: %s" % e}

    body = None
    for el in root.iter():
        if el.tag.split("}")[-1] == "body":
            body = el
            break
    if body is None:
        return {"판정": "본문없음", "길이": len(xml)}

    found: Dict[str, str] = {}
    titles: List[str] = []
    for sec in body.iter():
        if sec.tag.split("}")[-1] != "sec":
            continue
        t = _title_of(sec).strip().lower()
        if not t:
            continue
        titles.append(t)
        for name, pats in WANT:
            if name in found:
                continue
            if any(p in t for p in pats):
                found[name] = _text(sec)
                if name == "discussion":
                    # 문단 단위도 같이 들고 있는다 — 단서 있는 것만
                    # 고르려면 통짜 글자열로는 안 된다.
                    found["_discussion_paras"] = _paras(sec)
                break

    if not found:
        return {"판정": "절없음", "본문절": titles[:12]}

    # ── 명세 §2 — 우선순위대로 **하나만** 고른다 ────────────────────
    #
    #   ⚠ 09-14 · **어떻게 얻었는지를 판정에 남긴다.** 「독립 한계 절」과
    #     「논의에서 골라낸 문단」과 「논의 뒤쪽」은 **근거의 질이 다르다.**
    #     한 칸에 뭉뚱그리면 나중에 «무엇이 값을 했나» 를 못 가른다.
    for name, _ in WANT:
        if name not in found:
            continue
        txt = found[name]

        if name != "discussion":
            # 절 전체가 한계 서술이다 — **앞에서** 자른다.
            return {"판정": "추출됨", "종류": "한계절", "절": name,
                    "글자수": len(txt), "잘림": len(txt) > MAX_CHARS,
                    "본문": txt[:MAX_CHARS],
                    "다른절": [k for k in found if k != name],
                    "본문절": titles[:12]}

        # Discussion — 문단으로 쪼개 **단서가 있는 것만** 고른다.
        paras = found.get("_discussion_paras") or []
        hits = [p for p in paras
                if any(c in p.lower() for c in LIMIT_CUES)]
        if hits:
            joined = "\n\n".join(hits)
            return {"판정": "추출됨", "종류": "한계문단", "절": name,
                    "문단수": len(hits), "전체문단": len(paras),
                    "글자수": len(joined), "잘림": len(joined) > MAX_CHARS,
                    "본문": joined[:MAX_CHARS],
                    "다른절": [k for k in found if k != name
                              and not k.startswith("_")],
                    "본문절": titles[:12]}

        # 단서도 없다 — **뒤쪽**을 쓴다. 한계는 논의 끝에 오기 때문이다.
        # ⚠ 근거가 가장 약한 칸이다. 판정으로 그 사실을 남긴다.
        return {"판정": "추출됨", "종류": "논의뒤", "절": name,
                "글자수": len(txt), "잘림": len(txt) > MAX_CHARS,
                "본문": txt[-MAX_CHARS:],          # ← **뒤에서** 자른다
                "다른절": [k for k in found if k != name
                          and not k.startswith("_")],
                "본문절": titles[:12]}
    return {"판정": "절없음", "본문절": titles[:12]}


def limitations(pmcid: str, use_cache: bool = True) -> Dict[str, Any]:
    """`pmcid` → 절 하나. **판정 넷 중 하나를 반드시 단다.**

    ## ⛔ 09-15 · **본문 XML 을 캐시하지 않는다** (렌즈 7)

    처음엔 받은 XML 을 통째로 `PMCXML::` 에 넣었다. 실측하니 —

        pubmed_cache.json   31.2 MB
          그중 PMCXML 126편  11.5 MB  (**42%**)
          한 편 중앙 91 KB · 최대 538 KB

    **우리가 쓰는 것은 절 4,000자뿐이다.** 필요한 것의 **20배**를
    저장했고, 그 캐시는 **매 실행 통째로 로드**된다. 84쌍을 몇 번 더
    돌리면 수백 MB가 된다.

    **절만 캐시한다**(`PMCSEC::`). 한 편 ~4 KB — **23배 준다.**

    ⚠ **판정은 안 바뀐다.** 같은 절이 나오므로 캐시 방식은 결과와
      무관하다(`§3-2` 무관). 바뀌는 것은 **디스크와 메모리**뿐이다.

    ⚠ 파서를 고치면 **재추출이 필요하다.** 그때 XML 이 없으므로 다시
      받아야 한다 — `BIOREROUTE_PMC_KEEP_XML=1` 로 원본 보관을 켤 수
      있다(개발용). **기본은 끔.**
    """
    key = SEC_PRE + str(pmcid).lstrip("PMC")
    if use_cache:
        hit = cache.get(key)
        if isinstance(hit, dict) and hit.get("판정"):
            out = dict(hit)
            out["pmc"] = pmcid
            out["cached"] = True
            return out

    r = fetch_xml(pmcid, use_cache=use_cache, keep=KEEP_XML)
    if not r["ok"]:
        # ⚠ 조회 실패는 **캐시하지 않는다.** 캐시하면 망 장애가
        #   «전문 없음» 으로 굳는다(결함 35 계열).
        return {"판정": "조회실패", "왜": r["error"], "pmc": pmcid}
    out = sections(r["xml"])
    cache.put(key, {k: v for k, v in out.items() if k != "pmc"})
    out["pmc"] = pmcid
    out["cached"] = False
    return out


def main(argv=None) -> int:
    """단건 확인용 CLI — **실물 XML 로 추출기를 태우는 자리**.

    ⚠ 09-14 · 모의 XML 다섯 경우는 통과했지만 **그건 내가 만든 것**이다.
      실제 PMC 구조와 다를 수 있다(`CLAUDE.md §5`). 이 명령이 실물을 본다.
    """
    import argparse
    import json as _json
    ap = argparse.ArgumentParser(
        description="PMC 본문에서 Limitations 절만 뽑는다 (LLM 0회)")
    ap.add_argument("pmcid", nargs="?", default=None,
                    help="PMC ID (`PMC` 접두어는 있어도 없어도 된다)")
    ap.add_argument("--no-cache", action="store_true", help="캐시 무시")
    ap.add_argument("--full", action="store_true", help="뽑은 절 전문 출력")
    a = ap.parse_args(argv)

    if not a.pmcid:
        print("PMC ID 를 달라. 예: py -m bioreroute.io.fulltext 13424660")
        print("  (`pmccheck --fetch` 가 준 PMC 번호를 쓰면 된다)")
        return 2

    r = limitations(a.pmcid, use_cache=not a.no_cache)
    v = r.get("판정")
    print("PMC%s — **%s**%s"
          % (str(a.pmcid).lstrip("PMC"), v, " (캐시)" if r.get("cached") else ""))
    if v == "추출됨":
        print("  절 `%s` · %d자%s"
              % (r["절"], r["글자수"], " · **상한에 잘림**" if r["잘림"] else ""))
        if r.get("다른절"):
            print("  같이 있던 절: %s" % ", ".join(r["다른절"]))
        print("  본문 절 목록: %s" % ", ".join(r.get("본문절") or []))
        txt = r["본문"]
        print()
        print("  " + (txt if a.full else txt[:400] + ("…" if len(txt) > 400 else "")))
    elif v == "절없음":
        print("  ⚠ 본문은 읽혔는데 **해당 절이 없다** — «조회 실패»가 아니다.")
        print("  본문 절 목록: %s" % ", ".join(r.get("본문절") or []))
    elif v == "본문없음":
        print("  ⚠ `<body>` 가 없다 — **구독 전용**의 모습이다(길이 %s)."
              % r.get("길이"))
    else:
        print("  ⛔ %s" % r.get("왜"))
        print("  ⚠ 이건 **«없음» 이 아니라 «확인 실패»** 다.")
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
