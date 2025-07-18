# subscriptions/views.py
from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction, models
from django.shortcuts import get_object_or_404
from subscriptions.models import Subscription, SubscriptionPlanChangeLog, SubscriptionHistory
from subscriptions.serializers import (
    SubscriptionSerializer, 
    EnrollSubscriptionSerializer,
    PlanChangeSerializer,
    SubscriptionHistorySerializer
)
from members.models import Member
from plans.models import MembershipPlan
from plans.serializers import MembershipPlanSerializer
from members.serializers import MemberSerializer
from rest_framework.permissions import IsAuthenticated
import datetime
from rest_framework import serializers
from django.conf import settings
from django.db.models import Prefetch, Q
from datetime import date, timedelta
import os

# Import the WhatsApp tasks
from .tasks import send_membership_enrolled_message, send_plan_change_notification

# --- Helper functions and placeholders for missing functions ---
def get_subscription_snapshot(subscription):
    # Placeholder: return serialized data or dict snapshot
    from subscriptions.serializers import SubscriptionSerializer
    return SubscriptionSerializer(subscription).data

def get_member_snapshot(member):
    # Placeholder: return serialized data or dict snapshot
    from members.serializers import MemberSerializer
    return MemberSerializer(member).data

# Placeholder for async notification task
def send_plan_renewal_notification(*args, **kwargs):
    class DummyTask:
        def delay(self, *a, **kw):
            print("DEBUG: send_plan_renewal_notification called (dummy)")
    return DummyTask()


class SubscriptionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    lookup_field = 'id'

    def _get_user_or_none(self, request):
        """Helper method to get user or None for anonymous users"""
        return None if request.user.is_anonymous else request.user

    def get_serializer_class(self):
        if self.action == 'enroll':
            return EnrollSubscriptionSerializer
        elif self.action == 'change_plan':
            return PlanChangeSerializer
        return SubscriptionSerializer

    def get_queryset(self):
        qs = Subscription.objects.select_related('member', 'plan').prefetch_related(
            'member__subscriptions'
        )
        
        # Filter by member
        member_id = self.request.query_params.get('member_id')
        if member_id:
            qs = qs.filter(member__id=member_id)
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        
        # Search by member name or phone
        query = self.request.query_params.get('q')
        if query:
            qs = qs.filter(
                models.Q(member__full_name__icontains=query) |
                models.Q(member__phone_number__icontains=query) |
                models.Q(member__biometric_id__icontains=query)
            )
        
        return qs

    @action(detail=False, methods=['post'])
    def enroll(self, request):
        """
        Enroll a member in a subscription plan - creates active subscription by default
        """
        print("DEBUG: enroll called with data:", request.data)
        import logging
        logger = logging.getLogger(__name__)
        logger.debug("enroll called with data: %s", request.data)

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            print("DEBUG: serializer errors:", serializer.errors)
            logger.error("serializer errors: %s", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            with transaction.atomic():
                # Create subscription with active status
                subscription = serializer.save(status='active')
                print("DEBUG: subscription created as active:", subscription)
                logger.info("subscription created as active: %s", subscription)
                
                # Create history entry
                SubscriptionHistory.objects.create(
                    subscription=subscription,
                    snapshot=SubscriptionSerializer(subscription).data,
                    member_snapshot=MemberSerializer(subscription.member).data,
                    note="Initial enrollment - subscription activated",
                    
                )
                print("DEBUG: SubscriptionHistory created for subscription id:", subscription.id)
                logger.info("SubscriptionHistory created for subscription id: %s", subscription.id)
                
                # Trigger WhatsApp message task after successful enrollment
                try:
                    send_membership_enrolled_message.delay(
                        member_id=str(subscription.member.id),
                        subscription_id=str(subscription.id)
                    )
                    print("DEBUG: WhatsApp task queued successfully")
                    logger.info("WhatsApp task queued for member: %s", subscription.member.full_name)
                except Exception as task_error:
                    print(f"DEBUG: Failed to queue WhatsApp task: {task_error}")
                    logger.error("Failed to queue WhatsApp task: %s", task_error)
                    # Don't fail the enrollment if WhatsApp task fails
                
            return Response(
                SubscriptionSerializer(subscription).data, 
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            print("DEBUG: Exception occurred:", str(e))
            logger.exception("Exception occurred during enrollment")
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def change_plan(self, request, pk=None):
        """
        Change subscription plan within grace period
        """
        subscription = self.get_object()
        serializer = self.get_serializer(
            data=request.data, 
            context={'subscription': subscription}
        )
        serializer.is_valid(raise_exception=True)
        
        new_plan_id = serializer.validated_data['new_plan_id']
        
        try:
            new_plan = MembershipPlan.objects.get(id=new_plan_id)
            old_plan_name = subscription.plan.name  # Store old plan name before change
            
            with transaction.atomic():
                # Create history before change
                SubscriptionHistory.objects.create(
                    subscription=subscription,
                    snapshot=SubscriptionSerializer(subscription).data,
                    member_snapshot=MemberSerializer(subscription.member).data,
                    note=f"Plan change from {subscription.plan.name} to {new_plan.name}",
                    
                )
                
                subscription.change_plan(new_plan, self._get_user_or_none(request))
                subscription.refresh_from_db()
                
                # Trigger plan change notification
                try:
                    send_plan_change_notification.delay(
                        member_id=str(subscription.member.id),
                        subscription_id=str(subscription.id),
                        old_plan_name=old_plan_name,
                        new_plan_name=new_plan.name
                    )
                    print("DEBUG: Plan change notification task queued successfully")
                except Exception as task_error:
                    print(f"DEBUG: Failed to queue plan change notification: {task_error}")
                    # Don't fail the plan change if notification task fails
                
            return Response(
                SubscriptionSerializer(subscription).data,
                status=status.HTTP_200_OK
            )
        except MembershipPlan.DoesNotExist:
            return Response(
                {'error': 'Plan not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except ValueError as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['patch'])
    def cancel(self, request, pk=None):
        """
        Cancel an active subscription
        """
        subscription = self.get_object()
        
        if subscription.status not in ['active', 'pending']:
            return Response(
                {'error': 'Only active or pending subscriptions can be cancelled'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            subscription.status = 'cancelled'
            subscription.save()
            
            # Create history entry
            SubscriptionHistory.objects.create(
                subscription=subscription,
                snapshot=SubscriptionSerializer(subscription).data,
                member_snapshot=MemberSerializer(subscription.member).data,
                note="Subscription cancelled",
            
            )
        
        return Response(
            SubscriptionSerializer(subscription).data,
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'])
    def available_plans(self, request):
        """
        Get all available membership plans
        """
        plans = MembershipPlan.objects.all()
        serializer = MembershipPlanSerializer(plans, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def member_lookup(self, request):
        """
        Look up member by ID, phone, or email for enrollment - OPTIMIZED
        """
        member_id = request.query_params.get('member_id')
        phone = request.query_params.get('phone')
        email = request.query_params.get('email')
        biometric_id = request.query_params.get('biometric_id')
        
        if not any([member_id, phone, email, biometric_id]):
            return Response(
                {'error': 'Please provide member_id, phone, email, or biometric_id'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Optimized query with proper prefetching
            member_qs = Member.objects.select_related().prefetch_related(
                Prefetch(
                    'subscriptions',
                    queryset=Subscription.objects.select_related('plan'),
                    to_attr='ordered_subscriptions'
                )
            )
            
            if member_id:
                member = member_qs.get(id=member_id)
            elif phone:
                member = member_qs.get(phone_number=phone)
            elif email:
                member = member_qs.get(email=email)
            elif biometric_id:
                member = member_qs.get(biometric_id=biometric_id)
                
            # Check if member already has active subscription using prefetched data
            active_subscription = None
            if hasattr(member, 'ordered_subscriptions'):
                for subscription in member.ordered_subscriptions:
                    if subscription.status == 'active':
                        active_subscription = subscription
                        break
            
            response_data = MemberSerializer(member).data
            response_data['has_active_subscription'] = bool(active_subscription)
            
            if active_subscription:
                response_data['active_subscription'] = SubscriptionSerializer(active_subscription).data
            
            return Response(response_data)
            
        except Member.DoesNotExist:
            return Response(
                {'error': 'Member not found'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=['get'])
    def enrollment_data(self, request):
        """
        Get all data needed for enrollment form (members + plans) - OPTIMIZED
        """
        member_id = request.query_params.get('member_id')
        
        response_data = {
            'plans': MembershipPlanSerializer(
                MembershipPlan.objects.all(), 
                many=True
            ).data
        }
        
        if member_id:
            try:
                # Optimized query with proper prefetching
                member = Member.objects.select_related().prefetch_related(
                    Prefetch(
                        'subscriptions',
                        queryset=Subscription.objects.select_related('plan').order_by('-created_at'),
                        to_attr='ordered_subscriptions'
                    )
                ).get(id=member_id)
                
                response_data['member'] = MemberSerializer(member).data
                
                # Check active subscription using prefetched data
                active_subscription = None
                if hasattr(member, 'ordered_subscriptions'):
                    for subscription in member.ordered_subscriptions:
                        if subscription.status == 'active':
                            active_subscription = subscription
                            break
                
                response_data['has_active_subscription'] = bool(active_subscription)
                if active_subscription:
                    response_data['active_subscription'] = SubscriptionSerializer(active_subscription).data
                    
            except Member.DoesNotExist:
                response_data['member'] = None
                response_data['error'] = 'Member not found'
        
        return Response(response_data)




    @action(detail=False, methods=['get'])
    def all_members(self, request):
        """
        Fetch ALL members with their membership status. 
        Fully optimized to avoid N+1 queries and return same payload structure.
        """
        today = date.today()
        week_from_now = today + timedelta(days=7)
        
        # Single optimized query to get all members with their subscriptions
        members_qs = Member.objects.select_related().prefetch_related(
            Prefetch(
                'subscriptions',
                queryset=Subscription.objects.select_related('plan'),
                to_attr='ordered_subscriptions'
            )
        ).order_by('-id')
        
        members_data = []
        
        for member in members_qs:
            latest_subscription = None
            active_subscription = None
            
            # Find active subscription first, then latest if no active
            if hasattr(member, 'ordered_subscriptions') and member.ordered_subscriptions:
                for sub in member.ordered_subscriptions:
                    if sub.status == 'active':
                        active_subscription = sub
                        break
                
                if not active_subscription:
                    latest_subscription = member.ordered_subscriptions[0]
            
            current_subscription = active_subscription or latest_subscription
            
            # Default values
            membership_status = "no_membership"
            membership_actions = ["assign_membership", "view", "payment"]
            status_color = "gray"
            
            # Get photo URL safely
            photo_url = None
            if member.profile_photo:
                try:
                    photo_url = member.profile_photo.url
                except (ValueError, AttributeError):
                    photo_url = None
            
            member_data = {
                'id': member.id,
                'member_id': getattr(member, 'member_id', f"00{member.id}"),
                'full_name': member.full_name,
                'email': member.email,
                'phone_number': member.phone_number,
                'address': getattr(member, 'address', ''),
                'biometric_id': member.biometric_id,
                'created_at': member.created_at,
                'photo_url': photo_url,
                'membership_status': membership_status,
                'status_color': status_color,
                'actions': membership_actions,
                'subscription': None
            }
            
            if current_subscription:
                days_remaining = None
                days_expired = None
                
                if current_subscription.end_date:
                    days_diff = (current_subscription.end_date - today).days
                    if days_diff >= 0:
                        days_remaining = days_diff
                    else:
                        days_expired = abs(days_diff)
                
                # Determine membership status
                if current_subscription.status == 'active':
                    if days_remaining is not None:
                        if days_remaining <= 0:
                            membership_status = "expired_today"
                            status_color = "red"
                            membership_actions = ["renewal", "view", "payment"]
                        elif days_remaining <= 7:
                            membership_status = "expiring_soon"
                            status_color = "orange"
                            membership_actions = ["renewal", "view", "payment"]
                        else:
                            membership_status = "active"
                            status_color = "green"
                            membership_actions = ["view", "payment", "renewal"]
                    else:
                        membership_status = "active"
                        status_color = "green"
                        membership_actions = ["view", "payment", "renewal"]
                        
                elif current_subscription.status == 'expired':
                    membership_status = "expired"
                    status_color = "red"
                    membership_actions = ["renewal", "assign_membership", "view", "payment"]
                    
                elif current_subscription.status == 'cancelled':
                    membership_status = "cancelled"
                    status_color = "red"
                    membership_actions = ["assign_membership", "view", "payment"]
                    
                else:
                    membership_status = "pending"
                    status_color = "yellow"
                    membership_actions = ["view", "payment", "renewal"]
                
                # Build subscription data
                member_data['subscription'] = {
                    'id': current_subscription.id,
                    'plan_name': current_subscription.plan.name,
                    'plan_id': current_subscription.plan.id,
                    'status': current_subscription.status,
                    'start_date': current_subscription.start_date,
                    'end_date': current_subscription.end_date,
                    'days_remaining': days_remaining,
                    'days_expired': days_expired,
                    'can_change_plan': current_subscription.can_change_plan() if hasattr(current_subscription, 'can_change_plan') and current_subscription.status == 'active' else False,
                    'is_in_grace_period': current_subscription.is_in_grace_period() if hasattr(current_subscription, 'is_in_grace_period') and current_subscription.status == 'active' else False,
                    'grace_period_days': getattr(current_subscription, 'grace_period_days', None),
                    'is_renewal': getattr(current_subscription, 'is_renewal', False)
                }
            
            # Update member data with final status
            member_data['membership_status'] = membership_status
            member_data['status_color'] = status_color
            member_data['actions'] = membership_actions
            
            members_data.append(member_data)
        
        # Count members by status
        status_counts = {
            'total': len(members_data),
            'active': len([m for m in members_data if m['membership_status'] == 'active']),
            'expired': len([m for m in members_data if m['membership_status'] in ['expired', 'expired_today']]),
            'expiring_soon': len([m for m in members_data if m['membership_status'] == 'expiring_soon']),
            'no_membership': len([m for m in members_data if m['membership_status'] == 'no_membership']),
            'cancelled': len([m for m in members_data if m['membership_status'] == 'cancelled']),
            'pending': len([m for m in members_data if m['membership_status'] == 'pending'])
        }
        
        return Response({
            'members': members_data,
            'counts': status_counts,
            'filters': {
                'status': None,
                'search': None
            }
        })

    @action(detail=False, methods=['get'])
    def active_members(self, request):
        """
        Get only members with active subscriptions - ALREADY OPTIMIZED
        """
        today = date.today()
        
        # Optimized query to get only members with active subscriptions
        members_qs = Member.objects.select_related().prefetch_related(
            Prefetch(
                'subscriptions',
                queryset=Subscription.objects.select_related('plan').filter(status='active'),
                to_attr='active_subscriptions'
            )
        ).filter(subscriptions__status='active').distinct().order_by('id')

        members_data = []

        for member in members_qs:
            if not hasattr(member, 'active_subscriptions') or not member.active_subscriptions:
                continue
                
            active_subscription = member.active_subscriptions[0]
            
            days_remaining = None
            if active_subscription.end_date:
                days_diff = (active_subscription.end_date - today).days
                if days_diff >= 0:
                    days_remaining = days_diff
            
            photo_url = None
            if member.profile_photo:
                try:
                    photo_url = member.profile_photo.url
                except (ValueError, AttributeError):
                    photo_url = None
            
            member_data = {
                'id': member.id,
                'member_id': getattr(member, 'member_id', f"00{member.id}"),
                'full_name': member.full_name,
                'email': member.email,
                'phone_number': member.phone_number,
                'address': getattr(member, 'address', ''),
                'biometric_id': member.biometric_id,
                'created_at': member.created_at,
                'photo_url': photo_url,
                'subscription': {
                    'id': active_subscription.id,
                    'plan_name': active_subscription.plan.name,
                    'plan_id': active_subscription.plan.id,
                    'status': active_subscription.status,
                    'start_date': active_subscription.start_date,
                    'end_date': active_subscription.end_date,
                    'days_remaining': days_remaining,
                    'can_change_plan': active_subscription.can_change_plan() if hasattr(active_subscription, 'can_change_plan') else False,
                    'is_in_grace_period': active_subscription.is_in_grace_period() if hasattr(active_subscription, 'is_in_grace_period') else False,
                    'grace_period_days': getattr(active_subscription, 'grace_period_days', None),
                    'is_renewal': getattr(active_subscription, 'is_renewal', False),
                    'plan_details': {
                        'id': active_subscription.plan.id,
                        'name': active_subscription.plan.name,
                        'description': getattr(active_subscription.plan, 'description', ''),
                        'price': getattr(active_subscription.plan, 'price', None),
                        'duration': getattr(active_subscription.plan, 'duration', None),
                        'duration_type': getattr(active_subscription.plan, 'duration_type', None),
                        'features': getattr(active_subscription.plan, 'features', []),
                        'is_active': getattr(active_subscription.plan, 'is_active', True),
                        'created_at': getattr(active_subscription.plan, 'created_at', None),
                        'updated_at': getattr(active_subscription.plan, 'updated_at', None)
                    }
                }
            }
            members_data.append(member_data)

        return Response({'members': members_data, 'count': len(members_data)})

    @action(detail=False, methods=['get'])
    def inactive_members(self, request):
        """
        List members whose latest subscription is expired (inactive members) - ALREADY OPTIMIZED
        """
        today = date.today()

        # Optimized query to get all members with their subscriptions
        members_qs = Member.objects.select_related().prefetch_related(
            Prefetch(
                'subscriptions',
                queryset=Subscription.objects.select_related('plan').order_by('-created_at'),
                to_attr='ordered_subscriptions'
            )
        ).order_by('-id')

        inactive_members_data = []

        for member in members_qs:
            if not hasattr(member, 'ordered_subscriptions') or not member.ordered_subscriptions:
                continue  # No subscriptions at all, skip

            latest_subscription = member.ordered_subscriptions[0]
            
            # Only include members whose latest subscription is expired
            if latest_subscription.status == 'expired':
                days_expired = None
                if latest_subscription.end_date:
                    days_diff = (latest_subscription.end_date - today).days
                    if days_diff < 0:
                        days_expired = abs(days_diff)

                photo_url = None
                if member.profile_photo:
                    try:
                        photo_url = member.profile_photo.url
                    except (ValueError, AttributeError):
                        photo_url = None

                member_data = {
                    'id': member.id,
                    'member_id': getattr(member, 'member_id', f"00{member.id}"),
                    'full_name': member.full_name,
                    'email': member.email,
                    'phone_number': member.phone_number,
                    'address': getattr(member, 'address', ''),
                    'biometric_id': member.biometric_id,
                    'created_at': member.created_at,
                    'photo_url': photo_url,
                    'subscription': {
                        'id': latest_subscription.id,
                        'plan_name': latest_subscription.plan.name,
                        'plan_id': latest_subscription.plan.id,
                        'status': latest_subscription.status,
                        'start_date': latest_subscription.start_date,
                        'end_date': latest_subscription.end_date,
                        'days_expired': days_expired,
                        'is_renewal': getattr(latest_subscription, 'is_renewal', False),
                        'plan_details': {
                            'id': latest_subscription.plan.id,
                            'name': latest_subscription.plan.name,
                            'description': getattr(latest_subscription.plan, 'description', ''),
                            'price': getattr(latest_subscription.plan, 'price', None),
                            'duration': getattr(latest_subscription.plan, 'duration', None),
                            'duration_type': getattr(latest_subscription.plan, 'duration_type', None),
                            'features': getattr(latest_subscription.plan, 'features', []),
                            'is_active': getattr(latest_subscription.plan, 'is_active', True),
                            'created_at': getattr(latest_subscription.plan, 'created_at', None),
                            'updated_at': getattr(latest_subscription.plan, 'updated_at', None)
                        }
                    }
                }
                inactive_members_data.append(member_data)

        return Response({'members': inactive_members_data, 'count': len(inactive_members_data)})


    @action(detail=False, methods=["get"])
    def expiring_members(self, request):
        today = date.today()
        five_days_ago = today - timedelta(days=5)

        members_qs = Member.objects.prefetch_related(
            Prefetch(
                'subscriptions',
                queryset=Subscription.objects.select_related('plan').filter(status='active'),
                to_attr='active_subscriptions'
            )
        ).distinct().order_by('subscriptions__end_date')


        members_data = []

        for member in members_qs:
            active_subs = getattr(member, 'active_subscriptions', [])
            if not active_subs:
                continue

            active_subscription = active_subs[0]
            if not (five_days_ago <= active_subscription.end_date <= today):
                continue

            days_remaining = (active_subscription.end_date - today).days
            if days_remaining < 0:
                days_remaining = 0 

            photo_url = member.photo.url if getattr(member, 'photo', None) else None

            member_data = {
                'id': member.id,
                'member_id': getattr(member, 'member_id', f"00{member.id}"),
                'full_name': member.full_name,
                'email': member.email,
                'phone_number': member.phone_number,
                'address': getattr(member, 'address', ''),
                'biometric_id': member.biometric_id,
                'created_at': member.created_at,
                'photo_url': photo_url,
                'subscription': {
                    'id': active_subscription.id,
                    'plan_name': active_subscription.plan.name,
                    'plan_id': active_subscription.plan.id,
                    'status': active_subscription.status,
                    'start_date': active_subscription.start_date,
                    'end_date': active_subscription.end_date,
                    'days_remaining': days_remaining,
                    'can_change_plan': active_subscription.can_change_plan() if hasattr(active_subscription, 'can_change_plan') else False,
                    'is_in_grace_period': active_subscription.is_in_grace_period() if hasattr(active_subscription, 'is_in_grace_period') else False,
                    'grace_period_days': getattr(active_subscription, 'grace_period_days', None),
                    'is_renewal': getattr(active_subscription, 'is_renewal', False),
                    'plan_details': {
                        'id': active_subscription.plan.id,
                        'name': active_subscription.plan.name,
                        'description': getattr(active_subscription.plan, 'description', ''),
                        'price': getattr(active_subscription.plan, 'price', None),
                        'duration': getattr(active_subscription.plan, 'duration', None),
                        'duration_type': getattr(active_subscription.plan, 'duration_type', None),
                        'features': getattr(active_subscription.plan, 'features', []),
                        'is_active': getattr(active_subscription.plan, 'is_active', True),
                        'created_at': getattr(active_subscription.plan, 'created_at', None),
                        'updated_at': getattr(active_subscription.plan, 'updated_at', None)
                    }
                }
            }
            members_data.append(member_data)

        return Response({'members': members_data, 'count': len(members_data)})

    @action(detail=False, methods=["get"])
    def newly_added_members(self, request):
        """
        Get members who have no active membership plan (newly added members waiting for plan assignment)
        This includes members with no subscriptions OR members whose subscriptions are not active
        """
        today = date.today()
        
        # Get all members with their subscriptions
        members_qs = Member.objects.select_related().prefetch_related(
            Prefetch(
                'subscriptions',
                queryset=Subscription.objects.select_related('plan'),
                to_attr='ordered_subscriptions'
            )
        ).order_by('-created_at')  # Most recently created first

        newly_added_members_data = []

        for member in members_qs:
            latest_subscription = None
            active_subscription = None
            
            # Find active subscription first, then latest if no active
            if hasattr(member, 'ordered_subscriptions') and member.ordered_subscriptions:
                for sub in member.ordered_subscriptions:
                    if sub.status == 'active':
                        active_subscription = sub
                        break
                
                if not active_subscription:
                    latest_subscription = member.ordered_subscriptions[0]
            
            current_subscription = active_subscription or latest_subscription
            
            # Only include members with no membership (no active plan)
            membership_status = "no_membership"
            
            if current_subscription:
                if current_subscription.status == 'active':
                    # Skip members with active subscriptions
                    continue
                elif current_subscription.status in ['expired', 'cancelled']:
                    # Skip members with expired/cancelled - they're not "newly added"
                    continue
                elif current_subscription.status == 'pending':
                    # Include pending subscriptions as they're waiting for activation
                    membership_status = "pending"
            
            # Get photo URL safely
            photo_url = None
            if member.profile_photo:
                try:
                    photo_url = member.profile_photo.url
                except (ValueError, AttributeError):
                    photo_url = None

            member_data = {
                'id': member.id,
                'member_id': getattr(member, 'member_id', f"00{member.id}"),
                'full_name': member.full_name,
                'email': member.email,
                'phone_number': member.phone_number,
                'address': getattr(member, 'address', ''),
                'biometric_id': member.biometric_id,
                'created_at': member.created_at,
                'join_date': getattr(member, 'join_date', member.created_at),
                'photo_url': photo_url,
                'membership_status': membership_status,
                'status_color': 'yellow' if membership_status == 'pending' else 'gray',
                'actions': ['assign_membership', 'view', 'payment'] if membership_status == 'no_membership' else ['view', 'payment', 'activate'],
                'subscription': None if not current_subscription else {
                    'id': current_subscription.id,
                    'plan_name': current_subscription.plan.name,
                    'plan_id': current_subscription.plan.id,
                    'status': current_subscription.status,
                    'start_date': current_subscription.start_date,
                    'end_date': current_subscription.end_date,
                    'days_remaining': None,
                    'can_change_plan': False,
                    'is_in_grace_period': False,
                    'grace_period_days': None,
                    'is_renewal': getattr(current_subscription, 'is_renewal', False),
                    'plan_details': {
                        'id': current_subscription.plan.id,
                        'name': current_subscription.plan.name,
                        'description': getattr(current_subscription.plan, 'description', ''),
                        'price': getattr(current_subscription.plan, 'price', None),
                        'duration': getattr(current_subscription.plan, 'duration', None),
                        'duration_type': getattr(current_subscription.plan, 'duration_type', None),
                        'features': getattr(current_subscription.plan, 'features', []),
                        'is_active': getattr(current_subscription.plan, 'is_active', True),
                        'created_at': getattr(current_subscription.plan, 'created_at', None),
                        'updated_at': getattr(current_subscription.plan, 'updated_at', None)
                    }
                }
            }
            newly_added_members_data.append(member_data)

        return Response({'members': newly_added_members_data, 'count': len(newly_added_members_data)}) 

    @action(detail=True, methods=['post'])
    def renew(self, request, pk=None):
        """
        Renew a subscription plan - creates a new subscription and marks current as completed
        Also allows creation of a PersonalTrainingProfile if pt_profile is provided.
        """
        current_subscription = self.get_object()
        
        # Validate that subscription can be renewed
        if current_subscription.status not in ['active', 'expired']:
            return Response(
                {'error': 'Only active or expired subscriptions can be renewed'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get renewal data
        new_plan_id = request.data.get('new_plan_id')
        start_date = request.data.get('start_date')
        pt_data = request.data.get('pt_profile', {})
        wants_personal_training = request.data.get('wants_personal_training', False)
        
        # Use current plan if no new plan specified
        if not new_plan_id:
            new_plan_id = current_subscription.plan.id
        
        # Use today as start date if not specified
        if not start_date:
            start_date = date.today()
        else:
            try:
                import datetime as dt
                start_date = dt.datetime.strptime(start_date, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Invalid date format. Use YYYY-MM-DD'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        try:
            new_plan = MembershipPlan.objects.get(id=new_plan_id)
        except MembershipPlan.DoesNotExist:
            return Response(
                {'error': 'Plan not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Prevent duplicate active subscription for the same member and plan with overlapping dates
        overlapping_sub = Subscription.objects.filter(
            member=current_subscription.member,
            plan=new_plan,
            status='active',
            end_date__gte=start_date
        ).exclude(id=current_subscription.id).first()
        if overlapping_sub:
            return Response(
                {'error': 'Duplicate active subscription exists for this member and plan with overlapping dates.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            with transaction.atomic():
                # Calculate new end date
                new_end_date = start_date + timedelta(days=new_plan.duration_days)
                
                # Create new subscription for renewal
                new_subscription = Subscription.objects.create(
                    member=current_subscription.member,
                    plan=new_plan,
                    start_date=start_date,
                    end_date=new_end_date,
                    status='active',
                    is_renewal=True,
                    wants_personal_training=wants_personal_training
                )
                
                # If PT details provided, create PT profile
                if wants_personal_training and pt_data:
                    from subscriptions.models import PersonalTrainingProfile
                    PersonalTrainingProfile.objects.create(
                        subscription=new_subscription,
                        has_medical_conditions=pt_data.get('has_medical_conditions', False),
                        medical_conditions=pt_data.get('medical_conditions', ''),
                        medications=pt_data.get('medications', ''),
                        injuries=pt_data.get('injuries', ''),
                        allergies=pt_data.get('allergies', ''),
                        chronic_diseases=pt_data.get('chronic_diseases', ''),
                        family_medical_history=pt_data.get('family_medical_history', ''),
                        recent_surgeries=pt_data.get('recent_surgeries', ''),
                        lifestyle=pt_data.get('lifestyle', ''),
                        sleep_quality=pt_data.get('sleep_quality', ''),
                        stress_level=pt_data.get('stress_level', ''),
                        diet=pt_data.get('diet', ''),
                        hydration=pt_data.get('hydration', ''),
                        doctor_clearance_required=pt_data.get('doctor_clearance_required', False),
                        fitness_goals=pt_data.get('fitness_goals', ''),
                        current_fitness_level=pt_data.get('current_fitness_level', 'beginner'),
                        exercise_experience=pt_data.get('exercise_experience', ''),
                        preferred_workout_times=pt_data.get('preferred_workout_times', ''),
                        emergency_contact_name=pt_data.get('emergency_contact_name', ''),
                        emergency_contact_phone=pt_data.get('emergency_contact_phone', ''),
                        emergency_contact_relationship=pt_data.get('emergency_contact_relationship', '')
                    )
                
                # Mark current subscription as completed
                # Your signal will automatically create history snapshot
                current_subscription.status = 'completed'
                current_subscription.save()
                
                # If plan changed, log it
                if new_plan.id != current_subscription.plan.id:
                    SubscriptionPlanChangeLog.objects.create(
                        subscription=new_subscription,
                        old_plan=current_subscription.plan,
                        new_plan=new_plan,
                        changed_by=self._get_user_or_none(request),
                        change_reason='Plan renewal with plan change'
                    )
                
                # Manual history entry for the new subscription (since it's new, signal won't capture it)
                SubscriptionHistory.objects.create(
                    subscription=new_subscription,
                    snapshot=get_subscription_snapshot(new_subscription),
                    member_snapshot=get_member_snapshot(new_subscription.member),
                    note=f"Plan renewed - new subscription created with {new_plan.name}"
                )
                
                # Trigger renewal notification
                try:
                    send_plan_renewal_notification.delay(
                        member_id=str(current_subscription.member.id),
                        old_subscription_id=str(current_subscription.id),
                        new_subscription_id=str(new_subscription.id),
                        old_plan_name=current_subscription.plan.name,
                        new_plan_name=new_plan.name,
                        plan_changed=new_plan.id != current_subscription.plan.id
                    )
                    print("DEBUG: Plan renewal notification task queued successfully")
                except Exception as task_error:
                    print(f"DEBUG: Failed to queue plan renewal notification: {task_error}")
                    # Don't fail the renewal if notification task fails
                
                return Response({
                    'message': 'Plan renewed successfully',
                    'renewal_details': {
                        'old_subscription': {
                            'id': current_subscription.id,
                            'plan_name': current_subscription.plan.name,
                            'start_date': current_subscription.start_date,
                            'end_date': current_subscription.end_date,
                            'status': current_subscription.status,
                            'duration_days': current_subscription.plan.duration_days,
                            'price': current_subscription.plan.price
                        },
                        'new_subscription': {
                            'id': new_subscription.id,
                            'plan_name': new_subscription.plan.name,
                            'start_date': new_subscription.start_date,
                            'end_date': new_subscription.end_date,
                            'status': new_subscription.status,
                            'duration_days': new_subscription.plan.duration_days,
                            'price': new_subscription.plan.price
                        },
                        'member_details': {
                            'id': current_subscription.member.id,
                            'full_name': current_subscription.member.full_name,
                            'email': current_subscription.member.email,
                            'phone_number': current_subscription.member.phone_number,
                            'biometric_id': current_subscription.member.biometric_id,
                            'photo_url': current_subscription.member.profile_photo.url if current_subscription.member.profile_photo else None
                        },
                        'renewal_info': {
                            'plan_changed': new_plan.id != current_subscription.plan.id,
                            'price_difference': float(new_plan.price - current_subscription.plan.price),
                            'duration_difference': new_plan.duration_days - current_subscription.plan.duration_days,
                            'renewal_date': date.today(),
                            'days_extended': new_plan.duration_days
                        }
                    }
                }, status=status.HTTP_201_CREATED)
                
        except Exception as e:
            print(f"DEBUG: Exception during renewal: {str(e)}")
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )



    @action(detail=False, methods=['get'])
    def member_subscription_history(self, request):
        """
        Get subscription history for a member with thermal printer invoice format
        """
        member_id = request.query_params.get('member_id')
        if not member_id:
            return Response(
                {'error': 'member_id is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            member = Member.objects.get(id=member_id)
        except Member.DoesNotExist:
            return Response(
                {'error': 'Member not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get all subscriptions for the member
        subscriptions = Subscription.objects.filter(
            member=member
        ).select_related('plan').order_by('-start_date')
        
        # Get current active subscription
        current_subscription = subscriptions.filter(status='active').first()
        
        # Prepare subscription history data
        history_data = []
        total_paid = 0
        
        for subscription in subscriptions:
            subscription_data = {
                'id': subscription.id,
                'plan_name': subscription.plan.name,
                'plan_price': float(subscription.plan.price),
                'duration_days': subscription.plan.duration_days,
                'start_date': subscription.start_date,
                'end_date': subscription.end_date,
                'status': subscription.status,
                'is_renewal': subscription.is_renewal,
                'created_at': subscription.created_at,
                'formatted_duration': f"{subscription.plan.duration_days} days"
            }
            
            # Add to total if subscription was paid (active, expired, or completed)
            if subscription.status in ['active', 'expired', 'completed']:
                total_paid += float(subscription.plan.price)
                subscription_data['paid'] = True
            else:
                subscription_data['paid'] = False
            
            history_data.append(subscription_data)
        
        # Generate thermal printer invoice format
        invoice_text = generate_thermal_invoice(member, history_data, current_subscription, total_paid)
        
        return Response({
            'member': {
                'id': member.id,
                'full_name': member.full_name,
                'email': member.email,
                'phone_number': member.phone_number,
                'biometric_id': member.biometric_id,
                'member_id': getattr(member, 'member_id', f"00{member.id}"),
                'created_at': member.created_at
            },
            'current_subscription': SubscriptionSerializer(current_subscription).data if current_subscription else None,
            'subscription_history': history_data,
            'summary': {
                'total_subscriptions': len(history_data),
                'total_paid': total_paid,
                'active_subscriptions': len([s for s in history_data if s['status'] == 'active']),
                'expired_subscriptions': len([s for s in history_data if s['status'] == 'expired']),
                'cancelled_subscriptions': len([s for s in history_data if s['status'] == 'cancelled'])
            },
            'thermal_invoice': invoice_text
        })
    @action(detail=True, methods=['get'])
    def subscription_invoice(self, request, id=None):
        """
        Get thermal printer invoice for a specific subscription
        """
        subscription = self.get_object()
        member = subscription.member
        
        # Generate simple invoice for single subscription
        invoice_text = generate_single_subscription_invoice(subscription, member)
        
        return Response({
            'invoice_text': invoice_text,
            'subscription_id': subscription.id,
            'member_name': member.full_name,
            'plan_name': subscription.plan.name,
            'amount': float(subscription.plan.price),
            'start_date': subscription.start_date,
            'end_date': subscription.end_date,
            'status': subscription.status
        })

# Place these at the module level, outside any class

def generate_single_subscription_invoice(subscription, member):
    """
    Generate thermal printer format invoice for a single subscription
    """
    from datetime import datetime
    width = 40
    invoice_lines = []
    invoice_lines.append("=" * width)
    invoice_lines.append("MEMBERSHIP RECEIPT".center(width))
    invoice_lines.append("=" * width)
    invoice_lines.append("")
    invoice_lines.append("Club 7 Gym".center(width))
    invoice_lines.append("Sulthan bathery, Wayanad".center(width))
    invoice_lines.append("")
    invoice_lines.append("-" * width)
    invoice_lines.append("MEMBER:")
    invoice_lines.append(f"ID: {getattr(member, 'member_id', f'00{member.id}')}")
    invoice_lines.append(f"Name: {member.full_name}")
    invoice_lines.append(f"Phone: {member.phone_number}")
    if member.email:
        invoice_lines.append(f"Email: {member.email}")
    if member.biometric_id:
        invoice_lines.append(f"Biometric: {member.biometric_id}")
    invoice_lines.append("")
    invoice_lines.append("SUBSCRIPTION DETAILS:")
    invoice_lines.append(f"Plan: {subscription.plan.name}")
    invoice_lines.append(f"Duration: {subscription.plan.duration_days} days")
    invoice_lines.append(f"Start Date: {subscription.start_date}")
    invoice_lines.append(f"End Date: {subscription.end_date}")
    invoice_lines.append(f"Status: {subscription.status.upper()}")
    invoice_lines.append("")
    invoice_lines.append("-" * width)
    invoice_lines.append("PAYMENT INFORMATION:")
    invoice_lines.append(f"Amount: ${subscription.plan.price:.2f}")
    invoice_lines.append(f"Payment Date: {subscription.created_at.strftime('%m/%d/%Y')}")
    invoice_lines.append(f"Transaction ID: SUB-{subscription.id}")
    invoice_lines.append("")
    if subscription.status == 'active':
        if hasattr(subscription, 'grace_period_days') and subscription.grace_period_days:
            invoice_lines.append("GRACE PERIOD:")
            invoice_lines.append(f"Grace Days: {subscription.grace_period_days}")
            if hasattr(subscription, 'is_in_grace_period'):
                grace_status = "Yes" if subscription.is_in_grace_period() else "No"
                invoice_lines.append(f"In Grace Period: {grace_status}")
            invoice_lines.append("")
    invoice_lines.append("-" * width)
    invoice_lines.append(f"Printed: {datetime.now().strftime('%m/%d/%Y %H:%M:%S')}")
    invoice_lines.append("")
    invoice_lines.append("Thank you for your membership!".center(width))
    invoice_lines.append("Please keep this receipt safe".center(width))
    invoice_lines.append("")
    invoice_lines.append("=" * width)
    return "\n".join(invoice_lines)

def generate_thermal_invoice(member, history_data, current_subscription, total_paid):
    """
    Generate thermal printer invoice format for a member's history
    """
    from datetime import datetime
    width = 40
    invoice_lines = []
    
    # Header
    invoice_lines.append("=" * width)
    invoice_lines.append("MEMBERSHIP RECEIPT".center(width))
    invoice_lines.append("=" * width)
    invoice_lines.append("")
    invoice_lines.append("Club 7 Gym".center(width))
    invoice_lines.append("Sulthan bathery, Wayanad".center(width))
    invoice_lines.append("")
    
    # Member Information
    invoice_lines.append("-" * width)
    invoice_lines.append("MEMBER:")
    invoice_lines.append(f"ID: {getattr(member, 'member_id', f'00{member.id}')}")
    invoice_lines.append(f"Name: {member.full_name}")
    invoice_lines.append(f"Phone: {member.phone_number}")
    if member.email:
        invoice_lines.append(f"Email: {member.email}")
    if member.biometric_id:
        invoice_lines.append(f"Biometric: {member.biometric_id}")
    invoice_lines.append("")
    
    # Current Subscription
    if current_subscription:
        invoice_lines.append("-" * width)
        invoice_lines.append("CURRENT SUBSCRIPTION:")
        invoice_lines.append(f"Plan: {current_subscription.plan.name}")
        invoice_lines.append(f"Start Date: {current_subscription.start_date}")
        invoice_lines.append(f"End Date: {current_subscription.end_date}")
        invoice_lines.append(f"Status: {current_subscription.status.upper()}")
        invoice_lines.append("")
    
    # Subscription History
    invoice_lines.append("-" * width)
    invoice_lines.append("SUBSCRIPTION HISTORY:")
    for item in history_data:
        status_text = item['status'].upper()
        if item['paid']:
            status_text += " (PAID)"
        line = f"{item['plan_name']} - {item['start_date']} to"
        invoice_lines.append(line[:width])
        line2 = f"{item['end_date']} ({item['formatted_duration']})"
        invoice_lines.append(line2[:width])
        invoice_lines.append(f"Status: {status_text}")
        if item['paid']:
            invoice_lines.append(f"  Amount: ${item['plan_price']:.2f}")
        invoice_lines.append("")
    
    # Summary
    invoice_lines.append("-" * width)
    invoice_lines.append("SUMMARY:")
    invoice_lines.append(f"Total Paid: ${total_paid:.2f}")
    invoice_lines.append(f"Total Subscriptions: {len(history_data)}")
    invoice_lines.append(f"Active Subscriptions: {len([s for s in history_data if s['status'] == 'active'])}")
    invoice_lines.append(f"Expired Subscriptions: {len([s for s in history_data if s['status'] == 'expired'])}")
    invoice_lines.append(f"Cancelled Subscriptions: {len([s for s in history_data if s['status'] == 'cancelled'])}")
    invoice_lines.append("-" * width)
    invoice_lines.append(f"Printed: {datetime.now().strftime('%m/%d/%Y %H:%M:%S')}")
    invoice_lines.append("")
    invoice_lines.append("Thank you for your membership!".center(width))
    invoice_lines.append("Please keep this receipt safe".center(width))
    invoice_lines.append("")
    invoice_lines.append("=" * width)
    
    return "\n".join(invoice_lines)