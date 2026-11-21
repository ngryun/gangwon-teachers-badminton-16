#!/usr/bin/env python3
"""페이스콕 대진 페이지에서 예선 점수·조 순위·본선 대진을 읽어 results.js 를 만든다.

    python3 fetch_results.py            # 페이스콕에서 받아 온다(종목마다 1초씩 쉰다)
    python3 fetch_results.py --from 폴더  # 받아 둔 HTML 로 다시 만든다
    python3 fetch_results.py --save 폴더  # 받은 HTML 을 폴더에도 남긴다

- data.js(대진표)와 날짜·시각·코트로 짝을 맞춘다. 짝이 안 맞으면 알려 주고 그 경기는 뺀다.
- 사람이 필요할 때 한 번씩 돌리는 용도다. 자동으로 되풀이해 돌리지 않는다.
- 표준 라이브러리만 쓴다.
"""
import html, json, re, sys, time, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
GA_ID = 4395
BASE = 'https://www.facecock.co.kr'
INDEX = BASE + '/page/?pid=game_schedule&ga_id=%d&ga_type=%%s' % GA_ID
PAGE = INDEX + '&bg_id=%s'
HEAD = re.compile(r'(\d+)월\s*(\d+)일(?:&nbsp;|\s)*(\d+):(\d+).*?>(\d+)</span>코트.*?>(\d+)</span>번', re.S)


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (schedule viewer; one-off fetch)'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:                       # 잠깐 끊기는 일이 있어 두 번 더 해 본다
            err = e
            time.sleep(3)
    raise SystemExit(f'받지 못했습니다: {url} ({err})')


def text(s):
    return html.unescape(re.sub(r'<[^>]+>', ' ', s)).split()


def side(td):
    seed = re.search(r'<strong>(.*?)</strong>', td, re.S)
    names = [''.join(text(p)) for p in re.findall(r'<p[^>]*>(.*?)</p>', td, re.S) if '<strong>' not in p]
    return (''.join(text(seed.group(1))) if seed else None), [n for n in names if n]


def parse_matches(chunk):
    """<thead>머리(날짜·시각·코트)</thead><tr>경기 줄</tr> 묶음들을 읽는다."""
    out = []
    for block in chunk.split('<thead>')[1:]:
        h = HEAD.search(block.split('</thead>')[0])
        row = re.search(r'</thead>\s*<tr[^>]*>(.*?)</tr>', block, re.S)
        if not h or not row:
            continue
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row.group(1), re.S)
        if len(tds) != 5:
            continue
        mo, da, hh, mi, court, _no = h.groups()
        rnd = re.search(r'label-indigo[^>]*>(.*?)</span>', tds[2], re.S)
        state = re.search(r'label-red[^>]*>(.*?)</span>', tds[2], re.S)
        sa, sb = (int(''.join(text(tds[i])) or 0) for i in (1, 3))
        seed_a, names_a = side(tds[0])
        seed_b, names_b = side(tds[4])
        out.append({'key': f'{int(mo):02d}-{int(da):02d}|{int(hh):02d}:{mi}|{int(court)}',
                    'round': ''.join(text(rnd.group(1))) if rnd else None,
                    'done': bool(state) and ''.join(text(state.group(1))) == '기록',
                    'a': names_a, 'b': names_b, 'seed_a': seed_a, 'seed_b': seed_b, 's': [sa, sb]})
    return out


def parse_page(s):
    start = s.find('panel-group accordion-default')
    ko_from = s.find('game_tourna.html')
    ko = parse_matches(s[ko_from:start]) if 0 <= ko_from < start else []
    groups = []
    for panel in s[start:].split('<div class="panel panel-default">')[1:]:
        rows = []
        tbody = re.search(r'<table class="table table-bordered">.*?<tbody>(.*?)</tbody>', panel, re.S)
        for tr in re.findall(r'<tr>(.*?)</tr>', tbody.group(1) if tbody else '', re.S):
            tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
            if len(tds) < 7:
                continue
            who = [re.match(r'(.*?)(?:\[(.*)\])?$', ''.join(text(x))) for x in tds[0].split('<br>')]
            nums = [int(''.join(text(t)) or 0) for t in tds[1:7]]
            rows.append({'p': [w.group(1) for w in who if w and w.group(1)], 'r': nums[0], 'w': nums[1], 'l': nums[2],
                         'pf': nums[3], 'pa': nums[4]})
        groups.append({'rows': rows, 'matches': parse_matches(panel)})
    return ko, groups


def main():
    args = sys.argv[1:]
    src = Path(args[args.index('--from') + 1]) if '--from' in args else None
    save = Path(args[args.index('--save') + 1]) if '--save' in args else None
    if save:
        save.mkdir(parents=True, exist_ok=True)

    def page(name, url):
        if src:
            return (src / name).read_text(encoding='utf-8', errors='replace')
        body = get(url)
        if save:
            (save / name).write_text(body, encoding='utf-8')
        time.sleep(1)
        return body

    data = json.loads((HERE / 'data.js').read_text(encoding='utf-8')[len('window.DATA='):].rstrip().rstrip(';'))
    events, teams = data['events'], data['teams']
    mine = {f"{m['d']}|{m['t']}|{m['c']}": m for m in data['matches']}

    pages = []
    for ga_type in 'MF':
        idx = page(f'{ga_type}.html', INDEX % ga_type)
        ids = list(dict.fromkeys(re.findall(r'ga_type=%s&bg_id=(\d+)"' % ga_type, idx)))
        if not ids:
            raise SystemExit(f'{ga_type} 종목 목록을 찾지 못했습니다. 페이지 모양이 바뀐 것 같습니다.')
        for bg in ids:
            pages.append((ga_type, bg, page(f'{ga_type}_{bg}.html', PAGE % (ga_type, bg))))

    res_m, res_k, res_st, warn, seen = {}, {}, {}, [], set()
    for ga_type, bg, body in pages:
        ko, groups = parse_page(body)
        for g in groups:
            ev = grp = None
            for fm in g['matches']:
                m = mine.get(fm['key'])
                if m is None or m['k']:
                    warn.append(f'{bg}: 예선 {fm["key"]} 가 대진표에 없습니다'); continue
                seen.add(fm['key'])
                ev, grp = m['e'], m.get('g') or ''
                if set(fm['a']) == set(m['ap']) and set(fm['b']) == set(m['bp']):
                    s = fm['s']
                elif set(fm['a']) == set(m['bp']) and set(fm['b']) == set(m['ap']):
                    s = fm['s'][::-1]
                else:
                    warn.append(f'{events[m["e"]]} {fm["key"]}: 선수가 다릅니다 (페이스콕 {fm["a"]} / {fm["b"]})'); continue
                if fm['done']:
                    res_m[fm['key']] = s
            if ev is not None and g['rows']:
                res_st[f'{ev}|{grp}'] = g['rows']
        for fm in ko:
            m = mine.get(fm['key'])
            if m is None or not m['k']:
                warn.append(f'{bg}: 본선 {fm["key"]} 가 대진표에 없습니다'); continue
            seen.add(fm['key'])
            if (fm['seed_a'], fm['seed_b']) == (m['a'], m['b']):
                a, b, s = fm['a'], fm['b'], fm['s']
            elif (fm['seed_a'], fm['seed_b']) == (m['b'], m['a']):
                a, b, s = fm['b'], fm['a'], fm['s'][::-1]
            else:
                warn.append(f'{events[m["e"]]} {fm["key"]}: 본선 자리가 다릅니다 ({fm["seed_a"]} / {fm["seed_b"]})'); continue
            if a or b or fm['done']:
                res_k[fm['key']] = {'a': a, 'b': b, **({'s': s} if fm['done'] else {})}

    missing = [k for k in mine if k not in seen]
    if missing:
        warn.append(f'페이스콕에서 찾지 못한 경기 {len(missing)}건: {missing[:5]}')
    now = datetime.now(timezone(timedelta(hours=9)))
    out = {'at': now.strftime('%Y-%m-%d %H:%M'), 'src': BASE + '/page/?pid=game_schedule&ga_id=%d' % GA_ID,
           'm': res_m, 'k': res_k, 'st': res_st}
    if not src:
        (HERE / 'results.js').write_text('window.RESULTS=' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n', encoding='utf-8')
    else:                                              # 받아 둔 파일로 만들 때는 받은 시각을 알 수 없어 그대로 둔다
        old = HERE / 'results.js'
        at = re.search(r'"at":"([^"]+)"', old.read_text(encoding='utf-8')).group(1) if old.exists() else out['at']
        out['at'] = at
        old.write_text('window.RESULTS=' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n', encoding='utf-8')
    done_k = sum(1 for v in res_k.values() if 's' in v)
    filled = sum(1 for v in res_k.values() if v['a'] and v['b'])
    print(f'종목 {len(pages)} · 예선 점수 {len(res_m)}/{sum(1 for m in mine.values() if not m["k"])} · '
          f'본선 대진 확정 {filled}/{sum(1 for m in mine.values() if m["k"])} (끝난 경기 {done_k}) · 조 순위 {len(res_st)}개 → results.js')
    for w in warn:
        print('※', w)


if __name__ == '__main__':
    main()
