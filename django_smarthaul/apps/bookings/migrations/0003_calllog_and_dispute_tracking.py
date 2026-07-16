from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('bookings', '0002_booking_add_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='has_active_dispute',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name='booking',
            name='dispute_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='safety_report_filed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='call_logging_window_hours',
            field=models.IntegerField(default=24),
        ),
        migrations.CreateModel(
            name='CallLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('call_type', models.CharField(choices=[('inbound', 'Inbound'), ('outbound', 'Outbound')], max_length=20)),
                ('duration_seconds', models.IntegerField(blank=True, null=True)),
                ('recording_url', models.URLField(blank=True)),
                ('recording_enabled', models.BooleanField(default=False)),
                ('call_should_be_logged', models.BooleanField(default=False, help_text='True if booking had active dispute or safety report at call time')),
                ('reason_for_logging', models.CharField(blank=True, help_text='Why this call was logged: dispute_active, safety_report_filed, etc.', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('ended_at', models.DateTimeField(blank=True, null=True)),
                ('booking', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='call_logs', to='bookings.booking')),
                ('caller', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='calls_made', to=settings.AUTH_USER_MODEL)),
                ('recipient', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='calls_received', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Call Log',
                'verbose_name_plural': 'Call Logs',
            },
        ),
        migrations.AddIndex(
            model_name='calllog',
            index=models.Index(fields=['booking', 'created_at'], name='bookings_ca_booking_idx'),
        ),
        migrations.AddIndex(
            model_name='calllog',
            index=models.Index(fields=['call_should_be_logged'], name='bookings_ca_call_sho_idx'),
        ),
        migrations.AddIndex(
            model_name='calllog',
            index=models.Index(fields=['booking', 'call_should_be_logged'], name='bookings_ca_booking_call_idx'),
        ),
    ]
