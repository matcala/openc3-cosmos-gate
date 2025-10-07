# targets/<YOUR_TARGET>/lib/dispatcher.rb
require 'uri'
require 'json'
require 'net/http'

module OpenC3
  # WRITE protocol: inspect/gate command packets and optionally populate SER_CMD
  class Dispatcher < Protocol
    # allow_empty_data follows COSMOS Protocol semantics (nil/true/false)
    def initialize(rest_endpoint, keycloak_identity = nil, allow_empty_data = nil)
      super(allow_empty_data)
      @rest_endpoint       = normalize_endpoint(rest_endpoint)
      @keycloak_identity   = keycloak_identity
      @last_response_bytes = nil
    end

    # ---- WRITE side ----
    # Called BEFORE encoding. Return the packet to continue, or :STOP / :DISCONNECT
    def write_packet(packet)
      keycloak_id = @keycloak_identity || 'unknown'
      pkt_name    = packet.packet_name
      tgt_name    = packet.target_name

      # Read CCSDS header items
      stream_id_item = packet.get_item('CCSDS_STREAMID')
      func_code_item = packet.get_item('CCSDS_FC')
      stream_id      = packet.read_item(stream_id_item)  # default :CONVERTED
      func_code      = packet.read_item(func_code_item)  # default :CONVERTED

      # Let NOOP pass through without remote check
      if func_code == 1
        Logger.info('Dispatcher: NOOP command; passing without dispatch')
        return packet
      end

      # Build JSON summary (must match your upstream service expectations)
      summary = {
        keycloak_id:   keycloak_id,
        target:        tgt_name,
        packet_name:   pkt_name,
        stream_id:     stream_id,
        function_code: func_code
      }
      summary_json = JSON.dump(summary)
      Logger.info("Dispatcher: Prepared JSON #{summary_json}")
      Logger.info("Dispatcher: POST -> #{@rest_endpoint}")

      # Call remote gate
      should_continue = dispatch_packet(summary_json)
      unless should_continue
        Logger.warn('Dispatcher: Gate denied or error; stopping pipeline')
        return :STOP  # COSMOS expects :STOP to halt write chain. :contentReference[oaicite:2]{index=2}
      end

      # Populate SER_CMD with raw response bytes (BLOCK field in command)
      begin
        resp = @last_response_bytes || ''.b
        Logger.info("Dispatcher: Writing SER_CMD with #{resp.bytesize} byte(s)")
        packet.write('SER_CMD', resp) # write into modeled field before encode
      rescue => e
        Logger.error("Dispatcher: Failed to set SER_CMD: #{e}")
        return :STOP
      end

      if @last_response_bytes
        Logger.info("Dispatcher: REST response bytes length=#{@last_response_bytes.bytesize}")
      end
      Logger.info("Dispatcher: OK for #{tgt_name} #{pkt_name}")
      packet
    end

    private

    # Normalize endpoint:
    # - add http:// if missing
    # - handle //host:port/path style
    # - ensure path begins with '/'
    def normalize_endpoint(raw)
      raise ArgumentError, 'rest_endpoint must be non-empty' if raw.nil? || raw.strip.empty?
      ep = raw.strip
      ep = ep.start_with?('//') ? "http:#{ep}" : "http://#{ep}" unless ep.include?('://')

      uri = URI.parse(ep)
      if uri.host && uri.path && !uri.path.empty? && !uri.path.start_with?('/')
        uri.path = "/#{uri.path}"
      end
      normalized = uri.to_s
      Logger.info("Dispatcher: Normalized REST endpoint to #{normalized}")
      normalized
    end

    # POST summary and cache raw response bytes for later use
    def dispatch_packet(summary_json)
      uri       = URI.parse(@rest_endpoint)
      http      = Net::HTTP.new(uri.host, uri.port)
      http.use_ssl = (uri.scheme == 'https')

      req = Net::HTTP::Post.new(uri.request_uri)
      req['Content-Type'] = 'application/json'
      req.body = summary_json

      begin
        res = http.request(req)
        body = res.body ? res.body.b : ''.b
        @last_response_bytes = body
        ctype = res['Content-Type']

        if res.is_a?(Net::HTTPSuccess)
          Logger.info("Dispatcher: Success (#{res.code}), content-type=#{ctype}")
          true
        else
          preview =
            if body && !body.empty?
              begin
                tmp = body.dup
                tmp.force_encoding('UTF-8')
                tmp.valid_encoding? ? tmp[0, 1024] : "<#{body.bytesize} bytes>"
              rescue
                "<#{body.bytesize} bytes>"
              end
            else
              '<empty>'
            end
          Logger.error("Dispatcher: HTTP #{res.code} from #{@rest_endpoint}: #{preview}")
          false
        end
      rescue Net::HTTPError => e
        @last_response_bytes = e.respond_to?(:response) && e.response ? (e.response.body || '').b : nil
        body_str =
          begin
            b = @last_response_bytes || ''.b
            s = b.dup; s.force_encoding('UTF-8')
            s.valid_encoding? ? s : "<#{b.bytesize} bytes>"
          rescue
            "<#{@last_response_bytes ? @last_response_bytes.bytesize : 0} bytes>"
          end
        Logger.error("Dispatcher: HTTPError to #{@rest_endpoint}: #{e} body=#{body_str}")
        false
      rescue => e
        @last_response_bytes = nil
        Logger.error("Dispatcher: Unexpected error to #{@rest_endpoint}: #{e}")
        false
      end
    end
  end
end
