import logging
import socket

logger = logging.getLogger('ezbeq.mdns')

SERVICE_TYPE = '_ezbeq._tcp.local.'


class MdnsService:
    """Advertises ezBEQ via mDNS/Bonjour so clients can discover it on the local network."""

    def __init__(self, port: int, version: str, name: str | None = None):
        from zeroconf import Zeroconf, ServiceInfo
        self.__zeroconf = Zeroconf()
        hostname = socket.gethostname()
        service_name = name or f'ezbeq-{hostname}'
        self.__info = ServiceInfo(
            SERVICE_TYPE,
            f'{service_name}.{SERVICE_TYPE}',
            addresses=[socket.inet_aton(self._get_local_ip())],
            port=port,
            properties={
                'path': '/api',
                'version': version,
            },
            server=f'{hostname}.local.',
        )
        try:
            self.__zeroconf.register_service(self.__info)
            logger.info(f'mDNS: advertising {service_name} on port {port} as {SERVICE_TYPE}')
        except Exception:
            logger.exception('mDNS: failed to register service, continuing without mDNS')
            self.__zeroconf = None

    @staticmethod
    def _get_local_ip() -> str:
        """Get the local IP address that's reachable on the LAN."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('10.255.255.255', 1))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return '127.0.0.1'

    def unregister(self):
        """Unregister the service and close zeroconf."""
        if self.__zeroconf:
            try:
                self.__zeroconf.unregister_service(self.__info)
                self.__zeroconf.close()
                logger.info('mDNS: service unregistered')
            except Exception:
                logger.exception('mDNS: error during shutdown')
            self.__zeroconf = None
