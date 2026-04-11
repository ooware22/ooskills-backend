import os
import django
import traceback

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ooskillsbackend.settings')
django.setup()

from formation.services.zip_import_service import import_course_from_zip
from django.db import transaction

zip_path = r'd:\Users\pc\ooskills\ooskills-backend\ooskillsbackend\performance_tests\Travail en Équipe et Collaboration Professionnelle_COMPLET.zip'

try:
    with transaction.atomic():
        c = import_course_from_zip(zip_path)
        print('SUCCESS:', c)
        raise Exception('ROLLBACK')
except Exception as e:
    if str(e) != 'ROLLBACK':
        traceback.print_exc()
