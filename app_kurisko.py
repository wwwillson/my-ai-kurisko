import streamlit as st
import yfinance as yf
import pandas as pd
import mplfinance as mpf
import numpy as np
from streamlit_autorefresh import st_autorefresh
import requests # 用於發送 Line 通知

# ==========================================
# 1. 頁面與自動刷新設定
# ==========================================
st.set_page_config(layout="wide", page_title="John Kurisko 短線監控")
st.title("🛡️ John Kurisko 短線監控 (自動刷新版)")

# --- 自動刷新邏輯 ---
# 在側邊欄增加一個開關
with st.sidebar:
    st.markdown("---")
    st.header("⚙️ 監控設定")
    enable_refresh = st.checkbox("開啟自動刷新 (每60秒)", value=False)
    
    # Line Notify 設定 (選用)
    line_token = st.text_input("Line Notify Token (選填)", type="password")

if enable_refresh:
    # 設定每 60,000 毫秒 (60秒) 刷新一次
    count = st_autorefresh(interval=60000, limit=None, key="fizzbuzz")

# ==========================================
# 2. 函數定義區
# ==========================================

# 發送 Line 通知的函數
def send_line_notify(token, msg):
    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": "Bearer " + token}
    payload = {"message": msg}
    try:
        requests.post(url, headers=headers, data=payload)
    except:
        pass # 發送失敗也不要讓程式崩潰

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def calculate_stoch(df, k_period, d_period, smooth_k):
    low_min = df['Low'].rolling(window=k_period).min()
    high_max = df['High'].rolling(window=k_period).max()
    denom = high_max - low_min
    denom = denom.replace(0, 0.000001) 
    k_fast = 100 * ((df['Close'] - low_min) / denom)
    k_full = k_fast.rolling(window=smooth_k).mean()
    return k_full

def get_data(symbol, interval, ema_params):
    try:
        period = "1mo" if interval == "15m" else "6mo"
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        if df.empty: return None, "No Data"
        if df.index.tz is not None: df.index = df.index.tz_localize(None)
        
        df = df[df['Close'] > 0].dropna()

        # 指標計算
        df['EMA_20'] = calculate_ema(df['Close'], ema_params[0])
        df['EMA_50'] = calculate_ema(df['Close'], ema_params[1])
        df['EMA_200'] = calculate_ema(df['Close'], ema_params[2])

        df['Stoch1_K'] = calculate_stoch(df, 9, 1, 3)
        df['Stoch2_K'] = calculate_stoch(df, 14, 1, 3)
        df['Stoch3_K'] = calculate_stoch(df, 44, 1, 4)
        df['Stoch4_K'] = calculate_stoch(df, 60, 1, 10)

        df = df.dropna()
        return df, None
    except Exception as e:
        return None, str(e)

def analyze_market(df, slow_threshold):
    curr = df.iloc[-1]
    trend = "震盪/不明"
    if curr['Close'] > curr['EMA_50'] and curr['Close'] > curr['EMA_200']:
        trend = "🟢 強勢多頭"
    elif curr['Close'] < curr['EMA_50'] and curr['Close'] < curr['EMA_200']:
        trend = "🔴 空頭趨勢"
    
    signal = None # 預設無訊號
    signal_msg = "無特殊訊號"
    
    is_uptrend = curr['Close'] > curr['EMA_200']
    
    if is_uptrend:
        if curr['Stoch4_K'] > slow_threshold: 
            if curr['Stoch1_K'] < 25: 
                signal = "BUY"
                signal_msg = "🔥 牛旗買點出現！(強勢回調)"
            elif curr['Stoch1_K'] < 50:
                signal_msg = "👀 觀察中 (正在回調)"
    
    return trend, signal, signal_msg, curr

# ==========================================
# 3. 主畫面與執行
# ==========================================

with st.sidebar:
    # 參數設定區
    symbol = st.text_input("監控代號", value="BTC-USD")
    timeframe = st.selectbox("週期", ["15m", "1h"], index=0)
    ema_fast = st.number_input("EMA 快", value=20)
    ema_mid = st.number_input("EMA 中", value=50)
    ema_slow = st.number_input("EMA 慢", value=200)
    slow_stoch_threshold = st.slider("慢速 Stoch 強勢區 (>)", 50, 90, 80)

# 自動執行或手動按鈕
# 如果開啟自動刷新，我們就直接執行；否則顯示按鈕
should_run = True if enable_refresh else st.button("🚀 手動分析")

if should_run:
    with st.spinner("監控中..."):
        df, err = get_data(symbol, timeframe, [ema_fast, ema_mid, ema_slow])
        
        if err:
            st.error(err)
        elif df is not None:
            trend_str, signal_type, signal_str, curr_data = analyze_market(df, slow_stoch_threshold)
            
            # --- 4. 通知系統 ---
            if signal_type == "BUY":
                st.success(f"🔔 觸發訊號：{symbol} {signal_str}")
                
                # A. 網頁端通知 (Toast)
                st.toast(f"🔥 {symbol} 出現買點！", icon="💰")
                
                # B. 音效通知 (HTML5 Audio) - 有訊號時播放提示音
                # 這裡使用一個免費的線上提示音效連結
                audio_html = """
                    <audio autoplay>
                    <source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" type="audio/mpeg">
                    </audio>
                    """
                st.markdown(audio_html, unsafe_allow_html=True)
                
                # C. Line Notify 通知
                if line_token:
                    msg = f"\n【John Kurisko 訊號】\n標的: {symbol}\n週期: {timeframe}\n現價: {curr_data['Close']:.2f}\n狀態: {signal_str}"
                    send_line_notify(line_token, msg)
            
            else:
                # 無訊號時顯示一般狀態
                st.info(f"監控中... 最後更新: {pd.Timestamp.now().strftime('%H:%M:%S')}")

            # --- 5. 數據與圖表顯示 ---
            c1, c2, c3 = st.columns(3)
            c1.metric("價格", f"{curr_data['Close']:.2f}")
            c1.info(f"趨勢: {trend_str}")
            c2.metric("快速 Stoch (9,3)", f"{curr_data['Stoch1_K']:.1f}")
            c3.metric("慢速 Stoch (60,10)", f"{curr_data['Stoch4_K']:.1f}")

            plot_df = df.tail(60)
            apds = [
                mpf.make_addplot(plot_df['EMA_20'], color='cyan', width=1.5),
                mpf.make_addplot(plot_df['EMA_50'], color='orange', width=2.0),
                mpf.make_addplot(plot_df['EMA_200'], color='white', width=2.5),
                mpf.make_addplot(plot_df['Stoch1_K'], panel=1, color='#FF3333', width=1.5, ylabel='Stoch'),
                mpf.make_addplot(plot_df['Stoch4_K'], panel=1, color='#33FF33', width=2.0),
            ]
            
            fig, ax = mpf.plot(
                plot_df, type='candle', style='yahoo', addplot=apds,
                title=f"{symbol} ({timeframe})", returnfig=True, volume=False,
                panel_ratios=(7, 3), tight_layout=True,
                hlines=dict(hlines=[20, 80], colors=['gray', 'gray'], linestyle='--', linewidths=1.0)
            )
            st.pyplot(fig)
