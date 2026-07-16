from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ActivityLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('actor_role', models.CharField(blank=True, max_length=20)),
                ('action', models.CharField(max_length=100)),
                ('target_type', models.CharField(max_length=50)),
                ('target_id', models.CharField(blank=True, max_length=50)),
                ('summary', models.TextField()),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='activity_logs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['action'], name='analytics_a_action_fcaee8_idx'), models.Index(fields=['target_type', 'target_id'], name='analytics_a_target__eb70d1_idx'), models.Index(fields=['created_at'], name='analytics_a_created_6ac18e_idx')],
            },
        ),
    ]
