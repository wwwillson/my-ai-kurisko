import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import numpy as np

# ==========================================
# 1. 頁面設定
# ==========================================
st.set_page_config(layout="wide", page_title="John Kurisko 四重輪動交易系統")
st.title("🛡️ John Kurisko 四重輪動交易系統 (Four-Fold Rotation)")
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
# 3. 數據抓取與指標計算
# ==========================================
def get_data(symbol, interval):
    # 根據週期調整抓取長度
    period = "1y" if interval == "1d" else "2mo"
    if interval == "1h": period = "1mo"
    
    df = yf.download(symbol, period=period, interval=interval, progress=False)
    
    # 處理 MultiIndex
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    if df.empty:
        return None, "抓取不到數據"

    # --- 計算指標 ---
    
    # 1. EMAs
    df['EMA_20'] = ta.ema(df['Close'], length=ema_fast)
    df['EMA_50'] = ta.ema(df['Close'], length=ema_mid)
    df['EMA_200'] = ta.ema(df['Close'], length=ema_slow)

    # 2. Stochastics (四重輪動)
    # 參數格式: (K週期, Smooth K, Smooth D)
    # 注意: pandas_ta stoch 返回 k 和 d 兩條線，影片策略主要關注 K 線的走勢
    
    # 第1組 (快速): 9, 3, 1
    stoch1 = ta.stoch(df['High'], df['Low'], df['Close'], k=9, d=1, smooth_k=3)
    df['Stoch1_K'] = stoch1['STOCHk_9_1_3']
    
    # 第2組 (中快): 14, 3, 1
    stoch2 = ta.stoch(df['High'], df['Low'], df['Close'], k=14, d=1, smooth_k=3)
    df['Stoch2_K'] = stoch2['STOCHk_14_1_3']
    
    # 第3組 (中慢): 44, 4, 1
    stoch3 = ta.stoch(df['High'], df['Low'], df['Close'], k=44, d=1, smooth_k=4)
    df['Stoch3_K'] = stoch3['STOCHk_44_1_4']
    
    # 第4組 (慢速): 60, 10, 1
    stoch4 = ta.stoch(df['High'], df['Low'], df['Close'], k=60, d=1, smooth_k=10)
    df['Stoch4_K'] = stoch4['STOCHk_60_1_10']

    return df, None

# ==========================================
# 4. 分析邏輯 (牛旗/趨勢判斷)
# ==========================================
def analyze_market(df):
    curr = df.iloc[-1]
    
    # 趨勢判斷
    trend = "震盪/不明"
    if curr['Close'] > curr['EMA_50'] and curr['Close'] > curr['EMA_200']:
        trend = "🟢 強勢多頭 (價格 > 50 & 200 EMA)"
    elif curr['Close'] < curr['EMA_50'] and curr['Close'] < curr['EMA_200']:
        trend = "🔴 空頭趨勢 (價格 < 50 & 200 EMA)"
    
    # 訊號識別 (仿影片：牛旗 Strong Trend Pullback)
    # 條件：趨勢向上 + 慢速Stoch高檔 + 快速Stoch低檔
    signal = "無特殊訊號"
    
    is_uptrend = curr['Close'] > curr['EMA_200']
    
    # 牛旗偵測
    if is_uptrend:
        if curr['Stoch4_K'] > slow_stoch_threshold: # 慢速動量強勁
            if curr['Stoch1_K'] < 25: # 快速動量回調到位
                signal = "🔥 牛旗買點 (Bull Flag): 強趨勢回調到位"
            elif curr['Stoch1_K'] < 50:
                signal = "👀 觀察中: 趨勢強勁，正在回調"
    
    # 熊旗偵測 (反向)
    is_downtrend = curr['Close'] < curr['EMA_200']
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

            # 3. 繪製圖表 (仿照影片風格)
            st.subheader(f"📊 {symbol} [{timeframe}] 四重輪動圖表")
            
            # 準備繪圖資料 (只取最近 100-150 根 K 線以看清細節)
            plot_df = df.tail(150)
            
            # 設定 EMA 線
            apds = [
                mpf.make_addplot(plot_df['EMA_20'], color='cyan', width=1.0),
                mpf.make_addplot(plot_df['EMA_50'], color='orange', width=1.5),
                mpf.make_addplot(plot_df['EMA_200'], color='white', width=2.0),
                
                # 四重 Stochastics (畫在同一個 Panel，或者分開)
                # 影片中通常是疊加或者分開，這裡我們放在 Panel 1 (下方)
                # 快速 (黃/紅)
                mpf.make_addplot(plot_df['Stoch1_K'], panel=1, color='#FF0000', width=1.0, ylabel='Stoch Fast'), # 紅
                mpf.make_addplot(plot_df['Stoch2_K'], panel=1, color='#FFA500', width=1.0), # 橘
                
                # 慢速 (藍/綠)
                mpf.make_addplot(plot_df['Stoch3_K'], panel=1, color='#00FFFF', width=1.0), # 青
                mpf.make_addplot(plot_df['Stoch4_K'], panel=1, color='#00FF00', width=1.5, ylabel='Stoch Slow'), # 綠
            ]
            
            # 自訂風格 (深色背景，類似影片)
            mc = mpf.make_marketcolors(up='#00ff00', down='#ff0000', inherit=True)
            s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc, gridstyle=':')
            
            # 繪製
            fig, ax = mpf.plot(
                plot_df,
                type='candle',
                style=s,
                addplot=apds,
                title=f"{symbol} - EMA & Quad Stochs",
                returnfig=True,
                volume=False,
                panel_ratios=(6, 3), # 上下圖比例
                hlines=dict(hlines=[20, 80], colors=['gray', 'gray'], linestyle='--', linewidths=0.5) # Stoch 的 20/80 線
            )
            
            st.pyplot(fig)
            
            st.info("""
            **圖表說明：**
            - **主圖 (K線)**：
                - ⬜ 白色線：200 EMA (長期趨勢)
                - 🟧 橘色線：50 EMA (中期關鍵位)
                - 🟦 青色線：20 EMA (短期支撐)
            - **副圖 (Stochastics)**：
                - 🟥 紅色線：最快指標 (9,3) -> 用於尋找入場觸發點 (Trigger)。
                - 🟩 綠色線：最慢指標 (60,10) -> 用於確認大趨勢方向。
            
            **如何使用 (依據影片)：**
            1. 觀察綠色線 (慢速) 是否維持在高檔 (>80)。
            2. 等待紅色線 (快速) 掉入低檔 (<20)。
            3. 當價格回到橘色線 (50 EMA) 附近且符合上述條件時，為高勝率買點。
            """)
