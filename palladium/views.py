import csv
import datetime
import json

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    ChemicalSystem,
    ConcentrationRecord,
    ConcentrationSlot,
    Customer,
    DailyReport,
    OperationLog,
    PlatingType,
    Product,
    ProductLineConfig,
    ProductionLine,
    ReportDetail,
    ShiftEntry,
    Slot,
    StandardParamConfig,
    StandardParamHistory,
)

DETAIL_CATEGORIES = ['无效工时', '有效工时', '待料', '停机', '换线', '其他']
OPEN_STATUS = ['无', '开缸', '补缸']
TEST_STATUS = ['未检测', '检测']
GRASS_TYPES = ['罩头1', '罩头2', '罩头3']
CONC_SLOT_TYPES = ['镀钯', '镀镍']

FLOORS = ['车间1楼', '车间2楼', '车间3楼']

SLOT_TYPES = ['选金', '点镀', '镀钯']


def dashboard(request):
    """系统首页：最近操作记录 / 产线录入状态 / 浓度输入区块 + 快捷入口"""
    date = _parse_date(request.GET.get('date'), timezone.localdate())
    search = request.GET.get('q', '').strip()

    lines = ProductionLine.objects.filter(is_active=True)
    if search:
        lines = lines.filter(name__icontains=search)

    entries = ShiftEntry.objects.filter(date=date)
    entry_map = {(e.line_id, e.shift): e for e in entries}

    line_cards = [
        {
            'line': line,
            'day': entry_map.get((line.id, ShiftEntry.SHIFT_DAY)),
            'night': entry_map.get((line.id, ShiftEntry.SHIFT_NIGHT)),
        }
        for line in lines
    ]

    since = timezone.now() - datetime.timedelta(hours=24)
    logs = OperationLog.objects.filter(created_at__gte=since)[:50]

    context = {
        'page_title': '首页',
        'date': date,
        'search': search,
        'line_cards': line_cards,
        'logs': logs,
    }
    return render(request, 'palladium/dashboard.html', context)


def line_create(request):
    """定义新产线：槽位基本资料定义"""
    plating_types = PlatingType.objects.all()
    chemical_systems = ChemicalSystem.objects.all()

    if request.method == 'POST':
        floor = (request.POST.get('floor') or '').strip()
        name = (request.POST.get('name') or '').strip()
        plating_id = (request.POST.get('plating_type') or '').strip()

        slot_types = request.POST.getlist('slot_type')
        slot_names = request.POST.getlist('slot_name')
        chem_ids = request.POST.getlist('chem_system')
        vols = request.POST.getlist('std_volume')
        floats = request.POST.getlist('float_value')
        ctrls = request.POST.getlist('control_value')

        errors = []
        if not floor:
            errors.append('请选择车间楼层')
        if not name:
            errors.append('请输入产线名称')
        n = len(slot_types)
        if any(len(lst) != n for lst in (slot_names, chem_ids, vols, floats, ctrls)):
            errors.append('槽位数据不完整，请重新编辑')
        for i in range(n):
            if not slot_types[i].strip():
                errors.append(f'槽位{i + 1}：请选择槽位类型')
            if not slot_names[i].strip():
                errors.append(f'槽位{i + 1}：请输入槽位名称')
            if not chem_ids[i].strip() or chem_ids[i] == '__other__':
                errors.append(f'槽位{i + 1}：请选择项目药水系统')

        if errors:
            for msg in errors:
                messages.error(request, msg)
        else:
            plating = PlatingType.objects.filter(id=plating_id).first()
            line = ProductionLine.objects.create(
                name=name, floor=floor, plating_type=plating,
            )
            for i in range(n):
                chem = ChemicalSystem.objects.filter(id=chem_ids[i]).first()
                Slot.objects.create(
                    line=line, sort_order=i + 1, slot_no=i + 1,
                    slot_type=slot_types[i].strip(),
                    name=slot_names[i].strip(),
                    chemical_system=chem,
                    std_volume=vols[i].strip(),
                    float_value=floats[i].strip(),
                    control_value=ctrls[i].strip(),
                )
            user = request.user if request.user.is_authenticated else None
            OperationLog.objects.create(
                user=user,
                action=f'定义新产线：{name}（{floor}，{n}个槽位）',
            )
            messages.success(request, f'产线「{name}」创建成功，共 {n} 个槽位')
            return redirect('palladium:dashboard')

    context = {
        'page_title': '定义新产线',
        'floors': FLOORS,
        'slot_types': SLOT_TYPES,
        'plating_types': plating_types,
        'chemical_systems': chemical_systems,
    }
    return render(request, 'palladium/line_create.html', context)


def part_create(request):
    """定义新料号：产品基本信息输入"""
    lines = ProductionLine.objects.filter(is_active=True)
    customers = Customer.objects.all()

    if request.method == 'POST':
        part_no = (request.POST.get('part_no') or '').strip()
        customer_name = (request.POST.get('customer') or '').strip()
        cfg_lines = request.POST.getlist('cfg_line')
        cfg_golds = request.POST.getlist('cfg_gold')
        cfg_caps = request.POST.getlist('cfg_capacity')

        errors = []
        if not part_no:
            errors.append('请输入料号')
        elif Product.objects.filter(part_no=part_no).exists():
            errors.append(f'料号「{part_no}」已存在，请勿重复定义')
        n = len(cfg_lines)
        if n == 0:
            errors.append('请至少添加一组产线配置')
        if n > 5:
            errors.append('最多可添加5组产线配置')
        for i in range(min(n, 5)):
            if not cfg_lines[i].strip():
                errors.append(f'产线配置{i + 1}：请选择产线')

        if errors:
            for msg in errors:
                messages.error(request, msg)
        else:
            customer = None
            if customer_name:
                customer, created = Customer.objects.get_or_create(name=customer_name)
            product = Product.objects.create(
                part_no=part_no, customer=customer,
                created_by=request.user if request.user.is_authenticated else None,
            )
            for i in range(n):
                line = ProductionLine.objects.filter(id=cfg_lines[i]).first()
                ProductLineConfig.objects.create(
                    product=product, line=line,
                    std_gold_usage=cfg_golds[i].strip(),
                    std_capacity=cfg_caps[i].strip(),
                )
            user = request.user if request.user.is_authenticated else None
            OperationLog.objects.create(
                user=user,
                action=f'定义新料号：{part_no}'
                       f'（客户：{customer_name or "无"}，{n}组产线配置）',
            )
            messages.success(request, f'料号「{part_no}」创建成功，共 {n} 组产线配置')
            return redirect('palladium:dashboard')

    context = {
        'page_title': '定义新料号',
        'lines': lines,
        'customers': customers,
    }
    return render(request, 'palladium/part_create.html', context)


def product_list(request):
    """产品列表：按产线配置展示，支持筛选/排序/分页/导出"""
    q = (request.GET.get('q') or '').strip()
    customer_id = request.GET.get('customer') or ''
    line_id = request.GET.get('line') or ''
    status = request.GET.get('status') or ''      # '' | configured | unconfigured
    sort = request.GET.get('sort') or 'part_no'
    direction = request.GET.get('dir') or 'asc'
    try:
        page_size = int(request.GET.get('page_size') or 50)
    except ValueError:
        page_size = 50
    page_size = min(max(page_size, 10), 200)
    page_no = max(int(request.GET.get('page') or 1), 1)

    products = Product.objects.select_related(
        'customer', 'created_by',
    ).prefetch_related('line_configs__line', 'param_histories')
    if q:
        products = products.filter(part_no__icontains=q)
    if customer_id.isdigit():
        products = products.filter(customer_id=int(customer_id))

    rows = []
    for p in products:
        configs = list(p.line_configs.all())
        has_history = len(p.param_histories.all()) > 0
        creator = p.created_by.username if p.created_by else ''
        chip = sum(map(ord, creator)) % 4 if creator else None
        if status == 'unconfigured' and configs:
            continue
        if status == 'configured' and not configs:
            continue
        if not configs:
            rows.append({
                'product_id': p.id, 'part_no': p.part_no,
                'customer_name': p.customer.name if p.customer else '',
                'config_id': None, 'line_id': None, 'line_name': '',
                'gold': '', 'capacity': '',
                'creator': creator, 'chip': chip, 'created_at': p.created_at,
                'has_history': has_history, 'unconfigured': True,
            })
            continue
        for c in configs:
            rows.append({
                'product_id': p.id, 'part_no': p.part_no,
                'customer_name': p.customer.name if p.customer else '',
                'config_id': c.id, 'line_id': c.line_id,
                'line_name': c.line.name,
                'gold': _fmt_num(c.std_gold_usage),
                'capacity': _fmt_num(c.std_capacity),
                'creator': creator, 'chip': chip, 'created_at': p.created_at,
                'has_history': has_history, 'unconfigured': False,
            })

    if line_id.isdigit():
        rows = [r for r in rows if r['line_id'] == int(line_id)]

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return float('-inf') if v in ('', None) else 0

    sort_keys = {
        'part_no': lambda r: r['part_no'],
        'customer': lambda r: r['customer_name'],
        'line': lambda r: r['line_name'],
        'gold': lambda r: _num(r['gold']),
        'capacity': lambda r: _num(r['capacity']),
        'created_at': lambda r: r['created_at'],
    }
    rows.sort(key=sort_keys.get(sort, sort_keys['part_no']),
              reverse=(direction == 'desc'))

    # 查询串工具
    def list_url(overrides):
        params = request.GET.copy()
        for k, v in overrides.items():
            if v is None:
                params.pop(k, None)
            else:
                params[k] = v
        qs = params.urlencode()
        return request.path + ('?' + qs if qs else '')

    sort_urls = {}
    for field in sort_keys:
        next_dir = 'desc' if (sort == field and direction == 'asc') else 'asc'
        sort_urls[field] = list_url({'sort': field, 'dir': next_dir, 'page': None})

    export_url = list_url({'export': '1'})
    clear_url = request.path

    paginator = Paginator(rows, page_size)
    page = paginator.get_page(page_no)

    def page_url(num):
        return list_url({'page': num})

    context = {
        'page_title': '料号列表',
        'customers': Customer.objects.all(),
        'lines': ProductionLine.objects.filter(is_active=True),
        'page_sizes': [10, 20, 50, 100],
        'q': q, 'customer_id': customer_id, 'line_id': line_id,
        'status': status, 'sort': sort, 'direction': direction,
        'page_size': page_size,
        'page_obj': page,
        'sort_urls': sort_urls,
        'export_url': export_url,
        'clear_url': clear_url,
        'page_size_url': list_url({'page': None}),
        'prev_url': page_url(page.previous_page_number()) if page.has_previous() else '',
        'next_url': page_url(page.next_page_number()) if page.has_next() else '',
    }

    if request.GET.get('export'):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            f"attachment; filename=products_{timezone.localdate():%Y%m%d}.csv"
        )
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow(['料号', '客户名称', '产线', '标准钯用量(g/K)',
                         '标准产能(Kpcs/min)', '输入人员', '创建时间'])
        for r in rows:
            writer.writerow([
                r['part_no'], r['customer_name'], r['line_name'],
                r['gold'], r['capacity'], r['creator'],
                timezone.localtime(r['created_at']).strftime('%Y-%m-%d %H:%M'),
            ])
        return response

    return render(request, 'palladium/product_list.html', context)


def product_edit(request, pk):
    """编辑料号：基本信息 + 产线标准配置"""
    product = get_object_or_404(Product.objects.select_related('customer'), pk=pk)

    if request.method == 'POST':
        part_no = (request.POST.get('part_no') or '').strip()
        customer_name = (request.POST.get('customer') or '').strip()
        cfg_lines = request.POST.getlist('cfg_line')
        cfg_golds = request.POST.getlist('cfg_gold')
        cfg_caps = request.POST.getlist('cfg_capacity')

        errors = []
        if not part_no:
            errors.append('请输入料号')
        elif Product.objects.filter(part_no=part_no).exclude(id=product.id).exists():
            errors.append(f'料号「{part_no}」已存在')
        n = len(cfg_lines)
        for i in range(n):
            if not cfg_lines[i].strip():
                errors.append(f'产线配置{i + 1}：请选择产线')

        if errors:
            for msg in errors:
                messages.error(request, msg)
        else:
            customer = None
            if customer_name:
                customer = Customer.objects.get_or_create(name=customer_name)[0]
            product.part_no = part_no
            product.customer = customer
            product.save()
            product.line_configs.all().delete()
            for i in range(n):
                line = ProductionLine.objects.filter(id=cfg_lines[i]).first()
                ProductLineConfig.objects.create(
                    product=product, line=line,
                    std_gold_usage=cfg_golds[i].strip(),
                    std_capacity=cfg_caps[i].strip(),
                )
            user = request.user if request.user.is_authenticated else None
            OperationLog.objects.create(
                user=user,
                action=f'编辑料号：{part_no}（{n}组产线配置）',
            )
            messages.success(request, f'料号「{part_no}」已保存')
            return redirect('palladium:product_list')

    configs = product.line_configs.select_related('line')
    context = {
        'page_title': '编辑料号',
        'product': product,
        'configs': configs,
        'lines': ProductionLine.objects.filter(is_active=True),
        'customers': Customer.objects.all(),
    }
    return render(request, 'palladium/product_edit.html', context)


@require_POST
def product_delete(request, pk):
    """删除料号（或其单条产线配置）"""
    product = get_object_or_404(Product, pk=pk)
    cfg_id = request.POST.get('cfg') or ''
    if cfg_id.isdigit():
        config = ProductLineConfig.objects.filter(
            id=int(cfg_id), product=product).first()
        if config:
            line_name = config.line.name
            config.delete()
            OperationLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action=f'删除料号配置：{product.part_no} / {line_name}',
            )
            messages.success(request, f'已删除料号「{product.part_no}」的产线配置')
    else:
        part_no = product.part_no
        product.delete()
        OperationLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            action=f'删除料号：{part_no}',
        )
        messages.success(request, f'已删除料号「{part_no}」')
    return redirect('palladium:product_list')


def _fmt_num(value, digits=5):
    """数值统一格式化（默认5位小数），非数值原样返回"""
    try:
        return f'{float(value):.{digits}f}'
    except (TypeError, ValueError):
        return value or ''


def _creator_chip(user):
    name = user.username if user else ''
    return name, (sum(map(ord, name)) % 4 if name else None)


def line_list(request):
    """产线列表：分组展示产线及其槽位"""
    q = (request.GET.get('q') or '').strip()
    floor = request.GET.get('floor') or ''
    plating_id = request.GET.get('plating') or ''
    sort = request.GET.get('sort') or 'name_asc'

    lines = ProductionLine.objects.select_related(
        'plating_type', 'created_by').prefetch_related('slots__chemical_system', 'slots__created_by')
    if q:
        lines = lines.filter(name__icontains=q)
    if floor:
        lines = lines.filter(floor=floor)
    if plating_id.isdigit():
        lines = lines.filter(plating_type_id=int(plating_id))

    sort_map = {
        'name_asc': lambda l: l.name.lower(),
        'name_desc': lambda l: l.name.lower(),
        'floor_asc': lambda l: l.floor,
        'floor_desc': lambda l: l.floor,
        'time_desc': lambda l: l.created_at,
    }
    reverse = sort in ('name_desc', 'floor_desc')
    lines = sorted(lines, key=sort_map.get(sort, sort_map['name_asc']), reverse=reverse)

    def list_url(overrides):
        params = request.GET.copy()
        for k, v in overrides.items():
            if v is None:
                params.pop(k, None)
            else:
                params[k] = v
        qs = params.urlencode()
        return request.path + ('?' + qs if qs else '')

    sort_links = [
        ('名称↑', list_url({'sort': 'name_asc'}), sort == 'name_asc'),
        ('名称↓', list_url({'sort': 'name_desc'}), sort == 'name_desc'),
        ('楼层↑', list_url({'sort': 'floor_asc'}), sort == 'floor_asc'),
        ('楼层↓', list_url({'sort': 'floor_desc'}), sort == 'floor_desc'),
        ('时间↓', list_url({'sort': 'time_desc'}), sort == 'time_desc'),
    ]

    groups = []
    for line in lines:
        creator, chip = _creator_chip(line.created_by)
        slots = []
        type_counts = {}
        for s in line.slots.all():
            creator2, chip2 = _creator_chip(s.created_by)
            slots.append({
                'id': s.id, 'slot_no': s.slot_no, 'slot_type': s.slot_type,
                'name': s.name, 'chemical': s.chemical_system.name if s.chemical_system else '',
                'volume': _fmt_num(s.std_volume, 2),
                'concentration': _fmt_num(s.std_concentration, 2),
                'float_value': _fmt_num(s.float_value, 2),
                'creator': creator2, 'chip': chip2,
            })
            type_counts[s.slot_type] = type_counts.get(s.slot_type, 0) + 1
        groups.append({
            'line': line, 'slots': slots,
            'type_counts': sorted(type_counts.items()),
            'creator': creator, 'chip': chip,
        })

    context = {
        'page_title': '产线列表',
        'groups': groups,
        'floors': FLOORS,
        'plating_types': PlatingType.objects.all(),
        'q': q, 'floor': floor, 'plating_id': plating_id, 'sort': sort,
        'sort_links': sort_links,
        'clear_url': request.path,
    }
    return render(request, 'palladium/line_list.html', context)


def line_edit(request, pk):
    """编辑产线：基本信息 + 槽位信息表"""
    line = get_object_or_404(
        ProductionLine.objects.select_related('plating_type'), pk=pk)

    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        floor = (request.POST.get('floor') or '').strip()
        plating_id = (request.POST.get('plating_type') or '').strip()
        is_active = request.POST.get('is_active') == 'on'

        errors = []
        if not name:
            errors.append('请输入产线名称')
        elif ProductionLine.objects.filter(name=name).exclude(id=line.id).exists():
            errors.append(f'产线名称「{name}」已存在')
        if errors:
            for msg in errors:
                messages.error(request, msg)
        else:
            line.name = name
            line.floor = floor
            line.plating_type = PlatingType.objects.filter(id=plating_id).first()
            line.is_active = is_active
            line.save()
            OperationLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action=f'编辑产线：{name}（{"启用" if is_active else "停用"}）',
            )
            messages.success(request, f'产线「{name}」已保存')
            return redirect('palladium:line_list')

    context = {
        'page_title': '编辑产线',
        'line': line,
        'floors': FLOORS,
        'plating_types': PlatingType.objects.all(),
        'slot_count': line.slots.count(),
    }
    return render(request, 'palladium/line_edit.html', context)


@require_POST
def line_delete(request, pk):
    """删除产线"""
    line = get_object_or_404(ProductionLine, pk=pk)
    name = line.name
    line.delete()
    OperationLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=f'删除产线：{name}',
    )
    messages.success(request, f'已删除产线「{name}」')
    return redirect('palladium:line_list')


@require_POST
def line_slots_clear(request, pk):
    """一键删除产线下所有槽位"""
    line = get_object_or_404(ProductionLine, pk=pk)
    n = line.slots.count()
    line.slots.all().delete()
    OperationLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=f'删除产线「{line.name}」的全部槽位（{n}个）',
    )
    messages.success(request, f'已删除产线「{line.name}」的 {n} 个槽位')
    return redirect('palladium:line_edit', pk=line.id)


def _slot_form_context(line, slot=None):
    next_no = 1
    if not slot:
        last = line.slots.order_by('-slot_no').first()
        next_no = (last.slot_no + 1) if last else 1
    return {
        'page_title': '添加槽位' if not slot else '编辑槽位',
        'line': line,
        'slot': slot,
        'suggested_no': next_no,
        'slot_types': SLOT_TYPES,
        'chemical_systems': ChemicalSystem.objects.all(),
    }


def slot_add(request, pk):
    """添加槽位"""
    line = get_object_or_404(ProductionLine, pk=pk)

    if request.method == 'POST':
        errors, data = _validate_slot(line, request.POST)
        if errors:
            for msg in errors:
                messages.error(request, msg)
        else:
            user = request.user if request.user.is_authenticated else None
            Slot.objects.create(line=line, created_by=user, **data)
            OperationLog.objects.create(
                user=user,
                action=f'产线「{line.name}」添加槽位：{data["slot_no"]}号 {data["slot_type"]}',
            )
            messages.success(request, f'槽位 {data["slot_no"]} 已添加到产线「{line.name}」')
            return redirect('palladium:line_edit', pk=line.id)

    return render(request, 'palladium/slot_form.html', _slot_form_context(line))


def slot_edit(request, pk, slot_pk):
    """编辑槽位"""
    line = get_object_or_404(ProductionLine, pk=pk)
    slot = get_object_or_404(Slot, pk=slot_pk, line=line)

    if request.method == 'POST':
        errors, data = _validate_slot(line, request.POST, exclude_id=slot.id)
        if errors:
            for msg in errors:
                messages.error(request, msg)
        else:
            for k, v in data.items():
                setattr(slot, k, v)
            slot.save()
            OperationLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action=f'产线「{line.name}」编辑槽位：{data["slot_no"]}号',
            )
            messages.success(request, f'槽位已保存')
            return redirect('palladium:line_edit', pk=line.id)

    return render(request, 'palladium/slot_form.html', _slot_form_context(line, slot))


def _validate_slot(line, post, exclude_id=None):
    """槽位表单校验，返回 (errors, clean_data)"""
    errors = []
    slot_no = (post.get('slot_no') or '').strip()
    slot_type = (post.get('slot_type') or '').strip()
    name = (post.get('name') or '').strip()
    chem_id = (post.get('chemical_system') or '').strip()
    volume = (post.get('std_volume') or '').strip()
    concentration = (post.get('std_concentration') or '').strip()
    float_value = (post.get('float_value') or '').strip()

    data = {'slot_no': None, 'slot_type': slot_type, 'name': name, 'chemical_system': None,
            'std_volume': volume, 'std_concentration': concentration, 'float_value': float_value}

    if not slot_no.isdigit() or int(slot_no) <= 0:
        errors.append('槽位编号必须是正整数')
    else:
        dup = Slot.objects.filter(line=line, slot_no=int(slot_no))
        if exclude_id:
            dup = dup.exclude(id=exclude_id)
        if dup.exists():
            errors.append(f'槽位编号 {slot_no} 在产线「{line.name}」中已存在')
        else:
            data['slot_no'] = int(slot_no)
    if not slot_type:
        errors.append('请选择槽位类型')
    if not volume:
        errors.append('请输入标准体积')
    if not concentration:
        errors.append('请输入标准浓度')
    if chem_id.isdigit():
        data['chemical_system'] = ChemicalSystem.objects.filter(id=int(chem_id)).first()
    return errors, data


def _duration_minutes(start, end):
    """工时段分钟数，跨天（结束<=开始）自动加24小时"""
    if not start or not end:
        return 0
    d = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    if d < 0:
        d += 1440
    return d


def report_list(request):
    """生产日报查看：筛选 + 列表 + 行内详情"""
    line_id = request.GET.get('line') or ''
    start = _parse_date(request.GET.get('start'), None)
    end = _parse_date(request.GET.get('end'), None)
    leader = (request.GET.get('leader') or '').strip()
    ipqc = (request.GET.get('ipqc') or '').strip()

    reports = DailyReport.objects.select_related('line__plating_type', 'created_by')
    if line_id.isdigit():
        reports = reports.filter(line_id=int(line_id))
    if start:
        reports = reports.filter(sample_date__gte=start)
    if end:
        reports = reports.filter(sample_date__lte=end)
    if leader:
        reports = reports.filter(line_leader__icontains=leader)
    if ipqc:
        reports = reports.filter(ipqc__icontains=ipqc)

    rows = []
    for r in reports:
        creator, chip = _creator_chip(r.created_by)
        details = []
        total = 0
        for d in r.details.all():
            m = _duration_minutes(d.start_time, d.end_time)
            total += m
            details.append({
                'minutes': m,
                'range': f'{d.start_time:%H:%M} - {d.end_time:%H:%M}',
                'category': d.category,
                'part_no': d.part_no or '-',
                'quantity': d.quantity or '-',
            })
        rows.append({
            'id': r.id,
            'line': r.line,
            'floor': r.line.floor,
            'sample_date': r.sample_date,
            'sample_time': f'{r.sample_time:%H:%M}',
            'leader': r.line_leader,
            'ipqc': r.ipqc,
            'creator': creator, 'chip': chip,
            'slot_count': r.slot_data.count(),
            'slot_data': list(r.slot_data.all()),
            'details': details,
            'detail_count': len(details),
            'total_hours': f'{total / 60:.1f}',
        })

    def list_url(overrides):
        params = request.GET.copy()
        for k, v in overrides.items():
            if v is None:
                params.pop(k, None)
            else:
                params[k] = v
        qs = params.urlencode()
        return request.path + ('?' + qs if qs else '')

    context = {
        'page_title': '生产日报查看',
        'lines': ProductionLine.objects.filter(is_active=True),
        'rows': rows,
        'line_id': line_id,
        'start': request.GET.get('start') or '',
        'end': request.GET.get('end') or '',
        'leader': leader, 'ipqc': ipqc,
        'clear_url': request.path,
        'export_url': list_url({'export': '1'}),
    }

    if request.GET.get('export'):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            f"attachment; filename=daily_reports_{timezone.localdate():%Y%m%d}.csv"
        )
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow(['产线', '产线编号', '车间楼层', '取样日期', '取样时间',
                         '线长', 'IPQC', '输入人员', '槽位数量', '生产明细数量', '总时长(小时)'])
        for r in rows:
            writer.writerow([
                r['line'].name, r['line'].line_no, r['floor'],
                f"{r['sample_date']:%Y-%m-%d}", r['sample_time'],
                r['leader'] or '待填写', r['ipqc'] or '待填写',
                r['creator'], r['slot_count'], r['detail_count'], r['total_hours'],
            ])
        return response

    return render(request, 'palladium/report_list.html', context)


def report_edit(request, pk):
    """编辑生产日报：人员信息 + 生产明细"""
    report = get_object_or_404(
        DailyReport.objects.select_related('line'), pk=pk)

    if request.method == 'POST':
        leader = (request.POST.get('line_leader') or '').strip()
        ipqc = (request.POST.get('ipqc') or '').strip()
        d_starts = request.POST.getlist('d_start')
        d_ends = request.POST.getlist('d_end')
        d_cats = request.POST.getlist('d_cat')
        d_parts = request.POST.getlist('d_part')
        d_qty = request.POST.getlist('d_qty')

        errors = []
        details = []
        n = len(d_starts)
        for i in range(n):
            s = _parse_time(d_starts[i])
            e = _parse_time(d_ends[i])
            cat = d_cats[i].strip() if i < len(d_cats) else ''
            if not s:
                errors.append(f'明细{i + 1}：请选择开始时间')
            if not e:
                errors.append(f'明细{i + 1}：请选择结束时间')
            if not cat:
                errors.append(f'明细{i + 1}：请选择类别')
            if s and e and _duration_minutes(s, e) == 0:
                errors.append(f'明细{i + 1}：开始与结束时间相同')
            details.append({'start_time': s, 'end_time': e, 'category': cat,
                            'part_no': d_parts[i].strip() if i < len(d_parts) else '',
                            'quantity': d_qty[i].strip() if i < len(d_qty) else ''})

        if errors:
            for msg in errors:
                messages.error(request, msg)
        else:
            report.line_leader = leader
            report.ipqc = ipqc
            report.save()
            report.details.all().delete()
            for d in details:
                ReportDetail.objects.create(report=report, **d)
            OperationLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action=f'编辑生产日报：{report.line.name} {report.sample_date}（{len(details)}条明细）',
            )
            messages.success(request, '生产日报已保存')
            return redirect('palladium:report_list')

    total_minutes = sum(
        _duration_minutes(d.start_time, d.end_time) for d in report.details.all())
    context = {
        'page_title': '编辑生产日报',
        'report': report,
        'details': report.details.all(),
        'categories': DETAIL_CATEGORIES,
        'total_hours': f'{total_minutes / 60:.1f}',
    }
    return render(request, 'palladium/report_edit.html', context)


@require_POST
def report_delete(request, pk):
    """删除单条生产日报"""
    report = get_object_or_404(DailyReport, pk=pk)
    name = f'{report.line.name} {report.sample_date}'
    report.delete()
    OperationLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=f'删除生产日报：{name}',
    )
    messages.success(request, f'已删除生产日报（{name}）')
    return redirect('palladium:report_list')


@require_POST
def report_bulk_delete(request):
    """批量删除生产日报"""
    ids = request.POST.getlist('ids')
    qs = DailyReport.objects.filter(id__in=[i for i in ids if i.isdigit()])
    n = qs.count()
    qs.delete()
    OperationLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=f'批量删除生产日报（{n}条）',
    )
    messages.success(request, f'已批量删除 {n} 条生产日报')
    return redirect('palladium:report_list')


def concentration_list(request):
    """浓度数据查看"""
    line_id = request.GET.get('line') or ''
    slot_type = request.GET.get('slot_type') or ''
    start = _parse_date(request.GET.get('start'), None)
    end = _parse_date(request.GET.get('end'), None)

    rows_qs = ConcentrationSlot.objects.select_related(
        'record__line__plating_type', 'record__created_by').order_by(
        'record__line_id', 'slot_no', 'id')
    if line_id.isdigit():
        rows_qs = rows_qs.filter(record__line_id=int(line_id))
    if slot_type:
        rows_qs = rows_qs.filter(slot_type=slot_type)
    if start:
        rows_qs = rows_qs.filter(record__sample_date__gte=start)
    if end:
        rows_qs = rows_qs.filter(record__sample_date__lte=end)

    rows = []
    for s in rows_qs:
        creator, chip = _creator_chip(s.record.created_by)
        rows.append({
            'id': s.id,
            'record_id': s.record_id,
            'line': s.record.line,
            'floor': s.record.line.floor,
            'slot_no': s.slot_no,
            'slot_type': s.slot_type,
            'slot_name': s.slot_name,
            'chemical': s.chemical,
            'concentration': _fmt_num(s.concentration, 3),
            'liquid_level': _fmt_num(s.liquid_level, 2),
            'liters': _fmt_num(s.liters, 2) if s.liters else '-',
            'gold_salt': s.gold_salt or '-',
            'open_status': s.open_status or '无',
            'test_status': s.test_status or '未检测',
            'sample_date': s.record.sample_date,
            'sample_time': f'{s.record.sample_time:%H:%M}',
            'leader': s.record.line_leader,
            'ipqc': s.record.ipqc,
            'creator': creator, 'chip': chip,
        })

    context = {
        'page_title': '浓度数据查看',
        'lines': ProductionLine.objects.filter(is_active=True),
        'slot_types': CONC_SLOT_TYPES,
        'rows': rows,
        'line_id': line_id, 'slot_type_f': slot_type,
        'start': request.GET.get('start') or '',
        'end': request.GET.get('end') or '',
        'clear_url': request.path,
    }
    return render(request, 'palladium/concentration_list.html', context)


def concentration_edit(request, pk):
    """编辑浓度数据：槽位浓度行 + 分析员"""
    record = get_object_or_404(
        ConcentrationRecord.objects.select_related('line'), pk=pk)

    if request.method == 'POST':
        analyst = (request.POST.get('analyst') or '').strip()
        ids = request.POST.getlist('c_id')
        opens = request.POST.getlist('c_open')
        tests = request.POST.getlist('c_test')
        concs = request.POST.getlist('c_conc')
        grasses = request.POST.getlist('c_grass')
        liquids = request.POST.getlist('c_liquid')
        liters = request.POST.getlist('c_liters')
        golds = request.POST.getlist('c_gold')

        for i, sid in enumerate(ids):
            if not sid.isdigit():
                continue
            slot = ConcentrationSlot.objects.filter(id=int(sid), record=record).first()
            if not slot:
                continue
            slot.open_status = opens[i].strip() if i < len(opens) else '无'
            slot.test_status = tests[i].strip() if i < len(tests) else '未检测'
            if slot.test_status == '检测':
                # 检测状态下罩头/浓度/液位可填写
                slot.concentration = concs[i].strip() if i < len(concs) else slot.concentration
                slot.grass_type = grasses[i].strip() if i < len(grasses) else ''
                slot.liquid_level = liquids[i].strip() if i < len(liquids) else slot.liquid_level
            else:
                # 未检测状态下锁定，保持原值；罩头清空
                slot.grass_type = ''
            slot.gold_salt = golds[i].strip() if i < len(golds) else slot.gold_salt
            # 升数为自动计算，不由表单更新
            slot.save()
        record.analyst = analyst
        record.save()
        OperationLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            action=f'编辑浓度数据：{record.line.name} {record.sample_date}',
        )
        messages.success(request, '浓度数据已保存')
        return redirect('palladium:concentration_list')

    context = {
        'page_title': '编辑浓度数据',
        'record': record,
        'slot_rows': record.slot_rows.all(),
        'open_status_options': OPEN_STATUS,
        'test_status_options': TEST_STATUS,
        'grass_types': GRASS_TYPES,
    }
    return render(request, 'palladium/concentration_edit.html', context)


@require_POST
def concentration_slot_delete(request, pk):
    """删除单条浓度槽位行"""
    slot = get_object_or_404(ConcentrationSlot.objects.select_related('record'), pk=pk)
    line_name = slot.record.line.name
    slot.delete()
    OperationLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=f'删除浓度数据行：{line_name} 槽位{slot.slot_no}',
    )
    messages.success(request, f'已删除浓度数据行（{line_name} 槽位{slot.slot_no}）')
    return redirect('palladium:concentration_list')


@require_POST
def concentration_bulk_delete(request):
    """批量删除浓度槽位行"""
    ids = request.POST.getlist('ids')
    qs = ConcentrationSlot.objects.filter(id__in=[i for i in ids if i.isdigit()])
    n = qs.count()
    qs.delete()
    OperationLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=f'批量删除浓度数据行（{n}条）',
    )
    messages.success(request, f'已批量删除 {n} 条浓度数据')
    return redirect('palladium:concentration_list')


@require_POST
def concentration_slots_clear(request, pk):
    """一键删除某浓度记录下所有槽位数据"""
    record = get_object_or_404(ConcentrationRecord, pk=pk)
    n = record.slot_rows.count()
    record.slot_rows.all().delete()
    OperationLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=f'删除「{record.line.name} {record.sample_date}」全部浓度槽位数据（{n}条）',
    )
    messages.success(request, f'已删除 {n} 条槽位浓度数据')
    return redirect('palladium:concentration_edit', pk=record.id)


def name_diagnosis(request):
    """名称诊断：客户/线长/IPQC 名称使用情况"""
    customer_rows = [
        {'id': c.id, 'name': c.name, 'usage': c.usage}
        for c in Customer.objects.annotate(usage=Count('products')).order_by('-usage', 'name')
    ]

    def name_stats(field):
        rows = []
        for row in DailyReport.objects.values(field).annotate(
                usage=Count('id')).order_by('-usage'):
            blank = not row[field]
            rows.append({
                'name': row[field] or '待填写',
                'usage': row['usage'],
                'blank': blank,
            })
        return rows

    context = {
        'page_title': '名称诊断',
        'customers': customer_rows,
        'leaders': name_stats('line_leader'),
        'ipqcs': name_stats('ipqc'),
    }
    return render(request, 'palladium/name_diagnosis.html', context)


def param_history_list(request):
    """标准参数历史列表"""
    q = (request.GET.get('q') or '').strip()
    line_id = request.GET.get('line') or ''
    start = _parse_date(request.GET.get('start'), None)
    end = _parse_date(request.GET.get('end'), None)
    try:
        page_size = int(request.GET.get('page_size') or 20)
    except ValueError:
        page_size = 20
    page_size = min(max(page_size, 10), 200)
    page_no = max(int(request.GET.get('page') or 1), 1)

    configs = StandardParamConfig.objects.select_related(
        'history__product', 'history__created_by', 'line').order_by(
        'history__product__part_no', 'line__name', '-history__effective_date', '-history_id')

    rows = []
    for c in configs:
        h = c.history
        rows.append({
            'id': c.id,
            'line_id': c.line_id,
            'part_no': h.product.part_no,
            'line_name': c.line.name,
            'gold': _fmt_num(c.std_gold_usage),
            'capacity': _fmt_num(c.std_capacity),
            'effective': h.effective_date,
            'creator': h.created_by.username if h.created_by else '',
            'creator_chip': _creator_chip(h.created_by)[1],
            'created_at': h.created_at,
        })

    # 失效时间：同一料号+产线下，取晚于本条的最近生效时间
    groups = {}
    for r in rows:
        groups.setdefault((r['part_no'], r['line_name']), []).append(r)
    for items in groups.values():
        items.sort(key=lambda r: (r['effective'], r['id']))
        for i, r in enumerate(items):
            r['expiry'] = items[i + 1]['effective'] if i + 1 < len(items) else None

    if q:
        rows = [r for r in rows if q.lower() in r['part_no'].lower()]
    if line_id.isdigit():
        rows = [r for r in rows if r['line_id'] == int(line_id)]
    if start:
        rows = [r for r in rows if r['effective'] >= start]
    if end:
        rows = [r for r in rows if r['effective'] <= end]

    paginator = Paginator(rows, page_size)
    page = paginator.get_page(page_no)

    def list_url(overrides):
        params = request.GET.copy()
        for k, v in overrides.items():
            if v is None:
                params.pop(k, None)
            else:
                params[k] = v
        qs = params.urlencode()
        return request.path + ('?' + qs if qs else '')

    context = {
        'page_title': '历史参数列表',
        'lines': ProductionLine.objects.filter(is_active=True),
        'page_sizes': [10, 20, 50, 100],
        'page_size': page_size,
        'q': q, 'line_id': line_id,
        'start': request.GET.get('start') or '',
        'end': request.GET.get('end') or '',
        'page_obj': page,
        'clear_url': request.path,
        'prev_url': list_url({'page': page.previous_page_number()}) if page.has_previous() else '',
        'next_url': list_url({'page': page.next_page_number()}) if page.has_next() else '',
    }
    return render(request, 'palladium/param_history.html', context)


@require_POST
def param_history_delete(request, pk):
    """删除标准参数历史行（配置行；若历史下已无配置则一并删除历史）"""
    config = get_object_or_404(
        StandardParamConfig.objects.select_related('history__product', 'line'), pk=pk)
    history = config.history
    info = f'{history.product.part_no} / {config.line.name}'
    config.delete()
    if history.configs.count() == 0:
        history.delete()
    OperationLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=f'删除标准参数历史：{info}',
    )
    messages.success(request, f'已删除标准参数（{info}）')
    return redirect('palladium:param_history_list')


def param_create(request):
    """新增标准参数（标准参数历史）"""
    customers = Customer.objects.all()
    products = Product.objects.select_related('customer')

    if request.method == 'POST':
        product_id = (request.POST.get('product') or '').strip()
        effective_date = (request.POST.get('effective_date') or '').strip()
        cfg_lines = request.POST.getlist('cfg_line')
        cfg_golds = request.POST.getlist('cfg_gold')
        cfg_caps = request.POST.getlist('cfg_capacity')

        errors = []
        product = Product.objects.filter(id=product_id).first()
        if not product:
            errors.append('请选择料号')
        date_val = _parse_date(effective_date, None)
        if not date_val:
            errors.append('请选择生效日期')
        n = len(cfg_lines)
        if n == 0:
            errors.append('请至少添加一组产线配置')
        if n > 5:
            errors.append('最多可添加5组产线配置')
        for i in range(min(n, 5)):
            if not cfg_lines[i].strip():
                errors.append(f'产线配置{i + 1}：请选择产线')

        if errors:
            for msg in errors:
                messages.error(request, msg)
        else:
            history = StandardParamHistory.objects.create(
                product=product, effective_date=date_val,
                created_by=request.user if request.user.is_authenticated else None,
            )
            for i in range(n):
                line = ProductionLine.objects.filter(id=cfg_lines[i]).first()
                StandardParamConfig.objects.create(
                    history=history, line=line,
                    std_gold_usage=cfg_golds[i].strip(),
                    std_capacity=cfg_caps[i].strip(),
                )
            user = request.user if request.user.is_authenticated else None
            OperationLog.objects.create(
                user=user,
                action=f'新增标准参数：{product.part_no}'
                       f'（生效日期 {date_val}，{n}组产线配置）',
            )
            messages.success(request, f'料号「{product.part_no}」的标准参数已保存，'
                                      f'生效日期 {date_val}，共 {n} 组产线配置')
            return redirect('palladium:dashboard')

    context = {
        'page_title': '新增标准参数',
        'customers': customers,
        'products': products,
        'lines': ProductionLine.objects.filter(is_active=True),
    }
    return render(request, 'palladium/param_create.html', context)


@require_POST
def api_plating_type_add(request):
    """新增镀种"""
    name = (request.POST.get('name') or '').strip()
    if not name:
        return JsonResponse({'ok': False, 'error': '请输入镀种名称'}, status=400)
    obj, created = PlatingType.objects.get_or_create(name=name)
    if created:
        user = request.user if request.user.is_authenticated else None
        OperationLog.objects.create(user=user, action=f'新增镀种：{name}')
    return JsonResponse({'ok': True, 'id': obj.id, 'name': obj.name})


@require_POST
def api_chemical_system_add(request):
    """新增药水系统"""
    name = (request.POST.get('name') or '').strip()
    if not name:
        return JsonResponse({'ok': False, 'error': '请输入药水系统名称'}, status=400)
    obj, created = ChemicalSystem.objects.get_or_create(name=name)
    if created:
        user = request.user if request.user.is_authenticated else None
        OperationLog.objects.create(user=user, action=f'新增药水系统：{name}')
    return JsonResponse({'ok': True, 'id': obj.id, 'name': obj.name})


def placeholder(request, title):
    """占位页：未开发完成的菜单跳转到此"""
    return render(request, 'palladium/placeholder.html', {'page_title': title})


def _parse_date(value, default):
    if not value:
        return default
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return default


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.time.fromisoformat(value)
    except ValueError:
        return None


def _fmt_num(value, digits=5):
    """数值统一格式化（默认5位小数），非数值原样返回"""
    try:
        return f'{float(value):.{digits}f}'
    except (TypeError, ValueError):
        return value or ''
