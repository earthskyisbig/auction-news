# -*- coding: utf-8 -*-
"""카테고리 분류 공용 모듈 — 검색어가 없는 수집 채널(RSS 구독·기관 보도자료)이 함께 쓴다.

검색 채널은 "어떤 키워드로 찾았는지"가 곧 카테고리다. 구독·게시판 채널은 그 정보가 없어
제목에서 직접 추론해야 한다. 두 채널이 서로 다른 규칙으로 분류하면 같은 글이 수집 경로에
따라 다른 카테고리로 들어가므로 규칙을 여기 한 곳에 둔다.

점수: keywords.json의 구(句) 적중 1점 + CAT_TOKENS 단일어 적중 2점.
keywords.json이 '재건축 안전진단'처럼 구 위주라 '재건축'만 있는 제목을 못 잡는다.
"""
import json, os

# 제목에 흔한 단일어 → 카테고리
CAT_TOKENS = {
    "redevelopment": ["재건축", "재개발", "정비사업", "정비구역", "정비계획", "조합", "신속통합", "모아타운",
                      "추정분담금", "관리처분", "사업시행인가", "조합원", "입주권", "리모델링", "노후계획도시",
                      "선도지구", "재정비촉진"],
    "auction": ["경매", "공매", "낙찰", "권리분석", "말소기준", "명도", "유치권", "경락"],
    "subscription": ["청약", "분양권", "특별공급", "청약통장", "무순위", "줍줍", "견본주택", "사전청약"],
    "policy": ["대책", "규제지역", "토지거래허가", "세제", "종부세", "양도세", "취득세", "DSR", "LTV",
               "대출규제", "임대차", "전매제한", "가계부채", "주담대", "보금자리론", "디딤돌"],
    "market": ["시황", "매매가", "전세가", "거래량", "시세", "실거래", "매물", "호가", "전세가율", "미분양"],
    "urban_plan": ["도시계획", "지구단위", "그린벨트", "역세권", "공공주택", "도시개발", "택지지구",
                   "개발제한구역", "공급대책", "주택공급"],
    "industrial": ["산업단지", "신도시", "반도체", "클러스터", "국가산단"],
}


def load_keyword_map(config=None, watchlist=None):
    """(카테고리, 키워드) 목록. 긴 키워드를 먼저 봐야 짧은 것이 긴 것을 가리지 않는다."""
    pairs = []
    if config and os.path.isfile(config):
        for cat, spec in json.load(open(config, encoding="utf-8"))["categories"].items():
            for kw in spec["keywords"]:
                pairs.append((cat, kw))
    if watchlist and os.path.isfile(watchlist):
        for kw in json.load(open(watchlist, encoding="utf-8")).get("keywords", []):
            pairs.append(("watch", kw))
    return sorted(pairs, key=lambda p: -len(p[1]))


def classify(hay, pairs, fallback="market"):
    """(카테고리, 적중 키워드). 동점이면 watch(관심 지역)가 이긴다.

    hay에는 제목·태그처럼 압축된 텍스트만 넣는다. 본문 전체를 넣으면 '아파트 분양' 같은
    구가 아무 글에나 걸린다.
    """
    score, matched = {}, []
    for cat, kw in pairs:
        toks = [t for t in kw.split() if len(t) >= 2]
        if toks and all(t in hay for t in toks):
            score[cat] = score.get(cat, 0) + 1
            matched.append(kw)
    for cat, toks in CAT_TOKENS.items():
        for t in toks:
            if t in hay:
                score[cat] = score.get(cat, 0) + 2
    if not score:
        return fallback, []
    best = max(score.items(), key=lambda kv: (kv[1], kv[0] == "watch"))[0]
    return best, sorted(set(matched))[:6]


def is_on_topic(hay, terms):
    """부동산 무관 글 제거용. terms 중 하나라도 걸리면 통과."""
    return any(t in hay for t in terms) if terms else True
