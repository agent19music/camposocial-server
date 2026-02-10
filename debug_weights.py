from app import create_app
from models import db, Users, Like
from sqlalchemy import func, case

app, socketio = create_app()

def get_weighted_likes_count(yap_id):
    with app.app_context():
        result = db.session.query(
            func.coalesce(
                func.sum(
                    case(
                        (Users.engagement_multiplier.isnot(None), Users.engagement_multiplier),
                        else_=1.0
                    )
                ),
                0
            )
        ).select_from(Like).join(
            Users, Users.id == Like.user_id
        ).filter(
            Like.yap_id == yap_id
        ).scalar()
        print(f"Yap {yap_id}: weighted_likes_count = {result}")
        return float(result)

def debug():
    with app.app_context():
        # Get user 3
        u3 = Users.query.get(3)
        print(f"User 3: {u3.username}, multiplier: {u3.engagement_multiplier}")
        
        # Get a yap liked by user 3
        like = Like.query.filter_by(user_id=3).first()
        if like:
            print(f"User 3 liked yap: {like.yap_id}")
            # Calculate weight
            get_weighted_likes_count(like.yap_id)
        else:
            print("User 3 has no likes")

if __name__ == "__main__":
    debug()
