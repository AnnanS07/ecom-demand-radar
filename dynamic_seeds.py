#!/usr/bin/env python3
import os, time, math, csv, requests
from datetime import datetime
from pytrends.request import TrendReq
from pytrends.exceptions import TooManyRequestsError, ResponseError
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
import gspread

# CONFIG
SCOPES     = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
SHEET_ID   = os.environ["SPREADSHEET_ID"]
WORKSHEET  = "DynamicSeeds"
GEO        = "IN"
MAX_VOL    = 100_000
WEIGHTS    = {"trend":0.6,"vol":0.4}
OUTPUT_CSV = "dynamic_seed_metrics.csv"
pytrends   = TrendReq(hl="en-US", tz=330)

def discover_trends():
    try:
        top_daily = list(pytrends.trending_searches(pn="IN").head(20))
    except ResponseError:
        top_daily = []
    try:
        charts = pytrends.top_charts(2024, hl="en-IN", tz=330, geo=GEO, cid="shopping")
        top_shop = [item["title"] for item in charts[:20]]
    except ResponseError:
        top_shop = []
    return list(dict.fromkeys(top_daily + top_shop))

def generate_seeds(trend):
    for i in range(3):
        try:
            time.sleep(2)
            pytrends.build_payload([trend], timeframe="today 12-m", geo=GEO)
            rel = pytrends.related_queries().get(trend,{}).get("rising")
            return [r["query"] for r in (rel or [])[:10]]
        except TooManyRequestsError:
            time.sleep((i+1)*30)
    return []

def get_trend_spike(kw):
    for i in range(3):
        try:
            time.sleep(2)
            pytrends.build_payload([kw], timeframe="today 12-m", geo=GEO)
            df = pytrends.interest_over_time()
            if df.empty or df[kw].head(12).mean()==0: return 0.0
            r,p=df[kw].tail(12).mean(),df[kw].head(12).mean()
            return max((r-p)/p,0.0)
        except TooManyRequestsError:
            time.sleep((i+1)*30)
    return 0.0

def get_search_vol(kw):
    resp = requests.get(f"https://api.keywordserp.com/search?api_key=demo&q={requests.utils.quote(kw)}").json()
    return min(int(resp.get("search_volume",0)), MAX_VOL)

def get_amazon_supply(kw):
    url=f"https://www.amazon.in/s?k={requests.utils.quote(kw)}"
    r=requests.get(url,headers={"User-Agent":"Mozilla/5.0"})
    soup=BeautifulSoup(r.text,"html.parser")
    items=soup.select("div[data-component-type='s-search-result']")
    revs=[]
    for it in items[:5]:
        s=it.select_one(".a-size-small .a-link-normal")
        t=s.text.replace(",","") if s else ""
        if t.isdigit(): revs.append(int(t))
    return len(items), (sum(revs)/len(revs) if revs else 0.0)

def sanitize(x): return float(x) if math.isfinite(x) else 0.0

def main():
    trends=discover_trends()
    seeds=set(trends)
    for t in trends:
        seeds.update(generate_seeds(t))
    rows=[]
    for kw in seeds:
        ts=datetime.now().isoformat(timespec="seconds")
        spike=get_trend_spike(kw)
        vol  =get_search_vol(kw)
        nv   =vol/MAX_VOL
        lst,rev=get_amazon_supply(kw)
        score=WEIGHTS["trend"]*spike+WEIGHTS["vol"]*nv
        gap  =sanitize(score)/(lst*rev+1)
        rows.append([ts,kw,sanitize(spike),vol,sanitize(nv),lst,sanitize(rev),sanitize(score),sanitize(gap)])
    creds=Credentials.from_service_account_file("credentials.json",scopes=SCOPES)
    gc=gspread.authorize(creds)
    ss=gc.open_by_key(SHEET_ID)
    try:
        ws=ss.worksheet(WORKSHEET); ws.clear()
    except:
        ws=ss.add_worksheet(title=WORKSHEET,rows="1000",cols="20")
    hdr=["Timestamp","Keyword","TrendSpike","SearchVol","NormVol","Listings","AvgReviews","DemandScore","GapIndex"]
    ws.update([hdr]+rows)
    with open(OUTPUT_CSV,"w",newline="") as f:
        w=csv.writer(f); w.writerow(hdr); w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {WORKSHEET} and {OUTPUT_CSV}")

if __name__=="__main__":
    main()
