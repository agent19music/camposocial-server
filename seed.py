from app import db, create_app  # Import your app's create_app function
from models import Products, ProductImages, ProductVariation
from datetime import datetime
import random
import cuid

def seed_products():
    # Clear existing data
    ProductImages.query.delete()
    ProductVariation.query.delete()
    Products.query.delete()
    db.session.commit()

    # Bleach-inspired product list
    products_data = [
        {
            "title": "Zanpakuto Sword - Zangetsu",
            "description": "The iconic blade of Ichigo Kurosaki, forged to channel immense power.",
            "contact_info": "555-555-5555",
            "brand": "Soul Society Gear",
            "price": 350.00,
            "category": "Weapons",
            "seller_id": 'cm2k59imj0000audgav51l2dt',
            "total_sales": 150,
            "images": [
                "https://m.media-amazon.com/images/I/61+qJCsx7aL._AC_SX569_.jpg",
                "https://m.media-amazon.com/images/I/71BA-5u2ZDL._AC_SX569_.jpg"
            ],
            "variations": [
                {"name": "Release State", "value": "Shikai", "price": 350.00, "stock": 5},
                {"name": "Release State", "value": "Bankai", "price": 550.00, "stock": 2},
            ]
        },
        {
            "title": "Captain's Haori - Squad 4",
            "description": "The distinguished white Haori worn by captains of the Gotei 13. Squad 4 variant.",
            "contact_info": "777-888-9999",
            "brand": "Soul Society Gear",
            "price": 120.00,
            "category": "Clothing",
            "seller_id": 'cm2k59imj0000audgav51l2dt',
            "total_sales": 50,
            "images": [
                "https://m.media-amazon.com/images/I/51XL6XYiISL._AC_SX569_.jpg",
                "https://m.media-amazon.com/images/I/419m49yRqVL._AC_SX569_.jpg"
            ],
            "variations": [
                {"name": "Size", "value": "Medium", "price": 120.00, "stock": 10},
                {"name": "Size", "value": "Large", "price": 120.00, "stock": 8},
            ]
        },
        {
            "title": "Akatsuki cloak",
            "description": "AKatsuki cloak",
            "contact_info": "444-555-6666",
            "brand": "Obito wink wink",
            "price": 9999.99,
            "category": "CLothing",
            "seller_id": 'cm2k1clfo00000idgdemx8155',
            "total_sales": 3,
            "images": [
                "https://ke.jumia.is/unsafe/fit-in/500x500/filters:fill(white)/product/24/5111612/3.jpg?1177",
                "https://ke.jumia.is/unsafe/fit-in/500x500/filters:fill(white)/product/24/5111612/1.jpg?1177"
            ],
            "variations": [
                {"name": "Condition", "value": "Sealed", "price": 9999.99, "stock": 1},
                {"name": "Condition", "value": "Unsealed", "price": 19999.99, "stock": 1},
            ]
        },
          {
        "title": "Hidden Leaf Village Headband",
        "description": "Show your loyalty to Konoha with this classic headband.",
        "contact_info": "444-555-6666",
        "brand": "Naruto Shippuden",
        "price": 14.99,
        "category": "Accessories",
        "seller_id": "cm2k1clfo00000idgdemx8155",
        "total_sales": 25,
        "images": [
            "https://ke.jumia.is/unsafe/fit-in/500x500/filters:fill(white)/product/81/3367921/1.jpg?7500",
            "https://m.media-amazon.com/images/I/41Car1BwtkL._AC_.jpg"
        ],
        "variations": [
            { "name": "Color", "value": "Blue", "price": 14.99, "stock": 10 },
            { "name": "Color", "value": "Black", "price": 14.99, "stock": 12 }
        ]
    },
    {
        "title": "Uchiha Clan Symbol Necklace",
        "description": "Embrace the Uchiha legacy with this stylish necklace.",
        "contact_info": "444-555-6666",
        "brand": "Naruto Shippuden",
        "price": 29.99,
        "category": "Jewelry",
        "seller_id": "cm2k1clfo00000idgdemx8155",
        "total_sales": 18,
        "images": [
            "https://m.media-amazon.com/images/I/61GLDA3K7JL._AC_UF894,1000_QL80_.jpg",
            "https://m.media-amazon.com/images/I/61K-XjT4sjL._SX625_.jpg"
        ],
        "variations": [
            { "name": "Material", "value": "Silver", "price": 29.99, "stock": 5 },
            { "name": "Material", "value": "Gold", "price": 39.99, "stock": 3 }
        ]
    },
    {
        "title": "Naruto Ramen Bowl Set",
        "description": "Enjoy your ramen like Naruto with this authentic bowl set.",
        "contact_info": "444-555-6666",
        "brand": "Naruto Shippuden",
        "price": 34.99,
        "category": "Kitchenware",
        "seller_id": "cm2k1clfo00000idgdemx8155",
        "total_sales": 30,
        "images": [
            "https://m.media-amazon.com/images/I/61Ku05WD-ZL._AC_SX679_.jpg",
            "https://m.media-amazon.com/images/I/71jGrIBAAYL._AC_SX679_.jpg"
        ],
        "variations": [
            { "name": "Size", "value": "Small", "price": 34.99, "stock": 8 },
            { "name": "Size", "value": "Large", "price": 39.99, "stock": 10 }
        ]
    }
    ]

    for product_data in products_data:
        # Create Product
        product = Products(
            id=cuid.cuid(),
            title=product_data['title'],
            description=product_data['description'],
            contact_info=product_data['contact_info'],
            brand=product_data['brand'],
            price=product_data['price'],
            category=product_data['category'],
            seller_id=product_data['seller_id'],
            total_sales=product_data['total_sales'],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        # Add product images
        for image_url in product_data['images']:
            product_image = ProductImages(image_url=image_url, product=product)
            db.session.add(product_image)

        # Add product variations
        for variation_data in product_data['variations']:
            variation = ProductVariation(
                product=product,
                variation_name=variation_data['name'],
                variation_value=variation_data['value'],
                price=variation_data['price'],
                stock=variation_data['stock'],
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.session.add(variation)

        db.session.add(product)

    # Commit to the database
    db.session.commit()

    print("Database seeded successfully with Bleach-inspired products!")

if __name__ == "__main__":
    app = create_app()
    with app.app_context():  # Ensure we are in an application context
        seed_products()
