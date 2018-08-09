from django.conf import settings
from django.contrib.auth import models as auth_models
from django.core.validators import RegexValidator
from django.db import models
from django.template import TemplateDoesNotExist, engines
from django.template.loader import get_template
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _

from oscar.core.compat import AUTH_USER_MODEL
from oscar.core.loading import get_class
from oscar.models.fields import AutoSlugField


CommunicationTypeManager = get_class('customer.managers', 'CommunicationTypeManager')


# 用户管理器
class UserManager(auth_models.BaseUserManager):

    # 创建用户
    def create_user(self, email, password=None, **extra_fields):
        """
        Creates and saves a User with the given email and
        password.
        使用给定的电子邮件和密码创建和保存用户。
        """
        now = timezone.now()
        if not email:
            raise ValueError('The given email must be set')
            # 必须设置给定的电子邮件
        email = UserManager.normalize_email(email)
        user = self.model(
            email=email, is_staff=False, is_active=True,
            is_superuser=False,
            last_login=now, date_joined=now, **extra_fields)

        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra_fields):
        u = self.create_user(email, password, **extra_fields)
        u.is_staff = True
        u.is_active = True
        u.is_superuser = True
        u.save(using=self._db)
        return u


# 抽象用户
class AbstractUser(auth_models.AbstractBaseUser,
                   auth_models.PermissionsMixin):
    """
    An abstract base user suitable for use in Oscar projects.

    This is basically a copy of the core AbstractUser model but without a
    username field

    适合在奥斯卡项目中使用的抽象基础用户。

    这基本上是核心AbstractUser模型的副本，但没有用户名字段
    """
    email = models.EmailField(_('email address'), unique=True)
    first_name = models.CharField(
        _('First name'), max_length=255, blank=True)
    last_name = models.CharField(
        _('Last name'), max_length=255, blank=True)
    is_staff = models.BooleanField(
        _('Staff status'), default=False,
        help_text=_('Designates whether the user can log into this admin '
                    'site.'))
    # 指定用户是否可以登录此管理站点。
    is_active = models.BooleanField(
        _('Active'), default=True,
        help_text=_('Designates whether this user should be treated as '
                    'active. Unselect this instead of deleting accounts.'))
    # 指定是否应将此用户视为活动用户。 取消选择此项而不是删除帐户
    date_joined = models.DateTimeField(_('date joined'),
                                       default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = 'email'

    class Meta:
        abstract = True
        verbose_name = _('User')
        verbose_name_plural = _('Users')

    def get_full_name(self):
        full_name = '%s %s' % (self.first_name, self.last_name)
        return full_name.strip()

    def get_short_name(self):
        return self.first_name

    def _migrate_alerts_to_user(self):
        """
        Transfer any active alerts linked to a user's email address to the
        newly registered user.
        将链接到用户电子邮件地址的任何活动警报传输给新注册的用户。
        """
        ProductAlert = self.alerts.model
        alerts = ProductAlert.objects.filter(
            email=self.email, status=ProductAlert.ACTIVE)
        alerts.update(user=self, key='', email='')

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Migrate any "anonymous" product alerts to the registered user
        # Ideally, this would be done via a post-save signal. But we can't
        # use get_user_model to wire up signals to custom user models
        # see Oscar ticket #1127, Django ticket #19218
        # 将任何“匿名”产品警报迁移到注册用户理想情况下，这将通过保存后信号
        # 完成。 但我们不能使用get_user_model将信号连接到自定义用户模型，
        # 请参阅Oscar ticket＃1127，Django ticket＃19218
        self._migrate_alerts_to_user()


# 抽象电子邮件
class AbstractEmail(models.Model):
    """
    This is a record of all emails sent to a customer.
    Normally, we only record order-related emails.

    这是发送给客户的所有电子邮件的记录。
    通常，我们只记录与订单相关的电子邮件。
    """
    user = models.ForeignKey(
        AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='emails',
        verbose_name=_("User"),
        null=True)
    email = models.EmailField(_('Email Address'), null=True, blank=True)
    subject = models.TextField(_('Subject'), max_length=255)
    body_text = models.TextField(_("Body Text"))
    body_html = models.TextField(_("Body HTML"), blank=True)
    date_sent = models.DateTimeField(_("Date Sent"), auto_now_add=True)

    class Meta:
        abstract = True
        app_label = 'customer'
        verbose_name = _('Email')
        verbose_name_plural = _('Emails')

    def __str__(self):
        if self.user:
            return _("Email to %(user)s with subject '%(subject)s'") % {
                'user': self.user.get_username(), 'subject': self.subject}
        else:
            return _("Anonymous email to %(email)s with subject '%(subject)s'") % {
                'email': self.email, 'subject': self.subject}


# 抽象通信事件类型
class AbstractCommunicationEventType(models.Model):
    """
    A 'type' of communication.  Like an order confirmation email.
    沟通的“类型”。 像订单确认电子邮件。
    """

    #: Code used for looking up this event programmatically.
    # e.g. PASSWORD_RESET. AutoSlugField uppercases the code for us because
    # it's a useful convention that's been enforced in previous Oscar versions
    # 用于以编程方式查找此事件的代码。
    # 例如 重设密码。 AutoSlugField为我们提供了代码，因为它是一个在以前
    # 的Oscar版本中强制执行的有用约定

    code = AutoSlugField(
        _('Code'), max_length=128, unique=True, populate_from='name',
        separator="_", uppercase=True, editable=True,
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z_][0-9a-zA-Z_]*$',
                # 代码只能包含字母a-z，A-Z，数字和下划线，并且不能以数字开头。
                message=_(
                    "Code can only contain the letters a-z, A-Z, digits, "
                    "and underscores, and can't start with a digit."))],
        # 用于以编程方式查找此事件的代码
        help_text=_("Code used for looking up this event programmatically"))

    #: Name is the friendly description of an event for use in the admin
    #: 名称是在管理员中使用的事件的友好描述
    name = models.CharField(
        _('Name'), max_length=255,
        # 这仅用于组织目的
        help_text=_("This is just used for organisational purposes"))

    # We allow communication types to be categorised
    # For backwards-compatibility, the choice values are quite verbose
    # 我们允许对通信类型进行分类为了向后兼容，选择值非常详细
    ORDER_RELATED = 'Order related'
    USER_RELATED = 'User related'
    CATEGORY_CHOICES = (
        (ORDER_RELATED, _('Order related')),
        (USER_RELATED, _('User related'))
    )

    category = models.CharField(
        _('Category'), max_length=255, default=ORDER_RELATED,
        choices=CATEGORY_CHOICES)

    # Template content for emails
    # NOTE: There's an intentional distinction between None and ''. None
    # instructs Oscar to look for a file-based template, '' is just an empty
    # template.
    # 电子邮件的模板内容
    # 注意：None和''之间存在故意的区别。 没有指示Oscar寻找基于文件的
    # 模板，''只是一个空模板。
    email_subject_template = models.CharField(
        _('Email Subject Template'), max_length=255, blank=True, null=True)
    email_body_template = models.TextField(
        _('Email Body Template'), blank=True, null=True)
    email_body_html_template = models.TextField(
        _('Email Body HTML Template'), blank=True, null=True,
        help_text=_("HTML template"))

    # Template content for SMS messages
    # SMS消息的模板内容
    sms_template = models.CharField(_('SMS Template'), max_length=170,
                                    blank=True, null=True,
                                    help_text=_("SMS template"))

    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)
    date_updated = models.DateTimeField(_("Date Updated"), auto_now=True)

    objects = CommunicationTypeManager()

    # File templates
    # 文件模板
    email_subject_template_file = 'customer/emails/commtype_%s_subject.txt'
    email_body_template_file = 'customer/emails/commtype_%s_body.txt'
    email_body_html_template_file = 'customer/emails/commtype_%s_body.html'
    sms_template_file = 'customer/sms/commtype_%s_body.txt'

    class Meta:
        abstract = True
        app_label = 'customer'
        verbose_name = _("Communication event type")
        verbose_name_plural = _("Communication event types")

    def get_messages(self, ctx=None):
        """
        Return a dict of templates with the context merged in

        We look first at the field templates but fail over to
        a set of file templates that follow a conventional path.

        返回合并上下文的模板的dict

        我们首先查看字段模板，但故障转移到遵循传统路径的一组文件模板。
        """
        code = self.code.lower()

        # Build a dict of message name to Template instances
        # 为Template实例构建消息名称的dict
        templates = {'subject': 'email_subject_template',
                     'body': 'email_body_template',
                     'html': 'email_body_html_template',
                     'sms': 'sms_template'}
        for name, attr_name in templates.items():
            field = getattr(self, attr_name, None)
            if field is not None:
                # Template content is in a model field
                # 模板内容位于模型字段中
                templates[name] = engines['django'].from_string(field)
            else:
                # Model field is empty - look for a file template
                # 模型字段为空 - 查找文件模板
                template_name = getattr(self, "%s_file" % attr_name) % code
                try:
                    templates[name] = get_template(template_name)
                except TemplateDoesNotExist:
                    templates[name] = None

        # Pass base URL for serving images within HTML emails
        # 传递用于在HTML电子邮件中提供图像的基本URL
        if ctx is None:
            ctx = {}
        ctx['static_base_url'] = getattr(
            settings, 'OSCAR_STATIC_BASE_URL', None)

        messages = {}
        for name, template in templates.items():
            messages[name] = template.render(ctx) if template else ''

        # Ensure the email subject doesn't contain any newlines
        # 确保电子邮件主题不包含任何换行符
        messages['subject'] = messages['subject'].replace("\n", "")
        messages['subject'] = messages['subject'].replace("\r", "")

        return messages

    def __str__(self):
        return self.name

    def is_order_related(self):
        return self.category == self.ORDER_RELATED

    def is_user_related(self):
        return self.category == self.USER_RELATED


# 抽象通知
class AbstractNotification(models.Model):
    recipient = models.ForeignKey(
        AUTH_USER_MODEL,
        db_index=True,
        on_delete=models.CASCADE,
        related_name='notifications')

    # Not all notifications will have a sender.
    # 并非所有通知都有发件人。
    sender = models.ForeignKey(
        AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True)

    # HTML is allowed in this field as it can contain links
    # 此字段允许使用HTML，因为它可以包含链接
    subject = models.CharField(max_length=255)
    body = models.TextField()

    # Some projects may want to categorise their notifications.  You may want
    # to use this field to show a different icons next to the notification.
    # 某些项目可能希望对其通知进行分类。 您可能希望使用此字段在通知旁边显示不同的图标。
    category = models.CharField(max_length=255, blank=True)

    INBOX, ARCHIVE = 'Inbox', 'Archive'
    choices = (
        (INBOX, _('Inbox')),
        (ARCHIVE, _('Archive')))
    location = models.CharField(max_length=32, choices=choices,
                                default=INBOX)

    date_sent = models.DateTimeField(auto_now_add=True)
    date_read = models.DateTimeField(blank=True, null=True)

    class Meta:
        abstract = True
        app_label = 'customer'
        ordering = ('-date_sent',)
        verbose_name = _('Notification')
        verbose_name_plural = _('Notifications')

    def __str__(self):
        return self.subject

    def archive(self):
        self.location = self.ARCHIVE
        self.save()
    archive.alters_data = True

    @property
    def is_read(self):
        return self.date_read is not None


# 抽象产品提醒
class AbstractProductAlert(models.Model):
    """
    An alert for when a product comes back in stock
    产品何时回归库存的警报
    """
    product = models.ForeignKey(
        'catalogue.Product',
        on_delete=models.CASCADE)

    # A user is only required if the notification is created by a
    # registered user, anonymous users will only have an email address
    # attached to the notification
    # 仅当注册用户创建通知时才需要用户，匿名用户将只有通知附加的电子邮件地址
    user = models.ForeignKey(
        AUTH_USER_MODEL,
        blank=True,
        db_index=True,
        null=True,
        on_delete=models.CASCADE,
        related_name="alerts",
        verbose_name=_('User'))
    email = models.EmailField(_("Email"), db_index=True, blank=True)

    # This key are used to confirm and cancel alerts for anon users
    # 此密钥用于确认和取消匿名用户的警报
    key = models.CharField(_("Key"), max_length=128, blank=True, db_index=True)

    # An alert can have two different statuses for authenticated
    # users ``ACTIVE`` and ``CANCELLED`` and anonymous users have an
    # additional status ``UNCONFIRMED``. For anonymous users a confirmation
    # and unsubscription key are generated when an instance is saved for
    # the first time and can be used to confirm and unsubscribe the
    # notifications.
    # 对于经过身份验证的用户“ACTIVE”和“CANCELLED”，警报可以有两种不
    # 同的状态，匿名用户的状态为“UNCONFIRMED”。 对于匿名用户，首次保存
    # 实例时会生成确认和取消订阅密钥，并且可用于确认和取消订阅通知。
    UNCONFIRMED, ACTIVE, CANCELLED, CLOSED = (
        'Unconfirmed', 'Active', 'Cancelled', 'Closed')
    STATUS_CHOICES = (
        (UNCONFIRMED, _('Not yet confirmed')),
        (ACTIVE, _('Active')),
        (CANCELLED, _('Cancelled')),
        (CLOSED, _('Closed')),
    )
    status = models.CharField(_("Status"), max_length=20,
                              choices=STATUS_CHOICES, default=ACTIVE)

    date_created = models.DateTimeField(_("Date created"), auto_now_add=True)
    date_confirmed = models.DateTimeField(_("Date confirmed"), blank=True,
                                          null=True)
    date_cancelled = models.DateTimeField(_("Date cancelled"), blank=True,
                                          null=True)
    date_closed = models.DateTimeField(_("Date closed"), blank=True, null=True)

    class Meta:
        abstract = True
        app_label = 'customer'
        verbose_name = _('Product alert')
        verbose_name_plural = _('Product alerts')

    @property
    def is_anonymous(self):
        return self.user is None

    @property
    def can_be_confirmed(self):
        return self.status == self.UNCONFIRMED

    @property
    def can_be_cancelled(self):
        return self.status in (self.ACTIVE, self.UNCONFIRMED)

    @property
    def is_cancelled(self):
        return self.status == self.CANCELLED

    @property
    def is_active(self):
        return self.status == self.ACTIVE

    def confirm(self):
        self.status = self.ACTIVE
        self.date_confirmed = timezone.now()
        self.save()
    confirm.alters_data = True

    def cancel(self):
        self.status = self.CANCELLED
        self.date_cancelled = timezone.now()
        self.save()
    cancel.alters_data = True

    def close(self):
        self.status = self.CLOSED
        self.date_closed = timezone.now()
        self.save()
    close.alters_data = True

    def get_email_address(self):
        if self.user:
            return self.user.email
        else:
            return self.email

    def save(self, *args, **kwargs):
        if not self.id and not self.user:
            self.key = self.get_random_key()
            self.status = self.UNCONFIRMED
        # Ensure date fields get updated when saving from modelform (which just
        # calls save, and doesn't call the methods cancel(), confirm() etc).
        # 从modelform（只调用save，并且不调用方法cancel（），confirm（）等）
        # 保存时，确保日期字段得到更新。
        if self.status == self.CANCELLED and self.date_cancelled is None:
            self.date_cancelled = timezone.now()
        if not self.user and self.status == self.ACTIVE \
                and self.date_confirmed is None:
            self.date_confirmed = timezone.now()
        if self.status == self.CLOSED and self.date_closed is None:
            self.date_closed = timezone.now()

        return super().save(*args, **kwargs)

    def get_random_key(self):
        return get_random_string(length=40, allowed_chars='abcdefghijklmnopqrstuvwxyz0123456789')

    def get_confirm_url(self):
        return reverse('customer:alerts-confirm', kwargs={'key': self.key})

    def get_cancel_url(self):
        return reverse('customer:alerts-cancel-by-key', kwargs={'key': self.key})
