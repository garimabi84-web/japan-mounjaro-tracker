#!/usr/bin/env python3
"""Single all-dose fail-closed price publication rule for HTML and CSV.

An earlier automated 'passed' audit is not enough: every displayed dose
requires its own row/quantity/price evidence from the clinic's official page.
"""
from __future__ import annotations
import copy
import re
import unicodedata

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
    if not isinstance(ev,dict):return False
    n=ev.get('pens');raw=ev.get('raw_yen');quote=ev.get('quote','')
    if (ev.get('dose')!=d or ev.get('equivalent_12')!=p or n not in (1,2,4,8,12)
        or not isinstance(raw,int) or raw<=0 or not quote
        or not (ev.get('source_url') or c.get('url'))):return False
    # Independent math sanity check: the scanner is not allowed to claim a
    # 12-pen amount unrelated to its own original price and explicit units.
    tax_factor=1.1 if ev.get('tax')=='세전 가격에 소비세 10% 가산' else 1
    if ev.get('source_type')=='3개월 계약 월액':
        computed=round(raw*tax_factor)*3
    else:
        computed=round(raw*tax_factor)*(12//n)
    if computed!=p:return False
    fragment=unicodedata.normalize('NFKC',quote)
    if re.search(r'約\s*[¥￥]?\s*[\d,]+\s*円|[¥￥]?[\d,]+\s*円\s*[〜～~]|\d+円\s*から',fragment):
        return False
    # Catch unit disagreement such as "5mg/4本 | ¥33,000" recorded as
    # 1 pen. This failed even the previous "verified" run.
    source_units={int(v) for v in re.findall(r'(?<!\d)(1|2|4|8|12)\s*(?:本|ペン|キット)',fragment)}
    source_units.update(int(v)*4 for v in re.findall(
        r'(?<!\d)(1|2|3)\s*(?:ヶ月|か月|ヵ月|カ月)\s*分?',fragment))
    if source_units and (len(source_units)!=1 or n not in source_units):
        return False
    return True

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
    wrong_pack=copy.deepcopy(checked)
    wrong_pack['price_evidence']['5']['quote']='5mg/4本 | ¥6,000'
    wrong_pack['price_evidence']['5']['pens']=1
    wrong_pack['price_evidence']['5']['equivalent_12']=18000
    assert not trusted(wrong_pack,'5'),'quantity conflict must be rejected'
    starting=copy.deepcopy(checked)
    starting['price_evidence']['5']['quote']='5mg(1ヶ月分) 約6,000円〜'
    assert not trusted(starting,'5'),'approximate starting price cannot be published'
    reviewed_record={**base,'price_unit_reviewed_at':'2026-11-23'}
    assert published_price(reviewed_record,'5')==18000
    public=public_catalog({'clinics':[base]})['clinics'][0]
    assert public['status']=='candidate' and public['prices']['5'] is None
    print('All-dose public price integrity self-tests passed')
if __name__=='__main__':self_test()
