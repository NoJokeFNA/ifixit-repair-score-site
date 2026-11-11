import logging
import os
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

logger = logging.getLogger(__name__)


class _CoordinatedRetry(Retry):
    """Keep urllib3's bounded retries while sharing throttling across workers."""

    def __init__(self, *args, rate_limiter=None, **kwargs):
        self.rate_limiter = rate_limiter
        super().__init__(*args, **kwargs)

    def new(self, **kwargs):
        return super().new(rate_limiter=self.rate_limiter, **kwargs)

    def sleep(self, response=None):
        if self.rate_limiter is not None and response is not None and response.status == 429:
            delay = self.get_retry_after(response) or max(1.0, self.get_backoff_time())
            self.rate_limiter.throttle(delay)
            logger.warning("API throttled; shared cooldown %.1f seconds; budget: %s", delay, self.rate_limiter.stats())
        else:
            super().sleep(response)
        if self.rate_limiter is not None:
            self.rate_limiter.acquire()


class IFixitAPIClient:
    """A Python client for the iFixit API v2.0.

    This client provides methods to interact with all documented endpoints as per
    the iFixit API v2.0 documentation. It handles authentication, pagination,
    error handling, retries, and logging.

    Args:
        auth_token: Optional authentication token for authorized requests.
        app_id: Optional app ID for the X-App-Id header.
        retries: Number of retries for failed requests (default: 3).
        backoff_factor: Backoff factor for retries (default: 0.5).
        timeout: Request timeout in seconds (default: 30).
        log_level: Logging level (default: logging.INFO).
        allow_http: Allow HTTP requests when using a proxy (default: False).
        raise_for_status: Raise exceptions for HTTP error responses (default: True).
        wiki_html = client.get_wiki_page_html('Repairability_Scoring_Rubric_v1.0')

    Usage:
        client = IFixitAPIClient(auth_token='your_token', app_id='your_app_id')
        guides = client.get_guides(limit=10, offset=0)

    Note: Rate limits are not explicitly documented, but the client includes
    retries with backoff. Always check the API documentation for updates:
    https://www.ifixit.com/api/2.0/doc/
    """

    BASE_URL = "https://www.ifixit.com/api/2.0"
    WIKI_BASE_URL = "https://www.ifixit.com/Wiki"
    REPAIRABILITY_URL = "https://www.ifixit.com/repairability"

    def __init__(
        self,
        auth_token: str | None = None,
        app_id: str | None = None,
        retries: int = 3,
        backoff_factor: float = 0.5,
        timeout: int = 30,
        log_level: int = logging.INFO,
        proxy=False,
        allow_http: bool = False,
        raise_for_status: bool = True,
        api_key: str | None = None,
        ca_bundle: str | None = None,
        rate_limiter=None,
    ):
        """Initialize the client.

        Args:
            auth_token: Legacy authentication token (Authorization: api).
            api_key: Personal API key (Authorization: Bearer).
            ca_bundle: Optional PEM CA bundle; TLS verification always stays enabled.
            app_id: Optional app ID for the X-App-Id header.
            retries: Number of retries for failed requests.
            backoff_factor: Backoff factor for retries.
            timeout: Request timeout in seconds.
            log_level: Logging level (e.g., logging.DEBUG).
            allow_http: Allow HTTP requests when using a proxy.
            raise_for_status: Raise exceptions for HTTP error responses.
            proxy: Use proxy settings from environment variables.
            rate_limiter: Optional shared API request budget, including retries.
        """
        if api_key and auth_token:
            raise ValueError("Use api_key or auth_token, not both")
        self.auth_token = api_key or auth_token
        self.auth_scheme = "Bearer" if api_key else "api"
        self.verify = ca_bundle or True
        self.app_id = app_id
        self.timeout = timeout
        self.proxy = proxy
        self.raise_for_status = raise_for_status
        self.rate_limiter = rate_limiter
        logging.basicConfig(level=log_level)

        self.session = requests.Session()
        self.session.trust_env = bool(proxy)
        retry_strategy = _CoordinatedRetry(
            rate_limiter=rate_limiter,
            total=retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy, pool_maxsize=32 if rate_limiter is not None else 10)
        # Mount adapters for retries regardless of proxy usage
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        if self.proxy:
            self.session.proxies = {
                "http": os.getenv("HTTP_PROXY"),
                "https": os.getenv("HTTPS_PROXY"),
            }

    def _build_headers(self) -> dict[str, str]:
        """Build headers for API requests.

        Returns:
            Dict of headers.
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.auth_token:
            headers["Authorization"] = f"{self.auth_scheme} {self.auth_token}"
        if self.app_id:
            headers["X-App-Id"] = self.app_id
        return headers

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        **kwargs,
    ) -> Any:
        """Make an API request.

        Args:
            method: HTTP method (e.g., 'GET', 'POST').
            endpoint: API endpoint path.
            params: Query parameters.
            json: JSON payload for POST/PATCH/PUT.
            **kwargs: Additional requests kwargs.

        Returns:
            JSON response or None.

        Raises:
            requests.exceptions.HTTPError: For HTTP errors.
            requests.exceptions.RequestException: For other request failures.
        """
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        headers = self._build_headers()
        logger.debug("Making %s request to %s", method, url)

        try:
            if self.rate_limiter is not None:
                self.rate_limiter.acquire()
            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json,
                timeout=self.timeout,
                verify=self.verify,
                **kwargs,
            )
            if self.raise_for_status or response.status_code in {401, 403}:
                response.raise_for_status()
            if self.rate_limiter is not None and 200 <= response.status_code < 300:
                self.rate_limiter.on_success()
            return response.json() if response.content else None
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error: %s", e.response.status_code)
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e!s}")
            raise

    def get_wiki_page_html(self, title: str) -> str:
        """Fetch the raw HTML content of a wiki page.

        Args:
            title: Wiki page title (e.g., 'Repairability_Scoring_Rubric_v2.1').

        Returns:
            HTML content as a string.

        Raises:
            requests.exceptions.HTTPError: For HTTP errors.
            requests.exceptions.RequestException: For other request failures.
        """
        url = f"{self.WIKI_BASE_URL}/{title}"
        logger.debug(f"Fetching wiki page HTML from {url}")

        try:
            response = self.session.get(
                url=url,
                timeout=self.timeout,
                verify=self.verify,
            )
            if self.raise_for_status:
                response.raise_for_status()
            return response.text
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error fetching wiki page %s: %s", url, e.response.status_code)
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for wiki page {url}: {e!s}")
            raise

    def get_repairability_page_html(self, old_devices: bool = False) -> str:
        """Fetch the raw HTML content of a wiki page.

        Args:
            old_devices: If true, old devices will be printed.

        Returns:
            HTML content as a string.

        Raises:
            requests.exceptions.HTTPError: For HTTP errors.
            requests.exceptions.RequestException: For other request failures.
        """
        title = "smartphone-repairability-scores" if old_devices else "legacy-smartphone-scores"
        url = f"{self.REPAIRABILITY_URL}/{title}"
        logger.debug(f"Fetching repairability page HTML from {url}")

        try:
            response = self.session.get(
                url=url,
                timeout=self.timeout,
                verify=self.verify,
            )
            if self.raise_for_status:
                response.raise_for_status()
            return response.text
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error fetching repairability page %s: %s", url, e.response.status_code)
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for repairability page {url}: {e!s}")
            raise

    # --- Cart Endpoints ---

    def get_cart_product(self, itemcode: str, langid: str) -> dict:
        """Get a product from the cart.

        Args:
            itemcode: Item code.
            langid: Language ID.

        Returns:
            Product details.
        """
        return self._request("GET", f"/cart/product/{itemcode}/{langid}")

    # --- Authentication Endpoints ---

    def create_user_token(self, data: dict) -> dict:
        """Create a user token.

        Args:
            data: Payload for token creation.

        Returns:
            Token details.
        """
        return self._request("POST", "/user/token", json=data)

    def reset_password(self, data: dict) -> dict:
        """Reset user password.

        Args:
            data: Payload for password reset.

        Returns:
            Response details.
        """
        return self._request("POST", "/users/reset_password", json=data)

    def create_user(self, data: dict) -> dict:
        """Create a new user.

        Args:
            data: User creation payload.

        Returns:
            User details.
        """
        return self._request("POST", "/users", json=data)

    def delete_user_token(self) -> None:
        """Delete the current user token."""
        return self._request("DELETE", "/user/token")

    # --- Badges Endpoints ---

    def get_badges(self) -> list[dict]:
        """Get all badges.

        Returns:
            List of badges.
        """
        return self._request("GET", "/badges")

    def get_badge(self, badgeid: int) -> dict:
        """Get a specific badge.

        Args:
            badgeid: Badge ID.

        Returns:
            Badge details.
        """
        return self._request("GET", f"/badges/{badgeid}")

    # --- Content Hierarchy Endpoints ---

    def get_categories(self) -> list[dict]:
        """Get all categories.

        Returns:
            List of categories.
        """
        return self._request("GET", "/categories")

    # --- Media Endpoints ---

    def get_image(self, imageid: str) -> dict:
        """Get an image.

        Args:
            imageid: Image ID or GUID.

        Returns:
            Image details.
        """
        return self._request("GET", f"/media/images/{imageid}")

    def get_video(self, videoid: str) -> dict:
        """Get a video.

        Args:
            videoid: Video ID or GUID.

        Returns:
            Video details.
        """
        return self._request("GET", f"/media/videos/{videoid}")

    # --- Guides Endpoints ---

    def get_guides(self, params: dict | None = None) -> list[dict]:
        """Get a list of guides.

        Args:
            params: Query parameters for filtering, pagination, etc.

        Returns:
            List of guides.
        """
        return self._request("GET", "/guides", params=params)

    def get_all_guides(self, page_size: int = 100) -> list[dict]:
        """Get all guides by handling pagination.

        Args:
            page_size: Number of results per page.

        Returns:
            List of all guides.
        """
        all_guides: list[dict] = []
        offset = 0
        while True:
            batch = self.get_guides(limit=page_size, offset=offset)
            if not batch:
                break
            all_guides.extend(batch)
            offset += len(batch)
            logger.info("Fetched %d guides, total so far: %d", len(batch), len(all_guides))
            if len(batch) < page_size:
                break
        return all_guides

    def get_guide(self, guideid: int) -> dict:
        """Get a specific guide.

        Args:
            guideid: Guide ID.

        Returns:
            Guide details.
        """
        return self._request("GET", f"/guides/{guideid}")

    def get_guide_tags(self, guideid: int) -> list[str]:
        """Get tags for a guide.

        Args:
            guideid: Guide ID.

        Returns:
            List of tags.
        """
        return self._request("GET", f"/guides/{guideid}/tags")

    def create_guide(self, data: dict) -> dict:
        """Create a new guide.

        Args:
            data: Guide creation payload.

        Returns:
            Created guide details.
        """
        return self._request("POST", "/guides", json=data)

    def update_guide(self, guideid: int, data: dict, revisionid: int | None = None) -> dict:
        """Update a guide.

        Args:
            guideid: Guide ID.
            data: Update payload.
            revisionid: Optional revision ID.

        Returns:
            Updated guide details.
        """
        params = {"revisionid": revisionid} if revisionid else None
        return self._request("PATCH", f"/guides/{guideid}", json=data, params=params)

    def delete_guide(self, guideid: int) -> None:
        """Delete a guide.

        Args:
            guideid: Guide ID.
        """
        return self._request("DELETE", f"/guides/{guideid}")

    def restore_guide(self, guideid: int, langid: str) -> dict:
        """Restore a guide.

        Args:
            guideid: Guide ID.
            langid: Language ID.

        Returns:
            Restored guide details.
        """
        return self._request("POST", f"/guides/{guideid}/{langid}/restore")

    def complete_guide(self, guideid: int) -> dict:
        """Mark a guide as completed.

        Args:
            guideid: Guide ID.

        Returns:
            Response details.
        """
        return self._request("PUT", f"/guides/{guideid}/completed")

    def uncomplete_guide(self, guideid: int) -> None:
        """Unmark a guide as completed.

        Args:
            guideid: Guide ID.
        """
        return self._request("DELETE", f"/guides/{guideid}/completed")

    def make_guide_public(self, guideid: int) -> dict:
        """Make a guide public.

        Args:
            guideid: Guide ID.

        Returns:
            Response details.
        """
        return self._request("PUT", f"/guides/{guideid}/public")

    def make_guide_private(self, guideid: int) -> dict:
        """Make a guide private.

        Args:
            guideid: Guide ID.

        Returns:
            Response details.
        """
        return self._request("DELETE", f"/guides/{guideid}/public")

    def create_guide_step(self, guideid: int, data: dict) -> dict:
        """Create a step in a guide.

        Args:
            guideid: Guide ID.
            data: Step payload.

        Returns:
            Created step details.
        """
        return self._request("POST", f"/guides/{guideid}/steps", json=data)

    def update_guide_step(self, guideid: int, stepid: int, data: dict) -> dict:
        """Update a guide step.

        Args:
            guideid: Guide ID.
            stepid: Step ID.
            data: Update payload.

        Returns:
            Updated step details.
        """
        return self._request("PATCH", f"/guides/{guideid}/steps/{stepid}", json=data)

    def delete_guide_step(self, guideid: int, stepid: int) -> None:
        """Delete a guide step.

        Args:
            guideid: Guide ID.
            stepid: Step ID.
        """
        return self._request("DELETE", f"/guides/{guideid}/steps/{stepid}")

    def update_guide_step_order(self, guideid: int, data: dict) -> dict:
        """Update the order of steps in a guide.

        Args:
            guideid: Guide ID.
            data: Step order payload.

        Returns:
            Response details.
        """
        return self._request("PUT", f"/guides/{guideid}/steporder", json=data)

    def get_guide_users(self, guideid: int) -> list[dict]:
        """Get users associated with a guide.

        Args:
            guideid: Guide ID.

        Returns:
            List of users.
        """
        return self._request("GET", f"/guides/{guideid}/users")

    def add_user_to_guide(self, guideid: int, userid: int) -> dict:
        """Add a user to a guide.

        Args:
            guideid: Guide ID.
            userid: User ID.

        Returns:
            Response details.
        """
        return self._request("PUT", f"/guides/{guideid}/users/{userid}")

    def remove_user_from_guide(self, guideid: int, userid: int) -> None:
        """Remove a user from a guide.

        Args:
            guideid: Guide ID.
            userid: User ID.
        """
        return self._request("DELETE", f"/guides/{guideid}/users/{userid}")

    def get_guide_teams(self, guideid: int) -> list[dict]:
        """Get teams associated with a guide.

        Args:
            guideid: Guide ID.

        Returns:
            List of teams.
        """
        return self._request("GET", f"/guides/{guideid}/teams")

    def add_team_to_guide(self, guideid: int, teamid: int) -> dict:
        """Add a team to a guide.

        Args:
            guideid: Guide ID.
            teamid: Team ID.

        Returns:
            Response details.
        """
        return self._request("PUT", f"/guides/{guideid}/teams/{teamid}")

    def remove_team_from_guide(self, guideid: int, teamid: int) -> None:
        """Remove a team from a guide.

        Args:
            guideid: Guide ID.
            teamid: Team ID.
        """
        return self._request("DELETE", f"/guides/{guideid}/teams/{teamid}")

    def get_guide_releases(self) -> list[dict]:
        """Get all guide releases.

        Returns:
            List of releases.
        """
        return self._request("GET", "/guides/releases")

    def delete_guide_release(self, releaseid: int) -> None:
        """Delete a guide release.

        Args:
            releaseid: Release ID.
        """
        return self._request("DELETE", f"/guides/releases/{releaseid}")

    def get_guide_specific_releases(self, guideid: int) -> list[dict]:
        """Get releases for a specific guide.

        Args:
            guideid: Guide ID.

        Returns:
            List of releases.
        """
        return self._request("GET", f"/guides/{guideid}/releases")

    def create_guide_release(self, data: dict) -> dict:
        """Create a guide release.

        Args:
            data: Release payload.

        Returns:
            Created release details.
        """
        return self._request("POST", "/guides/releases", json=data)

    def update_guide_release(self, releaseid: int, data: dict) -> dict:
        """Update a guide release.

        Args:
            releaseid: Release ID.
            data: Update payload.

        Returns:
            Updated release details.
        """
        return self._request("PATCH", f"/guides/releases/{releaseid}", json=data)

    def add_guide_tag(self, guideid: int, data: dict) -> dict:
        """Add a tag to a guide.

        Args:
            guideid: Guide ID.
            data: Tag payload.

        Returns:
            Response details.
        """
        return self._request("PUT", f"/guides/{guideid}/tag", json=data)

    def remove_guide_tag(self, guideid: int, data: dict) -> None:
        """Remove a tag from a guide.

        Args:
            guideid: Guide ID.
            data: Tag payload.
        """
        return self._request("DELETE", f"/guides/{guideid}/tag", json=data)

    # --- Comments Endpoints ---

    def get_comments(self) -> list[dict]:
        """Get all comments.

        Returns:
            List of comments.
        """
        return self._request("GET", "/comments")

    def get_comment(self, commentid: int) -> dict:
        """Get a specific comment.

        Args:
            commentid: Comment ID.

        Returns:
            Comment details.
        """
        return self._request("GET", f"/comments/{commentid}")

    def create_comment(self, context: str, contextid: int, data: dict) -> dict:
        """Create a comment.

        Args:
            context: Context type (e.g., 'guide').
            contextid: Context ID.
            data: Comment payload.

        Returns:
            Created comment details.
        """
        return self._request("POST", f"/comments/{context}/{contextid}", json=data)

    def update_comment(self, commentid: int, data: dict) -> dict:
        """Update a comment.

        Args:
            commentid: Comment ID.
            data: Update payload.

        Returns:
            Updated comment details.
        """
        return self._request("PATCH", f"/comments/{commentid}", json=data)

    def delete_comment(self, commentid: int) -> None:
        """Delete a comment.

        Args:
            commentid: Comment ID.
        """
        return self._request("DELETE", f"/comments/{commentid}")

    # --- Suggest Endpoints ---

    def suggest(self, query: str, doctypes: str = "all") -> list[dict]:
        """Get suggestions based on a query.

        Args:
            query: Search query.
            doctypes: Document types (default: 'all').

        Returns:
            List of suggestions.
        """
        params = {"doctypes": doctypes}
        return self._request("GET", f"/suggest/{query}", params=params)

    # --- Stories Endpoints ---

    def get_stories(self) -> list[dict]:
        """Get all stories.

        Returns:
            List of stories.
        """
        return self._request("GET", "/stories")

    def get_story(self, storyid: int) -> dict:
        """Get a specific story.

        Args:
            storyid: Story ID.

        Returns:
            Story details.
        """
        return self._request("GET", f"/stories/{storyid}")

    def create_story(self, data: dict) -> dict:
        """Create a story.

        Args:
            data: Story payload.

        Returns:
            Created story details.
        """
        return self._request("POST", "/stories", json=data)

    def update_story(self, storyid: int, data: dict) -> dict:
        """Update a story.

        Args:
            storyid: Story ID.
            data: Update payload.

        Returns:
            Updated story details.
        """
        return self._request("PATCH", f"/stories/{storyid}", json=data)

    # --- Tags Endpoints ---

    def get_tags(self) -> list[dict]:
        """Get all tags.

        Returns:
            List of tags.
        """
        return self._request("GET", "/tags")

    def add_wiki_tag(self, namespace: str, title: str, data: dict) -> dict:
        """Add a tag to a wiki.

        Args:
            namespace: Wiki namespace.
            title: Wiki title.
            data: Tag payload.

        Returns:
            Response details.
        """
        return self._request("PUT", f"/wikis/{namespace}/{title}/tag", json=data)

    def remove_wiki_tag(self, namespace: str, title: str, data: dict) -> None:
        """Remove a tag from a wiki.

        Args:
            namespace: Wiki namespace.
            title: Wiki title.
            data: Tag payload.
        """
        return self._request("DELETE", f"/wikis/{namespace}/{title}/tag", json=data)

    # --- Teams Endpoints ---

    def get_teams(self) -> list[dict]:
        """Get all teams.

        Returns:
            List of teams.
        """
        return self._request("GET", "/teams")

    def get_team_members(self, teamid: int) -> list[dict]:
        """Get members of a team.

        Args:
            teamid: Team ID.

        Returns:
            List of members.
        """
        return self._request("GET", f"/teams/{teamid}")

    def add_user_to_team(self, teamid: int, userid: int) -> dict:
        """Add a user to a team.

        Args:
            teamid: Team ID.
            userid: User ID.

        Returns:
            Response details.
        """
        return self._request("PUT", f"/teams/{teamid}/users/{userid}")

    def remove_user_from_team(self, teamid: int, userid: int) -> None:
        """Remove a user from a team.

        Args:
            teamid: Team ID.
            userid: User ID.
        """
        return self._request("DELETE", f"/teams/{teamid}/users/{userid}")

    # --- Users Endpoints ---

    def get_users(self) -> list[dict]:
        """Get all users.

        Returns:
            List of users.
        """
        return self._request("GET", "/users")

    def search_users(self, search: str) -> list[dict]:
        """Search for users.

        Args:
            search: Search query.

        Returns:
            List of matching users.
        """
        return self._request("GET", f"/users/search/{search}")

    def get_user(self, userid: int) -> dict:
        """Get a specific user.

        Args:
            userid: User ID.

        Returns:
            User details.
        """
        return self._request("GET", f"/users/{userid}")

    def get_user_by_sso(self, sso_userid: str) -> dict:
        """Get a user by SSO ID.

        Args:
            sso_userid: SSO user ID.

        Returns:
            User details.
        """
        return self._request("GET", f"/users/sso/{sso_userid}")

    def get_user_by_email(self, email: str) -> dict:
        """Get a user by email.

        Args:
            email: User email.

        Returns:
            User details.
        """
        return self._request("GET", f"/users/email/{email}")

    def get_user_badges(self, userid: int) -> list[dict]:
        """Get badges for a user.

        Args:
            userid: User ID.

        Returns:
            List of badges.
        """
        return self._request("GET", f"/users/{userid}/badges")

    def get_user_favorite_guides(self, userid: int) -> list[dict]:
        """Get favorite guides for a user.

        Args:
            userid: User ID.

        Returns:
            List of favorite guides.
        """
        return self._request("GET", f"/users/{userid}/favorites/guides")

    def get_user_guides(self, userid: int) -> list[dict]:
        """Get guides for a user.

        Args:
            userid: User ID.

        Returns:
            List of guides.
        """
        return self._request("GET", f"/users/{userid}/guides")

    def get_user_completions(self, userid: int) -> list[dict]:
        """Get completions for a user.

        Args:
            userid: User ID.

        Returns:
            List of completions.
        """
        return self._request("GET", f"/users/{userid}/completions")

    def get_current_user(self) -> dict:
        """Get the current authenticated user.

        Returns:
            User details.
        """
        return self._request("GET", "/user")

    def get_current_user_badges(self) -> list[dict]:
        """Get badges for the current user.

        Returns:
            List of badges.
        """
        return self._request("GET", "/user/badges")

    def get_current_user_favorite_guides(self) -> list[dict]:
        """Get favorite guides for the current user.

        Returns:
            List of favorite guides.
        """
        return self._request("GET", "/user/favorites/guides")

    def favorite_guide(self, guideid: int) -> dict:
        """Favorite a guide for the current user.

        Args:
            guideid: Guide ID.

        Returns:
            Response details.
        """
        return self._request("PUT", f"/user/favorites/guides/{guideid}")

    def unfavorite_guide(self, guideid: int) -> None:
        """Unfavorite a guide for the current user.

        Args:
            guideid: Guide ID.
        """
        return self._request("DELETE", f"/user/favorites/guides/{guideid}")

    def get_current_user_guides(self) -> list[dict]:
        """Get guides for the current user.

        Returns:
            List of guides.
        """
        return self._request("GET", "/user/guides")

    def get_current_user_flags(self) -> list[dict]:
        """Get flags for the current user.

        Returns:
            List of flags.
        """
        return self._request("GET", "/user/flags")

    def get_current_user_completions(self) -> list[dict]:
        """Get completions for the current user.

        Returns:
            List of completions.
        """
        return self._request("GET", "/user/completions")

    def get_current_user_images(self) -> list[dict]:
        """Get images for the current user.

        Returns:
            List of images.
        """
        return self._request("GET", "/user/media/images")

    def upload_user_image(self, data: dict) -> dict:
        """Upload an image for the current user.

        Args:
            data: Image payload (e.g., base64-encoded).

        Returns:
            Uploaded image details.
        """
        return self._request("POST", "/user/media/images", json=data)

    def delete_user_images(self, imageids: str) -> None:
        """Delete images for the current user.

        Args:
            imageids: Comma-separated image IDs.
        """
        return self._request("DELETE", f"/user/media/images/{imageids}")

    def update_user_image(self, imageid: str, data: dict) -> dict:
        """Update a user image.

        Args:
            imageid: Image ID or GUID.
            data: Update payload.

        Returns:
            Updated image details.
        """
        return self._request("POST", f"/user/media/images/{imageid}", json=data)

    def get_current_user_videos(self) -> list[dict]:
        """Get videos for the current user.

        Returns:
            List of videos.
        """
        return self._request("GET", "/user/media/videos")

    def update_user(self, userid: int, data: dict) -> dict:
        """Update a user.

        Args:
            userid: User ID.
            data: Update payload.

        Returns:
            Updated user details.
        """
        return self._request("PATCH", f"/users/{userid}", json=data)

    # --- Wikis Endpoints ---

    def get_category(self, device_name: str | None = None, params: dict | None = None) -> dict:
        """Get the category hierarchy.

        Args:
            device_name: Optional device name to filter the hierarchy.
            params: Optional parameters to customize the response.

        Returns:
            Hierarchy details.
        """
        endpoint = "/wikis/CATEGORY"
        if device_name:
            endpoint += f"/{device_name}"
        if not params:
            params = {"display": "hierarchy"}
        return self._request("GET", endpoint, params=params)

    def get_wikis(self, namespace: str) -> list[dict]:
        """Get wikis in a namespace.

        Args:
            namespace: Wiki namespace.

        Returns:
            List of wikis.
        """
        return self._request("GET", f"/wikis/{namespace}")

    def get_wiki(self, namespace: str, title: str) -> dict:
        """Get a specific wiki.

        Args:
            namespace: Wiki namespace.
            title: Wiki title.

        Returns:
            Wiki details.
        """
        return self._request("GET", f"/wikis/{namespace}/{title}")

    def get_wiki_tags(self, namespace: str, title: str) -> list[str]:
        """Get tags for a wiki.

        Args:
            namespace: Wiki namespace.
            title: Wiki title.

        Returns:
            List of tags.
        """
        return self._request("GET", f"/wikis/{namespace}/{title}/tags")

    def get_category_children(self, title: str) -> list[dict]:
        """Get children of a category.

        Args:
            title: Category title.

        Returns:
            List of children.
        """
        return self._request("GET", f"/wikis/CATEGORY/{title}/children")

    def get_category_identification(self, title: str) -> str:
        """Get identification for a category.

        Args:
            title: Category title.

        Returns:
            Identification string.
        """
        return self._request("GET", f"/wikis/CATEGORY/{title}/identification")

    def get_category_variants(self, title: str) -> dict:
        """Get every regional/model variant; an unnamed entry is not a model code."""
        return self._request("GET", f"/wikis/CATEGORY/{title}/topic_variants")

    def create_wiki(self, data: dict) -> dict:
        """Create a new wiki.

        Args:
            data: Wiki creation payload.

        Returns:
            Created wiki details.
        """
        return self._request("POST", "/wikis", json=data)

    def update_wiki(self, namespace: str, title: str, data: dict, revisionid: int | None = None) -> dict:
        """Update a wiki.

        Args:
            namespace: Wiki namespace.
            title: Wiki title.
            data: Update payload.
            revisionid: Optional revision ID.

        Returns:
            Updated wiki details.
        """
        params = {"revisionid": revisionid} if revisionid else None
        return self._request("PATCH", f"/wikis/{namespace}/{title}", json=data, params=params)

    def delete_wiki(self, namespace: str, title: str) -> None:
        """Delete a wiki.

        Args:
            namespace: Wiki namespace.
            title: Wiki title.
        """
        return self._request("DELETE", f"/wikis/{namespace}/{title}")

    def revert_wiki(self, namespace: str, title: str, data: dict) -> dict:
        """Revert a wiki to a previous state.

        Args:
            namespace: Wiki namespace.
            title: Wiki title.
            data: Revert payload.

        Returns:
            Response details.
        """
        return self._request("POST", f"/wikis/{namespace}/{title}/revert", json=data)

    def set_wiki_parent(self, title: str, data: dict) -> dict:
        """Set the parent for a category wiki.

        Args:
            title: Category title.
            data: Parent payload.

        Returns:
            Response details.
        """
        return self._request("PUT", f"/wikis/CATEGORY/{title}/parent", json=data)

    # --- User View History Endpoints ---

    def get_user_view_history(self, userid: int) -> list[dict]:
        """Get view history for a user.

        Args:
            userid: User ID.

        Returns:
            List of view history entries.
        """
        return self._request("GET", f"/user_view_history/user/{userid}")

    def get_document_view_history(self, doc_type: str, docid: int) -> list[dict]:
        """Get view history for a document.

        Args:
            doc_type: Document type.
            docid: Document ID.

        Returns:
            List of view history entries.
        """
        return self._request("GET", f"/user_view_history/{doc_type}/{docid}")

    # --- Documents Endpoints ---

    def get_document(self, id_or_guid: str) -> dict:
        """Get a document.

        Args:
            id_or_guid: Document ID or GUID.

        Returns:
            Document details.
        """
        return self._request("GET", f"/documents/{id_or_guid}")
