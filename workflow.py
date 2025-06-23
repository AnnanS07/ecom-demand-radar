#!/usr/bin/env python3
"""
workflow.py
Fetches demand signals for seed keywords, writes to Google Sheets,
and fires webhook alerts for high-momentum terms.
"""
import os, csv, time, math, requests
from datetime import datetime
from pytrends.request import TrendReq
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
import gspread
from googleapiclient.discovery import build

# CONFIG
SEEDS_CSV        = "seeds.csv"
SPREADSHEET_ID   = os.environ.get("SPREADSHEET_ID")
SHEET_NAME       = "DemandData"
YOUTUBE_API_KEY  = os.environ.get("YOUTUBE_API_KEY")
N8N_WEBHOOK_URL  = os.environ.get("N8N_WEBHOOK_URL")
DEMAND_THRESHOLD = 0.8

# Sheets auth
SCOPES = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

# YouTube client
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

# Pytrends
pytrends = TrendReq(hl='en-US', tz=330)

def read_seeds():
    with open(SEEDS_CSV, newline='', encoding='utf-8') as f:
        return [r['keyword'] for r in csv.DictReader(f)]

def get_search_spike(kw):
    pytrends.build_payload([kw], timeframe='today 12-m')
    df = pytrends.interest_over_time()
    if df.empty: return 0.0
    recent = df[kw].tail(12).mean()
    prior  = df[kw].head(12).mean()
    return max((recent - prior)/prior, 0.0)

def get_amazon_review_velocity(kw):
    url = f"https://www.amazon.in/s?k={requests.utils.quote(kw)}"
    r = requests.get(url, headers={'User-Agent':'Mozilla/5.0'}, timeout=10)
    soup = BeautifulSoup(r.text, 'html.parser')
    spans = soup.select(".a-section .a-row.a-size-small span")
    nums = [int(s.get_text().replace(',','')) for s in spans if s.get_text().replace(',','').isdigit()]
    return sum(sorted(nums, reverse=True)[:5])

def get_youtube_social_growth(kw):
    resp = youtube.search().list(q=kw, part="id", type="video", maxResults=3).execute()
    total = 0
    for item in resp['items']:
        vid = item['id']['videoId']
        stats = youtube.videos().list(id=vid, part="statistics").execute()
        total += int(stats['items'][0]['statistics'].get('viewCount',0))
    return total / 1e5

def append_to_sheet(rows):
    sheet.append_rows(rows, value_input_option="USER_ENTERED")

def send_alert(kw, score):
    try:
        requests.post(N8N_WEBHOOK_URL, json={"keyword":kw,"score":score}, timeout=5)
    except:
        pass

def main():
    seeds = read_seeds()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = []
    for kw in seeds:
        spike    = get_search_spike(kw)
        velocity = get_amazon_review_velocity(kw)
        social   = get_youtube_social_growth(kw)

        
        vel_n = min(velocity / 500.0, 1.0)
        soc_n = min(social / 1.0, 1.0)
        demand_score = 0.4 * spike + 0.3 * vel_n + 0.3 * soc_n

        
        def clean(x):
            return float(x) if math.isfinite(x) else 0.0

        
        row = [
            now,
            kw,
            clean(spike),
            clean(velocity),
            clean(social),
            clean(demand_score),
        ]
        out.append(row)
          

        if score >= DEMAND_THRESHOLD:
            send_alert(kw, score)
        time.sleep(1)
    append_to_sheet(out)
    print(f"Appended {len(out)} rows.")

if __name__ == "__main__":
    main()
