# -*- coding: utf-8 -*-
# Generated by Django 1.11.20 on 2019-06-27 09:29


from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('frontend', '0049_on_delete_protect'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ncsoconcession',
            name='vmpp',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='dmd.VMPP'),
        ),
        migrations.AlterField(
            model_name='tariffprice',
            name='tariff_category',
            field=models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, to='dmd.DtPaymentCategory'),
        ),
        migrations.AlterField(
            model_name='tariffprice',
            name='vmpp',
            field=models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, to='dmd.VMPP'),
        ),
    ]
