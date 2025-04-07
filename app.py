#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Core application for visit counter service.

Features:
- Redis-backed visit counter
- Health checks
- Structured logging
- Production-ready config

"""

import logging
import os
import time
from flask import Flask, jsonify
import redis
from redis.exceptions import RedisError

# Configure JSON logging for better parsing in production
logging.basicConfig(
    level=logging.INFO,
    format='''{
        "timestamp": "%(asctime)s",
        "service": "visit-counter",
        "level": "%(levelname)s",
        "thread": "%(threadName)s",
        "message": "%(message)s",
        "context": %(custom_data)s
    }''',
    datefmt='%Y-%m-%dT%H:%M:%SZ'
)
logger = logging.getLogger('visit-counter')


# Custom log formatter that adds service context
class ServiceContextFormatter(logging.Formatter):
    def format(self, record):
        record.custom_data = '{}'  # Default empty context
        return super().format(record)


app = Flask(__name__)

# Redis connection pool for better performance
redis_pool = redis.ConnectionPool(
    host=os.getenv('REDIS_HOST', 'redis'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    max_connections=20,
    socket_timeout=1,
    socket_connect_timeout=1,
    health_check_interval=30,
    decode_responses=True
)

# Cache the Redis version for /version endpoint
REDIS_VERSION = None


def get_redis():
    """Thread-safe Redis connection getter with lazy version check"""
    global REDIS_VERSION
    conn = redis.Redis(connection_pool=redis_pool)

    # Check version on first connection
    if REDIS_VERSION is None:
        try:
            REDIS_VERSION = conn.info().get('redis_version', 'unknown')
            logger.info("Connected to Redis", extra={
                'custom_data': f'{{"version": "{REDIS_VERSION}"}}'
            })
        except RedisError:
            logger.warning("Could not fetch Redis version")
            REDIS_VERSION = 'unknown'

    return conn


@app.route('/ping')
def ping():
    """Health check endpoint"""
    start_time = time.perf_counter()

    response = {
        "status": "ok",
        "environment": os.getenv("FLASK_ENV", "development"),
        "redis_connected": False,
        "response_time_ms": 0,
        "version": "1.2.0"  # Remember to bump this on changes!
    }

    # Check Redis connection
    try:
        redis_conn = get_redis()
        redis_conn.ping()
        response['redis_connected'] = True
    except RedisError as e:
        logger.error("Redis ping failed", extra={
            'custom_data': f'{{"error": "{str(e)}"}}'
        })

    response['response_time_ms'] = round((time.perf_counter() - start_time) * 1000, 2)

    return jsonify(response)


@app.route('/count')
def count():
    """Visit counter endpoint with rate limiting awareness"""
    try:
        redis_conn = get_redis()
        visits = redis_conn.incr('counter')

        # Bonus: Track unique visitors if we had client info
        # redis_conn.pfadd('unique_visitors', request.remote_addr)

        logger.info("Visit recorded", extra={
            'custom_data': f'{{"visit_count": {visits}}}'
        })

        return jsonify({
            "status": "ok",
            "visit_count": visits,
            "note": "Try hitting refresh to see the counter increase!",
            "redis_version": REDIS_VERSION
        })

    except RedisError as e:
        logger.error("Redis operation failed", extra={
            'custom_data': f'{{"error": "{str(e)}"}}'
        })
        return jsonify({
            "status": "error",
            "message": "Counter service unavailable",
            "action": "Please try again later",
            "severity": "high"
        }), 503


if __name__ == '__main__':
    # Dev mode only - in prod we use gunicorn
    app.run(host='0.0.0.0', port=5000, debug=False)