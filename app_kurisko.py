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
st.title("🛡️ John Kurisko 專業操盤系統 (UI完美對齊版)")

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
        period = "5d" 
        if interval == "15m": period = "60d" 
        elif interval == "1h": period = "730d" 
        elif interval == "4h": period = "730d"
        
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        if df.empty: return None, "No Data"
        if df.index.tz is not None: df.index = df.index.tz_localize(None)
        
        df = df[df['Close'] > 0].dropna()

        # 指標
        df['EMA_20'] = calculate_ema(df['Close'], 20)
        df['EMA_50'] = calculate_ema(df['Close'], 50)
        df['EMA_200'] = calculate_ema(df['Close'], 200)
        
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

    # --- 策略 A: 背離 ---
    all_oversold = (curr['K1'] < 35) and (curr['K2'] < 35) and (curr['K3'] < 35) and (curr['K4'] < 35)
    all_overbought = (curr['K1'] > 65) and (curr['K2'] > 65) and (curr['K3'] > 65) and (curr['K4'] > 65)

    if all_oversold:
        min_price_idx = past_df['Low'].idxmin()
        min_price = past_df.loc[min_price_idx, 'Low']
        stoch_at_min = df.loc[min_price_idx, 'K1']
        if (curr['Low'] < min_price) and (curr['K1'] > stoch_at_min):
            signal_type = "LONG"
            strategy_name = "底背離反轉"
            reason = "價格破底 + 指標墊高"
            div_points = [(min_price_idx, min_price), (df.index[-1], curr['Low'])]

    elif all_overbought:
        max_price_idx = past_df['High'].idxmax()
        max_price = past_df.loc[max_price_idx, 'High']
        stoch_at_max = df.loc[max_price_idx, 'K1']
        if (curr['High'] > max_price) and (curr['K1'] < stoch_at_max):
            signal_type = "SHORT"
            strategy_name = "頂背離反轉"
            reason = "價格破頂 + 指標降低"
            div_points = [(max_price_idx, max_price), (df.index[-1], curr['High'])]

    # --- 策略 B: 趨勢中繼 ---
    if signal_type is None:
        if (curr['Close'] > curr['EMA_200']) and (curr['K4'] > 50):
            if curr['K1'] < 20: 
                signal_type = "LONG"
                strategy_name = "趨勢牛旗"
                reason = "順勢回調買點"
        elif (curr['Close'] < curr['EMA_200']) and (curr['K4'] < 50):
            if curr['K1'] > 80: 
                signal_type = "SHORT"
                strategy_name = "趨勢熊旗"
                reason = "順勢反彈空點"

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
# 5. 主程式與繪圖 (UI 優化核心)
# ==========================================
should_run = True if enable_refresh else st.button("🚀 分析最新訊號")

if should_run:
    with st.spinner("計算中..."):
        df, err = get_data(symbol, timeframe)
        
        if err:
            st.error(err)
        elif df is not None:
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
                if line_token: send_line_notify_wrapper(line_token, strat_name, symbol, signal, curr_price)
            else:
                st.info("目前無明確進場訊號。")

            # --- 繪圖設定 ---
            y_25 = np.full(len(plot_df), 25)
            y_75 = np.full(len(plot_df), 75)

            apds = [
                # 主圖
                mpf.make_addplot(plot_df['EMA_20'], color='#00FFFF', width=1.5),
                mpf.make_addplot(plot_df['EMA_50'], color='#FFA500', width=2.0),
                mpf.make_addplot(plot_df['EMA_200'], color='#9932CC', width=2.5),
                
                # Panel 1 (9,3)
                mpf.make_addplot(y_75, panel=1, color='white', width=0),
                mpf.make_addplot(y_25, panel=1, fill_between=dict(y1=y_75, y2=y_25, color='white', alpha=0.08), width=0, color='white'),
                mpf.make_addplot(plot_df['K1'], panel=1, color='#FF4444', width=1.5),
                mpf.make_addplot(plot_df['D1'], panel=1, color='#FF9999', width=1.0),
                
                # Panel 2 (14,3)
                mpf.make_addplot(y_75, panel=2, color='white', width=0),
                mpf.make_addplot(y_25, panel=2, fill_between=dict(y1=y_75, y2=y_25, color='white', alpha=0.08), width=0, color='white'),
                mpf.make_addplot(plot_df['K2'], panel=2, color='#FF8800', width=1.5),
                mpf.make_addplot(plot_df['D2'], panel=2, color='#FFCC00', width=1.0),
                
                # Panel 3 (44,4)
                mpf.make_addplot(y_75, panel=3, color='white', width=0),
                mpf.make_addplot(y_25, panel=3, fill_between=dict(y1=y_75, y2=y_25, color='white', alpha=0.08), width=0, color='white'),
                mpf.make_addplot(plot_df['K3'], panel=3, color='#0088FF', width=1.5),
                mpf.make_addplot(plot_df['D3'], panel=3, color='#00FFFF', width=1.0),
                
                # Panel 4 (60,10)
                mpf.make_addplot(y_75, panel=4, color='white', width=0),
                mpf.make_addplot(y_25, panel=4, fill_between=dict(y1=y_75, y2=y_25, color='white', alpha=0.08), width=0, color='white'),
                mpf.make_addplot(plot_df['K4'], panel=4, color='#00CC00', width=1.5),
                mpf.make_addplot(plot_df['D4'], panel=4, color='#66FF66', width=1.0),
            ]

            if signal:
                t_s = np.full(len(plot_df), tp); s_s = np.full(len(plot_df), sl); e_s = np.full(len(plot_df), entry)
                apds.append(mpf.make_addplot(t_s, color='green', width=0.5))
                apds.append(mpf.make_addplot(e_s, fill_between=dict(y1=t_s.tolist(), y2=e_s.tolist(), color='green', alpha=0.15), width=0))
                apds.append(mpf.make_addplot(s_s, color='red', width=0.5))
                apds.append(mpf.make_addplot(e_s, fill_between=dict(y1=e_s.tolist(), y2=s_s.tolist(), color='red', alpha=0.15), width=0))

            plot_kwargs = dict(
                type='candle', 
                style=mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mpf.make_marketcolors(up='#00ff00', down='#ff0000', inherit=True)), 
                addplot=apds,
                title=f"{symbol} ({timeframe})",
                returnfig=True, 
                volume=False, 
                panel_ratios=(3, 1, 1, 1, 1),
                tight_layout=True,
                # 修正重點 1: X 軸時間格式 (只顯示時間，不旋轉)
                datetime_format='%H:%M', 
                xrotation=0,
                # 修正重點 2: 畫出 25, 75 虛線 (輔助線)
                hlines=dict(hlines=[25, 75], colors=['gray', 'gray'], linestyle='--', linewidths=0.8)
            )

            if div_pts:
                line_data = [(div_pts[0], div_pts[2]), (div_pts[1], div_pts[3])]
                plot_kwargs['alines'] = dict(alines=line_data, colors='yellow', linewidths=2.5, alpha=0.9)

            fig, axlist = mpf.plot(plot_df, **plot_kwargs)

            # --- 深度客製化 Axes (解決刻度不對齊) ---
            curr_row = plot_df.iloc[-1]
            
            # 定義副圖資訊: (Axes索引, 標籤文字, 顏色)
            # axlist[0]=Main, axlist[1]=Main_Secondary...
            # 通常副圖的 Primary Axis 是偶數索引: 2, 4, 6, 8
            panels_info = [
                (2, f"Stoch 9 3 1  {curr_row['K1']:.2f}", '#FF4444'),
                (4, f"Stoch 14 3 1  {curr_row['K2']:.2f}", '#FF8800'),
                (6, f"Stoch 44 4 1  {curr_row['K3']:.2f}", '#0088FF'),
                (8, f"Stoch 60 10 1  {curr_row['K4']:.2f}", '#00CC00')
            ]

            for ax_idx, label_text, color in panels_info:
                if ax_idx < len(axlist):
                    ax = axlist[ax_idx]
                    
                    # 修正重點 3: 強制固定 Y 軸範圍與刻度
                    ax.set_ylim(0, 100)
                    ax.set_yticks([0, 25, 50, 75, 100])
                    ax.set_yticklabels([0, 25, 50, 75, 100], fontsize=9)
                    
                    # 確保刻度在右邊
                    ax.yaxis.tick_right()
                    
                    # 移除外部 Y 軸標題
                    ax.set_ylabel("")
                    
                    # 標籤內移
                    ax.text(0.01, 0.85, label_text, transform=ax.transAxes, 
                            color=color, fontsize=10, fontweight='bold', ha='left')

            st.pyplot(fig)
            
            if signal:
                st.caption("圖表說明：主圖黃線為背離線。紅綠色塊為止損止盈。")
