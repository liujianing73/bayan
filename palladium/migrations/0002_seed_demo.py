"""（已清空）演示数据种子迁移：保留迁移记录，不再写入任何数据"""
from django.db import migrations


def seed(apps, schema_editor):
    pass


def unseed(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('palladium', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
