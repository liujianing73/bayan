from django.contrib import admin

from .models import (
    ChemicalSystem,
    Customer,
    OperationLog,
    PlatingType,
    Product,
    ProductLineConfig,
    ProductionLine,
    ShiftEntry,
    Slot,
    StandardParamConfig,
    StandardParamHistory,
)


@admin.register(ProductionLine)
class ProductionLineAdmin(admin.ModelAdmin):
    list_display = ['name', 'line_no', 'floor', 'plating_type', 'is_active', 'sort_order', 'created_by']
    list_filter = ['is_active', 'floor']
    search_fields = ['name', 'line_no']


@admin.register(Slot)
class SlotAdmin(admin.ModelAdmin):
    list_display = ['line', 'slot_no', 'slot_type', 'name', 'chemical_system',
                    'std_volume', 'std_concentration', 'float_value']
    list_filter = ['slot_type']


@admin.register(PlatingType)
class PlatingTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at']


@admin.register(ChemicalSystem)
class ChemicalSystemAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['part_no', 'customer', 'created_by', 'created_at']
    search_fields = ['part_no']


@admin.register(ProductLineConfig)
class ProductLineConfigAdmin(admin.ModelAdmin):
    list_display = ['product', 'line', 'std_gold_usage', 'std_capacity']


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at']


@admin.register(StandardParamHistory)
class StandardParamHistoryAdmin(admin.ModelAdmin):
    list_display = ['product', 'effective_date', 'created_by', 'created_at']
    list_filter = ['effective_date']


@admin.register(StandardParamConfig)
class StandardParamConfigAdmin(admin.ModelAdmin):
    list_display = ['history', 'line', 'std_gold_usage', 'std_capacity']


@admin.register(ShiftEntry)
class ShiftEntryAdmin(admin.ModelAdmin):
    list_display = ['line', 'date', 'shift', 'entered_by', 'entered_at']
    list_filter = ['shift', 'date']


@admin.register(OperationLog)
class OperationLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'action', 'created_at']
