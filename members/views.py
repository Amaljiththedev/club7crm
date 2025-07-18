from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import models
from .models import Member
from .serializers import MemberSerializer
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view


class MemberViewSet(viewsets.ModelViewSet):
    queryset = Member.objects.all()
    serializer_class = MemberSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=['patch'], url_path='block')
    def block_member(self, request, pk=None):
        member = self.get_object()
        member.is_active = False
        member.save()
        return Response({'status': 'Member blocked successfully'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], url_path='unblock')
    def unblock_member(self, request, pk=None):
        member = self.get_object()
        member.is_active = True
        member.save()
        return Response({'status': 'Member unblocked successfully'}, status=status.HTTP_200_OK)


    # Alternative implementation with better error handling
    @action(detail=False, methods=['get'], url_path='active-with-membership')
    def active_with_membership(self, request):
        """
        Alternative implementation with better debugging
        """
        from subscriptions.models import Subscription
        
        try:
            # Use select_related for better performance
            members_with_active_subscriptions = Member.objects.filter(
                subscriptions__status='active'
            ).select_related().distinct()
            
            print(f"Members with active subscriptions (v2): {members_with_active_subscriptions.count()}")
            
            serializer = MemberSerializer(members_with_active_subscriptions, many=True)
            return Response(serializer.data)
            
        except Exception as e:
            print(f"Error in active_with_membership_v2: {str(e)}")
            return Response(
                {'error': f'Database error: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='expiring-members')
    def expiring_members(self, request):
        """
        List members whose active subscriptions are expiring within 5 days from now.
        """
        from subscriptions.models import Subscription
        from django.utils.timezone import now
        from datetime import timedelta
        
        try:
            # Calculate date 5 days from now
            five_days_from_now = now().date() + timedelta(days=5)
            
            # Debug info
            print(f"Checking for subscriptions expiring by: {five_days_from_now}")
            
            # Get active subscriptions expiring within 5 days
            expiring_subscriptions = Subscription.objects.filter(
                status='active',
                end_date__lte=five_days_from_now,
                end_date__gte=now().date()  # Don't include already expired ones
            )
            
            print(f"Found {expiring_subscriptions.count()} expiring subscriptions")
            
            # Get member IDs from expiring subscriptions
            expiring_member_ids = expiring_subscriptions.values_list('member_id', flat=True).distinct()
            
            # Get members who are active and have expiring subscriptions
            members = Member.objects.filter(
                id__in=expiring_member_ids,
                is_active=True
            ).select_related()
            
            print(f"Found {members.count()} members with expiring subscriptions")
            
            # Enhanced serializer data with expiration info
            members_data = []
            for member in members:
                member_data = MemberSerializer(member).data
                
                # Get the expiring subscription details
                expiring_sub = expiring_subscriptions.filter(member=member).first()
                if expiring_sub:
                    member_data['expiring_subscription'] = {
                        'id': str(expiring_sub.id),
                        'plan_name': expiring_sub.plan.name,
                        'end_date': expiring_sub.end_date,
                        'days_left': (expiring_sub.end_date - now().date()).days
                    }
                
                members_data.append(member_data)
            
            return Response({
                'data': members_data,
                'debug_info': {
                    'check_date': five_days_from_now,
                    'expiring_subscriptions_count': expiring_subscriptions.count(),
                    'expiring_members_count': members.count()
                }
            })
            
        except Exception as e:
            print(f"Error in expiring_members: {str(e)}")
            return Response(
                {'error': f'Database error: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='inactive-members')
    def inactive_members(self, request):
        """
        List members who have taken initial membership but haven't renewed.
        These are members who:
        1. Have at least one subscription (took initial membership)
        2. Don't have any active subscriptions currently
        3. Are still active members (is_active=True)
        """
        from subscriptions.models import Subscription
        from django.db.models import Count, Q
        
        try:
            # Get members who have subscriptions but no active ones
            inactive_members = Member.objects.filter(
                is_active=True,  # Member account is still active
                subscriptions__isnull=False  # Has at least one subscription (took initial membership)
            ).exclude(
                subscriptions__status='active'  # But no active subscriptions
            ).annotate(
                total_subscriptions=Count('subscriptions'),
                active_subscriptions=Count('subscriptions', filter=Q(subscriptions__status='active'))
            ).filter(
                total_subscriptions__gt=0,  # Has taken at least one subscription
                active_subscriptions=0  # But no active subscriptions
            ).distinct()
            
            print(f"Found {inactive_members.count()} inactive members")
            
            # Enhanced serializer data with subscription history
            members_data = []
            for member in inactive_members:
                member_data = MemberSerializer(member).data
                
                # Get last subscription details
                last_subscription = member.subscriptions.order_by('-end_date').first()
                if last_subscription:
                    member_data['last_subscription'] = {
                        'id': str(last_subscription.id),
                        'plan_name': last_subscription.plan.name,
                        'status': last_subscription.status,
                        'start_date': last_subscription.start_date,
                        'end_date': last_subscription.end_date,
                        'was_renewal': last_subscription.is_renewal
                    }
                
                # Get subscription counts
                member_data['subscription_stats'] = {
                    'total_subscriptions': member.subscriptions.count(),
                    'expired_subscriptions': member.subscriptions.filter(status='expired').count(),
                    'cancelled_subscriptions': member.subscriptions.filter(status='cancelled').count(),
                    'has_renewed': member.subscriptions.filter(is_renewal=True).exists()
                }
                
                members_data.append(member_data)
            
            return Response({
                'data': members_data,
                'debug_info': {
                    'inactive_members_count': inactive_members.count(),
                    'criteria': 'Members with initial membership but no active subscriptions'
                }
            })
            
        except Exception as e:
            print(f"Error in inactive_members: {str(e)}")
            return Response(
                {'error': f'Database error: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='membership-summary')
    def membership_summary(self, request):
        """
        Get a summary of all membership statuses
        """
        from subscriptions.models import Subscription
        from django.utils.timezone import now
        from datetime import timedelta
        
        try:
            five_days_from_now = now().date() + timedelta(days=5)
            
            # Active members with active subscriptions
            active_members = Member.objects.filter(
                is_active=True,
                subscriptions__status='active'
            ).distinct()
            
            # Expiring members
            expiring_subscriptions = Subscription.objects.filter(
                status='active',
                end_date__lte=five_days_from_now,
                end_date__gte=now().date()
            )
            expiring_members = Member.objects.filter(
                is_active=True,
                id__in=expiring_subscriptions.values_list('member_id', flat=True)
            ).distinct()
            
            # Inactive members (have subscriptions but no active ones)
            inactive_members = Member.objects.filter(
                is_active=True,
                subscriptions__isnull=False
            ).exclude(
                subscriptions__status='active'
            ).distinct()
            
            # Never subscribed members
            never_subscribed = Member.objects.filter(
                is_active=True,
                subscriptions__isnull=True
            )
            
            # Blocked members
            blocked_members = Member.objects.filter(is_active=False)
            
            summary = {
                'active_members': active_members.count(),
                'expiring_members': expiring_members.count(),
                'inactive_members': inactive_members.count(),
                'never_subscribed': never_subscribed.count(),
                'blocked_members': blocked_members.count(),
                'total_members': Member.objects.count(),
                'check_date': five_days_from_now
            }
            
            return Response(summary)
            
        except Exception as e:
            print(f"Error in membership_summary: {str(e)}")
            return Response(
                {'error': f'Database error: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def get_queryset(self):
        return Member.objects.all()


@api_view(['GET'])
def debug_headers(request):
    return Response(dict(request.headers))


# Additional debugging views
@api_view(['GET'])
def debug_subscriptions(request):
    """Debug view to check subscription data"""
    from subscriptions.models import Subscription
    from django.utils.timezone import now
    from datetime import timedelta
    
    all_subscriptions = Subscription.objects.all()
    active_subscriptions = Subscription.objects.filter(status='active')
    
    # Check expiring subscriptions
    five_days_from_now = now().date() + timedelta(days=5)
    expiring_subscriptions = Subscription.objects.filter(
        status='active',
        end_date__lte=five_days_from_now,
        end_date__gte=now().date()
    )
    
    debug_data = {
        'total_subscriptions': all_subscriptions.count(),
        'active_subscriptions': active_subscriptions.count(),
        'expiring_subscriptions': expiring_subscriptions.count(),
        'subscription_statuses': list(all_subscriptions.values_list('status', flat=True).distinct()),
        'check_date': five_days_from_now,
        'today': now().date(),
        'active_subscription_details': [
            {
                'id': str(sub.id),
                'member_id': sub.member_id,
                'member_name': sub.member.full_name if hasattr(sub, 'member') else 'No member',
                'status': sub.status,
                'start_date': sub.start_date,
                'end_date': sub.end_date,
                'is_renewal': sub.is_renewal,
                'days_left': (sub.end_date - now().date()).days if sub.end_date else None
            }
            for sub in active_subscriptions[:10]  # Limit to first 10 for debugging
        ],
        'expiring_subscription_details': [
            {
                'id': str(sub.id),
                'member_id': sub.member_id,
                'member_name': sub.member.full_name if hasattr(sub, 'member') else 'No member',
                'status': sub.status,
                'end_date': sub.end_date,
                'days_left': (sub.end_date - now().date()).days if sub.end_date else None
            }
            for sub in expiring_subscriptions[:10]
        ]
    }
    
    return Response(debug_data)


@api_view(['GET'])
def debug_members(request):
    """Debug view to check member data"""
    from subscriptions.models import Subscription
    from django.utils.timezone import now
    from datetime import timedelta
    
    all_members = Member.objects.all()
    active_members = Member.objects.filter(is_active=True)
    
    # Check for different member categories
    five_days_from_now = now().date() + timedelta(days=5)
    
    # Members with active subscriptions
    active_with_membership = Member.objects.filter(
        is_active=True,
        subscriptions__status='active'
    ).distinct()
    
    # Members with expiring subscriptions
    expiring_members = Member.objects.filter(
        is_active=True,
        subscriptions__status='active',
        subscriptions__end_date__lte=five_days_from_now,
        subscriptions__end_date__gte=now().date()
    ).distinct()
    
    # Inactive members (have subscriptions but no active ones)
    inactive_members = Member.objects.filter(
        is_active=True,
        subscriptions__isnull=False
    ).exclude(
        subscriptions__status='active'
    ).distinct()
    
    # Never subscribed members
    never_subscribed = Member.objects.filter(
        is_active=True,
        subscriptions__isnull=True
    )
    
    debug_data = {
        'total_members': all_members.count(),
        'active_members': active_members.count(),
        'active_with_membership': active_with_membership.count(),
        'expiring_members': expiring_members.count(),
        'inactive_members': inactive_members.count(),
        'never_subscribed': never_subscribed.count(),
        'blocked_members': Member.objects.filter(is_active=False).count(),
        'check_date': five_days_from_now,
        'member_details': [
            {
                'id': member.id,
                'full_name': member.full_name,
                'is_active': member.is_active,
                'subscription_count': member.subscriptions.count(),
                'active_subscription_count': member.subscriptions.filter(status='active').count(),
                'has_renewals': member.subscriptions.filter(is_renewal=True).exists(),
                'last_subscription_status': member.subscriptions.order_by('-created_at').first().status if member.subscriptions.exists() else None
            }
            for member in active_members[:10]  # Limit to first 10 for debugging
        ]
    }
    
    return Response(debug_data)