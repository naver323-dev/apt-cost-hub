"""Build the region / complex dataset from the K-apt weekly snapshots.

Inputs
  data/raw/kapt_fee.xlsx     K-apt 관리비공개의무단지 관리비정보 (주 1회)
  data/raw/kapt_area.xlsx    K-apt 관리비공개의무단지 면적정보 (주 1회)

Output
  data/processed/dataset.json   everything the site build needs
  data/processed/build.log      what happened (kept for the weekly log)

Every number here is either read from the snapshot or a documented arithmetic
combination of two read values (fee / area). Nothing is estimated.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from xlsx_stream import rows  # noqa: E402
from calc import slugify  # noqa: E402
import molit  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, 'data', 'raw')
COMMITTED = os.path.join(ROOT, 'data', 'committed')
TRADE_CACHE = os.path.join(COMMITTED, 'trade_cache.json')
KAPT_CACHE = os.path.join(COMMITTED, 'kapt_cache.json.gz')
OUT = os.path.join(ROOT, 'data', 'processed')

FEE_FILE = os.path.join(RAW, 'kapt_fee.xlsx')
AREA_FILE = os.path.join(RAW, 'kapt_area.xlsx')

# K-apt 관리비정보 column indexes (0-based, after the notice row + header row)
C_SIDO, C_SGG, C_EUP, C_DONG, C_CODE, C_NAME, C_MONTH = 0, 1, 2, 3, 4, 5, 6
C_COMMON, C_GENERAL, C_LABOR, C_OFFICE, C_TAX, C_CLOTH, C_EDU, C_CAR, C_OTHER = 7, 8, 9, 10, 11, 12, 13, 14, 15
C_CLEAN, C_GUARD, C_DISINF, C_ELEV, C_NET, C_REPAIR, C_REPAIR_PURE, C_FACILITY, C_SAFETY, C_DISASTER, C_OUTSRC = 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26
C_INDIV, C_LASTCHARGE, C_LASTUSE, C_LASTACCR, C_LAST_RATE, C_MISC_INCOME = 27, 44, 45, 46, 47, 48

# 공용관리비 합계를 이루는 세부 항목(일반관리비는 인건비·제사무비 등의 소계이므로 넣지 않음)
FEE_ITEMS = [
    ('labor', '인건비', C_LABOR),
    ('office', '제사무비', C_OFFICE),
    ('tax', '제세공과금', C_TAX),
    ('cloth', '피복비', C_CLOTH),
    ('edu', '교육훈련비', C_EDU),
    ('car', '차량유지비', C_CAR),
    ('other', '그 밖의 부대비용', C_OTHER),
    ('clean', '청소비', C_CLEAN),
    ('guard', '경비비', C_GUARD),
    ('disinfection', '소독비', C_DISINF),
    ('elevator', '승강기유지비', C_ELEV),
    ('network', '지능형네트워크유지비', C_NET),
    ('repair', '수선유지비', C_REPAIR),
    ('safety', '안전점검비', C_SAFETY),
    ('disaster', '재해예방비', C_DISASTER),
    ('outsourced', '위탁관리수수료', C_OUTSRC),
]


def num(v):
    if v is None:
        return 0.0
    try:
        return float(str(v).replace(',', ''))
    except ValueError:
        return 0.0


def load_areas():
    """단지코드 -> {households, billing_area, exclusive_area, dongs, name...}"""
    out = {}
    for i, r in enumerate(rows(AREA_FILE)):
        if i < 2 or len(r) < 11:
            continue
        code = r[4]
        if not code:
            continue
        rec = out.get(code)
        if rec is None:
            rec = out[code] = {
                'code': code, 'sido': r[0], 'sgg': r[1], 'eup': r[2], 'dong': r[3],
                'name': r[5], 'dongs': 0, 'billing_area': 0.0,
                'exclusive_area': 0.0, 'households': 0,
            }
        rec['dongs'] = int(num(r[6])) or rec['dongs']
        rec['billing_area'] = num(r[7]) or rec['billing_area']
        rec['exclusive_area'] = num(r[8]) or rec['exclusive_area']
        rec['households'] += int(num(r[10])) if num(r[10]) else 0
    return out


def load_fees():
    """단지코드 -> 월 -> fee record (last row wins; the file has one row per 단지·월)."""
    out = defaultdict(dict)
    months = defaultdict(int)
    for i, r in enumerate(rows(FEE_FILE)):
        if i < 2 or len(r) < 49:
            continue
        code = r[C_CODE]
        month = r[C_MONTH]
        if not code or len(month) != 6:
            continue
        rec = {
            'common': num(r[C_COMMON]),
            'general': num(r[C_GENERAL]),
            'indiv': num(r[C_INDIV]),
            'lastcharge': num(r[C_LASTCHARGE]),
            'lastaccr': num(r[C_LASTACCR]),
            'last_rate': num(r[C_LAST_RATE]),
            'misc_income': num(r[C_MISC_INCOME]),
        }
        for key, _label, idx in FEE_ITEMS:
            rec[key] = num(r[idx]) if idx < len(r) else 0.0
        out[code][month] = rec
        months[month] += 1
    return out, months


def pick_reference_month(months):
    """참조월 = 공개가 끝난 최신월.

    A month that only a handful of 단지 have filed for yet (the newest month in a
    weekly snapshot) is not a reference month: it would show a region's 관리비
    from a fraction of its complexes. Months below half of the peak count are
    dropped, the newest remaining month is the reference, and it is flagged
    잠정 when its count still trails the month before it.
    """
    peak = max(months.values())
    usable = sorted(m for m, n in months.items() if n >= peak * 0.5)
    latest = usable[-1]
    prev = usable[-2] if len(usable) > 1 else None
    provisional = bool(prev and months[latest] < months[prev] * 0.95)
    return latest, prev, provisional


def fmt_month(m):
    return f'{m[:4]}-{m[4:]}'


def snapshot_date():
    """Extraction date K-apt prints in the weekly file name or notice row."""
    meta = os.path.join(RAW, 'kapt_meta.json')
    if os.path.exists(meta):
        with open(meta, encoding='utf-8') as f:
            return json.load(f)['snapshot_date']
    return 'unknown'


def build():
    areas = load_areas()
    fees, months = load_fees()
    month, prev_month, provisional = pick_reference_month(months)

    complexes = []
    for code, area in areas.items():
        fmap = fees.get(code) or {}
        cur = fmap.get(month)
        if not cur:
            continue  # no public figure for the reference month -> not in the dataset
        billing = area['billing_area']
        households = area['households']
        if billing <= 0 and households <= 0:
            continue
        # 원자료 품질 가드: 관리비부과면적/세대수가 10㎡ 미만이거나 400㎡를 넘으면
        # 면적 입력 오류로 보고 ㎡당 지표에서 제외한다(단지 자체는 목록에 남김).
        area_per_hh = (billing / households) if households else None
        area_suspect = area_per_hh is not None and not (10 <= area_per_hh <= 400)
        usable = (not area_suspect) and billing > 0 and cur['common'] > 0
        rec = {
            'id': code,
            'name': area['name'],
            'sido': area['sido'],
            'sgg': area['sgg'],
            'dong': area['eup'] or area['dong'],
            'households': households,
            'dongs': area['dongs'],
            'billing_area': round(billing, 1),
            'exclusive_area': round(area['exclusive_area'], 1),
            'common_fee': round(cur['common']),
            'general_fee': round(cur['general']),
            'indiv_fee': round(cur['indiv']),
            'last_charge': round(cur['lastcharge']),
            'total_fee': round(cur['common'] + cur['indiv'] + cur['lastcharge']),
            'items': {k: round(cur[k]) for k, _l, _i in FEE_ITEMS},
            'months': len(fmap),
        }
        if usable:
            rec['fee_m2'] = round(cur['common'] / billing, 1)
            rec['total_m2'] = round((cur['common'] + cur['indiv'] + cur['lastcharge']) / billing, 1)
        else:
            rec['fee_m2'] = None
            rec['total_m2'] = None
        rec['quality'] = ('ok' if usable else
                          ('area_suspect' if area_suspect else 'no_fee'))
        if households > 0:
            rec['fee_hh'] = round((cur['common'] + cur['indiv'] + cur['lastcharge']) / households)
        else:
            rec['fee_hh'] = None
        prev = fmap.get(prev_month) if prev_month else None
        if usable and prev and prev['common'] > 0:
            rec['prev_fee_m2'] = round(prev['common'] / billing, 1)
            rec['mom_pct'] = round((rec['fee_m2'] - rec['prev_fee_m2']) / rec['prev_fee_m2'] * 100, 1) if rec['prev_fee_m2'] else None
        else:
            rec['prev_fee_m2'] = None
            rec['mom_pct'] = None

        # monthly 시계열 for the last 12 public months (area-weighted ㎡당 공용관리비)
        if usable:
            series = {}
            for m in sorted(fmap)[-12:]:
                series[fmt_month(m)] = round(fmap[m]['common'] / billing, 1)
            rec['series'] = series
        complexes.append(rec)

    # ---- region aggregation ------------------------------------------------
    by_region = defaultdict(list)
    for c in complexes:
        by_region[(c['sido'], c['sgg'])].append(c)

    regions = []
    for (sido, sgg), cs in by_region.items():
        counted = [c for c in cs if c['fee_m2'] is not None]
        area_sum = sum(c['billing_area'] for c in counted)
        common_sum = sum(c['common_fee'] for c in counted)
        total_sum = sum(c['total_fee'] for c in counted)
        hh_sum = sum(c['households'] for c in counted)
        fees_sorted = sorted(c['fee_m2'] for c in counted)
        med = fees_sorted[len(fees_sorted) // 2] if fees_sorted else None
        items = {}
        for key, _label, _idx in FEE_ITEMS:
            s = sum(c['items'][key] for c in counted)
            items[key] = round(s / area_sum, 1) if area_sum else None
        prev_area = 0.0
        prev_common = 0.0
        for c in counted:
            if c.get('prev_fee_m2') is not None:
                prev_area += c['billing_area']
                prev_common += c['prev_fee_m2'] * c['billing_area']
        regions.append({
            'slug': slugify(sido, sgg),
            'sido': sido, 'sgg': sgg,
            'complexes': len(cs),
            'counted': len(counted),
            'households': hh_sum,
            'billing_area': round(area_sum),
            'fee_m2': round(common_sum / area_sum, 1) if area_sum else None,
            'total_m2': round(total_sum / area_sum, 1) if area_sum else None,
            'fee_hh': round(total_sum / hh_sum) if hh_sum else None,
            'median_fee_m2': med,
            'mom_pct': round((common_sum / area_sum - prev_common / prev_area) / (prev_common / prev_area) * 100, 1) if prev_area and prev_common else None,
            'items': items,
        })
    regions.sort(key=lambda r: -(r['households'] or 0))

    total_area = sum(r['billing_area'] for r in regions)
    total_common = sum(r['fee_m2'] * r['billing_area'] for r in regions if r['fee_m2'])
    national = {
        'sido': '전국', 'sgg': '',
        'complexes': len(complexes),
        'households': sum(r['households'] for r in regions),
        'billing_area': total_area,
        'fee_m2': round(total_common / total_area, 1) if total_area else None,
        'regions': len(regions),
    }

    quality = {
        'area_suspect': sum(1 for c in complexes if c['quality'] == 'area_suspect'),
        'no_fee': sum(1 for c in complexes if c['quality'] == 'no_fee'),
    }
    quality = {
        'area_suspect': sum(1 for c in complexes if c['quality'] == 'area_suspect'),
        'no_fee': sum(1 for c in complexes if c['quality'] == 'no_fee'),
    }
    # ---- 실거래가 (국토교통부 실거래가공개시스템 자료제공 CSV) -----------------
    region_keys = {(r['sido'], r['sgg']) for r in regions}
    trade = molit.build(region_keys)
    stale = False
    if trade is None and os.path.exists(TRADE_CACHE):
        # 실거래 CSV를 못 받은 실행(네트워크 차단 등)에서는 마지막으로 받은 집계를 그대로 쓴다.
        with open(TRADE_CACHE, encoding='utf-8') as f:
            trade = json.load(f)
        stale = True
    elif trade is not None:
        os.makedirs(COMMITTED, exist_ok=True)
        cache = {'months': trade['months'], 'national': trade['national'],
                 'regions': {f'{k[0]}|{k[1]}': v for k, v in trade['regions'].items()},
                 'rows': trade['rows'], 'rows_unmatched': trade['rows_without_kapt_region'],
                 'collected_at': snapshot_date()}
        with open(TRADE_CACHE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, separators=(',', ':'))
    if trade and stale:
        trade = {'months': trade['months'], 'national': trade['national'],
                 'regions': {tuple(k.split('|')): v for k, v in trade['regions'].items()},
                 'rows': trade['rows'], 'rows_without_kapt_region': trade['rows_unmatched']}
    trade_summary = None
    if trade:
        tmonths = trade['months']
        tref = tmonths[-1]
        trade_summary = {
            'months': tmonths,
            'reference_month': tref,
            'reference_month_label': f'{tref[:4]}년 {int(tref[5:])}월',
            'national': trade['national'],
            'rows': trade['rows'],
            'rows_unmatched': trade['rows_without_kapt_region'],
            'stale': stale,
        }
        for r in regions:
            r['trade'] = trade['regions'].get((r['sido'], r['sgg']), {})

    dataset = {
        'snapshot_date': snapshot_date(),
        'trade': trade_summary,
        'quality': quality,
        'reference_month': fmt_month(month),
        'reference_month_label': f'{month[:4]}년 {int(month[4:])}월',
        'previous_month': fmt_month(prev_month) if prev_month else None,
        'provisional': provisional,
        'month_coverage': {fmt_month(m): n for m, n in sorted(months.items())},
        'national': national,
        'regions': regions,
        'complexes': complexes,
    }
    return dataset


def load_kapt_cache():
    with gzip.open(KAPT_CACHE, 'rt', encoding='utf-8') as f:
        return json.load(f)


def save_kapt_cache(d):
    os.makedirs(COMMITTED, exist_ok=True)
    payload = {k: v for k, v in d.items() if k not in ('trade', 'quality')}
    with gzip.open(KAPT_CACHE, 'wt', encoding='utf-8', compresslevel=9) as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))


def attach_trade(d):
    """실거래 집계를 붙인다. CSV가 없으면 커밋된 캐시로 대체한다."""
    regions = d['regions']
    region_keys = {(r['sido'], r['sgg']) for r in regions}
    trade = molit.build(region_keys)
    stale = False
    if trade is None and os.path.exists(TRADE_CACHE):
        with open(TRADE_CACHE, encoding='utf-8') as f:
            cached = json.load(f)
        trade = {'months': cached['months'], 'national': cached['national'],
                 'regions': {tuple(k.split('|')): v for k, v in cached['regions'].items()},
                 'rows': cached['rows'], 'rows_without_kapt_region': cached['rows_unmatched']}
        stale = True
    elif trade is not None:
        os.makedirs(COMMITTED, exist_ok=True)
        cache = {'months': trade['months'], 'national': trade['national'],
                 'regions': {f'{k[0]}|{k[1]}': v for k, v in trade['regions'].items()},
                 'rows': trade['rows'], 'rows_unmatched': trade['rows_without_kapt_region'],
                 'collected_at': snapshot_date()}
        with open(TRADE_CACHE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, separators=(',', ':'))
    d['trade'] = None
    if not trade:
        return d
    tmonths = trade['months']
    tref = tmonths[-1]
    d['trade'] = {
        'months': tmonths,
        'reference_month': tref,
        'reference_month_label': f'{tref[:4]}년 {int(tref[5:])}월',
        'national': trade['national'],
        'rows': trade['rows'],
        'rows_unmatched': trade['rows_without_kapt_region'],
        'stale': stale,
    }
    for r in regions:
        r['trade'] = trade['regions'].get((r['sido'], r['sgg']), {})
    return d


def main():
    os.makedirs(OUT, exist_ok=True)
    have_kapt = os.path.exists(FEE_FILE) and os.path.exists(AREA_FILE)
    if have_kapt:
        d = build()
        save_kapt_cache(d)
        d['kapt_stale'] = False
    elif os.path.exists(KAPT_CACHE):
        # K-apt 접속이 막힌 실행(GitHub Actions 등)에서는 마지막 정상 빌드를 쓴다.
        d = load_kapt_cache()
        d['kapt_stale'] = True
        print('K-apt 원본이 없어 커밋된 관리비 스냅샷을 사용합니다:', d.get('snapshot_date'))
    else:
        raise SystemExit('K-apt 원본도 캐시도 없음')
    d = attach_trade(d)
    with open(os.path.join(OUT, 'dataset.json'), 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, separators=(',', ':'))
    n = d['national']
    print(f"reference {d['reference_month']} provisional={d['provisional']} kapt_stale={d['kapt_stale']} "
          f"complexes={n['complexes']} regions={n['regions']} ㎡당={n['fee_m2']}")
    t = d.get('trade') or {}
    print(f"trade {t.get('reference_month')} rows={t.get('rows')} stale={t.get('stale')}")
    print('dataset.json', round(os.path.getsize(os.path.join(OUT, 'dataset.json')) / 1e6, 2), 'MB')


if __name__ == '__main__':
    main()
