"""
Serializer for Avatar Upload
"""

from rest_framework import serializers


class AvatarUploadSerializer(serializers.Serializer):
    """Serializer for avatar file upload validation."""
    
    avatar = serializers.ImageField(required=True)
    
    def validate_avatar(self, value):
        """Validate the uploaded avatar file."""
        # Check file size (max 5MB)
        max_size = 5 * 1024 * 1024  # 5MB
        if value.size > max_size:
            raise serializers.ValidationError(
                "La taille du fichier ne doit pas dépasser 5 Mo."
            )
        
        # Check file extension
        allowed_extensions = ['jpg', 'jpeg', 'png', 'webp', 'gif']
        file_extension = value.name.split('.')[-1].lower()
        if file_extension not in allowed_extensions:
            raise serializers.ValidationError(
                f"Format non supporté. Formats acceptés: {', '.join(allowed_extensions)}"
            )
        
        return value
