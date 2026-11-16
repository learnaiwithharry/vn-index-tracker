"""Chạy thử: nguồn dữ liệu nào truy cập được từ máy chủ GitHub."""
import json, sys, time, traceback
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
      "Accept": "application/json, text/plain, */*"}
now = int(time.time())

def show(name, fn):
    print(f"\n===== {name}")
    try:
        out = fn()
        s = out if isinstance(out, str) else repr(out)
        print(s[:1800])
    except Exception as e:
        print("FAILED:", type(e).__name__, str(e)[:400])

def get(url, **kw):
    r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=25, **kw)
    return f"HTTP {r.status_code} len={len(r.content)}\n{r.text[:1500]}"

def post(url, body, **kw):
    r = requests.post(url, json=body, headers={**UA, **kw.pop("headers", {})}, timeout=25)
    return f"HTTP {r.status_code} len={len(r.content)}\n{r.text[:1500]}"

show("ip", lambda: get("https://ipinfo.io/json"))
# --- VNDirect
show("vnd stock_prices VIC", lambda: get("https://api-finfo.vndirect.com.vn/v4/stock_prices?sort=date&q=code:VIC~date:gte:2020-01-01&size=3&page=1"))
show("vnd stock_prices VPL first days", lambda: get("https://api-finfo.vndirect.com.vn/v4/stock_prices?sort=date:asc&q=code:VPL&size=3"))
show("vnd stock_prices by date (all codes)", lambda: get("https://api-finfo.vndirect.com.vn/v4/stock_prices?q=date:2026-11-13~floor:HOSE&size=3"))
show("vnd stocks HOSE", lambda: get("https://api-finfo.vndirect.com.vn/v4/stocks?q=type:STOCK~status:LISTED~floor:HOSE&size=3"))
show("vnd index prices", lambda: get("https://api-finfo.vndirect.com.vn/v4/vnmarket_prices?sort=date&q=code:VNINDEX,VN30,VN100~date:gte:2026-11-10&size=9"))
show("vnd ratios latest mktcap", lambda: get("https://api-finfo.vndirect.com.vn/v4/ratios/latest?filter=itemCode:51003,57066&where=code:VIC&order=reportDate&fields=itemCode,value,reportDate,code"))
show("vnd ratios hist mktcap", lambda: get("https://api-finfo.vndirect.com.vn/v4/ratios?q=code:VIC~itemCode:51003~reportDate:gte:2020-03-25~reportDate:lte:2020-04-05&size=5"))
show("vnd dchart VNINDEX", lambda: get(f"https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol=VNINDEX&from={now-864000}&to={now}"))
show("vnd dchart VN100", lambda: get(f"https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol=VN100&from={now-864000}&to={now}"))
show("vnd events VIC", lambda: get("https://api-finfo.vndirect.com.vn/v4/events?q=code:VIC~effectiveDate:gte:2020-01-01&size=5&sort=effectiveDate:desc"))
# --- DNSE / entrade
show("entrade stock VIC", lambda: get(f"https://services.entrade.com.vn/chart-api/v2/ohlcs/stock?from={now-864000}&to={now}&symbol=VIC&resolution=1D"))
show("entrade index VNINDEX", lambda: get(f"https://services.entrade.com.vn/chart-api/v2/ohlcs/index?from={now-864000}&to={now}&symbol=VNINDEX&resolution=1D"))
show("entrade index VN100", lambda: get(f"https://services.entrade.com.vn/chart-api/v2/ohlcs/index?from={now-864000}&to={now}&symbol=VN100&resolution=1D"))
# --- SSI
show("ssi iboard hose", lambda: get("https://iboard-query.ssi.com.vn/stock/exchange/hose", headers={"Origin": "https://iboard.ssi.com.vn", "Referer": "https://iboard.ssi.com.vn/"}))
show("ssi iboard VN30 group", lambda: get("https://iboard-query.ssi.com.vn/stock/group/VN30", headers={"Origin": "https://iboard.ssi.com.vn", "Referer": "https://iboard.ssi.com.vn/"}))
show("ssi dchart VIC", lambda: get(f"https://iboard-api.ssi.com.vn/statistics/charts/history?resolution=1D&symbol=VIC&from={now-864000}&to={now}", headers={"Origin": "https://iboard.ssi.com.vn"}))
# --- Vietcap
show("vci symbols", lambda: get("https://trading.vietcap.com.vn/api/price/symbols/getAll", headers={"Origin": "https://trading.vietcap.com.vn", "Referer": "https://trading.vietcap.com.vn/"}))
show("vci ohlc", lambda: post("https://trading.vietcap.com.vn/api/chart/OHLCChart/gap-chart", {"timeFrame": "ONE_DAY", "symbols": ["VIC", "VNINDEX", "VN30", "VN100"], "to": now, "countBack": 3}, headers={"Origin": "https://trading.vietcap.com.vn", "Referer": "https://trading.vietcap.com.vn/"}))
# --- TCBS, cafef, yahoo
show("tcbs bars", lambda: get(f"https://apipubaws.tcbs.com.vn/stock-insight/v2/stock/bars-long-term?ticker=VIC&type=stock&resolution=D&to={now}&countBack=3"))
show("cafef price history", lambda: get("https://cafef.vn/du-lieu/Ajax/PageNew/DataHistory/PriceHistory.ashx?Symbol=VIC&StartDate=&EndDate=&PageIndex=1&PageSize=3"))
show("yahoo VIC.VN", lambda: get("https://query1.finance.yahoo.com/v8/finance/chart/VIC.VN?range=5d&interval=1d"))

# --- vnstock library
def vn():
    import vnstock
    return f"vnstock {getattr(vnstock, '__version__', '?')} exports: {[n for n in dir(vnstock) if not n.startswith('_')][:60]}"
show("vnstock import", vn)

for src in ("KBS", "VCI"):
    def q(sym, src=src, start="2026-11-01"):
        from vnstock import Quote
        df = Quote(symbol=sym, source=src).history(start=start, end="2026-11-16", interval="1D")
        return f"{df.shape}\n{df.tail(4).to_string()}"
    show(f"vnstock {src} quote VIC", lambda: q("VIC"))
    show(f"vnstock {src} quote VIC 2020", lambda: q("VIC", start="2020-03-25")[:600])
    show(f"vnstock {src} quote VNINDEX", lambda: q("VNINDEX"))
    show(f"vnstock {src} quote VN30", lambda: q("VN30"))
    show(f"vnstock {src} quote VN100", lambda: q("VN100"))
    def lst(src=src):
        from vnstock import Listing
        l = Listing(source=src)
        out = [str([m for m in dir(l) if not m.startswith('_')])]
        for meth, args in (("symbols_by_exchange", ()), ("symbols_by_group", ("VN30",)), ("symbols_by_group", ("VN100",)), ("symbols_by_group", ("HOSE",)), ("symbols_by_industries", ())):
            try:
                r = getattr(l, meth)(*args)
                out.append(f"{meth}{args}: shape={getattr(r,'shape',None)} cols={list(getattr(r,'columns',[]))}\n{r.head(4).to_string() if hasattr(r,'head') else r}")
            except Exception as e:
                out.append(f"{meth}{args} FAILED {type(e).__name__}: {str(e)[:200]}")
        return "\n".join(out)
    show(f"vnstock {src} listing", lst)
    def comp(src=src):
        from vnstock import Company
        c = Company(symbol="VIC", source=src)
        out = [str([m for m in dir(c) if not m.startswith('_')])]
        for meth in ("overview", "capital_history", "events", "trading_stats", "ratio_summary"):
            try:
                r = getattr(c, meth)()
                out.append(f"{meth}: shape={getattr(r,'shape',None)} cols={list(getattr(r,'columns',[]))}\n{r.head(8).to_string() if hasattr(r,'head') else r}")
            except Exception as e:
                out.append(f"{meth} FAILED {type(e).__name__}: {str(e)[:200]}")
        return "\n".join(out)
    show(f"vnstock {src} company VIC", comp)

def board():
    from vnstock import Trading
    df = Trading(source="KBS").price_board(["VIC", "VHM", "VPL", "FPT"])
    return f"{df.shape} cols={list(df.columns)}\n{df.to_string()}"
show("vnstock KBS price_board", board)
