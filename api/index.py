from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import re

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
    "Referer": "https://anichin.cafe/"
}

BASE_URL = "https://anichin.cafe"
CREATOR = "Sanka Vollerei"

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

def parse_card(element):
    """Parser untuk kartu anime di halaman list (Home, Search, dll)"""
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
            "status": status_el.text.strip() if status_el else "Unknown",
            "type": type_el.text.strip() if type_el else "Donghua",
            "current_episode": ep_el.text.strip() if ep_el else "?",
            "href": f"/donghua/detail/{slug}",
            "anichinUrl": url
        }
    except: return None

def get_list_by_filter(status="", order="", type_param="", sub=""):
    """Helper untuk mengambil data dari halaman /seri/ dengan filter"""
    params = {
        "status": status,
        "order": order,
        "type": type_param,
        "sub": sub
    }
    soup = get_soup(f"{BASE_URL}/seri/", params=params)
    if not soup: raise HTTPException(status_code=500, detail="Failed to fetch data")
    
    data = []
    for item in soup.select("div.listupd article.bs"):
        c = parse_card(item)
        if c: data.append(c)
        
    return {"status": "success", "creator": CREATOR, "data": data}

# --- ENDPOINTS UTAMA ---

@app.get("/")
def home():
    # Latest Release: /seri/?status=&type=&order=update
    return get_list_by_filter(order="update")

@app.get("/api/popular")
def popular():
    # Popular: /seri/?status=&type=&order=popular
    return get_list_by_filter(order="popular")

@app.get("/api/rating")
def rating():
    # Highest Rating: /seri/?sub=&order=rating
    return get_list_by_filter(order="rating")

@app.get("/api/ongoing")
def ongoing():
    # Ongoing: /seri/?status=ongoing&sub=
    return get_list_by_filter(status="ongoing")

@app.get("/api/completed")
def completed():
    # Completed: /seri/?status=completed&type=&order=
    return get_list_by_filter(status="completed")

# --- GENRES & SEASONS ---

@app.get("/api/genres")
def get_genres():
    soup = get_soup(f"{BASE_URL}/seri/")
    if not soup: raise HTTPException(status_code=500)
    
    genres = []
    seen = set()
    # Mencari link genre di sidebar/widget
    for a in soup.select("a[href*='/genres/']"):
        try:
            name = a.text.strip()
            href = a["href"]
            slug = extract_slug(href)
            if slug and slug not in seen and name:
                seen.add(slug)
                genres.append({
                    "name": name,
                    "slug": slug,
                    "href": f"/donghua/genres/{slug}",
                    "anichinUrl": href
                })
        except: continue
    
    return {"creator": CREATOR, "data": sorted(genres, key=lambda x: x['name'])}

@app.get("/api/genres/{slug}")
def get_by_genre(slug: str):
    soup = get_soup(f"{BASE_URL}/genres/{slug}/")
    if not soup: raise HTTPException(status_code=404)
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]
    return {"creator": CREATOR, "data": data}

@app.get("/api/season/{slug}")
def get_by_season(slug: str):
    soup = get_soup(f"{BASE_URL}/season/{slug}/")
    if not soup: raise HTTPException(status_code=404)
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]
    return {"creator": CREATOR, "data": data}

# --- SCHEDULE & SEARCH ---

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
                time = item.select_one("div.time").text.strip() if item.select_one("div.time") else ""
                # Modifikasi field agar sesuai request schedule
                donghua_list.append({
                    "title": c['title'], "slug": c['slug'], "poster": c['poster'], 
                    "release_time": time, "href": c['href'], "anichinUrl": c['anichinUrl']
                })
        if donghua_list: schedule_data.append({"day": day_name, "donghua_list": donghua_list})
    return {"status": "success", "creator": CREATOR, "schedule": schedule_data}

@app.get("/api/search")
def search(s: str = Query(..., alias="s")):
    soup = get_soup(BASE_URL, params={'s': s})
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]
    return {"creator": CREATOR, "data": data}

# --- DETAIL (EPISODE & INFO) ---

@app.get("/api/detail")
def get_detail(url: str):
    soup = get_soup(url)
    if not soup: raise HTTPException(status_code=404)

    # Cek apakah ini halaman Nonton (Episode) atau Info Series
    is_video = bool(soup.select_one("#playeroptionsul") or soup.select_one(".video-content") or soup.select_one("select.mirror"))

    if is_video:
        # === EPISODE VIEW ===
        title = soup.select_one("h1.entry-title").text.strip()
        
        # 1. Servers
        servers = []
        # List Mirror (UL/LI)
        for li in soup.select("ul#playeroptionsul li"):
            name = li.select_one(".title").text.strip()
            link = li.get("data-src") or li.get("data-url")
            if link: servers.append({"name": name, "url": link})
        # Select Option Mirror (Fallback)
        if not servers:
            for opt in soup.select("select.mirror option"):
                val = opt.get("value")
                if val: servers.append({"name": opt.text.strip(), "url": val})
        # Iframe Default (Fallback Akhir)
        if not servers:
            iframe = soup.select_one(".video-content iframe")
            if iframe: servers.append({"name": "Default", "url": iframe["src"]})
            
        main_url = servers[0] if servers else {"name": "None", "url": ""}
        
        # 2. Downloads
        downloads = {}
        for box in soup.select("div.mctnx div.soraddl") + soup.select("div.soraurl"):
            res_el = box.select_one("div.res") or box.select_one("h3")
            if not res_el: continue
            res_text = re.sub(r"[^0-9]", "", res_el.text) or "HD"
            key = f"download_url_{res_text}p"
            links_map = {}
            for a in box.select("a"): links_map[a.text.strip()] = a["href"]
            downloads[key] = links_map

        # 3. Navigation
        nav = {}
        nav_prev = soup.select_one("div.nvs .nav-previous a")
        if nav_prev: 
            nav["previous_episode"] = {
                "episode": "Previous Episode", 
                "slug": extract_slug(nav_prev["href"]),
                "href": f"/donghua/episode/{extract_slug(nav_prev['href'])}",
                "anichinUrl": nav_prev["href"]
            }
        nav_next = soup.select_one("div.nvs .nav-next a")
        if nav_next: 
            nav["next_episode"] = {
                "episode": "Next Episode", 
                "slug": extract_slug(nav_next["href"]),
                "href": f"/donghua/episode/{extract_slug(nav_next['href'])}",
                "anichinUrl": nav_next["href"]
            }
        nav_all = soup.select_one("div.nvs .nvsc a")
        if nav_all:
             nav["all_episodes"] = {
                 "slug": extract_slug(nav_all["href"]),
                 "href": f"/donghua/detail/{extract_slug(nav_all['href'])}",
                 "anichinUrl": nav_all["href"]
             }

        # 4. Donghua Details (Metadata Singkat)
        # Note: posted_by/uploader dihapus sesuai request
        thumb = soup.select_one("div.thumb img")
        donghua_details = {
            "title": title.split("Episode")[0].strip(),
            "slug": extract_slug(url),
            "poster": thumb["src"] if thumb else "",
            "type": "Donghua",
            "released": "Unknown",
            "href": f"/donghua/detail/{extract_slug(url)}",
            "anichinUrl": url
        }

        # 5. Episode List
        episodes_list = []
        for a in soup.select("div.bixbox.lpl li a"):
             episodes_list.append({
                 "episode": a.text.strip(), 
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
            "episodes_list": episodes_list
        }

    else:
        # === SERIES INFO VIEW ===
        title = soup.select_one("h1.entry-title").text.strip()
        thumb = soup.select_one("div.thumb img")["src"] if soup.select_one("div.thumb img") else ""
        
        def get_val(k):
            # Helper untuk ambil data dari div.spe (Info Table)
            found = soup.select_one(f"div.spe span:contains('{k}')")
            if found: return found.text.replace(k, "").replace(":", "").strip()
            for s in soup.select("div.spe span"):
                if k in s.text: return s.text.replace(k, "").replace(":", "").strip()
            return "-"

        genres = []
        for a in soup.select("div.genxed a"):
            genres.append({
                "name": a.text.strip(), 
                "slug": extract_slug(a["href"]), 
                "href": f"/donghua/genres/{extract_slug(a['href'])}", 
                "anichinUrl": a["href"]
            })

        episodes_list = []
        for li in soup.select("ul#episode_list li") + soup.select("div.eplister li"):
            a = li.select_one("a")
            if a: 
                episodes_list.append({
                    "episode": a.text.strip(), 
                    "slug": extract_slug(a["href"]), 
                    "href": f"/donghua/episode/{extract_slug(a['href'])}", 
                    "anichinUrl": a["href"]
                })

        syn = soup.select_one("div.entry-content[itemprop='description']")
        
        return {
            "status": get_val("Status"),
            "creator": CREATOR,
            "title": title,
            "poster": thumb,
            "studio": get_val("Studio"),
            "released": get_val("Released"),
            "duration": get_val("Duration"),
            "type": get_val("Type"),
            "genres": genres,
            "synopsis": syn.get_text(separator="\n").strip() if syn else "",
            "episodes_list": episodes_list
        }
