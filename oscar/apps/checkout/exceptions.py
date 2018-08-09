# 先决条件失败
class FailedPreCondition(Exception):

    def __init__(self, url, message=None, messages=None):
        self.url = url
        if message:
            self.messages = [message]
        elif messages:
            self.messages = messages
        else:
            self.messages = []


# 通过跳过条件
class PassedSkipCondition(Exception):
    """
    To be raised when a skip condition has been passed and the current view
    should be skipped. The passed URL dictates where to.

    在跳过条件并且应该跳过当前视图时引发。 传递的URL指示在何处。
    """
    def __init__(self, url):
        self.url = url
