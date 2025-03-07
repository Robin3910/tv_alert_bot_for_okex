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
import okx.Trade as Trade
import okx.Account as Account
import okx.PublicData as PublicData

# 格式化日志
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y/%m/%d/ %H:%M:%S %p"

# 配置日志记录
logger = logging.getLogger('okex_trading')
logger.setLevel(logging.INFO)

# 创建文件处理器
file_handler = logging.FileHandler('okex_trading.log', encoding='utf-8')
file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
logger.addHandler(file_handler)

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
    logger.info("The configuration file config.json does not exist and the program is about to exit.")
    exit()

# 服务配置
apiSec = config['service']['api_sec']
listenHost = config['service']['listen_host']
listenPort = config['service']['listen_port']
debugMode = config['service']['debug_mode']
ipWhiteList = config['service']['ip_white_list'].split(",")
flag = config['account']['flag']
wx_token = config['account']['wx_token']


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

accountAPI = Account.AccountAPI(accountConfig['apiKey'], accountConfig['secret'], accountConfig['password'], False, flag)
tradeAPI = Trade.TradeAPI(accountConfig['apiKey'], accountConfig['secret'], accountConfig['password'], False, flag)
publicDataAPI = PublicData.PublicAPI(flag=flag)

# CCXT初始化
exchange = ccxt.okx(config={
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

# 修改全局变量名称和文件名
SYMBOL_INFO_FILE = 'symbol_info.json'

def send_wx_notification(title, message):
    """
    发送微信通知
    
    Args:
        title: 通知标题
        message: 通知内容
    """
    try:
        # https://sctapi.ftqq.com/SCT264877TGGj20niEYBVMMFU1aN6NQF6g.send?title=test
        requests.get(f'https://sctapi.ftqq.com/{wx_token}.send?text={title}&desp={message}')
        logger.info('发送微信消息成功')
    except Exception as e:
        logger.error(f'发送微信消息失败: {str(e)}')

# 更新读取缓存函数
def load_symbol_info():
    try:
        if os.path.exists(SYMBOL_INFO_FILE):
            with open(SYMBOL_INFO_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        send_wx_notification("读取symbol信息缓存出错", f"读取symbol信息缓存出错: {str(e)}")
        logger.error(f"读取symbol信息缓存出错: {str(e)}")
    return {}

# 更新保存缓存函数
def save_symbol_info(cache):
    try:
        with open(SYMBOL_INFO_FILE, 'w') as f:
            json.dump(cache, f)
    except Exception as e:
        send_wx_notification("保存symbol信息缓存出错", f"保存symbol信息缓存出错: {str(e)}")
        logger.error(f"保存symbol信息缓存出错: {str(e)}")


def prefix_symbol(s: str) -> str:
    # BINANCE:BTCUSDT.P -> BTC-USDT-SWAP
    # 首先处理冒号，如果存在则取后面的部分
    if ':' in s:
        s = s.split(':')[1]
    
    # 检查字符串是否以".P"结尾并移除
    if s.endswith('.P'):
        s = s[:-2]
    
    # 将 BTCUSDT 格式转换为 BTC-USDT-SWAP 格式
    if 'USDT' in s:
        base = s.replace('USDT', '')
        return f"{base}-USDT-SWAP"
    
    return s

# 设置杠杆
def setLever(_symbol, _tdMode, _lever):
    try:
        res = accountAPI.set_leverage(
            instId=_symbol,
            lever=_lever,
            mgnMode=_tdMode
        )
        if res['code'] == '0':
            return True
        else:
            logger.info("setLever " + res["code"] + "|" + res['msg'])
            send_wx_notification("设置杠杆失败", f"设置杠杆失败: {res['msg']}")
            return False
    except Exception as e:
        logger.info("setLever 失败" + str(e))
        send_wx_notification("设置杠杆失败", f"设置杠杆失败: {str(e)}")
        return False

# 取消止盈止损订单
def cancelLastOrder(_symbol, _lastOrdId):
    try:
        result = tradeAPI.cancel_order(instId=_symbol, ordId = _lastOrdId)
        if result['code'] == '0':
            return True
        else:
            logger.info("cancelLastOrder " + result["code"] + "|" + result['msg'])
            return False
    except Exception as e:
        logger.info("cancelLastOrder 失败" + str(e))
        return False

# 平掉所有仓位
def closeAllPosition(_symbol, _tdMode):
    try:
        # res = exchange.privatePostTradeClosePosition(params={"instId": _symbol, "mgnMode": _tdMode})
        # logger.info("privatePostTradeClosePosition " + json.dumps(res))
        # 市价全平
        result = tradeAPI.close_positions(
            instId=_symbol,
            mgnMode=_tdMode,
            autoCxl=True
        )
        if result['code'] == '0':
            return True
        else:
            logger.info("closeAllPosition " + result["code"] + "|" + result['msg'])
            send_wx_notification("平仓失败", f"平仓失败: {result['msg']}")
            return False
    except Exception as e:
        logger.info("closeAllPosition 失败" + str(e))
        send_wx_notification("平仓失败", f"平仓失败: {str(e)}")
        return False

# 开仓
def createOrder(_symbol, _amount, _price, _side, _ordType, _tdMode, tp, sl, tp_sl_order_type):
    try:
        # 止盈止损如果为市价，则设置为-1
        if tp_sl_order_type.upper() == "MARKET":
            tpOrdPx = -1
            slOrdPx = -1
        else:
            # 止盈止损如果为限价单，则为限价单的价格
            tpOrdPx = tp
            slOrdPx = -1
        # 挂单
        attachAlgoOrds = [{
            "tpTriggerPx": tp,
            "tpOrdPx": tpOrdPx,
            "slTriggerPx": sl,
            "slOrdPx": slOrdPx,
            'attachAlgoClOrdId': str(int(time.time()))
        }]
        # 现货模式限价单
        res = tradeAPI.place_order(
                instId=_symbol,
                tdMode=_tdMode,
                side=_side,
                ordType=_ordType,
                px=_price,
                sz=_amount,
                attachAlgoOrds=attachAlgoOrds
            )
        
        global lastOrdId,config
        if res['code'] == '0':
            lastOrdId = res['data'][0]['ordId']
            ord_id = res['data'][0]['ordId']
            logger.info(f"{ord_id}|{_symbol}|{_amount}|{_price}|{_side}|{_ordType}|{_tdMode}|{tp}|{sl}|create order successfully")
            send_wx_notification("创建订单成功", f"创建订单成功{ord_id}|{_symbol}|{_amount}|{_price}|{_side}|{_ordType}|{_tdMode}|{tp}|{sl}")
            return ord_id, attachAlgoOrds[0]['attachAlgoClOrdId'], "create order successfully"
        else:
            logger.info(f"{_symbol}|{_amount}|{_price}|{_side}|{_ordType}|{_tdMode}|{tp}|{sl}|create order failed")
            send_wx_notification("创建订单失败", f"创建订单失败|{_symbol}|{_amount}|{_price}|{_side}|{_ordType}|{_tdMode}|{tp}|{sl}: {res['data'][0]['sMsg']}")
            return "", "", res['data'][0]['sMsg']
    except Exception as e:
        logger.info(f"{_symbol}|{_amount}|{_price}|{_side}|{_ordType}|{_tdMode}|{tp}|{sl}|create order failed")
        send_wx_notification("创建订单失败", f"创建订单失败|{_symbol}|{_amount}|{_price}|{_side}|{_ordType}|{_tdMode}|{tp}|{sl}: {str(e)}")
        return False, str(e)


# 获取公共数据，包含合约面值等信息
def initInstruments():
    c = 0
    try:
        swapInstrumentsRes = accountAPI.get_instruments(instType="SWAP")
        # 获取永续合约基础信息
        # swapInstrumentsRes = exchange.publicGetPublicInstruments(params={"instType": "SWAP"})
        if swapInstrumentsRes['code'] == '0':
            global swapInstruments
            swapInstruments = swapInstrumentsRes['data']
            c = c + 1
    except Exception as e:
        logger.info("publicGetPublicInstruments 失败" + str(e))
        send_wx_notification("获取合约信息失败", f"获取合约信息失败: {str(e)}")
    try:
        # 获取交割合约基础信息
        futureInstrumentsRes = accountAPI.get_instruments(instType="FUTURES")
        # futureInstrumentsRes = exchange.publicGetPublicInstruments(params={"instType": "FUTURES"})
        if futureInstrumentsRes['code'] == '0':
            global futureInstruments
            futureInstruments = futureInstrumentsRes['data']
            c = c + 1
    except Exception as e:
        logger.info("get_instruments 失败" + str(e))
        send_wx_notification("获取合约信息失败", f"获取合约信息失败: {str(e)}")
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
        send_wx_notification("获取合约面值失败", f"获取合约面值失败: {_symbol}")
        raise Exception("getFaceValue error.")
    # 币本位合约：张数 = 币数 / 面值 / 合约乘数 * 标记价格
    # U本位合约：张数 = 币数 / 面值 / 合约乘数
    sz = float(_amount) / faceValue / 1
    if _symbolSplit[1] == "USD":
        # 如果是市价单，获取一下最新标记价格
        if _ordType.upper() == "MARKET":
            # 获取标记价格
            result = publicDataAPI.get_mark_price(
                instId=_symbol,
                instType="SWAP",
            )
            _price = result['data'][0]['markPx']
        sz = sz * float(_price)
    return int(sz)


def getPricePrecision(price):
    val_str = str(price)
    digits_location = val_str.find('.')
    if digits_location:
        return len(val_str[digits_location + 1:])
    return 0


app = Flask(__name__)

@app.before_request
def before_req():
    logger.info(request.json)
    if request.json is None:
        abort(400)
    if request.remote_addr not in ipWhiteList:
        logger.info(f'ipWhiteList: {ipWhiteList}')
        logger.info(f'ip is not in ipWhiteList: {request.remote_addr}')
        abort(403)


@app.route('/ping', methods=['GET'])
def ping():
    return {}

# 请求参数
# {
#     "symbol": "OKX:BTCUSDT.P",
#     "trail_profit_slip": "0.001", # 追踪移动止损的滑点
#     "trail_profit_3_percent": "0.05", # 追踪移动止损的百分比
#     "trail_profit_3_activation": "0.1", # 追踪移动止损的激活百分比
#     "trail_profit_2_percent": "0.02", # 追踪移动止损的百分比
#     "trail_profit_2_activation": "0.05", # 追踪移动止损的激活百分比
#     "trail_stop_callback": "0.005", # 追踪移动止损的回调百分比
#     "trail_stop_activation": "0.02", # 追踪移动止损的激活百分比
#     "bool_trail_stop": "false", # 是否开启追踪移动止损
#     "ema": "104183.0433333325",
#     "tp_sl_order_type": "limit",
#     "quantity": "0.011517011",
#     "action": "buy",
#     "price": "104193.7",
#     "total_usdt": "1200",
#     "use_all_money": "false",
#     "leverage": "10",
#     "order_type": "limit",
#     "tp_percent": "0.03",
#     "sl_percent": "0.03",
#     "trail_profit": "0.015",
#     "entry_limit": "0.02"
# }
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
    if "action" not in _params:
        ret['msg'] = "Please specify side parameter"
        return ret
    
    symbol = prefix_symbol(_params['symbol'])
    tdMode = "cross"
    action = _params['action']

    price = float(_params['price'])
    ema = float(_params['ema'])
    entry_limit = float(_params['entry_limit'])
    global trail_profit
    trail_profit = float(_params['trail_profit'])
    sl_percent = float(_params['sl_percent'])
    tp_percent = float(_params['tp_percent'])
    quantity = float(_params['quantity'])
    order_type = _params['order_type']
    leverage = _params['leverage']
    tp_sl_order_type = _params['tp_sl_order_type']
    trail_profit_slip = float(_params['trail_profit_slip'])
    use_all_money = True if _params['use_all_money'] == "true" else False
    trail_profit_3_percent = float(_params['trail_profit_3_percent'])
    trail_profit_3_activation = float(_params['trail_profit_3_activation'])
    trail_profit_2_percent = float(_params['trail_profit_2_percent'])
    trail_profit_2_activation = float(_params['trail_profit_2_activation'])
    trail_profit_1_percent = float(_params['trail_profit_1_percent'])

    trail_stop_callback = float(_params['trail_stop_callback'])
    trail_stop_activation = float(_params['trail_stop_activation'])
    bool_trail_stop = True if _params['bool_trail_stop'] == "true" else False

    if leverage is not None:
        symbol_info = load_symbol_info()
        symbol_key = symbol
        
        # 获取或初始化symbol信息
        if symbol_key not in symbol_info:
            symbol_info[symbol_key] = {
                'leverage': leverage,
                'entry_price': 0,
                'trail_profit': float(_params['trail_profit']),
                'tp_price': 0,
                'sl_price': 0,
                'tp_sl_order_type': tp_sl_order_type,
                'trail_profit_slip': trail_profit_slip,
                'trail_profit_3_percent': trail_profit_3_percent,
                'trail_profit_3_activation': trail_profit_3_activation,
                'trail_profit_2_percent': trail_profit_2_percent,
                'trail_profit_2_activation': trail_profit_2_activation,
                'trail_profit_1_percent': trail_profit_1_percent,
                'trail_stop_callback': trail_stop_callback,
                'trail_stop_activation': trail_stop_activation,
                'bool_trail_stop': bool_trail_stop,
                "trail_profit_type": 0
            }
        
        # 更新杠杆值
        if symbol_info[symbol_key]['leverage'] != _params['leverage']:
            if setLever(symbol, tdMode, _params['leverage']):
                symbol_info[symbol_key]['leverage'] = _params['leverage']
                save_symbol_info(symbol_info)
                logger.info(f"更新杠杆值成功: {symbol_key} = {_params['leverage']}")
        
    pos_res = accountAPI.get_positions(instId=symbol)
    pos_amount = 0
    pos_side = ""
    if pos_res['code'] == '0' and len(pos_res['data']) > 0:
        pos_side = pos_res['data'][0]['posSide']
        pos_amount = float(pos_res['data'][0]['pos']) # 这获取到的是张数，而不是币数
        logger.info("pre pos side: " + pos_side + "|pos amount: " + str(pos_amount))
    else:
        logger.info(f"当前无仓位:{symbol}| {pos_res['code']} | {pos_res['msg']}")

    # 注意：开单的时候会先把原来的仓位平掉，然后再把你的多单挂上
    global lastOrdType
    if action.lower() in ["buy", "sell"]:
        # 检查EMA和价格之间的差价比例
        # if 'ema' in _params and 'price' in _params and 'entry_limit' in _params:
        #     # 计算差价比例
        #     price_diff_ratio = abs(price - ema) / ema
            
        #     # 如果差价比例超过限制,则不开单
        #     if price_diff_ratio > entry_limit:
        #         ret['msg'] = f'价格偏离EMA过大,差价比例{price_diff_ratio:.2%},超过限制{entry_limit:.2%}'
        #         return ret
        # 检查是否存在相同方向的订单
        if (action.lower() == "buy" and pos_amount > 0) or (action.lower() == "sell" and pos_amount < 0):
            ret['msg'] = f'已存在相同方向的仓位,数量:{abs(pos_amount)},不重复开单'
            return ret
        # 如果信号反转，则先平仓
        if (action.lower() == "sell" and pos_amount > 0) or (action.lower() == "buy" and pos_amount < 0):
            ret["closedPosition"] = closeAllPosition(symbol, tdMode)

        # 取消之前的挂单
        if 'ord_id' in symbol_info[symbol] and symbol_info[symbol]['ord_id'] is not None:
            cancelLastOrder(symbol, symbol_info[symbol]['ord_id'])
        if 'attach_oid' in symbol_info[symbol] and symbol_info[symbol]['attach_oid'] is not None:
            cancel_algo_params = [{'algoId': symbol_info[symbol]['attach_oid'], 'instId': symbol}]
            cancel_algo_res = tradeAPI.cancel_algo_order(cancel_algo_params)
            if cancel_algo_res['code'] == '0':
                logger.info(f"取消止盈止损单成功: {symbol}")
            else:
                logger.info(f"取消止盈止损单失败: {symbol}")

        # 如果使用全部资金，则使用账户余额来计算开仓量
        if use_all_money:
            result = accountAPI.get_account_balance()
            for i in result['data'][0]['details']:
                if i['ccy'] == "USDT":
                    available_balance = float(i['availBal'])
                    logger.info(f"当前可用余额available_balance: {available_balance}")
                    break
            # 使用的是加上杠杆的值，这里使用资金的95%进行开仓，防止开失败
            quantity = (available_balance * 0.95 * float(leverage)) / price
            logger.info(f"使用全部资金，开仓量: {quantity}")

        # 开仓
        sz = amountConvertToSZ(symbol, quantity, price, order_type)

        if sz < 1:
            ret['msg'] = 'Amount is too small. Please increase amount.'
        else:
            if action.lower() == "buy":
                tp = price * (1 + tp_percent)
                sl = price * (1 - sl_percent)
            else:
                tp = price * (1 - tp_percent)
                sl = price * (1 + sl_percent)
            ord_id, attach_oid, ret['msg'] = createOrder(symbol, sz, price, action, order_type, tdMode, tp, sl, tp_sl_order_type)
            
            # 如果订单创建成功,更新开仓价格
            if ord_id:
                # 更新其他信息
                symbol_info[symbol_key].update({
                    'entry_price': price,
                    'trail_profit': float(_params['trail_profit']),
                    'tp_price': tp,
                    'sl_price': sl,
                    'attach_oid': attach_oid,
                    'ord_id': ord_id,
                    'tp_sl_order_type': tp_sl_order_type,
                    'trail_profit_slip': trail_profit_slip,
                    'trail_profit_3_percent': trail_profit_3_percent,
                    'trail_profit_3_activation': trail_profit_3_activation,
                    'trail_profit_2_percent': trail_profit_2_percent,
                    'trail_profit_2_activation': trail_profit_2_activation,
                    'trail_profit_1_percent': trail_profit_1_percent,
                    'trail_stop_callback': trail_stop_callback,
                    'trail_stop_activation': trail_stop_activation,
                    'bool_trail_stop': bool_trail_stop,
                    "trail_profit_type": 0,
                    "active_trail_stop": False,
                    "trail_stop_highest_price": 0,
                    "trail_stop_lowest_price": 9999999,
                })
                save_symbol_info(symbol_info)
    # 平仓
    elif _params['side'].lower() in ["close"]:
        lastOrdType = None
        ret["closedPosition"] = closeAllPosition(symbol, tdMode)

    # 取消挂单
    elif _params['side'].lower() in ["cancel"]:
        lastOrdType = None
        ret["cancelLastOrder"] = cancelLastOrder(symbol, lastOrdId)
    else:
        pass

    # 发送微信通知
    # requests.get(
    #     f'https://sctapi.ftqq.com/SCT143186TIvKuCgmwWnzzzGQ6mE5qmyFU.send?title=okex_{_params["symbol"]}_{_params["side"]}')
    return ret

def trailing_stop_monitor():
    while True:
        try:
            # 获取当前持仓信息
            pos_res = accountAPI.get_positions()
            if pos_res['code'] == '0' and len(pos_res['data']) > 0:
                symbol_info = load_symbol_info()
                
                for position in pos_res['data']:
                    symbol = position['instId']
                    pos_amount = float(position['pos'])
                    entry_price = float(position['avgPx'])
                    uplRatio = float(position['uplRatio']) / int(symbol_info[symbol]['leverage'])
                    # 如果有持仓
                    if pos_amount != 0 and not symbol_info[symbol]['bool_trail_stop']:
                        slTriggerPx = 0
                        trail_profit_type = 0
                        # 分成多段上移止损位
                        if uplRatio >= symbol_info[symbol]['trail_profit_3_activation'] and symbol_info[symbol]['trail_profit_type'] < 3:
                            slTriggerPx = entry_price*(1+symbol_info[symbol]['trail_profit_3_percent'])*(1+symbol_info[symbol]['trail_profit_slip']) if pos_amount > 0 else entry_price*(1-symbol_info[symbol]['trail_profit_3_percent'])*(1-symbol_info[symbol]['trail_profit_slip'])
                            trail_profit_type = 3
                        elif uplRatio >= symbol_info[symbol]['trail_profit_2_activation'] and symbol_info[symbol]['trail_profit_type'] < 2:
                            slTriggerPx = entry_price*(1+symbol_info[symbol]['trail_profit_2_percent'])*(1+symbol_info[symbol]['trail_profit_slip']) if pos_amount > 0 else entry_price*(1-symbol_info[symbol]['trail_profit_2_percent'])*(1-symbol_info[symbol]['trail_profit_slip'])
                            trail_profit_type = 2
                        elif uplRatio >= symbol_info[symbol]['trail_profit'] and symbol_info[symbol]['trail_profit_type'] < 1:
                            slTriggerPx = entry_price*(1+symbol_info[symbol]['trail_profit_1_percent'])*(1+symbol_info[symbol]['trail_profit_slip']) if pos_amount > 0 else entry_price*(1-symbol_info[symbol]['trail_profit_1_percent'])*(1-symbol_info[symbol]['trail_profit_slip'])
                            trail_profit_type = 1
                        else:
                            slTriggerPx = 0

                        # 如果浮盈超过止盈上移的点位，则修改止盈止损单
                        if slTriggerPx > 0:
                            logger.info(f"{symbol}|当前盈利 {uplRatio:.2%}，触发跟踪止盈, 当前止损位置: {slTriggerPx}，第 {trail_profit_type} 级止损位")
                            order_details_res = tradeAPI.get_algo_order_details(
                                algoClOrdId=symbol_info[symbol]['attach_oid']
                            )
                            if order_details_res['code'] == '0':
                                order_data = order_details_res['data'][0]
                                tpTriggerPx = order_data["tpTriggerPx"]
                                # slTriggerPx = entry_price*(1+symbol_info[symbol]['trail_profit_slip']) if pos_amount > 0 else entry_price*(1-symbol_info[symbol]['trail_profit_slip'])
                                # 修改订单
                                amend_res = tradeAPI.amend_algo_order(
                                    instId=symbol,
                                    algoClOrdId=symbol_info[symbol]['attach_oid'],
                                    newSlTriggerPx=slTriggerPx
                                )
                                if amend_res['code'] == '0':
                                    logger.info(f"修改订单成功: {symbol_info[symbol]['attach_oid']}")
                                    # 更新symbol_info,标记已修改过订单
                                    symbol_info[symbol]['trail_profit_type'] = trail_profit_type
                                    # symbol_info[symbol]['trail_profit'] = 999999 # 设置一个极大值防止重复触发
                                    save_symbol_info(symbol_info)
                                    logger.info(f"已更新symbol_info,标记{symbol}订单已修改止损价为开仓价:{slTriggerPx}")
                                    send_wx_notification("修改止损订单成功", f"修改止损订单成功|{symbol}|{symbol_info[symbol]['attach_oid']}")
                                    break
                                else:
                                    logger.info("amend_order: "+symbol_info[symbol]['attach_oid'] + "|"+ amend_res['data'][0]['sCode'] +"|"+ amend_res['data'][0]['sMsg'])
                                    send_wx_notification("修改止损订单失败", f"修改止损订单失败|{symbol_info[symbol]['attach_oid']}|{amend_res['data'][0]['sCode']}|{amend_res['data'][0]['sMsg']}")
                            else:
                                logger.info(f"get_algo_order_details {symbol_info[symbol]['attach_oid']} failed")
                                # 如果止盈止损单不存在，则创建止盈止损单
                                # 这类情况只会存在于：限价单未完成成交，但是已经浮盈了，当浮盈超过了止损上移的点位，
                                # 发现没有止盈止损单，则对当前仓位创建止盈止损单，并取消掉原有的限价委托
                                cancel_res = tradeAPI.cancel_order(instId=symbol, ordId=symbol_info[symbol]['ord_id'])
                                if cancel_res['code'] == '0':
                                    logger.info(f"取消未完成的开仓限价委托: {symbol}, 且未能找到止盈止损单，创建新的止盈止损单")
                                    # 创建止盈止损单
                                    if symbol_info[symbol]['tp_sl_order_type'].upper() == "MARKET":
                                        tpOrdPx = -1
                                        slOrdPx = -1
                                    else:
                                        # 止盈止损如果为限价单，则为限价单的价格
                                        tpOrdPx = symbol_info[symbol]['tp_price']
                                        slOrdPx = entry_price*(1+symbol_info[symbol]['trail_profit_slip']) if pos_amount > 0 else entry_price*(1-symbol_info[symbol]['trail_profit_slip'])
                                    # 挂单
                                    place_algo_res = tradeAPI.place_algo_order(
                                        instId=symbol,
                                        tdMode="cross",
                                        side="sell" if pos_amount > 0 else "buy",
                                        ordType="oco",
                                        sz=abs(pos_amount),
                                        tpTriggerPx=tpOrdPx,
                                        tpOrdPx=tpOrdPx,
                                        slTriggerPx=slOrdPx,
                                        slOrdPx=-1,
                                    )
                                    if place_algo_res['code'] == '0':
                                        logger.info(f"创建止盈止损单成功: {symbol}")
                                        # 更新symbol_info,标记已修改过订单
                                        symbol_info[symbol]['attach_oid'] = place_algo_res['data'][0]['algoId']
                                        # symbol_info[symbol]['trail_profit'] = 999999 # 设置一个极大值防止重复触发
                                        symbol_info[symbol]['trail_profit_type'] = trail_profit_type
                                        save_symbol_info(symbol_info)
                                        logger.info(f"已更新symbol_info,标记{symbol}订单已修改止损价为开仓价:{entry_price}")
                                    else:
                                        logger.info(f"创建止盈止损单失败: {symbol}")
                                        send_wx_notification("创建止盈止损单失败", f"创建止盈止损单失败|{symbol}")
                                        logger.info(f"place_algo_res: {place_algo_res}")
                                else:
                                    logger.info(f"取消限价委托失败: {symbol}")
                                    send_wx_notification("取消未完成的限价开仓委托失败", f"取消未完成的限价开仓委托失败|{symbol}")
                    elif pos_amount != 0 and symbol_info[symbol]['bool_trail_stop']:
                        # 如果触发了追踪移动止损，则每次都需要判断一下当前价格是否从最高点回落了一定程序，如果回落了，则直接平仓
                        if uplRatio > symbol_info[symbol]['trail_stop_activation'] or symbol_info[symbol]['active_trail_stop']:
                            logger.info(f"{symbol}|当前盈利 {uplRatio:.2%}，触发追踪移动止损")
                            if symbol_info[symbol]['active_trail_stop'] is False:
                                symbol_info[symbol]['active_trail_stop'] = True
                                save_symbol_info(symbol_info)
                            # 获取当前价格以及最高点
                            # 可以直接将当前价格与记录的最高价做比较，如果发现当前价格比最高价高，则用当前价格更新最高价
                            result = publicDataAPI.get_mark_price(
                                instId=symbol,
                                instType="SWAP",
                            )
                            # 做多情况
                            if pos_amount > 0:
                                current_price = float(result['data'][0]['markPx'])
                                if current_price > symbol_info[symbol]['trail_stop_highest_price']:
                                    symbol_info[symbol]['trail_stop_highest_price'] = current_price
                                    save_symbol_info(symbol_info)
                                if (symbol_info[symbol]['trail_stop_highest_price'] - current_price) / current_price > symbol_info[symbol]['trail_stop_callback']:
                                    logger.info(f"{symbol}|做多|当前价格从最高点回落超过{symbol_info[symbol]['trail_stop_callback']}，平仓")
                                    # 平仓
                                    closeAllPosition(symbol, "cross")
                            # 做空情况
                            if pos_amount < 0:
                                current_price = float(result['data'][0]['markPx'])
                                if current_price < symbol_info[symbol]['trail_stop_lowest_price']:
                                    symbol_info[symbol]['trail_stop_lowest_price'] = current_price
                                    save_symbol_info(symbol_info)
                                if (current_price - symbol_info[symbol]['trail_stop_lowest_price']) / symbol_info[symbol]['trail_stop_lowest_price'] > symbol_info[symbol]['trail_stop_callback']:
                                    logger.info(f"{symbol}|做空|当前价格从最低点回升超过{symbol_info[symbol]['trail_stop_callback']}，平仓")
                                    # 平仓
                                    closeAllPosition(symbol, "cross")
                      
            elif pos_res['code'] != '0':
                logger.info(f"get_positions 失败: {pos_res['code']}|{pos_res['msg']}")
                send_wx_notification("获取持仓信息失败", f"获取持仓信息失败|{pos_res['code']}|{pos_res['msg']}")
        except Exception as e:
            logger.error(f"跟踪止盈监控异常: {str(e)}")
            send_wx_notification("跟踪止盈监控异常", f"跟踪止盈监控异常: {str(e)}")
        time.sleep(1)

if __name__ == '__main__':
    try:
        ip = json.load(urllib.request.urlopen('http://httpbin.org/ip'))['origin']
        logger.info(
            "It is recommended to run it on a server with an independent IP. If it is run on a personal computer, it requires FRP intranet penetration and affects the software efficiency.".format(
                listenPort=listenPort, listenHost=listenHost, ip=ip))
        logger.info(
            "Please be sure to modify apiSec in config.ini and modify it to a complex key.".format(
                listenPort=listenPort, listenHost=listenHost, ip=ip))
        logger.info(
            "The system interface service is about to start! Service listening address:{listenHost}:{listenPort}".format(
                listenPort=listenPort, listenHost=listenHost, ip=ip))
        logger.info(
            "interface addr: http://{ip}:{listenPort}/order".format(
                listenPort=listenPort, listenHost=listenHost, ip=ip))
        logger.info("It is recommended to use nohup python3 okex_trading.py & to run the program into the linux background")

        # 初始化交易币对基础信息
        if initInstruments() is False:
            msg = "Failed to initialize currency base information, please try again"
            raise Exception(msg)
        # 启动跟踪止盈监控线程
        _thread.start_new_thread(trailing_stop_monitor, ())
        # 启动服务
        app.run(debug=debugMode, port=listenPort, host=listenHost)
    except Exception as e:
        logger.info(e)
        pass
