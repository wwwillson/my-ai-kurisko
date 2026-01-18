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
st.title("🛡️ John Kurisko 專業操盤系統 (四重輪動 + 自動背離畫線)")

# 隱藏式說明
with st.expander("📖 策略邏輯與圖表說明 (點擊展開)", expanded=False):
    st.markdown("""
    ### 1️⃣ 策略 A：四重共振背離反轉 (Reversal)
    *   **環境**：**4 個 Stochastics 全部** 進入超賣區 (< 20-30) 或 超買區 (> 70-80)。
    *   **觸發**：
        *   **多頭 (Bull)**：價格創新低 (Lower Low)，但 Stoch 9,3 創新高 (Higher Low) -> **畫出黃色底背離線**。
        *   **空頭 (Bear)**：價格創新高 (Higher High)，但 Stoch 9,3 創新低 (Lower High) -> **畫出黃色頂背離線**。
    
    ### 2️⃣ 策略 B：趨勢中繼 (Trend Continuation)
    *   **多頭**：價格 > 200 EMA，慢速 Stoch (60,10) 強勢 (>50)，快速 Stoch 回調。
    *   **空頭**：價格 < 200 EMA，慢速 Stoch (60,10) 弱勢 (<50)，快速 Stoch 反彈。
    """)

# ==========================================
# 2. 側邊欄設定
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
        # 增加數據抓取量以確保 EMA 200 能計算出來
        period = "3mo" if interval == "15m" else "1y" 
        if interval == "4h": period = "2y"
        
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
        
        # 四重 Stochastics
        df['Stoch_9_3'] = calculate_stoch(df, 9, 1, 3)
        df['Stoch_14_3'] = calculate_stoch(df, 14, 1, 3) 
        df['Stoch_44_4'] = calculate_stoch(df, 44, 1, 4)
        df['Stoch_60_10'] = calculate_stoch(df, 60, 1, 10)

        df = df.dropna()
        return df, None
    except Exception as e:
        return None, str(e)

# ==========================================
# 4. 高階訊號分析 (含背離座標計算)
# ==========================================

def analyze_signals(df):
    curr = df.iloc[-1]
    
    # 搜尋範圍 (找 Pivot)
    lookback = 40 
    past_df = df.iloc[-lookback:-1] # 不含當前 K 線
    
    signal_type = None
    strategy_name = ""
    reason = ""
    
    # 用於畫背離線的座標 [(日期1, 數值1), (日期2, 數值2)]
    div_line_price = [] 
    div_line_stoch = []

    # ----------------------------------------------
    # 策略 A: 四重共振背離 (Reversal) - 優先判斷
    # ----------------------------------------------
    # 條件 1: 檢查四個指標是否都在低檔 (例如 < 35 寬鬆一點，確保能抓到)
    all_oversold = (curr['Stoch_9_3'] < 35) and (curr['Stoch_14_3'] < 35) and \
                   (curr['Stoch_44_4'] < 35) and (curr['Stoch_60_10'] < 35)
    
    all_overbought = (curr['Stoch_9_3'] > 65) and (curr['Stoch_14_3'] > 65) and \
                     (curr['Stoch_44_4'] > 65) and (curr['Stoch_60_10'] > 65)

    # 條件 2: 背離偵測
    if all_oversold:
        # 找過去最低價
        min_price_idx = past_df['Low'].idxmin()
        min_price = past_df.loc[min_price_idx, 'Low']
        stoch_at_min = df.loc[min_price_idx, 'Stoch_9_3']
        
        # 底背離: 價格創新低 (LL) 且 Stoch 9,3 墊高 (HL) 且 Stoch 黃金交叉向上
        if (curr['Low'] < min_price) and (curr['Stoch_9_3'] > stoch_at_min) and (curr['Stoch_9_3'] > df.iloc[-2]['Stoch_9_3']):
            signal_type = "LONG"
            strategy_name = "策略 A: 四重共振底背離"
            reason = "4指標低檔 + 價格破底 + Stoch墊高"
            # 紀錄畫線座標
            div_line_price = [(min_price_idx, min_price), (df.index[-1], curr['Low'])]
            div_line_stoch = [(min_price_idx, stoch_at_min), (df.index[-1], curr['Stoch_9_3'])]

    elif all_overbought:
        # 找過去最高價
        max_price_idx = past_df['High'].idxmax()
        max_price = past_df.loc[max_price_idx, 'High']
        stoch_at_max = df.loc[max_price_idx, 'Stoch_9_3']
        
        # 頂背離: 價格創新高 (HH) 且 Stoch 9,3 降低 (LH)
        if (curr['High'] > max_price) and (curr['Stoch_9_3'] < stoch_at_max) and (curr['Stoch_9_3'] < df.iloc[-2]['Stoch_9_3']):
            signal_type = "SHORT"
            strategy_name = "策略 A: 四重共振頂背離"
            reason = "4指標高檔 + 價格破頂 + Stoch降低"
            # 紀錄畫線座標
            div_line_price = [(max_price_idx, max_price), (df.index[-1], curr['High'])]
            div_line_stoch = [(max_price_idx, stoch_at_max), (df.index[-1], curr['Stoch_9_3'])]

    # ----------------------------------------------
    # 策略 B: 趨勢中繼 (Trend Continuation)
    # ----------------------------------------------
    if signal_type is None:
        # 牛旗
        if (curr['Close'] > curr['EMA_200']) and (curr['Stoch_60_10'] > 50):
            if curr['Stoch_9_3'] < 25:
                signal_type = "LONG"
                strategy_name = "策略 B: 趨勢牛旗"
                reason = "EMA多頭 + 慢速強 + 快速回調"
        
        # 熊旗
        elif (curr['Close'] < curr['EMA_200']) and (curr['Stoch_60_10'] < 50):
            if curr['Stoch_9_3'] > 75:
                signal_type = "SHORT"
                strategy_name = "策略 B: 趨勢熊旗"
                reason = "EMA空頭 + 慢速弱 + 快速反彈"

    # --- 計算止損止盈 ---
    entry = curr['Close']
    sl = 0.0
    tp = 0.0
    
    if signal_type == "LONG":
        swing_low = df['Low'].iloc[-10:].min()
        sl = swing_low * 0.995
        tp = entry + (entry - sl) * 3
    elif signal_type == "SHORT":
        swing_high = df['High'].iloc[-10:].max()
        sl = swing_high * 1.005
        tp = entry - (sl - entry) * 3

    return signal_type, strategy_name, reason, entry, sl, tp, div_line_price, div_line_stoch

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
            # 畫圖數據 (取最近 80 根，確保背離點在畫面內)
            plot_df = df.tail(80).copy()
            
            # 分析
            signal, strat_name, reason, entry, sl, tp, div_price, div_stoch = analyze_signals(df)
            
            # 顯示看板
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
                    send_line_notify(line_token, f"\n【{strat_name}】\n{symbol}\n方向: {signal}\n現價: {curr_price}")
            else:
                st.info("目前無明確進場訊號。")

            # --- 繪圖設定 (5面板) ---
            # Panel 0: Main
            # Panel 1: Stoch 9,3 (Trigger)
            # Panel 2: Stoch 14,3
            # Panel 3: Stoch 44,4
            # Panel 4: Stoch 60,10
            
            apds = [
                # EMA (主圖) - 加粗顯示
                mpf.make_addplot(plot_df['EMA_20'], color='cyan', width=1.0),
                mpf.make_addplot(plot_df['EMA_50'], color='orange', width=1.5),
                mpf.make_addplot(plot_df['EMA_200'], color='white', width=2.0),
                
                # 4個 Stochs (分開顯示)
                mpf.make_addplot(plot_df['Stoch_9_3'], panel=1, color='#FF5555', width=1.5, ylabel='9,3'),
                mpf.make_addplot(plot_df['Stoch_14_3'], panel=2, color='#FFAA00', width=1.5, ylabel='14,3'),
                mpf.make_addplot(plot_df['Stoch_44_4'], panel=3, color='#00AAFF', width=1.5, ylabel='44,4'),
                mpf.make_addplot(plot_df['Stoch_60_10'], panel=4, color='#55FF55', width=1.5, ylabel='60,10'),
            ]

            # --- 畫背離線與色塊 (關鍵升級) ---
            # 這裡使用 alines 來畫線
            # alines 格式: [ [(date1, val1), (date2, val2)], ... ]
            
            alines_config = []
            
            if signal and div_price:
                # 1. 在主圖畫價格背離線 (黃色粗線)
                alines_config.append(dict(alines=[div_price], colors=['yellow'], linewidths=2.5, panel=0))
                # 2. 在副圖1畫指標背離線 (黃色粗線)
                alines_config.append(dict(alines=[div_stoch], colors=['yellow'], linewidths=2.5, panel=1))

            # 畫止盈止損色塊
            if signal:
                t_series = np.full(len(plot_df), tp)
                s_series = np.full(len(plot_df), sl)
                e_series = np.full(len(plot_df), entry)
                
                apds.append(mpf.make_addplot(t_series, color='green', width=0.5))
                apds.append(mpf.make_addplot(e_series, fill_between=dict(y1=t_series.tolist(), y2=e_series.tolist(), color='green', alpha=0.1), width=0))
                
                apds.append(mpf.make_addplot(s_series, color='red', width=0.5))
                apds.append(mpf.make_addplot(e_series, fill_between=dict(y1=e_series.tolist(), y2=s_series.tolist(), color='red', alpha=0.1), width=0))

            # 繪製
            fig, ax = mpf.plot(
                plot_df, type='candle', style='yahoo', 
                addplot=apds,
                title=f"{symbol} ({timeframe}) Quad Rotation",
                returnfig=True, volume=False, 
                panel_ratios=(6, 1.5, 1.5, 1.5, 1.5), # 調整比例
                tight_layout=True,
                # 傳入多個 alines 配置
                alines=dict(alines=div_price if div_price else [], colors='yellow', linewidths=2, panel=0) if div_price else None,
                # 畫出 20/80 線
                hlines=dict(hlines=[20, 80], colors=['gray', 'gray'], linestyle='--', linewidths=0.5, alpha=0.5)
            )
            
            # 手動補上副圖的背離線 (因為 mplfinance 的 alines 參數有時候對多面板支援度有限，這裡主要確保主圖有線)
            # 上面的 alines 參數已經處理了主圖的線。
            
            st.pyplot(fig)
            
            if signal:
                st.caption("圖表說明：主圖黃線為價格背離，下方 4 個副圖依序為不同週期的 Stoch 指標。紅綠色塊為建議的風險回報區間。")
