from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup

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
    "Referer": "https://anichin.moe/"
}

BASE_URL = "https://anichin.moe"

# --- HELPER ---
def get_soup(url, params=None):
    try:
        req = requests.get(url, headers=HEADERS, params=params, timeout=15)
        req.raise_for_status()
        return BeautifulSoup(req.text, "html.parser")
    except Exception as e:
        print(f"Error accessing {url}: {e}")
        return None

# --- ENDPOINTS ---

@app.get("/")
def home():
    return {"message": "Anichin Scraper V4 - Full URL & Download Support"}

# 1. SEARCH (Full URL Fix)
@app.get("/api/search")
def search_anime(s: str = Query(..., alias="s")):
    soup = get_soup(BASE_URL, params={'s': s})
    if not soup: raise HTTPException(status_code=500)

    results = []
    # Selector umum Anichin
    articles = soup.select("div.listupd article.bs")
    
    for item in articles:
        try:
            # Title Guard: Cek beberapa kemungkinan tempat title
            title_el = item.select_one("div.tt") or item.select_one("h2")
            if not title_el: continue
            title = title_el.text.strip()

            thumb_el = item.select_one("img")
            thumb = thumb_el.get("src") if thumb_el else ""
            
            link_el = item.select_one("a")
            link = link_el.get("href") if link_el else ""

            results.append({
                "title": title,
                "thumbnail": thumb,
                "url": link  # Ini sudah Full URL dari webnya
            })
        except: continue

    return {"status": "success", "data": results}

# 2. SCHEDULE (Full URL Fix)
@app.get("/api/schedule")
def get_schedule():
    soup = get_soup(f"{BASE_URL}/schedule/")
    if not soup: raise HTTPException(status_code=500)
    
    data = []
    for box in soup.select("div.bixbox"):
        try:
            day_el = box.select_one("div.releases h3")
            if not day_el: continue
            day_name = day_el.text.strip()
            
            anime_list = []
            for anime in box.select("div.listupd div.bs"):
                title_el = anime.select_one("div.tt")
                link_el = anime.select_one("a")
                thumb_el = anime.select_one("img")
                ep_el = anime.select_one("div.epx")

                if title_el and link_el:
                    anime_list.append({
                        "title": title_el.text.strip(),
                        "thumbnail": thumb_el.get("src") if thumb_el else "",
                        "episode": ep_el.text.strip() if ep_el else "?",
                        "url": link_el.get("href") # Full URL
                    })
            
            if anime_list:
                data.append({"day": day_name, "list": anime_list})
        except: continue
            
    return {"status": "success", "data": data}

# 3. RECOMMENDED
@app.get("/api/recommended")
def get_recommended():
    soup = get_soup(f"{BASE_URL}/anime/")
    if not soup: raise HTTPException(status_code=500)

    results = []
    for item in soup.select("div.listupd article.bs"):
        try:
            title_el = item.select_one("div.tt")
            link_el = item.select_one("a")
            thumb_el = item.select_one("img")
            
            if title_el and link_el:
                results.append({
                    "title": title_el.text.strip(),
                    "thumbnail": thumb_el.get("src") if thumb_el else "",
                    "url": link_el.get("href")
                })
        except: continue

    return {"status": "success", "data": results}

# 4. DETAIL PAGE (Episode/Movie) - UPDATE TERBESAR
@app.get("/api/detail")
def get_detail(url: str):
    # Pastikan URL valid
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL format. Must be full URL.")

    soup = get_soup(url)
    if not soup: raise HTTPException(status_code=404)

    # A. JUDUL (Cari di H1 dengan class berbeda-beda)
    title = "Unknown Title"
    title_el = soup.select_one("h1.entry-title") or soup.select_one("h1.ts-title") or soup.select_one("h1")
    if title_el:
        title = title_el.text.strip()

    # B. STREAMING SERVERS (Video)
    streams = []
    
    # 1. Coba ambil dari Mirror List (Biasanya <select> atau <ul>)
    # Struktur: <ul id="playeroptionsul"> <li data-src="...">...</li> </ul>
    mirrors = soup.select("ul#playeroptionsul li")
    for m in mirrors:
        server_name = m.select_one("span.title").text.strip() if m.select_one("span.title") else "Server"
        # Ambil link dari atribut data
        link = m.get("data-src") or m.get("data-url") or m.get("data-nume")
        if link:
            streams.append({"server": server_name, "url": link})

    # 2. Fallback: Coba ambil Iframe langsung jika list mirror kosong
    if not streams:
        iframe = soup.select_one("div.video-content iframe") or soup.select_one("#embed_holder iframe")
        if iframe:
            src = iframe.get("src")
            if src: streams.append({"server": "Default", "url": src})

    # C. DOWNLOAD LINKS (Tambahan Baru)
    downloads = []
    # Biasanya ada di div.mctnx atau div.soraurl
    dl_boxes = soup.select("div.mctnx div.soraddl") or soup.select("div.soraurl")
    for box in dl_boxes:
        # Resolusi (360p, 480p, 720p)
        res_name = box.select_one("div.res") or box.select_one("h3")
        resolution = res_name.text.strip() if res_name else "Unknown Res"
        
        links = []
        for a in box.select("a"):
            links.append({
                "source": a.text.strip(),
                "link": a.get("href")
            })
        
        if links:
            downloads.append({"resolution": resolution, "links": links})

    # D. EPISODE LIST (Navigasi)
    episodes = []
    # Biasanya di sidebar widget atau bawah player
    ep_links = soup.select("div.bixbox.lpl li a")
    for link in ep_links:
        t_el = link.select_one("div.lpl_title") or link.select_one("span.lpl_title")
        t = t_el.text.strip() if t_el else link.text.strip()
        u = link.get("href")
        if u:
            episodes.append({"title": t, "url": u})

    # E. SINOPSIS
    synopsis = "-"
    syn_el = soup.select_one("div.entry-content[itemprop='description']") or soup.select_one("div.entry-content")
    if syn_el:
        synopsis = syn_el.get_text(separator="\n", strip=True)

    return {
        "status": "success",
        "data": {
            "title": title,
            "synopsis": synopsis,
            "streams": streams,
            "downloads": downloads, # Data download baru
            "episodes": episodes
        }
    }
