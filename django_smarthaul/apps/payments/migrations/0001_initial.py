from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ('bookings', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('completed', 'Completed'), ('failed', 'Failed'), ('cancelled', 'Cancelled'), ('refunded', 'Refunded')], default='pending', max_length=20)),
                ('gateway', models.CharField(choices=[('flutterwave', 'Flutterwave'), ('stripe', 'Stripe'), ('paypal', 'PayPal')], default='flutterwave', max_length=20)),
                ('external_reference', models.CharField(blank=True, db_index=True, max_length=255)),
                ('transaction_id', models.CharField(blank=True, max_length=255)),
                ('integration_status', models.CharField(choices=[('pending', 'Pending'), ('initiated', 'Initiated'), ('completed', 'Completed'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('escrow_status', models.CharField(choices=[('held', 'Held'), ('released', 'Released'), ('refunded', 'Refunded')], default='held', max_length=20)),
                ('payout_status', models.CharField(choices=[('pending', 'Pending'), ('released', 'Released'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('payout_release_at', models.DateTimeField(blank=True, null=True)),
                ('payout_released_at', models.DateTimeField(blank=True, null=True)),
                ('commission_amount', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('commission_rate', models.FloatField(default=0.1)),
                ('attempted_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('booking', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='payment', to='bookings.booking')),
            ],
            options={
                'verbose_name': 'Payment',
                'verbose_name_plural': 'Payments',
            },
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['status'], name='payments_status_1c0c7a_idx'),
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['external_reference'], name='payments_externa_6a7d4d_idx'),
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['payout_status'], name='payments_payout_4e3d6a_idx'),
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['created_at'], name='payments_created_0fbf8d_idx'),
        ),
    ]
