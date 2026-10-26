from django.contrib import admin
from .models import LearnerProfile, StudyTask

admin.site.register([LearnerProfile, StudyTask])
