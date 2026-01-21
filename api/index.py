from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import re
import base64

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

# --- HELPER FUNCTIONS ---

def get_soup(url, params=None):
    try:
        req = requests.get(url, headers=HEADERS, params=params, timeout=20)
        req.raise_for_status()
        return BeautifulSoup(req.text, "html.parser")
    except: return None

def extract_slug(url):
    try: return url.strip("/").split("/")[-1]
    except: return ""

def decode_url(raw_url):
    """
    Fungsi krusial untuk memperbaiki link 'PGlmcmFt...' menjadi link https://...
    """
    if not raw_url: return ""
    
    # Cek apakah ini URL biasa
    if raw_url.startswith("http"): return raw_url
    
    try:
        # Coba Decode Base64
        decoded_bytes = base64.b64decode(raw_url)
        decoded_str = decoded_bytes.decode('utf-8')
        
        # Hasil decode biasanya: <iframe src="https://anichin.stream/..." ...>
        # Kita perlu ambil src-nya saja menggunakan Regex
        match = re.search(r'src="([^"]+)"', decoded_str)
        if match:
            return match.group(1)
        return decoded_str # Return decoded string jika regex gagal (fallback)
    except:
        return raw_url # Kembalikan asli jika gagal decode

def parse_card(element, is_schedule=False):
    # (Parser standar untuk List/Home - Tidak ada perubahan besar disini)
    try:
        title_el = element.select_one("div.tt") or element.select_one(".entry-title")
        link_el = element.select_one("a")
        img_el = element.select_one("img")
        if not title_el or not link_el: return None
        
        url = link_el["href"]
        slug = extract_slug(url)
        
        status = (element.select_one("div.status") or element.select_one(".stat") or element).text.strip()
        if not status: status = "Ongoing"
        
        episode = (element.select_one("div.epx") or element.select_one(".ep") or element).text.strip()
        if not episode: episode = "??"

        data = {
            "title": title_el.text.strip(),
            "slug": slug,
            "poster": img_el["src"] if img_el else "",
            "status": status,
            "type": "Donghua",
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
    soup = get_soup(f"{BASE_URL}/seri/", params={"order": "update"})
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)] if soup else []
    return {"status": "success", "creator": CREATOR, "latest_donghua": data}

@app.get("/api/ongoing")
def ongoing():
    soup = get_soup(f"{BASE_URL}/seri/", params={"status": "ongoing"})
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)] if soup else []
    return {"status": "success", "creator": CREATOR, "ongoing_donghua": data}

@app.get("/api/completed")
def completed():
    soup = get_soup(f"{BASE_URL}/seri/", params={"status": "completed"})
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)] if soup else []
    return {"status": "success", "creator": CREATOR, "completed_donghua": data}

@app.get("/api/popular")
def popular():
    soup = get_soup(f"{BASE_URL}/seri/", params={"order": "popular"})
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)] if soup else []
    return {"status": "success", "creator": CREATOR, "popular_donghua": data}

@app.get("/api/rating")
def rating():
    soup = get_soup(f"{BASE_URL}/seri/", params={"order": "rating"})
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)] if soup else []
    return {"status": "success", "creator": CREATOR, "rating_donghua": data}

@app.get("/api/schedule")
def schedule():
    soup = get_soup(f"{BASE_URL}/schedule/")
    data = []
    if soup:
        for box in soup.select("div.bixbox"):
            day = box.select_one("div.releases h3")
            if not day: continue
            l = [parse_card(i, True) for i in box.select("div.listupd div.bs") if parse_card(i, True)]
            if l: data.append({"day": day.text.strip(), "donghua_list": l})
    return {"status": "success", "creator": CREATOR, "schedule": data}

@app.get("/api/search")
def search(s: str = Query(..., alias="s")):
    soup = get_soup(BASE_URL, params={'s': s})
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)] if soup else []
    return {"creator": CREATOR, "data": data}

@app.get("/api/genres")
def genres():
    soup = get_soup(f"{BASE_URL}/seri/")
    res = []
    seen = set()
    if soup:
        for a in soup.select("a[href*='/genres/']"):
            if a.text and a['href'] not in seen:
                seen.add(a['href'])
                res.append({"name": a.text.strip(), "slug": extract_slug(a['href']), "href": f"/donghua/genres/{extract_slug(a['href'])}", "anichinUrl": a['href']})
    return {"creator": CREATOR, "data": sorted(res, key=lambda x: x['name'])}

@app.get("/api/genres/{slug}")
def genre_detail(slug: str):
    soup = get_soup(f"{BASE_URL}/genres/{slug}/")
    data = [parse_card(i) for i in soup.select("div.listupd article.bs") if parse_card(i)] if soup else []
    return {"creator": CREATOR, "data": data}

# --- DETAIL (FIXED BASE64 & DOWNLOADS) ---
@app.get("/api/detail")
def get_detail(url: str):
    soup = get_soup(url)
    if not soup: raise HTTPException(404, detail="Page not found")

    is_episode = bool(soup.select_one("#playeroptionsul") or soup.select_one(".video-content") or soup.select_one("select.mirror") or soup.select_one("#pembed"))

    if is_episode:
        title = soup.select_one("h1.entry-title").text.strip()
        
        # 1. STREAMING (FIXED BASE64)
        servers = []
        
        # Scrape List Server dari UL (Mirror)
        for li in soup.select("ul#playeroptionsul li"):
            name = li.select_one(".title").text.strip()
            # Link mentah (mungkin Base64)
            raw_link = li.get("data-src") or li.get("data-url")
            # DECODE DISINI
            clean_link = decode_url(raw_link)
            
            if clean_link:
                servers.append({"name": name, "url": clean_link})
        
        # Fallback Iframe Default
        if not servers:
            iframe = soup.select_one(".video-content iframe")
            if iframe: 
                servers.append({"name": "Default", "url": iframe["src"]})
        
        # Main URL selalu server pertama
        main_url = servers[0] if servers else {"name": "Default", "url": ""}

        # 2. DOWNLOADS (AGGRESSIVE SEARCH)
        downloads = {}
        # Cari semua div yang mungkin jadi container download
        dl_containers = soup.select("div.mctnx div.soraddl") + soup.select("div.soraurl") + soup.select("div.dl-box")
        
        for box in dl_containers:
            # Cari teks resolusi (360p, 480p)
            res_el = box.select_one("div.res") or box.select_one("h3") or box.select_one("strong")
            if not res_el: continue
            
            res_text = res_el.text.strip()
            res_num = re.search(r'\d+', res_text) # Ambil angka saja
            
            if res_num:
                key = f"download_url_{res_num.group(0)}p"
            else:
                continue

            links_map = {}
            for a in box.select("a"):
                provider = a.text.strip()
                if provider:
                    links_map[provider] = a["href"]
            
            if links_map:
                downloads[key] = links_map

        # 3. NAVIGATION
        nav = {}
        nav_prev = soup.select_one("div.nvs .nav-previous a") or soup.select_one("a[rel='prev']")
        nav_next = soup.select_one("div.nvs .nav-next a") or soup.select_one("a[rel='next']")
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

        # 4. METADATA
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
            "anichinUrl": f"{BASE_URL}/seri/{series_slug}/"
        }

        # 5. EPISODES LIST (FIXED)
        episodes_list = []
        # Cari di Sidebar (.bixbox.lpl) DAN Main List (#episode_list)
        # Gunakan set untuk menghindari duplikat
        seen_urls = set()
        
        # Prioritas 1: Sidebar (biasanya ada di halaman nonton)
        sidebar_links = soup.select("div.bixbox.lpl li a")
        # Prioritas 2: Jika sidebar kosong, coba cari element hidden atau script
        # Untuk themesia, kadang list episode ada di bawah player dengan class .eplister
        main_links = soup.select("div.eplister li a") + soup.select("#episode_list li a")
        
        all_links = sidebar_links + main_links
        
        for a in all_links:
            href = a.get("href")
            if not href or href in seen_urls: continue
            seen_urls.add(href)
            
            # Extract Judul Bersih
            ep_num = a.select_one(".epl-num")
            ep_title = a.select_one(".epl-title") or a.select_one(".lpl_title")
            
            if ep_num and ep_title:
                raw_title = f"{ep_num.text.strip()} - {ep_title.text.strip()}"
            elif ep_title:
                raw_title = ep_title.text.strip()
            else:
                raw_title = a.text.strip()
            
            # Bersihkan judul dari nama series
            clean_title = raw_title.replace(series_title, "").replace("Subtitle Indonesia", "").strip()
            if not clean_title: clean_title = raw_title # Fallback

            episodes_list.append({
                "episode": clean_title,
                "slug": extract_slug(href),
                "href": f"/donghua/episode/{extract_slug(href)}",
                "anichinUrl": href
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
        # === INFO SERIES VIEW ===
        title = soup.select_one("h1.entry-title").text.strip()
        thumb = soup.select_one("div.thumb img")
        
        def get_val(key):
            for s in soup.select("div.spe span"):
                if key.lower() in s.text.lower():
                    return s.text.split(":", 1)[-1].strip()
            return "-"

        genres = [{"name": a.text.strip(), "slug": extract_slug(a['href']), "anichinUrl": a['href']} for a in soup.select("div.genxed a")]
        
        eps = []
        for a in soup.select("ul#episode_list li a"):
            ep_num = a.select_one(".epl-num")
            ep_text = a.select_one(".epl-title").text.strip() if a.select_one(".epl-title") else a.text.strip()
            final = f"{ep_num.text.strip()} - {ep_text}" if ep_num else ep_text
            
            eps.append({
                "episode": final,
                "slug": extract_slug(a['href']),
                "anichinUrl": a['href']
            })

        syn = soup.select_one("div.entry-content[itemprop='description']")
        
        return {
            "status": get_val("Status"),
            "creator": CREATOR,
            "title": title,
            "poster": thumb["src"] if thumb else "",
            "studio": get_val("Studio"),
            "released": get_val("Released"),
            "duration": get_val("Duration"),
            "type": get_val("Type"),
            "genres": genres,
            "synopsis": syn.get_text(separator="\n").strip() if syn else "",
            "episodes_list": eps
        }
