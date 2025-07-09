# members/tasks.py - Cleaned version
from celery import shared_task
from .models import Member
from plans.models import MembershipPlan
from .whatsapp import send_whatsapp_message
import logging
from django.utils import timezone
from django.db import connection, transaction
from django.core.exceptions import ObjectDoesNotExist
import time

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_member_welcome_whatsapp(self, member_id):
    """
    Send welcome WhatsApp message to new member
    """
    task_id = self.request.id
    
    try:
        # Force close existing connections to prevent stale connections
        connection.close()
        
        # Add small delay to ensure database consistency
        time.sleep(1)
        
        # Database operations with explicit transaction handling
        with transaction.atomic():
            try:
                # Use select_for_update to ensure we get the latest data
                member = Member.objects.select_for_update().get(id=member_id)
                member_name = member.full_name
                member_phone = member.phone_number
                
                # Validate phone number
                if not member_phone:
                    error_msg = f"No phone number found for member {member_name}"
                    logger.error(f"[Task {task_id}] {error_msg}")
                    return error_msg
                    
            except Member.DoesNotExist:
                error_msg = f"Member with ID {member_id} not found in database"
                logger.error(f"[Task {task_id}] {error_msg}")
                return error_msg
                
            except Exception as db_error:
                logger.error(f"[Task {task_id}] Database error: {db_error}", exc_info=True)
                raise db_error
        
        # Get membership plans with error handling
        try:
            plans = list(MembershipPlan.objects.all())
            logger.info(f"[Task {task_id}] Found {len(plans)} membership plans")
        except Exception as plan_error:
            logger.warning(f"[Task {task_id}] Error fetching plans: {plan_error}")
            plans = []
        
        # Generate message
        logger.info(f"[Task {task_id}] Generating welcome message...")
        message = generate_welcome_message(member_name, plans)
        logger.info(f"[Task {task_id}] Message generated (length: {len(message)} chars)")
        
        # Send WhatsApp message
        logger.info(f"[Task {task_id}] Attempting to send WhatsApp message to {member_phone}")
        try:
            message_sid = send_whatsapp_message(member_phone, message)
            success_msg = f"Welcome message sent to {member_name} (SID: {message_sid})"
            logger.info(f"[Task {task_id}] SUCCESS: {success_msg}")
            return success_msg
            
        except Exception as whatsapp_error:
            logger.error(f"[Task {task_id}] WhatsApp error: {whatsapp_error}", exc_info=True)
            raise whatsapp_error
        
    except Exception as e:
        error_msg = f"Error in welcome message task: {e}"
        logger.error(f"[Task {task_id}] GENERAL ERROR: {error_msg}", exc_info=True)
        
        # Retry with exponential backoff
        retry_count = self.request.retries + 1
        if retry_count <= 3:
            countdown = 60 * (2 ** (retry_count - 1))  # 60, 120, 240 seconds
            logger.info(f"[Task {task_id}] Retrying in {countdown} seconds... (Attempt {retry_count}/3)")
            raise self.retry(countdown=countdown, exc=e)
        else:
            final_error = f"Failed to send welcome message after {retry_count} attempts: {str(e)}"
            logger.error(f"[Task {task_id}] FINAL FAILURE: {final_error}")
            return final_error
    
    finally:
        logger.info(f"[Task {task_id}] Task completed")


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_birthday_wishes(self, member_id):
    """
    Send birthday wishes to member via WhatsApp
    """
    task_id = self.request.id
    
    try:
        # Force close existing connections to prevent stale connections
        connection.close()
        
        # Add small delay to ensure database consistency
        time.sleep(1)
        
        with transaction.atomic():
            try:
                # Get member with lock to ensure data consistency
                member = Member.objects.select_for_update().get(id=member_id)
                member_name = member.full_name
                member_phone = member.phone_number
                member_birthday = member.date_of_birth
                
                # Validate member data
                if not member_phone:
                    error_msg = f"No phone number found for member {member_name}"
                    logger.error(f"[Task {task_id}] {error_msg}")
                    return error_msg
                
                if not member_birthday:
                    error_msg = f"No birthday found for member {member_name}"
                    logger.error(f"[Task {task_id}] {error_msg}")
                    return error_msg
                
                # Check if it's actually their birthday today
                today = timezone.now().date()
                if not (member_birthday.month == today.month and member_birthday.day == today.day):
                    error_msg = f"Not birthday today for member {member_name}"
                    logger.warning(f"[Task {task_id}] {error_msg}")
                    return error_msg
                
                # Calculate age
                age = today.year - member_birthday.year
                if today < member_birthday.replace(year=today.year):
                    age -= 1
                
                logger.info(f"[Task {task_id}] Sending birthday wishes to {member_name} (Age: {age})")
                
            except Member.DoesNotExist:
                error_msg = f"Member with ID {member_id} not found in database"
                logger.error(f"[Task {task_id}] {error_msg}")
                return error_msg
                
            except Exception as db_error:
                logger.error(f"[Task {task_id}] Database error: {db_error}", exc_info=True)
                raise db_error
        
        # Generate birthday message
        logger.info(f"[Task {task_id}] Generating birthday message...")
        message = generate_birthday_message(member_name, age)
        logger.info(f"[Task {task_id}] Birthday message generated (length: {len(message)} chars)")
        
        # Send WhatsApp message
        logger.info(f"[Task {task_id}] Attempting to send birthday WhatsApp message to {member_phone}")
        try:
            message_sid = send_whatsapp_message(member_phone, message)
            success_msg = f"Birthday wishes sent to {member_name} (SID: {message_sid})"
            logger.info(f"[Task {task_id}] SUCCESS: {success_msg}")
            return success_msg
            
        except Exception as whatsapp_error:
            logger.error(f"[Task {task_id}] WhatsApp error: {whatsapp_error}", exc_info=True)
            raise whatsapp_error
        
    except Exception as e:
        error_msg = f"Error in birthday wishes task: {e}"
        logger.error(f"[Task {task_id}] GENERAL ERROR: {error_msg}", exc_info=True)
        
        # Retry with exponential backoff
        retry_count = self.request.retries + 1
        if retry_count <= 3:
            countdown = 60 * (2 ** (retry_count - 1))  # 60, 120, 240 seconds
            logger.info(f"[Task {task_id}] Retrying in {countdown} seconds... (Attempt {retry_count}/3)")
            raise self.retry(countdown=countdown, exc=e)
        else:
            final_error = f"Failed to send birthday wishes after {retry_count} attempts: {str(e)}"
            logger.error(f"[Task {task_id}] FINAL FAILURE: {final_error}")
            return final_error
    
    finally:
        logger.info(f"[Task {task_id}] Birthday task completed")



@shared_task
def daily_birthday_wishes():
    """
    Daily task to send birthday wishes to members
    """
    today = timezone.now().date()
    
    # Get all members with birthday today
    birthday_members = Member.objects.filter(
        date_of_birth__month=today.month,
        date_of_birth__day=today.day,
        is_active=True
    )
    
    logger.info(f"Found {birthday_members.count()} members with birthday today")
    
    for member in birthday_members:
        # Queue birthday wishes task
        generate_birthday_wishes.delay(member.id)
        logger.info(f"Queued birthday wishes for {member.full_name}")
    
    return f"Queued birthday wishes for {birthday_members.count()} members"






def generate_welcome_message(member_name, plans):
    """
    Generate a clean welcome message with highlighted features
    """
    logger.info(f"[Message Gen] Creating message for {member_name} with {len(plans)} plans")
    
    if plans:
        # Format membership plans in a more user-friendly way
        def format_duration(days):
            if days == 1:
                return "1 day"
            elif days == 7:
                return "1 week"
            elif days == 14:
                return "2 weeks"
            elif days == 30:
                return "1 month"
            elif days == 90:
                return "3 months"
            elif days == 180:
                return "6 months"
            elif days == 365:
                return "1 year"
            elif days % 30 == 0:
                months = days // 30
                return f"{months} month{'s' if months > 1 else ''}"
            elif days % 7 == 0:
                weeks = days // 7
                return f"{weeks} week{'s' if weeks > 1 else ''}"
            else:
                return f"{days} days"

        # Group plans by type
        membership_plans = [p for p in plans if p.type.lower() == 'membership']
        pt_plans = [p for p in plans if p.type.lower() == 'pt']
        
        # Format membership plans
        membership_list = []
        if membership_plans:
            for plan in membership_plans:
                duration = format_duration(plan.duration_days)
                membership_list.append(f"• {plan.name} - ₹{plan.price} ({duration})")
        
        # Format PT plans
        pt_list = []
        if pt_plans:
            for plan in pt_plans:
                duration = format_duration(plan.duration_days)
                pt_list.append(f"• {plan.name} - ₹{plan.price} ({duration})")
        
        # Create plan sections
        plan_sections = []
        
        if membership_list:
            plan_sections.append("🏋️ Membership Plans:")
            plan_sections.extend(membership_list)
        
        if pt_list:
            plan_sections.append("💪 Personal Training Plans:")
            plan_sections.extend(pt_list)
        
        plan_text = "\n".join(plan_sections)
        
        # Create the welcome message
        message = f"""🎉 *Welcome to Club7 Gym Family, {member_name}!* 🎉

We're absolutely thrilled to have you join our fitness community! 💪✨

Your journey to a healthier, stronger you starts here, and we're here to support you every step of the way! 🌟

Here are our amazing membership options tailored just for you:

{plan_text}

🔥 *What makes Club7 special:*
• State-of-the-art equipment
• Expert trainers & nutritionists  
• Friendly community atmosphere
• Flexible workout schedules
• Clean & hygienic facilities

Ready to transform your fitness journey? 🚀

💬 Need help choosing a plan? Simply reply to this message or visit us at the gym - our team is always happy to help!

Let's make your fitness goals a reality! 🏆

Welcome aboard! 🤝

*Team Club7 Gym*"""
        
        return message
    else:
        # Fallback message when no plans are available
        return f"""🎉 *Welcome to Club7 Gym Family, {member_name}!* 🎉

We're absolutely thrilled to have you join our fitness community! 💪✨

Your journey to a healthier, stronger you starts here, and we're here to support you every step of the way! 🌟

🔥 *What makes Club7 special:*
• State-of-the-art equipment
• Expert trainers & nutritionists  
• Friendly community atmosphere
• Flexible workout schedules
• Clean & hygienic facilities

Ready to transform your fitness journey? 🚀

💬 For membership plans and pricing, please reply to this message or visit us at the gym - our team is always happy to help!

Let's make your fitness goals a reality! 🏆

Welcome aboard! 🤝

*Team Club7 Gym*"""
    

def generate_birthday_message(member_name, age):
    """
    Generate a personalized birthday message
    """
    # Add age-appropriate emoji and messages
    if age < 25:
        age_emoji = "🎂"
        age_message = "Young and strong! 💪"
    elif age < 35:
        age_emoji = "🎉"
        age_message = "Prime time for fitness! 🏋️‍♂️"
    elif age < 50:
        age_emoji = "🎊"
        age_message = "Age is just a number! 🔥"
    else:
        age_emoji = "🌟"
        age_message = "Wisdom and strength combined! 💎"
    
    message = f"""🎉 *Happy Birthday, {member_name}!* 🎉

{age_emoji} Wishing you a fantastic {age}th birthday! {age_emoji}

{age_message}

On this special day, the entire Club7 Gym family wants to celebrate YOU! 🥳

May this new year of life bring you:
✨ Strength and vitality
🏆 Achievement of all your fitness goals
❤️ Good health and happiness
🌟 Endless energy and motivation

Come celebrate with us at the gym!

Keep shining and stay strong! 💪

*With love and birthday wishes,*
*Team Club7 Gym* 🏋️‍♂️"""
    
    return message