#!/usr/bin/env python3
"""Stable public adapter for fail-closed 12-pen source price engine V2.

Production callers use this module; the engine stores original amount, explicit
pen quantity or three-month contract, dose and exact page excerpt per price.
"""
from price_engine_v2 import parse_official_v2, self_test as engine_self_test

def extract_with_evidence(source,source_url=''):
    prices,basis,items=parse_official_v2(source,source_url)
    proof={}
    for d,e in items.items():
        proof[d]={
            'dose':d,'raw_yen':e['source_amount'],
            'pens':e['source_pens'],'equivalent_12':e['amount'],
            'unit_label':e['source_type'],'source_kind':e['source_kind'],
            'quote':e['source_fragment'],'tax':e['tax'],
            'source_url':source_url or e.get('source_url',''),
            'source_type':e['source_type'],'method':e['method'],
        }
    return prices,proof

def extract_official(source,source_url=''):
    prices,proof=extract_with_evidence(source,source_url)
    explanation=' / '.join(
        f"{d}mg 원문 {e['raw_yen']}엔, 단위 {e['unit_label']}, 12펜 {e['equivalent_12']}엔"
        for d,e in proof.items())
    return prices,('공식 원문 제품·용량·수량·계약기간 독립 검증: '+explanation if proof else '')

def self_test():
    engine_self_test()
    test="""<h2>マンジャロ料金</h2><table>
    <tr><th>用量</th><th>4本価格</th></tr>
    <tr><td>5mg</td><td>25,000円</td></tr></table>"""
    amount,details=extract_with_evidence(test,"https://example.clinic/price")
    assert amount['5']==75000
    assert details['5']['pens']==4 and details['5']['equivalent_12']==75000
    assert details['5']['source_url']=='https://example.clinic/price'
    print('Evidence adapter and 13-case price parser regression tests passed')

if __name__=='__main__':self_test()
