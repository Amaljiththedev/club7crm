# subscriptions/tasks.py
from celery import shared_task
from .models import Subscription
from members.models import Member
from plans.models import MembershipPlan
import logging
from django.utils import timezone
from django.db import connection, transaction
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
import time
import re
from django.http import HttpResponse
from django.template.loader import render_to_string
from xhtml2pdf import pisa
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
import os
from decimal import Decimal
from urllib.parse import urljoin
import io

logger = logging.getLogger(__name__)


def format_indian_phone_number(phone):
    """Format phone number for Indian WhatsApp messaging"""
    if not phone:
        return None
    phone = re.sub(r'\D', '', phone)
    if phone.startswith('91') and len(phone) == 12:
        return f"+{phone}"
    if phone.startswith('0'):
        phone = phone[1:]
    if len(phone) == 10:
        return f"+91{phone}"
    if phone.startswith('+91'):
        return phone
    return f"+91{phone}"


def send_whatsapp_message(to, message, media_url=None):
    """Send WhatsApp message using Twilio API with optional media attachment"""
    try:
        formatted_phone = format_indian_phone_number(to)
        logger.info(f"[WhatsApp] Sending message to: whatsapp:{formatted_phone}")
        logger.info(f"[WhatsApp] Message preview: {message[:60]}...")
        
        if media_url:
            logger.info(f"[WhatsApp] Attaching media: {media_url}")

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        # Use the correct WhatsApp number from settings
        from_number = settings.TWILIO_WHATSAPP_NUMBER  # e.g., 'whatsapp:+14155238886'

        # Prepare message parameters
        message_params = {
            'from_': from_number,
            'body': message,
            'to': f'whatsapp:{formatted_phone}'
        }
        
        # Add media URL if provided
        if media_url:
            message_params['media_url'] = [media_url]

        msg = client.messages.create(**message_params)
        
        logger.info(f"[WhatsApp] Message sent successfully. SID: {msg.sid}")
        return msg.sid

    except TwilioRestException as e:
        logger.error(f"[WhatsApp] Twilio error: {e}")
        raise

    except Exception as e:
        logger.error(f"[WhatsApp] Unexpected error: {e}")
        raise


def get_public_file_url(file_path):
    """
    Get publicly accessible URL for a file
    This assumes you have a way to serve files publicly
    """
    try:
        # If using Django's default storage with a public URL
        if hasattr(default_storage, 'url'):
            return default_storage.url(file_path)
        
        # Alternative: construct URL manually if you have a base URL
        base_url = getattr(settings, 'MEDIA_URL', '/media/')
        if hasattr(settings, 'MEDIA_ROOT'):
            # For local development
            return urljoin(getattr(settings, 'BASE_URL', 'http://localhost:8000'), f"{base_url}{file_path}")
        
        # For production with cloud storage (AWS S3, etc.)
        return default_storage.url(file_path)
        
    except Exception as e:
        logger.error(f"Error getting public URL for {file_path}: {e}")
        return None


def generate_subscription_pdf(subscription):
    """Generate PDF with subscription details using xhtml2pdf"""
    try:
        # Prepare context for PDF template
        context = {
            'subscription': subscription,
            'member': subscription.member,
            'plan': subscription.plan,
            'gym_name': getattr(settings, 'GYM_NAME', 'Fitness Center'),
            'gym_address': getattr(settings, 'GYM_ADDRESS', ''),
            'gym_phone': getattr(settings, 'GYM_PHONE', ''),
            'gym_email': getattr(settings, 'GYM_EMAIL', ''),
            'generated_date': timezone.now().strftime('%d %B %Y'),
            'qr_code_data': f"SUB-{subscription.id}",  # For QR code if needed
        }
        
        # Render HTML template
        html_string = render_to_string('subscriptions/subscription_receipt.html', context)
        
        # Create a BytesIO buffer to receive PDF data
        pdf_buffer = io.BytesIO()
        
        # Convert HTML to PDF using xhtml2pdf
        pisa_status = pisa.CreatePDF(
            html_string,
            dest=pdf_buffer,
            encoding='UTF-8'
        )
        
        # Check if PDF generation was successful
        if pisa_status.err:
            logger.error(f"PDF generation failed with errors: {pisa_status.err}")
            raise Exception("PDF generation failed")
        
        # Get PDF data
        pdf_data = pdf_buffer.getvalue()
        pdf_buffer.close()
        
        # Save PDF file
        pdf_filename = f'subscription_{subscription.id}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        pdf_path = f'subscriptions/receipts/{pdf_filename}'
        
        # Save to storage
        pdf_file = ContentFile(pdf_data, name=pdf_filename)
        saved_path = default_storage.save(pdf_path, pdf_file)
        
        logger.info(f"PDF generated successfully: {saved_path}")
        return saved_path
        
    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        raise


@shared_task(bind=True, max_retries=3)
def send_membership_enrolled_message(self, member_id, subscription_id):
    """
    Send WhatsApp message when a member enrolls in a membership plan
    """
    task_id = self.request.id
    logger.info(f"[Task {task_id}] Starting membership enrollment message task")
    
    try:
        # Close any existing database connections to avoid issues
        connection.close()
        time.sleep(1)
        
        with transaction.atomic():
            try:
                # Get member and subscription details
                member = Member.objects.get(id=member_id)
                subscription = Subscription.objects.get(id=subscription_id)
                
                logger.info(f"[Task {task_id}] Processing enrollment for member: {member.full_name}")
                
                # Generate PDF receipt
                pdf_path = None
                pdf_url = None
                try:
                    pdf_path = generate_subscription_pdf(subscription)
                    pdf_url = get_public_file_url(pdf_path)
                    logger.info(f"[Task {task_id}] PDF generated: {pdf_path}")
                    logger.info(f"[Task {task_id}] PDF URL: {pdf_url}")
                except Exception as pdf_error:
                    logger.error(f"[Task {task_id}] PDF generation failed: {pdf_error}")
                
                # Create enrollment message
                message = create_enrollment_message(member, subscription, pdf_attached=bool(pdf_url))
                
                # Send WhatsApp message with PDF attachment
                if member.phone_number:
                    message_sid = send_whatsapp_message(
                        member.phone_number, 
                        message, 
                        media_url=pdf_url
                    )
                    logger.info(f"[Task {task_id}] Message sent successfully. SID: {message_sid}")
                    
                    return {
                        'status': 'success',
                        'message_sid': message_sid,
                        'member_id': str(member_id),
                        'subscription_id': str(subscription_id),
                        'pdf_path': pdf_path,
                        'pdf_url': pdf_url
                    }
                else:
                    logger.warning(f"[Task {task_id}] No phone number found for member: {member.full_name}")
                    return {
                        'status': 'no_phone',
                        'message': 'Member has no phone number',
                        'pdf_path': pdf_path
                    }
                    
            except Member.DoesNotExist:
                logger.error(f"[Task {task_id}] Member with ID {member_id} not found")
                return {
                    'status': 'error',
                    'message': 'Member not found'
                }
                
            except Subscription.DoesNotExist:
                logger.error(f"[Task {task_id}] Subscription with ID {subscription_id} not found")
                return {
                    'status': 'error',
                    'message': 'Subscription not found'
                }
                
    except TwilioRestException as e:
        logger.error(f"[Task {task_id}] Twilio error: {e}")
        
        # Retry logic for Twilio errors
        if self.request.retries < self.max_retries:
            logger.info(f"[Task {task_id}] Retrying in 60 seconds... (Attempt {self.request.retries + 1}/{self.max_retries})")
            raise self.retry(countdown=60, exc=e)
        else:
            logger.error(f"[Task {task_id}] Max retries reached. Task failed.")
            return {
                'status': 'failed',
                'message': f'Twilio error after {self.max_retries} retries: {str(e)}'
            }
            
    except Exception as e:
        logger.error(f"[Task {task_id}] Unexpected error: {e}")
        
        # Retry for unexpected errors
        if self.request.retries < self.max_retries:
            logger.info(f"[Task {task_id}] Retrying in 60 seconds... (Attempt {self.request.retries + 1}/{self.max_retries})")
            raise self.retry(countdown=60, exc=e)
        else:
            logger.error(f"[Task {task_id}] Max retries reached. Task failed.")
            return {
                'status': 'failed',
                'message': f'Unexpected error after {self.max_retries} retries: {str(e)}'
            }


def create_enrollment_message(member, subscription, pdf_attached=False):
    """
    Create a personalized enrollment message with price
    """
    # Format price - assuming plan has a price field
    price_text = ""
    if hasattr(subscription.plan, 'price') and subscription.plan.price:
        price_text = f"• Amount Paid: ₹{subscription.plan.price:,.2f}\n"
    
    # Calculate validity period
    validity_days = subscription.plan.duration_days
    validity_text = f"{validity_days} days"
    if validity_days >= 365:
        years = validity_days // 365
        remaining_days = validity_days % 365
        if remaining_days > 0:
            validity_text = f"{years} year{'s' if years > 1 else ''} and {remaining_days} days"
        else:
            validity_text = f"{years} year{'s' if years > 1 else ''}"
    elif validity_days >= 30:
        months = validity_days // 30
        remaining_days = validity_days % 30
        if remaining_days > 0:
            validity_text = f"{months} month{'s' if months > 1 else ''} and {remaining_days} days"
        else:
            validity_text = f"{months} month{'s' if months > 1 else ''}"

    # Adjust message based on whether PDF is attached
    receipt_text = "📎 Your detailed membership receipt is attached to this message." if pdf_attached else "📄 A detailed receipt has been generated for your records."

    message = f"""🎉 Welcome to our Gym, {member.full_name}!

✅ Your membership has been successfully activated!

📋 Membership Details:
• Plan: {subscription.plan.name}
{price_text}• Start Date: {subscription.start_date.strftime('%d %B %Y')}
• End Date: {subscription.end_date.strftime('%d %B %Y')}
• Validity: {validity_text}

💪 You're all set to begin your fitness journey with us!

{receipt_text}

📞 For any questions, feel free to contact us.
🏋️‍♂️ See you at the gym!

Thank you for choosing us! 💪"""
    
    return message


@shared_task(bind=True, max_retries=3)
def send_membership_expiry_reminder(self, member_id, subscription_id, days_until_expiry):
    """
    Send WhatsApp reminder when membership is about to expire
    """
    task_id = self.request.id
    logger.info(f"[Task {task_id}] Starting expiry reminder task")
    
    try:
        connection.close()
        time.sleep(1)
        
        with transaction.atomic():
            try:
                member = Member.objects.get(id=member_id)
                subscription = Subscription.objects.get(id=subscription_id)
                
                message = create_expiry_reminder_message(member, subscription, days_until_expiry)
                
                if member.phone_number:
                    message_sid = send_whatsapp_message(member.phone_number, message)
                    logger.info(f"[Task {task_id}] Expiry reminder sent successfully. SID: {message_sid}")
                    
                    return {
                        'status': 'success',
                        'message_sid': message_sid,
                        'member_id': str(member_id),
                        'subscription_id': str(subscription_id)
                    }
                else:
                    logger.warning(f"[Task {task_id}] No phone number found for member: {member.full_name}")
                    return {
                        'status': 'no_phone',
                        'message': 'Member has no phone number'
                    }
                    
            except (Member.DoesNotExist, Subscription.DoesNotExist) as e:
                logger.error(f"[Task {task_id}] Database error: {e}")
                return {
                    'status': 'error',
                    'message': str(e)
                }
                
    except Exception as e:
        logger.error(f"[Task {task_id}] Error in expiry reminder: {e}")
        
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60, exc=e)
        else:
            return {
                'status': 'failed',
                'message': f'Error after {self.max_retries} retries: {str(e)}'
            }


def create_expiry_reminder_message(member, subscription, days_until_expiry):
    """
    Create expiry reminder message
    """
    if days_until_expiry <= 0:
        message = f"""⚠️ Hi {member.full_name},

Your membership has expired!

📋 Membership Details:
• Plan: {subscription.plan.name}
• Expired on: {subscription.end_date.strftime('%d %B %Y')}

💪 Don't let your fitness journey stop here!
🔄 Renew your membership today to continue your workouts.

📞 Contact us for renewal options.
Thank you! 🏋️‍♂️"""
    else:
        message = f"""⏰ Hi {member.full_name},

Your membership expires in {days_until_expiry} day{'s' if days_until_expiry > 1 else ''}!

📋 Membership Details:
• Plan: {subscription.plan.name}
• Expires on: {subscription.end_date.strftime('%d %B %Y')}

💪 Don't miss out on your fitness routine!
🔄 Renew your membership to continue your workouts.

📞 Contact us for renewal options.
Thank you! 🏋️‍♂️"""
    
    return message


@shared_task(bind=True, max_retries=3)
def send_plan_change_notification(self, member_id, subscription_id, old_plan_name, new_plan_name):
    """
    Send WhatsApp notification when member changes their plan
    """
    task_id = self.request.id
    logger.info(f"[Task {task_id}] Starting plan change notification task")
    
    try:
        connection.close()
        time.sleep(1)
        
        with transaction.atomic():
            try:
                member = Member.objects.get(id=member_id)
                subscription = Subscription.objects.get(id=subscription_id)
                
                # Generate PDF for plan change
                pdf_path = None
                pdf_url = None
                try:
                    pdf_path = generate_subscription_pdf(subscription)
                    pdf_url = get_public_file_url(pdf_path)
                    logger.info(f"[Task {task_id}] Plan change PDF generated: {pdf_path}")
                except Exception as pdf_error:
                    logger.error(f"[Task {task_id}] PDF generation failed: {pdf_error}")
                
                message = f"""🔄 Hi {member.full_name},

Your membership plan has been successfully changed!

📋 Plan Change Details:
• From: {old_plan_name}
• To: {new_plan_name}
• Effective Date: {timezone.now().strftime('%d %B %Y')}

💪 Enjoy your updated membership benefits!

{"📎 Your updated membership details are attached." if pdf_url else "📄 Updated membership details have been generated."}

📞 For any questions, feel free to contact us.
Thank you! 🏋️‍♂️"""
                
                if member.phone_number:
                    message_sid = send_whatsapp_message(
                        member.phone_number, 
                        message, 
                        media_url=pdf_url
                    )
                    logger.info(f"[Task {task_id}] Plan change notification sent successfully. SID: {message_sid}")
                    
                    return {
                        'status': 'success',
                        'message_sid': message_sid,
                        'member_id': str(member_id),
                        'subscription_id': str(subscription_id),
                        'pdf_path': pdf_path
                    }
                else:
                    logger.warning(f"[Task {task_id}] No phone number found for member: {member.full_name}")
                    return {
                        'status': 'no_phone',
                        'message': 'Member has no phone number'
                    }
                    
            except (Member.DoesNotExist, Subscription.DoesNotExist) as e:
                logger.error(f"[Task {task_id}] Database error: {e}")
                return {
                    'status': 'error',
                    'message': str(e)
                }
                
    except Exception as e:
        logger.error(f"[Task {task_id}] Error in plan change notification: {e}")
        
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60, exc=e)
        else:
            return {
                'status': 'failed',
                'message': f'Error after {self.max_retries} retries: {str(e)}'
            }