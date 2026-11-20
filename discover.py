#!/usr/bin/env python3
"""Public SNS / web clinic discovery for Japan Mounjaro tracker.

1) Query publicly indexed X/Instagram/Facebook posts through Bing RSS;
   read publicly accessible Yahoo JP realtime X search and Google News RSS.
2) Find clinic names in results; de-duplicate against catalog; insert unverified
   candidate clinics with null prices. Preserve the original post/search URL.
3) Flag coupon/event mentions, but do not fabricate unverified 12-week prices.

Runs from CI (GitHub Actions). No credentials, login bypass, scraping private pages
or proxy services. Feeds can be blocked or sparse: source_status reports errors.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, html, json, re, time, unicodedata, urllib.parse, xml.etree.ElementTree as ET
from pathlib import Path
from bs4 import BeautifulSoup
import requests
ROOT=Path(__file__).resolve().parent
CATALOG=ROOT/'catalog.json'; OUTPUT=ROOT/'discoveries.json'
DOSES=['2.5','5','7.5','10','12.5','15']
UA='Mozilla/5.0 (compatible; personal-public-mounjaro-clinic-research/1.0)'
TERM=r'(?:マンジャロ|Mounjaro|마운자로)'
STOP={'オンラインクリニック','クリニック','病院','美容クリニック','医療ダイエットクリニック','マンジャロクリニック','おすすめクリニック','専門クリニック','SNSクリニック'}
PREFIX=r'(?:公式|公式サイト|PR|激安|価格|期間限定|SNS|キャンペーン|新価格|予約|マンジャロ|医療ダイエット|の|で|当院|最安値|格安|・|＼|／|【|】|\s)+'
NAME_RE=re.compile(r'([A-Za-zＡ-Ｚａ-ｚ0-9\u3040-\u30ff\u3400-\u9fff・&\-ー\.\s]{2,44}?(?:クリニック|CLINIC|Clinic|医院|病院|美容皮膚科))')
EXPLICIT_RE=re.compile(r'(?:【公式】|〖公式〗|[《「])\s*([^【】《》「」\n]{2,38}?(?:クリニック|CLINIC|Clinic|医院|病院))')
DATE_RE=re.compile(r'(?:20\d{2}[/-])?\d{1,2}[/-]\d{1,2}')

QUERIES=[
 'マンジャロ クリニック 価格 キャンペーン 10mg',
 'マンジャロ 3ヶ月 12本 クリニック 限定',
 'マンジャロ 外国人 旅行者 処方 クリニック',
 '韓国人 マンジャロ クリニック 価格 九州 鳥取',
 'site:x.com マンジャロ クリニック 価格',
 'site:x.com マンジャロ 期間限定 キャンペーン',
 'site:instagram.com マンジャロ クリニック 料金',
 'site:facebook.com マンジャロ クリニック 値段',
 'site:instagram.com 마운자로 일본 클리닉',
]
SOCIAL_HOSTS=('x.com','twitter.com','instagram.com','facebook.com','m.facebook.com','search.yahoo.co.jp')
EVENT_TERMS=('キャンペーン','期間限定','タイムセール','特価','円OFF','%OFF','クーポン','初回限定','イベント','할인','期間:')


def now():return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec='seconds')
def norm_name(s):return re.sub(r'[^a-z0-9\u3040-\u30ff\u3400-\u9fff]', '',unicodedata.normalize('NFKC',s).lower())
def clean_name(s):
 s=re.sub(r'[\s\u3000]+',' ',html.unescape(s)).strip('【】〖〗「」()（）:：|·ー・-. ')
 s=re.sub(r'^(?:【公式】|〖公式〗|公式|PR|\\?n)+','',s).strip()
 # choose short last phrase (not entire advertisement)
 if len(s)>30:s=s[-30:]
 s=re.sub(r'^'+PREFIX,'',s).strip(' ・-:')
 return s

def names(text):
 # First, clinic-name followed by context; do not mine arbitrary price mentions as clinics
 text=html.unescape(text or '').replace('\n',' ')
 found=[]
 for m in list(EXPLICIT_RE.finditer(text))+list(NAME_RE.finditer(text)):
  name=clean_name(m.group(1));cn=norm_name(name)
  if 3<=len(name)<=29 and cn not in {norm_name(s) for s in STOP} and 'マンジャロ' not in name and 'おすすめ' not in name:
   if name not in found:found.append(name)
 return found[:5]

def event_hints(text):
 if not any(s in text for s in EVENT_TERMS):return None
 dates=DATE_RE.findall(text)
 return {'kind':'event_post','dates_mentioned':dates[:4],'snippet':text[:380],'price_verified':False,'note':'SNS 홍보에서 행사 감지. 12펜 적용·할인 기간 및 진료 조건 공식 확인 전'}

def entry(url,title,desc,origin,query):
 text=BeautifulSoup(html.unescape(title+' '+desc),'html.parser').get_text(' ',strip=True)
 if not re.search(TERM,text,re.I):return None
 n=names(text)
 if not n:return None
 social=('sns' if any(h in (urllib.parse.urlsplit(url).hostname or '') for h in SOCIAL_HOSTS) or 'site:' in query else 'web')
 return {'url':url,'title':title[:180],'snippet':text[:460],'clinic_names':n,'channel':social,'source':origin,'query':query,'event':event_hints(text)}

def fetch_rss(session,query,provider):
 if provider=='bing':
  url='https://www.bing.com/search?'+urllib.parse.urlencode({'q':query,'format':'rss','count':15})
 elif provider=='google_news':
  url='https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':query,'hl':'ja','gl':'JP','ceid':'JP:ja'})
 rsp=session.get(url,timeout=(7,20),headers={'Accept':'application/rss+xml,application/xml,text/xml'});rsp.raise_for_status()
 if '<rss' not in rsp.text[:600] and '<feed' not in rsp.text[:600]:raise RuntimeError('not RSS (provider may block public crawling)')
 root=ET.fromstring(rsp.content)
 for item in root.findall('.//item')[:25]:
  title=item.findtext('title','');lnk=item.findtext('link','');desc=item.findtext('description','')
  if lnk:yield title,lnk,desc

def fetch_yahoo(session,query):
 url='https://search.yahoo.co.jp/realtime/search?'+urllib.parse.urlencode({'p':query,'ei':'UTF-8'})
 rsp=session.get(url,timeout=(7,20));rsp.raise_for_status()
 soup=BeautifulSoup(rsp.text,'html.parser')
 # Public rendered HTML may include posts with the account display name and a tweet URL
 candidates=[]
 for link in soup.select('a[href]'):
  href=urllib.parse.urljoin(url,link.get('href',''))
  if 'x.com/' not in href and 'twitter.com/' not in href:continue
  label=link.get_text(' ',strip=True)
  block=link.find_parent('article') or link.find_parent('li') or link.parent
  snippet=block.get_text(' ',strip=True)[:600] if block else label
  if re.search(TERM,snippet,re.I):candidates.append((label or 'X public post',href,snippet))
 seen=set()
 for title,link,snippet in candidates[:80]:
  if link not in seen:
   seen.add(link);yield title,link,snippet

def discover(session,limit=75):
 hits=[];status=[];seen=set()
 for query in QUERIES:
  for provider in ('bing',):
   try:
    items=list(fetch_rss(session,query,provider));status.append({'source':provider,'query':query,'ok':True,'items':len(items)})
    for title,url,desc in items:
     k=url.split('#')[0]
     if k in seen:continue
     res=entry(url,title,desc,provider,query)
     if res:hits.append(res);seen.add(k)
   except Exception as e:status.append({'source':provider,'query':query,'ok':False,'reason':str(e)[:120]})
 for query in ('マンジャロ クリニック 価格','マンジャロ 期間限定 クリニック','マンジャロ 10mg'):
  try:
   items=list(fetch_yahoo(session,query));status.append({'source':'yahoo_x','query':query,'ok':True,'items':len(items)})
   for title,url,desc in items:
    if url in seen:continue
    res=entry(url,title,desc,'yahoo_x',query)
    if res:hits.append(res);seen.add(url)
  except Exception as e:status.append({'source':'yahoo_x','query':query,'ok':False,'reason':str(e)[:120]})
 # Google news can discover named clinics whose blogs are not indexed as X posts.
 for query in ('マンジャロ クリニック 料金 12本','マンジャロ 価格改定 クリニック'):
  try:
   items=list(fetch_rss(session,query,'google_news'));status.append({'source':'google_news','query':query,'ok':True,'items':len(items)})
   for title,url,desc in items:
    if url in seen:continue
    res=entry(url,title,desc,'google_news',query)
    if res:hits.append(res);seen.add(url)
  except Exception as e:status.append({'source':'google_news','query':query,'ok':False,'reason':str(e)[:120]})
 return hits[:limit],status

def merge_into_catalog(cat,rawhits,archive):
 ids={norm_name(x['name']):x for x in cat['clinics']}
 seen_names=set(ids)
 fresh=[];ts=now();today=ts[:10]
 for hit in rawhits:
  for name in hit['clinic_names']:
   key=norm_name(name)
   if key in seen_names:continue
   # do not insert very generic site labels
   if len(key)<4 or key in {norm_name(s) for s in STOP}:continue
   seen_names.add(key)
   id_='found-'+hashlib.sha1(key.encode()).hexdigest()[:12]
   row={'id':id_,'name':name,'region':'미확인','city':'미확인','mode':'미확인','foreign':'unknown','online':'unknown','ship':'unknown',
        'prices':{d:None for d in DOSES},'basis':'SNS/웹에서 신규 발굴, 가격 공식 검증 전',
        'url':hit['url'],'notes':'자동 수집된 공개 검색 결과의 병원 후보입니다. 실제 병원·가격·12펜 처방 조건을 확인해야 합니다.',
        'fees':'미확인','status':'candidate','address':'','channel':'자동 공개 '+hit['channel'].upper()+' 탐색',
        'updated':today,'discovery':'auto','price_verified':False,'events':[], 'first_seen':today}
   cat['clinics'].append(row);fresh.append({'name':name,'id':id_,'source_url':hit['url']})
  hkey=hashlib.sha1(hit['url'].encode()).hexdigest()[:20]
  old=archive.get(hkey,{});archive[hkey]={**hit,'first_seen':old.get('first_seen',ts),'last_seen':ts}
 return fresh,archive

def run():
 ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');ap.add_argument('--dry-run',action='store_true');args=ap.parse_args()
 if args.self_test:
  sample=entry('https://x.com/example/status/123','公式 ミナト自由診療クリニック マンジャロ 10mg','11/30まで 特価 キャンペーン 価格', 'test','site:x.com マンジャロ クリニック')
  assert sample and sample['clinic_names'] and sample['event']
  cat={'clinics':[]};f,a=merge_into_catalog(cat,[sample],{})
  assert len(f)==1 and cat['clinics'][0]['status']=='candidate' and cat['clinics'][0]['prices']['10'] is None
  print('self-test OK: SNS -> candidate, event hint, no unverified price');return
 cat=json.loads(CATALOG.read_text(encoding='utf-8'))
 old=json.loads(OUTPUT.read_text(encoding='utf-8')) if OUTPUT.exists() else {}
 archive={x['key']:x['hit'] for x in old.get('archive',[]) if 'key' in x}
 s=requests.Session();s.headers.update({'User-Agent':UA,'Accept-Language':'ja,ko;q=0.9,en;q=0.7'})
 hits,feeds=discover(s)
 fresh,archive=merge_into_catalog(cat,hits,archive)
 if args.dry_run:print(json.dumps({'hits':len(hits),'new_candidates':fresh,'sources':feeds},ensure_ascii=False,indent=2));return
 cat['updated']=now()[:10]
 CATALOG.write_text(json.dumps(cat,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 out={'ran_at':now(),'source_status':feeds,'hits_this_run':len(hits),'new_candidates':fresh,'archive':[{'key':k,'hit':v} for k,v in list(archive.items())[-400:]],
     'note':'Publicly indexed only; may be blocked/partial. Unverified prices never auto-enter ranking.'}
 OUTPUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('Discovered:',len(hits),'new candidates:',len(fresh),'sources OK:',sum(v['ok'] for v in feeds),'of',len(feeds))
if __name__=='__main__':run()
