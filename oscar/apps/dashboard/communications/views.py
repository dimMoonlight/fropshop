from django.contrib import messages
from django.contrib.sites.shortcuts import get_current_site
from django.template import TemplateSyntaxError
from django.utils.translation import gettext_lazy as _
from django.views import generic

from oscar.core.loading import get_class, get_model

CommunicationEventType = get_model('customer', 'CommunicationEventType')
CommunicationEventTypeForm = get_class('dashboard.communications.forms',
                                       'CommunicationEventTypeForm')
Dispatcher = get_class('customer.utils', 'Dispatcher')


# 列表视图
class ListView(generic.ListView):
    model = CommunicationEventType
    template_name = 'dashboard/comms/list.html'
    context_object_name = 'commtypes'


# 更新视图
class UpdateView(generic.UpdateView):
    model = CommunicationEventType
    form_class = CommunicationEventTypeForm
    template_name = 'dashboard/comms/detail.html'
    context_object_name = 'commtype'
    success_url = '.'
    slug_field = 'code'

    # 形式无效
    def form_invalid(self, form):
        messages.error(self.request,
                       _("The submitted form was not valid, please correct "
                         "the errors and resubmit"))
        return super().form_invalid(form)

    # 形式有效
    def form_valid(self, form):
        if 'send_preview' in self.request.POST:
            return self.send_preview(form)
        if 'show_preview' in self.request.POST:
            return self.show_preview(form)
        messages.success(self.request, _("Email saved"))
        return super().form_valid(form)

    # 获取消息上下文
    def get_messages_context(self, form):
        ctx = {'user': self.request.user,
               'site': get_current_site(self.request)}
        ctx.update(form.get_preview_context())
        return ctx

    # 显示预览
    def show_preview(self, form):
        ctx = super().get_context_data()
        ctx['form'] = form

        commtype = form.save(commit=False)
        commtype_ctx = self.get_messages_context(form)
        try:
            msgs = commtype.get_messages(commtype_ctx)
        except TemplateSyntaxError as e:
            form.errors['__all__'] = form.error_class([str(e)])
            return self.render_to_response(ctx)

        ctx['show_preview'] = True
        ctx['preview'] = msgs
        return self.render_to_response(ctx)

    # 发送预览
    def send_preview(self, form):
        ctx = super().get_context_data()
        ctx['form'] = form

        commtype = form.save(commit=False)
        commtype_ctx = self.get_messages_context(form)
        try:
            msgs = commtype.get_messages(commtype_ctx)
        except TemplateSyntaxError as e:
            form.errors['__all__'] = form.error_class([str(e)])
            return self.render_to_response(ctx)

        email = form.cleaned_data['preview_email']
        dispatch = Dispatcher()
        dispatch.send_email_messages(email, msgs)
        messages.success(self.request,
                         _("A preview email has been sent to %s") % email)

        return self.render_to_response(ctx)
