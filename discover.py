#!/usr/bin/env python3
"""Discover publicly advertised Japanese Mounjaro clinics, emphasizing Korean travelers.

Sources: search-indexed X/Instagram/Facebook, public Yahoo Japan real-time X,
Japanese/Korean public web and news RSS. Neither private posts nor platform
APIs are accessed. Discovered names remain unverified candidates until an
official price source is confirmed. This script does not infer prescription
eligibility from advertisements.
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
    "ミライメディカルクリニック": "mirai-medical",
    "ラピスクリニック": "lapis-tenjin",
    "スルリムクリニック": "sururim-tenjin",
    "カクヤスクリニック": "kakuyasu",
}
# A directory may display translated names. Identify known clinics by the
# directory's stable path, never by an unverified headline number.
KNOWN_DIRECTORY_SLUGS = {
 "ubclinic-online":"ub-online","koyomi-clinic":"koyomi","aurelia-online":"aurelia",
 "mirai-medical":"mirai-medical","miraimedical":"mirai-medical",
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

def fetch_directory_leads(session):
    roots = (
        "https://sushijaro.app/ja/city/online",
        "https://sushijaro.app/ja/?f=korean",
        "https://sushijaro.app/ja/city/fukuoka",
    )
    results, states, seen = [], [], set()
    for root in roots:
        try:
            response = session.get(root, timeout=(6, 15))
            response.raise_for_status()
            items = directory_entries(response.text, root)
            states.append({"source": "public_directory_lead", "query": root, "ok": True, "items": len(items)})
            for item in items:
                if item["url"] not in seen:
                    results.append(item)
                    seen.add(item["url"])
        except Exception as exc:
            states.append({"source": "public_directory_lead", "query": root, "ok": False,
                           "reason": str(exc)[:110]})
    return results[:60], states

def discover(session, limit=90, full=False):
    hits, status, seen = [], [], set()
    def ingest(provider, query, entries, fallback=False):
        items = list(entries)
        status.append({"source": provider, "query": query, "ok": True, "items": len(items), "fallback": fallback})
        for title, url, description in items:
            if not url or url in seen:
                continue
            item = entry(url, title, description, provider, query)
            if item:
                hits.append(item)
                seen.add(url)
    for query in planned_queries(full):
        try:
            entries = list(fetch_rss(session, query, "bing"))
            if entries:
                ingest("bing_rss", query, entries)
            else:
                ingest("bing_html", query, fetch_bing_html(session, query), True)
        except Exception as exc:
            status.append({"source": "bing", "query": query, "ok": False, "reason": str(exc)[:100]})
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
    # Public price directories are supplemental NAME-ONLY leads, not a
    # replacement for SNS discovery and never a source for price rankings.
    directory_hits, directory_status = fetch_directory_leads(session)
    status.extend(directory_status)
    for item in directory_hits:
        if item["url"] not in seen:
            hits.append(item)
            seen.add(item["url"])
    return hits[:limit], status

def merge_into_catalog(cat, rawhits, archive):
    ids = {x["id"] for x in cat["clinics"]}
    seen = {norm_name(x["name"]) for x in cat["clinics"]}
    known_aliases = {norm_name(name): ident for name, ident in ALIASES.items()}
    fresh = []
    stamp = now()
    for hit in rawhits:
        path=urllib.parse.urlsplit(hit.get("url","")).path
        match=re.search(r"/(?:ja/|en/)?clinic/([^/]+)",path)
        directory_slug=match.group(1) if match else None
        known_id=KNOWN_DIRECTORY_SLUGS.get(directory_slug) if directory_slug else None
        # Directory listing for a clinic already in the official data is NOT new.
        skip_known_dir=bool(known_id and known_id in ids)
        for name in hit["clinic_names"]:
            if skip_known_dir:
                continue
            norm = norm_name(name)
            if norm in seen or known_aliases.get(norm) in ids:
                continue
            if len(norm) < 5 or any(p in name for p in BAD_PARTS):
                continue
            ident = "found-" + hashlib.sha1(norm.encode()).hexdigest()[:12]
            if ident in ids:
                continue
            row = {"id": ident, "name": name, "region": "미확인", "city": "미확인",
                   "mode": "미확인", "foreign": "unknown", "online": "unknown", "ship": "unknown",
                   "prices": {k: None for k in DOSES}, "basis": "SNS·공개 웹의 명칭 후보 (공식 검증 전)",
                   "url": hit["url"],
                   "notes": "공개 검색에서 발견된 이름으로 실제 의료기관 여부부터 확인해야 합니다.",
                   "fees": "미확인", "status": "candidate", "address": "",
                   "channel": "자동 공개 SNS 탐색" if hit["channel"] == "sns" else "자동 웹 탐색",
                   "updated": stamp[:10], "discovery": "auto", "price_verified": False,
                   "candidate_quality": "name_unverified", "events": [],
                   "booking_method": "예약 방법 미확인", "booking_url": "",
                   "booking_type": "none", "booking_notes": "공식 예약 경로 확인 전",
                   "booking_checked": "", "first_seen": stamp[:10]}
            cat["clinics"].append(row)
            ids.add(ident)
            seen.add(norm)
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
    cat = {"clinics": []}
    found, _ = merge_into_catalog(cat, [positive], {})
    assert len(found) == 1 and cat["clinics"][0]["status"] == "candidate"
    assert all(v is None for v in cat["clinics"][0]["prices"].values())
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
    outcome = {"ran_at": now(), "source_status": sources, "hits_this_run": len(hits),
               "new_candidates": fresh,
               "archive": [{"key": k, "hit": v} for k, v in list(archive.items())[-600:]],
               "note": "Public indexed social/web sources only; 3-month prices require official evidence."}
    OUTPUT.write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("New clinic name leads:", " | ".join(x["name"] for x in fresh[:50]))
    print("Discover v2:", len(hits), "named hits;", len(fresh), "new candidates;",
          sum(s["ok"] for s in sources), "of", len(sources), "queries succeeded")

if __name__ == "__main__":
    run()
