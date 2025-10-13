import urllib.parse
import json, urllib.request, urllib.error
from openc3.interfaces.protocols.protocol import Protocol
from openc3.config.config_parser import ConfigParser
from openc3.utilities.logger import Logger

class Dispatcher(Protocol):
   """
   A WRITE protocol that inspects the command Packet (pre-encode),
   logs/sends a JSON summary to an external service, then returns
   the packet to continue the command pipeline.
   """

   def __init__(self, rest_endpoint:str, keycloak_identity=None, allow_empty_data=None):
      super().__init__(allow_empty_data)
      # Normalize endpoints like "localhost:8080/authorize" -> "http://localhost:8080/authorize"
      self.rest_endpoint = self._normalize_endpoint(rest_endpoint)
      self.keycloak_identity = keycloak_identity
      self.allow_empty_data = ConfigParser.handle_true_false_none(allow_empty_data)
      # Store raw response bytes from REST calls (set on every dispatch)
      self.last_response_bytes = None

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
      keycloak_id = self.keycloak_identity or "unknown"
      pkt_name = packet.packet_name
      tgt_name = packet.target_name
      stream_id_item = packet.get_item("CCSDS_STREAMID")
      func_code_item = packet.get_item("CCSDS_FC")
      stream_id = packet.read_item(stream_id_item)
      func_code = packet.read_item(func_code_item)
      
      # Let NOOP commands pass through without enforcing policy
      if func_code == 1:
         Logger.info(f"Dispatcher: Received NOOP command (FUNCTION_CODE=1); passing through without dispatch")
         return packet

      # Build a summary dictionary (match Aranya Gate's lib.rs CMDSummary)
      summary = {
         "keycloak_id": keycloak_id,
         "target": tgt_name,
         "packet_name": pkt_name,
         "stream_id": stream_id,
         "function_code": func_code
      }
      
      # Serialize to JSON
      summary_json = json.dumps(summary).encode('utf-8')
      Logger.info(f"Dispatcher: Prepared packet summary JSON: {summary_json}")
      Logger.info(f"Dispatcher: Sending packet summary to {self.rest_endpoint}")

      # Dispatch the summary and decide whether to continue
      should_continue = self.dispatch_packet(summary_json, packet)
      if not should_continue:
         Logger.warn("Dispatcher: Halting command pipeline as dispatch_packet returned False")
         return 'STOP'

      # Use REST bytes to populate SER_CMD before returing packet for encoding CMD (BLOCK 1024 bits = 128 bytes)
      try:
         resp = self.last_response_bytes or b''
         Logger.info(f"Dispatcher: Writing SER_CMD with {len(resp)} bytes from REST response")
         packet.write("SER_CMD", resp)
      except Exception as e:
         Logger.error(f"Dispatcher: Failed to set SER_CMD on packet: {e}")
         return 'STOP'

      # Optionally log what we received from the REST API
      if self.last_response_bytes is not None:
         Logger.info(f"Dispatcher: REST response bytes length={len(self.last_response_bytes)}")
         summary["serialized_command_bytes"] = list(self.last_response_bytes)
         Logger.info(f"Final packet: {summary}")

      Logger.info("Dispatcher: Packet summary dispatched and updated successfully")
      # IMPORTANT: return the SAME packet SCHEMA to continue the pipeline unchanged.
      # Updating existing packet items is allowed
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
            # Read raw bytes so we can accept application/octet-stream without corrupting data
            body_bytes = response.read()
            self.last_response_bytes = body_bytes
            # Try to get a content type for logging
            try:
               content_type = response.headers.get_content_type()
            except Exception:
               content_type = None

            if 200 <= status < 300:
               # For binary payloads, don't log content to avoid noise
               if content_type == 'application/octet-stream':
                  Logger.info(f"Dispatcher: Sent packet summary to {self.rest_endpoint} (HTTP {status}), received {len(body_bytes)} bytes (octet-stream)")
               else:
                  # Best-effort decode for text responses
                  preview = ''
                  try:
                     preview = body_bytes.decode('utf-8', errors='replace')
                  except Exception:
                     preview = f"<{len(body_bytes)} bytes>"
                  Logger.info(f"Dispatcher: Sent packet summary to {self.rest_endpoint} (HTTP {status}), response: {preview}")
               return True
            else:
               # Non-success: log with safe preview
               preview = ''
               try:
                  preview = body_bytes.decode('utf-8', errors='replace')
               except Exception:
                  preview = f"<{len(body_bytes)} bytes>"
               Logger.error(f"Dispatcher: Non-success status from {self.rest_endpoint}: HTTP {status}, response: {preview}")
               return False
      except urllib.error.HTTPError as e:
         # Read and store error body bytes safely
         try:
            body_bytes = e.read()
         except Exception:
            body_bytes = b''
         self.last_response_bytes = body_bytes
         try:
            body = body_bytes.decode('utf-8', errors='replace')
         except Exception:
            body = f"<{len(body_bytes)} bytes>"
         Logger.error(f"Dispatcher: HTTPError sending packet summary to {self.rest_endpoint}: HTTP {e.code}, response: {body}")
         return False
      except urllib.error.URLError as e:
         self.last_response_bytes = None
         Logger.error(f"Dispatcher: URLError sending packet summary to {self.rest_endpoint}, error: {e}")
         return False
      except Exception as e:
         self.last_response_bytes = None
         Logger.error(f"Dispatcher: Unexpected error sending packet summary to {self.rest_endpoint}: {e}")
         return False