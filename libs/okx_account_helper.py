import datetime
import json
import os.path
import time
import traceback

import requests
from flask import request

from libs.log_helper import get_logger
from libs.okx_account import OkxAccount
from libs.sqlite_helper import SQliteHelper


class OkxAccountHelper:
    def __init__(self, root_path="",logger=None):
        logger.debug("初始化OkxAccountHelper")
        # 初始化日志
        self.logger=logger
        # 初始化应用路劲
        self.root_path = root_path
        # 按照key索引存放账户信息
        self.accounts = []
        # 初始化配置文件中所有的账户
        self.init_accounts()
        #配置文件
        self.config = self.get_config()
    pass

    def init_accounts(self):
        self.logger.info("开始加载所有账户信息")
        # 加载json
        config_path = os.path.join(self.root_path, "account_conifg.json")
        with open(config_path, 'r') as f:
            config = json.load(f)
            for account in config['account_list']:
                account_info = {
                    "api_key": account['api_key'],
                    "instance": OkxAccount(api_key=account['api_key'], api_secret=account['secret_key'],
                                           api_passphrase=account['passphrase'], flag=account['flag'],logger=self.logger,okx_helper=self)
                }
                # 实例化账户类
                self.accounts.append(account_info)
                self.logger.info(f"初始化账户: {account['api_key']}")
                pass

    # 根据api_key获取账户实例
    def get_account_info(self, api_key):
        for account in self.accounts:
            if account['api_key'] == api_key:
                return account['instance']
        pass

    # 加载全局配置文件
    def get_config(self):
        try:
            config_path = os.path.join(self.root_path, "account_conifg.json")
            with open(config_path, 'r') as f:
                config = json.load(f)
                return config
        except Exception as e:
            self.logger.error(f"读取配置文件出错: {str(e)}")
            return None

    def send_wx_notification(self,title, message):
        return ""
        """
        发送微信通知
        Args:
            title: 通知标题
            message: 通知内容
        """
        try:
            # https://sctapi.ftqq.com/SCT264877TGGj20niEYBVMMFU1aN6NQF6g.send?title=test
            requests.get(f'https://sctapi.ftqq.com/{self.config["global"]["wx_token"]}.send?text={title}&desp={message}')
            self.logger.info('发送微信消息成功')
        except Exception as e:
            self.logger.error(f'发送微信消息失败: {str(e)}')

    def trailing_stop_monitor(self,instance):
        self.logger.debug("开始执行上移止损监控")
        accountAPI=instance.get_account_api()
        tradeAPI=instance.get_trade_api()
        publicDataAPI=instance.get_public_api()
        while True:
            try:
                # 获取当前持仓信息
                pos_res = accountAPI.get_positions()
                self.logger.info(f"【{instance.api_key}】监控线程获取持仓信息:\n{str(pos_res)}")
                if pos_res['code'] == '0' and len(pos_res['data']) > 0:
                    # 加载本地保存的订单信息
                    symbol_info = self.load_symbol_info(instance)
                    self.logger.info(f"【{instance.api_key}】监控线程获取本地持仓信息:\n{str(symbol_info)}")
                    # 循环获取仓位持有信息
                    for position in pos_res['data']:
                        # 获取产品id 如BTC-USDT-SWAP
                        symbol = position['instId']
                        # 如果没有本地持仓信息 跳过循环
                        if symbol not in symbol_info:
                            self.logger.warning(f"【{instance.api_key}】监控线程获取无法获取{symbol}的本地持仓信息:\n{str(symbol_info)}")
                            break
                        pos_amount = float(position['pos'])
                        entry_price = float(position['avgPx'])
                        uplRatio = float(position['uplRatio']) / int(symbol_info[symbol]['leverage'])
                        # 如果有持仓
                        if pos_amount != 0 and not symbol_info[symbol]['bool_trail_stop']:
                            slTriggerPx = 0
                            trail_profit_type = 0
                            # 分成多段上移止损位
                            if uplRatio >= symbol_info[symbol]['trail_profit_3_activation'] and symbol_info[symbol][
                                'trail_profit_type'] < 3:
                                slTriggerPx = entry_price * (1 + symbol_info[symbol]['trail_profit_3_percent']) * (
                                            1 + symbol_info[symbol][
                                        'trail_profit_slip']) if pos_amount > 0 else entry_price * (
                                            1 - symbol_info[symbol]['trail_profit_3_percent']) * (1 -
                                                                                                  symbol_info[symbol][
                                                                                                      'trail_profit_slip'])
                                trail_profit_type = 3
                            elif uplRatio >= symbol_info[symbol]['trail_profit_2_activation'] and symbol_info[symbol][
                                'trail_profit_type'] < 2:
                                slTriggerPx = entry_price * (1 + symbol_info[symbol]['trail_profit_2_percent']) * (
                                            1 + symbol_info[symbol][
                                        'trail_profit_slip']) if pos_amount > 0 else entry_price * (
                                            1 - symbol_info[symbol]['trail_profit_2_percent']) * (1 -
                                                                                                  symbol_info[symbol][
                                                                                                      'trail_profit_slip'])
                                trail_profit_type = 2
                            elif uplRatio >= symbol_info[symbol]['trail_profit'] and symbol_info[symbol][
                                'trail_profit_type'] < 1:
                                slTriggerPx = entry_price * (1 + symbol_info[symbol]['trail_profit_1_percent']) * (
                                            1 + symbol_info[symbol][
                                        'trail_profit_slip']) if pos_amount > 0 else entry_price * (
                                            1 - symbol_info[symbol]['trail_profit_1_percent']) * (1 -
                                                                                                  symbol_info[symbol][
                                                                                                      'trail_profit_slip'])
                                trail_profit_type = 1
                            else:
                                slTriggerPx = 0

                            # 如果浮盈超过止盈上移的点位，则修改止盈止损单
                            if slTriggerPx > 0:
                                self.logger.info(
                                    f"{symbol}|当前盈利 {uplRatio:.2%}，触发跟踪止盈, 当前止损位置: {slTriggerPx}，第 {trail_profit_type} 级止损位")
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
                                        self.logger.info(f"修改订单成功: {symbol_info[symbol]['attach_oid']}")
                                        # 更新symbol_info,标记已修改过订单
                                        symbol_info[symbol]['trail_profit_type'] = trail_profit_type
                                        # symbol_info[symbol]['trail_profit'] = 999999 # 设置一个极大值防止重复触发
                                        self.save_symbol_info(symbol_info,instance)
                                        self.logger.info(
                                            f"已更新symbol_info,标记{symbol}订单已修改止损价为开仓价:{slTriggerPx}")
                                        self.send_wx_notification("修改止损订单成功",
                                                             f"修改止损订单成功|{symbol}|{symbol_info[symbol]['attach_oid']}")
                                        break
                                    else:
                                        self.logger.info("amend_order: " + symbol_info[symbol]['attach_oid'] + "|" +
                                                    amend_res['data'][0]['sCode'] + "|" + amend_res['data'][0]['sMsg'])
                                        self.send_wx_notification("修改止损订单失败",
                                                             f"修改止损订单失败|{symbol_info[symbol]['attach_oid']}|{amend_res['data'][0]['sCode']}|{amend_res['data'][0]['sMsg']}")
                                else:
                                    self.logger.info(f"get_algo_order_details {symbol_info[symbol]['attach_oid']} failed")
                                    # 如果止盈止损单不存在，则创建止盈止损单
                                    # 这类情况只会存在于：限价单未完成成交，但是已经浮盈了，当浮盈超过了止损上移的点位，
                                    # 发现没有止盈止损单，则对当前仓位创建止盈止损单，并取消掉原有的限价委托
                                    cancel_res = tradeAPI.cancel_order(instId=symbol,
                                                                       ordId=symbol_info[symbol]['ord_id'])
                                    if cancel_res['code'] == '0':
                                        self.logger.info(
                                            f"取消未完成的开仓限价委托: {symbol}, 且未能找到止盈止损单，创建新的止盈止损单")
                                        # 创建止盈止损单
                                        if symbol_info[symbol]['tp_sl_order_type'].upper() == "MARKET":
                                            tpOrdPx = -1
                                            slOrdPx = -1
                                        else:
                                            # 止盈止损如果为限价单，则为限价单的价格
                                            tpOrdPx = symbol_info[symbol]['tp_price']
                                            slOrdPx = entry_price * (1 + symbol_info[symbol][
                                                'trail_profit_slip']) if pos_amount > 0 else entry_price * (
                                                        1 - symbol_info[symbol]['trail_profit_slip'])
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
                                            self.logger.info(f"创建止盈止损单成功: {symbol}")
                                            # 更新symbol_info,标记已修改过订单
                                            symbol_info[symbol]['attach_oid'] = place_algo_res['data'][0]['algoId']
                                            # symbol_info[symbol]['trail_profit'] = 999999 # 设置一个极大值防止重复触发
                                            symbol_info[symbol]['trail_profit_type'] = trail_profit_type
                                            self.save_symbol_info(symbol_info,instance)
                                            self.logger.info(
                                                f"已更新symbol_info,标记{symbol}订单已修改止损价为开仓价:{entry_price}")
                                        else:
                                            self.logger.info(f"创建止盈止损单失败: {symbol}")
                                            self.send_wx_notification("创建止盈止损单失败", f"创建止盈止损单失败|{symbol}")
                                            self.logger.info(f"place_algo_res: {place_algo_res}")
                                    else:
                                        self.logger.info(f"取消限价委托失败: {symbol}")
                                        self.send_wx_notification("取消未完成的限价开仓委托失败",
                                                             f"取消未完成的限价开仓委托失败|{symbol}")
                        elif pos_amount != 0 and symbol_info[symbol]['bool_trail_stop']:
                            # 如果触发了追踪移动止损，则每次都需要判断一下当前价格是否从最高点回落了一定程序，如果回落了，则直接平仓
                            if uplRatio > symbol_info[symbol]['trail_stop_activation'] or symbol_info[symbol][
                                'active_trail_stop']:
                                self.logger.info(f"{symbol}|当前盈利 {uplRatio:.2%}，触发追踪移动止损")
                                if symbol_info[symbol]['active_trail_stop'] is False:
                                    symbol_info[symbol]['active_trail_stop'] = True
                                    self.save_symbol_info(symbol_info,instance)
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
                                        self.save_symbol_info(symbol_info,instance)
                                    if (symbol_info[symbol][
                                            'trail_stop_highest_price'] - current_price) / current_price > \
                                            symbol_info[symbol]['trail_stop_callback']:
                                        self.logger.info(
                                            f"{symbol}|做多|当前价格从最高点回落超过{symbol_info[symbol]['trail_stop_callback']}，平仓")
                                        # 平仓
                                        instance.close_all_position(symbol, "cross")
                                # 做空情况
                                if pos_amount < 0:
                                    current_price = float(result['data'][0]['markPx'])
                                    if current_price < symbol_info[symbol]['trail_stop_lowest_price']:
                                        symbol_info[symbol]['trail_stop_lowest_price'] = current_price
                                        self.save_symbol_info(symbol_info,instance)
                                    if (current_price - symbol_info[symbol]['trail_stop_lowest_price']) / \
                                            symbol_info[symbol]['trail_stop_lowest_price'] > symbol_info[symbol][
                                        'trail_stop_callback']:
                                        self.logger.info(
                                            f"{symbol}|做空|当前价格从最低点回升超过{symbol_info[symbol]['trail_stop_callback']}，平仓")
                                        # 平仓
                                        instance.close_all_position(symbol, "cross")

                elif pos_res['code'] != '0':
                    self.logger.info(f"get_positions 失败: {pos_res['code']}|{pos_res['msg']}")
                    self.send_wx_notification("获取持仓信息失败", f"获取持仓信息失败|{pos_res['code']}|{pos_res['msg']}")
            except Exception as e:
                self.logger.error(f"跟踪止盈监控异常: {traceback.format_exc()}")
                self.send_wx_notification("跟踪止盈监控异常", f"跟踪止盈监控异常: {str(e)}")
            time.sleep(1)

    def load_symbol_info(self,instance):
        # 链接数据库
        sqlite_helper = SQliteHelper(os.path.join(self.root_path, "db", "symbol_info.db"))
        try:
            sqlite_helper.begin()
            f=sqlite_helper.query_one("SELECT * FROM symbol_info where api_key=?", (instance.api_key,))
            sqlite_helper.commit()
            if f is not None:
                return json.loads(dict(f)['data'])
        except Exception as e:
            sqlite_helper.rollback()
            self.send_wx_notification("读取symbol信息缓存出错", f"读取symbol信息缓存出错: {str(e)}")
            self.logger.error(f"读取symbol信息缓存出错: {traceback.format_exc()}")
        finally:
            sqlite_helper.close()
        return {}

    # 更新保存缓存函数
    def save_symbol_info(self,cache,instance):
        # 链接数据库
        sqlite_helper = SQliteHelper(os.path.join(self.root_path, "db", "symbol_info.db"))
        try:
            self.logger.info(f"{instance.api_key}保存的数据是\n{json.dumps(cache)}")
            sqlite_helper.begin()
            sqlite_helper.execute("INSERT OR REPLACE INTO symbol_info (`api_key`, `data`,`created_time`) VALUES (?, ?,?)",
                                  (instance.api_key, json.dumps(cache), datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            sqlite_helper.commit()
        except Exception as e:
            sqlite_helper.rollback()
            self.send_wx_notification("保存symbol信息缓存出错", f"保存symbol信息缓存出错: {str(e)}")
            self.logger.error(f"保存symbol信息缓存出错: {traceback.format_exc()}")
        finally:
            sqlite_helper.close()

    def prefix_symbol(self,s: str) -> str:
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
    # 下单
    def order(self,instance: OkxAccount):
        self.logger.info(f"【{instance.api_key}】下单开始接收到的参数是:\n {request.json}")
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
        # 合约币种信息
        symbol = self.prefix_symbol(_params['symbol'])
        self.logger.info(f"【{instance.api_key}】下单开始接收到的币种信息参数是:\n {symbol}")
        tdMode = "cross"
        action = _params['action']

        price = float(_params['price'])
        ema = float(_params['ema'])
        entry_limit = float(_params['entry_limit'])

        trail_profit = float(_params['trail_profit'] )
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
        trail_profit_1_percent = float(_params.get("trail_profit_1_percent",0))

        trail_stop_callback = float(_params['trail_stop_callback'])
        trail_stop_activation = float(_params['trail_stop_activation'])
        bool_trail_stop = True if _params['bool_trail_stop'] == "true" else False
        # 读取symbol信息
        symbol_info = self.load_symbol_info(instance)
        #  杠杆存在
        if leverage is not None:
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
                if instance.setLever(symbol, tdMode, _params['leverage']):
                    symbol_info[symbol_key]['leverage'] = _params['leverage']
                    self.save_symbol_info(symbol_info, instance)
                    self.logger.info(f"更新杠杆值成功: {symbol_key} = {_params['leverage']}")

        pos_res = instance.get_account_api().get_positions(instId=symbol)
        pos_amount = 0
        pos_side = ""
        if pos_res['code'] == '0' and len(pos_res['data']) > 0:
            pos_side = pos_res['data'][0]['posSide']
            pos_amount = float(pos_res['data'][0]['pos'])  # 这获取到的是张数，而不是币数
            self.logger.info("pre pos side: " + pos_side + "|pos amount: " + str(pos_amount))
        else:
            self.logger.info(f"当前无仓位:{symbol}| {pos_res['code']} | {pos_res['msg']}")

        # 注意：开单的时候会先把原来的仓位平掉，然后再把你的多单挂上
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
                ret["closedPosition"] = instance.close_all_position(symbol, tdMode)

            # 取消之前的挂单
            if 'ord_id' in symbol_info[symbol] and symbol_info[symbol]['ord_id'] is not None:
                instance.cancel_last_order(symbol, symbol_info[symbol]['ord_id'])
            if 'attach_oid' in symbol_info[symbol] and symbol_info[symbol]['attach_oid'] is not None:
                cancel_algo_params = [{'algoId': symbol_info[symbol]['attach_oid'], 'instId': symbol}]
                cancel_algo_res = instance.get_trade_api().cancel_algo_order(cancel_algo_params)
                if cancel_algo_res['code'] == '0':
                    self.logger.info(f"取消止盈止损单成功: {symbol}")
                else:
                    self.logger.info(f"取消止盈止损单失败: {symbol}")

            # 如果使用全部资金，则使用账户余额来计算开仓量
            if use_all_money:
                result = instance.get_account_api().get_account_balance()
                for i in result['data'][0]['details']:
                    if i['ccy'] == "USDT":
                        available_balance = float(i['availBal'])
                        self.logger.info(f"当前可用余额available_balance: {available_balance}")
                        break
                # 使用的是加上杠杆的值，这里使用资金的95%进行开仓，防止开失败
                quantity = (available_balance * 0.95 * float(leverage)) / price
                self.logger.info(f"使用全部资金，开仓量: {quantity}")

            # 开仓
            sz = instance.amountConvertToSZ(symbol, quantity, price, order_type)

            if sz < 1:
                ret['msg'] = 'Amount is too small. Please increase amount.'
            else:
                if action.lower() == "buy":
                    tp = price * (1 + tp_percent)
                    sl = price * (1 - sl_percent)
                else:
                    tp = price * (1 - tp_percent)
                    sl = price * (1 + sl_percent)
                ord_id, attach_oid, ret['msg'] = instance.create_order(symbol, sz, price, action, order_type, tdMode, tp, sl,
                                                             tp_sl_order_type)

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
                    self.logger.info(f"{symbol}|开仓成功开始保存数据\n{symbol_info}")
                    self.save_symbol_info(symbol_info,instance)
        # 平仓
        elif _params['side'].lower() in ["close"]:
            lastOrdType = None
            ret["closedPosition"] = instance.close_all_position(symbol, tdMode)

        # 取消挂单
        elif _params['side'].lower() in ["cancel"]:
            lastOrdType = None
            ret["cancelLastOrder"] = instance.cancel_last_order(symbol, instance.lastOrdId)
        else:
            pass

        # 发送微信通知
        # requests.get(
        #     f'https://sctapi.ftqq.com/SCT143186TIvKuCgmwWnzzzGQ6mE5qmyFU.send?title=okex_{_params["symbol"]}_{_params["side"]}')
        return ret

# if __name__ == '__main__':
#     # 日志处理
#     root_path='E:\\project-2025\\tv_alert_bot_for_okex'
#     logger = get_logger(log_path_dir=root_path)
#     helper=OkxAccountHelper(root_path,logger)
#     for account in helper.accounts:
#         c = helper.load_symbol_info(account['instance'])
#         helper.save_symbol_info(c,account['instance'])
#
#     pass