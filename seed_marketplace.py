"""
Seed script for marketplace demo data.
Creates example users, sellers, products with images and variations.

Run with: docker exec camposocial-server python seed_marketplace.py
"""

from app import app, db
from models import Users, Seller, Products, ProductImages, ProductVariation
from datetime import datetime
import bcrypt

def hash_password(password):
    """Hash a password for storing."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def seed_marketplace():
    """Seed the database with demo marketplace data"""
    
    with app.app_context():
        print("🌱 Starting marketplace seed...")
        
        # ==================== USERS ====================
        users_data = [
            {
                "username": "bakery_queen",
                "email": "bakeryqueen@demo.com",
                "first_name": "Sarah",
                "last_name": "Kimani",
                "password": hash_password("demo123"),
                "phone_no": "0712345678",
                "avatar": "https://randomuser.me/api/portraits/women/44.jpg",
                "display_name": "Sarah's Bakery",
                "bio": "Award-winning baker specializing in cupcakes and pastries 🧁",
                "category": "food",
                "profile_completed": True
            },
            {
                "username": "sneaker_hub",
                "email": "sneakerhub@demo.com",
                "first_name": "James",
                "last_name": "Ochieng",
                "password": hash_password("demo123"),
                "phone_no": "0723456789",
                "avatar": "https://randomuser.me/api/portraits/men/32.jpg",
                "display_name": "Sneaker Hub KE",
                "bio": "Authentic sneakers at the best prices 👟",
                "category": "fashion",
                "profile_completed": True
            },
            {
                "username": "vintage_vibes",
                "email": "vintagevibes@demo.com",
                "first_name": "Grace",
                "last_name": "Wanjiku",
                "password": hash_password("demo123"),
                "phone_no": "0734567890",
                "avatar": "https://randomuser.me/api/portraits/women/68.jpg",
                "display_name": "Vintage Vibes Thrift",
                "bio": "Curated vintage and retro fashion pieces ✨",
                "category": "fashion",
                "profile_completed": True
            }
        ]
        
        created_users = []
        for user_data in users_data:
            existing = Users.query.filter_by(username=user_data["username"]).first()
            if existing:
                print(f"  ⚠️ User {user_data['username']} already exists, skipping...")
                created_users.append(existing)
                continue
            
            user = Users(**user_data)
            db.session.add(user)
            db.session.flush()  # Get the ID
            created_users.append(user)
            print(f"  ✅ Created user: {user.username} (ID: {user.id})")
        
        db.session.commit()
        
        # ==================== SELLERS ====================
        sellers_data = [
            {
                "user": created_users[0],
                "display_name": "Sarah's Bakery",
                "about": "Home-baked cupcakes, cakes, and pastries made with love. Specializing in custom orders for birthdays, weddings, and special occasions.",
                "avatar": "https://randomuser.me/api/portraits/women/44.jpg",
                "phone_no": "0712345678",
                "is_verified": True
            },
            {
                "user": created_users[1],
                "display_name": "Sneaker Hub KE",
                "about": "Your go-to store for authentic sneakers. We stock Adidas, Nike, Puma, and more. Fast delivery across Kenya.",
                "avatar": "https://randomuser.me/api/portraits/men/32.jpg",
                "phone_no": "0723456789",
                "is_verified": True
            },
            {
                "user": created_users[2],
                "display_name": "Vintage Vibes Thrift",
                "about": "Pre-loved fashion with stories to tell. Quality second-hand clothing, jerseys, and accessories.",
                "avatar": "https://randomuser.me/api/portraits/women/68.jpg",
                "phone_no": "0734567890",
                "is_verified": False
            }
        ]
        
        created_sellers = []
        for seller_data in sellers_data:
            user = seller_data.pop("user")
            existing = Seller.query.filter_by(user_id=user.id).first()
            if existing:
                print(f"  ⚠️ Seller for user {user.username} already exists, skipping...")
                created_sellers.append(existing)
                continue
            
            seller = Seller(user_id=user.id, **seller_data)
            db.session.add(seller)
            db.session.flush()
            created_sellers.append(seller)
            print(f"  ✅ Created seller: {seller.display_name} (ID: {seller.id})")
        
        db.session.commit()
        
        # ==================== PRODUCTS ====================
        products_data = [
            {
                "seller": created_sellers[0],
                "title": "Floral Cupcakes (6 Pack)",
                "description": "Beautiful handcrafted cupcakes with floral buttercream frosting. Perfect for birthdays, baby showers, or just because! Available in vanilla, chocolate, or red velvet.",
                "price": 850.00,
                "category": "Food & Baking",
                "brand": "Sarah's Bakery",
                "contact_info": "0712345678",
                "images": [
                    "https://pub-0a313ba028f9423cba4b9803d081b5db.r2.dev/app%20ui/heroimages/marketplace/floralcupcakes.jpg"
                ],
                "variations": [
                    {"name": "Flavor", "value": "Vanilla", "price": 850.00, "stock": 20},
                    {"name": "Flavor", "value": "Chocolate", "price": 850.00, "stock": 15},
                    {"name": "Flavor", "value": "Red Velvet", "price": 950.00, "stock": 10},
                    {"name": "Pack Size", "value": "6 Pack", "price": 850.00, "stock": 25},
                    {"name": "Pack Size", "value": "12 Pack", "price": 1500.00, "stock": 10}
                ]
            },
            {
                "seller": created_sellers[1],
                "title": "Adidas Samba OG Classic",
                "description": "The iconic Adidas Samba returns! Soft leather upper with suede overlays. Gum rubber outsole for that classic look. True to size.",
                "price": 12500.00,
                "category": "Footwear",
                "brand": "Adidas",
                "contact_info": "0723456789",
                "images": [
                    "https://pub-0a313ba028f9423cba4b9803d081b5db.r2.dev/app%20ui/heroimages/marketplace/adidassamba.jpg"
                ],
                "variations": [
                    {"name": "Size", "value": "UK 7 / EU 40.5", "price": 12500.00, "stock": 3},
                    {"name": "Size", "value": "UK 8 / EU 42", "price": 12500.00, "stock": 5},
                    {"name": "Size", "value": "UK 9 / EU 43", "price": 12500.00, "stock": 4},
                    {"name": "Size", "value": "UK 10 / EU 44", "price": 12500.00, "stock": 2},
                    {"name": "Color", "value": "Black/White", "price": 12500.00, "stock": 8},
                    {"name": "Color", "value": "White/Black", "price": 12500.00, "stock": 6}
                ]
            },
            {
                "seller": created_sellers[2],
                "title": "Manchester United 2007 Home Kit (Thrift)",
                "description": "Vintage Manchester United 2007/08 home jersey. The iconic AIG sponsor era. Good condition with minor signs of wear. A collector's dream!",
                "price": 3500.00,
                "category": "Thrift & Vintage",
                "brand": "Nike",
                "contact_info": "0734567890",
                "images": [
                    "https://pub-0a313ba028f9423cba4b9803d081b5db.r2.dev/app%20ui/heroimages/marketplace/manutd2007homekitthrift.jpg"
                ],
                "variations": [
                    {"name": "Size", "value": "Medium", "price": 3500.00, "stock": 1},
                    {"name": "Size", "value": "Large", "price": 3500.00, "stock": 2},
                    {"name": "Condition", "value": "Good", "price": 3500.00, "stock": 2},
                    {"name": "Condition", "value": "Excellent", "price": 4500.00, "stock": 1}
                ]
            },
            {
                "seller": created_sellers[2],
                "title": "Sade Vintage Concert Tee (Thrift)",
                "description": "Rare Sade vintage concert t-shirt. Soft cotton, slightly faded for that authentic vintage feel. A piece of music history!",
                "price": 2800.00,
                "category": "Thrift & Vintage",
                "brand": "Vintage",
                "contact_info": "0734567890",
                "images": [
                    "https://pub-0a313ba028f9423cba4b9803d081b5db.r2.dev/app%20ui/heroimages/marketplace/sadeshirtthrift.jpg"
                ],
                "variations": [
                    {"name": "Size", "value": "Small", "price": 2800.00, "stock": 1},
                    {"name": "Size", "value": "Medium", "price": 2800.00, "stock": 2},
                    {"name": "Size", "value": "Large", "price": 2800.00, "stock": 1}
                ]
            }
        ]
        
        for product_data in products_data:
            seller = product_data.pop("seller")
            images_urls = product_data.pop("images")
            variations_data = product_data.pop("variations")
            
            # Check if product already exists
            existing = Products.query.filter_by(
                title=product_data["title"],
                seller_id=seller.id
            ).first()
            
            if existing:
                print(f"  ⚠️ Product '{product_data['title']}' already exists, skipping...")
                continue
            
            # Create product with slug
            product = Products(
                seller_id=seller.id, 
                slug=Products.generate_slug(product_data["title"]),
                **product_data
            )
            db.session.add(product)
            db.session.flush()  # Get the ID
            
            # Add images
            for img_url in images_urls:
                image = ProductImages(product_id=product.id, image_url=img_url)
                db.session.add(image)
            
            # Add variations
            for var_data in variations_data:
                variation = ProductVariation(
                    product_id=product.id,
                    variation_name=var_data["name"],
                    variation_value=var_data["value"],
                    price=var_data["price"],
                    stock=var_data["stock"]
                )
                db.session.add(variation)
            
            print(f"  ✅ Created product: {product.title}")
            print(f"      - Slug: {product.slug}")
            print(f"      - {len(images_urls)} images")
            print(f"      - {len(variations_data)} variations")
        
        db.session.commit()
        
        # ==================== SUMMARY ====================
        print("\n" + "="*50)
        print("🎉 Marketplace seed completed!")
        print("="*50)
        print(f"  Users created: {len(created_users)}")
        print(f"  Sellers created: {len(created_sellers)}")
        print(f"  Products created: {len(products_data)}")
        print("\n📝 Demo accounts:")
        print("  Email: bakeryqueen@demo.com | Password: demo123")
        print("  Email: sneakerhub@demo.com | Password: demo123")
        print("  Email: vintagevibes@demo.com | Password: demo123")
        print("="*50)


if __name__ == "__main__":
    seed_marketplace()
