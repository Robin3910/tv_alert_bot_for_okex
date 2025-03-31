import time

import okx.Account as Account
import okx.Trade as Trade
import okx.PublicData as PublicData


class OkxAccount:
    def __init__(self, api_key, api_secret, api_passphrase, flag, logger=None, okx_helper=None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.flag = flag
        self.logger = logger
        self.okx_helper = okx_helper
        self.init_instruments()

    # 账户
    def get_account_api(self):
        return Account.AccountAPI(self.api_key, self.api_secret, self.api_passphrase, False, self.flag)

    # 交易
    def get_trade_api(self):
        return Trade.TradeAPI(self.api_key, self.api_secret, self.api_passphrase, False, self.flag)

    # 公共api
    def get_public_api(self):
        return PublicData.PublicAPI(flag=self.flag)

    # 查看账户余额
    def get_account_info(self):
        account_info = self.get_account_api().get_account_balance()
        if account_info['code'] == '0':
            return account_info['data']
        return None

    def get_decimal_places(self,tick_size):
        """
        计算价格精度，只取到第一个非零数字的位置
        例如：
        0.0001000 -> 4
        0.001 -> 3
        1.0 -> 0
        """
        if '.' not in tick_size:
            return 0
        
        decimal_part = tick_size.split('.')[1]
        for i, digit in enumerate(decimal_part):
            if digit != '0':
                return i + 1
        return 0
    # 获取公共数据，包含合约面值等信息
    def init_instruments(self):
        c = 0
        try:
            swapInstrumentsRes = self.get_account_api().get_instruments(instType="SWAP")
            # 获取永续合约基础信息
            # swapInstrumentsRes = exchange.publicGetPublicInstruments(params={"instType": "SWAP"})
            if swapInstrumentsRes['code'] == '0':
                self.swapInstruments = swapInstrumentsRes['data']
                self.tickSizeMap = {}
                for i in self.swapInstruments:
                    self.tickSizeMap[i['instId']] = self.get_decimal_places(i['tickSz'])
                self.logger.info(f"{self.api_key}永续合约基础信息: {self.swapInstruments}")
                self.logger.info(f"{self.api_key}永续合约tickSizeMap: {self.tickSizeMap}")
                c = c + 1
        except Exception as e:
            self.logger.info(f"{self.api_key}publicGetPublicInstruments 失败" + str(e))
            self.okx_helper.send_wx_notification(f"{self.api_key}获取合约信息失败", f"获取合约信息失败: {str(e)}")
        try:
            # 获取交割合约基础信息
            futureInstrumentsRes = self.get_account_api().get_instruments(instType="FUTURES")
            # futureInstrumentsRes = exchange.publicGetPublicInstruments(params={"instType": "FUTURES"})
            if futureInstrumentsRes['code'] == '0':
                self.futureInstruments = futureInstrumentsRes['data']
                self.logger.info(f"{self.api_key}交割合约基础信息: {self.futureInstruments}")
                c = c + 1
        except Exception as e:
            self.logger.info("get_instruments 失败" + str(e))
            self.okx_helper.send_wx_notification(f"{self.api_key}获取合约信息失败", f"获取合约信息失败: {str(e)}")
        return c >= 2

    # 平仓
    def close_all_position(self, _symbol, _tdMode):
        try:
            # res = exchange.privatePostTradeClosePosition(params={"instId": _symbol, "mgnMode": _tdMode})
            # logger.info("privatePostTradeClosePosition " + json.dumps(res))
            # 市价全平
            result = self.get_trade_api().close_positions(
                instId=_symbol,
                mgnMode=_tdMode,
                autoCxl=True
            )
            if result['code'] == '0':
                return True
            else:
                self.logger.info("closeAllPosition " + result["code"] + "|" + result['msg'])
                self.okx_helper.send_wx_notification(f"{self.api_key}平仓失败", f"平仓失败: {result['msg']}")
                return False
        except Exception as e:
            self.logger.info("closeAllPosition 失败" + str(e))
            self.okx_helper.send_wx_notification(f"{self.api_key}平仓失败", f"平仓失败: {str(e)}")
            return False

    def create_order(self, _symbol, _amount, _price, _side, _ordType, _tdMode, tp, sl, tp_sl_order_type):
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
            res = self.get_trade_api().place_order(
                instId=_symbol,
                tdMode=_tdMode,
                side=_side,
                ordType=_ordType,
                px=_price,
                sz=_amount,
                attachAlgoOrds=attachAlgoOrds
            )

            if res['code'] == '0':
                self.lastOrdId = res['data'][0]['ordId']
                ord_id = res['data'][0]['ordId']
                self.logger.info(
                    f"{ord_id}|{_symbol}|{_amount}|{_price}|{_side}|{_ordType}|{_tdMode}|{tp}|{sl}|create order successfully")
                self.okx_helper.send_wx_notification("创建订单成功",
                                                     f"创建订单成功{ord_id}|{_symbol}|{_amount}|{_price}|{_side}|{_ordType}|{_tdMode}|{tp}|{sl}")
                return ord_id, attachAlgoOrds[0]['attachAlgoClOrdId'], "create order successfully"
            else:
                self.logger.info(
                    f"res:{res['data'][0]['sMsg']}|{_symbol}|{_amount}|{_price}|{_side}|{_ordType}|{_tdMode}|{tp}|{sl}|create order failed")
                self.okx_helper.send_wx_notification("创建订单失败",
                                                     f"创建订单失败|{_symbol}|{_amount}|{_price}|{_side}|{_ordType}|{_tdMode}|{tp}|{sl}: {res['data'][0]['sMsg']}")
                return "", "", res['data'][0]['sMsg']
        except Exception as e:
            self.logger.info(f"{_symbol}|{_amount}|{_price}|{_side}|{_ordType}|{_tdMode}|{tp}|{sl}|create order failed")
            self.okx_helper.send_wx_notification("创建订单失败",
                                                 f"创建订单失败|{_symbol}|{_amount}|{_price}|{_side}|{_ordType}|{_tdMode}|{tp}|{sl}: {str(e)}")
            return False, str(e)

    # 设置杠杆
    def setLever(self, _symbol, _tdMode, _lever):
        try:
            res = self.get_account_api().set_leverage(
                instId=_symbol,
                lever=_lever,
                mgnMode=_tdMode
            )
            if res['code'] == '0':
                self.logger.info(f"{self.api_key}设置杠杆成功{_symbol}|{_lever}|{_tdMode}")
                return True
            else:
                self.logger.info("setLever " + res["code"] + "|" + res['msg'])
                self.okx_helper.send_wx_notification("设置杠杆失败", f"{self.api_key}|{_symbol}|{_lever}|{_tdMode}|设置杠杆失败: {res['msg']}")
                return False
        except Exception as e:
            self.logger.info("setLever 失败" + str(e))
            self.okx_helper.send_wx_notification("设置杠杆失败", f"{self.api_key}|{_symbol}|{_lever}|{_tdMode}|设置杠杆失败: {str(e)}")
            return False

    # 取消止盈止损订单
    def cancel_last_order(self,_symbol, _lastOrdId):
        try:
            result = self.get_trade_api().cancel_order(instId=_symbol, ordId=_lastOrdId)
            if result['code'] == '0':
                return True
            else:
                self.logger.info("cancelLastOrder " + result["code"] + "|" + result['msg'])
                return False
        except Exception as e:
            self.logger.info("cancelLastOrder 失败" + str(e))
            return False

    # 将 amount 币数转换为合约张数
    # 币的数量与张数之间的转换公式
    # 单位是保证金币种（币本位的币数单位为币，U本位的币数单位为U）
    # 1、币本位合约：币数=张数*面值*合约乘数/标记价格
    # 2、U本位合约：币数=张数*面值*合约乘数*标记价格
    # 交割合约和永续合约合约乘数都是1
    def amountConvertToSZ(self,_symbol, _amount, _price, _ordType):
        _symbol = _symbol.upper()
        _symbolSplit = _symbol.split("-")
        isSwap = _symbol.endswith("SWAP")

        # 获取合约面值
        def getFaceValue(_symbol):
            instruments = self.swapInstruments if isSwap else self.futureInstruments
            for i in instruments:
                if i['instId'].upper() == _symbol:
                    return float(i['ctVal'])
            return False

        faceValue = getFaceValue(_symbol)
        if faceValue is False:
            self.okx_helper.send_wx_notification("获取合约面值失败", f"获取合约面值失败: {_symbol}")
            raise Exception("getFaceValue error.")
        # 币本位合约：张数 = 币数 / 面值 / 合约乘数 * 标记价格
        # U本位合约：张数 = 币数 / 面值 / 合约乘数
        sz = float(_amount) / faceValue / 1
        if _symbolSplit[1] == "USD":
            # 如果是市价单，获取一下最新标记价格
            if _ordType.upper() == "MARKET":
                # 获取标记价格
                result = self.get_trade_api().get_mark_price(
                    instId=_symbol,
                    instType="SWAP",
                )
                _price = result['data'][0]['markPx']
            sz = sz * float(_price)
        return int(sz)
