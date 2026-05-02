from django.apps import AppConfig


class FormationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'formation'

    def ready(self):
        import formation.signals  # noqa: F401  — register cache-invalidation handlers
