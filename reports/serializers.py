from rest_framework import serializers

from .catalog import SOURCES


class CriterionSerializer(serializers.Serializer):
    field = serializers.CharField(max_length=50)
    operator = serializers.CharField(max_length=20)
    value = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")


class SortSerializer(serializers.Serializer):
    field = serializers.CharField(max_length=50)
    direction = serializers.ChoiceField(choices=("asc", "desc"))


class ReportRequestSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=tuple(SOURCES))
    title = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    columns = serializers.ListField(child=serializers.CharField(max_length=50), min_length=1, max_length=20)
    filters = CriterionSerializer(many=True, required=False, default=list)
    ordering = SortSerializer(many=True, required=False, default=list)
    page = serializers.IntegerField(min_value=1, max_value=1000000, required=False, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False, default=25)
    format = serializers.ChoiceField(choices=("xlsx", "html"), required=False)

    def validate(self, data):
        columns = {column.key: column for column in SOURCES[data["source"]].columns}
        selected = data["columns"]
        if len(set(selected)) != len(selected) or any(key not in columns for key in selected):
            raise serializers.ValidationError("Selecciona columnas válidas, sin repetir.")
        if len(data["filters"]) > 10 or len(data["ordering"]) > 3:
            raise serializers.ValidationError("Se permiten hasta 10 filtros y 3 criterios de orden.")
        sort_fields = [item["field"] for item in data["ordering"]]
        if len(set(sort_fields)) != len(sort_fields) or any(key not in columns for key in sort_fields):
            raise serializers.ValidationError("El orden contiene columnas inválidas o repetidas.")
        for item in data["filters"]:
            column = columns.get(item["field"])
            if not column or item["operator"] not in column.operators:
                raise serializers.ValidationError("El filtro contiene una columna u operador inválido.")
            if item["operator"] not in ("is_empty", "not_empty") and not item["value"].strip():
                raise serializers.ValidationError(f"Indica el valor del filtro {column.label}.")
            if column.kind == "choice" and item["value"] not in dict(column.choices):
                raise serializers.ValidationError(f"El valor de {column.label} no es válido.")
        return data
