import streamlit as st
import yfinance as yf
import pandas as pd
import mplfinance as mpf
import numpy as np
from streamlit_autorefresh import st_autorefresh
import requests

# ==========================================
# 1. 頁面設定
# ==========================================
st.set_page_config(layout="wide", page_title="John Kurisko 專業操盤系統")
st.title("🛡️ John Kurisko 專業操盤系統 (深色圖表優化版)")

with st.expander("📖 策略邏輯與參數定義", expanded=False):
    st.markdown("""
    **策略 A (反轉)**：四組 Stochastics 同步進入高/低檔並發生背離。
    **策略 B (趨勢)**：EMA 排列正確，配合 Stochastics 動能回調。
    """)

# ==========================================
# 2. 系統設定
# ==========================================
with st.sidebar:
    st.header("⚙️ 參數設定")
    symbol = st.text_input("監控代號", value="BTC-USD")
    timeframe = st.selectbox("週期", ["15m", "1h", "4h"], index=0)
    
    st.markdown("---")
    enable_refresh = st.checkbox("開啟自動刷新 (60s)", value=False)
    line_token = st.text_input("Line Token (選填)", type="password")

if enable_refresh:
    count = st_autorefresh(interval=60000, limit=None, key="refresh_counter")

# ==========================================
# 3. 運算函數
# ==========================================

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def calculate_stoch_kd(df, k_period, smooth_k, smooth_d):
    # 確保數據足夠
    low_min = df['Low'].rolling(window=k_period).min()
    high_max = df['High'].rolling(window=k_period).max()
    denom = high_max - low_min
    denom = denom.replace(0, 0.000001)
    
    r_k = 100 * ((df['Close'] - low_min) / denom)
    k_full = r_k.rolling(window=smooth_k).mean()
    d_full = k_full.rolling(window=smooth_d).mean()
    return k_full, d_full

def get_data(symbol, interval):
    try:
        # --- 關鍵修正：極大化數據抓取量 ---
        # 為了確保 EMA 200 一定算得出來，我們要抓 yfinance 允許的最大值
        # 15m: max 60 days
        # 1h: max 730 days
        period = "5d" 
        if interval == "15m": period = "60d" 
        elif interval == "1h": period = "730d" # 2年
        elif interval == "4h": period = "730d" # 2年
        
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        if df.empty: return None, "No Data"
        if df.index.tz is not None: df.index = df.index.tz_localize(None)
        
        df = df[df['Close'] > 0].dropna()

        # --- 計算指標 (在裁切數據前計算) ---
        df['EMA_20'] = calculate_ema(df['Close'], 20)
        df['EMA_50'] = calculate_ema(df['Close'], 50)
        df['EMA_200'] = calculate_ema(df['Close'], 200) # 確保有足夠歷史數據
        
        # 4組 Stochastics
        df['K1'], df['D1'] = calculate_stoch_kd(df, 9, 3, 1)
        df['K2'], df['D2'] = calculate_stoch_kd(df, 14, 3, 1)
        df['K3'], df['D3'] = calculate_stoch_kd(df, 44, 4, 1)
        df['K4'], df['D4'] = calculate_stoch_kd(df, 60, 10, 1)

        df = df.dropna()
        return df, None
    except Exception as e:
        return None, str(e)

# ==========================================
# 4. 訊號分析
# ==========================================

def analyze_signals(df):
    curr = df.iloc[-1]
    lookback = 40 
    past_df = df.iloc[-lookback:-1] 
    
    signal_type = None
    strategy_name = ""
    reason = ""
    div_points = None 

    # --- 策略 A: 四重共振背離 ---
    all_oversold = (curr['K1'] < 35) and (curr['K2'] < 35) and (curr['K3'] < 35) and (curr['K4'] < 35)
    all_overbought = (curr['K1'] > 65) and (curr['K2'] > 65) and (curr['K3'] > 65) and (curr['K4'] > 65)

    if all_oversold:
        min_price_idx = past_df['Low'].idxmin()
        min_price = past_df.loc[min_price_idx, 'Low']
        stoch_at_min = df.loc[min_price_idx, 'K1']
        
        if (curr['Low'] < min_price) and (curr['K1'] > stoch_at_min):
            signal_type = "LONG"
            strategy_name = "四重共振底背離"
            reason = "4指標低檔 + 價格破底 + 指標墊高"
            div_points = [(min_price_idx, min_price), (df.index[-1], curr['Low'])]

    elif all_overbought:
        max_price_idx = past_df['High'].idxmax()
        max_price = past_df.loc[max_price_idx, 'High']
        stoch_at_max = df.loc[max_price_idx, 'K1']
        
        if (curr['High'] > max_price) and (curr['K1'] < stoch_at_max):
            signal_type = "SHORT"
            strategy_name = "四重共振頂背離"
            reason = "4指標高檔 + 價格破頂 + 指標降低"
            div_points = [(max_price_idx, max_price), (df.index[-1], curr['High'])]

    # --- 策略 B: 趨勢中繼 (含隱性背離) ---
    if signal_type is None:
        if (curr['Close'] > curr['EMA_200']) and (curr['K4'] > 50):
            if curr['K1'] < 20: 
                signal_type = "LONG"
                strategy_name = "趨勢牛旗"
                reason = "EMA多頭 + 慢速強 + 快速回調"
        elif (curr['Close'] < curr['EMA_200']) and (curr['K4'] < 50):
            if curr['K1'] > 80: 
                signal_type = "SHORT"
                strategy_name = "趨勢熊旗"
                reason = "EMA空頭 + 慢速弱 + 快速反彈"

    entry = curr['Close']
    sl = 0.0; tp = 0.0
    if signal_type == "LONG":
        sl = df['Low'].iloc[-10:].min() * 0.998
        tp = entry + (entry - sl) * 3
    elif signal_type == "SHORT":
        sl = df['High'].iloc[-10:].max() * 1.002
        tp = entry - (sl - entry) * 3

    return signal_type, strategy_name, reason, entry, sl, tp, div_points

def send_line_notify_wrapper(token, strat, symbol, direction, price):
    try:
        msg = f"\n【{strat}】\n{symbol}\n方向: {direction}\n現價: {price}"
        url = "https://notify-api.line.me/api/notify"
        headers = {"Authorization": "Bearer " + token}
        requests.post(url, headers=headers, data={"message": msg})
    except: pass

# ==========================================
# 5. 主程式與繪圖
# ==========================================
should_run = True if enable_refresh else st.button("🚀 分析最新訊號")

if should_run:
    with st.spinner("計算中..."):
        df, err = get_data(symbol, timeframe)
        
        if err:
            st.error(err)
        elif df is not None:
            # 畫圖只取最近 60-80 根，這樣 K 線才不會太擠
            plot_df = df.tail(80).copy()
            
            signal, strat_name, reason, entry, sl, tp, div_pts = analyze_signals(df)
            
            curr_price = df.iloc[-1]['Close']
            st.metric("目前價格", f"{curr_price:.2f}")
            
            if signal:
                color = "green" if signal == "LONG" else "red"
                st.markdown(f"### 🔥 訊號觸發：:{color}[{signal} - {strat_name}]")
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Entry", f"{entry:.2f}")
                c2.metric("TP (3R)", f"{tp:.2f}")
                c3.metric("SL", f"{sl:.2f}")
                
                if line_token:
                    send_line_notify_wrapper(line_token, strat_name, symbol, signal, curr_price)
            else:
                st.info("目前無明確進場訊號。")

            # --- 繪圖設定 (仿照圖片風格) ---
            # 使用 nightclouds 風格 (深色底)
            # 設定 5 個面板：0=Main, 1=Stoch1, 2=Stoch2...
            
            apds = [
                # 主圖 EMA (加粗)
                mpf.make_addplot(plot_df['EMA_20'], color='#00FFFF', width=1.5), # 青色 (20)
                mpf.make_addplot(plot_df['EMA_50'], color='#FFA500', width=2.0), # 橘色 (50)
                mpf.make_addplot(plot_df['EMA_200'], color='#9932CC', width=2.5), # 紫色 (200)
                
                # Panel 1: Stoch 9,3 (紅/粉)
                mpf.make_addplot(plot_df['K1'], panel=1, color='#FF4444', width=1.5, ylabel='9,3'),
                mpf.make_addplot(plot_df['D1'], panel=1, color='#FF9999', width=1.0),
                
                # Panel 2: Stoch 14,3 (橘/黃)
                mpf.make_addplot(plot_df['K2'], panel=2, color='#FF8800', width=1.5, ylabel='14,3'),
                mpf.make_addplot(plot_df['D2'], panel=2, color='#FFCC00', width=1.0),
                
                # Panel 3: Stoch 44,4 (藍/青)
                mpf.make_addplot(plot_df['K3'], panel=3, color='#0088FF', width=1.5, ylabel='44,4'),
                mpf.make_addplot(plot_df['D3'], panel=3, color='#00FFFF', width=1.0),
                
                # Panel 4: Stoch 60,10 (綠/亮綠)
                mpf.make_addplot(plot_df['K4'], panel=4, color='#00CC00', width=1.5, ylabel='60,10'),
                mpf.make_addplot(plot_df['D4'], panel=4, color='#66FF66', width=1.0),
            ]

            # 畫止盈止損色塊
            if signal:
                t_s = np.full(len(plot_df), tp)
                s_s = np.full(len(plot_df), sl)
                e_s = np.full(len(plot_df), entry)
                
                # 綠色獲利區 (Entry 到 TP)
                apds.append(mpf.make_addplot(t_s, color='green', width=0.5))
                apds.append(mpf.make_addplot(e_s, fill_between=dict(y1=t_s.tolist(), y2=e_s.tolist(), color='green', alpha=0.15), width=0))
                
                # 紅色虧損區 (Entry 到 SL)
                apds.append(mpf.make_addplot(s_s, color='red', width=0.5))
                apds.append(mpf.make_addplot(e_s, fill_between=dict(y1=e_s.tolist(), y2=s_s.tolist(), color='red', alpha=0.15), width=0))

            # 設定背離線
            alines_config = None
            if div_pts:
                # 確保背離線的日期在目前的繪圖範圍內
                p1_idx, p2_idx = div_pts[0], div_pts[1]
                # 簡單檢查：如果背離點非常久遠，就不畫了，避免圖表縮太小
                alines_config = dict(alines=[div_pts], colors='yellow', linewidths=2.5)

            # 自訂樣式：深色背景
            mc = mpf.make_marketcolors(up='#00ff00', down='#ff0000', inherit=True)
            s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc)

            # 繪製圖表
            # 關鍵修改：panel_ratios (主圖 : 副圖 : 副圖 : 副圖 : 副圖)
            # 設為 (3, 1, 1, 1, 1) 代表主圖佔 3份，四個副圖各佔 1份
            # 這樣副圖會有足夠的空間，不會擠在一起
            fig, ax = mpf.plot(
                plot_df, type='candle', style=s, 
                addplot=apds,
                title=f"{symbol} ({timeframe}) Quad Rotation",
                returnfig=True, volume=False, 
                panel_ratios=(3, 1, 1, 1, 1), 
                tight_layout=True,
                alines=alines_config,
                hlines=dict(hlines=[20, 80], colors=['gray', 'gray'], linestyle=':', linewidths=0.5)
            )
            st.pyplot(fig)
            
            if signal:
                st.caption("圖表說明：主圖黃線為背離線。紅綠色塊為止損止盈區間。紫色線為 200 EMA (趨勢分界)。")
