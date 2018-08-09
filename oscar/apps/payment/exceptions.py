class PaymentError(Exception):
    pass


class UserCancelled(PaymentError):
    """
    Exception for when a customer decides to cancel their payment
    after the process has started -- for example if they press a "Cancel"
    button on a third-party payment platform.
    客户在流程开始后决定取消付款的例外情况 - 例如，如果他们在第三方支付平
    台上按“取消”按钮。
    """
    pass


class TransactionDeclined(PaymentError):
    pass


class GatewayError(PaymentError):
    pass


class InvalidGatewayRequestError(PaymentError):
    pass


class InsufficientPaymentSources(PaymentError):
    """
    Exception for when a user attempts to checkout without specifying enough
    payment sources to cover the entire order total.

    Eg. When selecting an allocation off a giftcard but not specifying a
    bankcard to take the remainder from.

    用户在未指定足够的付款来源以覆盖整个订单总额时尝试结帐的例外情况。
    例如。 选择礼品卡的分配但未指定银行卡以从中取出剩余部分时。
    """
    pass


class RedirectRequired(PaymentError):
    """
    Exception to be used when payment processsing requires a redirect
    付款处理需要重定向时使用的例外情况
    """

    def __init__(self, url):
        self.url = url


class UnableToTakePayment(PaymentError):
    """
    Exception to be used for ANTICIPATED payment errors (eg card number wrong,
    expiry date has passed).  The message passed here will be shown to the end
    user.
    用于预期付款错误的例外情况（例如卡号错误，到期日期已过）。 此处传递的消息将
    显示给最终用户。
    """
    pass
