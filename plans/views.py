from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import MembershipPlan
from .serializers import MembershipPlanSerializer

# Create your views here.

class MembershipPlanViewSet(viewsets.ModelViewSet):
    queryset = MembershipPlan.objects.all()
    serializer_class = MembershipPlanSerializer

    @action(detail=True, methods=['post'])
    def block(self, request, pk=None):
        # Placeholder for block logic
        return Response({'status': 'blocked'}, status=status.HTTP_200_OK)
