import os
import time
import feedparser
import requests
from google import genai
from dotenv import load_dotenv

# טעינת הגדרות
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
tele_token = os.getenv("TELEGRAM_TOKEN")
tele_chat_id = os.getenv("TELEGRAM_CHAT_ID")

if not api_key or not tele_token or not tele_chat_id:
    raise ValueError("שגיאה: אחד או יותר מהמפתחות חסרים בקובץ .env!")

client = genai.Client(api_key=api_key)

PODCAST_RSS_URL = "https://feed.podbean.com/epgb/feed.xml" 
DOWNLOAD_FOLDER = "podcast_episodes"
HISTORY_FILE = "last_processed.txt"  
LOCAL_AUDIO_PATH = os.path.join(DOWNLOAD_FOLDER, "latest_episode.mp3") 

def get_latest_episode(rss_url):
    print("משוך נתונים מהפיד של קלצ'קין...")
    feed = feedparser.parse(rss_url)
    if not feed.entries:
        return None
    
    # חזרנו ל-[0] - בודק תמיד את הפרק הכי חדש שיצא באותו יום
    latest_entry = feed.entries[0]
    
    title = latest_entry.title
    audio_url = None
    if hasattr(latest_entry, 'enclosures'):
        for enclosure in latest_entry.enclosures:
            if 'audio' in enclosure.get('type', '') or enclosure.get('url', '').endswith('.mp3'):
                audio_url = enclosure.get('url')
                break
    return {"title": title, "audio_url": audio_url}

def is_already_processed(current_title):
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            last_title = f.read().strip()
            if last_title == current_title:
                return True
    return False

def save_to_history(title):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        f.write(title)

def download_episode(audio_url):
    if not os.path.exists(DOWNLOAD_FOLDER):
        os.makedirs(DOWNLOAD_FOLDER)
    if os.path.exists(LOCAL_AUDIO_PATH):
        os.remove(LOCAL_AUDIO_PATH)

    print("מוריד את הפרק האחרון...")
    response = requests.get(audio_url, stream=True)
    with open(LOCAL_AUDIO_PATH, 'wb') as f:
        for chunk in response.iter_content(chunk_size=1024*1024):
            if chunk: f.write(chunk)
    print("ההורדה הסתיימה בהצלחה.")
    return LOCAL_AUDIO_PATH

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{tele_token}/sendMessage"
    
    # ניסיון ראשון: שליחה עם עיצוב (Markdown)
    payload = {"chat_id": tele_chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"העיצוב נשבר, מנסה לשלוח כטקסט רגיל... (שגיאה: {response.text})")
            
            # ניסיון שני: גיבוי - שליחה ללא עיצוב
            fallback_payload = {"chat_id": tele_chat_id, "text": text}
            fallback_response = requests.post(url, json=fallback_payload)
            
            if fallback_response.status_code != 200:
                print(f"שגיאה מוחלטת בשליחה לטלגרם: {fallback_response.text}")
    except Exception as e:
        print(f"שגיאה בחיבור ל-API של טלגרם: {e}")

def analyze_audio_with_gemini(file_path, episode_title):
    print("מעלה את קובץ השמע לשרתי גוגל לניתוח...")
    audio_file = client.files.upload(file=file_path)
    
    print("גוגל מעבדת את השמע...")
    while audio_file.state.name == "PROCESSING":
        time.sleep(5)
        audio_file = client.files.get(name=audio_file.name)
        
    if audio_file.state.name == "FAILED":
        raise ValueError("עיבוד הקובץ נכשל בשרתי גוגל.")
        
    print("הקובץ מוכן! Gemini-Flash מתחיל לחלץ המלצות...")
    
    prompt = f"""
    אתה עוזר מחקר תרבותי חכם. הקשב היטב לפרק בשם "{episode_title}" מתוך הפודקאסט בעברית "ברדיו עם קלצ'קין".
    המנחה והאורחים ממליצים לעיתים קרובות על יצירות תרבות (ספר, סרט, סדרה, אלבום מוזיקה).
    
    עבור כל המלצה אקטיבית, חלץ בצורה מסודרת:
    - סוג המדיה (ספר / סרט / סדרה / אלבום מוזיקה / אחר)
    - שם היצירה והשם של היוצר
    - מי המליץ ולמה (הקשר קצר מהשיחה, מה הם אהבו בזה)
    
    אם ורק אם אין בפרק הזה אף המלצה תרבותית אקטיבית לקהל, כתוב בשורה הראשונה של תשובתך בדיוק את המילה: "NO_RECOMMENDATIONS".
    אם יש המלצות, אל תכתוב את המילה הזו, אלא פשוט תציג את רשימת ההמלצות בעברית קריאה ומעוצבת יפה עם בולטים והדגשות.
    """
    
    response = client.models.generate_content(model="gemini-2.5-flash", contents=[audio_file, prompt])
    print("מנקה את קובץ השמע משרתי גוגל...")
    client.files.delete(name=audio_file.name)
    return response.text

if __name__ == "__main__":
    latest = get_latest_episode(PODCAST_RSS_URL)
    if latest:
        print(f"הפרק הכי חדש בפיד: {latest['title']}")
        
        # חזרנו לבדיקת הזיכרון האמיתית
        if is_already_processed(latest['title']):
            print(f"\nהפרק '{latest['title']}' כבר עובד בעבר. מדלג.")
        else:
            file_path = download_episode(latest["audio_url"])
            if file_path:
                try:
                    raw_result = analyze_audio_with_gemini(file_path, latest['title'])
                    
                    # השינוי החדש נמצא כאן:
                    if "NO_RECOMMENDATIONS" in raw_result:
                        print(f"\nלא נמצאו המלצות תרבותיות בפרק: {latest['title']}. שולח עדכון לטלגרם...")
                        telegram_text = f"🎙️ *עדכון מהפודקאסט של קלצ'קין*\n\n"
                        telegram_text += f"📌 *שם הפרק:* {latest['title']}\n\n"
                        telegram_text += "אין סיכום לפרק הזה (לא נמצאו המלצות תרבותיות)."
                        send_telegram_message(telegram_text)
                    else:
                        telegram_text = f"🎙️ *המלצות תרבות מהפרק של קלצ'קין!*\n"
                        telegram_text += f"📌 *שם הפרק:* {latest['title']}\n\n"
                        telegram_text += raw_result
                        send_telegram_message(telegram_text)
                        print("ההמלצות נשלחו לטלגרם!")
                    
                    # שומרים בזיכרון כדי שלא ירוץ שוב מחר בטעות על אותו פרק
                    save_to_history(latest['title'])
                    
                except Exception as e:
                    print(f"שגיאה בתהליך הניתוח: {e}")