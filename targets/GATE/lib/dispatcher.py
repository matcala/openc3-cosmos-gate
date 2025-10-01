import urllib.parse
import json, urllib.request, urllib.error
from openc3.interfaces.protocols.protocol import Protocol
from openc3.config.config_parser import ConfigParser
from openc3.utilities.logger import Logger

class Dispatcher(Protocol):
   """
   A WRITE protocol that inspects the command Packet (pre-encode),
   logs/sends a JSON summary to an external service, then returns
   the same packet to continue the pipeline.
   """

   def __init__(self, rest_endpoint:str, keycloak_identity=None, allow_empty_data=None):
      super().__init__(allow_empty_data)
      # Normalize endpoints like "localhost:8000/authorize" -> "http://localhost:8000/authorize"
      self.rest_endpoint = self._normalize_endpoint(rest_endpoint)
      self.keycloak_identity = keycloak_identity
      self.allow_empty_data = ConfigParser.handle_true_false_none(allow_empty_data)

   def _normalize_endpoint(self, rest_endpoint: str) -> str:
      """
      Ensures rest_endpoint is a proper URL:
      - Adds default scheme (http) if missing.
      - Supports scheme-relative inputs like //host:port/path.
      - Ensures path begins with '/' when a netloc exists.
      """
      if not rest_endpoint:
         raise ValueError("rest_endpoint must be a non-empty string")

      ep = rest_endpoint.strip()

      # If no explicit scheme delimiter is present, add http:// (or http: for scheme-relative)
      if '://' not in ep:
         ep = ('http:' + ep) if ep.startswith('//') else ('http://' + ep)

      parsed = urllib.parse.urlparse(ep)

      # If we have a host:port and a non-empty path, ensure it starts with '/'
      if parsed.netloc and parsed.path and not parsed.path.startswith('/'):
         parsed = parsed._replace(path='/' + parsed.path)

      normalized = urllib.parse.urlunparse(parsed)
      Logger.info(f"Dispatcher: Normalized REST endpoint to {normalized}")
      return normalized

   def write_packet(self, packet):
      """
      Called BEFORE encoding. Returning the Packet continues the write;
      returning self.STOP drops; returning self.DISCONNECT disconnects interface.
      """
      pkt_name = packet.packet_name
      tgt_name = packet.target_name
      stream_id = packet.read_item("STREAM_ID", "RAW") \
            if any(i.name == "STREAM_ID" for i in getattr(packet, "sorted_items", [])) else None
      func_code = packet.read_item("FUNCTION_CODE", "RAW") \
            if any(i.name == "FUNCTION_CODE" for i in getattr(packet, "sorted_items", [])) else None
      
      # Build a summary dictionary
      summary = {
         "keycloak_id": self.keycloak_identity,
         "target": tgt_name,
         "packet": pkt_name,
         "stream_id": stream_id,
         "function_code": func_code
         }
      
      # Convert to JSON
      summary_json = json.dumps(summary).encode('utf-8')
      Logger.info(f"Dispatcher: Prepared packet summary JSON: {summary_json}")
      Logger.info(f"Dispatcher: Sending packet summary to {self.rest_endpoint}")

      # Dispatch the summary and decide whether to continue
      should_continue = self.dispatch_packet(summary_json, packet)
      if not should_continue:
         Logger.warn("Dispatcher: Halting pipeline as dispatch_packet returned False")
         return 'STOP'

      Logger.info("Dispatcher: Packet summary dispatched successfully")
      # IMPORTANT: return the SAME packet to continue the pipeline unchanged
      return packet

   def dispatch_packet(self, summary_json, packet):
      # Send to REST endpoint
      try:
         req = urllib.request.Request(
            self.rest_endpoint,
            data=summary_json,
            headers={'Content-Type': 'application/json'},
            method='POST'  # make POST explicit
         )
         with urllib.request.urlopen(req) as response:
            status = getattr(response, 'status', response.getcode())
            resp_body = response.read().decode('utf-8', errors='replace')
            if 200 <= status < 300:
               Logger.info(f"Dispatcher: Sent packet summary to {self.rest_endpoint} (HTTP {status}), response: {resp_body}")
               return True
            else:
               Logger.error(f"Dispatcher: Non-success status from {self.rest_endpoint}: HTTP {status}, response: {resp_body}")
               return False
      except urllib.error.HTTPError as e:
         try:
            body = e.read().decode('utf-8', errors='replace')
         except Exception:
            body = ''
         Logger.error(f"Dispatcher: HTTPError sending packet summary to {self.rest_endpoint}: HTTP {e.code}, response: {body}")
         return False
      except urllib.error.URLError as e:
         Logger.error(f"Dispatcher: URLError sending packet summary to {self.rest_endpoint}, error: {e}")
         return False
      except Exception as e:
         Logger.error(f"Dispatcher: Unexpected error sending packet summary to {self.rest_endpoint}: {e}")
         return False