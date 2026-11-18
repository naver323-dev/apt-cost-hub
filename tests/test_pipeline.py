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
        for r in self.d['regions'][:50]:
            if not r['fee_m2']:
                continue
            total = sum(v for v in r['items'].values() if v)
            self.assertAlmostEqual(total, r['fee_m2'], delta=max(1.0, r['fee_m2'] * 0.02))


if __name__ == '__main__':
    unittest.main()
