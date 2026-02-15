from app import app
from models import db, Badge

# University mapping (Copy from frontend constants or maintain single source if possible)
# For now, duplicating the map used in updates
UNIVERSITY_SLUGS = {
    "University of Nairobi": "uon",
    "Kenyatta University": "ku",
    "Moi University": "moi",
    "Egerton University": "egerton",
    "Jomo Kenyatta University of Agriculture and Technology": "jkuat",
    "Maseno University": "maseno",
    "Strathmore University": "strathmore",
    "United States International University Africa": "usiu",
    "Mount Kenya University": "mku",
    "Daystar University": "daystar",
    "Catholic University of Eastern Africa": "cuea",
    "Technical University of Kenya": "tuk",
    "Technical University of Mombasa": "tum",
    "Multimedia University of Kenya": "mmu",
    "Kabarak University": "kabarak",
    "Riara University": "riara",
    "KCA University": "kca",
    "Africa Nazarene University": "anu",
    "Zetech University": "zetech",
    "Dedan Kimathi University of Technology": "dkut"
}

def seed_badges():
    with app.app_context():
        print("Starting university badges seed...")
        
        added_count = 0
        updated_count = 0
        
        for name, slug in UNIVERSITY_SLUGS.items():
            badge_name = f"{name} Member"
            image_url = f"https://pub-0a313ba028f9423cba4b9803d081b5db.r2.dev/app%20ui/uni-logos-badges/{slug}-badge.png"
            
            # Check if badge exists
            badge = Badge.query.filter_by(name=badge_name).first()
            
            if badge:
                # Update existing if needed
                needs_update = False
                if badge.image_url != image_url:
                    badge.image_url = image_url
                    needs_update = True
                if badge.badge_type != 'uni':
                    badge.badge_type = 'uni'
                    needs_update = True
                if badge.price_ksh != 0:
                    badge.price_ksh = 0
                    needs_update = True
                    
                if needs_update:
                    print(f"Updated badge for {name}")
                    updated_count += 1
            else:
                # Create new badge with 'uni' type
                new_badge = Badge(
                    name=badge_name,
                    description=f"Official badge for {name} members",
                    image_url=image_url,
                    price_ksh=0,  # Free/Auto-awarded
                    badge_type='uni',  # University badge type
                    is_animated=False,
                    is_active=True
                )
                db.session.add(new_badge)
                print(f"Created badge for {name}")
                added_count += 1
        
        try:
            db.session.commit()
            print(f"Seed completed! Added: {added_count}, Updated: {updated_count}")
        except Exception as e:
            db.session.rollback()
            print(f"Error seeding badges: {e}")

if __name__ == "__main__":
    seed_badges()
