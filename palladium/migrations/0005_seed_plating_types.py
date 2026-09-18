"""（已清空）镀种种子迁移：保留迁移记录，不再写入任何数据"""
from django.db import migrations


def seed(apps, schema_editor):
    pass


def unseed(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('palladium', '0004_chemicalsystem_platingtype_productionline_floor_and_more'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
