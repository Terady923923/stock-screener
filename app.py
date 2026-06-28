import io
import time
from datetime import datetime

import pandas as pd
import streamlit as st
import yfinance as yf

JPX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"

st.set_page_config(page_title="MA Cross Screener", layout="wide")
st.title("東証 移動平均線スクリーナー")
st.caption("条件：5日線が25日線を直近5営業日以内に上抜け、かつ最新終値が5日線より下")

@st.cache_data(ttl=24*60*60)
def load_jpx_list():
    df = pd.read_excel(JPX_URL)
    # JPX file column names are Japanese; normalize common columns.
    code_col = None
    name_col = None
    market_col = None
    for c in df.columns:
        cs = str(c)
        if "コード" in cs:
            code_col = c
        if "銘柄名" in cs:
            name_col = c
        if "市場" in cs or "区分" in cs:
            market_col = c
    if code_col is None:
        raise ValueError("JPX銘柄コード列を取得できませんでした。")
    out = pd.DataFrame()
    out["code"] = df[code_col].astype(str).str.extract(r"(\d{4})")[0]
    out["name"] = df[name_col].astype(str) if name_col is not None else ""
    out["market"] = df[market_col].astype(str) if market_col is not None else ""
    out = out.dropna(subset=["code"]).drop_duplicates("code")
    return out


def is_hit(hist: pd.DataFrame, lookback_days: int):
    if hist is None or hist.empty or len(hist) < 30:
        return None
    close = hist["Close"].dropna()
    if len(close) < 30:
        return None
    ma5 = close.rolling(5).mean()
    ma25 = close.rolling(25).mean()
    crossed = (ma5 > ma25) & (ma5.shift(1) <= ma25.shift(1))
    recent_cross = crossed.tail(lookback_days).any()
    latest_close = float(close.iloc[-1])
    latest_ma5 = float(ma5.iloc[-1])
    latest_ma25 = float(ma25.iloc[-1])
    if recent_cross and latest_close < latest_ma5:
        cross_date = crossed[crossed].index[-1].strftime("%Y-%m-%d")
        return {
            "latest_close": round(latest_close, 2),
            "ma5": round(latest_ma5, 2),
            "ma25": round(latest_ma25, 2),
            "cross_date": cross_date,
            "gap_to_ma5_%": round((latest_close / latest_ma5 - 1) * 100, 2),
        }
    return None

with st.sidebar:
    st.header("設定")
    lookback_days = st.slider("GC判定：直近何営業日以内", 1, 10, 5)
    max_stocks = st.number_input("検索する最大銘柄数（最初は300推奨）", min_value=50, max_value=4000, value=300, step=50)
    sleep_sec = st.slider("取得間隔（秒）", 0.0, 1.0, 0.05, 0.05)
    market_filter = st.multiselect("市場で絞る（空欄なら全市場）", ["プライム", "スタンダード", "グロース"])

st.info("初回は時間がかかります。まずは300銘柄で試して、動いたら最大数を増やしてください。")

try:
    stocks = load_jpx_list()
    if market_filter:
        pattern = "|".join(market_filter)
        stocks = stocks[stocks["market"].str.contains(pattern, na=False)]
    stocks = stocks.head(int(max_stocks)).copy()
    st.write(f"対象銘柄数：{len(stocks)}")
except Exception as e:
    st.error(f"銘柄リスト取得エラー：{e}")
    st.stop()

if st.button("スクリーニング開始", type="primary"):
    progress = st.progress(0)
    status = st.empty()
    hits = []

    for i, row in enumerate(stocks.itertuples(index=False), start=1):
        code = row.code
        ticker = f"{code}.T"
        status.write(f"検索中：{i}/{len(stocks)}　{code} {row.name}")
        try:
            hist = yf.download(ticker, period="3mo", interval="1d", progress=False, auto_adjust=False)
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            hit = is_hit(hist, int(lookback_days))
            if hit:
                hits.append({
                    "code": code,
                    "name": row.name,
                    "market": row.market,
                    **hit,
                    "yahoo_url": f"https://finance.yahoo.co.jp/quote/{code}.T/chart",
                    "kabutan_url": f"https://kabutan.jp/stock/chart?code={code}",
                })
        except Exception:
            pass
        progress.progress(i / len(stocks))
        if sleep_sec:
            time.sleep(float(sleep_sec))

    result = pd.DataFrame(hits)
    st.subheader("結果")
    if result.empty:
        st.warning("該当銘柄は見つかりませんでした。対象銘柄数や市場を変えて再実行してください。")
    else:
        st.dataframe(result, use_container_width=True)
        csv = result.to_csv(index=False).encode("utf-8-sig")
        st.download_button("CSVダウンロード", csv, file_name=f"ma_cross_screen_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", mime="text/csv")
