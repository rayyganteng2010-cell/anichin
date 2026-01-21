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
CREATOR = "Ray Ackerman"

# --- HELPER FUNCTIONS ---
def get_soup(url, params=None):
    try:
        req = requests.get(url, headers=HEADERS, params=params, timeout=20)
        req.raise_for_status()
        return BeautifulSoup(req.text, "html.parser")
    except Exception as e:
        print(f"Error accessing {url}: {e}")
        return None

def extract_slug(url):
    parts = url.strip("/").split("/")
    return parts[-1] if parts else ""

# --- PARSER REAL (NO FAKE DATA) ---
def parse_card(element):
    try:
        # Title & Link
        title_el = element.select_one("div.tt") or element.select_one(".entry-title")
        link_el = element.select_one("a")
        img_el = element.select_one("img")
        
        if not title_el or not link_el: return None
        
        url = link_el["href"]
        
        # --- SCRAPING REAL DATA ---
        # Status (Cari elemen .status atau .stat)
        status_el = element.select_one("div.status") or element.select_one(".stat")
        status = status_el.text.strip() if status_el else "?" # Jika ga nemu, kasih ? jangan ngarang
        
        # Type (Cari .typez)
        type_el = element.select_one("div.typez")
        type_show = type_el.text.strip() if type_el else "Donghua" # Default wajar karena web khusus donghua
        
        # Episode
        ep_el = element.select_one("div.epx") or element.select_one(".ep")
        episode = ep_el.text.strip() if ep_el else ""
        
        # Subtitle (Cari badge sub)
        sub_el = element.select_one("div.sb") or element.select_one(".sub")
        sub = sub_el.text.strip() if sub_el else "Sub" # Default umum

        return {
            "title": title_el.text.strip(),
            "slug": extract_slug(url),
            "poster": img_el["src"] if img_el else "",
            "status": status,
            "type": type_show,
            "sub": sub,
            "current_episode": episode, # Untuk endpoint latest
            "episode": episode,         # Untuk endpoint schedule (biar aman key-nya ada dua2nya)
            "href": f"/donghua/detail/{extract_slug(url)}",
            "anichinUrl": url
        }
    except: return None

# --- ENDPOINTS ---

@app.get("/")
def home():
    # Mengambil REAL data update terbaru
    soup = get_soup(f"{BASE_URL}/seri/", params={"order": "update"})
    if not soup: raise HTTPException(500)
    
    data = []
    # Loop elemen artikel
    for item in soup.select("div.listupd article.bs"):
        card = parse_card(item)
        if card:
            # Hapus key duplikat biar rapi sesuai request latest_donghua
            res = {k: v for k, v in card.items() if k != 'episode'} 
            data.append(res)
            
    return {"status": "success", "creator": CREATOR, "latest_donghua": data}

@app.get("/api/ongoing")
def ongoing():
    soup = get_soup(f"{BASE_URL}/seri/", params={"status": "ongoing"})
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]
    return {"status": "success", "creator": CREATOR, "ongoing_donghua": data}

@app.get("/api/completed")
def completed():
    soup = get_soup(f"{BASE_URL}/seri/", params={"status": "completed"})
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]
    return {"status": "success", "creator": CREATOR, "completed_donghua": data}

@app.get("/api/schedule")
def schedule():
    soup = get_soup(f"{BASE_URL}/schedule/")
    data = []
    
    # Scrape Box Jadwal
    for box in soup.select("div.bixbox"):
        day = box.select_one("div.releases h3")
        if not day: continue
        
        l = []
        for i in box.select("div.listupd div.bs"):
            c = parse_card(i)
            if c:
                # Ambil Time secara Real
                time_el = i.select_one("div.time")
                release_time = time_el.text.strip() if time_el else ""
                
                # Format khusus schedule
                l.append({
                    "title": c['title'],
                    "slug": c['slug'],
                    "poster": c['poster'],
                    "release_time": release_time,
                    "episode": c['current_episode'], # Pakai hasil scrape real
                    "href": c['href'],
                    "anichinUrl": c['anichinUrl']
                })
        
        if l: data.append({"day": day.text.strip(), "donghua_list": l})
        
    return {"status": "success", "creator": CREATOR, "schedule": data}

@app.get("/api/genres")
def genres():
    soup = get_soup(f"{BASE_URL}/seri/")
    res = []
    seen = set()
    # Scrape real genres dari sidebar
    for a in soup.select("a[href*='/genres/']"):
        if a.text and a['href'] not in seen:
            seen.add(a['href'])
            res.append({
                "name": a.text.strip(),
                "slug": extract_slug(a['href']),
                "href": f"/donghua/genres/{extract_slug(a['href'])}",
                "anichinUrl": a['href']
            })
    return {"creator": CREATOR, "data": sorted(res, key=lambda x: x['name'])}

@app.get("/api/genres/{slug}")
def genre_detail(slug: str):
    soup = get_soup(f"{BASE_URL}/genres/{slug}/")
    return {"creator": CREATOR, "data": [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]}

@app.get("/api/season/{slug}")
def season_detail(slug: str):
    soup = get_soup(f"{BASE_URL}/season/{slug}/")
    return {"creator": CREATOR, "data": [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]}

@app.get("/api/search")
def search(s: str = Query(..., alias="s")):
    soup = get_soup(BASE_URL, params={'s': s})
    return {"creator": CREATOR, "data": [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]}

# --- DETAIL (FULL REAL SCRAPING) ---
@app.get("/api/detail")
def get_detail(url: str):
    soup = get_soup(url)
    if not soup: raise HTTPException(404)

    is_episode = bool(soup.select_one("#playeroptionsul") or soup.select_one(".video-content") or soup.select_one("select.mirror"))

    if is_episode:
        # === EPISODE MODE ===
        title = soup.select_one("h1.entry-title").text.strip()
        
        # 1. Real Streaming Links
        servers = []
        for li in soup.select("ul#playeroptionsul li"):
            name = li.select_one(".title").text.strip()
            link = li.get("data-src") or li.get("data-url")
            if link: servers.append({"name": name, "url": link})
        
        if not servers:
            # Fallback iframe
            iframe = soup.select_one(".video-content iframe")
            if iframe: servers.append({"name": "Default", "url": iframe["src"]})
            
        main_url = servers[0] if servers else {"name": "None", "url": ""}

        # 2. Real Download Links
        downloads = {}
        dl_elements = soup.select("div.mctnx div.soraddl") + soup.select("div.soraurl")
        
        for box in dl_elements:
            res_el = box.select_one("div.res") or box.select_one("h3")
            if not res_el: continue
            
            # Ambil resolusi real dari teks (360p, 480p, dll)
            res_text = res_el.text.strip()
            res_clean = re.sub(r"[^0-9]", "", res_text) 
            key = f"download_url_{res_clean}p" if res_clean else "download_url_unknown"

            links_map = {}
            for a in box.select("a"):
                provider = a.text.strip()
                links_map[provider] = a["href"]
            
            if links_map: downloads[key] = links_map

        # 3. Real Navigation
        nav = {}
        nav_prev = soup.select_one("div.nvs .nav-previous a")
        nav_next = soup.select_one("div.nvs .nav-next a")
        nav_all = soup.select_one("div.nvs .nvsc a")

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
        if nav_all:
            nav["all_episodes"] = {
                "slug": extract_slug(nav_all["href"]),
                "href": f"/donghua/detail/{extract_slug(nav_all['href'])}",
                "anichinUrl": nav_all["href"]
            }

        # 4. Details Metadata (Scraped)
        thumb = soup.select_one("div.thumb img")
        
        # Coba ambil info Type & Status dari breadcrumb atau info box jika ada
        type_txt = "Donghua" 
        released_txt = "?"
        uploader_txt = "Admin" # Default anichin biasanya admin, tapi coba cari
        
        # Scrape Author/Uploader jika ada
        auth_el = soup.select_one(".author i") or soup.select_one(".post-author")
        if auth_el: uploader_txt = auth_el.text.strip()
        
        # Scrape Released Date (Posted on)
        date_el = soup.select_one("time[itemprop='datePublished']")
        if date_el: released_txt = date_el.text.strip()

        donghua_details = {
            "title": title.split("Episode")[0].strip(),
            "slug": extract_slug(url).split("-episode-")[0],
            "poster": thumb["src"] if thumb else "",
            "type": type_txt,
            "released": released_txt, 
            "uploader": uploader_txt,
            "href": f"/donghua/detail/{extract_slug(url).split('-episode-')[0]}",
            "anichinUrl": url
        }

        # 5. Episodes List
        ep_list = []
        # Menggabungkan sumber list episode (sidebar + main list)
        for a in soup.select("div.bixbox.lpl li a") + soup.select("#episode_list li a"):
            ep_txt = a.select_one(".lpl_title").text.strip() if a.select_one(".lpl_title") else a.text.strip()
            ep_list.append({
                "episode": ep_txt,
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
        # === SERIES INFO MODE ===
        title = soup.select_one("h1.entry-title").text.strip()
        thumb = soup.select_one("div.thumb img")
        
        # Helper ambil data table (flexibel)
        def get_info(key):
            for s in soup.select("div.spe span"):
                if key.lower() in s.text.lower():
                    return s.text.split(":", 1)[-1].strip()
            return "?"

        genres = [{"name": a.text.strip(), "slug": extract_slug(a['href']), "anichinUrl": a['href']} for a in soup.select("div.genxed a")]
        
        eps = []
        for a in soup.select("ul#episode_list li a"):
            ep_num = a.select_one(".epl-num").text.strip() if a.select_one(".epl-num") else ""
            ep_title = a.select_one(".epl-title").text.strip() if a.select_one(".epl-title") else a.text.strip()
            eps.append({
                "episode": f"{ep_num} {ep_title}".strip(),
                "slug": extract_slug(a['href']),
                "anichinUrl": a['href']
            })

        syn = soup.select_one("div.entry-content[itemprop='description']")
        
        return {
            "status": get_info("Status"),
            "creator": CREATOR,
            "title": title,
            "poster": thumb["src"] if thumb else "",
            "studio": get_info("Studio"),
            "released": get_info("Released"),
            "duration": get_info("Duration"),
            "type": get_info("Type"),
            "genres": genres,
            "synopsis": syn.get_text(separator="\n").strip() if syn else "",
            "episodes_list": eps
        }
