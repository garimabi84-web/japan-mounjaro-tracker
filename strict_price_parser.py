#!/usr/bin/env python3
"""Version 2: evidence-first Mounjaro source price parser.

No unit, no quoted price; never pick a minimum or a last column from competing
subscription terms. Return per-dose raw amount, unit and exact row context so
the audit can independently decide which values are comparable.
"""
from __future__ import annotations
import re
import unicodedata
from bs4 import BeautifulSoup

DOSES=("2.5","5","7.5","10","12.5","15")
BRAND=re.compile(r"マンジャロ|mounjaro",re.I)
OTHER=re.compile(r"リベルサス|オゼンピック|ウゴービ|ゼップバウンド|サクセンダ|サノレックス|エンパグリフロジン|フォシーガ|ジャディアンス|リラグルチド|セマグルチド|カナグル|スーグラ",re.I)
DOSE=re.compile(r"(?<![\d.])(2\.5|5(?:\.0)?|7\.5|10(?:\.0)?|12\.5|15(?:\.0)?)\s*(?:mg|㎎)",re.I)
YEN=re.compile(r"(?:[¥￥]\s*(\d{1,3}(?:,\d{3})+|\d{4,7})|(\d{1,3}(?:,\d{3})+|\d{4,7})\s*(?:円|[¥￥]))")
PACK_ONE=re.compile(r"(?:1\s*(?:本|ペン|キット)(?:当たり|あたり|あたりの価格|の価格|単価)?|(?:単価|価格)\s*[/／]?\s*本|[/／]\s*本\b|1\s*(?:回分|回用))")
PACK_FOUR=re.compile(r"(?:4\s*(?:本|ペン|キット|回分|週分)|4\s*週間?分?|(?:1|一)\s*(?:ヶ|か|ヵ|カ)?月(?:分|セット)?|1\s*month)",re.I)
PACK_TWELVE=re.compile(r"(?:12\s*(?:本|ペン|キット|回分|週分)|12\s*週間?分?|3\s*(?:ヶ|か|ヵ|カ)?月(?:分|セット|定期)?|3\s*months?)",re.I)
OTHER_PLAN=re.compile(r"(?:2|6|8|9|12|18|24)\s*(?:ヶ|か|ヵ|カ)?月|(?:2|6|8|9|24)\s*(?:本|ペン|キット|週間?|週分)",re.I)
MONTHLY_RATE=re.compile(r"月額|毎月|1ヶ月あたり|ひと月あたり|月あたり|円\s*[/／]\s*月|[/／]\s*月\b|月\s*[/／]\s*単位")
PROMO=re.compile(r"初回限定|キャンペーン|クーポン|期間限定|モニター価格|お試し価格|初回価格|初月",re.I)
EX_TAX=re.compile(r"税抜|税別|税抜き|消費税別")
IN_TAX=re.compile(r"税込|税こみ|消費税込")
HEADINGS=["h1","h2","h3","h4","h5","h6"]

def norm(s):
    return unicodedata.normalize("NFKC",str(s or "")).replace("\xa0"," ").replace("，",",")

def num(s):
    matches=[int((m[1] or m[2]).replace(",","")) for m in YEN.finditer(norm(s))]
    return matches

def dose_key(s):
    m=DOSE.search(norm(s))
    if not m:return None
    v=str(float(m[1])).removesuffix(".0")
    return v if v in DOSES else None

def unit(s):
    """Only locally explicit 1/4/12 pen quantity; any conflict -> ambiguous."""
    s=norm(s)
    if not s:return None
    count=[]
    if PACK_ONE.search(s):count.append(1)
    if PACK_FOUR.search(s):count.append(4)
    if PACK_TWELVE.search(s):count.append(12)
    # A marketing comparison of several pack plans is not one price's unit.
    if OTHER_PLAN.search(s):return None
    return count[0] if len(set(count))==1 and count else None

def context_of(table):
    labels=[]
    for h in table.find_all_previous(HEADINGS,limit=3):
        t=norm(h.get_text(" ",strip=True))
        if OTHER.search(t) and not BRAND.search(t):
            break
        labels.append(t[:120])
        if BRAND.search(t):break
    return labels

def tax_mode(*texts):
    t=" ".join(norm(x) for x in texts)
    if EX_TAX.search(t):return "excluded"
    if IN_TAX.search(t):return "included"
    return "unknown"

def record(d,raw,pens,source,quote,unit_label,tax):
    if d not in DOSES or not 1<=pens<=12 or 12%pens:
        return None
    if raw<1000 or raw>1000000:return None
    total=raw*(12//pens)
    if total<12000 or total>1200000:return None
    return {"dose":d,"raw_yen":raw,"pens":pens,"equivalent_12":total,
            "unit_label":norm(unit_label)[:120],"source_kind":source,
            "quote":norm(quote)[:350],"tax":tax}

def table_evidence(table):
    cells=[[norm(c.get_text(" ",strip=True)) for c in row.find_all(["th","td"],recursive=False)]
           for row in table.select("tr")]
    cells=[row for row in cells if row]
    if len(cells)<2:return []
    headings=context_of(table)
    first_header=" ".join(cells[0])
    table_branded=any(BRAND.search(x) and not OTHER.search(x) for x in headings+cells[0])
    row_brands=any(BRAND.search(r[0]) for r in cells[1:] if r)
    if not (table_branded or row_brands):return []
    if OTHER.search(first_header) and not BRAND.search(first_header):return []
    if OTHER.search(headings[0]) and not BRAND.search(headings[0]):return []
    # Never pick a price in a table with multiple subscription length columns,
    # even if the last column is cheap. A human can compare plans.
    headers=cells[0]
    # Allow an explicitly labeled 1-month + 3-month table. If a longer
    # 6/12-month subscription is present, do not infer its installment prices.
    # That case remains for independently documented manual review.
    if any(OTHER_PLAN.search(h) for h in headers[1:]):
        return []
    # multi-column rows: one dose, an explicit quantity (4本), and one price
    entries=[]
    drug_state=table_branded
    for row in cells[1:]:
        label=row[0]
        if OTHER.search(label):
            drug_state=False
            continue
        if BRAND.search(label):drug_state=True
        if not drug_state:continue
        d=dose_key(label)
        if not d and BRAND.search(label) and len(row)>1:
            # Brand row containing all doses and explicit units in a single cell.
            for field in row[1:]:
                fields=norm(field)
                dose_matches=list(DOSE.finditer(fields))
                for j,m in enumerate(dose_matches):
                    d2=dose_key(m[0])
                    tail=fields[m.end():(dose_matches[j+1].start() if j+1<len(dose_matches) else len(fields))]
                    prices=num(tail)
                    pens=unit(tail)
                    if not pens or len(prices)!=1 or OTHER.search(tail) or PROMO.search(tail):continue
                    ev=record(d2,prices[0],pens,"branded_inline_cell",m[0]+" "+tail,tail,tax_mode(tail,first_header))
                    if ev:entries.append(ev)
            continue
        if not d or len(row)<2 or OTHER.search(" ".join(row)) or PROMO.search(" ".join(row)):
            continue
        # Identify monetary cells and *do not* silently select the last
        # numeric column. Each retained candidate must have its own unit.
        money=[(i,num(t)) for i,t in enumerate(row[1:],1)]
        money=[(i,values[0]) for i,values in money if len(values)==1]
        if not money:continue
        # Multiple money columns require a clearly labeled 12-pen/3-month
        # TOTAL (or a 3-month monthly installment) price column.
        if len(money)>1:
            choices=[]
            for i,amount in money:
                header=headers[i] if i<len(headers) else ""
                if (unit(header)==12 and not OTHER_PLAN.search(header)):
                    monthly=bool(MONTHLY_RATE.search(header))
                    pens=4 if monthly else 12
                    ev=record(d,amount,pens,"multi_plan_3month",f"{label} | {header}: {row[i]}",header,tax_mode(first_header,header,row[i]))
                    if ev:choices.append(ev)
            if len(choices)!=1:continue
            entries.extend(choices)
            continue
        i,amount=money[0]
        price_col_header=headers[i] if i<len(headers) else ""
        quantity=[unit(c) for j,c in enumerate(row[1:]) if j!=i and unit(c)]
        # If unit is explicitly specified in a quantity column, it overrides
        # a vague nearby explanatory paragraph about a different time span.
        if len(set(quantity))>1:continue
        pens=(quantity[0] if quantity else None)
        pens=pens or unit(row[i]) or unit(price_col_header) or unit(label)
        if not pens:
            # A SINGLE unambiguous table-wide unit in the header (e.g. 4週分).
            header_unit=unit(first_header)
            if len(money)==1 and header_unit:pens=header_unit
        # A single direct preceding sibling can explain this exact price table.
        if not pens:
            previous=table.find_previous_sibling()
            if previous and previous.name in ("p","small","div"):
                line=norm(previous.get_text(" ",strip=True))
                if len(line)<=100 and not OTHER.search(line):
                    pens=unit(line)
        if not pens:continue
        ev=record(d,amount,pens,"dose_table",f"{label} | "+" | ".join(row[1:]),price_col_header or label,tax_mode(first_header,headings[0] if headings else "",row[i]))
        if ev:entries.append(ev)
    return entries

def inline_evidence(soup):
    entries=[]
    active=False
    for node in soup.select("h1,h2,h3,h4,h5,h6,p,li,dd"):
        if node.find_parent("table") or node.find_parent(["nav","footer"]):continue
        line=norm(node.get_text(" ",strip=True))
        if not line or len(line)>450:continue
        if node.name in HEADINGS:
            active=bool(BRAND.search(line) and not OTHER.search(line))
            continue
        if OTHER.search(line):
            active=False
            continue
        has_brand=BRAND.search(line)
        if not (active or has_brand):continue
        for m in DOSE.finditer(line):
            d=dose_key(m[0])
            next_m=DOSE.search(line,m.end())
            tail=line[m.end():next_m.start() if next_m else len(line)]
            prices=num(tail)
            # Explicit unit must be attached to the same dose's price.
            pens=unit(tail)
            if len(prices)!=1 or not pens or PROMO.search(tail):continue
            ev=record(d,prices[0],pens,"dose_inline",m[0]+" "+tail,tail,tax_mode(line))
            if ev:entries.append(ev)
    return entries

def extract_with_evidence(source):
    soup=BeautifulSoup(source,"html.parser")
    for t in soup(["script","style","noscript","svg","nav","footer"]):t.decompose()
    if not BRAND.search(soup.get_text(" ",strip=True)):return {},{}
    found=[]
    for table in soup.select("table"):found.extend(table_evidence(table))
    found.extend(inline_evidence(soup))
    results={};evidence={}
    for d in DOSES:
        choices=[e for e in found if e["dose"]==d]
        if not choices:continue
        # Conflicting conditions, tax treatment, or prices = no automatic claim.
        values={e["equivalent_12"] for e in choices}
        if len(values)!=1:continue
        if any(e["tax"]=="excluded" for e in choices):continue
        ev=next((x for x in choices if x["tax"]=="included"),choices[0])
        results[d]=ev["equivalent_12"]
        evidence[d]=ev
    return results,evidence

def extract_official(source):
    amounts,detail=extract_with_evidence(source)
    return amounts,("엄격 검증: 공식 제품명·용량·판매 단위·가격 연결 확인 / "
                    +", ".join(f"{d}mg {ev['raw_yen']}엔/{ev['pens']}펜→12펜" for d,ev in detail.items()))

def self_test():
    def run(html):return extract_with_evidence(html)[0]
    table="""<h3>マンジャロ</h3><table><tr><th>用量</th><th>本数（1ヶ月分）</th><th>税込価格</th></tr>
    <tr><td>2.5mg</td><td>4本</td><td>19,800円</td></tr><tr><td>10mg</td><td>4本</td><td>66,000円</td></tr></table>"""
    assert run(table)=={"2.5":59400,"10":198000},run(table)
    assert run("<h2>マンジャロ価格</h2><p>5mg（4週分）32,000円</p>")=={"5":96000}
    assert run("<h2>マンジャロ価格</h2><p>10mg 1本 9,000円</p>")=={"10":108000}
    assert run("<h2>ゼップバウンド</h2><p>マンジャロと同成分</p><p>10mg 4本 33,000円</p>")=={}
    assert run("""<h3>マンジャロ価格</h3><table><tr><th>用量</th><th>1ヶ月分</th><th>6ヶ月分</th><th>12ヶ月分</th></tr>
      <tr><td>5mg</td><td>44,000円</td><td>18,900円</td><td>12,000円</td></tr></table>""")=={}
    assert run("""<h3>マンジャロ</h3><table><tr><th>用量</th><th>1ヶ月分</th><th>3ヶ月分</th></tr>
       <tr><td>5mg</td><td>44,000円</td><td>108,000円</td></tr></table>""")=={"5":108000}
    assert run("""<h3>マンジャロ</h3><table><tr><th>用量</th><th>1ヶ月分</th><th>3ヶ月プラン/月</th></tr>
       <tr><td>5mg</td><td>44,000円</td><td>36,000円</td></tr></table>""")=={"5":108000}
    assert run("""<h3>マンジャロ</h3><table><tr><th>用量</th><th>1ヶ月分</th><th>3ヶ月分</th><th>6ヶ月分</th></tr>
       <tr><td>5mg</td><td>44,000円</td><td>108,000円</td><td>170,000円</td></tr></table>""")=={}
    assert run("""<h3>マンジャロ</h3><table><tr><th>用量</th><th>1本単価</th></tr>
       <tr><td>5mg</td><td>12,000円</td></tr></table>""")=={"5":144000}
    assert run("""<h2>マンジャロ 5mg</h2><p>2.5mg（4週分）19,000円</p>
       <h3>ゼップバウンド</h3><p>5mg（4週分）30,000円</p>""")=={"2.5":57000}
    assert run("""<h2>マンジャロ</h2><table><tr><th>用量</th><th>価格</th></tr>
       <tr><td>10mg</td><td>66,000円</td></tr></table>""")=={}
    print("Strict V2 price evidence tests passed (units, drugs, subscription terms, ambiguity)")
if __name__=="__main__":self_test()
