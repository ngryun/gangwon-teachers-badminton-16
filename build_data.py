#!/usr/bin/env python3
"""대진표 한글 파일(.hwpx)을 읽어 data.js 를 만든다. 표준 라이브러리만 쓴다.

    python3 build_data.py 대진표.hwpx

- 종목 제목은 "[남복 40대 E]" 꼴의 문단, 그 아래 표가 조별 예선·본선 대진이다.
- 소속(학교·기관) → 지역은 regions.json 에서 읽는다. 문서에는 지역이 없으므로
  새 소속이 생기면 regions.json 에 추가한다.
- 이름이 같은 다른 학교가 함께 나온 경우(regions.json 의 split)는 선수 조합으로
  갈라 "신동초(삼척)" 처럼 지역을 붙인 이름으로 바꾼다.
"""
import json, re, sys, zipfile, collections
import xml.etree.ElementTree as ET
from pathlib import Path

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HERE = Path(__file__).resolve().parent
INFO = re.compile(r'^(?:(결승|4강|8강|16강|32강)\s+)?(\S+?)\s*(\d+)월\s*(\d+)일\s*(\d+):(\d+)\s*(\d+)코트\s*(\d+)번$')
SEED = re.compile(r'^[A-Z]\d$')


def para_text(p):
    return ''.join(''.join(t.itertext()) for run in p.findall(HP + 'run') for t in run.findall(HP + 't'))


def cell_text(tc):
    return '\n'.join(para_text(p) for sl in tc.findall(HP + 'subList') for p in sl.findall(HP + 'p'))


def read_items(hwpx):
    """문서를 위에서부터 ('p', 글) / ('tbl', 열 수, 행들) 로 편다."""
    with zipfile.ZipFile(hwpx) as z:
        root = ET.fromstring(z.read('Contents/section0.xml'))
    items = []
    for p in root.findall(HP + 'p'):
        text = para_text(p).strip()
        if text:
            items.append(('p', text))
        for run in p.findall(HP + 'run'):
            for tbl in run.findall(HP + 'tbl'):
                rows = [[cell_text(tc) for tc in tr.findall(HP + 'tc')] for tr in tbl.findall(HP + 'tr')]
                items.append(('tbl', int(tbl.get('colCnt')), rows))
    return items


def squash(s):
    return re.sub(r'\s+', '', s)


def parse_info(s):
    m = INFO.match(' '.join(s.split()))
    if not m:
        raise SystemExit(f'경기 시간 칸을 읽지 못했습니다: {s!r}')
    return {'round': m.group(1), 'venue': m.group(2), 'd': f'{int(m.group(3)):02d}-{int(m.group(4)):02d}',
            't': f'{int(m.group(5)):02d}:{m.group(6)}', 'c': int(m.group(7)), 'n': int(m.group(8))}


def parse(items):
    events, matches, notes, title = [], [], [], None
    cur = None
    for it in items:
        if it[0] == 'p':
            m = re.match(r'^\[(.+?)\]$', it[1])
            if m:
                cur = ' '.join(m.group(1).split())
                events.append(cur)
            elif title is None:
                title = it[1]
            continue
        _, ncol, rows = it
        if len(rows) == 1 and len(rows[0]) == 1:      # 대진 그림 칸 또는 안내문
            if rows[0][0].strip():
                notes.append(' '.join(rows[0][0].split()))
            continue
        if cur is None:
            raise SystemExit('종목 제목보다 표가 먼저 나왔습니다.')
        e = len(events) - 1
        if ncol == 3:                                   # 본선 대진
            for r in rows:
                d = parse_info(r[1])
                matches.append({'e': e, 'k': 1, 'r': d['round'], 'd': d['d'], 't': d['t'], 'c': d['c'], 'n': d['n'],
                                'a': squash(r[0]), 'b': squash(r[2]), 'venue': d['venue']})
            continue
        group = None                                    # 조별 예선(리그)
        if ncol == 6:
            head = rows[0][0].strip()
            if not head.startswith('Group'):
                raise SystemExit(f'[{cur}] 조 이름을 찾지 못했습니다: {head!r}')
            group, rows = head.split()[1], rows[1:]
        if len(rows) % 2:
            raise SystemExit(f'[{cur}] 표의 줄 수가 맞지 않습니다.')
        for i in range(0, len(rows), 2):
            r1, r2 = rows[i], rows[i + 1]
            if len(r1) != 5 or len(r2) != 2:
                raise SystemExit(f'[{cur}] 경기 줄 모양이 다릅니다: {r1} {r2}')
            d = parse_info(r1[2])
            matches.append({'e': e, 'k': 0, 'g': group, 'd': d['d'], 't': d['t'], 'c': d['c'], 'n': d['n'],
                            'a': squash(r1[0]), 'ap': [squash(r1[1]), squash(r2[0])],
                            'b': squash(r1[4]), 'bp': [squash(r1[3]), squash(r2[1])], 'venue': d['venue']})
    return title, events, matches, notes


def resolve_brackets(events, matches):
    """본선 칸의 'A1-E2'(A1~E2 구역 승자)를 그 구역에 드는 조 순위 목록으로 푼다."""
    by_event = collections.defaultdict(list)
    for m in matches:
        if m['k']:
            by_event[m['e']].append(m)
    for e, ms in by_event.items():
        span = {}                                       # (첫 시드, 끝 시드) → 경기
        for m in ms:
            fa, lb = m['a'].split('-')[0], m['b'].split('-')[-1]
            span[(fa, lb)] = m

        def seeds(side, depth=0):
            if SEED.match(side):
                return [side]
            first, last = side.split('-')
            src = span.get((first, last))
            if src is None or depth > 6:
                raise SystemExit(f'[{events[e]}] 본선 대진 {side} 의 앞 경기를 찾지 못했습니다.')
            return seeds(src['a'], depth + 1) + seeds(src['b'], depth + 1)

        for m in ms:
            m['as'], m['bs'] = seeds(m['a']), seeds(m['b'])


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    title, events, matches, notes = parse(read_items(sys.argv[1]))
    resolve_brackets(events, matches)

    reg = json.loads((HERE / 'regions.json').read_text(encoding='utf-8'))
    regions, unknown = dict(reg['regions']), reg.get('unknown', {})
    for name, by_region in reg.get('split', {}).items():   # 동명 학교: 선수 조합으로 가른다
        pair_region = {frozenset(pair): r for r, pairs in by_region.items() for pair in pairs}
        for m in matches:
            for s in 'ab':
                if not m['k'] and m[s] == name:
                    r = pair_region.get(frozenset(m[s + 'p']))
                    if r is None:
                        raise SystemExit(f'regions.json split 에 {name} {m[s + "p"]} 조의 지역이 없습니다.')
                    m[s] = f'{name}({r})'
                    regions[m[s]] = r
    names = sorted({m[s] for m in matches if not m['k'] for s in 'ab'})
    missing = [n for n in names if n not in regions and n not in unknown]
    if missing:
        print('※ regions.json 에 없는 소속(지역 "확인 필요"로 넣음):', ', '.join(missing))
    teams = [{'n': n, 'r': regions.get(n, ''), 'cand': unknown.get(n, [])} if n not in regions
             else {'n': n, 'r': regions[n]} for n in names]
    idx = {n: i for i, n in enumerate(names)}

    venues = sorted({m.pop('venue') for m in matches})
    for m in matches:
        if not m['k']:
            m['a'], m['b'] = idx[m['a']], idx[m['b']]
    matches.sort(key=lambda m: (m['d'], m['t'], m['c']))

    data = {'title': title, 'venue': ' · '.join(venues), 'notes': notes, 'events': events,
            'teams': teams, 'matches': matches}
    out = 'window.DATA=' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n'
    (HERE / 'data.js').write_text(out, encoding='utf-8')
    people = {(p, m[s]) for m in matches if not m['k'] for s in 'ab' for p in m[s + 'p']}
    print(f'종목 {len(events)} · 소속 {len(teams)} · 선수 {len(people)} · 경기 {len(matches)} → data.js ({len(out.encode()) // 1024}KB)')


if __name__ == '__main__':
    main()
