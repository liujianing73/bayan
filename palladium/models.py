import datetime

from django.conf import settings
from django.db import models
from django.utils import timezone


class PlatingType(models.Model):
    """镀种"""
    name = models.CharField('镀种名称', max_length=50, unique=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = '镀种'
        verbose_name_plural = '镀种'

    def __str__(self):
        return self.name


class ChemicalSystem(models.Model):
    """项目药水系统"""
    name = models.CharField('药水系统名称', max_length=100, unique=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = '药水系统'
        verbose_name_plural = '药水系统'

    def __str__(self):
        return self.name


class ProductionLine(models.Model):
    """产线"""
    name = models.CharField('产线名称', max_length=50)
    line_no = models.CharField('产线编号', max_length=50, blank=True, default='')
    floor = models.CharField('车间楼层', max_length=20, blank=True, default='')
    plating_type = models.ForeignKey(
        PlatingType, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='lines', verbose_name='镀种',
    )
    is_active = models.BooleanField('是否启用', default=True)
    sort_order = models.IntegerField('排序', default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='production_lines', verbose_name='创建人',
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = '产线'
        verbose_name_plural = '产线'

    def __str__(self):
        if self.line_no:
            return f'{self.name}({self.line_no})'
        return self.name


class Slot(models.Model):
    """产线槽位"""
    line = models.ForeignKey(
        ProductionLine, on_delete=models.CASCADE,
        related_name='slots', verbose_name='产线',
    )
    sort_order = models.IntegerField('槽位顺序', default=0)
    slot_no = models.PositiveIntegerField('槽位编号', default=1)
    slot_type = models.CharField('槽位类型', max_length=50)
    name = models.CharField('槽位名称', max_length=100, blank=True, default='')
    chemical_system = models.ForeignKey(
        ChemicalSystem, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='slots', verbose_name='化学体系',
    )
    std_volume = models.CharField('标准体积(L)', max_length=50, blank=True, default='')
    std_concentration = models.CharField('标准浓度(g/L)', max_length=50, blank=True, default='')
    float_value = models.CharField('槽位浮动单元值', max_length=50, blank=True, default='')
    control_value = models.CharField('管控中心值', max_length=50, blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='slots', verbose_name='创建人',
    )

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = '槽位'
        verbose_name_plural = '槽位'
        unique_together = [('line', 'slot_no')]

    def __str__(self):
        return f'{self.line} - {self.name}'


class Customer(models.Model):
    """客户"""
    name = models.CharField('客户名称', max_length=100, unique=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = '客户'
        verbose_name_plural = '客户'

    def __str__(self):
        return self.name


class Product(models.Model):
    """产品料号"""
    part_no = models.CharField('料号', max_length=50, unique=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='products', verbose_name='客户',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='products', verbose_name='创建人',
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-id']
        verbose_name = '产品料号'
        verbose_name_plural = '产品料号'

    def __str__(self):
        return self.part_no


class ProductLineConfig(models.Model):
    """产品产线参数配置"""
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE,
        related_name='line_configs', verbose_name='产品',
    )
    line = models.ForeignKey(
        ProductionLine, on_delete=models.CASCADE,
        related_name='product_configs', verbose_name='产线',
    )
    std_gold_usage = models.CharField('标准钯用量(g/K)', max_length=50, blank=True, default='')
    std_capacity = models.CharField('标准产能(Kpcs/min)', max_length=50, blank=True, default='')

    class Meta:
        ordering = ['id']
        verbose_name = '产线参数配置'
        verbose_name_plural = '产线参数配置'

    def __str__(self):
        return f'{self.product} - {self.line}'


class StandardParamHistory(models.Model):
    """标准参数历史"""
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE,
        related_name='param_histories', verbose_name='料号',
    )
    effective_date = models.DateField('生效日期')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='创建人',
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-effective_date', '-id']
        verbose_name = '标准参数历史'
        verbose_name_plural = '标准参数历史'

    def __str__(self):
        return f'{self.product} @{self.effective_date}'


class StandardParamConfig(models.Model):
    """标准参数历史的产线配置"""
    history = models.ForeignKey(
        StandardParamHistory, on_delete=models.CASCADE,
        related_name='configs', verbose_name='参数历史',
    )
    line = models.ForeignKey(
        ProductionLine, on_delete=models.CASCADE,
        related_name='param_configs', verbose_name='产线',
    )
    std_gold_usage = models.CharField('标准钯用量(g/K)', max_length=50, blank=True, default='')
    std_capacity = models.CharField('标准产能(Kpcs/min)', max_length=50, blank=True, default='')

    class Meta:
        ordering = ['id']
        verbose_name = '标准参数配置'
        verbose_name_plural = '标准参数配置'

    def __str__(self):
        return f'{self.history} - {self.line}'


class ShiftEntry(models.Model):
    """产线班次录入记录（早班/晚班）"""
    SHIFT_DAY = 'day'
    SHIFT_NIGHT = 'night'
    SHIFT_CHOICES = [
        (SHIFT_DAY, '早班'),
        (SHIFT_NIGHT, '晚班'),
    ]

    line = models.ForeignKey(
        ProductionLine, on_delete=models.CASCADE,
        related_name='entries', verbose_name='产线',
    )
    date = models.DateField('日期')
    shift = models.CharField('班次', max_length=10, choices=SHIFT_CHOICES)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='录入人',
    )
    entered_at = models.DateTimeField('录入时间', default=timezone.now)
    remark = models.TextField('备注', blank=True, default='')

    class Meta:
        unique_together = [('line', 'date', 'shift')]
        verbose_name = '班次录入记录'
        verbose_name_plural = '班次录入记录'

    def __str__(self):
        return f'{self.line} {self.date} {self.get_shift_display()}'


class DailyReport(models.Model):
    """生产日报"""
    line = models.ForeignKey(
        ProductionLine, on_delete=models.CASCADE,
        related_name='daily_reports', verbose_name='产线',
    )
    sample_date = models.DateField('取样日期')
    sample_time = models.TimeField('取样时间', default=datetime.time(8, 0))
    line_leader = models.CharField('线长', max_length=50, blank=True, default='')
    ipqc = models.CharField('IPQC', max_length=50, blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='daily_reports', verbose_name='输入人员',
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-sample_date', 'line_id']
        verbose_name = '生产日报'
        verbose_name_plural = '生产日报'

    def __str__(self):
        return f'{self.line} {self.sample_date} {self.sample_time}'


class ReportSlotData(models.Model):
    """生产日报槽位数据（浓度/液位）"""
    report = models.ForeignKey(
        DailyReport, on_delete=models.CASCADE,
        related_name='slot_data', verbose_name='日报',
    )
    slot_no = models.IntegerField('槽位')
    slot_type = models.CharField('类型', max_length=50, blank=True, default='')
    concentration = models.CharField('浓度', max_length=50, blank=True, default='')
    liquid_level = models.CharField('液位', max_length=50, blank=True, default='')
    status = models.CharField('状态', max_length=50, blank=True, default='无')

    class Meta:
        ordering = ['slot_no']
        verbose_name = '日报槽位数据'
        verbose_name_plural = '日报槽位数据'


class ReportDetail(models.Model):
    """生产日报生产明细（工时段）"""
    report = models.ForeignKey(
        DailyReport, on_delete=models.CASCADE,
        related_name='details', verbose_name='日报',
    )
    start_time = models.TimeField('开始时间')
    end_time = models.TimeField('结束时间')
    category = models.CharField('类别', max_length=50)
    part_no = models.CharField('料号', max_length=50, blank=True, default='')
    quantity = models.CharField('数量', max_length=50, blank=True, default='')

    class Meta:
        ordering = ['start_time', 'id']
        verbose_name = '生产明细'
        verbose_name_plural = '生产明细'


class ConcentrationRecord(models.Model):
    """浓度数据记录（按产线+取样批次）"""
    line = models.ForeignKey(
        ProductionLine, on_delete=models.CASCADE,
        related_name='concentration_records', verbose_name='产线',
    )
    sample_date = models.DateField('取样日期')
    sample_time = models.TimeField('取样时间', default=datetime.time(8, 0))
    line_leader = models.CharField('线长', max_length=50, blank=True, default='')
    ipqc = models.CharField('IPQC', max_length=50, blank=True, default='')
    analyst = models.CharField('分析员', max_length=50, blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='concentration_records', verbose_name='输入人员',
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-sample_date', 'line_id']
        verbose_name = '浓度数据记录'
        verbose_name_plural = '浓度数据记录'

    def __str__(self):
        return f'{self.line} {self.sample_date} {self.sample_time}'


class ConcentrationSlot(models.Model):
    """浓度数据记录的槽位测量行"""
    record = models.ForeignKey(
        ConcentrationRecord, on_delete=models.CASCADE,
        related_name='slot_rows', verbose_name='浓度记录',
    )
    slot_no = models.IntegerField('槽位编号')
    slot_type = models.CharField('槽位类型', max_length=50, blank=True, default='')
    slot_name = models.CharField('槽位名称/类型', max_length=100, blank=True, default='')
    chemical = models.CharField('化学体系', max_length=100, blank=True, default='')
    open_status = models.CharField('槽位开缸状态', max_length=20, blank=True, default='无')
    test_status = models.CharField('浓度检测状态', max_length=20, blank=True, default='未检测')
    concentration = models.CharField('浓度(g/L)', max_length=50, blank=True, default='0')
    grass_type = models.CharField('草头类型', max_length=50, blank=True, default='')
    liquid_level = models.CharField('液位(cm)', max_length=50, blank=True, default='0')
    liters = models.CharField('升数(L)', max_length=50, blank=True, default='')
    gold_salt = models.CharField('金盐添加量(g)', max_length=50, blank=True, default='')

    class Meta:
        ordering = ['slot_no', 'id']
        verbose_name = '浓度槽位数据'
        verbose_name_plural = '浓度槽位数据'


class OperationLog(models.Model):
    """最近操作记录"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='操作人',
    )
    action = models.CharField('操作内容', max_length=255)
    created_at = models.DateTimeField('操作时间', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '操作记录'
        verbose_name_plural = '操作记录'

    def __str__(self):
        return self.action
