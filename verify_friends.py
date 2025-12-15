import requests
import sys
import os
from app import create_app
from models import db, Users, Conversation, Friendship
from flask_jwt_extended import create_access_token

# Initialize Flask app context
app, _ = create_app()
app.app_context().push()

BASE_URL = "http://localhost:5001/camposocial/api"

def get_or_create_user(username, email):
    user = Users.query.filter_by(username=username).first()
    if not user:
        print(f"Creating user {username}...")
        user = Users(
            username=username,
            email=email,
            first_name=username,
            last_name="Test",
            password="password123", # This might be hashed in model, but for now just setting it
            profile_completed=True
        )
        db.session.add(user)
        db.session.commit()
    
    # Generate token
    token = create_access_token(identity=str(user.id))
    return user, token

def send_friend_request(token, user_id):
    url = f"{BASE_URL}/friends/request"
    headers = {"Authorization": f"Bearer {token}"}
    data = {"user_id": user_id}
    response = requests.post(url, json=data, headers=headers)
    return response

def accept_friend_request(token, request_id):
    url = f"{BASE_URL}/friends/request/{request_id}/accept"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(url, headers=headers)
    return response

def get_pending_requests(token):
    url = f"{BASE_URL}/friends/pending"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    return response.json()

def check_conversation(token, friend_id):
    url = f"{BASE_URL}/conversation-exists/{friend_id}"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    return response.json()

def main():
    print("Setting up users...")
    user1, token1 = get_or_create_user("user1_test", "user1_test@test.com")
    user2, token2 = get_or_create_user("user2_test", "user2_test@test.com")

    id1 = user1.id
    id2 = user2.id

    print(f"User 1 ID: {id1}")
    print(f"User 2 ID: {id2}")

    # Clean up existing friendship if any
    existing_friendship = Friendship.query.filter(
        ((Friendship.requester_id == id1) & (Friendship.addressee_id == id2)) |
        ((Friendship.requester_id == id2) & (Friendship.addressee_id == id1))
    ).first()
    
    if existing_friendship:
        print("Cleaning up existing friendship...")
        db.session.delete(existing_friendship)
        db.session.commit()

    # 1. Send Friend Request
    print("\n1. User 1 sending friend request to User 2...")
    resp = send_friend_request(token1, id2)
    if resp.status_code == 201:
        print("Request sent successfully")
    elif resp.status_code == 400 and "already sent" in resp.text:
        print("Request already sent (unexpected after cleanup)")
    else:
        print(f"Failed to send request: {resp.text}")

    # 2. Check Pending Requests
    print("\n2. User 2 checking pending requests...")
    pending = get_pending_requests(token2)
    request_id = None
    for req in pending.get('received', []):
        if req['user']['id'] == id1:
            request_id = req['id']
            break
    
    if request_id:
        print(f"Found pending request ID: {request_id}")
    else:
        print("No pending request found from User 1")

    # 3. Accept Friend Request (if pending)
    if request_id:
        print(f"\n3. User 2 accepting request {request_id}...")
        resp = accept_friend_request(token2, request_id)
        if resp.status_code == 200:
            print("Request accepted successfully")
        else:
            print(f"Failed to accept request: {resp.text}")

    # 4. Verify Conversation Creation
    print("\n4. Verifying conversation existence...")
    # Check from User 1 perspective
    conv1 = check_conversation(token1, id2)
    print(f"User 1 conversation check: {conv1}")
    
    # Check from User 2 perspective
    conv2 = check_conversation(token2, id1)
    print(f"User 2 conversation check: {conv2}")

    # 5. Checking Friends list for conversation ID
    print("\n5. Checking Friends list for conversation ID...")
    def get_friend_conv_id(token, friend_id):
        resp = requests.get(f"{BASE_URL}/friends", headers={"Authorization": f"Bearer {token}"})
        friends = resp.json().get('friends', [])
        for f in friends:
            if f['id'] == friend_id:
                return f.get('conversation_id')
        return None

    cid1 = get_friend_conv_id(token1, id2)
    cid2 = get_friend_conv_id(token2, id1)

    print(f"User 1 sees conversation ID: {cid1}")
    print(f"User 2 sees conversation ID: {cid2}")

    if cid1 and cid2 and cid1 == cid2:
        print("\nSUCCESS: Conversation created and synced!")
    else:
        print("\nFAILURE: Conversation ID missing or mismatch.")

if __name__ == "__main__":
    main()
