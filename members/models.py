from django.db import models
from datetime import date
from django.utils.timezone import now

class Member(models.Model):
    class Gender(models.TextChoices):
        MALE = 'M', 'Male'
        FEMALE = 'F', 'Female'
        OTHER = 'O', 'Other'

    class MaritalStatus(models.TextChoices):
        SINGLE = 'Single', 'Single'
        MARRIED = 'Married', 'Married'
        OTHER = 'Other', 'Other'

    class ReferralSource(models.TextChoices):
        FRIEND = 'Friend', 'Friend'
        SOCIAL_MEDIA = 'Social Media', 'Social Media'
        FLYER = 'Flyer', 'Flyer'
        ONLINE_AD = 'Online Ad', 'Online Ad'
        OTHER = 'Other', 'Other'

    # 1. Basic Info
    full_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True, db_index=True)
    phone_number = models.CharField(max_length=15, db_index=True)
    alternate_phone = models.CharField(max_length=15, blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices)
    dob = models.DateField()
    marital_status = models.CharField(max_length=10, choices=MaritalStatus.choices, blank=True, null=True)
    occupation = models.CharField(max_length=100, blank=True)
    profession = models.CharField(max_length=100, blank=True)
    referral_source = models.CharField(
        max_length=20,
        choices=ReferralSource.choices,
        blank=True,
        null=True,
        help_text="How did the member hear about the gym?"
    )
    firm_name = models.CharField(max_length=100, blank=True, null=True, help_text="Company/organization/firm the member is associated with.")
    area_or_locality = models.CharField(max_length=100, blank=True, null=True, help_text="Area, locality, or landmark for more granular location info.")

    # 2. Address
    address_line_1 = models.CharField(max_length=255)
    address_line_2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100)
    district = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pin_code = models.CharField(max_length=10)

    # 3. Physical Profile
    height_cm = models.FloatField(blank=True, null=True)
    weight_kg = models.FloatField(blank=True, null=True)

    # 4. Biometric & Visual ID
    biometric_id = models.CharField(max_length=4, unique=True, editable=False, blank=True, db_index=True)
    profile_photo = models.ImageField(upload_to='members/photos/', blank=True, null=True)

    # 5. Registration
    join_date = models.DateField(default=now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Status
    is_active = models.BooleanField(default=True)

    # Derived fields
    @property
    def age(self):
        if self.dob:
            today = date.today()
            return today.year - self.dob.year - ((today.month, today.day) < (self.dob.month, self.dob.day))
        return None

    @property
    def bmi(self):
        if self.height_cm and self.weight_kg:
            height_m = self.height_cm / 100
            return round(self.weight_kg / (height_m ** 2), 2)
        return None

    def save(self, *args, **kwargs):
        if not self.biometric_id:
            last_member = Member.objects.order_by('-id').first()
            if last_member and last_member.biometric_id:
                try:
                    last_id = int(last_member.biometric_id)
                except ValueError:
                    last_id = 0
            else:
                last_id = 0
            new_id = last_id + 1
            self.biometric_id = f"{new_id:04d}"  # Format: 0001, 0002, etc.
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} ({self.biometric_id})"

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Member'
        verbose_name_plural = 'Members'
        indexes = [
            models.Index(fields=['phone_number']),
            models.Index(fields=['email']),
            models.Index(fields=['biometric_id']),
        ]