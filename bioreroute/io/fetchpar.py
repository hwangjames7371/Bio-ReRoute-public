"""큰 파일을 **연결 여러 개로 나눠** 받는다. 설치할 것이 없다.

    py -m bioreroute.io.fetchpar <URL> -o <파일> [-x 16]

## 왜 만들었나

08-12에 `compounds.parquet` 4.2 GB 를 받는 데 **3시간이 넘게** 걸렸다
(389 KB/s). EBI 는 영국에 있고, 단일 TCP 연결은 왕복지연 때문에 대역폭을
못 채운다(BDP 한계). `aria2c` 가 표준 해법이지만 **설치가 또 하나의 관문**
이고, 승우의 PowerShell 에서 바로 막혔다.

표준 라이브러리로 되는 일이라 여기 둔다. **새 의존성 0개.**

## 이 도구가 하지 않는 것 — 먼저 적는다

- **속도를 보장하지 않는다.** 병목이 회선 자체면 연결을 늘려도 그대로다.
  그래서 **처음 몇 초의 실측 속도를 찍는다** — 판단은 사람이 한다
- **내용을 검사하지 않는다.** 크기와 이어받기만 본다.
  parquet 이면 `io.fto.parquet_state()` 로 따로 확인해라
- 서버가 `Range` 를 안 받으면 **단일 연결로 떨어지고, 그렇다고 말한다.**
  조용히 느려지지 않는다

## 이어받기

`<파일>.part` 에 **끝낸 조각 번호**를 적는다. 중간에 끊고 다시 돌리면
남은 것만 받는다. 08-11 DRKG 때 끊겨서 처음부터 다시 받았고, 그게
이 파일이 있는 이유의 절반이다.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

# **HTTP 헤더는 latin-1 이다.** 한글을 넣으면 `UnicodeEncodeError` 로
# 요청 자체가 안 나가고, 우리 코드는 그걸 «서버에 못 물었다» 로 읽는다 —
# 즉 **네트워크 장애로 오인**한다. 실측으로 첫 시험에서 바로 걸렸다.
UA = "Bio-ReRoute/1.0 (research; +https://osf.io/wc5zn)"
CHUNK = 8 << 20          # 8 MiB. 너무 잘게 나누면 요청 왕복이 이득을 먹는다
RETRY = 4


def _head(url: str, timeout: float = 30.0) -> Dict[str, Any]:
    """크기와 **Range 지원 여부**. 둘 다 모르면 병렬로 못 받는다."""
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": UA})
    out: Dict[str, Any] = {"size": None, "ranges": False, "error": None}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            cl = r.headers.get("Content-Length")
            out["size"] = int(cl) if cl and cl.isdigit() else None
            out["ranges"] = (r.headers.get("Accept-Ranges", "")
                             .lower() == "bytes")
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    return out


def _get_range(url: str, a: int, b: int, timeout: float) -> bytes:
    """`[a, b]` 바이트. **206 이 아니면 예외를 낸다.**

    200 을 받으면 서버가 Range 를 무시하고 **전체**를 보낸 것이다. 그걸
    조각으로 알고 쓰면 **파일 한가운데에 처음부터가 박힌다** — 조용한
    오염이라 크기 검사도 통과한다. 그래서 상태 코드를 반드시 본다.
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Range": "bytes=%d-%d" % (a, b)})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status != 206:
            raise IOError("서버가 Range 를 무시했다 (status %d) — 병렬 불가"
                          % r.status)
        d = r.read()
    if len(d) != b - a + 1:
        raise IOError("조각 길이가 다르다 — 요청 %d, 받음 %d"
                      % (b - a + 1, len(d)))
    return d


def _part_path(out: str) -> str:
    return out + ".part"


def _load_done(out: str, n: int, size: int) -> set:
    """끝낸 조각 번호. **크기가 다르면 처음부터 받는다.**"""
    p = _part_path(out)
    if not (os.path.exists(p) and os.path.exists(out)):
        return set()
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return set()
    if d.get("size") != size or d.get("chunks") != n:
        return set()                     # 원본이 바뀌었다. 섞으면 안 된다
    return set(d.get("done") or [])


def _save_done(out: str, done: set, n: int, size: int) -> None:
    tmp = _part_path(out) + ".tmp"
    json.dump({"size": size, "chunks": n, "done": sorted(done)},
              open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, _part_path(out))     # **원자적으로.** 반쯤 쓴 진행표 금지


def download(url: str, out: str, conns: int = 16, chunk: int = CHUNK,
             timeout: float = 60.0, log=print) -> Dict[str, Any]:
    """받는다. 돌려주는 값에 **왜 그렇게 됐는지**를 담는다."""
    res: Dict[str, Any] = {"ok": False, "url": url, "out": out,
                           "size": None, "parallel": False, "resumed": 0,
                           "seconds": None, "mb_s": None, "error": None}
    h = _head(url)
    if h["error"]:
        res["error"] = "**서버에 못 물었다** — %s" % h["error"]
        return res
    size = h["size"]
    res["size"] = size
    t0 = time.time()

    if not size or not h["ranges"]:
        # ── 병렬 불가. **그렇다고 말하고** 단일 연결로 받는다 ──────
        why = "크기를 모른다" if not size else "서버가 Range 를 안 받는다"
        log("  ⚠ 병렬 불가(%s) — 단일 연결로 받는다. 속도는 그대로다" % why)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r, \
                open(out, "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
        res["seconds"] = round(time.time() - t0, 1)
        res["size"] = os.path.getsize(out)
        res["mb_s"] = round(res["size"] / 1e6 / max(res["seconds"], 1e-9), 2)
        res["ok"] = True
        return res

    res["parallel"] = True
    n = (size + chunk - 1) // chunk
    done = _load_done(out, n, size)
    res["resumed"] = len(done)
    if done:
        log("  이어받기 — %d/%d 조각은 이미 있다 (%.1f%%)"
            % (len(done), n, 100 * len(done) / n))

    if not os.path.exists(out) or os.path.getsize(out) != size:
        with open(out, "wb") as f:            # 자리를 먼저 잡는다
            f.truncate(size)
        done = set()
        res["resumed"] = 0

    lock = threading.Lock()
    fh = open(out, "r+b")
    todo = [i for i in range(n) if i not in done]
    got = [0]

    def work(i: int) -> int:
        a = i * chunk
        b = min(a + chunk, size) - 1
        last = None
        for k in range(RETRY):
            try:
                d = _get_range(url, a, b, timeout)
                with lock:
                    fh.seek(a)
                    fh.write(d)
                    done.add(i)
                    got[0] += len(d)
                    if len(done) % 16 == 0:
                        _save_done(out, done, n, size)
                return i
            except Exception as e:            # 재시도. **조용히 넘기지 않는다**
                last = e
                time.sleep(1.5 * (k + 1))
        raise IOError("조각 %d 실패 — %s: %s" % (i, type(last).__name__,
                                              str(last)[:100]))

    try:
        with ThreadPoolExecutor(max_workers=conns) as ex:
            futs = {ex.submit(work, i): i for i in todo}
            k = 0
            for fu in as_completed(futs):
                fu.result()                   # 예외를 삼키지 않는다
                k += 1
                el = time.time() - t0
                if k % 8 == 0 or k == len(todo):
                    log("  %5.1f%%  %6.2f MB/s  경과 %4.0f초"
                        % (100 * (len(done)) / n, got[0] / 1e6 / max(el, 1e-9),
                           el))
    except Exception as e:
        res["error"] = ("**받다 멈췄다** — %s: %s. 같은 명령을 다시 돌리면 "
                        "남은 조각만 받는다" % (type(e).__name__, str(e)[:140]))
        return res
    finally:
        with lock:
            _save_done(out, done, n, size)
        fh.close()

    res["seconds"] = round(time.time() - t0, 1)
    res["mb_s"] = round(got[0] / 1e6 / max(res["seconds"], 1e-9), 2)
    real = os.path.getsize(out)
    if real != size:
        res["error"] = "**크기가 다르다** — 받은 %d · 알린 %d" % (real, size)
        return res
    try:
        os.remove(_part_path(out))
    except OSError:
        pass
    res["ok"] = True
    return res


def listdir(url: str, timeout: float = 30.0):
    """FTP-over-HTTP 색인에서 **파일 이름과 크기**를 뽑는다.

    ## 왜 필요한가 — 결함 204

    `surechembl_patents.parquet` 를 받으려다 **404** 가 났다. 같은
    디렉터리의 다른 다섯은 받아졌다. **나머지가 되니까 이것도 되겠지로
    이름을 추정했고, 그 URL 은 한 번도 성공한 적이 없어 검증된 적이 없다.**
    틀린 값이 `야간실행.ps1` → `FTO받기.ps1` → `밤새.ps1` 세 파일로 번졌다.

    > **추측으로 이름을 하나 더 만들면 네 번째 파일로 번진다.**
    > 목록을 받아서 **자료가 이름을 말하게** 한다.

    돌려주는 것 — `[{name, size}]`. 못 읽으면 `None`(빈 목록이 아니다).
    """
    import re as _re
    import urllib.request as _u
    try:
        req = _u.Request(url if url.endswith("/") else url + "/",
                         headers={"User-Agent": UA})
        with _u.urlopen(req, timeout=timeout) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception:
        return None
    out, seen = [], set()
    # `<a href="이름">` + 그 뒤 텍스트에서 크기를 줍는다. 서버 서식이
    # 여러 가지라 **크기는 못 읽어도 이름은 낸다**
    for m in _re.finditer(r'<a href="([^"?/][^"]*)"[^>]*>[^<]*</a>([^<\n]*)', html):
        name = m.group(1)
        if name in seen or name.startswith(("?", "/")):
            continue
        seen.add(name)
        tail = m.group(2)
        sz = None
        g = _re.search(r"(\d[\d,]*)\s*$", tail.strip()) or \
            _re.search(r"([\d.]+[KMGT])\s*$", tail.strip())
        if g:
            sz = g.group(1)
        out.append({"name": name, "size": sz})
    return out


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="연결 여러 개로 나눠 받기")
    ap.add_argument("url")
    ap.add_argument("--list", action="store_true",
                    help="**디렉터리 목록만 찍는다** — 이름을 추측하지 않는다 (결함 204)")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("-x", "--conns", type=int, default=16)
    ap.add_argument("--chunk-mb", type=int, default=8)
    a = ap.parse_args(argv)
    if a.list:
        items = listdir(a.url)
        if items is None:
            print("  ✗ 목록을 못 읽었다 — 서버가 색인을 안 준다"); return 1
        print("  %s" % a.url)
        print("  파일 %d개" % len(items))
        for x in items:
            print("    %-52s %s" % (x["name"], x["size"] or ""))
        return 0
    if not a.out:
        ap.error("-o/--out 이 필요하다 (또는 --list)")

    print("=" * 66)
    print("받는다 — 연결 %d개" % a.conns)
    print("=" * 66)
    r = download(a.url, a.out, conns=a.conns, chunk=a.chunk_mb << 20)
    print("-" * 66)
    if not r["ok"]:
        print("실패: %s" % r["error"])
        return 1
    print("완료  %.2f GB · %.0f초 · **%.2f MB/s**%s"
          % ((r["size"] or 0) / 1e9, r["seconds"] or 0, r["mb_s"] or 0,
             "" if r["parallel"] else "  (단일 연결)"))
    print("\n**크기만 맞춘 것이다.** parquet 이면 무결성을 따로 봐라:")
    print("  py -c \"from bioreroute.io import fto; import json; "
          "print(json.dumps(fto.parquet_state('%s'),ensure_ascii=False,indent=1))\""
          % os.path.basename(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
