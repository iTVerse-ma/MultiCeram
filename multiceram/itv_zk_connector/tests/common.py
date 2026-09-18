# -*- coding: utf-8 -*-
"""Doublures HTTP pour tester le connecteur sans serveur BioTime.

Les réponses reprennent le format des manuels officiels ZKTeco (BioTime 9.5 API
User Manual, BioTimeCloud API User Manual), avec des données anonymisées.
"""
import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests

FIXTURES = Path(__file__).parent / 'fixtures'


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


class FakeResponse:

    def __init__(self, status_code=200, payload=None, text=None, content_type='application/json'):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)
        self.headers = {'Content-Type': content_type}

    def json(self):
        if self._payload is None:
            raise requests.JSONDecodeError("Expecting value", self.text or '', 0)
        return self._payload


class FakeSession:
    """Session HTTP scriptée : consomme `script` dans l'ordre, sinon route par (méthode, chemin)."""

    def __init__(self, script=None, routes=None):
        self.script = list(script or [])
        self.routes = routes or {}
        self.calls = []
        self.auth = None

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        parts = urlsplit(url)
        merged = {key: values[0] for key, values in parse_qs(parts.query).items()}
        merged.update(params or {})
        self.calls.append({'method': method, 'url': url, 'params': merged, 'json': json, 'headers': dict(headers or {})})
        if self.script:
            outcome = self.script.pop(0)
        else:
            handler = self.routes[(method, parts.path)]
            outcome = handler(merged) if callable(handler) else handler
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeBioTime:
    """Serveur BioTime simulé pour les tests de synchronisation."""

    def __init__(self):
        self.transaction_pages = [load_fixture('transactions_page1.json'), load_fixture('transactions_page2.json')]
        self.terminals = load_fixture('terminals.json')
        self.departments = load_fixture('departments.json')
        self.employees = load_fixture('employees.json')
        self.day_counts = {}
        self.down = False
        self.session = FakeSession(routes={
            ('GET', '/iclock/api/transactions/'): lambda params: self._respond(self._transactions(params)),
            ('GET', '/iclock/api/terminals/'): lambda params: self._respond(self.terminals),
            ('GET', '/personnel/api/departments/'): lambda params: self._respond(self.departments),
            ('GET', '/personnel/api/employees/'): lambda params: self._respond(self.employees),
        })

    def _respond(self, payload):
        if self.down:
            return requests.ConnectionError("BioTime arrêté")
        return FakeResponse(payload=copy.deepcopy(payload))

    def _transactions(self, params):
        if params.get('page_size') == 1:
            # Requête de comptage de la réconciliation : un jour, un seul élément.
            day = str(params.get('start_time', ''))[:10]
            return {'count': self.day_counts.get(day, 0), 'next': None, 'previous': None, 'msg': '', 'code': 0, 'data': []}
        return self.transaction_pages[1] if params.get('page') == '2' else self.transaction_pages[0]
