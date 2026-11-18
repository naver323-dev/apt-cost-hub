"""Render the static site, JSON feeds, llms.txt and sitemap from dataset.json.

Everything on the page comes from data/processed/dataset.json, which is built from
the K-apt weekly snapshots by scripts/build_data.py. Numbers are never typed in by
hand and no value is estimated.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'processed', 'dataset.json')
SITE = os.path.join(ROOT, 'site')
CALC = os.path.join(ROOT, 'scripts', 'calc.py')

SITE_NAME = '아파트 관리비 인사이트'
BASE = 'https://apt-cost-hub.pages.dev'
GA4_ID = 'G-J80R3CFWY8'
SNAPSHOT_NOTE = 'K-apt(공동주택관리정보시스템) 자료실 주 1회 공개 자료'

sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from calc import region_rank, rank_list, fmt_int, fmt_dec, won, fmt_price  # noqa: E402


def esc(s):
    return html.escape(str(s), quote=True)


def load():
    with open(DATA, encoding='utf-8') as f:
        return json.load(f)


# ---------------------------------------------------------------- layout ----
def head(title, desc, canonical, extra_ld=None, og_type='website'):
    ld = ''
    if extra_ld:
        ld = ('<script type="application/ld+json">\n'
              + json.dumps(extra_ld, ensure_ascii=False, indent=1)
              + '\n</script>\n')
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="robots" content="index,follow,max-image-preview:large">
<link rel="canonical" href="{canonical}">
<link rel="alternate" type="text/plain" title="llms.txt" href="/llms.txt">
<link rel="alternate" type="application/json" title="API" href="/api/regions.json">
<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{canonical}">
<meta property="og:locale" content="ko_KR">
<meta name="twitter:card" content="summary">
<meta name="theme-color" content="#0f172a">
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/assets/style.css?v=1">
<script async src="https://www.googletagmanager.com/gtag/js?id={GA4_ID}"></script>
<script>
window.dataLayer = window.dataLayer || [];
function gtag(){{dataLayer.push(arguments);}}
gtag('js', new Date());
gtag('config', '{GA4_ID}', {{ anonymize_ip: true }});
</script>
{ld}</head>
<body>
<header class="top">
  <a class="brand" href="/">{SITE_NAME}</a>
  <nav><a href="/">지역 순위</a><a href="/about">데이터·산식</a></nav>
</header>
<main>
"""


def foot(d, extra=''):
    return f"""</main>
<footer>
  <p>{SNAPSHOT_NOTE} · 기준월 {d['reference_month_label']} · 스냅샷 {d['snapshot_date']}</p>
  <p><a href="/about">데이터 출처·산식·한계</a> · <a href="/llms.txt">llms.txt</a> · <a href="/api/regions.json">JSON API</a> · <a href="/privacy">개인정보·쿠키</a></p>
  <p class="small">이 사이트는 공개된 공공데이터를 집계해 보여줍니다. 개별 단지의 실제 부과액은 관리주체 고지서를 기준으로 하세요.</p>
</footer>
{extra}</body>
</html>
"""


# ------------------------------------------------------------- fragments ----
def fmt_month_label(m):
    return f"{m[:4]}년 {int(m[4:])}월" if len(m) == 6 else m


def mom_badge(pct):
    if pct is None:
        return '<span class="muted">—</span>'
    cls = 'up' if pct > 0 else ('down' if pct < 0 else 'flat')
    arrow = '▲' if pct > 0 else ('▼' if pct < 0 else '–')
    return f'<span class="mom {cls}">{arrow} {abs(pct):.1f}%</span>'


ITEM_LABELS = [
    ('labor', '인건비'), ('office', '제사무비'), ('tax', '제세공과금'), ('cloth', '피복비'),
    ('edu', '교육훈련비'), ('car', '차량유지비'), ('other', '그 밖의 부대비용'),
    ('clean', '청소비'), ('guard', '경비비'), ('disinfection', '소독비'),
    ('elevator', '승강기유지비'), ('network', '지능형네트워크유지비'),
    ('repair', '수선유지비'), ('safety', '안전점검비'), ('disaster', '재해예방비'),
    ('outsourced', '위탁관리수수료'),
]


def region_table(rows, start=1, link=True, limit=None):
    out = ['<div class="tablewrap"><table class="data"><thead><tr>'
           '<th class="n">#</th><th>지역</th><th class="r">단지</th><th class="r">세대</th>'
           '<th class="r">㎡당 공용관리비</th><th class="r">세대당 총관리비</th><th class="r">전월</th>'
           '</tr></thead><tbody>']
    for i, r in enumerate(rows[:limit] if limit else rows, start=start):
        name = f"{r['sido']} {r['sgg']}".strip()
        if link:
            name = f'<a href="/region/{r["slug"]}">{esc(name)}</a>'
        out.append(
            f'<tr><td class="n">{i}</td><td>{name}</td>'
            f'<td class="r">{fmt_int(r["complexes"])}</td>'
            f'<td class="r">{fmt_int(r["households"])}</td>'
            f'<td class="r num"><strong>{fmt_dec(r["fee_m2"])}</strong></td>'
            f'<td class="r num">{fmt_int(r["fee_hh"])}</td>'
            f'<td class="r">{mom_badge(r["mom_pct"])}</td></tr>')
    out.append('</tbody></table></div>')
    return '\n'.join(out)


def faq_block(items):
    out = ['<section class="faq"><h2>자주 묻는 질문</h2>']
    for q, a in items:
        out.append(f'<details><summary>{esc(q)}</summary><p>{a}</p></details>')
    out.append('</section>')
    return '\n'.join(out)


# ----------------------------------------------------------------- pages ----
def trade_summary_rows(regions, month, limit=50):
    rows = []
    for r in regions[:limit]:
        t = (r.get('trade') or {}).get(month)
        if not t:
            continue
        name = f"{r['sido']} {r['sgg']}".strip()
        rows.append((r, t, name))
    return rows


def build_index(d):
    regions = d['regions']
    ranked = [r for r in regions if r['counted'] >= 30 and r['fee_m2'] is not None]
    lowest = sorted(ranked, key=lambda r: r['fee_m2'])[:10]
    highest = sorted(ranked, key=lambda r: -r['fee_m2'])[:10]
    top50 = regions[:50]
    n = d['national']
    tr = d.get('trade') or {}
    tm = tr.get('reference_month')
    tn = (tr.get('national') or {}).get(tm, {}) if tm else {}
    # cheapest per-pyeong regions among those with enough trades
    trade_rank = sorted([r for r in regions if ((r.get('trade') or {}).get(tm) or {}).get('count', 0) >= 50],
                        key=lambda r: r['trade'][tm]['median_per_pyeong'])[:10]

    trade_cards = ''
    if tn:
        trade_cards = (
            f'<div class="card"><span>전국 아파트 매매 거래</span><strong>{fmt_int(tn["count"])}<small>건</small></strong></div>'
            f'<div class="card"><span>중간 매매가 · 평당가</span><strong>{fmt_price(tn["median_price"])}</strong>'
            f'<span class="sub2">평당 {fmt_dec(tn["median_per_pyeong"])}만원 · {tr["reference_month_label"]}</span></div>')

    faq = [
        ('이 사이트의 관리비 숫자는 어디서 오나요?',
         f"K-apt(공동주택관리정보시스템)가 주 1회 공개하는 ‘관리비공개의무단지 관리비정보’ 파일과 ‘면적정보’ 파일을 그대로 집계했습니다. "
         f"이번 스냅샷은 {d['snapshot_date']} 추출본이고, 기준월은 {d['reference_month_label']}입니다."),
        ('실거래가는 어떻게 집계했나요?',
         f"국토교통부 실거래가공개시스템의 자료제공 CSV(아파트 매매, 계약일 기준)를 받아 시군구별로 집계했습니다. "
         f"해제된 거래는 빼고, 거래 건수·중간 거래금액·중간 평당가를 계산합니다. 이번 기준월은 {tr.get('reference_month_label', '—')}입니다."),
        ('㎡당 공용관리비는 어떻게 계산하나요?',
         f"단지별 ‘공용관리비 합계’를 그 단지의 ‘관리비부과면적(㎡)’으로 나눈 값입니다. "
         f"지역 값은 단지별 값을 면적(관리비부과면적)으로 가중평균했습니다. 현재 전국 가중평균은 {fmt_dec(n['fee_m2'])}원/㎡입니다."),
        ('평당가는 어떻게 계산하나요?',
         "거래 1건마다 ‘거래금액 ÷ 전용면적 × 3.305785’로 평당 금액을 구한 뒤, 그 지역 거래들의 중간값을 씁니다. "
         "평균 대신 중간값을 쓰는 이유는 고가 거래 한 건이 지역 값을 끌고 가지 않게 하기 위해서입니다."),
        ('세대당 총관리비는 무엇을 더한 값인가요?',
         "공용관리비 + 개별사용료(전기·수도·난방 등) + 장기선충당금 월부과액을 더해 세대수로 나눈 값입니다. "
         "개별사용료는 사용량에 따라 달라지므로 지역 비교에는 ㎡당 공용관리비를 권합니다."),
        ('왜 우리 단지가 보이지 않나요?',
         "K-apt 관리비 공개는 300세대 이상, 150세대 이상이면서 승강기 또는 중앙난방이 있는 단지 등 ‘관리비 공개의무단지’가 대상입니다. "
         f"이 기준에 들지 않거나 해당 월 공개가 없는 단지는 표에 나오지 않습니다. 이번 기준월 집계 단지는 {fmt_int(n['complexes'])}곳입니다."),
        ('관리비가 가장 싼 지역은 어디인가요?',
         f"단지 30곳 이상이 집계된 지역 가운데 {lowest[0]['sido']} {lowest[0]['sgg']}가 ㎡당 {fmt_dec(lowest[0]['fee_m2'])}원으로 가장 낮았습니다. "
         f"다음은 {lowest[1]['sido']} {lowest[1]['sgg']}({fmt_dec(lowest[1]['fee_m2'])}원), {lowest[2]['sido']} {lowest[2]['sgg']}({fmt_dec(lowest[2]['fee_m2'])}원) 순입니다."),
        ('얼마나 자주 갱신되나요?',
         "관리비는 K-apt 파일이 주 1회 갱신되고, 실거래가는 매달 자료제공 파일을 받아 반영합니다. 이 사이트는 매주 자동으로 다시 만들어집니다."),
    ]
    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebSite", "@id": BASE + "/#website", "url": BASE + "/",
             "name": SITE_NAME, "inLanguage": "ko-KR",
             "description": "전국 아파트 단지·시군구별 관리비(㎡당)와 아파트 매매 실거래 통계"},
            {"@type": "WebPage", "@id": BASE + "/#webpage", "url": BASE + "/",
             "name": f"전국 아파트 관리비·실거래가 순위 ({d['reference_month_label']} 기준)",
             "inLanguage": "ko-KR", "isPartOf": {"@id": BASE + "/#website"},
             "dateModified": d['snapshot_date']},
            {"@type": "Dataset", "@id": BASE + "/#dataset",
             "name": "전국 공동주택 관리비·아파트 매매 실거래 집계",
             "description": f"K-apt 관리비공개의무단지 공개 자료와 국토교통부 실거래가공개시스템 자료를 시군구 단위로 집계한 통계. 관리비 기준월 {d['reference_month_label']}, 실거래 기준월 {tr.get('reference_month_label', '—')}.",
             "temporalCoverage": f"{d['reference_month']}-01/{tr.get('reference_month', d['reference_month'])}-28",
             "dateModified": d['snapshot_date'],
             "creator": {"@type": "Organization", "name": "국토교통부"},
             "isBasedOn": ["https://www.data.go.kr/data/3039714/fileData.do",
                           "https://rt.molit.go.kr/"],
             "license": "https://www.data.go.kr/ugs/selectPortalPolicyView.do",
             "variableMeasured": ["㎡당 공용관리비(원/㎡·월)", "세대당 총관리비(원/월)",
                                  "아파트 매매 거래 건수", "중간 매매가(만원)", "평당가(만원/평)"],
             "distribution": [
                 {"@type": "DataDownload", "encodingFormat": "application/json",
                  "contentUrl": BASE + "/api/regions.json"},
                 {"@type": "DataDownload", "encodingFormat": "text/plain",
                  "contentUrl": BASE + "/llms.txt"}]},
            {"@type": "FAQPage", "@id": BASE + "/#faq",
             "mainEntity": [{"@type": "Question", "name": q,
                             "acceptedAnswer": {"@type": "Answer", "text": re.sub('<[^>]+>', '', a)}}
                            for q, a in faq]},
        ]
    }
    trade_rows = ''.join(
        f'<tr><td><a href="/region/{r["slug"]}">{esc(name)}</a></td>'
        f'<td class="r">{fmt_int(t["count"])}</td>'
        f'<td class="r num">{fmt_price(t["median_price"])}</td>'
        f'<td class="r num">{fmt_dec(t["median_per_pyeong"])}</td></tr>'
        for r, t, name in trade_summary_rows(regions, tm, 50)) if tm else ''
    trade_section = ''
    if trade_rows:
        trade_section = f"""
<section>
  <h2>아파트 매매 실거래 · 세대수 상위 50개 시군구</h2>
  <p class="sub">{tr['reference_month_label']} 계약분 · 건수 {fmt_int(tn.get('count'))}건(전국) · 중간 매매가 {fmt_price(tn.get('median_price'))} · 중간 평당가 {fmt_dec(tn.get('median_per_pyeong'))}만원. 신고 기한이 30일이라 최근 월은 잠정치입니다.{' · 실거래 자동 수집이 지연되어 최근 수집분을 표시합니다.' if tr.get('stale') else ''}</p>
  <div class="tablewrap"><table class="data"><thead><tr>
    <th>지역</th><th class="r">거래 건수</th><th class="r">중간 매매가</th><th class="r">평당가(만원)</th>
  </tr></thead><tbody>{trade_rows}</tbody></table></div>
</section>
"""
    cheap_trade = ''
    if trade_rank:
        rows = ''.join(
            f'<tr><td><a href="/region/{r["slug"]}">{esc(r["sido"])} {esc(r["sgg"])}</a></td>'
            f'<td class="r num">{fmt_dec(r["trade"][tm]["median_per_pyeong"])}</td>'
            f'<td class="r num">{fmt_price(r["trade"][tm]["median_price"])}</td>'
            f'<td class="r">{fmt_int(r["trade"][tm]["count"])}</td></tr>' for r in trade_rank)
        cheap_trade = f"""
<section>
  <h2>평당가가 낮은 지역 (거래 50건 이상)</h2>
  <p class="sub">{tr['reference_month_label']} 기준 중간 평당가가 낮은 순입니다.</p>
  <div class="tablewrap"><table class="data"><thead><tr>
    <th>지역</th><th class="r">평당가(만원)</th><th class="r">중간 매매가</th><th class="r">거래 건수</th>
  </tr></thead><tbody>{rows}</tbody></table></div>
</section>
"""
    body = f"""
<section class="hero">
  <h1>전국 아파트 관리비·실거래가, 지역별로 한눈에</h1>
  <p class="lead">관리비 {d['reference_month_label']} · 실거래 {tr.get('reference_month_label', '—')} · K-apt·국토교통부 공개 자료 집계 · {fmt_int(n['regions'])}개 시군구 · {fmt_int(n['complexes'])}개 단지</p>
  <div class="cards">
    <div class="card"><span>전국 ㎡당 공용관리비</span><strong>{fmt_dec(n['fee_m2'])}<small>원/㎡·월</small></strong></div>
    <div class="card"><span>집계 단지</span><strong>{fmt_int(n['complexes'])}<small>곳</small></strong></div>
    <div class="card"><span>집계 세대</span><strong>{fmt_int(n['households'])}<small>세대</small></strong></div>
    {trade_cards}
  </div>
  {'' if not d['provisional'] else '<p class="notice">' + esc(d['reference_month_label']) + ' 관리비는 공개가 진행 중인 잠정 집계입니다. 신고가 끝난 단지만 포함되어 지역 평균이 다소 달라질 수 있습니다.</p>'}
  {'' if not d.get('kapt_stale') else '<p class="notice">관리비 원본 수집이 지연되어 ' + esc(d['snapshot_date']) + ' 스냅샷을 표시합니다. 다음 자동 갱신에서 최신 공개분으로 교체됩니다.</p>'}
</section>

<section>
  <h2>세대수 상위 50개 시군구 관리비</h2>
  <p class="sub">세대수가 많은 순입니다. ㎡당 공용관리비는 면적 가중평균, 세대당 총관리비는 공용관리비+개별사용료+장기선충당금 기준입니다.</p>
  {region_table(top50)}
</section>
{trade_section}
{cheap_trade}
<section class="two">
  <div>
    <h2>㎡당 관리비가 낮은 지역</h2>
    <p class="sub">단지 30곳 이상 집계된 지역만 비교했습니다.</p>
    {region_table(lowest)}
  </div>
  <div>
    <h2>㎡당 관리비가 높은 지역</h2>
    <p class="sub">같은 조건입니다. 고급·대형 단지 비중, 위탁관리 여부에 따라 달라집니다.</p>
    {region_table(highest)}
  </div>
</section>

{faq_block(faq)}

<section class="note">
  <h2>숫자를 읽을 때</h2>
  <ul>
    <li>관리비는 단지마다 부과 항목과 면적 기준이 달라, ㎡당 공용관리비로 비교하는 것이 가장 공정합니다.</li>
    <li>실거래는 계약일 기준이고 신고 기한이 30일이라, 최근 월은 신고가 더 들어오면 값이 달라집니다.</li>
    <li>평당가는 전용면적 기준입니다. 같은 단지라도 평형·층·향에 따라 거래금액이 크게 달라집니다.</li>
    <li>전체 지역 {fmt_int(n['regions'])}곳의 표와 단지별 12개월 추이는 지역 페이지에서 볼 수 있습니다.</li>
  </ul>
</section>
"""
    return head(f"전국 아파트 관리비·실거래가 — {d['reference_month_label']} 시군구별 비교",
                f"{d['reference_month_label']} K-apt 관리비와 {tr.get('reference_month_label', '')} 실거래를 전국 {fmt_int(n['complexes'])}개 단지·{fmt_int(n['regions'])}개 시군구로 정리했습니다.",
                BASE + '/', ld) + body + foot(d)


def build_region(d, r):
    complexes = sorted(r['_complexes'], key=lambda c: (-c['households'], c['name']))
    ranked = [x for x in d['regions'] if x['counted'] >= 30 and x['fee_m2'] is not None]
    rank_asc = sorted(ranked, key=lambda x: x['fee_m2'])
    pos = [i for i, x in enumerate(rank_asc, 1) if x['slug'] == r['slug']]
    rank_txt = f"㎡당 낮은 순 {pos[0]}위 / {len(rank_asc)}개 지역" if pos else '—'
    name = f"{r['sido']} {r['sgg']}".strip()
    label = r['sgg'] or r['sido']
    prev = d['previous_month']
    faq = [
        (f"{label} 아파트 관리비 평균은 얼마인가요?",
         f"{d['reference_month_label']} 기준 {r['sgg']}의 ㎡당 공용관리비는 면적 가중평균 {fmt_dec(r['fee_m2'])}원/㎡, 단지별 중위값은 {fmt_dec(r['median_fee_m2'])}원/㎡입니다. "
         f"세대당 총관리비(개별사용료·장기수선충당금 포함)는 평균 {fmt_int(r['fee_hh'])}원입니다."),
        (f"{label}에서 관리비가 가장 낮은 단지는 어디인가요?",
         f"집계된 {fmt_int(r['complexes'])}개 단지 중 ㎡당 공용관리비가 가장 낮은 곳은 {esc(min((c for c in r['_complexes'] if c['fee_m2']), key=lambda c: c['fee_m2'])['name'])}입니다. "
         "단지 표에서 ㎡당 값을 기준으로 비교할 수 있습니다."),
        (f"{label} 관리비는 전월보다 올랐나요?",
         (f"전월({prev}) 대비 {r['mom_pct']:.1f}% 변동했습니다." if r['mom_pct'] is not None else "전월 비교 값이 없습니다.")),
        ("관리비에 포함된 항목은 무엇인가요?",
         "공용관리비(인건비·청소비·경비비·수선유지비·승강기유지비 등), 개별사용료(전기·수도·난방·가스), 장기수선충당금으로 나뉩니다. 이 페이지의 항목별 표는 공용관리비 항목을 ㎡당으로 보여줍니다."),
    ]
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "WebPage", "@id": f"{BASE}/region/{r['slug']}#webpage",
         "url": f"{BASE}/region/{r['slug']}",
         "name": f"{name} 아파트 관리비 — {d['reference_month_label']}",
         "inLanguage": "ko-KR", "dateModified": d['snapshot_date']},
        {"@type": "Dataset", "name": f"{name} 아파트 관리비 집계",
         "description": f"{d['reference_month_label']} K-apt 공개 자료 기준 {name} {fmt_int(r['complexes'])}개 단지의 ㎡당 관리비·세대당 총관리비.",
         "dateModified": d['snapshot_date'],
         "creator": {"@type": "Organization", "name": "국토교통부 공동주택관리정보시스템(K-apt)"},
         "license": "https://www.data.go.kr/ugs/selectPortalPolicyView.do",
         "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json",
                           "contentUrl": f"{BASE}/api/regions/{r['slug']}.json"}]},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "홈", "item": BASE + "/"},
            {"@type": "ListItem", "position": 2, "name": name, "item": f"{BASE}/region/{r['slug']}"}]},
        {"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
    ]}
    items = '\n'.join(
        f'<tr><td>{esc(label)}</td><td class="r num">{fmt_dec(r["items"].get(key))}</td>'
        f'<td class="r num">{fmt_dec((r["items"].get(key) or 0) / r["fee_m2"] * 100, 1)}%</td></tr>'
        for key, label in ITEM_LABELS)
    items += (f'<tr class="total"><td>공용관리비 합계</td>'
              f'<td class="r num">{fmt_dec(r["fee_m2"])}</td><td class="r num">100.0%</td></tr>')
    rows = []
    for c in complexes[:40]:
        rows.append(
            f'<tr><td><a href="/complex/{c["id"]}">{esc(c["name"])}</a></td>'
            f'<td>{esc(c["dong"])}</td>'
            f'<td class="r">{fmt_int(c["households"])}</td>'
            f'<td class="r">{fmt_int(c["dongs"])}</td>'
            f'<td class="r num">{fmt_dec(c["fee_m2"])}</td>'
            f'<td class="r num">{fmt_int(c["fee_hh"])}</td>'
            f'<td class="r">{mom_badge(c["mom_pct"])}</td></tr>')
    trad = r.get('trade') or {}
    tr = d.get('trade') or {}
    tm = (tr or {}).get('reference_month')
    tcur = trad.get(tm) if tm else None
    trade_cards = ''
    trade_section = ''
    if tcur:
        trade_cards = f'''
  <div class="cards sub-cards">
    <div class="card"><span>아파트 매매 거래({tr['reference_month_label']})</span><strong>{fmt_int(tcur['count'])}<small>건</small></strong></div>
    <div class="card"><span>중간 매매가</span><strong>{fmt_price(tcur['median_price'])}</strong><span class="sub2">중간 전용면적 {fmt_dec(tcur['median_area'])}㎡</span></div>
    <div class="card"><span>중간 평당가</span><strong>{fmt_dec(tcur['median_per_pyeong'])}<small>만원/평</small></strong></div>
  </div>'''
        trade_row_html = ''.join(
            f'<tr><td>{esc(m)}</td><td class="r">{fmt_int(trad[m]["count"])}</td>'
            f'<td class="r num">{fmt_price(trad[m]["median_price"])}</td>'
            f'<td class="r num">{fmt_dec(trad[m]["median_per_pyeong"])}</td></tr>'
            for m in sorted(trad, reverse=True))
        trade_section = f'''
<section>
  <h2>아파트 매매 실거래</h2>
  <p class="sub">국토교통부 실거래가공개시스템 자료(계약일 기준, 해제 거래 제외). 중간값 기준입니다.{' 최근 수집분 기준입니다.' if tr.get('stale') else ''}</p>
  <div class="tablewrap narrow"><table class="data"><thead><tr>
    <th>계약월</th><th class="r">거래 건수</th><th class="r">중간 매매가</th><th class="r">중간 평당가(만원)</th>
  </tr></thead><tbody>{trade_row_html}</tbody></table></div>
</section>'''
    siblings = [x for x in sorted(d['regions'], key=lambda x: -(x['households'] or 0))
                if x['sido'] == r['sido'] and x['slug'] != r['slug']][:8]
    sib = ' · '.join(f'<a href="/region/{x["slug"]}">{esc(x["sgg"])}</a>' for x in siblings)

    body = f"""
<nav class="crumb"><a href="/">홈</a> › <span>{esc(r['sido'])}</span> › <span>{esc(r['sgg'])}</span></nav>
<section class="hero">
  <h1>{esc(name)} 아파트 관리비</h1>
  <p class="lead">{d['reference_month_label']} 기준 · 단지 {fmt_int(r['complexes'])}곳 · 세대 {fmt_int(r['households'])}세대 · {rank_txt}</p>
  <div class="cards">
    <div class="card"><span>㎡당 공용관리비</span><strong>{fmt_dec(r['fee_m2'])}<small>원/㎡·월</small></strong></div>
    <div class="card"><span>단지별 중위값</span><strong>{fmt_dec(r['median_fee_m2'])}<small>원/㎡·월</small></strong></div>
    <div class="card"><span>세대당 총관리비</span><strong>{fmt_int(r['fee_hh'])}<small>원/월</small></strong></div>
    <div class="card"><span>전월 대비</span><strong>{mom_badge(r['mom_pct'])}</strong></div>
  </div>
  {trade_cards}
</section>
{trade_section}

<section>
  <h2>단지별 관리비</h2>
  <p class="sub">세대수 순 상위 {min(40, len(complexes))}곳입니다. 단지명을 누르면 12개월 추이와 항목별 내역이 나옵니다.</p>
  <div class="tablewrap"><table class="data"><thead><tr>
    <th>단지</th><th>동</th><th class="r">세대</th><th class="r">동수</th>
    <th class="r">㎡당</th><th class="r">세대당</th><th class="r">전월</th>
  </tr></thead><tbody>
  {''.join(rows)}
  </tbody></table></div>
  {f'<p class="sub">그 밖의 {fmt_int(len(complexes) - 40)}개 단지는 <a href="/api/regions/{r["slug"]}.json">JSON 피드</a>에 모두 들어 있습니다.</p>' if len(complexes) > 40 else ''}
</section>

<section>
  <h2>공용관리비 항목별 구성</h2>
  <p class="sub">면적 가중평균, 단위 원/㎡·월. 비중은 공용관리비 합계 대비입니다.</p>
  <div class="tablewrap"><table class="data"><thead><tr><th>항목</th><th class="r">원/㎡</th><th class="r">비중</th></tr></thead>
  <tbody>{items}</tbody></table></div>
</section>

{faq_block(faq)}

<p class="sub">같은 시도: {sib}</p>
"""
    return head(f"{name} 아파트 관리비 — {d['reference_month_label']} ㎡당 {fmt_dec(r['fee_m2'])}원",
                f"{name} {fmt_int(r['complexes'])}개 단지의 {d['reference_month_label']} 관리비. ㎡당 공용관리비 {fmt_dec(r['fee_m2'])}원, 세대당 총관리비 {fmt_int(r['fee_hh'])}원.",
                f"{BASE}/region/{r['slug']}", ld) + body + foot(d)


def build_complex(d, c, r):
    name = c['name']
    pct = None
    if r and r['fee_m2'] and c['fee_m2']:
        pct = (c['fee_m2'] - r['fee_m2']) / r['fee_m2'] * 100
    series = c.get('series') or {}
    series_rows = ''.join(
        f'<tr><td>{esc(k)}</td><td class="r num">{fmt_dec(v)}</td></tr>' for k, v in sorted(series.items(), reverse=True))
    items = '\n'.join(
        f'<tr><td>{esc(label)}</td><td class="r num">{fmt_dec((c["items"].get(key) or 0) / c["billing_area"])}</td>'
        f'<td class="r num">{fmt_dec((c["items"].get(key) or 0) / c["common_fee"] * 100, 1)}%</td></tr>'
        for key, label in ITEM_LABELS)
    items += (f'<tr class="total"><td>공용관리비 합계</td>'
              f'<td class="r num">{fmt_dec(c["fee_m2"])}</td><td class="r num">100.0%</td></tr>')
    prev = c.get('prev_fee_m2')
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "WebPage", "url": f"{BASE}/complex/{c['id']}",
         "name": f"{name} 관리비 — {d['reference_month_label']}",
         "inLanguage": "ko-KR", "dateModified": d['snapshot_date']},
        {"@type": "Dataset", "name": f"{name} 관리비 시계열",
         "description": f"{name}({esc(c['sgg'])}, {fmt_int(c['households'])}세대)의 K-apt 공개 관리비. 기준월 {d['reference_month_label']} ㎡당 {fmt_dec(c['fee_m2'])}원.",
         "dateModified": d['snapshot_date'],
         "creator": {"@type": "Organization", "name": "국토교통부 공동주택관리정보시스템(K-apt)"},
         "license": "https://www.data.go.kr/ugs/selectPortalPolicyView.do"},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "홈", "item": BASE + "/"},
            {"@type": "ListItem", "position": 2, "name": f"{c['sido']} {c['sgg']}",
             "item": f"{BASE}/region/{r['slug']}" if r else BASE + "/"},
            {"@type": "ListItem", "position": 3, "name": name, "item": f"{BASE}/complex/{c['id']}"}]},
    ]}
    body = f"""
<nav class="crumb"><a href="/">홈</a>{f' › <a href="/region/{r["slug"]}">{esc(c["sido"])} {esc(c["sgg"])}</a>' if r else ''} › <span>{esc(name)}</span></nav>
<section class="hero">
  <h1>{esc(name)} 관리비</h1>
  <p class="lead">{esc(c['sido'])} {esc(c['sgg'])} {esc(c['dong'])} · {fmt_int(c['households'])}세대 · {fmt_int(c['dongs'])}개동 · 관리비부과면적 {fmt_int(round(c['billing_area']))}㎡</p>
  <div class="cards">
    <div class="card"><span>㎡당 공용관리비</span><strong>{fmt_dec(c['fee_m2'])}<small>원/㎡·월</small></strong></div>
    <div class="card"><span>공용관리비 합계</span><strong>{fmt_int(c['common_fee'])}<small>원/월</small></strong></div>
    <div class="card"><span>세대당 총관리비</span><strong>{fmt_int(c['fee_hh'])}<small>원/월</small></strong></div>
    <div class="card"><span>지역 평균 대비</span><strong>{('+' if (pct or 0) > 0 else '') + fmt_dec(pct, 1) + '%' if pct is not None else '—'}</strong></div>
  </div>
</section>

<section>
  <h2>월별 ㎡당 공용관리비</h2>
  <p class="sub">K-apt에 공개된 최근 {len(series)}개월 값입니다. 전월 값은 {fmt_dec(prev)}원/㎡입니다.</p>
  <div class="tablewrap narrow"><table class="data"><thead><tr><th>기준월</th><th class="r">원/㎡</th></tr></thead><tbody>{series_rows}</tbody></table></div>
</section>

<section>
  <h2>공용관리비 항목별</h2>
  <p class="sub">단지의 공용관리비를 항목별로 나눈 금액입니다. 단위 원/㎡·월, 비중은 공용관리비 합계 대비.</p>
  <div class="tablewrap narrow"><table class="data"><thead><tr><th>항목</th><th class="r">원/㎡</th><th class="r">비중</th></tr></thead><tbody>{items}</tbody></table></div>
</section>

<section class="note">
  <h2>함께 볼 값</h2>
  <ul>
    <li>개별사용료(전기·수도·난방·가스) 이번 달 합계: {fmt_int(c['indiv_fee'])}원</li>
    <li>장기수선충당금 월부과액: {fmt_int(c['last_charge'])}원</li>
    <li>세대당 총관리비: {fmt_int(c['fee_hh'])}원 (공용관리비+개별사용료+장기수선충당금 ÷ 세대수)</li>
  </ul>
</section>
"""
    return head(f"{name} 관리비 — {d['reference_month_label']} ㎡당 {fmt_dec(c['fee_m2'])}원",
                f"{esc(c['sido'])} {esc(c['sgg'])} {esc(name)}의 {d['reference_month_label']} 관리비. ㎡당 공용관리비 {fmt_dec(c['fee_m2'])}원, 세대당 총관리비 {fmt_int(c['fee_hh'])}원, 최근 {len(series)}개월 추이.",
                f"{BASE}/complex/{c['id']}", ld) + body + foot(d)


def build_about(d):
    n = d['national']
    q = d.get('quality') or {'area_suspect': 0, 'no_fee': 0}
    faq = [
        ("데이터 출처는 무엇인가요?",
         "K-apt(공동주택관리정보시스템) 자료실의 ‘K-apt 관리비공개의무단지 관리비정보’와 ‘면적정보’ 파일입니다. 두 자료는 공공데이터포털에도 같은 내용이 등록되어 있습니다(이용허락범위 제한 없음)."),
        ("어떤 단지가 포함되나요?",
         "관리비 공개 의무단지(300세대 이상, 150세대 이상이면서 승강기·중앙난방 보유 등) 중 해당 월 관리비가 공개된 단지입니다."),
        ("갱신 주기는 어떻게 되나요?",
         "K-apt는 주 1회 파일을 갱신하며, 이 사이트는 매주 자동으로 다시 만들어집니다. 기준월은 공개가 끝난 최신 월입니다."),
        ("값을 임의로 보정하거나 추정하지 않나요?",
         "아니요. 공개된 값을 그대로 쓰고, 계산은 나눗셈·가중평균만 합니다. 공개되지 않은 단지나 월은 비워 둡니다."),
    ]
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "WebPage", "url": BASE + "/about", "name": "데이터 출처·산식·한계",
         "inLanguage": "ko-KR", "dateModified": d['snapshot_date']},
        {"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
    ]}
    body = f"""
<section class="hero">
  <h1>데이터 출처·산식·한계</h1>
  <p class="lead">이 사이트의 모든 숫자가 어떻게 만들어졌는지 정리했습니다.</p>
</section>
<section>
  <h2>출처</h2>
  <ul>
    <li>원자료: K-apt 공동주택관리정보시스템 자료실 — ‘관리비공개의무단지 관리비정보’, ‘관리비공개의무단지 면적정보’ (주 1회 공개)</li>
    <li>공공데이터포털 등록본: 국토교통부_공동주택 단지 관리비 정보(3039714), 국토교통부_공동주택 단지 면적 정보(15073269)</li>
    <li>실거래: 국토교통부 실거래가공개시스템 ‘조건별 자료제공’ CSV(아파트 매매, 계약일 기준) — 최근 4개월분</li>
    <li>이용 조건: 이용허락범위 제한 없음(공공데이터포털 기준), 출처 표시</li>
    <li>이번 스냅샷: {d['snapshot_date']} 추출 · 관리비 기준월 {d['reference_month_label']} · 집계 단지 {fmt_int(n['complexes'])}곳 · 시군구 {fmt_int(n['regions'])}곳</li>
    <li>실거래: 기준월 {(d.get('trade') or {}).get('reference_month_label', '—')} · 최근 {len((d.get('trade') or {}).get('months', []))}개월 · 거래 {(d.get('trade') or {}).get('rows', 0):,}건</li>
  </ul>
</section>
<section>
  <h2>산식</h2>
  <ul>
    <li><strong>㎡당 공용관리비</strong> = 공용관리비 합계 ÷ 관리비부과면적(㎡)</li>
    <li><strong>지역 값</strong> = 단지별 ㎡당 값의 면적 가중평균 (Σ공용관리비 ÷ Σ관리비부과면적)</li>
    <li><strong>세대당 총관리비</strong> = (공용관리비 + 개별사용료 + 장기수선충당금 월부과액) ÷ 세대수</li>
    <li><strong>중위값</strong> = 지역 내 단지별 ㎡당 값의 중앙값</li>
    <li><strong>전월 대비</strong> = 같은 단지 집합 기준이 아니라 지역 전체 가중평균끼리의 비교입니다</li>
    <li><strong>평당가</strong> = 거래금액 ÷ 전용면적 × 3.305785 (만원/평), 지역 값은 거래별 값의 중간값</li>
    <li><strong>중간 매매가</strong> = 지역 내 거래금액의 중간값(만원)</li>
  </ul>
</section>
<section>
  <h2>한계</h2>
  <ul>
    <li>관리비 공개 의무가 없는 단지(소규모)는 포함되지 않습니다.</li>
    <li>신고·공개가 늦은 단지는 해당 월 집계에서 빠지므로 잠정 집계월은 평균이 달라질 수 있습니다.</li>
    <li>개별사용료(전기·수도·난방)는 사용량에 따라 달라 지역 비교 지표로 쓰지 않았습니다.</li>
    <li>원자료의 면적 입력 오류 가능성이 큰 {fmt_int(q['area_suspect'])}개 단지는 ㎡당 지표에서 제외했습니다(관리비부과면적÷세대수가 10㎡ 미만 또는 400㎡ 초과). 공용관리비가 0으로 공개된 {fmt_int(q['no_fee'])}개 단지도 ㎡당 값이 없습니다.</li>
    <li>실거래는 계약일 기준이고 신고 기한이 30일이므로, 최근 월은 신고가 더 들어오면 건수·중간가가 달라집니다.</li>
    <li>평당가는 전용면적 기준이며, 같은 단지·평형이라도 층·향·수리 상태에 따라 달라집니다.</li>
    <li>해제된 거래(해제사유발생일이 있는 건)는 집계에서 제외했습니다.</li>
    <li>개별 단지의 실제 부과액은 관리주체 고지서가 기준입니다.</li>
  </ul>
</section>
{faq_block(faq)}
"""
    return head('데이터 출처·산식·한계 | 아파트 관리비 인사이트',
                'K-apt 공개 자료를 어떻게 집계했는지, 어떤 한계가 있는지 정리했습니다.',
                BASE + '/about', ld) + body + foot(d)


def build_privacy(d):
    body = """
<section class="hero"><h1>개인정보·쿠키</h1></section>
<section>
  <h2>수집하는 정보</h2>
  <ul>
    <li>이 사이트는 회원가입·로그인·문의 폼이 없으며, 이용자가 입력한 개인정보를 받지 않습니다.</li>
    <li>방문 통계를 위해 Google Analytics 4를 사용합니다. IP 익명화 설정을 켜 두었고, 수집 항목은 페이지 조회·유입 경로·기기 유형 수준입니다.</li>
    <li>광고·제휴 스크립트는 넣지 않았습니다.</li>
  </ul>
  <h2>쿠키</h2>
  <p>Google Analytics가 방문을 구분하기 위해 쿠키를 사용합니다. 브라우저 설정에서 쿠키를 막아도 사이트의 모든 표와 수치는 그대로 볼 수 있습니다.</p>
  <h2>문의</h2>
  <p>데이터 오류 제보는 <a href="/about">데이터 출처·산식</a> 페이지의 설명을 확인한 뒤 원자료(K-apt)와 대조해 주세요.</p>
</section>
"""
    return head('개인정보·쿠키 | 아파트 관리비 인사이트',
                '이 사이트의 개인정보 처리와 쿠키 사용 안내.', BASE + '/privacy') + body + foot(d)


def build_llms(d):
    n = d['national']
    regions = d['regions']
    ranked = [r for r in regions if r['counted'] >= 30 and r['fee_m2'] is not None]
    lowest = sorted(ranked, key=lambda r: r['fee_m2'])[:5]
    highest = sorted(ranked, key=lambda r: -r['fee_m2'])[:5]
    top = regions[:10]
    lines = [
        f"# {SITE_NAME}",
        "",
        f"> 전국 아파트 관리비를 시군구·단지 단위로 집계한 한국어 정적 데이터 사이트. "
        f"기준월 {d['reference_month_label']} K-apt(공동주택관리정보시스템) 공개 자료. "
        f"집계 단지 {fmt_int(n['complexes'])}곳, 시군구 {fmt_int(n['regions'])}곳, 전국 ㎡당 공용관리비 {fmt_dec(n['fee_m2'])}원.",
        "",
        f"as_of: {d['snapshot_date']} (K-apt 스냅샷 추출일)",
        f"data_month: {d['reference_month']}" + (" (잠정 집계: 공개 진행 중)" if d['provisional'] else ""),
        f"trade_month: {(d.get('trade') or {}).get('reference_month', 'n/a')} (국토교통부 실거래가, 계약일 기준 · 신고 진행 중)", 
        "units: 관리비 원/㎡·월, 세대당 원/월, 세대수·단지수 개",
        "license: 공공데이터포털 이용허락범위 제한 없음 (출처: 국토교통부 K-apt)",
        "",
        "## 이 사이트가 답하는 질문",
        "",
        f"- \"수성구 아파트 관리비 평균\" → /region/{next((r['slug'] for r in regions if r['sgg']=='수성구'), 'daegu-suseonggu')} (㎡당 값과 세대당 총관리비)",
        "- \"관리비 싼 지역\" → 아래 '관리비가 낮은 시군구' 표",
        "- \"○○단지 관리비\" → /complex/{단지코드} (12개월 추이와 항목별 내역)",
        "",
        "## 핵심 수치",
        "",
        f"- 전국 가중평균 ㎡당 공용관리비: {fmt_dec(n['fee_m2'])}원",
        (f"- 전국 아파트 매매 실거래({(d.get('trade') or {}).get('reference_month_label')}): "
         f"{(d.get('trade') or {}).get('national', {}).get((d.get('trade') or {}).get('reference_month'), {}).get('count', 0):,}건 · "
         f"중간 매매가 {fmt_price((d.get('trade') or {}).get('national', {}).get((d.get('trade') or {}).get('reference_month'), {}).get('median_price'))} · "
         f"중간 평당가 {fmt_dec((d.get('trade') or {}).get('national', {}).get((d.get('trade') or {}).get('reference_month'), {}).get('median_per_pyeong'))}만원"
         if d.get('trade') else "- 실거래: 미연동"),
        f"- 세대수 상위 10개 시군구:",
    ]
    for r in top:
        lines.append(f"  - {r['sido']} {r['sgg']}: {fmt_dec(r['fee_m2'])}원/㎡, 단지 {fmt_int(r['complexes'])}곳, 세대 {fmt_int(r['households'])}")
    lines += ["- 관리비가 낮은 시군구(단지 30곳 이상):"]
    for r in lowest:
        lines.append(f"  - {r['sido']} {r['sgg']}: {fmt_dec(r['fee_m2'])}원/㎡")
    lines += ["- 관리비가 높은 시군구(단지 30곳 이상):"]
    for r in highest:
        lines.append(f"  - {r['sido']} {r['sgg']}: {fmt_dec(r['fee_m2'])}원/㎡")
    lines += [
        "",
        "## 데이터 구조",
        "",
        f"- /api/regions.json — 시군구 {len(regions)}곳 요약(단지 수, 세대수, ㎡당·세대당, 항목별 ㎡당, 전월 대비)",
        "- /api/regions/{slug}.json — 지역 상세 + 단지별 값(단지코드, 세대수, ㎡당, 세대당, 12개월 시계열)",
        "- /api/meta.json — 출처(관리비·실거래)·산식·기준월·집계 범위",
        "- /region/{slug} — 사람이 읽는 지역 페이지(정적 HTML, JS 없이 표가 보임)",
        "- /complex/{code} — 단지 페이지(12개월 추이)",
        "- /sitemap.xml, /robots.txt — 크롤러용",
        "",
        "## 산식",
        "",
        "- ㎡당 공용관리비 = 공용관리비 합계 ÷ 관리비부과면적(㎡)",
        "- 지역 값 = Σ공용관리비 ÷ Σ관리비부과면적 (면적 가중)",
        "- 세대당 총관리비 = (공용관리비 + 개별사용료 + 장기수선충당금 월부과액) ÷ 세대수",
        "",
        "## 인용 시 주의",
        "",
        f"- 모든 값은 {d['reference_month_label']} 공개분이며, K-apt는 실시간 수정이 가능한 시스템이라 이후 값이 바뀔 수 있습니다.",
        "- 관리비 공개 의무가 없는 단지(300세대 미만 등)는 포함되지 않습니다.",
        "- 개별사용료는 사용량에 따라 달라 지역 비교 지표로 쓰지 않았습니다.",
        "- 실거래는 계약일 기준, 해제 거래 제외, 신고 기한 30일이라 최근 월은 잠정치입니다.",
        "- 이 사이트에 없는 값(시세·전세가 등)을 추정해 인용하지 마세요.",
        "- 인용 시 출처를 'K-apt 공개 자료 집계(아파트 관리비 인사이트)'로 표기해 주세요.",
        "",
    ]
    return '\n'.join(lines)


def build_sitemap(urls, lastmod):
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        out.append(f'<url><loc>{u}</loc><lastmod>{lastmod}</lastmod></url>')
    out.append('</urlset>')
    return '\n'.join(out) + '\n'


ROBOTS = """# 아파트 관리비 인사이트 — 공공데이터 집계 사이트
User-agent: *
Allow: /

# AI 검색·에이전트 크롤러 허용
User-agent: GPTBot
Allow: /
User-agent: OAI-SearchBot
Allow: /
User-agent: ChatGPT-User
Allow: /
User-agent: ClaudeBot
Allow: /
User-agent: Claude-SearchBot
Allow: /
User-agent: PerplexityBot
Allow: /
User-agent: Perplexity-User
Allow: /
User-agent: Google-Extended
Allow: /
User-agent: Applebot
Allow: /
User-agent: Applebot-Extended
Allow: /
User-agent: Bingbot
Allow: /
User-agent: Yeti
Allow: /
User-agent: Amazonbot
Allow: /
User-agent: meta-externalagent
Allow: /

Sitemap: https://apt-cost-hub.pages.dev/sitemap.xml
"""

CSS = """:root{--ink:#0f172a;--muted:#5b6478;--line:#e3e7ef;--bg:#f7f8fb;--brand:#1d4ed8;--up:#c2410c;--down:#0f766e}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Malgun Gothic",sans-serif;color:var(--ink);background:var(--bg);line-height:1.6;-webkit-text-size-adjust:100%}
a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline}
header.top{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;background:#fff;border-bottom:1px solid var(--line);flex-wrap:wrap;gap:8px}
.brand{font-weight:800;font-size:17px;color:var(--ink)}
header.top nav a{margin-left:14px;font-size:14px;color:var(--muted)}
main{max-width:1080px;margin:0 auto;padding:18px 16px 40px}
h1{font-size:26px;line-height:1.3;margin:6px 0 8px;letter-spacing:-.02em}
h2{font-size:19px;margin:30px 0 6px;letter-spacing:-.01em}
.lead{color:var(--muted);margin:0 0 14px;font-size:14px}
.sub{color:var(--muted);font-size:13px;margin:0 0 8px}
.crumb{font-size:13px;color:var(--muted);margin-bottom:6px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0 8px}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:flex;flex-direction:column;gap:2px}
.card span{font-size:12px;color:var(--muted)}
.card strong{font-size:22px;font-weight:800;letter-spacing:-.02em}
.card small{font-size:12px;font-weight:500;color:var(--muted);margin-left:3px}
.tablewrap{overflow-x:auto;background:#fff;border:1px solid var(--line);border-radius:12px}
.tablewrap.narrow{max-width:420px}
table.data{width:100%;border-collapse:collapse;font-size:14px;min-width:520px}
.tablewrap.narrow table.data{min-width:0}
table.data th,table.data td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
table.data thead th{background:#f1f3f8;font-size:12px;color:var(--muted);font-weight:600}
table.data tbody tr:last-child td{border-bottom:0}\ntable.data tr.total td{font-weight:700;background:#f8fafc}
table.data .r{text-align:right}
table.data .n{text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
table.data .num{font-variant-numeric:tabular-nums}
.two{display:grid;grid-template-columns:1fr 1fr;gap:22px}
@media(max-width:820px){.two{grid-template-columns:1fr}}
.mom{font-size:12px;font-weight:600}
.mom.up{color:var(--up)}.mom.down{color:var(--down)}.mom.flat{color:var(--muted)}
.muted{color:var(--muted)}
.notice{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;padding:10px 12px;border-radius:10px;font-size:13px}
.faq details{background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-bottom:8px}
.faq summary{cursor:pointer;font-weight:600;font-size:14px}
.faq p{margin:8px 0 0;font-size:14px;color:#2b3244}
.note ul,.faq ul{padding-left:18px;font-size:14px}
footer{max-width:1080px;margin:0 auto;padding:22px 16px 40px;color:var(--muted);font-size:12px;border-top:1px solid var(--line)}
footer .small{font-size:11px}
section.note{background:#fff;border:1px solid var(--line);border-radius:12px;padding:4px 16px 14px;margin-top:26px}
"""


def main():
    d = load()
    d['snapshot_date'] = d.get('snapshot_date', 'unknown')

    # region slug + back-reference
    by_region = {}
    for c in d['complexes']:
        by_region.setdefault((c['sido'], c['sgg']), []).append(c)
    for r in d['regions']:
        r['_complexes'] = by_region.get((r['sido'], r['sgg']), [])

    if os.path.isdir(SITE):
        shutil.rmtree(SITE)
    for sub in ('assets', 'region', 'complex', 'api/regions'):
        os.makedirs(os.path.join(SITE, sub), exist_ok=True)

    # choose complex pages: big complexes inside the 50 biggest regions
    big_regions = {(r['sido'], r['sgg']) for r in d['regions'][:50]}
    page_complexes = [c for c in d['complexes']
                      if (c['sido'], c['sgg']) in big_regions and c['households'] >= 300 and c['fee_m2']]
    page_complexes.sort(key=lambda c: -c['households'])
    page_complexes = page_complexes[:1500]
    page_ids = {c['id'] for c in page_complexes}

    urls = [BASE + '/', BASE + '/about', BASE + '/privacy']
    with open(os.path.join(SITE, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(build_index(d))
    with open(os.path.join(SITE, 'about.html'), 'w', encoding='utf-8') as f:
        f.write(build_about(d))
    with open(os.path.join(SITE, 'privacy.html'), 'w', encoding='utf-8') as f:
        f.write(build_privacy(d))

    region_by_key = {(r['sido'], r['sgg']): r for r in d['regions']}
    for r in d['regions']:
        with open(os.path.join(SITE, 'region', f"{r['slug']}.html"), 'w', encoding='utf-8') as f:
            f.write(build_region(d, r))
        urls.append(f"{BASE}/region/{r['slug']}")

    for c in page_complexes:
        r = region_by_key.get((c['sido'], c['sgg']))
        with open(os.path.join(SITE, 'complex', f"{c['id']}.html"), 'w', encoding='utf-8') as f:
            f.write(build_complex(d, c, r))
        urls.append(f"{BASE}/complex/{c['id']}")

    # JSON feeds ---------------------------------------------------------
    def region_public(r):
        return {k: v for k, v in r.items() if not k.startswith('_')}

    regions_feed = {
        'site': SITE_NAME, 'as_of': d['snapshot_date'], 'data_month': d['reference_month'],
        'data_month_label': d['reference_month_label'], 'previous_month': d['previous_month'],
        'provisional': d['provisional'],
        'trade': d.get('trade'),
        'sources': [
            {'name': 'K-apt 공동주택관리정보시스템 (국토교통부)',
             'files': ['관리비공개의무단지 관리비정보', '관리비공개의무단지 면적정보'],
             'portal': 'https://www.data.go.kr/data/3039714/fileData.do',
             'license': '이용허락범위 제한 없음'},
            {'name': '국토교통부 실거래가공개시스템 (자료제공 CSV, 아파트 매매)',
             'portal': 'https://rt.molit.go.kr/pt/xls/xls.do',
             'basis': '계약일 기준, 해제 거래 제외',
             'license': '공공데이터 개방 (출처 표시)'},
        ],
        'source': {
            'name': 'K-apt 공동주택관리정보시스템 (국토교통부)',
            'files': ['관리비공개의무단지 관리비정보', '관리비공개의무단지 면적정보'],
            'portal': 'https://www.data.go.kr/data/3039714/fileData.do',
            'license': '이용허락범위 제한 없음',
        },
        'units': {'fee_m2': '원/㎡·월 (공용관리비)', 'total_m2': '원/㎡·월 (공용+개별+장충금)',
                  'fee_hh': '원/월', 'billing_area': '㎡', 'households': '세대',
                  'trade.median_price': '만원', 'trade.median_per_pyeong': '만원/평', 'trade.count': '건'},
        'national': d['national'],
        'regions': [dict(region_public(r), slug=r['slug'], url=f"{BASE}/region/{r['slug']}") for r in d['regions']],
        'data_notes': [
            '㎡당 공용관리비 = 공용관리비 합계 / 관리비부과면적',
            '지역 값 = Σ공용관리비 / Σ관리비부과면적 (면적 가중평균)',
            '세대당 총관리비 = (공용관리비 + 개별사용료 + 장기수선충당금 월부과액) / 세대수',
            '관리비 공개 의무단지(300세대 이상 등)만 포함',
            '실거래는 계약일 기준이며 신고 기한 30일 때문에 최근 월은 잠정치',
            '평당가 = 거래금액 / 전용면적 * 3.305785, 지역 값은 거래별 값의 중간값',
        ],
    }
    with open(os.path.join(SITE, 'api', 'regions.json'), 'w', encoding='utf-8') as f:
        json.dump(regions_feed, f, ensure_ascii=False, separators=(',', ':'))

    for r in d['regions']:
        feed = {
            'as_of': d['snapshot_date'], 'data_month': d['reference_month'],
            'region': dict(region_public(r), slug=r['slug']),
            'trade': r.get('trade') or {},
            'complexes': [{k: v for k, v in c.items() if k != 'series'} for c in
                          sorted(r['_complexes'], key=lambda c: -c['households'])],
            'data_notes': regions_feed['data_notes'],
        }
        with open(os.path.join(SITE, 'api', 'regions', f"{r['slug']}.json"), 'w', encoding='utf-8') as f:
            json.dump(feed, f, ensure_ascii=False, separators=(',', ':'))

    meta = {
        'site': SITE_NAME, 'url': BASE, 'as_of': d['snapshot_date'],
        'data_month': d['reference_month'], 'provisional': d['provisional'],
        'sources': regions_feed['sources'], 'units': regions_feed['units'],
        'counts': {'regions': d['national']['regions'], 'complexes': d['national']['complexes'],
                   'trade_rows': (d.get('trade') or {}).get('rows'),
                   'households': d['national']['households'], 'complex_pages': len(page_complexes),
                   'monthly_rows': sum(d['month_coverage'].values())},
        'month_coverage': d['month_coverage'],
        'definitions': regions_feed['data_notes'],
        'update': 'K-apt 주 1회 갱신, 이 사이트는 매주 자동 재생성',
    }
    with open(os.path.join(SITE, 'api', 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    with open(os.path.join(SITE, 'llms.txt'), 'w', encoding='utf-8') as f:
        f.write(build_llms(d))
    with open(os.path.join(SITE, 'robots.txt'), 'w', encoding='utf-8') as f:
        f.write(ROBOTS)
    with open(os.path.join(SITE, 'sitemap.xml'), 'w', encoding='utf-8') as f:
        f.write(build_sitemap(urls, d['snapshot_date']))
    with open(os.path.join(SITE, 'assets', 'style.css'), 'w', encoding='utf-8') as f:
        f.write(CSS)
    with open(os.path.join(SITE, 'assets', 'favicon.svg'), 'w', encoding='utf-8') as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#1d4ed8"/>'
                '<path d="M14 42V26l18-12 18 12v16z" fill="#fff"/><rect x="27" y="34" width="10" height="12" fill="#1d4ed8"/></svg>')
    with open(os.path.join(SITE, '404.html'), 'w', encoding='utf-8') as f:
        f.write(head('페이지를 찾을 수 없습니다', '요청한 페이지가 없습니다.', BASE + '/404.html')
                + '<section class="hero"><h1>페이지를 찾을 수 없습니다</h1>'
                  '<p class="lead"><a href="/">전국 관리비 순위로 돌아가기</a></p></section>' + foot(d))

    print(f"pages: index, about, privacy, {len(d['regions'])} regions, {len(page_complexes)} complexes")
    print(f"files: {sum(len(files) for _, _, files in os.walk(SITE))}")
    print(f"urls in sitemap: {len(urls)}")


if __name__ == '__main__':
    main()
