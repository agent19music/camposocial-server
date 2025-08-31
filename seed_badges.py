from app import create_app
from models import db, Badge

def seed_badges():
    """Add default badges to the database"""
    app, socketio = create_app()
    
    with app.app_context():
        # Check if badges already exist
        existing_badges = Badge.query.count()
        if existing_badges > 0:
            print(f"Badges already exist ({existing_badges} found). Skipping seed.")
            return
        
        # Define default badges
        default_badges = [
            {
                'name': 'Gold Verified',
                'description': 'Premium gold verification badge for distinguished users',
                'image_url': 'https://pub-c6a134c8e1fd4881a475bf80bc0717ba.r2.dev/twitter-verified-badge-gold-seeklogo.png',
                'price_ksh': 50,
                'is_animated': False
            },
            {
                'name': 'Hello Kitty Premium',
                'description': 'Cute animated Hello Kitty badge for kawaii lovers',
                'image_url': 'https://pure-essence.net/wp-content/uploads/2013/02/cutehellokittyanimation.gif',
                'price_ksh': 100,
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
