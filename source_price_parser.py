#!/usr/bin/env python3
"""Extract conservative 12-pen comparable amounts from a clinic's OWN HTML.

Supports explicit per-pen, four-week and twelve-week pricing from tables or
inline text.  Does not take any amount from third-party comparators.
"""
import re
import unicodedata
from bs4 import BeautifulSoup

DOSES={'2.5','5','7.5','10','12.5','15'}
DOSE_RE=re.compile(r'(?<![\d.])(2\.5|5(?:\.0)?|7\.5|10(?:\.0)?|12\.5|15(?:\.0)?)\s*mg\b',re.I)
MONEY=re.compile(r'(?:¥\s*(\d{1,3}(?:,\d{3})+|\d{4,6})|(\d{1,3}(?:,\d{3})+|\d{4,6})\s*(?:円|¥))')
# Exact Mounjaro brand is required: tirzepatide / Zepbound are NOT aliases.
DRUG=re.compile(r'マンジャロ|mounjaro',re.I)
OTHER_DRUG=re.compile(r'リベルサス|オゼンピック|ウゴービ|ゼップバウンド|サクセンダ|サノレックス|エンパグリフロジン|フォシーガ|ジャディアンス|リラグルチド|セマグルチド')
PROMO=re.compile(r'キャンペーン|クーポン|初回限定|期間限定')
PACKS=[
 (12,re.compile(r'(?:12\s*(?:本|キット|ペン)|(?:3\s*(?:ヶ月|か月|ヵ月|カ月))分?|12\s*週間?|12\s*週分)')),
 (8,re.compile(r'(?:8\s*(?:本|キット|ペン)|8\s*週間?|8\s*週分)')),
 (4,re.compile(r'(?:4\s*(?:本|キット|ペン)|4\s*週間?|4\s*週分|(?:1\s*(?:ヶ月|か月|ヵ月|カ月))分?)')),
 (2,re.compile(r'(?:2\s*(?:本|キット|ペン)|2\s*週間?|2\s*週分)')),
 (1,re.compile(r'(?:1\s*(?:本|キット|ペン)|1\s*本あたり|1\s*本当たり|1\s*本単価|1\s*本価格)')),
]
def normalize(text):
    return unicodedata.normalize('NFKC',str(text or '')).replace('，',',').replace('\xa0',' ')

def amount(text):
    m=MONEY.search(normalize(text))
    if not m:return None
    val=int((m[1] or m[2]).replace(',',''))
    return val if 1800<=val<=350000 else None

def pack_factor(text):
    s=normalize(text)
    for pens,pattern in PACKS:
        if pattern.search(s):return 12/pens
    return None

def extraction_per_segment(text, shared_pack=None):
    """Extract price only when dosage, price and package are clearly linked."""
    text=normalize(text)
    doses=list(DOSE_RE.finditer(text))
    result={}
    for i,m in enumerate(doses):
        d=str(float(m[1])).removesuffix('.0')
        if d not in DOSES:continue
        tail=text[m.end():(doses[i+1].start() if i+1<len(doses) else len(text))]
        tail=tail[:145]
        if OTHER_DRUG.search(tail[:65]):continue
        prices=list(MONEY.finditer(tail))
        if not prices:continue
        # A dose with multiple amounts (old/current; per pen/per month)
        # must identify a package locally; never guess which price is current.
        possible=[]
        for pm in prices[:4]:
            value=int((pm[1] or pm[2]).replace(',',''))
            if not 1800<=value<=350000:continue
            context=tail[max(0,pm.start()-32):pm.end()+5]
            factor=pack_factor(context)
            if factor is None:factor=pack_factor(tail[:pm.end()+5])
            if factor is None:factor=shared_pack
            if factor is None:continue
            possible.append((round(value*factor),factor))
        if not possible:continue
        # Prefer the earliest explicit unit-price within an inline dose segment.
        # For ambiguous unrelated amounts, avoid claiming a particular amount.
        unique={x[0] for x in possible}
        if len(unique)>1:
            # A single per-pen figure followed by an aggregate period price
            # (sometimes printed with broken comma grouping) has explicit
            # priority. Do not pick between two competing same-unit prices.
            if possible[0][1]==12 and all(x[1]!=12 for x in possible[1:]):
                val=possible[0][0]
            else:continue
        else:val=possible[0][0]
        if val<=350000*3:result[d]=val
    return result

def extract_official(source):
    soup=BeautifulSoup(source,'html.parser')
    for tag in soup(['script','style','nav','footer','noscript','svg']):
        tag.decompose()
    plain=normalize(soup.get_text(' ',strip=True))
    if not DRUG.search(plain):return {},''
    found={}; sources={}
    for table in soup.select('table'):
        cells=[[normalize(c.get_text(' ',strip=True)) for c in tr.find_all(['th','td'],recursive=False)]
               for tr in table.select('tr')]
        cells=[x for x in cells if x]
        if not cells:continue
        body=normalize(table.get_text(' ',strip=True))
        # Identify the drug from the table or its nearby introduction, not
        # simply anywhere on the webpage.
        offset=plain.find(body[:65])
        previous=plain[max(0,offset-600):offset] if offset>=0 else ''
        # A Mounjaro mention in a *different medicine's explanation* cannot
        # authorize price extraction from this table. Only a nearby Mounjaro
        # heading or an explicitly branded row identifies the drug.
        heading=table.find_previous(['h1','h2','h3','h4','h5','h6','strong','b'])
        heading_text=normalize(heading.get_text(' ',strip=True)) if heading else ''
        header_text=' '.join(cells[0])
        branded_rows=any(DRUG.search(c[0]) and not OTHER_DRUG.search(c[0])
                         for c in cells if c)
        branded_heading=bool(DRUG.search(heading_text) and not OTHER_DRUG.search(heading_text))
        branded_header=bool(DRUG.search(header_text) and not OTHER_DRUG.search(header_text))
        if not (branded_rows or branded_heading or branded_header):continue
        if OTHER_DRUG.search(heading_text) and not branded_rows:continue
        pack=pack_factor(previous[-175:]) or pack_factor(' '.join(cells[0]))
        headers=cells[0]
        in_mounjaro=branded_heading or branded_header
        for row in cells[1:]:
            joined=' '.join(row)
            if OTHER_DRUG.search(row[0]):
                in_mounjaro=False
                continue
            if DRUG.search(row[0]):in_mounjaro=True
            # One table cell can contain the whole price list for Mounjaro.
            if in_mounjaro and DRUG.search(row[0]) and len(row)>1:
                for col in row[1:]:
                    parsed=extraction_per_segment(col,pack)
                    for d,v in parsed.items():
                        if d not in found:
                            found[d]=v;sources[d]='공식 병원 가격표 · 용량별'
            # Standard dose rows can omit drug name if table is drug-specific.
            m=DOSE_RE.search(row[0])
            if not m or len(row)<2:continue
            d=str(float(m[1])).removesuffix('.0')
            if d not in DOSES:continue
            if in_mounjaro and not OTHER_DRUG.search(joined):
                price_cells=row[1:]
                # Explicit old/new table: select the current column, not old price.
                header_line=' '.join(headers)
                if len(price_cells)>1 and re.search('改定前|旧価格|変更前',header_line):
                    price_cells=[price_cells[-1]]
                elif len(price_cells)>1 and not re.search('12本|3ヶ月|1ヶ月|4本',header_line):
                    # Multiple unlabelled prices cannot be safely ranked.
                    continue
                price=amount(price_cells[-1])
                factor=pack_factor(row[0]) or pack_factor(price_cells[-1]) or pack
                if price is not None and factor and d not in found:
                    found[d]=round(price*factor);sources[d]='공식 병원 가격표 · 용량별'
    # Inline prices from an explicit Mounjaro paragraph or an adjacent dosage
    # paragraph immediately following a Mounjaro one.
    recent_drug=False;gap=0
    for node in soup.select('h1,h2,h3,h4,p,li,dd'):
        if node.find_parent(['table','nav','footer']):continue
        content=normalize(node.get_text(' ',strip=True))
        if len(content)>400:recent_drug=False;gap=0;continue
        # A Zepbound description saying "same ingredient as Mounjaro"
        # is not a Mounjaro price heading; reject it before drug detection.
        if OTHER_DRUG.search(content):
            recent_drug=False;gap=0;continue
        if node.name.startswith('h'):
            recent_drug=bool(DRUG.search(content));gap=0
        elif DRUG.search(content):
            # A branded price or a short standalone product label is valid;
            # generic comparative text discussing Mounjaro is not.
            recent_drug=bool(DOSE_RE.search(content) and MONEY.search(content)
                             or re.fullmatch(r'(?:マンジャロ|mounjaro)(?:\s*(?:料金|価格|注射|診療))*',content,re.I))
            gap=0
        elif not DOSE_RE.search(content):
            gap+=1
            if gap>3:recent_drug=False
            continue
        if not recent_drug:continue
        block=extraction_per_segment(content)
        for d,v in block.items():
            if d not in found:found[d]=v;sources[d]='공식 홈페이지 · 용량별 명시 가격'
    return found,' · '.join(sorted(set(sources.values())))+' (12펜 기준 단위 환산; 일괄 처방 가능 여부 별도)'

def self_test():
    html='<h2>メディカルダイエット</h2><table><tr><th>商品</th><th>料金</th></tr><tr><td>リベルサス</td><td>7mg（30日分）15,000円</td></tr><tr><td>マンジャロ</td><td>2.5mg（4週分）15,000円 5mg（4週分）30,000円 7.5mg（4週分）45,000円 10mg（4週分）60,000円</td></tr></table>'
    x,_=extract_official(html)
    assert x=={'2.5':45000,'5':90000,'7.5':135000,'10':180000},x
    inline='<h2>マンジャロ</h2><p>②GLP-1皮下注射（マンジャロ）2.5㎎ 1本3,500円（税込）1か月1,4000円</p><p>5.0mg 1本7,000円（税込）</p>'
    x,_=extract_official(inline)
    assert x=={'2.5':42000,'5':84000},x
    table='<h2>マンジャロ料金</h2><p>表示価格はすべて税込・4本／4週間分です</p><table><tr><th>用量</th><th>改定前</th><th>9月1日以降</th></tr><tr><td>10 mg</td><td>35,000円</td><td>33,000円</td></tr></table>'
    x,_=extract_official(table)
    assert x.get('10')==99000,x
    heading='<h2>マンジャロ価格</h2><p>10mg (4週分) 60,000円</p>'
    x,_=extract_official(heading)
    assert x.get('10')==180000,x
    sanage='''<h2>メディカルダイエット</h2>
      <h3>お薬の種類</h3><p>チルゼパチド（ゼップバウンド）</p>
      <p>糖尿病治療薬「マンジャロ」と同成分です。</p>
      <h3>費用について</h3><h4>料金表</h4>
      <table><tr><th>チルゼパチド（1ヶ月分）</th></tr>
       <tr><td>2.5mg</td><td>24,000円</td></tr>
       <tr><td>5mg</td><td>32,500円</td></tr>
       <tr><td>7.5mg</td><td>39,000円</td></tr></table>
       <table><tr><th>エンパグリフロジン</th></tr>
       <tr><td>10mg(1ヶ月分)</td><td>11,000円</td></tr></table>'''
    x,_=extract_official(sanage)
    assert x=={}, 'Zepbound and empagliflozin leaked into Mounjaro: '+repr(x)
    adjacent='''<h2>マンジャロ料金</h2><table><tr><th>用量</th><th>4週間分</th></tr>
      <tr><td>5mg</td><td>32,000円</td></tr></table>
      <h2>エンパグリフロジン</h2><table><tr><th>用量</th><th>1ヶ月分</th></tr>
      <tr><td>10mg</td><td>11,000円</td></tr></table>'''
    x,_=extract_official(adjacent)
    assert x=={'5':96000}, x
    wrong='<h2>美容料金</h2><p>オゼンピック 5mg 1本10,000円</p><p>マンジャロに関する注意喚起</p>'
    x,_=extract_official(wrong)
    assert x=={},x
    print('Official 12-pen parser tests passed for multi-dose cells, inline per-pen and amended tables')
if __name__=='__main__':self_test()
