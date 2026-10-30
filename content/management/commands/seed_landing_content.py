"""
Seed the landing-page CMS with sample content (hero, features, FAQ,
testimonials, site settings) so a fresh database renders a real homepage.

Meant for staging / local development. It refuses to run when
ENVIRONMENT=production unless --force is given.

Safe to re-run: every section is only created when it doesn't exist yet, so
content you edited in the admin panel is never overwritten.

    python manage.py seed_landing_content
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from content.models import (
    FAQItem,
    FAQSection,
    FeatureItem,
    FeaturesSection,
    HeroSection,
    SiteSettings,
    Testimonial,
)


def t(fr, en, ar):
    """Build a translatable JSON value."""
    return {'fr': fr, 'en': en, 'ar': ar}


HERO = dict(
    title=t('Apprenez les compétences qui font la différence avec', 'Learn the skills that make a difference with', 'تعلّم المهارات التي تصنع الفرق مع'),
    title_highlight=t('OOSkills', 'OOSkills', 'OOSkills'),
    subtitle=t('Des formations en ligne pour réussir votre carrière', 'Online courses to grow your career', 'دورات عبر الإنترنت لتطوير مسارك المهني'),
    description=t(
        'Des cours en français, en anglais et en arabe, des quiz, des certificats et un suivi de progression, accessibles depuis votre téléphone ou votre ordinateur.',
        'Courses in French, English and Arabic, with quizzes, certificates and progress tracking, on your phone or computer.',
        'دورات بالفرنسية والإنجليزية والعربية مع اختبارات وشهادات ومتابعة للتقدم، من هاتفك أو حاسوبك.',
    ),
    primary_cta_text=t('Commencer maintenant', 'Get started', 'ابدأ الآن'),
    secondary_cta_text=t('Voir les formations', 'Browse courses', 'تصفح الدورات'),
    badge_text=t('Nouveau : certificats vérifiables', 'New: verifiable certificates', 'جديد: شهادات قابلة للتحقق'),
    card_title=t('Gestion de projet', 'Project management', 'إدارة المشاريع'),
    card_subtitle=t('12 modules · Certificat inclus', '12 modules · Certificate included', '12 وحدة · شهادة مشمولة'),
)

FEATURES_SECTION = dict(
    title=t('Pourquoi choisir OOSkills ?', 'Why choose OOSkills?', 'لماذا تختار OOSkills؟'),
    subtitle=t('Tout ce qu’il faut pour apprendre efficacement', 'Everything you need to learn effectively', 'كل ما تحتاجه للتعلّم بفعالية'),
)

FEATURE_ITEMS = [
    ('book-open', t('Cours structurés', 'Structured courses', 'دورات منظّمة'),
     t('Des parcours clairs, module après module, avec leçons audio et diaporamas.', 'Clear paths, module by module, with audio lessons and slides.', 'مسارات واضحة، وحدة بعد وحدة، مع دروس صوتية وشرائح.')),
    ('award', t('Certificats', 'Certificates', 'شهادات'),
     t('Obtenez un certificat vérifiable après l’examen final.', 'Earn a verifiable certificate after the final exam.', 'احصل على شهادة قابلة للتحقق بعد الاختبار النهائي.')),
    ('trophy', t('Progression et XP', 'Progress and XP', 'التقدم والنقاط'),
     t('Gagnez de l’XP, débloquez des badges et suivez le classement.', 'Earn XP, unlock badges and climb the leaderboard.', 'اكسب النقاط وافتح الشارات وتابع الترتيب.')),
    ('smartphone', t('Partout, tout le temps', 'Anywhere, anytime', 'في أي مكان وزمان'),
     t('Apprenez depuis votre téléphone, votre tablette ou votre ordinateur.', 'Learn from your phone, tablet or computer.', 'تعلّم من هاتفك أو جهازك اللوحي أو حاسوبك.')),
]

FAQ_SECTION = dict(
    title=t('Questions fréquentes', 'Frequently asked questions', 'الأسئلة الشائعة'),
    subtitle=t('Vous avez une question ? Nous avons la réponse.', 'Got a question? We have the answer.', 'لديك سؤال؟ لدينا الجواب.'),
)

FAQ_ITEMS = [
    (t('Comment payer une formation ?', 'How do I pay for a course?', 'كيف أدفع ثمن الدورة؟'),
     t('Le paiement se fait en ligne par CIB, Edahabia ou carte bancaire via Chargily.', 'You pay online with CIB, Edahabia or a bank card through Chargily.', 'يتم الدفع عبر الإنترنت ببطاقة CIB أو الذهبية أو بطاقة بنكية عبر Chargily.')),
    (t('Puis-je obtenir un certificat ?', 'Can I get a certificate?', 'هل يمكنني الحصول على شهادة؟'),
     t('Oui, après avoir terminé le cours et réussi l’examen final.', 'Yes, once you finish the course and pass the final exam.', 'نعم، بعد إنهاء الدورة والنجاح في الاختبار النهائي.')),
    (t('Les cours sont-ils disponibles en arabe ?', 'Are courses available in Arabic?', 'هل الدورات متوفرة بالعربية؟'),
     t('Oui, le site et les cours existent en français, en anglais et en arabe.', 'Yes, the site and courses are available in French, English and Arabic.', 'نعم، الموقع والدورات متوفرة بالفرنسية والإنجليزية والعربية.')),
]

TESTIMONIALS = [
    ('Amine B.', t('Chef de projet', 'Project manager', 'مدير مشاريع'),
     t('Des cours clairs et un certificat reconnu. Je recommande.', 'Clear courses and a recognised certificate. Highly recommended.', 'دورات واضحة وشهادة معترف بها. أنصح بها.'), 5),
    ('Sara K.', t('Étudiante', 'Student', 'طالبة'),
     t('J’ai appris à mon rythme, depuis mon téléphone.', 'I learned at my own pace, from my phone.', 'تعلمت بالوتيرة التي تناسبني من هاتفي.'), 5),
    ('Yacine M.', t('Entrepreneur', 'Entrepreneur', 'رائد أعمال'),
     t('Les quiz m’ont aidé à vraiment retenir.', 'The quizzes helped me really retain it.', 'ساعدتني الاختبارات على الحفظ فعلاً.'), 4),
]


class Command(BaseCommand):
    help = 'Create sample landing-page content (staging/dev only). Re-runnable.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force', action='store_true',
            help='Allow running when ENVIRONMENT=production.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        env = getattr(settings, 'ENVIRONMENT', 'production')
        if env == 'production' and not options['force']:
            raise CommandError(
                'Refusing to seed sample content: ENVIRONMENT is "production". '
                'Set ENVIRONMENT=staging, or pass --force if you really mean it.'
            )

        created = []

        if not HeroSection.objects.filter(is_active=True).exists():
            HeroSection.objects.create(is_active=True, **HERO)
            created.append('hero')

        if not FeaturesSection.objects.filter(is_active=True).exists():
            section = FeaturesSection.objects.create(is_active=True, **FEATURES_SECTION)
            for order, (icon, title, desc) in enumerate(FEATURE_ITEMS):
                FeatureItem.objects.create(
                    section=section, icon=icon, title=title,
                    description=desc, order=order, is_active=True,
                )
            created.append(f'features ({len(FEATURE_ITEMS)} items)')

        if not FAQSection.objects.filter(is_active=True).exists():
            faq = FAQSection.objects.create(is_active=True, **FAQ_SECTION)
            for order, (q, a) in enumerate(FAQ_ITEMS):
                FAQItem.objects.create(
                    section=faq, question=q, answer=a, order=order, is_active=True,
                )
            created.append(f'faq ({len(FAQ_ITEMS)} items)')

        if not Testimonial.objects.exists():
            for order, (name, title, content, rating) in enumerate(TESTIMONIALS):
                Testimonial.objects.create(
                    author_name=name, author_title=title, content=content,
                    rating=rating, order=order, is_active=True,
                )
            created.append(f'testimonials ({len(TESTIMONIALS)})')

        site = SiteSettings.get_settings()
        changed = []
        for field, value in {
            'site_tagline': 'Apprenez. Progressez. Certifiez-vous.',
            'meta_title': 'OOSkills (staging)',
            'meta_description': 'Plateforme de formation en ligne — environnement de test.',
        }.items():
            if not getattr(site, field):
                setattr(site, field, value)
                changed.append(field)
        if changed:
            site.save(update_fields=changed + ['updated_at'])
            created.append('site settings')

        if created:
            self.stdout.write(self.style.SUCCESS('Created: ' + ', '.join(created)))
        else:
            self.stdout.write('Nothing to do: landing content already exists.')
