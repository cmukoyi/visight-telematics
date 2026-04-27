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
        # SendGrid configuration (preferred for production)
        self.sendgrid_api_key = os.getenv("SENDGRID_API_KEY", "")
        self.use_sendgrid = bool(self.sendgrid_api_key) and SENDGRID_AVAILABLE
        
        # SMTP configuration (fallback or development)
        self.smtp_host = os.getenv("SMTP_HOST", "mailhog")
        self.smtp_port = int(os.getenv("SMTP_PORT", "1025"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.from_email = os.getenv("FROM_EMAIL", "noreply@pinplot.me")
        self.debug = os.getenv("DEBUG", "False").lower() == "true"
        
        # Log email service configuration
        if self.use_sendgrid:
            print("📧 Email Service: Using SendGrid API")
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
            msg['Subject'] = 'Your Pinplot Verification Code'
            msg['From'] = self.from_email
            msg['To'] = to_email
            
            # Plain text version
            text = f"""
            Your verification code is: {pin}
            
            This code will expire in 10 minutes.
            
            If you didn't request this code, please ignore this email.
            
            Best regards,
            Pinplot Team
            """
            
            # HTML version
            html = f"""
            <html>
              <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                  <h2 style="color: #173C64;">Pinplot Verification</h2>
                  <p>Your verification code is:</p>
                  <div style="background-color: #f4f4f4; padding: 20px; text-align: center; border-radius: 8px; margin: 20px 0;">
                    <h1 style="color: #173C64; font-size: 36px; letter-spacing: 8px; margin: 0;">{pin}</h1>
                  </div>
                  <p style="color: #666;">This code will expire in <strong>10 minutes</strong>.</p>
                  <p style="color: #666;">If you didn't request this code, please ignore this email.</p>
                  <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
                  <p style="color: #999; font-size: 12px;">Best regards,<br>Pinplot Team</p>
                </div>
              </body>
            </html>
            """
            
            # Send via SendGrid or SMTP
            if self.use_sendgrid:
                return self._send_via_sendgrid(
                    to_email=to_email,
                    subject='Your Pinplot Verification Code',
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
    
    def send_welcome_email(self, to_email: str, first_name: Optional[str] = None) -> bool:
        """Send welcome email after successful registration"""
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = 'Welcome to Pinplot'
            msg['From'] = self.from_email
            msg['To'] = to_email
            
            name = first_name if first_name else "there"
            
            html = f"""
            <html>
              <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                  <h2 style="color: #173C64;">Welcome to Pinplot!</h2>
                  <p>Hi {name},</p>
                  <p>Thank you for joining BLE Tracker. Your account has been successfully created.</p>
                  <p>You can now start adding and tracking your BLE devices.</p>
                  <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
                  <p style="color: #999; font-size: 12px;">Best regards,<br>Pinplot Team</p>
                </div>
              </body>
            </html>
            """
            
            # Send via SendGrid or SMTP
            if self.use_sendgrid:
                return self._send_via_sendgrid(
                    to_email=to_email,
                    subject='Welcome to Pinplot',
                    text_content="Welcome to BLE Tracker!",
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
            Pinplot Team
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
                  <p style="color: #999; font-size: 12px;">Best regards,<br>Pinplot Team</p>
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
            base_url = os.getenv("FRONTEND_URL", "https://pinplot.me")
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
            msg['Subject'] = 'Reset Your Pinplot Password'
            msg['From'] = self.from_email
            msg['To'] = to_email
            
            # Plain text version
            text = f"""
            Password Reset Request
            
            Hi {name},
            
            You requested to reset your password for your Pinplot account.
            
            Click the link below to reset your password:
            {reset_link}
            
            This link will expire in 1 hour.
            
            If you didn't request a password reset, please ignore this email and your password will remain unchanged.
            
            Best regards,
            Pinplot Team
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
                      You requested to reset your password for your Pinplot account.
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
                    Best regards,<br>Pinplot Team
                  </p>
                </div>
              </body>
            </html>
            """
            
            # Send via SendGrid or SMTP
            if self.use_sendgrid:
                return self._send_via_sendgrid(
                    to_email=to_email,
                    subject='Reset Your Pinplot Password',
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
            
            sg = SendGridAPIClient(self.sendgrid_api_key)
            response = sg.send(message)
            
            if response.status_code >= 200 and response.status_code < 300:
                print(f"✅ Email sent via SendGrid to {to_email} (Status: {response.status_code})")
                return True
            else:
                print(f"⚠️  SendGrid returned status {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Error sending email via SendGrid: {e}")
            # Print SendGrid response body for diagnosis
            if hasattr(e, 'body'):
                print(f"❌ SendGrid error body: {e.body}")
            if hasattr(e, 'status_code'):
                print(f"❌ SendGrid status code: {e.status_code}")
            return False

