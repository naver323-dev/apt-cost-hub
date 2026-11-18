"""Download the K-apt weekly public files (관리비정보 + 면적정보).

K-apt's 자료실 (board seq 21 = 관리비, seq 20 = 면적) publishes one XLSX each week
for every 관리비 공개의무단지. Downloads need the site session that the board page
sets (the "정상적인 접근이 아닙니다" guard), so this walks the same flow a browser
does: main page -> board view -> file list JSON -> file download. No account, no
API key, 공공데이터포털 이용허락범위 제한 없음.

Writes:
  data/raw/kapt_fee.xlsx    관리비정보
  data/raw/kapt_area.xlsx   면적정보
  data/raw/kapt_meta.json   {"snapshot_date": "YYYY-MM-DD", "files": {...}}
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = 'https://www.k-apt.go.kr'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, 'data', 'raw')

BOARDS = [('21', 'kapt_fee.xlsx'), ('20', 'kapt_area.xlsx')]


def opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def get(op, url, referer=None, retries=3):
    headers = {'User-Agent': UA, 'Accept-Language': 'ko-KR,ko;q=0.9'}
    if referer:
        headers['Referer'] = referer
    last = None
    for i in range(retries):
        try:
            with op.open(urllib.request.Request(url, headers=headers), timeout=120) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - retry any transport error
            last = e
            time.sleep(2 + i * 3)
    raise last


def post_json(op, url, payload, referer, csrf):
    headers = {'User-Agent': UA, 'Referer': referer,
               'Content-Type': 'application/json;charset=UTF-8',
               'X-Requested-With': 'XMLHttpRequest',
               'Accept': 'application/json, text/javascript, */*; q=0.01'}
    if csrf:
        headers['X-CSRF-TOKEN'] = csrf
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method='POST')
    with op.open(req, timeout=120) as r:
        return r.read().decode('utf-8', 'replace')


def fetch_board(op, seq):
    get(op, BASE + '/web/main/index.do')
    view = (f'{BASE}/web/board/webReference/boardView.do?seq={seq}&boardSecret=0'
            f'&boardType=03&pageNo=1&keyword=&board_pwd=&scodeT=03')
    html = get(op, view, referer=BASE + '/web/board/webReference/boardList.do?boardType=03').decode('utf-8', 'replace')
    m = re.search(r'name="_csrf" content="([^"]+)"', html) or re.search(r'name="_csrf" value="([^"]+)"', html)
    csrf = m.group(1) if m else ''
    title = re.search(r'<p class="headLine">\s*(.*?)\s*</p>', html, re.S)
    payload = {'boardType': '03', 'pageNo': '1', 'stype': '', 'keyword': '', 'seq': seq,
               'scode': '03', 'boardPwd': '', '_csrf': csrf}
    raw = post_json(op, BASE + '/web/board/webReference/fileListData.do?seq=BOARD_FILE', payload, view, csrf)
    data = json.loads(raw)
    if data.get('code') != 'SCC':
        raise SystemExit(f'K-apt file list failed for board {seq}: {raw[:200]}')
    files = data['data']
    if not files:
        raise SystemExit(f'K-apt board {seq} has no files')
    item = files[0]
    url = (f"{BASE}/cmm/file/BOARD/fileDownload.do?key={item['seq']}"
           f"&fileName={urllib.parse.quote(item['fileName'])}")
    blob = get(op, url, referer=view)
    return item['fileName'], blob, (title.group(1) if title else '')


def main():
    os.makedirs(RAW, exist_ok=True)
    op = opener()
    meta = {'files': {}}
    for seq, target in BOARDS:
        name, blob, title = fetch_board(op, seq)
        if len(blob) < 100_000 or not blob.startswith(b'PK'):
            raise SystemExit(f'unexpected payload for board {seq}: {len(blob)} bytes')
        path = os.path.join(RAW, target)
        with open(path, 'wb') as f:
            f.write(blob)
        m = re.match(r'(\d{8})_', name)
        snap = f'{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}' if m else None
        if snap:
            meta['snapshot_date'] = snap
        meta['files'][target] = {'board': seq, 'fileName': name, 'bytes': len(blob), 'title': title}
        print(f'{target}: {name} ({len(blob):,} bytes)')
        time.sleep(2)
    if 'snapshot_date' not in meta:
        raise SystemExit('could not read the snapshot date from the K-apt file name')
    with open(os.path.join(RAW, 'kapt_meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print('snapshot_date', meta['snapshot_date'])


if __name__ == '__main__':
    sys.exit(main())
