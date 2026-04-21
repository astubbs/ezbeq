import pytest
from unittest.mock import patch, MagicMock


class TestMdnsService:

    def test_registers_service_with_correct_type(self):
        with patch('zeroconf.Zeroconf') as mock_zc_cls, \
             patch('zeroconf.ServiceInfo') as mock_si_cls, \
             patch('ezbeq.mdns.socket') as mock_socket:
            mock_socket.gethostname.return_value = 'testhost'
            mock_socket.inet_aton.return_value = b'\x7f\x00\x00\x01'
            mock_sock = MagicMock()
            mock_sock.getsockname.return_value = ('192.168.1.100', 0)
            mock_socket.socket.return_value = mock_sock
            mock_socket.AF_INET = 2
            mock_socket.SOCK_DGRAM = 2

            from ezbeq.mdns import MdnsService, SERVICE_TYPE
            svc = MdnsService(port=8080, version='1.2.3')

            mock_si_cls.assert_called_once()
            call_args = mock_si_cls.call_args
            assert call_args[0][0] == SERVICE_TYPE
            assert call_args[1]['port'] == 8080
            mock_zc_cls.return_value.register_service.assert_called_once()

    def test_txt_records_include_path_and_version(self):
        with patch('zeroconf.Zeroconf'), \
             patch('zeroconf.ServiceInfo') as mock_si_cls, \
             patch('ezbeq.mdns.socket') as mock_socket:
            mock_socket.gethostname.return_value = 'testhost'
            mock_socket.inet_aton.return_value = b'\x7f\x00\x00\x01'
            mock_sock = MagicMock()
            mock_sock.getsockname.return_value = ('192.168.1.100', 0)
            mock_socket.socket.return_value = mock_sock
            mock_socket.AF_INET = 2
            mock_socket.SOCK_DGRAM = 2

            from ezbeq.mdns import MdnsService
            svc = MdnsService(port=9968, version='2.5.0')

            call_kwargs = mock_si_cls.call_args[1]
            assert call_kwargs['properties']['path'] == '/api'
            assert call_kwargs['properties']['version'] == '2.5.0'

    def test_unregister_closes_zeroconf(self):
        with patch('zeroconf.Zeroconf') as mock_zc_cls, \
             patch('zeroconf.ServiceInfo'), \
             patch('ezbeq.mdns.socket') as mock_socket:
            mock_socket.gethostname.return_value = 'testhost'
            mock_socket.inet_aton.return_value = b'\x7f\x00\x00\x01'
            mock_sock = MagicMock()
            mock_sock.getsockname.return_value = ('192.168.1.100', 0)
            mock_socket.socket.return_value = mock_sock
            mock_socket.AF_INET = 2
            mock_socket.SOCK_DGRAM = 2

            from ezbeq.mdns import MdnsService
            svc = MdnsService(port=8080, version='1.0')
            svc.unregister()

            mock_zc_cls.return_value.unregister_service.assert_called_once()
            mock_zc_cls.return_value.close.assert_called_once()

    def test_unregister_idempotent(self):
        with patch('zeroconf.Zeroconf') as mock_zc_cls, \
             patch('zeroconf.ServiceInfo'), \
             patch('ezbeq.mdns.socket') as mock_socket:
            mock_socket.gethostname.return_value = 'testhost'
            mock_socket.inet_aton.return_value = b'\x7f\x00\x00\x01'
            mock_sock = MagicMock()
            mock_sock.getsockname.return_value = ('192.168.1.100', 0)
            mock_socket.socket.return_value = mock_sock
            mock_socket.AF_INET = 2
            mock_socket.SOCK_DGRAM = 2

            from ezbeq.mdns import MdnsService
            svc = MdnsService(port=8080, version='1.0')
            svc.unregister()
            svc.unregister()  # second call should not raise

    def test_registration_failure_leaves_service_degraded(self):
        with patch('zeroconf.Zeroconf') as mock_zc_cls, \
             patch('zeroconf.ServiceInfo'), \
             patch('ezbeq.mdns.socket') as mock_socket:
            mock_socket.gethostname.return_value = 'testhost'
            mock_socket.inet_aton.return_value = b'\x7f\x00\x00\x01'
            mock_sock = MagicMock()
            mock_sock.getsockname.return_value = ('192.168.1.100', 0)
            mock_socket.socket.return_value = mock_sock
            mock_socket.AF_INET = 2
            mock_socket.SOCK_DGRAM = 2
            mock_zc_cls.return_value.register_service.side_effect = OSError('Network unavailable')

            from ezbeq.mdns import MdnsService
            svc = MdnsService(port=8080, version='1.0')  # should not raise
            svc.unregister()  # should not raise even though registration failed

    def test_custom_name(self):
        with patch('zeroconf.Zeroconf'), \
             patch('zeroconf.ServiceInfo') as mock_si_cls, \
             patch('ezbeq.mdns.socket') as mock_socket:
            mock_socket.gethostname.return_value = 'testhost'
            mock_socket.inet_aton.return_value = b'\x7f\x00\x00\x01'
            mock_sock = MagicMock()
            mock_sock.getsockname.return_value = ('192.168.1.100', 0)
            mock_socket.socket.return_value = mock_sock
            mock_socket.AF_INET = 2
            mock_socket.SOCK_DGRAM = 2

            from ezbeq.mdns import MdnsService, SERVICE_TYPE
            svc = MdnsService(port=8080, version='1.0', name='my-ezbeq')

            call_args = mock_si_cls.call_args
            assert call_args[0][1] == f'my-ezbeq.{SERVICE_TYPE}'


class TestMdnsConfig:

    def test_mdns_disabled_by_default(self, httpserver, tmp_path):
        from conftest import MinidspSpyConfig
        cfg = MinidspSpyConfig(httpserver.host, httpserver.port, tmp_path)
        assert cfg.is_mdns_enabled is False

    def test_mdns_name_default_none(self, httpserver, tmp_path):
        from conftest import MinidspSpyConfig
        cfg = MinidspSpyConfig(httpserver.host, httpserver.port, tmp_path)
        assert cfg.mdns_name is None
