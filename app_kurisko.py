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
st.set_page_config(layout="wide", page_title="John Kurisko 四重輪動系統")
st.title("🛡️ John Kurisko 四重輪動系統 (完整指標版)")

# 移除原本的 1️⃣ 2:45... 字樣，改用更直觀的描述
with st.expander("📖 點擊查看：多空判斷邏輯與參數定義", expanded=False):
    st.markdown("""
    ### 策略 A：多重 Stoch 背離反轉 (Reversal)
    *   **邏輯**：抓市場轉折點（由空轉多 或 由多轉空）。
    *   **條件**：價格創出新高/新低，但快速 Stoch (9,3) 卻出現背離 (Divergence)。
    
    ### 策略 B：EMA 趨勢 + Stoch 動量中繼 (Trend Continuation)
    *   **邏輯**：在強勢趨勢中，尋找回調買點（牛旗/熊旗）。
    *   **多頭條件**：價格 > 200 EMA，慢速 Stoch (60,10) 強勢，快速 Stoch (9,3) 回調超賣。若伴隨**隱性背離**則更佳。
    *   **空頭條件**：價格 < 200 EMA，慢速 Stoch (60,10) 弱勢，快速 Stoch (9,3) 反彈超買。
    
    ### 🛑 止盈止損設定 (依據影片)
    *   **止損 (SL)**：設在最近的波段高點 (Swing High) 或 波段低點 (Swing Low)。
    *   **止盈 (TP)**：固定風險回報比 **1:3** (賺賠比 3倍)。
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
        
        # 計算全部 4 組 Stochastics (依據影片參數)
        # 1. 快速 (Trigger)
        df['Stoch_9_3'] = calculate_stoch(df, 9, 1, 3)
        # 2. 中快
        df['Stoch_14_3'] = calculate_stoch(df, 14, 1, 3) 
        # 3. 中慢
        df['Stoch_44_4'] = calculate_stoch(df, 44, 1, 4)
        # 4. 慢速 (Trend Strength)
        df['Stoch_60_10'] = calculate_stoch(df, 60, 1, 10)

        df = df.dropna()
        return df, None
    except Exception as e:
        return None, str(e)

# ==========================================
# 4. 關鍵邏輯：背離與趨勢判斷
# ==========================================

def analyze_signals(df):
    curr = df.iloc[-1]
    
    # 回溯數據用於找波段點 (Pivot)
    lookback = 30 
    past_df = df.iloc[-lookback:-1]
    
    signal_type = None
    strategy_name = ""
    reason = ""
    
    # ----------------------------------------------
    # 策略 2 (原 4:45): 趨勢中繼 (Trend Continuation)
    # ----------------------------------------------
    # 條件：EMA 排列 + Stoch 輪動 (慢速強/快速弱)
    
    # 做多 (Bull Flag)
    if (curr['Close'] > curr['EMA_200']) and (curr['Stoch_60_10'] > 50):
        # 觸發：快速 Stoch 回調到超賣區
        if curr['Stoch_9_3'] < 25:
            signal_type = "LONG"
            strategy_name = "趨勢牛旗 (Trend Bull Flag)"
            reason = "EMA多頭 + 慢速強勁 + 快速回調"
            
            # 進階檢查：隱性背離 (Hidden Divergence) - 價格 Higher Low，指標 Lower Low
            # 這是影片中提到的強勢確認
            recent_low = past_df['Low'].min()
            recent_stoch_low = past_df['Stoch_9_3'].min()
            if (curr['Low'] > recent_low) and (curr['Stoch_9_3'] <= recent_stoch_low):
                reason += " (含隱性背離⭐⭐)"

    # 做空 (Bear Flag)
    elif (curr['Close'] < curr['EMA_200']) and (curr['Stoch_60_10'] < 50):
        # 觸發：快速 Stoch 反彈到超買區
        if curr['Stoch_9_3'] > 75:
            signal_type = "SHORT"
            strategy_name = "趨勢熊旗 (Trend Bear Flag)"
            reason = "EMA空頭 + 慢速疲弱 + 快速反彈"
            
            # 進階檢查：隱性背離 (Hidden Divergence) - 價格 Lower High，指標 Higher High
            recent_high = past_df['High'].max()
            recent_stoch_high = past_df['Stoch_9_3'].max()
            if (curr['High'] < recent_high) and (curr['Stoch_9_3'] >= recent_stoch_high):
                reason += " (含隱性背離⭐⭐)"

    # ----------------------------------------------
    # 策略 1 (原 2:45): 反轉背離 (Reversal Divergence)
    # ----------------------------------------------
    # 只有在策略 2 沒訊號時才檢查這個 (優先順勢)
    if signal_type is None:
        
        # 多頭背離 (Regular Bullish Divergence)
        # 價格創新低，但指標墊高
        lowest_price = past_df['Low'].min()
        idx_min = past_df['Low'].idxmin()
        stoch_at_min = df.loc[idx_min]['Stoch_9_3']
        
        if (curr['Low'] < lowest_price) and (curr['Stoch_9_3'] > stoch_at_min) and (curr['Stoch_9_3'] < 30):
            signal_type = "LONG"
            strategy_name = "底部背離反轉 (Reversal)"
            reason = "價格破底 + 指標墊高 (底背離)"

        # 空頭背離 (Regular Bearish Divergence)
        # 價格創新高，但指標降低
        highest_price = past_df['High'].max()
        idx_max = past_df['High'].idxmax()
        stoch_at_max = df.loc[idx_max]['Stoch_9_3']
        
        if (curr['High'] > highest_price) and (curr['Stoch_9_3'] < stoch_at_max) and (curr['Stoch_9_3'] > 70):
            signal_type = "SHORT"
            strategy_name = "頂部背離反轉 (Reversal)"
            reason = "價格破頂 + 指標降低 (頂背離)"

    # --- 計算止損止盈 (Swing High/Low) ---
    entry = curr['Close']
    sl = 0.0
    tp = 0.0
    
    if signal_type == "LONG":
        # 止損設在過去 10 根 K 線的最低點 (波段低點)
        swing_low = df['Low'].iloc[-10:].min()
        sl = swing_low if swing_low < curr['Low'] else curr['Low'] * 0.995
        risk = entry - sl
        tp = entry + (risk * 3) # 1:3 盈虧比
        
    elif signal_type == "SHORT":
        # 止損設在過去 10 根 K 線的最高點 (波段高點)
        swing_high = df['High'].iloc[-10:].max()
        sl = swing_high if swing_high > curr['High'] else curr['High'] * 1.005
        risk = sl - entry
        tp = entry - (risk * 3)

    return signal_type, strategy_name, reason, entry, sl, tp

# ==========================================
# 5. 主程式與繪圖
# ==========================================
should_run = True if enable_refresh else st.button("🚀 分析最新訊號")

if should_run:
    with st.spinner("計算四重輪動指標中..."):
        df, err = get_data(symbol, timeframe)
        
        if err:
            st.error(err)
        elif df is not None:
            # 取最近 80 根畫圖，確保能看清趨勢
            plot_df = df.tail(80).copy()
            
            # 執行分析
            signal, strat_name, reason, entry, sl, tp = analyze_signals(df)
            
            # 顯示
            curr_price = df.iloc[-1]['Close']
            st.metric("目前價格", f"{curr_price:.2f}")
            
            if signal:
                color = "green" if signal == "LONG" else "red"
                st.markdown(f"### 🔥 訊號觸發：:{color}[{signal} - {strat_name}]")
                st.caption(f"判斷依據: {reason}")
                
                c1, c2, c3 = st.columns(3)
                c1.metric("建議進場 (Entry)", f"{entry:.2f}")
                c2.metric("止盈目標 (TP)", f"{tp:.2f}", help="風險回報比 1:3")
                c3.metric("止損防守 (SL)", f"{sl:.2f}", help="設於近期波段高低點")
                
                if line_token:
                    send_line_notify(line_token, f"\n【{strat_name}】\n{symbol}\n方向: {signal}\n進場: {entry:.2f}\n止損: {sl:.2f}")
            else:
                st.info("目前無符合進場條件的訊號 (等待輪動到位)。")

            # --- 繪圖設定 (5個面板) ---
            # Panel 0: K線 + EMA
            # Panel 1-4: Stochastics
            
            apds = [
                # 主圖 EMA
                mpf.make_addplot(plot_df['EMA_50'], color='orange', width=1.5),
                mpf.make_addplot(plot_df['EMA_200'], color='white', width=2),
                
                # 副圖 1: Stoch 9,3 (Trigger)
                mpf.make_addplot(plot_df['Stoch_9_3'], panel=1, color='#FF3333', width=1.5, ylabel='9,3'),
                
                # 副圖 2: Stoch 14,3
                mpf.make_addplot(plot_df['Stoch_14_3'], panel=2, color='#FFAA33', width=1.5, ylabel='14,3'),
                
                # 副圖 3: Stoch 44,4
                mpf.make_addplot(plot_df['Stoch_44_4'], panel=3, color='#33AAFF', width=1.5, ylabel='44,4'),
                
                # 副圖 4: Stoch 60,10 (Trend)
                mpf.make_addplot(plot_df['Stoch_60_10'], panel=4, color='#33FF33', width=1.5, ylabel='60,10'),
            ]

            # 畫出止損止盈色塊
            if signal:
                t_series = np.full(len(plot_df), tp)
                s_series = np.full(len(plot_df), sl)
                e_series = np.full(len(plot_df), entry)
                
                # 綠色獲利區
                apds.append(mpf.make_addplot(t_series, color='green', width=0.5))
                apds.append(mpf.make_addplot(e_series, fill_between=dict(y1=t_series.tolist(), y2=e_series.tolist(), color='green', alpha=0.15), width=0.5, color='white'))
                
                # 紅色虧損區
                apds.append(mpf.make_addplot(s_series, color='red', width=0.5))
                apds.append(mpf.make_addplot(e_series, fill_between=dict(y1=e_series.tolist(), y2=s_series.tolist(), color='red', alpha=0.15)))

            # 設定每個 Panel 的高度比例
            # 主圖給 6 份，副圖各給 1.5 份
            panel_ratios = (6, 1.5, 1.5, 1.5, 1.5)

            fig, ax = mpf.plot(
                plot_df, type='candle', style='yahoo', addplot=apds,
                title=f"{symbol} ({timeframe}) Four-Fold Stochs",
                returnfig=True, volume=False, 
                panel_ratios=panel_ratios, # 套用比例
                tight_layout=True,
                # 在所有副圖畫出 20/80 線
                hlines=dict(hlines=[20, 80], colors=['gray', 'gray'], linestyle='--', linewidths=0.5, alpha=0.5)
            )
            st.pyplot(fig)
            
            if signal:
                st.caption("圖表說明：主圖顯示 EMA 趨勢，下方四個副圖分別顯示不同週期的 Stochastic 動量輪動。紅綠色塊代表建議的止損止盈區間。")
