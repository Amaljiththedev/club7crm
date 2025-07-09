from django.shortcuts import render

# Create your views here.
from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from .models import User, Admin, Staff, Trainer, HR
from .serializers import (
    UserSerializer, AdminSerializer, StaffSerializer, 
    TrainerSerializer, HRSerializer, LoginSerializer, RegisterSerializer
)

class LoginView(generics.GenericAPIView):
    serializer_class = LoginSerializer
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        
        refresh = RefreshToken.for_user(user)
        
        # Get user profile based on role
        profile_data = None
        if user.role == 'admin':
            try:
                profile = Admin.objects.get(user=user)
                profile_data = AdminSerializer(profile).data
            except Admin.DoesNotExist:
                pass
        elif user.role == 'staff':
            try:
                profile = Staff.objects.get(user=user)
                profile_data = StaffSerializer(profile).data
            except Staff.DoesNotExist:
                pass
        elif user.role == 'trainer':
            try:
                profile = Trainer.objects.get(user=user)
                profile_data = TrainerSerializer(profile).data
            except Trainer.DoesNotExist:
                pass
        elif user.role == 'hr':
            try:
                profile = HR.objects.get(user=user)
                profile_data = HRSerializer(profile).data
            except HR.DoesNotExist:
                pass
        
        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': UserSerializer(user).data,
            'profile': profile_data
        })

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_profile(request):
    user = request.user
    profile_data = None
    
    if user.role == 'admin':
        try:
            profile = Admin.objects.get(user=user)
            profile_data = AdminSerializer(profile).data
        except Admin.DoesNotExist:
            pass
    elif user.role == 'staff':
        try:
            profile = Staff.objects.get(user=user)
            profile_data = StaffSerializer(profile).data
        except Staff.DoesNotExist:
            pass
    elif user.role == 'trainer':
        try:
            profile = Trainer.objects.get(user=user)
            profile_data = TrainerSerializer(profile).data
        except Trainer.DoesNotExist:
            pass
    elif user.role == 'hr':
        try:
            profile = HR.objects.get(user=user)
            profile_data = HRSerializer(profile).data
        except HR.DoesNotExist:
            pass
    
    return Response({
        'user': UserSerializer(user).data,
        'profile': profile_data
    })