from django.db import models

# Create your models here.

class MembershipPlan(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    name = models.CharField(max_length=255)
    duration_days = models.IntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    type = models.CharField(max_length=50, help_text='Membership or PT')
    description = models.TextField()
    features = models.JSONField(default=list, blank=True, help_text='List of features for this plan')

    def __str__(self):
        return self.name
