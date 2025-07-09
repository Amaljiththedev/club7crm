from django.db import models
from django.utils.timezone import now, timedelta
import uuid

class Subscription(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    member = models.ForeignKey('members.Member', on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey('plans.MembershipPlan', on_delete=models.PROTECT, related_name='subscriptions')

    start_date = models.DateField(default=now)
    end_date = models.DateField(blank=True, null=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    is_renewal = models.BooleanField(default=False)

    signed_by_member = models.BooleanField(default=False)
    signature_file = models.FileField(upload_to='signatures/', blank=True, null=True)

    member_snapshot = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Grace period logic ---
    @property
    def grace_period_days(self):
        return 30 if self.plan.duration_days >= 365 else 10

    def is_in_grace_period(self):
        grace_until = self.start_date + timedelta(days=self.grace_period_days)
        return now().date() <= grace_until

    def can_change_plan(self):
        return self.status == 'active' and self.is_in_grace_period()

    def change_plan(self, new_plan, changed_by):
        if not self.can_change_plan():
            raise ValueError("Plan change not allowed. Grace period expired.")

        if self.plan == new_plan:
            raise ValueError("New plan is same as current plan.")

        # Log the change
        SubscriptionPlanChangeLog.objects.create(
            subscription=self,
            old_plan=self.plan,
            new_plan=new_plan,
            changed_by=changed_by
        )

        # Update plan (keep start/end unchanged)
        self.plan = new_plan
        self.save()

    def save(self, *args, **kwargs):
        # Calculate end_date from plan only on first save
        if not self.end_date and self.plan and self.start_date:
            self.end_date = self.start_date + timedelta(days=self.plan.duration_days)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.member.full_name} - {self.plan.name} ({self.status})"

    class Meta:
        ordering = ['-start_date']
        verbose_name = 'Subscription'
        verbose_name_plural = 'Subscriptions'


class SubscriptionPlanChangeLog(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='plan_change_logs')
    old_plan = models.ForeignKey('plans.MembershipPlan', on_delete=models.SET_NULL, null=True, related_name='+')
    new_plan = models.ForeignKey('plans.MembershipPlan', on_delete=models.SET_NULL, null=True, related_name='+')
    changed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.subscription.member.full_name}: {self.old_plan.name} → {self.new_plan.name} on {self.changed_at.date()}"

    class Meta:
        ordering = ['-changed_at']
        verbose_name = 'Subscription Plan Change Log'


class SubscriptionHistory(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='history')
    snapshot = models.JSONField(help_text="Snapshot of the subscription at this point")
    member_snapshot = models.JSONField(help_text="Snapshot of the member at this point")
    note = models.TextField(blank=True, help_text="Optional context (e.g., 'plan changed during grace')")
    created_at = models.DateTimeField(auto_now_add=True)



    
    def __str__(self):
        return f"History: {self.subscription.member.full_name} on {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Subscription History'
