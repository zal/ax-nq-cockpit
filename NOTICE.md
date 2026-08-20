# Notices

This content is produced in the scope of the _Aerospace-X_ project, funded by the German Federal Ministry for Economic Affairs and Energy (BMWE) under the funding code 13MX004A as part of the Manufacturing-X funding program.

## Licenses
All code files are distributed under the Apache 2.0 license. See [LICENSE](./LICENSE) for more information.

All non-code files are distributed under the Creative Commons Attribution 4.0 International license. See [LICENSE_non-code](./LICENSE_non-code) for more information.

## AI-Assisted Development
Parts of this codebase and documentation were developed with the assistance of Claude Code (Anthropic). All AI-assisted changes were reviewed by the project team before inclusion.

## Trademarks
The ZAL Center of Applied Aeronautical Research GmbH and Aerospace-X names and logos (including `docs/ZAL_Logo_DE_GmbH_4C.png` and `static/logo/zal_logo_transparent.svg`) are trademarks of their respective owners. All rights reserved. They are **not** covered by the Apache 2.0 or CC BY 4.0 licenses above and may not be used without permission of the trademark owners.

## Third-Party Content
There are third-party contents used by and shipped with this project with different licenses.

### Python Dependencies
| Dependency | License | Link |
|---|---|---|
| Flask | BSD-3-Clause | https://flask.palletsprojects.com |
| Requests | Apache-2.0 | https://requests.readthedocs.io |
| Eclipse BaSyx Python SDK (`basyx-python-sdk`) | MIT | https://github.com/eclipse-basyx/basyx-python-sdk |

### Services Run via Docker (not shipped, pulled as images)
| Service | License | Link |
|---|---|---|
| Eclipse BaSyx AAS Environment (`eclipsebasyx/aas-environment`) | MIT | https://github.com/eclipse-basyx/basyx-java-server-sdk |
| Eclipse BaSyx AAS Web UI (`eclipsebasyx/aas-gui`) | MIT | https://github.com/eclipse-basyx/basyx-aas-web-ui |
| Keycloak (`quay.io/keycloak/keycloak`) | Apache-2.0 | https://www.keycloak.org |

### Data Model
The AAS submodel templates in `assets/model/*.aas.json` are generated from the Aerospace-X SAMM aspect model `org.w3id.aerospace-x.data-product-model.eNQ` (Aerospace-X data-product-model repository).

The optional live transport integrates with the Eclipse Dataspace Components (EDC) connector (Apache-2.0, https://github.com/eclipse-edc/Connector), which is not shipped with this repository.
