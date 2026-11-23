#!/usr/bin/env python3
"""Read-only independent comparison of previously hand-curated prices.

Do not silently replace a manually researched 12-week discount price with a
single-month price from the same site. Record any differing official evidence
for a human review of purchase conditions instead.
"""
from __future__ import annotations
import concurrent.futures,datetime as dt,json,requests
from pathlib import Path
from strict_price_parser import extract_with_evidence
from discover import ROOT,UA
from enrich_official import official_host
CAT=ROOT/'catalog.json'
OUT=ROOT/'legacy_price_review.json'
DS=("2.5","5","7.5","10","12.5","15")
TZ=dt.timezone(dt.timedelta(hours=9))
def now():return dt.datetime.now(TZ).isoformat(timespec='seconds')
def inspect(c):
    url=c.get('url','')
    result={'id':c['id'],'name':c.get('name',''),'url':url,'discovery':c.get('discovery'),
            'original':{d:c.get('prices',{}).get(d) for d in DS if isinstance(c.get('prices',{}).get(d),(float,int))}}
    if not url.startswith('https://') or not official_host(url):
        result['status']='no_official_url';return result
    try:
        r=requests.get(url,headers={'User-Agent':UA,'Accept-Language':'ja,ko;q=0.8'},timeout=(5,11))
        if not r.ok or len(r.content)>1_250_000 or official_host(r.url)!=official_host(url):
            result.update(status='source_unavailable',http=r.status_code);return result
        prices,evidence=extract_with_evidence(r.content)
    except requests.RequestException as e:
        result.update(status='source_unavailable',error=str(e)[:120]);return result
    result['strict_values']=prices
    result['strict_evidence']=evidence
    diffs={d:{'catalog':v,'official_structured':prices[d]} for d,v in result['original'].items() if d in prices and v!=prices[d]}
    same=[d for d,v in result['original'].items() if d in prices and v==prices[d]]
    result['same_doses']=same
    result['different_doses']=diffs
    result['unconfirmed_doses']=[d for d in result['original'] if d not in prices]
    if diffs:result['status']='different_option_or_price_requires_review'
    elif same:result['status']='some_doses_confirmed'
    else:result['status']='source_not_machine_parseable'
    return result

def main():
    doc=json.loads(CAT.read_text(encoding='utf-8'))
    selected=[c for c in doc['clinics'] if c.get('discovery') not in ('national','auto')
              and c.get('status')=='active'
              and any(isinstance(v,(int,float)) for v in c.get('prices',{}).values())]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        results=list(executor.map(inspect,selected))
    status={}
    for x in results:
        status[x['status']]=status.get(x['status'],0)+1
        if x.get('different_doses'):
            print('LEGACY SOURCE DIFFERENCE:',x['name'],x['different_doses'],flush=True)
    report={'at':now(),'checked':len(results),'status':status,'items':results,
      'caution':'원문에서 다른 금액이 발견돼도 별도 할인·단기 처방일 수 있어 자동으로 덮어쓰지 않음. 원문 단위와 구매조건을 독립 재검증해야 함.'}
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('LEGACY SOURCE REVIEW RESULT',json.dumps({'checked':len(results),'statuses':status},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
