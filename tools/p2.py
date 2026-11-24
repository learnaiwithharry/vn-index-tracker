import requests, time, json
UA={"User-Agent":"Mozilla/5.0 Chrome/130","Accept":"application/json"}
def g(u):
    try:
        r=requests.get(u,headers=UA,timeout=25); return f"{r.status_code} {r.text[:600]}"
    except Exception as e: return f"ERR {e}"
now=int(time.time())
for u in ["https://api-finfo.vndirect.com.vn/v4/stock_prices?sort=date&q=code:VIC&size=3",
          "https://api-finfo.vndirect.com.vn/v4/vnmarket_prices?sort=date&q=code:VNINDEX&size=3",
          "https://api-finfo.vndirect.com.vn/v4/stock_prices?q=date:2026-11-24~floor:HOSE&size=2",
          f"https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol=VNINDEX&from={now-6*86400}&to={now}",
          "https://kbbuddywts.kbsec.com.vn/iis-server/investment/index/VNINDEX/data_day?sdate=20-11-2026&edate=25-11-2026",
          "https://kbbuddywts.kbsec.com.vn/iis-server/investment/stocks/VIC/data_day?sdate=20-11-2026&edate=25-11-2026",
          f"https://services.entrade.com.vn/chart-api/v2/ohlcs/index?from={now-6*86400}&to={now}&symbol=VNINDEX&resolution=1D",
          "https://cafef.vn/du-lieu/Ajax/PageNew/DataHistory/PriceHistory.ashx?Symbol=VNINDEX&PageIndex=1&PageSize=3"]:
    print("=====",u[:90]); print(g(u))
