#!/usr/bin/env python3
"""Tải dữ liệu thị trường (HOSE) về kho dữ liệu trong repo: data/store/.

Nguồn chính: API công khai của VNDirect (api-finfo.vndirect.com.vn).
Nguồn phụ : KBS, DNSE (danh sách rổ VN30/VN100, chỉ số dự phòng).

Kho dữ liệu chỉ ghi thêm (append) theo tháng nên lịch sử đã tải không bị mất khi nguồn hỏng.
"""
import argparse, csv, datetime as dt, io, json, os, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "data", "store")
SECTOR_FILE = os.path.join(ROOT, "data", "sectors_fiinpro.csv")
VND = "https://api-finfo.vndirect.com.vn/v4"
KBS = "https://kbbuddywts.kbsec.com.vn/iis-server/investment"
DNSE = "https://services.entrade.com.vn/chart-api/v2/ohlcs"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept": "application/json, text/plain, */*"}
INDEXES = ["VNINDEX", "VN30", "VN100"]
ICT = dt.timezone(dt.timedelta(hours=7))
_local = threading.local()


def sess():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update(UA)
    return _local.s


def get_json(url, tries=5, **kw):
    err = None
    for i in range(tries):
        try:
            r = sess().get(url, timeout=40, **kw)
            if r.status_code == 200:
                return r.json()
            err = f"HTTP {r.status_code}: {r.text[:120]}"
        except Exception as e:  # noqa
            err = f"{type(e).__name__}: {e}"
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{url} -> {err}")


def vnd_all(path, q, sort, size=2000):
    """Đọc hết các trang của một truy vấn VNDirect."""
    out, page = [], 1
    while True:
        d = get_json(f"{VND}/{path}?sort={sort}&q={q}&size={size}&page={page}")
        rows = d.get("data") or []
        out.extend(rows)
        if page >= int(d.get("totalPages") or 1) or not rows:
            return out
        page += 1


# ---------------------------------------------------------------- universe
def read_sector_file():
    with open(SECTOR_FILE, encoding="utf-8-sig") as f:
        return {r["ma"].strip().upper(): r for r in csv.DictReader(f)}


def listed_hose():
    rows = vnd_all("stocks", "type:STOCK~status:LISTED~floor:HOSE", "code:asc", 1000)
    return {r["code"]: r for r in rows if len(r.get("code", "")) == 3}


def icb_l2_map():
    d = get_json(f"{VND}/industry_classification?q=industryLevel:2&size=100")
    m = {}
    for r in d.get("data", []):
        for c in (r.get("codeList") or "").split(","):
            m[c.strip()] = r.get("vietnameseName")
    return m


def index_members():
    out = {}
    for name, grp in (("VN30", "30"), ("VN100", "100")):
        try:
            d = get_json(f"{KBS}/index/{grp}/stocks", tries=3)
            codes = sorted(d.get("data") or [])
            if len(codes) >= 25:
                out[name] = codes
        except Exception as e:  # noqa
            print(f"  ! KBS {name}: {e}")
    if "VN30" not in out:
        try:
            rows = vnd_all("stocks", "indexCode:VN30", "code:asc", 100)
            out["VN30"] = sorted(r["code"] for r in rows)
        except Exception as e:  # noqa
            print(f"  ! VND VN30: {e}")
    return out


# ---------------------------------------------------------------- per-code fetch
def fetch_prices(code, start):
    rows = vnd_all("stock_prices", f"code:{code}~date:gte:{start}", "date:asc")
    out = {}
    for r in rows:
        if r.get("close") in (None, 0):
            continue
        val = (r.get("nmValue") or 0) + (r.get("ptValue") or 0)
        fl = {"HOSE": "H", "HNX": "N", "UPCOM": "U"}.get(r.get("floor"), "O")
        out[r["date"]] = [fl, r["close"], r.get("basicPrice") or "", r.get("ceilingPrice") or "", r.get("floorPrice") or "",
                          round(val / 1e9, 3)]
    return out


def fetch_mcap(code, start):
    rows = vnd_all("ratios", f"code:{code}~itemCode:51003~reportDate:gte:{start}", "reportDate:asc")
    return {r["reportDate"]: round(r["value"] / 1e9, 2) for r in rows if r.get("value")}


def fetch_events(code, start):
    rows = vnd_all("events", f"code:{code}~locale:VN~effectiveDate:gte:{start}", "effectiveDate:asc", 500)
    keep = ("code", "type", "typeDesc", "note", "effectiveDate", "dividend", "ratio", "numberOfShares", "price", "divYear", "period")
    return [{k: r[k] for k in keep if k in r} for r in rows]


def fetch_index(code, start):
    try:
        rows = vnd_all("vnmarket_prices", f"code:{code}~date:gte:{start}", "date:asc")
        out = {r["date"]: r["close"] for r in rows if r.get("close")}
        if out:
            return out
    except Exception as e:  # noqa
        print(f"  ! VND index {code}: {e}")
    # dự phòng: DNSE
    t0 = int(dt.datetime.fromisoformat(start).replace(tzinfo=ICT).timestamp())
    d = get_json(f"{DNSE}/index?from={t0}&to={int(time.time())}&symbol={code}&resolution=1D")
    return {dt.datetime.fromtimestamp(t, ICT).date().isoformat(): c for t, c in zip(d["t"], d["c"])}


# ---------------------------------------------------------------- store
PX_HEADER = ["date", "code", "fl", "close", "ref", "ceil", "floor", "value_bn", "mcap_bn"]


def month_path(ym):
    return os.path.join(STORE, "px", f"{ym}.csv")


def load_month(ym):
    p = month_path(ym)
    d = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for r in csv.reader(f):
                if r and r[0] != "date":
                    d[(r[0], r[1])] = r[2:]
    return d


def fmt(v):
    if v == "" or v is None:
        return ""
    s = f"{float(v):.3f}".rstrip("0").rstrip(".")
    return s


def save_month(ym, d):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(PX_HEADER)
    for k in sorted(d):
        w.writerow(list(k) + d[k])
    txt = buf.getvalue()
    p = month_path(ym)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if os.path.exists(p) and open(p, encoding="utf-8").read() == txt:
        return False
    with open(p, "w", encoding="utf-8") as f:
        f.write(txt)
    return True


def read_json(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa
        return default


def write_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01", help="ngày bắt đầu khi tải toàn bộ")
    ap.add_argument("--full", action="store_true", help="tải lại toàn bộ lịch sử")
    ap.add_argument("--lookback", type=int, default=12, help="số ngày tải lại khi cập nhật")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--events", action="store_true", help="tải lại toàn bộ sự kiện quyền")
    a = ap.parse_args()

    meta_p = os.path.join(STORE, "meta.json")
    meta = read_json(meta_p, {})
    now = dt.datetime.now(ICT)
    today = now.date().isoformat()
    session_closed = now.hour * 60 + now.minute >= 15 * 60 + 5
    last = meta.get("last_date")
    full = a.full or not last
    start = a.start if full else (dt.date.fromisoformat(last) - dt.timedelta(days=a.lookback)).isoformat()
    print(f"[{now:%Y-%m-%d %H:%M} ICT] mode={'FULL' if full else 'UPDATE'} start={start}")

    sectors = read_sector_file()
    try:
        listed = listed_hose()
    except Exception as e:  # noqa
        print("  ! danh sách HOSE lỗi:", e)
        listed = {}
    known = set(meta.get("codes", [])) | set(sectors)
    new_codes = sorted(c for c in listed if c not in known)
    codes = sorted(known | set(listed))
    print(f"universe: {len(codes)} mã (file ngành {len(sectors)}, niêm yết theo VND {len(listed)}, mới {new_codes})")

    # ---- prices + mcap
    def work(code):
        s = a.start if (full or code in new_codes) else start
        res = {"code": code}
        try:
            res["px"] = fetch_prices(code, s)
        except Exception as e:  # noqa
            res["err_px"] = str(e)
        try:
            res["mc"] = fetch_mcap(code, s)
        except Exception as e:  # noqa
            res["err_mc"] = str(e)
        if full or a.events or code in new_codes:
            try:
                res["ev"] = fetch_events(code, a.start)
            except Exception as e:  # noqa
                res["err_ev"] = str(e)
        return res

    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        results = list(ex.map(work, codes))
    print(f"fetched {len(results)} codes in {time.time()-t0:.0f}s")
    errs = [(r["code"], k, r[k]) for r in results for k in r if k.startswith("err_")]
    for e in errs[:20]:
        print("  ! ", e)
    n_px_err = sum(1 for e in errs if e[1] == "err_px")
    if n_px_err > len(codes) * 0.2:
        print(f"QUÁ NHIỀU LỖI GIÁ ({n_px_err}/{len(codes)}) - dừng, không ghi kho dữ liệu")
        sys.exit(2)

    by_month = {}
    max_date = last or ""
    n_rows = 0
    for r in results:
        px, mc = r.get("px") or {}, r.get("mc") or {}
        for d, v in px.items():
            if d == today and not session_closed:
                continue  # phiên chưa đóng cửa
            ym = d[:7]
            if ym not in by_month:
                by_month[ym] = load_month(ym)
            old = by_month[ym].get((d, r["code"]))
            m = mc.get(d)
            if m is None and old and old[-1] != "":
                m = old[-1]
            by_month[ym][(d, r["code"])] = [v[0]] + [fmt(x) for x in v[1:]] + [fmt(m) if m is not None else ""]
            n_rows += 1
            if d > max_date:
                max_date = d
    changed = [ym for ym in sorted(by_month) if save_month(ym, by_month[ym])]
    print(f"rows={n_rows} months changed={len(changed)} last_date={max_date}")

    # ---- events
    ev_p = os.path.join(STORE, "events.json")
    events = read_json(ev_p, {})
    for r in results:
        if "ev" in r:
            events[r["code"]] = r["ev"]
    if not (full or a.events):
        # cập nhật sự kiện gần đây cho mọi mã bằng một truy vấn chung
        try:
            rows = vnd_all("events", f"locale:VN~effectiveDate:gte:{start}", "effectiveDate:asc", 1000)
            keep = ("code", "type", "typeDesc", "note", "effectiveDate", "dividend", "ratio", "numberOfShares", "price", "divYear", "period")
            cs = set(codes)
            for x in rows:
                c = x.get("code")
                if c in cs:
                    e = {k: x[k] for k in keep if k in x}
                    lst = events.setdefault(c, [])
                    if e not in lst:
                        lst.append(e)
        except Exception as e:  # noqa
            print("  ! events update:", e)
    write_json(ev_p, events)

    # ---- indexes
    for ix in INDEXES:
        p = os.path.join(STORE, "index", f"{ix}.csv")
        cur = {}
        if os.path.exists(p):
            with open(p) as f:
                cur = {r[0]: r[1] for r in csv.reader(f) if r and r[0] != "date"}
        try:
            new = fetch_index(ix, a.start if full else start)
        except Exception as e:  # noqa
            print(f"  ! index {ix}: {e}")
            new = {}
        for d, v in new.items():
            if d == today and not session_closed:
                continue
            cur[d] = fmt(v)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("date,close\n" + "".join(f"{d},{cur[d]}\n" for d in sorted(cur)))
        print(f"index {ix}: {len(cur)} phiên, mới nhất {max(cur) if cur else None}")

    # ---- meta
    members = index_members()
    for k in ("VN30", "VN100"):
        if k in members:
            meta[k] = members[k]
    try:
        icb = icb_l2_map()
        meta["icb_l2"] = {c: icb.get(c) for c in codes if icb.get(c)}
    except Exception as e:  # noqa
        print("  ! icb:", e)
    meta["codes"] = codes
    meta["listed"] = {c: {"name": (listed[c].get("shortName") or listed[c].get("companyName") or "").strip(),
                          "listedDate": listed[c].get("listedDate")} for c in listed} or meta.get("listed", {})
    meta["last_date"] = max_date
    meta["fetched_at"] = now.isoformat(timespec="seconds")
    meta["source"] = "VNDirect finfo API; rổ VN30/VN100: KBS"
    write_json(meta_p, meta)
    print("done.")


if __name__ == "__main__":
    main()
