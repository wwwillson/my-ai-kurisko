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
st.set_page_config(layout="wide", page_title="John Kurisko 趨勢回調策略")
st.title("🛡️ John Kurisko 趨勢回調策略 (Trend Pullback)")

# 顯示策略邏輯 (根據影片 2:45 與 4:45)
st.info("""
### 🧠 策略判斷邏輯 (基於影片)

#### 📈 2:45 多頭進場 (Long Setup) - 順勢買進
1.  **趨勢判斷**：價格必須在 **50 EMA** 與 **200 EMA** 之上 (明確上升趨勢)。
2.  **回調訊號**：快速隨機指標 (Stoch 9,3) 跌入 **超賣區 (< 20)**。
3.  **進場點**：當上述條件滿足時，視為潛在買點。
4.  **止損 (SL)**：設置在最近的波段低點 (Swing Low)。
5.  **止盈 (TP)**：設置為止損距離的 3 倍 (風險回報比 1:3)。

#### 📉 4:45 空頭進場 (Short Setup) - 順勢做空
1.  **趨勢判斷**：價格必須在 **50 EMA** 與 **200 EMA** 之下 (明確下降趨勢)。
2.  **反彈訊號**：快速隨機指標 (Stoch 9,3) 衝上 **超買區 (> 80)**。
3.  **進場點**：當上述條件滿足時，視為潛在賣點。
4.  **止損 (SL)**：設置在最近的波段高點 (Swing High)。
5.  **止盈 (TP)**：設置為止損距離的 3 倍 (風險回報比 1:3)。
""")

# ==========================================
# 2. 系統設定
# ==========================================
with st.sidebar:
    st.header("⚙️ 參數設定")
    symbol = st.text_input("監控代號", value="BTC-USD")
    timeframe = st.selectbox("週期", ["15m", "1h"], index=0)
    
    st.markdown("---")
    enable_refresh = st.checkbox("開啟自動刷新 (60s)", value=False)
    line_token = st.text_input("Line Token (選填)", type="password")

if enable_refresh:
    count = st_autorefresh(interval=60000, limit=None, key="refresh_counter")

# ==========================================
# 3. 核心運算函數
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
        
        # 影片核心：Stoch (9,3,1)
        df['Stoch_Fast'] = calculate_stoch(df, 9, 1, 3) 
        df['Stoch_Slow'] = calculate_stoch(df, 60, 1, 10) # 輔助看大趨勢

        df = df.dropna()
        return df, None
    except Exception as e:
        return None, str(e)

# ==========================================
# 4. 訊號與止盈止損計算 (Risk/Reward Logic)
# ==========================================
def analyze_setup(df):
    """
    只分析「最後一根 K 線」是否符合條件。
    如果符合，計算 SL (止損) 與 TP (止盈) 的價格。
    """
    curr = df.iloc[-1]
    prev_5 = df.iloc[-6:-1] # 拿前5根來找波段高低點
    
    setup_type = None
    entry_price = curr['Close']
    stop_loss = 0.0
    take_profit = 0.0
    reason = ""

    # --- 條件 1: 做多 (Long) ---
    # 價格 > 50 & 200 EMA 且 Stoch < 20
    if (curr['Close'] > curr['EMA_50']) and (curr['Close'] > curr['EMA_200']):
        if curr['Stoch_Fast'] < 20:
            setup_type = "LONG"
            # 止損設在最近 5 根 K 線的最低點再低一點點
            swing_low = prev_5['Low'].min()
            stop_loss = swing_low if swing_low < curr['Low'] else curr['Low'] * 0.995
            
            risk = entry_price - stop_loss
            take_profit = entry_price + (risk * 3) # 3倍盈虧比
            reason = "趨勢向上 + Stoch超賣回調"

    # --- 條件 2: 做空 (Short) ---
    # 價格 < 50 & 200 EMA 且 Stoch > 80
    elif (curr['Close'] < curr['EMA_50']) and (curr['Close'] < curr['EMA_200']):
        if curr['Stoch_Fast'] > 80:
            setup_type = "SHORT"
            # 止損設在最近 5 根 K 線的最高點再高一點點
            swing_high = prev_5['High'].max()
            stop_loss = swing_high if swing_high > curr['High'] else curr['High'] * 1.005
            
            risk = stop_loss - entry_price
            take_profit = entry_price - (risk * 3) # 3倍盈虧比
            reason = "趨勢向下 + Stoch超買反彈"

    return setup_type, entry_price, stop_loss, take_profit, reason

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
            # 取最近 60 根畫圖
            plot_df = df.tail(60).copy()
            
            # 分析最新一根是否有訊號
            setup, entry, sl, tp, reason = analyze_setup(df)
            
            # --- 數據看板 ---
            curr_price = df.iloc[-1]['Close']
            st.metric("目前價格", f"{curr_price:.2f}")
            
            if setup:
                st.success(f"🔥 訊號觸發：{setup} ({reason})")
                c1, c2, c3 = st.columns(3)
                c1.metric("進場價 (Entry)", f"{entry:.2f}")
                c2.metric("止盈目標 (TP - Green)", f"{tp:.2f}", delta=f"3.0R")
                c3.metric("止損防守 (SL - Red)", f"{sl:.2f}", delta_color="inverse")
                
                if line_token:
                    send_line_notify(line_token, f"\n【{setup} 訊號】\n{symbol}\n進場: {entry:.2f}\n止盈: {tp:.2f}\n止損: {sl:.2f}")
            else:
                st.info("目前無符合 2:45 或 4:45 條件的進場訊號。")

            # --- 繪圖準備 ---
            apds = [
                mpf.make_addplot(plot_df['EMA_50'], color='orange', width=1.5),
                mpf.make_addplot(plot_df['EMA_200'], color='white', width=2),
                mpf.make_addplot(plot_df['Stoch_Fast'], panel=1, color='#FF3333', width=1.5, ylabel='Stoch (9,3)'),
            ]

            # --- 關鍵功能：畫出紅綠止盈止損區塊 (Fill Between) ---
            # 只有當有訊號時才畫
            fill_plots = dict()
            
            if setup:
                # 建立兩條水平線數據 (跟 K 線一樣長)
                tp_line = np.full(len(plot_df), tp)
                sl_line = np.full(len(plot_df), sl)
                entry_line = np.full(len(plot_df), entry)
                
                # 添加到圖表 (使用 addplot 畫隱形線，然後用 fill_between 填色)
                apds.append(mpf.make_addplot(tp_line, color='green', width=0.5, linestyle='--'))
                apds.append(mpf.make_addplot(sl_line, color='red', width=0.5, linestyle='--'))
                apds.append(mpf.make_addplot(entry_line, color='white', width=0.8, linestyle=':'))
                
                # 設定填色區塊
                # fill_between 需要 y1 和 y2 的值
                # 這裡我們用 dict 設定，mplfinance 會自動填滿這兩條線中間
                # 為了避免整個圖都是顏色，我們其實只需要最後幾根，但 mplfinance 限制較多
                # 這裡我們全圖畫水平帶狀，比較清楚
                
                if setup == "LONG":
                    # 綠色區塊：Entry 到 TP
                    # 紅色區塊：Entry 到 SL
                    fill_plots = dict(
                        hlines=dict(hlines=[entry, tp, sl], colors=['white', 'green', 'red'], linewidths=0.5)
                    )
                    # 無法直接在 mpf.plot 用 fill_between 填充水平線，
                    # 我們改用 addplot 的 fill_between 功能
                    
                    # 重新建構：
                    # 我們需要創造兩個 Series，一個是 TP值，一個是 Entry值
                    # 然後填色
                    apds.append(mpf.make_addplot(tp_line, color='g', alpha=0.0)) # 隱形輔助線
                    apds.append(mpf.make_addplot(entry_line, fill_between=dict(y1=tp_line.tolist(), y2=entry_line.tolist(), color='green', alpha=0.1)))
                    
                    apds.append(mpf.make_addplot(sl_line, color='r', alpha=0.0)) # 隱形輔助線
                    apds.append(mpf.make_addplot(entry_line, fill_between=dict(y1=entry_line.tolist(), y2=sl_line.tolist(), color='red', alpha=0.1)))

                elif setup == "SHORT":
                    # 綠色區塊：Entry 到 TP (下方)
                    # 紅色區塊：Entry 到 SL (上方)
                    apds.append(mpf.make_addplot(tp_line, color='g', alpha=0.0))
                    apds.append(mpf.make_addplot(entry_line, fill_between=dict(y1=entry_line.tolist(), y2=tp_line.tolist(), color='green', alpha=0.1)))
                    
                    apds.append(mpf.make_addplot(sl_line, color='r', alpha=0.0))
                    apds.append(mpf.make_addplot(entry_line, fill_between=dict(y1=sl_line.tolist(), y2=entry_line.tolist(), color='red', alpha=0.1)))

            # 繪製圖表
            fig, ax = mpf.plot(
                plot_df, type='candle', style='yahoo', addplot=apds,
                title=f"{symbol} ({timeframe}) Setup Analysis",
                returnfig=True, volume=False, panel_ratios=(7, 3), tight_layout=True,
                hlines=dict(hlines=[20, 80], colors=['gray', 'gray'], linestyle='--', linewidths=1.0)
            )
            st.pyplot(fig)
            
            if setup:
                st.caption("圖例說明：🟩 綠色半透明區 = 潛在獲利空間 (TP) | 🟥 紅色半透明區 = 風險承擔空間 (SL)")
