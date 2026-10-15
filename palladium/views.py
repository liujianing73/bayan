import csv
import datetime
import json

from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST
from urllib.parse import urlencode

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
DETAIL_CATEGORIES = ['生产', '换线', '重工', '试做', '判定', '阳极添加', '异常<90分钟', '无效工时']
# 类别联动：需要料号的类别 / 需要料号+生产数量的类别
CATEGORIES_NEED_PART = {'生产', '换线', '重工', '试做', '判定', '阳极添加', '异常<90分钟'}
CATEGORIES_NEED_QTY = {'生产', '重工', '试做'}
SAMPLE_TIMES = ['08:00', '20:00']
MIN_MINUTES = 720  # 每日总时长须满12小时
OPEN_STATUS = ['无', '开缸', '抽出', '回槽', '抽入']
TEST_STATUS = ['未检测', '检测']
GRASS_TYPES = ['无', '浸-单', '浸-双', '浸-三', '浸-四', '点-单', '点-双', '点-三', '点-四', '刷-单', '刷-双', '刷-三', '刷-四', '刷-五', '刷-六']
CONC_SLOT_TYPES = ['镀钯', '镀镍']

FLOORS = ['车间1楼', '车间2楼', '车间3楼']

SLOT_TYPES = ['镀钯', '镀镍']


def login_view(request):
    """登录页"""
    if request.user.is_authenticated:
        return redirect('palladium:dashboard')
    error = ''
    username = ''
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        if not username or not password:
            error = '请输入用户名和密码'
        else:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                auth_login(request, user)
                return redirect('palladium:dashboard')
            error = '用户名或密码错误'
    return render(request, 'palladium/login.html', {
        'error': error, 'username': username,
    })


def logout_view(request):
    """退出登录"""
    auth_logout(request)
    return redirect('palladium:login')


def register_view(request):
    """注册页"""
    error = ''
    username = ''
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        password2 = request.POST.get('password2') or ''
        if not username:
            error = '请输入用户名'
        elif User.objects.filter(username=username).exists():
            error = f'用户名「{username}」已存在'
        elif len(password) < 6:
            error = '密码至少 6 位'
        elif password != password2:
            error = '两次输入的密码不一致'
        if not error:
            user = User.objects.create_user(username=username, password=password)
            auth_login(request, user)
            messages.success(request, f'欢迎加入，{user.username}！')
            return redirect('palladium:dashboard')
    return render(request, 'palladium/register.html', {
        'error': error, 'username': username,
    })


def _build_line_cards(date, search):
    """产线录入状态卡片数据"""
    lines = ProductionLine.objects.filter(is_active=True)
    if search:
        lines = lines.filter(name__icontains=search)
    entries = ShiftEntry.objects.filter(date=date)
    entry_map = {(e.line_id, e.shift): e for e in entries}
    report_map = {
        (r.line_id, ShiftEntry.SHIFT_DAY if r.sample_time.hour < 12 else ShiftEntry.SHIFT_NIGHT): r.id
        for r in DailyReport.objects.filter(sample_date=date)
    }
    cards = []
    for line in lines:
        day_report_id = report_map.get((line.id, ShiftEntry.SHIFT_DAY))
        night_report_id = report_map.get((line.id, ShiftEntry.SHIFT_NIGHT))
        day_url = (reverse('palladium:report_edit', args=[day_report_id]) if day_report_id
                   else reverse('palladium:report_create')
                   + f"?line={line.id}&date={date:%Y-%m-%d}&time=08:00")
        night_url = (reverse('palladium:report_edit', args=[night_report_id]) if night_report_id
                     else reverse('palladium:report_create')
                     + f"?line={line.id}&date={date:%Y-%m-%d}&time=20:00")
        cards.append({
            'line': line,
            'day': entry_map.get((line.id, ShiftEntry.SHIFT_DAY)),
            'night': entry_map.get((line.id, ShiftEntry.SHIFT_NIGHT)),
            'day_url': day_url, 'night_url': night_url,
        })
    return cards


def _build_conc_cards(c_date, c_search):
    """钯盐浓度输入卡片数据（已录入跳编辑页，未录入跳录入页预选）"""
    c_lines = ProductionLine.objects.filter(is_active=True)
    if c_search:
        c_lines = c_lines.filter(name__icontains=c_search)
    conc_map = {
        (r.line_id, ShiftEntry.SHIFT_DAY if r.sample_time.hour < 12 else ShiftEntry.SHIFT_NIGHT): r
        for r in ConcentrationRecord.objects.filter(sample_date=c_date)
    }
    cards = []
    for line in c_lines:
        base = (reverse('palladium:concentration_input')
                + f"?line={line.id}&date={c_date:%Y-%m-%d}&time=")
        day_rec = conc_map.get((line.id, ShiftEntry.SHIFT_DAY))
        night_rec = conc_map.get((line.id, ShiftEntry.SHIFT_NIGHT))
        cards.append({
            'line': line,
            'day': day_rec, 'night': night_rec,
            'day_url': (reverse('palladium:concentration_edit', args=[day_rec.id])
                        if day_rec else base + '08:00'),
            'night_url': (reverse('palladium:concentration_edit', args=[night_rec.id])
                          if night_rec else base + '20:00'),
        })
    return cards


def dashboard(request):
    """系统首页：最近操作记录 / 产线录入状态 / 钯盐浓度输入 + 快捷入口"""
    date = _parse_date(request.GET.get('date'), timezone.localdate())
    search = request.GET.get('q', '').strip()
    c_date = _parse_date(request.GET.get('c_date'), timezone.localdate())
    c_search = request.GET.get('c_q', '').strip()

    line_cards = _build_line_cards(date, search)
    conc_cards = _build_conc_cards(c_date, c_search)

    since = timezone.now() - datetime.timedelta(hours=24)
    logs = OperationLog.objects.filter(created_at__gte=since)[:50]

    today = timezone.localdate()
    c_date_label = '今日' if c_date == today else f'{c_date.month}月{c_date.day}日'
    batch_sections = [x for x in (request.GET.get('batch') or '').split(',') if x in ('1', '2')]

    context = {
        'page_title': '首页',
        'date': date,
        'search': search,
        'line_cards': line_cards,
        'c_date': c_date,
        'c_date_label': c_date_label,
        'c_search': c_search,
        'conc_cards': conc_cards,
        'batch_sections': batch_sections,
        'logs': logs,
    }
    return render(request, 'palladium/dashboard.html', context)


def dashboard_cards(request):
    """AJAX：按日期/搜索就地刷新首页卡片区块（不整页跳转）"""
    sec = request.GET.get('sec') or '1'
    today = timezone.localdate()
    date = _parse_date(request.GET.get('date'), timezone.localdate())
    c_date = _parse_date(request.GET.get('c_date'), timezone.localdate())
    q = (request.GET.get('q') or '').strip()
    c_q = (request.GET.get('c_q') or '').strip()
    batch_sections = [x for x in (request.GET.get('batch') or '').split(',') if x in ('1', '2')]

    if sec == '2':
        c_date_label = '今日' if c_date == today else f'{c_date.month}月{c_date.day}日'
        html = render_to_string('palladium/_conc_cards.html', {
            'conc_cards': _build_conc_cards(c_date, c_q),
            'batch_sections': batch_sections,
            'c_date_label': c_date_label,
        })
    else:
        html = render_to_string('palladium/_line_cards.html', {
            'line_cards': _build_line_cards(date, q),
            'batch_sections': batch_sections,
        })
    return HttpResponse(html)

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
            part = d_parts[i].strip() if i < len(d_parts) else ''
            qty = d_qty[i].strip() if i < len(d_qty) else ''
            if not s:
                errors.append(f'明细{i + 1}：请选择开始时间')
            if not e:
                errors.append(f'明细{i + 1}：请选择结束时间')
            if not cat:
                errors.append(f'明细{i + 1}：请选择类别')
            if s and e and _duration_minutes(s, e) == 0:
                errors.append(f'明细{i + 1}：开始与结束时间相同')
            # 类别联动：生产/重工/试做 需料号+生产数量；换线/判定/阳极添加/异常<90分钟 需料号
            if cat in CATEGORIES_NEED_PART and not part:
                errors.append(f'明细{i + 1}：类别「{cat}」需要输入料号')
            if cat in CATEGORIES_NEED_QTY and not qty:
                errors.append(f'明细{i + 1}：类别「{cat}」需要输入生产数量')
            if cat not in CATEGORIES_NEED_PART:
                part = ''
                qty = ''
            details.append({'start_time': s, 'end_time': e, 'category': cat,
                            'part_no': part, 'quantity': qty})

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
        'products': Product.objects.select_related('customer'),
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
        'page_title': '浓度数据查看',
        'lines': ProductionLine.objects.filter(is_active=True),
        'slot_types': CONC_SLOT_TYPES,
        'rows': rows,
        'line_id': line_id, 'slot_type_f': slot_type,
        'start': request.GET.get('start') or '',
        'end': request.GET.get('end') or '',
        'clear_url': request.path,
        'export_url': list_url({'export': '1'}),
    }

    if request.GET.get('export'):
        return _export_concentration_csv(request, line_id, start, end)

    return render(request, 'palladium/concentration_list.html', context)


def _effective_concentration(line, day, sample_time):
    """有效浓度记录：当天有检测数据则当日录入；否则一直沿用之前最近的检测数据；
    批量生成的未检测占位记录不算新数据（仅在无任何检测数据时兜底返回）"""
    rec = ConcentrationRecord.objects.filter(
        line=line, sample_date=day, sample_time=sample_time, test_status='检测').first()
    if rec:
        return rec, '当日录入'
    rec = ConcentrationRecord.objects.filter(
        line=line, sample_time=sample_time, sample_date__lt=day,
        test_status='检测').order_by('-sample_date').first()
    if rec:
        return rec, f"沿用{rec.sample_date:%m-%d}"
    rec = ConcentrationRecord.objects.filter(
        line=line, sample_date=day, sample_time=sample_time).first()
    if rec:
        return rec, '当日录入(未检测)'
    return None, None


def _export_concentration_csv(request, line_id, start, end):
    """导出浓度数据：无当天录入的沿用前一天数据（来源列体现）"""
    today = timezone.localdate()
    if start and end and start <= end:
        span = (end - start).days
        dates = [start + datetime.timedelta(days=i) for i in range(span + 1)]
    elif start:
        dates = [start + datetime.timedelta(days=i) for i in range((today - start).days + 1)]
    elif end:
        dates = [end - datetime.timedelta(days=i) for i in range(30, -1, -1)]
    else:
        dates = [today - datetime.timedelta(days=i) for i in range(6, -1, -1)]
    dates = dates[-62:]  # 防止范围过大

    lines = ProductionLine.objects.filter(is_active=True)
    if line_id.isdigit():
        lines = lines.filter(id=int(line_id))

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = (
        f"attachment; filename=concentrations_{today:%Y%m%d}.csv")
    response.write('﻿')
    writer = csv.writer(response)
    writer.writerow(['取样日期', '产线', '班次', '槽位编号', '槽位类型', '槽位名称',
                     '化学体系', '浓度(g/L)', '液位(cm)', '升数(L)', '钯盐添加量(g)',
                     '槽位状态', '浓度检测状态', '数据来源'])
    shift_names = {'day': '早班', 'night': '晚班'}
    for line in lines:
        for d in dates:
            for shift, stime in (('day', datetime.time(8, 0)), ('night', datetime.time(20, 0))):
                rec, source = _effective_concentration(line, d, stime)
                if not rec:
                    continue
                for s in rec.slot_rows.all():
                    writer.writerow([
                        f"{d:%Y-%m-%d}", line.name, shift_names[shift],
                        s.slot_no, s.slot_type, s.slot_name, s.chemical,
                        _fmt_num(s.concentration, 3), _fmt_num(s.liquid_level, 2),
                        _fmt_num(s.liters, 2), s.gold_salt or '0',
                        s.open_status or '无', s.test_status or '未检测', source,
                    ])
    return response


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


def report_create(request):
    """填写生产日报：录入时间段明细，总时长须满12小时"""
    if request.method == 'POST':
        line_id = (request.POST.get('line') or '').strip()
        sample_time = (request.POST.get('sample_time') or '').strip()
        sample_date = _parse_date(request.POST.get('sample_date'), None)
        leader = (request.POST.get('line_leader') or '').strip()
        ipqc = (request.POST.get('ipqc') or '').strip()

        d_starts = request.POST.getlist('d_start')
        d_ends = request.POST.getlist('d_end')
        d_cats = request.POST.getlist('d_cat')
        d_parts = request.POST.getlist('d_part')
        d_qty = request.POST.getlist('d_qty')

        errors = []
        line = ProductionLine.objects.filter(id=line_id, is_active=True).first()
        if not line:
            errors.append('请选择产线')
        time_val = _parse_time(sample_time)
        if not time_val:
            errors.append('请选择时间')
        if not sample_date:
            errors.append('请选择日期')
        if line and time_val and sample_date:
            if DailyReport.objects.filter(
                    line=line, sample_date=sample_date, sample_time=time_val).exists():
                errors.append(f'产线「{line.name}」在 {sample_date} {sample_time} 的日报已存在，请勿重复填写')

        details = []
        total = 0
        n = len(d_starts)
        for i in range(n):
            s = _parse_time(d_starts[i])
            e = _parse_time(d_ends[i])
            cat = d_cats[i].strip() if i < len(d_cats) else ''
            part = d_parts[i].strip() if i < len(d_parts) else ''
            qty = d_qty[i].strip() if i < len(d_qty) else ''
            if not s:
                errors.append(f'明细{i + 1}：请选择开始时间')
            if not e:
                errors.append(f'明细{i + 1}：请选择结束时间')
            if not cat:
                errors.append(f'明细{i + 1}：请选择类别')
            if s and e:
                m = _duration_minutes(s, e)
                if m == 0:
                    errors.append(f'明细{i + 1}：开始与结束时间相同')
                total += m
            # 类别联动：生产/重工/试做 需料号+生产数量；换线/判定/阳极添加/异常<90分钟 需料号
            if cat in CATEGORIES_NEED_PART and not part:
                errors.append(f'明细{i + 1}：类别「{cat}」需要输入料号')
            if cat in CATEGORIES_NEED_QTY and not qty:
                errors.append(f'明细{i + 1}：类别「{cat}」需要输入生产数量')
            if cat not in CATEGORIES_NEED_PART:
                part = ''
                qty = ''
            details.append({'start_time': s, 'end_time': e, 'category': cat,
                            'part_no': part, 'quantity': qty})

        if not errors and total < MIN_MINUTES:
            errors.append(f'时间未满十二小时（当前总时长 {total / 60:.1f} 小时），无法保存')

        if errors:
            for msg in errors:
                messages.error(request, msg)
            return redirect('palladium:report_create')

        user = request.user if request.user.is_authenticated else None
        report = DailyReport.objects.create(
            line=line, sample_date=sample_date, sample_time=time_val,
            line_leader=leader, ipqc=ipqc, created_by=user)
        for d in details:
            ReportDetail.objects.create(report=report, **d)
        # 同步首页班次录入状态（08:00 为早班，其余为晚班）
        shift = ShiftEntry.SHIFT_DAY if time_val.hour < 12 else ShiftEntry.SHIFT_NIGHT
        ShiftEntry.objects.update_or_create(
            line=line, date=sample_date, shift=shift,
            defaults={'entered_by': user, 'entered_at': timezone.now()})
        OperationLog.objects.create(
            user=user,
            action=f'填写生产日报：{line.name} {sample_date} {sample_time}'
                   f'（{len(details)}条明细，总时长 {total / 60:.1f} 小时）',
        )
        messages.success(request, f'产线「{line.name}」的生产日报已提交'
                                  f'（总时长 {total / 60:.1f} 小时）')
        return redirect('palladium:report_list')

    init_line = request.GET.get('line') or ''
    init_date = _parse_date(request.GET.get('date'), timezone.localdate())
    init_time = request.GET.get('time') or '08:00'
    context = {
        'page_title': '填写生产日报',
        'lines': ProductionLine.objects.filter(is_active=True),
        'sample_times': SAMPLE_TIMES,
        'categories': DETAIL_CATEGORIES,
        'products': Product.objects.select_related('customer'),
        'today': timezone.localdate(),
        'init_line': init_line,
        'init_date': init_date,
        'init_time': init_time if init_time in SAMPLE_TIMES else '08:00',
    }
    return render(request, 'palladium/report_create.html', context)


def concentration_input(request):
    """钯盐浓度输入：选择产线/日期/时间后录入各槽位浓度"""
    line_id = request.GET.get('line') or ''
    sample_date = _parse_date(request.GET.get('date'), timezone.localdate())
    time_str = request.GET.get('time') or '08:00'
    time_val = _parse_time(time_str) or datetime.time(8, 0)
    selected = False
    slot_rows = []
    leader = ipqc = ''
    record = None

    lines = ProductionLine.objects.filter(is_active=True).annotate(
        n_slots=Count('slots')).filter(n_slots__gt=0)
    if line_id.isdigit():
        selected_line = lines.filter(id=int(line_id)).first()
        if selected_line:
            selected = True
            record = ConcentrationRecord.objects.filter(
                line=selected_line, sample_date=sample_date, sample_time=time_val).first()
            report = DailyReport.objects.filter(
                line=selected_line, sample_date=sample_date, sample_time=time_val).first()
            if report:
                leader = report.line_leader
                ipqc = report.ipqc
            # 载入槽位行：已有记录用其数据，否则用产线槽位默认值
            if record:
                for s in record.slot_rows.all():
                    slot_rows.append({
                        'slot': s, 'slot_no': s.slot_no, 'slot_type': s.slot_type,
                        'name': s.slot_name,
                        'open': s.open_status or '无', 'test': s.test_status or '未检测',
                        'conc': s.concentration, 'grass': s.grass_type,
                        'liquid': s.liquid_level, 'liters': s.liters,
                        'gold': s.gold_salt,
                    })
            else:
                for s in selected_line.slots.all():
                    slot_rows.append({
                        'slot': s, 'slot_no': s.slot_no, 'slot_type': s.slot_type,
                        'name': s.name, 'open': '无', 'test': '未检测',
                        'conc': '0', 'grass': '', 'liquid': '0',
                        'liters': s.std_volume, 'gold': '0',
                    })

    if request.method == 'POST':
        line = ProductionLine.objects.filter(
            id=request.POST.get('line') or 0, is_active=True).first()
        p_date = _parse_date(request.POST.get('date'), None)
        p_time = _parse_time(request.POST.get('time') or '')
        errors = []
        if not line:
            errors.append('请选择产线')
        if not p_date:
            errors.append('请选择日期')
        if not p_time:
            errors.append('请选择时间')
        ids = request.POST.getlist('s_id')
        opens = request.POST.getlist('s_open')
        tests = request.POST.getlist('s_test')
        concs = request.POST.getlist('s_conc')
        grasses = request.POST.getlist('s_grass')
        liquids = request.POST.getlist('s_liquid')
        golds = request.POST.getlist('s_gold')
        parsed = []
        for i, sid in enumerate(ids):
            if not sid.isdigit():
                continue
            slot = Slot.objects.filter(id=int(sid), line=line).first() if line else None
            if not slot:
                continue
            test = tests[i].strip() if i < len(tests) else '未检测'
            conc = concs[i].strip() if i < len(concs) else ''
            grass = grasses[i].strip() if i < len(grasses) else ''
            liquid = liquids[i].strip() if i < len(liquids) else ''
            if test == '检测':
                if not conc:
                    errors.append(f'槽位{slot.slot_no}：检测状态下浓度必填')
                if not grass:
                    errors.append(f'槽位{slot.slot_no}：检测状态下罩头类型必填')
                if not liquid:
                    errors.append(f'槽位{slot.slot_no}：检测状态下液位必填')
            parsed.append({
                'slot': slot, 'open': opens[i].strip() if i < len(opens) else '无',
                'test': test, 'conc': conc, 'grass': grass,
                'liquid': liquid, 'gold': golds[i].strip() if i < len(golds) else '0',
            })

        if not errors and line and p_date and p_time:
            if ConcentrationRecord.objects.filter(
                    line=line, sample_date=p_date, sample_time=p_time).exists():
                errors.append(f'产线「{line.name}」在 {p_date} {p_time} 的浓度数据已存在，'
                              f'请在"浓度数据查看"中编辑')
        if errors:
            for msg in errors:
                messages.error(request, msg)
            return redirect('palladium:concentration_input'
                            + f'?line={line.id if line else ""}&date={p_date or ""}&time={p_time or "08:00"}')

        user = request.user if request.user.is_authenticated else None
        record = ConcentrationRecord.objects.create(
            line=line, sample_date=p_date, sample_time=p_time,
            line_leader=(request.POST.get('line_leader') or '').strip(),
            ipqc=(request.POST.get('ipqc') or '').strip(),
            analyst=(request.POST.get('analyst') or '').strip(),
            created_by=user)
        for p in parsed:
            ConcentrationSlot.objects.create(
                record=record, slot_no=p['slot'].slot_no,
                slot_type=p['slot'].slot_type, slot_name=p['slot'].name,
                chemical=p['slot'].chemical_system.name if p['slot'].chemical_system else '',
                open_status=p['open'], test_status=p['test'],
                concentration=p['conc'], grass_type=p['grass'],
                liquid_level=p['liquid'], liters=p['slot'].std_volume,
                gold_salt=p['gold'])
        OperationLog.objects.create(
            user=user,
            action=f'钯盐浓度输入：{line.name} {p_date} {p_time}（{len(parsed)}个槽位）',
        )
        messages.success(request, f'产线「{line.name}」的浓度数据已提交（{len(parsed)}个槽位）')
        return redirect('palladium:concentration_list')

    context = {
        'page_title': '钯盐浓度输入',
        'lines': lines,
        'line_id': line_id,
        'sample_date': sample_date,
        'time_str': time_str,
        'sample_times': SAMPLE_TIMES,
        'open_status_options': OPEN_STATUS,
        'test_status_options': TEST_STATUS,
        'grass_types': GRASS_TYPES,
        'selected': selected,
        'slot_rows': slot_rows,
        'leader': leader,
        'ipqc': ipqc,
    }
    return render(request, 'palladium/concentration_input.html', context)


@require_POST
def shift_entry_batch(request):
    """批量标记产线班次已录入（按产线+班次精确勾选）"""
    date = _parse_date(request.POST.get('date'), timezone.localdate())
    user = request.user if request.user.is_authenticated else None
    n = 0
    for pair in request.POST.getlist('tiles'):
        pid, _, shift = pair.partition(':')
        if not pid.isdigit() or shift not in (ShiftEntry.SHIFT_DAY, ShiftEntry.SHIFT_NIGHT):
            continue
        line = ProductionLine.objects.filter(id=int(pid)).first()
        if not line:
            continue
        sample_time = datetime.time(8, 0) if shift == ShiftEntry.SHIFT_DAY else datetime.time(20, 0)
        shift_entry, created = ShiftEntry.objects.get_or_create(
            line=line, date=date, shift=shift,
            defaults={'entered_by': user, 'entered_at': timezone.now()})
        # 同步创建生产日报，默认明细：早班 08:00-20:00、晚班 20:00-次日08:00，类别 无效工时
        report, report_created = DailyReport.objects.get_or_create(
            line=line, sample_date=date, sample_time=sample_time,
            defaults={'created_by': user})
        if report_created or report.details.count() == 0:
            if shift == ShiftEntry.SHIFT_DAY:
                d_start, d_end = datetime.time(8, 0), datetime.time(20, 0)
            else:
                d_start, d_end = datetime.time(20, 0), datetime.time(8, 0)
            ReportDetail.objects.create(
                report=report, start_time=d_start, end_time=d_end, category='无效工时')
        if created:
            n += 1
    OperationLog.objects.create(user=user, action=f'批量标记班次已录入：{n}条（{date}）')
    messages.success(request, f'已批量标记 {n} 条班次为已录入')
    params = {'date': date, 'batch': '1'}
    return redirect(f"{reverse('palladium:dashboard')}?{urlencode(params)}")


@require_POST
def concentration_batch_fill(request):
    """批量填写未检测：为勾选的产线班次创建未检测浓度记录（按产线+班次精确勾选）"""
    date = _parse_date(request.POST.get('date'), timezone.localdate())
    user = request.user if request.user.is_authenticated else None
    n = 0
    for pair in request.POST.getlist('tiles'):
        pid, _, shift = pair.partition(':')
        if not pid.isdigit() or shift not in (ShiftEntry.SHIFT_DAY, ShiftEntry.SHIFT_NIGHT):
            continue
        line = ProductionLine.objects.filter(id=int(pid)).first()
        if not line:
            continue
        sample_time = datetime.time(8, 0) if shift == ShiftEntry.SHIFT_DAY else datetime.time(20, 0)
        if ConcentrationRecord.objects.filter(
                line=line, sample_date=date, sample_time=sample_time).exists():
            continue
        record = ConcentrationRecord.objects.create(
            line=line, sample_date=date, sample_time=sample_time, created_by=user)
        for slot in line.slots.all():
            ConcentrationSlot.objects.create(
                record=record, slot_no=slot.slot_no, slot_type=slot.slot_type,
                slot_name=slot.name,
                chemical=slot.chemical_system.name if slot.chemical_system else '',
                open_status='无', test_status='未检测', concentration='0',
                liquid_level='0', liters=slot.std_volume, gold_salt='0')
        n += 1
    OperationLog.objects.create(user=user, action=f'批量填写未检测浓度：{n}条（{date}）')
    messages.success(request, f'已批量填写 {n} 条未检测浓度数据')
    params = {'c_date': date, 'batch': '2'}
    return redirect(f"{reverse('palladium:dashboard')}?{urlencode(params)}")


@require_POST
def shift_entry_clear(request):
    """批量清空：删除勾选班次的录入标记和生产日报数据"""
    date = _parse_date(request.POST.get('date'), timezone.localdate())
    user = request.user if request.user.is_authenticated else None
    n_entries = 0
    n_reports = 0
    names = []
    for pair in request.POST.getlist('tiles'):
        pid, _, shift = pair.partition(':')
        if not pid.isdigit() or shift not in (ShiftEntry.SHIFT_DAY, ShiftEntry.SHIFT_NIGHT):
            continue
        line = ProductionLine.objects.filter(id=int(pid)).first()
        if not line:
            continue
        if shift == ShiftEntry.SHIFT_DAY:
            reports = DailyReport.objects.filter(line=line, sample_date=date, sample_time__hour__lt=12)
        else:
            reports = DailyReport.objects.filter(line=line, sample_date=date, sample_time__hour__gte=12)
        n_reports += reports.count()
        reports.delete()
        n_entries += ShiftEntry.objects.filter(line=line, date=date, shift=shift).delete()[0]
        names.append(line.name)
    OperationLog.objects.create(
        user=user, action=f'批量清空班次录入：{names}（日报{n_reports}条）')
    messages.success(request, f'已清空 {names} 的班次录入数据（含日报 {n_reports} 条）')
    params = {'date': date, 'batch': '1'}
    return redirect(f"{reverse('palladium:dashboard')}?{urlencode(params)}")


@require_POST
def concentration_clear(request):
    """批量清空：删除勾选班次的浓度记录数据"""
    date = _parse_date(request.POST.get('date'), timezone.localdate())
    user = request.user if request.user.is_authenticated else None
    n = 0
    names = []
    for pair in request.POST.getlist('tiles'):
        pid, _, shift = pair.partition(':')
        if not pid.isdigit() or shift not in (ShiftEntry.SHIFT_DAY, ShiftEntry.SHIFT_NIGHT):
            continue
        line = ProductionLine.objects.filter(id=int(pid)).first()
        if not line:
            continue
        if shift == ShiftEntry.SHIFT_DAY:
            records = ConcentrationRecord.objects.filter(line=line, sample_date=date, sample_time__hour__lt=12)
        else:
            records = ConcentrationRecord.objects.filter(line=line, sample_date=date, sample_time__hour__gte=12)
        n += records.count()
        names.append(line.name)
        records.delete()
    OperationLog.objects.create(
        user=user, action=f'批量清空浓度数据：{names}（{n}条）')
    messages.success(request, f'已清空 {names} 的浓度数据（{n} 条）')
    params = {'c_date': date, 'batch': '2'}
    return redirect(f"{reverse('palladium:dashboard')}?{urlencode(params)}")



def qline_stats(request):
    """Q线镀钯和钯盐每日统计：镀钯槽逐日深度报表"""
    today = timezone.localdate()
    start = _parse_date(request.GET.get('start'), today.replace(day=1))
    end = _parse_date(request.GET.get('end'), today - datetime.timedelta(days=1))
    selected_ids = {int(x) for x in request.GET.getlist('lines') if x.isdigit()}
    queried = request.GET.get('queried') == '1'
    export = request.GET.get('export') == '1'

    lines = list(ProductionLine.objects.order_by('id'))
    sel_lines = [l for l in lines if l.id in selected_ids] or list(lines)

    columns = []
    rows = []
    has_data = False

    if sel_lines and start and end and start <= end:
        span = min((end - start).days, 61)
        dates = [start + datetime.timedelta(days=i) for i in range(span + 1)]
        cell = {}
        line_cols = {}
        for line in sel_lines:
            recs = {}
            for r in ConcentrationRecord.objects.filter(line=line, sample_date__range=(start, end)).order_by('sample_time'):
                recs.setdefault(r.sample_date, r)
            for r in recs.values():
                for sl in r.slot_rows.all():
                    line_cols.setdefault(line.id, {}).setdefault(sl.slot_no, (sl.slot_type, sl.slot_name))
                    cell[(line.id, sl.slot_no, r.sample_date)] = str(sl.liquid_level or '').strip()
            if not line_cols.get(line.id):
                prev = ConcentrationRecord.objects.filter(line=line, sample_date__lt=start).order_by('-sample_date').first()
                if prev:
                    for sl in prev.slot_rows.all():
                        line_cols.setdefault(line.id, {}).setdefault(sl.slot_no, (sl.slot_type, sl.slot_name))

        for line in sel_lines:
            slots = line_cols.get(line.id, {})
            if not slots:
                continue
            carry = {}
            init = ConcentrationRecord.objects.filter(line=line, sample_date__lt=start).order_by('-sample_date', 'sample_time').first()
            if init:
                for sl in init.slot_rows.all():
                    carry[sl.slot_no] = str(sl.liquid_level or '').strip()
            for d in dates:
                for no, (st, sn) in sorted(slots.items()):
                    v = cell.get((line.id, no, d))
                    if v is None:
                        v = carry.get(no, '')
                    elif v:
                        carry[no] = v
                    cell[(line.id, no, ('row', d))] = v

        for line in sel_lines:
            for no, (st, sn) in sorted(line_cols.get(line.id, {}).items()):
                columns.append({'key': str(line.id) + ':' + str(no), 'label': line.name + ' ' + (sn or st)})
        for d in dates:
            vals = []
            for line in sel_lines:
                for no, (st, sn) in sorted(line_cols.get(line.id, {}).items()):
                    vals.append(cell.get((line.id, no, ('row', d))) or '')
            rows.append({'date': d, 'vals': vals})
        has_data = any(v for r in rows for v in r['vals'])

    if export:
        from .qline_export import build_qline_workbook
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename=qline_depth_' + str(today.strftime('%Y%m%d')) + '.xlsx'
        wb = build_qline_workbook(sel_lines, start, end,
                                  request.user if request.user.is_authenticated else None)
        wb.save(response)
        return response

    context = {
        'page_title': 'Q线镀钯和钯盐每日统计',
        'lines': lines,
        'start': request.GET.get('start') or '',
        'end': request.GET.get('end') or '',
        'selected_ids': selected_ids,
        'columns': columns,
        'rows': rows,
        'has_data': has_data,
        'queried': queried,
    }
    return render(request, 'palladium/qline_stats.html', context)


def line_toggle_page(request):
    """启用/关闭产线"""
    lines = ProductionLine.objects.all()
    return render(request, 'palladium/line_toggle.html', {
        'page_title': '启用/关闭产线',
        'lines': lines,
    })


@require_POST
def line_toggle(request, pk):
    """切换单条产线启用状态"""
    line = get_object_or_404(ProductionLine, pk=pk)
    line.is_active = not line.is_active
    line.save()
    user = request.user if request.user.is_authenticated else None
    OperationLog.objects.create(
        user=user,
        action=f'{"启用" if line.is_active else "关闭"}产线：{line.name}',
    )
    return JsonResponse({'ok': True, 'active': line.is_active})


@require_POST
def line_toggle_all(request):
    """批量启用/关闭所有产线"""
    action = request.POST.get('action')
    if action not in ('on', 'off'):
        messages.error(request, '无效的操作')
        return redirect('palladium:line_toggle_page')
    n = ProductionLine.objects.update(is_active=(action == 'on'))
    user = request.user if request.user.is_authenticated else None
    OperationLog.objects.create(
        user=user,
        action=f'批量{"启用" if action == "on" else "关闭"}所有产线（{n}条）',
    )
    messages.success(request, f'已{"启用" if action == "on" else "关闭"}全部 {n} 条产线')
    return redirect('palladium:line_toggle_page')


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


def api_part_check(request):
    """料号校验：是否存在 / 是否属于指定产线"""
    part_no = (request.GET.get('part_no') or '').strip()
    line_id = request.GET.get('line') or ''
    if not part_no:
        return JsonResponse({'status': 'empty'})
    product = Product.objects.filter(part_no=part_no).first()
    if not product:
        return JsonResponse({'status': 'not_found'})
    on_line = ProductLineConfig.objects.filter(product=product, line_id=line_id).exists()
    customer = product.customer.name if product.customer else ''
    return JsonResponse({'status': 'exists', 'on_line': on_line, 'customer': customer})


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
