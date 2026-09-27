# -*- coding: utf-8 -*-
"""질의 생성 — 짝짓기와 본 측정이 **같은 질의**를 써야 한다.

짝짓기를 엄격 질의('"약" AND "질환"')로 하고 본 측정을 완화 질의로 하면,
짝을 맞춘 기준과 실제로 읽는 문헌이 달라진다. 문헌량 교란을 통제했다고
말할 수 없게 된다. 그래서 한 곳에서만 정의한다.
"""

import re


def clean(s: str) -> str:
    """PubMed 질의에 쓸 수 있게 다듬는다.

    RepoDB 적응증에는 "COVID19 (disease)", "Leukemia, Myelomonocytic, Chronic",
    "Acute lymphoblastic leukemia - category" 같은 표기가 섞여 있다.
    괄호는 PubMed에서 그룹 연산자이고 쉼표도 파싱을 흔든다.
    """
    s = re.sub(r"\s*\([^)]*\)", " ", s or "")
    s = re.sub(r"\s*-\s*category\b", " ", s, flags=re.I)
    s = re.sub(r"[(),;:\[\]]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def pair(drug: str, indication: str) -> str:
    """약-질환 쌍 질의. 짝짓기·F0·팩트체커가 전부 이걸 쓴다."""
    return "%s AND %s" % (clean(drug), clean(indication))
