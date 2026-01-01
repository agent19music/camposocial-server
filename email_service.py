"""
Email Service using Resend API
Handles transactional emails for order confirmations, shipping updates, etc.
Docs: https://resend.com/docs/api-reference/introduction
"""

import os
from typing import Optional, List, Dict, Any
from datetime import datetime

# Environment configuration
RESEND_API_KEY = os.getenv('RESEND_API_KEY')
EMAIL_FROM_ADDRESS = os.getenv('EMAIL_FROM_ADDRESS', 'CampoSocial <orders@camposocial.app>')
EMAIL_REPLY_TO = os.getenv('EMAIL_REPLY_TO', 'support@camposocial.app')


class EmailError(Exception):
    """Custom exception for email errors"""
    def __init__(self, message: str, status_code: int = None, response: dict = None):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(self.message)


class EmailService:
    """
    Email service using Resend API
    
    Features:
    - Order confirmation emails
    - Seller new order notifications
    - Shipping update emails
    - Order status change emails
    """
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or RESEND_API_KEY
        self.from_address = EMAIL_FROM_ADDRESS
        self.reply_to = EMAIL_REPLY_TO
        
        try:
            import resend
            self.resend = resend
            if self.api_key:
                resend.api_key = self.api_key
        except ImportError:
            self.resend = None
    
    def is_configured(self) -> bool:
        """Check if email service is properly configured"""
        return self.resend is not None and self.api_key is not None
    
    def send_email(
        self,
        to: str | List[str],
        subject: str,
        html: str,
        text: str = None,
        reply_to: str = None,
        tags: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Send an email using Resend API
        
        Args:
            to: Recipient email(s)
            subject: Email subject
            html: HTML content
            text: Plain text content (optional)
            reply_to: Reply-to address (optional)
            tags: Email tags for analytics (optional)
        """
        if not self.is_configured():
            raise EmailError("Email service not configured")
        
        payload = {
            "from": self.from_address,
            "to": to if isinstance(to, list) else [to],
            "subject": subject,
            "html": html,
        }
        
        if text:
            payload["text"] = text
        if reply_to:
            payload["reply_to"] = reply_to
        elif self.reply_to:
            payload["reply_to"] = self.reply_to
        if tags:
            payload["tags"] = tags
        
        try:
            result = self.resend.Emails.send(payload)
            return {"id": result.get("id"), "success": True}
        except Exception as e:
            raise EmailError(f"Failed to send email: {str(e)}")
    
    # ==================== AUTHENTICATION EMAILS ====================
    
    def send_verification_otp(self, to_email: str, otp_code: str, display_name: str = None) -> Dict[str, Any]:
        """
        Send OTP verification email for account registration
        
        Args:
            to_email: Recipient email address
            otp_code: 6-digit verification code
            display_name: User's display name (optional)
        """
        greeting = f"Hi {display_name}," if display_name else "Hi there,"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; background-color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            <div style="width: 100%; padding: 40px 0;">
                <div style="max-width: 480px; margin: 0 auto; background-color: #ffffff; padding: 40px; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
                    
                    <!-- Logo/Header -->
                    <div style="text-align: center; margin-bottom: 30px;">
                        <h1 style="margin: 0; font-size: 28px; color: #1f2937; letter-spacing: -0.5px;">CampoSocial</h1>
                        <p style="margin: 5px 0 0; color: #6b7280; font-size: 14px;">Verify your email address</p>
                    </div>
                    
                    <!-- Greeting -->
                    <p style="color: #374151; font-size: 16px; margin-bottom: 20px;">{greeting}</p>
                    
                    <p style="color: #374151; font-size: 16px; margin-bottom: 30px;">
                        Welcome to CampoSocial! Please use the verification code below to complete your registration.
                    </p>
                    
                    <!-- OTP Code Box -->
                    <div style="background: linear-gradient(135deg, #ff9013 0%, #ff6b00 100%); padding: 30px; border-radius: 12px; text-align: center; margin: 30px 0;">
                        <p style="margin: 0 0 10px; color: rgba(255,255,255,0.9); font-size: 14px; text-transform: uppercase; letter-spacing: 2px;">Your Verification Code</p>
                        <p style="margin: 0; color: white; font-size: 40px; font-weight: bold; font-family: 'Courier New', monospace; letter-spacing: 8px;">{otp_code}</p>
                    </div>
                    
                    <!-- Expiry Notice -->
                    <p style="color: #9ca3af; font-size: 14px; text-align: center; margin: 20px 0;">
                        This code will expire in <strong style="color: #6b7280;">10 minutes</strong>
                    </p>
                    
                    <!-- Security Notice -->
                    <p style="margin: 30px 0 0; color: #9ca3af; font-size: 12px; text-align: center;">
                        If you didn't request this code, you can safely ignore this email.
                    </p>
                    
                    <!-- Footer -->
                    <div style="text-align: center; color: #9ca3af; font-size: 12px; margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb;">
                        <p style="margin: 0;">Need help? Contact us at support@camposocial.app</p>
                        <p style="margin: 10px 0 0;">&copy; {datetime.utcnow().year} CampoSocial. All rights reserved.</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Override from_address to use auth@ for verification emails
        original_from = self.from_address
        self.from_address = "CampoSocial <auth@camposocial.app>"
        
        try:
            result = self.send_email(
                to=to_email,
                subject=f"Your CampoSocial Verification Code: {otp_code}",
                html=html,
                tags=[{"name": "category", "value": "email_verification"}]
            )
            return result
        finally:
            self.from_address = original_from
    
    # ==================== ORDER EMAILS ====================
    
    def send_order_confirmation(self, order) -> Dict[str, Any]:
        """
        Send order confirmation email to buyer (Vintage Receipt Style)
        
        Args:
            order: Order object with customer details and items
        """
        items_html = ""
        for item in order.order_items:
            product = item.product
            price = item.price_at_purchase or (product.price if product else 0)
            items_html += f"""
            <tr>
                <td style="padding: 8px 0; font-family: 'Courier New', Courier, monospace; color: #333;">{product.title if product else 'Product'} <span style="color: #666; font-size: 12px;">x {item.quantity}</span></td>
                <td style="padding: 8px 0; text-align: right; font-family: 'Courier New', Courier, monospace; font-weight: bold; color: #333;">KES {item.total_item_price():,.2f}</td>
            </tr>
            """
        
        # Calculate discount display
        discount_html = ""
        if order.discount_amount > 0:
            discount_html = f"""
            <tr>
                <td style="padding: 8px 0; font-family: 'Courier New', Courier, monospace; color: #333;">Discount ({order.discount_code})</td>
                <td style="padding: 8px 0; text-align: right; font-family: 'Courier New', Courier, monospace; color: #ef4444;">- KES {order.discount_amount:,.2f}</td>
            </tr>
            """

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; background-color: #f3f4f6; font-family: 'Courier New', Courier, monospace;">
            <div style="width: 100%; padding: 40px 0;">
                <!-- Receipt Container -->
                <div style="max-width: 480px; margin: 0 auto; background-color: #fffcf8; padding: 40px; border-radius: 2px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06); position: relative; overflow: hidden;">
                    
                    <!-- Dotted Pattern Background (Simulated) -->
                    <div style="position: absolute; top: 0; left: 0; right: 0; height: 8px; background-image: radial-gradient(#e5e7eb 1px, transparent 1px); background-size: 8px 8px; opacity: 0.5;"></div>

                    <!-- PAID Stamp -->
                    <div style="position: absolute; top: 20px; right: 20px; border: 3px solid #22c55e; color: #22c55e; padding: 10px 20px; font-weight: bold; font-size: 20px; text-transform: uppercase; transform: rotate(12deg); opacity: 0.8; border-radius: 8px; font-family: sans-serif; letter-spacing: 2px;">
                        PAID
                    </div>

                    <!-- Header -->
                    <div style="text-align: center; border-bottom: 2px dashed #d1d5db; padding-bottom: 20px; margin-bottom: 20px;">
                        <h1 style="margin: 0; font-size: 24px; color: #1f2937; letter-spacing: -0.5px; text-transform: uppercase;">CampoSocial</h1>
                        <p style="margin: 5px 0 0; color: #6b7280; font-size: 12px;">Marketplace Receipt</p>
                    </div>

                    <!-- Order Info -->
                    <div style="margin-bottom: 20px;">
                        <table style="width: 100%; font-size: 14px;">
                            <tr>
                                <td style="color: #6b7280;">Order Number:</td>
                                <td style="text-align: right; font-weight: bold; color: #1f2937;">{order.ticket_number or order.id}</td>
                            </tr>
                            <tr>
                                <td style="color: #6b7280;">Date:</td>
                                <td style="text-align: right; font-weight: bold; color: #1f2937;">{order.created_at.strftime('%d %b %Y')}</td>
                            </tr>
                        </table>
                    </div>

                    <!-- Divider -->
                    <div style="border-bottom: 2px dashed #d1d5db; margin: 20px 0;"></div>

                    <!-- Customer Details -->
                    <div style="margin-bottom: 20px;">
                        <h3 style="margin: 0 0 10px; font-size: 14px; text-transform: uppercase; color: #1f2937;">Customer Details</h3>
                        <p style="margin: 0; font-size: 14px; color: #4b5563;">{order.first_name} {order.last_name}</p>
                        <p style="margin: 5px 0 0; font-size: 14px; color: #4b5563;">{order.email}</p>
                        <p style="margin: 5px 0 0; font-size: 14px; color: #4b5563;">{order.phone}</p>
                    </div>

                    <!-- Divider -->
                    <div style="border-bottom: 2px dashed #d1d5db; margin: 20px 0;"></div>

                    <!-- Items -->
                    <div style="margin-bottom: 20px;">
                        <h3 style="margin: 0 0 10px; font-size: 14px; text-transform: uppercase; color: #1f2937;">Order Items</h3>
                        <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                            {items_html}
                            {discount_html}
                        </table>
                    </div>

                    <!-- Divider -->
                    <div style="border-bottom: 2px dashed #d1d5db; margin: 20px 0;"></div>

                    <!-- Total -->
                    <div style="margin-bottom: 30px;">
                        <table style="width: 100%; font-size: 18px;">
                            <tr>
                                <td style="font-weight: bold; color: #1f2937;">TOTAL</td>
                                <td style="text-align: right; font-weight: bold; color: #1f2937;">KES {order.total_price:,.2f}</td>
                            </tr>
                        </table>
                    </div>

                    <!-- Footer -->
                    <div style="text-align: center; color: #9ca3af; font-size: 12px;">
                        <p style="margin: 0;">Keep this receipt for your records.</p>
                        <p style="margin: 5px 0 0;">Thank you for shopping with us! 🛍️</p>
                    </div>

                    <!-- Jagged Edge (Simulated with border) -->
                    <div style="margin-top: 30px; height: 10px; background: repeating-linear-gradient(45deg, #fffcf8, #fffcf8 10px, #f3f4f6 10px, #f3f4f6 20px);"></div>
                </div>
                
                <div style="text-align: center; margin-top: 20px; color: #6b7280; font-size: 12px; font-family: sans-serif;">
                    &copy; {datetime.utcnow().year} CampoSocial. All rights reserved.
                </div>
            </div>
        </body>
        </html>
        """
        
        return self.send_email(
            to=order.email,
            subject=f"Receipt for Order {order.ticket_number or order.id}",
            html=html,
            tags=[{"name": "category", "value": "order_confirmation"}]
        )
    
    def send_seller_new_order_notification(self, order, seller, seller_items) -> Dict[str, Any]:
        """
        Notify seller about a new order containing their products
        
        Args:
            order: Order object
            seller: Seller object
            seller_items: List of OrderItem objects belonging to this seller
        """
        items_html = ""
        seller_total = 0
        for item in seller_items:
            product = item.product
            price = item.price_at_purchase or (product.price if product else 0)
            item_total = item.total_item_price()
            seller_total += item_total
            items_html += f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #eee;">{product.title if product else 'Product'}</td>
                <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: center;">{item.quantity}</td>
                <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: right;">KES {item_total:,.2f}</td>
            </tr>
            """
        
        # Get seller's user email
        from models import Users
        user = Users.query.get(seller.user_id)
        if not user:
            raise EmailError("Seller user not found")
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background-color: #f4f4f5;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 24px;">New Order Received! 📦</h1>
                </div>
                
                <div style="background: white; padding: 30px; border-radius: 0 0 12px 12px;">
                    <p style="color: #374151; font-size: 16px;">Hi {seller.display_name},</p>
                    
                    <p style="color: #374151; font-size: 16px;">You have a new order! Please process it as soon as possible.</p>
                    
                    <div style="background: #fef3c7; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <p style="margin: 0; color: #92400e; font-size: 14px;">Order Number: <strong>{order.ticket_number or order.id}</strong></p>
                        <p style="margin: 10px 0 0; color: #92400e; font-size: 14px;">Your Earnings: <strong style="font-size: 18px;">KES {seller_total:,.2f}</strong></p>
                    </div>
                    
                    <h3 style="color: #374151;">Customer Details</h3>
                    <p style="color: #6b7280; margin: 5px 0;">Name: {order.first_name} {order.last_name}</p>
                    <p style="color: #6b7280; margin: 5px 0;">Phone: {order.phone}</p>
                    <p style="color: #6b7280; margin: 5px 0;">Address: {order.address}</p>
                    
                    <h3 style="color: #374151;">Your Items</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="background: #f9fafb;">
                                <th style="padding: 12px; text-align: left;">Product</th>
                                <th style="padding: 12px; text-align: center;">Qty</th>
                                <th style="padding: 12px; text-align: right;">Total</th>
                            </tr>
                        </thead>
                        <tbody>
                            {items_html}
                        </tbody>
                    </table>
                    
                    <div style="text-align: center; margin-top: 30px;">
                        <a href="https://seller.camposocial.app/orders/{order.id}" style="display: inline-block; background: #667eea; color: white; padding: 12px 30px; text-decoration: none; border-radius: 8px; font-weight: 600;">View Order in Dashboard</a>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self.send_email(
            to=user.email,
            subject=f"New Order - {order.ticket_number or order.id} - KES {seller_total:,.2f}",
            html=html,
            tags=[{"name": "category", "value": "seller_notification"}]
        )
    
    def send_shipping_update(self, order, tracking_number: str, carrier: str = None) -> Dict[str, Any]:
        """
        Send shipping notification to buyer
        
        Args:
            order: Order object
            tracking_number: Shipping tracking number
            carrier: Shipping carrier name (optional)
        """
        carrier_text = f" via {carrier}" if carrier else ""
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background-color: #f4f4f5;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 24px;">Your Order is on the Way! 🚚</h1>
                </div>
                
                <div style="background: white; padding: 30px; border-radius: 0 0 12px 12px;">
                    <p style="color: #374151; font-size: 16px;">Hi {order.first_name},</p>
                    
                    <p style="color: #374151; font-size: 16px;">Great news! Your order <strong>{order.ticket_number or order.id}</strong> has been shipped{carrier_text}.</p>
                    
                    <div style="background: #ecfdf5; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #10b981;">
                        <p style="margin: 0; color: #065f46; font-size: 14px;">Tracking Number</p>
                        <p style="margin: 5px 0 0; color: #111827; font-size: 20px; font-weight: bold; font-family: monospace;">{tracking_number}</p>
                    </div>
                    
                    <p style="color: #6b7280; font-size: 14px;">
                        Your package will be delivered to:<br>
                        <strong>{order.address}</strong>
                    </p>
                    
                    <p style="color: #6b7280; font-size: 14px; margin-top: 30px;">
                        If you have any questions, contact us at support@camposocial.app
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self.send_email(
            to=order.email,
            subject=f"Your Order is on the Way - {order.ticket_number or order.id}",
            html=html,
            tags=[{"name": "category", "value": "shipping_update"}]
        )


# Singleton instance
_email_service = None

def get_email_service() -> EmailService:
    """Get or create the email service singleton"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
