#!/usr/bin/env python3
"""Tính toán từ kho dữ liệu (data/store) ra site/data.json cho trang web.

Phương pháp (tóm tắt):
- Tỷ suất sinh lời ngày của từng mã theo quy ước CHỈ SỐ GIÁ (giống VN-Index): điều chỉnh cho
  chia tách/cổ phiếu thưởng/cổ tức cổ phiếu/quyền mua, KHÔNG cộng lại cổ tức tiền mặt.
- Chỉ số ngành = bình quân gia quyền theo vốn hóa (vốn hóa phiên trước tính theo giá tham chiếu).
  Mã mới niêm yết/chuyển sàn được đưa vào từ phiên giao dịch thứ hai trên HOSE (như VN-Index).
- VN-Index không gồm Vingroup: r_ex = (r_VNIndex - w * r_Vin) / (1 - w), với r_VNIndex là chỉ số
  chính thức, w là tỷ trọng vốn hóa nhóm Vingroup trong HOSE ở phiên trước.
"""
import csv, datetime as dt, glob, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "data", "store")
OUT = os.path.join(ROOT, "site", "data.json")
VIN = ["VIC", "VHM", "VRE", "VPL"]
BASES = ["2020-03-31", "2022-03-31", "2022-11-15", "2025-04-09"]
ORDER_DATE = "2026-11-13"   # ngày chốt vốn hóa để xếp thứ tự cột ngành (15/11/2026 là Chủ nhật)
ICT = dt.timezone(dt.timedelta(hours=7))


def load():
    files = sorted(glob.glob(os.path.join(STORE, "px", "*.csv")))
    df = pd.concat((pd.read_csv(f, dtype={"code": str, "fl": str, "date": str}) for f in files), ignore_index=True)
    df = df.sort_values(["code", "date"]).reset_index(drop=True)
    idx = {}
    for name in ("VNINDEX", "VN30", "VN100"):
        s = pd.read_csv(os.path.join(STORE, "index", f"{name}.csv"), dtype={"date": str}).set_index("date")["close"]
        idx[name] = s[~s.index.duplicated(keep="last")].sort_index()
    meta = json.load(open(os.path.join(STORE, "meta.json"), encoding="utf-8"))
    try:
        events = json.load(open(os.path.join(STORE, "events.json"), encoding="utf-8"))
    except Exception:  # noqa
        events = {}
    with open(os.path.join(ROOT, "data", "sectors_fiinpro.csv"), encoding="utf-8-sig") as f:
        sectors = {r["ma"].strip().upper(): (r["nganh_l2"].strip(), r["ten"].strip()) for r in csv.DictReader(f) if r.get("ma")}
    return df, idx, meta, events, sectors


def stock_returns(df, events):
    """Thêm các cột: r_adj (đã điều chỉnh đầy đủ), r_px (quy ước chỉ số giá), inidx, B (vốn hóa cơ sở)."""
    g = df.groupby("code", sort=False)
    df["prev"] = g["close"].shift(1)
    df["pfl"] = g["fl"].shift(1)
    sh = df["mcap_bn"] / df["close"]
    df["sh"] = sh.groupby(df["code"], sort=False).ffill()
    df["sh"] = df["sh"].groupby(df["code"], sort=False).bfill()
    df["sr"] = df["sh"] / df.groupby("code", sort=False)["sh"].shift(1)
    cash, stk = {}, set()
    for c, lst in events.items():
        for e in lst:
            d = e.get("effectiveDate")
            if e.get("type") == "DIVIDEND" and e.get("dividend"):
                cash[(c, d)] = cash.get((c, d), 0.0) + float(e["dividend"]) / 1000.0
            elif e.get("type") in ("STOCKDIV", "KINDDIV", "ISSUE"):
                stk.add((c, d))
    keys = list(zip(df["code"], df["date"]))
    df["cash"] = [cash.get(k, 0.0) for k in keys]
    df["stk"] = [k in stk for k in keys]
    hose = df["fl"] == "H"
    cont = hose & (df["pfl"] == "H")
    df["f"] = df["prev"] / df["ref"]
    # Ngày mà giá tham chiếu của nguồn lỗi hàng loạt (vd 04/06/2021): dùng giá đóng cửa phiên trước
    moved = (cont & ((df["f"] - 1).abs() > 0.0015)).groupby(df["date"]).sum()
    total = cont.groupby(df["date"]).sum()
    glitch = set((moved / total.replace(0, np.nan))[lambda s: s > 0.2].index)
    isg = df["date"].isin(glitch) & (df["cash"] == 0) & (~df["stk"])
    ref = df["ref"].where(df["ref"] > 0)
    ref = ref.where(~(isg & cont), df["prev"])
    df["ref_eff"] = ref
    # --- r_adj
    r_h = df["close"] / ref - 1
    adjbase = (df["prev"] - df["cash"]).where(df["prev"] > df["cash"], df["prev"])
    srx = df["sr"].where(df["stk"] & (df["sr"] > 1.01) & (df["sr"] < 5), 1.0)
    r_n = df["close"] * srx / adjbase - 1
    # Giá tham chiếu của nguồn đôi khi sai (biến động vượt mọi biên độ): thử lần lượt các cách tính khác
    bad = cont & (r_h.abs() > 0.21)
    alt1 = df["close"] * df["sr"] / df["prev"] - 1
    alt2 = df["close"] / df["prev"] - 1
    ok1 = (df["sr"] > 1.01) & (df["sr"] < 5) & (alt1.abs() <= 0.21)
    fix = np.where(ok1, alt1, np.where(alt2.abs() <= 0.21, alt2, 0.0))
    r_h = r_h.where(~bad, fix)
    ref = ref.where(~bad, df["close"] / (1 + r_h))
    df["ref_eff"] = ref
    df["anom"] = bad
    df["r_adj"] = np.where(hose & ref.notna(), r_h, r_n)
    df.loc[df["prev"].isna() & ~hose, "r_adj"] = np.nan
    # --- cổ tức tiền mặt vào ngày GDKHQ -> quy ước chỉ số giá không cộng lại
    gap = (df["prev"] - ref).clip(lower=0)
    c = np.where(df["cash"] > 0, np.minimum(df["cash"], gap + 0.05), 0.0)
    heur = cont & (df["cash"] == 0) & (~df["stk"]) & (df["f"] > 1.0015) & (df["f"] < 1.25) & ((df["sr"] - 1).abs() < 0.003) & (~isg)
    c = np.where(heur, gap, c)
    c = np.where(cont & ~bad, c, 0.0)
    df["r_px"] = (1 + df["r_adj"]) * (1 - np.nan_to_num(c / df["prev"])) - 1
    df["inidx"] = cont & df["r_px"].notna() & df["sh"].notna() & ref.notna()
    df["B"] = np.where(df["inidx"], df["sh"] * ref, 0.0)
    return df, sorted(glitch)


def wavg_ret(x):
    """Tỷ suất sinh lời bình quân gia quyền theo ngày của một tập dòng."""
    num = (x["r_px"] * x["B"]).groupby(x["date"]).sum()
    den = x["B"].groupby(x["date"]).sum()
    return (num / den.replace(0, np.nan)), den


def level(r, dates, start=100.0):
    r = r.reindex(dates).fillna(0.0)
    r.iloc[0] = 0.0
    return (1 + r).cumprod() * start


def rnd(s, n=2):
    return [None if (v is None or not np.isfinite(v)) else round(float(v), n) for v in s]


def sma_gaps(series):
    """series: pandas Series theo thời gian; trả (close, [gap20, gap50, gap200]) theo %."""
    s = series.dropna()
    out = []
    for n in (20, 50, 200):
        if len(s) >= n:
            m = s.iloc[-n:].mean()
            out.append(round((s.iloc[-1] / m - 1) * 100, 2))
        else:
            out.append(None)
    return out


def main():
    df, idx, meta, events, sectors = load()
    df, glitch = stock_returns(df, events)
    dmin, dmax = df["date"].min(), df["date"].max()
    dates = [d for d in idx["VNINDEX"].index if d >= dmin]
    last = min(dates[-1], dmax)
    dates = [d for d in dates if d <= last]
    df = df[df["date"] <= last]
    dset = set(dates)
    H = df[df["inidx"] & df["date"].isin(dset)]

    # ---------- phân ngành (FiinPro; mã mới: tạm theo ICB công khai)
    icb = meta.get("icb_l2", {})
    vote = {}
    for c, (sec, _) in sectors.items():
        k = icb.get(c)
        if k:
            vote.setdefault(k, {}).setdefault(sec, 0)
            vote[k][sec] += 1
    icb2sec = {k: max(v, key=v.get) for k, v in vote.items()}
    live = sorted(df[(df["date"] == last) & (df["fl"] == "H")]["code"].unique())
    sec_of, pending, unknown = {}, [], []
    for c in sorted(set(df["code"])):
        if c in sectors:
            sec_of[c] = sectors[c][0]
        elif icb.get(c) in icb2sec:
            sec_of[c] = icb2sec[icb[c]]
            if c in live:
                pending.append(c)
        elif c in live:
            unknown.append(c)
    names = {c: sectors[c][1] if c in sectors else (meta.get("listed", {}).get(c, {}).get("name") or c) for c in set(df["code"])}

    # ---------- thứ tự ngành cố định theo vốn hóa ngày chốt
    order_p = os.path.join(ROOT, "data", "sector_order.json")
    if os.path.exists(order_p):
        order = json.load(open(order_p, encoding="utf-8"))["order"]
    else:
        od = max(d for d in dates if d <= ORDER_DATE)
        x = df[(df["date"] == od) & (df["fl"] == "H")].copy()
        x["sec"] = x["code"].map(sec_of)
        cap = (x["sh"] * x["close"]).groupby(x["sec"]).sum().sort_values(ascending=False)
        order = list(cap.index)
        with open(order_p, "w", encoding="utf-8") as f:
            json.dump({"date": od, "note": "Thứ tự ngành theo tổng vốn hóa giảm dần, chốt một lần",
                       "order": order, "mcap_bn": {k: round(float(v), 0) for k, v in cap.items()}}, f, ensure_ascii=False, indent=1)
    for s in sorted(set(sec_of.values())):
        if s not in order:
            order.append(s)

    # ---------- chỉ số ngành
    Hs = H.assign(sec=H["code"].map(sec_of))
    sec_series = []
    lastrows = df[(df["date"] == last) & (df["fl"] == "H")].assign(sec=lambda x: x["code"].map(sec_of))
    capnow = (lastrows["sh"] * lastrows["close"]).groupby(lastrows["sec"]).sum()
    cntnow = lastrows.groupby("sec")["code"].count()

    def add_series(name, rows, extra=False, parent=None):
        r, _ = wavg_ret(rows)
        lv = level(r, dates)
        codes = set(rows["code"])
        lr = lastrows[lastrows["code"].isin(codes)]
        sec_series.append({"name": name, "extra": extra, "parent": parent, "n": int(len(lr)),
                           "mcap": round(float((lr["sh"] * lr["close"]).sum()), 0), "s": rnd(lv, 3)})
        return lv

    sec_levels = {}
    for s in order:
        sec_levels[s] = add_series(s, Hs[Hs["sec"] == s])
    vin_sec = {}
    for c in VIN:
        if c in sec_of:
            vin_sec.setdefault(sec_of[c], []).append(c)
    for s, cs in vin_sec.items():
        nm = f"{s} (không gồm {', '.join(cs)})"
        sec_levels[nm] = add_series(nm, Hs[(Hs["sec"] == s) & (~Hs["code"].isin(cs))], extra=True, parent=s)

    # ---------- VN-Index không gồm Vingroup
    off = idx["VNINDEX"].reindex(dates)
    r_off = off.pct_change()
    r_all, B_all = wavg_ret(H)
    r_vin, B_vin = wavg_ret(H[H["code"].isin(VIN)])
    w = (B_vin / B_all).reindex(dates).fillna(0.0)
    rv = r_vin.reindex(dates).fillna(0.0)
    r_ex = (r_off - w * rv) / (1 - w)
    exvin = level(r_ex, dates, start=float(off.iloc[0]))
    vin_lv = level(r_vin, dates)
    rep = level(r_all, dates, start=float(off.iloc[0]))
    lastH = df[(df["date"] == last) & (df["fl"] == "H")]
    capH = float((lastH["sh"] * lastH["close"]).sum())
    vin_now = []
    for c in VIN:
        x = lastH[lastH["code"] == c]
        if len(x):
            m = float((x["sh"] * x["close"]).iloc[0])
            vin_now.append({"code": c, "mcap": round(m, 0), "w": round(m / capH * 100, 2)})
    # sai số tái lập theo năm
    track = []
    for y in sorted({d[:4] for d in dates}):
        ds = [d for d in dates if d[:4] == y]
        a = float((1 + r_all.reindex(ds).fillna(0)).prod() - 1)
        b = float((1 + r_off.reindex(ds).fillna(0)).prod() - 1)
        track.append({"y": y, "rep": round(a * 100, 2), "off": round(b * 100, 2)})

    # ---------- SMA
    codes_live = [c for c in live if c in sec_of]
    D = df[df["code"].isin(codes_live)]
    lastclose = D[D["date"] == last].set_index("code")["close"]
    stocks = []
    sec_index = {s: i for i, s in enumerate(order)}
    growth = (1 + D["r_adj"].fillna(0.0))
    # hệ số điều chỉnh lùi: adj(t) = close(t) * prod_{u>t} (ref_u/prev_u ...) -> dùng tích lũy r_adj
    cum = growth.groupby(D["code"], sort=False).cumprod()
    endcum = cum.groupby(D["code"], sort=False).transform("last")
    adj = D["code"].map(lastclose) * cum / endcum
    D = D.assign(adj=adj)
    lastrow = D[D["date"] == last].set_index("code")
    for c, x in D.groupby("code", sort=False):
        a = x["adj"].tail(260)
        g = sma_gaps(a)
        lr = lastrow.loc[c]
        stocks.append({"c": c, "n": names.get(c, c), "s": sec_index[sec_of[c]], "p": round(float(lr["close"]), 2),
                       "m": round(float(lr["sh"] * lr["close"]), 0) if np.isfinite(lr["sh"]) else None, "g": g})
    idx_sma = []
    for nm, lab in (("VNINDEX", "VN-Index"), ("VN30", "VN30"), ("VN100", "VN100")):
        s = idx[nm].reindex(dates)
        idx_sma.append({"name": lab, "close": round(float(s.dropna().iloc[-1]), 2), "g": sma_gaps(s)})
    idx_sma.append({"name": "VN-Index không gồm Vingroup", "close": round(float(exvin.iloc[-1]), 2), "g": sma_gaps(exvin)})
    sec_sma = [{"name": s, "g": sma_gaps(sec_levels[s])} for s in order]

    # ---------- Money flow
    def dmy(d):
        return f"{d[8:10]}/{d[5:7]}/{d[:4]}"

    def period(ds, kind):
        if not ds:
            return None
        x = df[df["date"].isin(ds) & df["code"].isin(codes_live) & (df["fl"] == "H")]
        end = x[x["date"] == ds[-1]].set_index("code")
        if kind == "d":
            pct = (end["close"] / end["ref_eff"] - 1) * 100
            flag = np.where(end["close"] >= end["ceil"] - 1e-9, 1, np.where(end["close"] <= end["floor"] + 1e-9, -1, 0))
            flag = pd.Series(flag, index=end.index).where(end["ceil"].notna() & (pct.abs() > 0.5), 0)
            rows = {c: [round(float(end.at[c, "close"]), 2), round(float(pct[c]), 2), int(flag[c])] for c in end.index if np.isfinite(pct[c])}
            label = dmy(ds[-1])
        else:
            ret = ((1 + x["r_adj"].fillna(0.0)).groupby(x["code"]).prod() - 1) * 100
            rows = {c: [round(float(end.at[c, "close"]), 2), round(float(ret[c]), 2), 0] for c in end.index if c in ret.index}
            label = f"{dmy(ds[0])} – {dmy(ds[-1])}"
        return {"label": label, "n": len(ds), "from": ds[0], "to": ds[-1], "rows": rows}

    # Ngày gần nhất, 5 phiên gần nhất (1 tuần), 22 phiên gần nhất (1 tháng)
    flow = {"d": period([last], "d"), "w": period(dates[-5:], "w"), "m": period(dates[-22:], "m")}

    out = {
        "meta": {
            "last_date": last, "generated_at": dt.datetime.now(ICT).isoformat(timespec="minutes"),
            "fetched_at": meta.get("fetched_at"), "source": meta.get("source"),
            "bases": [b for b in BASES if b in dset], "n_stocks": len(codes_live),
            "pending": [{"c": c, "sec": sec_of[c], "n": names.get(c, c)} for c in pending],
            "unknown": unknown, "no_data": sorted(c for c in sectors if c not in set(live)),
            "glitch_dates": glitch, "anomalies": int(df["anom"].sum()), "track": track, "vin": vin_now, "vin_codes": VIN,
            "order_date": ORDER_DATE,
        },
        "dates": dates,
        "idx": {"VNINDEX": rnd(off), "VN30": rnd(idx["VN30"].reindex(dates).ffill()), "VN100": rnd(idx["VN100"].reindex(dates).ffill()),
                "EXVIN": rnd(exvin), "VIN": rnd(vin_lv, 3), "VINW": rnd(w * 100, 2), "REP": rnd(rep)},
        "sectors": sec_series,
        "order": order,
        "sma": {"idx": idx_sma, "sec": sec_sma},
        "stocks": stocks,
        "vn30": [c for c in meta.get("VN30", []) if c in set(codes_live)],
        "vn100": [c for c in meta.get("VN100", []) if c in set(codes_live)],
        "flow": flow,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"last={last} dates={len(dates)} stocks={len(codes_live)} sectors={len(order)} pending={pending} unknown={unknown}")
    print(f"VNINDEX {off.iloc[-1]:.2f} | EXVIN {exvin.iloc[-1]:.2f} | tỷ trọng Vin {w.iloc[-1]*100:.2f}% | glitch {glitch}")
    print("track:", track)
    print(f"data.json {os.path.getsize(OUT)/1e6:.2f} MB")


if __name__ == "__main__":
    main()
