"""Tests for DockerSpawner class"""
import asyncio
import json

import docker
import pytest
from jupyterhub.tests.test_api import add_user, api_request
from jupyterhub.tests.mocking import public_url
from jupyterhub.utils import url_path_join
from tornado.httpclient import AsyncHTTPClient, HTTPRequest

from dockerspawner import DockerSpawner

# Mark all tests in this file as asyncio
pytestmark = pytest.mark.asyncio

async def test_start_stop(dockerspawner_configured_app):
    app = dockerspawner_configured_app
    name = "has@"
    add_user(app.db, app, name=name)
    user = app.users[name]
    assert isinstance(user.spawner, DockerSpawner)
    token = user.new_api_token()
    # start the server
    r = await api_request(app, "users", name, "server", method="post")
    while r.status_code == 202:
        # request again
        r = await api_request(app, "users", name, "server", method="post")
        await asyncio.sleep(0.1)
    assert r.status_code == 201, r.text
    
    url = url_path_join(public_url(app, user), "api/status")
    resp = await AsyncHTTPClient().fetch(url, headers={"Authorization": "token %s" % token})
    assert resp.effective_url == url
    resp.rethrow()
    assert "kernels" in resp.body.decode("utf-8")

@pytest.mark.parametrize("image", ["1.0", "1.2", "nomatch"])
async def test_image_allow_list(dockerspawner_configured_app, image):
    app = dockerspawner_configured_app
    name = "checker"
    add_user(app.db, app, name=name)
    user = app.users[name]
    assert isinstance(user.spawner, DockerSpawner)
    user.spawner.remove_containers = True
    user.spawner.image_whitelist = {
        "0.9": "jupyterhub/singleuser:0.9",
        "0.8": "jupyterhub/singleuser:0.8",
    }
    token = user.new_api_token()
    # start the server
    r = await api_request(
        app, "users", name, "server", method="post", data=json.dumps({"image": image})
    )
    if image not in user.spawner.image_whitelist:
        with pytest.raises(Exception):
            r.raise_for_status()
        return
    while r.status_code == 202:
        # request again
        r = await api_request(app, "users", name, "server", method="post")
        await asyncio.sleep(0.1)
    assert r.status_code == 201, r.text
    
    url = url_path_join(public_url(app, user), "api/status")
    resp = await AsyncHTTPClient().fetch(url, headers={"Authorization": "token %s" % token})
    assert resp.effective_url == url
    resp.rethrow()

    assert resp.headers['x-jupyterhub-version'].startswith(image)
    r = await api_request(
        app, "users", name, "server", method="delete",
    )
    r.raise_for_status()


async def test_image_pull_policy(dockerspawner_configured_app):
    app = dockerspawner_configured_app
    name = "gumby"
    add_user(app.db, app, name=name)
    user = app.users[name]
    assert isinstance(user.spawner, DockerSpawner)
    spawner = user.spawners[""]
    spawner.image = "jupyterhub/doesntexist:nosuchtag"
    with pytest.raises(docker.errors.NotFound):
        spawner.image_pull_policy = "never"
        await spawner.pull_image(spawner.image)

    repo = "busybox"
    tag = "1.29.1"  # a version that's definitely not latest
    # ensure image isn't present
    try:
        await asyncio.wrap_future(spawner.docker("remove_image", "{}:{}".format(repo, tag)))
    except docker.errors.ImageNotFound:
        pass

    spawner.pull_policy = "ifnotpresent"
    image = "{}:{}".format(repo, tag)
    # should trigger a pull
    await spawner.pull_image(image)
    # verify that the image exists now
    old_image_info = await asyncio.wrap_future(spawner.docker("inspect_image", image))
    print(old_image_info)

    # now tag busybox:latest as our current version
    # which is not latest!
    await spawner.docker("tag", image, repo)

    image = repo  # implicit :latest
    spawner.pull_policy = "ifnotpresent"
    # check with ifnotpresent shouldn't pull
    await spawner.pull_image(image)
    image_info = await asyncio.wrap_future(spawner.docker("inspect_image", repo))
    assert image_info["Id"] == old_image_info["Id"]

    # run again with Always,
    # should trigger a pull even though the image is present
    spawner.pull_policy = "always"
    spawner.pull_image(image)
    image_info = await asyncio.wrap_future(spawner.docker("inspect_image", repo))
    assert image_info["Id"] != old_image_info["Id"]

    # run again with never, make sure it's still happy
    spawner.pull_policy = "never"
    spawner.pull_image(image)
