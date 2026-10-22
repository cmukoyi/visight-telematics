import smtplib
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Optional
import os

# SendGrid support
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Email, To, Content, TrackingSettings, ClickTracking
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False

class EmailService:
    def __init__(self):
        # Email API configuration (Twilio SendGrid-compatible credentials)
        self.twilio_api_key = os.getenv("TWILIO_API_KEY", "")
        self.twilio_api_secret = os.getenv("TWILIO_API_SECRET", "")
        self.twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        self.sendgrid_api_key = os.getenv("SENDGRID_API_KEY", "")

        # Prefer new Twilio email credentials first, then fall back to existing SendGrid key.
        self.email_api_key = (
            self.twilio_api_key or
            self.twilio_api_secret or
            self.twilio_auth_token or
            self.sendgrid_api_key
        )
        self.use_sendgrid = bool(self.email_api_key) and SENDGRID_AVAILABLE
        self.email_provider = "Twilio" if self.twilio_api_key or self.twilio_api_secret or self.twilio_auth_token else "SendGrid"
        
        # SMTP configuration (fallback or development)
        self.smtp_host = os.getenv("SMTP_HOST", "mailhog")
        self.smtp_port = int(os.getenv("SMTP_PORT", "1025"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.from_email = os.getenv("FROM_EMAIL", "noreply@visighttelematics.co.za")
        self.debug = os.getenv("DEBUG", "False").lower() == "true"

        # Branding (env-driven). Used in subjects / bodies / footer links of
        # every templated email below.
        self.brand_name    = os.getenv("BRAND_NAME", "ViSight Track")
        self.brand_domain  = os.getenv("BRAND_DOMAIN", "track.visighttelematics.co.za")
        self.brand_url     = os.getenv("FRONTEND_URL", f"https://{self.brand_domain}")
        self.brand_support = os.getenv("BRAND_SUPPORT_EMAIL", f"support@{self.brand_domain}")
        
        # Log email service configuration
        if self.use_sendgrid:
            print(f"📧 Email Service: Using {self.email_provider} API")
        else:
            print(f"📧 Email Service: Using SMTP ({self.smtp_host}:{self.smtp_port})")
        
    def generate_pin(self) -> str:
        """Generate a 6-digit PIN"""
        return ''.join([str(random.randint(0, 9)) for _ in range(6)])
    
    def send_verification_pin(self, to_email: str, pin: str) -> bool:
        """Send verification PIN via email"""
        try:
            # Development mode - print to console (but still send email)
            if self.debug:
                print(f"\n{'='*60}")
                print(f"📧 VERIFICATION PIN for {to_email}")
                print(f"     PIN: {pin}")
                print(f"{'='*60}\n")
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f'Your {self.brand_name} Verification Code'
            msg['From'] = self.from_email
            msg['To'] = to_email
            
            # Plain text version
            text = f"""
            Your verification code is: {pin}
            
            This code will expire in 10 minutes.
            
            If you didn't request this code, please ignore this email.
            
            Best regards,
            {self.brand_name} Team
            """
            
            # HTML version
            html = f"""
            <html>
              <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                  <h2 style="color: #173C64;">{self.brand_name} Verification</h2>
                  <p>Your verification code is:</p>
                  <div style="background-color: #f4f4f4; padding: 20px; text-align: center; border-radius: 8px; margin: 20px 0;">
                    <h1 style="color: #173C64; font-size: 36px; letter-spacing: 8px; margin: 0;">{pin}</h1>
                  </div>
                  <p style="color: #666;">This code will expire in <strong>10 minutes</strong>.</p>
                  <p style="color: #666;">If you didn't request this code, please ignore this email.</p>
                  <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
                  <p style="color: #999; font-size: 12px;">Best regards,<br>{self.brand_name} Team</p>
                </div>
              </body>
            </html>
            """
            
            # Send via SendGrid or SMTP
            if self.use_sendgrid:
                return self._send_via_sendgrid(
                    to_email=to_email,
                    subject=f'Your {self.brand_name} Verification Code',
                    text_content=text,
                    html_content=html
                )
            else:
                part1 = MIMEText(text, 'plain')
                part2 = MIMEText(html, 'html')
                msg.attach(part1)
                msg.attach(part2)
                
                # Send email via SMTP
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    if self.smtp_user and self.smtp_password:
                        server.starttls()
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_email, to_email, msg.as_string())
                
                return True
        except Exception as e:
            print(f"Error sending email: {e}")
            return False

    def send_portal_reset_pin(self, to_email: str, pin: str, first_name: Optional[str] = None) -> bool:
        """Send a 6-digit password reset PIN to a portal user."""
        try:
            name = first_name if first_name else "there"

            if self.debug:
                print(f"\n{'='*60}")
                print(f"🔑 PORTAL PASSWORD RESET PIN for {to_email}")
                print(f"     PIN: {pin}")
                print(f"{'='*60}\n")

            text = f"""
Hi {name},

You requested a password reset for your {self.brand_name} portal account.

Your reset PIN is:  {pin}

Enter this PIN on the portal password reset screen along with your new password.
This PIN expires in 15 minutes.

If you did not request a password reset, you can safely ignore this email.

Best regards,
{self.brand_name} Team
"""

            html = f"""
<html>
  <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0;">
    <div style="max-width: 560px; margin: 40px auto; padding: 0 20px;">
      <div style="background: #173C64; border-radius: 10px 10px 0 0; padding: 28px 32px; text-align: center;">
        <h1 style="color: #fff; margin: 0; font-size: 22px; letter-spacing: .5px;">🔑 Password Reset</h1>
      </div>
      <div style="background: #f9fafb; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 10px 10px; padding: 32px;">
        <p style="font-size: 15px; margin-top: 0;">Hi {name},</p>
        <p style="font-size: 15px;">We received a request to reset your {self.brand_name} portal password.
           Use the PIN below on the reset screen:</p>
        <div style="background: #fff; border: 2px dashed #173C64; border-radius: 10px;
                    text-align: center; padding: 24px; margin: 24px 0;">
          <p style="margin: 0 0 4px; font-size: 12px; color: #6b7280; letter-spacing: 1px; text-transform: uppercase;">Your reset PIN</p>
          <p style="margin: 0; font-size: 42px; font-weight: 700; letter-spacing: 12px;
                    color: #173C64; font-family: 'Courier New', monospace;">{pin}</p>
          <p style="margin: 8px 0 0; font-size: 12px; color: #ef4444;">⏱ Expires in 15 minutes</p>
        </div>
        <p style="font-size: 13px; color: #6b7280;">
          If you did not request a password reset, simply ignore this email — your account is safe.
        </p>
      </div>
      <p style="font-size: 11px; color: #9ca3af; text-align: center; margin-top: 20px;">
        {self.brand_name} &middot; <a href="{self.brand_url}" style="color:#9ca3af">{self.brand_domain}</a>
      </p>
    </div>
  </body>
</html>
"""

            if self.use_sendgrid:
                return self._send_via_sendgrid(
                    to_email=to_email,
                    subject=f'Your {self.brand_name} Portal Password Reset PIN',
                    text_content=text,
                    html_content=html,
                )
            else:
                msg = MIMEMultipart('alternative')
                msg['Subject'] = f'Your {self.brand_name} Portal Password Reset PIN'
                msg['From'] = self.from_email
                msg['To'] = to_email
                msg.attach(MIMEText(text, 'plain'))
                msg.attach(MIMEText(html, 'html'))
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    if self.smtp_user and self.smtp_password:
                        server.starttls()
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_email, to_email, msg.as_string())
                return True
        except Exception as e:
            print(f"Error sending portal reset PIN email: {e}")
            return False

    def send_welcome_email(self, to_email: str, first_name: Optional[str] = None) -> bool:
        """Send welcome email after successful registration"""
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f'Welcome to {self.brand_name}'
            msg['From'] = self.from_email
            msg['To'] = to_email
            
            name = first_name if first_name else "there"
            
            html = f"""
            <html>
              <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                  <h2 style="color: #173C64;">Welcome to {self.brand_name}!</h2>
                  <p>Hi {name},</p>
                  <p>Thank you for joining {self.brand_name}. Your account has been successfully created.</p>
                  <p>You can now start adding and tracking your devices.</p>
                  <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
                  <p style="color: #999; font-size: 12px;">Best regards,<br>{self.brand_name} Team</p>
                </div>
              </body>
            </html>
            """
            
            # Send via SendGrid or SMTP
            if self.use_sendgrid:
                return self._send_via_sendgrid(
                    to_email=to_email,
                    subject=f'Welcome to {self.brand_name}',
                    text_content=f"Welcome to {self.brand_name}!",
                    html_content=html
                )
            else:
                part = MIMEText(html, 'html')
                msg.attach(part)
                
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    if self.smtp_user and self.smtp_password:
                        server.starttls()
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_email, to_email, msg.as_string())
                
                return True
        except Exception as e:
            print(f"Error sending welcome email: {e}")
            return False

    def send_geofence_alert(
        self, 
        to_email: str, 
        event_type: str,  # e.g., 'inside Home', 'outside Office', 'left origin', etc.
        poi_name: str,
        tracker_name: str,
        latitude: float,
        longitude: float,
        timestamp: str
    ) -> bool:
        """Send geofence alert email when tracker enters or exits a POI"""
        try:
            # Development mode - print to console (but still send email)
            if self.debug:
                print(f"\n{'='*60}")
                print(f"🚨 GEOFENCE ALERT for {to_email}")
                print(f"     Event: {event_type}")
                print(f"     POI: {poi_name}")
                print(f"     Tracker: {tracker_name}")
                print(f"     Location: {latitude}, {longitude}")
                print(f"     Time: {timestamp}")
                print(f"{'='*60}\n")
            
            # Determine emoji and color based on event description
            # 'inside' or 'entry' events = green, 'outside' or 'exit' = red
            is_entry = 'inside' in event_type.lower() or 'entry' in event_type.lower() or 'arrived' in event_type.lower()
            event_emoji = "🟢" if is_entry else "🔴"
            event_color = "#4CAF50" if is_entry else "#F44336"
            
            msg = MIMEMultipart('alternative')
            # Subject line: "Tracker XXX is inside/outside Location"
            msg['Subject'] = f'{event_emoji} Alert: {tracker_name} is {event_type}'
            msg['From'] = self.from_email
            msg['To'] = to_email
            
            # Plain text version
            text = f"""
            Location Alert
            
            Your tracker "{tracker_name}" is {event_type}.
            
            Tracker: {tracker_name}
            Status: {event_type}
            Coordinates: {latitude}, {longitude}
            Time: {timestamp}
            
            View location on map: https://www.google.com/maps?q={latitude},{longitude}
            
            Best regards,
            {self.brand_name} Team
            """
            
            # HTML version
            html = f"""
            <html>
              <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                  <div style="background-color: {event_color}; padding: 20px; text-align: center; border-radius: 8px 8px 0 0;">
                    <h1 style="color: white; margin: 0; font-size: 32px;">{event_emoji} Location Alert</h1>
                  </div>
                  <div style="background-color: #f4f4f4; padding: 30px; border-radius: 0 0 8px 8px;">
                    <p style="font-size: 18px; margin-top: 0;">
                      Your tracker <strong>"{tracker_name}"</strong> is <strong style="color: {event_color};">{event_type}</strong>.
                    </p>
                    
                    <table style="width: 100%; margin: 20px 0; border-collapse: collapse;">
                      <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;"><strong>Tracker:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;">
                          {tracker_name}
                        </td>
                      </tr>
                      <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;"><strong>Status:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd; color: {event_color}; font-weight: bold;">
                          {event_type}
                        </td>
                      </tr>
                      <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;"><strong>Location:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;">{poi_name}</td>
                      </tr>
                      <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;"><strong>Coordinates:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;">{latitude:.6f}, {longitude:.6f}</td>
                      </tr>
                      <tr>
                        <td style="padding: 10px;"><strong>Time:</strong></td>
                        <td style="padding: 10px;">{timestamp}</td>
                      </tr>
                    </table>
                    
                    <div style="text-align: center; margin: 30px 0;">
                      <a href="https://www.google.com/maps?q={latitude},{longitude}" 
                         style="display: inline-block; background-color: #173C64; color: white; 
                                padding: 12px 30px; text-decoration: none; border-radius: 5px; 
                                font-weight: bold;">
                        📍 View on Map
                      </a>
                    </div>
                    
                    <p style="color: #666; font-size: 12px; margin-top: 30px;">
                      To stop receiving these alerts, you can disable email notifications in your app settings 
                      or disarm the geofence for this tracker.
                    </p>
                  </div>
                  <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
                  <p style="color: #999; font-size: 12px;">Best regards,<br>{self.brand_name} Team</p>
                </div>
              </body>
            </html>
            """
            
            # Send via SendGrid or SMTP
            if self.use_sendgrid:
                return self._send_via_sendgrid(
                    to_email=to_email,
                    subject=f'{event_emoji} Alert: {tracker_name} is {event_type}',
                    text_content=text,
                    html_content=html
                )
            else:
                part1 = MIMEText(text, 'plain')
                part2 = MIMEText(html, 'html')
                msg.attach(part1)
                msg.attach(part2)
                
                # Send email via SMTP
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    if self.smtp_user and self.smtp_password:
                        server.starttls()
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_email, to_email, msg.as_string())
                
                return True
        except Exception as e:
            print(f"Error sending geofence alert email: {e}")
            return False
    
    def send_password_reset_email(self, to_email: str, reset_token: str, first_name: Optional[str] = None) -> bool:
        """Send password reset email with reset link"""
        try:
            # Get base URL from environment or default
            base_url = os.getenv("FRONTEND_URL", self.brand_url)
            reset_link = f"{base_url}?reset_token={reset_token}"
            
            # Development mode - print to console (but still send email)
            if self.debug:
                print(f"\n{'='*60}")
                print(f"🔑 PASSWORD RESET for {to_email}")
                print(f"     Reset Link: {reset_link}")
                print(f"     Token: {reset_token}")
                print(f"{'='*60}\n")
            
            name = first_name if first_name else "there"
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f'Reset Your {self.brand_name} Password'
            msg['From'] = self.from_email
            msg['To'] = to_email
            
            # Plain text version
            text = f"""
            Password Reset Request
            
            Hi {name},
            
            You requested to reset your password for your {self.brand_name} account.
            
            Click the link below to reset your password:
            {reset_link}
            
            This link will expire in 1 hour.
            
            If you didn't request a password reset, please ignore this email and your password will remain unchanged.
            
            Best regards,
            {self.brand_name} Team
            """
            
            # HTML version
            html = f"""
            <html>
              <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                  <div style="background-color: #173C64; padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
                    <h1 style="color: white; margin: 0; font-size: 28px;">🔑 Password Reset</h1>
                  </div>
                  <div style="background-color: #f4f4f4; padding: 30px; border-radius: 0 0 8px 8px;">
                    <p style="font-size: 16px;">Hi {name},</p>
                    <p style="font-size: 16px;">
                      You requested to reset your password for your {self.brand_name} account.
                    </p>
                    <p style="color: #666; font-size: 14px;">
                      Click the link below to reset your password:
                    </p>
                    <p style="background-color: #e8e8e8; padding: 10px; border-radius: 4px; word-break: break-all; font-size: 12px;">
                      {reset_link}
                    </p>
                    <p style="color: #666; font-size: 14px;">
                      This link will expire in <strong>1 hour</strong>.
                    </p>
                    <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
                    <p style="color: #999; font-size: 12px;">
                      If you didn't request a password reset, please ignore this email and your password will remain unchanged.
                    </p>
                  </div>
                  <p style="color: #999; font-size: 12px; margin-top: 20px; text-align: center;">
                    Best regards,<br>{self.brand_name} Team
                  </p>
                </div>
              </body>
            </html>
            """
            
            # Send via SendGrid or SMTP
            if self.use_sendgrid:
                return self._send_via_sendgrid(
                    to_email=to_email,
                    subject=f'Reset Your {self.brand_name} Password',
                    text_content=text,
                    html_content=html
                )
            else:
                part1 = MIMEText(text, 'plain')
                part2 = MIMEText(html, 'html')
                msg.attach(part1)
                msg.attach(part2)
                
                # Send email via SMTP
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    if self.smtp_user and self.smtp_password:
                        server.starttls()
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_email, to_email, msg.as_string())
                
                return True
        except Exception as e:
            print(f"Error sending password reset email: {e}")
            return False
    
    def send_portal_alert_email(self, to_email: str, alert_type: str,
                                 title: str, message: str,
                                 meta_data: dict | None = None) -> bool:
        """Send a portal alert notification email (battery_low, tag_offline,
        geofence_entry, geofence_exit).  Called at most once per alert row."""
        try:
            from html import escape
            meta_data = {k: escape(str(v)) if isinstance(v, str) else v for k, v in (meta_data or {}).items()}
            # ── Per-type styling ──────────────────────────────────────────
            styles = {
                "battery_low":           {"emoji": "🔋", "color": "#F59E0B", "bg": "#FEF3C7", "label": "Battery Low"},
                "tag_offline":           {"emoji": "📴", "color": "#6B7280", "bg": "#F3F4F6", "label": "Tag Offline"},
                "geofence_entry":        {"emoji": "🟢", "color": "#10B981", "bg": "#D1FAE5", "label": "Geofence Entry"},
                "geofence_exit":         {"emoji": "🔴", "color": "#EF4444", "bg": "#FEE2E2", "label": "Geofence Exit"},
                "gdpr_deletion_warning": {"emoji": "🗑️", "color": "#7C3AED", "bg": "#EDE9FE", "label": "Data Deletion Notice"},
            }
            s = styles.get(alert_type, {"emoji": "🔔", "color": "#173C64", "bg": "#EFF6FF", "label": "Alert"})

            # ── Extra detail rows from meta_data ─────────────────────────
            detail_rows = ""
            if "battery" in meta_data:
                detail_rows += f"<tr><td style='padding:6px 12px;color:#666'>Battery level</td><td style='padding:6px 12px'><strong>{meta_data['battery']}%</strong></td></tr>"
            if "days_offline" in meta_data:
                detail_rows += f"<tr><td style='padding:6px 12px;color:#666'>Days offline</td><td style='padding:6px 12px'><strong>{meta_data['days_offline']} days</strong></td></tr>"
            if "poi_name" in meta_data:
                detail_rows += f"<tr><td style='padding:6px 12px;color:#666'>Zone</td><td style='padding:6px 12px'><strong>{meta_data['poi_name']}</strong></td></tr>"
            if "last_seen" in meta_data:
                detail_rows += f"<tr><td style='padding:6px 12px;color:#666'>Last seen</td><td style='padding:6px 12px'>{meta_data['last_seen'][:19].replace('T',' ')}</td></tr>"
            if "imei" in meta_data:
                detail_rows += f"<tr><td style='padding:6px 12px;color:#666'>IMEI</td><td style='padding:6px 12px'>{meta_data['imei']}</td></tr>"
            if "tag_description" in meta_data:
                detail_rows += f"<tr><td style='padding:6px 12px;color:#666'>Description</td><td style='padding:6px 12px'>{meta_data['tag_description']}</td></tr>"
            if "delete_on" in meta_data:
                detail_rows += f"<tr><td style='padding:6px 12px;color:#666'>Scheduled deletion</td><td style='padding:6px 12px'><strong>{meta_data['delete_on']}</strong></td></tr>"

            subject = f"{s['emoji']} {title}"
            text_content = f"{title}\n\n{message}\n\n{self.brand_name} Alerts"
            # Titles and messages can contain user-entered text (vehicle names, rule messages)
            title, message = escape(title), escape(message).replace("\n", "<br>")
            html_content = f"""
            <html>
              <body style="margin:0;padding:0;background:#f9fafb;font-family:Arial,sans-serif;">
                <div style="max-width:560px;margin:32px auto;background:#fff;border-radius:10px;
                            box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden;">
                  <!-- header bar -->
                  <div style="background:{s['color']};padding:20px 28px;display:flex;align-items:center;">
                    <span style="font-size:28px;margin-right:12px">{s['emoji']}</span>
                    <span style="color:#fff;font-size:18px;font-weight:700">{s['label']}</span>
                  </div>
                  <!-- body -->
                  <div style="padding:28px;">
                    <h2 style="margin:0 0 12px;color:#111;font-size:17px">{title}</h2>
                    <p style="margin:0 0 20px;color:#444;font-size:14px;line-height:1.6">{message}</p>
                    {f'<table style="width:100%;border-collapse:collapse;background:{s["bg"]};border-radius:8px;margin-bottom:20px">{detail_rows}</table>' if detail_rows else ''}
                    <a href="{self.brand_url}/#/map"
                       style="display:inline-block;background:#173C64;color:#fff;text-decoration:none;
                              padding:11px 24px;border-radius:6px;font-size:14px;font-weight:600">
                      Open {self.brand_name} →
                    </a>
                  </div>
                  <div style="padding:16px 28px;border-top:1px solid #f0f0f0;background:#fafafa">
                    <p style="margin:0;color:#999;font-size:11px">
                      You are receiving this because you have alert notifications enabled in {self.brand_name}.
                      To change your preferences, visit Settings inside the portal.
                    </p>
                  </div>
                </div>
              </body>
            </html>
            """
            if self.use_sendgrid:
                return self._send_via_sendgrid(to_email, subject, text_content, html_content)
            else:
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = self.from_email
                msg['To'] = to_email
                msg.attach(MIMEText(text_content, 'plain'))
                msg.attach(MIMEText(html_content, 'html'))
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    if self.smtp_user and self.smtp_password:
                        server.starttls()
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_email, to_email, msg.as_string())
                return True
        except Exception as e:
            print(f"Error sending portal alert email: {e}")
            return False

    def send_report_email(self, to_email: str, subject: str, text_content: str, html_content: str,
                          filename: str, content: bytes, mime_type: str) -> bool:
        """Send an email with one file attached (scheduled reports)."""
        try:
            if self.use_sendgrid:
                import base64
                from sendgrid.helpers.mail import Attachment, Disposition, FileContent, FileName, FileType
                message = Mail(from_email=self.from_email, to_emails=to_email, subject=subject,
                               plain_text_content=text_content, html_content=html_content)
                message.attachment = Attachment(FileContent(base64.b64encode(content).decode()),
                                                FileName(filename), FileType(mime_type), Disposition("attachment"))
                response = SendGridAPIClient(self.email_api_key).send(message)
                return 200 <= response.status_code < 300
            from email.mime.application import MIMEApplication
            msg = MIMEMultipart('mixed')
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = to_email
            body = MIMEMultipart('alternative')
            body.attach(MIMEText(text_content, 'plain'))
            body.attach(MIMEText(html_content, 'html'))
            msg.attach(body)
            part = MIMEApplication(content, Name=filename)
            part['Content-Disposition'] = f'attachment; filename="{filename}"'
            msg.attach(part)
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.smtp_user and self.smtp_password:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.from_email, to_email, msg.as_string())
            return True
        except Exception as e:
            print(f"Error sending report email to {to_email}: {e}")
            return False

    def _send_via_sendgrid(self, to_email: str, subject: str, text_content: str, html_content: str) -> bool:
        """Send email using SendGrid API"""
        try:
            message = Mail(
                from_email=self.from_email,
                to_emails=to_email,
                subject=subject,
                plain_text_content=text_content,
                html_content=html_content
            )
            # Disable click tracking so map/Google Maps links are not rewritten
            # to SendGrid redirect URLs (url####.domain/ls/click?upn=...)
            tracking_settings = TrackingSettings()
            tracking_settings.click_tracking = ClickTracking(enable=False, enable_text=False)
            message.tracking_settings = tracking_settings
            
            sg = SendGridAPIClient(self.email_api_key)
            response = sg.send(message)
            
            if response.status_code >= 200 and response.status_code < 300:
                print(f"✅ Email sent via {self.email_provider} to {to_email} (Status: {response.status_code})")
                return True
            else:
                print(f"⚠️  {self.email_provider} returned status {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Error sending email via {self.email_provider}: {e}")
            # Print response body for diagnosis
            if hasattr(e, 'body'):
                print(f"❌ SendGrid error body: {e.body}")
            if hasattr(e, 'status_code'):
                print(f"❌ SendGrid status code: {e.status_code}")
            return False

