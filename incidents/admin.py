from django.contrib import admin

from .models import (
    Incident,
    IncidentAssignment,
    IncidentAttachment,
    IncidentCategory,
    IncidentComment,
    IncidentStatusHistory,
    PriorityLevel,
    RiskRule,
)


class IncidentStatusHistoryInline(admin.TabularInline):
    model = IncidentStatusHistory
    extra = 0
    readonly_fields = ("from_status", "to_status", "comment", "changed_by_user", "changed_at")


class IncidentCommentInline(admin.TabularInline):
    model = IncidentComment
    extra = 0
    readonly_fields = ("author_user", "created_at")


class IncidentAssignmentInline(admin.TabularInline):
    model = IncidentAssignment
    extra = 0
    readonly_fields = ("assigned_at", "assigned_by_user")


class IncidentAttachmentInline(admin.TabularInline):
    model = IncidentAttachment
    extra = 0
    readonly_fields = ("uploaded_by_user", "created_at")


@admin.register(IncidentCategory)
class IncidentCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "default_staff_type", "is_active")
    list_filter = ("default_staff_type", "is_active")
    search_fields = ("code", "name", "description")
    ordering = ("name",)


@admin.register(PriorityLevel)
class PriorityLevelAdmin(admin.ModelAdmin):
    list_display = ("rank", "code", "name", "target_minutes", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    ordering = ("rank",)


@admin.register(RiskRule)
class RiskRuleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "entity_type", "weight", "is_active")
    list_filter = ("entity_type", "is_active")
    search_fields = ("code", "name", "description")
    ordering = ("code",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = (
        "public_code",
        "title",
        "status",
        "priority",
        "category",
        "current_assignee_staff",
        "due_at",
        "created_at",
    )
    list_filter = ("status", "priority", "category")
    search_fields = ("public_code", "title", "description")
    readonly_fields = ("public_code", "created_at", "updated_at")
    inlines = [
        IncidentStatusHistoryInline,
        IncidentCommentInline,
        IncidentAssignmentInline,
        IncidentAttachmentInline,
    ]


@admin.register(IncidentStatusHistory)
class IncidentStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("incident", "from_status", "to_status", "changed_by_user", "changed_at")
    list_filter = ("to_status", "changed_at")
    search_fields = ("incident__public_code", "comment")


@admin.register(IncidentComment)
class IncidentCommentAdmin(admin.ModelAdmin):
    list_display = ("incident", "visibility", "author_user", "created_at")
    list_filter = ("visibility", "created_at")
    search_fields = ("incident__public_code", "body")


@admin.register(IncidentAssignment)
class IncidentAssignmentAdmin(admin.ModelAdmin):
    list_display = ("incident", "assigned_to_staff", "assigned_by_user", "assigned_at", "ended_at")
    list_filter = ("assigned_at", "ended_at")
    search_fields = ("incident__public_code", "assigned_to_staff__employee_code")


@admin.register(IncidentAttachment)
class IncidentAttachmentAdmin(admin.ModelAdmin):
    list_display = ("incident", "file_type", "caption", "uploaded_by_user", "created_at")
    list_filter = ("file_type", "created_at")
    search_fields = ("incident__public_code", "caption")


from .models import IncidentAIAnalysis, IncidentAIReview


class ImmutableAIAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IncidentAIAnalysis)
class IncidentAIAnalysisAdmin(ImmutableAIAdmin):
    list_display = ('incident', 'execution_status', 'review_status', 'model_name', 'duration_ms', 'created_at')
    list_filter = ('execution_status', 'review_status')


@admin.register(IncidentAIReview)
class IncidentAIReviewAdmin(ImmutableAIAdmin):
    list_display = ('analysis', 'reviewer', 'category', 'priority', 'created_at')
