# -*- coding: utf-8 -*-
"""데이콘 본선 API 프록시 탐침 — **어느 경로가 열려 있는가.**

09-09 에 데이콘이 준 것은 **Azure API Management 프록시**다. 안내문이
명시한 것은 `/responses` 하나뿐이고, **우리 `io/llm.py` 는 LiteLLM 의
`completion()` 을 쓰므로 `/chat/completions` 로 간다.**

    안내문      POST {base}/responses          ← 보장된다
    우리 코드   POST {base}/chat/completions   ← **열려 있는지 모른다**

**모르는 채로 코드를 고치면 헛수고다.** 그래서 이 도구가 먼저다.
표준 라이브러리만 쓴다(litellm·openai·requests 없이) — 어댑터 층의
문제와 프록시의 문제를 **섞지 않기 위해서**다. 여기서 실패하면
그건 프록시나 키의 문제이고, 여기서 되는데 파이프라인이 안 되면
그건 우리 어댑터의 문제다.

  py -m bioreroute.apiprobe              # 두 경로 × 세 모델
  py -m bioreroute.apiprobe --model gpt-5.6-luna
  py -m bioreroute.apiprobe --json 결과.json

⚠ **키는 환경변수에서만 읽는다.** 인자로도 안 받고 화면에도 안 찍는다
(앞 4자만). 안내문 자신이 *"API 키를 외부에 공개하거나 GitHub 등 공개
저장소에 올리지 마세요"* 라고 적었고, `계획_9월.md §4` 가 **GitHub
이관**을 예정하고 있다. 둘이 만나는 자리라 여기서부터 조심한다.
"""

from __future__ import annotations

# ⚠ **09-09 · 첫 실행에서 이걸 빼먹어 «키 없음» 이 나왔다.**
#   `litellm` 도 이 프로젝트도 `.env` 를 자동으로 안 읽는다 —
#   `config` 를 임포트해야 `load_env()` 가 돌아 환경변수로 올라간다
#   (`io/llm.py` 도 같은 이유로 맨 위에서 임포트한다).
#   **안내문에는 «.env 도 된다» 고 적어 놓고 코드가 안 했다** — 화면이
#   거짓말을 한 것이고, 이 프로젝트가 여러 번 겪은 그 계열이다.
from . import config as _config          # noqa: F401  (.env 를 먼저 올린다)

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# 안내문이 준 값. `.env` 로 덮어쓸 수 있게 한다.
DEFAULT_BASE = "https://dacon-apim-hackathon-0903.azure-api.net/hackathon/openai/v1"
MODELS = ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]

# 팀 잔량·소비량이 여기로 온다. **크레딧 효율 15점의 원자료**다
# (`계획_9월.md §2-①`). 헤더 이름은 안내문 그대로다.
TEAM_HEADERS = ["x-team-remaining-quota-tokens", "x-team-tokens-consumed",
                "x-team-remaining-tokens", "x-team-remaining-requests"]

PROMPT = "Reply only OK"

# ── 모델 고르기 (`--pick`) — `사전명세_모델교체_본선.md §4` ──────────
#
#   ⛔ **판정 정확도로 모델을 고르지 않는다.** "여러 개 돌려 보고 제일
#     잘 맞는 걸 골랐다" 는 결과를 보고 시스템을 고른 것이고 `§3-2`
#     위반이다. 명세가 정한 순서는 **① 지연 ② 출력 토큰 ③ JSON 준수율
#     ④ 이름순** 이고, 이 도구는 그 셋**만** 잰다.
#
#   그래서 프롬프트도 **도메인과 무관한 형식 확인용**이다. 약·질환·
#   기전을 묻는 순간 그건 판정 성능 측정이 되어 명세를 어긴다.
PICK_PROMPTS = [
    ("빈_객체", '{"ok": true} 형식으로만 답하라. 설명 금지.', ["ok"]),
    ("숫자", 'JSON 으로만: {"n": 3 과 4 의 합}. 설명 금지.', ["n"]),
    ("배열", 'JSON 으로만: {"items": [1,2,3]}. 설명 금지.', ["items"]),
    ("한글값", 'JSON 으로만: {"말": "안녕"}. 설명 금지.', ["말"]),
    ("중첩", 'JSON 으로만: {"a": {"b": 1}}. 설명 금지.', ["a"]),
    ("널", 'JSON 으로만: {"v": null}. 설명 금지.', ["v"]),
    ("불린둘", 'JSON 으로만: {"x": true, "y": false}. 설명 금지.', ["x", "y"]),
    ("빈배열", 'JSON 으로만: {"list": []}. 설명 금지.', ["list"]),
    ("키셋", 'JSON 으로만: {"a":1,"b":2,"c":3}. 설명 금지.', ["a", "b", "c"]),
    ("문자열목록", 'JSON 으로만: {"ws": ["가","나"]}. 설명 금지.', ["ws"]),
]


def base_url() -> str:
    return (os.environ.get("BIOREROUTE_API_BASE") or DEFAULT_BASE).rstrip("/")


KEY_NAMES = ("DACON_API_KEY", "BIOREROUTE_API_KEY", "OPENAI_API_KEY")


def api_key() -> Tuple[str, str]:
    """환경변수에서만. **인자로 받지 않는다.**

    ⚠ **어느 이름에서 가져왔는지 같이 돌려준다.** 옛 `OPENAI_API_KEY` 가
      `.env` 에 남아 있으면 그걸 집어 프록시에 보내고 **401** 이 나는데,
      출처를 안 찍으면 «키가 틀렸나 프록시가 막혔나» 를 못 가른다.
      *조회 실패와 설정 오류를 섞지 않는다* — 결함 35 계열.
    """
    for name in KEY_NAMES:
        v = (os.environ.get(name) or "").strip()
        if v:
            return v, name
    return "", ""


def env_diag() -> str:
    """키를 못 찾았을 때 **어디를 봤는지** 적는다."""
    where = getattr(_config, "LOADED", None)
    lines = ["  .env      %s" % (where or "**못 찾았다**")]
    if where:
        try:
            names = []
            for ln in open(where, encoding="utf-8-sig"):
                ln = ln.strip()
                if ln and not ln.startswith("#") and "=" in ln:
                    k, v = ln.split("=", 1)
                    # ⚠ 값은 절대 안 찍는다. **이름과 «채워졌나» 만.**
                    names.append("%s%s" % (k.strip(),
                                           "" if v.strip() else "(빈값)"))
            lines.append("  그 안의 키  %s" % (", ".join(names) or "(없음)"))
        except Exception as e:
            lines.append("  읽기 실패  %s" % e)
    lines.append("  찾는 이름  %s" % " → ".join(KEY_NAMES))
    return "\n".join(lines)


def masked(k: str) -> str:
    """화면에 찍어도 되는 형태. **앞 4자 + 길이**뿐."""
    if not k:
        return "(없음)"
    return "%s… (%d자)" % (k[:4], len(k))


def _post(url: str, payload: Dict[str, Any], key: str,
          timeout: int = 60) -> Dict[str, Any]:
    """한 번 찌른다. **예외를 던지지 않고** 결과를 표로 돌려준다.

    ⚠ 실패를 «없음» 으로 세지 않는다(`CLAUDE.md §2` · 결함 35 계열).
    HTTP 오류·망 오류·타임아웃을 **각각 다른 값**으로 남긴다.
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    # 안내문: "일부 SDK 는 Authorization: Bearer 로만 보낸다. 이 경우
    #          반드시 api-key 사용자 지정 헤더도 함께 설정해야 한다."
    # 둘 다 보낸다 — 프록시가 어느 쪽을 보는지 모르기 때문이다.
    req.add_header("api-key", key)
    req.add_header("Authorization", "Bearer " + key)

    t0 = time.time()
    out: Dict[str, Any] = {"url": url, "model": payload.get("model")}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            out["status"] = r.status
            out["headers"] = {h: r.headers.get(h) for h in TEAM_HEADERS
                              if r.headers.get(h) is not None}
            out["ok"] = True
            try:
                out["body"] = json.loads(raw)
            except Exception:
                out["body"] = None
                out["raw_head"] = raw[:300]
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        out["ok"] = False
        out["status"] = e.code
        out["headers"] = {h: e.headers.get(h) for h in TEAM_HEADERS
                          if e.headers and e.headers.get(h) is not None}
        out["error"] = "HTTP %d" % e.code
        out["raw_head"] = raw[:300]
        # 안내문의 오류표를 그대로 옮긴다. 추측하지 않는다.
        out["hint"] = {401: "헤더가 api-key 인지·키가 정확한지",
                       400: "모델 이름이 허용 목록에 있는지",
                       404: "**이 경로가 안 열려 있다**(또는 모델 이름)",
                       429: "TPM/RPM 초과 — 잠시 후 재시도",
                       403: "**팀 전체 토큰 한도 소진**"}.get(e.code, "")
    except Exception as e:                                    # 망·타임아웃
        out["ok"] = False
        out["status"] = None
        out["error"] = "%s: %s" % (type(e).__name__, e)
        out["hint"] = "조회 불가 — **«실패» 이지 «한도 소진» 이 아니다**"
    out["초"] = round(time.time() - t0, 2)
    return out


def _text_of(res: Dict[str, Any]) -> str:
    """두 API 의 응답 모양이 다르다. **둘 다 읽는다.**

    Responses API   → output_text  또는  output[].content[].text
    Chat Completions → choices[0].message.content
    """
    b = res.get("body") or {}
    if not isinstance(b, dict):
        return ""
    if isinstance(b.get("output_text"), str):
        return b["output_text"].strip()
    try:
        for item in b.get("output") or []:
            for c in item.get("content") or []:
                if isinstance(c.get("text"), str):
                    return c["text"].strip()
    except Exception:
        pass
    try:
        return (b["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return ""


def _usage_of(res: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    b = res.get("body") or {}
    u = b.get("usage") if isinstance(b, dict) else None
    return u if isinstance(u, dict) else None


def probe(model: str, key: str, base: str) -> List[Dict[str, Any]]:
    """한 모델에 **두 경로**를 다 찔러 본다."""
    out = []

    r = _post(base + "/responses", {"model": model, "input": PROMPT}, key)
    r["경로"] = "responses"
    out.append(r)

    # LiteLLM 이 실제로 갈 경로. **이게 이 도구의 존재 이유다.**
    r = _post(base + "/chat/completions",
              {"model": model,
               "messages": [{"role": "user", "content": PROMPT}]}, key)
    r["경로"] = "chat/completions"
    out.append(r)
    return out


# ── 결정성 시험 (`--determinism`) — 09-09에 새로 생긴 물음 ──────────
#
#   본선 모델이 **`temperature=0` 을 거부한다**(400, *"Only the default
#   (1) value is supported"*). 이 프로젝트는 `TEMPERATURE = 0.0` 을
#   **«재현성 우선»** 이라 적어 두고 여덟 달을 굴렸다. 전제가 깨졌다.
#
#   그래서 세 가지를 **재서** 답한다. 추측하지 않는다 —
#     ① `temperature` 를 정말 못 쓰나 (0 · 1 · 생략)
#     ② `seed` 를 받아주나 (OpenAI 호환이면 있을 수 있다)
#     ③ **같은 질문 N회에 같은 답이 오나** ← 이게 진짜 물음이다
#
#   ⚠ 프롬프트는 **도메인 무관**이되 «자유도» 를 갈라 둔다. 답이 하나뿐인
#     물음만 쓰면 비결정성이 안 드러나고, 자유로운 물음만 쓰면 실제 판정과
#     동떨어진다. 판정은 **분류**에 가까우므로 그쪽에 무게를 둔다.
DET_PROMPTS = [
    ("소수·답하나", 'JSON 으로만: {"p": [1~10 중 소수를 오름차순]}. 설명 금지.'),
    ("분류·답하나", 'JSON 으로만: {"c": "고양이는 포유류/조류 중 무엇인가"}. 설명 금지.'),
    ("요약·자유도", 'JSON 으로만: {"w": [바다를 묘사하는 형용사 정확히 3개]}. 설명 금지.'),
]


def determinism(model: str, key: str, base: str, n: int = 5) -> Dict[str, Any]:
    """`temperature`·`seed` 수용 여부와 **반복 일치율**을 잰다."""
    url = base + "/chat/completions"
    msg = [{"role": "user", "content": "1+1=? 숫자만."}]

    accepts: Dict[str, Any] = {}
    for label, extra in (("temperature=0", {"temperature": 0}),
                         ("temperature=1", {"temperature": 1}),
                         ("생략", {}),
                         ("seed=42", {"seed": 42}),
                         ("seed+temp1", {"seed": 42, "temperature": 1})):
        r = _post(url, dict({"model": model, "messages": msg}, **extra), key)
        accepts[label] = {"ok": bool(r.get("ok")), "status": r.get("status"),
                          "err": (r.get("raw_head") or "")[:120]}

    # ③ 같은 질문 N회 — **기본 설정 그대로**(파이프라인이 쓸 모습)
    rep: Dict[str, Any] = {}
    for name, prompt in DET_PROMPTS:
        seen = []
        for _ in range(n):
            r = _post(url, {"model": model,
                            "messages": [{"role": "user", "content": prompt}]},
                      key)
            d = _parse_json_loose(_text_of(r))
            seen.append(json.dumps(d, ensure_ascii=False, sort_keys=True)
                        if d is not None else "«파싱실패»")
        uniq = sorted(set(seen))
        rep[name] = {"서로_다른_답": len(uniq), "시행": n,
                     "최빈_비율": round(max(seen.count(u) for u in uniq) / n, 2),
                     "예시": uniq[:3]}

    # seed 가 받아들여지면 **seed 고정 시 일치율**도 따로 본다.
    rep_seed = None
    if accepts.get("seed=42", {}).get("ok"):
        name, prompt = DET_PROMPTS[-1]          # 자유도 가장 큰 것으로
        seen = []
        for _ in range(n):
            r = _post(url, {"model": model, "seed": 42,
                            "messages": [{"role": "user", "content": prompt}]},
                      key)
            d = _parse_json_loose(_text_of(r))
            seen.append(json.dumps(d, ensure_ascii=False, sort_keys=True)
                        if d is not None else "«파싱실패»")
        uniq = sorted(set(seen))
        rep_seed = {"항목": name, "서로_다른_답": len(uniq), "시행": n,
                    "최빈_비율": round(max(seen.count(u) for u in uniq) / n, 2)}

    return {"수용여부": accepts, "반복": rep, "seed고정_반복": rep_seed}


def _report_determinism(model: str, res: Dict[str, Any]) -> None:
    print()
    print("=" * 70)
    print("모델 %s — 결정성" % model)
    print("=" * 70)
    print("\n[1] 무엇을 받아주나")
    for k, v in res["수용여부"].items():
        mark = "✅" if v["ok"] else "❌ %s" % (v["status"] or "")
        print("  %-14s %s %s" % (k, mark, "" if v["ok"] else v["err"][:70]))

    print("\n[2] 같은 질문 %d회 — **기본 설정 그대로**"
          % next(iter(res["반복"].values()))["시행"])
    for name, v in res["반복"].items():
        flag = "🟢 일정" if v["서로_다른_답"] == 1 else "🔴 흔들림"
        print("  %-14s 서로 다른 답 %d/%d · 최빈 %.0f%%  %s"
              % (name, v["서로_다른_답"], v["시행"], v["최빈_비율"] * 100, flag))
        if v["서로_다른_답"] > 1:
            for e in v["예시"]:
                print("      %s" % e[:74])

    if res.get("seed고정_반복"):
        s = res["seed고정_반복"]
        print("\n[3] `seed=42` 고정 시 (%s) — 서로 다른 답 %d/%d · 최빈 %.0f%%"
              % (s["항목"], s["서로_다른_답"], s["시행"], s["최빈_비율"] * 100))
        if s["서로_다른_답"] == 1:
            print("  🟢 **seed 로 재현성을 되찾을 수 있다.**")
        else:
            print("  🔴 seed 를 받아도 **답이 흔들린다.** 재현성 수단이 아니다.")

    print()
    print("⚠ **이 표는 «정답률» 이 아니다.** 같은 답이 오는지만 본다 —")
    print("   틀린 답이 일정하게 와도 여기서는 🟢 다.")


def _parse_json_loose(text: str):
    """코드펜스·앞뒤 설명을 걷어내고 JSON 을 꺼낸다.

    `io/llm._parse_json` 과 **같은 관용도**로 맞춘다 — 파이프라인이
    관대하게 읽는데 여기서 엄격하게 재면 **실제보다 나쁘게 나온다.**
    """
    t = (text or "").strip()
    if "```" in t:
        t = t.split("```")[1]
        t = t[4:] if t.lower().startswith("json") else t
    t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    for a, b in (("{", "}"), ("[", "]")):
        i, j = t.find(a), t.rfind(b)
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except Exception:
                continue
    return None


def pick(models: List[str], key: str, base: str,
         rounds: int = 1) -> Dict[str, Any]:
    """`§4` 의 셋만 잰다 — 지연 · 출력 토큰 · JSON 준수율.

    ⚠ **모델을 뭉쳐 돌리지 않는다 — 라운드 로빈이다.** 09-09 첫 실행은
      `for 모델: for 프롬프트:` 였고, 그러면 한 모델이 10회를 연속으로
      맞으므로 **망이 느려진 구간에 걸린 모델만 손해를 본다.** 모델
      차이와 시간대 차이가 **교락(confounded)** 된다. 같은 프롬프트를
      세 모델에 바로 이어 보내면 그 교락이 거의 사라진다.

      실제로 첫 실행에서 `luna` 만 최대 4.17초로 튀었는데, 그것이
      모델 탓인지 그 시간대 탓인지 **그 설계로는 못 가른다.**
    """
    acc = {m: {"lat": [], "otok": [], "ok": 0, "fails": []} for m in models}
    for _r in range(max(1, rounds)):
        for name, prompt, need in PICK_PROMPTS:
            for m in models:                 # ← 같은 프롬프트를 연속으로
                a = acc[m]
                r = _post(base + "/chat/completions",
                          {"model": m,
                           "messages": [{"role": "user", "content": prompt}]},
                          key)
                a["lat"].append(r.get("초") or 0.0)
                u = _usage_of(r) or {}
                ot = u.get("output_tokens", u.get("completion_tokens"))
                if isinstance(ot, int):
                    a["otok"].append(ot)
                d = _parse_json_loose(_text_of(r))
                if isinstance(d, dict) and all(k in d for k in need):
                    a["ok"] += 1
                else:
                    a["fails"].append(name)

    out: Dict[str, Any] = {}
    n = len(PICK_PROMPTS) * max(1, rounds)
    for m, a in acc.items():
        srt = sorted(a["lat"])
        med = srt[len(srt) // 2] if srt else None
        out[m] = {"지연_중앙값": round(med, 2) if med is not None else None,
                  "지연_최소": round(min(srt), 2) if srt else None,
                  "지연_최대": round(max(srt), 2) if srt else None,
                  "출력토큰_합": sum(a["otok"]) if a["otok"] else None,
                  "출력토큰_계량됨": len(a["otok"]),
                  "JSON_성공": a["ok"], "JSON_전체": n,
                  "실패항목": a["fails"],
                  "지연_원자료": [round(x, 2) for x in a["lat"]]}
    return out


def _report_pick(res: Dict[str, Any]) -> None:
    print()
    print("%-16s %8s %7s %7s %9s %s" % (
        "모델", "지연중앙", "최소", "최대", "출력토큰", "JSON"))
    print("-" * 66)
    for m, v in res.items():
        print("%-16s %8s %7s %7s %9s %d/%d %s" % (
            m, v["지연_중앙값"], v.get("지연_최소"), v["지연_최대"],
            v["출력토큰_합"] if v["출력토큰_합"] is not None else "—",
            v["JSON_성공"], v["JSON_전체"],
            ("실패:" + ",".join(v["실패항목"])) if v["실패항목"] else ""))

    # ── 명세 §4 — **JSON 준수는 순위가 아니라 자격이다** ─────────────
    #
    #   ⚠ **09-09 모의 실행에서 명세의 구멍이 드러났다.** 처음엔 §4 를
    #     «① 지연 ② 출력토큰 ③ JSON ④ 이름» 순의 **단순 정렬**로 짰는데,
    #     그러면 **JSON 0/10 인 모델이 «빠르다» 는 이유로 2위**로 올라온다.
    #     형식을 못 지키면 **판정 자체가 성립하지 않는다** — 3순위 감점이
    #     아니라 **자격 미달**이다.
    #
    #   §3-2 에 안 걸리는 이유를 적어 둔다: 이때 본 것은 **가짜 응답**이고
    #   실제 모델 수치는 **한 번도 안 봤다.** 결과를 보고 유리하게 고친 게
    #   아니라 **논리 구멍을 실행 전에 막은 것**이다. 명세에도 같이 적었다.
    QUALIFY = 0.9
    fit = {m: v for m, v in res.items()
           if v["JSON_성공"] >= QUALIFY * v["JSON_전체"]}
    unfit = [m for m in res if m not in fit]

    if unfit:
        print()
        print("⛔ **자격 미달**(JSON %d%% 미만) — %s"
              % (int(QUALIFY * 100), ", ".join(unfit)))
        print("   빠르든 싸든 **순위에서 뺀다.** 형식을 못 지키면 판정이 안 된다.")

    if not fit:
        print()
        print("⛔ **반증 조건 발동**(명세 §7) — 세 모델 «어느 것도» JSON")
        print("   준수 %d%% 미만이다. **모델 탓으로 넘기지 말고** 프롬프트를"
              % int(QUALIFY * 100))
        print("   고쳐라. 그 사실을 기록에 남긴다.")
        return

    ranked = sorted(fit.items(),
                    key=lambda kv: (kv[1]["지연_중앙값"] if kv[1]["지연_중앙값"]
                                    is not None else 9e9,
                                    kv[1]["출력토큰_합"] if kv[1]["출력토큰_합"]
                                    is not None else 9e9,
                                    kv[0]))
    print()
    print("명세 §4 — 자격 통과분을 **지연 → 출력토큰 → 이름** 순으로 —")
    for i, (m, _v) in enumerate(ranked, 1):
        print("  %d. %s" % (i, m))

    # ── **차이가 잡음보다 작으면 그렇다고 말한다** ────────────────
    #   순위를 찍어 놓고 흔들림을 안 적으면, 읽는 사람은 그 순위를
    #   확정된 것으로 읽는다. `CLAUDE.md §4` 의 «유의하지 않다 ≠ 차이
    #   없다» 와 같은 자리다.
    if len(ranked) >= 2:
        (m1, v1), (m2, v2) = ranked[0], ranked[1]
        try:
            gap = v2["지연_중앙값"] - v1["지연_중앙값"]
            spread = max(v1["지연_최대"] - v1["지연_최소"],
                         v2["지연_최대"] - v2["지연_최소"])
        except (TypeError, KeyError):
            gap = spread = None
        if gap is not None and gap < spread:
            print()
            print("⚠ **1·2위 차이(%.2f초)가 측정 흔들림(%.2f초)보다 작다.**"
                  % (gap, spread))
            print("   `%s` 와 `%s` 를 이 실행만으로 **구분했다고 말하지 마라.**"
                  % (m1, m2))
            print("   명세 §4 가 «두 번 이상 재고 순위가 바뀌면 바뀌었다고")
            print("   적으라» 고 요구한다 — `--rounds 2` 로 다시 재라.")

    print()
    print("⚠ **이 표로 «어느 모델이 더 똑똑한가» 를 말하지 마라.**")
    print("   판정 정확도는 재지 않았다(명세 §4). 일치도는 `§5` 에서 따로.")
    print("⚠ 이 프롬프트 10개는 **매우 짧다**(출력 기대 ~6토큰). 실제 판정은")
    print("   초록이 붙어 수천 토큰이므로 **출력토큰 비율이 여기와 다르다.**")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="데이콘 본선 API 프록시 탐침 — 어느 경로·모델이 열려 있나")
    ap.add_argument("--model", action="append", default=None,
                    help="이 모델만 (여러 번 가능). 기본은 셋 다")
    ap.add_argument("--base", default=None, help="Base URL 덮어쓰기")
    ap.add_argument("--json", dest="out", default=None, help="결과 저장 경로")
    ap.add_argument("--pick", action="store_true",
                    help="모델 고르기 (사전명세 §4) — 지연·출력토큰·JSON "
                         "준수율만. 모델당 10회 · 총 30회. **판정 정확도는 "
                         "안 잰다**")
    ap.add_argument("--rounds", type=int, default=1,
                    help="`--pick` 반복 바퀴 수. 지연은 망을 같이 재므로 "
                         "**2 이상 권장**(명세 §4)")
    ap.add_argument("--determinism", action="store_true",
                    help="**온도 0 을 못 쓰는 모델**에서 재현성이 남아 "
                         "있는지 잰다 — temperature·seed 수용 여부와 "
                         "같은 질문 N회 일치율")
    ap.add_argument("-n", type=int, default=5,
                    help="`--determinism` 반복 횟수 (기본 5)")
    a = ap.parse_args(argv)

    key, src = api_key()
    base = (a.base or base_url()).rstrip("/")
    models = a.model or MODELS

    print("Base   %s" % base)
    print("키     %s   ← %s" % (masked(key), src or "못 찾음"))
    print("모델   %s" % " · ".join(models))
    if src == "OPENAI_API_KEY":
        # 옛 키가 남아 있는 흔한 경우. **401 이 나면 여기부터 의심한다.**
        print("⚠ 옛 `OPENAI_API_KEY` 를 집었다. 본선 키가 맞나 확인해라 —")
        print("   맞다면 그대로, 아니면 `DACON_API_KEY` 로 따로 넣어라.")
    print()

    if not key:
        print("⛔ 키가 없다. 어디를 봤는지 —")
        print(env_diag())
        print()
        print("   **파일에 키를 적지 말고** 둘 중 하나로 준다 —")
        print('   ① 이번 창에서만:  $env:DACON_API_KEY = "실제키"')
        print("   ② `.env` 에 한 줄:  DACON_API_KEY=실제키")
        print("      (`.gitignore` 가 `.env` 를 막고 있어 커밋에 안 들어간다)")
        return 2

    if a.determinism:
        n = max(2, a.n)
        est = len(models) * (5 + len(DET_PROMPTS) * n + n)
        print("결정성 시험 — 모델 %d개 · 최대 **%d회**" % (len(models), est))
        print("⚠ 온도 0 이 막혔다. **재현성이 남아 있는지**를 잰다.")
        print()
        allres = {}
        for m in models:
            allres[m] = determinism(m, key, base, n=n)
            _report_determinism(m, allres[m])
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump({"base": base, "n": n, "결과": allres}, f,
                          ensure_ascii=False, indent=2)
            print("\n저장 %s  (키는 저장하지 않는다)" % a.out)
        return 0

    if a.pick:
        rounds = max(1, a.rounds)
        print("모델 고르기 — 프롬프트 %d × 모델 %d × %d바퀴 = **%d회**"
              % (len(PICK_PROMPTS), len(models), rounds,
                 len(PICK_PROMPTS) * len(models) * rounds))
        print("⛔ 명세 §4: **자격(JSON≥90%%) → 지연 → 출력토큰 → 이름순.**")
        print("   같은 프롬프트를 세 모델에 **이어서** 보낸다(라운드 로빈) —")
        print("   모델별로 뭉쳐 돌리면 **망 상태와 모델 차이가 섞인다.**")
        print()
        res = pick(models, key, base, rounds=rounds)
        _report_pick(res)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump({"base": base, "결과": res}, f,
                          ensure_ascii=False, indent=2)
            print("\n저장 %s  (키는 저장하지 않는다)" % a.out)
        return 0

    rows: List[Dict[str, Any]] = []
    for m in models:
        rows.extend(probe(m, key, base))

    print("%-16s %-16s %6s %7s  %s" % ("모델", "경로", "상태", "초", "결과"))
    print("-" * 74)
    for r in rows:
        txt = _text_of(r)
        if r.get("ok"):
            note = "«%s»" % (txt[:24] or "(빈 응답)")
        else:
            note = "%s %s" % (r.get("error", ""), r.get("hint", ""))
        print("%-16s %-16s %6s %7s  %s" % (
            r.get("model", ""), r.get("경로", ""),
            r.get("status") if r.get("status") is not None else "—",
            r.get("초", ""), note))

    # ── 판정 — **추측하지 않고 관측한 것만** ──────────────────────
    chat_ok = [r for r in rows if r["경로"] == "chat/completions" and r.get("ok")]
    resp_ok = [r for r in rows if r["경로"] == "responses" and r.get("ok")]

    print()
    print("=" * 74)
    if chat_ok:
        print("✅ **chat/completions 가 열려 있다** — LiteLLM 을 거의 그대로 쓴다.")
        print("   `io/llm.py` 에 api_base + api-key 헤더만 배선하면 된다.")
    elif resp_ok:
        print("⚠ **responses 만 열려 있다** — LiteLLM 의 completion() 은 못 간다.")
        print("   어댑터 한 겹이 필요하다. `계획_9월.md` 에 반영해라.")
    else:
        print("⛔ **둘 다 실패했다.** 위 상태·힌트를 그대로 보내라.")
        print("   ⚠ 이건 «한도 소진» 이 아니라 «확인 실패» 다 — 섞지 마라.")

    # 팀 잔량. 이게 크레딧 효율 15점의 원자료다.
    seen = {}
    for r in rows:
        for k, v in (r.get("headers") or {}).items():
            seen[k] = v
    if seen:
        print()
        print("팀 사용량 헤더 —")
        for k in TEAM_HEADERS:
            if k in seen:
                print("  %-34s %s" % (k, seen[k]))
        print("  ⚠ 잔여량은 안내문상 **추정치**다. 정확한 값은 운영진 문의.")
    else:
        print()
        print("⚠ 팀 사용량 헤더가 **안 왔다.** 성공한 요청이 없거나 프록시가")
        print("  이 응답에는 안 붙인 것이다. 성공 응답에서 다시 확인해라.")

    # ⚠ **경로마다 따로 찍는다.** 09-09 첫 실행에서 «첫 usage 하나» 만
    #   찍었더니 그게 Responses 형식이었고, `chat/completions` 쪽 형식은
    #   못 본 채로 넘어갈 뻔했다. **파이프라인이 실제로 쓰는 것은 후자다.**
    print()
    for path in ("responses", "chat/completions"):
        u = next((_usage_of(r) for r in rows
                  if r.get("경로") == path and _usage_of(r)), None)
        if u is None:
            print("본문 usage [%s] — 없음" % path)
            continue
        names = sorted(k for k in u if k.endswith("_tokens"))
        print("본문 usage [%s] — %s" % (path, json.dumps(u, ensure_ascii=False)))
        print("            키 이름: %s" % ", ".join(names))

    if a.out:
        # ⚠ 키는 어디에도 안 남긴다.
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"base": base, "모델": models, "결과": rows},
                      f, ensure_ascii=False, indent=2)
        print("\n저장 %s  (키는 저장하지 않는다)" % a.out)

    return 0 if (chat_ok or resp_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
