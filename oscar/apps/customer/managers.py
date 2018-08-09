from django.db import models


class CommunicationTypeManager(models.Manager):

    def get_and_render(self, code, context):
        """
        Return a dictionary of rendered messages, ready for sending.

        This method wraps around whether an instance of this event-type exists
        in the database.  If not, then an instance is created on the fly and
        used to generate the message contents.

        返回已呈现消息的字典，准备发送。

        此方法包含数据库中是否存在此事件类型的实例。 如果不是，则动态创建
        实例并用于生成消息内容
        """
        try:
            commtype = self.get(code=code)
        except self.model.DoesNotExist:
            commtype = self.model(code=code)
        return commtype.get_messages(context)
