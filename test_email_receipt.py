import os
import sys
import site
from datetime import datetime
from dotenv import load_dotenv

# Ensure user site packages are in path
# This helps if pip installed to ~/.local but python isn't picking it up
sys.path.append(site.getusersitepackages())

try:
    import resend
    print(f"✅ Resend module imported successfully: {resend.__file__}")
except ImportError as e:
    print(f"❌ Failed to import resend: {e}")

# Load environment variables
load_dotenv()

from email_service import get_email_service

# Mock classes to simulate database models
class MockProduct:
    def __init__(self, title, price):
        self.title = title
        self.price = price

class MockOrderItem:
    def __init__(self, product, quantity, price_at_purchase):
        self.product = product
        self.quantity = quantity
        self.price_at_purchase = price_at_purchase
    
    def total_item_price(self):
        return self.quantity * self.price_at_purchase

class MockOrder:
    def __init__(self, email):
        self.id = "ord_test_12345"
        self.ticket_number = "CS-20251218-TEST99"
        self.first_name = "Aegon"
        self.last_name = "Ronaldo"
        self.email = email
        self.phone = "+254712345678"
        self.address = "123 Vintage Lane, Nairobi"
        self.created_at = datetime.utcnow()
        self.discount_code = "TEST99"
        self.discount_amount = 500.00
        
        # Create some items
        prod1 = MockProduct("Vintage Leather Jacket", 4500.00)
        prod2 = MockProduct("Retro Sunglasses", 1200.00)
        
        self.order_items = [
            MockOrderItem(prod1, 1, 4500.00),
            MockOrderItem(prod2, 2, 1200.00)
        ]
        
        # Calculate total
        subtotal = sum(item.total_item_price() for item in self.order_items)
        self.total_price = subtotal - self.discount_amount

def test_send_receipt():
    print("🚀 Initializing Email Service Test...")
    
    # Check API Key
    api_key = os.getenv('RESEND_API_KEY')
    if not api_key:
        print("❌ Error: RESEND_API_KEY not found in .env")
        return

    print(f"✅ Found API Key: {api_key[:5]}...")
    
    service = get_email_service()
    if not service.is_configured():
        print("❌ Error: Email service not configured properly")
        return

    # Create mock order
    recipient = "aegonronaldo@gmail.com"
    print(f"📦 Creating mock order for {recipient}...")
    order = MockOrder(recipient)
    
    print("📧 Sending receipt...")
    try:
        result = service.send_order_confirmation(order)
        print("\n✨ Success! Receipt sent.")
        print(f"📨 Email ID: {result.get('id')}")
        print(f"👤 To: {recipient}")
        print("Check your inbox for the vintage receipt!")
    except Exception as e:
        print(f"\n❌ Failed to send email: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_send_receipt()
