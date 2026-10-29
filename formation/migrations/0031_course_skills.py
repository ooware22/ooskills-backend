import formation.skills_vocab
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('formation', '0030_course_course_title_trgm_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='skills',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='["Python", "SQL", ...] — keywords from formation/data/skill_keywords_fr.csv '
                          '(shared with Oosira for CV gap recommendations)',
                validators=[formation.skills_vocab.validate_skill_keywords],
                verbose_name='Compétences',
            ),
        ),
    ]
