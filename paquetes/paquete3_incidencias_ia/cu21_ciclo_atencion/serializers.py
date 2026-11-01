from rest_framework import serializers


class AssignmentRequestSerializer(serializers.Serializer):
    staff_id = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=240, required=False, allow_blank=True)


class AttentionAlertSerializer(serializers.Serializer):
    kind = serializers.CharField()
    code = serializers.CharField()
    title = serializers.CharField()
    due_at = serializers.DateTimeField()
    resource_id = serializers.IntegerField()


class AssigneeOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class TransitionOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()
