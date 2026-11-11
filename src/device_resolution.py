"""Resolve device identities using explicit iFixit redirects, never name similarity."""

import re

import requests

from data_quality import DataQualityError
from utils import _DeviceDataUtils


def resolve_device(client, title, limiter, namespace="CATEGORY"):
    if namespace not in {"CATEGORY", "WIKI"}:
        raise DataQualityError(f"Unsupported wiki namespace: {namespace}")
    visited = set()
    redirects = []
    for _ in range(6):
        key = (namespace, title)
        if key in visited:
            raise DataQualityError(f"Redirect loop for {title}")
        visited.add(key)
        limiter.acquire()
        data = client.get_wiki(namespace, title)
        if not isinstance(data, dict) or not isinstance(data.get("wikiid"), int) or not data.get("title"):
            raise DataQualityError(f"Invalid device response for {namespace}/{title}")
        redirect = re.fullmatch(r"\s*\[redirect\|([^\]]+)\]\s*", data.get("contents_raw") or "", re.IGNORECASE)
        if not redirect:
            return data, namespace, _DeviceDataUtils.to_ifixit_title(data["title"]), redirects
        redirects.append({"namespace": namespace, "title": title, "wikiid": data["wikiid"]})
        target = redirect.group(1).strip()
        if ":" in target:
            prefix, target = target.split(":", 1)
            namespace = {"category": "CATEGORY", "device": "CATEGORY", "wiki": "WIKI"}.get(prefix.casefold())
            if namespace is None:
                raise DataQualityError(f"Unsupported device redirect: {redirect.group(1)}")
        title = _DeviceDataUtils.to_ifixit_title(target)
    raise DataQualityError(f"Too many device redirects for {title}")


def resolve_previous_names(client, previous_devices, device_names, limiter):
    """Only an explicit redirect may connect a vanished baseline name to a new name."""
    current = {_DeviceDataUtils.to_ifixit_title(name): name for name in device_names}
    resolved = {}
    for previous in previous_devices or []:
        if previous["name"] in device_names:
            continue
        title = previous.get("title") or _DeviceDataUtils.to_ifixit_title(previous["name"])
        try:
            data, namespace, canonical, redirects = resolve_device(
                client, title, limiter, previous.get("wiki_namespace", "CATEGORY")
            )
        except requests.HTTPError as error:
            # The candidate may still be identifiable by a persisted wikiid.
            if error.response is not None and error.response.status_code == 404:
                continue
            raise
        if canonical not in current or not redirects:
            continue
        name = current[canonical]
        if name in resolved:
            raise DataQualityError(f"Multiple previous devices redirect to {name}")
        resolved[name] = (data, namespace, canonical, redirects, [previous["name"]])
    return resolved
