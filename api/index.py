from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import re
import base64

app = FastAPI()

# --- KONFIGURASI ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Header disesuaikan agar mirip browser asli
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://anichin.moe/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

BASE_URL = "https://anichin.moe"
CREATOR = "Sanka Vollerei"

# --- HELPER FUNCTIONS ---

def get_soup(url, params=None):
    try:
        # Timeout 25 detik karena kadang server lambat
        req = requests.get(url, headers=HEADERS, params=params, timeout=25)
        req.raise_for_status()
        return BeautifulSoup(req.text, "html.parser")
    except Exception as e:
        print(f"Error accessing {url}: {e}")
        return None

def extract_slug(url):
    try:
        return url.strip("/").split("/")[-1]
    except:
        return ""

def decode_url(raw_url):
    """
    Fungsi untuk memecahkan kode Base64 pada link video.
    Mengubah 'PGlmcmFtZS...' menjadi link https://... yang valid.
    """
    if not raw_url: return ""
    if raw_url.startswith("http"): return raw_url
    
    try:
        decoded_bytes = base64.b64decode(raw_url)
        decoded_str = decoded_bytes.decode('utf-8')
        
        # Cari src="..." di dalam string hasil decode (biasanya iframe)
        match = re.search(r'src="([^"]+)"', decoded_str)
        if match:
            return match.group(1)
        return decoded_str
    except:
        return raw_url # Kembalikan apa adanya jika gagal

def parse_card(element, is_schedule=False):
    """
    Parser Kartu Anime untuk Home/List/Schedule.
    """
    try:
        # Title kadang di .tt atau .entry-title
        title_el = element.select_one("div.tt") or element.select_one(".entry-title")
        link_el = element.select_one("a")
        img_el = element.select_one("img")
        
        if not title_el or not link_el: return None
        
        url = link_el["href"]
        slug = extract_slug(url)
        poster = img_el["src"] if img_el else ""
        
        # Scrape Data (Dengan Default Value agar tidak null)
        status_el = element.select_one("div.status") or element.select_one(".stat")
        status = status_el.text.strip() if status_el else "Ongoing"
        
        type_el = element.select_one("div.typez")
        type_show = type_el.text.strip() if type_el else "Donghua"
        
        ep_el = element.select_one("div.epx") or element.select_one(".ep")
        episode = ep_el.text.strip() if ep_el else "??"

        data = {
            "title": title_el.text.strip(),
            "slug": slug,
            "poster": poster,
            "status": status,
            "type": type_show,
            "sub": "Sub",
            "href": f"/donghua/detail/{slug}",
            "anichinUrl": url
        }

        if is_schedule:
            time_el = element.select_one("div.time")
            data["release_time"] = time_el.text.strip() if time_el else "at ??:??"
            data["episode"] = episode
        else:
            data["current_episode"] = episode

        return data
    except: return None

# --- ENDPOINTS LIST ---

@app.get("/")
def home():
    # Anichin Moe biasanya pakai /anime/ untuk list update
    soup = get_soup(f"{BASE_URL}/anime/", params={"order": "update"})
    data = []
    if soup:
        for item in soup.select("div.listupd article.bs"):
            c = parse_card(item)
            if c: data.append(c)
    return {"status": "success", "creator": CREATOR, "latest_donghua": data}

@app.get("/api/popular")
def popular():
    soup = get_soup(f"{BASE_URL}/anime/", params={"order": "popular"})
    data = []
    if soup:
        for item in soup.select("div.listupd article.bs"):
            c = parse_card(item)
            if c: data.append(c)
    return {"status": "success", "creator": CREATOR, "popular_donghua": data}

@app.get("/api/ongoing")
def ongoing():
    soup = get_soup(f"{BASE_URL}/anime/", params={"status": "ongoing"})
    data = []
    if soup:
        for item in soup.select("div.listupd article.bs"):
            c = parse_card(item)
            if c: data.append(c)
    return {"status": "success", "creator": CREATOR, "ongoing_donghua": data}

@app.get("/api/completed")
def completed():
    soup = get_soup(f"{BASE_URL}/anime/", params={"status": "completed"})
    data = []
    if soup:
        for item in soup.select("div.listupd article.bs"):
            c = parse_card(item)
            if c: data.append(c)
    return {"status": "success", "creator": CREATOR, "completed_donghua": data}

@app.get("/api/schedule")
def schedule():
    soup = get_soup(f"{BASE_URL}/schedule/")
    schedule_data = []
    if soup:
        for box in soup.select("div.bixbox"):
            day_el = box.select_one("div.releases h3")
            if not day_el: continue
            
            day_name = day_el.text.strip()
            donghua_list = []
            for item in box.select("div.listupd div.bs"):
                c = parse_card(item, is_schedule=True)
                if c: donghua_list.append(c)
            
            if donghua_list:
                schedule_data.append({"day": day_name, "donghua_list": donghua_list})
    return {"status": "success", "creator": CREATOR, "schedule": schedule_data}

@app.get("/api/search")
def search(s: str = Query(..., alias="s")):
    soup = get_soup(BASE_URL, params={'s': s})
    data = []
    if soup:
        for item in soup.select("div.listupd article.bs"):
            c = parse_card(item)
            if c: data.append(c)
    return {"creator": CREATOR, "data": data}

@app.get("/api/genres")
def genres():
    # Genre biasanya ada di sidebar halaman list
    soup = get_soup(f"{BASE_URL}/anime/")
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

# --- DETAIL (STREAMING + DOWNLOAD + INFO) ---
@app.get("/api/detail")
def get_detail(url: str):
    soup = get_soup(url)
    if not soup: raise HTTPException(status_code=404, detail="Page not found")

    # Deteksi Halaman Episode vs Info
    # Jika ada player atau download box, berarti halaman Episode
    is_episode_page = bool(
        soup.select_one("#playeroptionsul") or 
        soup.select_one(".video-content") or 
        soup.select_one("select.mirror") or 
        soup.select_one(".mctnx")
    )

    if is_episode_page:
        # === HALAMAN NONTON ===
        title = soup.select_one("h1.entry-title").text.strip()
        
        # 1. STREAMING (Dengan Decoder)
        servers = []
        # List Server Modern (UL/LI)
        for li in soup.select("ul#playeroptionsul li"):
            name = li.select_one(".title").text.strip()
            raw_link = li.get("data-src") or li.get("data-url")
            # Decode link Base64
            clean_link = decode_url(raw_link)
            
            if clean_link:
                servers.append({"name": name, "url": clean_link})
        
        # Fallback Iframe Default (Jika tidak ada di list)
        if not servers:
            iframe = soup.select_one(".video-content iframe")
            if iframe: 
                servers.append({"name": "Default", "url": iframe["src"]})
        
        main_url = servers[0] if servers else {"name": "Default", "url": ""}

        # 2. DOWNLOADS
        downloads = {}
        # Cari di .mctnx, .soraddl, .soraurl
        dl_containers = soup.select("div.mctnx div.soraddl") + soup.select("div.soraurl") + soup.select("div.dl-box")
        
        for box in dl_containers:
            # Ambil Resolusi (360p, 480p)
            res_el = box.select_one("div.res") or box.select_one("h3") or box.select_one("strong")
            if not res_el: continue
            
            res_text = res_el.text.strip()
            # Regex ambil angka resolusi
            res_match = re.search(r'(\d+)', res_text)
            
            if res_match:
                key = f"download_url_{res_match.group(1)}p"
            else:
                key = "download_url_unknown"

            links_map = {}
            for a in box.select("a"):
                provider = a.text.strip()
                if provider:
                    links_map[provider] = a["href"]
            
            if links_map:
                downloads[key] = links_map

        # 3. NAVIGASI
        nav = {}
        nav_prev = soup.select_one("div.nvs .nav-previous a") or soup.select_one("a[rel='prev']")
        nav_next = soup.select_one("div.nvs .nav-next a") or soup.select_one("a[rel='next']")
        nav_all = soup.select_one("div.nvs .nvsc a") or soup.select_one(".nvs a[href*='/anime/']")

        if nav_prev:
            nav["previous_episode"] = {
                "episode": "Previous Episode",
                "slug": extract_slug(nav_prev["href"]),
                "href": f"/donghua/episode/{extract_slug(nav_prev['href'])}",
                "anichinUrl": nav_prev["href"]
            }
        if nav_next:
            nav["next_episode"] = {
                "episode": "Next Episode",
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

        # 4. METADATA
        # Bersihkan "Episode ..." dari judul
        series_title = re.split(r' Episode \d+', title, flags=re.IGNORECASE)[0].strip()
        series_slug = extract_slug(url).split("-episode-")[0]
        thumb = soup.select_one("div.thumb img")
        
        donghua_details = {
            "title": series_title,
            "slug": series_slug,
            "poster": thumb["src"] if thumb else "",
            "type": "Donghua",
            "released": "Unknown",
            "uploader": "Admin",
            "href": f"/donghua/detail/{series_slug}",
            "anichinUrl": f"{BASE_URL}/{series_slug}/" # Anichin moe kadang url infonya di root
        }

        # 5. EPISODES LIST (Sidebar)
        episodes_list = []
        # Cari di Sidebar (.bixbox.lpl)
        for a in soup.select("div.bixbox.lpl li a"):
            ep_txt = a.select_one(".lpl_title").text.strip() if a.select_one(".lpl_title") else a.text.strip()
            episodes_list.append({
                "episode": ep_txt,
                "slug": extract_slug(a["href"]),
                "href": f"/donghua/episode/{extract_slug(a['href'])}",
                "anichinUrl": a["href"]
            })

        return {
            "status": "success",
            "creator": CREATOR,
            "episode": title,
            "streaming": {
                "main_url": main_url,
                "servers": servers
            },
            "download_url": downloads,
            "donghua_details": donghua_details,
            "navigation": nav,
            "episodes_list": episodes_list
        }

    else:
        # === HALAMAN INFO SERIES ===
        title = soup.select_one("h1.entry-title").text.strip()
        thumb = soup.select_one("div.thumb img")
        
        def get_info(key):
            for s in soup.select("div.spe span"):
                if key.lower() in s.text.lower():
                    return s.text.split(":", 1)[-1].strip()
            return "-"

        genres = []
        for a in soup.select("div.genxed a"):
            genres.append({
                "name": a.text.strip(),
                "slug": extract_slug(a['href']),
                "anichinUrl": a['href']
            })

        episodes_list = []
        # Cari list episode di halaman info (biasanya #episode_list)
        for a in soup.select("ul#episode_list li a"):
            ep_num = a.select_one(".epl-num")
            ep_title = a.select_one(".epl-title")
            
            raw_title = f"{ep_num.text.strip() if ep_num else ''} {ep_title.text.strip() if ep_title else ''}".strip()
            if not raw_title: raw_title = a.text.strip()
            
            episodes_list.append({
                "episode": raw_title,
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
            "episodes_list": episodes_list
        }
