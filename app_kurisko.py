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
**策略核心 (四重輪動)：**
1. **趨勢**：價格需在 50 & 200 EMA 之上 (做多)。
2. **動能**：慢速 Stoch (60,10) 維持高檔 (>80)，快速 Stoch (9,3) 回調至低檔 (<20)。
3. **週期**：專注於 15分鐘 與 1小時 級別。
""")

# ==========================================
# 2. 側邊欄設定
# ==========================================
with st.sidebar:
    st.header("參數設定")
    symbol = st.text_input("輸入代號 (如 BTC-USD, TSLA, 2330.TW)", value="BTC-USD")
    
    # 修改 1: 移除 4h/1d，新增 15m
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
# 3. 核心指標計算函數 (手寫公式版 - 穩定不報錯)
# ==========================================

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def calculate_stoch(df, k_period, d_period, smooth_k):
    # 1. 計算 K 週期內的最高與最低
    low_min = df['Low'].rolling(window=k_period).min()
    high_max = df['High'].rolling(window=k_period).max()
    
    # 2. 計算 Fast K (避免分母為0)
    denom = high_max - low_min
    denom = denom.replace(0, 0.000001) 
    k_fast = 100 * ((df['Close'] - low_min) / denom)
    
    # 3. 計算平滑後的 Full K (我們要的線)
    k_full = k_fast.rolling(window=smooth_k).mean()
    
    return k_full

def get_data(symbol, interval):
    try:
        # 根據短線需求調整抓取長度
        # 15m 只能抓最近 60 天，這裡設 1mo (1個月) 保證有數據且速度快
        period = "1mo" if interval == "15m" else "6mo"
        
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        
        # 數據清理
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        if df.empty:
            return None, "抓取不到數據，請確認代號。"

        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # --- 計算指標 ---
        # 1. EMAs
        df['EMA_20'] = calculate_ema(df['Close'], ema_fast)
        df['EMA_50'] = calculate_ema(df['Close'], ema_mid)
        df['EMA_200'] = calculate_ema(df['Close'], ema_slow)

        # 2. Stochastics (四重輪動參數)
        # 快速: 9, 3, 1
        df['Stoch1_K'] = calculate_stoch(df, 9, 1, 3)
        # 中快: 14, 3, 1
        df['Stoch2_K'] = calculate_stoch(df, 14, 1, 3)
        # 中慢: 44, 4, 1
        df['Stoch3_K'] = calculate_stoch(df, 44, 1, 4)
        # 慢速: 60, 10, 1
        df['Stoch4_K'] = calculate_stoch(df, 60, 1, 10)

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
    
    # 趨勢判斷
    trend = "震盪/不明"
    if curr['Close'] > curr['EMA_50'] and curr['Close'] > curr['EMA_200']:
        trend = "🟢 強勢多頭"
    elif curr['Close'] < curr['EMA_50'] and curr['Close'] < curr['EMA_200']:
        trend = "🔴 空頭趨勢"
    
    # 牛旗訊號
    signal = "無特殊訊號"
    is_uptrend = curr['Close'] > curr['EMA_200']
    
    if is_uptrend:
        if curr['Stoch4_K'] > slow_stoch_threshold: # 慢速強
            if curr['Stoch1_K'] < 25: # 快速弱 (回調)
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
            c2.caption("短線位置 (<20 超賣)")
            
            c3.metric("慢速 Stoch (60,10)", f"{curr_data['Stoch4_K']:.1f}")
            c3.caption(f"長線動能 (>{slow_stoch_threshold} 強勢)")

            st.markdown("---")

            # 修改 2: 圖表只畫最近 60 根 K 線，讓畫面放大清晰
            st.subheader(f"📊 K線圖表 (最近 60 根)")
            
            plot_df = df.tail(60) # 只取最後 60 筆，解決圖太小的問題
            
            apds = [
                mpf.make_addplot(plot_df['EMA_20'], color='cyan', width=1.0),
                mpf.make_addplot(plot_df['EMA_50'], color='orange', width=1.5),
                mpf.make_addplot(plot_df['EMA_200'], color='white', width=2.0),
                
                # 四重 Stochastics
                mpf.make_addplot(plot_df['Stoch1_K'], panel=1, color='#FF0000', width=1.5, ylabel='Stoch'), # 紅 (快速)
                mpf.make_addplot(plot_df['Stoch2_K'], panel=1, color='#FFA500', width=1.0), 
                mpf.make_addplot(plot_df['Stoch3_K'], panel=1, color='#00FFFF', width=1.0), 
                mpf.make_addplot(plot_df['Stoch4_K'], panel=1, color='#00FF00', width=2.0), # 綠 (慢速)
            ]
            
            mc = mpf.make_marketcolors(up='#00ff00', down='#ff0000', inherit=True)
            s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc, gridstyle=':')
            
            fig, ax = mpf.plot(
                plot_df,
                type='candle',
                style=s,
                addplot=apds,
                title=f"{symbol} ({timeframe})",
                returnfig=True,
                volume=False,
                panel_ratios=(7, 3), # 加大主圖比例
                hlines=dict(hlines=[20, 80], colors=['gray', 'gray'], linestyle='--', linewidths=0.8)
            )
            st.pyplot(fig)
