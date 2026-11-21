#!/usr/bin/env python3
"""Build offline-friendly HTML & CSV from evolving catalog and SNS finds."""
from pathlib import Path
import csv, io, json
ROOT=Path(__file__).resolve().parent
cat=json.loads((ROOT/'catalog.json').read_text(encoding='utf-8'))
finds=json.loads((ROOT/'discoveries.json').read_text(encoding='utf-8')) if (ROOT/'discoveries.json').exists() else {}
changes=json.loads((ROOT/'scan_changes.json').read_text(encoding='utf-8')) if (ROOT/'scan_changes.json').exists() else {}
national=json.loads((ROOT/'national_discovery.json').read_text(encoding='utf-8')) if (ROOT/'national_discovery.json').exists() else {}
read=lambda x:(ROOT/x).read_text(encoding='utf-8')
def jsjson(d):return json.dumps(d,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
html=read('index.template.html').replace('__CATALOG_JSON__',jsjson(cat)).replace('__DISCOVERIES_JSON__',jsjson(finds)).replace('__CHANGES_JSON__',jsjson(changes)).replace('__NATIONAL_JSON__',jsjson(national))
# Avoid file:// import errors from standalone HTML, inline monitor snapshot (no web request)
monitor=read('monitor.js') if (ROOT/'monitor.js').exists() else ''
html=html.replace('<script src="monitor.js"></script>','<script>'+monitor+'</script>')
(ROOT/'index.html').write_text(html,encoding='utf-8')
DS=cat['doses']
cols=['병원 ID','병원명','지역','도시','외국인단기체류처방','비대면진료','일본전국배송','상태','발견경로',
      *[f'{x}mg 12펜 기본가(엔)' for x in DS], *[f'{x}mg 12펜 행사 최저가(엔)' for x in DS],
      '행사명','행사시작','행사종료','행사조건','가격산정','진찰 배송비','예약 방법','예약 링크 종류','예약 페이지','예약 유의사항','예약 확인일','비고','가격공식출처','확인일', *[f'{x}mg 12펜 홍보가(엔)' for x in DS], '홍보물 게시일','홍보물 발견일','홍보물 출처']
with (ROOT/'catalog.csv').open('w',encoding='utf-8-sig',newline='') as fh:
 w=csv.writer(fh);w.writerow(cols)
 for r in cat['clinics']:
  events=r.get('events',[])
  event_vals=[min([e['prices'][x] for e in events if isinstance(e.get('prices',{}).get(x),int)],default=None) for x in DS]
  promo=[]
  for p in r.get('promotions',[]):
   for offer in p.get('offers',[]):
    promo.append((str(offer.get('dose','')),offer.get('equivalent_12'),p))
  cheapest_promo=[min((val for dose,val,p in promo if dose==d and isinstance(val,int)),default=None) for d in DS]
  w.writerow([r['id'],r['name'],r['region'],r['city'],r['foreign'],r['online'],r['ship'],r['status'],r.get('discovery',''),
              *[r.get('prices',{}).get(x) for x in DS], *event_vals,
              ' / '.join(e['name'] for e in events), ' / '.join(e.get('start','') for e in events),
              ' / '.join(e.get('end','') for e in events), ' / '.join(e.get('conditions','') for e in events),
              r.get('basis',''),r.get('fees',''),r.get('booking_method',''),r.get('booking_type',''),r.get('booking_url',''),r.get('booking_notes',''),r.get('booking_checked',''),r.get('notes',''),r.get('url',''),r.get('updated',''),*cheapest_promo,
              ' / '.join(p.get('posted_date','') or '게시일 미확인' for d,v,p in promo),
              ' / '.join(str(p.get('first_seen',''))[:10] for d,v,p in promo),
              ' / '.join(p.get('url','') for d,v,p in promo)])
print('Built HTML+CSV:',len(cat['clinics']),'items',sum(bool(r.get('events')) for r in cat['clinics']),'with events',len(finds.get('archive',[])),'discovery hits')
