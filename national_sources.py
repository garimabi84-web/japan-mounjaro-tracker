#!/usr/bin/env python3
"""Nationwide clinic leads: MHLW open-data registry + public comparison indexes.

Only MHLW may supply the registered institution identity/location. Sayaka and
Mirai are navigation *leads*, never authoritative drug prices or eligibility.
New leads remain unverified until enrich_official independently fetches their
clinic website and verifies a Mounjaro price. Respect public robots directives.
"""
from __future__ import annotations
import argparse, csv, datetime as dt, gzip, hashlib, io, json, re, time, urllib.parse
from collections import defaultdict
from pathlib import Path
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parent
CATALOG=ROOT/'catalog.json'
REGISTRY=ROOT/'national_registry.json.gz'
STATE=ROOT/'national_source_state.json'
REPORT=ROOT/'national_discovery.json'
MHLW='https://www.mhlw.go.jp/content/11121000/02-1_clinic_facility_info_20260601.csv.zip'
MHLW_PAGE='https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/newpage_43373.html'
SAYAKA='https://sayaka-biyou-clinic.com/mounjaro/'
MIRAI='https://md.mirai-medical.clinic/'
UA='JapanMounjaroTracker/3.0 (independent clinic price research)'
DOSES=('2.5','5','7.5','10','12.5','15')
PREFS=('北海道','青森','岩手','宮城','秋田','山形','福島','茨城','栃木','群馬',
 '埼玉','千葉','東京','神奈川','新潟','富山','石川','福井','山梨','長野',
 '岐阜','静岡','愛知','三重','滋賀','京都','大阪','兵庫','奈良','和歌山',
 '鳥取','島根','岡山','広島','山口','徳島','香川','愛媛','高知','福岡',
 '佐賀','長崎','熊本','大分','宮崎','鹿児島','沖縄')
PRIORITY=('fukuoka','osaka','tokyo','tottori','saga','nagasaki','hiroshima','hokkaido')
BLOCKED=('sayaka-biyou-clinic.com','md.mirai-medical.clinic','t.felmat.net','felmat.net',
 'sushijaro.app','kireireport.com','google.com','yahoo.co.jp','line.me','liff.line.me',
 'instagram.com','x.com','facebook.com','youtube.com','manjaro-info.jp','mounjarojp.com')
PROMO_RE=re.compile('マンジャロ|mounjaro|チルゼパチド',re.I)
SKIP_NAME=re.compile('運営|公式サイト|料金比較|お問い合わせ|検索|オンラインでおすすめ|料金と条件')
from discover import now, norm_name, DOSES as KNOWN_DOSES

def load(path,default=None):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return default if default is not None else {}

def save(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def clean_url(u):
    if not u:return ''
    u=str(u).strip().split(' ')[0].replace('／','/')
    if u.startswith('www.'):u='https://'+u
    if u.startswith('http://'):u='https://'+u[7:]
    try:
        p=urllib.parse.urlsplit(u)
        if p.scheme!='https' or not p.hostname or '.' not in p.hostname:return ''
        if p.username or p.password:return ''
        host=p.hostname.lower().removeprefix('www.')
        if any(host==h or host.endswith('.'+h) for h in BLOCKED):return ''
        if not re.fullmatch(r'[a-z0-9][a-z0-9.\-]{2,250}',p.hostname.lower()):return ''
        return urllib.parse.urlunsplit(('https',p.netloc.lower(),p.path or '/','',''))
    except ValueError:return ''

def host(url):
    try:return urllib.parse.urlsplit(url).hostname.lower().removeprefix('www.')
    except (AttributeError,ValueError):return ''

def official_page_candidates(html,page_url,hostnames):
    """Return official links from a *single* comparison-page heading context."""
    soup=BeautifulSoup(html,'html.parser')
    out=[];seen=set()
    for a in soup.select('a[href]'):
        label=a.get_text(' ',strip=True)
        if not ('公式' in label or '料金の記載を確認したページ' in label):
            continue
        url=clean_url(urllib.parse.urljoin(page_url,a.get('href','')))
        if not url or url in seen:continue
        # Heading nearest the anchor must clearly identify the same clinic.
        h=a.find_previous(['h3','h4','h5'])
        heading=h.get_text(' ',strip=True)[:160] if h else ''
        # Reject generic rankings, and outbound calls unrelated to clinics.
        if not heading or SKIP_NAME.search(heading):continue
        heading=re.sub(r'^\d+[.)．]\s*','',heading)
        name=re.split(r'の(?:詳細|特徴|料金|口コミ)|（|[(]|\s{3,}',heading)[0].strip()
        if not 4<=len(name)<=90 or not re.search(r'クリニック|医院|病院|外科|皮膚科|内科|メディカル|CLINIC',name,re.I):
            continue
        seen.add(url)
        out.append({'name_hint':name,'official_url':url,'referer':page_url})
    return out

def parse_registry_zip(blob):
    import zipfile
    z=zipfile.ZipFile(io.BytesIO(blob))
    entries=[]
    with z.open(next(x for x in z.namelist() if x.endswith('.csv'))) as f:
        reader=csv.DictReader(io.TextIOWrapper(f,encoding='utf-8-sig',newline='',errors='replace'))
        needed={'ID','正式名称','都道府県コード','所在地','案内用ホームページアドレス'}
        if not needed.issubset(set(reader.fieldnames or [])):
            raise ValueError('MHLW facility CSV columns changed: '+repr(reader.fieldnames[:18]))
        for r in reader:
            url=clean_url(r.get('案内用ホームページアドレス',''))
            name=str(r.get('正式名称','')).strip()
            if not url or not name:continue
            number=str(r.get('都道府県コード','')).strip()
            try:pref=PREFS[int(number)-1]+'県' if int(number) not in (1,13,26,27,40) else {'01':'北海道','13':'東京都','26':'京都府','27':'大阪府','40':'福岡県'}.get(number,'')
            except (ValueError,IndexError):pref=''
            if number=='02':pref='青森県'
            elif number in ('03','04','05','06','07','08','09','10','11','12','14','15','16','17','18','19','20','21','22','23','24','25','28','29','30','31','32','33','34','35','36','37','38','39','41','42','43','44','45','46','47'):
                suff='都' if number=='13' else ('府' if number in ('26','27') else '県')
                pref=PREFS[int(number)-1]+suff
            entries.append({'id':str(r.get('ID','')).strip(),'name':name,'url':url,'prefecture':pref,
                            'address':str(r.get('所在地','')).strip()[:160]})
    # Stable ordering enables resumable nationwide sampling.
    entries.sort(key=lambda r:(r['id'],host(r['url']),r['name']))
    return entries

def newest_government_source(session,state):
    """Check for future semiannual releases without guessing ZIP filenames."""
    today=dt.date.today()
    last=str(state.get('mhlw_source_checked',''))
    if last:
        try:
            if (today-dt.date.fromisoformat(last)).days<30:return state.get('mhlw_source_url',MHLW)
        except ValueError:pass
    try:
        r=session.get(MHLW_PAGE,timeout=(7,18));r.raise_for_status()
        soup=BeautifulSoup(r.content,'html.parser')
        candidates=[]
        for a in soup.select('a[href]'):
            url=urllib.parse.urljoin(MHLW_PAGE,a['href'])
            match=re.search(r'02-1_clinic_facility_info_(20[0-9]{6})[.]csv[.]zip',url)
            if match and urllib.parse.urlsplit(url).hostname=='www.mhlw.go.jp':
                candidates.append((match[1],url))
        if candidates:
            state['mhlw_source_url']=max(candidates)[1]
            state['mhlw_source_checked']=today.isoformat()
    except requests.RequestException as exc:
        print('MHLW source-index refresh failed:',str(exc)[:100])
    return state.get('mhlw_source_url',MHLW)

def get_registry(session,force=False,source_url=MHLW):
    if REGISTRY.exists() and not force:
        try:
            blob=gzip.decompress(REGISTRY.read_bytes())
            data=json.loads(blob)
            if isinstance(data,list) and data:return data,'cached'
        except Exception:pass
    rsp=session.get(source_url,timeout=(12,70))
    rsp.raise_for_status()
    if len(rsp.content)>35_000_000:raise ValueError('MHLW ZIP unexpectedly large')
    data=parse_registry_zip(rsp.content)
    if len(data)<2000:raise ValueError('MHLW registry suspiciously small: '+str(len(data)))
    REGISTRY.write_bytes(gzip.compress(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode(),compresslevel=8))
    return data,'downloaded'

def allowed(session,origin):
    # Check comparison-site robots directives; a 403 or explicit disallow is
    # interpreted as no permission to crawl. Avoid needless repeat checks.
    try:
        p=urllib.parse.urlsplit(origin)
        r=session.get(p.scheme+'://'+p.netloc+'/robots.txt',timeout=(5,10))
        if r.status_code in (401,403,429):return False
        if r.status_code==404:return True
        if not r.ok:return False
        rp=RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp.can_fetch(UA,origin)
    except requests.RequestException:
        return False

def page_roots(soup,base,kind):
    if kind=='sayaka':
        pattern=re.compile(r'^/mounjaro/([a-z-]{3,24})/?$')
        deny={'map','clinic','eki','guide','faq','online','ranking','articles'}
    else:
        pattern=re.compile(r'^/prefectures(\d\d)/?$')
        deny=set()
    links=[]
    for a in soup.select('a[href]'):
        u=urllib.parse.urljoin(base,a['href'])
        p=urllib.parse.urlsplit(u)
        if p.netloc!=urllib.parse.urlsplit(base).netloc:continue
        m=pattern.fullmatch(p.path)
        if not m or m[1] in deny:continue
        if kind=='mirai' and not (1<=int(m[1])<=47):continue
        if u not in links:links.append(u)
    if kind=='sayaka':
        links.sort(key=lambda u:(0 if urllib.parse.urlsplit(u).path.strip('/').split('/')[-1] in PRIORITY else 1,
                                 PRIORITY.index(urllib.parse.urlsplit(u).path.strip('/').split('/')[-1])
                                 if urllib.parse.urlsplit(u).path.strip('/').split('/')[-1] in PRIORITY else u))
    else:
        pri={'40':0,'27':1,'13':2,'31':3,'41':4,'42':5,'34':6,'01':7}
        links.sort(key=lambda u:(pri.get(re.search(r'(\d\d)/?$',u)[1],99),u))
    return links

def pick_pages(all_pages,cursor,count):
    if not all_pages:return [],0
    i=cursor%len(all_pages)
    items=[all_pages[(i+n)%len(all_pages)] for n in range(min(count,len(all_pages)))]
    return items,(i+len(items))%len(all_pages)

def region_for(pref):
    if any(x in pref for x in ('福岡','長崎','佐賀','熊本','大分','宮崎','鹿児島')):return '규슈'
    if any(x in pref for x in ('東京','神奈川','埼玉','千葉','群馬','栃木','茨城')):return '간토'
    if any(x in pref for x in ('大阪','京都','兵庫','奈良','滋賀','和歌山')):return '간사이'
    if any(x in pref for x in ('愛知','静岡','岐阜','三重','石川','福井','富山','長野','山梨','新潟')):return '주부'
    if any(x in pref for x in ('鳥取','島根','岡山','広島','山口')):return '주고쿠'
    if any(x in pref for x in ('香川','愛媛','徳島','高知')):return '시코쿠'
    if '北海道' in pref:return '홋카이도'
    if any(x in pref for x in ('宮城','岩手','青森','秋田','山形','福島')):return '도호쿠'
    if '沖縄' in pref:return '오키나와'
    return '미확인'

def normalized(s):
    return norm_name(re.sub(r'^(?:医療法人(?:社団|財団)?|社会医療法人|医療法人社団|医療法人財団)\s*','',str(s or '')))

def match_registry(leads,registry):
    by_host=defaultdict(list)
    for r in registry:by_host[host(r['url'])].append(r)
    result=[]
    for lead in leads:
        domain=host(lead['official_url'])
        options=by_host.get(domain,[])
        # A shared corporate site is not sufficient proof of branch identity.
        if len(options)==1:
            r=options[0]
            result.append({**lead,'name':r['name'],'prefecture':r['prefecture'],
                           'address':r['address'],'mhlw_id':r['id'],'gov_matched':True})
        else:
            name=lead['name_hint']
            similar=[r for r in options if normalized(name) in normalized(r['name']) or normalized(r['name']) in normalized(name)]
            if len(similar)==1:
                r=similar[0]
                result.append({**lead,'name':r['name'],'prefecture':r['prefecture'],
                               'address':r['address'],'mhlw_id':r['id'],'gov_matched':True})
            elif not options:
                result.append({**lead,'name':name,'prefecture':'','address':'',
                               'mhlw_id':'','gov_matched':False})
            # Ambiguous corporate domains are saved as name-only, no gov match.
            else:
                result.append({**lead,'name':name,'prefecture':'','address':'',
                               'mhlw_id':'','gov_matched':False})
    return result

def add_leads(cat,leads,limit):
    clinics=cat['clinics'];fresh=[]
    names=defaultdict(list);existing_hosts=defaultdict(list)
    for c in clinics:
        names[normalized(c['name'])].append(c)
        u=c.get('official_url_hint') or c.get('url','')
        if c.get('status')=='active' and c.get('official_domain'):u='https://'+c['official_domain']
        if host(u):existing_hosts[host(u)].append(c)
    # Prioritize MHLW identity, then linked official pages.
    leads.sort(key=lambda x:(not x.get('gov_matched',False),x.get('name','')))
    for lead in leads:
        u=lead.get('official_url','')
        if not clean_url(u):continue
        name=lead.get('name','').strip()
        if not name:continue
        domain=host(u)
        nn=normalized(name)
        same_host=existing_hosts[domain]
        # Avoid duplicating an existing provider's official site, even when
        # its Japanese legal title differs from the public brand.
        if same_host:
            if any(x.get('status')=='active' for x in same_host):continue
            if any(normalized(x['name'])==nn or x.get('mhlw_id') and x.get('mhlw_id')==lead.get('mhlw_id') for x in same_host):continue
        collision=bool(names[nn])
        ident='national-'+hashlib.sha1((str(lead.get('mhlw_id') or '')+domain+nn).encode()).hexdigest()[:14]
        if any(x['id']==ident for x in clinics):continue
        r={'id':ident,'name':name,'region':region_for(lead.get('prefecture','')),'city':lead.get('prefecture') or '미확인',
           'mode':'미확인','foreign':'unknown','online':'unknown','ship':'unknown',
           'prices':{k:None for k in DOSES},'basis':'공식 의료기관 DB·비교 사이트에서 발견한 후보, 가격 원문 검증 전',
           'url':lead.get('referer') or MHLW_PAGE,
           'official_url_hint':u,'notes':'후생노동성 등록 기관/공개 비교 사이트 공식 URL 단서. 마운자로 취급과 가격·방문 조건은 검증 전.',
           'fees':'미확인','status':'candidate','address':lead.get('address',''),
           'channel':'후생노동성 공식 DB + 공개 비교 사이트' if lead.get('gov_matched') else '공개 비교 사이트 공식 사이트 링크',
           'updated':now()[:10],'discovery':'national','price_verified':False,'identity_conflict':collision,
           'mhlw_id':lead.get('mhlw_id',''),'mhlw_identity_matched':bool(lead.get('gov_matched')),
           'candidate_quality':'gov_name_domain_matched' if lead.get('gov_matched') else 'directory_official_link',
           'comparison_source':lead.get('referer',''),'events':[],'booking_method':'예약 방법 미확인',
           'booking_url':'','booking_type':'none','booking_notes':'외국인/관광객 여부 미확인',
           'booking_checked':'','first_seen':now()[:10]}
        clinics.append(r);fresh.append(r)
        names[nn].append(r);existing_hosts[domain].append(r)
        if len(fresh)>=limit:break
    return fresh

def inspect_gov(session,registry,state,limit):
    # A medical-registry entry is NOT a Mounjaro clinic. Require the drug on
    # the actual provider website before adding it as an unverified lead.
    eligible=[r for r in registry if re.search(r'美容|メディカル|ダイエット|肥満|内科|皮膚科',r['name'])]
    if not eligible:return [],0
    cursor=int(state.get('mhlw_cursor',0))%len(eligible);leads=[];tested=0
    for n in range(min(limit,len(eligible))):
        r=eligible[(cursor+n)%len(eligible)]
        tested+=1
        try:
            rsp=session.get(r['url'],timeout=(5,9))
            if not rsp.ok or len(rsp.content)>800000:continue
            body=BeautifulSoup(rsp.content,'html.parser').get_text(' ',strip=True)[:35000]
            if not PROMO_RE.search(body):continue
            leads.append({'name':r['name'],'name_hint':r['name'],'official_url':r['url'],
                          'referer':MHLW_PAGE,'prefecture':r['prefecture'],'address':r['address'],
                          'mhlw_id':r['id'],'gov_matched':True})
        except requests.RequestException:pass
    state['mhlw_cursor']=(cursor+tested)%len(eligible)
    return leads,tested

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--self-test',action='store_true')
    p.add_argument('--full-scan',action='store_true')
    args=p.parse_args()
    if args.self_test:
        assert clean_url('http://abc-clinic.jp/x?campaign=1')=='https://abc-clinic.jp/x'
        assert not clean_url('https://t.felmat.net/ad')
        mock='''<h3>福岡テストクリニック</h3><a href="https://www.test-medical.jp/mounjaro/">公式サイトを見る</a>'''
        items=official_page_candidates(mock,SAYAKA,{})
        assert len(items)==1 and items[0]['name_hint']=='福岡テストクリニック',items
        assert region_for('福岡県')=='규슈'
        assert pick_pages(['a','b','c'],2,2)==(['c','a'],1)
        print('national source self-test passed')
        return
    session=requests.Session();session.headers.update({'User-Agent':UA,'Accept-Language':'ja,ko;q=0.8,en;q=0.6'})
    state=load(STATE);report={'ran_at':now(),'sources':[],'count':{}}
    try:
        source_url=newest_government_source(session,state)
        registry,mode=get_registry(session,force=bool(REGISTRY.exists() and state.get('mhlw_cached_url') and source_url!=state.get('mhlw_cached_url')),source_url=source_url)
        state['mhlw_cached_url']=source_url
        report['count']['mhlw_website_records']=len(registry)
        report['sources'].append({'source':'MHLW clinic open data','ok':True,'mode':mode,'records':len(registry),'url':source_url})
        print('MHLW registry:',len(registry),'website entries;',mode)
    except Exception as e:
        registry=[]
        report['sources'].append({'source':'MHLW 2026 clinic open data','ok':False,'error':str(e)[:200]})
        print('MHLW unavailable:',str(e)[:200])
    leads=[];seen=set()
    for kind,root in [('sayaka',SAYAKA),('mirai',MIRAI)]:
        try:
            if not allowed(session,root):
                raise ValueError('robots.txt disallows public-page fetching or robots unavailable')
            response=session.get(root,timeout=(8,20));response.raise_for_status()
            soup=BeautifulSoup(response.content,'html.parser')
            pages=page_roots(soup,root,kind)
            per_run=8 if args.full_scan else 4
            chosen,at=pick_pages(pages,int(state.get(kind+'_cursor',0)),per_run)
            state[kind+'_cursor']=at
            # Some official sites link directly from the index home page too.
            chosen=[root]+chosen
            count=0
            for page in chosen:
                if not allowed(session,page):
                    continue
                try:
                    rsp=session.get(page,timeout=(6,18));rsp.raise_for_status()
                    for lead in official_page_candidates(rsp.text,page,set()):
                        key=(host(lead['official_url']),normalized(lead['name_hint']))
                        if key not in seen:
                            leads.append(lead);seen.add(key);count+=1
                except requests.RequestException as e:
                    print('Directory page failed:',page,str(e)[:80])
                time.sleep(.15)
            report['sources'].append({'source':kind,'ok':True,'pages':len(chosen),'official_link_leads':count,'total_pages':len(pages)})
            print(kind,'pages',len(chosen),'official-link leads',count,'total prefecture pages',len(pages))
        except (requests.RequestException,ValueError) as e:
            report['sources'].append({'source':kind,'ok':False,'error':str(e)[:160]})
            print(kind,'unavailable:',str(e)[:160])
    if registry:
        matches=match_registry(leads,registry)
        gov_leads,gov_tests=inspect_gov(session,registry,state,35 if args.full_scan else 15)
    else:matches=match_registry(leads,[]);gov_leads=[];gov_tests=0
    cat=load(CATALOG)
    added=add_leads(cat,matches+gov_leads,200 if args.full_scan else 80)
    if added:save(CATALOG,cat)
    report['count'].update({'directory_links':len(leads),'matched_registry':sum(x.get('gov_matched',False) for x in matches),
       'registry_sites_checked':gov_tests,'gov_drug_site_leads':len(gov_leads),
       'new_candidates':len(added),'new_gov_matched':sum(x.get('mhlw_identity_matched') for x in added)})
    save(STATE,state);save(REPORT,report)
    print('NATIONAL RESULT:',json.dumps(report['count'],ensure_ascii=False))
if __name__=='__main__':main()
