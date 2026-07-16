from django.db import models
from django.conf import settings


class Notification(models.Model):
    CATEGORY_CHOICES = [
        ('booking', 'Booking'),
        ('payment', 'Payment'),
        ('support', 'Support'),
        ('moderation', 'Moderation'),
        ('system', 'System'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='system')
    title = models.CharField(max_length=255)
    body = models.TextField()
    booking_id = models.IntegerField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'read_at']),
            models.Index(fields=['category']),
        ]

    def mark_read(self, commit=True):
        from django.utils.timezone import now

        self.read_at = now()
        if commit:
            self.save(update_fields=['read_at', 'updated_at'])


class SupportCase(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_review', 'In Review'),
        ('escalated', 'Escalated'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='support_cases')
    booking = models.ForeignKey('bookings.Booking', on_delete=models.SET_NULL, null=True, blank=True, related_name='support_cases')
    subject = models.CharField(max_length=255)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    ai_summary = models.TextField(blank=True)
    human_assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_support_cases')
    resolution_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'priority']),
            models.Index(fields=['user', 'status']),
        ]

    def mark_escalated(self, summary=''):
        self.status = 'escalated'
        if summary:
            self.ai_summary = summary
        self.save(update_fields=['status', 'ai_summary', 'updated_at'])


class SafetyReport(models.Model):
    REPORT_TYPE_CHOICES = [
        ('harassment', 'Harassment'),
        ('misconduct', 'Misconduct'),
        ('fraud', 'Fraud'),
        ('unsafe_conduct', 'Unsafe Conduct'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('under_review', 'Under Review'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    TARGET_TYPE_CHOICES = [
        ('booking', 'Booking'),
        ('user', 'User'),
        ('provider', 'Provider'),
        ('vendor', 'Vendor'),
    ]

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='safety_reports')
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_safety_reports')
    booking = models.ForeignKey('bookings.Booking', on_delete=models.SET_NULL, null=True, blank=True, related_name='safety_reports')
    report_type = models.CharField(max_length=30, choices=REPORT_TYPE_CHOICES)
    target_type = models.CharField(max_length=20, choices=TARGET_TYPE_CHOICES, default='booking')
    target_name = models.CharField(max_length=255, blank=True)
    target_reference = models.CharField(max_length=255, blank=True)
    linked_entity_available = models.BooleanField(default=True)
    linked_entity_note = models.TextField(blank=True)
    description = models.TextField()
    evidence_url = models.URLField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    moderator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='moderated_safety_reports')
    moderator_notes = models.TextField(blank=True)
    moderation_action = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'report_type']),
            models.Index(fields=['target_type']),
            models.Index(fields=['linked_entity_available']),
            models.Index(fields=['reporter', 'status']),
        ]

    def mark_under_review(self, moderator):
        from django.utils.timezone import now

        self.status = 'under_review'
        self.moderator = moderator
        self.reviewed_at = now()
        self.save(update_fields=['status', 'moderator', 'reviewed_at', 'updated_at'])

    def mark_resolved(self, moderator, notes='', action=''):
        from django.utils.timezone import now

        self.status = 'resolved'
        self.moderator = moderator
        self.moderator_notes = notes
        self.moderation_action = action
        self.resolved_at = now()
        self.save(update_fields=['status', 'moderator', 'moderator_notes', 'moderation_action', 'resolved_at', 'updated_at'])

    def mark_closed(self, moderator=None, notes=''):
        from django.utils.timezone import now

        self.status = 'closed'
        if moderator is not None:
            self.moderator = moderator
        if notes:
            self.moderator_notes = notes
        self.closed_at = now()
        self.save(update_fields=['status', 'moderator', 'moderator_notes', 'closed_at', 'updated_at'])
