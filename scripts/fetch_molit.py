"""Download the monthly 아파트 매매 실거래가 CSV from 국토교통부 실거래가공개시스템.

The site's '자료제공' form posts to /pt/xls/ptXlsCSVDown.do; the same endpoint answers
a plain GET, so one request per month gives the whole country for that month
(전국은 최대 1개월 범위만 허용된다). Files land in data/raw/molit/apt_YYYY-MM.csv.

Network note: this endpoint is not reachable from every network (it refused our
build sandbox). When a download fails the existing CSV is kept and the build keeps
using the last month it has, so a blocked network never empties the site.
"""
from __future__ import annotations

import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'raw', 'molit')
ENDPOINT = 'https://rt.molit.go.kr/pt/xls/ptXlsCSVDown.do'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')


def months_back(n=4, today=None):
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f'{y:04d}-{m:02d}')
    return list(reversed(out))


def month_range(ym):
    y, m = int(ym[:4]), int(ym[5:])
    last = [31, 29 if (y % 4 == 0 and y % 100 != 0) or y % 400 == 0 else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return f'{y:04d}-{m:02d}-01', f'{y:04d}-{m:02d}-{last:02d}'


def url_for(ym):
    start, end = month_range(ym)
    params = {
        'srhThingNo': 'A',       # 아파트
        'srhDelngSecd': '1',     # 매매
        'srhAddrGbn': '1',       # 지번주소
        'srhLfstsSecd': '1',
        'sidoNm': '전체', 'sggNm': '전체', 'emdNm': '전체', 'loadNm': '전체',
        'areaNm': '전체', 'hsmpNm': '전체', 'mobileAt': '',
        'srhFromDt': start, 'srhToDt': end,
        'srhNewRonSecd': '', 'srhSidoCd': '', 'srhSggCd': '', 'srhEmdCd': '',
        'srhRoadNm': '', 'srhLoadCd': '', 'srhHsmpCd': '', 'srhArea': '',
        'srhFromAmount': '', 'srhToAmount': '', 'srhLrArea': '',
    }
    return ENDPOINT + '?' + urllib.parse.urlencode(params)


def fetch(ym, retries=2):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url_for(ym), headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                blob = r.read()
            if len(blob) < 50_000 or b'NO' not in blob[:20000]:
                raise ValueError(f'looks empty ({len(blob)} bytes)')
            return blob
        except Exception as e:  # noqa: BLE001
            print(f'  {ym} attempt {attempt + 1} failed: {e}')
            time.sleep(3 + attempt * 5)
    return None


def main(argv=None):
    argv = argv or sys.argv[1:]
    n = 4
    if '--months' in argv:
        n = int(argv[argv.index('--months') + 1])
    os.makedirs(OUT, exist_ok=True)
    wanted = months_back(n)
    keep_fresh = set(wanted[-2:])  # 최신 2개월은 매번 새로 받고, 나머지는 있으면 건너뛴다
    ok = 0
    for ym in wanted:
        target = os.path.join(OUT, f'apt_{ym}.csv')
        if ym not in keep_fresh and os.path.exists(target):
            print(f'{ym}: cached, skip')
            ok += 1
            continue
        blob = fetch(ym)
        if blob is None:
            state = 'kept previous' if os.path.exists(target) else 'missing'
            print(f'{ym}: download failed, {state}')
            continue
        with open(target, 'wb') as f:
            f.write(blob)
        print(f'{ym}: {len(blob):,} bytes')
        ok += 1
        time.sleep(2)
    print(f'downloaded {ok}/{len(wanted)} months')
    if ok == 0 and not os.listdir(OUT):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
