"""
IntaSend Payment Service
Handles payment collection (M-Pesa STK Push) and seller payouts (B2C disbursements).
Docs: https://developers.intasend.com/docs/introduction
"""

import os
import requests
import hashlib
import hmac
from datetime import datetime
from typing import Optional, Dict, Any, List

# Environment configuration
INTASEND_API_KEY = os.getenv('INTASEND_API_KEY')
INTASEND_PUBLISHABLE_KEY = os.getenv('INTASEND_PUBLISHABLE_KEY')
INTASEND_WEBHOOK_SECRET = os.getenv('INTASEND_WEBHOOK_SECRET')
INTASEND_SANDBOX = os.getenv('INTASEND_SANDBOX', 'true').lower() == 'true'

# API URLs
INTASEND_SANDBOX_URL = "https://sandbox.intasend.com/api/v1"
INTASEND_PRODUCTION_URL = "https://payment.intasend.com/api/v1"


class IntaSendError(Exception):
    """Custom exception for IntaSend API errors"""
    def __init__(self, message: str, status_code: int = None, response: dict = None):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(self.message)


class IntaSendService:
    """
    IntaSend Payment Gateway Service
    
    Features:
    - M-Pesa STK Push for payment collection
    - Webhook handling for payment confirmations
    - B2C/B2B disbursements for seller payouts
    - Transaction status queries
    """
    
    def __init__(self, api_key: str = None, publishable_key: str = None, sandbox: bool = None):
        self.api_key = api_key or INTASEND_API_KEY
        self.publishable_key = publishable_key or INTASEND_PUBLISHABLE_KEY
        self.sandbox = sandbox if sandbox is not None else INTASEND_SANDBOX
        self.base_url = INTASEND_SANDBOX_URL if self.sandbox else INTASEND_PRODUCTION_URL
        
        if not self.api_key:
            raise ValueError("IntaSend API key is required")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get authentication headers for API requests"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def _make_request(self, method: str, endpoint: str, data: dict = None) -> Dict[str, Any]:
        """Make an authenticated request to IntaSend API"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self._get_headers(),
                json=data,
                timeout=30
            )
            
            result = response.json() if response.content else {}
            
            if not response.ok:
                raise IntaSendError(
                    message=result.get('message', 'IntaSend API error'),
                    status_code=response.status_code,
                    response=result
                )
            
            return result
            
        except requests.RequestException as e:
            raise IntaSendError(f"Request failed: {str(e)}")
    
    # ==================== PAYMENT COLLECTION ====================
    
    def initiate_mpesa_payment(
        self,
        phone_number: str,
        amount: float,
        order_id: str,
        narrative: str = None,
        email: str = None,
        name: str = None
    ) -> Dict[str, Any]:
        """
        Initiate M-Pesa STK Push payment
        
        Args:
            phone_number: Customer's phone number (format: 2547XXXXXXXX)
            amount: Amount in KES
            order_id: Unique order/transaction reference
            narrative: Payment description shown to customer
            email: Customer email for receipt
            name: Customer name
            
        Returns:
            dict with invoice_id, state, and checkout details
        """
        # Normalize phone number to 2547XXXXXXXX format
        phone = self._normalize_phone(phone_number)
        
        payload = {
            "phone_number": phone,
            "amount": amount,
            "api_ref": order_id,
            "narrative": narrative or f"Payment for Order {order_id}",
        }
        
        if email:
            payload["email"] = email
        if name:
            payload["name"] = name
        
        result = self._make_request("POST", "/payment/mpesa-stk-push/", payload)
        
        return {
            "invoice_id": result.get("invoice", {}).get("invoice_id"),
            "state": result.get("invoice", {}).get("state"),
            "checkout_id": result.get("id"),
            "api_ref": order_id,
            "raw_response": result
        }
    
    def initiate_checkout(
        self,
        amount: float,
        order_id: str,
        email: str,
        phone_number: str = None,
        first_name: str = None,
        last_name: str = None,
        redirect_url: str = None,
        wallet_id: str = None
    ) -> Dict[str, Any]:
        """
        Create a checkout session for card/mobile payments
        
        Returns a URL to redirect the customer to for payment
        """
        payload = {
            "amount": amount,
            "currency": "KES",
            "api_ref": order_id,
            "email": email,
        }
        
        if phone_number:
            payload["phone_number"] = self._normalize_phone(phone_number)
        if first_name:
            payload["first_name"] = first_name
        if last_name:
            payload["last_name"] = last_name
        if redirect_url:
            payload["redirect_url"] = redirect_url
        if wallet_id:
            payload["wallet_id"] = wallet_id
        
        result = self._make_request("POST", "/checkout/", payload)
        
        return {
            "checkout_id": result.get("id"),
            "signature": result.get("signature"),
            "url": result.get("url"),
            "api_ref": order_id,
            "raw_response": result
        }
    
    def get_payment_status(self, invoice_id: str) -> Dict[str, Any]:
        """Check the status of a payment"""
        result = self._make_request("GET", f"/payment/status/{invoice_id}/")
        
        return {
            "invoice_id": result.get("invoice", {}).get("invoice_id"),
            "state": result.get("invoice", {}).get("state"),  # PENDING, PROCESSING, COMPLETE, FAILED
            "amount": result.get("invoice", {}).get("value"),
            "api_ref": result.get("invoice", {}).get("api_ref"),
            "raw_response": result
        }
    
    # ==================== SELLER PAYOUTS (B2C) ====================
    
    def send_money(
        self,
        transactions: List[Dict[str, Any]],
        callback_url: str = None
    ) -> Dict[str, Any]:
        """
        Send money to M-Pesa (B2C) or Bank accounts
        
        Args:
            transactions: List of transaction dicts with:
                - account: Phone number (2547XXXXXXXX) or bank account
                - amount: Amount to send
                - narrative: Description
                - name: Recipient name (optional)
            callback_url: URL for status updates
            
        Returns:
            Tracking ID and transaction statuses
        """
        # Prepare transactions
        prepared_txns = []
        for txn in transactions:
            prepared_txns.append({
                "account": self._normalize_phone(txn.get("account", "")),
                "amount": txn.get("amount"),
                "narrative": txn.get("narrative", "Payout"),
                "name": txn.get("name", "")
            })
        
        payload = {
            "provider": "mpesa",  # or "bank" for bank transfers
            "transactions": prepared_txns,
            "currency": "KES"
        }
        
        if callback_url:
            payload["callback_url"] = callback_url
        
        result = self._make_request("POST", "/send-money/initiate/", payload)
        
        return {
            "tracking_id": result.get("tracking_id"),
            "status": result.get("status"),
            "transactions": result.get("transactions", []),
            "raw_response": result
        }
    
    def get_payout_status(self, tracking_id: str) -> Dict[str, Any]:
        """Check the status of a payout batch"""
        result = self._make_request("GET", f"/send-money/status/{tracking_id}/")
        
        return {
            "tracking_id": result.get("tracking_id"),
            "status": result.get("status"),
            "transactions": result.get("transactions", []),
            "raw_response": result
        }
    
    # ==================== REFUNDS ====================
    
    def initiate_refund(
        self,
        invoice_id: str,
        amount: float = None,
        reason: str = None
    ) -> Dict[str, Any]:
        """
        Initiate a refund for a completed transaction
        
        Args:
            invoice_id: Original payment invoice ID
            amount: Refund amount (full refund if not specified)
            reason: Reason for refund
        """
        payload = {
            "invoice_id": invoice_id,
        }
        
        if amount:
            payload["amount"] = amount
        if reason:
            payload["reason"] = reason
        
        result = self._make_request("POST", "/payment/refund/", payload)
        
        return {
            "refund_id": result.get("id"),
            "status": result.get("status"),
            "amount": result.get("amount"),
            "raw_response": result
        }
    
    # ==================== WEBHOOKS ====================
    
    def verify_webhook_signature(self, payload: str, signature: str) -> bool:
        """
        Verify IntaSend webhook signature
        
        Args:
            payload: Raw request body as string
            signature: X-IntaSend-Signature header value
        """
        webhook_secret = INTASEND_WEBHOOK_SECRET
        if not webhook_secret:
            return False
        
        expected_signature = hmac.new(
            webhook_secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature)
    
    def parse_webhook_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse and normalize webhook payload
        
        Returns standardized event data
        """
        invoice = payload.get("invoice", {})
        
        return {
            "event_type": payload.get("state"),  # COMPLETE, FAILED, etc.
            "invoice_id": invoice.get("invoice_id"),
            "api_ref": invoice.get("api_ref"),  # Our order_id
            "amount": invoice.get("value"),
            "phone": invoice.get("account"),
            "state": invoice.get("state"),
            "failed_reason": invoice.get("failed_reason"),
            "created_at": invoice.get("created_at"),
            "updated_at": invoice.get("updated_at"),
        }
    
    # ==================== HELPERS ====================
    
    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number to 2547XXXXXXXX format"""
        if not phone:
            return phone
            
        # Remove any spaces, dashes, or plus signs
        phone = phone.replace(" ", "").replace("-", "").replace("+", "")
        
        # Handle different formats
        if phone.startswith("0"):
            phone = "254" + phone[1:]
        elif phone.startswith("7") or phone.startswith("1"):
            phone = "254" + phone
        elif not phone.startswith("254"):
            phone = "254" + phone
        
        return phone


# Singleton instance for convenience
_intasend_service = None

def get_intasend_service() -> IntaSendService:
    """Get or create the IntaSend service singleton"""
    global _intasend_service
    if _intasend_service is None:
        _intasend_service = IntaSendService()
    return _intasend_service
