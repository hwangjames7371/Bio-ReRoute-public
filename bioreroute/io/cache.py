# -*- coding: utf-8 -*-
"""통합 디스크 캐시.

캐시를 1급 시민으로 두는 이유
  1. 개발 중 반복 실행 비용 절감
  2. 시연 중 네트워크 사고 차단 (제안서의 '데모 하드캐시')
  3. 재현성 — 같은 입력이 같은 판정을 내는지 검증 가능
"""

import json
import os
import re
import threading
from typing import Any, Dict, Optional

_STORE: Dict[str, Dict[str, Any]] = {}
_PATH = "pubmed_cache.json"
_ENABLED = True
_LOADED = [False]          # load() 를 거쳤는가 — save() 의 방어에 쓴다

# 이 횟수마다 자동 저장. 0이면 끈다(시험용).
AUTOSAVE = 20
_SINCE = [0]
# 병렬 실행에서 `_STORE`·`_SINCE`·`save()` 가 겹치는 것을 막는다 (08-18).
#   스레드가 없을 때는 동작이 같다 — 있을 때만 달라진다.
_LOCK = threading.RLock()


def configure(path: str = "pubmed_cache.json", enabled: bool = True) -> None:
    """캐시 경로를 바꾼다. **메모리 저장소를 비운다** (결함 62).

    ## 왜 비워야 하는가

    첫 판은 `_PATH` 와 `_ENABLED` 만 바꾸고 `_STORE` 를 그대로 뒀다.
    그래서 **한 프로세스 안에서 경로를 바꾸면 앞 경로의 항목이 그대로
    조회됐다.** `get`·`has` 는 `_STORE` 를 직접 읽고 `load()` 를 부르지
    않으므로 아무것도 그걸 지우지 않았다.

    실측으로 잡힌 경로 — 활성부위 pLDDT 시험에서 표적을 바꿔 두 번
    `assess()` 를 부르는데, 두 번째가 **첫 번째의 UniProt 응답을**
    캐시에서 받아 `basis=활성부위` 를 냈다. 모의를 바꿨는데 결과가 안
    바뀌었다.

    > **시험이 앞선 시험의 캐시로 통과할 수 있었다는 뜻이다.**
    > 이 파일이 이미 네 번 당한 유형(결함 5·26·27·37)의 다섯 번째이고,
    > 이번엔 **검사기 쪽에서** 났다.

    운영 호출부는 전부 `configure()` 바로 뒤에 `load()` 를 부르므로
    비워도 손실이 없다(`run` · `discover` · `funnel` · `demo` · `ceiling`).
    `netcheck` 은 **빈 캐시를 원하는** 쪽이라 이 동작이 오히려 맞다.
    """
    global _PATH, _ENABLED, _STORE
    _PATH, _ENABLED = path, enabled
    _STORE = {}            # **앞 경로의 항목을 물고 넘어가지 않는다** (결함 62)
    _SINCE[0] = 0
    _LOADED[0] = False     # 경로가 바뀌면 그 파일은 아직 안 읽은 것이다


def load() -> None:
    """디스크에서 읽는다.

    ⛔ **09-21 — 읽기에 실패했는데 «읽었다» 고 표시해 33MB 를 날렸다.**

    앞판은 `except: _STORE = {}` 뒤에 **무조건** `_LOADED[0] = True` 를
    놓았다. 그러면 `save()` 의 병합 방어가 *«이미 읽었으니 병합 불필요»*
    로 판단해 **빈 딕셔너리를 그대로 디스크에 쓴다.**

      실측: `pubmed_cache.json` 이 33MB → **2바이트(`{}`)** 가 됐다.
      C6 실행 결과는 무사했지만 **그 시점의 문헌 상태를 고정할 수단을
      또 잃었다** — 08-05 에 2.7MB 를 같은 이유로 잃고 *"구조로 막는다"*
      고 적어 둔 바로 그 자리다. **플래그로 막으려 한 것이 문제였다.**

    읽기는 **정상적으로 실패할 수 있다** — 33MB JSON 을 다른 프로세스가
    쓰는 중이면 불완전하게 읽힌다(그 현상을 같은 날 눈으로 봤다).
    그러니 실패를 «빈 캐시» 로 승격시키면 안 된다.

    **못 읽었으면 «안 읽은 상태» 로 둔다.** 그래야 `save()` 가 병합한다.
    """
    global _STORE
    _STORE = {}
    ok = False
    if _ENABLED and os.path.exists(_PATH):
        try:
            with open(_PATH, "r", encoding="utf-8") as f:
                _STORE = json.load(f)
            ok = True
        except Exception as e:
            # **조용히 비우지 않는다** — 결함 99(침묵과 통과는 다르다)
            print("  ! 캐시를 못 읽었다 (%s: %s) — **빈 캐시로 취급하지 "
                  "않는다.** 저장할 때 디스크와 병합한다"
                  % (type(e).__name__, str(e)[:80]))
    elif not _ENABLED:
        ok = True              # 일부러 끈 것이다. 읽은 것으로 본다
    _LOADED[0] = ok


def save() -> None:
    """디스크에 내린다. **읽지 않고 쓰면 병합한다.**

    호출부가 `load()` 를 잊으면 `_STORE` 가 빈 dict 로 시작하고, 여기서
    그대로 쓰면 **기존 캐시를 통째로 덮는다.**

    실제로 당했다 — 2026-08-05 홀드아웃 짝짓기(`bench.match`)가 `load()` 를
    부르지 않아 2.7MB(초록·등록부 본문·PubChem 동의어)가 `SEARCH` 580개만
    남기고 사라졌다. 백업이 없었다. 측정 결과 파일은 무사했지만 **그 시점의
    문헌 상태를 고정할 수단을 잃었다** — PubMed은 시간이 지나면 바뀐다.

    호출을 기억하라는 규약으로는 막히지 않는다(오늘만 다섯 번째 유형이다).
    그래서 **구조로 막는다** — `load()` 를 안 거쳤으면 디스크 내용을 먼저
    읽어 병합한 뒤 쓴다. 메모리 값이 디스크 값을 이긴다(더 최신이므로).
    """
    # ⚠ 08-18 — **`with _LOCK` 이 여기 있어야 위 주석이 참이 된다.**
    #   `put()` 이 *"저장은 잠금 밖에서 — save() 도 잠근다"* 라고 적었는데
    #   정작 `save()` 가 안 잠그면 그건 **주석이 거짓말**인 것이다.
    #   `RLock` 이라 같은 스레드가 다시 들어와도 안 막힌다.
    with _LOCK:
      try:
          out = _STORE
          # ── ⛔ 09-21 · **빈 것으로 덮지 않는다** — 최종 방어 ──────────
          #
          #   아래 병합은 `_LOADED[0]` 플래그에 기댄다. 그런데 09-21 에
          #   **`load()` 가 읽기에 실패하고도 «읽었다» 고 표시**해서 그
          #   방어가 통째로 건너뛰어졌고, **33MB 가 2바이트가 됐다.**
          #   `load()` 쪽도 고쳤지만 **플래그 하나에 33MB 를 걸지 않는다** —
          #   어떤 경로로 오든 **비어 있으면 안 쓴다.**
          #
          #   ⚠ 캐시를 «비우는» 정당한 경로는 없다. 지우고 싶으면
          #     파일을 지우면 된다. 이 함수의 일이 아니다.
          if not out and os.path.exists(_PATH):
              try:
                  _cur = os.path.getsize(_PATH)
              except Exception:
                  _cur = 0
              if _cur > 2:
                  print("  ! **빈 캐시로 %d바이트를 덮으려 했다 — 하지 않는다.**"
                        % _cur)
                  print("    (캐시를 비우려면 파일을 직접 지워라. "
                        "이 경로는 결함 322 가 난 자리다)")
                  return
          if not _LOADED[0] and os.path.exists(_PATH):
              try:
                  with open(_PATH, "r", encoding="utf-8") as f:
                      disk = json.load(f)
                  if isinstance(disk, dict) and disk:
                      merged = dict(disk)
                      merged.update(_STORE)
                      print("  ! 캐시를 읽지 않고 저장하려 했다 — 디스크 %d개와 "
                            "병합한다(%d → %d)"
                            % (len(disk), len(_STORE), len(merged)))
                      out = merged
              except Exception as _e:
                  # ── ⛔ 09-21 · **«메모리 것이라도 남긴다» 가 33MB 를 먹었다** ──
                  #
                  #   앞판은 여기서 그냥 `pass` 했다. 그러면 **디스크를 못
                  #   읽은 채로 메모리 것(때로는 한 항목)을 그대로 덮는다.**
                  #
                  #   못 읽는 이유는 둘인데 **구별할 수 없다** —
                  #     ① 파일이 진짜 깨졌다        → 새로 써도 된다
                  #     ② 다른 프로세스가 쓰는 중이다 → **덮으면 큰일난다**
                  #   33MB JSON 은 쓰는 데 수 초가 걸리고, 그동안 읽으면
                  #   반드시 ②가 된다. **같은 날 눈으로 봤다**(32.8MB 가
                  #   22.5MB 로 보였고 27초 뒤 32.9MB 였다).
                  #
                  #   구별할 수 없으면 **잃지 않는 쪽**을 고른다 —
                  #   백업을 뜨고 쓴다. 백업조차 실패하면 **안 쓴다.**
                  try:
                      import shutil as _sh
                      import time as _tm
                      _bak = "%s.unreadable_%s" % (
                          _PATH, _tm.strftime("%Y%m%d_%H%M%S"))
                      _sh.copy2(_PATH, _bak)
                      print("  ! 디스크 캐시를 못 읽었다 (%s) — "
                            "**%s 로 백업하고** 새로 쓴다"
                            % (type(_e).__name__, os.path.basename(_bak)))
                  except Exception as _e2:
                      print("  ! 디스크 캐시를 못 읽었고 **백업도 실패**했다 "
                            "(%s) — **덮지 않는다.** 캐시는 최적화이고, "
                            "잃는 쪽이 더 나쁘다" % type(_e2).__name__)
                      return
          # ── ⛔ 09-25 · **쓰는 도중에 끊기면 반쪽 파일이 남았다** (결함 335) ──
          #
          #   앞판은 `open(_PATH, "w")` 로 **바로** 썼다. 그러면 쓰는 도중 무엇이
          #   끊든(예외 · 시그널 · 프로세스 종료) 그 순간의 반쪽 JSON 이 남는다.
          #   09-25 02:20 에 실제로 그랬다 — 샌드박스 회귀 실행의 시험별 시간
          #   제한이 `json.dump` 한가운데를 끊어 **48.9MB 가 17.9MB 반쪽**이 됐다.
          #   읽는 쪽도 같은 병이다 — 09-21 에 쓰는 중인 파일을 «22.5MB» 로 읽었다.
          #
          #   **임시 파일에 다 쓰고 한 번에 바꾼다** — `os.replace` 는 같은 폴더
          #   안에서 원자적이다. 끊기면 **옛 파일이 그대로 남는다.**
          _tmp = "%s.tmp_%d" % (_PATH, os.getpid())
          try:
              with open(_tmp, "w", encoding="utf-8") as f:
                  json.dump(out, f, ensure_ascii=False, indent=1)
              _swap(_tmp, _PATH)
          finally:
              if os.path.exists(_tmp):
                  try:
                      os.remove(_tmp)
                  except OSError:
                      pass
      except Exception as e:
          print("  ! 캐시 저장 실패:", e)


_SWAP_WAIT = 0.25          # 바꿔 넣기 재시도 간격(초) — 시험은 0 으로 둔다


def _swap(src: str, dst: str) -> bool:
    """`src` 를 `dst` 자리로 **한 번에** 옮긴다 (결함 335).

    윈도우는 다른 프로세스가 `dst` 를 열고 있으면 바꿔 넣기를 잠깐 거부한다.
    몇 번 다시 해 보고(최대 약 5초), 끝내 안 되면 **옛 파일을 그대로 둔다** —
    이번 항목은 메모리에 남아 있으므로 다음 저장 때 다시 시도된다.
    반쪽을 쓰는 것보다 낫다.
    """
    import time as _tm
    for i in range(6):
        try:
            os.replace(src, dst)
            return True
        except PermissionError:
            _tm.sleep(_SWAP_WAIT * (i + 1))
    print("  ! 캐시를 바꿔 넣지 못했다(다른 프로세스가 잡고 있다) — **옛 파일을 그대로 "
          "둔다.** 새 항목은 다음 저장 때 다시 시도한다")
    return False


def get(key: str) -> Optional[Any]:
    return _STORE.get(key) if _ENABLED else None


# 일시적 장애를 뜻하는 오류. **이건 캐시에 남기면 안 된다.**
_TRANSIENT = re.compile(
    r"Tunnel connection|URLError|HTTPError: HTTP Error 5\d\d"
    r"|HTTP Error 429|timed out|timeout|Connection (reset|refused|aborted)"
    r"|Temporary failure|Name or service not known|SSLError|IncompleteRead"
    r"|esearch 무응답",                 # 결함 327 — 개수 없는 응답은 저장하지 않고 다시 묻는다
    re.I)


def transient(value: Any) -> bool:
    """이 결과가 **일시적 장애** 때문인가."""
    if not isinstance(value, dict):
        return False
    return bool(value.get("error") and _TRANSIENT.search(str(value["error"])))


def put(key: str, value: Any) -> Any:
    """저장하고, 일정 횟수마다 디스크에 내린다.

    자동 저장이 없으면 30분짜리 실행을 중간에 끊었을 때 **비싼 LLM 호출을
    통째로 잃는다.** 캐시는 비용을 아끼려고 만든 것인데 정작 사고가 났을 때
    아무것도 못 건지면 존재 이유가 없다.

    ## 일시적 장애는 저장하지 않는다 (결함 37)

    전에는 오류도 그대로 저장했다. 그래서 **몇 분짜리 네트워크 장애가
    캐시에 박혀 영구화됐다.** 다시 돌려도 캐시가 그 오류를 돌려주므로
    스스로는 절대 낫지 않는다.

      실측: `pubmed_cache.json` 에 `Tunnel connection failed` 가 **380개**.
      전부 `NCT…[si]` 질의 — **누출 차단용 PMID 확장**이다. 그 결과
      홀드아웃 sealed 의 라벨 출처 432건 중 **380건(88%)에서
      PMID 수준 차단이 조용히 걸리지 않았다.**

    404·NotFound 같은 **영구적** 오류는 계속 저장한다. 그건 사실이고,
    매번 다시 물으면 조회 예산만 태운다.
    """
    if transient(value):
        return value                     # 값은 돌려주되 **남기지 않는다**
    # ── **잠금** — 08-18. 병렬 실행을 넣기 전에 먼저 건다 ──────────────
    #
    #   `_SINCE[0] += 1` 은 **읽고-고쳐-쓰기**다. 스레드 둘이 겹치면
    #   계수가 어긋나 `save()` 가 안 불리거나 두 번 불린다. 그리고
    #   `save()` 는 디스크 병합까지 하므로 **동시에 들어가면 캐시가 깨진다.**
    #
    #   캐시는 결함 26·27·36·37 이 난 자리다. **병렬을 넣기 전에 잠금을
    #   먼저 거는 것이 순서**다 — 넣고 나서 고치면 그때는 원인을 못 가른다.
    with _LOCK:
        _STORE[key] = value
        _SINCE[0] += 1
        due = bool(AUTOSAVE and _SINCE[0] >= AUTOSAVE)
        if due:
            _SINCE[0] = 0
    if due:                              # 저장은 **잠금 밖에서** — save() 도 잠근다
        save()
    return value


def has(key: str) -> bool:
    return _ENABLED and key in _STORE


def stale(key: str, *fields) -> bool:
    """캐시에 있으나 **요구한 필드가 빠져 있는가.**

    판 번호를 손으로 올리는 규약은 두 번 샜다 —
    등록부 본문(CTGR2)과 ceiling의 조회 캐시에서 각각 한 번씩.
    두 번째는 "무작위배정 0/42"라는 가짜 결정 지표를 만들어
    하마터면 방향 하나를 통째로 버릴 뻔했다.

    사람이 기억해야 하는 규약은 결국 잊힌다. 필요한 필드를 직접 물어
    없으면 다시 받게 한다. 판 번호보다 이쪽이 안전하다.
    """
    if not _ENABLED or key not in _STORE:
        return True
    v = _STORE[key]
    if not isinstance(v, dict):
        return False
    return any(f not in v for f in fields)
