import resend
from sqlalchemy.orm import Session
from app import models
from typing import Optional

def send_email(db: Session, to_email: str, html_content: str, subject: Optional[str] = None):
    """
    Sends an email using Resend.com based on global settings.
    """
    settings = db.query(models.GlobalSettings).first()
    if not settings or not settings.resend_api_key:
        print("[EmailService] Resend API key not configured. Skipping email.")
        return None

    resend.api_key = settings.resend_api_key
    
    sender_name = settings.resend_sender_name or "Immo-Boussole"
    sender_email = settings.resend_sender_email
    
    if not sender_email:
        print("[EmailService] Resend sender email not configured. Skipping email.")
        return None

    final_subject = subject or settings.resend_subject or "Notification Immo-Boussole"
    
    if settings.APP_ENV == "development":
        final_subject = f"[DEV] {final_subject}"
    
    try:
        params = {
            "from": f"{sender_name} <{sender_email}>",
            "to": [to_email],
            "subject": final_subject,
            "html": html_content,
        }
        
        response = resend.Emails.send(params)
        return response
    except Exception as e:
        print(f"[EmailService] Error sending email: {e}")
        return None
