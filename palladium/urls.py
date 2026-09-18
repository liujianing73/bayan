from django.urls import path

from . import views

app_name = 'palladium'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('line/new/', views.line_create, name='line_create'),
    path('part/new/', views.part_create, name='part_create'),
    path('param/new/', views.param_create, name='param_create'),
    path('products/', views.product_list, name='product_list'),
    path('lines/', views.line_list, name='line_list'),
    path('lines/<int:pk>/edit/', views.line_edit, name='line_edit'),
    path('lines/<int:pk>/delete/', views.line_delete, name='line_delete'),
    path('lines/<int:pk>/slots/clear/', views.line_slots_clear, name='line_slots_clear'),
    path('lines/<int:pk>/slots/add/', views.slot_add, name='slot_add'),
    path('lines/<int:pk>/slots/<int:slot_pk>/edit/', views.slot_edit, name='slot_edit'),
    path('reports/', views.report_list, name='report_list'),
    path('reports/<int:pk>/edit/', views.report_edit, name='report_edit'),
    path('reports/<int:pk>/delete/', views.report_delete, name='report_delete'),
    path('reports/bulk-delete/', views.report_bulk_delete, name='report_bulk_delete'),
    path('concentrations/', views.concentration_list, name='concentration_list'),
    path('concentrations/bulk-delete/', views.concentration_bulk_delete, name='concentration_bulk_delete'),
    path('concentrations/<int:pk>/edit/', views.concentration_edit, name='concentration_edit'),
    path('concentrations/<int:pk>/slots/clear/', views.concentration_slots_clear, name='concentration_slots_clear'),
    path('concentrations/slots/<int:pk>/delete/', views.concentration_slot_delete, name='concentration_slot_delete'),
    path('param-history/', views.param_history_list, name='param_history_list'),
    path('param-history/<int:pk>/delete/', views.param_history_delete, name='param_history_delete'),
    path('name-diagnosis/', views.name_diagnosis, name='name_diagnosis'),
    path('products/<int:pk>/edit/', views.product_edit, name='product_edit'),
    path('products/<int:pk>/delete/', views.product_delete, name='product_delete'),
    path('api/plating-type/add/', views.api_plating_type_add, name='api_plating_type_add'),
    path('api/chemical-system/add/', views.api_chemical_system_add, name='api_chemical_system_add'),
    path('page/<path:title>/', views.placeholder, name='placeholder'),
]
