from django.db import models
import uuid

class Feature(models.Model):
    """Features available in gym (sauna, swimming, classes, etc.)"""
    FEATURE_TYPES = [
        ('facility', 'Facility'),     # Sauna, Pool, etc.
        ('service', 'Service'),       # Personal Training, Massage
        ('class', 'Group Class'),     # Yoga, Zumba, etc.
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    feature_type = models.CharField(max_length=20, choices=FEATURE_TYPES)
    
    # Pricing for additional purchases
    price_per_session = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        ordering = ['feature_type', 'name']

class MembershipPlan(models.Model):
    """Membership plans with included features"""
    PLAN_TYPES = [
        ('basic', 'Basic Membership'),
        ('premium', 'Premium Membership'),
        ('personal_training', 'Personal Training'),
        ('combo', 'Combo Package'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    plan_type = models.CharField(max_length=20, choices=PLAN_TYPES)
    duration_days = models.IntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True)
    
    # Features included in this plan
    features = models.ManyToManyField(Feature, through='PlanFeature', blank=True)
    
    # Personal Training availability
    includes_personal_training = models.BooleanField(default=False)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} ({self.duration_days} days)"
    
    class Meta:
        ordering = ['plan_type', 'price']

class PlanFeature(models.Model):
    """Junction table - features included in each plan with allowances"""
    plan = models.ForeignKey(MembershipPlan, on_delete=models.CASCADE)
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE)
    
    # How many times this feature can be used
    allowed_uses = models.IntegerField(default=0, help_text="0 = unlimited")
    is_unlimited = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ['plan', 'feature']
    
    def __str__(self):
        uses_text = "Unlimited" if self.is_unlimited else f"{self.allowed_uses} uses"
        return f"{self.plan.name} - {self.feature.name} ({uses_text})"
