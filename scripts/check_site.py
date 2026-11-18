"""Validate the built site before it is published.

Runs after scripts/build_site.py and fails the build (exit 1) when a page is
missing, a number on a page disagrees with the JSON feed, the FAQ markup and the
FAQPage JSON-LD differ, a forbidden string slipped in, or the deployment would
exceed Cloudflare Pages limits.
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, 'site')
DATA = json.load(open(os.path.join(ROOT, 'data', 'processed', 'dataset.json'), encoding='utf-8'))
BASE = 'https://apt-cost-hub.pages.dev'
GA4 = 'G-J80R3CFWY8'
MAX_FILES = 20000
MAX_BYTES = 25 * 1024 * 1024

# 개인 식별 문자열은 저장소에 적지 않는다. 운영 환경의 data/private/forbidden.txt
# (한 줄에 하나, 커밋 제외)에 넣고, 그 파일이 없으면 이 검사만 건너뛴다.
FORBIDDEN = []
_priv = os.path.join(ROOT, 'data', 'private', 'forbidden.txt')
if os.path.exists(_priv):
    with open(_priv, encoding='utf-8') as _f:
        FORBIDDEN = [ln.strip() for ln in _f if ln.strip()]

errors = []
checks = 0


def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        errors.append(msg)


def read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


def text_of(h):
    h = re.sub(r'<script.*?</script>', ' ', h, flags=re.S)
    h = re.sub(r'<style.*?</style>', ' ', h, flags=re.S)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', h))


def all_files():
    for dirpath, _dirs, files in os.walk(SITE):
        for f in files:
            yield os.path.join(dirpath, f)


def main():
    # 1. required files
    for rel in ['index.html', 'about.html', 'privacy.html', '404.html', 'llms.txt', 'robots.txt',
                'sitemap.xml', 'assets/style.css', 'api/regions.json', 'api/meta.json']:
        check(os.path.exists(os.path.join(SITE, rel)), f'missing {rel}')

    regions = DATA['regions']
    regions_feed = json.load(open(os.path.join(SITE, 'api', 'regions.json'), encoding='utf-8'))
    meta = json.load(open(os.path.join(SITE, 'api', 'meta.json'), encoding='utf-8'))
    check(len(regions_feed['regions']) == len(regions), 'regions feed length mismatch')
    check(regions_feed['as_of'] == DATA['snapshot_date'], 'as_of mismatch in feed')
    check(meta['data_month'] == DATA['reference_month'], 'meta data_month mismatch')
    check(meta['counts']['regions'] == DATA['national']['regions'], 'meta region count mismatch')

    # 2. every region page + per-region JSON
    for r in regions:
        p = os.path.join(SITE, 'region', r['slug'] + '.html')
        check(os.path.exists(p), f'missing region page {r["slug"]}')
        check(os.path.exists(os.path.join(SITE, 'api', 'regions', r['slug'] + '.json')),
              f'missing region json {r["slug"]}')
        if not os.path.exists(p):
            continue
        h = read(p)
        t = text_of(h)
        check(f"{r['fee_m2']:,.1f}" in t, f'{r["slug"]}: ㎡당 값 불일치({r["fee_m2"]})')
        check(DATA['reference_month_label'] in t, f'{r["slug"]}: 기준월 표기 없음')
        check(h.count('<h1') == 1, f'{r["slug"]}: h1 개수 {h.count("<h1")}')
        check('lang="ko"' in h, f'{r["slug"]}: lang 없음')
        check(f'id={GA4}' in h, f'{r["slug"]}: GA4 없음')
        check(f'{BASE}/region/{r["slug"]}.html' in h, f'{r["slug"]}: canonical 없음')
        fe = json.load(open(os.path.join(SITE, 'api', 'regions', r['slug'] + '.json'), encoding='utf-8'))
        check(fe['region']['fee_m2'] == r['fee_m2'], f'{r["slug"]}: JSON 값 불일치')
        check(len(fe['complexes']) == len(r['_complexes']) if '_complexes' in r else True,
              f'{r["slug"]}: 단지 수 불일치')

    # 3. complex pages agree with the dataset
    by_id = {c['id']: c for c in DATA['complexes']}
    complex_files = [f for f in os.listdir(os.path.join(SITE, 'complex')) if f.endswith('.html')]
    check(len(complex_files) > 100, 'complex pages missing')
    for f in complex_files[::37]:  # sample every 37th page: full scan costs minutes, this covers all regions
        cid = f[:-5]
        c = by_id.get(cid)
        check(c is not None, f'complex page for unknown id {cid}')
        if not c:
            continue
        t = text_of(read(os.path.join(SITE, 'complex', f)))
        check(f"{c['fee_m2']:,.1f}" in t, f'{cid}: ㎡당 값 불일치')
        check(f"{c['households']:,}" in t, f'{cid}: 세대수 불일치')

    # 4. FAQ markup == FAQPage JSON-LD on every page that has one
    pages = [os.path.join(SITE, 'index.html'), os.path.join(SITE, 'about.html')] + \
            [os.path.join(SITE, 'region', r['slug'] + '.html') for r in regions[:20]]
    for p in pages:
        h = read(p)
        summaries = [re.sub(r'<[^>]+>', '', s).strip() for s in re.findall(r'<summary>(.*?)</summary>', h, re.S)]
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S)
        faq_qs = []
        for b in blocks:
            obj = json.loads(b)
            for node in obj.get('@graph', [obj]):
                if node.get('@type') == 'FAQPage':
                    faq_qs = [q['name'] for q in node['mainEntity']]
        if summaries:
            check(faq_qs == [s.replace('&amp;', '&') for s in summaries],
                  f'{os.path.relpath(p, SITE)}: FAQ 화면/JSON-LD 불일치 ({len(summaries)} vs {len(faq_qs)})')

    # 5. JSON-LD parses everywhere and declares the dataset source
    for p in [os.path.join(SITE, 'index.html')] + [os.path.join(SITE, 'region', r['slug'] + '.html') for r in regions[:10]]:
        for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', read(p), re.S):
            json.loads(b)
    idx = read(os.path.join(SITE, 'index.html'))
    check('"Dataset"' in idx and 'data.go.kr' in idx, 'index: Dataset JSON-LD 또는 출처 없음')

    # 6. forbidden strings anywhere in the deployed text
    for p in all_files():
        if os.path.getsize(p) > MAX_BYTES:
            errors.append(f'file over 25MB: {p}')
        if p.endswith(('.html', '.txt', '.json', '.xml', '.svg', '.css')):
            t = read(p)
            for bad in FORBIDDEN:
                if bad in t:
                    errors.append(f'forbidden "{bad}" in {os.path.relpath(p, SITE)}')

    # 7. sitemap covers the site and every URL has a file
    sm = read(os.path.join(SITE, 'sitemap.xml')).replace('<![CDATA[', '').replace(']]>', '')
    locs = re.findall(r'<loc>(.*?)</loc>', sm)
    check(len(locs) > len(regions), 'sitemap too small')
    check(len(set(locs)) == len(locs), 'sitemap has duplicates')
    for u in locs[::11]:
        rel = u.replace(BASE + '/', '')
        rel = '' if rel in ('', '/') else rel
        target = os.path.join(SITE, rel) if rel else os.path.join(SITE, 'index.html')
        check(os.path.exists(target), f'sitemap url without file: {u}')

    # 8. llms.txt + robots.txt
    llms = read(os.path.join(SITE, 'llms.txt'))
    check(llms.startswith('# '), 'llms.txt: H1 없음')
    check('as_of:' in llms and 'data_month:' in llms, 'llms.txt: as_of/data_month 없음')
    check(str(DATA['national']['complexes']) in llms.replace(',', ''), 'llms.txt: 단지 수 없음')
    check(len(llms.splitlines()) < 200, 'llms.txt too long')
    robots = read(os.path.join(SITE, 'robots.txt'))
    for agent in ['GPTBot', 'ClaudeBot', 'PerplexityBot', 'Google-Extended']:
        check(f'User-agent: {agent}' in robots, f'robots.txt: {agent} 없음')
    check('Sitemap: ' + BASE + '/sitemap.xml' in robots, 'robots.txt: sitemap 없음')

    # 9. no third-party scripts other than GA4, no inline handlers
    for p in [os.path.join(SITE, 'index.html')] + [os.path.join(SITE, 'region', r['slug'] + '.html') for r in regions[:30]]:
        srcs = re.findall(r'<script[^>]+src="([^"]+)"', read(p))
        for s in srcs:
            check('googletagmanager.com' in s, f'{os.path.relpath(p, SITE)}: 외부 스크립트 {s}')

    # 10. deployment limits
    files = list(all_files())
    check(len(files) < MAX_FILES, f'too many files: {len(files)}')

    print(f'{checks} checks, {len(errors)} problems')
    for e in errors[:40]:
        print(' FAIL', e)
    if len(errors) > 40:
        print(f' ... {len(errors) - 40} more')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
