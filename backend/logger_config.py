import logging

def setup_logger(name, log_file=None, level=logging.INFO):
    """设置日志器"""
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # 创建处理器：控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # 创建日志器，设置日志级别
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(console_handler)

    # 如果指定了日志文件，添加文件处理器
    if log_file:
        file_handler = logging.FileHandler(log_file)
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
