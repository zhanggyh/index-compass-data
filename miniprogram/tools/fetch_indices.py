#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
指数罗盘 · 真实数据采集脚本（基于 AKShare，免费开源、无需账号、无需付费）

作用：
    抓取各板块的 PE / PB / 股息率 / 历史分位 / 近12月走势，
    输出 utils/indices_bundle.js —— 一个可直接被小程序 require 的数据文件，
    小程序编译时会把这份数据直接打进安装包，无需云开发、零成本。

运行（在你自己的电脑，命令行）：
    pip install -r requirements.txt
    python fetch_indices.py

数据源说明（全部免费公开接口）：
    中证指数官网  ak.stock_zh_index_hist_csindex  → A股/中证系指数：滚动PE + 每日收盘
    百度证券      ak.stock_hk_valuation_baidu      → 港股指数：PE(TTM) + 近一年历史
    新浪财经      ak.index_us_stock_sina           → 美股指数：每日收盘（算价格分位）
    上金所        ak.spot_hist_sge                  → 黄金：每日收盘价
    东方财富期货  ak.futures_foreign_commodity_realtime → 原油/白银/铜：最新价
    债券收益率    ak.bond_zh_us_rate                → 中美国债收益率
    申万行业分析  ak.index_analysis_daily_sw        → 行业PB/股息率/换手率
    乐咕乐股      ak.stock_market_pe_lg             → 全市场平均PE + 历史分位

容错设计：
    任何板块抓不到都会自动回退到 DEFAULTS 兜底值并打印 WARNING，
    保证脚本永远输出结构完整的文件，不会中断。
"""

import json
import os
import datetime
import math
import time

# ---------------------------------------------------------------
# 1) 板块清单 + 兜底默认数值
#    src 字段标记数据来源，决定脚本走哪条抓取路径：
#      csindex     → 中证官网（PE+分位+走势）
#      baidu_hk    → 百度证券（港股PE+分位）
#      sina_us     → 新浪美股（指数/ETF价格+分位）
#      sina_global → 新浪全球（海外指数价格+分位）
#      sge         → 上金所（黄金）
#      futures     → 东财期货（原油/银/铜）
#      bond        → 债券收益率
#      external    → 无免费源，保留兜底值
#
#    PE 数据来源（海外指数无实时 PE 接口，使用权威研究机构定期发布的值）：
#      Bloomberg/Invesco Valuation Tracker（2026-09-30）
#      Siblis Research Global Equity Valuation（2026-09-30）
#      ValuEngine S&P 500 Sector P/E（2026-10）
#      东方财富/国元证券 全球市场周报（2026-08）
# ---------------------------------------------------------------
DEFAULTS = [
    # ===== 宽基 =====
    dict(code='000300', name='沪深300',    cat='宽基', market='A股', pe=12.69, pb=1.32, div=3.10, pct=40, heat=64, src='csindex'),
    dict(code='000905', name='中证500',    cat='宽基', market='A股', pe=22.29, pb=1.78, div=1.80, pct=54, heat=58, src='csindex'),
    dict(code='399006', name='创业板指',   cat='宽基', market='A股', pe=31.20, pb=3.90, div=0.90, pct=12, heat=71, src='sina_sz'),
    dict(code='000016', name='上证50',     cat='宽基', market='A股', pe=11.10, pb=1.15, div=4.00, pct=67, heat=49, src='csindex'),
    dict(code='000688', name='科创50',     cat='宽基', market='A股', pe=59.76, pb=4.20, div=0.80, pct=61, heat=75, src='csindex'),
    dict(code='HSI',    name='恒生指数',   cat='宽基', market='港股', pe=8.90,  pb=0.92, div=4.20, pct=15, heat=52, src='baidu_hk', baidu='000001', hk='HSI'),
    dict(code='NDX',    name='纳斯达克100',cat='宽基', market='美股', pe=30.50, pb=8.20, div=0.70, pct=68, heat=83, src='sina_us', sina='.NDX'),
    dict(code='SPX',    name='标普500',    cat='宽基', market='美股', pe=24.10, pb=4.50, div=1.30, pct=75, heat=79, src='sina_us', sina='.INX'),
    dict(code='DJI',    name='道琼斯',     cat='宽基', market='美股', pe=24.50, pb=6.00, div=1.50, pct=72, heat=60, src='sina_us', sina='.DJI'),
    dict(code='RUT',    name='罗素2000',   cat='宽基', market='美股', pe=28.50, pb=2.10, div=1.30, pct=58, heat=55, src='sina_us', sina='IWV', peSrc='estimate'),

    # ===== 全球市场（价格用新浪全球指数，PE用权威研究机构发布值）=====
    dict(code='N225',  name='日经225',     cat='全球市场', market='日韩', pe=20.00, pb=1.80, div=2.00, pct=55, heat=62, src='sina_global', sina='NKY', peSrc='bloomberg'),
    dict(code='TPX',   name='东证指数',    cat='全球市场', market='日韩', pe=17.50, pb=1.83, div=2.13, pct=50, heat=55, src='sina_us', sina='TPX', peSrc='bloomberg'),
    dict(code='KOSPI', name='韩国KOSPI',   cat='全球市场', market='日韩', pe=12.50, pb=1.69, div=2.07, pct=25, heat=48, src='sina_global', sina='KOSPI', peSrc='bloomberg'),
    dict(code='DAX',   name='德国DAX',     cat='全球市场', market='欧洲', pe=17.20, pb=2.04, div=2.76, pct=45, heat=50, src='sina_global', sina='DAX', peSrc='siblis'),
    dict(code='CAC',   name='法国CAC40',   cat='全球市场', market='欧洲', pe=16.70, pb=1.96, div=3.39, pct=47, heat=48, src='sina_global', sina='CAC', peSrc='siblis'),
    dict(code='FTSE',  name='英国富时100', cat='全球市场', market='欧洲', pe=14.70, pb=2.31, div=3.40, pct=30, heat=45, src='sina_global', sina='UKX', peSrc='siblis'),
    dict(code='SX5E',  name='欧洲STOXX50', cat='全球市场', market='欧洲', pe=18.50, pb=1.70, div=2.60, pct=44, heat=49, src='sina_global', sina='SX5E', peSrc='research'),

    # ===== 行业 =====
    dict(code='399998', name='中证煤炭',   cat='行业', market='A股', pe=18.01, pb=1.39, div=4.66, pct=86, heat=60, src='csindex'),
    dict(code='931151', name='光伏产业',   cat='行业', market='A股', pe=25.71, pb=3.89, div=0.54, pct=49, heat=66, src='csindex'),
    dict(code='399997', name='中证白酒',   cat='行业', market='A股', pe=20.32, pb=5.50, div=2.51, pct=23, heat=55, src='csindex'),
    dict(code='399989', name='中证医疗',   cat='行业', market='A股', pe=27.14, pb=3.12, div=1.02, pct=20, heat=58, src='csindex'),
    dict(code='399967', name='中证军工',   cat='行业', market='A股', pe=47.15, pb=3.57, div=0.38, pct=18, heat=70, src='csindex'),
    dict(code='931865', name='半导体',     cat='行业', market='A股', pe=89.82, pb=4.50, div=0.40, pct=75, heat=80, src='csindex'),
    dict(code='399976', name='新能源车',   cat='行业', market='A股', pe=16.75, pb=2.19, div=1.26, pct=9,  heat=68, src='csindex'),
    dict(code='399986', name='中证银行',   cat='行业', market='A股', pe=7.47,  pb=0.44, div=5.62, pct=97, heat=45, src='csindex'),
    dict(code='399975', name='证券公司',   cat='行业', market='A股', pe=12.00, pb=1.02, div=3.26, pct=1,  heat=62, src='csindex'),
    dict(code='931775', name='中证地产',   cat='行业', market='A股', pe=29.56, pb=0.77, div=3.12, pct=86, heat=40, src='csindex'),
    dict(code='H30590', name='机器人',     cat='行业', market='A股', pe=40.78, pb=3.20, div=0.80, pct=47, heat=78, src='csindex'),
    dict(code='931160', name='通信设备',   cat='行业', market='A股', pe=30.88, pb=1.86, div=1.21, pct=74, heat=65, src='csindex'),
    dict(code='931723', name='光模块',     cat='行业', market='A股', pe=35.0, pb=4.00, div=0.60, pct=0,  heat=85, src='csindex'),
    dict(code='931071', name='人工智能',   cat='行业', market='A股', pe=35.83, pb=4.20, div=0.70, pct=31, heat=82, src='csindex'),
    dict(code='399971', name='中证传媒',   cat='行业', market='A股', pe=23.64, pb=1.72, div=1.62, pct=32, heat=58, src='csindex'),
    dict(code='930651', name='计算机',     cat='行业', market='A股', pe=28.17, pb=3.11, div=0.65, pct=2,  heat=67, src='csindex'),

    # ===== 主题策略 =====
    dict(code='930955', name='红利低波',   cat='主题策略', market='A股', pe=9.04,  pb=1.00, div=4.50, pct=86, heat=50, src='csindex'),
    dict(code='000922', name='中证红利',   cat='主题策略', market='A股', pe=9.01,  pb=0.95, div=4.80, pct=81, heat=48, src='csindex'),
    dict(code='000932', name='中证消费',   cat='主题策略', market='A股', pe=20.39, pb=4.80, div=2.20, pct=15, heat=53, src='csindex'),
    dict(code='000919', name='300价值',    cat='主题策略', market='A股', pe=8.73,  pb=1.05, div=4.20, pct=58, heat=47, src='csindex'),
    dict(code='932039', name='央企股东回报', cat='主题策略', market='A股', pe=13.2,  pb=0.95, div=4.00, pct=38, heat=52, src='csindex'),

    # ===== 美股细分（价格用新浪ETF代理，PE用ValuEngine 2026-10）=====
    dict(code='SOX',    name='费城半导体', cat='美股细分', market='美股', pe=28.00, pb=7.00, div=0.90, pct=70, heat=88, src='sina_us', sina='.SOX'),
    dict(code='NBI',    name='纳指生物科技',cat='美股细分',market='美股', pe=28.00, pb=3.50, div=0.50, pct=25, heat=60, src='sina_us', sina='.NBI', peSrc='estimate'),
    dict(code='S5INFT', name='标普500信息科技',cat='美股细分',market='美股', pe=30.00, pb=8.00, div=0.80, pct=72, heat=80, src='sina_us', sina='XLK', peSrc='valuengine'),
    dict(code='S5ENRS', name='标普500能源', cat='美股细分', market='美股', pe=12.50, pb=2.20, div=3.50, pct=35, heat=55, src='sina_us', sina='XLE', peSrc='valuengine'),
    dict(code='S5FINL', name='标普500金融', cat='美股细分', market='美股', pe=15.50, pb=1.50, div=2.50, pct=55, heat=52, src='sina_us', sina='XLF', peSrc='valuengine'),

    # ===== 商品（无PE，用价格衡量历史分位）=====
    dict(code='AU9999', name='黄金',     cat='商品', market='商品', type='commodity', price=860.31, pct=62, heat=72, mLabel='金价(元/克)',   mVal=860.31, src='sge'),
    dict(code='WTI',    name='原油(WTI)', cat='商品', market='商品', type='commodity', price=101.04, pct=45, heat=55, mLabel='WTI(美元/桶)', mVal=101.04, src='futures', fut='CL'),
    dict(code='XAG',    name='白银',     cat='商品', market='商品', type='commodity', price=54.24,  pct=50, heat=60, mLabel='银价(美元/盎司)', mVal=54.24, src='futures', fut='XAG'),
    dict(code='CU',     name='LME铜',    cat='商品', market='商品', type='commodity', price=664.59, pct=55, heat=52, mLabel='铜价(美元/吨)',  mVal=664.59, src='futures', fut='HG'),

    # ===== 债券（用收益率/指数衡量历史分位）=====
    dict(code='CGB10',  name='十年国债',   cat='债券', market='债券', type='bond', price=1.64, pct=28, heat=38, mLabel='收益率%', mVal=1.64, src='bond', bond='cn10'),
    dict(code='000832', name='中证转债',   cat='债券', market='债券', type='bond', price=452.89, pct=55, heat=50, mLabel='指数', mVal=452.89, src='csindex'),
    dict(code='CBA027', name='中债信用债', cat='债券', market='债券', type='bond', price=127.75, pct=65, heat=35, mLabel='指数', mVal=127.75, src='cbond', cbond='高等级信用债综合指数'),
    dict(code='CBA001', name='中债国债',   cat='债券', market='债券', type='bond', price=135.69, pct=72, heat=33, mLabel='指数', mVal=135.69, src='cbond', cbond='国债总指数'),
]


# ---------------------------------------------------------------
# 2) 通用工具
# ---------------------------------------------------------------
def gen_trend(base, pct):
    """兜底：本地生成一条平滑、末点落在 base 的 12 月走势。"""
    start = base * (1.12 if pct <= 30 else 1.05 if pct <= 70 else 0.93)
    out = []
    for i in range(12):
        t = i / 11
        v = start + (base - start) * t + math.sin(i * 1.3) * base * 0.012
        out.append(round(v, 1))
    out[11] = round(base, 1)
    return out


def percentile_of(series, current):
    """计算 current 在历史 series 中的百分位（0-100）。"""
    vals = [v for v in series if v is not None and v == v and v > 0]
    if len(vals) < 30 or current is None or current != current or current <= 0:
        return None
    below = sum(1 for v in vals if v <= current)
    return round(below / len(vals) * 100, 1)


def sample_every(series, n=12, max_points=250):
    """把长序列等距抽样成 n 个点，用作走势。自动跳过 None/NaN。
    max_points: 先截取最近 max_points 个交易日，避免采样到更早以前的数据。"""
    clean = [v for v in series if v is not None and v == v]
    if not clean:
        return []
    # 只保留最近 max_points 个数据点
    if len(clean) > max_points:
        clean = clean[-max_points:]
    if len(clean) < n:
        return [round(v, 2) for v in clean]
    step = (len(clean) - 1) / (n - 1)
    return [round(clean[int(round(i * step))], 2) for i in range(n)]


# 五档时间跨度：(key, 交易日数≈自然日, 显示标签)
TREND_RANGES = [
    ('y1',  250,  '近一年'),
    ('y2',  500,  '近两年'),
    ('y3',  750,  '近三年'),
    ('y5',  1250, '近五年'),
    ('y10', 2500, '近十年'),
]

def sample_ranges(series):
    """为一条长序列生成 5 档时间跨度的走势数组。每档抽样 12 个点。"""
    out = {}
    for key, days, _label in TREND_RANGES:
        out[key] = sample_every(series, 12, max_points=days)
    return out


def to_float(v):
    try:
        f = float(v)
        return f if f == f else None   # 过滤 NaN
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------
# 3) 各数据源抓取函数
# ---------------------------------------------------------------
def fetch_csindex(code, start='20160101', end=None, retries=3):
    """
    中证指数官网：滚动PE序列 + 收盘价序列 + 指数名称。
    该接口有频率限制，失败时采用较长退避后重试，避免加重限流。
    """
    import akshare as ak
    if end is None:
        end = datetime.date.today().strftime('%Y%m%d')
    last_err = None
    # 退避间隔逐步拉长，避免连续快速请求触发限流
    backoffs = [4, 9, 18]
    for attempt in range(retries):
        try:
            df = ak.stock_zh_index_hist_csindex(symbol=code, start_date=start, end_date=end)
            if df is None or len(df) == 0:
                last_err = '空数据'
                if attempt < retries - 1:
                    time.sleep(backoffs[attempt])
                continue
            pe_series, close_series = [], []
            for _, row in df.iterrows():
                pe_series.append(to_float(row.get('滚动市盈率')))
                close_series.append(to_float(row.get('收盘')))
            return dict(pe=pe_series, close=close_series, name=str(df.iloc[-1].get('指数中文简称') or ''))
        except Exception as e:
            last_err = str(e)[:80]
            if attempt < retries - 1:
                time.sleep(backoffs[attempt])
    raise RuntimeError(last_err or '未知错误')


def fetch_baidu_hk(symbol, indicator='市盈率(TTM)', period='近一年'):
    """百度证券：港股指数 PE(TTM) 历史。"""
    import akshare as ak
    df = ak.stock_hk_valuation_baidu(symbol=symbol, indicator=indicator, period=period)
    if df is None or len(df) == 0:
        return None
    vals = [to_float(v) for v in df['value'].tolist()]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return dict(series=vals, latest=vals[-1], date=str(df.iloc[-1].get('date')))


def fetch_sina_us(symbol):
    """新浪财经：美股指数每日收盘。"""
    import akshare as ak
    df = ak.index_us_stock_sina(symbol=symbol)
    if df is None or len(df) == 0:
        return None
    closes = [to_float(c) for c in df['close'].tolist()]
    closes = [c for c in closes if c is not None]
    if not closes:
        return None
    return dict(series=closes, latest=closes[-1], date=str(df.iloc[-1].get('date')))


def fetch_sge_gold():
    """上海黄金交易所：黄金每日收盘（元/克）。"""
    import akshare as ak
    df = ak.spot_hist_sge()
    if df is None or len(df) == 0:
        return None
    closes = [to_float(c) for c in df['close'].tolist()]
    closes = [c for c in closes if c is not None]
    if not closes:
        return None
    return dict(series=closes, latest=closes[-1], date=str(df.iloc[-1].get('date')))


def fetch_futures(symbol):
    """东方财富期货：原油/白银/铜 最新价。"""
    import akshare as ak
    df = ak.futures_foreign_commodity_realtime(symbol=symbol)
    if df is None or len(df) == 0:
        return None
    row = df.iloc[0]
    price = to_float(row.get('最新价'))
    if price is None:
        return None
    return dict(price=price, name=str(row.get('名称') or ''), date=str(row.get('日期') or ''))


def fetch_bond_rates():
    """中美国债收益率（一次拿全）。"""
    import akshare as ak
    df = ak.bond_zh_us_rate(start_date='20180101')
    if df is None or len(df) == 0:
        return None
    out = {}
    for key, col in (('cn10', '中国国债收益率10年'), ('cn2', '中国国债收益率2年'),
                     ('us10', '美国国债收益率10年'), ('us2', '美国国债收益率2年')):
        if col in df.columns:
            vals = [to_float(v) for v in df[col].tolist()]
            vals = [v for v in vals if v is not None]
            if vals:
                out[key] = dict(series=vals, latest=vals[-1], date=str(df.iloc[-1].get('日期')))
    return out


def fetch_sina_sz(code):
    """
    新浪财经：深市指数每日收盘（399xxx 系列，中证接口不支持）。
    代码需带 sz 前缀，如 399006 -> sz399006。
    """
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol='sz' + code)
    if df is None or len(df) == 0:
        return None
    closes = [to_float(c) for c in df['close'].tolist()]
    closes = [c for c in closes if c is not None]
    if not closes:
        return None
    return dict(series=closes, latest=closes[-1], date=str(df.iloc[-1].get('date')))


def fetch_sse_sz_valuation():
    """乐咕乐股：全市场涨跌统计（备用源）。"""
    import akshare as ak
    df = ak.stock_market_activity_legu()
    if df is None or len(df) == 0:
        return None
    return {str(r['item']): r['value'] for _, r in df.iterrows()}


def fetch_sina_hk(symbol):
    """
    新浪财经：港股指数每日收盘（HSI 恒生、HSCEI 国企、HSCCI 红筹、HSTECH 恒生科技）。
    """
    import akshare as ak
    df = ak.stock_hk_index_daily_sina(symbol=symbol)
    if df is None or len(df) == 0:
        return None
    closes = [to_float(c) for c in df['close'].tolist()]
    closes = [c for c in closes if c is not None]
    if not closes:
        return None
    return dict(series=closes, latest=closes[-1], date=str(df.iloc[-1].get('date')))


def fetch_sina_global(symbol):
    """
    新浪财经全球指数：每日收盘（日经NKY、KOSPI、DAX、CAC、富时UKX、STOXX50 SX5E）。
    直接调用新浪 gi.finance.sina.com.cn/hq/daily 接口。
    """
    import requests
    url = 'https://gi.finance.sina.com.cn/hq/daily'
    H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
         'Referer': 'https://finance.sina.com.cn/'}
    r = requests.get(url, params={'symbol': symbol, 'num': '10000'}, headers=H, timeout=20)
    j = r.json()
    data = j.get('result', {}).get('data', [])
    if not data:
        return None
    closes = []
    for row in data:
        v = to_float(row.get('c'))
        if v is not None:
            closes.append(v)
    if not closes:
        return None
    return dict(series=closes, latest=closes[-1], date=str(data[-1].get('d')))


def fetch_cbond_index(name):
    """
    中债/外汇交易中心：债券指数历史（高等级信用债综合指数、国债总指数等）。
    """
    import akshare as ak
    df = ak.bond_index_general_cbond(index_category=name, indicator='全价', period='总值')
    if df is None or len(df) == 0:
        return None
    vals = [to_float(v) for v in df['value'].tolist()]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return dict(series=vals, latest=vals[-1], date=str(df.iloc[-1].get('date')))


def fetch_sw_valuation():
    """申万一级行业：PE/PB/股息率/换手率。"""
    out = {}
    try:
        import akshare as ak
        df = ak.index_analysis_daily_sw(symbol='一级行业')
        for _, row in df.iterrows():
            nm = str(row.get('指数名称') or '').strip()
            rec = {}
            for src, dst in (('市盈率', 'pe'), ('市净率', 'pb'), ('股息率', 'div'), ('换手率', 'turn')):
                v = to_float(row.get(src))
                if v is not None:
                    rec[dst] = v
            if nm:
                out[nm] = rec
        print(f'  [ok] 申万一级行业估值 {len(out)} 条')
    except Exception as e:
        print(f'  [warn] 申万行业估值抓取失败：{e}')
    return out


def fetch_market_sentiment():
    """全市场情绪面：平均PE + 历史分位 + 成交/涨跌家数。"""
    sent = {}
    try:
        import akshare as ak
        df = ak.stock_market_pe_lg(symbol='深证')
        if df is not None and len(df):
            last = df.iloc[-1]
            pe = to_float(last['平均市盈率'])
            if pe is not None:
                sent['marketPe'] = round(pe, 2)
                sent['marketPeDate'] = str(last['日期'])
                hist = [to_float(x) for x in df['平均市盈率'].tolist()]
                hist = [h for h in hist if h is not None]
                p = percentile_of(hist, pe)
                if p is not None:
                    sent['marketPct'] = p
        print('  [ok] 全市场PE/情绪抓取成功')
    except Exception as e:
        print(f'  [warn] 全市场情绪抓取失败：{e}')

    # 涨跌家数 / 涨跌停 / 活跃度（乐咕乐股，收盘后真实统计）
    try:
        import akshare as ak
        df = ak.stock_market_activity_legu()
        if df is not None and len(df):
            m = {str(r['item']): r['value'] for _, r in df.iterrows()}
            def g(k):
                v = to_float(m.get(k))
                return int(v) if v is not None else None
            up, down, flat = g('上涨'), g('下跌'), g('平盘')
            if up is not None and down is not None:
                sent['up'] = up
                sent['down'] = down
                sent['flat'] = flat if flat is not None else 0
                sent['limitUp'] = g('涨停') or 0
                sent['limitDown'] = g('跌停') or 0
                act = to_float(m.get('活跃度'))
                if act:
                    # 源值形如 "11.03%"，to_float 解析不了百分号，这里手工处理
                    s = str(m.get('活跃度')).replace('%', '')
                    sent['turnover'] = round(float(s), 2)
                sent['activityDate'] = str(m.get('统计日期'))
                print('  [ok] 涨跌家数/涨跌停/活跃度抓取成功')
    except Exception as e:
        print(f'  [warn] 涨跌家数抓取失败：{str(e)[:100]}')

    # 成交额 + 换手率（沪深交易所官方汇总）
    # 注意：盘中（当天）接口会返回未收盘的异常数据，故优先用已收盘的上一交易日
    try:
        import akshare as ak
        def pick_date():
            for back in range(0, 6):
                d = (datetime.date.today() - datetime.timedelta(days=back)).strftime('%Y%m%d')
                try:
                    df = ak.stock_szse_summary(date=d)
                    if df is not None and len(df):
                        r = df[df['证券类别'] == '股票']
                        if len(r) and to_float(r.iloc[0]['成交金额']):
                            return d
                except Exception:
                    continue
            return None

        sse_amt = sse_turn = None
        for back in range(0, 6):
            d = (datetime.date.today() - datetime.timedelta(days=back)).strftime('%Y%m%d')
            try:
                sse = ak.stock_sse_deal_daily(date=d)
                if sse is None or len(sse) == 0:
                    continue
                row = sse[sse['单日情况'] == '成交金额']
                if len(row):
                    sse_amt = to_float(row.iloc[0]['股票'])
                row2 = sse[sse['单日情况'] == '换手率']
                if len(row2):
                    sse_turn = to_float(row2.iloc[0]['股票'])
                if sse_amt:
                    break
            except Exception:
                continue

        szse_amt = None
        d = pick_date()
        if d:
            df = ak.stock_szse_summary(date=d)
            r = df[df['证券类别'] == '股票']
            if len(r):
                szse_amt = to_float(r.iloc[0]['成交金额'])

        if sse_amt or szse_amt:
            # 单位统一：沪市接口返回「亿元」，深市接口返回「元」，一律折算成「万亿」
            sse_wt = (sse_amt or 0) / 1e4          # 亿元 → 万亿
            szse_wt = (szse_amt or 0) / 1e12        # 元   → 万亿
            sent['amount'] = round(sse_wt + szse_wt, 2)
            if sse_turn:
                sent['turnover'] = round(sse_turn, 2)
            print(f'  [ok] 成交额/换手率抓取成功（沪市{sse_amt}亿 + 深市{szse_amt}元 → {sent["amount"]}万亿）')
    except Exception as e:
        print(f'  [warn] 成交额抓取失败：{str(e)[:100]}')
    return sent


# ---------------------------------------------------------------
# 4) 主流程
# ---------------------------------------------------------------
def load_previous(bundle_path):
    """
    读取上一次生成的数据文件。
    作用：当某个板块这次抓取失败（接口限流/网络抖动）时，
    沿用它上次抓到的真实值，避免数据"越更新越差"。
    """
    if not os.path.exists(bundle_path):
        return {}
    try:
        with open(bundle_path, encoding='utf-8') as f:
            s = f.read()
        s = s[s.index('['):s.rindex(']') + 1]
        old = json.loads(s)
        return {o['code']: o for o in old if o.get('code')}
    except Exception:
        return {}


def merge_with_previous(result, previous):
    """
    增量合并：本次抓失败(isReal=False)的板块，若上次有真实数据，则保留上次的真实值。
    返回 (合并后的列表, 保留旧数据的板块数)
    """
    kept = 0
    for item in result:
        if item.get('isReal'):
            continue
        old = previous.get(item['code'])
        if not old or not old.get('isReal'):
            continue
        # 沿用上次的真实字段
        for k in ('pe', 'pb', 'div', 'pct', 'heat', 'trend', 'trends', 'mVal', 'mLabel',
                  'type', 'price', 'pctBasis', 'pctLabel', 'turn'):
            if old.get(k) is not None and item.get(k) in (None, 0, ''):
                item[k] = old[k]
        # 若上次有 trend/trends 而本次是生成的兜底曲线，则用上次的
        old_trend = old.get('trend') or []
        new_trend = item.get('trend') or []
        if len(old_trend) == 12 and len(new_trend) == 12:
            # 判断本次是否为兜底生成：末值与 pe/mVal 完全一致通常是生成的
            base = item.get('mVal') or item.get('pe') or 0
            if base and abs(new_trend[-1] - base) < 0.05 and abs(old_trend[-1] - base) > 0.05:
                item['trend'] = old_trend
                if old.get('trends'):
                    item['trends'] = old['trends']
        item['isReal'] = True
        item['stale'] = True     # 标记为"沿用上次数据"
        kept += 1
    return result, kept


def build():
    print('开始采集指数估值数据...')
    sw = fetch_sw_valuation()
    sentiment = fetch_market_sentiment()
    bond_rates = fetch_bond_rates() or {}

    # 板块名 → 申万行业名（用于补 PB/股息率/换手率）
    sw_map = {
        '中证煤炭': '煤炭', '中证银行': '银行', '中证军工': '国防军工',
        '中证白酒': '食品饮料', '中证医疗': '医药生物', '中证传媒': '传媒',
        '中证地产': '房地产', '证券公司': '非银金融', '计算机': '计算机',
        '通信设备': '通信', '新能源车': '汽车', '光伏产业': '电力设备',
    }

    gold_cache = None
    result = []
    ok_real = 0
    fails = []

    for d in DEFAULTS:
        item = dict(d)
        code = d['code']
        src = d.get('src', 'external')
        is_eq = d.get('type', 'equity') == 'equity'

        try:
            # ---- A股/中证系：PE + 分位 + 走势 ----
            if src == 'csindex':
                info = fetch_csindex(code)
                if info and info['pe']:
                    valid = [p for p in info['pe'] if p is not None]
                    if valid:
                        cur = valid[-1]
                        item['pe'] = round(cur, 2)
                        p = percentile_of(info['pe'], cur)
                        if p is not None:
                            item['pct'] = p
                        item['trends'] = sample_ranges(info['pe'])
                        item['trend'] = item['trends']['y1']
                        item['_real'] = True
                        ok_real += 1
                    elif info and info['close']:
                        # PE 全为 nan（如中特估，中证不计算其 PE）→ 用收盘价算分位
                        closes = info['close']
                        cur_close = closes[-1]
                        item['pct'] = percentile_of(closes, cur_close) or item.get('pct')
                        item['trends'] = sample_ranges(closes)
                        item['trend'] = item['trends']['y1']
                        item['peNote'] = '源站未提供PE，按指数点位计算分位'
                        item['_real'] = True
                        ok_real += 1
                # 转债等债券类：mVal 用收盘价
                if d.get('type') == 'bond' and info and info['close']:
                    closes = info['close']
                    item['mVal'] = round(closes[-1], 2)
                    item['price'] = round(closes[-1], 2)
                    p = percentile_of(closes, closes[-1])
                    if p is not None:
                        item['pct'] = p
                    item['trends'] = sample_ranges(closes)
                    item['trend'] = item['trends']['y1']

            # ---- 深市指数（创业板指等）：新浪源 ----
            elif src == 'sina_sz':
                info = fetch_sina_sz(code)
                if info:
                    item['price'] = round(info['latest'], 2)
                    p = percentile_of(info['series'], info['latest'])
                    if p is not None:
                        item['pct'] = p
                    item['trends'] = sample_ranges(info['series'])
                    item['trend'] = item['trends']['y1']
                    item['_real'] = True
                    ok_real += 1

            # ---- 港股：百度 PE + 分位 ----
            elif src == 'baidu_hk':
                info = fetch_baidu_hk(d.get('baidu', '000001'))
                if info:
                    item['pe'] = round(info['latest'], 2)
                    p = percentile_of(info['series'], info['latest'])
                    if p is not None:
                        item['pct'] = p
                    item['trends'] = sample_ranges(info['series'])
                    item['trend'] = item['trends']['y1']
                    item['_real'] = True
                    ok_real += 1
                # 补充：用新浪港股点位历史算更长周期的分位（百度只有近一年）
                # 注意：只更新分位和价格，不覆盖 trend（trend 保留百度 PE 走势）
                if d.get('hk'):
                    try:
                        hk = fetch_sina_hk(d['hk'])
                        if hk:
                            p2 = percentile_of(hk['series'], hk['latest'])
                            if p2 is not None:
                                item['pct'] = p2
                                item['price'] = round(hk['latest'], 2)
                    except Exception:
                        pass

            # ---- 美股：价格 + 分位（PE无免费源，保留兜底）----
            elif src == 'sina_us':
                info = fetch_sina_us(d.get('sina'))
                if info:
                    item['price'] = round(info['latest'], 2)
                    p = percentile_of(info['series'], info['latest'])
                    if p is not None:
                        item['pct'] = p
                    item['trends'] = sample_ranges(info['series'])
                    item['trend'] = item['trends']['y1']
                    item['_real'] = True
                    ok_real += 1

            # ---- 全球指数（日经/DAX/CAC/富时/STOXX50/KOSPI）：新浪全球源 ----
            elif src == 'sina_global':
                info = fetch_sina_global(d.get('sina'))
                if info:
                    item['price'] = round(info['latest'], 2)
                    p = percentile_of(info['series'], info['latest'])
                    if p is not None:
                        item['pct'] = p
                    item['trends'] = sample_ranges(info['series'])
                    item['trend'] = item['trends']['y1']
                    item['_real'] = True
                    ok_real += 1

            # ---- 黄金：上金所 ----
            elif src == 'sge':
                if gold_cache is None:
                    gold_cache = fetch_sge_gold()
                if gold_cache:
                    item['price'] = round(gold_cache['latest'], 2)
                    item['mVal'] = round(gold_cache['latest'], 2)
                    p = percentile_of(gold_cache['series'], gold_cache['latest'])
                    if p is not None:
                        item['pct'] = p
                    item['trends'] = sample_ranges(gold_cache['series'])
                    item['trend'] = item['trends']['y1']
                    item['_real'] = True
                    ok_real += 1

            # ---- 原油/白银/铜：期货最新价 ----
            elif src == 'futures':
                info = fetch_futures(d.get('fut'))
                if info:
                    item['price'] = round(info['price'], 2)
                    item['mVal'] = round(info['price'], 2)
                    item['_real'] = True
                    ok_real += 1

            # ---- 债券收益率 ----
            elif src == 'bond':
                key = d.get('bond')
                if key in bond_rates:
                    r = bond_rates[key]
                    item['mVal'] = round(r['latest'], 2)
                    item['price'] = round(r['latest'], 2)
                    p = percentile_of(r['series'], r['latest'])
                    if p is not None:
                        item['pct'] = p
                    item['trends'] = sample_ranges(r['series'])
                    item['trend'] = item['trends']['y1']
                    item['_real'] = True
                    ok_real += 1

            # ---- 中债指数（信用债/国债）----
            elif src == 'cbond':
                info = fetch_cbond_index(d.get('cbond'))
                if info:
                    item['mVal'] = round(info['latest'], 2)
                    item['price'] = round(info['latest'], 2)
                    p = percentile_of(info['series'], info['latest'])
                    if p is not None:
                        item['pct'] = p
                    item['trends'] = sample_ranges(info['series'])
                    item['trend'] = item['trends']['y1']
                    item['_real'] = True
                    ok_real += 1

        except Exception as e:
            fails.append(f"{d['name']}({str(e)[:40]})")
            print(f"  [warn] {code} {d['name']} 抓取失败：{str(e)[:70]}")

        # ---- 补充：申万 PB / 股息率 / 换手率 ----
        sw_key = sw_map.get(d['name'])
        if sw_key and sw_key in sw:
            for k in ('pb', 'div', 'turn'):
                if k in sw[sw_key]:
                    item[k] = round(sw[sw_key][k], 2)

        # ---- 兜底：走势图不能为空 ----
        if not item.get('trends'):
            base = item.get('mVal') or item.get('pe') or item.get('price') or 1
            gen = gen_trend(base, item.get('pct', 50))
            item['trends'] = {k: gen for k, _, _ in TREND_RANGES}
            item['trend'] = gen

        item.setdefault('mLabel', 'PE(TTM)')
        if item.get('mVal') is None:
            item['mVal'] = item.get('pe')

        # ---- 标注：分位是按什么口径算的（前端据此显示正确的白话说明）----
        #   pe  = 按市盈率(PE)算的分位，最标准
        #   px  = 按指数点位/价格算的分位（海外指数无实时PE历史，用价格算分位）
        #   yld = 按收益率算的分位（债券，注意反向：收益率低=债券贵）
        if item.get('type') == 'commodity':
            item['pctBasis'] = 'px'
            item['pctLabel'] = '价格历史分位'
        elif item.get('type') == 'bond':
            item['pctBasis'] = 'yld' if src == 'bond' else 'px'
            item['pctLabel'] = '收益率分位' if src == 'bond' else '点位历史分位'
        elif src in ('sina_us', 'sina_global', 'sina_sz'):
            item['pctBasis'] = 'px'
            item['pctLabel'] = '点位历史分位'
        elif item.get('peNote'):
            item['pctBasis'] = 'px'
            item['pctLabel'] = '点位历史分位'
        else:
            item['pctBasis'] = 'pe'
            item['pctLabel'] = 'PE历史分位'

        # ---- 海外/美股：把价格走势换算成 PE 估算走势（所有时间档都换算）----
        if (item.get('pctBasis') == 'px' and not item.get('type')
                and item.get('pe') and item['pe'] > 0):
            for k, trend in (item.get('trends') or {}).items():
                if trend and trend[-1] and trend[-1] > 0:
                    ratio = item['pe'] / trend[-1]
                    item['trends'][k] = [round(v * ratio, 1) for v in trend]
            item['trend'] = item.get('trends', {}).get('y1', [])
            item['trendNote'] = 'PE走势由价格走势等比换算估算（假设盈利稳定），仅供参考'

        # ---- PE 来源标注（海外指数PE来自研究机构而非实时接口）----
        pe_src = item.get('peSrc')
        if pe_src:
            pe_src_labels = {
                'bloomberg': 'Bloomberg/Invesco 2026-09',
                'siblis': 'Siblis Research 2026-09',
                'valuengine': 'ValuEngine 2026-10',
                'research': '国元证券 2026-08',
                'estimate': '综合研究机构估算',
            }
            item['peNote'] = f'PE来自{pe_src_labels.get(pe_src, pe_src)}，非实时接口'
            item['peSrc'] = pe_src

        item['updatedAt'] = datetime.date.today().strftime('%Y-%m-%d')
        # isReal = 本次是否抓到真实数据（前端可据此提示"该板块暂用示例值"）
        item['isReal'] = bool(item.pop('_real', False))
        result.append(item)
        # 礼貌性限速：中证官网有频率限制，请求之间留足间隔
        time.sleep(0.8 if src == 'csindex' else 0.25)

    print(f'共输出 {len(result)} 个板块，其中 {ok_real} 个抓到真实数据。')
    if fails:
        print(f'  [info] 失败并保留兜底值：{"、".join(fails)}')
    return result, sentiment


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    bundle_path = os.path.join(here, '..', 'utils', 'indices_bundle.js')

    # 先读取上一次的数据（用于抓取失败时沿用真实值）
    previous = load_previous(bundle_path)

    data, sentiment = build()

    # 增量合并：本次抓失败的板块，沿用上次的真实数据
    data, kept = merge_with_previous(data, previous)
    real_now = sum(1 for d in data if d.get('isReal'))
    stale = sum(1 for d in data if d.get('stale'))
    print(f'真实数据合计 {real_now}/{len(data)} 个板块'
          f'（其中 {stale} 个因接口限流沿用上次数据）')

    with open(bundle_path, 'w', encoding='utf-8') as f:
        f.write('// 自动生成，请勿手动修改。来源：tools/fetch_indices.py\n')
        f.write('// 编译时直接打进小程序安装包，无需云开发。\n')
        f.write('module.exports = ')
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(';\n')
    print(f'已写入：{os.path.normpath(bundle_path)}')

    sent_path = os.path.join(here, '..', 'utils', 'sentiment_bundle.js')
    with open(sent_path, 'w', encoding='utf-8') as f:
        f.write('// 自动生成，请勿手动修改。来源：tools/fetch_indices.py\n')
        f.write('module.exports = ')
        json.dump(sentiment, f, ensure_ascii=False, indent=2)
        f.write(';\n')
    print(f'已写入：{os.path.normpath(sent_path)}')


if __name__ == '__main__':
    main()
