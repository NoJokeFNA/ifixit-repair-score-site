import logging
import os
from typing import Any, Dict, List, Optional

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3 import Retry

logger = logging.getLogger(__name__)


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

    Usage:
        client = IFixitAPIClient(auth_token='your_token', app_id='your_app_id')
        guides = client.get_guides(limit=10, offset=0)

    Note: Rate limits are not explicitly documented, but the client includes
    retries with backoff. Always check the API documentation for updates:
    https://www.ifixit.com/api/2.0/doc/
    """

    BASE_URL = 'https://www.ifixit.com/api/2.0'

    def __init__(
            self,
            auth_token: Optional[str] = None,
            app_id: Optional[str] = None,
            retries: int = 3,
            backoff_factor: float = 0.5,
            timeout: int = 30,
            log_level: int = logging.INFO,
            proxy=False,
            allow_http: bool = False,
            raise_for_status: bool = True,
    ):
        """Initialize the client.

        Args:
            auth_token: Authentication token for authorized requests.
            app_id: Optional app ID for the X-App-Id header.
            retries: Number of retries for failed requests.
            backoff_factor: Backoff factor for retries.
            timeout: Request timeout in seconds.
            log_level: Logging level (e.g., logging.DEBUG).
            allow_http: Allow HTTP requests when using a proxy.
            raise_for_status: Raise exceptions for HTTP error responses.
            proxy: Use proxy settings from environment variables.
        """
        self.auth_token = auth_token
        self.app_id = app_id
        self.timeout = timeout
        self.proxy = proxy
        self.raise_for_status = raise_for_status
        logging.basicConfig(level=log_level)

        self.session = requests.Session()
        retry_strategy = Retry(
            total=retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=['HEAD', 'GET', 'OPTIONS', 'POST', 'PATCH', 'PUT',
                             'DELETE']
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        # Mount adapters for retries regardless of proxy usage
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

        if self.proxy:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self.session.proxies = {
                "http": os.getenv("HTTP_PROXY"),
                "https": os.getenv("HTTPS_PROXY"),
            }

    def _build_headers(self) -> Dict[str, str]:
        """Build headers for API requests.

        Returns:
            Dict of headers.
        """
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        if self.auth_token:
            headers['Authorization'] = f'api {self.auth_token}'
        if self.app_id:
            headers['X-App-Id'] = self.app_id
        return headers

    def _request(
            self,
            method: str,
            endpoint: str,
            params: Optional[Dict[str, Any]] = None,
            json: Optional[Dict[str, Any]] = None,
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
        url = f'{self.BASE_URL}/{endpoint.lstrip("/")}'
        headers = self._build_headers()
        logger.debug(f'Making {method} request to {url} with params={params}, '
                     f'json={json}')

        try:
            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json,
                timeout=self.timeout,
                verify=not self.proxy,
                **kwargs,
            )
            if self.raise_for_status:
                response.raise_for_status()
            return response.json() if response.content else None
        except requests.exceptions.HTTPError as e:
            logger.error(f'HTTP error: {e.response.status_code} - '
                         f'{e.response.text}')
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f'Request failed: {str(e)}')
            raise

    # --- Cart Endpoints ---

    def get_cart_product(self, itemcode: str, langid: str) -> Dict:
        """Get a product from the cart.

        Args:
            itemcode: Item code.
            langid: Language ID.

        Returns:
            Product details.
        """
        return self._request('GET', f'/cart/product/{itemcode}/{langid}')

    # --- Authentication Endpoints ---

    def create_user_token(self, data: Dict) -> Dict:
        """Create a user token.

        Args:
            data: Payload for token creation.

        Returns:
            Token details.
        """
        return self._request('POST', '/user/token', json=data)

    def reset_password(self, data: Dict) -> Dict:
        """Reset user password.

        Args:
            data: Payload for password reset.

        Returns:
            Response details.
        """
        return self._request('POST', '/users/reset_password', json=data)

    def create_user(self, data: Dict) -> Dict:
        """Create a new user.

        Args:
            data: User creation payload.

        Returns:
            User details.
        """
        return self._request('POST', '/users', json=data)

    def delete_user_token(self) -> None:
        """Delete the current user token."""
        return self._request('DELETE', '/user/token')

    # --- Badges Endpoints ---

    def get_badges(self) -> List[Dict]:
        """Get all badges.

        Returns:
            List of badges.
        """
        return self._request('GET', '/badges')

    def get_badge(self, badgeid: int) -> Dict:
        """Get a specific badge.

        Args:
            badgeid: Badge ID.

        Returns:
            Badge details.
        """
        return self._request('GET', f'/badges/{badgeid}')

    # --- Content Hierarchy Endpoints ---

    def get_categories(self) -> List[Dict]:
        """Get all categories.

        Returns:
            List of categories.
        """
        return self._request('GET', '/categories')

    # --- Media Endpoints ---

    def get_image(self, imageid: str) -> Dict:
        """Get an image.

        Args:
            imageid: Image ID or GUID.

        Returns:
            Image details.
        """
        return self._request('GET', f'/media/images/{imageid}')

    def get_video(self, videoid: str) -> Dict:
        """Get a video.

        Args:
            videoid: Video ID or GUID.

        Returns:
            Video details.
        """
        return self._request('GET', f'/media/videos/{videoid}')

    # --- Guides Endpoints ---

    def get_guides(self, params: Optional[Dict] = None) -> List[Dict]:
        """Get a list of guides.

        Args:
            params: Query parameters for filtering, pagination, etc.

        Returns:
            List of guides.
        """
        return self._request('GET', '/guides', params=params)

    def get_all_guides(self, page_size: int = 100) -> List[Dict]:
        """Get all guides by handling pagination.

        Args:
            page_size: Number of results per page.

        Returns:
            List of all guides.
        """
        all_guides: List[Dict] = []
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

    def get_guide(self, guideid: int) -> Dict:
        """Get a specific guide.

        Args:
            guideid: Guide ID.

        Returns:
            Guide details.
        """
        return self._request('GET', f'/guides/{guideid}')

    def get_guide_tags(self, guideid: int) -> List[str]:
        """Get tags for a guide.

        Args:
            guideid: Guide ID.

        Returns:
            List of tags.
        """
        return self._request('GET', f'/guides/{guideid}/tags')

    def create_guide(self, data: Dict) -> Dict:
        """Create a new guide.

        Args:
            data: Guide creation payload.

        Returns:
            Created guide details.
        """
        return self._request('POST', '/guides', json=data)

    def update_guide(self, guideid: int, data: Dict,
                     revisionid: Optional[int] = None) -> Dict:
        """Update a guide.

        Args:
            guideid: Guide ID.
            data: Update payload.
            revisionid: Optional revision ID.

        Returns:
            Updated guide details.
        """
        params = {'revisionid': revisionid} if revisionid else None
        return self._request('PATCH', f'/guides/{guideid}', json=data,
                             params=params)

    def delete_guide(self, guideid: int) -> None:
        """Delete a guide.

        Args:
            guideid: Guide ID.
        """
        return self._request('DELETE', f'/guides/{guideid}')

    def restore_guide(self, guideid: int, langid: str) -> Dict:
        """Restore a guide.

        Args:
            guideid: Guide ID.
            langid: Language ID.

        Returns:
            Restored guide details.
        """
        return self._request('POST', f'/guides/{guideid}/{langid}/restore')

    def complete_guide(self, guideid: int) -> Dict:
        """Mark a guide as completed.

        Args:
            guideid: Guide ID.

        Returns:
            Response details.
        """
        return self._request('PUT', f'/guides/{guideid}/completed')

    def uncomplete_guide(self, guideid: int) -> None:
        """Unmark a guide as completed.

        Args:
            guideid: Guide ID.
        """
        return self._request('DELETE', f'/guides/{guideid}/completed')

    def make_guide_public(self, guideid: int) -> Dict:
        """Make a guide public.

        Args:
            guideid: Guide ID.

        Returns:
            Response details.
        """
        return self._request('PUT', f'/guides/{guideid}/public')

    def make_guide_private(self, guideid: int) -> Dict:
        """Make a guide private.

        Args:
            guideid: Guide ID.

        Returns:
            Response details.
        """
        return self._request('DELETE', f'/guides/{guideid}/public')

    def create_guide_step(self, guideid: int, data: Dict) -> Dict:
        """Create a step in a guide.

        Args:
            guideid: Guide ID.
            data: Step payload.

        Returns:
            Created step details.
        """
        return self._request('POST', f'/guides/{guideid}/steps', json=data)

    def update_guide_step(self, guideid: int, stepid: int, data: Dict) -> Dict:
        """Update a guide step.

        Args:
            guideid: Guide ID.
            stepid: Step ID.
            data: Update payload.

        Returns:
            Updated step details.
        """
        return self._request('PATCH', f'/guides/{guideid}/steps/{stepid}',
                             json=data)

    def delete_guide_step(self, guideid: int, stepid: int) -> None:
        """Delete a guide step.

        Args:
            guideid: Guide ID.
            stepid: Step ID.
        """
        return self._request('DELETE', f'/guides/{guideid}/steps/{stepid}')

    def update_guide_step_order(self, guideid: int, data: Dict) -> Dict:
        """Update the order of steps in a guide.

        Args:
            guideid: Guide ID.
            data: Step order payload.

        Returns:
            Response details.
        """
        return self._request('PUT', f'/guides/{guideid}/steporder', json=data)

    def get_guide_users(self, guideid: int) -> List[Dict]:
        """Get users associated with a guide.

        Args:
            guideid: Guide ID.

        Returns:
            List of users.
        """
        return self._request('GET', f'/guides/{guideid}/users')

    def add_user_to_guide(self, guideid: int, userid: int) -> Dict:
        """Add a user to a guide.

        Args:
            guideid: Guide ID.
            userid: User ID.

        Returns:
            Response details.
        """
        return self._request('PUT', f'/guides/{guideid}/users/{userid}')

    def remove_user_from_guide(self, guideid: int, userid: int) -> None:
        """Remove a user from a guide.

        Args:
            guideid: Guide ID.
            userid: User ID.
        """
        return self._request('DELETE', f'/guides/{guideid}/users/{userid}')

    def get_guide_teams(self, guideid: int) -> List[Dict]:
        """Get teams associated with a guide.

        Args:
            guideid: Guide ID.

        Returns:
            List of teams.
        """
        return self._request('GET', f'/guides/{guideid}/teams')

    def add_team_to_guide(self, guideid: int, teamid: int) -> Dict:
        """Add a team to a guide.

        Args:
            guideid: Guide ID.
            teamid: Team ID.

        Returns:
            Response details.
        """
        return self._request('PUT', f'/guides/{guideid}/teams/{teamid}')

    def remove_team_from_guide(self, guideid: int, teamid: int) -> None:
        """Remove a team from a guide.

        Args:
            guideid: Guide ID.
            teamid: Team ID.
        """
        return self._request('DELETE', f'/guides/{guideid}/teams/{teamid}')

    def get_guide_releases(self) -> List[Dict]:
        """Get all guide releases.

        Returns:
            List of releases.
        """
        return self._request('GET', '/guides/releases')

    def delete_guide_release(self, releaseid: int) -> None:
        """Delete a guide release.

        Args:
            releaseid: Release ID.
        """
        return self._request('DELETE', f'/guides/releases/{releaseid}')

    def get_guide_specific_releases(self, guideid: int) -> List[Dict]:
        """Get releases for a specific guide.

        Args:
            guideid: Guide ID.

        Returns:
            List of releases.
        """
        return self._request('GET', f'/guides/{guideid}/releases')

    def create_guide_release(self, data: Dict) -> Dict:
        """Create a guide release.

        Args:
            data: Release payload.

        Returns:
            Created release details.
        """
        return self._request('POST', '/guides/releases', json=data)

    def update_guide_release(self, releaseid: int, data: Dict) -> Dict:
        """Update a guide release.

        Args:
            releaseid: Release ID.
            data: Update payload.

        Returns:
            Updated release details.
        """
        return self._request('PATCH', f'/guides/releases/{releaseid}',
                             json=data)

    def add_guide_tag(self, guideid: int, data: Dict) -> Dict:
        """Add a tag to a guide.

        Args:
            guideid: Guide ID.
            data: Tag payload.

        Returns:
            Response details.
        """
        return self._request('PUT', f'/guides/{guideid}/tag', json=data)

    def remove_guide_tag(self, guideid: int, data: Dict) -> None:
        """Remove a tag from a guide.

        Args:
            guideid: Guide ID.
            data: Tag payload.
        """
        return self._request('DELETE', f'/guides/{guideid}/tag', json=data)

    # --- Comments Endpoints ---

    def get_comments(self) -> List[Dict]:
        """Get all comments.

        Returns:
            List of comments.
        """
        return self._request('GET', '/comments')

    def get_comment(self, commentid: int) -> Dict:
        """Get a specific comment.

        Args:
            commentid: Comment ID.

        Returns:
            Comment details.
        """
        return self._request('GET', f'/comments/{commentid}')

    def create_comment(self, context: str, contextid: int, data: Dict) -> Dict:
        """Create a comment.

        Args:
            context: Context type (e.g., 'guide').
            contextid: Context ID.
            data: Comment payload.

        Returns:
            Created comment details.
        """
        return self._request('POST', f'/comments/{context}/{contextid}',
                             json=data)

    def update_comment(self, commentid: int, data: Dict) -> Dict:
        """Update a comment.

        Args:
            commentid: Comment ID.
            data: Update payload.

        Returns:
            Updated comment details.
        """
        return self._request('PATCH', f'/comments/{commentid}', json=data)

    def delete_comment(self, commentid: int) -> None:
        """Delete a comment.

        Args:
            commentid: Comment ID.
        """
        return self._request('DELETE', f'/comments/{commentid}')

    # --- Suggest Endpoints ---

    def suggest(self, query: str, doctypes: str = 'all') -> List[Dict]:
        """Get suggestions based on a query.

        Args:
            query: Search query.
            doctypes: Document types (default: 'all').

        Returns:
            List of suggestions.
        """
        params = {'doctypes': doctypes}
        return self._request('GET', f'/suggest/{query}', params=params)

    # --- Stories Endpoints ---

    def get_stories(self) -> List[Dict]:
        """Get all stories.

        Returns:
            List of stories.
        """
        return self._request('GET', '/stories')

    def get_story(self, storyid: int) -> Dict:
        """Get a specific story.

        Args:
            storyid: Story ID.

        Returns:
            Story details.
        """
        return self._request('GET', f'/stories/{storyid}')

    def create_story(self, data: Dict) -> Dict:
        """Create a story.

        Args:
            data: Story payload.

        Returns:
            Created story details.
        """
        return self._request('POST', '/stories', json=data)

    def update_story(self, storyid: int, data: Dict) -> Dict:
        """Update a story.

        Args:
            storyid: Story ID.
            data: Update payload.

        Returns:
            Updated story details.
        """
        return self._request('PATCH', f'/stories/{storyid}', json=data)

    # --- Tags Endpoints ---

    def get_tags(self) -> List[Dict]:
        """Get all tags.

        Returns:
            List of tags.
        """
        return self._request('GET', '/tags')

    def add_wiki_tag(self, namespace: str, title: str, data: Dict) -> Dict:
        """Add a tag to a wiki.

        Args:
            namespace: Wiki namespace.
            title: Wiki title.
            data: Tag payload.

        Returns:
            Response details.
        """
        return self._request('PUT', f'/wikis/{namespace}/{title}/tag',
                             json=data)

    def remove_wiki_tag(self, namespace: str, title: str, data: Dict) -> None:
        """Remove a tag from a wiki.

        Args:
            namespace: Wiki namespace.
            title: Wiki title.
            data: Tag payload.
        """
        return self._request('DELETE', f'/wikis/{namespace}/{title}/tag',
                             json=data)

    # --- Teams Endpoints ---

    def get_teams(self) -> List[Dict]:
        """Get all teams.

        Returns:
            List of teams.
        """
        return self._request('GET', '/teams')

    def get_team_members(self, teamid: int) -> List[Dict]:
        """Get members of a team.

        Args:
            teamid: Team ID.

        Returns:
            List of members.
        """
        return self._request('GET', f'/teams/{teamid}')

    def add_user_to_team(self, teamid: int, userid: int) -> Dict:
        """Add a user to a team.

        Args:
            teamid: Team ID.
            userid: User ID.

        Returns:
            Response details.
        """
        return self._request('PUT', f'/teams/{teamid}/users/{userid}')

    def remove_user_from_team(self, teamid: int, userid: int) -> None:
        """Remove a user from a team.

        Args:
            teamid: Team ID.
            userid: User ID.
        """
        return self._request('DELETE', f'/teams/{teamid}/users/{userid}')

    # --- Users Endpoints ---

    def get_users(self) -> List[Dict]:
        """Get all users.

        Returns:
            List of users.
        """
        return self._request('GET', '/users')

    def search_users(self, search: str) -> List[Dict]:
        """Search for users.

        Args:
            search: Search query.

        Returns:
            List of matching users.
        """
        return self._request('GET', f'/users/search/{search}')

    def get_user(self, userid: int) -> Dict:
        """Get a specific user.

        Args:
            userid: User ID.

        Returns:
            User details.
        """
        return self._request('GET', f'/users/{userid}')

    def get_user_by_sso(self, sso_userid: str) -> Dict:
        """Get a user by SSO ID.

        Args:
            sso_userid: SSO user ID.

        Returns:
            User details.
        """
        return self._request('GET', f'/users/sso/{sso_userid}')

    def get_user_by_email(self, email: str) -> Dict:
        """Get a user by email.

        Args:
            email: User email.

        Returns:
            User details.
        """
        return self._request('GET', f'/users/email/{email}')

    def get_user_badges(self, userid: int) -> List[Dict]:
        """Get badges for a user.

        Args:
            userid: User ID.

        Returns:
            List of badges.
        """
        return self._request('GET', f'/users/{userid}/badges')

    def get_user_favorite_guides(self, userid: int) -> List[Dict]:
        """Get favorite guides for a user.

        Args:
            userid: User ID.

        Returns:
            List of favorite guides.
        """
        return self._request('GET', f'/users/{userid}/favorites/guides')

    def get_user_guides(self, userid: int) -> List[Dict]:
        """Get guides for a user.

        Args:
            userid: User ID.

        Returns:
            List of guides.
        """
        return self._request('GET', f'/users/{userid}/guides')

    def get_user_completions(self, userid: int) -> List[Dict]:
        """Get completions for a user.

        Args:
            userid: User ID.

        Returns:
            List of completions.
        """
        return self._request('GET', f'/users/{userid}/completions')

    def get_current_user(self) -> Dict:
        """Get the current authenticated user.

        Returns:
            User details.
        """
        return self._request('GET', '/user')

    def get_current_user_badges(self) -> List[Dict]:
        """Get badges for the current user.

        Returns:
            List of badges.
        """
        return self._request('GET', '/user/badges')

    def get_current_user_favorite_guides(self) -> List[Dict]:
        """Get favorite guides for the current user.

        Returns:
            List of favorite guides.
        """
        return self._request('GET', '/user/favorites/guides')

    def favorite_guide(self, guideid: int) -> Dict:
        """Favorite a guide for the current user.

        Args:
            guideid: Guide ID.

        Returns:
            Response details.
        """
        return self._request('PUT', f'/user/favorites/guides/{guideid}')

    def unfavorite_guide(self, guideid: int) -> None:
        """Unfavorite a guide for the current user.

        Args:
            guideid: Guide ID.
        """
        return self._request('DELETE', f'/user/favorites/guides/{guideid}')

    def get_current_user_guides(self) -> List[Dict]:
        """Get guides for the current user.

        Returns:
            List of guides.
        """
        return self._request('GET', '/user/guides')

    def get_current_user_flags(self) -> List[Dict]:
        """Get flags for the current user.

        Returns:
            List of flags.
        """
        return self._request('GET', '/user/flags')

    def get_current_user_completions(self) -> List[Dict]:
        """Get completions for the current user.

        Returns:
            List of completions.
        """
        return self._request('GET', '/user/completions')

    def get_current_user_images(self) -> List[Dict]:
        """Get images for the current user.

        Returns:
            List of images.
        """
        return self._request('GET', '/user/media/images')

    def upload_user_image(self, data: Dict) -> Dict:
        """Upload an image for the current user.

        Args:
            data: Image payload (e.g., base64-encoded).

        Returns:
            Uploaded image details.
        """
        return self._request('POST', '/user/media/images', json=data)

    def delete_user_images(self, imageids: str) -> None:
        """Delete images for the current user.

        Args:
            imageids: Comma-separated image IDs.
        """
        return self._request('DELETE', f'/user/media/images/{imageids}')

    def update_user_image(self, imageid: str, data: Dict) -> Dict:
        """Update a user image.

        Args:
            imageid: Image ID or GUID.
            data: Update payload.

        Returns:
            Updated image details.
        """
        return self._request('POST', f'/user/media/images/{imageid}',
                             json=data)

    def get_current_user_videos(self) -> List[Dict]:
        """Get videos for the current user.

        Returns:
            List of videos.
        """
        return self._request('GET', '/user/media/videos')

    def update_user(self, userid: int, data: Dict) -> Dict:
        """Update a user.

        Args:
            userid: User ID.
            data: Update payload.

        Returns:
            Updated user details.
        """
        return self._request('PATCH', f'/users/{userid}', json=data)

    # --- Wikis Endpoints ---

    def get_category(self, device_name: Optional[str] = None, params: Optional[dict] = None) -> Dict:
        """Get the category hierarchy.

        Args:
            device_name: Optional device name to filter the hierarchy.
            params: Optional parameters to customize the response.

        Returns:
            Hierarchy details.
        """
        endpoint = '/wikis/CATEGORY'
        if device_name:
            endpoint += f'/{device_name}'
        if not params:
            params = {'display': 'hierarchy'}
        return self._request('GET', endpoint, params=params)

    def get_wikis(self, namespace: str) -> List[Dict]:
        """Get wikis in a namespace.

        Args:
            namespace: Wiki namespace.

        Returns:
            List of wikis.
        """
        return self._request('GET', f'/wikis/{namespace}')

    def get_wiki(self, namespace: str, title: str) -> Dict:
        """Get a specific wiki.

        Args:
            namespace: Wiki namespace.
            title: Wiki title.

        Returns:
            Wiki details.
        """
        return self._request('GET', f'/wikis/{namespace}/{title}')

    def get_wiki_tags(self, namespace: str, title: str) -> List[str]:
        """Get tags for a wiki.

        Args:
            namespace: Wiki namespace.
            title: Wiki title.

        Returns:
            List of tags.
        """
        return self._request('GET', f'/wikis/{namespace}/{title}/tags')

    def get_category_children(self, title: str) -> List[Dict]:
        """Get children of a category.

        Args:
            title: Category title.

        Returns:
            List of children.
        """
        return self._request('GET', f'/wikis/CATEGORY/{title}/children')

    def get_category_identification(self, title: str) -> str:
        """Get identification for a category.

        Args:
            title: Category title.

        Returns:
            Identification string.
        """
        return self._request('GET', f'/wikis/CATEGORY/{title}/identification')

    def create_wiki(self, data: Dict) -> Dict:
        """Create a new wiki.

        Args:
            data: Wiki creation payload.

        Returns:
            Created wiki details.
        """
        return self._request('POST', '/wikis', json=data)

    def update_wiki(self, namespace: str, title: str, data: Dict,
                    revisionid: Optional[int] = None) -> Dict:
        """Update a wiki.

        Args:
            namespace: Wiki namespace.
            title: Wiki title.
            data: Update payload.
            revisionid: Optional revision ID.

        Returns:
            Updated wiki details.
        """
        params = {'revisionid': revisionid} if revisionid else None
        return self._request('PATCH', f'/wikis/{namespace}/{title}',
                             json=data, params=params)

    def delete_wiki(self, namespace: str, title: str) -> None:
        """Delete a wiki.

        Args:
            namespace: Wiki namespace.
            title: Wiki title.
        """
        return self._request('DELETE', f'/wikis/{namespace}/{title}')

    def revert_wiki(self, namespace: str, title: str, data: Dict) -> Dict:
        """Revert a wiki to a previous state.

        Args:
            namespace: Wiki namespace.
            title: Wiki title.
            data: Revert payload.

        Returns:
            Response details.
        """
        return self._request('POST', f'/wikis/{namespace}/{title}/revert',
                             json=data)

    def set_wiki_parent(self, title: str, data: Dict) -> Dict:
        """Set the parent for a category wiki.

        Args:
            title: Category title.
            data: Parent payload.

        Returns:
            Response details.
        """
        return self._request('PUT', f'/wikis/CATEGORY/{title}/parent',
                             json=data)

    # --- User View History Endpoints ---

    def get_user_view_history(self, userid: int) -> List[Dict]:
        """Get view history for a user.

        Args:
            userid: User ID.

        Returns:
            List of view history entries.
        """
        return self._request('GET', f'/user_view_history/user/{userid}')

    def get_document_view_history(self, doc_type: str, docid: int) -> List[Dict]:
        """Get view history for a document.

        Args:
            doc_type: Document type.
            docid: Document ID.

        Returns:
            List of view history entries.
        """
        return self._request('GET', f'/user_view_history/{doc_type}/{docid}')

    # --- Documents Endpoints ---

    def get_document(self, id_or_guid: str) -> Dict:
        """Get a document.

        Args:
            id_or_guid: Document ID or GUID.

        Returns:
            Document details.
        """
        return self._request('GET', f'/documents/{id_or_guid}')
