import json

import pytest

from conftest import MinidspSpyConfig


@pytest.fixture
def profile_client(httpserver, tmp_path):
    from ezbeq import main
    app, _ = main.create_app(MinidspSpyConfig(httpserver.host, httpserver.port, tmp_path))
    return app.test_client()


@pytest.fixture
def profile_app(httpserver, tmp_path):
    from ezbeq import main
    cfg = MinidspSpyConfig(httpserver.host, httpserver.port, tmp_path)
    app, _ = main.create_app(cfg)
    return app, cfg


def make_profile(slot='1', master_volume=None, filters=None):
    """Build a profile payload in BEQ Designer's native format."""
    payload = {'slot': slot, 'filters': filters or []}
    if master_volume is not None:
        payload['masterVolume'] = master_volume
    return payload


def make_filter(freq=28.0, gain=4.0, q=0.9, filt_type='LowShelf'):
    """Build a single filter with pre-computed biquads at 96000 Hz."""
    return {
        'type': filt_type,
        'freq': freq,
        'gain': gain,
        'q': q,
        'biquads': {
            '96000': {
                'b': ['1.0002351230602025', '-1.9981834204960565', '0.9979525215864314'],
                'a': ['1.9981841999419296', '-0.9981868652007604']
            }
        }
    }


class TestLoadProfileHappyPath:

    def test_load_profile_with_filters_and_mv(self, profile_app):
        app, cfg = profile_app
        client = app.test_client()
        filters = [make_filter(), make_filter(freq=40.0, gain=3.0)]
        payload = make_profile(master_volume=-2.5, filters=filters)

        r = client.put('/api/1/devices/master/profile',
                       data=json.dumps(payload),
                       content_type='application/json')

        assert r.status_code == 200
        # Verify biquad commands were sent
        cmds = cfg.spy.take_commands()
        bq_cmds = [c for c in cmds if 'set --' in c]
        assert len(bq_cmds) > 0, f"Expected biquad commands, got: {cmds}"
        # Verify gain was set
        gain_cmds = [c for c in cmds if c.startswith('gain')]
        assert any('-- -2.5' in c for c in gain_cmds) or any('-2.5' in c for c in cmds), \
            f"Expected master volume -2.5 in commands: {cmds}"

    def test_load_profile_without_mv(self, profile_app):
        app, cfg = profile_app
        client = app.test_client()
        filters = [make_filter()]
        payload = make_profile(filters=filters)

        r = client.put('/api/1/devices/master/profile',
                       data=json.dumps(payload),
                       content_type='application/json')

        assert r.status_code == 200
        cmds = cfg.spy.take_commands()
        bq_cmds = [c for c in cmds if 'set --' in c]
        assert len(bq_cmds) > 0
        # No gain commands should be sent
        gain_cmds = [c for c in cmds if c.startswith('gain')]
        assert len(gain_cmds) == 0, f"Expected no gain commands, got: {gain_cmds}"

    def test_response_contains_device_state(self, profile_client):
        payload = make_profile(filters=[make_filter()])
        r = profile_client.put('/api/1/devices/master/profile',
                               data=json.dumps(payload),
                               content_type='application/json')
        assert r.status_code == 200
        data = r.json
        assert 'masterVolume' in data
        assert 'slots' in data


class TestLoadProfileEdgeCases:

    def test_empty_filters_returns_success(self, profile_app):
        app, cfg = profile_app
        client = app.test_client()
        payload = make_profile(filters=[])

        r = client.put('/api/1/devices/master/profile',
                       data=json.dumps(payload),
                       content_type='application/json')

        assert r.status_code == 200
        cmds = cfg.spy.take_commands()
        # No biquad commands should be sent
        bq_cmds = [c for c in cmds if 'set --' in c]
        assert len(bq_cmds) == 0, f"Expected no biquad commands, got: {cmds}"


class TestLoadProfileErrors:

    def test_unknown_device_returns_error(self, profile_client):
        payload = make_profile(filters=[make_filter()])
        r = profile_client.put('/api/1/devices/nonexistent/profile',
                               data=json.dumps(payload),
                               content_type='application/json')
        assert r.status_code in (404, 500)

    def test_invalid_slot_returns_400(self, profile_client):
        payload = make_profile(slot='5', filters=[make_filter()])
        r = profile_client.put('/api/1/devices/master/profile',
                               data=json.dumps(payload),
                               content_type='application/json')
        assert r.status_code == 400

    def test_mv_too_high_returns_400(self, profile_client):
        payload = make_profile(master_volume=1.0, filters=[make_filter()])
        r = profile_client.put('/api/1/devices/master/profile',
                               data=json.dumps(payload),
                               content_type='application/json')
        assert r.status_code == 400

    def test_mv_too_low_returns_400(self, profile_client):
        payload = make_profile(master_volume=-128.0, filters=[make_filter()])
        r = profile_client.put('/api/1/devices/master/profile',
                               data=json.dumps(payload),
                               content_type='application/json')
        assert r.status_code == 400

    def test_malformed_filter_returns_error(self, profile_client):
        payload = make_profile(filters=[{'type': 'LowShelf', 'freq': 28.0}])
        r = profile_client.put('/api/1/devices/master/profile',
                               data=json.dumps(payload),
                               content_type='application/json')
        assert r.status_code in (400, 500)
