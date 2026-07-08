from __future__ import annotations

import base64
import re
import ssl
import xml.etree.ElementTree as ET
from urllib import error, request
from typing import Any

import config


class ObixClient:
    def __init__(self) -> None:
        self._auth_header = self._build_auth_header()
        self._ssl_context = None
        if config.OBIX_USE_HTTPS and not config.OBIX_VERIFY_SSL:
            self._ssl_context = ssl._create_unverified_context()

    @property
    def enabled(self) -> bool:
        return not config.SIMULATION_MODE

    def _base_url(self) -> str:
        protocol = "https" if config.OBIX_USE_HTTPS else "http"
        root = config.OBIX_ROOT_PATH.rstrip("/")
        return f"{protocol}://{config.OBIX_IP}:{config.OBIX_PORT}{root}"

    def _point_url(self, point_name: str) -> str:
        """Build oBIX URL for a point under ModbusAsyncNetwork/IO$2d22U/points/"""
        encoded = self._niagara_encode(point_name)
        return (
            f"{self._base_url()}/config/Drivers/ModbusAsyncNetwork/"
            f"IO%242d22U/points/{encoded}/"
        )

    @staticmethod
    def _niagara_encode(name: str) -> str:
        """Encode a point name in Niagara $uXXXX format."""
        result = []
        for ch in name:
            code = ord(ch)
            if code > 127:
                result.append(f"%24u{code:04x}")
            elif ch == "$":
                result.append("%24")
            elif ch == " ":
                result.append("%20")
            elif ch.isalnum() or ch in ("_", "-"):
                result.append(ch)
            else:
                result.append(f"%24{code:02x}")
        return "".join(result)

    def read_point(self, point_name: str) -> float:
        raw = self._read_point_raw(point_name)
        return float(raw)

    def _read_point_raw(self, point_name: str) -> str:
        """Read a point and return the raw string value from XML."""
        response_text = self._send_request(
            url=self._point_url(point_name),
            method="GET",
            headers={"Accept": "application/xml"},
        )
        m = re.search(r'\bval="([^"]+)"', response_text)
        if m:
            return m.group(1)
        raise ValueError("oBIX response did not contain a val attribute")

    def write_point(self, point_name: str, value: Any, kind: str) -> None:
        # Writable oBIX points are controlled through their set action.
        set_suffix = "/set/" if kind in {"bool", "real", "int"} else ""
        payload = self._build_payload(value=value, kind=kind)
        self._send_request(
            url=self._point_url(point_name).rstrip("/") + set_suffix,
            method="POST",
            headers={"Content-Type": "application/xml", "Accept": "application/xml"},
            data=payload.encode("utf-8"),
        )

    def read_device_points(self) -> dict[str, Any]:
        states: dict[str, Any] = {}
        for device_name, meta in config.DEVICE_POINTS.items():
            try:
                raw_value = self._read_point_raw(meta["point_name"])
                if meta["kind"] == "bool":
                    states[device_name] = raw_value.lower() == "true"
                else:
                    states[device_name] = float(raw_value)
            except Exception as exc:
                states[device_name] = {"error": str(exc)}
        return states

    def _parse_value(self, xml_text: str) -> str:
        m = re.search(r'\bval="([^"]+)"', xml_text)
        if m:
            return m.group(1)
        raise ValueError("oBIX response did not contain a val attribute")

    def _build_payload(self, value: Any, kind: str) -> str:
        if kind == "bool":
            bool_value = str(bool(value)).lower()
            return f'<bool val="{bool_value}"/>'
        if kind == "real":
            return f'<real val="{float(value)}"/>'
        if kind == "int":
            return f'<int name="out" val="{int(value)}"/>'
        raise ValueError(f"Unsupported oBIX value kind: {kind}")

    def _build_auth_header(self) -> str:
        raw = f"{config.OBIX_USERNAME}:{config.OBIX_PASSWORD}".encode("utf-8")
        token = base64.b64encode(raw).decode("ascii")
        return f"Basic {token}"

    def _send_request(
        self,
        url: str,
        method: str,
        headers: dict[str, str],
        data: bytes | None = None,
    ) -> str:
        request_headers = {"Authorization": self._auth_header, **headers}
        req = request.Request(url=url, data=data, headers=request_headers, method=method)
        try:
            with request.urlopen(
                req,
                timeout=config.OBIX_TIMEOUT_SECONDS,
                context=self._ssl_context,
            ) as response:
                return response.read().decode("utf-8")
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"oBIX request failed with HTTP {exc.code}: {body[:200]}") from exc
        except error.URLError as exc:
            if self._should_retry_without_ssl_verify(exc):
                with request.urlopen(
                    req,
                    timeout=config.OBIX_TIMEOUT_SECONDS,
                    context=ssl._create_unverified_context(),
                ) as response:
                    return response.read().decode("utf-8")
            raise

    def _should_retry_without_ssl_verify(self, exc: error.URLError) -> bool:
        if not config.OBIX_USE_HTTPS:
            return False
        message = str(exc).lower()
        return "certificate_verify_failed" in message or "self-signed certificate" in message
