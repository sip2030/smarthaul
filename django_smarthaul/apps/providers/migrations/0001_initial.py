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
            name='Provider',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('service_area', models.CharField(max_length=255)),
                ('vehicle_type', models.CharField(blank=True, max_length=100)),
                ('license_number', models.CharField(blank=True, max_length=100)),
                ('is_available', models.BooleanField(default=True)),
                ('rating', models.FloatField(default=0)),
                ('total_earnings', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('total_bookings', models.IntegerField(default=0)),
                ('completed_bookings', models.IntegerField(default=0)),
                ('cancelled_bookings', models.IntegerField(default=0)),
                ('permanently_banned', models.BooleanField(default=False)),
                ('ban_reason', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='provider_profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Provider',
                'verbose_name_plural': 'Providers',
            },
        ),
        migrations.AddIndex(
            model_name='provider',
            index=models.Index(fields=['service_area'], name='providers_s_area_7d0f2f_idx'),
        ),
        migrations.AddIndex(
            model_name='provider',
            index=models.Index(fields=['is_available'], name='providers_i_avail_3d9f0a_idx'),
        ),
        migrations.AddIndex(
            model_name='provider',
            index=models.Index(fields=['created_at'], name='providers_c_created_b6a213_idx'),
        ),
    ]
