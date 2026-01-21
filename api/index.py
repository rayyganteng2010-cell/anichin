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
    "Referer": "https://anichin.cafe/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

BASE_URL = "https://anichin.cafe"
CREATOR = "Sanka Vollerei"

def get_soup(url, params=None):
    try:
        # Timeout dinaikkan & verify=False jika ada masalah SSL (opsional, hati-hati di prod)
        req = requests.get(url, headers=HEADERS, params=params, timeout=25)
        req.raise_for_status()
        return BeautifulSoup(req.text, "html.parser")
    except Exception as e:
        print(f"Error accessing {url}: {e}")
        return None

def extract_slug(url):
    try:
        return url.strip("/").split("/")[-1]
    except: return ""

def parse_card(element, is_schedule=False):
    try:
        title_el = element.select_one("div.tt") or element.select_one(".entry-title")
        link_el = element.select_one("a")
        img_el = element.select_one("img")
        
        if not title_el or not link_el: return None
        
        url = link_el["href"]
        slug = extract_slug(url)
        poster = img_el["src"] if img_el else ""
        
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

# --- DETAIL (REVISED AGGRESSIVE SCRAPING) ---
@app.get("/api/detail")
def get_detail(url: str):
    soup = get_soup(url)
    if not soup: raise HTTPException(status_code=404, detail="Page not found")

    # Cek tipe halaman (Episode vs Info)
    is_episode_page = bool(soup.select_one("#playeroptionsul") or soup.select_one(".video-content") or soup.select_one("select.mirror") or soup.select_one("div.mctnx"))

    if is_episode_page:
        # === HALAMAN NONTON ===
        title = soup.select_one("h1.entry-title").text.strip()
        
        # 1. STREAMING (Coba berbagai selector)
        servers = []
        
        # Opsi A: List UL (Standard)
        for li in soup.select("ul#playeroptionsul li"):
            name = li.select_one(".title").text.strip()
            link = li.get("data-src") or li.get("data-url")
            if link: servers.append({"name": name, "url": link})
            
        # Opsi B: Select Option (Legacy)
        if not servers:
            for opt in soup.select("select.mirror option"):
                val = opt.get("value")
                if val: servers.append({"name": opt.text.strip(), "url": val})
        
        # Opsi C: Iframe Default (Selalu ambil sebagai fallback/main)
        iframe = soup.select_one(".video-content iframe")
        if iframe: 
            def_url = iframe["src"]
            # Cek apakah default sudah ada di server list, jika belum, tambahkan
            if not any(s['url'] == def_url for s in servers):
                servers.insert(0, {"name": "Default", "url": def_url})
            main_url = {"name": "Default", "url": def_url}
        else:
            main_url = servers[0] if servers else {"name": "None", "url": ""}

        # 2. DOWNLOADS (Aggressive Logic)
        downloads = {}
        # Kumpulkan semua elemen yang MUNGKIN berisi download
        dl_candidates = soup.select("div.mctnx div.soraddl") + soup.select("div.soraurl") + soup.select("div.dl-box")
        
        for box in dl_candidates:
            # Cari judul resolusi
            res_el = box.select_one("div.res") or box.select_one("h3") or box.select_one("strong")
            if not res_el: continue
            
            res_text = res_el.text.strip()
            # Regex untuk menangkap 360, 480, 720, 1080
            res_match = re.search(r'(360|480|720|1080)p?', res_text)
            
            if res_match:
                key = f"download_url_{res_match.group(1)}p"
            else:
                continue # Skip jika tidak ada indikator resolusi

            links_map = {}
            for a in box.select("a"):
                provider = a.text.strip()
                # Filter link sampah/iklan jika perlu
                if provider and a.get("href"):
                    links_map[provider] = a["href"]
            
            if links_map:
                downloads[key] = links_map

        # 3. NAVIGATION
        nav = {}
        # Coba selector standar & alternatif
        nav_prev = soup.select_one("div.nvs .nav-previous a") or soup.select_one("a[rel='prev']")
        nav_next = soup.select_one("div.nvs .nav-next a") or soup.select_one("a[rel='next']")
        nav_all = soup.select_one("div.nvs .nvsc a") or soup.select_one(".nvs a[href*='/seri/']")

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

        # 4. DETAILS METADATA
        series_title = re.split(r' Episode \d+', title, flags=re.IGNORECASE)[0].strip()
        # Fallback slug extraction
        try:
            series_slug = extract_slug(url).split("-episode-")[0]
        except:
            series_slug = "unknown"
            
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

        # 5. EPISODES LIST (Fix untuk Sidebar Kosong)
        episodes_list = []
        # Cari di beberapa kemungkinan tempat
        # 1. Sidebar widget (.bixbox.lpl)
        # 2. Main list (#episode_list) - terkadang dimuat juga di bawah player
        sources = soup.select("div.bixbox.lpl li a") + soup.select("#episode_list li a") + soup.select(".eplister li a")
        
        # Deduplikasi berdasarkan URL
        seen_urls = set()
        
        for a in sources:
            href = a.get("href")
            if not href or href in seen_urls: continue
            seen_urls.add(href)
            
            # Coba ambil judul yang bersih
            ep_txt = a.select_one(".lpl_title") or a.select_one(".epl-title")
            final_title = ep_txt.text.strip() if ep_txt else a.text.strip()
            
            # Cleanup judul
            final_title = final_title.replace(series_title, "").replace("Subtitle Indonesia", "").strip()
            if not final_title: final_title = a.text.strip() # Fallback

            episodes_list.append({
                "episode": final_title,
                "slug": extract_slug(href),
                "href": f"/donghua/episode/{extract_slug(href)}",
                "anichinUrl": href
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

        genres = [{"name": a.text.strip(), "slug": extract_slug(a['href']), "anichinUrl": a['href']} for a in soup.select("div.genxed a")]
        
        episodes_list = []
        for a in soup.select("ul#episode_list li a"):
            ep_num = a.select_one(".epl-num")
            ep_title = a.select_one(".epl-title")
            final_title = f"{ep_num.text.strip() if ep_num else ''} {ep_title.text.strip() if ep_title else ''}".strip()
            if not final_title: final_title = a.text.strip()
            
            episodes_list.append({
                "episode": final_title,
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
