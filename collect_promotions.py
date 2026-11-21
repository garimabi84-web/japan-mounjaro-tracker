#!/usr/bin/env python3
"""Collect clearly stated public SNS advertised prices as separate evidence.

An advertised price is NEVER copied into official prices or verified events.
Require an unambiguous clinic identity, dosage, yen amount, and 4/12-pen
package before displaying it as an estimated 12-week comparison.
"""
import argparse
import datetime as dt
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent
CAT=ROOT/'catalog.json'
DISC=ROOT/'discoveries.json'
DOSES={'2.5','5','7.5','10','12.5','15'}
SNS=('x.com','twitter.com','instagram.com','facebook.com','threads.net')
DOSE_RE=re.compile(r'(?<!\d)(2\.5|5(?:\.0)?|7\.5|10(?:\.0)?|12\.5|15(?:\.0)?)\s*mg',re.I)
YEN_RE=re.compile(r'(?:[¥￥]\s*([\d,]{4,8})|([\d,]{4,8})\s*(?:円|엔))')
PACK12=re.compile(r'12\s*(?:本|펜|개|キット|pens?)|3\s*(?:ヶ|か|ヵ|개)?\s*(?:月|개월)|12\s*주',re.I)
PACK4=re.compile(r'4\s*(?:本|펜|개|キット|pens?)|1\s*(?:ヶ|か|ヵ|개)?\s*(?:月|개월)|4\s*주',re.I)
PUB_DATE=re.compile(r'(?<!\d)(20\d{2})[-/.年]\s*(0?[1-9]|1[0-2])[-/.月]\s*(0?[1-9]|[12]\d|3[01])(?:日)?')
SOCIAL_PHRASE=re.compile(r'キャンペーン|価格|料金|割引|特価|12本|4本|원|円|엔|할인|행사|価格表',re.I)

def norm(s):
    return re.sub(r'[^a-z0-9ぁ-んァ-ヴ一-龥]', '',unicodedata.normalize('NFKC',str(s)).lower())

def valid_sns(url):
    try:
        p=urlsplit(url)
        return p.scheme=='https' and any((p.hostname or '')==s or (p.hostname or '').endswith('.'+s) for s in SNS)
    except ValueError:
        return False

def x_status_date(url):
    """Twitter/X Snowflake status IDs encode the UTC post creation time."""
    try:
        host=urlsplit(url).hostname or ''
        if not any(host==x or host.endswith('.'+x) for x in ('x.com','twitter.com')):
            return ''
        match=re.search(r'/status/(\d{14,22})(?:[/?#]|$)',url)
        if not match:return ''
        status_id=int(match[1])
        timestamp=((status_id >> 22)+1288834974657)/1000
        value=dt.datetime.fromtimestamp(timestamp,dt.timezone.utc)
        if dt.date(2011,1,1)<=value.date()<=dt.datetime.now(dt.timezone.utc).date()+dt.timedelta(days=1):
            return value.date().isoformat()
    except (OverflowError,ValueError,TypeError):
        pass
    return ''

def posted_date(hit):
    # The publisher's date must be explicitly labelled by the source adapter.
    # Dates in an event caption are often sale END dates, not post dates.
    for field in ('published_at','posted_date','date_published'):
        raw=str(hit.get(field,''))
        if raw:
            m=PUB_DATE.search(raw)
            if m:
                value=f'{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}'
                try:dt.date.fromisoformat(value);return value
                except ValueError:pass
    return x_status_date(str(hit.get('url','')))

def detect_offers(text):
    txt=unicodedata.normalize('NFKC',text or '')
    if not SOCIAL_PHRASE.search(txt):
        return []
    offers=[]
    for m in DOSE_RE.finditer(txt):
        dose=str(float(m[1])).removesuffix('.0')
        if dose not in DOSES:
            continue
        # Link dosage to a price in the same compact statement; stop at the
        # next dosage token to prevent one price being assigned to two doses.
        nextm=DOSE_RE.search(txt,m.end())
        cap=min(len(txt),m.end()+95,nextm.start() if nextm else len(txt))
        snippet=txt[max(0,m.start()-22):cap]
        yen_matches=list(YEN_RE.finditer(txt[m.end():cap]))
        if len(yen_matches)!=1:
            continue
        price=int((yen_matches[0][1] or yen_matches[0][2]).replace(',',''))
        if not 1800<=price<=350000:
            continue
        twelve=bool(PACK12.search(snippet))
        four=bool(PACK4.search(snippet))
        if twelve==four: # Ambiguous or missing package size
            continue
        pens=12 if twelve else 4
        offers.append({'dose':dose,'pens':pens,'price_yen':price,
                       'equivalent_12':price if pens==12 else price*3,
                       'basis':'12펜 표시 금액' if pens==12 else '4펜 가격 × 3 환산'})
    return list({(p['dose'],p['pens'],p['price_yen']):p for p in offers}.values())[:6]

def clinic_index(cat):
    index={}
    for c in cat['clinics']:
        key=norm(c.get('name',''))
        if key:
            index.setdefault(key,[]).append(c)
    return index

def run():
    ap=argparse.ArgumentParser()
    ap.add_argument('--self-test',action='store_true')
    args=ap.parse_args()
    if args.self_test:
        assert detect_offers('東京シルククリニック マンジャロ10mg 12本 90,000円')[0]['equivalent_12']==90000
        assert detect_offers('10mg 4本 30,000円')[0]['equivalent_12']==90000
        assert not detect_offers('10mg 50,000円') # no explicit unit count
        assert not detect_offers('10mg 4本 12本 30,000円') # ambiguous packaging
        assert posted_date({'posted_date':'2026-11-21T12:00:00+09:00'})=='2026-11-21'
        assert posted_date({'snippet':'2026/11/30まで'})==''
        synthetic=(1700000000000-1288834974657)<<22
        assert x_status_date('https://x.com/test/status/'+str(synthetic))=='2023-11-14'
        print('advertised-price extraction self-test passed')
        return
    cat=json.loads(CAT.read_text(encoding='utf-8'))
    disc=json.loads(DISC.read_text(encoding='utf-8'))
    by_name=clinic_index(cat)
    added=0
    for entry in disc.get('archive',[]):
        h=entry.get('hit',entry)
        url=str(h.get('url',''))
        if not valid_sns(url):
            continue
        offers=detect_offers(' '.join((h.get('title',''),h.get('snippet',''))))
        if not offers:
            continue
        names=h.get('clinic_names',[])
        matches={c['id']:c for n in names for c in by_name.get(norm(n),[])}
        # Public search captions sometimes contain an existing brand without a
        # clean name token (e.g., Korean transliteration). Require a UNIQUE
        # complete existing clinic name in the same ad, never a fuzzy match.
        if not matches:
            searchable=norm(' '.join((h.get('title',''),h.get('snippet',''))))
            matches={c['id']:c for key,clinics in by_name.items()
                     if len(key)>=7 and key in searchable for c in clinics}
        # Matching just a generic phrase, or a shared brand, is not enough.
        if len(matches)!=1:
            continue
        clinic=next(iter(matches.values()))
        promotions=clinic.setdefault('promotions',[])
        if any(p.get('url')==url for p in promotions):
            continue
        promotions.append({
            'url':url, 'source':'공개 SNS 홍보물', 'posted_date':posted_date(h),
            'first_seen':h.get('first_seen') or disc.get('ran_at','')[:10],
            'date_basis':'explicit' if h.get('published_at') or h.get('posted_date') else ('x_status_id' if x_status_date(url) else 'unknown'),
            'offers':offers, 'snippet':str(h.get('snippet',''))[:350],
            'verified':False,
            'note':'공식 가격표와 별개의 공개 홍보물 단서. 현재 유효성·조건·일괄 처방 미확인'
        })
        added+=1
    if added:
        CAT.write_text(json.dumps(cat,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('New public SNS advertisement price leads:',added)

if __name__=='__main__':
    run()
