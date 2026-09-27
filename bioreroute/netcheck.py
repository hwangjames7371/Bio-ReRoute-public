# -*- coding: utf-8 -*-
"""외부 조회가 살아 있는가 — **LLM 비용 0.**

    py -m bioreroute.netcheck

## 왜 따로 두는가

`diag.py` 는 LLM만 본다. 그런데 이 시스템의 근거는 **PubMed와 CT.gov**에서
온다. 그 둘이 막히면 게이트는 조용히 캐시만 읽고, 화면에는 여전히
초록 수와 판정이 찍힌다. **완전해 보이는 결과가 나온다.**

결함 6에서 같은 일을 겪었다 — *"LLM 없이 돌려도 완전한 결과표 출력"*.
결함 35에서 또 겪었다 — *"조회 실패 14건을 0건으로 합산해 B6를 빼라고 결론"*.
**세 번째를 막으려고 만든다.**

## 캐시를 **끄지 않는다. 비운다.**

첫 판은 `cache.configure(enabled=False)` 로 껐다. 캐시가 켜져 있으면
"되는 것처럼" 보이니까. **그런데 정반대로 틀렸다** —
`pubmed_abstracts` 가 캐시를 거쳐 반환하는 구조라, 캐시를 끄면
조회에 성공해도 빈 결과가 나온다. **진단기가 거짓 경보를 냈다**(결함 36).

지금은 **빈 임시 캐시 파일**을 쓴다. 낡은 자료가 섞일 수 없고,
그러면서 저장·조회 경로는 정상 동작한다.

> 켜면 거짓 안심, 끄면 거짓 경보. **둘 다 틀린 답이었다.**
> 방어를 켜고 끄는 문제로 놓으면 이렇게 된다 — 구조를 바꿔야 한다.
"""

import argparse
import sys
import os

from .io import cache, sources


def head(t):
    print("\n" + t)
    print("─" * 68)


def show(name, fn):
    try:
        r = fn()
    except Exception as e:
        r = {"error": "%s: %s" % (type(e).__name__, e)}
    err = r.get("error")
    print("  %-4s %-30s %s" % ("실패" if err else "OK", name,
                               (str(err)[:60] if err else _ok_detail(r))))
    return not err


def _ok_detail(r):
    if "count" in r:
        return "%s건" % r["count"]
    if "ncts" in r:
        return "%d건 %s" % (len(r["ncts"]), r.get("how", ""))
    return "응답 있음"


def main(argv=None):
    ap = argparse.ArgumentParser(description="외부 조회 진단 (LLM 비용 0)")
    ap.add_argument("--use-cache", action="store_true",
                    help="기존 캐시를 쓴다. **기본은 빈 임시 캐시** — "
                         "낡은 자료가 성공으로 보이는 것을 막는다")
    a = ap.parse_args(argv)

    print("=" * 68)
    print("Bio-ReRoute 외부 조회 진단%s"
          % ("" if a.use_cache else "  (빈 임시 캐시)"))
    print("=" * 68)

    head("[1] 프록시 설정 — 이게 있으면 여기가 먼저 의심 대상이다")
    found = False
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        v = os.environ.get(k)
        if v:
            found = True
            print("  %-12s = %s" % (k, v))
    if not found:
        print("  프록시 환경변수 없음")
    else:
        print("\n  → `Tunnel connection failed: 403` 은 **프록시가 거절한 것**이다.")
        print("     원격 서버가 아니라 이 프록시가 막는다. 임시 해제:")
        print("       $env:HTTPS_PROXY=''  ;  $env:HTTP_PROXY=''")

    if not a.use_cache:
        # **끄지 않고 비운다.** 끄면 `pubmed_abstracts` 가 캐시를 거쳐
        # 반환하는 구조 때문에 성공해도 빈 결과가 나온다(결함 36).
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), "_netcheck_cache.json")
        if os.path.exists(tmp):
            os.remove(tmp)
        cache.configure(tmp, enabled=True)

    head("[2] PubMed — 근거의 주 경로")
    hit = {}

    def _search():
        r = sources.pubmed_search("aspirin", 3)
        hit.update(r)
        return r

    p1 = show("검색 (esearch)", _search)

    def _abs():
        """**초록 본문이 왔는지**를 본다.

        레코드 개수만 세면 안 된다 — 조회가 실패해도 `error` 를 담은
        빈 레코드가 1건 돌아오므로 `len(...)==1` 은 성공처럼 보인다.
        실제로 첫 판에서 그렇게 만들었고 화면에 `OK 1건` 이 떴다.
        **내용이 아니라 껍데기를 세는 검사는 검사가 아니다.**
        """
        # **검색이 방금 돌려준 PMID를 쓴다.** 상수를 박아 두면 그 논문에
        # 초록이 없거나 사라졌을 때 진단기가 네트워크 탓을 한다.
        # 그리고 이 편이 시스템이 실제로 타는 경로(검색→초록)와 같다.
        pid = (hit.get("pmids") or [None])[0]
        if not pid:
            return {"error": "검색이 PMID를 못 줘서 확인 불가"}
        recs = sources.pubmed_abstracts([pid]) or {}          # {pmid: {...}}
        r0 = recs.get(pid)
        if not r0:
            return {"error": "빈 응답"}
        if r0.get("error"):
            return {"error": r0["error"]}
        body = (r0.get("abstract") or "").strip()
        return {"count": "%d자" % len(body)} if body else {"error": "초록 본문 없음"}

    p2 = show("초록 (efetch)", _abs)

    head("[3] CT.gov — 등록부 게이트(B6)의 유일한 경로")
    c1 = show("검색 (studies?query)",
              lambda: sources.ctgov_search("metformin", "Breast Cancer", 3))
    c2 = show("개별 시험 (studies/NCT…)",
              lambda: sources._ctg(sources.CTG + "/NCT01101438?format=json")
              and {"count": 1})

    # ── [4] 선언은 했는데 **파일로 받아야 하는** 자료원 ──────────
    #
    #   제안서 §3.1 이 DRKG 를 자료원으로 적었다. 그런데 이건 API 가
    #   아니라 **1.4GB tsv 를 내려받아야** 쓰는 것이고, 안 받으면
    #   `io/drkg.py` 는 아무도 안 부르는 죽은 코드로 남는다 — 실제로
    #   그랬다(preflight 렌즈 3이 매번 잡았다).
    #
    #   **여기서 부르는 이유는 가드를 통과하려는 게 아니다.**
    #   netcheck 의 일이 *"선언한 자료원이 실제로 닿는가"* 이고,
    #   `없다` 도 그 질문의 답이다. 조용히 없는 것보다 화면에 `없음` 이
    #   찍히는 편이 낫다 — 결함 35가 정확히 *조용한 부재*였다.
    head("[4] DRKG — **API 가 아니라 내려받아야 하는 파일** (제안서 §3.1)")
    from .io import drkg
    d = drkg.available()
    if d["ok"]:
        print("  %-4s %-30s %s" % ("OK", "drkg.tsv", "%s MB" % d["size_mb"]))
    else:
        print("  %-4s %-30s %s" % ("없음", "drkg.tsv", d["error"][:60]))
        print("       → **다중홉(§2.1)은 로드맵이다.** 없다고 해서 판정이"
              " 틀리지 않는다.")
        print("         받으면 `BIOREROUTE_DRKG` 로 경로를 준다.")
        print("       ⚠ DrugBank 유래 관계는 **CC BY-NC** — 상업 배포는 별도"
              " 라이선스")

    head("[5] 특허 — **우리가 만든 게 아니라 세상이 바꾼 것** (결함 95)")
    #
    #   08-10: 승우가 키를 신청하려다 발급처가 없어진 걸 알았다.
    #   **다섯 달 전에 멈췄고 그날 아침 `netcheck` 는 전부 초록이었다** —
    #   특허가 이 목록에 없었기 때문이다. *가드가 안 보는 곳이 가장
    #   오래 낡는다*(결함 60)가 또 맞았다. 그래서 목록에 넣는다.
    #
    #   **살았는지 죽었는지 여기서 판정하지 않는다.** 우리가 통제 못 하는
    #   외부 상태이고, 화면이 할 일은 *"확인해라"* 라고 말하는 것이다.
    import os as _os
    from .io import fto as _fto
    _pk = bool(_os.environ.get("PATENTSVIEW_API_KEY", ""))
    print("  %-4s %-30s %s" % ("키" if _pk else "없음", "PATENTSVIEW_API_KEY",
                               "설정됨" if _pk else "미설정"))
    print("  %-4s %-30s %s" % ("⚠", "PatentsView search·API",
                               "**2026-03-20 USPTO ODP 전환으로 중단**"))
    print("       → 신청 페이지(`patentsview.org/apis/keyrequest`)가 전환")
    print("         안내로 넘어간다. **키를 새로 못 받는다.**")
    print("       → `fto.check()` 는 `확인불가` 를 낸다 — **개발가능이 아니다.**")
    print("         특허 층(§3.3-8)은 **로드맵**이고, 대안은 SureChEMBL·ODP 벌크다.")
    print("       ⓘ 이 줄은 **조회 결과가 아니라 기록**이다. 되살아났는지는")
    print("         `%s` 를 직접 확인해라." % _fto.PV)

    head("판정")
    if all([p1, p2, c1, c2]):
        # **DRKG 부재를 실패로 세지 않는다.** 로드맵 항목이고, 이걸 실패로
        # 세면 진단기가 늘 붉어져서 아무도 안 본다. 대신 위에 찍는다.
        print("  전부 살아 있다. 마음대로 돌려라.")
        if not d["ok"]:
            print("  (DRKG 는 없지만 **로드맵 항목**이므로 실패로 세지 않는다)")
        return 0

    print("  **막힌 경로가 있다. 이 상태로 벤치마크를 돌리지 마라.**")
    print()
    print("  게이트는 조회가 실패해도 예외를 던지지 않는다(설계상 그렇다).")
    print("  대신 **캐시에 있는 것만 읽고** 화면에는 초록 수와 판정을 찍는다.")
    print("  결과가 완전해 보이지만 실제로는 옛 자료로 만든 것이다.")
    print()
    if not (c1 or c2):
        print("  · CT.gov 전면 차단 → **B6(등록부)는 의미가 없다.** 상한 측정도 못 한다")
    elif not c1:
        print("  · CT.gov 검색만 차단 → 개별 조회는 되므로 캐시된 NCT는 읽힌다.")
        print("    그러나 **새 독립 시험을 못 찾으므로 B6의 값어치를 잴 수 없다**")
    if not (p1 and p2):
        print("  · PubMed 차단 → F0·팩트체커·회의주의자가 전부 캐시에 갇힌다.")
        print("    **새 쌍에 대한 판정은 신뢰할 수 없다**")
    print()
    print("  확인 순서")
    print("    1. 위 [1]의 프록시 변수 — 있으면 지우고 다시")
    print("    2. VPN·사내망 — 껐다 켜 보라")
    print("    3. 둘 다 아니면 잠시 뒤 재시도 (대량 수확 후 일시 차단일 수 있다)")
    return 1


if __name__ == "__main__":
    sys.exit(main())


    head("[6] 구조 — **S1·S3 의 유일한 경로** (결함 196)")
    # ── 왜 08-13에야 들어왔나 ────────────────────────────────────
    #
    #   이 파일 독스트링이 이렇게 적어 뒀다 —
    #     *"그 둘이 막히면 게이트는 **조용히 캐시만 읽고**, 화면에는
    #       여전히 초록 수와 판정이 찍힌다. **완전해 보이는 결과가 나온다**"*
    #
    #   **그 구멍이 구조 경로에 그대로 있었다.** S1 은 08-11에 도달
    #   가능해졌고 S3 는 08-13에 열렸는데, 둘 다 여기서 안 봤다.
    #   시연장에서 막히면 S1 이 `구조없음` 을 내고 **그게 「구조가 없다」로
    #   보인다** — 조회 실패와 부재를 가르는 이 프로젝트 원칙의 정반대다.
    def _uniprot():
        from .io import structure as S
        r = S.resolve("3CL protease", "SARS-CoV-2")
        return {"accession": r.get("accession"), "error": r.get("error"),
                "사슬": len(r.get("chains") or []),
                "부위": len(r.get("sites") or [])}

    show("UniProt (표적 해석)", _uniprot)

    def _af():
        from .io import structure as S
        r = S.resolve("3CL protease", "SARS-CoV-2")
        if not r.get("accession"):
            return {"error": "UniProt 이 먼저 막혔다 — AlphaFold 를 못 잰다"}
        p = S.plddt(r["accession"])
        return {"mean": p.get("mean"), "error": p.get("error"),
                "cif": bool(p.get("cif_url"))}

    show("AlphaFold (pLDDT)", _af)

    def _pdb():
        import json as _j, urllib.request as _u
        from .io import structure as S
        from .bench import dockcheck as D
        req = _u.Request(D.RCSB_ENTRY % "6LU7", headers={"User-Agent": S.UA})
        with _u.urlopen(req, timeout=S.TIMEOUT, context=S._ctx) as rr:
            d = _j.loads(rr.read().decode("utf-8"))
        ids = D.parse_nonpoly_ids(d)
        return {"항목": (d.get("rcsb_entry_info") or {}).get("nonpolymer_entity_count"),
                "엔티티번호": ids, "핵산": D.parse_polymer(d)}

    show("RCSB PDB (실험 구조 · 6LU7)", _pdb)