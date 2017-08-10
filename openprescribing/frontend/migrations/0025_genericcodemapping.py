# -*- coding: utf-8 -*-
# Generated by Django 1.9.1 on 2017-06-14 16:13
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('frontend', '0024_ppusaving'),
    ]

    operations = [
        migrations.CreateModel(
            name='GenericCodeMapping',
            fields=[
                ('from_code', models.CharField(db_index=True, max_length=15, primary_key=True, serialize=False, validators=[django.core.validators.RegexValidator(b'^[\\w]*$', code=b'Invalid name', message=b'name must be alphanumeric')])),
                ('to_code', models.CharField(db_index=True, max_length=15, validators=[django.core.validators.RegexValidator(b'^[\\w]*$', code=b'Invalid name', message=b'name must be alphanumeric')])),
            ],
        ),
    ]
