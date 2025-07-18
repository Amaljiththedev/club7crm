# subscriptions/serializers.py
from rest_framework import serializers
from django.db import transaction
from subscriptions.models import Subscription, SubscriptionHistory
from members.models import Member
from plans.models import MembershipPlan
from members.serializers import MemberSerializer
from plans.serializers import MembershipPlanSerializer
import datetime

class DateFromDateTimeField(serializers.DateField):
    """Custom field that handles both date and datetime inputs"""
    def to_internal_value(self, value):
        if isinstance(value, datetime.datetime):
            value = value.date()
        elif isinstance(value, str) and 'T' in value:
            # Handle ISO datetime string
            value = value.split('T')[0]
        return super().to_internal_value(value)

class SubscriptionSerializer(serializers.ModelSerializer):
    member = MemberSerializer(read_only=True)
    plan = MembershipPlanSerializer(read_only=True)
    grace_period_days = serializers.ReadOnlyField()
    is_in_grace_period = serializers.ReadOnlyField()
    can_change_plan = serializers.ReadOnlyField()
    start_date = DateFromDateTimeField()
    end_date = DateFromDateTimeField()
    
    class Meta:
        model = Subscription
        fields = [
            'id', 'member', 'plan', 'start_date', 'end_date', 
            'status', 'is_renewal', 'signed_by_member', 'signature_file',
            'member_snapshot', 'created_at', 'updated_at',
            'grace_period_days', 'is_in_grace_period', 'can_change_plan'
        ]


class EnrollSubscriptionSerializer(serializers.Serializer):
    member_id = serializers.IntegerField()
    plan_id = serializers.UUIDField()
    start_date = DateFromDateTimeField(required=False)  # Add this field
    status = serializers.CharField(default='pending', required=False)
    is_renewal = serializers.BooleanField(default=False, required=False)
    signed_by_member = serializers.BooleanField(default=False, required=False)
    signature_file = serializers.FileField(required=False, allow_null=True)

    def to_internal_value(self, data):
        # Handle array inputs (common with FormData)
        data = data.copy() if hasattr(data, 'copy') else dict(data)
        for key in ['member_id', 'plan_id']:
            value = data.get(key)
            if isinstance(value, list):
                data[key] = value[0]
        return super().to_internal_value(data)

    def validate_member_id(self, value):
        if not Member.objects.filter(id=value).exists():
            raise serializers.ValidationError("Member with this ID does not exist.")
        return value

    def validate_plan_id(self, value):
        try:
            MembershipPlan.objects.get(id=value)
            return value
        except MembershipPlan.DoesNotExist:
            raise serializers.ValidationError("Plan not found")

    def validate(self, attrs):
        member_id = attrs.get('member_id')
        
        # Check if member already has an active subscription
        if Subscription.objects.filter(member_id=member_id, status='active').exists():
            raise serializers.ValidationError("Member already has an active subscription")
        
        # Set default start_date if not provided
        if 'start_date' not in attrs or attrs['start_date'] is None:
            attrs['start_date'] = datetime.date.today()
        
        return attrs

    def create(self, validated_data):
        member_id = validated_data.pop('member_id')
        plan_id = validated_data.pop('plan_id')
        
        member = Member.objects.get(id=member_id)
        plan = MembershipPlan.objects.get(id=plan_id)
        
        # Calculate end_date based on plan duration
        start_date = validated_data.pop('start_date', datetime.date.today())
        end_date = start_date + datetime.timedelta(days=plan.duration_days)
        
        # Store member snapshot
        member_snapshot = MemberSerializer(member).data
        
        subscription = Subscription.objects.create(
            member=member,
            plan=plan,
            start_date=start_date,
            end_date=end_date,
            member_snapshot=member_snapshot,
            **validated_data
        )
        
        return subscription


class PlanChangeSerializer(serializers.Serializer):
    new_plan_id = serializers.UUIDField()
    
    def validate_new_plan_id(self, value):
        try:
            MembershipPlan.objects.get(id=value)
            return value
        except MembershipPlan.DoesNotExist:
            raise serializers.ValidationError("Plan not found")
    
    def validate(self, attrs):
        subscription = self.context.get('subscription')
        new_plan_id = attrs.get('new_plan_id')
        
        if not subscription:
            raise serializers.ValidationError("Subscription context required")
        
        if not subscription.can_change_plan():
            raise serializers.ValidationError("Plan change not allowed. Grace period expired or subscription not active.")
        
        if str(subscription.plan.id) == str(new_plan_id):
            raise serializers.ValidationError("New plan is same as current plan")
        
        return attrs


class SubscriptionHistorySerializer(serializers.ModelSerializer):
    changed_by_username = serializers.SerializerMethodField()
    
    class Meta:
        model = SubscriptionHistory
        fields = [
            'id', 'subscription', 'snapshot', 'member_snapshot', 
            'note', 'created_at', 'changed_by', 'changed_by_username'
        ]
    
    def get_changed_by_username(self, obj):
        return obj.changed_by.username if obj.changed_by else None


class SubscriptionListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing subscriptions"""
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    member_phone = serializers.CharField(source='member.phone_number', read_only=True)
    member_biometric_id = serializers.CharField(source='member.biometric_id', read_only=True)
    plan_name = serializers.CharField(source='plan.name', read_only=True)
    plan_duration = serializers.IntegerField(source='plan.duration_days', read_only=True)
    start_date = DateFromDateTimeField(read_only=True)
    end_date = DateFromDateTimeField(read_only=True)
    
    class Meta:
        model = Subscription
        fields = [
            'id', 'member_name', 'member_phone', 'member_biometric_id',
            'plan_name', 'plan_duration', 'start_date', 'end_date', 
            'status', 'is_renewal', 'created_at'
        ]



class RenewalSerializer(serializers.Serializer):
    new_plan_id = serializers.UUIDField(required=False, help_text="New plan ID. If not provided, current plan will be used")
    start_date = serializers.DateField(required=False, help_text="Start date for renewal. If not provided, today will be used")
    
    def validate_start_date(self, value):
        if value and value < date.today():
            raise serializers.ValidationError("Start date cannot be in the past")
        return value
    
    def validate_new_plan_id(self, value):
        if value:
            try:
                MembershipPlan.objects.get(id=value)
            except MembershipPlan.DoesNotExist:
                raise serializers.ValidationError("Plan does not exist")
        return value


# Update your get_serializer_class method to include renewal
def get_serializer_class(self):
    if self.action == 'enroll':
        return EnrollSubscriptionSerializer
    elif self.action == 'change_plan':
        return PlanChangeSerializer
    elif self.action == 'renew':
        return RenewalSerializer
    return SubscriptionSerializer