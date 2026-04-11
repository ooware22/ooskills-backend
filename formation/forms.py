from django import forms
from django.contrib.auth import get_user_model
from formation.models import Category

User = get_user_model()

class CourseImportZipForm(forms.Form):
    zip_file = forms.FileField(
        label="Fichier ZIP",
        help_text="Sélectionnez le fichier ZIP contenant manifest.json, formation.json et les dossiers (audio, slides).",
        widget=forms.ClearableFileInput(attrs={'accept': '.zip'})
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        label="Catégorie",
        required=True,
        help_text="Sélectionnez la catégorie de la formation."
    )
    instructor = forms.ModelChoiceField(
        queryset=User.objects.filter(is_staff=True), # assuming instructors are staff or similar, adjust if needed
        label="Instructeur",
        required=False,
        help_text="Optionnel: Sélectionnez l'instructeur."
    )

    def clean_zip_file(self):
        zip_file = self.cleaned_data.get('zip_file')
        if not zip_file.name.endswith('.zip'):
            raise forms.ValidationError("Le fichier doit être au format ZIP.")
        return zip_file
