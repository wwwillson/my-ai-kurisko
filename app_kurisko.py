import streamlit as st
import yfinance as yf
import pandas as pd
import mplfinance as mpf
import numpy as np
from streamlit_autorefresh import st_autorefresh
import requests

# ==========================================
# 1. 頁面與設定
# ==========================================
st.set_page_config(layout="wide", page_title="John Kurisko 背離偵測系統")
st.title("🛡️ John Kurisko 背離偵測系統 (Divergence)")

with st.sidebar:
    st.markdown("---")
    st.header("⚙️ 系統設定")
    enable_refresh = st.checkbox("開啟自動刷新 (60s)", value=False)
    line_token = st.text_input("Line Token (選填)", type="password")
    
    st.markdown("---")
    st.info("此版本專注於偵測「價格」與「Stoch動量」的背離現象。")

if enable_refresh:
    count = st_autorefresh(interval=60000, limit=None, key="refresh_counter")

# ==========================================
# 2. 運算函數
# ==========================================

def send_line_notify(token, msg):
    try:
        url = "https://notify-api.line.me/api/notify"
        headers = {"Authorization": "Bearer " + token}
        requests.post(url, headers=headers, data={"message": msg})
    except: pass

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def calculate_stoch(df, k_period, d_period, smooth_k):
    low_min = df['Low'].rolling(window=k_period).min()
    high_max = df['High'].rolling(window=k_period).max()
    denom = high_max - low_min
    denom = denom.replace(0, 0.000001)
    k_fast = 100 * ((df['Close'] - low_min) / denom)
    return k_fast.rolling(window=smooth_k).mean()

def get_data(symbol, interval):
    try:
        period = "1mo" if interval == "15m" else "6mo"
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        if df.empty: return None, "No Data"
        if df.index.tz is not None: df.index = df.index.tz_localize(None)
        
        df = df[df['Close'] > 0].dropna()

        # 指標計算
        df['EMA_20'] = calculate_ema(df['Close'], 20)
        df['EMA_50'] = calculate_ema(df['Close'], 50)
        df['EMA_200'] = calculate_ema(df['Close'], 200)

        # 影片重點：快速線 (Fast Stoch) 用來找背離
        df['Stoch_Fast'] = calculate_stoch(df, 9, 1, 3) 
        # 慢速線用來參考趨勢
        df['Stoch_Slow'] = calculate_stoch(df, 60, 1, 10) 

        df = df.dropna()
        return df, None
    except Exception as e:
        return None, str(e)

# ==========================================
# 3. 核心邏輯：背離偵測 (Divergence Logic)
# ==========================================
def detect_divergence(df, window=5):
    """
    偵測背離演算法：
    1. 找出局部的價格高點/低點 (Pivot High/Low)。
    2. 找出對應時間點的 Stoch 值。
    3. 比對：
       - 頂背離 (Bearish): 價格創新高 (HH) + Stoch 沒創新高 (LH)
       - 底背離 (Bullish): 價格創新低 (LL) + Stoch 沒創新低 (HL)
    """
    buy_signals = [np.nan] * len(df)
    sell_signals = [np.nan] * len(df)
    status = "無訊號"

    # 我們需要遍歷尋找 Pivot
    # 為了效率，我們只檢查每一個點是否是過去 N 根和未來 N 根的極值 (這在實時中只能檢查過去)
    # 這裡採用實時模擬：只比對「當前 K 線」與「過去某個波段高點」
    
    # 找出所有的波段高低點索引
    highs = df['High'].values
    lows = df['Low'].values
    stochs = df['Stoch_Fast'].values
    
    # 用於儲存過去的波段點 (Index, Price, StochValue)
    pivot_highs = [] 
    pivot_lows = []
    
    for i in range(window, len(df) - 1): # 預留空間
        # --- 1. 識別波段高點 (Pivot High) ---
        # 簡單定義：中間比左右兩邊都高 (類似分形)
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            # 這是潛在的波段高點
            current_high_price = highs[i]
            current_high_stoch = stochs[i]
            
            # 檢查是否構成頂背離 (與上一個波段高點比較)
            if len(pivot_highs) > 0:
                last_idx, last_price, last_stoch = pivot_highs[-1]
                
                # 距離不能太遠 (例如 60 根以內)，也不能太近 (至少隔 5 根)
                if 5 < (i - last_idx) < 60:
                    # 條件：價格創新高 (Price High > Prev Price High)
                    # 條件：指標沒創新高 (Stoch < Prev Stoch)
                    # 過濾：Stoch 必須在超買區 (例如 > 70) 才有意義
                    if current_high_price > last_price and current_high_stoch < last_stoch and current_high_stoch > 70:
                        sell_signals[i] = highs[i] * 1.002 # 標記在 K 線上方
                        if i >= len(df) - 3: status = "❄️ 看空背離 (Bearish Divergence)"
            
            pivot_highs.append((i, current_high_price, current_high_stoch))

        # --- 2. 識別波段低點 (Pivot Low) ---
        if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
            current_low_price = lows[i]
            current_low_stoch = stochs[i]
            
            if len(pivot_lows) > 0:
                last_idx, last_price, last_stoch = pivot_lows[-1]
                
                if 5 < (i - last_idx) < 60:
                    # 條件：價格創新低 (Price Low < Prev Price Low)
                    # 條件：指標沒創新低 (Stoch > Prev Stoch)
                    # 過濾：Stoch 必須在超賣區 (例如 < 30)
                    if current_low_price < last_price and current_low_stoch > last_stoch and current_low_stoch < 30:
                        buy_signals[i] = lows[i] * 0.998 # 標記在 K 線下方
                        if i >= len(df) - 3: status = "🔥 看多背離 (Bullish Divergence)"
            
            pivot_lows.append((i, current_low_price, current_low_stoch))

    return buy_signals, sell_signals, status

# ==========================================
# 4. 主程式介面
# ==========================================
with st.sidebar:
    symbol = st.text_input("監控代號", value="BTC-USD")
    timeframe = st.selectbox("週期", ["15m", "1h"], index=0)
    ema_fast = st.number_input("EMA 快", value=20)
    ema_mid = st.number_input("EMA 中", value=50)
    ema_slow = st.number_input("EMA 慢", value=200)

should_run = True if enable_refresh else st.button("🚀 分析圖表")

if should_run:
    with st.spinner("計算中..."):
        df, err = get_data(symbol, timeframe)
        
        if err:
            st.error(err)
        elif df is not None:
            # 取多一點數據來計算 Pivot，但畫圖只畫最近 60 根
            buys, sells, status = detect_divergence(df)
            
            # 切片取最近 60 根用於顯示
            plot_df = df.tail(60)
            plot_buys = buys[-60:]
            plot_sells = sells[-60:]
            curr = plot_df.iloc[-1]

            # --- 通知 ---
            if "背離" in status:
                st.toast(f"{symbol} 出現 {status}！", icon="🚨")
                if line_token:
                    send_line_notify(line_token, f"\n【背離訊號】\n{symbol} ({timeframe})\n現價: {curr['Close']:.2f}\n{status}")

            # --- 數據顯示 ---
            st.markdown(f"### 🎯 狀態：{status}")
            c1, c2, c3 = st.columns(3)
            c1.metric("價格", f"{curr['Close']:.2f}")
            c1.metric("快速 Stoch (9,3)", f"{curr['Stoch_Fast']:.1f}")
            c2.metric("趨勢 EMA 200", f"{curr['EMA_200']:.2f}")

            # --- 圖例說明 ---
            with st.expander("📖 點擊查看【線條顏色定義】與【背離條件】", expanded=True):
                st.markdown("""
                ### 📊 圖表指標說明
                *   **主圖 (K線區)：**
                    *   🟦 **青色 (EMA 20)** | 🟧 **橘色 (EMA 50)** | ⬜ **白色 (EMA 200)**：趨勢參考。
                *   **副圖 (下方震盪區)：**
                    *   🟥 **紅色線 (Fast Stoch 9,3)**：**主要背離偵測線**。
                    *   🟩 **綠色線 (Slow Stoch 60,10)**：長期動量。

                ### 🚦 買賣訊號邏輯 (嚴格背離)
                | 訊號 | 圖示 | 定義 (Divergence) | 條件 |
                | :--- | :---: | :--- | :--- |
                | **看多背離** | ▲ 黃色 | **底背離** | 價格創 **更低** 的低點 (LL) <br> 但紅色 Stoch 創 **更高** 的低點 (HL) <br> (發生在超賣區 < 30) |
                | **看空背離** | ▼ 紫色 | **頂背離** | 價格創 **更高** 的高點 (HH) <br> 但紅色 Stoch 創 **更低** 的高點 (LH) <br> (發生在超買區 > 70) |
                """)

            # --- 繪圖 ---
            apds = [
                mpf.make_addplot(plot_df['EMA_20'], color='cyan', width=1),
                mpf.make_addplot(plot_df['EMA_50'], color='orange', width=1.5),
                mpf.make_addplot(plot_df['EMA_200'], color='white', width=2),
                
                mpf.make_addplot(plot_df['Stoch_Fast'], panel=1, color='#FF3333', width=1.5, ylabel='Fast Stoch'),
                mpf.make_addplot(plot_df['Stoch_Slow'], panel=1, color='#33FF33', width=1.5),
            ]

            # 避免全空值報錯
            if not np.isnan(plot_buys).all():
                apds.append(mpf.make_addplot(plot_buys, type='scatter', markersize=100, marker='^', color='yellow'))
            if not np.isnan(plot_sells).all():
                apds.append(mpf.make_addplot(plot_sells, type='scatter', markersize=100, marker='v', color='#ff00ff'))

            fig, ax = mpf.plot(
                plot_df, type='candle', style='yahoo', addplot=apds,
                title=f"{symbol} ({timeframe}) - Divergence",
                returnfig=True, volume=False, panel_ratios=(7, 3), tight_layout=True,
                hlines=dict(hlines=[20, 80], colors=['gray', 'gray'], linestyle='--', linewidths=1.0)
            )
            st.pyplot(fig)
