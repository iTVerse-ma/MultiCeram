# -*- coding: utf-8 -*-
import requests

from odoo.tests.common import BaseCase, tagged

from ..services.biotime_client import (
    BioTimeAuthError,
    BioTimeClient,
    BioTimeError,
    BioTimeReadOnlyError,
    BioTimeUnavailable,
)
from .common import FakeResponse, FakeSession, load_fixture

BASE_URL = 'http://biotime.test:8090/'


def make_client(session, **kwargs):
    kwargs.setdefault('username', 'api')
    kwargs.setdefault('password', 'secret')
    return BioTimeClient(BASE_URL, session=session, sleep=lambda seconds: None, **kwargs)


@tagged('post_install', '-at_install', 'itv_zk')
class TestBioTimeClient(BaseCase):

    def test_token_is_obtained_then_sent(self):
        session = FakeSession(script=[
            FakeResponse(payload={'token': 'abc'}),
            FakeResponse(payload=load_fixture('terminals.json')),
        ])
        tokens = []
        make_client(session, on_token=tokens.append).get('iclock/api/terminals/')
        self.assertEqual((session.calls[0]['method'], session.calls[0]['url']), ('POST', BASE_URL + 'api-token-auth/'))
        self.assertEqual(session.calls[1]['headers']['Authorization'], 'Token abc')
        self.assertEqual(tokens, ['abc'])

    def test_expired_token_reauthenticates_once(self):
        session = FakeSession(script=[
            FakeResponse(401, payload={'detail': 'Invalid token.'}),
            FakeResponse(payload={'token': 'fresh'}),
            FakeResponse(payload=load_fixture('terminals.json')),
        ])
        data = make_client(session, token='stale').get('iclock/api/terminals/')
        self.assertEqual(data['count'], 2)
        self.assertEqual(session.calls[2]['headers']['Authorization'], 'Token fresh')

    def test_forbidden_after_reauthentication_is_an_auth_error(self):
        session = FakeSession(script=[
            FakeResponse(403, payload={}),
            FakeResponse(payload={'token': 'second'}),
            FakeResponse(403, payload={}),
        ])
        with self.assertRaises(BioTimeAuthError):
            make_client(session, token='first').get('personnel/api/employees/')

    def test_connection_error_is_retried(self):
        session = FakeSession(script=[
            requests.ConnectionError("réseau coupé"),
            FakeResponse(payload=load_fixture('terminals.json')),
        ])
        client = make_client(session, token='t')
        self.assertEqual(client.get('iclock/api/terminals/')['count'], 2)
        self.assertEqual(client.calls, 2)

    def test_server_error_after_all_retries_is_unavailable(self):
        session = FakeSession(script=[FakeResponse(503, text='Service Unavailable', content_type='text/html')] * 3)
        client = make_client(session, token='t')
        with self.assertRaises(BioTimeUnavailable):
            client.get('iclock/api/terminals/')
        self.assertEqual(client.calls, 3)

    def test_html_page_with_http_200_is_unavailable(self):
        session = FakeSession(script=[
            FakeResponse(200, text='<html><body>Service stopped</body></html>', content_type='text/html'),
        ])
        with self.assertRaises(BioTimeUnavailable):
            make_client(session, token='t').get('iclock/api/terminals/')

    def test_error_code_in_envelope_is_raised(self):
        session = FakeSession(script=[FakeResponse(payload={'code': 1, 'msg': 'Permission denied', 'data': []})])
        with self.assertRaises(BioTimeError):
            make_client(session, token='t').get('iclock/api/terminals/')

    def test_read_only_blocks_writes_but_not_login(self):
        session = FakeSession(script=[FakeResponse(payload={'token': 'abc'})])
        client = make_client(session)
        client.authenticate()
        with self.assertRaises(BioTimeReadOnlyError):
            client.request('POST', 'att/api/manuallogs/', json={'employee': 1})
        self.assertEqual(len(session.calls), 1)

    def test_pagination_follows_next_on_the_configured_host(self):
        session = FakeSession(script=[
            FakeResponse(payload=load_fixture('transactions_page1.json')),
            FakeResponse(payload=load_fixture('transactions_page2.json')),
        ])
        records = list(make_client(session, token='t').iter_records('iclock/api/transactions/', {'page_size': 2}))
        self.assertEqual([record['id'] for record in records], [1001, 1002, 1003])
        self.assertTrue(session.calls[1]['url'].startswith(BASE_URL + 'iclock/api/transactions/'))

    def test_pagination_loop_is_detected(self):
        page = load_fixture('transactions_page1.json')
        session = FakeSession(script=[FakeResponse(payload=page)] * 3)
        with self.assertRaises(BioTimeError):
            list(make_client(session, token='t').iter_records('iclock/api/transactions/'))

    def test_basic_auth_needs_no_token(self):
        session = FakeSession(script=[FakeResponse(payload=load_fixture('terminals.json'))])
        make_client(session, auth_mode='basic').get('iclock/api/terminals/')
        self.assertEqual(session.auth, ('api', 'secret'))
        self.assertNotIn('Authorization', session.calls[0]['headers'])
