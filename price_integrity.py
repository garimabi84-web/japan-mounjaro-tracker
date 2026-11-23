#!/usr/bin/env python3
"""Single all-dose fail-closed price publication rule for HTML and CSV.

An earlier automated 'passed' audit is not enough: every displayed dose
requires its own row/quantity/price evidence from the clinic's official page.
"""
from __future__ import annotations
import copy

DOSES=('2.5','5','7.5','10','12.5','15')
AUTOMATED={'national','auto'}

def reviewed(c):
    return bool(c.get('price_unit_reviewed_at') or
                (c.get('source_pack_pens') and c.get('source_pack_prices')))

def trusted(c,d):
    p=c.get('prices',{}).get(d)
    if not isinstance(p,(int,float)) or p<=0:return False
    if c.get('discovery') not in AUTOMATED:return True
    if reviewed(c):return True
    if c.get('price_integrity')!='strict_v2':return False
    if c.get('official_price_audit_status') in ('page_unavailable','dose_price_anomaly','removed_unconfirmed'):
        return False
    ev=c.get('price_evidence',{}).get(d)
    return bool(isinstance(ev,dict) and ev.get('dose')==d
        and ev.get('equivalent_12')==p
        and ev.get('pens') in (1,2,4,8,12)
        and isinstance(ev.get('raw_yen'),int) and ev['raw_yen']>0
        and ev.get('quote') and (ev.get('source_url') or c.get('url')))

def published_price(c,d):
    return c.get('prices',{}).get(d) if trusted(c,d) else None

def public_catalog(cat):
    out=copy.deepcopy(cat)
    for c in out.get('clinics',[]):
        if c.get('discovery') not in AUTOMATED or reviewed(c):continue
        previously=[d for d in DOSES if isinstance(c.get('prices',{}).get(d),(int,float))]
        c['prices']={d:published_price(c,d) for d in DOSES}
        if previously and not any(c['prices'].values()):
            c['price_verified']=False
            if c.get('status')=='active':c['status']='candidate'
            c['price_review_pending']=True
    return out

def self_test():
    base={'discovery':'national','status':'active','price_verified':True,
          'prices':{'5':18000,'10':99000},'url':'https://clinic.example/price'}
    assert published_price(base,'5') is None
    checked={**base,'price_integrity':'strict_v2','price_evidence':{'5':{
       'dose':'5','raw_yen':6000,'pens':4,'equivalent_12':18000,
       'quote':'5mg 4本 6,000円','source_url':base['url']}}}
    assert published_price(checked,'5')==18000
    assert published_price(checked,'10') is None,'Each dose requires its OWN evidence'
    invalid=copy.deepcopy(checked);invalid['price_evidence']['5']['equivalent_12']=54000
    assert not trusted(invalid,'5'),'mismatched proof cannot publish'
    reviewed_record={**base,'price_unit_reviewed_at':'2026-11-23'}
    assert published_price(reviewed_record,'5')==18000
    public=public_catalog({'clinics':[base]})['clinics'][0]
    assert public['status']=='candidate' and public['prices']['5'] is None
    print('All-dose public price integrity self-tests passed')
if __name__=='__main__':self_test()
