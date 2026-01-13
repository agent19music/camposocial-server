"""
Badge Payment Service
A unified abstraction for badge payments that supports switching between
IntaSend and native M-Pesa providers via environment variable.

Usage:
    from badge_payment_service import get_badge_payment_service
    
    service = get_badge_payment_service()
    result = service.initiate_payment(phone_number, amount, order_ref, ...)
    status = service.check_payment_status(checkout_id)

Configuration:
    Set BADGE_PAYMENT_PROVIDER environment variable:
    - 'intasend' (default) - Uses IntaSend's M-Pesa wrapper
    - 'mpesa' - Uses native Safaricom M-Pesa API
"""

import os
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime


class PaymentResult:
    """Standardized payment result across providers"""
    def __init__(
        self,
        success: bool,
        checkout_id: Optional[str] = None,
        invoice_id: Optional[str] = None,
        state: str = 'PENDING',
        error_message: Optional[str] = None,
        raw_response: Optional[Dict] = None,
        provider: str = 'unknown'
    ):
        self.success = success
        self.checkout_id = checkout_id
        self.invoice_id = invoice_id
        self.state = state
        self.error_message = error_message
        self.raw_response = raw_response or {}
        self.provider = provider


class PaymentStatusResult:
    """Standardized payment status result across providers"""
    def __init__(
        self,
        state: str,
        completed: bool = False,
        failed: bool = False,
        receipt_number: Optional[str] = None,
        error_message: Optional[str] = None,
        raw_response: Optional[Dict] = None
    ):
        self.state = state
        self.completed = completed
        self.failed = failed
        self.receipt_number = receipt_number
        self.error_message = error_message
        self.raw_response = raw_response or {}


class BadgePaymentProvider(ABC):
    """Abstract base class for payment providers"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider name"""
        pass
    
    @abstractmethod
    def initiate_payment(
        self,
        phone_number: str,
        amount: float,
        order_ref: str,
        description: str,
        email: Optional[str] = None,
        customer_name: Optional[str] = None
    ) -> PaymentResult:
        """Initiate an STK push payment"""
        pass
    
    @abstractmethod
    def check_payment_status(self, checkout_id: str) -> PaymentStatusResult:
        """Check the status of a payment"""
        pass


class IntaSendProvider(BadgePaymentProvider):
    """IntaSend payment provider implementation"""
    
    @property
    def name(self) -> str:
        return 'intasend'
    
    def initiate_payment(
        self,
        phone_number: str,
        amount: float,
        order_ref: str,
        description: str,
        email: Optional[str] = None,
        customer_name: Optional[str] = None
    ) -> PaymentResult:
        from intasend_service import get_intasend_service, IntaSendError
        
        try:
            intasend = get_intasend_service()
            response = intasend.initiate_mpesa_payment(
                phone_number=phone_number,
                amount=amount,
                order_id=order_ref,
                narrative=description,
                email=email,
                name=customer_name
            )
            
            return PaymentResult(
                success=True,
                checkout_id=response.get('checkout_id'),
                invoice_id=response.get('invoice_id'),
                state=response.get('state', 'PENDING'),
                raw_response=response.get('raw_response', {}),
                provider=self.name
            )
        except IntaSendError as e:
            return PaymentResult(
                success=False,
                error_message=str(e),
                provider=self.name
            )
        except Exception as e:
            return PaymentResult(
                success=False,
                error_message=f"Unexpected error: {str(e)}",
                provider=self.name
            )
    
    def check_payment_status(self, checkout_id: str) -> PaymentStatusResult:
        from intasend_service import get_intasend_service, IntaSendError
        
        try:
            intasend = get_intasend_service()
            response = intasend.get_payment_status(checkout_id)
            state = response.get('state', '').upper()
            
            return PaymentStatusResult(
                state=state,
                completed=state == 'COMPLETE',
                failed=state == 'FAILED',
                receipt_number=response.get('raw_response', {}).get('invoice', {}).get('mpesa_reference'),
                raw_response=response.get('raw_response', {})
            )
        except IntaSendError as e:
            return PaymentStatusResult(
                state='UNKNOWN',
                error_message=str(e)
            )
        except Exception as e:
            return PaymentStatusResult(
                state='UNKNOWN',
                error_message=f"Unexpected error: {str(e)}"
            )


class MPESAProvider(BadgePaymentProvider):
    """Native M-Pesa payment provider implementation"""
    
    @property
    def name(self) -> str:
        return 'mpesa'
    
    def initiate_payment(
        self,
        phone_number: str,
        amount: float,
        order_ref: str,
        description: str,
        email: Optional[str] = None,
        customer_name: Optional[str] = None
    ) -> PaymentResult:
        from mpesa_service import mpesa_service
        
        try:
            response = mpesa_service.stk_push(
                phone_number=phone_number,
                amount=int(amount),  # M-Pesa requires integer amounts
                account_reference=order_ref,
                transaction_desc=description
            )
            
            # M-Pesa returns CheckoutRequestID on success
            checkout_request_id = response.get('CheckoutRequestID')
            response_code = response.get('ResponseCode')
            
            if response_code == '0' and checkout_request_id:
                return PaymentResult(
                    success=True,
                    checkout_id=checkout_request_id,
                    invoice_id=checkout_request_id,  # Use same ID for consistency
                    state='PENDING',
                    raw_response=response,
                    provider=self.name
                )
            else:
                return PaymentResult(
                    success=False,
                    error_message=response.get('ResponseDescription', 'STK push failed'),
                    raw_response=response,
                    provider=self.name
                )
        except Exception as e:
            return PaymentResult(
                success=False,
                error_message=str(e),
                provider=self.name
            )
    
    def check_payment_status(self, checkout_id: str) -> PaymentStatusResult:
        from mpesa_service import mpesa_service
        
        try:
            response = mpesa_service.query_transaction_status(checkout_id)
            
            result_code = response.get('ResultCode')
            
            # ResultCode 0 = success, 1032 = cancelled, others = failed
            if result_code == '0' or result_code == 0:
                return PaymentStatusResult(
                    state='COMPLETE',
                    completed=True,
                    receipt_number=response.get('MpesaReceiptNumber'),
                    raw_response=response
                )
            elif result_code == '1032' or result_code == 1032:
                return PaymentStatusResult(
                    state='CANCELLED',
                    failed=True,
                    error_message='Transaction cancelled by user',
                    raw_response=response
                )
            elif result_code is not None:
                return PaymentStatusResult(
                    state='FAILED',
                    failed=True,
                    error_message=response.get('ResultDesc', 'Payment failed'),
                    raw_response=response
                )
            else:
                # Still processing
                return PaymentStatusResult(
                    state='PENDING',
                    raw_response=response
                )
        except Exception as e:
            return PaymentStatusResult(
                state='UNKNOWN',
                error_message=str(e)
            )


# Provider registry
_PROVIDERS = {
    'intasend': IntaSendProvider,
    'mpesa': MPESAProvider
}

# Singleton instance
_badge_payment_service: Optional[BadgePaymentProvider] = None


def get_badge_payment_service() -> BadgePaymentProvider:
    """
    Get the configured badge payment service.
    
    Reads BADGE_PAYMENT_PROVIDER from environment:
    - 'intasend' (default): Use IntaSend M-Pesa wrapper
    - 'mpesa': Use native Safaricom M-Pesa API
    """
    global _badge_payment_service
    
    provider_name = os.getenv('BADGE_PAYMENT_PROVIDER', 'intasend').lower().strip()
    
    # Check if we need to create a new instance (different provider or first call)
    if _badge_payment_service is None or _badge_payment_service.name != provider_name:
        provider_class = _PROVIDERS.get(provider_name)
        if not provider_class:
            raise ValueError(
                f"Unknown payment provider: {provider_name}. "
                f"Valid options: {', '.join(_PROVIDERS.keys())}"
            )
        _badge_payment_service = provider_class()
    
    return _badge_payment_service


def get_current_provider_name() -> str:
    """Get the name of the currently configured provider"""
    return os.getenv('BADGE_PAYMENT_PROVIDER', 'intasend').lower()
