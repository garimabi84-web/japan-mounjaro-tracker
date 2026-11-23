#!/usr/bin/env python3
"""Persist meaningful changes between two completed discovery scans.

Use --before immediately before collectors, then --after after the collectors.
Only material changes are tracked; check timestamps and attempt counters are not.
"""
import argparse
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CAT = ROOT / 'catalog.json'
WATCH = ROOT / 'watch_state.json'
BEFORE = ROOT / '.scan_before.json'
OUTPUT = ROOT / 'scan_changes.json'
DOSES = ('2.5', '5', '7.5', '10', '12.5', '15')
# Track substantive clinic-data changes. Exclude scan timestamps/attempt counts,
# which change on a routine recheck without changing the clinic information.
META = ('foreign', 'online', 'ship', 'booking_url', 'region', 'city', 'address',
        'mode', 'fees', 'booking_method', 'booking_type', 'booking_notes',
        'url', 'official_url_hint', 'price_verified', 'price_integrity', 'official_price_audit_status', 'basis', 'notes')
META_LABELS = {
    'foreign':'외국인 처방 정보 변경', 'online':'비대면 진료 정보 변경',
    'ship':'일본 배송 정보 변경', 'booking_url':'예약 링크 변경',
    'region':'지역 변경', 'city':'도시/도도부현 변경',
    'address':'주소 변경', 'mode':'진료 방식 변경',
    'fees':'진료·배송 비용 변경', 'booking_method':'예약 방법 변경',
    'booking_type':'예약 유형 변경','booking_notes':'예약 조건 변경',
    'url':'공식/등록 원문 주소 변경','official_url_hint':'공식 홈페이지 후보 변경',
    'price_verified':'가격 검증 상태 변경',
    'price_integrity':'가격 검증 방식 변경',
    'official_price_audit_status':'공식 가격 감사 상태 변경',
    'basis':'가격 산정 근거 변경',
    'notes':'병원 추가 정보 변경'
}

def read(path, fallback=None):
    if not path.exists():
        return {} if fallback is None else fallback
    return json.loads(path.read_text(encoding='utf-8'))

def snapshot(cat, watch):
    return {
        'clinics': {x['id']: {
            'name': x.get('name',''), 'status': x.get('status',''),
            'prices': x.get('prices',{}), 'promotions': x.get('promotions',[]),
            'events': x.get('events',[]),
            'proof': {d: {k: e.get(k) for k in ('pens','raw_yen','source_url','tax')}
                      for d,e in x.get('price_evidence',{}).items() if isinstance(e,dict)},
            **{k: x.get(k,'') for k in META}
        } for x in cat.get('clinics',[])},
        'hashes': watch.get('hashes',{})
    }

def promotional_key(item):
    # A single post may publish prices for several doses.
    return (item.get('url') or item.get('source_url') or item.get('name',''),
            item.get('posted_date',''), item.get('start',''))

def promotions_index(clinic):
    result = {}
    for p in clinic.get('promotions',[]):
        for offer in p.get('offers',[]):
            dose = str(offer.get('dose',''))
            key = 'promo:' + str(promotional_key(p)) + ':' + dose
            result[key] = {
                'amount': offer.get('price_yen'),
                'units': offer.get('pens'),
                'equivalent_12': offer.get('equivalent_12'),
                'url': p.get('url') or p.get('source_url',''),
                'posted_date': p.get('posted_date',''),
                'first_seen': p.get('first_seen','')
            }
    for p in clinic.get('events',[]):
        for dose, price in p.get('prices',{}).items():
            if isinstance(price,(int,float)):
                key = 'event:' + str(promotional_key(p)) + ':' + dose
                result[key] = {'amount':price,'units':12,
                               'url':p.get('url',''),'posted_date':p.get('posted_date',''),
                               'start':p.get('start',''),'end':p.get('end','')}
    return result

def changes(before, after):
    out = []
    old, new = before['clinics'], after['clinics']
    for ident, row in new.items():
        former = old.get(ident)
        name = row.get('name') or ident
        if former is None:
            out.append({'type':'new','clinic_id':ident,'clinic':name,
                        'label':'신규 병원 후보' if row.get('status')=='candidate' else '신규 병원 등록',
                         'before':'미등록', 'after':row.get('status','등록')})
            continue
        if row.get('name') != former.get('name'):
            out.append({'type':'info','clinic_id':ident,'clinic':name,
                        'label':'병원명 변경','before':former.get('name'),
                         'after':row.get('name')})
        if row.get('status') != former.get('status'):
            out.append({'type':'verified' if row.get('status')=='active' else 'status',
                        'clinic_id':ident,'clinic':name,'label':'병원 등록/검증 상태 변경',
                         'before':former.get('status'), 'after':row.get('status')})
        for dose in DOSES:
            p=former.get('prices',{}).get(dose)
            n=row.get('prices',{}).get(dose)
            if p!=n and (p is not None or n is not None):
                out.append({'type':'price','clinic_id':ident,'clinic':name,
                            'dose':dose,'before':p,'after':n,
                            'label':f'{dose}mg 12펜 비교가 변경'})
            elif former.get('proof',{}).get(dose)!=row.get('proof',{}).get(dose):
                out.append({'type':'evidence','clinic_id':ident,'clinic':name,
                            'dose':dose,'before':former.get('proof',{}).get(dose),
                            'after':row.get('proof',{}).get(dose),
                            'label':f'{dose}mg 공식 가격 근거 변경'})
        first = promotions_index(former)
        second = promotions_index(row)
        for key, val in second.items():
            if key not in first or first[key] != val:
                out.append({'type':'promotion','clinic_id':ident,'clinic':name,
                            'dose':key.rsplit(':',1)[-1],
                            'before':first.get(key,{}).get('amount'),
                            'after':val.get('amount'),
                            'before_detail':first.get(key), 'after_detail':val,
                            'posted_date':val.get('posted_date',''),
                            'first_seen':val.get('first_seen',''),
                            'source_url':val.get('url',''),
                            'label':'홍보·이벤트 가격 추가/변경'})
        for key in META:
            if former.get(key) != row.get(key):
                out.append({'type':'info','clinic_id':ident,'clinic':name,
                            'label':META_LABELS[key],
                             'before':former.get(key), 'after':row.get(key)})
    clinic_urls = {c.get('name',''): c for c in []}  # Explicit page checks are signals, not price claims.
    rev_urls = {}
    cat = read(CAT)
    for c in cat.get('clinics',[]):
        u=c.get('url','')
        if u.startswith('https://'):
            from urllib.parse import urlsplit,urlunsplit
            sp=urlsplit(u)
            key=urlunsplit((sp.scheme,sp.netloc.lower(),sp.path.rstrip('/') or '/','',''))
            rev_urls.setdefault(key,c)
    for url, digest in after.get('hashes',{}).items():
        if url in before.get('hashes',{}) and before['hashes'][url] != digest:
            x=rev_urls.get(url,{})
            out.append({'type':'source','clinic_id':x.get('id',''),
                        'clinic':x.get('name',url),'source_url':url,
                        'label':'공식 출처 내용 변경 감지 · 가격 재확인 필요'})
    return out

def update_history(history, at, items):
    counts={kind:sum(c['type']==kind for c in items)
            for kind in ('new','verified','price','evidence','promotion','info','status','source')}
    # Store every affected clinic ID, even when the detailed change log is
    # trimmed. The row highlight must never silently miss item 251+.
    clinic_ids=list(dict.fromkeys(x['clinic_id'] for x in items if x.get('clinic_id')))
    # Never lose the explanation for a highlighted clinic after 250 events.
    by_clinic={}
    for item in items:
        if item.get('clinic_id'):
            by_clinic.setdefault(item['clinic_id'],[]).append(item)
    entry={'at':at,'total':len(items),'counts':counts,
           'clinic_ids':clinic_ids,'by_clinic':by_clinic,'items':items[:250]}
    runs=[entry]+[r for r in history.get('runs',[]) if r.get('at')!=at]
    return {'schema':2,'latest':entry,'runs':runs[:30]}

def self_test():
    a={'clinics':{'a':{'name':'테스트','status':'candidate','prices':{'10':None},'promotions':[],'events':[],'foreign':'unknown','online':'unknown','ship':'unknown','booking_url':''}},'hashes':{}}
    b={'clinics':{'a':{'name':'테스트','status':'active','prices':{'10':120000},
      'promotions':[{'url':'https://x.com/test/1','posted_date':'2026-11-21','offers':[{'dose':'10','pens':12,'price_yen':98000,'equivalent_12':98000}]}],
      'events':[],'foreign':'unknown','online':'unknown','ship':'unknown','booking_url':''}},'hashes':{}}
    types={x['type'] for x in changes(a,b)}
    assert {'verified','price','promotion'} <= types, types
    h=update_history({},'2026-11-21T12:00:00+09:00',changes(a,b))
    assert h['latest']['total'] == 3 and len(h['runs']) == 1
    assert h['latest']['clinic_ids'] == ['a'],h['latest']['clinic_ids']
    meta_before=snapshot({'clinics':[{'id':'x','name':'병원','region':'미확인',
        'status':'active','prices':{},'notes':'초기 확인'}]},{}).get('clinics')
    meta_after=snapshot({'clinics':[{'id':'x','name':'병원','region':'규슈',
        'status':'active','prices':{},'notes':'추가 안내'}]},{}).get('clinics')
    meta_changes=changes({'clinics':meta_before,'hashes':{}},
                         {'clinics':meta_after,'hashes':{}})
    assert len(meta_changes)==2 and all(x['type']=='info' for x in meta_changes),meta_changes
    many=[{'type':'new','clinic_id':f'id-{n}','clinic':f'병원 {n}'} for n in range(275)]
    overflow=update_history({},'2026-11-21T13:00:00+09:00',many)
    assert len(overflow['latest']['items'])==250
    assert len(overflow['latest']['clinic_ids'])==275
    assert len(overflow['latest']['by_clinic'])==275
    assert overflow['latest']['by_clinic']['id-274'][0]['clinic']=='병원 274'
    cleared=update_history(overflow,'2026-11-21T13:10:00+09:00',[])
    assert cleared['latest']['clinic_ids']==[] and cleared['latest']['total']==0
    detailed=changes({'clinics':{'p':{'name':'가격병원','status':'active','prices':{'5':75000},'promotions':[],'events':[], 'notes':'기존'}},'hashes':{}},
                     {'clinics':{'p':{'name':'가격병원','status':'active','prices':{'5':90000},'promotions':[],'events':[], 'notes':'수정'}},'hashes':{}})
    assert any(x['type']=='price' and x['before']==75000 and x['after']==90000 for x in detailed)
    assert any(x['type']=='info' and x['before']=='기존' and x['after']=='수정' for x in detailed)
    print('scan change self-test passed')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--before',action='store_true')
    p.add_argument('--after',action='store_true')
    p.add_argument('--self-test',action='store_true')
    args=p.parse_args()
    if args.self_test:
        self_test()
        return
    if args.before:
        BEFORE.write_text(json.dumps(snapshot(read(CAT),read(WATCH)),ensure_ascii=False),encoding='utf-8')
        print('Previous scan state recorded')
        return
    if not args.after or not BEFORE.exists():
        raise SystemExit('Use --before then --after in one workflow run')
    old=read(BEFORE)
    new=snapshot(read(CAT),read(WATCH))
    items=changes(old,new)
    discoveries=read(ROOT/'discoveries.json')
    at=discoveries.get('ran_at') or dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec='seconds')
    history=read(OUTPUT)
    if any(run.get('at')==at for run in history.get('runs',[])):
        # A price-only audit can rerun without an actual discovery crawl.
        # No-op audits must not erase yellow highlights from the last scan.
        if not items:
            print('No additional changes; preserving last real scan history')
            return
        # Keep material audit changes separate from the older crawl.
        at=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec='microseconds')
    result=update_history(history,at,items)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Scan changes:',json.dumps(result['latest']['counts'],ensure_ascii=False))

if __name__=='__main__':
    main()
