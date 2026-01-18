import streamlit as st
import yfinance as yf
import pandas as pd
import mplfinance as mpf
import numpy as np
from streamlit_autorefresh import st_autorefresh
import requests

# ==========================================
# 1. 頁面設定與策略邏輯說明
# ==========================================
st.set_page_config(layout="wide", page_title="John Kurisko 雙重超級訊號")
st.title("🛡️ John Kurisko 雙重超級訊號 (2:45 反轉 & 4:45 趨勢)")

st.info("""
### 🧠 策略邏輯詳解 (依據影片修正)

#### 1️⃣ 2:45 策略：多重 Stoch 背離反轉 (Reversal)
*   **核心**：利用 4 組 Stochastics (9,3 / 14,3 / 44,4 / 60,10) 判斷動量極值。
*   **做多條件**：價格創 **新低** (Lower Low)，但快速 Stoch (9,3) 創 **更高低點** (Higher Low) -> **底背離**。
*   **做空條件**：價格創 **新高** (Higher High)，但快速 Stoch (9,3) 創 **更低高點** (Lower High) -> **頂背離**。
*   **適用場景**：抓頂部或底部反轉。

#### 2️⃣ 4:45 策略：EMA 趨勢 + Stoch 動量中繼 (Trend Continuation)
*   **核心**：利用 EMA 確認趨勢，利用 Stoch (60,10) 確認強度，利用 Stoch (9,3) 找入場點。
*   **做多條件 (牛旗)**：
    1. **趨勢**：價格 > 200 EMA (且 > 50 EMA 為佳)。
    2. **強度**：慢速 Stoch (60,10) 維持高檔 (> 50-80)。
    3. **觸發**：快速 Stoch (9,3) 回調至超賣區 (< 20) 且出現 **隱性背離** (價格 HL 但指標 LL) 或單純超賣回升。
*   **做空條件 (熊旗)**：
    1. **趨勢**：價格 < 200 EMA。
    2. **強度**：慢速 Stoch (60,10) 維持低檔 (< 20-50)。
    3. **觸發**：快速 Stoch (9,3) 反彈至超買區 (> 80)。
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

        # EMA
        df['EMA_20'] = calculate_ema(df['Close'], 20)
        df['EMA_50'] = calculate_ema(df['Close'], 50)
        df['EMA_200'] = calculate_ema(df['Close'], 200)
        
        # Stochs
        df['Stoch_9_3'] = calculate_stoch(df, 9, 1, 3) 
        df['Stoch_60_10'] = calculate_stoch(df, 60, 1, 10)

        df = df.dropna()
        return df, None
    except Exception as e:
        return None, str(e)

# ==========================================
# 4. 關鍵邏輯：背離與趨勢判斷
# ==========================================

def identify_pivots(series, window=5):
    """ 找出波段高低點的索引 """
    pivots_high = []
    pivots_low = []
    
    # 簡單算法：如果是過去N根和未來N根的極值 (模擬實時則只看過去)
    # 這裡我們用過去 window 根 K 線來判斷是否為 Pivot
    for i in range(window, len(series)):
        segment = series[i-window:i+1]
        current = series[i]
        
        if current == max(segment): pivots_high.append(i)
        if current == min(segment): pivots_low.append(i)
        
    return pivots_high, pivots_low

def analyze_signals(df):
    """
    分析最後一根 K 線是否符合 2:45 或 4:45 的條件
    """
    curr = df.iloc[-1]
    curr_idx = df.index[-1]
    
    # 取得 Pivot 點 (用於背離判斷)
    # 我們回溯找最近的兩個波段點
    # 注意：這裡簡化計算，實際背離需要更複雜的波峰波谷比對
    # 這裡我們比較「當前價格」與「前 20-60 根 K 線內的最低/最高點」
    
    lookback = 40 # 回溯範圍
    past_df = df.iloc[-lookback:-1] # 過去的數據 (不含當前)
    
    signal_type = None
    strategy_name = ""
    reason = ""
    
    # --- 策略 1: 4:45 趨勢延續 (Trend Continuation) ---
    # 做多：價格 > EMA 200, 慢速Stoch強 (>60), 快速Stoch超賣 (<20)
    if (curr['Close'] > curr['EMA_200']) and (curr['Stoch_60_10'] > 60):
        if curr['Stoch_9_3'] < 25:
            signal_type = "LONG"
            strategy_name = "4:45 趨勢牛旗"
            reason = "EMA多頭 + 慢速強勁 + 快速回調"
            
    # 做空：價格 < EMA 200, 慢速Stoch弱 (<40), 快速Stoch超買 (>80)
    elif (curr['Close'] < curr['EMA_200']) and (curr['Stoch_60_10'] < 40):
        if curr['Stoch_9_3'] > 75:
            signal_type = "SHORT"
            strategy_name = "4:45 趨勢熊旗"
            reason = "EMA空頭 + 慢速疲弱 + 快速反彈"

    # --- 策略 2: 2:45 反轉背離 (Reversal Divergence) ---
    # 如果策略 1 沒訊號，檢查策略 2
    if signal_type is None:
        # 底背離 (做多)：價格創新低，指標墊高
        lowest_price_idx = past_df['Low'].idxmin()
        lowest_price = past_df.loc[lowest_price_idx, 'Low']
        stoch_at_lowest = past_df.loc[lowest_price_idx, 'Stoch_9_3']
        
        if (curr['Low'] < lowest_price) and (curr['Stoch_9_3'] > stoch_at_lowest) and (curr['Stoch_9_3'] < 30):
            signal_type = "LONG"
            strategy_name = "2:45 多頭背離"
            reason = "價格破底 + Stoch墊高 (底背離)"

        # 頂背離 (做空)：價格創新高，指標降低
        highest_price_idx = past_df['High'].idxmax()
        highest_price = past_df.loc[highest_price_idx, 'High']
        stoch_at_highest = past_df.loc[highest_price_idx, 'Stoch_9_3']
        
        if (curr['High'] > highest_price) and (curr['Stoch_9_3'] < stoch_at_highest) and (curr['Stoch_9_3'] > 70):
            signal_type = "SHORT"
            strategy_name = "2:45 空頭背離"
            reason = "價格破頂 + Stoch降低 (頂背離)"

    # --- 計算止損止盈 (TP/SL) ---
    entry = curr['Close']
    sl = 0.0
    tp = 0.0
    
    if signal_type == "LONG":
        # 止損設在近期低點
        swing_low = past_df['Low'].min()
        sl = swing_low if swing_low < curr['Low'] else curr['Low'] * 0.995
        risk = entry - sl
        tp = entry + (risk * 3) # 1:3 盈虧比
        
    elif signal_type == "SHORT":
        # 止損設在近期高點
        swing_high = past_df['High'].max()
        sl = swing_high if swing_high > curr['High'] else curr['High'] * 1.005
        risk = sl - entry
        tp = entry - (risk * 3)

    return signal_type, strategy_name, reason, entry, sl, tp

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
            plot_df = df.tail(80).copy()
            
            # 執行分析
            signal, strat_name, reason, entry, sl, tp = analyze_signals(df)
            
            # 顯示
            curr_price = df.iloc[-1]['Close']
            st.metric("目前價格", f"{curr_price:.2f}")
            
            if signal:
                color = "green" if signal == "LONG" else "red"
                st.markdown(f"### 🔥 訊號觸發：:{color}[{signal} - {strat_name}]")
                st.caption(f"原因: {reason}")
                
                c1, c2, c3 = st.columns(3)
                c1.metric("進場 (Entry)", f"{entry:.2f}")
                c2.metric("止盈 (TP)", f"{tp:.2f}")
                c3.metric("止損 (SL)", f"{sl:.2f}")
                
                if line_token:
                    send_line_notify(line_token, f"\n【{strat_name}】\n{symbol}\n方向: {signal}\n進場: {entry:.2f}")
            else:
                st.info("目前無符合 2:45 或 4:45 邏輯的訊號。")

            # --- 繪圖 (紅綠色塊) ---
            apds = [
                mpf.make_addplot(plot_df['EMA_50'], color='orange', width=1.5),
                mpf.make_addplot(plot_df['EMA_200'], color='white', width=2),
                mpf.make_addplot(plot_df['Stoch_9_3'], panel=1, color='#FF3333', width=1.5, ylabel='Fast Stoch'),
                mpf.make_addplot(plot_df['Stoch_60_10'], panel=1, color='#33FF33', width=1.5, ylabel='Slow Stoch'),
            ]

            if signal:
                # 準備畫色塊的數據
                t_series = np.full(len(plot_df), tp)
                s_series = np.full(len(plot_df), sl)
                e_series = np.full(len(plot_df), entry)
                
                # 綠色獲利區 (Entry 到 TP)
                apds.append(mpf.make_addplot(t_series, color='green', width=0.5))
                apds.append(mpf.make_addplot(e_series, fill_between=dict(y1=t_series.tolist(), y2=e_series.tolist(), color='green', alpha=0.15), width=0.5, color='white'))
                
                # 紅色虧損區 (Entry 到 SL)
                apds.append(mpf.make_addplot(s_series, color='red', width=0.5))
                apds.append(mpf.make_addplot(e_series, fill_between=dict(y1=e_series.tolist(), y2=s_series.tolist(), color='red', alpha=0.15)))

            fig, ax = mpf.plot(
                plot_df, type='candle', style='yahoo', addplot=apds,
                title=f"{symbol} ({timeframe}) Analysis",
                returnfig=True, volume=False, panel_ratios=(7, 3), tight_layout=True,
                hlines=dict(hlines=[20, 80], colors=['gray', 'gray'], linestyle='--', linewidths=1.0)
            )
            st.pyplot(fig)
            
            if signal:
                st.caption("圖例說明： 🟩 綠色區 = 預期獲利空間 (3R) | 🟥 紅色區 = 風險空間 (1R)")
