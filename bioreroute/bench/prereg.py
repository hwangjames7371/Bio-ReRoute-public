"""사전 기준 대장 — **봉인한 기준 가운데 몇 개가 통과했고 몇 개가 미달했나** 를 센다.

## 왜 만들었나 (09-25)

«사전 기준이 붙고 결과가 나온 **넷 중 셋이 미달**» 이 1페이지·README·
보고서·발표 대본·슬라이드에 박혀 있었다. 09-25 에 봉인 31개를 전부 읽고
기준마다 세 보니 **결과가 나온 기준은 넷이 아니라 39개**였다.

  · «넷» 은 **08-05 첫 봉인의 넷**이었다. 그 뒤 스물일곱 번의 봉인은
    서사에 한 번도 안 들어왔다 — 라우터분기·역발상·모델교체의 통과도,
    재현성 72/84·본선 모델 주② 0.939 의 미달도.
  · 넷 안에서도 **생성은 통과**였다(빗나간 것은 예측이다). 깔때기는
    자기 명세의 분기에 따라 **«모른다»** 였다(검정력 60%).
  · 비율 75% 는 전체 기록보다 **나빠 보이고**, 건수 3 은 실제 미달보다
    **적다.** 양쪽으로 틀린 수였다.

결함 303 이 이미 적었다 — 이 수는 «기계로 못 센다». **맞다. 분류는 판단이다.**
그래서 이 도구는 분류를 대신하지 않는다. 대신 **다음 넷을 기계로 막는다** —

  ① 봉인 명세가 대장에서 빠지면 멈춘다       ← 새 봉인이 서사에서 또 빠지는 것
  ② 근거 인용이 그 파일에 실제로 있어야 한다   ← 손으로 옮긴 수(결함 19)
  ③ «실행 중» 인데 결과 파일이 생겼으면 멈춘다  ← 대장이 낡는 것
  ④ 문서의 집계 문장이 이 도구의 수와 같아야 한다 ← `docaudit` 가 부른다

**셈법이 판단을 탄다는 것도 숨기지 않는다.** `셈` 열의 표시로 다른 셈법의
폭을 같이 낸다 — 문서 표기대로 · 09-20 재적용 제외 · 철회한 통과 제외.
어느 셈법이든 미달은 12~16 개다. **한 수만 고르지 않고 폭을 같이 적는다.**

    py -m bioreroute.bench.prereg            # 집계 · 셈법별 폭 · 확인
    py -m bioreroute.bench.prereg --md       # 부록용 표 (표준 출력)
    py -m bioreroute.bench.prereg --json     # 기계용 (표준 출력)

**파일을 쓰지 않는다.** 대장(`사전기준_대장.csv`)은 사람이 고친다 —
결과가 나오면 «실행 중» 행을 분류로 바꾸고 근거 인용을 적는다.
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, OrderedDict

from .docaudit import ROOT, sealed_docs, _fenced, _skip

LEDGER = "사전기준_대장.csv"
COLS = ("번호", "명세", "기준", "분류", "근거", "인용", "셈", "비고")

KINDS = ("통과", "미달", "판정 불가", "실행 중", "실행 안 함", "기준 없음")
DONE = ("통과", "미달", "판정 불가")          # 결과가 나온 것 — 분모
FLAGS = ("표기=미달", "재적용", "철회", "사례", "판단")

# 셈법 — **판단이 들어가는 자리마다 다른 쪽으로 셌을 때의 수**를 같이 낸다
WAYS = OrderedDict([
    ("기본", "대장의 분류 그대로"),
    ("문서 표기대로", "`표기=미달` 행을 미달로 — 요약 문서들이 그렇게 적었다"),
    ("재적용 제외", "09-20 에 같은 기준을 새 모델에 다시 댄 행을 뺀다"),
    ("철회 제외", "나중에 주장을 거둔 통과(ECE)를 분모에서 뺀다"),
])

# ── 집계 문장 — **이 꼴 하나만** 쓴다. `docaudit` 가 이 꼴을 읽는다 ──
#   「사전 기준 39개 — 통과 18 · 미달 13 · 판정 불가 8」
SENTENCE = "사전 기준 %d개 — 통과 %d · 미달 %d · 판정 불가 %d"
_SENT = re.compile(
    r"사전 기준\s*\**\s*(\d{1,3})\s*개\s*\**\s*—\s*\**\s*통과\s*\**\s*(\d{1,3})"
    r"\s*\**\s*·\s*\**\s*미달\s*\**\s*(\d{1,3})\s*\**\s*·\s*\**\s*판정 불가"
    r"\s*\**\s*(\d{1,3})")

# ── 옛 서사 — **제출물과 발표 대본에서** 현재 주장으로 쓰면 안 되는 꼴 ──
#   날짜가 박힌 기록 문서(`우선순위_0916` 등)는 그때의 판단이므로 안 본다.
#   인용(«…» · *"…"*)이나 결함 번호가 붙은 줄은 기록이다 — 건너뛴다.
OLD_PHRASES = ("넷 중 셋이 미달", "넷 중 셋 미달", "넷 중 셋을 통과하지 못했다",
               "넷 중 셋이 기준에 못 미쳤")
NARRATIVE_DOCS = ("Bio-ReRoute_1페이지.md", "README.md", "연구기술보고서.md",
                  "발표뼈대.md", "시연영상_대본.md", "심사기준대조.md",
                  "선행연구대조.md", "재현절차.md",
                  # ⚠ `Q&A카드_1장.md` · `발표대본_10분.md` 는 **8월 기록**이다
                  #   (`docaudit.LOG`). 그때 쓴 것이라 옛 서사가 남는 게 정상이다 —
                  #   09-25 에 한 번 고쳤다가 되돌렸다. 본선 Q&A 는 새로 만든다.
                  "발표대본_본선10분.md", "slides/build_deck.py",
                  "slides/make_10min_본선.py",
                  # **구운 파일도 본다** — 소스만 고치고 안 구우면 제출물이 낡는다(결함 60)
                  "slides/Bio-ReRoute_발표.pptx", "slides/Bio-ReRoute_본선_10분.pptx")

_MARK = re.compile(r"\*\*|\*|`")


def norm(s):
    """굵게·기울임·코드 표시를 걷고 공백을 한 칸으로 — 인용은 **글자**로 대조한다."""
    return re.sub(r"\s+", " ", _MARK.sub("", s or "")).strip()


def load(root=ROOT):
    p = os.path.join(root, LEDGER)
    with open(p, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["번호"] = int(r["번호"])
        r["명세들"] = [x.strip() for x in r["명세"].split("+") if x.strip()]
        r["셈들"] = [x for x in re.split(r"[\s,]+", r.get("셈") or "") if x]
    return rows


def sealed_specs(root=ROOT):
    """봉인된 **사전명세** — `docaudit._spec_count` 와 같은 규칙(봉인 json 이 지목한 것)."""
    out = set()
    for d in sealed_docs(root):
        b = os.path.basename(d)
        if b.startswith("사전명세") and b.endswith(".md") \
                and os.path.exists(os.path.join(root, b)):
            out.add(b)
    return out


def check(root=ROOT, rows=None):
    """문제 목록. **비어 있어야** 대장의 수를 문서에 쓸 수 있다."""
    rows = load(root) if rows is None else rows
    bad = []
    seen = Counter(r["번호"] for r in rows)
    bad += ["번호 %d 가 %d번 나온다" % (k, v) for k, v in sorted(seen.items()) if v > 1]
    for r in rows:
        if r["분류"] not in KINDS:
            bad.append("#%d 분류 «%s» 는 없는 분류다 %s" % (r["번호"], r["분류"], KINDS))
        for g in r["셈들"]:
            if g not in FLAGS:
                bad.append("#%d 셈 표시 «%s» 는 없는 표시다 %s" % (r["번호"], g, FLAGS))

    # ① 봉인 명세가 전부 있나 · 봉인 안 된 것이 섞였나
    have = {s for r in rows for s in r["명세들"]}
    want = sealed_specs(root)
    bad += ["봉인 명세 %s 가 대장에 없다 — 기준을 적어라(기준이 없으면 «기준 없음» 행)" % s
            for s in sorted(want - have)]
    bad += ["대장의 %s 는 봉인된 사전명세가 아니다" % s for s in sorted(have - want)]

    # ② 인용 · ③ 실행 중인데 결과가 나왔나
    texts = {}
    for r in rows:
        p = os.path.join(root, r["근거"])
        if r["분류"] == "실행 중":
            if os.path.exists(p):
                bad.append("#%d %s — 결과 파일 %s 가 생겼다. «실행 중» 을 분류로 바꿔라"
                           % (r["번호"], r["명세"], r["근거"]))
            continue
        if not os.path.exists(p):
            bad.append("#%d 근거 파일 %s 가 없다" % (r["번호"], r["근거"]))
            continue
        if not norm(r["인용"]):
            bad.append("#%d 인용이 비었다" % r["번호"])
            continue
        if p not in texts:
            with open(p, encoding="utf-8", errors="replace") as f:
                texts[p] = norm(f.read())
        if norm(r["인용"]) not in texts[p]:
            bad.append("#%d 인용을 %s 에서 못 찾았다 — «%s»"
                       % (r["번호"], r["근거"], r["인용"][:60]))
    return bad


def _kind(r, way):
    """셈법 `way` 에서 이 행을 어떻게 세나. None 이면 분모에서 뺀다."""
    k = r["분류"]
    if way == "문서 표기대로" and "표기=미달" in r["셈들"]:
        return "미달"
    if way == "재적용 제외" and "재적용" in r["셈들"]:
        return None
    if way == "철회 제외" and "철회" in r["셈들"] and k == "통과":
        return None
    return k


def tally(rows, way="기본"):
    c = Counter()
    for r in rows:
        k = _kind(r, way)
        if k is not None:
            c[k] += 1
    out = OrderedDict((k, c.get(k, 0)) for k in KINDS)
    out["결과"] = sum(out[k] for k in DONE)
    return out


def by_spec(rows):
    """명세 단위 — 결과가 나온 명세마다 «전부 통과 / 미달 있음 / 그 밖»."""
    got = {}
    for r in rows:
        if r["분류"] not in DONE:
            continue
        for s in r["명세들"]:
            got.setdefault(s, []).append(r["분류"])
    c = Counter()
    for s, ks in got.items():
        if "미달" in ks:
            c["미달 있음"] += 1
        elif all(k == "통과" for k in ks):
            c["전부 통과"] += 1
        else:
            c["판정 불가 섞임"] += 1
    return {"명세": len(got), "전부 통과": c["전부 통과"],
            "미달 있음": c["미달 있음"], "판정 불가 섞임": c["판정 불가 섞임"]}


def sentence(t):
    return SENTENCE % (t["결과"], t["통과"], t["미달"], t["판정 불가"])


def summary(root=ROOT):
    rows = load(root)
    ways = OrderedDict((w, tally(rows, w)) for w in WAYS)
    fails = [t["미달"] for t in ways.values()]
    return {
        "대장": LEDGER, "행": len(rows), "봉인_명세": len(sealed_specs(root)),
        "기본": ways["기본"], "셈법": ways,
        "미달_폭": [min(fails), max(fails)],
        "명세단위": by_spec(rows),
        "문장": sentence(ways["기본"]),
        "문제": check(root, rows),
    }


def doc_problems(root=ROOT, canon=None, texts=None):
    """문서가 **대장과 다른 수**를 쓰거나 **옛 서사**를 현재 주장으로 쓰는 곳.

    `texts` 를 주면 파일 대신 그것을 본다({이름: 본문}) — 시험용.
    """
    if canon is None:
        canon = tally(load(root))
    want = (canon["결과"], canon["통과"], canon["미달"], canon["판정 불가"])
    out = []
    for d, text in sorted((texts if texts is not None else _texts(root)).items()):
        lines = text.split("\n")
        fenced = _fenced(text)
        for m in _SENT.finditer(text):
            ln = text[:m.start()].count("\n") + 1
            if ln in fenced or _skip(lines[ln - 1]):
                continue
            got = tuple(int(x) for x in m.groups())
            if got != want:
                out.append("%s:%d  «%s» — 대장은 «%s»"
                           % (d, ln, m.group(0), SENTENCE % want))
        if d not in NARRATIVE_DOCS:
            continue
        for ln, line in enumerate(lines, 1):
            if ln in fenced:
                continue
            lo = line.lstrip()
            # 결함 **번호**(`결함 303`)가 붙은 줄은 기록이다. 결함 **건수**
            # (`결함 323건`)는 현재 주장이므로 건너뛰지 않는다 — 첫 판이 둘을
            # 같이 건너뛰어 `build_deck.py:1163` 을 놓쳤다.
            if ("«" in line or '*"' in line or re.search(r"결함\s*\d+(?![\d건])", line)
                    or lo.startswith("#") and d.endswith(".py")):
                continue
            for ph in OLD_PHRASES:
                if ph in line:
                    out.append("%s:%d  옛 서사 «%s» — 대장 집계로 바꿔라" % (d, ln, ph))
    return out


def sync(root=ROOT, files=None, apply=True):
    """집계 문장을 **대장의 현재 수로** 맞춘다 — 결과가 들어올 때마다 손으로 고치지 않게.

    09-25 새벽에 표적 재시험 결과 한 줄(대장 45행)이 들어오자 **문서 열두 곳**이
    한꺼번에 낡았다(`doc_problems` 가 잡았다). 잡는 눈은 있고 고치는 손이 없으면
    결함 309 의 자리다(«같은 한 줄을 하루에 세 번 손으로 고쳤다»).

    - 고치는 것은 **`SENTENCE` 꼴 하나뿐**이다. 다른 수는 안 만진다
    - **봉인 문서 · 기록(`docaudit.LOG`) · 구운 pptx 는 안 만진다** — pptx 는 다시 굽는다
    - 코드 펜스 안 · 결함 대장 행(`_skip`)은 기록이라 건너뛴다
    - 돌려주는 것: [(파일, 줄, 옛 문장)]
    """
    from .docaudit import DOCS, LOG
    want = sentence(tally(load(root)))
    sealed = {os.path.basename(x) for x in sealed_docs(root)}
    if files is None:
        files = sorted((set(DOCS) | set(NARRATIVE_DOCS)) - set(LOG))
    changed = []
    for d in files:
        if d.endswith(".pptx") or os.path.basename(d) in sealed:
            continue
        p = os.path.join(root, d)
        if not os.path.exists(p):
            continue
        raw = open(p, "rb").read()
        text = raw.decode("utf-8-sig")
        bom = raw[:3] == b"\xef\xbb\xbf"
        lines = text.split("\n")
        fenced = _fenced(text)
        out, last = [], 0
        for m in _SENT.finditer(text):
            ln = text[:m.start()].count("\n") + 1
            if ln in fenced or _skip(lines[ln - 1]) or m.group(0) == want:
                continue
            out.append(text[last:m.start()])
            out.append(want)
            last = m.end()
            changed.append((d, ln, m.group(0).replace("\n", " ")))
        if out and apply:
            out.append(text[last:])
            new = "".join(out)
            with open(p, "wb") as f:
                f.write((b"\xef\xbb\xbf" if bom else b"") + new.encode("utf-8"))
    return changed


def _texts(root):
    """감사할 글 — `docaudit` 의 DOCS · EXTRA(구운 pptx 포함) + 서사 문서."""
    from .docaudit import DOCS, EXTRA, _pptx_text
    readers = dict(EXTRA)
    names = set(DOCS) | set(NARRATIVE_DOCS) | set(readers)
    out = {}
    for d in names:
        p = os.path.join(root, d)
        if not os.path.exists(p):
            continue
        reader = readers.get(d) or (_pptx_text if d.endswith(".pptx") else None)
        try:
            out[d] = reader(p) if reader else open(p, encoding="utf-8", errors="replace").read()
        except Exception as e:                  # 잠긴 pptx 등 — 조용히 넘기지 않는다
            out[d] = ""
            print("  ⚠ %s 를 못 읽었다 — %s" % (d, e))
    return out


def to_md(rows):
    head = "| # | 명세 | 기준 | 분류 | 근거 | 셈 | 비고 |\n|---|---|---|---|---|---|---|"
    body = []
    for r in rows:
        spec = " + ".join(s.replace("사전명세_", "").replace(".md", "") or s
                          for s in r["명세들"])
        spec = spec.replace("사전명세", "첫 봉인(08-05)")
        body.append("| %d | %s | %s | %s | `%s` | %s | %s |" % (
            r["번호"], spec, r["기준"].replace("|", "\\|"), r["분류"], r["근거"],
            r.get("셈") or "", (r.get("비고") or "").replace("|", "\\|")))
    return head + "\n" + "\n".join(body)


def report(s):
    b = s["기본"]
    print("사전 기준 대장 — %s · %d행 · 봉인 사전명세 %d개" % (s["대장"], s["행"], s["봉인_명세"]))
    print()
    print("  통과 %d · 미달 %d · 판정 불가 %d   (결과가 나온 기준 %d)"
          % (b["통과"], b["미달"], b["판정 불가"], b["결과"]))
    print("  실행 중 %d · 실행 안 함 %d · 기준 없음 %d"
          % (b["실행 중"], b["실행 안 함"], b["기준 없음"]))
    print()
    print("  셈법에 따라 —")
    for w, t in s["셈법"].items():
        print("    %-10s 통과 %2d · 미달 %2d · 판정 불가 %2d  (결과 %d)   %s"
              % (w, t["통과"], t["미달"], t["판정 불가"], t["결과"], WAYS[w]))
    print("    → 미달 %d~%d" % tuple(s["미달_폭"]))
    m = s["명세단위"]
    print()
    print("  명세 단위 (결과가 나온 %d개) — 전부 통과 %d · 미달 있음 %d · 판정 불가 섞임 %d"
          % (m["명세"], m["전부 통과"], m["미달 있음"], m["판정 불가 섞임"]))
    print()
    print("  문장 — 문서에는 이 꼴로만 적는다(docaudit 가 대조한다)")
    print("    " + s["문장"])
    print()
    if s["문제"]:
        print("  ⛔ 대장 문제 %d건" % len(s["문제"]))
        for x in s["문제"]:
            print("    - " + x)
    else:
        print("  ✅ 봉인 명세 전부 있음 · 인용 전부 찾음 · «실행 중» 인데 결과가 나온 행 없음")


def main(argv=None):
    ap = argparse.ArgumentParser(description="사전 기준 대장 집계")
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--json", action="store_true", help="기계용 JSON 을 표준 출력으로")
    ap.add_argument("--md", action="store_true", help="부록용 표를 표준 출력으로")
    ap.add_argument("--docs", action="store_true", help="문서의 집계 문장·옛 서사도 본다")
    ap.add_argument("--sync", action="store_true",
                    help="집계 문장을 대장의 현재 수로 맞춘다 (봉인·기록·pptx 는 안 만진다)")
    ap.add_argument("--sync-dry", action="store_true", help="--sync 가 무엇을 바꿀지만 찍는다")
    a = ap.parse_args(argv)
    if a.sync or a.sync_dry:
        bad = check(a.root)
        if bad:
            print("  ⛔ 대장에 문제가 있어 맞추지 않는다 — 먼저 고쳐라")
            for x in bad[:5]:
                print("    - " + x)
            return 1
        ch = sync(a.root, apply=not a.sync_dry)
        want = sentence(tally(load(a.root)))
        print("  %s — 정본 «%s»" % ("미리보기" if a.sync_dry else "맞췄다", want))
        for d, ln, old in ch:
            print("    %s:%d  «%s»" % (d, ln, old))
        if not ch:
            print("    바꿀 곳 없음")
        elif not a.sync_dry:
            print("  → 발표자료는 다시 구워라: py slides\\build_deck.py · py slides\\make_10min_본선.py")
        return 0
    s = summary(a.root)
    if a.docs:
        s["문서"] = doc_problems(a.root, s["기본"])
    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=1))
    elif a.md:
        print(to_md(load(a.root)))
    else:
        report(s)
        if a.docs:
            print()
            if s["문서"]:
                print("  ⛔ 문서 %d곳" % len(s["문서"]))
                for x in s["문서"]:
                    print("    - " + x)
            else:
                print("  ✅ 문서의 집계 문장이 대장과 같다 · 옛 서사 없음")
    bad = len(s["문제"]) + len(s.get("문서", []))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
