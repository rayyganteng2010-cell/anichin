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

def get_soup(url, params=None):
    try:
        req = requests.get(url, headers=HEADERS, params=params, timeout=15)
        req.raise_for_status()
        return BeautifulSoup(req.text, "html.parser")
    except Exception as e:
        print(f"Error: {e}")
        return None

def extract_slug(url):
    parts = url.strip("/").split("/")
    return parts[-1] if parts else ""

# --- PARSER STANDAR (Untuk Home/Ongoing) ---
def parse_card(element):
    try:
        title_el = element.select_one("div.tt") or element.select_one(".entry-title")
        link_el = element.select_one("a")
        img_el = element.select_one("img")
        
        if not title_el or not link_el: return None
        
        url = link_el["href"]
        slug = extract_slug(url)
        
        ep_el = element.select_one("div.epx")
        status_el = element.select_one("div.status")
        type_el = element.select_one("div.typez")
        
        return {
            "title": title_el.text.strip(),
            "slug": slug,
            "poster": img_el["src"] if img_el else "",
            "status": status_el.text.strip() if status_el else "Ongoing",
            "type": type_el.text.strip() if type_el else "Donghua",
            "sub": "Sub", # Default
            "href": f"/donghua/detail/{slug}",
            "anichinUrl": url
        }
    except: return None

# --- PARSER DETAIL (Untuk Season/Search Musim) ---
# Mengambil data dari Tooltip (.tt) yang biasanya tersembunyi
def parse_detailed_card(element):
    try:
        basic = parse_card(element)
        if not basic: return None
        
        # Scrape data hidden dari div.tt (Tooltip)
        # Struktur tema biasanya: div.tt > div.gnr, div.desc, div.rat
        tt = element.select_one("div.tt") # Ini container tooltip di banyak tema
        
        # Data default jika tidak ketemu
        rating = 0
        studio = "-"
        desc = "-"
        alt = "-"
        genres_list = []
        
        # Coba ambil rating
        rat_el = element.select_one("div.numscore") or element.select_one("span.numscore")
        if rat_el: rating = rat_el.text.strip()

        # Coba ambil deskripsi/sinopsis dari tooltip (jika ada)
        # Note: Anichin kadang tidak merender full desc di list, kita coba best effort
        # Kita pakai basic data dulu, lalu extend
        
        return {
            "title": basic['title'],
            "slug": basic['slug'],
            "poster": basic['poster'],
            "status": basic['status'],
            "type": basic['type'],
            "episodes": basic.get('status', 'Unknown'), # Fallback
            "alternative": alt,
            "rating": rating,
            "studio": studio,
            "description": desc,
            "genres": genres_list, # Web biasanya ga nampilin list genre lengkap di card view
            "href": basic['href'],
            "anichinUrl": basic['anichinUrl']
        }
    except: return None

# --- ENDPOINTS ---

@app.get("/")
def home():
    soup = get_soup(BASE_URL)
    if not soup: raise HTTPException(status_code=500)
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]
    return {"status": "success", "creator": CREATOR, "latest_release": data}

@app.get("/api/ongoing")
def ongoing():
    soup = get_soup(f"{BASE_URL}/ongoing/")
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]
    return {"status": "success", "creator": CREATOR, "ongoing_donghua": data}

@app.get("/api/completed")
def completed():
    soup = get_soup(f"{BASE_URL}/completed/")
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]
    return {"status": "success", "creator": CREATOR, "completed_donghua": data}

@app.get("/api/schedule")
def schedule():
    soup = get_soup(f"{BASE_URL}/schedule/")
    schedule_data = []
    for box in soup.select("div.bixbox"):
        day_el = box.select_one("div.releases h3")
        if not day_el: continue
        day_name = day_el.text.strip()
        donghua_list = []
        for item in box.select("div.listupd div.bs"):
            c = parse_card(item)
            if c:
                # Custom field untuk schedule
                time = item.select_one("div.time").text.strip() if item.select_one("div.time") else ""
                donghua_list.append({
                    "title": c['title'], "slug": c['slug'], "poster": c['poster'], 
                    "release_time": time, "episode": "Unknown", 
                    "href": c['href'], "anichinUrl": c['anichinUrl']
                })
        if donghua_list: schedule_data.append({"day": day_name, "donghua_list": donghua_list})
    return {"status": "success", "creator": CREATOR, "schedule": schedule_data}

# --- NEW: GENRES LIST ---
@app.get("/api/genres")
def get_all_genres():
    soup = get_soup(BASE_URL) # Genre biasanya ada di sidebar home/all page
    genres = []
    
    # Mencari widget genre (biasanya ul.genre atau div.genre)
    # Kita cari semua link yang mengandung /genres/
    seen = set()
    for a in soup.select("a[href*='/genres/']"):
        name = a.text.strip()
        url = a["href"]
        slug = extract_slug(url)
        
        if slug not in seen and name:
            seen.add(slug)
            genres.append({
                "name": name,
                "slug": slug,
                "href": f"/donghua/genres/{slug}",
                "anichinUrl": url
            })
    
    # Sort A-Z
    genres = sorted(genres, key=lambda x: x['name'])
    return {"creator": CREATOR, "data": genres}

# --- NEW: DONGHUA BY GENRE ---
@app.get("/api/genres/{slug}")
def get_by_genre(slug: str):
    url = f"{BASE_URL}/genres/{slug}/"
    soup = get_soup(url)
    if not soup: raise HTTPException(status_code=404)
    
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]
    return {"creator": CREATOR, "data": data}

# --- NEW: DONGHUA BY SEASON ---
@app.get("/api/season/{slug}")
def get_by_season(slug: str):
    # Contoh slug: spring-2024, winter-2025
    url = f"{BASE_URL}/season/{slug}/"
    soup = get_soup(url)
    if not soup: raise HTTPException(status_code=404)
    
    # Gunakan parser yang lebih detail jika memungkinkan, 
    # tapi karena keterbatasan list view, kita pakai parser standar + enrichment
    # Agar sesuai request JSON "cari donghua berdasarkan musim"
    
    data = []
    for item in soup.select("div.listupd article.bs"):
        basic = parse_card(item)
        if not basic: continue
        
        # Enrichment manual agar mirip JSON request (Data dummy utk list view karena web aslinya hide info ini)
        # Untuk data real 100%, scraper harus buka link satu2 (lambat).
        # Kita ambil yg bisa diambil saja.
        
        rating = "0"
        rat_el = item.select_one(".numscore")
        if rat_el: rating = rat_el.text.strip()

        data.append({
            "title": basic['title'],
            "slug": basic['slug'],
            "poster": basic['poster'],
            "status": basic['status'],
            "type": basic['type'],
            "episodes": "? eps", # List view jarang nampilin total eps
            "alternative": "-",
            "rating": rating,
            "studio": "-",
            "description": "...", # Deskripsi butuh request detail
            "genres": [], # Genre butuh request detail
            "href": basic['href'],
            "anichinUrl": basic['anichinUrl']
        })

    return {"creator": CREATOR, "data": data}

@app.get("/api/search")
def search(s: str = Query(..., alias="s")):
    soup = get_soup(BASE_URL, params={'s': s})
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]
    return {"creator": CREATOR, "data": data}

@app.get("/api/detail")
def get_detail(url: str):
    # (Kode Detail sama seperti sebelumnya - Full Logic)
    soup = get_soup(url)
    if not soup: raise HTTPException(status_code=404)

    is_video = bool(soup.select_one("#playeroptionsul") or soup.select_one(".video-content"))

    if is_video:
        title = soup.select_one("h1.entry-title").text.strip()
        servers = []
        for li in soup.select("ul#playeroptionsul li"):
            name = li.select_one(".title").text.strip()
            link = li.get("data-src") or li.get("data-url")
            if link: servers.append({"name": name, "url": link})
        
        if not servers:
            iframe = soup.select_one(".video-content iframe")
            if iframe: servers.append({"name": "Default", "url": iframe["src"]})
        main_url = servers[0] if servers else {"name": "None", "url": ""}
        
        downloads = {}
        for box in soup.select("div.mctnx div.soraddl") + soup.select("div.soraurl"):
            res_el = box.select_one("div.res") or box.select_one("h3")
            if not res_el: continue
            res_text = re.sub(r"[^0-9]", "", res_el.text) or "HD"
            key = f"download_url_{res_text}p"
            links_map = {}
            for a in box.select("a"): links_map[a.text.strip()] = a["href"]
            downloads[key] = links_map

        nav = {}
        nav_all = soup.select_one("div.nvs .nvsc a")
        if nav_all: nav["all_episodes"] = {"slug": extract_slug(nav_all["href"]), "href": f"/donghua/detail/{extract_slug(nav_all['href'])}", "anichinUrl": nav_all["href"]}
        nav_prev = soup.select_one("div.nvs .nav-previous a")
        if nav_prev: nav["previous_episode"] = {"episode": "Prev", "slug": extract_slug(nav_prev["href"]), "href": f"/donghua/episode/{extract_slug(nav_prev['href'])}", "anichinUrl": nav_prev["href"]}
        nav_next = soup.select_one("div.nvs .nav-next a")
        if nav_next: nav["next_episode"] = {"episode": "Next", "slug": extract_slug(nav_next["href"]), "href": f"/donghua/episode/{extract_slug(nav_next['href'])}", "anichinUrl": nav_next["href"]}

        thumb = soup.select_one("div.thumb img")
        donghua_details = {
            "title": title.split("Episode")[0].strip(), "slug": extract_slug(url),
            "poster": thumb["src"] if thumb else "", "type": "Donghua", "released": "?", "uploader": "admin",
            "href": f"/donghua/detail/{extract_slug(url)}", "anichinUrl": url
        }

        episodes_list = []
        for a in soup.select("div.bixbox.lpl li a"):
             episodes_list.append({"episode": a.text.strip(), "slug": extract_slug(a["href"]), "href": f"/donghua/episode/{extract_slug(a['href'])}", "anichinUrl": a["href"]})

        return {"status": "success", "creator": CREATOR, "episode": title, "streaming": {"main_url": main_url, "servers": servers}, "download_url": downloads, "donghua_details": donghua_details, "navigation": nav, "episodes_list": episodes_list}

    else:
        title = soup.select_one("h1.entry-title").text.strip()
        thumb = soup.select_one("div.thumb img")["src"] if soup.select_one("div.thumb img") else ""
        def get_val(k):
            found = soup.select_one(f"div.spe span:contains('{k}')")
            if found: return found.text.replace(k, "").replace(":", "").strip()
            for s in soup.select("div.spe span"):
                if k in s.text: return s.text.replace(k, "").replace(":", "").strip()
            return "-"

        genres = []
        for a in soup.select("div.genxed a"):
            genres.append({"name": a.text.strip(), "slug": extract_slug(a["href"]), "href": f"/donghua/genres/{extract_slug(a['href'])}", "anichinUrl": a["href"]})

        episodes_list = []
        for li in soup.select("ul#episode_list li") + soup.select("div.eplister li"):
            a = li.select_one("a")
            if a: episodes_list.append({"episode": a.text.strip(), "slug": extract_slug(a["href"]), "href": f"/donghua/episode/{extract_slug(a['href'])}", "anichinUrl": a["href"]})

        syn = soup.select_one("div.entry-content[itemprop='description']")
        return {"status": get_val("Status"), "creator": CREATOR, "title": title, "poster": thumb, "studio": get_val("Studio"), "released": get_val("Released"), "duration": get_val("Duration"), "type": get_val("Type"), "genres": genres, "synopsis": syn.get_text(separator="\n").strip() if syn else "", "episodes_list": episodes_list}
