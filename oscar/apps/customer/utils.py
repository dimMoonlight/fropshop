import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from oscar.core.loading import get_model

# 通信事件
CommunicationEvent = get_model('order', 'CommunicationEvent')
# 电子邮件
Email = get_model('customer', 'Email')


# 调度员
class Dispatcher(object):
    def __init__(self, logger=None, mail_connection=None):
        if not logger:
            logger = logging.getLogger(__name__)
        self.logger = logger
        # Supply a mail_connection if you want the dispatcher to use that
        # instead of opening a new one.
        # 如果您希望调度程序使用它而不是打开一个新的，请提供mail_connection。
        self.mail_connection = mail_connection

    # Public API methods
    # 公共API方法

    # 发送直接消息
    def dispatch_direct_messages(self, recipient, messages):
        """
        Dispatch one-off messages to explicitly specified recipient.

        将一次性消息发送给明确指定的收件人。
        """
        if messages['subject'] and (messages['body'] or messages['html']):
            return self.send_email_messages(recipient, messages)

    # 发送订单消息
    def dispatch_order_messages(self, order, messages, event_type=None, **kwargs):
        """
        Dispatch order-related messages to the customer.
        向客户发送与订单相关的消息。
        """
        if order.is_anonymous:
            email = kwargs.get('email_address', order.guest_email)
            dispatched_messages = self.dispatch_anonymous_messages(email, messages)
        else:
            dispatched_messages = self.dispatch_user_messages(order.user, messages)

        self.create_communication_event(order, event_type, dispatched_messages)

    # 发送匿名消息
    def dispatch_anonymous_messages(self, email, messages):
        dispatched_messages = {}
        if email:
            dispatched_messages['email'] = self.send_email_messages(email, messages), None
        return dispatched_messages

    # 发送用户消息
    def dispatch_user_messages(self, user, messages):
        """
        Send messages to a site user
        向站点用户发送消息
        """
        dispatched_messages = {}
        if messages['subject'] and (messages['body'] or messages['html']):
            dispatched_messages['email'] = self.send_user_email_messages(user, messages)
        if messages['sms']:
            dispatched_messages['sms'] = self.send_text_message(user, messages['sms'])
        return dispatched_messages

    # Internal 内部

    # 创建通信事件
    def create_communication_event(self, order, event_type, dispatched_messages):
        """
        Create order communications event for audit
        为审计创建订单通信事件
        """
        if dispatched_messages and event_type is not None:
            CommunicationEvent._default_manager.create(order=order, event_type=event_type)

    # 创建客户电子邮件
    def create_customer_email(self, user, messages, email):
        """
        Create Email instance in database for logging purposes.
        在数据库中创建用于日志记录的电子邮件实例。
        """
        # Is user is signed in, record the event for audit
        # 用户是否签到，记录事件以供审核
        if email and user.is_authenticated:
            return Email._default_manager.create(user=user,
                                                 email=user.email,
                                                 subject=email.subject,
                                                 body_text=email.body,
                                                 body_html=messages['html'])

    # 发送用户电子邮件消息
    def send_user_email_messages(self, user, messages):
        """
        Send message to the registered user / customer and collect data in database.
        向注册用户/客户发送消息，并在数据库中收集数据。
        """
        if not user.email:
            self.logger.warning("Unable to send email messages as user #%d has"
                                " no email address", user.id)
            return None, None

        email = self.send_email_messages(user.email, messages)
        return email, self.create_customer_email(user, messages, email)

    # 发送电子邮件消息
    def send_email_messages(self, recipient, messages):
        """
        Send email to recipient, HTML attachment optional.
        发送电子邮件到收件人，HTML附件可选。
        """
        if hasattr(settings, 'OSCAR_FROM_EMAIL'):
            from_email = settings.OSCAR_FROM_EMAIL
        else:
            from_email = None

        # Determine whether we are sending a HTML version too
        # 确定我们是否也发送HTML版本
        if messages['html']:
            email = EmailMultiAlternatives(messages['subject'],
                                           messages['body'],
                                           from_email=from_email,
                                           to=[recipient])
            email.attach_alternative(messages['html'], "text/html")
        else:
            email = EmailMessage(messages['subject'],
                                 messages['body'],
                                 from_email=from_email,
                                 to=[recipient])
        self.logger.info("Sending email to %s" % recipient)

        if self.mail_connection:
            self.mail_connection.send_messages([email])
        else:
            email.send()

        return email

    # 发送文本消息
    def send_text_message(self, user, event_type):
        raise NotImplementedError


# 获取密码重置URL
def get_password_reset_url(user, token_generator=default_token_generator):
    """
    Generate a password-reset URL for a given user
    为给定用户生成密码重置URL
    """
    kwargs = {
        'token': token_generator.make_token(user),
        'uidb64': urlsafe_base64_encode(force_bytes(user.id)).decode(),
    }
    return reverse('password-reset-confirm', kwargs=kwargs)


# 规范电子邮件
def normalise_email(email):
    """
    The local part of an email address is case-sensitive, the domain part
    isn't.  This function lowercases the host and should be used in all email
    handling.
    电子邮件地址的本地部分是区分大小写的，域部分不是。这个函数会降低主机
    的值，并且应该在所有的电子邮件处理中使用。
    """
    clean_email = email.strip()
    if '@' in clean_email:
        local, host = clean_email.split('@')
        return local + '@' + host.lower()
    return clean_email
