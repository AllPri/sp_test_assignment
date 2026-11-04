"""Выполняет ограниченные HTTP-запросы и не раскрывает ключи в сообщениях ошибок."""

import json
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .models import ServiceError


class NoRedirect(HTTPRedirectHandler):
    """Не позволяет незаметно передать запрос или ключ на другой адрес."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Передаёт перенаправление вызывающему коду как HTTP-ошибку."""
        return None


def request_bytes(url, *, payload=None, headers=None, timeout=45, limit=2_000_000):
    """Ограничивает ожидание и размер ответа; не выполняет автоматических повторов."""
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers=headers or {})
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            result = response.read(limit + 1)
            if len(result) > limit:
                raise ServiceError("Ответ сервера превысил допустимый размер.")
            return result, response.headers
    except HTTPError as exc:
        exc.close()
        explanations = {
            401: "неверный ключ или отсутствует авторизация",
            403: "доступ запрещён",
            404: "страница, модель или адрес API не найдены",
            429: "исчерпан лимит запросов или квота",
        }
        reason = explanations.get(exc.code, "сервер отклонил запрос")
        raise ServiceError(f"HTTP {exc.code}: {reason}. Проверьте настройки.") from None
    except (URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise ServiceError("Сервер недоступен или истекло время ожидания.") from None


def request_json(url, *, payload, headers, timeout):
    """Разбирает только JSON; тело ошибочного ответа не выводит пользователю."""
    raw, _ = request_bytes(url, payload=payload, headers=headers, timeout=timeout)
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise ServiceError("Сервер вернул ответ, который не является JSON.") from None
