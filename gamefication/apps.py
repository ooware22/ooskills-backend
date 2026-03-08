from django.apps import AppConfig


class GamificationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'gamefication'
    verbose_name = 'Gamification'

    def ready(self):
        import gamefication.signals  # noqa: F401
