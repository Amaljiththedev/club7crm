from django.db.models.signals import pre_save
from django.dispatch import receiver
from subscriptions.models import Subscription, SubscriptionHistory, SubscriptionPlanChangeLog
from django.utils.timezone import now, timedelta





def get_member_snapshot(member):
    return {
        "full_name": member.full_name,
        "email": member.email,
        "phone_number": member.phone_number,
        "alternate_phone": member.alternate_phone,
        "dob": str(member.dob),
        "gender": member.get_gender_display(),
        "marital_status": member.get_marital_status_display() if member.marital_status else None,
        "occupation": member.occupation,
        "profession": member.profession,
        "referral_source": member.get_referral_source_display() if member.referral_source else None,
        "firm_name": member.firm_name,
        "area_or_locality": member.area_or_locality,
        "address": {
            "line1": member.address_line_1,
            "line2": member.address_line_2,
            "city": member.city,
            "district": member.district,
            "state": member.state,
            "pin_code": member.pin_code,
        },
        "height_cm": member.height_cm,
        "weight_kg": member.weight_kg,
        "bmi": member.bmi,
        "biometric_id": member.biometric_id,
        "profile_photo": member.profile_photo.url if member.profile_photo else None,
        "join_date": str(member.join_date),
        "is_active": member.is_active,
    }

def get_subscription_snapshot(subscription: Subscription):
    return {
        "subscription_id": str(subscription.id),
        "member_id": subscription.member.id,
        "plan_id": subscription.plan.id,
        "plan_name": subscription.plan.name,
        "start_date": str(subscription.start_date),
        "end_date": str(subscription.end_date),
        "status": subscription.status,
        "is_renewal": subscription.is_renewal,
        "signed_by_member": subscription.signed_by_member,
        "created_at": str(subscription.created_at),
        "updated_at": str(subscription.updated_at),
    }

@receiver(pre_save, sender=Subscription)
def snapshot_before_subscription_update(sender, instance, **kwargs):
    if not instance.pk:
        return  # Skip new subscriptions

    try:
        old = Subscription.objects.get(pk=instance.pk)
    except Subscription.DoesNotExist:
        return

    plan_changed = old.plan != instance.plan
    status_changed = old.status != instance.status
    other_changes = (
        old.start_date != instance.start_date or
        old.end_date != instance.end_date or
        old.is_renewal != instance.is_renewal
    )

    if plan_changed or status_changed or other_changes:
        note = ""

        # If plan changed during grace, log it separately too
        if plan_changed and old.status == "active":
            grace_days = 30 if old.plan.duration_days >= 365 else 10
            grace_end = old.start_date + timedelta(days=grace_days)
            if now().date() <= grace_end:
                note = "Plan changed during grace period"

                # Auto-log plan change
                SubscriptionPlanChangeLog.objects.create(
                    subscription=old,
                    old_plan=old.plan,
                    new_plan=instance.plan,
                    changed_by=None  # Or use `threadlocals` if tracking user
                )

        SubscriptionHistory.objects.create(
            subscription=old,
            snapshot=get_subscription_snapshot(old),
            member_snapshot=get_member_snapshot(old.member),
            note=note or "Subscription updated"
        )
