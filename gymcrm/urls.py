from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from management.views import LoginView, RegisterView, get_user_profile
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('members.urls')),
    path('api/', include('plans.urls')),
    path('api/', include('subscriptions.urls')),
    path('api/auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/register/', RegisterView.as_view(), name='register'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/profile/', get_user_profile, name='user_profile'),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)