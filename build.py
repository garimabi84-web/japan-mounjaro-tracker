#!/usr/bin/env python3
"""Build offline-friendly HTML & CSV from evolving catalog and SNS finds."""
from pathlib import Path
import csv, io, json
ROOT=Path(__file__).resolve().parent
cat=json.loads((ROOT/'catalog.json').read_text(encoding='utf-8'))
finds=json.loads((ROOT/'discoveries.json').read_text(encoding='utf-8')) if (ROOT/'discoveries.json').exists() else {}
read=lambda x:(ROOT/x).read_text(encoding='utf-8')
def jsjson(d):return json.dumps(d,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
html=read('index.template.html').replace('__CATALOG_JSON__',jsjson(cat)).replace('__DISCOVERIES_JSON__',jsjson(finds))
# Avoid file:// import errors from standalone HTML, inline monitor snapshot (no web request)
monitor=read('monitor.js') if (ROOT/'monitor.js').exists() else ''
html=html.replace('<script src="monitor.js"></script>','<script>'+monitor+'</script>')
(ROOT/'index.html').write_text(html,encoding='utf-8')
DS=cat['doses']
cols=['병원 ID','병원명','지역','도시','외국인단기체류처방','비대면진료','일본전국배송','상태','발견경로',
      *[f'{x}mg 12펜 기본가(엔)' for x in DS], *[f'{x}mg 12펜 행사 최저가(엔)' for x in DS],
      '행사명','행사시작','행사종료','행사조건','가격산정','진찰 배송비','비고','가격공식출처','확인일']
with (ROOT/'catalog.csv').open('w',encoding='utf-8-sig',newline='') as fh:
 w=csv.writer(fh);w.writerow(cols)
 for r in cat['clinics']:
  events=r.get('events',[])
  event_vals=[min([e['prices'][x] for e in events if isinstance(e.get('prices',{}).get(x),int)],default=None) for x in DS]
  w.writerow([r['id'],r['name'],r['region'],r['city'],r['foreign'],r['online'],r['ship'],r['status'],r.get('discovery',''),
              *[r.get('prices',{}).get(x) for x in DS], *event_vals,
              ' / '.join(e['name'] for e in events), ' / '.join(e.get('start','') for e in events),
              ' / '.join(e.get('end','') for e in events), ' / '.join(e.get('conditions','') for e in events),
              r.get('basis',''),r.get('fees',''),r.get('notes',''),r.get('url',''),r.get('updated','')])
print('Built HTML+CSV:',len(cat['clinics']),'items',sum(bool(r.get('events')) for r in cat['clinics']),'with events',len(finds.get('archive',[])),'discovery hits')
