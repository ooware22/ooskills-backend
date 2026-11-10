"""
Export courses to a CSV ready for skill tagging.

Usage:
    python manage.py export_course_skills course_skills.csv
    python manage.py export_course_skills course_skills.csv --all-statuses

Columns: course_slug, status, title, what_you_learn, skills.
Fill the ``skills`` column with a JSON array of keywords from
formation/data/skill_keywords_fr.csv, then load it back with
``import_course_skills``.
"""

import csv
import json

from django.core.management.base import BaseCommand

from formation.models import Course, CourseStatus


class Command(BaseCommand):
    help = 'Export courses (slug, title, whatYouLearn, current skills) to a CSV for tagging'

    def add_arguments(self, parser):
        parser.add_argument('path', type=str, help='CSV file to write')
        parser.add_argument('--all-statuses', action='store_true',
                            help='Include draft and archived courses (default: published only)')

    def handle(self, *args, **options):
        qs = Course.objects.order_by('slug')
        if not options['all_statuses']:
            qs = qs.filter(status=CourseStatus.PUBLISHED)

        with open(options['path'], 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['course_slug', 'status', 'title', 'what_you_learn', 'skills'])
            count = 0
            for course in qs:
                writer.writerow([
                    course.slug, course.status, course.title,
                    ' | '.join(str(item) for item in (course.whatYouLearn or [])),
                    json.dumps(course.skills or [], ensure_ascii=False),
                ])
                count += 1

        self.stdout.write(self.style.SUCCESS(f'Exported {count} courses to {options["path"]}'))
