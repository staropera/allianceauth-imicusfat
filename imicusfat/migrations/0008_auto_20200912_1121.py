# Generated by Django 2.2.15 on 2020-09-12 11:21

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("imicusfat", "0007_auto_20200826_1537"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="dellog",
            options={
                "default_permissions": (),
                "verbose_name": "Delete Log",
                "verbose_name_plural": "Delete Logs",
            },
        ),
        migrations.AlterModelOptions(
            name="ifat",
            options={"verbose_name": "FAT", "verbose_name_plural": "FATs"},
        ),
        migrations.AlterModelOptions(
            name="ifatlink",
            options={
                "ordering": ("-ifattime",),
                "permissions": (
                    ("manage_imicusfat", "Can manage the imicusfat module"),
                    ("stats_corp_own", "Can see own corp stats"),
                    ("stats_corp_other", "Can see stats of other corps."),
                    (
                        "stats_char_other",
                        "Can see stats of characters not associated with current user.",
                    ),
                ),
                "verbose_name": "FAT Link",
                "verbose_name_plural": "FAT Links",
            },
        ),
        migrations.AlterModelOptions(
            name="ifatlinktype",
            options={
                "default_permissions": (),
                "verbose_name": "FAT Link Type",
                "verbose_name_plural": "FAT Link Types",
            },
        ),
    ]
