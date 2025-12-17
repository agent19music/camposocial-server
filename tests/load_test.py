#!/usr/bin/env python3
"""
Load testing script for the CampoSocial server.

This script simulates multiple concurrent users connecting via WebSocket,
sending messages, and disconnecting to test the multi-session presence system.

Usage:
    python tests/load_test.py --users 100 --duration 60 --url http://localhost:5000

Requirements:
    pip install python-socketio requests
"""

import argparse
import asyncio
import time
import random
import json
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Any
import requests
import socketio

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class TestMetrics:
    """Metrics collected during load test."""
    connections_attempted: int = 0
    connections_successful: int = 0
    connections_failed: int = 0
    messages_sent: int = 0
    messages_received: int = 0
    disconnections: int = 0
    errors: List[str] = None
    start_time: float = 0
    end_time: float = 0
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time
    
    @property
    def success_rate(self) -> float:
        if self.connections_attempted == 0:
            return 0
        return self.connections_successful / self.connections_attempted * 100
    
    def to_dict(self) -> dict:
        return {
            'connections_attempted': self.connections_attempted,
            'connections_successful': self.connections_successful,
            'connections_failed': self.connections_failed,
            'success_rate': f'{self.success_rate:.2f}%',
            'messages_sent': self.messages_sent,
            'messages_received': self.messages_received,
            'disconnections': self.disconnections,
            'duration_seconds': f'{self.duration:.2f}',
            'errors_count': len(self.errors),
            'sample_errors': self.errors[:5] if self.errors else []
        }


class TestUser:
    """Simulates a single user with WebSocket connection."""
    
    def __init__(self, user_id: int, token: str, server_url: str, metrics: TestMetrics):
        self.user_id = user_id
        self.token = token
        self.server_url = server_url
        self.metrics = metrics
        self.sio = socketio.Client(logger=False, engineio_logger=False)
        self.connected = False
        self.messages_received = 0
        
        # Set up event handlers
        self.sio.on('connect', self._on_connect)
        self.sio.on('disconnect', self._on_disconnect)
        self.sio.on('connected', self._on_connected)
        self.sio.on('new_message', self._on_message)
        self.sio.on('error', self._on_error)
    
    def _on_connect(self):
        logger.debug(f'User {self.user_id} socket connected')
    
    def _on_disconnect(self):
        logger.debug(f'User {self.user_id} socket disconnected')
        self.connected = False
        self.metrics.disconnections += 1
    
    def _on_connected(self, data):
        logger.debug(f'User {self.user_id} authenticated: {data}')
        self.connected = True
        self.metrics.connections_successful += 1
    
    def _on_message(self, data):
        self.messages_received += 1
        self.metrics.messages_received += 1
    
    def _on_error(self, data):
        logger.warning(f'User {self.user_id} error: {data}')
        self.metrics.errors.append(f'User {self.user_id}: {data}')
    
    def connect(self):
        """Establish WebSocket connection."""
        self.metrics.connections_attempted += 1
        try:
            self.sio.connect(
                self.server_url,
                auth={'token': self.token},
                transports=['websocket'],
                wait_timeout=10
            )
            return True
        except Exception as e:
            self.metrics.connections_failed += 1
            self.metrics.errors.append(f'Connect error for user {self.user_id}: {str(e)}')
            logger.warning(f'User {self.user_id} failed to connect: {e}')
            return False
    
    def send_heartbeat(self):
        """Send a heartbeat to maintain connection."""
        if self.connected:
            try:
                self.sio.emit('heartbeat', {})
            except Exception as e:
                logger.warning(f'User {self.user_id} heartbeat failed: {e}')
    
    def send_typing(self, recipient_id: int):
        """Send a typing indicator."""
        if self.connected:
            try:
                self.sio.emit('typing', {
                    'recipient_id': str(recipient_id),
                    'is_typing': True
                })
                self.metrics.messages_sent += 1
            except Exception as e:
                logger.warning(f'User {self.user_id} typing failed: {e}')
    
    def disconnect(self):
        """Disconnect from server."""
        try:
            if self.sio.connected:
                self.sio.disconnect()
        except Exception as e:
            logger.warning(f'User {self.user_id} disconnect error: {e}')


class LoadTester:
    """Orchestrates the load test."""
    
    def __init__(self, server_url: str, num_users: int, duration: int, tokens: List[str] = None):
        self.server_url = server_url
        self.num_users = num_users
        self.duration = duration
        self.tokens = tokens or []
        self.metrics = TestMetrics()
        self.users: List[TestUser] = []
    
    def get_or_create_token(self, user_id: int) -> str:
        """Get existing token or create a test user and get token."""
        if user_id < len(self.tokens):
            return self.tokens[user_id]
        
        # For testing, we'd need to either:
        # 1. Use pre-created test users
        # 2. Create users via API
        # 3. Use a test token
        
        # This is a placeholder - in real tests, you'd get actual tokens
        return f'test_token_{user_id}'
    
    def run(self):
        """Run the load test."""
        logger.info(f'Starting load test: {self.num_users} users, {self.duration}s duration')
        logger.info(f'Server URL: {self.server_url}')
        
        self.metrics.start_time = time.time()
        
        # Create and connect users
        logger.info('Connecting users...')
        for i in range(self.num_users):
            token = self.get_or_create_token(i)
            user = TestUser(i, token, self.server_url, self.metrics)
            self.users.append(user)
            
            # Stagger connections slightly
            if user.connect():
                time.sleep(0.05)  # 50ms between connections
            
            if (i + 1) % 10 == 0:
                logger.info(f'Connected {i + 1}/{self.num_users} users')
        
        logger.info(f'All users connected. Running test for {self.duration}s...')
        
        # Run test duration
        test_end = time.time() + self.duration
        heartbeat_interval = 5  # seconds
        last_heartbeat = time.time()
        
        while time.time() < test_end:
            # Send heartbeats
            if time.time() - last_heartbeat >= heartbeat_interval:
                for user in self.users:
                    user.send_heartbeat()
                last_heartbeat = time.time()
                logger.info(f'Sent heartbeats. Active connections: {sum(1 for u in self.users if u.connected)}')
            
            # Randomly send typing indicators
            for user in self.users:
                if user.connected and random.random() < 0.1:  # 10% chance per iteration
                    other_user = random.choice(self.users)
                    if other_user.user_id != user.user_id:
                        user.send_typing(other_user.user_id)
            
            time.sleep(1)
        
        # Disconnect all users
        logger.info('Test complete. Disconnecting users...')
        for user in self.users:
            user.disconnect()
        
        self.metrics.end_time = time.time()
        
        # Print results
        self.print_results()
    
    def print_results(self):
        """Print test results."""
        results = self.metrics.to_dict()
        
        logger.info('\n' + '=' * 60)
        logger.info('LOAD TEST RESULTS')
        logger.info('=' * 60)
        
        for key, value in results.items():
            logger.info(f'{key}: {value}')
        
        logger.info('=' * 60)


def create_test_users(server_url: str, num_users: int) -> List[str]:
    """Create test users and return their tokens."""
    tokens = []
    
    for i in range(num_users):
        username = f'loadtest_user_{i}_{int(time.time())}'
        password = 'testpassword123'
        
        # Try to register user
        try:
            register_response = requests.post(
                f'{server_url}/camposocial/api/register',
                json={
                    'username': username,
                    'password': password,
                    'email': f'{username}@test.com',
                    'first_name': 'Load',
                    'last_name': f'Test{i}'
                },
                timeout=10
            )
            
            if register_response.status_code in [200, 201]:
                # Login to get token
                login_response = requests.post(
                    f'{server_url}/camposocial/api/login',
                    json={
                        'username': username,
                        'password': password
                    },
                    timeout=10
                )
                
                if login_response.status_code == 200:
                    token = login_response.json().get('access_token')
                    if token:
                        tokens.append(token)
                        logger.info(f'Created test user {i + 1}/{num_users}')
                        continue
            
            logger.warning(f'Failed to create test user {i}: {register_response.text}')
            
        except Exception as e:
            logger.warning(f'Error creating test user {i}: {e}')
    
    return tokens


def main():
    parser = argparse.ArgumentParser(description='Load test the CampoSocial server')
    parser.add_argument('--url', default='http://localhost:5000', help='Server URL')
    parser.add_argument('--users', type=int, default=10, help='Number of concurrent users')
    parser.add_argument('--duration', type=int, default=30, help='Test duration in seconds')
    parser.add_argument('--create-users', action='store_true', help='Create test users before running')
    
    args = parser.parse_args()
    
    tokens = []
    if args.create_users:
        logger.info('Creating test users...')
        tokens = create_test_users(args.url, args.users)
        if len(tokens) < args.users:
            logger.warning(f'Only created {len(tokens)} users, continuing with available tokens')
    
    tester = LoadTester(
        server_url=args.url,
        num_users=args.users,
        duration=args.duration,
        tokens=tokens
    )
    
    tester.run()


if __name__ == '__main__':
    main()


