"""槽位字段扩展：槽位编号、标准浓度、创建人；产线创建人"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def normalize_slots(apps, schema_editor):
    Slot = apps.get_model('palladium', 'Slot')
    for s in Slot.objects.all():
        if not s.slot_no:
            s.slot_no = s.sort_order or 1
        t = s.slot_type or ''
        if '钯' in t:
            s.slot_type = '镀钯'
        elif '金' in t:
            s.slot_type = '选金'
        elif '点镀' in t:
            s.slot_type = '点镀'
        s.save()


def unnormalize(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('palladium', '0008_product_created_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='slot', name='slot_no',
            field=models.PositiveIntegerField(default=1, verbose_name='槽位编号'),
        ),
        migrations.AddField(
            model_name='slot', name='std_concentration',
            field=models.CharField(blank=True, default='', max_length=50, verbose_name='标准浓度(g/L)'),
        ),
        migrations.AddField(
            model_name='slot', name='created_by',
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='slots', to=settings.AUTH_USER_MODEL, verbose_name='创建人'),
        ),
        migrations.AddField(
            model_name='productionline', name='created_by',
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='production_lines', to=settings.AUTH_USER_MODEL, verbose_name='创建人'),
        ),
        migrations.RunPython(normalize_slots, unnormalize),
        migrations.AlterUniqueTogether(
            name='slot',
            unique_together={('line', 'slot_no')},
        ),
    ]
