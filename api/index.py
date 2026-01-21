from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://anichin.cafe/"
}

BASE_URL = "https://anichin.cafe"
CREATOR = "Sanka Vollerei"

# --- HELPER ---
def get_soup(url, params=None):
    try:
        req = requests.get(url, headers=HEADERS, params=params, timeout=20)
        req.raise_for_status()
        return BeautifulSoup(req.text, "html.parser")
    except: return None

def extract_slug(url):
    return url.strip("/").split("/")[-1] if url else ""

# --- PARSER UTAMA (STRICT FORMAT) ---
def parse_card(element, is_schedule=False):
    """
    Parser ini MEMAKSA data terisi sesuai request user.
    Tidak ada field kosong.
    """
    try:
        # Title & Link
        title_el = element.select_one("div.tt") or element.select_one(".entry-title")
        link_el = element.select_one("a")
        img_el = element.select_one("img")
        
        if not title_el or not link_el: return None
        
        # Data Dasar
        title = title_el.text.strip()
        url = link_el["href"]
        slug = extract_slug(url)
        poster = img_el["src"] if img_el else ""
        
        # === LOGIKA PEMAKSAAN DATA (DEFAULT VALUES) ===
        # Status (Jika kosong/gagal scrape -> Default "Ongoing")
        status_el = element.select_one("div.status") or element.select_one(".stat")
        status = status_el.text.strip() if status_el else "Ongoing"
        if not status: status = "Ongoing" # Double check

        # Type (Jika kosong -> Default "Donghua")
        type_el = element.select_one("div.typez")
        type_show = type_el.text.strip() if type_el else "Donghua"
        if not type_show: type_show = "Donghua"

        # Episode
        ep_el = element.select_one("div.epx") or element.select_one(".ep")
        episode = ep_el.text.strip() if ep_el else "??"

        # Sub (Selalu "Sub")
        sub = "Sub"

        # Base Object
        data = {
            "title": title,
            "slug": slug,
            "poster": poster,
            "status": status,
            "type": type_show,
            "sub": sub,
            "href": f"/donghua/detail/{slug}",
            "anichinUrl": url
        }

        # Jika ini untuk Schedule, tambahkan release_time
        if is_schedule:
            time_el = element.select_one("div.time")
            # Format: "at 08:17"
            data["release_time"] = time_el.text.strip() if time_el else "at ??:??"
            data["episode"] = episode # Schedule minta key 'episode'
        else:
            # Endpoint lain minta key 'current_episode' (opsional, sesuaikan json kamu)
            # Tapi JSON kamu di latest pakai 'status' & 'type' & 'sub', tidak highlight episode di root
            pass

        return data
    except: return None

# --- ENDPOINTS LIST (URL SESUAI REQUEST) ---

@app.get("/")
def home():
    # URL: /seri/?status=&type=&order=update
    soup = get_soup(f"{BASE_URL}/seri/", params={"status": "", "type": "", "order": "update"})
    data = []
    if soup:
        for item in soup.select("div.listupd article.bs"):
            c = parse_card(item)
            if c: data.append(c)
    return {"status": "success", "creator": CREATOR, "latest_donghua": data}

@app.get("/api/popular")
def popular():
    # URL: /seri/?status=&type=&order=popular
    soup = get_soup(f"{BASE_URL}/seri/", params={"status": "", "type": "", "order": "popular"})
    data = []
    if soup:
        for item in soup.select("div.listupd article.bs"):
            c = parse_card(item)
            if c: data.append(c)
    return {"status": "success", "creator": CREATOR, "popular_donghua": data}

@app.get("/api/rating")
def rating():
    # URL: /seri/?sub=&order=rating
    soup = get_soup(f"{BASE_URL}/seri/", params={"sub": "", "order": "rating"})
    data = []
    if soup:
        for item in soup.select("div.listupd article.bs"):
            c = parse_card(item)
            if c: data.append(c)
    return {"status": "success", "creator": CREATOR, "rating_donghua": data}

@app.get("/api/ongoing")
def ongoing():
    # URL: /seri/?status=ongoing&sub=
    soup = get_soup(f"{BASE_URL}/seri/", params={"status": "ongoing", "sub": ""})
    data = []
    if soup:
        for item in soup.select("div.listupd article.bs"):
            c = parse_card(item)
            if c: data.append(c)
    return {"status": "success", "creator": CREATOR, "ongoing_donghua": data}

@app.get("/api/completed")
def completed():
    # URL: /seri/?status=completed&type=&order=
    soup = get_soup(f"{BASE_URL}/seri/", params={"status": "completed", "type": "", "order": ""})
    data = []
    if soup:
        for item in soup.select("div.listupd article.bs"):
            c = parse_card(item)
            if c: data.append(c)
    return {"status": "success", "creator": CREATOR, "completed_donghua": data}

# --- SCHEDULE (FORMAT SPESIFIK) ---
@app.get("/api/schedule")
def schedule():
    soup = get_soup(f"{BASE_URL}/schedule/")
    schedule_data = []
    
    if soup:
        for box in soup.select("div.bixbox"):
            day_el = box.select_one("div.releases h3")
            if not day_el: continue
            
            day_name = day_el.text.strip() # Contoh: "Wednesday"
            donghua_list = []
            
            for item in box.select("div.listupd div.bs"):
                # Pakai parser mode schedule=True agar dapat release_time
                c = parse_card(item, is_schedule=True)
                if c: donghua_list.append(c)
            
            if donghua_list:
                schedule_data.append({
                    "day": day_name,
                    "donghua_list": donghua_list
                })

    return {"status": "success", "creator": CREATOR, "schedule": schedule_data}

# --- GENRES & SEARCH ---
@app.get("/api/genres")
def genres():
    soup = get_soup(f"{BASE_URL}/seri/")
    data = []
    seen = set()
    if soup:
        for a in soup.select("a[href*='/genres/']"):
            if a.text and a['href'] not in seen:
                seen.add(a['href'])
                data.append({
                    "name": a.text.strip(),
                    "slug": extract_slug(a['href']),
                    "href": f"/donghua/genres/{extract_slug(a['href'])}",
                    "anichinUrl": a['href']
                })
    return {"creator": CREATOR, "data": sorted(data, key=lambda x: x['name'])}

@app.get("/api/genres/{slug}")
def genre_detail(slug: str):
    soup = get_soup(f"{BASE_URL}/genres/{slug}/")
    data = []
    if soup:
        for item in soup.select("div.listupd article.bs"):
            c = parse_card(item)
            if c: data.append(c)
    return {"creator": CREATOR, "data": data}

@app.get("/api/search")
def search(s: str = Query(..., alias="s")):
    soup = get_soup(BASE_URL, params={'s': s})
    data = []
    if soup:
        for item in soup.select("div.listupd article.bs"):
            c = parse_card(item)
            if c: data.append(c)
    return {"creator": CREATOR, "data": data}

# --- DETAIL (FULL STRUCTURE) ---
@app.get("/api/detail")
def get_detail(url: str):
    soup = get_soup(url)
    if not soup: raise HTTPException(404)

    # Deteksi Halaman (Video vs Info)
    is_video = bool(soup.select_one("#playeroptionsul") or soup.select_one(".video-content"))

    if is_video:
        # === HALAMAN EPISODE (NONTON) ===
        title = soup.select_one("h1.entry-title").text.strip()
        
        # 1. Streaming
        servers = []
        for li in soup.select("ul#playeroptionsul li"):
            name = li.select_one(".title").text.strip()
            link = li.get("data-src") or li.get("data-url")
            if link: servers.append({"name": name, "url": link})
        
        if not servers:
            iframe = soup.select_one(".video-content iframe")
            if iframe: servers.append({"name": "Default", "url": iframe["src"]})
            
        main_url = servers[0] if servers else {"name": "None", "url": ""}

        # 2. Downloads (Nested Format: 360p -> Providers)
        downloads = {}
        # Cari semua container download yang mungkin
        dl_boxes = soup.select("div.mctnx div.soraddl") + soup.select("div.soraurl")
        
        for box in dl_boxes:
            # Resolusi (Misal: 360p, 480p)
            res_el = box.select_one("div.res") or box.select_one("h3")
            if not res_el: continue
            
            res_text = re.sub(r"[^0-9]", "", res_el.text.strip()) # Ambil angkanya saja
            if not res_text: res_text = "unknown"
            
            # Key JSON: download_url_360p
            key = f"download_url_{res_text}p"
            
            links_map = {}
            for a in box.select("a"):
                provider = a.text.strip()
                links_map[provider] = a["href"]
            
            if links_map: downloads[key] = links_map

        # 3. Navigation (Nested Object)
        nav = {}
        nav_prev = soup.select_one("div.nvs .nav-previous a")
        nav_next = soup.select_one("div.nvs .nav-next a")
        nav_all = soup.select_one("div.nvs .nvsc a")

        if nav_all:
            nav["all_episodes"] = {
                "slug": extract_slug(nav_all["href"]),
                "href": f"/donghua/detail/{extract_slug(nav_all['href'])}",
                "anichinUrl": nav_all["href"]
            }
        if nav_prev:
            nav["previous_episode"] = {
                "episode": "Previous", 
                "slug": extract_slug(nav_prev["href"]),
                "href": f"/donghua/episode/{extract_slug(nav_prev['href'])}",
                "anichinUrl": nav_prev["href"]
            }
        if nav_next:
            nav["next_episode"] = {
                "episode": "Next", 
                "slug": extract_slug(nav_next["href"]),
                "href": f"/donghua/episode/{extract_slug(nav_next['href'])}",
                "anichinUrl": nav_next["href"]
            }

        # 4. Details Metadata
        # Kita ambil series title dari judul episode
        series_title = re.sub(r'(Episode\s+\d+.*)', '', title, flags=re.IGNORECASE).strip()
        series_slug = extract_slug(url).split("-episode-")[0]
        thumb = soup.select_one("div.thumb img")
        
        # Hardcode 'admin' & 'Donghua' sesuai request
        donghua_details = {
            "title": series_title,
            "slug": series_slug,
            "poster": thumb["src"] if thumb else "",
            "type": "Donghua", # Default
            "released": "Unknown", # Bisa discrape dari meta jika perlu
            "uploader": "admin",
            "href": f"/donghua/detail/{series_slug}",
            "anichinUrl": f"{BASE_URL}/seri/{series_slug}/"
        }

        # 5. List Episodes
        ep_list = []
        for a in soup.select("div.bixbox.lpl li a") + soup.select("#episode_list li a"):
            ep_txt = a.select_one(".lpl_title")
            ep_title = ep_txt.text.strip() if ep_txt else a.text.strip()
            ep_list.append({
                "episode": ep_title,
                "slug": extract_slug(a["href"]),
                "href": f"/donghua/episode/{extract_slug(a['href'])}",
                "anichinUrl": a["href"]
            })

        return {
            "status": "success",
            "creator": CREATOR,
            "episode": title,
            "streaming": {"main_url": main_url, "servers": servers},
            "download_url": downloads,
            "donghua_details": donghua_details,
            "navigation": nav,
            "episodes_list": ep_list
        }

    else:
        # === HALAMAN INFO SERIES ===
        title = soup.select_one("h1.entry-title").text.strip()
        thumb = soup.select_one("div.thumb img")
        
        def get_val(k):
            # Cari di tabel info
            for s in soup.select("div.spe span"):
                if k in s.text: return s.text.replace(k, "").replace(":", "").strip()
            return "-"

        genres = [{"name": a.text.strip(), "slug": extract_slug(a['href']), "anichinUrl": a['href']} for a in soup.select("div.genxed a")]
        
        eps = []
        for a in soup.select("ul#episode_list li a"):
            eps.append({
                "episode": a.select_one(".epl-title").text.strip() if a.select_one(".epl-title") else a.text.strip(),
                "slug": extract_slug(a['href']),
                "anichinUrl": a['href']
            })

        syn = soup.select_one("div.entry-content[itemprop='description']")
        
        # Info lengkap
        return {
            "status": get_val("Status") or "Completed", # Default jika kosong
            "creator": CREATOR,
            "title": title,
            "poster": thumb["src"] if thumb else "",
            "studio": get_val("Studio"),
            "released": get_val("Released"),
            "duration": get_val("Duration"),
            "type": get_val("Type") or "Donghua",
            "genres": genres,
            "synopsis": syn.get_text(separator="\n").strip() if syn else "",
            "episodes_list": eps
        }
