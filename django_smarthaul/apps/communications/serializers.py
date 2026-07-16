from rest_framework import serializers
from .models import Notification, SupportCase, SafetyReport


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ['id', 'user', 'category', 'title', 'body', 'booking_id', 'read_at', 'created_at', 'updated_at', 'is_read']
        read_only_fields = ['id', 'created_at', 'updated_at', 'read_at', 'is_read']

    def get_is_read(self, obj):
        return obj.read_at is not None


class SupportCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportCase
        fields = [
            'id', 'user', 'booking', 'subject', 'description', 'status', 'priority',
            'ai_summary', 'human_assignee', 'resolution_notes', 'created_at', 'updated_at', 'resolved_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'resolved_at', 'ai_summary']


class SupportCaseCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportCase
        fields = ['booking', 'subject', 'description', 'priority']


class SafetyReportSerializer(serializers.ModelSerializer):
    reporter_name = serializers.CharField(source='reporter.get_full_name', read_only=True)
    moderator_name = serializers.CharField(source='moderator.get_full_name', read_only=True)

    class Meta:
        model = SafetyReport
        fields = [
            'id', 'reporter', 'reporter_name', 'target_user', 'booking', 'report_type',
            'target_type', 'target_name', 'target_reference', 'linked_entity_available',
            'linked_entity_note', 'description', 'evidence_url', 'status',
            'moderator', 'moderator_name', 'moderator_notes', 'moderation_action',
            'created_at', 'updated_at', 'reviewed_at', 'resolved_at', 'closed_at'
        ]
        read_only_fields = [
            'id', 'reporter_name', 'moderator_name', 'status', 'moderator', 'created_at',
            'updated_at', 'reviewed_at', 'resolved_at', 'closed_at', 'moderator_notes',
            'moderation_action', 'linked_entity_available', 'linked_entity_note',
        ]


class SafetyReportCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SafetyReport
        fields = [
            'booking', 'target_user', 'report_type', 'target_type', 'target_name',
            'target_reference', 'linked_entity_available', 'linked_entity_note',
            'description', 'evidence_url'
        ]
