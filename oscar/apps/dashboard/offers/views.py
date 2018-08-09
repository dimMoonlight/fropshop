import json

from django.conf import settings
from django.contrib import messages
from django.core import serializers
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import DeleteView, FormView, ListView

from oscar.core.loading import get_class, get_classes, get_model
from oscar.views import sort_queryset

ConditionalOffer = get_model('offer', 'ConditionalOffer')
Condition = get_model('offer', 'Condition')
Range = get_model('offer', 'Range')
Product = get_model('catalogue', 'Product')
OrderDiscount = get_model('order', 'OrderDiscount')
Benefit = get_model('offer', 'Benefit')
MetaDataForm, ConditionForm, BenefitForm, RestrictionsForm, OfferSearchForm \
    = get_classes('dashboard.offers.forms',
                  ['MetaDataForm', 'ConditionForm', 'BenefitForm',
                   'RestrictionsForm', 'OfferSearchForm'])
OrderDiscountCSVFormatter = get_class(
    'dashboard.offers.reports', 'OrderDiscountCSVFormatter')


# 报价清单视图
class OfferListView(ListView):
    model = ConditionalOffer
    context_object_name = 'offers'
    template_name = 'dashboard/offers/offer_list.html'
    form_class = OfferSearchForm
    paginate_by = settings.OSCAR_DASHBOARD_ITEMS_PER_PAGE

    def get_queryset(self):
        qs = self.model._default_manager.exclude(
            offer_type=ConditionalOffer.VOUCHER)
        qs = sort_queryset(qs, self.request,
                           ['name', 'start_datetime', 'end_datetime',
                            'num_applications', 'total_discount'])

        self.description = _("All offers")

        # We track whether the queryset is filtered to determine whether we
        # show the search form 'reset' button.
        # 我们跟踪是否过滤了查询集以确定我们是否显示搜索表单“重置”按钮。
        self.is_filtered = False
        self.form = self.form_class(self.request.GET)
        if not self.form.is_valid():
            return qs

        data = self.form.cleaned_data

        if data['name']:
            qs = qs.filter(name__icontains=data['name'])
            self.description = _("Offers matching '%s'") % data['name']
            self.is_filtered = True
        if data['is_active']:
            self.is_filtered = True
            today = timezone.now()
            qs = qs.filter(start_datetime__lte=today, end_datetime__gte=today)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['queryset_description'] = self.description
        ctx['form'] = self.form
        ctx['is_filtered'] = self.is_filtered
        return ctx


# 报价向导步骤视图
class OfferWizardStepView(FormView):
    wizard_name = 'offer_wizard'
    form_class = None
    step_name = None
    update = False
    url_name = None

    # Keep a reference to previous view class to allow checks to be made on
    # whether prior steps have been completed
    # 保留对先前视图类的引用，以允许检查先前的步骤是否已完成
    previous_view = None

    # 调度
    def dispatch(self, request, *args, **kwargs):
        if self.update:
            self.offer = get_object_or_404(ConditionalOffer, id=kwargs['pk'])
        if not self.is_previous_step_complete(request):
            messages.warning(
                request, _("%s step not complete") % (
                    self.previous_view.step_name.title(),))
            return HttpResponseRedirect(self.get_back_url())
        return super().dispatch(request, *args, **kwargs)

    # 上一步完成
    def is_previous_step_complete(self, request):
        if not self.previous_view:
            return True
        return self.previous_view.is_valid(self, request)

    def _key(self, step_name=None, is_object=False):
        key = step_name if step_name else self.step_name
        if self.update:
            key += str(self.offer.id)
        if is_object:
            key += '_obj'
        return key

    def _store_form_kwargs(self, form):
        session_data = self.request.session.setdefault(self.wizard_name, {})

        # Adjust kwargs to avoid trying to save the range instance
        # 调整KARGGS以避免尝试保存范围实例
        form_data = form.cleaned_data.copy()
        range = form_data.get('range', None)
        if range is not None:
            form_data['range_id'] = range.id
            del form_data['range']
        form_kwargs = {'data': form_data}
        json_data = json.dumps(form_kwargs, cls=DjangoJSONEncoder)

        session_data[self._key()] = json_data
        self.request.session.save()

    def _fetch_form_kwargs(self, step_name=None):
        if not step_name:
            step_name = self.step_name
        session_data = self.request.session.setdefault(self.wizard_name, {})
        json_data = session_data.get(self._key(step_name), None)
        if json_data:
            form_kwargs = json.loads(json_data)
            if 'range_id' in form_kwargs['data']:
                form_kwargs['data']['range'] = Range.objects.get(
                    id=form_kwargs['data']['range_id'])
                del form_kwargs['data']['range_id']
            return form_kwargs

        return {}

    def _store_object(self, form):
        session_data = self.request.session.setdefault(self.wizard_name, {})

        # We don't store the object instance as that is not JSON serialisable.
        # Instead, we save an alternative form
        # 我们不存储对象实例，因为它不是JSON可序列化的。
        # 相反，我们保存了另一种形式
        instance = form.save(commit=False)
        json_qs = serializers.serialize('json', [instance])

        session_data[self._key(is_object=True)] = json_qs
        self.request.session.save()

    def _fetch_object(self, step_name, request=None):
        if request is None:
            request = self.request
        session_data = request.session.setdefault(self.wizard_name, {})
        json_qs = session_data.get(self._key(step_name, is_object=True), None)
        if json_qs:
            # Recreate model instance from passed data
            # 从传递的数据重新创建模型实例
            deserialised_obj = list(serializers.deserialize('json', json_qs))
            return deserialised_obj[0].object

    def _fetch_session_offer(self):
        """
        Return the offer instance loaded with the data stored in the
        session.  When updating an offer, the updated fields are used with the
        existing offer data.
        返回加载了会话中存储的数据的商品实例。 更新商品时，更新的字段与现有商品数据一起使用。
        """
        offer = self._fetch_object('metadata')
        if offer is None and self.update:
            offer = self.offer
        return offer

    def _flush_session(self):
        self.request.session[self.wizard_name] = {}
        self.request.session.save()

    def get_form_kwargs(self, *args, **kwargs):
        form_kwargs = {}
        if self.update:
            form_kwargs['instance'] = self.get_instance()
        session_kwargs = self._fetch_form_kwargs()
        form_kwargs.update(session_kwargs)
        parent_kwargs = super().get_form_kwargs(
            *args, **kwargs)
        form_kwargs.update(parent_kwargs)
        return form_kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.update:
            ctx['offer'] = self.offer
        ctx['session_offer'] = self._fetch_session_offer()
        ctx['title'] = self.get_title()
        return ctx

    def get_back_url(self):
        if not self.previous_view:
            return None
        if self.update:
            return reverse(self.previous_view.url_name,
                           kwargs={'pk': self.kwargs['pk']})
        return reverse(self.previous_view.url_name)

    def get_title(self):
        return self.step_name.title()

    def form_valid(self, form):
        self._store_form_kwargs(form)
        self._store_object(form)

        if self.update and 'save' in form.data:
            # Save changes to this offer when updating and pressed save button
            # 更新并按下保存按钮时保存对此优惠的更改
            return self.save_offer(self.offer)
        else:
            # Proceed to next page
            # 继续下一页
            return super().form_valid(form)

    def save_offer(self, offer):
        # We update the offer with the name/description from step 1
        # 我们用步骤1的名称/描述更新报价。
        session_offer = self._fetch_session_offer()
        offer.name = session_offer.name
        offer.description = session_offer.description

        # Save the related models, then save the offer.
        # Note than you can save already on the first page of the wizard,
        # so le'ts check if the benefit and condition exist
        # 保存相关模型，然后保存报价。
        # 注意，您可以在向导的第一页上保存，所以让我们检查是否存在好处和条件
        benefit = self._fetch_object('benefit')
        if benefit:
            benefit.save()
            offer.benefit = benefit

        condition = self._fetch_object('condition')
        if condition:
            condition.save()
            offer.condition = condition

        offer.save()

        self._flush_session()

        if self.update:
            msg = _("Offer '%s' updated") % offer.name
        else:
            msg = _("Offer '%s' created!") % offer.name
        messages.success(self.request, msg)

        return HttpResponseRedirect(reverse(
            'dashboard:offer-detail', kwargs={'pk': offer.pk}))

    def get_success_url(self):
        if self.update:
            return reverse(self.success_url_name,
                           kwargs={'pk': self.kwargs['pk']})
        return reverse(self.success_url_name)

    @classmethod
    def is_valid(cls, current_view, request):
        if current_view.update:
            return True
        return current_view._fetch_object(cls.step_name, request) is not None


# 报价元数据视图
class OfferMetaDataView(OfferWizardStepView):
    step_name = 'metadata'
    form_class = MetaDataForm
    template_name = 'dashboard/offers/metadata_form.html'
    url_name = 'dashboard:offer-metadata'
    success_url_name = 'dashboard:offer-benefit'

    def get_instance(self):
        return self.offer

    def get_title(self):
        return _("Name and description")


# 报价优惠视图
class OfferBenefitView(OfferWizardStepView):
    step_name = 'benefit'
    form_class = BenefitForm
    template_name = 'dashboard/offers/benefit_form.html'
    url_name = 'dashboard:offer-benefit'
    success_url_name = 'dashboard:offer-condition'
    previous_view = OfferMetaDataView

    def get_instance(self):
        return self.offer.benefit

    def get_title(self):
        # This is referred to as the 'incentive' within the dashboard.
        # 这被称为仪表板中的“激励”。
        return _("Incentive")


# 报价条件视图
class OfferConditionView(OfferWizardStepView):
    step_name = 'condition'
    form_class = ConditionForm
    template_name = 'dashboard/offers/condition_form.html'
    url_name = 'dashboard:offer-condition'
    success_url_name = 'dashboard:offer-restrictions'
    previous_view = OfferBenefitView

    def get_instance(self):
        return self.offer.condition


# 报价限制视图
class OfferRestrictionsView(OfferWizardStepView):
    step_name = 'restrictions'
    form_class = RestrictionsForm
    template_name = 'dashboard/offers/restrictions_form.html'
    previous_view = OfferConditionView
    url_name = 'dashboard:offer-restrictions'

    def form_valid(self, form):
        offer = form.save(commit=False)
        return self.save_offer(offer)

    def get_instance(self):
        return self.offer

    def get_title(self):
        return _("Restrictions")


# 报价删除视图
class OfferDeleteView(DeleteView):
    model = ConditionalOffer
    template_name = 'dashboard/offers/offer_delete.html'
    context_object_name = 'offer'

    def get_success_url(self):
        messages.success(self.request, _("Offer deleted!"))
        return reverse('dashboard:offer-list')


# 报价详细视图
class OfferDetailView(ListView):
    # Slightly odd, but we treat the offer detail view as a list view so the
    # order discounts can be browsed.
    # 稍微奇怪一点，但是我们把报价细节视为列表视图，因此可以浏览订单折扣。
    model = OrderDiscount
    template_name = 'dashboard/offers/offer_detail.html'
    context_object_name = 'order_discounts'
    paginate_by = settings.OSCAR_DASHBOARD_ITEMS_PER_PAGE

    # 调度
    def dispatch(self, request, *args, **kwargs):
        self.offer = get_object_or_404(ConditionalOffer, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if 'suspend' in request.POST:
            return self.suspend()
        elif 'unsuspend' in request.POST:
            return self.unsuspend()

    # 暂停
    def suspend(self):
        if self.offer.is_suspended:
            messages.error(self.request, _("Offer is already suspended"))
        else:
            self.offer.suspend()
            messages.success(self.request, _("Offer suspended"))
        return HttpResponseRedirect(
            reverse('dashboard:offer-detail', kwargs={'pk': self.offer.pk}))

    # 取消暂停
    def unsuspend(self):
        if not self.offer.is_suspended:
            messages.error(
                self.request,
                _("Offer cannot be reinstated as it is not currently "
                  "suspended"))
        else:
            self.offer.unsuspend()
            messages.success(self.request, _("Offer reinstated"))
        return HttpResponseRedirect(
            reverse('dashboard:offer-detail', kwargs={'pk': self.offer.pk}))

    # 获取查询集
    def get_queryset(self):
        return self.model.objects.filter(offer_id=self.offer.pk) \
            .select_related('order')

    # 获取上下文数据
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['offer'] = self.offer
        return ctx

    # 渲染到响应
    def render_to_response(self, context):
        if self.request.GET.get('format') == 'csv':
            formatter = OrderDiscountCSVFormatter()
            return formatter.generate_response(context['order_discounts'],
                                               offer=self.offer)
        return super().render_to_response(context)
