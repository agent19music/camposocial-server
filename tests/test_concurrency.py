"""
Concurrency and load tests for multi-session support.

These tests verify that:
1. Multiple sockets per user work correctly
2. User only goes offline when ALL sockets disconnect
3. Events reach all of a user's active sockets
4. System handles rapid connect/disconnect cycles

Run with: pytest tests/test_concurrency.py -v
"""

import pytest
import time
import threading
from unittest.mock import MagicMock, patch
from datetime import datetime


class MockRedis:
    """Mock Redis client for testing without actual Redis."""
    
    def __init__(self):
        self._data = {}
        self._sets = {}
        self._hashes = {}
        self._expiry = {}
    
    def pipeline(self):
        return MockPipeline(self)
    
    def sadd(self, key, *values):
        if key not in self._sets:
            self._sets[key] = set()
        for v in values:
            self._sets[key].add(v)
        return len(values)
    
    def srem(self, key, *values):
        if key not in self._sets:
            return 0
        removed = 0
        for v in values:
            if v in self._sets[key]:
                self._sets[key].remove(v)
                removed += 1
        return removed
    
    def scard(self, key):
        return len(self._sets.get(key, set()))
    
    def smembers(self, key):
        return self._sets.get(key, set()).copy()
    
    def sismember(self, key, value):
        return value in self._sets.get(key, set())
    
    def get(self, key):
        return self._data.get(key)
    
    def set(self, key, value, ex=None):
        self._data[key] = value
        if ex:
            self._expiry[key] = time.time() + ex
        return True
    
    def delete(self, *keys):
        deleted = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                deleted += 1
            if key in self._sets:
                del self._sets[key]
                deleted += 1
            if key in self._hashes:
                del self._hashes[key]
                deleted += 1
        return deleted
    
    def hset(self, key, *args, mapping=None):
        if key not in self._hashes:
            self._hashes[key] = {}
        if mapping:
            self._hashes[key].update(mapping)
        elif len(args) == 2:
            self._hashes[key][args[0]] = args[1]
        return 1
    
    def hgetall(self, key):
        return self._hashes.get(key, {})
    
    def expire(self, key, seconds):
        self._expiry[key] = time.time() + seconds
        return True
    
    def exists(self, key):
        return key in self._data or key in self._sets or key in self._hashes
    
    def incr(self, key):
        val = int(self._data.get(key, 0)) + 1
        self._data[key] = str(val)
        return val
    
    def keys(self, pattern):
        # Simple pattern matching for testing
        import fnmatch
        all_keys = list(self._data.keys()) + list(self._sets.keys()) + list(self._hashes.keys())
        return [k for k in all_keys if fnmatch.fnmatch(k, pattern)]


class MockPipeline:
    """Mock Redis pipeline for batched operations."""
    
    def __init__(self, redis):
        self.redis = redis
        self._ops = []
    
    def sadd(self, key, *values):
        self._ops.append(('sadd', key, values))
        return self
    
    def srem(self, key, *values):
        self._ops.append(('srem', key, values))
        return self
    
    def set(self, key, value, ex=None):
        self._ops.append(('set', key, value, ex))
        return self
    
    def delete(self, *keys):
        self._ops.append(('delete', keys))
        return self
    
    def hset(self, key, *args, mapping=None):
        self._ops.append(('hset', key, mapping or dict(zip(args[::2], args[1::2]))))
        return self
    
    def expire(self, key, seconds):
        self._ops.append(('expire', key, seconds))
        return self
    
    def execute(self):
        results = []
        for op in self._ops:
            if op[0] == 'sadd':
                results.append(self.redis.sadd(op[1], *op[2]))
            elif op[0] == 'srem':
                results.append(self.redis.srem(op[1], *op[2]))
            elif op[0] == 'set':
                results.append(self.redis.set(op[1], op[2], ex=op[3] if len(op) > 3 else None))
            elif op[0] == 'delete':
                results.append(self.redis.delete(*op[1]))
            elif op[0] == 'hset':
                results.append(self.redis.hset(op[1], mapping=op[2]))
            elif op[0] == 'expire':
                results.append(self.redis.expire(op[1], op[2]))
        self._ops = []
        return results


class TestPresenceManager:
    """Tests for the PresenceManager class."""
    
    @pytest.fixture
    def mock_redis(self):
        return MockRedis()
    
    @pytest.fixture
    def presence_manager(self, mock_redis):
        from presence import PresenceManager
        pm = PresenceManager(redis_client=mock_redis)
        return pm
    
    def test_register_first_socket_returns_was_offline_true(self, presence_manager):
        """First socket connection should indicate user was offline."""
        was_offline = presence_manager.register_socket(user_id=1, socket_id='socket_1')
        assert was_offline is True
    
    def test_register_second_socket_returns_was_offline_false(self, presence_manager):
        """Second socket connection should indicate user was already online."""
        presence_manager.register_socket(user_id=1, socket_id='socket_1')
        was_offline = presence_manager.register_socket(user_id=1, socket_id='socket_2')
        assert was_offline is False
    
    def test_user_online_with_any_socket(self, presence_manager):
        """User should be online if they have any active sockets."""
        presence_manager.register_socket(user_id=1, socket_id='socket_1')
        assert presence_manager.is_user_online(1) is True
    
    def test_user_offline_with_no_sockets(self, presence_manager):
        """User should be offline if they have no active sockets."""
        assert presence_manager.is_user_online(1) is False
    
    def test_unregister_socket_preserves_other_sockets(self, presence_manager):
        """Unregistering one socket should not affect others."""
        presence_manager.register_socket(user_id=1, socket_id='socket_1')
        presence_manager.register_socket(user_id=1, socket_id='socket_2')
        
        user_id, went_offline = presence_manager.unregister_socket('socket_1')
        
        assert user_id == 1
        assert went_offline is False
        assert presence_manager.is_user_online(1) is True
        assert presence_manager.get_socket_count(1) == 1
    
    def test_unregister_last_socket_marks_offline(self, presence_manager):
        """Unregistering the last socket should mark user offline."""
        presence_manager.register_socket(user_id=1, socket_id='socket_1')
        
        user_id, went_offline = presence_manager.unregister_socket('socket_1')
        
        assert user_id == 1
        assert went_offline is True
        assert presence_manager.is_user_online(1) is False
    
    def test_socket_count_accurate(self, presence_manager):
        """Socket count should accurately reflect active connections."""
        assert presence_manager.get_socket_count(1) == 0
        
        presence_manager.register_socket(user_id=1, socket_id='socket_1')
        assert presence_manager.get_socket_count(1) == 1
        
        presence_manager.register_socket(user_id=1, socket_id='socket_2')
        assert presence_manager.get_socket_count(1) == 2
        
        presence_manager.register_socket(user_id=1, socket_id='socket_3')
        assert presence_manager.get_socket_count(1) == 3
        
        presence_manager.unregister_socket('socket_2')
        assert presence_manager.get_socket_count(1) == 2
    
    def test_multiple_users_independent(self, presence_manager):
        """Different users should have independent presence tracking."""
        presence_manager.register_socket(user_id=1, socket_id='socket_1a')
        presence_manager.register_socket(user_id=1, socket_id='socket_1b')
        presence_manager.register_socket(user_id=2, socket_id='socket_2a')
        
        assert presence_manager.get_socket_count(1) == 2
        assert presence_manager.get_socket_count(2) == 1
        
        presence_manager.unregister_socket('socket_1a')
        
        assert presence_manager.is_user_online(1) is True
        assert presence_manager.is_user_online(2) is True
        
        presence_manager.unregister_socket('socket_2a')
        
        assert presence_manager.is_user_online(1) is True
        assert presence_manager.is_user_online(2) is False
    
    def test_get_online_users(self, presence_manager):
        """Should return set of all online user IDs."""
        presence_manager.register_socket(user_id=1, socket_id='socket_1')
        presence_manager.register_socket(user_id=2, socket_id='socket_2')
        presence_manager.register_socket(user_id=3, socket_id='socket_3')
        
        online = presence_manager.get_online_users()
        
        assert 1 in online
        assert 2 in online
        assert 3 in online
        
        presence_manager.unregister_socket('socket_2')
        
        online = presence_manager.get_online_users()
        assert 1 in online
        assert 2 not in online
        assert 3 in online
    
    def test_rate_limiting(self, presence_manager):
        """Rate limiting should restrict excessive requests."""
        user_id = 1
        action = 'typing'
        max_requests = 5
        
        # First max_requests should pass
        for i in range(max_requests):
            assert presence_manager.check_rate_limit(user_id, action, max_requests) is True
        
        # Next request should be blocked
        assert presence_manager.check_rate_limit(user_id, action, max_requests) is False
    
    def test_concurrent_socket_registration(self, presence_manager):
        """Concurrent socket registrations should be handled safely."""
        results = []
        
        def register_socket(socket_id):
            was_offline = presence_manager.register_socket(user_id=1, socket_id=socket_id)
            results.append((socket_id, was_offline))
        
        threads = []
        for i in range(10):
            t = threading.Thread(target=register_socket, args=(f'socket_{i}',))
            threads.append(t)
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        # Only one socket should report was_offline=True
        offline_true_count = sum(1 for _, was_offline in results if was_offline)
        assert offline_true_count == 1
        
        # All 10 sockets should be registered
        assert presence_manager.get_socket_count(1) == 10


class TestConcurrentDisconnects:
    """Tests for handling concurrent disconnect events."""
    
    @pytest.fixture
    def mock_redis(self):
        return MockRedis()
    
    @pytest.fixture
    def presence_manager(self, mock_redis):
        from presence import PresenceManager
        pm = PresenceManager(redis_client=mock_redis)
        return pm
    
    def test_rapid_connect_disconnect_cycle(self, presence_manager):
        """Rapid connect/disconnect should not corrupt state."""
        for cycle in range(100):
            presence_manager.register_socket(user_id=1, socket_id=f'socket_{cycle}')
            presence_manager.unregister_socket(f'socket_{cycle}')
        
        # After all cycles, user should be offline
        assert presence_manager.is_user_online(1) is False
        assert presence_manager.get_socket_count(1) == 0
    
    def test_interleaved_connect_disconnect(self, presence_manager):
        """Interleaved connects and disconnects should maintain consistency."""
        # Connect 5 sockets
        for i in range(5):
            presence_manager.register_socket(user_id=1, socket_id=f'socket_{i}')
        
        # Disconnect odd sockets
        for i in range(1, 5, 2):
            presence_manager.unregister_socket(f'socket_{i}')
        
        # Should have 3 sockets left (0, 2, 4)
        assert presence_manager.get_socket_count(1) == 3
        assert presence_manager.is_user_online(1) is True
        
        # Disconnect remaining sockets
        for i in range(0, 5, 2):
            presence_manager.unregister_socket(f'socket_{i}')
        
        assert presence_manager.get_socket_count(1) == 0
        assert presence_manager.is_user_online(1) is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


