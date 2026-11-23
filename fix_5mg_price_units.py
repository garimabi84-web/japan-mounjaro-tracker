#!/usr/bin/env python3
"""Correct seven 5mg leaderboard clinics from independently verified official price tables.

The comparator is for 12 weekly pens, NOT one pen, a four-pen box or the
monthly installment of a six-/twelve-month subscription. See evidence:
https://asahina-clinic.jp/index.html
https://haab.clinic/menu/diet/
https://femuse-clinic.jp/price/
https://digital-clinic.life/online/diet/
https://ikegaki-hifuka.com/%E6%96%99%E9%87%91%E8%A1%A8
https://himejiekimae-clinic.com/diet.html
https://kobe-ed-corona.jp/diet.html
Prices checked 2026-11-23; exclude visit fees and shipping unless stated.
"""
import argparse
import datetime
import json
from pathlib import Path
from scan_changes import snapshot, changes, update_history

ROOT=Path(__file__).resolve().parent
CATALOG=ROOT/'catalog.json'
HISTORY=ROOT/'scan_changes.json'
DOSES=('2.5','5','7.5','10','12.5','15')
JST=datetime.timezone(datetime.timedelta(hours=9))

SOURCES={
 # A bare weekly-injection price, clinic says 12 pens maximum/prescription.
 'national-74496af43d6b1b':{
  'name':'朝比奈クリニック','url':'https://asahina-clinic.jp/index.html',
  'four_or_one':'1펜 가격 × 12','raw':{'2.5':3300,'5':5500,'7.5':7700},'factor':12,
  'condition':'1회 주사/1펜 단가 환산. 초진 진찰·검사료 별도, 검사 결과 후 처방, 우편 배송 불가'},
 # HAAB 5mg ¥12,000 is per pen, two pen minimum purchase.
 'national-bc39c46aff3977':{
  'name':'ＨＡＡＢエッグクリニック','url':'https://haab.clinic/menu/diet/',
  'four_or_one':'1펜 가격 × 12','raw':{'2.5':7000,'5':12000,'7.5':15000},'factor':12,
  'condition':'공식표의 각 주사 1펜 가격. 2펜 단위부터 구매 가능, 12펜 일괄 구매 조건 미확인'},
 # Three-month subscription price is a monthly installment, not the 6mo tier.
 'national-5a0014ff50fb32':{
  'name':'フェミューズクリニック','url':'https://femuse-clinic.jp/price/',
  'four_or_one':'3개월 구독 월액 × 3','raw':{'2.5':11200,'5':19600,'7.5':28000},'factor':3,
  'condition':'3개월분 열의 월액을 3배. 6개월분 열의 월액 ¥18,900(5mg)은 3개월 구매가 아님. 진찰·배송비 별도'},
 # Explicit 3-month total incl consumption tax, not 12-month plan's tax-exclusive monthly payment.
 'national-3ba16144280470':{
  'name':'デジタルクリニック　渋谷院','url':'https://digital-clinic.life/online/diet/',
  'four_or_one':'3개월 정기 계약 세금 포함 합계','raw':{'2.5':78375,'5':156123},'factor':1,
  'condition':'공식표 3개월 정기 합계(税込). 12개월 정기의 월액 ¥39,840(세전)은 12펜 가격이 아님'},
 # Explicit per-pen and four-pen price: use four-pen bundle (tax included).
 'national-af1c31d0f63e16':{
  'name':'いけがき皮膚科','url':'https://ikegaki-hifuka.com/%E6%96%99%E9%87%91%E8%A1%A8',
  'four_or_one':'4펜(税込) 가격 × 3','raw':{'2.5':15000,'5':25200,'7.5':33600},'factor':3,
  'condition':'공식표의 GLP-1 4본 세금 포함 가격 ×3. 초진·재진비 별도'},
 'national-f35b616276017d':{
  'name':'姫路駅前糖尿病内科・認知症クリニック','url':'https://himejiekimae-clinic.com/diet.html',
  'four_or_one':'4회분(1개월) 가격 × 3','raw':{'2.5':22000,'5':44000,'7.5':66000},'factor':3,
  'condition':'공식표 4회(1개월) 가격 × 3. BMI·초진검사 및 처방 기간 조건 별도 확인'},
 'national-a44a974e3df021':{
  'name':'神戸元町呼吸器内科・アレルギークリニック','url':'https://kobe-ed-corona.jp/diet.html',
  'four_or_one':'4회분(1개월) 가격 × 3','raw':{'2.5':22000,'5':44000,'7.5':66000},'factor':3,
  'condition':'공식표 4회(1개월) 가격 ×3. BMI·검사·처방 조건 별도 확인'},
}

def corrected(item):
    return {d:(item['raw'][d]*item['factor'] if d in item['raw'] else None) for d in DOSES}

def verify_cases():
    assert len(SOURCES)==7
    expected={'national-74496af43d6b1b':66000,'national-bc39c46aff3977':144000,
              'national-5a0014ff50fb32':58800,'national-3ba16144280470':156123,
              'national-af1c31d0f63e16':75600,'national-f35b616276017d':132000,
              'national-a44a974e3df021':132000}
    assert {k:corrected(v)['5'] for k,v in SOURCES.items()}==expected
    assert len({x['url'] for x in SOURCES.values()})==7
    print('Seven independent official 5mg unit-conversion cases passed')

def now():
    return datetime.datetime.now(JST).isoformat(timespec='seconds')

def run():
    verify_cases()
    catalog=json.loads(CATALOG.read_text(encoding='utf-8'))
    old=snapshot(catalog,{})
    by_id={x['id']:x for x in catalog.get('clinics',[])}
    for ident,case in SOURCES.items():
        c=by_id.get(ident)
        if c is None:raise SystemExit('Missing verified clinic record '+ident)
        if case['name'] not in c.get('name',''):raise SystemExit('Clinic identity mismatch '+ident)
        if c.get('status') not in ('active','candidate'):raise SystemExit('Unexpected clinic status '+ident)
        c['prices']=corrected(case)
        c['status']='active'
        c['price_verified']=True
        c['official_price_audit_status']='passed'
        c['official_price_audited_at']=now()
        c['price_unit_reviewed_at']=now()
        c['price_unit_reviewed_source_url']=case['url']
        c['price_unit_reviewed_kind']=case['four_or_one']
        c['source_price_values']=case['raw']
        c['price_plan_factor']=case['factor']
        c['basis']='공식 홈페이지 가격표의 '+case['four_or_one']+' (동일 용량 12주 기준 단순 환산).'
        c['notes']=case['condition']+'. 12펜 일괄 구매 가능·외국인 처방 여부는 별도 확인.'
        c['url']=case['url']
        c['updated']=now()[:10]
        assert c['prices']['5']==case['raw']['5']*case['factor']
        print('CORRECTED',c['name'],'5mg:',c['prices']['5'],'12 pens;',case['four_or_one'],flush=True)
    CATALOG.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    delta=changes(old,snapshot(catalog,{}))
    last=json.loads(HISTORY.read_text(encoding='utf-8')) if HISTORY.exists() else {}
    new=update_history(last,now(),delta)
    HISTORY.write_text(json.dumps(new,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Corrected seven clinics, substantive changes',len(delta),'12-pen units reviewed.',flush=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--self-test',action='store_true')
    args=p.parse_args()
    if args.self_test:return verify_cases()
    run()

if __name__=='__main__':main()
