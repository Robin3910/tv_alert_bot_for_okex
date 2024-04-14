# -*- coding: utf-8 -*-
import configparser
import ccxt
import logging
from flask import Flask
from flask import request, abort
import json
import urllib.request
import requests
import os
import _thread
import time


# 读取配置文件，优先读取json格式，如果没有就读取ini格式
config = {}
if os.path.exists('./config.json'):
    config = json.load(open('./config.json',encoding="UTF-8"))
elif os.path.exists('./config.ini'):
    conf = configparser.ConfigParser()
    conf.read("./config.ini", encoding="UTF-8")
    for i in dict(conf._sections):
        config[i] = {}
        for j in dict(conf._sections[i]):
            config[i][j] = conf.get(i, j)
    config['account']['enable_proxies'] = config['account']['enable_proxies'].lower() == "true"
    config['trading']['enable_stop_loss'] = config['trading']['enable_stop_loss'].lower() == "true"
    config['trading']['enable_stop_gain'] = config['trading']['enable_stop_gain'].lower() == "true"
else:
    print("The configuration file config.json does not exist and the program is about to exit.")
    exit()

# 服务配置
apiSec = config['service']['api_sec']
listenHost = config['service']['listen_host']
listenPort = config['service']['listen_port']
debugMode = config['service']['debug_mode']
ipWhiteList = config['service']['ip_white_list'].split(",")

# 交易对
symbol = config['trading']['symbol']
amount = config['trading']['amount']
tdMode = config['trading']['td_mode']
lever = config['trading']['lever']

# 交易所API账户配置
accountConfig = {
    'apiKey': config['account']['api_key'],
    'secret': config['account']['secret'],
    'password': config['account']['password'],
    'enable_proxies': config['account']['enable_proxies'],
    'proxies': {
        'http': config['account']['proxies'],  # these proxies won't work for you, they are here for example
        'https': config['account']['proxies'],
    }
}

# 格式化日志
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y/%m/%d/ %H:%M:%S %p"
logging.basicConfig(filename='okex_trade.log', level=logging.INFO, format=LOG_FORMAT, datefmt=DATE_FORMAT)
# logging.FileHandler(filename='okex_trade.log', encoding=)

# CCXT初始化
exchange = ccxt.okex5(config={
    'enableRateLimit': True,
    'apiKey': accountConfig['apiKey'],
    'secret': accountConfig['secret'],
    # okex requires this: https://github.com/ccxt/ccxt/wiki/Manual#authentication
    'password': accountConfig['password'],
    'verbose': False,  # for debug output
})
if accountConfig['enable_proxies'] is True:
    exchange.proxies = accountConfig['proxies']
if 'ouyihostname' in config['account']:
    exchange.hostname = config['account']['ouyi_hostname']

# lastOrdId
lastOrdId = 0
lastOrdType = None
lastAlgoOrdId = 0

# 挂止盈止损单
def sltpThread(oid, side, symbol, sz, tdMode, config):
    global lastOrdType,lastAlgoOrdId
    privatePostTradeOrderAlgoParams = {
        "instId": symbol,
        "tdMode": tdMode,
        "side": "sell" if side.lower() == "buy" else "buy",
        "ordType": "oco",
        "sz": sz
    }
    if config['trading']['enable_stop_loss']:
        privatePostTradeOrderAlgoParams['slTriggerPx'] = config['trading']['stop_loss_trigger_price']
        privatePostTradeOrderAlgoParams['slOrdPx'] = config['trading']['stop_loss_order_price']
    if config['trading']['enable_stop_gain']:
        privatePostTradeOrderAlgoParams['tpTriggerPx'] = config['trading']['stop_gain_trigger_price']
        privatePostTradeOrderAlgoParams['tpOrdPx'] = config['trading']['stop_gain_order_price']
    while True:
        try:
            privateGetTradeOrderRes = exchange.privateGetTradeOrder(params={"ordId": oid,"instId": symbol})
            print(privateGetTradeOrderRes)
            if privateGetTradeOrderRes['data'][0]['state'] == "filled":
                avgPx = float(privateGetTradeOrderRes['data'][0]['avgPx'])
                direction = -1 if side.lower() == "buy" else 1
                slTriggerPx = (1 + direction * float(config['trading']['stop_loss_trigger_price'])*0.01) * avgPx
                tpOrdPx = (1 + direction * float(config['trading']['stop_gain_order_price'])*0.01) * avgPx
                tpTriggerPx = (1 - direction * float(config['trading']['stop_gain_trigger_price'])*0.01) * avgPx
                slOrdPx = (1 - direction * float(config['trading']['stop_loss_order_price'])*0.01) * avgPx
                privatePostTradeOrderAlgoParams['slTriggerPx'] = '%.12f' % slTriggerPx
                privatePostTradeOrderAlgoParams['slOrdPx'] = '%.12f' % slOrdPx
                privatePostTradeOrderAlgoParams['tpTriggerPx'] = '%.12f' % tpTriggerPx
                privatePostTradeOrderAlgoParams['tpOrdPx'] = '%.12f' % tpOrdPx
                print("订单{oid}设置止盈止损...".format(oid=oid))
                privatePostTradeOrderAlgoRes = exchange.privatePostTradeOrderAlgo(params=privatePostTradeOrderAlgoParams)
                if 'code' in privatePostTradeOrderAlgoRes and privatePostTradeOrderAlgoRes['code'] == '0':
                    lastAlgoOrdId = privatePostTradeOrderAlgoRes['data'][0]['algoId']
                    break
                else:
                    continue
            elif privateGetTradeOrderRes['data'][0]['state'] == "canceled":
                lastOrdType = None
                break
        except Exception as e:
            print(e)
        time.sleep(1)
    print("订单{oid}止盈止损单挂单结束".format(oid=oid))



# 设置杠杆
def setLever(_symbol, _tdMode, _lever):
    try:
        privatePostAccountSetLeverageRes = exchange.privatePostAccountSetLeverage(
            params={"instId": _symbol, "mgnMode": _tdMode, "lever": _lever})
        # logging.info(json.dumps(privatePostAccountSetLeverageRes))
        return True
    except Exception as e:
        # logging.error("privatePostTradeCancelBatchOrders " + str(e))
        return False

# 取消止盈止损订单


# 市价全平
def cancelLastOrder(_symbol, _lastOrdId):
    try:
        res = exchange.privatePostTradeCancelOrder(params={"instId": _symbol, "ordId": _lastOrdId})
        # logging.info("privatePostTradeCancelBatchOrders " + json.dumps(res))
        return True
    except Exception as e:
        # logging.error("privatePostTradeCancelBatchOrders " + str(e))
        return False


# 平掉所有仓位
def closeAllPosition(_symbol, _tdMode):
    try:
        res = exchange.privatePostTradeClosePosition(params={"instId": _symbol, "mgnMode": _tdMode})
        # logging.info("privatePostTradeClosePosition " + json.dumps(res))
        return True
    except Exception as e:
        print("privatePostTradeClosePosition " + str(e))
        return False

# 开仓
def createOrder(_symbol, _amount, _price, _side, _ordType, _tdMode, enable_stop_loss=False, stop_loss_trigger_price=0, stop_loss_order_price=0, enable_stop_gain=False, stop_gain_trigger_price=0, stop_gain_order_price=0):
    try:
        # 挂单
        res = exchange.privatePostTradeOrder(
            params={"instId": _symbol, "sz": _amount, "px": _price, "side": _side, "ordType": _ordType,
                    "tdMode": _tdMode})
        global lastOrdId,config
        lastOrdId = res['data'][0]['ordId']
        # 如果止盈止损
        if config['trading']['enable_stop_loss'] or config['trading']['enable_stop_gain']:
            try:
                _thread.start_new_thread(sltpThread, (lastOrdId, _side, _symbol, _amount, _tdMode, config))
            except:
                logging.error("Error: unable to run sltpThread")
        return True, "create order successfully"
    except Exception as e:
        logging.error("createOrder " + str(e))
        return False, str(e)


# 获取公共数据，包含合约面值等信息
def initInstruments():
    c = 0
    try:
        # 获取永续合约基础信息
        swapInstrumentsRes = exchange.publicGetPublicInstruments(params={"instType": "SWAP"})
        if swapInstrumentsRes['code'] == '0':
            global swapInstruments
            swapInstruments = swapInstrumentsRes['data']
            c = c + 1
    except Exception as e:
        logging.error("publicGetPublicInstruments " + str(e))
    try:
        # 获取交割合约基础信息
        futureInstrumentsRes = exchange.publicGetPublicInstruments(params={"instType": "FUTURES"})
        if futureInstrumentsRes['code'] == '0':
            global futureInstruments
            futureInstruments = futureInstrumentsRes['data']
            c = c + 1
    except Exception as e:
        logging.error("publicGetPublicInstruments " + str(e))
    return c >= 2

# 将 amount 币数转换为合约张数
# 币的数量与张数之间的转换公式
# 单位是保证金币种（币本位的币数单位为币，U本位的币数单位为U）
# 1、币本位合约：币数=张数*面值*合约乘数/标记价格
# 2、U本位合约：币数=张数*面值*合约乘数*标记价格
# 交割合约和永续合约合约乘数都是1
def amountConvertToSZ(_symbol, _amount, _price, _ordType):
    _symbol = _symbol.upper()
    _symbolSplit = _symbol.split("-")
    isSwap = _symbol.endswith("SWAP")
    # 获取合约面值
    def getFaceValue(_symbol):
        instruments = swapInstruments if isSwap else futureInstruments
        for i in instruments:
            if i['instId'].upper() == _symbol:
                return float(i['ctVal'])
        return False
    faceValue = getFaceValue(_symbol)
    if faceValue is False:
        raise Exception("getFaceValue error.")
    # 币本位合约：张数 = 币数 / 面值 / 合约乘数 * 标记价格
    # U本位合约：张数 = 币数 / 面值 / 合约乘数
    sz = float(_amount) / faceValue / 1
    if _symbolSplit[1] == "USD":
        # 如果是市价单，获取一下最新标记价格
        if _ordType.upper() == "MARKET":
            _price = exchange.publicGetPublicMarkPrice(params={"instId": _symbol,"instType":("SWAP" if isSwap else "FUTURES")})['data'][0]['markPx']
        sz = sz * float(_price)
    return int(sz)


def getPricePrecision(price):
    val_str = str(price)
    digits_location = val_str.find('.')
    if digits_location:
        return len(val_str[digits_location + 1:])
    return 0


# 初始化杠杆倍数
setLever(symbol, tdMode, lever)

app = Flask(__name__)

@app.before_request
def before_req():
    logging.info(request.json)
    if request.json is None:
        abort(400)
    if request.remote_addr not in ipWhiteList:
        logging.info(f'ipWhiteList: {ipWhiteList}')
        logging.error(f'ip is not in ipWhiteList: {request.remote_addr}')
        abort(403)
    # if "apiSec" not in request.json or request.json["apiSec"] != apiSec:
    #     abort(401)


@app.route('/ping', methods=['GET'])
def ping():
    return {}

@app.route('/order', methods=['POST'])
def order():
    ret = {
        "cancelLastOrder": False,
        "closedPosition": False,
        "createOrderRes": False,
        "msg": ""
    }
    # 获取参数 或 填充默认参数
    _params = request.json
    # if "apiSec" not in _params or _params["apiSec"] != apiSec:
    #     ret['msg'] = "Permission Denied."
    #     return ret
    if "symbol" not in _params:
        _params["symbol"] = symbol
    if "amount" not in _params:
        _params["amount"] = amount
    if "tdMode" not in _params:
        _params["tdMode"] = tdMode
    # if "slPercent" not in _params:
    #     _params['slPercent'] = 0.03
    if "side" not in _params:
        ret['msg'] = "Please specify side parameter"
        return ret
    # 如果修改杠杆倍数，那么需要请重新请求一下
    if "lever" in _params and _params['lever'] != lever:
        setLever(_params['symbol'], _params['lever'], _params['lever'])

    # 注意：开单的时候会先把原来的仓位平掉，然后再把你的多单挂上
    global lastOrdType
    if _params['side'].lower() in ["buy", "sell"]:

        pos_res = exchange.privateGetAccountPositions(params={"instId": _params['symbol']})
        pos_side = pos_res['data'][0]['posSide']
        if (_params['side'].lower() == "sell" and pos_side == "long") or (_params['side'].lower() == "buy" and pos_side == "short"):
            ret["closedPosition"] = closeAllPosition(_params['symbol'], _params['tdMode'])

        ret["cancelLastOrder"] = cancelLastOrder(_params['symbol'], lastOrdId)
        # ret["closedPosition"] = closeAllPosition(_params['symbol'], _params['tdMode'])
        # 开仓
        sz = amountConvertToSZ(_params['symbol'], _params['amount'], _params['price'], _params['ordType'])
        if sz < 1:
            ret['msg'] = 'Amount is too small. Please increase amount.'
        else:
            ret["createOrderRes"], ret['msg'] = createOrder(_params['symbol'], sz, _params['price'], _params['side'],
                                                _params['ordType'], _params['tdMode'])

    # 平仓
    elif _params['side'].lower() in ["close"]:
        lastOrdType = None
        ret["closedPosition"] = closeAllPosition(_params['symbol'], _params['tdMode'])

    # 取消挂单
    elif _params['side'].lower() in ["cancel"]:
        lastOrdType = None
        ret["cancelLastOrder"] = cancelLastOrder(_params['symbol'], lastOrdId)
    else:
        pass

    # 发送微信通知
    requests.get(
        f'https://sctapi.ftqq.com/SCT143186TIvKuCgmwWnzzzGQ6mE5qmyFU.send?title=okex_{_params["symbol"]}_{_params["side"]}')
    return ret


if __name__ == '__main__':
    try:
        ip = json.load(urllib.request.urlopen('http://httpbin.org/ip'))['origin']
        print(
            "It is recommended to run it on a server with an independent IP. If it is run on a personal computer, it requires FRP intranet penetration and affects the software efficiency.".format(
                listenPort=listenPort, listenHost=listenHost, ip=ip))
        print(
            "Please be sure to modify apiSec in config.ini and modify it to a complex key.".format(
                listenPort=listenPort, listenHost=listenHost, ip=ip))
        print(
            "The system interface service is about to start! Service listening address:{listenHost}:{listenPort}".format(
                listenPort=listenPort, listenHost=listenHost, ip=ip))
        print(
            "interface addr: http://{ip}:{listenPort}/order".format(
                listenPort=listenPort, listenHost=listenHost, ip=ip))
        print("It is recommended to use nohup python3 okex_trading.py & to run the program into the linux background")

        # 初始化交易币对基础信息
        if initInstruments() is False:
            msg = "Failed to initialize currency base information, please try again"
            raise Exception(msg)
        # 启动服务
        app.run(debug=debugMode, port=listenPort, host=listenHost)
    except Exception as e:
        print(e)
        pass
