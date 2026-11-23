#!/usr/bin/env python3
"""Conservatively attach publicly confirmed OFFICIAL 12-week pricing to SNS candidates.

Only parses explicit 12-pen/3-month tables or 4-pen/1-month unit prices.
Never guesses foreigner eligibility, online access, shipping, or promo validity.
No SNS advertisement price is promoted without official price-page evidence.
"""
import argparse, datetime as dt, json, re, urllib.parse, unicodedata, os
from pathlib import Path
from bs4 import BeautifulSoup
import requests
from discover import ROOT,CATALOG,UA,fetch_rss,fetch_bing_html,now,DOSES,potential_official_site
from strict_price_parser import extract_with_evidence, self_test as official_price_self_test

EXCLUDE=['sushijaro','mounjarojp','kireireport','yahoo','instagram','facebook','x.com','twitter','note.com','reddit','beauty.hotpepper','kuchikomi','a-clinic-column','seikeitimes','jihi-shohou','google.com','news.google','blogspot']
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
        official_price_self_test()
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
    queue=[x for x in cat['clinics'] if x.get('status')=='candidate' and x.get('discovery') in ('auto','national')]
    queue.sort(key=lambda x:(x.get('official_checked_at',''),x.get('first_seen','')))
    # Reserve slots for comparison-site links that point straight to a possible
    # official clinic website, without starving older name-only candidates.
    linked = [x for x in queue if x.get('official_url_hint')]
    name_only = [x for x in queue if not x.get('official_url_hint')]
    batch = linked[:(48 if os.environ.get('FULL_SCAN')=='true' else 32)] + name_only[:(8 if os.environ.get('FULL_SCAN')=='true' else 4)]
    done=0
    for item in batch:
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
            resp=session.get(official,timeout=(5,11));resp.raise_for_status()
            soup=BeautifulSoup(resp.content,'html.parser');text=soup.get_text(' ',strip=True)
            # Strict medicine-scoped parsing only: do not use the permissive
            # legacy extractor, which can mix Mounjaro with other medicines.
            prices,evidence=extract_with_evidence(resp.content,resp.url)
            basis='검증 V2: 공식 용량·가격·판매 수량 확인'
            # A clinic homepage may link to a dedicated Mounjaro price page.
            if not prices:
                links=[]
                for a in soup.select('a[href]'):
                    href=urllib.parse.urljoin(official,a.get('href',''))
                    label=a.get_text(' ',strip=True)+' '+a.get('href','')
                    if official_host(href)!=official_host(official):continue
                    if href==official or not re.search(r'マンジャロ|mounjaro|チルゼパチド|medical[-_/]?diet|glp[-_/]?1|ダイエット|自由診療|料金|価格|美容',label,re.I):continue
                    if href not in links:links.append(href)
                links.sort(key=lambda u:(0 if re.search(r'マンジャロ|mounjaro',u,re.I)
                                         else 1 if re.search(r'料金|price|ダイエット|diet',u,re.I)
                                         else 2, len(u)))
                for href in links[:3]:
                    try:
                        follow=session.get(href,timeout=(5,9));follow.raise_for_status()
                        found,found_evidence=extract_with_evidence(follow.content,follow.url)
                        if found and official_host(follow.url)==official_host(official):
                            prices=found;evidence=found_evidence;official=follow.url
                            soup=BeautifulSoup(follow.content,'html.parser');text=soup.get_text(' ',strip=True)
                            break
                    except requests.RequestException:pass
            if not re.search('マンジャロ|mounjaro',text,re.I):continue
            # A price table is useful only if it actually belongs to the named
            # institution. Do not attribute comparison articles to a clinic.
            normalized=lambda x:re.sub(r'[^a-z0-9ぁ-んァ-ヴ一-龥]','',unicodedata.normalize('NFKC',x).lower())
            key=normalized(item['name'])
            if not item.get('mhlw_identity_matched') and len(key)>=6 and key not in normalized(text[:3000]):
                item['notes']='공식 사이트 후보 발견, 병원명 교차 검증 실패: '+official
                continue
            if not prices:continue
            # Temporary campaign/coupon pages require a verifiable end date and
            # separate event treatment, so do not auto-promote their prices.
            if re.search(r'期間限定|初回限定|キャンペーン価格|クーポン適用',text[:5000]):
                item['notes']='공식 가격 페이지 후보 발견, 기간 한정/쿠폰 조건 때문에 자동 비교가 보류: '+official
                continue
            item['prices']={d:prices.get(d) for d in DOSES}
            item['price_integrity']='strict_v2'
            item['price_evidence']=evidence
            item['official_price_audit_status']='passed'
            item['official_price_audited_at']=now()
            item['basis']=basis+'; 공개 검색 후보를 공식 페이지로 교차 확인'
            item['url']=official;item['status']='active';item['price_verified']=True
            item['official_domain']=official_host(official)
            item['channel']=('공식 홈페이지 검색 → 공식 가격 검증' if item.get('official_url_hint')
                             else 'SNS·비교 사이트 발견 → 공식 가격 검증')
            item['updated']=now()[:10]
            item['notes']='가격은 공식 페이지에서 단위를 명시한 금액만 채움. 외국인/배송/온라인 진료는 검증 전이며 자동으로 가능 표시하지 않음.'
            print('Price confirmed:',item['name'],len(prices),'doses',official)
        except (requests.RequestException,ValueError) as exc:print('Page check failed:',item['name'],str(exc)[:100])
    CATALOG.write_text(json.dumps(cat,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Official candidate pages checked:',done)
if __name__=='__main__':run()
