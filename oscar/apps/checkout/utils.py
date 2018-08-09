# 检查会话数据
class CheckoutSessionData(object):
    """
    Responsible for marshalling all the checkout session data

    Multi-stage checkouts often require several forms to be submitted and their
    data persisted until the final order is placed. This class helps store and
    organise checkout form data until it is required to write out the final
    order.

    负责编组所有结账会话数据

    多阶段结账通常需要提交多种表格，并且数据会一直存在，直到下达最终订单。 此类
    有助于存储和组织结帐表单数据，直到需要写出最终订单。
    """
    SESSION_KEY = 'checkout_data'

    def __init__(self, request):
        self.request = request
        if self.SESSION_KEY not in self.request.session:
            self.request.session[self.SESSION_KEY] = {}

    # 检查命名空间
    def _check_namespace(self, namespace):
        """
        Ensure a namespace within the session dict is initialised
        确保初始化会话dict中的命名空间
        """
        if namespace not in self.request.session[self.SESSION_KEY]:
            self.request.session[self.SESSION_KEY][namespace] = {}

    def _get(self, namespace, key, default=None):
        """
        Return a value from within a namespace
        从命名空间中返回一个值
        """
        self._check_namespace(namespace)
        if key in self.request.session[self.SESSION_KEY][namespace]:
            return self.request.session[self.SESSION_KEY][namespace][key]
        return default

    def _set(self, namespace, key, value):
        """
        Set a namespaced value
        设置命名空间值
        """
        self._check_namespace(namespace)
        self.request.session[self.SESSION_KEY][namespace][key] = value
        self.request.session.modified = True

    def _unset(self, namespace, key):
        """
        Remove a namespaced value
        删除命名空间值
        """
        self._check_namespace(namespace)
        if key in self.request.session[self.SESSION_KEY][namespace]:
            del self.request.session[self.SESSION_KEY][namespace][key]
            self.request.session.modified = True

    def _flush_namespace(self, namespace):
        """
        Flush a namespace
        刷新命名空间s
        """
        self.request.session[self.SESSION_KEY][namespace] = {}
        self.request.session.modified = True

    def flush(self):
        """
        Flush all session data
        刷新所有会话数据
        """
        self.request.session[self.SESSION_KEY] = {}

    # Guest checkout
    # 客人结账
    # ==============

    def set_guest_email(self, email):
        self._set('guest', 'email', email)

    def get_guest_email(self):
        return self._get('guest', 'email')

    # Shipping address
    # 邮寄地址
    # ================
    # Options:
    # 1. No shipping required (eg digital products)
    # 2. Ship to new address (entered in a form)
    # 3. Ship to an address book address (address chosen from list)
    # 选项：
    # 1.不需要运输（例如数码产品）
    # 2.运送到新地址（以表格形式输入）
    # 3.发送到地址簿地址（从列表中选择的地址）


    # 重置送货数据
    def reset_shipping_data(self):
        self._flush_namespace('shipping')

    # 运送到用户地址
    def ship_to_user_address(self, address):
        """
        Use an user address (from an address book) as the shipping address.
        使用用户地址（来自地址簿）作为送货地址
        """
        self.reset_shipping_data()
        self._set('shipping', 'user_address_id', address.id)

    # 运送到新地址
    def ship_to_new_address(self, address_fields):
        """
        Use a manually entered address as the shipping address
        使用手动输入的地址作为送货地址
        """
        self._unset('shipping', 'new_address_fields')
        phone_number = address_fields.get('phone_number')
        if phone_number:
            # Phone number is stored as a PhoneNumber instance. As we store
            # strings in the session, we need to serialize it.
            # 电话号码存储为PhoneNumber实例。 当我们在会话中存储字符串时，我们需要对其进行序列化。
            address_fields = address_fields.copy()
            address_fields['phone_number'] = phone_number.as_international
        self._set('shipping', 'new_address_fields', address_fields)

    # 新的送货地址字段
    def new_shipping_address_fields(self):
        """
        Return shipping address fields
        返回送货地址字段
        """
        return self._get('shipping', 'new_address_fields')

    # 运送用户地址ID
    def shipping_user_address_id(self):
        """
        Return user address id
        返回用户地址ID
        """
        return self._get('shipping', 'user_address_id')

    # Legacy accessor
    # 旧版访问者
    user_address_id = shipping_user_address_id

    # 是送货地址集
    def is_shipping_address_set(self):
        """
        Test whether a shipping address has been stored in the session.

        This can be from a new address or re-using an existing address.

        测试发货地址是否已存储在会话中。
        这可以来自新地址或重新使用现有地址。
        """
        new_fields = self.new_shipping_address_fields()
        has_new_address = new_fields is not None
        user_address_id = self.shipping_user_address_id()
        has_old_address = user_address_id is not None and user_address_id > 0
        return has_new_address or has_old_address

    # Shipping method
    # 邮寄方式
    # ===============

    # 使用免费送货
    def use_free_shipping(self):
        """
        Set "free shipping" code to session
        将“免费送货”代码设置为会话
        """
        self._set('shipping', 'method_code', '__free__')

    # 使用送货方式
    def use_shipping_method(self, code):
        """
        Set shipping method code to session
        将送货方式代码设置为会话
        """
        self._set('shipping', 'method_code', code)

    # 送货方式代码
    def shipping_method_code(self, basket):
        """
        Return the shipping method code
        退回送货方式代码
        """
        return self._get('shipping', 'method_code')

    # 是运输方法集
    def is_shipping_method_set(self, basket):
        """
        Test if a valid shipping method is stored in the session
        测试会话中是否存储了有效的送货方式
        """
        return self.shipping_method_code(basket) is not None

    # Billing address fields
    # 帐单邮寄地址字段
    # ======================
    #
    # There are 3 common options:
    # 1. Billing address is entered manually through a form
    # 2. Billing address is selected from address book
    # 3. Billing address is the same as the shipping address
    # 共有3种常见选择：
    # 1.通过表格手动输入账单地址
    # 2.帐单地址从地址簿中选择
    # 3.结算地址与送货地址相同

    # 账单到新地址
    def bill_to_new_address(self, address_fields):
        """
        Store address fields for a billing address.
        存储帐单邮寄地址的地址字段。
        """
        self._unset('billing', 'new_address_fields')
        phone_number = address_fields.get('phone_number')
        if phone_number:
            # Phone number is stored as a PhoneNumber instance. As we store
            # strings in the session, we need to serialize it.
            # 电话号码存储为PhoneNumber实例。 当我们在会话中存储字符串时，我们需要对其进行序列化。
            address_fields = address_fields.copy()
            address_fields['phone_number'] = phone_number.as_international
        self._set('billing', 'new_address_fields', address_fields)

    # 账单到用户地址
    def bill_to_user_address(self, address):
        """
        Set an address from a user's address book as the billing address

        :address: The address object
        将用户地址簿中的地址设置为帐单地址：地址：地址对象
        """
        self._flush_namespace('billing')
        self._set('billing', 'user_address_id', address.id)

    # 账单到送货地址
    def bill_to_shipping_address(self):
        """
        Record fact that the billing address is to be the same as
        the shipping address.
        记录账单地址与送货地址相同的事实。
        """
        self._flush_namespace('billing')
        self._set('billing', 'billing_address_same_as_shipping', True)

    # Legacy method name
    # 遗留方法名称
    billing_address_same_as_shipping = bill_to_shipping_address

    # 帐单邮寄地址与送货地址相同
    def is_billing_address_same_as_shipping(self):
        return self._get('billing', 'billing_address_same_as_shipping', False)

    # 结算用户地址ID
    def billing_user_address_id(self):
        """
        Return the ID of the user address being used for billing
        返回用于计费的用户地址的ID
        """
        return self._get('billing', 'user_address_id')

    # 新的帐单邮寄地址字段
    def new_billing_address_fields(self):
        """
        Return fields for a billing address
        返回帐单邮寄地址的字段
        """
        return self._get('billing', 'new_address_fields')

    # 是帐单地址集
    def is_billing_address_set(self):
        """
        Test whether a billing address has been stored in the session.

        This can be from a new address or re-using an existing address.

        测试帐单地址是否已存储在会话中。
        这可以来自新地址或重新使用现有地址。
        """
        if self.is_billing_address_same_as_shipping():
            return True
        new_fields = self.new_billing_address_fields()
        has_new_address = new_fields is not None
        user_address_id = self.billing_user_address_id()
        has_old_address = user_address_id is not None and user_address_id > 0
        return has_new_address or has_old_address

    # Payment methods
    # 支付方式
    # ===============

    def pay_by(self, method):
        self._set('payment', 'method', method)

    def payment_method(self):
        return self._get('payment', 'method')

    # Submission methods
    # 提交方法
    # ==================

    def set_order_number(self, order_number):
        self._set('submission', 'order_number', order_number)

    def get_order_number(self):
        return self._get('submission', 'order_number')

    def set_submitted_basket(self, basket):
        self._set('submission', 'basket_id', basket.id)

    def get_submitted_basket_id(self):
        return self._get('submission', 'basket_id')
