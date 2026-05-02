import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_add_referral_balance'),
    ]

    operations = [
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('type', models.CharField(
                    db_index=True,
                    max_length=30,
                    choices=[
                        ('course_purchased', 'Cours acheté'),
                        ('course_completed', 'Cours terminé'),
                        ('certificate_earned', 'Certificat obtenu'),
                        ('achievement_unlocked', 'Badge débloqué'),
                        ('level_up', 'Niveau supérieur'),
                        ('gift_received', 'Cadeau reçu'),
                        ('referral_bonus', 'Bonus parrainage'),
                        ('quiz_passed', 'Quiz réussi'),
                    ],
                    verbose_name='Type',
                )),
                ('title', models.CharField(max_length=200, verbose_name='Titre')),
                ('body', models.CharField(blank=True, max_length=500, verbose_name='Corps')),
                ('link', models.CharField(blank=True, max_length=200, verbose_name='Lien')),
                ('is_read', models.BooleanField(db_index=True, default=False, verbose_name='Lu')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='notifications',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Notification',
                'verbose_name_plural': 'Notifications',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['user', '-created_at'], name='notif_user_date_idx'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['user', 'is_read'], name='notif_user_read_idx'),
        ),
    ]
