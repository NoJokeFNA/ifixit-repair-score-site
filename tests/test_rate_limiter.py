import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

from urllib3.response import HTTPResponse

from fetch_device_data import fetch_teardown_guides
from ifixit_api_client import IFixitAPIClient, _CoordinatedRetry
from rate_limiter import _RateLimiter


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(seconds, 1e-9)


class RateLimiterTests(unittest.TestCase):
    def test_failed_guide_page_cannot_be_treated_as_the_end_of_pagination(self):
        client = Mock()

        def page(params):
            if params["offset"] == 200:
                raise RuntimeError("guide page unavailable")
            return []

        client.get_guides.side_effect = page
        with self.assertRaisesRegex(RuntimeError, "guide page unavailable"):
            fetch_teardown_guides(client)

    def test_request_budget_is_rechecked_under_concurrent_contention(self):
        limiter = _RateLimiter(100)
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=8) as workers:
            list(workers.map(lambda _: limiter.acquire(), range(24)))
        self.assertGreaterEqual(time.perf_counter() - started, 0.22)
        self.assertEqual(limiter.stats()["requests"], 24)
        self.assertGreaterEqual(limiter._tokens, 0)

    def test_shared_cooldown_reduces_rate_and_does_not_accumulate_burst_tokens(self):
        clock = Clock()
        limiter = _RateLimiter(8, clock=clock, sleep=clock.sleep)
        limiter.acquire()
        limiter.throttle(3)
        limiter.acquire()
        self.assertGreaterEqual(clock.now, 3.25)
        self.assertEqual(limiter.stats()["current_rate"], 4)
        self.assertEqual(limiter.stats()["throttles"], 1)
        limiter.acquire()
        self.assertGreaterEqual(clock.now, 3.5)

    def test_successes_recover_gradually_without_exceeding_configured_ceiling(self):
        clock = Clock()
        limiter = _RateLimiter(8, clock=clock, sleep=clock.sleep)
        limiter.throttle(1)
        for _ in range(31):
            limiter.on_success()
        self.assertEqual(limiter.rate, 4)
        limiter.on_success()
        self.assertEqual(limiter.rate, 5)
        for _ in range(320):
            limiter.on_success()
        self.assertEqual(limiter.rate, 8)

    def test_invalid_rates_are_rejected_and_slow_configurations_remain_bounded(self):
        for rate in [0, -1, float("nan"), float("inf")]:
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                _RateLimiter(rate)
        limiter = _RateLimiter(0.5)
        limiter.throttle(1)
        self.assertEqual(limiter.rate, 0.5)

    def test_retry_clone_preserves_the_shared_limiter_and_retry_after(self):
        for header in ["6", formatdate(1006, usegmt=True)]:
            with self.subTest(header=header):
                limiter = Mock()
                retry = _CoordinatedRetry(total=2, rate_limiter=limiter)
                response = HTTPResponse(status=429, headers={"Retry-After": header})
                retry = retry.increment(method="GET", url="https://example.com", response=response)
                self.assertIs(retry.rate_limiter, limiter)
                with patch("urllib3.util.retry.time.time", return_value=1000):
                    retry.sleep(response)
                limiter.throttle.assert_called_once_with(6)
                limiter.acquire.assert_called_once()

    def test_missing_retry_after_uses_exponential_backoff(self):
        limiter = Mock()
        retry = _CoordinatedRetry(total=3, backoff_factor=1, rate_limiter=limiter)
        response = HTTPResponse(status=429)
        for _ in range(3):
            retry = retry.increment(method="GET", url="https://example.com", response=response)
        retry.sleep(response)
        limiter.throttle.assert_called_once_with(4)

    def test_real_http_retry_obeys_the_global_budget_and_cooldown(self):
        attempts = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                attempts.append(self.path)
                body = json.dumps({"wikiid": 123}).encode()
                self.send_response(429 if len(attempts) == 1 else 200)
                self.send_header("Retry-After", "2")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            clock = Clock()
            limiter = _RateLimiter(8, clock=clock, sleep=clock.sleep)
            client = IFixitAPIClient(rate_limiter=limiter, retries=1)
            client.BASE_URL = f"http://127.0.0.1:{server.server_port}"
            self.assertEqual(client.get_wiki("CATEGORY", "Phone"), {"wikiid": 123})
            self.assertEqual(len(attempts), 2)
            self.assertEqual(limiter.stats()["requests"], 2)
            self.assertEqual(limiter.stats()["throttles"], 1)
            self.assertGreaterEqual(clock.now, 2.25)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
