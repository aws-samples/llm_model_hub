import logging
import os

log_dir = "logs"

if not os.path.exists(log_dir):
    os.makedirs(log_dir)
    print(f"目录 '{log_dir}' 已创建")
else:
    print(f"目录 '{log_dir}' 已存在，无需创建")

def setup_logger(name, log_file=None, level=logging.INFO):
    """设置日志器"""
    logger = logging.getLogger(name)

    # Prevent adding duplicate handlers
    if logger.handlers:
        return logger

    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    formatter = logging.Formatter(format)

    # 创建处理器：控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # 设置日志级别
    logger.setLevel(level)
    logger.addHandler(console_handler)

    # 如果指定了日志文件，添加文件处理器
    if log_file:
        file_handler = logging.FileHandler(f"{log_dir}/{log_file}")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

# 创建一个默认的日志器
default_logger = setup_logger('default')

# 提供一些便捷的日志记录函数
def debug(msg):
    default_logger.debug(msg)

def info(msg):
    default_logger.info(msg)

def warning(msg):
    default_logger.warning(msg)

def error(msg):
    default_logger.error(msg)

def critical(msg):
    default_logger.critical(msg)
