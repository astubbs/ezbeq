import pytest

from conftest import MinidspSpyConfig


class VersionedConfig(MinidspSpyConfig):
    """MinidspSpyConfig with controllable version and git_info."""

    def __init__(self, host, port, tmp_path, version='1.2.3', git_info=None):
        self.__version = version
        self.__git_info = git_info if git_info is not None else {'branch': None, 'sha': None}
        super().__init__(host, port, tmp_path)

    @property
    def version(self):
        return self.__version

    @property
    def git_info(self):
        return self.__git_info


@pytest.fixture
def version_client_no_git(httpserver, tmp_path):
    from ezbeq import main
    app, _ = main.create_app(VersionedConfig(httpserver.host, httpserver.port, tmp_path,
                                              version='1.2.3',
                                              git_info={'branch': None, 'sha': None}))
    return app.test_client()


@pytest.fixture
def version_client_with_git(httpserver, tmp_path):
    from ezbeq import main
    app, _ = main.create_app(VersionedConfig(httpserver.host, httpserver.port, tmp_path,
                                              version='1.2.3',
                                              git_info={'branch': 'feats/my-feature', 'sha': 'abc1234'}))
    return app.test_client()


@pytest.fixture
def version_client_unknown(httpserver, tmp_path):
    from ezbeq import main
    app, _ = main.create_app(VersionedConfig(httpserver.host, httpserver.port, tmp_path,
                                              version='UNKNOWN',
                                              git_info={'branch': 'main', 'sha': 'deadbee'}))
    return app.test_client()


def test_version_returns_version(version_client_no_git):
    r = version_client_no_git.get('/api/1/version')
    assert r.status_code == 200
    assert r.json['version'] == '1.2.3'


def test_version_no_git_info_omits_branch_and_sha(version_client_no_git):
    r = version_client_no_git.get('/api/1/version')
    assert r.status_code == 200
    assert 'branch' not in r.json
    assert 'sha' not in r.json


def test_version_with_git_info_includes_branch_and_sha(version_client_with_git):
    r = version_client_with_git.get('/api/1/version')
    assert r.status_code == 200
    assert r.json['version'] == '1.2.3'
    assert r.json['branch'] == 'feats/my-feature'
    assert r.json['sha'] == 'abc1234'


def test_version_unknown_with_git_still_returns_git_info(version_client_unknown):
    r = version_client_unknown.get('/api/1/version')
    assert r.status_code == 200
    assert r.json['version'] == 'UNKNOWN'
    assert r.json['branch'] == 'main'
    assert r.json['sha'] == 'deadbee'
