#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成网页 APP 用的数据文件 webapp/data/indices.json。

两种模式：
  --from-bundle （默认）把已生成的小程序数据文件转成 JSON，零依赖、秒完成
  --live        重新抓取真实数据后再转成 JSON（云端定时任务用这个）

安全保护：真实板块数不足 25 个时不覆盖已有 JSON，避免接口临时故障
把好数据换成差数据。
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEBAPP = os.path.dirname(HERE)
ROOT = os.path.dirname(WEBAPP)
MINI_UTILS = os.path.join(ROOT, 'miniprogram', 'utils')
MINI_TOOLS = os.path.join(ROOT, 'miniprogram', 'tools')
DATA_DIR = os.path.join(WEBAPP, 'data')
OUT_JSON = os.path.join(DATA_DIR, 'indices.json')
OUT_FALLBACK = os.path.join(DATA_DIR, 'fallback.js')
MIN_REAL = 25


def parse_bundle(path):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    m = re.search(r'module\.exports\s*=\s*([\s\S]*?);?\s*$', text.strip())
    if not m:
        raise RuntimeError('无法解析数据文件: ' + path)
    return json.loads(m.group(1).rstrip(';'))


def build_payload():
    indices = parse_bundle(os.path.join(MINI_UTILS, 'indices_bundle.js'))
    sentiment = parse_bundle(os.path.join(MINI_UTILS, 'sentiment_bundle.js'))
    dates = [d.get('updatedAt') for d in indices if d.get('updatedAt')]
    return {
        'updatedAt': max(dates) if dates else datetime.date.today().strftime('%Y-%m-%d'),
        'indices': indices,
        'sentiment': sentiment,
    }


def run_live():
    sys.path.insert(0, MINI_TOOLS)
    import fetch_indices as fi
    fi.main()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--live', action='store_true', help='先重新抓取真实数据')
    ap.add_argument('--from-bundle', action='store_true', help='直接用现有数据文件（默认）')
    ap.add_argument('--with-fallback', action='store_true', help='同时更新内置兜底文件')
    args = ap.parse_args()

    if args.live:
        print('[1/3] 抓取最新数据 ...')
        try:
            run_live()
        except Exception as exc:
            print('  [warn] 抓取过程异常：%s' % str(exc)[:120])

    payload = build_payload()
    real = sum(1 for d in payload['indices'] if d.get('isReal'))
    print('[2/3] 板块 %d 个，其中真实数据 %d 个' % (len(payload['indices']), real))

    if args.live and real < MIN_REAL:
        print('  [warn] 真实数据不足 %d 个，保留原有 JSON 不覆盖' % MIN_REAL)
        return 0

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))

    if args.with_fallback:
        with open(OUT_FALLBACK, 'w', encoding='utf-8') as f:
            f.write('// 内置兜底数据：在线数据拉取失败时使用\nwindow.__FALLBACK__=')
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
            f.write(';\n')

    print('[3/3] 已写入 %s（数据日期 %s，%d 字节）'
          % (os.path.normpath(OUT_JSON), payload['updatedAt'], os.path.getsize(OUT_JSON)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
