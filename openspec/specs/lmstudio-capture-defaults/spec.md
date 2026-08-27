# lmstudio-capture-defaults Specification

## Purpose
Prevent local LM Studio proxy mode from persisting sensitive prompts, responses, headers, and credentials unless the operator deliberately enables payload capture.

## Requirements

### Requirement: LM Studio payload capture SHALL be opt-in

The LM Studio forwarder SHALL disable request and response payload capture when its capture setting is absent, blank, invalid, or false. The safe default SHALL not create capture JSONL files or payload-bearing forwarder log files.

#### Scenario: Default forwarder start

- **WHEN** the forwarder starts without an explicit capture opt-in
- **THEN** payload capture SHALL be disabled
- **AND** no capture directory or capture file SHALL be created solely by startup

#### Scenario: Explicit capture opt-in

- **WHEN** the operator sets the documented capture opt-in to a recognized true value
- **THEN** the forwarder MAY create its capture files and preserve the existing capture workflow
- **AND** startup output SHALL clearly indicate that capture is enabled

#### Scenario: Invalid capture setting

- **WHEN** the capture setting contains an unrecognized value
- **THEN** the forwarder SHALL treat it as disabled
- **AND** it SHALL not fall back to enabled capture

### Requirement: Capture paths SHALL be rooted and forwarding SHALL remain compatible

When capture is enabled, capture files SHALL be rooted relative to the NeverEndingQuest forwarder location rather than the caller's current working directory. Disabling capture SHALL not prevent request forwarding, response handling, or concise operational console output.

#### Scenario: Forwarding with capture disabled

- **WHEN** a valid LM Studio request passes through the forwarder with capture disabled
- **THEN** the request and response SHALL continue through the existing forwarding path
- **AND** no request or response body, header, authorization value, or credential SHALL be persisted by the forwarder

#### Scenario: Capture from alternate current directory

- **WHEN** capture is explicitly enabled while the forwarder is launched from another working directory
- **THEN** capture files SHALL be written beneath the documented project-local forwarder log directory
- **AND** they SHALL not be written to an arbitrary caller-selected current-directory path
