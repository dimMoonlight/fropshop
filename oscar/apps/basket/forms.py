from django import forms
from django.conf import settings
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from oscar.core.loading import get_model
from oscar.forms import widgets

Line = get_model('basket', 'line')
Basket = get_model('basket', 'basket')
Product = get_model('catalogue', 'product')


# 购物篮行 格式
class BasketLineForm(forms.ModelForm):
    save_for_later = forms.BooleanField(
        initial=False, required=False, label=_('Save for Later'))

    def __init__(self, strategy, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.strategy = strategy

        max_allowed_quantity = None
        num_available = getattr(self.instance.purchase_info.availability, 'num_available', None)
        basket_max_allowed_quantity = self.instance.basket.max_allowed_quantity()[0]
        if all([num_available, basket_max_allowed_quantity]):
            max_allowed_quantity = min(num_available, basket_max_allowed_quantity)
        else:
            max_allowed_quantity = num_available or basket_max_allowed_quantity
        if max_allowed_quantity:
            self.fields['quantity'].widget.attrs['max'] = max_allowed_quantity

    def clean_quantity(self):   # 清空
        qty = self.cleaned_data['quantity']
        if qty > 0:
            self.check_max_allowed_quantity(qty)
            self.check_permission(qty)
        return qty

    def check_max_allowed_quantity(self, qty):    # 校验最大允许量
        # Since `Basket.is_quantity_allowed` checks quantity of added product
        # against total number of the products in the basket, instead of sending
        # updated quantity of the product, we send difference between current
        # number and updated. Thus, product already in the basket and we don't
        # add second time, just updating number of items.
        # 由于“Basket.is_quantity_allowed”检查增加的产品数量相对于购物篮中的产品总数，
        # 而不是发送更新的产品数量，我们发送当前号码和更新之间的差额。因此，
        # 产品已经在购物篮里，我们不添加第二次，只是更新项目的数量。
        qty_delta = qty - self.instance.quantity
        is_allowed, reason = self.instance.basket.is_quantity_allowed(qty_delta)
        if not is_allowed:
            raise forms.ValidationError(reason)

    # 检查权限
    def check_permission(self, qty):
        policy = self.instance.purchase_info.availability
        is_available, reason = policy.is_purchase_permitted(
            quantity=qty)
        if not is_available:
            raise forms.ValidationError(reason)

    class Meta:
        model = Line
        fields = ['quantity']


# 保存 行的格式
class SavedLineForm(forms.ModelForm):
    move_to_basket = forms.BooleanField(initial=False, required=False,
                                        label=_('Move to Basket'))

    class Meta:
        model = Line
        fields = ('id', 'move_to_basket')

    def __init__(self, strategy, basket, *args, **kwargs):
        self.strategy = strategy
        self.basket = basket
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data['move_to_basket']:
            # skip further validation (see issue #666)
            # 跳过进一步验证（见第666页）
            return cleaned_data

        # Get total quantity of all lines with this product (there's normally
        # only one but there can be more if you allow product options).
        # 用这个产品得到所有产品的总数量（通常只有一个，
        # 但是如果你允许产品选择，就可以有更多的产品）。
        lines = self.basket.lines.filter(product=self.instance.product)
        current_qty = lines.aggregate(Sum('quantity'))['quantity__sum'] or 0
        desired_qty = current_qty + self.instance.quantity

        result = self.strategy.fetch_for_product(self.instance.product)
        is_available, reason = result.availability.is_purchase_permitted(
            quantity=desired_qty)
        if not is_available:
            raise forms.ValidationError(reason)
        return cleaned_data


# 购物篮优惠券 格式
class BasketVoucherForm(forms.Form):
    code = forms.CharField(max_length=128, label=_('Code'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean_code(self):
        return self.cleaned_data['code'].strip().upper()


# 添加到购物篮的 格式
class AddToBasketForm(forms.Form):
    quantity = forms.IntegerField(initial=1, min_value=1, label=_('Quantity'))

    def __init__(self, basket, product, *args, **kwargs):
        # Note, the product passed in here isn't necessarily the product being
        # added to the basket. For child products, it is the *parent* product
        # that gets passed to the form. An optional product_id param is passed
        # to indicate the ID of the child product being added to the basket.

        # 注意，这里传递的产品不一定是添加到篮子里的产品。对于子产品，它是
        # 传递给表单的起源产品。传递一个可选的产品id
        # id参数来指示添加到篮子中的子产品的ID。
        self.basket = basket
        self.parent_product = product

        super().__init__(*args, **kwargs)

        # Dynamically build fields
        # 动态构建字段
        if product.is_parent:
            self._create_parent_product_fields(product)
        self._create_product_fields(product)

    # Dynamic form building methods
    # 动态模板构建方法

    # 创建父产品字段
    def _create_parent_product_fields(self, product):
        """
        Adds the fields for a "group"-type product (eg, a parent product with a
        list of children.

        Currently requires that a stock record exists for the children

        为“组”类型的产品添加字段（例如，带有子列表的父产品）。
        目前需要为子产品提供库存记录。
        """
        choices = []
        disabled_values = []
        for child in product.children.all():
            # Build a description of the child, including any pertinent
            # attributes
            # 建立对子产品的描述，包括任何相关的
            attr_summary = child.attribute_summary
            if attr_summary:
                summary = attr_summary
            else:
                summary = child.get_title()

            # Check if it is available to buy
            # 检查是否可以购买
            info = self.basket.strategy.fetch_for_product(child)
            if not info.availability.is_available_to_buy:
                disabled_values.append(child.id)

            choices.append((child.id, summary))

        self.fields['child_id'] = forms.ChoiceField(
            choices=tuple(choices), label=_("Variant"),
            widget=widgets.AdvancedSelect(disabled_values=disabled_values))

    # 创建产品字段
    def _create_product_fields(self, product):
        """
        Add the product option fields.
        添加产品选项字段
        """
        for option in product.options:
            self._add_option_field(product, option)

    def _add_option_field(self, product, option):       # 添加选项字段
        """
        Creates the appropriate form field for the product option.

        This is designed to be overridden so that specific widgets can be used
        for certain types of options.

        为产品选项创建适当的表单字段。
        这被设计为重写，以便特定的小部件可以用于某些类型的选项。
        """
        self.fields[option.code] = forms.CharField(
            label=option.name, required=option.is_required)

    # Cleaning 清除

    def clean_child_id(self):
        try:
            child = self.parent_product.children.get(
                id=self.cleaned_data['child_id'])
        except Product.DoesNotExist:
            raise forms.ValidationError(
                _("Please select a valid product"))

        # To avoid duplicate SQL queries, we cache a copy of the loaded child
        # product as we're going to need it later.
        # 为了避免重复的SQL查询，我们将缓存已加载的子产品的副本，因为稍后我们将需要它。

        self.child_product = child

        return self.cleaned_data['child_id']

    def clean_quantity(self):
        # Check that the proposed new line quantity is sensible
        # 检查建议的新品行数量是否合理
        qty = self.cleaned_data['quantity']
        basket_threshold = settings.OSCAR_MAX_BASKET_QUANTITY_THRESHOLD
        if basket_threshold:
            total_basket_quantity = self.basket.num_items
            max_allowed = basket_threshold - total_basket_quantity
            if qty > max_allowed:
                raise forms.ValidationError(
                    _("Due to technical limitations we are not able to ship"
                      " more than %(threshold)d items in one order. Your"
                      " basket currently has %(basket)d items.")
                    % {'threshold': basket_threshold,
                       'basket': total_basket_quantity})
        return qty

    @property
    def product(self):   # 产品
        """
        The actual product being added to the basket
        实际产品被添加到购物篮里
        """
        # Note, the child product attribute is saved in the clean_child_id
        # method
        # 注意，子产品属性保存在clean_child_id方法中。
        return getattr(self, 'child_product', self.parent_product)

    def clean(self):
        info = self.basket.strategy.fetch_for_product(self.product)

        # Check that a price was found by the strategy
        # 检查策略是否找到了价格
        if not info.price.exists:
            raise forms.ValidationError(
                _("This product cannot be added to the basket because a "
                  "price could not be determined for it."))

        # Check currencies are sensible
        # 支票货币是明智的
        if (self.basket.currency and
                info.price.currency != self.basket.currency):
            raise forms.ValidationError(
                _("This product cannot be added to the basket as its currency "
                  "isn't the same as other products in your basket"))

        # Check user has permission to add the desired quantity to their
        # basket.
        # 检查用户是否有权将期望的数量添加到他们的购物篮中
        current_qty = self.basket.product_quantity(self.product)
        desired_qty = current_qty + self.cleaned_data.get('quantity', 1)
        is_permitted, reason = info.availability.is_purchase_permitted(
            desired_qty)
        if not is_permitted:
            raise forms.ValidationError(reason)

        return self.cleaned_data

    # Helpers 助手

    def cleaned_options(self):  # 清除选项
        """
        Return submitted options in a clean format
        以清除格式返回提交的选项
        """
        options = []
        for option in self.parent_product.options:
            if option.code in self.cleaned_data:
                options.append({
                    'option': option,
                    'value': self.cleaned_data[option.code]})
        return options


# 简单增加到购物篮的格式
class SimpleAddToBasketForm(AddToBasketForm):
    """
    Simplified version of the add to basket form where the quantity is
    defaulted to 1 and rendered in a hidden widget

    Most of the time, you won't need to override this class. Just change
    AddToBasketForm to change behaviour in both forms at once.

    “添加到购物篮”窗体的简化版本，其中数量默认为 1 并呈现在隐藏控件中。
    大多数时候，你不需要重写这个类。只需要立即改变AddToBasketForm 形式 。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'quantity' in self.fields:
            self.fields['quantity'].initial = 1
            self.fields['quantity'].widget = forms.HiddenInput()
