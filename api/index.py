from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import re

app = FastAPI()

# --- KONFIGURASI ---
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
    try:
        return url.strip("/").split("/")[-1]
    except:
        return ""

def parse_card(element, is_schedule=False):
    """
    Parser Kartu Anime untuk Home/List.
    Memastikan data 'Status', 'Type', 'Sub' tidak pernah kosong.
    """
    try:
        title_el = element.select_one("div.tt") or element.select_one(".entry-title")
        link_el = element.select_one("a")
        img_el = element.select_one("img")
        
        if not title_el or not link_el: return None
        
        url = link_el["href"]
        slug = extract_slug(url)
        poster = img_el["src"] if img_el else ""
        
        # Data Wajib (Default Value jika scrape gagal)
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
            # Endpoint latest biasanya perlu current_episode
            data["current_episode"] = episode

        return data
    except: return None

# --- ENDPOINTS LIST ---

@app.get("/")
def home():
    soup = get_soup(f"{BASE_URL}/seri/", params={"order": "update"})
    data = []
    if soup:
        for item in soup.select("div.listupd article.bs"):
            c = parse_card(item)
            if c: data.append(c)
    return {"status": "success", "creator": CREATOR, "latest_donghua": data}

@app.get("/api/popular")
def popular():
    soup = get_soup(f"{BASE_URL}/seri/", params={"order": "popular"})
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]
    return {"status": "success", "creator": CREATOR, "popular_donghua": data}

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
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]
    return {"creator": CREATOR, "data": data}

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
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)]
    return {"creator": CREATOR, "data": data}

# --- DETAIL ENDPOINT (SUPER COMPLETE) ---
@app.get("/api/detail")
def get_detail(url: str):
    soup = get_soup(url)
    if not soup: raise HTTPException(status_code=404, detail="Page not found")

    # Cek apakah ini halaman nonton (Episode)
    # Cirinya: Ada list server mirror (playeroptionsul) atau iframe video
    is_episode_page = bool(soup.select_one("#playeroptionsul") or soup.select_one(".video-content") or soup.select_one("select.mirror"))

    if is_episode_page:
        # ==========================================
        # LOGIKA 1: HALAMAN NONTON (EPISODE DETAIL)
        # ==========================================
        title = soup.select_one("h1.entry-title").text.strip()
        
        # 1. Streaming Servers
        servers = []
        # Coba ambil dari List UL (Tema Baru)
        for li in soup.select("ul#playeroptionsul li"):
            name = li.select_one(".title").text.strip()
            link = li.get("data-src") or li.get("data-url")
            if link: servers.append({"name": name, "url": link})
        
        # Jika kosong, coba Iframe Default
        if not servers:
            iframe = soup.select_one(".video-content iframe")
            if iframe: servers.append({"name": "Default", "url": iframe["src"]})
            
        main_url = servers[0] if servers else {"name": "None", "url": ""}

        # 2. Download Links (Nested per Resolusi)
        downloads = {}
        # Cari semua container download (.mctnx, .soraddl, .soraurl)
        dl_boxes = soup.select("div.mctnx div.soraddl") + soup.select("div.soraurl")
        
        for box in dl_boxes:
            # Ambil Judul Resolusi (misal: "360p (MP4)")
            res_el = box.select_one("div.res") or box.select_one("h3")
            if not res_el: continue
            
            res_raw = res_el.text.strip()
            # Ambil angka saja untuk key JSON (360, 480, 720)
            res_num = re.search(r'\d+', res_raw)
            
            if res_num:
                key = f"download_url_{res_num.group(0)}p" # Hasil: download_url_360p
            else:
                key = "download_url_unknown"

            # Ambil link-link di dalamnya (Gdrive, Zippyshare, dll)
            links_map = {}
            for a in box.select("a"):
                provider = a.text.strip()
                links_map[provider] = a["href"]
            
            if links_map:
                downloads[key] = links_map

        # 3. Navigation (Prev/Next/All)
        nav = {}
        nav_prev = soup.select_one("div.nvs .nav-previous a")
        nav_next = soup.select_one("div.nvs .nav-next a")
        nav_all = soup.select_one("div.nvs .nvsc a")

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

        # 4. Donghua Metadata
        # Kita ambil series title dari judul episode (Hapus kata "Episode ...")
        series_title = re.split(r' Episode \d+', title, flags=re.IGNORECASE)[0].strip()
        series_slug = extract_slug(url).split("-episode-")[0]
        thumb = soup.select_one("div.thumb img")
        
        # Scrape status dan type dari breadcrumb atau elemen info (jika ada)
        # Default fallback
        type_txt = "Donghua"
        status_txt = "Ongoing"
        
        donghua_details = {
            "title": series_title,
            "slug": series_slug,
            "poster": thumb["src"] if thumb else "",
            "type": type_txt,
            "released": "Unknown",
            "uploader": "Admin", # Default
            "href": f"/donghua/detail/{series_slug}",
            "anichinUrl": f"{BASE_URL}/seri/{series_slug}/"
        }

        # 5. List Episodes (Wajib ada di detail episode juga)
        episodes_list = []
        # Biasanya di sidebar saat nonton (.bixbox.lpl)
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
        # ========================================
        # LOGIKA 2: HALAMAN INFO SERIES
        # ========================================
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

        # List Episode (Biasanya di ul#episode_list atau .eplister)
        episodes_list = []
        # Gabungkan selector untuk keamanan
        for li in soup.select("ul#episode_list li") + soup.select("div.eplister li"):
            a = li.select_one("a")
            if a:
                ep_num = li.select_one(".epl-num")
                ep_title = li.select_one(".epl-title")
                
                # Format judul episode
                final_title = a.text.strip()
                if ep_num and ep_title:
                    final_title = f"{ep_num.text.strip()} - {ep_title.text.strip()}"
                
                episodes_list.append({
                    "episode": final_title,
                    "slug": extract_slug(a["href"]),
                    "href": f"/donghua/episode/{extract_slug(a['href'])}",
                    "anichinUrl": a["href"]
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
