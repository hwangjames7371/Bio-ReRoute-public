# -*- coding: utf-8 -*-
"""소표본 통계 — **보고하는 숫자는 코드에서 나와야 한다.**

`wilson` 이 세 파일에 각각 정의돼 있었고, 문서에 실린 Fisher p값은
**터미널에서 손으로 계산해 옮겨 적은 것**이었다. 코드 어디에도 없으니
판 번호도 시험도 없다. 이 프로젝트가 경계하는 바로 그 유형의 숫자다.

여기로 모으고 시험을 붙인다. scipy에 의존하지 않는다 — 표준 라이브러리만
쓴다(설치 환경이 갈리면 재현이 깨진다).
"""

from math import erf, exp, lgamma, log, log1p, sqrt


def wilson(k, n):
    """이항 비율의 95% 신뢰구간 (Wilson score).

    n이 작거나 비율이 0·1에 붙으면 정규근사(Wald)는 구간이 음수로
    가거나 폭이 0이 된다. 이 프로젝트의 n은 7~42라 Wald를 쓰면 안 된다.
    """
    if not n:
        return 0.0, 0.0
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, c - h), min(1.0, c + h)


def _lchoose(n, k):
    if k < 0 or k > n:
        return float("-inf")
    return lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)


def fisher(a, b, c, d):
    """2×2 양측 Fisher 정확검정.

        [[a, b],
         [c, d]]

    기대빈도가 5 미만인 칸이 있어 카이제곱을 쓸 수 없다. 양측은
    **관측만큼 또는 그보다 드문 표** 전부의 확률합으로 정의한다
    (점확률법). R의 `fisher.test` 기본값과 같은 규약이다.
    """
    n = a + b + c + d
    if n == 0:
        return 1.0
    r1, c1 = a + b, a + c
    base = _lchoose(n, c1)

    def logp(x):
        return _lchoose(r1, x) + _lchoose(n - r1, c1 - x) - base

    obs = logp(a)
    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    tot = 0.0
    for x in range(lo, hi + 1):
        p = logp(x)
        if p <= obs + 1e-9:          # 부동소수 동률을 살린다
            tot += exp(p)
    return min(1.0, tot)


def fmt_p(p):
    """p값 표기. 소표본에서 '유의하다'로 읽히지 않게 문구를 붙인다."""
    s = "p<0.001" if p < 0.001 else "p=%.3f" % p
    return s + (" — 유의하지 않다" if p >= 0.05 else "")


def _z_two_sided(alpha=0.05):
    """양측 α 의 임계 z. **α 를 받으면 실제로 써야 한다** (결함 152).

    역정규분포는 표준 라이브러리에 없다. Acklam 유리근사(정밀도 ~1e-9)를
    쓴다 — 우리가 쓰는 α(0.05·0.025·0.01·0.001)에서 소수 6자리까지 맞다.
    """
    p = 1.0 - alpha / 2.0
    if p <= 0.0 or p >= 1.0:
        return 1.959963985
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = sqrt(-2 * log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > ph:
        q = sqrt(-2 * log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def power2(p1, p2, n1, n2, alpha=0.05):
    """두 비율 비교의 사후 검정력 (정규근사).

    **`p >= 0.05` 를 '차이가 없다'로 읽는 것을 막으려고 있다.** 이 프로젝트의
    n은 20~42라 웬만한 차이는 애초에 잡히지 않는다. 검정력을 같이 적지 않으면
    "유의하지 않다"가 "효과 없다"로 오독된다.

    정규근사이므로 소표본에서 정확하지 않다. **자릿수만 읽어라.**
    """
    if not (n1 and n2):
        return 0.0
    # ⚠ 앞판은 `1.959963985 if alpha == 0.05 else 1.959963985` 였다 —
    #   **삼항 연산자 양쪽이 같은 상수**라 `alpha` 가 통째로 무시됐다
    #   (결함 152). 이 저장소는 Bonferroni·Holm 을 자랑하는데, 보정 후
    #   임계값(0.01)으로 검정력을 물으면 **조용히 α=0.05 답을 줬다.**
    z = _z_two_sided(alpha)
    pbar = (p1 * n1 + p2 * n2) / (n1 + n2)
    se0 = sqrt(pbar * (1 - pbar) * (1 / n1 + 1 / n2))
    se1 = sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    # ⚠ `se1 == 0` 은 **완전 분리**(p1=0, p2=1)를 포함한다. 앞판은 거기서
    #   `0.0` 을 냈다 — 깔때기가 완벽히 작동한 경우에 «검정력 0%%» 가
    #   찍힌다는 뜻이고 참값은 1.0 이다. **방향이 정반대**였고,
    #   짝이라던 `power1` 은 같은 입력에 1.0 을 냈다 (결함 152).
    if se1 <= 0:
        if se0 <= 0:
            return 1.0 if p1 != p2 else alpha / 2
        se1 = se0
    return max(0.0, min(1.0, 0.5 * (1 + erf(((abs(p1 - p2) - z * se0) / se1)
                                            / sqrt(2)))))


def binom_ge(k, n, p):
    """P(X >= k | Bin(n, p)) — **알려진 비율 p 대비** 일표본 정확검정(단측).

    ## 왜 Fisher를 쓰면 안 되는가 (결함 32)

    비교 상대가 **관측 표본이 아니라 상수**일 때는 2×2가 성립하지 않는다.
    무작위 기준선은 48만 회 모의로 얻은 값이라 자체 오차가 사실상 0이다.
    이걸 "n번 중 k번 나온 관측"으로 바꿔 Fisher에 넣으면 **없는 표본 오차를
    집어넣어** p값이 부풀려진다.

      실측: 생성 실험에서 Fisher가 p=0.122 를 찍었는데
            같은 자료의 올바른 이항검정은 p=0.0002 였다. 600배 차이다.

    Fisher를 쓸 자리는 **두 관측 표본**을 비교할 때다(strict vs loose).
    """
    if not n or k <= 0:
        return 1.0
    if p <= 0:
        return 0.0
    return min(1.0, sum(exp(_lchoose(n, i) + i * log(p) + (n - i) * log1p(-p))
                        for i in range(k, n + 1)))


def mcnemar(b, c):
    """짝지은 이분 자료의 **McNemar 정확검정** (양측 p값).

    ## 왜 필요한가 — 09-21 · 봉인 명세 §9가 시킨 것

    옛 모델과 새 모델을 **같은 387쌍**에서 비교할 때 맞는 틀이다.
    `power1`(일표본)은 기준선을 **상수**로 보고, `power2`(두 표본)는
    **독립**으로 본다. **우리는 둘 다 아니다** — 같은 항목을 두 번 쟀다.

    b = 옛은 기각, 새는 비기각 · c = 옛은 비기각, 새는 기각.
    **일치 쌍(a, d)은 정보를 주지 않는다** — 검정력은 오직 `b+c` 에 달렸다.

    ⚠ **카이제곱 근사를 안 쓴다.** `b+c` 가 작으면(여기서는 38)
    근사가 빗나간다. 이항 정확검정이 맞다 — `CLAUDE.md §4`
    *«소표본에 Wald 금지»* 와 같은 이유다.
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    # 양측: P(X <= k) + P(X >= n-k) = 2 * P(X <= k)  (p=0.5 대칭)
    tail = sum(exp(_lchoose(n, i) - n * log(2.0)) for i in range(0, k + 1))
    return min(1.0, 2.0 * tail)


def mcnemar_power(n_disc, psi, alpha=0.05):
    """불일치 쌍 `n_disc` 개, 참 비율 `psi` 일 때 McNemar 정확검정의 검정력.

    `psi` = c / (b+c) — **불일치 중 «새 쪽이 기각» 인 비율.**
    0.5 면 효과 없음.

    기각역을 **정확검정으로 먼저 정하고**(양측 α 이하가 되는 k 집합),
    그 기각역에 참 `psi` 에서 떨어질 확률을 더한다. 정규근사를 안 쓰므로
    소표본에서도 자릿수가 아니라 **값을 읽어도 된다.**

    ⚠ **사후 검정력의 한계는 그대로다** — 관측된 효과크기를 그대로
    넣으면 p값의 단조함수가 되어 정보가 없다(Hoenig & Heisey 2001).
    그래서 부르는 쪽이 **미리 정한 효과크기**를 넣어야 한다.
    """
    n = int(n_disc)
    if n <= 0:
        return 0.0
    rej = [k for k in range(n + 1) if mcnemar(k, n - k) <= alpha]
    if not rej:
        return 0.0
    return sum(exp(_lchoose(n, k) + k * log(psi) + (n - k) * log1p(-psi))
               for k in rej)


def power1(p0, p1, n, alpha=0.05):
    """알려진 비율 p0 대비 일표본 검정의 사후 검정력 (정규근사).

    `power2` 와 짝이다. 기준선이 상수인 비교에 `power2` 를 쓰면 자유도를
    두 배로 세어 검정력을 과소평가한다.
    """
    if not n:
        return 0.0
    z = _z_two_sided(alpha)
    se0, se1 = sqrt(p0 * (1 - p0) / n), sqrt(max(p1 * (1 - p1), 1e-12) / n)
    return max(0.0, min(1.0, 0.5 * (1 + erf(((abs(p1 - p0) - z * se0) / se1)
                                            / sqrt(2)))))


def mde(p1, n1, n2, target=0.80, alpha=0.05):
    """p1을 기준으로 **검정력 target에 도달하는 최소 p2**. 없으면 None."""
    if not (n1 and n2):
        return None
    step = 0.005
    for i in range(1, int(1 / step) + 1):
        p2 = min(1.0, p1 + i * step)
        if power2(p1, p2, n1, n2, alpha) >= target:
            return p2
        if p2 >= 1.0:
            break
    return None
