#!/usr/bin/env python3
"""
Test script to verify real-time messaging functionality
"""
import asyncio
import socketio
import json
import time

# Create a SocketIO client
sio = socketio.AsyncClient()

@sio.event
async def connect():
    print("✅ Connected to server")
    
    # Authenticate with a test token (you'll need a real token for actual testing)
    await sio.emit('authenticate', {'token': 'your-jwt-token-here'})

@sio.event
async def authenticated(data):
    print(f"✅ Authenticated: {data}")

@sio.event
async def new_message(data):
    print(f"📨 New message received: {data}")

@sio.event
async def friend_status_change(data):
    print(f"👥 Friend status change: {data}")

@sio.event
async def user_typing(data):
    print(f"✍️  User typing: {data}")

@sio.event
async def disconnect():
    print("❌ Disconnected from server")

async def test_websocket():
    """Test WebSocket connection"""
    try:
        # Connect to the server
        await sio.connect('ws://localhost:5000')
        
        # Wait a bit to see responses
        await asyncio.sleep(2)
        
        # Test sending a message (this would normally go through HTTP API)
        print("📤 Testing message sending...")
        
        # Test typing indicator
        await sio.emit('typing', {
            'recipient_id': 123,
            'is_typing': True
        })
        
        await asyncio.sleep(1)
        
        await sio.emit('typing', {
            'recipient_id': 123,
            'is_typing': False
        })
        
        # Keep connection alive for a few seconds
        await asyncio.sleep(3)
        
        await sio.disconnect()
        
    except Exception as e:
        print(f"❌ Test failed: {e}")

if __name__ == "__main__":
    print("🧪 Testing Real-time Messaging Infrastructure...")
    print("Note: This requires a valid JWT token and running server")
    print("For full testing, use the frontend client or update the token above")
    print()
    
    # Uncomment the line below to run the actual test
    # asyncio.run(test_websocket())
    
    print("✨ Test script ready - update with real token to test WebSocket features")
