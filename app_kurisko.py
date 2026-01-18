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
st.title("🛡️ John Kurisko 專業操盤系統 (完整視覺優化版)")

# 隱藏詳細說明，保持畫面簡潔
with st.expander("📖 策略邏輯與參數定義 (點擊展開)", expanded=False):
    st.markdown("""
    **策略 A (反轉)**：四組 Stochastics 同步進入高/低檔並發生背離。
    **策略 B (趨勢)**：EMA 排列正確，配合 Stochastics 動能回調。
    
    *   **EMA 設定**：20 (青), 50 (橘), 200 (紫/黑)
    *   **Stoch 設定**：
        1.  9, 3, 1 (快速)
        2.  14, 3, 1 (中快)
        3.  44, 4, 1 (中慢)
        4.  60, 10, 1 (慢速)
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

def send_line_notify(token, msg):
    try:
        url = "https://notify-api.line.me/api/notify"
        headers = {"Authorization": "Bearer " + token}
        requests.post(url, headers=headers, data={"message": msg})
    except: pass

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def calculate_stoch_kd(df, k_period, smooth_k, smooth_d):
    """
    計算完整的 Stochastic %K 和 %D
    Returns: k_line, d_line
    """
    low_min = df['Low'].rolling(window=k_period).min()
    high_max = df['High'].rolling(window=k_period).max()
    
    denom = high_max - low_min
    denom = denom.replace(0, 0.000001)
    
    # Raw K
    r_k = 100 * ((df['Close'] - low_min) / denom)
    
    # Smooth K (我們圖表上的主線)
    k_full = r_k.rolling(window=smooth_k).mean()
    
    # Smooth D (訊號線)
    d_full = k_full.rolling(window=smooth_d).mean()
    
    return k_full, d_full

def get_data(symbol, interval):
    try:
        # 大幅增加數據長度，確保 200 EMA 計算出來
        # 4H 級別需要非常長的歷史數據
        period = "1mo" 
        if interval == "15m": period = "2mo" # 15m 抓2個月
        if interval == "1h": period = "1y"   # 1h 抓1年
        if interval == "4h": period = "2y"   # 4h 抓2年 (yfinance 最大限制)
        
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        if df.empty: return None, "No Data"
        if df.index.tz is not None: df.index = df.index.tz_localize(None)
        
        df = df[df['Close'] > 0].dropna()

        # --- 計算 EMA ---
        df['EMA_20'] = calculate_ema(df['Close'], 20)
        df['EMA_50'] = calculate_ema(df['Close'], 50)
        df['EMA_200'] = calculate_ema(df['Close'], 200)
        
        # --- 計算 4 組 Stochastics (K & D) ---
        # 1. 快速 (9, 3, 1) -> 這裡 D 是 1，所以 K=D
        df['K1'], df['D1'] = calculate_stoch_kd(df, 9, 3, 1)
        
        # 2. 中快 (14, 3, 1)
        df['K2'], df['D2'] = calculate_stoch_kd(df, 14, 3, 1)
        
        # 3. 中慢 (44, 4, 1)
        df['K3'], df['D3'] = calculate_stoch_kd(df, 44, 4, 1)
        
        # 4. 慢速 (60, 10, 1)
        df['K4'], df['D4'] = calculate_stoch_kd(df, 60, 10, 1)

        # 移除剛開始計算導致的 NaN
        df = df.dropna()
        return df, None
    except Exception as e:
        return None, str(e)

# ==========================================
# 4. 訊號分析邏輯
# ==========================================

def analyze_signals(df):
    curr = df.iloc[-1]
    lookback = 40 
    past_df = df.iloc[-lookback:-1] 
    
    signal_type = None
    strategy_name = ""
    reason = ""
    div_points = None # 背離線座標

    # --- 策略 A: 四重共振背離 ---
    # 檢查是否四個指標都進入極端區域 (K值判斷)
    all_oversold = (curr['K1'] < 30) and (curr['K2'] < 30) and (curr['K3'] < 30) and (curr['K4'] < 30)
    all_overbought = (curr['K1'] > 70) and (curr['K2'] > 70) and (curr['K3'] > 70) and (curr['K4'] > 70)

    if all_oversold:
        # 底背離檢查
        min_price_idx = past_df['Low'].idxmin()
        min_price = past_df.loc[min_price_idx, 'Low']
        stoch_at_min = df.loc[min_price_idx, 'K1'] # 用快速線 9,3 檢查背離
        
        if (curr['Low'] < min_price) and (curr['K1'] > stoch_at_min):
            signal_type = "LONG"
            strategy_name = "四重共振底背離"
            reason = "4指標低檔 + 價格破底 + 指標墊高"
            div_points = [(min_price_idx, min_price), (df.index[-1], curr['Low'])]

    elif all_overbought:
        # 頂背離檢查
        max_price_idx = past_df['High'].idxmax()
        max_price = past_df.loc[max_price_idx, 'High']
        stoch_at_max = df.loc[max_price_idx, 'K1']
        
        if (curr['High'] > max_price) and (curr['K1'] < stoch_at_max):
            signal_type = "SHORT"
            strategy_name = "四重共振頂背離"
            reason = "4指標高檔 + 價格破頂 + 指標降低"
            div_points = [(max_price_idx, max_price), (df.index[-1], curr['High'])]

    # --- 策略 B: 趨勢中繼 ---
    if signal_type is None:
        # 牛旗
        if (curr['Close'] > curr['EMA_200']) and (curr['K4'] > 50):
            if curr['K1'] < 20: # 快速線超賣
                signal_type = "LONG"
                strategy_name = "趨勢牛旗 (Bull Flag)"
                reason = "趨勢向上 + 慢速強勁 + 快速回調到位"
        
        # 熊旗
        elif (curr['Close'] < curr['EMA_200']) and (curr['K4'] < 50):
            if curr['K1'] > 80: # 快速線超買
                signal_type = "SHORT"
                strategy_name = "趨勢熊旗 (Bear Flag)"
                reason = "趨勢向下 + 慢速疲弱 + 快速反彈到位"

    # --- 止損止盈 ---
    entry = curr['Close']
    sl = 0.0; tp = 0.0
    if signal_type == "LONG":
        sl = df['Low'].iloc[-10:].min() * 0.998
        tp = entry + (entry - sl) * 3
    elif signal_type == "SHORT":
        sl = df['High'].iloc[-10:].max() * 1.002
        tp = entry - (sl - entry) * 3

    return signal_type, strategy_name, reason, entry, sl, tp, div_points

# ==========================================
# 5. 主程式與繪圖
# ==========================================
should_run = True if enable_refresh else st.button("🚀 分析最新訊號")

if should_run:
    with st.spinner("計算四重輪動指標與背離結構..."):
        df, err = get_data(symbol, timeframe)
        
        if err:
            st.error(err)
        elif df is not None:
            # 取最近 80 根 K 線畫圖
            plot_df = df.tail(80).copy()
            
            signal, strat_name, reason, entry, sl, tp, div_pts = analyze_signals(df)
            
            # --- 看板 ---
            curr_price = df.iloc[-1]['Close']
            st.metric("目前價格", f"{curr_price:.2f}")
            
            if signal:
                color = "green" if signal == "LONG" else "red"
                st.markdown(f"### 🔥 訊號觸發：:{color}[{signal} - {strat_name}]")
                st.caption(f"原因: {reason}")
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Entry", f"{entry:.2f}")
                c2.metric("TP (3R)", f"{tp:.2f}")
                c3.metric("SL", f"{sl:.2f}")
                
                if line_token:
                    send_line_notify(line_token, f"\n【{strat_name}】\n{symbol}\n方向: {signal}")
            else:
                st.info("目前無明確進場訊號。")

            # --- 繪圖設定 (5面板) ---
            # 顏色設定 (仿影片風格)
            # Stoch 1 (9,3): 紅色系
            # Stoch 2 (14,3): 橘黃系
            # Stoch 3 (44,4): 藍色系
            # Stoch 4 (60,10): 綠色系
            
            apds = [
                # 主圖 3條 EMA (加粗顯示)
                # 修正: 200 EMA 改為深紫色/黑色，確保在白色背景可見
                mpf.make_addplot(plot_df['EMA_20'], color='cyan', width=1.2),
                mpf.make_addplot(plot_df['EMA_50'], color='orange', width=1.5),
                mpf.make_addplot(plot_df['EMA_200'], color='#551A8B', width=2.5), # 深紫色
                
                # Panel 1: Stoch 9,3 (Trigger)
                mpf.make_addplot(plot_df['K1'], panel=1, color='#FF0000', width=1.2, ylabel='9,3'),
                mpf.make_addplot(plot_df['D1'], panel=1, color='#FF8888', width=0.8),
                
                # Panel 2: Stoch 14,3
                mpf.make_addplot(plot_df['K2'], panel=2, color='#FF8800', width=1.2, ylabel='14,3'),
                mpf.make_addplot(plot_df['D2'], panel=2, color='#FFCC66', width=0.8),
                
                # Panel 3: Stoch 44,4
                mpf.make_addplot(plot_df['K3'], panel=3, color='#0088FF', width=1.2, ylabel='44,4'),
                mpf.make_addplot(plot_df['D3'], panel=3, color='#66CCFF', width=0.8),
                
                # Panel 4: Stoch 60,10 (Trend Strength)
                mpf.make_addplot(plot_df['K4'], panel=4, color='#00CC00', width=1.5, ylabel='60,10'),
                mpf.make_addplot(plot_df['D4'], panel=4, color='#66FF66', width=0.8),
            ]

            # 畫止盈止損色塊
            if signal:
                t_s = np.full(len(plot_df), tp)
                s_s = np.full(len(plot_df), sl)
                e_s = np.full(len(plot_df), entry)
                
                apds.append(mpf.make_addplot(t_s, color='green', width=0.5))
                apds.append(mpf.make_addplot(e_s, fill_between=dict(y1=t_s.tolist(), y2=e_s.tolist(), color='green', alpha=0.1), width=0))
                
                apds.append(mpf.make_addplot(s_s, color='red', width=0.5))
                apds.append(mpf.make_addplot(e_s, fill_between=dict(y1=e_s.tolist(), y2=s_s.tolist(), color='red', alpha=0.1), width=0))

            # 畫背離線
            alines_config = None
            if div_pts:
                # 這裡只畫主圖的價格背離線，指標背離線因為多面板限制較難同時畫
                alines_config = dict(alines=[div_pts], colors='blue', linewidths=2.5, alpha=0.8)

            # 繪製
            fig, ax = mpf.plot(
                plot_df, type='candle', style='yahoo', 
                addplot=apds,
                title=f"{symbol} ({timeframe}) Quad Stochastics",
                returnfig=True, volume=False, 
                # 調整比例: 主圖大一點，副圖平均分配
                panel_ratios=(5, 1, 1, 1, 1),
                tight_layout=True,
                alines=alines_config,
                # 在所有副圖畫 20/80 線
                hlines=dict(hlines=[20, 80], colors=['gray', 'gray'], linestyle=':', linewidths=0.5)
            )
            st.pyplot(fig)
            
            st.caption("""
            **圖表說明**：
            - **主圖**：K線 + EMA 20(青)/50(橘)/200(紫)。黃色線為背離線。紅綠區塊為止損止盈。
            - **副圖 1-4**：依序為 Stoch 9,3 / 14,3 / 44,4 / 60,10。深色為主線(%K)，淺色為訊號線(%D)。
            """)
