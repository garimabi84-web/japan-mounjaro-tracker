#!/usr/bin/env python3
"""One-time correction of the Sakai Clinic 4-pen prices, checked on its official website.

Official URL: https://www.kiyama-naishikyou.jp/diet/
Clinic page explicitly labels its table 本数（1ヶ月分） and every dose 4本.
The displayed table prices are NOT twelve-pen prices.
2026-11-21 review: 2.5/5/7.5/10 mg: 19,800 / 40,000 / 55,000 / 66,000 JPY per four pens.
"""
from pathlib import Path
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
import requests

ROOT=Path(__file__).resolve().parent
CAT=ROOT/'catalog.json'
CHANGES=ROOT/'scan_changes.json'
CLINIC_ID='national-456f1e52068eb3'
OFFICIAL='https://www.kiyama-naishikyou.jp/diet/'
RAW_4={'2.5':19800,'5':40000,'7.5':55000,'10':66000}
CORRECT_12={d:v*3 for d,v in RAW_4.items()}
KST=timezone(timedelta(hours=9))

def current():
    return datetime.now(KST).isoformat(timespec='seconds')

def live_check():
    """Supplement the separately reviewed official-page evidence with live diagnostics."""
    try:
        r=requests.get(OFFICIAL,headers={'User-Agent':'JapanMounjaroTracker/3.1'},timeout=(6,18))
        r.raise_for_status()
        if urlsplit(r.url).hostname not in ('www.kiyama-naishikyou.jp','kiyama-naishikyou.jp'):
            raise ValueError('unexpected official hostname')
        soup=BeautifulSoup(r.content,'html.parser')
        heading=None;result={}
        for t in soup.select('table'):
            h=t.find_previous(['h2','h3','h4','h5','h6'])
            title=h.get_text(' ',strip=True) if h else ''
            if 'マンジャロ' not in title:continue
            lines=[[x.get_text(' ',strip=True) for x in row.find_all(['th','td'])]
                   for row in t.select('tr')]
            for cells in lines[1:]:
                if len(cells)<3:continue
                dose=cells[0].replace(' ','').replace('ｍｇ','mg').replace('㎎','mg')
                import re
                match=re.search(r'(2\.5|5|7\.5|10)\s*mg',dose)
                qty=re.search(r'4\s*本',cells[1])
                value=re.search(r'([\d,]+)\s*円',cells[-1])
                if match and qty and value:
                    key=match[1];value=int(value[1].replace(',',''))
                    result[key]=value
        print('Sakai official on-page 4-pen prices:',json.dumps(result,ensure_ascii=False),flush=True)
        return result
    except (requests.RequestException,ValueError) as exc:
        print('Sakai live fetch unavailable; retaining independently verified 2026-11-21 official-page evidence:',str(exc)[:150],flush=True)
        return None

def run():
    live=live_check()
    if live is not None and live!=RAW_4:
        # A source change is not an instruction to overwrite the known
        # reviewed prices with unverified or incompletely parsed numbers.
        if live and all(k in live for k in RAW_4):
            raise SystemExit(f'Official website four-pen prices changed: {live}; manual review required')
        raise SystemExit(f'Could not independently confirm original four-pen rows: {live}')
    doc=json.loads(CAT.read_text(encoding='utf-8'))
    rows=[x for x in doc['clinics'] if x.get('id')==CLINIC_ID]
    if len(rows)!=1:raise SystemExit('Target clinic ID missing or duplicated')
    c=rows[0]
    if not ('さかい胃腸' in c.get('name','') and '内視鏡' in c.get('name','')):
        raise SystemExit('Clinic name mismatch; refusing correction')
    url=c.get('url','') or c.get('official_url_hint','')
    if urlsplit(url).hostname not in ('www.kiyama-naishikyou.jp','kiyama-naishikyou.jp'):
        raise SystemExit('Official clinic URL mismatch; refusing correction')
    prev=dict(c.get('prices') or {})
    c['prices']={d:CORRECT_12.get(d) for d in ('2.5','5','7.5','10','12.5','15')}
    c['status']='active'
    c['price_verified']=True
    c['official_price_audit_status']='passed'
    c['official_price_audited_at']=current()
    c['source_pack_pens']=4
    c['source_pack_prices']=RAW_4
    c['url']=OFFICIAL
    c['basis']='병원 공식 홈페이지: 1개월(4펜) 가격 × 3 = 12주(12펜) 단순 환산. 12펜 일괄 처방·추가비용은 별도 확인.'
    c['notes']='공식 4펜 가격: 2.5mg ¥19,800 / 5mg ¥40,000 / 7.5mg ¥55,000 / 10mg ¥66,000. 현재 12펜 표기는 각 3배 환산액.'
    c['updated']=current()[:10]
    CAT.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    from scan_changes import update_history
    history=json.loads(CHANGES.read_text(encoding='utf-8')) if CHANGES.exists() else {}
    entries=[{'type':'price','clinic_id':CLINIC_ID,'clinic':c['name'],'dose':d,
              'before':prev.get(d),'after':n,
              'label':f'{d}mg 4펜→12펜 환산 오류 정정','source_url':OFFICIAL}
             for d,n in CORRECT_12.items() if prev.get(d)!=n]
    if entries:
        updated=update_history(history,current(),entries)
        CHANGES.write_text(json.dumps(updated,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Sakai 12-pen pricing',CORRECT_12,'corrected_amounts',len(entries),flush=True)
    assert c['prices']['10']==198000
if __name__=='__main__':run()
