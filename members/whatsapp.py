from django.conf import settings
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
import re

def format_indian_phone_number(phone):
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

def send_whatsapp_message(to, message):
    try:
        formatted_phone = format_indian_phone_number(to)
        print(f"[WhatsApp] Sending message to: whatsapp:{formatted_phone}")
        print(f"[WhatsApp] Message preview: {message[:60]}...")

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        # IMPORTANT: Use the correct WhatsApp number
        from_number = settings.TWILIO_WHATSAPP_NUMBER  # e.g., 'whatsapp:+14155238886'

        msg = client.messages.create(
            from_=from_number,
            body=message,
            to=f'whatsapp:{formatted_phone}'
        )
        return msg.sid

    except TwilioRestException as e:
        raise

    except Exception as e:
        raise
