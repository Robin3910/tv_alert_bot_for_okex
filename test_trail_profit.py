import unittest
from unittest.mock import patch, MagicMock
import json
import time
from okex_trading import trailing_stop_monitor

# 测试移动止盈
class TestTrailingStopMonitor(unittest.TestCase):
    def setUp(self):
        # 设置测试环境
        self.symbol_info = {
            'BTC-USDT-SWAP': {
                'leverage': '10',
                'trail_stop_activation': 0.02,
                'trail_stop_callback': 0.005,
                'bool_trail_stop': False,
                'active_trail_stop': False,
                'trail_stop_highest_price': 0,
                'trail_profit_3_activation': 0.1,
                'trail_profit_2_activation': 0.05,
                'trail_profit_3_percent': 0.05,
                'trail_profit_2_percent': 0.02,
                'trail_profit_slip': 0.001,
                'trail_profit_type': 0,
                'attach_oid': 'test_algo_id'
            }
        }
    
    @patch('okex_trading.accountAPI')
    @patch('okex_trading.publicDataAPI')
    @patch('okex_trading.tradeAPI')
    @patch('okex_trading.load_symbol_info')
    @patch('okex_trading.save_symbol_info')
    def test_trailing_stop_normal_case(self, mock_save_info, mock_load_info, mock_trade_api, mock_public_api, mock_account_api):
        # 模拟持仓数据
        mock_account_api.get_positions.return_value = {
            'code': '0',
            'data': [{
                'instId': 'BTC-USDT-SWAP',
                'pos': '1',
                'avgPx': '50000',
                'uplRatio': '0.3'  # 3%的收益率
            }]
        }
        
        # 创建一个生成器函数来模拟每秒变化的价格
        def price_generator():
            prices = ['50000', '51000', '52000', '51700']
            for price in prices:
                yield {
                    'data': [{
                        'markPx': price  # 每秒变化一次价格
                    }]
                }
                time.sleep(2)
        
        mock_public_api.get_mark_price.side_effect = price_generator()
        
        mock_load_info.return_value = self.symbol_info
        
        # 执行测试
        with self.assertLogs() as log:
            trailing_stop_monitor()
            
        # 验证日志输出
        self.assertIn('触发追踪移动止损', log.output[0])
        
        # 验证最高价是否被更新
        mock_save_info.assert_called_with({
            'BTC-USDT-SWAP': {
                **self.symbol_info['BTC-USDT-SWAP'],
                'active_trail_stop': True,
                'trail_stop_highest_price': 52000
            }
        })

    # @patch('okex_trading.accountAPI')
    # @patch('okex_trading.publicDataAPI')
    # @patch('okex_trading.tradeAPI')
    # @patch('okex_trading.load_symbol_info')
    # def test_trailing_stop_trigger_close(self, mock_load_info, mock_trade_api, mock_public_api, mock_account_api):
    #     # 模拟持仓数据
    #     mock_account_api.get_positions.return_value = {
    #         'code': '0',
    #         'data': [{
    #             'instId': 'BTC-USDT-SWAP',
    #             'pos': '1',
    #             'avgPx': '50000',
    #             'uplRatio': '0.3' # 需要加入杠杆进行计算
    #         }]
    #     }
        
    #     # 设置最高价和当前价格,触发平仓条件
    #     self.symbol_info['BTC-USDT-SWAP']['trail_stop_highest_price'] = 52000
    #     self.symbol_info['BTC-USDT-SWAP']['active_trail_stop'] = True
    #     mock_load_info.return_value = self.symbol_info
        
        
        
    #     # 模拟平仓API
    #     mock_trade_api.close_positions.return_value = {'code': '0'}
        
    #     # 执行测试
    #     with self.assertLogs() as log:
    #         # 创建一个生成器函数来模拟每秒变化的价格
    #         def price_generator():
    #             prices = ['52000', '52000', '52000', '51700']
    #             for price in prices:
    #                 yield {
    #                     'data': [{
    #                         'markPx': price  # 每秒变化一次价格
    #                     }]
    #                 }
    #                 time.sleep(2)
            
    #         mock_public_api.get_mark_price.side_effect = price_generator()
    #         trailing_stop_monitor()
            
    #     # 验证是否调用了平仓API
    #     mock_trade_api.close_positions.assert_called_once()
    #     self.assertIn('平仓', log.output[0])

    # @patch('okex_trading.accountAPI')
    # @patch('okex_trading.load_symbol_info')
    # def test_no_position(self, mock_load_info, mock_account_api):
    #     # 模拟无持仓状态
    #     mock_account_api.get_positions.return_value = {
    #         'code': '0',
    #         'data': []
    #     }
        
    #     mock_load_info.return_value = self.symbol_info
        
    #     # 执行测试
    #     trailing_stop_monitor()
        
    #     # 验证没有进行其他操作
    #     mock_load_info.assert_called_once()

    # @patch('okex_trading.accountAPI')
    # @patch('okex_trading.load_symbol_info')
    # def test_api_error(self, mock_load_info, mock_account_api):
    #     # 模拟API错误
    #     mock_account_api.get_positions.return_value = {
    #         'code': '500',
    #         'msg': 'Internal Server Error'
    #     }
        
    #     mock_load_info.return_value = self.symbol_info
        
    #     # 执行测试
    #     with self.assertLogs() as log:
    #         trailing_stop_monitor()
            
    #     # 验证错误日志
    #     self.assertIn('获取持仓信息失败', log.output[0])

if __name__ == '__main__':
    unittest.main() 