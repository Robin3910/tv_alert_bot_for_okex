import logging
import logging.handlers
import os


def get_logger(log_path_dir=""):
    log_file_path = os.path.join(log_path_dir, "logs", "okx_trading.log")
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

    # 创建 TimedRotatingFileHandler
    handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_file_path,
        when="D",  # 每天
        interval=1,
        backupCount=365,  # 保留 365 天的日志
        encoding="utf-8",
        delay=False,  # 立即创建文件
        utc=False
    )
    # 设置日志格式
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y/%m/%d/ %H:%M:%S %p')
    handler.setFormatter(formatter)
    # 设置文件后缀
    handler.suffix = "%Y-%m-%d.log"
    # 获取 logger 并添加 handler
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger
