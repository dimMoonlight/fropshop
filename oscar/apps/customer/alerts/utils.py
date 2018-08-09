import logging

from django.contrib.sites.models import Site
from django.core import mail
from django.db.models import Max
from django.template import loader

from oscar.apps.customer.notifications import services
from oscar.core.loading import get_class, get_model

# 通讯事件类型
CommunicationEventType = get_model('customer', 'CommunicationEventType')
# 产品快讯
ProductAlert = get_model('customer', 'ProductAlert')
# 产品
Product = get_model('catalogue', 'Product')
# 调度员
Dispatcher = get_class('customer.utils', 'Dispatcher')
# 选择
Selector = get_class('partner.strategy', 'Selector')
# 记录仪
logger = logging.getLogger('oscar.alerts')


# 发送提醒
def send_alerts():
    """
    Send out product alerts
    发出产品提醒
    """
    products = Product.objects.filter(
        productalert__status=ProductAlert.ACTIVE
    ).distinct()
    logger.info("Found %d products with active alerts", products.count())
    for product in products:
        send_product_alerts(product)


# 发送警报确认
def send_alert_confirmation(alert):
    """
    Send an alert confirmation email.
    发送提醒确认电子邮件。
    """
    ctx = {
        'alert': alert,
        'site': Site.objects.get_current(),
    }

    code = 'PRODUCT_ALERT_CONFIRMATION'
    messages = CommunicationEventType.objects.get_and_render(code, ctx)

    if messages and messages['body']:
        Dispatcher().dispatch_direct_messages(alert.email, messages)


# 发送产品提醒
def send_product_alerts(product):   # noqa C901 too complex C901太复杂了
    """
    Check for notifications for this product and send email to users
    if the product is back in stock. Add a little 'hurry' note if the
    amount of in-stock items is less then the number of notifications.
    检查此产品的通知，如果产品有库存，则向用户发送电子邮件。 如果库存商品的
    数量少于通知数量，请添加一些“快点”注释。
    """
    stockrecords = product.stockrecords.all()
    num_stockrecords = len(stockrecords)
    if not num_stockrecords:
        return

    logger.info("Sending alerts for '%s'", product)
    alerts = ProductAlert.objects.filter(
        product_id__in=(product.id, product.parent_id),
        status=ProductAlert.ACTIVE,
    )

    # 确定'匆忙模式'
    # Determine 'hurry mode'
    if num_stockrecords == 1:
        num_in_stock = stockrecords[0].num_in_stock
    else:
        result = stockrecords.aggregate(max_in_stock=Max('num_in_stock'))
        num_in_stock = result['max_in_stock']

    # hurry_mode is false if num_in_stock is None
    # 如果num_in_stock为None，则hurry_mode为false
    hurry_mode = num_in_stock is not None and alerts.count() > num_in_stock

    code = 'PRODUCT_ALERT'
    try:
        event_type = CommunicationEventType.objects.get(code=code)
    except CommunicationEventType.DoesNotExist:
        event_type = CommunicationEventType.objects.model(code=code)

    messages_to_send = []
    user_messages_to_send = []
    num_notifications = 0
    selector = Selector()
    for alert in alerts:
        # Check if the product is available to this user
        # 检查该用户是否可以使用该产品
        strategy = selector.strategy(user=alert.user)
        data = strategy.fetch_for_product(product)
        if not data.availability.is_available_to_buy:
            continue

        ctx = {
            'alert': alert,
            'site': Site.objects.get_current(),
            'hurry': hurry_mode,
        }
        if alert.user:
            # Send a site notification
            # 发送网站通知
            num_notifications += 1
            subj_tpl = loader.get_template('customer/alerts/message_subject.html')
            message_tpl = loader.get_template('customer/alerts/message.html')
            services.notify_user(
                alert.user,
                subj_tpl.render(ctx).strip(),
                body=message_tpl.render(ctx).strip()
            )

        # Build message and add to list
        # 构建消息并添加到列表中
        messages = event_type.get_messages(ctx)

        if messages and messages['body']:
            if alert.user:
                user_messages_to_send.append(
                    (alert.user, messages)
                )
            else:
                messages_to_send.append(
                    (alert.get_email_address(), messages)
                )
        alert.close()

    # Send all messages using one SMTP connection to avoid opening lots of them
    # 使用一个SMTP连接发送所有邮件，以避免打开大量邮件
    if messages_to_send or user_messages_to_send:
        connection = mail.get_connection()
        connection.open()
        disp = Dispatcher(mail_connection=connection)
        for message in messages_to_send:
            disp.dispatch_direct_messages(*message)
        for message in user_messages_to_send:
            disp.dispatch_user_messages(*message)
        connection.close()

    logger.info("Sent %d notifications and %d messages", num_notifications,
                len(messages_to_send) + len(user_messages_to_send))
