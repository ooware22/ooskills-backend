# Data migration: convert old lowercase section type values to new uppercase short codes

from django.db import migrations


OLD_TO_NEW = {
    'teaser': 'TEASER',
    'introduction': 'INTRO',
    'initialisation': 'INIT',
    'approfondissement': 'APPRO',
    'etude_de_cas': 'CAS',
    'conclusion': 'CONCL',
    'module': 'APPRO',   # legacy catch-all → APPRO
}


def convert_types_forward(apps, schema_editor):
    Section = apps.get_model('formation', 'Section')
    for old_val, new_val in OLD_TO_NEW.items():
        Section.objects.filter(type=old_val).update(type=new_val)


def convert_types_backward(apps, schema_editor):
    Section = apps.get_model('formation', 'Section')
    for old_val, new_val in OLD_TO_NEW.items():
        Section.objects.filter(type=new_val).update(type=old_val)


class Migration(migrations.Migration):

    dependencies = [
        ('formation', '0025_section_type_uppercase'),
    ]

    operations = [
        migrations.RunPython(convert_types_forward, convert_types_backward),
    ]
