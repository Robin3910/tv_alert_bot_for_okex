# -*- coding: utf-8 -*-
import _thread
import configparser
import traceback

import ccxt
import logging

import requests
from flask import Flask
from flask import request, abort
from flask import g
import json
import urllib.request
import os
from libs.log_helper import get_logger
from libs.okx_account_helper import OkxAccountHelper

# 获取当前文件所在的目录
root_path = os.path.dirname(os.path.abspath(__file__))
# 日志处理
logger = get_logger(log_path_dir=root_path)
# 加载OKX辅助工具类
okx_helper = OkxAccountHelper(root_path=root_path, logger=logger)
# 加载配置文件信息
config = okx_helper.get_config()

app = Flask(__name__)


@app.before_request
def before_req():
    logger.info(request.json)
    if request.json is None:
        abort(400)
    if request.remote_addr not in config["global"]["ip_white_list"].split(","):
        logger.info(f'ipWhiteList: {config["global"]["ip_white_list"]}')
        logger.info(f'ip is not in ipWhiteList: {request.remote_addr}')
        abort(403)
    # 从请求参数中获取api_key
    api_key = request.json.get("api_key")
    if api_key is not None:
        instance = okx_helper.get_account_info(api_key=api_key)
        if instance is None:
            logger.info(f'api_key is not in config: {api_key}')
            return abort(403)
        g.okx = instance

@app.route('/ping', methods=['GET'])
def ping():
    return {}
@app.route('/order', methods=['POST'])
def order():
    return okx_helper.order(g.get('okx'))


if __name__ == '__main__':
    print('####################服务已经启动#########################')
    try:
        ip = json.load(urllib.request.urlopen('http://httpbin.org/ip'))['origin']
        logger.info(
            "It is recommended to run it on a server with an independent IP. If it is run on a personal computer, it requires FRP intranet penetration and affects the software efficiency.".format(
                listenPort=config['global']['listen_port'], listenHost=config['global']['listen_host'], ip=ip))
        logger.info(
            "Please be sure to modify apiSec in config.ini and modify it to a complex key.".format(
                listenPort=config['global']['listen_port'], listenHost=config['global']['listen_host'], ip=ip))
        logger.info(
            "The system interface service is about to start! Service listening address:{listenHost}:{listenPort}".format(
                listenPort=config['global']['listen_port'], listenHost=config['global']['listen_host'], ip=ip))
        logger.info(
            "interface addr: http://{ip}:{listenPort}/order".format(
                listenPort=config['global']['listen_port'], listenHost=config['global']['listen_host'], ip=ip))
        logger.info(
            "It is recommended to use nohup python3 okex_trading.py & to run the program into the linux background")
        # 启动跟踪止盈监控线程
        for account in okx_helper.accounts:
            _thread.start_new_thread(okx_helper.trailing_stop_monitor, (account["instance"],))
        # 启动服务
        app.run(debug=False, port=config['global']['listen_port'],
                host=config['global']['listen_host'])
    except Exception as e:
        logger.error(traceback.format_exc())
        pass
