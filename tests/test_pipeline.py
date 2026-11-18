"""Unit tests for the data/format helpers and a fixture run of the data build.

Run: python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import build_data  # noqa: E402
import calc  # noqa: E402
import molit  # noqa: E402


class SlugTest(unittest.TestCase):
    def test_sido_prefix(self):
        self.assertEqual(calc.slugify('대구광역시', '수성구'), 'daegu-suseonggu')
        self.assertEqual(calc.slugify('경기도', '성남분당구'), 'gyeonggi-seongnambundanggu')

    def test_merged_city_district_is_unique(self):
        a = calc.slugify('경기도', '수원영통구')
        b = calc.slugify('경기도', '수원팔달구')
        self.assertNotEqual(a, b)

    def test_ascii_only(self):
        for sido, sgg in [('서울특별시', '강남구'), ('세종특별자치시', ''), ('제주특별자치도', '서귀포시')]:
            slug = calc.slugify(sido, sgg)
            self.assertTrue(slug.isascii(), slug)
            self.assertRegex(slug, r'^[a-z0-9-]+$')


class FormatTest(unittest.TestCase):
    def test_price(self):
        self.assertEqual(calc.fmt_price(36800), '3억 6,800만원')
        self.assertEqual(calc.fmt_price(48000), '4억 8,000만원')
        self.assertEqual(calc.fmt_price(9000), '9,000만원')
        self.assertEqual(calc.fmt_price(12000), '1억 2,000만원')

    def test_dec_none(self):
        self.assertEqual(calc.fmt_dec(None), '—')
        self.assertEqual(calc.fmt_int(None), '—')


class ReferenceMonthTest(unittest.TestCase):
    def test_skips_a_month_that_just_opened(self):
        months = {'2026-07': 21500, '2026-08': 21448, '2026-09': 18812, '2026-10': 818}
        month, prev, provisional = build_data.pick_reference_month(months)
        self.assertEqual(month, '2026-09')
        self.assertEqual(prev, '2026-08')
        self.assertTrue(provisional)  # 18,812 < 21,448 * 0.95

    def test_full_month_is_not_provisional(self):
        months = {'2026-07': 21500, '2026-08': 21448}
        month, prev, provisional = build_data.pick_reference_month(months)
        self.assertEqual(month, '2026-08')
        self.assertFalse(provisional)


class AddressTest(unittest.TestCase):
    def test_split_seoul(self):
        self.assertEqual(molit.split_address('서울특별시 서초구 서초동'), ('서울특별시', '서초구'))

    def test_split_merged_city(self):
        self.assertEqual(molit.split_address('경기도 성남시 분당구 정자동'), ('경기도', '성남시 분당구'))

    def test_split_county(self):
        self.assertEqual(molit.split_address('전남광주통합특별시 화순군 화순읍 교리'),
                         ('전남광주통합특별시', '화순군'))

    def test_normalize_merged_name(self):
        keys = {('경기도', '성남분당구')}
        self.assertEqual(molit.normalize_key('경기도', '성남시 분당구', keys), ('경기도', '성남분당구'))
        self.assertIsNone(molit.normalize_key('경기도', '없는시 없는구', keys))


class QualityGuardTest(unittest.TestCase):
    def test_area_per_household_bounds(self):
        # 97,712,016㎡ / 156세대 = 626,359㎡/세대 -> 원자료 오류
        area, households = 97712016.0, 156
        self.assertFalse(10 <= area / households <= 400)
        self.assertTrue(10 <= 43298.2 / 414 <= 400)


class LastChargeColumnTest(unittest.TestCase):
    """P0-1 회귀: 장기수선충당금은 45열(‘장충금 월부과액’)이다. 44열은 ‘기타’."""

    def test_constants_point_at_lastcharge_column(self):
        self.assertEqual(build_data.C_LASTCHARGE, 45)
        self.assertEqual(build_data.C_LASTUSE, 46)
        self.assertEqual(build_data.C_LASTACCR, 47)
        self.assertEqual(build_data.C_LAST_RATE, 48)
        self.assertEqual(build_data.C_MISC_INCOME, 49)

    def test_header_matches_constants(self):
        path = os.path.join(ROOT, 'data', 'raw', 'kapt_fee.xlsx')
        if not os.path.exists(path):
            self.skipTest('kapt_fee.xlsx 없음')
        from xlsx_stream import rows
        it = rows(path)
        next(it)
        header = next(it)
        self.assertEqual(header[44], '기타')
        self.assertEqual(header[build_data.C_LASTCHARGE], '장충금 월부과액')
        self.assertEqual(header[build_data.C_MISC_INCOME], '잡수입 월수입금액')

    def test_fee_hh_includes_last_charge(self):
        path = os.path.join(ROOT, 'data', 'processed', 'dataset.json')
        if not os.path.exists(path):
            self.skipTest('dataset.json 없음')
        import json
        d = json.load(open(path, encoding='utf-8'))
        sampled = [c for c in d['complexes'] if c['last_charge'] > 0 and c['households'] > 0][:50]
        self.assertTrue(sampled, '장기수선충당금이 반영된 단지가 없음')
        for c in sampled:
            expect = (c['common_fee'] + c['indiv_fee'] + c['last_charge']) / c['households']
            self.assertAlmostEqual(c['fee_hh'], expect, delta=1.5, msg=c['id'])
        # 전국 세대당 총관리비가 장충금을 빼고 계산되었던 값(약 199,564원)보다 커야 한다
        counted = [c for c in d['complexes'] if c['fee_m2'] is not None]
        hh = sum(c['households'] for c in counted)
        total = sum(c['total_fee'] for c in counted)
        self.assertGreater(total / hh, 210000)


class DatasetInvariantTest(unittest.TestCase):
    """dataset.json이 있으면 페이지가 쓰는 값이 서로 맞는지 확인한다."""

    @classmethod
    def setUpClass(cls):
        import json
        path = os.path.join(ROOT, 'data', 'processed', 'dataset.json')
        if not os.path.exists(path):
            raise unittest.SkipTest('dataset.json 없음 (build_data.py 먼저 실행)')
        cls.d = json.load(open(path, encoding='utf-8'))

    def test_national_matches_complex_sum(self):
        cs = [c for c in self.d['complexes'] if c['fee_m2'] is not None]
        area = sum(c['billing_area'] for c in cs)
        common = sum(c['common_fee'] for c in cs)
        self.assertAlmostEqual(self.d['national']['fee_m2'], common / area, delta=0.2)

    def test_region_fee_between_complex_values(self):
        by_region = {}
        for c in self.d['complexes']:
            if c['fee_m2'] is not None:
                by_region.setdefault((c['sido'], c['sgg']), []).append(c['fee_m2'])
        for r in self.d['regions']:
            vals = by_region.get((r['sido'], r['sgg']), [])
            if not vals:
                self.assertIsNone(r['fee_m2'])
                continue
            self.assertGreaterEqual(r['fee_m2'], min(vals) - 0.1)
            self.assertLessEqual(r['fee_m2'], max(vals) + 0.1)

    def test_trade_counts_positive(self):
        trade = self.d.get('trade') or {}
        for r in self.d['regions']:
            for month, t in (r.get('trade') or {}).items():
                self.assertGreater(t['count'], 0, f'{r["sgg"]} {month}')
                self.assertGreater(t['median_price'], 0)
                self.assertGreater(t['median_per_pyeong'], 0)

    def test_item_sum_matches_common_fee(self):
        """P1-1 회귀: 항목 합 + 미분류 = 공용관리비(이중합산으로 합이 커지면 안 된다)."""
        for r in self.d['regions']:
            if not r['fee_m2']:
                continue
            total = sum(v for v in r['items'].values() if v) + max(r.get('unclassified_m2') or 0, 0)
            self.assertAlmostEqual(total, r['fee_m2'], delta=max(1.0, r['fee_m2'] * 0.02),
                                   msg=f"{r['sido']} {r['sgg']}")

    def test_no_item_double_count_region_wide(self):
        # 안전점검비·재해예방비를 수선유지비에 또 더했을 때는 항목 합이 합계를 1% 이상 넘는 지역이 있었다.
        over = [r['sgg'] for r in self.d['regions']
                if r['fee_m2'] and sum(v for v in r['items'].values() if v) > r['fee_m2'] * 1.01]
        self.assertEqual(over, [])

    def test_quality_guards_exclude_structural_errors(self):
        ids = {c['id'] for c in self.d['complexes']}
        self.assertIn('A10021851', ids)
        c = next(x for x in self.d['complexes'] if x['id'] == 'A10021851')
        # 수성풀비체: 부과면적 < 전용면적 -> ㎡당 지표 제외
        self.assertIsNone(c['fee_m2'])
        self.assertIn(c['quality'], ('struct_suspect', 'area_suspect'))
        for c in self.d['complexes']:
            if c['quality'] == 'ok':
                self.assertTrue(10 <= c['billing_area'] / c['households'] <= 400)
                self.assertLessEqual(c['exclusive_area'], c['billing_area'] * 1.05 + 1)
                self.assertGreaterEqual(c['common_fee'] / c['households'], 5000)

    def test_series_stops_at_reference_month(self):
        ref = self.d['reference_month']
        for c in self.d['complexes'][:2000]:
            for m in (c.get('series') or {}):
                self.assertLessEqual(m, ref, f'{c["id"]} 시계열에 잠정월 {m} 혼입')


if __name__ == '__main__':
    unittest.main()
