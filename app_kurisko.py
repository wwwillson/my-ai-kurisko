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
st.set_page_config(layout="wide", page_title="John Kurisko 短線狙擊")

# 修改 1: 移除 (穩定版) 字樣
st.title("🛡️ John Kurisko 短線狙擊")

# 自動刷新設定
with st.sidebar:
    st.markdown("---")
    st.header("⚙️ 系統設定")
    enable_refresh = st.checkbox("開啟自動刷新 (60s)", value=False)
    line_token = st.text_input("Line Token (選填)", type="password")

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

def get_data(symbol, interval, ema_params):
    try:
        period = "1mo" if interval == "15m" else "6mo"
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        if df.empty: return None, "No Data"
        if df.index.tz is not None: df.index = df.index.tz_localize(None)
        
        df = df[df['Close'] > 0]
        df = df.dropna()

        # 指標計算
        df['EMA_20'] = calculate_ema(df['Close'], ema_params[0])
        df['EMA_50'] = calculate_ema(df['Close'], ema_params[1])
        df['EMA_200'] = calculate_ema(df['Close'], ema_params[2])

        df['Stoch1_K'] = calculate_stoch(df, 9, 1, 3) # Fast
        df['Stoch2_K'] = calculate_stoch(df, 14, 1, 3)
        df['Stoch3_K'] = calculate_stoch(df, 44, 1, 4)
        df['Stoch4_K'] = calculate_stoch(df, 60, 1, 10) # Slow

        df = df.dropna()
        return df, None
    except Exception as e:
        return None, str(e)

# ==========================================
# 3. 訊號邏輯
# ==========================================
def generate_signals(df, slow_threshold):
    buy_signals = []
    sell_signals = []
    current_signal_status = "無訊號"

    for i in range(len(df)):
        row = df.iloc[i]
        
        # 1. 牛旗買點
        is_uptrend = (row['Close'] > row['EMA_200']) and (row['Close'] > row['EMA_50'])
        slow_strong = row['Stoch4_K'] > slow_threshold
        fast_dip = row['Stoch1_K'] < 25
        
        if is_uptrend and slow_strong and fast_dip:
            buy_signals.append(row['Low'] * 0.999)
            sell_signals.append(np.nan)
            if i == len(df) - 1: current_signal_status = "🔥 牛旗買點 (做多)"
        
        # 2. 熊旗賣點
        elif (row['Close'] < row['EMA_200']) and (row['Close'] < row['EMA_50']) and \
             (row['Stoch4_K'] < (100 - slow_threshold)) and (row['Stoch1_K'] > 75):
            buy_signals.append(np.nan)
            sell_signals.append(row['High'] * 1.001)
            if i == len(df) - 1: current_signal_status = "❄️ 熊旗賣點 (做空)"
            
        else:
            buy_signals.append(np.nan)
            sell_signals.append(np.nan)
            
    return buy_signals, sell_signals, current_signal_status

# ==========================================
# 4. 主程式介面
# ==========================================
with st.sidebar:
    symbol = st.text_input("監控代號", value="BTC-USD")
    timeframe = st.selectbox("週期", ["15m", "1h"], index=0)
    ema_fast = st.number_input("EMA 快", value=20)
    ema_mid = st.number_input("EMA 中", value=50)
    ema_slow = st.number_input("EMA 慢", value=200)
    slow_stoch_threshold = st.slider("慢速 Stoch 強勢區", 50, 90, 80)

should_run = True if enable_refresh else st.button("🚀 分析圖表")

if should_run:
    with st.spinner("計算中..."):
        df, err = get_data(symbol, timeframe, [ema_fast, ema_mid, ema_slow])
        
        if err:
            st.error(err)
        elif df is not None:
            plot_df = df.tail(60).copy()
            buys, sells, status = generate_signals(plot_df, slow_stoch_threshold)
            curr = plot_df.iloc[-1]

            # --- 通知邏輯 ---
            if "買點" in status or "賣點" in status:
                st.toast(f"{symbol} 出現 {status}！", icon="🚨")
                if line_token:
                    send_line_notify(line_token, f"\n【訊號觸發】\n{symbol} ({timeframe})\n現價: {curr['Close']:.2f}\n{status}")

            # --- 數據顯示區 ---
            st.markdown(f"### 🎯 狀態：{status}")
            c1, c2, c3 = st.columns(3)
            c1.metric("價格", f"{curr['Close']:.2f}")
            c1.metric("趨勢強度 (慢速)", f"{curr['Stoch4_K']:.1f}")
            c2.metric("入場扳機 (快速)", f"{curr['Stoch1_K']:.1f}")

            st.markdown("---")

            # 修改 2: 新增詳細圖例與策略說明 (位於圖表上方)
            with st.expander("📖 點擊查看【線條顏色定義】與【買賣點條件】", expanded=True):
                st.markdown(f"""
                ### 📊 圖表指標說明
                *   **主圖 (K線區)：**
                    *   🟦 **青色線 (EMA 20)**：短期支撐/壓力。
                    *   🟧 **橘色線 (EMA 50)**：中線多空分界 (價格需在此之上才做多)。
                    *   ⬜ **白色線 (EMA 200)**：長線趨勢 (牛熊分界線)。
                *   **副圖 (下方震盪區)：**
                    *   🟥 **紅色線 (Fast Stoch 9,3)**：進場扳機。
                    *   🟩 **綠色線 (Slow Stoch 60,10)**：大趨勢動能。

                ### 🚦 買賣訊號邏輯
                | 訊號類型 | 圖示 | 觸發條件 (三者缺一不可) |
                | :--- | :---: | :--- |
                | **牛旗買進 (Long)** | ▲ 黃色 | 1. **趨勢向上**：價格 > EMA 50 & 200<br>2. **動能強勁**：慢速 Stoch (綠) > {slow_stoch_threshold}<br>3. **回調到位**：快速 Stoch (紅) < 25 (超賣) |
                | **熊旗賣出 (Short)** | ▼ 紫色 | 1. **趨勢向下**：價格 < EMA 50 & 200<br>2. **動能極弱**：慢速 Stoch (綠) < {100-slow_stoch_threshold}<br>3. **反彈到位**：快速 Stoch (紅) > 75 (超買) |
                """)

            # --- 繪圖設定 ---
            apds = [
                mpf.make_addplot(plot_df['EMA_20'], color='cyan', width=1),
                mpf.make_addplot(plot_df['EMA_50'], color='orange', width=1.5),
                mpf.make_addplot(plot_df['EMA_200'], color='white', width=2),
                
                mpf.make_addplot(plot_df['Stoch1_K'], panel=1, color='#FF3333', width=1.5, ylabel='Stoch'),
                mpf.make_addplot(plot_df['Stoch4_K'], panel=1, color='#33FF33', width=2.0),
            ]

            # 防止全 NaN 導致報錯
            if not np.isnan(buys).all():
                apds.append(mpf.make_addplot(buys, type='scatter', markersize=100, marker='^', color='yellow'))
            if not np.isnan(sells).all():
                apds.append(mpf.make_addplot(sells, type='scatter', markersize=100, marker='v', color='#ff00ff'))

            fig, ax = mpf.plot(
                plot_df, type='candle', style='yahoo', addplot=apds,
                title=f"{symbol} ({timeframe})",
                returnfig=True, volume=False, panel_ratios=(7, 3), tight_layout=True,
                hlines=dict(hlines=[20, 80], colors=['gray', 'gray'], linestyle='--', linewidths=1.0)
            )
            st.pyplot(fig)
