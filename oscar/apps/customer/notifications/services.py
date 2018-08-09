from oscar.core.loading import get_model

Notification = get_model('customer', 'Notification')


# 通知用户
def notify_user(user, subject, **kwargs):
    """
    Send a simple notification to a user
    向用户发送简单通知
    """
    Notification.objects.create(recipient=user, subject=subject, **kwargs)


def notify_users(users, subject, **kwargs):
    """
    Send a simple notification to an iterable of users
    向可迭代的用户发送简单通知
    """
    for user in users:
        notify_user(user, subject, **kwargs)
