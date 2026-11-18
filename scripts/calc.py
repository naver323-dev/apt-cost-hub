"""Formatting, ranking and slug helpers shared by the data and site builds."""
from __future__ import annotations

CHO = ['g', 'kk', 'n', 'd', 'tt', 'r', 'm', 'b', 'pp', 's', 'ss', '', 'j', 'jj', 'ch', 'k', 't', 'p', 'h']
JUNG = ['a', 'ae', 'ya', 'yae', 'eo', 'e', 'yeo', 'ye', 'o', 'wa', 'wae', 'oe', 'yo', 'u', 'wo', 'we', 'wi', 'yu',
        'eu', 'ui', 'i']
JONG = ['', 'k', 'k', 'ks', 'n', 'nj', 'nh', 't', 'l', 'lk', 'lm', 'lb', 'ls', 'lt', 'lp', 'lh', 'm', 'p', 'ps', 't',
        't', 'ng', 't', 't', 'k', 't', 'p', 'h']

SIDO_SLUG = {
    '서울특별시': 'seoul', '부산광역시': 'busan', '대구광역시': 'daegu', '인천광역시': 'incheon',
    '대전광역시': 'daejeon', '울산광역시': 'ulsan', '세종특별자치시': 'sejong', '경기도': 'gyeonggi',
    '강원특별자치도': 'gangwon', '충청북도': 'chungbuk', '충청남도': 'chungnam',
    '전북특별자치도': 'jeonbuk', '전라북도': 'jeonbuk', '전남광주통합특별시': 'jeonnamgwangju',
    '전라남도': 'jeonnam', '광주광역시': 'gwangju', '경상북도': 'gyeongbuk', '경상남도': 'gyeongnam',
    '제주특별자치도': 'jeju', '제주도': 'jeju',
}


def romanize(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            idx = code - 0xAC00
            out.append(CHO[idx // 588] + JUNG[(idx % 588) // 28] + JONG[idx % 28])
        elif ch.isalnum():
            out.append(ch.lower())
    return ''.join(out)


def slugify(sido: str, sgg: str) -> str:
    prefix = SIDO_SLUG.get(sido)
    if prefix is None:
        prefix = romanize(sido) or 'region'
    body = romanize(sgg) or 'area'
    return f'{prefix}-{body}'


def fmt_int(v):
    if v is None:
        return '—'
    return f'{int(round(v)):,}'


def fmt_dec(v, digits=1):
    if v is None:
        return '—'
    return f'{v:,.{digits}f}'


def won(v):
    return f'{fmt_int(v)}원'


def rank_list(regions, min_complexes=30, ascending=True):
    rows = [r for r in regions if r.get('counted', 0) >= min_complexes and r.get('fee_m2') is not None]
    rows.sort(key=lambda r: r['fee_m2'] if ascending else -r['fee_m2'])
    return rows


def region_rank(regions, slug, min_complexes=30):
    rows = rank_list(regions, min_complexes, ascending=True)
    for i, r in enumerate(rows, 1):
        if r.get('slug') == slug:
            return i, len(rows)
    return None, len(rows)


def fmt_price(manwon):
    """36,800 (만원) -> '3억 6,800만원'."""
    if manwon is None:
        return '—'
    v = int(round(manwon))
    eok, rest = divmod(v, 10000)
    if eok and rest:
        return f'{eok}억 {rest:,}만원'
    if eok:
        return f'{eok}억원'
    return f'{rest:,}만원'


def trade_of(region, month):
    t = (region.get('trade') or {}).get(month)
    return t or None
