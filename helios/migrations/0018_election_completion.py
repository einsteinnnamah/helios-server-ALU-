import datetime
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('helios', '0017_verification_wakeup')]
    operations = [migrations.CreateModel(name='ElectionCompletionJob', fields=[
        ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('state', models.CharField(default='pending', max_length=12)),
        ('attempts', models.PositiveIntegerField(default=0)),
        ('next_attempt_at', models.DateTimeField(db_index=True, default=datetime.datetime.utcnow)),
        ('lease', models.UUIDField(null=True)),
        ('lease_until', models.DateTimeField(null=True)),
        ('payload', models.JSONField(null=True)),
        ('saved_at', models.DateTimeField(null=True)),
        ('last_error_code', models.CharField(blank=True, default='', max_length=80)),
        ('election', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='completion_job', to='helios.election')),
    ])]
