try:
    import resend
except ImportError:
    resend = None

from sqlalchemy.orm import Session
from app import models
from typing import Optional

def send_email(db: Session, to_email: str, html_content: str, subject: Optional[str] = None):
    """
    Sends an email using Resend.com based on global settings.
    """
    if not resend:
        print("[EmailService] Resend library not installed. Skipping email.")
        return None

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


def send_visit_invitation_email(
    db: Session,
    visit: models.Visit,
    participant_email: str,
    participant_name: Optional[str] = None,
    base_url: Optional[str] = None
):
    """
    Sends a styled invitation email to a participant with visit date, meeting address,
    GPS navigation link, Immo-Boussole listing details link, and direct magic link to the
    collaborative visit session & FAQ.
    """
    if not participant_email:
        return None

    name_display = participant_name or participant_email.split("@")[0]
    base = (base_url or "http://localhost:8000").rstrip("/")
    visit_url = f"{base}/v/{visit.access_token}" if visit.access_token else f"{base}/visites"
    listing = visit.listing
    listing_title = listing.title if listing else "Bien immobilier"
    listing_url = f"{base}/#listing-{listing.id}" if listing else base

    # Format date
    try:
        dt_str = visit.scheduled_at.strftime("%d/%m/%Y à %H:%M")
    except Exception:
        dt_str = str(visit.scheduled_at)

    type_label = "Contre-visite" if visit.visit_type == "contre_visite" else "Visite immobilière"
    address_display = visit.meeting_address or (listing.address if listing else "") or (listing.city if listing else "Adresse non précisée")
    import urllib.parse
    maps_link = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(address_display)}"

    instructions_html = ""
    if visit.instructions:
        instructions_html = f"""
        <div style="background-color: #f8fafc; border-left: 4px solid #3b82f6; padding: 12px 16px; margin: 16px 0; border-radius: 4px;">
            <strong style="color: #1e293b; font-size: 14px;">📝 Consignes & Instructions :</strong>
            <p style="color: #475569; margin: 6px 0 0 0; font-size: 13px; white-space: pre-wrap;">{visit.instructions}</p>
        </div>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #1e293b; margin: 0; padding: 0; background-color: #f1f5f9; }}
            .container {{ max-width: 600px; margin: 24px auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.06); }}
            .header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); color: #ffffff; padding: 24px 32px; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }}
            .header p {{ margin: 6px 0 0 0; color: #94a3b8; font-size: 14px; }}
            .content {{ padding: 32px; }}
            .card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px 20px; margin-bottom: 20px; }}
            .card-title {{ font-weight: 600; font-size: 16px; color: #0f172a; margin-bottom: 12px; display: flex; align-items: center; }}
            .info-row {{ margin-bottom: 8px; font-size: 14px; color: #334155; }}
            .info-label {{ font-weight: 600; color: #64748b; }}
            .btn-primary {{ display: inline-block; background-color: #2563eb; color: #ffffff !important; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: 600; font-size: 15px; text-align: center; margin-top: 10px; }}
            .btn-secondary {{ display: inline-block; background-color: #f1f5f9; color: #334155 !important; border: 1px solid #cbd5e1; text-decoration: none; padding: 8px 16px; border-radius: 6px; font-weight: 500; font-size: 13px; text-align: center; margin-right: 8px; }}
            .footer {{ background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 16px 32px; text-align: center; font-size: 12px; color: #94a3b8; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🧭 Immo-Boussole</h1>
                <p>Invitation : {type_label}</p>
            </div>
            <div class="content">
                <p style="font-size: 15px; margin-top: 0;">Bonjour <strong>{name_display}</strong>,</p>
                <p style="font-size: 14px; color: #475569;">
                    Vous êtes invité(e) à participer à la <strong>{type_label}</strong> du bien immobilier suivant :
                </p>

                <div class="card">
                    <div class="card-title">🏡 {listing_title}</div>
                    <div class="info-row"><span class="info-label">📅 Date & Heure :</span> <strong>{dt_str}</strong></div>
                    <div class="info-row"><span class="info-label">📍 Lieu de RDV :</span> {address_display}</div>
                    <div style="margin-top: 12px;">
                        <a href="{maps_link}" class="btn-secondary" target="_blank">🗺️ Ouvrir GPS / Navigation</a>
                        <a href="{listing_url}" class="btn-secondary" target="_blank">📋 Voir l'annonce</a>
                    </div>
                </div>

                {instructions_html}

                <div style="text-align: center; margin: 28px 0 16px 0;">
                    <a href="{visit_url}" class="btn-primary" target="_blank">🚀 Accéder à l'Espace Visite Collaborative & FAQ</a>
                </div>

                <div style="background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 14px; margin-top: 20px; font-size: 13px; color: #166534;">
                    <strong>💡 Sur l'Espace Visite :</strong>
                    <ul style="margin: 6px 0 0 0; padding-left: 20px;">
                        <li>Consultez et complétez les questions d'inspection classées par thématique (FAQ).</li>
                        <li>Prenez des photos et vidéos en direct pendant la visite sur votre smartphone.</li>
                        <li>Partagez vos impressions et notes en direct avec les autres participants.</li>
                    </ul>
                </div>
            </div>
            <div class="footer">
                Immo-Boussole — Votre assistant intelligent de recherche et visite immobilière.
            </div>
        </div>
    </body>
    </html>
    """

    subject = f"[{type_label}] {listing_title} — {dt_str}"
    return send_email(db, participant_email, html, subject=subject)
