"""Show contact@ooskills.com as the site's contact address.

The public site settings showed a personal Gmail address (or nothing). Only
those two values are replaced: an address set on purpose in the admin
panel is kept.
"""
from django.db import migrations

NEW = 'contact@ooskills.com'
REPLACED = ('', 'sbboxmail3@gmail.com')


def forwards(apps, schema_editor):
    SiteSettings = apps.get_model('content', 'SiteSettings')
    SiteSettings.objects.filter(contact_email__in=REPLACED).update(contact_email=NEW)


class Migration(migrations.Migration):
    dependencies = [('content', '0009_countdownsection')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
