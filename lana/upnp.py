"""Ouverture automatique des ports sur la box par UPnP (IGD), bibliothèque standard uniquement.

Quand un serveur tourne, LANa demande à la box de rediriger ses ports vers cette machine ; quand il s'arrête,
la redirection est retirée. Les redirections ont une durée de vie (LEASE_SECONDS) et sont renouvelées tant que
le serveur tourne : un serveur arrêté hors de LANa ne garde pas ses ports ouverts indéfiniment.
"""
import ipaddress
import socket
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

SSDP_ADDR = ("239.255.255.250", 1900)
SEARCH_TARGETS = ("urn:schemas-upnp-org:device:InternetGatewayDevice:1",
                  "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
                  "urn:schemas-upnp-org:service:WANIPConnection:1")
SERVICES = ("urn:schemas-upnp-org:service:WANIPConnection:2",
            "urn:schemas-upnp-org:service:WANIPConnection:1",
            "urn:schemas-upnp-org:service:WANPPPConnection:1")
LEASE_SECONDS = 3600
RENEW_SECONDS = 600
RETRY_DISCOVERY_SECONDS = 60
DESCRIPTION = "LANa "      # suivi de l'identifiant du serveur : permet de retrouver nos redirections
ONLY_PERMANENT = 725       # codes d'erreur UPnP IGD
CONFLICT = 718

_lock = threading.RLock()
_wake = threading.Event()
_gateway = None
_gateway_checked = 0.0
_gateway_error = ""
_mapped = {}               # id du serveur -> {(port, proto)}
_state = {}                # id du serveur -> {"state", "message"}
_cleaned = False
_external_ip = ""          # adresse Internet de la box, relue à chaque synchronisation


class UPnPError(Exception):
    def __init__(self, message, code=0):
        super().__init__(message)
        self.code = code


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _find(node, name):
    for child in node.iter():
        if _local(child.tag) == name:
            return child
    return None


def parse_ssdp(data):
    """Adresse LOCATION d'une réponse SSDP, ou ''."""
    for line in data.decode("latin-1").split("\r\n"):
        key, _, value = line.partition(":")
        if key.strip().lower() == "location":
            return value.strip()
    return ""


def parse_description(xml_bytes, location):
    """(type de service, URL de contrôle) du premier service de connexion WAN de la description, ou None."""
    root = ET.fromstring(xml_bytes)
    base = _find(root, "URLBase")
    base = base.text.strip() if base is not None and base.text else location
    found = {}
    for service in root.iter():
        if _local(service.tag) != "service":
            continue
        kind, control = _find(service, "serviceType"), _find(service, "controlURL")
        if kind is not None and control is not None and kind.text and control.text:
            found.setdefault(kind.text.strip(), urllib.parse.urljoin(base, control.text.strip()))
    for kind in SERVICES:
        if kind in found:
            return kind, found[kind]
    return None


def soap_body(service, action, args):
    params = "".join("<%s>%s</%s>" % (k, _escape(v), k) for k, v in args)
    return ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            '<u:%s xmlns:u="%s">%s</u:%s></s:Body></s:Envelope>' % (action, service, params, action)).encode()


def _escape(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def parse_soap(xml_bytes):
    """Champs de la réponse ; lève UPnPError si la box a renvoyé une erreur."""
    root = ET.fromstring(xml_bytes)
    fault = _find(root, "UPnPError")
    if fault is not None:
        code, text = _find(fault, "errorCode"), _find(fault, "errorDescription")
        code = int(code.text) if code is not None and code.text and code.text.strip().isdigit() else 0
        raise UPnPError((text.text or "").strip() if text is not None else "erreur UPnP", code)
    body = _find(root, "Body")
    response = list(body)[0] if body is not None and len(body) else None
    return {_local(c.tag): (c.text or "") for c in response} if response is not None else {}


class Gateway:
    def __init__(self, service, control_url):
        self.service, self.control_url = service, control_url
        self.host = urllib.parse.urlparse(control_url).hostname
        self.permanent_only = False
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:   # interface qui mène à la box
            sock.connect((self.host, 1900))
            self.local_ip = sock.getsockname()[0]

    def call(self, action, args=()):
        req = urllib.request.Request(self.control_url, data=soap_body(self.service, action, args), method="POST", headers={
            "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": '"%s#%s"' % (self.service, action)})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return parse_soap(resp.read())
        except urllib.error.HTTPError as ex:   # les erreurs UPnP arrivent en HTTP 500 avec un corps SOAP
            body = ex.read()
            if body:
                parse_soap(body)
            raise UPnPError("la box a répondu HTTP %s" % ex.code)
        except (OSError, ET.ParseError) as ex:
            raise UPnPError("box injoignable (%s)" % ex)

    def external_ip(self):
        return self.call("GetExternalIPAddress").get("NewExternalIPAddress", "")

    def add(self, port, proto, description):
        def attempt(lease):
            self.call("AddPortMapping", [
                ("NewRemoteHost", ""), ("NewExternalPort", port), ("NewProtocol", proto.upper()),
                ("NewInternalPort", port), ("NewInternalClient", self.local_ip), ("NewEnabled", 1),
                ("NewPortMappingDescription", description), ("NewLeaseDuration", lease)])
        try:
            attempt(0 if self.permanent_only else LEASE_SECONDS)
        except UPnPError as ex:
            if ex.code != ONLY_PERMANENT:
                raise
            self.permanent_only = True   # vieille box : redirection permanente, retirée à l'arrêt du serveur
            attempt(0)

    def delete(self, port, proto):
        self.call("DeletePortMapping", [("NewRemoteHost", ""), ("NewExternalPort", port), ("NewProtocol", proto.upper())])

    def mappings(self, limit=128):
        """Redirections existantes : liste de dicts (port, proto, client, description)."""
        out = []
        for index in range(limit):
            try:
                entry = self.call("GetGenericPortMappingEntry", [("NewPortMappingIndex", index)])
            except UPnPError:
                break
            out.append({"port": int(entry.get("NewExternalPort") or 0), "proto": entry.get("NewProtocol", "").lower(),
                        "client": entry.get("NewInternalClient", ""), "description": entry.get("NewPortMappingDescription", "")})
        return out


def discover(timeout=3):
    """Première box UPnP qui répond sur le réseau local, ou lève UPnPError."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        for target in SEARCH_TARGETS:
            sock.sendto(('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\n'
                         'MX: 2\r\nST: %s\r\n\r\n' % target).encode(), SSDP_ADDR)
        seen = set()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _addr = sock.recvfrom(8192)
            except socket.timeout:
                break
            except OSError as ex:
                raise UPnPError("recherche de la box impossible (%s)" % ex)
            location = parse_ssdp(data)
            if not location or location in seen or urllib.parse.urlparse(location).scheme != "http":
                continue
            seen.add(location)
            try:
                with urllib.request.urlopen(location, timeout=5) as resp:
                    found = parse_description(resp.read(), location)
            except (OSError, ET.ParseError):
                continue
            if found:
                return Gateway(*found)
    raise UPnPError("aucune box UPnP n'a répondu : l'UPnP est peut-être désactivé dans les réglages de la box")


def gateway():
    """Box en cache ; nouvelle recherche au plus toutes les RETRY_DISCOVERY_SECONDS en cas d'échec."""
    global _gateway, _gateway_checked, _gateway_error
    with _lock:
        if _gateway is None and time.time() - _gateway_checked > RETRY_DISCOVERY_SECONDS:
            _gateway_checked = time.time()
            try:
                _gateway, _gateway_error = discover(), ""
            except UPnPError as ex:
                _gateway_error = str(ex)
        if _gateway is None:
            raise UPnPError(_gateway_error)
        return _gateway


def is_public(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_global


def _wanted(inst):
    try:
        if not inst.upnp_enabled() or not inst.meta().get("installed") or not inst.running():
            return set()
        return {(p["port"], p["proto"]) for p in inst.ports()}
    except Exception:   # noqa: BLE001 - serveur supprimé ou config illisible pendant la synchronisation
        return set()


def _clean_leftovers(gw, wanted):
    """Retire les redirections LANa d'un lancement précédent qui ne servent plus (au premier passage seulement)."""
    global _cleaned
    if _cleaned:
        return
    _cleaned = True
    for entry in gw.mappings():
        key = (entry["port"], entry["proto"])
        if entry["description"].startswith(DESCRIPTION) and entry["client"] == gw.local_ip and key not in wanted:
            try:
                gw.delete(*key)
            except UPnPError:
                pass


def sync(instances):
    """Aligne les redirections de la box sur les serveurs en marche."""
    global _external_ip
    with _lock:
        wanted = {inst.id: _wanted(inst) for inst in instances}
        if not any(wanted.values()) and not any(_mapped.values()):
            for inst_id in list(_state):
                if not wanted.get(inst_id):
                    _state.pop(inst_id, None)
            return
        try:
            gw = gateway()
        except UPnPError as ex:
            for inst_id, ports in wanted.items():
                if ports:
                    _state[inst_id] = {"state": "error", "message": str(ex)}
            return
        try:
            _external_ip = gw.external_ip()
        except UPnPError:
            _external_ip = ""
        _clean_leftovers(gw, set().union(*wanted.values()) if wanted else set())
        for inst_id in set(_mapped) - set(wanted):   # serveur supprimé
            wanted[inst_id] = set()
        for inst_id, ports in wanted.items():
            done = _mapped.setdefault(inst_id, set())
            for key in sorted(done - ports):
                try:
                    gw.delete(*key)
                except UPnPError:
                    pass   # déjà retirée ou expirée
                done.discard(key)
            errors = []
            for key in sorted(ports):
                try:
                    gw.add(key[0], key[1], DESCRIPTION + inst_id)
                    done.add(key)
                except UPnPError as ex:
                    if ex.code == CONFLICT:
                        errors.append("le port %s/%s est déjà redirigé vers une autre machine" % (key[0], key[1].upper()))
                    else:
                        errors.append("%s/%s : %s" % (key[0], key[1].upper(), ex))
            if not ports:
                _mapped.pop(inst_id, None)
                _state.pop(inst_id, None)
            elif errors:
                _state[inst_id] = {"state": "error", "message": " ; ".join(errors)}
            else:
                _state[inst_id] = {"state": "ok", "message": ""}


def poke():
    """Demande une synchronisation immédiate (serveur démarré, arrêté ou réglage changé)."""
    _wake.set()


def status(inst):
    """État affiché dans l'interface pour un serveur."""
    out = {"enabled": inst.upnp_enabled(), "state": "off", "message": "", "external_ip": ""}
    if not out["enabled"]:
        return out
    with _lock:
        state = _state.get(inst.id)
        external = _external_ip
    if state:
        out.update(state)
    elif _wanted(inst):
        out["state"] = "pending"
    if out["state"] == "ok" and external:
        out["external_ip"] = external
        if not is_public(external):
            out["state"] = "error"
            out["message"] = ("la box a l'adresse %s, qui n'est pas une adresse Internet : elle est derrière un autre routeur "
                              "ou chez un fournisseur qui partage les adresses (CGNAT). Les joueurs extérieurs ne pourront "
                              "pas se connecter sans régler ce routeur ou demander une IP publique." % out["external_ip"])
    return out


def maintain_forever(list_instances):
    """Les redirections suivent les serveurs, pas LANa : si LANa s'arrête, les serveurs (qui continuent de tourner)
    gardent leurs ports jusqu'à la fin du bail, et le prochain lancement de LANa reprend la main."""
    while True:
        delay = RENEW_SECONDS
        try:
            sync(list_instances())
        except Exception as ex:   # noqa: BLE001 - l'UPnP ne doit jamais arrêter LANa
            print("UPnP : %s" % ex)
            delay = RETRY_DISCOVERY_SECONDS
        _wake.wait(delay)
        _wake.clear()
