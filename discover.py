#!/usr/bin/env python3
"""Discover publicly advertised Japanese Mounjaro clinics, emphasizing Korean travelers.

Sources: three independent discovery channels: indexed clinic official
websites, indexed public SNS, and clinic directories (name-only leads).
Public Yahoo Japan X, Japanese/Korean web and news RSS are supplemental.
Neither private posts nor platform APIs are accessed. Candidates remain
unverified until their clinic identity and official price source are confirmed.
Prescription eligibility is never inferred from advertisements.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import html
import json
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "catalog.json"
OUTPUT = ROOT / "discoveries.json"
DOSES = ["2.5", "5", "7.5", "10", "12.5", "15"]
UA = "Mozilla/5.0 (compatible; JapanMounjaroPublicPriceResearch/2.0)"
TERM = re.compile(r"マンジャロ|Mounjaro|마운자로|チルゼパチド", re.I)
SOCIAL_HOSTS = ("x.com", "twitter.com", "instagram.com", "facebook.com", "threads.net")
EVENT_TERMS = ("キャンペーン", "期間限定", "割引", "特価", "クーポン", "イベント", "행사", "할인", "한정", "今だけ")
SUFFIX = r"(?:オンラインクリニック|美容クリニック|クリニック|CLINIC|Clinic|医院|美容皮膚科|皮膚科)"
NAME_RE = re.compile(r"(?<![0-9A-Za-zぁ-んァ-ヴ一-龥])([A-Za-zＡ-Ｚａ-ｚ0-9ぁ-んァ-ヴ一-龥&・ー\-]{2,27}" + SUFFIX + r")")
BAD_PARTS = (
    "のある", "今回", "教えて", "ホームページ", "オンライン診療可能", "こちらの",
    "そういう", "おすすめ", "安全な", "新しい", "いろんな", "たくさん", "東京の",
    "日本の", "地元の", "近くの", "激安な", "値下げ", "価格", "効果",
    "マウンジャロ", "マンジャロ", "ランキング", "ご紹介", "比較", "購入",
    "炎上", "口コミ", "料金", "医師が", "患者が", "臨床", "知りたい",
    "まとめ", "解説", "使い方", "質問", "数字", "最高", "サイト",
)
GENERIC = {"クリニック", "オンラインクリニック", "美容クリニック", "医療ダイエットクリニック",
           "マンジャロクリニック", "安全なクリニック", "日本のクリニック"}
# English/Korean transliterations of already verified providers.
ALIASES = {
    "mオンラインクリニック": "monline", "ckkオンラインクリニック": "ckk",
    "sdhクリニック": "sdh", "こよみクリニック": "koyomi",
    "新宿駅前クリニック": "shinjuku-eki", "東京シルククリニック": "silk-visit",
    "ubクリニック": "ub-online", "ubclinic": "ub-online",
    # This name refers to distinct Fukuoka and Tokyo facilities; no name-only alias.
    "ラピスクリニック": "lapis-tenjin",
    "スルリムクリニック": "sururim-tenjin",
    "カクヤスクリニック": "kakuyasu",
}
# A directory may display translated names. Identify known clinics by the
# directory's stable path, never by an unverified headline number.
KNOWN_DIRECTORY_SLUGS = {
 "ubclinic-online":"ub-online","koyomi-clinic":"koyomi","aurelia-online":"aurelia",
 "mirai-medical":"mirai-medical-tokyo","miraimedical":"mirai-medical",
 "slim-clinic":"sururim-tenjin","slim-clinic-fukuoka":"sururim-tenjin",
 "modena-clinic":"modena","okachi-clinic":"okachi","ehealthclinic":"ehealth",
 "mil-clinic":"mil","bw-med":"japan-web-clinic",
 "baba-totalcareclinic":"baba","japannetclinic":"japan-net-clinic",
 "fontana-clinic":"fontana","lapis-clinic":"lapis-tenjin",
 "mbcf":"mbcf","pgc-clinic":"", "nana":"", "ys-med":"",
}
# Focus on inbound/Korean promotional material, not all Japanese primary-care facilities.
CORE = [
    "韓国人 観光客 マンジャロ クリニック 予約",
    "訪日韓国人 マンジャロ 処方 価格 LINE",
    "マウンジャロ 韓国人 旅行者 ホテル 配送 クリニック",
    "マンジャロ 12本 3ヶ月 外国人 処方",
    "マンジャロ 韓国語 予約 クリニック",
    "마운자로 일본 병원 예약 할인 3개월",
    "일본 마운자로 한국인 처방 클리닉 호텔 배송",
    "일본 마운자로 병원 SNS 이벤트 10mg",
    "マンジャロ 10mg 12本 クリニック キャンペーン",
    "マンジャロ 観光客 価格改定 クリニック",
]
SOCIAL = [
    "site:x.com マンジャロ 韓国人 クリニック",
    "site:x.com マンジャロ 期間限定 クリニック 価格",
    "site:x.com マンジャロ 外国人 観光客 処方",
    "site:instagram.com マンジャロ クリニック 韓国人",
    "site:instagram.com マンジャロ 3ヶ月 予約",
    "site:instagram.com 마운자로 일본 클리닉 예약",
    "site:facebook.com マンジャロ 韓国人 クリニック",
    "site:facebook.com 마운자로 일본 병원 할인",
    "site:threads.net マンジャロ クリニック 価格",
]
REGIONS = [
    "福岡", "大阪", "東京", "対馬", "名古屋", "鳥取", "広島", "札幌",
    "京都", "神戸", "那覇", "長崎", "横浜", "金沢", "米子", "高松",
]
# Explicit official-website discovery: source results are *leads* until a
# clinic's own page is fetched and its identity/price are independently checked.
# Unrelated comparison sites/news articles cannot become "official" leads.
NON_OFFICIAL_DOMAINS = (
    "sushijaro.app", "mounjarojp.com", "kireireport.com",
    "beauty.hotpepper.jp", "yahoo.co.jp", "yahoo.com", "google.com",
    "google.co.jp", "news.google.com", "instagram.com", "facebook.com",
    "threads.net", "x.com", "twitter.com", "note.com", "reddit.com",
    "youtube.com", "tiktok.com", "ameblo.jp", "hatena.ne.jp",
    "prtimes.jp", "atpress.ne.jp", "value-press.com", "livedoor.jp",
    "note.jp", "sushijaro.jp", "jihi-shohou.com", "seikeitimes.com",
    "manjaro-info.jp", "mounjaro-map.jobby-time.com",
    "kusurigo.vercel.app", "best.e-health.care", "iryodiet-navi.com",
    "bing.com", "bing.cn", "msn.com", "duckduckgo.com", "search.yahoo.co.jp",
)
OFFICIAL_CORE = [
    "マンジャロ 10mg 料金 4本 クリニック",
    "マンジャロ 12本 3ヶ月 料金 クリニック",
    "マンジャロ 自由診療 料金表 クリニック",
    "マンジャロ 2.5mg 5mg 7.5mg 10mg 料金表",
    "マンジャロ 外国人 処方 料金 クリニック",
    "マンジャロ 韓国語 予約 料金 医院",
    "マンジャロ 10mg 価格 月額 医療ダイエット",
]
OFFICIAL_REGION_PATTERNS = [
    "マンジャロ 料金表 {region} クリニック",
    "マンジャロ 10mg 価格 {region} 医院",
]

def hostname(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""

def potential_official_site(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        host = hostname(url)
        if parsed.scheme != "https" or not host or "." not in host:
            return False
        return not any(host == h or host.endswith("." + h) for h in NON_OFFICIAL_DOMAINS)
    except ValueError:
        return False

def official_queries(full=False):
    # All core price searches daily; rotate prefectures on regular scans.
    day = dt.date.today().toordinal()
    regions = REGIONS if full else [REGIONS[(day * 3 + i) % len(REGIONS)] for i in range(3)]
    return OFFICIAL_CORE + [
        OFFICIAL_REGION_PATTERNS[i % len(OFFICIAL_REGION_PATTERNS)].format(region=region)
        for i, region in enumerate(regions)
    ]

def official_entry(url, title, desc, query):
    if not potential_official_site(url):
        return None
    result = entry(url, title, desc, "official_site_search", query)
    if not result:
        return None
    # Search snippets can still be misleading. This URL is a HINT only;
    # enrich_official.py fetches the actual page before any price is approved.
    result["channel"] = "official"
    result["official_url_hint"] = url
    return result

NEWS = [
    "マンジャロ 韓国人 クリニック 値段 予約",
    "マンジャロ 訪日外国人 クリニック 新規 価格",
    "マンジャロ クリニック 韓国語 ホテル 配送",
]
YAHOO = [
    "マンジャロ 韓国人 クリニック",
    "マンジャロ 外国人 予約",
    "マンジャロ 期間限定 クリニック",
    "マンジャロ 10mg 3ヶ月 価格",
    "マンジャロ 福岡 LINE 予約",
]

def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")

def norm_name(s):
    return re.sub(r"[^a-z0-9ぁ-んァ-ヴ一-龥]", "", unicodedata.normalize("NFKC", s).lower())

def candidate_names(text):
    """Extract brand-like institution names, never arbitrary text ending in クリニック."""
    txt = html.unescape(BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True))
    out = []
    # Boundaries prevent the preceding promotional sentence becoming part of the name.
    for section in re.split(r"[「」『』【】《》｜|:：/／（）()\n\t ]+", txt):
        for m in NAME_RE.finditer(section):
            name = unicodedata.normalize("NFKC", m.group(1)).strip("-・")
            norm = norm_name(name)
            if len(name) < 5 or len(name) > 32 or norm in {norm_name(x) for x in GENERIC}:
                continue
            if any(x in name for x in BAD_PARTS):
                continue
            if name.startswith(("の", "が", "で", "と", "は", "を", "に", "も", "お", "その")):
                continue
            # Reject snippets where a long common sentence precedes the word clinic.
            if re.search(r"[。！？、，]", name) or re.search(r"\d{3,}", name):
                continue
            if name not in out:
                out.append(name)
    return out[:4]

def event_hints(txt):
    if not any(t in txt for t in EVENT_TERMS):
        return None
    dates = re.findall(r"(?:20\d{2}[-/])?\d{1,2}[-/]\d{1,2}", txt)
    return {"kind": "event_post", "dates_mentioned": dates[:5],
            "snippet": txt[:300], "price_verified": False,
            "note": "행사 언급만 감지. 적용 기간과 12펜 가격은 공식 검증 전"}

def entry(url, title, desc, origin, query):
    txt = BeautifulSoup(html.unescape((title or "") + " " + (desc or "")), "html.parser").get_text(" ", strip=True)
    if not TERM.search(txt):
        return None
    # Prefer the headline, then the short description, but never concatenate them
    # for entity extraction; concatenation is a major cause of false clinic names.
    found = list(dict.fromkeys(candidate_names(title) + candidate_names(desc)))
    if not found:
        return None
    domain = (urllib.parse.urlsplit(url).hostname or "").lower()
    social = any(domain == h or domain.endswith("." + h) for h in SOCIAL_HOSTS)
    return {"url": url, "title": (title or "")[:160], "snippet": txt[:450],
            "clinic_names": found, "channel": "sns" if social else "web",
            "source": origin, "query": query, "event": event_hints(txt)}

def official_page_lead(url, page_html, query):
    """Derive a clinic name from a fetched page's own branding metadata.

    Search headlines are often "Mounjaro | Prices" without the clinic name.
    This remains a NAME-only candidate, not verified medicine pricing.
    """
    if not potential_official_site(url):
        return None
    soup=BeautifulSoup(page_html, "html.parser")
    for node in soup(["script","style","footer","nav"]):
        node.decompose()
    text=soup.get_text(" ",strip=True)
    if not TERM.search(text):
        return None
    site=soup.select_one('meta[property="og:site_name"]')
    site_name=site.get("content","") if site else ""
    title=soup.title.get_text(" ",strip=True) if soup.title else ""
    top_header=soup.select_one("header")
    header=top_header.get_text(" ",strip=True)[:350] if top_header else ""
    brand=list(dict.fromkeys(candidate_names(site_name)+candidate_names(title)+candidate_names(header)))
    if not brand:
        return None
    return {"url": url, "title": title[:160], "snippet": "Official-site page branding: "+site_name[:120],
            "clinic_names": brand[:2], "channel": "official",
            "source": "official_site_search", "official_url_hint": url,
            "query": query, "event": None}

def probe_official_site(session, url, query):
    if not potential_official_site(url):
        return None
    try:
        response=session.get(url, timeout=(4, 9), headers={"Accept": "text/html"})
        response.raise_for_status()
        if "html" not in response.headers.get("Content-Type","").lower() and not response.text.lstrip().startswith("<"):
            return None
        return official_page_lead(response.url, response.text[:950000], query)
    except (requests.RequestException, ValueError, UnicodeError):
        return None

def fetch_rss(session, query, provider):
    if provider == "bing":
        url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "format": "rss", "count": 25})
    else:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": query, "hl": "ja", "gl": "JP", "ceid": "JP:ja"})
    response = session.get(url, timeout=(6, 16), headers={"Accept": "application/rss+xml,text/xml"})
    response.raise_for_status()
    if "<rss" not in response.text[:600] and "<feed" not in response.text[:600]:
        raise ValueError("Search did not return public RSS")
    root = ET.fromstring(response.content)
    for node in root.findall(".//item")[:25]:
        title = node.findtext("title", "")
        url = node.findtext("link", "")
        desc = node.findtext("description", "")
        if url:
            yield title, url, desc

def fetch_bing_html(session, query):
    """Alternative public index view, used when Bing RSS has zero items."""
    url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "count": 20})
    res = session.get(url, timeout=(6, 16))
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")
    for item in soup.select("li.b_algo")[:20]:
        a = item.select_one("h2 a[href]")
        if not a:
            continue
        desc = item.select_one(".b_caption p")
        yield a.get_text(" ", strip=True), a.get("href", ""), desc.get_text(" ", strip=True) if desc else ""

def fetch_yahoo(session, query):
    url = "https://search.yahoo.co.jp/realtime/search?" + urllib.parse.urlencode({"p": query, "ei": "UTF-8"})
    resp = session.get(url, timeout=(6, 16))
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    seen = set()
    for link in soup.select('a[href]'):
        href = urllib.parse.urljoin(url, link.get("href", ""))
        if "x.com/" not in href and "twitter.com/" not in href:
            continue
        label = link.get_text(" ", strip=True)
        block = link.find_parent("article") or link.find_parent("li") or link.parent
        text = block.get_text(" ", strip=True)[:650] if block else label
        if not TERM.search(text) or href in seen:
            continue
        seen.add(href)
        yield label or "X public post", href, text
        if len(seen) >= 60:
            return

def planned_queries(full=False):
    # Daily: the highest-yield Korean/traveler searches plus rotating SNS and cities.
    day = dt.date.today().toordinal()
    social = SOCIAL if full else [SOCIAL[(day * 4 + i) % len(SOCIAL)] for i in range(4)]
    region = REGIONS if full else [REGIONS[(day * 4 + i) % len(REGIONS)] for i in range(4)]
    return CORE + social + [f"マンジャロ 韓国人 旅行者 クリニック {x} 予約" for x in region]

def directory_entries(source, base_url, limit=35):
    """Find names/links only in publicly accessible directories.

    These are discovery leads, not price confirmations or endorsements.
    Do not copy directory prices, eligibility labels, reviews or ratings.
    """
    soup = BeautifulSoup(source, "html.parser")
    found, seen = [], set()
    for a in soup.select("a[href]"):
        url = urllib.parse.urljoin(base_url, a.get("href", ""))
        path = urllib.parse.urlsplit(url).path
        if not re.search(r"/(?:ja/|en/)?clinic/[^/#?]+", path, re.I):
            continue
        if url in seen:
            continue
        label = a.get_text(" ", strip=True)
        if len(label) < 4:
            parent = a.parent
            label = parent.get_text(" ", strip=True)[:110] if parent else ""
        label = re.split(r"[（(（]|(?:¥|￥|円|엔|詳細|총액|가격|入れる)", label)[0].strip()
        label = re.sub(r"\s+", " ", label).strip("- |")
        label = re.sub(r"^\d{1,3}\s+", "", label)
        label = re.sub(r"\s*(?:チャットボット|予約ページ|公式サイト)$", "", label).strip()
        if not 4 <= len(label) <= 48:
            continue
        # Directory location is precise: /clinic/slug. A readable clinic
        # brand is still required; never infer a name from the slug alone.
        if not re.search(r"(?:クリニック|CLINIC|Clinic|クリ$|美容外科|医院|병원|클리닉)", label):
            continue
        if any(part in label for part in BAD_PARTS):
            continue
        if re.search(r"(?:ランキング|比較|料金|値段|代わり|おすすめ)", label):
            continue
        seen.add(url)
        found.append({"url": url, "title": label[:120], "snippet": "Mounjaro clinic listing (name lead only)",
                      "clinic_names": [label], "channel": "web", "source": "public_directory_lead",
                      "query": "foreign-traveler clinic directory", "event": None})
        if len(found) >= limit:
            break
    return found

def comparison_link_entries(source, base_url, limit=30):
    """Extract institution NAME leads from a public comparison page.

    Only linked clinic labels are retained. Never import the comparison site's
    price, claim of official status, tourist policy or promotional discount.
    """
    soup = BeautifulSoup(source, "html.parser")
    for tag in soup(["script", "style", "footer", "nav"]):
        tag.decompose()
    out, seen_names = [], set()
    for a in soup.select("a[href]"):
        names = candidate_names(a.get_text(" ", strip=True))
        if not names:
            continue
        target = urllib.parse.urljoin(base_url, a.get("href", ""))
        if not target.startswith("https://"):
            continue
        for name in names[:2]:
            norm = norm_name(name)
            if norm in seen_names:
                continue
            seen_names.add(norm)
            out.append({"url": target, "title": name,
                        "snippet": "Comparison directory clinic name lead only; no price copied.",
                        "clinic_names": [name], "channel": "web",
                        "source": "public_directory_lead", "query": base_url, "event": None})
            if len(out) >= limit:
                return out
    return out

def fetch_directory_leads(session):
    # Independently published comparisons are a SECONDARY way to find names;
    # their prices and purported eligibility are not imported.
    roots = (
        ("https://sushijaro.app/ja/", "sushijaro"),
        ("https://sushijaro.app/ja/answers/clinics-by-city", "sushijaro"),
        ("https://sushijaro.app/ja/city/online", "sushijaro"),
        ("https://sushijaro.app/ja/?f=korean", "sushijaro"),
        ("https://sushijaro.app/ja/city/fukuoka", "sushijaro"),
        ("https://manjaro-info.jp/clinic-search/", "comparison"),
        ("https://mounjaro-map.jobby-time.com/ja/", "comparison"),
        ("https://mounjaro-map.jobby-time.com/ja/online/", "comparison"),
        ("https://mounjaro-map.jobby-time.com/ja/city/tokyo/", "comparison"),
        ("https://kusurigo.vercel.app/mounjaro-ja.html", "comparison"),
    )
    results, states, seen = [], [], set()
    for root, kind in roots:
        try:
            response = session.get(root, timeout=(6, 15))
            response.raise_for_status()
            items = (directory_entries(response.text, root, limit=80) if kind == "sushijaro"
                     else comparison_link_entries(response.text, root))
            states.append({"source": "public_directory_lead", "query": root,
                           "ok": True, "items": len(items)})
            for item in items:
                key = (norm_name(item["clinic_names"][0]), hostname(item["url"]))
                if key not in seen:
                    results.append(item)
                    seen.add(key)
        except Exception as exc:
            states.append({"source": "public_directory_lead", "query": root, "ok": False,
                           "reason": str(exc)[:110]})
    return results[:200], states

def discover(session, limit=210, full=False):
    official_hits, public_hits, status, seen = [], [], [], set()
    probe_budget=12
    probed_urls=set()

    def ingest(provider, query, entries, fallback=False, official=False):
        items = list(entries)
        qualified = 0
        nonlocal probe_budget
        for title, url, description in items:
            if not url or url in seen:
                continue
            item = official_entry(url, title, description, query) if official else entry(
                url, title, description, provider, query)
            if official and not item and probe_budget>0 and url not in probed_urls and potential_official_site(url):
                probe_budget-=1
                probed_urls.add(url)
                item=probe_official_site(session,url,query)
            if item:
                (official_hits if official else public_hits).append(item)
                seen.add(url)
                qualified += 1
        # Keep compact public index diagnostics in Action logs to distinguish
        # a true zero-result query from changes in search-result markup.
        if provider == "official_site_search" and items and not qualified and query == OFFICIAL_CORE[0]:
            for sample in items[:3]:
                print("OFFICIAL SEARCH SAMPLE:", repr(sample[0][:135]),
                      repr(sample[1][:145]), repr(sample[2][:110]))
        status.append({"source": provider, "query": query, "ok": True,
                       "items": len(items), "qualified": qualified, "fallback": fallback})

    for query in planned_queries(full):
        try:
            entries = list(fetch_rss(session, query, "bing"))
            if entries:
                ingest("bing_rss", query, entries)
            else:
                ingest("bing_html", query, fetch_bing_html(session, query), fallback=True)
        except Exception as exc:
            status.append({"source": "bing", "query": query, "ok": False, "reason": str(exc)[:100]})
    # Keep official clinic sites independent of SNS results. RSS search can
    # change/fail; use public HTML search as a fallback only when RSS is empty.
    for query in official_queries(full):
        try:
            entries = list(fetch_rss(session, query, "bing"))
            if entries:
                ingest("official_site_search", query, entries, official=True)
            else:
                ingest("official_site_search", query, fetch_bing_html(session, query),
                       fallback=True, official=True)
        except Exception as exc:
            status.append({"source": "official_site_search", "query": query, "ok": False,
                           "reason": str(exc)[:100]})
    for query in YAHOO:
        try:
            ingest("yahoo_x", query, fetch_yahoo(session, query))
        except Exception as exc:
            status.append({"source": "yahoo_x", "query": query, "ok": False, "reason": str(exc)[:100]})
    for query in NEWS:
        try:
            ingest("google_news", query, fetch_rss(session, query, "google_news"))
        except Exception as exc:
            status.append({"source": "google_news", "query": query, "ok": False, "reason": str(exc)[:100]})
    # Directory listings provide NAMES ONLY, never authoritative prices or
    # foreigner eligibility. Maintain an independent budget for this channel.
    directory_hits, directory_status = fetch_directory_leads(session)
    status.extend(directory_status)
    directory_hits = [x for x in directory_hits if x["url"] not in seen]
    # Three independent channel quotas stop an ad-heavy query from consuming
    # all available result slots and hiding official clinics or directories.
    return (official_hits[:min(70, limit)] +
            public_hits[:min(60, max(0, limit - 70))] +
            directory_hits[:min(80, max(0, limit - 130))]), status

def merge_into_catalog(cat, rawhits, archive):
    ids = {x["id"] for x in cat["clinics"]}
    seen = {norm_name(x["name"]) for x in cat["clinics"]}
    # Domain identity prevents re-adding known clinics on every daily
    # official search, while a same-name clinic on a DIFFERENT official
    # domain remains a separately reviewable candidate.
    known_official_hosts = {
        hostname(x.get("url", "")) for x in cat["clinics"]
        if x.get("status") != "candidate" and x.get("url", "").startswith("https://")
    }
    known_official_hosts.update(
        x.get("official_domain", "").lower().removeprefix("www.")
        for x in cat["clinics"] if x.get("status") != "candidate" and x.get("official_domain")
    )
    seen_official_pairs = {
        (hostname(x.get("official_url_hint", "")), norm_name(x["name"]))
        for x in cat["clinics"] if x.get("official_url_hint")
    }
    seen_directory_slugs = set()
    for existing in cat["clinics"]:
        existing_path = urllib.parse.urlsplit(existing.get("url", "")).path
        existing_match = re.search(r"/(?:ja/|en/)?clinic/([^/]+)", existing_path)
        if existing_match:
            seen_directory_slugs.add(existing_match.group(1))
    known_aliases = {norm_name(name): ident for name, ident in ALIASES.items()}
    fresh = []
    stamp = now()
    for hit in rawhits:
        official = hit.get("channel") == "official" and hit.get("source") == "official_site_search"
        official_domain = hostname(hit.get("official_url_hint") or hit.get("url", "")) if official else ""
        if official and (not official_domain or official_domain in known_official_hosts):
            # This provider's clinic website has already been verified.
            continue
        path=urllib.parse.urlsplit(hit.get("url","")).path
        match=re.search(r"/(?:ja/|en/)?clinic/([^/]+)",path)
        directory_slug=match.group(1) if match else None
        known_id=KNOWN_DIRECTORY_SLUGS.get(directory_slug) if directory_slug else None
        # Directory listing for a clinic already in the official data is NOT new.
        skip_known_dir = bool(known_id and known_id in ids)
        if directory_slug and (skip_known_dir or directory_slug in seen_directory_slugs):
            # Same provider already catalogued (or on another directory page).
            continue
        for name in hit["clinic_names"]:
            if skip_known_dir:
                continue
            norm = norm_name(name)
            # An exact name is not a unique identifier. Two independent
            # providers can share the same branded name (Tokyo and Fukuoka
            # Mirai are one confirmed case). For directory hits, a different
            # stable clinic slug may represent a different provider and is
            # retained as a *candidate* until official URL/address validation.
            # SNS hits without a stable entity URL remain conservative.
            name_collision = norm in seen
            if official:
                if (official_domain, norm) in seen_official_pairs:
                    continue
            elif not directory_slug and (name_collision or known_aliases.get(norm) in ids):
                continue
            if len(norm) < 5 or any(p in name for p in BAD_PARTS):
                continue
            identity_key = ("official:" + official_domain + ":" + norm) if official else (directory_slug or norm)
            ident = "found-" + hashlib.sha1(identity_key.encode()).hexdigest()[:12]
            if ident in ids:
                continue
            row = {"id": ident, "name": name, "region": "미확인", "city": "미확인",
                   "mode": "미확인", "foreign": "unknown", "online": "unknown", "ship": "unknown",
                   "prices": {k: None for k in DOSES}, "basis": "공식 출처·SNS·비교 사이트에서 발견된 후보 (검증 전)",
                   "url": hit["url"],
                   "official_url_hint": hit["official_url_hint"] if official else "",
                   "notes": "공개 공식 사이트 검색에서 발견된 페이지. 실제 의료기관·기관명·가격 확인 전." if official else "공개 검색에서 발견된 이름으로 실제 의료기관 여부부터 확인해야 합니다.",
                   "fees": "미확인", "status": "candidate", "address": "",
                   "channel": "공식 홈페이지 검색 후보" if official else ("자동 공개 SNS 탐색" if hit["channel"] == "sns" else "비교 사이트·웹 검색 후보"),
                   "updated": stamp[:10], "discovery": "auto", "price_verified": False,
                   "candidate_quality": "same_name_needs_identity_verification" if name_collision else "name_unverified",
                   "identity_conflict": bool(name_collision), "directory_slug": directory_slug or "",
                   "events": [],
                   "booking_method": "예약 방법 미확인", "booking_url": "",
                   "booking_type": "none", "booking_notes": "공식 예약 경로 확인 전",
                   "booking_checked": "", "first_seen": stamp[:10]}
            cat["clinics"].append(row)
            ids.add(ident)
            seen.add(norm)
            if directory_slug:
                seen_directory_slugs.add(directory_slug)
            if official:
                seen_official_pairs.add((official_domain, norm))
            fresh.append({"id": ident, "name": name, "source_url": hit["url"],
                          "source": hit["source"], "channel": hit["channel"]})
        key = hashlib.sha1(hit["url"].encode()).hexdigest()[:20]
        older = archive.get(key, {})
        archive[key] = {**hit, "first_seen": older.get("first_seen", stamp),
                        "last_seen": stamp}
    return fresh, archive

def self_test():
    positive = entry("https://x.com/example/status/123",
        "公式 ミライメディカルクリニック マンジャロ 韓国人予約",
        "12本のマンジャロ予約 キャンペーン", "test", "韓国人 マンジャロ")
    assert positive and positive["clinic_names"] == ["ミライメディカルクリニック"], positive
    for t in ["東京のあるクリニック マンジャロ", "今回教えてもらったクリニック マンジャロ",
              "安全なクリニック マンジャロ", "マンジャロ料金比較オンラインクリニック"]:
        assert not entry("https://x.com/example/status/4", t, "", "test", "test"), t
    html_fixture = '<a href="/ja/clinic/ubclinic-online">1 UBクリニック チャットボット</a><a href="/ja/clinic/x">安全なクリニック</a>'
    fixture = directory_entries(html_fixture, "https://sushijaro.app/")
    assert len(fixture) == 1 and fixture[0]["clinic_names"] == ["UBクリニック"], fixture
    compare_fixture='<a href="https://sample-clinic.jp/mounjaro/">新星クリニック</a><a href="/info">マンジャロ料金比較クリニック</a>'
    compare_items=comparison_link_entries(compare_fixture,"https://manjaro-info.jp/clinic-search/")
    assert len(compare_items)==1 and compare_items[0]["clinic_names"]==["新星クリニック"],compare_items
    cat = {"clinics": []}
    found, _ = merge_into_catalog(cat, [positive], {})
    assert len(found) == 1 and cat["clinics"][0]["status"] == "candidate"
    assert all(v is None for v in cat["clinics"][0]["prices"].values())
    directory_hit = {"url": "https://sushijaro.app/ja/clinic/new-clinic",
        "clinic_names": ["テスト医療クリニック"], "channel":"web",
        "source":"public_directory_lead"}
    cat2={"clinics":[]}
    leads, _ = merge_into_catalog(cat2, [directory_hit, directory_hit], {})
    assert len(leads)==1 and len(cat2["clinics"])==1, leads
    # Regression test: an established Fukuoka Mirai must NOT hide Tokyo Mirai,
    # even if the Japanese display names are exactly identical.
    tokyo={"url":"https://sushijaro.app/ja/clinic/mirai-medical",
           "clinic_names":["ミライメディカルクリニック"],
           "channel":"web","source":"public_directory_lead"}
    fukuoka={"id":"mirai-medical","name":"ミライメディカルクリニック",
             "url":"https://miraimedical.com/","status":"active"}
    cat3={"clinics":[fukuoka]}
    tokyo_candidates,_=merge_into_catalog(cat3,[tokyo],{})
    assert len(tokyo_candidates)==1 and tokyo_candidates[0]["name"]=="ミライメディカルクリニック",tokyo_candidates
    assert cat3["clinics"][-1]["identity_conflict"] is True
    # An official URL is a distinct DISCOVERY path and not proof of price or
    # identity. Known official domains should not be cloned as new clinics.
    official_hit=official_entry("https://new-clinic.jp/mounjaro/price",
        "マウンジャロの価格 - 新星クリニック", "マンジャロ 10mg 4本 30,000円", "official test")
    assert official_hit and official_hit["channel"]=="official",official_hit
    assert not official_entry("https://sushijaro.app/ja/clinic/new",
        "新星クリニック マンジャロ", "マンジャロ価格", "official test")
    assert not official_entry("https://www.bing.com/ck/a?redirect=1",
        "新星クリニック マンジャロ", "マンジャロ価格", "official test")
    site_fixture='<html><head><title>マンジャロ価格</title><meta property="og:site_name" content="天神スタークリニック"></head><body>マンジャロ 10mg 価格表</body></html>'
    from_site=official_page_lead("https://tenjin-star.jp/mounjaro/",site_fixture,"test")
    assert from_site and from_site["clinic_names"]==["天神スタークリニック"],from_site
    cat_official={"clinics":[{"id":"known","name":"既存クリニック",
        "status":"active","url":"https://known-clinic.jp/mounjaro/"}]}
    duplicate=official_entry("https://known-clinic.jp/new-price",
        "既存クリニック マンジャロ", "マンジャロ 価格", "test")
    assert merge_into_catalog(cat_official,[duplicate],{})[0]==[]
    same_brand=official_entry("https://separate-clinic.jp/fee",
        "既存クリニック マンジャロ", "マンジャロ料金", "test")
    newofficial,_=merge_into_catalog(cat_official,[same_brand,same_brand],{})
    assert len(newofficial)==1 and cat_official["clinics"][-1]["identity_conflict"],newofficial
    assert cat_official["clinics"][-1]["official_url_hint"]=="https://separate-clinic.jp/fee"
    # When both are verified separately, the known Tokyo directory record
    # must be suppressed as already registered.
    cat3["clinics"].append({"id":"mirai-medical-tokyo","name":"미라이 메디컬(도쿄)","status":"active"})
    dup,_=merge_into_catalog(cat3,[tokyo],{})
    assert not dup,dup
    print("discovery self-test passed: real name, false-positive rejection, safe candidates")

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--full-scan", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    prior = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    archive = {x["key"]: x["hit"] for x in prior.get("archive", []) if "key" in x}
    # Reclassify legacy titles before keeping them; older parser captured sentences.
    archive = {k: v for k, v in archive.items() if entry(v.get("url", ""), v.get("title", ""),
               v.get("snippet", ""), v.get("source", "legacy"), v.get("query", ""))}
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "ja,ko;q=0.9,en;q=0.7"})
    hits, sources = discover(session, full=args.full_scan)
    fresh, archive = merge_into_catalog(cat, hits, archive)
    if args.dry_run:
        print(json.dumps({"hits": len(hits), "new_candidates": fresh,
                          "sources": sources}, ensure_ascii=False, indent=2))
        return
    cat["updated"] = now()[:10]
    cat["auto_candidate_quality_version"] = 2
    CATALOG.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    channels = {"official": sum(h["channel"]=="official" for h in hits),
                "sns": sum(h["channel"]=="sns" for h in hits),
                "web": sum(h["channel"]=="web" for h in hits)}
    outcome = {"ran_at": now(), "source_status": sources, "hits_this_run": len(hits),
               "channel_counts": channels,
               "new_candidates": fresh,
               "archive": [{"key": k, "hit": v} for k, v in list(archive.items())[-600:]],
               "note": "Three leads: official site index, public SNS/web, comparison directories (name-only). 12-week price and visitor eligibility require official evidence."}
    OUTPUT.write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("New clinic name leads:", " | ".join(x["name"] for x in fresh[:50]))
    print("Discover v3 official+SNS+directories:", len(hits), "named hits;",
          len([x for x in hits if x.get("channel")=="official"]), "official page leads;",
          len(fresh), "new candidates;",
          sum(s["ok"] for s in sources), "of", len(sources), "queries succeeded")

if __name__ == "__main__":
    run()
