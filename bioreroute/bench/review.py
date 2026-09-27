# -*- coding: utf-8 -*-
"""사람 판정 기록 — 자동화가 가를 수 없는 8건.

문자열 휴리스틱은 "같은 병의 다른 이름"과 "같은 병의 다른 아형"을 구분하지
못한다. 앞은 TN에서 빼야 하고 뒤는 남겨야 하는데, 판단 근거가 문자열에 없다.

그래서 판정을 코드에 숨기지 않고 여기에 근거와 함께 적는다. 심사에서
"이 라벨 왜 이렇게 정했냐"는 질문에 답할 수 있어야 한다.

각 항목: (약물, 실패 적응증) → (유지|제외, 근거)
"""

DECISIONS = {
    # ── 제외: 같은 병의 다른 이름. 승인약을 TN으로 세면 안 된다 ──────
    ("temozolomide", "Glioblastoma Multiforme"): (
        "제외", "Brain Glioblastoma와 동일 질환. 테모졸로마이드는 GBM 표준치료제"
                "(Stupp 요법)로 2005년 FDA 승인됐다. RepoDB가 이명을 다른 CUI로 "
                "색인해 갈라진 것뿐이다."),
    ("methotrexate", "Acute lymphoblastic leukemia - category"): (
        "제외", "Acute lymphocytic leukemia와 동일 질환. ALL의 두 이름이다. "
                "메토트렉세이트는 ALL 표준 병용요법의 핵심 약제다."),
    ("furosemide", "Heart failure"): (
        "제외", "Decompensated cardiac failure와 같은 질환군. 푸로세미드는 "
                "심부전 울혈 관리의 표준 이뇨제다."),

    # ── 유지: 이름이 비슷할 뿐 다른 질환이다 ─────────────────────────
    ("fingolimod", "Multiple Sclerosis, Primary Progressive"): (
        "유지", "재발완화형(RRMS)과 일차진행형(PPMS)은 병태가 다르고 치료 반응도 "
                "다르다. 핀골리모드는 RRMS에 승인됐으나 PPMS 대상 INFORMS 3상은 "
                "1차 평가변수를 만족하지 못했다. 전형적인 진짜 TN이다."),
    ("warfarin", "Idiopathic Pulmonary Fibrosis"): (
        "유지", "폐색전증(승인)과 특발성 폐섬유증은 별개 질환이다. IPF 대상 "
                "ACE-IPF 시험은 사망률 증가로 조기 중단됐다."),
    ("methotrexate", "Leukemia, Myelomonocytic, Chronic"): (
        "유지", "만성 골수단핵구성 백혈병(CMML)은 급성 림프모구성 백혈병(ALL)과 "
                "계통이 다른 질환이다."),
    ("methotrexate", "Malignant tumor of small intestine"): (
        "유지", "건선(승인)과 소장 악성종양은 무관하다. 'small'이라는 흔한 토큰이 "
                "우연히 겹쳐 걸린 오탐이다."),
    # ── CT.gov "확인필요"로 빠진 건들. 자동 폐기하면 벤치마크가 편향된다 ──
    #    match.py는 '유지'만 남기므로, 판정을 안 적으면 조용히 사라진다.
    ("hydroxychloroquine", "COVID19 (disease)"): (
        "유지", "RECOVERY·WHO SOLIDARITY 모두 사망률 개선 없음. 명백한 효능 실패다. "
                "다만 실패 자체가 세계적 뉴스였으므로 사전학습 누출 위험 최상급 — "
                "폐쇄형 질의로 반드시 확인해야 한다."),
    ("azithromycin", "COVID19 (disease)"): (
        "유지", "RECOVERY·PRINCIPLE에서 효능 없음. 누출 위험 높음."),
    ("rivaroxaban", "COVID19 (disease)"): (
        "유지", "데이터모니터링위원회 권고로 중단. 누출 위험 중간."),
    ("oxycodone", "Degenerative polyarthritis"): (
        "제외", "옥시코돈의 승인 적응증은 '통증'이고 골관절염 통증도 그 범위에 든다. "
                "질환 치료가 아니라 증상 조절이므로 효능 가설의 반례가 아니다."),

    ("alprostadil", "Pulmonary Hypertension"): (
        "유지", "알프로스타딜의 승인 적응증은 선천성 심질환 신생아의 동맥관 개존 "
                "유지다. 폐고혈압 치료와는 목적이 다르다."),

    # ═══════════════════════════════════════════════════════════
    # 승인 교차 검증(bench.approval)이 표시한 14건에 대한 판정
    #
    #   RepoDB의 Approved 목록이 불완전해 실제 승인약이 TN에 섞였다.
    #   자동 표시는 선별 장치일 뿐이라 3건은 오탐이었다. 특히 베바시주맙은
    #   지우면 안 되는 것을 지울 뻔했다 — 아래 참조.
    # ═══════════════════════════════════════════════════════════

    # ── 제외: 실제로 승인·표준치료인데 RepoDB에 없었다 ──────────
    ("capecitabine", "Malignant neoplasm of breast"): (
        "제외", "젤로다는 1998년 전이성 유방암에 FDA 승인됐다. RepoDB Approved에 "
                "위암·대장암만 있어 필터를 통과했다."),
    ("cyclophosphamide", "Acute lymphoblastic leukemia - category"): (
        "제외", "사이톡산 라벨에 급성 림프모구성 백혈병이 명시돼 있다."),
    ("fulvestrant", "Malignant neoplasm of breast"): (
        "제외", "파슬로덱스는 2002년 HR 양성 전이성 유방암에 승인됐다. "
                "RepoDB에 이 약의 승인 적응증이 하나도 없다."),
    ("exenatide", "Diabetes Mellitus"): (
        "제외", "바이에타는 2005년 2형 당뇨에 승인됐다. RepoDB에 승인 기록 없음."),
    ("pregabalin", "Pain"): (
        "제외", "리리카는 신경병성 통증·대상포진후신경통·섬유근통에 승인됐다. "
                "적응증 'Pain'이 그 범위와 겹친다."),
    ("mycophenolate mofetil", "Lupus Nephritis"): (
        "제외", "루푸스 신염의 관해 유도·유지 표준요법이다(ACR·EULAR 권고). "
                "라벨 적응증이 이식 거부 예방이라 문자열 필터를 빠져나갔다."),
    ("hydroxycarbamide", "Polycythemia Vera"): (
        "제외", "고위험 진성적혈구증가증의 표준 세포감소 치료다."),
    ("colistin", "Pneumonia"): (
        "제외", "다제내성 그람음성균 폐렴에 쓰이는 승인 항생제다."),
    ("vinorelbine", "Malignant neoplasm of breast"): (
        "제외", "유럽에서 진행성 유방암에 승인돼 있다(미국 라벨은 비소세포폐암)."),
    ("paclitaxel", "Squamous cell carcinoma"): (
        "제외", "편평상피암은 부위가 특정되지 않은 광범위 표기다. 파클리탁셀은 "
                "비소세포폐암(편평상피 조직형 포함)에 승인돼 있어 반례로 쓸 수 없다."),
    ("fluorouracil", "Squamous cell carcinoma"): (
        "제외", "국소 5-FU가 광선각화증·표재성 기저세포암에 승인돼 있고 두경부 "
                "편평상피암 표준 병용요법의 구성 약제다."),

    # ── 유지: 자동 표시가 틀렸다 ─────────────────────────────────
    ("bevacizumab", "Malignant neoplasm of breast"): (
        "유지", "**이 벤치마크에서 가장 좋은 TN이다.** 아바스틴은 2008년 전이성 "
                "유방암에 신속승인됐으나 확증 시험이 효능을 입증하지 못해 FDA가 "
                "2011년 그 적응증을 철회했다. 자동 표시는 2008년 승인만 보고 "
                "제외하려 했는데, 철회 사유가 정확히 '효능 부족'이므로 "
                "반례로서 완벽하다. 자동 판정을 그대로 받았으면 지울 뻔했다."),
    ("etoposide", "Multiple Myeloma"): (
        "유지", "에토포시드의 승인 적응증은 고환암·소세포폐암이다. 다발성 골수종에서는 "
                "구제요법 병용의 일부로 쓰일 뿐 1차 표준이 아니다."),

    # ── 2차 교차 검증(51건 → 7건 표시)에 대한 판정 ────────────────
    ("dexamethasone phosphate", "Multiple Myeloma"): (
        "제외", "덱사메타손은 다발성 골수종 표준요법(VRd·DRd 등)의 필수 구성 약제다. "
                "ADJUNCT 차단 목록에 'dexamethasone'은 있었으나 염 형태인 "
                "'dexamethasone phosphate'가 없어 빠져나갔다. 목록에 염 형태를 추가했다."),
    ("cisplatin", "Human epidermal growth factor 2 positive carcinoma of breast"): (
        "유지", "시스플라틴의 승인 적응증은 고환암·난소암·방광암이다. HER2 양성 "
                "유방암 표준은 트라스투주맙 기반 요법이며 시스플라틴은 아니다."),
    ("enocitabine", "Acute lymphoblastic leukemia - category"): (
        "유지", "에노시타빈은 일본에서 **급성 골수성**백혈병에 승인된 시타라빈 유도체다. "
                "급성 림프모구성 백혈병은 다른 질환이다. 자동 표시의 'Sunpla 2007'은 "
                "근거를 확인할 수 없다."),
}


# ─────────────────────────────────────────────────────────────
# 검증 도구가 낸 환각 기록
#   자동 표시를 그대로 받으면 안 되는 이유의 실물이다.
# ─────────────────────────────────────────────────────────────
SCREEN_HALLUCINATIONS = [
    ("alprostadil", "Pulmonary Hypertension", "Flolan 1995",
     "Flolan은 **에포프로스테놀**의 제품명이다. 알프로스타딜이 아니다. "
     "둘 다 프로스타사이클린 계열이라 혼동한 것으로 보인다. "
     "에포프로스테놀은 폐동맥고혈압에 승인됐지만 알프로스타딜은 아니다."),
    ("fingolimod", "Multiple Sclerosis, Primary Progressive", "Gilenya 2010",
     "길레니아의 승인 적응증은 **재발형** 다발성경화증이다. 일차진행형이 아니다. "
     "아형 구분을 무시한 표시다."),
    ("bevacizumab", "Malignant neoplasm of breast", "Avastin 2008",
     "2008년 신속승인은 사실이나 **2011년 FDA가 효능 미입증으로 철회**했다. "
     "철회를 누락한 표시다."),
]


def apply(rows):
    """라벨 목록에 판정을 적용한다. (남은 행, 제외된 행)"""
    keep, drop = [], []
    for r in rows:
        d = DECISIONS.get((r.get("drug", "").strip().lower().replace("  ", " "),
                           r.get("indication", "").strip()))
        if d is None:
            # 키를 소문자 약물명으로 한 번 더 시도
            d = DECISIONS.get((r.get("drug", "").strip(), r.get("indication", "").strip()))
        if d and d[0] == "제외":
            r["review"] = d[1]
            drop.append(r)
        else:
            if d:
                r["review"] = d[1]
            keep.append(r)
    return keep, drop


def lookup(drug, indication):
    return DECISIONS.get((str(drug).strip().lower(), str(indication).strip()))
