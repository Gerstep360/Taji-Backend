from rest_framework import serializers
from .catalog import SOURCES

OPERATOR_CHOICES = ("eq", "ne", "gte", "lte", "contains", "is_empty", "not_empty")
FORMAT_CHOICES = ("xlsx", "html", "csv")


class FilterItemSerializer(serializers.Serializer):
    field = serializers.CharField(max_length=60)
    operator = serializers.ChoiceField(choices=OPERATOR_CHOICES)
    value = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class OrderingItemSerializer(serializers.Serializer):
    field = serializers.CharField(max_length=60)
    direction = serializers.ChoiceField(choices=("asc", "desc"), default="asc")


class ReportRequestSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=list(SOURCES.keys()))
    columns = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False, default=list
    )
    filters = FilterItemSerializer(many=True, required=False, default=list)
    ordering = OrderingItemSerializer(many=True, required=False, default=list)
    title = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    format = serializers.ChoiceField(choices=FORMAT_CHOICES, required=False)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=200, default=25)


class VoiceQueryRequestSerializer(serializers.Serializer):
    voice_text = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )
    audio_file = serializers.FileField(required=False, allow_null=True)
    preferred_format = serializers.ChoiceField(
        choices=("preview", "xlsx", "html", "csv"), default="preview"
    )
    auto_narrate = serializers.BooleanField(default=True)

    def validate(self, attrs):
        if not attrs.get("voice_text") and not attrs.get("audio_file"):
            raise serializers.ValidationError(
                "Debe proporcionar 'voice_text' (transcripción) o un archivo 'audio_file'."
            )
        return attrs


class VoiceNarrateRequestSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=list(SOURCES.keys()))
    total_count = serializers.IntegerField(min_value=0, default=0)
    context_data = serializers.DictField(required=False, default=dict)
    custom_message = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")

