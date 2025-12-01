import feedparser
import asyncio
import hashlib
import re
import json
import os
import requests
from telegram import Bot
import logging
import random  

from bs4 import BeautifulSoup

# تنظیمات - عوض کن!
BOT_TOKEN = "8297507213:AAExuYByDdP5cRaY0A0JRfMVdp9G58vj_Zs"
CHANNEL_ID = "@my_Latest_news"

# RSS feeds - منابع آزاد رو بیشتر (وزن ۳ برابر داخلی)
FREE_FEEDS = [
    "https://www.iranintl.com/rss",
    "https://ir.voanews.com/rss.xml",
    "https://www.manototv.com/rss",
    "https://www.radiofarda.com/api/zq_ottqem_tq",
    "https://rss.dw.com/rdf/rss-fa-all",
    "https://feeds.bbci.co.uk/persian/rss.xml",
    "https://www.alarabiya.net/persian/rss",
    "https://www.radiozamaneh.com/rss",
    "https://www.rfi.fr/fa/rss",  # RFI فارسی
    "https://www.euronews.com/rss/persian.xml",  # Euronews فارسی
]

DOMESTIC_FEEDS = [
    "https://www.farsnews.ir/rss",
    "https://www.tasnimnews.com/fa/rss",
    "https://www.mehrnews.com/rss",
    "https://www.isna.ir/rss",
    "https://www.irna.ir/rss",
    "https://www.eghtesadonline.com/rss",
    "https://www.donya-e-eqtesad.com/rss",
    "https://www.khabaronline.ir/rss",
]

# فایل برای ذخیره seen_hashes
SEEN_FILE = "seen_news.json"

# بارگذاری seen_hashes از فایل
if os.path.exists(SEEN_FILE):
    with open(SEEN_FILE, 'r', encoding='utf-8') as f:
        seen_hashes = set(json.load(f))
else:
    seen_hashes = set()

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)

def clean_html(text):
    return re.sub('<.*?>', '', text).strip()

def get_unique_id(entry):
    pub_date = getattr(entry, 'published', '') or getattr(entry, 'updated', '')
    return hashlib.md5((entry.title + entry.link + pub_date).encode('utf-8')).hexdigest()

def save_seen():
    with open(SEEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(seen_hashes), f)

def download_image(url):
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.content
    except:
        pass
    return None

def download_video(url):
    try:
        response = requests.get(url, timeout=15)  # timeout بیشتر برای ویدیو
        if response.status_code == 200:
            return response.content
    except:
        pass
    return None

def is_persian_text(text):
    # چک درصد حروف فارسی/عربی (حداقل ۶۰%)
    persian_chars = re.findall(r'[\u0600-\u06FF]', text)
    total_chars = len(text)
    if total_chars == 0:
        return False
    return len(persian_chars) / total_chars >= 0.6  # ۶۰% فارسی

async def send_news():
    # وزن‌دار رندوم: آزاد وزن ۳، داخلی ۱ (بیشتر آزاد بیاد)
    combined_feeds = FREE_FEEDS * 3 + DOMESTIC_FEEDS
    random.shuffle(combined_feeds)
    feeds_to_check = combined_feeds[:len(FREE_FEEDS + DOMESTIC_FEEDS)]  # تعداد اصلی
    
    new_posts = 0
    for url in feeds_to_check:
        try:
            feed = feedparser.parse(url, request_headers={'User-Agent': 'NewsBot/1.0'})
            if not feed.entries:
                continue
            for entry in reversed(feed.entries[:10]):
                uid = get_unique_id(entry)
                if uid in seen_hashes:
                    continue
                title = entry.title.strip()
                link = entry.link.strip()
                
                # فیلتر عنوان فارسی (حداقل ۶۰% حروف فارسی)
                if not is_persian_text(title):
                    continue  # skip اگر انگلیسی یا مخلوط بود
                
                # متن کامل
                try:
                    # اول سعی کن از content یا summary
                    description = entry.summary if hasattr(entry, 'summary') else ""
                    content = entry.content[0].value if hasattr(entry, 'content') and entry.content else description
                    full_text = clean_html(content)
                    full_text = re.sub(r'\s+', ' ', full_text).strip()
                    
                    # اگر کوتاه بود، از لینک scrape کن (کامل‌تر)
                    if len(full_text) < 800:
                        response = requests.get(link, timeout=10)
                        if response.status_code == 200:
                            soup = BeautifulSoup(response.text, 'html.parser')
                            # حذف جدول‌ها، تبلیغات و اسکریپت‌ها
                            for table in soup.find_all('table'):
                                table.decompose()
                            for ad in soup.find_all('div', class_=re.compile(r'ad|advert')):
                                ad.decompose()
                            for script in soup.find_all('script'):
                                script.decompose()
                            # سعی کن از article یا body div
                            article = soup.find('article') or soup.find('div', class_='body') or soup.find('div', id='body') or soup.find('div', class_='content') or soup.find('div', id='content')
                            if article:
                                paragraphs = article.find_all('p')
                            else:
                                paragraphs = soup.find_all('p')
                            full_text = ' '.join([p.get_text().strip() for p in paragraphs[:30]])  # ۳۰ پاراگراف برای کامل‌تر
                            full_text = clean_html(full_text)
                            full_text = re.sub(r'\s+', ' ', full_text).strip()
                    
                    # برش بدون "ادامه در منبع" (فقط ... اگر لازم)
                    if len(full_text) > 4000:
                        full_text = full_text[:4000] + " ..."
                except:
                    full_text = "متن کامل در منبع موجود است."
                # عکس یا ویدیو - دانلود کن
                media_data = None
                media_type = None  # 'photo' یا 'video'
                if hasattr(entry, 'media_content'):
                    for media in entry.media_content:
                        if 'url' in media:
                            if 'jpg' in media['url'] or 'png' in media['url']:
                                media_data = download_image(media['url'])
                                media_type = 'photo'
                                break
                            elif 'mp4' in media['url'] or 'video' in media.get('type', ''):
                                media_data = download_video(media['url'])
                                media_type = 'video'
                                break
                elif hasattr(entry, 'enclosures'):
                    for enc in entry.enclosures:
                        if enc.type.startswith('image/'):
                            media_data = download_image(enc.url)
                            media_type = 'photo'
                            break
                        elif enc.type.startswith('video/'):
                            media_data = download_video(enc.url)
                            media_type = 'video'
                            break
                # پیام - عنوان بولد
                caption = f"🟥 <b>{title}</b>\n\n{full_text}\n\n@my_Latest_news"
                try:
                    if media_data:
                        if media_type == 'video':
                            await bot.send_video(chat_id=CHANNEL_ID, video=media_data, caption=caption[:1024], parse_mode='HTML')
                            print(f"✅ ویدیو ارسال شد: {title[:50]}...")
                        else:
                            await bot.send_photo(chat_id=CHANNEL_ID, photo=media_data, caption=caption[:1024], parse_mode='HTML')
                            print(f"✅ عکس ارسال شد: {title[:50]}...")
                    else:
                        if len(caption) > 4096:
                            parts = [caption[i:i+4000] for i in range(0, len(caption), 4000)]
                            for part in parts:
                                await bot.send_message(chat_id=CHANNEL_ID, text=part, parse_mode='HTML', disable_web_page_preview=False)
                                await asyncio.sleep(1)
                        else:
                            await bot.send_message(chat_id=CHANNEL_ID, text=caption, parse_mode='HTML', disable_web_page_preview=False)
                        print(f"✅ متن ارسال شد: {title[:50]}...")
                    seen_hashes.add(uid)
                    save_seen()
                    new_posts += 1
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"❌ خطا ارسال: {e}")
        except Exception as e:
            print(f"❌ خطا فید {url}: {e}")
    print(f"🔄 چک تمام | اخبار جدید: {new_posts} | کل: {len(seen_hashes)}")

async def main_loop():
    print("🚀 ربات خبرخوان شروع شد...")
    try:
        while True:
            await send_news()
            await asyncio.sleep(60)  # هر ۶۰ ثانیه
    except KeyboardInterrupt:
        print("🛑 توقف...")
        save_seen()
    finally:
        await bot.shutdown()

if __name__ == "__main__":
    asyncio.run(main_loop())