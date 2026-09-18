"""导入演示数据（覆盖产线/槽位/料号/生产日报/浓度数据等），可重复执行"""
import datetime
import random

from django.core.management.base import BaseCommand
from django.utils import timezone

from palladium.models import (
    ChemicalSystem, ConcentrationRecord, ConcentrationSlot, Customer,
    DailyReport, PlatingType, Product, ProductLineConfig, ProductionLine,
    ReportDetail, ReportSlotData, Slot, StandardParamConfig,
    StandardParamHistory,
)

TODAY = timezone.localdate()


def dt(h, m=0):
    return datetime.time(h, m)


class Command(BaseCommand):
    help = '导入演示数据（重复执行会跳过已存在的数据）'

    def handle(self, *args, **options):
        created = []

        # 用户（仅用于"输入人员"显示）
        from django.contrib.auth.models import User
        u1 = User.objects.filter(username='吴肖竺').first() or User.objects.create_user('吴肖竺')
        u1.set_unusable_password()
        u1.save()
        u2 = User.objects.filter(username='刘佳宁').first() or User.objects.create_user('刘佳宁')
        u2.set_unusable_password()
        u2.save()

        # 镀种 / 化学体系
        for name in ['不锈钢镀金', '铜材镀锡', '铜材镀金', '钯', '金']:
            PlatingType.objects.get_or_create(name=name)
        for name in ['K-186S', 'K-1410CB']:
            ChemicalSystem.objects.get_or_create(name=name)
        chem = {c.name: c for c in ChemicalSystem.objects.all()}
        plating = {p.name: p for p in PlatingType.objects.all()}

        # 产线 + 槽位
        lines_spec = [
            # (名称, 编号, 楼层, 镀种, 创建人, [(槽位编号, 类型, 名称, 化学体系, 体积, 标准浓度, 浮动值)...])
            ('2E1', '260424', '车间2楼', '不锈钢镀金', u1, [
                (1, '选金', '1-3', 'K-186S', '100.00', '6.50', '4.20'),
                (2, '点镀', '1', 'K-1410CB', '140.00', '2.50', '4.80')]),
            ('2E2', '', '车间2楼', '不锈钢镀金', u1, []),
            ('2F', '', '车间1楼', '铜材镀锡', u2, []),
            ('2J', '', '车间2楼', '铜材镀金', u2, [
                (1, '选金', '2-1', 'K-186S', '110.00', '5.80', '4.00'),
                (2, '点镀', '2-2', 'K-1410CB', '150.00', '3.10', '4.50')]),
            ('2R1', '251210', '车间2楼', '铜材镀金', u1, [
                (1, '镀钯', 'R-1', 'K-186S', '90.00', '4.20', '3.80')]),
            ('2R2', '', '车间2楼', '铜材镀金', u1, [
                (1, '镀钯', 'R-2', 'K-1410CB', '95.00', '4.00', '3.90')]),
            ('K1', '', '车间2楼', '铜材镀锡', u1, [(1, '点镀', '1-2', 'K-1410CB', '170.00', '2.50', '4.80')]),
            ('K2', '', '车间2楼', '铜材镀锡', u1, [
                (1, '选金', '1-3', 'K-186S', '120.00', '6.00', '4.20'),
                (2, '点镀', '1-2', 'K-1410CB', '170.00', '2.70', '4.80')]),
            ('L1', '', '车间2楼', '不锈钢镀金', u1, [
                (1, '点镀', '1-2', 'K-1410CB', '167.60', '2.40', '4.60'),
                (2, '点镀', '3-4', 'K-1410CB', '170.00', '2.60', '4.80')]),
            ('L2', '', '车间2楼', '不锈钢镀金', u1, [
                (1, '点镀', '1-2', 'K-1410CB', '170.00', '2.50', '4.80'),
                (2, '点镀', '3-4', 'K-1410CB', '170.00', '2.50', '4.80')]),
            ('M', '', '车间1楼', '不锈钢镀金', u2, [(1, '点镀', '1-2', 'K-1410CB', '172.40', '2.80', '4.90')]),
        ]
        lines = {}
        for name, no, floor, pt, user, slots in lines_spec:
            line, c = ProductionLine.objects.get_or_create(
                name=name, line_no=no, defaults={
                    'floor': floor, 'plating_type': plating.get(pt), 'created_by': user})
            lines[name] = line
            if c:
                created.append(f'产线 {name}')
            for no_, st, sn, cs, vol, conc, fl in slots:
                Slot.objects.get_or_create(
                    line=line, slot_no=no_,
                    defaults={'sort_order': no_, 'slot_type': st, 'name': sn,
                              'chemical_system': chem.get(cs), 'std_volume': vol,
                              'std_concentration': conc, 'float_value': fl, 'created_by': user})

        # 客户 / 产品 / 产线参数配置
        for cname in ['鸿讯威', '层望', '信创', '艾锐博', '宏泽', '兴昂']:
            Customer.objects.get_or_create(name=cname)
        cust = {c.name: c for c in Customer.objects.all()}

        products_spec = [
            ('0.1*12', '鸿讯威', [('2E1', '0.03200', '1.30000')]),
            ('0.1*17.5', '层望', [('2E1', '0.00000', '0.00000')]),
            ('0.15*26', '信创', [('2E1', '0.00000', '0.00000')]),
            ('0.15*42', '信创', [('2E1', '0.00000', '0.00000')]),
            ('00AR25218-001', '艾锐博', [('2E2', '0.00000', '0.12000'), ('2J', '0.00000', '0.10000')]),
            ('010-A234-01', '鸿讯威', [('2J', '0.00000', '0.50000')]),
            ('042/043', '层望', []),  # 未配置产线参数（演示黄色警示行）
            ('042-043', '层望', [('2E2', '0.07400', '1.47000')]),
        ]
        for part_no, cname, cfgs in products_spec:
            p, c = Product.objects.get_or_create(
                part_no=part_no, defaults={'customer': cust.get(cname), 'created_by': u2})
            if c:
                created.append(f'料号 {part_no}')
            for lname, gold, cap in cfgs:
                ProductLineConfig.objects.get_or_create(
                    product=p, line=lines[lname],
                    defaults={'std_gold_usage': gold, 'std_capacity': cap})

        # 生产日报（每条产线今日 08:00 一条，线长/IPQC 部分留空）
        slot_data_pattern = [(1, '选金', '7.306', '0.50'), (2, '点镀', '2.316', '0.00')]
        leaders = ['刘广磊', '雷传好', '冯民', '蔡晓', '', '吴孟清']
        ipqcs = ['武蒙蒙', '顾宝进', '张强', '李艳', '', '任静静']
        for idx, (name, line) in enumerate(lines.items()):
            if DailyReport.objects.filter(line=line, sample_date=TODAY).exists():
                continue
            r = DailyReport.objects.create(
                line=line, sample_date=TODAY, sample_time=dt(8),
                line_leader=leaders[idx % len(leaders)],
                ipqc=ipqcs[idx % len(ipqcs)],
                created_by=u1)
            if name in ('2E1', '2J', '2R1', '2R2', 'K2', 'L1'):
                for no_, st, conc, liq in slot_data_pattern:
                    ReportSlotData.objects.create(
                        report=r, slot_no=no_, slot_type=st,
                        concentration=conc, liquid_level=liq, status='无')
            ReportDetail.objects.create(
                report=r, start_time=dt(8), end_time=dt(20), category='无效工时')
            created.append(f'生产日报 {name}')

        # 浓度数据记录（产线/槽位行，参照浓度查看截图）
        conc_spec = [
            ('K1', [(1, '镀镍', '1-2', 'K-1410CB', '0.000', '0.00', '', '未检测', '0', '')]),
            ('K2', [(1, '镀钯', '1-3', 'K-186S', '0.000', '0.00', '120.00', '检测', '0', ''),
                    (2, '镀镍', '1-2', 'K-1410CB', '0.000', '0.00', '170.00', '检测', '0', '')]),
            ('L1', [(1, '镀镍', '1-2', 'K-1410CB', '6.085', '-0.50', '167.60', '检测', '0', ''),
                    (2, '镀镍', '3-4', 'K-1410CB', '0.000', '0.00', '170.00', '未检测', '0', '')]),
            ('L2', [(1, '镀镍', '1-2', 'K-1410CB', '6.198', '0.00', '170.00', '检测', '0', ''),
                    (2, '镀镍', '3-4', 'K-1410CB', '2.016', '0.00', '170.00', '检测', '0', '')]),
            ('M', [(1, '镀镍', '1-2', 'K-1410CB', '7.388', '0.50', '172.40', '检测', '0', '')]),
            ('2E1', [(1, '镀钯', '1-3', 'K-186S', '7.306', '0.50', '100.00', '检测', '0', ''),
                     (2, '镀镍', '1', 'K-1410CB', '2.316', '0.00', '140.00', '检测', '0', '')]),
        ]
        for lname, slots in conc_spec:
            if ConcentrationRecord.objects.filter(line=lines[lname], sample_date=TODAY).exists():
                continue
            rec = ConcentrationRecord.objects.create(
                line=lines[lname], sample_date=TODAY, sample_time=dt(8), created_by=u1)
            for no_, st, sn, cs, conc, liq, liters, test, gold, _ in slots:
                ConcentrationSlot.objects.create(
                    record=rec, slot_no=no_, slot_type=st, slot_name=sn,
                    chemical=cs, open_status='无', test_status=test,
                    concentration=conc, liquid_level=liq, liters=liters, gold_salt=gold)
            created.append(f'浓度记录 {lname}')

        # 标准参数历史（料号+产线+生效时间）
        history_spec = [
            ('0.1*12', '2E1', '0.03200', '1.30000', '2026-08-01'),
            ('0.1*17.5', '2E1', '0.09700', '1.67000', '2026-08-01'),
            ('0.15*26', '2E2', '0.15400', '0.93000', '2026-08-01'),
            ('00AR25218-001', '2E2', '0.00000', '1.13000', '2026-08-01'),
            ('00AR25218-001', '2J', '0.03500', '3.80000', '2026-08-01'),
            ('010-A234-01', '2J', '0.10000', '1.50000', '2026-08-01'),
            ('042-043', '2E2', '0.05100', '2.25000', '2026-08-01'),
            ('0.1*12', '2J', '0.04600', '11.76000', '2026-09-01'),
            ('0.15*42', '2R1', '0.01600', '2.25000', '2026-08-01'),
            ('0.15*54', '2R2', '0.01000', '1.38000', '2026-08-01'),
        ]
        for part_no, lname, gold, cap, eff in history_spec:
            product = Product.objects.filter(part_no=part_no).first()
            line = lines.get(lname)
            if not product or not line:
                continue
            eff_date = datetime.date.fromisoformat(eff)
            exists = StandardParamConfig.objects.filter(
                history__product=product, line=line,
                history__effective_date=eff_date).exists()
            if exists:
                continue
            history = StandardParamHistory.objects.create(
                product=product, effective_date=eff_date, created_by=u1)
            StandardParamConfig.objects.create(
                history=history, line=line, std_gold_usage=gold, std_capacity=cap)
            created.append(f'标准参数历史 {part_no}@{lname}')

        self.stdout.write(self.style.SUCCESS(
            f'演示数据导入完成，新增 {len(created)} 项：\n' + '\n'.join(created)))
