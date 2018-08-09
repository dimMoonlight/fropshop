import re
from logging import Formatter


class PciFormatter(Formatter):
    """
    Strip card numbers out of log messages to avoid leaving sensitive
    information in the logs.
    从日志消息中删除卡号，以避免在日志中留下敏感信息。
    """

    def format(self, record):
        s = Formatter.format(self, record)
        return re.sub(r'\d[ \d-]{15,22}', 'XXXX-XXXX-XXXX-XXXX', s)
