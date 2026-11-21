#!/usr/bin/env python3
"""Conservatively attach publicly confirmed OFFICIAL 12-week pricing to SNS candidates.

Only parses explicit 12-pen/3-month tables or 4-pen/1-month unit prices.
Never guesses foreigner eligibility, online access, shipping, or promo validity.
No SNS advertisement price is promoted without official price-page evidence.
"""
import argparse, datetime as dt, json, re, urllib.parse, unicodedata
from pathlib import Path
from bs4 import BeautifulSoup
import requests
from discover import ROOT,CATALOG,UA,fetch_rss,fetch_bing_html,now,DOSES,potential_official_site

EXCLUDE=['sushijaro','mounjarojp','kireireport','yahoo','instagram','facebook','x.com','twitter','note.com','reddit','beauty.hotpepper','kuchikomi','a-clinic-column','seikeitimes','jihi-shohou','google.com','news.google','blogspot']
PATT_DOSE=re.compile(r'(?<![\d.])(?:マンジャロ|mounjaro)?\s*(2[.]5|5(?:[.]0)?|7[.]5|10(?:[.]0)?|12[.]5|15(?:[.]0)?)\s*mg',re.I)
PATT_YEN=re.compile(r'(?:[¥￥]\s*)?([\d]{1,3}(?:,[\d]{3})+|[\d]{4,6})\s*(?:円|엔|[¥￥])?')

def numeric_price(s):
    for m in PATT_YEN.finditer(s.replace('，',',')):
        if not any(x in s for x in ('円','¥','￥','엔')):return None
        v=int(m.group(1).replace(',',''))
        if 1800<=v<=350000:return v
    return None

def dose_key(s):
    m=PATT_DOSE.search(s)
    if not m:return None
    d=str(float(m.group(1))).removesuffix('.0')
    return d if d in DOSES else None

def extract_prices(source):
    soup=BeautifulSoup(source,'html.parser')
    for tag in soup(['script','style','nav','footer','noscript','svg']):tag.decompose()
    text=' '.join(soup.stripped_strings)
    if not re.search('マンジャロ|mounjaro|마운자로',text,re.I):return {},'not Mounjaro page'
    prices={}
    for table in soup.select('table'):
        rows=[[c.get_text(' ',strip=True) for c in tr.find_all(['th','td'])] for tr in table.select('tr')]
        rows=[r for r in rows if len(r)>=2]
        head=' '.join(' '.join(r) for r in rows[:2])
        three_col=[];one_col=[]
        if any(x in head for x in ['3ヶ月','3か月','12本','12キット']):
            for index,col in enumerate(rows[0]):
                if re.search('3ヶ月|3か月|12本|12キット',col):three_col.append(index)
        if any(x in head for x in ['1ヶ月','1か月','4本','4キット']):
            for index,col in enumerate(rows[0]):
                if re.search('1ヶ月|1か月|4本|4キット',col):one_col.append(index)
        for row in rows:
            key=dose_key(row[0])
            if not key:continue
            if not ('マンジャロ' in ' '.join(row) or 'マンジャロ' in head or 'マンジャロ' in text[:3500]):continue
            val=None
            for index in three_col:
                if index<len(row):val=numeric_price(row[index])
            if val is not None:prices[key]=val;continue
            for index in one_col:
                if index<len(row) and numeric_price(row[index]):val=numeric_price(row[index])*3
            if val is not None:prices[key]=val;continue
            # Explicit single row inline 12-pen or 4-pen descriptions
            inline=' '.join(row)
            if re.search('12本|3ヶ月分|3か月分',inline):
                vals=[numeric_price(c) for c in row[1:]]
                vals=[v for v in vals if v]
                if vals:prices[key]=vals[-1]
            elif re.search('4本|4キット|1ヶ月分|1ヵ月分|1か月分',inline):
                vals=[numeric_price(c) for c in row[1:]]
                vals=[v for v in vals if v]
                if vals:prices[key]=vals[-1]*3
    # Single product page: heading names dosage, explicitly defines 4-pen unit
    if not prices:
        h1=soup.find('h1')
        key=dose_key(h1.get_text(' ',strip=True)) if h1 else None
        if key and re.search('1ヶ月分.{0,15}4本|1か月分.{0,15}4本',text):
            local=text[text.find(h1.get_text(' ',strip=True)):][:220]
            val=numeric_price(local)
            if val:prices[key]=val*3
    return prices, 'official 12-pen posted or explicit 4-pen price × 3'

def official_link(session,name,hint=None):
    # When the official-site search found a probable clinic page, try that
    # exact URL before another name lookup, but never treat its pricing as
    # verified until we actually fetch and validate the page below.
    if hint and potential_official_site(hint):
        return hint
    for q in (f'"{name}" マンジャロ 料金',f'{name} マンジャロ 3ヶ月 価格'):
        try:
            candidates=list(fetch_rss(session,q,'bing'))
            if not candidates:
                candidates=list(fetch_bing_html(session,q))
            for title,url,desc in candidates:
                if not potential_official_site(url):continue
                if not re.search(r'マンジャロ|mounjaro',title+' '+desc,re.I):continue
                return url
        except Exception:pass
    return None

def official_host(url):
    try:
        host=(urllib.parse.urlsplit(url).hostname or '').lower()
        return host.removeprefix('www.')
    except (TypeError,ValueError):
        return ''

def run():
    ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');arg=ap.parse_args()
    if arg.self_test:
        html='''<html><body><h1>CKK ONLINE CLINIC マンジャロ 料金</h1><table><tr><th>用量</th><th>1ヶ月分（4本）</th><th>2ヶ月分（8本）</th><th>3ヶ月分（12本）</th></tr><tr><td>10mg</td><td>27,500円</td><td>55,000円</td><td>82,500円</td></tr><tr><td>5mg</td><td>16,000円</td><td>32,000円</td><td>48,000円</td></tr></table></body></html>'''
        prices,_=extract_prices(html)
        assert prices['10']==82500 and prices['5']==48000,prices
        product='<h1>マンジャロ 10.0mg</h1> ¥46,000 (税込) 1ヶ月分（4本）のお値段となります。'
        prices,_=extract_prices(product)
        assert prices.get('10')==138000,prices
        assert official_host('https://www.miraimedical.com/price')=='miraimedical.com'
        assert official_host('https://mirai-medical.clinic/ko/mounjaro/')=='mirai-medical.clinic'
        assert official_host('https://miraimedical.com/')!=official_host('https://mirai-medical.clinic/')
        assert official_link(None,"サンプルクリニック","https://sample-clinic.jp/mounjaro/")=="https://sample-clinic.jp/mounjaro/"
        assert not potential_official_site("https://sushijaro.app/ja/clinic/example")
        print('self-test OK: official prices, source hints and distinct same-name domains')
        return
    cat=json.loads(CATALOG.read_text(encoding='utf-8'))
    # A distinct branch/domain may use an identical Japanese display name.
    # Never attribute an existing clinic's official price to a newly found
    # namesake without explicit identity verification.
    claimed_domains={}
    for known in cat['clinics']:
        if known.get('status')!='active':
            continue
        host=official_host('https://'+known['official_domain']) if known.get('official_domain') else official_host(known.get('url',''))
        if host:
            claimed_domains.setdefault(host,set()).add(known['id'])
    session=requests.Session();session.headers.update({'User-Agent':UA,'Accept-Language':'ja,ko;q=0.8'})
    # Fair rotating verification queue: previously the same first twelve
    # unverified names were retried forever while later discoveries starved.
    # The oldest attempt is examined first on each run.
    queue=[x for x in cat['clinics'] if x.get('status')=='candidate' and x.get('discovery')=='auto']
    queue.sort(key=lambda x:(x.get('official_checked_at',''),x.get('first_seen','')))
    done=0
    for item in queue[:12]:
        done+=1
        item['official_checked_at']=now()
        item['official_attempts']=item.get('official_attempts',0)+1
        if item.get('identity_conflict'):
            item['notes']='다른 지역에 동일 명칭 병원이 존재. 주소·공식 도메인 검증 전 가격 자동 등록 보류.'
            continue
        official=official_link(session,item['name'],item.get('official_url_hint'))
        if official:
            host=official_host(official)
            if host and host in claimed_domains and item['id'] not in claimed_domains[host]:
                item['notes']='다른 등록 병원 공식 도메인에 속하는 가격표. 기관 동일성 확인 전 자동 등록 보류: '+official
                continue
        if not official:continue
        try:
            resp=session.get(official,timeout=(6,15));resp.raise_for_status()
            soup=BeautifulSoup(resp.content,'html.parser');text=soup.get_text(' ',strip=True)
            if not re.search('マンジャロ|mounjaro',text,re.I):continue
            # A price table is useful only if it actually belongs to the named
            # institution. Do not attribute comparison articles to a clinic.
            normalized=lambda x:re.sub(r'[^a-z0-9ぁ-んァ-ヴ一-龥]','',unicodedata.normalize('NFKC',x).lower())
            key=normalized(item['name'])
            if len(key)>=6 and key not in normalized(text[:3000]):
                item['notes']='공식 사이트 후보 발견, 병원명 교차 검증 실패: '+official
                continue
            prices,basis=extract_prices(resp.content)
            if not prices:continue
            # Temporary campaign/coupon pages require a verifiable end date and
            # separate event treatment, so do not auto-promote their prices.
            if re.search(r'期間限定|初回限定|キャンペーン価格|クーポン適用',text[:5000]):
                item['notes']='공식 가격 페이지 후보 발견, 기간 한정/쿠폰 조건 때문에 자동 비교가 보류: '+official
                continue
            item['prices'].update(prices)
            item['basis']=basis+'; 공개 검색 후보를 공식 페이지로 교차 확인'
            item['url']=official;item['status']='active';item['price_verified']=True
            item['official_domain']=host
            item['channel']=('공식 홈페이지 검색 → 공식 가격 검증' if item.get('official_url_hint')
                             else 'SNS·비교 사이트 발견 → 공식 가격 검증')
            item['updated']=now()[:10]
            item['notes']='가격은 공식 페이지에서 단위를 명시한 금액만 채움. 외국인/배송/온라인 진료는 검증 전이며 자동으로 가능 표시하지 않음.'
            print('Price confirmed:',item['name'],len(prices),'doses',official)
        except (requests.RequestException,ValueError) as exc:print('Page check failed:',item['name'],str(exc)[:100])
    CATALOG.write_text(json.dumps(cat,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Official candidate pages checked:',done)
if __name__=='__main__':run()
