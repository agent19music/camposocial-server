"""
Test script for M-Pesa integration
Run this to verify your M-Pesa credentials are working
"""

import os
import sys
from dotenv import load_dotenv

# Add the parent directory to sys.path to import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mpesa_service import MPESAService

def test_mpesa_connection():
    """Test M-Pesa connection and credentials"""
    load_dotenv()
    
    print("🧪 Testing M-Pesa Integration...")
    print("=" * 50)
    
    # Check environment variables
    required_vars = [
        'MPESA_CONSUMER_KEY',
        'MPESA_CONSUMER_SECRET',
        'MPESA_BUSINESS_SHORT_CODE',
        'MPESA_PASSKEY'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print("❌ Missing environment variables:")
        for var in missing_vars:
            print(f"   - {var}")
        print("\nPlease check your .env file and try again.")
        return False
    
    print("✅ All environment variables found")
    
    # Test access token
    try:
        mpesa = MPESAService()
        print("📡 Testing access token...")
        token = mpesa.get_access_token()
        print(f"✅ Access token obtained: {token[:20]}...")
        
        # Test STK Push (using test phone number)
        print("📱 Testing STK Push initiation...")
        test_phone = "254708374149"  # Safaricom test number
        
        response = mpesa.stk_push(
            phone_number=test_phone,
            amount=1,  # 1 KSH for testing
            account_reference="TEST_BADGE_001",
            transaction_desc="Test Badge Purchase"
        )
        
        if response.get('CheckoutRequestID'):
            print(f"✅ STK Push initiated successfully")
            print(f"   Checkout Request ID: {response['CheckoutRequestID']}")
            print(f"   Response Code: {response.get('ResponseCode')}")
            print(f"   Description: {response.get('ResponseDescription')}")
        else:
            print("❌ STK Push failed:")
            print(f"   Error: {response.get('errorMessage', 'Unknown error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing M-Pesa: {str(e)}")
        return False
    
    print("\n🎉 M-Pesa integration test completed successfully!")
    print("You can now proceed with badge purchases.")
    return True

if __name__ == "__main__":
    success = test_mpesa_connection()
    sys.exit(0 if success else 1)
