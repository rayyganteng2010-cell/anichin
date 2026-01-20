from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin, urlparse
import re
import time

app = FastAPI()

# --- CONFIGURATION ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://anichin.moe/",
}

BASE_URL = "https://anichin.moe"

# --- tiny cache (biar nggak jadi beban server & bikin kamu dikira bot rusuh) ---
_CACHE = {}  # url -> (ts, html)
CACHE_TTL = 60  # seconds

def normalize_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return urljoin(BASE_URL, u)
    if u.startswith("http://") or u.startswith("https://"):
        return u
    # slug / relative tanpa leading slash
    return urljoin(BASE_URL + "/", u)

def same_domain(u: str) -> bool:
    try:
        return urlparse(u).netloc.endswith(urlparse(BASE_URL).netloc)
    except:
        return False

def get_soup(url: str, params=None) -> BeautifulSoup:
    url = normalize_url(url)
    if not url:
        return None

    # cache
    now = time.time()
    cached = _CACHE.get((url, str(params)))
    if cached:
        ts, html = cached
        if now - ts < CACHE_TTL:
            return BeautifulSoup(html, "html.parser")

    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=20)
        r.raise_for_status()
        html = r.text
        _CACHE[(url, str(params))] = (now, html)
        return BeautifulSoup(html, "html.parser")
    except Exception as e:
        print(f"[ERR] GET {url} -> {e}")
        return None

def text_clean(el: Tag) -> str:
    if not el:
        return ""
    return el.get_text(" ", strip=True)

def pick_first(soup: BeautifulSoup, selectors: list[str]) -> Tag:
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            return el
    return None

def extract_title(soup: BeautifulSoup) -> str:
    el = pick_first(soup, ["h1.entry-title", "h1.ts-title", "h1", "header h1"])
    return text_clean(el) or "Unknown Title"

def extract_thumbnail(soup: BeautifulSoup) -> str:
    # series biasanya punya cover image dekat judul
    img = pick_first(soup, ["div.thumb img", ".thumb img", ".ts-post-image img", "article img"])
    if img and img.get("src"):
        return normalize_url(img.get("src"))
    return ""

def extract_genres(soup: BeautifulSoup) -> list[str]:
    genres = []
    for a in soup.select("a[rel='tag'], .genxed a, .mgen a"):
        t = text_clean(a)
        if t and t.lower() not in ("batch",):
            genres.append(t)
    # unique preserve order
    seen = set()
    out = []
    for g in genres:
        if g not in seen:
            seen.add(g)
            out.append(g)
    return out

def extract_alt_titles(soup: BeautifulSoup) -> list[str]:
    # di series page biasanya ada baris judul alternatif setelah paragraf pendek
    # contoh: "Link Click Season 2, Shi Guang..., 时光代理人 第2季" 3
    alts = []
    # cari kandidat: paragraf/teks dekat judul (heuristic)
    # ambil beberapa teks di sekitar judul
    h1 = pick_first(soup, ["h1.entry-title", "h1.ts-title", "h1"])
    if h1:
        parent = h1.parent
        blob = text_clean(parent)
        # coba split pakai koma
        parts = [p.strip() for p in blob.split(",") if p.strip()]
        # buang yang sama dengan title
        title = text_clean(h1)
        for p in parts:
            if p and p != title and len(p) <= 80:
                alts.append(p)
    # fallback: meta og:title kadang panjang
    return list(dict.fromkeys(alts))[:6]

def extract_synopsis(soup: BeautifulSoup) -> str:
    # series page punya "Synopsis ..." dan paragraf setelahnya 4
    # episode page kadang nggak relevan, tapi kita tetap ambil bila ada
    syn = ""
    # coba cari heading synopsis
    for h in soup.select("h2, h3, strong"):
        t = text_clean(h).lower()
        if "sinopsis" in t or "synopsis" in t:
            # ambil text sesudah heading (next siblings)
            buf = []
            cur = h
            for _ in range(10):
                cur = cur.find_next_sibling()
                if not cur:
                    break
                if cur.name in ("h2", "h3"):
                    break
                tt = cur.get_text("\n", strip=True)
                if tt:
                    buf.append(tt)
            syn = "\n".join(buf).strip()
            if syn:
                return syn

    # fallback ke entry-content
    box = pick_first(soup, ["div.entry-content[itemprop='description']", "div.entry-content", "article .entry-content"])
    if box:
        syn = box.get_text("\n", strip=True)
    return syn.strip() if syn else "-"

def extract_meta_info_line(soup: BeautifulSoup) -> dict:
    """
    Series page punya baris panjang:
    Status: ... Network: ... Studio: ... Released: ... 5
    Kita parse pake regex 'Key: Value'
    """
    meta = {}
    # cari node yang mengandung "Status:" dan "Released:"
    cand = None
    for el in soup.select("div, p, span"):
        tx = text_clean(el)
        if "Status:" in tx and ("Released:" in tx or "Country:" in tx or "Type:" in tx):
            cand = tx
            break
    if not cand:
        return meta

    # regex Key: Value (Value sampai ketemu Key berikutnya)
    keys = ["Status", "Network", "Studio", "Released", "Duration", "Season", "Country", "Type", "Episodes", "Fansub", "Posted by", "Updated on"]
    # bikin pattern yang fleksibel
    for i, k in enumerate(keys):
        # cari "k:" lalu ambil sampai sebelum " <key_next>:"
        nxt = "|".join([re.escape(x) for x in keys if x != k])
        m = re.search(rf"{re.escape(k)}:\s*(.+?)(?=\s+(?:{nxt})\s*:|$)", cand)
        if m:
            meta[k.lower().replace(" ", "_")] = m.group(1).strip()
    return meta

def extract_episode_list(soup: BeautifulSoup) -> list[dict]:
    episodes = []
    selectors = [
        "ul.eplister li a",
        "div.eplister li a",
        "div#episode_list li a",
        "div.bixbox li a",
        "div.bixbox.lpl li a",
    ]
    links = []
    for sel in selectors:
        found = soup.select(sel)
        if found and len(found) >= 3:
            links = found
            break
    if not links:
        # fallback: "All Episodes" widget list (episode page) 6
        links = soup.select("div.bixbox ul li a")

    for a in links:
        href = a.get("href")
        if not href:
            continue
        url = normalize_url(href)
        t = text_clean(a)
        # bersihin text biar ga kepanjangan
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            episodes.append({"title": t, "url": url})

    # unique by url
    seen = set()
    out = []
    for ep in episodes:
        if ep["url"] not in seen:
            seen.add(ep["url"])
            out.append(ep)
    return out

def extract_streams(soup: BeautifulSoup) -> list[dict]:
    streams = []

    # A) ul/li data-src (beberapa theme pakai ini)
    for li in soup.select("ul#playeroptionsul li, ul#playeroptionsul > li"):
        name = text_clean(li.select_one("span.title")) or text_clean(li) or "Server"
        link = li.get("data-src") or li.get("data-url") or li.get("data-nume") or li.get("data-embed")
        if link:
            streams.append({"server": name.strip(), "url": normalize_url(link)})

    # B) select/option (episode page tampak seperti "Select Video Server ..." 7
    sel = pick_first(soup, ["select", "div.select-server select", "select#server", "select#select-server"])
    if sel:
        for opt in sel.select("option"):
            name = text_clean(opt) or opt.get("label") or "Server"
            val = opt.get("value") or opt.get("data-src") or opt.get("data-url")
            if val and val.strip() and "select" not in name.lower():
                streams.append({"server": name.strip(), "url": normalize_url(val.strip())})

    # C) iframe fallback
    iframe = pick_first(soup, ["div.video-content iframe", "#embed_holder iframe", "iframe"])
    if iframe and iframe.get("src"):
        streams.append({"server": "Default", "url": normalize_url(iframe.get("src"))})

    # unique by (server,url)
    seen = set()
    out = []
    for s in streams:
        key = (s["server"], s["url"])
        if s["url"] and key not in seen:
            seen.add(key)
            out.append(s)
    return out

def _is_download_heading(t: str) -> bool:
    t = (t or "").lower()
    return "download" in t

def extract_downloads(soup: BeautifulSoup) -> list[dict]:
    """
    Pola real di Anichin:
    ### Download <Title>
    ### <Group Name> (mis: Episode 01-20 / Episode 60 ...)
    360p <a>...</a> <a>...</a>
    480p <a>...</a> ...
    8
    """
    downloads = []

    content = pick_first(soup, ["div.entry-content", "article .entry-content", "div#content", "main"])
    if not content:
        return downloads

    # cari heading "Download"
    start = None
    for h in content.select("h2, h3, h4"):
        if _is_download_heading(text_clean(h)):
            start = h
            break
    if not start:
        return downloads

    # jalanin node setelah heading download sampai sebelum heading besar berikutnya yang bukan bagian download/watch
    cur = start
    current_group = None

    def push_group():
        nonlocal current_group
        if current_group and current_group.get("links"):
            downloads.append(current_group)
        current_group = None

    # iterate sibling-ish (BeautifulSoup nggak punya iterator rapi, jadi pakai next_elements terbatas)
    # stop conditions: ketemu heading "Watch", "History", "Comment", dsb
    stop_words = ("watch", "history", "comment", "recommended", "related")
    steps = 0
    for el in start.next_elements:
        steps += 1
        if steps > 800:
            break
        if not isinstance(el, Tag):
            continue

        if el.name in ("h2", "h3", "h4"):
            ht = text_clean(el)
            lht = ht.lower()
            # stop jika masuk section lain
            if any(w in lht for w in stop_words) and not _is_download_heading(lht):
                push_group()
                break

            # group heading setelah "Download ..." biasanya adalah nama pack/episode group
            if not _is_download_heading(ht):
                push_group()
                current_group = {"resolution_group": ht.strip(), "links": []}
            continue

        # baris resolusi biasanya ada di <p> atau <div> yang berisi "360p" dst dan punya <a>
        if el.name in ("p", "div", "li"):
            line = text_clean(el)
            if not line:
                continue

            # deteksi resolusi
            m = re.match(r"^(240p|360p|480p|720p|1080p|1440p|4k)\b", line.lower())
            if m:
                res = m.group(1)
                if not current_group:
                    current_group = {"resolution_group": "Download", "links": []}

                # ambil semua <a> dalam container ini
                links = []
                for a in el.select("a"):
                    href = a.get("href")
                    if not href:
                        continue
                    links.append({
                        "source": text_clean(a) or "Link",
                        "link": normalize_url(href),
                    })
                if links:
                    current_group["links"].append({"resolution": res, "items": links})

    push_group()

    # rapihin: buang group tanpa links
    cleaned = []
    for g in downloads:
        g_links = [x for x in g.get("links", []) if x.get("items")]
        if g_links:
            cleaned.append({"group": g.get("resolution_group", "Download"), "packs": g_links})
    return cleaned

def extract_recommended_series(soup: BeautifulSoup) -> list[dict]:
    recs = []
    # episode page ada "Recommended Series" list 9
    # coba cari block setelah heading itu
    h = None
    for hh in soup.select("h2, h3, h4"):
        if "recommended" in text_clean(hh).lower():
            h = hh
            break
    if not h:
        return recs

    # ambil beberapa link setelahnya
    cnt = 0
    for a in h.find_all_next("a"):
        href = a.get("href")
        t = text_clean(a)
        if href and t and same_domain(normalize_url(href)):
            # filter link navigasi umum
            if t.lower() in ("home", "schedule", "bookmark"):
                continue
            recs.append({"title": t, "url": normalize_url(href)})
            cnt += 1
        if cnt >= 10:
            break

    # unique
    seen = set()
    out = []
    for r in recs:
        if r["url"] not in seen:
            seen.add(r["url"])
            out.append(r)
    return out

# --- ENDPOINTS ---

@app.get("/")
def home():
    return {"message": "Anichin Scraper - Robust Detail (Series + Episode)"}

# 1) SEARCH
@app.get("/api/search")
def search_anime(s: str = Query(..., alias="s")):
    soup = get_soup(BASE_URL, params={"s": s})
    if not soup:
        raise HTTPException(status_code=502, detail="Failed to fetch search page")

    results = []
    articles = soup.select("div.listupd article.bs")
    for item in articles:
        title_el = item.select_one("div.tt") or item.select_one("h2") or item.select_one("a")
        link_el = item.select_one("a")
        thumb_el = item.select_one("img")

        title = text_clean(title_el)
        link = normalize_url(link_el.get("href")) if link_el and link_el.get("href") else ""
        thumb = normalize_url(thumb_el.get("src")) if thumb_el and thumb_el.get("src") else ""

        if title and link:
            results.append({"title": title, "thumbnail": thumb, "url": link})

    return {"status": "success", "data": results}

# 2) SCHEDULE
@app.get("/api/schedule")
def get_schedule():
    soup = get_soup(f"{BASE_URL}/schedule/")
    if not soup:
        raise HTTPException(status_code=502, detail="Failed to fetch schedule page")

    data = []
    for box in soup.select("div.bixbox"):
        day_el = box.select_one("div.releases h3") or box.select_one("h3")
        if not day_el:
            continue
        day_name = text_clean(day_el)
        anime_list = []

        for anime in box.select("div.listupd div.bs, div.listupd article.bs"):
            title_el = anime.select_one("div.tt") or anime.select_one("h2") or anime.select_one("a")
            link_el = anime.select_one("a")
            thumb_el = anime.select_one("img")
            ep_el = anime.select_one("div.epx")

            title = text_clean(title_el)
            url = normalize_url(link_el.get("href")) if link_el and link_el.get("href") else ""
            thumb = normalize_url(thumb_el.get("src")) if thumb_el and thumb_el.get("src") else ""
            ep = text_clean(ep_el) if ep_el else "?"

            if title and url:
                anime_list.append({"title": title, "thumbnail": thumb, "episode": ep, "url": url})

        if anime_list:
            data.append({"day": day_name, "list": anime_list})

    return {"status": "success", "data": data}

# 3) RECOMMENDED (ambil dari /anime/ default list)
@app.get("/api/recommended")
def get_recommended():
    soup = get_soup(f"{BASE_URL}/anime/")
    if not soup:
        raise HTTPException(status_code=502, detail="Failed to fetch recommended page")

    results = []
    for item in soup.select("div.listupd article.bs"):
        title_el = item.select_one("div.tt") or item.select_one("h2") or item.select_one("a")
        link_el = item.select_one("a")
        thumb_el = item.select_one("img")

        title = text_clean(title_el)
        url = normalize_url(link_el.get("href")) if link_el and link_el.get("href") else ""
        thumb = normalize_url(thumb_el.get("src")) if thumb_el and thumb_el.get("src") else ""

        if title and url:
            results.append({"title": title, "thumbnail": thumb, "url": url})

    return {"status": "success", "data": results}

# 4) DETAIL (Series page atau Episode page)
@app.get("/api/detail")
def get_detail(url: str = Query(..., description="Full URL atau slug/relative path")):
    url = normalize_url(url)
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")

    soup = get_soup(url)
    if not soup:
        raise HTTPException(status_code=404, detail="Page not found / fetch failed")

    title = extract_title(soup)
    thumb = extract_thumbnail(soup)
    synopsis = extract_synopsis(soup)
    genres = extract_genres(soup)
    alt_titles = extract_alt_titles(soup)
    meta = extract_meta_info_line(soup)

    streams = extract_streams(soup)
    downloads = extract_downloads(soup)
    episodes = extract_episode_list(soup)

    # deteksi tipe halaman (kasar tapi cukup)
    # episode page biasanya ada "Select Video Server" 10
    page_text = soup.get_text(" ", strip=True).lower()
    is_episode = "select video server" in page_text or "/episode" in url.lower()

    recommended = extract_recommended_series(soup) if is_episode else []

    return {
        "status": "success",
        "data": {
            "url": url,
            "type": "episode" if is_episode else "series",
            "title": title,
            "alternative_titles": alt_titles,
            "thumbnail": thumb,
            "genres": genres,
            "meta": meta,  # status/network/studio/released/duration/season/country/type/episodes/fansub/...
            "synopsis": synopsis,
            "streams": streams,       # mostly meaningful on episode page
            "downloads": downloads,   # works for series & episode page
            "episodes": episodes,     # list episode urls (mostly meaningful on series page)
            "recommended": recommended
        }
    }
