"""Q线镀钯和钯盐每日统计：按金盐手工输入格式导出（每线一表 + 钯盐每日统计）"""
import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from django.utils import timezone

from .models import ConcentrationRecord, DailyReport, ProductLineConfig

YELLOW = PatternFill('solid', fgColor='FFF2A8')
GRAY = PatternFill('solid', fgColor='EDEDED')
THIN = Border(*[Side(style='thin', color='B0B0B0')] * 4)
CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _shift_of(sample_time):
    return 'day' if sample_time.hour < 12 else 'night'


def build_qline_workbook(sel_lines, start, end, created_by):
    """生成工作簿：每条产线一个工作表 + 钯盐每日统计表"""
    wb = Workbook()
    wb.remove(wb.active)
    span = min((end - start).days, 92) + 1
    dates = [start + datetime.timedelta(days=i) for i in range(span)]

    sheet_infos = []
    for line in sel_lines:
        info = _build_line_sheet(wb, line, dates, start, created_by)
        sheet_infos.append(info)

    _build_stats_sheet(wb, sheet_infos, dates)
    if not wb.sheetnames:
        ws = wb.create_sheet('无数据')
        ws['A1'] = '所选日期范围内暂无数据'
    return wb


def _week_blocks(dates):
    """按7天切块：[(首idx, 末idx, '第N周汇总')]"""
    blocks = []
    i = 0
    n = 1
    while i < len(dates):
        j = min(i + 6, len(dates) - 1)
        blocks.append((i, j, f'第{n}周汇总'))
        n += 1
        i = j + 1
    return blocks


def _build_line_sheet(wb, line, dates, start, created_by):
    ws = wb.create_sheet(f"{line.name}（镀钯）"[:31])

    pd_slot = line.slots.filter(slot_type='镀钯').order_by('slot_no').first()
    ni_slot = line.slots.filter(slot_type='镀镍').order_by('slot_no').first()

    vol = _f(pd_slot.std_volume) if pd_slot else 0.0        # 槽体积
    cv = _f(pd_slot.control_value) if pd_slot else 0.0      # 管控中心值

    # 列布局：日期双班列 + 周汇总列 + 半月/整月汇总列
    layout = []  # [('date', d, shift) / ('sum', label, first_idx, last_idx)]
    blocks = _week_blocks(dates)
    for i0, i1, wlabel in blocks:
        for d in dates[i0:i1 + 1]:
            layout.append(('date', d, 'day'))
            layout.append(('date', d, 'night'))
        layout.append(('sum', wlabel, i0, i1))
    half = len(dates) // 2
    if half:
        layout.append(('sum', '上半月汇总', 0, half - 1))
    layout.append(('sum', '下半月汇总', half, len(dates) - 1))
    layout.append(('sum', '整月汇总', 0, len(dates) - 1))

    col_start = 6  # F 列起（A客户 B标准发行日期 C标准耗钯量 D名称 E项目）
    col_index = {}  # (date, shift) -> 列号；汇总列label -> 列号
    ci = col_start
    for item in layout:
        if item[0] == 'date':
            col_index[(item[1], item[2])] = ci
        else:
            col_index[item[1]] = ci
        ci += 1
    total_cols = ci - col_start

    # ===== 数据收集 =====
    rec_map, rep_map = {}, {}
    for r in ConcentrationRecord.objects.filter(line=line, sample_date__range=(dates[0], dates[-1])):
        rec_map[(r.sample_date, _shift_of(r.sample_time))] = r
    for r in DailyReport.objects.filter(line=line, sample_date__range=(dates[0], dates[-1])):
        rep_map[(r.sample_date, _shift_of(r.sample_time))] = r

    # 逐班有效记录：该班有“检测”数据用该班；否则沿用之前最近一次“检测”的记录
    # （批量生成的未检测占位记录不算新数据）
    eff_by_col = {}
    last_real = None
    for key, cc in sorted(col_index.items(), key=lambda kv: kv[1]):
        if not isinstance(key, tuple):
            continue
        d, shift = key
        rec = rec_map.get((d, shift))
        if rec and rec.slot_rows.filter(test_status='检测').exists():
            eff_by_col[(d, shift)] = rec
            last_real = rec
        elif last_real is not None:
            eff_by_col[(d, shift)] = last_real
        elif rec:
            eff_by_col[(d, shift)] = rec

    configs = {}
    for c in ProductLineConfig.objects.filter(line=line).select_related('product', 'product__customer'):
        try:
            std = float(c.std_gold_usage)
        except (TypeError, ValueError):
            std = 0.0
        configs[c.product.part_no] = (c.product.customer.name if c.product.customer else '', std)

    col_vals = {}  # (date, shift) -> dict
    for (d, shift) in [k for k in col_index if isinstance(k, tuple)]:
        rec = eff_by_col.get((d, shift))
        rep = rep_map.get((d, shift))

        def row_of(slot):
            if rec and slot:
                return rec.slot_rows.filter(slot_no=slot.slot_no).first()
            return None

        pd_row = row_of(pd_slot)
        ni_row = row_of(ni_slot)
        col_vals[(d, shift)] = {
            'analyst': rec.analyst if rec else '',
            'conc_pd': _f(pd_row.concentration) if pd_row else None,
            'conc_ni': _f(ni_row.concentration) if ni_row else None,
            'grass_pd': (pd_row.grass_type or '无') if pd_row else '无',
            'grass_ni': (ni_row.grass_type or '无') if ni_row else '无',
            'liq_pd': (pd_row.liquid_level or '') if pd_row else '',
            'liq_ni': (ni_row.liquid_level or '') if ni_row else '',
            'salt': _f(pd_row.gold_salt) if pd_row and pd_row.gold_salt else 0.0,
            'usage': 0.0,
            'prod': {},
        }
        if rep:
            for det in rep.details.all():
                qty = _f(det.quantity)
                cfg = configs.get(det.part_no)
                std = cfg[1] if cfg else 0.0
                col_vals[(d, shift)]['usage'] += qty * std
                col_vals[(d, shift)]['prod'][det.part_no] = col_vals[(d, shift)]['prod'].get(det.part_no, 0.0) + qty

    # ===== 写入工作表 =====
    ws.cell(row=1, column=1, value='客户')
    ws.cell(row=1, column=2, value='标准发行日期')
    ws.cell(row=1, column=3, value='标准耗钯量')
    ws.cell(row=1, column=4, value='名称')
    ws.cell(row=1, column=5, value='项目')

    ws.cell(row=2, column=4, value='班次时间')
    ws.cell(row=3, column=2, value=start)
    ws.cell(row=3, column=2).number_format = 'yyyy-mm-dd'
    ws.cell(row=3, column=3, value='钯镍')
    ws.cell(row=3, column=4, value='分析员')

    label_pd = f"{line.name}刷钯镍（Pd钯）({cv:g}g/L*{vol:g}L)"
    label_status = f"{line.name}钯镍（Pd钯）槽位状况{vol:g}L 1CM={cv:g}L"
    ws.cell(row=4, column=4, value=label_pd)
    ws.cell(row=5, column=4, value='镍浓度')
    ws.cell(row=6, column=4, value=label_status)
    ws.cell(row=8, column=4, value='添加（Pd钯）盐量(g)')
    ws.cell(row=8, column=5, value=f"{line.name}钯镍")
    ws.cell(row=9, column=4, value='（Pd钯）标准耗用量')
    ws.cell(row=10, column=4, value='当班盈亏值(g)')
    ws.cell(row=11, column=4, value='当班盈亏率(%)')
    ws.cell(row=12, column=4, value='累计盈亏值')

    # 日期列与汇总列填充
    for item in layout:
        if item[0] == 'date':
            d, shift = item[1], item[2]
            cc = col_index[(d, shift)]
            c1 = ws.cell(row=1, column=cc)
            c1.value = d
            c1.number_format = 'M"月"D"日"'
            ws.cell(row=2, column=cc, value='8:00-20:00' if shift == 'day' else '20:00-8:00')
            v = col_vals.get((d, shift))
            if v is None:
                raise KeyError(f'写入时缺失: {d} {shift}，col_vals共{len(col_vals)}项，键样例: {list(col_vals.keys())[:3]}')
            ws.cell(row=3, column=cc, value=v.get('analyst', ''))
            ws.cell(row=4, column=cc, value=(round(v['conc_pd'], 3) if v['conc_pd'] is not None else ''))
            ws.cell(row=4, column=cc).number_format = '0.000'
            ws.cell(row=5, column=cc, value=(round(v['conc_ni'], 3) if v['conc_ni'] is not None else ''))
            ws.cell(row=5, column=cc).number_format = '0.000'
            ws.cell(row=6, column=cc, value=(f"{v['grass_pd']}-{v['liq_pd']}" if v['liq_pd'] else v['grass_pd']))
            ws.cell(row=7, column=cc, value=(f"{v['grass_ni']}-{v['liq_ni']}" if v['liq_ni'] else v['grass_ni']))
            ws.cell(row=8, column=cc, value=(round(v['salt'], 2) if v['salt'] is not None else ''))
            ws.cell(row=8, column=cc).number_format = '0.00'
            ws.cell(row=9, column=cc, value=round(v['usage'], 2))
            ws.cell(row=9, column=cc).number_format = '0.00'
        else:
            label, i0, i1 = item[1], item[2], item[3]
            cc = col_index[label]
            ws.cell(row=1, column=cc, value=label)
            f0 = get_column_letter(col_index[(dates[i0], 'day')])
            f1 = get_column_letter(col_index[(dates[i1], 'night')])
            for r in (8, 9, 10):
                cell = ws.cell(row=r, column=cc, value=f"=SUM({f0}{r}:{f1}{r})")
                cell.number_format = '0.00'
            ws.cell(row=11, column=cc, value='-')
            # 汇总列本身即一个周区间，累计值等于本列周合计
            cell12 = ws.cell(row=12, column=cc, value=f"={get_column_letter(cc)}10")
            cell12.number_format = '0.00'

    # 盈亏值公式：后一天浓度×槽体积 − 本列浓度×槽体积 − 盐量 + 耗用量
    # “后一天”引用遇到汇总列自动跳过（末列用本列浓度）
    date_items = sorted(((key, cc) for key, cc in col_index.items() if isinstance(key, tuple)),
                        key=lambda kv: kv[1])
    for i, (key, cc) in enumerate(date_items):
        d, shift = key
        v = col_vals.get((d, shift), {})
        cur_conc = f"{get_column_letter(cc)}4"
        salt = f"{get_column_letter(cc)}8"
        usage = f"{get_column_letter(cc)}9"
        # 各天调整后槽体积 = 原槽位体积 + 液位×浮动单元值（液位保留正负号）
        liq_cur = _f(v.get('liq_pd'))
        flt = _f(pd_slot.float_value) if pd_slot else 0.0
        vol_adj_cur = vol + liq_cur * flt
        if i + 1 < len(date_items):
            nkey = date_items[i + 1][0]
            liq_next = _f(col_vals.get(nkey, {}).get('liq_pd'))
            vol_adj_next = vol + liq_next * flt
            next_conc = f"{get_column_letter(date_items[i + 1][1])}4"
        else:
            next_conc = cur_conc
            vol_adj_next = vol_adj_cur
        cell10 = ws.cell(row=10, column=cc,
                value=f"=({next_conc}*{vol_adj_next:g}-{cur_conc}*{vol_adj_cur:g})-{salt}+{usage}")
        cell10.number_format = '0.00'

    # 累计盈亏：一周为一个界限，每周清零重新累计
    prev_letter = 'E'
    prev_week = None
    for i, (key, cc) in enumerate(date_items):
        d, shift = key
        # 每天2个班次列，7天一周 = 14列，清零点与“第N周汇总”列对齐
        week = i // 14
        if prev_week is not None and week == prev_week:
            cell = ws.cell(row=12, column=cc, value=f"={prev_letter}12+{get_column_letter(cc)}10")
        else:
            cell = ws.cell(row=12, column=cc, value=f"={get_column_letter(cc)}10")
        cell.number_format = '0.00'
        prev_letter = get_column_letter(cc)
        prev_week = week

    # 产品行：客户 / 标准耗钯量 / 料号 + 每班生产数
    part_row = {}
    pr = 13
    for part_no, (cust, std) in configs.items():
        ws.cell(row=pr, column=1, value=cust)
        ws.cell(row=pr, column=3, value=std)
        ws.cell(row=pr, column=3).number_format = '0.0000'
        ws.cell(row=pr, column=4, value=part_no)
        ws.cell(row=pr, column=5, value='生产数')
        part_row[part_no] = pr
        pr += 1

    for (d, shift), cc in [kv for kv in sorted(col_index.items(), key=lambda kv: kv[1]) if isinstance(kv[0], datetime.date)]:
        v = col_vals.get((d, shift), {})
        for part_no, qty in v['prod'].items():
            r = part_row.get(part_no)
            if r:
                ws.cell(row=r, column=cc, value=round(qty, 2))
                ws.cell(row=r, column=cc).number_format = '0.00'

    # ===== 样式 =====
    ws.column_dimensions['A'].width = 10
    ws.column_dimensions['B'].width = 14
    ws.column_dimensions['C'].width = 12
    ws.column_dimensions['D'].width = 26
    ws.column_dimensions['E'].width = 10
    for item in layout:
        if item[0] == 'date':
            cc = col_index[(item[1], item[2])]
        else:
            cc = col_index[item[1]]
        ws.column_dimensions[get_column_letter(cc)].width = 13
    max_r = max(pr + 1, 14)
    for r in range(1, max_r + 1):
        for cc in range(1, total_cols + col_start):
            cell = ws.cell(row=r, column=cc)
            cell.border = THIN
            cell.alignment = CENTER
    for r in (1, 2, 3):
        for cc in range(1, total_cols + col_start):
            ws.cell(row=r, column=cc).fill = GRAY
            ws.cell(row=r, column=cc).font = Font(bold=True)
    for r in range(4, 9):
        for cc in range(1, 5):
            ws.cell(row=r, column=cc).fill = YELLOW
    ws.freeze_panes = 'F4'

    # 引用信息（供钯盐每日统计汇总块引用）
    refs = {}
    for key, cc in col_index.items():
        if isinstance(key, datetime.date):
            refs[key] = get_column_letter(cc)
    return {
        'sheet': ws.title,
        'line': line,
        'refs': refs,                     # (date, shift) -> 列字母
        'loss_row': 10, 'usage_row': 9,
        'salt_row': 8, 'cum_row': 12,
    }


def _build_stats_sheet(wb, sheet_infos, dates):
    """钯盐每日统计：盈亏% 块 + 钯盐每日汇总块"""
    ws = wb.create_sheet('钯盐每日统计')
    today = timezone.localdate()

    ws.cell(row=1, column=2, value=f"{dates[0].month}月钯盐盈亏%")

    # 块一：截止到当天的盈亏%
    ws.cell(row=2, column=2, value='截止日期')
    ws.cell(row=2, column=3, value='标准耗用量(g)')
    ws.cell(row=2, column=4, value='当班盈亏值(g)')
    ws.cell(row=2, column=5, value='本月截止到当天的盈亏%')
    ws.cell(row=3, column=2, value=today)
    ws.cell(row=3, column=2).number_format = 'yyyy-mm-dd'

    r = 4
    for info in sheet_infos:
        sh = f"'{info['sheet']}'"
        last = get_column_letter(max(info['refs'].values())) if info['refs'] else 'F'
        ws.cell(row=r, column=2, value=f"{info['line'].name}线")
        cell_c = ws.cell(row=r, column=3, value=f"={sh}!{last}{info['cum_row']}")
        cell_c.number_format = '0.00'
        cell_d = ws.cell(row=r, column=4, value=f"={sh}!{last}{info['loss_row']}")
        cell_d.number_format = '0.00'
        ws.cell(row=r, column=5, value=f"=IF(C{r}=0,'',D{r}/C{r})")
        ws.cell(row=r, column=5).number_format = '0.00%'
        r += 1
    ws.cell(row=r, column=2, value='合计')
    first_data = 4
    cell_c = ws.cell(row=r, column=3, value=f"=SUM(C{first_data}:C{r - 1})")
    cell_c.number_format = '0.00'
    cell_d = ws.cell(row=r, column=4, value=f"=SUM(D{first_data}:D{r - 1})")
    cell_d.number_format = '0.00'
    ws.cell(row=r, column=5, value=f"=IF(C{r}=0,'',D{r}/C{r})")
    ws.cell(row=r, column=5).number_format = '0.00%'

    # 块二：钯盐每日汇总
    head = r + 2
    ws.cell(row=head - 1, column=2, value='钯盐每日汇总')
    ws.cell(row=head, column=3, value='亏钯检讨标准')
    ws.cell(row=head, column=4, value='线别/日期')
    shift_cols = []  # (date, shift)
    for d in dates:
        for shift, sl in (('day', '早'), ('night', '晚')):
            shift_cols.append((d, shift, f"{d.month}/{d.day}{sl}"))
    cc = 5
    for (d, shift, sl) in shift_cols:
        ws.cell(row=head, column=cc, value=sl)
        cc += 1

    row = head + 1
    ws.cell(row=row, column=2, value='盈钯量')
    for info in sheet_infos:
        sh = f"'{info['sheet']}'"
        ws.cell(row=row, column=4, value=f"{info['line'].name}线")
        cc = 5
        for (d, shift, sl) in shift_cols:
            letter = info['refs'].get((d, shift))
            ws.cell(row=row, column=cc, value=f"={sh}!{letter}{info['loss_row']}" if letter else '')
            cc += 1
        row += 1
    sum_row = row
    ws.cell(row=sum_row, column=3, value='盈钯量合计')
    cc = 5
    for (d, shift, sl) in shift_cols:
        col = get_column_letter(cc)
        cell = ws.cell(row=sum_row, column=cc, value=f"=SUM({col}{head + 1}:{col}{row - 1})")
        cell.number_format = '0.00'
        cc += 1
    row = sum_row + 1
    ws.cell(row=row, column=2, value='标准钯用量')
    for info in sheet_infos:
        sh = f"'{info['sheet']}'"
        ws.cell(row=row, column=4, value=f"{info['line'].name}线")
        cc = 5
        for (d, shift, sl) in shift_cols:
            letter = info['refs'].get((d, shift))
            ws.cell(row=row, column=cc, value=f"={sh}!{letter}{info['usage_row']}" if letter else '')
            cc += 1
    row += 1
    sum_row2 = row
    ws.cell(row=sum_row2, column=3, value='标准钯用量合计')
    cc = 5
    for (d, shift, sl) in shift_cols:
        col = get_column_letter(cc)
        cell = ws.cell(row=sum_row2, column=cc, value=f"=SUM({col}{head + 1}:{col}{row - 1})")
        cell.number_format = '0.00'
        cc += 1

    # 样式
    ws.column_dimensions['A'].width = 4
    ws.column_dimensions['B'].width = 16
    ws.column_dimensions['C'].width = 16
    ws.column_dimensions['D'].width = 16
    for i in range(len(dates) * 2):
        ws.column_dimensions[get_column_letter(5 + i)].width = 10
    for r in range(1, sum_row2 + 2):
        for cc in range(2, 5 + len(dates) * 2):
            ws.cell(row=r, column=cc).border = THIN
            ws.cell(row=r, column=cc).alignment = CENTER
