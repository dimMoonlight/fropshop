from django import forms
from django.core import exceptions
from django.utils.translation import gettext_lazy as _
from treebeard.forms import movenodeform_factory

from oscar.core.loading import get_class, get_model
from oscar.core.utils import slugify
from oscar.forms.widgets import DateTimePickerInput, ImageInput

Product = get_model('catalogue', 'Product')
ProductClass = get_model('catalogue', 'ProductClass')
ProductAttribute = get_model('catalogue', 'ProductAttribute')
Category = get_model('catalogue', 'Category')
StockRecord = get_model('partner', 'StockRecord')
ProductCategory = get_model('catalogue', 'ProductCategory')
ProductImage = get_model('catalogue', 'ProductImage')
ProductRecommendation = get_model('catalogue', 'ProductRecommendation')
AttributeOptionGroup = get_model('catalogue', 'AttributeOptionGroup')
AttributeOption = get_model('catalogue', 'AttributeOption')
ProductSelect = get_class('dashboard.catalogue.widgets', 'ProductSelect')
RelatedFieldWidgetWrapper = get_class('dashboard.widgets',
                                      'RelatedFieldWidgetWrapper')

CategoryForm = movenodeform_factory(
    Category,
    fields=['name', 'description', 'image'])


# 产品类别选择表格
class ProductClassSelectForm(forms.Form):
    """
    Form which is used before creating a product to select it's product class
    在创建产品之前使用的表单，用于选择产品类别
    """

    product_class = forms.ModelChoiceField(
        label=_("Create a new product of type"),
        empty_label=_("-- Choose type --"),
        queryset=ProductClass.objects.all())

    def __init__(self, *args, **kwargs):
        """
        If there's only one product class, pre-select it
        如果只有一个产品类，请预先选择它
        """
        super().__init__(*args, **kwargs)
        qs = self.fields['product_class'].queryset
        if not kwargs.get('initial') and len(qs) == 1:
            self.fields['product_class'].initial = qs[0]


# 产品搜索表格
class ProductSearchForm(forms.Form):
    upc = forms.CharField(max_length=16, required=False, label=_('UPC'))
    title = forms.CharField(
        max_length=255, required=False, label=_('Product title'))

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data['upc'] = cleaned_data['upc'].strip()
        cleaned_data['title'] = cleaned_data['title'].strip()
        return cleaned_data


# 凭证记录表格
class StockRecordForm(forms.ModelForm):

    def __init__(self, product_class, user, *args, **kwargs):
        # The user kwarg is not used by stock StockRecordForm. We pass it
        # anyway in case one wishes to customise the partner queryset
        # StockRecordForm库存不使用用户kwarg。 我们无论如何都要传递它，以防一
        # 个人想要自定义伙伴查询集
        self.user = user
        super().__init__(*args, **kwargs)

        # Restrict accessible partners for non-staff users
        # 限制非员工用户的可访问合作伙伴
        if not self.user.is_staff:
            self.fields['partner'].queryset = self.user.partners.all()

        # If not tracking stock, we hide the fields
        # 如果不跟踪库存，我们会隐藏字段
        if not product_class.track_stock:
            for field_name in ['num_in_stock', 'low_stock_treshold']:
                if field_name in self.fields:
                    del self.fields[field_name]
        else:
            for field_name in ['price_excl_tax', 'num_in_stock']:
                if field_name in self.fields:
                    self.fields[field_name].required = True

    class Meta:
        model = StockRecord
        fields = [
            'partner', 'partner_sku',
            'price_currency', 'price_excl_tax', 'price_retail', 'cost_price',
            'num_in_stock', 'low_stock_threshold',
        ]


def _attr_text_field(attribute):
    return forms.CharField(label=attribute.name,
                           required=attribute.required)


def _attr_textarea_field(attribute):
    return forms.CharField(label=attribute.name,
                           widget=forms.Textarea(),
                           required=attribute.required)


def _attr_integer_field(attribute):
    return forms.IntegerField(label=attribute.name,
                              required=attribute.required)


def _attr_boolean_field(attribute):
    return forms.BooleanField(label=attribute.name,
                              required=attribute.required)


def _attr_float_field(attribute):
    return forms.FloatField(label=attribute.name,
                            required=attribute.required)


def _attr_date_field(attribute):
    return forms.DateField(label=attribute.name,
                           required=attribute.required,
                           widget=forms.widgets.DateInput)


def _attr_datetime_field(attribute):
    return forms.DateTimeField(label=attribute.name,
                               required=attribute.required,
                               widget=DateTimePickerInput())


def _attr_option_field(attribute):
    return forms.ModelChoiceField(
        label=attribute.name,
        required=attribute.required,
        queryset=attribute.option_group.options.all())


def _attr_multi_option_field(attribute):
    return forms.ModelMultipleChoiceField(
        label=attribute.name,
        required=attribute.required,
        queryset=attribute.option_group.options.all())


def _attr_entity_field(attribute):
    # Product entities don't have out-of-the-box supported in the ProductForm.
    # There is no ModelChoiceField for generic foreign keys, and there's no
    # good default behaviour anyway; offering a choice of *all* model instances
    # is hardly useful.
    # 产品实体在ProductForm中不支持开箱即用。 普通外键没有ModelChoiceField，无论
    # 如何都没有好的默认行为; 提供* all * model实例的选择几乎没有用。
    return None


def _attr_numeric_field(attribute):
    return forms.FloatField(label=attribute.name,
                            required=attribute.required)


def _attr_file_field(attribute):
    return forms.FileField(
        label=attribute.name, required=attribute.required)


def _attr_image_field(attribute):
    return forms.ImageField(
        label=attribute.name, required=attribute.required)


# 产品表格
class ProductForm(forms.ModelForm):
    FIELD_FACTORIES = {
        "text": _attr_text_field,
        "richtext": _attr_textarea_field,
        "integer": _attr_integer_field,
        "boolean": _attr_boolean_field,
        "float": _attr_float_field,
        "date": _attr_date_field,
        "datetime": _attr_datetime_field,
        "option": _attr_option_field,
        "multi_option": _attr_multi_option_field,
        "entity": _attr_entity_field,
        "numeric": _attr_numeric_field,
        "file": _attr_file_field,
        "image": _attr_image_field,
    }

    class Meta:
        model = Product
        fields = [
            'title', 'upc', 'description', 'is_discountable', 'structure']
        widgets = {
            'structure': forms.HiddenInput()
        }

    def __init__(self, product_class, data=None, parent=None, *args, **kwargs):
        self.set_initial(product_class, parent, kwargs)
        super().__init__(data, *args, **kwargs)
        if parent:
            self.instance.parent = parent
            # We need to set the correct product structures explicitly to pass
            # attribute validation and child product validation. Note that
            # those changes are not persisted.
            # 我们需要明确设置正确的产品结构以传递属性验证和子产品验证。 请注意，这些更改不会保留。
            self.instance.structure = Product.CHILD
            self.instance.parent.structure = Product.PARENT

            self.delete_non_child_fields()
        else:
            # Only set product class for non-child products
            # 仅为非子产品设置产品类别
            self.instance.product_class = product_class
        self.add_attribute_fields(product_class, self.instance.is_parent)

        if 'title' in self.fields:
            self.fields['title'].widget = forms.TextInput(
                attrs={'autocomplete': 'off'})

    # 设置初始
    def set_initial(self, product_class, parent, kwargs):
        """
        Set initial data for the form. Sets the correct product structure
        and fetches initial values for the dynamically constructed attribute
        fields.
        设置表单的初始数据。 设置正确的产品结构并获取动态构造的属性字段的初始值。
        """
        if 'initial' not in kwargs:
            kwargs['initial'] = {}
        self.set_initial_attribute_values(product_class, kwargs)
        if parent:
            kwargs['initial']['structure'] = Product.CHILD

    # 设置初始属性值
    def set_initial_attribute_values(self, product_class, kwargs):
        """
        Update the kwargs['initial'] value to have the initial values based on
        the product instance's attributes
        更新kwargs ['initial']值以根据产品实例的属性获得初始值
        """
        instance = kwargs.get('instance')
        if instance is None:
            return
        for attribute in product_class.attributes.all():
            try:
                value = instance.attribute_values.get(
                    attribute=attribute).value
            except exceptions.ObjectDoesNotExist:
                pass
            else:
                kwargs['initial']['attr_%s' % attribute.code] = value

    # 添加属性字段
    def add_attribute_fields(self, product_class, is_parent=False):
        """
        For each attribute specified by the product class, this method
        dynamically adds form fields to the product form.
        对于产品类指定的每个属性，此方法会动态地将表单字段添加到产品表单中。
        """
        for attribute in product_class.attributes.all():
            field = self.get_attribute_field(attribute)
            if field:
                self.fields['attr_%s' % attribute.code] = field
                # Attributes are not required for a parent product
                # 父产品不需要属性
                if is_parent:
                    self.fields['attr_%s' % attribute.code].required = False

    # 获取属性字段
    def get_attribute_field(self, attribute):
        """
        Gets the correct form field for a given attribute type.
        获取给定属性类型的正确表单字段。
        """
        return self.FIELD_FACTORIES[attribute.type](attribute)

    # 删除非子字段
    def delete_non_child_fields(self):
        """
        Deletes any fields not needed for child products. Override this if
        you want to e.g. keep the description field.
        删除子产品不需要的任何字段。 如果你想要覆盖这个，请覆盖它 保留描述字段。
        """
        for field_name in ['description', 'is_discountable']:
            if field_name in self.fields:
                del self.fields[field_name]

    def _post_clean(self):
        """
        Set attributes before ModelForm calls the product's clean method
        (which it does in _post_clean), which in turn validates attributes.
        在ModelForm调用产品的clean方法（它在_post_clean中）之前设置属性，这反过来验证属性。
        """
        self.instance.attr.initiate_attributes()
        for attribute in self.instance.attr.get_all_attributes():
            field_name = 'attr_%s' % attribute.code
            # An empty text field won't show up in cleaned_data.
            # 空文本字段不会显示在cleaning_data中。
            if field_name in self.cleaned_data:
                value = self.cleaned_data[field_name]
                setattr(self.instance.attr, attribute.code, value)
        super()._post_clean()


# 凭证提示搜索表格
class StockAlertSearchForm(forms.Form):
    status = forms.CharField(label=_('Status'))


# 产品类别表格
class ProductCategoryForm(forms.ModelForm):

    class Meta:
        model = ProductCategory
        fields = ('category', )


# 产品图像表格
class ProductImageForm(forms.ModelForm):

    class Meta:
        model = ProductImage
        fields = ['product', 'original', 'caption']
        # use ImageInput widget to create HTML displaying the
        # actual uploaded image and providing the upload dialog
        # when clicking on the actual image.
        # 使用ImageInput小部件创建HTML，显示实际上传的图像，并在单击实际图像时提供上载对话框。
        widgets = {
            'original': ImageInput(),
        }

    def save(self, *args, **kwargs):
        # We infer the display order of the image based on the order of the
        # image fields within the formset.
        # 我们基于formset中的图像字段的顺序推断图像的显示顺序。
        kwargs['commit'] = False
        obj = super().save(*args, **kwargs)
        obj.display_order = self.get_display_order()
        obj.save()
        return obj

    def get_display_order(self):
        return self.prefix.split('-').pop()


# 产品推荐表格
class ProductRecommendationForm(forms.ModelForm):

    class Meta:
        model = ProductRecommendation
        fields = ['primary', 'recommendation', 'ranking']
        widgets = {
            'recommendation': ProductSelect,
        }


# 产品类别
class ProductClassForm(forms.ModelForm):

    class Meta:
        model = ProductClass
        fields = ['name', 'requires_shipping', 'track_stock', 'options']


# 产品属性表
class ProductAttributesForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # because we'll allow submission of the form with blank
        # codes so that we can generate them.
        # 因为我们允许提交带有空白代码的表单，以便我们可以生成它们。
        self.fields["code"].required = False

        self.fields["option_group"].help_text = _("Select an option group")

        remote_field = self._meta.model._meta.get_field('option_group').remote_field
        self.fields["option_group"].widget = RelatedFieldWidgetWrapper(
            self.fields["option_group"].widget, remote_field)

    def clean_code(self):
        code = self.cleaned_data.get("code")
        title = self.cleaned_data.get("name")

        if not code and title:
            code = slugify(title)

        return code

    class Meta:
        model = ProductAttribute
        fields = ["name", "code", "type", "option_group", "required"]


# 属性选项组表单
class AttributeOptionGroupForm(forms.ModelForm):

    class Meta:
        model = AttributeOptionGroup
        fields = ['name']


# 属性选项表单
class AttributeOptionForm(forms.ModelForm):

    class Meta:
        model = AttributeOption
        fields = ['option']
