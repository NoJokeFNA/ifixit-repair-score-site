import unittest
from unittest.mock import Mock

import requests

from ifixit_api_client import IFixitAPIClient


class APIAuthenticationTests(unittest.TestCase):
    def test_key_is_bearer_and_proxy_does_not_disable_tls(self):
        client = IFixitAPIClient(api_key="example", proxy=True, ca_bundle="custom.pem")
        client.session.request = Mock(return_value=Mock(content=b"{}", json=Mock(return_value={})))
        client.get_guides(params={"limit": 1})
        options = client.session.request.call_args.kwargs
        self.assertEqual(options["headers"]["Authorization"], "Bearer example")
        self.assertEqual(options["verify"], "custom.pem")

    def test_proxy_is_opt_in_and_legacy_auth_remains_supported(self):
        client = IFixitAPIClient(auth_token="legacy")
        self.assertFalse(client.session.trust_env)
        self.assertIs(client.verify, True)
        self.assertEqual(client._build_headers()["Authorization"], "api legacy")

    def test_auth_errors_raise_even_when_other_http_errors_are_tolerated(self):
        client = IFixitAPIClient(raise_for_status=False)
        for status in (401, 403):
            response = Mock(status_code=status)
            response.raise_for_status.side_effect = requests.HTTPError(response=response)
            client.session.request = Mock(return_value=response)
            with self.subTest(status=status), self.assertRaises(requests.HTTPError):
                client.get_guides(params={"limit": 1})
            response.json.assert_not_called()

    def test_html_scraping_does_not_receive_api_key(self):
        client = IFixitAPIClient(api_key="example")
        client.session.get = Mock(return_value=Mock(text="<html />"))
        client.get_wiki_page_html("Repairability_Scoring_Rubric_v2.4")
        self.assertNotIn("headers", client.session.get.call_args.kwargs)
        self.assertIs(client.session.get.call_args.kwargs["verify"], True)

    def test_html_errors_log_status_and_url_without_response_body(self):
        for method, args in [("get_wiki_page_html", ("Missing_rubric",)), ("get_repairability_page_html", ())]:
            with self.subTest(method=method):
                client = IFixitAPIClient()
                response = requests.Response()
                response.status_code = 404
                response._content = b"<html><style>UNNECESSARY_CSS</style>Error page</html>"
                response.raise_for_status = Mock(side_effect=requests.HTTPError(response=response))
                client.session.get = Mock(return_value=response)
                with self.assertLogs("ifixit_api_client", level="ERROR") as logs, self.assertRaises(requests.HTTPError):
                    getattr(client, method)(*args)
                message = "\n".join(logs.output)
                self.assertIn("404", message)
                self.assertIn("https://www.ifixit.com/", message)
                self.assertNotIn("UNNECESSARY_CSS", message)
                self.assertNotIn("<html>", message)
