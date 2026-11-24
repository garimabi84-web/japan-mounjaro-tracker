#!/usr/bin/env python3
"""Fail-closed, dose-specific evidence-based Mounjaro price parser.

A price can be published only with a Mounjaro-specific source fragment, dose,
explicit pen count / plan term, unambiguous tax, and a 12-week comparison
basis. Never infer quantity from nearby general prose.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
import re
import unicodedata
from bs4 import BeautifulSoup

VALID_DOSES=('2.5','5','7.5','10','12.5','15')
BRAND=re.compile(r'マンジャロ|mounjaro',re.I)
OTHER=re.compile(r'ゼップバウンド|リベルサス|オゼンピック|ウゴービ|サクセンダ|サノレックス|エンパグリフロジン|ジャディアンス|フォシーガ|リラグルチド|セマグルチド',re.I)
DOSE=re.compile(r'(?<![\d.])(2[.]5|5(?:[.]0)?|7[.]5|10(?:[.]0)?|12[.]5|15(?:[.]0)?)\s*mg\b',re.I)
YEN=re.compile(r'(?:[¥￥]\s*(\d{1,3}(?:,\d{3})+|\d{4,7})|(\d{1,3}(?:,\d{3})+|\d{4,7})\s*(?:円|[¥￥]))')
QTY=re.compile(r'(?<!\d)(1|2|4|8|12|24)\s*(?:本|キット|ペン|回(?:分)?)')
MONTH=re.compile(r'(?<!\d)(1|2|3|6|12)\s*(?:ヶ?月|か月|ヵ月|カ月|ヶ月)(?:分|分間|コース|プラン|定期|契約)?')
WEEKS=re.compile(r'(?<!\d)(1|2|4|8|12)\s*週(?:間|分)?')
INTRO=re.compile(r'初回|初月|初診限定|お試し|トライアル|キャンペーン|割引コード|クーポン|限定|特別価格',re.I)
OLD=re.compile(r'旧価格|改定前|変更前|従来価格')
EXCLUSIVE=re.compile(r'税抜|税別|税抜き|税抜価格')
INCLUSIVE=re.compile(r'税込|税込み|税こみ')
PER_MONTH=re.compile(r'月額|毎月|月あたり|1ヶ月あたり|一ヶ月あたり|月々|[/／]\s*月|月\s*単価')
PRICE_PER_PEN=re.compile(r'(?:円|[¥￥])\s*[/／]\s*(?:本|ペン|キット)|(?:1本|一本)\s*(?:あたり|当たり|単価|価格)')
# Minimum order quantity (2本ずつ販売) must never be treated as
# quantity included in a nearby per-pen price (8,000円/本).
ORDER_ONLY=re.compile(r'^\s*(?:ずつ|単位(?:で|から)?|ごと|以上|から(?:販売|処方)|より(?:販売|処方))')
UNPRICED_BOX=re.compile(r'(?:円|[¥￥])\s*[/／]\s*(?:箱|セット)')

MONEY_FORMAT=re.compile(r'^\s*(?:[¥￥]?\s*[\d,]+\s*(?:円|[¥￥])?\s*(?:\([^)]*\))?)\s*$')

def norm(x):
    return unicodedata.normalize('NFKC',str(x or '')).replace('，',',').replace('\xa0',' ')

def price_value(cell):
    hits=list(YEN.finditer(norm(cell)))
    if len(hits)!=1:return None
    value=int((hits[0][1] or hits[0][2]).replace(',',''))
    return value if 1500<=value<=900000 else None

def dose_key(text):
    hit=DOSE.search(norm(text))
    return str(float(hit[1])).removesuffix('.0') if hit else None

def quantity(text, *, allow_month=True):
    """Return (pen_count, origin) only for explicit source unit strings."""
    text=norm(text)
    # A plan lasting 6 or 12 months is not a valid 3-month purchase offer,
    # even when a per-month payment happens to be low.
    units={int(m[1]) for m in QTY.finditer(text)
           if not ORDER_ONLY.match(text[m.end():])}
    # "8,000円/本" is explicitly one pen, regardless of minimum
    # purchase sizes such as "2本ずつ販売" in adjacent cells.
    if PRICE_PER_PEN.search(text):units.add(1)
    units.update(int(m[1]) for m in WEEKS.finditer(text))
    if allow_month:
        units.update(int(m[1])*4 for m in MONTH.finditer(text))
    if len(units)==1:
        n=next(iter(units))
        if n in (1,2,4,8,12):return n,'명시된 펜·주수/기간'
    return None,''

def tax_price(n,text):
    text=norm(text)
    if EXCLUSIVE.search(text) and not INCLUSIVE.search(text):
        return round(n*1.1),'세전 가격에 소비세 10% 가산'
    return n,'세금 포함 여부는 병원 안내 확인' if not INCLUSIVE.search(text) else '세금 포함'

def plan(text, *, header=False):
    """12 pens total or a 3-month contract's monthly payment only."""
    text=norm(text)
    mths={int(m[1]) for m in MONTH.finditer(text)}
    if any(m>3 for m in mths):return None,'장기구독'
    # A table header such as "3ヶ月分" paired with "19,600円/月"
    # gives a monthly rate, not the total 12-pen package price.
    if mths=={3} and PER_MONTH.search(text):return 12,'3개월 계약 월액'
    # A two-month monthly rate cannot be treated as the total price of 8 pens,
    # nor is it proof that a 3-month purchase is available at that rate.
    if mths=={2} and PER_MONTH.search(text):return None,'2개월 월액 (비교 제외)'
    if len(mths)>1 and PER_MONTH.search(text):return None,'기간 혼재 월액'
    return None,''

def collect(candidates,dose,raw,unit,fragment,origin,context,source_url=''):
    if dose not in VALID_DOSES or not isinstance(raw,int):return
    pens,kind=unit
    if pens not in (1,2,4,8,12):return
    if INTRO.search(fragment) or OLD.search(fragment) or INTRO.search(context) or OLD.search(context):return
    if OTHER.search(fragment):return
    # Monthly subscription for 6/12 month contract is NOT a 12-pen price.
    lower=norm(context+' '+fragment)
    if PER_MONTH.search(lower) and any(int(m[1])>3 for m in MONTH.finditer(lower)):return
    # A monthly rate must not be interpreted as the total payment for
    # 8/12 pens even if the column header says 2/3 months.
    if PER_MONTH.search(lower) and pens>4 and kind!='3개월 계약 월액':return
    amount,tax=tax_price(raw,fragment+' '+context)
    if kind=='3개월 계약 월액':
        comparable=amount*3;rank=5
    else:
        comparable=round(amount*12/pens)
        rank={12:6,8:4,4:3,2:2,1:1}[pens]
    if not 12000<=comparable<=1200000:return
    candidates[dose].append({
        'amount':comparable,'source_amount':raw,'source_pens':pens,
        'source_type':kind,'method':('3개월 계약 월액 × 3' if kind=='3개월 계약 월액' else '12펜 직접금액' if pens==12 else f'{pens}펜 기준 12펜 환산'),
        'tax':tax,'source_fragment':norm(fragment)[:180],
        'source_url':source_url,'rank':rank,'source_kind':origin
    })

def parse_official_v2(source,source_url=''):
    soup=BeautifulSoup(source,'html.parser')
    for t in soup(['script','style','nav','footer','noscript','svg']):
        t.decompose()
    if not BRAND.search(norm(soup.get_text(' ',strip=True))):return {},'',{}
    found=defaultdict(list)
    for table in soup.select('table'):
        rows=[]
        for tr in table.select('tr'):
            cells=[norm(c.get_text(' ',strip=True)) for c in tr.find_all(['td','th'],recursive=False)]
            if cells:rows.append((cells,any(c.name=='th' for c in tr.find_all(['td','th'],recursive=False))))
        if not rows:continue
        title_tag=table.find_previous(['h1','h2','h3','h4','h5','h6'])
        heading=norm(title_tag.get_text(' ',strip=True)) if title_tag else ''
        top=' '.join(rows[0][0])
        table_title=norm(table.get('aria-label',''))+' '+norm(table.get('summary',''))
        table_branded=bool(BRAND.search(heading+' '+top+' '+table_title) and not OTHER.search(heading))
        any_branded=any(BRAND.search(' '.join(r)) for r,_ in rows)
        if not (table_branded or any_branded):continue
        if OTHER.search(heading) and not any_branded:continue
        # Many Japanese price tables have no header row at all. Their first
        # row is often "マンジャロ | 2.5mg/1本 | ¥6,050".
        # Treating that data row as headers leaks its "1本" unit into all
        # later 4-pen rows and creates a 4x price overstatement.
        first_is_offer=bool(DOSE.search(top) and YEN.search(top))
        headers=(rows[0][0] if not first_is_offer and
                 (rows[0][1] or bool(re.search(r'用量|規格|本数|容量|価格|料金',top)))
                 else [])
        start=1 if headers else 0
        current=table_branded
        # A pen-unit statement in this table's heading/header may be applied
        # only to this same table, never to arbitrary adjacent paragraphs.
        # A first offer row is not a header and cannot supply units to later rows.
        shared_unit=(quantity(heading+' '+top) if headers and not OTHER.search(top)
                     else quantity(heading) if heading and not first_is_offer else (None,''))
        for cells,_ in rows[start:]:
            full=' '.join(cells)
            if OTHER.search(full):
                if OTHER.search(cells[0]):current=False
                continue
            if BRAND.search(cells[0]):current=True
            if not current:continue
            # A list of strengths followed by one "from ¥..." price is
            # NOT a dose-specific price. This caused Oji Kaneda's "2.5,
            # 5 and 7.5mg, from ¥12,300/month" to be misassigned to 7.5mg.
            if len(list(DOSE.finditer(full)))>1:continue
            if re.search(r'約\s*[¥￥]?\s*[\d,]+\s*円|[¥￥]?[\d,]+\s*円\s*[〜～~]|\d+円\s*から|\d+円\s*より',full):
                continue
            dose=dose_key(full)
            if dose is None:continue
            price_cols=[(i,price_value(cell)) for i,cell in enumerate(cells) if price_value(cell)]
            if not price_cols:continue
            dose_pos=next((i for i,c in enumerate(cells) if dose_key(c)),0)
            descriptor=' '.join(c for i,c in enumerate(cells)
                                if i not in {j for j,_ in price_cols})
            qty_cells=[quantity(c) for i,c in enumerate(cells) if i not in {j for j,_ in price_cols} and i!=dose_pos]
            unit_column=next((z for z in qty_cells if z[0] is not None), (None,''))
            for j,raw in price_cols:
                if j==dose_pos and len(cells)>1:continue
                label=headers[j] if j<len(headers) else ''
                # A specific price-column term takes precedence over a table
                # footer or plan duration appearing somewhere else on page.
                if INTRO.search(label+' '+cells[j]) or OLD.search(label):continue
                if OTHER.search(label):continue
                # Per-box prices have no usable pen count without an
                # explicit pack size (unrelated minimum order does not count).
                if UNPRICED_BOX.search(cells[j]) and not quantity(label)[0] and not quantity(cells[j])[0]:
                    continue
                plan_info=plan(label+' '+cells[j],header=True)
                if plan_info[0]:
                    unit=plan_info
                else:
                    if plan_info[1]:continue
                    unit=quantity(cells[j])
                    if unit[0] is None:unit=quantity(label)
                    if unit[0] is None:unit=unit_column
                    if unit[0] is None:unit=quantity(cells[dose_pos])
                    if unit[0] is None:unit=shared_unit
                # A 6/12mo subscription price column can never fall back
                # to 4 pens just because the row also says 4 pens.
                if re.search('定期|プラン|契約|コース',label) and any(int(x[1])>3 for x in MONTH.finditer(label)):
                    continue
                if unit[0] is None:continue
                # Do not mistake a dosage row with e.g "10mg" for 10 pens.
                # Evidence must cite THIS price column, including its header.
                # The former whole-row quote obscured that 19,600円/月 was
                # a monthly rate in the "3ヶ月分" column.
                evidence_parts=[cells[dose_pos],label,cells[j]]
                evidence_parts.extend(c for i,c in enumerate(cells) if i not in (dose_pos,j) and quantity(c)[0] is not None)
                fragment=' | '.join(dict.fromkeys(x for x in evidence_parts if x))
                context=label+' '+heading
                collect(found,dose,raw,unit,fragment,'official_table',context,source_url)
    # Small explicit Mounjaro paragraphs and inline price rows. Heading scopes
    # do not leak into a later unrelated medical product.
    scoped=False;age=0
    for node in soup.select('h1,h2,h3,h4,h5,p,li,dd'):
        if node.find_parent('table'):continue
        txt=norm(node.get_text(' ',strip=True))
        if node.name.startswith('h'):
            scoped=bool(BRAND.search(txt) and not OTHER.search(txt))
            age=0
            continue
        if OTHER.search(txt):
            scoped=False;age=0;continue
        if len(txt)>380:scoped=False;continue
        if BRAND.search(txt):
            # A product comparison ("Zepbound has the same ingredient as
            # Mounjaro") must never activate Mounjaro-price scope.
            is_explicit_price=bool(DOSE.search(txt) and YEN.search(txt))
            is_product_label=bool(re.fullmatch(
                r'(?:マンジャロ|mounjaro)(?:\s*(?:料金|価格|注射|費用|処方|診療|薬代|料金表))*',
                txt,re.I))
            scoped=is_explicit_price or is_product_label
            age=0
            if not scoped:continue
        elif not scoped:continue
        elif not dose_key(txt):
            age+=1
            if age>2:scoped=False
            continue
        if not dose_key(txt):continue
        # Limit each price to its dose segment, so prices on an adjacent dose
        # cannot be accidentally assigned across columns.
        matches=list(DOSE.finditer(txt))
        if not matches:continue
        # "2.5, 5, 7.5mg: from ¥12,300" denotes a starting price for
        # the group, NOT the last listed dosage. Reject approximation/ranges.
        if re.search(r'約\s*[¥￥]?\s*[\d,]+\s*円|[¥￥]?[\d,]+\s*円\s*[〜～~]|\d+円\s*から|\d+円\s*より',txt):
            continue
        if len(matches)>1:
            all_segments=[txt[m.start():matches[ix+1].start() if ix+1<len(matches) else len(txt)]
                          for ix,m in enumerate(matches)]
            if any(price_value(seg) is None or quantity(seg)[0] is None for seg in all_segments):
                continue
        for ix,m in enumerate(matches):
            dose=str(float(m[1])).removesuffix('.0')
            seg=txt[m.start():matches[ix+1].start() if ix+1<len(matches) else len(txt)]
            raw=price_value(seg)
            if raw is None:continue
            info=plan(seg)
            if info[1] and info[0] is None:continue
            unit=info if info[0] else quantity(seg)
            if unit[0] is None:continue
            collect(found,dose,raw,unit,seg,'official_inline',txt[:80],source_url)
    prices={};evidence={}
    for dose,options in found.items():
        top=max(x['rank'] for x in options)
        finalists=[x for x in options if x['rank']==top]
        # Different amounts at the same strength+unit without explicit
        # regular/initial distinctions are ambiguous, not verified.
        if len({x['amount'] for x in finalists})!=1:continue
        winner=finalists[0]
        prices[dose]=winner['amount']
        evidence[dose]={k:v for k,v in winner.items() if k!='rank'}
    basis='공식 홈페이지에서 제품·용량·판매수량·판매기간을 독립 확인한 12펜 금액/환산' if prices else ''
    return prices,basis,evidence

def self_test():
    fixtures=[
        ('sakai',"""<h2>マンジャロ</h2><table><tr><th>用量</th><th>本数(1ヶ月分)</th><th>価格(税込)</th></tr>
        <tr><td>2.5mg</td><td>4本</td><td>19,800円</td></tr>
        <tr><td>5mg</td><td>4本</td><td>40,000円</td></tr>
        <tr><td>7.5mg</td><td>4本</td><td>55,000円</td></tr>
        <tr><td>10mg</td><td>4本</td><td>66,000円</td></tr></table>""",
         {'2.5':59400,'5':120000,'7.5':165000,'10':198000}),
        ('wclinic_no_header',"""<h2>マンジャロの料金のご案内</h2><table>
         <tr><td>マンジャロ</td><td>2.5mg/1本</td><td>¥6,050</td></tr>
         <tr><td></td><td>2.5mg/1本(1ヶ月分)(初回価格)</td><td>¥5,720</td></tr>
         <tr><td></td><td>2.5mg/4本(1ヶ月分)</td><td>¥22,880</td></tr>
         <tr><td></td><td>5mg/1本</td><td>¥8,580</td></tr>
         <tr><td></td><td>5mg/4本(1ヶ月分)</td><td>¥33,000</td></tr></table>""",
         {'2.5':68640,'5':99000}),
        ('wclinic',"""<h2>マンジャロ料金</h2><table><tr><th>規格</th><th>価格</th></tr>
         <tr><td>2.5mg/1本</td><td>6,050円</td></tr>
         <tr><td>2.5mg/1本(初回価格)</td><td>5,720円</td></tr>
         <tr><td>2.5mg/4本(1ヶ月分)</td><td>22,880円</td></tr>
         <tr><td>5mg/1本</td><td>8,580円</td></tr>
         <tr><td>5mg/4本(1ヶ月分)</td><td>33,000円</td></tr></table>""",
         {'2.5':68640,'5':99000}),
        ('oji_starting_price',"""<h3>痩身・ダイエット</h3>
          <p>マンジャロ皮下注(取扱い:2.5mg、5.0mg、7.5mg)1ヶ月分</p>
          <p>約12,300円〜</p>""",{}),
        ('oji_one_paragraph',"""<h2>マンジャロ</h2>
          <p>マンジャロ皮下注(取扱い:2.5mg、5.0mg、7.5mg)1ヶ月分 約12,300円〜</p>""",{}),
        ('explicit_multi_dose',"""<h2>マンジャロ</h2>
          <p>2.5mg(4本)10,000円 5mg(4本)20,000円</p>""",
          {'2.5':30000,'5':60000}),
        ('zenbound',"""<h2>ゼップバウンド</h2><p>マンジャロと同成分</p>
         <table><tr><th>エンパグリフロジン</th><th>1ヶ月</th></tr><tr><td>10mg</td><td>11,000円</td></tr></table>""",{}),
        ('zepbound_context',"""<h3>ゼップバウンド</h3>
          <p>糖尿病治療薬「マンジャロ」と同成分。</p>
          <p>10mg（1ヶ月分）33,000円</p>""",{}),

        ('no_header_unit_leak',"""<h2>マンジャロ</h2><table>
          <tr><td>マンジャロ</td><td>5mg/1本</td><td>8,000円</td></tr>
          <tr><td></td><td>7.5mg</td><td>12,000円</td></tr></table>""",{'5':96000}),
        ('femuse_price_table',"""<h3>注射薬（マンジャロ）</h3><table>
          <tr><th>用量</th><th>1ヶ月分</th><th>2ヶ月分</th><th>3ヶ月分</th><th>6ヶ月分</th></tr>
          <tr><td>2.5mg</td><td>12,600円/月</td><td>11,900円/月</td><td>11,200円/月</td><td>10,500円/月</td></tr>
          <tr><td>5.0mg</td><td>21,000円/月</td><td>20,300円/月</td><td>19,600円/月</td><td>18,900円/月</td></tr>
          <tr><td>7.5mg</td><td>29,400円/月</td><td>28,700円/月</td><td>28,000円/月</td><td>27,300円/月</td></tr></table>""",
         {'2.5':33600,'5':58800,'7.5':84000}),
        ('femuse_monthly_headers',"""<h3>マンジャロ</h3><table>
          <tr><th>用量</th><th>月額(定価)</th><th>2ヶ月セット/月</th><th>3ヶ月セット/月</th><th>6ヶ月セット/月</th></tr>
          <tr><td>5.0mg</td><td>¥21,000</td><td>¥20,300</td><td>¥19,600</td><td>¥18,900</td></tr></table>""", {'5':58800}),
        ('two_month_only_monthly_rate',"""<h3>マンジャロ</h3><table>
          <tr><th>用量</th><th>2ヶ月セット/月</th></tr>
          <tr><td>5mg</td><td>20,300円</td></tr></table>""",{}),
        ('yokoi_min_order_is_not_pack_price',"""<h2>マンジャロ</h2>
          <table><tr><th>用量</th><th>料金(税込)</th><th>備考</th></tr>
          <tr><td>2.5mg</td><td>4,500円/本(税込)</td><td>2本ずつの販売となります。</td></tr>
          <tr><td>5mg</td><td>8,000円/本(税込)</td><td>2本ずつの販売となります。</td></tr>
          <tr><td>7.5mg</td><td>12,000円/本(税込)</td><td>2本ずつの販売となります。</td></tr>
          <tr><td>10mg</td><td>16,000円/本(税込)</td><td>2本ずつの販売となります。</td></tr></table>""",
          {'2.5':54000,'5':96000,'7.5':144000,'10':192000}),
        ('yokoi_per_box_requires_explicit_pack_size',"""<h2>マンジャロ</h2>
          <table><tr><th>項目</th><th>料金</th><th>料金</th></tr>
          <tr><td>5mg</td><td>8,000円/本</td><td>16,000円/箱</td></tr>
          <tr><td>10mg</td><td>16,000円/本</td><td>32,000円/箱</td></tr></table>""",
          {'5':96000,'10':192000}),
        ('reject_minimum_order_without_price_unit',"""<h2>マンジャロ</h2>
          <table><tr><th>用量</th><th>価格</th><th>備考</th></tr>
          <tr><td>5mg</td><td>8,000円</td><td>2本ずつの販売</td></tr></table>""",{}),
        ('unknownunit',"""<h2>マンジャロ</h2><table><tr><th>用量</th><th>価格</th></tr>
         <tr><td>10mg</td><td>30,000円</td></tr></table>""",{}),
        ('haab',"""<h2>マンジャロ料金</h2><table><tr><th>用量</th><th>1本価格</th></tr>
         <tr><td>5mg</td><td>12,000円</td></tr></table>""",{'5':144000}),
        ('subscription',"""<h2>マンジャロ料金</h2><table>
         <tr><th>用量</th><th>3ヶ月定期 月額</th><th>6ヶ月定期 月額</th><th>12ヶ月定期 月額</th></tr>
         <tr><td>5mg</td><td>19,600円</td><td>18,900円</td><td>17,200円</td></tr></table>""",
         {'5':58800}),
        ('monthlyvsbulk',"""<h2>マンジャロ</h2><table>
          <tr><th>用量</th><th>4本(1ヶ月分)</th><th>12本(3ヶ月分)</th></tr>
          <tr><td>10mg</td><td>27,500円</td><td>82,500円</td></tr></table>""",{'10':82500}),
        ('unrelatedmonths',"""<p>3ヶ月の治療を考えましょう。</p>
          <h2>マンジャロ</h2><table><tr><th>用量</th><th>価格</th></tr>
          <tr><td>5mg</td><td>24,000円</td></tr></table>""",{}),
        ('multi_med',"""<h2>マンジャロ</h2><table><tr><th>製品</th><th>用量</th><th>本数</th><th>価格</th></tr>
          <tr><td>マンジャロ</td><td>5mg</td><td>4本</td><td>20,000円</td></tr>
          <tr><td>ゼップバウンド</td><td>10mg</td><td>4本</td><td>30,000円</td></tr></table>""",
         {'5':60000}),
        ('monthly_4_pens',"""<h3>マンジャロ</h3><p>5mg (4週分) 60,000円</p>""",{'5':180000}),
        ('annual_monthly_only',"""<h3>マンジャロ</h3><table><tr><th>容量</th><th>12ヶ月定期(月額)</th></tr>
          <tr><td>5mg</td><td>39,840円</td></tr></table>""",{}),
        ('tax_exclusive',"""<h3>マンジャロ</h3><table><tr><th>容量</th><th>4本(税込)</th></tr>
          <tr><td>5mg</td><td>22,000円</td></tr></table>""",{'5':66000}),
        ('old_price',"""<h3>マンジャロ</h3><table><tr><th>用量</th><th>改定前4本</th><th>通常4本</th></tr>
          <tr><td>5mg</td><td>18,000円</td><td>24,000円</td></tr></table>""",{'5':72000}),
    ]
    for name,html,expected in fixtures:
        got,_,proof=parse_official_v2(html)
        assert got==expected,(name,got,expected,proof)
        for dose,price in got.items():
            assert proof[dose]['source_pens'] in (1,2,4,8,12),(name,proof)
            assert proof[dose]['amount']==price,(name,proof)
    print('Verified strict V2 parser:',len(fixtures),'mixed-package/plan/medicine cases')
if __name__=='__main__':self_test()
