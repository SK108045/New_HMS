"""Isolated regressions. Any accidental external gateway call fails immediately."""
import socket


def _deny_network(*args, **kwargs):
    raise AssertionError('Regression tests may not contact external services')


socket.socket.connect = _deny_network
