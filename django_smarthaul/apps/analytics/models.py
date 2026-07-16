from django.conf import settings
from django.db import models


class ActivityLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activity_logs',
    )
    actor_role = models.CharField(max_length=20, blank=True)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=50)
    target_id = models.CharField(max_length=50, blank=True)
    summary = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action']),
            models.Index(fields=['target_type', 'target_id']),
            models.Index(fields=['created_at']),
        ]


def log_activity(*, actor=None, action, target_type, target_id='', summary, metadata=None):
    return ActivityLog.objects.create(
        actor=actor,
        actor_role=getattr(actor, 'role', '') if actor else '',
        action=action,
        target_type=target_type,
        target_id=str(target_id or ''),
        summary=summary,
        metadata=metadata or {},
    )
