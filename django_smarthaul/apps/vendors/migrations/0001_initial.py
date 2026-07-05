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
            name='Vendor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('category', models.CharField(max_length=100)),
                ('location', models.CharField(max_length=255)),
                ('rating', models.FloatField(default=0)),
                ('contact_email', models.EmailField(blank=True, max_length=254)),
                ('contact_phone', models.CharField(blank=True, max_length=20)),
                ('website', models.URLField(blank=True)),
                ('onboarding_status', models.CharField(choices=[('pending_review', 'Pending Review'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('needs_more_info', 'Needs More Info')], default='pending_review', max_length=20)),
                ('document_status', models.CharField(choices=[('missing', 'Missing'), ('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='missing', max_length=20)),
                ('onboarding_notes', models.TextField(blank=True)),
                ('bank_account_number', models.CharField(blank=True, max_length=50)),
                ('bank_name', models.CharField(blank=True, max_length=100)),
                ('account_holder_name', models.CharField(blank=True, max_length=255)),
                ('total_earnings', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('total_orders', models.IntegerField(default=0)),
                ('total_completed_orders', models.IntegerField(default=0)),
                ('permanently_banned', models.BooleanField(default=False)),
                ('ban_reason', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='vendor_profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Vendor',
                'verbose_name_plural': 'Vendors',
            },
        ),
        migrations.AddIndex(
            model_name='vendor',
            index=models.Index(fields=['onboarding_status'], name='vendors_oi_status_47c6e1_idx'),
        ),
        migrations.AddIndex(
            model_name='vendor',
            index=models.Index(fields=['category'], name='vendors_ca_category_0d2dd5_idx'),
        ),
        migrations.AddIndex(
            model_name='vendor',
            index=models.Index(fields=['created_at'], name='vendors_cr_created_4f4e52_idx'),
        ),
    ]
