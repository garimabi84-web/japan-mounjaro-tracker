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
    # A legacy 'unit reviewed' flag is not proof for each individual dose.
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
        computed=round(round(raw*tax_factor)*12/n)
    if computed!=p:return False
    fragment=unicodedata.normalize('NFKC',quote)
    if not re.search(r'(?<![\d.])'+re.escape(d)+r'(?:\.0)?\s*mg\b',fragment,re.I):
        return False
    source_amounts={int(value.replace(',','')) for match in re.findall(
        r'(?:[¥￥]\s*([\d,]+)|([\d,]+)\s*(?:円|[¥￥]))',fragment)
        for value in match if value}
    if raw not in source_amounts:return False
    # Prevent an inherited "12 pens reviewed" label from masking monthly
    # column rates (e.g. 19,600円/月 in the 3ヶ月分 column).
    monthly=bool(re.search(r'月額|毎月|月あたり|月々|[/／]\s*月',fragment))
    if ev.get('source_type')=='3개월 계약 월액':
        if not monthly or not re.search(r'3\s*(?:ヶ?月|か月|ヵ月|カ月|ヶ月)',fragment):
            return False
    elif monthly and n>4:
        return False
    if re.search(r'約\s*[¥￥]?\s*[\d,]+\s*円|[¥￥]?[\d,]+\s*円\s*[〜～~]|\d+円\s*から',fragment):
        return False
    # Catch unit disagreement such as "5mg/4本 | ¥33,000" recorded as
    # 1 pen. This failed even the previous "verified" run.
    # An explicit "円/本" means one pen; the phrase
    # "2本ずつの販売" describes minimum purchase, NOT a 2-pen price.
    if re.search(r'円\s*[/／]\s*(?:本|ペン|キット)',fragment):
        if n!=1:return False
    source_units={int(m[1]) for m in re.finditer(
        r'(?<!\d)(1|2|4|8|12)\s*(?:本|ペン|キット)',fragment)
        if not re.match(r'\s*(?:ずつ|単位(?:で|から)?|ごと|以上|から(?:販売|処方))',
                        fragment[m.end():])}
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
        if c.get('discovery') not in AUTOMATED:continue
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
    assert published_price(reviewed_record,'5') is None, 'Review flag alone cannot bypass per-dose proof'
    eight=copy.deepcopy(checked)
    eight['price_evidence']['5'].update({'pens':8,'raw_yen':12000,'equivalent_12':18000,
                                         'quote':'5mg 8本 12,000円'})
    assert published_price(eight,'5')==18000, '8 pens must multiply by 1.5'
    wrong_dose=copy.deepcopy(checked)
    wrong_dose['price_evidence']['5']['quote']='10mg 4本 6,000円'
    assert published_price(wrong_dose,'5') is None
    wrong_yen=copy.deepcopy(checked)
    wrong_yen['price_evidence']['5']['quote']='5mg 4本 8,000円'
    assert published_price(wrong_yen,'5') is None
    yokoi_wrong=copy.deepcopy(checked)
    yokoi_wrong['price_evidence']['5'].update({
        'raw_yen':8000,'pens':2,'equivalent_12':48000,
        'quote':'5mg | 8,000円/本(税込) | 2本ずつの販売となります。'})
    yokoi_wrong['prices']['5']=48000
    assert published_price(yokoi_wrong,'5') is None, 'Minimum purchase != amount priced'
    yokoi_right=copy.deepcopy(yokoi_wrong)
    yokoi_right['price_evidence']['5'].update({
        'pens':1,'equivalent_12':96000})
    yokoi_right['prices']['5']=96000
    assert published_price(yokoi_right,'5')==96000
    femuse_wrong=copy.deepcopy(checked)
    femuse_wrong['price_evidence']['5'].update({
        'raw_yen':19600,'pens':12,'equivalent_12':19600,
        'quote':'5.0mg | 3ヶ月分 | 19,600円/月',
        'source_type':'명시된 펜·주수/기간'})
    femuse_wrong['prices']['5']=19600
    assert published_price(femuse_wrong,'5') is None, 'Monthly rate must not pass as total'
    femuse_correct=copy.deepcopy(femuse_wrong)
    femuse_correct['price_evidence']['5'].update({'equivalent_12':58800,
                                                 'source_type':'3개월 계약 월액'})
    femuse_correct['prices']['5']=58800
    assert published_price(femuse_correct,'5')==58800
    public=public_catalog({'clinics':[base]})['clinics'][0]
    assert public['status']=='candidate' and public['prices']['5'] is None
    print('All-dose public price integrity self-tests passed')
if __name__=='__main__':self_test()
