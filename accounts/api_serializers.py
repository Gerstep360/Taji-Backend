from rest_framework import serializers

from .serializers import UserSerializer


class MessageResponseSerializer(serializers.Serializer):
    message = serializers.CharField()


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class RegisterResponseSerializer(MessageResponseSerializer):
    user = UserSerializer()


class LoginResponseSerializer(MessageResponseSerializer):
    user = UserSerializer()
    tokens = TokenPairSerializer(required=False)


class MeResponseSerializer(serializers.Serializer):
    user = UserSerializer()
    resident_units = serializers.ListField(child=serializers.DictField(), required=False)
    linked_residents = serializers.ListField(child=serializers.DictField(), required=False)


class RefreshResponseSerializer(serializers.Serializer):
    message = serializers.CharField(required=False)
    tokens = TokenPairSerializer(required=False)


class ErrorPayloadSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    fields = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        required=False,
    )


class ErrorResponseSerializer(serializers.Serializer):
    error = ErrorPayloadSerializer()
