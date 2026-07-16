from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='cancelled_by',
            field=models.CharField(
                blank=True,
                choices=[
                    ('customer', 'Customer'),
                    ('provider', 'Provider'),
                    ('system', 'System'),
                    ('admin', 'Admin'),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='cancellation_fee_owed',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='cancellation_fee_logged_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='provider_last_ping_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='booking',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('accepted', 'Accepted'),
                    ('in_progress', 'In Progress'),
                    ('completed', 'Completed'),
                    ('cancelled', 'Cancelled'),
                    ('disputed', 'Disputed'),
                    ('admin_review', 'Admin Review'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name='booking',
            index=models.Index(fields=['provider_last_ping_at'], name='bookings_provider_ping_idx'),
        ),
    ]
