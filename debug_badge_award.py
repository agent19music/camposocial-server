from app import app
from models import db, Users, Badge, UserBadge
from sqlalchemy import func

def debug_check():
    with app.app_context():
        print("--- DEBUGGING BADGE AWARDING LOGIC ---")
        
        # 1. Check if Badges exist
        uni_name = "University of Nairobi"
        badge_name = f"{uni_name} Member"
        print(f"Target Badge Name: '{badge_name}'")
        
        badge = Badge.query.filter(func.lower(Badge.name) == badge_name.lower()).first()
        
        if badge:
            print(f"✅ SUCCESS: Badge found in DB!")
            print(f"   ID: {badge.id}")
            print(f"   Name: '{badge.name}'")
            print(f"   Price: {badge.price_ksh}")
        else:
            print(f"❌ FAILURE: Badge NOT found in DB.")
            
            # List some badges to see what's there
            print("   Listing first 5 badges in DB:")
            all_badges = Badge.query.limit(5).all()
            for b in all_badges:
                print(f"   - '{b.name}'")
                
        # 2. Simulate User Logic
        print("\n--- SIMULATING USER LOGIC ---")
        # Create a ephemeral user object (not added to session)
        class MockUser:
            id = 99999
            university = uni_name
            
        user = MockUser()
        print(f"User University: '{user.university}'")
        
        derived_badge_name = f"{user.university} Member"
        print(f"Derived Badge Name: '{derived_badge_name}'")
        
        if user.university:
             found_badge = Badge.query.filter(func.lower(Badge.name) == derived_badge_name.lower()).first()
             if found_badge:
                 print(f"✅ SUCCESS: Logic found badge '{found_badge.name}' for user university '{user.university}'")
             else:
                 print(f"❌ FAILURE: Logic did NOT find badge for '{user.university}'")

if __name__ == "__main__":
    debug_check()
