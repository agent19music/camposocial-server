from app import create_app
from models import db, Badge

def seed_badges():
    """Add default badges to the database"""
    app, socketio = create_app()
    
    with app.app_context():
        # Empty the badges table to avoid replications
        deleted_count = Badge.query.delete()
        db.session.commit()
        print(f"Cleared badges table (deleted {deleted_count} records).")
        
        # Define default badges
        default_badges = [
            {
                'name': 'Pink Butterflies',
                'description': 'Pink butterflies animated badge',
                'image_url': 'https://pub-c6a134c8e1fd4881a475bf80bc0717ba.r2.dev/Oxh7.gif',
                'price_ksh': 99,
                'is_animated': True
            },
            {
                'name': 'Adventure Time BMO',
                'description': 'Adventure Time BMO animated badge',
                'image_url': 'https://pub-c6a134c8e1fd4881a475bf80bc0717ba.r2.dev/adventuretimebmo.gif',
                'price_ksh': 29,
                'is_animated': True
            },
            {
                'name': 'Cat Butterfly',
                'description': 'Cat butterfly animated badge',
                'image_url': 'https://pub-c6a134c8e1fd4881a475bf80bc0717ba.r2.dev/catbutterfly.gif',
                'price_ksh': 49,
                'is_animated': True
            },
            {
                'name': 'Flying Money Stack',
                'description': 'Animated flying money stack badge',
                'image_url': 'https://pub-c6a134c8e1fd4881a475bf80bc0717ba.r2.dev/flyingmoneystack.gif',
                'price_ksh': 999,
                'is_animated': True
            },
            {
                'name': 'Blue Check',
                'description': 'Blue verification checkmark',
                'image_url': 'https://pub-c6a134c8e1fd4881a475bf80bc0717ba.r2.dev/bluecheckmark.svg',
                'price_ksh': 9,
                'is_animated': False
            },
            {
                'name': 'Gold Verified',
                'description': 'Premium gold verification badge for distinguished users',
                'image_url': 'https://pub-c6a134c8e1fd4881a475bf80bc0717ba.r2.dev/twitter-verified-badge-gold-seeklogo.png',
                'price_ksh': 9,
                'is_animated': False
            },
            {
                'name': 'Hello Kitty Premium',
                'description': 'Cute animated Hello Kitty badge for kawaii lovers',
                'image_url': 'https://pure-essence.net/wp-content/uploads/2013/02/cutehellokittyanimation.gif',
                'price_ksh': 99,
                'is_animated': True
            }
        ]
        
        # Add badges to database
        for badge_data in default_badges:
            badge = Badge(**badge_data)
            db.session.add(badge)
        
        db.session.commit()
        print(f"Successfully added {len(default_badges)} badges to the database!")
        
        # Display added badges
        for badge in Badge.query.all():
            print(f"- {badge.name}: {badge.price_ksh} KSH")

if __name__ == '__main__':
    seed_badges()
