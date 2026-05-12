## Purpose

Define the Toolkit Module Builder GUI integration for downloading the generated Homebrewery adventure markdown file. This provides a one-click path for facilitators to obtain a formatted adventure document from any module.

## Requirements

### Requirement: SHALL expose an API endpoint for adventure markdown download

The web interface SHALL expose `GET /api/toolkit/modules/<slug>/adventure.md` that returns the generated Homebrewery V3 adventure markdown.

#### Scenario: Successful adventure download

**Given** a valid module slug with accessible module data
**When** `GET /api/toolkit/modules/The_Ancients_Lab/adventure.md` is requested
**Then** the response SHALL have Content-Type `text/markdown` or `text/plain` and contain a complete Homebrewery V3 adventure document

#### Scenario: Invalid module slug

**Given** a module slug that does not correspond to an existing module
**When** `GET /api/toolkit/modules/nonexistent/adventure.md` is requested
**Then** the response SHALL return HTTP 404 with a descriptive error

### Requirement: SHALL add [Download Adventure] button to Toolkit sidebar

The Module Builder GUI SHALL display a `[Download Adventure]` button in the module action sidebar when a module is selected.

#### Scenario: Button visible for selected module

**Given** a module is selected in the Module Builder
**When** the sidebar renders
**Then** a `[Download Adventure]` button SHALL be visible among the module action buttons

#### Scenario: Button triggers file download

**Given** the `[Download Adventure]` button is clicked
**When** the adventure markdown is generated
**Then** the browser SHALL trigger a file download of the `.md` file

### Requirement: SHALL set Content-Disposition for file download

The API response SHALL include `Content-Disposition: attachment; filename="<slug>_adventure.md"` so the browser treats the response as a downloadable file rather than displaying it inline.

#### Scenario: Download filename

**Given** a request for the Ancients Lab adventure
**When** the response is sent
**Then** the Content-Disposition header SHALL suggest filename `The_Ancients_Lab_adventure.md`

### Requirement: SHALL not require authentication

The adventure download endpoint SHALL be accessible without authentication, consistent with other toolkit module endpoints.

#### Scenario: No auth required

**Given** an unauthenticated request to the adventure download endpoint
**When** the request is processed
**Then** the endpoint SHALL return content without redirecting to a login page

### Requirement: SHALL handle generation errors with HTTP 500

If the adventure writer encounters an error during generation (e.g., corrupted module data), the endpoint SHALL return HTTP 500 with a descriptive error message.

#### Scenario: Generation failure

**Given** module data that causes the writer to fail
**When** the adventure download is requested
**Then** the response SHALL return HTTP 500 and the error SHALL be logged
