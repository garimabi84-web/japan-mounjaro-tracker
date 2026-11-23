#!/usr/bin/env python3
"""Parallel verification of official Mounjaro prices from nationwide clinic leads.

The comparison indexes are used for official URL discovery only; every
price must come from the named clinic's actual official website.
"""
import argparse, concurrent.futures, json, re, unicodedata, urllib.parse
import requests
from bs4 import BeautifulSoup
from discover import CATALOG, UA, now
from enrich_official import official_host
from strict_price_parser import extract_with_evidence

DRUG=re.compile('マンジャロ|mounjaro',re.I)
FOLLOW=re.compile('マンジャロ|mounjaro|medical[-_/ ]?diet|glp[-_/]?1|ダイエット|自由診療|料金|価格|美容',re.I)
TEMPORARY=re.compile('期間限定|初回限定|キャンペーン価格|クーポン適用')

def normalized(s):
    return re.sub(r'[^a-z0-9ぁ-んァ-ヴ一-龥]','',unicodedata.normalize('NFKC',str(s)).lower())

def parse_price(html):
    prices,evidence=extract_with_evidence(html)
    return prices,'검증 V2: 원문 용량·판매 단위·금액 연결',evidence

def validate_page(item,original,response):
    root=official_host(original)
    if not response.ok or official_host(response.url)!=root:return None
    if len(response.content)>1_000_000:return None
    soup=BeautifulSoup(response.content,'html.parser')
    txt=soup.get_text(' ',strip=True)
    if not DRUG.search(txt) or TEMPORARY.search(txt[:5000]):return None
    if not item.get('mhlw_identity_matched'):
        name=normalized(item['name'])
        if len(name)>=6 and name not in normalized(txt[:4200]):return None
    prices,basis,evidence=parse_price(response.content)
    if not prices:return None
    return {'prices':prices,'basis':basis,'evidence':evidence,'url':response.url}

def probe(item):
    url=item.get('official_url_hint','')
    if not url.startswith('https://'):return item['id'],None
    host=official_host(url)
    session=requests.Session()
    session.headers.update({'User-Agent':UA,'Accept-Language':'ja,ko;q=0.8'})
    try:
        r=session.get(url,timeout=(4,10))
        result=validate_page(item,url,r)
        if result:return item['id'],result
        if not r.ok or official_host(r.url)!=host or len(r.content)>1_000_000:
            return item['id'],None
        soup=BeautifulSoup(r.content,'html.parser')
        links=[]
        for a in soup.select('a[href]'):
            href=urllib.parse.urljoin(r.url,a.get('href',''))
            words=a.get_text(' ',strip=True)+' '+a.get('href','')
            if official_host(href)!=host or href==r.url or not FOLLOW.search(words):continue
            if href not in links:links.append(href)
        links.sort(key=lambda u:(0 if re.search('マンジャロ|mounjaro',u,re.I)
                                  else 1 if re.search('料金|price|diet',u,re.I) else 2,len(u)))
        for link in links[:3]:
            try:
                page=session.get(link,timeout=(4,9))
                result=validate_page(item,url,page)
                if result:return item['id'],result
            except requests.RequestException:continue
        return item['id'],None
    except requests.RequestException:
        return item['id'],None
    finally:session.close()

def choose(clinics,count):
    claimed=set()
    for c in clinics:
        if c.get('status')=='active':
            url='https://'+c['official_domain'] if c.get('official_domain') else c.get('url','')
            if official_host(url):claimed.add(official_host(url))
    candidates=[c for c in clinics if c.get('status')=='candidate' and c.get('official_url_hint')
                and c.get('discovery') in ('national','auto') and not c.get('identity_conflict')
                and official_host(c['official_url_hint']) not in claimed]
    candidates.sort(key=lambda c:(c.get('official_checked_at',''),
                                  not c.get('mhlw_identity_matched'),
                                  -sum(q in c.get('official_url_hint','').lower()
                                       for q in ('mounjaro','price','diet'))))
    seen=set();chosen=[]
    for item in candidates:
        domain=official_host(item['official_url_hint'])
        if not domain or domain in seen:continue
        seen.add(domain);chosen.append(item)
        if len(chosen)>=count:break
    return chosen

def self_test():
    sample=[{'id':'a','status':'candidate','discovery':'national','name':'Aクリニック',
             'official_url_hint':'https://a-clinic.jp/'},
            {'id':'b','status':'candidate','discovery':'national','name':'Bクリニック',
             'official_url_hint':'https://b-clinic.jp/'},
            {'id':'c','status':'candidate','discovery':'national','name':'Cクリニック',
             'official_url_hint':'https://b-clinic.jp/price'}]
    assert len(choose(sample,10))==2
    prices,_,_=parse_price('<h2>マンジャロ</h2><p>10mg（4週分）60,000円</p>')
    assert prices.get('10')==180000,prices
    zep='<h3>ゼップバウンド</h3><p>糖尿病治療薬「マンジャロ」と同成分。</p><p>10mg（1ヶ月分）33,000円</p>'
    assert parse_price(zep)[0]=={},parse_price(zep)
    print('Parallel official-price verification self-test passed')

def run():
    ap=argparse.ArgumentParser()
    ap.add_argument('--self-test',action='store_true')
    ap.add_argument('--limit',type=int,default=100)
    args=ap.parse_args()
    if args.self_test:return self_test()
    catalog=json.loads(CATALOG.read_text(encoding='utf-8'))
    batch=choose(catalog['clinics'],max(0,min(args.limit,160)))
    print('Parallel official-site checks:',len(batch),flush=True)
    outcome={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        futures=[pool.submit(probe,item) for item in batch]
        for f in concurrent.futures.as_completed(futures):
            ident,data=f.result();outcome[ident]=data
    verified=0
    for item in batch:
        data=outcome.get(item['id'])
        item['official_checked_at']=now()
        item['official_attempts']=item.get('official_attempts',0)+1
        if not data:continue
        item['prices'].update(data['prices'])
        item['price_integrity']='strict_v2'
        item['price_evidence']=data['evidence']
        item['official_price_audit_status']='passed'
        item['official_price_audited_at']=now()
        item['basis']=data['basis']+'; 해당 병원 공식 홈페이지 가격 · 12주 기준 환산'
        item['url']=data['url']
        item['official_domain']=official_host(data['url'])
        item['price_verified']=True
        item['status']='active'
        item['channel']='전국 공개 자료 발견 → 공식 홈페이지 가격 검증'
        item['updated']=now()[:10]
        item['notes']='공식 페이지의 용량·단위가 명확한 금액만 등록. 외국인 처방·배송·12펜 일괄 구매 여부 별도 확인.'
        verified+=1
        print('PARALLEL PRICE VERIFIED:',item['name'],data['prices'],data['url'],flush=True)
    CATALOG.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PARALLEL PRICE RESULT: checked',len(batch),'verified',verified,flush=True)

if __name__=='__main__':run()
