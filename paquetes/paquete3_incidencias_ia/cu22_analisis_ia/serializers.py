from rest_framework import serializers
import math
from incidents.models import IncidentCategory, PriorityLevel

CONTEXTS = ('present', 'negated', 'distant', 'past', 'uncertain', 'drill')


class EntityPredictionSerializer(serializers.Serializer):
    entity_type = serializers.RegexField(r'^[A-Za-z_]{1,40}$')
    text = serializers.CharField(max_length=240)
    context = serializers.ChoiceField(choices=CONTEXTS)


class RiskPredictionSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    evidence = serializers.CharField(max_length=240)
    context = serializers.ChoiceField(choices=CONTEXTS)


class PredictionSerializer(serializers.Serializer):
    category_code = serializers.CharField(max_length=50)
    priority_code = serializers.CharField(max_length=20)
    confidence = serializers.FloatField(min_value=0, max_value=1)
    risk_score = serializers.FloatField(min_value=0, max_value=100)
    summary = serializers.CharField(max_length=500)
    entities = EntityPredictionSerializer(many=True, max_length=30)
    risks = RiskPredictionSerializer(many=True, max_length=15)
    recommendations = serializers.ListField(child=serializers.CharField(max_length=300), max_length=8)

    def validate(self, attrs):
        if not all(math.isfinite(attrs[key]) for key in ('confidence', 'risk_score')):
            raise serializers.ValidationError('Las puntuaciones deben ser finitas.')
        return attrs


class ReviewSerializer(serializers.Serializer):
    category = serializers.PrimaryKeyRelatedField(queryset=IncidentCategory.objects.filter(is_active=True))
    priority = serializers.PrimaryKeyRelatedField(queryset=PriorityLevel.objects.filter(is_active=True))
    reason = serializers.CharField(min_length=10, max_length=2000)
    safety_override = serializers.BooleanField(default=False)


class CategoryWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = IncidentCategory
        fields = ('id', 'code', 'name', 'description', 'default_staff_type', 'is_active')
        read_only_fields = ('id', 'code')


class PriorityWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriorityLevel
        fields = ('id', 'code', 'name', 'rank', 'min_score', 'max_score', 'target_minutes', 'is_active')
        read_only_fields = ('id',)

    def validate(self, attrs):
        current = self.instance
        low = attrs.get('min_score', current.min_score if current else None)
        high = attrs.get('max_score', current.max_score if current else None)
        if low is not None and high is not None and high < low:
            raise serializers.ValidationError('El máximo no puede ser menor al mínimo.')
        if attrs.get('rank', 1) <= 0 or attrs.get('target_minutes', 1) is not None and attrs.get('target_minutes', 1) <= 0:
            raise serializers.ValidationError('El orden y el plazo deben ser positivos.')
        return attrs
