# -*- coding: utf-8 -*-
"""진단 — LLM 호출이 왜 실패하는지 원문 그대로 보여준다.

llm.complete()는 예외를 삼켜서 판정을 보류시킨다. 파이프라인 안정성에는 맞지만
설정을 고칠 때는 원인이 안 보인다. 이 도구는 반대로 전부 드러낸다.

실행: py -m bioreroute.diag
"""

import os
import sys
import traceback

from . import config

# 모델 이름과 가용성은 계정·시점마다 다르다. 추측하지 말고 직접 물어본다.
#
# ⚠ 08-24 — 승우 계정이 **`gpt-5.4` 계열 nano·mini 만** 허용으로 바뀌었다.
#   `gpt-5.4-nano` 가 이 목록에 **없었다.** 즉 «쓸 수 있는 모델»을
#   탐색하는 도구가 **실제로 쓸 수 있는 모델을 안 물어봤다.**
CANDIDATES = {
    # ── 09-09 · 본선 크레딧 (데이콘 Azure APIM 프록시) ────────────────
    #   `BIOREROUTE_API_BASE` 와 `DACON_API_KEY` 가 있을 때만 탐색한다.
    #   ⚠ **`openai/` 접두어를 붙인다.** litellm 은 모르는 모델명을 만나면
    #     공급자를 못 정한다 — 접두어가 «OpenAI 호환 경로로 가라» 는 지시다.
    #   ⚠ 이 셋은 **본선 기간(~10/2)에만** 쓰는 것이고, 그 밖에서는
    #     키가 없어 자동으로 건너뛴다.
    "본선프록시": ["openai/gpt-5.6-terra", "openai/gpt-5.6-luna",
                   "openai/gpt-5.6-sol"],
    "OpenAI": ["gpt-5.4-mini", "gpt-5.4-nano", "gpt-5-mini", "gpt-5-nano",
               "gpt-5.4", "gpt-4o-mini"],
    "Gemini": ["gemini/gemini-flash-latest", "gemini/gemini-2.0-flash",
               "gemini/gemini-2.5-flash", "gemini/gemini-2.5-flash-lite"],
}
KEY_OF = {"본선프록시": "DACON_API_KEY",
          "OpenAI": "OPENAI_API_KEY", "Gemini": "GEMINI_API_KEY"}

# 온도 0을 받아주는 모델. 팩트체커는 재현성이 생명이므로 이쪽을 우선한다.
DETERMINISTIC = set()


def line(c="─", n=70):
    print(c * n)


def main(argv=None):
    quick = "--quick" in (argv if argv is not None else sys.argv[1:])
    line("=")
    print("Bio-ReRoute 진단" + ("  [빠른 확인]" if quick else ""))
    line("=")

    # 1. 환경
    print("\n[1] 환경")
    print("  파이썬     : %s" % sys.version.split()[0])
    print("  설정       : %s" % config.status())
    for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        v = os.environ.get(k)
        if v:
            print("  %-18s: %s… (%d자)" % (k, v[:6], len(v)))
    try:
        import litellm
        print("  litellm    : %s" % getattr(litellm, "__version__", "버전 미상"))
    except Exception as e:
        print("  litellm    : 불러오기 실패 — %s" % e)
        print("\n  → py -m pip install litellm")
        return 1

    # 2. 원문 예외
    print("\n[2] 현재 모델로 1회 호출 (예외를 그대로 출력)")
    model = os.environ.get("BIOREROUTE_MODEL", "gemini/gemini-2.0-flash")
    print("  모델: %s" % model)
    litellm.suppress_debug_info = True
    # ⚠ **09-09 · 프록시 인자를 여기서도 붙인다.** 본선 크레딧은 Azure
    #   APIM 을 거치고 `io/llm.py` 는 `_endpoint_kwargs()` 로 `api_base`
    #   와 `api-key` 헤더를 붙인다. 이 파일은 `litellm` 을 **직접** 부르므로
    #   그대로 두면 **진단만 다른 곳으로 간다** — 아래 §3 주석이 *"프로덕션과
    #   같은 경로를 탄다"* 고 적어 놨는데 그 문장이 거짓이 될 뻔했다.
    #   `CLAUDE.md §5`: **검증 환경이 실행 환경과 다르면 그 검증은 거짓말이다.**
    from .io.llm import _endpoint_kwargs as _ep, _temp_unsupported as _tu
    _msg = [{"role": "user", "content": "1+1=? 숫자만."}]

    def _once(**kw):
        r = litellm.completion(model=model, messages=_msg,
                               **dict(_ep(model), **kw))
        return (r["choices"][0]["message"]["content"] or "").strip()

    try:
        try:
            body, note = _once(temperature=0.0), "temperature=0.0 · 결정적"
        except Exception as e:
            # ⚠ **09-09 · 파이프라인과 같은 처리를 해야 한다.** 본선 모델은
            #   `temperature=0` 을 400 으로 거부한다(*"Only the default (1)
            #   value is supported"*). `io/llm.py` 는 `_NO_TEMP` 에 넣고
            #   기본 온도로 한 번 더 가는데, 여기서 그냥 죽으면 진단이
            #   **«이 모델은 안 된다» 고 거짓 보고**를 한다 — 실제로는 된다.
            if not _tu(e):
                raise
            body = _once()
            # ⚠ **`seed` 를 쓰는지까지 말해야 한다.** «비결정» 이라고만
            #   찍으면 `BIOREROUTE_SEED` 를 넣은 실행과 안 넣은 실행이
            #   화면에서 **구분이 안 된다** — 나중에 «그날 재현을 시도했나»
            #   를 못 가른다. 09-09에 실제로 그렇게 찍혀서 고쳤다.
            from .io.llm import _seed_kwargs as _sk
            _s = _sk(model)
            if _s:
                note = ("⚠ 기본 온도 + **seed=%s 고정** — 재현을 «시도» 한다"
                        % _s["seed"])
            else:
                note = "⚠ **기본 온도(비결정) · seed 미설정**"
        print("  성공 → %r" % body)
        print("  %s" % note)
        if "seed=" in note:
            print("  → best-effort 다. **«재현된다» 가 아니라 «시도한다».**")
            print("     감사 추적에도 그렇게 남는다(`사전명세_…_본선.md §9`).")
        elif "비결정" in note:
            print("  → `.env` 에 `BIOREROUTE_SEED=42` 를 넣으면 재현을")
            print("     시도할 수 있다. 09-09 실측: 세 모델 다 seed 수용,")
            print("     고정 시 5/5 일치(`본선API_실측.md §5-d`).")
        else:
            print("  현재 모델은 정상이다.")
    except Exception:
        print("  실패. 아래가 원문이다.\n")
        line()
        traceback.print_exc()
        line()

    if quick:
        print("\n  (--quick: 모델 탐색 생략)")
        return 0
    return probe(litellm, model)


def probe(litellm, current=None):
    """공급자별로 어떤 모델이 실제로 응답하는지 확인한다.

    주의: 모델마다 1회씩 실제로 호출한다. Gemini 무료 티어에서는 이 탐색 자체가
    일일 할당량(모델당 20회)을 먹는다. 건너뛰려면 --quick.
    """
    n = sum(len(v) for k, v in CANDIDATES.items() if os.environ.get(KEY_OF[k]))
    print("\n[3] 사용 가능한 모델 탐색 — 최대 %d회 호출 (건너뛰려면 --quick)" % n)
    ok = {}
    for vendor, models in CANDIDATES.items():
        if not os.environ.get(KEY_OF[vendor]):
            print("\n  %s — 키 없음, 건너뜀" % vendor)
            continue
        print("\n  %s" % vendor)
        for m in models:
            # 프로덕션(llm.complete)과 같은 경로를 탄다. 온도 거부 시 기본값으로
            # 재시도하는 로직이 거기 있으므로, 여기서만 실패 처리하면 거짓 음성이 된다.
            # ⚠ **`max_tokens=5` 를 보내면 안 된다** — 08-24.
            #   추론 모델은 **생각에도 출력 예산을 쓴다**(결함 237이 이미
            #   적어 뒀다). 5토큰이면 생각하다 끝나 **본문이 빈 채로
            #   «성공» 이 돌아온다.** 그러면 이 도구가 «쓸 수 있다» 고
            #   말하고 실제 파이프라인에서는 답이 안 온다 —
            #   **거짓 양성이다.** 예산을 넉넉히 주고 본문을 확인한다.
            msg = [{"role": "user", "content": "1+1=? 숫자만."}]
            det, body, fin = None, "", ""

            def _try(**kw):
                # 09-09 — 프록시 모델도 여기서 태워야 «같은 경로» 가 참이 된다.
                from .io.llm import _endpoint_kwargs as _ep2
                r = litellm.completion(model=m, messages=msg,
                                       max_tokens=256, **dict(_ep2(m), **kw))
                c = r["choices"][0]
                return ((c["message"]["content"] or "").strip(),
                        str(c.get("finish_reason") or ""))
            try:
                body, fin = _try(temperature=0.0)
                det = True
            except Exception as e:
                s = str(e).replace("\n", " ")
                if "temperature" in s.lower():
                    try:
                        body, fin = _try()
                        det = False
                    except Exception as e2:
                        s = str(e2).replace("\n", " ")
            if det is None:
                # **원문을 자르지 마라.** 오늘 하루가 «요약이 범인을
                #   가린다» 였다(결함 306). 분류는 붙이되 원문도 남긴다.
                why = ("일일 할당량 소진(429)" if ("429" in s or "quota" in s.lower())
                       else "모델 없음" if "404" in s or "not found" in s.lower()
                       else "인증 실패" if "auth" in s.lower() or "401" in s
                       else "권한 없음" if "403" in s or "not have access" in s.lower()
                       else "")
                print("    실패  %-30s %s" % (m, why or "(아래 원문)"))
                print("           %s" % s[:400])
                continue
            if not body:
                # **빈 응답을 성공으로 세지 않는다** — 침묵과 통과는 다르다(결함 99).
                print("    빈답  %-30s 예외는 없는데 **본문이 비었다** "
                      "(finish_reason=%s). 파이프라인에서도 안 온다"
                      % (m, fin or "?"))
                continue
            print("    성공  %-30s %s%s" % (m, "온도 0 고정 가능" if det
                                            else "온도 고정 불가 — 재현성 손실",
                                            "" if fin in ("stop", "") else
                                            "  ⚠ finish_reason=%s" % fin))
            ok.setdefault(vendor, []).append(m)
            if det:
                DETERMINISTIC.add(m)

    print("")
    line("=")
    if not ok:
        print("→ 응답하는 모델이 없다. [2]의 예외 원문을 확인한다.")
        line("=")
        return 1

    # 주력 선정 기준 두 가지
    #   1) 온도 0 고정 가능 — 팩트체커는 같은 초록에 같은 판정을 내야 한다.
    #      온도가 풀리면 재실행마다 답이 흔들려 제거 실험·일치도 측정이 오염된다.
    #   2) OpenAI 우선 — Gemini 무료 티어는 모델당 하루 20회라
    #      벤치마크(후보 100개)를 감당하지 못한다. 폴백 완충재로 남긴다.
    flat = (ok.get("OpenAI") or []) + (ok.get("Gemini") or [])
    det = [m for m in flat if m in DETERMINISTIC]
    primary = (det or flat)[0]
    others = [m for m in flat if m != primary]
    if det:
        print("→ 온도 0 고정 가능한 모델을 주력으로 잡는다 (재현성)")
    else:
        print("→ [경고] 온도 0을 받는 모델이 없다. 판정이 실행마다 흔들릴 수 있다.")
    # ── **지금 사슬에 죽은 칸이 있나** — 08-24 ─────────────────────────
    #
    #   `llm.py` 는 `[MODEL] + FALLBACKS` 를 순서대로 탄다. 그 안에
    #   **못 쓰는 모델이 있으면 매 호출마다 실패를 한 번씩 낭비**한다.
    #   429 가 아니면 `MAX_RETRY` 만큼 재시도까지 하므로 **호출당 지연**이
    #   붙는다. 시연 시간은 배점 30점짜리다 — 조용히 넘어갈 자리가 아니다.
    from .io import llm as _llm
    live = set(flat)
    chain = [_llm.MODEL] + [x for x in _llm.FALLBACKS if x != _llm.MODEL]
    tested = {m for v in CANDIDATES.values() for m in v}
    dead = [c for c in chain if c in tested and c not in live]
    print("\n   지금 `.env` 사슬 — %s" % " → ".join(chain))
    if dead:
        print("   ⚠ **죽은 칸 %d개: %s**" % (len(dead), ", ".join(dead)))
        print("      이 칸들은 **매 호출마다 실패를 한 번씩 낭비**한다.")
        print("      앞쪽에 있으면 그만큼 **판정이 느려진다.**")
    else:
        print("   ✓ 사슬에 죽은 칸 없음")
    unknown = [c for c in chain if c not in tested]
    if unknown:
        print("   ⓘ 이 탐색이 **안 물어본 칸**: %s — 모른다고 적는다"
              % ", ".join(unknown))

    print("\n   .env 를 아래처럼 맞춘다\n")
    print("     BIOREROUTE_MODEL=%s" % primary)
    if others:
        print("     BIOREROUTE_FALLBACKS=%s" % ",".join(others[:3]))
    print("     BIOREROUTE_MAX_CALLS=60")
    print("\n   ⚠ **모델을 바꾸면 동결 수치가 다른 시스템의 수치가 된다**")
    print("     (`CLAUDE.md §3-2` · `llm.py` 주석). 바꾼 사실을 기록해라.")
    if ok.get("OpenAI") and ok.get("Gemini"):
        print("")
        print("   두 공급자가 다 살아 있다. 판정 일치도(BYOM 주장의 실측 근거)를")
        print("   낼 수 있다:  py -m bioreroute.agreement")
    line("=")
    return 0


if __name__ == "__main__":
    sys.exit(main())
