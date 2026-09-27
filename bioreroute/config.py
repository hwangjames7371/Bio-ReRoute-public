# -*- coding: utf-8 -*-
"""설정 로딩 — .env를 환경변수로 올린다.

litellm은 .env를 자동으로 읽지 않는다. 이 모듈이 io/llm.py보다 먼저 import되어야
MODEL 상수가 올바른 값으로 초기화된다. 외부 의존성 없이 직접 파싱한다.
이미 환경변수에 있는 값은 덮어쓰지 않는다(셸 지정이 파일보다 우선).
"""

import os
import pathlib

LOADED = None


def load_env(path=None) -> bool:
    global LOADED
    cands = ([pathlib.Path(path)] if path else []) + [
        pathlib.Path.cwd() / ".env",
        pathlib.Path(__file__).resolve().parent.parent / ".env",
        pathlib.Path(__file__).resolve().parent / ".env",
    ]
    for p in cands:
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and not os.environ.get(k):
                os.environ[k] = v
        LOADED = str(p)
        return True
    return False


def status() -> str:
    # 09-09 — `DACON_API_KEY`(본선 크레딧)와 **프록시 경유 여부**를 같이 찍는다.
    #   프록시가 켜졌는지는 `§3-2` 상 중요한 사실이다 — 켜진 순간부터
    #   **다른 시스템**이므로, 화면이 그 말을 안 하면 나중에 «어느 판이
    #   어느 모델로 돌았나» 를 못 가른다(08-24에 실제로 그랬다).
    keys = [k for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                        "DACON_API_KEY") if os.environ.get(k)]
    base = (os.environ.get("BIOREROUTE_API_BASE") or "").strip()
    seed = (os.environ.get("BIOREROUTE_SEED") or "").strip()
    return "%s · 키 %s · 모델 %s%s%s" % (
        LOADED or ".env 없음",
        ("+".join(k.split("_")[0] for k in keys) if keys else "없음"),
        os.environ.get("BIOREROUTE_MODEL", "gemini/gemini-2.0-flash"),
        (" · 프록시 경유(%s)" % base.split("//")[-1].split("/")[0]) if base
        else " · 직결",
        # 온도 0 이 막힌 뒤로 **seed 가 재현성의 유일한 손잡이**다.
        # 켜졌는지 한 줄에서 보여야 «그날 어떻게 돌았나» 를 가릴 수 있다.
        (" · seed %s" % seed) if seed else " · seed 없음")


load_env()
