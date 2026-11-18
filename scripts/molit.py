"""Parse the 국토교통부 실거래가공개시스템 CSV downloads into monthly aggregates.

The public 자료제공 CSV starts with a notice block and one header line; the data
columns are (지번주소 기준):

    NO, 시군구, 번지, 본번, 부번, 단지명, 전용면적(㎡), 계약년월, 계약일,
    거래금액(만원), 동, 층, 매수자, 매도자, 건축년도, 도로명, 해제사유발생일,
    거래유형, 중개사소재지, 등기일자

We keep 아파트 매매 only (the download is already filtered), drop 해제된 거래,
and aggregate per 시군구: 거래 건수, 중간 거래금액, 중간 평당가.

평당가(만원/평) = 거래금액(만원) ÷ 전용면적(㎡) × 3.305785
"""
from __future__ import annotations

import csv
import io
import os
import re
import statistics
from collections import defaultdict

PYEONG = 3.305785
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOLIT_DIR = os.path.join(ROOT, 'data', 'raw', 'molit')


def decode(blob: bytes) -> str:
    for enc in ('utf-8-sig', 'cp949', 'utf-8'):
        try:
            return blob.decode(enc)
        except UnicodeDecodeError:
            continue
    return blob.decode('cp949', 'replace')


def split_address(addr: str):
    """'경기도 성남시 분당구 정자동' -> ('경기도', '성남시 분당구')."""
    parts = addr.split()
    if not parts:
        return None, None
    sido = parts[0]
    if len(parts) == 1:
        return sido, ''
    first = parts[1]
    if first.endswith(('동', '읍', '면', '리', '가')):
        # 세종특별자치시처럼 시·군·구 없이 동부터 오는 주소
        return sido, ''
    if first.endswith('시') and len(parts) > 2 and parts[2].endswith('구'):
        return sido, f'{first} {parts[2]}'
    return sido, first


def read_rows(path):
    text = decode(open(path, 'rb').read())
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith('"NO"') or line.startswith('NO,'):
            start = i
            break
    if start is None:
        return []
    reader = csv.DictReader(io.StringIO('\n'.join(lines[start:])))
    out = []
    for row in reader:
        try:
            price = float((row.get('거래금액(만원)') or '').replace(',', '').strip())
            area = float((row.get('전용면적(㎡)') or '').replace(',', '').strip())
        except (TypeError, ValueError):
            continue
        if price <= 0 or area <= 0:
            continue
        released = (row.get('해제사유발생일') or '-').strip()
        if released not in ('-', ''):
            continue
        sido, sgg = split_address(row.get('시군구') or '')
        if not sido:
            continue
        out.append({
            'sido': sido, 'sgg': sgg,
            'name': (row.get('단지명') or '').strip(),
            'price': price, 'area': area,
            'per_pyeong': price / area * PYEONG,
            'ym': (row.get('계약년월') or '').strip(),
            'deal_type': (row.get('거래유형') or '').strip(),
        })
    return out


def month_files():
    if not os.path.isdir(MOLIT_DIR):
        return {}
    out = {}
    for f in sorted(os.listdir(MOLIT_DIR)):
        m = re.match(r'apt_(\d{4}-\d{2})\.csv$', f)
        if m:
            out[m.group(1)] = os.path.join(MOLIT_DIR, f)
    return out


def normalize_key(sido, sgg, region_keys):
    """MOLIT writes '성남시 분당구', K-apt merges it into '성남분당구'."""
    if (sido, sgg) in region_keys:
        return sido, sgg
    parts = sgg.split()
    if len(parts) == 2 and parts[0].endswith('시') and parts[1].endswith('구'):
        for cand in (parts[0] + parts[1], parts[0][:-1] + parts[1]):
            if (sido, cand) in region_keys:
                return sido, cand
    return None


def build(region_keys):
    """region_keys: set of (sido, sgg) that exist in the K-apt dataset."""
    months = month_files()
    if not months:
        return None
    by_month_all = defaultdict(list)
    by_region = defaultdict(lambda: defaultdict(list))
    by_complex = defaultdict(lambda: defaultdict(list))
    released_dropped = 0
    unmatched = 0
    total = 0
    for month, path in months.items():
        for r in read_rows(path):
            total += 1
            by_month_all[month].append(r)
            key = normalize_key(r['sido'], r['sgg'], region_keys)
            if key is None:
                unmatched += 1
                continue
            by_region[key][month].append(r)
            if r['name']:
                by_complex[(key[0], key[1], r['name'])][month].append(r)

    def stats(rows):
        prices = [x['price'] for x in rows]
        ppps = [x['per_pyeong'] for x in rows]
        return {
            'count': len(rows),
            'median_price': round(statistics.median(prices)),          # 만원
            'median_per_pyeong': round(statistics.median(ppps), 1),    # 만원/평
            'median_area': round(statistics.median([x['area'] for x in rows]), 1),
        }

    region_out = {}
    for key, months_map in by_region.items():
        region_out[key] = {m: stats(rows) for m, rows in months_map.items()}
    complex_out = {}
    for key, months_map in by_complex.items():
        complex_out[key] = {m: stats(rows) for m, rows in months_map.items()}
    national = {m: stats(rows) for m, rows in by_month_all.items()}
    return {
        'months': sorted(months),
        'national': national,
        'regions': region_out,
        'complexes': complex_out,
        'rows': total,
        'rows_without_kapt_region': unmatched,
    }
