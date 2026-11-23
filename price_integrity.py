#!/usr/bin/env python3
"""Central fail-closed publication filter for price comparisons and CSV export.

Legacy auto-discovered prices were incorrectly marked 'verified' with no unit
evidence. Never publish these just because price_verified=True.
"""
from __future__ import annotations

DOSES=('2.5','5','7.5','10','12.5','15')
AUTOMATED={'national','auto'}
ENGINE_VERSION=2

def reviewed(c):
    # Source-specific corrections were independently checked against their
    # official price tables, including explicit four-/one-pen quantities.
    return bool(c.get('price_unit_reviewed_at') or
                (c.get('source_pack_pens') and c.get('source_pack_prices')))

def trusted(c,d):
    p=c.get('prices',{}).get(d)
    if not isinstance(p,(int,float)) or p<=0:return False
    if c.get('discovery') not in AUTOMATED:return True
    if reviewed(c):return True
    if c.get('price_engine_version')!=ENGINE_VERSION:return False
    proof=c.get('price_evidence',{}).get(d)
    return (isinstance(proof,dict)
            and proof.get('amount')==p
            and proof.get('source_pens') in (1,2,4,8,12)
            and proof.get('source_amount',0)>0
            and proof.get('source_fragment')
            and proof.get('source_url')
            and proof.get('source_kind') in ('official_table','official_inline')
            and c.get('official_price_audit_status') not in ('page_unavailable','dose_price_anomaly','removed_unconfirmed'))

def published_price(c,d):
    return c.get('prices',{}).get(d) if trusted(c,d) else None

def public_catalog(cat):
    import copy
    filtered=copy.deepcopy(cat)
    for c in filtered.get('clinics',[]):
        if c.get('discovery') in AUTOMATED and not reviewed(c):
            visible={d:published_price(c,d) for d in DOSES}
            c['prices']=visible
            if not any(v is not None for v in visible.values()):
                c['price_verified']=False
                if c.get('status')=='active':c['status']='candidate'
                c['price_review_pending']=True
    return filtered

def self_test():
    base={'discovery':'national','status':'active','price_verified':True,
          'prices':{'5':18000}}
    assert not trusted(base,'5')
    assert published_price(base,'5') is None
    checked={**base,'price_engine_version':2,'price_evidence':{'5':{
        'amount':18000,'source_amount':6000,'source_pens':4,
        'source_fragment':'5mg 4本 6,000円','source_url':'https://clinic.example/price',
        'source_kind':'official_table'}}}
    assert trusted(checked,'5')
    assert not trusted({**checked,'price_evidence':{'5':{**checked['price_evidence']['5'],'amount':54000}}},'5')
    assert trusted({**base,'price_unit_reviewed_at':'2026-11-23'},'5')
    out=public_catalog({'clinics':[base]})['clinics'][0]
    assert out['status']=='candidate' and out['prices']['5'] is None
    print('Publication integrity tests passed: legacy, V2 evidence, manual review')
if __name__=='__main__':self_test()
