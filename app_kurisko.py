import streamlit as st
import yfinance as yf
import pandas as pd
import mplfinance as mpf
import numpy as np

# ==========================================
# 1. 頁面設定
# ==========================================
st.set_page_config(layout="wide", page_title="John Kurisko 四重輪動交易系統")
st.title("🛡️ John Kurisko 四重輪動交易系統")
st.markdown("""
**策略來源：** 基於傳奇交易員 John Kurisko 的 30 年經驗系統。
**核心邏輯：** 
1. 使用 **3條 EMA** (20, 50, 200) 確定主趨勢。
2. 使用 **4組 Stochastic** 捕捉動量輪動與背離。
3. **牛旗訊號**：當慢速動量維持高檔，而快速動量進入超賣區時，視為強勢回調買點。
""")

# ==========================================
# 2. 側邊欄設定
# ==========================================
with st.sidebar:
    st.header("參數設定")
    symbol = st.text_input("輸入代號 (如 BTC-USD, TSLA, 2330.TW)", value="BTC-USD")
    timeframe = st.selectbox("時間週期", ["1h", "4h", "1d"], index=1)
    
    st.markdown("---")
    st.subheader("EMA 設定")
    ema_fast = st.number_input("EMA 快", value=20)
    ema_mid = st.number_input("EMA 中", value=50)
    ema_slow = st.number_input("EMA 慢", value=200)
    
    st.markdown("---")
    st.subheader("信號過濾")
    slow_stoch_threshold = st.slider("慢速 Stoch 強勢區間 (>數值)", 50, 90, 80, help="影片建議牛旗形態中，慢速指標應維持在85以上")

# ==========================================
# 3. 核心指標計算函數 (手寫公式版 - 最穩定)
# ==========================================

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def calculate_stoch(df, k_period, d_period, smooth_k):
    # 1. 計算由過去 k_period 天的最高價與最低價
    low_min = df['Low'].rolling(window=k_period).min()
    high_max = df['High'].rolling(window=k_period).max()
    
    # 2. 計算未平滑的 %K (Fast K)
    # 避免分母為 0
    denom = high_max - low_min
    denom = denom.replace(0, 0.000001) 
    
    k_fast = 100 * ((df['Close'] - low_min) / denom)
    
    # 3. 計算平滑後的 %K (Full K) -> 這是我們要畫的線
    k_full = k_fast.rolling(window=smooth_k).mean()
    
    # 4. 計算 %D (Signal Line) -> 雖然四重輪動主要看K，但公式需要完整
    d_full = k_full.rolling(window=d_period).mean()
    
    return k_full

def get_data(symbol, interval):
    try:
        # 根據週期調整抓取長度
        period = "2y" if interval == "1d" else "6mo"
        if interval == "1h": period = "2mo"
        
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        
        # --- 數據清理 (解決 yfinance 多層索引問題) ---
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # 確保數據不為空
        if df.empty:
            return None, "抓取不到數據，請確認代號。"

        # 移除時區資訊 (避免圖表報錯)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # --- 計算指標 (使用上方自定義函數) ---
        
        # 1. EMAs
        df['EMA_20'] = calculate_ema(df['Close'], ema_fast)
        df['EMA_50'] = calculate_ema(df['Close'], ema_mid)
        df['EMA_200'] = calculate_ema(df['Close'], ema_slow)

        # 2. Stochastics (四重輪動)
        # 參數格式: (K週期, Smooth K, Smooth D) -> 注意：這裡主要需要 K 和 Smooth K
        
        # 第1組 (快速): 9, 3, 1 (k=9, smooth_k=3, d=1)
        df['Stoch1_K'] = calculate_stoch(df, k_period=9, d_period=1, smooth_k=3)
        
        # 第2組 (中快): 14, 3, 1
        df['Stoch2_K'] = calculate_stoch(df, k_period=14, d_period=1, smooth_k=3)
        
        # 第3組 (中慢): 44, 4, 1
        df['Stoch3_K'] = calculate_stoch(df, k_period=44, d_period=1, smooth_k=4)
        
        # 第4組 (慢速): 60, 10, 1
        df['Stoch4_K'] = calculate_stoch(df, k_period=60, d_period=1, smooth_k=10)

        # 移除包含 NaN 的行 (避免畫圖錯誤)
        df = df.dropna()

        return df, None

    except Exception as e:
        return None, f"發生錯誤: {str(e)}"

# ==========================================
# 4. 分析邏輯 (牛旗/趨勢判斷)
# ==========================================
def analyze_market(df):
    if len(df) < 2:
        return "數據不足", "無", df.iloc[-1]

    curr = df.iloc[-1]
    
    # 趨勢判斷
    trend = "震盪/不明"
    if curr['Close'] > curr['EMA_50'] and curr['Close'] > curr['EMA_200']:
        trend = "🟢 強勢多頭 (價格 > 50 & 200 EMA)"
    elif curr['Close'] < curr['EMA_50'] and curr['Close'] < curr['EMA_200']:
        trend = "🔴 空頭趨勢 (價格 < 50 & 200 EMA)"
    
    # 訊號識別 (仿影片：牛旗 Strong Trend Pullback)
    signal = "無特殊訊號"
    
    is_uptrend = curr['Close'] > curr['EMA_200']
    is_downtrend = curr['Close'] < curr['EMA_200']
    
    # 牛旗偵測
    if is_uptrend:
        if curr['Stoch4_K'] > slow_stoch_threshold: # 慢速動量強勁
            if curr['Stoch1_K'] < 25: # 快速動量回調到位
                signal = "🔥 牛旗買點 (Bull Flag): 強趨勢回調到位"
            elif curr['Stoch1_K'] < 50:
                signal = "👀 觀察中: 趨勢強勁，正在回調"
    
    # 熊旗偵測
    if is_downtrend:
        if curr['Stoch4_K'] < (100 - slow_stoch_threshold): # 慢速動量極弱
            if curr['Stoch1_K'] > 75: # 快速動量反彈到位
                signal = "❄️ 熊旗賣點 (Bear Flag): 弱勢反彈到位"

    return trend, signal, curr

# ==========================================
# 5. 執行與繪圖
# ==========================================
if st.button("🚀 開始四重輪動分析", type="primary"):
    with st.spinner("正在計算四重隨機指標與 EMA 結構..."):
        df, err = get_data(symbol, timeframe)
        
        if err:
            st.error(err)
        elif df is not None:
            # 1. 執行分析
            trend_str, signal_str, curr_data = analyze_market(df)
            
            # 2. 顯示數據面板
            st.markdown(f"### 🎯 分析結果：{signal_str}")
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("目前價格", f"{curr_data['Close']:.2f}")
            c1.info(f"趨勢: {trend_str}")
            
            c2.metric("快速 Stoch (9,3)", f"{curr_data['Stoch1_K']:.1f}")
            c2.caption("反應最快，<20 為超賣")
            
            c3.metric("慢速 Stoch (60,10)", f"{curr_data['Stoch4_K']:.1f}")
            c3.caption(f"趨勢強度，>{slow_stoch_threshold} 為強勢")
            
            c4.metric("50 EMA", f"{curr_data['EMA_50']:.2f}")
            c4.caption("關鍵多空支撐")

            st.markdown("---")

            # 3. 繪製圖表
            st.subheader(f"📊 {symbol} [{timeframe}] 四重輪動圖表")
            
            # 準備繪圖資料 (只取最近 100 根)
            plot_df = df.tail(100)
            
            # 設定 EMA 線
            apds = [
                mpf.make_addplot(plot_df['EMA_20'], color='cyan', width=1.0),
                mpf.make_addplot(plot_df['EMA_50'], color='orange', width=1.5),
                mpf.make_addplot(plot_df['EMA_200'], color='white', width=2.0),
                
                # 四重 Stochastics
                mpf.make_addplot(plot_df['Stoch1_K'], panel=1, color='#FF0000', width=1.0, ylabel='Stochs'), # 紅
                mpf.make_addplot(plot_df['Stoch2_K'], panel=1, color='#FFA500', width=1.0), # 橘
                mpf.make_addplot(plot_df['Stoch3_K'], panel=1, color='#00FFFF', width=1.0), # 青
                mpf.make_addplot(plot_df['Stoch4_K'], panel=1, color='#00FF00', width=1.5), # 綠
            ]
            
            # 自訂風格
            mc = mpf.make_marketcolors(up='#00ff00', down='#ff0000', inherit=True)
            s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc, gridstyle=':')
            
            # 繪製
            fig, ax = mpf.plot(
                plot_df,
                type='candle',
                style=s,
                addplot=apds,
                title=f"{symbol} - Four-Fold Rotation",
                returnfig=True,
                volume=False,
                panel_ratios=(6, 3),
                hlines=dict(hlines=[20, 80], colors=['gray', 'gray'], linestyle='--', linewidths=0.5)
            )
            
            st.pyplot(fig)
            
            st.info("""
            **圖表說明：**
            - **主圖 (K線)**：⬜200 EMA (長期), 🟧50 EMA (中期), 🟦20 EMA (短期)
            - **副圖 (Stochastics)**：
                - 🟥 紅色線 (9,3)：入場扳機 (Trigger)。
                - 🟩 綠色線 (60,10)：大趨勢動量。
            """)
