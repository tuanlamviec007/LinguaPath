"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from learning import views as learning_views
from config.health import liveness, readiness
from learning.privacy import privacy_center

urlpatterns = [
    path('healthz/', readiness, name='readiness'),
    path('livez/', liveness, name='liveness'),
    path('admin/', admin.site.urls),
    path('', learning_views.home, name='home'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('accounts/register/', learning_views.register, name='register'),
    path('learn/', include('learning.urls')),
    path('dashboard/', learning_views.dashboard, name='dashboard'),
    path('settings/goal/', learning_views.learning_goal, name='learning_goal'),
    path('settings/privacy/', privacy_center, name='privacy_center'),
    path('progress/', learning_views.progress, name='progress'),
    path('tutor/', learning_views.tutor, name='tutor'),
]
