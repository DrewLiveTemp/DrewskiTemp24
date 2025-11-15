import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import aiohttp
from datetime import datetime
import re 

API_URL = "https://ppv.to/api/streams"

CUSTOM_HEADERS = [
    '#EXTVLCOPT:http-origin=https://ppv.to',
    '#EXTVLCOPT:http-referrer=https://ppv.to/',
    '#EXTVLCOPT:http-user-agent=Mozilla/5.0'
]

ALLOWED_CATEGORIES = {
    "24/7 Streams", "Wrestling", "Football", "Basketball", "Baseball",
    "Combat Sports", "American Football", "Darts", "Motorsports", "Ice Hockey"
}

CATEGORY_LOGOS = {
    "24/7 Streams": "http://drewlive24.duckdns.org:9000/Logos/247.png",
    "Wrestling": "http://drewlive24.duckdns.org:9000/Logos/Wrestling.png",
    "Football": "http://drewlive24.duckdns.org:9000/Logos/Football.png",
    "Basketball": "http://drewlive24.duckdns.org:9000/Logos/Basketball.png",
    "Baseball": "http://drewlive24.duckdns.org:9000/Logos/Baseball.png",
    "American Football": "http://drewlive24.duckdns.org:9000/Logos/NFL3.png",
    "Combat Sports": "http://drewlive24.duckdns.org:9000/Logos/CombatSports2.png",
    "Darts": "http://drewlive24.duckdns.org:9000/Logos/Darts.png",
    "Motorsports": "http://drewlive24.duckdns.org:9000/Logos/Motorsports2.png",
    "Live Now": "http://drewlive24.duckdns.org:9000/Logos/DrewLiveSports.png",
    "Ice Hockey": "http://drewlive24.duckdns.org:9000/Logos/Hockey.png"
}

CATEGORY_TVG_IDS = {
    "24/7 Streams": "24.7.Dummy.us",
    "Wrestling": "PPV.EVENTS.Dummy.us",
    "Football": "Soccer.Dummy.us",
    "Basketball": "Basketball.Dummy.us",
    "Baseball": "MLB.Baseball.Dummy.us",
    "American Football": "NFL.Dummy.us",
    "Combat Sports": "PPV.EVENTS.Dummy.us",
    "Darts": "Darts.Dummy.us",
    "Motorsports": "Racing.Dummy.us",
    "Live Now": "24.7.Dummy.us",
    "Ice Hockey": "NHL.Hockey.Dummy.us"
}

GROUP_RENAME_MAP = {
    "24/7 Streams": "PPVLand - Live Channels 24/7",
    "Wrestling": "PPVLand - Wrestling Events",
    "Football": "PPVLand - Global Football Streams",
    "Basketball": "PPVLand - Basketball Hub",
    "Baseball": "PPVLand - MLB",
    "American Football": "PPVLand - NFL Action",
    "Combat Sports": "PPVLand - Combat Sports",
    "Darts": "PPVLand - Darts",
    "Motorsports": "PPVLand - Racing Action",
    "Live Now": "PPVLand - Live Now",
    "Ice Hockey": "PPVLand - NHL Action"
}

NFL_TEAMS = {
    # your full NFL set here
}

COLLEGE_TEAMS = {
    # your full college set here
}

# ------------------------------------------------------------
# ⭐ TRUE FIRST-M3U8 + SAFE LISTENER + FASTER PAGE LOAD
# ------------------------------------------------------------
async def grab_m3u8_from_iframe(page, iframe_url):
    first_url = None

    def handle_response(response):
        nonlocal first_url
        url = response.url

        if ".m3u8" in url and first_url is None:
            print(f"✅ Found M3U8 Stream: {url}")
            first_url = url
            # remove listener safely once we got first URL
            try:
                page.remove_listener("response", handle_response)
            except:
                pass

    page.on("response", handle_response)

    print(f"🌐 Navigating to iframe: {iframe_url}")

    # Faster, and we don't care if it "fails" as long as we saw a URL
    try:
        await page.goto(iframe_url, timeout=5000, wait_until="commit")
    except Exception:
        # No noisy ❌ log here – if we already got the URL, it's fine
        pass

    # tiny delay to let any JS kick in if needed
    try:
        await page.wait_for_timeout(300)
        nested_iframe = page.locator("iframe")

        if await nested_iframe.count() > 0:
            print("🔎 Found nested iframe, attempting to click inside it.")
            await page.mouse.click(200, 200)
            print("✅ Mouse click dispatched on page center to trigger nested player.")
        else:
            print("🖱️ No nested iframe found. Clicking center of page body.")
            await page.mouse.click(200, 200)

    except Exception as e:
        print(f"⚠️ Clicking failed, but proceeding anyway. Error: {e}")

    print("⏳ Waiting for stream to be requested (max 10s)...")

    for _ in range(400):  # up to ~10s, but we break as soon as first_url is set
        if first_url:
            break
        await page.wait_for_timeout(25)

    try:
        page.remove_listener("response", handle_response)
    except:
        pass

    if not first_url:
        print(f"❌ No M3U8 URLs were captured for {iframe_url}")
        return set()

    valid = await check_m3u8_url(first_url, iframe_url)
    if valid:
        return {first_url}

    print(f"🗑️ Discarding invalid or unreachable URL: {first_url}")
    return set()

# ------------------------------------------------------------
# Everything below this stays EXACTLY the same
# ------------------------------------------------------------
async def check_m3u8_url(url, referer):
    if "gg.poocloud.in" in url:
        return True
    try:
        origin = "https://" + referer.split('/')[2]
        headers = {"User-Agent": "Mozilla/5.0", "Referer": referer, "Origin": origin}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url, headers=headers) as resp:
                return resp.status in (200, 403)
    except:
        return False

async def get_streams():
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'User-Agent': 'Mozilla/5.0'}
        ) as session:
            print(f"🌐 Fetching streams from {API_URL}")
            resp = await session.get(API_URL)
            print(f"🔍 Response status: {resp.status}")
            if resp.status != 200:
                print(f"❌ Error response: {await resp.text()}")
                return None
            return await resp.json()
    except Exception as e:
        print(f"❌ Error in get_streams: {str(e)}")
        return None

async def grab_live_now_from_html(page, base_url="https://ppv.to/"):
    print("🌐 Scraping 'Live Now' streams from HTML...")
    live_now_streams = []
    try:
        await page.goto(base_url, timeout=20000)
        await asyncio.sleep(3)

        live_cards = await page.query_selector_all("#livecards a.item-card")
        for card in live_cards:
            href = await card.get_attribute("href")
            name_el = await card.query_selector(".card-title")
            poster_el = await card.query_selector("img.card-img-top")
            name = await name_el.inner_text() if name_el else "Unnamed Live"
            poster = await poster_el.get_attribute("src") if poster_el else None

            if href:
                iframe_url = f"{base_url.rstrip('/')}{href}"
                live_now_streams.append({
                    "name": name.strip(),
                    "iframe": iframe_url,
                    "category": "Live Now",
                    "poster": poster
                })
    except Exception as e:
        print(f"❌ Failed scraping 'Live Now': {e}")

    print(f"✅ Found {len(live_now_streams)} 'Live Now' streams")
    return live_now_streams

def build_m3u(streams, url_map):
    lines = ['#EXTM3U url-tvg="https://epgshare01.online/epgshare01/epg_ripper_DUMMY_CHANNELS.xml.gz"']
    seen_names = set()

    for s in streams:
        name_lower = s["name"].strip().lower()
        if name_lower in seen_names:
            continue
        seen_names.add(name_lower)

        key = f"{s['name']}::{s['category']}::{s['iframe']}"
        urls = url_map.get(key, [])
        if not urls:
            print(f"⚠️ No working URLs for {s['name']}")
            continue

        orig_cat = s["category"]
        final_group = GROUP_RENAME_MAP.get(orig_cat)
        logo = s.get("poster") or CATEGORY_LOGOS.get(orig_cat)
        tvg_id = CATEGORY_TVG_IDS.get(orig_cat)

        if orig_cat == "American Football":
            nl = name_lower
            for t in NFL_TEAMS:
                if t in nl:
                    final_group = "PPVLand - NFL Action"
                    tvg_id = "NFL.Dummy.us"
            for t in COLLEGE_TEAMS:
                if t in nl:
                    final_group = "PPVLand - College Football"
                    tvg_id = "NCAA.Football.Dummy.us"

        url = next(iter(urls))
        lines.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{logo}" group-title="{final_group}",{s["name"]}')
        lines.extend(CUSTOM_HEADERS)
        lines.append(url)

    return "\n".join(lines)

async def main():
    print("🚀 Starting PPV Stream Fetcher")
    data = await get_streams()
    if not data or "streams" not in data:
        print("❌ No valid data received from API")
        return

    print(f"✅ Found {len(data['streams'])} categories")
    streams = []

    for cat_obj in data["streams"]:
        cat = cat_obj.get("category", "")
        for stream in cat_obj.get("streams", []):
            iframe = stream.get("iframe")
            name = stream.get("name")
            poster = stream.get("poster")
            if iframe:
                streams.append({
                    "name": name,
                    "iframe": iframe,
                    "category": cat,
                    "poster": poster
                })

    seen = set()
    unique = []
    for s in streams:
        k = s["name"].lower()
        if k not in seen:
            seen.add(k)
            unique.append(s)
    streams = unique

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        url_map = {}
        total = len(streams)

        for idx, s in enumerate(streams, start=1):
            print(f"\n🔎 Scraping stream {idx}/{total}: {s['name']} ({s['category']})")
            key = f"{s['name']}::{s['category']}::{s['iframe']}"
            url_map[key] = await grab_m3u8_from_iframe(page, s["iframe"])

        live_now = await grab_live_now_from_html(page)
        for s in live_now:
            key = f"{s['name']}::{s['category']}::{s['iframe']}"
            url_map[key] = await grab_m3u8_from_iframe(page, s["iframe"])

        streams.extend(live_now)

        await browser.close()

    print("\n💾 Writing final playlist to PPVLand.m3u8 ...")
    playlist = build_m3u(streams, url_map)

    with open("PPVLand.m3u8", "w", encoding="utf-8") as f:
        f.write(playlist)

    print(f"✅ Done! Playlist saved as PPVLand.m3u8 at", datetime.utcnow().isoformat(), "UTC")

if __name__ == "__main__":
    asyncio.run(main())
