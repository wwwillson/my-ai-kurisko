import streamlit as st
import yfinance as yf
import pandas as pd
import mplfinance as mpf
import numpy as np

# ==========================================
# 1. 頁面設定
# ==========================================
st.set_page_config(layout="wide", page_title="John Kurisko 短線交易系統")
st.title("🛡️ John Kurisko 短線交易系統 (15m/1h)")
st.markdown("""
**策略核心：**
1. **趨勢**：價格需在 50 & 200 EMA 之上 (做多)。
2. **動能**：慢速 Stoch (60,10) 維持高檔 (>80)，快速 Stoch (9,3) 回調至低檔 (<20)。
""")

# ==========================================
# 2. 側邊欄設定
# ==========================================
with st.sidebar:
    st.header("參數設定")
    symbol = st.text_input("輸入代號 (如 BTC-USD, TSLA, 2330.TW)", value="BTC-USD")
    timeframe = st.selectbox("時間週期", ["15m", "1h"], index=0)
    
    st.markdown("---")
    st.subheader("EMA 設定")
    ema_fast = st.number_input("EMA 快", value=20)
    ema_mid = st.number_input("EMA 中", value=50)
    ema_slow = st.number_input("EMA 慢", value=200)
    
    st.markdown("---")
    st.subheader("信號過濾")
    slow_stoch_threshold = st.slider("慢速 Stoch 強勢區間 (>數值)", 50, 90, 80)

# ==========================================
# 3. 核心指標計算函數
# ==========================================

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

def get_data(symbol, interval):
    try:
        # 15m 抓取最近 5 天就足夠畫 60 根 K 線，但為了 EMA 準確，我們抓 1 個月
        period = "1mo" if interval == "15m" else "6mo"
        
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        
        # 數據清理 (MultiIndex)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        if df.empty:
            return None, "抓取不到數據。"

        # 移除時區
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # --- 關鍵修正：移除價格為 0 或空的異常值 (這就是導致圖表壓扁的原因) ---
        df = df[df['Close'] > 0]
        df = df.dropna()

        # --- 計算指標 ---
        df['EMA_20'] = calculate_ema(df['Close'], ema_fast)
        df['EMA_50'] = calculate_ema(df['Close'], ema_mid)
        df['EMA_200'] = calculate_ema(df['Close'], ema_slow)

        # Stochastics
        df['Stoch1_K'] = calculate_stoch(df, 9, 1, 3)
        df['Stoch2_K'] = calculate_stoch(df, 14, 1, 3)
        df['Stoch3_K'] = calculate_stoch(df, 44, 1, 4)
        df['Stoch4_K'] = calculate_stoch(df, 60, 1, 10)

        # 再次移除指標計算後產生的 NaN (避免繪圖錯誤)
        df = df.dropna()

        return df, None

    except Exception as e:
        return None, f"發生錯誤: {str(e)}"

# ==========================================
# 4. 分析邏輯
# ==========================================
def analyze_market(df):
    if len(df) < 2: return "數據不足", "無", df.iloc[-1]
    curr = df.iloc[-1]
    
    # 趨勢
    trend = "震盪/不明"
    if curr['Close'] > curr['EMA_50'] and curr['Close'] > curr['EMA_200']:
        trend = "🟢 強勢多頭"
    elif curr['Close'] < curr['EMA_50'] and curr['Close'] < curr['EMA_200']:
        trend = "🔴 空頭趨勢"
    
    # 訊號
    signal = "無特殊訊號"
    is_uptrend = curr['Close'] > curr['EMA_200']
    
    if is_uptrend:
        if curr['Stoch4_K'] > slow_stoch_threshold: 
            if curr['Stoch1_K'] < 25: 
                signal = "🔥 牛旗買點 (強勢回調)"
            elif curr['Stoch1_K'] < 50:
                signal = "👀 觀察中 (正在回調)"
    
    return trend, signal, curr

# ==========================================
# 5. 執行與繪圖
# ==========================================
if st.button("🚀 開始分析", type="primary"):
    with st.spinner(f"正在計算 {symbol} ({timeframe}) 數據..."):
        df, err = get_data(symbol, timeframe)
        
        if err:
            st.error(err)
        elif df is not None:
            trend_str, signal_str, curr_data = analyze_market(df)
            
            # 數據看板
            st.markdown(f"### 🎯 訊號：{signal_str}")
            c1, c2, c3 = st.columns(3)
            c1.metric("價格", f"{curr_data['Close']:.2f}")
            c1.info(f"趨勢: {trend_str}")
            c2.metric("快速 Stoch (9,3)", f"{curr_data['Stoch1_K']:.1f}")
            c3.metric("慢速 Stoch (60,10)", f"{curr_data['Stoch4_K']:.1f}")

            st.markdown("---")

            # 圖表繪製區
            st.subheader(f"📊 K線圖表 (最近 60 根)")
            
            # 只取最後 60 筆
            plot_df = df.tail(60)
            
            # 設定指標線 (Addplots)
            apds = [
                mpf.make_addplot(plot_df['EMA_20'], color='cyan', width=1.5),
                mpf.make_addplot(plot_df['EMA_50'], color='orange', width=2.0),
                mpf.make_addplot(plot_df['EMA_200'], color='white', width=2.5),
                
                # Stochs (Panel 1)
                mpf.make_addplot(plot_df['Stoch1_K'], panel=1, color='#FF3333', width=1.5, ylabel='Stoch'), # 紅
                mpf.make_addplot(plot_df['Stoch2_K'], panel=1, color='#FFAA33', width=1.0), 
                mpf.make_addplot(plot_df['Stoch3_K'], panel=1, color='#33AAFF', width=1.0), 
                mpf.make_addplot(plot_df['Stoch4_K'], panel=1, color='#33FF33', width=2.0), # 綠
            ]
            
            # --- 修正重點：使用 'yahoo' 風格 (對比度高)，並強制關閉 Volume 以防干擾 ---
            # 這樣可以確保 K 線不會是黑色的，背景也不會造成誤判
            
            fig, ax = mpf.plot(
                plot_df,
                type='candle',
                style='yahoo', # 改用 Yahoo 風格，確保蠟燭清晰可見
                addplot=apds,
                title=f"{symbol} ({timeframe})",
                returnfig=True,
                volume=False, # 關閉成交量，讓畫面更專注於價格
                panel_ratios=(7, 3),
                tight_layout=True,
                hlines=dict(hlines=[20, 80], colors=['gray', 'gray'], linestyle='--', linewidths=1.0)
            )
            st.pyplot(fig)
