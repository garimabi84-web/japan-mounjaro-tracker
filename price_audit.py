#!/usr/bin/env python3
"""Reaudit automatic official prices; revoke cross-drug / incorrect unit matches.

Runs after candidate verification on every scan. Only independent official
webpage evidence may restore a revoked 12-pen price. Source access errors
are recorded separately from proof that a price was wrongly extracted.
"""
from __future__ import annotations
import argparse, concurrent.futures, json, re
from pathlib import Path
import requests
from discover import CATALOG, UA, now
from strict_price_parser import extract_with_evidence, self_test as strict_self_test
from enrich_official import official_host

ROOT=Path(__file__).resolve().parent
DOSES=('2.5','5','7.5','10','12.5','15')
AUDIT=ROOT/'price_audit.json'

def suspicious(prices):
    """Flag dose sequences which require manual unit/product review."""
    ordered=[(float(d),d,v) for d,v in prices.items() if d in DOSES and isinstance(v,(int,float)) and v>0]
    ordered.sort()
    problems=[]
    for a,b in zip(ordered,ordered[1:]):
        if b[2]<a[2]*0.78:
            problems.append(f'{b[1]}mg {b[2]} < {a[1]}mg {a[2]} (possible unit/product mismatch)')
    return problems

def automatic(c):
    previously_verified=(c.get('status')=='active' and c.get('price_verified') is True)
    previously_rejected=(c.get('status')=='candidate' and c.get('official_price_audit_status')
                         in ('removed_unconfirmed','dose_price_anomaly'))
    return ((previously_verified or previously_rejected)
            # Independently checked pack-price cases are already source-reviewed.
            and not c.get('price_unit_reviewed_at')
            and not (c.get('source_pack_pens') and c.get('source_pack_prices'))
            and c.get('discovery') in ('national','auto')
            and (c.get('official_domain') or c.get('official_url_hint')))

def source_url(c):
    url=c.get('url','')
    if url.startswith('https://') and official_host(url)==official_host('https://'+c.get('official_domain','') if c.get('official_domain') else c.get('official_url_hint','')):
        return url
    return c.get('official_url_hint','')

def inspect(c):
    url=source_url(c)
    if not url.startswith('https://'):return c['id'],{'status':'no_valid_official_url'}
    try:
        r=requests.get(url,headers={'User-Agent':UA,'Accept-Language':'ja,ko;q=0.8'},timeout=(4,12))
        if not r.ok or len(r.content)>1_000_000 or official_host(r.url)!=official_host(url):
            return c['id'],{'status':'unavailable','http':r.status_code}
        prices,evidence=extract_with_evidence(r.content,r.url)
        return c['id'],{'status':'checked','prices':prices,'evidence':evidence,
                         'basis':'독립 증거검증: 원문 단위·용량·금액 확인','url':r.url,
                         'anomalies':suspicious(prices)}
    except requests.RequestException as e:
        return c['id'],{'status':'unavailable','error':str(e)[:120]}

def correct_one(c,outcome):
    if outcome.get('status')!='checked':
        c['official_price_audit_status']='page_unavailable'
        # A network outage is NOT proof of bad pricing. Keep the raw amount
        # for later verification; the UI/CSV must not rank it without V2 proof.
        return 'unavailable'
    prices=outcome.get('prices',{})
    old={d:v for d,v in c.get('prices',{}).items() if isinstance(v,(int,float))}
    if not prices:
        # No *machine-verifiable* unit evidence does not mean the clinic
        # does not sell Mounjaro; retain it as a discovery lead.
        c['prices']={d:None for d in DOSES}
        c['status']='candidate';c['price_verified']=False
        c['basis']='병원 공식 페이지에서 용량별 수량·계약 기간·금액을 안전하게 대응시키지 못함'
        c['notes']='처방 중단 판단이 아니라 가격 자동검증 보류. 실제 공식 판매표는 개별 확인 필요.'
        c['official_price_audit_status']='removed_unconfirmed'
        c['price_integrity']='unverified'
        c['price_evidence']={}
        c['updated']=now()[:10]
        return 'removed'
    if outcome.get('anomalies'):
        c['prices']={d:None for d in DOSES}
        c['status']='candidate';c['price_verified']=False
        c['basis']='공식 가격 추출에서 용량별 비정상 가격 관계 발견; 수동 검증 전 가격 보류'
        c['notes']=' / '.join(outcome['anomalies'])[:400]
        c['official_price_audit_status']='dose_price_anomaly'
        c['price_integrity']='unverified'
        c['price_evidence']={}
        c['updated']=now()[:10]
        return 'anomaly'
    c['prices']={d:prices.get(d) for d in DOSES}
    c['status']='active';c['price_verified']=True
    c['basis']=outcome['basis']+'; 12펜 환산 근거는 price_evidence에 용량별 저장'
    c['price_integrity']='strict_v2'
    c['price_evidence']=outcome.get('evidence',{})
    c['official_price_audit_status']='passed'
    c['official_price_audited_at']=now()
    c['url']=outcome['url']
    if old!=prices:c['updated']=now()[:10]
    return 'corrected' if old!=prices else 'passed'

def self_test():
    mismatched={'id':'wrong','status':'active','price_verified':True,'discovery':'national',
      'prices':{'5':97500,'7.5':117000,'10':33000},'official_domain':'sanage-clinic.com'}
    assert suspicious(mismatched['prices'])
    assert correct_one(mismatched,{'status':'checked','prices':{}})=='removed'
    assert mismatched['status']=='candidate' and not any(v for v in mismatched['prices'].values())
    valid={'id':'valid','status':'active','price_verified':True,'discovery':'auto',
      'prices':{'5':99000,'10':115000},'official_domain':'example.com'}
    assert correct_one(valid,{'status':'checked','prices':{'5':99000,'10':135000},
         'basis':'공식 가격', 'url':'https://example.com/prices','anomalies':[]})=='corrected'
    assert valid['prices']['10']==135000 and valid['prices']['7.5'] is None
    assert valid['price_integrity']=='strict_v2'
    reviewed={'status':'active','price_verified':True,'discovery':'national',
              'official_domain':'femuse-clinic.jp',
              'price_unit_reviewed_at':'2026-11-23T18:00:00+09:00'}
    assert not automatic(reviewed), 'unit-reviewed prices must not be overwritten by generic audit'
    zep='<h3>ゼップバウンド</h3><p>マンジャロと同成分</p><p>10mg（1ヶ月分）33,000円</p>'
    assert extract_with_evidence(zep)[0]=={}
    strict_self_test()
    print('Price audit self-tests passed: strict independent price units and product scope')

def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true')
    p.add_argument('--limit',type=int,default=300)
    args=p.parse_args()
    if args.self_test:return self_test()
    cat=json.loads(CATALOG.read_text(encoding='utf-8'))
    candidates=[x for x in cat['clinics'] if automatic(x)]
    candidates.sort(key=lambda c:(c.get('official_price_audited_at',''),c.get('official_checked_at','')))
    chosen=candidates[:max(0,min(args.limit,500))]
    results={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        for ident,outcome in pool.map(inspect,chosen):results[ident]=outcome
    counter={};review=[]
    for c in chosen:
        outcome=results.get(c['id'],{'status':'unavailable'})
        status=correct_one(c,outcome)
        counter[status]=counter.get(status,0)+1
        if status in ('removed','anomaly','corrected'):
            review.append({'name':c['name'],'id':c['id'],'status':status,
                           'url':source_url(c),'message':c.get('notes','') if status!='corrected' else '가격 재확인 후 갱신'})
            print('PRICE AUDIT:',status,c['name'],outcome.get('prices',{}),flush=True)
    CATALOG.write_text(json.dumps(cat,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    AUDIT.write_text(json.dumps({'at':now(),'checked':len(chosen),'result':counter,'review':review},
                              ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PRICE AUDIT RESULT:',json.dumps({'checked':len(chosen),'outcomes':counter},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
