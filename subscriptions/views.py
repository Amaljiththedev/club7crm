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


class SubscriptionViewSet(viewsets.ModelViewSet):
    queryset = Subscription.objects.all().order_by('-created_at')
    serializer_class = SubscriptionSerializer

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
        qs = Subscription.objects.all()
        
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
        
        return qs.order_by('-created_at')

    @action(detail=False, methods=['post'])
    def enroll(self, request):
        """
        Enroll a member in a subscription plan
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            with transaction.atomic():
                subscription = serializer.save()
                
                # Create history entry
                SubscriptionHistory.objects.create(
                    subscription=subscription,
                    snapshot=SubscriptionSerializer(subscription).data,
                    member_snapshot=MemberSerializer(subscription.member).data,
                    note="Initial enrollment",
                    changed_by=self._get_user_or_none(request)
                )
                
            return Response(
                SubscriptionSerializer(subscription).data, 
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
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
            
            with transaction.atomic():
                # Create history before change
                SubscriptionHistory.objects.create(
                    subscription=subscription,
                    snapshot=SubscriptionSerializer(subscription).data,
                    member_snapshot=MemberSerializer(subscription.member).data,
                    note=f"Plan change from {subscription.plan.name} to {new_plan.name}",
                    changed_by=self._get_user_or_none(request)
                )
                
                subscription.change_plan(new_plan, self._get_user_or_none(request))
                subscription.refresh_from_db()
                
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
    def activate(self, request, pk=None):
        """
        Activate a pending subscription
        """
        subscription = self.get_object()
        
        if subscription.status != 'pending':
            return Response(
                {'error': 'Only pending subscriptions can be activated'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            subscription.status = 'active'
            subscription.save()
            
            # Create history entry
            SubscriptionHistory.objects.create(
                subscription=subscription,
                snapshot=SubscriptionSerializer(subscription).data,
                member_snapshot=MemberSerializer(subscription.member).data,
                note="Subscription activated",
                changed_by=self._get_user_or_none(request)
            )
        
        return Response(
            SubscriptionSerializer(subscription).data,
            status=status.HTTP_200_OK
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
                changed_by=self._get_user_or_none(request)
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
        Look up member by ID, phone, or email for enrollment
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
            if member_id:
                member = Member.objects.get(id=member_id)
            elif phone:
                member = Member.objects.get(phone_number=phone)
            elif email:
                member = Member.objects.get(email=email)
            elif biometric_id:
                member = Member.objects.get(biometric_id=biometric_id)
                
            # Check if member already has active subscription
            active_subscription = Subscription.objects.filter(
                member=member, 
                status='active'
            ).first()
            
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
        Get all data needed for enrollment form (members + plans)
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
                member = Member.objects.get(id=member_id)
                response_data['member'] = MemberSerializer(member).data
                
                # Check active subscription
                active_subscription = Subscription.objects.filter(
                    member=member, 
                    status='active'
                ).first()
                
                response_data['has_active_subscription'] = bool(active_subscription)
                if active_subscription:
                    response_data['active_subscription'] = SubscriptionSerializer(active_subscription).data
                    
            except Member.DoesNotExist:
                response_data['member'] = None
                response_data['error'] = 'Member not found'
        
        return Response(response_data)

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """
        Get subscription history
        """
        subscription = self.get_object()
        history = SubscriptionHistory.objects.filter(subscription=subscription)
        serializer = SubscriptionHistorySerializer(history, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def plan_change_logs(self, request, pk=None):
        """
        Get plan change logs for a subscription
        """
        subscription = self.get_object()
        logs = SubscriptionPlanChangeLog.objects.filter(subscription=subscription)
        
        logs_data = []
        for log in logs:
            logs_data.append({
                'id': log.id,
                'old_plan': {
                    'id': log.old_plan.id,
                    'name': log.old_plan.name
                } if log.old_plan else None,
                'new_plan': {
                    'id': log.new_plan.id,
                    'name': log.new_plan.name
                } if log.new_plan else None,
                'changed_by': log.changed_by.username if log.changed_by else None,
                'changed_at': log.changed_at
            })
        
        return Response(logs_data)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        Get subscription statistics
        """
        total_subscriptions = Subscription.objects.count()
        active_subscriptions = Subscription.objects.filter(status='active').count()
        pending_subscriptions = Subscription.objects.filter(status='pending').count()
        expired_subscriptions = Subscription.objects.filter(status='expired').count()
        cancelled_subscriptions = Subscription.objects.filter(status='cancelled').count()
        
        return Response({
            'total_subscriptions': total_subscriptions,
            'active_subscriptions': active_subscriptions,
            'pending_subscriptions': pending_subscriptions,
            'expired_subscriptions': expired_subscriptions,
            'cancelled_subscriptions': cancelled_subscriptions
        })

    @action(detail=False, methods=['get'])
    def expiring_soon(self, request):
        """
        Get subscriptions expiring in the next 7 days
        """
        from datetime import date, timedelta
        
        next_week = date.today() + timedelta(days=7)
        expiring_subscriptions = Subscription.objects.filter(
            status='active',
            end_date__lte=next_week,
            end_date__gte=date.today()
        ).order_by('end_date')
        
        serializer = SubscriptionSerializer(expiring_subscriptions, many=True)
        return Response(serializer.data)