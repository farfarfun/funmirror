import pytest

from funmirror.sync.platforms import (
    GitCodePlatform,
    GiteePlatform,
    GitHubPlatform,
    GitLabPlatform,
    make_platform,
)


def test_make_platform_github():
    assert isinstance(make_platform("github", token="t"), GitHubPlatform)


def test_make_platform_gitee():
    platform = make_platform("gitee", token="t", key_file="/tmp/key")
    assert isinstance(platform, GiteePlatform)


def test_make_platform_gitee_requires_key_file():
    with pytest.raises(ValueError):
        make_platform("gitee", token="t")


def test_make_platform_gitlab():
    platform = make_platform("gitlab", token="t", endpoint="gitlab.example.com")
    assert isinstance(platform, GitLabPlatform)
    assert platform.endpoint == "gitlab.example.com"


def test_make_platform_gitcode():
    assert isinstance(make_platform("gitcode", token="t"), GitCodePlatform)


def test_make_platform_unknown_kind():
    with pytest.raises(ValueError):
        make_platform("bitbucket")
