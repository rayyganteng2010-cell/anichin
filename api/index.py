from fastapi import FastAPI, HTTPException, Query
import requests
from bs4 import BeautifulSoup

app = FastAPI()

# Konfigurasi Header agar dikira manusia (Bypass proteksi ringan)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://google.com/"
}

BASE_URL = "https://anichin.moe"

def get_soup(url):
    try:
        req = requests.get(url, headers=HEADERS, timeout=10)
        req.raise_for_status()
        return BeautifulSoup(req.text, "html.parser")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")

@app.get("/")
def home():
    return {
        "message": "Anichin Scraper API is Running",
        "endpoints": [
            "/api/schedule",
            "/api/recommended",
            "/api/search?query=nama_donghua",
            "/api/detail?url=link_donghua"
        ]
    }

# 1. Schedule Scraper
@app.get("/api/schedule")
def get_schedule():
    url = f"{BASE_URL}/schedule/"
    soup = get_soup(url)
    
    data = []
    # Sesuaikan selector ini dengan inspect element di browser jika hasil kosong
    # Biasanya schedule ada di dalam tab content
    for item in soup.select("div.bixbox"): 
        day = item.select_one("div.releases h3")
        day_name = day.text.strip() if day else "Unknown Day"
        
        anime_list = []
        for anime in item.select("div.listupd div.bs"):
            title = anime.select_one("div.tt").text.strip() if anime.select_one("div.tt") else "-"
            thumb = anime.select_one("img")["src"] if anime.select_one("img") else ""
            ep_element = anime.select_one("div.epx") or anime.select_one("span.epx")
            episode = ep_element.text.strip() if ep_element else "?"
            link = anime.select_one("a")["href"] if anime.select_one("a") else ""

            anime_list.append({
                "title": title,
                "thumbnail": thumb,
                "episode": episode,
                "url": link
            })
        
        if anime_list:
            data.append({"day": day_name, "list": anime_list})
            
    return {"status": "success", "data": data}

# 2. Recommended Scraper (Halaman Anime List)
@app.get("/api/recommended")
def get_recommended():
    url = f"{BASE_URL}/anime/"
    soup = get_soup(url)
    
    results = []
    # Mengambil list dari halaman anime
    for item in soup.select("div.listupd article.bs"):
        title = item.select_one("div.tt").text.strip() if item.select_one("div.tt") else "No Title"
        thumb = item.select_one("img")["src"] if item.select_one("img") else ""
        type_show = item.select_one("div.typez").text.strip() if item.select_one("div.typez") else ""
        status = item.select_one("div.status").text.strip() if item.select_one("div.status") else ""
        link = item.select_one("a")["href"] if item.select_one("a") else ""
        
        results.append({
            "title": title,
            "thumbnail": thumb,
            "type": type_show,
            "status": status,
            "url": link
        })

    return {"status": "success", "data": results}

# 3. Search Scraper
@app.get("/api/search")
def search_anime(query: str = Query(..., alias="s")):
    # URL contoh: https://anichin.moe/?s=Renegade
    url = f"{BASE_URL}/?s={query}"
    soup = get_soup(url)
    
    results = []
    for item in soup.select("div.listupd article.bs"):
        title = item.select_one("div.tt").text.strip() if item.select_one("div.tt") else "No Title"
        thumb = item.select_one("img")["src"] if item.select_one("img") else ""
        link = item.select_one("a")["href"] if item.select_one("a") else ""
        
        # Kadang rating atau info lain ada di overlay
        results.append({
            "title": title,
            "thumbnail": thumb,
            "url": link
        })
        
    return {"status": "success", "search_query": query, "data": results}

# 4. Detail Page (Video & Stream Links)
@app.get("/api/detail")
def get_detail(url: str):
    # Pastikan URL valid dari anichin.moe
    if "anichin.moe" not in url:
        raise HTTPException(status_code=400, detail="Invalid URL domain")
        
    soup = get_soup(url)
    
    # Ambil Judul
    title = soup.select_one("h1.entry-title").text.strip() if soup.select_one("h1.entry-title") else "Unknown Title"
    
    # Ambil Sinopsis
    synopsis = soup.select_one("div.entry-content p")
    synopsis_text = synopsis.text.strip() if synopsis else "No synopsis available."
    
    # Ambil Video Streams (Iframe)
    # Biasanya ada di dalam <select> mirror atau list server
    streams = []
    
    # Coba cari iframe langsung (Server default)
    default_iframe = soup.select_one("div.video-content iframe")
    if default_iframe:
        streams.append({
            "server": "Default",
            "url": default_iframe.get("src")
        })

    # Coba cari list server mirror (biasanya di class .mirror-item atau <select>)
    # Struktur ini sangat bervariasi tergantung tema
    mirrors = soup.select("ul#playeroptionsul li")
    for mirror in mirrors:
        server_name = mirror.select_one("span.title").text.strip() if mirror.select_one("span.title") else "Unknown Server"
        # Link embed biasanya ada di atribut data-src atau perlu di-fetch lagi via AJAX
        # Untuk scraping statis, kita ambil atribut yang tersedia di elemen
        server_url = mirror.get("data-nume") or mirror.get("data-src")
        
        streams.append({
            "server": server_name,
            "embed_url": server_url # Note: Mungkin masih encrypted atau butuh decoding base64
        })

    # List Episode Lainnya (Navigasi)
    episode_list = []
    # Biasanya ada di sidebar atau bawah player
    for ep in soup.select("div.bixbox.lpl li"):
        ep_title = ep.select_one("div.lpl_title").text.strip() if ep.select_one("div.lpl_title") else ""
        ep_link = ep.select_one("a")["href"] if ep.select_one("a") else ""
        if ep_title:
            episode_list.append({"title": ep_title, "url": ep_link})

    return {
        "status": "success",
        "data": {
            "title": title,
            "synopsis": synopsis_text,
            "streams": streams,
            "episodes": episode_list
        }
    }
