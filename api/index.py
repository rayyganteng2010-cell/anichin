from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import urllib.parse

app = FastAPI()

# --- 1. CONFIGURATION ---
# Penting: CORS diaktifkan agar frontend (HTML) bisa akses API ini
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Mengizinkan semua domain akses
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://anichin.moe/"
}

BASE_URL = "https://anichin.moe"

# --- 2. HELPER FUNCTIONS ---
def get_soup(url, params=None):
    try:
        # Timeout 15 detik agar tidak hang jika web lambat
        req = requests.get(url, headers=HEADERS, params=params, timeout=15)
        req.raise_for_status()
        return BeautifulSoup(req.text, "html.parser")
    except requests.exceptions.RequestException as e:
        print(f"Error accessing {url}: {e}")
        return None

# --- 3. ENDPOINTS ---

@app.get("/")
def home():
    return {
        "status": "Alive",
        "message": "Anichin Scraper API V2",
        "endpoints": {
            "search": "/api/search?s=Judul",
            "schedule": "/api/schedule",
            "recommended": "/api/recommended",
            "detail": "/api/detail?url=LinkHalaman"
        }
    }

# --- SEARCH FUNCTION (DIPERBAIKI) ---
@app.get("/api/search")
def search_anime(s: str = Query(..., description="Search keyword")):
    # Kita biarkan requests library menangani encoding ?s=...
    soup = get_soup(BASE_URL, params={'s': s})
    
    if not soup:
        raise HTTPException(status_code=500, detail="Gagal mengambil data dari Anichin")

    results = []
    # Mencari container hasil pencarian
    # Selector .listupd article.bs adalah standar tema web ini
    articles = soup.select("div.listupd article.bs")
    
    for item in articles:
        try:
            # Title
            title_el = item.select_one("div.tt")
            title = title_el.text.strip() if title_el else "No Title"
            
            # Thumbnail
            img_el = item.select_one("img")
            thumb = img_el.get("src") if img_el else ""
            
            # Link
            link_el = item.select_one("a")
            link = link_el.get("href") if link_el else ""
            
            # Type (Donghua/Movie)
            type_el = item.select_one("div.typez")
            tipe = type_el.text.strip() if type_el else "Series"

            # Status
            stat_el = item.select_one("div.status")
            status = stat_el.text.strip() if stat_el else "Unknown"

            results.append({
                "title": title,
                "thumbnail": thumb,
                "type": tipe,
                "status": status,
                "url": link
            })
        except Exception as e:
            continue # Skip jika ada 1 item error

    return {
        "status": "success", 
        "query": s,
        "total": len(results),
        "data": results
    }

# --- SCHEDULE FUNCTION ---
@app.get("/api/schedule")
def get_schedule():
    url = f"{BASE_URL}/schedule/"
    soup = get_soup(url)
    if not soup:
        raise HTTPException(status_code=500, detail="Cannot fetch schedule")
    
    data = []
    # Loop setiap box hari
    for box in soup.select("div.bixbox"):
        day_el = box.select_one("div.releases h3")
        if not day_el: continue # Skip jika bukan box jadwal
        
        day_name = day_el.text.strip()
        anime_list = []
        
        for anime in box.select("div.listupd div.bs"):
            try:
                title = anime.select_one("div.tt").text.strip()
                link = anime.select_one("a")["href"]
                thumb = anime.select_one("img")["src"]
                
                # Episode text
                ep_el = anime.select_one("div.epx") or anime.select_one("span.epx")
                episode = ep_el.text.strip() if ep_el else "?"
                
                # Time release (kadang ada)
                time_el = anime.select_one("div.time")
                time_rel = time_el.text.strip() if time_el else ""

                anime_list.append({
                    "title": title,
                    "thumbnail": thumb,
                    "episode": episode,
                    "time": time_rel,
                    "url": link
                })
            except:
                continue

        if anime_list:
            data.append({"day": day_name, "list": anime_list})
            
    return {"status": "success", "data": data}

# --- RECOMMENDED / HOMEPAGE ---
@app.get("/api/recommended")
def get_recommended():
    # Mengambil dari halaman 'anime' (list) atau homepage
    url = f"{BASE_URL}/anime/"
    soup = get_soup(url)
    
    if not soup: raise HTTPException(status_code=500)

    results = []
    for item in soup.select("div.listupd article.bs"):
        try:
            title = item.select_one("div.tt").text.strip()
            thumb = item.select_one("img")["src"]
            link = item.select_one("a")["href"]
            
            # Mengambil rating jika ada
            rating_el = item.select_one("div.rating")
            rating = rating_el.text.strip() if rating_el else "-"

            results.append({
                "title": title,
                "thumbnail": thumb,
                "rating": rating,
                "url": link
            })
        except:
            continue

    return {"status": "success", "data": results}

# --- DETAIL PAGE & STREAM ---
@app.get("/api/detail")
def get_detail(url: str):
    # Validasi URL sederhana
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")

    soup = get_soup(url)
    if not soup:
        raise HTTPException(status_code=404, detail="Page not found")

    # 1. Info Utama
    title_el = soup.select_one("h1.entry-title")
    title = title_el.text.strip() if title_el else "Unknown"
    
    synopsis_el = soup.select_one("div.entry-content[itemprop='description']")
    # Fallback jika synopsis selector beda
    if not synopsis_el:
        synopsis_el = soup.select_one("div.entry-content")
    synopsis = synopsis_el.text.strip() if synopsis_el else ""

    # 2. Get Video Stream (Iframe)
    streams = []
    
    # Cara 1: Cari elemen iframe di .video-content
    iframe = soup.select_one("div.video-content iframe")
    if iframe:
        src = iframe.get("src") or iframe.get("data-src")
        streams.append({"server": "Main Server", "url": src})
    
    # Cara 2: Cari di dropdown/list server mirror
    # Biasanya ada di <select> atau <ul>
    mirrors = soup.select("ul#playeroptionsul li")
    for m in mirrors:
        name = m.select_one("span.title").text.strip()
        # Ambil data-src, data-nume, atau atribut lain yang menyimpan link
        link = m.get("data-src") or m.get("data-nume")
        if link:
            streams.append({"server": name, "url": link})

    # 3. Get Episode List (Navigasi)
    episodes = []
    # Biasanya ada di div.bixbox.lpl atau ul#episodes
    ep_list_el = soup.select("div.bixbox.lpl li a")
    for ep in ep_list_el:
        ep_title = ep.select_one("div.lpl_title") or ep.select_one("span.lpl_title")
        t = ep_title.text.strip() if ep_title else ep.text.strip()
        l = ep["href"]
        episodes.append({"title": t, "url": l})

    return {
        "status": "success",
        "data": {
            "title": title,
            "synopsis": synopsis,
            "streams": streams,
            "episodes": episodes
        }
    }
