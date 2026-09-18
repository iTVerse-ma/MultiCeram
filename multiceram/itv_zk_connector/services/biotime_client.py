# -*- coding: utf-8 -*-
"""Client HTTP pour l'API REST de ZKTeco BioTime 9.x.

Aucune dépendance à l'ORM : la session HTTP est injectable, ce qui permet de
tester le client avec des réponses enregistrées (tests/fixtures) sans serveur.
"""
import logging
import random
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

_logger = logging.getLogger(__name__)

AUTH_PATHS = {
    'token': 'api-token-auth/',
    'jwt': 'jwt-api-token-auth/',
}
AUTH_HEADER_PREFIX = {
    'token': 'Token',
    'jwt': 'JWT',
}
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class BioTimeError(Exception):
    """Erreur renvoyée par BioTime (code applicatif non nul, requête rejetée)."""


class BioTimeUnavailable(BioTimeError):
    """BioTime injoignable, en erreur serveur, ou réponse non JSON (page d'erreur HTML)."""


class BioTimeAuthError(BioTimeError):
    """Identifiants refusés, ou licence sans module API (HTTP 403)."""


class BioTimeReadOnlyError(BioTimeError):
    """Écriture refusée : la connexion est en lecture seule."""


class BioTimeClient:

    def __init__(self, base_url, *, auth_mode='token', username=None, password=None, token=None,
                 read_only=True, session=None, timeout=(5, 60), max_retries=3, backoff=1.0,
                 sleep=time.sleep, on_token=None, max_pages=10000):
        if not base_url:
            raise ValueError("L'URL du serveur BioTime est obligatoire.")
        self.base_url = base_url if base_url.endswith('/') else base_url + '/'
        self.auth_mode = auth_mode
        self.username = username
        self.password = password
        self.token = token
        self.read_only = read_only
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.sleep = sleep
        self.on_token = on_token
        self.max_pages = max_pages
        self.calls = 0
        if auth_mode == 'basic':
            self.session.auth = (username or '', password or '')

    # -- URLs -------------------------------------------------------------------

    def _url(self, path_or_url):
        if path_or_url.startswith(('http://', 'https://')):
            return self._rebase(path_or_url)
        return urljoin(self.base_url, path_or_url.lstrip('/'))

    def _rebase(self, url):
        """Remplace l'hôte d'une URL « next » par celui de la connexion configurée.

        BioTime construit ses liens de pagination avec le nom d'hôte qu'il voit
        lui-même (IP interne, proxy), souvent injoignable depuis Odoo.
        """
        base = urlsplit(self.base_url)
        parts = urlsplit(url)
        return urlunsplit((base.scheme, base.netloc, parts.path, parts.query, ''))

    # -- Authentification ---------------------------------------------------------

    def authenticate(self):
        """Obtient un jeton. Autorisé même en lecture seule : ce POST n'écrit rien."""
        if self.auth_mode == 'basic':
            return None
        response = self._send(
            'POST', self._url(AUTH_PATHS[self.auth_mode]),
            json={'username': self.username or '', 'password': self.password or ''},
            retry=False,
        )
        if response.status_code in (400, 401, 403):
            raise BioTimeAuthError("BioTime a refusé les identifiants (HTTP %s)." % response.status_code)
        if response.status_code >= 400:
            raise BioTimeUnavailable("Authentification BioTime impossible (HTTP %s)." % response.status_code)
        data = self._decode(response)
        token = data.get('token') if isinstance(data, dict) else None
        if not token:
            raise BioTimeAuthError("Réponse d'authentification BioTime sans jeton.")
        self.token = token
        if self.on_token:
            self.on_token(token)
        return token

    def _headers(self):
        headers = {'Accept': 'application/json'}
        if self.auth_mode in AUTH_HEADER_PREFIX and self.token:
            headers['Authorization'] = '%s %s' % (AUTH_HEADER_PREFIX[self.auth_mode], self.token)
        return headers

    # -- Requêtes ---------------------------------------------------------------------

    def get(self, path, params=None):
        return self.request('GET', path, params=params)

    def request(self, method, path_or_url, params=None, json=None):
        method = method.upper()
        if self.read_only and method != 'GET':
            raise BioTimeReadOnlyError(
                "Connexion BioTime en lecture seule : %s %s refusé." % (method, path_or_url))
        if self.auth_mode != 'basic' and not self.token:
            self.authenticate()
        url = self._url(path_or_url)
        retry = method == 'GET'
        response = self._send(method, url, params=params, json=json, retry=retry)
        if response.status_code in (401, 403) and self.auth_mode != 'basic':
            # Jeton expiré ou révoqué : une seule ré-authentification.
            self.authenticate()
            response = self._send(method, url, params=params, json=json, retry=retry)
        if response.status_code in (401, 403):
            raise BioTimeAuthError(
                "BioTime refuse l'accès à %s (HTTP %s) : droits de l'utilisateur API ou licence sans module API."
                % (urlsplit(url).path, response.status_code))
        if response.status_code in RETRYABLE_STATUS:
            raise BioTimeUnavailable("BioTime indisponible (HTTP %s)." % response.status_code)
        if response.status_code >= 400:
            raise BioTimeError("Requête BioTime rejetée (HTTP %s) : %s"
                               % (response.status_code, (response.text or '')[:200]))
        return self._decode(response)

    def _send(self, method, url, params=None, json=None, retry=True):
        attempts = self.max_retries if retry else 1
        for attempt in range(1, attempts + 1):
            self.calls += 1
            try:
                response = self.session.request(
                    method, url, params=params, json=json, headers=self._headers(), timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= attempts:
                    raise BioTimeUnavailable("BioTime injoignable : %s" % exc) from exc
                self._wait(attempt)
                continue
            if response.status_code in RETRYABLE_STATUS and attempt < attempts:
                self._wait(attempt)
                continue
            return response

    def _wait(self, attempt):
        delay = self.backoff * (2 ** (attempt - 1))
        self.sleep(delay + random.uniform(0, delay / 2))

    @staticmethod
    def _decode(response):
        try:
            data = response.json()
        except ValueError as exc:
            # Service BioTime arrêté : page d'erreur HTML servie en HTTP 200.
            raise BioTimeUnavailable("Réponse BioTime non JSON (page d'erreur ?).") from exc
        if isinstance(data, dict) and data.get('code') not in (None, 0, '0'):
            raise BioTimeError("BioTime a répondu code=%s : %s"
                               % (data.get('code'), data.get('msg') or data.get('message') or ''))
        return data

    # -- Pagination ---------------------------------------------------------------------

    def iter_pages(self, path, params=None):
        """Parcourt une liste paginée en suivant « next » ; rend chaque page."""
        page = self.get(path, params=params)
        seen = set()
        pages = 1
        while True:
            if not isinstance(page, dict) or not isinstance(page.get('data'), list):
                raise BioTimeError("Réponse BioTime inattendue : liste « data » absente.")
            yield page
            next_url = page.get('next')
            if not next_url:
                return
            url = self._rebase(next_url)
            if url in seen:
                raise BioTimeError("Pagination BioTime en boucle (%s)." % url)
            if pages >= self.max_pages:
                raise BioTimeError("Pagination BioTime interrompue après %s pages." % pages)
            seen.add(url)
            page = self.get(url)
            pages += 1

    def iter_records(self, path, params=None):
        for page in self.iter_pages(path, params):
            yield from page['data']

    def count(self, path, params=None, page_size_param='page_size'):
        """Nombre total d'éléments d'une liste, en ne rapatriant qu'un élément."""
        params = dict(params or {})
        params[page_size_param] = 1
        page = self.get(path, params=params)
        return int((page or {}).get('count') or 0)
