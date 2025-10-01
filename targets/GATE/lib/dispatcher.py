import json, urllib.request, urllib.error
from openc3.interfaces.protocols.protocol import Protocol
from openc3.config.config_parser import ConfigParser
from openc3.utilities.logger import Logger

# TODO:
# change to use packet native type
# it has to json and formatted prints
# forward json to decision container

class Dispatcher(Protocol):
   """
   A WRITE protocol that inspects the command Packet (pre-encode),
   logs/sends a JSON summary to an external service, then returns
   the same packet to continue the pipeline.
   """

   def __init__(self, test_arg, allow_empty_data=None):
      super().__init__(allow_empty_data)      
      self.arg = test_arg
      self.allow_empty_data = ConfigParser.handle_true_false_none(allow_empty_data)

   def write_packet(self, packet):
      """
      Called BEFORE encoding. Returning the Packet continues the write;
      returning self.STOP drops; returning self.DISCONNECT disconnects interface.
      """
      Logger.info(f"GateProtocol: write_packet called for target '{packet.target_name}' packet '{packet.packet_name}'")
      Logger.info(f"GateProtocol: test_arg = '{self.arg}'")

      # IMPORTANT: return the SAME packet to continue the pipeline unchanged
      return packet
