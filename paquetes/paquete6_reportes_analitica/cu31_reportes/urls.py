from django.urls import path

from .views import (
    Cu31CatalogView,
    Cu31TranscribeView,
    Cu31ExportView,
    Cu31PreviewView,
    Cu31VoiceNarrateView,
    Cu31VoiceQueryView,
)

urlpatterns = [
    path("transcribe/", Cu31TranscribeView.as_view(), name="cu31-reports-transcribe"),
    path("catalog/", Cu31CatalogView.as_view(), name="cu31-reports-catalog"),
    path("preview/", Cu31PreviewView.as_view(), name="cu31-reports-preview"),
    path("export/", Cu31ExportView.as_view(), name="cu31-reports-export"),
    path("voice-query/", Cu31VoiceQueryView.as_view(), name="cu31-reports-voice-query"),
    path("voice-narrate/", Cu31VoiceNarrateView.as_view(), name="cu31-reports-voice-narrate"),
]

