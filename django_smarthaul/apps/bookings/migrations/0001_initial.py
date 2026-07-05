from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('vendors', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Booking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('service_type', models.CharField(max_length=100)),
                ('pickup', models.CharField(max_length=255)),
                ('destination', models.CharField(max_length=255)),
                ('price', models.DecimalField(decimal_places=2, max_digits=10)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('in_progress', 'In Progress'), ('completed', 'Completed'), ('cancelled', 'Cancelled')], default='pending', max_length=20)),
                ('current_latitude', models.FloatField(blank=True, null=True)),
                ('current_longitude', models.FloatField(blank=True, null=True)),
                ('eta_minutes', models.IntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('rating', models.IntegerField(blank=True, null=True)),
                ('feedback_comment', models.TextField(blank=True)),
                ('feedback_submitted_at', models.DateTimeField(blank=True, null=True)),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bookings_as_customer', to=settings.AUTH_USER_MODEL)),
                ('provider', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bookings_as_provider', to=settings.AUTH_USER_MODEL)),
                ('vendor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='vendors.vendor')),
            ],
            options={
                'verbose_name': 'Booking',
                'verbose_name_plural': 'Bookings',
            },
        ),
        migrations.CreateModel(
            name='BookingTracking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('latitude', models.FloatField()),
                ('longitude', models.FloatField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('booking', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tracking_events', to='bookings.booking')),
            ],
            options={
                'verbose_name': 'Booking Tracking',
                'verbose_name_plural': 'Booking Tracking Events',
            },
        ),
        migrations.AddIndex(
            model_name='booking',
            index=models.Index(fields=['customer', 'status'], name='bookings_c_status_5f4d1c_idx'),
        ),
        migrations.AddIndex(
            model_name='booking',
            index=models.Index(fields=['provider', 'status'], name='bookings_p_status_f4c38a_idx'),
        ),
        migrations.AddIndex(
            model_name='booking',
            index=models.Index(fields=['status'], name='bookings_status_1c8f7e_idx'),
        ),
        migrations.AddIndex(
            model_name='booking',
            index=models.Index(fields=['created_at'], name='bookings_created_2d57b1_idx'),
        ),
        migrations.AddIndex(
            model_name='bookingtracking',
            index=models.Index(fields=['booking', 'created_at'], name='bookings_bk_created_7eb52d_idx'),
        ),
    ]
