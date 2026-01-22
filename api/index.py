from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import re
import base64
from urllib.parse import urljoin

app = FastAPI(title="Anichin Moe Scraper API")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIG ---
BASE_URL = "https://anichin.moe"
CREATOR = "Sanka Vollerei"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": BASE_URL + "/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "id,en-US;q=0.9,en;q=0.8",
}


# --------------------------
# HELPERS
# --------------------------
def get_soup(url: str, params=None) -> BeautifulSoup | None:
    try:
        req = requests.get(url, headers=HEADERS, params=params, timeout=25)
        req.raise_for_status()
        return BeautifulSoup(req.text, "html.parser")
    except Exception as e:
        print(f"[get_soup] Error {url}: {e}")
        return None


def abs_url(u: str) -> str:
    if not u:
        return ""
    return urljoin(BASE_URL, u)


def extract_slug(url: str) -> str:
    try:
        url = (url or "").split("?")[0].strip("/")
        return url.split("/")[-1]
    except:
        return ""


def normalize_label(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def safe_text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def pick_first(*vals):
    for v in vals:
        if v:
            return v
    return ""


def split_label_value(text: str):
    # "Status: Ongoing" -> ("status", "Ongoing")
    if ":" not in text:
        return None, None
    k, v = text.split(":", 1)
    k = normalize_label(k).lower()
    v = normalize_label(v)
    return k, v


def decode_url(raw_url: str) -> str:
    """
    Decode Base64 yang biasanya berisi iframe HTML, ambil src="...".
    Kalau sudah http, return langsung.
    """
    if not raw_url:
        return ""
    if raw_url.startswith("http"):
        return raw_url

    try:
        decoded = base64.b64decode(raw_url).decode("utf-8", errors="ignore")
        m = re.search(r'src="([^"]+)"', decoded)
        if m:
            return m.group(1)
        return decoded.strip()
    except:
        return raw_url


def build_list_params(
    status: str | None,
    type_: str | None,
    sub: str | None,
    order: str | None,
    genres: list[str] | None,
):
    """
    Bikin params sesuai pola Anichin:
    /anime/?status=&type=&sub=&order=update
    genre[] bisa lebih dari 1.
    """
    params = {}
    if status is not None:
        params["status"] = status
    if type_ is not None:
        params["type"] = type_
    if sub is not None:
        params["sub"] = sub
    if order is not None:
        params["order"] = order
    if genres:
        params["genre[]"] = genres
    return params


# --------------------------
# PARSERS
# --------------------------
def parse_card(element, is_schedule: bool = False):
    """
    Card parser untuk list/search/genre/schedule.
    Output standar: title, poster, status, type, rating, episode/current_episode
    Schedule: upload_at (HH:MM) + episode (angka)
    """
    try:
        a = element.select_one("a")
        if not a or not a.get("href"):
            return None

        url = abs_url(a["href"])
        slug = extract_slug(url)

        # title
        title_el = (
            element.select_one("div.tt")
            or element.select_one(".entry-title")
            or element.select_one("h2")
            or element.select_one("h3")
        )
        title = safe_text(title_el) or safe_text(a)

        # poster
        img = element.select_one("img")
        poster = ""
        if img:
            poster = pick_first(
                img.get("data-src", ""),
                img.get("src", ""),
                (img.get("srcset", "").split(" ")[0] if img.get("srcset") else ""),
            )
        poster = abs_url(poster) if poster else ""

        # episode text on card
        ep_el = element.select_one("div.epx") or element.select_one(".ep") or element.select_one(".episode")
        ep_txt = safe_text(ep_el)

        # status/type/rating
        status_el = element.select_one("div.status") or element.select_one(".stat") or element.select_one(".status")
        status = safe_text(status_el) or "Ongoing"

        type_el = element.select_one("div.typez") or element.select_one(".type") or element.select_one(".typez")
        type_show = safe_text(type_el) or "Donghua"

        rating_el = (
            element.select_one(".numscore")
            or element.select_one(".rating")
            or element.select_one(".score")
            or element.select_one(".imdb")
        )
        rating = safe_text(rating_el)

        data = {
            "title": title,
            "slug": slug,
            "poster": poster,
            "status": status,
            "type": type_show,
            "rating": rating,
            "sub": "Sub",
            "href": f"/donghua/detail/{slug}",
            "anichinUrl": url,
        }

        if is_schedule:
            # time text biasanya "at 14:25"
            time_el = element.select_one("div.time") or element.select_one(".time")
            time_txt = safe_text(time_el)
            m_time = re.search(r"(\d{1,2}:\d{2})", time_txt)
            upload_at = m_time.group(1) if m_time else ""

            m_ep = re.search(r"(\d+)", ep_txt)
            episode_num = m_ep.group(1) if m_ep else (ep_txt or "??")

            data["upload_at"] = upload_at
            data["episode"] = episode_num
        else:
            data["current_episode"] = ep_txt or "??"

        return data
    except Exception as e:
        print("[parse_card] error:", e)
        return None


def parse_list_page(soup: BeautifulSoup | None):
    if not soup:
        return []

    cards = soup.select("div.listupd article.bs")
    if not cards:
        cards = soup.select("div.listupd div.bs")

    out = []
    for it in cards:
        c = parse_card(it)
        if c:
            out.append(c)
    return out


def parse_series_detail(soup: BeautifulSoup, url: str):
    # Title & alt title
    title = safe_text(soup.select_one("h1.entry-title")) or safe_text(soup.select_one("h1")) or ""
    alt_title = ""
    alt_el = (
        soup.select_one(".seriestitl .alter, .seriestitl .alttitle, .seriestitl h2")
        or soup.select_one("div.seriestitl h2")
    )
    alt_title = safe_text(alt_el)

    # Poster
    thumb = soup.select_one("div.thumb img") or soup.select_one(".thumb img") or soup.select_one("img")
    poster = abs_url(thumb.get("src", "")) if thumb else ""

    # Short description (paragraf panjang pertama)
    short_desc = ""
    entry = soup.select_one("div.entry-content") or soup.select_one("article")
    if entry:
        for p in entry.select("p"):
            t = normalize_label(p.get_text(" ", strip=True))
            if len(t) > 80:
                short_desc = t
                break

    # Info fields
    info = {
        "status": "-",
        "network": "-",
        "studio": "-",
        "released": "-",
        "duration": "-",
        "country": "-",
        "type": "-",
        "episodes": "-",
        "fansub": "-",
        "posted by": "-",
        "released on": "-",
        "updated on": "-",
    }

    for sp in soup.select("div.spe span"):
        k, v = split_label_value(sp.get_text(" ", strip=True))
        if not k:
            continue
        if "status" in k:
            info["status"] = v
        elif "network" in k:
            info["network"] = v
        elif "studio" in k:
            info["studio"] = v
        elif k == "released":
            info["released"] = v
        elif "duration" in k:
            info["duration"] = v
        elif "country" in k:
            info["country"] = v
        elif k == "type":
            info["type"] = v
        elif "episodes" in k:
            info["episodes"] = v
        elif "fansub" in k:
            info["fansub"] = v
        elif "posted" in k:
            info["posted by"] = v
        elif "released on" in k:
            info["released on"] = v
        elif "updated on" in k:
            info["updated on"] = v

    # Genres (link)
    genres = []
    seen = set()
    for a in soup.select("div.genxed a, .genxed a, a[href*='/genre/'], a[href*='/genres/']"):
        name = safe_text(a)
        href = abs_url(a.get("href", ""))
        if not name:
            continue
        slug = extract_slug(href) if href else re.sub(r"\s+", "-", name.lower())
        key = slug or name.lower()
        if key in seen:
            continue
        seen.add(key)
        genres.append({"name": name, "slug": slug, "anichinUrl": href})

    # Synopsis
    synopsis_title = "Synopsis"
    synopsis_text = ""

    syn_head = None
    for h in soup.select("h2, h3, h4"):
        if "synopsis" in safe_text(h).lower():
            syn_head = h
            synopsis_title = safe_text(h) or "Synopsis"
            break

    if syn_head:
        parts = []
        for sib in syn_head.find_all_next():
            if sib.name in ("h2", "h3", "h4"):
                break
            if sib.name in ("p", "div"):
                txt = normalize_label(sib.get_text(" ", strip=True))
                if txt:
                    parts.append(txt)
        synopsis_text = "\n".join(parts).strip()
    else:
        syn = soup.select_one("div.entry-content[itemprop='description']") or soup.select_one("div.entry-content")
        if syn:
            synopsis_text = syn.get_text("\n", strip=True)

    # Episodes list on series page
    episodes_list = []
    for a in soup.select("ul#episode_list li a, .eplister li a, .episodelist li a"):
        href = a.get("href", "")
        if not href:
            continue
        full = abs_url(href)

        ep_num = a.select_one(".epl-num")
        ep_title = a.select_one(".epl-title")
        ep_text = normalize_label(f"{safe_text(ep_num)} {safe_text(ep_title)}").strip()
        if not ep_text:
            ep_text = safe_text(a)

        episodes_list.append(
            {
                "episode": ep_text,
                "slug": extract_slug(full),
                "href": f"/donghua/episode/{extract_slug(full)}",
                "anichinUrl": full,
            }
        )

    return {
        "status": "success",
        "creator": CREATOR,
        "title": title,
        "alt_title": alt_title,
        "short_description": short_desc,
        "poster": poster,
        "slug": extract_slug(url),
        "info": info,
        "genres": genres,
        "synopsis_title": synopsis_title,
        "synopsis": synopsis_text,
        "episodes_list": episodes_list,
        "anichinUrl": url,
    }


def parse_episode_detail(soup: BeautifulSoup, url: str):
    episode_title = safe_text(soup.select_one("h1.entry-title")) or "Episode"

    # --- STREAM SERVERS ---
    servers = []

    # 1) UL/LI servers
    for li in soup.select("ul#playeroptionsul li"):
        name = safe_text(li.select_one(".title")) or safe_text(li) or "Server"
        raw = li.get("data-src") or li.get("data-url") or ""
        clean = decode_url(raw)
        if clean and "http" in clean:
            servers.append({"name": name, "url": clean})

    # 2) select.mirror servers (dropdown)
    if not servers:
        sel = soup.select_one("select.mirror")
        if sel:
            for opt in sel.select("option"):
                name = safe_text(opt) or "Server"
                raw = opt.get("value", "")
                clean = decode_url(raw)
                if clean and "http" in clean:
                    servers.append({"name": name, "url": clean})

    # 3) fallback iframe
    if not servers:
        iframe = soup.select_one(".video-content iframe") or soup.select_one("iframe")
        if iframe and iframe.get("src"):
            servers.append({"name": "Default", "url": iframe["src"]})

    main_url = servers[0] if servers else {"name": "Default", "url": ""}

    # --- DOWNLOADS ---
    downloads = {}

    # cari area download yang mengandung resolusi
    dl_sections = []
    for box in soup.select("div, section, article"):
        t = normalize_label(box.get_text(" ", strip=True)).lower()
        if "download" in t and any(x in t for x in ["240p", "360p", "480p", "720p", "1080p"]):
            dl_sections.append(box)

    # fallback container pattern lama
    dl_sections += soup.select("div.mctnx div.soraddl, div.soraurl, div.dl-box")

    def add_links(res_key: str, container):
        links_map = {}
        for a in container.select("a"):
            provider = safe_text(a)
            href = a.get("href", "")
            if provider and href and href.startswith("http"):
                links_map[provider] = href
        if links_map:
            downloads[res_key] = links_map

    # scan resolusi di setiap section
    for sec in dl_sections:
        # coba pecah per row
        rows = sec.select("tr, li, .row, .dlrow, .dldiv, div")
        if not rows:
            rows = [sec]

        for r in rows:
            txt = normalize_label(r.get_text(" ", strip=True)).lower()
            m = re.search(r"(240|360|480|720|1080)p", txt)
            if not m:
                continue
            res = m.group(1)
            add_links(f"download_url_{res}p", r)

    # NAV
    nav = {}
    nav_prev = soup.select_one("div.nvs .nav-previous a") or soup.select_one("a[rel='prev']")
    nav_next = soup.select_one("div.nvs .nav-next a") or soup.select_one("a[rel='next']")

    if nav_prev and nav_prev.get("href"):
        u = abs_url(nav_prev["href"])
        nav["previous_episode"] = {"slug": extract_slug(u), "anichinUrl": u}
    if nav_next and nav_next.get("href"):
        u = abs_url(nav_next["href"])
        nav["next_episode"] = {"slug": extract_slug(u), "anichinUrl": u}

    # Sidebar episodes list (optional)
    episodes_list = []
    for a in soup.select("div.bixbox.lpl li a"):
        href = a.get("href", "")
        if not href:
            continue
        full = abs_url(href)
        ep_txt = safe_text(a.select_one(".lpl_title")) or safe_text(a)
        episodes_list.append({"episode": ep_txt, "slug": extract_slug(full), "anichinUrl": full})

    return {
        "status": "success",
        "creator": CREATOR,
        "episode": episode_title,
        "streaming": {"main_url": main_url, "servers": servers},
        "download_url": downloads,
        "navigation": nav,
        "episodes_list": episodes_list,
        "anichinUrl": url,
    }


def scrape_all_genres():
    """
    Ambil all genres dari halaman filter:
    https://anichin.moe/anime/?status=&order=
    Biasanya ada input name="genre[]" value="adventure"
    """
    soup = get_soup(f"{BASE_URL}/anime/", params={"status": "", "order": ""})
    if not soup:
        return []

    results = []
    seen = set()

    # Strategy 1: checkbox genre[]
    for inp in soup.select("input[name='genre[]']"):
        slug = (inp.get("value") or "").strip()
        if not slug:
            continue

        label_txt = ""
        lab = None
        if inp.get("id"):
            lab = soup.select_one(f"label[for='{inp.get('id')}']")
        if not lab:
            lab = inp.find_parent("label")
        label_txt = safe_text(lab)

        name = label_txt or slug.replace("-", " ").title()

        if slug not in seen:
            seen.add(slug)
            results.append(
                {
                    "name": name,
                    "slug": slug,
                    "href": f"/donghua/genres/{slug}",
                    "anichinUrl": f"{BASE_URL}/anime/?genre%5B%5D={slug}&status=&type=&sub=&order=",
                }
            )

    # Strategy 2: fallback select option
    if not results:
        for opt in soup.select("select option"):
            v = (opt.get("value") or "").strip()
            t = safe_text(opt)
            if v and re.fullmatch(r"[a-z0-9-]+", v) and t and v not in seen:
                seen.add(v)
                results.append(
                    {
                        "name": t,
                        "slug": v,
                        "href": f"/donghua/genres/{v}",
                        "anichinUrl": f"{BASE_URL}/anime/?genre%5B%5D={v}&status=&type=&sub=&order=",
                    }
                )

    results.sort(key=lambda x: x["name"].lower())
    return results


# --------------------------
# ENDPOINTS: LIST
# --------------------------
@app.get("/")
def root():
    return {
        "status": "success",
        "creator": CREATOR,
        "message": "API hidup. Manusia tetap ribet, tapi API hidup.",
        "docs": "/docs",
    }


@app.get("/api/update")
def list_update():
    soup = get_soup(f"{BASE_URL}/anime/", params={"status": "", "type": "", "sub": "", "order": "update"})
    return {"status": "success", "creator": CREATOR, "order": "update", "data": parse_list_page(soup)}


@app.get("/api/popular")
def list_popular():
    soup = get_soup(f"{BASE_URL}/anime/", params={"order": "popular"})
    return {"status": "success", "creator": CREATOR, "order": "popular", "data": parse_list_page(soup)}


@app.get("/api/rating")
def list_rating():
    soup = get_soup(f"{BASE_URL}/anime/", params={"status": "", "type": "", "sub": "", "order": "rating"})
    return {"status": "success", "creator": CREATOR, "order": "rating", "data": parse_list_page(soup)}


@app.get("/api/completed")
def list_completed():
    soup = get_soup(f"{BASE_URL}/anime/", params={"status": "completed", "order": ""})
    return {"status": "success", "creator": CREATOR, "status_filter": "completed", "data": parse_list_page(soup)}


@app.get("/api/ongoing")
def list_ongoing():
    soup = get_soup(f"{BASE_URL}/anime/", params={"status": "ongoing", "type": "", "sub": ""})
    return {"status": "success", "creator": CREATOR, "status_filter": "ongoing", "data": parse_list_page(soup)}


@app.get("/api/list")
def list_universal(
    status: str = "",
    type: str = "",
    sub: str = "",
    order: str = "",
    genre: list[str] = Query(default=[], alias="genre[]"),
):
    params = build_list_params(status, type, sub, order, genre)
    soup = get_soup(f"{BASE_URL}/anime/", params=params)
    return {
        "status": "success",
        "creator": CREATOR,
        "filters": {"status": status, "type": type, "sub": sub, "order": order, "genre[]": genre},
        "data": parse_list_page(soup),
    }


# --------------------------
# ENDPOINTS: GENRES
# --------------------------
@app.get("/api/genres")
def all_genres():
    data = scrape_all_genres()
    return {"status": "success", "creator": CREATOR, "count": len(data), "data": data}


@app.get("/api/genres/{slug}")
def genre_detail(slug: str):
    params = {"genre[]": [slug], "status": "", "type": "", "sub": "", "order": ""}
    soup = get_soup(f"{BASE_URL}/anime/", params=params)
    return {"status": "success", "creator": CREATOR, "genre": slug, "data": parse_list_page(soup)}


# --------------------------
# ENDPOINTS: SCHEDULE
# --------------------------
@app.get("/api/schedule")
def schedule():
    soup = get_soup(f"{BASE_URL}/schedule/")
    out = []

    if soup:
        for box in soup.select("div.bixbox"):
            day_el = box.select_one("div.releases h3") or box.select_one("h3")
            if not day_el:
                continue

            day_name = safe_text(day_el)
            items = []

            for it in box.select("div.listupd article.bs, div.listupd div.bs"):
                c = parse_card(it, is_schedule=True)
                if c:
                    items.append(c)

            if items:
                out.append({"day": day_name, "donghua_list": items})

    return {"status": "success", "creator": CREATOR, "schedule": out}


# --------------------------
# ENDPOINTS: SEARCH
# --------------------------
@app.get("/api/search")
def search(s: str = Query(..., alias="s")):
    soup = get_soup(BASE_URL, params={"s": s})
    return {"status": "success", "creator": CREATOR, "query": s, "data": parse_list_page(soup)}


# --------------------------
# ENDPOINTS: SERIES & EPISODE DETAIL (yang lu minta)
# --------------------------
@app.get("/api/series")
def series_detail(url: str):
    if not url.startswith("http"):
        url = abs_url(url)
    soup = get_soup(url)
    if not soup:
        raise HTTPException(status_code=404, detail="Gagal akses series page / page not found")
    return parse_series_detail(soup, url)


@app.get("/api/episode")
def episode_detail(url: str):
    if not url.startswith("http"):
        url = abs_url(url)
    soup = get_soup(url)
    if not soup:
        raise HTTPException(status_code=404, detail="Gagal akses episode page / page not found")
    return parse_episode_detail(soup, url)


# --------------------------
# OPTIONAL: 1 endpoint detail auto-detect (kalau lu males mikir URL ini series atau episode)
# --------------------------
@app.get("/api/detail")
def detail_auto(url: str):
    if not url.startswith("http"):
        url = abs_url(url)
    soup = get_soup(url)
    if not soup:
        raise HTTPException(status_code=404, detail="Gagal akses page / page not found")

    # deteksi episode page
    is_episode_page = bool(
        soup.select_one("#playeroptionsul")
        or soup.select_one("select.mirror")
        or soup.select_one(".video-content iframe")
        or soup.select_one(".mctnx")
    )

    if is_episode_page:
        return parse_episode_detail(soup, url)
    return parse_series_detail(soup, url)
