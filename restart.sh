#!/bin/bash

# 关闭okex_trading.py的进程
pkill -f okex_trading.py
echo "关闭 okex_trading.py 进程成功"


# 进入指定目录
cd /data/tv_alert_bot_for_okex

# 执行git pull
echo "正在执行 git pull..."
git pull

# 启动okex_trading.py
echo "正在启动 okex_trading.py..."
nohup python3 okex_trading.py &