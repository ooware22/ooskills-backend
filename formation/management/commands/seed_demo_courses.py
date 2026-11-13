"""
Load demo categories and courses so staging can be tested end to end
(audit K01 / FN-01 / UX-01 / UX-28 / LAN-26): catalogue, course page,
free enrolment, paid checkout, lesson player, section quizzes, final exam
and certificate.

Every course is short (2 sections, 3 slides each, a quiz per section and a
final exam) and has no audio or image: it exists to test the flows, not to
be sold.

It refuses to run when ENVIRONMENT=production unless --force is given.
Safe to re-run: a category or course that already exists (same slug) is left
as it is, so edits made in the admin panel are kept.

    python manage.py seed_demo_courses           # create what is missing
    python manage.py seed_demo_courses --delete  # remove the demo courses
"""

from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from formation.models import (
    Category, Course, CourseLevel, CourseStatus, DisplayMode, FinalQuiz,
    Lesson, LessonType, Module, Quiz, QuizQuestion, Section, SectionType,
)

CATEGORIES = [
    # slug, icon, fr, en, ar
    ('gestion-de-projet', 'briefcase', 'Gestion de projet', 'Project management', 'إدارة المشاريع'),
    ('communication', 'globe', 'Communication', 'Communication', 'التواصل'),
    ('bureautique', 'chart', 'Bureautique', 'Office tools', 'المكتبيات'),
    ('developpement-personnel', 'lightbulb', 'Développement personnel', 'Personal development', 'التطوير الذاتي'),
]


def slide(title, *points):
    return (title, list(points))


def question(text, options, answer, explanation=''):
    return (text, options, answer, explanation)


COURSES = [
    dict(
        slug='demo-gestion-de-projet-les-bases',
        category='gestion-de-projet',
        title='Gestion de projet : les bases',
        language='Français',
        level=CourseLevel.INITIALISATION,
        is_free=True, original_price=0, price=0,
        skills=['Gestion de projets'],
        description=(
            'Formation de démonstration pour tester la plateforme. Les étapes d’un projet, '
            'le rôle du chef de projet et les outils simples pour suivre l’avancement.'
        ),
        prerequisites=['Aucun prérequis'],
        what_you_learn=[
            'Découper un projet en étapes',
            'Définir un objectif clair',
            'Suivre l’avancement avec un planning simple',
        ],
        sections=[
            (SectionType.INTRO, 'Comprendre un projet', [
                slide('Qu’est-ce qu’un projet ?',
                      'Un objectif précis', 'Un début et une fin', 'Des ressources limitées'),
                slide('Le rôle du chef de projet',
                      'Il organise le travail', 'Il fait le lien entre les personnes', 'Il suit les risques'),
                slide('Les quatre phases',
                      'Lancement', 'Planification', 'Réalisation', 'Clôture'),
            ], [
                question('Quelle est une caractéristique d’un projet ?',
                         ['Il n’a pas de fin', 'Il a un début et une fin', 'Il n’a pas d’objectif'], 1,
                         'Un projet est limité dans le temps.'),
                question('Qui organise le travail dans un projet ?',
                         ['Le client', 'Le chef de projet', 'Le fournisseur'], 1),
                question('Quelle phase vient après la planification ?',
                         ['La clôture', 'Le lancement', 'La réalisation'], 2),
                question('Un projet dispose de ressources illimitées.', ['Vrai', 'Faux'], 1),
            ]),
            (SectionType.INIT, 'Planifier et suivre', [
                slide('Un objectif SMART',
                      'Spécifique', 'Mesurable', 'Atteignable', 'Réaliste', 'Temporellement défini'),
                slide('Découper le travail',
                      'Lister les livrables', 'Découper en tâches', 'Estimer la durée de chaque tâche'),
                slide('Suivre l’avancement',
                      'Un planning partagé', 'Un point d’équipe chaque semaine', 'Des indicateurs simples'),
            ], [
                question('Que veut dire le M de SMART ?', ['Motivant', 'Mesurable', 'Moderne'], 1),
                question('Que fait-on après avoir listé les livrables ?',
                         ['On découpe en tâches', 'On clôture le projet', 'On recrute'], 0),
                question('Quel outil aide à suivre l’avancement ?',
                         ['Un planning partagé', 'Un logo', 'Une carte de visite'], 0),
                question('Un objectif SMART doit avoir une date.', ['Vrai', 'Faux'], 0),
            ]),
        ],
    ),
    dict(
        slug='demo-communication-professionnelle',
        category='communication',
        title='Communication professionnelle',
        language='Français',
        level=CourseLevel.APPROFONDISSEMENT,
        is_free=False, original_price=3500, price=2500,
        skills=['Communication'],
        description=(
            'Formation de démonstration (payante) pour tester le paiement. Écrire un e-mail clair, '
            'mener une réunion courte et donner un retour utile.'
        ),
        prerequisites=['Savoir écrire un e-mail simple'],
        what_you_learn=[
            'Écrire un e-mail professionnel clair',
            'Préparer et animer une réunion courte',
            'Donner un retour constructif',
        ],
        sections=[
            (SectionType.APPRO, 'Écrire et présenter', [
                slide('Un e-mail clair',
                      'Un objet précis', 'Une idée par paragraphe', 'Une demande explicite à la fin'),
                slide('Une réunion utile',
                      'Un ordre du jour envoyé avant', '30 minutes maximum', 'Un compte rendu après'),
                slide('Présenter une idée',
                      'Commencer par la conclusion', 'Trois arguments maximum', 'Finir par la prochaine étape'),
            ], [
                question('Que doit contenir l’objet d’un e-mail ?',
                         ['Un mot vague', 'Le sujet précis', 'Rien'], 1),
                question('Quand envoyer l’ordre du jour d’une réunion ?',
                         ['Avant la réunion', 'Pendant', 'Jamais'], 0),
                question('Par quoi commencer une présentation courte ?',
                         ['Les détails', 'La conclusion', 'Les remerciements'], 1),
                question('Une bonne réunion dure le plus longtemps possible.', ['Vrai', 'Faux'], 1),
            ]),
            (SectionType.CAS, 'Le retour constructif', [
                slide('La méthode en trois temps',
                      'Les faits', 'L’effet observé', 'La proposition'),
                slide('Choisir le moment',
                      'Rapidement après les faits', 'En privé', 'Au calme'),
                slide('Recevoir un retour',
                      'Écouter jusqu’au bout', 'Poser des questions', 'Remercier'),
            ], [
                question('Par quoi commence un retour constructif ?',
                         ['Un jugement', 'Les faits', 'Une sanction'], 1),
                question('Où donner un retour négatif ?', ['En public', 'En privé', 'Par affiche'], 1),
                question('Quand on reçoit un retour, il faut d’abord…',
                         ['Se justifier', 'Écouter jusqu’au bout', 'Partir'], 1),
                question('Un retour doit proposer une piste d’amélioration.', ['Vrai', 'Faux'], 0),
            ]),
        ],
    ),
    dict(
        slug='demo-personal-productivity-basics',
        category='developpement-personnel',
        title='Personal productivity basics',
        language='English',
        level=CourseLevel.INITIALISATION,
        is_free=False, original_price=2000, price=1500,
        skills=[],
        description=(
            'Demo course (paid, in English) to test the platform in another language. '
            'Plan your week, focus on one task and keep a simple to-do list.'
        ),
        prerequisites=['None'],
        what_you_learn=[
            'Plan a week in 15 minutes',
            'Work in focused blocks',
            'Keep a to-do list that stays short',
        ],
        sections=[
            (SectionType.INTRO, 'Plan your week', [
                slide('Why plan?', 'Less stress', 'Fewer forgotten tasks', 'More time for what matters'),
                slide('The weekly review', 'Look back at last week', 'List the three main goals', 'Book time for them'),
                slide('Keep it short', 'Three goals, not ten', 'Leave free time', 'Review on Friday'),
            ], [
                question('How many main goals for a week?', ['One hundred', 'Three', 'None'], 1),
                question('When is a good moment for the weekly review?', ['Friday', 'Never', 'Every hour'], 0),
                question('A good plan leaves some free time.', ['True', 'False'], 0),
                question('What is the first step of the weekly review?',
                         ['Look back at last week', 'Delete all tasks', 'Buy a new notebook'], 0),
            ]),
            (SectionType.INIT, 'Focus and to-do lists', [
                slide('Focused blocks', '25 to 50 minutes', 'One task only', 'A short break after'),
                slide('Remove distractions', 'Silence notifications', 'Close extra tabs', 'Tell others you are busy'),
                slide('A short to-do list', 'Write the next action', 'Remove what is done', 'Move the rest to tomorrow'),
            ], [
                question('How long is a focused block?', ['2 minutes', '25 to 50 minutes', '5 hours'], 1),
                question('During a focused block you work on…', ['One task', 'Five tasks', 'No task'], 0),
                question('What helps remove distractions?',
                         ['More notifications', 'Silencing notifications', 'More tabs'], 1),
                question('A to-do list should keep growing forever.', ['True', 'False'], 1),
            ]),
        ],
    ),
]


class Command(BaseCommand):
    help = 'Create demo categories and courses (with quizzes and a final exam) for staging.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='Allow running when ENVIRONMENT=production.')
        parser.add_argument('--delete', action='store_true',
                            help='Delete the demo courses instead of creating them.')

    def handle(self, *args, **options):
        env = getattr(settings, 'ENVIRONMENT', 'production')
        if env == 'production' and not options['force']:
            raise CommandError(
                'Refusing to load demo courses: ENVIRONMENT is "production". '
                'Set ENVIRONMENT=staging, or pass --force if you really mean it.'
            )

        slugs = [c['slug'] for c in COURSES]
        if options['delete']:
            # Courses with enrolments or orders are protected by the database;
            # archive those instead of failing halfway.
            removed = archived = 0
            for course in Course.objects.filter(slug__in=slugs):
                try:
                    with transaction.atomic():
                        course.delete()
                    removed += 1
                except Exception:  # noqa: BLE001 - protected relations
                    course.status = CourseStatus.ARCHIVED
                    course.save(update_fields=['status', 'updated_at'])
                    archived += 1
            self.stdout.write(self.style.SUCCESS(f'Demo courses deleted: {removed}, archived: {archived}.'))
            return

        with transaction.atomic():
            categories = {}
            for slug, icon, fr, en, ar in CATEGORIES:
                cat, created = Category.objects.get_or_create(
                    slug=slug, defaults={'icon': icon, 'name': {'fr': fr, 'en': en, 'ar': ar}},
                )
                categories[slug] = cat
                self._report('Category', slug, created)

            for data in COURSES:
                if Course.objects.filter(slug=data['slug']).exists():
                    self._report('Course', data['slug'], False)
                    continue
                self._create_course(data, categories[data['category']])
                self._report('Course', data['slug'], True)

    def _report(self, kind, slug, created):
        if created:
            self.stdout.write(self.style.SUCCESS(f'{kind} created: {slug}'))
        else:
            self.stdout.write(f'{kind} already there, left as it is: {slug}')

    def _create_course(self, data, category):
        today = date.today()
        course = Course(
            slug=data['slug'],
            title=data['title'],
            description=data['description'],
            prerequisites=data['prerequisites'],
            whatYouLearn=data['what_you_learn'],
            skills=data['skills'],
            category=category,
            level=data['level'],
            duration=1,
            language=data['language'],
            is_free=data['is_free'],
            originalPrice=data['original_price'],
            price=data['price'],
            discount=(round(100 * (1 - data['price'] / data['original_price']))
                      if data['original_price'] else 0),
            certificate=True,
            date=today,
            lastUpdated=today,
            status=CourseStatus.PUBLISHED,
        )
        course.full_clean(exclude=['image', 'instructor'])
        course.save()

        for s_idx, (s_type, s_title, slides, questions) in enumerate(data['sections'], start=1):
            section = Section.objects.create(course=course, title=s_title, type=s_type, sequence=s_idx)
            module = Module.objects.create(section=section, title=s_title, sequence=1)
            for l_idx, (l_title, points) in enumerate(slides, start=1):
                Lesson.objects.create(
                    module=module,
                    title=l_title,
                    type=LessonType.SLIDE,
                    sequence=l_idx,
                    duration_seconds=60,
                    slide_type='bullet_points',
                    # No audio file: show the slide only.
                    display_mode=DisplayMode.SLIDE,
                    content={
                        'title': l_title,
                        'slide_type': 'bullet_points',
                        'visual_content': {'bullet_points': points},
                        'narration_script': {'mode': 'monologue', 'speakers': []},
                    },
                )
            quiz = Quiz.objects.create(
                section=section,
                title=f'Quiz : {s_title}' if data['language'] == 'Français' else f'Quiz: {s_title}',
                pass_threshold=70, max_attempts=0, xp_reward=10,
            )
            for q_idx, (text, opts, answer, explanation) in enumerate(questions, start=1):
                QuizQuestion.objects.create(
                    quiz=quiz,
                    type='true_false' if len(opts) == 2 else 'multiple_choice',
                    question=text, options=opts, correct_answer=answer,
                    explanation=explanation, sequence=q_idx,
                )

        FinalQuiz.objects.create(
            course=course,
            title='Examen final' if data['language'] == 'Français' else 'Final exam',
            num_questions=6, pass_threshold=70, max_attempts=0, xp_reward=50,
        )
