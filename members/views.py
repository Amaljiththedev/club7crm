from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import models
from .models import Member
from .serializers import MemberSerializer


class MemberViewSet(viewsets.ModelViewSet):
    queryset = Member.objects.filter(is_active=True).order_by('-created_at')
    serializer_class = MemberSerializer

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
        return Response({'status': 'Member unblocked successfully'})
    
    def get_queryset(self):
        qs = Member.objects.filter(is_active=True)
        query = self.request.query_params.get('q')
        if query:
            qs = qs.filter(models.Q(full_name__icontains=query) | models.Q(phone_number__icontains=query))
        return qs.order_by('-created_at')