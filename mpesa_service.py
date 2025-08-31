import requests
import json
import base64
from datetime import datetime
import os
from flask import current_app

class MPESAService:
    def __init__(self):
        # M-Pesa Configuration - Set these in your environment variables
        self.consumer_key = os.getenv('MPESA_CONSUMER_KEY')
        self.consumer_secret = os.getenv('MPESA_CONSUMER_SECRET')
        self.business_short_code = os.getenv('MPESA_BUSINESS_SHORT_CODE', '174379')  # Sandbox shortcode
        self.passkey = os.getenv('MPESA_PASSKEY')
        self.callback_url = os.getenv('MPESA_CALLBACK_URL', 'https://your-app.com/api/mpesa/callback')
        
        # Environment URLs
        self.is_sandbox = os.getenv('MPESA_ENVIRONMENT', 'sandbox') == 'sandbox'
        if self.is_sandbox:
            self.base_url = 'https://sandbox.safaricom.co.ke'
        else:
            self.base_url = 'https://api.safaricom.co.ke'
    
    def get_access_token(self):
        """Get OAuth access token from M-Pesa"""
        try:
            api_url = f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials"
            
            # Create credentials string and encode
            credentials = f"{self.consumer_key}:{self.consumer_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            headers = {
                'Authorization': f'Basic {encoded_credentials}'
            }
            
            response = requests.get(api_url, headers=headers)
            response.raise_for_status()
            
            return response.json()['access_token']
        
        except Exception as e:
            current_app.logger.error(f"Error getting M-Pesa access token: {str(e)}")
            raise e
    
    def generate_password(self, timestamp):
        """Generate password for STK push"""
        data_to_encode = f"{self.business_short_code}{self.passkey}{timestamp}"
        encoded_string = base64.b64encode(data_to_encode.encode()).decode()
        return encoded_string
    
    def stk_push(self, phone_number, amount, account_reference, transaction_desc):
        """Initiate STK Push payment"""
        try:
            access_token = self.get_access_token()
            api_url = f"{self.base_url}/mpesa/stkpush/v1/processrequest"
            
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            password = self.generate_password(timestamp)
            
            # Format phone number (remove + and ensure it starts with 254)
            if phone_number.startswith('+'):
                phone_number = phone_number[1:]
            if phone_number.startswith('0'):
                phone_number = '254' + phone_number[1:]
            if not phone_number.startswith('254'):
                phone_number = '254' + phone_number
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                "BusinessShortCode": self.business_short_code,
                "Password": password,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": amount,
                "PartyA": phone_number,
                "PartyB": self.business_short_code,
                "PhoneNumber": phone_number,
                "CallBackURL": self.callback_url,
                "AccountReference": account_reference,
                "TransactionDesc": transaction_desc
            }
            
            response = requests.post(api_url, json=payload, headers=headers)
            response.raise_for_status()
            
            return response.json()
        
        except Exception as e:
            current_app.logger.error(f"Error initiating STK push: {str(e)}")
            raise e
    
    def query_transaction_status(self, checkout_request_id):
        """Query the status of a transaction"""
        try:
            access_token = self.get_access_token()
            api_url = f"{self.base_url}/mpesa/stkpushquery/v1/query"
            
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            password = self.generate_password(timestamp)
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                "BusinessShortCode": self.business_short_code,
                "Password": password,
                "Timestamp": timestamp,
                "CheckoutRequestID": checkout_request_id
            }
            
            response = requests.post(api_url, json=payload, headers=headers)
            response.raise_for_status()
            
            return response.json()
        
        except Exception as e:
            current_app.logger.error(f"Error querying transaction status: {str(e)}")
            raise e

# Initialize the service
mpesa_service = MPESAService()
