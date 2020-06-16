"""Tests for SwarmSpawner"""

from unittest import mock

import pytest
from jupyterhub.tests.test_api import add_user, api_request
from jupyterhub.tests.mocking import public_url
from jupyterhub.utils import url_path_join
from tornado.httpclient import AsyncHTTPClient, HTTPRequest

from dockerspawner import SwarmSpawner

# Mark all tests in this file as asyncio
pytestmark = pytest.mark.asyncio

async def test_start_stop(swarmspawner_configured_app):
    app = swarmspawner_configured_app
    name = "somebody"
    add_user(app.db, app, name=name)
    user = app.users[name]
    assert isinstance(user.spawner, SwarmSpawner)
    token = user.new_api_token()
    # start the server
    r = await api_request(app, "users", name, "server", method="post")
    while r.status_code == 202:
        # request again
        r = await api_request(app, "users", name, "server", method="post")
    assert r.status_code == 201, r.text
    url = url_path_join(public_url(app, user), "api/status")

    resp = await AsyncHTTPClient().fetch(url, headers={"Authorization": "token %s" % token})
    assert resp.effective_url == url
    resp.rethrow()
    assert "kernels" in resp.body.decode("utf-8")
