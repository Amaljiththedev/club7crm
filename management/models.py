from django.db import models

# Create your models here.
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import RegexValidator
import uuid

class User(AbstractUser):
    """Base user model with common fields"""
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('staff', 'Staff'),
        ('trainer', 'Trainer'),
        ('hr', 'HR'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$', message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.")
    phone = models.CharField(validators=[phone_regex], max_length=17, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'role']
    
    def __str__(self):
        return f"{self.email} - {self.role}"

class Admin(models.Model):
    """Admin model with extended details"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='admin_profile')
    employee_id = models.CharField(max_length=20, unique=True)
    department = models.CharField(max_length=100, default='Management')
    access_level = models.CharField(max_length=20, choices=[
        ('super', 'Super Admin'),
        ('manager', 'Manager'),
        ('supervisor', 'Supervisor')
    ], default='manager')
    salary = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    hire_date = models.DateField()
    emergency_contact = models.CharField(max_length=100)
    emergency_phone = models.CharField(max_length=17)
    address = models.TextField()
    
    def __str__(self):
        return f"Admin: {self.user.email} - {self.employee_id}"

class Staff(models.Model):
    """Staff model with extended details"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='staff_profile')
    employee_id = models.CharField(max_length=20, unique=True)
    department = models.CharField(max_length=100, choices=[
        ('reception', 'Reception'),
        ('maintenance', 'Maintenance'),
        ('cleaning', 'Cleaning'),
        ('security', 'Security'),
        ('sales', 'Sales')
    ])
    shift = models.CharField(max_length=20, choices=[
        ('morning', 'Morning (6AM-2PM)'),
        ('evening', 'Evening (2PM-10PM)'),
        ('night', 'Night (10PM-6AM)')
    ])
    hourly_rate = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    hire_date = models.DateField()
    supervisor = models.ForeignKey(Admin, on_delete=models.SET_NULL, null=True, blank=True)
    emergency_contact = models.CharField(max_length=100)
    emergency_phone = models.CharField(max_length=17)
    address = models.TextField()
    
    def __str__(self):
        return f"Staff: {self.user.email} - {self.department}"

class Trainer(models.Model):
    """Trainer model with extended details"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='trainer_profile')
    employee_id = models.CharField(max_length=20, unique=True)
    specialization = models.CharField(max_length=100, choices=[
        ('personal', 'Personal Training'),
        ('group', 'Group Fitness'),
        ('yoga', 'Yoga'),
        ('pilates', 'Pilates'),
        ('crossfit', 'CrossFit'),
        ('cardio', 'Cardio Training'),
        ('strength', 'Strength Training'),
        ('nutrition', 'Nutrition Counseling')
    ])
    certifications = models.TextField(help_text="List of certifications")
    experience_years = models.IntegerField()
    hourly_rate = models.DecimalField(max_digits=6, decimal_places=2)
    availability = models.JSONField(default=dict, help_text="Weekly availability schedule")
    max_clients = models.IntegerField(default=20)
    hire_date = models.DateField()
    emergency_contact = models.CharField(max_length=100)
    emergency_phone = models.CharField(max_length=17)
    address = models.TextField()
    bio = models.TextField(blank=True)
    
    def __str__(self):
        return f"Trainer: {self.user.email} - {self.specialization}"

class HR(models.Model):
    """HR model with extended details"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='hr_profile')
    employee_id = models.CharField(max_length=20, unique=True)
    department = models.CharField(max_length=100, default='Human Resources')
    hr_level = models.CharField(max_length=20, choices=[
        ('manager', 'HR Manager'),
        ('specialist', 'HR Specialist'),
        ('coordinator', 'HR Coordinator'),
        ('assistant', 'HR Assistant')
    ])
    responsibilities = models.TextField(help_text="Key responsibilities and areas")
    salary = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    hire_date = models.DateField()
    emergency_contact = models.CharField(max_length=100)
    emergency_phone = models.CharField(max_length=17)
    address = models.TextField()
    
    def __str__(self):
        return f"HR: {self.user.email} - {self.hr_level}"