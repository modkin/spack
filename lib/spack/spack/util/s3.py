# Copyright 2013-2022 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
import os
import urllib.parse
from typing import Any, Dict, Tuple

import spack
import spack.config

#: Map (mirror name, method) tuples to s3 client instances.
s3_client_cache: Dict[Tuple[str, str], Any] = dict()


def get_s3_session(url, method="fetch"):
    # import boto and friends as late as possible.  We don't want to require boto as a
    # dependency unless the user actually wants to access S3 mirrors.
    from boto3 import Session
    from botocore import UNSIGNED
    from botocore.client import Config
    from botocore.exceptions import ClientError

    # Circular dependency
    from spack.mirror import MirrorCollection

    global s3_client_cache

    # Parse the URL if not already done.
    if not isinstance(url, urllib.parse.ParseResult):
        url = urllib.parse.urlparse(url)
    url_str = url.geturl()

    def get_mirror_url(mirror):
        return mirror.fetch_url if method == "fetch" else mirror.push_url

    # Get all configured mirrors that could match.
    all_mirrors = MirrorCollection()
    mirrors = [
        (name, mirror)
        for name, mirror in all_mirrors.items()
        if url_str.startswith(get_mirror_url(mirror))
    ]

    if not mirrors:
        name, mirror = None, {}
    else:
        # In case we have more than one mirror, we pick the longest matching url.
        # The heuristic being that it's more specific, and you can have different
        # credentials for a sub-bucket (if that is a thing).
        name, mirror = max(
            mirrors, key=lambda name_and_mirror: len(get_mirror_url(name_and_mirror[1]))
        )

    key = (name, method)

    # Did we already create a client for this? Then return it.
    if key in s3_client_cache:
        return s3_client_cache[key]

    # Otherwise, create it.
    s3_connection, s3_client_args = get_mirror_s3_connection_info(mirror, method)

    session = Session(**s3_connection)
    # if no access credentials provided above, then access anonymously
    if not session.get_credentials():
        s3_client_args["config"] = Config(signature_version=UNSIGNED)

    client = session.client("s3", **s3_client_args)
    client.ClientError = ClientError

    # Cache the client.
    s3_client_cache[key] = client
    return client


def _parse_s3_endpoint_url(endpoint_url):
    if not urllib.parse.urlparse(endpoint_url, scheme="").scheme:
        endpoint_url = "://".join(("https", endpoint_url))

    return endpoint_url


def get_mirror_s3_connection_info(mirror, method):
    """Create s3 config for session/client from a Mirror instance (or just set defaults
    when no mirror is given.)"""
    from spack.mirror import Mirror

    s3_connection = {}
    s3_client_args = {"use_ssl": spack.config.get("config:verify_ssl")}

    # access token
    if isinstance(mirror, Mirror):
        access_token = mirror.get_access_token(method)
        if access_token:
            s3_connection["aws_session_token"] = access_token

        # access pair
        access_pair = mirror.get_access_pair(method)
        if access_pair and access_pair[0] and access_pair[1]:
            s3_connection["aws_access_key_id"] = access_pair[0]
            s3_connection["aws_secret_access_key"] = access_pair[1]

        # profile
        profile = mirror.get_profile(method)
        if profile:
            s3_connection["profile_name"] = profile

        # endpoint url
        endpoint_url = mirror.get_endpoint_url(method) or os.environ.get("S3_ENDPOINT_URL")
    else:
        endpoint_url = os.environ.get("S3_ENDPOINT_URL")

    if endpoint_url:
        s3_client_args["endpoint_url"] = _parse_s3_endpoint_url(endpoint_url)

    return (s3_connection, s3_client_args)
