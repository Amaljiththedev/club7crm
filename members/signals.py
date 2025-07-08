# members/signals.py - Enhanced debugging version
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Member
from .tasks import send_member_welcome_whatsapp
from django.db import transaction
from django.conf import settings
import logging
import time

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Member)
def send_welcome_whatsapp_signal(sender, instance, created, **kwargs):
    """
    Enhanced signal handler with better debugging
    """
    if created:
        
        # Check if WhatsApp is enabled (you can add this setting to your Django settings)
        whatsapp_enabled = getattr(settings, 'WHATSAPP_ENABLED', True)
        if not whatsapp_enabled:
            return
        
        # Only queue if member has a phone number
        if not instance.phone_number:
            return
        
        # Use transaction.on_commit to ensure DB transaction is complete
        def queue_whatsapp_task():
            try:

                
                # Verify member exists before queuing task
                if Member.objects.filter(id=instance.id).exists():
                    
                    # Add more debugging info
                    member_check = Member.objects.get(id=instance.id)
            
                    
                    # You can switch between different tasks for testing
                    task_result = send_member_welcome_whatsapp.apply_async(
                        args=[instance.id],
                        countdown=5  # 5 seconds delay
                    )

                    
          
                    
            except Exception as e:
                pass
        
        # Queue the task after transaction commits
        transaction.on_commit(queue_whatsapp_task)
        
    else:
        pass