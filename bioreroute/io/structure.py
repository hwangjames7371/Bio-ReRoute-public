# -*- coding: utf-8 -*-
"""S1 구조 신뢰도 — UniProt 조회 → AlphaFold DB pLDDT (제안서 §3.3-7 · §2.5)

제안서 §2.5가 이 모듈의 명세다.

  > S1은 활성부위 pLDDT를 **신뢰도 게이트로만** 쓰고 **결합력으로 환산하지
  > 않으며**, S3는 포켓 내 포즈를 실제 생성한 뒤에만 입체 상보성을 산출한다.

그리고 §1이 왜 그런지 적어 뒀다 —

  > 다수 접근이 구조 예측 신뢰도(pLDDT)를 **결합력으로 오인**하나,
  > 본 시스템은 신뢰도 게이트로만 사용한다.

## 그래서 이 모듈은 **점수를 돌려주지 않는다**

`plddt` 를 로그오즈에 더할 수 있게 만들면 언젠가 누가 더한다. 이 프로젝트의
원칙이 *"안내문은 방어가 아니다. 구조로 막아야 한다"* 이므로 —

  · 반환값에 `weight` · `score` · `logodds` 같은 이름을 **두지 않는다**
  · 판정은 `"신뢰" | "저신뢰" | "구조없음" | "오류"` **네 글자짜리 라벨**이다
  · `저신뢰` 는 **기각이 아니라 연산 제외**다. 구조를 못 믿겠다는 말이지
    약이 안 듣는다는 말이 아니다

시험 [45]가 이 모듈의 어떤 반환 키도 수치 가중치로 읽히지 않는지 검사한다.

## 임계값

AlphaFold 팀의 공식 구간을 그대로 쓴다(EBI 문서 · 우리가 정한 값이 아니다).

    pLDDT > 90   매우 높음
    70–90        높음        ← 이 위를 "신뢰"로 본다
    50–70        낮음
    < 50         매우 낮음 — **무질서 영역일 가능성이 높다**

경계를 70으로 잡는 근거는 EBI가 "70 미만은 주의해서 다루라"고 적었기
때문이다. 우리 자료를 보고 고른 값이 아니다 — 그랬으면 사후 조정이다.

## `신뢰` 가 무엇을 뜻하지 **않는가** — 문헌이 우리 문구를 반증했다

초판 독스트링은 `신뢰` 를 *"구조 기반 검증을 태울 만하다"* 로 적었다.
**그 문장이 문헌에서 반증됐다**(결함 65 · 08-06 심야 선행연구 검색).

> In **four out of the five** AF models that **worsened the HTD performance
> the most**, the pLDDT metric **is equal to or greater than 70 for every
> residue in the binding site** (cf. Column 1 in Table 2), indicating high
> confidence in these modeled structures.
> — *How good are AlphaFold models for docking-based virtual screening?*
>   (PMC9852548)

**활성부위 잔기가 전부 pLDDT 70 이상인데도 도킹 성능이 가장 나빴다.**
그러므로 이 게이트가 말할 수 있는 것은 이것뿐이다 —

    `신뢰`     예측 좌표의 **국소 신뢰도가 높다**
               → 구조 기반 검증의 **전제 조건**은 만족한다
               → **성공을 예측하지 않는다.** 문헌이 그걸 반증했다
    `저신뢰`   좌표를 못 믿겠다 → **연산 제외이지 기각이 아니다**

즉 **필요조건이지 충분조건이 아니다.** 이 구분을 독스트링에 박아 두는
이유는, 그동안 줄곧 `활성부위` 라고 적고 전체 평균을 쓴 것과 같은 일이
문구 쪽에서 또 났기 때문이다 — **재는 것과 말하는 것을 계속 벌어지게
두면 그게 결함 47·63·65의 공통 원인이다.**

## 활성부위를 쓰는 것도 **우리 것이 아니다**

**리간드 heavy atom 에서 4.0 Å 이내** 잔기의 pLDDT 를 보는 것은 AlphaFold
도킹 문헌의 표준 절차다(같은 논문 · STAR Methods §Protein metrics).
한때 여기에 «8Å» 라고 적혀 있었는데 **원문 대조에서 틀린 것으로 확인됐다**
(08-18 · 결함 238). 우리는 리간드가 없어 **UniProt 주석**으로 대체하는데,
그건 **더 약한 대리물이지 새 방법이 아니다.** 발표에서 이걸 기여로
말하지 않는다.
"""

from .. import config as _config     # .env 먼저 (순서 중요)

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import cache

TIMEOUT = 25
UA = "Bio-ReRoute"
UNIPROT = ("https://rest.uniprot.org/uniprotkb/search"
           "?query=%s&fields=accession,protein_name,organism_name"
           ",length,ft_chain,ft_binding,ft_act_site&format=json&size=5")
AFDB = "https://alphafold.ebi.ac.uk/api/prediction/%s"
# 실험 구조 **개수만** 센다. `format=tsv` 라 응답이 한 줄이고, JSON 으로
# 받으면 P0DTD1 하나가 80KB 다(실측). 개수 말고는 안 쓴다.
UNIPROT_PDB = ("https://rest.uniprot.org/uniprotkb/search?query=accession:%s"
               "&fields=xref_pdb&format=tsv&size=1")

# **라벨 전집.** 소비자(`core/gates.py`)가 이 중 하나라도 안 다루면
# 시험 [73]이 깨진다. 08-10에 `신뢰도미상` 을 늘려 놓고 게이트를 안 고쳐서
# 조회 실패로 취급됐다(결함 92) — 그래서 목록을 코드로 못 박는다.
LABELS = ("신뢰", "저신뢰", "신뢰도미상", "구조없음", "오류")

# UniProt feature type 중 "여기가 약이 붙는 자리"에 해당하는 것.
# **주석이지 예측이 아니다** — 아래 `site_positions` 독스트링 참조.
SITE_TYPES = ("Binding site", "Active site")

# AlphaFold 공식 구간. **우리가 정한 값이 아니다.**
PLDDT_OK = 70.0
_ctx = ssl.create_default_context()


def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
        return json.loads(r.read().decode("utf-8"))


def _acc_queries(target: str, organism: Optional[str]) -> List[str]:
    """표적 이름 → UniProt 검색식 **둘**. 앞의 것이 0건이면 뒤를 쓴다.

    ## 08-10 — **처음 실제로 태워 보고 고쳤다** (결함 88)

    그동안 줄곧 모의로만 돌렸고(재현절차 함정 20) 08-10에 승우가 처음
    진짜 UniProt 을 태웠다. 결과 —

        assess("SARS-CoV-2 3CL protease", "SARS-CoV-2")  →  구조없음 · UniProt 0건

    **없는 게 아니라 우리가 못 찾은 것이다.** 같은 표적을 실측으로 대조 —

        protein_name:"SARS-CoV-2 3CL protease"       0건    ← 우리가 쓰던 것
        자유 텍스트 SARS-CoV-2 3CL protease           P0DTC1 · P0DTD1 · P0C6U8
        3CL protease + organism_name:"SARS-CoV-2"    P0DTC1 · P0DTD1

    원인 셋 —

      ① `protein_name:` 은 **정확 구문 일치**를 요구한다. UniProt 이름은
         `3C-like proteinase nsp5` 이고 별칭이 `Main protease`·`Mpro`·
         `3CL-PRO` 다. **`SARS-CoV-2 3CL protease` 는 UniProt 명명이 아니다**
         — 라우터가 LLM 에서 받은 말이다
      ② `gene:SARS-CoV-2 3CL protease` — 따옴표가 없어 **공백에서 질의가
         깨진다.** 뒤 토큰이 필드 밖으로 샌다
      ③ 그래서 두 항이 다 빗나가면 `AND` 결과가 0 이 된다

    자유 텍스트는 UniProt 이 **이름·별칭·약칭을 다 훑는다.** 정밀도는
    떨어지지만 **0건보다 낫다** — 그리고 정밀한 쪽을 먼저 쓰므로
    맞을 때는 그대로 맞는다.

    > **찾아도 그것은 폴리단백질이다.** P0DTD1 은 7,096잔기 `pp1ab` 이고
    > 성숙 3CL 프로테아제(306잔기)가 그 안에 들어 있다. 전체 평균 pLDDT 를
    > 쓰면 **완전히 무의미한 수**가 나왔을 것이다 — 결함 63에서 활성부위
    > 기준으로 바꾼 것이 여기서 값을 한다. 그래도 **성숙 단백질이 아니라는
    > 한계는 남는다.** 화면에 `basis` 로 실어 보낸다.
    """
    t = target.split("(")[0].split("/")[0].strip()
    org = (' AND (organism_name:"%s")' % organism) if organism else ""
    precise = '(protein_name:"%s" OR gene:"%s") AND (reviewed:true)%s' % (t, t, org)
    # 자유 텍스트 — 따옴표를 **안 씌운다.** 씌우면 다시 구문 일치가 된다.
    loose = '%s AND (reviewed:true)%s' % (t, org)
    return [UNIPROT % urllib.parse.quote(q) for q in (precise, loose)]


def site_positions(entry: Dict[str, Any]) -> List[int]:
    """UniProt 항목 → **활성부위·결합부위 잔기 번호**.

    ## 제안서 §2.5 가 요구한 것

      > S1은 **활성부위 pLDDT** 를 신뢰도 게이트로만 쓴다

    그동안 줄곧 우리는 **단백질 전체 평균**을 썼다. `제안서_전수대조.md` 가
    그걸 `❌ 우리는 전체 평균이다` 로 적어 뒀다. 게이트 이름은 §2.5 것이고
    재는 것은 다른 것이었다 — **결함 47과 같은 계열**(구성 개념 타당도)이다.

    왜 차이가 나는가: AlphaFold 는 무질서 말단·루프에서 pLDDT 가 낮다.
    전체 평균은 그 영역에 끌려 내려가고, **정작 리간드가 붙는 포켓은
    보통 잘 접힌 코어**에 있다. 즉 전체 평균은 **틀린 방향으로 보수적**이다.

    ## 이것은 fpocket 이 아니다 — 먼저 적는다

    제안서 §3.1 은 `BioPython · fpocket` 으로 포켓을 잡겠다고 했다.
    **안 썼다.** 대신 **UniProt 이 이미 주석해 둔 잔기**를 쓴다.

    | | fpocket | 여기 |
    |---|---|---|
    | 무엇 | 기하학으로 포켓을 **예측** | 문헌 근거 **주석**을 조회 |
    | 없을 때 | 늘 뭔가 내놓는다 | **없으면 없다고 말한다** |
    | 한계 | 예측이 틀릴 수 있다 | **주석이 없는 단백질이 많다** |

    주석 기반이 더 보수적이다 — 없으면 침묵하기 때문이다. 그래서
    `assess()` 는 주석이 없으면 **전체 평균으로 내려가고 그렇다고 적는다.**
    조용히 대리물로 바꾸는 것이 줄곧 문제였다.
    """
    out = set()
    for f in (entry.get("features") or []):
        if f.get("type") not in SITE_TYPES:
            continue
        loc = (f.get("location") or {})
        a = (loc.get("start") or {}).get("value")
        b = (loc.get("end") or {}).get("value")
        if not isinstance(a, int):
            continue
        if not isinstance(b, int):
            b = a
        # 구간이 비정상적으로 길면 포켓이 아니다 — 도메인 주석이 섞인 것이다.
        # **넓은 구간을 포켓으로 쓰면 전체 평균과 다를 게 없어진다.**
        if b - a > 30:
            continue
        out.update(range(a, b + 1))
    return sorted(out)


def chains(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """UniProt 항목 → **성숙 사슬 목록** `[{name, start, end}]`.

    폴리단백질을 다루려면 이게 있어야 한다. `Chain` 자질에는 전장 사슬
    (`Replicase polyprotein 1a` 1–4405)과 성숙 산물(`3C-like proteinase
    nsp5` 3264–3569)이 **같이** 들어 있다. 둘을 안 가르면 3CL 프로테아제를
    물었는데 nsp2 잔기를 평균 내게 된다 — 그게 결함 90이다.
    """
    out = []
    for f in (entry.get("features") or []):
        if f.get("type") != "Chain":
            continue
        loc = (f.get("location") or {})
        a = (loc.get("start") or {}).get("value")
        b = (loc.get("end") or {}).get("value")
        if isinstance(a, int) and isinstance(b, int):
            out.append({"name": f.get("description") or "", "start": a, "end": b})
    return out


# 표기 차이를 흡수한다. **표적 이름은 LLM 이 준 말**이고 UniProt 은 자기
# 명명법을 쓴다 — `3CL protease` vs `3C-like proteinase`. 아래는 실측으로
# 확인한 것만 넣는다(P0DTC1 · 08-10). 추측으로 늘리지 않는다.
_ALIAS = {"proteinase": "protease", "peptidase": "protease",
          "polyprotein": "polyprotein"}


def _tok(s: str) -> List[str]:
    """이름 → 비교용 토큰. 하이픈을 **지운다**(`3C-like` → `3clike`)."""
    s = (s or "").lower().replace("-", "").replace("_", "")
    raw = "".join(c if c.isalnum() else " " for c in s).split()
    return [_ALIAS.get(t, t) for t in raw]


def _pmatch(t: str, x: str) -> bool:
    """토큰 둘이 **같은 것을 가리키나.** 접두 일치를 허용하되 **숫자에서 끊는다.**

    ## 왜 그냥 접두가 아니면 안 되는가 — 결함 177

    08-13 실측. `SARS-CoV-2 RdRp (nsp12)` 를 P0DTD1 의 성숙 사슬 15개에
    붙이려는데 **두 개가 1점으로 비겨** `모호` 가 났다.

        Host translation inhibitor **nsp1**    ← `nsp12`.startswith(`nsp1`)
        RNA-directed RNA polymerase **nsp12**  ← 진짜 답

    `nsp1` 은 `nsp12` 의 **짧은 표기가 아니라 다른 단백질**이다.
    `3cl` ⊂ `3clike` 를 허용하려고 넣은 규칙이 **번호를 삼켰다.**

    > **뒤에 붙은 것이 숫자면 그건 다른 번호다.**
    > `nsp1`≠`nsp12` · `IL1`≠`IL12` · `CYP3A4`≠`CYP3A43`

    반대로 뒤에 붙은 것이 글자면 같은 이름의 긴 표기일 수 있으므로
    (`3cl`→`3clike`) 그대로 허용한다.
    """
    if t == x:
        return True
    lo, hi = (t, x) if len(t) < len(x) else (x, t)
    if not lo or not hi.startswith(lo):
        return False
    return not hi[len(lo)].isdigit()


def localize(target: str, chs: List[Dict[str, Any]],
             seq_len: Optional[int]) -> Dict[str, Any]:
    """표적 이름 + 사슬 목록 → **어느 성숙 사슬을 묻고 있는가**.

    돌려주는 것 — `{"kind", "chain", "why"}`

      `단일`     폴리단백질이 아니다. 사슬 전체를 쓴다
      `국소화`   성숙 사슬 하나로 좁혔다. `chain` 에 그 사슬
      `모호`     폴리단백질인데 **어느 사슬인지 못 정했다** → 거절한다

    ## 못 정했으면 **거절한다.** 전체로 되돌리지 않는다

    되돌리면 결함 90이 그대로 재현된다 — 3CL 프로테아제를 물었는데
    pp1a 전체의 주석 40개를 평균 내고 `활성부위` 라고 적는 것. 이 프로젝트
    원칙이 *"안내문은 방어가 아니다"* 이므로 **각주로 적지 말고 막는다.**

    ## 점수 규칙 — 유일한 승자만 인정한다

    표적 토큰이 사슬 토큰의 **앞부분과 맞으면** 1점(`3cl` ⊂ `3clike`).
    최고점이 1점 이상이고 2등보다 **엄격히 높아야** 국소화로 친다.
    `protease` 만 물으면 nsp3(papain-like)와 nsp5가 1점으로 비겨 `모호` 가
    되는데, **그게 맞는 결과다** — 코로나 폴리단백질에 프로테아제는 둘이다.
    """
    mature = [c for c in chs if not (seq_len and c["end"] - c["start"] + 1 >= seq_len)]
    if not mature:
        return {"kind": "단일", "chain": None, "why": ""}
    tt = _tok(target)
    scored = []
    for c in mature:
        ct = _tok(c["name"])
        n = sum(1 for t in tt if any(_pmatch(t, x) for x in ct))
        scored.append((n, c))
    scored.sort(key=lambda x: -x[0])
    best = scored[0]
    second = scored[1][0] if len(scored) > 1 else -1
    if best[0] >= 1 and best[0] > second:
        return {"kind": "국소화", "chain": best[1],
                "why": "성숙 사슬 `%s` (%d–%d) 로 좁혔다"
                       % (best[1]["name"], best[1]["start"], best[1]["end"])}
    return {"kind": "모호", "chain": None,
            "why": "**폴리단백질인데 어느 성숙 사슬인지 못 정했다** — 사슬 %d개 "
                   "중 이름이 유일하게 맞는 것이 없다" % len(mature)}


def resolve(target: str, organism: Optional[str] = None) -> Dict[str, Any]:
    """표적 이름 → UniProt accession + **활성부위 잔기**.

    실패하면 error 를 그대로 올린다. `sites` 가 빈 리스트인 것과
    조회가 실패한 것은 다르다 — 후자는 `error` 가 찬다.
    """
    if not (target or "").strip():
        return {"accession": None, "name": "", "organism": "", "sites": [],
                "chains": [], "seq_len": None,
                "error": "표적 없음", "error_kind": "질의실패"}
    # **캐시 키를 v2 로 올린다.** 옛 키에는 `sites` 가 없어서 그대로 쓰면
    # 활성부위가 영구히 빈 채로 캐시에서 나온다 — 결함 5·26·27 계열이다.
    # v3 — `chains`·`seq_len`·`error_kind` 가 늘어서 또 올린다.
    key = "UNIPROT3::%s::%s" % (target.strip().lower(), (organism or "").lower())
    if cache.has(key):
        return cache.get(key)
    out = {"accession": None, "name": "", "organism": "", "sites": [],
           "chains": [], "seq_len": None, "error": None, "error_kind": None}
    try:
        # **정밀 → 느슨** 두 단계. 어느 쪽으로 찾았는지 기록한다 —
        # 느슨한 쪽은 정밀도가 낮으므로 **화면이 그 사실을 알아야 한다.**
        rs, stage = [], None
        for i, url in enumerate(_acc_queries(target, organism)):
            d = _get(url)
            rs = d.get("results") or []
            if rs:
                stage = "정확이름" if i == 0 else "자유텍스트"
                break
        if rs:
            r = rs[0]
            out["accession"] = r.get("primaryAccession")
            out["name"] = ((r.get("proteinDescription") or {}).get("recommendedName")
                           or {}).get("fullName", {}).get("value", "")
            out["organism"] = (r.get("organism") or {}).get("scientificName", "")
            out["sites"] = site_positions(r)
            out["chains"] = chains(r)
            out["seq_len"] = (r.get("sequence") or {}).get("length")
            out["match"] = stage
        else:
            # **문자열로 분기하지 않는다.** 08-10에 결함 88을 고치면서 이
            # 문구에 `(정확이름·자유텍스트 둘 다)` 를 붙였고, `assess()` 가
            # `== "UniProt 0건"` 으로 비교하고 있어서 **`구조없음` 분기가
            # 그날로 죽었다**(결함 91). 사람이 읽는 문구와 기계가 읽는
            # 값을 갈라 둔다.
            out["error"] = "UniProt 0건 (정확이름·자유텍스트 둘 다)"
            out["error_kind"] = "없음"
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
        out["error_kind"] = "질의실패"
    return cache.put(key, out)


def parse_pdb_tsv(text: str) -> int:
    """UniProt TSV → PDB 교차참조 **개수**. 네트워크를 안 탄다 — 시험용."""
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return 0
    return len([x for x in lines[1].replace("\t", "").split(";") if x.strip()])


def pdb_count(accession: str) -> Optional[int]:
    """이 UniProt 항목에 연결된 **실험 구조 개수**. 실패하면 `None`.

    ## 왜 이걸 세나 — **예측 구조를 쓸 이유가 없는 표적이 있다** (결함 94)

    08-10 실측: `SARS-CoV-2 3CL protease` 로 물으면 AlphaFold 예측 구조의
    pLDDT 를 답한다. 그런데 이 표적은 **실험 구조가 수천 건**이다 —
    `6LU7`(2020) 이 있고 `5R…`·`5S…`·`7G…`·`7H…` 계열이 통째로 Mpro
    단편 스크리닝이다. **결정 구조가 있는데 예측 구조로 신뢰도를 재는
    것은 자료원 선택의 오류**이고, 게이트가 아무리 정확해도 안 고쳐진다.

    ## 세는 것뿐이다 — **어느 사슬을 덮는지는 안 본다**

    이 수는 **UniProt 항목 전체**(pp1a 4,405잔기)에 붙은 것이라
    nsp3·nsp5·nsp12 구조가 다 섞여 있다. *"3CL 프로테아제의 실험 구조가
    N건"* 이라고 **말하면 안 된다** — 그게 정확히 결함 90이 한 짓
    (폴리단백질 전체의 수를 특정 사슬 것으로 말하기)이다.

    그래서 `assess()` 의 문구는 **"이 UniProt 항목에 연결된"** 이라고
    적고, 사슬 대응은 **안 봤다고 같이 적는다.**
    """
    if not accession:
        return None
    key = "PDBN::" + accession
    if cache.has(key):
        return cache.get(key)
    try:
        req = urllib.request.Request(UNIPROT_PDB % urllib.parse.quote(accession),
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
            n = parse_pdb_tsv(r.read().decode("utf-8", "replace"))
    except Exception:
        return None                      # **0 이 아니다.** 못 센 것과 없는 것은 다르다
    return cache.put(key, n)


def pick_fragment(entries: List[Dict[str, Any]],
                  want: Optional[Tuple[int, int]] = None) -> Optional[Dict[str, Any]]:
    """AFDB 단편 목록 → **원하는 구간을 가장 많이 덮는 하나.**

    **네트워크를 안 탄다** — 시험용으로 따로 뺀다.

    `want` 가 없으면 첫 항목을 준다(전장 모델이면 그게 맞다). `want` 가
    있는데 **겹치는 단편이 하나도 없으면 `None`** 을 준다 — 아무거나
    집어서 답을 만드는 것이 결함 90·98이었다.
    """
    if not entries:
        return None
    if not want:
        return entries[0]
    a, b = want
    best, cover = None, 0
    for e in entries:
        s0, e0 = e.get("uniprotStart"), e.get("uniprotEnd")
        if not isinstance(s0, int) or not isinstance(e0, int):
            continue
        ov = min(b, e0) - max(a, s0) + 1
        if ov > cover:
            best, cover = e, ov
    return best


def site_stats(vals: List[float], sites: List[int],
               start: Optional[int] = None) -> Dict[str, Any]:
    """잔기 번호 목록으로 pLDDT 부분 통계. **범위를 벗어난 것은 버리고 센다.**

    ## `start` 가 이 함수의 전부다 (결함 90 → 98)

    초판은 `vals[p-1]` 이었다. **모델이 UniProt 1번 잔기에서 시작한다는
    가정**이고, 확인한 적이 없었다. 08-11 실측에서 깨졌다 —

        P0DTC1 은 4,405잔기인데 모델은 **1566–1868** 구간의 303잔기였다

    그러니 `vals[199]` 는 UniProt 200번이 아니라 **1765번**이다. 넉넉히
    빗나간 잔기의 pLDDT 를 *"활성부위"* 라고 부르고 있었다.

    이제 `start` 를 **반드시 밖에서 받는다.** 기본값 1을 두긴 하지만
    그건 전장 모델(`uniprotStart == 1`)일 때만 맞고, 부르는 쪽이
    AFDB 응답의 `uniprotStart` 를 그대로 넘긴다.

    범위 밖은 버리고 **몇 개가 버려졌는지 같이 돌려준다** — 조용히
    잘라내면 주석 5개 중 1개만 맞았는데도 평균이 나온다.
    """
    lo = start or 1
    idx = [p - lo for p in sites if lo <= p < lo + len(vals)]
    # **키 이름을 `plddt` 와 겹치지 않게 한다.** `start` 로 두면
    # `out.update(site_stats(...))` 가 `plddt` 의 `start`(=uniprotStart, 없으면
    # None)를 1 로 덮어써서 **"번호 틀을 모른다"는 신호가 지워진다.**
    # 실제로 그렇게 만들었고 시험 [72]가 잡았다.
    out = {"n_site": len(sites), "n_site_used": len(idx), "site_start": lo,
           "site_mean": None, "site_min": None, "out_of_range": len(sites) - len(idx)}
    if not idx:
        return out
    v = [vals[i] for i in idx]
    out["site_mean"] = round(sum(v) / len(v), 1)
    out["site_min"] = round(min(v), 1)
    return out


def plddt(accession: str, sites: Optional[List[int]] = None,
          want: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
    """AlphaFold DB → pLDDT 통계. `sites` 를 주면 **활성부위 통계도** 낸다.

    **결합력이 아니다.** 이 값이 높다는 것은 *구조 예측을 믿을 만하다*는
    뜻이지 *약이 붙는다*는 뜻이 아니다. 모듈 독스트링 참조.

    돌려주는 것:
      mean · min · frac_low        — 단백질 **전체** 분포
      site_mean · site_min         — **활성부위만** (§2.5 가 요구한 것)
      n_site · n_site_used         — 주석 수 / 그중 모델 범위 안
      cif_url · pdb_url            — 3Dmol.js 가 읽을 주소 (§3.3-10)
      start · end                  — 이 모델이 덮는 **UniProt 구간**
      n_frag                       — 응답에 온 단편 수
      error                        — 실패는 실패라고 적는다. 0으로 채우지 않는다

    ## `want` — **어느 구간을 원하는가** (결함 98)

    AFDB 는 긴 단백질을 **단편으로 쪼개** 여러 항목으로 돌려준다. 초판은
    `d[0]` 을 그냥 집었다. P0DTC1 실측에서 그 첫 항목이 **1566–1868**
    (PLpro 영역)이었고, 우리가 물은 것은 **3CL 프로테아제(3264–3569)**
    였다. **겹치는 구간이 0인 단편을 놓고 답을 만들고 있었다.**

    `want=(start, end)` 를 주면 **그 구간과 가장 많이 겹치는 단편**을
    고른다. 겹치는 게 하나도 없으면 그렇다고 적는다 — 아무거나 집지 않는다.
    """
    out = {"accession": accession, "mean": None, "min": None, "frac_low": None,
           "n_res": None, "cif_url": None, "pdb_url": None,
           "site_mean": None, "site_min": None, "n_site": 0, "n_site_used": 0,
           "out_of_range": 0, "version": None, "start": None, "end": None,
           "n_frag": 0, "error": None}
    if not accession:
        out["error"] = "accession 없음"
        return out
    # 전체 분포는 표적과 무관하게 같으므로 accession 으로 캐시한다.
    # **활성부위 통계는 캐시하지 않는다** — `sites` 가 키에 없어서
    # 캐시하면 다른 표적의 부위 통계가 섞인다. 계산이 리스트 인덱싱뿐이라
    # 다시 하는 비용이 0에 가깝다.
    # v3 — 단편 선택이 `want` 에 달렸으므로 **키에 넣는다.** 안 넣으면
    # 다른 표적이 고른 단편이 캐시에서 나온다(결함 5·26·27 계열).
    key = "AFDB3::%s::%s" % (accession, "%d-%d" % want if want else "-")
    cached = cache.get(key) if cache.has(key) else None
    if cached is not None:
        out = dict(cached)
        vals = out.pop("_vals", None) or []
    else:
        vals = []
        try:
            d = _get(AFDB % urllib.parse.quote(accession))
            if not d:
                out["error"] = "AlphaFold 미수록"
                return cache.put(key, out)
            ents = d if isinstance(d, list) else [d]
            out["n_frag"] = len(ents)
            e = pick_fragment(ents, want)
            if e is None:
                out["error"] = "요청 구간을 덮는 단편 없음"
                return cache.put(key, out)
            out["cif_url"] = e.get("cifUrl")
            out["pdb_url"] = e.get("pdbUrl")
            out["version"] = e.get("latestVersion") or e.get("modelCreatedDate")
            # **실측으로 확인한 이름이다** (08-11 · P0DTC1 → 1566/1868).
            # 결함 89 는 이 자리에서 이름을 **지어내서** 났다.
            out["start"] = e.get("uniprotStart")
            out["end"] = e.get("uniprotEnd")
            vals = _confidence(e)
            if not vals:
                out["error"] = "pLDDT 배열 없음"
                return cache.put(key, out)
            n = len(vals)
            out["n_res"] = n
            out["mean"] = round(sum(vals) / n, 1)
            out["min"] = round(min(vals), 1)
            out["frac_low"] = round(sum(1 for v in vals if v < PLDDT_OK) / n, 3)
            cache.put(key, dict(out, _vals=vals))
        except urllib.error.HTTPError as e:
            # ── **404 는 "없다" 이지 "못 봤다" 가 아니다** (결함 107) ──
            #
            #   08-11 실측: `oseltamivir / Influenza` → 라우터가 구조로
            #   보냈고 S1 이 `ERROR · HTTP Error 404` 를 냈다. 그런데
            #   AFDB 는 **수록된 것에 200+JSON, 없는 것에 404** 를 준다
            #   (P0DTC1 은 200 이었다). 즉 이건 조회 실패가 아니라 **답**이다.
            #
            #   갈라야 하는 이유는 라벨이 다르기 때문이다 —
            #     `오류`    경로를 **안 바꾼다.** 후보가 구조 경로에 남는데
            #               뒤에 아무것도 없다 (제자리에 갇힌다)
            #     `구조없음` 증거 경로로 내려간다 — **설계가 원하는 처분**
            #
            #   결함 35(조회 실패를 0건으로 셈)의 **반대 방향**이다.
            #   그때는 없음을 실패로 안 읽으려고 했고, 여기서는 실패로
            #   읽고 있었다. 둘 다 같은 구분을 못 한 것이다.
            #
            #   **5xx·타임아웃은 그대로 `오류`다.** 그건 진짜 못 본 것이다.
            if e.code == 404:
                out["error"] = "AlphaFold 미수록"
                return cache.put(key, out)
            out["error"] = "HTTP %d" % e.code
            return out
        except Exception as e:
            out["error"] = "%s: %s" % (type(e).__name__, e)
            return out
    if sites and vals:
        out.update(site_stats(vals, sites, out.get("start")))
    elif sites and not vals:
        # 캐시가 배열을 안 갖고 있으면 **활성부위를 계산할 수 없다.**
        # 전체 평균으로 조용히 대체하지 않는다.
        out["out_of_range"] = len(sites)
        out["n_site"] = len(sites)
    return out


def _confidence(entry: Dict[str, Any]) -> List[float]:
    """응답에서 잔기별 pLDDT 배열을 꺼낸다.

    AFDB 응답 형태가 판마다 달랐다. 셋 다 받는다 — 하나만 가정하면
    스키마가 바뀐 날 **조용히 빈 배열**이 되고, 그러면 `error` 없이
    "구조없음"이 된다. 그게 결함 35와 같은 고장이다.
    """
    for k in ("confidenceScore", "plddt", "confidenceList"):
        v = entry.get(k)
        if isinstance(v, list) and v:
            return [float(x) for x in v if isinstance(x, (int, float))]
    u = entry.get("confidenceUrl") or entry.get("paeDocUrl")
    if u:
        try:
            d = _get(u)
            v = (d.get("confidenceScore") if isinstance(d, dict) else None) or []
            if v:
                return [float(x) for x in v]
        except Exception:
            pass
    # ── 마지막 경로: **좌표 파일의 B-factor** (결함 89) ─────────────
    #
    #   위 세 이름은 전부 **모의를 보고 지은 것**이었다. 08-10에 승우가
    #   진짜 AFDB 를 태우니 셋 다 없었고 `pLDDT 배열 없음` 이 떴다.
    #
    #   AlphaFold 는 잔기별 pLDDT 를 **API 본문에 안 싣는다.** 좌표
    #   파일의 **B-factor 칸**에 넣는다 — 그게 AFDB 의 공식 표기법이다.
    #   `cifUrl`·`pdbUrl` 은 응답에 있었으니(승우 실측) 거기서 읽는다.
    #
    #   PDB 는 고정 폭 형식이라 파서가 필요 없다. `CA` 원자만 세면
    #   잔기당 하나가 나온다.
    return _bfactors(entry.get("pdbUrl") or "")


def _bfactors(pdb_url: str) -> List[float]:
    """PDB 좌표 파일의 `CA` 원자 B-factor = AlphaFold pLDDT.

    **형식이 고정 폭이다** — 컬럼 위치가 규격이라 split 하면 안 된다
    (좌표가 붙어 나오는 줄이 있다). 61~66 이 B-factor 칸이다.
    """
    if not pdb_url:
        return []
    try:
        req = urllib.request.Request(pdb_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
            txt = r.read().decode("utf-8", "replace")
    except Exception:
        return []
    return parse_bfactors(txt)


def parse_bfactors(text: str) -> List[float]:
    """PDB 본문 → `CA` B-factor 목록. **네트워크를 안 탄다** — 시험용."""
    out = []
    for line in text.splitlines():
        if line.startswith(("ATOM  ", "HETATM")) and line[12:16].strip() == "CA":
            try:
                out.append(float(line[60:66]))
            except ValueError:
                continue
    return out


def assess(target: str, organism: Optional[str] = None) -> Dict[str, Any]:
    """표적 → S1 판정. **라벨이지 점수가 아니다.**

      신뢰    : pLDDT ≥ 70 — 좌표 신뢰도가 높다. **필요조건이지 충분조건이
                아니다** — 활성부위가 전부 70 이상인데 도킹이 실패한 사례가
                문헌에 있다(PMC9852548 · 결함 65). 성공을 예측하지 않는다
      저신뢰  : 70 미만 — 무질서 영역 가능. **연산 제외이지 기각이 아니다**
      신뢰도미상: **구조는 있는데** pLDDT 를 못 읽었다 (결함 89).
                좌표는 그릴 수 있다. **구조없음과 다르다**
      구조없음: AlphaFold 에 **정말로** 없다
      오류    : 조회 실패. **0건과 구분한다**

    ## 무엇을 기준으로 재는가 — `basis` 를 반드시 읽어라

      `활성부위`   UniProt 주석 잔기의 pLDDT 평균. **§2.5 가 요구한 것**
      `전체평균`   주석이 없어서 단백질 전체 평균으로 내려간 것.
                 **약한 대리물이다** — 무질서 말단이 값을 끌어내린다

    그동안 줄곧 전부 `전체평균` 이었고 문서에는 §2.5 문구(`활성부위`)를
    적어 뒀다. **조용히 대리물을 쓰는 것이 그 자체로 결함이다**(결함 47).
    그래서 이제 `basis` 를 판정에 실어 보내고 `why` 에 적는다.
    """
    r = resolve(target, organism)
    if r.get("error"):
        # `error_kind` 로 가른다. **문구로 비교하면 문구를 고친 날 죽는다**
        # — 실제로 죽었다(결함 91).
        lab = "구조없음" if r.get("error_kind") == "없음" else "오류"
        return {"label": lab, "why": "UniProt: " + r["error"], "uniprot": r,
                "plddt": None, "cif_url": None, "basis": None, "chain": None,
                "pdb_n": None}

    # 실험 구조가 있으면 **예측 구조는 대리물이다** (결함 94).
    #
    #   08-13 — 이 주석의 뒷문장이 «S3 도킹이 로드맵이라 쓸 데가 없다» 였다.
    #   **그 전제가 08-13에 바뀌었다**(결함 169 뒤집음 · 제안서 게이트표가
    #   S3 를 직접결합 한정으로 허용한다). 그런데도 **판정은 그대로 둔다** —
    #   이유가 달라졌다.
    #
    #     바뀐 이유  라벨을 여기서 바꾸면 **동결 벤치마크의 수치가 전부 무효**가
    #                된다. 결과를 보고 고친 뒤 같은 벤치마크로 재는 것이라
    #                `CLAUDE.md §3-2` 위반이다.
    #     대신       `pdb_n` 을 실어 보내고, **도킹 경로만** 그것을 읽어
    #                예측 구조 대신 실험 구조로 간다(`bench/dockcheck.apo_scan`).
    #
    #   **화면이 사실을 말하게 할 뿐이다.**
    npdb = pdb_count(r.get("accession"))

    def _out(label, why, basis, chain, r, p):
        """판정 하나를 조립한다. **실험 구조 사실을 빠뜨릴 수 없게** 한 곳에서.

        결함 90·92 가 둘 다 *"여러 반환 지점 중 한 곳만 고쳤다"* 였다.
        반환을 하나로 모으면 다음에 항목이 늘어도 **전부에 실린다.**
        """
        # **`why` 에 안 붙인다** (결함 108). 이 문자열은 게이트 추적표의
        # 한 칸으로도 들어가는데, 붙였더니 행이 **243자**가 돼 가로
        # 스크롤이 생겼다(시험 [61]). 뷰어는 `pdb_n` 을 직접 읽으므로
        # 화면에서 잃는 것이 없다 — **좁은 칸과 넓은 칸은 다른 글을 받는다.**
        return {"label": label, "why": why, "basis": basis, "chain": chain,
                "uniprot": r, "plddt": p, "cif_url": (p or {}).get("cif_url"),
                "pdb_n": npdb}

    # ── 성숙 사슬로 좁힌다 (결함 90) ───────────────────────────────────
    loc = localize(target, r.get("chains") or [], r.get("seq_len"))
    sites = r.get("sites") or []
    if loc["kind"] == "국소화":
        c = loc["chain"]
        sites = [p for p in sites if c["start"] <= p <= c["end"]]
    c0 = loc.get("chain")
    want = (c0["start"], c0["end"]) if c0 else None
    p = plddt(r["accession"], sites, want)
    if p.get("error"):
        # ── **없는 것과 못 잰 것을 가른다** (결함 89) ────────────────
        #
        #   08-10 실측에서 이 자리가 거짓말을 했다 —
        #
        #     구조는 **있었다**  cif_url: AF-…-model_v1.cif  (응답에 있었다)
        #     화면이 말한 것     "구조없음"
        #
        #   `AlphaFold 미수록` 은 진짜로 없는 것이고, `pLDDT 배열 없음` 은
        #   **있는데 신뢰도를 못 읽은 것**이다. 둘을 같은 라벨로 묶으면
        #   결함 35와 같은 고장이 된다 — *조회 실패를 0건으로 셈.*
        #
        #   그리고 **좌표 주소를 버리면 안 된다.** 뷰어(§3.3-10)는 pLDDT
        #   없이도 구조를 그릴 수 있다. 신뢰도 색칠만 못 할 뿐이다.
        if p["error"] == "AlphaFold 미수록":
            lab, why = "구조없음", "AlphaFold 에 이 표적의 예측 구조가 없다"
        elif p["error"] == "pLDDT 배열 없음":
            lab = "신뢰도미상"
            why = ("**구조는 있는데 pLDDT 를 못 읽었다.** 좌표는 그릴 수 "
                   "있으나 신뢰도 판정은 못 한다 — **구조가 없다는 뜻이 아니다**")
        else:
            lab, why = "오류", "AlphaFold: " + p["error"]
        return _out(lab, why, None, None, r, p)

    # ── 거절 조건 둘. **여기서 막지 않으면 결함 90이 재현된다** ─────────
    #
    #   ① 어느 성숙 사슬인지 모르면 부위 통계를 내지 않는다
    #   ② **좌표 번호와 UniProt 번호가 같다는 보장이 없으면** 내지 않는다
    #
    #   ②가 08-10 실측에서 터진 자리다. P0DTC1 은 4,405잔기인데 모델은
    #   303잔기였다. `site_stats` 는 `vals[p-1]` 로 읽으므로 **모델이 1번
    #   잔기에서 시작한다고 가정**한 것이고, 그 가정을 확인한 적이 없다.
    #   AFDB 응답에 오프셋 필드가 있을 수 있으나 **이름을 모른다** —
    #   모르는 필드 이름을 지어내는 것이 바로 결함 89였다. 알 때까지 거절한다.
    unk = None
    if loc["kind"] == "모호":
        unk = loc["why"] + " — 사슬을 못 정한 채 폴리단백질 전체의 주석을 " \
                           "평균 내면 **다른 단백질의 값이 섞인다**"
    elif (p.get("start") is None and r.get("seq_len")
          and r["seq_len"] != p.get("n_res")):
        # 오프셋을 못 읽었는데 길이도 안 맞으면 **번호를 못 맞춘다.**
        unk = ("**좌표 번호와 UniProt 번호를 맞출 수 없다** — UniProt %s잔기 · "
               "모델 %s잔기인데 응답에 `uniprotStart` 가 없다"
               % (r.get("seq_len"), p.get("n_res")))
    if unk:
        return _out("신뢰도미상", unk, None, loc.get("chain"), r, p)

    if p.get("site_mean") is not None:
        basis, val = "활성부위", p["site_mean"]
        why = ("활성부위 pLDDT %.1f — 주석 잔기 %d개 중 %d개"
               % (val, p["n_site"], p["n_site_used"]))
        if loc["kind"] == "국소화":
            why += " · " + loc["why"]
        if p.get("out_of_range"):
            why += " · **모델 범위 밖 %d개 제외**" % p["out_of_range"]
        why += " · (전체 평균은 %.1f)" % p["mean"]
    elif sites:
        # 사슬은 정했는데 **그 사슬에 주석이 하나도 안 남았다.** 전체
        # 평균으로 내려가면 다시 다른 단백질 얘기가 된다.
        return _out("신뢰도미상",
                    "**이 사슬의 주석 잔기가 모델에 하나도 없다** (%d개 전부 범위 밖)"
                    % p.get("out_of_range", len(sites)),
                    None, loc.get("chain"), r, p)
    else:
        basis, val = "전체평균", p["mean"]
        # 짧게 — 게이트 표의 한 칸에 들어간다. 자세한 것은 뷰어가 말한다.
        why = ("전체 평균 pLDDT %.1f · 70 미만 %.0f%% — "
               "**활성부위 주석 없음. 약한 대리물**"
               % (val, 100 * p["frac_low"]))
    return _out("신뢰" if val >= PLDDT_OK else "저신뢰", why, basis,
                loc.get("chain"), r, p)
