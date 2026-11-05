"""Explicit Linux NetworkManager profiles; TLS and exact receipts stay mandatory."""
import http.client
import re
import socket
import ssl
import subprocess
import time
import urllib.request
import uuid


def bound_connection(interface):
    def connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        error = None
        for family, kind, protocol, unused, endpoint in socket.getaddrinfo(address[0], address[1], 0, socket.SOCK_STREAM):
            stream = socket.socket(family, kind, protocol)
            try:
                stream.settimeout(timeout)
                stream.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode() + b'\0')
                stream.connect(endpoint)
                return stream
            except OSError as failure:
                stream.close()
                error = failure
        raise error or OSError('No address for backhaul endpoint')
    return connect


class BoundHTTPS(urllib.request.HTTPSHandler):
    def __init__(self, interface, context=None):
        self.tls_context = context if context is not None else ssl.create_default_context()
        if not self.tls_context.check_hostname or self.tls_context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError('Verified certificates and hostnames are required')
        super().__init__(context=self.tls_context)
        self.interface = interface

    def https_open(self, request):
        def factory(host, **kwargs):
            connection = http.client.HTTPSConnection(host, context=self.tls_context, **kwargs)
            connection._create_connection = bound_connection(self.interface)
            return connection
        return self.do_open(factory, request)


class Backhaul:
    def __init__(self, config, runner=subprocess.run, clock=time.monotonic):
        self.links = config['links']
        if not isinstance(self.links, list) or not 1 <= len(self.links) <= 4:
            raise ValueError('One to four explicit backhaul links required')
        self.runner, self.clock = runner, clock
        self.activate = config.get('allow_network_changes') is True
        self.failures, self.status = {}, dict(state='NOT_CONNECTED', medium=None)
        self.activated = {}
        identities = set()
        for link in self.links:
            if link.get('medium') not in ('ethernet', 'cellular') or not re.fullmatch('[A-Za-z0-9_.-]{1,15}', link.get('interface', '')):
                raise ValueError('Invalid explicit Linux backhaul interface')
            if link['interface'] in identities:
                raise ValueError('Duplicate backhaul interface')
            identities.add(link['interface'])
            if str(uuid.UUID(link['connection_uuid'])) != link['connection_uuid']:
                raise ValueError('Canonical NetworkManager profile UUID required')

    def open(self, request, timeout):
        from .uplink import NoRedirect
        errors = []
        for link in self.links:
            interface = link['interface']
            if self.failures.get(interface, 0) > self.clock():
                continue
            try:
                if self.activate and self.activated.get(interface, -1000) + 60 <= self.clock():
                    self.runner(['nmcli', '--wait', '0', 'connection', 'up', 'uuid', link['connection_uuid'], 'ifname', interface],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=2, check=True, shell=False)
                    self.activated[interface] = self.clock()
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), BoundHTTPS(interface))
                response = opener.open(request, timeout=timeout)
                self.status = dict(state='TLS_RESPONSE', medium=link['medium'], interface=interface)
                return response
            except (OSError, ValueError, subprocess.SubprocessError, AttributeError) as error:
                self.failures[interface] = self.clock() + 30
                errors.append(interface + ':' + type(error).__name__)
        self.status = dict(state='OFFLINE', medium=None, errors=errors)
        raise OSError('No authenticated backhaul response: ' + ','.join(errors))
