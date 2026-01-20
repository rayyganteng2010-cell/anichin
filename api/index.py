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

# Header disesuaikan agar tidak diblokir Cloudflare/Firewall sederhana
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://anichin.moe/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

BASE_URL = "https://anichin.moe"

# --- HELPER ---
def get_soup(url, params=None):
    try:
        req = requests.get(url, headers=HEADERS, params=params, timeout=15)
        req.raise_for_status()
        return BeautifulSoup(req.text, "html.parser")
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return None

# --- ENDPOINTS ---

@app.get("/")
def home():
    return {"message": "Anichin Scraper API Pro V3 is Running"}

# 1. SEARCH
@app.get("/api/search")
def search_anime(s: str = Query(..., alias="s")):
    soup = get_soup(BASE_URL, params={'s': s})
    if not soup: raise HTTPException(status_code=500, detail="Server Error")

    results = []
    # Mencari container hasil
    articles = soup.select("div.listupd article.bs")
    
    for item in articles:
        try:
            title = item.select_one("div.tt").text.strip()
            thumb = item.select_one("img")["src"]
            link = item.select_one("a")["href"]
            type_show = item.select_one("div.typez").text.strip() if item.select_one("div.typez") else "Series"
            status = item.select_one("div.status").text.strip() if item.select_one("div.status") else "?"
            
            results.append({
                "title": title,
                "thumbnail": thumb,
                "type": type_show,
                "status": status,
                "url": link
            })
        except: continue

    return {"status": "success", "data": results}

# 2. SCHEDULE
@app.get("/api/schedule")
def get_schedule():
    soup = get_soup(f"{BASE_URL}/schedule/")
    if not soup: raise HTTPException(status_code=500)
    
    data = []
    for box in soup.select("div.bixbox"):
        day_el = box.select_one("div.releases h3")
        if not day_el: continue
        
        day_name = day_el.text.strip()
        anime_list = []
        
        for anime in box.select("div.listupd div.bs"):
            try:
                title = anime.select_one("div.tt").text.strip()
                link = anime.select_one("a")["href"]
                thumb = anime.select_one("img")["src"]
                ep = anime.select_one("div.epx").text.strip() if anime.select_one("div.epx") else ""
                time_rel = anime.select_one("div.time").text.strip() if anime.select_one("div.time") else ""
                
                anime_list.append({
                    "title": title, 
                    "thumbnail": thumb, 
                    "episode": ep, 
                    "time": time_rel, 
                    "url": link
                })
            except: continue
            
        if anime_list:
            data.append({"day": day_name, "list": anime_list})
            
    return {"status": "success", "data": data}

# 3. RECOMMENDED
@app.get("/api/recommended")
def get_recommended():
    soup = get_soup(f"{BASE_URL}/anime/")
    if not soup: raise HTTPException(status_code=500)

    results = []
    for item in soup.select("div.listupd article.bs"):
        try:
            title = item.select_one("div.tt").text.strip()
            thumb = item.select_one("img")["src"]
            link = item.select_one("a")["href"]
            type_show = item.select_one("div.typez").text.strip() if item.select_one("div.typez") else ""
            status = item.select_one("div.status").text.strip() if item.select_one("div.status") else ""

            results.append({
                "title": title,
                "thumbnail": thumb,
                "type": type_show,
                "status": status,
                "url": link
            })
        except: continue

    return {"status": "success", "data": results}

# 4. DETAIL (FULL FIX)
@app.get("/api/detail")
def get_detail(url: str):
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")
        
    soup = get_soup(url)
    if not soup: raise HTTPException(status_code=404, detail="Page Not Found")

    # --- A. DATA UTAMA ---
    title = soup.select_one("h1.entry-title").text.strip() if soup.select_one("h1.entry-title") else "Unknown"
    
    # Synopsis (Cari beberapa kemungkinan selector)
    synopsis = "No synopsis"
    syn_el = soup.select_one("div.entry-content[itemprop='description']") or soup.select_one("div.entry-content")
    if syn_el:
        synopsis = syn_el.get_text(separator="\n", strip=True)

    # Thumbnail
    thumb_el = soup.select_one("div.thumb img")
    thumbnail = thumb_el["src"] if thumb_el else ""

    # --- B. INFO DETAIL (Genre, Status, dll) ---
    info_data = {
        "status": "Unknown",
        "studio": "Unknown",
        "released": "Unknown",
        "duration": "Unknown",
        "genres": []
    }

    # Scrape Info Box (.infox)
    try:
        # Genre
        genres = [a.text.strip() for a in soup.select("div.genxed a")]
        info_data["genres"] = genres
        
        # Info baris per baris (Status, Studio, dll)
        # Biasanya struktur: <div class="spe"><span><b>Status:</b> On Going</span></div>
        for span in soup.select("div.spe span"):
            text = span.text.strip()
            if "Status:" in text: info_data["status"] = text.replace("Status:", "").strip()
            if "Studio:" in text: info_data["studio"] = text.replace("Studio:", "").strip()
            if "Released:" in text: info_data["released"] = text.replace("Released:", "").strip()
            if "Duration:" in text: info_data["duration"] = text.replace("Duration:", "").strip()
    except:
        pass

    # --- C. STREAM / VIDEO SOURCES (LOGIC UTAMA) ---
    streams = []
    
    # Logika 1: Ambil dari list Server (Biasanya di ul#playeroptionsul)
    server_list = soup.select("ul#playeroptionsul li")
    for li in server_list:
        try:
            name = li.select_one("span.title").text.strip()
            # Link video biasanya di atribut 'data-src', 'data-url', atau 'data-nume'
            # Kita cek semuanya
            video_url = li.get("data-src") or li.get("data-url") or li.get("data-nume")
            
            if video_url:
                streams.append({"server": name, "url": video_url})
        except: continue

    # Logika 2: Jika list server kosong, cari iframe langsung (Default player)
    if not streams:
        iframe = soup.select_one("div.video-content iframe") or soup.select_one("div#embed_holder iframe")
        if iframe:
            src = iframe.get("src")
            if src:
                streams.append({"server": "Default Server", "url": src})

    # --- D. EPISODE LIST ---
    episodes = []
    # Biasanya ada di dalam div.lpl atau ul#episodes
    ep_links = soup.select("div.bixbox.lpl li a")
    for link in ep_links:
        try:
            ep_title = link.select_one("div.lpl_title").text.strip() if link.select_one("div.lpl_title") else link.text.strip()
            ep_url = link["href"]
            episodes.append({"title": ep_title, "url": ep_url})
        except: continue

    return {
        "status": "success",
        "data": {
            "title": title,
            "thumbnail": thumbnail,
            "synopsis": synopsis,
            "info": info_data,
            "streams": streams,
            "episodes": episodes
        }
    }
