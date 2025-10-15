# Aranya-enabled Telecommand Gate for OpenC3 COSMOS

This plugin inserts an Aranya gate into the COSMOS command path, so you can enforce an Aranya policy for fine-grained control of which commands a user can send to a target.

> Tested on Apple Silicon macOS. Linux should behave similarly. Aranya does not support Windows. Running this on Windows would require additional reconfiguration. If you make it work on Windows, please let us know.

## Prerequisites

1. [Docker Desktop](https://docs.docker.com/get-started/get-docker/) or a Docker engine with Docker Compose
2. An OpenC3 COSMOS deployment, see the [installation guide](https://docs.openc3.com/docs/getting-started/installation)
3. Access to the COSMOS CLI, or the prebuilt gem `openc3-cosmos-gate-1.0.0.gem`
4. [rustup](https://rustup.rs/)

If you feel lost at any point, see Helpers at the end of this document.

## Components

This plugin is one of four pieces that simulate an operator sending telecommands via COSMOS.

- **OpenC3 COSMOS**
  - You can build this plugin with the COSMOS CLI, or install the prebuilt gem from the Admin portal.
  - Update `docker-compose.yaml` to allow inbound UDP into the `openc3-operator` container. Under `ports`, add:

    ```yaml
    - "127.0.0.1:6201:6201/udp"
    ```

- **Aranya cosmos-gate instance**
  - Exposes a REST API and evaluates outgoing telecommands from this plugin’s dispatcher against an Aranya policy.
  - Use the [cosmos-gate example README](https://github.com/matcala/aranya/tree/d3c1cd841aba6d64c52d5a0f50637945d045ac87/examples/rust/cosmos-gate) for setup.
<!-- TODO: update link and remove permalink -->

- **Target application**
  - A simple Python “satellite” app in Docker, located in the `tools` directory.
  - Exposes UDP 6200 to receive COSMOS commands.

- **This COSMOS plugin**
  - Routes telecommands through a custom WRITE protocol to the dispatcher, which posts to the Aranya gate.

### Command Flow

When a user sends a command processed by the Aranya gate, the flow is:

![Command sequence diagram showing COSMOS → Dispatcher → Aranya gate → COSMOS → Target](cmd_sequence_diagram.png)

## Configuration

The following parameters must align across components. Defaults in this repo should work without changes.

| Setting         | Description                                                                                           | Where it is used                 | Default                      |
|-----------------|-------------------------------------------------------------------------------------------------------|----------------------------------|------------------------------|
| `CMD port`      | UDP port where COSMOS sends command packets, must match the target’s listening port                   | COSMOS interface, target app     | 6200                         |
| `TLM port`      | UDP port where COSMOS listens for telemetry, target sends telemetry here                              | COSMOS interface, target app     | 6201                         |
| `rest_endpoint` | URL where the dispatcher posts the command packet to the Aranya gate                                  | Dispatcher configuration         | `http://host.docker.internal:8080` |
| Docker host     | Hostname used by containers to reach the host loopback                                                | Dispatcher, Aranya gate          | `host.docker.internal`       |

> `host.docker.internal` routes from a container to the host loopback on macOS and Windows, for Linux you may need to map the host IP or use an alternate approach if the default does not resolve.

## Build and Install the Plugin

1. Verify COSMOS is running by visiting [http://localhost:2900/](http://localhost:2900/).
2. Build this plugin with the COSMOS CLI to produce a `.gem`, or use the provided `openc3-cosmos-gate-1.0.0.gem`.

    ```bash
    openc3.sh cli rake build VERSION=X.X.X  # e.g., 2.0.0
    ```
3. Install the plugin in COSMOS:
   - Open the Admin Console.
   - Click **Install From File**, select the `.gem` you built, or the prebuilt one.
4. Verify in CmdTlmServer:
   - Interface `GATE_INT` appears and shows **CONNECTED**.
   - Target `GATE` routes telecommands and telemetry through `GATE_INT`.

### Custom WRITE Protocol

This plugin uses a custom WRITE protocol to route telecommands via the dispatcher:
```
  PROTOCOL WRITE <%= _target_name %>/lib/dispatcher.py <%= rest_endpoint %>
```

COSMOS executes `dispatcher.py` for each telecommand sent through `GATE_INT`. The first and only argument, `<%= rest_endpoint %>`, is passed to the script and used for the POST request to the Aranya gate API.

You can learn more about [custom COSMOS protocols here](https://docs.openc3.com/docs/configuration/protocols#custom-protocols).

## Running the Demo

1. **Start the mock target container**

    - Build the container image:

      ```bash
      cd tools
      docker build -t target .
      ```
    - And run it:

      ```bash
      docker run --rm --name target -p 6200:6200/udp target:latest
      ```
   - The Python app emits telemetry every second to the configured UDP port as defined in `openc3-cosmos-gate/targets/GATE/cmd_tlm/tlm.txt`.
   - In the CmdTlmServer view, observe `rx bytes` and `tlm pkts` increase every second.
   - Use the Packet Viewer tool to inspect inbound telemetry.

2. **Run the Aranya gate**
   - Follow the [example README](https://github.com/matcala/aranya/tree/d3c1cd841aba6d64c52d5a0f50637945d045ac87/examples/rust/cosmos-gate).
   - Ensure the REST endpoint matches the dispatcher configuration.
   <!-- update link -->

3. **Test the integration**
   - Open the Command Sender in COSMOS.
   - Two telecommands are defined for the `GATE` target:
     - `NOOP`, the dispatcher skips the Aranya gate for this command, check CmdTlmServer logs.
     - `ARANYA_EP_EXP1`, CmdTlmServer logs should show the dispatcher posting the packet to the Aranya gate. The Aranya gate logs should show a received packet. If the policy allows, the gate returns a serialized command, the dispatcher inserts it into the `SER_CMD` field, then the packet is sent to the mock target, which logs receipt.

> The dispatcher behavior is keyed off the CCSDS function code field. Feel free to modify the dispatcher script to adapt behavior.

## Troubleshooting

- **`GATE_INT` not CONNECTED**
  - Recheck the `docker-compose.yaml` port mapping for `openc3-operator`.
  - Confirm the target container is listening on the expected UDP port.
- **Aranya gate unreachable**
  - Verify `rest_endpoint` resolves from inside the `openc3-operator` container.
  - For Linux hosts, replace `host.docker.internal` with your host IP and update both dispatcher and gate configs.
- **No telemetry in Packet Viewer**
  - Make sure the TLM port in COSMOS matches the target’s telemetry destination.
  - Confirm the target is running and emitting once per second.

## Helpers

- [What is Aranya?](https://aranya-project.github.io/)
- [OpenC3 COSMOS, Getting Started](https://docs.openc3.com/docs/getting-started/installation)
- [OpenC3 COSMOS, Plugins](https://docs.openc3.com/docs/configuration/plugins)
- [OpenC3 COSMOS, Custom Protocols](https://docs.openc3.com/docs/configuration/protocols#custom-protocols)
